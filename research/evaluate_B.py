"""EVALUATE -- Candidate B: breakout -> retest -> continuation.

Directional. Every candidate number is reported beside a DRIFT-MATCHED
unconditional baseline: the same metric, same horizon, same temporal segment,
and critically the SAME SIDE, computed over all eligible M5 bars. Comparing a
SHORT candidate against zero would credit it with the period's -3.2% drift.

Independence: events are discrete, but breakouts cluster, so inference uses
non-overlapping h-bar blocks -- one value per block, the mean of the events
inside it.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

R = Path(__file__).parent
sys.path.insert(0, str(R))
V = Path(sys.argv[1])
HOR = [(6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")]

m5 = pd.read_pickle(V / "features.pkl")
labs = pd.read_pickle(V / "labels.pkl")
ev = pd.read_pickle(V / "events_B.pkl")
n = len(m5); atr = m5["atr_14"].to_numpy(float); idx = np.arange(n)

seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)


def arrays(h):
    up = labs[f"up_{h}"].to_numpy(float); dn = labs[f"dn_{h}"].to_numpy(float)
    hw = labs[f"has_window_{h}"].to_numpy(bool)
    cl = m5["close"].to_numpy(float)
    ret = np.full(n, np.nan)
    m = n - h
    ret[:m] = (cl[h:][:m] - cl[:m]) / atr[:m]          # signed LONG
    base = (m5["feature_eligible"].to_numpy(bool) & hw & np.isfinite(atr) & (atr > 0)
            & np.isfinite(ret))
    return ret, up / atr, dn / atr, hw, base


def sided(side, ret, mfe_l, mae_l):
    """Return (signed_return, MFE, MAE) for the given side."""
    if side == "BUY":
        return ret, mfe_l, mae_l
    return -ret, mae_l, mfe_l                          # short: roles swap


def race(h, rows, side):
    """Favourable-first share at +/-1 ATR, M1-resolved only."""
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    tu = labs[f"t_up_{h}"].to_numpy(float); td = labs[f"t_dn_{h}"].to_numpy(float)
    rows = rows[m1[rows]]
    if len(rows) == 0:
        return dict(n=0)
    fav, adv = (tu[rows], td[rows]) if side == "BUY" else (td[rows], tu[rows])
    f_ok, a_ok = np.isfinite(fav), np.isfinite(adv)
    fav_first = (f_ok & ~a_ok) | (f_ok & a_ok & (fav < adv))
    adv_first = (a_ok & ~f_ok) | (f_ok & a_ok & (adv < fav))
    resolved = int((fav_first | adv_first).sum())
    return dict(n=int(len(rows)), resolved=resolved,
                fav_first_pct=float(fav_first.sum() / resolved * 100) if resolved else None,
                med_t_fav=float(np.nanmedian(fav)) if f_ok.any() else None,
                med_t_adv=float(np.nanmedian(adv)) if a_ok.any() else None,
                pct_touch_fav=float(f_ok.mean() * 100), pct_touch_adv=float(a_ok.mean() * 100))


def block_se(values, positions, h):
    b = positions // h
    bm = pd.DataFrame({"b": b, "v": values}).groupby("b")["v"].mean().to_numpy()
    se = bm.std(ddof=1) / np.sqrt(len(bm)) if len(bm) > 1 else np.nan
    return len(bm), (float(se) if np.isfinite(se) else None), float(bm.mean())


def run(h, lab, tag, side_filter):
    ret, mfe_l, mae_l, hw, base = arrays(h)
    sm = seg[tag]
    e = ev if side_filter is None else ev[ev.side == side_filter]
    pos = e["retest_idx"].to_numpy(int)
    keep = base[pos] & sm[pos]
    pos, sides = pos[keep], e["side"].to_numpy()[keep]
    if len(pos) == 0:
        return None

    cr, cm, ca = np.empty(len(pos)), np.empty(len(pos)), np.empty(len(pos))
    for i, (p, s) in enumerate(zip(pos, sides)):
        r, mf, ma = sided(s, ret, mfe_l, mae_l)
        cr[i], cm[i], ca[i] = r[p], mf[p], ma[p]

    # ---- drift-matched baseline: same side mix, same segment, all eligible bars ----
    bl = base & sm
    comp = {}
    for s in ("BUY", "SELL"):
        r, mf, ma = sided(s, ret, mfe_l, mae_l)
        comp[s] = (r[bl], mf[bl], ma[bl])
    w = {s: float((sides == s).mean()) for s in ("BUY", "SELL")}
    b_ret = np.concatenate([comp[s][0] for s in ("BUY", "SELL") if w[s] > 0])
    # weighted baseline means matching the candidate's side composition
    bmean = sum(w[s] * comp[s][0].mean() for s in ("BUY", "SELL") if w[s] > 0)
    bmed = sum(w[s] * np.median(comp[s][0]) for s in ("BUY", "SELL") if w[s] > 0)
    bmfe = sum(w[s] * np.median(comp[s][1]) for s in ("BUY", "SELL") if w[s] > 0)
    bmae = sum(w[s] * np.median(comp[s][2]) for s in ("BUY", "SELL") if w[s] > 0)
    bhit = sum(w[s] * float((comp[s][0] > 0).mean()) for s in ("BUY", "SELL") if w[s] > 0)
    nb_b, se_b, _ = block_se(comp["BUY"][0] if w["BUY"] >= w["SELL"] else comp["SELL"][0],
                             idx[bl], h)
    nb, se_c, blk_mean = block_se(cr, pos, h)

    se_diff = float(np.sqrt((se_c or 0) ** 2 + (se_b or 0) ** 2)) if se_c else None
    d = float(cr.mean() - bmean)
    return {
        "horizon": lab, "h": h, "segment": tag, "side": side_filter or "ALL",
        "events": int(len(pos)), "blocks": int(nb),
        "cand_ret_mean": float(cr.mean()), "cand_ret_median": float(np.median(cr)),
        "cand_mfe_median": float(np.median(cm)), "cand_mae_median": float(np.median(ca)),
        "cand_hit_pct": float((cr > 0).mean() * 100),
        "base_ret_mean": float(bmean), "base_ret_median": float(bmed),
        "base_mfe_median": float(bmfe), "base_mae_median": float(bmae),
        "base_hit_pct": float(bhit * 100),
        "diff_ret_mean": d, "diff_ret_median": float(np.median(cr) - bmed),
        "diff_mfe_median": float(np.median(cm) - bmfe),
        "diff_mae_median": float(np.median(ca) - bmae),
        "diff_hit_pp": float((cr > 0).mean() * 100 - bhit * 100),
        "se_cand_block": se_c, "se_base_block": se_b, "se_diff": se_diff,
        "mde_2se": float(2 * se_diff) if se_diff else None,
        "t_stat": float(d / se_diff) if se_diff else None,
        "race": race(h, pos, side_filter) if side_filter else None,
        "gap_pct": float(labs[f"gapped_{h}"].to_numpy(bool)[pos].mean() * 100),
        "m1_cov_pct": float(labs[f"m1_ok_{h}"].to_numpy(bool)[pos].mean() * 100),
    }


out = []
for h, lab in HOR:
    for tag in ("FULL", "H1", "H2", "Q1", "Q2", "Q3", "Q4"):
        for sf in (None, "BUY", "SELL"):
            r = run(h, lab, tag, sf)
            if r: out.append(r)
(V / "results_B.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(f"wrote {len(out)} result rows -> {V/'results_B.json'}")
