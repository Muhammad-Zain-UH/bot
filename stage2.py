"""STAGE 2: INTERMARKET CHECK — Hard blocks & correlation scoring.

Only runs if STAGE 1 gate passes.
Implements hard blocks A, B, C, D that cause immediate continue/block.
"""

from __future__ import annotations

from typing import Any

import config
from intermarket import get_intermarket_analysis
from utils import log_debug


def run_stage2(
    direction: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    oversold_depth_m1: float | None = None,  # UPGRADE 1B: Oversold depth tracking
) -> dict[str, Any]:
    """Execute STAGE 2: Intermarket analysis with hard blocks.
    
    HARD BLOCKS (absolute vetoes):
    - BLOCK A: XAGUSD is "Strong Bearish" AND direction is BUY
    - BLOCK B: M1 RSI > 70 AND direction is BUY
    - BLOCK C: M1 RSI < 30 AND direction is SELL (unless in recovery from oversold)
    - BLOCK D: Intermarket score <= -3
    
    Args:
        direction: Trade direction (BUY, SELL, etc.)
        timeframe_indicators: Dict of timeframe indicators
        oversold_depth_m1: Lowest M1 RSI in current oversold episode (None if episode cleared)
    
    Returns:
        {
            "passed": bool,  # Whether GATE 2 is passed (no hard blocks)
            "intermarket_score": int,  # Score from intermarket correlation
            "intermarket_label": str,  # Label for the score
            "hard_block": str | None,  # Name of triggered hard block (A, B, C, or D)
            "hard_block_reason": str,  # Explanation of the block
            "headwind_detected": bool,  # True if score < -2
            "headwind_reason": str,  # Explanation of headwind
            "data": dict,  # Full intermarket data for logging
            "error": str | None,  # Error message if analysis failed
        }
    """
    try:
        log_debug("[STAGE 2] Analyzing intermarket correlation...")
        
        # Fetch intermarket data
        intermarket = get_intermarket_analysis(direction)
        score = intermarket.get("intermarket_score", 0)
        label = intermarket.get("alignment_label", "Neutral")
        
        xagusd_trend = intermarket.get("silver_trend", "Unknown")
        m1_rsi = timeframe_indicators.get("M1", {}).get("rsi_14")
        
        # HARD BLOCK A: XAGUSD strong bearish + BUY signal
        if direction == "BUY" and "Strong Bearish" in str(xagusd_trend):
            log_debug(f"[STAGE 2] HARD BLOCK A: XAGUSD is {xagusd_trend}, BUY blocked")
            return {
                "passed": False,
                "intermarket_score": score,
                "intermarket_label": label,
                "hard_block": "A",
                "hard_block_reason": f"Silver (XAGUSD) is {xagusd_trend} — gold BUY conflicted",
                "headwind_detected": False,
                "headwind_reason": "",
                "data": intermarket,
                "error": None,
            }
        
        # HARD BLOCK B: M1 RSI > 70 + BUY
        if direction == "BUY" and m1_rsi is not None and m1_rsi > 70:
            log_debug(f"[STAGE 2] HARD BLOCK B: M1 RSI {m1_rsi:.1f} > 70, BUY blocked")
            return {
                "passed": False,
                "intermarket_score": score,
                "intermarket_label": label,
                "hard_block": "B",
                "hard_block_reason": f"M1 RSI {m1_rsi:.1f} is overbought — BUY entry unsafe",
                "headwind_detected": False,
                "headwind_reason": "",
                "data": intermarket,
                "error": None,
            }
        
        # HARD BLOCK C: M1 RSI < 30 + SELL (UPGRADE 1B: Modified for oversold depth tracking)
        if direction == "SELL" and m1_rsi is not None:
            # Check if still in active oversold episode (not yet cleared)
            if oversold_depth_m1 is not None:
                # Still in oversold episode - recovery requirement not yet met
                log_debug(
                    f"[STAGE 2] HARD BLOCK C: M1 RSI {m1_rsi:.1f} — active oversold episode from depth {oversold_depth_m1:.1f}, "
                    f"SELL blocked until recovery requirement met"
                )
                return {
                    "passed": False,
                    "intermarket_score": score,
                    "intermarket_label": label,
                    "hard_block": "C",
                    "hard_block_reason": f"M1 RSI {m1_rsi:.1f} in active oversold episode (depth {oversold_depth_m1:.1f}) — SELL blocked until recovery",
                    "headwind_detected": False,
                    "headwind_reason": "",
                    "data": intermarket,
                    "error": None,
                }
            elif m1_rsi < 30:
                # Fresh entry into oversold, not yet tracking
                log_debug(f"[STAGE 2] HARD BLOCK C: M1 RSI {m1_rsi:.1f} < 30, SELL blocked")
                return {
                    "passed": False,
                    "intermarket_score": score,
                    "intermarket_label": label,
                    "hard_block": "C",
                    "hard_block_reason": f"M1 RSI {m1_rsi:.1f} is oversold — SELL entry unsafe",
                    "headwind_detected": False,
                    "headwind_reason": "",
                    "data": intermarket,
                    "error": None,
                }
        
        # HARD BLOCK D: Intermarket score <= -3
        if score <= -3:
            log_debug(f"[STAGE 2] HARD BLOCK D: Intermarket score {score} <= -3")
            return {
                "passed": False,
                "intermarket_score": score,
                "intermarket_label": label,
                "hard_block": "D",
                "hard_block_reason": f"Intermarket alignment {label} (score {score}) opposes all entry signals",
                "headwind_detected": False,
                "headwind_reason": "",
                "data": intermarket,
                "error": None,
            }
        
        # GATE 2 CHECK: Headwind detection (not a block, but reduces confidence)
        headwind_detected = False
        headwind_reason = ""
        
        if score < -2:
            headwind_detected = True
            headwind_reason = f"Intermarket headwind: {label} (score {score}) — confidence penalty applied"
            log_debug(f"[STAGE 2] GATE 2 HEADWIND: {headwind_reason}")
        
        log_debug(f"[STAGE 2] No hard blocks. Intermarket: {label} (score {score})")
        
        return {
            "passed": True,  # No hard blocks triggered
            "intermarket_score": score,
            "intermarket_label": label,
            "hard_block": None,
            "hard_block_reason": "",
            "headwind_detected": headwind_detected,
            "headwind_reason": headwind_reason,
            "data": intermarket,
            "error": None,
        }
    
    except Exception as exc:
        log_debug(f"[STAGE 2] ERROR: {exc}")
        # On error, allow the signal through (don't hard-block)
        return {
            "passed": True,
            "intermarket_score": 0,
            "intermarket_label": "Error - assuming neutral",
            "hard_block": None,
            "hard_block_reason": "",
            "headwind_detected": False,
            "headwind_reason": "",
            "data": {},
            "error": str(exc),
        }
