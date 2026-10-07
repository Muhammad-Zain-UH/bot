"""STAGE 1: CHEAP SCAN — Fetch data, calculate indicators, run technical engine.

Runs every loop iteration. No expensive API calls.
"""

from __future__ import annotations

from typing import Any

import MetaTrader5 as mt5

import config
try:
    from confidence_calibrator import apply_uncalibrated_lockout, is_calibration_complete
except ImportError:
    def apply_uncalibrated_lockout(confidence: int, **_: Any) -> tuple[int, str]:
        return confidence, ""

    def is_calibration_complete() -> tuple[bool, int]:
        return True, 0
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


def _is_soft_pullback_conflict(
    tf_label: str,
    setup_direction: str,
    tfa: dict[str, dict[str, Any]],
    structured_pullback_reentry: bool,
) -> bool:
    """Ignore weak H1/M15 pullback labels once continuation is re-confirmed."""
    if not structured_pullback_reentry or setup_direction not in {"BUY", "SELL"}:
        return False
    if tf_label not in {"H1", "M15"}:
        return False

    tf = tfa.get(tf_label, {})
    trend = str(tf.get("trend_classification", "Neutral"))
    pvwap = str(tf.get("price_vs_vwap", "Unknown"))

    if setup_direction == "BUY":
        return trend == "Weak Bearish" and pvwap == "Above"
    return trend == "Weak Bullish" and pvwap == "Below"


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
        
        # FIX 4: Calculate signal quality metrics for relaxed confidence cap
        setup_direction = tech.get("setup_direction", "NO TRADE")
        tfa = tech.get("timeframe_analysis", {})
        gates = tech.get("gates", {})
        structured_pullback_reentry = bool(gates.get("structured_pullback_reentry", False))

        # Check for 5/5 TF alignment
        tf_alignment_count = 0
        for tf_label in ["H4", "H1", "M15", "M5", "M1"]:
            tf_dir = tfa.get(tf_label, {}).get("direction", "NO TRADE")
            if tf_dir == setup_direction and setup_direction in {"BUY", "SELL"}:
                tf_alignment_count += 1
            elif _is_soft_pullback_conflict(tf_label, setup_direction, tfa, structured_pullback_reentry):
                tf_alignment_count += 1

        perfect_tf_alignment = (tf_alignment_count == 5)

        # Check for timeframe conflicts
        has_tf_conflicts = any(
            (
                tfa.get(label, {}).get("direction") != setup_direction
                and not _is_soft_pullback_conflict(label, setup_direction, tfa, structured_pullback_reentry)
            )
            for label in ["H4", "H1", "M15", "M5", "M1"]
            if setup_direction in {"BUY", "SELL"}
            and tfa.get(label, {}).get("direction") in {"BUY", "SELL"}
        )
        
        # Get H4 and H1 directions for calibration bypass rule
        h4_direction = tfa.get("H4", {}).get("direction", "NO TRADE")
        h1_direction = tfa.get("H1", {}).get("direction", "NO TRADE")
        
        # FIX 6: Apply uncalibrated lockout
        # CRITICAL: During calibration, if score > 8.0 and H4 == H1 AND no high-impact news, bypass penalties
        # This allows data accumulation without penalty paralysis, but blocks during NFP/FOMC/etc.
        # If < 50 completed trades, cap confidence at 50% and mark UNCALIBRATED
        # FIX 4: Allow 60% cap for exceptional setups (score > 8.0 + 5/5 alignment + no conflicts)
        uncal_confidence, uncal_label = apply_uncalibrated_lockout(
            confidence,
            score=abs(score),
            perfect_tf_alignment=perfect_tf_alignment,
            has_tf_conflicts=has_tf_conflicts,
            h4_direction=h4_direction,
            h1_direction=h1_direction,
            high_impact_news=high_impact_news,
        )
        if uncal_label:
            gates["calibration_status"] = uncal_label
            log_debug(f"[STAGE 1] {uncal_label} - confidence capped at {uncal_confidence}%")
        
        is_calibrated, completed_count = is_calibration_complete()
        
        # Log confidence breakdown
        try:
            tf_conflict = has_tf_conflicts
            
            # FIX 2: Log simple breakdown (actual penalties calculated in technical_engine with weighted logic)
            # Don't hardcode penalty estimates here — technical_engine already applies weighted penalties
            try:
                volume_penalty_applied = tech.get("gates", {}).get("m15_volume_thin", False)
                tf_conflict_applied = tf_conflict
                mixed_applied = tech.get("mixed_signals", False)
                
                # Log conditions only (actual penalty values are context-aware in technical_engine)
                log_debug(
                    f"[CONF BREAKDOWN] base=57% | "
                    f"volume_penalty={'applied' if volume_penalty_applied else '0.0'}% | "
                    f"tf_conflict_penalty={'weighted (see logs)' if tf_conflict_applied else '0.0'}% | "
                    f"mixed_signals_penalty={'-2.0' if mixed_applied else '0.0'}% | "
                    f"final={uncal_confidence}%"
                )
            except Exception:
                log_debug(
                    f"[CONF BREAKDOWN] final={uncal_confidence}% | "
                    f"tf_conflict={tf_conflict} | "
                    f"mixed_signals={tech.get('mixed_signals', False)}"
                )
            
            # Log timeframe conflicts if any
            if tf_conflict:
                conflicting_tfs = []
                setup_dir = tech.get("setup_direction")
                for label in ["H4", "H1", "M15", "M5", "M1"]:
                    tf_dir = tfa.get(label, {}).get("direction")
                    if (
                        tf_dir
                        and tf_dir != setup_dir
                        and tf_dir in {"BUY", "SELL"}
                        and not _is_soft_pullback_conflict(label, setup_dir, tfa, structured_pullback_reentry)
                    ):
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
            "timeframe_analysis": tfa,  # UPGRADE 1A: Include timeframe analysis for volume penalty exemption check
            "perfect_tf_alignment": perfect_tf_alignment,  # UPGRADE 1A: Export perfect alignment flag
            "has_tf_conflicts": has_tf_conflicts,  # UPGRADE 1A: Export conflict flag
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
