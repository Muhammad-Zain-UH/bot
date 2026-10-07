"""Integration-level leakage and determinism.

Critical requirements 4, 9 and 10. Phase 2A proved the *feed* cannot leak; these
tests prove the leakage guarantee survives all the way through the **real**
strategy, the broker and the ledger.

Test A  mutate every bar after the decision by +$500; the decision, signal,
        entry, SL and TP must be byte-identical
Test B  changing bars after the entry decision cannot alter the decision
Test C  future bars may decide the EXIT, but never the signal, entry, SL or TP
Test D  boundary: a bar closing exactly at T is visible, one a second later is not
"""

from __future__ import annotations

import unittest
from datetime import timedelta

import pandas as pd

from backtest.replay_engine import DEFAULT_BAR_COUNTS
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from data.timeframes import resample_from_m1
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import (
    SPREAD_PIPS,
    analyse_at,
    decision_instant,
    long_dataset,
    run_replay,
)

MUTATION = 500.0


def _mutate_after(dataset: HistoricalDataset, cutoff) -> HistoricalDataset:
    """Return a copy with every M1 bar opening at/after ``cutoff`` shifted up $500.

    Rebuilds the higher timeframes from the mutated M1 so the dataset stays
    internally consistent -- otherwise a test could fail for the wrong reason.
    """
    m1 = dataset.frame(Timeframe.M1).copy(deep=True)
    tail = m1["time"] >= pd.Timestamp(cutoff)
    for column in ("open", "high", "low", "close"):
        m1.loc[tail, column] = m1.loc[tail, column] + MUTATION
    frames = {Timeframe.M1: m1}
    for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
        frames[timeframe] = resample_from_m1(m1, timeframe)
    return HistoricalDataset(symbol=dataset.symbol, frames=frames)


