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

from core.symbols import SymbolSpecification
from core.types import Side
from execution.broker import PositionState, SimulatedPosition

__all__ = [
    "SimulatedTrade",
    "TradeLedger",
    "TradeOutcome",
    "trade_from_position",
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
