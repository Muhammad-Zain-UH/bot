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
) -> str:
    """Format a single-line monitor status for WAIT states.
    
    Format:
    [MONITOR HH:MM:SS] BUY | Score: 5.95/12.5 | Conf: 33% (need 49%) | 
    H4: Strong Bull | M1 RSI: 68.6 | Gap: -16% | Next check: 60s | result.txt: NONE
    """
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%H:%M:%S")
    
    score_str = f"{score:.2f}"
    max_str = f"{required_score:.2f}"
    score_bar = f"{score_str}/{max_str}"
    
    conf_gap = required_confidence - confidence
    conf_gap_pct = (conf_gap / required_confidence * 100) if required_confidence > 0 else 0
    
    rsi_str = f"{m1_rsi:.1f}" if m1_rsi is not None else "N/A"
    
    result_status = "ACTIVE" if result_txt_active else "NONE"
    
    line = (
        f"[MONITOR {time_str}] {direction} | "
        f"Score: {score_bar} | "
        f"Conf: {confidence}% (need {required_confidence}%) | "
        f"H4: {h4_trend} | "
        f"M1 RSI: {rsi_str} | "
        f"Gap: {conf_gap_pct:.0f}% | "
        f"Next: {next_sleep_secs}s | "
        f"result.txt: {result_status}"
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
