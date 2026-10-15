"""Coherent multi-timeframe strategy engine for XAUUSD.

The previous technical engine accumulated many overlapping fixes and confidence
adjustments. This module replaces that path with a single decision model:

1. Establish higher-timeframe bias from H4/H1.
2. Decide whether lower timeframes are in pullback or continuation.
3. Require M15/M5 re-alignment before looking for an M1 trigger.
4. Use institutional patterns and volume as confirmation, not direction setters.
5. Build a transparent score, confidence, and trade plan from one rule set.
"""

from __future__ import annotations

from typing import Any

from institutional_patterns import detect_institutional_patterns
from risk_manager import get_current_session
from utils import log_debug

WAIT_SIGNAL = "WAIT_FOR_CONFIRMATION"
TRADE_SIGNALS = {"BUY", "SELL"}
BULLISH_TRENDS = {"Strong Bullish", "Weak Bullish"}
BEARISH_TRENDS = {"Strong Bearish", "Weak Bearish"}
RELEVANT_TIMEFRAMES = ("H4", "H1", "M15", "M5", "M1")
MAX_STRATEGY_SCORE = 10.0


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except Exception:
        return None


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _trend_dir(trend: str) -> str:
    if trend in BULLISH_TRENDS:
        return "BUY"
    if trend in BEARISH_TRENDS:
        return "SELL"
    return "NO TRADE"


def _evaluate_tf(indicators: dict[str, Any]) -> dict[str, Any]:
    trend = str(indicators.get("trend_classification", "Neutral"))
    direction = _trend_dir(trend)
    pvwap = str(indicators.get("price_vs_vwap", "Unknown"))
    return {
        "trend_classification": trend,
        "direction": direction,
        "price_vs_vwap": pvwap,
        "rsi_signal": str(indicators.get("rsi_signal", "Unavailable")),
        "strong_trend": trend.startswith("Strong"),
        "trend_strength_ratio": _f(indicators.get("trend_strength_ratio")) or 0.0,
    }


def _alignment_count(direction: str, tfa: dict[str, dict[str, Any]]) -> int:
    if direction not in TRADE_SIGNALS:
        return 0
    return sum(1 for label in RELEVANT_TIMEFRAMES if tfa.get(label, {}).get("direction") == direction)


def _volume_context(tfi: dict[str, dict[str, Any]]) -> dict[str, Any]:
    m15_ratio = _f(tfi.get("M15", {}).get("volume_ratio"))
    m5_ratio = _f(tfi.get("M5", {}).get("volume_ratio"))
    m1_ratio = _f(tfi.get("M1", {}).get("volume_ratio"))

    dead = (
        m15_ratio is not None
        and m15_ratio < 0.35
        and (m5_ratio is None or m5_ratio < 0.55)
        and (m1_ratio is None or m1_ratio < 0.55)
    )
    thin = m15_ratio is not None and m15_ratio < 0.75
    healthy = m15_ratio is not None and m15_ratio >= 0.95 and not dead

    if dead:
        reason = "Entry participation is dead across M15/M5/M1."
        score = -1.4
    elif thin:
        reason = f"M15 volume is thin ({m15_ratio:.2f}); require tighter confirmation."
        score = -0.6
    elif healthy:
        reason = f"M15 volume is healthy ({m15_ratio:.2f})."
        score = 0.8
    else:
        reason = "Volume is usable but not strong."
        score = 0.2

    return {
        "dead": dead,
        "thin": thin,
        "healthy": healthy,
        "m15_ratio": m15_ratio,
        "reason": reason,
        "score": score,
    }


