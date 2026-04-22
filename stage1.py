"""STAGE 1: CHEAP SCAN — Fetch data, calculate indicators, run technical engine.

Runs every loop iteration. No expensive API calls.
"""

from __future__ import annotations

from typing import Any

import MetaTrader5 as mt5

import config
from indicators import calculate_indicators
from mt5_handler import get_market_data
from technical_engine import get_technical_signal
from utils import log_debug

TIMEFRAME_MAP = {
    "H4":  mt5.TIMEFRAME_H4,
    "H1":  mt5.TIMEFRAME_H1,
    "M15": mt5.TIMEFRAME_M15,
    "M5":  mt5.TIMEFRAME_M5,
    "M1":  mt5.TIMEFRAME_M1,
}


def fetch_indicators(symbol: str, n_candles: int) -> dict[str, dict[str, Any]]:
    """Fetch multi-timeframe indicators.
    
    Args:
        symbol: Trading symbol (e.g., "XAUUSD")
        n_candles: Number of candles to fetch
    
    Returns:
        Dict mapping timeframe labels to their indicator dictionaries
    
    Raises:
        ValueError: If any timeframe fails to fetch data
    """
    result: dict[str, dict[str, Any]] = {}
    for label, tf in TIMEFRAME_MAP.items():
        data = get_market_data(symbol, tf, n_candles)
        if data.empty:
            raise ValueError(f"No market data for {label}.")
        result[label] = calculate_indicators(data)
        ind = result[label]
        log_debug(
            f"{label} → trend={ind.get('trend_classification')} | "
            f"RSI={ind.get('rsi_14', 0):.2f} | "
            f"VWAP={ind.get('price_vs_vwap')} | "
            f"vol={ind.get('volume_classification')} ({ind.get('volume_ratio', 0):.3f})"
        )
    return result


def run_stage1(symbol: str, n_candles: int, high_impact_news: bool = False) -> dict[str, Any]:
    """Execute STAGE 1: Cheap technical scan.
    
    Args:
        symbol: Trading symbol
        n_candles: Number of candles for indicators
        high_impact_news: Whether high-impact news is currently active
    
    Returns:
        Dictionary containing:
        {
            "passed": bool,  # Whether GATE 1 threshold is met
            "technical_signal": str,  # "BUY", "SELL", "WAIT_FOR_CONFIRMATION", or "NO TRADE"
            "setup_direction": str,  # Expected direction if trade were to trigger
            "confidence": int,  # Confidence percentage (0-100)
            "score": float,  # Weighted technical score
            "max_score": float,  # Maximum possible score
            "indicators": dict,  # All timeframe indicators
            "gates": dict,  # Gate information for downstream logging
            "trade_levels": dict,  # Potential entry, SL, TP
            "risk_level": str,  # Risk assessment
            "mixed_signals": bool,  # Whether timeframes conflict
            "error": str | None,  # Error message if fetch/calculation failed
        }
    """
    try:
        log_debug("[STAGE 1] Fetching multi-timeframe market data...")
        
        # Fetch all timeframe indicators
        tfi = fetch_indicators(symbol, n_candles)
        
        log_debug("[STAGE 1] Running technical signal engine...")
        
        # Run the technical analysis
        tech = get_technical_signal(
            symbol=symbol,
            timeframe_indicators=tfi,
            high_impact_news=high_impact_news,
        )
        
        signal = tech["technical_signal"]
        confidence = tech["technical_confidence"]
        score = tech["weighted_score"]
        max_score = tech["max_score"]
        
        # GATE 1 CHECK: Does confidence meet minimum threshold?
        # Thresholds are typically 45-55% depending on session
        gate1_passed = confidence >= 45  # Will be refined with session threshold in main loop
        
        log_debug(
            f"[STAGE 1] GATE 1: confidence={confidence}% (threshold ~45%) | "
            f"score={score:.2f}/{max_score:.2f} | "
            f"signal={signal}"
        )
        
        return {
            "passed": gate1_passed,
            "technical_signal": signal,
            "setup_direction": tech.get("setup_direction", "NO TRADE"),
            "confidence": confidence,
            "score": score,
            "max_score": max_score,
            "indicators": tfi,
            "gates": tech.get("gates", {}),
            "trade_levels": tech.get("trade_levels", {}),
            "risk_level": tech.get("risk_level", "Unknown"),
            "mixed_signals": tech.get("mixed_signals", False),
            "error": None,
        }
    
    except Exception as exc:
        log_debug(f"[STAGE 1] ERROR: {exc}")
        return {
            "passed": False,
            "technical_signal": "NO TRADE",
            "setup_direction": "NO TRADE",
            "confidence": 0,
            "score": 0.0,
            "max_score": 12.5,
            "indicators": {},
            "gates": {},
            "trade_levels": {},
            "risk_level": "Unknown",
            "mixed_signals": False,
            "error": str(exc),
        }
