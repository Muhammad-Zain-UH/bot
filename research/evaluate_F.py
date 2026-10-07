"""EVALUATE -- Candidate F: momentum exhaustion -> reversal.

Same methodology as evaluate_B / evaluate_D: every candidate number sits beside
a DRIFT-MATCHED baseline (same horizon, same segment, same side) computed over
all eligible M5 bars, and inference uses non-overlapping h-bar blocks.

Adds the immediate-reversal diagnostic the brief asks for: 5m and 15m alongside
the primary horizons, so it is visible whether reversal starts at once or only
appears once the window is long enough to contain unrelated movement.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).parent
sys.path.insert(0, str(R))

V = Path(sys.argv[1])
DIAG = [(1, "5m"), (3, "15m"), (6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")]
PRIMARY = {"30m", "1h", "2h"}

m5 = pd.read_pickle(V / "features.pkl")
labs = pd.read_pickle(V / "labels.pkl")
ev = pd.read_pickle(V / "events_F.pkl")
n = len(m5)
atr = m5["atr_14"].to_numpy(float)
cl = m5["close"].to_numpy(float)
idx = np.arange(n)

seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)

POS = ev["m5_idx"].to_numpy(int)
SIDE = ev["side"].to_numpy()
# One event rests on an M15 RSI computed during warmup (pandas_ta.rsi emits
# values from index 1, not 14). Reported both ways, never silently dropped.
WARM = ~np.isfinite(ev["atr15"].to_numpy(float))
CACHE = {}


def fwd(h):
    if h in CACHE:
        return CACHE[h]
    up = labs[f"up_{h}"].to_numpy(float) / atr
    dn = labs[f"dn_{h}"].to_numpy(float) / atr
    r = np.full(n, np.nan)
    m = n - h
    r[:m] = (cl[h:][:m] - cl[:m]) / atr[:m]
    ok = (m5["feature_eligible"].to_numpy(bool) & labs[f"has_window_{h}"].to_numpy(bool)
          & np.isfinite(atr) & (atr > 0) & np.isfinite(r))
    CACHE[h] = (r, up, dn, ok)
    return CACHE[h]


def sided(s, r, up, dn):
    return (r, up, dn) if s == "BUY" else (-r, dn, up)


def block_se(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    return len(bm), (float(bm.std(ddof=1) / np.sqrt(len(bm))) if len(bm) > 1 else None)


def race_stats(h, pos, sides):
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    tu, td = labs[f"t_up_{h}"].to_numpy(float), labs[f"t_dn_{h}"].to_numpy(float)
    k = m1[pos]
    pos, sides = pos[k], sides[k]
    if not len(pos):
        return None
    fav = np.where(sides == "BUY", tu[pos], td[pos])
    adv = np.where(sides == "BUY", td[pos], tu[pos])
    fo, ao = np.isfinite(fav), np.isfinite(adv)
    ff = (fo & ~ao) | (fo & ao & (fav < adv))
    aa = (ao & ~fo) | (fo & ao & (adv < fav))
    res = int((ff | aa).sum())
    return {"n": int(len(pos)), "resolved": res,
            "fav_first_pct": float(ff.sum() / res * 100) if res else None,
            "med_t_fav": float(np.nanmedian(fav)) if fo.any() else None,
            "med_t_adv": float(np.nanmedian(adv)) if ao.any() else None}


def race_base(h, mask, sides):
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    tu, td = labs[f"t_up_{h}"].to_numpy(float), labs[f"t_dn_{h}"].to_numpy(float)
    _, _, _, ok = fwd(h)
    m = ok & m1 & mask
    u, d = tu[m], td[m]
    uo, do = np.isfinite(u), np.isfinite(d)
    upf = (uo & ~do) | (uo & do & (u < d))
    dnf = (do & ~uo) | (uo & do & (d < u))
    res = (upf | dnf).sum()
    if not res:
        return None
    w = {s: float((sides == s).mean()) for s in ("BUY", "SELL")}
    return float(w["BUY"] * upf.sum() / res * 100 + w["SELL"] * dnf.sum() / res * 100)


def run(h, lab, tag, sf, drop_warmup):
    r, up, dn, ok = fwd(h)
    pick = np.ones(len(POS), bool) if sf is None else (SIDE == sf)
    if drop_warmup:
        pick = pick & ~WARM
    m = ok[POS] & seg[tag][POS] & pick
    pos, sides = POS[m], SIDE[m]
    if len(pos) < 2:
        return None
    comp = {s: sided(s, r, up, dn) for s in ("BUY", "SELL")}
    cr = np.array([comp[s][0][p] for p, s in zip(pos, sides)])
    cm = np.array([comp[s][1][p] for p, s in zip(pos, sides)])
    ca = np.array([comp[s][2][p] for p, s in zip(pos, sides)])
    bl = ok & seg[tag]
    w = {s: float((sides == s).mean()) for s in ("BUY", "SELL")}
    bmean = sum(w[s] * comp[s][0][bl].mean() for s in w if w[s] > 0)
    bmed = sum(w[s] * np.median(comp[s][0][bl]) for s in w if w[s] > 0)
    bmfe = sum(w[s] * np.median(comp[s][1][bl]) for s in w if w[s] > 0)
    bmae = sum(w[s] * np.median(comp[s][2][bl]) for s in w if w[s] > 0)
    bhit = sum(w[s] * float((comp[s][0][bl] > 0).mean()) for s in w if w[s] > 0)
    nb, se_c = block_se(cr, pos, h)
    _, se_b = block_se(comp["BUY"][0][bl], idx[bl], h)
    sed = float(np.sqrt((se_c or 0) ** 2 + (se_b or 0) ** 2)) if se_c else None
    d = float(cr.mean() - bmean)
    rs = race_stats(h, pos, sides)
    rb = race_base(h, seg[tag], sides)
    return {
        "horizon": lab, "h": h, "segment": tag, "side": sf or "ALL",
        "drop_warmup": drop_warmup,
        "events": int(len(pos)), "blocks": int(nb),
        "cand_ret_mean": float(cr.mean()), "cand_ret_median": float(np.median(cr)),
        "cand_mfe_median": float(np.median(cm)), "cand_mae_median": float(np.median(ca)),
        "cand_hit_pct": float((cr > 0).mean() * 100),
        "base_ret_mean": float(bmean), "base_ret_median": float(bmed),
        "base_mfe_median": float(bmfe), "base_mae_median": float(bmae),
        "base_hit_pct": float(bhit * 100),
        "diff_ret_mean": d, "diff_ret_median": float(np.median(cr) - bmed),
        "diff_hit_pp": float((cr > 0).mean() * 100 - bhit * 100),
        "se_diff": sed, "t_stat": float(d / sed) if sed else None,
        "mde_2se": float(2 * sed) if sed else None,
        "race": rs, "race_base_pct": rb,
        "race_diff_pp": (float(rs["fav_first_pct"] - rb)
                         if rs and rb and rs.get("fav_first_pct") is not None else None),
        "gap_pct": float(labs[f"gapped_{h}"].to_numpy(bool)[pos].mean() * 100),
        "m1_cov_pct": float(labs[f"m1_ok_{h}"].to_numpy(bool)[pos].mean() * 100),
    }


rows = []
for h, lab in DIAG:
    for tag in ("FULL", "H1", "H2", "Q1", "Q2", "Q3", "Q4"):
        for sf in (None, "BUY", "SELL"):
            for dw in (False, True):
                if tag != "FULL" and dw:
                    continue
                res = run(h, lab, tag, sf, dw)
                if res:
                    rows.append(res)

(V / "results_F.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"wrote {len(rows)} rows")
