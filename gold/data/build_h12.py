"""H12 universe: MT5 export and build for the 29 breadth symbols (v1b clock rule).

Symbols: the 27 FX majors/crosses and XAUUSD, XAGUSD that are fully tradable with D1
history on or before 2010-01-01 (research/v2/breadth_metadata.csv, kept == True).

    venv\\Scripts\\python.exe -m gold.data.build_h12 export   # raw server-time CSVs (write-once)
    venv\\Scripts\\python.exe -m gold.data.build_h12 build    # UTC Parquet, D1 at 17:00 NY, fingerprints
    venv\\Scripts\\python.exe -m gold.data.build_h12 check    # weekend-reopen clock check (TRAIN+DEV)
    venv\\Scripts\\python.exe -m gold.data.build_h12 costs    # tick spreads 2026-10-05 -> 10-09, swaps

Raw: data/h12_v1/raw_server/{SYM}_{TF}_server.csv for H1, H4, D1, server time as delivered,
never overwritten. Built: data/h12_v1/bars/{SYM}_{H1|H4|D1}.parquet. UTC via
gold.data.build_broker_v1b.server_to_utc (NY + 7 h before 2020-07-01, Europe/Athens after).
D1 = H4 aggregated at the 17:00 New York boundary (gold/data/broker_daily.py). H1 is used for
the clock check only.

Early history is daily-only: before a symbol's intraday history begins, its H1 and H4
"bars" are one bar per day. intraday_start (recorded per symbol) is the first session after
the last run of daily-only sessions; nothing in this module chooses a research start.

spread_px = MT5 bar spread x point, in quote-currency price units (not USD).
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from gold.data.broker_daily import daily_bars
from gold.data.build_broker_v1b import NEW_YORK, server_to_utc

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "data" / "h12_v1"
RAW = ROOT / "raw_server"
BARS = ROOT / "bars"
FINGERPRINTS = REPO / "research" / "h12_fingerprints.json"
COSTS = REPO / "research" / "h12_costs.json"
MANIFEST = REPO / "research" / "research_split_manifest_h12.json"
V1B_MANIFEST = REPO / "research" / "research_split_manifest_h1_v1b.json"
BREADTH_CSV = REPO / "research" / "v2" / "breadth_metadata.csv"
SYMBOLS = ("AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD", "CADCHF", "CADJPY", "CHFJPY",
           "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD", "GBPAUD",
           "GBPCAD", "GBPCHF", "GBPJPY", "GBPUSD", "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD",
           "USDCAD", "USDCHF", "USDJPY", "XAGUSD", "XAUUSD")
METALS = ("XAUUSD", "XAGUSD")
TIMEFRAMES = ("H1", "H4", "D1")
EXPORT_FROM = datetime(1970, 1, 1, tzinfo=timezone.utc)
EXPORT_TO = datetime(2026, 10, 1, 23, 59, tzinfo=timezone.utc)   # server wall time; FINAL_OOS end
RAW_COLUMNS = ["time_server", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
BAR_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread_px", "utc_suspect"]
DAILY_ONLY_RUN = 5            # sessions with a single H4 bar in a row mark daily-only history
TRAIN_D1_END = "2020-12-31 22:00:00+00:00"     # 17:00 New York close of 2020-12-31
REOPEN_HOUR_NY = {"fx": 17, "metal": 18}
CALIBRATION_UTC = (datetime(2026, 10, 5, tzinfo=timezone.utc), datetime(2026, 10, 9, 21, tzinfo=timezone.utc))
CALIBRATION_REQUEST_SERVER = (datetime(2026, 10, 4, tzinfo=timezone.utc), datetime(2026, 10, 11, tzinfo=timezone.utc))


class OutputExistsError(RuntimeError):
    """Raw and built files are write-once."""


def check_symbol_list() -> None:
    with BREADTH_CSV.open(encoding="utf-8") as fh:
        kept = sorted(r["symbol"] for r in csv.DictReader(fh) if r["kept"] == "True")
    if kept != sorted(SYMBOLS):
        raise ValueError(f"SYMBOLS differ from breadth_metadata.csv kept list: {kept}")


def raw_path(sym: str, tf: str) -> Path:
    return RAW / f"{sym}_{tf}_server.csv"


def bar_path(sym: str, tf: str) -> Path:
    return BARS / f"{sym}_{tf}.parquet"


# ---------------------------------------------------------------- export (MT5)
def export() -> None:
    import MetaTrader5 as mt5
    check_symbol_list()
    if not mt5.initialize():
        raise RuntimeError(f"MT5 not reachable: {mt5.last_error()}")
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            for tf in TIMEFRAMES:
                path = raw_path(sym, tf)
                if path.exists():
                    print(f"{sym} {tf}: exists, kept (raw files are write-once)")
                    continue
                r = None
                for _ in range(6):
                    r = mt5.copy_rates_range(sym, getattr(mt5, f"TIMEFRAME_{tf}"), EXPORT_FROM, EXPORT_TO)
                    if r is not None and len(r):
                        break
                    time.sleep(2)
                if r is None or not len(r):
                    raise RuntimeError(f"{sym} {tf}: no bars ({mt5.last_error()})")
                df = pd.DataFrame(r)
                df["time_server"] = pd.to_datetime(df["time"], unit="s", utc=True)
                tmp = path.with_suffix(".partial")
                df[RAW_COLUMNS].to_csv(tmp, index=False)
                tmp.rename(path)
                print(f"{sym} {tf}: {len(df)} bars {df.time_server.iloc[0]:%Y-%m-%d} -> {df.time_server.iloc[-1]:%Y-%m-%d}")
    finally:
        mt5.shutdown()


# ---------------------------------------------------------------- build (pure)
def convert(raw: pd.DataFrame, point: float) -> pd.DataFrame:
    out = pd.DataFrame({"time": server_to_utc(raw["time_server"])})
    for c in ("open", "high", "low", "close", "tick_volume"):
        out[c] = raw[c].astype(float).to_numpy()
    out["spread_px"] = raw["spread"].astype(float).to_numpy() * point
    out["utc_suspect"] = False
    if not out["time"].is_monotonic_increasing or out["time"].duplicated().any():
        raise ValueError("converted times are not unique and increasing")
    return out[BAR_COLUMNS]


def d1_from_h4(h4: pd.DataFrame) -> pd.DataFrame:
    d1 = daily_bars(h4.rename(columns={"spread_px": "spread_usd"}))
    return d1.rename(columns={"spread_usd": "spread_px"})


def intraday_start(d1: pd.DataFrame) -> pd.Timestamp:
    """First session after the last run of >= DAILY_ONLY_RUN single-H4-bar sessions."""
    single = (d1["n_h4"] == 1).to_numpy()
    run, last_end = 0, -1
    for i, s in enumerate(single):
        run = run + 1 if s else 0
        if run >= DAILY_ONLY_RUN:
            last_end = i
    while last_end + 1 < len(single) and single[last_end + 1]:
        last_end += 1
    return d1["session"].iloc[last_end + 1]


def build(points: dict[str, float]) -> dict:
    from research.dataset_access import _fingerprint
    existing = [str(bar_path(s, tf)) for s in SYMBOLS for tf in TIMEFRAMES if bar_path(s, tf).exists()]
    if existing:
        raise OutputExistsError(f"refusing to overwrite {len(existing)} built files, e.g. {existing[0]}")
    BARS.mkdir(parents=True, exist_ok=True)
    record = {"rule": "server time before 2020-07-01: (server - 7 h) in America/New_York; "
                      "from 2020-07-01: server time in Europe/Athens; converted to UTC",
              "d1": "built from H4 at the 17:00 New York boundary (gold/data/broker_daily.py)",
              "spread_px": "MT5 bar spread x point, quote-currency price units",
              "export_to_server": EXPORT_TO.isoformat(), "symbols": {}}
    for sym in SYMBOLS:
        frames = {tf: convert(pd.read_csv(raw_path(sym, tf)), points[sym]) for tf in ("H1", "H4")}
        frames["D1"] = d1_from_h4(frames["H4"])
        entry = {"raw_sha256": {tf: hashlib.sha256(raw_path(sym, tf).read_bytes()).hexdigest()
                                for tf in TIMEFRAMES},
                 "point": points[sym], "frames": {},
                 "intraday_start": str(intraday_start(frames["D1"]).date())}
        for tf, df in frames.items():
            df.to_parquet(bar_path(sym, tf), index=False)
            entry["frames"][tf] = {"values_sha256": _fingerprint(df), "rows": len(df),
                                   "first_utc": df["time"].iloc[0].isoformat(),
                                   "last_utc": df["time"].iloc[-1].isoformat()}
        record["symbols"][sym] = entry
        print(f"{sym}: H4 {len(frames['H4'])}, D1 {len(frames['D1'])}, intraday from {entry['intraday_start']}")
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def split_manifest() -> dict:
    v1b = json.loads(V1B_MANIFEST.read_text(encoding="utf-8"))
    return {
        "status": "H12 split: DEV and FINAL_OOS copied from research/research_split_manifest_h1_v1b.json",
        "dataset": "data/h12_v1/bars, fingerprints in research/h12_fingerprints.json",
        "FINAL_OOS_LOCKED": v1b["FINAL_OOS_LOCKED"],
        "oos_authorisation_token": v1b["oos_authorisation_token"],
        "oos_unlock_requirements": v1b["oos_unlock_requirements"],
        "oos_prohibitions": v1b["oos_prohibitions"],
        "purge_embargo": v1b["purge_embargo"],
        "membership_rule": "D1 sessions wholly inside [from_utc, to_utc]; H1/H4 bars with "
                           "from_utc <= open <= to_utc",
        "arms": {"TRAIN_D1": {"from_utc": "1970-01-01 00:00:00+00:00", "to_utc": TRAIN_D1_END,
                              "note": "each symbol's own start -> the 2020-12-31 17:00 New York close"},
                 "DEV": v1b["arms"]["DEV"], "FINAL_OOS": v1b["arms"]["FINAL_OOS"]},
        "enforcement": "gold/data/store.load_h12 raises research.dataset_access.OOSLockedError on "
                       "any FINAL_OOS read without the manifest token",
    }


# ---------------------------------------------------------------- clock check (timestamps only)
def us_eu_mismatch(t: pd.Series) -> pd.Series:
    from zoneinfo import ZoneInfo
    us = t.dt.tz_convert(NEW_YORK).map(lambda x: bool(x.dst()))
    eu = t.dt.tz_convert(ZoneInfo("Europe/London")).map(lambda x: bool(x.dst()))
    return us != eu


def weekend_reopens(h1_time: pd.Series) -> pd.DataFrame:
    """First H1 bar after each gap of >= 24 h: UTC time, New York hour, month."""
    t = h1_time.reset_index(drop=True)
    first = t[(t.diff() >= pd.Timedelta(hours=24)).to_numpy()]
    ny = first.dt.tz_convert(NEW_YORK)
    return pd.DataFrame({"time": first.to_numpy(), "ny_hour": ny.dt.hour.to_numpy(),
                         "month": ny.dt.strftime("%Y-%m").to_numpy(),
                         "us_eu_mismatch": us_eu_mismatch(first).to_numpy()})


def clock_check(sym: str, h1_time: pd.Series, start: pd.Timestamp) -> dict:
    """Months in which the most common weekend-reopen New York hour differs from the
    expected one (FX 17:00, metals 18:00); weeks when only the US is on summer time are
    tallied separately, because there the server clock and New York differ by 6 h."""
    kind = "metal" if sym in METALS else "fx"
    ev = weekend_reopens(h1_time)
    ev = ev[ev["time"] >= start]
    normal = ev[~ev["us_eu_mismatch"]]
    modes = normal.groupby("month")["ny_hour"].agg(lambda s: int(s.mode().iloc[0]))
    expected = REOPEN_HOUR_NY[kind]
    off = modes[modes != expected]
    mism = ev[ev["us_eu_mismatch"]]
    return {"expected_ny_hour": expected, "months": int(len(modes)),
            "months_off": {m: int(h) for m, h in off.items()},
            "weeks": int(len(ev)), "weeks_at_expected": int((normal["ny_hour"] == expected).sum()),
            "mismatch_weeks_hours": {int(k): int(v) for k, v in mism["ny_hour"].value_counts().items()}}


# ---------------------------------------------------------------- costs (outside every arm)
def tick_spread_bp(ticks: pd.DataFrame) -> float:
    t = ticks[(ticks["bid"] > 0) & (ticks["ask"] >= ticks["bid"])]
    return float(((t["ask"] - t["bid"]) / t["bid"] * 1e4).median())


def costs() -> dict:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 not reachable: {mt5.last_error()}")
    out = {"window_utc": [d.isoformat() for d in CALIBRATION_UTC],
           "outside_every_arm": "after FINAL_OOS ends 2026-10-01",
           "method": "median over ticks of (ask - bid) / bid, in bp", "symbols": {}}
    swaps = {}
    with BREADTH_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["symbol"] in SYMBOLS:
                swaps[r["symbol"]] =(float(r["swap_long_annual"]), float(r["swap_short_annual"]), r["swap_mode"])
    try:
        for sym in SYMBOLS:
            raw = mt5.copy_ticks_range(sym, *CALIBRATION_REQUEST_SERVER, mt5.COPY_TICKS_ALL)
            if raw is None or not len(raw):
                raise RuntimeError(f"{sym}: no ticks ({mt5.last_error()})")
            tk = pd.DataFrame(raw)
            t = server_to_utc(pd.Series(pd.to_datetime(tk["time_msc"], unit="ms", utc=True)))
            sel = ((t >= CALIBRATION_UTC[0]) & (t < CALIBRATION_UTC[1])).to_numpy()
            ticks = pd.DataFrame({"bid": tk["bid"].to_numpy()[sel], "ask": tk["ask"].to_numpy()[sel]})
            sl, ss, mode = swaps[sym]
            out["symbols"][sym] = {"tick_spread_median_bp": round(tick_spread_bp(ticks), 4),
                                   "ticks": int(len(ticks)),
                                   "swap_long_annual": sl, "swap_short_annual": ss, "swap_mode": mode}
            print(f"{sym}: {out['symbols'][sym]}")
    finally:
        mt5.shutdown()
    out["swap_source"] = "research/v2/breadth_metadata.csv (MT5 symbol_info, 2026-10-13), annual fraction of notional"
    COSTS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "export":
        export()
    elif cmd == "build":
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError("MT5 needed for symbol points")
        try:
            pts = {s: mt5.symbol_info(s).point for s in SYMBOLS}
        finally:
            mt5.shutdown()
        build(pts)
        MANIFEST.write_text(json.dumps(split_manifest(), indent=2) + "\n", encoding="utf-8")
    elif cmd == "check":
        from gold.data.store import load_h12
        res = {}
        for sym in SYMBOLS:
            start = pd.Timestamp(json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
                                 ["symbols"][sym]["intraday_start"], tz="UTC")
            h1 = pd.concat([load_h12(sym, "H1", a) for a in ("TRAIN_D1", "DEV")], ignore_index=True)
            res[sym] = clock_check(sym, h1["time"], start)
            print(sym, {k: v for k, v in res[sym].items() if k != "months_off"},
                  "months_off:", res[sym]["months_off"])
        rec = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
        rec["clock_check_train_dev"] = res
        FINGERPRINTS.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    elif cmd == "costs":
        costs()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
