"""PANEL: LABELS -- FUTURE INFORMATION. Deliberately sees forward bars.

Reads the raw dataset frames directly, NOT through ReplayFeed: the feed's
no-look-ahead guard protects the strategy, and this is diagnostic measurement of
what happened next.

Dependency direction
--------------------
This module reads `features.pkl` for ONE thing: the per-bar ATR used as the
barrier distance. That is features -> labels, which is the permitted direction.
Nothing here ever flows back into a feature. Excursions are emitted in RAW PRICE
units so that ATR-normalisation happens in `evaluate`, not here.

Barrier resolution
------------------
Touch times are resolved on M1 (per the brief), giving 1-minute rather than
5-minute granularity. M1 begins 2026-06-02 10:20 -- decisions before that, or
whose window M1 does not fully cover, are FLAGGED, not silently downgraded.

Gap honesty
-----------
A horizon of h M5 bars is h*5 MARKET minutes, which is not h*5 wall-clock
minutes when the window straddles the 20:00-22:00 break or a weekend. Both the
market span and the wall-clock span are recorded per row.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

REPO = Path(__file__).resolve().parents[1]
# argv is parsed inside main() so this module stays importable as a library
# (evaluate_D imports first_touch_m1 from it).
sys.path.insert(0, str(REPO))
from core.types import Timeframe
from data.dataset import load_bars_csv

HORIZONS = (1, 3, 6, 12, 24, 48)   # M5 bars: 5m/15m/30m/1h/2h/4h
"""1 and 3 exist only for the Candidate F "does reversal start immediately?"
diagnostic; 48 (4h) is secondary throughout."""



def first_touch_m1(m1_times, m1_high, m1_low, start, end, level, direction):
    """First M1 bar touching `level`, as market minutes from the window start.

    LABEL-DOMAIN: deliberately sees the future. `level` is supplied by the
    caller (a feature), which is the permitted features -> labels direction.

    Args:
        direction: "UP" if the level is above and reached by a high, "DOWN" if
            below and reached by a low.

    Returns:
        (minutes_to_touch | None, covered) -- `covered` is False when M1 does
        not span the window, so the row can be excluded rather than counted as
        a non-touch.
    """
    a = int(np.searchsorted(m1_times, start, side="left"))
    z = int(np.searchsorted(m1_times, end, side="left"))
    if z <= a:
        return None, False
    hit = (m1_high[a:z] >= level) if direction == "UP" else (m1_low[a:z] <= level)
    return (int(np.argmax(hit)) + 1 if hit.any() else None), True


def main() -> None:
    FEATURES = Path(sys.argv[1]); OUT = Path(sys.argv[2])
    feats = pd.read_pickle(FEATURES)
    atr = feats["atr_14"].to_numpy(float)          # barrier distance only

    m5 = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M5.csv", Timeframe.M5)
    m1 = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M1.csv", Timeframe.M1)
    n = len(m5)
    hi, lo, cl = (m5[k].to_numpy(float) for k in ("high", "low", "close"))
    t5 = pd.to_datetime(m5["time"], utc=True).to_numpy("datetime64[ns]")
    t1 = pd.to_datetime(m1["time"], utc=True).to_numpy("datetime64[ns]")
    m1hi, m1lo = m1["high"].to_numpy(float), m1["low"].to_numpy(float)
    FIVE = np.timedelta64(5, "m"); ONE = np.timedelta64(1, "m")

    out = {}
    for h in HORIZONS:
        # ---- M5 excursions over bars i+1 .. i+h, vectorised ----
        wh = sliding_window_view(hi, h)[1:]        # row i -> bars i+1..i+h
        wl = sliding_window_view(lo, h)[1:]
        m = len(wh)                                 # valid for i in [0, m)
        up = np.full(n, np.nan); dn = np.full(n, np.nan)
        up[:m] = wh.max(axis=1) - cl[:m]
        dn[:m] = cl[:m] - wl.min(axis=1)

        has_window = np.zeros(n, bool); has_window[:m] = True

        # ---- wall-clock vs market span ----
        wall = np.full(n, np.nan); 
        end_close = t5[h:][:m] + FIVE                # close time of bar i+h
        start_open = t5[1:][:m]                      # open time of bar i+1
        wall[:m] = (end_close - start_open) / np.timedelta64(1, "m")
        gapped = np.zeros(n, bool); gapped[:m] = wall[:m] > h * 5

        # ---- M1 barrier touch at +/- 1 ATR and +/- 2 ATR ----
        t_up = np.full(n, np.nan); t_dn = np.full(n, np.nan)
        t_up2 = np.full(n, np.nan); t_dn2 = np.full(n, np.nan)
        m1_ok = np.zeros(n, bool)
        lo_i = np.searchsorted(t1, start_open, side="left")
        hi_i = np.searchsorted(t1, end_close, side="left")
        for i in range(m):
            b = atr[i]
            if not np.isfinite(b) or b <= 0:
                continue
            a, z = lo_i[i], hi_i[i]
            if z <= a:
                continue
            # M1 must actually cover the window: expected market minutes = h*5
            covered = (z - a) >= h * 5
            m1_ok[i] = covered
            if not covered:
                continue
            ref = cl[i]
            wh1, wl1 = m1hi[a:z], m1lo[a:z]
            u = wh1 >= ref + b
            d = wl1 <= ref - b
            if u.any(): t_up[i] = int(np.argmax(u)) + 1      # market minutes
            if d.any(): t_dn[i] = int(np.argmax(d)) + 1
            u2 = wh1 >= ref + 2.0 * b
            d2 = wl1 <= ref - 2.0 * b
            if u2.any(): t_up2[i] = int(np.argmax(u2)) + 1
            if d2.any(): t_dn2[i] = int(np.argmax(d2)) + 1
        out[h] = dict(up=up, dn=dn, has_window=has_window, wall=wall,
                      gapped=gapped, t_up=t_up, t_dn=t_dn,
                      t_up2=t_up2, t_dn2=t_dn2, m1_ok=m1_ok)

    cols = {"idx": np.arange(n)}
    for h, d in out.items():
        for k, v in d.items():
            cols[f"{k}_{h}"] = v
    lab = pd.DataFrame(cols)
    lab.to_pickle(OUT)

    meta = {"horizons": list(HORIZONS), "rows": int(n),
            "per_horizon": {int(h): {
                "with_forward_window": int(d["has_window"].sum()),
                "m1_resolved": int(d["m1_ok"].sum()),
                "m1_unavailable": int((d["has_window"] & ~d["m1_ok"]).sum()),
                "gap_straddling": int(d["gapped"].sum()),
                "gap_pct": round(float(d["gapped"].sum() / d["has_window"].sum() * 100), 3),
                "wall_span_min_median": float(np.nanmedian(d["wall"])),
                "wall_span_min_p99": float(np.nanpercentile(d["wall"], 99)),
                "wall_span_min_max": float(np.nanmax(d["wall"])),
            } for h, d in out.items()}}
    OUT.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
