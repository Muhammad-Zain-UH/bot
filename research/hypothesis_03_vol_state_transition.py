"""Hypothesis 03 -- VOLATILITY-STATE TRANSITION.

Implements, literally and only, the pre-registration committed at 140df22:
research/hypothesis_03_vol_state_transition.md.

No production module is imported. No H01/H02 construct is used. Nothing outside
the pre-registered definitions is searched: one state variable, one window pair,
one threshold pair, one transition machine, three horizons, two transition types.

FINAL_OOS is never read, as data or as context. No threshold, window, horizon or
stratum boundary is refit on DEV.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import load_timeframe, verify_dataset          # noqa: E402
from research.phase1_statistical_controls import (                          # noqa: E402
    Weighting, benjamini_hochberg, bonferroni_t, block_stats, conditional_stat,
    contrast, forward_window_audit, non_overlapping_indices, raw_stats,
)

# --------------------------------------------------------- frozen definitions
N_SHORT = 4             # 1 hour
N_LONG = 96             # 24 hours
ATR_LEN = 14
PCT_HI = 80
PCT_LO = 20
DISP_WINDOW = 12
HORIZONS = {"1h": 4, "2h": 8, "4h": 16}
TRANSITIONS = ("EXPANSION", "CONTRACTION")
N_PRIMARY = 6                       # 2 transitions x 3 horizons
N_ACCUMULATED = 9                   # + 3 Phase 1 vol_transition cells (spec section 2)
ALPHA = 0.05

BOOTSTRAP_BLOCKS = (96, 480)
BOOTSTRAP_REPLICATES = 4000
BOOTSTRAP_SEED = 20261004
CAUSAL_PROBES = 60
CAUSAL_SEED = 20261004

# causal tolerances, frozen in spec section 13 from float64 precision alone
TOL_VOL_REL = 1e-13
TOL_RATIO_REL = 1e-13
TOL_DISP_REL = 1e-12
TOL_ATR_REL = 1e-12

SPREAD_USD = 0.33
COST_ATR = {"TRAIN": 0.158, "DEV": 0.093}
MIN_NONOVERLAPPING_N = 100

SPLIT = json.loads((Path(__file__).with_name("research_split_manifest.json")).read_text(encoding="utf-8"))
TRAIN_LO = pd.Timestamp(SPLIT["arms"]["TRAIN"]["from_utc"])
TRAIN_HI = pd.Timestamp(SPLIT["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(SPLIT["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])

HIGH, LOW, MID = 1, -1, 0


# ================================================================== features
def true_range(h: np.ndarray, lo: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Standard true range. TR[k] uses close[k-1], so it is causal at k."""
    prev = np.full(len(c), np.nan)
    prev[1:] = c[:-1]
    return np.maximum.reduce([h - lo, np.abs(h - prev), np.abs(lo - prev)])


def build_features(m15: pd.DataFrame) -> dict:
    """Every quantity is a function of bars at or before i-1. close[i] appears
    in nothing here -- it enters only the label, so feature and label share no
    price point (spec section 5.4)."""
    h, lo, c = (m15[k].to_numpy(float) for k in ("high", "low", "close"))
    tr = true_range(h, lo, c)
    s_tr = pd.Series(tr)
    short_vol = s_tr.rolling(N_SHORT).mean().shift(1).to_numpy(float)
    long_vol = s_tr.rolling(N_LONG).mean().shift(1).to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(np.isfinite(long_vol) & (long_vol > 0), short_vol / long_vol, np.nan)
    A = ta.atr(m15["high"], m15["low"], m15["close"], length=ATR_LEN).shift(1).to_numpy(float)
    c1 = np.full(len(c), np.nan); c1[1:] = c[:-1]                    # close[i-1]
    c13 = np.full(len(c), np.nan); c13[DISP_WINDOW + 1:] = c[:-(DISP_WINDOW + 1)]
    with np.errstate(invalid="ignore", divide="ignore"):
        disp = np.where(np.isfinite(A) & (A > 0), (c1 - c13) / A, np.nan)
    return {"high": h, "low": lo, "close": c, "tr": tr, "short_vol": short_vol,
            "long_vol": long_vol, "ratio": ratio, "A": A, "disp": disp}


def transition_events(state: np.ndarray, eligible: np.ndarray,
                      arm_mask: np.ndarray) -> dict:
    """The pre-registered machine (spec section 5.3).

    An event is the first crossing into a state after having been in the OPPOSITE
    state, so a genuine traversal of the MID band is required and expansion and
    contraction alternate strictly.
    """
    exp_, con, sup_hi, sup_lo = [], [], 0, 0
    last = None
    for i in np.flatnonzero(arm_mask & eligible):
        s = state[i]
        if s == HIGH:
            if last == LOW:
                exp_.append(int(i))
            elif last == HIGH:
                sup_hi += 1
            last = HIGH
        elif s == LOW:
            if last == HIGH:
                con.append(int(i))
            elif last == LOW:
                sup_lo += 1
            last = LOW
    return {"EXPANSION": np.array(exp_, np.int64), "CONTRACTION": np.array(con, np.int64),
            "suppressed_repeat_high": sup_hi, "suppressed_repeat_low": sup_lo}


