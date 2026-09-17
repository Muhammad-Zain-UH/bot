"""Paper broker tests: fills, stops, targets, gaps and ambiguity.

Also pins the entry-timing invariant: a fill must use a bar that had **not
started** when the signal was generated. Violating it is silent look-ahead, so
:class:`~execution.broker.SimulatedFill` raises rather than recording it.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.symbols import XAUUSD_2DIGIT
from core.types import DomainInvariantError, Side
from core.units import Pips
from execution.broker import FillStatus, PositionState, SimulatedFill
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import PaperBroker

UTC = timezone.utc
T0 = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
NO_COST = FillModel(spread=Pips(0.0), slippage=Pips(0.0))


def bar(time: datetime, o: float, h: float, low: float, c: float) -> pd.Series:
    """Build a bar Series."""
    return pd.Series(
        {"time": pd.Timestamp(time), "open": o, "high": h, "low": low, "close": c,
         "tick_volume": 100.0}
    )


class EntryTimingTests(unittest.TestCase):
    """The fill must not use information that existed at decision time."""

    def setUp(self) -> None:
        self.broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)

    def test_full_timing_chain_is_recorded(self) -> None:
        execution_bar = bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0)
        fill = self.broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=execution_bar,
        )
        self.assertIs(fill.status, FillStatus.FILLED)
        self.assertEqual(fill.decision_time, T0)
        self.assertEqual(fill.decision_bar_time, T0 - timedelta(minutes=5))
        self.assertEqual(fill.signal_time, T0)
        self.assertEqual(fill.entry_bar_time, T0 + timedelta(minutes=5))
        self.assertAlmostEqual(fill.entry_price, 2400.0)

    def test_entry_bar_is_strictly_after_the_decision_bar(self) -> None:
        execution_bar = bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0)
        fill = self.broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=execution_bar,
        )
        self.assertGreater(fill.entry_bar_time, fill.decision_bar_time)
        self.assertGreaterEqual(fill.entry_bar_time, fill.decision_time)

    def test_filling_on_the_decision_bar_is_rejected_as_lookahead(self) -> None:
        """Constructing such a fill must raise, not be quietly recorded."""
        with self.assertRaises(DomainInvariantError) as ctx:
            SimulatedFill(
                status=FillStatus.FILLED, side=Side.BUY,
                decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
                signal_time=T0,
                entry_available_time=T0 - timedelta(minutes=5),
                entry_bar_time=T0 - timedelta(minutes=5),  # the bar it decided on
                entry_price=2400.0, reference_price=2400.0, volume=0.01,
            )
        self.assertIn("LOOK-AHEAD", str(ctx.exception))

    def test_filling_before_the_decision_is_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            SimulatedFill(
                status=FillStatus.FILLED, side=Side.BUY,
                decision_time=T0, decision_bar_time=None, signal_time=T0,
                entry_available_time=T0 - timedelta(hours=1),
                entry_bar_time=T0 - timedelta(hours=1),
                entry_price=2400.0, reference_price=2400.0, volume=0.01,
            )

    def test_entry_fills_at_next_bar_open_not_decision_close(self) -> None:
        """Filling at the decision bar's close would be trading on hindsight."""
        execution_bar = bar(T0 + timedelta(minutes=5), 2405.0, 2410.0, 2404.0, 2409.0)
        fill = self.broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2395.0, take_profit=2430.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=execution_bar,
        )
        self.assertAlmostEqual(fill.reference_price, 2405.0)  # the OPEN

    def test_no_execution_bar_is_reported_not_silently_dropped(self) -> None:
        fill = self.broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None, execution_bar=None,
        )
        self.assertIs(fill.status, FillStatus.NO_EXECUTION_BAR)
        self.assertEqual(len(self.broker.open_positions()), 0)


