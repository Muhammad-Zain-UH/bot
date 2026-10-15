"""PHASE 2 -- intrabar path-order hypotheses H1, H2, H3.

Three confirmatory-style tests, three conditional baselines, two randomised-order
nulls, and the Phase 1 endpoint-coupling control applied to every headline.

Randomised-order nulls
----------------------
P1  interior permutation of M1 bars 2,3,4. Preserves M5 O/H/L/C and volume
    exactly, but MEASURED to flip `high_first` in only 5.7% of bars, because the
    extremes usually sit in the pinned first or last M1 bar. Reported with that
    weakness stated; it is not a sufficient null on its own.

P2  analytic order randomisation. Draws the high/low ORDER at random while
    holding the actual M5 open, high, low and close fixed, then re-derives every
    order feature from those preserved levels. Ordering information is destroyed
    completely; level information is untouched. This is the null the brief wants:
    if an effect survives P2, it came from the levels, not the order.

Both use a fixed seed. P2 uses 20 draws per bar for a stable null.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

V = Path(sys.argv[1])
HOR = [(3, "15m"), (6, "30m"), (12, "1h"), (24, "2h")]
PRIMARY = ("30m", "1h", "2h")
NDRAW = 20
SEED = 20261001

path = pd.read_pickle(V / "path.pkl")
perm = pd.read_pickle(V / "path_perm.pkl")
labs = pd.read_pickle(V / "labels.pkl")
base = pd.read_pickle(V / "features.pkl")
st = pd.read_pickle(V / "state.pkl")

n = len(path)
atr = base["atr_14"].to_numpy(float)
cl = base["close"].to_numpy(float)
hi5 = base["high"].to_numpy(float)
lo5 = base["low"].to_numpy(float)
op5 = base["open"].to_numpy(float)
idx = np.arange(n)

usable = path["usable"].to_numpy(bool)
seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)

# conditioners for baselines B and C
d12 = st["disp_12"].to_numpy(float)
vol = st["atr_ratio5"].to_numpy(float)


def qbin(x, k=5):
    q = np.full(n, -1)
    f = np.isfinite(x)
    q[f] = pd.qcut(x[f], k, labels=False, duplicates="drop")
    return q


QD, QV = qbin(d12), qbin(vol)


def label(h, ref="close", delay=0):
    """Signed-long forward return in ATR. `ref` controls the origin."""
    y = np.full(n, np.nan)
    m = n - h - delay - 1
    if ref == "close":
        origin = cl[delay:][:m] if delay else cl[:m]
    elif ref == "mid":
        origin = ((hi5 + lo5) / 2.0)[:m]
    else:
        raise ValueError(ref)
    y[:m] = (cl[h:][:m] - origin) / atr[:m]
    ok = (usable & base["feature_eligible"].to_numpy(bool)
          & labs[f"has_window_{h}"].to_numpy(bool)
          & np.isfinite(atr) & (atr > 0) & np.isfinite(y))
    return y, ok


def bstats(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    return float(bm.mean()), float(bm.std(ddof=1) / np.sqrt(len(bm))), len(bm)


def contrast(y, ok, up, dn, h, cond=None):
    """Mean(up-group) - Mean(dn-group), optionally conditioned within strips."""
    A, B = ok & up, ok & dn
    if A.sum() < 30 or B.sum() < 30:
        return None
    if cond is None:
        ma, sa, na = bstats(y[A], idx[A], h)
        mb, sb, nb = bstats(y[B], idx[B], h)
        d = ma - mb
        se = float(np.sqrt(sa ** 2 + sb ** 2))
    else:
        ds, ws = [], []
        for v in np.unique(cond[ok]):
            if v < 0:
                continue
            a2, b2 = A & (cond == v), B & (cond == v)
            if a2.sum() < 30 or b2.sum() < 30:
                continue
            ma, sa, _ = bstats(y[a2], idx[a2], h)
            mb, sb, _ = bstats(y[b2], idx[b2], h)
            ds.append(ma - mb)
            ws.append(1.0 / max(sa ** 2 + sb ** 2, 1e-12))
        if not ds:
            return None
        w = np.array(ws)
        d = float(np.average(ds, weights=w))
        se = float(np.sqrt(1.0 / w.sum()))
        na = int(A.sum())
        nb = int(B.sum())
    _, _, nblk = bstats(y[A | B], idx[A | B], h)
    return {"diff": d, "se": se, "t": (d / se if se > 0 else None),
            "n_up": int(A.sum()), "n_dn": int(B.sum()), "blocks": int(nblk),
            "mean_up": float(y[A].mean()), "mean_dn": float(y[B].mean()),
            "hit_up": float((y[A] > 0).mean() * 100), "hit_dn": float((y[B] > 0).mean() * 100)}


def race_share(h, mask):
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    tu, td = labs[f"t_up_{h}"].to_numpy(float), labs[f"t_dn_{h}"].to_numpy(float)
    m = mask & m1
    u, d = tu[m], td[m]
    uo, do = np.isfinite(u), np.isfinite(d)
    upf = (uo & ~do) | (uo & do & (u < d))
    dnf = (do & ~uo) | (uo & do & (d < u))
    r = int((upf | dnf).sum())
    return (float(upf.sum() / r * 100) if r else None), r


# ------------------------------------------------------------------ P2 null
rng = np.random.default_rng(SEED)
H = hi5
L = lo5
O = op5
C = cl
atr_prior = path["atr_prior"].to_numpy(float)


def randomised_order_features(draw_rng):
    """Random high/low ORDER with M5 O/H/L/C held fixed."""
    hf = draw_rng.random(n) < 0.5                     # high-first, 50/50
    out = {"high_first": hf.astype(float)}
    for thr in (0.25, 0.50):
        band = thr * atr_prior
        up_ok = H >= O + band
        dn_ok = L <= O - band
        d = np.zeros(n)
        # whichever qualifying extreme comes first under the randomised order
        d[up_ok & ~dn_ok] = 1.0
        d[dn_ok & ~up_ok] = -1.0
        both = up_ok & dn_ok
        d[both & hf] = 1.0
        d[both & ~hf] = -1.0
        out[f"first_exc_dir_{int(thr*100)}"] = d
    return out


results: dict = {"hypotheses": {}, "controls": {}, "meta": {}}

HF = path["high_first"].to_numpy(float) == 1.0
LF = path["low_first"].to_numpy(float) == 1.0
E25 = path["first_exc_dir_25"].to_numpy(float)
E50 = path["first_exc_dir_50"].to_numpy(float)
FAIL = path["h2_failed_exc"].to_numpy(float)
PU3 = path["probe_up_3"].to_numpy(float)
PD3 = path["probe_dn_3"].to_numpy(float)
RU3 = path["reject_up_3"].to_numpy(float)
RD3 = path["reject_dn_3"].to_numpy(float)

TESTS = {
    "H1_high_vs_low_first": (HF, LF),
    "H1_first_exc_025": (E25 > 0, E25 < 0),
    "H1_first_exc_050": (E50 > 0, E50 < 0),
    "H2_failed_up_vs_down": (FAIL > 0, FAIL < 0),
    "H3_probe_up3_vs_dn3": (PU3 >= 2, PD3 >= 2),
    "H3_reject_up3_vs_dn3": (RU3 >= 2, RD3 >= 2),
}

for name, (up, dn) in TESTS.items():
    entry: dict = {}
    for h, hl in HOR:
        y, ok = label(h)
        cell: dict = {}
        r = contrast(y, ok, up, dn, h)
        cell["raw"] = r
        cell["cond_disp"] = contrast(y, ok, up, dn, h, cond=QD)
        cell["cond_vol"] = contrast(y, ok, up, dn, h, cond=QV)
        # Phase 1 endpoint-coupling controls
        ym, okm = label(h, ref="mid")
        cell["ref_mid"] = contrast(ym, okm, up, dn, h)
        yd, okd = label(h, delay=1)
        cell["delay1"] = contrast(yd, okd, up, dn, h)
        # barrier race
        ru, nu = race_share(h, ok & up)
        rd, nd = race_share(h, ok & dn)
        cell["race_up_grp_pct"] = ru
        cell["race_dn_grp_pct"] = rd
        cell["race_diff_pp"] = (ru - rd) if (ru is not None and rd is not None) else None
        cell["race_n"] = [nu, nd]
        # temporal
        tmp = {}
        for tag, sm in seg.items():
            tmp[tag] = contrast(y, ok & sm, up, dn, h)
        cell["temporal"] = tmp
        # gaps
        gp = labs[f"gapped_{h}"].to_numpy(bool)
        w = labs[f"wall_{h}"].to_numpy(float)
        mm = ok & (up | dn)
        cell["gap_pct"] = float(gp[mm].mean() * 100)
        cell["wall_med"] = float(np.nanmedian(w[mm]))
        cell["wall_p99"] = float(np.nanpercentile(w[mm], 99))
        cell["m1_cov_pct"] = float(labs[f"m1_ok_{h}"].to_numpy(bool)[mm].mean() * 100)
        entry[hl] = cell
    results["hypotheses"][name] = entry

# ------------------------------------------------- randomised-order controls
ctrl: dict = {"P1_interior_perm": {}, "P2_analytic_random": {}}
pw = perm.pivot_table(index="idx", columns="perm", values=["high_first", "first_exc_dir_50"])
for h, hl in HOR:
    y, ok = label(h)
    # P1
    ts = []
    for p in range(6):
        hfp = np.full(n, np.nan)
        hfp[pw.index.to_numpy()] = pw[("high_first", p)].to_numpy()
        r = contrast(y, ok, hfp == 1.0, hfp == 0.0, h)
        if r:
            ts.append(r["t"])
    ctrl["P1_interior_perm"][hl] = {"t_values": ts,
                                    "mean_t": float(np.mean(ts)) if ts else None,
                                    "max_abs_t": float(np.max(np.abs(ts))) if ts else None}
    # P2
    ts2, ts2e = [], []
    r2 = np.random.default_rng(SEED + h)
    for _ in range(NDRAW):
        f = randomised_order_features(r2)
        a = contrast(y, ok, f["high_first"] == 1.0, f["high_first"] == 0.0, h)
        b = contrast(y, ok, f["first_exc_dir_50"] > 0, f["first_exc_dir_50"] < 0, h)
        if a:
            ts2.append(a["t"])
        if b:
            ts2e.append(b["t"])
    ctrl["P2_analytic_random"][hl] = {
        "high_first_null_mean_t": float(np.mean(ts2)) if ts2 else None,
        "high_first_null_sd_t": float(np.std(ts2, ddof=1)) if len(ts2) > 1 else None,
        "high_first_null_max_abs_t": float(np.max(np.abs(ts2))) if ts2 else None,
        "exc050_null_mean_t": float(np.mean(ts2e)) if ts2e else None,
        "exc050_null_max_abs_t": float(np.max(np.abs(ts2e))) if ts2e else None,
        "draws": NDRAW}
results["controls"] = ctrl
results["meta"] = {"usable": int(usable.sum()), "seed": SEED,
                   "perm_flip_rate_pct": 5.69,
                   "confirmatory_tests": len(TESTS), "horizons": [h for _, h in HOR]}

(V / "phase2.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(f"wrote phase2.json -- {len(TESTS)} tests x {len(HOR)} horizons")
