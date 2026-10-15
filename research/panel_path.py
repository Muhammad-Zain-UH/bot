"""M1 EVENT-SEQUENCE PANEL -- intrabar path order, PAST INFORMATION ONLY.

One row per completed M5 bar, describing the ORDER in which price moved inside
that bar, reconstructed from its five M1 bars.

Anti-artifact discipline (Phase 1's failure mode)
------------------------------------------------
* Every feature for M5 bar i is built from bar i's own five M1 bars and from
  ATR5 measured at bar i-1 -- i.e. volatility known BEFORE bar i began. ATR5 at
  bar i would already contain bar i's range.
* The prediction interval starts at the first M1 bar AFTER bar i closes, so it
  never overlaps the feature-construction interval.
* Two features are LEVEL features, not order features, and are flagged
  `couples_with_close`: `final_close_in_range` and `retrace_frac`. They involve
  close[i], which the forward label also subtracts, so they carry the same
  endpoint-coupling risk that produced Phase 1's spurious t = 8.17. They are
  computed and reported, never treated as order evidence without the control.

Randomised-order null
---------------------
`permute_interior` reorders only M1 bars 2,3,4 inside each M5 bar. M5 open (bar
1's open), M5 close (bar 5's close), M5 high (max of highs), M5 low (min of
lows) and summed tick volume are ALL preserved exactly -- max and min are
permutation-invariant, and the pinned endpoints fix open and close. Only the
interior ordering changes. All 3! = 6 permutations are enumerated, so the null
is deterministic and complete rather than sampled.
"""
from __future__ import annotations
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core.types import Timeframe
from data.dataset import load_bars_csv

EXC_THRESHOLDS = (0.25, 0.50)     # fixed by brief; not optimised
H2_EXC = 0.50                     # frozen H2 definition
H2_RETRACE = 0.50
MEMORY_WINDOWS = (2, 3, 6)
INTERIOR_PERMS = list(itertools.permutations((1, 2, 3)))   # all 6


