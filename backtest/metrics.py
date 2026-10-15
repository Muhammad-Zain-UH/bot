"""Descriptive backtest metrics.

**These are measurements, not judgements.** Nothing here ranks a strategy,
scores it, or projects it forward. There is no "good", "bad", "profitable" or
"expected return" anywhere in this module, and none should be added: a backtest
over a single unvalidated sample cannot support such a claim, and attaching one
to a number is how a descriptive statistic quietly becomes a promise.

Two cautions that the report must always carry
----------------------------------------------
**Currency figures are size-dependent.** Every simulated position is a fixed
0.01 lots because ``risk_manager`` has a known ~10x sizing defect that Phase 2A
must not fix. Monetary P&L is therefore an artefact of that choice.
:attr:`BacktestMetrics.average_r` and :attr:`BacktestMetrics.expectancy_r` are
the size-independent measures.

**Ambiguous exits are counted.** When a bar contained both the stop and the
target, OHLC could not say which came first and a policy decided it. If that
count is a large share of trades, the result rests on the policy rather than on
the data, and :attr:`BacktestMetrics.ambiguous_exit_fraction` makes that visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backtest.ledger import SimulatedTrade, TradeOutcome

__all__ = ["BacktestMetrics", "compute_metrics"]


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Descriptive statistics for one replay run.

    Attributes:
        total_signals: Signals the strategy generated, filled or not.
        total_orders: Orders submitted to the simulator.
        total_trades: Positions that were filled.
        completed_trades: Trades the strategy finished, excluding ``END_OF_DATA``.
        open_at_end: Positions still open when the dataset ended.
        rejected_orders: Orders the simulator declined.
        wins: Completed trades with positive net P&L.
        losses: Completed trades with negative net P&L.
        breakeven: Completed trades with exactly zero net P&L.
        win_rate: ``wins / completed_trades``, or ``None`` when there are none.
        gross_pnl: Sum of gross P&L, account currency, at the fixed size.
        net_pnl: Sum of net P&L, account currency, at the fixed size.
        total_commission: Commission charged across the run.
        average_win: Mean net P&L of winning trades.
        average_loss: Mean net P&L of losing trades (negative).
        expectancy: Mean net P&L per completed trade, account currency.
        expectancy_r: Mean R-multiple per completed trade. **Size-independent.**
        average_r: Alias of ``expectancy_r``, under the conventional name.
        profit_factor: Gross profit / gross loss, or ``None`` when there are no
            losses (the ratio is undefined, not infinite).
        max_drawdown: Largest peak-to-trough decline of the cumulative net P&L.
        max_drawdown_r: The same, measured in R.
        max_consecutive_wins: Longest run of winning trades.
        max_consecutive_losses: Longest run of losing trades.
        average_bars_held: Mean bars held per completed trade.
        ambiguous_exits: Completed trades whose outcome a policy decided.
        ambiguous_exit_fraction: That count as a share of completed trades.
        by_outcome: Counts per :class:`~backtest.ledger.TradeOutcome`.
        by_direction: Counts per side.
        by_regime: Counts per regime reported at decision time.
        by_setup: Counts per setup type reported at decision time.
    """

    total_signals: int = 0
    total_orders: int = 0
    total_trades: int = 0
    completed_trades: int = 0
    open_at_end: int = 0
    rejected_orders: int = 0

    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float | None = None

    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_commission: float = 0.0
    average_win: float | None = None
    average_loss: float | None = None
    expectancy: float | None = None
    expectancy_r: float | None = None
    average_r: float | None = None
    profit_factor: float | None = None

    max_drawdown: float = 0.0
    max_drawdown_r: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    average_bars_held: float | None = None

    ambiguous_exits: int = 0
    ambiguous_exit_fraction: float | None = None

    by_outcome: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, int] = field(default_factory=dict)
    by_regime: dict[str, int] = field(default_factory=dict)
    by_setup: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        from dataclasses import asdict

        return asdict(self)


def _max_drawdown(series: list[float]) -> float:
    """Return the largest peak-to-trough decline of a cumulative series.

    Args:
        series: Cumulative values in chronological order.

    Returns:
        The drawdown as a non-negative magnitude; ``0.0`` if never below a peak.
    """
    peak = 0.0
    worst = 0.0
    running = 0.0
    for value in series:
        running += value
        peak = max(peak, running)
        worst = max(worst, peak - running)
    return worst


