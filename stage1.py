"""STAGE 1: CHEAP SCAN — Fetch data, calculate indicators, run technical engine.

Runs every loop iteration. No expensive API calls.
"""

from __future__ import annotations

from typing import Any

import MetaTrader5 as mt5

import config
from confidence_calibrator import apply_uncalibrated_lockout, is_calibration_complete
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
        
        # FIX 6: Apply uncalibrated lockout
        # If < 50 completed trades, cap confidence at 50% and mark UNCALIBRATED
        uncal_confidence, uncal_label = apply_uncalibrated_lockout(confidence)
        gates = tech.get("gates", {})
        if uncal_label:
            gates["calibration_status"] = uncal_label
            log_debug(f"[STAGE 1] {uncal_label} - confidence capped at {uncal_confidence}%")
        
        is_calibrated, completed_count = is_calibration_complete()
        
        # Log confidence breakdown
        try:
            tfa = tech.get("timeframe_analysis", {})
            tf_conflict = any(
                tfa.get(label, {}).get("direction") != tech.get("setup_direction")
                for label in ["H4", "H1", "M15", "M5", "M1"]
                if tech.get("setup_direction") in {"BUY", "SELL"}
                and tfa.get(label, {}).get("direction") in {"BUY", "SELL"}
            )
            
            # FIX 2: Log detailed numeric penalties instead of boolean flags
            try:
                # Calculate actual penalty values from score components
                # NOTE: score and max_score already set from tech["weighted_score"] and tech["max_score"] above
                # Do NOT overwrite with tech.get("score", 0.0) — that key doesn't exist and resets to 0!
                volume_penalty_applied = tech.get("gates", {}).get("m15_volume_thin", False)
                volume_penalty_points = tech.get("gates", {}).get("volume_penalty_points", 0.0)
                
                # Estimate component contributions
                vol_penalty = -volume_penalty_points if volume_penalty_applied else 0.0
                tf_penalty = -8.0 if tf_conflict else 0.0
                mixed_penalty = -2.0 if tech.get("mixed_signals", False) else 0.0
                
                # Base confidence before penalties
                base_conf_est = int(uncal_confidence - vol_penalty - tf_penalty - mixed_penalty)
                base_conf_est = max(0, min(100, base_conf_est))  # Clamp to 0-100
                
                log_debug(
                    f"[CONF BREAKDOWN] base={base_conf_est}% | "
                    f"volume_penalty={vol_penalty:.1f}% | "
                    f"tf_conflict_penalty={tf_penalty:.1f}% | "
                    f"mixed_signals_penalty={mixed_penalty:.1f}% | "
                    f"final={uncal_confidence}%"
                )
            except Exception:
                log_debug(
                    f"[CONF BREAKDOWN] base={confidence:.0f}% | "
                    f"tf_conflict={tf_conflict} | "
                    f"mixed_signals={tech.get('mixed_signals', False)} | "
                    f"final={uncal_confidence}%"
                )
            
            # Log timeframe conflicts if any
            if tf_conflict:
                conflicting_tfs = []
                setup_dir = tech.get("setup_direction")
                for label in ["H4", "H1", "M15", "M5", "M1"]:
                    tf_dir = tfa.get(label, {}).get("direction")
                    if tf_dir and tf_dir != setup_dir and tf_dir in {"BUY", "SELL"}:
                        conflicting_tfs.append(label)
                if conflicting_tfs:
                    log_debug(
                        f"[TF CONFLICT] {', '.join(conflicting_tfs)} contradicts majority {setup_dir} signal — "
                        f"confidence penalized"
                    )
        except Exception:
            pass  # Silent fallback if breakdown fails
        # BUG FIX 3: Confidence below 35% is a hard skip — don't process at all
        if uncal_confidence < 35:
            log_debug(f"[STAGE 1] HARD SKIP: confidence {uncal_confidence}% below minimum floor of 35%")
            return {
                "passed": False,
                "technical_signal": "NO TRADE",
                "setup_direction": "NO TRADE",
                "confidence": uncal_confidence,
                "confidence_display": f"{uncal_confidence}% (HARD SKIP - below 35% floor)",
                "score": score,
                "max_score": max_score,
                "indicators": tfi,
                "gates": {**gates, "confidence_floor_block": True, "confidence_floor_reason": f"confidence {uncal_confidence}% below 35% minimum"},
                "trade_levels": tech.get("trade_levels", {}),
                "risk_level": tech.get("risk_level", "Unknown"),
                "mixed_signals": tech.get("mixed_signals", False),
                "error": None,
            }
        
        # GATE 1 CHECK: Use confidence-based gating in both modes
        # During calibration, score percentage is logged for information only
        # GATE DECISION: Always based on confidence, never on score
        gate1_passed = uncal_confidence >= 45
        
        if is_calibrated:
            # Production mode: confidence-based Gate 1
            gate1_reason = f"confidence {uncal_confidence}% >= 45%"
        else:
            # Calibration phase: score check is INFORMATIONAL ONLY, gate still uses confidence
            # Score threshold normalized to 0-100 scale: score/max_score * 100
            score_pct = (abs(score) / max_score * 100) if max_score > 0 else 0
            gate1_reason = f"CALIBRATION MODE — score check informational only | score={score_pct:.0f}%/45% (threshold not applied) | confidence gate active: {uncal_confidence}% >= 45% (completed: {completed_count}/50 trades)"
        
        log_debug(
            f"[STAGE 1] GATE 1: {gate1_reason} | "
            f"score={score:.2f}/{max_score:.2f} | "
            f"signal={signal}"
        )
        
        return {
            "passed": gate1_passed,
            "technical_signal": signal,
            "setup_direction": tech.get("setup_direction", "NO TRADE"),
            "confidence": uncal_confidence,  # Use capped confidence
            "confidence_display": f"{uncal_confidence}% {uncal_label}",
            "score": score,
            "max_score": max_score,
            "indicators": tfi,
            "gates": gates,
            "trade_levels": tech.get("trade_levels", {}),
            "risk_level": tech.get("risk_level", "Unknown"),
            "mixed_signals": tech.get("mixed_signals", False),
            "scorecard": tech.get("scorecard", {}),  # FIX 1: Include scorecard for monitor display
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
