"""Contract tests for the canonical trade-management model.

Source of truth
---------------
``docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md`` at ``adbbb05``. Every
expectation below cites the section it comes from. **Nothing here is derived
from** ``trade_manager.py``, ``order_execution.py`` or ``paper_broker.py``:
DD1 demoted all three to historical evidence, so agreeing with them is a
coincidence, never a justification.

Status
------
``core.trade_model`` does not exist yet. While it is absent every contract test
**skips** with an explicit reason and :class:`CanonicalImplementationGate`
**fails**, so the outstanding work is visible in one place instead of fifty.
Delete that one gate test when the module lands. The contract tests then run at
full strength -- they were never weakened to accommodate the absence.

The API this contract requires
------------------------------
The specification fixes the domain vocabulary but not the Python surface, so
these tests pin the surface. Renaming is cheap now and expensive later.

Types::

    StopState           ORIGINAL | BREAKEVEN | LOCKED_1R          (spec 7.1)
    PositionLifecycle   OPEN | CLOSED                             (spec 8.2)
    ClosureReason       STOP | TARGET | EXTERNAL | END_OF_DATA | MANUAL   (8.3)
    Milestone           M1R | M2R | TARGET                        (spec 6)
    EventType           PARTIAL_CLOSE_REQUESTED | STOP_MODIFY_REQUESTED
                        | CLOSE_REQUESTED                         (spec 11.1)

Construction and evaluation::

    open_position(*, side, fill_price, original_stop_price, tp_ratio,
                  steps, opened_at) -> TradeState
    PriceObservation(time=, open=, high=, low=, close=)
    PriceObservation.from_price(time, price)
    evaluate(state, observation) -> EvaluationResult(state, events, ambiguous)

Broker boundary (spec 16, four layers)::

    apply_broker_result(state, result) -> TradeState
    PartialCloseFilled(steps_closed=) / PartialCloseRejected(reason=)
    StopModifyConfirmed(stop_price=, to_state=) / StopModifyRejected(reason=)
    CloseFilled(reason=, fill_price=, steps_closed=) / CloseRejected(reason=)
    QuantityReconciled(steps_remaining=) / PositionGone()

Quantity boundary (spec 5.1)::

    steps_to_lots(steps, volume_step) -> float
    lots_to_steps(lots, volume_step) -> int

Portfolio guard (spec 24 MUST NOT 6, pending R2)::

    may_open_position(open_states, side) -> bool

``TradeState`` is frozen and exposes: ``side``, ``entry_price``,
``original_stop_price``, ``r``, ``m1r``, ``m2r``, ``target``, ``tp_ratio``,
``steps_at_entry``, ``steps_remaining``, ``milestones_consumed``,
``stop_state_intended``, ``stop_state_confirmed``, ``effective_stop_price``,
``lifecycle``, ``closure_reason``, ``pending_close_reason``,
``last_evaluated_time``, ``anomalies``, ``is_open``, ``is_closed``.

Two readings reconciled, and reported as an ambiguity
-----------------------------------------------------
Spec 11.1 says a stop hit sets ``state := CLOSED``; spec 16 says a position
"must not be marked CLOSED on an unconfirmed close" and MUST #16 says canonical
state updates only from broker results. These tests take the reading that
satisfies both MUSTs: ``evaluate`` emits ``CLOSE_REQUESTED`` and records
``pending_close_reason``; ``CLOSED`` arrives via ``apply_broker_result``. In
paper and replay the adapter performs both steps synchronously, which is what
spec 11.1 describes. Tests that do not depend on the distinction assert
``is_closed`` rather than a representation, so they hold under either reading.

Executable pricing stays outside the domain
-------------------------------------------
Spec 12 names four layers; spec 18 puts the cost/fill model in the execution
adapter. A ``CLOSE_REQUESTED`` event therefore carries ``requested_level`` and
``observed_reference`` only. The executable price and the recorded fill come
back through ``CloseFilled``. Keeping the cost model out of ``core`` also keeps
CONVENTIONS section 7 (``core`` stays pure) intact.
"""

from __future__ import annotations

import ast
import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MODULE = "core.trade_model"
CANONICAL_SOURCE = REPO_ROOT / "core" / "trade_model.py"

try:  # pragma: no cover - the whole point is that this usually fails today
    _tm = importlib.import_module(CANONICAL_MODULE)
except ModuleNotFoundError:
    _tm = None

ABSENT = (
    f"{CANONICAL_MODULE} does not exist yet. These are contract tests written "
    "before the implementation; see docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md."
)

# XAUUSD_2DIGIT: volume_min == volume_step == 0.01 (core/symbols.py).
VOLUME_STEP = 0.01

# entry_engine.detect_regime, mirrored in backtest/baseline.py:336-341.
REGIME_TP_RATIOS = {
    "MICRO_SCALP": 1.5,
    "DEAD_CALM": 1.5,
    "REGIME_SCALP": 2.0,
    "INTRADAY_SWING": 3.0,
}

T0 = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)


def _t(minutes: int) -> datetime:
    """Observation time ``minutes`` after the reference instant."""
    return T0 + timedelta(minutes=minutes)


class CanonicalImplementationGate(unittest.TestCase):
    """The one test that records that the canonical model is not written yet.

    It fails until ``core/trade_model.py`` exists. That single failure is the
    honest signal; the contract tests below skip so a genuinely new regression
    elsewhere in the suite stays visible. **Delete this class when the module
    lands** -- the contract tests become the gate at that point.
    """

    def test_canonical_trade_model_module_exists(self) -> None:
        self.assertIsNotNone(
            _tm,
            "core/trade_model.py has not been implemented. The contract tests in "
            "this module are skipped until it exists. This failure is expected "
            "for Phase 4B and is not a regression.",
        )


