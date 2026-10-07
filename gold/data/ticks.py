"""Decode Dukascopy daily tick files (DD_ticks.bi5) and build M1 bid/ask candles.

A .bi5 file is LZMA-compressed; the payload is 20-byte big-endian records:
uint32 ms offset, uint32 ask, uint32 bid, float32 ask volume, float32 bid volume.
Prices are integer points divided by PRICE_DIVISOR.

M1 candles: bid OHLC from bid ticks, ask OHLC from ask ticks, volume = tick
count, no bar for a minute without ticks. Both sides come from the same ticks,
so the build's spread_c = ask_c - bid_c is last ask minus last bid.
"""
from __future__ import annotations

import datetime as dt
import lzma

import numpy as np
import pandas as pd

# VERIFY ON FIRST REAL FILE: XAUUSD points per USD. The jetta feed used by the
# CLI reports multiplier 0.001 for XAU-USD, so 1,000 is expected; price_sanity
# in the build catches a wrong value.
PRICE_DIVISOR = 1000.0
# VERIFY ON FIRST REAL FILE: offsets are milliseconds since this UTC time on the
# file's calendar day (the S3 export documents "ms from day start").
OFFSET_ORIGIN_UTC = dt.time(0, 0)

RECORD = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
                   ("ask_volume", ">f4"), ("bid_volume", ">f4")])
TICK_COLUMNS = ["time", "ask", "bid", "ask_volume", "bid_volume"]


def decode_bi5(raw: bytes, day: dt.date) -> pd.DataFrame:
    """Ticks of one day, time-sorted, prices in USD per oz. Raises ValueError on a
    corrupt file (bad LZMA stream or a payload that is not whole records)."""
    if not raw:
        payload = b""
    else:
        try:
            payload = lzma.decompress(raw)
        except lzma.LZMAError as exc:
            raise ValueError(f"{day}: not a valid LZMA stream: {exc}") from exc
    if len(payload) % RECORD.itemsize:
        raise ValueError(f"{day}: payload of {len(payload)} bytes is not whole "
                         f"{RECORD.itemsize}-byte records")
    rec = np.frombuffer(payload, dtype=RECORD)
    origin = pd.Timestamp(dt.datetime.combine(day, OFFSET_ORIGIN_UTC), tz="UTC")
    df = pd.DataFrame({
        "time": origin + pd.to_timedelta(rec["ms"].astype("int64"), unit="ms"),
        "ask": rec["ask"].astype("float64") / PRICE_DIVISOR,
        "bid": rec["bid"].astype("float64") / PRICE_DIVISOR,
        "ask_volume": rec["ask_volume"].astype("float64"),
        "bid_volume": rec["bid_volume"].astype("float64"),
    })
    df["time"] = df["time"].astype("datetime64[ns, UTC]")
    return df.sort_values("time", kind="stable", ignore_index=True)


def ticks_to_m1(ticks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(bid candles, ask candles) with columns time, open, high, low, close, volume."""
    minute = ticks["time"].dt.floor("1min").rename("time")
    out = []
    for side in ("bid", "ask"):
        g = ticks.groupby(minute, sort=True)[side]
        c = pd.DataFrame({"open": g.first(), "high": g.max(), "low": g.min(),
                          "close": g.last(), "volume": g.size()}).reset_index()
        c["time"] = c["time"].astype("datetime64[ns, UTC]")
        out.append(c[["time", "open", "high", "low", "close", "volume"]])
    return out[0], out[1]
