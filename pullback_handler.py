"""Pullback detection (legacy stub)."""
def detect_pullback_in_progress(direction, tfa, tfi):
    return False, "No pullback"
def check_pullback_reversal_ready(direction, tfi, tfa):
    return True, "Ready"
def apply_pullback_state_to_gates(direction, tfa, tfi, gates):
    return