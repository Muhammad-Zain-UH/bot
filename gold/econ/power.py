"""Power pre-check for H07-H11 on broker v1b (TRAIN only for the statistics).

Blinding: no mean of any hypothesis variable is computed, printed or stored --
only counts, standard deviations and costs.

Batch 1 (H07 blocks, H08, H09): MDE = z x sd / sqrt(N), z = Bonferroni two-sided
at alpha = 0.05 over the batch-1 test count. Cost = median DEV round-turn cost
at the hypothesis's own entry and exit bars, k_cost x (s_entry + s_exit) / 2,
in log units of the entry price; a zero bar spread is missing, not free.
TESTABLE if MDE <= cost. H09's TRAIN is the old-fix era only (to 2015-03-19).

Batch 2 (H10, H11): weekly observations in TRAIN_D1 and DEV, and the Sharpe
standard error sqrt((1 + SR^2 / 2) / years) for SR = 0.3 and 0.5.

    venv\\Scripts\\python.exe -m gold.econ.power
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gold.econ.costs import cost_in_log_units, round_turn_cost_usd
from gold.hyp import h07_sessions, h08_intraday_momentum, h09_pm_auction
from research.phase1_statistical_controls import bonferroni_t

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research" / "power_v2.json"
ALPHA = 0.05
BATCH1_TESTS = 8
SHARPES = (0.3, 0.5)


def mde(sd: float, n: int, z: float) -> float:
    return z * sd / math.sqrt(n)


def sharpe_se(sr: float, years: float) -> float:
    return math.sqrt((1 + sr ** 2 / 2) / years)


def median_cost_log(s_entry, s_exit, price, k_cost: float) -> tuple[float, float]:
    """(median round-turn cost in log units, share of rows without a usable spread)."""
    s_entry = pd.Series(np.asarray(s_entry, float)).replace(0, np.nan)
    s_exit = pd.Series(np.asarray(s_exit, float)).replace(0, np.nan)
    cost = cost_in_log_units(round_turn_cost_usd(s_entry, s_exit, k_cost), np.asarray(price, float))
    cost = pd.Series(cost)
    return float(cost.median()), float(cost.isna().mean())


def batch1_rows(train: pd.DataFrame, dev: pd.DataFrame, k_cost: float) -> list[dict]:
    rows = []
    h7t, h7d = h07_sessions.block_returns(train), h07_sessions.block_returns(dev)
    prev = "s_start"
    for name, _, _ in h07_sessions.BLOCKS:
        cost, missing = median_cost_log(h7d[prev], h7d[f"s_{name}"], h7d["p_start_usd"], k_cost)
        rows.append({"test": f"H07 {name}", "n": len(h7t), "sd": float(h7t[f"r_{name}"].std(ddof=1)),
                     "cost": cost, "dev_rows": len(h7d), "dev_cost_missing_share": missing})
        prev = f"s_{name}"
    h8t, h8d = h08_intraday_momentum.momentum(train), h08_intraday_momentum.momentum(dev)
    cost, missing = median_cost_log(h8d["s_entry"], h8d["s_exit"], h8d["price_entry_usd"], k_cost)
    rows.append({"test": "H08", "n": len(h8t), "sd": float(h8t["y"].std(ddof=1)), "cost": cost,
                 "dev_rows": len(h8d), "dev_cost_missing_share": missing})
    h9t = h09_pm_auction.auction(train)
    h9t = h9t[h9t["day"] <= h09_pm_auction.OLD_FIX_ERA_END]
    h9d = h09_pm_auction.auction(dev)
    cost, missing = median_cost_log(h9d["s_entry"], h9d["s_exit"], h9d["price_entry_usd"], k_cost)
    rows.append({"test": "H09 (old-fix era)", "n": len(h9t), "sd": float(h9t["y"].std(ddof=1)),
                 "cost": cost, "dev_rows": len(h9d), "dev_cost_missing_share": missing})
    return rows


def assess(rows: list[dict], n_tests: int) -> float:
    z = bonferroni_t(n_tests, ALPHA)
    for r in rows:
        r["mde"] = mde(r["sd"], r["n"], z)
        r["testable"] = bool(r["mde"] <= r["cost"])
    return z


def weekly(d1: pd.DataFrame) -> dict:
    week = d1["session"] - pd.to_timedelta(d1["session"].dt.dayofweek, unit="D")
    years = (d1["session"].iloc[-1] - d1["session"].iloc[0]).days / 365.25
    return {"weeks": int(week.nunique()), "years": round(years, 2),
            **{f"sharpe_se_sr{sr}": round(sharpe_se(sr, years), 3) for sr in SHARPES}}


def h08_spec_cost(h1: pd.DataFrame, k_cost: float) -> pd.Series:
    """Per-day H08 round-turn cost in log units as in research/v2/H08_SPEC.md:
    k_cost x (spread of the 12:00 NY bar + spread of the 13:00 NY bar) / 2 over the
    12:00 close; a missing or zero spread takes that New York hour's median in h1."""
    from gold.hyp.anchors import NEW_YORK, Bars, local_time
    m = h08_intraday_momentum.momentum(h1)
    bars = Bars(h1)
    t12, t13 = (local_time(m["day"], h, NEW_YORK) for h in (12, 13))
    s12 = bars.spread_of_bar_ending_at(t12 + pd.Timedelta(hours=1))
    s13 = bars.spread_of_bar_ending_at(t13 + pd.Timedelta(hours=1))
    spread = h1["spread_usd"].replace(0, np.nan)
    hour_median = spread.groupby(h1["time"].dt.tz_convert(NEW_YORK).dt.hour).median()
    s12 = pd.Series(s12).replace(0, np.nan).fillna(hour_median[12])
    s13 = pd.Series(s13).replace(0, np.nan).fillna(hour_median[13])
    return pd.Series(cost_in_log_units(round_turn_cost_usd(s12, s13, k_cost), m["price_entry_usd"]))


