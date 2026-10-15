"""H-PSX-01 construction: 12-1 month momentum winners vs the equal-weight liquid PSX universe.

Spec: research/psx/H_PSX01_SPEC.md (section "Construction"). Pure functions over a Panel of daily arrays
(rows = PSX trading days in the closing files, columns = companies, symbol changes chained). The signal and
universe at month-end t read only rows up to t. Nothing here computes a mean, cumulative or annualised
return; the results script is separate.

Prices in PKR per share (`*_pkr`); portfolio returns are simple returns (`ret_*`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from psx.data.audit import (DERIVED, LIMIT_FLOOR_RS, RAW, adjusted, equity_mask, observed_limits, possible_renames,
                            ref_moves, sector_names)

FIRST_HOLD, LAST_HOLD = pd.Period("2015-01", "M"), pd.Period("2026-09", "M")
TOP_N = 100                         # universe: most traded names
HIST_DAYS = 252                     # trading days of history required
ACTIVE_SHARE = 0.80                 # share of the last HIST_DAYS with volume > 0
LIQ_DAYS = 126                      # window of the median daily traded value
MIN_PRICE_PKR = 10.0
SPREAD_DAYS = 63                    # Abdi-Ranaldo window
SPREAD_FLOOR = 0.0010               # full relative spread floor
COMMISSION = 0.0015                 # of traded value ...
COMMISSION_MIN_PKR_PER_SHARE = 0.03  # ... or this per share, whichever is higher
SALES_TAX = 0.15                    # on the commission
LEVIES = 0.0002                     # exchange, CDC, NCCPL, SECP, of traded value
DELIST_HAIRCUT = 0.30               # sensitivity: delisted holding valued at (1 - this) x last official close
LOCK_SLACK = 0.005                  # a close within 0.5 % of the band (plus one tick) counts as at the band
TICK_PKR = 0.01
EXCLUDED_SECTORS = ("MODARABAS", "REAL ESTATE INVESTMENT TRUST")


# ---------------------------------------------------------------- panel
@dataclass
class Panel:
    days: pd.DatetimeIndex
    names: list[str]
    close: np.ndarray                 # official close where the company has a row that day, else NaN
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    ldcp: np.ndarray
    adj: np.ndarray                   # adjusted total-return close, carried forward after the first row
    limit: np.ndarray                 # the day's observed price limit (fraction of LDCP)
    close_ff: np.ndarray = field(init=False)
    has_row: np.ndarray = field(init=False)
    first_pos: np.ndarray = field(init=False)
    last_pos: np.ndarray = field(init=False)

    def __post_init__(self):
        self.has_row = ~np.isnan(self.close)
        self.close_ff = pd.DataFrame(self.close).ffill().to_numpy()
        any_row = self.has_row.any(axis=0)
        self.first_pos = np.where(any_row, self.has_row.argmax(axis=0), -1)
        self.last_pos = np.where(any_row, len(self.days) - 1 - self.has_row[::-1].argmax(axis=0), -1)

    @classmethod
    def from_rows(cls, rows: pd.DataFrame, days: pd.DatetimeIndex, limits) -> "Panel":
        """rows: symbol (company), date, close, high, low, volume, ldcp, adj_close; one row per company-day."""
        wide = {c: rows.pivot(index="date", columns="symbol", values=c).reindex(days) for c in
                ("close", "high", "low", "volume", "ldcp", "adj_close")}
        names = sorted(wide["close"].columns)
        arr = {c: w[names].to_numpy(dtype=float) for c, w in wide.items()}
        lim = np.full(len(days), float(limits)) if np.isscalar(limits) else pd.Series(limits).reindex(days).to_numpy(float)
        return cls(days, names, arr["close"], arr["high"], arr["low"], arr["volume"], arr["ldcp"],
                   pd.DataFrame(arr["adj_close"]).ffill().to_numpy(), lim)

    def truncate(self, p: int) -> "Panel":
        """The panel as it was known at the close of day p."""
        s = slice(0, p + 1)
        return Panel(self.days[s], self.names, self.close[s], self.high[s], self.low[s], self.volume[s],
                     self.ldcp[s], self.adj[s], self.limit[s])


def rename_chain(renames: list[tuple[str, str, str]]) -> dict[str, str]:
    """old symbol -> final symbol of the company; pairs where a symbol has two candidates are dropped."""
    olds = pd.Series([o for o, _, _ in renames]).value_counts()
    news = pd.Series([n for _, n, _ in renames]).value_counts()
    step = {o: n for o, n, _ in renames if olds[o] == 1 and news[n] == 1}
    out = {}
    for o in step:
        s, seen = o, {o}
        while s in step and step[s] not in seen:
            s = step[s]
            seen.add(s)
        out[o] = s
    return out


def load_panel(snapshot: str = "2026-10-14") -> tuple[Panel, dict]:
    """Ordinary shares per the audit filter without modarabas and REITs, symbol changes chained."""
    closing = pd.read_parquet(DERIVED / "closing.parquet")
    listed = pd.DataFrame(json.loads((RAW / "symbols" / f"{snapshot}.json").read_bytes()))
    days = pd.DatetimeIndex(sorted(closing["date"].unique()))
    eq = closing[equity_mask(closing, listed)]
    limits = observed_limits(ref_moves(eq), days)
    sector = eq["sector_code"].map(sector_names(closing, listed)).fillna("").str.upper()
    eq = eq[~sector.isin(EXCLUDED_SECTORS)]
    chain = rename_chain(possible_renames(adjusted(eq, limits), days))
    eq = eq.assign(symbol=eq["symbol"].map(lambda s: chain.get(s, s)))
    adj = adjusted(eq, limits)
    info = {"companies": int(adj["symbol"].nunique()), "symbol_changes_chained": len(chain),
            "excluded_sectors": list(EXCLUDED_SECTORS)}
    return Panel.from_rows(adj, days, limits), info


# ---------------------------------------------------------------- calendar
def month_end_positions(days: pd.DatetimeIndex) -> dict[pd.Period, int]:
    """Month -> position of its last trading day in the closing files."""
    s = pd.Series(np.arange(len(days)), index=days)
    return {m: int(g.iloc[-1]) for m, g in s.groupby(days.to_period("M"))}


@dataclass
class MonthPlan:
    month: pd.Period                  # holding month
    t_pos: int                        # signal month-end t (last trading day of the previous month)
    exec_pos: int                     # first trading day after t: trades at its close
    next_pos: int                     # next execution day: the holding return runs to its close
    targets: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))


def schedule(days: pd.DatetimeIndex, first: pd.Period = FIRST_HOLD, last: pd.Period = LAST_HOLD) -> list[MonthPlan]:
    me = month_end_positions(days)
    out = []
    for m in pd.period_range(first, last, freq="M"):
        t, nxt = me[m - 1], me[m] + 1
        if nxt >= len(days):
            raise ValueError(f"no execution day after {m}")
        out.append(MonthPlan(m, t, t + 1, nxt))
    return out


# ---------------------------------------------------------------- signal and universe (rows <= t only)
def momentum(P: Panel, t_pos: int) -> np.ndarray:
    """Total return on the adjusted series from month-end t-12 to month-end t-1."""
    me = month_end_positions(P.days[: t_pos + 1])
    m = P.days[t_pos].to_period("M")
    a, b = me.get(m - 1), me.get(m - 12)
    if a is None or b is None:
        return np.full(len(P.names), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        return P.adj[a] / P.adj[b] - 1


def universe(P: Panel, t_pos: int, top_n: int = TOP_N) -> tuple[np.ndarray, np.ndarray]:
    """Companies eligible at month-end t, the top_n by median daily traded value; and the signal."""
    p = t_pos
    sig = momentum(P, p)
    if p + 1 < HIST_DAYS:
        return np.array([], dtype=int), sig
    hist_ok = (P.first_pos >= 0) & (P.first_pos <= p - HIST_DAYS + 1)
    vol = np.nan_to_num(P.volume[p - HIST_DAYS + 1: p + 1])
    active = (vol > 0).sum(axis=0) >= ACTIVE_SHARE * HIST_DAYS
    with np.errstate(invalid="ignore"):
        price_ok = P.close_ff[p] >= MIN_PRICE_PKR
    lw = slice(p - LIQ_DAYS + 1, p + 1)
    value_pkr = np.median(np.nan_to_num(P.close[lw] * P.volume[lw]), axis=0)
    idx = np.flatnonzero(hist_ok & active & price_ok & np.isfinite(sig))
    order = idx[np.lexsort((idx, -value_pkr[idx]))]
    return order[:top_n], sig


def winners(univ: np.ndarray, sig: np.ndarray) -> np.ndarray:
    """Top third of the universe by signal (floor(N/3) names); ties by name."""
    k = len(univ) // 3
    return univ[np.lexsort((univ, -sig[univ]))][:k]


# ---------------------------------------------------------------- execution frictions
def locked(P: Panel, p: int, i: int, side: str) -> bool:
    """Locked at the band all day: traded, high = low = close, and the close at LDCP +- the day's limit."""
    c, ref = P.close[p, i], P.ldcp[p, i]
    if not (P.volume[p, i] > 0 and ref > 0 and P.high[p, i] == c and P.low[p, i] == c):
        return False
    band = max(P.limit[p] * ref, LIMIT_FLOOR_RS)
    slack = LOCK_SLACK * band + TICK_PKR
    return c >= ref + band - slack if side == "up" else c <= ref - band + slack


