"""Tests for the partial-exit ledger representation.

One canonical position becomes one :class:`TradeRecord` holding one
:class:`TradeExecution` per fill, so a partial exit is an execution and never a
second trade. Settled in
``docs/PHASE_4B_PARTIAL_EXIT_REPRESENTATION_DECISION.md`` and the identity
decisions D13-D15.

Worked example used throughout: BUY 1.00 lot at 2450.00, original stop 2420.00,
so R is 30.00 and 1.00 lot is 100 steps at ``volume_step`` 0.01. The 1R partial
closes 50 steps at 2479.80 and the remainder closes at 2539.80 -- both a touch
below their levels because an exit crosses the spread. Money per price unit is
100.00 per lot, so:

    partial : (2479.80 - 2450.00) * 100.00 * 0.50 = +1490.00
    final   : (2539.80 - 2450.00) * 100.00 * 0.50 = +4490.00
    gross                                          = +5980.00
    risk    : 30.00 * 100.00 * 1.00                =  3000.00
    R       : 5980.00 / 3000.00                    =     1.9933...
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from backtest.ledger import (
    SimulatedTrade,
    TradeOutcome,
    TradeRecord,
    trade_from_position,
    trade_record_from_fills,
)
from core.symbols import XAUUSD_2DIGIT
from core.types import Side
from execution.broker import PositionState, SimulatedPosition
from execution.trade_identity import (
    FillIdentity,
    FillKind,
    FillLog,
    FillRecord,
    IdentityMinter,
    OperationKind,
)

SPEC = XAUUSD_2DIGIT
ENTRY_TIME = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
POSITION = "XAUUSD-20260319T090500-BUY-0001"

ENTRY_PRICE = 2450.00
ORIGINAL_STOP = 2420.00
TARGET = 2540.00
PARTIAL_PRICE = 2479.80
FINAL_PRICE = 2539.80
STEPS = 100


def _execution(
    *,
    kind: FillKind,
    cause: str,
    steps: int,
    price: float,
    minutes: int,
    operation: str = "OP-1",
    index: int = 1,
    deal: str | None = None,
    position_id: str = POSITION,
) -> FillRecord:
    return FillRecord(
        identity=FillIdentity(
            position_id=position_id,
            operation_id=operation,
            broker_deal_id=deal,
            execution_index=None if deal else index,
        ),
        kind=kind,
        cause=cause,
        quantity_steps=steps,
        price=price,
        time=ENTRY_TIME + timedelta(minutes=minutes),
    )


def _entry() -> FillRecord:
    return _execution(
        kind=FillKind.ENTRY, cause="ENTRY", steps=STEPS, price=ENTRY_PRICE,
        minutes=0, operation="OP-ENTRY",
    )


def _partial() -> FillRecord:
    return _execution(
        kind=FillKind.PARTIAL_EXIT, cause="M1R", steps=50, price=PARTIAL_PRICE,
        minutes=10, operation="OP-PARTIAL",
    )


def _final(price: float = FINAL_PRICE, cause: str = "TARGET") -> FillRecord:
    return _execution(
        kind=FillKind.FINAL_EXIT, cause=cause, steps=50, price=price,
        minutes=30, operation="OP-FINAL",
    )


def _record(
    *,
    executions=None,
    final_stop_price: float | None = None,
    commission_per_lot: float = 0.0,
    bars_held: int = 7,
    ambiguous_fill_ids=(),
    outcome: TradeOutcome = TradeOutcome.TARGET_HIT,
) -> TradeRecord:
    return trade_record_from_fills(
        position_id=POSITION,
        symbol="XAUUSD",
        side=Side.BUY,
        outcome=outcome,
        entry_price=ENTRY_PRICE,
        original_stop_price=ORIGINAL_STOP,
        original_quantity_steps=STEPS,
        executions=executions if executions is not None
        else [_entry(), _partial(), _final()],
        spec=SPEC,
        take_profit=TARGET,
        final_stop_price=final_stop_price,
        bars_held=bars_held,
        commission_per_lot=commission_per_lot,
        ambiguous_fill_ids=ambiguous_fill_ids,
        metadata={"regime": "INTRADAY_SWING", "setup_type": "OB"},
    )


class OneTradePerPosition(unittest.TestCase):
    """A partial exit is an execution, never a second trade."""

    def test_one_position_produces_one_record(self) -> None:
        record = _record()
        self.assertEqual(record.trade_id, POSITION)
        self.assertEqual(record.position_id, POSITION)

    def test_two_exit_executions_remain_one_trade(self) -> None:
        records = [_record()]
        self.assertEqual(len(records), 1, "a partial must not become a second trade")
        self.assertEqual(len(records[0].exit_executions), 2)

    def test_the_trade_count_is_unchanged_by_a_partial_lifecycle(self) -> None:
        """Entry 1.00, partial 0.50, final 0.50 is one trade and two exits."""
        record = _record()
        self.assertEqual(len([record]), 1)
        self.assertEqual(len(record.exit_executions), 2)
        self.assertEqual(len(record.executions), 3, "the entry is recorded too")

    def test_executed_quantities_sum_to_the_original(self) -> None:
        record = _record()
        self.assertEqual(record.closed_quantity_steps, STEPS)
        self.assertEqual(record.original_quantity_steps, STEPS)
        self.assertAlmostEqual(record.original_quantity, 1.00, places=9)


class ExecutionRecords(unittest.TestCase):
    """Each execution keeps the price and quantity it actually executed at."""

    def test_the_partial_price_is_preserved(self) -> None:
        partial = _record().exit_executions[0]
        self.assertAlmostEqual(partial.price, PARTIAL_PRICE, places=9)
        self.assertEqual(partial.quantity_steps, 50)
        self.assertAlmostEqual(partial.quantity, 0.50, places=9)
        self.assertEqual(partial.cause, "M1R")

    def test_the_final_price_is_preserved(self) -> None:
        final = _record().exit_executions[-1]
        self.assertAlmostEqual(final.price, FINAL_PRICE, places=9)
        self.assertEqual(final.cause, "TARGET")

    def test_the_entry_execution_realises_nothing(self) -> None:
        entry = _record().executions[0]
        self.assertEqual(entry.kind, FillKind.ENTRY.value)
        self.assertEqual(entry.gross_pnl, 0.0)
        self.assertEqual(entry.commission, 0.0)
        self.assertFalse(entry.is_exit)

    def test_a_duplicate_execution_does_not_become_a_second_fill(self) -> None:
        """Recorded through the Phase 2 log, a redelivery collapses."""
        log = FillLog()
        for execution in (_entry(), _partial(), _partial(), _final()):
            log.record(execution, for_position=POSITION)
        record = _record(executions=list(log.fills_for(POSITION)))
        self.assertEqual(len(record.executions), 3)
        self.assertEqual(record.closed_quantity_steps, STEPS)

    def test_two_executions_of_one_operation_stay_distinct(self) -> None:
        first = _execution(
            kind=FillKind.FINAL_EXIT, cause="TARGET", steps=30,
            price=FINAL_PRICE, minutes=30, operation="OP-FINAL", index=1,
        )
        second = _execution(
            kind=FillKind.FINAL_EXIT, cause="TARGET", steps=20,
            price=FINAL_PRICE, minutes=31, operation="OP-FINAL", index=2,
        )
        record = _record(executions=[_entry(), _partial(), first, second])
        self.assertEqual(len(record.exit_executions), 3)
        self.assertEqual(record.closed_quantity_steps, STEPS)


class AggregateEconomics(unittest.TestCase):
    """Aggregates are summed from the executions, never from an average price."""

    def test_per_execution_gross_pnl(self) -> None:
        partial, final = _record().exit_executions
        self.assertAlmostEqual(partial.gross_pnl, 1490.00, places=6)
        self.assertAlmostEqual(final.gross_pnl, 4490.00, places=6)

    def test_aggregate_gross_equals_the_sum_of_executions(self) -> None:
        record = _record()
        self.assertAlmostEqual(
            record.gross_pnl,
            sum(e.gross_pnl for e in record.executions),
            places=9,
        )
        self.assertAlmostEqual(record.gross_pnl, 5980.00, places=6)

    def test_commission_is_one_round_turn_on_the_original_quantity(self) -> None:
        """Charged per exit execution, summing to what one charge on the full
        volume gives -- the existing repository convention."""
        record = _record(commission_per_lot=8.0)
        self.assertAlmostEqual(record.commission, 8.0 * 1.00, places=9)
        self.assertAlmostEqual(
            record.commission,
            sum(e.commission for e in record.executions),
            places=9,
        )

    def test_net_pnl_is_gross_minus_commission(self) -> None:
        record = _record(commission_per_lot=8.0)
        self.assertAlmostEqual(record.net_pnl, 5980.00 - 8.0, places=6)

    def test_slippage_is_reported_not_subtracted(self) -> None:
        record = _record(commission_per_lot=0.0)
        self.assertEqual(record.slippage_cost, 0.0)
        self.assertAlmostEqual(record.net_pnl, record.gross_pnl, places=9)


class ImmutableOriginalRisk(unittest.TestCase):
    """D13: risk comes from the original stop, never the promoted one."""

    def test_original_risk_survives_stop_movement(self) -> None:
        record = _record(final_stop_price=ENTRY_PRICE)
        self.assertAlmostEqual(record.price_risk, 30.00, places=9)
        self.assertAlmostEqual(record.original_stop_price, ORIGINAL_STOP, places=9)
        self.assertAlmostEqual(record.final_stop_price, ENTRY_PRICE, places=9)

    def test_r_multiple_uses_the_original_risk(self) -> None:
        record = _record()
        self.assertAlmostEqual(record.risk_amount, 3000.00, places=6)
        self.assertAlmostEqual(record.r_multiple, 5980.00 / 3000.00, places=9)

    def test_r_multiple_survives_a_stop_promoted_to_breakeven(self) -> None:
        """The defect this representation exists to prevent: with risk taken
        from the current stop, breakeven gives a zero denominator and
        ``r_multiple`` silently becomes ``None``."""
        record = _record(final_stop_price=ENTRY_PRICE)
        self.assertIsNotNone(record.r_multiple)
        self.assertAlmostEqual(record.r_multiple, 5980.00 / 3000.00, places=9)

    def test_a_losing_position_reports_a_negative_r(self) -> None:
        record = _record(
            executions=[_entry(), _partial(), _final(price=2420.20, cause="STOP")],
            outcome=TradeOutcome.STOPPED,
            final_stop_price=ENTRY_PRICE,
        )
        self.assertLess(record.exit_executions[-1].gross_pnl, 0.0)
        self.assertIsNotNone(record.r_multiple)


class PositionLevelMetrics(unittest.TestCase):
    """bars_held stays position-level; ambiguity aggregates over exits."""

    def test_bars_held_is_recorded_once_for_the_position(self) -> None:
        record = _record(bars_held=7)
        self.assertEqual(record.bars_held, 7)

    def test_no_ambiguous_exit_means_false(self) -> None:
        self.assertFalse(_record().was_ambiguous_exit)

    def test_any_ambiguous_exit_marks_the_position(self) -> None:
        final = _final()
        record = _record(ambiguous_fill_ids=[final.fill_id])
        self.assertTrue(record.was_ambiguous_exit)
        self.assertFalse(record.exit_executions[0].was_ambiguous)
        self.assertTrue(record.exit_executions[-1].was_ambiguous)

    def test_the_final_execution_supplies_the_closure_fields(self) -> None:
        record = _record()
        self.assertAlmostEqual(record.exit_price, FINAL_PRICE, places=9)
        self.assertEqual(record.exit_reason, "TARGET")
        self.assertEqual(record.exit_time, (ENTRY_TIME + timedelta(minutes=30)).isoformat())


class Validation(unittest.TestCase):
    """The builder refuses an incoherent execution history."""

    def test_an_execution_naming_another_position_is_refused(self) -> None:
        foreign = _execution(
            kind=FillKind.FINAL_EXIT, cause="TARGET", steps=50,
            price=FINAL_PRICE, minutes=30, position_id="OTHER",
        )
        with self.assertRaises(ValueError):
            _record(executions=[_entry(), foreign])

    def test_a_position_with_no_exit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _record(executions=[_entry()])

    def test_out_of_order_executions_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            _record(executions=[_entry(), _final(), _partial()])

    def test_closing_more_than_was_opened_is_refused(self) -> None:
        too_much = _execution(
            kind=FillKind.FINAL_EXIT, cause="TARGET", steps=80,
            price=FINAL_PRICE, minutes=30,
        )
        with self.assertRaises(ValueError):
            _record(executions=[_entry(), _partial(), too_much])

    def test_two_entry_executions_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            _record(executions=[_entry(), _entry(), _final()])


class Serialisation(unittest.TestCase):
    """JSON holds the nested executions; identity survives the round trip."""

    def test_the_record_serialises_with_its_executions(self) -> None:
        payload = json.loads(json.dumps(_record().to_dict(), default=str))
        self.assertEqual(len(payload["executions"]), 3)
        self.assertEqual(payload["position_id"], POSITION)

    def test_fill_identity_survives_serialisation(self) -> None:
        record = _record()
        payload = json.loads(json.dumps(record.to_dict(), default=str))
        self.assertEqual(
            [e["fill_id"] for e in payload["executions"]],
            [e.fill_id for e in record.executions],
        )

    def test_a_broker_deal_id_is_carried_through(self) -> None:
        final = _execution(
            kind=FillKind.FINAL_EXIT, cause="TARGET", steps=50,
            price=FINAL_PRICE, minutes=30, deal="D-42",
        )
        record = _record(executions=[_entry(), _partial(), final])
        self.assertEqual(record.exit_executions[-1].broker_deal_id, "D-42")


class BackwardCompatibility(unittest.TestCase):
    """The projection keeps existing consumers working unchanged."""

    def _closed_position(self) -> SimulatedPosition:
        return SimulatedPosition(
            position_id=POSITION,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=1.00,
            entry_price=ENTRY_PRICE,
            stop_loss=ORIGINAL_STOP,
            take_profit=TARGET,
            entry_time=ENTRY_TIME,
            state=PositionState.CLOSED_TARGET,
            exit_price=FINAL_PRICE,
            exit_time=ENTRY_TIME + timedelta(minutes=30),
            exit_reason="TARGET",
            was_ambiguous_exit=False,
            bars_held=7,
            metadata={"regime": "INTRADAY_SWING", "setup_type": "OB"},
        )

    def test_a_single_exit_record_projects_onto_the_existing_trade(self) -> None:
        """A position that never partials must produce the same figures the
        existing producer gives for it."""
        existing = trade_from_position(self._closed_position(), SPEC, commission=8.0)
        projected = trade_record_from_fills(
            position_id=POSITION,
            symbol="XAUUSD",
            side=Side.BUY,
            outcome=TradeOutcome.TARGET_HIT,
            entry_price=ENTRY_PRICE,
            original_stop_price=ORIGINAL_STOP,
            original_quantity_steps=STEPS,
            executions=[
                _entry(),
                _execution(
                    kind=FillKind.FINAL_EXIT, cause="TARGET", steps=STEPS,
                    price=FINAL_PRICE, minutes=30, operation="OP-FINAL",
                ),
            ],
            spec=SPEC,
            take_profit=TARGET,
            bars_held=7,
            commission_per_lot=8.0,
            metadata={"regime": "INTRADAY_SWING", "setup_type": "OB"},
        ).to_simulated_trade()

        self.assertIsInstance(projected, SimulatedTrade)
        for attribute in (
            "trade_id", "symbol", "side", "outcome", "entry_price", "stop_loss",
            "take_profit", "exit_price", "exit_reason", "was_ambiguous_exit",
            "quantity", "price_risk", "gross_pnl", "commission", "net_pnl",
            "risk_amount", "r_multiple", "bars_held", "regime", "setup_type",
        ):
            with self.subTest(field=attribute):
                self.assertEqual(
                    getattr(projected, attribute), getattr(existing, attribute)
                )

    def test_the_projection_keeps_one_row_per_position(self) -> None:
        rows = [_record().to_simulated_trade()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].trade_id, POSITION)

    def test_the_projection_carries_the_original_stop(self) -> None:
        """So that ``price_risk == abs(entry - stop_loss)`` still reads true."""
        projected = _record(final_stop_price=ENTRY_PRICE).to_simulated_trade()
        self.assertAlmostEqual(projected.stop_loss, ORIGINAL_STOP, places=9)
        self.assertAlmostEqual(
            projected.price_risk,
            abs(projected.entry_price - projected.stop_loss),
            places=9,
        )

    def test_the_existing_producer_is_unchanged(self) -> None:
        """trade_from_position still yields a flat single-exit record."""
        existing = trade_from_position(self._closed_position(), SPEC)
        self.assertFalse(hasattr(existing, "executions"))
        self.assertAlmostEqual(existing.quantity, 1.00, places=9)


if __name__ == "__main__":
    unittest.main()
