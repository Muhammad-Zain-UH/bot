"""Canonical trade-management adapter.

Phase 5B of ``docs/PHASE_4B_CANONICAL_INTEGRATION_IMPLEMENTATION_PLAN.md``,
executed against ``docs/PHASE_4B_5B_CUTOVER_PLAN.md``.

The adapter is the **sole exit authority**. It owns the canonical
:class:`~core.trade_model.TradeState` for every live position, builds a
:class:`~core.trade_model.PriceObservation` per bar, asks the domain what should
happen, and turns each answer into a broker instruction. The broker executes and
reports; it decides nothing.

Position creation happens **at the fill** (specification §13): an order that
never fills has no position and no canonical state.

Target: anchored to the actual fill
-----------------------------------
The target is **recomputed from the actual fill** as ``entry ± tp_ratio × R``
(specification §4.2), where ``R`` is measured against the *original* stop and
``tp_ratio`` is the ratio the strategy asked for, carried on the fill metadata.

The position may arrive carrying a ``take_profit`` computed from the entry the
strategy *intended*. That level is **not** the canonical target and takes no
part in the geometry. A fill that beats the intended entry shrinks R, and a
target left at the intended anchor would then sit at some other multiple of the
R that actually exists -- on the R1 fixtures, 4.35R and 6.62R against a
requested 3.0R. Re-anchoring is what makes ``reward / R`` equal ``tp_ratio``.

Until the previous commit ``tp_ratio`` was reconstructed from the carried
target, as a migration control that kept the two equal by construction while
exit authority and the ledger moved. That control is gone; §4.2 is now in
force, and the exit bar moves accordingly.

Record-then-apply
-----------------
Every quantity-changing broker result is written to the fill log **before** it
reaches canonical state, through
:func:`~execution.trade_identity.record_then_apply`. A redelivered execution is
recognised at the log and never produces a second economic effect
(specification §16.3).

Rejections surface
------------------
Paper execution rejects only for an unknown position or an unusable price,
neither of which this adapter can produce for a position it tracks. If one ever
happens it is raised, not absorbed: absorbing it would require inventing the
retry semantics that remain **U5/R8** and **U6/R9**, both unresolved.

Intrabar policy
---------------
Per decision D16 the domain resolves every exit adverse-first, and
:class:`~execution.intrabar.IntrabarPolicy` is an annotation only. This module
never consults it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from backtest.ledger import TradeOutcome, TradeRecord, trade_record_from_fills
from core.symbols import SymbolSpecification
from core.trade_model import (
    CloseFilled,
    CloseRequest,
    ClosureReason,
    EventType,
    Milestone,
    PartialCloseFilled,
    PriceObservation,
    StopModifyConfirmed,
    StopState,
    TradeState,
    apply_broker_result,
    evaluate,
    open_position,
    steps_to_lots,
)
from core.types import DomainInvariantError
from execution.broker import PositionState, SimulatedPosition
from execution.fills import FillModel
from execution.paper_broker import PaperBroker
from execution.trade_identity import (
    FillIdentity,
    FillKind,
    FillLog,
    FillRecord,
    IdentityMinter,
    OperationKind,
    record_then_apply,
)

__all__ = [
    "BrokerRejectionNotHandled",
    "TradeEventKind",
    "TradeEvent",
    "TradeAdapter",
]

_REASON_TO_STATE: dict[ClosureReason, PositionState] = {
    ClosureReason.STOP: PositionState.CLOSED_STOP,
    ClosureReason.TARGET: PositionState.CLOSED_TARGET,
    ClosureReason.END_OF_DATA: PositionState.CLOSED_END_OF_DATA,
    ClosureReason.MANUAL: PositionState.CLOSED_MANUAL,
}

_REASON_TO_OUTCOME: dict[ClosureReason, TradeOutcome] = {
    ClosureReason.STOP: TradeOutcome.STOPPED,
    ClosureReason.TARGET: TradeOutcome.TARGET_HIT,
    ClosureReason.END_OF_DATA: TradeOutcome.END_OF_DATA,
    ClosureReason.MANUAL: TradeOutcome.MANUAL,
}


class BrokerRejectionNotHandled(RuntimeError):
    """Raised when the broker refuses an instruction.

    Paper execution cannot produce this for a tracked position. Handling it
    would mean choosing what a re-requested close carries (**U5/R8**) or what
    happens to the ladder after a refused promotion (**U6/R9**), and both are
    unresolved. Raising keeps the condition visible instead of inventing an
    answer.
    """


class TradeEventKind(Enum):
    """What the canonical domain did on one observation."""

    POSITION_OPENED = "POSITION_OPENED"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    STOP_PROMOTED = "STOP_PROMOTED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """One canonical decision and its execution.

    Attributes:
        kind: What happened.
        bar_time: The observation it happened on.
        position_id: Canonical position identity.
        broker_position_id: The broker position it manages.
        canonical_only: True for an event the pre-cut engine had no concept of
            -- the 1R partial and the stop promotions.
        reason: Closure reason, on a close.
        requested_level: The level the domain asked for.
        observed_reference: The first price available at or beyond it.
        executed_price: What the broker reported.
        steps: Quantity in volume steps.
        stop_price: The new stop, on a promotion.
        stop_state: The state promoted to.
        ambiguous: The domain's ambiguity flag for the observation.
        detail: Free text, used for a skip reason.
    """

    kind: TradeEventKind
    bar_time: datetime | None
    position_id: str
    broker_position_id: str
    canonical_only: bool = False
    reason: ClosureReason | None = None
    requested_level: float | None = None
    observed_reference: float | None = None
    executed_price: float | None = None
    steps: int | None = None
    stop_price: float | None = None
    stop_state: StopState | None = None
    ambiguous: bool = False
    detail: str = ""


@dataclass
class _Managed:
    """One position's canonical state and its provenance."""

    broker_position_id: str
    canonical_id: str
    state: TradeState
    ambiguous_fill_ids: set[str]


