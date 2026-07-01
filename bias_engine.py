"""LAYER 1: H4 BIAS ENGINE - Determines the ONLY direction the bot is allowed to trade.

XAUUSD-Specific Rules:
- Bullish bias: H4 EMA20 > EMA50 by a meaningful ATR-scaled separation + last 2 closes above EMA20 + price > daily midpoint
- Bearish bias: H4 EMA20 < EMA50 by a meaningful ATR-scaled separation + last 2 closes below EMA20 + price < daily midpoint
- Neutral: EMA20 ≈ EMA50 (below the dynamic separation threshold) or price choppy around daily midpoint

Bias Invalidation:
- If Daily candle closes beyond last H4 swing high (bearish bias) → flip to BULLISH
- If Daily candle closes beyond last H4 swing low (bullish bias) → flip to BEARISH
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


def _find_h4_swings(h4_data: pd.DataFrame | None, lookback: int = 50) -> dict[str, float | None]:
    """Find most recent H4 fractal swing high/low over lookback candles."""
    if h4_data is None or len(h4_data) < 5:
        return {"swing_high": None, "swing_low": None}

    recent = h4_data.tail(lookback).reset_index(drop=True)
    swing_high = None
    swing_low = None

    # Scan backward so the first match is the most recent fractal
    for i in range(len(recent) - 3, 1, -1):
        if swing_high is None:
            h = _to_float(recent["high"].iloc[i])
            h1 = _to_float(recent["high"].iloc[i - 1])
            h2 = _to_float(recent["high"].iloc[i - 2])
            h3 = _to_float(recent["high"].iloc[i + 1])
            h4 = _to_float(recent["high"].iloc[i + 2])
            if h is not None and all(v is not None for v in (h1, h2, h3, h4)):
                if h > h1 and h > h2 and h > h3 and h > h4:
                    swing_high = h

        if swing_low is None:
            l = _to_float(recent["low"].iloc[i])
            l1 = _to_float(recent["low"].iloc[i - 1])
            l2 = _to_float(recent["low"].iloc[i - 2])
            l3 = _to_float(recent["low"].iloc[i + 1])
            l4 = _to_float(recent["low"].iloc[i + 2])
            if l is not None and all(v is not None for v in (l1, l2, l3, l4)):
                if l < l1 and l < l2 and l < l3 and l < l4:
                    swing_low = l

        if swing_high is not None and swing_low is not None:
            break

    if swing_high is None:
        swing_high = _to_float(recent["high"].max())
    if swing_low is None:
        swing_low = _to_float(recent["low"].min())

    return {"swing_high": swing_high, "swing_low": swing_low}


def _calculate_ema_threshold(atr_14: float | None, floor: float = 3.0, atr_ratio: float = 0.20) -> float:
    """Return the minimum EMA separation needed for a directional bias.
    
    FIX (PHASE 5): Lowered floor from 5.0 to 3.0 pips.
    During low-volatility periods (Asian session), even small EMA separations indicate bias.
    """
    if atr_14 is None or atr_14 <= 0:
        return floor
    return max(floor, atr_14 * atr_ratio)


def calculate_h4_ema_bias(
    h4_indicators: dict[str, Any],
    daily_data: pd.DataFrame | None = None,
    h4_data: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Determine H4 bias from EMA20/EMA50 positioning.
    
    FIX #4: Now includes:
    - Daily midpoint confirmation (BULLISH: price > daily midpoint, BEARISH: price < daily midpoint)
    - 2-candle close validation (BULLISH: last 2 closes > EMA20, BEARISH: last 2 closes < EMA20)
    
    Returns:
        {
            "bias": "BULLISH | BEARISH | NEUTRAL",
            "bias_strength": 0.0-10.0,
            "ema_distance": float,  # price distance (positive = bullish, negative = bearish)
            "swing_high": float,
            "swing_low": float,
            "h4_close": float,
            "ema20": float,
            "ema50": float,
            "reasoning": str,
        }
    """
    try:
        ema20 = _to_float(h4_indicators.get("ema_20") or h4_indicators.get("ema20"))
        ema50 = _to_float(h4_indicators.get("ema_50") or h4_indicators.get("ema50"))
        h4_close = _to_float(h4_indicators.get("close"))
        h4_high = _to_float(h4_indicators.get("high"))
        h4_low = _to_float(h4_indicators.get("low"))
        atr_14 = _to_float(h4_indicators.get("atr_14") or h4_indicators.get("atr14"))
        ema_threshold = _calculate_ema_threshold(atr_14)
        
        if any(v is None for v in [ema20, ema50, h4_close]):
            return {
                "bias": "NEUTRAL",
                "bias_strength": 0.0,
                "ema_distance": 0.0,
                "ema_threshold": ema_threshold,
                "swing_high": h4_high,
                "swing_low": h4_low,
                "h4_close": h4_close,
                "ema20": ema20,
                "ema50": ema50,
                "reasoning": "Missing EMA or close data",
            }
        
        # Calculate EMA distance in price units
        ema_distance = ema20 - ema50
        ema_distance_abs = abs(ema_distance)
        
        # Determine bias based on EMA separation using an ATR-scaled threshold.
        if ema_distance_abs < ema_threshold:
            bias = "NEUTRAL"
            strength = 0.0
            reason = f"EMAs too close: distance = {ema_distance_abs:.2f} (need ≥{ema_threshold:.2f})"
        elif ema_distance > ema_threshold:
            bias = "BULLISH"
            strength = min(10.0, ema_distance_abs / ema_threshold)  # Scale to 10
            reason = (
                f"EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f}), "
                f"distance = {ema_distance:.2f} (threshold ≥{ema_threshold:.2f})"
            )
        else:  # ema_distance < -ema_threshold
            bias = "BEARISH"
            strength = min(10.0, ema_distance_abs / ema_threshold)  # Scale to 10
            reason = (
                f"EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f}), "
                f"distance = {abs(ema_distance):.2f} (threshold ≥{ema_threshold:.2f})"
            )
        
        # FIX #4: Add daily midpoint confirmation
        daily_midpoint = None
        if daily_data is not None and len(daily_data) >= 1:
            daily_high = _to_float(daily_data.iloc[-1].get("high"))
            daily_low = _to_float(daily_data.iloc[-1].get("low"))
            if daily_high is not None and daily_low is not None:
                daily_midpoint = (daily_high + daily_low) / 2.0
        
        # Check if H4 close confirms bias direction (relative to daily midpoint)
        midpoint_confirmed = True
        midpoint_reason = ""
        if daily_midpoint is not None:
            if bias == "BULLISH" and h4_close < daily_midpoint:
                midpoint_confirmed = False
                midpoint_reason = f" [WARNING] Bullish bias but H4 close {h4_close:.2f} < daily midpoint {daily_midpoint:.2f}"
                # Reduce strength slightly for midpoint conflict
                strength = max(0.0, strength - 2.0)
            elif bias == "BEARISH" and h4_close > daily_midpoint:
                midpoint_confirmed = False
                midpoint_reason = f" [WARNING] Bearish bias but H4 close {h4_close:.2f} > daily midpoint {daily_midpoint:.2f}"
                # Reduce strength slightly for midpoint conflict
                strength = max(0.0, strength - 2.0)
        
        # FIX #4: Validate 2-candle close series (H4 last 2 closes should align with bias)
        two_candle_confirmed = True
        two_candle_reason = ""
        if isinstance(h4_indicators, dict) and "closes_2" in h4_indicators:
            # If closes_2 list is available
            closes_2 = h4_indicators.get("closes_2", [])
            if len(closes_2) >= 2:
                close_1 = _to_float(closes_2[-2])
                close_2 = _to_float(closes_2[-1])
                if bias == "BULLISH":
                    if not (close_1 > ema20 and close_2 > ema20):
                        two_candle_confirmed = False
                        two_candle_reason = f" [WARNING] Bullish bias but closes [{close_1:.2f}, {close_2:.2f}] not above EMA20 {ema20:.2f}"
                        strength = max(0.0, strength - 1.5)
                elif bias == "BEARISH":
                    if not (close_1 < ema20 and close_2 < ema20):
                        two_candle_confirmed = False
                        two_candle_reason = f" [WARNING] Bearish bias but closes [{close_1:.2f}, {close_2:.2f}] not below EMA20 {ema20:.2f}"
                        strength = max(0.0, strength - 1.5)
        
        # Find recent swing high/low (last 50 H4 candles; fallback to last candle)
        swings = _find_h4_swings(h4_data, lookback=50)
        swing_high = swings["swing_high"] if swings["swing_high"] is not None else (h4_high if h4_high else ema20 + 20)
        swing_low = swings["swing_low"] if swings["swing_low"] is not None else (h4_low if h4_low else ema50 - 20)
        
        full_reason = reason + midpoint_reason + two_candle_reason
        
        return {
            "bias": bias,
            "bias_strength": strength,
            "ema_distance": ema_distance,
            "ema_threshold": ema_threshold,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "h4_close": h4_close,
            "ema20": ema20,
            "ema50": ema50,
            "reasoning": full_reason,
        }
    
    except Exception as exc:
        log_debug(f"H4 bias calculation error: {exc}")
        return {
            "bias": "NEUTRAL",
            "bias_strength": 0.0,
            "ema_distance": 0.0,
            "ema_threshold": None,
            "swing_high": None,
            "swing_low": None,
            "h4_close": None,
            "ema20": None,
            "ema50": None,
            "reasoning": f"Error: {str(exc)}",
        }


