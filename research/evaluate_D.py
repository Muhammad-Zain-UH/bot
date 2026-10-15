"""EVALUATE -- Candidate D: false breakout -> reclaim -> reversal.

Same methodology as evaluate_B: every candidate number sits beside a
DRIFT-MATCHED baseline (same horizon, same segment, same side) over all
eligible M5 bars, and inference uses non-overlapping h-bar blocks.

Adds the range-target diagnostic the hypothesis names explicitly: does price
actually travel to the OPPOSITE side of the prior 20-bar range? That target is
event-specific, so its baseline is matched per event -- for each event's
required distance d, the unconditional probability of a favourable excursion
>= d over the same eligible population and side.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).parent
sys.path.insert(0, str(R))
REPO = R.parent
sys.path.insert(0, str(REPO))
from panel_labels import first_touch_m1
from core.types import Timeframe
from data.dataset import load_bars_csv

V = Path(sys.argv[1])
HOR = [(6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")]

m5 = pd.read_pickle(V / "features.pkl")
labs = pd.read_pickle(V / "labels.pkl")
ev = pd.read_pickle(V / "events_D.pkl")
n = len(m5)
atr = m5["atr_14"].to_numpy(float)
cl = m5["close"].to_numpy(float)
idx = np.arange(n)
seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)

POS = ev["m5_idx"].to_numpy(int)
SIDE = ev["side"].to_numpy()
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
            "med_t_fav": float(np.nanmedian(fav)) if fo.any() else None}


def race_base(h, mask, sides):
    """Drift-matched race baseline, weighted to the candidate's side mix."""
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


rows = []
for h, lab in HOR:
    r, up, dn, ok = fwd(h)
    for tag in ("FULL", "H1", "H2", "Q1", "Q2", "Q3", "Q4"):
        for sf in (None, "BUY", "SELL"):
            pick = np.ones(len(POS), bool) if sf is None else (SIDE == sf)
            m = ok[POS] & seg[tag][POS] & pick
            pos, sides = POS[m], SIDE[m]
            if not len(pos):
                continue
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
            rb = race_base(h, seg[tag], sides)
            rs = race_stats(h, pos, sides)
            rows.append({
                "horizon": lab, "h": h, "segment": tag, "side": sf or "ALL",
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
                "race": rs, "race_base_pct": rb,
                "race_diff_pp": (float(rs["fav_first_pct"] - rb)
                                 if rs and rb and rs.get("fav_first_pct") is not None else None),
                "gap_pct": float(labs[f"gapped_{h}"].to_numpy(bool)[pos].mean() * 100),
                "m1_cov_pct": float(labs[f"m1_ok_{h}"].to_numpy(bool)[pos].mean() * 100),
            })

# ---------------- range-target diagnostic ----------------
m1f = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M1.csv", Timeframe.M1)
m1t = pd.to_datetime(m1f["time"], utc=True).to_numpy("datetime64[ns]")
m1h, m1l = m1f["high"].to_numpy(float), m1f["low"].to_numpy(float)
m5t = pd.to_datetime(m5["time"], utc=True).to_numpy("datetime64[ns]")
FIVE = np.timedelta64(5, "m")
opp = ev["level_opposite"].to_numpy(float)

target = []
for h, lab in HOR[:3]:
    _, up, dn, ok = fwd(h)
    for sf in (None, "BUY", "SELL"):
        pick = np.ones(len(POS), bool) if sf is None else (SIDE == sf)
        m = ok[POS] & pick
        pos, sides, lv = POS[m], SIDE[m], opp[m]
        if not len(pos):
            continue
        need = np.where(sides == "BUY", lv - cl[pos], cl[pos] - lv) / atr[pos]
        favmfe = np.array([up[p] if s == "BUY" else dn[p] for p, s in zip(pos, sides)])
        reached = favmfe >= need
        pool_b, pool_s = up[ok], dn[ok]
        bp = [float(((pool_b if s == "BUY" else pool_s) >= nd).mean())
              for s, nd in zip(sides, need)]
        tt, cov = [], 0
        for p, s, L in zip(pos, sides, lv):
            mins, c = first_touch_m1(m1t, m1h, m1l, m5t[p] + FIVE,
                                     m5t[p] + FIVE * (h + 1), L,
                                     "UP" if s == "BUY" else "DOWN")
            cov += int(c)
            if c and mins is not None:
                tt.append(mins)
        target.append({"horizon": lab, "side": sf or "ALL", "events": int(len(pos)),
                       "need_atr_median": float(np.median(need)),
                       "need_atr_p25": float(np.percentile(need, 25)),
                       "need_atr_p75": float(np.percentile(need, 75)),
                       "reached_pct": float(reached.mean() * 100),
                       "baseline_pct": float(np.mean(bp) * 100),
                       "diff_pp": float(reached.mean() * 100 - np.mean(bp) * 100),
                       "m1_covered": cov, "m1_touched": len(tt),
                       "med_minutes_to_target": float(np.median(tt)) if tt else None})

(V / "results_D.json").write_text(json.dumps({"main": rows, "target": target}, indent=2),
                                  encoding="utf-8")
print(f"wrote {len(rows)} main rows, {len(target)} target rows")
