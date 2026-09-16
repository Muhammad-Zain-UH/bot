"""Intrabar stop/target resolution policy.

The ambiguity
-------------
A single bar can satisfy both conditions at once::

    low  <= stop_loss      and      high >= take_profit

From OHLC alone it is **impossible** to know which level was touched first. The
bar records four numbers; the path between them is discarded. Only tick data can
resolve it, and this repository has tick data for one month (May 2026) out of a
2004-2026 history.

Why the baseline is CONSERVATIVE
--------------------------------
:attr:`IntrabarPolicy.CONSERVATIVE` assumes the **stop** was hit first.

This was chosen **before any result was produced**, on the principle that an
ambiguous bar must not be resolved in the strategy's favour. It is the
pessimistic assumption by construction: it can only reduce measured performance,
never inflate it. It was **not** selected because it produces better numbers --
it produces worse ones, deliberately.

The alternative policies exist for sensitivity analysis, so the fragility of a
result can be quantified. Switching the baseline policy to improve a headline
figure would be curve-fitting the *simulator* rather than the strategy, which is
worse than curve-fitting the strategy because it is harder to detect.

Every ambiguous bar is counted and surfaced in the metrics. If ambiguous
resolutions drive a large share of outcomes, the result is fragile and the
report must say so rather than quoting a single number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.types import Side

__all__ = ["IntrabarPolicy", "IntrabarResolution", "resolve_intrabar"]


class IntrabarPolicy(Enum):
    """How to resolve a bar that contains both the stop and the target.

    Attributes:
        CONSERVATIVE: Assume the stop was hit first. **The Phase 2A baseline.**
        OPTIMISTIC: Assume the target was hit first. Sensitivity analysis only;
            must never be used to produce a headline result.
        MIDPOINT_HEURISTIC: Infer from the bar's direction -- a bar that closed
            up is assumed to have traded down to its low first, and vice versa.
            A heuristic, not evidence.
        TICK_DATA: Resolve from real ticks. Requires tick data for the period;
            raises if unavailable rather than silently falling back, because a
            silent fallback would misrepresent the method used.
    """

    CONSERVATIVE = "conservative"
    OPTIMISTIC = "optimistic"
    MIDPOINT_HEURISTIC = "midpoint_heuristic"
    TICK_DATA = "tick_data"


@dataclass(frozen=True, slots=True)
class IntrabarResolution:
    """Outcome of resolving one bar against a position's exit levels.

    Attributes:
        hit_stop: Whether the stop was triggered.
        hit_target: Whether the target was triggered.
        was_ambiguous: Whether both levels fell inside the bar, meaning the
            outcome was decided by policy rather than by evidence.
        policy: The policy that decided it.
        reason: Human-readable explanation for the ledger.
    """

    hit_stop: bool
    hit_target: bool
    was_ambiguous: bool
    policy: IntrabarPolicy
    reason: str


def resolve_intrabar(
    *,
    side: Side,
    bar_high: float,
    bar_low: float,
    bar_open: float,
    bar_close: float,
    stop_loss: float,
    take_profit: float | None,
    policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
) -> IntrabarResolution:
    """Decide whether a bar triggered the stop, the target, or neither.

    Args:
        side: Position direction.
        bar_high: Bar high.
        bar_low: Bar low.
        bar_open: Bar open.
        bar_close: Bar close.
        stop_loss: Stop price.
        take_profit: Target price, or ``None`` if the position has no target.
        policy: Resolution policy for ambiguous bars.

    Returns:
        An :class:`IntrabarResolution`.

    Raises:
        NotImplementedError: If :attr:`IntrabarPolicy.TICK_DATA` is requested.
            Tick-level resolution is not implemented in Phase 2A; raising keeps
            the reported method honest instead of quietly using OHLC.
    """
    if policy is IntrabarPolicy.TICK_DATA:
        raise NotImplementedError(
            "TICK_DATA intrabar resolution is not implemented in Phase 2A. "
            "Tick history covers only 2026-05 in this environment, so it cannot "
            "resolve a general backtest. Falling back silently would misreport "
            "the method used."
        )

    if side is Side.BUY:
        stop_touched = bar_low <= stop_loss
        target_touched = take_profit is not None and bar_high >= take_profit
    else:
        stop_touched = bar_high >= stop_loss
        target_touched = take_profit is not None and bar_low <= take_profit

    if not stop_touched and not target_touched:
        return IntrabarResolution(
            hit_stop=False,
            hit_target=False,
            was_ambiguous=False,
            policy=policy,
            reason="bar touched neither level",
        )

    if stop_touched != target_touched:
        which = "stop" if stop_touched else "target"
        return IntrabarResolution(
            hit_stop=stop_touched,
            hit_target=target_touched,
            was_ambiguous=False,
            policy=policy,
            reason=f"bar touched only the {which}",
        )

    # Both touched: OHLC cannot say which came first.
    if policy is IntrabarPolicy.CONSERVATIVE:
        return IntrabarResolution(
            hit_stop=True,
            hit_target=False,
            was_ambiguous=True,
            policy=policy,
            reason=(
                "AMBIGUOUS: bar contained both stop and target; "
                "conservative policy resolved to STOP"
            ),
        )

    if policy is IntrabarPolicy.OPTIMISTIC:
        return IntrabarResolution(
            hit_stop=False,
            hit_target=True,
            was_ambiguous=True,
            policy=policy,
            reason=(
                "AMBIGUOUS: bar contained both stop and target; "
                "optimistic policy resolved to TARGET"
            ),
        )

    # MIDPOINT_HEURISTIC: a bar that closed above its open is assumed to have
    # traded down to its low before rallying, and vice versa.
    closed_up = bar_close >= bar_open
    if side is Side.BUY:
        stop_first = closed_up  # low reached first on an up-closing bar
    else:
        stop_first = not closed_up  # high reached first on a down-closing bar
    return IntrabarResolution(
        hit_stop=stop_first,
        hit_target=not stop_first,
        was_ambiguous=True,
        policy=policy,
        reason=(
            f"AMBIGUOUS: bar contained both levels; midpoint heuristic "
            f"(bar closed {'up' if closed_up else 'down'}) resolved to "
            f"{'STOP' if stop_first else 'TARGET'}"
        ),
    )
