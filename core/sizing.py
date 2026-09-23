"""Canonical risk-based position sizing.

One implementation, used by every path that needs a quantity. Pure: it takes a
:class:`~core.symbols.SymbolSpecification` and numbers, and returns numbers. It
reads no configuration, touches no broker, and knows nothing about strategies.

The contract
------------
For every mode in :class:`~core.symbols.CalculationMode` the platform's profit
formula is ``(close - open) * contract_size * lots``, so::

    risk_budget    = balance * risk_fraction                 [account currency]
    money_per_lot  = stop_distance * money_per_price_unit(1) [account currency]
    raw_lots       = risk_budget / money_per_lot             [lots]
    lots           = floor_to_step(raw_lots)                 [lots]

``money_per_price_unit`` is the symbol's own conversion and refuses modes whose
economics are not implemented, so an unsupported instrument raises here rather
than being sized by a formula that does not describe it.

Rounding is **down, always**
----------------------------
``raw_lots`` is the largest size whose loss at the stop equals the budget, so
any rounding up spends more than was authorised. Floor is therefore not a
preference but the only direction consistent with the word "budget", and the
tests pin the resulting risk at or below the budget for every case.

A size below ``volume_min`` is **declined, not raised to the minimum**. Raising
it would take more risk than authorised -- quietly, and precisely when the
account is smallest or the stop widest. :class:`SizingDecision` reports
``tradeable=False`` with a reason and ``lots=0.0``; the caller decides what to
do, and cannot mistake it for a size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.symbols import SymbolSpecification

__all__ = [
    "SizingDecision",
    "SizingInputError",
    "lots_for_risk",
]


class SizingInputError(ValueError):
    """Raised when a sizing input cannot describe a real position."""


@dataclass(frozen=True, slots=True)
class SizingDecision:
    """The outcome of one sizing calculation.

    Attributes:
        lots: The size to trade, floored to the volume step. ``0.0`` when
            ``tradeable`` is false -- never a substituted minimum.
        raw_lots: The unrounded size, before the step and the bounds. Kept so a
            caller or test can see how much the normalisation gave up.
        risk_budget: ``balance * risk_fraction``, in account currency.
        money_per_lot: Loss at the stop for ``1.0`` lot, in account currency.
        actual_risk: Loss at the stop for ``lots``, in account currency. Always
            ``<= risk_budget`` when ``tradeable`` is true.
        tradeable: Whether ``lots`` is a size the broker would accept.
        reason: Why a non-tradeable decision was reached; empty otherwise.
    """

    lots: float
    raw_lots: float
    risk_budget: float
    money_per_lot: float
    actual_risk: float
    tradeable: bool
    reason: str = ""


def lots_for_risk(
    spec: SymbolSpecification,
    *,
    balance: float,
    risk_fraction: float,
    stop_distance: float,
) -> SizingDecision:
    """Size a position so its loss at the stop does not exceed the risk budget.

    Args:
        spec: The instrument, which supplies the economics and the volume rules.
        balance: Account balance in the account currency. Must be positive.
        risk_fraction: Fraction of balance to risk, e.g. ``0.01`` for 1 %. Must
            be greater than zero and at most ``1.0``. **A fraction, not a
            percentage** -- ``1.0`` means the whole balance.
        stop_distance: Distance from entry to the original stop, in **price
            units**, not pips or points. Must be positive.

    Returns:
        A :class:`SizingDecision`. Check ``tradeable`` before using ``lots``.

    Raises:
        SizingInputError: If any input cannot describe a real position.
        UnsupportedCalculationModeError: If the symbol's calculation mode has
            no implemented economics.
    """
    if not math.isfinite(balance) or balance <= 0.0:
        raise SizingInputError(f"balance must be finite and > 0, got {balance!r}")
    if not math.isfinite(risk_fraction) or risk_fraction <= 0.0 or risk_fraction > 1.0:
        raise SizingInputError(
            f"risk_fraction must be a fraction in (0, 1], got {risk_fraction!r}. "
            f"A percentage such as 1.0 for 1% is not accepted here -- divide by 100."
        )
    if not math.isfinite(stop_distance) or stop_distance <= 0.0:
        raise SizingInputError(
            f"stop_distance must be finite and > 0 price units, got {stop_distance!r}"
        )

    risk_budget = balance * risk_fraction
    money_per_lot = stop_distance * spec.money_per_price_unit(1.0)
    if money_per_lot <= 0.0:  # pragma: no cover - guarded by the checks above
        raise SizingInputError(
            f"{spec.symbol}: money at risk per lot is {money_per_lot!r}"
        )

    raw_lots = risk_budget / money_per_lot
    lots = spec.round_volume_to_step(raw_lots)

    if lots > spec.volume_max:
        lots = spec.round_volume_to_step(spec.volume_max)

    if lots < spec.volume_min:
        return SizingDecision(
            lots=0.0,
            raw_lots=raw_lots,
            risk_budget=risk_budget,
            money_per_lot=money_per_lot,
            actual_risk=0.0,
            tradeable=False,
            reason=(
                f"{spec.symbol}: risk budget {risk_budget:.2f} over a "
                f"{stop_distance} stop affords {raw_lots:.6f} lots, below the "
                f"{spec.volume_min} minimum. Declined rather than raised, which "
                f"would exceed the budget."
            ),
        )

    return SizingDecision(
        lots=lots,
        raw_lots=raw_lots,
        risk_budget=risk_budget,
        money_per_lot=money_per_lot,
        actual_risk=stop_distance * spec.money_per_price_unit(lots),
        tradeable=True,
    )