def spread(P: Panel, p: int, i: int) -> float:
    """Abdi & Ranaldo (2017) close-high-low spread over the last SPREAD_DAYS trading days to p: two-day
    estimates from consecutive traded rows (prices adjusted, so ex-dates do not jump), negatives set to 0,
    square roots averaged; floored at SPREAD_FLOOR."""
    lo = max(0, p - SPREAD_DAYS + 1)
    sl = slice(lo, p + 1)
    ok = (P.volume[sl, i] > 0) & (P.high[sl, i] > 0) & (P.low[sl, i] > 0) & (P.close[sl, i] > 0)
    rows = np.flatnonzero(ok) + lo
    if len(rows) < 2:
        return SPREAD_FLOOR
    f = P.adj[rows, i] / P.close[rows, i]
    eta = (np.log(P.high[rows, i] * f) + np.log(P.low[rows, i] * f)) / 2
    c = np.log(P.close[rows, i] * f)
    s2 = 4 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    return max(float(np.sqrt(np.maximum(s2, 0)).sum() / len(s2)), SPREAD_FLOOR)


def cost_rate(price_pkr: float, spread_full: float, mult: float = 1.0) -> float:
    """Cost per side as a fraction of traded value: commission (higher of 0.15 % and Rs 0.03 per share) plus
    15 % sales tax on it, 0.02 % levies, half the spread; mult = 2 doubles every component."""
    commission = max(COMMISSION, COMMISSION_MIN_PKR_PER_SHARE / price_pkr)
    return mult * (commission * (1 + SALES_TAX) + LEVIES + spread_full / 2)


