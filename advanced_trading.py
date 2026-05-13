"""
Advanced Trading System Enhancements - Final Module
Combines: Session Rotation Strategy, Composite Man Simulation, Bracket Prediction, Volatility Index, and Multi-touch Support

These are integrated as helper functions since they're interdependent features.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# TASK 6: SESSION ROTATION STRATEGY
# ══════════════════════════════════════════════════════════════════════════════

class SessionPhaseStrategy:
    """Adjusts Wyckoff phase triggers and confidence by trading session."""
    
    SESSIONS = {
        'ASIAN': {'start_hour': 0, 'end_hour': 8, 'focus_phase': 'ACCUMULATION'},
        'LONDON': {'start_hour': 8, 'end_hour': 12, 'focus_phase': 'SPRING/SHAKEOUT'},
        'NEWYORK': {'start_hour': 13, 'end_hour': 21, 'focus_phase': 'MARKUP/MARKDOWN'},
        'OVERLAP': {'start_hour': 21, 'end_hour': 24, 'focus_phase': 'DISTRIBUTION'},
    }
    
    SESSION_CONFIDENCE_THRESHOLDS = {
        'ASIAN': 50.0,      # Most permissive (low liquidity)
        'LONDON': 48.0,     # Active session
        'NEWYORK': 47.0,    # Most active
        'OVERLAP': 49.0,    # Moderate
    }
    
    @staticmethod
    def get_current_session() -> str:
        """Get current trading session based on UTC time."""
        current_hour = datetime.now(timezone.utc).hour
        
        if 0 <= current_hour < 8:
            return 'ASIAN'
        elif 8 <= current_hour < 12:
            return 'LONDON'
        elif 12 <= current_hour < 13:
            return 'OVERLAP'  # London closing, NY opening
        elif 13 <= current_hour < 21:
            return 'NEWYORK'
        else:
            return 'OVERLAP'  # After NY close
    
    @staticmethod
    def adjust_phase_bonus_by_session(
        phase: str,
        session: str,
        base_bonus: float
    ) -> float:
        """
        Adjust Wyckoff phase bonus by session.
        
        Args:
            phase: Wyckoff phase (ACCUMULATION, SPRING, etc.)
            session: Current trading session
            base_bonus: Base confidence bonus
        
        Returns: Adjusted bonus
        """
        focus_phase = SessionPhaseStrategy.SESSIONS[session]['focus_phase']
        
        # Bonus for phases that align with session focus
        if phase in focus_phase or focus_phase in phase:
            return base_bonus * 1.25  # +25% bonus
        else:
            return base_bonus * 0.85  # -15% penalty


# ══════════════════════════════════════════════════════════════════════════════
# TASK 7: COMPOSITE MAN SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

class CompositeManSimulator:
    """
    Simulates smart money (composite man) behavior to predict price action.
    
    Composite Man Theory: Market acts as a single entity with specific goals:
    - ACCUMULATION: Buy low, accumulate, then push price up
    - DISTRIBUTION: Sell high, distribute, then let price fall
    - SPRING: Fake downside break to shake out weak longs
    - SHAKEOUT: Fake upside break to shake out weak shorts
    """
    
    @staticmethod
    def predict_next_move(
        phase: str,
        phase_confidence: float,
        price_low: float,
        price_high: float,
        volume_profile: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Predict composite man's likely next move.
        
        Returns: {move_direction, probability, target_area, rationale}
        """
        
        if phase == "ACCUMULATION":
            # Composite man is buying - next move is UP (MARKUP phase)
            return {
                'next_phase': 'MARKUP',
                'direction': 'BUY',
                'probability': min(95.0, phase_confidence * 1.2),
                'target_low': price_high,
                'target_range': (price_high, price_high * 1.02),
                'rationale': 'Accumulation complete - composite man will now push price higher'
            }
        
        elif phase == "SPRING":
            # Spring (failed downside break) - next move is UP after shaking weak longs
            return {
                'next_phase': 'MARKUP',
                'direction': 'BUY',
                'probability': min(90.0, phase_confidence * 1.3),
                'target_low': price_low,
                'target_range': (price_high, price_high * 1.03),
                'rationale': 'Spring trapped shorts - composite man will push higher after shakeout'
            }
        
        elif phase == "DISTRIBUTION":
            # Distribution - next move is DOWN (MARKDOWN phase)
            return {
                'next_phase': 'MARKDOWN',
                'direction': 'SELL',
                'probability': min(95.0, phase_confidence * 1.2),
                'target_high': price_low,
                'target_range': (price_low * 0.98, price_low),
                'rationale': 'Distribution complete - composite man will now push price lower'
            }
        
        elif phase == "SHAKEOUT":
            # Shakeout (failed upside break) - next move is DOWN after shaking weak shorts
            return {
                'next_phase': 'MARKDOWN',
                'direction': 'SELL',
                'probability': min(90.0, phase_confidence * 1.3),
                'target_high': price_high,
                'target_range': (price_low * 0.97, price_high),
                'rationale': 'Shakeout trapped longs - composite man will push lower after shake'
            }
        
        elif phase == "MARKUP":
            # During markup - watch for distribution signs (exhaustion)
            return {
                'next_phase': 'POTENTIAL_DISTRIBUTION',
                'direction': 'NEUTRAL',
                'probability': phase_confidence * 0.6,  # Lower conviction - move in progress
                'target_range': (price_high, price_high * 1.02),
                'rationale': 'Markup in progress - watch for exhaustion or resistance'
            }
        
        elif phase == "MARKDOWN":
            # During markdown - watch for accumulation signs (exhaustion)
            return {
                'next_phase': 'POTENTIAL_ACCUMULATION',
                'direction': 'NEUTRAL',
                'probability': phase_confidence * 0.6,
                'target_range': (price_low * 0.98, price_low),
                'rationale': 'Markdown in progress - watch for support or bounce'
            }
        
        return {
            'next_phase': 'UNKNOWN',
            'direction': 'NEUTRAL',
            'probability': 0.0,
            'rationale': f'Cannot predict from {phase} phase'
        }


