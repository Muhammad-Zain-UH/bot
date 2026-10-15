"""Multiple-testing accounting, spread tests, artifact checks, interactions.

Three things the quintile scan cannot answer on its own:

1. How many extreme t-statistics did 504 primary cells produce, against how
   many chance predicts?
2. Is a monotonic quintile relationship actually significant? The right test is
   on the Q5-Q1 SPREAD, not on individual cells.
3. Are the volatility features real, or an ATR-normalisation artifact? The
   label is divided by the same ATR the feature is built from, so a state where
   ATR understates current volatility inflates |ret/ATR| mechanically. Re-running
   on RAW dollar returns separates the two.
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

V = Path(sys.argv[1])
d = json.loads((V / "discovery.json").read_text())
df = pd.DataFrame(d["rows"])
st = pd.read_pickle(V / "state.pkl")
labs = pd.read_pickle(V / "labels.pkl")
base = pd.read_pickle(V / "features.pkl")
n = len(st)
atr = base["atr_14"].to_numpy(float)
cl = base["close"].to_numpy(float)
idx = np.arange(n)
NQ = 5
PRIMARY = ("30m", "1h", "2h")

print("=" * 78)
print("1. MULTIPLE-TESTING ACCOUNTING")
print("=" * 78)
full = df[(df.segment == "FULL") & (df.horizon.isin(PRIMARY))]
for col, lab in (("t_A", "vs baseline A"), ("t_C", "vs baseline C")):
    t = full[col].to_numpy(float)
    t = t[np.isfinite(t)]
    print(f"  {lab}: cells={len(t)}  max|t|={np.abs(t).max():.2f}")
    for thr in (1.5, 2.0, 2.5, 3.0):
        exp = len(t) * 2 * (1 - 0.5 * (1 + math.erf(thr / math.sqrt(2))))
        print(f"    |t|>={thr}: observed {int((np.abs(t) >= thr).sum()):>3}   "
              f"expected under null {exp:>5.1f}")

print()
print("=" * 78)
print("2. Q5-Q1 SPREAD TESTS (the correct test for a monotonic relationship)")
print("=" * 78)


def horizon_arrays(h):
    r = np.full(n, np.nan)
    m = n - h
    r[:m] = (cl[h:][:m] - cl[:m]) / atr[:m]
    raw = np.full(n, np.nan)
    raw[:m] = cl[h:][:m] - cl[:m]
    ok = (base["feature_eligible"].to_numpy(bool) & labs[f"has_window_{h}"].to_numpy(bool)
          & np.isfinite(atr) & (atr > 0) & np.isfinite(r))
    return r, raw, ok


HA = {h: horizon_arrays(h) for h in (6, 12, 24)}


def blocks_mean_se(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    return len(bm), float(bm.mean()), float(bm.std(ddof=1) / np.sqrt(len(bm)))


def spread_test(feat, h, use_raw=False, seg_mask=None):
    x = st[feat].to_numpy(float)
    fin = np.isfinite(x)
    q = np.full(n, -1)
    q[fin] = pd.qcut(x[fin], NQ, labels=False, duplicates="drop")
    r, raw, ok = HA[h]
    y = raw if use_raw else r
    m = ok & (seg_mask if seg_mask is not None else True) & np.isfinite(y)
    lo, hi = m & (q == 0), m & (q == NQ - 1)
    if lo.sum() < 30 or hi.sum() < 30:
        return None
    nl, ml, sl = blocks_mean_se(y[lo], idx[lo], h)
    nh, mh, sh = blocks_mean_se(y[hi], idx[hi], h)
    sp = mh - ml
    se = float(np.sqrt(sl ** 2 + sh ** 2))
    return {"spread": sp, "se": se, "t": sp / se if se > 0 else None,
            "n_lo": int(lo.sum()), "n_hi": int(hi.sum()), "blk_lo": nl, "blk_hi": nh}


struct = pd.read_json(V / "structure.json")
top = struct[struct.min_blocks >= 100].head(8)
print(f"  {'feature':<20} " + " ".join(f"{h:>22}" for h in PRIMARY))
print(f"  {'':<20} " + " ".join(f"{'spread   SE      t':>22}" for _ in PRIMARY))
for feat in top.feature:
    cells = []
    for h, lab in ((6, "30m"), (12, "1h"), (24, "2h")):
        s = spread_test(feat, h)
        cells.append(f"{s['spread']:>7.3f} {s['se']:>6.3f} {s['t']:>6.2f}" if s else " " * 22)
    print(f"  {feat:<20} " + " ".join(f"{c:>22}" for c in cells))

print()
print("=" * 78)
print("3. ATR-NORMALISATION ARTIFACT CHECK  (same spread, RAW dollar return)")
print("=" * 78)
print("  If a volatility feature predicts ATR-normalised return but NOT raw")
print("  return, the relationship is a property of the denominator.")
print(f"  {'feature':<20} {'1h ATR-norm t':>15} {'1h RAW $ t':>13} {'2h ATR-norm t':>15} {'2h RAW $ t':>13}")
for feat in top.feature:
    a1 = spread_test(feat, 12)
    r1 = spread_test(feat, 12, use_raw=True)
    a2 = spread_test(feat, 24)
    r2 = spread_test(feat, 24, use_raw=True)
    print(f"  {feat:<20} {a1['t']:>15.2f} {r1['t']:>13.2f} {a2['t']:>15.2f} {r2['t']:>13.2f}")

print()
print("=" * 78)
print("4. COLLINEARITY among shortlisted features")
print("=" * 78)
sub = st[list(top.feature)].to_numpy(float)
good = np.isfinite(sub).all(axis=1)
C = np.corrcoef(sub[good].T)
print(f"  {'':<20} " + " ".join(f"{f[:8]:>9}" for f in top.feature))
for i, f in enumerate(top.feature):
    print(f"  {f:<20} " + " ".join(f"{C[i, j]:>9.2f}" for j in range(len(top))))

print()
print("=" * 78)
print("5. TEMPORAL DETAIL, shortlisted features, 1h spread by segment")
print("=" * 78)
segs = {"FULL": np.ones(n, bool), "H1": idx < n // 2, "H2": idx >= n // 2}
for q in range(4):
    segs[f"Q{q+1}"] = (idx >= q * n // 4) & (idx < (q + 1) * n // 4)
print(f"  {'feature':<20} " + " ".join(f"{k:>14}" for k in segs))
for feat in top.feature:
    cells = []
    for k, sm in segs.items():
        s = spread_test(feat, 12, seg_mask=sm)
        cells.append(f"{s['spread']:>7.3f}({s['t']:>5.2f})" if s else "      --      ")
    print(f"  {feat:<20} " + " ".join(f"{c:>14}" for c in cells))
