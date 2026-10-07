"""Bar timing arithmetic -- the primitive that prevents look-ahead.

The single most important rule in this package
----------------------------------------------
MetaTrader timestamps a bar by its **open** time. An M5 bar stamped ``10:35``
covers 10:35:00-10:39:59 and only becomes known at ``10:40``.

So a bar is visible at replay time ``T`` if and only if::

    bar.open_time + timeframe.duration <= T

Getting this backwards -- treating the stamp as a close time -- is the classic
silent look-ahead. It does not raise, it does not look wrong in a chart, and it
makes every backtest result optimistic because the strategy sees the outcome of
the bar it is deciding on.

Worked example at ``T = 10:37:00``

=====  ==================  ==========  =======
TF     latest visible bar  closes at   visible
=====  ==================  ==========  =======
M1     10:36               10:37       yes
M5     10:30               10:35       yes
M5     10:35               10:40       **no**
M15    10:15               10:30       yes
H1     09:00               10:00       yes
H4     04:00               08:00       yes
=====  ==================  ==========  =======

A bar closing exactly at ``T`` **is** visible -- the boundary is inclusive,
because at ``10:37:00`` the bar that closed at ``10:37:00`` is complete.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from core.types import Timeframe

__all__ = [
    "MT5_TIMEFRAME_NAMES",
    "bar_close_time",
    "duration",
    "floor_to_timeframe",
    "is_visible_at",
    "latest_visible_open_time",
    "resample_from_m1",
]

MT5_TIMEFRAME_NAMES: dict[Timeframe, str] = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
    Timeframe.D1: "TIMEFRAME_D1",
    Timeframe.W1: "TIMEFRAME_W1",
}
"""Maps our enum to MetaTrader5 constant names, by name only.

Kept as strings so this module never imports ``MetaTrader5``; the export tool
resolves them with ``getattr`` at its own call site.
"""

_PANDAS_FREQ: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1D",
    Timeframe.W1: "1W",
}


def duration(timeframe: Timeframe) -> timedelta:
    """Return the wall-clock length of one bar on ``timeframe``.

    Args:
        timeframe: The timeframe.

    Returns:
        Bar duration as a :class:`~datetime.timedelta`.
    """
    return timedelta(minutes=timeframe.minutes)


def bar_close_time(open_time: datetime, timeframe: Timeframe) -> datetime:
    """Return the instant at which a bar becomes complete.

    Args:
        open_time: The bar's open (stamped) time.
        timeframe: The bar's timeframe.

    Returns:
        ``open_time + duration(timeframe)``.
    """
    return open_time + duration(timeframe)


def is_visible_at(open_time: datetime, timeframe: Timeframe, as_of: datetime) -> bool:
    """Return whether a bar is known at ``as_of``.

    Args:
        open_time: The bar's open (stamped) time.
        timeframe: The bar's timeframe.
        as_of: Replay time.

    Returns:
        ``True`` if the bar has closed at or before ``as_of``.
    """
    return bar_close_time(open_time, timeframe) <= as_of


def floor_to_timeframe(moment: datetime, timeframe: Timeframe) -> datetime:
    """Round ``moment`` down to the start of its containing bar.

    Uses UTC-anchored boundaries. A broker whose server runs at a UTC offset may
    align its H4 and D1 bars differently; that is why native per-timeframe
    exports are preferred over resampling, and why
    :func:`resample_from_m1` records that it derived the bars.

    Args:
        moment: Any instant.
        timeframe: The timeframe to floor to.

    Returns:
        The open time of the bar containing ``moment``.
    """
    return pd.Timestamp(moment).floor(_PANDAS_FREQ[timeframe]).to_pydatetime()


def latest_visible_open_time(
    timeframe: Timeframe,
    as_of: datetime,
) -> datetime:
    """Return the open time of the most recent bar that has closed by ``as_of``.

    Args:
        timeframe: The timeframe.
        as_of: Replay time.

    Returns:
        The open time of the newest fully closed bar.

    Example:
        >>> from datetime import datetime, timezone
        >>> t = datetime(2026, 5, 1, 10, 37, tzinfo=timezone.utc)
        >>> latest_visible_open_time(Timeframe.M5, t).strftime("%H:%M")
        '10:30'
    """
    floored = floor_to_timeframe(as_of, timeframe)
    # If `as_of` sits exactly on a boundary, the bar opening there has not
    # closed yet -- the one before it is the newest complete bar.
    if floored + duration(timeframe) > as_of:
        floored = floored - duration(timeframe)
    return floored


def resample_from_m1(m1_bars: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Derive higher-timeframe bars from M1 data.

    Used only when a native export for ``timeframe`` is unavailable. Derived
    bars are anchored to **UTC** boundaries, which may not match the broker's
    own H4/D1 boundaries if its server runs at an offset. Any run that relies on
    this records the fact in its manifest.

    Args:
        m1_bars: M1 bars with ``time``, ``open``, ``high``, ``low``, ``close``
            and ``tick_volume``. ``time`` must be tz-aware UTC.
        timeframe: Target timeframe; must be coarser than M1.

    Returns:
        Resampled bars in the same column layout, with empty periods (weekends,
        holidays) dropped rather than forward-filled -- inventing a bar for a
        closed market would be fabricated data.

    Raises:
        ValueError: If ``timeframe`` is M1 or finer, or required columns are
            missing.
    """
    if timeframe is Timeframe.M1:
        raise ValueError("cannot resample M1 from M1")
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(m1_bars.columns)
    if missing:
        raise ValueError(f"m1_bars is missing columns: {sorted(missing)}")

    frame = m1_bars.set_index("time").sort_index()
    aggregation: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "tick_volume" in frame.columns:
        aggregation["tick_volume"] = "sum"

    resampled = frame.resample(_PANDAS_FREQ[timeframe], label="left", closed="left").agg(
        aggregation
    )
    # Periods with no ticks produce all-NaN rows; the market was closed, so the
    # bar does not exist. Dropping is correct; filling would fabricate data.
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    resampled = resampled.reset_index()
    if "tick_volume" not in resampled.columns:
        resampled["tick_volume"] = 0.0
    return resampled[["time", "open", "high", "low", "close", "tick_volume"]]
