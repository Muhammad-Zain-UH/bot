"""Hypothesis 01 -- COMPRESSION -> RANGE BREAKOUT -> EXPANSION.

Implements, literally and only, the pre-registration committed at 44419ef:
research/hypothesis_01_compression_breakout.md.

Independent of the frozen historical control. No fast_bias, bias_strength, H1
production bias, CHoCH, sweep, POI, FVG, production session gate, production
entry trigger or production threshold is imported or consulted. The breakout
alone determines direction.

Nothing outside the pre-registered definitions is searched. No alternative
compression window, breakout buffer, percentile or horizon is computed.

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

# ----------------------------------------------------------- frozen constants
W_COMPRESSION = 12          # pre-breakout window, bars i-12 .. i-1
ATR_LEN = 14
PERCENTILE = 20             # TRAIN-only, frozen, not optimised
BUFFER_ATR = 0.10           # frozen, not optimised
HORIZONS = {"1h": 4, "2h": 8, "4h": 16}
N_HYPOTHESES = 3            # frozen before results: E[R_h] > 0 at three horizons
ALPHA = 0.05

RANDOM_REPLICATES = 2000
RANDOM_SEED = 20261002
BOOTSTRAP_BLOCKS = (96, 480)
BOOTSTRAP_REPLICATES = 4000
BOOTSTRAP_SEED = 20261002

SPREAD_USD = 0.33           # measured median round turn = 1 x spread
SLIPPAGE_GRID = (0.0, 0.25, 0.50, 1.00)
# economic meaningfulness, declared in advance (spec section 11)
COST_ATR = {"TRAIN": 0.158, "DEV": 0.093}
MIN_NONOVERLAPPING_N = 100  # below this a cell is INCONCLUSIVE by the spec

SPLIT = json.loads((Path(__file__).with_name("research_split_manifest.json")).read_text(encoding="utf-8"))
TRAIN_LO = pd.Timestamp(SPLIT["arms"]["TRAIN"]["from_utc"])
TRAIN_HI = pd.Timestamp(SPLIT["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(SPLIT["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])


# =============================================================== feature build
def build_features(m15: pd.DataFrame) -> dict:
    """Every quantity here is a function of bars at or before i-1, except
    close[i], which enters only the breakout test (spec section 8 declares the
    coupling this creates)."""
    high, low, close = (m15[k].to_numpy(float) for k in ("high", "low", "close"))
    atr14 = ta.atr(m15["high"], m15["low"], m15["close"], length=ATR_LEN)
    # A[i] = ATR_14[i-1]
    A = atr14.shift(1).to_numpy(float)
    # bars i-12 .. i-1
    range_high = m15["high"].rolling(W_COMPRESSION).max().shift(1).to_numpy(float)
    range_low = m15["low"].rolling(W_COMPRESSION).min().shift(1).to_numpy(float)
    range_12 = range_high - range_low
    with np.errstate(invalid="ignore", divide="ignore"):
        comp_ratio = np.where(np.isfinite(A) & (A > 0), range_12 / A, np.nan)
    return {"high": high, "low": low, "close": close,
            "open": m15["open"].to_numpy(float),
            "A": A, "range_high": range_high, "range_low": range_low,
            "range_12": range_12, "comp_ratio": comp_ratio}


def dedup_events(gate: np.ndarray, breakout: np.ndarray, eligible: np.ndarray,
                 arm_mask: np.ndarray) -> tuple[np.ndarray, int]:
    """The pre-registered state machine (spec section 7).

    armed = True at the first eligible bar of the arm.
      if armed and gate[i] and breakout[i]:  emit, armed = False
      elif not gate[i]:                      armed = True

    `gate` is `compressed` for the hypothesis population and `~compressed` for
    baseline C, which is the structural analogue: the series must leave the
    gating regime and re-enter it before another event can fire.

    Returns (event indices, bars suppressed by the armed flag).
    """
    out: list[int] = []
    suppressed = 0
    armed = True
    for i in np.flatnonzero(arm_mask & eligible):
        if gate[i] and breakout[i]:
            if armed:
                out.append(int(i))
                armed = False
            else:
                suppressed += 1
        if not gate[i]:
            armed = True
    return np.array(out, dtype=np.int64), suppressed


# ================================================================== statistics
def cell_report(y: np.ndarray, idx: np.ndarray, h: int, label: str) -> dict:
    """Full disclosure for one cell of events, headline non-overlapping."""
    mask = np.zeros(len(y), bool)
    mask[idx] = True
    cs = conditional_stat(y, mask, h, label)
    d = cs.to_dict()
    keep = non_overlapping_indices(idx[np.isfinite(y[idx])], h)
    d["headline"]["sd"] = raw_stats(y[keep]).get("sd")
    d["headline"]["median"] = raw_stats(y[keep]).get("median")
    d["n_events_raw"] = int(np.isfinite(y[idx]).sum())
    d["n_events_non_overlapping"] = int(len(keep))
    d["below_min_n"] = bool(len(keep) < MIN_NONOVERLAPPING_N)
    return d


def _bootstrap_diff(y: np.ndarray, m_hi: np.ndarray, m_lo: np.ndarray,
                    block: int, reps: int, seed: int) -> dict:
    """Moving-block bootstrap for mean(hi) - mean(lo); carries cross-group
    dependence, which the pooled analytic SE assumes away."""
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
    d = np.full(reps, np.nan)
    d[good] = s1[good] / n1[good] - s0[good] / n0[good]
    d = d[np.isfinite(d)]
    if len(d) < 100:
        return {"block_bars": block, "se": None, "t": None,
                "replicates_used": int(len(d))}
    point = float(S1.sum() / N1.sum() - S0.sum() / N0.sum())
    se = float(np.std(d, ddof=1))
    return {"block_bars": block, "replicates_used": int(len(d)),
            "point_all_observations": round(point, 6), "se": round(se, 6),
            "t": (round(point / se, 4) if se > 0 else None),
            "ci95": [round(float(np.percentile(d, 2.5)), 6),
                     round(float(np.percentile(d, 97.5)), 6)],
            "weighting": "block bootstrap over ALL observations"}


def random_baseline(y: np.ndarray, pool: np.ndarray, n_draw: int, p_long: float,
                    h: int, sign_pool: np.ndarray, seed: int) -> dict:
    """Baseline B, exactly as pre-registered (spec section 10).

    Draw bars one at a time uniformly from the eligible pool, rejecting any bar
    within h bars of an already-drawn bar, until n_draw bars are drawn; abandon a
    replicate after 1,000 consecutive rejections. Assign direction = +1 to
    round(n*p) of them at random, -1 to the rest.
    """
    if n_draw < 2 or len(pool) < n_draw:
        return {"replicates": 0, "note": "insufficient pool or draw size"}
    rng = np.random.default_rng(seed)
    n_long = int(round(n_draw * p_long))
    means, abandoned = [], 0
    for _ in range(RANDOM_REPLICATES):
        chosen: list[int] = []
        misses = 0
        # `blocked[j]` marks any j within h-1 bars of an already-drawn bar, which
        # is exactly the pre-registered rejection rule `all(|cand - c| >= h)`,
        # evaluated in O(1) instead of O(n). Same rule, same draw order, same seed.
        blocked = np.zeros(len(y), bool)
        while len(chosen) < n_draw and misses < 1000:
            cand = int(pool[rng.integers(0, len(pool))])
            if not blocked[cand]:
                chosen.append(cand)
                blocked[max(0, cand - h + 1): cand + h] = True
                misses = 0
            else:
                misses += 1
        if len(chosen) < n_draw:
            abandoned += 1
            continue
        ci = np.array(chosen, dtype=np.int64)
        d = np.full(n_draw, -1.0)
        d[rng.permutation(n_draw)[:n_long]] = 1.0
        vals = d * sign_pool[ci] * y[ci]   # y here is the UNSIGNED return
        vals = vals[np.isfinite(vals)]
        if len(vals):
            means.append(float(vals.mean()))
    if len(means) < 50:
        return {"replicates": len(means), "abandoned": abandoned,
                "note": "too few successful replicates"}
    arr = np.array(means)
    return {"replicates": int(len(arr)), "abandoned": int(abandoned),
            "n_drawn_each": int(n_draw), "p_long_matched": round(p_long, 4),
            "mean": round(float(arr.mean()), 6), "sd": round(float(arr.std(ddof=1)), 6),
            "pct2_5": round(float(np.percentile(arr, 2.5)), 6),
            "pct97_5": round(float(np.percentile(arr, 97.5)), 6),
            "_dist": arr}


# ======================================================================== main
def run(out_dir: Path) -> None:
    assert SPLIT["FINAL_OOS_LOCKED"] is True, "split manifest no longer declares the OOS lock"
    fp = verify_dataset()

    m15 = load_timeframe("M15")
    m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
    assert m15["time"].max() <= DEV_HI, "M15 panel extends past the DEV boundary"
    n = len(m15)
    t = m15["time"]
    in_train = ((t >= TRAIN_LO) & (t <= TRAIN_HI)).to_numpy()
    in_dev = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
    print(f"[data] M15 rows to DEV boundary: {n:,}   TRAIN {in_train.sum():,}  DEV {in_dev.sum():,}")

    F = build_features(m15)
    A, close, op = F["A"], F["close"], F["open"]

    finite_feat = np.isfinite(F["comp_ratio"]) & np.isfinite(A) & (A > 0) & np.isfinite(F["range_12"])
    eligible = finite_feat & (in_train | in_dev)

    # ---- THETA: TRAIN only, frozen -----------------------------------------
    train_cr = F["comp_ratio"][finite_feat & in_train]
    THETA = float(np.percentile(train_cr, PERCENTILE, method="linear"))
    print(f"[theta] TRAIN-only {PERCENTILE}th percentile of compression_ratio = {THETA:.10f}"
          f"   (from {len(train_cr):,} TRAIN bars)")

    compressed = np.zeros(n, bool)
    compressed[finite_feat] = F["comp_ratio"][finite_feat] <= THETA

    long_break = np.zeros(n, bool)
    short_break = np.zeros(n, bool)
    long_break[finite_feat] = close[finite_feat] > F["range_high"][finite_feat] + BUFFER_ATR * A[finite_feat]
    short_break[finite_feat] = close[finite_feat] < F["range_low"][finite_feat] - BUFFER_ATR * A[finite_feat]
    ambiguous = int((long_break & short_break & eligible).sum())
    breakout = (long_break | short_break) & ~(long_break & short_break)
    sign = np.where(long_break, 1.0, np.where(short_break, -1.0, 0.0))

    excluded_invalid_atr = int((~finite_feat & (in_train | in_dev)).sum())

    # ---- events --------------------------------------------------------------
    events, suppressed, bl_c_events, bl_c_suppressed = {}, {}, {}, {}
    for arm, m_arm in (("TRAIN", in_train), ("DEV", in_dev)):
        events[arm], suppressed[arm] = dedup_events(compressed, breakout, eligible, m_arm)
        bl_c_events[arm], bl_c_suppressed[arm] = dedup_events(~compressed, breakout, eligible, m_arm)
    for arm in ("TRAIN", "DEV"):
        ev = events[arm]
        print(f"[events] {arm}: {len(ev):,} compression-breakout events "
              f"(suppressed {suppressed[arm]:,})   baseline-C {len(bl_c_events[arm]):,}")

    # ---- labels -------------------------------------------------------------
    arm_of = {"TRAIN": in_train, "DEV": in_dev}
    R, Rp, MFE, MAE, same_arm = {}, {}, {}, {}, {}
    for name, h in HORIZONS.items():
        fwd = np.full(n, np.nan); fwd[: n - h] = close[h:]
        with np.errstate(invalid="ignore"):
            R[name] = np.where(np.isfinite(A) & (A > 0), (fwd - close) / A, np.nan)
            nxt_open = np.full(n, np.nan); nxt_open[: n - 1] = op[1:]
            Rp[name] = np.where(np.isfinite(A) & (A > 0), (fwd - nxt_open) / A, np.nan)
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

    def signed(arr: np.ndarray, s: np.ndarray) -> np.ndarray:
        return s * arr

    # ---- primary tests ------------------------------------------------------
    results: dict = {
        "hypothesis": "research/hypothesis_01_compression_breakout.md",
        "preregistration_commit": "44419ef",
        "gate": "research/RESEARCH_TO_STRATEGY_GATE.md",
        "declared_hypotheses": N_HYPOTHESES,
        "frozen_definitions": {
            "compression_window_bars": W_COMPRESSION, "atr_length": ATR_LEN,
            "atr_convention": "A[i] = ATR_14[i-1] (Wilder, M15)",
            "percentile": PERCENTILE, "THETA_train_only": THETA,
            "breakout_buffer_atr": BUFFER_ATR,
            "horizons_m15_bars": HORIZONS,
            "deduplication": ("armed/fired state machine; must leave and re-enter the "
                              "gating regime; state resets per arm"),
        },
        "dataset": {"dataset_sha256": SPLIT["dataset_sha256"],
                    "fingerprints_verified": True,
                    "m15_rows_to_dev_boundary": int(n),
                    "panel_time_max": str(m15["time"].max()),
                    "dev_boundary": str(DEV_HI)},
        "arms": {"TRAIN": {"from": str(TRAIN_LO), "to": str(TRAIN_HI)},
                 "DEV": {"from": str(DEV_LO), "to": str(DEV_HI)},
                 "FINAL_OOS": "LOCKED - not read, not used as context"},
        "event_accounting": {
            "ambiguous_excluded": ambiguous,
            "invalid_atr_or_window_excluded": excluded_invalid_atr,
            "compression_rate_pct": {
                arm: round(100 * float(compressed[finite_feat & m].mean()), 4)
                for arm, m in arm_of.items()},
            "events": {arm: int(len(events[arm])) for arm in arm_of},
            "suppressed_by_dedup": {arm: int(suppressed[arm]) for arm in arm_of},
            "baseline_C_events": {arm: int(len(bl_c_events[arm])) for arm in arm_of},
            "baseline_C_suppressed": {arm: int(bl_c_suppressed[arm]) for arm in arm_of},
        },
        "primary": {}, "control_open_anchor": {}, "path_diagnostics": {},
        "baselines": {}, "per_arm_sides": {},
    }
    controls: dict = {"weighting_headline": Weighting.NON_OVERLAPPING,
                      "weighting_secondary": Weighting.EQUAL_BLOCK,
                      "declared_hypotheses": N_HYPOTHESES, "cells": {}}

    t_primary, t_keys = [], []
    for arm in ("TRAIN", "DEV", "POOLED"):
        for name, h in HORIZONS.items():
            if arm == "POOLED":
                idx = np.concatenate([events["TRAIN"], events["DEV"]])
            else:
                idx = events[arm]
            idx = idx[same_arm[name][idx]]
            if len(idx) == 0:
                results["primary"][f"{arm}@{name}"] = {"n_events_raw": 0, "note": "no events"}
                continue
            s = sign[idx]
            y = np.full(n, np.nan); y[idx] = s * R[name][idx]
            d = cell_report(y, idx, h, f"H01_{arm}@{name}")
            d["side_counts"] = {"LONG": int((s > 0).sum()), "SELL_SHORT": int((s < 0).sum())}
            # LONG/SHORT split -- the drift diagnostic declared in spec section 12
            for nm, sel in (("LONG", s > 0), ("SHORT", s < 0)):
                sub = idx[sel]
                if len(sub) >= 2:
                    ys = np.full(n, np.nan); ys[sub] = sign[sub] * R[name][sub]
                    keep = non_overlapping_indices(sub[np.isfinite(ys[sub])], h)
                    d[f"side_{nm}"] = {**raw_stats(ys[keep]), "n_non_overlapping": int(len(keep))}
            results["primary"][f"{arm}@{name}"] = d
            controls["cells"][f"{arm}@{name}"] = {
                "overlap": d["overlap"], "audit": d["audit"], "flags": d["flags"],
                "needs_review": d["needs_review"]}
            if arm == "TRAIN" and d["headline"].get("t") is not None:
                t_primary.append(float(d["headline"]["t"])); t_keys.append(f"{arm}@{name}")

            # control label, open[i+1] anchor -- 0 hypotheses
            yc = np.full(n, np.nan); yc[idx] = s * Rp[name][idx]
            results["control_open_anchor"][f"{arm}@{name}"] = cell_report(
                yc, idx, h, f"H01ctl_{arm}@{name}")["headline"]

            # path diagnostics -- 0 hypotheses, no stop/target derived
            mfe = np.where(s > 0, MFE[name][idx], -MAE[name][idx])
            mae = np.where(s > 0, MAE[name][idx], -MFE[name][idx])
            results["path_diagnostics"][f"{arm}@{name}"] = {
                "MFE_atr": raw_stats(mfe), "MAE_atr": raw_stats(mae),
                "note": "DIAGNOSTIC ONLY. No stop or target is selected from these."}

    # ---- baselines ----------------------------------------------------------
    for arm in ("TRAIN", "DEV"):
        m_arm = arm_of[arm]
        for name, h in HORIZONS.items():
            key = f"{arm}@{name}"
            ev = events[arm][same_arm[name][events[arm]]]
            if len(ev) == 0:
                continue
            keep_ev = non_overlapping_indices(ev[np.isfinite(R[name][ev])], h)
            p_long = float((sign[keep_ev] > 0).mean()) if len(keep_ev) else 0.0
            pool = np.flatnonzero(m_arm & eligible & same_arm[name] & np.isfinite(R[name]))

            # A -- unconditional, side-matched
            m_plus = float(np.nanmean(R[name][pool]))
            m_minus = float(np.nanmean(-R[name][pool]))
            bl_a = {"long_side_mean": round(m_plus, 6), "short_side_mean": round(m_minus, 6),
                    "p_long_from_events": round(p_long, 4),
                    "side_matched_mean": round(p_long * m_plus + (1 - p_long) * m_minus, 6),
                    "n_pool": int(len(pool)),
                    "weighting": "all eligible bars, overlapping (reference only)"}

            # B -- direction-balanced random events
            bl_b = random_baseline(R[name], pool, len(keep_ev), p_long, h,
                                   np.ones(n), RANDOM_SEED + h)
            obs = float(np.nanmean(sign[keep_ev] * R[name][keep_ev])) if len(keep_ev) else float("nan")
            if "_dist" in bl_b:
                dist = bl_b.pop("_dist")
                bl_b["observed_event_mean"] = round(obs, 6)
                bl_b["observed_percentile_rank"] = round(100 * float((dist < obs).mean()), 2)
                bl_b["empirical_p_one_sided_greater"] = round(float((dist >= obs).mean()), 5)

            # C -- breakout WITHOUT compression (the decisive comparison)
            evc = bl_c_events[arm][same_arm[name][bl_c_events[arm]]]
            bl_c = {"n_events_raw": int(len(evc))}
            if len(evc) >= 2:
                y = np.full(n, np.nan)
                y[ev] = sign[ev] * R[name][ev]
                y[evc] = sign[evc] * R[name][evc]
                m_hi = np.zeros(n, bool); m_hi[ev] = True
                m_lo = np.zeros(n, bool); m_lo[evc] = True
                c = contrast(y, m_hi, m_lo, h, label=f"C_{key}")
                kp = non_overlapping_indices(ev[np.isfinite(y[ev])], h)
                kf = non_overlapping_indices(evc[np.isfinite(y[evc])], h)
                cg = None
                if len(kp) and len(kf):
                    dmin = np.abs(kp[:, None] - kf[None, :]).min(axis=1)
                    cg = round(100 * float((dmin < h).mean()), 2)
                bl_c.update({
                    "compression_breakout": {k: c["hi"]["headline"][k]
                                             for k in ("n", "mean", "se", "t", "ci95")},
                    "breakout_without_compression": {k: c["lo"]["headline"][k]
                                                     for k in ("n", "mean", "se", "t", "ci95")},
                    "headline_diff": c.get("headline_diff"),
                    "block_diff_SECONDARY": c.get("block_diff_SECONDARY"),
                    "cross_group_overlap_pct": cg,
                    "bootstrap": {f"block_{b}": _bootstrap_diff(y, m_hi, m_lo, b,
                                                                BOOTSTRAP_REPLICATES,
                                                                BOOTSTRAP_SEED + b)
                                  for b in BOOTSTRAP_BLOCKS},
                    "flags": c["flags"],
                    "note": ("DECLARED BASELINE, 0 hypotheses. Cannot promote the candidate.")})
            results["baselines"][key] = {"A_unconditional_side_matched": bl_a,
                                         "B_random_direction_balanced": bl_b,
                                         "C_breakout_without_compression": bl_c}

    # ---- multiple testing over the declared 3 (primary arm = TRAIN) ---------
    padded = list(t_primary) + [0.0] * (N_HYPOTHESES - len(t_primary))
    pvals = [math.erfc(abs(v) / math.sqrt(2)) for v in padded]
    bh = benjamini_hochberg(pvals, ALPHA)
    thr = bonferroni_t(N_HYPOTHESES, ALPHA)
    results["multiple_testing"] = {
        "primary_arm": "TRAIN",
        "n_declared": N_HYPOTHESES, "n_with_computable_t": len(t_primary),
        "n_padded_as_non_rejection": N_HYPOTHESES - len(t_primary),
        "nominal_alpha": ALPHA, "bonferroni_threshold_t": round(thr, 4),
        "t_values": {k: round(v, 4) for k, v in zip(t_keys, t_primary)},
        "survivors_bonferroni": [k for k, v in zip(t_keys, t_primary) if abs(v) >= thr],
        "benjamini_hochberg": bh,
        "max_abs_t": (round(max(abs(v) for v in t_primary), 4) if t_primary else None),
        "observed_abs_t_ge_2": int(sum(1 for v in t_primary if abs(v) >= 2)),
        "expected_abs_t_ge_2_under_null": round(0.0455 * N_HYPOTHESES, 4),
        "note": ("One-sided positive hypothesis; the threshold shown is two-sided, "
                 "which is conservative for a directional claim and is reported as such."),
    }

    # ---- power --------------------------------------------------------------
    power = {}
    for arm in ("TRAIN", "DEV"):
        for name, h in HORIZONS.items():
            d = results["primary"].get(f"{arm}@{name}", {})
            se = (d.get("headline") or {}).get("se")
            if se and se == se:
                power[f"{arm}@{name}"] = {
                    "non_overlapping_n": d["n_events_non_overlapping"],
                    "se": round(se, 5),
                    "mde_2se_atr": round(2 * se, 4),
                    "mde_bonferroni_atr": round(thr * se, 4),
                    "cost_atr_reference": COST_ATR[arm],
                    "can_detect_cost_sized_effect": bool(thr * se <= COST_ATR[arm])}
    results["power"] = power

    # ---- causal reconstruction (prefix rebuild) -----------------------------
    rng = np.random.default_rng(7)
    allev = np.concatenate([events["TRAIN"], events["DEV"]])
    probe = np.sort(rng.choice(allev, size=min(40, len(allev)), replace=False)) if len(allev) else []
    maxdev = 0.0
    for i in probe:
        pre = m15.iloc[: int(i)]                      # bars 0 .. i-1 only
        a = float(ta.atr(pre["high"], pre["low"], pre["close"], length=ATR_LEN).iloc[-1])
        rh = float(pre["high"].tail(W_COMPRESSION).max())
        rl = float(pre["low"].tail(W_COMPRESSION).min())
        maxdev = max(maxdev, abs(a - A[i]), abs(rh - F["range_high"][i]), abs(rl - F["range_low"][i]))
    controls["causal_reconstruction"] = {
        "probes": int(len(probe)),
        "max_abs_deviation": maxdev,
        "exactly_zero": bool(maxdev == 0.0),
        "method": ("features rebuilt from m15.iloc[:i] (bars 0..i-1 only) and compared "
                   "to the panel value at i")}
    print(f"[causal] prefix rebuild over {len(probe)} events: max deviation {maxdev:.3e}")

    controls["forward_window_audits"] = {}
    for arm in ("TRAIN", "DEV"):
        for name, h in HORIZONS.items():
            ev = events[arm][same_arm[name][events[arm]]]
            keep = non_overlapping_indices(ev[np.isfinite(R[name][ev])], h)
            controls["forward_window_audits"][f"{arm}@{name}"] = forward_window_audit(keep, h)
    controls["sign_disagreement_cells"] = [
        k for k, v in controls["cells"].items()
        if "ESTIMATOR_SIGN_DISAGREEMENT" in (v.get("flags") or [])]
    controls["theta_frozen_from"] = {"arm": "TRAIN", "percentile": PERCENTILE,
                                     "value": THETA, "n_train_bars": int(len(train_cr))}
    controls["no_alternative_hypothesis_tested"] = {
        "compression_windows_tested": [W_COMPRESSION],
        "breakout_buffers_tested": [BUFFER_ATR],
        "percentiles_tested": [PERCENTILE],
        "horizons_tested": sorted(HORIZONS.values()),
        "statement": ("One compression window, one buffer, one percentile, three "
                      "pre-declared horizons. No alternative was computed.")}
    controls["final_oos"] = {"opened": False, "panel_truncated_at": str(DEV_HI),
                             "token": "OOS-AUTHORISATION-NOT-ISSUED"}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hypothesis_01_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "hypothesis_01_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")

    # ------------------------------------------------------------------ console
    print("\n" + "=" * 92)
    print("EVENT ACCOUNTING")
    print("=" * 92)
    ea = results["event_accounting"]
    print(f"  THETA (TRAIN 20th pct, frozen)      : {THETA:.6f}")
    print(f"  compression rate   TRAIN {ea['compression_rate_pct']['TRAIN']:6.2f}%"
          f"   DEV {ea['compression_rate_pct']['DEV']:6.2f}%   (DEV uses the frozen TRAIN theta)")
    print(f"  events             TRAIN {ea['events']['TRAIN']:6,}   DEV {ea['events']['DEV']:6,}")
    print(f"  suppressed by dedup TRAIN {ea['suppressed_by_dedup']['TRAIN']:5,}"
          f"   DEV {ea['suppressed_by_dedup']['DEV']:5,}")
    print(f"  baseline-C events  TRAIN {ea['baseline_C_events']['TRAIN']:6,}"
          f"   DEV {ea['baseline_C_events']['DEV']:6,}")
    print(f"  ambiguous excluded : {ea['ambiguous_excluded']}      "
          f"invalid ATR/window excluded : {ea['invalid_atr_or_window_excluded']:,}")

    print("\n" + "=" * 92)
    print("PRIMARY -- E[R_h] > 0 on NON-OVERLAPPING events  (headline)")
    print("=" * 92)
    print(f"  {'cell':14s} {'raw n':>6s} {'non-ov':>7s} {'ov':>6s} {'mean':>9s} {'median':>9s}"
          f" {'sd':>7s} {'se':>7s} {'t':>7s}  95% CI")
    for arm in ("TRAIN", "DEV", "POOLED"):
        for name in HORIZONS:
            d = results["primary"].get(f"{arm}@{name}", {})
            hd = d.get("headline")
            if not hd or hd.get("t") is None:
                print(f"  {arm}@{name:9s}  no computable statistic")
                continue
            o, ci = d["overlap"], hd["ci95"]
            print(f"  {arm}@{name:9s} {d['n_events_raw']:6,} {d['n_events_non_overlapping']:7,}"
                  f" {o['overlap_ratio']:5.1f}x {hd['mean']:+9.4f} {hd['median']:+9.4f}"
                  f" {hd['sd']:7.3f} {hd['se']:7.4f} {hd['t']:+7.2f}"
                  f"  [{ci[0]:+.4f}, {ci[1]:+.4f}]")

    print("\n" + "=" * 92)
    print("LONG / SHORT SPLIT -- the drift diagnostic declared in the preregistration")
    print("=" * 92)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            d = results["primary"].get(f"{arm}@{name}", {})
            L, S = d.get("side_LONG"), d.get("side_SHORT")
            if not L or not S:
                continue
            print(f"  {arm}@{name:4s}  LONG n={L['n_non_overlapping']:4d} mean {L['mean']:+.4f}"
                  f"   SHORT n={S['n_non_overlapping']:4d} mean {S['mean']:+.4f}")

    print("\n" + "=" * 92)
    print("MULTIPLE TESTING  (declared 3, primary arm TRAIN)")
    print("=" * 92)
    mt = results["multiple_testing"]
    print(f"  t values                  : {mt['t_values']}")
    print(f"  Bonferroni threshold |t|  : {mt['bonferroni_threshold_t']}")
    print(f"  Bonferroni survivors      : {len(mt['survivors_bonferroni'])} {mt['survivors_bonferroni']}")
    print(f"  BH survivors              : {bh.get('n_survivors')}")
    print(f"  max |t|                   : {mt['max_abs_t']}")
    print(f"  observed |t| >= 2         : {mt['observed_abs_t_ge_2']}"
          f"   expected {mt['expected_abs_t_ge_2_under_null']}")

    print("\n" + "=" * 92)
    print("BASELINE C -- compression+breakout  vs  breakout WITHOUT compression")
    print("=" * 92)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            b = (results["baselines"].get(f"{arm}@{name}") or {}).get("C_breakout_without_compression", {})
            hd = b.get("headline_diff")
            if not hd:
                continue
            bs = b["bootstrap"]["block_96"]
            print(f"  {arm}@{name:4s} comp n={hd['n_hi']:4d} mean {b['compression_breakout']['mean']:+.4f}"
                  f" | nocomp n={hd['n_lo']:5d} mean {b['breakout_without_compression']['mean']:+.4f}"
                  f" | diff {hd['diff']:+.4f} t {hd['t']:+.2f}"
                  f" | boot t {('%+.2f' % bs['t']) if bs.get('t') is not None else 'n/a'}"
                  f" | x-overlap {b.get('cross_group_overlap_pct')}%")

    print("\n" + "=" * 92)
    print("BASELINE B -- direction-balanced random events")
    print("=" * 92)
    for arm in ("TRAIN", "DEV"):
        for name in HORIZONS:
            b = (results["baselines"].get(f"{arm}@{name}") or {}).get("B_random_direction_balanced", {})
            if "observed_event_mean" not in b:
                continue
            print(f"  {arm}@{name:4s} observed {b['observed_event_mean']:+.4f}"
                  f"  random mean {b['mean']:+.4f} sd {b['sd']:.4f}"
                  f"  [{b['pct2_5']:+.4f}, {b['pct97_5']:+.4f}]"
                  f"  pct-rank {b['observed_percentile_rank']:5.1f}  p(>=obs) {b['empirical_p_one_sided_greater']}")

    print("\n" + "=" * 92)
    print("POWER")
    print("=" * 92)
    for k, v in power.items():
        print(f"  {k:12s} n={v['non_overlapping_n']:5,}  se {v['se']:.4f}"
              f"  MDE(2se) {v['mde_2se_atr']:.3f}  MDE(Bonf) {v['mde_bonferroni_atr']:.3f} ATR"
              f"  cost {v['cost_atr_reference']}  detectable={v['can_detect_cost_sized_effect']}")

    print("\n" + "=" * 92)
    print("CONTROLS")
    print("=" * 92)
    print(f"  causal prefix rebuild max deviation : {maxdev:.3e}  exactly zero={maxdev == 0.0}")
    print(f"  ESTIMATOR_SIGN_DISAGREEMENT cells   : {len(controls['sign_disagreement_cells'])}"
          f" {controls['sign_disagreement_cells']}")
    nd = [k for k, v in controls["forward_window_audits"].items() if not v["disjoint"]]
    print(f"  forward-window audits non-disjoint  : {len(nd)} {nd}")
    print(f"  FINAL_OOS opened                    : {controls['final_oos']['opened']}")
    print(f"\n  wrote {out_dir/'hypothesis_01_results.json'}")
    print(f"  wrote {out_dir/'hypothesis_01_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
