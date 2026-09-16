"""Simulated broker.

Holds virtual positions and resolves stops and targets bar by bar. It has **no
path to a real broker**: nothing in this module imports ``MetaTrader5`` or calls
``order_send``, and ``tests/execution/test_no_live_execution.py`` enforces that
by parsing the AST of every file under ``execution/``.

Modelling choices, all deliberate and all disclosed
---------------------------------------------------
**Entries fill on the next bar's open.** A decision is taken after a bar closes,
so filling at that same close would let the strategy trade at a price it could
only know once the opportunity had passed.

**Gaps fill at the open, not at the level.** If a bar opens beyond the stop, the
fill is the open -- worse than the stop. Assuming a stop always fills exactly at
its level is one of the most common ways a backtest flatters itself.

**Ambiguous bars follow an explicit policy.** See :mod:`execution.intrabar`.
Every ambiguous resolution is flagged on the position and counted in the metrics.

**Position size is fixed at 0.01 lots.** ``risk_manager`` has a known ~10x
sizing defect (PHASE_2_ISSUES R1) and Phase 2A forbids fixing it, so calling it
would contaminate every P&L figure. A fixed size keeps **R-multiples valid**,
which is the size-independent metric that actually matters.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.symbols import SymbolSpecification
from core.types import DomainInvariantError, Side
from execution.broker import (
    FillStatus,
    PositionState,
    SimulatedFill,
    SimulatedPosition,
)
from execution.fills import DEFAULT_FILL_MODEL, FillModel
from execution.intrabar import IntrabarPolicy, resolve_intrabar

__all__ = ["DEFAULT_SIMULATED_VOLUME", "PaperBroker"]

DEFAULT_SIMULATED_VOLUME: float = 0.01
"""Fixed simulated position size, in lots. See the module docstring."""


class PaperBroker:
    """In-memory broker simulation.

    Implements :class:`~execution.broker.Broker`.

    Args:
        spec: Broker symbol specification, supplying pip size and contract value.
        fill_model: Transaction-cost assumptions.
        intrabar_policy: How to resolve bars containing both stop and target.
        max_open_positions: Concurrency cap, mirroring production's
            ``max_concurrent_trades``.
        max_bars_held: Optional time stop, in bars on the driving timeframe.
            ``None`` means positions are held until stop, target, or end of data.
    """

    __slots__ = (
        "_spec", "_fill_model", "_policy", "_max_open", "_max_bars_held",
        "_open", "_closed", "_counter", "_pending",
    )

    def __init__(
        self,
        spec: SymbolSpecification,
        fill_model: FillModel = DEFAULT_FILL_MODEL,
        intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
        max_open_positions: int = 3,
        max_bars_held: int | None = None,
    ) -> None:
        self._spec = spec
        self._fill_model = fill_model
        self._policy = intrabar_policy
        self._max_open = max_open_positions
        self._max_bars_held = max_bars_held
        self._open: list[SimulatedPosition] = []
        self._closed: list[SimulatedPosition] = []
        self._counter = 0
        self._pending: list[dict] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def spec(self) -> SymbolSpecification:
        """The symbol specification in use."""
        return self._spec

    @property
    def fill_model(self) -> FillModel:
        """The cost assumptions in use."""
        return self._fill_model

    @property
    def intrabar_policy(self) -> IntrabarPolicy:
        """The ambiguous-bar policy in use."""
        return self._policy

    def open_positions(self) -> list[SimulatedPosition]:
        """Return all currently open positions."""
        return list(self._open)

    def closed_positions(self) -> list[SimulatedPosition]:
        """Return all closed positions, in the order they closed."""
        return list(self._closed)

    def has_capacity(self) -> bool:
        """Whether another position may be opened."""
        return len(self._open) < self._max_open

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def submit_market_order(
        self,
        *,
        side: Side,
        volume: float,
        stop_loss: float,
        take_profit: float | None,
        decision_time: datetime,
        decision_bar_time: datetime | None,
        execution_bar: pd.Series | None,
        metadata: dict | None = None,
    ) -> SimulatedFill:
        """Fill a market order against ``execution_bar``'s open.

        Args:
            side: Trade direction.
            volume: Size in lots.
            stop_loss: Stop price from the strategy.
            take_profit: Target price from the strategy, if any.
            decision_time: Replay instant the decision was taken at.
            decision_bar_time: Open time of the newest bar the strategy saw.
            execution_bar: The first bar that had not yet begun at
                ``decision_time``. ``None`` if the dataset ended.
            metadata: Strategy context to carry onto the position.

        Returns:
            A :class:`SimulatedFill`. Its ``__post_init__`` raises if the
            execution bar predates the decision.

        Raises:
            DomainInvariantError: If the stop sits on the wrong side of the fill,
                or the timing invariant is violated.
        """
        if execution_bar is None:
            return SimulatedFill(
                status=FillStatus.NO_EXECUTION_BAR,
                side=side, decision_time=decision_time,
                decision_bar_time=decision_bar_time, signal_time=decision_time,
                entry_available_time=None, entry_bar_time=None,
                entry_price=None, reference_price=None, volume=volume,
                reason="dataset ended before an execution bar was available",
            )

        if not self.has_capacity():
            return SimulatedFill(
                status=FillStatus.REJECTED,
                side=side, decision_time=decision_time,
                decision_bar_time=decision_bar_time, signal_time=decision_time,
                entry_available_time=None, entry_bar_time=None,
                entry_price=None, reference_price=None, volume=volume,
                reason=f"max open positions reached ({self._max_open})",
            )

        bar_time = pd.Timestamp(execution_bar["time"]).to_pydatetime()
        reference = float(execution_bar["open"])
        entry_price = self._fill_model.entry_price(side, reference, self._spec)

        # The strategy computed its stop against a slightly different price than
        # the one we filled at. If cost adjustment has pushed the fill through
        # the stop, the trade is not takeable -- reject rather than silently
        # opening a position that is already losing more than 1R.
        if side is Side.BUY and stop_loss >= entry_price:
            return SimulatedFill(
                status=FillStatus.REJECTED,
                side=side, decision_time=decision_time,
                decision_bar_time=decision_bar_time, signal_time=decision_time,
                entry_available_time=bar_time, entry_bar_time=None,
                entry_price=None, reference_price=reference, volume=volume,
                reason=(
                    f"stop {stop_loss:.2f} is at or above the BUY fill "
                    f"{entry_price:.2f} after cost adjustment"
                ),
            )
        if side is Side.SELL and stop_loss <= entry_price:
            return SimulatedFill(
                status=FillStatus.REJECTED,
                side=side, decision_time=decision_time,
                decision_bar_time=decision_bar_time, signal_time=decision_time,
                entry_available_time=bar_time, entry_bar_time=None,
                entry_price=None, reference_price=reference, volume=volume,
                reason=(
                    f"stop {stop_loss:.2f} is at or below the SELL fill "
                    f"{entry_price:.2f} after cost adjustment"
                ),
            )

        fill = SimulatedFill(
            status=FillStatus.FILLED,
            side=side,
            decision_time=decision_time,
            decision_bar_time=decision_bar_time,
            signal_time=decision_time,
            entry_available_time=bar_time,
            entry_bar_time=bar_time,
            entry_price=entry_price,
            reference_price=reference,
            volume=volume,
        )

        self._counter += 1
        position = SimulatedPosition(
            position_id=f"SIM-{self._counter:06d}",
            symbol=self._spec.symbol,
            side=side,
            volume=volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=bar_time,
            fill=fill,
            metadata=dict(metadata or {}),
        )
        if position.risk_distance <= 0.0:
            raise DomainInvariantError(
                f"position {position.position_id} has zero risk distance "
                f"(entry {entry_price}, stop {stop_loss})"
            )
        self._open.append(position)
        return fill

    # ------------------------------------------------------------------
    # Bar processing
    # ------------------------------------------------------------------

    def on_bar(self, bar: pd.Series, bar_time: datetime) -> list[SimulatedPosition]:
        """Advance every open position against one bar.

        A position is never evaluated against the bar it was filled on: the fill
        happened at that bar's open and resolving the same bar's range against
        it would double-count the bar.

        Args:
            bar: OHLC bar with ``open``, ``high``, ``low``, ``close``.
            bar_time: The bar's open time.

        Returns:
            Positions that closed on this bar.
        """
        closed_now: list[SimulatedPosition] = []
        high, low = float(bar["high"]), float(bar["low"])
        bar_open, bar_close = float(bar["open"]), float(bar["close"])

        for position in list(self._open):
            if bar_time <= position.entry_time:
                continue
            position.bars_held += 1

            resolution = resolve_intrabar(
                side=position.side,
                bar_high=high, bar_low=low,
                bar_open=bar_open, bar_close=bar_close,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                policy=self._policy,
            )

            if resolution.hit_stop:
                # Gap handling: if the bar opened already through the stop, the
                # realistic fill is the open, which is worse than the stop.
                gapped = (
                    bar_open < position.stop_loss
                    if position.side is Side.BUY
                    else bar_open > position.stop_loss
                )
                raw_exit = bar_open if gapped else position.stop_loss
                self._close(
                    position,
                    raw_exit_price=raw_exit,
                    exit_time=bar_time,
                    state=PositionState.CLOSED_STOP,
                    reason=(
                        f"{resolution.reason}"
                        + (" | GAPPED through stop, filled at bar open" if gapped else "")
                    ),
                    ambiguous=resolution.was_ambiguous,
                )
                closed_now.append(position)
                continue

            if resolution.hit_target and position.take_profit is not None:
                gapped = (
                    bar_open > position.take_profit
                    if position.side is Side.BUY
                    else bar_open < position.take_profit
                )
                raw_exit = bar_open if gapped else position.take_profit
                self._close(
                    position,
                    raw_exit_price=raw_exit,
                    exit_time=bar_time,
                    state=PositionState.CLOSED_TARGET,
                    reason=(
                        f"{resolution.reason}"
                        + (" | GAPPED through target, filled at bar open" if gapped else "")
                    ),
                    ambiguous=resolution.was_ambiguous,
                )
                closed_now.append(position)
                continue

            if self._max_bars_held is not None and position.bars_held >= self._max_bars_held:
                self._close(
                    position,
                    raw_exit_price=bar_close,
                    exit_time=bar_time,
                    state=PositionState.CLOSED_TIME,
                    reason=f"time stop after {position.bars_held} bars",
                    ambiguous=False,
                )
                closed_now.append(position)

        return closed_now

    def close_all_at_end_of_data(
        self,
        final_price: float,
        final_time: datetime,
    ) -> list[SimulatedPosition]:
        """Close every remaining position because the dataset ended.

        These are flagged :attr:`PositionState.CLOSED_END_OF_DATA` and reported
        separately: their outcome was decided by where the data stopped, not by
        the strategy, so mixing them into win/loss statistics would be misleading.

        Args:
            final_price: Price to close at.
            final_time: Time to record.

        Returns:
            The positions that were closed.
        """
        closed_now: list[SimulatedPosition] = []
        for position in list(self._open):
            self._close(
                position,
                raw_exit_price=final_price,
                exit_time=final_time,
                state=PositionState.CLOSED_END_OF_DATA,
                reason="dataset ended while the position was open",
                ambiguous=False,
            )
            closed_now.append(position)
        return closed_now

    def _close(
        self,
        position: SimulatedPosition,
        *,
        raw_exit_price: float,
        exit_time: datetime,
        state: PositionState,
        reason: str,
        ambiguous: bool,
    ) -> None:
        """Move a position from open to closed, applying exit costs.

        Args:
            position: The position to close.
            raw_exit_price: Pre-cost exit price.
            exit_time: Bar open time of the exit.
            state: Terminal state to record.
            reason: Human-readable explanation.
            ambiguous: Whether an ambiguous bar decided this outcome.
        """
        position.exit_price = self._fill_model.exit_price(
            position.side, raw_exit_price, self._spec
        )
        position.exit_time = exit_time
        position.state = state
        position.exit_reason = reason
        position.was_ambiguous_exit = ambiguous
        self._open.remove(position)
        self._closed.append(position)
