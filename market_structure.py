"""
Market Structure Database Module
Maintains 20-day running chart with structural levels, test counting, and break probability prediction.

Core Concepts:
1. STRUCTURAL LEVELS: Key support/resistance zones identified by multiple touches
2. TEST COUNTING: Number of times price has tested a level (5+ = STRONG, 2-3 = WEAK, 1 = RANDOM)
3. STRUCTURAL STRENGTH: Probability that price will hold/bounce at this level
4. BREAK PROBABILITY: Likelihood that price will break through this level
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any
from datetime import datetime, timedelta
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class StructuralLevel:
    """Represents a single structural level (support or resistance)."""
    
    def __init__(self, level_price: float, level_type: str, first_touch_time: str):
        """
        Args:
            level_price: The price level
            level_type: "SUPPORT" or "RESISTANCE"
            first_touch_time: ISO timestamp of first touch
        """
        self.price = level_price
        self.type = level_type
        self.first_touch_time = first_touch_time
        self.touches = 1
        self.last_touch_time = first_touch_time
        self.last_touch_distance = 0.0  # Price distance from level at last touch
        self.break_count = 0  # Number of times price broke through this level
        self.intrabar_spike_count = 0  # Number of times price spiked through briefly then retracted
        self.rejection_count = 0  # Number of times price rejected at level
        
    def register_touch(self, current_price: float, current_time: str) -> None:
        """Register a new touch at this level."""
        self.touches += 1
        self.last_touch_time = current_time
        self.last_touch_distance = abs(current_price - self.price)
        
    def register_break(self) -> None:
        """Register a break through this level."""
        self.break_count += 1
        
    def register_rejection(self) -> None:
        """Register price rejection at this level."""
        self.rejection_count += 1
        
    def get_structural_strength(self) -> float:
        """
        Calculate structural strength (0-100%).
        - 5+ touches = STRONG (85-100%)
        - 3-4 touches = MEDIUM (60-85%)
        - 2 touches = WEAK (35-60%)
        - 1 touch = RANDOM (10-35%)
        """
        if self.touches >= 5:
            # Strong level: 85-100% based on rejection vs break ratio
            rejection_ratio = self.rejection_count / max(1, self.rejection_count + self.break_count)
            return 85.0 + (rejection_ratio * 15.0)
        elif self.touches == 4:
            return 70.0 + (self.rejection_count * 5.0)
        elif self.touches == 3:
            return 60.0 + (self.rejection_count * 5.0)
        elif self.touches == 2:
            return 45.0 + (self.rejection_count * 10.0)
        else:  # 1 touch
            return 25.0 + (self.rejection_count * 10.0)
    
    def get_break_probability(self) -> float:
        """
        Calculate probability that price will break through this level (0-100%).
        - High break history + low touch count = HIGH probability (70-100%)
        - Low break history + high rejection = LOW probability (0-30%)
        """
        if self.touches == 0:
            return 50.0  # Unknown
        
        total_interactions = self.rejection_count + self.break_count
        if total_interactions == 0:
            return 50.0  # Unknown
        
        break_ratio = self.break_count / total_interactions
        
        # Base: higher breaks = higher probability of future break
        base_prob = break_ratio * 100.0
        
        # Adjust based on touch count (more touches = less likely to break)
        if self.touches >= 5:
            base_prob *= 0.4  # Strong level - reduces break probability
        elif self.touches >= 3:
            base_prob *= 0.6  # Medium level
        else:
            base_prob *= 0.9  # Weak level - more likely to break
        
        return min(100.0, max(0.0, base_prob))
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            'price': self.price,
            'type': self.type,
            'first_touch_time': self.first_touch_time,
            'touches': self.touches,
            'last_touch_time': self.last_touch_time,
            'last_touch_distance': self.last_touch_distance,
            'break_count': self.break_count,
            'intrabar_spike_count': self.intrabar_spike_count,
            'rejection_count': self.rejection_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StructuralLevel:
        """Deserialize from dictionary."""
        level = cls(data['price'], data['type'], data['first_touch_time'])
        level.touches = data.get('touches', 1)
        level.last_touch_time = data.get('last_touch_time', data['first_touch_time'])
        level.last_touch_distance = data.get('last_touch_distance', 0.0)
        level.break_count = data.get('break_count', 0)
        level.intrabar_spike_count = data.get('intrabar_spike_count', 0)
        level.rejection_count = data.get('rejection_count', 0)
        return level


class MarketStructureDatabase:
    """Maintains 20-day running market structure with levels, tests, and break predictions."""
    
    DB_FILE = "market_structure_db.json"
    MAX_LEVELS = 10  # Track top 10 S/R levels
    TOUCH_TOLERANCE = 5.0  # Price tolerance for registering a touch (5 cents for gold)
    MIN_LEVEL_SEPARATION = 30.0  # Minimum separation between levels (prevent clustering)
    
    def __init__(self):
        """Initialize the market structure database."""
        self.support_levels: Dict[float, StructuralLevel] = {}
        self.resistance_levels: Dict[float, StructuralLevel] = {}
        self.load_from_disk()
    
    def identify_structural_levels(
        self,
        recent_ohlc: List[Dict[str, float]],
        current_price: float,
        current_time: str
    ) -> None:
        """
        Identify structural levels from recent price action.
        
        Algorithm:
        1. Find local highs and lows (peaks and valleys)
        2. Group by price proximity (tolerance window)
        3. Register touches on current price
        
        Args:
            recent_ohlc: List of OHLC candles (last 250 candles)
            current_price: Current market price
            current_time: ISO timestamp
        """
        if len(recent_ohlc) < 5:
            return
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 1: Find local highs (resistance) from last 250 candles
        # ═══════════════════════════════════════════════════════════════
        resistance_peaks = []
        for i in range(2, len(recent_ohlc) - 2):
            candle = recent_ohlc[i]
            high = candle.get('high', 0)
            prev_high = recent_ohlc[i - 1].get('high', 0)
            next_high = recent_ohlc[i + 1].get('high', 0)
            
            # Local high: higher than surrounding candles
            if high > prev_high and high > next_high and high > recent_ohlc[i - 2].get('high', 0):
                resistance_peaks.append(high)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 2: Find local lows (support) from last 250 candles
        # ═══════════════════════════════════════════════════════════════
        support_valleys = []
        for i in range(2, len(recent_ohlc) - 2):
            candle = recent_ohlc[i]
            low = candle.get('low', 0)
            prev_low = recent_ohlc[i - 1].get('low', 0)
            next_low = recent_ohlc[i + 1].get('low', 0)
            
            # Local low: lower than surrounding candles
            if low < prev_low and low < next_low and low < recent_ohlc[i - 2].get('low', 0):
                support_valleys.append(low)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 3: Cluster peaks/valleys into levels (group by tolerance)
        # ═══════════════════════════════════════════════════════════════
        resistance_clustered = self._cluster_levels(resistance_peaks)
        support_clustered = self._cluster_levels(support_valleys)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 4: Register new levels or update existing ones
        # ═══════════════════════════════════════════════════════════════
        for level_price in resistance_clustered:
            self._register_or_update_level(
                level_price, "RESISTANCE", current_price, current_time
            )
        
        for level_price in support_clustered:
            self._register_or_update_level(
                level_price, "SUPPORT", current_price, current_time
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 5: Prune old levels (older than 20 days)
        # ═══════════════════════════════════════════════════════════════
        cutoff_time = datetime.fromisoformat(current_time) - timedelta(days=20)
        cutoff_iso = cutoff_time.isoformat()
        self._prune_old_levels(cutoff_iso)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 6: Keep only top levels (by strength), max MAX_LEVELS
        # ═══════════════════════════════════════════════════════════════
        self._keep_top_levels()
    
    def _cluster_levels(self, prices: List[float], tolerance: float = None) -> List[float]:
        """
        Cluster nearby price levels into single levels.
        
        Returns: List of representative prices for each cluster
        """
        if not prices:
            return []
        
        if tolerance is None:
            tolerance = self.TOUCH_TOLERANCE
        
        sorted_prices = sorted(prices)
        clusters = []
        current_cluster = [sorted_prices[0]]
        
        for price in sorted_prices[1:]:
            if abs(price - current_cluster[-1]) <= tolerance:
                current_cluster.append(price)
            else:
                # New cluster - save average of current cluster
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [price]
        
        # Save last cluster
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))
        
        # Filter clusters that are too close together
        filtered = []
        for level in sorted(clusters):
            if not filtered or abs(level - filtered[-1]) >= self.MIN_LEVEL_SEPARATION:
                filtered.append(level)
        
        return filtered
    
    def _register_or_update_level(
        self,
        level_price: float,
        level_type: str,
        current_price: float,
        current_time: str
    ) -> None:
        """Register a new level or update an existing one."""
        
        target_dict = self.resistance_levels if level_type == "RESISTANCE" else self.support_levels
        
        # Check if a level already exists near this price
        existing_key = None
        for key in target_dict.keys():
            if abs(key - level_price) <= self.TOUCH_TOLERANCE:
                existing_key = key
                break
        
        if existing_key:
            # Update existing level
            target_dict[existing_key].register_touch(current_price, current_time)
        else:
            # Create new level
            new_level = StructuralLevel(level_price, level_type, current_time)
            target_dict[level_price] = new_level
        
        # Check if current price is near this level (register rejection or break)
        if abs(current_price - level_price) <= self.TOUCH_TOLERANCE * 2:
            level = target_dict.get(existing_key or level_price)
            if level_type == "RESISTANCE" and current_price < level_price:
                level.register_rejection()
            elif level_type == "SUPPORT" and current_price > level_price:
                level.register_rejection()
    
    def _prune_old_levels(self, cutoff_iso: str) -> None:
        """Remove levels older than 20 days."""
        
        for level_dict in [self.support_levels, self.resistance_levels]:
            keys_to_remove = []
            for key, level in level_dict.items():
                if level.first_touch_time < cutoff_iso:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del level_dict[key]
    
    def _keep_top_levels(self) -> None:
        """Keep only top structural levels by strength."""
        
        # Sort support levels by strength
        support_sorted = sorted(
            self.support_levels.items(),
            key=lambda x: x[1].get_structural_strength(),
            reverse=True
        )
        self.support_levels = dict(support_sorted[:self.MAX_LEVELS])
        
        # Sort resistance levels by strength
        resistance_sorted = sorted(
            self.resistance_levels.items(),
            key=lambda x: x[1].get_structural_strength(),
            reverse=True
        )
        self.resistance_levels = dict(resistance_sorted[:self.MAX_LEVELS])
    
    def get_support_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all support levels with strength and break probability."""
        summary = []
        for price, level in sorted(self.support_levels.items(), reverse=True):
            summary.append({
                'price': round(price, 2),
                'touches': level.touches,
                'strength': round(level.get_structural_strength(), 1),
                'break_prob': round(level.get_break_probability(), 1),
                'last_touch': level.last_touch_time,
            })
        return summary
    
    def get_resistance_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all resistance levels with strength and break probability."""
        summary = []
        for price, level in sorted(self.resistance_levels.items()):
            summary.append({
                'price': round(price, 2),
                'touches': level.touches,
                'strength': round(level.get_structural_strength(), 1),
                'break_prob': round(level.get_break_probability(), 1),
                'last_touch': level.last_touch_time,
            })
        return summary
    
    def get_nearest_structure(self, current_price: float, direction: str) -> Tuple[float, float]:
        """
        Get nearest structural level in the given direction.
        
        Args:
            current_price: Current market price
            direction: "UP" for nearest resistance, "DOWN" for nearest support
        
        Returns:
            (level_price, strength_0_100)
        """
        if direction == "UP":
            resistances = sorted(
                [p for p in self.resistance_levels.keys() if p > current_price]
            )
            if resistances:
                nearest = resistances[0]
                level = self.resistance_levels[nearest]
                return (nearest, level.get_structural_strength())
        else:  # DOWN
            supports = sorted(
                [p for p in self.support_levels.keys() if p < current_price],
                reverse=True
            )
            if supports:
                nearest = supports[0]
                level = self.support_levels[nearest]
                return (nearest, level.get_structural_strength())
        
        return (0.0, 0.0)
    
    def save_to_disk(self) -> None:
        """Persist database to JSON file."""
        data = {
            'support_levels': {
                str(price): level.to_dict()
                for price, level in self.support_levels.items()
            },
            'resistance_levels': {
                str(price): level.to_dict()
                for price, level in self.resistance_levels.items()
            },
            'last_updated': datetime.now().isoformat(),
        }
        
        try:
            with open(self.DB_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save market structure database: {e}")
    
    def load_from_disk(self) -> None:
        """Load database from JSON file."""
        if not Path(self.DB_FILE).exists():
            return
        
        try:
            with open(self.DB_FILE, 'r') as f:
                data = json.load(f)
            
            self.support_levels = {
                float(price): StructuralLevel.from_dict(level_data)
                for price, level_data in data.get('support_levels', {}).items()
            }
            
            self.resistance_levels = {
                float(price): StructuralLevel.from_dict(level_data)
                for price, level_data in data.get('resistance_levels', {}).items()
            }
        except Exception as e:
            logger.error(f"Failed to load market structure database: {e}")


# Global instance
_market_structure_db: MarketStructureDatabase = None

def get_market_structure_database() -> MarketStructureDatabase:
    """Get or create the global market structure database."""
    global _market_structure_db
    if _market_structure_db is None:
        _market_structure_db = MarketStructureDatabase()
    return _market_structure_db
