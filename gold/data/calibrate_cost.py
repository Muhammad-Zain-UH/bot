"""Broker cost calibration, outside every research arm.

k_cost = median broker tick spread (ask - bid) / median H1 bar spread_usd over
the same hours, floored at 1. Research costs are DEV bar spread_usd x k_cost,
because the MT5 bar spread field is a broker-defined summary (typically lower
than the typical tick spread).

Window: 2026-10-05 00:00 -> 2026-10-09 21:00 UTC, after FINAL_OOS ends
(2026-10-01), so calibrating never touches a research arm. The 2026-09-24 tick
sample is not used: it lies inside FINAL_OOS. MT5 returns server time; it is
converted with the v1b rule (gold.data.build_broker_v1b.server_to_utc).

Result is stored under "cost_calibration" in research/broker_v1b_fingerprints.json,
with the share of zero or missing spread_usd per year of v1b H1 (TRAIN and DEV).

    venv\\Scripts\\python.exe -m gold.data.calibrate_cost
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from gold.data.build_broker_v1b import FINGERPRINTS, NEW_YORK, server_to_utc

SYMBOL = "XAUUSD"
WINDOW_UTC = (pd.Timestamp("2026-10-05 00:00", tz="UTC"), pd.Timestamp("2026-10-09 21:00", tz="UTC"))
# MT5 takes and returns server wall time; request a day either side, then cut in UTC.
REQUEST_SERVER = (datetime(2026, 10, 4, tzinfo=timezone.utc), datetime(2026, 10, 11, tzinfo=timezone.utc))
K_COST_FLOOR = 1.0


class CalibrationError(RuntimeError):
    pass


def k_cost(ticks: pd.DataFrame, bars: pd.DataFrame) -> dict:
    """ticks: time (UTC), bid, ask. bars: time (UTC, H1 open), spread_usd.
    Uses only the hours present in both."""
    ticks = ticks[(ticks["bid"] > 0) & (ticks["ask"] >= ticks["bid"])].copy()
    ticks["hour"] = ticks["time"].dt.floor("1h")
    hours = sorted(set(ticks["hour"]) & set(bars["time"]))
    if not hours:
        raise CalibrationError("no hour has both ticks and an H1 bar")
    t = ticks[ticks["hour"].isin(hours)]
    b = bars[bars["time"].isin(hours)]
    tick_med = float((t["ask"] - t["bid"]).median())
    bar_med = float(b["spread_usd"].median())
    if bar_med <= 0:
        raise CalibrationError(f"median bar spread_usd is {bar_med}; cannot form a ratio")
    ny_hour = t["time"].dt.tz_convert(NEW_YORK).dt.hour
    spread = t["ask"] - t["bid"]
    per_hour = {int(h): {"median_usd": round(float(s.median()), 4),
                         "p95_usd": round(float(s.quantile(0.95)), 4), "ticks": int(s.size)}
                for h, s in spread.groupby(ny_hour)}
    return {"k_cost": max(K_COST_FLOOR, tick_med / bar_med), "k_cost_unfloored": tick_med / bar_med,
            "tick_spread_median_usd": tick_med, "bar_spread_median_usd": bar_med,
            "hours_used": len(hours), "ticks_used": int(len(t)),
            "tick_spread_per_ny_hour": per_hour}


def spread_completeness(h1: pd.DataFrame) -> dict:
    """Share of zero or missing spread_usd per UTC year."""
    bad = h1["spread_usd"].isna() | (h1["spread_usd"] == 0)
    g = bad.groupby(h1["time"].dt.year)
    return {int(y): {"bars": int(s.size), "zero_or_missing_share": round(float(s.mean()), 4)}
            for y, s in g}


def fetch_mt5() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise CalibrationError(f"MT5 is not running or not reachable: {mt5.last_error()}")
    try:
        si = mt5.symbol_info(SYMBOL)
        if si is None:
            raise CalibrationError(f"symbol {SYMBOL} not available")
        raw_ticks = mt5.copy_ticks_range(SYMBOL, *REQUEST_SERVER, mt5.COPY_TICKS_ALL)
        raw_bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_H1, *REQUEST_SERVER)
        info = {"server": getattr(mt5.account_info(), "server", None), "symbol_point": si.point}
    finally:
        mt5.shutdown()
    if raw_ticks is None or len(raw_ticks) == 0:
        raise CalibrationError(f"no ticks returned: {mt5.last_error()}")
    if raw_bars is None or len(raw_bars) == 0:
        raise CalibrationError(f"no H1 bars returned: {mt5.last_error()}")
    tk = pd.DataFrame(raw_ticks)
    ticks = pd.DataFrame({"time": server_to_utc(pd.Series(pd.to_datetime(tk["time_msc"], unit="ms", utc=True))),
                          "bid": tk["bid"].to_numpy(), "ask": tk["ask"].to_numpy()})
    br = pd.DataFrame(raw_bars)
    bars = pd.DataFrame({"time": server_to_utc(pd.Series(pd.to_datetime(br["time"], unit="s", utc=True))),
                         "spread_usd": br["spread"].to_numpy() * si.point})
    lo, hi = WINDOW_UTC
    ticks = ticks[(ticks["time"] >= lo) & (ticks["time"] < hi)].reset_index(drop=True)
    bars = bars[(bars["time"] >= lo) & (bars["time"] < hi)].reset_index(drop=True)
    return ticks, bars, info


def main() -> int:
    from gold.data.store import load_broker_v1b
    ticks, bars, info = fetch_mt5()
    result = k_cost(ticks, bars)
    h1 = pd.concat([load_broker_v1b("H1", a) for a in ("TRAIN", "DEV")], ignore_index=True)
    record = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    record["cost_calibration"] = {
        "window_utc": [WINDOW_UTC[0].isoformat(), WINDOW_UTC[1].isoformat()],
        "outside_every_arm": "after FINAL_OOS ends 2026-10-01; the 2026-09-24 sample is not used",
        "method": "k_cost = max(1, median tick (ask - bid) / median H1 bar spread_usd, same hours)",
        "calibrated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **info, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in result.items()},
        "spread_usd_completeness_h1_train_dev": spread_completeness(h1),
    }
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    c = record["cost_calibration"]
    print(f"k_cost {c['k_cost']} (unfloored {c['k_cost_unfloored']}); tick median "
          f"{c['tick_spread_median_usd']} USD, bar median {c['bar_spread_median_usd']} USD; "
          f"{c['hours_used']} hours, {c['ticks_used']} ticks")
    for h, v in c["tick_spread_per_ny_hour"].items():
        print(f"  NY {h:02d}: median {v['median_usd']}  p95 {v['p95_usd']}  ({v['ticks']} ticks)")
    for y, v in c["spread_usd_completeness_h1_train_dev"].items():
        print(f"  H1 {y}: {v['zero_or_missing_share']:.1%} zero/missing of {v['bars']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
