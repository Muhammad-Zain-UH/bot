"""H10 -- time-series momentum, long/short, volatility-targeted (research/v2/H10_SPEC.md).

Target position at each weekly decision close, from D1 closes up to and including that
close only: s = mean(sign(R21), sign(R63), sign(R252)); position = s x min(2, 0.10 / σ63).
Pure function, no I/O.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from gold.hyp.weekly import BARS_PER_YEAR, decision_index, log_returns

LOOKBACKS = (21, 63, 252)
VOL_WINDOW = 63
VOL_TARGET = 0.10
MAX_LEVERAGE = 2.0
MIN_HISTORY_BARS = 253


def target(d1: pd.DataFrame, i: int) -> float:
    """Target position at d1 row i, using rows 0..i only (NaN without enough history)."""
    if i + 1 < MIN_HISTORY_BARS:
        return float("nan")
    close = d1["close"].to_numpy()[: i + 1]
    s = np.mean([np.sign(math.log(close[-1] / close[-1 - k])) for k in LOOKBACKS])
    r = np.diff(np.log(close[-VOL_WINDOW - 1:]))
    sigma = float(np.std(r, ddof=1) * math.sqrt(BARS_PER_YEAR))
    return float(s * min(MAX_LEVERAGE, VOL_TARGET / sigma))


def targets(d1: pd.DataFrame, first_session: pd.Timestamp) -> pd.Series:
    """Target per weekly decision session on or after first_session."""
    out = {}
    for i in decision_index(d1):
        s = d1["session"].iloc[i]
        if s >= first_session:
            t = target(d1, i)
            if not math.isnan(t):
                out[s] = t
    return pd.Series(out, dtype=float)


__all__ = ["target", "targets", "log_returns"]
