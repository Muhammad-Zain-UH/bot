"""PHASE 1 STRUCTURE SCAN -- conditional structure, with controls.

Discipline
----------
* Quintile cutoffs are derived from **TRAIN ONLY** and applied unchanged to DEV.
  The previous programme computed cutoffs over the whole sample; acceptable for
  exploration, not for this.
* DEV is used **only to replicate** a TRAIN finding, never to discover one.
* FINAL_OOS is never touched: the panels stop at the DEV boundary.
* Inference uses **non-overlapping h-bar blocks**; raw N is reported but never
  used for a standard error.
* The primary statistic is the **Q5 - Q1 spread**, which is the correct test for a
  monotonic relationship. Per-quintile cells are reported for shape.

Controls applied to every candidate that clears the screen
----------------------------------------------------------
1. reference-price sensitivity   label measured from mid[i] instead of close[i]
2. delayed entry                 origin close[i+1] and close[i+2]
3. displacement-conditioned      spread recomputed within disp_8 quintile strips
4. volatility-conditioned        spread recomputed within atr_ratio strips
5. temporal stability            TRAIN halves and quarters
6. TRAIN -> DEV replication      sign and magnitude must carry
7. block-shift null              feature circularly shifted to break the
                                 feature/label link while preserving each
                                 series' own autocorrelation

Classification: A robust / B weak / C coupling artifact / D explained by another
family / E insufficient evidence.
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
from dataset_access import _split
from phase1_feature_panel import COUPLES_WITH_CLOSE

HOR = {"1h": 4, "2h": 8, "4h": 16}
NQ = 5
SEED = 20261002
NULL_SHIFTS = 50
SCREEN_T = 2.5          # pre-declared screen on the TRAIN spread |t|

P1 = Path(__file__).parent / "phase1"
feats = pd.read_pickle(P1 / "features.pkl")
labs = pd.read_pickle(P1 / "labels.pkl")
split = _split()
TRAIN_HI = pd.Timestamp(split["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(split["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(split["arms"]["DEV"]["to_utc"])

t = feats["time"]
IS_TRAIN = (t <= TRAIN_HI).to_numpy()
IS_DEV = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
ELIG = feats["feature_eligible"].to_numpy(bool)
IDX = feats["idx"].to_numpy()
FEATURES = [c for c in feats.columns
            if c not in ("idx", "time", "close", "high", "low", "open", "atr",
                         "feature_eligible")]
COND_DISP = feats["disp_8"].to_numpy(float)
COND_VOL = feats["atr_ratio"].to_numpy(float)



def _norm_sf(z: float) -> float:
    """Two-sided normal tail, erfc via math -- no scipy dependency."""
    import math
    return math.erfc(abs(z) / math.sqrt(2.0))


def bonferroni_t(n_tests: int, alpha: float = 0.05) -> float:
    """Smallest |t| whose two-sided p-value is <= alpha/n_tests."""
    target = alpha / max(n_tests, 1)
    lo, hi = 0.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _norm_sf(mid) > target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 3)


def qcut_from_train(x: np.ndarray, train_mask: np.ndarray) -> tuple[np.ndarray, list]:
    """Cutoffs from TRAIN only; applied everywhere."""
    tr = x[train_mask & np.isfinite(x)]
    if len(tr) < 1000:
        return np.full(len(x), -1), []
    qs = np.quantile(tr, np.linspace(0, 1, NQ + 1)[1:-1])
    qs = np.unique(qs)
    if len(qs) < NQ - 1:
        return np.full(len(x), -1), list(map(float, qs))
    b = np.full(len(x), -1)
    ok = np.isfinite(x)
    b[ok] = np.searchsorted(qs, x[ok], side="right")
    return b, list(map(float, qs))


def block_mean_se(v: np.ndarray, pos: np.ndarray, h: int):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    if len(bm) < 2:
        return np.nan, np.nan, len(bm)
    return float(bm.mean()), float(bm.std(ddof=1) / np.sqrt(len(bm))), int(len(bm))


def spread(y: np.ndarray, ok: np.ndarray, q: np.ndarray, h: int):
    lo, hi = ok & (q == 0), ok & (q == NQ - 1)
    if lo.sum() < 50 or hi.sum() < 50:
        return None
    ml, sl, nl = block_mean_se(y[lo], IDX[lo], h)
    mh, sh, nh = block_mean_se(y[hi], IDX[hi], h)
    if not (np.isfinite(sl) and np.isfinite(sh)):
        return None
    sp = mh - ml
    se = float(np.sqrt(sl ** 2 + sh ** 2))
    return {"spread": sp, "se": se, "t": (sp / se if se > 0 else np.nan),
            "n_lo": int(lo.sum()), "n_hi": int(hi.sum()),
            "blocks_lo": nl, "blocks_hi": nh,
            "ci95": [sp - 1.96 * se, sp + 1.96 * se]}


def strip_spread(y, ok, q, h, cond):
    """Spread recomputed WITHIN strips of `cond`, inverse-variance pooled."""
    cq, _ = qcut_from_train(cond, IS_TRAIN)
    ds, ws = [], []
    for v in range(NQ):
        s = spread(y, ok & (cq == v), q, h)
        if s and s["se"] > 0:
            ds.append(s["spread"])
            ws.append(1.0 / s["se"] ** 2)
    if not ds:
        return None
    w = np.array(ws)
    d = float(np.average(ds, weights=w))
    se = float(np.sqrt(1.0 / w.sum()))
    return {"spread": d, "se": se, "t": d / se, "strips_used": len(ds)}


def label(kind: str, hl: str) -> np.ndarray:
    return labs[f"ret_atr_{kind}_{hl}"].to_numpy(float)


def ok_mask(hl: str, arm: np.ndarray, y: np.ndarray) -> np.ndarray:
    return ELIG & arm & labs[f"has_window_{hl}"].to_numpy(bool) & np.isfinite(y)


# ----------------------------------------------------------------- main screen
results = {"meta": {}, "screen": [], "controls": {}, "classification": {}}
cells = 0
for f in FEATURES:
    x = feats[f].to_numpy(float)
    q, cuts = qcut_from_train(x, IS_TRAIN)
    if (q >= 0).sum() == 0:
        continue
    for hl, hb in HOR.items():
        y = label("d0", hl)
        okT = ok_mask(hl, IS_TRAIN, y)
        s = spread(y, okT, q, hb)
        if s is None:
            continue
        cells += 1
        # per-quintile shape, vs the unconditional arm mean
        base_mean, base_se, base_blk = block_mean_se(y[okT], IDX[okT], hb)
        shape = []
        for b in range(NQ):
            m = okT & (q == b)
            if m.sum() < 50:
                shape.append(None); continue
            mm, ss, nb = block_mean_se(y[m], IDX[m], hb)
            shape.append({"q": b + 1, "n": int(m.sum()), "blocks": nb,
                          "mean": mm, "se": ss,
                          "diff_vs_uncond": mm - base_mean,
                          "hit_pct": float((y[m] > 0).mean() * 100)})
        results["screen"].append({
            "feature": f, "horizon": hl, "h_bars": hb,
            "couples_with_close": f in COUPLES_WITH_CLOSE,
            "train_cutoffs": cuts, **s,
            "uncond_mean": base_mean, "uncond_se": base_se, "uncond_blocks": base_blk,
            "shape": shape})

scr = pd.DataFrame([{k: v for k, v in r.items() if k != "shape"}
                    for r in results["screen"]])
scr["abs_t"] = scr["t"].abs()
results["meta"] = {
    "bonferroni_t_alpha05": bonferroni_t(cells),
    "cells_tested_train": int(cells),
    "features": len(FEATURES), "horizons": list(HOR),
    "screen_threshold_abs_t": SCREEN_T,
    "expected_abs_t_ge_2_under_null": round(cells * 0.0455, 1),
    "expected_abs_t_ge_2_5_under_null": round(cells * 0.0124, 1),
    "expected_abs_t_ge_3_under_null": round(cells * 0.0027, 1),
    "observed_abs_t_ge_2": int((scr.abs_t >= 2).sum()),
    "observed_abs_t_ge_2_5": int((scr.abs_t >= 2.5).sum()),
    "observed_abs_t_ge_3": int((scr.abs_t >= 3).sum()),
    "max_abs_t": float(scr.abs_t.max()),
    # Bonferroni threshold without scipy: invert the normal tail by bisection.
    "bonferroni_alpha05_t": None,
    "train_rows": int((ELIG & IS_TRAIN).sum()),
    "dev_rows": int((ELIG & IS_DEV).sum()),
}

# ------------------------------------------------------- controls on survivors
survivors = scr[scr.abs_t >= SCREEN_T].sort_values("abs_t", ascending=False)
rng = np.random.default_rng(SEED)
for _, row in survivors.iterrows():
    f, hl, hb = row["feature"], row["horizon"], int(row["h_bars"])
    key = f"{f}@{hl}"
    x = feats[f].to_numpy(float)
    q, _ = qcut_from_train(x, IS_TRAIN)
    y0 = label("d0", hl)
    okT = ok_mask(hl, IS_TRAIN, y0)
    ctrl = {"train": {k: row[k] for k in ("spread", "se", "t", "n_lo", "n_hi")}}

    # 1 reference price
    ym = label("mid", hl)
    ctrl["ref_mid"] = spread(ym, ok_mask(hl, IS_TRAIN, ym), q, hb)
    # 2 delayed entry
    for d in (1, 2):
        yd = label(f"d{d}", hl)
        ctrl[f"delay_{d}"] = spread(yd, ok_mask(hl, IS_TRAIN, yd), q, hb)
    # 3 displacement-conditioned
    ctrl["cond_disp"] = strip_spread(y0, okT, q, hb, COND_DISP)
    # 4 volatility-conditioned
    ctrl["cond_vol"] = strip_spread(y0, okT, q, hb, COND_VOL)
    # 5 temporal stability within TRAIN
    tr_idx = np.flatnonzero(IS_TRAIN)
    halves = {}
    mid_i = tr_idx[len(tr_idx) // 2]
    halves["TRAIN_H1"] = spread(y0, okT & (IDX <= mid_i), q, hb)
    halves["TRAIN_H2"] = spread(y0, okT & (IDX > mid_i), q, hb)
    for k in range(4):
        a = tr_idx[k * len(tr_idx) // 4]
        b = tr_idx[min((k + 1) * len(tr_idx) // 4, len(tr_idx) - 1)]
        halves[f"TRAIN_Q{k+1}"] = spread(y0, okT & (IDX >= a) & (IDX <= b), q, hb)
    ctrl["temporal"] = halves
    # 6 DEV replication
    ctrl["dev"] = spread(y0, ok_mask(hl, IS_DEV, y0), q, hb)
    # 7 block-shift null
    nulls = []
    nz = len(x)
    for _ in range(NULL_SHIFTS):
        sh = int(rng.integers(nz // 10, nz - nz // 10))
        qs = np.roll(q, sh)
        s = spread(y0, okT, qs, hb)
        if s and np.isfinite(s["t"]):
            nulls.append(s["t"])
    ctrl["null_block_shift"] = {
        "shifts": len(nulls),
        "mean_t": float(np.mean(nulls)) if nulls else None,
        "sd_t": float(np.std(nulls, ddof=1)) if len(nulls) > 1 else None,
        "max_abs_t": float(np.max(np.abs(nulls))) if nulls else None,
        "p_exceed": (float(np.mean(np.abs(nulls) >= abs(row["t"]))) if nulls else None)}
    results["controls"][key] = ctrl

out = P1 / "structure_results.json"
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
h = hashlib.sha256(out.read_bytes()).hexdigest()
(P1 / "structure_results.sha256").write_text(h, encoding="utf-8")
print(json.dumps(results["meta"], indent=2))
print(f"\n  survivors at |t| >= {SCREEN_T}: {len(survivors)}")
for _, r in survivors.head(15).iterrows():
    print(f"    {r['feature']:<24} {r['horizon']:>3}  spread={r['spread']:>8.4f}  "
          f"t={r['t']:>7.2f}  couples={bool(r['couples_with_close'])}")
print(f"\n  results sha256 {h}")