class ContractTest(unittest.TestCase):
    """Base class: skips while the implementation is absent, never weakens.

    A missing *module* skips. A module that exists but lacks a required name
    **fails**, because that is a contract violation rather than an absence.
    """

    def setUp(self) -> None:
        if _tm is None:
            self.skipTest(ABSENT)

    # -- API access -----------------------------------------------------
    def api(self, name: str):
        """Return a required attribute, failing with the contract it breaks."""
        if not hasattr(_tm, name):
            self.fail(
                f"{CANONICAL_MODULE} must expose {name!r}; see the API contract "
                "in this module's docstring."
            )
        return getattr(_tm, name)

    # -- builders -------------------------------------------------------
    def open_buy(self, *, fill=2450.0, stop=2420.0, tp_ratio=3.0, steps=6):
        """A BUY with R = 30.00: 1R 2480, 2R 2510, target at tp_ratio x R."""
        return self.api("open_position")(
            side=self.side().BUY, fill_price=fill, original_stop_price=stop,
            tp_ratio=tp_ratio, steps=steps, opened_at=T0,
        )

    def open_sell(self, *, fill=2450.0, stop=2480.0, tp_ratio=3.0, steps=6):
        """A SELL with R = 30.00: 1R 2420, 2R 2390."""
        return self.api("open_position")(
            side=self.side().SELL, fill_price=fill, original_stop_price=stop,
            tp_ratio=tp_ratio, steps=steps, opened_at=T0,
        )

    def side(self):
        from core.types import Side
        return Side

    def bar(self, minutes, *, open_, high, low, close):
        return self.api("PriceObservation")(
            time=_t(minutes), open=open_, high=high, low=low, close=close,
        )

    def touch(self, minutes, price, *, base=2450.0):
        """An observation whose range reaches ``price`` and closes back at base."""
        return self.api("PriceObservation")(
            time=_t(minutes), open=base, high=max(base, price),
            low=min(base, price), close=base,
        )

    def evaluate(self, state, observation):
        return self.api("evaluate")(state, observation)

    def event_types(self, result):
        return [event.type for event in result.events]

    def events_of(self, result, event_type):
        return [e for e in result.events if e.type == event_type]


# =====================================================================
# 1. R
# =====================================================================
class RDefinition(ContractTest):
    """Spec 4: R = abs(actual fill - original stop), frozen at creation."""

    def test_r_is_the_absolute_distance_from_actual_fill_to_original_stop(self) -> None:
        for name, state, expected in (
            ("BUY", self.open_buy(fill=2450.0, stop=2420.0), 30.0),
            ("SELL", self.open_sell(fill=2450.0, stop=2480.0), 30.0),
        ):
            with self.subTest(side=name):
                self.assertAlmostEqual(state.r, expected, places=9)

    def test_r_is_positive_for_both_directions(self) -> None:
        for name, state in (("BUY", self.open_buy()), ("SELL", self.open_sell())):
            with self.subTest(side=name):
                self.assertGreater(state.r, 0.0)

    def test_r_is_frozen_after_entry_however_the_stop_moves(self) -> None:
        """Spec 4.1: moving the stop never redefines R."""
        stop_state = self.api("StopState")
        for price, expected in ((2480.0, stop_state.BREAKEVEN),
                                (2510.0, stop_state.LOCKED_1R)):
            with self.subTest(promoted_to=expected):
                state = self.open_buy()
                after = self.evaluate(state, self.touch(5, price)).state
                self.assertEqual(after.stop_state_intended, expected)
                self.assertAlmostEqual(after.r, state.r, places=9)

    def test_r_uses_the_actual_fill_price_not_the_intended_limit(self) -> None:
        """Spec 4.1/13: a gapped or cost-adjusted fill defines the geometry."""
        intended_limit = 2450.0
        actual_fill = 2448.0  # filled better, e.g. the bar gapped through the limit
        state = self.open_buy(fill=actual_fill, stop=2420.0)
        self.assertAlmostEqual(state.entry_price, actual_fill, places=9)
        self.assertAlmostEqual(state.r, 28.0, places=9)
        self.assertNotAlmostEqual(state.r, abs(intended_limit - 2420.0), places=9)

    def test_a_fill_that_destroys_the_geometry_is_rejected_not_clamped(self) -> None:
        """Spec 4.3: R == 0, or a stop on the wrong side, must raise."""
        cases = (
            ("zero R", dict(fill=2450.0, stop=2450.0)),
            ("BUY stop above fill", dict(fill=2450.0, stop=2460.0)),
        )
        for label, kwargs in cases:
            with self.subTest(case=label):
                with self.assertRaises(Exception):
                    self.open_buy(**kwargs)


# =====================================================================
# 2. Final TP
# =====================================================================
class FinalTarget(ContractTest):
    """Spec 4.2 / 6.1: TP = actual fill +/- tp_ratio x R, recomputed at fill."""

    def test_the_target_is_the_fill_offset_by_ratio_times_r_on_the_correct_side(self) -> None:
        """Every current regime ratio, both directions."""
        for ratio in (1.5, 2.0, 3.0):
            with self.subTest(tp_ratio=ratio, side="BUY"):
                state = self.open_buy(fill=2450.0, stop=2420.0, tp_ratio=ratio)
                self.assertAlmostEqual(state.target, 2450.0 + ratio * 30.0, places=9)
            with self.subTest(tp_ratio=ratio, side="SELL"):
                state = self.open_sell(fill=2450.0, stop=2480.0, tp_ratio=ratio)
                self.assertAlmostEqual(state.target, 2450.0 - ratio * 30.0, places=9)

    def test_target_uses_the_actual_fill_not_the_intended_entry(self) -> None:
        """Spec 4.2: the behaviour change from carrying intent.take_profit."""
        state = self.open_buy(fill=2448.0, stop=2420.0, tp_ratio=3.0)
        self.assertAlmostEqual(state.target, 2448.0 + 3.0 * 28.0, places=9)

    def test_the_rr_identity_holds_for_every_position(self) -> None:
        """Spec 4.2 / MUST 4: realised ratio equals tp_ratio exactly."""
        for ratio in (1.5, 2.0, 3.0):
            for label, state in (
                ("BUY", self.open_buy(fill=2448.37, stop=2419.11, tp_ratio=ratio)),
                ("SELL", self.open_sell(fill=2448.37, stop=2477.63, tp_ratio=ratio)),
            ):
                with self.subTest(tp_ratio=ratio, side=label):
                    reward = abs(state.target - state.entry_price)
                    self.assertAlmostEqual(reward / state.r, ratio, places=9)

    def test_regime_tp_ratios_are_unchanged(self) -> None:
        """Spec 19: the four values stay as the repository has them."""
        from backtest.baseline import REGIME_TP_RATIO
        self.assertEqual(dict(REGIME_TP_RATIO), REGIME_TP_RATIOS)


