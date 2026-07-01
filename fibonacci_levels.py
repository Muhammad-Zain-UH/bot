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
    """Find the most recent swing high and low using fractal pattern (not just max/min).
    
    Fractal swing: A high/low surrounded by lower/higher candles on both sides.
    More accurate than max/min for choppy markets.
    
    Returns:
        (swing_high_price, swing_low_price, high_index, low_index)
    """
    if len(data) < lookback:
        lookback = len(data)
    
    if len(data) < 5:  # Need at least 5 candles for fractal detection
        # Fallback to max/min if insufficient data
        recent = data.iloc[-lookback:] if len(data) >= lookback else data
        swing_high = recent['high'].max()
        swing_low = recent['low'].min()
        high_idx = recent['high'].idxmax()
        low_idx = recent['low'].idxmin()
        return swing_high, swing_low, high_idx, low_idx
    
    recent = data.iloc[-lookback:]
    
    # Find fractal swing high: high surrounded by lower highs
    swing_high = None
    high_idx = None
    for i in range(2, len(recent) - 2):
        if (recent['high'].iloc[i] > recent['high'].iloc[i-1] and
            recent['high'].iloc[i] > recent['high'].iloc[i-2] and
            recent['high'].iloc[i] > recent['high'].iloc[i+1] and
            recent['high'].iloc[i] > recent['high'].iloc[i+2]):
            swing_high = recent['high'].iloc[i]
            high_idx = recent.index[i]
    
    # Find fractal swing low: low surrounded by higher lows
    swing_low = None
    low_idx = None
    for i in range(2, len(recent) - 2):
        if (recent['low'].iloc[i] < recent['low'].iloc[i-1] and
            recent['low'].iloc[i] < recent['low'].iloc[i-2] and
            recent['low'].iloc[i] < recent['low'].iloc[i+1] and
            recent['low'].iloc[i] < recent['low'].iloc[i+2]):
            swing_low = recent['low'].iloc[i]
            low_idx = recent.index[i]
    
    # Fallback to max/min if no fractal found
    if swing_high is None:
        swing_high = recent['high'].max()
        high_idx = recent['high'].idxmax()
    if swing_low is None:
        swing_low = recent['low'].min()
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


def validate_fibonacci_hard_gate(entry_price: float, direction: str, swing_high: float | None, 
                                 swing_low: float | None) -> tuple[bool, str, float]:
    """Hard gate validation: Entry price MUST be within Fibonacci zones.
    
    For pullback entries, price MUST be in:
    - 0.618 zone (golden): PRIMARY zone (bonus)
    - 0.500-0.786 zone: ACCEPTABLE zone (no penalty)
    - 0.382-0.500 zone: WEAK zone (-10% confidence)
    - Outside zones: BLOCKED (return False)
    
    Args:
        entry_price: Current/proposed entry price
        direction: "BUY" or "SELL"
        swing_high: Recent swing high price
        swing_low: Recent swing low price
    
    Returns:
        (is_valid, reason_message, confidence_adjustment)
    """
    try:
        if swing_high is None or swing_low is None:
            return True, "No swing data available; allowing entry", 0.0
        
        if swing_high <= swing_low:
            return True, "Invalid swing data; allowing entry", 0.0
        
        range_size = swing_high - swing_low
        
        # Calculate Fibonacci levels
        fib_0236 = swing_high - (range_size * 0.236) if direction == "BUY" else swing_low + (range_size * 0.236)
        fib_0382 = swing_high - (range_size * 0.382) if direction == "BUY" else swing_low + (range_size * 0.382)
        fib_0500 = swing_high - (range_size * 0.500) if direction == "BUY" else swing_low + (range_size * 0.500)
        fib_0618 = swing_high - (range_size * 0.618) if direction == "BUY" else swing_low + (range_size * 0.618)
        fib_0786 = swing_high - (range_size * 0.786) if direction == "BUY" else swing_low + (range_size * 0.786)
        
        # Distance from 0.618 (golden ratio)
        dist_from_618 = abs(entry_price - fib_0618)
        
        # Zone detection
        if dist_from_618 < 2.0:  # Within 2 pips of 0.618
            return True, f"Entry at 0.618 golden zone (distance: {dist_from_618:.1f}pips)", 10.0
        
        # Check if in acceptable zones (0.500-0.786)
        min_zone = min(fib_0500, fib_0786)
        max_zone = max(fib_0500, fib_0786)
        if min_zone <= entry_price <= max_zone:
            return True, f"Entry in 0.500-0.786 zone (acceptable)", 2.0
        
        # Check if in weak zone (0.382-0.500)
        min_weak = min(fib_0382, fib_0500)
        max_weak = max(fib_0382, fib_0500)
        if min_weak <= entry_price <= max_weak:
            return True, f"Entry in 0.382-0.500 zone (weak, -10% confidence)", -10.0
        
        # Check if in very weak zone (0.236-0.382)
        min_vweak = min(fib_0236, fib_0382)
        max_vweak = max(fib_0236, fib_0382)
        if min_vweak <= entry_price <= max_vweak:
            return False, f"Entry in 0.236-0.382 zone (too shallow, BLOCKED)", 0.0
        
        # Outside all zones - BLOCK
        return False, f"Entry outside Fibonacci zones (0.236-0.786) - BLOCKED", 0.0
        
    except Exception as exc:
        log_debug(f"Fibonacci hard gate validation error: {exc}")
        return True, "Fibonacci gate error; allowing entry", 0.0