class TradeAdapter:
    """Drives the canonical domain and instructs the broker.

    Args:
        broker: The broker to instruct.
        minter: Identity minter. One is created if not supplied.
        fill_log: Fill log. One is created if not supplied.
    """

    __slots__ = ("_broker", "_spec", "_fill_model", "_minter", "_fill_log",
                 "_live", "_closed", "_events", "_records")

    def __init__(
        self,
        broker: PaperBroker,
        minter: IdentityMinter | None = None,
        fill_log: FillLog | None = None,
    ) -> None:
        self._broker = broker
        self._spec: SymbolSpecification = broker.spec
        self._fill_model: FillModel = broker.fill_model
        self._minter = minter or IdentityMinter()
        self._fill_log = fill_log or FillLog()
        self._live: dict[str, _Managed] = {}
        self._closed: dict[str, _Managed] = {}
        self._events: list[TradeEvent] = []
        self._records: list[TradeRecord] = []

    # -- inspection ------------------------------------------------------

    @property
    def events(self) -> tuple[TradeEvent, ...]:
        """Every canonical decision, in order."""
        return tuple(self._events)

    @property
    def fill_log(self) -> FillLog:
        """Every execution recorded."""
        return self._fill_log

    @property
    def records(self) -> tuple[TradeRecord, ...]:
        """The aggregate record of every position that has closed."""
        return tuple(self._records)

    def drain_records(self) -> list[TradeRecord]:
        """Return records finalised since the last drain, and clear them.

        Lets the caller append to a ledger without tracking indices.
        """
        drained = list(self._records)
        self._records.clear()
        return drained

    def state_for(self, broker_position_id: str) -> TradeState | None:
        """The canonical state for a broker position, live or closed."""
        managed = self._live.get(broker_position_id) or self._closed.get(broker_position_id)
        return managed.state if managed else None

    def events_for(self, broker_position_id: str) -> tuple[TradeEvent, ...]:
        """Every event recorded against one broker position."""
        return tuple(
            event for event in self._events
            if event.broker_position_id == broker_position_id
        )

    # -- position creation ----------------------------------------------

    def on_position_opened(self, position: SimulatedPosition) -> str | None:
        """Create the canonical position for a filled broker position.

        Called at the fill, before the position is managed for the first time.

        Args:
            position: A freshly filled broker position.

        Returns:
            The canonical ``position_id``, or ``None`` if it could not be
            created, in which case a ``SKIPPED`` event records why.
        """
        broker_id = position.position_id
        existing = self._live.get(broker_id) or self._closed.get(broker_id)
        if existing is not None:
            return existing.canonical_id

        original_stop = position.original_stop
        risk = abs(position.entry_price - original_stop)
        if risk <= 0.0:
            return self._skip(position, "R is zero at the fill")

        # §4.2: the ratio is the strategy's own, and the target is rebuilt from
        # the actual fill below. The carried take_profit is anchored to the
        # entry the strategy intended and is deliberately not consulted.
        raw_ratio = position.metadata.get("strategy_rr_ratio")
        if raw_ratio is None:
            return self._skip(
                position,
                "no strategy tp_ratio on the fill, so the target cannot be recomputed",
            )
        tp_ratio = float(raw_ratio)
        if tp_ratio <= 0.0:
            return self._skip(position, f"tp_ratio {tp_ratio} is not positive")

        steps = int(round(position.volume / self._spec.volume_step))
        if steps <= 0:
            return self._skip(position, f"volume {position.volume} is under one step")

        try:
            state = open_position(
                side=position.side,
                fill_price=position.entry_price,
                original_stop_price=original_stop,
                tp_ratio=tp_ratio,
                steps=steps,
                opened_at=position.entry_time,
            )
        except DomainInvariantError as exc:
            return self._skip(position, f"canonical geometry refused the fill: {exc}")

        canonical_id = self._minter.next_position_id(
            symbol=position.symbol,
            side=position.side,
            entry_bar_time=position.entry_time,
        )
        self._live[broker_id] = _Managed(
            broker_position_id=broker_id,
            canonical_id=canonical_id,
            state=state,
            ambiguous_fill_ids=set(),
        )

        # The broker-facing projection follows the canonical geometry: the
        # target is the recomputed one, and the entry stop is preserved apart
        # from the stop that will move.
        position.original_stop_price = original_stop
        position.take_profit = state.target

        operation = self._minter.next_operation_id(
            scope=canonical_id, kind=OperationKind.ENTRY
        )
        self._append_entry_fill(
            canonical_id, operation, steps, position.entry_price, position.entry_time
        )
        self._events.append(
            TradeEvent(
                kind=TradeEventKind.POSITION_OPENED,
                bar_time=position.entry_time,
                position_id=canonical_id,
                broker_position_id=broker_id,
                steps=steps,
            )
        )
        return canonical_id

    def _skip(self, position: SimulatedPosition, why: str) -> None:
        """Record that a position was not adopted, and why."""
        self._events.append(
            TradeEvent(
                kind=TradeEventKind.SKIPPED,
                bar_time=position.entry_time,
                position_id="",
                broker_position_id=position.position_id,
                detail=why,
            )
        )
        return None

    # -- management ------------------------------------------------------

    def manage(self, bar: pd.Series, bar_time: datetime) -> list[SimulatedPosition]:
        """Advance every managed position against one bar.

        Args:
            bar: The OHLC bar.
            bar_time: Its open time.

        Returns:
            The broker positions that closed on this bar.
        """
        observation = PriceObservation(
            time=bar_time,
            open=float(bar["open"]),
            high=float(bar["high"]),
            low=float(bar["low"]),
            close=float(bar["close"]),
        )
        closed: list[SimulatedPosition] = []
        for broker_id in list(self._live):
            position = self._advance(broker_id, observation)
            if position is not None:
                closed.append(position)
        return closed

    def _advance(
        self, broker_id: str, observation: PriceObservation
    ) -> SimulatedPosition | None:
        """Evaluate one position and execute whatever it asked for."""
        managed = self._live[broker_id]
        result = evaluate(managed.state, observation)
        managed.state = result.state

        for event in result.events:
            if event.type is EventType.PARTIAL_CLOSE_REQUESTED:
                self._do_partial(managed, event.steps, observation, result.ambiguous)
            elif event.type is EventType.STOP_MODIFY_REQUESTED:
                self._do_stop_modify(
                    managed, event.stop_price, event.to_state,
                    observation, result.ambiguous,
                )
            elif event.type is EventType.CLOSE_REQUESTED:
                return self._do_close(managed, event, observation, result.ambiguous)
        return None

    def _do_partial(
        self,
        managed: _Managed,
        steps: int,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> None:
        """Instruct a partial close and fold the result back."""
        state = managed.state
        operation = self._minter.next_operation_id(
            scope=managed.canonical_id, kind=OperationKind.PARTIAL_CLOSE
        )
        result = self._broker.execute_partial_close(
            managed.broker_position_id,
            volume=steps_to_lots(steps, self._spec.volume_step),
            reference_price=state.m1r,
            operation_id=operation,
            at_time=observation.time,
            cause=Milestone.M1R.value,
        )
        if not result.filled:
            raise BrokerRejectionNotHandled(
                f"partial close rejected for {managed.canonical_id}: {result.reason}"
            )

        record = self._fill_record(
            managed.canonical_id, operation, FillKind.PARTIAL_EXIT,
            Milestone.M1R.value, result.executed_volume, result.executed_price,
            observation.time, result.broker_order_id, result.broker_deal_id,
        )
        if ambiguous:
            managed.ambiguous_fill_ids.add(record.fill_id)

        def _apply(fill: FillRecord) -> None:
            managed.state = apply_broker_result(
                managed.state, PartialCloseFilled(steps_closed=fill.quantity_steps)
            )

        record_then_apply(
            self._fill_log, record, for_position=managed.canonical_id, apply=_apply
        )
        self._events.append(
            TradeEvent(
                kind=TradeEventKind.PARTIAL_CLOSE,
                bar_time=observation.time,
                position_id=managed.canonical_id,
                broker_position_id=managed.broker_position_id,
                canonical_only=True,
                requested_level=state.m1r,
                executed_price=result.executed_price,
                steps=record.quantity_steps,
                ambiguous=ambiguous,
            )
        )

    def _do_stop_modify(
        self,
        managed: _Managed,
        stop_price: float,
        to_state: StopState,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> None:
        """Instruct a stop move and fold the confirmation back."""
        operation = self._minter.next_operation_id(
            scope=managed.canonical_id, kind=OperationKind.STOP_MODIFY
        )
        result = self._broker.execute_stop_modify(
            managed.broker_position_id,
            stop_price=stop_price,
            operation_id=operation,
            at_time=observation.time,
        )
        if not result.confirmed:
            raise BrokerRejectionNotHandled(
                f"stop modification rejected for {managed.canonical_id}: {result.reason}"
            )
        managed.state = apply_broker_result(
            managed.state,
            StopModifyConfirmed(stop_price=result.confirmed_stop, to_state=to_state),
        )
        self._events.append(
            TradeEvent(
                kind=TradeEventKind.STOP_PROMOTED,
                bar_time=observation.time,
                position_id=managed.canonical_id,
                broker_position_id=managed.broker_position_id,
                canonical_only=True,
                stop_price=result.confirmed_stop,
                stop_state=to_state,
                ambiguous=ambiguous,
            )
        )

    def _do_close(
        self,
        managed: _Managed,
        event: CloseRequest,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> SimulatedPosition | None:
        """Instruct a close, fold the result back, and emit the trade record."""
        if event.observed_reference is None:
            raise BrokerRejectionNotHandled(
                f"a re-requested close for {managed.canonical_id} carries no observed "
                "reference; what it should carry is U5/R8 and is unresolved"
            )

        self._events.append(
            TradeEvent(
                kind=TradeEventKind.CLOSE_REQUESTED,
                bar_time=observation.time,
                position_id=managed.canonical_id,
                broker_position_id=managed.broker_position_id,
                reason=event.reason,
                requested_level=event.requested_level,
                observed_reference=event.observed_reference,
                steps=event.steps,
                ambiguous=ambiguous,
            )
        )

        operation = self._minter.next_operation_id(
            scope=managed.canonical_id, kind=OperationKind.FINAL_CLOSE
        )
        result = self._broker.execute_close(
            managed.broker_position_id,
            reference_price=event.observed_reference,
            operation_id=operation,
            at_time=observation.time,
            state=_REASON_TO_STATE[event.reason],
            reason=event.reason.value,
            ambiguous=ambiguous,
        )
        if not result.filled:
            raise BrokerRejectionNotHandled(
                f"close rejected for {managed.canonical_id}: {result.reason}"
            )

        record = self._fill_record(
            managed.canonical_id, operation, FillKind.FINAL_EXIT,
            event.reason.value, result.executed_volume, result.executed_price,
            observation.time, result.broker_order_id, result.broker_deal_id,
        )
        if ambiguous:
            managed.ambiguous_fill_ids.add(record.fill_id)

        def _apply(fill: FillRecord) -> None:
            managed.state = apply_broker_result(
                managed.state,
                CloseFilled(
                    reason=event.reason,
                    fill_price=fill.price,
                    steps_closed=fill.quantity_steps,
                ),
            )

        record_then_apply(
            self._fill_log, record, for_position=managed.canonical_id, apply=_apply
        )

        position = self._finalise(managed, event.reason)
        self._events.append(
            TradeEvent(
                kind=TradeEventKind.POSITION_CLOSED,
                bar_time=observation.time,
                position_id=managed.canonical_id,
                broker_position_id=managed.broker_position_id,
                reason=event.reason,
                executed_price=result.executed_price,
                steps=record.quantity_steps,
                ambiguous=ambiguous,
            )
        )
        return position

    # -- end of data -----------------------------------------------------

    def close_all_at_end_of_data(
        self, reference_price: float, at_time: datetime
    ) -> list[SimulatedPosition]:
        """Close every still-open position because the dataset ended.

        The reason is the adapter's to supply: the domain has no concept of a
        dataset boundary.

        Args:
            reference_price: The last price available.
            at_time: When the dataset ended.

        Returns:
            The positions closed.
        """
        reference = float(reference_price)
        closed: list[SimulatedPosition] = []
        for broker_id in list(self._live):
            managed = self._live[broker_id]
            operation = self._minter.next_operation_id(
                scope=managed.canonical_id, kind=OperationKind.FINAL_CLOSE
            )
            result = self._broker.execute_close(
                broker_id,
                reference_price=reference,
                operation_id=operation,
                at_time=at_time,
                state=PositionState.CLOSED_END_OF_DATA,
                reason="end of data",
            )
            if not result.filled:
                raise BrokerRejectionNotHandled(
                    f"end-of-data close rejected for {managed.canonical_id}: "
                    f"{result.reason}"
                )
            record = self._fill_record(
                managed.canonical_id, operation, FillKind.FINAL_EXIT,
                ClosureReason.END_OF_DATA.value, result.executed_volume,
                result.executed_price, at_time,
                result.broker_order_id, result.broker_deal_id,
            )

            def _apply(fill: FillRecord, _m: _Managed = managed) -> None:
                _m.state = apply_broker_result(
                    _m.state,
                    CloseFilled(
                        reason=ClosureReason.END_OF_DATA,
                        fill_price=fill.price,
                        steps_closed=fill.quantity_steps,
                    ),
                )

            record_then_apply(
                self._fill_log, record, for_position=managed.canonical_id, apply=_apply
            )
            position = self._finalise(managed, ClosureReason.END_OF_DATA)
            self._events.append(
                TradeEvent(
                    kind=TradeEventKind.POSITION_CLOSED,
                    bar_time=at_time,
                    position_id=managed.canonical_id,
                    broker_position_id=broker_id,
                    reason=ClosureReason.END_OF_DATA,
                    executed_price=result.executed_price,
                    steps=record.quantity_steps,
                )
            )
            if position is not None:
                closed.append(position)
        return closed

    # -- plumbing --------------------------------------------------------

    def _finalise(
        self, managed: _Managed, reason: ClosureReason
    ) -> SimulatedPosition | None:
        """Emit the aggregate record and retire the position."""
        broker_id = managed.broker_position_id
        position = next(
            (p for p in self._broker.closed_positions() if p.position_id == broker_id),
            None,
        )
        state = managed.state
        record = trade_record_from_fills(
            position_id=managed.canonical_id,
            symbol=self._spec.symbol,
            side=state.side,
            outcome=_REASON_TO_OUTCOME[reason],
            entry_price=state.entry_price,
            original_stop_price=state.original_stop_price,
            original_quantity_steps=state.steps_at_entry,
            executions=list(self._fill_log.fills_for(managed.canonical_id)),
            spec=self._spec,
            take_profit=state.target,
            final_stop_price=state.confirmed_stop_price,
            bars_held=position.bars_held if position else 0,
            commission_per_lot=self._fill_model.commission_per_lot,
            ambiguous_fill_ids=managed.ambiguous_fill_ids,
            fill=position.fill if position else None,
            metadata=dict(position.metadata) if position else None,
        )
        self._records.append(record)
        self._closed[broker_id] = managed
        self._live.pop(broker_id, None)
        return position

    def _fill_record(
        self,
        canonical_id: str,
        operation_id: str,
        kind: FillKind,
        cause: str,
        volume: float,
        price: float,
        at_time: datetime,
        broker_order_id: str | None = None,
        broker_deal_id: str | None = None,
    ) -> FillRecord:
        """Build the execution record for a broker result."""
        return FillRecord(
            identity=FillIdentity(
                position_id=canonical_id,
                operation_id=operation_id,
                broker_deal_id=broker_deal_id,
                execution_index=None if broker_deal_id else 1,
            ),
            kind=kind,
            cause=cause,
            quantity_steps=int(round(volume / self._spec.volume_step)),
            price=price,
            time=at_time,
            broker_order_id=broker_order_id,
        )

    def _append_entry_fill(
        self,
        canonical_id: str,
        operation_id: str,
        steps: int,
        price: float,
        at_time: datetime,
    ) -> None:
        """Append the entry execution, which has no broker result to fold."""
        self._fill_log.record(
            FillRecord(
                identity=FillIdentity(
                    position_id=canonical_id,
                    operation_id=operation_id,
                    execution_index=1,
                ),
                kind=FillKind.ENTRY,
                cause="ENTRY",
                quantity_steps=steps,
                price=price,
                time=at_time,
            ),
            for_position=canonical_id,
        )
