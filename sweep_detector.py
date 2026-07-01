"""LAYER 5: SWEEP + CHoCH/BOS DETECTOR - Real vs Fake Breakouts.

Sweep Detection for XAUUSD:

REAL SWEEP (Bullish):
- Candle wick goes BELOW liquidity level (sweep wick low)
- Wick penetration: 3-8 pips below pool (stops triggered)
- Candle CLOSES back ABOVE pool level within same/next candle
- Close > Open (bullish confirmation)
- Volume on sweep candle ≥ baseline (no volume fade)

REAL SWEEP (Bearish):
- Candle wick goes ABOVE liquidity level
- Wick penetration: 3-8 pips above pool
- Candle CLOSES back BELOW pool level within same/next candle
- Close < Open (bearish confirmation)

Quality Checklist (Real sweep must pass 3+):
- [ ] Wick ≥ 1.5× candle body size
- [ ] Close back inside prior range within 1 candle
- [ ] Volume spike on sweep vs baseline
- [ ] Price closes at opposite end of sweep range (not middle)

CHoCH (M15 STRUCTURE SHIFT):
- After sweep, M15 must close ABOVE last M15 Lower High (bullish)
  or BELOW last M15 Lower Low (bearish)
- Grade: B-Tier (decent setup, 0.75% risk)

BOS (H1 BREAK OF STRUCTURE):
- After CHoCH confirmed, H1 must close above significant swing high
  or below swing low
- Grade: A+-Tier (strong setup, 1.5% risk)
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


def _estimate_m15_atr(m15_data: pd.DataFrame, default: float = 15.0) -> float:
    """Estimate a lightweight ATR for M15 sweep filtering."""
    try:
        if m15_data is None or len(m15_data) < 2 or "close" not in m15_data.columns:
            return default
        atr_series = m15_data["close"].diff().abs().rolling(14).mean()
        atr_value = _to_float(atr_series.iloc[-1]) if len(atr_series) > 0 else None
        return atr_value if atr_value is not None and atr_value > 0 else default
    except Exception:
        return default


def _find_recent_fractal_level(data: pd.DataFrame, column: str) -> float | None:
    """Find the most recent confirmed fractal high/low."""
    if data is None or len(data) < 5 or column not in data.columns:
        return None

    recent = data.tail(25).reset_index(drop=True)
    for i in range(len(recent) - 3, 1, -1):
        center = _to_float(recent.iloc[i][column])
        left_1 = _to_float(recent.iloc[i - 1][column])
        left_2 = _to_float(recent.iloc[i - 2][column])
        right_1 = _to_float(recent.iloc[i + 1][column])
        right_2 = _to_float(recent.iloc[i + 2][column])
        if None in (center, left_1, left_2, right_1, right_2):
            continue
        if column == "high" and center > left_1 and center > left_2 and center > right_1 and center > right_2:
            return center
        if column == "low" and center < left_1 and center < left_2 and center < right_1 and center < right_2:
            return center

    return _to_float(recent[column].max() if column == "high" else recent[column].min())


def _assess_sweep_state(
    m15_data: pd.DataFrame,
    liquidity_level: float,
    direction: str,
    sweep_result: dict[str, Any],
) -> dict[str, Any]:
    """Classify a sweep setup as PASS, WATCH, or BLOCK."""
    if m15_data is None or len(m15_data) < 3:
        return {
            "state": "BLOCK",
            "reason": "Insufficient M15 data",
        }

    if sweep_result.get("sweep_confirmed") or sweep_result.get("choch_confirmed") or sweep_result.get("bos_confirmed"):
        return {
            "state": "PASS",
            "reason": sweep_result.get("reason", sweep_result.get("reasoning", "Structure confirmed")),
        }

    recent = m15_data.tail(12)
    m15_atr = _estimate_m15_atr(m15_data)
    near_buffer = max(2.5, m15_atr * 0.20)
    momentum_buffer = max(5.0, m15_atr * 0.50)

    if direction == "BUY":
        closest_low = _to_float(recent["low"].min()) if "low" in recent.columns else None
        if closest_low is not None:
            distance_to_level = liquidity_level - closest_low
            if -near_buffer <= distance_to_level <= momentum_buffer:
                return {
                    "state": "WATCH",
                    "reason": (
                        f"BUY zone is near liquidity {liquidity_level:.2f}; closest low {closest_low:.2f}, "
                        f"waiting for wick/close confirmation."
                    ),
                }
    elif direction == "SELL":
        closest_high = _to_float(recent["high"].max()) if "high" in recent.columns else None
        if closest_high is not None:
            distance_to_level = closest_high - liquidity_level
            if -near_buffer <= distance_to_level <= momentum_buffer:
                return {
                    "state": "WATCH",
                    "reason": (
                        f"SELL zone is near liquidity {liquidity_level:.2f}; closest high {closest_high:.2f}, "
                        f"waiting for wick/close confirmation."
                    ),
                }

    return {
        "state": "BLOCK",
        "reason": sweep_result.get("reasoning", "No sweep or CHoCH detected"),
    }


def detect_sweep(
    m15_data: pd.DataFrame,
    liquidity_level: float,
    direction: str,
    tolerance_pips: float = 1.5,
    l4_override_level: float | None = None,
) -> dict[str, Any]:
    """
    Detect if liquidity sweep occurred at specific level.
    
    Args:
        m15_data: M15 OHLC data
        liquidity_level: Target liquidity pool level
        direction: "BUY" (sweep below level) or "SELL" (sweep above level)
        tolerance_pips: Tolerance for level matching (default 1.5)
        l4_override_level: (FIX #3) Override with exact L4 sweep level for hard handshake
    
    Returns:
        {
            "sweep_confirmed": bool,
            "sweep_type": "bullish_sweep | bearish_sweep | no_sweep",
            "sweep_level": float,
            "sweep_depth": float,  # pips below/above level
            "sweep_candle_idx": int,
            "sweep_wick_low": float | None,
            "sweep_wick_high": float | None,
            "sweep_wick": float,
            "sweep_body": float,
            "sweep_volume": float,
            "sweep_quality": 0.0-10.0,
            "reasoning": str,
        }
    """
    try:
        # FIX #3 (PHASE 4): HARD HANDSHAKE - Use exact L4 level if provided
        if l4_override_level is not None:
            liquidity_level = l4_override_level
        if len(m15_data) < 3:
            return {
                "sweep_confirmed": False,
                "sweep_type": "no_sweep",
                "sweep_level": None,
                "sweep_depth": None,
                "sweep_candle_idx": None,
                "sweep_wick_low": None,
                "sweep_wick_high": None,
                "sweep_wick": None,
                "sweep_body": None,
                "sweep_volume": None,
                "sweep_quality": 0.0,
                "reasoning": "Insufficient M15 data",
            }
        
        recent = m15_data.tail(15)  # Give the detector a slightly wider memory
        baseline_volume = m15_data["tick_volume"].mean()
        m15_atr = _estimate_m15_atr(m15_data)
        sweep_min = max(2.5, m15_atr * 0.12)
        sweep_max = max(30.0, m15_atr * 2.0)
        volume_threshold = 1.4

        for idx in range(len(recent) - 1, -1, -1):
            candles_ago = len(recent) - 1 - idx
            # Allow older sweeps to be recognized, but keep the signal reasonably fresh.
            if candles_ago > 8:
                continue

            candle = recent.iloc[idx]
            candle_open = _to_float(candle["open"])
            candle_close = _to_float(candle["close"])
            candle_high = _to_float(candle["high"])
            candle_low = _to_float(candle["low"])
            candle_volume = _to_float(candle.get("tick_volume", baseline_volume))
            
            if any(v is None for v in [candle_open, candle_close, candle_high, candle_low]):
                continue
            
            body = abs(candle_close - candle_open)
            
            # BUY sweep: wick below level, close above level
            if direction == "BUY":
                sweep_depth = liquidity_level - candle_low
                
                # Check: wick goes below level using dynamic XAUUSD range
                if sweep_min <= sweep_depth <= sweep_max and candle_close > liquidity_level:
                    wick_size = liquidity_level - candle_low
                    wick_ratio = wick_size / body if body > 0 else 0
                    
                    # Quality checks
                    quality = 0.0
                    checks_passed = 0
                    
                    # Check 1: Wick ≥ 1.5× body
                    if wick_ratio >= 1.5:
                        quality += 3.0
                        checks_passed += 1
                    
                    # Check 2: Volume spike
                    if candle_volume >= baseline_volume * volume_threshold:
                        quality += 2.0
                        checks_passed += 1
                    
                    # Check 3: Close in upper 50% of range
                    range_size = candle_high - candle_low
                    close_pos = (candle_close - candle_low) / range_size if range_size > 0 else 0
                    if close_pos > 0.5:
                        quality += 2.0
                        checks_passed += 1
                    
                    # Check 4: Next candle continues up (if available)
                    if idx < len(recent) - 1:
                        next_candle = recent.iloc[idx + 1]
                        if _to_float(next_candle["close"]) > candle_close:
                            quality += 1.0
                            checks_passed += 1
                    
                    if checks_passed >= 2:  # Pass if 2+ checks passed
                        return {
                            "sweep_confirmed": True,
                            "sweep_type": "bullish_sweep",
                            "sweep_level": liquidity_level,
                            "sweep_depth": sweep_depth,
                            "sweep_candle_idx": idx,
                            "sweep_wick_low": candle_low,
                            "sweep_wick_high": candle_high,
                            "sweep_wick": wick_size,
                            "sweep_body": body,
                            "sweep_volume": candle_volume / baseline_volume if baseline_volume > 0 else 1.0,
                            "sweep_quality": min(10.0, quality),
                            "reasoning": f"Bullish sweep at {liquidity_level:.2f}: wick {wick_size:.2f}, volume {candle_volume/baseline_volume:.1f}x, checks {checks_passed}/4",
                        }
            
            # SELL sweep: wick above level, close below level
            elif direction == "SELL":
                sweep_depth = candle_high - liquidity_level
                
                # Check: wick goes above level using dynamic XAUUSD range
                if sweep_min <= sweep_depth <= sweep_max and candle_close < liquidity_level:
                    wick_size = candle_high - liquidity_level
                    wick_ratio = wick_size / body if body > 0 else 0
                    
                    # Quality checks
                    quality = 0.0
                    checks_passed = 0
                    
                    # Check 1: Wick ≥ 1.5× body
                    if wick_ratio >= 1.5:
                        quality += 3.0
                        checks_passed += 1
                    
                    # Check 2: Volume spike
                    if candle_volume >= baseline_volume * volume_threshold:
                        quality += 2.0
                        checks_passed += 1
                    
                    # Check 3: Close in lower 50% of range
                    range_size = candle_high - candle_low
                    close_pos = (candle_close - candle_low) / range_size if range_size > 0 else 0
                    if close_pos < 0.5:
                        quality += 2.0
                        checks_passed += 1
                    
                    # Check 4: Next candle continues down
                    if idx < len(recent) - 1:
                        next_candle = recent.iloc[idx + 1]
                        if _to_float(next_candle["close"]) < candle_close:
                            quality += 1.0
                            checks_passed += 1
                    
                    if checks_passed >= 2:
                        return {
                            "sweep_confirmed": True,
                            "sweep_type": "bearish_sweep",
                            "sweep_level": liquidity_level,
                            "sweep_depth": sweep_depth,
                            "sweep_candle_idx": idx,
                            "sweep_wick_low": candle_low,
                            "sweep_wick_high": candle_high,
                            "sweep_wick": wick_size,
                            "sweep_body": body,
                            "sweep_volume": candle_volume / baseline_volume if baseline_volume > 0 else 1.0,
                            "sweep_quality": min(10.0, quality),
                            "reasoning": f"Bearish sweep at {liquidity_level:.2f}: wick {wick_size:.2f}, volume {candle_volume/baseline_volume:.1f}x, checks {checks_passed}/4",
                        }
        
        return {
            "sweep_confirmed": False,
            "sweep_type": "no_sweep",
            "sweep_level": liquidity_level,
            "sweep_depth": None,
            "sweep_candle_idx": None,
            "sweep_wick_low": None,
            "sweep_wick_high": None,
            "sweep_wick": None,
            "sweep_body": None,
            "sweep_volume": None,
            "sweep_quality": 0.0,
            "reasoning": f"No sweep detected at {liquidity_level:.2f} in last 10 candles",
        }
    
    except Exception as exc:
        log_debug(f"Sweep detection error: {exc}")
        return {
            "sweep_confirmed": False,
            "sweep_type": "no_sweep",
            "sweep_level": None,
            "sweep_depth": None,
            "sweep_candle_idx": None,
            "sweep_wick_low": None,
            "sweep_wick_high": None,
            "sweep_wick": None,
            "sweep_body": None,
            "sweep_volume": None,
            "sweep_quality": 0.0,
            "reasoning": f"Error: {str(exc)}",
        }


def detect_choch(
    m15_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect CHoCH (Change of Character) on M15.
    
    Bullish CHoCH: M15 close above last Lower High (LH)
    Bearish CHoCH: M15 close below last Lower Low (LL)
    
    Returns:
        {
            "choch_confirmed": bool,
            "choch_level": float,
            "choch_type": "m15_bullish_choch | m15_bearish_choch",
            "reasoning": str,
        }
    """
    try:
        if len(m15_data) < 10:
            return {
                "choch_confirmed": False,
                "choch_level": None,
                "choch_type": None,
                "reasoning": "Insufficient M15 data for CHoCH",
            }
        
        recent = m15_data.tail(25).reset_index(drop=True)
        current_close = _to_float(recent.iloc[-1]["close"])
        
        if direction == "BUY":
            # Looking for close above the most recent confirmed lower high / swing high.
            last_lh = _find_recent_fractal_level(recent, "high")
            if last_lh is None:
                last_lh = _to_float(recent["high"].max())
            
            # CHoCH confirmed if current close > last LH
            if current_close > last_lh:
                return {
                    "choch_confirmed": True,
                    "choch_level": last_lh,
                    "choch_type": "m15_bullish_choch",
                    "reasoning": f"M15 bullish CHoCH: close {current_close:.2f} > LH {last_lh:.2f}",
                }
        
        else:  # SELL
            # Looking for close below the most recent confirmed lower low / swing low.
            last_ll = _find_recent_fractal_level(recent, "low")
            if last_ll is None:
                last_ll = _to_float(recent["low"].min())
            
            # CHoCH confirmed if current close < last LL
            if current_close < last_ll:
                return {
                    "choch_confirmed": True,
                    "choch_level": last_ll,
                    "choch_type": "m15_bearish_choch",
                    "reasoning": f"M15 bearish CHoCH: close {current_close:.2f} < LL {last_ll:.2f}",
                }
        
        return {
            "choch_confirmed": False,
            "choch_level": None,
            "choch_type": None,
            "reasoning": f"M15 CHoCH not confirmed for {direction}",
        }
    
    except Exception as exc:
        log_debug(f"CHoCH detection error: {exc}")
        return {
            "choch_confirmed": False,
            "choch_level": None,
            "choch_type": None,
            "reasoning": f"Error: {str(exc)}",
        }


def detect_bos(
    h1_data: pd.DataFrame,
    direction: str,
    reference_level: float | None = None,
) -> dict[str, Any]:
    """
    Detect BOS (Break of Structure) on H1.
    
    Bullish BOS: H1 close above significant swing high
    Bearish BOS: H1 close below significant swing low
    
    Returns:
        {
            "bos_confirmed": bool,
            "bos_level": float,
            "bos_type": "h1_bullish_bos | h1_bearish_bos",
            "reasoning": str,
        }
    """
    try:
        if len(h1_data) < 20:
            return {
                "bos_confirmed": False,
                "bos_level": None,
                "bos_type": None,
                "reasoning": "Insufficient H1 data for BOS",
            }
        
        recent = h1_data.tail(30)
        current_close = _to_float(recent.iloc[-1]["close"])
        
        if direction == "BUY":
            # Find SIGNIFICANT swing high (not just max)
            # Swing high = touched 2+ times within 2 pips
            highs = recent["high"].values
            swing_candidates = []
            
            for i in range(len(highs) - 5):
                high_val = highs[i]
                # Count touches within 2 pips
                touches = sum(1 for h in highs[i:i+15] if abs(h - high_val) <= 2.0)
                if touches >= 2:
                    swing_candidates.append(high_val)
            
            swing_high = max(swing_candidates) if swing_candidates else recent["high"].max()
            
            # BOS confirmed if close cleanly above it
            if current_close > swing_high:
                return {
                    "bos_confirmed": True,
                    "bos_level": swing_high,
                    "bos_type": "h1_bullish_bos",
                    "reasoning": f"H1 bullish BOS: close {current_close:.2f} > swing high {swing_high:.2f}",
                }
        
        else:  # SELL
            # Find SIGNIFICANT swing low (not just min)
            # Swing low = touched 2+ times within 2 pips
            lows = recent["low"].values
            swing_candidates = []
            
            for i in range(len(lows) - 5):
                low_val = lows[i]
                # Count touches within 2 pips
                touches = sum(1 for l in lows[i:i+15] if abs(l - low_val) <= 2.0)
                if touches >= 2:
                    swing_candidates.append(low_val)
            
            swing_low = min(swing_candidates) if swing_candidates else recent["low"].min()
            
            # BOS confirmed if close cleanly below it
            if current_close < swing_low:
                return {
                    "bos_confirmed": True,
                    "bos_level": swing_low,
                    "bos_type": "h1_bearish_bos",
                    "reasoning": f"H1 bearish BOS: close {current_close:.2f} < swing low {swing_low:.2f}",
                }
        
        return {
            "bos_confirmed": False,
            "bos_level": None,
            "bos_type": None,
            "reasoning": f"H1 BOS not confirmed for {direction}",
        }
    
    except Exception as exc:
        log_debug(f"BOS detection error: {exc}")
        return {
            "bos_confirmed": False,
            "bos_level": None,
            "bos_type": None,
            "reasoning": f"Error: {str(exc)}",
        }


def get_sweep_and_structure(
    m15_data: pd.DataFrame,
    h1_data: pd.DataFrame,
    liquidity_level: float,
    direction: str,
    l4_override_level: float | None = None,
) -> dict[str, Any]:
    """
    Complete sweep detection + CHoCH/BOS analysis.
    
    FIX #8 (PHASE 4): Accepts exact L4 sweep level as override (hard handshake)
    
    Returns:
        {
            "sweep_confirmed": bool,
            "sweep_quality": 0.0-10.0,
            "sweep_wick_low": float | None,
            "sweep_wick_high": float | None,
            "choch_confirmed": bool,
            "choch_level": float,
            "bos_confirmed": bool,
            "bos_level": float,
            "setup_grade": "A+ (BOS) | B (CHoCH only) | INVALID",
            "reason": str,
        }
    """
    # FIX #8: Pass L4 override level to detect_sweep for hard handshake
    # Detect sweep using exact L4-provided level if available
    sweep_result = detect_sweep(m15_data, liquidity_level, direction, l4_override_level=l4_override_level)
    
    # IMPORTANT: Always evaluate CHoCH independently, even if sweep fails
    # CHoCH (Change of Character) is a valid setup type even without sweep
    choch_result = detect_choch(m15_data, direction)
    
    # If CHoCH confirmed, check for BOS
    bos_result = detect_bos(h1_data, direction) if choch_result["choch_confirmed"] else {
        "bos_confirmed": False,
        "bos_level": None,
        "bos_type": None,
    }
    
    # Determine grade (now allows CHoCH-only setups even without sweep)
    if bos_result["bos_confirmed"]:
        grade = "A+ (BOS)"
    elif choch_result["choch_confirmed"]:
        grade = "B (CHoCH only)"
    elif sweep_result["sweep_confirmed"]:
        grade = "C (Sweep only)"
    else:
        grade = "INVALID"

    gate_state = _assess_sweep_state(m15_data, liquidity_level, direction, {
        **sweep_result,
        **choch_result,
        **bos_result,
        "reason": f"{sweep_result.get('reasoning', '')} | {choch_result.get('reasoning', '')} | {bos_result.get('reasoning', '')}",
    })
    
    return {
        "sweep_confirmed": sweep_result["sweep_confirmed"],
        "sweep_type": sweep_result.get("sweep_type"),
        "sweep_level": sweep_result.get("sweep_level"),
        "sweep_quality": sweep_result["sweep_quality"],
        "sweep_wick_low": sweep_result.get("sweep_wick_low"),
        "sweep_wick_high": sweep_result.get("sweep_wick_high"),
        "sweep_reasoning": sweep_result.get("reasoning"),
        "choch_confirmed": choch_result["choch_confirmed"],
        "choch_level": choch_result["choch_level"],
        "bos_confirmed": bos_result["bos_confirmed"],
        "bos_level": bos_result["bos_level"],
        "setup_grade": grade,
        "gate_state": gate_state["state"],
        "gate_reason": gate_state["reason"],
        "reason": f"Sweep quality: {sweep_result['sweep_quality']:.1f}, CHoCH: {choch_result['choch_confirmed']}, BOS: {bos_result['bos_confirmed']}",
    }
