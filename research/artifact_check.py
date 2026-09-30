"""Decisive test: shared-endpoint coupling vs genuine conditional structure.

`dist_high12_atr` and `close_loc` both condition on where close[i] sits relative
to a local range. The forward label is (close[i+h] - close[i]) / atr[i]. close[i]
appears in BOTH with opposite sign, so if close[i] carries any transient
component -- a low draw inside its own bar, a tick at the bid -- then a low
close[i] mechanically makes the feature large AND the measured forward return
large, with no economic content whatsoever.

The test: re-measure the forward return from a reference point that is NOT
close[i].

  ref = open[i+1]   the next bar's open. This is also the price the existing
                    fill model actually fills at, so it is the economically
                    meaningful reference, not merely a statistical control.
  ref = mid[i]      (high[i] + low[i]) / 2, a reference inside bar i that does
                    not privilege the closing tick.

If the relationship is real it survives both. If it is endpoint coupling it
collapses toward zero when close[i] is removed from the label.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

V = Path(sys.argv[1])
st = pd.read_pickle(V / "state.pkl")
labs = pd.read_pickle(V / "labels.pkl")
base = pd.read_pickle(V / "features.pkl")

n = len(st)
atr = base["atr_14"].to_numpy(float)
cl = base["close"].to_numpy(float)
op = base["open"].to_numpy(float)
hi = base["high"].to_numpy(float)
lo = base["low"].to_numpy(float)
idx = np.arange(n)
NQ = 5

FEATS = ["dist_high12_atr", "close_loc", "dist_low12_atr", "pos_12", "pos_24",
         "rng12_atr", "atr_ratio15", "disp_m15_6"]
REFS = {
    "close[i]  (original)": cl,
    "open[i+1] (fill price)": np.r_[op[1:], np.nan],
    "mid[i]    (bar midpoint)": (hi + lo) / 2.0,
}


def blocks_mean_se(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    return float(bm.mean()), float(bm.std(ddof=1) / np.sqrt(len(bm))), len(bm)


def spread_t(feat, h, ref):
    x = st[feat].to_numpy(float)
    fin = np.isfinite(x)
    q = np.full(n, -1)
    q[fin] = pd.qcut(x[fin], NQ, labels=False, duplicates="drop")
    y = np.full(n, np.nan)
    m = n - h - 1
    y[:m] = (cl[h:][:m] - ref[:m]) / atr[:m]
    ok = (base["feature_eligible"].to_numpy(bool) & labs[f"has_window_{h}"].to_numpy(bool)
          & np.isfinite(atr) & (atr > 0) & np.isfinite(y))
    a, b = ok & (q == 0), ok & (q == NQ - 1)
    if a.sum() < 30 or b.sum() < 30:
        return None
    ml, sl, _ = blocks_mean_se(y[a], idx[a], h)
    mh, sh, _ = blocks_mean_se(y[b], idx[b], h)
    sp = mh - ml
    se = float(np.sqrt(sl ** 2 + sh ** 2))
    return sp, se, (sp / se if se > 0 else np.nan)


print("Q5-Q1 SPREAD, measured from three different reference points")
print("(same feature, same quintiles, same horizon -- only the label's origin changes)\n")
for h, hl in ((6, "30m"), (12, "1h"), (24, "2h")):
    print(f"  ===== {hl} =====")
    print(f"  {'feature':<20} " + " ".join(f"{k:>26}" for k in REFS))
    print(f"  {'':<20} " + " ".join(f"{'spread    SE       t':>26}" for _ in REFS))
    for f in FEATS:
        cells = []
        for k, ref in REFS.items():
            r = spread_t(f, h, ref)
            cells.append(f"{r[0]:>8.3f} {r[1]:>6.3f} {r[2]:>7.2f}" if r else " " * 26)
        print(f"  {f:<20} " + " ".join(f"{c:>26}" for c in cells))
    print()

print("INTERPRETATION AID -- how much of the effect is carried by close[i] alone")
print("  ratio = |t(open[i+1])| / |t(close[i])|. Near 0 => endpoint coupling.")
print(f"  {'feature':<20} {'30m':>8} {'1h':>8} {'2h':>8}")
for f in FEATS:
    cells = []
    for h in (6, 12, 24):
        a = spread_t(f, h, REFS["close[i]  (original)"])
        b = spread_t(f, h, REFS["open[i+1] (fill price)"])
        cells.append(f"{abs(b[2]) / abs(a[2]):>8.2f}" if a and b and a[2] else "      --")
    print(f"  {f:<20} " + " ".join(cells))
