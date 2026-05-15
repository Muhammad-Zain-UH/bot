"""Institutional pattern detection – identifies market structure and Wyckoff phases."""

from __future__ import annotations
from typing import Any


def detect_institutional_patterns(
    direction: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    timeframe_analysis: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Detect institutional patterns (Wyckoff phases, sweeps, upthrusts).
    
    Returns:
        {
            "confidence_adjustment": float (0-100, positive or negative),
            "is_upthrust": bool,
            "upthrust_severity": float,
            "is_liquidity_sweep": bool,
            "sweep_type": str ("bull" or "bear"),
            "sweep_severity": float,
        }
    """
    try:
        m15 = timeframe_indicators.get("M15", {})
        m5 = timeframe_indicators.get("M5", {})
        m1 = timeframe_indicators.get("M1", {})
        d1 = timeframe_indicators.get("D1", {})
        
        patterns = {
            "confidence_adjustment": 0.0,
            "is_upthrust": False,
            "upthrust_severity": 0.0,
            "is_liquidity_sweep": False,
            "sweep_type": None,
            "sweep_severity": 0.0,
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
        
        # Simple upthrust detection (close near high with rejection)
        if direction == "SELL":
            body = abs(m15_close - m15_open)
            range_size = m15_high - m15_low
            if range_size > 0:
                wick_ratio = (range_size - body) / range_size
                if m15_close > m15_open and wick_ratio > 0.5:  # Long upper wick
                    patterns["is_upthrust"] = True
                    patterns["upthrust_severity"] = min(wick_ratio, 1.0)
                    patterns["confidence_adjustment"] = 5.0
        
        # Simple sweep detection (price touches daily extremes)
        if m15_close >= d1_high or m15_close <= d1_low:
            if direction == "BUY" and m15_close <= d1_low:
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bear"
                patterns["sweep_severity"] = (d1_high - m15_close) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = 8.0
            elif direction == "SELL" and m15_close >= d1_high:
                patterns["is_liquidity_sweep"] = True
                patterns["sweep_type"] = "bull"
                patterns["sweep_severity"] = (m15_close - d1_low) / max(d1_high - d1_low, 1.0)
                patterns["confidence_adjustment"] = 8.0
        
        return patterns
    
    except Exception as e:
        return {
            "confidence_adjustment": 0.0,
            "is_upthrust": False,
            "upthrust_severity": 0.0,
            "is_liquidity_sweep": False,
            "sweep_type": None,
            "sweep_severity": 0.0,
        }
