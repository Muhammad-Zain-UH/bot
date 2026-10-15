"""H07 -- session return structure (ROADMAP_V2 §6). Variable only, no statistics.

Six blocks of the trading day in New York time: B1 18-22, B2 22-02, B3 02-06,
B4 06-10, B5 10-14, B6 14-17. r_Bk = log(P_end / P_start), mid prices of the
broker H1 bars (close of the bar ending at each boundary; the 18:00 start uses
the 18:00 bar's open). A day is dropped if any of its 23 bars (18:00 -> 16:00
open) is missing or utc_suspect. Cost columns: the spread_usd of each anchor bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold.hyp.anchors import NEW_YORK, Bars, local_time, log_return, trading_days

# (name, end hour NY, end day offset relative to day d); B1 starts 18:00 on d-1
BLOCKS = (("B1", 22, -1), ("B2", 2, 0), ("B3", 6, 0), ("B4", 10, 0), ("B5", 14, 0), ("B6", 17, 0))
START = (18, -1)
LAST_BAR_OPEN = (16, 0)


def block_returns(h1: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day: day, r_B1..r_B6, the day's start price, and the
    anchor bars' spread_usd (s_start, s_B1..s_B6)."""
    bars = Bars(h1)
    days = trading_days(h1)
    start = local_time(days, START[0], NEW_YORK, START[1])
    out = pd.DataFrame({"day": days})
    prev = bars.open_at(start)
    out["p_start_usd"] = prev
    out["s_start"] = bars.spread_of_bar_ending_at(start + pd.Timedelta(hours=1))
    for name, hour, off in BLOCKS:
        end = local_time(days, hour, NEW_YORK, off)
        p = bars.close_at(end)
        out[f"r_{name}"] = log_return(p, prev)
        out[f"s_{name}"] = bars.spread_of_bar_ending_at(end)
        prev = p
    ok = bars.complete(start, local_time(days, LAST_BAR_OPEN[0], NEW_YORK, LAST_BAR_OPEN[1]))
    ok &= np.isfinite(out[[f"r_{b}" for b, _, _ in BLOCKS]]).all(axis=1).to_numpy()
    return out[ok].reset_index(drop=True)
