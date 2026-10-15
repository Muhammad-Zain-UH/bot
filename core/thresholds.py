"""Price-relative thresholds, so a constant stops meaning different things.

Why this module exists
----------------------
``core/units.py`` fixed one half of the problem: a bare number is never a
*distance*, so ``Pips(3.0)`` and ``PriceDistance(3.0)`` can no longer be
confused. This fixes the other half: a number that is correctly a distance can
still be **absolute**, and an absolute distance is not a fixed rule on an
instrument whose price quadruples.

Measured on the frozen export (``research/UNIT_MIGRATION_EVIDENCE.md``), the L2
volatility floor ``h1_atr < 8.0`` admitted:

    2017  (gold ~$1,258)    0.00% of bars
    2018  (gold ~$1,269)    0.00% of bars
    2026  (gold ~$4,550)  100.00% of bars

Same code, opposite behaviour, purely because gold went from $951 to $4,173. The
gate was not a volatility filter; it was a proxy for whether gold had got
expensive. Every threshold listed in ``PHASE_2_ISSUES.md`` section 1 has this
property, and correcting the ten-fold unit error does **not** fix it.

What this does, and what it does not
------------------------------------
:func:`at_price` converts a threshold expressed in dollars *at the reference
price* into the equivalent threshold at the price actually prevailing. The
threshold is numerically **unchanged at the reference** and scales from there.

It does **not** make the choice parameter-free, and this module does not pretend
otherwise. :data:`REFERENCE_PRICE` is a declared constant, and a different one
would give a different selectivity -- for the L2 floor, anchoring at the H1
median gives 0.5181% of price and anchoring at the M5 median would give 0.1916%.
What the conversion removes is the **price-level dependence**, which is the
defect. On the L2 floor the best-to-worst-year spread falls from **100.0
percentage points to 30.1**.

See ``research/unit_migration_spec.md``, which fixes this rule in writing before
the migration that uses it, including the correction recording that the anchor is
a declared choice rather than a derived quantity.

Design notes
------------
Pure arithmetic: no I/O, no pandas, no instrument lookup. Relative thresholds do
not need a ``SymbolSpecification`` because a ratio of two prices carries no
instrument economics -- unlike a pip conversion, which does and must go through
``core.units``. The two are therefore composable and kept separate.
"""

from __future__ import annotations

import math
from typing import Final

__all__ = [
    "REFERENCE_PRICE",
    "ThresholdError",
    "as_fraction",
    "at_price",
    "describe",
]

REFERENCE_PRICE: Final[float] = 1544.08
"""The declared anchor: the median XAUUSD H1 close of the frozen export.

100,001 H1 bars, 2009-08-31 to 2026-10-01, from
``data/research_v1/bars/XAUUSD_H1.csv``.

H1 is used for every site regardless of the timeframe the threshold is applied
on, so that the choice of timeframe cannot change a threshold. H1 is this
programme's reference series -- ``research/research_split_manifest_h1.json``
defines TRAIN, DEV and FINAL_OOS on it -- and it is the deepest series with full
bar coverage.

**This is a declared choice, not a derived quantity.** It was fixed before any
outcome was measured. The timeframes span different eras and so have very
different medians (M15 $2,457 over 2022-2026; M5 $4,175 over 2025-2026), and
anchoring elsewhere would change every threshold's selectivity. Do not change
it to adjust a result.
"""


class ThresholdError(ValueError):
    """Raised when a threshold or price cannot describe a real quantity.

    An error rather than a clamp. A silently corrected threshold is how the
    defects this module exists to fix went unnoticed for so long.
    """


def _check(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThresholdError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise ThresholdError(f"{name} must be finite, got {value!r}")
    return value


def as_fraction(threshold_at_reference: float) -> float:
    """The threshold as a fraction of price.

    Args:
        threshold_at_reference: The threshold in quote currency, as it should be
            **at** :data:`REFERENCE_PRICE`.

    Returns:
        The equivalent fraction of price.

    Raises:
        ThresholdError: If the threshold is not a finite, non-negative number.

    Example:
        >>> round(as_fraction(8.0), 8)
        0.00518108
    """
    threshold = _check(threshold_at_reference, "threshold_at_reference")
    if threshold < 0.0:
        raise ThresholdError(f"threshold must be >= 0, got {threshold}")
    return threshold / REFERENCE_PRICE


def at_price(threshold_at_reference: float, price: float) -> float:
    """Scale a reference-price threshold to the price actually prevailing.

    Args:
        threshold_at_reference: The threshold in quote currency at
            :data:`REFERENCE_PRICE`.
        price: The price now. Must be positive -- a non-positive price cannot
            scale anything, and defaulting it would reintroduce exactly the
            silent-fallback behaviour this module exists to remove.

    Returns:
        The equivalent threshold in quote currency at ``price``.

    Raises:
        ThresholdError: If either argument is not finite, the threshold is
            negative, or the price is not positive.

    Example:
        >>> round(at_price(8.0, 1544.08), 6)   # unchanged at the reference
        8.0
        >>> round(at_price(8.0, 4550.0), 2)    # 2026 gold
        23.57
        >>> round(at_price(8.0, 1260.0), 2)    # 2017 gold
        6.53
    """
    threshold = as_fraction(threshold_at_reference)
    current = _check(price, "price")
    if current <= 0.0:
        raise ThresholdError(
            f"price must be > 0 to scale a threshold, got {current}. A "
            f"defaulted price would silently restore an absolute threshold."
        )
    return threshold * current


def describe(threshold_at_reference: float, price: float) -> str:
    """One-line explanation, for logs that previously stated a bare number."""
    scaled = at_price(threshold_at_reference, price)
    return (
        f"${scaled:.4f} (= ${threshold_at_reference:.4f} at the "
        f"${REFERENCE_PRICE:.2f} reference, "
        f"{100 * as_fraction(threshold_at_reference):.4f}% of ${price:.2f})"
    )
