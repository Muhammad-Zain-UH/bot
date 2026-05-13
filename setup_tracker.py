"""
Setup Expiry & Bias Tracking System
====================================

ARCHITECTURAL FIX: Prevents setup bias lock where system pursues same direction for hours.

Key Functions:
1. Track when BUY/SELL setup first detected
2. Expire setups after 60-120 minutes
3. Auto-clear when supporting conditions deteriorate
4. Reset daily at session start
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from utils import log_debug


SETUP_STATE_FILE = "setup_state.json"
SETUP_TIMEOUT_MINUTES = 90  # Max lifetime for a setup
CONDITION_DETERIORATION_THRESHOLD = 0.20  # If supporting conditions drop 20%, expire setup


def _load_setup_state() -> dict:
    """Load setup state from disk."""
    try:
        if Path(SETUP_STATE_FILE).exists():
            return json.loads(Path(SETUP_STATE_FILE).read_text())
    except Exception as e:
        log_debug(f"[SETUP TRACKER] Error loading state: {e}")
    return {
        "active_setup": None,
        "setup_direction": None,
        "setup_start_time": None,
        "setup_start_score": None,
        "setup_start_h4_strength": None,
        "session_date": None,
    }


def _save_setup_state(state: dict) -> None:
    """Save setup state to disk."""
    try:
        Path(SETUP_STATE_FILE).write_text(json.dumps(state, indent=2, default=str))
    except Exception as e:
        log_debug(f"[SETUP TRACKER] Error saving state: {e}")


def reset_daily_bias(current_date: str) -> None:
    """
    Called at session start with current date.
    Clears any stale setup bias from previous session.
    """
    state = _load_setup_state()
    stored_date = state.get("session_date")
    
    if stored_date != current_date:
        log_debug(f"[SESSION CHANGE] Resetting setup bias: {stored_date} → {current_date}")
        state = {
            "active_setup": None,
            "setup_direction": None,
            "setup_start_time": None,
            "setup_start_score": None,
            "setup_start_h4_strength": None,
            "session_date": current_date,
        }
        _save_setup_state(state)


def register_setup(
    direction: str,
    score: float,
    h4_strength: float,
    current_date: str,
) -> None:
    """
    Register a new BUY/SELL setup.
    
    Args:
        direction: "BUY" or "SELL"
        score: Initial score when setup detected
        h4_strength: H4 trend strength % (0-100)
        current_date: ISO format date
    """
    now = datetime.now(timezone.utc)
    
    state = _load_setup_state()
    
    # Only register if different from current setup (avoid spam)
    if state.get("setup_direction") != direction:
        log_debug(
            f"[SETUP REGISTERED] {direction} setup detected. "
            f"Score={score:.2f}, H4_strength={h4_strength:.1f}% — "
            f"Will expire at {(now + timedelta(minutes=SETUP_TIMEOUT_MINUTES)).isoformat()}"
        )
        state = {
            "active_setup": direction,
            "setup_direction": direction,
            "setup_start_time": now.isoformat(),
            "setup_start_score": score,
            "setup_start_h4_strength": h4_strength,
            "session_date": current_date,
        }
        _save_setup_state(state)


def check_setup_expiry(
    current_score: float,
    current_h4_strength: float,
) -> Tuple[bool, str]:
    """
    Check if active setup should expire.
    
    Returns: (should_expire, reason)
    
    Expiry triggers:
    1. Timeout: Setup older than SETUP_TIMEOUT_MINUTES
    2. Condition deterioration: Supporting score/H4 strength dropped >20%
    3. H4 structure change: H4 flipped direction significantly
    """
    state = _load_setup_state()
    
    if not state.get("setup_direction"):
        return False, ""  # No active setup
    
    setup_dir = state["setup_direction"]
    setup_time_str = state.get("setup_start_time")
    setup_score = state.get("setup_start_score", current_score)
    setup_h4_strength = state.get("setup_start_h4_strength", current_h4_strength)
    
    if not setup_time_str:
        return False, ""
    
    now = datetime.now(timezone.utc)
    setup_time = datetime.fromisoformat(setup_time_str.replace('Z', '+00:00'))
    age_minutes = (now - setup_time).total_seconds() / 60
    
    # CHECK 1: Timeout
    if age_minutes > SETUP_TIMEOUT_MINUTES:
        reason = f"[SETUP EXPIRED] {setup_dir} setup older than {SETUP_TIMEOUT_MINUTES}min (age: {age_minutes:.0f}min)"
        log_debug(reason)
        return True, reason
    
    # CHECK 2: Score deterioration
    # If setup was strong (score > 3.0) but now weak (score < 1.0), expire
    if setup_score > 3.0 and current_score < 1.0:
        deterioration = (setup_score - current_score) / max(setup_score, 0.1)
        if deterioration > CONDITION_DETERIORATION_THRESHOLD:
            reason = (
                f"[SETUP EXPIRED] {setup_dir} setup score collapsed: "
                f"{setup_score:.2f} → {current_score:.2f} ({deterioration*100:.0f}% deterioration)"
            )
            log_debug(reason)
            return True, reason
    
    # CHECK 3: H4 strength reversal
    # If H4 was supporting setup but now opposes it significantly, expire
    if setup_h4_strength > 60 and current_h4_strength < 30:
        reason = (
            f"[SETUP EXPIRED] {setup_dir} setup: H4 strength reversed "
            f"{setup_h4_strength:.1f}% → {current_h4_strength:.1f}% "
            f"(structure changed)"
        )
        log_debug(reason)
        return True, reason
    
    return False, ""


def get_active_setup() -> Optional[str]:
    """
    Get current active setup direction.
    Returns: "BUY", "SELL", or None
    """
    state = _load_setup_state()
    return state.get("setup_direction")


def clear_setup() -> None:
    """Manually clear the active setup."""
    state = _load_setup_state()
    if state.get("setup_direction"):
        old_dir = state["setup_direction"]
        log_debug(f"[SETUP CLEARED] {old_dir} setup cleared manually")
    state["active_setup"] = None
    state["setup_direction"] = None
    state["setup_start_time"] = None
    state["setup_start_score"] = None
    state["setup_start_h4_strength"] = None
    _save_setup_state(state)
