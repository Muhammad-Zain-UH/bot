"""Live data from 2026-10-01 to the export moment: MT5 H1/H4 for six symbols and three FRED
series, into data/live_2026q4/ (gitignored, write-once). Exploratory use only (FINAL_OOS opened
2026-10-14 by owner decision).

    venv\\Scripts\\python.exe -m gold.data.build_live_2026q4

Raw: data/live_2026q4/raw_server/{SYM}_{TF}_server.csv (server time as delivered, never
overwritten). Built: data/live_2026q4/bars/{SYM}_{TF}.parquet with the v1b clock rule
(gold.data.build_h12.convert); bars still forming at the export moment are dropped. FRED:
data/live_2026q4/fred/{ID}.csv. Fingerprints and the overlap check against the existing v1b / H12
bars on 2026-10-01: research/v2026/live_2026q4_fingerprints.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from gold.data.build_h12 import RAW_COLUMNS, convert

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "data" / "live_2026q4"
RAW, BARS, FRED = ROOT / "raw_server", ROOT / "bars", ROOT / "fred"
FINGERPRINTS = REPO / "research" / "v2026" / "live_2026q4_fingerprints.json"
SYMBOLS = ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD")
TIMEFRAMES = {"H1": timedelta(hours=1), "H4": timedelta(hours=4)}
EXPORT_FROM_SERVER = datetime(2026, 10, 1, tzinfo=timezone.utc)
FRED_SERIES = ("DGS10", "DFII10", "DTWEXBGS")


class OutputExistsError(RuntimeError):
    pass


def main() -> int:
    import MetaTrader5 as mt5
    from research.acquire_cross_asset import fetch
    from research.dataset_access import _fingerprint
    existing = [p for p in list(RAW.glob("*.csv")) + list(BARS.glob("*.parquet")) + list(FRED.glob("*.csv"))]
    if existing:
        raise OutputExistsError(f"refusing to overwrite {len(existing)} files in {ROOT}")
    for d in (RAW, BARS, FRED):
        d.mkdir(parents=True, exist_ok=True)
    if not mt5.initialize():
        raise RuntimeError(f"MT5 not reachable: {mt5.last_error()}")
    record = {"exported_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "server": None, "rule": "v1b clock rule (Europe/Athens after 2020-07-01)",
              "use": "exploratory only; FINAL_OOS opened 2026-10-14", "symbols": {}, "fred": {}}
    try:
        record["server"] = mt5.account_info().server
        # MT5 takes server wall time; ask a day ahead so the latest bars are included
        to_server = datetime.now(timezone.utc) + timedelta(days=1)
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            point = mt5.symbol_info(sym).point
            record["symbols"][sym] = {"point": point, "frames": {}}
            for tf, length in TIMEFRAMES.items():
                r = None
                for _ in range(6):
                    r = mt5.copy_rates_range(sym, getattr(mt5, f"TIMEFRAME_{tf}"), EXPORT_FROM_SERVER, to_server)
                    if r is not None and len(r):
                        break
                    time.sleep(2)
                if r is None or not len(r):
                    raise RuntimeError(f"{sym} {tf}: no bars ({mt5.last_error()})")
                df = pd.DataFrame(r)
                df["time_server"] = pd.to_datetime(df["time"], unit="s", utc=True)
                raw_path = RAW / f"{sym}_{tf}_server.csv"
                df[RAW_COLUMNS].to_csv(raw_path, index=False)
                bars = convert(df[RAW_COLUMNS].astype({"time_server": str}), point)
                export_moment = pd.Timestamp(record["exported_utc"])
                complete = bars["time"] + length <= export_moment
                bars = bars[complete].reset_index(drop=True)
                if sym == "XAUUSD":
                    bars["spread_usd"] = bars["spread_px"]          # XAUUSD is quoted in USD
                bars.to_parquet(BARS / f"{sym}_{tf}.parquet", index=False)
                record["symbols"][sym]["frames"][tf] = {
                    "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    "values_sha256": _fingerprint(bars), "rows": len(bars),
                    "dropped_incomplete": int((~complete).sum()),
                    "first_utc": bars["time"].iloc[0].isoformat(), "last_utc": bars["time"].iloc[-1].isoformat()}
                print(sym, tf, record["symbols"][sym]["frames"][tf]["rows"], bars["time"].iloc[-1])
    finally:
        mt5.shutdown()
    for sid in FRED_SERIES:
        body = fetch(sid)
        (FRED / f"{sid}.csv").write_bytes(body)
        f = pd.read_csv(FRED / f"{sid}.csv")
        vals = pd.to_numeric(f.iloc[:, 1], errors="coerce")
        record["fred"][sid] = {"sha256": hashlib.sha256(body).hexdigest(), "rows": len(f),
                               "last_date": str(f.iloc[:, 0][vals.notna()].iloc[-1])}
        print(sid, record["fred"][sid])
    record["overlap_check_2026_10_01"] = overlap_check()
    FINGERPRINTS.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0


def overlap_check() -> dict:
    """Bars present both here and in the existing datasets (2026-10-01): max |difference|."""
    from gold.data.store import load_broker_v1b, load_h12
    token = "OPENED-2026-10-14-EXPLORATION"
    out = {}
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            new = pd.read_parquet(BARS / f"{sym}_{tf}.parquet")
            if sym == "XAUUSD":
                old = load_broker_v1b(tf, "FINAL_OOS", token)
            elif tf in ("H1", "H4"):
                old = load_h12(sym, tf, "FINAL_OOS", token)
            j = new.merge(old, on="time", suffixes=("_new", "_old"))
            diff = max(float((j[f"{c}_new"] - j[f"{c}_old"]).abs().max()) for c in ("open", "high", "low", "close")) if len(j) else None
            out[f"{sym} {tf}"] = {"overlapping_bars": int(len(j)), "max_abs_ohlc_diff": diff}
    return out


SYNC_WAIT_S = 90


def export_batch2() -> int:
    """Second export with a sync check; write-once like batch 1; recorded under "batch2"."""
    import MetaTrader5 as mt5
    from research.dataset_access import _fingerprint
    raw2, bars2 = ROOT / "b2" / "raw_server", ROOT / "b2" / "bars"
    if list(raw2.glob("*")) or list(bars2.glob("*")):
        raise OutputExistsError(f"refusing to overwrite {ROOT / 'b2'}")
    raw2.mkdir(parents=True, exist_ok=True)
    bars2.mkdir(parents=True, exist_ok=True)
    rec = {"exported_utc": None, "frames": {}, "superset_of_batch1": {}}
    if not mt5.initialize():
        raise RuntimeError(f"MT5 not reachable: {mt5.last_error()}")
    try:
        to_server = datetime.now(timezone.utc) + timedelta(days=1)
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            point = mt5.symbol_info(sym).point
            for tf, length in TIMEFRAMES.items():
                deadline, r = time.time() + SYNC_WAIT_S, None
                while True:
                    r = mt5.copy_rates_range(sym, getattr(mt5, f"TIMEFRAME_{tf}"), EXPORT_FROM_SERVER, to_server)
                    tick = mt5.symbol_info_tick(sym)
                    if r is not None and len(r) and tick is not None and                             int(r["time"][-1]) + 2 * length.total_seconds() > tick.time:
                        break
                    if time.time() > deadline:
                        raise RuntimeError(f"{sym} {tf}: history not synced after {SYNC_WAIT_S}s")
                    time.sleep(3)
                df = pd.DataFrame(r)
                df["time_server"] = pd.to_datetime(df["time"], unit="s", utc=True)
                raw_path = raw2 / f"{sym}_{tf}_server.csv"
                df[RAW_COLUMNS].to_csv(raw_path, index=False)
                bars = convert(df[RAW_COLUMNS].astype({"time_server": str}), point)
                moment = pd.Timestamp(datetime.now(timezone.utc))
                complete = bars["time"] + length <= moment
                bars = bars[complete].reset_index(drop=True)
                if sym == "XAUUSD":
                    bars["spread_usd"] = bars["spread_px"]
                bars.to_parquet(bars2 / f"{sym}_{tf}.parquet", index=False)
                b1 = pd.read_parquet(BARS / f"{sym}_{tf}.parquet")
                j = b1.merge(bars, on="time", suffixes=("_1", "_2"))
                same = len(j) == len(b1) and all((j[f"{c}_1"] == j[f"{c}_2"]).all()
                                                for c in ("open", "high", "low", "close"))
                rec["frames"][f"{sym} {tf}"] = {"raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                                               "values_sha256": _fingerprint(bars), "rows": len(bars),
                                               "dropped_incomplete": int((~complete).sum()),
                                               "last_utc": bars["time"].iloc[-1].isoformat()}
                rec["superset_of_batch1"][f"{sym} {tf}"] = bool(same)
                print(sym, tf, len(bars), bars["time"].iloc[-1], "superset of batch 1:", same)
        rec["exported_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    finally:
        mt5.shutdown()
    record = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    record["batch2"] = rec
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0 if all(rec["superset_of_batch1"].values()) else 1


if __name__ == "__main__":
    sys.exit(export_batch2() if sys.argv[1:] == ["b2"] else main())