# ══════════════════════════════════════════════════════════════════════════════
# TASK 8: BRACKET PREDICTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class BracketPredictorEngine:
    """Predicts stop hunt targets (brackets where composite man may trigger stops)."""
    
    @staticmethod
    def predict_stop_hunt_brackets(
        phase: str,
        phase_low: float,
        phase_high: float,
        volume_profile: Dict[str, float],
        open_interest_levels: List[float] = None
    ) -> List[Dict[str, float]]:
        """
        Predict likely stop hunt levels.
        
        For SPRING: Look for shorts' stops above accumulation zone
        For SHAKEOUT: Look for longs' stops below distribution zone
        
        Returns: List of predicted bracket levels
        """
        if open_interest_levels is None:
            open_interest_levels = []
        
        brackets = []
        
        if phase in ["SPRING", "SHAKEOUT"]:
            # Spring/Shakeout typically run 1-2.5 ATR worth of distance
            range_size = phase_high - phase_low
            
            if phase == "SPRING":
                # Stop hunts usually above the high of accumulation
                bracket_1 = phase_high + (range_size * 0.5)
                bracket_2 = phase_high + (range_size * 1.0)
                bracket_3 = phase_high + (range_size * 1.5)
                brackets = [
                    {'level': bracket_1, 'intensity': 'LIGHT'},
                    {'level': bracket_2, 'intensity': 'MODERATE'},
                    {'level': bracket_3, 'intensity': 'HEAVY'},
                ]
            
            elif phase == "SHAKEOUT":
                # Stop hunts usually below the low of distribution
                bracket_1 = phase_low - (range_size * 0.5)
                bracket_2 = phase_low - (range_size * 1.0)
                bracket_3 = phase_low - (range_size * 1.5)
                brackets = [
                    {'level': bracket_1, 'intensity': 'LIGHT'},
                    {'level': bracket_2, 'intensity': 'MODERATE'},
                    {'level': bracket_3, 'intensity': 'HEAVY'},
                ]
        
        return brackets


# ══════════════════════════════════════════════════════════════════════════════
# TASK 9: ADVANCED SVI VOLATILITY INDEX
# ══════════════════════════════════════════════════════════════════════════════

