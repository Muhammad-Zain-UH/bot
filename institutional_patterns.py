"""Institutional pattern detection – identifies market structure and Wyckoff phases.

CORRECTED LOGIC:
- Upthrust: FAKE breakout (close above range with long upper wick) → REDUCE confidence
- Liquidity Sweep: Price touches daily extreme → CONFIRM trend if direction matches, REDUCE if counter
"""

from __future__ import annotations
from typing import Any


def detect_institutional_patterns(
    direction: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    timeframe_analysis: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Detect institutional patterns (Wyckoff phases, sweeps, upthrusts).
    
    CORRECTED LOGIC:
    - Upthrust (fake breakout): REDUCES confidence by 15% (counter-signal)
    - Liquidity Sweep: Matches direction = +8% (institutions swept shorts/longs), Counter = -12%
    
    Returns:
        {
            "confidence_adjustment": float (can be positive or negative),
            "is_upthrust": bool,
            "upthrust_severity": float,
            "is_liquidity_sweep": bool,
            "sweep_type": str ("bull" or "bear"),
            "sweep_severity": float,
            "upthrust_reason": str,
            "sweep_reason": str,
        }
    """
    try:
        m15 = timeframe_indicators.get("M15", {})
        m5 = timeframe_indicators.get("M5", {})
        d1 = timeframe_indicators.get("D1", {})
        
        patterns = {
            "confidence_adjustment": 0.0,
            "is_upthrust": False,
            "upthrust_severity": 0.0,
            "upthrust_reason": "",
            "is_liquidity_sweep": False,
            "sweep_type": None,
            "sweep_severity": 0.0,
            "sweep_reason": "",
        }
        
        # Get price data
        m15_close = m15.get("close")
        m15_open = m15.get("open")
        m15_high = m15.get("high")
        m15_low = m15.get("low")
        
        d1_high = d1.get("high")
        d1_low = d1.get("low")
        
        if not all([m15_close, m15_open, m15_high, m15_low, d1_high, d1_low]):
            return patterns
        
        # ===== UPTHRUST DETECTION (CORRECTED) =====
        # Fake breakout: Price near high with long upper wick + close rejecting down
        # This is a COUNTER-SIGNAL → REDUCE confidence
        if direction == "BUY":
            # For BUY setups: upthrust = price tried to go up but got rejected down
            body = abs(m15_close - m15_open)
            range_size = m15_high - m15_low
            if range_size > 0:
                wick_ratio = (range_size - body) / range_size  # Upper wick as % of range
                is_buy_rejection = m15_close < m15_open  # Close below open = rejection
                
                if m15_high > m15_open and wick_ratio > 0.55 and is_buy_rejection:
                    # Buyers failed: long wick up, then sold off
                    patterns["is_upthrust"] = True
                    patterns["upthrust_severity"] = min(wick_ratio, 1.0)
                    patterns["confidence_adjustment"] = -15.0  # REDUCE confidence by 15% (counter-signal)
                    patterns["upthrust_reason"] = f"BUY setup has upper wick rejection ({wick_ratio:.1%})"
        
        elif direction == "SELL":
            # For SELL setups: upthrust = price tried to go down but got rejected up
            body = abs(m15_close - m15_open)
            range_size = m15_high - m15_low
            if range_size > 0:
                wick_ratio = (range_size - body) / range_size  # Lower wick as % of range
                is_sell_rejection = m15_close > m15_open  # Close above open = rejection
                
                if m15_low < m15_open and wick_ratio > 0.55 and is_sell_rejection:
                    # Sellers failed: long wick down, then bought back up
                    patterns["is_upthrust"] = True
                    patterns["upthrust_severity"] = min(wick_ratio, 1.0)
                    patterns["confidence_adjustment"] = -15.0  # REDUCE confidence by 15% (counter-signal)
                    patterns["upthrust_reason"] = f"SELL setup has lower wick rejection ({wick_ratio:.1%})"
        
        # ===== LIQUIDITY SWEEP DETECTION (CORRECTED) =====
        # Price touches/breaks daily extreme → Institutions swept stops
        # If sweep direction MATCHES setup direction = institutions swept opposing stops = BULLISH for setup
        # If sweep direction OPPOSES setup direction = institutions swept our stops = BEARISH for setup
        
        if m15_close >= d1_high * 0.995:  # Within 0.5% of daily high (sweep/touch)
            if direction == "SELL":
                # SELL setup AND price touches daily HIGH = Sweep of BUY stops (bullish for us) = +8%
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bull"
                patterns["sweep_severity"] = (m15_close - d1_low) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = 8.0
                patterns["sweep_reason"] = f"Daily high touched: Institutions swept BUY stops"
            elif direction == "BUY":
                # BUY setup BUT price swept HIGH = Institutions swept BUY stops (bearish for us) = -12%
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bear"
                patterns["sweep_severity"] = (m15_close - d1_low) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = -12.0
                patterns["sweep_reason"] = f"Daily high touched: Institutions swept BUY stops (counter to setup)"
        
        elif m15_close <= d1_low * 1.005:  # Within 0.5% of daily low (sweep/touch)
            if direction == "BUY":
                # BUY setup AND price touches daily LOW = Sweep of SELL stops (bullish for us) = +8%
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bear"
                patterns["sweep_severity"] = (d1_high - m15_close) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = 8.0
                patterns["sweep_reason"] = f"Daily low touched: Institutions swept SELL stops"
            elif direction == "SELL":
                # SELL setup BUT price swept LOW = Institutions swept SELL stops (bearish for us) = -12%
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bull"
                patterns["sweep_severity"] = (d1_high - m15_close) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = -12.0
                patterns["sweep_reason"] = f"Daily low touched: Institutions swept SELL stops (counter to setup)"
        
        return patterns
    
    except Exception as e:
        return {
            "confidence_adjustment": 0.0,
            "is_upthrust": False,
            "upthrust_severity": 0.0,
            "upthrust_reason": "",
            "is_liquidity_sweep": False,
            "sweep_type": None,
            "sweep_severity": 0.0,
            "sweep_reason": "",
        }
