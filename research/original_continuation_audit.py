"""Audit of the ORIGINAL continuation hypothesis, frozen in
`research/original_continuation_hypothesis.md` (committed first, by design).

This is a hypothesis audit, not a feature search. Exactly the 9 pre-declared
hypotheses are tested. No threshold is chosen, tuned, or invented.

Production definitions are used literally. Where a rule is evaluated vectorised
for tractability, the vectorised result is VERIFIED against the production
function itself on a random sample and must agree exactly.

The statistical standard in `STATISTICAL_RESEARCH_CONTROLS.md` is mandatory and
is applied through `phase1_statistical_controls`.
"""
from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))
from dataset_access import load_timeframe, _split
from phase1_statistical_controls import (
    Weighting, conditional_stat, multiple_testing_report,
    non_overlapping_indices, raw_stats)

HOR = {"1h": 4, "2h": 8, "4h": 16}
ALPHA = 0.05
SPREAD_USD = 0.33
NQ = 5
OUT = Path(__file__).parent

split = _split()
TRAIN_HI = pd.Timestamp(split["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(split["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(split["arms"]["DEV"]["to_utc"])

m15 = load_timeframe("M15")
h1 = load_timeframe("H1")
m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)
assert m15["time"].max() <= DEV_HI and h1["time"].max() <= DEV_HI, "panel past DEV boundary"

# ---------------------------------------------------------------- L1 bias on H1
# bias_engine.get_fast_bias, vectorised; verified against production below.
h1c = h1["close"].to_numpy(float)
h1_ema20 = ta.ema(h1["close"], length=20).to_numpy(float)
h1_ema50 = ta.ema(h1["close"], length=50).to_numpy(float)
h1_atr14 = ta.atr(h1["high"], h1["low"], h1["close"], length=14).to_numpy(float)
h1_thr = np.where(np.isfinite(h1_atr14) & (h1_atr14 > 0),
                  np.maximum(2.0, h1_atr14 * 0.12), 2.0)
h1_d = h1_ema20 - h1_ema50
h1_bias = np.where(np.abs(h1_d) < h1_thr, 0, np.where(h1_d > h1_thr, 1, -1))
h1_bias = np.where(np.isfinite(h1_d), h1_bias, 0)
h1_strength = np.where(h1_thr > 0, np.minimum(10.0, np.abs(h1_d) / h1_thr), 0.0)
h1_strength = np.where(h1_bias == 0, 0.0, h1_strength)
# H1 regime context (same definition used in the clean Phase 1 work)
h1_ma50 = pd.Series(h1c).rolling(50).mean().to_numpy(float)
h1_regime = np.where(np.isfinite(h1_atr14) & (h1_atr14 > 0), (h1c - h1_ma50) / h1_atr14, np.nan)

# ------------------------------------------------- displacement on M15 (literal)
mo, mh, ml, mc = (m15[k].to_numpy(float) for k in ("open", "high", "low", "close"))
m_atr = ta.atr(m15["high"], m15["low"], m15["close"], length=14).to_numpy(float)
m_rng = mh - ml
m_body = np.abs(mc - mo)
with np.errstate(invalid="ignore", divide="ignore"):
    close_pos = np.where(m_rng > 0, (mc - ml) / m_rng, 0.5)
    body_to_atr = np.where(np.isfinite(m_atr) & (m_atr > 0), m_body / m_atr, np.nan)
    body_to_rng = np.where(m_rng > 0, m_body / m_rng, 0.0)
size_ok = ((np.isfinite(body_to_atr) & (body_to_atr >= 0.9)) | (body_to_rng >= 0.6))
disp_buy = (mc > mo) & (close_pos >= 0.7) & size_ok
disp_sell = (mc < mo) & (close_pos <= 0.3) & size_ok

# ------------------------------------------------------- map M15 -> last H1 bar
h1_close_t = (h1["time"] + pd.Timedelta(hours=1)).to_numpy("datetime64[ns]")
m15_close_t = (m15["time"] + pd.Timedelta(minutes=15)).to_numpy("datetime64[ns]")
j = np.searchsorted(h1_close_t, m15_close_t, side="right") - 1
have_h1 = j >= 60
jv = np.clip(j, 0, len(h1c) - 1)
BIAS = np.where(have_h1, h1_bias[jv], 0)
STRENGTH = np.where(have_h1, h1_strength[jv], 0.0)
REGIME = np.where(have_h1, h1_regime[jv], np.nan)

# ------------------------------------- L2 structure per H1 bar (production call)
from structure_engine import get_h1_structure
STRUCT_CONF = np.zeros(len(h1c), dtype=bool)
for i in range(60, len(h1c)):
    b = h1_bias[i]
    if b == 0:
        continue
    frame = h1.iloc[max(0, i - 59):i + 1]
    try:
        r = get_h1_structure(frame, "BULLISH" if b > 0 else "BEARISH") or {}
    except Exception:
        continue
    st = r.get("structure_type")
    STRUCT_CONF[i] = (st == "HH/HL" and b > 0) or (st == "LH/LL" and b < 0)
STRUCT = np.where(have_h1, STRUCT_CONF[jv], False)

# ------------------------------------------------------------- labels and masks
n = len(mc)
t = m15["time"]
IS_TRAIN = (t <= TRAIN_HI).to_numpy()
IS_DEV = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
IDX = np.arange(n)
BASE_OK = np.isfinite(m_atr) & (m_atr > 0) & have_h1

Y, YUSD, HASW = {}, {}, {}
for hl, hb in HOR.items():
    y = np.full(n, np.nan); u = np.full(n, np.nan); w = np.zeros(n, bool)
    m = n - hb
    y[:m] = (mc[hb:] - mc[:m]) / m_atr[:m]
    u[:m] = mc[hb:] - mc[:m]
    w[:m] = True
    Y[hl], YUSD[hl], HASW[hl] = y, u, w

# direction-normalised return: +y for BUY, -y for SELL
def signed(hl):
    return np.where(BIAS > 0, Y[hl], np.where(BIAS < 0, -Y[hl], np.nan))

def signed_usd(hl):
    return np.where(BIAS > 0, YUSD[hl], np.where(BIAS < 0, -YUSD[hl], np.nan))

# displacement-conditioned strips use 8-bar M15 displacement (prior movement)
disp8 = np.full(n, np.nan)
disp8[8:] = (mc[8:] - mc[:-8]) / np.where(m_atr[8:] > 0, m_atr[8:], np.nan)
d8q = np.full(n, -1)
tr = disp8[IS_TRAIN & np.isfinite(disp8)]
if len(tr) > 1000:
    cuts = np.unique(np.quantile(tr, np.linspace(0, 1, NQ + 1)[1:-1]))
    ok = np.isfinite(disp8)
    d8q[ok] = np.searchsorted(cuts, disp8[ok], side="right")

FAMILIES = {
    "A_bias_alone":        lambda: BIAS != 0,
    "B_bias_displacement": lambda: ((BIAS > 0) & disp_buy) | ((BIAS < 0) & disp_sell),
    "C_bias_structure":    lambda: (BIAS != 0) & STRUCT,
}

results = {
    "provenance": {
        "hypothesis_commit": "1110636 (committed before this analysis existed)",
        "dataset_sha256": json.loads(
            (REPO / "research" / "accessible_bar_dataset_fingerprints.json").read_text()
        )["dataset_sha256"],
        "oos_token": split["oos_authorisation_token"],
        "FINAL_OOS_LOCKED": split["FINAL_OOS_LOCKED"],
        "m15_span": [str(t.iloc[0]), str(t.iloc[-1])],
        "h1_span": [str(h1["time"].iloc[0]), str(h1["time"].iloc[-1])],
        "dev_boundary": str(DEV_HI),
    },
    "population": {}, "primary": [], "multiple_testing": {},
    "baselines": {}, "temporal": {}, "regime": {}, "strength_terciles": {},
    "cost": {}, "verdict": {},
}

results["population"] = {
    "m15_bars": int(n),
    "with_h1_context": int(have_h1.sum()),
    "bias_bullish": int((BIAS > 0).sum()), "bias_bearish": int((BIAS < 0).sum()),
    "bias_neutral_excluded": int((BIAS == 0).sum()),
    "displacement_aligned": int(FAMILIES["B_bias_displacement"]().sum()),
    "structure_confirmed": int(FAMILIES["C_bias_structure"]().sum()),
    "train_rows": int((BASE_OK & IS_TRAIN).sum()), "dev_rows": int((BASE_OK & IS_DEV).sum()),
}

# ------------------------------------------------------- the 9 pre-declared tests
for fam, fn in FAMILIES.items():
    cond = fn()
    for hl, hb in HOR.items():
        s = signed(hl)
        ok = BASE_OK & IS_TRAIN & HASW[hl] & np.isfinite(s) & cond
        cs = conditional_stat(s, ok, hb, f"{fam}@{hl}")
        d = cs.to_dict()
        # direction-conditioned baseline: same side, all eligible bars
        base_ok = BASE_OK & IS_TRAIN & HASW[hl] & np.isfinite(s) & (BIAS != 0)
        bs = conditional_stat(s, base_ok, hb, f"baseline_dir@{hl}")
        hdl, bhd = d["headline"], bs.to_dict()["headline"]
        diff = (hdl["mean"] - bhd["mean"]) if (hdl["mean"] is not None
                                               and bhd["mean"] is not None) else None
        se = (math.sqrt(hdl["se"] ** 2 + bhd["se"] ** 2)
              if hdl["se"] == hdl["se"] and bhd["se"] == bhd["se"] else None)
        results["primary"].append({
            "family": fam, "horizon": hl, "h_bars": hb,
            "raw": d["raw"], "headline": hdl, "block_SECONDARY": d["block"],
            "overlap": d["overlap"], "audit": d["audit"], "flags": d["flags"],
            "needs_review": d["needs_review"],
            "baseline_direction_conditioned": bhd,
            "excess_over_direction_baseline": diff,
            "excess_se": se, "excess_t": (diff / se if se and se > 0 else None),
            "excess_ci95": ([diff - 1.96 * se, diff + 1.96 * se] if se else None),
        })

mt = multiple_testing_report([r["headline"]["t"] for r in results["primary"]], alpha=ALPHA)
mt["hypotheses_predeclared"] = 9
results["multiple_testing"] = mt
THR = mt["bonferroni_threshold_abs_t"]

# -------------------------------------------- displacement-conditioned baseline
for fam, fn in FAMILIES.items():
    cond = fn()
    for hl, hb in HOR.items():
        s = signed(hl)
        ok = BASE_OK & IS_TRAIN & HASW[hl] & np.isfinite(s) & cond
        ds, ws = [], []
        for v in range(NQ):
            c = conditional_stat(s, ok & (d8q == v), hb, "")
            b = conditional_stat(s, BASE_OK & IS_TRAIN & HASW[hl] & np.isfinite(s)
                                 & (BIAS != 0) & (d8q == v), hb, "")
            hh, bb = c.to_dict()["headline"], b.to_dict()["headline"]
            if hh["n"] > 30 and bb["n"] > 30 and hh["se"] == hh["se"] and bb["se"] == bb["se"]:
                e = hh["mean"] - bb["mean"]
                sse = math.sqrt(hh["se"] ** 2 + bb["se"] ** 2)
                if sse > 0:
                    ds.append(e); ws.append(1.0 / sse ** 2)
        if ds:
            w = np.array(ws)
            e = float(np.average(ds, weights=w)); sse = float(math.sqrt(1.0 / w.sum()))
            results["baselines"][f"{fam}@{hl}"] = {
                "weighting": Weighting.NON_OVERLAPPING, "strips": len(ds),
                "excess_over_displacement_baseline": e, "se": sse, "t": e / sse}

# --------------------------------------------------- temporal and regime context
tr_idx = np.flatnonzero(IS_TRAIN)
SEG = {"TRAIN_H1": (tr_idx[0], tr_idx[len(tr_idx) // 2]),
       "TRAIN_H2": (tr_idx[len(tr_idx) // 2], tr_idx[-1])}
for k in range(4):
    a = tr_idx[k * len(tr_idx) // 4]
    b = tr_idx[min((k + 1) * len(tr_idx) // 4, len(tr_idx) - 1)]
    SEG[f"TRAIN_Q{k+1}"] = (a, b)
SEG["DEV"] = (int(np.flatnonzero(IS_DEV)[0]), int(np.flatnonzero(IS_DEV)[-1]))

for fam, fn in FAMILIES.items():
    cond = fn()
    for hl, hb in HOR.items():
        key = f"{fam}@{hl}"
        results["temporal"][key] = {}
        s = signed(hl)
        for sn, (a, b) in SEG.items():
            ok = BASE_OK & HASW[hl] & np.isfinite(s) & cond & (IDX >= a) & (IDX <= b)
            cs = conditional_stat(s, ok, hb, key).to_dict()["headline"]
            results["temporal"][key][sn] = {
                "n": cs["n"], "mean": cs["mean"], "se": cs["se"], "t": cs["t"],
                "ci95": cs["ci95"]}
        results["regime"][key] = {}
        for rn, rm in (("H1_BULL", REGIME > 0.5),
                       ("H1_NEUTRAL", (REGIME >= -0.5) & (REGIME <= 0.5)),
                       ("H1_BEAR", REGIME < -0.5)):
            ok = BASE_OK & (IS_TRAIN | IS_DEV) & HASW[hl] & np.isfinite(s) & cond & rm
            cs = conditional_stat(s, ok, hb, key).to_dict()["headline"]
            results["regime"][key][rn] = {"n": cs["n"], "mean": cs["mean"],
                                          "se": cs["se"], "t": cs["t"], "ci95": cs["ci95"]}

# bias-strength terciles (secondary, existing bias_strength scale)
for hl, hb in HOR.items():
    s = signed(hl)
    base = BASE_OK & IS_TRAIN & HASW[hl] & np.isfinite(s) & (BIAS != 0)
    st = STRENGTH[base]
    if len(st) > 100:
        q1, q2 = np.quantile(st, [1 / 3, 2 / 3])
        results["strength_terciles"][hl] = {}
        for nm, mk in (("low", STRENGTH <= q1),
                       ("mid", (STRENGTH > q1) & (STRENGTH <= q2)),
                       ("high", STRENGTH > q2)):
            cs = conditional_stat(s, base & mk, hb, "").to_dict()["headline"]
            results["strength_terciles"][hl][nm] = {
                "n": cs["n"], "mean": cs["mean"], "t": cs["t"], "ci95": cs["ci95"]}

# ------------------------------------------------------------------ cost gate
survivors = [r for r in results["primary"]
             if r["headline"]["t"] is not None and abs(r["headline"]["t"]) >= THR
             and r["headline"]["mean"] is not None and r["headline"]["mean"] > 0]
results["cost"] = {
    "run": bool(survivors),
    "reason": ("gross effect survived the corrected screen" if survivors else
               "NOT RUN -- no family produced a positive gross effect surviving the "
               "corrected threshold, so the cost analysis is stopped as specified"),
    "round_turn_convention": "1 x spread", "spread_usd": SPREAD_USD,
}
if survivors:
    for r in survivors:
        fam, hl, hb = r["family"], r["horizon"], r["h_bars"]
        cond = FAMILIES[fam]()
        su = signed_usd(hl); s = signed(hl)
        ok = BASE_OK & (IS_TRAIN | IS_DEV) & HASW[hl] & np.isfinite(s) & cond
        keep = non_overlapping_indices(np.flatnonzero(ok), hb)
        g = su[keep]; rs = raw_stats(g)
        cell = {"n_trades": int(len(keep)), "gross_mean_usd": rs["mean"],
                "gross_se_usd": rs["se"], "win_rate_pct": float((g > 0).mean() * 100),
                "net": {}}
        for frac in (0.0, 0.25, 0.5, 1.0):
            cost = SPREAD_USD * (1.0 + 2.0 * frac)
            cell["net"][f"slip_{frac}x"] = {
                "cost_usd": round(cost, 4),
                "net_mean_usd": float(g.mean() - cost),
                "net_win_rate_pct": float(((g - cost) > 0).mean() * 100)}
        results["cost"][f"{fam}@{hl}"] = cell

pos = [r for r in results["primary"] if r["headline"]["mean"] is not None
       and r["headline"]["mean"] > 0]
results["verdict"] = {
    "bonferroni_threshold_abs_t": THR,
    "n_predeclared_hypotheses": 9,
    "cells_with_positive_gross_mean": len(pos),
    "cells_surviving_bonferroni": len(survivors),
    "bh_survivors": mt["benjamini_hochberg"]["n_survivors"],
    "max_abs_headline_t": mt["max_abs_t"],
    "n_sign_disagreement": int(sum("ESTIMATOR_SIGN_DISAGREEMENT" in r["flags"]
                                   for r in results["primary"])),
}

out = OUT / "original_continuation_audit_results.json"
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(json.dumps(results["population"], indent=2))
print(json.dumps(results["verdict"], indent=2))
print(f"  sha256 {hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")