# =====================================================================
# 3. 1R milestone
# =====================================================================
class OneRMilestone(ContractTest):
    """Spec 6.2 / 5.2: detection, the partial, and single consumption."""

    def test_one_r_is_detected_on_the_bar_range_not_the_close(self) -> None:
        for label, state, level in (
            ("BUY", self.open_buy(), 2480.0),
            ("SELL", self.open_sell(), 2420.0),
        ):
            with self.subTest(side=label):
                result = self.evaluate(state, self.touch(5, level))
                self.assertIn(
                    self.api("Milestone").M1R, result.state.milestones_consumed
                )

    def test_one_r_requests_exactly_half_of_the_original_steps(self) -> None:
        state = self.open_buy(steps=6)
        result = self.evaluate(state, self.touch(5, 2480.0))
        requests = self.events_of(result, self.api("EventType").PARTIAL_CLOSE_REQUESTED)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].steps, 3)

    def test_remaining_steps_after_a_confirmed_partial_are_correct(self) -> None:
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        self.assertEqual(state.steps_remaining, 3)
        self.assertEqual(state.steps_at_entry, 6)

    def test_one_r_cannot_execute_twice(self) -> None:
        """Spec 6.3 / 15.2: the milestone is consumed once, ever."""
        state = self.open_buy(steps=6)
        first = self.evaluate(state, self.touch(5, 2480.0))
        state = self.api("apply_broker_result")(
            first.state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        second = self.evaluate(state, self.touch(10, 2485.0))
        self.assertEqual(
            self.events_of(second, self.api("EventType").PARTIAL_CLOSE_REQUESTED), []
        )
        self.assertEqual(second.state.steps_remaining, 3)

    def test_one_r_does_not_redefine_r_or_the_levels(self) -> None:
        state = self.open_buy()
        before = (state.r, state.m1r, state.m2r, state.target)
        after = self.evaluate(state, self.touch(5, 2480.0)).state
        self.assertEqual((after.r, after.m1r, after.m2r, after.target), before)

    def test_the_one_r_level_is_direction_aware(self) -> None:
        """Spec 6.1: never 'entry + R' for both sides."""
        self.assertAlmostEqual(self.open_buy().m1r, 2480.0, places=9)
        self.assertAlmostEqual(self.open_sell().m1r, 2420.0, places=9)


# =====================================================================
# 4. Quantity
# =====================================================================
class QuantityRules(ContractTest):
    """Spec 5: integer steps, floor rounding, the one-step case."""

    def test_the_partial_is_floor_of_half_the_original_steps(self) -> None:
        """Spec 5.2, including every size in INTRADAY_LOT_SIZE_MIN..MAX."""
        expected = {1: 0, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 9: 4, 10: 5}
        for steps, to_close in expected.items():
            with self.subTest(steps=steps):
                result = self.evaluate(
                    self.open_buy(steps=steps), self.touch(5, 2480.0)
                )
                requests = self.events_of(
                    result, self.api("EventType").PARTIAL_CLOSE_REQUESTED
                )
                if to_close == 0:
                    self.assertEqual(requests, [], "no order may be sent for 0 steps")
                else:
                    self.assertEqual(requests[0].steps, to_close)

    def test_a_single_step_position_consumes_one_r_without_a_partial(self) -> None:
        """Spec 5.2: at the configured minimum size no partial is possible."""
        state = self.open_buy(steps=1)
        result = self.evaluate(state, self.touch(5, 2480.0))
        self.assertEqual(
            self.events_of(result, self.api("EventType").PARTIAL_CLOSE_REQUESTED), []
        )
        self.assertIn(self.api("Milestone").M1R, result.state.milestones_consumed)
        self.assertEqual(result.state.steps_remaining, 1)

    def test_steps_are_integers_and_lots_are_derived_at_the_boundary(self) -> None:
        """Spec 5.1 / MUST 5."""
        state = self.open_buy(steps=6)
        self.assertIsInstance(state.steps_at_entry, int)
        self.assertIsInstance(state.steps_remaining, int)
        self.assertAlmostEqual(
            self.api("steps_to_lots")(6, VOLUME_STEP), 0.06, places=9
        )
        self.assertEqual(self.api("lots_to_steps")(0.06, VOLUME_STEP), 6)

    def test_lots_to_steps_rounds_down(self) -> None:
        """CONVENTIONS section 9: rounding volume up takes unauthorised risk."""
        self.assertEqual(self.api("lots_to_steps")(0.069, VOLUME_STEP), 6)

    def test_remaining_steps_never_increase(self) -> None:
        state = self.open_buy(steps=6)
        seen = [state.steps_remaining]
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        seen.append(state.steps_remaining)
        state = self.evaluate(state, self.touch(10, 2510.0)).state
        seen.append(state.steps_remaining)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_a_closing_event_requests_all_remaining_steps(self) -> None:
        """Spec 5.3: close-all means the whole remainder, in one request."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        result = self.evaluate(state, self.touch(10, 2540.0))
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].steps, 3)


# =====================================================================
# 5. Breakeven
# =====================================================================
class BreakevenTransition(ContractTest):
    """Spec 7 / 5.4: the 1R stop move, and its independence from the partial."""

    def test_one_r_promotes_the_intended_stop_to_breakeven_at_the_entry_price(self) -> None:
        for label, state in (("BUY", self.open_buy(fill=2450.0)),
                             ("SELL", self.open_sell(fill=2450.0))):
            with self.subTest(side=label):
                result = self.evaluate(state, self.touch(5, state.m1r))
                self.assertEqual(
                    result.state.stop_state_intended,
                    self.api("StopState").BREAKEVEN,
                )
                moves = self.events_of(
                    result, self.api("EventType").STOP_MODIFY_REQUESTED
                )
                self.assertAlmostEqual(moves[0].stop_price, 2450.0, places=9)

    def test_a_rejected_partial_does_not_suppress_the_stop_move(self) -> None:
        """Spec 5.4: the two effects of the 1R event are independent."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseRejected")(reason="broker rejected")
        )
        self.assertEqual(state.stop_state_intended, self.api("StopState").BREAKEVEN)
        self.assertEqual(state.steps_remaining, 6)

    def test_the_stop_is_not_re_requested_once_confirmed(self) -> None:
        """Spec 15.2: repeated evaluations above 1R do not re-modify the stop."""
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2450.0, to_state=self.api("StopState").BREAKEVEN
            ),
        )
        for minute in (10, 15, 20):
            with self.subTest(minute=minute):
                result = self.evaluate(state, self.touch(minute, 2485.0))
                self.assertEqual(
                    self.events_of(
                        result, self.api("EventType").STOP_MODIFY_REQUESTED
                    ),
                    [],
                )
                state = result.state

    def test_an_unconfirmed_stop_move_is_re_requested_to_the_same_price(self) -> None:
        """Spec 7.3 / 16: idempotent retry while confirmed lags intended."""
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("StopModifyRejected")(reason="broker rejected")
        )
        self.assertEqual(state.stop_state_confirmed, self.api("StopState").ORIGINAL)
        again = self.evaluate(state, self.touch(10, 2485.0))
        moves = self.events_of(again, self.api("EventType").STOP_MODIFY_REQUESTED)
        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves[0].stop_price, 2450.0, places=9)

    def test_risk_statements_use_the_confirmed_stop_not_the_intended_one(self) -> None:
        """Spec 7.3: effective stop is the confirmed one."""
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("StopModifyRejected")(reason="broker rejected")
        )
        self.assertAlmostEqual(state.effective_stop_price, 2420.0, places=9)