# ================================================================ statistics
def cell_report(y: np.ndarray, idx: np.ndarray, h: int, label: str) -> dict:
    mask = np.zeros(len(y), bool)
    mask[idx] = True
    cs = conditional_stat(y, mask, h, label)
    d = cs.to_dict()
    keep = non_overlapping_indices(idx[np.isfinite(y[idx])], h)
    rs = raw_stats(y[keep])
    d["headline"]["sd"] = rs.get("sd")
    d["headline"]["median"] = rs.get("median")
    d["n_events_raw"] = int(np.isfinite(y[idx]).sum())
    d["n_events_non_overlapping"] = int(len(keep))
    d["below_min_n"] = bool(len(keep) < MIN_NONOVERLAPPING_N)
    return d


def block_bootstrap_mean(y: np.ndarray, mask: np.ndarray, block: int,
                         reps: int, seed: int) -> dict:
    """Moving-block bootstrap of the MEAN. Each replicate is
    OBSERVATION-weighted within the resampled blocks, so this is NOT the
    equal-block-mean estimator that failed in Phase 1."""
    ok = mask & np.isfinite(y)
    n = len(y)
    nb = int(np.ceil(n / block))
    edges = np.minimum(np.arange(nb + 1) * block, n)
    S = np.add.reduceat(np.where(ok, y, 0.0), edges[:-1])
    N = np.add.reduceat(ok.astype(float), edges[:-1])
    if N.sum() < 2:
        return {"block_bars": block, "mean": None, "se": None, "t": None}
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nb, size=(reps, nb))
    s, c = S[pick].sum(1), N[pick].sum(1)
    good = c > 0
    d = np.full(reps, np.nan)
    d[good] = s[good] / c[good]
    d = d[np.isfinite(d)]
    if len(d) < 100:
        return {"block_bars": block, "mean": None, "se": None, "t": None}
    point = float(S.sum() / N.sum())
    se = float(np.std(d, ddof=1))
    return {"block_bars": block, "replicates_used": int(len(d)),
            "mean_all_observations": round(point, 6), "se": round(se, 6),
            "t": (round(point / se, 4) if se > 0 else None),
            "ci95": [round(float(np.percentile(d, 2.5)), 6),
                     round(float(np.percentile(d, 97.5)), 6)],
            "weighting": "observation-weighted within resampled contiguous blocks"}


def stratified_contrast(y: np.ndarray, ev_idx: np.ndarray, non_idx: np.ndarray,
                        strata: np.ndarray, n_strata: int) -> dict:
    """Control 3: events vs non-events WITHIN frozen displacement quintiles.

    Aggregation is OBSERVATION-WEIGHTED by event count per stratum. It is never
    an equal-weighted mean of per-stratum means -- that is the Phase 1 failure --
    and the strata are frozen TRAIN feature quantiles, so their composition is
    not endogenous to the outcome.
    """
    rows, w, diffs, vars_ = [], [], [], []
    for s in range(n_strata):
        e = ev_idx[(strata[ev_idx] == s) & np.isfinite(y[ev_idx])]
        o = non_idx[(strata[non_idx] == s) & np.isfinite(y[non_idx])]
        if len(e) < 2 or len(o) < 2:
            rows.append({"stratum": s, "n_event": int(len(e)), "n_non_event": int(len(o)),
                         "diff": None})
            continue
        m1, m0 = float(y[e].mean()), float(y[o].mean())
        v = y[e].var(ddof=1) / len(e) + y[o].var(ddof=1) / len(o)
        rows.append({"stratum": s, "n_event": int(len(e)), "n_non_event": int(len(o)),
                     "mean_event": round(m1, 6), "mean_non_event": round(m0, 6),
                     "diff": round(m1 - m0, 6), "se": round(float(np.sqrt(v)), 6)})
        w.append(len(e)); diffs.append(m1 - m0); vars_.append(float(v))
    if not w:
        return {"strata": rows, "aggregate": None}
    w = np.array(w, float); w /= w.sum()
    diff = float(np.dot(w, diffs))
    se = float(np.sqrt(np.dot(w ** 2, vars_)))
    return {"strata": rows,
            "aggregate": {"diff": round(diff, 6), "se": round(se, 6),
                          "t": (round(diff / se, 4) if se > 0 else None),
                          "ci95": [round(diff - 1.96 * se, 6), round(diff + 1.96 * se, 6)],
                          "weighting": "observation-weighted by event count per stratum",
                          "n_strata_used": int(len(w))}}


