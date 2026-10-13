"""D1 bars from v1b H4 bars, with the day boundary at 17:00 America/New_York.

The broker's H4 bars start at server midnight, which is 17:00 New York (US
rule, before 2020-07) or 18:00 New York (EU rule in the weeks when only the US
is on summer time). Either way no H4 bar holds trading from two sessions,
because 17:00-18:00 New York is the daily break; daily_bars checks this and
fails otherwise. Each H4 bar goes to the session that contains its open.

time is the UTC instant the session opens (17:00 New York the day before);
session is the New York date the session closes. Weekend sessions are dropped.
Before 2009-08 the broker's clock convention is unconfirmed; a 1 h shift is
negligible for daily bars. Pure function, no I/O.
"""
from __future__ import annotations

import pandas as pd

from gold.hyp.anchors import NEW_YORK, local_time

SESSION_CLOSE_HOUR_NY = 17
H4_GRID_HOURS_NY = (17, 18)          # H4 opens fall on a 4 h grid from one of these
COLUMNS = ["time", "session", "open", "high", "low", "close", "tick_volume",
           "spread_usd", "utc_suspect", "n_h4"]


def session_of(time: pd.Series) -> pd.Series:
    ny = time.dt.tz_convert(NEW_YORK).dt.tz_localize(None)
    return (ny + pd.Timedelta(hours=24 - SESSION_CLOSE_HOUR_NY)).dt.normalize()


def daily_bars(h4: pd.DataFrame) -> pd.DataFrame:
    ny_hour = h4["time"].dt.tz_convert(NEW_YORK).dt.hour
    on_grid = pd.Series(False, index=h4.index)
    for g in H4_GRID_HOURS_NY:
        on_grid |= (ny_hour - g) % 4 == 0
    if not on_grid.all():
        bad = h4.loc[~on_grid, "time"].iloc[0]
        raise ValueError(f"H4 bar at {bad} is off the 17:00/18:00 New York grid and may "
                         "hold trading from two sessions")
    g = h4.groupby(session_of(h4["time"]).rename("session"), sort=True)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), tick_volume=("tick_volume", "sum"),
                spread_usd=("spread_usd", "median"), utc_suspect=("utc_suspect", "any"),
                n_h4=("time", "size")).reset_index()
    out = out[out["session"].dt.dayofweek < 5].reset_index(drop=True)
    out["time"] = local_time(out["session"], SESSION_CLOSE_HOUR_NY, NEW_YORK, day_offset=-1)
    return out[COLUMNS]
