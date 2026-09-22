"""Shadow integration of the canonical trade-management domain.

Phase 5A of ``docs/PHASE_4B_CANONICAL_INTEGRATION_IMPLEMENTATION_PLAN.md``,
following option **G2** from
``docs/PHASE_4B_EXIT_OWNERSHIP_INTRABAR_TIME_EXIT_AND_MIGRATION_DECISION.md``.

What shadow means here
----------------------
:class:`ShadowTradeAdapter` runs the canonical domain over the same bars the
paper broker sees, and records what the domain **would** have done. It never
instructs the broker, never touches a :class:`~execution.broker.SimulatedPosition`,
and never changes an outcome. The broker keeps its exit authority for now; this
exists to produce evidence that the domain reaches the same decisions, before
anything is cut over.

Because nothing is executed, the adapter confirms its own instructions against
its **own** :class:`~core.trade_model.TradeState`. That is faithful rather than
optimistic: paper execution always succeeds, so a request the adapter issued
would have come back confirmed. Prices are taken through the same cost model
the broker would have used, so a shadow exit price is comparable with a real
one.

Two scoping choices, both deliberate
------------------------------------
**The target is reconstructed, not recomputed.** The canonical model derives
the target from the actual fill (specification §4.2), while a position carries a
target the strategy computed from its *intended* entry. Recomputing here would
mix two changes in one measurement, so this adapter derives ``tp_ratio`` from
the carried target, making the canonical target equal the legacy one by
construction. The ladder's effect is then the only thing the comparison sees.
Recomputation belongs to the cut-over phase.

**Ambiguity is observed, never consulted.** Per decision D16, the domain
decides every exit with adverse-first ordering, and
:class:`~execution.intrabar.IntrabarPolicy` survives only as an annotation.
This module records the domain's own ambiguity flag and never asks a policy
which exit to take.

What this module does not do
----------------------------
No live path, no persistence, no recovery, no concurrency policy: I2, I3 and I7
are untouched. No reversal protection, no netting rule, no session handling, no
anomaly grading: R1 through R4 are untouched, as are U5/R8 and U6/R9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd

from core.symbols import SymbolSpecification
from core.trade_model import (
    ClosureReason,
    CloseFilled,
    CloseRequest,
    EventType,
    Milestone,
    PartialCloseFilled,
    PriceObservation,
    StopModifyConfirmed,
    StopState,
    TradeState,
    evaluate,
    open_position,
)
from core.types import DomainInvariantError
from execution.broker import SimulatedPosition
from execution.fills import DEFAULT_FILL_MODEL, FillModel
from execution.trade_identity import (
    FillIdentity,
    FillKind,
    FillLog,
    FillRecord,
    IdentityMinter,
    OperationKind,
)

__all__ = [
    "ShadowEventKind",
    "ShadowEvent",
    "ShadowTradeAdapter",
]


class ShadowEventKind(Enum):
    """What the canonical domain did on one observation.

    Attributes:
        POSITION_OPENED: A filled broker position was adopted as a canonical
            position.
        PARTIAL_CLOSE: The 1R partial. **The legacy path has no equivalent** --
            a new canonical event, not a divergence.
        STOP_PROMOTED: The stop moved to breakeven or to entry ± 1R. **No
            legacy equivalent**, and the point after which exits are no longer
            expected to match.
        CLOSE_REQUESTED: The domain asked to close the remainder.
        POSITION_CLOSED: The close was confirmed.
        SKIPPED: The position could not be adopted, with the reason.
    """

    POSITION_OPENED = "POSITION_OPENED"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    STOP_PROMOTED = "STOP_PROMOTED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class ShadowEvent:
    """One canonical decision, recorded rather than executed.

    Attributes:
        kind: What happened.
        bar_time: The observation it happened on.
        position_id: Canonical position identity.
        broker_position_id: The broker position it shadows.
        canonical_only: True when the legacy path has no equivalent concept --
            the ``NEW_CANONICAL_EVENT`` classification.
        reason: Closure reason, on a close.
        requested_level: The level the domain asked for, on a close.
        observed_reference: The first price available at or beyond it.
        executed_price: The cost-adjusted price the adapter recorded.
        steps: Quantity in volume steps, on a quantity-changing event.
        stop_price: The new stop, on a promotion.
        stop_state: The state promoted to.
        ambiguous: The domain's own ambiguity flag for the observation.
        detail: Free text, used for a skip reason.
    """

    kind: ShadowEventKind
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
class _Shadowed:
    """One position's shadow state."""

    broker_position_id: str
    state: TradeState
    promoted: bool = False
    partialled: bool = False


