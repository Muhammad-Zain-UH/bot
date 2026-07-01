"""LAYER 3: M15 PULLBACK PHASE DETECTOR - Identifies retracement opportunities.

Pullback Detection Rules for XAUUSD:

IN BULLISH BIAS:
- M15 closes turn from bullish to bearish (EMA20 cross below EMA50)
- M15 printing LH/LL temporarily (reversal phase)
- Volume on down candles < volume on up candles (weak selling)
- Pullback depth ≤ 0.618 fib of last bullish move (not too deep)

IN BEARISH BIAS:
- M15 closes turn from bearish to bullish temporarily
- M15 printing HH/HL temporarily
- Volume on up candles < volume on down candles (weak buying)
- Pullback depth ≤ 0.618 fib of last bearish move

PULLBACK QUALITY SCORING (0-10):
- Ideal pullback zone (38%-62% retracement): highest score
- Structure confirmation (LH/LL or HH/HL against the bias): required for a strong score
- Volume contracting into the pullback: adds confidence
- RSI stretched into the opposite extreme: adds confidence
"""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug
try:
    from indicators import calculate_indicators
except Exception:  # pragma: no cover - optional runtime fallback
    calculate_indicators = None


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_m15_rsi(m15_frame: pd.DataFrame) -> float | None:
    """Extract a real RSI reading from the M15 frame, computing it if needed."""
    if m15_frame is None or m15_frame.empty:
        return None

    last_row = m15_frame.iloc[-1]
    for key in ("rsi", "rsi_14"):
        rsi_value = _to_float(last_row.get(key))
        if rsi_value is not None:
            return rsi_value

    if callable(calculate_indicators):
        frame_for_indicators = m15_frame.copy()
        if "time" not in frame_for_indicators.columns:
            frame_for_indicators["time"] = pd.date_range(
                end=pd.Timestamp.now(tz="UTC"),
                periods=len(frame_for_indicators),
                freq="15min",
            )
        indicators = calculate_indicators(frame_for_indicators)
        return _to_float(indicators.get("rsi_14"))

    return None


