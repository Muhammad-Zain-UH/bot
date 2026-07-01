"""LAYER 7: CONFIDENCE SCORE ENGINE - Explicit 5-component formula (0-100).

CONFIDENCE SCORING FORMULA for XAUUSD:

Final Score = 
  (Bias strength × 0.25) +              # 25%: How strong is H4 trend?
  (Structure confidence × 0.20) +       # 20%: Is H1 structure intact?
  (Sweep quality × 0.20) +              # 20%: Clean sweep?
  (POI score × 0.20) +                  # 20%: Quality entry zone?
  (Session bonus × 0.10)                # 10%: London/NY = +5, else 0
  + Additional bonuses
  ─────────────────────────────────────
  = Final Score (0-100 max)

SETUP GRADE ASSIGNMENT:

85-100:  A+ Grade (1.5% risk, best entries)
70-84:   A Grade (1.0% risk, good entries)
<70:     REJECT (skip this setup)

A+ GRADE CHECKLIST (must have 6+):
- [ ] Bias strength ≥ 8/10
- [ ] H1 structure valid & intact
- [ ] Sweep quality ≥ 8/10
- [ ] POI score ≥ 80
- [ ] Fib confluence
- [ ] Session is London or NY
- [ ] RSI not overbought/oversold
- [ ] No conflicting HTF signals
"""

from __future__ import annotations
from typing import Any
import pandas as pd
from fibonacci_levels import calculate_fibonacci_levels, find_swing_high_low
from utils import log_debug


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_session_adjustment(session: str) -> tuple[float, str]:
    """Return session-based score adjustment and label.
    
    FIX #5 (PHASE 4): Remove Asian penalty. Asian-range sweeps are valid setups.
    All tier 2 sessions (Asian, Euro) now neutral (0) instead of -5.
    """
    session_name = session.upper()
    if session_name in ["LONDON", "NEWYORK"]:
        return 8.0, f"{session} (Tier 1)"
    if session_name == "ASIAN":
        return 0.0, f"{session} (Tier 2, neutral - no penalty)"
    if session_name == "DEAD":
        return -15.0, f"{session} (Tier 3 penalty)"
    return 0.0, "OTHER (Neutral)"


def evaluate_poi_fib_confluence(
    h1_data: pd.DataFrame | None,
    poi_top: float | None,
    poi_bottom: float | None,
    direction: str,
    tolerance_pips: float = 2.0,
) -> dict[str, Any]:
    """Check whether the POI aligns with the 0.5 or 0.618 fib levels of the last H1 impulse."""
    try:
        if h1_data is None or len(h1_data) < 5:
            return {
                "has_fib_confluence": False,
                "matched_levels": [],
                "fib_levels": {},
                "reasoning": "Insufficient H1 data",
            }

        poi_top_val = _to_float(poi_top)
        poi_bottom_val = _to_float(poi_bottom)
        if poi_top_val is None or poi_bottom_val is None:
            return {
                "has_fib_confluence": False,
                "matched_levels": [],
                "fib_levels": {},
                "reasoning": "Missing POI bounds",
            }

        swing_high, swing_low, _, _ = find_swing_high_low(h1_data, lookback=min(50, len(h1_data)))
        swing_high_val = _to_float(swing_high)
        swing_low_val = _to_float(swing_low)
        if swing_high_val is None or swing_low_val is None or swing_high_val <= swing_low_val:
            return {
                "has_fib_confluence": False,
                "matched_levels": [],
                "fib_levels": {},
                "reasoning": "Invalid H1 swing range",
            }

        fib_levels = calculate_fibonacci_levels(swing_high_val, swing_low_val, direction)
        zone_top = max(poi_top_val, poi_bottom_val)
        zone_bottom = min(poi_top_val, poi_bottom_val)
        zone_mid = (zone_top + zone_bottom) / 2.0

        matched_levels: list[dict[str, Any]] = []
        for level_name in ("0.500", "0.618"):
            level_price = fib_levels.get(level_name)
            if level_price is None:
                continue

            within_zone = zone_bottom - tolerance_pips <= level_price <= zone_top + tolerance_pips
            near_mid = abs(zone_mid - level_price) <= tolerance_pips
            if within_zone or near_mid:
                matched_levels.append({
                    "level": level_name,
                    "price": level_price,
                    "distance": min(abs(level_price - zone_bottom), abs(level_price - zone_top), abs(level_price - zone_mid)),
                })

        return {
            "has_fib_confluence": bool(matched_levels),
            "matched_levels": matched_levels,
            "fib_levels": fib_levels,
            "swing_high": swing_high_val,
            "swing_low": swing_low_val,
            "reasoning": "Fib confluence confirmed" if matched_levels else "POI not near 0.5/0.618 fib levels",
        }

    except Exception as exc:
        log_debug(f"Fib confluence evaluation error: {exc}")
        return {
            "has_fib_confluence": False,
            "matched_levels": [],
            "fib_levels": {},
            "reasoning": f"Error: {str(exc)}",
        }


