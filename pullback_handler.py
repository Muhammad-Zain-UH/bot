"""Legacy pullback compatibility helpers.

The live detector now lives in ``pullback_detector.py``. These wrappers keep the
old interface usable without duplicating logic.
"""

from __future__ import annotations

from typing import Any

from pullback_detector import get_m15_pullback


def _get_m15_raw_data(tfi: dict[str, Any] | None) -> Any:
    if not isinstance(tfi, dict):
        return None
    m15 = tfi.get("M15", {})
    if isinstance(m15, dict):
        return m15.get("raw_data")
    return None


def detect_pullback_in_progress(direction, tfa, tfi):
    m15_data = _get_m15_raw_data(tfi)
    if m15_data is None:
        return False, "No M15 raw data"

    result = get_m15_pullback(m15_data, direction)
    in_progress = bool(result.get("pullback_in_progress")) or (
        not result.get("pullback_detected", False) and result.get("pullback_quality", 0.0) >= 3.0
    )
    return in_progress, result.get("reasoning", "No pullback")


def check_pullback_reversal_ready(direction, tfi, tfa):
    m15_data = _get_m15_raw_data(tfi)
    if m15_data is None:
        return False, "No M15 raw data"

    result = get_m15_pullback(m15_data, direction)
    return bool(result.get("pullback_detected", False) and result.get("pullback_quality", 0.0) >= 5.0), result.get(
        "reasoning",
        "No pullback",
    )


def apply_pullback_state_to_gates(direction, tfa, tfi, gates):
    if not isinstance(gates, dict):
        return

    m15_data = _get_m15_raw_data(tfi)
    if m15_data is None:
        gates["pullback_in_progress"] = False
        gates["pullback_reversal_ready"] = False
        gates["pullback_reason"] = "No M15 raw data"
        return

    result = get_m15_pullback(m15_data, direction)
    gates["pullback_in_progress"] = bool(result.get("pullback_in_progress"))
    gates["pullback_reversal_ready"] = bool(result.get("pullback_detected", False) and result.get("pullback_quality", 0.0) >= 5.0)
    gates["pullback_reason"] = result.get("reasoning", "No pullback")
