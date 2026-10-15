"""CLEAN PHASE 1 -- conditional structure discovery, rerun from scratch.

Nothing is imported from the retracted Phase 1 results: no rankings, no survivor
list, no rejection classifications. Only the feature DEFINITIONS are reused, and
those were never in question -- the failure was in the estimator.

Every statistic goes through `phase1_statistical_controls`, so:
  * the headline is NON-OVERLAPPING by construction,
  * block statistics are secondary and always carry their weighting,
  * sign disagreement between estimators raises a flag,
  * overlap ratios and forward-window audits are attached to every cell.

Validation chain a feature must survive to be called a candidate:
  1. headline (non-overlapping) |t| above the Bonferroni threshold on TRAIN
  2. not mechanically coupled to the label (Part C)
  3. survives the displacement-conditioned control
  4. survives the volatility-conditioned control
  5. survives the reference-price control (label measured from mid[i])
  6. survives the delayed-entry control (origin close[i+1])
  7. replicates in DEV with the same sign
  8. gross hypothetical trade return positive BEFORE costs

`|t| > 2` is not a qualification.
"""
from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))
from dataset_access import _split
from phase1_feature_panel import COUPLES_WITH_CLOSE
from phase1_statistical_controls import (
    Weighting, conditional_stat, contrast, multiple_testing_report,
    non_overlapping_indices, bonferroni_t, raw_stats)

NQ = 5
ALPHA = 0.05
HOR = {"1h": 4, "2h": 8, "4h": 16}
SPREAD_USD = 0.33           # measured median; round-turn = 1 x spread
P1 = Path(__file__).parent / "phase1"

