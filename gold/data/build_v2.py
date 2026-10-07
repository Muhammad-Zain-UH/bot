"""Build the V2 bar frames from M1 bid and ask candles of any source.

Source-independent: `build_m1` takes two candle frames with columns
time (UTC, bar open), open, high, low, close, volume -- one for bid, one for
ask -- whether they came from the dukascopy-node CLI (`read_cli_csv`) or from
decoded S3 ticks (`gold.data.ticks`). Everything downstream sees one schema:

    time, bid_o, bid_h, bid_l, bid_c, ask_o, ask_h, ask_l, ask_c,
    mid_o, mid_h, mid_l, mid_c, spread_c, volume

mid = (bid + ask) / 2 per field; spread_c = ask_c - bid_c. volume is the bid
candle's volume (for ticks, the tick count; both sides carry the same count).

`resample` builds M15, H1, H4 (left-closed, left-labelled, UTC) and D1 with the
day boundary at 17:00 America/New_York. Each bar's bid and ask OHLC aggregate
the M1 bars; mid and spread are recomputed from them by the same formulas.

    venv\\Scripts\\python.exe -m gold.data.build_v2 --source s3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
V2_ROOT = REPO / "data" / "dukascopy_v1"
BARS_DIR = V2_ROOT / "bars"
META_DIR = V2_ROOT / "meta"
FINGERPRINTS = REPO / "research" / "dukascopy_v1_fingerprints.json"

NEW_YORK = ZoneInfo("America/New_York")
D1_BOUNDARY_HOUR_NY = 17
CANDLE_COLUMNS = ["time", "open", "high", "low", "close", "volume"]
OHLC = ("o", "h", "l", "c")
PRICE_COLUMNS = [f"{side}_{f}" for side in ("bid", "ask", "mid") for f in OHLC]
COLUMNS = ["time", *PRICE_COLUMNS, "spread_c", "volume"]
INTRADAY_FREQ = {"M15": "15min", "H1": "1h", "H4": "4h"}
TIMEFRAMES = ("M1", "M15", "H1", "H4", "D1")
TF_DURATION = {"M1": pd.Timedelta(minutes=1), "M15": pd.Timedelta(minutes=15),
               "H1": pd.Timedelta(hours=1), "H4": pd.Timedelta(hours=4),
               "D1": pd.Timedelta(days=1)}


def _utc_ns(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True).astype("datetime64[ns, UTC]")


def read_cli_csv(paths: list[Path]) -> pd.DataFrame:
    """Read dukascopy-node CSV months (timestamp in epoch ms) into candles."""
    frames = [pd.read_csv(p) for p in sorted(paths)]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["time"] = _utc_ns(pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True))
    return df[CANDLE_COLUMNS].sort_values("time", ignore_index=True)


def is_flat(c: pd.DataFrame) -> pd.Series:
    """Zero-volume candle with open == high == low == close (market closed)."""
    return ((c["volume"] == 0) & (c["open"] == c["high"])
            & (c["open"] == c["low"]) & (c["open"] == c["close"]))


def build_m1(bid: pd.DataFrame, ask: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inner-join bid and ask candles on time after excluding flat candles.

    Returns (m1, report) where report has one row per UTC year: input rows,
    flats removed, and rows dropped from each side for lack of a partner.
    """
    sides = {}
    for name, c in (("bid", bid), ("ask", ask)):
        c = c[CANDLE_COLUMNS].copy()
        c["time"] = _utc_ns(c["time"])
        flat = is_flat(c)
        sides[name] = (c, flat)
    bid_c, ask_c = sides["bid"][0][~sides["bid"][1]], sides["ask"][0][~sides["ask"][1]]
    m1 = bid_c.rename(columns={"open": "bid_o", "high": "bid_h", "low": "bid_l",
                               "close": "bid_c"}).merge(
        ask_c.drop(columns="volume").rename(columns={"open": "ask_o", "high": "ask_h",
                                                     "low": "ask_l", "close": "ask_c"}),
        on="time", how="inner", validate="one_to_one")
    for f in OHLC:
        m1[f"mid_{f}"] = (m1[f"bid_{f}"] + m1[f"ask_{f}"]) / 2
    m1["spread_c"] = m1["ask_c"] - m1["bid_c"]
    m1 = m1[COLUMNS].sort_values("time", ignore_index=True)

    joined = set(m1["time"])
    rows = []
    for name in ("bid", "ask"):
        c, flat = sides[name]
        kept = c[~flat]
        rows.append(pd.DataFrame({
            "year": c["time"].dt.year, "side": name, "rows": 1, "flats": flat.astype(int),
            "unmatched": (~flat & ~c["time"].isin(joined)).astype(int)}))
    report = (pd.concat(rows).groupby(["year", "side"])[["rows", "flats", "unmatched"]]
              .sum().unstack("side"))
    report.columns = [f"{side}_{what}" for what, side in report.columns]
    report["joined"] = m1.groupby(m1["time"].dt.year).size()
    return m1, report.fillna(0).astype(int).reset_index()


