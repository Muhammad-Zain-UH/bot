"""Canonical bar/candle convention.

Why this module exists
----------------------
The Phase 1 audit found four mutually incompatible answers to the question
"which row is the current bar?" inside a single decision pass. Because
``mt5_handler.get_market_data`` already excludes the forming bar
(``closed_only=True`` -> ``start_pos=1``), ``iloc[-1]`` **is** the last closed
bar. Yet the code does all of the following on the same frame:

===========================================================  =====================  ==================
Call site                                                    Row used               Effect
===========================================================  =====================  ==================
``entry_engine.detect_displacement_candle``                  ``iloc[-1]``           correct
``entry_engine.detect_fvg``                                  ``iloc[-3:-1]``        correct
``entry_engine.detect_rejection_candle``                     ``iloc[-2]``           **one bar stale**
``entry_engine.detect_momentum_confirmation``                ``iloc[:-1].tail(3)``  **one bar stale**
``entry_engine._evaluate_pullback_entry`` (entry price)      ``iloc[-2]["close"]``  **one bar stale**
``main_production.analyze_entry`` (``confirmed_m5_close``)   ``iloc[-2]["close"]``  **one bar stale**
``pullback_detector.detect_m15_pullback``                    ``recent.iloc[:-1]``   **double-drop**
===========================================================  =====================  ==================

So a pullback entry is priced off a bar that closed five minutes ago while a
momentum entry is priced off the current one -- on a strategy targeting 15-25
pip moves.

The convention
--------------
**A frame's bar convention is a property of the frame, declared explicitly by
whoever produced it. It is never inferred.**

* :attr:`BarConvention.CLOSED_ONLY` -- every row is a completed bar. This is what
  ``get_market_data(closed_only=True)`` returns, and it is the default everywhere.
  ``last_closed`` is ``iloc[-1]``.
* :attr:`BarConvention.INCLUDES_FORMING` -- the final row is still forming and its
  ``high``/``low``/``close`` will change. ``last_closed`` is ``iloc[-2]``.

Using the forming bar for structure, sweeps or entries causes **repainting**: the
signal changes as the bar develops and disappears after it closes. Using
``iloc[-2]`` on a ``CLOSED_ONLY`` frame causes **staleness**: a full bar of lag
for no benefit. Both are silent. Naming the convention makes them loud.

Phase 0/1 scope
---------------
This module defines and tests the convention. It does **not** rewrite the call
sites above -- that would change strategy behaviour, which this phase forbids.
The violations are catalogued in ``PHASE_2_ISSUES.md``.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Sequence

import pandas as pd

__all__ = [
    "BarConvention",
    "InsufficientBarsError",
    "HLC_COLUMNS",
    "OHLC_COLUMNS",
    "closed_bars",
    "forming_bar",
    "has_ohlc_columns",
    "last_closed_bar",
    "previous_closed_bar",
]

OHLC_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close")
"""Default required columns for a bar frame. ``time``/``tick_volume`` are optional."""

HLC_COLUMNS: Final[tuple[str, ...]] = ("high", "low", "close")
"""Columns required by range-based calculations such as true range and ATR."""


class InsufficientBarsError(ValueError):
    """Raised when a frame has too few bars to satisfy the requested access.

    Raised rather than returning ``None`` so the caller cannot accidentally
    propagate a missing bar into a price comparison, where it would either crash
    far from the cause or be swallowed by a broad ``except``.
    """


class BarConvention(Enum):
    """Declares whether a bar frame's final row is still forming.

    Attributes:
        CLOSED_ONLY: Every row is a completed bar; ``iloc[-1]`` is the last
            closed bar. Produced by ``get_market_data(closed_only=True)``.
        INCLUDES_FORMING: The final row is the live, still-forming bar;
            ``iloc[-2]`` is the last closed bar.
    """

    CLOSED_ONLY = "closed_only"
    INCLUDES_FORMING = "includes_forming"

    @property
    def forming_row_count(self) -> int:
        """Number of trailing rows that are not yet closed (``0`` or ``1``)."""
        return 1 if self is BarConvention.INCLUDES_FORMING else 0


def has_ohlc_columns(
    bars: pd.DataFrame,
    required_columns: Sequence[str] = OHLC_COLUMNS,
) -> bool:
    """Return whether ``bars`` carries every column in ``required_columns``.

    Args:
        bars: Candidate bar frame.
        required_columns: Columns that must be present. Defaults to
            :data:`OHLC_COLUMNS`; pass :data:`HLC_COLUMNS` for range-based
            calculations that do not need ``open``.

    Returns:
        ``True`` if every required column is present.
    """
    return all(column in bars.columns for column in required_columns)


def _validate(
    bars: pd.DataFrame,
    required: int,
    convention: BarConvention,
    required_columns: Sequence[str] = OHLC_COLUMNS,
) -> None:
    """Validate a frame before access.

    Args:
        bars: The bar frame.
        required: Minimum total rows needed for the requested access.
        convention: The frame's declared convention.
        required_columns: Columns that must be present.

    Raises:
        TypeError: If ``bars`` is not a DataFrame.
        InsufficientBarsError: If the frame is missing a required column or has
            fewer than ``required`` rows.
    """
    if not isinstance(bars, pd.DataFrame):
        raise TypeError(f"bars must be a pandas DataFrame, got {type(bars).__name__}")
    if not has_ohlc_columns(bars, required_columns):
        missing = [c for c in required_columns if c not in bars.columns]
        raise InsufficientBarsError(f"bar frame is missing columns: {', '.join(missing)}")
    if len(bars) < required:
        raise InsufficientBarsError(
            f"need at least {required} row(s) under {convention.value} convention, "
            f"got {len(bars)}"
        )


def closed_bars(
    bars: pd.DataFrame,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
    required_columns: Sequence[str] = OHLC_COLUMNS,
) -> pd.DataFrame:
    """Return only the completed bars of ``bars``.

    Under :attr:`BarConvention.CLOSED_ONLY` this is a no-op returning the frame
    unchanged. Applying it twice is therefore safe -- unlike the ad-hoc
    ``.iloc[:-1]`` pattern, which silently discards a real bar each time it is
    repeated.

    Args:
        bars: The bar frame.
        convention: The frame's declared convention.
        required_columns: Columns that must be present.

    Returns:
        A frame containing only completed bars. May be the input object itself
        when nothing needs removing.

    Raises:
        InsufficientBarsError: If no completed bars remain.
    """
    _validate(
        bars,
        required=convention.forming_row_count + 1,
        convention=convention,
        required_columns=required_columns,
    )
    if convention is BarConvention.CLOSED_ONLY:
        return bars
    return bars.iloc[:-1]


def last_closed_bar(
    bars: pd.DataFrame,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
) -> pd.Series:
    """Return the most recently **completed** bar.

    This is the bar all structure, sweep and entry logic should reason about.

    Args:
        bars: The bar frame.
        convention: The frame's declared convention.

    Returns:
        The last closed bar as a Series.

    Raises:
        InsufficientBarsError: If there is no completed bar.

    Example:
        >>> import pandas as pd
        >>> frame = pd.DataFrame({"open": [1, 2], "high": [2, 3],
        ...                       "low": [0, 1], "close": [1.5, 2.5]})
        >>> float(last_closed_bar(frame)["close"])
        2.5
        >>> float(last_closed_bar(frame, BarConvention.INCLUDES_FORMING)["close"])
        1.5
    """
    _validate(bars, required=convention.forming_row_count + 1, convention=convention)
    return bars.iloc[-1 - convention.forming_row_count]


def previous_closed_bar(
    bars: pd.DataFrame,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
) -> pd.Series:
    """Return the completed bar immediately before :func:`last_closed_bar`.

    Args:
        bars: The bar frame.
        convention: The frame's declared convention.

    Returns:
        The second-most-recent closed bar as a Series.

    Raises:
        InsufficientBarsError: If fewer than two completed bars exist.
    """
    _validate(bars, required=convention.forming_row_count + 2, convention=convention)
    return bars.iloc[-2 - convention.forming_row_count]


def forming_bar(
    bars: pd.DataFrame,
    convention: BarConvention = BarConvention.CLOSED_ONLY,
) -> pd.Series | None:
    """Return the still-forming bar, if the frame declares one.

    Returns ``None`` -- rather than raising -- under
    :attr:`BarConvention.CLOSED_ONLY`, because "there is no forming bar" is a
    normal, expected state for such a frame.

    Warning:
        The returned bar **repaints**. Its ``high``, ``low`` and ``close`` change
        until the bar closes. Never use it for structure, sweep detection, or
        entry levels. It is legitimate only for display and for live
        stop/target monitoring against the current price.

    Args:
        bars: The bar frame.
        convention: The frame's declared convention.

    Returns:
        The forming bar, or ``None`` if the convention declares none.

    Raises:
        InsufficientBarsError: If the frame is empty or malformed.
    """
    _validate(bars, required=1, convention=convention)
    if convention is BarConvention.CLOSED_ONLY:
        return None
    return bars.iloc[-1]