class FillCostTests(unittest.TestCase):
    """Spread and slippage must always be adverse."""

    def test_buy_pays_the_spread(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, FillModel(spread=Pips(2.0)))
        fill = broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        self.assertAlmostEqual(fill.entry_price, 2400.20)  # 2 pips = $0.20

    def test_sell_pays_the_spread_in_the_other_direction(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, FillModel(spread=Pips(2.0)))
        fill = broker.submit_market_order(
            side=Side.SELL, volume=0.01, stop_loss=2410.0, take_profit=2380.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        self.assertAlmostEqual(fill.entry_price, 2399.80)

    def test_slippage_is_also_adverse(self) -> None:
        broker = PaperBroker(
            XAUUSD_2DIGIT, FillModel(spread=Pips(0.0), slippage=Pips(1.0))
        )
        fill = broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        self.assertAlmostEqual(fill.entry_price, 2400.10)

    def test_fill_model_rejects_untyped_distances(self) -> None:
        with self.assertRaises(TypeError):
            FillModel(spread=2.0)  # type: ignore[arg-type]

    def test_stop_pushed_through_by_costs_is_rejected(self) -> None:
        """A tight stop can end up above a BUY fill once the spread is paid.

        Bar opens 2400.00; a 2-pip spread fills the BUY at 2400.20. A stop at
        2400.50 is then *above* the entry, so the position would open already
        beyond its own stop. Reject rather than open it.
        """
        broker = PaperBroker(XAUUSD_2DIGIT, FillModel(spread=Pips(2.0)))
        fill = broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2400.5, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        self.assertIs(fill.status, FillStatus.REJECTED)
        self.assertIn("stop", fill.reason)
        self.assertEqual(len(broker.open_positions()), 0)


class ExitTests(unittest.TestCase):
    """Stops, targets, gaps and the time stop."""

    def _open_buy(self, broker: PaperBroker) -> None:
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )

    def test_stop_hit(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2399.0, 2400.0, 2385.0, 2392.0),
            T0 + timedelta(minutes=10),
        )
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2390.0)

    def test_target_hit(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2402.0, 2425.0, 2401.0, 2424.0),
            T0 + timedelta(minutes=10),
        )
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)
        self.assertAlmostEqual(closed[0].exit_price, 2420.0)

    def test_gap_through_stop_fills_at_the_open_not_the_stop(self) -> None:
        """A gap fills worse than the stop. Assuming otherwise flatters results."""
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2370.0, 2375.0, 2365.0, 2372.0),
            T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(closed[0].exit_price, 2370.0)
        self.assertIn("GAPPED", closed[0].exit_reason)

    def test_gap_through_target_fills_at_the_open(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2440.0, 2445.0, 2438.0, 2444.0),
            T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(closed[0].exit_price, 2440.0)

    def test_bar_touching_neither_level_keeps_the_position_open(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        self.assertEqual(
            broker.on_bar(
                bar(T0 + timedelta(minutes=10), 2401.0, 2405.0, 2398.0, 2403.0),
                T0 + timedelta(minutes=10),
            ),
            [],
        )
        self.assertEqual(len(broker.open_positions()), 1)

    def test_entry_bar_is_evaluated(self) -> None:
        """R1: the fill bar counts.

        This test previously asserted the opposite, on the reasoning that
        resolving the fill bar's range would double-count it. That was wrong: a
        market fill happens at the bar's open, so the position is exposed to the
        rest of that bar. Here the fill bar's low (2380) is through the stop
        (2390), so the position closes on the bar it opened on.
        """
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        entry_bar = bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2380.0, 2401.0)
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None, execution_bar=entry_bar,
        )
        closed = broker.on_bar(entry_bar, T0 + timedelta(minutes=5))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2390.0)
        self.assertEqual(closed[0].bars_held, 1)
        self.assertEqual(len(broker.open_positions()), 0)

    def test_sell_stop_and_target(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        broker.submit_market_order(
            side=Side.SELL, volume=0.01, stop_loss=2410.0, take_profit=2380.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2400.0, 2415.0, 2398.0, 2412.0),
            T0 + timedelta(minutes=10),
        )
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2410.0)

    def test_time_stop(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, max_bars_held=2)
        self._open_buy(broker)
        broker.on_bar(bar(T0 + timedelta(minutes=10), 2401.0, 2405.0, 2398.0, 2403.0),
                      T0 + timedelta(minutes=10))
        closed = broker.on_bar(bar(T0 + timedelta(minutes=15), 2403.0, 2406.0, 2400.0, 2404.0),
                               T0 + timedelta(minutes=15))
        self.assertIs(closed[0].state, PositionState.CLOSED_TIME)

    def test_end_of_data_close_is_labelled_separately(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        closed = broker.close_all_at_end_of_data(2405.0, T0 + timedelta(hours=1))
        self.assertIs(closed[0].state, PositionState.CLOSED_END_OF_DATA)

    def test_concurrency_cap_is_enforced(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, max_open_positions=1)
        self._open_buy(broker)
        fill = broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=10), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        self.assertIs(fill.status, FillStatus.REJECTED)
        self.assertIn("max open positions", fill.reason)