def validate_bias_with_daily_close(
    current_bias: str,
    daily_data: pd.DataFrame | None,
    h4_swing_high: float | None,
    h4_swing_low: float | None,
) -> dict[str, Any]:
    """
    Check if Daily close invalidates the current bias.
    
    Invalidation rules:
    - In BULLISH bias: if Daily closes below last H4 swing low → flip to BEARISH
    - In BEARISH bias: if Daily closes above last H4 swing high → flip to BULLISH
    
    Returns:
        {
            "bias": str,  # Original or flipped
            "invalidated": bool,
            "flip_reason": str,
            "daily_close": float,
        }
    """
    try:
        if daily_data is None or len(daily_data) == 0:
            return {
                "bias": current_bias,
                "invalidated": False,
                "flip_reason": "No daily data to validate",
                "daily_close": None,
            }
        
        daily_close = _to_float(daily_data.iloc[-1].get("close"))
        
        if daily_close is None:
            return {
                "bias": current_bias,
                "invalidated": False,
                "flip_reason": "Daily close is None",
                "daily_close": daily_close,
            }
        
        invalidated = False
        flip_reason = ""
        flipped_bias = current_bias
        
        if current_bias == "BULLISH" and h4_swing_low is not None:
            if daily_close < h4_swing_low:
                invalidated = True
                flipped_bias = "BEARISH"
                flip_reason = f"Daily closed below H4 swing low ({h4_swing_low:.2f}); flipped to BEARISH"
        
        elif current_bias == "BEARISH" and h4_swing_high is not None:
            if daily_close > h4_swing_high:
                invalidated = True
                flipped_bias = "BULLISH"
                flip_reason = f"Daily closed above H4 swing high ({h4_swing_high:.2f}); flipped to BULLISH"
        
        return {
            "bias": flipped_bias,
            "invalidated": invalidated,
            "flip_reason": flip_reason,
            "daily_close": daily_close,
        }
    
    except Exception as exc:
        log_debug(f"Daily bias validation error: {exc}")
        return {
            "bias": current_bias,
            "invalidated": False,
            "flip_reason": f"Validation error: {str(exc)}",
            "daily_close": None,
        }


