"""W01 walk-forward selection, information coefficient and random control (research/v2026/W01_SPEC.md §4-5).

A trade belongs to the UTC month of its entry. At the start of month m (the decision time, after the last
bar of m - 1) a variant's score is the t-statistic of its mean net R per trade over trades entered in the
previous `lookback` months and already closed; it needs MIN_TRADES trades and a positive sd. The process
trades the top-scoring variant's trades entered in month m.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACK = 6
MIN_TRADES = 5
MIN_IC_VARIANTS = 5
N_PATHS = 2000
SEED = 20261015
FIRST_MONTH, LAST_MONTH = pd.Period("2011-01", "M"), pd.Period("2026-09", "M")


def entry_month(tr: pd.DataFrame) -> pd.PeriodIndex:
    return pd.PeriodIndex(tr["entry_time"].dt.tz_convert("UTC").dt.tz_localize(None), freq="M")


def monthly_r(tr: pd.DataFrame, vids, months: pd.PeriodIndex, col: str = "r") -> pd.DataFrame:
    """Months x variants: sum of net R over trades entered in the month (0 without trades)."""
    s = tr.groupby([entry_month(tr), tr["vid"]])[col].sum()
    return s.unstack(fill_value=0.0).reindex(index=months, columns=list(vids), fill_value=0.0)


def scores(tr: pd.DataFrame, m: pd.Period, lookback: int = LOOKBACK, col: str = "r") -> pd.Series:
    """vid -> t-statistic of mean net R per trade, eligible variants only, as known at the start of m."""
    start = pd.Timestamp(m.start_time, tz="UTC")
    lo = pd.Timestamp((m - lookback).start_time, tz="UTC")
    w = tr[(tr["entry_time"] >= lo) & (tr["entry_time"] < start) & (tr["exit_time"] < start)]
    g = w.groupby("vid")[col]
    n, mean, sd = g.count(), g.mean(), g.std(ddof=1)
    ok = (n >= MIN_TRADES) & (sd > 0)
    return (mean / (sd / np.sqrt(n)))[ok]


def ranked(sc: pd.Series) -> list[int]:
    """Variant ids by score, highest first; ties to the lower id."""
    return [int(v) for v in sorted(sc.index, key=lambda v: (-sc[v], v))]


def spearman(a, b) -> float:
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def walk(tr: pd.DataFrame, vids, months: pd.PeriodIndex, lookback: int = LOOKBACK, top: int = 1,
         col: str = "r") -> tuple[pd.DataFrame, list[np.ndarray]]:
    """Per month: chosen variants, process net R (mean over the chosen), eligible count and IC; and the
    eligible variant ids per month (for the random control)."""
    R = monthly_r(tr, vids, months, col)
    rows, elig = [], []
    for m in months:
        sc = scores(tr, m, lookback, col)
        order = ranked(sc)
        chosen = order[:top]
        nxt = R.loc[m, sc.index] if len(sc) else pd.Series(dtype=float)
        rows.append({"month": str(m), "chosen": chosen, "r": float(R.loc[m, chosen].mean()) if chosen else 0.0,
                     "n_eligible": len(sc),
                     "ic": spearman(sc.to_numpy(), nxt.to_numpy()) if len(sc) >= MIN_IC_VARIANTS else float("nan")})
        elig.append(np.array(sorted(int(v) for v in sc.index), dtype=int))
    return pd.DataFrame(rows), elig


def random_control(R: pd.DataFrame, elig: list[np.ndarray], n_paths: int = N_PATHS, seed: int = SEED) -> np.ndarray:
    """Mean monthly net R of n_paths processes that each month pick a uniformly random eligible variant."""
    rng = np.random.default_rng(seed)
    total = np.zeros(n_paths)
    for k, ids in enumerate(elig):
        if len(ids):
            total += R.iloc[k][ids].to_numpy()[rng.integers(0, len(ids), n_paths)]
    return total / len(elig)
