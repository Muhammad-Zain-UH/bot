"""Console output formatting for monitoring loop."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def format_monitor_status_line(
    direction: str,
    score: float,
    required_score: float,
    confidence: int,
    required_confidence: int,
    h4_trend: str,
    m1_rsi: float | None,
    next_sleep_secs: int,
    result_txt_active: bool = False,
    h1_recovery_watch: bool = False,
    h4_recovery_watch: bool = False,
    buy_score: float = 0,
    sell_score: float = 0,
    blocking_reason: str = "",
    rsi_bounce_detected: bool = False,
) -> str:
    """Format a single-line monitor status for WAIT states.
    
    Now shows dominant side score (buy or sell) against threshold, with net score in brackets.
    
    Format:
    [MONITOR HH:MM:SS] SELL | SellScore: 7.72 / threshold: 3.60 — ABOVE ✓ | Net: -4.49 | 
    Conf: 44% (need 48%) | H4: Weak Bull | M1 RSI: 68.6 | Next: 60s | result.txt: NONE
    """
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%H:%M:%S")
    
    # Special handling for NO TRADE (score too close to zero)
    if direction == "NO TRADE":
        # Show BUY vs SELL score comparison without implying a direction
        if buy_score != 0 or sell_score != 0:
            score_detail = f"BUYScore: {buy_score:.2f} vs SELLScore: {sell_score:.2f}"
        else:
            score_detail = f"Scores: {buy_score:.2f} vs {sell_score:.2f}"
        
        net_display = f"NET: {score:.2f} (no conviction)"
        conf_display = f"Conf: {confidence}% (need {required_confidence}%)"
        rsi_str = f"{m1_rsi:.1f}" if m1_rsi is not None else "N/A"
        result_status = "ACTIVE" if result_txt_active else "NONE"
        
        recovery_tags = []
        if h1_recovery_watch:
            recovery_tags.append("H1: ⚠ RECOVERY WATCH")
        if h4_recovery_watch:
            recovery_tags.append("H4: ⚠ RECOVERY WATCH")
        if rsi_bounce_detected:
            recovery_tags.append("M1: ⚠ RSI BOUNCE")
        recovery_str = " | " + " | ".join(recovery_tags) if recovery_tags else ""
        
        line = (
            f"[MONITOR {time_str}] NO TRADE | {score_detail} | {net_display} | "
            f"{conf_display} | "
            f"H4: {h4_trend} | "
            f"M1 RSI: {rsi_str} | "
            f"Next: {next_sleep_secs}s | "
            f"result.txt: {result_status}"
            f"{recovery_str}"
        )
        return line
    
    # Normal handling for BUY/SELL/WAIT directions
    # Determine dominant side score — use actual score components as primary indicator
    # Always show whichever of buy_score or sell_score is larger, regardless of net score sign
    # This prevents showing SELL when buy_score is actually higher
    if buy_score > sell_score:
        dominant_side = "BUY"
        dominant_score = buy_score
    elif sell_score > buy_score:
        dominant_side = "SELL"
        dominant_score = sell_score
    else:
        # If equal, use net score sign as tiebreaker
        dominant_side = "SELL" if score < 0 else "BUY"
        dominant_score = max(buy_score, sell_score)
    
    # Compare dominant score to threshold
    score_comparison = "ABOVE ✓" if dominant_score >= required_score else "BELOW"
    score_side_str = f"{dominant_side}Score"
    dominant_display = f"{dominant_side} | {score_side_str}: {dominant_score:.2f} / threshold: {required_score:.2f} — {score_comparison}"
    
    # Show net score in brackets
    net_display = f"Net: {score:.2f}"
    
    # Confidence display with blocking reason if applicable
    if blocking_reason:
        conf_display = f"Conf: {confidence}% (need {required_confidence}%) — BLOCKED: {blocking_reason}"
    else:
        conf_display = f"Conf: {confidence}% (need {required_confidence}%)"
    
    rsi_str = f"{m1_rsi:.1f}" if m1_rsi is not None else "N/A"
    
    result_status = "ACTIVE" if result_txt_active else "NONE"
    
    # Build recovery watch tags and RSI bounce indicator
    recovery_tags = []
    if h1_recovery_watch:
        recovery_tags.append("H1: ⚠ RECOVERY WATCH")
    if h4_recovery_watch:
        recovery_tags.append("H4: ⚠ RECOVERY WATCH")
    if rsi_bounce_detected:
        recovery_tags.append("M1: ⚠ RSI BOUNCE")
    recovery_str = " | " + " | ".join(recovery_tags) if recovery_tags else ""
    
    line = (
        f"[MONITOR {time_str}] {dominant_display} | {net_display} | "
        f"{conf_display} | "
        f"H4: {h4_trend} | "
        f"M1 RSI: {rsi_str} | "
        f"Next: {next_sleep_secs}s | "
        f"result.txt: {result_status}"
        f"{recovery_str}"
    )
    return line


def format_gate_result(
    stage: int,
    passed: bool,
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> str:
    """Format a gate result message for console output."""
    status = "PASS" if passed else "BLOCK"
    prefix = f"[GATE {stage}]"
    
    if not reason:
        reason = "Conditions passed" if passed else "Conditions blocked entry"
    
    line = f"{prefix} {status}: {reason}"
    
    if details:
        for key, value in details.items():
            if value is not None:
                line += f" | {key}={value}"
    
    return line


def format_hard_block(
    block_name: str,
    condition: str,
    sleep_secs: int,
) -> str:
    """Format a hard block message."""
    return f"[HARD BLOCK] {block_name}: {condition} → sleep {sleep_secs}s"


def format_stage_header(stage: int, name: str) -> str:
    """Format a stage header for console output."""
    return f"\n[STAGE {stage} - {name.upper()}]"


def format_execute_header(direction: str, confidence: int) -> str:
    """Format execution message."""
    return f"\n[EXECUTE] {direction} | Confidence: {confidence}% | Placing trade..."


def format_cooldown(secs: int) -> str:
    """Format post-trade cooldown message."""
    return f"\n[COOLDOWN] Post-trade sleep {secs}s"


def format_error(exc_type: str, message: str, sleep_secs: int) -> str:
    """Format error message during monitoring."""
    return f"[ERROR] {exc_type}: {message} → sleep {sleep_secs}s, continue"


def format_ai_response(confirmed: bool, confidence_adjustment: int, reason: str) -> str:
    """Format AI verification response."""
    status = "CONFIRMED" if confirmed else "REJECTED"
    return f"[AI] {status} | Adjustment: {confidence_adjustment:+d}% | {reason}"
