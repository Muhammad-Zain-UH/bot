"""Cumulative Volume Delta (CVD) divergence detector for entry confirmation."""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug

def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_cvd(data: pd.DataFrame) -> pd.Series:
    """Calculate Cumulative Volume Delta (CVD).
    
    CVD = Cumulative sum of (close > open ? volume : -volume)
    
    Shows whether volume is accumulating on up closes (bullish) or down closes (bearish).
    
    Args:
        data: DataFrame with columns: open, close, volume (tick_volume)
    
    Returns:
        Pandas Series of CVD values
    """
    try:
        if len(data) == 0:
            return pd.Series(dtype=float)
        
        # Determine direction: +1 if close > open, -1 if close <= open
        direction = (data['close'] > data['open']).astype(int) * 2 - 1
        
        # Volume delta = direction * volume
        delta = direction * data['tick_volume'].fillna(0)
        
        # Cumulative sum
        cvd = delta.cumsum()
        
        return cvd
    except Exception as exc:
        log_debug(f"CVD calculation error: {exc}")
        return pd.Series(dtype=float)


def detect_cvd_divergence(price_data: pd.DataFrame, lookback: int = 20) -> dict[str, Any]:
    """Detect divergence between price and CVD.
    
    BULLISH DIVERGENCE (for BUY setups):
    - Price makes a new 5-minute low
    - CVD makes a HIGHER low (volume didn't follow price down)
    - Indicates selling pressure is weak → bullish reversal likely
    
    BEARISH DIVERGENCE (for SELL setups):
    - Price makes a new 5-minute high
    - CVD makes a LOWER high (volume didn't follow price up)
    - Indicates buying pressure is weak → bearish reversal likely
    
    Args:
        price_data: DataFrame with OHLCV data
        lookback: Number of candles to check for divergence
    
    Returns:
        {
            "has_divergence": bool,
            "type": "bullish" | "bearish" | "none",
            "price_new_low": float or None,
            "price_new_high": float or None,
            "cvd_at_price_low": float or None,
            "cvd_at_price_high": float or None,
            "confidence_adjustment": float,
        }
    """
    try:
        if len(price_data) < lookback + 2:
            return {
                "has_divergence": False,
                "type": "none",
                "reason": "Insufficient data for divergence detection",
                "confidence_adjustment": 0.0,
            }
        
        frame = price_data.reset_index(drop=True).copy()
        cvd = calculate_cvd(frame).reset_index(drop=True)

        recent_price = frame.iloc[-lookback:]
        recent_cvd = cvd.iloc[-lookback:]

        recent_5 = frame.iloc[-5:]
        prev_15 = frame.iloc[-lookback:-5]

        recent_5_low = _to_float(recent_5["low"].min())
        prev_15_low = _to_float(prev_15["low"].min()) if len(prev_15) > 0 else None
        recent_5_high = _to_float(recent_5["high"].max())
        prev_15_high = _to_float(prev_15["high"].max()) if len(prev_15) > 0 else None

        is_new_low = prev_15_low is not None and recent_5_low is not None and recent_5_low < prev_15_low
        is_new_high = prev_15_high is not None and recent_5_high is not None and recent_5_high > prev_15_high

        price_low_idx = int(recent_price["low"].idxmin())
        price_high_idx = int(recent_price["high"].idxmax())

        cvd_at_low = _to_float(cvd.iloc[price_low_idx]) if 0 <= price_low_idx < len(cvd) else None
        cvd_at_high = _to_float(cvd.iloc[price_high_idx]) if 0 <= price_high_idx < len(cvd) else None

        recent_delta = cvd.diff().fillna(0.0)
        bullish_confirmation = len(recent_delta) >= 2 and (recent_delta.iloc[-2:] > 0).all()
        bearish_confirmation = len(recent_delta) >= 2 and (recent_delta.iloc[-2:] < 0).all()

        # BULLISH divergence: price new low, but CVD is rising on two consecutive bars
        has_bullish_div = False
        if is_new_low and cvd_at_low is not None and prev_15_low is not None:
            prev_lows_cvd = cvd.iloc[max(0, price_low_idx - 10):price_low_idx]
            if len(prev_lows_cvd) > 0:
                has_bullish_div = cvd_at_low > prev_lows_cvd.min() and bullish_confirmation

        # BEARISH divergence: price new high, but CVD is falling on two consecutive bars
        has_bearish_div = False
        if is_new_high and cvd_at_high is not None and prev_15_high is not None:
            prev_highs_cvd = cvd.iloc[max(0, price_high_idx - 10):price_high_idx]
            if len(prev_highs_cvd) > 0:
                has_bearish_div = cvd_at_high < prev_highs_cvd.max() and bearish_confirmation
        
        result = {
            "has_divergence": has_bullish_div or has_bearish_div,
            "type": "bullish" if has_bullish_div else "bearish" if has_bearish_div else "none",
            "price_new_low": float(recent_5_low) if is_new_low else None,
            "price_new_high": float(recent_5_high) if is_new_high else None,
            "cvd_at_price_low": cvd_at_low,
            "cvd_at_price_high": cvd_at_high,
            "confidence_adjustment": 8.0 if (has_bullish_div or has_bearish_div) else 0.0,
        }
        
        if result["has_divergence"]:
            log_debug(
                f"[CVD DIVERGENCE] {result['type'].upper()}: "
                f"Price new {'low' if has_bullish_div else 'high'} but CVD showing "
                f"{'strength' if has_bullish_div else 'weakness'} → +8% confidence"
            )
        
        return result
        
    except Exception as exc:
        log_debug(f"CVD divergence detection error: {exc}")
        return {
            "has_divergence": False,
            "type": "none",
            "reason": f"Error: {exc}",
            "confidence_adjustment": 0.0,
        }


def get_cvd_summary(cvd_series: pd.Series, lookback: int = 5) -> str:
    """Format CVD trend for logging."""
    if len(cvd_series) < lookback:
        return "Insufficient CVD data"
    
    recent = cvd_series.iloc[-lookback:]
    trend = "↑" if recent.iloc[-1] > recent.iloc[0] else "↓"
    current = recent.iloc[-1]
    
    return f"[CVD {trend}] Current: {current:.0f}"
