"""
Pullback Detection & Confirmation Module
=========================================

CRITICAL FIX #4: Pullback confirmation system to prevent entering during active pullbacks.

The system should NOT enter BUY when M5/M1 are pulling back against H4/H1 trend.
Instead, it should:
1. DETECT: H4/H1 bullish + M5/M1 bearish = pullback in progress
2. MEASURE: Expected pullback zone (Daily S1 + ATR depth)
3. WAIT: For pullback completion signal (max 120 cycles = ~2 hours)
4. CONFIRM: M5 RSI > 45 + M1 prints bullish candle = reversal ready
5. EXECUTE: Only then generate BUY signal
6. TIMEOUT: Auto-expire pullback wait after 120 cycles to prevent indefinite locking

Similarly for SELL setups (reverse logic).

ARCHITECTURAL FIX: Added timeout mechanism so pullback gate doesn't wait forever.
"""

import json
from pathlib import Path
from typing import Any
from utils.result_writer import log_debug

PULLBACK_WAIT_STATE_FILE = "pullback_wait_state.json"
PULLBACK_WAIT_TIMEOUT_CYCLES = 120  # ~2 hours at 60-sec cycles

def _f(val: Any) -> float | None:
    """Safe float conversion."""
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _load_pullback_wait_state() -> dict:
    """Load pullback wait state from disk."""
    try:
        if Path(PULLBACK_WAIT_STATE_FILE).exists():
            return json.loads(Path(PULLBACK_WAIT_STATE_FILE).read_text())
    except Exception as e:
        log_debug(f"[PULLBACK TRACKER] Error loading wait state: {e}")
    return {"wait_cycle_count": 0, "wait_direction": None}


def _save_pullback_wait_state(state: dict) -> None:
    """Save pullback wait state to disk."""
    try:
        Path(PULLBACK_WAIT_STATE_FILE).write_text(json.dumps(state, indent=2))
    except Exception as e:
        log_debug(f"[PULLBACK TRACKER] Error saving wait state: {e}")


def check_pullback_wait_timeout(direction: str) -> tuple[bool, str]:
    """
    ARCHITECTURAL FIX: Check if pullback wait has exceeded timeout.
    
    Returns: (should_timeout, reason)
    
    Logic:
    - Track how many cycles have been spent waiting for pullback reversal
    - If direction changed, reset counter
    - If counter exceeds PULLBACK_WAIT_TIMEOUT_CYCLES, force timeout
    """
    state = _load_pullback_wait_state()
    stored_dir = state.get("wait_direction")
    cycle_count = state.get("wait_cycle_count", 0)
    
    # Direction changed - reset counter
    if stored_dir != direction:
        state = {"wait_cycle_count": 0, "wait_direction": direction}
        _save_pullback_wait_state(state)
        return False, ""
    
    # Increment cycle count
    cycle_count += 1
    state["wait_cycle_count"] = cycle_count
    _save_pullback_wait_state(state)
    
    # Check timeout
    if cycle_count > PULLBACK_WAIT_TIMEOUT_CYCLES:
        reason = (
            f"[PULLBACK TIMEOUT] {direction} setup waited {cycle_count} cycles "
            f"(max {PULLBACK_WAIT_TIMEOUT_CYCLES}) — conditions not materializing, auto-expire"
        )
        log_debug(reason)
        return True, reason
    
    return False, ""


def clear_pullback_wait_state() -> None:
    """Clear pullback wait state (called when setup expires or trade executes)."""
    state = {"wait_cycle_count": 0, "wait_direction": None}
    _save_pullback_wait_state(state)