# ====================================================================== main
def run(out_dir: Path) -> None:
    assert SPLIT["FINAL_OOS_LOCKED"] is True, "split manifest no longer declares the OOS lock"
    verify_dataset()

    m15 = load_timeframe("M15")
    m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
    assert m15["time"].max() <= DEV_HI, "M15 panel extends past the DEV boundary"
    n = len(m15)
    t = m15["time"]
    in_train = ((t >= TRAIN_LO) & (t <= TRAIN_HI)).to_numpy()
    in_dev = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
    arm_of = {"TRAIN": in_train, "DEV": in_dev}
    print(f"[data] M15 {n:,}  TRAIN {in_train.sum():,}  DEV {in_dev.sum():,}")

    F = build_features(m15)
    A, close, ratio, disp = F["A"], F["close"], F["ratio"], F["disp"]
    finite = (np.isfinite(ratio) & np.isfinite(A) & (A > 0) & np.isfinite(disp))
    eligible = finite & (in_train | in_dev)
    excluded = int(((in_train | in_dev) & ~finite).sum())

    # ---- thresholds and strata: TRAIN only, frozen ------------------------
    tr_ratio = ratio[finite & in_train]
    THETA_HI = float(np.percentile(tr_ratio, PCT_HI, method="linear"))
    THETA_LO = float(np.percentile(tr_ratio, PCT_LO, method="linear"))
    disp_cuts = [float(np.percentile(disp[finite & in_train], q, method="linear"))
                 for q in (20, 40, 60, 80)]
    print(f"[theta] TRAIN-only  THETA_HI({PCT_HI}) = {THETA_HI!r}")
    print(f"[theta] TRAIN-only  THETA_LO({PCT_LO}) = {THETA_LO!r}")
    print(f"[strata] TRAIN-only disp_12 quintile cuts = {[round(x,4) for x in disp_cuts]}")

    state = np.full(n, MID, np.int8)
    state[finite & (ratio >= THETA_HI)] = HIGH
    state[finite & (ratio <= THETA_LO)] = LOW
    strata = np.digitize(disp, disp_cuts).astype(np.int64)      # 0..4

    EV = {arm: transition_events(state, eligible, m) for arm, m in arm_of.items()}
    for arm in arm_of:
        e = EV[arm]
        print(f"[events] {arm}: EXPANSION {len(e['EXPANSION']):,}  "
              f"CONTRACTION {len(e['CONTRACTION']):,}   "
              f"(repeat-HIGH suppressed {e['suppressed_repeat_high']:,}, "
              f"repeat-LOW {e['suppressed_repeat_low']:,})")

    # ---- labels -----------------------------------------------------------
    S, MFE, MAE, same_arm = {}, {}, {}, {}
    for name, h in HORIZONS.items():
        f = np.full(n, np.nan); f[: n - h] = close[h:]
        with np.errstate(invalid="ignore"):
            S[name] = (f - close) / A
        hi_f = pd.Series(F["high"]).rolling(h).max().shift(-h).to_numpy(float)
        lo_f = pd.Series(F["low"]).rolling(h).min().shift(-h).to_numpy(float)
        with np.errstate(invalid="ignore"):
            MFE[name] = (hi_f - close) / A
            MAE[name] = (lo_f - close) / A
        sa = np.zeros(n, bool)
        for arm, m_arm in arm_of.items():
            src = np.flatnonzero(m_arm)
            ok = src[(src + h) < n]
            ok = ok[m_arm[ok + h]]
            sa[ok] = True
        same_arm[name] = sa
    sgn_disp = np.sign(disp)

    # ---- H1 regime --------------------------------------------------------
    h1 = load_timeframe("H1")
    h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)
    h1_sma = h1["close"].rolling(50).mean().to_numpy(float)
    h1_atr = ta.atr(h1["high"], h1["low"], h1["close"], length=ATR_LEN).to_numpy(float)
    with np.errstate(invalid="ignore"):
        h1_z = (h1["close"].to_numpy(float) - h1_sma) / h1_atr
    j = np.searchsorted((h1["time"] + pd.Timedelta(hours=1)).to_numpy("datetime64[ns]"),
                        (m15["time"] + pd.Timedelta(minutes=15)).to_numpy("datetime64[ns]"),
                        side="right") - 1
    z = np.where(j >= 50, h1_z[np.clip(j, 0, len(h1_z) - 1)], np.nan)
    zt = z[np.isfinite(z) & in_train]
    z_cuts = [float(np.percentile(zt, 100 / 3, method="linear")),
              float(np.percentile(zt, 200 / 3, method="linear"))]
    regime = np.where(~np.isfinite(z), "NA",
                      np.where(z < z_cuts[0], "BEARISH",
                               np.where(z > z_cuts[1], "BULLISH", "NEUTRAL")))
    print(f"[h1] TRAIN tercile cuts of z = {[round(x,4) for x in z_cuts]}")

    results: dict = {
        "hypothesis": "research/hypothesis_03_vol_state_transition.md",
        "preregistration_commit": "140df22",
        "gate": "research/RESEARCH_TO_STRATEGY_GATE.md",
        "prior_status": {"H01": "NOT SUPPORTED (45223cd)",
                         "H02": "INCONCLUSIVE / UNDERPOWERED (5230336)"},
        "declared_primary_hypotheses": N_PRIMARY,
        "accumulated_hypotheses": N_ACCUMULATED,
        "accumulated_note": ("6 declared + 3 Phase 1 vol_transition cells already spent on "
                             "this construct family. Promotion requires surviving the "
                             "accumulated-9 threshold (spec section 2)."),
        "frozen_definitions": {
            "n_short": N_SHORT, "n_long": N_LONG, "atr_length": ATR_LEN,
            "atr_convention": "A[i] = ATR_14[i-1]",
            "vol_ratio": "mean(TR over i-4..i-1) / mean(TR over i-96..i-1)",
            "pct_hi": PCT_HI, "pct_lo": PCT_LO,
            "THETA_HI": THETA_HI, "THETA_LO": THETA_LO,
            "disp_12": "(close[i-1] - close[i-13]) / A[i]",
            "disp_quintile_cuts_TRAIN": disp_cuts,
            "h1_z_tercile_cuts_TRAIN": z_cuts,
            "horizons_m15_bars": HORIZONS,
            "transition_rule": ("first crossing into a state after having been in the "
                                "OPPOSITE state; MID traversal required"),
            "endpoint_coupling": "NONE -- close[i] appears in no feature",
        },
        "dataset": {"dataset_sha256": SPLIT["dataset_sha256"], "fingerprints_verified": True,
                    "m15_rows": int(n), "panel_time_max": str(m15["time"].max()),
                    "dev_boundary": str(DEV_HI)},
        "arms": {"TRAIN": {"from": str(TRAIN_LO), "to": str(TRAIN_HI)},
                 "DEV": {"from": str(DEV_LO), "to": str(DEV_HI)},
                 "FINAL_OOS": "LOCKED - not read, not used as context"},
        "event_accounting": {
            "excluded_non_finite_features": excluded,
            "state_bar_counts": {arm: {"HIGH": int((state[eligible & m] == HIGH).sum()),
                                       "MID": int((state[eligible & m] == MID).sum()),
                                       "LOW": int((state[eligible & m] == LOW).sum())}
                                 for arm, m in arm_of.items()},
            "events": {arm: {tt: int(len(EV[arm][tt])) for tt in TRANSITIONS}
                       for arm in arm_of},
            "suppressed_repeats": {arm: {"HIGH": EV[arm]["suppressed_repeat_high"],
                                         "LOW": EV[arm]["suppressed_repeat_low"]}
                                   for arm in arm_of},
        },
        "primary": {}, "path_diagnostics": {}, "exploratory_disp_direction": {},
        "controls": {}, "h1_regime": {},
    }
    controls: dict = {"weighting_headline": Weighting.NON_OVERLAPPING,
                      "declared_primary": N_PRIMARY, "accumulated": N_ACCUMULATED,
                      "cells": {}}

    t_primary, t_keys = [], []
    for arm in ("TRAIN", "DEV", "POOLED"):
        for tt in TRANSITIONS:
            src = (np.concatenate([EV["TRAIN"][tt], EV["DEV"][tt]]) if arm == "POOLED"
                   else EV[arm][tt])
            if len(src) == 0:
                continue
            for name, h in HORIZONS.items():
                idx = src[same_arm[name][src]]
                if len(idx) == 0:
                    continue
                y = np.full(n, np.nan); y[idx] = S[name][idx]
                key = f"{arm}|{tt}@{name}"
                d = cell_report(y, idx, h, key)
                d["long_direction_mean"] = d["headline"]["mean"]
                d["short_direction_mean"] = (None if d["headline"]["mean"] is None
                                             else -d["headline"]["mean"])
                d["symmetry_note"] = ("long and short outcomes are exact negatives for a "
                                      "direction-less event; not two findings")
                d["bootstrap"] = {f"block_{b}": block_bootstrap_mean(
                    y, np.isin(np.arange(n), idx), b, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED + b)
                    for b in BOOTSTRAP_BLOCKS}
                d["equal_block_SECONDARY"] = block_stats(y[idx], idx, h)
                results["primary"][key] = d
                controls["cells"][key] = {"overlap": d["overlap"], "audit": d["audit"],
                                          "flags": d["flags"], "needs_review": d["needs_review"]}
                if arm == "TRAIN" and d["headline"].get("t") is not None:
                    t_primary.append(float(d["headline"]["t"])); t_keys.append(f"{tt}@{name}")

                mfe = MFE[name][idx]; mae = MAE[name][idx]
                results["path_diagnostics"][key] = {
                    "MFE_atr": raw_stats(mfe), "MAE_atr": raw_stats(mae),
                    "abs_asymmetry": (None if not np.isfinite(np.nanmean(mfe))
                                      else round(float(np.nanmean(mfe) + np.nanmean(mae)), 6)),
                    "note": "DESCRIPTIVE. No stop or target derived or selected."}

                ye = np.full(n, np.nan); ye[idx] = sgn_disp[idx] * S[name][idx]
                results["exploratory_disp_direction"][key] = {
                    **cell_report(ye, idx, h, "EXPLORATORY " + key)["headline"],
                    "label": "EXPLORATORY ONLY - cannot promote H03"}

    # ---- controls ---------------------------------------------------------
    for arm in ("TRAIN", "DEV"):
        m_arm = arm_of[arm]
        for tt in TRANSITIONS:
            ev = EV[arm][tt]
            if len(ev) == 0:
                continue
            st_target = HIGH if tt == "EXPANSION" else LOW
            for name, h in HORIZONS.items():
                key = f"{arm}|{tt}@{name}"
                idx = ev[same_arm[name][ev]]
                if len(idx) == 0:
                    continue
                y = S[name]
                pool = np.flatnonzero(m_arm & eligible & same_arm[name] & np.isfinite(y))
                is_ev = np.zeros(n, bool); is_ev[idx] = True

                # 1 unconditional
                keep_u = non_overlapping_indices(pool, h)
                c1 = {**raw_stats(y[keep_u]), "n_non_overlapping": int(len(keep_u)),
                      "weighting": "non-overlapping over all eligible bars"}

                # 2 same state, no transition
                same_state = np.flatnonzero(m_arm & eligible & same_arm[name]
                                            & (state == st_target) & ~is_ev & np.isfinite(y))
                c2 = None
                if len(same_state) >= 2:
                    yy = np.full(n, np.nan)
                    yy[idx] = y[idx]; yy[same_state] = y[same_state]
                    mh = np.zeros(n, bool); mh[idx] = True
                    ml = np.zeros(n, bool); ml[same_state] = True
                    ct = contrast(yy, mh, ml, h, label=f"C2_{key}")
                    c2 = {"event": {k: ct["hi"]["headline"][k] for k in ("n", "mean", "se", "t")},
                          "same_state_no_transition": {k: ct["lo"]["headline"][k]
                                                       for k in ("n", "mean", "se", "t")},
                          "headline_diff": ct.get("headline_diff"), "flags": ct["flags"]}

                # 3 matched displacement stratum -- the decisive control
                keep_e = non_overlapping_indices(idx[np.isfinite(y[idx])], h)
                non_ev = np.flatnonzero(m_arm & eligible & same_arm[name] & ~is_ev & np.isfinite(y))
                keep_o = non_overlapping_indices(non_ev, h)
                c3 = stratified_contrast(y, keep_e, keep_o, strata, 5)

                # 4 opposite transition
                other = "CONTRACTION" if tt == "EXPANSION" else "EXPANSION"
                oidx = EV[arm][other]
                oidx = oidx[same_arm[name][oidx]] if len(oidx) else oidx
                c4 = None
                if len(oidx) >= 2:
                    yy = np.full(n, np.nan)
                    yy[idx] = y[idx]; yy[oidx] = y[oidx]
                    mh = np.zeros(n, bool); mh[idx] = True
                    ml = np.zeros(n, bool); ml[oidx] = True
                    ct = contrast(yy, mh, ml, h, label=f"C4_{key}")
                    c4 = {"headline_diff": ct.get("headline_diff"),
                          "this": {k: ct["hi"]["headline"][k] for k in ("n", "mean", "t")},
                          "opposite": {k: ct["lo"]["headline"][k] for k in ("n", "mean", "t")},
                          "flags": ct["flags"]}

                results["controls"][key] = {
                    "C1_unconditional": c1, "C2_same_state_no_transition": c2,
                    "C3_matched_displacement_stratum": c3, "C4_opposite_transition": c4}

                # 5 H1 regime
                reg = {}
                for r in ("BULLISH", "NEUTRAL", "BEARISH"):
                    sub = idx[regime[idx] == r]
                    if len(sub) >= 2:
                        kp = non_overlapping_indices(sub[np.isfinite(y[sub])], h)
                        reg[r] = {**raw_stats(y[kp]), "n_non_overlapping": int(len(kp))}
                results["h1_regime"][key] = reg

    # ---- multiple testing -------------------------------------------------
    def mt_block(nt: int) -> dict:
        padded = list(t_primary) + [0.0] * max(0, nt - len(t_primary))
        pv = [math.erfc(abs(v) / math.sqrt(2)) for v in padded]
        thr = bonferroni_t(nt, ALPHA)
        return {"n_tests": nt, "bonferroni_threshold_t": round(thr, 4),
                "survivors_bonferroni": [k for k, v in zip(t_keys, t_primary) if abs(v) >= thr],
                "benjamini_hochberg": benjamini_hochberg(pv, ALPHA),
                "expected_abs_t_ge_2_under_null": round(0.0455 * nt, 4)}
    results["multiple_testing"] = {
        "primary_arm": "TRAIN", "two_sided": True,
        "t_values": {k: round(v, 4) for k, v in zip(t_keys, t_primary)},
        "max_abs_t": (round(max(abs(v) for v in t_primary), 4) if t_primary else None),
        "observed_abs_t_ge_2": int(sum(1 for v in t_primary if abs(v) >= 2)),
        "declared_6": mt_block(N_PRIMARY),
        "accumulated_9_PROMOTION_TEST": mt_block(N_ACCUMULATED)}

    # ---- power and cost ---------------------------------------------------
    thr_acc = results["multiple_testing"]["accumulated_9_PROMOTION_TEST"]["bonferroni_threshold_t"]
    power = {}
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                d = results["primary"].get(f"{arm}|{tt}@{name}")
                if not d:
                    continue
                se = (d.get("headline") or {}).get("se")
                if se and se == se:
                    mde = thr_acc * se
                    gross = d["headline"]["mean"]
                    power[f"{arm}|{tt}@{name}"] = {
                        "non_overlapping_n": d["n_events_non_overlapping"],
                        "below_min_n_100": d["below_min_n"], "se": round(se, 5),
                        "mde_2se_atr": round(2 * se, 4),
                        "mde_corrected_atr": round(mde, 4),
                        "cost_atr": COST_ATR[arm],
                        "gross_mean_atr": round(gross, 6),
                        "abs_gross_minus_cost_atr": round(abs(gross) - COST_ATR[arm], 6),
                        "can_detect_cost_sized_effect": bool(mde <= COST_ATR[arm])}
    results["power_and_cost"] = {
        "round_turn_convention": "1 x spread", "spread_usd": SPREAD_USD,
        "cost_atr_by_arm": COST_ATR, "cells": power,
        "note": ("Cost is reported alongside power as the authorisation requires. Net "
                 "figures are NOT expected returns and must not be read as such for a "
                 "cell that failed the statistical screen.")}

    # ---- causal reconstruction -------------------------------------------
    allev = np.concatenate([EV["TRAIN"]["EXPANSION"], EV["TRAIN"]["CONTRACTION"],
                            EV["DEV"]["EXPANSION"], EV["DEV"]["CONTRACTION"]])
    rng = np.random.default_rng(CAUSAL_SEED)
    pick = np.sort(rng.choice(allev, size=min(CAUSAL_PROBES, len(allev)), replace=False))
    dv = {"short_vol": 0.0, "long_vol": 0.0, "ratio": 0.0, "disp": 0.0, "atr": 0.0}
    bad = {"state": 0, "event": 0}
    margins = []
    for i in pick:
        pre = m15.iloc[: int(i)]
        hh, ll, cc = (pre[k].to_numpy(float) for k in ("high", "low", "close"))
        tr2 = true_range(hh, ll, cc)
        sv = float(np.mean(tr2[-N_SHORT:])); lv = float(np.mean(tr2[-N_LONG:]))
        r2 = sv / lv
        a2 = float(ta.atr(pre["high"], pre["low"], pre["close"], length=ATR_LEN).iloc[-1])
        d2 = (cc[-1] - cc[-1 - DISP_WINDOW]) / a2
        dv["short_vol"] = max(dv["short_vol"], abs(sv - F["short_vol"][i]) / abs(F["short_vol"][i]))
        dv["long_vol"] = max(dv["long_vol"], abs(lv - F["long_vol"][i]) / abs(F["long_vol"][i]))
        dv["ratio"] = max(dv["ratio"], abs(r2 - ratio[i]) / abs(ratio[i]))
        dv["atr"] = max(dv["atr"], abs(a2 - A[i]) / abs(A[i]))
        dv["disp"] = max(dv["disp"], abs(d2 - disp[i]) / max(abs(disp[i]), 1e-12))
        s2 = HIGH if r2 >= THETA_HI else (LOW if r2 <= THETA_LO else MID)
        if s2 != state[i]:
            bad["state"] += 1
            margins.append(min(abs(r2 - THETA_HI) / THETA_HI, abs(r2 - THETA_LO) / THETA_LO))
    passed = (dv["short_vol"] <= TOL_VOL_REL and dv["long_vol"] <= TOL_VOL_REL
              and dv["ratio"] <= TOL_RATIO_REL and dv["atr"] <= TOL_ATR_REL
              and dv["disp"] <= TOL_DISP_REL and sum(bad.values()) == 0)
    controls["causal_reconstruction"] = {
        "probes": int(len(pick)), "seed": CAUSAL_SEED,
        "frozen_tolerances": {"short_long_vol_relative": TOL_VOL_REL,
                              "vol_ratio_relative": TOL_RATIO_REL,
                              "disp_relative": TOL_DISP_REL, "atr_relative": TOL_ATR_REL,
                              "classifications": "0 disagreements"},
        "observed": {**{k: v for k, v in dv.items()}, "classification_disagreements": bad,
                     "threshold_margins": margins},
        "PASS": bool(passed),
        "method": "rebuilt from m15.iloc[:i] (bars 0..i-1) and compared with the panel at i"}
    print(f"[causal] {dv}  bad={bad}  PASS={passed}")

    controls["forward_window_audits"] = {}
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            ev = EV[arm][tt]
            for name, h in HORIZONS.items():
                if len(ev) == 0:
                    continue
                idx = ev[same_arm[name][ev]]
                keep = non_overlapping_indices(idx[np.isfinite(S[name][idx])], h)
                controls["forward_window_audits"][f"{arm}|{tt}@{name}"] = \
                    forward_window_audit(keep, h)
    controls["sign_disagreement_cells"] = [
        k for k, v in controls["cells"].items()
        if "ESTIMATOR_SIGN_DISAGREEMENT" in (v.get("flags") or [])]
    controls["no_feature_mining"] = {
        "window_pairs_tested": [[N_SHORT, N_LONG]], "percentile_pairs_tested": [[PCT_LO, PCT_HI]],
        "horizons_tested": sorted(HORIZONS.values()), "transition_types": list(TRANSITIONS),
        "disp_windows_tested": [DISP_WINDOW],
        "statement": ("One state variable, one window pair, one threshold pair, one "
                      "transition machine, three horizons, two transition types.")}
    controls["dev_tuning"] = {"thresholds_refit_on_dev": False,
                              "strata_refit_on_dev": False,
                              "h1_cuts_refit_on_dev": False}
    controls["final_oos"] = {"opened": False, "panel_truncated_at": str(DEV_HI),
                             "token": "OOS-AUTHORISATION-NOT-ISSUED"}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hypothesis_03_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "hypothesis_03_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")

    # --------------------------------------------------------------- console
    W = 104
    print("\n" + "=" * W); print("EVENT ACCOUNTING"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        sc = results["event_accounting"]["state_bar_counts"][arm]
        ec = results["event_accounting"]["events"][arm]
        sr = results["event_accounting"]["suppressed_repeats"][arm]
        tot = sum(sc.values())
        print(f"  {arm:5s} bars HIGH {sc['HIGH']:6,} ({100*sc['HIGH']/tot:5.2f}%)  "
              f"MID {sc['MID']:6,}  LOW {sc['LOW']:6,} ({100*sc['LOW']/tot:5.2f}%)")
        print(f"        events  EXPANSION {ec['EXPANSION']:4,}   CONTRACTION {ec['CONTRACTION']:4,}"
              f"   suppressed repeats HIGH {sr['HIGH']:5,} LOW {sr['LOW']:5,}")
    print(f"  THETA_HI {THETA_HI:.6f}   THETA_LO {THETA_LO:.6f}"
          f"   excluded (non-finite features) {excluded:,}")

    print("\n" + "=" * W)
    print("PRIMARY -- E[S_h] two-sided, raw SIGNED return, NON-OVERLAPPING events")
    print("=" * W)
    print(f"  {'cell':26s} {'raw n':>6s} {'non-ov':>7s} {'ov':>5s} {'mean':>9s} {'median':>9s}"
          f" {'sd':>6s} {'se':>7s} {'t':>7s}  95% CI")
    for arm in ("TRAIN", "DEV", "POOLED"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                d = results["primary"].get(f"{arm}|{tt}@{name}")
                if not d or d["headline"].get("t") is None:
                    continue
                hd, o, ci = d["headline"], d["overlap"], d["headline"]["ci95"]
                fl = " [n<100]" if d["below_min_n"] else ""
                print(f"  {arm}|{tt}@{name:16s}"[:28] + f" {d['n_events_raw']:6,} "
                      f"{d['n_events_non_overlapping']:7,} {o['overlap_ratio']:4.1f}x "
                      f"{hd['mean']:+9.4f} {hd['median']:+9.4f} {hd['sd']:6.3f} {hd['se']:7.4f} "
                      f"{hd['t']:+7.2f}  [{ci[0]:+.4f}, {ci[1]:+.4f}]{fl}")

    print("\n" + "=" * W); print("MULTIPLE TESTING (primary arm TRAIN, two-sided)"); print("=" * W)
    mt = results["multiple_testing"]
    print(f"  t values: {mt['t_values']}")
    print(f"  max |t| {mt['max_abs_t']}   observed |t|>=2 {mt['observed_abs_t_ge_2']}")
    for lbl, k in (("declared 6", "declared_6"), ("ACCUMULATED 9 (promotion)", "accumulated_9_PROMOTION_TEST")):
        b = mt[k]
        print(f"  {lbl:28s} Bonferroni |t|>={b['bonferroni_threshold_t']:.3f}  "
              f"survivors {len(b['survivors_bonferroni'])} {b['survivors_bonferroni']}  "
              f"BH {b['benjamini_hochberg'].get('n_survivors')}")

    print("\n" + "=" * W); print("CONTROL 3 -- matched displacement stratum (DECISIVE)"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                c = (results["controls"].get(f"{arm}|{tt}@{name}") or {}).get(
                    "C3_matched_displacement_stratum") or {}
                ag = c.get("aggregate")
                if not ag:
                    continue
                print(f"  {arm}|{tt}@{name:4s} diff {ag['diff']:+.4f} se {ag['se']:.4f} "
                      f"t {ag['t']:+.2f}  CI [{ag['ci95'][0]:+.4f}, {ag['ci95'][1]:+.4f}]  "
                      f"strata {ag['n_strata_used']}")

    print("\n" + "=" * W); print("CONTROLS 1 / 2 / 4"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                c = results["controls"].get(f"{arm}|{tt}@{name}")
                d = results["primary"].get(f"{arm}|{tt}@{name}")
                if not c or not d:
                    continue
                c2 = (c.get("C2_same_state_no_transition") or {}).get("headline_diff")
                c4 = (c.get("C4_opposite_transition") or {}).get("headline_diff")
                print(f"  {arm}|{tt}@{name:4s} event {d['headline']['mean']:+.4f} | "
                      f"C1 uncond {c['C1_unconditional']['mean']:+.4f} | "
                      f"C2 vs same-state diff "
                      + (f"{c2['diff']:+.4f} (t {c2['t']:+.2f})" if c2 else "n/a")
                      + " | C4 vs opposite diff "
                      + (f"{c4['diff']:+.4f} (t {c4['t']:+.2f})" if c4 else "n/a"))

    print("\n" + "=" * W); print("PATH DIAGNOSTICS -- volatility-only vs directional"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                p = results["path_diagnostics"].get(f"{arm}|{tt}@{name}")
                if not p:
                    continue
                print(f"  {arm}|{tt}@{name:4s} MFE {p['MFE_atr']['mean']:+.3f}  "
                      f"MAE {p['MAE_atr']['mean']:+.3f}  |MFE|-|MAE| {p['abs_asymmetry']:+.4f}")

    print("\n" + "=" * W); print("POWER AND COST"); print("=" * W)
    for k, v in power.items():
        print(f"  {k:26s} n={v['non_overlapping_n']:4,}{' [n<100]' if v['below_min_n_100'] else '        '}"
              f" se {v['se']:.4f}  MDE(2se) {v['mde_2se_atr']:.3f}  "
              f"MDE(corr) {v['mde_corrected_atr']:.3f}  cost {v['cost_atr']}  "
              f"detectable={v['can_detect_cost_sized_effect']}")

    print("\n" + "=" * W); print("H1 REGIME CONDITIONING"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for tt in TRANSITIONS:
            for name in HORIZONS:
                r = results["h1_regime"].get(f"{arm}|{tt}@{name}")
                if not r:
                    continue
                parts = [f"{k[:4]} n={v['n_non_overlapping']:3d} {v['mean']:+.3f}"
                         for k, v in r.items()]
                print(f"  {arm}|{tt}@{name:4s} " + "  ".join(parts))

    print("\n" + "=" * W); print("CONTROLS SUMMARY"); print("=" * W)
    cr = controls["causal_reconstruction"]
    print(f"  causal reconstruction PASS={cr['PASS']}  observed {cr['observed']}")
    print(f"  ESTIMATOR_SIGN_DISAGREEMENT cells: {len(controls['sign_disagreement_cells'])}"
          f" {controls['sign_disagreement_cells']}")
    nd = [k for k, v in controls["forward_window_audits"].items() if not v["disjoint"]]
    print(f"  forward-window audits non-disjoint: {len(nd)} {nd}")
    print(f"  DEV tuning: {controls['dev_tuning']}")
    print(f"  FINAL_OOS opened: {controls['final_oos']['opened']}")
    print(f"\n  wrote {out_dir/'hypothesis_03_results.json'}")
    print(f"  wrote {out_dir/'hypothesis_03_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
