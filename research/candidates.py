"""CANDIDATES -- setup definitions. Pure functions of the feature panel.

No thresholds are tuned. Every constant is fixed by the pre-declared brief and
is reproduced here verbatim. No candidate assigns a side; direction, where a
candidate has one, is applied at evaluation time.
"""
from __future__ import annotations
import numpy as np, pandas as pd

# ---- Candidate E constants. FIXED BY BRIEF. DO NOT TUNE. ----
E_RATIO_MAX = 0.7        # ATR(M5) / ATR_average_20(M5) <= 0.7
E_SUSTAIN = 12           # sustained for >= 12 consecutive M5 bars
E_RANGE_MULT = 1.5       # 12-bar high-low range <= 1.5 * ATR(M5)
E_RANGE_LOOKBACK = 12


def candidate_E(feats: pd.DataFrame) -> np.ndarray:
    """Volatility contraction. Non-directional: returns a mask, never a side.

    Fires at bar i when the compression ratio has held for the 12 bars ending
    at i (inclusive) AND the trailing 12-bar range is tight relative to ATR.
    """
    ratio = feats["atr_ratio"].to_numpy(float)
    compressed = ratio <= E_RATIO_MAX                     # NaN -> False
    sustained = (pd.Series(compressed.astype(float))
                 .rolling(E_SUSTAIN).min().to_numpy() == 1.0)
    sustained = np.where(np.isnan(sustained), False, sustained)
    tight = (feats["range_12"].to_numpy(float)
             <= E_RANGE_MULT * feats["atr_14"].to_numpy(float))
    return sustained & tight & feats["feature_eligible"].to_numpy(bool)