def _path_features(o, h, l, c, atr_prior):
    """Order/geometry features for ONE M5 bar from its five M1 bars.

    Args:
        o, h, l, c: length-5 arrays of M1 open/high/low/close, in time order.
        atr_prior: ATR5 at the PREVIOUS M5 bar -- known before this bar began.
    """
    m5o, m5c = float(o[0]), float(c[-1])
    m5h, m5l = float(h.max()), float(l.min())
    a = atr_prior
    out: dict[str, float] = {}

    ih, il = int(np.argmax(h)), int(np.argmin(l))
    out["m1_high_pos"] = ih
    out["m1_low_pos"] = il
    out["high_first"] = float(ih < il)
    out["low_first"] = float(il < ih)
    out["hl_same_bar"] = float(ih == il)

    # ---- first meaningful excursion from the M5 OPEN, at each fixed threshold
    for thr in EXC_THRESHOLDS:
        tag = f"{int(thr * 100)}"
        d = 0.0
        amb = 0.0
        if a > 0:
            band = thr * a
            for k in range(5):
                up = h[k] >= m5o + band
                dn = l[k] <= m5o - band
                if up and dn:
                    amb = 1.0
                    d = 0.0
                    break
                if up:
                    d = 1.0
                    break
                if dn:
                    d = -1.0
                    break
        out[f"first_exc_dir_{tag}"] = d
        out[f"first_exc_ambig_{tag}"] = amb

    out["first_m1_close_dir"] = float(np.sign(c[0] - m5o))
    out["final_m1_close_dir"] = float(np.sign(c[4] - c[3]))

    # ---- excursion geometry (all normalised by ATR known before the bar)
    out["m5_range_atr"] = (m5h - m5l) / a if a > 0 else np.nan
    out["mfe_from_open"] = (m5h - m5o) / a if a > 0 else np.nan
    out["mae_from_open"] = (m5o - m5l) / a if a > 0 else np.nan
    tot = (m5h - m5o) + (m5o - m5l)
    out["exc_asym"] = ((m5h - m5o) - (m5o - m5l)) / tot if tot > 0 else 0.0

    # direction of the 0.50-ATR excursion drives the retracement geometry
    d50 = out["first_exc_dir_50"]
    ext, maxexc = m5o, 0.0
    if d50 != 0:
        stop = 5
        for k in range(5):
            run = (h[k] - m5o) if d50 > 0 else (m5o - l[k])
            maxexc = max(maxexc, run)
            # first M1 bar closing against the excursion direction
            if (d50 > 0 and c[k] < (c[k - 1] if k else m5o)) or \
               (d50 < 0 and c[k] > (c[k - 1] if k else m5o)):
                stop = k
                break
        ext = (m5o + d50 * maxexc)
        pre = 0.0
        for k in range(min(stop + 1, 5)):
            pre = max(pre, (h[k] - m5o) if d50 > 0 else (m5o - l[k]))
        out["max_exc_before_retrace"] = pre / a if a > 0 else np.nan
    else:
        out["max_exc_before_retrace"] = 0.0
    out["exc_extreme_atr"] = maxexc / a if a > 0 else np.nan
    # LEVEL features -- flagged for endpoint coupling
    out["retrace_frac"] = (((ext - m5c) / (ext - m5o)) if (d50 > 0 and ext > m5o)
                           else ((m5c - ext) / (m5o - ext)) if (d50 < 0 and ext < m5o)
                           else 0.0)
    rng = m5h - m5l
    out["final_close_in_range"] = (m5c - m5l) / rng if rng > 0 else 0.5

    dirs = np.sign(np.diff(np.r_[m5o, c]))
    out["n_dir_m1_closes"] = float((dirs == (d50 if d50 != 0 else 1)).sum())
    out["n_alternating"] = float((np.diff(dirs) != 0).sum())

    # ---- H2: frozen failed-excursion definition
    failed = 0.0
    if d50 != 0 and a > 0 and maxexc >= H2_EXC * a:
        retr = out["retrace_frac"]
        recovered = (m5c >= ext - 1e-9) if d50 > 0 else (m5c <= ext + 1e-9)
        if retr >= H2_RETRACE and not recovered:
            failed = d50
    out["h2_failed_exc"] = failed            # +1 up-excursion failed, -1 down, 0 none

    # ---- C. path sequencing category
    if d50 == 0:
        cat = "NO_EXC"
    else:
        side = "H" if d50 > 0 else "L"
        cat = f"{side}_FIRST_{'FAIL' if failed != 0 else 'HOLD'}"
    out["order_cat"] = cat
    return out


def permute_interior(o, h, l, c, perm):
    """Reorder M1 bars 2,3,4. Preserves M5 open/high/low/close and volume."""
    order = [0] + list(perm) + [4]
    return o[order], h[order], l[order], c[order]


def build(m5: pd.DataFrame, m1: pd.DataFrame, atr5: np.ndarray):
    t5 = pd.to_datetime(m5["time"], utc=True).to_numpy("datetime64[ns]")
    t1 = pd.to_datetime(m1["time"], utc=True).to_numpy("datetime64[ns]")
    o1, h1, l1, c1 = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    FIVE = np.timedelta64(5, "m")
    lo = np.searchsorted(t1, t5, side="left")
    hi = np.searchsorted(t1, t5 + FIVE, side="left")

    rows, perm_rows = [], []
    for i in range(len(t5)):
        a, b = lo[i], hi[i]
        rec = {"idx": i, "m1_complete": bool(b - a == 5)}
        ap = atr5[i - 1] if i > 0 else np.nan        # ATR known BEFORE bar i
        rec["atr_prior"] = float(ap) if np.isfinite(ap) else np.nan
        if (b - a == 5) and np.isfinite(ap) and ap > 0:
            O, H, L, C = o1[a:b], h1[a:b], l1[a:b], c1[a:b]
            rec.update(_path_features(O, H, L, C, float(ap)))
            rec["usable"] = True
            for pi, perm in enumerate(INTERIOR_PERMS):
                Op, Hp, Lp, Cp = permute_interior(O, H, L, C, perm)
                pf = _path_features(Op, Hp, Lp, Cp, float(ap))
                perm_rows.append({"idx": i, "perm": pi,
                                  "high_first": pf["high_first"],
                                  "low_first": pf["low_first"],
                                  "first_exc_dir_25": pf["first_exc_dir_25"],
                                  "first_exc_dir_50": pf["first_exc_dir_50"],
                                  "h2_failed_exc": pf["h2_failed_exc"]})
        else:
            rec["usable"] = False
        rows.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(perm_rows)


