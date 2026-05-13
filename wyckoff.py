"""
Wyckoff Market Methodology Module
Identifies accumulation/distribution phases and supply/demand imbalances for XAUUSD

Core Principles:
1. ACCUMULATION: Institutional buying before uptrend
2. DISTRIBUTION: Institutional selling before downtrend
3. SPRING: Failed downside breakout (bullish reversal)
4. SHAKOUT: Failed upside breakout (bearish reversal)
5. SUPPLY/DEMAND IMBALANCE: Zones where institutions exhausted (entry points)
"""

from typing import Dict, Tuple, Any, List
import logging

logger = logging.getLogger(__name__)


def _f(val):
    """Safe float conversion."""
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


class WyckoffPhaseDetector:
    """Detects Wyckoff accumulation/distribution phases with graduated confidence scoring."""
    
    # Phase thresholds
    ACCUMULATION_MIN_BARS = 8  # Minimum bars in accumulation zone
    DISTRIBUTION_MIN_BARS = 8
    SPRING_RSI_THRESHOLD = 30  # RSI < 30 on failed down break
    SHAKEOUT_RSI_THRESHOLD = 70  # RSI > 70 on failed up break
    VOLUME_DECLINE_RATIO = 0.7  # Volume should be <70% of preceding bar
    
    # Confidence thresholds for phase classification
    PHASE_CONFIDENCE_HIGH = 0.85      # 85%+ = HIGH confidence
    PHASE_CONFIDENCE_BUILDING = 0.45  # 45-84% = BUILDING confidence
    # <45% = FALSE/REJECTED
    
    @staticmethod
    def _score_rsi_phase_component(
        direction: str,
        phase: str,
        h4_rsi: float,
        h1_rsi: float,
        m5_rsi: float,
        m15_rsi: float
    ) -> float:
        """
        Score RSI phase component (40-90% baseline).
        Measures whether RSI values match the expected phase.
        """
        score = 50.0  # Neutral baseline
        
        if phase == "ACCUMULATION" and direction == "BUY":
            # Accumulation: H4 RSI <45, H1 RSI 40-60 (quiet)
            if h4_rsi and h4_rsi < 45:
                score += 20.0
            if h1_rsi and 40 < h1_rsi < 60:
                score += 20.0
            return min(90.0, max(40.0, score))
        
        elif phase == "DISTRIBUTION" and direction == "SELL":
            # Distribution: H4 RSI >55, H1 RSI 40-60 (quiet)
            if h4_rsi and h4_rsi > 55:
                score += 20.0
            if h1_rsi and 40 < h1_rsi < 60:
                score += 20.0
            return min(90.0, max(40.0, score))
        
        elif phase == "SPRING" and direction == "BUY":
            # Spring: M5 RSI <30 (extreme oversold)
            if m5_rsi and m5_rsi < 30:
                score = 90.0
            elif m5_rsi and m5_rsi < 40:
                score = 75.0
            return score
        
        elif phase == "SHAKEOUT" and direction == "SELL":
            # Shakeout: M5 RSI >70 (extreme overbought)
            if m5_rsi and m5_rsi > 70:
                score = 90.0
            elif m5_rsi and m5_rsi > 60:
                score = 75.0
            return score
        
        elif phase == "MARKUP" and direction == "BUY":
            # Markup: H4 RSI >50, sustained bullish
            if h4_rsi and h4_rsi > 50:
                score = 80.0
            return score
        
        elif phase == "MARKDOWN" and direction == "SELL":
            # Markdown: H4 RSI <50, sustained bearish
            if h4_rsi and h4_rsi < 50:
                score = 80.0
            return score
        
        return 50.0
    
    @staticmethod
    def _score_volume_profile_component(
        direction: str,
        phase: str,
        m15_vol_ratio: float,
        m5_vol_ratio: float
    ) -> float:
        """
        Score volume profile fit (20-80% baseline).
        Measures whether volume patterns match the expected phase.
        """
        score = 50.0  # Neutral
        
        if phase in ["ACCUMULATION", "DISTRIBUTION"]:
            # Consolidation phases: low volume pattern (vol_ratio < 0.7)
            if m15_vol_ratio and m15_vol_ratio < 0.7:
                score = 75.0
            elif m15_vol_ratio and m15_vol_ratio < 0.85:
                score = 60.0
            else:
                score = 30.0  # High volume contradicts consolidation
        
        elif phase in ["SPRING", "SHAKEOUT", "MARKUP", "MARKDOWN"]:
            # Trend phases: normal to high volume (vol_ratio 0.8-1.2)
            if m15_vol_ratio and 0.8 <= m15_vol_ratio <= 1.2:
                score = 75.0
            elif m15_vol_ratio and 0.6 <= m15_vol_ratio <= 1.4:
                score = 60.0
            else:
                score = 35.0  # Abnormal volume pattern
        
        return min(80.0, max(20.0, score))
    
    @staticmethod
    def _score_price_action_component(
        direction: str,
        phase: str,
        h4_trend: str,
        h1_trend: str,
        m15_trend: str
    ) -> float:
        """
        Score price action confirmation (30-85% baseline).
        Measures whether price action aligns with phase expectations.
        """
        score = 40.0  # Conservative baseline
        
        if phase == "ACCUMULATION" and direction == "BUY":
            if h4_trend in ["HOLD", "BUY"] and h1_trend in ["HOLD", "BUY", "Weak Bullish"]:
                score = 75.0
            elif h4_trend == "HOLD" and h1_trend in ["NO TRADE", "Weak Bullish"]:
                score = 60.0
            return min(85.0, max(30.0, score))
        
        elif phase == "DISTRIBUTION" and direction == "SELL":
            if h4_trend in ["HOLD", "SELL"] and h1_trend in ["HOLD", "SELL", "Weak Bearish"]:
                score = 75.0
            elif h4_trend == "HOLD" and h1_trend in ["NO TRADE", "Weak Bearish"]:
                score = 60.0
            return min(85.0, max(30.0, score))
        
        elif phase == "SPRING" and direction == "BUY":
            if h4_trend == "BUY" or (h4_trend == "HOLD" and h1_trend == "BUY"):
                score = 80.0
            elif h1_trend == "BUY":
                score = 70.0
            return min(85.0, max(30.0, score))
        
        elif phase == "SHAKEOUT" and direction == "SELL":
            if h4_trend == "SELL" or (h4_trend == "HOLD" and h1_trend == "SELL"):
                score = 80.0
            elif h1_trend == "SELL":
                score = 70.0
            return min(85.0, max(30.0, score))
        
        elif phase == "MARKUP" and direction == "BUY":
            if h4_trend == "BUY" and h1_trend == "BUY":
                score = 80.0
            elif h4_trend == "BUY":
                score = 70.0
            return min(85.0, max(30.0, score))
        
        elif phase == "MARKDOWN" and direction == "SELL":
            if h4_trend == "SELL" and h1_trend == "SELL":
                score = 80.0
            elif h4_trend == "SELL":
                score = 70.0
            return min(85.0, max(30.0, score))
        
        return min(85.0, max(30.0, score))
    
    @staticmethod
    def _score_time_in_zone_component(
        phase: str,
        consolidation_bars: int = 0
    ) -> float:
        """
        Score time in consolidation zone (10-70% baseline).
        Measures duration of phase (more bars = more conviction).
        """
        if consolidation_bars <= 0:
            return 30.0  # No consolidation data
        
        if consolidation_bars < 5:
            return 25.0  # Too brief
        elif consolidation_bars < 12:
            return 45.0  # Starting to build
        elif consolidation_bars < 20:
            return 60.0  # Solid
        else:
            return 70.0  # Strong consolidation
    
    @staticmethod
    def _score_supply_demand_slope_component(
        direction: str,
        phase: str,
        h4_rsi: float,
        h1_rsi: float
    ) -> float:
        """
        Score supply/demand line slope (40-90% baseline).
        Measures RSI momentum indicating supply/demand balance.
        """
        score = 50.0
        
        if phase == "ACCUMULATION" and direction == "BUY":
            # Supply/demand should be balanced (RSI 40-60)
            if h1_rsi and 40 <= h1_rsi <= 60:
                score = 80.0
            elif h1_rsi and 35 <= h1_rsi <= 65:
                score = 65.0
            else:
                score = 40.0
        
        elif phase == "DISTRIBUTION" and direction == "SELL":
            # Supply/demand should be balanced (RSI 40-60)
            if h1_rsi and 40 <= h1_rsi <= 60:
                score = 80.0
            elif h1_rsi and 35 <= h1_rsi <= 65:
                score = 65.0
            else:
                score = 40.0
        
        elif phase in ["SPRING", "MARKUP"] and direction == "BUY":
            # Buyers dominating
            if h1_rsi and h1_rsi > 50:
                score = 85.0
            elif h1_rsi and h1_rsi > 45:
                score = 70.0
            else:
                score = 40.0
        
        elif phase in ["SHAKEOUT", "MARKDOWN"] and direction == "SELL":
            # Sellers dominating
            if h1_rsi and h1_rsi < 50:
                score = 85.0
            elif h1_rsi and h1_rsi < 55:
                score = 70.0
            else:
                score = 40.0
        
        return min(90.0, max(40.0, score))
    
    @staticmethod
    def identify_phase(
        direction: str,
        tfa: Dict[str, Dict[str, Any]],
        tfi: Dict[str, Dict[str, Any]],
        recent_price_history: List[float] = None,
        recent_volume_history: List[float] = None
    ) -> Tuple[str, float, str, Dict[str, float]]:
        """
        Identify current Wyckoff phase with graduated confidence scoring.
        
        Returns:
            - phase: 'ACCUMULATION', 'DISTRIBUTION', 'MARKUP', 'MARKDOWN', 'SPRING', 'SHAKEOUT', 'NEUTRAL'
            - confidence: 0-100 graduated confidence (not binary)
            - reason: Explanation for phase determination
            - components: {rsi_score, volume_score, price_action_score, time_score, supply_demand_score}
        """
        
        h4_trend = tfa.get("H4", {}).get("direction", "NO TRADE")
        h1_trend = tfa.get("H1", {}).get("direction", "NO TRADE")
        m15_trend = tfa.get("M15", {}).get("direction", "NO TRADE")
        
        # Get RSI values
        h4_rsi = _f(tfi.get("H4", {}).get("rsi_14"))
        h1_rsi = _f(tfi.get("H1", {}).get("rsi_14"))
        m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
        m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
        
        # Get volume data
        m15_vol_ratio = _f(tfi.get("M15", {}).get("volume_ratio"))
        m5_vol_ratio = _f(tfi.get("M5", {}).get("volume_ratio"))
        
        # ═══════════════════════════════════════════════════════════════
        # PHASE DETECTION LOGIC (with multi-phase scoring)
        # ═══════════════════════════════════════════════════════════════
        
        phase_candidates = []
        
        # ACCUMULATION detection
        if h4_trend == "HOLD" and direction == "BUY":
            if h1_trend in ["Weak Bullish", "NO TRADE", "HOLD"] and h4_rsi is not None and h4_rsi < 45:
                phase_candidates.append(("ACCUMULATION", 0.95))
            elif h4_rsi is not None and h4_rsi < 50 and h1_rsi is not None and 35 < h1_rsi < 65:
                phase_candidates.append(("ACCUMULATION", 0.80))
        
        # DISTRIBUTION detection
        if h4_trend == "HOLD" and direction == "SELL":
            if h1_trend in ["Weak Bearish", "NO TRADE", "HOLD"] and h4_rsi is not None and h4_rsi > 55:
                phase_candidates.append(("DISTRIBUTION", 0.95))
            elif h4_rsi is not None and h4_rsi > 50 and h1_rsi is not None and 35 < h1_rsi < 65:
                phase_candidates.append(("DISTRIBUTION", 0.80))
        
        # SPRING detection (M5 RSI <30)
        if direction == "BUY" and m5_rsi is not None and m5_rsi < 30:
            if h4_trend == "BUY":
                phase_candidates.append(("SPRING", 0.95))
            elif h4_trend == "HOLD" and h1_trend == "BUY":
                phase_candidates.append(("SPRING", 0.85))
            else:
                phase_candidates.append(("SPRING", 0.70))
        
        # SHAKEOUT detection (M5 RSI >70)
        if direction == "SELL" and m5_rsi is not None and m5_rsi > 70:
            if h4_trend == "SELL":
                phase_candidates.append(("SHAKEOUT", 0.95))
            elif h4_trend == "HOLD" and h1_trend == "SELL":
                phase_candidates.append(("SHAKEOUT", 0.85))
            else:
                phase_candidates.append(("SHAKEOUT", 0.70))
        
        # MARKUP detection
        if h4_trend == "BUY" and direction == "BUY" and h1_trend == "BUY":
            if h4_rsi is not None and h4_rsi > 50:
                phase_candidates.append(("MARKUP", 0.90))
            else:
                phase_candidates.append(("MARKUP", 0.70))
        
        # MARKDOWN detection
        if h4_trend == "SELL" and direction == "SELL" and h1_trend == "SELL":
            if h4_rsi is not None and h4_rsi < 50:
                phase_candidates.append(("MARKDOWN", 0.90))
            else:
                phase_candidates.append(("MARKDOWN", 0.70))
        
        # Select highest confidence phase
        if phase_candidates:
            phase, raw_strength = max(phase_candidates, key=lambda x: x[1])
        else:
            phase = "NEUTRAL"
            raw_strength = 0.0
        
        # ═══════════════════════════════════════════════════════════════
        # CALCULATE 5 COMPONENT SCORES FOR GRADUATED CONFIDENCE
        # ═══════════════════════════════════════════════════════════════
        
        rsi_score = WyckoffPhaseDetector._score_rsi_phase_component(
            direction, phase, h4_rsi, h1_rsi, m5_rsi, m15_rsi
        )
        
        volume_score = WyckoffPhaseDetector._score_volume_profile_component(
            direction, phase, m15_vol_ratio, m5_vol_ratio
        )
        
        price_action_score = WyckoffPhaseDetector._score_price_action_component(
            direction, phase, h4_trend, h1_trend, m15_trend
        )
        
        consolidation_bars = 0  # TODO: Track actual consolidation duration
        time_score = WyckoffPhaseDetector._score_time_in_zone_component(
            phase, consolidation_bars
        )
        
        supply_demand_score = WyckoffPhaseDetector._score_supply_demand_slope_component(
            direction, phase, h4_rsi, h1_rsi
        )
        
        # ═══════════════════════════════════════════════════════════════
        # BLEND 5 COMPONENTS INTO GRADUATED CONFIDENCE (0-100%)
        # ═══════════════════════════════════════════════════════════════
        
        # Weighted average (adjustable weights for optimization)
        confidence_0_100 = (
            rsi_score * 0.25 +           # 25% - RSI alignment
            volume_score * 0.20 +         # 20% - Volume profile
            price_action_score * 0.25 +   # 25% - Price action
            time_score * 0.10 +           # 10% - Time in zone
            supply_demand_score * 0.20    # 20% - Supply/demand slope
        )
        
        # Apply raw phase detection strength as multiplier (0-1)
        confidence_0_100 = confidence_0_100 * raw_strength
        
        # Build component scores dict for detailed logging
        components = {
            'rsi': round(rsi_score, 1),
            'volume': round(volume_score, 1),
            'price_action': round(price_action_score, 1),
            'time': round(time_score, 1),
            'supply_demand': round(supply_demand_score, 1),
            'raw_strength': round(raw_strength * 100, 1)
        }
        
        # Generate explanation
        if phase == "NEUTRAL":
            reason = f"No clear Wyckoff phase detected (confidence: {confidence_0_100:.0f}%)"
        else:
            confidence_level = "HIGH" if confidence_0_100 >= 85 else "BUILDING" if confidence_0_100 >= 45 else "FALSE"
            reason = f"{phase} ({confidence_level}, {confidence_0_100:.0f}%) | RSI:{rsi_score:.0f} Vol:{volume_score:.0f} PA:{price_action_score:.0f} SD:{supply_demand_score:.0f}"
        
        return (phase, confidence_0_100, reason, components)


