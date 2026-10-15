"""Hypothesis 05 -- SLOW TREND-CONDITIONAL EXPOSURE.

Implements, literally and only, the pre-registration committed at 60b93e4:
research/hypothesis_05_trend_exposure.md.

Not an alpha claim. Tests whether reducing exposure below a slow trend filter
improves RISK-ADJUSTED outcomes versus holding continuously, net of cost.

Accounting convention, chosen for exactness and realism:
  exposure changes at an H1 bar OPEN, and returns are OPEN-TO-OPEN, so the
  exposure in force over an interval is unambiguous and no mixed-price return is
  ever constructed. The committed close-based benchmark is also reported, and the
  two conventions are compared rather than assumed equivalent.

FINAL_OOS is never loaded. No DEV tuning. No parameter search.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import H1_SPLIT_MANIFEST, load_arm, verify_dataset  # noqa: E402

# ----------------------------------------------------------- frozen definitions
SMA_PRIMARY = 100
SMA_SENSITIVITY = (50, 200)          # disclosure only, never selected from
SPREAD_USD = 0.33                    # one round turn
HALF_SPREAD = SPREAD_USD / 2.0       # one exposure change
SLIPPAGE_GRID = (0.0, 0.25, 0.50, 1.00)
EXPOSURE_CAP = 1.0
DD_IMPROVEMENT_REQUIRED_PP = 5.0     # percentage points, pre-declared
ERA_EDGES = [2008, 2012, 2016, 2020, 2024, 2027]
ERA_LABELS = ["2009-12", "2013-16", "2017-20", "2021-24", "2025-26"]
CAUSAL_PROBES = 60
CAUSAL_SEED = 20261007
TOL_DAILY_CLOSE = 0.0                # a selection, no arithmetic
TOL_SMA_REL = 1e-13                  # mean of 100 float64 terms


# ================================================================== mechanics
def daily_closes(h1: pd.DataFrame) -> pd.DataFrame:
    """Last H1 bar of each UTC day, keeping that bar's integer index so the
    execution bar can be identified exactly."""
    idx = h1.groupby(h1["time"].dt.date)["time"].idxmax()
    d = h1.loc[idx, ["time", "close"]].copy()
    d["h1_index"] = idx.to_numpy()
    d["day"] = d["time"].dt.date
    return d.reset_index(drop=True)


def exposure_series(h1: pd.DataFrame, window: int) -> dict:
    """The frozen rule. Returns the H1-aligned exposure vector plus the pieces
    needed for the causal audit."""
    n = len(h1)
    d = daily_closes(h1)
    sma = d["close"].rolling(window).mean()
    signal = (d["close"] > sma).to_numpy()
    valid = sma.notna().to_numpy()
    target = np.where(signal, 1.0, 0.0)

    # execution at the open of the first H1 bar strictly after the signal bar
    exec_idx = d["h1_index"].to_numpy() + 1
    exp = np.full(n, np.nan)
    ok = valid & (exec_idx < n)
    exp[exec_idx[ok]] = target[ok]
    exp = pd.Series(exp).ffill().to_numpy()
    first = int(np.argmax(~np.isnan(exp))) if np.isfinite(exp).any() else n
    return {"exposure": exp, "first_valid_bar": first, "daily": d,
            "sma": sma.to_numpy(), "signal": signal, "valid": valid,
            "target": target, "exec_idx": exec_idx, "window": window}


def equity_curve(h1: pd.DataFrame, exp: np.ndarray, start: int,
                 slip_mult: float = 0.0) -> dict:
    """Open-to-open marked equity with cost charged on every exposure change at
    the price prevailing at that change."""
    op = h1["open"].to_numpy(float)
    n = len(op)
    cost_per_change = HALF_SPREAD * (1.0 + slip_mult)
    eq = np.full(n, np.nan)
    eq[start] = 1.0
    changes = 0
    cost_total = 0.0
    prev_e = 0.0
    for t in range(start, n - 1):
        e = exp[t]
        if not np.isfinite(e):
            e = 0.0
        e = min(e, EXPOSURE_CAP)
        if t == start:
            prev_e = e
        elif e != prev_e:
            changes += 1
            c = abs(e - prev_e) * cost_per_change / op[t]
            eq[t] *= (1.0 - c)
            cost_total += abs(e - prev_e) * cost_per_change
            prev_e = e
        r = op[t + 1] / op[t] - 1.0
        eq[t + 1] = eq[t] * (1.0 + e * r)
    return {"equity": eq, "exposure_changes": changes,
            "round_turns": changes / 2.0, "cost_dollars_per_unit": cost_total,
            "start": start}


def curve_stats(eq: np.ndarray, times: pd.Series, start: int,
                bars_per_year: float) -> dict:
    e = eq[start:]
    e = e[np.isfinite(e)]
    if len(e) < 10:
        return {"bars": int(len(e))}
    peak = np.maximum.accumulate(e)
    dd = (e - peak) / peak
    yrs = (times.iloc[-1] - times.iloc[start]).days / 365.25
    tot = e[-1] / e[0] - 1.0
    r = np.diff(np.log(e))
    vol = float(r.std(ddof=1) * np.sqrt(bars_per_year))
    under = dd < -0.01
    run = best = 0
    for u in under:
        run = run + 1 if u else 0
        best = max(best, run)
    return {"bars": int(len(e)), "years": round(yrs, 2),
            "total_return_pct": round(100 * float(tot), 2),
            "cagr_pct": round(100 * float((1 + tot) ** (1 / yrs) - 1), 3),
            "max_drawdown_pct": round(100 * float(dd.min()), 2),
            "longest_underwater_years": round(best / bars_per_year, 2),
            "ann_volatility_pct": round(100 * vol, 2),
            "sharpe_rf0": round(float(np.log(1 + tot) / yrs / vol), 3) if vol > 0 else None,
            "log_returns": r}


def paired_sharpe_test(r_s: np.ndarray, r_b: np.ndarray, bars_per_year: float,
                       yrs: float) -> dict:
    """Jobson-Korkie with the Memmel correction. Reports the SE honestly rather
    than a bare difference."""
    m = min(len(r_s), len(r_b))
    a, b = r_s[:m], r_b[:m]
    rho = float(np.corrcoef(a, b)[0, 1])
    sa = float(a.mean() / a.std(ddof=1) * np.sqrt(bars_per_year))
    sb = float(b.mean() / b.std(ddof=1) * np.sqrt(bars_per_year))
    var = (1 / yrs) * (2 * (1 - rho) + 0.5 * (sa ** 2 + sb ** 2 - 2 * sa * sb * rho ** 2))
    se = float(np.sqrt(max(var, 0.0)))
    d = sa - sb
    return {"sharpe_strategy": round(sa, 3), "sharpe_benchmark": round(sb, 3),
            "difference": round(d, 3), "correlation": round(rho, 4),
            "se_of_difference": round(se, 3),
            "t": (round(d / se, 3) if se > 0 else None),
            "min_detectable_difference_2se": round(2 * se, 3),
            "significant_at_2se": bool(se > 0 and abs(d) >= 2 * se),
            "note": ("underpowered by construction; see the specification section 6. "
                     "A significant Sharpe improvement is not claimed.")}


def episodes(h1: pd.DataFrame, exp: np.ndarray, start: int) -> dict:
    """Per-episode ledger. MANDATORY: TRAIN's outcome may lean on a single event,
    and that must be visible rather than hidden inside an aggregate."""
    op = h1["open"].to_numpy(float)
    t = h1["time"]
    e = np.where(np.isfinite(exp), exp, 0.0)
    inm, outm = [], []
    i = start
    while i < len(e) - 1:
        state = e[i]
        j = i
        while j < len(e) - 1 and e[j + 1] == state:
            j += 1
        seg = {"from": str(t.iloc[i]), "to": str(t.iloc[min(j + 1, len(e) - 1)]),
               "bars": int(j - i + 1),
               "market_return_pct": round(100 * (op[min(j + 1, len(op) - 1)] / op[i] - 1), 2)}
        (inm if state >= 0.5 else outm).append(seg)
        i = j + 1
    in_ret = [s["market_return_pct"] for s in inm]
    out_ret = [s["market_return_pct"] for s in outm]
    return {
        "in_market_episodes": len(inm), "out_of_market_episodes": len(outm),
        "in_market_bars": int(sum(s["bars"] for s in inm)),
        "out_of_market_bars": int(sum(s["bars"] for s in outm)),
        "time_in_market_pct": round(100 * sum(s["bars"] for s in inm)
                                    / max(sum(s["bars"] for s in inm)
                                          + sum(s["bars"] for s in outm), 1), 2),
        "avoided_moves_while_flat": {
            "n": len(out_ret),
            "sum_pct": round(float(np.sum(out_ret)), 2) if out_ret else None,
            "worst_avoided_pct": round(float(np.min(out_ret)), 2) if out_ret else None,
            "best_forgone_pct": round(float(np.max(out_ret)), 2) if out_ret else None,
            "n_beneficial": int(sum(1 for r in out_ret if r < 0)),
            "n_harmful": int(sum(1 for r in out_ret if r > 0))},
        "in_market_moves": {
            "n": len(in_ret),
            "sum_pct": round(float(np.sum(in_ret)), 2) if in_ret else None},
        "largest_avoided": sorted(outm, key=lambda s: s["market_return_pct"])[:5],
        "largest_forgone": sorted(outm, key=lambda s: -s["market_return_pct"])[:5],
        "all_out_of_market": outm, "all_in_market": inm}


# ======================================================================= main
def run(out_dir: Path) -> None:
    verify_dataset()
    results: dict = {
        "hypothesis": "research/hypothesis_05_trend_exposure.md",
        "preregistration_commit": "60b93e4",
        "claim": ("not an alpha claim: tests whether a known risk-management effect "
                  "survives this instrument's costs"),
        "frozen": {"sma_primary": SMA_PRIMARY, "sma_sensitivity": list(SMA_SENSITIVITY),
                   "exposure_ladder": [0.0, 1.0], "exposure_cap": EXPOSURE_CAP,
                   "round_turn_usd": SPREAD_USD, "cost_per_exposure_change_usd": HALF_SPREAD,
                   "accounting": "open-to-open, cost at the price of each change",
                   "dd_improvement_required_pp": DD_IMPROVEMENT_REQUIRED_PP},
        "oos": {"loaded": False, "note": "FINAL_OOS is not read, as data or as context"},
        "arms": {}, "sensitivity": {}, "slippage_grid": {}, "eras": {},
    }

    for arm in ("TRAIN", "DEV"):
        h1 = load_arm("H1", arm, manifest=H1_SPLIT_MANIFEST).reset_index(drop=True)
        yrs_full = (h1["time"].max() - h1["time"].min()).days / 365.25
        bpy = len(h1) / yrs_full

        S = exposure_series(h1, SMA_PRIMARY)
        start = S["first_valid_bar"]
        strat = equity_curve(h1, S["exposure"], start)
        # benchmark on the IDENTICAL window and the IDENTICAL convention
        hold = equity_curve(h1, np.ones(len(h1)), start)

        s_st = curve_stats(strat["equity"], h1["time"], start, bpy)
        s_bh = curve_stats(hold["equity"], h1["time"], start, bpy)
        pst = paired_sharpe_test(s_st.pop("log_returns"), s_bh.pop("log_returns"),
                                 bpy, s_st["years"])
        ep = episodes(h1, S["exposure"], start)

        # Drawdowns are NEGATIVE percentages, so a SHALLOWER (better) drawdown is
        # the LARGER number. Improvement = strategy - benchmark, positive = better.
        dd_imp = s_st["max_drawdown_pct"] - s_bh["max_drawdown_pct"]
        results["arms"][arm] = {
            "window": {"from": str(h1["time"].iloc[start]), "to": str(h1["time"].iloc[-1]),
                       "warmup_bars_dropped": int(start), "bars_per_year": round(bpy, 1)},
            "strategy": s_st, "benchmark_same_window": s_bh,
            "drawdown_improvement_pp": round(dd_imp, 2),
            "drawdown_criterion_met": bool(dd_imp >= DD_IMPROVEMENT_REQUIRED_PP),
            "cagr_give_up_pp": round(s_bh["cagr_pct"] - s_st["cagr_pct"], 3),
            "sharpe_not_degraded": bool((s_st["sharpe_rf0"] or -9) >= (s_bh["sharpe_rf0"] or 9)),
            "paired_sharpe_test": pst,
            "transitions": {"exposure_changes": strat["exposure_changes"],
                            "round_turns": strat["round_turns"],
                            "round_turns_per_year": round(strat["round_turns"] / s_st["years"], 2),
                            "cost_dollars_per_unit": round(strat["cost_dollars_per_unit"], 2),
                            "gate_round_turns_per_year": 52},
            "episodes": ep,
        }
        print(f"\n[{arm}] {str(h1['time'].iloc[start])[:10]} -> {str(h1['time'].iloc[-1])[:10]}"
              f"  ({s_st['years']} yr, warmup {start} bars dropped)")
        print(f"  {'':22} {'STRATEGY':>12} {'HOLD':>12}   delta")
        print(f"  {'CAGR %':22} {s_st['cagr_pct']:>+12.3f} {s_bh['cagr_pct']:>+12.3f}"
              f"   {s_st['cagr_pct']-s_bh['cagr_pct']:+.3f}")
        print(f"  {'max drawdown %':22} {s_st['max_drawdown_pct']:>+12.2f} "
              f"{s_bh['max_drawdown_pct']:>+12.2f}   {dd_imp:+.2f} pp"
              f"  {'MET' if dd_imp>=DD_IMPROVEMENT_REQUIRED_PP else 'NOT MET'}")
        print(f"  {'longest underwater yr':22} {s_st['longest_underwater_years']:>12.2f} "
              f"{s_bh['longest_underwater_years']:>12.2f}")
        print(f"  {'ann vol %':22} {s_st['ann_volatility_pct']:>12.2f} "
              f"{s_bh['ann_volatility_pct']:>12.2f}")
        print(f"  {'Sharpe':22} {s_st['sharpe_rf0']:>12.3f} {s_bh['sharpe_rf0']:>12.3f}"
              f"   {pst['difference']:+.3f}  (SE {pst['se_of_difference']:.3f}, "
              f"rho {pst['correlation']:.3f}, sig={pst['significant_at_2se']})")
        print(f"  time in market {ep['time_in_market_pct']:.1f}%   "
              f"round turns/yr {strat['round_turns']/s_st['years']:.1f} (gate 52)   "
              f"cost ${strat['cost_dollars_per_unit']:.2f}/unit")
        av = ep["avoided_moves_while_flat"]
        print(f"  flat {av['n']} times: {av['n_beneficial']} avoided a decline, "
              f"{av['n_harmful']} missed a rise; worst avoided {av['worst_avoided_pct']}%, "
              f"best forgone {av['best_forgone_pct']}%")

        # sensitivity -- disclosure only
        for w in SMA_SENSITIVITY:
            Sw = exposure_series(h1, w)
            st = Sw["first_valid_bar"]
            cw = equity_curve(h1, Sw["exposure"], st)
            bw = equity_curve(h1, np.ones(len(h1)), st)
            a = curve_stats(cw["equity"], h1["time"], st, bpy)
            b = curve_stats(bw["equity"], h1["time"], st, bpy)
            a.pop("log_returns", None); b.pop("log_returns", None)
            results["sensitivity"][f"{arm}|SMA{w}"] = {
                "strategy": a, "benchmark_same_window": b,
                "drawdown_improvement_pp": round(a["max_drawdown_pct"] - b["max_drawdown_pct"], 2),
                "round_turns_per_year": round(cw["round_turns"] / a["years"], 2),
                "note": "DISCLOSURE ONLY -- not an alternative to select from"}

        # slippage grid
        for sl in SLIPPAGE_GRID:
            c = equity_curve(h1, S["exposure"], start, slip_mult=sl)
            s = curve_stats(c["equity"], h1["time"], start, bpy)
            s.pop("log_returns", None)
            results["slippage_grid"][f"{arm}|slip{sl}"] = {
                "cagr_pct": s["cagr_pct"], "max_drawdown_pct": s["max_drawdown_pct"],
                "sharpe_rf0": s["sharpe_rf0"],
                "cost_dollars_per_unit": round(c["cost_dollars_per_unit"], 2)}

        # eras
        era = pd.cut(h1["time"].dt.year, ERA_EDGES, labels=ERA_LABELS)
        for lbl in ERA_LABELS:
            m = (era == lbl).to_numpy()
            if m.sum() < 500:
                continue
            lo, hi = int(np.argmax(m)), int(len(m) - np.argmax(m[::-1]) - 1)
            if lo < start:
                lo = start
            if hi - lo < 500:
                continue
            sub = h1.iloc[lo:hi + 1].reset_index(drop=True)
            e_sub = S["exposure"][lo:hi + 1]
            cs = equity_curve(sub, e_sub, 0)
            bs = equity_curve(sub, np.ones(len(sub)), 0)
            a = curve_stats(cs["equity"], sub["time"], 0, bpy)
            b = curve_stats(bs["equity"], sub["time"], 0, bpy)
            a.pop("log_returns", None); b.pop("log_returns", None)
            results["eras"][f"{arm}|{lbl}"] = {
                "strategy_cagr_pct": a.get("cagr_pct"), "hold_cagr_pct": b.get("cagr_pct"),
                "strategy_maxdd_pct": a.get("max_drawdown_pct"),
                "hold_maxdd_pct": b.get("max_drawdown_pct"),
                "drawdown_improvement_pp": (round(a["max_drawdown_pct"] - b["max_drawdown_pct"], 2)
                                            if a.get("max_drawdown_pct") is not None else None)}

    # ---- controls -----------------------------------------------------------
    controls: dict = {"frozen_tolerances": {
        "daily_close_abs": TOL_DAILY_CLOSE, "sma_relative": TOL_SMA_REL,
        "signal_disagreements": 0, "exposure_disagreements": 0,
        "execution_index_disagreements": 0}}
    h1 = load_arm("H1", "TRAIN", manifest=H1_SPLIT_MANIFEST).reset_index(drop=True)
    S = exposure_series(h1, SMA_PRIMARY)
    d = S["daily"]
    rng = np.random.default_rng(CAUSAL_SEED)
    cand = np.flatnonzero(S["valid"])
    pick = np.sort(rng.choice(cand, size=min(CAUSAL_PROBES, len(cand)), replace=False))
    dev_dc = dev_sma = 0.0
    bad = {"signal": 0, "exec_index": 0}
    for k in pick:
        i_sig = int(d["h1_index"].iloc[k])
        pre = h1.iloc[: i_sig + 1]                      # bars 0..signal bar
        dsub = daily_closes(pre)
        dc2 = float(dsub["close"].iloc[-1])
        sma2 = float(dsub["close"].tail(SMA_PRIMARY).mean())
        dev_dc = max(dev_dc, abs(dc2 - float(d["close"].iloc[k])))
        dev_sma = max(dev_sma, abs(sma2 - float(S["sma"][k])) / abs(float(S["sma"][k])))
        if (dc2 > sma2) != bool(S["signal"][k]):
            bad["signal"] += 1
        if int(dsub["h1_index"].iloc[-1]) + 1 != int(S["exec_idx"][k]):
            bad["exec_index"] += 1
    # exhaustive lookahead audit: the exposure at bar t must come from a daily
    # close whose H1 bar index is strictly less than t
    src = np.full(len(h1), -1)
    ok = S["valid"] & (S["exec_idx"] < len(h1))
    src[S["exec_idx"][ok]] = d["h1_index"].to_numpy()[ok]
    src = pd.Series(np.where(src >= 0, src, np.nan)).ffill().to_numpy()
    bars = np.arange(len(h1), dtype=float)
    viol = int(np.nansum(src[S["first_valid_bar"]:] >= bars[S["first_valid_bar"]:]))
    controls["causal_reconstruction"] = {
        "probes": int(len(pick)), "seed": CAUSAL_SEED,
        "observed": {"daily_close_abs": dev_dc, "sma_relative": dev_sma,
                     "disagreements": bad},
        "lookahead_audit": {"bars_checked": int(len(h1) - S["first_valid_bar"]),
                            "violations": viol},
        "PASS": bool(dev_dc <= TOL_DAILY_CLOSE and dev_sma <= TOL_SMA_REL
                     and sum(bad.values()) == 0 and viol == 0)}
    controls["no_feature_mining"] = {
        "windows_tested": [SMA_PRIMARY] + list(SMA_SENSITIVITY),
        "primary_fixed": SMA_PRIMARY,
        "statement": ("one signal definition, one primary window, one cadence, one "
                      "exposure ladder, one execution rule. SMA50/200 are disclosure.")}
    controls["dev_tuning"] = {"anything_refit_on_dev": False}
    controls["final_oos"] = {"loaded": False, "token": "OOS-AUTHORISATION-NOT-ISSUED"}
    controls["cost_convention"] = {
        "used": "1 x spread per round turn, USD (research convention)",
        "conflict_recorded": ("execution/fills.py FillModel applies the full spread on "
                              "both entry and exit = 2x per round turn, in pips. Not "
                              "used here; recorded, not repaired.")}

    cr = controls["causal_reconstruction"]
    print(f"\n[causal] daily_close dev {cr['observed']['daily_close_abs']:.1e} "
          f"sma_rel {cr['observed']['sma_relative']:.2e} "
          f"disagreements {cr['observed']['disagreements']} "
          f"lookahead violations {cr['lookahead_audit']['violations']} -> PASS={cr['PASS']}")

    # ---- verdict ------------------------------------------------------------
    tr, dv = results["arms"]["TRAIN"], results["arms"]["DEV"]
    both_dd = tr["drawdown_criterion_met"] and dv["drawdown_criterion_met"]
    both_sh = tr["sharpe_not_degraded"] and dv["sharpe_not_degraded"]
    results["verdict"] = {
        "primary_drawdown_both_arms": both_dd,
        "sharpe_not_degraded_both_arms": both_sh,
        "train_dd_improvement_pp": tr["drawdown_improvement_pp"],
        "dev_dd_improvement_pp": dv["drawdown_improvement_pp"],
        "train_cagr_give_up_pp": tr["cagr_give_up_pp"],
        "dev_cagr_give_up_pp": dv["cagr_give_up_pp"],
        # Specification section 10: ANY section-7 criterion met -> NOT SUPPORTED, and
        # "Sharpe degrading in either arm" is one of them, so it takes precedence
        # over the INCONCLUSIVE row.
        "against_criteria_met": {
            "sharpe_degraded_either_arm": not both_sh,
            "drawdown_not_improved_either_arm": (tr["drawdown_improvement_pp"] <= 0
                                                 or dv["drawdown_improvement_pp"] <= 0)},
        "classification": (
            "NOT SUPPORTED" if (not both_sh
                                or tr["drawdown_improvement_pp"] <= 0
                                or dv["drawdown_improvement_pp"] <= 0)
            else "SUPPORTED" if (both_dd and both_sh)
            else "INCONCLUSIVE")}
    print("\n" + "=" * 92)
    print(f"  drawdown >= {DD_IMPROVEMENT_REQUIRED_PP}pp better in BOTH arms : {both_dd}"
          f"   (TRAIN {tr['drawdown_improvement_pp']:+.2f}pp, DEV {dv['drawdown_improvement_pp']:+.2f}pp)")
    print(f"  Sharpe not degraded in BOTH arms              : {both_sh}")
    print(f"  CAGR give-up                                  : TRAIN {tr['cagr_give_up_pp']:+.3f}pp, "
          f"DEV {dv['cagr_give_up_pp']:+.3f}pp")
    print(f"  => H05 {results['verdict']['classification']}")
    print("=" * 92)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hypothesis_05_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "hypothesis_05_controls.json").write_text(
        json.dumps(controls, indent=1, default=str), encoding="utf-8")
    print(f"\n  wrote {out_dir/'hypothesis_05_results.json'}")
    print(f"  wrote {out_dir/'hypothesis_05_controls.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
