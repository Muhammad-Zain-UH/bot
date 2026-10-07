"""Broker protocol and the simulated position/fill records.

Only :class:`~execution.paper_broker.PaperBroker` implements this in Phase 2A.
**No live implementation exists anywhere in this package**, by design -- this
phase must remain incapable of live trading. ``tests/execution`` asserts, by
parsing the AST, that nothing under ``execution/`` imports ``MetaTrader5`` or
calls ``order_send``.

Entry-timing provenance
-----------------------
:class:`SimulatedFill` records the full causal chain of a fill::

    decision_time         when the strategy ran
    decision_bar_time     open time of the newest bar it could see
    signal_time           when the signal was emitted (== decision_time)
    entry_available_time  open time of the first bar that had NOT yet started
    entry_bar_time        the bar actually filled against
    entry_price           the fill

This exists so a test can prove the fill used information that did **not** exist
when the signal was generated. ``entry_bar_time >= decision_time`` must always
hold; if it did not, the simulator would be trading on the bar it decided from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

import pandas as pd

from core.types import DomainInvariantError, PendingOrderIntent, Side

__all__ = [
    "Broker",
    "BrokerExecutionResult",
    "BrokerModifyResult",
    "ExecutionStatus",
    "FillStatus",
    "PendingOrder",
    "PendingState",
    "PositionState",
    "SimulatedFill",
    "SimulatedPosition",
]


class FillStatus(Enum):
    """Outcome of an order submission in the simulator."""

    FILLED = "FILLED"
    REJECTED = "REJECTED"
    NO_EXECUTION_BAR = "NO_EXECUTION_BAR"
    """The dataset ended before a bar existed to fill against."""


class PositionState(Enum):
    """Lifecycle of a simulated position."""

    OPEN = "OPEN"
    CLOSED_STOP = "CLOSED_STOP"
    CLOSED_TARGET = "CLOSED_TARGET"
    CLOSED_TIME = "CLOSED_TIME"
    CLOSED_END_OF_DATA = "CLOSED_END_OF_DATA"
    CLOSED_MANUAL = "CLOSED_MANUAL"


class PendingState(Enum):
    """Lifecycle of a resting order.

    Kept separate from :class:`FillStatus` (the outcome of one submission
    attempt) and :class:`PositionState` (the life of an open position), because
    other code already switches on those and overloading them would conflate
    three different questions.

    ``EXPIRED``, ``INVALIDATED`` and ``CANCELLED`` are defined here because the
    lifecycle is incomplete without them, but **no rule currently produces
    them**: expiry, zone invalidation and cross-session cancellation are
    unresolved research questions, and the first experiment runs with all three
    disabled. See ``docs/PHASE_4A_STEP4_DECISION_EVIDENCE.md``.
    """

    PENDING = "PENDING"
    FILLED = "FILLED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class PendingOrder:
    """A resting order owned by the execution layer.

    The strategy produced the :class:`~core.types.PendingOrderIntent`; this
    object owns everything about its life afterwards. It enforces the
    no-look-ahead invariant itself rather than trusting whoever calls it.

    Attributes:
        intent: What the strategy asked for.
        order_id: Simulator identifier.
        sequence: Monotonic creation counter, so several resting orders are
            always processed in a defined order.
        volume: Size in lots.
        state: Current lifecycle state.
        first_reached_time: Bar on which the limit was first reached, if ever.
        fill_time: Bar it filled on.
        fill_price: Price it filled at.
        terminal_reason: Why it left ``PENDING``.
        metadata: Carried through to the ledger.
    """

    intent: PendingOrderIntent
    order_id: str
    sequence: int
    volume: float
    state: PendingState = PendingState.PENDING
    first_reached_time: datetime | None = None
    fill_time: datetime | None = None
    fill_price: float | None = None
    terminal_reason: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        """Whether the order is still waiting."""
        return self.state is PendingState.PENDING

    def may_fill_on(self, bar_time: datetime) -> bool:
        """Whether a bar is eligible to fill this order at all.

        The formation bar is never eligible. A pending order created from a gap
        that completed on bar N can fill no earlier than N+1.

        Args:
            bar_time: Open time of the bar being offered.

        Returns:
            Whether the bar is strictly after formation.
        """
        return bar_time > self.intent.formation_bar_time

    def mark_filled(self, bar_time: datetime, price: float) -> None:
        """Record a fill, refusing one that would violate the timing invariant.

        Args:
            bar_time: Open time of the filling bar.
            price: Price the order filled at.

        Raises:
            DomainInvariantError: If the order is not pending, or the bar is the
                formation bar or earlier -- which would mean the simulator filled
                using a bar the strategy had already seen.
        """
        if not self.is_pending:
            raise DomainInvariantError(
                f"pending order {self.order_id} is {self.state.value}, not PENDING"
            )
        if not self.may_fill_on(bar_time):
            raise DomainInvariantError(
                f"LOOK-AHEAD: pending order {self.order_id} would fill on {bar_time}, "
                f"which is not after its formation bar "
                f"{self.intent.formation_bar_time}."
            )
        self.state = PendingState.FILLED
        self.fill_time = bar_time
        self.fill_price = price
        self.terminal_reason = "limit reached"


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    """A fill with its complete timing provenance.

    Attributes:
        status: Whether the order filled.
        side: Trade direction.
        decision_time: Replay instant at which the strategy ran.
        decision_bar_time: Open time of the newest bar visible to that decision.
        signal_time: When the signal was emitted.
        entry_available_time: Open time of the first bar that had not yet begun
            at ``decision_time`` -- the earliest bar that could legitimately
            fill the order.
        entry_bar_time: Open time of the bar actually filled against.
        entry_price: The fill price, after spread and slippage.
        reference_price: The raw bar price before cost adjustment.
        volume: Size in lots.
        reason: Explanation, populated when the order did not fill.
    """

    status: FillStatus
    side: Side
    decision_time: datetime
    decision_bar_time: datetime | None
    signal_time: datetime
    entry_available_time: datetime | None
    entry_bar_time: datetime | None
    entry_price: float | None
    reference_price: float | None
    volume: float
    reason: str = ""

    def __post_init__(self) -> None:
        """Enforce the no-look-ahead timing invariant.

        Raises:
            DomainInvariantError: If the execution bar opened before the
                decision was taken, which would mean the simulator filled using
                a bar the strategy had already seen.
        """
        if self.status is not FillStatus.FILLED:
            return
        if self.entry_bar_time is None or self.entry_price is None:
            raise DomainInvariantError("a FILLED result must carry an entry bar and price")
        if self.entry_bar_time < self.decision_time:
            raise DomainInvariantError(
                f"LOOK-AHEAD: execution bar opened at {self.entry_bar_time} which is "
                f"before the decision at {self.decision_time}. The simulator would be "
                f"filling on a bar the strategy had already observed."
            )
        if self.decision_bar_time is not None and self.entry_bar_time <= self.decision_bar_time:
            raise DomainInvariantError(
                f"LOOK-AHEAD: execution bar {self.entry_bar_time} is not after the "
                f"decision bar {self.decision_bar_time}."
            )


@dataclass(slots=True)
class SimulatedPosition:
    """A virtual position held by the paper broker.

    Attributes:
        position_id: Unique identifier within the run.
        symbol: Instrument.
        side: Direction.
        volume: Size in lots.
        entry_price: Fill price.
        stop_loss: Stop price.
        take_profit: Target price, if any.
        entry_time: Open time of the bar filled against.
        state: Current lifecycle state.
        exit_price: Fill price on exit, once closed.
        exit_time: Bar open time of the exit.
        exit_reason: Why the position closed.
        was_ambiguous_exit: Whether the exit bar contained both stop and target,
            meaning the outcome was decided by policy rather than evidence.
        bars_held: How many bars the position was open for.
        fill: The originating fill, retained for timing provenance.
    """

    position_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float | None
    entry_time: datetime
    state: PositionState = PositionState.OPEN
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str = ""
    was_ambiguous_exit: bool = False
    bars_held: int = 0
    fill: SimulatedFill | None = None
    metadata: dict = field(default_factory=dict)

    # -- Projection fields (Phase 4B) -----------------------------------
    # Transitional. These make the broker-facing view expressible without
    # making it authoritative. Canonical quantity, milestone state and
    # management state belong to ``core.trade_model.TradeState``, which is
    # connected in a later phase; nothing here decides anything.
    original_stop_price: float | None = None
    """The stop at entry, kept apart from :attr:`stop_loss`, which moves.

    ``None`` on a position created before the distinction existed, in which
    case :attr:`original_stop` falls back to the current stop -- identical to
    the old behaviour while no stop has moved.
    """

    volume_closed: float = 0.0
    """How much of :attr:`volume` has been executed out, in lots.

    :attr:`volume` stays the size at entry. Existing positions leave this at
    zero, so :attr:`remaining_volume` equals :attr:`volume` exactly as before.
    """

    @property
    def is_open(self) -> bool:
        """Whether the position is still open."""
        return self.state is PositionState.OPEN

    @property
    def original_stop(self) -> float:
        """The stop at entry, for risk that must not move with the stop.

        Falls back to :attr:`stop_loss` when no original was recorded, which is
        the same value while the stop has not been promoted.
        """
        return self.stop_loss if self.original_stop_price is None else self.original_stop_price

    @property
    def remaining_volume(self) -> float:
        """Broker-executable quantity: entry size less what has been closed."""
        return round(self.volume - self.volume_closed, 8)

    @property
    def is_partially_closed(self) -> bool:
        """Whether some, but not all, of the position has been executed out."""
        return 0.0 < self.volume_closed < self.volume

    @property
    def risk_distance(self) -> float:
        """Absolute price distance from entry to stop -- the ``1R`` unit."""
        return abs(self.entry_price - self.stop_loss)

    def price_move(self, price: float) -> float:
        """Signed favourable move from entry to ``price``.

        Args:
            price: The price to measure to.

        Returns:
            Positive when in profit for this side, negative when in loss.
        """
        return (price - self.entry_price) * self.side.sign


class ExecutionStatus(Enum):
    """Outcome of one explicit instruction to the broker."""

    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class BrokerExecutionResult:
    """What the broker did with a close instruction, and what it cost.

    The broker reports; it does not decide. ``requested_volume`` and
    ``executed_volume`` are separate because a broker may fill less than it was
    asked for, and the canonical state is entitled to know which is which
    (specification §16).

    Attributes:
        status: Filled or rejected.
        position_id: The position the instruction concerned.
        operation_id: The instruction it answers. Supplied by the caller; the
            broker never mints one.
        requested_volume: What the instruction asked for, in lots.
        executed_volume: What actually executed, in lots. Zero on a rejection.
        executed_price: The price obtained, after exit costs. ``None`` on a
            rejection.
        reference_price: The pre-cost price the execution was measured
            against, retained so the cost applied stays visible.
        time: When it executed.
        broker_order_id: The broker's order identifier, where one exists.
        broker_deal_id: The broker's execution identifier, where one exists.
        remaining_volume: Broker-facing quantity left open afterwards.
        closed_position: Whether this execution left nothing open.
        reason: Why it was rejected, or the cause the caller supplied.
    """

    status: ExecutionStatus
    position_id: str
    operation_id: str
    requested_volume: float
    executed_volume: float
    executed_price: float | None
    reference_price: float | None
    time: datetime | None
    broker_order_id: str | None = None
    broker_deal_id: str | None = None
    remaining_volume: float = 0.0
    closed_position: bool = False
    reason: str = ""

    @property
    def filled(self) -> bool:
        """Whether the instruction executed."""
        return self.status is ExecutionStatus.FILLED

    @property
    def partially_filled(self) -> bool:
        """Whether less executed than was asked for."""
        return self.filled and self.executed_volume < self.requested_volume


@dataclass(frozen=True, slots=True)
class BrokerModifyResult:
    """What the broker did with a stop-modification instruction.

    A modification transfers no quantity, so it produces no execution and no
    deal identity (specification §16.3). ``requested_stop`` and
    ``confirmed_stop`` are kept apart because an unconfirmed move protects
    nothing.

    Attributes:
        status: Confirmed or rejected.
        position_id: The position the instruction concerned.
        operation_id: The instruction it answers.
        requested_stop: The price the caller asked for.
        confirmed_stop: The price now registered, or ``None`` on a rejection.
        time: When it was applied.
        reason: Why it was rejected.
    """

    status: ExecutionStatus
    position_id: str
    operation_id: str
    requested_stop: float
    confirmed_stop: float | None
    time: datetime | None
    reason: str = ""

    @property
    def confirmed(self) -> bool:
        """Whether the broker acknowledged the move."""
        return self.status is ExecutionStatus.FILLED


@runtime_checkable
class Broker(Protocol):
    """Places orders and tracks positions.

    Production and replay are intended to share this interface so the same
    decision code can drive either. Phase 2A implements only the simulator.
    """

    def submit_market_order(
        self,
        *,
        side: Side,
        volume: float,
        stop_loss: float,
        take_profit: float | None,
        decision_time: datetime,
        decision_bar_time: datetime | None,
        metadata: dict | None = None,
    ) -> SimulatedFill:
        """Submit a market order and return the resulting fill."""
        ...

    def on_bar(self, bar: pd.Series, bar_time: datetime) -> list[SimulatedPosition]:
        """Advance open positions against one bar; return any that closed."""
        ...

    def open_positions(self) -> list[SimulatedPosition]:
        """Return all currently open positions."""
        ...

    def closed_positions(self) -> list[SimulatedPosition]:
        """Return all closed positions."""
        ...