def _bias_context(
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Bias context using H4 as PRIMARY direction source and H1 as confirmation."""
    h4 = tfa.get("H4", {})
    h1 = tfa.get("H1", {})
    h4_dir = h4.get("direction", "NO TRADE")
    h1_dir = h1.get("direction", "NO TRADE")
    h4_trend = str(h4.get("trend_classification", "Neutral"))
    h1_trend = str(h1.get("trend_classification", "Neutral"))
    h4_strength = _clip((_f(tfi.get("H4", {}).get("trend_strength_ratio")) or 0.0) / 1.2, 0.0, 1.0)
    h1_strength = _clip((_f(tfi.get("H1", {}).get("trend_strength_ratio")) or 0.0) / 1.2, 0.0, 1.0)

    if h4_dir in TRADE_SIGNALS:
        h1_conflict = h1_dir in TRADE_SIGNALS and h1_dir != h4_dir
        if h1_dir == h4_dir:
            strength = 0.85 + (h4_strength * 0.05) + (h1_strength * 0.1)
        elif h1_conflict:
            strength = 0.50 + (h4_strength * 0.05)
        else:
            strength = 0.68 + (h4_strength * 0.12)
        return {
            "direction": h4_dir,
            "strength": round(_clip(strength, 0.50, 0.95), 2),
            "conflicted": h1_conflict,
            "h1_countertrend": h1_conflict,
            "h4_conflict_warning": h1_conflict,
            "reason": (
                f"H4 primary direction is {h4_dir} ({h4_trend}). "
                f"H1 {'confirms' if h1_dir == h4_dir else 'is countertrend' if h1_conflict else 'is neutral'}."
            ),
        }

    return {
        "direction": "NO TRADE",
        "strength": 0.0,
        "conflicted": False,
        "h1_countertrend": False,
        "h4_conflict_warning": False,
        "reason": "H1 and H4 both show no trade signal.",
    }


def _rsi_context(direction: str, tfi: dict[str, dict[str, Any]]) -> dict[str, Any]:
    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))

    exhausted = False
    caution = False
    reason = ""

    if direction == "BUY":
        if (m15_rsi is not None and m15_rsi >= 72.0) or (m1_rsi is not None and m1_rsi >= 75.0):
            exhausted = True
            reason = f"BUY is stretched (M15 RSI={m15_rsi}, M1 RSI={m1_rsi})."
        elif (m15_rsi is not None and m15_rsi >= 66.0) or (m5_rsi is not None and m5_rsi >= 68.0):
            caution = True
            reason = f"BUY is warm but not exhausted (M15 RSI={m15_rsi}, M5 RSI={m5_rsi})."
    elif direction == "SELL":
        if (m15_rsi is not None and m15_rsi <= 28.0) or (m1_rsi is not None and m1_rsi <= 25.0):
            exhausted = True
            reason = f"SELL is stretched (M15 RSI={m15_rsi}, M1 RSI={m1_rsi})."
        elif (m15_rsi is not None and m15_rsi <= 34.0) or (m5_rsi is not None and m5_rsi <= 32.0):
            caution = True
            reason = f"SELL is extended but still workable (M15 RSI={m15_rsi}, M5 RSI={m5_rsi})."

    return {
        "exhausted": exhausted,
        "caution": caution,
        "reason": reason,
    }


def _m1_trigger_ready(
    direction: str,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    m1 = tfi.get("M1", {})
    m1_dir = tfa.get("M1", {}).get("direction", "NO TRADE")
    m1_rsi = _f(m1.get("rsi_14"))
    m1_vwap = str(m1.get("price_vs_vwap", "Unknown"))
    m1_trend = str(m1.get("trend_classification", "Neutral"))

    if m1_rsi is None:
        return False, "M1 RSI is unavailable."

    if direction == "BUY":
        if m1_dir != "BUY":
            return False, f"M1 is not bullish yet ({m1_trend})."
        if m1_vwap != "Above":
            return False, "M1 price is still below VWAP."
        if not (42.0 <= m1_rsi <= 68.0):
            return False, f"M1 RSI {m1_rsi:.1f} is outside the BUY trigger window."
        return True, ""

    if direction == "SELL":
        if m1_dir != "SELL":
            return False, f"M1 is not bearish yet ({m1_trend})."
        if m1_vwap != "Below":
            return False, "M1 price is still above VWAP."
        if not (32.0 <= m1_rsi <= 58.0):
            return False, f"M1 RSI {m1_rsi:.1f} is outside the SELL trigger window."
        return True, ""

    return False, "No trade direction."


def _pullback_context(
    direction: str,
    bias: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if direction not in TRADE_SIGNALS:
        return {
            "active": False,
            "structured_reentry": False,
            "target_zone": "",
            "reason": "",
            "trigger": "",
        }

    m15_dir = tfa.get("M15", {}).get("direction", "NO TRADE")
    m5_dir = tfa.get("M5", {}).get("direction", "NO TRADE")
    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    daily = tfi.get("D1", {})
    daily_pivot = _f(daily.get("daily_pivot"))
    daily_s1 = _f(daily.get("daily_s1"))
    daily_r1 = _f(daily.get("daily_r1"))
    atr = _f(tfi.get("M15", {}).get("atr_14")) or _f(tfi.get("M5", {}).get("atr_14")) or 0.0

    if direction == "BUY":
        active = m15_dir == "SELL" or m5_dir == "SELL"
        target = daily_pivot if daily_pivot is not None else (daily_s1 + atr * 0.5 if daily_s1 is not None else None)
        target_zone = f"watch {target:.2f} as the pullback completion area" if target is not None else ""
        reason = (
            f"Higher-timeframe BUY bias is intact, but M15/M5 are still pulling back "
            f"(M15 RSI={m15_rsi}, M5 RSI={m5_rsi})."
        )
        trigger = "Wait for M15 and M5 to flip back to BUY before looking for M1 entry."
        structured_reentry = not active and bias.get("h1_countertrend", False)
    else:
        active = m15_dir == "BUY" or m5_dir == "BUY"
        target = daily_pivot if daily_pivot is not None else (daily_r1 - atr * 0.5 if daily_r1 is not None else None)
        target_zone = f"watch {target:.2f} as the pullback completion area" if target is not None else ""
        reason = (
            f"Higher-timeframe SELL bias is intact, but M15/M5 are still retracing higher "
            f"(M15 RSI={m15_rsi}, M5 RSI={m5_rsi})."
        )
        trigger = "Wait for M15 and M5 to flip back to SELL before looking for M1 entry."
        structured_reentry = not active and bias.get("h1_countertrend", False)

    return {
        "active": active,
        "structured_reentry": structured_reentry,
        "target_zone": target_zone,
        "reason": reason if active else "",
        "trigger": trigger if active else "",
    }


def _legacy_momentum_entry_conditions(
    direction: str,
    bias: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
    volume: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate momentum-based fast entry: M5 RSI in extreme territory.
    
    BUY: M5 RSI > 60 (momentum buyers) + H1 BUY bias
    SELL: M5 RSI < 40 (momentum sellers) + H1 SELL bias
    
    Does NOT require M15 pullback or M1 rejection wick.
    Entry happens quickly when momentum conditions align.
    """
    if direction not in TRADE_SIGNALS:
        return {
            "momentum_ready": False,
            "entry_type": None,
            "reason": "Invalid direction",
            "m5_rsi": None,
        }

    if bias.get("direction") != direction:
        return {
            "momentum_ready": False,
            "entry_type": None,
            "reason": f"H4 bias ({bias.get('direction')}) does not match direction {direction}",
            "m5_rsi": None,
        }

    if tfa.get("H1", {}).get("direction") != direction:
        return {
            "momentum_ready": False,
            "entry_type": None,
            "reason": f"H1 structure ({tfa.get('H1', {}).get('direction', 'NO TRADE')}) does not confirm {direction}",
            "m5_rsi": None,
        }
    
    # Check volume is acceptable (dead volume blocks all entries)
    if volume.get("dead", False):
        return {
            "momentum_ready": False,
            "entry_type": None,
            "reason": "Entry participation is dead",
            "m5_rsi": None,
        }
    
    # Get M5 RSI
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    if m5_rsi is None:
        return {
            "momentum_ready": False,
            "entry_type": None,
            "reason": "M5 RSI not available",
            "m5_rsi": None,
        }
    
    # Evaluate momentum RSI thresholds
    if direction == "BUY":
        momentum_ready = m5_rsi > 60.0
        reason = f"M5 RSI={m5_rsi:.1f} {'✓ momentum buy signal' if momentum_ready else '✗ not yet in momentum zone (need >60)'}"
    else:  # SELL
        momentum_ready = m5_rsi < 40.0
        reason = f"M5 RSI={m5_rsi:.1f} {'✓ momentum sell signal' if momentum_ready else '✗ not yet in momentum zone (need <40)'}"
    
    return {
        "momentum_ready": momentum_ready,
        "entry_type": "momentum" if momentum_ready else None,
        "reason": reason,
        "m5_rsi": m5_rsi,
    }


def _recent_m15_shift_context(
    direction: str,
    tfi: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_m15 = tfi.get("M15", {}).get("raw_data")
    if raw_m15 is None or len(raw_m15) < 8:
        return {
            "available": False,
            "confirmed": True,
            "reason": "M15 raw data unavailable for recent structural confirmation.",
        }

    recent = raw_m15.tail(8).reset_index(drop=True)
    highs = recent["high"].astype(float).tolist()
    lows = recent["low"].astype(float).tolist()
    closes = recent["close"].astype(float).tolist()

    if direction == "BUY":
        for idx in range(3, len(recent)):
            prior_high = max(highs[idx - 3:idx])
            prior_low = min(lows[idx - 3:idx])
            if lows[idx] < prior_low and closes[idx] > prior_high:
                return {
                    "available": True,
                    "confirmed": True,
                    "reason": f"M15 sweep/CHOCH confirmed at index {idx}.",
                }
        return {
            "available": True,
            "confirmed": False,
            "reason": "No recent bullish sweep or CHoCH in the last 8 M15 bars.",
        }

    if direction == "SELL":
        for idx in range(3, len(recent)):
            prior_high = max(highs[idx - 3:idx])
            prior_low = min(lows[idx - 3:idx])
            if highs[idx] > prior_high and closes[idx] < prior_low:
                return {
                    "available": True,
                    "confirmed": True,
                    "reason": f"M15 sweep/CHOCH confirmed at index {idx}.",
                }
        return {
            "available": True,
            "confirmed": False,
            "reason": "No recent bearish sweep or CHoCH in the last 8 M15 bars.",
        }

    return {
        "available": False,
        "confirmed": False,
        "reason": "Invalid direction.",
    }


def _momentum_entry_conditions(
    direction: str,
    bias: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
    volume: dict[str, Any],
) -> dict[str, Any]:
    """Breakout scalping entry: aligned H1/M15/M5 plus closed M1 breakout."""
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    base = {
        "momentum_ready": False,
        "entry_type": None,
        "reason": "",
        "m5_rsi": m5_rsi,
    }

    if direction not in TRADE_SIGNALS:
        return {**base, "reason": "Invalid direction"}
    if bias.get("direction") != direction:
        return {**base, "reason": f"H4 bias ({bias.get('direction')}) does not match {direction}"}
    if volume.get("dead", False):
        return {**base, "reason": "Entry participation is dead"}
    if tfa.get("H1", {}).get("direction") != direction:
        return {**base, "reason": f"H1 structure ({tfa.get('H1', {}).get('direction', 'NO TRADE')}) does not confirm {direction}"}
    if tfa.get("M15", {}).get("direction") != direction or tfa.get("M5", {}).get("direction") != direction:
        return {**base, "reason": f"M15/M5 are not aligned with {direction}"}
    if m5_rsi is None:
        return {**base, "reason": "M5 RSI not available"}

    recent_shift = _recent_m15_shift_context(direction, tfi)
    if recent_shift.get("available", False) and not recent_shift.get("confirmed", False):
        return {
            **base,
            "reason": recent_shift.get("reason", "Recent M15 structural confirmation missing."),
            "recent_m15_shift_confirmed": False,
            "recent_m15_shift_reason": recent_shift.get("reason", ""),
        }

    m1 = tfi.get("M1", {})
    m1_close = _f(m1.get("close"))
    prev_high = _f(m1.get("prev_high"))
    prev_low = _f(m1.get("prev_low"))
    m1_high = _f(m1.get("high"))
    m1_low = _f(m1.get("low"))
    m1_atr = _f(m1.get("atr_14")) or 0.0
    m1_body = _f(m1.get("body")) or 0.0
    m1_volume = _f(m1.get("latest_volume", m1.get("volume"))) or 0.0
    m1_avg_volume = _f(m1.get("average_volume_20")) or 0.0
    m1_vwap = str(m1.get("price_vs_vwap", "Unknown"))

    if None in (m1_close, prev_high, prev_low, m1_high, m1_low):
        return {**base, "reason": "M1 breakout data unavailable"}

    candle_range = max((m1_high or 0.0) - (m1_low or 0.0), 0.0)
    close_position = (m1_close - m1_low) / candle_range if candle_range > 0 else 0.5
    breakout_buffer = max(0.08, m1_atr * 0.10)
    min_body = max(0.05, m1_atr * 0.12)
    volume_ok = m1_avg_volume <= 0 or m1_volume >= m1_avg_volume * 1.35
    body_ok = m1_body >= min_body

    if direction == "BUY":
        breakout = m1_close > prev_high + breakout_buffer
        rsi_ok = 50.0 <= m5_rsi <= 72.0
        vwap_ok = m1_vwap == "Above"
        close_ok = close_position >= 0.60
        reason = (
            f"M1 BUY breakout={breakout} close={m1_close:.2f} prev_high={prev_high:.2f} "
            f"vol_ok={volume_ok} body_ok={body_ok} M5_RSI={m5_rsi:.1f}"
        )
    else:
        breakout = m1_close < prev_low - breakout_buffer
        rsi_ok = 28.0 <= m5_rsi <= 50.0
        vwap_ok = m1_vwap == "Below"
        close_ok = close_position <= 0.40
        reason = (
            f"M1 SELL breakout={breakout} close={m1_close:.2f} prev_low={prev_low:.2f} "
            f"vol_ok={volume_ok} body_ok={body_ok} M5_RSI={m5_rsi:.1f}"
        )

    momentum_ready = all([breakout, volume_ok, body_ok, rsi_ok, vwap_ok, close_ok])
    return {
        **base,
        "momentum_ready": momentum_ready,
        "entry_type": "momentum" if momentum_ready else None,
        "reason": reason,
        "volume_ok": volume_ok,
        "body_ok": body_ok,
        "breakout_buffer": breakout_buffer,
        "recent_m15_shift_confirmed": recent_shift.get("confirmed", True),
        "recent_m15_shift_reason": recent_shift.get("reason", ""),
    }


def _pullback_entry_conditions(
    direction: str,
    bias: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate pullback-based entry: M15 pullback completion + M1 rejection wick.
    
    This is the conservative path:
    - Wait for M15/M5 to pullback (reverse direction)
    - Wait for M1 rejection wick confirmation
    - Fibonacci levels used as completion zones
    
    Slower than momentum entry but higher probability.
    """
    if direction not in TRADE_SIGNALS:
        return {
            "pullback_ready": False,
            "entry_type": None,
            "target_zone": None,
            "reason": "Invalid direction",
        }
    
    # Check H1 bias alignment
    if bias.get("direction") != direction:
        return {
            "pullback_ready": False,
            "entry_type": None,
            "target_zone": None,
            "reason": f"H1 bias ({bias.get('direction')}) does not match direction {direction}",
        }
    
    # Get M15/M5 directions
    m15_dir = tfa.get("M15", {}).get("direction", "NO TRADE")
    m5_dir = tfa.get("M5", {}).get("direction", "NO TRADE")
    
    # Pullback is active when M15/M5 are opposite to bias direction
    pullback_active = False
    if direction == "BUY":
        pullback_active = m15_dir == "SELL" or m5_dir == "SELL"
    else:  # SELL
        pullback_active = m15_dir == "BUY" or m5_dir == "BUY"
    
    # Calculate target zone (where pullback should complete)
    daily_pivot = _f(tfi.get("D1", {}).get("daily_pivot"))
    daily_s1 = _f(tfi.get("D1", {}).get("daily_s1"))
    daily_r1 = _f(tfi.get("D1", {}).get("daily_r1"))
    atr = _f(tfi.get("M15", {}).get("atr_14")) or _f(tfi.get("M5", {}).get("atr_14")) or 0.0
    
    target_zone = None
    if direction == "BUY":
        target_zone = daily_pivot if daily_pivot is not None else (daily_s1 + atr * 0.5 if daily_s1 is not None else None)
    else:  # SELL
        target_zone = daily_pivot if daily_pivot is not None else (daily_r1 - atr * 0.5 if daily_r1 is not None else None)
    
    reason = f"M15={m15_dir}, M5={m5_dir}; pullback {'active' if pullback_active else 'completed'}"
    
    return {
        "pullback_ready": not pullback_active,  # Ready when pullback has completed (flipped back)
        "entry_type": "pullback" if not pullback_active else None,
        "target_zone": target_zone,
        "reason": reason,
    }


def _phase_context(
    direction: str,
    bias: dict[str, Any],
    tfa: dict[str, dict[str, Any]],
    patterns: dict[str, Any],
) -> tuple[str, float]:
    if direction not in TRADE_SIGNALS:
        return "RANGE", 0.0

    if patterns.get("is_liquidity_sweep"):
        return ("SPRING", 72.0) if direction == "BUY" else ("UPTHRUST", 72.0)

    # H1 is now the primary higher timeframe check (H4 removed)
    aligned_higher = tfa.get("H1", {}).get("direction") == direction
    aligned_entry = tfa.get("M15", {}).get("direction") == direction and tfa.get("M5", {}).get("direction") == direction

    if aligned_higher and aligned_entry:
        return ("MARKUP", 68.0) if direction == "BUY" else ("MARKDOWN", 68.0)

    if bias.get("h1_countertrend") or tfa.get("M15", {}).get("direction") != direction:
        return "PULLBACK", 45.0

    return "RANGE", 30.0


def _directional_quality(
    direction: str,
    bias: dict[str, Any],
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
    volume: dict[str, Any],
    patterns: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    components = {
        "bias": 0.0,
        "m15_structure": 0.0,
        "m5_trigger": 0.0,
        "m1_trigger": 0.0,
        "volume": 0.0,
        "rsi": 0.0,
        "pivot_context": 0.0,
        "patterns": 0.0,
    }

    # Bias scoring: H4 primary with H1 confirmation
    if bias.get("direction") == direction:
        components["bias"] = 2.8 + (bias.get("strength", 0.0) * 1.8)
        if tfa.get("H1", {}).get("direction") == direction:
            components["bias"] += 0.6
        elif tfa.get("H1", {}).get("direction") in TRADE_SIGNALS:
            components["bias"] -= 0.8
    elif bias.get("direction") in TRADE_SIGNALS:
        components["bias"] = -1.8

    if tfa.get("M15", {}).get("direction") == direction:
        components["m15_structure"] = 1.6
    elif tfa.get("M15", {}).get("direction") in TRADE_SIGNALS:
        components["m15_structure"] = -1.1

    if tfa.get("M5", {}).get("direction") == direction:
        components["m5_trigger"] = 1.1
    elif tfa.get("M5", {}).get("direction") in TRADE_SIGNALS:
        components["m5_trigger"] = -0.9

    if tfa.get("M1", {}).get("direction") == direction:
        components["m1_trigger"] = 0.7
    elif tfa.get("M1", {}).get("direction") in TRADE_SIGNALS:
        components["m1_trigger"] = -0.5

    components["volume"] = volume["score"]

    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    if m15_rsi is not None:
        if direction == "BUY":
            if 52.0 <= m15_rsi <= 64.0:
                components["rsi"] = 0.8
            elif m15_rsi >= 70.0:
                components["rsi"] = -0.8
        else:
            if 36.0 <= m15_rsi <= 48.0:
                components["rsi"] = 0.8
            elif m15_rsi <= 30.0:
                components["rsi"] = -0.8

    current_price = _f(tfi.get("M1", {}).get("close")) or _f(tfi.get("M15", {}).get("close"))
    daily_pivot = _f(tfi.get("D1", {}).get("daily_pivot"))
    if current_price is not None and daily_pivot is not None:
        if direction == "BUY":
            components["pivot_context"] = 0.4 if current_price >= daily_pivot else -0.4
        else:
            components["pivot_context"] = 0.4 if current_price <= daily_pivot else -0.4

    components["patterns"] = _clip((patterns.get("confidence_adjustment", 0.0) / 12.0), -1.5, 1.5)

    score = sum(components.values())
    return round(_clip(score, -MAX_STRATEGY_SCORE, MAX_STRATEGY_SCORE), 2), components


def _build_levels(direction: str, tfi: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    if direction not in TRADE_SIGNALS:
        return {
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "risk_distance": None,
            "pullback_target": None,
        }

    entry = _f(tfi.get("M1", {}).get("close")) or _f(tfi.get("M5", {}).get("close")) or _f(tfi.get("M15", {}).get("close"))
    atr = _f(tfi.get("M15", {}).get("atr_14")) or _f(tfi.get("M5", {}).get("atr_14")) or _f(tfi.get("H1", {}).get("atr_14"))
    daily_pivot = _f(tfi.get("D1", {}).get("daily_pivot"))
    daily_s1 = _f(tfi.get("D1", {}).get("daily_s1"))
    daily_r1 = _f(tfi.get("D1", {}).get("daily_r1"))
    
    # PRIORITY 2 FIX: Get M15 swing levels for structure-based targets
    m15_swing_high = _f(tfi.get("M15", {}).get("swing_high"))
    m15_swing_low = _f(tfi.get("M15", {}).get("swing_low"))
    
    # PRIORITY 4 FIX: Get M5 ATR for body minimum check
    m5_atr = _f(tfi.get("M5", {}).get("atr"))

    if entry is None or atr in {None, 0.0}:
        return {
            "entry_price": entry,
            "stop_loss": None,
            "take_profit": None,
            "risk_distance": None,
            "pullback_target": None,
        }

    risk_distance = max(atr * 1.35, 6.0)

    # PRIORITY 2 FIX: Structure-based targets using next technical level
    if direction == "BUY":
        stop_loss = entry - risk_distance
        if daily_s1 is not None and entry - daily_s1 < risk_distance * 1.4:
            stop_loss = min(stop_loss, daily_s1 - (atr * 0.15))
        
        # Target = next resistance (R1, M15 swing high, or Fibonacci 1.272 extension)
        # Use R1 if valid, else M15 swing high, else fixed R:R
        if daily_r1 is not None and daily_r1 > entry:
            take_profit = daily_r1 + (atr * 0.2)  # Slightly above R1
        elif m15_swing_high is not None and m15_swing_high > entry:
            take_profit = m15_swing_high + (atr * 0.1)
        else:
            # Fallback: Fibonacci 1.272 extension from entry
            fib_extension = entry + (entry - stop_loss) * 1.272
            take_profit = max(fib_extension, entry + (risk_distance * 2.0))
        
        if daily_pivot is not None and daily_pivot < entry:
            pullback_target = daily_pivot
        elif daily_s1 is not None:
            pullback_target = daily_s1 + (atr * 0.5)
        else:
            pullback_target = entry - (atr * 0.7)
    else:
        stop_loss = entry + risk_distance
        if daily_r1 is not None and daily_r1 - entry < risk_distance * 1.4:
            stop_loss = max(stop_loss, daily_r1 + (atr * 0.15))
        
        # Target = next support (S1, M15 swing low, or Fibonacci 1.272 extension)
        if daily_s1 is not None and daily_s1 < entry:
            take_profit = daily_s1 - (atr * 0.2)  # Slightly below S1
        elif m15_swing_low is not None and m15_swing_low < entry:
            take_profit = m15_swing_low - (atr * 0.1)
        else:
            # Fallback: Fibonacci 1.272 extension from entry
            fib_extension = entry - (stop_loss - entry) * 1.272
            take_profit = min(fib_extension, entry - (risk_distance * 2.0))
        
        if daily_pivot is not None and daily_pivot > entry:
            pullback_target = daily_pivot
        elif daily_r1 is not None:
            pullback_target = daily_r1 - (atr * 0.5)
        else:
            pullback_target = entry + (atr * 0.7)

    return {
        "entry_price": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_distance": round(abs(entry - stop_loss), 2),
        "pullback_target": round(pullback_target, 2) if pullback_target is not None else None,
    }


def _risk_level(
    bias: dict[str, Any],
    volume: dict[str, Any],
    rsi_ctx: dict[str, Any],
    mixed_signals: bool,
    entry_state: str,
) -> str:
    risk_points = 0
    if bias.get("conflicted", False):
        risk_points += 2
    if volume.get("thin", False):
        risk_points += 1
    if volume.get("dead", False):
        risk_points += 2
    if rsi_ctx.get("caution", False):
        risk_points += 1
    if rsi_ctx.get("exhausted", False):
        risk_points += 2
    if mixed_signals:
        risk_points += 1
    if entry_state != "ready":
        risk_points += 1
    if risk_points >= 5:
        return "High"
    if risk_points >= 2:
        return "Medium"
    return "Low"




def _confidence(
    setup_direction: str,
    direction_score: float,
    bias: dict[str, Any],
    alignment_count: int,
    volume: dict[str, Any],
    rsi_ctx: dict[str, Any],
    patterns: dict[str, Any],
    entry_state: str,
    high_impact_news: bool,
    h4_bias: str = "NO TRADE",
    h1_direction: str = "NO TRADE",
    cvd_result: dict[str, Any] | None = None,
) -> int:
    """Calculate technical confidence with full 25-99% range support.
    
    Args:
        setup_direction: BUY or SELL
        direction_score: Raw directional strength (-10 to +10)
        bias: Higher TF bias context (strength, h4_conflict_warning, etc.)
        alignment_count: Number of timeframes aligned (0-5)
        volume: Volume context (dead, thin, healthy)
        rsi_ctx: RSI context (exhausted, caution flags)
        patterns: Institutional patterns detected
        entry_state: Entry readiness state
        high_impact_news: Whether high-impact news is present
        h4_bias: H4 directional bias for conflict checking
        h1_direction: H1 directional bias
        cvd_result: CVD divergence result dict
        
    Returns:
        Confidence percentage 25-99
    """
    if setup_direction not in TRADE_SIGNALS:
        return 0

    # Base confidence formula: 25 + components
    confidence = 25.0
    
    # 1. H1 strength component (up to +35)
    h1_strength = bias.get("strength", 0.0)  # 0.0 to 1.0
    confidence += h1_strength * 35.0
    
    # 2. Directional score component (up to +25)
    score_component = max(0.0, direction_score) * 2.5
    confidence += min(score_component, 25.0)
    
    # 3. Alignment component (up to +20)
    alignment_component = alignment_count * 4.0
    confidence += min(alignment_component, 20.0)
    
    # 4. H4 conflict modifier (±3 to ±12 based on conflict severity) - STRENGTHENED
    h4_conflict = bias.get("h4_conflict_warning", False)
    if h4_conflict:
        # H4 conflicts with H1 - reduce confidence significantly (increased from -9% to -12%)
        h4_modifier = -12.0  # -12% penalty for H4 conflict (more serious)
        confidence += h4_modifier
        log_debug(f"[CONFIDENCE] H4 conflict detected: {h4_bias} vs {h1_direction} → {h4_modifier:.0f}% penalty")
    else:
        # H4 aligned with H1 - slight boost (kept at +3%)
        h4_modifier = 3.0  # +3% bonus for H4 alignment
        confidence += h4_modifier
    
    # 5. Pattern modifiers (CORRECTED: upthrust now reduces, sweep adjusted)
    if patterns.get("is_upthrust"):
        confidence -= 15.0  # UPTHRUST is counter-signal (fake breakout)
        log_debug(f"[CONFIDENCE] Upthrust detected → -15% penalty")
    elif patterns.get("is_liquidity_sweep"):
        sweep_type = patterns.get("sweep_type", "")
        if (setup_direction == "BUY" and sweep_type == "bear") or (setup_direction == "SELL" and sweep_type == "bull"):
            confidence += 8.0  # Sweep aligned with setup = institutions swept opposing stops
            log_debug(f"[CONFIDENCE] Liquidity sweep aligned → +8% bonus")
        else:
            confidence -= 12.0  # Sweep against setup = counter-signal
            log_debug(f"[CONFIDENCE] Liquidity sweep opposed → -12% penalty")
    
    # 6. Volume modifiers (STRENGTHENED)
    if volume.get("healthy"):
        confidence += 6.0  # Good volume support (increased from +4%)
    if volume.get("thin"):
        confidence -= 8.0  # Thin volume warning (increased from -6%)
    if volume.get("dead"):
        confidence -= 15.0  # Dead volume - high risk (increased from -12%)
    
    # 7. CVD divergence modifier (±6 or ±10)
    if cvd_result and cvd_result.get("has_divergence"):
        div_type = cvd_result.get("type", "")
        if (setup_direction == "BUY" and div_type == "bullish") or (setup_direction == "SELL" and div_type == "bearish"):
            confidence += 10.0  # Strong CVD confirmation
            log_debug(f"[CONFIDENCE] CVD {div_type} divergence confirmed → +10% bonus")
        else:
            confidence -= 6.0  # CVD conflict
            log_debug(f"[CONFIDENCE] CVD {div_type} divergence conflicts → -6% penalty")
    
    # 8. RSI context modifiers (STRENGTHENED)
    if rsi_ctx.get("exhausted"):
        confidence -= 12.0  # Exhaustion = high risk (increased from -10%)
    elif rsi_ctx.get("caution"):
        confidence -= 6.0  # Warm but not exhausted (increased from -4%)
    
    # 9. Entry state modifier
    if entry_state == "ready":
        confidence += 2.0  # Ready state = slight boost
    elif entry_state == "ready_momentum":
        confidence += 4.0  # Momentum ready = better boost
    elif entry_state == "ready_pullback_await_wick":
        confidence += 1.0  # Pullback await = minimal boost (confirmation pending)
    else:
        confidence -= 3.0  # Not ready states
    
    # 10. News impact modifier
    if high_impact_news:
        confidence -= 8.0  # High impact news = significant penalty
    
    # Final clip to valid range: 25-99%
    final_confidence = int(round(_clip(confidence, 25.0, 99.0)))
    return final_confidence


def _empty(reason: str) -> dict[str, Any]:
    return {
        "technical_signal": "NO TRADE",
        "bias_direction": "NO TRADE",
        "setup_direction": "NO TRADE",
        "execute_signal": "NO TRADE",
        "trigger_state": "not_actionable",
        "signal_status": "NO_TRADE",
        "weighted_score": 0.0,
        "max_score": MAX_STRATEGY_SCORE,
        "technical_confidence": 0,
        "scorecard": {},
        "timeframe_analysis": {},
        "mixed_signals": False,
        "risk_level": "High",
        "trade_levels": {
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "risk_distance": None,
            "pullback_target": None,
        },
        "gates": {},
        "entry_timing_state": "not_actionable",
        "wait_reason": "",
        "wait_trigger": "",
        "error": reason,
    }


# ============================================================================
# COMPREHENSIVE GATE VALIDATION SYSTEM
# ============================================================================

def _validate_m1_candle_quality(
    m1_candle: dict[str, Any],
    direction: str,
    m1_volume_avg: float = 0.0,
) -> tuple[bool, str]:
    """
    GATE: M1 Candle Formation Quality
    
    Validates that M1 candle has:
    - Sufficient body size (> 2.0 pips)
    - Valid price position (not at extreme)
    - Valid wick structure
    - Minimum volume
    """
    try:
        body = m1_candle.get("body", 0)
        wick_ratio = m1_candle.get("wick_ratio", 0)
        close = m1_candle.get("close", 0)
        high = m1_candle.get("high", 0)
        low = m1_candle.get("low", 0)
        volume = m1_candle.get("latest_volume", m1_candle.get("volume", 0))
        atr = _f(m1_candle.get("atr_14")) or 0.0
        min_body = max(0.05, atr * 0.12)
        
        # Check 1: Body size must be meaningful relative to current M1 ATR.
        if body < min_body:
            return False, f"M1 body too thin ({body:.2f} < {min_body:.2f})"
        
        # Check 2: Volume (must be >= avg * 1.5 for momentum)
        if m1_volume_avg > 0 and volume < m1_volume_avg * 1.5:
            return False, f"M1 volume insufficient ({volume:.0f} < {m1_volume_avg*1.5:.0f})"
        
        # Check 3: Price position (not at extremes)
        candle_range = high - low if high > 0 and low > 0 else 1
        if candle_range > 0:
            close_position = (close - low) / candle_range
            
            if direction == "BUY":
                # Close must be > 50% from low (not at bottom)
                if close_position < 0.5:
                    return False, f"M1 close at bottom ({close_position:.1%} from low)"
            else:  # SELL
                # Close must be < 50% from high (not at top)
                if close_position > 0.5:
                    return False, f"M1 close at top ({close_position:.1%} from low)"
        
        # Check 4: Wick structure (must show rejection)
        if wick_ratio is not None and wick_ratio < 0.35:
            return False, f"M1 wick ratio too low ({wick_ratio:.1%})"
        
        return True, "M1 candle quality valid"
    except Exception as e:
        return False, f"M1 quality check error: {e}"


def _validate_price_not_at_extreme(
    entry_price: float,
    direction: str,
    daily_pivot: float,
    daily_s1: float | None,
    daily_r1: float | None,
    atr: float,
    m1_low: float,
    m1_high: float,
    m15_low: float,
    m15_high: float,
) -> tuple[bool, str]:
    """
    GATE: Price NOT at Extreme Levels
    
    Blocks entry if:
    - BUY price < (Daily Pivot - 1.5 ATR) → too low in range
    - SELL price > (Daily Pivot + 1.5 ATR) → too high in range
    - M1 price in lowest/highest 10% of M15 range
    """
    try:
        if atr <= 0 or daily_pivot <= 0:
            return True, "Cannot validate extremes (missing data)"
        
        # Check 1: Price vs Daily Pivot ± ATR
        extreme_low = daily_pivot - (atr * 1.5)
        extreme_high = daily_pivot + (atr * 1.5)
        
        if direction == "BUY" and entry_price < extreme_low:
            return False, f"BUY entry {entry_price:.2f} < extreme low {extreme_low:.2f}"
        elif direction == "SELL" and entry_price > extreme_high:
            return False, f"SELL entry {entry_price:.2f} > extreme high {extreme_high:.2f}"
        
        # Check 2: M1 price in extreme zone of M15
        m15_range = m15_high - m15_low
        if m15_range > 0:
            position_in_m15 = (entry_price - m15_low) / m15_range
            
            if position_in_m15 < 0.10:  # Bottom 10% of M15
                return False, f"Entry at bottom 10% of M15 range ({position_in_m15:.1%})"
            elif position_in_m15 > 0.90:  # Top 10% of M15
                return False, f"Entry at top 10% of M15 range ({position_in_m15:.1%})"
        
        return True, "Price level valid (not at extremes)"
    except Exception as e:
        return False, f"Extreme level check error: {e}"


def _validate_trend_strength_minimum(
    direction: str,
    direction_score: float,
    h1_trend: str,
    alignment_count: int,
) -> tuple[bool, str]:
    """
    GATE: Trend Strength Minimum
    
    Blocks if:
    - direction_score < 4.5 (< 45% of max 10)
    - H1 trend is "Weak" (must be "Strong" for confident entries)
    - Fewer than 3 of 5 timeframes aligned
    """
    try:
        # Check 1: Minimum score threshold (STRENGTHENED from 4.5 to 5.0)
        if direction_score < 5.0:
            return False, f"Setup quality insufficient ({direction_score:.2f}/{MAX_STRATEGY_SCORE:.1f}; need ≥5.0)"
        
        # Check 2: H1 trend strength requirement (must be Strong, not Weak)
        if "Weak" in str(h1_trend) and direction in TRADE_SIGNALS:
            return False, f"H1 trend too weak ({h1_trend}); need Strong Bullish/Bearish"
        
        # Check 3: Alignment requirement (need 3+ of 5 timeframes)
        if alignment_count < 3:
            return False, f"Insufficient alignment ({alignment_count}/5 timeframes; need ≥3)"
        
        return True, f"Trend strength valid (score={direction_score:.2f}, alignment={alignment_count}/5)"
    except Exception as e:
        return False, f"Trend strength check error: {e}"


def _validate_m5_momentum_confirmation(
    direction: str,
    m5_trend: str,
    m5_rsi: float,
    h1_direction: str,
) -> tuple[bool, str]:
    """
    GATE: M5 Momentum Direction Confirmation
    
    Blocks if:
    - M5 trend ≠ H1 direction (conflicted)
    - M5 RSI in wrong zone
    - M5 in pullback (opposite direction)
    """
    try:
        # Check 1: M5 trend must match H1 (no pullback)
        if h1_direction in TRADE_SIGNALS:
            h1_bullish = "Bullish" in str(h1_direction)
            m5_bullish = "Bullish" in str(m5_trend)
            
            if h1_bullish and not m5_bullish:
                return False, f"M5 bearish but H1 bullish (pullback likely)"
            elif not h1_bullish and m5_bullish:
                return False, f"M5 bullish but H1 bearish (pullback likely)"
        
        # Check 2: M5 RSI in correct zone
        if m5_rsi is not None:
            if direction == "BUY" and m5_rsi < 45:
                return False, f"M5 RSI {m5_rsi:.1f} too low for BUY (need >45)"
            elif direction == "SELL" and m5_rsi > 55:
                return False, f"M5 RSI {m5_rsi:.1f} too high for SELL (need <55)"
        
        return True, "M5 momentum confirmed"
    except Exception as e:
        return False, f"M5 momentum check error: {e}"


def _validate_m15_m5_alignment(
    direction: str,
    m15_trend: str,
    m5_trend: str,
    pullback_active: bool,
) -> tuple[bool, str]:
    """
    GATE: M15/M5 Alignment Check
    
    Blocks if:
    - For Momentum: M15 opposite to H1 (pullback still active)
    - For Pullback: M15/M5 cannot both be opposite
    """
    try:
        m15_bullish = "Bullish" in str(m15_trend)
        m5_bullish = "Bullish" in str(m5_trend)
        m15_bearish = "Bearish" in str(m15_trend)
        m5_bearish = "Bearish" in str(m5_trend)
        
        if direction == "BUY":
            # Both M15 and M5 must support BUY
            if not m15_bullish:
                return False, f"M15 not bullish ({m15_trend})"
            if not m5_bullish:
                return False, f"M5 not bullish ({m5_trend})"
        elif direction == "SELL":
            # Both M15 and M5 must support SELL
            if not m15_bearish:
                return False, f"M15 not bearish ({m15_trend})"
            if not m5_bearish:
                return False, f"M5 not bearish ({m5_trend})"
        
        return True, f"M15/M5 aligned (M15={m15_trend}, M5={m5_trend})"
    except Exception as e:
        return False, f"M15/M5 alignment check error: {e}"


def _validate_volume_surge(
    m1_volume: float,
    m1_volume_avg: float,
    m5_volume: float,
    m5_volume_avg: float,
) -> tuple[bool, str]:
    """
    GATE: Volume Surge on Entry Candle
    
    Blocks if:
    - M1 volume < 2× average M1 volume
    - M5 volume < 1.5× average M5 volume
    """
    try:
        # Check M1 volume
        if m1_volume_avg > 0 and m1_volume < m1_volume_avg * 2.0:
            return False, f"M1 volume low ({m1_volume:.0f} < {m1_volume_avg*2:.0f})"
        
        # Check M5 volume
        if m5_volume_avg > 0 and m5_volume < m5_volume_avg * 1.5:
            return False, f"M5 volume insufficient ({m5_volume:.0f} < {m5_volume_avg*1.5:.0f})"
        
        return True, "Volume surge confirmed"
    except Exception as e:
        return False, f"Volume check error: {e}"


def _validate_confluence_level(
    entry_price: float,
    daily_pivot: float,
    daily_s1: float | None,
    daily_r1: float | None,
    swing_high: float | None,
    swing_low: float | None,
) -> tuple[bool, str]:
    """
    GATE: Confluence Level Check
    
    Blocks if entry > 5 pips from ANY support/resistance:
    - Daily Pivot
    - Daily S1/R1
    - Previous swing high/low
    """
    try:
        confluence_levels = [daily_pivot]
        if daily_s1 is not None:
            confluence_levels.append(daily_s1)
        if daily_r1 is not None:
            confluence_levels.append(daily_r1)
        if swing_high is not None:
            confluence_levels.append(swing_high)
        if swing_low is not None:
            confluence_levels.append(swing_low)
        
        # Find closest level
        min_distance = min(abs(entry_price - level) for level in confluence_levels)
        
        if min_distance > 5.0:  # More than 5 pips from any level
            return False, f"Entry {entry_price:.2f} too far from confluence (nearest: {min_distance:.2f} pips)"
        
        return True, f"Confluence valid (distance: {min_distance:.2f} pips)"
    except Exception as e:
        return False, f"Confluence check error: {e}"


def _validate_session_rules(
    session: str,
    direction: str,
) -> tuple[bool, str]:
    """
    GATE: Session-Based Entry Restrictions
    
    - "Asian": Only BUY (gold buys in Asia)
    - "Dead" (21:00-00:00): Restricted entries
    - "Closed": NO ENTRIES
    """
    try:
        from risk_manager import get_current_session
        
        if session == "Closed":
            return False, "Market closed – no entries allowed"
        
        if session == "Dead" and direction in TRADE_SIGNALS:
            return False, "Dead hour (21:00-00:00) – restricted trading"
        
        if False and session == "Asian" and direction == "SELL":
            return False, "Asian session – SELL restricted (typically BUY only)"
        
        return True, f"Session rules met ({session})"
    except Exception as e:
        return False, f"Session check error: {e}"


def _run_entry_validations(
    direction: str,
    entry_method: str | None,
    direction_score: float,
    alignment_count: int,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Hard pre-entry checks shared by momentum and pullback-ready states."""
    reasons: list[str] = []
    validators: list[tuple[bool, str]] = []
    session = get_current_session()

    validators.append(_validate_session_rules(session, direction))
    validators.append(_validate_trend_strength_minimum(
        direction,
        direction_score,
        str(tfa.get("H1", {}).get("trend_classification", "Neutral")),
        alignment_count,
    ))

    if entry_method in {"momentum", "pullback"}:
        validators.append(_validate_m15_m5_alignment(
            direction,
            str(tfa.get("M15", {}).get("trend_classification", "Neutral")),
            str(tfa.get("M5", {}).get("trend_classification", "Neutral")),
            pullback_active=False,
        ))

    if entry_method == "momentum":
        m1 = tfi.get("M1", {})
        m5 = tfi.get("M5", {})
        validators.append(_validate_m1_candle_quality(
            m1,
            direction,
            _f(m1.get("average_volume_20")) or 0.0,
        ))
        validators.append(_validate_volume_surge(
            _f(m1.get("latest_volume", m1.get("volume"))) or 0.0,
            _f(m1.get("average_volume_20")) or 0.0,
            _f(m5.get("latest_volume", m5.get("volume"))) or 0.0,
            _f(m5.get("average_volume_20")) or 0.0,
        ))

    for passed, reason in validators:
        if not passed:
            reasons.append(reason)

    return len(reasons) == 0, reasons


def get_technical_signal(
    symbol: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    high_impact_news: bool = False,
) -> dict[str, Any]:
    required = set(RELEVANT_TIMEFRAMES)
    missing = sorted(required.difference(timeframe_indicators))
    if missing:
        return _empty(f"Missing timeframe data: {', '.join(missing)}.")

    try:
        tfi = timeframe_indicators
        tfa = {label: _evaluate_tf(tfi[label]) for label in RELEVANT_TIMEFRAMES}
        bias = _bias_context(tfi, tfa)
        volume = _volume_context(tfi)

        buy_patterns = detect_institutional_patterns("BUY", tfi, tfa)
        sell_patterns = detect_institutional_patterns("SELL", tfi, tfa)
        buy_score, buy_components = _directional_quality("BUY", bias, tfi, tfa, volume, buy_patterns)
        sell_score, sell_components = _directional_quality("SELL", bias, tfi, tfa, volume, sell_patterns)
        net_edge = round(buy_score - sell_score, 2)

        setup_direction = bias.get("direction", "NO TRADE")
        patterns = buy_patterns if setup_direction == "BUY" else sell_patterns if setup_direction == "SELL" else {}
        direction_score = buy_score if setup_direction == "BUY" else sell_score if setup_direction == "SELL" else 0.0
        final_score = (
            round(direction_score, 2)
            if setup_direction == "BUY"
            else round(-direction_score, 2)
            if setup_direction == "SELL"
            else 0.0
        )

        lower_dirs = {tfa[label]["direction"] for label in ("M15", "M5", "M1")} - {"NO TRADE"}
        mixed_signals = len(lower_dirs) > 1 and setup_direction == "NO TRADE"
        rsi_ctx = _rsi_context(setup_direction, tfi)
        pullback = _pullback_context(setup_direction, bias, tfi, tfa)
        phase, phase_strength = _phase_context(setup_direction, bias, tfa, patterns)
        m1_ready, m1_reason = _m1_trigger_ready(setup_direction, tfi, tfa)
        
        # NEW: Dual-entry evaluation (momentum vs pullback)
        momentum = _momentum_entry_conditions(setup_direction, bias, tfi, tfa, volume)
        pullback_cond = _pullback_entry_conditions(setup_direction, bias, tfi, tfa)
        alignment_count = _alignment_count(setup_direction, tfa)

        entry_state = "not_actionable"
        entry_method = None  # Track which entry method is active: "momentum" or "pullback"
        technical_signal = "NO TRADE"
        wait_reason = ""
        wait_trigger = ""

        if setup_direction not in TRADE_SIGNALS:
            entry_state = "no_higher_tf_bias"
        elif volume["dead"]:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_volume"
            wait_reason = volume["reason"]
            wait_trigger = "Wait for M15 participation to recover before evaluating entry again."
        # NEW: Momentum entry path (fast, no pullback wait required)
        elif momentum["momentum_ready"]:
            technical_signal = setup_direction
            entry_state = "ready_momentum"
            entry_method = "momentum"
            wait_reason = ""
            wait_trigger = ""
        # Fallback to pullback path
        elif pullback["active"]:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_pullback_completion"
            wait_reason = pullback["reason"]
            wait_trigger = f"{pullback['trigger']} {pullback['target_zone']}".strip()
        elif pullback_cond["pullback_ready"]:
            # Pullback has completed, now wait for M1 confirmation
            technical_signal = WAIT_SIGNAL
            entry_state = "ready_pullback_await_wick"
            entry_method = "pullback"
            wait_reason = "Pullback completed; awaiting M1 rejection wick confirmation."
            wait_trigger = "Look for M1 rejection wick and CVD divergence."
        elif rsi_ctx["exhausted"]:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_rsi_reset"
            wait_reason = rsi_ctx["reason"]
            wait_trigger = "Wait for the stretched move to cool off and then re-check M1."
        elif not m1_ready:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_m1_confirmation"
            wait_reason = m1_reason
            wait_trigger = "Wait for M1 to align with the higher-timeframe direction."
        elif direction_score >= 4.5:
            technical_signal = WAIT_SIGNAL
            entry_state = "ready_pullback_await_wick"
            entry_method = "pullback"
            wait_reason = "Directional structure is ready; awaiting final M1 wick confirmation."
            wait_trigger = "Look for a closed M1 rejection candle with no CVD conflict."
        elif direction_score >= 3.0:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_quality_expansion"
            wait_reason = f"{setup_direction} bias exists, but the setup quality is still only {direction_score:.2f}/{MAX_STRATEGY_SCORE:.1f}."
            wait_trigger = "Wait for M15/M5 continuation to strengthen before entry."
        else:
            entry_state = "weak_setup"

        validation_reasons: list[str] = []
        if setup_direction in TRADE_SIGNALS and entry_state in {"ready_momentum", "ready_pullback_await_wick", "ready"}:
            validation_method = entry_method or ("momentum" if entry_state == "ready" else None)
            validation_passed, validation_reasons = _run_entry_validations(
                setup_direction,
                validation_method,
                direction_score,
                alignment_count,
                tfi,
                tfa,
            )
            if not validation_passed:
                technical_signal = WAIT_SIGNAL
                entry_state = "wait_for_quality_expansion"
                wait_reason = " | ".join(validation_reasons)
                wait_trigger = "Wait for the failed hard gates to reset before entry."
                entry_method = None

        technical_confidence = _confidence(
            setup_direction=setup_direction,
            direction_score=direction_score,
            bias=bias,
            alignment_count=alignment_count,
            volume=volume,
            rsi_ctx=rsi_ctx,
            patterns=patterns,
            entry_state=entry_state,
            high_impact_news=high_impact_news,
            h4_bias=tfa.get("H4", {}).get("direction", "NO TRADE"),
            h1_direction=tfa.get("H1", {}).get("direction", "NO TRADE"),
            cvd_result=None,  # CVD is calculated in main.py after get_technical_signal()
        )
        trade_levels = _build_levels(setup_direction, tfi)
        risk_level = _risk_level(bias, volume, rsi_ctx, mixed_signals, entry_state)

        gates: dict[str, Any] = {
            "all_vol_low": volume["dead"],
            "m15_volume_thin": volume["thin"],
            "m15_volume_reason": volume["reason"],
            "h4_conflict_warning": bias.get("h4_conflict_warning", False),
            "h4_status": bias.get("h4_conflict_warning", False),
            "higher_tf_conflict": bias.get("conflicted", False),
            "higher_tf_reason": bias.get("reason", "") if bias.get("conflicted", False) else "",
            "higher_tf_bias": setup_direction if setup_direction in TRADE_SIGNALS else "",
            "higher_tf_bias_reason": bias.get("reason", ""),
            "h4_primary_bias": bias.get("direction", "NO TRADE"),
            "h1_structure_confirmed": tfa.get("H1", {}).get("direction", "NO TRADE") == setup_direction,
            "rsi_exhausted": rsi_ctx["exhausted"],
            "rsi_caution": rsi_ctx["caution"],
            "m1_counter": technical_signal == WAIT_SIGNAL and entry_state == "wait_for_m1_confirmation",
            "m1_counter_reason": m1_reason if entry_state == "wait_for_m1_confirmation" else "",
            "wait_for_confirmation": technical_signal == WAIT_SIGNAL,
            "wait_reason": wait_reason,
            "wait_trigger": wait_trigger,
            "entry_timing_state": entry_state,
            "entry_method": entry_method,  # NEW: Track momentum vs pullback
            "hard_gate_passed": len(validation_reasons) == 0,
            "hard_gate_reasons": validation_reasons,
            "momentum_ready": momentum["momentum_ready"],  # NEW
            "momentum_rsi": momentum.get("m5_rsi"),  # NEW
            "momentum_reason": momentum["reason"],  # NEW
            "momentum_recent_m15_shift_confirmed": momentum.get("recent_m15_shift_confirmed", True),
            "momentum_recent_m15_shift_reason": momentum.get("recent_m15_shift_reason", ""),
            "pullback_in_progress": pullback["active"],
            "pullback_detection_reason": pullback["reason"],
            "pullback_reversal_ready": not pullback["active"],
            "pullback_ready_reason": "" if pullback["active"] else "Lower timeframes aligned with higher-timeframe bias.",
            "pullback_target_zone": pullback["target_zone"],
            "structured_pullback_reentry": pullback["structured_reentry"],
            "wyckoff_phase": phase,
            "wyckoff_phase_strength": phase_strength,
            "wyckoff_phase_reason": f"{phase} context derived from higher-timeframe bias and lower-timeframe behaviour.",
            "wyckoff_valid": phase in {"SPRING", "UPTHRUST", "MARKUP", "MARKDOWN"},
            "wyckoff_validation": "Phase is supportive." if phase in {"SPRING", "UPTHRUST", "MARKUP", "MARKDOWN"} else "No supportive phase.",
            "wyckoff_imbalances": [],
            "is_upthrust": patterns.get("is_upthrust", False),
            "upthrust_severity": patterns.get("upthrust_severity", 0.0),
            "is_liquidity_sweep": patterns.get("is_liquidity_sweep", False),
            "sweep_type": patterns.get("sweep_type", ""),
            "sweep_severity": patterns.get("sweep_severity", 0.0),
            "patterns_adjustment": patterns.get("confidence_adjustment", 0.0),
            "confluence_bonus": max(0.0, alignment_count - 2) * 2.0,
            "confluence_reason": f"{alignment_count}/5 timeframes align with {setup_direction}." if setup_direction in TRADE_SIGNALS else "",
            "volatility_adjusted_threshold": 4.5,
        }

        scorecard = {
            "buy_score": buy_score,
            "sell_score": sell_score,
            "final_score": final_score,
            "net_edge": net_edge,
            "max_score": MAX_STRATEGY_SCORE,
            "buy_components": buy_components,
            "sell_components": sell_components,
            "bias_reason": bias.get("reason", ""),
            "directional_score": direction_score,
        }

        execute_signal = technical_signal if technical_signal in TRADE_SIGNALS else "NO TRADE"
        signal_status = (
            "READY"
            if technical_signal in TRADE_SIGNALS
            else "WAIT"
            if technical_signal == WAIT_SIGNAL
            else "NO_TRADE"
        )
        
        # NOTE: H4 confidence filter now integrated into _confidence() function with nuanced modifiers

        log_debug(
            f"Strategy engine | bias={setup_direction} | state={technical_signal} | "
            f"buy={buy_score:.2f} | sell={sell_score:.2f} | score={final_score:+.2f} | edge={net_edge:+.2f} | "
            f"conf={technical_confidence}% | risk={risk_level}"
        )

        trap_filter_status = (
            "HardGates: OK"
            if not validation_reasons
            else "HardGates: BLOCKED | " + " | ".join(validation_reasons)
        )

        return {
            "technical_signal": technical_signal,
            "bias_direction": setup_direction,
            "setup_direction": setup_direction,
            "execute_signal": execute_signal,
            "trigger_state": entry_state,
            "signal_status": signal_status,
            "weighted_score": final_score,
            "max_score": MAX_STRATEGY_SCORE,
            "technical_confidence": technical_confidence,
            "scorecard": scorecard,
            "timeframe_analysis": tfa,
            "mixed_signals": mixed_signals,
            "risk_level": risk_level,
            "trade_levels": trade_levels,
            "gates": gates,
            "entry_timing_state": entry_state,
            "wait_reason": wait_reason,
            "wait_trigger": wait_trigger,
            "trap_filter_status": trap_filter_status,
        }
    except Exception as exc:
        log_debug(f"Strategy engine failed: {exc}")
        return _empty(str(exc))
