"""Immutable baseline runs over real historical data.

Produces a versioned, hashable record of what the **unmodified** strategy did on
a specific dataset under specific execution assumptions. The point is that the
run can be reproduced exactly and compared against later runs once defects are
fixed -- so the artifacts are written once, into a directory named after the
baseline id, and never overwritten.

Reports descriptive measurements only. Nothing here ranks, scores or judges a
strategy, and no forward-looking statement should be added to it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from backtest.ledger import TradeLedger, TradeOutcome
from backtest.metrics import BacktestMetrics, compute_metrics
from backtest.replay_engine import DEFAULT_BAR_COUNTS, ReplayConfig, ReplayEngine
from core.symbols import SymbolSpecification
from core.types import Timeframe
from core.units import Pips
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import DEFAULT_SIMULATED_VOLUME, PaperBroker

__all__ = [
    "BaselineArtifacts",
    "PRODUCTION_LOG_NAMES",
    "assert_logs_are_redirected",
    "dataset_fingerprint",
    "decision_stream_fingerprint",
    "run_baseline",
    "spec_from_broker_metadata",
    "write_artifacts",
]

ENTRY_LAYERS = (
    "L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY",
    "L5_SWEEP", "L6_POI", "L7_CONFIDENCE", "L8_ENTRY",
)

# Block labels the strategy emits, mapped to the layer they belong to, so the
# funnel counts variants (L5_SWEEP_WAIT, L3_PULLBACK_MOMENTUM, ...) correctly.
_BLOCK_TO_LAYER = {
    "DAILY_LIMIT": "L0_GATES",
    "L1_BIAS": "L1_BIAS",
    "L2_STRUCTURE": "L2_STRUCTURE",
    "L3_PULLBACK": "L3_PULLBACK",
    "L4_LIQUIDITY": "L4_LIQUIDITY",
    "L5_SWEEP": "L5_SWEEP",
    "L5_SWEEP_WAIT": "L5_SWEEP",
    "L5_SWEEP_DIRECTION": "L5_SWEEP",
    "L6_POI": "L6_POI",
    "L7_CONFIDENCE": "L7_CONFIDENCE",
    "L8_ENTRY": "L8_ENTRY",
    "ERROR": "ERROR",
}


@dataclass(slots=True)
class BaselineArtifacts:
    """Everything one baseline run produced."""

    baseline_id: str
    manifest: dict[str, Any]
    dataset_manifest: dict[str, Any]
    metrics: BacktestMetrics
    ledger: TradeLedger
    decision_statistics: dict[str, Any]
    layer_funnel: dict[str, Any]
    regime_statistics: dict[str, Any]
    exit_statistics: dict[str, Any]
    defect_observations: dict[str, Any]
    decisions_fingerprint: str
    run_fingerprint: str
    directory: Path | None = None
    snapshots: list = field(default_factory=list)


def decision_stream_fingerprint(snapshots: list) -> str:
    """Return a stable hash of the ordered decision stream.

    This exists because :data:`BaselineArtifacts.run_fingerprint` alone cannot
    demonstrate that a replay repeated. That hash covers the dataset, the ledger
    and the metrics -- and on a run that produced no trades the ledger is empty
    and every metric is ``None``, so it collapses to a value any zero-trade run
    over the same data would produce, whatever the strategy decided along the
    way. Hashing the decisions themselves is what makes a repeat check
    meaningful: every decision must agree one by one, not merely in total.

    Hashed per decision, in replay order: the instant, the regime, the signal
    type, the side, the layers cleared, the layer that blocked, and the
    strategy's stated reason. Prices are excluded -- they are a function of the
    dataset, which is fingerprinted separately.

    Args:
        snapshots: Decision snapshots, in the order they were produced.

    Returns:
        A hex SHA-256 digest.
    """
    digest = hashlib.sha256()
    for snapshot in snapshots:
        digest.update("|".join((
            snapshot.replay_time.isoformat(),
            snapshot.regime,
            snapshot.signal_type,
            snapshot.direction,
            ",".join(snapshot.layers_passed),
            snapshot.layer_failed,
            snapshot.fail_reason,
        )).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def dataset_fingerprint(dataset: HistoricalDataset) -> tuple[str, dict[str, str]]:
    """Return a stable hash of the dataset and a per-timeframe breakdown.

    Hashes the actual bar values, not the file bytes, so the fingerprint is
    independent of CSV formatting and float repr.

    Args:
        dataset: The dataset to fingerprint.

    Returns:
        ``(overall_sha256, {timeframe: sha256})``.
    """
    per_timeframe: dict[str, str] = {}
    combined = hashlib.sha256()
    for timeframe in sorted(dataset.frames, key=lambda tf: tf.minutes):
        frame = dataset.frame(timeframe)
        digest = hashlib.sha256()
        digest.update(timeframe.value.encode())
        digest.update(
            pd.util.hash_pandas_object(frame, index=False).values.tobytes()
        )
        per_timeframe[timeframe.value] = digest.hexdigest()
        combined.update(digest.digest())
    return combined.hexdigest(), per_timeframe


def spec_from_broker_metadata(metadata: dict, pip_size: float = 0.10) -> SymbolSpecification:
    """Build a :class:`SymbolSpecification` from an exported broker metadata file.

    Uses the broker's **own** reported values rather than any reference constant.
    ``pip_size`` stays an explicit argument because MT5 does not report it.

    Args:
        metadata: Parsed ``broker_metadata.json``.
        pip_size: Pip size by market convention. ``0.10`` for XAUUSD.

    Returns:
        The specification.
    """
    return SymbolSpecification(
        symbol=metadata["symbol"],
        digits=int(metadata["digits"]),
        point=float(metadata["point"]),
        pip_size=pip_size,
        tick_size=float(metadata["trade_tick_size"]),
        tick_value=float(metadata["trade_tick_value"]),
        contract_size=float(metadata["trade_contract_size"]),
        volume_min=float(metadata["volume_min"]),
        volume_max=float(metadata["volume_max"]),
        volume_step=float(metadata["volume_step"]),
        base_currency=str(metadata.get("currency_base", "")),
        quote_currency=str(metadata.get("currency_profit", "")),
        account_currency=str(metadata.get("account_currency", "USD")),
    )


def _funnel(snapshots: list) -> dict[str, Any]:
    """Build the L0-L8 funnel from decision snapshots.

    Args:
        snapshots: Every decision snapshot from the run.

    Returns:
        Per-layer reached/blocked counts and percentages.
    """
    total = len(snapshots)
    blocked = Counter()
    for snapshot in snapshots:
        blocked[_BLOCK_TO_LAYER.get(snapshot.layer_failed, snapshot.layer_failed)] += 1

    # A layer counts as "reached" if the decision passed it, was BLOCKED at it,
    # or BYPASSED it. The bypass labels matter: MICRO_SCALP skips L3 and L6 via
    # "L3_PULLBACK_BYPASSED" / "L6_POI_BYPASSED", and REGIME_SCALP can pass L3 as
    # "L3_PULLBACK_MOMENTUM". Matching only the bare name undercounts those
    # layers and makes the funnel non-monotonic.
    reached: dict[str, int] = {}
    for layer in ENTRY_LAYERS:
        reached[layer] = sum(
            1 for snapshot in snapshots
            if any(passed == layer or passed.startswith(layer + "_")
                   for passed in snapshot.layers_passed)
            or _BLOCK_TO_LAYER.get(snapshot.layer_failed) == layer
        )

    return {
        "total_decisions": total,
        "blocked_at": dict(blocked.most_common()),
        "blocked_at_percent": {
            key: round(100.0 * value / total, 4) for key, value in blocked.most_common()
        } if total else {},
        "reached_layer": reached,
        "reached_layer_percent": {
            key: round(100.0 * value / total, 4) for key, value in reached.items()
        } if total else {},
        "blocked_reasons": _block_reasons(snapshots),
        "note": (
            "'reached' counts decisions that passed, were blocked at, or bypassed "
            "the layer. Variant labels (L5_SWEEP_WAIT, L3_PULLBACK_MOMENTUM, "
            "L6_POI_BYPASSED) are folded into their parent layer."
        ),
    }


def _normalise_reason(reason: str) -> str:
    """Strip varying numbers from a fail reason so reasons can be grouped."""
    collapsed = re.sub(r"-?\d+\.?\d*", "N", reason or "")
    return collapsed[:140]


def _block_reasons(snapshots: list) -> dict[str, dict[str, int]]:
    """Group the strategy's own fail reasons per blocking layer.

    This is the diagnostic that says *why* a layer rejected, not merely that it
    did. Numbers inside the message are collapsed so that otherwise-identical
    reasons aggregate.
    """
    grouped: dict[str, Counter] = {}
    for snapshot in snapshots:
        layer = _BLOCK_TO_LAYER.get(snapshot.layer_failed, snapshot.layer_failed)
        if not layer or layer == "None":
            continue
        grouped.setdefault(layer, Counter())[_normalise_reason(snapshot.fail_reason)] += 1
    return {
        layer: dict(counter.most_common(6)) for layer, counter in grouped.items()
    }


def _regime_statistics(snapshots: list) -> dict[str, Any]:
    """Count decisions and signals per regime."""
    total = len(snapshots)
    decisions = Counter(snapshot.regime for snapshot in snapshots)
    signals = Counter(
        snapshot.regime for snapshot in snapshots if snapshot.signal_type == "ENTRY_SIGNAL"
    )
    return {
        "decisions_by_regime": dict(decisions.most_common()),
        "decisions_by_regime_percent": {
            key: round(100.0 * value / total, 4) for key, value in decisions.most_common()
        } if total else {},
        "signals_by_regime": dict(signals.most_common()),
    }


def _exit_statistics(ledger: TradeLedger) -> dict[str, Any]:
    """Break exits down by reason, direction, regime and session."""
    trades = ledger.trades
    by_outcome = Counter(trade.outcome for trade in trades)
    by_direction = Counter(trade.side for trade in trades)

    def _cross(key) -> dict[str, dict[str, int]]:  # noqa: ANN001
        result: dict[str, dict[str, int]] = {}
        for trade in trades:
            bucket = result.setdefault(str(key(trade)) or "UNKNOWN", {})
            bucket[trade.outcome] = bucket.get(trade.outcome, 0) + 1
        return result

    return {
        "by_outcome": dict(by_outcome.most_common()),
        "by_direction": dict(by_direction.most_common()),
        "by_outcome_and_direction": _cross(lambda t: t.side),
        "by_outcome_and_regime": _cross(lambda t: t.regime),
        "by_outcome_and_session": _cross(lambda t: _session_of(t.decision_time)),
        "ambiguous_exits": sum(1 for trade in trades if trade.was_ambiguous_exit),
    }


def _side_performance(ledger: TradeLedger, side: str) -> dict[str, Any]:
    """Descriptive statistics for one direction."""
    trades = [
        trade for trade in ledger.trades
        if trade.side == side and trade.outcome_enum.is_completed_trade
    ]
    if not trades:
        return {"trades": 0}
    r_values = [trade.r_multiple for trade in trades if trade.r_multiple is not None]
    wins = [trade for trade in trades if trade.net_pnl > 0]
    losses = [trade for trade in trades if trade.net_pnl < 0]
    gross_profit = sum(trade.net_pnl for trade in wins)
    gross_loss = abs(sum(trade.net_pnl for trade in losses))
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 6),
        "net_pnl": round(sum(trade.net_pnl for trade in trades), 6),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss > 0 else None,
        "average_r": round(sum(r_values) / len(r_values), 6) if r_values else None,
        "median_r": round(median(r_values), 6) if r_values else None,
        "max_r": round(max(r_values), 6) if r_values else None,
        "min_r": round(min(r_values), 6) if r_values else None,
    }


_ATR_REASON = re.compile(r"H1 ATR too calm \(([\d.]+) < ([\d.]+) pips\)")

# Mirror of the tp_ratio literals assigned by ``entry_engine.detect_regime``
# (entry_engine.py:78, 90, 100, 109). Read-only: this module never feeds a value
# back into the strategy. ``tests/backtest/test_baseline_defects.py`` parses
# entry_engine's AST and fails if this mapping ever drifts from the source.
REGIME_TP_RATIO: dict[str, float] = {
    "MICRO_SCALP": 1.5,
    "REGIME_SCALP": 2.0,
    "INTRADAY_SWING": 3.0,
    "DEAD_CALM": 1.5,
}

# The threshold ``valid_rr`` compares against (entry_engine.py:409).
VALID_RR_THRESHOLD = 2.0


def _session_of(decision_time_iso: str) -> str:
    """Return the trading session for a decision timestamp.

    Derived post-hoc by calling the strategy's own ``get_current_session`` under
    the replay clock, so the label matches exactly what the strategy saw. It is a
    pure function of the instant, so computing it after the run is equivalent to
    recording it during one.

    Args:
        decision_time_iso: ISO timestamp of the decision.

    Returns:
        The session name, or ``"UNKNOWN"`` if it could not be determined.
    """
    try:
        import risk_manager

        from backtest.clock_patch import frozen_clock

        moment = pd.Timestamp(decision_time_iso).to_pydatetime()
        with frozen_clock(moment):
            return str(risk_manager.get_current_session())
    except Exception:
        return "UNKNOWN"


def _defect_observations(snapshots: list, ledger: TradeLedger) -> dict[str, Any]:
    """Collect evidence for known defects. **Records only; fixes nothing.**

    Every entry is measured from this run. Where a defect could not be measured
    from the captured data, it says so rather than guessing.
    """
    observations: dict[str, Any] = {}

    # E9 / E10 / Q3 -- regimes whose tp_ratio makes valid_rr unreachable.
    #
    # ``calculate_entry_levels`` derives the target as ``risk_distance * tp_ratio``
    # and then tests ``valid_rr = (reward / risk) >= 2.0``. Those two lines make
    # ``rr`` identically equal to ``tp_ratio``, so the test reads a config
    # constant. ``entry_triggered = raw_triggered and valid_rr`` is therefore
    # false for every decision in a ``tp_ratio < 2.0`` regime, whatever the price
    # action did. The sharpest measurement is not how many decisions occurred in
    # those regimes but how many *reached L8* there: for those, every other layer
    # passed and only the tautology blocked the entry.
    decisions = Counter(snapshot.regime for snapshot in snapshots)
    signals = Counter(
        snapshot.regime for snapshot in snapshots if snapshot.signal_type == "ENTRY_SIGNAL"
    )
    reached_l8 = Counter(
        snapshot.regime
        for snapshot in snapshots
        if snapshot.layer_failed == "L8_ENTRY"
        or any(passed.startswith("L8_") for passed in snapshot.layers_passed)
    )
    # A regime absent from the mirror is reported as unknown, never assumed
    # deadlocked -- a silent default would manufacture evidence for the defect.
    by_regime = {
        regime: {
            "tp_ratio": REGIME_TP_RATIO.get(regime),
            "valid_rr_reachable": (
                None if regime not in REGIME_TP_RATIO
                else REGIME_TP_RATIO[regime] >= VALID_RR_THRESHOLD
            ),
            "decisions": count,
            "reached_l8": reached_l8.get(regime, 0),
            "signals": signals.get(regime, 0),
        }
        for regime, count in decisions.most_common()
    }
    unreachable = {r: v for r, v in by_regime.items() if v["valid_rr_reachable"] is False}
    unknown = sorted(r for r, v in by_regime.items() if v["valid_rr_reachable"] is None)
    total_l8 = sum(reached_l8.values())
    blocked_by_tautology = sum(item["reached_l8"] for item in unreachable.values())
    observations["E9_E10_Q3_regime_rr_deadlock"] = {
        "defect": (
            "entry_engine.calculate_entry_levels sets take_profit = entry +/- "
            "risk_distance * tp_ratio, so reward_to_risk_ratio == tp_ratio "
            "identically; valid_rr = rr >= 2.0 therefore tests the regime constant "
            "and is unsatisfiable wherever tp_ratio < 2.0 (MICRO_SCALP, DEAD_CALM)."
        ),
        "occurrences": sum(item["decisions"] for item in unreachable.values()),
        "reached_l8_in_unreachable_regime": blocked_by_tautology,
        "reached_l8_total": total_l8,
        "share_of_l8_blocked_by_tautology": (
            round(blocked_by_tautology / total_l8, 6) if total_l8 else None
        ),
        "by_regime": by_regime,
        "regimes_not_in_mirror": unknown,
        "effect_on_baseline": (
            "Decisions in a tp_ratio<2.0 regime cannot reach an entry regardless of "
            "setup quality. Decisions that reached L8 there had already cleared "
            "every other gate, so the tautology alone accounts for them."
        ),
    }

    # Q1 / Q2 -- realised R versus the strategy's own reported RR.
    completed = [t for t in ledger.trades if t.outcome_enum.is_completed_trade]
    rr_rows = []
    for trade in completed:
        nominal = trade.metadata.get("strategy_rr_ratio")
        if nominal is None or trade.r_multiple is None:
            continue
        rr_rows.append({
            "trade_id": trade.trade_id,
            "decision_time": trade.decision_time,
            "strategy_rr_ratio": nominal,
            "realised_r": round(trade.r_multiple, 6),
            "difference": round(trade.r_multiple - float(nominal), 6),
            "strategy_entry_price": trade.metadata.get("strategy_entry_price"),
            "actual_fill_price": trade.entry_price,
        })
    observations["Q1_Q2_rr_vs_realised_r"] = {
        "defect": (
            "The strategy derives its target as risk x tp_ratio, so rr_ratio always "
            "equals the regime constant; and it prices risk against an entry it is "
            "never filled at."
        ),
        "occurrences": len(rr_rows),
        "distinct_reported_rr": sorted({row["strategy_rr_ratio"] for row in rr_rows}),
        "examples": rr_rows[:10],
        "effect_on_baseline": (
            "Realised R differs from the reported RR on every trade. The reported "
            "value cannot be used as an outcome measure."
        ),
    }

    # U9 -- the L2 gate compares dollars while the message says pips.
    atr_values: list[float] = []
    for snapshot in snapshots:
        match = _ATR_REASON.search(snapshot.fail_reason or "")
        if match:
            atr_values.append(float(match.group(1)))
    observations["U9_h1_atr_gate_units"] = {
        "defect": "main_production gates on h1_atr < 8.0 and reports it as 'pips'; the value is quote-currency dollars",
        "occurrences": len(atr_values),
        "observed_atr_min": round(min(atr_values), 4) if atr_values else None,
        "observed_atr_max": round(max(atr_values), 4) if atr_values else None,
        "threshold": 8.0,
        "effect_on_baseline": (
            "Blocks every decision whose H1 mean range is below $8.00. Because the "
            "threshold is absolute USD, its selectivity depends on the price level."
        ),
    }

    # G2 / U10 -- regime bands are absolute USD.
    observations["G2_U10_absolute_regime_bands"] = {
        "defect": "detect_regime classifies on absolute-USD M5 ATR bands (2.5/4.5/7.0)",
        "regime_distribution": dict(decisions.most_common()),
        "effect_on_baseline": (
            "Regime selection on this dataset is a function of gold's price level "
            "during the period, not of relative volatility."
        ),
    }

    # Q6 -- the stop buffer is applied in price units.
    observations["Q6_stop_buffer_units"] = {
        "defect": "_select_stop_anchor subtracts buffer_pips=3.0 directly from a price, giving a $3.00 buffer",
        "occurrences": len(completed),
        "note": (
            "Not separately measurable from the ledger without the sweep wick level, "
            "which the decision snapshot does not carry. Confirmed by inspection in "
            "Phase 2A.1 (sweep wick 2511.73 -> stop 2508.73)."
        ),
    }

    return observations


PRODUCTION_LOG_NAMES: tuple[str, ...] = (
    "trading_bot_production.log",
    "trading_bot_main.log",
    "trading_bot.log",
    "signal_log.csv",
    "signal_log_v2.csv",
    "signal_log_main_v2.csv",
)
"""Filenames that hold the permanent production record, at the repository root."""

REPO_ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_LOG_PATHS: frozenset[Path] = frozenset(
    (REPO_ROOT / name) for name in PRODUCTION_LOG_NAMES
)
"""The actual files a replay must not write to."""


def _is_production_record(target: str | Path) -> bool:
    """Return whether a path is one of the real production files.

    Compared by resolved path, not by filename. That distinction matters:
    ``tests/__init__.py`` redirects output into a temporary directory while
    keeping the original basenames, so matching on the name alone would reject
    a redirect that is doing exactly the right thing.

    Args:
        target: The path to classify.

    Returns:
        Whether it resolves to a production file at the repository root.
    """
    try:
        resolved = Path(target).resolve()
    except (OSError, ValueError):
        return False
    return resolved in PRODUCTION_LOG_PATHS


def assert_logs_are_redirected() -> None:
    """Refuse to run a baseline that would write to the production record.

    ``main_production`` builds a ``logging.FileHandler`` at module scope from
    ``TRADING_BOT_LOG_FILE``, defaulting to ``trading_bot_production.log`` in
    the repository root. A replay drives that module tens of thousands of times,
    so leaving the variable unset appends the whole run to the permanent log.

    That is the failure Phase 0.4 was built to prevent, and it happened during
    Phase 3A: baselines 001-004 appended roughly 8,900 diagnostic lines to
    ``trading_bot_production.log``. No fabricated signal entered the record --
    the run produced none -- but the record was still polluted by a simulation.

    Both the environment variable and any handler already installed are checked,
    because the module may have been imported before this is reached.

    Raises:
        RuntimeError: If a production file would receive output.
    """
    offenders: list[str] = []

    configured = os.getenv("TRADING_BOT_LOG_FILE")
    if configured is None:
        offenders.append(
            "TRADING_BOT_LOG_FILE is unset, so main_production defaults to "
            f"{REPO_ROOT / 'trading_bot_production.log'}"
        )
    elif _is_production_record(configured):
        offenders.append(f"TRADING_BOT_LOG_FILE points at {configured}")

    for logger in (logging.getLogger(), *(
        logging.getLogger(name) for name in list(logging.root.manager.loggerDict)
    )):
        for handler in getattr(logger, "handlers", ()):
            filename = getattr(handler, "baseFilename", None)
            if filename and _is_production_record(filename):
                offenders.append(f"logger {logger.name!r} writes to {filename}")

    if offenders:
        raise RuntimeError(
            "refusing to run a baseline that writes to the production record:"
            + "".join(chr(10) + "  " + line for line in sorted(set(offenders)))
            + chr(10)
            + "Point TRADING_BOT_LOG_FILE (and the other output paths) at a "
              "scratch location before importing main_production."
        )


def run_baseline(
    dataset: HistoricalDataset,
    spec: SymbolSpecification,
    *,
    baseline_id: str,
    git_commit: str,
    broker_metadata: dict,
    spread_pips: float = 2.0,
    spread_is_assumed: bool = True,
    slippage_pips: float = 0.0,
    commission_per_lot: float = 0.0,
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
    volume: float = DEFAULT_SIMULATED_VOLUME,
    max_open_positions: int = 3,
    driving_timeframe: Timeframe = Timeframe.M5,
    progress_every: int = 2000,
) -> BaselineArtifacts:
    """Run one immutable baseline over a real dataset.

    Args:
        dataset: Validated historical data.
        spec: Broker symbol specification, from the broker's own metadata.
        baseline_id: Identifier for this baseline; also the output directory name.
        git_commit: Commit the strategy was at.
        broker_metadata: Parsed ``broker_metadata.json``, recorded in the manifest.
        spread_pips: Spread assumption.
        spread_is_assumed: Whether the spread is an assumption rather than measured.
        slippage_pips: Slippage assumption.
        commission_per_lot: Commission assumption.
        intrabar_policy: Ambiguous-bar policy.
        volume: Fixed simulated size, in lots.
        max_open_positions: Concurrency cap.
        driving_timeframe: Timeframe whose closes trigger decisions.
        progress_every: Emit progress every N decisions.

    Returns:
        A :class:`BaselineArtifacts`.

    Raises:
        RuntimeError: If logging would reach the production record.
    """
    assert_logs_are_redirected()
    feed = ReplayFeed(dataset, spread_pips=spread_pips)
    fill_model = FillModel(
        spread=Pips(spread_pips),
        slippage=Pips(slippage_pips),
        commission_per_lot=commission_per_lot,
    )
    broker = PaperBroker(
        spec, fill_model=fill_model, intrabar_policy=intrabar_policy,
        max_open_positions=max_open_positions,
    )
    engine = ReplayEngine(
        feed, broker, spec,
        ReplayConfig(
            driving_timeframe=driving_timeframe,
            volume=volume,
            max_open_positions=max_open_positions,
            bar_counts=dict(DEFAULT_BAR_COUNTS),
            capture_all_snapshots=True,
            progress_every=progress_every,
        ),
        strategy=None,  # the real main_production module
    )

    started = time.time()

    def _on_progress(index: int, moment: datetime) -> None:
        print(f"  ... decision {index:>7,} at {moment.isoformat()}", flush=True)

    result = engine.run(on_progress=_on_progress if progress_every else None)
    elapsed = time.time() - started

    metrics = compute_metrics(
        result.ledger.trades, result.signals, len(result.ledger.rejections)
    )
    overall_hash, per_timeframe_hash = dataset_fingerprint(dataset)

    coverage = {}
    for timeframe in dataset.timeframes:
        first, last = dataset.coverage(timeframe)
        coverage[timeframe.value] = {
            "bars": int(len(dataset.frame(timeframe))),
            "first": str(first),
            "last": str(last),
            "derived_from_m1": timeframe in dataset.derived,
            "sha256": per_timeframe_hash[timeframe.value],
        }

    dataset_manifest = {
        "symbol": dataset.symbol,
        "dataset_sha256": overall_hash,
        "coverage": coverage,
        "all_native": not dataset.derived,
        "broker_metadata": broker_metadata,
    }

    manifest = {
        "baseline_id": baseline_id,
        "git_commit": git_commit,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_hash": overall_hash,
        "dataset_start": str(min(v["first"] for v in coverage.values())),
        "dataset_end": str(max(v["last"] for v in coverage.values())),
        "symbol": dataset.symbol,
        "broker": broker_metadata.get("broker"),
        "server": broker_metadata.get("server"),
        "timeframes": [tf.value for tf in dataset.timeframes],
        "strategy_version": git_commit,
        "strategy_entry_point": "main_production.analyze_entry",
        "driving_timeframe": driving_timeframe.value,
        "bar_counts": {tf.value: n for tf, n in DEFAULT_BAR_COUNTS.items()},
        "execution_assumptions": {
            **fill_model.describe(),
            "spread_source": "ASSUMED" if spread_is_assumed else "MEASURED",
            "intrabar_policy": intrabar_policy.value,
            "position_size_lots": volume,
            "position_sizing_note": (
                "FIXED size. risk_manager is NOT used: its ~10x contract-size defect "
                "(PHASE_2_ISSUES R1) would contaminate every currency figure. "
                "R-multiple is the size-independent measure."
            ),
            "max_open_positions": max_open_positions,
        },
        "symbol_specification_used": {
            "digits": spec.digits, "point": spec.point, "pip_size": spec.pip_size,
            "tick_size": spec.tick_size, "tick_value": spec.tick_value,
            "contract_size": spec.contract_size,
            "money_per_price_unit_per_lot": spec.money_per_price_unit(1.0),
        },
        "performance": {
            "elapsed_seconds": round(elapsed, 2),
            "decisions": result.decisions,
            "decisions_per_second": round(result.decisions / elapsed, 2) if elapsed else None,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "live_trading_enabled": False,
    }

    decision_statistics = {
        "total_decisions": result.decisions,
        "total_signals": result.signals,
        "strategy_errors": result.errors,
        "first_decision": result.first_decision_time.isoformat() if result.first_decision_time else None,
        "last_decision": result.last_decision_time.isoformat() if result.last_decision_time else None,
        "signals_by_side": dict(Counter(
            s.direction for s in result.snapshots if s.signal_type == "ENTRY_SIGNAL"
        )),
        "signal_type_counts": dict(Counter(s.signal_type for s in result.snapshots)),
    }

    decisions_hash = decision_stream_fingerprint(result.snapshots)
    run_fingerprint = hashlib.sha256(
        (overall_hash + decisions_hash + result.ledger.fingerprint() + json.dumps(
            metrics.to_dict(), sort_keys=True, default=str)).encode()
    ).hexdigest()

    return BaselineArtifacts(
        baseline_id=baseline_id,
        manifest=manifest,
        dataset_manifest=dataset_manifest,
        metrics=metrics,
        ledger=result.ledger,
        decision_statistics=decision_statistics,
        layer_funnel=_funnel(result.snapshots),
        regime_statistics=_regime_statistics(result.snapshots),
        exit_statistics=_exit_statistics(result.ledger),
        defect_observations=_defect_observations(result.snapshots, result.ledger),
        decisions_fingerprint=decisions_hash,
        run_fingerprint=run_fingerprint,
        snapshots=result.snapshots,
    )


def write_artifacts(artifacts: BaselineArtifacts, root: Path) -> Path:
    """Write a baseline's artifacts to an immutable, versioned directory.

    Args:
        artifacts: The run to persist.
        root: Parent directory for baselines.

    Returns:
        The directory written to.

    Raises:
        FileExistsError: If the baseline directory already exists. Baselines are
            immutable; overwriting one would destroy the reference point later
            runs are compared against.
    """
    directory = Path(root) / artifacts.baseline_id
    if directory.exists():
        raise FileExistsError(
            f"baseline {artifacts.baseline_id} already exists at {directory}. "
            f"Baselines are immutable -- choose a new id rather than overwriting."
        )
    directory.mkdir(parents=True)

    def _dump(name: str, payload: Any) -> None:
        (directory / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )

    _dump("manifest.json", artifacts.manifest)
    _dump("dataset_manifest.json", artifacts.dataset_manifest)
    _dump("metrics.json", artifacts.metrics.to_dict())
    _dump("decision_statistics.json", artifacts.decision_statistics)
    _dump("layer_funnel.json", artifacts.layer_funnel)
    _dump("regime_statistics.json", artifacts.regime_statistics)
    _dump("exit_statistics.json", artifacts.exit_statistics)
    _dump("defect_observations.json", artifacts.defect_observations)
    _dump("trade_ledger.json", [trade.to_dict() for trade in artifacts.ledger.trades])
    _dump("side_performance.json", {
        "BUY": _side_performance(artifacts.ledger, "BUY"),
        "SELL": _side_performance(artifacts.ledger, "SELL"),
    })

    if artifacts.ledger.trades:
        pd.DataFrame([t.to_dict() for t in artifacts.ledger.trades]).to_csv(
            directory / "trade_ledger.csv", index=False
        )
    if artifacts.ledger.rejections:
        _dump("rejections.json", artifacts.ledger.rejections)

    # Compact per-decision log. One line per decision so the funnel and the
    # block reasons can be re-derived or audited without re-running the replay.
    if artifacts.snapshots:
        with (directory / "decisions.jsonl").open("w", encoding="utf-8") as handle:
            for snapshot in artifacts.snapshots:
                handle.write(json.dumps({
                    "t": snapshot.replay_time.isoformat(),
                    "regime": snapshot.regime,
                    "side": snapshot.direction,
                    "signal": snapshot.signal_type,
                    "blocked": snapshot.layer_failed,
                    "passed": list(snapshot.layers_passed),
                    "reason": snapshot.fail_reason,
                    "price": snapshot.current_price,
                }, default=str) + "\n")

    (directory / "run_fingerprint.txt").write_text(
        f"run_fingerprint={artifacts.run_fingerprint}\n"
        f"dataset_sha256={artifacts.dataset_manifest['dataset_sha256']}\n"
        f"decisions_fingerprint={artifacts.decisions_fingerprint}\n"
        f"ledger_fingerprint={artifacts.ledger.fingerprint()}\n",
        encoding="utf-8",
    )
    artifacts.directory = directory
    return directory