# ---------------------------------------------------------------- monthly simulation
def simulate(P: Panel, plans: list[MonthPlan], cost_mult: float = 1.0, haircut: float = 0.0) -> pd.DataFrame:
    """Equal weights over plan.targets reset at each execution close. A buy locked at the upper limit (or with
    no close that day) is not filled and its slot stays in cash; a sell locked at the lower limit (or with no
    close) executes at the next close that is not locked down. A holding with no further closes is valued at
    its last official close x (1 - haircut) and turns into cash. Cash earns nothing; buys are scaled down if
    cash (after costs and blocked sells) cannot fund them. One row per month: ret_net (simple), cost and
    one-way turnover as fractions of the value at execution, and event counts."""
    pos: dict[int, float] = {}
    cash = 1.0
    pending: dict[int, float] = {}
    rates: dict[tuple[int, int], float] = {}
    last_day = len(P.days) - 1

    def rate(i: int, p: int) -> float:
        if (i, p) not in rates:
            rates[(i, p)] = cost_rate(P.close[p, i], spread(P, p, i), cost_mult)
        return rates[(i, p)]

    out = []
    for plan in plans:
        e = plan.exec_pos
        value = sum(pos.values()) + cash
        rec = {"month": str(plan.month), "n_targets": len(plan.targets), "unfilled_locked_buys": 0,
               "unfilled_locked_new": 0, "unfilled_no_close": 0, "locked_sells": 0, "sells_no_close": 0, "delistings": 0,
               "zero_volume_fills": 0}
        traded = costs = 0.0
        slot = value / len(plan.targets) if len(plan.targets) else 0.0
        targets = set(int(i) for i in plan.targets)
        pending.clear()                                    # orders are set afresh each month
        for i in sorted(pos):                              # sells
            want = slot if i in targets else 0.0
            cur = pos[i]
            if cur - want <= 1e-12 * value:
                continue
            if P.has_row[e, i] and not locked(P, e, i, "down"):
                amt = cur - want
                c = amt * rate(i, e)
                cash += amt - c
                costs, traded = costs + c, traded + amt
                rec["zero_volume_fills"] += int(not P.volume[e, i] > 0)
                pos[i] = want
                if want == 0.0:
                    del pos[i]
            else:
                pending[i] = (cur - want) / cur
                rec["locked_sells" if P.has_row[e, i] else "sells_no_close"] += 1
        buys = {}
        for i in sorted(targets):                          # buys
            need = slot - pos.get(i, 0.0)
            if need <= 1e-9 * slot:
                continue
            if not P.has_row[e, i]:
                rec["unfilled_no_close"] += 1
            elif locked(P, e, i, "up"):
                rec["unfilled_locked_buys"] += 1
                rec["unfilled_locked_new"] += int(i not in pos)
            else:
                buys[i] = need
        spend = sum(n * (1 + rate(i, e)) for i, n in buys.items())
        scale = min(1.0, max(cash, 0.0) / spend) if spend > 0 else 1.0
        for i, n in buys.items():
            amt = n * scale
            c = amt * rate(i, e)
            cash -= amt + c
            costs, traded = costs + c, traded + amt
            rec["zero_volume_fills"] += int(not P.volume[e, i] > 0)
            pos[i] = pos.get(i, 0.0) + amt
        for d in range(e + 1, plan.next_pos + 1):          # hold to the next execution close
            for i in list(pos):
                if P.last_pos[i] < d and P.last_pos[i] < last_day:
                    cash += pos.pop(i) * (1 - haircut)
                    pending.pop(i, None)
                    rec["delistings"] += 1
                else:
                    pos[i] *= P.adj[d, i] / P.adj[d - 1, i]
            for i in list(pending):
                if i in pos and P.has_row[d, i] and not locked(P, d, i, "down"):
                    amt = pos[i] * pending.pop(i)
                    c = amt * rate(i, d)
                    cash += amt - c
                    costs, traded = costs + c, traded + amt
                    pos[i] -= amt
                    if pos[i] <= 1e-15:
                        del pos[i]
        rec.update(ret_net=(sum(pos.values()) + cash) / value - 1, cost=costs / value, turnover=traded / 2 / value)
        out.append(rec)
    return pd.DataFrame(out)
