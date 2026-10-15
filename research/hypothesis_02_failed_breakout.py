"""Hypothesis 02 -- FAILED BREAKOUT -> RANGE RE-ENTRY -> REVERSAL.

Implements, literally and only, the pre-registration committed at 9c59e7b:
research/hypothesis_02_failed_breakout.md.

The compression and breakout definitions are IMPORTED from the Hypothesis 01
module rather than retyped, so "the exact frozen definition from Hypothesis 01"
is literally true and cannot drift. THETA is recomputed and asserted against
H01's published value.

Independent of the frozen historical control. No production module is imported.
The breakout establishes the initial direction; the reversal direction is its
negation. Nothing outside the pre-registered definitions is searched.

FINAL_OOS is never read, as data or as context.
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
    Weighting, benjamini_hochberg, bonferroni_t, conditional_stat, contrast,
    forward_window_audit, non_overlapping_indices, raw_stats,
)
# the frozen H01 definitions, imported not retyped
from research.hypothesis_01_compression_breakout import (                   # noqa: E402
    ATR_LEN, BUFFER_ATR, PERCENTILE, W_COMPRESSION, build_features,
    DEV_HI, DEV_LO, TRAIN_HI, TRAIN_LO, SPLIT,
)

# ------------------------------------------------------------ frozen constants
FAILURE_WINDOW = 4          # bars j in {i+1 .. i+4}
HORIZONS = {"1h": 4, "2h": 8, "4h": 16}
N_HYPOTHESES = 3
ALPHA = 0.05
# The reference is read from the COMMITTED H01 results artifact at full
# precision, not from a hand-transcribed literal. The spec quotes THETA rounded
# to 10 dp (2.4579083398); comparing a full-precision recomputation against that
# rounding cannot succeed at 1e-12, because the rounding itself is 1.5e-11. Both
# checks are therefore performed: exact agreement with the committed value to
# 1e-12 relative (the real definition-drift check), and agreement of the 10-dp
# rendering with the literal published in the specification.
THETA_H01_PUBLISHED_10DP = 2.4579083398     # the spec's printed value
H01_RESULTS = Path(__file__).with_name("hypothesis_01_results.json")
THETA_ASSERT_RTOL = 1e-12

BOUNDARY_WINDOW = 16        # opposite-boundary diagnostic window after j
BOOTSTRAP_BLOCKS = (96, 480)
BOOTSTRAP_REPLICATES = 4000
BOOTSTRAP_SEED = 20261003

# causal reconstruction -- tolerances frozen in spec section 14, from float64
# precision alone. Not revisable after results.
TOL_RANGE = 0.0             # max/min performs no arithmetic
TOL_ATR_REL = 1e-12         # Wilder recursion contracts by 13/14; steady state ~14*eps
TOL_RATIO_REL = 1e-12
CAUSAL_PROBES = 60
CAUSAL_SEED = 20261003

SPREAD_USD = 0.33
SLIPPAGE_GRID = (0.0, 0.25, 0.50, 1.00)
COST_ATR = {"TRAIN": 0.158, "DEV": 0.093}
MIN_NONOVERLAPPING_N = 100


# ===================================================================== events
def find_events(compressed: np.ndarray, long_break: np.ndarray, short_break: np.ndarray,
                eligible: np.ndarray, arm_mask: np.ndarray, range_high: np.ndarray,
                range_low: np.ndarray, close: np.ndarray, A: np.ndarray,
                n: int) -> dict:
    """The pre-registered state machine (spec section 10).

    The H01 armed/fired machine with the re-entry search appended. One initial
    breakout yields at most one failed event; the episode is consumed whether or
    not it failed, so failed and successful populations are disjoint and jointly
    exhaustive over initial breakouts.
    """
    failed: list[tuple[int, int, int]] = []    # (j, d, i)
    success: list[tuple[int, int, int]] = []   # (anchor = i+4, d, i)
    suppressed = window_out_of_arm = bad_atr = 0
    armed = True
    for i in np.flatnonzero(arm_mask & eligible):
        lb, sb = bool(long_break[i]), bool(short_break[i])
        if compressed[i] and (lb != sb):            # XOR: unambiguous breakout
            if not armed:
                suppressed += 1
            else:
                d = 1 if lb else -1
                last = i + FAILURE_WINDOW
                if last >= n or not arm_mask[last]:
                    window_out_of_arm += 1
                else:
                    j_found = None
                    for j in range(i + 1, last + 1):
                        if (d == 1 and close[j] <= range_high[i]) or \
                           (d == -1 and close[j] >= range_low[i]):
                            j_found = j
                            break
                    if j_found is not None:
                        if np.isfinite(A[j_found]) and A[j_found] > 0:
                            failed.append((int(j_found), d, int(i)))
                        else:
                            bad_atr += 1
                    else:
                        if np.isfinite(A[last]) and A[last] > 0:
                            success.append((int(last), d, int(i)))
                        else:
                            bad_atr += 1
                armed = False
        if not compressed[i]:
            armed = True
    return {"failed": failed, "success": success, "suppressed": suppressed,
            "window_out_of_arm": window_out_of_arm, "bad_atr": bad_atr}


# ================================================================= statistics
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


def _bootstrap_diff(y, m_hi, m_lo, block, reps, seed) -> dict:
    ok = np.isfinite(y)
    hi, lo = m_hi & ok, m_lo & ok
    n = len(y)
    nb = int(np.ceil(n / block))
    edges = np.minimum(np.arange(nb + 1) * block, n)
    S1 = np.add.reduceat(np.where(hi, y, 0.0), edges[:-1])
    N1 = np.add.reduceat(hi.astype(float), edges[:-1])
    S0 = np.add.reduceat(np.where(lo, y, 0.0), edges[:-1])
    N0 = np.add.reduceat(lo.astype(float), edges[:-1])
    if not (N1.sum() and N0.sum()):
        return {"block_bars": block, "se": None, "t": None}
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nb, size=(reps, nb))
    s1, n1 = S1[pick].sum(1), N1[pick].sum(1)
    s0, n0 = S0[pick].sum(1), N0[pick].sum(1)
    good = (n1 > 0) & (n0 > 0)
    dd = np.full(reps, np.nan)
    dd[good] = s1[good] / n1[good] - s0[good] / n0[good]
    dd = dd[np.isfinite(dd)]
    if len(dd) < 100:
        return {"block_bars": block, "se": None, "t": None, "replicates_used": int(len(dd))}
    point = float(S1.sum() / N1.sum() - S0.sum() / N0.sum())
    se = float(np.std(dd, ddof=1))
    return {"block_bars": block, "replicates_used": int(len(dd)),
            "point_all_observations": round(point, 6), "se": round(se, 6),
            "t": (round(point / se, 4) if se > 0 else None),
            "ci95": [round(float(np.percentile(dd, 2.5)), 6),
                     round(float(np.percentile(dd, 97.5)), 6)],
            "weighting": "block bootstrap over ALL observations"}


# ======================================================================= main
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
    print(f"[data] M15 rows to DEV boundary: {n:,}   TRAIN {in_train.sum():,}  DEV {in_dev.sum():,}")

    F = build_features(m15)                 # H01 definitions, imported
    A, close, high, low, op = F["A"], F["close"], F["high"], F["low"], F["open"]
    # A[k] = ATR_14[k-1]; so A[i] is A_i and A[j] is A_j -- one array, both roles.

    finite_feat = (np.isfinite(F["comp_ratio"]) & np.isfinite(A) & (A > 0)
                   & np.isfinite(F["range_12"]))
    eligible = finite_feat & (in_train | in_dev)

    train_cr = F["comp_ratio"][finite_feat & in_train]
    THETA = float(np.percentile(train_cr, PERCENTILE, method="linear"))
    theta_ref = float(json.loads(H01_RESULTS.read_text(encoding="utf-8"))
                      ["frozen_definitions"]["THETA_train_only"])
    drift = abs(THETA - theta_ref) / theta_ref
    print(f"[theta] recomputed {THETA!r}")
    print(f"[theta] H01 committed {theta_ref!r}   rel-diff {drift:.2e}   bit-identical={THETA == theta_ref}")
    assert drift <= THETA_ASSERT_RTOL, (
        f"THETA drifted from the H01 committed value: {THETA} vs {theta_ref}")
    assert round(THETA, 10) == THETA_H01_PUBLISHED_10DP, (
        f"THETA 10-dp rendering {round(THETA, 10)} does not match the value published "
        f"in the specification, {THETA_H01_PUBLISHED_10DP}")

    compressed = np.zeros(n, bool)
    compressed[finite_feat] = F["comp_ratio"][finite_feat] <= THETA
    long_break = np.zeros(n, bool)
    short_break = np.zeros(n, bool)
    long_break[finite_feat] = close[finite_feat] > F["range_high"][finite_feat] + BUFFER_ATR * A[finite_feat]
    short_break[finite_feat] = close[finite_feat] < F["range_low"][finite_feat] - BUFFER_ATR * A[finite_feat]
    ambiguous = int((long_break & short_break & eligible).sum())

    arm_of = {"TRAIN": in_train, "DEV": in_dev}
    EV = {arm: find_events(compressed, long_break, short_break, eligible, m,
                           F["range_high"], F["range_low"], close, A, n)
          for arm, m in arm_of.items()}
    for arm in arm_of:
        e = EV[arm]
        tot = len(e["failed"]) + len(e["success"])
        print(f"[events] {arm}: initial breakouts {tot:,}  ->  FAILED {len(e['failed']):,}"
              f"  SUCCESS {len(e['success']):,}   (suppressed {e['suppressed']:,},"
              f" window-out-of-arm {e['window_out_of_arm']}, bad ATR {e['bad_atr']})")

    # ---- labels at the anchor (j for failed, i+4 for successful) -----------
    fwd, nxt_open = {}, np.full(n, np.nan)
    nxt_open[: n - 1] = op[1:]
    for name, h in HORIZONS.items():
        f = np.full(n, np.nan)
        f[: n - h] = close[h:]
        fwd[name] = f
    same_arm = {}
    for name, h in HORIZONS.items():
        sa = np.zeros(n, bool)
        for arm, m_arm in arm_of.items():
            src = np.flatnonzero(m_arm)
            ok = src[(src + h) < n]
            ok = ok[m_arm[ok + h]]
            sa[ok] = True
        same_arm[name] = sa

    def label(anchors: np.ndarray, r: np.ndarray, name: str, anchor_open: bool = False) -> np.ndarray:
        y = np.full(n, np.nan)
        base = nxt_open[anchors] if anchor_open else close[anchors]
        with np.errstate(invalid="ignore"):
            y[anchors] = r * (fwd[name][anchors] - base) / A[anchors]
        return y

    results: dict = {
        "hypothesis": "research/hypothesis_02_failed_breakout.md",
        "preregistration_commit": "9c59e7b",
        "gate": "research/RESEARCH_TO_STRATEGY_GATE.md",
        "hypothesis_01_status": "CLOSED - NOT SUPPORTED (45223cd)",
        "declared_hypotheses": N_HYPOTHESES,
        "frozen_definitions": {
            "compression_window_bars": W_COMPRESSION, "atr_length": ATR_LEN,
            "atr_instances": {"A_i": "ATR_14[i-1] (compression ratio, breakout buffer)",
                              "A_j": "ATR_14[j-1] (label normaliser)"},
            "percentile": PERCENTILE,
            "THETA_recomputed": THETA, "THETA_h01_committed": "read from hypothesis_01_results.json at full precision",
            "THETA_h01_published_10dp": THETA_H01_PUBLISHED_10DP,
            "THETA_rel_diff": drift,
            "breakout_buffer_atr": BUFFER_ATR,
            "failure_window_bars": FAILURE_WINDOW,
            "horizons_m15_bars": HORIZONS,
            "definitions_imported_from": "research/hypothesis_01_compression_breakout.py",
        },
        "dataset": {"dataset_sha256": SPLIT["dataset_sha256"],
                    "fingerprints_verified": True, "m15_rows": int(n),
                    "panel_time_max": str(m15["time"].max()), "dev_boundary": str(DEV_HI)},
        "arms": {"TRAIN": {"from": str(TRAIN_LO), "to": str(TRAIN_HI)},
                 "DEV": {"from": str(DEV_LO), "to": str(DEV_HI)},
                 "FINAL_OOS": "LOCKED - not read, not used as context"},
        "event_accounting": {
            "ambiguous_excluded": ambiguous,
            "per_arm": {arm: {"initial_breakouts": len(EV[arm]["failed"]) + len(EV[arm]["success"]),
                              "failed": len(EV[arm]["failed"]),
                              "successful": len(EV[arm]["success"]),
                              "failure_rate_pct": round(100 * len(EV[arm]["failed"]) /
                                                        max(len(EV[arm]["failed"]) + len(EV[arm]["success"]), 1), 2),
                              "suppressed_by_dedup": EV[arm]["suppressed"],
                              "window_out_of_arm": EV[arm]["window_out_of_arm"],
                              "excluded_bad_atr": EV[arm]["bad_atr"]}
                        for arm in arm_of},
            "compression_rate_pct": {arm: round(100 * float(compressed[finite_feat & m].mean()), 4)
                                     for arm, m in arm_of.items()},
        },
        "primary": {}, "control_open_anchor": {}, "baselines": {},
        "boundary_diagnostics": {},
    }
    controls: dict = {"weighting_headline": Weighting.NON_OVERLAPPING,
                      "weighting_secondary": Weighting.EQUAL_BLOCK,
                      "declared_hypotheses": N_HYPOTHESES, "cells": {}}

    t_primary, t_keys = [], []
    for arm in ("TRAIN", "DEV", "POOLED"):
        src = (EV["TRAIN"]["failed"] + EV["DEV"]["failed"]) if arm == "POOLED" else EV[arm]["failed"]
        if not src:
            continue
        anchors_all = np.array([e[0] for e in src], dtype=np.int64)
        rev_all = np.array([-e[1] for e in src], dtype=float)
        for name, h in HORIZONS.items():
            sel = same_arm[name][anchors_all]
            anchors, rev = anchors_all[sel], rev_all[sel]
            if len(anchors) == 0:
                continue
            y = label(anchors, rev, name)
            d = cell_report(y, anchors, h, f"H02_{arm}@{name}")
            d["reversal_side_counts"] = {"LONG": int((rev > 0).sum()),
                                         "SHORT": int((rev < 0).sum())}
            for nm, m_sel in (("LONG", rev > 0), ("SHORT", rev < 0)):
                sub, rsub = anchors[m_sel], rev[m_sel]
                if len(sub) >= 2:
                    ys = label(sub, rsub, name)
                    keep = non_overlapping_indices(sub[np.isfinite(ys[sub])], h)
                    d[f"reversal_{nm}"] = {**raw_stats(ys[keep]),
                                           "n_non_overlapping": int(len(keep))}
            results["primary"][f"{arm}@{name}"] = d
            controls["cells"][f"{arm}@{name}"] = {
                "overlap": d["overlap"], "audit": d["audit"], "flags": d["flags"],
                "needs_review": d["needs_review"]}
            if arm == "TRAIN" and d["headline"].get("t") is not None:
                t_primary.append(float(d["headline"]["t"])); t_keys.append(f"{arm}@{name}")
            yc = label(anchors, rev, name, anchor_open=True)
            results["control_open_anchor"][f"{arm}@{name}"] = cell_report(
                yc, anchors, h, f"H02ctl_{arm}@{name}")["headline"]

    # ---- baselines ---------------------------------------------------------
    for arm in ("TRAIN", "DEV"):
        m_arm = arm_of[arm]
        fail = EV[arm]["failed"]
        succ = EV[arm]["success"]
        if not fail:
            continue
        fa = np.array([e[0] for e in fail], dtype=np.int64)
        fr = np.array([-e[1] for e in fail], dtype=float)
        sa_ = np.array([e[0] for e in succ], dtype=np.int64) if succ else np.array([], np.int64)
        sr = np.array([-e[1] for e in succ], dtype=float) if succ else np.array([], float)
        for name, h in HORIZONS.items():
            key = f"{arm}@{name}"
            fsel = same_arm[name][fa]
            fan, frn = fa[fsel], fr[fsel]
            if len(fan) == 0:
                continue
            yf = label(fan, frn, name)
            keep_f = non_overlapping_indices(fan[np.isfinite(yf[fan])], h)
            q_long = float((frn[np.isin(fan, keep_f)] > 0).mean()) if len(keep_f) else 0.0

            # A -- unconditional, side-matched in the reversal direction
            pool = np.flatnonzero(m_arm & eligible & same_arm[name] & np.isfinite(A) & (A > 0))
            with np.errstate(invalid="ignore"):
                unc = (fwd[name][pool] - close[pool]) / A[pool]
            m_plus, m_minus = float(np.nanmean(unc)), float(np.nanmean(-unc))
            bl_a = {"long_side_mean": round(m_plus, 6), "short_side_mean": round(m_minus, 6),
                    "q_reversal_long_from_events": round(q_long, 4),
                    "side_matched_mean": round(q_long * m_plus + (1 - q_long) * m_minus, 6),
                    "n_pool": int(len(pool)),
                    "weighting": "all eligible bars, overlapping (reference only)"}

            # B -- breakouts that did NOT fail, anchored at i+4
            bl_b = {"n_events_raw": 0}
            ssel = same_arm[name][sa_] if len(sa_) else np.array([], bool)
            san, srn = (sa_[ssel], sr[ssel]) if len(sa_) else (sa_, sr)
            if len(san) >= 2:
                ys = label(san, srn, name)
                bl_b = cell_report(ys, san, h, f"B_{key}")
                bl_b["anchor"] = "i+4, normaliser ATR[i+3]; same reversal direction"

            # C -- the incremental contrast
            bl_c = {}
            if len(san) >= 2:
                y = np.full(n, np.nan)
                y[fan] = yf[fan]
                y[san] = label(san, srn, name)[san]
                m_hi = np.zeros(n, bool); m_hi[fan] = True
                m_lo = np.zeros(n, bool); m_lo[san] = True
                c = contrast(y, m_hi, m_lo, h, label=f"C_{key}")
                kp = non_overlapping_indices(fan[np.isfinite(y[fan])], h)
                kf = non_overlapping_indices(san[np.isfinite(y[san])], h)
                cg = None
                if len(kp) and len(kf):
                    cg = round(100 * float((np.abs(kp[:, None] - kf[None, :]).min(axis=1) < h).mean()), 2)
                bl_c = {"failed": {k: c["hi"]["headline"][k] for k in ("n", "mean", "se", "t", "ci95")},
                        "successful": {k: c["lo"]["headline"][k] for k in ("n", "mean", "se", "t", "ci95")},
                        "headline_diff": c.get("headline_diff"),
                        "block_diff_SECONDARY": c.get("block_diff_SECONDARY"),
                        "cross_group_overlap_pct": cg,
                        "bootstrap": {f"block_{b}": _bootstrap_diff(y, m_hi, m_lo, b,
                                                                    BOOTSTRAP_REPLICATES,
                                                                    BOOTSTRAP_SEED + b)
                                      for b in BOOTSTRAP_BLOCKS},
                        "flags": c["flags"],
                        "note": "DECLARED BASELINE, 0 hypotheses. Cannot promote the candidate."}
            results["baselines"][key] = {"A_unconditional_side_matched": bl_a,
                                         "B_successful_breakouts": bl_b,
                                         "C_incremental_contrast": bl_c}

        # ---- opposite-boundary diagnostics (descriptive only) --------------
        reach, times = {4: 0, 8: 0, 16: 0}, []
        total = 0
        for (j, d, i0) in fail:
            if j + BOUNDARY_WINDOW >= n or not m_arm[j + BOUNDARY_WINDOW]:
                continue
            total += 1
            tgt = F["range_low"][i0] if d == 1 else F["range_high"][i0]
            hit = None
            for k in range(j + 1, j + BOUNDARY_WINDOW + 1):
                if (d == 1 and low[k] <= tgt) or (d == -1 and high[k] >= tgt):
                    hit = k - j
                    break
            if hit is not None:
                times.append(hit)
                for w in (4, 8, 16):
                    if hit <= w:
                        reach[w] += 1
        results["boundary_diagnostics"][arm] = {
            "events_with_full_window": total,
            "fraction_reaching_within": {f"{w}_bars": (round(reach[w] / total, 4) if total else None)
                                         for w in (4, 8, 16)},
            "fraction_not_reaching_within_16": (round(1 - reach[16] / total, 4) if total else None),
            "time_to_boundary_bars": ({"median": float(np.median(times)),
                                       "q25": float(np.percentile(times, 25)),
                                       "q75": float(np.percentile(times, 75)),
                                       "n": len(times)} if times else None),
            "note": ("DESCRIPTIVE mechanism evidence only. No target or stop is "
                     "derived or selected from this.")}

    # ---- multiple testing --------------------------------------------------
    padded = list(t_primary) + [0.0] * (N_HYPOTHESES - len(t_primary))
    pvals = [math.erfc(abs(v) / math.sqrt(2)) for v in padded]
    bh = benjamini_hochberg(pvals, ALPHA)
    thr = bonferroni_t(N_HYPOTHESES, ALPHA)
    results["multiple_testing"] = {
        "primary_arm": "TRAIN", "n_declared": N_HYPOTHESES,
        "n_with_computable_t": len(t_primary),
        "n_padded_as_non_rejection": N_HYPOTHESES - len(t_primary),
        "nominal_alpha": ALPHA, "bonferroni_threshold_t": round(thr, 4),
        "t_values": {k: round(v, 4) for k, v in zip(t_keys, t_primary)},
        "survivors_bonferroni": [k for k, v in zip(t_keys, t_primary) if abs(v) >= thr],
        "benjamini_hochberg": bh,
        "max_abs_t": (round(max(abs(v) for v in t_primary), 4) if t_primary else None),
        "observed_abs_t_ge_2": int(sum(1 for v in t_primary if abs(v) >= 2)),
        "expected_abs_t_ge_2_under_null": round(0.0455 * N_HYPOTHESES, 4)}

    # ---- power -------------------------------------------------------------
    power = {}
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            d = results["primary"].get(f"{arm}@{name}")
            if not d:
                continue
            se = (d.get("headline") or {}).get("se")
            if se and se == se:
                power[f"{arm}@{name}"] = {
                    "non_overlapping_n": d["n_events_non_overlapping"],
                    "below_min_n_100": d["below_min_n"],
                    "se": round(se, 5), "mde_2se_atr": round(2 * se, 4),
                    "mde_bonferroni_atr": round(thr * se, 4),
                    "cost_atr_reference": COST_ATR[arm],
                    "can_detect_cost_sized_effect": bool(thr * se <= COST_ATR[arm])}
    results["power"] = power

    # ---- causal reconstruction, frozen tolerances --------------------------
    allf = EV["TRAIN"]["failed"] + EV["DEV"]["failed"]
    rng = np.random.default_rng(CAUSAL_SEED)
    pick = rng.choice(len(allf), size=min(CAUSAL_PROBES, len(allf)), replace=False)
    dev_rng = dev_atr = dev_ratio = 0.0
    bool_mismatch = {"compressed": 0, "breakout": 0, "re_entry": 0}
    margins: list[float] = []
    for p in sorted(pick):
        j, d, i0 = allf[p]
        pre_i = m15.iloc[:i0]
        a_i = float(ta.atr(pre_i["high"], pre_i["low"], pre_i["close"], length=ATR_LEN).iloc[-1])
        rh = float(pre_i["high"].tail(W_COMPRESSION).max())
        rl = float(pre_i["low"].tail(W_COMPRESSION).min())
        ratio = (rh - rl) / a_i
        dev_rng = max(dev_rng, abs(rh - F["range_high"][i0]), abs(rl - F["range_low"][i0]))
        dev_atr = max(dev_atr, abs(a_i - A[i0]) / abs(A[i0]))
        dev_ratio = max(dev_ratio, abs(ratio - F["comp_ratio"][i0]) / abs(F["comp_ratio"][i0]))
        if (ratio <= THETA) != bool(compressed[i0]):
            bool_mismatch["compressed"] += 1
            margins.append(abs(ratio - THETA) / THETA)
        lb2 = close[i0] > rh + BUFFER_ATR * a_i
        sb2 = close[i0] < rl - BUFFER_ATR * a_i
        if lb2 != bool(long_break[i0]) or sb2 != bool(short_break[i0]):
            bool_mismatch["breakout"] += 1
        re2 = (close[j] <= rh) if d == 1 else (close[j] >= rl)
        if not re2:
            bool_mismatch["re_entry"] += 1
        pre_j = m15.iloc[:j]
        a_j = float(ta.atr(pre_j["high"], pre_j["low"], pre_j["close"], length=ATR_LEN).iloc[-1])
        dev_atr = max(dev_atr, abs(a_j - A[j]) / abs(A[j]))

    passed = (dev_rng <= TOL_RANGE and dev_atr <= TOL_ATR_REL
              and dev_ratio <= TOL_RATIO_REL and sum(bool_mismatch.values()) == 0)
    controls["causal_reconstruction"] = {
        "probes": int(len(pick)), "seed": CAUSAL_SEED,
        "frozen_tolerances": {"range_high_low_abs": TOL_RANGE,
                              "atr_relative": TOL_ATR_REL,
                              "compression_ratio_relative": TOL_RATIO_REL,
                              "boolean_classifications": "0 disagreements"},
        "observed": {"range_high_low_abs": dev_rng,
                     "atr_relative": dev_atr,
                     "compression_ratio_relative": dev_ratio,
                     "boolean_disagreements": bool_mismatch,
                     "threshold_margins_at_disagreement": margins},
        "PASS": bool(passed),
        "method": ("every quantity rebuilt from m15.iloc[:k] (bars 0..k-1 only) and "
                   "compared with the panel value at k, for k=i and k=j")}
    print(f"[causal] range {dev_rng:.3e} (tol {TOL_RANGE})  atr_rel {dev_atr:.3e} (tol {TOL_ATR_REL})"
          f"  ratio_rel {dev_ratio:.3e}  bools {bool_mismatch}  -> PASS={passed}")

    controls["forward_window_audits"] = {}
    for arm in ("TRAIN", "DEV"):
        fail = EV[arm]["failed"]
        if not fail:
            continue
        fa = np.array([e[0] for e in fail], dtype=np.int64)
        fr = np.array([-e[1] for e in fail], dtype=float)
        for name, h in HORIZONS.items():
            sel = same_arm[name][fa]
            y = label(fa[sel], fr[sel], name)
            keep = non_overlapping_indices(fa[sel][np.isfinite(y[fa[sel]])], h)
            controls["forward_window_audits"][f"{arm}@{name}"] = forward_window_audit(keep, h)
    controls["sign_disagreement_cells"] = [
        k for k, v in controls["cells"].items()
        if "ESTIMATOR_SIGN_DISAGREEMENT" in (v.get("flags") or [])]
    controls["exactly_one_hypothesis_tested"] = {
        "hypothesis": "FAILED BREAKOUT -> RANGE RE-ENTRY -> REVERSAL",
        "compression_windows_tested": [W_COMPRESSION],
        "percentiles_tested": [PERCENTILE],
        "breakout_buffers_tested": [BUFFER_ATR],
        "failure_windows_tested": [FAILURE_WINDOW],
        "horizons_tested": sorted(HORIZONS.values()),
        "statement": ("One compression window, one percentile, one buffer, one failure "
                      "window, three pre-declared horizons. No alternative computed.")}
    controls["final_oos"] = {"opened": False, "panel_truncated_at": str(DEV_HI),
                             "token": "OOS-AUTHORISATION-NOT-ISSUED",
                             "h1_used": False}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hypothesis_02_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "hypothesis_02_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")

    # ----------------------------------------------------------------- console
    W = 96
    print("\n" + "=" * W); print("EVENT ACCOUNTING"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        a = results["event_accounting"]["per_arm"][arm]
        print(f"  {arm:5s} initial {a['initial_breakouts']:5,}  FAILED {a['failed']:5,}"
              f"  SUCCESS {a['successful']:5,}  failure rate {a['failure_rate_pct']:5.2f}%"
              f"   suppressed {a['suppressed_by_dedup']:4,}  out-of-arm {a['window_out_of_arm']}"
              f"  bad-ATR {a['excluded_bad_atr']}")
    print(f"  ambiguous excluded: {ambiguous}   THETA {THETA!r}  bit-identical to H01: {drift == 0.0}")

    print("\n" + "=" * W)
    print("PRIMARY -- E[R_h] > 0 in the REVERSAL direction, NON-OVERLAPPING events")
    print("=" * W)
    print(f"  {'cell':14s} {'raw n':>6s} {'non-ov':>7s} {'ov':>6s} {'mean':>9s} {'median':>9s}"
          f" {'sd':>7s} {'se':>7s} {'t':>7s}  95% CI")
    for arm in ("TRAIN", "DEV", "POOLED"):
        for name in HORIZONS:
            d = results["primary"].get(f"{arm}@{name}")
            if not d or d["headline"].get("t") is None:
                continue
            hd, o, ci = d["headline"], d["overlap"], d["headline"]["ci95"]
            flag = " [n<100]" if d["below_min_n"] else ""
            print(f"  {arm}@{name:9s} {d['n_events_raw']:6,} {d['n_events_non_overlapping']:7,}"
                  f" {o['overlap_ratio']:5.1f}x {hd['mean']:+9.4f} {hd['median']:+9.4f}"
                  f" {hd['sd']:7.3f} {hd['se']:7.4f} {hd['t']:+7.2f}"
                  f"  [{ci[0]:+.4f}, {ci[1]:+.4f}]{flag}")

    print("\n" + "=" * W)
    print("REVERSAL LONG / SHORT SPLIT -- the direction-neutrality diagnostic")
    print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            d = results["primary"].get(f"{arm}@{name}")
            if not d or "reversal_LONG" not in d or "reversal_SHORT" not in d:
                continue
            L, S = d["reversal_LONG"], d["reversal_SHORT"]
            print(f"  {arm}@{name:4s}  rev-LONG n={L['n_non_overlapping']:4d} mean {L['mean']:+.4f}"
                  f"   rev-SHORT n={S['n_non_overlapping']:4d} mean {S['mean']:+.4f}")

    print("\n" + "=" * W); print("MULTIPLE TESTING (declared 3, primary arm TRAIN)"); print("=" * W)
    mt = results["multiple_testing"]
    print(f"  t values {mt['t_values']}")
    print(f"  Bonferroni |t| >= {mt['bonferroni_threshold_t']}   survivors "
          f"{len(mt['survivors_bonferroni'])} {mt['survivors_bonferroni']}   BH {bh.get('n_survivors')}")
    print(f"  max |t| {mt['max_abs_t']}   observed |t|>=2 {mt['observed_abs_t_ge_2']}"
          f"   expected {mt['expected_abs_t_ge_2_under_null']}")

    print("\n" + "=" * W)
    print("BASELINE C -- INCREMENTAL CONTRAST: failed vs successful breakouts")
    print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            b = (results["baselines"].get(f"{arm}@{name}") or {}).get("C_incremental_contrast") or {}
            hd = b.get("headline_diff")
            if not hd:
                continue
            bs = b["bootstrap"]["block_96"]
            print(f"  {arm}@{name:4s} failed n={hd['n_hi']:4d} mean {b['failed']['mean']:+.4f}"
                  f" | success n={hd['n_lo']:4d} mean {b['successful']['mean']:+.4f}"
                  f" | diff {hd['diff']:+.4f} se {hd['se']:.4f} t {hd['t']:+.2f}"
                  f" | boot t {('%+.2f' % bs['t']) if bs.get('t') is not None else 'n/a'}"
                  f" | x-ov {b.get('cross_group_overlap_pct')}%")

    print("\n" + "=" * W); print("BASELINE A -- unconditional, side-matched (reversal direction)"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            a = (results["baselines"].get(f"{arm}@{name}") or {}).get("A_unconditional_side_matched")
            d = results["primary"].get(f"{arm}@{name}")
            if not a or not d:
                continue
            print(f"  {arm}@{name:4s} long-side {a['long_side_mean']:+.4f} short-side {a['short_side_mean']:+.4f}"
                  f"  q(rev LONG) {a['q_reversal_long_from_events']:.3f}"
                  f"  side-matched {a['side_matched_mean']:+.4f}   event mean {d['headline']['mean']:+.4f}")

    print("\n" + "=" * W); print("OPPOSITE-BOUNDARY DIAGNOSTICS (descriptive only)"); print("=" * W)
    for arm in ("TRAIN", "DEV"):
        b = results["boundary_diagnostics"].get(arm)
        if not b:
            continue
        fr = b["fraction_reaching_within"]
        tt = b["time_to_boundary_bars"]
        print(f"  {arm:5s} n={b['events_with_full_window']:4,}  reach within 4 {fr['4_bars']}"
              f"  8 {fr['8_bars']}  16 {fr['16_bars']}   never(16) {b['fraction_not_reaching_within_16']}"
              + (f"   time median {tt['median']:.1f} q25 {tt['q25']:.1f} q75 {tt['q75']:.1f}" if tt else ""))

    print("\n" + "=" * W); print("POWER"); print("=" * W)
    for k, v in power.items():
        print(f"  {k:12s} n={v['non_overlapping_n']:5,}{' [n<100]' if v['below_min_n_100'] else '        '}"
              f"  se {v['se']:.4f}  MDE(2se) {v['mde_2se_atr']:.3f}"
              f"  MDE(Bonf) {v['mde_bonferroni_atr']:.3f} ATR  cost {v['cost_atr_reference']}"
              f"  detectable={v['can_detect_cost_sized_effect']}")

    print("\n" + "=" * W); print("CONTROLS"); print("=" * W)
    cr = controls["causal_reconstruction"]
    print(f"  causal reconstruction PASS={cr['PASS']}  range {cr['observed']['range_high_low_abs']:.3e}"
          f"  atr_rel {cr['observed']['atr_relative']:.3e}  ratio_rel {cr['observed']['compression_ratio_relative']:.3e}")
    print(f"  boolean disagreements: {cr['observed']['boolean_disagreements']}")
    print(f"  ESTIMATOR_SIGN_DISAGREEMENT cells: {len(controls['sign_disagreement_cells'])}"
          f" {controls['sign_disagreement_cells']}")
    nd = [k for k, v in controls["forward_window_audits"].items() if not v["disjoint"]]
    print(f"  forward-window audits non-disjoint: {len(nd)} {nd}")
    print(f"  FINAL_OOS opened: {controls['final_oos']['opened']}   H1 used: {controls['final_oos']['h1_used']}")
    print(f"\n  wrote {out_dir/'hypothesis_02_results.json'}")
    print(f"  wrote {out_dir/'hypothesis_02_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
