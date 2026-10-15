"""H-PSX-01 blinded power check -> research/psx/power_h_psx01.json and POWER_H_PSX01.md.

BLINDED: no mean of any strategy, portfolio, universe or index return, and no cumulative or annualised
return, Sharpe, CAGR or hit rate, is computed, printed or written. Only counts, standard deviations,
autocorrelations, turnover and costs; second moments come from psx.strategy.blind (differences only).

    venv\\Scripts\\python.exe -m psx.strategy.power_h_psx01
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from psx.data.audit import DERIVED, REPO
from psx.data.download import INDEX
from psx.strategy import blind
from psx.strategy import h_psx01 as h

OUT_JSON = REPO / "research" / "psx" / "power_h_psx01.json"
OUT_MD = REPO / "research" / "psx" / "POWER_H_PSX01.md"
FINGERPRINTS = REPO / "research" / "psx" / "psx_fingerprints.json"
E_REF = 0.006                         # 0.60 % a month net (Shah & Shah ~0.8 % long-only gross - ~0.2 % costs)
NW_LAGS = 3
KSE_FROM = pd.Period("2016-11", "M")  # first holding month inside the KSE-100 history
SMALL_UNIVERSE = 60


def q(x, p) -> float:
    return float(np.quantile(np.asarray(x, dtype=float), p))


def main() -> int:
    P, info = h.load_panel()
    plans_w, plans_b, spreads, rows = [], [], [], []
    for plan in h.schedule(P.days):
        u, sig = h.universe(P, plan.t_pos)
        w = h.winners(u, sig)
        plans_b.append(h.MonthPlan(plan.month, plan.t_pos, plan.exec_pos, plan.next_pos, u))
        plans_w.append(h.MonthPlan(plan.month, plan.t_pos, plan.exec_pos, plan.next_pos, w))
        spreads += [h.spread(P, plan.t_pos, i) for i in u]
        rows.append({"year": plan.month.year, "n": len(u), "k": len(w)})
    W, B = h.simulate(P, plans_w), h.simulate(P, plans_b)
    excess = W["ret_net"].to_numpy() - B["ret_net"].to_numpy()

    hist = pd.read_parquet(DERIVED / "histories.parquet")
    kse = hist[hist["symbol"] == INDEX].set_index("date")["close"]
    ret_kse = [kse[P.days[p.next_pos]] / kse[P.days[p.exec_pos]] - 1 for p in plans_b if p.month >= KSE_FROM]

    sizes = pd.DataFrame(rows)
    by_year = {int(y): {"universe_median": int(g["n"].median()), "universe_min": int(g["n"].min()),
                        "universe_max": int(g["n"].max()), "winners_median": int(g["k"].median())}
               for y, g in sizes.groupby("year")}
    counts = {"months": len(plans_b), "months_universe_below_60": int((sizes["n"] < SMALL_UNIVERSE).sum())}
    for name, R in (("winners", W), ("benchmark", B)):
        for c in ("unfilled_locked_buys", "unfilled_locked_new", "unfilled_no_close", "locked_sells", "sells_no_close",
                  "delistings", "zero_volume_fills"):
            counts[f"{name}_{c}"] = int(R[c].sum())
    res = {
        "note": "BLINDED power check: counts, standard deviations, autocorrelations, turnover and costs only",
        "data_all_files_sha256": json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["all_files_sha256"],
        "panel": info,
        "holding_months": [str(plans_b[0].month), str(plans_b[-1].month)],
        "by_year": by_year,
        "universe_size_range": [int(sizes["n"].min()), int(sizes["n"].max())],
        "turnover_one_way": {k: {"median": float(np.median(R["turnover"])), "p90": q(R["turnover"], 0.9)}
                             for k, R in (("winners", W), ("benchmark", B))},
        "spread_full_universe": {"median": q(spreads, 0.5), "p90": q(spreads, 0.9), "n": len(spreads)},
        "cost_per_month_1x_median": {"winners": float(np.median(W["cost"])), "benchmark": float(np.median(B["cost"])),
                                     "excess": float(np.median(W["cost"] - B["cost"]))},
        "counts": counts,
        "dispersion_1x": {"sd_excess": blind.sd(excess), "ac1_excess": blind.autocorr(excess, 1),
                          "sd_winners": blind.sd(W["ret_net"]), "sd_benchmark": blind.sd(B["ret_net"]),
                          "sd_kse100": blind.sd(ret_kse), "kse100_months": len(ret_kse)},
        "power": {"n": len(excess), "nw_lags": NW_LAGS, "z_alpha": blind.Z_ALPHA, "z_power": blind.Z_POWER,
                  **blind.power_summary(blind.nw_se(excess, NW_LAGS), E_REF)},
    }
    OUT_JSON.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(res), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("universe_size_range", "cost_per_month_1x_median", "power")}, indent=1))
    return 0


def render(r: dict) -> str:
    pct = lambda x: f"{100 * x:.2f} %"
    yrs = sorted(r["by_year"])
    by = r["by_year"]
    c, d, pw, t = r["counts"], r["dispersion_1x"], r["power"], r["turnover_one_way"]
    L = [f"# H-PSX-01 — blinded power check: **{pw['verdict']}**", "",
         "Script `psx/strategy/power_h_psx01.py` · numbers `research/psx/power_h_psx01.json` · blinded: no mean, "
         "cumulative or annualised return, Sharpe, CAGR or hit rate computed. Max 30 lines.", "",
         "| Year | " + " | ".join(str(y)[2:] for y in yrs) + " |", "|---|" + "---|" * len(yrs),
         "| Universe (median; min–max) | " + " | ".join(f"{by[y]['universe_median']} ({by[y]['universe_min']}–{by[y]['universe_max']})" for y in yrs) + " |",
         "| Winners (median) | " + " | ".join(str(by[y]["winners_median"]) for y in yrs) + " |", "",
         "| Turnover and costs (monthly) | Winners | Benchmark | Excess |", "|---|---|---|---|",
         f"| One-way turnover, median / p90 | {pct(t['winners']['median'])} / {pct(t['winners']['p90'])} | "
         f"{pct(t['benchmark']['median'])} / {pct(t['benchmark']['p90'])} | |",
         f"| Cost per month at 1×, median | {pct(r['cost_per_month_1x_median']['winners'])} | "
         f"{pct(r['cost_per_month_1x_median']['benchmark'])} | {pct(r['cost_per_month_1x_median']['excess'])} |",
         f"| Full spread in the universe (Abdi–Ranaldo), median / p90 | {pct(r['spread_full_universe']['median'])} / "
         f"{pct(r['spread_full_universe']['p90'])} | | |", "",
         f"**Counts.** {c['months']} months; universe below 60 names in {c['months_universe_below_60']}. Unfilled buys locked "
         f"at the upper limit: winners {c['winners_unfilled_locked_buys']} (new entries {c['winners_unfilled_locked_new']}), "
         f"benchmark {c['benchmark_unfilled_locked_buys']} ({c['benchmark_unfilled_locked_new']}). No close on the execution "
         f"day (slot stays in cash): {c['winners_unfilled_no_close']} / {c['benchmark_unfilled_no_close']}. Sells deferred, locked at "
         f"the lower limit: {c['winners_locked_sells']} / {c['benchmark_locked_sells']}; no close: {c['winners_sells_no_close']} / "
         f"{c['benchmark_sells_no_close']}. Delisting events among holdings: winners "
         f"{c['winners_delistings']}, benchmark {c['benchmark_delistings']}.", "",
         f"**Dispersion (net, 1× cost, monthly).** sd of the excess {pct(d['sd_excess'])}, lag-1 autocorrelation "
         f"{d['ac1_excess']:.2f}; sd winners {pct(d['sd_winners'])}, benchmark {pct(d['sd_benchmark'])}, KSE-100 "
         f"{pct(d['sd_kse100'])} ({d['kse100_months']} months from 2016-11).", "",
         f"**Power (n = {pw['n']}).** Newey–West ({pw['nw_lags']} lags) SE of the mean excess {pct(pw['se'])}; "
         f"MDE = ({pw['z_alpha']} + {pw['z_power']}) × SE = **{pct(pw['mde'])}** a month vs E_ref {pct(pw['e_ref'])} "
         f"(MDE / E_ref = **{pw['mde_over_e_ref']:.2f}**); power at E_ref {100 * pw['power_at_e_ref']:.0f} %. "
         f"Verdict: **{pw['verdict']}** (TESTABLE if MDE ≤ E_ref).", "",
         "E_ref = 0.60 % a month net: Shah & Shah (2018) report about 20 % a year long–short gross (2004–2014), about "
         "0.8 % a month long-only gross, less about 0.2 % a month of costs.",
         ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
