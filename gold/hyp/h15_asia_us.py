"""H15 -- Asia vs US session (WGC session definitions, fixed UTC). Variable only, no statistics.

Trading day d = the UTC date of the Asia session's end (weekdays).
r_asia = log(close of the bar ending 11:00 UTC on d / open of the first bar at or after
         22:00 UTC on d-1); that first bar must open on d-1 (22:00 or 23:00 UTC: the broker is
         closed 22:00-23:00 UTC in US winter), else the day is dropped;
r_us   = log(close of the last bar ending at or before 22:00 UTC on d (opening 14:00..21:00 UTC)
         / close of the bar ending 14:00 UTC on d);
y = r_asia - r_us; per-hour contrast = r_asia / 13 - r_us / 8 (WGC session lengths).
A day needs every hourly bar from the Asia start bar through the US end bar, none utc_suspect.
Cost columns: spread_usd and prices of the four bars whose prices are used.
Pure function, no I/O.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold.hyp.anchors import Bars, log_return

ASIA_START_HOURS_UTC = (22, 23)        # on d-1: first bar at or after 22:00 UTC
ASIA_END_UTC = 11                      # close of the bar ending 11:00 UTC
US_START_UTC = 14                      # close of the bar ending 14:00 UTC
US_END_LATEST_OPEN_UTC = 21            # last bar ending at or before 22:00 UTC
ASIA_HOURS, US_HOURS = 13, 8
HOUR = pd.Timedelta(hours=1)


def _first_existing(bars: Bars, candidates: list[pd.Series]) -> pd.Series:
    """Per row, the first candidate bar-open time that exists in bars (NaT if none)."""
    out = pd.Series(pd.NaT, index=candidates[0].index, dtype="datetime64[ns, UTC]")
    for c in candidates:
        _, found = bars._at(c)
        out = out.where(out.notna() | ~pd.Series(found, index=c.index), c)
    return out


def asia_us(h1: pd.DataFrame) -> pd.DataFrame:
    bars = Bars(h1)
    dates = h1["time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    days = pd.Series(sorted(set(dates[dates.dt.dayofweek < 5])))
    def at(h: int, off: int = 0) -> pd.Series:
        return (days + pd.Timedelta(days=off, hours=h)).dt.tz_localize("UTC").astype("datetime64[ns, UTC]")
    start = _first_existing(bars, [at(h, -1) for h in ASIA_START_HOURS_UTC])
    end = _first_existing(bars, [at(h) for h in range(US_END_LATEST_OPEN_UTC, US_START_UTC - 1, -1)])
    t11, t14 = at(ASIA_END_UTC), at(US_START_UTC)
    ok = start.notna() & end.notna()
    s0 = start.fillna(t11 - HOUR)                  # placeholders; rows dropped below
    e0 = end.fillna(t14)
    p_start, p_11, p_14 = bars.open_at(s0), bars.close_at(t11), bars.close_at(t14)
    p_end = bars.close_at(e0 + HOUR)
    out = pd.DataFrame({"day": days, "r_asia": log_return(p_11, p_start), "r_us": log_return(p_end, p_14)})
    out["y"] = out["r_asia"] - out["r_us"]
    out["per_hour"] = out["r_asia"] / ASIA_HOURS - out["r_us"] / US_HOURS
    out["asia_start"], out["us_end"] = start, end
    out["s_asia_start"] = bars.spread_of_bar_ending_at(s0 + HOUR)
    out["s_11"] = bars.spread_of_bar_ending_at(t11)
    out["s_14"] = bars.spread_of_bar_ending_at(t14)
    out["s_us_end"] = bars.spread_of_bar_ending_at(e0 + HOUR)
    out["p_asia_start"], out["p_14"] = p_start, p_14
    ok &= pd.Series(bars.complete(s0, e0), index=days.index)
    ok &= np.isfinite(out[["r_asia", "r_us"]]).all(axis=1)
    return out[ok.to_numpy()].reset_index(drop=True)
