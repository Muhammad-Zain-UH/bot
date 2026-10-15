"""Exact timing of decision, signal and fill.

Critical requirement 3. The chain that must hold for every integration trade::

    strategy observes only CLOSED information
            |
    signal generated at the close of bar N
            |
    entry CANNOT occur on bar N
            |
    entry occurs on the next eligible bar

A signal generated at the close of bar N filling at bar N's close would be
trading on hindsight -- the strategy would transact at a price it could only
know once the opportunity had passed.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

import pandas as pd

from backtest.replay_engine import DEFAULT_BAR_COUNTS
from core.types import Timeframe
from data.replay_feed import ReplayFeed
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import (
    SPREAD_PIPS,
    decision_instant,
    long_dataset,
    run_replay,
    short_dataset,
)

REQUIRED_TIMING_FIELDS = (
    "decision_time", "decision_bar_time", "signal_time",
    "entry_available_time", "entry_bar_time", "entry_price",
    "stop_loss", "take_profit", "exit_time", "exit_price",
    "exit_reason", "side", "quantity", "r_multiple", "net_pnl",
)


class TimingFieldsTests(unittest.TestCase):
    """Every field required by the phase brief must be recorded."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.ledger, _, _ = run_replay(long_dataset(Resolution.TARGET))
        cls.trade = cls.ledger.trades[0]

    def test_a_trade_was_recorded(self) -> None:
        self.assertEqual(len(self.ledger.trades), 1)

    def test_all_required_fields_present_and_populated(self) -> None:
        for field in REQUIRED_TIMING_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(hasattr(self.trade, field))
                self.assertIsNotNone(getattr(self.trade, field))

    def test_timestamps_are_timezone_aware_iso(self) -> None:
        for field in ("decision_time", "decision_bar_time", "signal_time",
                      "entry_bar_time", "exit_time"):
            with self.subTest(field=field):
                parsed = pd.Timestamp(getattr(self.trade, field))
                self.assertIsNotNone(parsed.tz)


class NoSameBarFillTests(unittest.TestCase):
    """The core no-hindsight guarantee."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.trades = {}
        for name, dataset in (("long", long_dataset(Resolution.TARGET)),
                              ("short", short_dataset(Resolution.TARGET))):
            _, ledger, _, _ = run_replay(dataset)
            cls.trades[name] = ledger.trades[0]

    def test_entry_bar_opens_strictly_after_the_decision_bar(self) -> None:
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                self.assertGreater(
                    pd.Timestamp(trade.entry_bar_time),
                    pd.Timestamp(trade.decision_bar_time),
                    "the fill used the bar the strategy decided from",
                )

    def test_entry_bar_opens_at_or_after_the_decision_instant(self) -> None:
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                self.assertGreaterEqual(
                    pd.Timestamp(trade.entry_bar_time),
                    pd.Timestamp(trade.decision_time),
                )

    def test_decision_bar_closed_exactly_at_the_decision_instant(self) -> None:
        """The decision consumes a bar that had just completed, not a live one."""
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                decision_bar_close = pd.Timestamp(trade.decision_bar_time) + timedelta(
                    minutes=Timeframe.M5.minutes
                )
                self.assertEqual(decision_bar_close, pd.Timestamp(trade.decision_time))

    def test_signal_time_equals_decision_time(self) -> None:
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                self.assertEqual(trade.signal_time, trade.decision_time)

    def test_entry_is_the_immediately_next_bar(self) -> None:
        """No unexplained gap between the decision and the fill."""
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                self.assertEqual(
                    pd.Timestamp(trade.entry_bar_time),
                    pd.Timestamp(trade.decision_bar_time) + timedelta(
                        minutes=Timeframe.M5.minutes
                    ),
                )

    def test_fill_price_is_the_execution_bar_open_plus_costs(self) -> None:
        """The fill references the next bar's OPEN, never the decision close."""
        from core.symbols import XAUUSD_2DIGIT
        from core.units import Pips

        cost = Pips(SPREAD_PIPS).to_price(XAUUSD_2DIGIT).value
        for name, dataset in (("long", long_dataset(Resolution.TARGET)),
                              ("short", short_dataset(Resolution.TARGET))):
            with self.subTest(side=name):
                trade = self.trades[name]
                feed = ReplayFeed(dataset, spread_pips=SPREAD_PIPS)
                execution_bar = feed.next_bar_after(
                    Timeframe.M5, pd.Timestamp(trade.decision_time).to_pydatetime()
                )
                self.assertAlmostEqual(
                    trade.entry_reference_price, float(execution_bar["open"]), places=6
                )
                sign = 1 if trade.side == "BUY" else -1
                self.assertAlmostEqual(
                    trade.entry_price, float(execution_bar["open"]) + cost * sign, places=6
                )

    def test_exit_occurs_after_entry(self) -> None:
        for name, trade in self.trades.items():
            with self.subTest(side=name):
                self.assertGreater(
                    pd.Timestamp(trade.exit_time), pd.Timestamp(trade.entry_bar_time)
                )


