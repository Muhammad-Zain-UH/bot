"""Backtest runner.

Executes a replay and writes results to ``backtest_results/<run>/``:

* ``trades.jsonl``   -- one record per simulated trade
* ``metrics.json``   -- descriptive statistics
* ``manifest.json``  -- data source, date range, and **every execution assumption**

The manifest exists so no result can be read without its assumptions. A P&L
figure means nothing without the spread, the intrabar policy and the position
size that produced it.

Reports measurements only. It does not rank, score, or draw a forward-looking
conclusion, and no such interpretation should be added to it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backtest.metrics import BacktestMetrics, compute_metrics
from backtest.replay_engine import DEFAULT_BAR_COUNTS, ReplayConfig, ReplayEngine
from core.safety import assert_live_trading_disabled
from core.symbols import XAUUSD_2DIGIT, SymbolSpecification
from core.types import Timeframe
from core.units import Pips
from data.dataset import HistoricalDataset
from data.replay_feed import DEFAULT_REPLAY_SPREAD_PIPS, ReplayFeed
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import DEFAULT_SIMULATED_VOLUME, PaperBroker

__all__ = ["RunArtifacts", "format_report", "run_backtest"]

DEFAULT_RESULTS_DIR = Path("backtest_results")


class RunArtifacts:
    """Paths and objects produced by one run."""

    __slots__ = ("directory", "metrics", "manifest", "result")

    def __init__(self, directory: Path, metrics: BacktestMetrics, manifest: dict, result) -> None:  # noqa: ANN001
        self.directory = directory
        self.metrics = metrics
        self.manifest = manifest
        self.result = result


def run_backtest(
    dataset: HistoricalDataset,
    spec: SymbolSpecification = XAUUSD_2DIGIT,
    *,
    driving_timeframe: Timeframe = Timeframe.M5,
    spread_pips: float = DEFAULT_REPLAY_SPREAD_PIPS,
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
    volume: float = DEFAULT_SIMULATED_VOLUME,
    max_open_positions: int = 3,
    start: datetime | None = None,
    end: datetime | None = None,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    run_name: str | None = None,
    data_source: str = "unspecified",
    strategy=None,  # noqa: ANN001
    progress: bool = True,
) -> RunArtifacts:
    """Run one replay and persist its artifacts.

    Args:
        dataset: Validated historical data.
        spec: Broker symbol specification.
        driving_timeframe: Timeframe whose closes trigger decisions.
        spread_pips: Assumed spread.
        intrabar_policy: Ambiguous-bar resolution policy.
        volume: Fixed simulated size in lots.
        max_open_positions: Concurrency cap.
        start: Optional first decision instant.
        end: Optional last decision instant.
        results_dir: Root output directory.
        run_name: Subdirectory name; defaults to a UTC timestamp.
        data_source: Free-text provenance recorded in the manifest.
        strategy: Strategy object; defaults to ``main_production``.
        progress: Print progress while running.

    Returns:
        A :class:`RunArtifacts`.
    """
    assert_live_trading_disabled()

    feed = ReplayFeed(dataset, spread_pips=spread_pips)
    fill_model = FillModel(spread=Pips(spread_pips))
    broker = PaperBroker(
        spec, fill_model=fill_model, intrabar_policy=intrabar_policy,
        max_open_positions=max_open_positions,
    )
    config = ReplayConfig(
        driving_timeframe=driving_timeframe,
        start=start, end=end, volume=volume,
        max_open_positions=max_open_positions,
        bar_counts=dict(DEFAULT_BAR_COUNTS),
        progress_every=2_000 if progress else 0,
    )
    engine = ReplayEngine(feed, broker, spec, config, strategy=strategy)

    started = time.time()

    def _on_progress(index: int, moment: datetime) -> None:
        print(f"  ... decision {index:>7,} at {moment.isoformat()}", flush=True)

    result = engine.run(on_progress=_on_progress if progress else None)
    elapsed = time.time() - started

    metrics = compute_metrics(
        result.ledger.trades,
        total_signals=result.signals,
        rejected_orders=len(result.ledger.rejections),
    )

    coverage = {}
    for timeframe in dataset.timeframes:
        first, last = dataset.coverage(timeframe)
        coverage[timeframe.value] = {
            "bars": int(len(dataset.frame(timeframe))),
            "first": str(first),
            "last": str(last),
            "derived_from_m1": timeframe in dataset.derived,
        }

    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "data_source": data_source,
        "symbol": dataset.symbol,
        "coverage": coverage,
        "driving_timeframe": driving_timeframe.value,
        "bar_counts": {tf.value: n for tf, n in DEFAULT_BAR_COUNTS.items()},
        "decisions": result.decisions,
        "signals": result.signals,
        "strategy_errors": result.errors,
        "first_decision": (
            result.first_decision_time.isoformat() if result.first_decision_time else None
        ),
        "last_decision": (
            result.last_decision_time.isoformat() if result.last_decision_time else None
        ),
        "execution_assumptions": {
            **fill_model.describe(),
            "intrabar_policy": intrabar_policy.value,
            "simulated_volume_lots": volume,
            "max_open_positions": max_open_positions,
            "position_sizing_note": (
                "FIXED size. risk_manager is NOT used: it has a known ~10x contract-size "
                "defect (PHASE_2_ISSUES R1) that Phase 2A must not fix. Currency P&L is "
                "therefore an artefact of this fixed size; R-multiple is the "
                "size-independent measure."
            ),
        },
        "live_trading_enabled": False,
    }

    directory = Path(results_dir) / (
        run_name or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    )
    directory.mkdir(parents=True, exist_ok=True)
    result.ledger.write_jsonl(directory / "trades.jsonl")
    (directory / "metrics.json").write_text(
        json.dumps(metrics.to_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    if result.ledger.rejections:
        (directory / "rejections.jsonl").write_text(
            "\n".join(json.dumps(r, sort_keys=True, default=str)
                      for r in result.ledger.rejections),
            encoding="utf-8",
        )

    return RunArtifacts(directory, metrics, manifest, result)


def format_report(artifacts: RunArtifacts) -> str:
    """Render a run as the Phase 2A report block.

    Descriptive only. Contains no verdict, no ranking and no forward-looking
    statement, and none should be added.

    Args:
        artifacts: The run to describe.

    Returns:
        A plain-text report.
    """
    metrics = artifacts.metrics
    manifest = artifacts.manifest
    assumptions = manifest["execution_assumptions"]

    def _number(value, digits: int = 2, suffix: str = "") -> str:
        if value is None:
            return "n/a"
        return f"{value:.{digits}f}{suffix}"

    coverage_lines = [
        f"    {tf:<4} {info['bars']:>9,} bars  {info['first']} -> {info['last']}"
        f"{'  (derived from M1)' if info['derived_from_m1'] else ''}"
        for tf, info in manifest["coverage"].items()
    ]

    return "\n".join([
        "PHASE 2A REPLAY RESULT",
        "=" * 72,
        f"Data source:  {manifest['data_source']}",
        f"Symbol:       {manifest['symbol']}",
        "Coverage:",
        *coverage_lines,
        f"Driving TF:   {manifest['driving_timeframe']}",
        f"Decisions:    {manifest['decisions']:,}"
        f"   ({manifest['first_decision']} -> {manifest['last_decision']})",
        f"Elapsed:      {manifest['elapsed_seconds']}s",
        "",
        "COUNTS",
        f"  Signals generated:  {metrics.total_signals:,}",
        f"  Orders submitted:   {metrics.total_orders:,}",
        f"  Orders rejected:    {metrics.rejected_orders:,}",
        f"  Positions filled:   {metrics.total_trades:,}",
        f"  Completed trades:   {metrics.completed_trades:,}",
        f"  Open at end:        {metrics.open_at_end:,}  (excluded from statistics)",
        f"  Strategy errors:    {manifest['strategy_errors']:,}",
        "",
        "OUTCOMES",
        f"  Wins:     {metrics.wins:,}",
        f"  Losses:   {metrics.losses:,}",
        f"  Breakeven:{metrics.breakeven:,}",
        f"  Win rate: {_number(metrics.win_rate, 4)}",
        "",
        "RESULT (currency figures are artefacts of the fixed 0.01-lot size)",
        f"  Gross P&L:      {_number(metrics.gross_pnl)}",
        f"  Net P&L:        {_number(metrics.net_pnl)}",
        f"  Commission:     {_number(metrics.total_commission)}",
        f"  Average win:    {_number(metrics.average_win)}",
        f"  Average loss:   {_number(metrics.average_loss)}",
        f"  Expectancy:     {_number(metrics.expectancy)}",
        f"  Expectancy (R): {_number(metrics.expectancy_r, 4)}",
        f"  Average R:      {_number(metrics.average_r, 4)}",
        f"  Profit factor:  {_number(metrics.profit_factor, 4)}",
        f"  Max drawdown:   {_number(metrics.max_drawdown)}",
        f"  Max drawdown R: {_number(metrics.max_drawdown_r, 4)}",
        f"  Max consec wins:   {metrics.max_consecutive_wins}",
        f"  Max consec losses: {metrics.max_consecutive_losses}",
        f"  Avg bars held:     {_number(metrics.average_bars_held, 1)}",
        "",
        "AMBIGUITY",
        f"  Ambiguous exits: {metrics.ambiguous_exits:,} "
        f"({_number(metrics.ambiguous_exit_fraction, 4)} of completed trades)",
        "  An ambiguous bar contained both stop and target; OHLC cannot say which",
        "  came first, so the policy below decided it.",
        "",
        "BREAKDOWNS",
        f"  By outcome:   {metrics.by_outcome}",
        f"  By direction: {metrics.by_direction}",
        f"  By regime:    {metrics.by_regime}",
        f"  By setup:     {metrics.by_setup}",
        "",
        "EXECUTION ASSUMPTIONS",
        f"  Spread:      {assumptions['spread_pips']} pips (ASSUMED - no historical series)",
        f"  Slippage:    {assumptions['slippage_pips']} pips",
        f"  Commission:  {assumptions['commission_per_lot']} per lot",
        f"  Entry:       {assumptions['entry_timing']}",
        f"  Intrabar:    {assumptions['intrabar_policy']}",
        f"  Volume:      {assumptions['simulated_volume_lots']} lots (FIXED)",
        f"  Max open:    {assumptions['max_open_positions']}",
        "",
        f"Artifacts: {artifacts.directory}",
        "=" * 72,
        "These are descriptive measurements of one dataset under the assumptions",
        "above. They are not evidence of future performance.",
    ])


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Run a deterministic replay backtest.")
    parser.add_argument("--dataset", required=True, help="directory of <SYMBOL>_<TF>.csv files")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--spread-pips", type=float, default=DEFAULT_REPLAY_SPREAD_PIPS)
    parser.add_argument("--volume", type=float, default=DEFAULT_SIMULATED_VOLUME)
    parser.add_argument(
        "--intrabar", default=IntrabarPolicy.CONSERVATIVE.value,
        choices=[policy.value for policy in IntrabarPolicy],
    )
    parser.add_argument("--out", default=str(DEFAULT_RESULTS_DIR))
    arguments = parser.parse_args(argv)

    try:
        dataset = HistoricalDataset.from_directory(arguments.dataset, arguments.symbol)
    except FileNotFoundError as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    artifacts = run_backtest(
        dataset,
        spread_pips=arguments.spread_pips,
        volume=arguments.volume,
        intrabar_policy=IntrabarPolicy(arguments.intrabar),
        results_dir=Path(arguments.out),
        data_source=str(arguments.dataset),
    )
    print(format_report(artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
