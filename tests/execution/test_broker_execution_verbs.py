"""Tests for the broker's explicit execution verbs.

Phase 4 of the canonical integration plan. The broker executes instructions and
reports what happened; it decides nothing. These tests pin both halves: that the
verbs work, and that the broker does not act on its own.

Nothing here uses the canonical adapter, which does not exist yet.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.symbols import XAUUSD_2DIGIT
from core.types import Side
from execution.broker import ExecutionStatus, PositionState, SimulatedPosition
from execution.fills import FillModel
from execution.paper_broker import PaperBroker
from execution.trade_identity import (
    FillIdentity,
    FillKind,
    FillLog,
    FillRecord,
    IdentityMinter,
    OperationKind,
)
from core.units import Pips

SPEC = XAUUSD_2DIGIT
T0 = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
FREE = FillModel(spread=Pips(0.0), slippage=Pips(0.0))


def _bar(minutes: int, *, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {
            "time": pd.Timestamp(T0 + timedelta(minutes=minutes)),
            "open": open_, "high": high, "low": low, "close": close,
        }
    )


class VerbTestCase(unittest.TestCase):
    """A broker holding one open BUY of 1.00 lot at 2450, stop 2420."""

    fill_model = FREE

    def setUp(self) -> None:
        self.broker = PaperBroker(SPEC, fill_model=self.fill_model)
        self.minter = IdentityMinter()
        fill = self.broker.submit_market_order(
            side=Side.BUY,
            volume=1.00,
            stop_loss=2420.0,
            take_profit=2540.0,
            decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=_bar(0, open_=2450.0, high=2451.0, low=2449.0, close=2450.5),
        )
        self.assertTrue(fill.filled if hasattr(fill, "filled") else True)
        self.position = self.broker.open_positions()[0]

    def operation(self, kind: OperationKind) -> str:
        return self.minter.next_operation_id(
            scope=self.position.position_id, kind=kind
        )


class PartialClose(VerbTestCase):
    """A partial reduces broker quantity; it does not end the position."""

    def test_a_partial_close_reduces_the_broker_quantity(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id,
            volume=0.50,
            reference_price=2480.0,
            operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
            at_time=T0 + timedelta(minutes=10),
            cause="M1R",
        )
        self.assertTrue(result.filled)
        self.assertAlmostEqual(result.executed_volume, 0.50, places=9)
        self.assertAlmostEqual(result.remaining_volume, 0.50, places=9)
        self.assertAlmostEqual(self.position.remaining_volume, 0.50, places=9)
        self.assertAlmostEqual(self.position.volume, 1.00, places=9,
                               msg="the entry size is immutable")

    def test_the_position_stays_open_after_a_partial(self) -> None:
        self.broker.execute_partial_close(
            self.position.position_id, volume=0.50, reference_price=2480.0,
            operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
            at_time=T0 + timedelta(minutes=10),
        )
        self.assertTrue(self.position.is_open)
        self.assertTrue(self.position.is_partially_closed)
        self.assertEqual(self.broker.open_positions(), [self.position])
        self.assertEqual(self.broker.closed_positions(), [])
        self.assertIsNone(self.position.exit_price)

    def test_two_partials_are_two_executions(self) -> None:
        results = [
            self.broker.execute_partial_close(
                self.position.position_id, volume=0.30, reference_price=2480.0,
                operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
                at_time=T0 + timedelta(minutes=10),
            ),
            self.broker.execute_partial_close(
                self.position.position_id, volume=0.20, reference_price=2500.0,
                operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
                at_time=T0 + timedelta(minutes=20),
            ),
        ]
        self.assertTrue(all(r.filled for r in results))
        self.assertEqual(len({r.operation_id for r in results}), 2)
        self.assertAlmostEqual(self.position.remaining_volume, 0.50, places=9)

    def test_a_partial_may_not_close_the_whole_remainder(self) -> None:
        """That instruction is a close, and the two are different results."""
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=1.00, reference_price=2480.0,
            operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
            at_time=T0 + timedelta(minutes=10),
        )
        self.assertFalse(result.filled)
        self.assertIn("use the close verb", result.reason)
        self.assertAlmostEqual(self.position.remaining_volume, 1.00, places=9)

    def test_the_executed_price_carries_exit_costs(self) -> None:
        broker = PaperBroker(SPEC, fill_model=FillModel(spread=Pips(2.0)))
        broker.submit_market_order(
            side=Side.BUY, volume=1.00, stop_loss=2420.0, take_profit=2540.0,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=_bar(0, open_=2450.0, high=2451.0, low=2449.0, close=2450.5),
        )
        position = broker.open_positions()[0]
        result = broker.execute_partial_close(
            position.position_id, volume=0.50, reference_price=2480.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(result.reference_price, 2480.0, places=9)
        self.assertLess(result.executed_price, 2480.0,
                        "closing a BUY sells the bid, so the fill is worse")


class FullClose(VerbTestCase):
    """A close ends the position and reports what was still open."""

    def test_a_close_closes_the_remaining_quantity(self) -> None:
        result = self.broker.execute_close(
            self.position.position_id,
            reference_price=2540.0,
            operation_id=self.operation(OperationKind.FINAL_CLOSE),
            at_time=T0 + timedelta(minutes=30),
            state=PositionState.CLOSED_TARGET,
            reason="TARGET",
        )
        self.assertTrue(result.filled)
        self.assertTrue(result.closed_position)
        self.assertAlmostEqual(result.executed_volume, 1.00, places=9)
        self.assertEqual(result.remaining_volume, 0.0)
        self.assertFalse(self.position.is_open)
        self.assertEqual(self.position.state, PositionState.CLOSED_TARGET)

    def test_a_close_after_a_partial_closes_only_what_remains(self) -> None:
        self.broker.execute_partial_close(
            self.position.position_id, volume=0.50, reference_price=2480.0,
            operation_id=self.operation(OperationKind.PARTIAL_CLOSE),
            at_time=T0 + timedelta(minutes=10),
        )
        result = self.broker.execute_close(
            self.position.position_id, reference_price=2540.0,
            operation_id=self.operation(OperationKind.FINAL_CLOSE),
            at_time=T0 + timedelta(minutes=30),
            state=PositionState.CLOSED_TARGET, reason="TARGET",
        )
        self.assertAlmostEqual(result.executed_volume, 0.50, places=9)
        self.assertAlmostEqual(self.position.volume, 1.00, places=9)
        self.assertEqual(len(self.broker.closed_positions()), 1,
                         "a partial then a close is still one position")

    def test_the_caller_supplies_the_terminal_state_and_reason(self) -> None:
        self.broker.execute_close(
            self.position.position_id, reference_price=2420.0,
            operation_id=self.operation(OperationKind.FINAL_CLOSE),
            at_time=T0 + timedelta(minutes=30),
            state=PositionState.CLOSED_STOP, reason="STOP",
        )
        self.assertEqual(self.position.state, PositionState.CLOSED_STOP)
        self.assertEqual(self.position.exit_reason, "STOP")


class RejectionsChangeNothing(VerbTestCase):
    """A rejection is a result, and it leaves the position untouched."""

    def test_an_unknown_position_is_rejected(self) -> None:
        result = self.broker.execute_partial_close(
            "NOT-A-POSITION", volume=0.50, reference_price=2480.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertEqual(result.status, ExecutionStatus.REJECTED)
        self.assertAlmostEqual(self.position.remaining_volume, 1.00, places=9)

    def test_an_oversized_partial_is_rejected_without_changing_quantity(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=1.50, reference_price=2480.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertEqual(result.status, ExecutionStatus.REJECTED)
        self.assertEqual(result.executed_volume, 0.0)
        self.assertAlmostEqual(self.position.remaining_volume, 1.00, places=9)
        self.assertTrue(self.position.is_open)

    def test_a_volume_off_the_step_grid_is_rejected(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.005, reference_price=2480.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertEqual(result.status, ExecutionStatus.REJECTED)
        self.assertIn("volume step", result.reason)

    def test_a_non_positive_volume_is_rejected(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.0, reference_price=2480.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertEqual(result.status, ExecutionStatus.REJECTED)


class RequestedVersusExecuted(VerbTestCase):
    """The two quantities are reported separately, as the spec requires."""

    def test_requested_and_executed_are_separate_fields(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.40, reference_price=2480.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(result.requested_volume, 0.40, places=9)
        self.assertAlmostEqual(result.executed_volume, 0.40, places=9)
        self.assertFalse(result.partially_filled,
                         "paper execution fills what it is asked for")

    def test_a_rejection_reports_zero_executed_against_what_was_asked(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=5.00, reference_price=2480.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertAlmostEqual(result.requested_volume, 5.00, places=9)
        self.assertEqual(result.executed_volume, 0.0)
        self.assertIsNone(result.executed_price)


class StopModification(VerbTestCase):
    """The broker moves a stop when told, and never on its own."""

    def test_a_stop_moves_only_when_requested(self) -> None:
        before = self.position.stop_loss
        self.broker.fill_pending_orders(
            _bar(5, open_=2480.0, high=2485.0, low=2479.0, close=2484.0),
            T0 + timedelta(minutes=5),
        )
        self.assertEqual(
            self.position.stop_loss, before,
            "price reached 1R and the broker must not have moved anything",
        )

        result = self.broker.execute_stop_modify(
            self.position.position_id, stop_price=2450.0,
            operation_id=self.operation(OperationKind.STOP_MODIFY),
            at_time=T0 + timedelta(minutes=10),
        )
        self.assertTrue(result.confirmed)
        self.assertAlmostEqual(self.position.stop_loss, 2450.0, places=9)

    def test_the_original_stop_stays_distinct_from_the_current_stop(self) -> None:
        self.broker.execute_stop_modify(
            self.position.position_id, stop_price=2450.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(self.position.original_stop, 2420.0, places=9)
        self.assertAlmostEqual(self.position.stop_loss, 2450.0, places=9)

    def test_requested_and_confirmed_stops_are_reported_separately(self) -> None:
        result = self.broker.execute_stop_modify(
            self.position.position_id, stop_price=2450.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
        )
        self.assertAlmostEqual(result.requested_stop, 2450.0, places=9)
        self.assertAlmostEqual(result.confirmed_stop, 2450.0, places=9)

    def test_an_unusable_stop_is_rejected_without_changing_the_stop(self) -> None:
        result = self.broker.execute_stop_modify(
            self.position.position_id, stop_price=0.0,
            operation_id="OP-1", at_time=T0,
        )
        self.assertFalse(result.confirmed)
        self.assertAlmostEqual(self.position.stop_loss, 2420.0, places=9)

    def test_the_broker_does_not_judge_the_direction_of_a_move(self) -> None:
        """Monotonicity is a canonical rule, enforced where the decision is
        made. A broker that refused here would be deciding management."""
        result = self.broker.execute_stop_modify(
            self.position.position_id, stop_price=2400.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
        )
        self.assertTrue(result.confirmed)
        self.assertAlmostEqual(self.position.original_stop, 2420.0, places=9)


class BrokerDecidesNothing(VerbTestCase):
    """The restriction that matters most in this phase."""

    def test_reaching_1r_triggers_no_partial(self) -> None:
        self.broker.fill_pending_orders(
            _bar(5, open_=2480.0, high=2485.0, low=2479.0, close=2484.0),
            T0 + timedelta(minutes=5),
        )
        self.assertAlmostEqual(self.position.remaining_volume, 1.00, places=9)
        self.assertEqual(self.position.volume_closed, 0.0)
        self.assertTrue(self.position.is_open)

    def test_reaching_2r_triggers_no_stop_move(self) -> None:
        self.broker.fill_pending_orders(
            _bar(5, open_=2505.0, high=2515.0, low=2504.0, close=2512.0),
            T0 + timedelta(minutes=5),
        )
        self.assertAlmostEqual(self.position.stop_loss, 2420.0, places=9)

    def test_no_close_happens_without_an_instruction_or_a_level(self) -> None:
        """A bar that touches neither stop nor target leaves it open."""
        self.broker.fill_pending_orders(
            _bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0),
            T0 + timedelta(minutes=5),
        )
        self.assertTrue(self.position.is_open)
        self.assertEqual(self.broker.closed_positions(), [])


class IdentityThroughExecution(VerbTestCase):
    """Phase 2 identity survives the round trip, and duplicates are visible."""

    def test_position_and_operation_identity_are_preserved(self) -> None:
        operation = self.operation(OperationKind.PARTIAL_CLOSE)
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.50, reference_price=2480.0,
            operation_id=operation, at_time=T0 + timedelta(minutes=10),
        )
        self.assertEqual(result.position_id, self.position.position_id)
        self.assertEqual(result.operation_id, operation)

    def test_broker_order_and_deal_identity_are_carried_through(self) -> None:
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.50, reference_price=2480.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
            broker_order_id="ORD-7", broker_deal_id="DEAL-9",
        )
        self.assertEqual(result.broker_order_id, "ORD-7")
        self.assertEqual(result.broker_deal_id, "DEAL-9")

    def test_a_result_can_be_recorded_through_the_phase_2_fill_log(self) -> None:
        """A redelivered result is recognised, using the existing
        infrastructure rather than a second one."""
        result = self.broker.execute_partial_close(
            self.position.position_id, volume=0.50, reference_price=2480.0,
            operation_id="OP-1", at_time=T0 + timedelta(minutes=10),
            broker_deal_id="DEAL-9",
        )
        record = FillRecord(
            identity=FillIdentity(
                position_id=result.position_id,
                operation_id=result.operation_id,
                broker_deal_id=result.broker_deal_id,
            ),
            kind=FillKind.PARTIAL_EXIT,
            cause="M1R",
            quantity_steps=50,
            price=result.executed_price,
            time=result.time,
            broker_order_id=result.broker_order_id,
        )
        log = FillLog()
        self.assertTrue(log.record(record, for_position=result.position_id))
        self.assertFalse(log.record(record, for_position=result.position_id))
        self.assertEqual(len(log), 1)


class ExistingBehaviourUnchanged(VerbTestCase):
    """Phase 5 has not taken exit decisions yet, so on_bar still resolves."""

    def test_bars_held_semantics_are_unchanged(self) -> None:
        self.broker.fill_pending_orders(
            _bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0),
            T0 + timedelta(minutes=5),
        )
        self.assertEqual(self.position.bars_held, 1)
        self.broker.fill_pending_orders(
            _bar(10, open_=2465.0, high=2470.0, low=2460.0, close=2468.0),
            T0 + timedelta(minutes=10),
        )
        self.assertEqual(self.position.bars_held, 2)

    def test_a_position_created_without_projection_fields_behaves_as_before(self) -> None:
        """Defaults keep every existing construction identical."""
        legacy = SimulatedPosition(
            position_id="LEGACY", symbol="XAUUSD", side=Side.BUY, volume=0.01,
            entry_price=2450.0, stop_loss=2420.0, take_profit=2540.0,
            entry_time=T0,
        )
        self.assertEqual(legacy.volume_closed, 0.0)
        self.assertAlmostEqual(legacy.remaining_volume, 0.01, places=9)
        self.assertAlmostEqual(legacy.original_stop, 2420.0, places=9)
        self.assertFalse(legacy.is_partially_closed)


if __name__ == "__main__":
    unittest.main()