def get_h4_bias(
    h4_indicators: dict[str, Any],
    daily_data: pd.DataFrame | None = None,
    h4_data: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Complete H4 bias determination: EMA-based bias + daily invalidation check.
    
    Returns:
        {
            "bias": "BULLISH | BEARISH | NEUTRAL",
            "bias_strength": 0.0-10.0,
            "swing_high": float,
            "swing_low": float,
            "ema_distance": float,
            "invalidated": bool,
            "flip_reason": str,
            "full_report": str,  # Readable summary
        }
    """
    # Step 1: Calculate EMA-based bias
    ema_result = calculate_h4_ema_bias(h4_indicators, daily_data, h4_data=h4_data)
    
    # Step 2: Validate with daily close
    validation = validate_bias_with_daily_close(
        current_bias=ema_result["bias"],
        daily_data=daily_data,
        h4_swing_high=ema_result["swing_high"],
        h4_swing_low=ema_result["swing_low"],
    )
    
    # Step 3: Compile final report
    final_bias = validation["bias"]
    was_invalidated = validation["invalidated"]
    
    ema20_val = ema_result['ema20'] if ema_result['ema20'] is not None else 0
    ema50_val = ema_result['ema50'] if ema_result['ema50'] is not None else 0
    distance = ema_result['ema_distance'] if ema_result['ema_distance'] is not None else 0
    ema_threshold = ema_result.get("ema_threshold", 5.0) or 5.0

    report_lines = [
        f"[BIAS] H4 EMA-based bias: {ema_result['bias']} (strength: {ema_result['bias_strength']:.1f}/10)",
        f"[BIAS] EMA20: {ema20_val:.2f} | EMA50: {ema50_val:.2f} | Distance: {abs(distance):.2f} (threshold: {ema_threshold:.2f})",
        f"[BIAS] Status: {ema_result.get('reasoning', 'N/A')}",
    ]
    
    if was_invalidated:
        report_lines.append(f"[BIAS] ⚠️ INVALIDATED: {validation['flip_reason']}")
    
    full_report = " | ".join(report_lines)
    
    return {
        "bias": final_bias,
        "bias_strength": ema_result["bias_strength"],
        "swing_high": ema_result["swing_high"],
        "swing_low": ema_result["swing_low"],
        "ema_distance": ema_result["ema_distance"],
        "ema_threshold": ema_threshold,
        "ema20": ema20_val,  # ADD THIS
        "ema50": ema50_val,  # ADD THIS
        "invalidated": was_invalidated,
        "flip_reason": validation["flip_reason"],
        "full_report": full_report,
    }