def _longest_run(flags: list[bool]) -> int:
    """Return the longest consecutive run of ``True``.

    Args:
        flags: Chronological sequence.

    Returns:
        Length of the longest run.
    """
    longest = 0
    current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def compute_metrics(
    trades: list[SimulatedTrade],
    total_signals: int = 0,
    rejected_orders: int = 0,
) -> BacktestMetrics:
    """Compute descriptive statistics for a set of simulated trades.

    Args:
        trades: All recorded trades, including any left open at end of data.
        total_signals: Signals generated during the run, filled or not.
        rejected_orders: Orders the simulator declined.

    Returns:
        A :class:`BacktestMetrics`. An empty input yields a zeroed result with
        ``None`` for every ratio -- never a division by zero and never a
        fabricated ``0.0`` win rate, which would read as "lost every trade".
    """
    completed = [t for t in trades if t.outcome_enum.is_completed_trade]
    open_at_end = sum(1 for t in trades if t.outcome_enum is TradeOutcome.END_OF_DATA)

    by_outcome: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    by_regime: dict[str, int] = {}
    by_setup: dict[str, int] = {}
    for trade in trades:
        by_outcome[trade.outcome] = by_outcome.get(trade.outcome, 0) + 1
        by_direction[trade.side] = by_direction.get(trade.side, 0) + 1
        if trade.regime:
            by_regime[trade.regime] = by_regime.get(trade.regime, 0) + 1
        if trade.setup_type:
            by_setup[trade.setup_type] = by_setup.get(trade.setup_type, 0) + 1

    base = BacktestMetrics(
        total_signals=total_signals,
        total_orders=len(trades) + rejected_orders,
        total_trades=len(trades),
        completed_trades=len(completed),
        open_at_end=open_at_end,
        rejected_orders=rejected_orders,
        by_outcome=by_outcome,
        by_direction=by_direction,
        by_regime=by_regime,
        by_setup=by_setup,
    )

    if not completed:
        return base

    wins = [t for t in completed if t.net_pnl > 0.0]
    losses = [t for t in completed if t.net_pnl < 0.0]
    breakeven = [t for t in completed if t.net_pnl == 0.0]

    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))

    r_values = [t.r_multiple for t in completed if t.r_multiple is not None]
    pnl_series = [t.net_pnl for t in completed]
    r_series = [t.r_multiple for t in completed if t.r_multiple is not None]

    ambiguous = sum(1 for t in completed if t.was_ambiguous_exit)

    return BacktestMetrics(
        total_signals=total_signals,
        total_orders=len(trades) + rejected_orders,
        total_trades=len(trades),
        completed_trades=len(completed),
        open_at_end=open_at_end,
        rejected_orders=rejected_orders,
        wins=len(wins),
        losses=len(losses),
        breakeven=len(breakeven),
        win_rate=len(wins) / len(completed),
        gross_pnl=sum(t.gross_pnl for t in completed),
        net_pnl=sum(t.net_pnl for t in completed),
        total_commission=sum(t.commission for t in completed),
        average_win=(gross_profit / len(wins)) if wins else None,
        average_loss=(sum(t.net_pnl for t in losses) / len(losses)) if losses else None,
        expectancy=sum(pnl_series) / len(completed),
        expectancy_r=(sum(r_values) / len(r_values)) if r_values else None,
        average_r=(sum(r_values) / len(r_values)) if r_values else None,
        # Undefined rather than infinite when there are no losses: a run with no
        # losing trade has no meaningful ratio, and reporting `inf` invites
        # exactly the over-reading this module avoids.
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0.0 else None,
        max_drawdown=_max_drawdown(pnl_series),
        max_drawdown_r=_max_drawdown(r_series),
        max_consecutive_wins=_longest_run([t.net_pnl > 0.0 for t in completed]),
        max_consecutive_losses=_longest_run([t.net_pnl < 0.0 for t in completed]),
        average_bars_held=sum(t.bars_held for t in completed) / len(completed),
        ambiguous_exits=ambiguous,
        ambiguous_exit_fraction=ambiguous / len(completed),
        by_outcome=by_outcome,
        by_direction=by_direction,
        by_regime=by_regime,
        by_setup=by_setup,
    )
