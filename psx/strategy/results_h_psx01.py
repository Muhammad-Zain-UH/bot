"""H-PSX-01 results, exactly as pre-registered: research/psx/H_PSX01_SPEC.md (521cfde), construction
psx/strategy/h_psx01.py (07b9e3f). Writes research/psx/h_psx01_results.json (summary numbers) and
research/psx/H_PSX01_REPORT.md; the monthly series go to gitignored data/psx/derived/h_psx01_monthly.parquet.

    venv\\Scripts\\python.exe -m psx.strategy.results_h_psx01
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

from psx.data.audit import DERIVED, REPO
from psx.data.download import INDEX
from psx.strategy import h_psx01 as h

OUT_JSON = REPO / "research" / "psx" / "h_psx01_results.json"
OUT_MD = REPO / "research" / "psx" / "H_PSX01_REPORT.md"
MONTHLY = DERIVED / "h_psx01_monthly.parquet"
ALPHA = 0.05 / 3
NW_LAGS = 3
ERA_CAP = 0.60
ERAS = (("2015–2018", "2015-01", "2018-12"), ("2019–2022", "2019-01", "2022-12"), ("2023 → 2026-09", "2023-01", "2026-09"))
TOP_SMALL = 60
KSE_FROM = pd.Period("2016-11", "M")
CGT = 0.15


# ---------------------------------------------------------------- statistics
def nw_se(x, lags: int = NW_LAGS) -> float:
    """Newey-West (Bartlett) standard error of the mean, demeaned 1/n autocovariances."""
    x = np.asarray(x, dtype=float)
    d = x - x.mean()
    n = len(x)
    s = d @ d / n + 2 * sum((1 - k / (lags + 1)) * (d[k:] @ d[:-k]) / n for k in range(1, lags + 1))
    return math.sqrt(max(s, 0.0) / n)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h_ = d
    for m in range(1, 500):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h_ *= d * c
        if abs(d * c - 1) < 3e-15:
            break
    return h_


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student-t with df degrees of freedom."""
    tail = 0.5 * betainc(df / 2, 0.5, df / (df + t * t))
    return tail if t >= 0 else 1 - tail


def mean_test(x) -> dict:
    """Mean, NW(3) SE, one-sided t and p (Student-t, n - 1 df) for H1: mean > 0."""
    x = np.asarray(x, dtype=float)
    se = nw_se(x)
    t = float(x.mean() / se)
    return {"n": len(x), "mean": float(x.mean()), "se": se, "t": t, "p_one_sided": t_sf(t, len(x) - 1)}