# =====================================================================
# 6. 2R
# =====================================================================
class TwoRMilestone(ContractTest):
    """Spec 7.1 / 6: the second stop promotion, with no further partial."""

    def test_two_r_promotes_the_stop_to_entry_plus_or_minus_one_r(self) -> None:
        for label, state, expected in (
            ("BUY", self.open_buy(), 2480.0),
            ("SELL", self.open_sell(), 2420.0),
        ):
            with self.subTest(side=label):
                result = self.evaluate(state, self.touch(5, state.m2r))
                self.assertEqual(
                    result.state.stop_state_intended,
                    self.api("StopState").LOCKED_1R,
                )
                moves = self.events_of(
                    result, self.api("EventType").STOP_MODIFY_REQUESTED
                )
                self.assertAlmostEqual(moves[-1].stop_price, expected, places=9)

    def test_two_r_closes_no_additional_quantity(self) -> None:
        """Spec 3 Q5 / 23: no partial at 2R."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        result = self.evaluate(state, self.touch(10, 2510.0))
        self.assertEqual(
            self.events_of(result, self.api("EventType").PARTIAL_CLOSE_REQUESTED), []
        )
        self.assertEqual(result.state.steps_remaining, 3)
        self.assertTrue(result.state.is_open)

    def test_two_r_cannot_execute_repeatedly(self) -> None:
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2510.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2480.0, to_state=self.api("StopState").LOCKED_1R
            ),
        )
        result = self.evaluate(state, self.touch(10, 2515.0))
        self.assertEqual(
            self.events_of(result, self.api("EventType").STOP_MODIFY_REQUESTED), []
        )
        self.assertEqual(
            result.state.stop_state_confirmed, self.api("StopState").LOCKED_1R
        )


# =====================================================================
# 7. Target
# =====================================================================
class TargetClosure(ContractTest):
    """Spec 11.1 step 3c: the target closes the remainder, once."""

    def test_the_target_requests_closure_of_all_remaining_quantity(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(state, self.touch(5, 2540.0))
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").TARGET)

    def test_a_confirmed_target_fill_closes_the_position(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").TARGET,
                fill_price=2540.0,
                steps_closed=state.steps_remaining,
            ),
        )
        self.assertTrue(state.is_closed)
        self.assertEqual(state.closure_reason, self.api("ClosureReason").TARGET)
        self.assertEqual(state.steps_remaining, 0)

    def test_a_closed_position_cannot_close_again(self) -> None:
        """Spec 15.2 / MUST 18."""
        state = self.open_buy(tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").TARGET,
                fill_price=2540.0,
                steps_closed=state.steps_remaining,
            ),
        )
        result = self.evaluate(state, self.touch(10, 2545.0))
        self.assertEqual(result.events, ())
        self.assertTrue(result.state.is_closed)

    def test_the_target_milestone_is_consumed(self) -> None:
        state = self.open_buy(tp_ratio=3.0)
        after = self.evaluate(state, self.touch(5, 2540.0)).state
        self.assertIn(self.api("Milestone").TARGET, after.milestones_consumed)


# =====================================================================
# 8. Event ordering
# =====================================================================
class EventOrdering(ContractTest):
    """Spec 11.3: the nine cases, asserted on outcome not on implementation."""

    def _closed_by_stop(self, result) -> None:
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").STOP)
        self.assertEqual(
            result.state.pending_close_reason, self.api("ClosureReason").STOP
        )

    def test_case_a_one_r_and_stop_reachable_resolves_to_the_stop(self) -> None:
        state = self.open_buy(steps=6)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2419.0, close=2430.0)
        )
        self._closed_by_stop(result)
        self.assertEqual(
            self.events_of(result, self.api("EventType").PARTIAL_CLOSE_REQUESTED), [],
            "no partial may be taken on a bar resolved as a stop-out",
        )
        self.assertEqual(result.state.steps_remaining, 6)
        self.assertEqual(
            result.state.stop_state_intended, self.api("StopState").ORIGINAL
        )
        self.assertNotIn(self.api("Milestone").M1R, result.state.milestones_consumed)

    def test_case_b_two_r_and_stop_reachable_resolves_to_the_stop(self) -> None:
        state = self.open_buy(steps=6)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2515.0, low=2419.0, close=2430.0)
        )
        self._closed_by_stop(result)
        self.assertEqual(
            result.state.stop_state_intended, self.api("StopState").ORIGINAL
        )

    def test_case_c_target_and_stop_reachable_resolves_to_the_stop(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0)
        )
        self._closed_by_stop(result)
        self.assertNotIn(self.api("Milestone").TARGET, result.state.milestones_consumed)

    def test_case_d_one_r_and_two_r_both_fire_in_ascending_order(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2515.0, low=2449.0, close=2512.0)
        )
        consumed = result.state.milestones_consumed
        self.assertIn(self.api("Milestone").M1R, consumed)
        self.assertIn(self.api("Milestone").M2R, consumed)
        self.assertTrue(result.state.is_open)
        self.assertEqual(
            result.state.stop_state_intended, self.api("StopState").LOCKED_1R
        )
        moves = self.events_of(result, self.api("EventType").STOP_MODIFY_REQUESTED)
        self.assertEqual(
            [m.stop_price for m in moves][-1], 2480.0,
            "the last stop request in the evaluation is the LOCKED_1R price",
        )

    def test_case_e_one_r_two_r_and_target_end_in_a_target_closure(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2545.0, low=2449.0, close=2542.0)
        )
        consumed = result.state.milestones_consumed
        for milestone in ("M1R", "M2R", "TARGET"):
            with self.subTest(milestone=milestone):
                self.assertIn(getattr(self.api("Milestone"), milestone), consumed)
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").TARGET)
        partials = self.events_of(
            result, self.api("EventType").PARTIAL_CLOSE_REQUESTED
        )
        self.assertEqual(partials[0].steps, 3, "the 1R partial still happens first")

    def test_case_f_a_stop_after_a_partial_closes_only_the_remainder(self) -> None:
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=3)
        )
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2450.0, to_state=self.api("StopState").BREAKEVEN
            ),
        )
        result = self.evaluate(
            state, self.bar(10, open_=2460.0, high=2461.0, low=2449.0, close=2450.0)
        )
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").STOP)
        self.assertEqual(closes[0].steps, 3, "only the remaining steps are closed")

    def test_case_g_a_gapped_stop_reports_the_observed_reference(self) -> None:
        state = self.open_buy(steps=6)
        result = self.evaluate(
            state, self.bar(5, open_=2400.0, high=2405.0, low=2395.0, close=2402.0)
        )
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertAlmostEqual(closes[0].requested_level, 2420.0, places=9)
        self.assertAlmostEqual(closes[0].observed_reference, 2400.0, places=9)

    def test_case_h_a_gapped_target_reports_the_observed_reference(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(
            state, self.bar(5, open_=2560.0, high=2565.0, low=2558.0, close=2562.0)
        )
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").TARGET)
        self.assertAlmostEqual(closes[0].requested_level, 2540.0, places=9)
        self.assertAlmostEqual(closes[0].observed_reference, 2560.0, places=9)

    def test_case_i_reversal_protection_is_not_part_of_the_model(self) -> None:
        """Spec 10.3 / MUST NOT 3: R1 is unresolved, so nothing may emit it."""
        event_type = self.api("EventType")
        self.assertFalse(
            any("PROTECT" in member.name or "REVERSAL" in member.name
                for member in event_type),
            "reversal protection is UNRESOLVED (spec 10.3) and must not be "
            "implemented; R1 is not decided",
        )

    def test_an_ambiguous_bar_is_flagged(self) -> None:
        """Spec 11.4: ambiguity is recorded so it stays measurable."""
        state = self.open_buy(steps=6, tp_ratio=3.0)
        ambiguous = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0)
        )
        self.assertTrue(ambiguous.ambiguous)
        clean = self.evaluate(
            self.open_buy(steps=6), self.bar(5, open_=2450.0, high=2485.0,
                                             low=2449.0, close=2482.0)
        )
        self.assertFalse(clean.ambiguous)


# =====================================================================
# 9. Stop effective time
# =====================================================================
class StopEffectiveTime(ContractTest):
    """Spec 11.2 / MUST 12: a stop moved in evaluation N binds from N+1."""

    def test_stop_promotion_does_not_apply_to_the_observation_that_caused_it(self) -> None:
        state = self.open_buy(steps=6)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2449.0, close=2451.0)
        )
        self.assertEqual(
            self.events_of(result, self.api("EventType").CLOSE_REQUESTED), [],
            "the bar dipped below the new breakeven stop but not below the old one, "
            "so no closure may occur on this observation",
        )
        self.assertTrue(result.state.is_open)

    def test_the_promoted_stop_binds_on_the_next_observation(self) -> None:
        state = self.open_buy(steps=6)
        state = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2449.0, close=2451.0)
        ).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2450.0, to_state=self.api("StopState").BREAKEVEN
            ),
        )
        result = self.evaluate(
            state, self.bar(10, open_=2451.0, high=2452.0, low=2449.0, close=2449.5)
        )
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").STOP)
        self.assertAlmostEqual(closes[0].requested_level, 2450.0, places=9)

    def test_the_stop_tested_is_the_one_confirmed_before_the_evaluation(self) -> None:
        """Spec 11.1 step 1: the snapshot is the confirmed stop, not the intended."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("StopModifyRejected")(reason="broker rejected")
        )
        result = self.evaluate(
            state, self.bar(10, open_=2451.0, high=2452.0, low=2449.0, close=2450.0)
        )
        self.assertEqual(
            self.events_of(result, self.api("EventType").CLOSE_REQUESTED), [],
            "the breakeven move was rejected, so the original stop is still the "
            "effective one and 2449 does not close the position",
        )