class TestAFutureMutationTests(unittest.TestCase):
    """Test A: changing the future must not change the decision."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.moment = decision_instant()
        cls.original = long_dataset(Resolution.TARGET)
        cls.mutated = _mutate_after(cls.original, cls.moment)
        cls.baseline, _, _, _ = analyse_at(cls.original, cls.moment)
        cls.after, _, _, _ = analyse_at(cls.mutated, cls.moment)

    def test_the_mutation_is_material(self) -> None:
        """Guards the whole class against passing because nothing changed."""
        later = self.moment + timedelta(hours=1)
        original_feed = ReplayFeed(self.original, spread_pips=SPREAD_PIPS)
        mutated_feed = ReplayFeed(self.mutated, spread_pips=SPREAD_PIPS)
        self.assertNotAlmostEqual(
            original_feed.price_at(later), mutated_feed.price_at(later), places=2
        )

    def test_signal_type_unchanged(self) -> None:
        self.assertEqual(self.baseline["signal_type"], "ENTRY_SIGNAL")
        self.assertEqual(self.after["signal_type"], self.baseline["signal_type"])

    def test_layers_passed_unchanged(self) -> None:
        self.assertEqual(self.after["layers_passed"], self.baseline["layers_passed"])

    def test_entry_price_unchanged(self) -> None:
        self.assertAlmostEqual(
            self.after["entry_signal"]["entry_price"],
            self.baseline["entry_signal"]["entry_price"],
            places=9,
        )

    def test_stop_loss_unchanged(self) -> None:
        self.assertAlmostEqual(
            self.after["entry_signal"]["stop_loss"],
            self.baseline["entry_signal"]["stop_loss"],
            places=9,
        )

    def test_take_profit_unchanged(self) -> None:
        self.assertAlmostEqual(
            self.after["entry_signal"]["take_profit"],
            self.baseline["entry_signal"]["take_profit"],
            places=9,
        )

    def test_direction_unchanged(self) -> None:
        self.assertEqual(
            self.after["entry_signal"]["position_type"],
            self.baseline["entry_signal"]["position_type"],
        )

    def test_every_layer_payload_unchanged(self) -> None:
        """Per-layer, not just the final verdict."""
        for layer in ("layer_1", "layer_2", "layer_4", "layer_5", "layer_6", "layer_7", "layer_8"):
            with self.subTest(layer=layer):
                self.assertEqual(
                    str(self.after.get(layer)), str(self.baseline.get(layer))
                )


class TestBDecisionsBeforeTheCutoffTests(unittest.TestCase):
    """Test B: earlier decisions are unaffected by later mutation."""

    def test_decisions_before_the_cutoff_are_identical(self) -> None:
        moment = decision_instant()
        original = long_dataset(Resolution.TARGET)
        mutated = _mutate_after(original, moment)
        for minutes_before in (10, 20, 30, 60):
            earlier = moment - timedelta(minutes=minutes_before)
            with self.subTest(minutes_before=minutes_before):
                baseline, _, _, _ = analyse_at(original, earlier)
                after, _, _, _ = analyse_at(mutated, earlier)
                self.assertEqual(baseline["signal_type"], after["signal_type"])
                self.assertEqual(baseline.get("layer_failed"), after.get("layer_failed"))
                self.assertEqual(
                    baseline.get("layers_passed"), after.get("layers_passed")
                )


class TestCFutureAffectsOnlyTheExitTests(unittest.TestCase):
    """Test C: the future decides the exit, and nothing earlier."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.to_target, _, _ = run_replay(long_dataset(Resolution.TARGET))
        _, cls.to_stop, _, _ = run_replay(long_dataset(Resolution.STOP))
        cls.target_trade = cls.to_target.trades[0]
        cls.stop_trade = cls.to_stop.trades[0]

    def test_the_two_futures_produce_different_exits(self) -> None:
        """Confirms the fixtures really do diverge after the decision."""
        self.assertNotEqual(self.target_trade.outcome, self.stop_trade.outcome)

    def test_entry_price_is_identical_across_both_futures(self) -> None:
        self.assertAlmostEqual(
            self.target_trade.entry_price, self.stop_trade.entry_price, places=9
        )

    def test_stop_and_target_are_identical_across_both_futures(self) -> None:
        self.assertAlmostEqual(
            self.target_trade.stop_loss, self.stop_trade.stop_loss, places=9
        )
        self.assertAlmostEqual(
            self.target_trade.take_profit, self.stop_trade.take_profit, places=9
        )

    def test_decision_and_entry_timing_identical(self) -> None:
        for field in ("decision_time", "decision_bar_time", "signal_time", "entry_bar_time"):
            with self.subTest(field=field):
                self.assertEqual(
                    getattr(self.target_trade, field), getattr(self.stop_trade, field)
                )

    def test_only_the_exit_differs(self) -> None:
        self.assertNotEqual(self.target_trade.exit_time, self.stop_trade.exit_time)
        self.assertNotAlmostEqual(
            self.target_trade.exit_price, self.stop_trade.exit_price, places=2
        )


class TestDBoundaryTests(unittest.TestCase):
    """Test D: the close boundary is inclusive and exact."""

    def setUp(self) -> None:
        self.feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        self.moment = decision_instant()

    def test_bar_closing_exactly_at_the_instant_is_visible(self) -> None:
        frame = self.feed.bars(Timeframe.M5, 1, self.moment)
        latest_close = frame["time"].iloc[-1] + timedelta(minutes=5)
        self.assertEqual(latest_close, pd.Timestamp(self.moment))

    def test_bar_closing_one_second_later_is_not_visible(self) -> None:
        just_before = self.moment - timedelta(seconds=1)
        frame = self.feed.bars(Timeframe.M5, 1, just_before)
        latest_close = frame["time"].iloc[-1] + timedelta(minutes=5)
        self.assertLess(latest_close, pd.Timestamp(self.moment))

    def test_one_second_changes_the_strategys_information_set(self) -> None:
        at_boundary = self.feed.bars(Timeframe.M5, 1, self.moment)
        before = self.feed.bars(Timeframe.M5, 1, self.moment - timedelta(seconds=1))
        self.assertNotEqual(
            pd.Timestamp(at_boundary["time"].iloc[-1]),
            pd.Timestamp(before["time"].iloc[-1]),
        )


