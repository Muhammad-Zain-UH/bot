"""H08 -- intraday momentum into the COMEX settlement (ROADMAP_V2 §6). Variable only.

r_early = 18:00 (day d-1) -> 12:00 New York; r_late = 12:00 -> 14:00 New York.
H1 bars cannot resolve the 13:30 COMEX settlement; 12:00-14:00 contains it.
y = sign(r_early) x r_late. Days with r_early == 0 are dropped, as are days
missing any bar from 18:00 to the 13:00 bar, or with a utc_suspect bar.
Cost columns: spread_usd of the entry (12:00) and exit (14:00) anchor bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold.hyp.anchors import NEW_YORK, Bars, local_time, log_return, trading_days

START = (18, -1)
SPLIT = (12, 0)
END = (14, 0)


def momentum(h1: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day: day, r_early, r_late, y, s_entry, s_exit."""
    bars = Bars(h1)
    days = trading_days(h1)
    t0 = local_time(days, START[0], NEW_YORK, START[1])
    t1 = local_time(days, SPLIT[0], NEW_YORK, SPLIT[1])
    t2 = local_time(days, END[0], NEW_YORK, END[1])
    p0, p1, p2 = bars.open_at(t0), bars.close_at(t1), bars.close_at(t2)
    out = pd.DataFrame({"day": days, "r_early": log_return(p1, p0), "r_late": log_return(p2, p1)})
    out["y"] = np.sign(out["r_early"]) * out["r_late"]
    out["s_entry"] = bars.spread_of_bar_ending_at(t1)
    out["s_exit"] = bars.spread_of_bar_ending_at(t2)
    out["price_entry_usd"] = p1
    ok = bars.complete(t0, t2 - pd.Timedelta(hours=1))
    ok &= np.isfinite(out[["r_early", "r_late"]]).all(axis=1).to_numpy()
    ok &= (out["r_early"] != 0).to_numpy()
    return out[ok].reset_index(drop=True)