class AmbiguousBarTests(unittest.TestCase):
    """A bar containing both levels is decided by policy, and flagged as such."""

    def _broker_with(self, policy: IntrabarPolicy) -> PaperBroker:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, intrabar_policy=policy)
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        return broker

    AMBIGUOUS = (2400.0, 2425.0, 2385.0, 2405.0)  # spans both stop and target

    def test_conservative_resolves_to_the_stop(self) -> None:
        broker = self._broker_with(IntrabarPolicy.CONSERVATIVE)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), *self.AMBIGUOUS), T0 + timedelta(minutes=10)
        )
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertTrue(closed[0].was_ambiguous_exit)
        self.assertIn("AMBIGUOUS", closed[0].exit_reason)

    def test_optimistic_resolves_to_the_target(self) -> None:
        broker = self._broker_with(IntrabarPolicy.OPTIMISTIC)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), *self.AMBIGUOUS), T0 + timedelta(minutes=10)
        )
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)
        self.assertTrue(closed[0].was_ambiguous_exit)

    def test_the_two_policies_genuinely_disagree(self) -> None:
        """If they agreed, the ambiguity would not be material."""
        conservative = self._broker_with(IntrabarPolicy.CONSERVATIVE).on_bar(
            bar(T0 + timedelta(minutes=10), *self.AMBIGUOUS), T0 + timedelta(minutes=10)
        )[0]
        optimistic = self._broker_with(IntrabarPolicy.OPTIMISTIC).on_bar(
            bar(T0 + timedelta(minutes=10), *self.AMBIGUOUS), T0 + timedelta(minutes=10)
        )[0]
        self.assertNotEqual(conservative.state, optimistic.state)

    def test_unambiguous_bar_is_not_flagged(self) -> None:
        broker = self._broker_with(IntrabarPolicy.CONSERVATIVE)
        closed = broker.on_bar(
            bar(T0 + timedelta(minutes=10), 2399.0, 2400.0, 2385.0, 2392.0),
            T0 + timedelta(minutes=10),
        )
        self.assertFalse(closed[0].was_ambiguous_exit)

    def test_tick_policy_raises_rather_than_silently_using_ohlc(self) -> None:
        broker = self._broker_with(IntrabarPolicy.TICK_DATA)
        with self.assertRaises(NotImplementedError):
            broker.on_bar(
                bar(T0 + timedelta(minutes=10), *self.AMBIGUOUS),
                T0 + timedelta(minutes=10),
            )


if __name__ == "__main__":
    unittest.main()


