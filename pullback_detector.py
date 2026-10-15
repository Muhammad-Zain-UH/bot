"""LAYER 3: M15 PULLBACK PHASE DETECTOR - Identifies retracement opportunities.

Evaluates the **effective post-L2 direction** (D-6OF-2B), not L1's pre-flip bias.

The rules below describe HEAD. An earlier version of this docstring described an
EMA20/EMA50 crossover, a directional up-candle/down-candle volume comparison and
a hard 0.618 depth maximum -- three rules inherited from predecessor modules that
this module never implemented. They were corrected in D-6OF-2H; the historical
evidence is in docs/PHASE_6O_B_L3_PULLBACK_DEEP_AUDIT.md and the D-6OF-2D/2E/2F
investigations. Nothing about the implementation changed.

RETRACEMENT DEPTH
- Accepted band: 0.236 <= pullback_percent <= 0.786, inclusive at both ends.
- Ideal zone:       0.382 <= p <= 0.618  -> base quality 5.5
- Shallow shoulder: 0.236 <= p <  0.382  -> base quality 4.0
- Deep shoulder:    0.618 <  p <= 0.786  -> base quality 4.0
- Rejected: p < 0.236 or p > 0.786.
- **0.618 is NOT a hard rejection boundary.** It is the upper edge of the
  highest-quality zone only; 0.618-0.786 is accepted and scored 4.0. The
  predecessor's hard 0.618 gate in technical_engine.py was deliberately made
  non-blocking (FIX #5) in the same commit that created this module.
- **0.786 provenance is UNRESOLVED.** The five ratios were inherited wholesale
  from fibonacci_levels.py as the standard Fibonacci level set, and the accepted
  band is exactly [min, max] of that set. No repository evidence explains why
  78.6% was selected as the acceptance ceiling. Do not invent a rationale.

STRUCTURE
- `is_making_lh_ll` -- counter-trend fractal against the effective direction --
  contributes +3.0 to quality. It is a bonus, not a requirement.

VOLUME
- Scored from **temporal contraction across the pullback window**: the mean of
  the window's last 3 bars against the mean of its first 3 (`_volume_context`).
  declining (< 0.9x) -> +1.5 | stable -> +0.5 | rising (> 1.1x) -> +0.0
- It is **direction-blind**. It does not compare up-candle volume against
  down-candle volume, and no such comparison exists in this module.
- Volume is **not a standalone gate**. `volume_warning` is emitted for reporting
  only; nothing in the production path (main_production.py) reads it.

RSI
- RSI stretched into the opposite extreme (overbought/oversold) -> +1.0

EMA
- When `ema20` and `ema50` are both present on the frame, alignment of
  (ema20 vs ema50) and (close vs ema20) with the expected direction adds +0.5.
- This is an **alignment bonus, not an EMA20/EMA50 crossover gate.** No crossover
  condition is implemented anywhere in this module.
- It is **currently inert**: the raw M15 frame L3 receives carries no
  `ema20`/`ema50` columns, so the branch does not fire in the production path.

PULLBACK DETECTION
    pullback_detected = (0.236 <= p <= 0.786)
                        AND (is_making_lh_ll OR quality >= 5.0)
- Detection is **not purely structural**. Since FIX (PULLBACK-1) a sufficiently
  high composite quality substitutes for the fractal confirmation, so the flag is
  structural on one disjunct and quality-derived on the other.

QUALITY (0-10)
- Base 5.5 / 4.0 / 1.0 (p < 0.236) / 2.5 (p > 0.786), plus the non-negative
  bonuses above, capped at 10.0. Every early return yields 0.0 with
  pullback_detected=False.
- Consequence, pinned by tests/backtest/test_l3_quality_invariant.py:
  **pullback_detected == True implies pullback_quality >= 4.0**, because the
  accepted band floors the base score at 4.0 and no bonus is negative.

The downstream admission gate in main_production.py requires a pullback result
AND pullback_detected AND pullback_quality >= MIN_PULLBACK_QUALITY. That
both-detection-and-quality gate is intentional; see the note at its definition.
"""

from __future__ import annotations
from typing import Any
import pandas as pd
from utils import log_debug

from core.candles import InsufficientBarsError, closed_bars
from core.indicators import atr_wilder
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


def _estimate_recent_atr(recent: pd.DataFrame) -> float | None:
    """True Wilder ATR on closed bars, or ``None`` when it cannot be computed.

    A2 (``PHASE_2_ISSUES.md``). The true-range calculation here was correct, but
    it was smoothed with ``rolling(14).mean()`` -- a simple moving average, not
    Wilder's recursive smoothing. That is a different statistic: an SMA weights
    the oldest bar in the window as heavily as the newest and drops it entirely
    at bar 15, where Wilder decays it geometrically and never drops it.

    ``min_periods=3`` also meant a three-bar frame produced a "14-period ATR"
    from three observations without saying so.

    Returns ``None`` rather than the previous ``default = 10.0``, which
    fabricated a volatility reading on any short frame or exception. ``atr_val``
    gates the impulse test (``impulse_range < atr_val * 1.2``), so a fabricated
    10.0 silently imposed a 12.0 impulse requirement from no data.

    Args:
        recent: Bars under ``BarConvention.CLOSED_ONLY``.

    Returns:
        The ATR in quote currency, or ``None`` if it cannot be computed.
    """
    if recent is None:
        return None
    try:
        return float(atr_wilder(recent, period=14).value.value)
    except (InsufficientBarsError, ValueError, KeyError, TypeError) as exc:
        log_debug(f"[PULLBACK] ATR unavailable: {exc}")
        return None


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
        # B5 (PHASE_2_ISSUES.md) -- the DOUBLE DROP. `m15_data` arrives from
        # get_market_data(closed_only=True), which has already removed MT5's
        # forming bar, so `iloc[:-1]` removed a second, REAL closed bar and this
        # detector ran two bars stale. The variable name `closed` records the
        # intent, which was already satisfied before this line.
        #
        # core.candles.closed_bars is a no-op under CLOSED_ONLY, so applying it
        # twice is safe -- that is exactly why it exists, and its own docstring
        # names this bug: "unlike the ad-hoc .iloc[:-1] pattern, which silently
        # discards a real bar each time it is repeated."
        closed = closed_bars(recent).copy()
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
        if atr_val is None:
            # A2: no fabricated volatility. The old default of 10.0 imposed a
            # 12.0 impulse requirement (atr_val * 1.2) from no data at all.
            return {
                "pullback_detected": False,
                "pullback_quality": 0.0,
                "reasoning": "ATR unavailable; cannot assess impulse",
            }

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
        
        # Pullback is considered detected once the retracement exists AND either
        # the counter-trend fractal structure is confirmed OR the composite quality
        # score is already high enough to stand on its own.
        # FIX (PULLBACK-1): previously this required is_making_lh_ll strictly, even
        # though quality (above) only treats it as a +3.0 bonus rather than a hard
        # requirement. That mismatch let genuinely good pullbacks (high quality from
        # retracement depth + volume + RSI) get marked detected=False, and the
        # downstream gate in main_production.py requires both detected AND quality,
        # so those setups were being blocked for a reason the score itself disagreed with.
        pullback_detected = (
            0.236 <= pullback_percent <= 0.786 and
            (is_making_lh_ll or quality >= 5.0)
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