def detect_pullback_in_progress(
    direction: str,
    tfa: dict[str, dict[str, Any]],
    tfi: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    """
    DETECT: Is a pullback currently in progress against the main trend?
    
    For BUY: H4/H1 bullish but M5/M1 bearish = pullback in progress
    For SELL: H4/H1 bearish but M5/M1 bullish = pullback in progress
    
    Returns: (pullback_detected, reason)
    """
    if direction not in {"BUY", "SELL"}:
        return False, ""
    
    h4_dir = tfa.get("H4", {}).get("direction", "NO TRADE")
    h1_dir = tfa.get("H1", {}).get("direction", "NO TRADE")
    m5_dir = tfa.get("M5", {}).get("direction", "NO TRADE")
    m1_dir = tfa.get("M1", {}).get("direction", "NO TRADE")
    
    if direction == "BUY":
        h_bullish = (h4_dir == "BUY") or (h1_dir == "BUY")
        l_bearish = (m5_dir == "SELL") or (m1_dir == "SELL")
        
        if h_bullish and l_bearish:
            m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
            m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
            reason = f"[PULLBACK DETECTED] BUY setup: H4/H1 bullish vs M5/M1 bearish (M5 RSI {m5_rsi:.1f}, M1 RSI {m1_rsi:.1f})"
            log_debug(reason)
            return True, reason
    
    elif direction == "SELL":
        h_bearish = (h4_dir == "SELL") or (h1_dir == "SELL")
        l_bullish = (m5_dir == "BUY") or (m1_dir == "BUY")
        
        if h_bearish and l_bullish:
            m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
            m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
            reason = f"[PULLBACK DETECTED] SELL setup: H4/H1 bearish vs M5/M1 bullish (M5 RSI {m5_rsi:.1f}, M1 RSI {m1_rsi:.1f})"
            log_debug(reason)
            return True, reason
    
    return False, ""


def check_pullback_reversal_ready(
    direction: str,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    """
    CONFIRM: Is pullback complete and reversal ready for entry?
    
    For BUY: M5 RSI > 45 + M1 bullish + price stabilized
    For SELL: M5 RSI < 55 + M1 bearish + price stabilized
    
    Returns: (ready_for_entry, reason)
    """
    if direction not in {"BUY", "SELL"}:
        return False, ""
    
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
    m1_dir = tfa.get("M1", {}).get("direction", "NO TRADE")
    m5_dir = tfa.get("M5", {}).get("direction", "NO TRADE")
    
    if direction == "BUY":
        m5_recovered = m5_rsi is not None and m5_rsi > 45.0
        m1_bullish = m1_dir == "BUY"
        
        if m5_recovered and m1_bullish:
            reason = f"[PULLBACK REVERSAL CONFIRMED] M5 RSI recovered {m5_rsi:.1f} > 45 + M1 bullish — ready for BUY entry"
            log_debug(reason)
            return True, reason
        else:
            reason = f"[PULLBACK WAITING] BUY needs: M5 RSI > 45 (current {m5_rsi:.1f}) AND M1 bullish (current {m1_dir})"
            return False, reason
    
    elif direction == "SELL":
        m5_recovered = m5_rsi is not None and m5_rsi < 55.0
        m1_bearish = m1_dir == "SELL"
        
        if m5_recovered and m1_bearish:
            reason = f"[PULLBACK REVERSAL CONFIRMED] M5 RSI recovered {m5_rsi:.1f} < 55 + M1 bearish — ready for SELL entry"
            log_debug(reason)
            return True, reason
        else:
            reason = f"[PULLBACK WAITING] SELL needs: M5 RSI < 55 (current {m5_rsi:.1f}) AND M1 bearish (current {m1_dir})"
            return False, reason
    
    return False, ""


def calculate_pullback_target_zone(
    direction: str,
    tfi: dict[str, dict[str, Any]],
) -> dict[str, float | None]:
    """
    MEASURE: Expected pullback zone using Daily S1/R1 + M15 ATR depth.
    
    For BUY: Pullback expected to reach Daily S1 + (M15 ATR * 1.5)
    For SELL: Pullback expected to reach Daily R1 - (M15 ATR * 1.5)
    
    Returns: {"target_bottom": price, "target_range": "price_min to price_max"}
    """
    if direction not in {"BUY", "SELL"}:
        return {"target_bottom": None, "target_range": ""}
    
    daily_s1 = _f(tfi.get("D1", {}).get("daily_s1"))
    daily_r1 = _f(tfi.get("D1", {}).get("daily_r1"))
    m15_atr = _f(tfi.get("M15", {}).get("atr_14"))
    
    if m15_atr is None or m15_atr == 0:
        return {"target_bottom": None, "target_range": ""}
    
    depth = m15_atr * 1.5
    
    if direction == "BUY" and daily_s1 is not None:
        target_bottom = daily_s1 + depth
        target_top = daily_s1 + (m15_atr * 2.0)  # Wider range for reference
        log_debug(f"[PULLBACK ZONE] BUY: Expected pullback zone {target_bottom:.2f} to {target_top:.2f} (S1 {daily_s1:.2f} ± ATR depth)")
        return {
            "target_bottom": target_bottom,
            "target_top": target_top,
            "daily_support": daily_s1,
            "depth_measurement": depth,
            "target_range": f"{target_bottom:.2f} - {target_top:.2f}"
        }
    
    elif direction == "SELL" and daily_r1 is not None:
        target_bottom = daily_r1 - (m15_atr * 2.0)
        target_top = daily_r1 - depth
        log_debug(f"[PULLBACK ZONE] SELL: Expected pullback zone {target_bottom:.2f} to {target_top:.2f} (R1 {daily_r1:.2f} ± ATR depth)")
        return {
            "target_bottom": target_bottom,
            "target_top": target_top,
            "daily_resistance": daily_r1,
            "depth_measurement": depth,
            "target_range": f"{target_bottom:.2f} - {target_top:.2f}"
        }
    
    return {"target_bottom": None, "target_range": ""}


def get_pullback_wait_message(
    direction: str,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> str:
    """
    Generate human-readable wait message explaining pullback status.
    """
    if direction not in {"BUY", "SELL"}:
        return ""
    
    is_pullback, pullback_reason = detect_pullback_in_progress(direction, tfa, tfi)
    is_ready, ready_reason = check_pullback_reversal_ready(direction, tfi, tfa)
    pullback_zone = calculate_pullback_target_zone(direction, tfi)
    
    if not is_pullback:
        return ""
    
    if is_ready:
        return f"{ready_reason} | Target zone crossed."
    
    target_range = pullback_zone.get("target_range", "")
    if target_range:
        return f"{pullback_reason} | Wait for pullback to {target_range} and reversal confirmation."
    
    return f"{pullback_reason} | Waiting for pullback completion."


def apply_pullback_state_to_gates(
    direction: str,
    tfa: dict[str, dict[str, Any]],
    tfi: dict[str, dict[str, Any]],
    gates: dict[str, Any],
) -> None:
    """
    UPDATE GATES: Apply pullback detection to trading gates.
    
    This modifies the gates dict to reflect pullback status.
    
    ARCHITECTURAL FIX: Now checks timeout and forces gate exit if exceeded.
    """
    is_pullback, pullback_reason = detect_pullback_in_progress(direction, tfa, tfi)
    is_ready, ready_reason = check_pullback_reversal_ready(direction, tfi, tfa)
    pullback_zone = calculate_pullback_target_zone(direction, tfi)
    
    # ARCHITECTURAL FIX: Check pullback wait timeout
    timeout_exceeded, timeout_reason = check_pullback_wait_timeout(direction)
    if timeout_exceeded:
        log_debug(timeout_reason)
        clear_pullback_wait_state()
        gates["pullback_in_progress"] = False
        gates["pullback_detection_reason"] = ""
        gates["pullback_reversal_ready"] = True
        gates["pullback_ready_reason"] = timeout_reason
        gates["pullback_target_zone"] = ""
        gates["wait_for_confirmation"] = False
        gates["wait_reason"] = ""
        return
    
    gates["pullback_in_progress"] = is_pullback
    gates["pullback_detection_reason"] = pullback_reason
    gates["pullback_reversal_ready"] = is_ready
    gates["pullback_ready_reason"] = ready_reason
    gates["pullback_target_zone"] = pullback_zone.get("target_range", "")
    
    # If pullback in progress but NOT ready, add to wait state
    if is_pullback and not is_ready:
        gates["wait_for_confirmation"] = True
        gates["wait_reason"] = f"Pullback in progress — {ready_reason}"
        gates["wait_trigger"] = f"Execute when: M5 aligns with H4/H1 direction"
        log_debug(f"[PULLBACK GATE] WAIT state activated: {gates['wait_reason']}")
    else:
        gates["wait_for_confirmation"] = False
        clear_pullback_wait_state()
