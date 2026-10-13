"""Anchor prices on H1 (UTC) bars for the batch-1 hypothesis variables.

A trading day d runs 18:00 America/New_York on calendar day d-1 to 17:00 New
York on day d; it is labelled d and only weekdays are days. An anchor at local
time T uses the close of the H1 bar ending at T (the bar opening at T - 1 h).
The one exception is the day's start at 18:00 New York, which uses the open of
the 18:00 bar, so the daily-break gap is excluded.

A value needs every H1 bar from its first anchor bar to its last; if any of
them is missing or has utc_suspect = True, the value is NaN and the row is
dropped. No trading day contains a DST switch (they happen on Sunday ~02:00),
so consecutive bars inside a day are exactly one hour apart in UTC.

Pure functions, no I/O.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
DAY_START_HOUR_NY = 18
DAY_END_HOUR_NY = 17
HOUR = pd.Timedelta(hours=1)


def trading_days(h1: pd.DataFrame) -> pd.Series:
    """The weekday trading days (as midnight Timestamps) that have at least one bar."""
    ny = h1["time"].dt.tz_convert(NEW_YORK).dt.tz_localize(None)
    day = (ny + pd.Timedelta(hours=24 - DAY_END_HOUR_NY)).dt.normalize()
    days = pd.Series(sorted(set(day[day.dt.dayofweek < 5])))
    return days


def local_time(days: pd.Series, hour: int, tz: ZoneInfo, day_offset: int = 0) -> pd.Series:
    """UTC instant of `hour`:00 local time on each day + day_offset (DST-correct)."""
    wall = days + pd.Timedelta(days=day_offset) + pd.Timedelta(hours=hour)
    return wall.dt.tz_localize(tz, ambiguous="raise", nonexistent="raise") \
        .dt.tz_convert("UTC").astype("datetime64[ns, UTC]")


class Bars:
    """H1 bars indexed for anchor lookups."""

    def __init__(self, h1: pd.DataFrame):
        h1 = h1.sort_values("time")
        self.t = h1["time"].astype("datetime64[ns, UTC]").to_numpy()
        self.open = h1["open"].to_numpy(float)
        self.close = h1["close"].to_numpy(float)
        self.spread = (h1["spread_usd"].to_numpy(float) if "spread_usd" in h1
                       else np.full(len(h1), np.nan))
        suspect = (h1["utc_suspect"].to_numpy(bool) if "utc_suspect" in h1
                   else np.zeros(len(h1), bool))
        self.suspect_cum = np.concatenate([[0], np.cumsum(suspect)])

    def _at(self, bar_open: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        q = bar_open.to_numpy()
        i = np.searchsorted(self.t, q)
        found = (i < len(self.t)) & (self.t[np.minimum(i, len(self.t) - 1)] == q)
        return np.minimum(i, len(self.t) - 1), found

    def open_at(self, t: pd.Series) -> np.ndarray:
        """Open of the bar opening at t (NaN if missing)."""
        i, ok = self._at(t)
        return np.where(ok, self.open[i], np.nan)

    def close_at(self, t: pd.Series) -> np.ndarray:
        """Close of the bar ending at t, i.e. opening at t - 1 h (NaN if missing)."""
        i, ok = self._at(t - HOUR)
        return np.where(ok, self.close[i], np.nan)

    def spread_of_bar_ending_at(self, t: pd.Series) -> np.ndarray:
        i, ok = self._at(t - HOUR)
        return np.where(ok, self.spread[i], np.nan)

    def complete(self, first_open: pd.Series, last_open: pd.Series) -> np.ndarray:
        """True where every hourly bar from first_open to last_open exists and none
        is utc_suspect."""
        lo = np.searchsorted(self.t, first_open.to_numpy(), side="left")
        hi = np.searchsorted(self.t, last_open.to_numpy(), side="right")
        expected = ((last_open - first_open) // HOUR).to_numpy() + 1
        return ((hi - lo) == expected) & (self.suspect_cum[hi] - self.suspect_cum[lo] == 0)


def log_return(p_end: np.ndarray, p_start: np.ndarray) -> np.ndarray:
    return np.log(p_end / p_start)
