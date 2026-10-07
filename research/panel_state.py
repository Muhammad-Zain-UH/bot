"""STATE PANEL -- PAST/KNOWN INFORMATION ONLY.

One row per M5 bar. Every column is a causal function of bars <= i and describes
market STATE without asserting a direction. No column is derived from, selected
by, or thresholded against any label.

Timeframes: M5 and M15 only. H4/D1 are deliberately excluded (21.8% warmup cost,
broker-native bar alignment); H1 is not required by any feature family here.

M15 alignment: for M5 bar i, the last M15 bar to have CLOSED at or before bar
i's close. A decision mid-M15-bar reads the previous completed M15 bar.

Causality is VERIFIED, not asserted: every feature is recomputed on truncated
prefixes and must agree exactly.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core.types import Timeframe
from data.dataset import load_bars_csv

SESSION_HOURS = (1, 7, 13, 22)


def _roll_max(a, w):
    return pd.Series(a).rolling(w).max().to_numpy(float)


def _roll_min(a, w):
    return pd.Series(a).rolling(w).min().to_numpy(float)


def _safe(num, den):
    out = np.full(len(num), np.nan)
    ok = np.isfinite(num) & np.isfinite(den) & (den != 0)
    out[ok] = num[ok] / den[ok]
    return out


def build_state(m5: pd.DataFrame, m15: pd.DataFrame) -> dict[str, np.ndarray]:
    """Return {feature_name: array}. Element i uses only bars <= i."""
    o, h, l, c = (m5[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    atr5 = ta.atr(pd.Series(h), pd.Series(l), pd.Series(c), length=14).to_numpy(float)
    atr5_avg = pd.Series(atr5).rolling(20, min_periods=5).mean().to_numpy(float)
    tr = np.r_[np.nan, np.maximum.reduce([
        h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    tr3 = pd.Series(tr).rolling(3).mean().to_numpy(float)

    hh, lh, ch = (m15[k].to_numpy(float) for k in ("high", "low", "close"))
    atr15 = m15["atr_14"].to_numpy(float)
    atr15_avg = pd.Series(atr15).rolling(20, min_periods=5).mean().to_numpy(float)

    # last M15 bar CLOSED at or before this M5 bar's close
    t5 = pd.to_datetime(m5["time"], utc=True)
    t15 = pd.to_datetime(m15["time"], utc=True)
    FIVE, FIFTEEN = pd.Timedelta(minutes=5), pd.Timedelta(minutes=15)
    j = np.searchsorted((t15 + FIFTEEN).to_numpy("datetime64[ns]"),
                        (t5 + FIVE).to_numpy("datetime64[ns]"), side="right") - 1
    jv = np.clip(j, 0, len(ch) - 1)
    ok15 = j >= 6

    def m15_at(arr, back=0):
        out = np.full(n, np.nan)
        idx = jv - back
        good = ok15 & (idx >= 0)
        out[good] = arr[idx[good]]
        return out

    f: dict[str, np.ndarray] = {}

    # ---------------- A. directional displacement ----------------
    for w in (3, 6, 12):
        prev = np.r_[np.full(w, np.nan), c[:-w]]
        f[f"disp_{w}"] = _safe(c - prev, atr5)
    for w in (3, 6):
        f[f"disp_m15_{w}"] = _safe(m15_at(ch) - m15_at(ch, w), m15_at(atr15))

    # ---------------- B. volatility state ----------------
    f["atr5"] = atr5
    f["atr15"] = m15_at(atr15)
    f["atr_ratio5"] = _safe(atr5, atr5_avg)
    f["atr_ratio15"] = _safe(m15_at(atr15), m15_at(atr15_avg))
    f["atr_short_long"] = _safe(tr3, atr5)
    rng12 = _roll_max(h, 12) - _roll_min(l, 12)
    rng12_prev = np.r_[np.full(12, np.nan), rng12[:-12]]
    f["rng12_atr"] = _safe(rng12, atr5)
    f["rng_expand"] = _safe(rng12, rng12_prev)

    # ---------------- C. position inside recent range ----------------
    for w in (12, 24):
        hi, lo = _roll_max(h, w), _roll_min(l, w)
        f[f"pos_{w}"] = _safe(c - lo, hi - lo)
        if w == 12:
            f["dist_high12_atr"] = _safe(hi - c, atr5)
            f["dist_low12_atr"] = _safe(c - lo, atr5)
    hi15, lo15 = _roll_max(hh, 20), _roll_min(lh, 20)
    f["pos_m15_20"] = _safe(m15_at(ch) - m15_at(lo15), m15_at(hi15) - m15_at(lo15))
    f["dist_high_m15_atr"] = _safe(m15_at(hi15) - m15_at(ch), m15_at(atr15))
    f["dist_low_m15_atr"] = _safe(m15_at(ch) - m15_at(lo15), m15_at(atr15))

    # ---------------- D. candle / path structure ----------------
    rng = h - l
    f["body_ratio"] = _safe(np.abs(c - o), rng)
    f["upper_wick_ratio"] = _safe(h - np.maximum(o, c), rng)
    f["lower_wick_ratio"] = _safe(np.minimum(o, c) - l, rng)
    f["close_loc"] = _safe(c - l, rng)
    up = np.r_[np.nan, np.sign(np.diff(c))]
    for w in (6, 12):
        f[f"up_frac_{w}"] = pd.Series((up > 0).astype(float)).rolling(w).mean().to_numpy()
    flip = np.r_[np.nan, (up[1:] * up[:-1]) < 0].astype(float)
    f["alt_freq_12"] = pd.Series(flip).rolling(12).mean().to_numpy()
    consec = np.zeros(n)
    for i in range(1, n):
        if up[i] == 0 or not np.isfinite(up[i]):
            consec[i] = 0
        elif up[i] == up[i - 1]:
            consec[i] = consec[i - 1] + up[i]
        else:
            consec[i] = up[i]
    f["consec_same"] = consec

    # ---------------- E. session / time ----------------
    hr = t5.dt.hour.to_numpy().astype(float)
    f["utc_hour"] = hr
    sess = np.full(n, np.nan)
    mins = np.full(n, np.nan)
    for hh_ in SESSION_HOURS:
        start = (hr == hh_) & (t5.dt.minute.to_numpy() == 0)
        for s in np.flatnonzero(start):
            e = min(s + 12, n)
            sess[s:e] = hh_
            mins[s:e] = np.arange(e - s) * 5.0
    f["session_bucket"] = sess
    f["mins_since_open"] = mins

    # ---------------- F. volatility x direction interactions ----------------
    f["disp12_x_atrratio"] = f["disp_12"] * f["atr_ratio5"]
    f["disp12_x_pos24"] = f["disp_12"] * f["pos_24"]
    f["disthigh_x_disp6"] = f["dist_high12_atr"] * f["disp_6"]
    f["rngexp_x_disp6"] = f["rng_expand"] * f["disp_6"]
    f["pos24_x_atrratio"] = f["pos_24"] * f["atr_ratio5"]
    return f


def main() -> None:
    out = Path(sys.argv[1])
    m5 = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M5.csv", Timeframe.M5)
    m15 = pd.read_pickle(sys.argv[2])          # existing M15 feature panel
    f = build_state(m5, m15)
    n = len(m5)

    rng = np.random.default_rng(20260930)
    probes = sorted(rng.choice(np.arange(200, n), size=120, replace=False).tolist())
    worst: dict[str, float] = {k: 0.0 for k in f}
    t15 = pd.to_datetime(m15["time"], utc=True)
    t5 = pd.to_datetime(m5["time"], utc=True)
    for i in probes:
        cut15 = int((t15 + pd.Timedelta(minutes=15) <= t5.iloc[i] + pd.Timedelta(minutes=5)).sum())
        pf = build_state(m5.iloc[:i + 1].reset_index(drop=True),
                         m15.iloc[:cut15].reset_index(drop=True))
        for k in f:
            a, b = f[k][i], pf[k][i]
            if (np.isnan(a) and np.isnan(b)):
                continue
            worst[k] = max(worst[k], abs(float(a) - float(b)))
    exact = all(v == 0.0 for v in worst.values())

    df = pd.DataFrame({"idx": np.arange(n), "time": t5, **f})
    df.to_pickle(out)
    meta = {"rows": n, "features": sorted(f), "n_features": len(f),
            "causality_prefix_test": {"probes": len(probes), "exact": bool(exact),
                                      "max_abs_deviation": {k: float(v) for k, v in worst.items()}}}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"rows": n, "n_features": len(f), "causal_exact": bool(exact),
                      "worst": max(worst.values())}, indent=2))
    if not exact:
        bad = {k: v for k, v in worst.items() if v > 0}
        raise SystemExit(f"CAUSALITY FAILED: {bad}")


if __name__ == "__main__":
    main()
