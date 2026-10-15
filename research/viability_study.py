"""Viability study -- what effect size is needed to beat cost, and is it detectable?

Asked BEFORE any further hypothesis. Phases 1-3 and hypotheses H01-H04 produced
126+ pre-registered tests and 0 survivors, with 0/6, 1/12 and 0/24 cells powered
against spread cost in H02, H03 and H04. This study establishes, as a hard design
constraint, which (horizon, timeframe, event-rate) combinations can support a
decision at all.

Framing, corrected from the first draft of the plan: the round-turn cost is a
fixed DOLLAR amount, and a 4-hour price move is the same move however it is
barred. So the choice of bar timeframe does NOT change the economics of a trade
at a given holding period. What it changes is how much HISTORY is available and
therefore how many INDEPENDENT observations of that holding period exist.

Everything is therefore expressed at a fixed wall-clock horizon:
    cost_in_sd = round_turn_dollars / sd( dollar move over the horizon )
    MDE_in_sd  = z / sqrt( independent observations )
A combination is testable only if MDE_in_sd <= cost_in_sd.

READ-ONLY. No feature, threshold, candidate or label is selected here. Reports
only up to the DEV boundary; FINAL_OOS is not inspected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import load_timeframe, verify_dataset        # noqa: E402
from research.phase1_statistical_controls import (                        # noqa: E402
    bonferroni_t, non_overlapping_indices, raw_stats,
)

SPREAD_USD = 0.33                 # measured median round turn, 1 x spread
BAR_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
# wall-clock horizons, in hours
HORIZONS_H = (1, 4, 24)
# event rates to budget, as a fraction of bars
EVENT_RATES = (0.005, 0.01, 0.02, 0.05, 0.10, 0.25, 1.00)
# correction sizes seen in this programme
N_TESTS_REF = {"single": 1, "declared_12": 12, "accumulated_30": 30}
ERA_EDGES = [2008, 2015, 2021, 2024, 2027]
ERA_LABELS = ["2009-15", "2016-21", "2022-24", "2025-26"]
RETENTION_SEED = 20261006

SPLIT = json.loads((Path(__file__).with_name("research_split_manifest.json")).read_text(encoding="utf-8"))
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])

# Observed retention from the committed hypotheses, used to validate the model
# rather than trusting a Poisson assumption. raw -> non-overlapping at h bars.
OBSERVED_RETENTION = [
    ("H01 TRAIN @4h", 1052, 914, 16), ("H02 TRAIN @4h", 574, 516, 16),
    ("H03 TRAIN EXP @4h", 697, 687, 16), ("H04 TRAIN LONG_ACCEPT @4h", 624, 502, 16),
    ("H01 TRAIN @1h", 1052, 1044, 4), ("H03 TRAIN EXP @1h", 697, 697, 4),
]


def measure_retention(n_bars: int, rate: float, h: int, reps: int = 5) -> float:
    """Fraction of events surviving non-overlapping selection, measured with the
    production selector rather than modelled, by placing events at random.

    Measured against the committed hypotheses, this UNDER-estimates retention in
    5 of 6 cases (see `retention_validation`), because every hypothesis in this
    programme enforces minimum event spacing in its deduplication rule, which
    makes real events more regular than random rather than more clustered. The
    model is therefore conservative: it over-states the MDE and so sets a
    slightly too strict GO bar, which is the safe direction for a gating study.
    """
    rng = np.random.default_rng(RETENTION_SEED)
    k = int(round(rate * n_bars))
    if k < 2:
        return 0.0
    keep = []
    for _ in range(reps):
        idx = np.sort(rng.choice(n_bars, size=min(k, n_bars), replace=False))
        keep.append(len(non_overlapping_indices(idx, h)) / len(idx))
    return float(np.mean(keep))


def run(out_dir: Path) -> None:
    verify_dataset()
    results: dict = {
        "question": ("what effect size is needed to beat cost, and is it detectable "
                     "with the data available?"),
        "framing": ("cost is a fixed dollar amount and a given holding period is the "
                    "same move however barred, so timeframe changes HISTORY and "
                    "INDEPENDENT OBSERVATIONS, not the economics of a trade"),
        "round_turn_usd": SPREAD_USD,
        "oos": {"inspected": False, "reported_through": str(DEV_HI),
                "note": ("all statistics are computed on bars at or before the DEV "
                         "boundary; FINAL_OOS is not inspected")},
        "spread_era_caveat": ("$0.33 was measured on the current broker feed in "
                             "2025-26. Applying it to 2009-2015 is an assumption and "
                             "is almost certainly optimistic for the older eras; a "
                             "sensitivity band is reported. Note the sensitivity runs "
                             "counter-intuitively: a WIDER spread raises cost_in_sd and "
                             "so makes a combination EASIER to call testable, because "
                             "only larger effects then qualify as economically "
                             "interesting and larger effects are easier to detect. It "
                             "makes the TEST easier and the STRATEGY harder. The useful "
                             "reading is that the GO verdicts are robust to the spread "
                             "assumption."),
        "timeframes": {}, "horizon_table": {}, "event_rate_budget": {},
        "regime_inventory": {}, "retention_validation": {}, "go_no_go": [],
    }

    # ---- load, truncate at the DEV boundary -------------------------------
    data: dict[str, pd.DataFrame] = {}
    for tf in BAR_MINUTES:
        df = load_timeframe(tf)
        df = df[df["time"] <= DEV_HI].reset_index(drop=True)
        assert df["time"].max() <= DEV_HI, f"{tf} extends past the DEV boundary"
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        df["era"] = pd.cut(df["time"].dt.year, ERA_EDGES, labels=ERA_LABELS)
        data[tf] = df
        yrs = (df["time"].max() - df["time"].min()).days / 365.25
        results["timeframes"][tf] = {
            "bars": int(len(df)), "from": str(df["time"].min()),
            "to": str(df["time"].max()), "years": round(yrs, 2),
            "bar_minutes": BAR_MINUTES[tf]}
        print(f"[data] {tf:>4} {len(df):>8,} bars  {str(df['time'].min())[:10]} -> "
              f"{str(df['time'].max())[:10]}  {yrs:5.1f} yr")

    # ---- the horizon table: the decisive calculation ----------------------
    print("\n" + "=" * 104)
    print("DECISIVE TABLE -- at a fixed wall-clock horizon, can a cost-sized effect be seen at all?")
    print("  cost_in_sd = $0.33 / sd(dollar move over horizon).  MDE_in_sd = z / sqrt(independent obs).")
    print("  TESTABLE requires MDE <= cost.  'all bars' is the absolute ceiling: every bar an event.")
    print("=" * 104)
    hdr = (f"  {'hor':>4} {'TF':>4} {'bars/hor':>8} {'indep obs':>10} {'sd($)':>8} "
           f"{'cost_sd':>8} {'MDE1':>7} {'MDE12':>7} {'MDE30':>7} {'verdict(30)':>12}")
    print(hdr)
    for H in HORIZONS_H:
        for tf, bm in BAR_MINUTES.items():
            if (H * 60) % bm != 0:
                continue
            h = (H * 60) // bm
            df = data[tf]
            n = len(df)
            if h < 1 or n < 10 * h:
                continue
            c = df["close"].to_numpy(float)
            # non-overlapping dollar moves over the horizon
            moves = c[h::h] - c[:-h:h]
            moves = moves[np.isfinite(moves)]
            n_indep = len(moves)
            sd = float(np.std(moves, ddof=1))
            if sd <= 0:
                continue
            cost_in_sd = SPREAD_USD / sd
            row = {"horizon_hours": H, "timeframe": tf, "bars_per_horizon": h,
                   "independent_obs": n_indep, "sd_dollars": round(sd, 4),
                   "cost_in_sd": round(cost_in_sd, 5)}
            verdict = None
            for lbl, k in N_TESTS_REF.items():
                z = bonferroni_t(k, 0.05) if k > 1 else 2.0
                mde = z / np.sqrt(n_indep)
                row[f"mde_in_sd_{lbl}"] = round(float(mde), 5)
                row[f"testable_{lbl}"] = bool(mde <= cost_in_sd)
                if lbl == "accumulated_30":
                    verdict = "TESTABLE" if mde <= cost_in_sd else "NOT TESTABLE"
                    row["headroom_x"] = round(float(cost_in_sd / mde), 2)
            results["horizon_table"][f"{H}h|{tf}"] = row
            print(f"  {H:>3}h {tf:>4} {h:>8} {n_indep:>10,} {sd:>8.3f} {cost_in_sd:>8.4f} "
                  f"{row['mde_in_sd_single']:>7.4f} {row['mde_in_sd_declared_12']:>7.4f} "
                  f"{row['mde_in_sd_accumulated_30']:>7.4f} {verdict:>12}")

    # ---- event-rate budget: the constraint the hypotheses violated --------
    print("\n" + "=" * 104)
    print("EVENT-RATE BUDGET -- a mechanism firing on only p of bars loses power proportionally.")
    print("  Columns give MDE_in_sd at the accumulated-30 threshold. Bold-equivalent = TESTABLE.")
    print("=" * 104)
    z30 = bonferroni_t(30, 0.05)
    for H in HORIZONS_H:
        for tf, bm in BAR_MINUTES.items():
            if (H * 60) % bm != 0:
                continue
            h = (H * 60) // bm
            df = data[tf]
            n = len(df)
            if n < 10 * h:
                continue
            key = f"{H}h|{tf}"
            if key not in results["horizon_table"]:
                continue
            cost_in_sd = results["horizon_table"][key]["cost_in_sd"]
            cells, line = {}, []
            for p in EVENT_RATES:
                ret = measure_retention(n, p, h)
                n_ev = p * n * ret
                if n_ev < 2:
                    cells[f"p={p}"] = None
                    line.append("    -  ")
                    continue
                mde = z30 / np.sqrt(n_ev)
                ok = mde <= cost_in_sd
                cells[f"p={p}"] = {"events_raw": int(round(p * n)),
                                   "retention": round(ret, 4),
                                   "events_non_overlapping": int(round(n_ev)),
                                   "mde_in_sd": round(float(mde), 5), "testable": bool(ok)}
                line.append(f"{mde:6.3f}{'*' if ok else ' '}")
            results["event_rate_budget"][key] = {"cost_in_sd": cost_in_sd, "rates": cells}
            print(f"  {H:>3}h {tf:>4} cost {cost_in_sd:.4f} | "
                  + " ".join(line) + "   (p=" + ", ".join(str(r) for r in EVENT_RATES) + ")")
    print("  * = TESTABLE at that event rate (MDE <= cost)")

    # ---- minimum event count per combination ------------------------------
    print("\n" + "=" * 104)
    print("MINIMUM EVENTS NEEDED -- the design constraint every future hypothesis must cite")
    print("=" * 104)
    print(f"  {'hor':>4} {'TF':>4} {'cost_in_sd':>11} {'min events':>11} {'min rate':>10} {'available':>11} {'feasible':>9}")
    for key, row in results["horizon_table"].items():
        H, tf = row["horizon_hours"], row["timeframe"]
        cost = row["cost_in_sd"]
        n_min = (z30 / cost) ** 2
        n_avail = row["independent_obs"]
        rate_min = n_min / len(data[tf])
        feasible = n_min <= n_avail
        row["min_events_needed"] = int(np.ceil(n_min))
        row["min_event_rate"] = round(float(rate_min), 5)
        row["feasible_at_full_history"] = bool(feasible)
        print(f"  {H:>3}h {tf:>4} {cost:>11.4f} {int(np.ceil(n_min)):>11,} {rate_min:>10.4f} "
              f"{n_avail:>11,} {'YES' if feasible else 'NO':>9}")

    # ---- regime inventory, to the DEV boundary only -----------------------
    print("\n" + "=" * 104)
    print("REGIME INVENTORY (to the DEV boundary; FINAL_OOS not inspected)")
    print("=" * 104)
    for tf in ("M15", "H1", "H4"):
        df = data[tf]
        g = df.groupby(df["time"].dt.year)["close"].agg(["first", "last", "count"])
        g["ret_pct"] = 100 * (g["last"] / g["first"] - 1)
        up = g[g.ret_pct > 0]; down = g[g.ret_pct < 0]
        inv = {"years_total": int(len(g)),
               "years_up": int(len(up)), "years_down": int(len(down)),
               "bars_up": int(g.loc[up.index, "count"].sum()),
               "bars_down": int(g.loc[down.index, "count"].sum()),
               "down_years": [int(y) for y in down.index],
               "net_pct_full": round(float(100 * (df.close.iloc[-1] / df.close.iloc[0] - 1)), 2)}
        inv["pct_bars_in_down_years"] = round(
            100 * inv["bars_down"] / max(inv["bars_up"] + inv["bars_down"], 1), 2)
        results["regime_inventory"][tf] = inv
        print(f"  {tf:>4} {inv['years_total']:>3} yr  up {inv['years_up']:>2} / down "
              f"{inv['years_down']:>2}   bars in down years {inv['pct_bars_in_down_years']:>5.1f}%"
              f"   net {inv['net_pct_full']:+8.1f}%   down: {inv['down_years']}")

    # ---- cost sensitivity to the spread assumption ------------------------
    print("\n" + "=" * 104)
    print("COST SENSITIVITY -- the $0.33 spread was measured in 2025-26; older eras were wider")
    print("=" * 104)
    sens = {}
    for mult, lbl in ((1.0, "as measured"), (2.0, "2x"), (4.0, "4x")):
        row = {}
        for key, r in results["horizon_table"].items():
            cost = (SPREAD_USD * mult) / r["sd_dollars"]
            n_min = (z30 / cost) ** 2
            row[key] = {"cost_in_sd": round(cost, 5), "min_events": int(np.ceil(n_min)),
                        "feasible": bool(n_min <= r["independent_obs"])}
        sens[lbl] = row
        feas = sum(1 for v in row.values() if v["feasible"])
        print(f"  spread x{mult:<4.1f} ({lbl:<11}) -> {feas} of {len(row)} combinations feasible at full history")
    results["cost_sensitivity"] = sens

    # ---- validate the retention model against observed hypotheses ---------
    print("\n" + "=" * 104)
    print("RETENTION MODEL VALIDATION -- modelled vs observed in the committed hypotheses")
    print("=" * 104)
    for lbl, raw_n, obs_n, h in OBSERVED_RETENTION:
        n_bars = 50010
        modelled = measure_retention(n_bars, raw_n / n_bars, h)
        results["retention_validation"][lbl] = {
            "raw": raw_n, "observed_non_overlapping": obs_n,
            "observed_retention": round(obs_n / raw_n, 4),
            "modelled_retention": round(modelled, 4)}
        print(f"  {lbl:<28} raw {raw_n:>5,} -> obs {obs_n:>5,} "
              f"({100*obs_n/raw_n:5.1f}%)   modelled {100*modelled:5.1f}%")
    print("  Model UNDER-estimates retention in 5 of 6 cases: the hypotheses enforce event")
    print("  spacing in deduplication, making real events more regular than random. The model")
    print("  is therefore conservative -- it over-states MDE and sets a slightly strict GO bar.")

    # ---- go / no-go -------------------------------------------------------
    print("\n" + "=" * 104)
    print("GO / NO-GO -- every future hypothesis must cite a row from here")
    print("=" * 104)
    for key, r in sorted(results["horizon_table"].items(),
                         key=lambda kv: -kv[1].get("headroom_x", 0)):
        go = r["feasible_at_full_history"]
        results["go_no_go"].append({
            "combination": key, "horizon_hours": r["horizon_hours"],
            "timeframe": r["timeframe"], "independent_obs": r["independent_obs"],
            "cost_in_sd": r["cost_in_sd"],
            "mde_in_sd_accumulated_30": r["mde_in_sd_accumulated_30"],
            "headroom_x": r.get("headroom_x"),
            "min_events_needed": r["min_events_needed"],
            "min_event_rate": r["min_event_rate"], "GO": bool(go)})
        print(f"  {key:>10}  {'GO ' if go else 'NO '}  headroom {r.get('headroom_x', 0):>6.2f}x"
              f"   needs >= {r['min_events_needed']:>7,} events "
              f"(rate >= {r['min_event_rate']:.4f})   has {r['independent_obs']:>8,}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "viability_results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\n  wrote {out_dir/'viability_results.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    run(Path(ap.parse_args().out))