feats = pd.read_pickle(P1 / "features.pkl")
labs = pd.read_pickle(P1 / "labels.pkl")
split = _split()
TRAIN_HI = pd.Timestamp(split["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(split["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(split["arms"]["DEV"]["to_utc"])

t = feats["time"]
assert t.max() <= DEV_HI, "panel extends past the DEV boundary"
IS_TRAIN = (t <= TRAIN_HI).to_numpy()
IS_DEV = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
ELIG = feats["feature_eligible"].to_numpy(bool)
IDX = feats["idx"].to_numpy()
close = feats["close"].to_numpy(float)
atr = feats["atr"].to_numpy(float)

FEATURES = [c for c in feats.columns
            if c not in ("idx", "time", "close", "high", "low", "open", "atr",
                         "feature_eligible")]
COND_DISP = feats["disp_8"].to_numpy(float)
COND_VOL = feats["atr_ratio"].to_numpy(float)
H1_TREND = feats["h1_trend"].to_numpy(float)


def qcut_train(x):
    tr = x[IS_TRAIN & np.isfinite(x)]
    if len(tr) < 1000:
        return np.full(len(x), -1), []
    cuts = np.unique(np.quantile(tr, np.linspace(0, 1, NQ + 1)[1:-1]))
    if len(cuts) < NQ - 1:
        return np.full(len(x), -1), [float(v) for v in cuts]
    b = np.full(len(x), -1)
    ok = np.isfinite(x)
    b[ok] = np.searchsorted(cuts, x[ok], side="right")
    return b, [float(v) for v in cuts]


def y_of(kind, hl):
    return labs[f"ret_atr_{kind}_{hl}"].to_numpy(float)


def ok_of(hl, arm, y):
    return ELIG & arm & labs[f"has_window_{hl}"].to_numpy(bool) & np.isfinite(y)


results = {
    "provenance": {
        "dataset_sha256": json.loads(
            (REPO / "research" / "accessible_bar_dataset_fingerprints.json").read_text()
        )["dataset_sha256"],
        "oos_token": split["oos_authorisation_token"],
        "FINAL_OOS_LOCKED": split["FINAL_OOS_LOCKED"],
        "panel_last_utc": str(t.max()), "dev_boundary": str(DEV_HI),
        "train_rows_eligible": int((ELIG & IS_TRAIN).sum()),
        "dev_rows_eligible": int((ELIG & IS_DEV).sum()),
        "retracted_phase1_imported": False,
    },
    "part_c_excluded_by_construction": sorted(COUPLES_WITH_CLOSE & set(FEATURES)),
    "screen": [], "multiple_testing": {}, "candidates": {}, "verdict": {},
}

# ============================ PART B/C -- primary screen on TRAIN, non-overlapping
eligible_features = [f for f in FEATURES if f not in COUPLES_WITH_CLOSE]
rows = []
for f in eligible_features:
    x = feats[f].to_numpy(float)
    q, cuts = qcut_train(x)
    if (q >= 0).sum() == 0:
        continue
    for hl, hb in HOR.items():
        y = y_of("d0", hl)
        ok = ok_of(hl, IS_TRAIN, y)
        c = contrast(y, ok & (q == NQ - 1), ok & (q == 0), hb, f"{f}@{hl}")
        if c["headline_diff"] is None:
            continue
        hd = c["headline_diff"]
        rows.append({
            "feature": f, "horizon": hl, "h_bars": hb, "train_cutoffs": cuts,
            "headline_diff": hd["diff"], "headline_se": hd["se"], "headline_t": hd["t"],
            "headline_ci95": hd["ci95"], "headline_p": hd["p_two_sided"],
            "n_hi_nonoverlap": hd["n_hi"], "n_lo_nonoverlap": hd["n_lo"],
            "raw_n_hi": c["hi"]["overlap"]["raw_observations"],
            "raw_n_lo": c["lo"]["overlap"]["raw_observations"],
            "overlap_ratio_hi": c["hi"]["overlap"]["overlap_ratio"],
            "raw_diff_overlapping": (c.get("raw_diff_OVERLAPPING") or {}).get("diff"),
            "block_diff_secondary": (c.get("block_diff_SECONDARY") or {}).get("diff"),
            "block_t_secondary": (c.get("block_diff_SECONDARY") or {}).get("t"),
            "flags": c["flags"], "needs_review": c["needs_review"],
            "weighting": Weighting.NON_OVERLAPPING,
        })
results["screen"] = rows

mt = multiple_testing_report([r["headline_t"] for r in rows], alpha=ALPHA)
mt["features_tested"] = len(eligible_features)
mt["features_excluded_part_c"] = len(results["part_c_excluded_by_construction"])
mt["horizons"] = list(HOR)
results["multiple_testing"] = mt
THR = mt["bonferroni_threshold_abs_t"]

survivors = [r for r in rows if r["headline_t"] is not None and abs(r["headline_t"]) >= THR]

# ========================== controls for anything clearing the corrected threshold
def strip_contrast(y, ok, q, hb, cond, label):
    cq, _ = qcut_train(cond)
    ds, ws = [], []
    for v in range(NQ):
        c = contrast(y, ok & (cq == v) & (q == NQ - 1), ok & (cq == v) & (q == 0),
                     hb, label)
        hd = c["headline_diff"]
        if hd and hd["se"] and hd["se"] > 0:
            ds.append(hd["diff"]); ws.append(1.0 / hd["se"] ** 2)
    if not ds:
        return None
    w = np.array(ws)
    d = float(np.average(ds, weights=w))
    se = float(math.sqrt(1.0 / w.sum()))
    return {"weighting": Weighting.NON_OVERLAPPING, "diff": d, "se": se,
            "t": d / se, "strips": len(ds)}


for r in survivors:
    f, hl, hb = r["feature"], r["horizon"], r["h_bars"]
    key = f"{f}@{hl}"
    x = feats[f].to_numpy(float)
    q, _ = qcut_train(x)
    y0 = y_of("d0", hl)
    okT = ok_of(hl, IS_TRAIN, y0)
    ctrl = {"train_headline": {k: r[k] for k in
                               ("headline_diff", "headline_se", "headline_t", "headline_ci95")}}
    ym = y_of("mid", hl)
    cm = contrast(ym, ok_of(hl, IS_TRAIN, ym) & (q == NQ - 1),
                  ok_of(hl, IS_TRAIN, ym) & (q == 0), hb, key)
    ctrl["ref_mid"] = cm["headline_diff"]
    yd = y_of("d1", hl)
    cd = contrast(yd, ok_of(hl, IS_TRAIN, yd) & (q == NQ - 1),
                  ok_of(hl, IS_TRAIN, yd) & (q == 0), hb, key)
    ctrl["delay_1"] = cd["headline_diff"]
    ctrl["cond_displacement"] = strip_contrast(y0, okT, q, hb, COND_DISP, key)
    ctrl["cond_volatility"] = strip_contrast(y0, okT, q, hb, COND_VOL, key)
    okD = ok_of(hl, IS_DEV, y0)
    cdev = contrast(y0, okD & (q == NQ - 1), okD & (q == 0), hb, key)
    ctrl["dev_replication"] = cdev["headline_diff"]
    results["candidates"][key] = ctrl

# ================================================ PART F -- gross-return screen
def gross_screen(f, hl, hb):
    x = feats[f].to_numpy(float)
    q, _ = qcut_train(x)
    y = y_of("d0", hl)
    ok = ok_of(hl, IS_TRAIN | IS_DEV, y) & ((q == 0) | (q == NQ - 1))
    keep = non_overlapping_indices(np.flatnonzero(ok), hb)
    if len(keep) < 50:
        return {"n": int(len(keep)), "status": "insufficient"}
    side = np.where(q[keep] == 0, 1.0, -1.0)      # opposite the feature's sign
    g_atr = side * y[keep]
    g_usd = side * (close[np.minimum(keep + hb, len(close) - 1)] - close[keep])
    rs = raw_stats(g_atr)
    cost = SPREAD_USD                              # round turn = 1 x spread
    return {"n_non_overlapping_trades": int(len(keep)),
            "weighting": Weighting.NON_OVERLAPPING,
            "gross_mean_atr": rs["mean"], "gross_median_atr": rs["median"],
            "gross_se_atr": rs["se"], "gross_t": (rs["mean"] / rs["se"] if rs["se"] else None),
            "gross_mean_usd": float(g_usd.mean()),
            "win_rate_pct": float((g_atr > 0).mean() * 100),
            "round_turn_cost_usd": cost,
            "gross_positive_before_costs": bool(rs["mean"] is not None and rs["mean"] > 0),
            "note": ("if gross is not positive before costs the candidate fails at the "
                     "gross stage and no cost optimisation is performed")}


for key in list(results["candidates"]):
    f, hl = key.split("@")
    results["candidates"][key]["gross_screen"] = gross_screen(f, hl, HOR[hl])

results["verdict"] = {
    "bonferroni_threshold_abs_t": THR,
    "n_hypotheses": mt["n_hypotheses"],
    "observed_abs_t_ge_2": mt["observed_abs_t_ge_2"],
    "expected_abs_t_ge_2_under_null": mt["expected_abs_t_ge_2_under_null"],
    "bonferroni_survivors": len(survivors),
    "bh_survivors": mt["benjamini_hochberg"]["n_survivors"],
    "max_abs_headline_t": mt["max_abs_t"],
    "n_sign_disagreement_flags": int(sum(
        "ESTIMATOR_SIGN_DISAGREEMENT" in r["flags"] for r in rows)),
}

out = Path(__file__).parent / "phase1_clean_results.json"
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(json.dumps(results["verdict"], indent=2))
print(f"\n  part C excluded by construction: {results['part_c_excluded_by_construction']}")
print(f"  results sha256 {hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")
top = sorted(rows, key=lambda r: -abs(r["headline_t"] or 0))[:12]
print(f"\n  {'feature':<24} {'hor':>4} {'diff':>9} {'se':>7} {'t':>7} {'n_hi/n_lo':>13} {'ovl':>6} flags")
for r in top:
    print(f"  {r['feature']:<24} {r['horizon']:>4} {r['headline_diff']:>9.4f} "
          f"{r['headline_se']:>7.4f} {r['headline_t']:>7.2f} "
          f"{r['n_hi_nonoverlap']:>6}/{r['n_lo_nonoverlap']:<6} "
          f"{r['overlap_ratio_hi']:>6.1f} {','.join(r['flags']) or '-'}")
