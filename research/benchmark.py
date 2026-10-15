"""The benchmark every candidate is measured against, and the cost budget that
decides which candidates may be attempted at all.

Why this exists: Phase 1-3 and H01-H04 all tested "is mean forward return > 0".
For a rising asset that is trivially yes, which is why the drift baselines ate
every result. Nobody computed what buy-and-hold actually returns, so nothing was
ever measured against the only benchmark that matters.

Two outputs, both reusable:

1. BUY-AND-HOLD per arm -- CAGR, max drawdown, longest time underwater,
   annualised volatility, Sharpe. A candidate must beat this risk-adjusted.
2. TRANSITION-COST BUDGET -- how many round turns per year a candidate can
   afford before the spread eats the benchmark's return. This is a HARD GATE: a
   strategy form whose capture requires more transitions than the budget allows
   is not attempted, however strong its statistics.

READ-ONLY. FINAL_OOS is not inspected.
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

from research.dataset_access import (                                     # noqa: E402
    H1_SPLIT_MANIFEST, _split, load_arm, verify_dataset,
)

SPREAD_USD = 0.33          # measured median round turn = 1 x spread
# The gate threshold: a candidate may not surrender more than this share of the
# benchmark's return to transaction costs. Declared, not fitted.
GATE_SHARE_OF_RETURN = 0.20
SCHEDULES = {"twice daily": 504, "daily": 252, "every 2 days": 126,
             "weekly": 52, "fortnightly": 25, "monthly": 12, "quarterly": 4}
ERA_EDGES = [2008, 2012, 2016, 2020, 2024, 2027]
ERA_LABELS = ["2009-12", "2013-16", "2017-20", "2021-24", "2025-26"]


def hold_stats(df: pd.DataFrame, bars_per_year: float) -> dict:
    """Buy-and-hold, marked at bar close, paying one round turn over the whole
    holding period (entry and exit together) as a holder actually does."""
    c = df["close"].to_numpy(float)
    peak = np.maximum.accumulate(c)
    dd = (c - peak) / peak
    yrs = (df["time"].max() - df["time"].min()).days / 365.25
    gross = c[-1] - c[0]
    net = gross - SPREAD_USD
    tot_net = net / c[0]
    logret = np.diff(np.log(c))
    vol_ann = float(logret.std(ddof=1) * np.sqrt(bars_per_year))
    cagr = (1 + tot_net) ** (1 / yrs) - 1
    under = dd < -0.01
    run = best = 0
    for u in under:
        run = run + 1 if u else 0
        best = max(best, run)
    return {
        "bars": int(len(df)), "years": round(yrs, 2),
        "bars_per_year": round(bars_per_year, 1),
        "price_first": round(float(c[0]), 2), "price_last": round(float(c[-1]), 2),
        "price_mean": round(float(c.mean()), 2),
        "gross_dollars_per_unit": round(float(gross), 2),
        "cost_dollars_one_round_turn": SPREAD_USD,
        "total_return_pct": round(100 * float(tot_net), 2),
        "cagr_pct": round(100 * float(cagr), 3),
        "max_drawdown_pct": round(100 * float(dd.min()), 2),
        "longest_underwater_years": round(best / bars_per_year, 2),
        "ann_volatility_pct": round(100 * vol_ann, 2),
        "sharpe_rf0": round(float(np.log(1 + tot_net) / yrs / vol_ann), 3),
        "annual_dollar_gain_per_unit": round(float(gross / yrs), 2),
    }


def budget(hold: dict) -> dict:
    """How many round turns per year a candidate can afford.

    Expressed as an annual drag in PERCENT OF CAPITAL, which is the comparable
    unit: N transitions x spread / mean price. The dollar framing is also kept
    because the spread is a fixed dollar amount while the return scales with the
    price level.
    """
    cagr = hold["cagr_pct"] / 100.0
    mean_px = hold["price_mean"]
    drag_per_turn_pct = SPREAD_USD / mean_px          # per round turn, % of capital
    out = {
        "cagr_pct": hold["cagr_pct"], "mean_price": mean_px,
        "drag_per_round_turn_pct_of_capital": round(100 * drag_per_turn_pct, 5),
        "affordable_round_turns_per_year": {},
        "schedule_cost": {},
    }
    for share in (0.10, GATE_SHARE_OF_RETURN, 0.50, 1.00):
        n = cagr * share / drag_per_turn_pct if drag_per_turn_pct > 0 else 0
        out["affordable_round_turns_per_year"][f"{int(100*share)}%_of_return"] = {
            "round_turns": int(np.floor(n)),
            "one_per_days": (round(365 / n, 1) if n > 0 else None)}
    for lbl, n in SCHEDULES.items():
        drag = n * drag_per_turn_pct
        out["schedule_cost"][lbl] = {
            "round_turns_per_year": n,
            "annual_drag_pct_of_capital": round(100 * drag, 3),
            "share_of_cagr_pct": round(100 * drag / cagr, 1) if cagr > 0 else None,
            "verdict": ("DEAD" if drag >= cagr else
                        "viable" if drag <= GATE_SHARE_OF_RETURN * cagr else "marginal")}
    gate = cagr * GATE_SHARE_OF_RETURN / drag_per_turn_pct
    out["GATE_max_round_turns_per_year"] = int(np.floor(gate))
    out["GATE_basis"] = (
        f"a candidate may not surrender more than {int(100*GATE_SHARE_OF_RETURN)}% of the "
        f"benchmark CAGR to spread. Declared, not fitted.")
    return out


def run(out_dir: Path) -> None:
    verify_dataset()
    split = _split(H1_SPLIT_MANIFEST)
    results: dict = {
        "purpose": ("the buy-and-hold benchmark every candidate is measured against, and "
                    "the transition-cost budget that decides which strategy forms may be "
                    "attempted at all"),
        "manifest": "research/research_split_manifest_h1.json",
        "round_turn_usd": SPREAD_USD,
        "gate_share_of_return": GATE_SHARE_OF_RETURN,
        "oos": {"inspected": False,
                "note": "FINAL_OOS is not loaded; only TRAIN and DEV are benchmarked"},
        "annualisation": None, "arms": {}, "eras": {},
    }

    print("=" * 100)
    print("BUY-AND-HOLD BENCHMARK -- the reference nobody computed")
    print("=" * 100)
    for arm in ("TRAIN", "DEV"):
        df = load_arm("H1", arm, manifest=H1_SPLIT_MANIFEST)
        yrs = (df["time"].max() - df["time"].min()).days / 365.25
        bpy = len(df) / yrs                   # MEASURED, not assumed 24x365
        h = hold_stats(df, bpy)
        b = budget(h)
        results["arms"][arm] = {"hold": h, "budget": b,
                               "from": str(df["time"].min()), "to": str(df["time"].max())}
        print(f"\n  {arm}  {str(df['time'].min())[:10]} -> {str(df['time'].max())[:10]}"
              f"   {h['bars']:,} bars, {h['years']} yr")
        print(f"    total return      {h['total_return_pct']:+8.2f}%   (net of one round turn)")
        print(f"    CAGR              {h['cagr_pct']:+8.3f}%")
        print(f"    max drawdown      {h['max_drawdown_pct']:+8.2f}%")
        print(f"    longest underwater{h['longest_underwater_years']:8.2f} years")
        print(f"    ann. volatility   {h['ann_volatility_pct']:8.2f}%   "
              f"(annualised on {h['bars_per_year']:,.0f} measured bars/yr)")
        print(f"    SHARPE (rf=0)     {h['sharpe_rf0']:8.3f}   <-- the number to beat")

    # annualisation disclosure -- this corrected a figure quoted earlier
    tr = results["arms"]["TRAIN"]["hold"]
    naive = tr["ann_volatility_pct"] * np.sqrt(24 * 365.25 / tr["bars_per_year"])
    results["annualisation"] = {
        "basis": "measured bars per year per arm, not an assumed 24x365",
        "train_bars_per_year": tr["bars_per_year"],
        "calendar_hours_per_year": round(24 * 365.25, 1),
        "train_vol_pct_measured_basis": tr["ann_volatility_pct"],
        "train_vol_pct_if_24x365_assumed": round(float(naive), 2),
        "note": ("gold trades about 120 hours a week, not 168. Annualising hourly "
                 "returns with sqrt(24*365) overstates volatility by about "
                 f"{np.sqrt(24*365.25/tr['bars_per_year']):.2f}x and understates Sharpe by "
                 "the same factor. An earlier quick calculation in this session used the "
                 "24x365 basis and therefore understated the benchmark Sharpe; the figure "
                 "here supersedes it.")}
    print(f"\n  [annualisation] measured {tr['bars_per_year']:,.0f} bars/yr vs "
          f"{24*365.25:,.0f} calendar hours. Using the calendar basis would report "
          f"{naive:.2f}% vol instead of {tr['ann_volatility_pct']:.2f}% and understate "
          f"Sharpe by {np.sqrt(24*365.25/tr['bars_per_year']):.2f}x.")

    print("\n" + "=" * 100)
    print("TRANSITION-COST BUDGET -- the hard gate on strategy form")
    print("=" * 100)
    for arm in ("TRAIN", "DEV"):
        b = results["arms"][arm]["budget"]
        print(f"\n  {arm}: CAGR {b['cagr_pct']:+.3f}%  mean price ${b['mean_price']:,.0f}  "
              f"drag per round turn {b['drag_per_round_turn_pct_of_capital']:.4f}% of capital")
        for k, v in b["affordable_round_turns_per_year"].items():
            print(f"    cost <= {k:<18} {v['round_turns']:>6,} round turns/yr"
                  + (f"  (~1 per {v['one_per_days']} days)" if v["one_per_days"] else ""))
        print(f"    {'schedule':<16} {'turns/yr':>9} {'drag%/yr':>9} {'% of CAGR':>10}  verdict")
        for lbl, v in b["schedule_cost"].items():
            print(f"    {lbl:<16} {v['round_turns_per_year']:>9,} "
                  f"{v['annual_drag_pct_of_capital']:>9.3f} {v['share_of_cagr_pct']:>9.1f}%  "
                  f"{v['verdict']}")
        print(f"    >>> GATE: at most {b['GATE_max_round_turns_per_year']:,} round turns/yr")

    # per-era budget: the spread is fixed in dollars, the price level is not
    print("\n" + "=" * 100)
    print("PER-ERA BUDGET -- the spread is a fixed dollar amount, the price level is not")
    print("=" * 100)
    full = pd.concat([load_arm("H1", a, manifest=H1_SPLIT_MANIFEST) for a in ("TRAIN", "DEV")])
    full = full.sort_values("time").reset_index(drop=True)
    full["era"] = pd.cut(full["time"].dt.year, ERA_EDGES, labels=ERA_LABELS)
    print(f"  {'era':<10} {'bars':>8} {'mean $':>9} {'drag/turn %':>12} {'weekly drag%':>13} {'monthly drag%':>14}")
    for era, g in full.groupby("era", observed=True):
        if len(g) < 500:
            continue
        mp = float(g["close"].mean())
        d = SPREAD_USD / mp
        results["eras"][str(era)] = {
            "bars": int(len(g)), "mean_price": round(mp, 2),
            "drag_per_round_turn_pct": round(100 * d, 5),
            "weekly_drag_pct": round(100 * 52 * d, 3),
            "monthly_drag_pct": round(100 * 12 * d, 3)}
        print(f"  {str(era):<10} {len(g):>8,} {mp:>9,.0f} {100*d:>12.4f} "
              f"{100*52*d:>13.3f} {100*12*d:>14.3f}")
    print("  -> the budget is ~3.6x tighter in 2009-12 than in 2025-26, so a rule that is")
    print("     affordable at today's price level may not have been in the earlier era.")

    print("\n" + "=" * 100)
    print("CONSEQUENCE FOR STRATEGY FORM")
    print("=" * 100)
    g_tr = results["arms"]["TRAIN"]["budget"]["GATE_max_round_turns_per_year"]
    g_dv = results["arms"]["DEV"]["budget"]["GATE_max_round_turns_per_year"]
    binding = min(g_tr, g_dv)
    results["binding_gate_round_turns_per_year"] = binding
    results["forms_ruled_out"] = [lbl for lbl, v in
                                  results["arms"]["TRAIN"]["budget"]["schedule_cost"].items()
                                  if v["verdict"] == "DEAD"]
    results["forms_viable"] = [lbl for lbl, v in
                               results["arms"]["TRAIN"]["budget"]["schedule_cost"].items()
                               if v["verdict"] == "viable"]
    print(f"  binding gate across arms: {binding:,} round turns/yr "
          f"(TRAIN {g_tr:,}, DEV {g_dv:,})")
    print(f"  RULED OUT on cost alone : {results['forms_ruled_out']}")
    print(f"  VIABLE                  : {results['forms_viable']}")
    print("\n  Intraday timing is ruled out here on economics, not on statistics: an")
    print("  hour-of-day rule has ~3x statistical headroom per hour bucket but needs")
    print("  ~504 round turns/yr, which exceeds the gate by an order of magnitude.")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\n  wrote {out_dir/'benchmark_results.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
