"""Weekly decision / execution / daily P&L engine shared by H10 and H11
(research/v2/H10_SPEC.md §4, H11_SPEC.md §4). Pure functions, no I/O.

d1: D1 bars (gold/data/broker_daily.py) with session, close -- lookback history plus the arm.
h4: the arm's H4 bars (time, open), for execution prices.
All P&L is in log units of equity; a position of 1 is 100 % notional exposure.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from gold.econ.costs import financing_usd
from gold.hyp.anchors import NEW_YORK, local_time

BARS_PER_YEAR = 256.65
DECISION_CLOSE_HOUR_NY = 17
EXECUTION_DELAY = pd.Timedelta(minutes=60)
COST_PER_UNIT = 1e-4                      # 1 bp of price per unit of |Δposition|
ERAS = (("2004-06-01", "2008-12-31"), ("2009-01-01", "2012-12-31"),
        ("2013-01-01", "2016-12-31"), ("2017-01-01", "2020-12-31"))


def log_returns(d1: pd.DataFrame) -> pd.Series:
    return np.log(d1["close"]).diff()


def decision_index(d1: pd.DataFrame) -> np.ndarray:
    """Row positions in d1 of each week's last session (Friday, or the last trading day)."""
    week = d1["session"] - pd.to_timedelta(d1["session"].dt.dayofweek, unit="D")
    return np.flatnonzero((week != week.shift(-1)).to_numpy())


def execution(h4: pd.DataFrame, decision_session: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """Open of the first H4 bar starting >= 60 minutes after the reopen, the reopen
    being the first bar after the decision close. None if the arm's data ends first."""
    close_utc = local_time(pd.Series([decision_session]), DECISION_CLOSE_HOUR_NY, NEW_YORK).iloc[0]
    after = h4[h4["time"] >= close_utc]
    if after.empty:
        return None
    later = after[after["time"] >= after["time"].iloc[0] + EXECUTION_DELAY]
    if later.empty:
        return None
    return later["time"].iloc[0], float(later["open"].iloc[0])


def run(d1: pd.DataFrame, h4: pd.DataFrame, targets: pd.Series, dff: pd.Series,
        cost_per_unit: float = COST_PER_UNIT) -> pd.DataFrame:
    """Daily P&L from the first execution to the end of d1.

    targets: target position per decision session (index = session Timestamp).
    dff: effective fed funds rate in percent, indexed by date (forward-filled here).
    """
    from gold.data.broker_daily import session_of
    execs = {}
    for session, target in targets.items():
        ex = execution(h4, session)
        if ex is not None:
            t, price = ex
            execs[session_of(pd.Series([t])).iloc[0]] = (price, float(target))
    if not execs:
        return pd.DataFrame()
    first = min(execs)
    d = d1.reset_index(drop=True)
    start = int(np.flatnonzero((d["session"] >= first).to_numpy())[0])
    dff = dff.sort_index()
    rows, pos = [], 0.0
    for k in range(start, len(d)):
        s, c, c_prev = d.at[k, "session"], d.at[k, "close"], d.at[k - 1, "close"]
        delta = 0.0
        if s in execs:
            price, new = execs[s]
            gross = pos * math.log(price / c_prev) + new * math.log(c / price)
            delta = abs(new - pos)
            pos = new
        else:
            gross = pos * math.log(c / c_prev)
        nxt = d.at[k + 1, "session"] if k + 1 < len(d) else s + pd.offsets.BDay(1)
        nights = (nxt - s).days
        rate = float(dff.loc[:s].iloc[-1]) / 100 if len(dff.loc[:s]) else float("nan")
        side = "long" if pos > 0 else "short"
        fin = float(financing_usd(abs(pos), nights, side, rate)) if pos != 0 else 0.0
        cost = cost_per_unit * delta
        rows.append({"session": s, "position": pos, "delta": delta, "gross": gross, "cost": cost,
                     "financing": fin, "net": gross - cost - fin,
                     "gold_r": math.log(c / c_prev)})
    return pd.DataFrame(rows)


def metrics(daily: pd.DataFrame, col: str = "net") -> dict:
    r = daily[col].to_numpy()
    years = len(r) / BARS_PER_YEAR
    sr = float(r.mean() / r.std(ddof=1) * math.sqrt(BARS_PER_YEAR))
    eq = np.exp(np.cumsum(r))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    dd = 1 - eq / peak
    dates = daily["session"].to_numpy()
    under, longest, start = False, 0, None
    for i, x in enumerate(dd):
        if x > 0 and not under:
            under, start = True, (dates[i - 1] if i else dates[i])
        if under:
            longest = max(longest, int((dates[i] - start) / np.timedelta64(1, "D")))
            if x == 0:
                under = False
    return {"sessions": int(len(r)), "years": round(years, 2), "sharpe": sr,
            "sharpe_se": math.sqrt((1 + sr ** 2 / 2) / years),
            "cagr": float(math.exp(r.sum() / years) - 1), "max_drawdown": float(dd.max()),
            "longest_underwater_days": longest,
            "turnover_per_year": float(daily["delta"].sum() / years),
            "corr_buy_and_hold": float(np.corrcoef(r, daily["gold_r"])[0, 1]),
            "total_net_log": float(r.sum())}


def era_pnl(daily: pd.DataFrame, col: str = "net") -> dict:
    out = {}
    for lo, hi in ERAS:
        sel = (daily["session"] >= pd.Timestamp(lo)) & (daily["session"] <= pd.Timestamp(hi))
        out[f"{lo[:7]} -> {hi[:4]}"] = float(daily.loc[sel, col].sum())
    return out


def era_rule(eras: dict) -> dict:
    """Total > 0 and no era above 60 % of the total."""
    total = sum(eras.values())
    shares = {k: (v / total if total else float("nan")) for k, v in eras.items()}
    return {"total": total, "shares": shares,
            "pass": bool(total > 0 and max(shares.values()) <= 0.6)}
