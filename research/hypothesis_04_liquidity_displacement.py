"""Hypothesis 04 -- LIQUIDITY DISPLACEMENT -> ACCEPTANCE / REJECTION.

Implements, literally and only, the pre-registration committed at 43dc34c:
research/hypothesis_04_liquidity_displacement.md.

No production module is imported. No H01/H02/H03 construct is used. M5/M1 are not
used. Nothing outside the pre-registered definitions is searched.

Timeline (spec section 5):
    area        bars e-27 .. e-4      highs/lows only
    displacement bars e-3  .. e
    classify    bars e+1  .. e+4      closes vs a boundary fixed at e-4
    label       anchor open[e+5], exit close[e+4+h]
Feature period <= e+4, label period >= e+5: disjoint, sharing no price point.
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
    Weighting, benjamini_hochberg, block_stats, bonferroni_t, conditional_stat,
    contrast, forward_window_audit, non_overlapping_indices, raw_stats,
)

# ---------------------------------------------------------- frozen definitions
AREA_LOOKBACK = 24      # a, bars e-27..e-4  (6 hours)
DISP_INTERVAL = 4       # d, bars e-3..e     (1 hour)
ACCEPT_WINDOW = 4       # w, bars e+1..e+4   (1 hour)
ATR_LEN = 14
TAU_PCT = 80            # TRAIN-only displacement threshold percentile
RECENT_DISP_WINDOW = 12
HORIZONS = {"1h": 4, "2h": 8, "4h": 16}
STATES = ("LONG_ACCEPT", "LONG_REJECT", "SHORT_ACCEPT", "SHORT_REJECT")
N_DECLARED = 12
N_ACCUMULATED = 30      # 12 declared + 18 prior displacement cells (spec section 2)
N_PROGRAMME = 138       # 126 prior tests on this TRAIN arm + 12 declared
ALPHA = 0.05

BOOTSTRAP_BLOCKS = (96, 480)
BOOTSTRAP_REPLICATES = 4000
BOOTSTRAP_SEED = 20261005
CAUSAL_PROBES = 60
CAUSAL_SEED = 20261005

TOL_AREA = 0.0          # max/min performs no arithmetic
TOL_REL = 1e-12         # ATR-derived quantities

SPREAD_USD = 0.33
COST_ATR = {"TRAIN": 0.158, "DEV": 0.093}
MIN_NONOVERLAPPING_N = 100

SPLIT = json.loads((Path(__file__).with_name("research_split_manifest.json")).read_text(encoding="utf-8"))
TRAIN_LO = pd.Timestamp(SPLIT["arms"]["TRAIN"]["from_utc"])
TRAIN_HI = pd.Timestamp(SPLIT["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(SPLIT["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])


# ==================================================================== features
def build_features(m15: pd.DataFrame) -> dict:
    """All detection quantities are functions of bars at or before e.
    open[e+w+1] -- the label anchor -- is read by nothing here."""
    o, h, lo, c = (m15[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    A = ta.atr(m15["high"], m15["low"], m15["close"], length=ATR_LEN).shift(1).to_numpy(float)
    # area over bars e-d-a+1 .. e-d
    prior_high = m15["high"].rolling(AREA_LOOKBACK).max().shift(DISP_INTERVAL).to_numpy(float)
    prior_low = m15["low"].rolling(AREA_LOOKBACK).min().shift(DISP_INTERVAL).to_numpy(float)
    n = len(c)
    c_d = np.full(n, np.nan); c_d[DISP_INTERVAL:] = c[:-DISP_INTERVAL]          # close[e-d]
    k = DISP_INTERVAL + RECENT_DISP_WINDOW
    c_dk = np.full(n, np.nan); c_dk[k:] = c[:-k]                                # close[e-d-12]
    A_d = np.full(n, np.nan); A_d[DISP_INTERVAL:] = A[:-DISP_INTERVAL]           # A[e-d]
    with np.errstate(invalid="ignore", divide="ignore"):
        disp_size = np.where(np.isfinite(A) & (A > 0), np.abs(c - c_d) / A, np.nan)
        recent_disp = np.where(np.isfinite(A_d) & (A_d > 0), (c_d - c_dk) / A_d, np.nan)
    direction = np.where(c > c_d, 1.0, np.where(c < c_d, -1.0, 0.0))
    return {"open": o, "high": h, "low": lo, "close": c, "A": A,
            "prior_high": prior_high, "prior_low": prior_low,
            "disp_size": disp_size, "recent_disp": recent_disp, "direction": direction}


def find_events(F: dict, TAU: float, eligible: np.ndarray, arm_mask: np.ndarray,
                n: int) -> dict:
    """The pre-registered machine with its declared precedence rule (spec s.10).

    The EARLIER episode wins: a qualifying displacement at or before
    last_event_e + w is suppressed and counted, never allowed to pre-empt the
    episode in progress. A new event also requires the condition to have been
    absent for at least one bar. Reads only the feature stream.
    """
    c, ph, pl = F["close"], F["prior_high"], F["prior_low"]
    dirn, ds = F["direction"], F["disp_size"]
    raw = retained = 0
    sup_not_armed = sup_in_window = ambiguous = 0
    out: list[tuple[int, int]] = []
    armed = True
    last_e = -(10 ** 9)
    for e in np.flatnonzero(arm_mask & eligible):
        big = ds[e] >= TAU
        up = big and dirn[e] > 0 and c[e] > ph[e]
        dn = big and dirn[e] < 0 and c[e] < pl[e]
        if up and dn:
            ambiguous += 1
            continue
        if up or dn:
            raw += 1
            if not armed:
                sup_not_armed += 1
            elif e <= last_e + ACCEPT_WINDOW:
                sup_in_window += 1
            else:
                out.append((int(e), 1 if up else -1))
                last_e = e
                retained += 1
            armed = False
        else:
            armed = True
    return {"events": out, "raw": raw, "retained": retained,
            "suppressed_not_armed": sup_not_armed,
            "suppressed_within_unresolved_window": sup_in_window,
            "ambiguous": ambiguous}


def classify(F: dict, e: int, d: int) -> bool:
    """True = ACCEPTANCE. Boundary fixed at detection; closes of bars e+1..e+w
    only. Fully determined at the close of bar e+w."""
    c = F["close"]
    B = F["prior_high"][e] if d > 0 else F["prior_low"][e]
    for k in range(e + 1, e + ACCEPT_WINDOW + 1):
        if d > 0 and c[k] <= B:
            return False
        if d < 0 and c[k] >= B:
            return False
    return True


# ================================================================== statistics
def cell_report(y: np.ndarray, idx: np.ndarray, h: int, label: str) -> dict:
    mask = np.zeros(len(y), bool); mask[idx] = True
    cs = conditional_stat(y, mask, h, label)
    d = cs.to_dict()
    keep = non_overlapping_indices(idx[np.isfinite(y[idx])], h)
    rs = raw_stats(y[keep])
    d["headline"]["sd"] = rs.get("sd"); d["headline"]["median"] = rs.get("median")
    d["n_events_raw"] = int(np.isfinite(y[idx]).sum())
    d["n_events_non_overlapping"] = int(len(keep))
    d["below_min_n"] = bool(len(keep) < MIN_NONOVERLAPPING_N)
    return d


def bootstrap_mean(y: np.ndarray, idx: np.ndarray, block: int, reps: int, seed: int) -> dict:
    mask = np.zeros(len(y), bool); mask[idx] = True
    ok = mask & np.isfinite(y)
    n = len(y); nb = int(np.ceil(n / block))
    edges = np.minimum(np.arange(nb + 1) * block, n)
    S = np.add.reduceat(np.where(ok, y, 0.0), edges[:-1])
    N = np.add.reduceat(ok.astype(float), edges[:-1])
    if N.sum() < 2:
        return {"block_bars": block, "mean": None, "se": None, "t": None}
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nb, size=(reps, nb))
    s, cnt = S[pick].sum(1), N[pick].sum(1)
    good = cnt > 0
    dd = np.full(reps, np.nan); dd[good] = s[good] / cnt[good]
    dd = dd[np.isfinite(dd)]
    if len(dd) < 100:
        return {"block_bars": block, "mean": None, "se": None, "t": None}
    point = float(S.sum() / N.sum()); se = float(np.std(dd, ddof=1))
    return {"block_bars": block, "replicates_used": int(len(dd)),
            "mean_all_observations": round(point, 6), "se": round(se, 6),
            "t": (round(point / se, 4) if se > 0 else None),
            "ci95_percentile": [round(float(np.percentile(dd, 2.5)), 6),
                                round(float(np.percentile(dd, 97.5)), 6)],
            "weighting": "observation-weighted within resampled contiguous blocks"}


def stratified_accept_vs_reject(y: np.ndarray, acc: np.ndarray, rej: np.ndarray,
                                strata: np.ndarray, n_strata: int) -> dict:
    """Baselines D and E. Acceptance vs rejection WITHIN frozen TRAIN quintiles,
    aggregated observation-weighted by the SMALLER class count per stratum, as
    declared. Never an equal-weighted mean of per-stratum means."""
    rows, w, diffs, vars_ = [], [], [], []
    for s in range(n_strata):
        a = acc[(strata[acc] == s) & np.isfinite(y[acc])]
        r = rej[(strata[rej] == s) & np.isfinite(y[rej])]
        if len(a) < 2 or len(r) < 2:
            rows.append({"stratum": s, "n_accept": int(len(a)), "n_reject": int(len(r)),
                         "diff": None})
            continue
        m1, m0 = float(y[a].mean()), float(y[r].mean())
        v = y[a].var(ddof=1) / len(a) + y[r].var(ddof=1) / len(r)
        rows.append({"stratum": s, "n_accept": int(len(a)), "n_reject": int(len(r)),
                     "mean_accept": round(m1, 6), "mean_reject": round(m0, 6),
                     "diff": round(m1 - m0, 6), "se": round(float(np.sqrt(v)), 6)})
        w.append(min(len(a), len(r))); diffs.append(m1 - m0); vars_.append(float(v))
    if not w:
        return {"strata": rows, "aggregate": None}
    w = np.array(w, float); w /= w.sum()
    diff = float(np.dot(w, diffs)); se = float(np.sqrt(np.dot(w ** 2, vars_)))
    return {"strata": rows,
            "aggregate": {"diff": round(diff, 6), "se": round(se, 6),
                          "t": (round(diff / se, 4) if se > 0 else None),
                          "ci95": [round(diff - 1.96 * se, 6), round(diff + 1.96 * se, 6)],
                          "weighting": "observation-weighted by min(n_accept, n_reject) per stratum",
                          "n_strata_used": int(len(w))}}


# ======================================================================== main
def run(out_dir: Path) -> None:
    assert SPLIT["FINAL_OOS_LOCKED"] is True, "split manifest no longer declares the OOS lock"
    verify_dataset()

    m15 = load_timeframe("M15")
    m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
    assert m15["time"].max() <= DEV_HI, "M15 panel extends past the DEV boundary"
    n = len(m15)
    tcol = m15["time"]
    in_train = ((tcol >= TRAIN_LO) & (tcol <= TRAIN_HI)).to_numpy()
    in_dev = ((tcol >= DEV_LO) & (tcol <= DEV_HI)).to_numpy()
    arm_of = {"TRAIN": in_train, "DEV": in_dev}
    print(f"[data] M15 {n:,}  TRAIN {in_train.sum():,}  DEV {in_dev.sum():,}")

    F = build_features(m15)
    A, close, op = F["A"], F["close"], F["open"]
    finite = (np.isfinite(F["prior_high"]) & np.isfinite(F["prior_low"])
              & np.isfinite(A) & (A > 0) & np.isfinite(F["disp_size"])
              & np.isfinite(F["recent_disp"]))
    eligible = finite & (in_train | in_dev)

    TAU = float(np.percentile(F["disp_size"][finite & in_train], TAU_PCT, method="linear"))
    # Baseline D must match displacement magnitude WITHIN the event population.
    # Whole-population quintiles are degenerate here: every event satisfies
    # disp_size >= TAU, and TAU *is* the 80th-percentile cut, so all events land in
    # one bin and the control performs no matching. The cut points are therefore
    # the quintiles of disp_size among TRAIN EVENTS -- still TRAIN-only, still
    # frozen before DEV, and now actually stratifying. Disclosed in the report.
    _tr_ev = find_events(F, TAU, eligible, in_train, len(F["close"]))["events"]
    _tr_ds = np.array([F["disp_size"][e] for e, _ in _tr_ev], float)
    ds_cuts = [float(np.percentile(_tr_ds, q, method="linear")) for q in (20, 40, 60, 80)]
    ds_cuts_population_DEGENERATE = [
        float(np.percentile(F["disp_size"][finite & in_train], q, method="linear"))
        for q in (20, 40, 60, 80)]
    rd_cuts = [float(np.percentile(F["recent_disp"][finite & in_train], q, method="linear"))
               for q in (20, 40, 60, 80)]
    print(f"[tau] TRAIN-only {TAU_PCT}th pct of displacement_size = {TAU!r}")

    EV = {arm: find_events(F, TAU, eligible, m, n) for arm, m in arm_of.items()}

    # ---- classification, validity, labels --------------------------------
    same_arm = {}
    for name, h in HORIZONS.items():
        sa = np.zeros(n, bool)
        for arm, m_arm in arm_of.items():
            src = np.flatnonzero(m_arm)
            ok = src[(src + h) < n]
            ok = ok[m_arm[ok + h]]
            sa[ok] = True
        same_arm[name] = sa

    recs: dict[str, list[dict]] = {}
    invalid = {arm: 0 for arm in arm_of}
    for arm, m_arm in arm_of.items():
        rr = []
        for (e, d) in EV[arm]["events"]:
            anchor = e + ACCEPT_WINDOW + 1
            last = e + ACCEPT_WINDOW
            if last >= n or anchor >= n or not m_arm[last] or not m_arm[anchor]:
                invalid[arm] += 1; continue
            if not (np.isfinite(A[anchor]) and A[anchor] > 0 and np.isfinite(op[anchor])):
                invalid[arm] += 1; continue
            acc = classify(F, e, d)
            rr.append({"e": e, "d": d, "anchor": anchor, "accept": acc,
                       "state": ("LONG" if d > 0 else "SHORT") + ("_ACCEPT" if acc else "_REJECT"),
                       "pred": (d if acc else -d),
                       "disp_size": float(F["disp_size"][e]),
                       "recent_disp": float(F["recent_disp"][e])})
        recs[arm] = rr
        na = sum(1 for r in rr if r["accept"])
        print(f"[events] {arm}: raw {EV[arm]['raw']:,} retained {EV[arm]['retained']:,} "
              f"valid {len(rr):,}  ACCEPT {na:,} REJECT {len(rr)-na:,}  "
              f"(sup_not_armed {EV[arm]['suppressed_not_armed']:,}, "
              f"sup_in_window {EV[arm]['suppressed_within_unresolved_window']:,}, "
              f"ambiguous {EV[arm]['ambiguous']}, invalid {invalid[arm]})")

    def label(anchors: np.ndarray, sgn: np.ndarray, h: int, coupled: bool = False) -> np.ndarray:
        """R_h (or C_h, by the sign passed). coupled=True uses close[e+w] as the
        anchor instead of open[e+w+1] -- the endpoint-coupling audit only."""
        y = np.full(n, np.nan)
        base = close[anchors - 1] if coupled else op[anchors]
        ex = np.full(len(anchors), np.nan)
        ok = (anchors + h - 1) < n
        ex[ok] = close[(anchors + h - 1)[ok]]
        with np.errstate(invalid="ignore"):
            y[anchors] = sgn * (ex - base) / A[anchors]
        return y

    def dollars(anchors: np.ndarray, sgn: np.ndarray, h: int) -> np.ndarray:
        ex = np.full(len(anchors), np.nan)
        ok = (anchors + h - 1) < n
        ex[ok] = close[(anchors + h - 1)[ok]]
        return sgn * (ex - op[anchors])

    # ---- H1 regime --------------------------------------------------------
    h1 = load_timeframe("H1"); h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)
    h1_sma = h1["close"].rolling(50).mean().to_numpy(float)
    h1_atr = ta.atr(h1["high"], h1["low"], h1["close"], length=ATR_LEN).to_numpy(float)
    with np.errstate(invalid="ignore"):
        h1z = (h1["close"].to_numpy(float) - h1_sma) / h1_atr
    jj = np.searchsorted((h1["time"] + pd.Timedelta(hours=1)).to_numpy("datetime64[ns]"),
                         (m15["time"] + pd.Timedelta(minutes=15)).to_numpy("datetime64[ns]"),
                         side="right") - 1
    zz = np.where(jj >= 50, h1z[np.clip(jj, 0, len(h1z) - 1)], np.nan)
    ztr = zz[np.isfinite(zz) & in_train]
    z_cuts = [float(np.percentile(ztr, 100 / 3, method="linear")),
              float(np.percentile(ztr, 200 / 3, method="linear"))]
    regime = np.where(~np.isfinite(zz), "NA",
                      np.where(zz < z_cuts[0], "BEARISH",
                               np.where(zz > z_cuts[1], "BULLISH", "NEUTRAL")))

    results: dict = {
        "hypothesis": "research/hypothesis_04_liquidity_displacement.md",
        "preregistration_commit": "43dc34c",
        "gate": "research/RESEARCH_TO_STRATEGY_GATE.md",
        "prior_status": {"H01": "NOT SUPPORTED (45223cd)",
                         "H02": "INCONCLUSIVE / UNDERPOWERED (5230336)",
                         "H03": "NOT SUPPORTED (7b59b95)"},
        "declared_hypotheses": N_DECLARED, "accumulated_hypotheses": N_ACCUMULATED,
        "programme_wide_tests": N_PROGRAMME,
        "frozen_definitions": {
            "area_lookback_bars": AREA_LOOKBACK, "disp_interval_bars": DISP_INTERVAL,
            "accept_window_bars": ACCEPT_WINDOW, "atr_length": ATR_LEN,
            "atr_convention": "A[k] = ATR_14[k-1]",
            "tau_percentile": TAU_PCT, "TAU": TAU,
            "disp_size_quintile_cuts_TRAIN_EVENTS": ds_cuts,
            "disp_size_quintile_cuts_TRAIN_POPULATION_degenerate": ds_cuts_population_DEGENERATE,
            "baseline_D_note": ("stratified within the EVENT population; whole-population "
                                "quintiles put every event in one bin because TAU is the "
                                "80th-percentile cut"),
            "recent_disp_quintile_cuts_TRAIN": rd_cuts,
            "h1_z_tercile_cuts_TRAIN": z_cuts,
            "horizons_m15_bars": HORIZONS,
            "label_anchor": "open[e+w+1] -- read by no feature",
            "label_exit": "close[e+w+h]",
            "timeline": "area e-27..e-4 | disp e-3..e | classify e+1..e+4 | label >= e+5"},
        "dataset": {"dataset_sha256": SPLIT["dataset_sha256"], "fingerprints_verified": True,
                    "m15_rows": int(n), "panel_time_max": str(m15["time"].max()),
                    "dev_boundary": str(DEV_HI)},
        "arms": {"TRAIN": {"from": str(TRAIN_LO), "to": str(TRAIN_HI)},
                 "DEV": {"from": str(DEV_LO), "to": str(DEV_HI)},
                 "FINAL_OOS": "LOCKED - not read, not used as context"},
        "event_accounting": {arm: {**{k: v for k, v in EV[arm].items() if k != "events"},
                                   "valid": len(recs[arm]), "invalid": invalid[arm],
                                   "accept": sum(1 for r in recs[arm] if r["accept"]),
                                   "reject": sum(1 for r in recs[arm] if not r["accept"]),
                                   "acceptance_rate_pct": (round(100 * sum(1 for r in recs[arm] if r["accept"])
                                                                 / max(len(recs[arm]), 1), 2))}
                             for arm in arm_of},
        "primary": {}, "pooled_summaries": {}, "path_diagnostics": {},
        "baselines": {}, "h1_regime": {}, "timeline_examples": {},
    }
    controls: dict = {"weighting_headline": Weighting.NON_OVERLAPPING,
                      "declared": N_DECLARED, "accumulated": N_ACCUMULATED,
                      "programme_wide": N_PROGRAMME, "cells": {}}

    strata_ds = np.digitize(F["disp_size"], ds_cuts).astype(np.int64)
    strata_rd = np.digitize(F["recent_disp"], rd_cuts).astype(np.int64)

    t_primary, t_keys = [], []
    for arm in ("TRAIN", "DEV", "POOLED"):
        rr = (recs["TRAIN"] + recs["DEV"]) if arm == "POOLED" else recs[arm]
        if not rr:
            continue
        for st in STATES:
            sub = [r for r in rr if r["state"] == st]
            if len(sub) < 2:
                continue
            anch = np.array([r["anchor"] for r in sub], np.int64)
            pred = np.array([r["pred"] for r in sub], float)
            for name, h in HORIZONS.items():
                sel = same_arm[name][anch]
                aa, pp = anch[sel], pred[sel]
                if len(aa) < 2:
                    continue
                y = label(aa, pp, h)
                key = f"{arm}|{st}@{name}"
                d = cell_report(y, aa, h, key)
                d["raw_dollars_mean"] = round(float(np.nanmean(dollars(aa, pp, h))), 6)
                d["bootstrap"] = {f"block_{b}": bootstrap_mean(y, aa, b, BOOTSTRAP_REPLICATES,
                                                               BOOTSTRAP_SEED + b)
                                  for b in BOOTSTRAP_BLOCKS}
                d["equal_block_SECONDARY"] = block_stats(y[aa], aa, h)
                results["primary"][key] = d
                controls["cells"][key] = {"overlap": d["overlap"], "audit": d["audit"],
                                          "flags": d["flags"], "needs_review": d["needs_review"]}
                if arm == "TRAIN" and d["headline"].get("t") is not None:
                    t_primary.append(float(d["headline"]["t"])); t_keys.append(f"{st}@{name}")
                mfe = np.full(len(aa), np.nan); mae = np.full(len(aa), np.nan)
                for q, (a0, s0) in enumerate(zip(aa, pp)):
                    hi = F["high"][a0:a0 + h].max(); lov = F["low"][a0:a0 + h].min()
                    base = op[a0]
                    up = (hi - base) / A[a0]; dn = (lov - base) / A[a0]
                    mfe[q] = up if s0 > 0 else -dn
                    mae[q] = dn if s0 > 0 else -up
                results["path_diagnostics"][key] = {
                    "MFE_atr": raw_stats(mfe), "MAE_atr": raw_stats(mae),
                    "note": "DESCRIPTIVE. No stop or target derived or selected."}

        # pooled ACCEPT / REJECT summaries -- declared summaries, not extra tests
        for grp, pick_f in (("ACCEPT", lambda r: r["accept"]), ("REJECT", lambda r: not r["accept"])):
            sub = [r for r in rr if pick_f(r)]
            if len(sub) < 2:
                continue
            anch = np.array([r["anchor"] for r in sub], np.int64)
            pred = np.array([r["pred"] for r in sub], float)
            for name, h in HORIZONS.items():
                sel = same_arm[name][anch]
                aa, pp = anch[sel], pred[sel]
                if len(aa) < 2:
                    continue
                results["pooled_summaries"][f"{arm}|{grp}@{name}"] = {
                    **cell_report(label(aa, pp, h), aa, h, f"pooled {grp}")["headline"],
                    "note": "declared summary of the same cells; NOT an additional test"}

    # ---- baselines --------------------------------------------------------
    for arm in ("TRAIN", "DEV"):
        m_arm = arm_of[arm]
        rr = recs[arm]
        if not rr:
            continue
        acc = np.array([r["anchor"] for r in rr if r["accept"]], np.int64)
        rej = np.array([r["anchor"] for r in rr if not r["accept"]], np.int64)
        d_acc = np.array([r["d"] for r in rr if r["accept"]], float)
        d_rej = np.array([r["d"] for r in rr if not r["accept"]], float)
        all_a = np.array([r["anchor"] for r in rr], np.int64)
        all_d = np.array([r["d"] for r in rr], float)
        all_p = np.array([r["pred"] for r in rr], float)

        # baseline C population: big displacement, NO area interaction
        c, ph, pl = F["close"], F["prior_high"], F["prior_low"]
        nobreak = (eligible & m_arm & (F["disp_size"] >= TAU)
                   & ~(((F["direction"] > 0) & (c > ph)) | ((F["direction"] < 0) & (c < pl)))
                   & (F["direction"] != 0))
        nb_e = np.flatnonzero(nobreak)
        nb_e = nb_e[(nb_e + ACCEPT_WINDOW + 1) < n]
        nb_anchor = nb_e + ACCEPT_WINDOW + 1
        keepmask = m_arm[nb_anchor] & np.isfinite(A[nb_anchor]) & (A[nb_anchor] > 0)
        nb_anchor, nb_d = nb_anchor[keepmask], F["direction"][nb_e][keepmask]

        for name, h in HORIZONS.items():
            key = f"{arm}@{name}"
            selA = same_arm[name][all_a]
            # A -- unconditional, side-matched in the pred direction
            pool = np.flatnonzero(m_arm & eligible & same_arm[name]
                                  & np.isfinite(A) & (A > 0))
            pa = pool[(pool + h - 1) < n]
            with np.errstate(invalid="ignore"):
                unc = (close[pa + h - 1] - op[pa]) / A[pa]
            q_long = float((all_p[selA] > 0).mean()) if selA.any() else 0.0
            bl_a = {"long_side_mean": round(float(np.nanmean(unc)), 6),
                    "short_side_mean": round(float(np.nanmean(-unc)), 6),
                    "q_pred_long": round(q_long, 4),
                    "side_matched_mean": round(q_long * float(np.nanmean(unc))
                                               + (1 - q_long) * float(np.nanmean(-unc)), 6),
                    "n_pool": int(len(pa)),
                    "weighting": "all eligible bars, overlapping (reference only)"}

            # B -- all displacement+break events in the DISPLACEMENT direction
            aa, dd = all_a[selA], all_d[selA]
            bl_b = cell_report(label(aa, dd, h), aa, h, f"B_{key}")["headline"] if len(aa) >= 2 else None

            # C -- big displacement WITHOUT area interaction, displacement direction
            selC = same_arm[name][nb_anchor] if len(nb_anchor) else np.array([], bool)
            ca, cd = (nb_anchor[selC], nb_d[selC]) if len(nb_anchor) else (nb_anchor, nb_d)
            bl_c = cell_report(label(ca, cd, h), ca, h, f"C_{key}")["headline"] if len(ca) >= 2 else None
            # incremental: break vs no-break, both in displacement direction
            inc_bc = None
            if len(aa) >= 2 and len(ca) >= 2:
                yy = np.full(n, np.nan)
                yy[aa] = label(aa, dd, h)[aa]; yy[ca] = label(ca, cd, h)[ca]
                mh = np.zeros(n, bool); mh[aa] = True
                ml = np.zeros(n, bool); ml[ca] = True
                ct = contrast(yy, mh, ml, h, label=f"BC_{key}")
                inc_bc = {"headline_diff": ct.get("headline_diff"), "flags": ct["flags"]}

            # accept vs reject, displacement direction -- the incremental claim
            sa_ = same_arm[name][acc] if len(acc) else np.array([], bool)
            sr_ = same_arm[name][rej] if len(rej) else np.array([], bool)
            A_a, A_d2 = (acc[sa_], d_acc[sa_]) if len(acc) else (acc, d_acc)
            R_a, R_d2 = (rej[sr_], d_rej[sr_]) if len(rej) else (rej, d_rej)
            inc_ar = None
            yC = np.full(n, np.nan)
            if len(A_a) >= 2 and len(R_a) >= 2:
                yC[A_a] = label(A_a, A_d2, h)[A_a]
                yC[R_a] = label(R_a, R_d2, h)[R_a]
                mh = np.zeros(n, bool); mh[A_a] = True
                ml = np.zeros(n, bool); ml[R_a] = True
                ct = contrast(yC, mh, ml, h, label=f"AR_{key}")
                inc_ar = {"accept": {k: ct["hi"]["headline"][k] for k in ("n", "mean", "se", "t")},
                          "reject": {k: ct["lo"]["headline"][k] for k in ("n", "mean", "se", "t")},
                          "headline_diff": ct.get("headline_diff"),
                          "bootstrap": {f"block_{b}": None for b in BOOTSTRAP_BLOCKS},
                          "flags": ct["flags"]}

            # D / E -- matched strata, accept vs reject on C_h
            kA = non_overlapping_indices(A_a[np.isfinite(yC[A_a])], h) if len(A_a) else np.array([], np.int64)
            kR = non_overlapping_indices(R_a[np.isfinite(yC[R_a])], h) if len(R_a) else np.array([], np.int64)
            ev_e = {r["anchor"]: r["e"] for r in rr}
            st_ds = np.zeros(n, np.int64); st_rd = np.zeros(n, np.int64)
            for a0, e0 in ev_e.items():
                st_ds[a0] = strata_ds[e0]; st_rd[a0] = strata_rd[e0]
            bl_d = stratified_accept_vs_reject(yC, kA, kR, st_ds, 5) if len(kA) and len(kR) else None
            bl_e = stratified_accept_vs_reject(yC, kA, kR, st_rd, 5) if len(kA) and len(kR) else None

            results["baselines"][key] = {
                "A_unconditional_side_matched": bl_a,
                "B_all_displacement_break_events": bl_b,
                "C_displacement_without_area_interaction": bl_c,
                "incremental_break_vs_nobreak": inc_bc,
                "incremental_accept_vs_reject": inc_ar,
                "D_matched_displacement_magnitude": bl_d,
                "E_matched_recent_displacement": bl_e}

        # H1 regime
        for st in STATES:
            sub = [r for r in rr if r["state"] == st]
            if len(sub) < 2:
                continue
            anch = np.array([r["anchor"] for r in sub], np.int64)
            pred = np.array([r["pred"] for r in sub], float)
            for name, h in HORIZONS.items():
                sel = same_arm[name][anch]
                aa, pp = anch[sel], pred[sel]
                if len(aa) < 2:
                    continue
                y = label(aa, pp, h)
                reg = {}
                for rname in ("BULLISH", "NEUTRAL", "BEARISH"):
                    s2 = aa[regime[aa] == rname]
                    if len(s2) >= 2:
                        kp = non_overlapping_indices(s2[np.isfinite(y[s2])], h)
                        reg[rname] = {**raw_stats(y[kp]), "n_non_overlapping": int(len(kp))}
                results["h1_regime"][f"{arm}|{st}@{name}"] = reg

    # ---- multiple testing -------------------------------------------------
    def mt(nt: int) -> dict:
        padded = list(t_primary) + [0.0] * max(0, nt - len(t_primary))
        pv = [math.erfc(abs(v) / math.sqrt(2)) for v in padded]
        thr = bonferroni_t(nt, ALPHA)
        return {"n_tests": nt, "bonferroni_threshold_t": round(thr, 4),
                "survivors_bonferroni": [k for k, v in zip(t_keys, t_primary) if abs(v) >= thr],
                "benjamini_hochberg": benjamini_hochberg(pv, ALPHA),
                "expected_abs_t_ge_2_under_null": round(0.0455 * nt, 4)}
    results["multiple_testing"] = {
        "primary_arm": "TRAIN", "one_sided_hypothesis": "E[R_h] > 0 per state",
        "t_values": {k: round(v, 4) for k, v in zip(t_keys, t_primary)},
        "max_abs_t": (round(max(abs(v) for v in t_primary), 4) if t_primary else None),
        "observed_abs_t_ge_2": int(sum(1 for v in t_primary if abs(v) >= 2)),
        "declared_12": mt(N_DECLARED),
        "accumulated_30_PROMOTION_TEST": mt(N_ACCUMULATED),
        "programme_wide_138_DISCLOSED": mt(N_PROGRAMME)}

    thr_acc = results["multiple_testing"]["accumulated_30_PROMOTION_TEST"]["bonferroni_threshold_t"]
    power = {}
    for arm in ("TRAIN", "DEV"):
        for st in STATES:
            for name in HORIZONS:
                d = results["primary"].get(f"{arm}|{st}@{name}")
                if not d:
                    continue
                se = (d.get("headline") or {}).get("se")
                if se and se == se:
                    g = d["headline"]["mean"]
                    power[f"{arm}|{st}@{name}"] = {
                        "non_overlapping_n": d["n_events_non_overlapping"],
                        "below_min_n_100": d["below_min_n"], "se": round(se, 5),
                        "mde_2se_atr": round(2 * se, 4),
                        "mde_corrected_atr": round(thr_acc * se, 4),
                        "cost_atr": COST_ATR[arm], "gross_atr": round(g, 6),
                        "net_atr": round(g - COST_ATR[arm], 6),
                        "gross_dollars": d["raw_dollars_mean"],
                        "net_dollars": round(d["raw_dollars_mean"] - SPREAD_USD, 6),
                        "can_detect_cost_sized_effect": bool(thr_acc * se <= COST_ATR[arm])}
    results["power_and_cost"] = {
        "round_turn_convention": "1 x spread", "spread_usd": SPREAD_USD,
        "cost_atr_by_arm": COST_ATR, "cells": power,
        "note": ("Cost reported alongside power as the authorisation requires. Net figures "
                 "are NOT expected returns for a cell that failed the statistical screen.")}

    # ---- endpoint-coupling audit -----------------------------------------
    feat_reads = {"prior_high/low": "high,low of bars e-27..e-4",
                  "disp_size": "close[e], close[e-4], ATR_14[e-1]",
                  "direction": "close[e], close[e-4]",
                  "recent_disp": "close[e-4], close[e-16], ATR_14[e-5]",
                  "acceptance": "close of bars e+1..e+4, boundary fixed at e-4",
                  "max feature bar index": "e+4"}
    lab_reads = {"anchor": "open[e+5]", "exit": "close[e+4+h]",
                 "normaliser": "ATR_14[e+4]  (feature-period, numerator-disjoint)",
                 "min label price bar index": "e+5"}
    coupled_cmp = {}
    for arm in ("TRAIN", "DEV"):
        rr = recs[arm]
        for st in STATES:
            sub = [r for r in rr if r["state"] == st]
            if len(sub) < 2:
                continue
            anch = np.array([r["anchor"] for r in sub], np.int64)
            pred = np.array([r["pred"] for r in sub], float)
            for name, h in HORIZONS.items():
                sel = same_arm[name][anch]
                aa, pp = anch[sel], pred[sel]
                if len(aa) < 2:
                    continue
                clean = cell_report(label(aa, pp, h), aa, h, "clean")["headline"]
                cpl = cell_report(label(aa, pp, h, coupled=True), aa, h, "coupled")["headline"]
                coupled_cmp[f"{arm}|{st}@{name}"] = {
                    "clean_open_anchor_mean": clean["mean"], "clean_t": clean["t"],
                    "coupled_close_anchor_mean": cpl["mean"], "coupled_t": cpl["t"],
                    "sign_agrees": (None if clean["mean"] is None or cpl["mean"] is None
                                    else (clean["mean"] > 0) == (cpl["mean"] > 0))}
    controls["endpoint_coupling_audit"] = {
        "structural": {"feature_reads": feat_reads, "label_reads": lab_reads,
                       "shared_price_point": False,
                       "assertion": ("max feature bar index e+4 < min label price bar index e+5; "
                                     "open[e+5] is read by no feature")},
        "empirical_coupled_anchor_comparison": coupled_cmp,
        "note": "DECLARED AUDIT, 0 hypotheses. The coupled anchor cannot promote the candidate."}

    # ---- causal reconstruction -------------------------------------------
    allrec = recs["TRAIN"] + recs["DEV"]
    rng = np.random.default_rng(CAUSAL_SEED)
    pk = rng.choice(len(allrec), size=min(CAUSAL_PROBES, len(allrec)), replace=False)
    dv = {"area": 0.0, "disp_size": 0.0, "recent_disp": 0.0, "atr": 0.0}
    bad = {"direction": 0, "break": 0, "acceptance": 0}
    margins = []
    for q in sorted(pk):
        r = allrec[q]; e = r["e"]
        pre = m15.iloc[:e]
        a2 = float(ta.atr(pre["high"], pre["low"], pre["close"], length=ATR_LEN).iloc[-1])
        # bars e-27..e-4 inclusive. In `pre` (bars 0..e-1) bar e-4 sits at index -4,
        # so the half-open slice is [-(d+a-1) : -(d-1)] = [-27:-3]; verified against
        # the rolling definition rather than assumed.
        lo_s, hi_s = -(DISP_INTERVAL + AREA_LOOKBACK - 1), -(DISP_INTERVAL - 1)
        ph2 = float(pre["high"].iloc[lo_s:hi_s].max())
        pl2 = float(pre["low"].iloc[lo_s:hi_s].min())
        assert len(pre["high"].iloc[lo_s:hi_s]) == AREA_LOOKBACK
        cc = pre["close"].to_numpy(float)
        ds2 = abs(close[e] - cc[-DISP_INTERVAL]) / a2
        rd2 = (cc[-DISP_INTERVAL] - cc[-(DISP_INTERVAL + RECENT_DISP_WINDOW)]) / \
              float(ta.atr(m15["high"].iloc[:e - DISP_INTERVAL], m15["low"].iloc[:e - DISP_INTERVAL],
                           m15["close"].iloc[:e - DISP_INTERVAL], length=ATR_LEN).iloc[-1])
        dv["area"] = max(dv["area"], abs(ph2 - F["prior_high"][e]), abs(pl2 - F["prior_low"][e]))
        dv["atr"] = max(dv["atr"], abs(a2 - A[e]) / abs(A[e]))
        dv["disp_size"] = max(dv["disp_size"], abs(ds2 - F["disp_size"][e]) / abs(F["disp_size"][e]))
        dv["recent_disp"] = max(dv["recent_disp"],
                                abs(rd2 - F["recent_disp"][e]) / max(abs(F["recent_disp"][e]), 1e-12))
        d2 = 1 if close[e] > cc[-DISP_INTERVAL] else (-1 if close[e] < cc[-DISP_INTERVAL] else 0)
        if d2 != r["d"]:
            bad["direction"] += 1
        brk = (close[e] > ph2) if r["d"] > 0 else (close[e] < pl2)
        if not brk:
            bad["break"] += 1
        if ds2 < TAU:
            margins.append(abs(ds2 - TAU) / TAU)
        B = ph2 if r["d"] > 0 else pl2
        acc2 = all((close[k] > B) if r["d"] > 0 else (close[k] < B)
                   for k in range(e + 1, e + ACCEPT_WINDOW + 1))
        if acc2 != r["accept"]:
            bad["acceptance"] += 1
    passed = (dv["area"] <= TOL_AREA and dv["atr"] <= TOL_REL
              and dv["disp_size"] <= TOL_REL and dv["recent_disp"] <= TOL_REL
              and sum(bad.values()) == 0)
    controls["causal_reconstruction"] = {
        "probes": int(len(pk)), "seed": CAUSAL_SEED,
        "frozen_tolerances": {"area_abs": TOL_AREA, "atr_relative": TOL_REL,
                              "disp_size_relative": TOL_REL, "recent_disp_relative": TOL_REL,
                              "classifications": "0 disagreements"},
        "observed": {**dv, "classification_disagreements": bad, "threshold_margins": margins},
        "PASS": bool(passed),
        "method": "rebuilt from m15.iloc[:e] (bars 0..e-1) and compared with the panel"}
    print(f"[causal] {dv} bad={bad} PASS={passed}")

    # ---- worked timeline examples ----------------------------------------
    for want_d, nm in ((1, "LONG"), (-1, "SHORT")):
        ex = next((r for r in recs["TRAIN"] if r["d"] == want_d), None)
        if not ex:
            continue
        e = ex["e"]
        B = F["prior_high"][e] if want_d > 0 else F["prior_low"][e]
        results["timeline_examples"][nm] = {
            "state": ex["state"], "direction": nm,
            "area_bars": f"{e-DISP_INTERVAL-AREA_LOOKBACK+1}..{e-DISP_INTERVAL}",
            "area_times": [str(m15['time'].iloc[e-DISP_INTERVAL-AREA_LOOKBACK+1]),
                           str(m15['time'].iloc[e-DISP_INTERVAL])],
            "PRIOR_HIGH": round(float(F["prior_high"][e]), 3),
            "PRIOR_LOW": round(float(F["prior_low"][e]), 3),
            "boundary_used": round(float(B), 3),
            "disp_bars": f"{e-DISP_INTERVAL+1}..{e}",
            "close_e_minus_d": round(float(close[e-DISP_INTERVAL]), 3),
            "close_e": round(float(close[e]), 3),
            "A_e": round(float(A[e]), 4),
            "disp_size": round(float(F["disp_size"][e]), 4), "TAU": round(TAU, 4),
            "classify_bars": f"{e+1}..{e+ACCEPT_WINDOW}",
            "classify_closes": [round(float(close[k]), 3)
                                for k in range(e+1, e+ACCEPT_WINDOW+1)],
            "classification": "ACCEPTANCE" if ex["accept"] else "REJECTION",
            "label_anchor_bar": e+ACCEPT_WINDOW+1,
            "label_anchor_open": round(float(op[e+ACCEPT_WINDOW+1]), 3),
            "label_anchor_time": str(m15['time'].iloc[e+ACCEPT_WINDOW+1]),
            "predicted_direction": ex["pred"],
            "separation": "max feature bar e+4 < label anchor bar e+5"}

    controls["forward_window_audits"] = {}
    for arm in ("TRAIN", "DEV"):
        for st in STATES:
            sub = [r for r in recs[arm] if r["state"] == st]
            if len(sub) < 2:
                continue
            anch = np.array([r["anchor"] for r in sub], np.int64)
            pred = np.array([r["pred"] for r in sub], float)
            for name, h in HORIZONS.items():
                sel = same_arm[name][anch]
                aa = anch[sel]
                if len(aa) < 2:
                    continue
                y = label(aa, pred[sel], h)
                controls["forward_window_audits"][f"{arm}|{st}@{name}"] = \
                    forward_window_audit(non_overlapping_indices(aa[np.isfinite(y[aa])], h), h)
    controls["sign_disagreement_cells"] = [
        k for k, v in controls["cells"].items()
        if "ESTIMATOR_SIGN_DISAGREEMENT" in (v.get("flags") or [])]
    controls["no_feature_mining"] = {
        "area_lookbacks_tested": [AREA_LOOKBACK], "disp_intervals_tested": [DISP_INTERVAL],
        "tau_percentiles_tested": [TAU_PCT], "accept_windows_tested": [ACCEPT_WINDOW],
        "atr_lengths_tested": [ATR_LEN], "horizons_tested": sorted(HORIZONS.values()),
        "states": list(STATES),
        "statement": ("One area lookback, one displacement interval, one threshold "
                      "percentile, one acceptance window, one ATR length, three "
                      "horizons, four states. No alternative computed.")}
    controls["dev_tuning"] = {"tau_refit_on_dev": False, "strata_refit_on_dev": False,
                              "h1_cuts_refit_on_dev": False}
    controls["m5_m1_used"] = False
    controls["final_oos"] = {"opened": False, "panel_truncated_at": str(DEV_HI),
                             "token": "OOS-AUTHORISATION-NOT-ISSUED"}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hypothesis_04_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "hypothesis_04_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")

    # --------------------------------------------------------------- console
    W = 108
    print("\n" + "=" * W); print("EVENT ACCOUNTING / DEDUPLICATION"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        a = results["event_accounting"][arm]
        print(f"  {arm:5s} raw {a['raw']:5,}  retained {a['retained']:5,}  valid {a['valid']:5,}"
              f"  ACCEPT {a['accept']:4,} ({a['acceptance_rate_pct']:5.2f}%)  REJECT {a['reject']:4,}")
        print(f"        suppressed: not-armed {a['suppressed_not_armed']:5,}  "
              f"within-unresolved-window {a['suppressed_within_unresolved_window']:4,}  "
              f"ambiguous {a['ambiguous']}  invalid {a['invalid']}")
    print(f"  TAU (TRAIN {TAU_PCT}th pct of displacement_size) = {TAU:.6f}")

    print("\n" + "=" * W)
    print("PRIMARY -- E[R_h] > 0, direction-normalised, NON-OVERLAPPING events")
    print("=" * W)
    print(f"  {'cell':30s} {'raw':>5s} {'n-ov':>5s} {'ov':>5s} {'mean':>9s} {'med':>8s}"
          f" {'sd':>6s} {'se':>7s} {'t':>7s} {'$':>8s}")
    for arm in ("TRAIN", "DEV", "POOLED"):
        for st in STATES:
            for name in HORIZONS:
                d = results["primary"].get(f"{arm}|{st}@{name}")
                if not d or d["headline"].get("t") is None:
                    continue
                hd = d["headline"]
                fl = "*" if d["below_min_n"] else " "
                print(f"  {arm}|{st}@{name}"[:31].ljust(32)
                      + f"{d['n_events_raw']:5,} {d['n_events_non_overlapping']:5,}{fl}"
                      f"{d['overlap']['overlap_ratio']:4.1f}x {hd['mean']:+9.4f} {hd['median']:+8.4f}"
                      f" {hd['sd']:6.3f} {hd['se']:7.4f} {hd['t']:+7.2f} {d['raw_dollars_mean']:+8.3f}")
    print("  * = fewer than 100 non-overlapping events (INCONCLUSIVE by the standing rule)")

    print("\n" + "=" * W); print("MULTIPLE TESTING (primary arm TRAIN)"); print("=" * W)
    m = results["multiple_testing"]
    print(f"  t values: {m['t_values']}")
    print(f"  max |t| {m['max_abs_t']}   observed |t|>=2 {m['observed_abs_t_ge_2']}")
    for lbl, k in (("declared 12", "declared_12"),
                   ("ACCUMULATED 30 (promotion)", "accumulated_30_PROMOTION_TEST"),
                   ("programme-wide 138 (disclosed)", "programme_wide_138_DISCLOSED")):
        b = m[k]
        print(f"  {lbl:32s} |t|>={b['bonferroni_threshold_t']:.3f}  survivors "
              f"{len(b['survivors_bonferroni'])} {b['survivors_bonferroni']}  "
              f"BH {b['benjamini_hochberg'].get('n_survivors')}")

    print("\n" + "=" * W); print("BASELINES -- incremental tests"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            b = results["baselines"].get(f"{arm}@{name}")
            if not b:
                continue
            bb = b["B_all_displacement_break_events"]; cc2 = b["C_displacement_without_area_interaction"]
            ibc = (b["incremental_break_vs_nobreak"] or {}).get("headline_diff")
            iar = (b["incremental_accept_vs_reject"] or {}).get("headline_diff")
            dd = (b["D_matched_displacement_magnitude"] or {}).get("aggregate")
            ee = (b["E_matched_recent_displacement"] or {}).get("aggregate")
            print(f"  {arm}@{name:3s} A uncond {b['A_unconditional_side_matched']['side_matched_mean']:+.4f}"
                  f" | B break {bb['mean']:+.4f} (t {bb['t']:+.2f})"
                  f" | C no-break {cc2['mean']:+.4f} (t {cc2['t']:+.2f})")
            print(f"           break-vs-nobreak "
                  + (f"{ibc['diff']:+.4f} (t {ibc['t']:+.2f})" if ibc else "n/a")
                  + " | ACCEPT-vs-REJECT "
                  + (f"{iar['diff']:+.4f} (t {iar['t']:+.2f})" if iar else "n/a"))
            print(f"           D matched-magnitude "
                  + (f"{dd['diff']:+.4f} (t {dd['t']:+.2f})" if dd else "n/a")
                  + " | E matched-recent-disp "
                  + (f"{ee['diff']:+.4f} (t {ee['t']:+.2f})" if ee else "n/a"))

    print("\n" + "=" * W); print("POWER AND COST"); print("=" * W)
    for k, v in power.items():
        print(f"  {k[:30]:30s} n={v['non_overlapping_n']:4,}{'*' if v['below_min_n_100'] else ' '}"
              f" se {v['se']:.4f} MDE(corr) {v['mde_corrected_atr']:.3f} cost {v['cost_atr']}"
              f" gross {v['gross_atr']:+.4f} net {v['net_atr']:+.4f}"
              f" det={v['can_detect_cost_sized_effect']}")

    print("\n" + "=" * W); print("ENDPOINT-COUPLING AUDIT"); print("=" * W)
    sa = controls["endpoint_coupling_audit"]["structural"]
    print(f"  shared price point: {sa['shared_price_point']}   {sa['assertion']}")
    dis = [k for k, v in coupled_cmp.items() if v["sign_agrees"] is False]
    print(f"  coupled-anchor sign disagreements: {len(dis)} of {len(coupled_cmp)} {dis[:6]}")

    print("\n" + "=" * W); print("CONTROLS SUMMARY"); print("=" * W)
    cr = controls["causal_reconstruction"]
    print(f"  causal reconstruction PASS={cr['PASS']}  {cr['observed']}")
    print(f"  ESTIMATOR_SIGN_DISAGREEMENT cells: {len(controls['sign_disagreement_cells'])}")
    nd = [k for k, v in controls["forward_window_audits"].items() if not v["disjoint"]]
    print(f"  forward-window audits non-disjoint: {len(nd)}")
    print(f"  DEV tuning: {controls['dev_tuning']}   M5/M1 used: {controls['m5_m1_used']}")
    print(f"  FINAL_OOS opened: {controls['final_oos']['opened']}")
    print(f"\n  wrote {out_dir/'hypothesis_04_results.json'}")
    print(f"  wrote {out_dir/'hypothesis_04_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
