"""Phase 5A shadow equivalence: canonical domain versus the legacy exit path.

The adapter runs beside the paper broker and changes nothing. These tests are
the evidence that the canonical domain reaches the **same** decisions as the
existing engine wherever both have an equivalent concept, and they classify the
places where it necessarily does more.

The oracle, stated once
-----------------------
Comparison is **event-level**, not outcome-level, and it has a validity window:

* **Before the first canonical stop promotion** the two systems must agree
  exactly -- same bar, same closure reason, same requested level.
* **From the first promotion onward** the canonical stop sits somewhere the
  legacy stop never does, so exits are no longer expected to match. Differences
  there are classified, not asserted.

An event the legacy representation cannot express -- the 1R partial and the
stop promotion that follows it -- is a ``NEW_CANONICAL_EVENT``, never an
equivalence failure.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.symbols import XAUUSD_2DIGIT
from core.trade_model import ClosureReason, PositionLifecycle, StopState
from core.types import Side
from core.units import Pips
from execution.broker import PositionState
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import PaperBroker
from execution.trade_adapter import ShadowEventKind, ShadowTradeAdapter

SPEC = XAUUSD_2DIGIT
T0 = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
NO_COST = FillModel(spread=Pips(0.0), slippage=Pips(0.0))

ENTRY = 2450.0
STOP = 2420.0          # R = 30
TARGET = 2540.0        # tp_ratio 3.0
ONE_R = 2480.0
TWO_R = 2510.0


def bar(minutes: int, *, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {
            "time": pd.Timestamp(T0 + timedelta(minutes=minutes)),
            "open": open_, "high": high, "low": low, "close": close,
        }
    )


class ShadowHarness(unittest.TestCase):
    """A broker with one open BUY, shadowed by the canonical domain."""

    policy = IntrabarPolicy.CONSERVATIVE
    volume = 1.00
    target: float | None = TARGET

    def setUp(self) -> None:
        self.broker = PaperBroker(SPEC, NO_COST, intrabar_policy=self.policy)
        self.adapter = ShadowTradeAdapter(SPEC, NO_COST)
        self.broker.submit_market_order(
            side=Side.BUY,
            volume=self.volume,
            stop_loss=STOP,
            take_profit=self.target,
            decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=ENTRY, high=2451.0, low=2449.0, close=2450.5),
        )
        self.position = self.broker.open_positions()[0]
        self.canonical_id = self.adapter.adopt(self.position)

    def feed(self, *bars: pd.Series) -> list:
        """Drive both systems over the same bars, broker first."""
        closed = []
        for candidate in bars:
            bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
            closed.extend(self.broker.on_bar(candidate, bar_time))
            self.adapter.observe(candidate, bar_time)
        return closed

    def kinds(self) -> list[ShadowEventKind]:
        return [event.kind for event in self.adapter.events]

    def first(self, kind: ShadowEventKind):
        for event in self.adapter.events:
            if event.kind is kind:
                return event
        return None


class Adoption(ShadowHarness):
    """A filled position becomes a canonical position, at the fill."""

    def test_the_position_is_adopted_with_canonical_identity(self) -> None:
        self.assertIsNotNone(self.canonical_id)
        self.assertTrue(self.canonical_id.startswith("XAUUSD-20260319T090500-BUY-"))

    def test_the_actual_fill_price_becomes_the_canonical_entry(self) -> None:
        state = self.adapter.state_for(self.position.position_id)
        self.assertAlmostEqual(state.entry_price, self.position.entry_price, places=9)

    def test_the_original_stop_and_r_come_from_the_fill(self) -> None:
        state = self.adapter.state_for(self.position.position_id)
        self.assertAlmostEqual(state.original_stop_price, STOP, places=9)
        self.assertAlmostEqual(state.r, 30.0, places=9)
        self.assertAlmostEqual(state.m1r, ONE_R, places=9)
        self.assertAlmostEqual(state.m2r, TWO_R, places=9)

    def test_the_canonical_target_equals_the_legacy_target(self) -> None:
        """tp_ratio is reconstructed, so the ladder is the only difference."""
        state = self.adapter.state_for(self.position.position_id)
        self.assertAlmostEqual(state.target, self.position.take_profit, places=9)

    def test_adoption_is_idempotent(self) -> None:
        again = self.adapter.adopt(self.position)
        self.assertEqual(again, self.canonical_id)
        opened = [k for k in self.kinds() if k is ShadowEventKind.POSITION_OPENED]
        self.assertEqual(len(opened), 1)

    def test_the_broker_position_is_untouched_by_adoption(self) -> None:
        self.assertAlmostEqual(self.position.remaining_volume, self.volume, places=9)
        self.assertAlmostEqual(self.position.stop_loss, STOP, places=9)
        self.assertEqual(self.position.volume_closed, 0.0)


class EquivalenceBeforeAnyPromotion(ShadowHarness):
    """Inside the validity window both systems must agree exactly."""

    def test_a_stop_bar_closes_both_on_the_same_bar_for_the_same_reason(self) -> None:
        closed = self.feed(bar(5, open_=2440.0, high=2445.0, low=2419.0, close=2425.0))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)

        event = self.first(ShadowEventKind.POSITION_CLOSED)
        self.assertIsNotNone(event)
        self.assertIs(event.reason, ClosureReason.STOP)
        self.assertEqual(event.bar_time, closed[0].exit_time)
        self.assertAlmostEqual(event.executed_price, closed[0].exit_price, places=9)

    def test_a_gapped_stop_agrees_on_the_observed_reference(self) -> None:
        closed = self.feed(bar(5, open_=2400.0, high=2405.0, low=2395.0, close=2402.0))
        event = self.first(ShadowEventKind.CLOSE_REQUESTED)
        self.assertAlmostEqual(event.requested_level, STOP, places=9)
        self.assertAlmostEqual(event.observed_reference, 2400.0, places=9)
        self.assertAlmostEqual(event.executed_price, closed[0].exit_price, places=9)

    def test_a_bar_touching_neither_level_leaves_both_open(self) -> None:
        closed = self.feed(bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0))
        self.assertEqual(closed, [])
        state = self.adapter.state_for(self.position.position_id)
        self.assertIs(state.lifecycle, PositionLifecycle.OPEN)
        self.assertEqual(
            [k for k in self.kinds() if k is not ShadowEventKind.POSITION_OPENED], []
        )

    def test_an_ambiguous_bar_is_flagged_by_both(self) -> None:
        closed = self.feed(bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0))
        self.assertTrue(closed[0].was_ambiguous_exit)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)

        event = self.first(ShadowEventKind.POSITION_CLOSED)
        self.assertTrue(event.ambiguous, "the domain flags the same ambiguity")
        self.assertIs(event.reason, ClosureReason.STOP, "adverse-first, as spec 11.2")


class NewCanonicalEvents(ShadowHarness):
    """Events the legacy representation cannot express. Not failures."""

    def test_reaching_1r_produces_a_partial_the_legacy_path_has_no_concept_of(self) -> None:
        closed = self.feed(bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0))
        self.assertEqual(closed, [], "the legacy path sees nothing at 1R")

        partial = self.first(ShadowEventKind.PARTIAL_CLOSE)
        self.assertIsNotNone(partial)
        self.assertTrue(partial.canonical_only, "classified NEW_CANONICAL_EVENT")
        self.assertEqual(partial.steps, 50, "floor(100/2)")
        self.assertAlmostEqual(partial.requested_level, ONE_R, places=9)

    def test_the_stop_promotion_that_follows_is_also_canonical_only(self) -> None:
        self.feed(bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0))
        promotion = self.first(ShadowEventKind.STOP_PROMOTED)
        self.assertIsNotNone(promotion)
        self.assertTrue(promotion.canonical_only)
        self.assertIs(promotion.stop_state, StopState.BREAKEVEN)
        self.assertAlmostEqual(promotion.stop_price, ENTRY, places=9)

    def test_the_broker_stop_is_not_moved_by_the_shadow(self) -> None:
        """The whole point of shadow mode."""
        self.feed(bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0))
        self.assertAlmostEqual(self.position.stop_loss, STOP, places=9)
        self.assertAlmostEqual(self.position.remaining_volume, self.volume, places=9)
        self.assertTrue(self.position.is_open)

    def test_reaching_2r_promotes_again_and_still_closes_nothing(self) -> None:
        self.feed(bar(5, open_=2460.0, high=2515.0, low=2459.0, close=2512.0))
        promotions = [
            e for e in self.adapter.events if e.kind is ShadowEventKind.STOP_PROMOTED
        ]
        self.assertEqual(len(promotions), 2)
        self.assertIs(promotions[-1].stop_state, StopState.LOCKED_1R)
        self.assertAlmostEqual(promotions[-1].stop_price, ONE_R, places=9)
        self.assertTrue(self.position.is_open)

    def test_a_partial_is_recorded_once_in_the_fill_log(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2482.0, high=2486.0, low=2481.0, close=2484.0),
        )
        partials = [
            e for e in self.adapter.events if e.kind is ShadowEventKind.PARTIAL_CLOSE
        ]
        self.assertEqual(len(partials), 1, "the milestone fires once")
        self.assertEqual(len(self.adapter.fill_log), 1)


class DivergenceAfterPromotionIsAttributed(ShadowHarness):
    """Outside the validity window, differences are classified, not asserted."""

    def test_a_retrace_to_entry_stops_the_canonical_position_only(self) -> None:
        """After breakeven, the canonical stop sits where the legacy one never
        does. This is the documented consequence of the ladder."""
        closed = self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2470.0, high=2472.0, low=2449.0, close=2452.0),
        )
        self.assertEqual(closed, [], "the legacy stop at 2420 was not reached")

        closure = self.first(ShadowEventKind.POSITION_CLOSED)
        self.assertIsNotNone(closure, "the canonical breakeven stop was reached")
        self.assertIs(closure.reason, ClosureReason.STOP)

        requested = self.first(ShadowEventKind.CLOSE_REQUESTED)
        self.assertAlmostEqual(
            requested.requested_level, ENTRY, places=9,
            msg="the stop that fired is the promoted one, at entry",
        )

    def test_the_full_ladder_produces_one_position_and_two_exits(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2515.0, low=2489.0, close=2512.0),
            bar(15, open_=2520.0, high=2545.0, low=2519.0, close=2542.0),
        )
        exits = [
            e for e in self.adapter.events
            if e.kind in (ShadowEventKind.PARTIAL_CLOSE, ShadowEventKind.POSITION_CLOSED)
        ]
        self.assertEqual(len(exits), 2, "one partial and one final")
        self.assertEqual(len(self.adapter.fill_log), 2)
        self.assertEqual(
            len([e for e in self.adapter.events if e.kind is ShadowEventKind.POSITION_OPENED]),
            1,
            "still one position, never two trades",
        )
        state = self.adapter.state_for(self.position.position_id)
        self.assertIs(state.lifecycle, PositionLifecycle.CLOSED)
        self.assertIs(state.closure_reason, ClosureReason.TARGET)


class ShadowChangesNothing(ShadowHarness):
    """The invariants Phase 5A exists to protect."""

    def test_bars_held_is_unaffected_by_the_shadow(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2482.0, high=2486.0, low=2481.0, close=2484.0),
        )
        self.assertEqual(self.position.bars_held, 2)

    def test_the_legacy_outcome_is_identical_with_and_without_a_shadow(self) -> None:
        """Run the same bars on a broker with no adapter and compare."""
        lonely = PaperBroker(SPEC, NO_COST, intrabar_policy=self.policy)
        lonely.submit_market_order(
            side=Side.BUY, volume=self.volume, stop_loss=STOP, take_profit=TARGET,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=ENTRY, high=2451.0, low=2449.0, close=2450.5),
        )
        bars = [
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        ]
        for candidate in bars:
            lonely.on_bar(candidate, pd.Timestamp(candidate["time"]).to_pydatetime())
        shadowed = self.feed(*bars)

        alone = lonely.closed_positions()
        self.assertEqual(len(alone), 1)
        self.assertEqual(len(shadowed), 1)
        for attribute in ("state", "exit_price", "exit_time", "bars_held",
                          "was_ambiguous_exit", "volume"):
            with self.subTest(field=attribute):
                self.assertEqual(
                    getattr(shadowed[0], attribute), getattr(alone[0], attribute)
                )


class PolicyIsAnnotationOnly(ShadowHarness):
    """D16: the domain decides; IntrabarPolicy never selects the exit."""

    policy = IntrabarPolicy.OPTIMISTIC

    def test_the_domain_resolves_adverse_first_whatever_the_policy_says(self) -> None:
        closed = self.feed(bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0))
        self.assertIs(
            closed[0].state, PositionState.CLOSED_TARGET,
            "the legacy engine still follows its policy in shadow mode",
        )
        event = self.first(ShadowEventKind.POSITION_CLOSED)
        self.assertIs(
            event.reason, ClosureReason.STOP,
            "the domain resolves adverse-first regardless of the broker policy",
        )
        self.assertTrue(event.ambiguous)


class AdoptionRefusals(ShadowHarness):
    """A position the canonical model cannot describe is skipped, with a reason."""

    target = None

    def test_a_position_without_a_target_is_skipped_not_guessed(self) -> None:
        self.assertIsNone(self.canonical_id)
        skip = self.first(ShadowEventKind.SKIPPED)
        self.assertIsNotNone(skip)
        self.assertIn("no target", skip.detail)

    def test_a_skipped_position_still_runs_normally_in_the_broker(self) -> None:
        closed = self.feed(bar(5, open_=2440.0, high=2445.0, low=2419.0, close=2425.0))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)


if __name__ == "__main__":
    unittest.main()