def _estimate_recent_atr(recent: pd.DataFrame, default: float = 10.0) -> float:
    """Estimate ATR from true range so the pullback gate is less noisy."""
    try:
        if recent is None or recent.empty:
            return default
        if not all(col in recent.columns for col in ("high", "low", "close")):
            return default

        frame = recent[["high", "low", "close"]].astype(float).copy()
        prev_close = frame["close"].shift(1)
        true_range = pd.concat(
            [
                frame["high"] - frame["low"],
                (frame["high"] - prev_close).abs(),
                (frame["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_series = true_range.rolling(14, min_periods=3).mean()
        atr_value = _to_float(atr_series.iloc[-1]) if len(atr_series) > 0 else None
        return atr_value if atr_value is not None and atr_value > 0 else default
    except Exception:
        return default


def _find_recent_fractal_swing(recent: pd.DataFrame, swing_type: str) -> tuple[int | None, float | None]:
    """Find the most recent confirmed fractal swing high/low."""
    if recent is None or len(recent) < 5:
        return None, None

    swing_type = swing_type.upper()
    column = "high" if swing_type == "HIGH" else "low"
    if column not in recent.columns:
        return None, None

    for i in range(len(recent) - 3, 1, -1):
        center = _to_float(recent.iloc[i][column])
        left_1 = _to_float(recent.iloc[i - 1][column])
        left_2 = _to_float(recent.iloc[i - 2][column])
        right_1 = _to_float(recent.iloc[i + 1][column])
        right_2 = _to_float(recent.iloc[i + 2][column])
        if None in (center, left_1, left_2, right_1, right_2):
            continue
        if swing_type == "HIGH" and center > left_1 and center > left_2 and center > right_1 and center > right_2:
            return i, center
        if swing_type == "LOW" and center < left_1 and center < left_2 and center < right_1 and center < right_2:
            return i, center

    fallback_idx = int(recent[column].idxmax() if swing_type == "HIGH" else recent[column].idxmin())
    fallback_value = _to_float(recent.iloc[fallback_idx][column])
    return fallback_idx, fallback_value


def _structure_confirmation(window: pd.DataFrame, direction: str) -> tuple[bool, str]:
    """Check whether the pullback window is printing counter-trend structure."""
    if window is None or len(window) < 3:
        return False, "Not enough candles for structure confirmation"
    if not all(col in window.columns for col in ("high", "low")):
        return False, "Missing OHLC data for structure confirmation"

    highs = window["high"].astype(float).tolist()
    lows = window["low"].astype(float).tolist()
    if len(highs) < 2 or len(lows) < 2:
        return False, "Not enough candles for structure confirmation"

    if direction == "BULLISH":
        lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
        lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])
        threshold = max(2, min(4, len(window) // 2))
        confirmed = lower_highs >= threshold or lower_lows >= threshold
        return confirmed, f"LH={lower_highs}, LL={lower_lows}, threshold={threshold}"

    if direction == "BEARISH":
        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
        threshold = max(2, min(4, len(window) // 2))
        confirmed = higher_highs >= threshold or higher_lows >= threshold
        return confirmed, f"HH={higher_highs}, HL={higher_lows}, threshold={threshold}"

    return False, "Invalid direction"


def _volume_context(window: pd.DataFrame) -> tuple[str, bool]:
    """Classify pullback volume as declining, stable, or rising."""
    if window is None or len(window) < 3 or "tick_volume" not in window.columns:
        return "stable", False

    volumes = window["tick_volume"].fillna(0).astype(float).tolist()
    sample = min(3, len(volumes))
    first_avg = sum(volumes[:sample]) / sample
    last_avg = sum(volumes[-sample:]) / sample

    if last_avg < first_avg * 0.9:
        return "declining", False
    if last_avg > first_avg * 1.1:
        return "rising", True
    return "stable", False


def calculate_fib_levels(swing_high: float, swing_low: float) -> dict[str, float]:
    """Calculate Fibonacci retracement levels."""
    diff = abs(swing_high - swing_low)
    return {
        "0.236": swing_low + (diff * 0.236),
        "0.382": swing_low + (diff * 0.382),
        "0.500": swing_low + (diff * 0.500),
        "0.618": swing_low + (diff * 0.618),
        "0.786": swing_low + (diff * 0.786),
    }


def detect_m15_pullback(
    m15_data: pd.DataFrame,
    expected_bias: str,
    lookback: int = 50,
) -> dict[str, Any]:
    """
    Detect M15 pullback phase.
    
    Returns:
        {
            "pullback_detected": bool,
            "pullback_depth_fib": 0.236-0.786,
            "pullback_quality": 0.0-10.0,
            "pullback_duration": int,  # candles
            "volume_trend": "declining | stable | rising",
            "rsi_state": "overbought | oversold | neutral",
            "current_low": float,
            "current_high": float,
            "swing_point": float,
            "reasoning": str,
        }
    """
    try:
        if m15_data is None or len(m15_data) < 10:
            return {
                "pullback_detected": False,
                "pullback_depth_fib": None,
                "retracement_ratio": 0.0,
                "pullback_quality": 0.0,
                "pullback_duration": 0,
                "volume_trend": "unknown",
                "volume_warning": False,
                "rsi_state": "unknown",
                "rsi_value": None,
                "current_low": None,
                "current_high": None,
                "swing_point": None,
                "reasoning": "Insufficient M15 data",
            }

        recent = m15_data.tail(lookback).copy().reset_index(drop=True)
        closed = recent.iloc[:-1].copy() if len(recent) > 1 else recent.copy()
        if len(closed) < 10:
            return {
                "pullback_detected": False,
                "pullback_depth_fib": None,
                "retracement_ratio": 0.0,
                "pullback_quality": 0.0,
                "pullback_duration": 0,
                "volume_trend": "unknown",
                "volume_warning": False,
                "rsi_state": "unknown",
                "rsi_value": None,
                "current_low": None,
                "current_high": None,
                "swing_point": None,
                "reasoning": "Insufficient closed M15 candles",
            }

        # Use the latest closed candle so the detector is not whipsawed by a forming bar.
        current_close = _to_float(closed.iloc[-1]["close"])
        current_low = _to_float(closed.iloc[-1]["low"])
        current_high = _to_float(closed.iloc[-1]["high"])

        # Get EMA data if available.
        ema20 = _to_float(closed.iloc[-1].get("ema20"))
        ema50 = _to_float(closed.iloc[-1].get("ema50"))

        # Get RSI and volume.
        rsi = _get_m15_rsi(closed)
        current_volume = _to_float(closed.iloc[-1].get("tick_volume"))
        avg_volume = closed["tick_volume"].mean() if "tick_volume" in closed.columns else 0
        atr_val = _estimate_recent_atr(closed)

        # Find the most recent confirmed swing in the direction opposite the bias.
        if expected_bias == "BULLISH":
            swing_high_pos, swing_high = _find_recent_fractal_swing(closed, "HIGH")
            if swing_high is None:
                swing_high_pos = int(closed["high"].idxmax())
                swing_high = _to_float(closed.iloc[swing_high_pos]["high"])
            swing_low = _to_float(closed.iloc[: swing_high_pos + 1]["low"].min()) if swing_high_pos is not None and swing_high_pos >= 0 else _to_float(closed["low"].min())
            swing_point = swing_high

            impulse_range = max((swing_high or 0.0) - (swing_low or 0.0), 0.0)
            if impulse_range < atr_val * 1.2:
                return {
                    "pullback_detected": False,
                    "pullback_depth_fib": None,
                    "retracement_ratio": 0.0,
                    "pullback_quality": 0.0,
                    "pullback_duration": 0,
                    "volume_trend": "stable",
                    "volume_warning": False,
                    "rsi_state": "neutral",
                    "rsi_value": rsi,
                    "current_low": current_low,
                    "current_high": current_high,
                    "swing_point": swing_point,
                    "structure_confirmed": False,
                    "reasoning": f"No genuine impulse (range {impulse_range:.2f} < 1.2x ATR {atr_val:.2f})",
                }

            pullback_distance = max((swing_high or 0.0) - (current_low or 0.0), 0.0)
            pullback_percent = (pullback_distance / impulse_range) if impulse_range > 0 else 0.0

            pullback_window = closed.iloc[swing_high_pos + 1:] if swing_high_pos + 1 < len(closed) else closed.tail(1)
            if len(pullback_window) < 3:
                return {
                    "pullback_detected": False,
                    "pullback_depth_fib": None,
                    "retracement_ratio": round(pullback_percent, 3),
                    "pullback_quality": 0.0,
                    "pullback_duration": 0,
                    "volume_trend": "stable",
                    "volume_warning": False,
                    "rsi_state": "neutral",
                    "rsi_value": rsi,
                    "current_low": current_low,
                    "current_high": current_high,
                    "swing_point": swing_point,
                    "structure_confirmed": False,
                    "reasoning": f"Swing too recent ({len(pullback_window)} bars), waiting for structure",
                }

            structure_window = pullback_window.tail(min(10, len(pullback_window)))
            is_making_lh_ll, structure_reason = _structure_confirmation(structure_window, "BULLISH")
            volume_trend, volume_warning = _volume_context(pullback_window)

            # Bullish pullback likes a temporary dip in RSI.
            rsi_state = "oversold" if rsi is not None and rsi < 35 else ("overbought" if rsi is not None and rsi > 70 else "neutral")
            pullback_duration = max(0, len(closed) - 1 - swing_high_pos)
            
        else:  # BEARISH
            swing_low_pos, swing_low = _find_recent_fractal_swing(closed, "LOW")
            if swing_low is None:
                swing_low_pos = int(closed["low"].idxmin())
                swing_low = _to_float(closed.iloc[swing_low_pos]["low"])
            swing_high = _to_float(closed.iloc[: swing_low_pos + 1]["high"].max()) if swing_low_pos is not None and swing_low_pos >= 0 else _to_float(closed["high"].max())
            swing_point = swing_low

            impulse_range = max((swing_high or 0.0) - (swing_low or 0.0), 0.0)
            if impulse_range < atr_val * 1.2:
                return {
                    "pullback_detected": False,
                    "pullback_depth_fib": None,
                    "retracement_ratio": 0.0,
                    "pullback_quality": 0.0,
                    "pullback_duration": 0,
                    "volume_trend": "stable",
                    "volume_warning": False,
                    "rsi_state": "neutral",
                    "rsi_value": rsi,
                    "current_low": current_low,
                    "current_high": current_high,
                    "swing_point": swing_point,
                    "structure_confirmed": False,
                    "reasoning": f"No genuine impulse (range {impulse_range:.2f} < 1.2x ATR {atr_val:.2f})",
                }

            pullback_distance = max((current_high or 0.0) - (swing_low or 0.0), 0.0)
            pullback_percent = (pullback_distance / impulse_range) if impulse_range > 0 else 0.0

            pullback_window = closed.iloc[swing_low_pos + 1:] if swing_low_pos + 1 < len(closed) else closed.tail(1)
            if len(pullback_window) < 3:
                return {
                    "pullback_detected": False,
                    "pullback_depth_fib": None,
                    "retracement_ratio": round(pullback_percent, 3),
                    "pullback_quality": 0.0,
                    "pullback_duration": 0,
                    "volume_trend": "stable",
                    "volume_warning": False,
                    "rsi_state": "neutral",
                    "rsi_value": rsi,
                    "current_low": current_low,
                    "current_high": current_high,
                    "swing_point": swing_point,
                    "structure_confirmed": False,
                    "reasoning": f"Swing too recent ({len(pullback_window)} bars), waiting for structure",
                }

            structure_window = pullback_window.tail(min(10, len(pullback_window)))
            is_making_lh_ll, structure_reason = _structure_confirmation(structure_window, "BEARISH")
            volume_trend, volume_warning = _volume_context(pullback_window)

            # Bearish pullback likes a temporary overbought RSI.
            rsi_state = "overbought" if rsi is not None and rsi > 65 else ("oversold" if rsi is not None and rsi < 30 else "neutral")
            pullback_duration = max(0, len(closed) - 1 - swing_low_pos)
        
        # Calculate Fib levels for pullback depth using the actual impulse range.
        # BULLISH: impulse from swing_low -> swing_high, pullback measured from swing_high down.
        # BEARISH: impulse from swing_low -> swing_high, pullback measured from swing_low up.
        fibs = calculate_fib_levels(swing_high, swing_low)
        
        # Estimate pullback depth using standard retracement buckets.
        pullback_fib = 0.0
        if pullback_percent >= 0.786:
            pullback_fib = 0.786
        elif pullback_percent >= 0.618:
            pullback_fib = 0.618
        elif pullback_percent >= 0.500:
            pullback_fib = 0.500
        elif pullback_percent >= 0.382:
            pullback_fib = 0.382
        elif pullback_percent >= 0.236:
            pullback_fib = 0.236

        # Score pullback quality
        quality = 0.0
        if 0.382 <= pullback_percent <= 0.618:
            quality = 5.5
        elif 0.236 <= pullback_percent < 0.382 or 0.618 < pullback_percent <= 0.786:
            quality = 4.0
        elif pullback_percent < 0.236:
            quality = 1.0
        else:
            quality = 2.5

        if is_making_lh_ll:
            quality += 3.0
        if volume_trend == "declining":
            quality += 1.5
        elif volume_trend == "stable":
            quality += 0.5
        elif volume_trend == "rising":
            quality += 0.0
        if rsi_state in ["overbought", "oversold"]:
            quality += 1.0
        if ema20 is not None and ema50 is not None:
            if expected_bias == "BULLISH" and ema20 >= ema50 and current_close is not None and current_close >= ema20:
                quality += 0.5
            elif expected_bias == "BEARISH" and ema20 <= ema50 and current_close is not None and current_close <= ema20:
                quality += 0.5
        
        quality = min(10.0, quality)
        
        # Pullback is considered detected once the retracement exists and the
        # counter-trend structure is confirmed.
        pullback_detected = (
            0.236 <= pullback_percent <= 0.786 and
            is_making_lh_ll
        )
        
        # Safe formatting with None checks
        rsi_val = rsi if rsi is not None else 0
        pullback_fib_pct = f"{pullback_fib:.1%}" if pullback_fib is not None else "N/A"
        reasoning = (
            f"M15 pullback on closed candles: retracement={pullback_percent:.1%} ({pullback_fib_pct} fib), "
            f"structure={is_making_lh_ll}, volume={volume_trend}, RSI={rsi_val:.0f} ({rsi_state}), "
            f"duration={pullback_duration} bars"
        )
        if "structure_reason" in locals():
            reasoning += f" | {structure_reason}"
        if volume_warning:
            reasoning += " | WARNING: volume rising into pullback"
        
        return {
            "pullback_detected": pullback_detected,
            "pullback_depth_fib": pullback_fib,
            "retracement_ratio": round(pullback_percent, 3),
            "pullback_quality": quality,
            "pullback_duration": pullback_duration,
            "volume_trend": volume_trend,
            "volume_warning": volume_warning,
            "rsi_state": rsi_state,
            "rsi_value": rsi,
            "current_low": current_low,
            "current_high": current_high,
            "swing_point": swing_point,
            "structure_confirmed": is_making_lh_ll,
            "pullback_in_progress": 0.236 <= pullback_percent <= 0.786 and not pullback_detected,
            "ema_alignment": {
                "ema20": ema20,
                "ema50": ema50,
                "current_close": current_close,
            },
            "reasoning": reasoning,
        }
    
    except Exception as exc:
        log_debug(f"M15 pullback detection error: {exc}")
        return {
            "pullback_detected": False,
            "pullback_depth_fib": None,
            "pullback_quality": 0.0,
            "pullback_duration": 0,
            "volume_trend": "unknown",
            "volume_warning": False,
            "rsi_state": "unknown",
            "rsi_value": None,
            "current_low": None,
            "current_high": None,
            "swing_point": None,
            "pullback_in_progress": False,
            "reasoning": f"Error: {str(exc)}",
        }


def get_m15_pullback(
    m15_data: pd.DataFrame,
    bias: str,
) -> dict[str, Any]:
    """
    Wrapper for M15 pullback detection.
    """
    return detect_m15_pullback(m15_data, bias)