def calculate_confidence_score(
    bias_strength: float,
    structure_confidence: float,
    sweep_quality: float,
    poi_score: float,
    session: str = "OTHER",
) -> dict[str, Any]:
    """
    Calculate final confidence score from component inputs.
    
    FIX #5 (PHASE 4): WEIGHTED FORMULA CORRECTION
    
    Args:
        bias_strength: 0-10
        structure_confidence: 0-10
        sweep_quality: 0-10
        poi_score: 0-100
        session: "LONDON", "NEWYORK", "ASIAN", "DEAD", "OTHER"
    
    Returns:
        {
            "final_score": 0-100,
            "grade": "A+ | A | REJECT",
            "confidence_breakdown": {
                "bias_component": float,
                "structure_component": float,
                "sweep_component": float,
                "poi_component": float,
                "cohesion_component": float,
                "session_bonus": float,
            },
            "reasoning": str,
        }
    """
    try:
        # Normalize inputs
        bias_norm = min(10.0, max(0.0, _to_float(bias_strength) or 0.0)) / 10.0 * 100
        structure_norm = min(10.0, max(0.0, _to_float(structure_confidence) or 0.0)) / 10.0 * 100
        sweep_norm = min(10.0, max(0.0, _to_float(sweep_quality) or 0.0)) / 10.0 * 100
        poi_norm = min(100, max(0, _to_float(poi_score) or 0))
        
        # FIX #5: Component scores now sum to exactly 1.0
        bias_component = bias_norm * 0.24  # 24% (was 25%)
        structure_component = structure_norm * 0.20  # 20%
        sweep_component = sweep_norm * 0.20  # 20%
        poi_component = poi_norm * 0.20  # 20%
        
        # NEW: Fifth component - "Setup Cohesion"
        # Measures how well all signals align (no conflicting signals)
        # Bonus if 3+ components are strong (≥70%)
        strong_components = sum([
            bias_norm >= 70,
            structure_norm >= 70,
            sweep_norm >= 70,
            poi_norm >= 70,
        ])
        cohesion_component = min(16.0, strong_components * 4.0)  # 16% max, 4% per strong signal
        
        # Session adjustment: reward prime sessions, penalize low-liquidity ones.
        session_bonus, _ = _get_session_adjustment(session)
        
        # Final score (now sums properly)
        final_score = (
            bias_component +
            structure_component +
            sweep_component +
            poi_component +
            cohesion_component +
            session_bonus
        )
        
        # Grade
        if final_score >= 85:
            grade = "A+"
        elif final_score >= 70:
            grade = "A"
        else:
            grade = "REJECT"
        
        # Reasoning
        reasoning_parts = [
            f"Bias {bias_norm:.0f}% (×0.24={bias_component:.1f})",
            f"Structure {structure_norm:.0f}% (×0.20={structure_component:.1f})",
            f"Sweep {sweep_norm:.0f}% (×0.20={sweep_component:.1f})",
            f"POI {poi_norm:.0f}% (×0.20={poi_component:.1f})",
            f"Cohesion {strong_components} signals (={cohesion_component:.1f})",
            f"Session adjustment {session_bonus:+.1f}",
        ]
        
        return {
            "final_score": max(0.0, min(100.0, final_score)),
            "grade": grade,
            "confidence_breakdown": {
                "bias_component": bias_component,
                "structure_component": structure_component,
                "sweep_component": sweep_component,
                "poi_component": poi_component,
                "cohesion_component": cohesion_component,
                "session_bonus": session_bonus,
            },
            "reasoning": " | ".join(reasoning_parts),
        }
    
    except Exception as exc:
        log_debug(f"Confidence score calculation error: {exc}")
        return {
            "final_score": 0.0,
            "grade": "REJECT",
            "confidence_breakdown": {
                "bias_component": 0.0,
                "structure_component": 0.0,
                "sweep_component": 0.0,
                "poi_component": 0.0,
                "cohesion_component": 0.0,
                "session_bonus": 0.0,
            },
            "reasoning": f"Error: {str(exc)}",
        }


