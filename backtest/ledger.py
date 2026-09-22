"""Simulated trade ledger.

Records what the simulator did, with enough provenance that any figure in the
report can be traced back to the bars that produced it.

Outcome labels come from the simulated future
---------------------------------------------
:class:`TradeOutcome` is never assigned by judgement or by a rule of thumb. A
trade is ``STOPPED`` because the simulator resolved a stop against later bars;
it is ``TARGET_HIT`` because a target was resolved the same way. No artificial
positive/negative label is ever created.

``END_OF_DATA`` is kept deliberately separate: those outcomes were decided by
where the dataset stopped, not by the strategy, so folding them into win/loss
statistics would misattribute them.

Results are written to ``backtest_results/`` as JSONL, never into
``trade_states/``. Simulated trades must not mix with production trade history --
the Phase 1 audit found fabricated records already sitting in that directory.

Currency figures are size-dependent
-----------------------------------
Every position is a fixed 0.01 lots, because ``risk_manager`` has a known ~10x
sizing defect (PHASE_2_ISSUES R1) that Phase 2A must not fix. Monetary P&L is
therefore an artefact of that fixed size and carries no information about
production risk. :attr:`SimulatedTrade.r_multiple` is the size-independent
measure and is the primary metric.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from typing import Iterable, Sequence

from core.symbols import SymbolSpecification
from core.types import Side
from execution.broker import PositionState, SimulatedFill, SimulatedPosition
from execution.trade_identity import FillKind, FillRecord

__all__ = [
    "SimulatedTrade",
    "TradeExecution",
    "TradeLedger",
    "TradeOutcome",
    "TradeRecord",
    "trade_from_position",
    "trade_record_from_fills",
]


class TradeOutcome(Enum):
    """How a simulated trade ended.

    Attributes:
        SIGNAL_ONLY: A signal was generated but no order was submitted.
        REJECTED: An order was submitted and the simulator declined it -- for
            example the concurrency cap, or a stop that cost adjustment had
            already pushed through.
        NO_EXECUTION_BAR: The dataset ended before a fillable bar existed.
        STOPPED: Stop resolved against a later bar.
        TARGET_HIT: Target resolved against a later bar.
        TIME_EXIT: Closed by the time stop.
        END_OF_DATA: Still open when the dataset ended. Reported separately.
        MANUAL: Closed explicitly by the harness.
    """

    SIGNAL_ONLY = "SIGNAL_ONLY"
    REJECTED = "REJECTED"
    NO_EXECUTION_BAR = "NO_EXECUTION_BAR"
    STOPPED = "STOPPED"
    TARGET_HIT = "TARGET_HIT"
    TIME_EXIT = "TIME_EXIT"
    END_OF_DATA = "END_OF_DATA"
    MANUAL = "MANUAL"

    @property
    def is_completed_trade(self) -> bool:
        """Whether this outcome represents a trade the strategy actually finished.

        ``END_OF_DATA`` is excluded: the dataset boundary decided it, not the
        strategy.
        """
        return self in {
            TradeOutcome.STOPPED,
            TradeOutcome.TARGET_HIT,
            TradeOutcome.TIME_EXIT,
            TradeOutcome.MANUAL,
        }


_STATE_TO_OUTCOME: dict[PositionState, TradeOutcome] = {
    PositionState.CLOSED_STOP: TradeOutcome.STOPPED,
    PositionState.CLOSED_TARGET: TradeOutcome.TARGET_HIT,
    PositionState.CLOSED_TIME: TradeOutcome.TIME_EXIT,
    PositionState.CLOSED_END_OF_DATA: TradeOutcome.END_OF_DATA,
    PositionState.CLOSED_MANUAL: TradeOutcome.MANUAL,
}


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """One simulated trade, with full timing and cost provenance.

    Attributes:
        trade_id: Identifier unique within the run.
        symbol: Instrument.
        side: Direction.
        outcome: How it ended, derived from the simulated future.
        decision_time: Replay instant the strategy ran at.
        decision_bar_time: Open time of the newest bar the strategy could see.
        signal_time: When the signal was emitted.
        entry_available_time: Open time of the earliest bar that could
            legitimately fill the order.
        entry_bar_time: Open time of the bar actually filled against.
        entry_time: Alias of ``entry_bar_time``, for the conventional field name.
        entry_price: Fill price, after spread and slippage.
        entry_reference_price: Raw bar price before cost adjustment.
        stop_loss: Stop price.
        take_profit: Target price, if any.
        exit_time: Bar open time of the exit.
        exit_price: Exit fill price, after costs.
        exit_reason: Why it closed, including any ambiguity note.
        was_ambiguous_exit: Whether an ambiguous bar decided the outcome.
        quantity: Size in lots.
        price_risk: Entry-to-stop distance in price units.
        gross_pnl: P&L before commission, in account currency.
        commission: Commission charged.
        slippage_cost: Modelled slippage cost.
        net_pnl: ``gross_pnl - commission``.
        risk_amount: Money at risk at ``1R``, given ``quantity``.
        r_multiple: ``net_pnl / risk_amount`` -- the size-independent result.
        bars_held: Bars the position was open for.
        regime: Regime the strategy reported at decision time.
        setup_type: Setup label the strategy reported.
        entry_method: Entry style the strategy reported.
        confidence: Confidence score the strategy reported.
        metadata: Any further strategy context captured at decision time.
    """

    trade_id: str
    symbol: str
    side: str
    outcome: str

    decision_time: str
    decision_bar_time: str | None
    signal_time: str
    entry_available_time: str | None
    entry_bar_time: str | None
    entry_time: str | None
    entry_price: float | None
    entry_reference_price: float | None

    stop_loss: float | None
    take_profit: float | None
    exit_time: str | None
    exit_price: float | None
    exit_reason: str
    was_ambiguous_exit: bool

    quantity: float
    price_risk: float | None
    gross_pnl: float
    commission: float
    slippage_cost: float
    net_pnl: float
    risk_amount: float | None
    r_multiple: float | None
    bars_held: int

    regime: str = ""
    setup_type: str = ""
    entry_method: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_win(self) -> bool:
        """Whether the trade finished with positive net P&L."""
        return self.outcome_enum.is_completed_trade and self.net_pnl > 0.0

    @property
    def is_loss(self) -> bool:
        """Whether the trade finished with negative net P&L."""
        return self.outcome_enum.is_completed_trade and self.net_pnl < 0.0

    @property
    def outcome_enum(self) -> TradeOutcome:
        """The outcome as an enum."""
        return TradeOutcome(self.outcome)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return asdict(self)


def trade_from_position(
    position: SimulatedPosition,
    spec: SymbolSpecification,
    commission: float = 0.0,
    slippage_cost: float = 0.0,
) -> SimulatedTrade:
    """Build a ledger record from a closed simulated position.

    P&L is computed through :meth:`~core.symbols.SymbolSpecification.money_for_price_distance`,
    which derives value from the broker's own tick size and tick value. It does
    **not** use ``risk_manager``, whose contract-size assumption is wrong by ~10x.

    Args:
        position: The closed position.
        spec: Broker specification supplying monetary conversion.
        commission: Commission charged on the round turn.
        slippage_cost: Modelled slippage cost, for reporting.

    Returns:
        A :class:`SimulatedTrade`.

    Raises:
        ValueError: If the position is still open.
    """
    if position.is_open:
        raise ValueError(f"position {position.position_id} is still open")

    outcome = _STATE_TO_OUTCOME.get(position.state, TradeOutcome.MANUAL)
    fill = position.fill

    price_move = 0.0
    if position.exit_price is not None:
        price_move = position.price_move(position.exit_price)

    gross_pnl = price_move * spec.money_per_price_unit(position.volume)
    net_pnl = gross_pnl - commission

    price_risk = position.risk_distance
    risk_amount = spec.money_for_price_distance(price_risk, position.volume)
    r_multiple = (net_pnl / risk_amount) if risk_amount > 0.0 else None

    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    return SimulatedTrade(
        trade_id=position.position_id,
        symbol=position.symbol,
        side=position.side.value,
        outcome=outcome.value,
        decision_time=_iso(fill.decision_time) if fill else "",
        decision_bar_time=_iso(fill.decision_bar_time) if fill else None,
        signal_time=_iso(fill.signal_time) if fill else "",
        entry_available_time=_iso(fill.entry_available_time) if fill else None,
        entry_bar_time=_iso(fill.entry_bar_time) if fill else None,
        entry_time=_iso(position.entry_time),
        entry_price=position.entry_price,
        entry_reference_price=fill.reference_price if fill else None,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        exit_time=_iso(position.exit_time),
        exit_price=position.exit_price,
        exit_reason=position.exit_reason,
        was_ambiguous_exit=position.was_ambiguous_exit,
        quantity=position.volume,
        price_risk=price_risk,
        gross_pnl=gross_pnl,
        commission=commission,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
        risk_amount=risk_amount,
        r_multiple=r_multiple,
        bars_held=position.bars_held,
        regime=str(position.metadata.get("regime", "")),
        setup_type=str(position.metadata.get("setup_type", "")),
        entry_method=str(position.metadata.get("entry_method", "")),
        confidence=float(position.metadata.get("confidence", 0.0) or 0.0),
        metadata=dict(position.metadata),
    )


class TradeLedger:
    """Collects simulated trades and rejected signals for a run.

    Writes to ``backtest_results/``, never to ``trade_states/``. Simulated
    results must stay separate from production trade history.
    """

    __slots__ = ("_trades", "_rejections")

    def __init__(self) -> None:
        self._trades: list[SimulatedTrade] = []
        self._rejections: list[dict] = []

    def record(self, trade: SimulatedTrade) -> None:
        """Append a completed trade.

        Args:
            trade: The trade to record.
        """
        self._trades.append(trade)

    def record_rejection(
        self,
        *,
        decision_time: datetime,
        side: str,
        outcome: TradeOutcome,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        """Record a signal that never became a position.

        Kept because the ratio of signals to fills is itself a measurement: a
        strategy whose signals are mostly rejected behaves very differently from
        one whose signals mostly trade.

        Args:
            decision_time: When the signal was generated.
            side: Intended direction.
            outcome: Why no position resulted.
            reason: Human-readable explanation.
            metadata: Strategy context.
        """
        self._rejections.append(
            {
                "decision_time": decision_time.isoformat(),
                "side": side,
                "outcome": outcome.value,
                "reason": reason,
                "metadata": dict(metadata or {}),
            }
        )

    @property
    def trades(self) -> list[SimulatedTrade]:
        """All recorded trades."""
        return list(self._trades)

    @property
    def rejections(self) -> list[dict]:
        """All recorded rejections."""
        return list(self._rejections)

    def completed_trades(self) -> list[SimulatedTrade]:
        """Trades the strategy actually finished, excluding ``END_OF_DATA``."""
        return [t for t in self._trades if t.outcome_enum.is_completed_trade]

    def write_jsonl(self, path: Path | str) -> Path:
        """Write the ledger as newline-delimited JSON.

        Args:
            path: Destination file. Parent directories are created.

        Returns:
            The path written to.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for trade in self._trades:
                handle.write(json.dumps(trade.to_dict(), sort_keys=True, default=str) + "\n")
        return target

    def fingerprint(self) -> str:
        """Return a stable hash of the ledger contents.

        Used by the determinism tests: two runs over identical data must produce
        an identical fingerprint.

        Returns:
            A hex SHA-256 digest.
        """
        import hashlib

        payload = json.dumps(
            [t.to_dict() for t in self._trades], sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Phase 4B: one canonical position, several executions, one aggregate record
# ---------------------------------------------------------------------------
#
# A canonical position closes in more than one execution: half at 1R, the
# remainder at the target or the stop. :class:`SimulatedTrade` carries exactly
# one ``exit_price``/``exit_time``/``exit_reason``, so it cannot hold that
# history. The types below add the representation settled in
# ``docs/PHASE_4B_PARTIAL_EXIT_REPRESENTATION_DECISION.md``: one
# :class:`TradeRecord` per position -- so a partial is never a second trade --
# holding an immutable :class:`TradeExecution` per execution.
#
# Nothing here is wired. :class:`SimulatedTrade`, :func:`trade_from_position`
# and :class:`TradeLedger` are untouched, so every existing ledger fingerprint
# is unchanged by this phase. :meth:`TradeRecord.to_simulated_trade` is the
# compatibility projection for the consumers that count trades today.


@dataclass(frozen=True, slots=True)
class TradeExecution:
    """One execution against a position, with its economics.

    Built from an :class:`~execution.trade_identity.FillRecord`, which carries
    the identity, and priced here. Immutable: an execution is a fact about the
    past.

    Attributes:
        fill_id: The key this execution is recorded under (spec 16.3).
        position_id: The canonical position it belongs to.
        operation_id: The instruction it answers.
        broker_order_id: The broker's order identifier, where one exists.
        broker_deal_id: The broker's execution identifier, where one exists.
        time: When it executed, ISO-8601.
        side: Direction of the position, as a string.
        kind: ``ENTRY``, ``PARTIAL_EXIT`` or ``FINAL_EXIT``.
        cause: Why it happened -- ``M1R``, ``STOP``, ``TARGET`` and so on.
        quantity_steps: Size in broker volume steps, the authoritative unit.
        quantity: The same size in lots, for the broker boundary and reporting.
        price: The price actually executed at.
        gross_pnl: Realised P&L for this execution alone, before commission.
            Zero for an entry, which realises nothing.
        commission: This execution's share of the round turn.
        slippage_cost: Modelled slippage, for reporting. Zero unless supplied,
            as in :func:`trade_from_position`, because slippage is already
            inside the executed price.
        was_ambiguous: Whether the bar that produced it contained both stop and
            target, so policy rather than evidence decided the outcome.
    """

    fill_id: str
    position_id: str
    operation_id: str
    broker_order_id: str | None
    broker_deal_id: str | None
    time: str
    side: str
    kind: str
    cause: str
    quantity_steps: int
    quantity: float
    price: float
    gross_pnl: float
    commission: float
    slippage_cost: float
    was_ambiguous: bool

    @property
    def net_pnl(self) -> float:
        """This execution's P&L after its share of commission."""
        return self.gross_pnl - self.commission

    @property
    def is_exit(self) -> bool:
        """Whether this execution reduced the position."""
        return self.kind != FillKind.ENTRY.value

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One canonical position, from entry to confirmed closure. **One trade.**

    A partial exit is an execution, never a second trade, so ``len(records)``
    keeps the meaning ``total_trades`` has today.

    Risk is stated from the **original** stop. Deriving it from the current
    stop would collapse to zero once the stop is promoted to breakeven, and
    ``r_multiple`` would become ``None`` for every position that reached 1R --
    the defect recorded in the identity investigation. ``original_stop_price``
    and ``final_stop_price`` are therefore separate fields.

    Attributes:
        trade_id: Equal to ``position_id``. Kept for readers expecting the name.
        position_id: The canonical position identity.
        symbol: Instrument.
        side: Direction, as a string.
        outcome: How the position ended.
        decision_time: Replay instant the strategy ran at.
        decision_bar_time: Open time of the newest bar that decision saw.
        signal_time: When the signal was emitted.
        entry_available_time: Open time of the earliest fillable bar.
        entry_bar_time: Open time of the bar actually filled against.
        entry_time: Alias of ``entry_bar_time``, for the conventional name.
        entry_price: The actual fill price. R and the levels derive from it.
        entry_reference_price: Raw bar price before cost adjustment.
        original_stop_price: The stop at entry. **Immutable.**
        final_stop_price: Where the stop stood at closure, if it moved.
        take_profit: Target price, if any.
        original_quantity_steps: Size at entry, in volume steps.
        original_quantity: The same size in lots.
        exit_time: The **final** execution's time.
        exit_price: The **final** execution's price.
        exit_reason: The final execution's cause.
        was_ambiguous_exit: Whether **any** exit was resolved by policy.
        price_risk: ``abs(entry_price - original_stop_price)`` -- R, in price
            units.
        risk_amount: Money at risk at 1R on the original quantity.
        gross_pnl: Sum of every execution's gross P&L.
        commission: Sum of every execution's commission.
        slippage_cost: Sum of every execution's modelled slippage.
        net_pnl: ``gross_pnl - commission``, as elsewhere in this module.
        r_multiple: ``net_pnl / risk_amount``, computed once at closure.
        bars_held: Bars the position was open for. Position-level: a partial
            does not end the position, so it is not counted twice.
        executions: Every execution, in recording order.
        regime: Regime the strategy reported at decision time.
        setup_type: Setup label the strategy reported.
        entry_method: Entry style the strategy reported.
        confidence: Confidence score the strategy reported.
        metadata: Any further strategy context.
    """

    trade_id: str
    position_id: str
    symbol: str
    side: str
    outcome: str

    decision_time: str
    decision_bar_time: str | None
    signal_time: str
    entry_available_time: str | None
    entry_bar_time: str | None
    entry_time: str | None
    entry_price: float
    entry_reference_price: float | None

    original_stop_price: float
    final_stop_price: float | None
    take_profit: float | None

    original_quantity_steps: int
    original_quantity: float

    exit_time: str | None
    exit_price: float | None
    exit_reason: str
    was_ambiguous_exit: bool

    price_risk: float
    risk_amount: float | None
    gross_pnl: float
    commission: float
    slippage_cost: float
    net_pnl: float
    r_multiple: float | None
    bars_held: int

    executions: tuple[TradeExecution, ...] = ()

    regime: str = ""
    setup_type: str = ""
    entry_method: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def outcome_enum(self) -> TradeOutcome:
        """The outcome as an enum."""
        return TradeOutcome(self.outcome)

    @property
    def is_win(self) -> bool:
        """Whether the position finished with positive net P&L."""
        return self.outcome_enum.is_completed_trade and self.net_pnl > 0.0

    @property
    def is_loss(self) -> bool:
        """Whether the position finished with negative net P&L."""
        return self.outcome_enum.is_completed_trade and self.net_pnl < 0.0

    @property
    def exit_executions(self) -> tuple[TradeExecution, ...]:
        """Only the executions that reduced the position."""
        return tuple(execution for execution in self.executions if execution.is_exit)

    @property
    def closed_quantity_steps(self) -> int:
        """Total quantity closed, summed from the executions themselves."""
        return sum(execution.quantity_steps for execution in self.exit_executions)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation.

        ``executions`` nests as a list of objects. JSON and JSONL hold that
        directly; a flat CSV cannot, and would stringify the column -- the
        known limitation recorded in the partial-exit decision.
        """
        return asdict(self)

    def to_simulated_trade(self) -> SimulatedTrade:
        """Project onto the flat record existing consumers read.

        The projection is lossy by construction: it keeps the **final**
        execution's price, time and reason, and the aggregate economics, but
        not the individual executions. It exists so that consumers which count
        trades and aggregate P&L keep working unchanged -- one position still
        yields exactly one row.

        ``stop_loss`` carries the **original** stop, so that
        ``price_risk == abs(entry_price - stop_loss)`` stays true for a reader
        checking the row. Where the stop moved, ``final_stop_price`` on this
        record holds where it ended.
        """
        return SimulatedTrade(
            trade_id=self.trade_id,
            symbol=self.symbol,
            side=self.side,
            outcome=self.outcome,
            decision_time=self.decision_time,
            decision_bar_time=self.decision_bar_time,
            signal_time=self.signal_time,
            entry_available_time=self.entry_available_time,
            entry_bar_time=self.entry_bar_time,
            entry_time=self.entry_time,
            entry_price=self.entry_price,
            entry_reference_price=self.entry_reference_price,
            stop_loss=self.original_stop_price,
            take_profit=self.take_profit,
            exit_time=self.exit_time,
            exit_price=self.exit_price,
            exit_reason=self.exit_reason,
            was_ambiguous_exit=self.was_ambiguous_exit,
            quantity=self.original_quantity,
            price_risk=self.price_risk,
            gross_pnl=self.gross_pnl,
            commission=self.commission,
            slippage_cost=self.slippage_cost,
            net_pnl=self.net_pnl,
            risk_amount=self.risk_amount,
            r_multiple=self.r_multiple,
            bars_held=self.bars_held,
            regime=self.regime,
            setup_type=self.setup_type,
            entry_method=self.entry_method,
            confidence=self.confidence,
            metadata=dict(self.metadata),
        )


def trade_record_from_fills(
    *,
    position_id: str,
    symbol: str,
    side: Side,
    outcome: TradeOutcome,
    entry_price: float,
    original_stop_price: float,
    original_quantity_steps: int,
    executions: Sequence[FillRecord],
    spec: SymbolSpecification,
    take_profit: float | None = None,
    final_stop_price: float | None = None,
    bars_held: int = 0,
    commission_per_lot: float = 0.0,
    slippage_cost_per_lot: float = 0.0,
    ambiguous_fill_ids: Iterable[str] = (),
    fill: SimulatedFill | None = None,
    metadata: dict | None = None,
) -> TradeRecord:
    """Build the aggregate record for one closed canonical position.

    Every money figure is derived from the executions themselves, never from an
    average price: each carries the price it actually executed at.

    P&L uses the same primitive as :func:`trade_from_position` --
    ``money_per_price_unit`` from the broker's own tick value -- and the same
    convention, ``net = gross - commission``, with ``slippage_cost`` reported
    rather than subtracted. Commission is charged per exit execution on that
    execution's volume, so the total is one round turn on the original
    quantity, exactly as charging once on the full volume gives today.

    Risk comes from ``original_stop_price``. It is a required argument rather
    than something read off a position, because reading a mutable stop is the
    defect this representation exists to prevent.

    Args:
        position_id: Canonical position identity.
        symbol: Instrument.
        side: Direction.
        outcome: How the position ended.
        entry_price: The actual fill price.
        original_stop_price: The stop at entry. Never the promoted stop.
        original_quantity_steps: Size at entry, in volume steps.
        executions: Every execution, in recording order. At least one exit.
        spec: Broker specification supplying monetary conversion and the volume
            step.
        take_profit: Target price, if any.
        final_stop_price: Where the stop stood at closure, if it moved.
        bars_held: Bars the position was open for.
        commission_per_lot: Round-turn commission per lot.
        slippage_cost_per_lot: Modelled slippage per lot, for reporting.
        ambiguous_fill_ids: Executions whose bar was resolved by policy.
        fill: The originating entry fill, for timing provenance.
        metadata: Strategy context captured at decision time.

    Returns:
        A :class:`TradeRecord`.

    Raises:
        ValueError: If no exit execution is supplied, an execution names a
            different position, the executions are out of time order, there is
            more than one entry, or the closed quantity exceeds the original.
    """
    if not executions:
        raise ValueError(f"position {position_id} has no executions")

    foreign = {execution.position_id for execution in executions} - {position_id}
    if foreign:
        raise ValueError(
            f"executions name other positions: {sorted(foreign)}; an execution "
            "belongs to exactly one position"
        )

    times = [execution.time for execution in executions]
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise ValueError(
            f"executions for {position_id} are out of time order; they are "
            "recorded in the order they happened"
        )

    entries = [e for e in executions if e.kind is FillKind.ENTRY]
    if len(entries) > 1:
        raise ValueError(
            f"position {position_id} has {len(entries)} entry executions; a "
            "canonical position has one entry"
        )
    if entries and entries[0].quantity_steps != original_quantity_steps:
        raise ValueError(
            f"entry execution is {entries[0].quantity_steps} steps but the "
            f"original quantity is {original_quantity_steps}"
        )

    exits = [e for e in executions if e.kind is not FillKind.ENTRY]
    if not exits:
        raise ValueError(
            f"position {position_id} has no exit execution, so it is not closed"
        )

    closed_steps = sum(e.quantity_steps for e in exits)
    if closed_steps > original_quantity_steps:
        raise ValueError(
            f"executions close {closed_steps} steps but only "
            f"{original_quantity_steps} were opened"
        )

    ambiguous = set(ambiguous_fill_ids)
    step = spec.volume_step
    priced: list[TradeExecution] = []
    for execution in executions:
        lots = round(execution.quantity_steps * step, 8)
        is_exit = execution.kind is not FillKind.ENTRY
        gross = (
            (execution.price - entry_price) * side.sign * spec.money_per_price_unit(lots)
            if is_exit
            else 0.0
        )
        priced.append(
            TradeExecution(
                fill_id=execution.fill_id,
                position_id=execution.position_id,
                operation_id=execution.operation_id,
                broker_order_id=execution.broker_order_id,
                broker_deal_id=execution.identity.broker_deal_id,
                time=execution.time.isoformat(),
                side=side.value,
                kind=execution.kind.value,
                cause=execution.cause,
                quantity_steps=execution.quantity_steps,
                quantity=lots,
                price=execution.price,
                gross_pnl=gross,
                commission=commission_per_lot * lots if is_exit else 0.0,
                slippage_cost=slippage_cost_per_lot * lots if is_exit else 0.0,
                was_ambiguous=execution.fill_id in ambiguous,
            )
        )

    exit_records = tuple(e for e in priced if e.is_exit)
    final = exit_records[-1]

    gross_pnl = sum(e.gross_pnl for e in priced)
    commission = sum(e.commission for e in priced)
    slippage_cost = sum(e.slippage_cost for e in priced)
    net_pnl = gross_pnl - commission

    original_quantity = round(original_quantity_steps * step, 8)
    price_risk = abs(entry_price - original_stop_price)
    risk_amount = spec.money_for_price_distance(price_risk, original_quantity)
    r_multiple = (net_pnl / risk_amount) if risk_amount > 0.0 else None

    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    entry_time = (
        _iso(fill.entry_bar_time)
        if fill is not None
        else (priced[0].time if entries else None)
    )

    return TradeRecord(
        trade_id=position_id,
        position_id=position_id,
        symbol=symbol,
        side=side.value,
        outcome=outcome.value,
        decision_time=_iso(fill.decision_time) if fill else "",
        decision_bar_time=_iso(fill.decision_bar_time) if fill else None,
        signal_time=_iso(fill.signal_time) if fill else "",
        entry_available_time=_iso(fill.entry_available_time) if fill else None,
        entry_bar_time=_iso(fill.entry_bar_time) if fill else None,
        entry_time=entry_time,
        entry_price=entry_price,
        entry_reference_price=fill.reference_price if fill else None,
        original_stop_price=original_stop_price,
        final_stop_price=final_stop_price,
        take_profit=take_profit,
        original_quantity_steps=original_quantity_steps,
        original_quantity=original_quantity,
        exit_time=final.time,
        exit_price=final.price,
        exit_reason=final.cause,
        was_ambiguous_exit=any(e.was_ambiguous for e in exit_records),
        price_risk=price_risk,
        risk_amount=risk_amount,
        gross_pnl=gross_pnl,
        commission=commission,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        bars_held=bars_held,
        executions=tuple(priced),
        regime=str((metadata or {}).get("regime", "")),
        setup_type=str((metadata or {}).get("setup_type", "")),
        entry_method=str((metadata or {}).get("entry_method", "")),
        confidence=float((metadata or {}).get("confidence", 0.0) or 0.0),
        metadata=dict(metadata or {}),
    )
