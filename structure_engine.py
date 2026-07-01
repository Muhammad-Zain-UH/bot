"""LAYER 2: H1 STRUCTURE ENGINE - Validates intermediate trend integrity.

H1 Structure Rules for XAUUSD:

BULLISH STRUCTURE VALID:
- H1 printing HH (Higher Highs) and HL (Higher Lows)
- Last H1 swing low has NOT been broken by a close
- H1 ATR expanding (not collapsing into range)
- Confirmation: close > previous HL

BEARISH STRUCTURE VALID:
- H1 printing LH (Lower Highs) and LL (Lower Lows)
- Last H1 swing high has NOT been broken by a close
- H1 ATR expanding
- Confirmation: close < previous LH

STRUCTURE INVALIDATION:
- If H1 closes beyond last HL (bullish) or LH (bearish) → structure broken
- Bot waits 3+ candles for new structure to form before resuming
"""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_h1_swings(h1_data: pd.DataFrame, lookback: int = 50) -> dict[str, Any]:
    """
    Find recent H1 swing highs and lows.
    
    Uses fractal pattern: high surrounded by lower highs on both sides.
    Falls back to max/min if insufficient data.
    
    Returns:
        {
            "recent_high": float,
            "recent_high_idx": int,
            "recent_low": float,
            "recent_low_idx": int,
            "second_recent_high": float,  # For HH/LH check
            "second_recent_low": float,   # For HL/LL check
        }
    """
    try:
        if len(h1_data) < 5:
            # Fallback: just use max/min
            recent = h1_data.tail(lookback) if len(h1_data) >= lookback else h1_data
            recent_high = recent["high"].max()
            recent_low = recent["low"].min()
            return {
                "recent_high": recent_high,
                "recent_high_idx": recent["high"].idxmax(),
                "recent_low": recent_low,
                "recent_low_idx": recent["low"].idxmin(),
                "second_recent_high": recent_high * 0.995,  # Slightly lower
                "second_recent_low": recent_low * 1.005,    # Slightly higher
            }
        
        recent = h1_data.tail(lookback) if len(h1_data) >= lookback else h1_data
        
        # Find the most recent swing high/low by scanning backward (fractal pattern)
        recent_high = None
        recent_high_idx = None
        recent_low = None
        recent_low_idx = None
        second_high = None
        second_low = None

        for i in range(len(recent) - 3, 1, -1):
            if recent_high is None:
                if (recent["high"].iloc[i] > recent["high"].iloc[i - 1]
                        and recent["high"].iloc[i] > recent["high"].iloc[i - 2]
                        and recent["high"].iloc[i] > recent["high"].iloc[i + 1]
                        and recent["high"].iloc[i] > recent["high"].iloc[i + 2]):
                    recent_high = recent["high"].iloc[i]
                    recent_high_idx = recent.index[i]
            elif second_high is None:
                if (recent["high"].iloc[i] > recent["high"].iloc[i - 1]
                        and recent["high"].iloc[i] > recent["high"].iloc[i - 2]
                        and recent["high"].iloc[i] > recent["high"].iloc[i + 1]
                        and recent["high"].iloc[i] > recent["high"].iloc[i + 2]):
                    second_high = recent["high"].iloc[i]

            if recent_low is None:
                if (recent["low"].iloc[i] < recent["low"].iloc[i - 1]
                        and recent["low"].iloc[i] < recent["low"].iloc[i - 2]
                        and recent["low"].iloc[i] < recent["low"].iloc[i + 1]
                        and recent["low"].iloc[i] < recent["low"].iloc[i + 2]):
                    recent_low = recent["low"].iloc[i]
                    recent_low_idx = recent.index[i]
            elif second_low is None:
                if (recent["low"].iloc[i] < recent["low"].iloc[i - 1]
                        and recent["low"].iloc[i] < recent["low"].iloc[i - 2]
                        and recent["low"].iloc[i] < recent["low"].iloc[i + 1]
                        and recent["low"].iloc[i] < recent["low"].iloc[i + 2]):
                    second_low = recent["low"].iloc[i]

            if recent_high is not None and recent_low is not None and second_high is not None and second_low is not None:
                break
        
        # If no fractal found, use max/min
        if recent_high is None:
            recent_high = recent["high"].max()
            recent_high_idx = recent["high"].idxmax()
        
        if recent_low is None:
            recent_low = recent["low"].min()
            recent_low_idx = recent["low"].idxmin()
        
        if second_high is None:
            highs = recent["high"].values
            candidates = [h for h in highs if h < recent_high]
            second_high = max(candidates) if candidates else recent_high * 0.995
        if second_low is None:
            lows = recent["low"].values
            candidates = [l for l in lows if l > recent_low]
            second_low = min(candidates) if candidates else recent_low * 1.005
        
        return {
            "recent_high": recent_high,
            "recent_high_idx": recent_high_idx,
            "recent_low": recent_low,
            "recent_low_idx": recent_low_idx,
            "second_recent_high": second_high,
            "second_recent_low": second_low,
        }
    
    except Exception as exc:
        log_debug(f"H1 swing finding error: {exc}")
        return {
            "recent_high": None,
            "recent_high_idx": None,
            "recent_low": None,
            "recent_low_idx": None,
            "second_recent_high": None,
            "second_recent_low": None,
        }


