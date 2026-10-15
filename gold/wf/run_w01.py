"""W01 results, exactly as pre-registered in research/v2026/W01_SPEC.md (commit 4d48091).

Writes research/v2026/w01_results.json and W01_REPORT.md; trades and each variant's daily net R series
(1x and 2x cost, by exit session) go to gitignored data/w01/.

    venv\\Scripts\\python.exe -m gold.wf.run_w01
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from gold.data.broker_daily import session_of
from gold.data.build_broker_v1b import FINGERPRINTS
from gold.data.store import REPO
from gold.wf import bars as BR
from gold.wf import menu as M
from gold.wf import select as S
from psx.strategy.results_h_psx01 import cagr, max_drawdown, mean_test

OUT_DIR = REPO / "data" / "w01"
OUT_JSON = REPO / "research" / "v2026" / "w01_results.json"
OUT_MD = REPO / "research" / "v2026" / "W01_REPORT.md"
ALPHA = 0.05
ERAS = (("2011–2015", "2011-01", "2015-12"), ("2016–2020", "2016-01", "2020-12"), ("2021 → 2026-09", "2021-01", "2026-09"))


def era_means(months: pd.PeriodIndex, r) -> list[dict]:
    x = pd.Series(np.asarray(r, float), index=months)
    out = []
    for name, a, b in ERAS:
        e = x[(x.index >= pd.Period(a, "M")) & (x.index <= pd.Period(b, "M"))]
        out.append({"era": name, "months": len(e), "mean": float(e.mean()), "sum": float(e.sum())})
    return out


def main() -> int:
    B = BR.load()
    dff = BR.load_dff()
    k_cost = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["cost_calibration"]["k_cost"]
    variants = M.menu()
    tr = pd.concat([M.trades(B, v) for v in variants], ignore_index=True)
    tr["r1"] = M.net_r(tr, B, dff, k_cost, 1.0)
    tr["r2"] = M.net_r(tr, B, dff, k_cost, 2.0)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tr.to_parquet(OUT_DIR / "trades.parquet", index=False)
    daily = tr.assign(session=session_of(tr["exit_time"])).groupby(["vid", "session"])[["r1", "r2"]].sum().reset_index()
    daily.to_parquet(OUT_DIR / "daily_net_r.parquet", index=False)

    months = pd.period_range(S.FIRST_MONTH, S.LAST_MONTH, freq="M")
    vids = [v.vid for v in variants]
    run = lambda lb, top, col: S.walk(tr.assign(r=tr[col]), vids, months, lb, top)
    p1, elig = run(S.LOOKBACK, 1, "r1")
    p2, _ = run(S.LOOKBACK, 1, "r2")
    R1 = S.monthly_r(tr.assign(r=tr["r1"]), vids, months)
    paths = S.random_control(R1, elig)

    prim = mean_test(p1["r"])
    ic = p1["ic"].dropna()
    ic_test = mean_test(ic)
    eras = era_means(months, p1["r"])
    p95 = float(np.percentile(paths, 95))
    pct = float(100 * ((paths < prim["mean"]).mean() + 0.5 * (paths == prim["mean"]).mean()))
    tests = {"1_mean_1x_gt0_p_lt_0.05": prim["mean"] > 0 and prim["p_one_sided"] < ALPHA,
             "2_mean_2x_ge0": float(p2["r"].mean()) >= 0,
             "3_above_random_p95": prim["mean"] > p95,
             "4_mean_ic_gt0_p_lt_0.05": ic_test["mean"] > 0 and ic_test["p_one_sided"] < ALPHA,
             "5_positive_in_2_of_3_eras": sum(e["mean"] > 0 for e in eras) >= 2}
    verdict = "WORKS" if all(tests.values()) else "DOES NOT WORK"

    names = {v.vid: v for v in variants}
    fam = pd.Series([names[c[0]].family for c in p1["chosen"] if c]).value_counts()
    info = {}
    for lb in (3, 12):
        q, _ = run(lb, 1, "r1")
        info[f"lookback_{lb}"] = mean_test(q["r"])
    q3, _ = run(S.LOOKBACK, 3, "r1")
    info["top3_equal_weight"] = mean_test(q3["r"])
    ev = tr[(S.entry_month(tr) >= months[0]) & (S.entry_month(tr) <= months[-1])]
    g = ev.groupby("vid")["r1"]
    hind = pd.DataFrame({"trades": g.count(), "total_r": g.sum(), "mean_r_trade": g.mean(),
                         "t": g.mean() / (g.std(ddof=1) / np.sqrt(g.count()))}).sort_values("total_r", ascending=False)
    info["hindsight_top10"] = [{"variant": names[int(v)].name, "family": names[int(v)].family, **{k: float(x) for k, x in row.items()}}
                               for v, row in hind.head(10).iterrows()]
    d1 = B.d1.assign(m=pd.PeriodIndex(B.d1["session"], freq="M"))
    me = d1.groupby("m")["close"].last()
    gold = (me / me.shift(1) - 1).reindex(months)
    info["buy_and_hold_gold"] = {"cagr": cagr(gold), "max_drawdown": max_drawdown(gold), "months": int(gold.notna().sum())}
    info["cash"] = {"mean_monthly_r": 0.0}
    info["family_chosen_months"] = {k: int(v) for k, v in fam.items()}
    info["months_without_eligible_variant"] = int((p1["n_eligible"] == 0).sum())
    info["trades_per_variant"] = {"min": int(tr.groupby("vid").size().reindex(vids, fill_value=0).min()),
                                  "median": float(tr.groupby("vid").size().median()), "total": int(len(tr))}

    res = {"spec": "research/v2026/W01_SPEC.md @ 4d48091", "k_cost": k_cost, "variants": len(variants),
           "months": [str(months[0]), str(months[-1]), len(months)], "verdict": verdict, "tests": tests,
           "process_1x": prim, "process_2x_mean": float(p2["r"].mean()),
           "random_control": {"paths": S.N_PATHS, "seed": S.SEED, "p95": p95, "median": float(np.median(paths)),
                              "process_percentile": pct},
           "ic": {**ic_test, "months": int(len(ic)), "share_positive": float((ic > 0).mean())},
           "eras": eras, "informational": info}
    OUT_JSON.write_text(json.dumps(res, indent=1, default=float) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(res), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("verdict", "tests", "process_1x", "process_2x_mean", "random_control", "ic", "eras")},
                     indent=1, default=float))
    return 0


def render(r: dict) -> str:
    p, rc, ic, inf, t = r["process_1x"], r["random_control"], r["ic"], r["informational"], r["tests"]
    f2 = lambda x: f"{x:+.3f}"
    pf = lambda b: "PASS" if b else "FAIL"
    L = ["# W01 — walk-forward selection on XAUUSD: does the setup that works now keep working? — report", "",
         "Spec: `research/v2026/W01_SPEC.md` at commit `4d48091` · Code: `gold/wf/` · Script: `gold/wf/run_w01.py` · "
         "Numbers: `research/v2026/w01_results.json` · Max 120 lines.", "",
         "## Verdict",
         f"**{r['verdict']}** — choosing each month the variant with the best 6-month t-statistic earned "
         f"{f2(p['mean'])} R a month net at 1× cost (Newey–West t = {p['t']:.2f}, one-sided p = {p['p_one_sided']:.3f}), "
         f"{rc['process_percentile']:.0f}th percentile of 2,000 random-pick paths; mean IC {f2(ic['mean'])} "
         f"(t = {ic['t']:.2f}). {sum(t.values())} of 5 pre-declared tests pass.", "",
         "## Pre-declared results",
         f"{r['variants']} variants, {r['months'][2]} months {r['months'][0]} → {r['months'][1]}, net R per month "
         f"(k_cost {r['k_cost']}, financing past 17:00 New York).", "",
         "| # | Test | Estimate | SE | t | p (one-sided) | Threshold | Result |", "|---|---|---|---|---|---|---|---|",
         f"| 1 | Process mean net R / month, 1× | {f2(p['mean'])} | {p['se']:.3f} | {p['t']:.2f} | {p['p_one_sided']:.3f} | > 0, p < 0.05 | {pf(t['1_mean_1x_gt0_p_lt_0.05'])} |",
         f"| 2 | Process mean net R / month, 2× | {f2(r['process_2x_mean'])} | | | | ≥ 0 | {pf(t['2_mean_2x_ge0'])} |",
         f"| 3 | Process vs random control (95th pct {f2(rc['p95'])}) | {rc['process_percentile']:.1f} pct | | | | > 95th | {pf(t['3_above_random_p95'])} |",
         f"| 4 | Mean IC ({ic['months']} months, {100 * ic['share_positive']:.0f} % positive) | {f2(ic['mean'])} | {ic['se']:.3f} | "
         f"{ic['t']:.2f} | {ic['p_one_sided']:.3f} | > 0, p < 0.05 | {pf(t['4_mean_ic_gt0_p_lt_0.05'])} |",
         f"| 5 | Eras with a positive process mean | {sum(e['mean'] > 0 for e in r['eras'])} of 3 | | | | ≥ 2 | {pf(t['5_positive_in_2_of_3_eras'])} |", "",
         "## Controls",
         "| Process vs random control | Mean net R / month |", "|---|---|",
         f"| Walk-forward process (top-1, 6 months) | {f2(p['mean'])} |",
         f"| Random eligible variant, median of 2,000 paths | {f2(rc['median'])} |",
         f"| Random eligible variant, 95th percentile | {f2(rc['p95'])} |", "",
         "Ranking does carry information (tests 3 and 4), but mostly about losers: variants that trade often pay "
         "costs every month and stay at the bottom, so the top-ranked variant is the mildest loser, not a winner.", "",
         "| Era | Months | Process mean net R / month | Sum |", "|---|---|---|---|"]
    L += [f"| {e['era']} | {e['months']} | {f2(e['mean'])} | {e['sum']:+.1f} |" for e in r["eras"]]
    L += ["", "| Family chosen | Months |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in inf["family_chosen_months"].items()]
    if inf["months_without_eligible_variant"]:
        L.append(f"| (no eligible variant: cash) | {inf['months_without_eligible_variant']} |")
    L += ["", "## Informational only — no verdict weight",
          f"- Lookback 3 months: {f2(inf['lookback_3']['mean'])} R / month (t = {inf['lookback_3']['t']:.2f}); "
          f"12 months: {f2(inf['lookback_12']['mean'])} (t = {inf['lookback_12']['t']:.2f}); top-3 equal weight (6 months): "
          f"{f2(inf['top3_equal_weight']['mean'])} (t = {inf['top3_equal_weight']['t']:.2f}).",
          f"- Buy-and-hold gold (D1 closes, same months): CAGR {100 * inf['buy_and_hold_gold']['cagr']:+.1f} %, max drawdown "
          f"{100 * inf['buy_and_hold_gold']['max_drawdown']:.1f} %; cash 0. Not comparable in R units.",
          f"- Trades: {inf['trades_per_variant']['total']:,} in total; per variant median {inf['trades_per_variant']['median']:.0f}, "
          f"minimum {inf['trades_per_variant']['min']}.", "",
          "**Hindsight only — not tradable, chosen after the fact.** The 10 variants with the largest total net R "
          f"(1×) over {r['months'][0]} → {r['months'][1]}:", "",
          "| Variant | Family | Trades | Total R | Mean R / trade | t |", "|---|---|---|---|---|---|"]
    L += [f"| {h['variant']} | {h['family']} | {h['trades']:.0f} | {h['total_r']:+.1f} | {h['mean_r_trade']:+.3f} | {h['t']:.2f} |"
          for h in inf["hindsight_top10"]]
    L += ["", "The leaders are long D1 trend rules, which largely carry gold's rise over the period; picked after the "
              "fact from 102 variants, their t-statistics (at most 2.3) are within what chance alone produces.", "",
          "## Limitations",
          "- FINAL_OOS was opened for exploration (2026-10-14), so no period here is a clean holdout; only a forward "
          "demo test could validate a WORKS result.",
          "- Bid-based H1 bars; costs are modelled from bar spreads × k_cost 4.625 (one week of ticks, 2026), not measured "
          "fills; intrabar order is assumed stop-first.",
          "- The menu is the owner's list with fixed parameters; other rules or parameters could behave differently.",
          "- Months are UTC entry months; a selected variant's trades are held to their exits, so risk can overlap "
          "month boundaries.",
          "- Monthly net R sums trades of different counts per variant: high-frequency variants (time of day, H1 "
          "rules) dominate both scores and outcomes.", "",
          "## Changes", "- (none)"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
