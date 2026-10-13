"""H11 -- volatility-managed long exposure (research/v2/H11_SPEC.md).

Target exposure at each weekly decision close, from D1 closes up to and including that
close only: min(1.5, σ* / σ21), σ* = 0.1433 (median σ21 over TRAIN_D1, frozen in the spec).
Each arm starts at the same weekly close as H10 (253 bars of history in TRAIN_D1).
Pure function, no I/O.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from gold.hyp.h10_tsmom import MIN_HISTORY_BARS
from gold.hyp.weekly import BARS_PER_YEAR, decision_index

SIGMA_STAR = 0.1433
VOL_WINDOW = 21
MAX_EXPOSURE = 1.5


def target(d1: pd.DataFrame, i: int) -> float:
    if i + 1 < MIN_HISTORY_BARS:
        return float("nan")
    close = d1["close"].to_numpy()[: i + 1]
    r = np.diff(np.log(close[-VOL_WINDOW - 1:]))
    sigma = float(np.std(r, ddof=1) * math.sqrt(BARS_PER_YEAR))
    return float(min(MAX_EXPOSURE, SIGMA_STAR / sigma))


def targets(d1: pd.DataFrame, first_session: pd.Timestamp) -> pd.Series:
    out = {}
    for i in decision_index(d1):
        s = d1["session"].iloc[i]
        if s >= first_session:
            t = target(d1, i)
            if not math.isnan(t):
                out[s] = t
    return pd.Series(out, dtype=float)


def benchmark(h11_targets: pd.Series) -> pd.Series:
    """Buy-and-hold: exposure 1 at the same decisions (so the same first execution)."""
    return pd.Series(1.0, index=h11_targets.index)