def check_a_plus_checklist(
    bias_strength: float,
    structure_valid: bool,
    sweep_quality: float,
    poi_score: float,
    has_fib_confluence: bool,
    session: str,
    rsi_value: float | None = None,
) -> dict[str, Any]:
    """
    Verify A+ grade setup requirements.
    
    A+ Checklist (must pass 6+ checks):
    - [ ] Bias strength ≥ 8/10
    - [ ] H1 structure valid & intact
    - [ ] Sweep quality ≥ 8/10
    - [ ] POI score ≥ 80
    - [ ] Fib confluence (0.5 or 0.618)
    - [ ] Session is London or NY
    - [ ] RSI not overbought (< 70 in BUY) or oversold (> 30 in SELL)
    
    Returns:
        {
            "checks_passed": int,  # 0-7
            "checks_list": [
                {"check": str, "passed": bool},
                ...
            ],
            "qualifies_for_a_plus": bool,
        }
    """
    try:
        checks = []
        passes = 0
        
        # Check 1: Bias strength ≥ 8/10
        bias_ok = (_to_float(bias_strength) or 0) >= 8.0
        checks.append({"check": "Bias strength ≥ 8/10", "passed": bias_ok})
        if bias_ok:
            passes += 1
        
        # Check 2: Structure valid
        checks.append({"check": "H1 structure valid", "passed": structure_valid})
        if structure_valid:
            passes += 1
        
        # Check 3: Sweep quality ≥ 8/10
        sweep_ok = (_to_float(sweep_quality) or 0) >= 8.0
        checks.append({"check": "Sweep quality ≥ 8/10", "passed": sweep_ok})
        if sweep_ok:
            passes += 1
        
        # Check 4: POI score ≥ 80
        poi_ok = (_to_float(poi_score) or 0) >= 80
        checks.append({"check": "POI score ≥ 80", "passed": poi_ok})
        if poi_ok:
            passes += 1
        
        # Check 5: Fib confluence
        checks.append({"check": "Fibonacci confluence", "passed": has_fib_confluence})
        if has_fib_confluence:
            passes += 1
        
        # Check 6: Session is London or NY
        session_ok = session.upper() in ["LONDON", "NEWYORK"]
        checks.append({"check": "Session: London or NY", "passed": session_ok})
        if session_ok:
            passes += 1
        
        # Check 7: RSI not extreme (optional, if provided)
        if rsi_value is not None:
            rsi_ok = 35 <= rsi_value <= 65  # Neutral zone
            checks.append({"check": "RSI neutral (35-65)", "passed": rsi_ok})
            if rsi_ok:
                passes += 1
        
        qualifies = passes >= 6
        
        return {
            "checks_passed": passes,
            "checks_list": checks,
            "qualifies_for_a_plus": qualifies,
        }
    
    except Exception as exc:
        log_debug(f"A+ checklist error: {exc}")
        return {
            "checks_passed": 0,
            "checks_list": [{"check": "error", "passed": False}],
            "qualifies_for_a_plus": False,
        }


def get_confidence_engine(
    bias_strength: float,
    structure_confidence: float,
    sweep_quality: float,
    poi_score: float,
    session: str = "OTHER",
    structure_valid: bool = False,
    has_fib_confluence: bool = False,
    rsi_value: float | None = None,
) -> dict[str, Any]:
    """
    Complete confidence scoring with A+ checklist.
    
    Returns:
        {
            "final_score": 0-100,
            "grade": "A+ | A | REJECT",
            "confidence_breakdown": {...},
            "reasoning": str,
            "a_plus_checklist": {
                "checks_passed": int,
                "qualifies": bool,
            },
            "recommendation": str,
        }
    """
    # Calculate score
    score_result = calculate_confidence_score(
        bias_strength,
        structure_confidence,
        sweep_quality,
        poi_score,
        session,
    )
    
    # Check A+ qualifications
    checklist_result = check_a_plus_checklist(
        bias_strength,
        structure_valid,
        sweep_quality,
        poi_score,
        has_fib_confluence,
        session,
        rsi_value,
    )
    
    # Final recommendation
    if score_result["grade"] == "A+" and checklist_result["qualifies_for_a_plus"]:
        recommendation = "STRONG BUY (A+ grade, 1.5% risk)"
    elif score_result["grade"] == "A":
        recommendation = "BUY WITH CAUTION (A grade, 1.0% risk)"
    else:
        recommendation = "REJECT (below 70)"
    
    return {
        "final_score": score_result["final_score"],
        "grade": score_result["grade"],
        "confidence_breakdown": score_result["confidence_breakdown"],
        "reasoning": score_result["reasoning"],
        "a_plus_checklist": {
            "checks_passed": checklist_result["checks_passed"],
            "checks_list": checklist_result["checks_list"],
            "qualifies": checklist_result["qualifies_for_a_plus"],
        },
        "recommendation": recommendation,
    }