def sharpe_lo(x, lags: int = NW_LAGS, q: int = 12) -> dict:
    """Lo (2002): monthly Sharpe with a GMM / Newey-West(lags) standard error (delta method), annualised by
    eta(q) = q / sqrt(q + 2 sum_k (q - k) rho_k) with rho_1..rho_lags (eta treated as fixed for the SE)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    mu = x.mean()
    d = x - mu
    var = d @ d / n
    sdv = math.sqrt(var)
    g = np.column_stack([d, d * d - var])
    S = g.T @ g / n
    for k in range(1, lags + 1):
        G = g[k:].T @ g[:-k] / n
        S += (1 - k / (lags + 1)) * (G + G.T)
    grad = np.array([1 / sdv, -mu / (2 * sdv ** 3)])
    se_m = math.sqrt(float(grad @ S @ grad) / n)
    rho = [float(d[k:] @ d[:-k] / n / var) for k in range(1, min(lags, q - 1) + 1)]
    eta = q / math.sqrt(q + 2 * sum((q - k) * r for k, r in enumerate(rho, start=1)))
    return {"sharpe_monthly": mu / sdv, "se_monthly": se_m, "eta": eta, "sharpe_annual": eta * mu / sdv,
            "se_annual": eta * se_m, "rho": rho}


def era_table(months: pd.PeriodIndex, x) -> list[dict]:
    x = pd.Series(np.asarray(x, dtype=float), index=months)
    total = float(x.sum())
    out = []
    for name, a, b in ERAS:
        e = x[(x.index >= pd.Period(a, "M")) & (x.index <= pd.Period(b, "M"))]
        out.append({"era": name, "months": len(e), "mean": float(e.mean()), "sum": float(e.sum()),
                    "share_of_total": float(e.sum() / total) if total != 0 else float("nan")})
    return out


def robustness(mean_2x: float, mean_d30: float, eras: list[dict]) -> dict:
    total = sum(e["sum"] for e in eras)
    return {"cost_2x_mean_ge_0": mean_2x >= 0, "delist_30_mean_gt_0": mean_d30 > 0,
            "positive_in_2_of_3_eras": sum(e["mean"] > 0 for e in eras) >= 2,
            "no_era_over_60pct": total > 0 and max(e["share_of_total"] for e in eras) <= ERA_CAP}


def verdict(p: float, mean: float, checks: dict) -> str:
    """Spec section 7, mechanically."""
    ok = all(checks.values())
    if ok and p < ALPHA:
        return "SUPPORTED"
    if ok and mean > 0:
        return "WEAK SUPPORT"
    return "NOT SUPPORTED"


def wealth(r) -> np.ndarray:
    return np.concatenate([[1.0], np.cumprod(1 + np.asarray(r, dtype=float))])


def cagr(r) -> float:
    return float(wealth(r)[-1] ** (12 / len(r)) - 1)


def max_drawdown(r) -> float:
    w = wealth(r)
    return float((1 - w / np.maximum.accumulate(w)).max())


# ---------------------------------------------------------------- realised gains (informational after-tax)
def simulate_basis(P: h.Panel, plans: list[h.MonthPlan], cost_mult: float = 1.0) -> pd.DataFrame:
    """h.simulate with cost-basis tracking: realised net gain per month (sale proceeds after costs minus the
    cost-inclusive basis sold). Its ret_net must equal h.simulate's; main() asserts it."""
    pos: dict[int, float] = {}
    basis: dict[int, float] = {}
    cash = 1.0
    pending: dict[int, float] = {}
    last_day = len(P.days) - 1
    rate = lambda i, p: h.cost_rate(P.close[p, i], h.spread(P, p, i), cost_mult)

    def sell(i: int, amt: float, c: float) -> float:
        b = basis[i] * amt / pos[i]
        basis[i] -= b
        pos[i] -= amt
        return amt - c - b

    out = []
    for plan in plans:
        e = plan.exec_pos
        value = sum(pos.values()) + cash
        realised = 0.0
        slot = value / len(plan.targets) if len(plan.targets) else 0.0
        targets = set(int(i) for i in plan.targets)
        pending.clear()
        for i in sorted(pos):
            want = slot if i in targets else 0.0
            cur = pos[i]
            if cur - want <= 1e-12 * value:
                continue
            if P.has_row[e, i] and not h.locked(P, e, i, "down"):
                amt = cur - want
                c = amt * rate(i, e)
                cash += amt - c
                realised += sell(i, amt, c)
                if want == 0.0:
                    del pos[i], basis[i]
            else:
                pending[i] = (cur - want) / cur
        buys = {}
        for i in sorted(targets):
            need = slot - pos.get(i, 0.0)
            if need <= 1e-9 * slot or not P.has_row[e, i] or h.locked(P, e, i, "up"):
                continue
            buys[i] = need
        spend = sum(n * (1 + rate(i, e)) for i, n in buys.items())
        scale = min(1.0, max(cash, 0.0) / spend) if spend > 0 else 1.0
        for i, n in buys.items():
            amt = n * scale
            c = amt * rate(i, e)
            cash -= amt + c
            pos[i] = pos.get(i, 0.0) + amt
            basis[i] = basis.get(i, 0.0) + amt + c
        for d in range(e + 1, plan.next_pos + 1):
            for i in list(pos):
                if P.last_pos[i] < d and P.last_pos[i] < last_day:
                    proceeds = pos.pop(i)
                    cash += proceeds
                    realised += proceeds - basis.pop(i)
                    pending.pop(i, None)
                else:
                    pos[i] *= P.adj[d, i] / P.adj[d - 1, i]
            for i in list(pending):
                if i in pos and P.has_row[d, i] and not h.locked(P, d, i, "down"):
                    amt = pos[i] * pending.pop(i)
                    c = amt * rate(i, d)
                    cash += amt - c
                    realised += sell(i, amt, c)
                    if pos[i] <= 1e-15:
                        del pos[i], basis[i]
        out.append({"month": str(plan.month), "ret_net": (sum(pos.values()) + cash) / value - 1,
                    "realised": realised, "value_start": value})
    return pd.DataFrame(out)


