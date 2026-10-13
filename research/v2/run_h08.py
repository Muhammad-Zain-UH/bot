"""Run H08 exactly as pre-registered in research/v2/H08_SPEC.md (commit f6dab74).

Nothing here is chosen: every constant, window and threshold is the spec's.
Arms TRAIN and DEV only. FINAL_OOS can never be loaded by this script: the one
loader it uses raises on that arm before any read.

Verdict mapping (fixed before the first run):
  NOT SUPPORTED  the TRAIN test fails (|t| < 1.96, or a significant negative), or any
                 TRAIN control fails (a leg in the wrong direction, an era with
                 mean(y) <= 0, ESTIMATOR_SIGN_DISAGREEMENT);
  INCONCLUSIVE   TRAIN and all its controls pass but a DEV rule fails (one-sided
                 p >= 0.05, or economics) -- spec §10: DEV is underpowered;
  SUPPORTED      every rule passes.

    venv\\Scripts\\python.exe research/v2/run_h08.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from gold.data.store import load_broker_v1b                          # noqa: E402
from gold.econ.costs import round_turn_cost_usd                      # noqa: E402
from gold.hyp.anchors import NEW_YORK, Bars, local_time              # noqa: E402
from gold.hyp.h08_intraday_momentum import momentum                  # noqa: E402
from research.phase1_statistical_controls import raw_stats           # noqa: E402

SPEC = "research/v2/H08_SPEC.md"
SPEC_COMMIT = "f6dab74"
OUT = REPO / "research" / "v2" / "h08_results.json"
ALLOWED_ARMS = ("TRAIN", "DEV")
Z_TWO_SIDED = 1.96
ALPHA_DEV = 0.05
BOOT_DRAWS = 10_000
BOOT_SEED = 20261013
ERAS = (("2009-08-31", "2012-12-31"), ("2013-01-01", "2016-12-31"), ("2017-01-01", "2020-12-31"))
K_COST = 4.625
ENTRY_BAR_HOUR_NY, EXIT_BAR_HOUR_NY = 12, 13      # bars whose spread_usd is the cost
ENTRY_HOUR_NY, EXIT_HOUR_NY = 12, 14              # closes: bar ending 12:00, bar ending 14:00

ND = NormalDist()


class ForbiddenArmError(RuntimeError):
    pass


def load(arm: str) -> pd.DataFrame:
    if arm not in ALLOWED_ARMS:
        raise ForbiddenArmError(f"run_h08 never loads {arm!r}; allowed: {ALLOWED_ARMS}")
    return load_broker_v1b("H1", arm)


def headline(y: pd.Series) -> dict:
    s = raw_stats(y.to_numpy())
    s["t"] = s["mean"] / s["se"]
    s["p_two_sided"] = math.erfc(abs(s["t"]) / math.sqrt(2))
    s["p_one_sided_positive"] = 1 - ND.cdf(s["t"])
    return s


def month_block(days: pd.Series, y: pd.Series) -> dict:
    """Equal-weighted mean of calendar-month means; SE from a calendar-month block
    bootstrap (BOOT_DRAWS draws, BOOT_SEED)."""
    month_means = y.groupby(days.dt.to_period("M").to_numpy()).mean().to_numpy()
    rng = np.random.default_rng(BOOT_SEED)
    draws = month_means[rng.integers(0, len(month_means), (BOOT_DRAWS, len(month_means)))].mean(axis=1)
    m, se = float(month_means.mean()), float(draws.std(ddof=1))
    return {"n_months": int(len(month_means)), "mean": m, "se_bootstrap": se, "t": m / se,
            "draws": BOOT_DRAWS, "seed": BOOT_SEED}


def economics(dev: pd.DataFrame) -> dict:
    m = momentum(dev)
    bars = Bars(dev)
    entry = bars.close_at(local_time(m["day"], ENTRY_HOUR_NY, NEW_YORK))
    exit_ = bars.close_at(local_time(m["day"], EXIT_HOUR_NY, NEW_YORK))
    direction = np.sign(m["r_early"].to_numpy())
    gross = direction * (exit_ - entry)
    usable = dev[~dev["utc_suspect"]]
    spread = usable["spread_usd"].replace(0, np.nan)
    hour_median = spread.groupby(usable["time"].dt.tz_convert(NEW_YORK).dt.hour).median()
    s = {}
    for h in (ENTRY_BAR_HOUR_NY, EXIT_BAR_HOUR_NY):
        raw = pd.Series(bars.spread_of_bar_ending_at(local_time(m["day"], h + 1, NEW_YORK)))
        s[h] = raw.replace(0, np.nan)
        s[f"filled_{h}"] = int(s[h].isna().sum())
        s[h] = s[h].fillna(hour_median[h])
    cost = round_turn_cost_usd(s[ENTRY_BAR_HOUR_NY], s[EXIT_BAR_HOUR_NY], K_COST)
    net1, net2 = gross - cost, gross - 2 * cost
    return {"trades": int(len(m)), "gross_mean_usd": float(np.mean(gross)),
            "cost_mean_usd_1x": float(np.mean(cost)),
            "net_mean_usd_1x": float(np.mean(net1)), "net_mean_usd_2x": float(np.mean(net2)),
            "spreads_filled": {"12:00 bar": s[f"filled_{ENTRY_BAR_HOUR_NY}"],
                               "13:00 bar": s[f"filled_{EXIT_BAR_HOUR_NY}"]},
            "fill_median_usd": {"12": float(hour_median[ENTRY_BAR_HOUR_NY]),
                                "13": float(hour_median[EXIT_BAR_HOUR_NY])},
            "pass_1x": bool(np.mean(net1) > 0), "pass_2x": bool(np.mean(net2) >= 0)}


def main() -> int:
    train = momentum(load("TRAIN"))
    t = headline(train["y"])
    train_pass = bool(abs(t["t"]) >= Z_TWO_SIDED and t["mean"] > 0)
    blk = month_block(train["day"], train["y"])
    disagreement = bool(np.sign(blk["mean"]) != np.sign(t["mean"]))
    legs = {"r_late | r_early > 0": raw_stats(train.loc[train.r_early > 0, "r_late"].to_numpy()),
            "r_late | r_early < 0": raw_stats(train.loc[train.r_early < 0, "r_late"].to_numpy())}
    legs_pass = bool(legs["r_late | r_early > 0"]["mean"] > 0 and legs["r_late | r_early < 0"]["mean"] < 0)
    eras = {}
    for lo, hi in ERAS:
        sel = (train["day"] >= pd.Timestamp(lo)) & (train["day"] <= pd.Timestamp(hi))
        eras[f"{lo} -> {hi}"] = raw_stats(train.loc[sel, "y"].to_numpy())
    eras_pass = all(e["mean"] > 0 for e in eras.values())

    dev_frame = load("DEV")
    dev = momentum(dev_frame)
    d = headline(dev["y"])
    dev_pass = bool(d["p_one_sided_positive"] < ALPHA_DEV)
    econ = economics(dev_frame)

    train_ok = train_pass and legs_pass and eras_pass and not disagreement
    dev_ok = dev_pass and econ["pass_1x"] and econ["pass_2x"]
    verdict = ("SUPPORTED" if train_ok and dev_ok else
               "INCONCLUSIVE" if train_ok else "NOT SUPPORTED")
    result = {
        "spec": SPEC, "spec_commit": SPEC_COMMIT, "verdict": verdict,
        "train": {"headline": t, "pass": train_pass,
                  "secondary_month_block": blk, "ESTIMATOR_SIGN_DISAGREEMENT": disagreement,
                  "legs": legs, "legs_pass": legs_pass, "eras": eras, "eras_pass": eras_pass},
        "dev": {"headline": d, "pass_one_sided": dev_pass, "economics": econ},
        "checks": {"train_ok": train_ok, "dev_ok": dev_ok},
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