def find_imbalance_zones(
    tfi: Dict[str, Dict[str, Any]],
    tfa: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Identify supply/demand imbalance zones.
    
    Imbalances form where:
    - High volume bar followed by low volume bars = Zone where institutions exited
    - Price respects these zones as support/resistance
    
    Returns:
        List of {type, zone_low, zone_high, strength}
    """
    
    imbalances = []
    
    m15_vol_ratio = _f(tfi.get("M15", {}).get("volume_ratio"))
    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    
    # DEMAND IMBALANCE: High-volume selloff followed by rising price on low volume
    # This means sellers exhausted their position = buyers can step in
    if m15_vol_ratio is not None and m15_vol_ratio > 1.0:  # Recent high volume
        if m15_rsi is not None and m15_rsi < 35:  # Oversold condition
            if m5_rsi is not None and m5_rsi > 40:  # But M5 recovering
                imbalances.append({
                    'type': 'DEMAND',  # Buyers can enter here
                    'strength': min(1.0, (1.5 - m15_vol_ratio) * 2),  # Normalized strength
                    'rsi_level': m15_rsi,
                    'reason': 'Sell-side imbalance - sellers exhausted'
                })
    
    # SUPPLY IMBALANCE: High-volume rally followed by falling price on low volume
    # This means buyers exhausted their position = sellers can step in
    if m15_vol_ratio is not None and m15_vol_ratio > 1.0:  # Recent high volume
        if m15_rsi is not None and m15_rsi > 65:  # Overbought condition
            if m5_rsi is not None and m5_rsi < 60:  # But M5 declining
                imbalances.append({
                    'type': 'SUPPLY',  # Sellers can enter here
                    'strength': min(1.0, (1.5 - m15_vol_ratio) * 2),
                    'rsi_level': m15_rsi,
                    'reason': 'Buy-side imbalance - buyers exhausted'
                })
    
    return imbalances


def apply_wyckoff_confidence_adjustment(
    base_confidence: float,
    direction: str,
    phase: str,
    phase_confidence: float,
    imbalances: List[Dict[str, Any]]
) -> Tuple[float, str]:
    """
    Adjust confidence based on Wyckoff phase alignment.
    
    Args:
        base_confidence: Current confidence 0-100
        direction: "BUY" or "SELL"
        phase: Wyckoff phase detected
        phase_confidence: 0-100 graduated phase confidence
        imbalances: List of detected imbalance zones
    
    Returns:
        (adjusted_confidence, adjustment_reason)
    """
    
    adjustment = 0.0
    reasons = []
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE ALIGNMENT BONUSES (scaled by phase_confidence)
    # ═══════════════════════════════════════════════════════════════
    
    phase_confidence_multiplier = phase_confidence / 100.0  # Convert to 0-1 for bonus scaling
    
    if phase == "ACCUMULATION" and direction == "BUY":
        adjustment += 12.0 * phase_confidence_multiplier
        reasons.append(f"ACCUMULATION phase alignment +{12.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "DISTRIBUTION" and direction == "SELL":
        adjustment += 12.0 * phase_confidence_multiplier
        reasons.append(f"DISTRIBUTION phase alignment +{12.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "SPRING" and direction == "BUY":
        adjustment += 15.0 * phase_confidence_multiplier  # Spring is high conviction bullish
        reasons.append(f"SPRING reversal +{15.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "SHAKEOUT" and direction == "SELL":
        adjustment += 15.0 * phase_confidence_multiplier  # Shakeout is high conviction bearish
        reasons.append(f"SHAKEOUT reversal +{15.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "MARKUP" and direction == "BUY":
        adjustment += 8.0 * phase_confidence_multiplier
        reasons.append(f"MARKUP continuation +{8.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "MARKDOWN" and direction == "SELL":
        adjustment += 8.0 * phase_confidence_multiplier
        reasons.append(f"MARKDOWN continuation +{8.0 * phase_confidence_multiplier:.1f}%")
    
    elif phase == "NEUTRAL":
        adjustment -= 5.0
        reasons.append("No Wyckoff phase detected -5%")
    
    # ═══════════════════════════════════════════════════════════════
    # IMBALANCE ZONE BONUSES
    # ═══════════════════════════════════════════════════════════════
    
    if imbalances:
        for imbalance in imbalances:
            if imbalance['type'] == 'DEMAND' and direction == "BUY":
                bonus = 8.0 * imbalance['strength']
                adjustment += bonus
                reasons.append(f"DEMAND imbalance zone +{bonus:.1f}%")
            
            elif imbalance['type'] == 'SUPPLY' and direction == "SELL":
                bonus = 8.0 * imbalance['strength']
                adjustment += bonus
                reasons.append(f"SUPPLY imbalance zone +{bonus:.1f}%")
    
    # ═══════════════════════════════════════════════════════════════
    # PENALTY FOR TRADING AGAINST PHASE (graduated by phase_confidence)
    # ═══════════════════════════════════════════════════════════════
    
    if phase in ["ACCUMULATION", "SPRING"] and direction == "SELL":
        penalty = 20.0 * phase_confidence_multiplier
        adjustment -= penalty
        reasons.append(f"Trading SELL against {phase} phase -{penalty:.1f}%")
    
    elif phase in ["DISTRIBUTION", "SHAKEOUT"] and direction == "BUY":
        penalty = 20.0 * phase_confidence_multiplier
        adjustment -= penalty
        reasons.append(f"Trading BUY against {phase} phase -{penalty:.1f}%")
    
    final_confidence = max(20.0, base_confidence + adjustment)  # Floor at 20%
    reason_str = " | ".join(reasons) if reasons else "No Wyckoff adjustments"
    
    return (final_confidence, reason_str)


def validate_entry_with_wyckoff(
    direction: str,
    entry_price: float,
    phase: str,
    imbalances: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Validate if entry is valid based on Wyckoff structure.
    
    Returns:
        (is_valid, validation_reason)
    """
    
    # High-conviction phases always allow entries
    if phase in ["SPRING", "SHAKEOUT"]:
        return (True, f"{phase} phase - High conviction entry")
    
    # Accumulation/Distribution require imbalance zone confirmation
    if phase == "ACCUMULATION" and direction == "BUY":
        demand_imbalance = any(i['type'] == 'DEMAND' for i in imbalances)
        if demand_imbalance:
            return (True, "Accumulation + demand imbalance confirmed")
        else:
            return (False, "Accumulation detected but no demand imbalance - Wait for confirmation")
    
    if phase == "DISTRIBUTION" and direction == "SELL":
        supply_imbalance = any(i['type'] == 'SUPPLY' for i in imbalances)
        if supply_imbalance:
            return (True, "Distribution + supply imbalance confirmed")
        else:
            return (False, "Distribution detected but no supply imbalance - Wait for confirmation")
    
    # Markup/Markdown are continuations - lower conviction
    if phase == "MARKUP" and direction == "BUY":
        return (True, "Markup continuation - Valid entry")
    
    if phase == "MARKDOWN" and direction == "SELL":
        return (True, "Markdown continuation - Valid entry")
    
    # Neutral phase requires strong imbalance
    if phase == "NEUTRAL":
        if imbalances and len(imbalances) > 0:
            return (True, "Neutral phase but strong imbalance detected")
        else:
            return (False, "Neutral phase and no imbalance - Wait for clearer structure")
    
    return (False, f"Phase {phase} not suitable for {direction}")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Get Wyckoff Summary for Logging
# ═══════════════════════════════════════════════════════════════════════════════

def get_wyckoff_summary(
    phase: str,
    phase_strength: float,
    imbalances: List[Dict[str, Any]],
    confidence_adjustment: float
) -> str:
    """Format Wyckoff analysis for logging."""
    
    parts = [f"[WYCKOFF] Phase: {phase} ({phase_strength*100:.0f}%)"]
    
    if imbalances:
        imbalance_types = [f"{i['type']}({i['strength']*100:.0f}%)" for i in imbalances]
        parts.append(f"Imbalances: {', '.join(imbalance_types)}")
    
    if confidence_adjustment != 0:
        sign = "+" if confidence_adjustment > 0 else ""
        parts.append(f"Confidence: {sign}{confidence_adjustment:.1f}%")
    
    return " | ".join(parts)