def h08_only(train: pd.DataFrame, dev: pd.DataFrame, k_cost: float) -> dict:
    """Batch 1 = H08 alone. Counts, sds and costs only."""
    from statistics import NormalDist
    nd = NormalDist()
    yt = h08_intraday_momentum.momentum(train)["y"]
    yd = h08_intraday_momentum.momentum(dev)["y"]
    cost = float(h08_spec_cost(dev, k_cost).median())
    z_train, z_dev = bonferroni_t(1, ALPHA), nd.inv_cdf(1 - ALPHA)
    n_t, sd_t, n_d, sd_d = len(yt), float(yt.std(ddof=1)), len(yd), float(yd.std(ddof=1))
    mde_t, mde_d = mde(sd_t, n_t, z_train), mde(sd_d, n_d, z_dev)
    power = {f"{m}x_cost": nd.cdf(m * cost * math.sqrt(n_d) / sd_d - z_dev) for m in (1.0, 1.5)}
    return {"cost_log": cost, "train": {"n": n_t, "sd": sd_t, "z": z_train, "mde": mde_t,
                                        "mde_over_cost": mde_t / cost, "testable": mde_t <= cost},
            "dev": {"n": n_d, "sd": sd_d, "z_one_sided": z_dev, "mde": mde_d,
                    "mde_over_cost": mde_d / cost, "power": power}}


def main_h08() -> int:
    from gold.data.build_broker_v1b import FINGERPRINTS
    from gold.data.store import load_broker_v1b
    k = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["cost_calibration"]["k_cost"]
    r = h08_only(load_broker_v1b("H1", "TRAIN"), load_broker_v1b("H1", "DEV"), k)
    out = json.loads(OUT.read_text(encoding="utf-8"))
    out["h08_only"] = r
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=2))
    return 0


def main() -> int:
    from gold.data.build_broker_v1b import FINGERPRINTS
    from gold.data.store import load_broker_v1b, load_broker_v1b_d1
    k = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["cost_calibration"]["k_cost"]
    train, dev = load_broker_v1b("H1", "TRAIN"), load_broker_v1b("H1", "DEV")
    rows = batch1_rows(train, dev, k)
    z8 = assess(rows, BATCH1_TESTS)
    kept = [dict(r) for r in rows if r["testable"]]
    z_kept = assess(kept, len(kept)) if kept else None
    batch2 = {arm: weekly(load_broker_v1b_d1(arm)) for arm in ("TRAIN_D1", "DEV")}
    result = {"k_cost": k, "alpha": ALPHA, "batch1_tests": BATCH1_TESTS, "z_batch1": z8,
              "batch1": rows, "kept_tests": len(kept), "z_kept": z_kept, "kept": kept,
              "batch2": batch2}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"k_cost {k}; z(8) = {z8:.3f}")
    for r in rows:
        print(f"  {r['test']:<18} N {r['n']:>5}  sd {r['sd']:.5f}  MDE {r['mde']:.6f}  "
              f"cost {r['cost']:.6f}  {'TESTABLE' if r['testable'] else 'NOT TESTABLE'}  "
              f"(DEV rows {r['dev_rows']}, cost missing {r['dev_cost_missing_share']:.1%})")
    print(f"kept {len(kept)} tests" + (f", z = {z_kept:.3f}" if kept else ""))
    for r in kept:
        print(f"  {r['test']:<18} MDE {r['mde']:.6f}  cost {r['cost']:.6f}  "
              f"{'TESTABLE' if r['testable'] else 'NOT TESTABLE'}")
    print(json.dumps(batch2, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main_h08() if sys.argv[1:] == ["--h08"] else main())
