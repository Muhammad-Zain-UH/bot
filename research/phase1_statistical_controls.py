"""Standing statistical guardrails for conditional research.

Written after an estimator failure that produced a spurious t = -14.6 and survived
seven artifact controls before being caught in Phase 2. The failure was NOT a bad
hypothesis -- it was an unweighted mean of per-block means applied to 16x
overlapping observations. These utilities make that class of error loud.

The rules, enforced here rather than remembered:

  * The HEADLINE estimator is always NON-OVERLAPPING. Block statistics are
    secondary diagnostics and are never returned without their weighting label.
  * Raw conditional statistics are always computed and carried alongside.
  * If sign(block) != sign(raw), the result carries ESTIMATOR_SIGN_DISAGREEMENT
    and `needs_review = True`.
  * Every forward-looking result reports raw n, non-overlapping n, and the ratio.
  * A forward-window audit proves the headline sample has disjoint label windows.
  * Multiple testing is reported with the hypothesis count, nominal alpha,
    expected null exceedances, and a documented correction -- never as a bare
    count of |t| > 2.

Run `python research/phase1_statistical_controls.py` to execute the self-tests,
which include the two fixtures the research standard requires: a deliberate
estimator-sign-disagreement, and an overlapping-label fixture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

__all__ = [
    "Weighting", "ConditionalStat", "raw_stats", "non_overlapping_indices",
    "forward_window_audit", "block_stats", "conditional_stat", "contrast",
    "multiple_testing_report", "bonferroni_t", "benjamini_hochberg",
]


class Weighting:
    """Aggregation weighting. Never report an aggregate without one of these."""
    OBSERVATION = "observation-weighted"
    EQUAL_BLOCK = "equal-block-weighted"
    NON_OVERLAPPING = "non-overlapping (observation-weighted, disjoint windows)"
    OVERLAPPING = "overlapping (observation-weighted, windows share bars)"


def _norm_sf2(z: float) -> float:
    """Two-sided normal tail. math only -- scipy is not installed here."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def bonferroni_t(n_tests: int, alpha: float = 0.05) -> float:
    """Smallest |t| whose two-sided p <= alpha / n_tests."""
    target = alpha / max(n_tests, 1)
    lo, hi = 0.0, 12.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _norm_sf2(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> dict:
    """BH FDR. Returns the threshold and which hypotheses survive."""
    p = np.asarray(pvals, float)
    m = len(p)
    if m == 0:
        return {"threshold_p": None, "n_survivors": 0, "survivor_idx": []}
    order = np.argsort(p)
    ranked = p[order]
    crit = alpha * (np.arange(1, m + 1) / m)
    passing = np.flatnonzero(ranked <= crit)
    if len(passing) == 0:
        return {"threshold_p": None, "n_survivors": 0, "survivor_idx": []}
    k = passing[-1]
    thr = float(ranked[k])
    surv = [int(i) for i in order[: k + 1]]
    return {"threshold_p": thr, "n_survivors": len(surv), "survivor_idx": sorted(surv)}


def raw_stats(y: np.ndarray) -> dict:
    """Raw conditional statistics. Computed BEFORE any aggregation, always."""
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    n = len(y)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "sd": None, "se": None}
    sd = float(y.std(ddof=1)) if n > 1 else float("nan")
    return {"n": int(n), "mean": float(y.mean()), "median": float(np.median(y)),
            "sd": sd, "se": (sd / math.sqrt(n) if n > 1 else float("nan"))}


def non_overlapping_indices(idx: np.ndarray, horizon_bars: int) -> np.ndarray:
    """Greedy forward scan: accept an index, then skip the full label window.

    Deterministic, and the resulting sample has provably disjoint forward windows
    (see `forward_window_audit`).
    """
    idx = np.asarray(idx, dtype=np.int64)
    idx = np.sort(idx)
    keep: list[int] = []
    last = -(10 ** 18)
    for i in idx:
        if i - last >= horizon_bars:
            keep.append(int(i))
            last = int(i)
    return np.array(keep, dtype=np.int64)


