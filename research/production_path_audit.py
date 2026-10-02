"""Phase 3 -- production path decomposition: analysis.

Consumes the panel built by production_path_reconstruction.py and produces the
21 pre-declared tests, the neutral accounting, the descriptive-only sections and
the controls record. Nothing is optimised, no layer is ranked, no component is
selected.

Frozen specification: research/production_path_spec.md (predates this file).
Statistical standard: research/STATISTICAL_RESEARCH_CONTROLS.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.phase1_statistical_controls import (                   # noqa: E402
    Weighting, bonferroni_t, conditional_stat, contrast,
    multiple_testing_report, non_overlapping_indices,
)

HORIZONS = {"1h": 4, "2h": 8, "4h": 16}

# The 7 incremental layers, frozen in the spec. Order is the spec's order, which
# is the production execution order; it is NOT a ranking.
LAYERS = [
    ("B", "gate_B_h1_regime", "H1 regime gate (h1_atr >= 8.0)"),
    ("C", "gate_C_displacement", "Displacement candle aligned with bias"),
    ("D", "gate_D_structure", "H1 structure confirmation (HH/HL | LH/LL)"),
    ("E", "gate_E_sweep", "L5 sweep / CHoCH passes"),
    ("F", "gate_F_poi", "L6 POI passes"),
    ("G", "gate_G_session", "Session gate (kill zone)"),
    ("H", "gate_H_pullback", "L3 pullback passes"),
]

# Measured median spread, $0.33 round turn (1 x spread), and median ATR per arm
# from research_split_manifest.json. Reference scale only.
SPREAD_ROUND_TURN_USD = 0.33
MEDIAN_ATR_USD = {"TRAIN": 2.085, "DEV": 3.564}


def _as_bool_array(series: pd.Series, n: int, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scatter a nullable boolean column into full M15 index space.

    Returns (value, defined) where `defined` is False wherever the gate was not
    evaluable (NEUTRAL bias, or a production call that failed).
    """
    val = np.zeros(n, bool)
    dfn = np.zeros(n, bool)
    raw = series.to_numpy(object)
    ok = np.array([v is not None and v is not np.nan and not (isinstance(v, float) and math.isnan(v))
                   for v in raw], bool)
    dfn[pos[ok]] = True
    val[pos[ok]] = np.array([bool(v) for v in raw[ok]], bool)
    return val, dfn




# Block lengths for the bootstrap control, in M15 bars. Both are reported;
# neither is selected on the basis of its result. 96 bars = 24h, 480 = 1 week.
# Every horizon tested is at most 16 bars, so both exceed it by a wide margin.
BOOTSTRAP_BLOCKS = (96, 480)
BOOTSTRAP_REPLICATES = 4000
BOOTSTRAP_SEED = 20260302


def _block_bootstrap_diff(y: np.ndarray, m_pass: np.ndarray, m_fail: np.ndarray,
                          block: int, reps: int, seed: int) -> dict:
    """Moving-block bootstrap SE for mean(pass) - mean(fail).

    The analytic contrast pools two independent standard errors. The two samples
    are internally non-overlapping but their forward windows overlap EACH OTHER,
    so that independence does not hold. A block bootstrap resamples contiguous
    spans of calendar time and therefore carries the cross-group dependence with
    it, whatever its sign.
    """
    ok = np.isfinite(y)
    p_ok, f_ok = m_pass & ok, m_fail & ok
    n = len(y)
    nb = int(np.ceil(n / block))
    edges = np.minimum(np.arange(nb + 1) * block, n)
    ys = np.where(p_ok, y, 0.0)
    yf = np.where(f_ok, y, 0.0)
    S1 = np.add.reduceat(ys, edges[:-1])
    N1 = np.add.reduceat(p_ok.astype(float), edges[:-1])
    S0 = np.add.reduceat(yf, edges[:-1])
    N0 = np.add.reduceat(f_ok.astype(float), edges[:-1])

    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nb, size=(reps, nb))
    s1 = S1[pick].sum(1); n1 = N1[pick].sum(1)
    s0 = S0[pick].sum(1); n0 = N0[pick].sum(1)
    good = (n1 > 0) & (n0 > 0)
    d = np.full(reps, np.nan)
    d[good] = s1[good] / n1[good] - s0[good] / n0[good]
    d = d[np.isfinite(d)]
    if len(d) < 100 or not (N1.sum() and N0.sum()):
        return {"block_bars": block, "replicates_used": int(len(d)), "se": None, "t": None}
    point = S1.sum() / N1.sum() - S0.sum() / N0.sum()
    se = float(np.std(d, ddof=1))
    return {"block_bars": block, "replicates_used": int(len(d)),
            "point_all_observations": round(float(point), 6),
            "se": round(se, 6),
            "t": (round(float(point) / se, 4) if se > 0 else None),
            "ci95": [round(float(np.percentile(d, 2.5)), 6),
                     round(float(np.percentile(d, 97.5)), 6)],
            "weighting": "block bootstrap over ALL observations (not non-overlapping)"}