# =====================================================================
# 10. State machine
# =====================================================================
class StateMachineTransitions(ContractTest):
    """Spec 7.2 / 8 / 22: legal transitions, and the forbidden ones."""

    def test_the_stop_state_progression_is_original_breakeven_locked_1r(self) -> None:
        stop_state = self.api("StopState")
        state = self.open_buy()
        self.assertEqual(state.stop_state_confirmed, stop_state.ORIGINAL)

        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2450.0, to_state=stop_state.BREAKEVEN
            ),
        )
        self.assertEqual(state.stop_state_confirmed, stop_state.BREAKEVEN)

        state = self.evaluate(state, self.touch(10, 2510.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2480.0, to_state=stop_state.LOCKED_1R
            ),
        )
        self.assertEqual(state.stop_state_confirmed, stop_state.LOCKED_1R)

    def test_backward_stop_transitions_raise(self) -> None:
        """Spec 7.2: forbidden transitions raise rather than being ignored."""
        stop_state = self.api("StopState")
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2510.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("StopModifyConfirmed")(
                stop_price=2480.0, to_state=stop_state.LOCKED_1R
            ),
        )
        for target_state, price in (
            (stop_state.BREAKEVEN, 2450.0),
            (stop_state.ORIGINAL, 2420.0),
        ):
            with self.subTest(to=target_state):
                with self.assertRaises(Exception):
                    self.api("apply_broker_result")(
                        state,
                        self.api("StopModifyConfirmed")(
                            stop_price=price, to_state=target_state
                        ),
                    )

    def test_an_adverse_stop_price_is_refused_even_within_the_same_state(self) -> None:
        """Spec 7.2: monotonicity is a hard invariant, not a state-list artefact."""
        stop_state = self.api("StopState")
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        with self.assertRaises(Exception):
            self.api("apply_broker_result")(
                state,
                self.api("StopModifyConfirmed")(
                    stop_price=2410.0, to_state=stop_state.BREAKEVEN
                ),
            )

    def test_a_closed_position_cannot_return_to_open(self) -> None:
        state = self.open_buy(tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").TARGET,
                fill_price=2540.0, steps_closed=state.steps_remaining,
            ),
        )
        with self.assertRaises(Exception):
            self.api("apply_broker_result")(
                state, self.api("PartialCloseFilled")(steps_closed=1)
            )

    def test_a_closed_position_executes_no_milestones(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2419.0, close=2430.0)
        )
        state = self.api("apply_broker_result")(
            result.state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").STOP,
                fill_price=2420.0, steps_closed=6,
            ),
        )
        after = self.evaluate(state, self.touch(10, 2510.0))
        self.assertEqual(after.events, ())
        self.assertEqual(after.state.milestones_consumed, state.milestones_consumed)

    def test_the_canonical_state_names_are_exactly_as_specified(self) -> None:
        """Spec 22: the names are part of the contract."""
        self.assertEqual(
            [m.name for m in self.api("StopState")],
            ["ORIGINAL", "BREAKEVEN", "LOCKED_1R"],
        )
        self.assertEqual(
            [m.name for m in self.api("PositionLifecycle")], ["OPEN", "CLOSED"]
        )
        self.assertEqual(
            sorted(m.name for m in self.api("ClosureReason")),
            ["END_OF_DATA", "EXTERNAL", "MANUAL", "STOP", "TARGET"],
        )


