"""H14 -- overnight vs New York session. Variable only, no statistics.

Per trading day d (18:00 New York on d-1 -> 17:00 on d):
r_on = log(close of the bar ending 08:00 NY / open of the 18:00 NY bar on d-1);
r_ny = log(close of the bar ending 15:00 NY / close of the bar ending 08:00 NY);
y = r_on - r_ny. A day needs every H1 bar opening 18:00 (d-1) .. 14:00 (d), none utc_suspect.
Cost columns: spread_usd of the bars whose prices are used (18:00 bar, bar ending 08:00,
bar ending 15:00) and the two entry prices. Pure function, no I/O.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold.hyp.anchors import NEW_YORK, Bars, local_time, log_return, trading_days

START = (18, -1)
SPLIT = (8, 0)
END = (15, 0)


def overnight_vs_ny(h1: pd.DataFrame) -> pd.DataFrame:
    bars = Bars(h1)
    days = trading_days(h1)
    t0 = local_time(days, START[0], NEW_YORK, START[1])
    t1 = local_time(days, SPLIT[0], NEW_YORK, SPLIT[1])
    t2 = local_time(days, END[0], NEW_YORK, END[1])
    p0, p1, p2 = bars.open_at(t0), bars.close_at(t1), bars.close_at(t2)
    out = pd.DataFrame({"day": days, "r_on": log_return(p1, p0), "r_ny": log_return(p2, p1)})
    out["y"] = out["r_on"] - out["r_ny"]
    out["s_18"] = bars.spread_of_bar_ending_at(t0 + pd.Timedelta(hours=1))
    out["s_08"] = bars.spread_of_bar_ending_at(t1)
    out["s_15"] = bars.spread_of_bar_ending_at(t2)
    out["p_18"], out["p_08"] = p0, p1
    ok = bars.complete(t0, t2 - pd.Timedelta(hours=1))
    ok &= np.isfinite(out[["r_on", "r_ny"]]).all(axis=1).to_numpy()
    return out[ok].reset_index(drop=True)
