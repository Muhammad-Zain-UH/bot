"""Fibonacci retracement level calculator for XAUUSD entry validation."""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug

# Fibonacci levels for retracement detection
FIB_LEVELS = {
    "0.236": 0.236,
    "0.382": 0.382,
    "0.500": 0.500,
    "0.618": 0.618,  # Golden ratio - most important
    "0.786": 0.786,
}


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_swing_high_low(data: pd.DataFrame, lookback: int = 50) -> tuple[float | None, float | None, int, int]:
    """Find the most recent swing high and low in the last 'lookback' candles.
    
    Returns:
        (swing_high_price, swing_low_price, high_index, low_index)
    """
    if len(data) < lookback:
        lookback = len(data)
    
    recent = data.iloc[-lookback:]
    
    swing_high = recent['high'].max()
    swing_low = recent['low'].min()
    high_idx = recent['high'].idxmax()
    low_idx = recent['low'].idxmin()
    
    return swing_high, swing_low, high_idx, low_idx


def calculate_fibonacci_levels(swing_high: float, swing_low: float, direction: str) -> dict[str, float]:
    """Calculate Fibonacci retracement levels.
    
    Args:
        swing_high: Recent swing high price
        swing_low: Recent swing low price
        direction: "BUY" (retracing from high) or "SELL" (retracing from low)
    
    Returns:
        Dict mapping level names to prices
    """
    if swing_high <= swing_low:
        return {}
    
    range_size = swing_high - swing_low
    levels = {}
    
    if direction == "BUY":
        # Price retracing DOWN from swing high
        for level_name, ratio in FIB_LEVELS.items():
            levels[level_name] = swing_high - (range_size * ratio)
    else:
        # Price retracing UP from swing low
        for level_name, ratio in FIB_LEVELS.items():
            levels[level_name] = swing_low + (range_size * ratio)
    
    return levels


def check_fibonacci_confirmation(current_price: float, fib_levels: dict[str, float], 
                                 direction: str, tolerance_pips: float = 5.0) -> dict[str, Any]:
    """Check if current price is near a Fibonacci level.
    
    Args:
        current_price: Current market price
        fib_levels: Dictionary of Fibonacci levels
        direction: "BUY" or "SELL"
        tolerance_pips: Tolerance in pips (XAUUSD = 0.01 per pip)
    
    Returns:
        {
            "is_at_fib_level": bool,
            "nearest_level": str,
            "nearest_level_price": float,
            "distance_from_level": float,
            "fib_618_distance": float,
        }
    """
    if not fib_levels:
        return {
            "is_at_fib_level": False,
            "nearest_level": None,
            "nearest_level_price": None,
            "distance_from_level": None,
            "fib_618_distance": None,
        }
    
    # Find nearest level
    nearest_level = None
    nearest_distance = float('inf')
    
    for level_name, level_price in fib_levels.items():
        distance = abs(current_price - level_price)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_level = level_name
    
    # Check if at or near a Fibonacci level
    is_at_level = nearest_distance <= tolerance_pips
    
    # Specifically check 0.618 level (most important for entry)
    fib_618_price = fib_levels.get("0.618")
    fib_618_distance = abs(current_price - fib_618_price) if fib_618_price else None
    
    return {
        "is_at_fib_level": is_at_level,
        "nearest_level": nearest_level,
        "nearest_level_price": fib_levels.get(nearest_level),
        "distance_from_level": nearest_distance,
        "fib_618_distance": fib_618_distance,
        "fib_618_price": fib_618_price,
    }


def validate_entry_with_fibonacci(current_price: float, direction: str, tfi: dict[str, Any], 
                                  require_618: bool = True, tolerance_pips: float = 5.0) -> tuple[bool, dict[str, Any]]:
    """Validate if current price is at a valid Fibonacci level for entry.
    
    Args:
        current_price: Current market price
        direction: "BUY" or "SELL"
        tfi: Timeframe indicators dict (should have M15 data)
        require_618: If True, require price to be within tolerance_pips of 0.618 level
        tolerance_pips: Tolerance in pips
    
    Returns:
        (is_valid_entry, analysis_dict)
    """
    try:
        m15_data = tfi.get("M15", {})
        if not m15_data:
            return False, {"reason": "No M15 data available"}
        
        # For now, use close price as reference (would use actual OHLC in production)
        close_price = _to_float(m15_data.get("close"))
        if close_price is None:
            return False, {"reason": "No M15 close price"}
        
        # In production, you'd fetch actual M15 candle data
        # For this implementation, we're using the calculated values
        swing_high = _to_float(m15_data.get("swing_high"))
        swing_low = _to_float(m15_data.get("swing_low"))
        
        if swing_high is None or swing_low is None:
            # Fallback: estimate from recent highs/lows
            return True, {
                "reason": "No swing data, allowing entry",
                "fib_check_available": False
            }
        
        fib_levels = calculate_fibonacci_levels(swing_high, swing_low, direction)
        analysis = check_fibonacci_confirmation(current_price, fib_levels, direction, tolerance_pips)
        
        if require_618:
            fib_618_dist = analysis.get("fib_618_distance")
            if fib_618_dist is None or fib_618_dist > tolerance_pips:
                return False, {
                    "reason": f"Price not at 0.618 Fib level (distance: {fib_618_dist:.1f} pips)",
                    "analysis": analysis,
                }
        
        return True, {
            "reason": "Price at valid Fibonacci level",
            "analysis": analysis,
            "fib_levels": fib_levels,
        }
        
    except Exception as exc:
        log_debug(f"Fibonacci validation error: {exc}")
        return True, {"reason": "Fibonacci check error, allowing entry", "error": str(exc)}


def get_fibonacci_summary(fib_levels: dict[str, float], current_price: float) -> str:
    """Format Fibonacci levels for logging."""
    if not fib_levels:
        return "No Fibonacci levels available"
    
    lines = ["[FIBONACCI LEVELS]"]
    for level_name in sorted(fib_levels.keys(), key=lambda x: float(x)):
        level_price = fib_levels[level_name]
        distance = current_price - level_price
        lines.append(f"  {level_name}: {level_price:.2f} (Δ {distance:+.2f})")
    
    return " | ".join(lines)
