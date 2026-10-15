"""W01 menu: 102 variants and their trades on H1 bars (research/v2026/W01_SPEC.md §4, exactly).

Every trade has an entry, a stop and a target or time exit, and is scored in net R. Signals form at bar
closes; the reopen bar is never a signal or entry bar. Prices USD per oz (bid bars).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gold.data.broker_daily import session_of
from gold.econ.costs import financing_usd, round_turn_cost_usd
from gold.wf.bars import Bars

K_STOPS = (1.0, 1.5)                 # ATR stop multiples where the rule gives no stop
SIDES = (1, -1)
ATR_N = 14
DONCHIAN_N = (10, 20, 55)
MA_PAIRS = ((10, 50), (20, 100), (50, 200))
RSI_N, RSI_LO, RSI_HI = 2, 10.0, 90.0
BB_N, BB_K = 20, 2.0
MR_HOLD = 5                          # mean reversion: bars
SESSION_RANGE_HOUR = 8               # 08:00 London / 08:00 New York range bar
SESSION_LAST_SIGNAL_NY = 13          # signal bars open before 13:00 New York
SESSION_EXIT_NY = 14                 # exit at the close of the bar opening 14:00 New York
WINDOW = 24                          # sweep / FVG time exit, FVG order life (H1 bars)
FVG_MIN_GAP_ATR = 0.25
FVG_TREND_MA = 50                    # D1 SMA for the FVG trend filter
BLOCKS_NY = (19, 23, 3, 7, 11)
BLOCK_HOURS = 4


@dataclass(frozen=True)
class Variant:
    vid: int
    family: str
    name: str
    side: int
    params: tuple


def menu() -> list[Variant]:
    out = []
    add = lambda fam, name, side, **p: out.append(Variant(len(out), fam, f"{name}_{'L' if side > 0 else 'S'}", side,
                                                          tuple(sorted(p.items()))))
    for tf in ("H1", "D1"):
        for n in DONCHIAN_N:
            for k in K_STOPS:
                for s in SIDES:
                    add("a_donchian", f"donchian_{tf}_N{n}_k{k}", s, tf=tf, n=n, k=k)
    for tf in ("H1", "D1"):
        for f, sl in MA_PAIRS:
            for k in K_STOPS:
                for s in SIDES:
                    add("b_ma_trend", f"ma_{tf}_{f}x{sl}_k{k}", s, tf=tf, fast=f, slow=sl, k=k)
    for rule in ("rsi2", "bollinger"):
        for tf in ("H1", "D1"):
            for k in K_STOPS:
                for s in SIDES:
                    add("c_mean_reversion", f"{rule}_{tf}_k{k}", s, rule=rule, tf=tf, k=k)
    for where in ("london", "newyork"):
        for s in SIDES:
            add("d_session_breakout", f"session_{where}", s, where=where)
    for tgt in ("1R", "2R", "mid"):
        for s in SIDES:
            add("e_sweep", f"sweep_{tgt}", s, target=tgt)
    for tgt in ("1R", "2R"):
        for flt in ("none", "d1ma50"):
            for s in SIDES:
                add("f_fvg", f"fvg_{tgt}_{flt}", s, target=tgt, filter=flt)
    for b in BLOCKS_NY:
        for k in K_STOPS:
            for s in SIDES:
                add("g_time_of_day", f"block{b:02d}_k{k}", s, block=b, k=k)
    return out


# ---------------------------------------------------------------- indicators (value at a bar uses bars <= it)
def atr(h, l, c, n: int = ATR_N) -> np.ndarray:
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def sma(x, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).mean().to_numpy()


def rsi_wilder(c, n: int = RSI_N) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + up / dn)
    r = np.where(dn == 0, 100.0, r)
    r[: n] = np.nan
    return np.asarray(r, dtype=float)


def prev_max(x, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).max().shift(1).to_numpy()


def prev_min(x, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).min().shift(1).to_numpy()


# ---------------------------------------------------------------- trade management
def manage(B: Bars, E: int, entry: float, side: int, stop: float, target: float | None = None, exit_fn=None,
           last: int | None = None, target_on_entry_bar: bool = True) -> tuple[int, float, str]:
    """Walk H1 bars from the entry bar E. Stop first (filled at the stop, or at the open if a later bar opens
    beyond it), then the target (filled at the target), then a signal exit or the time exit at the close."""
    for j in range(E, B.n):
        if side > 0:
            if B.l[j] <= stop:
                return j, (min(B.o[j], stop) if j > E else stop), "stop"
            if target is not None and (j > E or target_on_entry_bar) and B.h[j] >= target:
                return j, target, "target"
        else:
            if B.h[j] >= stop:
                return j, (max(B.o[j], stop) if j > E else stop), "stop"
            if target is not None and (j > E or target_on_entry_bar) and B.l[j] <= target:
                return j, target, "target"
        if exit_fn is not None and exit_fn(j):
            return j, B.c[j], "signal"
        if last is not None and j >= last:
            return j, B.c[j], "time"
    return B.n - 1, B.c[B.n - 1], "end"


def _record(out: list, E: int, X: int, side: int, entry: float, exit_: float, stop: float, why: str) -> None:
    out.append((E, X, side, entry, exit_, stop, why))


def _decision_points(B: Bars, tf: str):
    """Decision bar (signal at its close) and entry bar per decision point."""
    if tf == "H1":
        dec = np.arange(B.n)
        ent = np.where(dec + 1 < B.n, dec + 1, -1)
        bad = np.zeros(B.n, bool)
        bad[:-1] = B.reopen[1:]
        ent = np.where(B.reopen | bad, -1, ent)
        return dec, ent
    dec = B.d1_last.copy()
    ent = np.full(len(dec), -1)
    ent[:-1] = B.d1_entry[1:]
    ent = np.where(ent >= 0, ent, -1)
    return dec, ent


def _series(B: Bars, tf: str):
    if tf == "H1":
        return B.h, B.l, B.c
    d = B.d1
    return d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)


def run_decision(B: Bars, tf: str, side: int, enter, exit_sig, atr_arr, k: float, max_hold: int) -> list:
    """Families a-c: enter at the entry bar after a decision-point signal, stop k x ATR, exit on exit_sig at a
    later decision close or max_hold decision points after the signal."""
    dec, ent = _decision_points(B, tf)
    bar_to_q = np.full(B.n, -1)
    ok = dec >= 0
    bar_to_q[dec[ok]] = np.flatnonzero(ok)
    out, blocked, Q = [], -1, len(dec)
    for q in range(Q):
        if dec[q] < 0 or dec[q] < blocked or not enter[q] or ent[q] < 0 or not np.isfinite(atr_arr[q]):
            continue
        E = ent[q]
        entry = B.o[E]
        stop = entry - side * k * atr_arr[q]
        lq = q + max_hold
        last = dec[lq] if lq < Q and dec[lq] >= 0 else None
        X, px, why = manage(B, E, entry, side, stop, None,
                            lambda j: bar_to_q[j] >= 0 and bool(exit_sig[bar_to_q[j]]), last)
        _record(out, E, X, side, entry, px, stop, why)
        blocked = X
    return out


def family_a(B, v, p):
    h, l, c = _series(B, p["tf"])
    n, half = p["n"], int(np.ceil(p["n"] / 2))
    if v.side > 0:
        enter, exit_sig = c > prev_max(h, n), c < prev_min(l, half)
    else:
        enter, exit_sig = c < prev_min(l, n), c > prev_max(h, half)
    return run_decision(B, p["tf"], v.side, enter, exit_sig, atr(h, l, c), p["k"], 2 * n)


def family_b(B, v, p):
    h, l, c = _series(B, p["tf"])
    f, s = sma(c, p["fast"]), sma(c, p["slow"])
    up = (f > s) & (np.roll(f, 1) <= np.roll(s, 1))
    dn = (f < s) & (np.roll(f, 1) >= np.roll(s, 1))
    up[0] = dn[0] = False
    enter, exit_sig = (up, dn) if v.side > 0 else (dn, up)
    return run_decision(B, p["tf"], v.side, enter, exit_sig, atr(h, l, c), p["k"], p["slow"])


def family_c(B, v, p):
    h, l, c = _series(B, p["tf"])
    m = sma(c, BB_N)
    if p["rule"] == "rsi2":
        r = rsi_wilder(c)
        enter = r < RSI_LO if v.side > 0 else r > RSI_HI
    else:
        sd = pd.Series(c).rolling(BB_N).std(ddof=0).to_numpy()
        enter = c < m - BB_K * sd if v.side > 0 else c > m + BB_K * sd
    exit_sig = c >= m if v.side > 0 else c <= m
    return run_decision(B, p["tf"], v.side, enter, exit_sig, atr(h, l, c), p["k"], MR_HOLD)


def family_d(B, v, p):
    hour = B.ldn_hour if p["where"] == "london" else B.ny_hour
    out = []
    for r in np.flatnonzero((hour == SESSION_RANGE_HOUR) & (B.ny_minute == 0) & ~B.reopen):
        day, hi, lo = B.ny_date[r], B.h[r], B.l[r]
        j = r + 1
        x0 = None
        k = r + 1
        while k < B.n and B.ny_date[k] == day and B.ny_hour[k] <= SESSION_EXIT_NY:
            x0 = k
            k += 1
        if x0 is None:
            continue
        while j < B.n and B.ny_date[j] == day and B.ny_hour[j] < SESSION_LAST_SIGNAL_NY:
            if (v.side > 0 and B.c[j] > hi) or (v.side < 0 and B.c[j] < lo):
                E = j + 1
                if E <= x0 and not B.reopen[E]:
                    entry, stop = B.o[E], (lo if v.side > 0 else hi)
                    if (entry - stop) * v.side > 0:
                        X, px, why = manage(B, E, entry, v.side, stop, None, None, x0)
                        _record(out, E, X, v.side, entry, px, stop, why)
                break
            j += 1
    return out


def family_e(B, v, p):
    d = B.d1
    dh, dl = d["high"].to_numpy(float), d["low"].to_numpy(float)
    dm = (dh + dl) / 2
    out, blocked, used = [], -1, -1
    for i in range(B.n - 1):
        s = B.sess[i]
        if i < blocked or s < 1 or s == used or B.reopen[i] or B.reopen[i + 1] or B.sess[i + 1] != s:
            continue
        if v.side < 0:
            hit, stop = B.h[i] > dh[s - 1] and B.c[i] < dh[s - 1], B.h[i]
        else:
            hit, stop = B.l[i] < dl[s - 1] and B.c[i] > dl[s - 1], B.l[i]
        if not hit:
            continue
        used = s
        E = i + 1
        entry = B.o[E]
        risk = (entry - stop) * v.side
        if risk <= 0:
            continue
        if p["target"] == "mid":
            target = dm[s - 1]
            if (target - entry) * v.side <= 0:
                continue
        else:
            target = entry + v.side * risk * (1.0 if p["target"] == "1R" else 2.0)
        X, px, why = manage(B, E, entry, v.side, stop, target, None, E + WINDOW - 1)
        _record(out, E, X, v.side, entry, px, stop, why)
        blocked = X
    return out


def family_f(B, v, p):
    a = atr(B.h, B.l, B.c)
    d = B.d1
    dc = d["close"].to_numpy(float)
    dma = sma(dc, FVG_TREND_MA)
    out, blocked = [], -1
    for i in range(2, B.n - 1):
        if i < blocked or B.reopen[i - 2] or B.reopen[i - 1] or B.reopen[i] or not np.isfinite(a[i]):
            continue
        if v.side > 0:
            gap, limit, stop = B.l[i] - B.h[i - 2], B.l[i], B.h[i - 2]
        else:
            gap, limit, stop = B.l[i - 2] - B.h[i], B.h[i], B.l[i - 2]
        if gap <= 0 or gap < FVG_MIN_GAP_ATR * a[i]:
            continue
        if p["filter"] == "d1ma50":
            s = B.sess[i]
            if s < 1 or not np.isfinite(dma[s - 1]) or (dc[s - 1] - dma[s - 1]) * v.side <= 0:
                continue
        blocked = min(i + WINDOW + 1, B.n)                  # order life: the next 24 bars
        for j in range(i + 1, min(i + WINDOW + 1, B.n)):
            touched = B.l[j] <= limit if v.side > 0 else B.h[j] >= limit
            if not touched:
                continue
            if B.reopen[j]:
                blocked = j + 1
                break
            fill = min(B.o[j], limit) if v.side > 0 else max(B.o[j], limit)
            risk = (fill - stop) * v.side
            if risk <= 0:
                blocked = j + 1
                break
            target = fill + v.side * risk * (1.0 if p["target"] == "1R" else 2.0)
            X, px, why = manage(B, j, fill, v.side, stop, target, None, j + WINDOW - 1, target_on_entry_bar=False)
            _record(out, j, X, v.side, fill, px, stop, why)
            blocked = X
            break
    return out


def family_g(B, v, p):
    a = atr(B.h, B.l, B.c)
    out = []
    span = np.timedelta64(BLOCK_HOURS, "h")
    for i in np.flatnonzero((B.ny_hour == p["block"]) & (B.ny_minute == 0) & ~B.reopen):
        if i < 1 or not np.isfinite(a[i - 1]):
            continue
        x0 = i
        while x0 + 1 < B.n and not B.reopen[x0 + 1] and B.t[x0 + 1] < B.t[i] + span:
            x0 += 1
        entry = B.o[i]
        stop = entry - v.side * p["k"] * a[i - 1]
        X, px, why = manage(B, i, entry, v.side, stop, None, None, x0)
        _record(out, i, X, v.side, entry, px, stop, why)
    return out


FAMILIES = {"a_donchian": family_a, "b_ma_trend": family_b, "c_mean_reversion": family_c,
            "d_session_breakout": family_d, "e_sweep": family_e, "f_fvg": family_f, "g_time_of_day": family_g}


def trades(B: Bars, v: Variant) -> pd.DataFrame:
    rows = FAMILIES[v.family](B, v, dict(v.params))
    df = pd.DataFrame(rows, columns=["entry_idx", "exit_idx", "side", "entry", "exit", "stop", "reason"])
    df.insert(0, "vid", v.vid)
    times = B.h1["time"]
    df["entry_time"] = times.iloc[df["entry_idx"].to_numpy(int)].to_numpy() if len(df) else times.iloc[:0].to_numpy()
    df["exit_time"] = times.iloc[df["exit_idx"].to_numpy(int)].to_numpy() if len(df) else times.iloc[:0].to_numpy()
    for c in ("entry_time", "exit_time"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


def net_r(tr: pd.DataFrame, B: Bars, dff: pd.Series, k_cost: float, mult: float = 1.0) -> np.ndarray:
    """(side x (exit - entry) - mult x (spread cost + financing)) / |entry - stop|, per trade."""
    if tr.empty:
        return np.array([])
    E, X = tr["entry_idx"].to_numpy(int), tr["exit_idx"].to_numpy(int)
    side = tr["side"].to_numpy(int)
    entry, exit_, stop = (tr[c].to_numpy(float) for c in ("entry", "exit", "stop"))
    cost = round_turn_cost_usd(B.spread[E], B.spread[X], k_cost)
    t = B.h1["time"]
    nights = (session_of(t.iloc[X].reset_index(drop=True)) - session_of(t.iloc[E].reset_index(drop=True))).dt.days.to_numpy()
    days = t.iloc[E].dt.tz_convert(None).dt.normalize()
    dff = dff[~dff.index.duplicated(keep="last")]
    asof = dff.reindex(dff.index.union(pd.DatetimeIndex(days.unique()))).ffill()
    rate = asof.reindex(pd.DatetimeIndex(days)).to_numpy() / 100
    fin = np.where(side > 0, financing_usd(entry, nights, "long", rate), financing_usd(entry, nights, "short", rate))
    return (side * (exit_ - entry) - mult * (cost + fin)) / np.abs(entry - stop)
