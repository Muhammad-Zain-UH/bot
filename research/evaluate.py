"""EVALUATE -- joins features and labels on index, aggregates, reports.

The only module that sees both panels. ATR-normalisation happens here.

Independence
------------
Adjacent M5 bars share forward windows, and a sustained-compression setup fires
in runs, so raw N wildly overstates independence. Every inferential number is
computed on NON-OVERLAPPING h-bar blocks: a block contributes one value, the
mean of the candidate observations inside it. The headline comparison is PAIRED
-- candidate block mean vs the same block's all-eligible mean -- so it controls
for when the candidate happened to fire.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

R = Path(__file__).parent
sys.path.insert(0, str(R))
from candidates import candidate_E, E_RATIO_MAX, E_SUSTAIN, E_RANGE_MULT

feats = pd.read_pickle(R / "features.pkl")
labs = pd.read_pickle(R / "labels.pkl")
n = len(feats)
atr = feats["atr_14"].to_numpy(float)
HOR = [(6, "30m"), (12, "1h"), (24, "2h")]

mask_E = candidate_E(feats)

# segments defined on bar index over the whole dataset
seg = {"FULL": np.ones(n, bool),
       "H1": np.arange(n) < n // 2, "H2": np.arange(n) >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (np.arange(n) >= q * n // 4) & (np.arange(n) < (q + 1) * n // 4)
tt = pd.to_datetime(feats["time"], utc=True)
for k in ("H1", "H2", "Q1", "Q2", "Q3", "Q4"):
    m = seg[k]
    seg[k + "_span"] = f"{tt[m].iloc[0]:%Y-%m-%d} -> {tt[m].iloc[-1]:%Y-%m-%d}"


def blocks(values, idx, h):
    """Non-overlapping h-bar block means. Returns (block_ids, block_means)."""
    b = idx // h
    d = pd.DataFrame({"b": b, "v": values}).groupby("b")["v"].mean()
    return d.index.to_numpy(), d.to_numpy()


def stats(h, lab, segment_mask, tag):
    up = labs[f"up_{h}"].to_numpy(float); dn = labs[f"dn_{h}"].to_numpy(float)
    hw = labs[f"has_window_{h}"].to_numpy(bool)
    elig = (feats["feature_eligible"].to_numpy(bool)
            & feats["sustain_available"].to_numpy(bool) & hw
            & np.isfinite(atr) & (atr > 0) & segment_mask)
    cand = elig & mask_E
    if cand.sum() == 0:
        return None
    exc = np.maximum(up, dn) / atr                      # max(|excursion|) in ATR
    idx = np.arange(n)

    # ---- block aggregation ----
    be, me = blocks(exc[elig], idx[elig], h)            # unconditional
    bc, mc = blocks(exc[cand], idx[cand], h)            # candidate
    # paired: candidate block vs the SAME block's all-eligible mean
    common = np.intersect1d(bc, be)
    pc = mc[np.isin(bc, common)]; pe = me[np.isin(be, common)]
    d = pc - pe
    se_paired = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else np.nan
    se_cand = mc.std(ddof=1) / np.sqrt(len(mc)) if len(mc) > 1 else np.nan
    se_unc = me.std(ddof=1) / np.sqrt(len(me)) if len(me) > 1 else np.nan

    # ---- barrier touch, M1-resolved only ----
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    tu = labs[f"t_up_{h}"].to_numpy(float); td = labs[f"t_dn_{h}"].to_numpy(float)
    def touch(m):
        mm = m & m1
        if mm.sum() == 0:
            return dict(n_m1=0)
        u, dd = tu[mm], td[mm]
        either = np.nanmin(np.vstack([u, dd]), axis=0)
        return dict(
            n_m1=int(mm.sum()),
            pct_up=float(np.isfinite(u).mean() * 100),
            pct_dn=float(np.isfinite(dd).mean() * 100),
            pct_either=float(np.isfinite(either).mean() * 100),
            med_up=float(np.nanmedian(u)) if np.isfinite(u).any() else None,
            med_dn=float(np.nanmedian(dd)) if np.isfinite(dd).any() else None,
            med_either=float(np.nanmedian(either)) if np.isfinite(either).any() else None)

    return {
        "tag": tag, "horizon": lab, "h_bars": h,
        "eligible_N": int(elig.sum()), "cand_N": int(cand.sum()),
        "cand_pct": float(cand.sum() / elig.sum() * 100),
        "cand_blocks": int(len(mc)), "elig_blocks": int(len(me)),
        "paired_blocks": int(len(d)),
        "cand_mean": float(exc[cand].mean()), "cand_median": float(np.median(exc[cand])),
        "unc_mean": float(exc[elig].mean()), "unc_median": float(np.median(exc[elig])),
        "mean_uplift": float(exc[cand].mean() - exc[elig].mean()),
        "median_uplift": float(np.median(exc[cand]) - np.median(exc[elig])),
        "block_cand_mean": float(mc.mean()), "block_unc_mean": float(me.mean()),
        "paired_lift": float(d.mean()) if len(d) else None,
        "paired_se": float(se_paired) if np.isfinite(se_paired) else None,
        "paired_mde_2se": float(2 * se_paired) if np.isfinite(se_paired) else None,
        "paired_t": float(d.mean() / se_paired) if np.isfinite(se_paired) and se_paired > 0 else None,
        "se_cand": float(se_cand) if np.isfinite(se_cand) else None,
        "se_unc": float(se_unc) if np.isfinite(se_unc) else None,
        "touch_cand": touch(cand), "touch_unc": touch(elig),
        "gap_pct_cand": float(labs[f"gapped_{h}"].to_numpy(bool)[cand].mean() * 100),
    }


res = {"constants": {"E_RATIO_MAX": E_RATIO_MAX, "E_SUSTAIN": E_SUSTAIN,
                     "E_RANGE_MULT": E_RANGE_MULT},
       "segment_spans": {k: v for k, v in seg.items() if k.endswith("_span")},
       "results": []}
for h, lab in HOR:
    for tag in ("FULL", "H1", "H2", "Q1", "Q2", "Q3", "Q4"):
        r = stats(h, lab, seg[tag], tag)
        if r: res["results"].append(r)

(R / "results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res["constants"]), "\n")
print("segment spans:", json.dumps(res["segment_spans"], indent=2))
print(f"\nCandidate E fires on {int(mask_E.sum())} of {n} M5 bars "
      f"({mask_E.sum()/n*100:.3f}% of all bars)")
