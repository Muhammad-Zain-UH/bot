"""H12 -- multi-asset time-series momentum on the broker's tradable universe
(research/v2/H12_SPEC.md, commit 724eb6f). Pure functions, no I/O.

Per symbol i, as H10 (gold/hyp/weekly.py for decisions, execution and daily P&L):
s_i = mean(sign R21, sign R63, sign R252); position_i = s_i x min(2, (0.10 / sqrt(N_t)) / σ63_i),
σ63_i annualised with the symbol's D1 bars per year from the spec. A symbol is active at a
decision once it has 253 D1 bars of history (from its intraday start). N_t = the number of
active symbols with a decision in that week (weeks keyed by their Monday).
Cost per unit |Δposition_i| = cost_i bp; financing at each session close = |position_i| x the
broker swap for the side held when it is a charge (credits ignored) x nights / 365.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from gold.hyp import weekly
from gold.hyp.h10_tsmom import LOOKBACKS, MAX_LEVERAGE, MIN_HISTORY_BARS, VOL_WINDOW

PORTFOLIO_VOL = 0.10
TABLE_ROW = re.compile(
    r"\|\s*([A-Z]{6})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|"
    r"\s*[\d.]+\+[\d.]+→\*\*([\d.]+)\*\*\s*\|\s*([+-][\d.]+)\s*/\s*([+-][\d.]+)\s*")


def spec_constants(spec_text: str) -> pd.DataFrame:
    """Frozen per-symbol constants from the spec's table: intraday start, join date, D1 bars
    per year, total cost in bp, swaps (%/yr, rounded; the run uses h12_costs.json for swaps)."""
    rows = []
    for line in spec_text.splitlines():
        if not line.startswith("| ") or "Symbol" in line:
            continue
        for m in TABLE_ROW.finditer(line):
            rows.append({"symbol": m.group(1), "intraday_start": pd.Timestamp(m.group(2)),
                         "join": pd.Timestamp(m.group(3)), "d1_per_year": float(m.group(4)),
                         "cost_bp": float(m.group(5)), "swap_long_pct": float(m.group(6)),
                         "swap_short_pct": float(m.group(7))})
    return pd.DataFrame(rows).set_index("symbol")


def signal_and_vol(close: np.ndarray, i: int, d1_per_year: float) -> tuple[float, float]:
    """(s, σ63) at row i from closes 0..i only."""
    c = close[: i + 1]
    s = float(np.mean([np.sign(math.log(c[-1] / c[-1 - k])) for k in LOOKBACKS]))
    r = np.diff(np.log(c[-VOL_WINDOW - 1:]))
    return s, float(np.std(r, ddof=1) * math.sqrt(d1_per_year))


def decisions(d1s: dict[str, pd.DataFrame], first_session: pd.Timestamp) -> pd.DataFrame:
    """Every (symbol, decision session) on or after first_session with its row index and
    whether the symbol is active (>= 253 D1 bars of history at that close)."""
    rows = []
    for sym, d1 in d1s.items():
        for i in weekly.decision_index(d1):
            s = d1["session"].iloc[i]
            if s >= first_session:
                rows.append({"symbol": sym, "session": s, "row": int(i),
                             "week": s - pd.Timedelta(days=s.dayofweek),
                             "active": bool(i + 1 >= MIN_HISTORY_BARS)})
    return pd.DataFrame(rows)


def targets(d1s: dict[str, pd.DataFrame], consts: pd.DataFrame,
            first_session: pd.Timestamp) -> tuple[dict[str, pd.Series], pd.Series]:
    """Target position per symbol per decision session, and N_t per week."""
    dec = decisions(d1s, first_session)
    dec = dec[dec["active"]]
    n_week = dec.groupby("week")["symbol"].nunique()
    out = {}
    for sym, g in dec.groupby("symbol"):
        close = d1s[sym]["close"].to_numpy()
        vals = {}
        for row in g.itertuples():
            s, sigma = signal_and_vol(close, row.row, consts.at[sym, "d1_per_year"])
            n = int(n_week[row.week])
            vals[row.session] = s * min(MAX_LEVERAGE, (PORTFOLIO_VOL / math.sqrt(n)) / sigma)
        out[sym] = pd.Series(vals, dtype=float)
    return out, n_week


def swap_charge_fn(swap_long: float, swap_short: float, level: float = 1.0):
    """(position, nights) -> financing charge in log units of equity. Swaps are annual
    fractions of notional (negative = the trader pays); credits are ignored."""
    long_rate, short_rate = max(0.0, -swap_long), max(0.0, -swap_short)

    def fn(pos: float, nights: int) -> float:
        if pos == 0:
            return 0.0
        rate = long_rate if pos > 0 else short_rate
        return abs(pos) * rate * nights / 365 * level
    return fn


def unapplied_executions(d1: pd.DataFrame, h4: pd.DataFrame, tg: pd.Series) -> list:
    """Decision sessions whose execution falls in a session absent from d1 (integrity check)."""
    from gold.data.broker_daily import session_of
    sessions, bad = set(d1["session"]), []
    for session in tg.index:
        ex = weekly.execution(h4, session)
        if ex is not None and session_of(pd.Series([ex[0]])).iloc[0] not in sessions:
            bad.append(session)
    return bad


def portfolio(per_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sum of the symbols' daily rows per session date."""
    frames = [df.assign(symbol=sym) for sym, df in per_symbol.items() if len(df)]
    allrows = pd.concat(frames, ignore_index=True)
    allrows["abs_delta"] = allrows["delta"].abs()
    p = allrows.groupby("session")[["gross", "cost", "financing", "net", "abs_delta"]].sum().reset_index()
    p["net_of_cost"] = p["gross"] - p["cost"]
    return p


def metrics(daily: pd.DataFrame, col: str) -> dict:
    """Portfolio metrics, annualised with the measured sessions per year of the series."""
    r = daily[col].to_numpy()
    dates = daily["session"]
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    bpy = len(r) / years
    sd = r.std(ddof=1)
    sr = float(r.mean() / sd * math.sqrt(bpy)) if sd > 0 else float("nan")
    eq = np.exp(np.cumsum(r))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    dd = 1 - eq / peak
    under, longest, start = False, 0, None
    d = dates.to_numpy()
    for i, x in enumerate(dd):
        if x > 0 and not under:
            under, start = True, (d[i - 1] if i else d[i])
        if under:
            longest = max(longest, int((d[i] - start) / np.timedelta64(1, "D")))
            if x == 0:
                under = False
    return {"sessions": int(len(r)), "years": round(years, 2), "sessions_per_year": round(bpy, 2),
            "sharpe": sr, "sharpe_se": math.sqrt((1 + sr ** 2 / 2) / years),
            "cagr": float(math.exp(r.sum() / years) - 1), "max_drawdown": float(dd.max()),
            "longest_underwater_days": longest, "realised_vol": float(sd * math.sqrt(bpy)),
            "turnover_per_year": float(daily["abs_delta"].sum() / years), "total_log": float(r.sum())}
