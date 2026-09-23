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

import math
from datetime import datetime

import pandas as pd

from core.symbols import SymbolSpecification
from core.types import DomainInvariantError, PendingOrderIntent, Side
from execution.broker import (
    BrokerExecutionResult,
    BrokerModifyResult,
    ExecutionStatus,
    PendingOrder,
    PendingState,
    FillStatus,
    PositionState,
    SimulatedFill,
    SimulatedPosition,
)
from execution.fills import DEFAULT_FILL_MODEL, FillModel
from execution.intrabar import IntrabarPolicy

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
    """

    __slots__ = (
        "_spec", "_fill_model", "_policy", "_max_open",
        "_open", "_closed", "_counter", "_pending",
    )

    def __init__(
        self,
        spec: SymbolSpecification,
        fill_model: FillModel = DEFAULT_FILL_MODEL,
        intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
        max_open_positions: int = 3,
    ) -> None:
        self._spec = spec
        self._fill_model = fill_model
        self._policy = intrabar_policy
        self._max_open = max_open_positions
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

        self._open_position(
            side=side, volume=volume, entry_price=entry_price,
            stop_loss=stop_loss, take_profit=take_profit,
            entry_time=bar_time, fill=fill, metadata=metadata,
        )
        return fill

    def _open_position(
        self,
        *,
        side: Side,
        volume: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float | None,
        entry_time: datetime,
        fill: SimulatedFill,
        metadata: dict | None,
    ) -> SimulatedPosition:
        """Create and register an open position.

        Shared by the market and limit paths so both produce identical position
        objects; only the fill price and the bar differ.

        Args:
            side: Trade direction.
            volume: Size in lots.
            entry_price: Price actually filled at.
            stop_loss: Stop price.
            take_profit: Target price, or ``None``.
            entry_time: Open time of the filling bar.
            fill: The fill record to attach.
            metadata: Strategy context.

        Returns:
            The registered position.

        Raises:
            DomainInvariantError: If the stop coincides with the entry.
        """
        self._counter += 1
        position = SimulatedPosition(
            position_id=f"SIM-{self._counter:06d}",
            symbol=self._spec.symbol,
            side=side,
            volume=volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=entry_time,
            fill=fill,
            metadata=dict(metadata or {}),
        )
        if position.risk_distance <= 0.0:
            raise DomainInvariantError(
                f"position {position.position_id} has zero risk distance "
                f"(entry {entry_price}, stop {stop_loss})"
            )
        self._open.append(position)
        return position

    # ------------------------------------------------------------------
    # Pending orders
    # ------------------------------------------------------------------

    def pending_orders(self) -> list[PendingOrder]:
        """Return the orders still resting, in creation order."""
        return [order for order in self._pending if order.is_pending]

    def all_pending_orders(self) -> list[PendingOrder]:
        """Return every pending order ever created, including terminal ones."""
        return list(self._pending)

    def submit_limit_order(
        self,
        intent: PendingOrderIntent,
        *,
        volume: float = DEFAULT_SIMULATED_VOLUME,
        metadata: dict | None = None,
    ) -> PendingOrder:
        """Rest an order at the intent's limit price.

        Nothing is filled here. The order waits for a later bar to reach it;
        whether that ever happens is decided in :meth:`on_bar`.

        Args:
            intent: What the strategy asked for.
            volume: Size in lots.
            metadata: Strategy context, carried to the ledger.

        Returns:
            The resting :class:`~execution.broker.PendingOrder`.
        """
        self._counter += 1
        order = PendingOrder(
            intent=intent,
            order_id=f"PEND-{self._counter:06d}",
            sequence=self._counter,
            volume=volume,
            metadata=dict(metadata or {}),
        )
        self._pending.append(order)
        return order

    def _fill_pending(self, bar: pd.Series, bar_time: datetime) -> list[SimulatedPosition]:
        """Fill any resting order this bar reaches, in creation order.

        Ordering is by ``sequence`` so the outcome does not depend on list
        mutation or dict iteration. The formation bar is excluded by
        :meth:`PendingOrder.may_fill_on`, which raises rather than relying on
        this method to have checked.

        A bar that opens beyond the limit fills at the open, mirroring the gap
        rule already applied to stops: the realistic fill is the first price
        available, which is better than the limit for a limit order.

        Args:
            bar: OHLC bar.
            bar_time: The bar's open time.

        Returns:
            Positions opened on this bar.
        """
        opened: list[SimulatedPosition] = []
        high, low, bar_open = float(bar["high"]), float(bar["low"]), float(bar["open"])

        for order in sorted(self._pending, key=lambda o: o.sequence):
            if not order.is_pending or not order.may_fill_on(bar_time):
                continue
            if not order.intent.is_reached_by(high, low):
                continue

            order.first_reached_time = order.first_reached_time or bar_time
            if not self.has_capacity():
                # Recorded, not filled: capacity is a broker constraint, and the
                # order stays pending rather than being silently dropped.
                continue

            intent = order.intent
            gapped = (
                bar_open < intent.limit_price
                if intent.side is Side.BUY
                else bar_open > intent.limit_price
            )
            raw_fill = bar_open if gapped else intent.limit_price
            entry_price = self._fill_model.entry_price(intent.side, raw_fill, self._spec)

            order.mark_filled(bar_time, entry_price)
            position = self._open_position(
                side=intent.side, volume=order.volume, entry_price=entry_price,
                stop_loss=intent.stop_loss, take_profit=intent.take_profit,
                entry_time=bar_time,
                fill=SimulatedFill(
                    status=FillStatus.FILLED, side=intent.side,
                    decision_time=intent.decision_time,
                    decision_bar_time=intent.formation_bar_time,
                    signal_time=intent.decision_time,
                    entry_available_time=bar_time, entry_bar_time=bar_time,
                    entry_price=entry_price, reference_price=raw_fill,
                    volume=order.volume,
                    reason="limit reached" + (" | GAPPED through limit, filled at bar open" if gapped else ""),
                ),
                metadata={**order.metadata, "pending_order_id": order.order_id},
            )
            opened.append(position)
        return opened

    # ------------------------------------------------------------------
    # Explicit execution verbs (Phase 4B)
    # ------------------------------------------------------------------
    #
    # The broker executes instructions and reports what happened. It decides
    # nothing: not that a position should exit, not that a level was reached,
    # not that a stop should move. Those are canonical decisions and reach here
    # only as an instruction someone else already took.
    #
    # Every verb validates mechanically -- is the position known, is it open,
    # is the quantity sane and on the broker's step grid -- and reports a
    # rejection rather than raising, because a rejection is a result the
    # canonical state is entitled to see (specification §16.2).
    #
    # These verbs are not yet driven by anything. ``on_bar`` is unchanged.

    def position(self, position_id: str) -> SimulatedPosition | None:
        """Return an open position by identity, or ``None``.

        Args:
            position_id: The identity to look up.

        Returns:
            The open position, or ``None`` if no open position has that id.
        """
        for candidate in self._open:
            if candidate.position_id == position_id:
                return candidate
        return None

    def _reject(
        self,
        *,
        position_id: str,
        operation_id: str,
        requested_volume: float,
        reason: str,
        remaining_volume: float = 0.0,
    ) -> BrokerExecutionResult:
        """Build a rejection result. Nothing about the position changes."""
        return BrokerExecutionResult(
            status=ExecutionStatus.REJECTED,
            position_id=position_id,
            operation_id=operation_id,
            requested_volume=requested_volume,
            executed_volume=0.0,
            executed_price=None,
            reference_price=None,
            time=None,
            remaining_volume=remaining_volume,
            closed_position=False,
            reason=reason,
        )

    def _volume_problem(self, position: SimulatedPosition, volume: float) -> str:
        """Return why ``volume`` cannot be executed, or an empty string."""
        if volume <= 0.0:
            return f"requested volume {volume} is not positive"
        snapped = self._spec.round_volume_to_step(volume)
        if abs(snapped - volume) > 1e-9:
            return (
                f"requested volume {volume} is not a multiple of the broker's "
                f"volume step {self._spec.volume_step}"
            )
        if volume > position.remaining_volume + 1e-9:
            return (
                f"requested volume {volume} exceeds the {position.remaining_volume} "
                "still open"
            )
        return ""

    def execute_partial_close(
        self,
        position_id: str,
        *,
        volume: float,
        reference_price: float,
        operation_id: str,
        at_time: datetime,
        cause: str = "",
        broker_order_id: str | None = None,
        broker_deal_id: str | None = None,
    ) -> BrokerExecutionResult:
        """Close part of a position, leaving the remainder open.

        The quantity comes from the instruction; the broker never chooses it.
        The position stays ``OPEN`` and keeps its entry, stop, target and
        ``bars_held`` -- a partial reduces size, it does not end anything.

        Closing the whole remaining quantity is rejected rather than silently
        treated as a close: a partial that leaves nothing open is a full close,
        and the two are different instructions with different results.

        Args:
            position_id: Which position.
            volume: Lots to close. Must be positive, on the broker's step grid,
                and strictly less than what is open.
            reference_price: The pre-cost price to execute against. The caller
                supplies it; exit costs are applied here.
            operation_id: The instruction being answered.
            at_time: When the execution happens.
            cause: Why the caller asked, carried onto the result.
            broker_order_id: Broker order identifier, where one exists.
            broker_deal_id: Broker execution identifier, where one exists.

        Returns:
            A :class:`BrokerExecutionResult`. Rejections leave the position
            untouched.
        """
        position = self.position(position_id)
        if position is None:
            return self._reject(
                position_id=position_id, operation_id=operation_id,
                requested_volume=volume,
                reason="no open position has that identity",
            )
        problem = self._volume_problem(position, volume)
        if problem:
            return self._reject(
                position_id=position_id, operation_id=operation_id,
                requested_volume=volume, reason=problem,
                remaining_volume=position.remaining_volume,
            )
        if abs(volume - position.remaining_volume) <= 1e-9:
            return self._reject(
                position_id=position_id, operation_id=operation_id,
                requested_volume=volume,
                reason=(
                    "a partial close may not close the whole remaining "
                    f"{position.remaining_volume}; use the close verb"
                ),
                remaining_volume=position.remaining_volume,
            )

        executed_price = self._fill_model.exit_price(
            position.side, reference_price, self._spec
        )
        position.volume_closed = round(position.volume_closed + volume, 8)

        return BrokerExecutionResult(
            status=ExecutionStatus.FILLED,
            position_id=position_id,
            operation_id=operation_id,
            requested_volume=volume,
            executed_volume=volume,
            executed_price=executed_price,
            reference_price=reference_price,
            time=at_time,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            remaining_volume=position.remaining_volume,
            closed_position=False,
            reason=cause,
        )

    def execute_close(
        self,
        position_id: str,
        *,
        reference_price: float,
        operation_id: str,
        at_time: datetime,
        state: PositionState = PositionState.CLOSED_MANUAL,
        reason: str = "",
        ambiguous: bool = False,
        broker_order_id: str | None = None,
        broker_deal_id: str | None = None,
    ) -> BrokerExecutionResult:
        """Close whatever remains of a position.

        The terminal state and the reason are supplied by the caller. The
        broker does not infer why a position closed, and ``ambiguous`` is
        likewise reported, not judged: whoever resolved the bar knows.

        Args:
            position_id: Which position.
            reference_price: The pre-cost price to execute against.
            operation_id: The instruction being answered.
            at_time: When the execution happens.
            state: Terminal state to record.
            reason: Why it closed.
            ambiguous: Whether the deciding bar was ambiguous.
            broker_order_id: Broker order identifier, where one exists.
            broker_deal_id: Broker execution identifier, where one exists.

        Returns:
            A :class:`BrokerExecutionResult` whose ``executed_volume`` is the
            quantity that was still open.
        """
        position = self.position(position_id)
        if position is None:
            return self._reject(
                position_id=position_id, operation_id=operation_id,
                requested_volume=0.0,
                reason="no open position has that identity",
            )

        remaining = position.remaining_volume
        self._close(
            position,
            raw_exit_price=reference_price,
            exit_time=at_time,
            state=state,
            reason=reason,
            ambiguous=ambiguous,
        )
        position.volume_closed = position.volume

        return BrokerExecutionResult(
            status=ExecutionStatus.FILLED,
            position_id=position_id,
            operation_id=operation_id,
            requested_volume=remaining,
            executed_volume=remaining,
            executed_price=position.exit_price,
            reference_price=reference_price,
            time=at_time,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            remaining_volume=0.0,
            closed_position=True,
            reason=reason,
        )

    def execute_stop_modify(
        self,
        position_id: str,
        *,
        stop_price: float,
        operation_id: str,
        at_time: datetime,
    ) -> BrokerModifyResult:
        """Move a position's stop, because the caller asked.

        The broker does not judge whether the move is sensible, forward or
        adverse. Monotonicity is a canonical rule (specification §7.2) enforced
        where the decision is made; a broker that second-guessed it would be
        deciding management.

        The original stop is preserved separately, so risk taken at entry
        survives the move.

        Args:
            position_id: Which position.
            stop_price: The new stop.
            operation_id: The instruction being answered.
            at_time: When it is applied.

        Returns:
            A :class:`BrokerModifyResult`.
        """
        position = self.position(position_id)
        if position is None:
            return BrokerModifyResult(
                status=ExecutionStatus.REJECTED,
                position_id=position_id,
                operation_id=operation_id,
                requested_stop=stop_price,
                confirmed_stop=None,
                time=None,
                reason="no open position has that identity",
            )
        if not math.isfinite(stop_price) or stop_price <= 0.0:
            return BrokerModifyResult(
                status=ExecutionStatus.REJECTED,
                position_id=position_id,
                operation_id=operation_id,
                requested_stop=stop_price,
                confirmed_stop=position.stop_loss,
                time=None,
                reason=f"stop price {stop_price} is not a usable price",
            )

        if position.original_stop_price is None:
            position.original_stop_price = position.stop_loss
        position.stop_loss = stop_price

        return BrokerModifyResult(
            status=ExecutionStatus.FILLED,
            position_id=position_id,
            operation_id=operation_id,
            requested_stop=stop_price,
            confirmed_stop=position.stop_loss,
            time=at_time,
        )

    # ------------------------------------------------------------------
    # Bar processing
    # ------------------------------------------------------------------

    def fill_pending_orders(
        self, bar: pd.Series, bar_time: datetime
    ) -> list[SimulatedPosition]:
        """Advance every open position against one bar.

        A position **is** evaluated against the bar it was filled on. A market
        fill happens at that bar's open, so the position genuinely exists for
        the whole of that bar and its range can legitimately reach the stop or
        the target.

        This corrects a Phase 2A defect (R1). The original guard skipped the
        fill bar on the grounds that evaluating it would "double-count the bar",
        which was wrong: the position is exposed to the bar's range from its
        open onward. The guard is retained as ``<`` so a bar that precedes the
        fill is still never applied.

        ``bars_held`` counts the fill bar, so a position closed on the bar it
        opened on has ``bars_held == 1``. Measured effect of this correction on
        the existing fixtures: no exit outcome changed, but every position's
        ``bars_held`` increased by exactly one. See
        ``docs/PHASE_4A_R1_SAME_BAR_EXIT_MEASUREMENT.md``.

        Exit selection is **not** done here. Choosing when a position leaves
        is a canonical decision, taken by the trade-management domain, which
        instructs this broker through :meth:`execute_partial_close`,
        :meth:`execute_stop_modify` and :meth:`execute_close`. This method
        fills resting orders and counts bars.

        Args:
            bar: OHLC bar with ``open``, ``high``, ``low``, ``close``.
            bar_time: The bar's open time.

        Returns:
            Positions **opened** on this bar. Nothing is closed here.
        """

        # Phase A -- pending maintenance (expiry / invalidation / cancellation).
        # Intentionally empty: all three are unresolved research questions and
        # the first LIMIT_FVG experiment runs with them disabled. This is an
        # EXPERIMENTAL CONTROL, not a policy. See
        # docs/PHASE_4A_STEP4_DECISION_EVIDENCE.md.
        #
        # Phase B -- fill any resting order this bar reaches. Runs before
        # management so a position filled on this bar is eligible for its own
        # stop or target on the same bar, per R1.
        opened = self._fill_pending(bar, bar_time)

        # Phase C -- advance positions that are now live. The broker counts
        # bars and nothing else: choosing an exit is a canonical decision and
        # belongs to the trade-management domain, which instructs this broker
        # through execute_partial_close, execute_stop_modify and execute_close.
        for position in list(self._open):
            # R1: strictly-before, not at-or-before. The fill bar is counted.
            if bar_time < position.entry_time:
                continue
            position.bars_held += 1

        return opened

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