class ClosedInformationOnlyTests(unittest.TestCase):
    """At the decision instant, every frame contained only completed bars."""

    def test_no_frame_contains_an_unclosed_bar(self) -> None:
        moment = decision_instant()
        feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        for timeframe, count in DEFAULT_BAR_COUNTS.items():
            with self.subTest(timeframe=timeframe.value):
                frame = feed.bars(timeframe, count, moment)
                latest_close = frame["time"].iloc[-1] + timedelta(minutes=timeframe.minutes)
                self.assertLessEqual(latest_close, pd.Timestamp(moment))

    def test_higher_timeframes_lag_as_expected(self) -> None:
        """The exact lag structure at the decision instant, per timeframe."""
        moment = decision_instant()  # 07:10 UTC
        feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        expected = {
            Timeframe.M1: "07:09",
            Timeframe.M5: "07:05",
            Timeframe.M15: "06:45",
            Timeframe.H1: "06:00",
            Timeframe.H4: "00:00",
        }
        for timeframe, want in expected.items():
            with self.subTest(timeframe=timeframe.value):
                frame = feed.bars(timeframe, DEFAULT_BAR_COUNTS[timeframe], moment)
                self.assertEqual(
                    pd.Timestamp(frame["time"].iloc[-1]).strftime("%H:%M"), want
                )

    def test_the_execution_bar_was_not_visible_at_decision_time(self) -> None:
        """The clinching check: the bar we fill on had not closed yet."""
        moment = decision_instant()
        feed = ReplayFeed(long_dataset(Resolution.TARGET), spread_pips=SPREAD_PIPS)
        visible = feed.bars(Timeframe.M5, DEFAULT_BAR_COUNTS[Timeframe.M5], moment)
        execution_bar = feed.next_bar_after(Timeframe.M5, moment)
        self.assertNotIn(
            pd.Timestamp(execution_bar["time"]), set(visible["time"]),
            "the execution bar was already inside the strategy's information set",
        )


class RMultipleTests(unittest.TestCase):
    """R is computed from the ACTUAL fill and stop, not the intended entry."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.ledger, _, _ = run_replay(long_dataset(Resolution.TARGET))
        cls.trade = cls.ledger.trades[0]

    def test_price_risk_is_fill_to_stop(self) -> None:
        self.assertAlmostEqual(
            self.trade.price_risk,
            abs(self.trade.entry_price - self.trade.stop_loss),
            places=6,
        )

    def test_r_multiple_is_net_pnl_over_risk_amount(self) -> None:
        self.assertAlmostEqual(
            self.trade.r_multiple, self.trade.net_pnl / self.trade.risk_amount, places=9
        )

    def test_realised_r_differs_from_the_strategys_nominal_ratio(self) -> None:
        """Documents a real consequence, not a defect in the simulator.

        The strategy computes its 3.0 RR against an entry price it does not get
        filled at: the fill is the next bar's open plus spread. Risk and reward
        are therefore both measured from a different price than the one the
        strategy assumed, so realised R does not equal the nominal 3.0.
        This is the practical effect of PHASE_2_ISSUES B3/B4 and E9.
        """
        self.assertNotAlmostEqual(self.trade.r_multiple, 3.0, places=2)


if __name__ == "__main__":
    unittest.main()
