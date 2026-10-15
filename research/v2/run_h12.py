"""Run H12 exactly as pre-registered in research/v2/H12_SPEC.md (commit 724eb6f).
TRAIN_D1 first, then DEV. FINAL_OOS is never loaded: the script's only loader refuses it.

Verdict (spec §8): SUPPORTED if every pass condition holds at 1x cost, net of cost and
financing; NOT SUPPORTED otherwise.

    venv\\Scripts\\python.exe research/v2/run_h12.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from gold.data.build_h12 import COSTS, FINGERPRINTS, SYMBOLS        # noqa: E402
from gold.data.store import load_h12                                # noqa: E402
from gold.hyp import h12_multi_tsmom as h12, weekly                 # noqa: E402

SPEC = "research/v2/H12_SPEC.md"
SPEC_COMMIT = "724eb6f"
OUT = REPO / "research" / "v2" / "h12_results.json"
ALLOWED_ARMS = ("TRAIN_D1", "DEV")
TRAIN_PNL_START = pd.Timestamp("2004-06-14")
LEVELS = (1, 2)
SERIES = {"gross": "gross", "net_of_cost": "net_of_cost", "net_of_cost_and_financing": "net"}
ERA_CAP, SYMBOL_CAP, TRAIN_SHARPE_MIN = 0.60, 0.30, 0.30


class ForbiddenArmError(RuntimeError):
    pass


def load(sym: str, tf: str, arm: str) -> pd.DataFrame:
    if arm not in ALLOWED_ARMS:
        raise ForbiddenArmError(f"run_h12 never loads {arm!r}; allowed: {ALLOWED_ARMS}")
    return load_h12(sym, tf, arm)


def frozen_constants() -> pd.DataFrame:
    committed = subprocess.run(["git", "show", f"{SPEC_COMMIT}:{SPEC}"], cwd=REPO, check=True,
                               capture_output=True, text=True, encoding="utf-8").stdout
    if committed != (REPO / SPEC).read_text(encoding="utf-8"):
        raise RuntimeError(f"{SPEC} differs from commit {SPEC_COMMIT}")
    consts = h12.spec_constants(committed)
    if sorted(consts.index) != sorted(SYMBOLS):
        raise RuntimeError(f"spec table has {len(consts)} symbols, expected the 29")
    swaps = json.loads(COSTS.read_text(encoding="utf-8"))["symbols"]
    starts = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["symbols"]
    for sym in consts.index:
        consts.at[sym, "swap_long"] = swaps[sym]["swap_long_annual"]
        consts.at[sym, "swap_short"] = swaps[sym]["swap_short_annual"]
        if (abs(round(100 * swaps[sym]["swap_long_annual"], 2) - consts.at[sym, "swap_long_pct"]) > 1e-9
                or abs(round(100 * swaps[sym]["swap_short_annual"], 2) - consts.at[sym, "swap_short_pct"]) > 1e-9):
            raise RuntimeError(f"{sym}: h12_costs.json swaps do not round to the spec table")
        if str(consts.at[sym, "intraday_start"].date()) != starts[sym]["intraday_start"]:
            raise RuntimeError(f"{sym}: intraday start differs from h12_fingerprints.json")
    return consts


def arm_data(consts: pd.DataFrame, arm: str, train_d1: dict | None) -> tuple[dict, dict]:
    d1s, h4s = {}, {}
    for sym in consts.index:
        d1 = load(sym, "D1", arm)
        if arm == "DEV":
            d1 = pd.concat([train_d1[sym], d1], ignore_index=True)       # lookback, past data only
        d1s[sym] = d1[d1["session"] >= consts.at[sym, "intraday_start"]].reset_index(drop=True)
        h4s[sym] = load(sym, "H4", arm)
    return d1s, h4s


def run_arm(consts, d1s, h4s, first_session) -> dict:
    tg, n_week = h12.targets(d1s, consts, first_session)
    problems = {}
    for sym, t in tg.items():
        bad = [s for s in h12.unapplied_executions(d1s[sym], h4s[sym], t) if s != t.index.max()]
        if bad:
            problems[sym] = [str(b.date()) for b in bad]
    if problems:
        raise RuntimeError(f"executions outside the symbol's sessions (possible bug): {problems}")
    out = {"n_t": {"min": int(n_week.min()), "max": int(n_week.max()),
                   "first_week": str(n_week.index.min().date()),
                   "weeks_at_29": int((n_week == len(consts)).sum()), "weeks": int(len(n_week))},
           "levels": {}}
    for level in LEVELS:
        per = {sym: weekly.run(d1s[sym], h4s[sym], t, None,
                               cost_per_unit=consts.at[sym, "cost_bp"] * 1e-4 * level,
                               financing_fn=h12.swap_charge_fn(consts.at[sym, "swap_long"],
                                                               consts.at[sym, "swap_short"], level))
               for sym, t in tg.items()}
        port = h12.portfolio(per)
        res = {name: {"metrics": h12.metrics(port, col), "eras": weekly.era_pnl(port, col)}
               for name, col in SERIES.items()}
        res["per_symbol_net"] = {sym: float(df["net"].sum()) for sym, df in per.items() if len(df)}
        res["per_symbol_gross"] = {sym: float(df["gross"].sum()) for sym, df in per.items() if len(df)}
        res["first_session"] = str(port["session"].iloc[0].date())
        res["last_session"] = str(port["session"].iloc[-1].date())
        out["levels"][f"{level}x"] = res
    return out


def main() -> int:
    consts = frozen_constants()
    d1_train, h4_train = arm_data(consts, "TRAIN_D1", None)
    train = run_arm(consts, d1_train, h4_train, TRAIN_PNL_START)
    raw_train = {sym: load(sym, "D1", "TRAIN_D1") for sym in consts.index}
    d1_dev, h4_dev = arm_data(consts, "DEV", raw_train)
    dev_first = min(load(sym, "D1", "DEV")["session"].iloc[0] for sym in consts.index)
    dev = run_arm(consts, d1_dev, h4_dev, dev_first)

    t1, d1x = train["levels"]["1x"], dev["levels"]["1x"]
    net = "net_of_cost_and_financing"
    era = weekly.era_rule(t1[net]["eras"])
    total = sum(t1["per_symbol_net"].values())
    shares = {s: v / total for s, v in t1["per_symbol_net"].items()} if total else {}
    conditions = {
        "train_sharpe_ge_0.30": t1[net]["metrics"]["sharpe"] >= TRAIN_SHARPE_MIN,
        "dev_sharpe_gt_0": d1x[net]["metrics"]["sharpe"] > 0,
        "train_pnl_gt_0_and_no_era_above_60pct": era["pass"],
        "no_symbol_above_30pct": bool(total > 0 and max(shares.values()) <= SYMBOL_CAP),
    }
    result = {"spec": SPEC, "spec_commit": SPEC_COMMIT,
              "verdict": "SUPPORTED" if all(conditions.values()) else "NOT SUPPORTED",
              "conditions": conditions, "era_rule": era,
              "symbol_shares_train_net": dict(sorted(shares.items(), key=lambda kv: -kv[1])),
              "TRAIN_D1": train, "DEV": dev}
    OUT.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "conditions": conditions}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
