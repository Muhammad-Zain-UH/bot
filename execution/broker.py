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

    @property
    def is_open(self) -> bool:
        """Whether the position is still open."""
        return self.state is PositionState.OPEN

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
