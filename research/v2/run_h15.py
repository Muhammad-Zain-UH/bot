"""Run H15 exactly as pre-registered in research/v2/H15_SPEC.md (commit 46a0e93).

TRAIN first, then DEV. FINAL_OOS is never loaded: the one loader refuses it before any read.
Verdict mapping (spec §9, fixed before the first run):
  NOT SUPPORTED  the TRAIN test fails (|t| < 2.241, or a significant negative), or a TRAIN control
                 fails (per-hour contrast <= 0, an era with mean(y) <= 0, ESTIMATOR_SIGN_DISAGREEMENT);
  INCONCLUSIVE   TRAIN and its controls pass but a DEV rule fails (one-sided p >= 0.05, or economics);
  SUPPORTED      every rule passes.

    venv\\Scripts\\python.exe research/v2/run_h15.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from gold.data.store import load_broker_v1b                          # noqa: E402
from gold.econ.costs import round_turn_cost_usd                      # noqa: E402
from gold.econ.power import filled, hour_median_spread               # noqa: E402
from gold.hyp.h15_asia_us import ASIA_HOURS, US_HOURS, asia_us       # noqa: E402
from research.phase1_statistical_controls import raw_stats           # noqa: E402

SPEC = "research/v2/H15_SPEC.md"
SPEC_COMMIT = "46a0e93"
OUT = REPO / "research" / "v2" / "h15_results.json"
ALLOWED_ARMS = ("TRAIN", "DEV")
Z_TRAIN = 2.241                       # Bonferroni two-sided, alpha 0.05, 2 V2 tests
ALPHA_DEV = 0.05
BOOT_DRAWS = 10_000
BOOT_SEED = 20261015
ERAS = (("2009-08-31", "2012-12-31"), ("2013-01-01", "2016-12-31"), ("2017-01-01", "2020-12-31"))
K_COST = 4.625
ND = NormalDist()


class ForbiddenArmError(RuntimeError):
    pass


def load(arm: str) -> pd.DataFrame:
    if arm not in ALLOWED_ARMS:
        raise ForbiddenArmError(f"run_h15 never loads {arm!r}; allowed: {ALLOWED_ARMS}")
    return load_broker_v1b("H1", arm)


def headline(y: pd.Series) -> dict:
    s = raw_stats(y.to_numpy())
    s["t"] = s["mean"] / s["se"]
    s["p_two_sided"] = math.erfc(abs(s["t"]) / math.sqrt(2))
    s["p_one_sided_positive"] = 1 - ND.cdf(s["t"])
    return s


def month_block(days: pd.Series, y: pd.Series) -> dict:
    month_means = y.groupby(days.dt.to_period("M").to_numpy()).mean().to_numpy()
    rng = np.random.default_rng(BOOT_SEED)
    draws = month_means[rng.integers(0, len(month_means), (BOOT_DRAWS, len(month_means)))].mean(axis=1)
    m, se = float(month_means.mean()), float(draws.std(ddof=1))
    return {"n_months": int(len(month_means)), "mean": m, "se_bootstrap": se, "t": m / se,
            "draws": BOOT_DRAWS, "seed": BOOT_SEED}


def economics(dev_h1: pd.DataFrame, d: pd.DataFrame) -> dict:
    """Two round trips per day (long Asia, short US) in USD/oz; long-Asia-only for disclosure."""
    hm = hour_median_spread(dev_h1)
    day_utc = d["day"].dt.tz_localize("UTC")
    p0, p14 = d["p_asia_start"].to_numpy(), d["p_14"].to_numpy()
    p11, p_end = p0 * np.exp(d["r_asia"].to_numpy()), p14 * np.exp(d["r_us"].to_numpy())
    s0 = filled(d["s_asia_start"], d["asia_start"], hm)
    s11 = filled(d["s_11"], day_utc + pd.Timedelta(hours=10), hm)
    s14 = filled(d["s_14"], day_utc + pd.Timedelta(hours=13), hm)
    s_end = filled(d["s_us_end"], d["us_end"], hm)
    gross_asia, gross_us = p11 - p0, p14 - p_end
    cost_asia, cost_us = round_turn_cost_usd(s0, s11, K_COST), round_turn_cost_usd(s14, s_end, K_COST)
    gross, cost = gross_asia + gross_us, cost_asia + cost_us
    zero = {k: int(np.sum((pd.Series(np.asarray(v, float)).fillna(0) == 0)))
            for k, v in (("asia_start", d["s_asia_start"]), ("11", d["s_11"]), ("14", d["s_14"]),
                         ("us_end", d["s_us_end"]))}
    return {"days": int(len(d)), "gross_mean_usd": float(gross.mean()), "cost_mean_usd_1x": float(cost.mean()),
            "net_mean_usd_1x": float((gross - cost).mean()), "net_mean_usd_2x": float((gross - 2 * cost).mean()),
            "pass_1x": bool((gross - cost).mean() > 0), "pass_2x": bool((gross - 2 * cost).mean() >= 0),
            "spreads_filled": zero,
            "long_asia_only_disclosure": {"gross_mean_usd": float(gross_asia.mean()),
                                          "cost_mean_usd_1x": float(cost_asia.mean()),
                                          "net_mean_usd_1x": float((gross_asia - cost_asia).mean()),
                                          "net_mean_usd_2x": float((gross_asia - 2 * cost_asia).mean())}}


def main() -> int:
    committed = subprocess.run(["git", "show", f"{SPEC_COMMIT}:{SPEC}"], cwd=REPO, check=True,
                               capture_output=True, text=True, encoding="utf-8").stdout
    if committed != (REPO / SPEC).read_text(encoding="utf-8"):
        raise RuntimeError(f"{SPEC} differs from commit {SPEC_COMMIT}")

    train = asia_us(load("TRAIN"))
    t = headline(train["y"])
    train_pass = bool(abs(t["t"]) >= Z_TRAIN and t["mean"] > 0)
    blk = month_block(train["day"], train["y"])
    disagreement = bool(np.sign(blk["mean"]) != np.sign(t["mean"]))
    legs = {"r_asia": raw_stats(train["r_asia"].to_numpy()), "r_us": raw_stats(train["r_us"].to_numpy())}
    per_hour = legs["r_asia"]["mean"] / ASIA_HOURS - legs["r_us"]["mean"] / US_HOURS
    eras = {}
    for lo, hi in ERAS:
        sel = (train["day"] >= pd.Timestamp(lo)) & (train["day"] <= pd.Timestamp(hi))
        eras[f"{lo} -> {hi}"] = raw_stats(train.loc[sel, "y"].to_numpy())
    eras_pass = all(e["mean"] > 0 for e in eras.values())

    dev_h1 = load("DEV")
    dev = asia_us(dev_h1)
    d = headline(dev["y"])
    dev_pass = bool(d["p_one_sided_positive"] < ALPHA_DEV)
    econ = economics(dev_h1, dev)
    dev_legs = {"r_asia": raw_stats(dev["r_asia"].to_numpy()), "r_us": raw_stats(dev["r_us"].to_numpy())}

    train_ok = train_pass and per_hour > 0 and eras_pass and not disagreement
    dev_ok = dev_pass and econ["pass_1x"] and econ["pass_2x"]
    verdict = "SUPPORTED" if train_ok and dev_ok else "INCONCLUSIVE" if train_ok else "NOT SUPPORTED"
    result = {"spec": SPEC, "spec_commit": SPEC_COMMIT, "verdict": verdict,
              "train": {"headline": t, "pass": train_pass, "legs": legs,
                        "per_hour_contrast": per_hour, "per_hour_pass": bool(per_hour > 0),
                        "secondary_month_block": blk, "ESTIMATOR_SIGN_DISAGREEMENT": disagreement,
                        "eras": eras, "eras_pass": eras_pass},
              "dev": {"headline": d, "pass_one_sided": dev_pass, "legs": dev_legs, "economics": econ},
              "checks": {"train_ok": train_ok, "dev_ok": dev_ok}}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