def d1_session_open(time: pd.Series) -> pd.Series:
    """UTC open of the 17:00-New-York trading day containing each timestamp."""
    wall = time.dt.tz_convert(NEW_YORK).dt.tz_localize(None)
    open_wall = (wall - pd.Timedelta(hours=D1_BOUNDARY_HOUR_NY)).dt.normalize() \
        + pd.Timedelta(hours=D1_BOUNDARY_HOUR_NY)
    return open_wall.dt.tz_localize(NEW_YORK).dt.tz_convert("UTC").astype("datetime64[ns, UTC]")


def bar_open(time: pd.Series, tf: str) -> pd.Series:
    if tf == "D1":
        return d1_session_open(time)
    return time.dt.floor(INTRADAY_FREQ[tf])


def resample(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Aggregate M1 to tf; a bar exists only where at least one M1 bar exists."""
    if tf == "M1":
        return m1[COLUMNS].copy()
    agg = {"volume": "sum"}
    for side in ("bid", "ask"):
        agg.update({f"{side}_o": "first", f"{side}_h": "max",
                    f"{side}_l": "min", f"{side}_c": "last"})
    out = m1.groupby(bar_open(m1["time"], tf).rename("time"), sort=True).agg(agg).reset_index()
    for f in OHLC:
        out[f"mid_{f}"] = (out[f"bid_{f}"] + out[f"ask_{f}"]) / 2
    out["spread_c"] = out["ask_c"] - out["bid_c"]
    return out[COLUMNS]


def build_all(bid: pd.DataFrame, ask: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """M1 join plus every resampled frame, validated. Raises on any failure."""
    from gold.data.validate_v2 import validate_frame
    m1, join_report = build_m1(bid, ask)
    frames = {tf: resample(m1, tf) for tf in TIMEFRAMES}
    for tf, df in frames.items():
        validate_frame(df, tf)
    return frames, join_report


def _load_source(source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if source == "cli":
        raw = V2_ROOT / "raw"
        return (read_cli_csv(list((raw / "bid").rglob("*.csv"))),
                read_cli_csv(list((raw / "ask").rglob("*.csv"))))
    from gold.data.download_dukascopy_s3 import load_tick_candles
    return load_tick_candles()


def main(argv: list[str] | None = None) -> int:
    from research.dataset_access import _fingerprint
    from gold.data.validate_v2 import price_sanity, report_figures
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("s3", "cli"), required=True)
    args = ap.parse_args(argv)
    bid, ask = _load_source(args.source)
    frames, join_report = build_all(bid, ask)
    price_sanity(frames["M1"])
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    record = {"source": args.source, "columns": COLUMNS, "frames": {}}
    for tf, df in frames.items():
        df.to_parquet(BARS_DIR / f"XAUUSD_{tf}.parquet", index=False)
        record["frames"][tf] = {"values_sha256": _fingerprint(df[COLUMNS]), "rows": len(df),
                                "first_utc": df["time"].iloc[0].isoformat(),
                                "last_utc": df["time"].iloc[-1].isoformat()}
    join_report.to_csv(META_DIR / "join_report.csv", index=False)
    (META_DIR / "report_figures.json").write_text(
        json.dumps(report_figures(frames["M1"]), indent=2), encoding="utf-8")
    old = json.loads(FINGERPRINTS.read_text(encoding="utf-8")) if FINGERPRINTS.exists() else {}
    record = {**old, **record}                  # keeps "cost_calibration" if present
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["frames"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
