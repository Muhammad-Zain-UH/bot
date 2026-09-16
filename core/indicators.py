"""Canonical indicator definitions.

Currently contains one indicator: Average True Range. It is here because the
Phase 1 audit found **four mutually incompatible ATR implementations** feeding
decisions that are compared against each other:

=================================================  ===================================================
Call site                                          Definition
=================================================  ===================================================
``indicators.calculate_indicators``                ``pandas_ta.atr`` -- true Wilder ATR
``pullback_detector._estimate_recent_atr``         correct true range, but **SMA-14**, not Wilder
``sweep_detector._estimate_m15_atr``               ``close.diff().abs().rolling(14).mean()`` --
                                                   **ignores high/low entirely**; materially understates
``main_production.analyze_entry`` (``h1_atr``)     ``mean(high - low)`` over 14 bars -- **ignores gaps**
=================================================  ===================================================

Three of the four are not ATR. The close-to-close variant in ``sweep_detector``
is the most divergent: it cannot see intrabar range at all, so on a wide-range
bar it reports a small value. That understated ATR then sets ``sweep_min`` -- the
minimum wick depth required to call a sweep -- which is one of the system's
busiest rejection gates.

Compounding it, the returned **unit** is undocumented at every site, and the
consuming thresholds (``m5_atr >= 2.5``, ``h1_atr < 8.0``) are written as though
the value were pips when it is in fact quote-currency price. See
:mod:`core.units`.

Canonical definition
--------------------
:func:`atr_wilder` is the one definition new code must use:

* **Input**: a bar frame with ``high``, ``low``, ``close``.
* **Bars**: computed on **closed bars only**; the forming bar repaints and would
  make ATR -- and every threshold derived from it -- repaint with it.
* **True range**: ``max(H-L, |H - C_prev|, |L - C_prev|)``. The first bar has no
  previous close and is therefore excluded, not zero-filled.
* **Smoothing**: Wilder's RMA, seeded with a simple mean of the first ``period``
  true ranges, then ``ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period``. This
  matches MetaTrader's own ATR.
* **Returned unit**: :class:`~core.units.PriceDistance` -- quote-currency price,
  never pips. Convert with :meth:`AtrResult.to_pips` when pips are wanted.
* **Insufficient bars**: raises :class:`~core.candles.InsufficientBarsError`.
  It never returns a silent default such as the ``15.0`` and ``10.0`` fallbacks
  in the existing code, which fabricate a volatility reading out of nothing.

Implemented in plain pandas/numpy rather than via ``pandas_ta`` so results are
deterministic and independent of that package's version (the installed build is
a beta, ``0.4.71b0``).

Phase 0/1 scope
---------------
The four implementations above are **not** migrated onto this function. Doing so
would change strategy behaviour -- switching ``sweep_detector`` from
close-to-close to true Wilder ATR would immediately alter ``sweep_min`` and the
rate at which sweeps are detected. That is a Phase 2/4 change requiring a
measured baseline. Catalogued in ``PHASE_2_ISSUES.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pandas as pd

from core.candles import HLC_COLUMNS, BarConvention, InsufficientBarsError, closed_bars
from core.units import PriceDistance

if TYPE_CHECKING:
    from core.symbols import SymbolSpecification
    from core.units import Pips

__all__ = [
    "ATR_METHOD_WILDER_RMA",
    "AtrResult",
    "DEFAULT_ATR_PERIOD",
    "atr_wilder",
    "true_range",
]

DEFAULT_ATR_PERIOD: Final[int] = 14
"""Standard ATR period.

