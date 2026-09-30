"""SESSION-OPEN DIRECTIONAL SHAPE DIAGNOSTIC.

NOT Candidate H. This produces a small predeclared surface (k x session x
horizon) so a legitimate H specification can be written from measurement. It
selects no k, no session and no horizon, and declares no threshold.

Two baselines, both side-matched to the candidate's own direction mix:

  A  unconditional drift-matched -- all eligible M5 bars, the control used for
     Candidates B/D/F.
  B  session-conditioned -- eligible M5 bars in the SAME UTC hour as the
     decision bar. Necessary because session drift and volatility differ from
     the all-day average, so an effect against A alone could be nothing more
     than "this hour behaves unlike the rest of the day".

Baseline B is matched PER EVENT on (hour, side) and then averaged, so the
control carries exactly the candidate's own session and direction composition.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).parent
sys.path.insert(0, str(R))
from candidates import PRECURSOR_K_GRID, PRECURSOR_SESSION_HOURS

V = Path(sys.argv[1])
HOR = [(6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")]

m5 = pd.read_pickle(V / "features.pkl")
labs = pd.read_pickle(V / "labels.pkl")
ev = pd.read_pickle(V / "events_H.pkl")
ev = ev[(ev.open_dir != "UNDEFINED") & ev.decision_eligible].reset_index(drop=True)

n = len(m5)
atr = m5["atr_14"].to_numpy(float)
cl = m5["close"].to_numpy(float)
idx = np.arange(n)
hour = pd.to_datetime(m5["time"], utc=True).dt.hour.to_numpy()

seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)

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


def block_stats(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    se = float(bm.std(ddof=1) / np.sqrt(len(bm))) if len(bm) > 1 else None
    return len(bm), se


def baseline_pool(h, mask, side):
    """Side-signed unconditional stats over `mask`."""
    r, up, dn, ok = fwd(h)
    m = ok & mask
    rr, mf, ma = sided(side, r, up, dn)
    return rr[m], mf[m], ma[m], idx[m]


def race_of(h, pos, sides):
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


def race_baseline(h, mask, sides):
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


def evaluate(k, sess, tag, h, lab):
    r, up, dn, ok = fwd(h)
    d = ev[ev.k == k] if sess == "ALL" else ev[(ev.k == k) & (ev.session == sess)]
    pos = d["decision_idx"].to_numpy(int)
    sides = d["side"].to_numpy()
    keep = ok[pos] & seg[tag][pos]
    pos, sides = pos[keep], sides[keep]
    sub = d[keep]
    if len(pos) < 2:
        return None

    comp = {s: sided(s, r, up, dn) for s in ("BUY", "SELL")}
    cr = np.array([comp[s][0][p] for p, s in zip(pos, sides)])
    cm = np.array([comp[s][1][p] for p, s in zip(pos, sides)])
    ca = np.array([comp[s][2][p] for p, s in zip(pos, sides)])
    nb, se_c = block_stats(cr, pos, h)
    w = {s: float((sides == s).mean()) for s in ("BUY", "SELL")}

    # ---- Baseline A: all eligible bars, side-mix weighted ----
    blA = ok & seg[tag]
    a_mean = sum(w[s] * comp[s][0][blA].mean() for s in w if w[s] > 0)
    a_hit = sum(w[s] * float((comp[s][0][blA] > 0).mean()) for s in w if w[s] > 0)
    _, se_a = block_stats(comp["BUY"][0][blA], idx[blA], h)

    # ---- Baseline B: same UTC hour as each event's decision bar, per-event ----
    b_vals, b_hits = [], []
    for p, s in zip(pos, sides):
        hm = ok & seg[tag] & (hour == hour[p])
        if hm.sum() < 10:
            continue
        v = comp[s][0][hm]
        b_vals.append(v.mean())
        b_hits.append(float((v > 0).mean()))
    b_mean = float(np.mean(b_vals)) if b_vals else None
    b_hit = float(np.mean(b_hits)) if b_hits else None
    hours_used = sorted(set(int(hour[p]) for p in pos))
    hmask = ok & seg[tag] & np.isin(hour, hours_used)
    _, se_b = block_stats(comp["BUY"][0][hmask], idx[hmask], h)

    sd_a = float(np.sqrt((se_c or 0) ** 2 + (se_a or 0) ** 2)) if se_c else None
    sd_b = float(np.sqrt((se_c or 0) ** 2 + (se_b or 0) ** 2)) if se_c else None
    dA = float(cr.mean() - a_mean)
    dB = float(cr.mean() - b_mean) if b_mean is not None else None

    # ---- descriptive volatility stratification (NOT a threshold) ----
    strat = []
    amv = sub["open_abs_move_atr"].to_numpy(float)
    if len(cr) >= 15 and np.isfinite(amv).all():
        cuts = np.percentile(amv, [100 / 3, 200 / 3])
        for ti, m in enumerate([amv <= cuts[0],
                                (amv > cuts[0]) & (amv <= cuts[1]),
                                amv > cuts[1]]):
            if m.sum() >= 3:
                strat.append({"tercile": ti + 1, "n": int(m.sum()),
                              "open_abs_move_atr_med": float(np.median(amv[m])),
                              "cand_ret_mean": float(cr[m].mean()),
                              "diff_B": (float(cr[m].mean() - b_mean)
                                         if b_mean is not None else None),
                              "hit_pct": float((cr[m] > 0).mean() * 100)})

    rb = race_baseline(h, seg[tag], sides)
    rs = race_of(h, pos, sides)
    return {
        "k": int(k), "session": str(sess), "segment": tag, "horizon": lab, "h": h,
        "events": int(len(pos)), "blocks": int(nb),
        "up_share_pct": float((sides == "BUY").mean() * 100),
        "cand_ret_mean": float(cr.mean()), "cand_ret_median": float(np.median(cr)),
        "cand_mfe_median": float(np.median(cm)), "cand_mae_median": float(np.median(ca)),
        "cand_hit_pct": float((cr > 0).mean() * 100),
        "baseA_ret_mean": float(a_mean), "baseA_hit_pct": float(a_hit * 100),
        "diff_A": dA, "se_diff_A": sd_a,
        "t_A": float(dA / sd_a) if sd_a else None,
        "baseB_ret_mean": b_mean,
        "baseB_hit_pct": float(b_hit * 100) if b_hit is not None else None,
        "diff_B": dB, "se_diff_B": sd_b,
        "t_B": float(dB / sd_b) if (sd_b and dB is not None) else None,
        "race": rs, "race_base_pct": rb,
        "race_diff_pp": (float(rs["fav_first_pct"] - rb)
                         if rs and rb and rs.get("fav_first_pct") is not None else None),
        "open_abs_move_atr_med": float(np.nanmedian(sub["open_abs_move_atr"])),
        "open_range_atr_med": float(np.nanmedian(sub["open_range_atr"])),
        "subseq_abs_exc_med": float(np.median(np.maximum(cm, ca))),
        "vol_terciles": strat,
        "gap_pct": float(labs[f"gapped_{h}"].to_numpy(bool)[pos].mean() * 100),
        "m1_cov_pct": float(labs[f"m1_ok_{h}"].to_numpy(bool)[pos].mean() * 100),
    }


rows = []
for k in PRECURSOR_K_GRID:
    for sess in ("ALL",) + PRECURSOR_SESSION_HOURS:
        tags = (("FULL", "H1", "H2", "Q1", "Q2", "Q3", "Q4") if sess == "ALL"
                else ("FULL", "H1", "H2"))
        for tag in tags:
            for h, lab in HOR:
                res = evaluate(k, sess, tag, h, lab)
                if res:
                    rows.append(res)

(V / "results_H.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"wrote {len(rows)} rows")