# =====================================================================
# 11. Idempotency
# =====================================================================
class Idempotency(ContractTest):
    """Spec 15: repeated and out-of-order evaluation."""

    def test_a_repeated_identical_observation_is_a_no_op(self) -> None:
        state = self.open_buy(steps=6)
        observation = self.touch(5, 2480.0)
        first = self.evaluate(state, observation)
        second = self.evaluate(first.state, observation)
        self.assertEqual(second.events, ())
        self.assertEqual(second.state.steps_remaining, first.state.steps_remaining)

    def test_an_earlier_observation_is_a_no_op(self) -> None:
        """Spec 15.2: the monotonic evaluation-time guard."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(10, 2480.0)).state
        stale = self.evaluate(state, self.touch(5, 2510.0))
        self.assertEqual(stale.events, ())

    def test_ten_observations_above_one_r_produce_exactly_one_partial(self) -> None:
        state = self.open_buy(steps=6)
        partials = 0
        for minute in range(1, 11):
            result = self.evaluate(state, self.touch(minute * 5, 2485.0))
            partials += len(
                self.events_of(result, self.api("EventType").PARTIAL_CLOSE_REQUESTED)
            )
            state = result.state
        self.assertEqual(partials, 1)

    def test_closure_is_not_emitted_twice(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        first = self.evaluate(state, self.touch(5, 2540.0))
        state = self.api("apply_broker_result")(
            first.state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").TARGET,
                fill_price=2540.0, steps_closed=6,
            ),
        )
        second = self.evaluate(state, self.touch(10, 2550.0))
        self.assertEqual(
            self.events_of(second, self.api("EventType").CLOSE_REQUESTED), []
        )

    def test_evaluation_does_not_mutate_the_state_it_was_given(self) -> None:
        """Spec 15.2 / MUST 17: evaluation is a pure function."""
        state = self.open_buy(steps=6)
        snapshot = (
            state.steps_remaining, state.stop_state_intended,
            frozenset(state.milestones_consumed), state.lifecycle,
        )
        self.evaluate(state, self.touch(5, 2480.0))
        self.assertEqual(
            (state.steps_remaining, state.stop_state_intended,
             frozenset(state.milestones_consumed), state.lifecycle),
            snapshot,
        )

    def test_the_same_state_and_observation_always_produce_the_same_events(self) -> None:
        """Spec 18.3 / MUST 20: determinism is what makes the stream comparable."""
        state = self.open_buy(steps=6, tp_ratio=3.0)
        observation = self.bar(5, open_=2450.0, high=2515.0, low=2449.0, close=2512.0)
        first = self.evaluate(state, observation)
        second = self.evaluate(state, observation)
        self.assertEqual(self.event_types(first), self.event_types(second))
        self.assertEqual(first.state, second.state)


# =====================================================================
# 12. LIMIT_FVG hand-off
# =====================================================================
class LimitFvgHandoff(ContractTest):
    """Spec 13: geometry is frozen at the fill, never at the intent."""

    def test_the_fill_price_becomes_the_entry_and_defines_r_and_the_target(self) -> None:
        state = self.open_buy(fill=2448.0, stop=2420.0, tp_ratio=3.0)
        self.assertAlmostEqual(state.entry_price, 2448.0, places=9)
        self.assertAlmostEqual(state.r, 28.0, places=9)
        self.assertAlmostEqual(state.target, 2448.0 + 84.0, places=9)

    def test_the_formation_price_is_not_treated_as_the_entry(self) -> None:
        """Spec 13: the decision/formation price is a request, not a fill."""
        formation_midpoint = 2450.0
        state = self.open_buy(fill=2448.0, stop=2420.0, tp_ratio=3.0)
        self.assertNotAlmostEqual(state.entry_price, formation_midpoint, places=9)
        self.assertNotAlmostEqual(
            state.target, formation_midpoint + 3.0 * 30.0, places=9
        )

    def test_management_may_act_on_the_fill_bar(self) -> None:
        """Spec 13 / R1 measurement: the position exists from the fill onward."""
        state = self.api("open_position")(
            side=self.side().BUY, fill_price=2450.0, original_stop_price=2420.0,
            tp_ratio=3.0, steps=6, opened_at=_t(5),
        )
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2449.0, close=2482.0)
        )
        self.assertIn(self.api("Milestone").M1R, result.state.milestones_consumed)

    def test_a_same_bar_fill_and_stop_resolves_adverse_first(self) -> None:
        state = self.api("open_position")(
            side=self.side().BUY, fill_price=2450.0, original_stop_price=2420.0,
            tp_ratio=3.0, steps=6, opened_at=_t(5),
        )
        result = self.evaluate(
            state, self.bar(5, open_=2450.0, high=2485.0, low=2419.0, close=2430.0)
        )
        closes = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").STOP)

    def test_an_observation_before_the_fill_is_never_evaluated(self) -> None:
        """Spec 13: no management state exists before the position does."""
        state = self.api("open_position")(
            side=self.side().BUY, fill_price=2450.0, original_stop_price=2420.0,
            tp_ratio=3.0, steps=6, opened_at=_t(5),
        )
        earlier = self.evaluate(state, self.touch(1, 2480.0))
        self.assertEqual(earlier.events, ())
        self.assertEqual(earlier.state.milestones_consumed, frozenset())


# =====================================================================
# 13. Gap contract
# =====================================================================
class GapContract(ContractTest):
    """Spec 12: requested level and observed reference, both directions."""

    def test_a_non_gapped_level_is_its_own_observed_reference(self) -> None:
        """Both bars touch the level exactly, so this also pins spec 6.2's
        inclusive comparison: reaching the level is enough."""
        cases = (
            ("BUY stop", self.open_buy(), dict(open_=2450.0, high=2451.0,
                                               low=2420.0, close=2425.0), 2420.0),
            ("SELL stop", self.open_sell(), dict(open_=2450.0, high=2480.0,
                                                 low=2449.0, close=2475.0), 2480.0),
        )
        for label, state, bar_kwargs, level in cases:
            with self.subTest(case=label):
                result = self.evaluate(state, self.bar(5, **bar_kwargs))
                close = self.events_of(
                    result, self.api("EventType").CLOSE_REQUESTED
                )[0]
                self.assertAlmostEqual(close.requested_level, level, places=9)
                self.assertAlmostEqual(close.observed_reference, level, places=9)

    def test_a_gapped_stop_uses_the_bar_open_for_both_sides(self) -> None:
        cases = (
            ("BUY", self.open_buy(), dict(open_=2400.0, high=2405.0,
                                          low=2395.0, close=2402.0), 2420.0, 2400.0),
            ("SELL", self.open_sell(), dict(open_=2500.0, high=2505.0,
                                            low=2495.0, close=2502.0), 2480.0, 2500.0),
        )
        for label, state, bar_kwargs, level, reference in cases:
            with self.subTest(side=label):
                result = self.evaluate(state, self.bar(5, **bar_kwargs))
                close = self.events_of(
                    result, self.api("EventType").CLOSE_REQUESTED
                )[0]
                self.assertEqual(close.reason, self.api("ClosureReason").STOP)
                self.assertAlmostEqual(close.requested_level, level, places=9)
                self.assertAlmostEqual(close.observed_reference, reference, places=9)

    def test_a_gapped_target_uses_the_bar_open_for_both_sides(self) -> None:
        cases = (
            ("BUY", self.open_buy(tp_ratio=3.0),
             dict(open_=2560.0, high=2565.0, low=2558.0, close=2562.0), 2540.0, 2560.0),
            ("SELL", self.open_sell(tp_ratio=3.0),
             dict(open_=2340.0, high=2345.0, low=2335.0, close=2342.0), 2360.0, 2340.0),
        )
        for label, state, bar_kwargs, level, reference in cases:
            with self.subTest(side=label):
                result = self.evaluate(state, self.bar(5, **bar_kwargs))
                close = self.events_of(
                    result, self.api("EventType").CLOSE_REQUESTED
                )[0]
                self.assertEqual(close.reason, self.api("ClosureReason").TARGET)
                self.assertAlmostEqual(close.requested_level, level, places=9)
                self.assertAlmostEqual(close.observed_reference, reference, places=9)

    def test_the_domain_never_reports_an_executable_price(self) -> None:
        """Spec 18: costs belong to the execution adapter, not to the model."""
        result = self.evaluate(
            self.open_buy(), self.bar(5, open_=2400.0, high=2405.0,
                                      low=2395.0, close=2402.0)
        )
        close = self.events_of(result, self.api("EventType").CLOSE_REQUESTED)[0]
        self.assertFalse(
            hasattr(close, "executable_price"),
            "the executable price is produced by the adapter and returned via "
            "CloseFilled; the domain must not compute it",
        )

    def test_the_recorded_fill_comes_from_the_broker_result(self) -> None:
        """Spec 12.1: the recorded fill is what statistics use."""
        state = self.open_buy(steps=6)
        state = self.evaluate(
            state, self.bar(5, open_=2400.0, high=2405.0, low=2395.0, close=2402.0)
        ).state
        state = self.api("apply_broker_result")(
            state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").STOP,
                fill_price=2399.80, steps_closed=6,
            ),
        )
        self.assertTrue(state.is_closed)
        self.assertAlmostEqual(state.closure_fill_price, 2399.80, places=9)


# =====================================================================
# 14. Broker failure contract
# =====================================================================
class BrokerFailureContract(ContractTest):
    """Spec 16: canonical state follows broker results, never intents."""

    def test_a_rejected_partial_leaves_the_quantity_unchanged(self) -> None:
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        rejected = self.api("apply_broker_result")(
            state, self.api("PartialCloseRejected")(reason="no liquidity")
        )
        self.assertEqual(rejected.steps_remaining, 6)
        self.assertIn(self.api("Milestone").M1R, rejected.milestones_consumed)
        self.assertTrue(rejected.anomalies)

    def test_a_partial_fill_smaller_than_requested_is_adopted(self) -> None:
        """Spec 16.2: the broker wins on quantity."""
        state = self.open_buy(steps=6)
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("PartialCloseFilled")(steps_closed=2)
        )
        self.assertEqual(state.steps_remaining, 4)

    def test_a_rejected_stop_modification_does_not_advance_the_confirmed_state(self) -> None:
        state = self.open_buy()
        state = self.evaluate(state, self.touch(5, 2480.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("StopModifyRejected")(reason="market closed")
        )
        self.assertEqual(state.stop_state_confirmed, self.api("StopState").ORIGINAL)
        self.assertEqual(state.stop_state_intended, self.api("StopState").BREAKEVEN)

    def test_a_rejected_close_does_not_report_the_position_as_closed(self) -> None:
        """Spec 16.2 / MUST NOT 12."""
        state = self.open_buy(steps=6, tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("CloseRejected")(reason="requote")
        )
        self.assertFalse(state.is_closed)
        self.assertIsNone(state.closure_reason)

    def test_a_rejected_close_is_re_requested_on_the_next_observation(self) -> None:
        state = self.open_buy(steps=6, tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state, self.api("CloseRejected")(reason="requote")
        )
        again = self.evaluate(state, self.touch(10, 2541.0))
        closes = self.events_of(again, self.api("EventType").CLOSE_REQUESTED)
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].reason, self.api("ClosureReason").TARGET)

    def test_a_quantity_mismatch_adopts_the_broker_value_and_records_it(self) -> None:
        state = self.open_buy(steps=6)
        reconciled = self.api("apply_broker_result")(
            state, self.api("QuantityReconciled")(steps_remaining=4)
        )
        self.assertEqual(reconciled.steps_remaining, 4)
        self.assertTrue(
            reconciled.anomalies, "a silent reconciliation is forbidden (spec 16.2)"
        )

    def test_a_position_the_broker_no_longer_has_closes_as_external(self) -> None:
        state = self.open_buy(steps=6)
        gone = self.api("apply_broker_result")(state, self.api("PositionGone")())
        self.assertTrue(gone.is_closed)
        self.assertEqual(gone.closure_reason, self.api("ClosureReason").EXTERNAL)

    def test_anomaly_severity_is_not_decided(self) -> None:
        """R4 is unresolved (spec 24 U4): recording is required, grading is not."""
        state = self.open_buy(steps=6)
        reconciled = self.api("apply_broker_result")(
            state, self.api("QuantityReconciled")(steps_remaining=4)
        )
        for anomaly in reconciled.anomalies:
            with self.subTest(anomaly=anomaly):
                self.assertFalse(
                    hasattr(anomaly, "severity"),
                    "R4 (anomaly severity) is UNRESOLVED and must not be invented",
                )


# =====================================================================
# 15. Multiple positions
# =====================================================================
class MultiplePositions(ContractTest):
    """Spec 14: independent positions; opposing ones refused pending R2."""

    def test_concurrent_positions_in_the_same_direction_are_permitted(self) -> None:
        first = self.open_buy()
        second = self.open_buy(fill=2460.0, stop=2430.0)
        self.assertTrue(
            self.api("may_open_position")([first, second], self.side().BUY)
        )

    def test_an_opposing_position_is_refused_while_one_is_open(self) -> None:
        """Spec 14.1 / MUST NOT 6: refused until the account model is known."""
        self.assertFalse(
            self.api("may_open_position")([self.open_buy()], self.side().SELL)
        )

    def test_an_opposing_position_is_permitted_once_nothing_is_open(self) -> None:
        state = self.open_buy(tp_ratio=3.0)
        state = self.evaluate(state, self.touch(5, 2540.0)).state
        state = self.api("apply_broker_result")(
            state,
            self.api("CloseFilled")(
                reason=self.api("ClosureReason").TARGET,
                fill_price=2540.0, steps_closed=state.steps_remaining,
            ),
        )
        self.assertTrue(self.api("may_open_position")([state], self.side().SELL))

    def test_positions_do_not_share_state(self) -> None:
        """Spec 14: no netting of R, no cross-position stop logic."""
        first = self.open_buy(steps=6)
        second = self.open_buy(steps=4)
        advanced = self.evaluate(first, self.touch(5, 2480.0)).state
        self.assertEqual(second.steps_remaining, 4)
        self.assertEqual(second.milestones_consumed, frozenset())
        self.assertNotEqual(
            advanced.stop_state_intended, second.stop_state_intended
        )


# =====================================================================
# 16. Prohibitions verifiable without the implementation running
# =====================================================================
class StaticProhibitions(unittest.TestCase):
    """Spec 24 MUST NOT: checks that read the source rather than run it."""

    def setUp(self) -> None:
        if not CANONICAL_SOURCE.exists():
            self.skipTest(ABSENT)
        self.source = CANONICAL_SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_the_deferred_config_constants_are_not_read(self) -> None:
        """MUST NOT 2: the config.py trailing specification stays inactive."""
        for name in (
            "TRAILING_STOP_ATR_TRIGGER", "TRAILING_STOP_ATR_TRAIL",
            "INTRADAY_MAX_HOLD_MINUTES", "INTRADAY_MIN_HOLD_MINUTES",
            "MAX_SLIPPAGE_PIPS",
        ):
            with self.subTest(constant=name):
                self.assertNotIn(
                    name, self.source,
                    f"{name} is deferred historical configuration (spec 9.1) and "
                    "must not become active behaviour",
                )

    def test_no_broker_terminal_import(self) -> None:
        """MUST NOT 1: the state machine contains no MT5-specific calls."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                with self.subTest(imported=name):
                    self.assertNotIn("MetaTrader5", name)
                    self.assertNotIn("mt5", name.lower())

    def test_no_historical_manager_is_imported(self) -> None:
        """DD1: the demoted implementations must not be dependencies."""
        for banned in ("trade_manager", "order_execution", "paper_broker",
                       "main_production"):
            with self.subTest(module=banned):
                self.assertNotIn(banned, self.source)

    # Ambient clock and I/O, expressed as AST shapes rather than substrings.
    #
    # A substring search cannot tell a call to the builtin `open` from the
    # `is_open` accessor this same contract requires, and it also matches any
    # docstring that merely mentions either. Matching call nodes is both
    # narrower in what it flags and wider in what it catches: `path.open()` and
    # `builtins.open()` are caught here and were invisible to the old check.
    FORBIDDEN_NAME_CALLS = {"open"}
    FORBIDDEN_ATTRIBUTE_CALLS = {
        "open",       # path.open(...), builtins.open(...) -- any receiver
        "now",        # datetime.now(...)
        "today",      # datetime.today(...)
        "getLogger",  # logging is I/O
    }
    FORBIDDEN_MODULE_CALLS = {("time", "time")}
    FORBIDDEN_IMPORTS = {"requests", "urllib", "socket", "http", "shutil"}

    def _io_offenders(self) -> list[str]:
        """Every ambient-I/O or clock call in the module, with line numbers."""
        offenders: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in self.FORBIDDEN_NAME_CALLS:
                    offenders.append(f"line {node.lineno}: {func.id}()")
                elif isinstance(func, ast.Attribute):
                    if func.attr in self.FORBIDDEN_ATTRIBUTE_CALLS:
                        offenders.append(f"line {node.lineno}: .{func.attr}()")
                    elif (
                        isinstance(func.value, ast.Name)
                        and (func.value.id, func.attr) in self.FORBIDDEN_MODULE_CALLS
                    ):
                        offenders.append(
                            f"line {node.lineno}: {func.value.id}.{func.attr}()"
                        )
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                else:
                    roots = [(node.module or "").split(".")[0]]
                for root in roots:
                    if root in self.FORBIDDEN_IMPORTS:
                        offenders.append(f"line {node.lineno}: import {root}")
        return offenders

    def _offenders_in(self, source: str) -> list[str]:
        """Run the detector over an arbitrary snippet, for self-verification."""
        real_tree, self.tree = self.tree, ast.parse(source)
        try:
            return self._io_offenders()
        finally:
            self.tree = real_tree

    def test_no_ambient_clock_or_io(self) -> None:
        """MUST 17: evaluation reads no clock and performs no I/O.

        The detector is verified against two probes in the same test, so the
        prohibition cannot pass merely because the check became inert -- the
        failure mode `tests/core/test_core_constraints.py` guards against for
        the clock rule.
        """
        with self.subTest(check="detects real violations"):
            self.assertEqual(
                len(self._offenders_in(
                    "import socket\n"
                    "def f(p, d):\n"
                    "    handle = open(p)\n"
                    "    other = p.open()\n"
                    "    stamp = d.now()\n"
                    "    return handle, other, stamp\n"
                )),
                4,
                "the detector must catch a builtin open, an attribute open, an "
                "ambient clock read and a network import",
            )

        with self.subTest(check="does not flag the required is_open accessor"):
            self.assertEqual(
                self._offenders_in(
                    "class S:\n"
                    "    @property\n"
                    "    def is_open(self):\n"
                    "        return self.lifecycle is OPEN\n"
                    "    def use(self, bar):\n"
                    "        return self.is_open and bar.open > 0\n"
                ),
                [],
                "`is_open` and a bar's `open` field are part of this contract "
                "and are not file I/O",
            )

        with self.subTest(check="the canonical module is clean"):
            self.assertEqual(
                self._io_offenders(), [],
                "the canonical domain model must not read a clock, open a "
                "file, log, or reach the network; time arrives on the "
                "observation and everything else belongs to the adapter",
            )


# =====================================================================
# 17. Unresolved items -- recorded, not answered
# =====================================================================
class UnresolvedItemsAreNotDecided(unittest.TestCase):
    """Spec 25: R1-R4 stay open. These tests assert that they stay open."""

    def test_r1_reversal_protection_remains_unresolved(self) -> None:
        spec = (REPO_ROOT / "docs" / "PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md")
        text = spec.read_text(encoding="utf-8")
        self.assertIn("R1 | Reversal protection in or out", text)

    def test_r2_account_model_remains_unresolved(self) -> None:
        spec = (REPO_ROOT / "docs" / "PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md")
        text = spec.read_text(encoding="utf-8")
        self.assertIn("R2 | Netting vs hedging", text)

    def test_the_spec_still_defers_trailing_and_time_exit(self) -> None:
        spec = (REPO_ROOT / "docs" / "PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md")
        text = spec.read_text(encoding="utf-8")
        self.assertIn("ATR-based continuous trailing", text)
        self.assertIn("Time-based exit", text)


if __name__ == "__main__":
    unittest.main()