Matches the period already used everywhere in the existing code. Phase 1 does
not tune indicator periods; this constant exists to name the value, not to
change it.
"""

ATR_METHOD_WILDER_RMA: Final[str] = "wilder_rma"
"""Identifier for the smoothing method, recorded on every :class:`AtrResult`."""


@dataclass(frozen=True, slots=True)
class AtrResult:
    """An ATR reading together with the provenance needed to trust it.

    Carrying ``period``, ``bars_used`` and ``method`` alongside the value makes
    two ATR readings comparable. The existing code passes bare floats, which is
    how four different definitions came to be compared against one another.

    Attributes:
        value: The ATR, as a quote-currency :class:`~core.units.PriceDistance`.
        period: Smoothing period used.
        bars_used: Number of closed bars that contributed.
        method: Smoothing method identifier, always
            :data:`ATR_METHOD_WILDER_RMA` for now.
    """

    value: PriceDistance
    period: int
    bars_used: int
    method: str = ATR_METHOD_WILDER_RMA

    def to_pips(self, spec: SymbolSpecification) -> Pips:
        """Return the ATR expressed in pips.

        Args:
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The ATR in pips.
        """
        return self.value.to_pips(spec)

    def __repr__(self) -> str:
        return (
            f"AtrResult(value={self.value.value:.6g} price, period={self.period}, "
            f"bars_used={self.bars_used}, method={self.method!r})"
        )


def true_range(
    bars: pd.DataFrame,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
) -> pd.Series:
    """Compute the true range series for ``bars``.

    ``TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)``

    The first bar has no previous close, so its true range is undefined and is
    **dropped** rather than approximated by ``H - L``. Approximating it biases
    the ATR seed on short frames.

    Args:
        bars: Bar frame with ``high``, ``low`` and ``close``.
        convention: The frame's bar convention. The forming bar is excluded.

    Returns:
        True range values indexed as in the input, with the first bar removed.
        Length is ``len(closed_bars) - 1``.

    Raises:
        InsufficientBarsError: If fewer than two closed bars are available.
    """
    frame = closed_bars(bars, convention, required_columns=HLC_COLUMNS)
    if len(frame) < 2:
        raise InsufficientBarsError(
            f"true range needs at least 2 closed bars, got {len(frame)}"
        )

    high = frame["high"].astype("float64")
    low = frame["low"].astype("float64")
    previous_close = frame["close"].astype("float64").shift(1)

    candidates = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    # skipna=False is essential. With pandas' default (skipna=True), a NaN in
    # `high` would simply be ignored and the true range would be computed from
    # the remaining candidates -- yielding a plausible-looking number derived
    # from incomplete data. Propagating the NaN instead lets `atr_wilder` drop
    # the bar and raise if too few usable ranges remain, so bad input surfaces
    # as an error rather than as a quietly wrong volatility reading.
    return candidates.max(axis=1, skipna=False).iloc[1:]


def atr_wilder(
    bars: pd.DataFrame,
    period: int = DEFAULT_ATR_PERIOD,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
) -> AtrResult:
    """Compute Wilder's Average True Range on closed bars.

    See the module docstring for the full definition and rationale.

    Args:
        bars: Bar frame with ``high``, ``low`` and ``close``.
        period: Smoothing period. Must be >= 1.
        convention: The frame's bar convention. The forming bar is excluded so
            the result does not repaint.

    Returns:
        An :class:`AtrResult` whose ``value`` is in quote-currency price units.

    Raises:
        ValueError: If ``period`` is less than 1.
        InsufficientBarsError: If fewer than ``period + 1`` closed bars are
            available, or if the data yields no usable true ranges.

    Example:
        >>> import pandas as pd
        >>> frame = pd.DataFrame({
        ...     "high":  [10.0, 11.0, 12.0],
        ...     "low":   [ 9.0, 10.0, 11.0],
        ...     "close": [ 9.5, 10.5, 11.5],
        ... })
        >>> atr_wilder(frame, period=2).value.value
        1.5

        Worked by hand: bar 0 has no previous close so its true range is
        undefined and dropped. ``TR_1 = max(11-10, |11-9.5|, |10-9.5|) = 1.5``
        and ``TR_2 = max(12-11, |12-10.5|, |11-10.5|) = 1.5``. With
        ``period=2`` the seed is ``mean([1.5, 1.5]) = 1.5`` and no smoothing
        steps remain.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    frame = closed_bars(bars, convention, required_columns=HLC_COLUMNS)
    if len(frame) < period + 1:
        raise InsufficientBarsError(
            f"ATR({period}) needs at least {period + 1} closed bars "
            f"(one extra for the initial previous-close), got {len(frame)}"
        )

    ranges = true_range(frame, BarConvention.CLOSED_ONLY).dropna()
    if len(ranges) < period:
        raise InsufficientBarsError(
            f"ATR({period}) needs {period} usable true ranges, got {len(ranges)}; "
            f"the frame likely contains NaN values in high/low/close"
        )

    values = ranges.to_numpy(dtype="float64")

    # Seed with the simple mean of the first `period` true ranges, then apply
    # Wilder's recursive smoothing. Written as an explicit loop for exactness and
    # readability; frames here are hundreds of bars, so this is not hot.
    atr = float(values[:period].mean())
    for true_range_value in values[period:]:
        atr = (atr * (period - 1) + float(true_range_value)) / period

    return AtrResult(
        value=PriceDistance(atr),
        period=period,
        bars_used=len(frame),
        method=ATR_METHOD_WILDER_RMA,
    )
