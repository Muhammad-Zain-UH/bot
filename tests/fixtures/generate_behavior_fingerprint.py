"""Regenerate ``tests/fixtures/behavior_fingerprint.json`` (Phase 6P).

Read-only. Calls production functions under the replay clock and reads the frozen
``baseline_005`` decision stream. Writes nothing except the fingerprint.

    python tests/fixtures/generate_behavior_fingerprint.py

Runs for roughly 20 minutes: it recomputes regime, bias and H1 structure for all
15,735 decisions. It is **not** invoked by the test suite -- the tests assert
against the committed fingerprint and recompute only the cheap fields.

Scope caveat: ``blocked_at`` / ``signal_type`` / ``passed`` come from the frozen
stream, which was produced at commit ``7b702dd`` and predates U4. The
reconstructed fields (regime, session, bias, side, structure) are computed with
whatever code is checked out, and U4 did not touch any of them.
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import pandas as pd

from backtest.clock_patch import frozen_clock
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

import bias_engine
import entry_engine
import risk_manager
import structure_engine
from indicators import calculate_indicators

REPO_ROOT = Path(__file__).resolve().parents[2]
BAR_COUNTS = {
    Timeframe.D1: 10,
    Timeframe.H1: 60,
    Timeframe.H4: 100,
    Timeframe.M15: 50,
    Timeframe.M5: 100,
}


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def collect() -> list[dict]:
    dataset = HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD")
    feed = ReplayFeed(dataset, spread_pips=2.0)
    stream = REPO_ROOT / "baselines" / "baseline_005" / "decisions.jsonl"
    frozen = {
        row["t"]: row
        for row in (json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines())
    }

    records: list[dict] = []
    for raw_time in feed.decision_times(Timeframe.M5, None, None):
        key = pd.Timestamp(raw_time).isoformat()
        recorded = frozen.get(key)
        if recorded is None:
            continue
        moment = pd.Timestamp(raw_time).to_pydatetime()
        frames = {tf: feed.bars(tf, count, moment) for tf, count in BAR_COUNTS.items()}
        if any(len(frame) == 0 for frame in frames.values()):
            continue

        with frozen_clock(moment):
            regime_info = entry_engine.detect_regime(
                frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
                current_spread=2.0,
            )
            session = risk_manager.get_current_session()
            kill_zone = bool(entry_engine._within_kill_zone())

        regime = str(regime_info.get("regime"))
        uses_fast_bias = regime in ("MICRO_SCALP", "REGIME_SCALP")
        if uses_fast_bias:
            bias_result = bias_engine.get_fast_bias(
                calculate_indicators(frames[Timeframe.H1]) or {}, h1_data=frames[Timeframe.H1]
            )
        else:
            h4_indicators = calculate_indicators(frames[Timeframe.H4]) or {}
            h4_indicators["closes_2"] = [
                float(value) for value in frames[Timeframe.H4]["close"].tail(2).tolist()
            ]
            bias_result = bias_engine.get_h4_bias(
                h4_indicators, daily_data=frames[Timeframe.D1], h4_data=frames[Timeframe.H4]
            )

        bias = str(bias_result.get("bias"))
        initial_side = None if bias == "NEUTRAL" else ("BUY" if bias.upper() == "BULLISH" else "SELL")
        effective_side = recorded.get("side") or None

        structure_type = h1_close = swing_low = swing_high = None
        if initial_side:
            structure = structure_engine.get_h1_structure(frames[Timeframe.H1], bias)
            structure_type = str((structure or {}).get("structure_type"))
            h1_close = round(float(frames[Timeframe.H1].iloc[-1]["close"]), 6)
            low = (structure or {}).get("last_swing_low")
            high = (structure or {}).get("last_swing_high")
            swing_low = round(float(low), 6) if low is not None else None
            swing_high = round(float(high), 6) if high is not None else None

        records.append({
            "t": key,
            "regime": regime,
            "m5_atr": round(float(regime_info.get("m5_atr") or 0.0), 6),
            "session": session,
            "kill_zone": kill_zone,
            "bias_tf": "H1" if uses_fast_bias else "H4",
            "bias": bias,
            "bias_strength": round(float(bias_result.get("bias_strength") or 0.0), 6),
            "l1_initial_side": initial_side,
            "effective_side": effective_side,
            "reversed": bool(initial_side and effective_side and initial_side != effective_side),
            "bias_side_used_by_l3": initial_side,
            "l2_structure_type": structure_type,
            "h1_close": h1_close,
            "last_swing_low": swing_low,
            "last_swing_high": swing_high,
            "blocked": recorded.get("blocked"),
            "signal": recorded.get("signal"),
            "passed": recorded.get("passed") or [],
            "reason": recorded.get("reason", ""),
            "price": recorded.get("price"),
        })
        if len(records) % 2000 == 0:
            print(f"  {len(records)}", flush=True)
    return records


def summarise(records: list[dict]) -> dict:
    def tally(key):
        return dict(sorted(collections.Counter(str(row[key]) for row in records).items()))

    reversals = [row for row in records if row["reversed"]]
    sided = sum(1 for row in records if row["l1_initial_side"] and row["effective_side"])

    runs: list[int] = []
    previous = None
    length = 0
    for row in records:
        state = (
            (row["h1_close"], row["last_swing_high"], row["last_swing_low"])
            if row["reversed"] else None
        )
        if state is not None and state == previous:
            length += 1
        else:
            if length:
                runs.append(length)
            length = 1 if state is not None else 0
        previous = state
    if length:
        runs.append(length)

    l2_blocks = [row for row in records if row["blocked"] == "L2_STRUCTURE"]
    atr = pd.Series([row["m5_atr"] for row in records])
    strength = pd.Series([row["bias_strength"] for row in records])

    return {
        "decisions": len(records),
        "regime": tally("regime"),
        "session": tally("session"),
        "kill_zone_true": sum(1 for row in records if row["kill_zone"]),
        "bias_timeframe": tally("bias_tf"),
        "bias_label": tally("bias"),
        "l1_initial_side": tally("l1_initial_side"),
        "effective_side": tally("effective_side"),
        "l2_structure_type": tally("l2_structure_type"),
        "blocked_at": tally("blocked"),
        "signal_type": tally("signal"),
        "reversals": {
            "count": len(reversals),
            "pct_of_sided": round(100 * len(reversals) / sided, 4),
            "direction": dict(sorted(collections.Counter(
                f'{row["l1_initial_side"]}->{row["effective_side"]}' for row in reversals
            ).items())),
            "by_regime": dict(sorted(collections.Counter(row["regime"] for row in reversals).items())),
            "by_session": dict(sorted(collections.Counter(row["session"] for row in reversals).items())),
            "terminal_layer": dict(sorted(collections.Counter(
                str(row["blocked"]) for row in reversals
            ).items())),
            "distinct_h1_states": len({
                (row["h1_close"], row["last_swing_high"], row["last_swing_low"])
                for row in reversals
            }),
            "consecutive_runs": len(runs),
            "run_length": {
                "min": min(runs), "median": int(pd.Series(runs).median()), "max": max(runs)
            },
        },
        "side_state_matrix": dict(sorted(collections.Counter(
            f'L1={row["l1_initial_side"]}|EFF={row["effective_side"]}|L3={row["bias_side_used_by_l3"]}'
            for row in records
        ).items())),
        "l2_blocks": {
            "decisions": len(l2_blocks),
            "distinct_reasons": sorted({row["reason"] for row in l2_blocks}),
            "distinct_h1_states": len({(row["h1_close"], row["last_swing_high"]) for row in l2_blocks}),
        },
        "m5_atr": {
            "min": round(atr.min(), 4), "p25": round(atr.quantile(0.25), 4),
            "median": round(atr.median(), 4), "p75": round(atr.quantile(0.75), 4),
            "max": round(atr.max(), 4),
        },
        "bias_strength": {
            "min": round(strength.min(), 4), "median": round(strength.median(), 4),
            "max": round(strength.max(), 4),
        },
        "checksums": {
            "regime_session_side": _digest([
                [r["t"], r["regime"], r["session"], r["l1_initial_side"], r["effective_side"]]
                for r in records
            ]),
            "layer_outcome": _digest([[r["t"], str(r["blocked"]), r["signal"]] for r in records]),
            "reversal_set": _digest(sorted(row["t"] for row in reversals)),
            "full_record": _digest(records),
        },
    }


if __name__ == "__main__":
    collected = collect()
    print("records:", len(collected))
    target = REPO_ROOT / "tests" / "fixtures" / "behavior_fingerprint.json"
    target.write_text(
        json.dumps(summarise(collected), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("wrote", target)
