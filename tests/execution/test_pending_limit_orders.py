"""LIMIT_FVG pending-order lifecycle.

Covers the semantics the specification fixed and nothing more. Expiry, zone
invalidation and cross-session cancellation are **not** implemented, and the
tests at the end of this file pin that absence deliberately: the first
experiment runs as a control with all three disabled, which is a research
condition and not a policy. See ``docs/PHASE_4A_STEP4_DECISION_EVIDENCE.md``.

The fill rule under test is the one from the momentum entry specification,
mirroring the comparison ``resolve_intrabar`` already applies to a stop:

    BUY  reached when bar.low  <= limit
    SELL reached when bar.high >= limit

and the order may never fill on the bar its gap formed on.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.symbols import XAUUSD_2DIGIT
from core.types import DomainInvariantError, PendingOrderIntent, Side
from core.units import Pips
from execution.broker import PendingState, PositionState
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import PaperBroker

UTC = timezone.utc
T0 = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
FORMATION = T0                      # the bar the gap completed on
NEXT = T0 + timedelta(minutes=5)    # earliest bar that may fill
NO_COST = FillModel(spread=Pips(0.0), slippage=Pips(0.0))

ZONE_LOW, ZONE_HIGH = 2400.0, 2404.0
MID = 2402.0                        # the FVG midpoint: where the order rests


def bar(time: datetime, o: float, h: float, low: float, c: float) -> pd.Series:
    """Build a bar Series."""
    return pd.Series(
        {"time": pd.Timestamp(time), "open": o, "high": h, "low": low, "close": c,
         "tick_volume": 100.0}
    )


def buy_intent(stop: float = 2396.0, target: float | None = 2412.0) -> PendingOrderIntent:
    """A BUY limit resting at the zone midpoint."""
    return PendingOrderIntent(
        side=Side.BUY, limit_price=MID, stop_loss=stop, take_profit=target,
        zone_low=ZONE_LOW, zone_high=ZONE_HIGH,
        formation_bar_time=FORMATION, decision_time=FORMATION,
    )


def sell_intent(stop: float = 2408.0, target: float | None = 2392.0) -> PendingOrderIntent:
    """A SELL limit resting at the zone midpoint."""
    return PendingOrderIntent(
        side=Side.SELL, limit_price=MID, stop_loss=stop, take_profit=target,
        zone_low=ZONE_LOW, zone_high=ZONE_HIGH,
        formation_bar_time=FORMATION, decision_time=FORMATION,
    )


class IntentTests(unittest.TestCase):
    """The intent validates the geometry the strategy asked for."""

    def test_limit_outside_the_zone_is_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            PendingOrderIntent(
                side=Side.BUY, limit_price=2410.0, stop_loss=2396.0, take_profit=None,
                zone_low=ZONE_LOW, zone_high=ZONE_HIGH,
                formation_bar_time=FORMATION, decision_time=FORMATION,
            )

    def test_stop_on_the_wrong_side_is_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            PendingOrderIntent(
                side=Side.BUY, limit_price=MID, stop_loss=2403.0, take_profit=None,
                zone_low=ZONE_LOW, zone_high=ZONE_HIGH,
                formation_bar_time=FORMATION, decision_time=FORMATION,
            )

    def test_inverted_zone_is_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            PendingOrderIntent(
                side=Side.BUY, limit_price=MID, stop_loss=2396.0, take_profit=None,
                zone_low=ZONE_HIGH, zone_high=ZONE_LOW,
                formation_bar_time=FORMATION, decision_time=FORMATION,
            )

    def test_reach_is_direction_aware(self) -> None:
        self.assertTrue(buy_intent().is_reached_by(2405.0, 2401.0))    # low <= mid
        self.assertFalse(buy_intent().is_reached_by(2405.0, 2403.0))
        self.assertTrue(sell_intent().is_reached_by(2403.0, 2399.0))   # high >= mid
        self.assertFalse(sell_intent().is_reached_by(2401.0, 2399.0))


class PendingCreationTests(unittest.TestCase):
    """Creating an order rests it; nothing fills at creation."""

    def setUp(self) -> None:
        self.broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self.order = self.broker.submit_limit_order(buy_intent())

    def test_order_is_pending(self) -> None:
        self.assertIs(self.order.state, PendingState.PENDING)
        self.assertEqual(len(self.broker.pending_orders()), 1)

    def test_no_position_exists_yet(self) -> None:
        self.assertEqual(self.broker.open_positions(), [])

    def test_order_carries_its_formation_bar(self) -> None:
        self.assertEqual(self.order.intent.formation_bar_time, FORMATION)


class SameBarFillIsImpossibleTests(unittest.TestCase):
    """A pending order may never fill on the bar its gap formed on."""

    def test_formation_bar_does_not_fill_even_when_it_reaches(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(buy_intent())
        # This bar reaches the limit, but it IS the formation bar.
        broker.on_bar(bar(FORMATION, 2404.0, 2405.0, 2399.0, 2400.0), FORMATION)
        self.assertIs(order.state, PendingState.PENDING)
        self.assertEqual(broker.open_positions(), [])

    def test_eligibility_is_strictly_after_formation(self) -> None:
        order = PaperBroker(XAUUSD_2DIGIT, NO_COST).submit_limit_order(buy_intent())
        self.assertFalse(order.may_fill_on(FORMATION))
        self.assertTrue(order.may_fill_on(NEXT))

    def test_marking_a_formation_bar_fill_raises(self) -> None:
        """The guard lives on the object, not on the caller."""
        order = PaperBroker(XAUUSD_2DIGIT, NO_COST).submit_limit_order(buy_intent())
        with self.assertRaises(DomainInvariantError):
            order.mark_filled(FORMATION, MID)


class ReachAndFillTests(unittest.TestCase):
    """A later bar that reaches the limit opens a position."""

    def test_buy_fills_when_the_low_reaches_the_midpoint(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2404.0, 2405.0, 2401.0, 2403.0), NEXT)
        self.assertIs(order.state, PendingState.FILLED)
        self.assertAlmostEqual(order.fill_price, MID)
        self.assertEqual(order.fill_time, NEXT)
        self.assertEqual(len(broker.open_positions()), 1)

    def test_sell_fills_when_the_high_reaches_the_midpoint(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(sell_intent())
        broker.on_bar(bar(NEXT, 2399.0, 2403.0, 2398.0, 2401.0), NEXT)
        self.assertIs(order.state, PendingState.FILLED)
        self.assertAlmostEqual(order.fill_price, MID)
        self.assertEqual(len(broker.open_positions()), 1)

    def test_a_bar_that_does_not_reach_leaves_it_pending(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2404.0, 2406.0, 2403.0, 2405.0), NEXT)
        self.assertIs(order.state, PendingState.PENDING)
        self.assertIsNone(order.first_reached_time)
        self.assertEqual(broker.open_positions(), [])

    def test_a_gapping_bar_fills_at_the_open(self) -> None:
        """Mirrors the existing gap rule for stops: the first available price."""
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2401.0, 2401.5, 2400.5, 2401.2), NEXT)
        self.assertIs(order.state, PendingState.FILLED)
        self.assertAlmostEqual(order.fill_price, 2401.0)

    def test_position_records_the_pending_order_id(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2404.0, 2405.0, 2401.0, 2403.0), NEXT)
        self.assertEqual(
            broker.open_positions()[0].metadata["pending_order_id"], order.order_id
        )


class FillThenExitOnTheSameBarTests(unittest.TestCase):
    """R1 applies to limit fills: the fill bar is evaluated for exits."""

    def test_fill_then_stop_on_the_same_bar(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        broker.submit_limit_order(buy_intent(stop=2396.0, target=2412.0))
        closed = broker.on_bar(bar(NEXT, 2404.0, 2405.0, 2395.0, 2397.0), NEXT)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, 2396.0)

    def test_fill_then_target_on_the_same_bar(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        broker.submit_limit_order(buy_intent(stop=2396.0, target=2404.5))
        closed = broker.on_bar(bar(NEXT, 2403.0, 2405.0, 2401.0, 2404.8), NEXT)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)

    def test_fill_then_both_uses_the_existing_policy(self) -> None:
        """No new ambiguity policy: resolve_intrabar decides, and flags it."""
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        broker.submit_limit_order(buy_intent(stop=2396.0, target=2404.5))
        closed = broker.on_bar(bar(NEXT, 2403.0, 2405.0, 2395.0, 2400.0), NEXT)
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertTrue(closed[0].was_ambiguous_exit)

    def test_optimistic_policy_still_reaches_the_target(self) -> None:
        """The policy remains selectable and is not reinterpreted."""
        broker = PaperBroker(
            XAUUSD_2DIGIT, NO_COST, intrabar_policy=IntrabarPolicy.OPTIMISTIC
        )
        broker.submit_limit_order(buy_intent(stop=2396.0, target=2404.5))
        closed = broker.on_bar(bar(NEXT, 2403.0, 2405.0, 2395.0, 2400.0), NEXT)
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)
        self.assertTrue(closed[0].was_ambiguous_exit)


class OrderingAndCapacityTests(unittest.TestCase):
    """Several resting orders resolve in a defined order."""

    def test_orders_fill_in_creation_sequence(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, max_open_positions=3)
        first = broker.submit_limit_order(buy_intent())
        second = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2404.0, 2405.0, 2401.0, 2403.0), NEXT)
        self.assertLess(first.sequence, second.sequence)
        self.assertIs(first.state, PendingState.FILLED)
        self.assertIs(second.state, PendingState.FILLED)

    def test_capacity_denies_the_fill_but_keeps_the_order_pending(self) -> None:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST, max_open_positions=1)
        first = broker.submit_limit_order(buy_intent())
        second = broker.submit_limit_order(buy_intent())
        broker.on_bar(bar(NEXT, 2404.0, 2405.0, 2401.0, 2403.0), NEXT)
        self.assertIs(first.state, PendingState.FILLED)
        self.assertIs(second.state, PendingState.PENDING)
        self.assertIsNotNone(second.first_reached_time)


class ExperimentalControlTests(unittest.TestCase):
    """[EXPERIMENTAL CONTROL] -- expiry, invalidation and cancellation are OFF.

    These pin a research condition, not a policy. They must fail loudly if a
    rule is ever added without the decision behind it being recorded first.
    """

    def _rested(self) -> tuple[PaperBroker, object]:
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        return broker, broker.submit_limit_order(buy_intent())

    def test_no_expiry_order_survives_many_bars(self) -> None:
        broker, order = self._rested()
        for step in range(1, 500):
            moment = FORMATION + timedelta(minutes=5 * step)
            broker.on_bar(bar(moment, 2410.0, 2411.0, 2409.0, 2410.5), moment)
        self.assertIs(order.state, PendingState.PENDING)

    def test_no_zone_invalidation_when_price_traverses_the_zone(self) -> None:
        """Price passing fully through must not cancel the order."""
        broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        order = broker.submit_limit_order(
            PendingOrderIntent(
                side=Side.BUY, limit_price=MID, stop_loss=2380.0, take_profit=2412.0,
                zone_low=ZONE_LOW, zone_high=ZONE_HIGH,
                formation_bar_time=FORMATION, decision_time=FORMATION,
            )
        )
        # Traverses the whole zone: it fills, it is not invalidated.
        broker.on_bar(bar(NEXT, 2405.0, 2406.0, 2398.0, 2399.0), NEXT)
        self.assertIs(order.state, PendingState.FILLED)

    def test_no_cross_session_cancellation_over_a_weekend_gap(self) -> None:
        broker, order = self._rested()
        # A three-day gap, then a bar that reaches the limit.
        later = FORMATION + timedelta(days=3)
        broker.on_bar(bar(later, 2404.0, 2405.0, 2401.0, 2403.0), later)
        self.assertIs(order.state, PendingState.FILLED)
        self.assertEqual(order.fill_time, later)

    def test_no_rule_produces_a_terminal_non_fill_state(self) -> None:
        """Nothing in the implementation can currently expire or cancel."""
        broker, order = self._rested()
        for step in range(1, 50):
            moment = FORMATION + timedelta(minutes=5 * step)
            broker.on_bar(bar(moment, 2410.0, 2411.0, 2409.0, 2410.5), moment)
        self.assertNotIn(
            order.state,
            (PendingState.EXPIRED, PendingState.INVALIDATED, PendingState.CANCELLED),
        )


if __name__ == "__main__":
    unittest.main()