def after_tax_by_year(sb: pd.DataFrame) -> list[dict]:
    """Per calendar year: pre-tax return, 15 % CGT on the year's positive realised net gains as a share of the
    value at the year's first execution, after-tax return (tax paid at year end)."""
    sb = sb.assign(year=pd.PeriodIndex(sb["month"], freq="M").year)
    out = []
    for y, g in sb.groupby("year"):
        pre = float(np.prod(1 + g["ret_net"]) - 1)
        drag = CGT * max(float(g["realised"].sum()), 0.0) / float(g["value_start"].iloc[0])
        out.append({"year": int(y), "months": len(g), "pre_tax": pre, "tax_drag": drag, "after_tax": pre - drag})
    return out


# ---------------------------------------------------------------- run
def run_pair(P, plans_w, plans_b, **kw) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    W, B = h.simulate(P, plans_w, **kw), h.simulate(P, plans_b, **kw)
    return W, B, W["ret_net"].to_numpy() - B["ret_net"].to_numpy()


def main() -> int:
    P, info = h.load_panel()
    sched = h.schedule(P.days)
    plans = {"w": [], "b": [], "w60": [], "b60": []}
    for s in sched:
        u, sig = h.universe(P, s.t_pos)
        u60, _ = h.universe(P, s.t_pos, top_n=TOP_SMALL)
        for key, tg in (("w", h.winners(u, sig)), ("b", u), ("w60", h.winners(u60, sig)), ("b60", u60)):
            plans[key].append(h.MonthPlan(s.month, s.t_pos, s.exec_pos, s.next_pos, tg))
    months = pd.PeriodIndex([s.month for s in sched], freq="M")
    W1, B1, x1 = run_pair(P, plans["w"], plans["b"])
    _, _, x2 = run_pair(P, plans["w"], plans["b"], cost_mult=2.0)
    W0, B0, x0 = run_pair(P, plans["w"], plans["b"], cost_mult=0.0)
    _, _, xd = run_pair(P, plans["w"], plans["b"], haircut=h.DELIST_HAIRCUT)
    W60, B60, x60 = run_pair(P, plans["w60"], plans["b60"])
    sb = simulate_basis(P, plans["w"])
    if not np.allclose(sb["ret_net"].to_numpy(), W1["ret_net"].to_numpy(), rtol=0, atol=1e-12):
        raise AssertionError("basis replica diverges from h.simulate")

    hist = pd.read_parquet(DERIVED / "histories.parquet")
    kse = hist[hist["symbol"] == INDEX].set_index("date")["close"]
    ret_kse = pd.Series([kse[P.days[s.next_pos]] / kse[P.days[s.exec_pos]] - 1 if s.month >= KSE_FROM else np.nan
                         for s in sched], index=months)
    k = months >= KSE_FROM

    monthly = pd.DataFrame({"month": months.astype(str), "ret_net_winners": W1["ret_net"], "ret_net_benchmark": B1["ret_net"],
                            "excess_1x": x1, "excess_2x": x2, "excess_0x": x0, "excess_delist30": xd,
                            "excess_top60": x60, "ret_kse100": ret_kse.to_numpy(), "cost_winners": W1["cost"],
                            "cost_benchmark": B1["cost"]})
    monthly.to_parquet(MONTHLY, index=False)

    prim = mean_test(x1)
    eras = era_table(months, x1)
    checks = robustness(float(x2.mean()), float(xd.mean()), eras)
    v = verdict(prim["p_one_sided"], prim["mean"], checks)
    years = pd.Series(x1, index=months).groupby(months.year)
    perf = lambda r: {"cagr": cagr(r), "max_drawdown": max_drawdown(r), "months": len(r)}
    res = {
        "spec": "research/psx/H_PSX01_SPEC.md @ 521cfde", "construction": "psx/strategy/h_psx01.py @ 07b9e3f",
        "panel": info, "holding_months": [str(months[0]), str(months[-1])],
        "verdict": v, "primary": prim, "alpha_one_sided": ALPHA,
        "robustness": {"mean_excess_2x": float(x2.mean()), "mean_excess_delist30": float(xd.mean()), "eras": eras,
                       "checks": checks},
        "sharpe_excess_lo2002": sharpe_lo(x1),
        "informational": {
            "gross_excess_0x": mean_test(x0),
            "excess_by_year": {int(y): {"months": len(g), "mean": float(g.mean()), "sum": float(g.sum())} for y, g in years},
            "top60": mean_test(x60),
            "winners_minus_kse100_from_2016_11": mean_test(W1["ret_net"].to_numpy()[k] - ret_kse.to_numpy()[k]),
            "after_tax_winners_by_year": after_tax_by_year(sb),
            "performance_full": {"winners": perf(W1["ret_net"]), "benchmark": perf(B1["ret_net"])},
            "performance_from_2016_11": {"winners": perf(W1["ret_net"][k]), "benchmark": perf(B1["ret_net"][k]),
                                         "kse100": perf(ret_kse[k])},
            "median_cost_per_month_1x": {"winners": float(W1["cost"].median()), "benchmark": float(B1["cost"].median())},
        },
    }
    at = res["informational"]["after_tax_winners_by_year"]
    res["informational"]["after_tax_winners_cagr"] = float(np.prod([1 + a["after_tax"] for a in at])
                                                           ** (12 / sum(a["months"] for a in at)) - 1)
    OUT_JSON.write_text(json.dumps(res, indent=1, default=float) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(res), encoding="utf-8")
    print(json.dumps({"verdict": v, "primary": prim, "checks": checks}, indent=1))
    return 0