class MultiTimeframeIntegrityTests(unittest.TestCase):
    """Critical requirement 9: every step of the timeframe ladder."""

    def test_each_timeframe_only_shows_closed_bars(self) -> None:
        moment = decision_instant()
        feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        for timeframe, count in DEFAULT_BAR_COUNTS.items():
            with self.subTest(timeframe=timeframe.value):
                frame = feed.bars(timeframe, count, moment)
                closes = frame["time"] + timedelta(minutes=timeframe.minutes)
                self.assertTrue((closes <= pd.Timestamp(moment)).all())

    def test_the_ladder_is_monotonic(self) -> None:
        """M1 -> M5 -> M15 -> H1 -> H4 -> D1, each at least as stale as the last."""
        moment = decision_instant()
        feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        ladder = [Timeframe.M1, Timeframe.M5, Timeframe.M15,
                  Timeframe.H1, Timeframe.H4, Timeframe.D1]
        latest = [
            pd.Timestamp(feed.bars(tf, DEFAULT_BAR_COUNTS[tf], moment)["time"].iloc[-1])
            for tf in ladder
        ]
        for finer, coarser in zip(ladder, ladder[1:]):
            index = ladder.index(finer)
            with self.subTest(step=f"{finer.value}->{coarser.value}"):
                self.assertGreaterEqual(latest[index], latest[index + 1])

    def test_higher_timeframe_bars_aggregate_their_children(self) -> None:
        """An H1 bar's extremes really are its M1 constituents' extremes."""
        dataset = long_dataset(Resolution.TARGET)
        m1 = dataset.frame(Timeframe.M1)
        h1 = dataset.frame(Timeframe.H1)
        sample = h1.iloc[len(h1) // 2]
        window = m1[
            (m1["time"] >= sample["time"])
            & (m1["time"] < sample["time"] + timedelta(hours=1))
        ]
        self.assertAlmostEqual(float(sample["high"]), float(window["high"].max()), places=9)
        self.assertAlmostEqual(float(sample["low"]), float(window["low"].min()), places=9)


class DeterminismTests(unittest.TestCase):
    """Critical requirement 10: identical input, identical everything."""

    def test_two_identical_runs_agree_completely(self) -> None:
        first_result, first_ledger, first_metrics, _ = run_replay(
            long_dataset(Resolution.TARGET)
        )
        second_result, second_ledger, second_metrics, _ = run_replay(
            long_dataset(Resolution.TARGET)
        )

        self.assertEqual(first_ledger.fingerprint(), second_ledger.fingerprint())
        self.assertEqual(first_result.signals, second_result.signals)
        self.assertEqual(first_result.decisions, second_result.decisions)
        self.assertEqual(first_metrics.to_dict(), second_metrics.to_dict())

        a, b = first_ledger.trades[0], second_ledger.trades[0]
        for field in ("entry_price", "stop_loss", "take_profit",
                      "exit_price", "r_multiple", "net_pnl"):
            with self.subTest(field=field):
                self.assertAlmostEqual(
                    getattr(a, field), getattr(b, field), places=12
                )

    def test_result_is_independent_of_the_machine_timezone(self) -> None:
        import os
        import time

        fingerprints = []
        original = os.environ.get("TZ")
        try:
            for zone in ("UTC", "Asia/Karachi", "America/New_York"):
                os.environ["TZ"] = zone
                if hasattr(time, "tzset"):
                    time.tzset()
                _, ledger, _, _ = run_replay(long_dataset(Resolution.TARGET))
                fingerprints.append(ledger.fingerprint())
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            if hasattr(time, "tzset"):
                time.tzset()
        self.assertEqual(len(set(fingerprints)), 1)

    def test_the_fixture_itself_is_reproducible(self) -> None:
        from tests.fixtures.integration_market import make_long_setup_dataset

        first = make_long_setup_dataset(resolution=Resolution.TARGET)
        second = make_long_setup_dataset(resolution=Resolution.TARGET)
        pd.testing.assert_frame_equal(
            first.frame(Timeframe.M1), second.frame(Timeframe.M1)
        )


if __name__ == "__main__":
    unittest.main()