def forward_window_audit(idx: np.ndarray, horizon_bars: int) -> dict:
    """Prove the sample's label windows do not overlap.

    Observation i owns the half-open bar range (i, i + horizon_bars].
    """
    idx = np.sort(np.asarray(idx, dtype=np.int64))
    if len(idx) < 2:
        return {"n": int(len(idx)), "disjoint": True, "min_gap": None, "n_overlaps": 0}
    gaps = np.diff(idx)
    bad = int((gaps < horizon_bars).sum())
    return {"n": int(len(idx)), "disjoint": bool(bad == 0),
            "min_gap": int(gaps.min()), "required_gap": int(horizon_bars),
            "n_overlaps": bad}


def block_stats(y: np.ndarray, pos: np.ndarray, block_bars: int) -> dict:
    """SECONDARY diagnostic only. Equal-block-weighted by construction.

    Never use as a headline. The weighting label is attached so it cannot be
    reported without it.
    """
    y = np.asarray(y, float)
    pos = np.asarray(pos, np.int64)
    ok = np.isfinite(y)
    y, pos = y[ok], pos[ok]
    if len(y) == 0:
        return {"weighting": Weighting.EQUAL_BLOCK, "n_blocks": 0, "mean": None,
                "se": None, "t": None}
    bm = pd.DataFrame({"b": pos // block_bars, "v": y}).groupby("b")["v"].mean().to_numpy()
    if len(bm) < 2:
        return {"weighting": Weighting.EQUAL_BLOCK, "n_blocks": int(len(bm)),
                "mean": float(bm.mean()), "se": None, "t": None}
    se = float(bm.std(ddof=1) / math.sqrt(len(bm)))
    m = float(bm.mean())
    return {"weighting": Weighting.EQUAL_BLOCK, "n_blocks": int(len(bm)),
            "mean": m, "se": se, "t": (m / se if se > 0 else None),
            "obs_per_block_mean": float(len(y) / len(bm))}


@dataclass
class ConditionalStat:
    """One conditional cell, with every required disclosure attached."""
    label: str
    horizon_bars: int
    raw: dict
    headline: dict                      # non-overlapping -- the number that counts
    block: dict                         # secondary diagnostic
    overlap: dict
    audit: dict
    flags: list = field(default_factory=list)
    needs_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def conditional_stat(y: np.ndarray, mask: np.ndarray, horizon_bars: int,
                     label: str = "") -> ConditionalStat:
    """Full disclosure for one conditional subset.

    `headline` is the NON-OVERLAPPING estimate. `block` is carried only as a
    diagnostic and triggers ESTIMATOR_SIGN_DISAGREEMENT when it disagrees in sign.
    """
    y = np.asarray(y, float)
    mask = np.asarray(mask, bool) & np.isfinite(y)
    idx = np.flatnonzero(mask)
    raw = raw_stats(y[idx])

    keep = non_overlapping_indices(idx, horizon_bars)
    hs = raw_stats(y[keep])
    headline = {"weighting": Weighting.NON_OVERLAPPING, **hs}
    if hs["n"] > 1 and hs["se"] == hs["se"]:
        headline["t"] = hs["mean"] / hs["se"] if hs["se"] > 0 else None
        headline["ci95"] = [hs["mean"] - 1.96 * hs["se"], hs["mean"] + 1.96 * hs["se"]]
    else:
        headline["t"] = None
        headline["ci95"] = [None, None]

    blk = block_stats(y[idx], idx, horizon_bars)
    overlap = {"raw_observations": int(len(idx)),
               "non_overlapping_observations": int(len(keep)),
               "overlap_ratio": (round(len(idx) / len(keep), 3) if len(keep) else None),
               "raw_weighting": Weighting.OVERLAPPING}
    audit = forward_window_audit(keep, horizon_bars)

    flags: list[str] = []
    if not audit["disjoint"]:
        flags.append("FORWARD_WINDOW_OVERLAP_IN_HEADLINE")
    rm, bm = raw.get("mean"), blk.get("mean")
    if rm is not None and bm is not None and rm != 0 and bm != 0:
        if math.copysign(1, rm) != math.copysign(1, bm):
            flags.append("ESTIMATOR_SIGN_DISAGREEMENT")
    if overlap["overlap_ratio"] and overlap["overlap_ratio"] > 2.0:
        flags.append(f"HIGH_OVERLAP_{overlap['overlap_ratio']}x")
    return ConditionalStat(label=label, horizon_bars=horizon_bars, raw=raw,
                           headline=headline, block=blk, overlap=overlap,
                           audit=audit, flags=flags,
                           needs_review="ESTIMATOR_SIGN_DISAGREEMENT" in flags
                           or not audit["disjoint"])


def contrast(y: np.ndarray, mask_hi: np.ndarray, mask_lo: np.ndarray,
             horizon_bars: int, label: str = "") -> dict:
    """Difference of two conditional cells, headline on non-overlapping samples."""
    a = conditional_stat(y, mask_hi, horizon_bars, f"{label}:hi")
    b = conditional_stat(y, mask_lo, horizon_bars, f"{label}:lo")
    out = {"label": label, "hi": a.to_dict(), "lo": b.to_dict(), "flags": []}
    ah, bh = a.headline, b.headline
    if ah["n"] > 1 and bh["n"] > 1 and ah["se"] == ah["se"] and bh["se"] == bh["se"]:
        d = ah["mean"] - bh["mean"]
        se = math.sqrt(ah["se"] ** 2 + bh["se"] ** 2)
        t = d / se if se > 0 else None
        out["headline_diff"] = {
            "weighting": Weighting.NON_OVERLAPPING, "diff": d, "se": se, "t": t,
            "ci95": [d - 1.96 * se, d + 1.96 * se],
            "p_two_sided": (_norm_sf2(t) if t is not None else None),
            "n_hi": ah["n"], "n_lo": bh["n"]}
    else:
        out["headline_diff"] = None
    # secondary, explicitly labelled
    ab, bb = a.block, b.block
    if ab.get("se") and bb.get("se"):
        db = ab["mean"] - bb["mean"]
        seb = math.sqrt(ab["se"] ** 2 + bb["se"] ** 2)
        out["block_diff_SECONDARY"] = {
            "weighting": Weighting.EQUAL_BLOCK, "diff": db, "se": seb,
            "t": (db / seb if seb > 0 else None),
            "warning": "equal-block-weighted; NOT a headline estimator"}
        rd = (a.raw["mean"] - b.raw["mean"]) if (a.raw["mean"] is not None
                                                and b.raw["mean"] is not None) else None
        if rd is not None and rd != 0 and db != 0 and \
                math.copysign(1, rd) != math.copysign(1, db):
            out["flags"].append("ESTIMATOR_SIGN_DISAGREEMENT")
        out["raw_diff_OVERLAPPING"] = {"weighting": Weighting.OVERLAPPING, "diff": rd}
    out["flags"] += [f for f in a.flags + b.flags if f not in out["flags"]]
    out["needs_review"] = bool(out["flags"])
    return out


def multiple_testing_report(t_values: list[float], alpha: float = 0.05,
                            method: str = "bonferroni+BH") -> dict:
    """Hypothesis count, expected null exceedances, and documented corrections."""
    ts = [t for t in t_values if t is not None and np.isfinite(t)]
    m = len(ts)
    pv = [_norm_sf2(t) for t in ts]
    bonf_t = bonferroni_t(m, alpha) if m else None
    bh = benjamini_hochberg(pv, alpha)
    return {
        "n_hypotheses": m, "nominal_alpha": alpha, "correction_method": method,
        "expected_false_positives_at_alpha": round(m * alpha, 2),
        "expected_abs_t_ge_2_under_null": round(m * _norm_sf2(2.0), 2),
        "observed_abs_t_ge_2": int(sum(abs(t) >= 2 for t in ts)),
        "expected_abs_t_ge_3_under_null": round(m * _norm_sf2(3.0), 2),
        "observed_abs_t_ge_3": int(sum(abs(t) >= 3 for t in ts)),
        "bonferroni_threshold_abs_t": (round(bonf_t, 3) if bonf_t else None),
        "bonferroni_survivors": (int(sum(abs(t) >= bonf_t for t in ts)) if bonf_t else 0),
        "benjamini_hochberg": bh,
        "max_abs_t": (float(max(abs(t) for t in ts)) if ts else None),
        "note": ("a bare count of |t| > 2 is NOT evidence; compare observed against "
                 "expected and use a corrected threshold"),
    }


# ============================================================ self-tests
def _selftest() -> int:
    rng = np.random.default_rng(7)
    failures = 0

    def check(name, cond):
        nonlocal failures
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures += 1

    print("FIXTURE 1 -- estimator sign disagreement must be CAUGHT")
    # Construct it exactly as the real failure arose: block membership correlated
    # with outcome, so equal-block weighting flips the sign of the raw mean.
    n, h = 4000, 16
    y = np.full(n, np.nan)
    mask = np.zeros(n, bool)
    for b in range(n // h):
        s = b * h
        if b % 2 == 0:
            # dense block, mildly positive -> dominates the OBSERVATION mean
            sel = np.arange(s, s + 12)
            vals = rng.normal(+0.5, 0.05, len(sel))
        else:
            # sparse block, strongly negative -> dominates the EQUAL-BLOCK mean.
            # 12 x (+0.5) + 1 x (-4.0) = +2 over 13 obs  -> raw mean POSITIVE
            # mean(+0.5, -4.0) = -1.75 over 2 blocks      -> block mean NEGATIVE
            sel = np.arange(s, s + 1)
            vals = rng.normal(-4.0, 0.05, len(sel))
        y[sel] = vals
        mask[sel] = True
    cs = conditional_stat(y, mask, h, "fixture_sign")
    print(f"    raw mean   {cs.raw['mean']:+.4f}  (observation-weighted, overlapping)")
    print(f"    block mean {cs.block['mean']:+.4f}  ({cs.block['weighting']})")
    print(f"    flags      {cs.flags}")
    check("raw and block means have opposite signs",
          math.copysign(1, cs.raw["mean"]) != math.copysign(1, cs.block["mean"]))
    check("ESTIMATOR_SIGN_DISAGREEMENT raised", "ESTIMATOR_SIGN_DISAGREEMENT" in cs.flags)
    check("needs_review set", cs.needs_review is True)

    print("\nFIXTURE 2 -- overlapping labels: raw and non-overlapping counts must differ")
    n, h = 1000, 16
    y2 = rng.normal(0, 1, n)
    mask2 = np.zeros(n, bool)
    mask2[100:900] = True                      # 800 contiguous -> heavy overlap
    cs2 = conditional_stat(y2, mask2, h, "fixture_overlap")
    print(f"    raw n {cs2.overlap['raw_observations']}  "
          f"non-overlapping n {cs2.overlap['non_overlapping_observations']}  "
          f"ratio {cs2.overlap['overlap_ratio']}x")
    check("raw count is 800", cs2.overlap["raw_observations"] == 800)
    check("non-overlapping count is 50 (800/16)",
          cs2.overlap["non_overlapping_observations"] == 50)
    check("ratio is 16x", abs(cs2.overlap["overlap_ratio"] - 16.0) < 1e-9)
    check("HIGH_OVERLAP flagged", any(f.startswith("HIGH_OVERLAP") for f in cs2.flags))

    print("\nFIXTURE 3 -- forward-window audit proves disjointness")
    check("headline sample is disjoint", cs2.audit["disjoint"] is True)
    check("min gap >= horizon", cs2.audit["min_gap"] >= h)
    bad = forward_window_audit(np.arange(0, 100, 4), 16)
    check("audit detects overlap when gap < horizon", bad["disjoint"] is False)

    print("\nFIXTURE 4 -- non_overlapping_indices is deterministic and correct")
    k = non_overlapping_indices(np.arange(0, 64), 16)
    check("picks 0,16,32,48", list(k) == [0, 16, 32, 48])
    check("idempotent", list(non_overlapping_indices(k, 16)) == list(k))

    print("\nFIXTURE 5 -- multiple-testing arithmetic")
    mt = multiple_testing_report([0.1] * 95 + [2.5, 2.6, 3.1, 4.0, 5.0], alpha=0.05)
    print(f"    hypotheses {mt['n_hypotheses']}  bonferroni |t| >= "
          f"{mt['bonferroni_threshold_abs_t']}  survivors {mt['bonferroni_survivors']}")
    check("100 hypotheses counted", mt["n_hypotheses"] == 100)
    check("expected |t|>=2 under null ~4.55",
          abs(mt["expected_abs_t_ge_2_under_null"] - 4.55) < 0.1)
    check("bonferroni threshold near 3.48",
          abs(mt["bonferroni_threshold_abs_t"] - 3.483) < 0.02)
    check("BH returns a dict", isinstance(mt["benjamini_hochberg"], dict))

    print("\nFIXTURE 6 -- block stats always carry a weighting label")
    bs = block_stats(np.array([1.0, 2.0, 3.0, 4.0]), np.array([0, 1, 16, 17]), 16)
    check("weighting disclosed", bs["weighting"] == Weighting.EQUAL_BLOCK)

    print(f"\n{'ALL SELF-TESTS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(_selftest())
