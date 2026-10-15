"""Replay engine tests.

Covers the wiring between feed, strategy and broker: that the engine requests
exactly the bar counts production uses, that it hands the strategy only what was
visible, that it captures the decision snapshot at decision time rather than
reconstructing it later, and that it never fills on a bar the strategy had
already seen.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

import pandas as pd

from backtest.replay_engine import (
    DEFAULT_BAR_COUNTS,
    DecisionSnapshot,
    ReplayConfig,
    ReplayEngine,
)
from core.symbols import XAUUSD_2DIGIT
from core.types import Timeframe
from data.replay_feed import ReplayFeed
from execution.paper_broker import PaperBroker
from tests.fixtures.market import SYNTHETIC_START, make_synthetic_dataset

SMALL_COUNTS = {
    Timeframe.H4: 20, Timeframe.H1: 20, Timeframe.M15: 20,
    Timeframe.M5: 20, Timeframe.M1: 20, Timeframe.D1: 2,
}


class _RecordingStrategy:
    """Captures exactly what the engine passed in, for inspection."""

    def __init__(self, signal_on_call: int | None = None) -> None:
        self.calls: list[dict] = []
        self.signal_on_call = signal_on_call

    def detect_regime(self, m5, m15, h1, current_spread=1.0):  # noqa: ANN001
        return {"regime": "REGIME_SCALP", "tp_ratio": 2.0, "m5_atr": 5.0,
                "current_spread": current_spread}

    def analyze_entry(self, h4, h1, m15, m5, m1, daily, current_price=0.0,
                      regime_info=None):  # noqa: ANN001
        self.calls.append({
            "frames": {"H4": h4, "H1": h1, "M15": m15, "M5": m5, "M1": m1, "D1": daily},
            "current_price": current_price,
            "regime_info": regime_info,
        })
        if self.signal_on_call is not None and len(self.calls) == self.signal_on_call:
            entry = float(m5["close"].iloc[-1])
            return {
                "signal_type": "ENTRY_SIGNAL", "direction": "BUY",
                "layers_passed": ["L1_BIAS"], "layer_failed": None,
                "entry_signal": {
                    "position_type": "BUY", "entry_price": entry,
                    "stop_loss": entry - 5.0, "take_profit": entry + 10.0,
                    "setup_type": "TEST", "entry_method": "TEST",
                },
            }
        return {"signal_type": "PRE_ENTRY", "direction": "BUY",
                "layers_passed": ["L1_BIAS"], "layer_failed": "L2_STRUCTURE",
                "fail_reason": "test", "entry_signal": None}


def _engine(strategy, counts=None, start=5_000, end=7_000, bars=9_000):
    dataset = make_synthetic_dataset(bars=bars)
    feed = ReplayFeed(dataset)
    broker = PaperBroker(XAUUSD_2DIGIT)
    config = ReplayConfig(
        driving_timeframe=Timeframe.M5,
        start=SYNTHETIC_START + timedelta(minutes=start),
        end=SYNTHETIC_START + timedelta(minutes=end),
        bar_counts=dict(counts or SMALL_COUNTS),
        capture_all_snapshots=True,
    )
    return ReplayEngine(feed, broker, XAUUSD_2DIGIT, config, strategy=strategy), feed, broker


class ProductionParityTests(unittest.TestCase):
    """The engine must ask for exactly what production asks for."""

    def test_default_bar_counts_match_main_production_config(self) -> None:
        import main_production

        config = main_production.CONFIG
        self.assertEqual(DEFAULT_BAR_COUNTS[Timeframe.H4], config["h4_candles_required"])
        self.assertEqual(DEFAULT_BAR_COUNTS[Timeframe.H1], config["h1_candles_required"])
        self.assertEqual(DEFAULT_BAR_COUNTS[Timeframe.M15], config["m15_candles_required"])
        self.assertEqual(DEFAULT_BAR_COUNTS[Timeframe.M5], config["m5_candles_required"])
        self.assertEqual(DEFAULT_BAR_COUNTS[Timeframe.M1], config["m1_candles_required"])

    def test_frames_match_the_production_column_contract(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        engine.run()
        self.assertGreater(len(strategy.calls), 0)
        for name, frame in strategy.calls[0]["frames"].items():
            with self.subTest(timeframe=name):
                self.assertEqual(
                    list(frame.columns),
                    ["time", "open", "high", "low", "close", "tick_volume"],
                )
                self.assertIsNotNone(frame["time"].dt.tz)

    def test_requested_counts_are_delivered(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        engine.run()
        frames = strategy.calls[0]["frames"]
        self.assertEqual(len(frames["M5"]), SMALL_COUNTS[Timeframe.M5])
        self.assertEqual(len(frames["H1"]), SMALL_COUNTS[Timeframe.H1])


class VisibilityTests(unittest.TestCase):
    """The strategy may never be handed a bar that had not closed."""

    def test_no_frame_contains_a_bar_closing_after_the_decision(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        result = engine.run()
        self.assertEqual(len(strategy.calls), len(result.snapshots))
        for call, snapshot in zip(strategy.calls, result.snapshots):
            for name, frame in call["frames"].items():
                timeframe = Timeframe[name]
                latest_close = frame["time"].iloc[-1] + timedelta(minutes=timeframe.minutes)
                self.assertLessEqual(
                    latest_close, pd.Timestamp(snapshot.replay_time),
                    f"{name} leaked a bar closing after {snapshot.replay_time}",
                )

    def test_higher_timeframes_lag_lower_ones(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        engine.run()
        frames = strategy.calls[-1]["frames"]
        self.assertLess(
            pd.Timestamp(frames["H1"]["time"].iloc[-1]),
            pd.Timestamp(frames["M1"]["time"].iloc[-1]),
        )


class SnapshotTests(unittest.TestCase):
    """Snapshots are captured at decision time, not reconstructed later."""

    def test_snapshot_records_the_decision(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        result = engine.run()
        snapshot = result.snapshots[0]
        self.assertIsInstance(snapshot, DecisionSnapshot)
        self.assertEqual(snapshot.regime, "REGIME_SCALP")
        self.assertEqual(snapshot.signal_type, "PRE_ENTRY")
        self.assertEqual(snapshot.layer_failed, "L2_STRUCTURE")

    def test_snapshot_reports_every_timeframe(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        result = engine.run()
        snapshot = result.snapshots[0]
        for timeframe in SMALL_COUNTS:
            self.assertIn(timeframe, snapshot.availability)

    def test_snapshot_description_is_inspectable(self) -> None:
        """The replay-integrity record required for debugging."""
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        text = engine.run().snapshots[0].describe()
        for token in ("replay_time", "H4", "H1", "M15", "M5", "M1", "D1",
                      "current_price", "spread", "regime", "signal"):
            self.assertIn(token, text)

    def test_snapshot_availability_never_exceeds_replay_time(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        for snapshot in engine.run().snapshots:
            for availability in snapshot.availability.values():
                if availability.latest_close_time is not None:
                    self.assertLessEqual(
                        availability.latest_close_time, pd.Timestamp(snapshot.replay_time)
                    )


class OrderSubmissionTests(unittest.TestCase):
    """Signals must fill on a later bar, and the chain must be recorded."""

    def test_signal_produces_a_position(self) -> None:
        strategy = _RecordingStrategy(signal_on_call=5)
        engine, _, broker = _engine(strategy)
        result = engine.run()
        self.assertEqual(result.signals, 1)
        self.assertGreaterEqual(
            len(broker.open_positions()) + len(broker.closed_positions()), 1
        )

    def test_fill_uses_a_bar_after_the_decision_bar(self) -> None:
        strategy = _RecordingStrategy(signal_on_call=5)
        engine, _, broker = _engine(strategy)
        engine.run()
        positions = broker.closed_positions() + broker.open_positions()
        position = positions[0]
        self.assertIsNotNone(position.fill)
        self.assertGreater(position.fill.entry_bar_time, position.fill.decision_bar_time)
        self.assertGreaterEqual(position.fill.entry_bar_time, position.fill.decision_time)

    def test_entry_fills_against_the_next_bars_open(self) -> None:
        """The fill reference must be the execution bar's open.

        Note this is asserted positively rather than as "not the decision
        close". The synthetic fixture is a gapless walk, so each bar's open
        equals the previous bar's close by construction and a negative
        assertion would fail even though the engine is behaving correctly.
        ``tests/execution/test_paper_broker.py`` covers the gapped case with
        explicit, discontinuous bars.
        """
        strategy = _RecordingStrategy(signal_on_call=5)
        engine, feed, broker = _engine(strategy)
        engine.run()
        position = (broker.closed_positions() + broker.open_positions())[0]
        execution_bar = feed.next_bar_after(
            Timeframe.M5, position.fill.decision_time
        )
        self.assertAlmostEqual(
            position.fill.reference_price, float(execution_bar["open"])
        )
        self.assertEqual(
            position.fill.entry_bar_time,
            pd.Timestamp(execution_bar["time"]).to_pydatetime(),
        )

    def test_signal_without_a_stop_is_rejected_not_traded(self) -> None:
        class NoStop(_RecordingStrategy):
            def analyze_entry(self, h4, h1, m15, m5, m1, daily,
                              current_price=0.0, regime_info=None):  # noqa: ANN001
                self.calls.append({"frames": {}, "current_price": current_price,
                                   "regime_info": regime_info})
                if len(self.calls) == 3:
                    return {"signal_type": "ENTRY_SIGNAL", "direction": "BUY",
                            "layers_passed": [], "layer_failed": None,
                            "entry_signal": {"position_type": "BUY",
                                             "entry_price": 2400.0, "stop_loss": 0}}
                return {"signal_type": "PRE_ENTRY", "direction": "BUY",
                        "layers_passed": [], "layer_failed": "X",
                        "fail_reason": "t", "entry_signal": None}

        strategy = NoStop()
        engine, _, broker = _engine(strategy)
        result = engine.run()
        self.assertEqual(len(broker.open_positions()), 0)
        self.assertGreaterEqual(len(result.ledger.rejections), 1)


class RunMechanicsTests(unittest.TestCase):
    def test_warmup_decisions_are_skipped_not_run_on_short_frames(self) -> None:
        """Production returns EMPTY frames when history is short; so do we."""
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy, start=0, end=3_000)
        result = engine.run()
        self.assertEqual(result.decisions, 0)
        self.assertEqual(len(strategy.calls), 0)

    def test_decisions_are_counted(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        result = engine.run()
        self.assertEqual(result.decisions, len(strategy.calls))
        self.assertGreater(result.decisions, 10)

    def test_decision_times_are_strictly_increasing(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        times = [s.replay_time for s in engine.run().snapshots]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_decision_times_fall_on_driving_bar_closes(self) -> None:
        strategy = _RecordingStrategy()
        engine, _, _ = _engine(strategy)
        for snapshot in engine.run().snapshots:
            self.assertEqual(snapshot.replay_time.minute % 5, 0)
            self.assertEqual(snapshot.replay_time.second, 0)

    def test_strategy_errors_are_counted_not_swallowed_silently(self) -> None:
        class Failing(_RecordingStrategy):
            def analyze_entry(self, *args, **kwargs):  # noqa: ANN002, ANN003
                self.calls.append({"frames": {}, "current_price": 0, "regime_info": None})
                return {"signal_type": "ERROR", "fail_reason": "boom",
                        "layers_passed": [], "layer_failed": "ERROR",
                        "direction": "", "entry_signal": None}

        engine, _, _ = _engine(Failing())
        result = engine.run()
        self.assertGreater(result.errors, 0)
        self.assertEqual(result.errors, result.decisions)


if __name__ == "__main__":
    unittest.main()