def add_memory(df: pd.DataFrame) -> pd.DataFrame:
    """Multi-bar causal path memory over the PREVIOUS k completed M5 bars."""
    hf = df["high_first"].to_numpy(float)
    lf = df["low_first"].to_numpy(float)
    e50 = df["first_exc_dir_50"].to_numpy(float)
    fail = df["h2_failed_exc"].to_numpy(float)
    rng = df["m5_range_atr"].to_numpy(float)
    rtr = df["retrace_frac"].to_numpy(float)
    for k in MEMORY_WINDOWS:
        s = lambda a: pd.Series(a).shift(1).rolling(k).sum().to_numpy()
        m = lambda a: pd.Series(a).shift(1).rolling(k).mean().to_numpy()
        df[f"hf_frac_{k}"] = m(hf)
        df[f"lf_frac_{k}"] = m(lf)
        df[f"exc_persist_{k}"] = m(e50)
        df[f"probe_up_{k}"] = s((e50 > 0).astype(float))
        df[f"probe_dn_{k}"] = s((e50 < 0).astype(float))
        df[f"reject_up_{k}"] = s((fail > 0).astype(float))
        df[f"reject_dn_{k}"] = s((fail < 0).astype(float))
        df[f"cum_exc_{k}"] = s(rng)
        df[f"cum_retrace_{k}"] = m(rtr)
        df[f"alt_count_{k}"] = s((np.r_[0.0, np.diff(e50)] != 0).astype(float))
    return df


def main() -> None:
    out = Path(sys.argv[1])
    m5 = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M5.csv", Timeframe.M5)
    m1 = load_bars_csv(REPO / "data" / "raw" / "XAUUSD_M1.csv", Timeframe.M1)
    feats = pd.read_pickle(sys.argv[2])
    atr5 = feats["atr_14"].to_numpy(float)

    df, perms = build(m5, m1, atr5)
    df = add_memory(df)
    df["time"] = pd.to_datetime(m5["time"], utc=True)
    df.to_pickle(out)
    perms.to_pickle(out.with_name(out.stem + "_perm" + out.suffix))

    u = df["usable"].to_numpy(bool)
    hfl = df.loc[u, "high_first"].to_numpy(float)
    # how often does interior permutation actually change the ordering?
    p = perms.merge(df[["idx", "high_first"]].rename(columns={"high_first": "hf_true"}),
                    on="idx")
    changed = float((p["high_first"] != p["hf_true"]).mean() * 100)
    meta = {
        "m5_rows": int(len(m5)), "m1_rows": int(len(m1)),
        "m1_complete": int(df["m1_complete"].sum()),
        "usable": int(u.sum()),
        "high_first_pct": float(hfl.mean() * 100),
        "hl_same_bar_pct": float(df.loc[u, "hl_same_bar"].mean() * 100),
        "first_exc_025_nonzero_pct": float((df.loc[u, "first_exc_dir_25"] != 0).mean() * 100),
        "first_exc_050_nonzero_pct": float((df.loc[u, "first_exc_dir_50"] != 0).mean() * 100),
        "first_exc_025_ambig_pct": float(df.loc[u, "first_exc_ambig_25"].mean() * 100),
        "first_exc_050_ambig_pct": float(df.loc[u, "first_exc_ambig_50"].mean() * 100),
        "h2_failed_pct": float((df.loc[u, "h2_failed_exc"] != 0).mean() * 100),
        "order_cat_counts": {k: int(v) for k, v in
                             df.loc[u, "order_cat"].value_counts().items()},
        "permutations_per_bar": len(INTERIOR_PERMS),
        "perm_changes_high_first_pct": changed,
        "level_features_flagged": ["final_close_in_range", "retrace_frac"],
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
