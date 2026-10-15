"""Run V2 batch 2 (H10, H11) exactly as pre-registered in research/v2/H10_SPEC.md and
research/v2/H11_SPEC.md (commit 3fffc24). TRAIN_D1 first, then DEV. FINAL_OOS can never
be loaded: the script's loaders raise on any other arm before reading.

Verdicts (spec §8, external-prior standard): SUPPORTED if every pass condition holds,
NOT SUPPORTED otherwise.

    venv\\Scripts\\python.exe research/v2/run_batch2.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from gold.data.store import load_broker_v1b, load_broker_v1b_d1     # noqa: E402
from gold.hyp import h10_tsmom, h11_vol_managed, weekly              # noqa: E402

SPECS = ("research/v2/H10_SPEC.md", "research/v2/H11_SPEC.md")
SPEC_COMMIT = "3fffc24"
OUT = REPO / "research" / "v2" / "batch2_results.json"
ALLOWED_ARMS = ("TRAIN_D1", "DEV")
COST_LEVELS = (1, 2)
DFF_CSV = REPO / "data" / "cross_asset_v1" / "raw" / "DFF.csv"
CROSS_MANIFEST = REPO / "data" / "cross_asset_v1" / "meta" / "manifest.json"


class ForbiddenArmError(RuntimeError):
    pass


def _check(arm: str) -> None:
    if arm not in ALLOWED_ARMS:
        raise ForbiddenArmError(f"run_batch2 never loads {arm!r}; allowed: {ALLOWED_ARMS}")


def load_d1(arm: str) -> pd.DataFrame:
    _check(arm)
    return load_broker_v1b_d1(arm)


def load_h4(arm: str) -> pd.DataFrame:
    _check(arm)
    return load_broker_v1b("H4", arm)


def load_dff() -> pd.Series:
    body = DFF_CSV.read_bytes()
    expect = json.loads(CROSS_MANIFEST.read_text(encoding="utf-8"))["series"]["DFF"]["sha256"]
    if hashlib.sha256(body).hexdigest() != expect:
        raise RuntimeError("DFF.csv does not match the cross-asset manifest")
    f = pd.read_csv(DFF_CSV)
    return pd.Series(pd.to_numeric(f.iloc[:, 1], errors="coerce").to_numpy(),
                     index=pd.to_datetime(f.iloc[:, 0])).dropna()


def swap_reference() -> dict:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {"available": False, "error": str(mt5.last_error())}
        try:
            si = mt5.symbol_info("XAUUSD")
            return {"available": True, "swap_long": si.swap_long, "swap_short": si.swap_short,
                    "swap_mode": si.swap_mode, "note": "reference only, not used in P&L"}
        finally:
            mt5.shutdown()
    except Exception as exc:                      # reference only; never blocks the run
        return {"available": False, "error": repr(exc)}


def arm_runs(d1: pd.DataFrame, h4: pd.DataFrame, first: pd.Timestamp, dff: pd.Series) -> dict:
    t10 = h10_tsmom.targets(d1, first)
    t11 = h11_vol_managed.targets(d1, first)
    tb = h11_vol_managed.benchmark(t11)
    out = {}
    for level in COST_LEVELS:
        cost = weekly.COST_PER_UNIT * level
        out[level] = {name: weekly.run(d1, h4, t, dff, cost)
                      for name, t in (("H10", t10), ("H11", t11), ("H11_benchmark", tb))}
    return out


def summarise(runs: dict, with_eras: bool) -> dict:
    res = {}
    for level, by in runs.items():
        res[f"{level}x"] = {}
        for name, daily in by.items():
            r = {"metrics": weekly.metrics(daily),
                 "first_session": str(daily["session"].iloc[0].date()),
                 "last_session": str(daily["session"].iloc[-1].date())}
            if with_eras:
                r["eras"] = weekly.era_pnl(daily)
            res[f"{level}x"][name] = r
        if with_eras:
            s, b = by["H11"], by["H11_benchmark"]
            assert list(s["session"]) == list(b["session"]), "H11 and benchmark sessions differ"
            excess = s.assign(net=s["net"].to_numpy() - b["net"].to_numpy())
            res[f"{level}x"]["H11_excess_eras"] = weekly.era_pnl(excess)
    return res


def main() -> int:
    dff = load_dff()
    d1_train, h4_train = load_d1("TRAIN_D1"), load_h4("TRAIN_D1")
    train = summarise(arm_runs(d1_train, h4_train, d1_train["session"].iloc[0], dff), True)
    d1_dev, h4_dev = load_d1("DEV"), load_h4("DEV")
    lookback = pd.concat([d1_train, d1_dev], ignore_index=True)       # past data only
    dev = summarise(arm_runs(lookback, h4_dev, d1_dev["session"].iloc[0], dff), False)

    def m(arm, name):
        return arm["1x"][name]["metrics"]

    h10_era = weekly.era_rule(train["1x"]["H10"]["eras"])
    h10 = {"train_sharpe_gt_0": m(train, "H10")["sharpe"] > 0,
           "dev_sharpe_gt_0": m(dev, "H10")["sharpe"] > 0, "train_era_rule": h10_era["pass"]}
    h11_era = weekly.era_rule(train["1x"]["H11_excess_eras"])
    h11 = {}
    for arm_name, arm in (("train", train), ("dev", dev)):
        h11[f"{arm_name}_sharpe_above_benchmark"] = m(arm, "H11")["sharpe"] > m(arm, "H11_benchmark")["sharpe"]
        h11[f"{arm_name}_drawdown_below_benchmark"] = (m(arm, "H11")["max_drawdown"]
                                                       < m(arm, "H11_benchmark")["max_drawdown"])
    h11["train_excess_era_rule"] = h11_era["pass"]
    result = {
        "specs": SPECS, "spec_commit": SPEC_COMMIT,
        "verdicts": {"H10": "SUPPORTED" if all(h10.values()) else "NOT SUPPORTED",
                     "H11": "SUPPORTED" if all(h11.values()) else "NOT SUPPORTED"},
        "conditions": {"H10": h10, "H11": h11},
        "era_rules": {"H10": h10_era, "H11_excess": h11_era},
        "TRAIN_D1": train, "DEV": dev, "broker_swap_reference": swap_reference(),
    }
    OUT.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
