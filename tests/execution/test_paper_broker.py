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
from execution.intrabar import IntrabarPolicy, resolve_intrabar
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

    def test_bar_touching_neither_level_keeps_the_position_open(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self._open_buy(broker)
        self.assertEqual(
            broker.fill_pending_orders(
                bar(T0 + timedelta(minutes=10), 2401.0, 2405.0, 2398.0, 2403.0),
                T0 + timedelta(minutes=10),
            ),
            [],
        )
        self.assertEqual(len(broker.open_positions()), 1)

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
    """The intrabar policy is an **annotation**, not an exit selector.

    Since the Phase 5B-i cut-over the canonical domain resolves every exit
    adverse-first and never consults a policy (decision D16). The resolver is
    still here, still policy-specific, and still flags ambiguity -- so these
    exercise it directly rather than through a broker that no longer decides.
    """

    AMBIGUOUS = dict(bar_high=2425.0, bar_low=2385.0, bar_open=2400.0, bar_close=2405.0)
    LEVELS = dict(stop_loss=2390.0, take_profit=2420.0)

    def _resolve(self, policy: IntrabarPolicy):
        return resolve_intrabar(
            side=Side.BUY, policy=policy, **self.AMBIGUOUS, **self.LEVELS
        )

    def test_conservative_resolves_to_the_stop(self) -> None:
        resolution = self._resolve(IntrabarPolicy.CONSERVATIVE)
        self.assertTrue(resolution.hit_stop)
        self.assertFalse(resolution.hit_target)
        self.assertTrue(resolution.was_ambiguous)
        self.assertIn("AMBIGUOUS", resolution.reason)

    def test_optimistic_resolves_to_the_target(self) -> None:
        resolution = self._resolve(IntrabarPolicy.OPTIMISTIC)
        self.assertTrue(resolution.hit_target)
        self.assertFalse(resolution.hit_stop)
        self.assertTrue(resolution.was_ambiguous)

    def test_the_two_policies_genuinely_disagree(self) -> None:
        """If they agreed, the ambiguity would not be material."""
        conservative = self._resolve(IntrabarPolicy.CONSERVATIVE)
        optimistic = self._resolve(IntrabarPolicy.OPTIMISTIC)
        self.assertNotEqual(conservative.hit_stop, optimistic.hit_stop)

    def test_a_disagreeing_policy_no_longer_changes_an_outcome(self) -> None:
        """The annotation may differ; the executable result may not.

        The broker holds the policy and closes nothing, so configuring it
        cannot move a headline figure -- which is what D16 settled.
        """
        broker = PaperBroker(
            XAUUSD_2DIGIT, NO_COST, intrabar_policy=IntrabarPolicy.OPTIMISTIC
        )
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=2390.0, take_profit=2420.0,
            decision_time=T0, decision_bar_time=None,
            execution_bar=bar(T0 + timedelta(minutes=5), 2400.0, 2402.0, 2399.0, 2401.0),
        )
        closed = broker.fill_pending_orders(
            bar(T0 + timedelta(minutes=10), 2400.0, 2425.0, 2385.0, 2405.0),
            T0 + timedelta(minutes=10),
        )
        self.assertEqual(closed, [], "the broker returns opened positions, not closed")
        self.assertEqual(broker.closed_positions(), [])

    def test_unambiguous_bar_is_not_flagged(self) -> None:
        resolution = resolve_intrabar(
            side=Side.BUY, bar_high=2400.0, bar_low=2385.0,
            bar_open=2399.0, bar_close=2392.0, **self.LEVELS
        )
        self.assertFalse(resolution.was_ambiguous)
        self.assertTrue(resolution.hit_stop)

    def test_tick_policy_raises_rather_than_silently_using_ohlc(self) -> None:
        with self.assertRaises(NotImplementedError):
            self._resolve(IntrabarPolicy.TICK_DATA)

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

    def test_fill_bar_covering_neither_leaves_the_position_open(self) -> None:
        broker = self._broker()
        closed = broker.fill_pending_orders(bar(self.FILL, 2400.0, 2402.0, 2399.0, 2401.0), self.FILL)
        self.assertEqual(closed, [])
        self.assertEqual(len(broker.open_positions()), 1)
        self.assertEqual(broker.open_positions()[0].bars_held, 1)

    def test_bars_held_counts_the_fill_bar(self) -> None:
        """N bars presented, starting with the fill bar, gives bars_held == N."""
        broker = self._broker()
        quiet = (2400.0, 2402.0, 2399.0, 2401.0)
        for step in range(0, 4):
            moment = self.FILL + timedelta(minutes=5 * step)
            broker.fill_pending_orders(bar(moment, *quiet), moment)
            self.assertEqual(broker.open_positions()[0].bars_held, step + 1)

    def test_a_bar_before_the_fill_is_still_never_applied(self) -> None:
        """The guard is narrowed to `<`, not removed."""
        broker = self._broker()
        earlier = T0 - timedelta(minutes=10)
        closed = broker.fill_pending_orders(bar(earlier, 2400.0, 2425.0, 2385.0, 2405.0), earlier)
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

