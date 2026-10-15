"""H09 -- London PM auction reversal (ROADMAP_V2 §6). Variable only.

r_pre = 14:00 -> 15:00 Europe/London; r_post = 15:00 -> 16:00 Europe/London.
y = -sign(r_pre) x r_post. Days with r_pre == 0 are dropped (no direction, as
for H08's r_early), as are days missing any of the three bars (13:00, 14:00,
15:00 London opens) or with a utc_suspect bar. Cost columns: spread_usd of the
entry (15:00) and exit (16:00) anchor bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gold.hyp.anchors import LONDON, Bars, local_time, log_return, trading_days

PRE_START, AUCTION, POST_END = 14, 15, 16        # Europe/London hours, on day d
OLD_FIX_ERA_END = pd.Timestamp("2015-03-19")     # last day of the old London PM fixing


def auction(h1: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day: day, r_pre, r_post, y, s_entry, s_exit."""
    bars = Bars(h1)
    days = trading_days(h1)
    t0, t1, t2 = (local_time(days, h, LONDON) for h in (PRE_START, AUCTION, POST_END))
    p0, p1, p2 = bars.close_at(t0), bars.close_at(t1), bars.close_at(t2)
    out = pd.DataFrame({"day": days, "r_pre": log_return(p1, p0), "r_post": log_return(p2, p1)})
    out["y"] = -np.sign(out["r_pre"]) * out["r_post"]
    out["s_entry"] = bars.spread_of_bar_ending_at(t1)
    out["s_exit"] = bars.spread_of_bar_ending_at(t2)
    out["price_entry_usd"] = p1
    ok = bars.complete(t0 - pd.Timedelta(hours=1), t2 - pd.Timedelta(hours=1))
    ok &= np.isfinite(out[["r_pre", "r_post"]]).all(axis=1).to_numpy()
    ok &= (out["r_pre"] != 0).to_numpy()
    return out[ok].reset_index(drop=True)
