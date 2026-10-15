"""H13 -- round-number levels (Osler 2003). Events and variables only, no statistics.

Levels: round = multiples of $50; control = multiples of $50 plus $17 and plus $33.
A fresh touch from below at level L is H1 bar t with high[t] >= L, close[t-1] < L and every
high in bars t-24 .. t-1 below L; from above mirrors it with lows (low[t] <= L, close[t-1] > L,
every low in t-24 .. t-1 above L). d = +1 from below, -1 from above. Bar offsets count bars in
the data (a window may span a weekend). An event needs bars t-24 .. t+4 inside the given frame
(one arm), none utc_suspect. A bar touching several levels gives one event per level.

H13a: y = -d x log(close[t+4] / L).
H13b: events with d x (close[t] - L) > 0; y = d x log(close[t+4] / close[t]).
Pure functions, no I/O.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

STEP_USD = 50.0
CONTROL_OFFSETS_USD = (17.0, 33.0)
LOOKBACK_BARS = 24
HORIZON_BARS = 4


def levels(low: float, high: float) -> pd.DataFrame:
    """All round and control levels between low and high."""
    k0, k1 = math.floor(low / STEP_USD) - 1, math.ceil(high / STEP_USD) + 1
    rows = []
    for k in range(k0, k1 + 1):
        rows.append((k * STEP_USD, "round"))
        rows.extend((k * STEP_USD + o, "control") for o in CONTROL_OFFSETS_USD)
    lv = pd.DataFrame(rows, columns=["level", "kind"])
    return lv[(lv.level >= low) & (lv.level <= high)].reset_index(drop=True)


def _rolling_prev(a: np.ndarray, n: int, fn) -> np.ndarray:
    """fn over the n values before each index (NaN where fewer than n exist)."""
    s = pd.Series(a).shift(1).rolling(n, min_periods=n)
    return (s.max() if fn == "max" else s.min()).to_numpy()


def events(h1: pd.DataFrame) -> pd.DataFrame:
    """Every fresh touch in h1 (one arm): index t, time, level, kind, d, and the prices and
    spreads the variables and costs need."""
    h1 = h1.reset_index(drop=True)
    hi, lo, cl = (h1[c].to_numpy(float) for c in ("high", "low", "close"))
    suspect = h1["utc_suspect"].to_numpy(bool) if "utc_suspect" in h1 else np.zeros(len(h1), bool)
    spread = h1["spread_usd"].to_numpy(float) if "spread_usd" in h1 else np.full(len(h1), np.nan)
    n = len(h1)
    prev_close = np.concatenate([[np.nan], cl[:-1]])
    max_prev = _rolling_prev(hi, LOOKBACK_BARS, "max")
    min_prev = _rolling_prev(lo, LOOKBACK_BARS, "min")
    win = LOOKBACK_BARS + HORIZON_BARS + 1
    bad = pd.Series(suspect.astype(int)).rolling(win, min_periods=1).sum().shift(-HORIZON_BARS).to_numpy()
    idx = np.arange(n)
    valid = (idx >= LOOKBACK_BARS) & (idx + HORIZON_BARS < n)
    valid &= np.nan_to_num(bad, nan=1) == 0
    out = []
    for lv in levels(np.nanmin(lo), np.nanmax(hi)).itertuples():
        L = lv.level
        up = valid & (hi >= L) & (prev_close < L) & (max_prev < L)
        dn = valid & (lo <= L) & (prev_close > L) & (min_prev > L)
        for mask, d in ((up, 1), (dn, -1)):
            t = np.flatnonzero(mask)
            if len(t):
                out.append(pd.DataFrame({"t": t, "level": L, "kind": lv.kind, "d": d}))
    if not out:
        return pd.DataFrame(columns=["t", "time", "level", "kind", "d", "close_t", "close_t4",
                                     "spread_t", "spread_t4"])
    ev = pd.concat(out, ignore_index=True).sort_values(["t", "level"], ignore_index=True)
    t = ev["t"].to_numpy()
    ev["time"] = h1["time"].to_numpy()[t]
    ev["close_t"] = cl[t]
    ev["close_t4"] = cl[t + HORIZON_BARS]
    ev["spread_t"] = spread[t]
    ev["spread_t4"] = spread[t + HORIZON_BARS]
    ev["time_t4"] = h1["time"].to_numpy()[t + HORIZON_BARS]
    return ev


def h13a(ev: pd.DataFrame) -> pd.DataFrame:
    out = ev.copy()
    out["y"] = -out["d"] * np.log(out["close_t4"] / out["level"])
    return out


def h13b(ev: pd.DataFrame) -> pd.DataFrame:
    out = ev[(ev["d"] * (ev["close_t"] - ev["level"])) > 0].copy()
    out["y"] = out["d"] * np.log(out["close_t4"] / out["close_t"])
    return out.reset_index(drop=True)