def _forensics() -> dict:
    """Four-trade causal trace from the FROZEN baseline_008 artifacts.

    FORENSIC AND DESCRIPTIVE ONLY. n = 4. No statistic is computed from these
    trades, no threshold is derived from them, and they are not used as evidence
    for or against any layer. baseline_008 derives from data/raw, not from
    data/research_v1, and dataset_access is not used here -- no FINAL_OOS arm of
    the research dataset is read.
    """
    b = REPO / "baselines" / "baseline_008"
    out: dict = {"source": "baselines/baseline_008 (frozen)",
                 "scope": "FORENSIC / DESCRIPTIVE ONLY -- n=4, not evidence"}
    led = json.loads((b / "trade_ledger.json").read_text(encoding="utf-8"))
    out["trades"] = [{
        "decision_bar_time": r["decision_bar_time"],
        "side": r["side"], "regime": r["regime"], "setup_type": r["setup_type"],
        "entry_method": r["entry_method"],
        "layers_passed": r["metadata"].get("layers_passed"),
        "grade": r["metadata"].get("grade"),
        "ledger_confidence_field": r["confidence"],
        "exit_reason": r["exit_reason"], "outcome": r["outcome"],
        "r_multiple": r["r_multiple"], "net_pnl": r["net_pnl"],
        "bars_held": r["bars_held"],
    } for r in led]
    out["common_to_all_four"] = {
        "regime": sorted({r["regime"] for r in led}),
        "entry_method": sorted({r["entry_method"] for r in led}),
        "layers_passed_identical": len({tuple(r["metadata"]["layers_passed"]) for r in led}) == 1,
        "layers_passed": led[0]["metadata"]["layers_passed"],
        "L3_bypassed": all("L3_PULLBACK_BYPASSED" in r["metadata"]["layers_passed"] for r in led),
        "L6_bypassed": all("L6_POI_BYPASSED" in r["metadata"]["layers_passed"] for r in led),
    }
    out["decision_statistics"] = json.loads((b / "decision_statistics.json").read_text(encoding="utf-8"))
    funnel = json.loads((b / "layer_funnel.json").read_text(encoding="utf-8"))
    out["layer_funnel_as_published"] = funnel["blocked_at"]

    dj = b / "decisions.jsonl"
    if dj.exists():
        import collections
        blocked = collections.Counter(); regimes = collections.Counter()
        with dj.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                blocked[d.get("blocked")] += 1
                regimes[d.get("regime")] += 1
        out["blocked_raw_from_decisions_jsonl"] = dict(blocked.most_common())
        out["regime_distribution"] = dict(regimes.most_common())
        agg = blocked.get("L5_SWEEP", 0) + blocked.get("L5_SWEEP_WAIT", 0)
        out["funnel_aggregation_discrepancy"] = {
            "observed": "layer_funnel.json reports a single L5_SWEEP bucket.",
            "detail": ("decisions.jsonl distinguishes L5_SWEEP from L5_SWEEP_WAIT: "
                       f"{blocked.get('L5_SWEEP', 0)} + {blocked.get('L5_SWEEP_WAIT', 0)} = {agg}, "
                       f"published as L5_SWEEP = {funnel['blocked_at'].get('L5_SWEEP')}."),
            "consequence": ("The published funnel does not separate 'no sweep' from "
                            "'waiting for confirmation'. RECORDED, NOT FIXED."),
        }
    else:
        out["blocked_raw_from_decisions_jsonl"] = "decisions.jsonl not present (gitignored)"

    out["observed_discrepancies"] = [
        ("All four signals carry grade 'A' while the ledger confidence field is 0.0. "
         "L7 admits on conf['final_score'] >= 55 for MICRO_SCALP, so the ledger's "
         "confidence field does not carry the score L7 gated on. RECORDED, NOT FIXED."),
        ("All four signals bypassed L3 and L6 via the regime flags, so the only path "
         "that ever produced a signal evaluated six of the eight layers, not eight."),
    ]
    return out

