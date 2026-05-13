"""
Volume Profile Point of Control (POC) Analysis Module
Identifies where institutions traded the most volume and uses these levels as price magnets/rejections.

Core Concepts:
1. POINT OF CONTROL (POC): Price level with highest trading volume (most institution activity)
2. VALUE AREA: Price range containing 70% of volume (core trading zone)
3. HIGH VOLUME NODES: Levels where price was rejected (heavy institution selling/buying)
4. GAP ZONES: Price areas with low volume (likely to be filled quickly)
5. POC MAGNET: Current price will be drawn back to POC over time

Strategy:
- Trading against POC = lower probability (going against institution activity)
- POC support/resistance = strong levels
- Gap zones above/below = likely price rotation targets
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)


class VolumeNode:
    """Represents a price level with associated volume."""
    
    def __init__(self, price: float, volume: float):
        self.price = price
        self.volume = volume
        self.test_count = 1  # Number of times price touched this level


class VolumeProfile:
    """Represents volume profile for a given price range."""
    
    PRICE_BUCKET_SIZE = 5.0  # Group prices into 5-point buckets (for XAUUSD)
    
    def __init__(self):
        """Initialize volume profile."""
        self.nodes: Dict[float, VolumeNode] = {}  # price -> VolumeNode
        self.total_volume = 0.0
        self.poc_price = 0.0  # Point of Control
        self.value_area_high = 0.0
        self.value_area_low = 0.0
    
    def add_candle(self, high: float, low: float, close: float, volume: float) -> None:
        """
        Add a candle's volume to the profile.
        
        Args:
            high: Candle high price
            low: Candle low price
            close: Candle close price
            volume: Candle volume
        """
        # Distribute volume across the range with emphasis on close price
        range_size = high - low
        if range_size <= 0:
            # No range - assign all volume to close price
            self._add_volume_to_level(close, volume)
        else:
            # Distribute volume across the range
            num_points = max(1, int(range_size / self.PRICE_BUCKET_SIZE))
            volume_per_point = volume / num_points
            
            for i in range(num_points):
                level_price = low + (i * self.PRICE_BUCKET_SIZE)
                # Emphasize close price
                if abs(level_price - close) < self.PRICE_BUCKET_SIZE / 2:
                    self._add_volume_to_level(level_price, volume_per_point * 1.5)
                else:
                    self._add_volume_to_level(level_price, volume_per_point)
    
    def _add_volume_to_level(self, price: float, volume: float) -> None:
        """Add volume to a specific price level."""
        # Round to bucket size
        bucket_price = round(price / self.PRICE_BUCKET_SIZE) * self.PRICE_BUCKET_SIZE
        
        if bucket_price not in self.nodes:
            self.nodes[bucket_price] = VolumeNode(bucket_price, volume)
        else:
            self.nodes[bucket_price].volume += volume
        
        self.total_volume += volume
    
    def calculate_profile_levels(self) -> None:
        """Calculate POC and value area from profile."""
        if not self.nodes:
            return
        
        # Find Point of Control (highest volume node)
        max_node = max(self.nodes.values(), key=lambda x: x.volume)
        self.poc_price = max_node.price
        
        # Calculate Value Area (70% of volume)
        sorted_nodes = sorted(self.nodes.values(), key=lambda x: x.volume, reverse=True)
        cumulative_volume = 0.0
        value_area_nodes = []
        
        for node in sorted_nodes:
            cumulative_volume += node.volume
            value_area_nodes.append(node)
            if cumulative_volume >= self.total_volume * 0.70:  # 70% of volume
                break
        
        if value_area_nodes:
            prices = [n.price for n in value_area_nodes]
            self.value_area_low = min(prices)
            self.value_area_high = max(prices)
    
    def get_poc_strength(self) -> float:
        """
        Get strength of POC (0-100%).
        
        Strength indicators:
        - POC node contains >20% of volume = 80%+ strength
        - POC node contains >15% = 60%+
        - POC node contains >10% = 40%+
        """
        if self.total_volume <= 0:
            return 0.0
        
        poc_node = self.nodes.get(self.poc_price)
        if not poc_node:
            return 0.0
        
        poc_percentage = (poc_node.volume / self.total_volume) * 100.0
        
        if poc_percentage > 20:
            return 85.0 + min(15.0, (poc_percentage - 20) * 0.5)  # 85-100%
        elif poc_percentage > 15:
            return 70.0 + (poc_percentage - 15) * 2.0  # 70-80%
        elif poc_percentage > 10:
            return 50.0 + (poc_percentage - 10) * 4.0  # 50-70%
        else:
            return 20.0 + poc_percentage * 2.0  # 20-40%
    
    def get_profile_summary(self) -> Dict[str, Any]:
        """Get volume profile summary."""
        self.calculate_profile_levels()
        
        return {
            'poc_price': round(self.poc_price, 2),
            'poc_strength': round(self.get_poc_strength(), 1),
            'value_area_low': round(self.value_area_low, 2),
            'value_area_high': round(self.value_area_high, 2),
            'value_area_width': round(self.value_area_high - self.value_area_low, 2),
            'total_volume': round(self.total_volume, 0),
            'num_price_nodes': len(self.nodes),
        }


class VolumeProfileAnalyzer:
    """Analyzes volume profiles to identify POC-based trading opportunities."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.daily_profile: Optional[VolumeProfile] = None
        self.weekly_profile: Optional[VolumeProfile] = None
    
    def build_profile_from_candles(
        self,
        ohlc_candles: List[Dict[str, float]],
        period_name: str = "custom"
    ) -> VolumeProfile:
        """
        Build volume profile from OHLC candles.
        
        Args:
            ohlc_candles: List of OHLC dictionaries
            period_name: Name of the period (e.g., "daily", "weekly")
        
        Returns: VolumeProfile object
        """
        profile = VolumeProfile()
        
        for candle in ohlc_candles:
            high = candle.get('high', 0)
            low = candle.get('low', 0)
            close = candle.get('close', 0)
            volume = candle.get('volume', 0)
            
            if high > 0 and volume > 0:
                profile.add_candle(high, low, close, volume)
        
        profile.calculate_profile_levels()
        return profile
    
    def analyze_price_vs_poc(
        self,
        current_price: float,
        profile: VolumeProfile
    ) -> Dict[str, Any]:
        """
        Analyze current price relationship to POC.
        
        Returns:
            Dictionary with distance, alignment, and magnet information
        """
        if profile.poc_price <= 0:
            return {'error': 'No POC calculated'}
        
        distance_to_poc = current_price - profile.poc_price
        distance_pct = (distance_to_poc / profile.poc_price) * 100.0 if profile.poc_price > 0 else 0
        
        # Determine alignment
        if abs(distance_to_poc) < 10.0:  # Within 10 pts of POC
            alignment = "AT_POC"
            alignment_strength = 80.0
        elif distance_to_poc > 0 and distance_to_poc < 50.0:  # Above POC
            alignment = "ABOVE_POC"
            alignment_strength = 50.0 + (50.0 - distance_to_poc / 50.0 * 50.0)
        elif distance_to_poc < 0 and distance_to_poc > -50.0:  # Below POC
            alignment = "BELOW_POC"
            alignment_strength = 50.0 + (50.0 - abs(distance_to_poc) / 50.0 * 50.0)
        elif distance_to_poc > 50.0:
            alignment = "FAR_ABOVE_POC"
            alignment_strength = 20.0  # Likely to be pulled back
        else:
            alignment = "FAR_BELOW_POC"
            alignment_strength = 20.0  # Likely to be pulled back
        
        return {
            'current_price': round(current_price, 2),
            'poc_price': round(profile.poc_price, 2),
            'distance_to_poc': round(distance_to_poc, 2),
            'distance_pct': round(distance_pct, 3),
            'alignment': alignment,
            'poc_magnet_strength': round(alignment_strength, 1),
            'poc_overall_strength': round(profile.get_poc_strength(), 1),
            'summary': f"Price {alignment} POC by {abs(distance_to_poc):.0f}pts — Magnet strength {alignment_strength:.0f}%"
        }
    
    def identify_gap_zones(
        self,
        profile: VolumeProfile,
        gap_threshold: float = 0.3  # 30% below average volume
    ) -> List[Dict[str, float]]:
        """
        Identify low-volume gap zones (likely to be filled quickly).
        
        Args:
            profile: VolumeProfile object
            gap_threshold: Percentage threshold for gap detection
        
        Returns: List of gap zones with price ranges
        """
        if not profile.nodes:
            return []
        
        avg_volume = profile.total_volume / len(profile.nodes)
        gap_threshold_vol = avg_volume * gap_threshold
        
        gaps = []
        sorted_nodes = sorted(profile.nodes.items(), key=lambda x: x[0])
        gap_start = None
        
        for price, node in sorted_nodes:
            if node.volume < gap_threshold_vol:
                if gap_start is None:
                    gap_start = price
            else:
                if gap_start is not None:
                    gaps.append({
                        'low': gap_start,
                        'high': price,
                        'width': price - gap_start,
                    })
                    gap_start = None
        
        return gaps


def analyze_volume_profile_at_price(
    ohlc_history: List[Dict[str, float]],
    current_price: float
) -> Dict[str, Any]:
    """
    Convenience function to analyze volume profile at current price.
    
    Returns:
        Dictionary with POC info, alignment, and trading implications
    """
    analyzer = VolumeProfileAnalyzer()
    profile = analyzer.build_profile_from_candles(ohlc_history, "analysis")
    analysis = analyzer.analyze_price_vs_poc(current_price, profile)
    
    return {
        'profile_summary': profile.get_profile_summary(),
        'price_analysis': analysis,
        'gap_zones': analyzer.identify_gap_zones(profile),
    }
