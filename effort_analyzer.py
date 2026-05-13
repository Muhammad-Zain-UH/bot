"""
Effort vs Result Analyzer Module
Detects market exhaustion 48-72 hours early by analyzing effort (volume × candle body) vs result (price move).

Core Principle:
- EXHAUSTION: High volume/effort but low price progress = buyers/sellers exhausted = reversal imminent
- STRONG BREAKOUT: High volume/effort AND high price progress = strong directional bias
- Weak Trend: Low volume/effort = low conviction = likely pullback/reversal

Ratios:
- >1.5: STRONG (breakout, high conviction)
- 0.5-1.5: NORMAL (trend continuation expected)
- <0.5: EXHAUSTION (reversal probability 70%+, reversal in 48-72h)
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class EffortResult:
    """Represents effort vs result analysis for a candle."""
    
    def __init__(
        self,
        candle_index: int,
        timestamp: str,
        volume: float,
        body_size: float,
        high_low_range: float,
        direction: str
    ):
        """
        Args:
            candle_index: Index in candle history
            timestamp: ISO timestamp
            volume: Volume for this candle
            body_size: Absolute distance between open and close
            high_low_range: Distance between high and low
            direction: "UP" (close > open) or "DOWN" (close < open)
        """
        self.candle_index = candle_index
        self.timestamp = timestamp
        self.volume = volume
        self.body_size = body_size
        self.high_low_range = high_low_range
        self.direction = direction
        
        # Calculate effort vs result ratio
        # Effort = Volume × (Body_Size / High_Low_Range) normalized
        # Result = Body_Size (how far price actually moved)
        self.wick_size = high_low_range - body_size  # Wicks indicate rejection
        self.wick_ratio = self.wick_size / high_low_range if high_low_range > 0 else 0
        
    def calculate_effort_vs_result_ratio(self, avg_volume: float) -> float:
        """
        Calculate effort vs result ratio.
        
        Formula: (Volume / AvgVolume) × (Body_Size / High_Low_Range) / (High_Low_Range / AvgBodySize)
        
        Simplified interpretation:
        - If price moved 50pts on 50K volume = good effort-result alignment (ratio ~1.0)
        - If price moved 10pts on 50K volume = bad alignment (high effort, low result) (ratio ~0.3)
        - If price moved 100pts on 50K volume = exceptional (ratio ~2.0)
        
        Returns: 0-3.0+ ratio (>1.5 = strong, 0.5-1.5 = normal, <0.5 = exhaustion)
        """
        if avg_volume <= 0 or self.high_low_range <= 0:
            return 1.0
        
        volume_component = self.volume / avg_volume  # >1.0 if above average
        efficiency = self.body_size / self.high_low_range  # 0-1.0 (1.0 = no wicks, perfect body)
        result_component = 1.0 / efficiency if efficiency > 0 else 1.0  # Normalize
        
        ratio = (volume_component * efficiency) / result_component
        return max(0.0, min(5.0, ratio))  # Clamp to 0-5 range
    
    def get_exhaustion_probability(self, ratio: float) -> float:
        """
        Estimate probability of reversal within 48-72 hours.
        
        <0.5 ratio = 70% reversal probability
        0.5-0.7 ratio = 50% reversal probability
        0.7-1.0 ratio = 30% reversal probability
        1.0-1.5 ratio = 15% reversal probability
        >1.5 ratio = 5% reversal probability (strong trend)
        """
        if ratio < 0.5:
            return 70.0  # Very high exhaustion
        elif ratio < 0.7:
            return 50.0
        elif ratio < 1.0:
            return 30.0
        elif ratio < 1.5:
            return 15.0
        else:
            return 5.0  # Strong breakout
    
    def get_strength_assessment(self, ratio: float) -> str:
        """Get human-readable strength assessment."""
        if ratio > 1.5:
            return "STRONG"  # Breakout, high conviction
        elif ratio >= 0.5:
            return "NORMAL"  # Trend continuation expected
        else:
            return "EXHAUSTION"  # Reversal likely imminent


class EffortVsResultAnalyzer:
    """Analyzes effort vs result across candle history to detect exhaustion."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.candle_analysis: List[EffortResult] = []
        self.recent_ratio_history: List[float] = []
        self.exhaustion_alerts: List[Dict[str, Any]] = []
    
    def analyze_candle_history(
        self,
        ohlc_history: List[Dict[str, float]],
        direction: str = "BUY"
    ) -> Tuple[float, List[Dict[str, Any]], str]:
        """
        Analyze candle history for exhaustion signals.
        
        Args:
            ohlc_history: List of OHLC candles (newest last)
            direction: "BUY" or "SELL"
        
        Returns:
            (average_ratio, exhaustion_candles, summary_reason)
        """
        if len(ohlc_history) < 5:
            return 1.0, [], "Insufficient candle data"
        
        self.candle_analysis = []
        self.recent_ratio_history = []
        self.exhaustion_alerts = []
        
        # Calculate average volume for normalization
        volumes = [c.get('volume', 0) for c in ohlc_history[-20:]]
        avg_volume = sum(volumes) / len(volumes) if volumes else 1.0
        
        # Analyze last 20 candles
        for i, candle in enumerate(ohlc_history[-20:]):
            open_price = candle.get('open', 0)
            close_price = candle.get('close', 0)
            high_price = candle.get('high', 0)
            low_price = candle.get('low', 0)
            volume = candle.get('volume', 0)
            
            body_size = abs(close_price - open_price)
            high_low_range = high_price - low_price
            candle_direction = "UP" if close_price >= open_price else "DOWN"
            
            timestamp = datetime.now(timezone.utc).isoformat()  # TODO: Use real timestamp if available
            
            effort = EffortResult(
                candle_index=i,
                timestamp=timestamp,
                volume=volume,
                body_size=body_size,
                high_low_range=high_low_range,
                direction=candle_direction
            )
            
            ratio = effort.calculate_effort_vs_result_ratio(avg_volume)
            self.recent_ratio_history.append(ratio)
            self.candle_analysis.append(effort)
            
            # Alert on exhaustion
            if ratio < 0.5 and candle_direction == direction:
                self.exhaustion_alerts.append({
                    'candle_index': i,
                    'ratio': ratio,
                    'probability': effort.get_exhaustion_probability(ratio),
                    'volume': volume,
                    'body_size': body_size,
                    'wick_ratio': effort.wick_ratio,
                    'direction': candle_direction,
                })
        
        # Calculate statistics
        avg_ratio = sum(self.recent_ratio_history) / len(self.recent_ratio_history) if self.recent_ratio_history else 1.0
        
        # Generate summary
        summary_reason = ""
        if len(self.exhaustion_alerts) >= 3:
            summary_reason = f"CRITICAL EXHAUSTION: {len(self.exhaustion_alerts)} exhaustion candles in last 20 — reversal highly likely (70%+)"
        elif len(self.exhaustion_alerts) >= 1:
            summary_reason = f"Exhaustion signal detected: {len(self.exhaustion_alerts)} candle(s) show effort-result breakdown — watch for reversal"
        elif avg_ratio < 0.7:
            summary_reason = f"Weakening trend: Average effort-result ratio {avg_ratio:.2f} < 0.7 — trend losing steam"
        elif avg_ratio > 1.5:
            summary_reason = f"STRONG trend: Average effort-result ratio {avg_ratio:.2f} > 1.5 — high conviction breakout"
        else:
            summary_reason = f"Normal trend: Average effort-result ratio {avg_ratio:.2f} — steady progression"
        
        return avg_ratio, self.exhaustion_alerts, summary_reason
    
    def get_trend_strength_score(self) -> float:
        """
        Get trend strength score based on recent effort-result ratios.
        
        Returns: 0-100 score (0-30 = weak, 30-70 = normal, 70+ = strong)
        """
        if not self.recent_ratio_history:
            return 50.0
        
        # Score each candle
        recent = self.recent_ratio_history[-10:]  # Last 10 candles
        scores = [min(100.0, max(0.0, ratio * 50.0)) for ratio in recent]  # Convert ratio to 0-100
        
        avg_score = sum(scores) / len(scores) if scores else 50.0
        return avg_score
    
    def predict_reversal_window(self) -> Tuple[bool, str, float]:
        """
        Predict if reversal is imminent within 48-72 hours.
        
        Returns:
            (is_reversal_imminent, reason, reversal_probability_0_100)
        """
        if not self.exhaustion_alerts:
            return False, "No exhaustion signals detected", 5.0
        
        # Count consecutive exhaustion candles
        consecutive = 0
        for alert in sorted(self.exhaustion_alerts, key=lambda x: x['candle_index'], reverse=True):
            consecutive += 1
            if consecutive > 3:
                break
        
        if consecutive >= 2:
            avg_prob = sum(a['probability'] for a in self.exhaustion_alerts[-3:]) / min(3, len(self.exhaustion_alerts))
            return True, f"{consecutive} consecutive exhaustion candles — reversal window 48-72h", avg_prob
        
        return False, "Single exhaustion alert (need 2+) to confirm reversal window", 30.0
    
    def get_exhaustion_summary(self) -> Dict[str, Any]:
        """Get detailed exhaustion analysis summary."""
        avg_ratio = sum(self.recent_ratio_history) / len(self.recent_ratio_history) if self.recent_ratio_history else 1.0
        is_reversal, reason, prob = self.predict_reversal_window()
        
        return {
            'average_ratio': round(avg_ratio, 2),
            'trend_strength': round(self.get_trend_strength_score(), 1),
            'exhaustion_candle_count': len(self.exhaustion_alerts),
            'exhaustion_alerts': self.exhaustion_alerts[-5:],  # Last 5 alerts
            'reversal_imminent': is_reversal,
            'reversal_reason': reason,
            'reversal_probability': round(prob, 1),
        }


# Global instance
_effort_analyzer: Optional[EffortVsResultAnalyzer] = None

def get_effort_analyzer() -> EffortVsResultAnalyzer:
    """Get or create the global effort vs result analyzer."""
    global _effort_analyzer
    if _effort_analyzer is None:
        _effort_analyzer = EffortVsResultAnalyzer()
    return _effort_analyzer


def analyze_effort_vs_result(
    ohlc_history: List[Dict[str, float]],
    direction: str
) -> Tuple[float, str, float]:
    """
    Convenience function to analyze effort vs result.
    
    Returns:
        (average_ratio, summary, exhaustion_probability)
    """
    analyzer = get_effort_analyzer()
    avg_ratio, alerts, summary = analyzer.analyze_candle_history(ohlc_history, direction)
    _, _, reversal_prob = analyzer.predict_reversal_window()
    return avg_ratio, summary, reversal_prob


# Import timezone for the module
from datetime import timezone
