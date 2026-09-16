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

from core.types import DomainInvariantError, Side

__all__ = [
    "Broker",
    "FillStatus",
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