class SameBarExitTests(unittest.TestCase):
    """R1: a position is evaluated for exits on the bar it filled on.

    A market fill happens at the execution bar's open, so the position exists
    for the whole of that bar. Phase 2A skipped it on the grounds that
    evaluating the fill bar would "double-count" it, which was wrong -- the
    position is exposed to that bar's range from the open onward.

    The fill bar here is always ``T0 + 5min``, the bar ``submit_market_order``
    was given, and it is passed straight back to ``on_bar``.
    """

    FILL = T0 + timedelta(minutes=5)

    def _broker(self, **kwargs) -> PaperBroker:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, **kwargs)
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(self.FILL, 2400.0, 2402.0, 2399.0, 2401.0),
        )
        return broker

    def test_fill_bar_covering_the_stop_closes_on_that_bar(self) -> None:
        broker = self._broker()
        closed = broker.on_bar(bar(self.FILL, 2400.0, 2402.0, 2385.0, 2392.0), self.FILL)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2390.0)
        self.assertEqual(closed[0].exit_time, self.FILL)

    def test_fill_bar_covering_the_target_closes_on_that_bar(self) -> None:
        broker = self._broker()
        closed = broker.on_bar(bar(self.FILL, 2400.0, 2425.0, 2399.0, 2421.0), self.FILL)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)
        self.assertAlmostEqual(closed[0].exit_price, 2420.0)

    def test_fill_bar_covering_both_uses_the_existing_policy(self) -> None:
        """No new ambiguity class: the existing resolution decides it."""
        broker = self._broker()
        closed = broker.on_bar(bar(self.FILL, 2400.0, 2425.0, 2385.0, 2405.0), self.FILL)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertTrue(closed[0].was_ambiguous_exit)

    def test_fill_bar_covering_neither_leaves_the_position_open(self) -> None:
        broker = self._broker()
        closed = broker.on_bar(bar(self.FILL, 2400.0, 2402.0, 2399.0, 2401.0), self.FILL)
        self.assertEqual(closed, [])
        self.assertEqual(len(broker.open_positions()), 1)
        self.assertEqual(broker.open_positions()[0].bars_held, 1)

    def test_fill_bar_gapping_through_the_stop_exits_at_the_open(self) -> None:
        """The existing gap rule applies unchanged on the fill bar."""
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2399.5, take_profit=2420.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(self.FILL, 2400.0, 2402.0, 2399.0, 2401.0),
        )
        # Same bar, re-presented with a low that gaps under the stop.
        closed = broker.on_bar(bar(self.FILL, 2399.0, 2400.0, 2385.0, 2390.0), self.FILL)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2399.0)
        self.assertIn("GAPPED", closed[0].exit_reason)

    def test_bars_held_counts_the_fill_bar(self) -> None:
        """N bars presented, starting with the fill bar, gives bars_held == N."""
        broker = self._broker()
        quiet = (2400.0, 2402.0, 2399.0, 2401.0)
        for step in range(0, 4):
            moment = self.FILL + timedelta(minutes=5 * step)
            broker.on_bar(bar(moment, *quiet), moment)
            self.assertEqual(broker.open_positions()[0].bars_held, step + 1)

    def test_a_bar_before_the_fill_is_still_never_applied(self) -> None:
        """The guard is narrowed to `<`, not removed."""
        broker = self._broker()
        earlier = T0 - timedelta(minutes=10)
        closed = broker.on_bar(bar(earlier, 2400.0, 2425.0, 2385.0, 2405.0), earlier)
        self.assertEqual(closed, [])
        self.assertEqual(broker.open_positions()[0].bars_held, 0)

    def test_timing_invariant_still_raises(self) -> None:
        """R1 must not weaken the no-look-ahead guard."""
        with self.assertRaises(DomainInvariantError):
            SimulatedFill(
                status=FillStatus.FILLED, side=Side.BUY,
                decision_time=T0, decision_bar_time=T0,
                signal_time=T0, entry_available_time=T0,
                entry_bar_time=T0, entry_price=2400.0,
                reference_price=2400.0, volume=0.01,
            )

    def test_max_bars_held_fires_at_the_configured_count(self) -> None:
        """Still N bars -- but the fill bar is now one of them."""
        broker = self._broker(max_bars_held=2)
        quiet = (2400.0, 2402.0, 2399.0, 2401.0)
        first = broker.on_bar(bar(self.FILL, *quiet), self.FILL)
        self.assertEqual(first, [])
        second = self.FILL + timedelta(minutes=5)
        closed = broker.on_bar(bar(second, *quiet), second)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_TIME)
        self.assertEqual(closed[0].bars_held, 2)
