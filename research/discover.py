"""EDGE DISCOVERY PHASE 1 -- conditional state -> path -> outcome scan.

Exploratory. Produces a machine-readable surface; selects nothing, thresholds
nothing, and builds no rule.

Label convention
----------------
Every label is signed LONG. A feature carries directional information when its
quintile means move monotonically with the signed-long outcome -- a negative
slope is as informative as a positive one. Features never assert a direction,
so this keeps both directions symmetric.

Three baselines, each side-matched by construction (all labels are long-signed):

  A  unconditional        -- all eligible bars in the segment
  B  hour-conditioned     -- bars in the same UTC hour, averaged per event
  C  direction-conditioned -- bars in the same disp_12 quintile, averaged per
     event. This answers "does this state add anything beyond what recent
     directional displacement already explains?". For the disp_* family itself
     C is degenerate by construction and is flagged, not hidden.

Quantile cutoffs come from the FEATURE distribution only; no label value
influences any cutoff. They are computed over the whole sample, which is an
in-sample look at the feature marginal -- acceptable for discovery, but a frozen
validation must fix cutoffs from a training period. Stated, not assumed away.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

V = Path(sys.argv[1])
HOR = [(3, "15m"), (6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")]
PRIMARY = ("30m", "1h", "2h")
NQ = 5

st = pd.read_pickle(V / "state.pkl")
labs = pd.read_pickle(V / "labels.pkl")
base = pd.read_pickle(V / "features.pkl")

n = len(st)
atr = base["atr_14"].to_numpy(float)
cl = base["close"].to_numpy(float)
idx = np.arange(n)
hour = st["utc_hour"].to_numpy(float)

FEATURES = [c for c in st.columns if c not in ("idx", "time")]
DISP_FAMILY = {"disp_3", "disp_6", "disp_12", "disp_m15_3", "disp_m15_6"}

seg = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    seg[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)


def horizon_arrays(h):
    up = labs[f"up_{h}"].to_numpy(float) / atr
    dn = labs[f"dn_{h}"].to_numpy(float) / atr
    r = np.full(n, np.nan)
    m = n - h
    r[:m] = (cl[h:][:m] - cl[:m]) / atr[:m]
    ok = (base["feature_eligible"].to_numpy(bool) & labs[f"has_window_{h}"].to_numpy(bool)
          & np.isfinite(atr) & (atr > 0) & np.isfinite(r))
    tu, td = labs[f"t_up_{h}"].to_numpy(float), labs[f"t_dn_{h}"].to_numpy(float)
    m1 = labs[f"m1_ok_{h}"].to_numpy(bool)
    return r, up, dn, ok, tu, td, m1


HA = {h: horizon_arrays(h) for h, _ in HOR}

# disp_12 quintile -- the conditioner for baseline C
d12 = st["disp_12"].to_numpy(float)
d12q = np.full(n, -1)
fin = np.isfinite(d12)
d12q[fin] = pd.qcut(d12[fin], NQ, labels=False, duplicates="drop")


def block_se(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    return len(bm), (float(bm.std(ddof=1) / np.sqrt(len(bm))) if len(bm) > 1 else None)


def race_up_share(tu, td, m1, mask):
    m = mask & m1
    u, d = tu[m], td[m]
    uo, do = np.isfinite(u), np.isfinite(d)
    upf = (uo & ~do) | (uo & do & (u < d))
    dnf = (do & ~uo) | (uo & do & (d < u))
    res = int((upf | dnf).sum())
    return (float(upf.sum() / res * 100) if res else None), res


rows = []
ntests = 0
for feat in FEATURES:
    x = st[feat].to_numpy(float)
    fin = np.isfinite(x)
    if fin.sum() < 1000 or len(np.unique(x[fin])) < NQ:
        continue
    try:
        qb = pd.qcut(x[fin], NQ, labels=False, duplicates="drop")
    except ValueError:
        continue
    q = np.full(n, -1)
    q[fin] = qb
    nq = int(qb.max()) + 1

    for h, lab in HOR:
        r, up, dn, ok, tu, td, m1 = HA[h]
        for tag, sm in seg.items():
            elig = ok & sm
            if elig.sum() < 100:
                continue
            # precompute conditional baseline maps on this (h, segment)
            hr_mean = {}
            for hv in np.unique(hour[elig]):
                mm = elig & (hour == hv)
                if mm.sum() >= 10:
                    hr_mean[hv] = float(r[mm].mean())
            dq_mean = {}
            for dv in range(NQ):
                mm = elig & (d12q == dv)
                if mm.sum() >= 10:
                    dq_mean[dv] = float(r[mm].mean())
            a_mean = float(r[elig].mean())
            a_hit = float((r[elig] > 0).mean() * 100)
            _, se_a = block_se(r[elig], idx[elig], h)

            for b in range(nq):
                m = elig & (q == b)
                if m.sum() < 20:
                    continue
                if tag == "FULL" and lab in PRIMARY:
                    ntests += 1
                v = r[m]
                nb, se_c = block_se(v, idx[m], h)
                bB = np.array([hr_mean.get(hv, np.nan) for hv in hour[m]])
                bC = np.array([dq_mean.get(dv, np.nan) for dv in d12q[m]])
                mB = float(np.nanmean(bB)) if np.isfinite(bB).any() else None
                mC = float(np.nanmean(bC)) if np.isfinite(bC).any() else None
                sd = float(np.sqrt((se_c or 0) ** 2 + (se_a or 0) ** 2)) if se_c else None
                ups, res = race_up_share(tu, td, m1, m)
                ub, _ = race_up_share(tu, td, m1, elig)
                rows.append({
                    "feature": feat, "quintile": b + 1, "nq": nq,
                    "horizon": lab, "h": h, "segment": tag,
                    "N": int(m.sum()), "blocks": int(nb),
                    "x_median": float(np.median(x[m])),
                    "ret_mean": float(v.mean()), "ret_median": float(np.median(v)),
                    "hit_pct": float((v > 0).mean() * 100),
                    "mfe_long_med": float(np.median(up[m])),
                    "mae_long_med": float(np.median(dn[m])),
                    "mfe_short_med": float(np.median(dn[m])),
                    "mae_short_med": float(np.median(up[m])),
                    "baseA": a_mean, "baseA_hit": a_hit,
                    "baseB": mB, "baseC": mC,
                    "diff_A": float(v.mean() - a_mean),
                    "diff_B": (float(v.mean() - mB) if mB is not None else None),
                    "diff_C": (float(v.mean() - mC) if mC is not None else None),
                    "se": sd, "t_A": (float((v.mean() - a_mean) / sd) if sd else None),
                    "t_C": (float((v.mean() - mC) / sd) if (sd and mC is not None) else None),
                    "race_up_pct": ups, "race_base_up_pct": ub, "race_resolved": res,
                    "disp_family": feat in DISP_FAMILY,
                    "gap_pct": float(labs[f"gapped_{h}"].to_numpy(bool)[m].mean() * 100),
                    "m1_cov_pct": float(m1[m].mean() * 100),
                })

out = {"n_features_scanned": len(set(r["feature"] for r in rows)),
       "primary_tests_FULL": ntests, "rows": rows}
(V / "discovery.json").write_text(json.dumps(out), encoding="utf-8")
print(f"features scanned: {out['n_features_scanned']}")
print(f"FULL-sample primary cells (feature x quintile x 30m/1h/2h): {ntests}")
print(f"total rows written: {len(rows)}")