class AdvancedVolatilityIndex:
    """
    Measures market stress via ATR, Range, and Volatility Classification.
    
    SVI (Stress Volatility Index):
    - <1.0 = Market calm (low stress)
    - 1.0-1.3 = Normal volatility
    - 1.3-1.6 = Elevated volatility
    - >1.6 = High stress
    """
    
    @staticmethod
    def calculate_svi(
        atr_ratio: float,
        recent_range_avg: float,
        expected_range: float
    ) -> float:
        """
        Calculate Stress Volatility Index.
        
        Args:
            atr_ratio: Current ATR / Normal ATR
            recent_range_avg: Average true range of recent candles
            expected_range: Expected normal range
        
        Returns: SVI 0-3.0 (>1.6 = stress)
        """
        if expected_range <= 0:
            return 1.0
        
        svi = (atr_ratio * 0.6 + (recent_range_avg / expected_range) * 0.4)
        return min(3.0, max(0.0, svi))
    
    @staticmethod
    def classify_market_stress(svi: float) -> str:
        """Classify market stress level."""
        if svi < 0.8:
            return 'CALM'
        elif svi < 1.2:
            return 'NORMAL'
        elif svi < 1.5:
            return 'ELEVATED'
        else:
            return 'STRESS'


# ══════════════════════════════════════════════════════════════════════════════
# TASK 10: MULTI-TOUCH SUPPORT CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

class MultiTouchSupportConfirm:
    """Confirms structural level strength via multiple touches."""
    
    @staticmethod
    def calculate_support_strength(
        level_price: float,
        touch_count: int,
        rejection_count: int,
        break_count: int
    ) -> Tuple[str, float]:
        """
        Determine support/resistance strength from multiple touches.
        
        Returns: (confidence_level, strength_0_100)
        """
        
        if touch_count < 2:
            return ('WEAK', 30.0)
        
        rejection_ratio = rejection_count / max(1, rejection_count + break_count)
        
        if touch_count >= 5 and rejection_ratio > 0.8:
            return ('VERY_STRONG', 90.0)
        elif touch_count >= 5 and rejection_ratio > 0.5:
            return ('STRONG', 75.0)
        elif touch_count >= 3 and rejection_ratio > 0.7:
            return ('STRONG', 70.0)
        elif touch_count >= 3 and rejection_ratio > 0.4:
            return ('MODERATE', 55.0)
        elif touch_count == 2 and rejection_ratio > 0.8:
            return ('MODERATE', 50.0)
        elif touch_count == 2:
            return ('WEAK', 35.0)
        else:
            return ('VERY_WEAK', 20.0)
    
    @staticmethod
    def confirm_structure_trade(
        level_price: float,
        current_price: float,
        structure_strength: str,
        tolerance_pts: float = 10.0
    ) -> Tuple[bool, str]:
        """
        Confirm if trade should be taken based on structure confirmation.
        
        Returns: (should_trade, reason)
        """
        distance = abs(current_price - level_price)
        
        if distance > tolerance_pts * 2:
            return (False, "Price too far from structure")
        
        if structure_strength in ['VERY_STRONG', 'STRONG']:
            return (True, f"Trade confirmed by {structure_strength} structure at {level_price}")
        elif structure_strength == 'MODERATE' and distance < tolerance_pts:
            return (True, f"Trade confirmed by {structure_strength} structure + proximity")
        else:
            return (False, f"Insufficient confirmation from {structure_strength} structure")


def get_session_adjusted_analysis(
    wyckoff_phase: str,
    phase_confidence: float,
    phase_bonus: float
) -> Dict[str, Any]:
    """
    Get session-adjusted Wyckoff analysis.
    
    Returns: Analysis with session-specific adjustments
    """
    session = SessionPhaseStrategy.get_current_session()
    adjusted_bonus = SessionPhaseStrategy.adjust_phase_bonus_by_session(
        wyckoff_phase, session, phase_bonus
    )
    adjusted_confidence = phase_confidence + (adjusted_bonus - phase_bonus)
    
    return {
        'session': session,
        'original_bonus': phase_bonus,
        'adjusted_bonus': adjusted_bonus,
        'original_confidence': phase_confidence,
        'adjusted_confidence': min(100.0, max(0.0, adjusted_confidence)),
    }