def run(panel_path: Path, out_dir: Path) -> None:
    panel = pd.read_pickle(panel_path)
    n_m15 = int(panel["i"].max()) + 1
    pos = panel["i"].to_numpy(int)

    results: dict = {"spec": "research/production_path_spec.md",
                     "standard": "research/STATISTICAL_RESEARCH_CONTROLS.md",
                     "panel_rows": int(len(panel)),
                     "declared_hypotheses": len(LAYERS) * len(HORIZONS)}
    controls: dict = {"weighting_headline": Weighting.NON_OVERLAPPING,
                      "weighting_secondary": Weighting.EQUAL_BLOCK,
                      "declared_hypotheses": len(LAYERS) * len(HORIZONS),
                      "cells": {}}

    # ---------------------------------------------------------------- section 1
    # Neutral accounting, BEFORE any directional analysis. Neutral observations
    # are not dropped from the denominator.
    bias = panel["bias"].to_numpy(object)
    acct = {"total_eligible": int(len(panel))}
    for lbl in ("BULLISH", "BEARISH", "NEUTRAL"):
        c = int((bias == lbl).sum())
        acct[lbl] = {"n": c, "pct": round(100 * c / len(panel), 3)}
    acct["by_arm"] = {}
    for arm in ("TRAIN", "DEV"):
        sub = panel[panel["arm"] == arm]
        acct["by_arm"][arm] = {"total": int(len(sub)), **{
            lbl: {"n": int((sub["bias"] == lbl).sum()),
                  "pct": round(100 * (sub["bias"] == lbl).mean(), 3)} for lbl in
            ("BULLISH", "BEARISH", "NEUTRAL")}}
    nfail = int((panel["fail"].astype(str).str.strip() != "").sum())
    acct["rows_with_production_call_failure"] = nfail
    results["neutral_accounting"] = acct

    # direction-normalised labels in full M15 index space
    sign = np.zeros(n_m15)
    sign[pos] = np.where(bias == "BULLISH", 1.0, np.where(bias == "BEARISH", -1.0, 0.0))
    sided = np.zeros(n_m15, bool)
    sided[pos] = (bias != "NEUTRAL")
    arm_train = np.zeros(n_m15, bool); arm_train[pos] = (panel["arm"] == "TRAIN").to_numpy()
    arm_dev = np.zeros(n_m15, bool); arm_dev[pos] = (panel["arm"] == "DEV").to_numpy()

    Y: dict[str, np.ndarray] = {}
    for name in HORIZONS:
        y = np.full(n_m15, np.nan)
        y[pos] = panel["fwd_" + name].to_numpy(float)
        Y[name] = y * sign          # +1 for BUY, -1 for SELL

    gates: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for _, col, _ in LAYERS:
        gates[col] = _as_bool_array(panel[col], n_m15, pos)

    # ---------------------------------------------------------------- section 2
    # Baseline: bias alone. Reported, not a hypothesis.
    base = {}
    for name, h in HORIZONS.items():
        cs = conditional_stat(Y[name], sided, h, f"baseline_bias_alone@{name}")
        base[name] = cs.to_dict()
        controls["cells"][f"baseline@{name}"] = {
            "overlap": cs.overlap, "audit": cs.audit, "flags": cs.flags,
            "needs_review": cs.needs_review}
    results["baseline_bias_alone"] = base

    # ---------------------------------------------------------------- section 3
    # The 21 declared tests. Headline statistic is the DISJOINT pass-vs-fail
    # contrast inside the bias population. The declared effect size, excess over
    # the bias-only population, is reported alongside; the two are related by
    #   mean_pass - mean_all = (1 - p) * (mean_pass - mean_fail),  p = pass rate,
    # so they share a sign and a null hypothesis.
    tests: dict = {}
    t_values: list[float] = []
    t_keys: list[str] = []
    for code, col, desc in LAYERS:
        val, dfn = gates[col]
        for name, h in HORIZONS.items():
            key = f"{code}@{name}"
            m_pass = sided & dfn & val
            m_fail = sided & dfn & ~val
            c = contrast(Y[name], m_pass, m_fail, h, label=f"{code}_{col}@{name}")
            hd = c.get("headline_diff")

            # declared effect size: excess over bias-only
            bh = conditional_stat(Y[name], sided & dfn, h).headline
            ph = c["hi"]["headline"]
            excess = (ph["mean"] - bh["mean"]) if (ph["n"] and bh["n"]) else None

            rec = {
                "code": code, "layer": desc, "column": col, "horizon": name,
                "horizon_bars": h,
                "n_defined": int((sided & dfn).sum()),
                "n_pass_raw": int(m_pass.sum()),
                "n_fail_raw": int(m_fail.sum()),
                "pass_rate_pct": (round(100 * m_pass.sum() / max((sided & dfn).sum(), 1), 3)),
                # Section F disclosure for the layer-pass population itself.
                "pass_population": {
                    "raw_n": c["hi"]["overlap"]["raw_observations"],
                    "non_overlapping_n": c["hi"]["overlap"]["non_overlapping_observations"],
                    "overlap_ratio": c["hi"]["overlap"]["overlap_ratio"],
                    "mean": ph["mean"], "se": ph["se"], "t_vs_zero": ph["t"],
                    "ci95": ph["ci95"], "weighting": ph["weighting"],
                    "raw_mean_OVERLAPPING": c["hi"]["raw"]["mean"],
                    "block_mean_SECONDARY": c["hi"]["block"].get("mean")},
                "fail_population": {
                    "raw_n": c["lo"]["overlap"]["raw_observations"],
                    "non_overlapping_n": c["lo"]["overlap"]["non_overlapping_observations"],
                    "overlap_ratio": c["lo"]["overlap"]["overlap_ratio"],
                    "mean": c["lo"]["headline"]["mean"], "se": c["lo"]["headline"]["se"],
                    "ci95": c["lo"]["headline"]["ci95"]},
                "headline_pass_vs_fail": hd,
                "excess_over_bias_only": (round(excess, 6) if excess is not None else None),
                "mean_pass": ph["mean"], "mean_fail": c["lo"]["headline"]["mean"],
                "mean_bias_only": bh["mean"],
                "block_diff_SECONDARY": c.get("block_diff_SECONDARY"),
                "raw_diff_OVERLAPPING": c.get("raw_diff_OVERLAPPING"),
                "flags": c["flags"], "needs_review": c["needs_review"],
            }
            # cross-group forward-window overlap: the two non-overlapping samples
            # are internally disjoint but may overlap EACH OTHER. Disclosed.
            kp = non_overlapping_indices(np.flatnonzero(m_pass & np.isfinite(Y[name])), h)
            kf = non_overlapping_indices(np.flatnonzero(m_fail & np.isfinite(Y[name])), h)
            if len(kp) and len(kf):
                d = np.abs(kp[:, None] - kf[None, :]).min(axis=1) if len(kp) * len(kf) < 4e7 else None
                rec["cross_group_overlap_pct"] = (
                    round(100 * float((d < h).mean()), 2) if d is not None else "not_computed_too_large")
            tests[key] = rec
            controls["cells"][key] = {
                "overlap_pass": c["hi"]["overlap"], "overlap_fail": c["lo"]["overlap"],
                "audit_pass": c["hi"]["audit"], "audit_fail": c["lo"]["audit"],
                "flags": c["flags"], "cross_group_overlap_pct": rec.get("cross_group_overlap_pct")}
            if hd and hd.get("t") is not None:
                t_values.append(float(hd["t"])); t_keys.append(key)
    results["tests"] = tests

    # ---- bootstrap control: the analytic contrast assumes the pass and fail
    # samples are independent of each other. Measured cross-group forward-window
    # overlap reaches ~100% in several cells, so that assumption fails. This
    # re-estimates the same 21 differences without it. It is a CONTROL, not a new
    # hypothesis: the declared headline remains the non-overlapping contrast.
    boot: dict = {}
    for code, col, _ in LAYERS:
        val, dfn = gates[col]
        for name, h in HORIZONS.items():
            m_pass = sided & dfn & val
            m_fail = sided & dfn & ~val
            boot[f"{code}@{name}"] = {
                f"block_{b}": _block_bootstrap_diff(Y[name], m_pass, m_fail, b,
                                                    BOOTSTRAP_REPLICATES,
                                                    BOOTSTRAP_SEED + b)
                for b in BOOTSTRAP_BLOCKS}
    results["bootstrap_control"] = {
        "why": ("The analytic pass-vs-fail contrast pools two standard errors as if "
                "the samples were independent. They are internally non-overlapping "
                "but their forward windows overlap each other, up to ~100% in some "
                "cells. A moving-block bootstrap carries that dependence."),
        "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
        "block_lengths_m15_bars": list(BOOTSTRAP_BLOCKS),
        "note": "CONTROL ONLY. The declared headline is the non-overlapping contrast.",
        "cells": boot}

    # ---------------------------------------------------------------- section 4
    n_declared = len(LAYERS) * len(HORIZONS)
    # Correction over the DECLARED count, not the computable count. A cell whose
    # t cannot be formed (an empty pass or fail group) is padded with t = 0, i.e.
    # treated as a non-rejection, so m stays 21 and BH is not made more liberal
    # by cells that produced no statistic.
    padded = list(t_values) + [0.0] * (n_declared - len(t_values))
    mt = multiple_testing_report(padded, alpha=0.05)
    mt["n_declared"] = n_declared
    mt["n_with_computable_t"] = len(t_values)
    mt["n_padded_as_non_rejection"] = n_declared - len(t_values)
    mt["bonferroni_threshold_t"] = bonferroni_t(len(LAYERS) * len(HORIZONS), 0.05)
    mt["survivors_bonferroni"] = [k for k, t in zip(t_keys, t_values)
                                  if abs(t) >= mt["bonferroni_threshold_t"]]
    mt["max_abs_t"] = (max(abs(t) for t in t_values) if t_values else None)
    mt["max_abs_t_cell"] = (t_keys[int(np.argmax(np.abs(t_values)))] if t_values else None)
    mt["observed_abs_t_ge_2"] = int(sum(1 for t in t_values if abs(t) >= 2))
    mt["expected_abs_t_ge_2_under_null"] = round(0.0455 * n_declared, 3)
    results["multiple_testing"] = mt

    # ---------------------------------------------------------------- section 5
    # Temporal robustness, SURVIVORS ONLY. Run unconditionally over zero cells
    # when there are no survivors -- that is the correct behaviour, not an omission.
    robust: dict = {}
    for key in mt["survivors_bonferroni"]:
        rec = tests[key]
        val, dfn = gates[rec["column"]]
        h = rec["horizon_bars"]
        seg = {}
        for arm, m_arm in (("TRAIN", arm_train), ("DEV", arm_dev)):
            c = contrast(Y[rec["horizon"]], sided & dfn & val & m_arm,
                         sided & dfn & ~val & m_arm, h, label=f"{key}:{arm}")
            seg[arm] = c.get("headline_diff")
        robust[key] = seg
    results["temporal_robustness_survivors_only"] = robust
    results["temporal_robustness_note"] = (
        "Run for Bonferroni survivors only, per the standard. "
        f"{len(mt['survivors_bonferroni'])} survivors.")

    # ---------------------------------------------------------------- section 6
    # Per-arm breakdown of every cell: reported for completeness, NOT used to
    # select a period or a layer.
    per_arm: dict = {}
    for code, col, _ in LAYERS:
        val, dfn = gates[col]
        for name, h in HORIZONS.items():
            for arm, m_arm in (("TRAIN", arm_train), ("DEV", arm_dev)):
                c = contrast(Y[name], sided & dfn & val & m_arm,
                             sided & dfn & ~val & m_arm, h, label=f"{code}@{name}:{arm}")
                hd = c.get("headline_diff")
                per_arm[f"{code}@{name}:{arm}"] = (
                    None if not hd else {k: hd[k] for k in ("diff", "se", "t", "n_hi", "n_lo")})
    results["per_arm_SECONDARY"] = per_arm

    # ---------------------------------------------------------------- section 7
    # DESCRIPTIVE ONLY.
    s = panel[panel["bias"] != "NEUTRAL"]
    desc = {
        "L4_state_distribution": {k: int(v) for k, v in s["l4_state"].value_counts().items()},
        "L5_reason_distribution": {k: int(v) for k, v in s["l5_reason"].value_counts().items()},
        "structure_type_distribution": {k: int(v) for k, v in panel["struct_type"].value_counts().items()},
        "h1_atr": {q: round(float(panel["h1_atr"].quantile(q / 100)), 3)
                   for q in (1, 5, 25, 50, 75, 95, 99)},
        "pct_bars_h1_atr_below_8": round(100 * float((panel["h1_atr"] < 8.0).mean()), 3),
        "L7_confidence_score": {
            "note": "DESCRIPTIVE ONLY. The production regime string cannot be derived "
                    "(M5 has zero bars in TRAIN), so get_confidence_engine was called "
                    "with its default regime and the L7 GATE was not evaluated.",
            "quantiles": {q: round(float(s["conf_score"].quantile(q / 100)), 2)
                          for q in (1, 5, 25, 50, 75, 95, 99)},
            "grade_distribution": {k: int(v) for k, v in s["conf_grade"].value_counts().items()},
            "pct_at_or_above_55": round(100 * float((s["conf_score"] >= 55).mean()), 3),
            "pct_at_or_above_70": round(100 * float((s["conf_score"] >= 70).mean()), 3),
            "pct_at_or_above_75": round(100 * float((s["conf_score"] >= 75).mean()), 3)},
        "L8_entry_trigger": {
            "classification": "UNTESTABLE / DESCRIPTIVE ONLY",
            "reason": "get_entry_trigger requires M5 and M1. M1 has ZERO bars in TRAIN "
                      "and ZERO in DEV inside the authorised window."},
        "regime_dependent_gates": {
            "classification": "UNTESTABLE / DESCRIPTIVE ONLY",
            "reason": "detect_regime requires M5, which has zero bars in TRAIN. "
                      "bypass_l3, bypass_l6 and the L7 threshold therefore cannot be "
                      "evaluated over the authorised window."},
        "poi_score": {q: round(float(s["poi_score"].quantile(q / 100)), 2)
                      for q in (5, 25, 50, 75, 95)},
        "sweep_quality": {q: round(float(s["sweep_quality"].quantile(q / 100)), 2)
                          for q in (5, 25, 50, 75, 95)},
        "pullback_quality": {q: round(float(s["pullback_quality"].quantile(q / 100)), 2)
                             for q in (5, 25, 50, 75, 95)},
    }
    results["descriptive_only"] = desc

    # ---------------------------------------------------------------- section 8
    # Cost reference scale. The cost screen runs only for survivors.
    results["cost_reference"] = {
        "round_turn_convention": "1 x spread (ask = mid + S/2, bid = mid - S/2)",
        "round_turn_usd": SPREAD_ROUND_TURN_USD,
        "round_turn_in_atr_units": {k: round(SPREAD_ROUND_TURN_USD / v, 4)
                                    for k, v in MEDIAN_ATR_USD.items()},
        "cost_screen_run": bool(mt["survivors_bonferroni"]),
        "note": "No cost screen is performed for a layer that does not survive the "
                "statistical screen, per the standard."}

    # ---------------------------------------------------------------- section 9
    results["baseline_008_forensics"] = _forensics()

    # ---------------------------------------------------------------- controls
    controls["panel_time_min"] = str(panel["time"].min())
    controls["panel_time_max"] = str(panel["time"].max())
    controls["rows_with_production_call_failure"] = nfail
    controls["sign_disagreement_cells"] = [k for k, v in controls["cells"].items()
                                           if "ESTIMATOR_SIGN_DISAGREEMENT" in (v.get("flags") or [])]
    controls["cells_needing_review"] = [k for k, v in controls["cells"].items() if v.get("flags")]
    controls["power"] = {}
    for name, h in HORIZONS.items():
        ses = [tests[f"{c}@{name}"]["headline_pass_vs_fail"]["se"]
               for c, _, _ in LAYERS if tests[f"{c}@{name}"]["headline_pass_vs_fail"]]
        if ses:
            controls["power"][name] = {
                "median_se": round(float(np.median(ses)), 4),
                "mde_2se_atr": round(2 * float(np.median(ses)), 4),
                "mde_bonferroni_atr": round(mt["bonferroni_threshold_t"] * float(np.median(ses)), 4)}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "production_path_audit_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "production_path_audit_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------------- console
    print("=" * 78)
    print("NEUTRAL ACCOUNTING  (before any directional analysis)")
    print("=" * 78)
    print(f"  total eligible M15 decisions : {acct['total_eligible']:,}")
    for lbl in ("BULLISH", "BEARISH", "NEUTRAL"):
        print(f"  {lbl:8s} {acct[lbl]['n']:7,}  ({acct[lbl]['pct']:5.2f}%)")
    print(f"  production-call failures     : {nfail:,}")
    for arm in ("TRAIN", "DEV"):
        a = acct["by_arm"][arm]
        print(f"  {arm:5s} total {a['total']:7,}  BULL {a['BULLISH']['n']:6,}"
              f"  BEAR {a['BEARISH']['n']:6,}  NEUT {a['NEUTRAL']['n']:6,}"
              f" ({a['NEUTRAL']['pct']:.1f}%)")

    print("\n" + "=" * 78)
    print("BASELINE -- bias alone (reported, not a hypothesis)")
    print("=" * 78)
    print(f"  {'hor':4s} {'raw n':>8s} {'non-ov n':>9s} {'ov':>6s} {'mean':>9s} {'se':>7s} {'t':>7s}  95% CI")
    for name in HORIZONS:
        b = base[name]
        h, o = b["headline"], b["overlap"]
        ci = h["ci95"]
        print(f"  {name:4s} {o['raw_observations']:8,} {o['non_overlapping_observations']:9,}"
              f" {o['overlap_ratio']:5.1f}x {h['mean']:+9.4f} {h['se']:7.4f} {h['t']:+7.2f}"
              f"  [{ci[0]:+.4f}, {ci[1]:+.4f}]")

    print("\n" + "=" * 78)
    print("THE 21 DECLARED TESTS -- layer PASS vs FAIL inside the bias population")
    print("  headline = non-overlapping. 'excess' = mean(pass) - mean(bias-only).")
    print("=" * 78)
    print(f"  {'cell':9s} {'pass%':>6s} {'n hi':>7s} {'n lo':>7s} {'diff':>9s} {'se':>7s}"
          f" {'t':>7s} {'excess':>9s}  flags")
    for code, _, _ in LAYERS:
        for name in HORIZONS:
            r = tests[f"{code}@{name}"]
            hd = r["headline_pass_vs_fail"]
            if not hd:
                print(f"  {code}@{name:4s}  NOT COMPUTABLE")
                continue
            fl = ",".join(f for f in r["flags"] if not f.startswith("HIGH_OVERLAP")) or "-"
            print(f"  {code}@{name:4s} {r['pass_rate_pct']:6.2f} {hd['n_hi']:7,} {hd['n_lo']:7,}"
                  f" {hd['diff']:+9.4f} {hd['se']:7.4f} {hd['t']:+7.2f}"
                  f" {r['excess_over_bias_only']:+9.4f}  {fl}")

    print()
    print("=" * 78)
    print("BOOTSTRAP CONTROL -- cross-group dependence not assumed away")
    print("  blocks of 96 and 480 M15 bars, 4,000 replicates, ALL observations")
    print("=" * 78)
    hdr = ("  cell      analytic t   boot t (96)  boot t (480)"
           "    se ana    se 96   se 480")
    print(hdr)
    for code, _, _ in LAYERS:
        for name in HORIZONS:
            r = tests[f"{code}@{name}"]
            hd = r["headline_pass_vs_fail"]
            bc = results["bootstrap_control"]["cells"][f"{code}@{name}"]
            b96, b480 = bc["block_96"], bc["block_480"]
            at = f"{hd['t']:+.2f}" if hd else "n/a"
            ase = f"{hd['se']:.4f}" if hd else "n/a"
            t96 = f"{b96['t']:+.2f}" if b96.get("t") is not None else "n/a"
            t480 = f"{b480['t']:+.2f}" if b480.get("t") is not None else "n/a"
            s96 = f"{b96['se']:.4f}" if b96.get("se") else "n/a"
            s480 = f"{b480['se']:.4f}" if b480.get("se") else "n/a"
            print(f"  {code}@{name:4s} {at:>11s} {t96:>13s} {t480:>13s}"
                  f" {ase:>9s} {s96:>8s} {s480:>8s}")
    print()
    print("\n" + "=" * 78)
    print("MULTIPLE TESTING")
    print("=" * 78)
    print(f"  declared hypotheses          : {mt['n_declared']}")
    print(f"  with computable t            : {mt['n_with_computable_t']}")
    print(f"  Bonferroni threshold |t|     : {mt['bonferroni_threshold_t']:.3f}")
    print(f"  Bonferroni survivors         : {len(mt['survivors_bonferroni'])}  {mt['survivors_bonferroni']}")
    bh = mt.get("benjamini_hochberg") or {}
    print(f"  Benjamini-Hochberg survivors : {bh.get('n_survivors', bh.get('survivors', 'n/a'))}")
    print(f"  max |t|                      : {mt['max_abs_t']:.3f}  ({mt['max_abs_t_cell']})")
    print(f"  observed |t| >= 2            : {mt['observed_abs_t_ge_2']}")
    print(f"  expected |t| >= 2 under null : {mt['expected_abs_t_ge_2_under_null']}")

    print("\n" + "=" * 78)
    print("CONTROLS")
    print("=" * 78)
    print(f"  panel window                 : {controls['panel_time_min']} .. {controls['panel_time_max']}")
    print(f"  ESTIMATOR_SIGN_DISAGREEMENT  : {len(controls['sign_disagreement_cells'])} cells")
    print(f"  cells carrying any flag      : {len(controls['cells_needing_review'])} / {len(controls['cells'])}")
    for name, p in controls["power"].items():
        print(f"  power {name:3s}: median se {p['median_se']:.4f}"
              f"  MDE(2se) {p['mde_2se_atr']:.3f} ATR  MDE(Bonferroni) {p['mde_bonferroni_atr']:.3f} ATR")
    print(f"  round-turn cost in ATR units : {results['cost_reference']['round_turn_in_atr_units']}")
    f = results["baseline_008_forensics"]
    print("\n" + "=" * 78)
    print("BASELINE_008 FOUR-TRADE TRACE -- FORENSIC / DESCRIPTIVE ONLY (n=4)")
    print("=" * 78)
    for tr in f["trades"]:
        print(f"  {tr['decision_bar_time'][:16]} {tr['side']:4s} {tr['regime']:12s}"
              f" {tr['entry_method']:9s} grade {str(tr['grade']):3s}"
              f" ledger_conf {tr['ledger_confidence_field']:.1f}"
              f"  {tr['exit_reason']:6s} R {tr['r_multiple']:+.2f}")
    cc = f["common_to_all_four"]
    print(f"  identical layer path across all four : {cc['layers_passed_identical']}")
    print(f"  L3 bypassed: {cc['L3_bypassed']}   L6 bypassed: {cc['L6_bypassed']}")
    print(f"  path actually evaluated             : {cc['layers_passed']}")

    print(f"\n  wrote {out_dir/'production_path_audit_results.json'}")
    print(f"  wrote {out_dir/'production_path_audit_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", default=str(Path(__file__).parent))
    a = ap.parse_args()
    run(Path(a.panel), Path(a.out))