class ShadowTradeAdapter:
    """Runs the canonical domain beside the broker, changing nothing.

    Args:
        spec: Broker specification, supplying the volume step and the symbol.
        fill_model: Cost model, used so shadow prices are comparable with real
            ones.
        minter: Identity minter. One is created if not supplied.
        fill_log: Fill log. One is created if not supplied.
    """

    __slots__ = (
        "_spec", "_fill_model", "_minter", "_fill_log",
        "_live", "_closed", "_ids", "_events",
    )

    def __init__(
        self,
        spec: SymbolSpecification,
        fill_model: FillModel = DEFAULT_FILL_MODEL,
        minter: IdentityMinter | None = None,
        fill_log: FillLog | None = None,
    ) -> None:
        self._spec = spec
        self._fill_model = fill_model
        self._minter = minter or IdentityMinter()
        self._fill_log = fill_log or FillLog()
        self._live: dict[str, _Shadowed] = {}
        self._closed: dict[str, _Shadowed] = {}
        self._ids: dict[str, str] = {}
        self._events: list[ShadowEvent] = []

    # -- inspection ------------------------------------------------------

    @property
    def events(self) -> tuple[ShadowEvent, ...]:
        """Every canonical decision recorded, in order."""
        return tuple(self._events)

    @property
    def fill_log(self) -> FillLog:
        """The executions the domain would have produced."""
        return self._fill_log

    def state_for(self, broker_position_id: str) -> TradeState | None:
        """The canonical state shadowing a broker position, live or closed."""
        entry = self._live.get(broker_position_id) or self._closed.get(broker_position_id)
        return entry.state if entry else None

    def events_for(self, broker_position_id: str) -> tuple[ShadowEvent, ...]:
        """Every event recorded against one broker position."""
        return tuple(
            event for event in self._events
            if event.broker_position_id == broker_position_id
        )

    # -- adoption --------------------------------------------------------

    def adopt(self, position: SimulatedPosition) -> str | None:
        """Create the canonical position for a filled broker position.

        Called at the fill, never at intent: an order that never fills has no
        position (specification §13).

        ``tp_ratio`` is reconstructed from the carried target so that the
        canonical target equals the legacy one -- see the module docstring.

        Args:
            position: A filled broker position.

        Returns:
            The canonical ``position_id``, or ``None`` if the position could
            not be adopted, in which case a ``SKIPPED`` event records why.
        """
        broker_id = position.position_id
        if broker_id in self._ids:
            return self._ids[broker_id]  # adoption is idempotent

        original_stop = position.original_stop
        risk = abs(position.entry_price - original_stop)
        if position.take_profit is None:
            return self._skip(position, "position carries no target, so tp_ratio is undefined")
        if risk <= 0.0:
            return self._skip(position, "R is zero at the fill")

        steps = int(round(position.volume / self._spec.volume_step))
        if steps <= 0:
            return self._skip(position, f"volume {position.volume} is under one step")

        tp_ratio = abs(position.take_profit - position.entry_price) / risk
        if tp_ratio <= 0.0:
            return self._skip(position, "target coincides with the entry")

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
        self._live[broker_id] = _Shadowed(broker_position_id=broker_id, state=state)
        self._events.append(
            ShadowEvent(
                kind=ShadowEventKind.POSITION_OPENED,
                bar_time=position.entry_time,
                position_id=canonical_id,
                broker_position_id=broker_id,
                steps=steps,
            )
        )
        self._ids[broker_id] = canonical_id
        return canonical_id

    def _skip(self, position: SimulatedPosition, why: str) -> None:
        """Record that a position was not adopted, and why."""
        self._events.append(
            ShadowEvent(
                kind=ShadowEventKind.SKIPPED,
                bar_time=position.entry_time,
                position_id="",
                broker_position_id=position.position_id,
                detail=why,
            )
        )
        return None

    # -- observation -----------------------------------------------------

    def observe(self, bar: pd.Series, bar_time: datetime) -> tuple[ShadowEvent, ...]:
        """Advance every shadowed position against one bar.

        The broker is not consulted and not changed. Each instruction the
        domain emits is confirmed against the adapter's own state, because
        paper execution would have succeeded.

        Args:
            bar: The OHLC bar.
            bar_time: Its open time.

        Returns:
            The events recorded for this bar.
        """
        observation = PriceObservation(
            time=bar_time,
            open=float(bar["open"]),
            high=float(bar["high"]),
            low=float(bar["low"]),
            close=float(bar["close"]),
        )

        produced: list[ShadowEvent] = []
        for broker_id in list(self._live):
            produced.extend(self._advance(broker_id, observation))
        self._events.extend(produced)
        return tuple(produced)

    def _advance(self, broker_id: str, observation: PriceObservation) -> list[ShadowEvent]:
        """Evaluate one position and confirm whatever it asked for."""
        shadowed = self._live[broker_id]
        canonical_id = self._ids[broker_id]
        result = evaluate(shadowed.state, observation)
        shadowed.state = result.state
        produced: list[ShadowEvent] = []

        for event in result.events:
            if event.type is EventType.PARTIAL_CLOSE_REQUESTED:
                produced.append(
                    self._confirm_partial(
                        shadowed, canonical_id, event.steps, observation, result.ambiguous
                    )
                )
            elif event.type is EventType.STOP_MODIFY_REQUESTED:
                produced.append(
                    self._confirm_stop(
                        shadowed, canonical_id, event.stop_price, event.to_state,
                        observation, result.ambiguous,
                    )
                )
            elif event.type is EventType.CLOSE_REQUESTED:
                produced.extend(
                    self._confirm_close(
                        shadowed, canonical_id, event, observation, result.ambiguous
                    )
                )
        return produced

    def _confirm_partial(
        self,
        shadowed: _Shadowed,
        canonical_id: str,
        steps: int,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> ShadowEvent:
        """Record and apply the 1R partial. No legacy equivalent exists."""
        state = shadowed.state
        executed = self._fill_model.exit_price(state.side, state.m1r, self._spec)
        operation = self._minter.next_operation_id(
            scope=canonical_id, kind=OperationKind.PARTIAL_CLOSE
        )
        self._record_fill(
            canonical_id, operation, FillKind.PARTIAL_EXIT, Milestone.M1R.value,
            steps, executed, observation.time,
        )
        shadowed.state = self._apply(shadowed.state, PartialCloseFilled(steps_closed=steps))
        shadowed.partialled = True
        return ShadowEvent(
            kind=ShadowEventKind.PARTIAL_CLOSE,
            bar_time=observation.time,
            position_id=canonical_id,
            broker_position_id=shadowed.broker_position_id,
            canonical_only=True,
            requested_level=state.m1r,
            executed_price=executed,
            steps=steps,
            ambiguous=ambiguous,
        )

    def _confirm_stop(
        self,
        shadowed: _Shadowed,
        canonical_id: str,
        stop_price: float,
        to_state: StopState,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> ShadowEvent:
        """Record and apply a stop promotion. No legacy equivalent exists."""
        self._minter.next_operation_id(scope=canonical_id, kind=OperationKind.STOP_MODIFY)
        shadowed.state = self._apply(
            shadowed.state,
            StopModifyConfirmed(stop_price=stop_price, to_state=to_state),
        )
        shadowed.promoted = True
        return ShadowEvent(
            kind=ShadowEventKind.STOP_PROMOTED,
            bar_time=observation.time,
            position_id=canonical_id,
            broker_position_id=shadowed.broker_position_id,
            canonical_only=True,
            stop_price=stop_price,
            stop_state=to_state,
            ambiguous=ambiguous,
        )

    def _confirm_close(
        self,
        shadowed: _Shadowed,
        canonical_id: str,
        event: CloseRequest,
        observation: PriceObservation,
        ambiguous: bool,
    ) -> list[ShadowEvent]:
        """Record and apply a closure."""
        state = shadowed.state
        reference = event.observed_reference
        reason = event.reason
        steps = event.steps
        executed = (
            self._fill_model.exit_price(state.side, reference, self._spec)
            if reference is not None else None
        )
        operation = self._minter.next_operation_id(
            scope=canonical_id, kind=OperationKind.FINAL_CLOSE
        )
        requested = ShadowEvent(
            kind=ShadowEventKind.CLOSE_REQUESTED,
            bar_time=observation.time,
            position_id=canonical_id,
            broker_position_id=shadowed.broker_position_id,
            reason=reason,
            requested_level=event.requested_level,
            observed_reference=reference,
            executed_price=executed,
            steps=steps,
            ambiguous=ambiguous,
        )
        if executed is None:
            return [requested]

        self._record_fill(
            canonical_id, operation, FillKind.FINAL_EXIT, reason.value,
            steps, executed, observation.time,
        )
        shadowed.state = self._apply(
            shadowed.state,
            CloseFilled(reason=reason, fill_price=executed, steps_closed=steps),
        )
        self._closed[shadowed.broker_position_id] = shadowed
        self._live.pop(shadowed.broker_position_id, None)
        return [
            requested,
            ShadowEvent(
                kind=ShadowEventKind.POSITION_CLOSED,
                bar_time=observation.time,
                position_id=canonical_id,
                broker_position_id=shadowed.broker_position_id,
                reason=reason,
                executed_price=executed,
                steps=steps,
                ambiguous=ambiguous,
            ),
        ]

    # -- plumbing --------------------------------------------------------

    def _record_fill(
        self,
        canonical_id: str,
        operation_id: str,
        kind: FillKind,
        cause: str,
        steps: int,
        price: float,
        at_time: datetime,
    ) -> None:
        """Append one execution through the Phase 2 identity infrastructure."""
        record = FillRecord(
            identity=FillIdentity(
                position_id=canonical_id,
                operation_id=operation_id,
                execution_index=1,
            ),
            kind=kind,
            cause=cause,
            quantity_steps=steps,
            price=price,
            time=at_time,
        )
        self._fill_log.record(record, for_position=canonical_id)

    @staticmethod
    def _apply(state: TradeState, result: object) -> TradeState:
        """Fold a broker result into canonical state."""
        from core.trade_model import apply_broker_result

        return apply_broker_result(state, result)
