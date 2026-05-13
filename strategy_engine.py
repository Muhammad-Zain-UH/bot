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
    h4 = tfa.get("H4", {})
    h1 = tfa.get("H1", {})
    h4_dir = h4.get("direction", "NO TRADE")
    h1_dir = h1.get("direction", "NO TRADE")
    h4_trend = str(h4.get("trend_classification", "Neutral"))
    h1_trend = str(h1.get("trend_classification", "Neutral"))
    h4_strength = _clip((_f(tfi.get("H4", {}).get("trend_strength_ratio")) or 0.0) / 1.2, 0.0, 1.0)
    h1_strength = _clip((_f(tfi.get("H1", {}).get("trend_strength_ratio")) or 0.0) / 1.2, 0.0, 1.0)

    if h4_dir == h1_dir and h4_dir in TRADE_SIGNALS:
        strength = 0.55 + ((h4_strength * 0.55) + (h1_strength * 0.45)) * 0.35
        return {
            "direction": h4_dir,
            "strength": round(_clip(strength, 0.55, 0.95), 2),
            "conflicted": False,
            "h1_countertrend": False,
            "reason": f"H4 and H1 align {h4_dir} ({h4_trend} / {h1_trend}).",
        }

    if h4_dir in TRADE_SIGNALS and h1_dir == "NO TRADE":
        strength = 0.45 + (h4_strength * 0.25)
        return {
            "direction": h4_dir,
            "strength": round(_clip(strength, 0.45, 0.75), 2),
            "conflicted": False,
            "h1_countertrend": False,
            "reason": f"H4 carries the structural {h4_dir} bias while H1 is neutral.",
        }

    if h4_dir in TRADE_SIGNALS and h1_dir in TRADE_SIGNALS and h4_dir != h1_dir:
        h4_is_strong = h4_trend.startswith("Strong")
        h1_is_weak = h1_trend.startswith("Weak")
        if h4_is_strong and h1_is_weak:
            return {
                "direction": h4_dir,
                "strength": 0.56,
                "conflicted": True,
                "h1_countertrend": True,
                "reason": f"H4 remains {h4_trend} while H1 shows only a weak countertrend pullback.",
            }
        if h4_is_strong:
            return {
                "direction": h4_dir,
                "strength": 0.50,
                "conflicted": True,
                "h1_countertrend": True,
                "reason": f"H4 is structurally {h4_trend}, but H1 is still pushing {h1_trend}; wait for re-alignment.",
            }
        return {
            "direction": "NO TRADE",
            "strength": 0.0,
            "conflicted": True,
            "h1_countertrend": False,
            "reason": f"H4 ({h4_trend}) and H1 ({h1_trend}) conflict without a dominant structure.",
        }

    if h4_dir == "NO TRADE" and h1_dir in TRADE_SIGNALS and h1_strength >= 0.6:
        return {
            "direction": h1_dir,
            "strength": 0.42,
            "conflicted": False,
            "h1_countertrend": False,
            "reason": f"H1 is the only tradeable bias ({h1_trend}); H4 has no clear structure.",
        }

    return {
        "direction": "NO TRADE",
        "strength": 0.0,
        "conflicted": False,
        "h1_countertrend": False,
        "reason": "Higher timeframes do not provide a usable directional bias.",
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

    aligned_higher = tfa.get("H4", {}).get("direction") == direction and tfa.get("H1", {}).get("direction") in {direction, "NO TRADE"}
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
        "h4_h1_alignment": 0.0,
        "m15_structure": 0.0,
        "m5_trigger": 0.0,
        "m1_trigger": 0.0,
        "volume": 0.0,
        "rsi": 0.0,
        "pivot_context": 0.0,
        "patterns": 0.0,
    }

    if bias.get("direction") == direction:
        components["bias"] = 2.2 + (bias.get("strength", 0.0) * 1.8)
        if not bias.get("conflicted", False):
            components["h4_h1_alignment"] = 1.0
        else:
            components["h4_h1_alignment"] = -0.5
    elif bias.get("direction") in TRADE_SIGNALS:
        components["bias"] = -1.8
        components["h4_h1_alignment"] = -1.0

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

    if entry is None or atr in {None, 0.0}:
        return {
            "entry_price": entry,
            "stop_loss": None,
            "take_profit": None,
            "risk_distance": None,
            "pullback_target": None,
        }

    risk_distance = max(atr * 1.35, 6.0)

    if direction == "BUY":
        stop_loss = entry - risk_distance
        if daily_s1 is not None and entry - daily_s1 < risk_distance * 1.4:
            stop_loss = min(stop_loss, daily_s1 - (atr * 0.15))
        take_profit = entry + (abs(entry - stop_loss) * 2.0)
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
        take_profit = entry - (abs(stop_loss - entry) * 2.0)
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
) -> int:
    if setup_direction not in TRADE_SIGNALS:
        return 0

    confidence = 28.0
    confidence += bias.get("strength", 0.0) * 24.0
    confidence += max(0.0, direction_score) * 5.0
    confidence += alignment_count * 4.0

    if patterns.get("is_liquidity_sweep"):
        confidence += 4.0
    if patterns.get("is_upthrust"):
        confidence -= 6.0
    if volume.get("thin"):
        confidence -= 8.0
    if volume.get("dead"):
        confidence -= 15.0
    if rsi_ctx.get("caution"):
        confidence -= 4.0
    if rsi_ctx.get("exhausted"):
        confidence -= 12.0
    if entry_state != "ready":
        confidence -= 5.0
    if high_impact_news:
        confidence -= 6.0

    return int(round(_clip(confidence, 20.0, 92.0)))


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

        entry_state = "not_actionable"
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
        elif pullback["active"]:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_pullback_completion"
            wait_reason = pullback["reason"]
            wait_trigger = f"{pullback['trigger']} {pullback['target_zone']}".strip()
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
            technical_signal = setup_direction
            entry_state = "ready"
        elif direction_score >= 3.0:
            technical_signal = WAIT_SIGNAL
            entry_state = "wait_for_quality_expansion"
            wait_reason = f"{setup_direction} bias exists, but the setup quality is still only {direction_score:.2f}/{MAX_STRATEGY_SCORE:.1f}."
            wait_trigger = "Wait for M15/M5 continuation to strengthen before entry."
        else:
            entry_state = "weak_setup"

        alignment_count = _alignment_count(setup_direction, tfa)
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
        )
        trade_levels = _build_levels(setup_direction, tfi)
        risk_level = _risk_level(bias, volume, rsi_ctx, mixed_signals, entry_state)

        gates: dict[str, Any] = {
            "all_vol_low": volume["dead"],
            "m15_volume_thin": volume["thin"],
            "m15_volume_reason": volume["reason"],
            "higher_tf_conflict": bias.get("conflicted", False),
            "higher_tf_reason": bias.get("reason", "") if bias.get("conflicted", False) else "",
            "higher_tf_bias": setup_direction if setup_direction in TRADE_SIGNALS else "",
            "higher_tf_bias_reason": bias.get("reason", ""),
            "rsi_exhausted": rsi_ctx["exhausted"],
            "rsi_caution": rsi_ctx["caution"],
            "m1_counter": technical_signal == WAIT_SIGNAL and entry_state == "wait_for_m1_confirmation",
            "m1_counter_reason": m1_reason if entry_state == "wait_for_m1_confirmation" else "",
            "wait_for_confirmation": technical_signal == WAIT_SIGNAL,
            "wait_reason": wait_reason,
            "wait_trigger": wait_trigger,
            "entry_timing_state": entry_state,
            "structured_pullback_reentry": pullback["structured_reentry"],
            "pullback_in_progress": pullback["active"],
            "pullback_detection_reason": pullback["reason"],
            "pullback_reversal_ready": not pullback["active"],
            "pullback_ready_reason": "" if pullback["active"] else "Lower timeframes aligned with higher-timeframe bias.",
            "pullback_target_zone": pullback["target_zone"],
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

        log_debug(
            f"Strategy engine | bias={setup_direction} | state={technical_signal} | "
            f"buy={buy_score:.2f} | sell={sell_score:.2f} | score={final_score:+.2f} | edge={net_edge:+.2f} | "
            f"conf={technical_confidence}% | risk={risk_level}"
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
        }
    except Exception as exc:
        log_debug(f"Strategy engine failed: {exc}")
        return _empty(str(exc))
