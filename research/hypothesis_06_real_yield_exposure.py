"""H06 — real-yield-conditional gold exposure. Runs the pre-registered spec.

Specification: `research/hypothesis_06_real_yield_exposure.md`, committed alone
before this file existed. Every constant and every decision below is taken from
it; nothing here is chosen.

FINAL_OOS is never requested. Only TRAIN and DEV are loaded, through
`research.dataset_access.load_arm`, which raises on FINAL_OOS without the token.

Run: ``python research/hypothesis_06_real_yield_exposure.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.benchmark import SPREAD_USD, hold_stats          # one source for cost
from research.dataset_access import H1_SPLIT_MANIFEST, load_arm

RAW = REPO / "data" / "cross_asset_v1" / "raw"
OUT_JSON = REPO / "research" / "hypothesis_06_results.json"

# ---------------------------------------------------------------- spec §2, §3
PRIMARY_SERIES = "DFII10"
PRIMARY_LOOKBACK_MONTHS = 12
EXPOSURE_CAP = 1.0                 # long-or-flat, unlevered
HALF_SPREAD = SPREAD_USD / 2.0     # one exposure change crosses half a round turn
EMBARGO_BUSINESS_DAYS = 1          # spec §3
ARMS = ("TRAIN", "DEV")            # FINAL_OOS deliberately absent

# spec §5 — the numbers to beat, quoted from research/BENCHMARK_REPORT.md
BENCHMARK_H1 = {
    "TRAIN": {"sharpe_rf0": 0.387, "max_drawdown_pct": -45.25},
    "DEV": {"sharpe_rf0": 0.880, "max_drawdown_pct": -21.87},
}
TRANSITION_BUDGET_PER_YEAR = 52.0  # spec §4, from BENCHMARK_REPORT

# spec §7 — power guards, declared in advance
MIN_STATE_CHANGES_TRAIN = 6
MAX_SINGLE_STATE_SHARE = 0.90

# spec §6 — diagnostics, Bonferroni corrected. NOT selection candidates.
DIAGNOSTICS: tuple[tuple[str, str, int], ...] = (
    ("DFII10_3m", "DFII10", 3),
    ("DFII10_6m", "DFII10", 6),
    ("DFII10_24m", "DFII10", 24),
    ("DFII5_12m", "DFII5", 12),
    ("DTWEXBGS_12m", "DTWEXBGS", 12),
)
VIX_DIAGNOSTIC = "VIXCLS_vs_12m_median"
DIAGNOSTIC_CELLS = 8               # as declared in the spec
ALPHA = 0.05
ALPHA_BONFERRONI = ALPHA / DIAGNOSTIC_CELLS

MISSING = {"", "."}


# ------------------------------------------------------------------ loading
def load_macro(series_id: str) -> pd.Series:
    """One FRED series, gaps filled by LAST OBSERVATION CARRIED FORWARD.

    LOCF is the rule declared in spec §3: a yield that was not published did not
    change, because the market was shut. Interpolation is rejected there because
    interpolating between two dates uses the later one, which is look-ahead.
    """
    frame = pd.read_csv(RAW / f"{series_id}.csv")
    date_column, value_column = frame.columns[0], frame.columns[1]
    frame[date_column] = pd.to_datetime(frame[date_column])
    values = pd.to_numeric(
        frame[value_column].astype(str).str.strip().replace(list(MISSING), None),
        errors="coerce",
    )
    series = pd.Series(values.values, index=frame[date_column], name=series_id)
    # Reindex onto every calendar day between the first and last observation,
    # then carry forward. ffill() alone would not bridge a weekend, because a
    # weekend has no row at all in the source.
    full = series.reindex(pd.date_range(series.index.min(), series.index.max()))
    return full.ffill()


def daily_gold(arm: str) -> pd.DataFrame:
    """Daily gold closes for one arm, resampled from the frozen H1 bars.

    The last H1 close of each UTC day is that day's close. No FINAL_OOS path
    exists here: `arm` comes from ARMS.
    """
    h1 = load_arm("H1", arm, manifest=H1_SPLIT_MANIFEST)
    times = pd.to_datetime(h1["time"], utc=True)
    frame = pd.DataFrame({"time": times, "close": h1["close"].astype(float)})
    frame = frame.set_index("time").sort_index()
    daily = frame["close"].resample("1D").last().dropna()
    # Drop the timezone AFTER resampling, so the day boundary is still UTC but
    # the index can be compared with the FRED series, which is tz-naive calendar
    # dates. Without this every `as_of in macro.index` test is False and the
    # exposure is NaN everywhere -- which `curve_stats` then reports as a
    # ten-bar curve rather than as an error.
    index = daily.index.tz_convert("UTC").tz_localize(None).normalize()
    return pd.DataFrame({"time": index, "close": daily.to_numpy(float)})


# ------------------------------------------------------------------ signal
def monthly_exposure(
    gold: pd.DataFrame, macro: pd.Series, lookback_months: int,
    rule: str = "sign_of_change",
) -> tuple[np.ndarray, list[pd.Timestamp]]:
    """Exposure per gold day, rebalanced monthly, with the spec §3 embargo.

    For each month in the arm, the signal is read as of the last business day of
    the PREVIOUS month minus `EMBARGO_BUSINESS_DAYS`, and the resulting exposure
    applies from the first gold day of the month until the next rebalance.

    Args:
        gold: Daily gold frame with `time` and `close`.
        macro: The conditioning series, already LOCF-filled onto calendar days.
        lookback_months: Months of change to measure.
        rule: ``"sign_of_change"`` for the primary and the change diagnostics;
            ``"vs_median"`` for the VIX level diagnostic.

    Returns:
        ``(exposure_per_gold_day, rebalance_dates)``. Exposure is NaN before the
        first month for which a signal exists.
    """
    times = pd.DatetimeIndex(gold["time"])
    exposure = np.full(len(gold), np.nan)
    rebalances: list[pd.Timestamp] = []

    months = pd.PeriodIndex(times, freq="M").unique()
    for period in months:
        in_month = np.flatnonzero(pd.PeriodIndex(times, freq="M") == period)
        if len(in_month) == 0:
            continue
        first_day = times[in_month[0]]

        # As-of date: last business day before the month starts, minus the
        # embargo. BDay arithmetic, so a Monday start looks back past the
        # weekend rather than into it.
        as_of = (first_day - pd.tseries.offsets.BDay(1)
                 - pd.tseries.offsets.BDay(EMBARGO_BUSINESS_DAYS))
        if as_of not in macro.index:
            continue

        if rule == "sign_of_change":
            previous = as_of - pd.DateOffset(months=lookback_months)
            if previous not in macro.index:
                continue
            delta = float(macro.loc[as_of]) - float(macro.loc[previous])
            level = 1.0 if delta <= 0.0 else 0.0
        elif rule == "vs_median":
            window = macro.loc[
                as_of - pd.DateOffset(months=lookback_months): as_of]
            if len(window) < 30:
                continue
            # Risk-off (VIX above its own median) favours gold as a haven.
            level = 1.0 if float(macro.loc[as_of]) >= float(window.median()) else 0.0
        else:  # pragma: no cover - guarded by callers
            raise ValueError(f"unknown rule {rule!r}")

        exposure[in_month] = min(level, EXPOSURE_CAP)
        rebalances.append(first_day)

    return exposure, rebalances


# ------------------------------------------------------------------ equity
def equity_curve(gold: pd.DataFrame, exposure: np.ndarray) -> dict:
    """Close-to-close equity, cost charged on each exposure change.

    Exposure at day `t` earns day `t -> t+1`'s return, never day `t`'s: spec §3.
    Cost is `|delta exposure| * HALF_SPREAD` in dollars, converted to a fraction
    at the price prevailing at the change, as BENCHMARK_REPORT requires.
    """
    close = gold["close"].to_numpy(float)
    n = len(close)
    start = int(np.argmax(np.isfinite(exposure)))
    if not np.isfinite(exposure[start]):
        return {"equity": np.full(n, np.nan), "exposure_changes": 0,
                "round_turns": 0.0, "cost_dollars_per_unit": 0.0, "start": start}

    equity = np.full(n, np.nan)
    equity[start] = 1.0
    changes = 0
    cost_total = 0.0
    previous = exposure[start]

    for t in range(start, n - 1):
        current = exposure[t]
        if not np.isfinite(current):
            current = 0.0
        if t > start and current != previous:
            changes += 1
            moved = abs(current - previous)
            equity[t] *= 1.0 - moved * HALF_SPREAD / close[t]
            cost_total += moved * HALF_SPREAD
            previous = current
        daily_return = close[t + 1] / close[t] - 1.0
        equity[t + 1] = equity[t] * (1.0 + current * daily_return)

    return {"equity": equity, "exposure_changes": changes,
            "round_turns": changes / 2.0,
            "cost_dollars_per_unit": round(cost_total, 4), "start": start}


def curve_stats(equity: np.ndarray, times: pd.Series, start: int,
                bars_per_year: float) -> dict:
    """Statistics matching `research.benchmark.hold_stats` exactly.

    Same Sharpe definition (log total return / years / annualised log-return
    vol), same drawdown definition, same 1% underwater threshold -- so the
    comparison against the benchmark is like for like rather than two different
    conventions placed side by side.
    """
    series = equity[start:]
    series = series[np.isfinite(series)]
    if len(series) < 10:
        return {"bars": int(len(series))}
    peak = np.maximum.accumulate(series)
    drawdown = (series - peak) / peak
    years = (times.iloc[-1] - times.iloc[start]).days / 365.25
    total = series[-1] / series[0] - 1.0
    log_returns = np.diff(np.log(series))
    volatility = float(log_returns.std(ddof=1) * np.sqrt(bars_per_year))
    underwater = drawdown < -0.01
    run = best = 0
    for flag in underwater:
        run = run + 1 if flag else 0
        best = max(best, run)
    return {
        "bars": int(len(series)), "years": round(years, 2),
        "bars_per_year": round(bars_per_year, 1),
        "total_return_pct": round(100 * float(total), 2),
        "cagr_pct": round(100 * float((1 + total) ** (1 / years) - 1), 3),
        "max_drawdown_pct": round(100 * float(drawdown.min()), 2),
        "longest_underwater_years": round(best / bars_per_year, 2),
        "ann_volatility_pct": round(100 * volatility, 2),
        "sharpe_rf0": (round(float(np.log(1 + total) / years / volatility), 3)
                       if volatility > 0 else None),
    }


def exposure_profile(exposure: np.ndarray) -> dict:
    """State occupancy and transition count, for the spec §7 power guards."""
    valid = exposure[np.isfinite(exposure)]
    if len(valid) == 0:
        return {"observations": 0}
    long_share = float((valid >= 1.0).mean())
    changes = int((np.diff(valid) != 0).sum())
    return {
        "observations": int(len(valid)),
        "share_long": round(long_share, 4),
        "share_flat": round(1.0 - long_share, 4),
        "state_changes": changes,
        "dominant_state_share": round(max(long_share, 1.0 - long_share), 4),
    }


# ------------------------------------------------------------------ one cell
def evaluate(arm: str, gold: pd.DataFrame, macro: pd.Series,
             lookback: int, rule: str) -> dict:
    exposure, rebalances = monthly_exposure(gold, macro, lookback, rule)
    curve = equity_curve(gold, exposure)
    bars_per_year = len(gold) / (
        (pd.Timestamp(gold["time"].max()) - pd.Timestamp(gold["time"].min())).days
        / 365.25)
    strategy = curve_stats(curve["equity"], gold["time"], curve["start"],
                           bars_per_year)
    hold = hold_stats(gold, bars_per_year)
    years = strategy.get("years") or 1.0
    profile = exposure_profile(exposure)
    return {
        "arm": arm,
        "rebalances": len(rebalances),
        "strategy": strategy,
        "hold_same_series": hold,
        "exposure": profile,
        "transitions": {
            "exposure_changes": curve["exposure_changes"],
            "round_turns": curve["round_turns"],
            "round_turns_per_year": round(curve["round_turns"] / years, 2),
            "within_budget": bool(
                curve["round_turns"] / years <= TRANSITION_BUDGET_PER_YEAR),
            "cost_dollars_per_unit": curve["cost_dollars_per_unit"],
        },
        "versus_hold_same_series": {
            "sharpe_delta": (round(strategy["sharpe_rf0"] - hold["sharpe_rf0"], 3)
                             if strategy.get("sharpe_rf0") is not None else None),
            # Drawdowns are NEGATIVE, so a shallower (better) one is the LARGER
            # number: improvement = strategy - benchmark. Spec §3.
            "drawdown_improvement_pp": round(
                strategy["max_drawdown_pct"] - hold["max_drawdown_pct"], 2),
        },
    }


def main() -> int:
    macro_cache = {sid: load_macro(sid)
                   for sid in {PRIMARY_SERIES, "DFII5", "DTWEXBGS", "VIXCLS"}}
    gold = {arm: daily_gold(arm) for arm in ARMS}

    results: dict = {
        "hypothesis": "H06 real-yield-conditional gold exposure",
        "specification": "research/hypothesis_06_real_yield_exposure.md",
        "dataset_sha256": json.loads(
            (REPO / "data" / "cross_asset_v1" / "meta" / "manifest.json")
            .read_text(encoding="utf-8"))["dataset_sha256"],
        "final_oos": "NOT LOADED, NOT INSPECTED",
        "primary": {}, "diagnostics": {},
        "alpha": ALPHA, "diagnostic_cells": DIAGNOSTIC_CELLS,
        "alpha_bonferroni": ALPHA_BONFERRONI,
    }

    print("=" * 78)
    print("H06 — REAL-YIELD-CONDITIONAL GOLD EXPOSURE")
    print("=" * 78)
    print(f"  spec            research/hypothesis_06_real_yield_exposure.md")
    print(f"  macro series    {PRIMARY_SERIES}, {PRIMARY_LOOKBACK_MONTHS}-month change")
    print(f"  rule            exposure = 1.0 if delta <= 0 else 0.0, monthly")
    print(f"  FINAL_OOS       not loaded\n")

    for arm in ARMS:
        cell = evaluate(arm, gold[arm], macro_cache[PRIMARY_SERIES],
                        PRIMARY_LOOKBACK_MONTHS, "sign_of_change")
        results["primary"][arm] = cell
        s, h, x = cell["strategy"], cell["hold_same_series"], cell["exposure"]
        print(f"  --- {arm} ---  {s['bars']} daily bars, {s['years']} years, "
              f"{cell['rebalances']} rebalances")
        print(f"    {'':22} {'strategy':>12} {'hold':>12}")
        print(f"    {'CAGR %':22} {s['cagr_pct']:>12.3f} {h['cagr_pct']:>12.3f}")
        print(f"    {'Sharpe (rf=0)':22} {s['sharpe_rf0']:>12.3f} "
              f"{h['sharpe_rf0']:>12.3f}")
        print(f"    {'max drawdown %':22} {s['max_drawdown_pct']:>12.2f} "
              f"{h['max_drawdown_pct']:>12.2f}")
        print(f"    {'ann vol %':22} {s['ann_volatility_pct']:>12.2f} "
              f"{h['ann_volatility_pct']:>12.2f}")
        print(f"    {'underwater yrs':22} {s['longest_underwater_years']:>12.2f} "
              f"{h['longest_underwater_years']:>12.2f}")
        print(f"    exposure: long {100 * x['share_long']:.1f}% of days, "
              f"{x['state_changes']} state changes, "
              f"{cell['transitions']['round_turns_per_year']} round turns/yr "
              f"(budget {TRANSITION_BUDGET_PER_YEAR})")
        print()

    # ------------------------------------------------- spec §7 power guards
    train = results["primary"]["TRAIN"]
    changes_train = train["exposure"]["state_changes"]
    dominant_train = train["exposure"]["dominant_state_share"]
    underpowered = changes_train < MIN_STATE_CHANGES_TRAIN
    uninformative = dominant_train > MAX_SINGLE_STATE_SHARE
    results["power"] = {
        "train_state_changes": changes_train,
        "min_required": MIN_STATE_CHANGES_TRAIN,
        "underpowered": bool(underpowered),
        "train_dominant_state_share": dominant_train,
        "max_allowed": MAX_SINGLE_STATE_SHARE,
        "uninformative": bool(uninformative),
    }

    # ------------------------------------------------- spec §5 criteria
    criteria = {}
    for arm in ARMS:
        cell = results["primary"][arm]
        s = cell["strategy"]
        hold_same = cell["hold_same_series"]
        criteria[arm] = {
            "sharpe_beats_hold_same_series":
                bool(s["sharpe_rf0"] > hold_same["sharpe_rf0"]),
            "sharpe_beats_report_h1_benchmark":
                bool(s["sharpe_rf0"] > BENCHMARK_H1[arm]["sharpe_rf0"]),
            "drawdown_shallower_than_hold_same_series":
                bool(s["max_drawdown_pct"] > hold_same["max_drawdown_pct"]),
            "drawdown_shallower_than_report_h1_benchmark":
                bool(s["max_drawdown_pct"] > BENCHMARK_H1[arm]["max_drawdown_pct"]),
            "within_transition_budget": cell["transitions"]["within_budget"],
        }
    results["criteria"] = criteria

    all_met = all(all(v.values()) for v in criteria.values())
    if underpowered:
        verdict = "UNDERPOWERED"
    elif uninformative:
        verdict = "UNINFORMATIVE"
    elif all_met:
        verdict = "SUPPORTED"
    else:
        verdict = "NOT SUPPORTED"
    results["verdict"] = verdict

    print("  " + "-" * 74)
    print("  PRE-DECLARED CRITERIA (spec §5) — all five, both arms, or NOT SUPPORTED")
    for arm in ARMS:
        for name, met in criteria[arm].items():
            print(f"    {arm:<6} {name:<46} {'PASS' if met else 'FAIL'}")
    print(f"\n    power: TRAIN state changes {changes_train} "
          f"(>= {MIN_STATE_CHANGES_TRAIN} required) -> "
          f"{'UNDERPOWERED' if underpowered else 'adequate'}")
    print(f"    power: TRAIN dominant state {100 * dominant_train:.1f}% "
          f"(<= {100 * MAX_SINGLE_STATE_SHARE:.0f}% required) -> "
          f"{'UNINFORMATIVE' if uninformative else 'adequate'}")
    print(f"\n  VERDICT: {verdict}")

    # ------------------------------------------------- spec §6 diagnostics
    print("\n  " + "-" * 74)
    print("  SECONDARY DIAGNOSTICS (spec §6) — NOT selection candidates")
    print(f"  Bonferroni: {DIAGNOSTIC_CELLS} cells, alpha' = {ALPHA_BONFERRONI:.5f}")
    for name, series_id, lookback in DIAGNOSTICS:
        results["diagnostics"][name] = {}
        row = []
        for arm in ARMS:
            cell = evaluate(arm, gold[arm], macro_cache[series_id], lookback,
                            "sign_of_change")
            results["diagnostics"][name][arm] = cell
            row.append((arm, cell))
        print(f"    {name:<16} " + "  ".join(
            f"{arm} Sharpe {c['strategy'].get('sharpe_rf0')} vs "
            f"{c['hold_same_series']['sharpe_rf0']}" for arm, c in row))
    results["diagnostics"][VIX_DIAGNOSTIC] = {}
    row = []
    for arm in ARMS:
        cell = evaluate(arm, gold[arm], macro_cache["VIXCLS"], 12, "vs_median")
        results["diagnostics"][VIX_DIAGNOSTIC][arm] = cell
        row.append((arm, cell))
    print(f"    {VIX_DIAGNOSTIC:<16} " + "  ".join(
        f"{arm} Sharpe {c['strategy'].get('sharpe_rf0')} vs "
        f"{c['hold_same_series']['sharpe_rf0']}" for arm, c in row))

    OUT_JSON.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\n  written: {OUT_JSON.relative_to(REPO)}")
    print("\n  No profitability claim is made on any figure above (spec §8).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
