"""PHASE 1 FEATURE PANEL -- causal M15 state, PAST INFORMATION ONLY.

One row per M15 bar. Every column at row i is a function of bars <= i only.

OOS isolation by construction
-----------------------------
The panel is TRUNCATED at the DEV end boundary before any feature is computed, so
no FINAL_OOS bar is ever read, let alone used. `dataset_access` is the only loader
and its token is untouched. The truncation is asserted, not assumed.

Known coupling hazard, carried explicitly
-----------------------------------------
Phases 1 and 2 of the previous programme each produced a t-statistic above 8 from
a feature with no economic content, because the feature was a function of
`close[i]` and the label subtracts `close[i]`. Features with that exposure are
tagged in `COUPLES_WITH_CLOSE` and the scan refuses to promote any of them without
the reference-price and delayed-entry controls.

H1 context alignment
--------------------
For M15 bar i, the H1 features come from the last H1 bar to have CLOSED at or
before bar i's close. A decision mid-H1-bar reads the previous completed H1 bar.

Causality is VERIFIED by prefix recomputation, not asserted.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))
from dataset_access import load_timeframe, _split

M15_MIN = 15
# features that are a direct function of close[i]'s position -> coupling hazard
COUPLES_WITH_CLOSE = {
    "close_loc", "pos_20", "pos_50", "dist_high20_atr", "dist_low20_atr",
    "pos_h1_20", "dist_vwapless_atr",
}


def _safe(num, den):
    out = np.full(len(num), np.nan)
    ok = np.isfinite(num) & np.isfinite(den) & (den != 0)
    out[ok] = num[ok] / den[ok]
    return out


def _wilder_atr(h, l, c, n=14):
    """Causal Wilder ATR implemented directly so there is no library ambiguity."""
    tr = np.full(len(c), np.nan)
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]),
                                np.abs(l[1:] - c[:-1])])
    atr = np.full(len(c), np.nan)
    if len(c) <= n:
        return atr
    atr[n] = np.nanmean(tr[1:n + 1])
    for i in range(n + 1, len(c)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def _slope(c, w):
    """Least-squares slope over the trailing w bars, per bar, ending at i."""
    out = np.full(len(c), np.nan)
    x = np.arange(w, dtype=float)
    x -= x.mean()
    denom = (x ** 2).sum()
    for i in range(w - 1, len(c)):
        y = c[i - w + 1:i + 1]
        out[i] = float(((y - y.mean()) * x).sum() / denom)
    return out


def build_features(m15: pd.DataFrame, h1: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (m15[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    t15 = pd.to_datetime(m15["time"], utc=True)
    atr = _wilder_atr(h, l, c, 14)
    atr_avg = pd.Series(atr).rolling(20, min_periods=10).mean().to_numpy(float)
    rng = h - l
    f: dict[str, np.ndarray] = {}

    # ---------------- 1. displacement ----------------
    for w in (1, 4, 8, 16):
        prev = np.r_[np.full(w, np.nan), c[:-w]]
        f[f"disp_{w}"] = _safe(c - prev, atr)
    up = np.r_[np.nan, np.sign(np.diff(c))]
    f["persist_8"] = pd.Series(up).rolling(8).mean().to_numpy(float)
    f["persist_16"] = pd.Series(up).rolling(16).mean().to_numpy(float)

    # ---------------- 2. volatility ----------------
    f["atr"] = atr
    f["atr_ratio"] = _safe(atr, atr_avg)
    tr3 = pd.Series(np.r_[np.nan, np.maximum.reduce(
        [h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    ).rolling(3).mean().to_numpy(float)
    f["atr_short_long"] = _safe(tr3, atr)
    r20 = (pd.Series(h).rolling(20).max() - pd.Series(l).rolling(20).min()).to_numpy(float)
    r20_prev = np.r_[np.full(20, np.nan), r20[:-20]]
    f["range20_atr"] = _safe(r20, atr)
    f["range_expansion"] = _safe(r20, r20_prev)
    f["ntr"] = _safe(rng, atr)

    # ---------------- 3. candle / range structure ----------------
    f["body_ratio"] = _safe(np.abs(c - o), rng)
    f["upper_wick"] = _safe(h - np.maximum(o, c), rng)
    f["lower_wick"] = _safe(np.minimum(o, c) - l, rng)
    f["close_loc"] = _safe(c - l, rng)

    # ---------------- 4. trend / state ----------------
    for w in (20, 50):
        ma = pd.Series(c).rolling(w).mean().to_numpy(float)
        f[f"ma{w}_dist_atr"] = _safe(c - ma, atr)
    ma20 = pd.Series(c).rolling(20).mean().to_numpy(float)
    ma50 = pd.Series(c).rolling(50).mean().to_numpy(float)
    f["ma_spread_atr"] = _safe(ma20 - ma50, atr)
    f["slope20_atr"] = _safe(_slope(c, 20), atr)
    f["slope50_atr"] = _safe(_slope(c, 50), atr)

    # ---------------- 5. location ----------------
    for w in (20, 50):
        hi_w = pd.Series(h).rolling(w).max().to_numpy(float)
        lo_w = pd.Series(l).rolling(w).min().to_numpy(float)
        f[f"pos_{w}"] = _safe(c - lo_w, hi_w - lo_w)
        if w == 20:
            f["dist_high20_atr"] = _safe(hi_w - c, atr)
            f["dist_low20_atr"] = _safe(c - lo_w, atr)

    # ---------------- 6. compression / expansion ----------------
    f["compression"] = _safe(r20, atr * 20.0)          # tight range vs ATR budget
    f["expansion_state"] = _safe(rng, pd.Series(rng).rolling(20).mean().to_numpy(float))
    f["vol_transition"] = _safe(
        pd.Series(atr).rolling(5).mean().to_numpy(float),
        pd.Series(atr).rolling(20).mean().to_numpy(float))

    # ---------------- 7. session / time ----------------
    f["utc_hour"] = t15.dt.hour.to_numpy(float)
    f["weekday"] = t15.dt.weekday.to_numpy(float)
    hr = t15.dt.hour.to_numpy()
    # distance (bars) since the 22:00 UTC reopen; break is 19:55 -> 22:00 UTC
    reopen = (hr == 22) & (t15.dt.minute.to_numpy() == 0)
    since = np.full(n, np.nan)
    last = -1
    for i in range(n):
        if reopen[i]:
            last = i
        if last >= 0:
            since[i] = i - last
    f["bars_since_reopen"] = since
    f["session"] = np.select(
        [hr < 7, hr < 13, hr < 20], [0.0, 1.0, 2.0], default=3.0)  # ASIA/LON/NY/DEAD

    # ---------------- 8. H1 context ----------------
    hh, hl, hc = (h1[k].to_numpy(float) for k in ("high", "low", "close"))
    th1 = pd.to_datetime(h1["time"], utc=True)
    h1_atr = _wilder_atr(hh, hl, hc, 14)
    h1_atr_avg = pd.Series(h1_atr).rolling(20, min_periods=10).mean().to_numpy(float)
    h1_hi20 = pd.Series(hh).rolling(20).max().to_numpy(float)
    h1_lo20 = pd.Series(hl).rolling(20).min().to_numpy(float)
    h1_ma50 = pd.Series(hc).rolling(50).mean().to_numpy(float)
    # last H1 bar CLOSED at or before this M15 bar's close
    h1_close = (th1 + pd.Timedelta(hours=1)).to_numpy("datetime64[ns]")
    m15_close = (t15 + pd.Timedelta(minutes=M15_MIN)).to_numpy("datetime64[ns]")
    j = np.searchsorted(h1_close, m15_close, side="right") - 1
    ok = j >= 50
    jv = np.clip(j, 0, len(hc) - 1)

    def pick(arr, back=0):
        out = np.full(n, np.nan)
        idx = jv - back
        good = ok & (idx >= 0)
        out[good] = arr[idx[good]]
        return out

    f["h1_disp_4"] = _safe(pick(hc) - pick(hc, 4), pick(h1_atr))
    f["h1_disp_12"] = _safe(pick(hc) - pick(hc, 12), pick(h1_atr))
    f["h1_atr_ratio"] = _safe(pick(h1_atr), pick(h1_atr_avg))
    f["h1_trend"] = _safe(pick(hc) - pick(h1_ma50), pick(h1_atr))
    f["pos_h1_20"] = _safe(pick(hc) - pick(h1_lo20), pick(h1_hi20) - pick(h1_lo20))
    f["h1_trend_x_m15_disp"] = f["h1_trend"] * f["disp_8"]

    df = pd.DataFrame({"idx": np.arange(n), "time": t15, "close": c,
                       "high": h, "low": l, "open": o, "atr": atr, **f})
    df["feature_eligible"] = (np.isfinite(atr) & (atr > 0) & np.isfinite(f["slope50_atr"])
                              & np.isfinite(f["pos_50"]) & np.isfinite(f["h1_trend"]))
    return df


def main() -> None:
    out = Path(sys.argv[1])
    split = _split()
    dev_end = pd.Timestamp(split["arms"]["DEV"]["to_utc"])

    m15 = load_timeframe("M15")
    h1 = load_timeframe("H1")
    # ---- OOS ISOLATION: truncate BEFORE computing anything ----
    m15 = m15[m15["time"] <= dev_end].reset_index(drop=True)
    h1 = h1[h1["time"] <= dev_end].reset_index(drop=True)
    assert m15["time"].max() <= dev_end, "M15 panel extends past DEV end"
    assert h1["time"].max() <= dev_end, "H1 panel extends past DEV end"

    df = build_features(m15, h1)
    feat_cols = [c for c in df.columns
                 if c not in ("idx", "time", "close", "high", "low", "open",
                              "atr", "feature_eligible")]

    # ---- CAUSALITY VERIFICATION: prefix rebuild, exact agreement required ----
    rng = np.random.default_rng(20261002)
    probes = sorted(rng.choice(np.arange(600, len(df)), size=60, replace=False).tolist())
    worst = {k: 0.0 for k in feat_cols}
    for i in probes:
        cut_t = m15["time"].iloc[i]
        sub15 = m15[m15["time"] <= cut_t].reset_index(drop=True)
        sub1 = h1[h1["time"] + pd.Timedelta(hours=1)
                  <= cut_t + pd.Timedelta(minutes=M15_MIN)].reset_index(drop=True)
        pf = build_features(sub15, sub1)
        for k in feat_cols:
            a, b = df[k].iloc[i], pf[k].iloc[len(pf) - 1]
            if pd.isna(a) and pd.isna(b):
                continue
            worst[k] = max(worst[k], abs(float(a) - float(b)))
    exact = all(v == 0.0 for v in worst.values())

    df.to_pickle(out)
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df[feat_cols], index=False).values.tobytes())
    meta = {
        "rows": int(len(df)), "n_features": len(feat_cols), "features": feat_cols,
        "first_utc": df["time"].iloc[0].isoformat(),
        "last_utc": df["time"].iloc[-1].isoformat(),
        "dev_end_boundary": dev_end.isoformat(),
        "oos_isolation": "panel truncated at DEV end before any computation; asserted",
        "feature_eligible": int(df["feature_eligible"].sum()),
        "couples_with_close": sorted(COUPLES_WITH_CLOSE & set(feat_cols)),
        "causality_prefix_test": {"probes": len(probes), "exact": bool(exact),
                                  "max_abs_deviation": {k: float(v) for k, v in worst.items()}},
        "fingerprint_sha256": h.hexdigest(),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in
                      ("rows", "n_features", "feature_eligible", "first_utc",
                       "last_utc", "fingerprint_sha256")}, indent=2))
    print(f"  causal exact: {exact}  worst deviation: {max(worst.values()):.3e}")
    if not exact:
        bad = {k: v for k, v in worst.items() if v > 0}
        raise SystemExit(f"CAUSALITY FAILED: {bad}")


if __name__ == "__main__":
    main()