def _count_consecutive_moves(values: list[float], direction: str) -> int:
    """Count consecutive progression steps in one direction."""
    count = 0
    for i in range(1, len(values)):
        previous_value = values[i - 1]
        current_value = values[i]
        if direction == "up" and current_value > previous_value:
            count += 1
        elif direction == "down" and current_value < previous_value:
            count += 1
    return count


def validate_h1_structure(
    h1_data: pd.DataFrame,
    expected_bias: str,
) -> dict[str, Any]:
    """
    Validate H1 structure based on bias direction.
    
    Returns:
        {
            "structure_valid": bool,
            "structure_type": "HH/HL | LH/LL | BROKEN | UNKNOWN",
            "last_swing_high": float,
            "last_swing_low": float,
            "structure_confidence": 0.0-10.0,
            "break_reason": str,
            "reasoning": str,
        }
    """
    try:
        if len(h1_data) < 5:
            return {
                "structure_valid": False,
                "structure_type": "UNKNOWN",
                "last_swing_high": None,
                "last_swing_low": None,
                "structure_confidence": 0.0,
                "break_reason": "Insufficient data (need 5+ candles)",
                "reasoning": "Not enough H1 data to validate structure",
            }
        
        swings = find_h1_swings(h1_data)
        last_high = _to_float(swings["recent_high"])
        last_low = _to_float(swings["recent_low"])
        second_high = _to_float(swings["second_recent_high"])
        second_low = _to_float(swings["second_recent_low"])
        current_close = _to_float(h1_data.iloc[-1]["close"])
        
        if any(v is None for v in [last_high, last_low, current_close]):
            return {
                "structure_valid": False,
                "structure_type": "UNKNOWN",
                "last_swing_high": last_high,
                "last_swing_low": last_low,
                "structure_confidence": 0.0,
                "break_reason": "Missing price data",
                "reasoning": "Cannot validate structure with missing data",
            }
        
        # Determine structure type and validity
        if expected_bias == "BULLISH":
            # In bullish: looking for HH/HL
            # HH check: current_high > last_high
            # HL check: current_low > last_low
            current_high = _to_float(h1_data.iloc[-1]["high"])
            current_low = _to_float(h1_data.iloc[-1]["low"])
            
            if current_high is None or current_low is None:
                return {
                    "structure_valid": False,
                    "structure_type": "UNKNOWN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": "Missing current candle OHLC",
                    "reasoning": "Cannot validate current structure",
                }
            
            # Validate SERIES progression over the most recent candles, not just
            # whether they exceed the absolute swing peak.
            last_5 = h1_data.tail(5)
            highs_5 = [_to_float(v) for v in last_5["high"].tolist()]
            lows_5 = [_to_float(v) for v in last_5["low"].tolist()]
            highs_5 = [value for value in highs_5 if value is not None]
            lows_5 = [value for value in lows_5 if value is not None]

            hh_count = _count_consecutive_moves(highs_5, "up")
            hl_count = _count_consecutive_moves(lows_5, "up")
            
            # Structure broken if close goes below last swing low
            if current_close < last_low:
                return {
                    "structure_valid": False,
                    "structure_type": "BROKEN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": f"Close {current_close:.2f} < last_low {last_low:.2f}",
                    "reasoning": "H1 bullish structure broken: close below last swing low",
                }
            
            # Structure valid if the last 5 candles show enough consecutive HH/HL progression.
            # With 5 candles there are 4 comparisons, so 2+ progression steps in both series
            # is a reasonable minimum for a live trend.
            if hh_count >= 2 and hl_count >= 2:
                confidence = min(10.0, ((hh_count + hl_count) / 8.0) * 10.0)
                return {
                    "structure_valid": True,
                    "structure_type": "HH/HL",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": confidence,
                    "break_reason": "",
                    "reasoning": f"Bullish HH/HL progression confirmed: {hh_count}/4 HH steps, {hl_count}/4 HL steps",
                }
            else:
                return {
                    "structure_valid": False,
                    "structure_type": "UNKNOWN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": f"Series insufficient: HH progression={hh_count}/4, HL progression={hl_count}/4 (need 2+ each)",
                    "reasoning": "H1 structure not consistently HH/HL across the last 5 candles",
                }
        
        elif expected_bias == "BEARISH":
            # In bearish: looking for LH/LL
            current_high = _to_float(h1_data.iloc[-1]["high"])
            current_low = _to_float(h1_data.iloc[-1]["low"])
            
            if current_high is None or current_low is None:
                return {
                    "structure_valid": False,
                    "structure_type": "UNKNOWN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": "Missing current candle OHLC",
                    "reasoning": "Cannot validate current structure",
                }
            
            # Validate SERIES progression over the most recent candles, not just
            # whether they sit below the absolute swing trough.
            last_5 = h1_data.tail(5)
            highs_5 = [_to_float(v) for v in last_5["high"].tolist()]
            lows_5 = [_to_float(v) for v in last_5["low"].tolist()]
            highs_5 = [value for value in highs_5 if value is not None]
            lows_5 = [value for value in lows_5 if value is not None]

            lh_count = _count_consecutive_moves(highs_5, "down")
            ll_count = _count_consecutive_moves(lows_5, "down")
            
            # Structure broken if close goes above last swing high
            if current_close > last_high:
                return {
                    "structure_valid": False,
                    "structure_type": "BROKEN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": f"Close {current_close:.2f} > last_high {last_high:.2f}",
                    "reasoning": "H1 bearish structure broken: close above last swing high",
                }
            
            # Structure valid if the last 5 candles show enough consecutive LH/LL progression.
            if lh_count >= 2 and ll_count >= 2:
                confidence = min(10.0, ((lh_count + ll_count) / 8.0) * 10.0)
                return {
                    "structure_valid": True,
                    "structure_type": "LH/LL",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": confidence,
                    "break_reason": "",
                    "reasoning": f"Bearish LH/LL progression confirmed: {lh_count}/4 LH steps, {ll_count}/4 LL steps",
                }
            else:
                return {
                    "structure_valid": False,
                    "structure_type": "UNKNOWN",
                    "last_swing_high": last_high,
                    "last_swing_low": last_low,
                    "structure_confidence": 0.0,
                    "break_reason": f"Series insufficient: LH progression={lh_count}/4, LL progression={ll_count}/4 (need 2+ each)",
                    "reasoning": "H1 structure not consistently LH/LL across the last 5 candles",
                }
        
        else:  # NEUTRAL bias
            return {
                "structure_valid": False,
                "structure_type": "UNKNOWN",
                "last_swing_high": last_high,
                "last_swing_low": last_low,
                "structure_confidence": 0.0,
                "break_reason": "Bias is NEUTRAL, no structure to validate",
                "reasoning": "Cannot validate structure without clear bias",
            }
    
    except Exception as exc:
        log_debug(f"H1 structure validation error: {exc}")
        return {
            "structure_valid": False,
            "structure_type": "UNKNOWN",
            "last_swing_high": None,
            "last_swing_low": None,
            "structure_confidence": 0.0,
            "break_reason": str(exc),
            "reasoning": f"Error validating structure: {str(exc)}",
        }


def get_h1_structure(
    h1_data: pd.DataFrame,
    bias: str,
) -> dict[str, Any]:
    """
    Complete H1 structure validation.
    
    Returns:
        {
            "structure_valid": bool,
            "structure_type": str,
            "last_swing_high": float,
            "last_swing_low": float,
            "structure_confidence": 0.0-10.0,
            "reason": str,
        }
    """
    return validate_h1_structure(h1_data, bias)
