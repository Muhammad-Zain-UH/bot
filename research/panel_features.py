"""PANEL: FEATURES -- PAST/KNOWN INFORMATION ONLY.

Emits one row per M5 bar close. Every column is a causal function of bars <= i.

This module must never import panel_labels, and must never read a bar with
index > i when producing row i. That invariant is not asserted here -- it is
VERIFIED empirically at the bottom of this file by recomputing each feature on
truncated prefixes and requiring exact agreement.

ATR definition
--------------
`pandas_ta.atr(..., length=14)` -- Wilder RMA, identical to the call in
production `indicators.calculate_indicators` (indicators.py:130), and
`atr_average_20 = atr_14.rolling(20, min_periods=5).mean()` (indicators.py:133).

Computed over the FULL frame rather than over production's 100-bar request
window. Both are strictly causal; they differ only in RMA initialisation.
The discrepancy is measured and reported, not assumed away.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np, pandas as pd, pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("features.pkl")
sys.path.insert(0, str(REPO))
from core.types import Timeframe
from data.dataset import load_bars_csv

SUSTAIN = 12          # bars the ratio condition must hold, inclusive of i
RANGE_LOOKBACK = 12   # bars in the high-low range window, inclusive of i


def _causal_features(high, low, close) -> dict[str, np.ndarray]:
    """Every array element i depends only on bars <= i."""
    h, l, c = (pd.Series(x) for x in (high, low, close))
    atr = ta.atr(h, l, c, length=14).to_numpy(float)
    atr_avg = pd.Series(atr).rolling(20, min_periods=5).mean().to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = atr / atr_avg
    # trailing 12-bar high-low range, inclusive of the current bar
    rng = (pd.Series(high).rolling(RANGE_LOOKBACK).max()
           - pd.Series(low).rolling(RANGE_LOOKBACK).min()).to_numpy(float)
    return {"atr_14": atr, "atr_avg_20": atr_avg, "atr_ratio": ratio, "range_12": rng}


BREAKOUT_LOOKBACK = 20   # prior-extreme window, EXCLUSIVE of the breakout bar


def _causal_m15(high, low, close) -> dict[str, np.ndarray]:
    """M15 features. Element i depends only on bars <= i.

    `prior_high`/`prior_low` are shifted by one bar so the extreme a breakout is
    measured against never contains the breakout bar itself -- the brief's
    "computed using only bars available before the breakout close".
    """
    h, l, c = (pd.Series(x) for x in (high, low, close))
    atr = ta.atr(h, l, c, length=14).to_numpy(float)
    prior_high = h.rolling(BREAKOUT_LOOKBACK).max().shift(1).to_numpy(float)
    prior_low = l.rolling(BREAKOUT_LOOKBACK).min().shift(1).to_numpy(float)
    return {"atr_14": atr, "prior_high": prior_high, "prior_low": prior_low}


def _verify_causal(fn, high, low, close, probes, label):
    """Recompute on truncated prefixes; require exact agreement at the cut."""
    full = fn(high, low, close)
    worst = {k: 0.0 for k in full}
    for i in probes:
        pf = fn(high[: i + 1], low[: i + 1], close[: i + 1])
        for k in full:
            a, b = full[k][i], pf[k][i]
            if np.isnan(a) and np.isnan(b):
                continue
            worst[k] = max(worst[k], abs(float(a) - float(b)))
    return full, {"panel": label, "probes": len(probes),
                  "max_abs_deviation": {k: float(v) for k, v in worst.items()},
                  "exact": all(v == 0.0 for v in worst.values())}


def _m15_panel(out_path: Path) -> dict:
    bars = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M15.csv", Timeframe.M15)
    t = pd.to_datetime(bars["time"], utc=True)
    high, low, close = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(bars)
    rng = np.random.default_rng(20260930)
    probes = sorted(rng.choice(np.arange(60, n), size=200, replace=False).tolist())
    f, check = _verify_causal(_causal_m15, high, low, close, probes, "M15")
    df = pd.DataFrame({"idx": np.arange(n), "time": t, "close": close,
                       "high": high, "low": low, **f})
    df["eligible"] = (np.isfinite(f["atr_14"]) & (f["atr_14"] > 0)
                      & np.isfinite(f["prior_high"]) & np.isfinite(f["prior_low"]))
    df.to_pickle(out_path)
    if not check["exact"]:
        raise SystemExit("M15 CAUSALITY VERIFICATION FAILED")
    return {"rows": int(n), "eligible": int(df["eligible"].sum()),
            "causality_prefix_test": check,
            "constants": {"BREAKOUT_LOOKBACK": BREAKOUT_LOOKBACK}}


def main() -> None:
    bars = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M5.csv", Timeframe.M5)
    t = pd.to_datetime(bars["time"], utc=True)
    high, low, close = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(bars)

    f = _causal_features(high, low, close)
    df = pd.DataFrame({"idx": np.arange(n), "time": t, "close": close,
                       "high": high, "low": low, **f})

    # --- feature eligibility: every feature defined, nothing about the future ---
    df["feature_eligible"] = (np.isfinite(f["atr_14"]) & (f["atr_14"] > 0)
                              & np.isfinite(f["atr_avg_20"]) & (f["atr_avg_20"] > 0)
                              & np.isfinite(f["range_12"]))
    # sustained-condition availability needs SUSTAIN-1 prior bars of the ratio
    ok = np.isfinite(f["atr_ratio"])
    sustained_avail = pd.Series(ok).rolling(SUSTAIN).min().to_numpy() == 1.0
    df["sustain_available"] = np.where(np.isnan(sustained_avail), False, sustained_avail)

    # ---------------- CAUSALITY VERIFICATION (prefix test) ----------------
    rng = np.random.default_rng(20260930)
    probes = sorted(rng.choice(np.arange(60, n), size=250, replace=False).tolist())
    worst = {k: 0.0 for k in f}
    for i in probes:
        pf = _causal_features(high[: i + 1], low[: i + 1], close[: i + 1])
        for k in f:
            a, b = f[k][i], pf[k][i]
            if np.isnan(a) and np.isnan(b):
                continue
            worst[k] = max(worst[k], abs(float(a) - float(b)))
    causal_ok = all(v == 0.0 for v in worst.values())

    # ------- production-window comparison: RMA init over 100 bars, not all -------
    diffs = []
    for i in probes:
        if i < 100:
            continue
        s = slice(i - 99, i + 1)                       # exactly production's request
        pf = _causal_features(high[s], low[s], close[s])
        if np.isfinite(pf["atr_14"][-1]) and np.isfinite(f["atr_14"][i]):
            diffs.append(abs(pf["atr_14"][-1] - f["atr_14"][i]) / f["atr_14"][i])
    diffs = np.array(diffs)

    meta = {
        "rows": int(n),
        "feature_eligible": int(df["feature_eligible"].sum()),
        "sustain_available": int(df["sustain_available"].sum()),
        "first_eligible_idx": int(np.argmax(df["feature_eligible"].to_numpy())),
        "causality_prefix_test": {
            "probes": len(probes),
            "max_abs_deviation": {k: float(v) for k, v in worst.items()},
            "exact": bool(causal_ok),
        },
        "production_window_atr_discrepancy": {
            "probes": int(len(diffs)),
            "median_rel": float(np.median(diffs)) if len(diffs) else None,
            "p95_rel": float(np.percentile(diffs, 95)) if len(diffs) else None,
            "max_rel": float(diffs.max()) if len(diffs) else None,
        },
        "constants": {"SUSTAIN": SUSTAIN, "RANGE_LOOKBACK": RANGE_LOOKBACK},
    }
    m15_out = OUT.with_name(OUT.stem + "_m15" + OUT.suffix)
    meta["m15_panel"] = _m15_panel(m15_out)
    df.to_pickle(OUT)
    OUT.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    if not causal_ok:
        raise SystemExit("CAUSALITY VERIFICATION FAILED -- features saw future bars")


if __name__ == "__main__":
    main()