def render(r: dict) -> str:
    pct = lambda x: f"{100 * x:+.2f} %"
    upct = lambda x: f"{100 * x:.2f} %"
    pf = lambda b: "PASS" if b else "FAIL"
    p, rb, inf, sh = r["primary"], r["robustness"], r["informational"], r["sharpe_excess_lo2002"]
    ch = rb["checks"]
    L = ["# H-PSX-01 — PSX 12–1 month momentum winners vs the equal-weight liquid universe — report", "",
         "Spec: `research/psx/H_PSX01_SPEC.md` at commit `521cfde` · Construction: `psx/strategy/h_psx01.py` at `07b9e3f` · "
         "Script: `psx/strategy/results_h_psx01.py` · Numbers: `research/psx/h_psx01_results.json` · Max 120 lines.", "",
         "## Verdict",
         f"**{r['verdict']}** — mean monthly net excess of winners over the equal-weight universe at 1× cost "
         f"{pct(p['mean'])} (Newey–West t = {p['t']:.2f}, one-sided p = {p['p_one_sided']:.4f} vs α = 0.0167), "
         f"{p['n']} months {r['holding_months'][0]} → {r['holding_months'][1]}. Robustness: {sum(ch.values())} of "
         f"{len(ch)} pass" + ("" if all(ch.values()) else " (failed: " + ", ".join(n for n, ok in ch.items() if not ok)
                              + "; spec §7 then rules out WEAK SUPPORT too)") + ".", "",
         "## Pre-declared results",
         "| # | Test | Period | n | Estimate (per month) | SE | t | p (one-sided) | Threshold | Result |",
         "|---|---|---|---|---|---|---|---|---|---|",
         f"| 1 | Mean net excess, 1× cost | {r['holding_months'][0]} → {r['holding_months'][1]} | {p['n']} | {pct(p['mean'])} | "
         f"{upct(p['se'])} | {p['t']:.2f} | {p['p_one_sided']:.4f} | p < 0.0167 | {'PASS' if p['p_one_sided'] < r['alpha_one_sided'] else 'FAIL'} |", "",
         "## Controls (robustness, all required)",
         "| Control | Estimate | Required | Result |", "|---|---|---|---|",
         f"| Mean net excess at 2× cost | {pct(rb['mean_excess_2x'])} | ≥ 0 | {pf(ch['cost_2x_mean_ge_0'])} |",
         f"| Mean net excess, delisted holdings at −30 % | {pct(rb['mean_excess_delist30'])} | > 0 | {pf(ch['delist_30_mean_gt_0'])} |",
         f"| Eras with mean net excess > 0 | {sum(e['mean'] > 0 for e in rb['eras'])} of 3 | ≥ 2 | {pf(ch['positive_in_2_of_3_eras'])} |",
         f"| Largest era share of the cumulative net excess | {100 * max(e['share_of_total'] for e in rb['eras']):.0f} % "
         f"(total {pct(sum(e['sum'] for e in rb['eras']))}) | ≤ 60 %, total > 0 | {pf(ch['no_era_over_60pct'])} |", "",
         "| Era | Months | Mean net excess | Sum | Share of cumulative sum |", "|---|---|---|---|---|"]
    L += [f"| {e['era']} | {e['months']} | {pct(e['mean'])} | {pct(e['sum'])} | {100 * e['share_of_total']:.0f} % |" for e in rb["eras"]]
    L += ["", f"Disclosed (Lo 2002, NW 3 lags): annualised Sharpe of the excess {sh['sharpe_annual']:.2f} "
              f"(SE {sh['se_annual']:.2f}; monthly {sh['sharpe_monthly']:.3f}, SE {sh['se_monthly']:.3f}; η = {sh['eta']:.2f}).", "",
          "## Economics",
          "| Portfolio | Median cost / month (1×) | Net CAGR | Max drawdown |", "|---|---|---|---|",
          f"| Winners (33 names) | {upct(inf['median_cost_per_month_1x']['winners'])} | {pct(inf['performance_full']['winners']['cagr'])} | "
          f"{upct(inf['performance_full']['winners']['max_drawdown'])} |",
          f"| Benchmark (100 names) | {upct(inf['median_cost_per_month_1x']['benchmark'])} | {pct(inf['performance_full']['benchmark']['cagr'])} | "
          f"{upct(inf['performance_full']['benchmark']['max_drawdown'])} |", "",
          f"Gross (0× cost) mean excess {pct(inf['gross_excess_0x']['mean'])} a month vs net {pct(p['mean'])}: costs take "
          f"{upct(inf['gross_excess_0x']['mean'] - p['mean'])} a month. Returns are simple, in PKR, monthly between execution closes.", "",
          "## Informational only — no verdict weight",
          f"- Top-60 universe: mean net excess {pct(inf['top60']['mean'])} (t = {inf['top60']['t']:.2f}, p = {inf['top60']['p_one_sided']:.3f}).",
          f"- Winners − KSE-100 from 2016-11 ({inf['winners_minus_kse100_from_2016_11']['n']} months; KSE-100 is a price index "
          f"without dividends, so this favours the strategy): {pct(inf['winners_minus_kse100_from_2016_11']['mean'])} a month "
          f"(t = {inf['winners_minus_kse100_from_2016_11']['t']:.2f}).",
          "", "| From 2016-11 | Net CAGR | Max drawdown |", "|---|---|---|"]
    for name, key in (("Winners", "winners"), ("Benchmark", "benchmark"), ("KSE-100 (price index)", "kse100")):
        q = inf["performance_from_2016_11"][key]
        L.append(f"| {name} | {pct(q['cagr'])} | {upct(q['max_drawdown'])} |")
    yrs = inf["excess_by_year"]
    L += ["", "| Year | " + " | ".join(str(y)[2:] for y in yrs) + " |", "|---|" + "---|" * len(yrs),
          "| Mean net excess / month | " + " | ".join(pct(v["mean"]) for v in yrs.values()) + " |"]
    at = inf["after_tax_winners_by_year"]
    L += ["| Winners pre-tax | " + " | ".join(pct(a["pre_tax"]) for a in at) + " |",
          "| Winners after 15 % CGT | " + " | ".join(pct(a["after_tax"]) for a in at) + " |",
          "", f"After-tax CAGR of winners {pct(inf['after_tax_winners_cagr'])} (CGT on each year's positive realised "
              "net gains, paid at year end; 2026 covers 9 months).", "",
          "## Limitations",
          "- Underpowered by design: the blinded power check put the MDE at 0.66 % a month against a 0.60 % reference "
          "(power 71 %), so a miss does not show the effect is absent.",
          "- One price source (PSX closing files), 2015–2026 only; the 12 inferred missing trading days are chained over, "
          "and symbol changes are detected heuristically (51 chained); others count as delistings.",
          "- Costs are modelled (Abdi–Ranaldo spread, published commission), not measured fills; no market impact "
          "beyond half the spread; locked-limit and no-close rules approximate execution.",
          "- Benchmark and winners are equal-weighted with no size or risk adjustment, unlike the prior's long–short, "
          "risk-adjusted test.",
          "- KSE-100 comparisons use a price index without dividends; the after-tax figures ignore tax on dividends.", "",
          "## Changes", "- (none)"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
