"""
Spring/Shakeout Projection Engine Module
Calculates automatic targets using Wyckoff cause-effect distance and geometric patterns.

Core Principle:
- CAUSE: The consolidation/accumulation/distribution zone size (distance)
- EFFECT: The resulting move after breakout from the zone
- Traditional ratio: Effect = Cause × 1.0 to Cause × 3.0 (depending on conviction)

For SPRING (bullish reversal from accumulation):
- Target = Spring_Low + (Accumulation_Range × Multiplier)
- Multiplier: 1.0 (conservative) to 2.5 (aggressive)

For SHAKEOUT (bearish reversal from distribution):
- Target = Shakeout_High - (Distribution_Range × Multiplier)
- Multiplier: 1.0 (conservative) to 2.5 (aggressive)

Multiplier determination:
- High volume on breakout → 2.0-2.5
- Normal volume → 1.5-2.0
- Low volume → 1.0-1.5
- Plus: +0.5 if structurally supported (multiple touches)
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)


class WyckoffProjection:
    """Represents a Wyckoff projection with cause and effect."""
    
    def __init__(
        self,
        phase: str,
        direction: str,
        cause_low: float,
        cause_high: float,
        breakout_point: float,
        volume_ratio: float = 1.0,
        structural_touches: int = 0
    ):
        """
        Args:
            phase: "SPRING" or "SHAKEOUT"
            direction: "BUY" or "SELL"
            cause_low: Lowest point of consolidation (accumulation/distribution)
            cause_high: Highest point of consolidation
            breakout_point: Price where breakout occurred
            volume_ratio: Volume ratio during breakout (>1.0 = high volume)
            structural_touches: Number of touches at key levels (indicates strength)
        """
        self.phase = phase
        self.direction = direction
        self.cause_low = cause_low
        self.cause_high = cause_high
        self.breakout_point = breakout_point
        self.volume_ratio = volume_ratio
        self.structural_touches = structural_touches
        
        # Calculate cause (consolidation range)
        self.cause_distance = abs(cause_high - cause_low)
        
        # Calculate base multiplier based on factors
        self._calculate_multiplier()
    
    def _calculate_multiplier(self) -> None:
        """Calculate the cause-effect multiplier (1.0-2.5)."""
        
        # Base multiplier from volume
        if self.volume_ratio > 1.3:
            self.multiplier = 2.2  # Strong volume = aggressive projection
        elif self.volume_ratio > 1.0:
            self.multiplier = 1.8  # Normal volume
        else:
            self.multiplier = 1.2  # Weak volume = conservative
        
        # Adjust for structural strength (multiple touches = strong level = better projection)
        if self.structural_touches >= 5:
            self.multiplier += 0.4  # Very strong structure
        elif self.structural_touches >= 3:
            self.multiplier += 0.2  # Moderate structure
        
        # Cap multiplier
        self.multiplier = min(2.5, max(1.0, self.multiplier))
    
    def get_primary_target(self) -> float:
        """Get primary (1:1) profit target."""
        if self.phase == "SPRING":
            # Spring Low + Cause Distance
            return self.cause_low + self.cause_distance * self.multiplier
        else:  # SHAKEOUT
            # Shakeout High - Cause Distance
            return self.cause_high - self.cause_distance * self.multiplier
    
    def get_extended_target(self) -> float:
        """Get extended (1:1.5) profit target."""
        if self.phase == "SPRING":
            return self.cause_low + self.cause_distance * (self.multiplier * 1.5)
        else:  # SHAKEOUT
            return self.cause_high - self.cause_distance * (self.multiplier * 1.5)
    
    def get_aggressive_target(self) -> float:
        """Get aggressive (1:2) profit target."""
        if self.phase == "SPRING":
            return self.cause_low + self.cause_distance * (self.multiplier * 2.0)
        else:  # SHAKEOUT
            return self.cause_high - self.cause_distance * (self.multiplier * 2.0)
    
    def get_stop_loss(self, atr_multiple: float = 1.5) -> float:
        """
        Get stop loss price.
        
        For SPRING: Just below cause_low (spring low)
        For SHAKEOUT: Just above cause_high (shakeout high)
        
        Args:
            atr_multiple: ATR multiplier for hard stop distance
        """
        if self.phase == "SPRING":
            # Stop below spring low
            buffer = self.cause_distance * 0.15  # 15% buffer
            return self.cause_low - buffer
        else:  # SHAKEOUT
            # Stop above shakeout high
            buffer = self.cause_distance * 0.15
            return self.cause_high + buffer
    
    def get_risk_reward_ratio(self, primary_target: bool = True) -> float:
        """
        Calculate risk-to-reward ratio.
        
        Returns: Ratio (e.g., 1:3 = 3.0)
        """
        if primary_target:
            target = self.get_primary_target()
        else:
            target = self.get_extended_target()
        
        stop_loss = self.get_stop_loss()
        entry = self.breakout_point
        
        risk = abs(entry - stop_loss)
        reward = abs(target - entry)
        
        if risk <= 0:
            return 1.0
        
        return reward / risk
    
    def get_projection_summary(self) -> Dict[str, Any]:
        """Get detailed projection summary."""
        return {
            'phase': self.phase,
            'direction': self.direction,
            'cause_distance': round(self.cause_distance, 2),
            'multiplier': round(self.multiplier, 2),
            'breakout_point': round(self.breakout_point, 2),
            'primary_target': round(self.get_primary_target(), 2),
            'extended_target': round(self.get_extended_target(), 2),
            'aggressive_target': round(self.get_aggressive_target(), 2),
            'stop_loss': round(self.get_stop_loss(), 2),
            'risk_reward_ratio': round(self.get_risk_reward_ratio(), 2),
        }


class SpringShakeoutProjector:
    """Projects spring/shakeout targets using Wyckoff cause-effect methodology."""
    
    @staticmethod
    def project_spring_target(
        accumulation_low: float,
        accumulation_high: float,
        spring_low: float,
        current_price: float,
        volume_ratio: float = 1.0,
        structural_touches: int = 0
    ) -> WyckoffProjection:
        """
        Project spring target (bullish reversal).
        
        Args:
            accumulation_low: Low point of accumulation zone
            accumulation_high: High point of accumulation zone
            spring_low: Lowest point of spring (failed downside break)
            current_price: Current market price
            volume_ratio: Volume during spring breakout
            structural_touches: Touches at accumulation support
        
        Returns: WyckoffProjection with targets
        """
        return WyckoffProjection(
            phase="SPRING",
            direction="BUY",
            cause_low=accumulation_low,
            cause_high=accumulation_high,
            breakout_point=current_price,
            volume_ratio=volume_ratio,
            structural_touches=structural_touches
        )
    
    @staticmethod
    def project_shakeout_target(
        distribution_low: float,
        distribution_high: float,
        shakeout_high: float,
        current_price: float,
        volume_ratio: float = 1.0,
        structural_touches: int = 0
    ) -> WyckoffProjection:
        """
        Project shakeout target (bearish reversal).
        
        Args:
            distribution_low: Low point of distribution zone
            distribution_high: High point of distribution zone
            shakeout_high: Highest point of shakeout (failed upside break)
            current_price: Current market price
            volume_ratio: Volume during shakeout breakout
            structural_touches: Touches at distribution resistance
        
        Returns: WyckoffProjection with targets
        """
        return WyckoffProjection(
            phase="SHAKEOUT",
            direction="SELL",
            cause_low=distribution_low,
            cause_high=distribution_high,
            breakout_point=current_price,
            volume_ratio=volume_ratio,
            structural_touches=structural_touches
        )
    
    @staticmethod
    def project_from_wyckoff_phase(
        wyckoff_phase: str,
        direction: str,
        current_price: float,
        market_low: float,
        market_high: float,
        volume_ratio: float = 1.0,
        structural_touches: int = 0
    ) -> Optional[WyckoffProjection]:
        """
        Create projection from detected Wyckoff phase.
        
        Args:
            wyckoff_phase: "SPRING", "SHAKEOUT", "ACCUMULATION", "DISTRIBUTION", etc.
            direction: "BUY" or "SELL"
            current_price: Current market price
            market_low: Recent market low (for accumulation/distribution)
            market_high: Recent market high
            volume_ratio: Volume ratio
            structural_touches: Number of structural touches
        
        Returns: WyckoffProjection if spring/shakeout phase, None otherwise
        """
        if wyckoff_phase == "SPRING" and direction == "BUY":
            # market_low is spring low, market_high is top of consolidation
            return SpringShakeoutProjector.project_spring_target(
                accumulation_low=market_low,
                accumulation_high=market_high,
                spring_low=market_low,
                current_price=current_price,
                volume_ratio=volume_ratio,
                structural_touches=structural_touches
            )
        elif wyckoff_phase == "SHAKEOUT" and direction == "SELL":
            # market_high is shakeout high, market_low is bottom of consolidation
            return SpringShakeoutProjector.project_shakeout_target(
                distribution_low=market_low,
                distribution_high=market_high,
                shakeout_high=market_high,
                current_price=current_price,
                volume_ratio=volume_ratio,
                structural_touches=structural_touches
            )
        
        return None
    
    @staticmethod
    def get_geometric_levels(
        projection: WyckoffProjection
    ) -> Dict[str, float]:
        """
        Get all geometric projection levels.
        
        Returns: Dictionary with multiple profit targets and support/resistance
        """
        return {
            'breakout': projection.breakout_point,
            'stop_loss': projection.get_stop_loss(),
            'target_1_conservative': projection.get_primary_target() * 0.8,  # 80% of target
            'target_1_primary': projection.get_primary_target(),
            'target_2_extended': projection.get_extended_target(),
            'target_3_aggressive': projection.get_aggressive_target(),
            'cause_distance': projection.cause_distance,
            'multiplier': projection.multiplier,
            'risk_reward': projection.get_risk_reward_ratio(),
        }


def calculate_wyckoff_targets(
    phase: str,
    direction: str,
    phase_low: float,
    phase_high: float,
    current_price: float,
    volume_ratio: float = 1.0,
    structural_strength: float = 50.0  # 0-100%
) -> Dict[str, Any]:
    """
    Convenience function to calculate Wyckoff targets.
    
    Returns:
        Dictionary with phase, targets, stop loss, and risk-reward ratio
    """
    # Convert structural strength (0-100) to touch count (0-5+)
    structural_touches = max(0, int((structural_strength / 20.0)))
    
    if phase == "SPRING" and direction == "BUY":
        projection = SpringShakeoutProjector.project_spring_target(
            accumulation_low=phase_low,
            accumulation_high=phase_high,
            spring_low=phase_low,
            current_price=current_price,
            volume_ratio=volume_ratio,
            structural_touches=structural_touches
        )
    elif phase == "SHAKEOUT" and direction == "SELL":
        projection = SpringShakeoutProjector.project_shakeout_target(
            distribution_low=phase_low,
            distribution_high=phase_high,
            shakeout_high=phase_high,
            current_price=current_price,
            volume_ratio=volume_ratio,
            structural_touches=structural_touches
        )
    else:
        return {
            'phase': phase,
            'error': f"Cannot project targets for {phase} + {direction}"
        }
    
    summary = projection.get_projection_summary()
    levels = SpringShakeoutProjector.get_geometric_levels(projection)
    
    return {
        'phase': phase,
        'direction': direction,
        'projection': summary,
        'geometric_levels': levels,
        'summary': f"{phase} {direction} - Primary target: {summary['primary_target']}, Stop: {summary['stop_loss']}, R:R {summary['risk_reward_ratio']:.1f}:1"
    }
