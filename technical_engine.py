"""Improved technical decision engine for intraday XAUUSD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from confidence_calibrator import calibrate_technical_confidence
from utils import log_debug

WAIT_SIGNAL = "WAIT_FOR_CONFIRMATION"
TRADE_SIGNALS = {"BUY", "SELL"}

WEIGHTS = {
    "ema_trend": 2.0,       # 20% of M15 score
    "vwap_position": 1.5,   # 15%
    "rsi": 1.5,             # 15%
    "volume": 1.25,         # 12% (increased from 6% - critical for gold)
    "volume_spike": 0.75,   # 7%
}

BULLISH_TRENDS = {"Strong Bullish", "Weak Bullish"}
BEARISH_TRENDS = {"Strong Bearish", "Weak Bearish"}
STRONG_TRENDS = {"Strong Bullish", "Strong Bearish"}

ENTRY_PULLBACK_M5_ATR_FACTOR = 0.50
LOW_VOLUME_RATIO = 0.70  # Score penalty threshold for thin participation
GENUINELY_DEAD_VOLUME_RATIO = 0.50
GENUINELY_DEAD_TICK_VOLUME = 200.0
HIGH_VOLUME_RATIO = 1.10
LOW_VOLUME_PENALTY = 0.80
LOW_VOLUME_TREND_PENALTY = 0.40
COUNTERTREND_REJECTION_SCORE = 4.00
MIN_CONFIDENCE_THRESHOLD = 55  # Lowered from 60 to generate more signals
LIVE_ENTRY_WEIGHTS = {"M5": 0.12, "M1": 0.18}
ENTRY_RSI_IDEALS = {"BUY": 58.0, "SELL": 42.0}
ENTRY_RSI_WINDOW = 18.0

RSI_EXHAUSTION_SELL = 25.0  # Wilder standard for oversold
RSI_EXHAUSTION_BUY = 75.0   # Wilder standard for overbought
RSI_CAUTION_SELL = 30.0     # Wilder standard light zone
RSI_CAUTION_BUY = 70.0      # Wilder standard light zone

M1_COUNTER_SELL_RSI = 60.0
M1_COUNTER_BUY_RSI = 40.0
M5_REVERSAL_BUY_RSI = 52.0
M5_REVERSAL_SELL_RSI = 48.0
M1_VOL_HIGH_ENTRY = 1.05
M1_VOL_NORM_ENTRY = 0.95

SIGNAL_SCORE_THRESHOLD = 1.0  # Lowered from 2.0 - allow scores 1.0+ to generate BUY/SELL
WAIT_SCORE_FLOOR = 0.5      # Lowered from 1.0 - WAIT state for weaker setups

ENTRY_TIMEFRAMES = ("M15", "M5", "M1")
HIGHER_TIMEFRAMES = ("H4", "H1")
TIMEFRAME_CONFIRM_WEIGHTS = {"H4": 1.0, "H1": 1.5, "M5": 2.0, "M1": 1.0}

MAX_WEIGHTED_SCORE = sum(WEIGHTS.values()) + sum(TIMEFRAME_CONFIRM_WEIGHTS.values())

# FIX: Session-aware minimum confidence thresholds (RELAXED for profitability)
MIN_CONFIDENCE_BY_SESSION = {
    "LondonNewYork": 45,  # Best session - most trades
    "London": 48,
    "NewYork": 49,
    "Asian": 50,          # Quieter but tradeable
    "Dead": 52,           # Allow trading with risk management
    "Closed": 99,
}


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


def _volume_is_genuinely_dead(ind: dict[str, Any]) -> bool:
    """Hard-block only when both relative and absolute volume are dead."""
    vr = _f(ind.get("volume_ratio"))
    latest_volume = _f(ind.get("latest_volume"))
    if vr is None or latest_volume is None:
        return False
    return vr < GENUINELY_DEAD_VOLUME_RATIO and latest_volume < GENUINELY_DEAD_TICK_VOLUME


def _all_vol_low(tfi: dict[str, dict[str, Any]]) -> bool:
    for label in ENTRY_TIMEFRAMES:
        if not _volume_is_genuinely_dead(tfi.get(label, {})):
            return False
    return True


def _m15_vol_thin(tfi: dict[str, dict[str, Any]]) -> bool:
    vr = _f(tfi.get("M15", {}).get("volume_ratio"))
    return vr is not None and vr < LOW_VOLUME_RATIO


def _detect_mixed_signals(tfa: dict[str, dict[str, Any]]) -> bool:
    """Detect when entry timeframes have conflicting directional signals.
    
    FIX: Only flag as mixed if no clear higher TF bias exists.
    In a trending market, pullbacks on lower TF = normal, not "mixed".
    """
    # Check for clear higher timeframe bias
    h4_dir = tfa.get("H4", {}).get("direction", "NO TRADE")
    h1_dir = tfa.get("H1", {}).get("direction", "NO TRADE")
    
    # If H4 and H1 agree, lower TF variations are structured, not conflicted
    if h4_dir in {"BUY", "SELL"} and h4_dir == h1_dir:
        return False  # Clear bias exists, pullbacks are expected
    
    # Only flag as mixed if higher TF is unclear AND entry TF disagree
    directions = {
        tfa.get("M15", {}).get("direction", "NO TRADE"),
        tfa.get("M5", {}).get("direction", "NO TRADE"),
        tfa.get("M1", {}).get("direction", "NO TRADE"),
    } - {"NO TRADE"}
    
    return len(directions) > 1  # True only if entry TFs really conflict


def _m1_vol_high(m1: dict[str, Any]) -> bool:
    ratio = _f(m1.get("atr_ratio"))
    if ratio is None:
        return False
    if str(m1.get("volatility_classification", "Normal")) == "High":
        return ratio >= M1_VOL_NORM_ENTRY
    return ratio >= M1_VOL_HIGH_ENTRY


def _evaluate_tf(ind: dict[str, Any]) -> dict[str, Any]:
    trend = str(ind.get("trend_classification", "Neutral"))
    direction = _trend_dir(trend)
    pvwap = str(ind.get("price_vs_vwap", "Unknown"))
    return {
        "trend_classification": trend,
        "direction": direction,
        "price_vs_vwap": pvwap,
        "rsi_signal": str(ind.get("rsi_signal", "Unavailable")),
        "strong_trend": trend in STRONG_TRENDS,
        "vwap_aligned": (
            (direction == "BUY" and pvwap == "Above")
            or (direction == "SELL" and pvwap == "Below")
        ),
    }


def _higher_tf_bias(tfa: dict[str, dict[str, Any]]) -> tuple[str, int, str]:
    h4_dir = tfa.get("H4", {}).get("direction", "NO TRADE")
    h1_dir = tfa.get("H1", {}).get("direction", "NO TRADE")
    h4_trend = str(tfa.get("H4", {}).get("trend_classification", "Neutral"))
    h1_trend = str(tfa.get("H1", {}).get("trend_classification", "Neutral"))
    if h4_dir == h1_dir and h4_dir in TRADE_SIGNALS:
        return h4_dir, 2, f"H4 {h4_trend} and H1 {h1_trend} align {h4_dir}."
    if h4_dir in TRADE_SIGNALS and h1_dir == "NO TRADE":
        return h4_dir, 1, f"H4 {h4_trend} leads while H1 is neutral."
    if h1_dir in TRADE_SIGNALS and h4_dir == "NO TRADE":
        return h1_dir, 1, f"H1 {h1_trend} leads while H4 is neutral."
    return "NO TRADE", 0, ""


def _apply_volume_penalty(
    weighted_score: float,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> tuple[float, bool, float, str]:
    if not _m15_vol_thin(tfi):
        return weighted_score, False, 0.0, ""
    m15_vol = _f(tfi.get("M15", {}).get("volume_ratio"))
    if m15_vol is None:
        return weighted_score, False, 0.0, ""
    m15_dir = tfa.get("M15", {}).get("direction", "NO TRADE")
    htf_bias, _, _ = _higher_tf_bias(tfa)
    thinness = _clip((LOW_VOLUME_RATIO - m15_vol) / LOW_VOLUME_RATIO, 0.0, 1.0)
    penalty_pct = 0.05 + (thinness * 0.17)
    if htf_bias in TRADE_SIGNALS and htf_bias == m15_dir:
        penalty_pct *= 0.80
    penalized = weighted_score * (1.0 - penalty_pct)
    penalty_amount = abs(weighted_score - penalized)  # For logging
    reason = (
        f"M15 volume thin ({m15_vol:.3f}) - "
        f"{penalty_pct*100:.0f}% proportional score penalty applied."
    )
    return penalized, True, penalty_amount, reason


def _score(primary: dict[str, Any]) -> dict[str, Any]:
    buy = 0.0
    sell = 0.0
    components = {key: 0.0 for key in WEIGHTS}
    trend = str(primary.get("trend_classification", "Neutral"))
    direction = _trend_dir(trend)
    if direction == "BUY":
        weight = WEIGHTS["ema_trend"] if trend.startswith("Strong") else 1.50
        buy += weight
        components["ema_trend"] = weight
    elif direction == "SELL":
        weight = WEIGHTS["ema_trend"] if trend.startswith("Strong") else 1.50
        sell += weight
        components["ema_trend"] = -weight
    pvwap = str(primary.get("price_vs_vwap", "Unknown"))
    if pvwap == "Above":
        buy += WEIGHTS["vwap_position"]
        components["vwap_position"] = WEIGHTS["vwap_position"]
    elif pvwap == "Below":
        sell += WEIGHTS["vwap_position"]
        components["vwap_position"] = -WEIGHTS["vwap_position"]
    rsi_sig = str(primary.get("rsi_signal", "Unavailable"))
    if rsi_sig == "Bullish Continuation":
        buy += WEIGHTS["rsi"]
        components["rsi"] = WEIGHTS["rsi"]
    elif rsi_sig == "Bearish Continuation":
        sell += WEIGHTS["rsi"]
        components["rsi"] = -WEIGHTS["rsi"]
    
    vc = str(primary.get("volume_classification", "Unknown"))
    vr = _f(primary.get("volume_ratio"))
    vol_low = vc == "Low" or (vr is not None and vr < LOW_VOLUME_RATIO)
    vol_high = vc == "High"
    if vol_high and direction in TRADE_SIGNALS:
        if direction == "BUY":
            buy += WEIGHTS["volume"]
            components["volume"] = WEIGHTS["volume"]
        else:
            sell += WEIGHTS["volume"]
            components["volume"] = -WEIGHTS["volume"]
    if primary.get("volume_spike"):
        if direction == "BUY":
            buy += WEIGHTS["volume_spike"]
            components["volume_spike"] = WEIGHTS["volume_spike"]
        elif direction == "SELL":
            sell += WEIGHTS["volume_spike"]
            components["volume_spike"] = -WEIGHTS["volume_spike"]
    return {
        "buy_score": buy,
        "sell_score": sell,
        "final_score": buy - sell,
        "score_direction": "BUY" if buy > sell else ("SELL" if sell > buy else "NO TRADE"),
        "components": components,
        "vol_penalized": vol_low,
    }


def _confirmation_components(tfa: dict[str, dict[str, Any]]) -> dict[str, Any]:
    buy = 0.0
    sell = 0.0
    net = 0.0
    components = {label: 0.0 for label in TIMEFRAME_CONFIRM_WEIGHTS}
    for label, weight in TIMEFRAME_CONFIRM_WEIGHTS.items():
        direction = tfa.get(label, {}).get("direction", "NO TRADE")
        if direction == "BUY":
            buy += weight
            net += weight
            components[label] = weight
        elif direction == "SELL":
            sell += weight
            net -= weight
            components[label] = -weight
    return {"buy_score": buy, "sell_score": sell, "net_score": net, "components": components}


def _entry_rsi_quality(direction: str, rsi: float | None) -> float:
    if direction not in TRADE_SIGNALS or rsi is None:
        return 0.0
    ideal = ENTRY_RSI_IDEALS[direction]
    return _clip(1.0 - (abs(rsi - ideal) / ENTRY_RSI_WINDOW), 0.0, 1.0)


def _live_entry_components(
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buy = 0.0
    sell = 0.0
    net = 0.0
    components = {label: 0.0 for label in LIVE_ENTRY_WEIGHTS}
    for label, weight in LIVE_ENTRY_WEIGHTS.items():
        direction = tfa.get(label, {}).get("direction", "NO TRADE")
        if direction not in TRADE_SIGNALS:
            continue
        rsi_quality = _entry_rsi_quality(direction, _f(tfi.get(label, {}).get("rsi_14")))
        trend_strength = _clip((_f(tfi.get(label, {}).get("trend_strength_ratio")) or 0.0) / 1.0, 0.0, 1.0)
        live_score = weight * ((0.75 * rsi_quality) + (0.25 * trend_strength))
        if direction == "BUY":
            buy += live_score
            net += live_score
            components[label] = live_score
        else:
            sell += live_score
            net -= live_score
            components[label] = -live_score
    return {"buy_score": buy, "sell_score": sell, "net_score": net, "components": components}


def _rsi_exhaustion(signal: str, tfi: dict[str, dict[str, Any]]) -> tuple[bool, bool, str]:
    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
    if signal == "SELL":
        if m1_rsi is not None and m1_rsi < 30.0:
            return False, True, f"RSI caution: M1 RSI {m1_rsi:.1f} is oversold."
        if m15_rsi is not None and m15_rsi < RSI_EXHAUSTION_SELL:
            return True, False, f"RSI stretched: M15 RSI {m15_rsi:.1f} is deeply oversold."
        if m15_rsi is not None and m5_rsi is not None and m15_rsi < RSI_CAUTION_SELL and m5_rsi < RSI_CAUTION_SELL:
            return False, True, f"RSI caution: M15 {m15_rsi:.1f} and M5 {m5_rsi:.1f} are oversold."
    if signal == "BUY":
        # CRITICAL FIX: M1 RSI > 75 is a hard exhaustion block (not just caution)
        if m1_rsi is not None and m1_rsi > 75.0:
            return True, False, f"RSI EXHAUSTION: M1 RSI {m1_rsi:.1f} is extreme overbought - wait for pullback."
        if m1_rsi is not None and m1_rsi > 70.0:
            return False, True, f"RSI caution: M1 RSI {m1_rsi:.1f} is overbought."
        if m15_rsi is not None and m15_rsi > RSI_EXHAUSTION_BUY:
            return True, False, f"RSI stretched: M15 RSI {m15_rsi:.1f} is deeply overbought."
        if m15_rsi is not None and m5_rsi is not None and m15_rsi > RSI_CAUTION_BUY and m5_rsi > RSI_CAUTION_BUY:
            return False, True, f"RSI caution: M15 {m15_rsi:.1f} and M5 {m5_rsi:.1f} are overbought."
    return False, False, ""


def _m1_counter(signal: str, tfi: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    rsi = _f(tfi.get("M1", {}).get("rsi_14"))
    trend = str(tfi.get("M1", {}).get("trend_classification", "Neutral"))
    if signal == "SELL" and rsi is not None and rsi > M1_COUNTER_SELL_RSI:
        return True, f"M1 bounce: RSI {rsi:.1f} ({trend}) - wait for RSI < {M1_COUNTER_SELL_RSI:.0f}."
    if signal == "BUY" and rsi is not None and rsi < M1_COUNTER_BUY_RSI:
        return True, f"M1 pullback: RSI {rsi:.1f} ({trend}) - wait for RSI > {M1_COUNTER_BUY_RSI:.0f}."
    return False, ""


def _higher_tf_conflict(signal: str, tfa: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    """SOFTENED: Check higher timeframe conflicts but allow override with high confidence.
    
    H1 opposition now triggers a confidence penalty (-12%) rather than hard block.
    This allows strong lower-TF setups to trade against intraday bias if conditions are right.
    H4 opposition is secondary and weaker penalty.
    
    Returns (conflict_detected, reason)
    Caller uses this to penalize confidence, not block trades outright.
    """
    if signal not in TRADE_SIGNALS:
        return False, ""
    
    h4_dir = tfa.get("H4", {}).get("direction", "NO TRADE")
    h1_dir = tfa.get("H1", {}).get("direction", "NO TRADE")
    h4_trend = str(tfa.get("H4", {}).get("trend_classification", "Neutral"))
    h1_trend = str(tfa.get("H1", {}).get("trend_classification", "Neutral"))
    
    # FIX: H1 opposition now triggers confidence penalty, not hard block
    # This allows strong M15 setups to trade if confidence stays high (65%+)
    if h1_dir in TRADE_SIGNALS and h1_dir != signal:
        return True, f"! H1 {h1_trend} opposes {signal} (confidence penalty applied)."
    
    # Secondary: H4 opposition is a weaker flag
    if h4_dir in TRADE_SIGNALS and h4_dir != signal:
        return True, f"! H4 {h4_trend} opposes {signal} (minor penalty)."
    
    return False, ""


def _rsi_conf(direction: str, rsi: float | None) -> float:
    if rsi is None:
        return 1.5
    if direction == "BUY":
        if 50 <= rsi <= 65:
            return 12.0
        if 65 < rsi <= 73:
            return 6.0
        if rsi > 73:
            return 2.0
        if 45 <= rsi < 50:
            return 4.0
    if direction == "SELL":
        if 35 <= rsi < 50:
            return 12.0
        if 27 <= rsi < 35:
            return 2.0
        if rsi < 27:
            return 1.0
        if 50 <= rsi <= 55:
            return 4.0
    return 0.0


def _vol_conf(primary: dict[str, Any], thin_volume: bool) -> float:
    vr = _f(primary.get("volume_ratio"))
    vc = str(primary.get("volume_classification", "Unknown"))
    if vr is None or vc == "Unknown":
        return -1.0
    if thin_volume:
        return max(-3.0, (vr - LOW_VOLUME_RATIO) * 8.0)
    if vc == "High":
        return 6.0
    if vr >= HIGH_VOLUME_RATIO:
        return 3.0
    # NORMAL volume (0.85-1.10) gets modest confidence boost for healthy participation
    if vr >= LOW_VOLUME_RATIO:
        return 1.5
    return 0.0


def _align_conf(direction: str, tfa: dict[str, dict[str, Any]]) -> float:
    if direction not in TRADE_SIGNALS:
        return 0.0
    score = 0.0
    for label, weight in (("H4", 5.0), ("H1", 4.0), ("M15", 4.0), ("M5", 3.0), ("M1", 1.5)):
        current = tfa.get(label, {}).get("direction", "NO TRADE")
        if current == direction:
            score += weight
        elif current in TRADE_SIGNALS:
            score -= weight * 0.80
    return max(-10.0, min(10.0, score))


def _calculate_confidence(
    direction: str,
    scorecard: dict[str, Any],
    tfa: dict[str, dict[str, Any]],
    tfi: dict[str, dict[str, Any]],
    mixed: bool,
    high_news: bool,
    rsi_caution: bool,
    rsi_exhausted: bool,
    m1_counter: bool,
    waiting: bool,
    thin_volume: bool = False,
    higher_tf_conflict: bool = False,
) -> int:
    primary = tfi.get("M15", {})
    m1 = tfi.get("M1", {})
    tsr = _f(primary.get("trend_strength_ratio")) or 0.0
    rsi_val = _f(primary.get("rsi_14"))
    atr_ratio = _f(primary.get("atr_ratio")) or 1.0
    m1_atr = _f(m1.get("atr_ratio")) or 1.0
    
    # GATE #1: Thin volume graduated penalty (NOT hard cap)
    vol_ratio = _f(primary.get("volume_ratio"))
    thin_vol_penalty = 0.0
    if thin_volume and vol_ratio is not None and vol_ratio < 0.5:
        # Penalty: up to 50% for critically thin volume, proportional to thinness
        thin_vol_penalty = min(50.0, (0.5 - vol_ratio) * 100.0)
        log_debug(f"THIN VOLUME PENALTY: ratio {vol_ratio:.3f} < 0.5 — {thin_vol_penalty:.0f}% penalty (allow trade)")
    
    confidence = 22.0
    confidence += min(abs(scorecard.get("final_score", 0.0)) / MAX_WEIGHTED_SCORE, 1.0) * 14.0
    confidence += min(tsr / 0.75, 1.0) * 16.0
    confidence += _align_conf(direction, tfa)
    confidence += _rsi_conf(direction, rsi_val)
    confidence += _vol_conf(primary, scorecard.get("volume_penalty_applied", False))
    confidence += max(-3.0, 5.0 - max(0.0, atr_ratio - 1.0) * 5.0) if str(primary.get("volatility_classification", "Normal")) == "High" else 6.0
    confidence += (-7.0 if m1_atr >= 1.45 else -4.0) if _m1_vol_high(m1) else 3.0
    if mixed:
        confidence -= 2.0  # Reduced from 4.0 - pullbacks in trends are normal
    if high_news:
        confidence -= 4.0  # Reduced from 6.0
    if rsi_caution:
        confidence -= 3.0  # Reduced from 5.0
    if rsi_exhausted:
        confidence -= 5.0  # Reduced from 7.0
    if m1_counter:
        confidence -= 3.0  # Reduced from 4.0
    if waiting:
        confidence -= 2.0  # Reduced from 5.0
    if higher_tf_conflict:
        confidence -= 8.0  # Reduced from 12.0 - allow pullback entries
    
    fallback = int(round(max(30.0, min(95.0, confidence - thin_vol_penalty))))
    calibrated, _ = calibrate_technical_confidence(
        fallback_confidence=fallback,
        direction=direction,
        scorecard=scorecard,
        tfi=tfi,
        mixed_signals=mixed,
        high_impact_news=high_news,
        rsi_caution=rsi_caution or rsi_exhausted,
        m1_counter=m1_counter,
    )
    return calibrated


def _m5_reversal_ready(direction: str, tfi: dict[str, dict[str, Any]], tfa: dict[str, dict[str, Any]]) -> bool:
    m5_dir = tfa.get("M5", {}).get("direction", "NO TRADE")
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    m5_vwap = str(tfi.get("M5", {}).get("price_vs_vwap", "Unknown"))
    if direction == "BUY":
        return m5_dir == "BUY" and ((m5_rsi is not None and m5_rsi >= M5_REVERSAL_BUY_RSI) or m5_vwap == "Above")
    if direction == "SELL":
        return m5_dir == "SELL" and ((m5_rsi is not None and m5_rsi <= M5_REVERSAL_SELL_RSI) or m5_vwap == "Below")
    return False


def _build_wait_metadata(
    direction: str,
    tfi: dict[str, dict[str, Any]],
    tfa: dict[str, dict[str, Any]],
    gates: dict[str, Any],
    context: str,
) -> tuple[str, str]:
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    if direction == "BUY":
        if context == "countertrend_pullback":
            return (
                "H4 and H1 still favor BUY, but M15 is pulling back against the higher timeframe trend.",
                f"Wait for M5 to flip bullish and RSI to recover above {M5_REVERSAL_BUY_RSI:.0f}.",
            )
        if tfa.get("M5", {}).get("direction") == "SELL":
            return (
                "H4 and H1 are bullish, but M5 is still correcting lower.",
                f"Wait for M5 bullish reversal, RSI >= {M5_REVERSAL_BUY_RSI:.0f}, and price back above VWAP.",
            )
        if gates.get("m1_counter"):
            return ("The broader BUY setup is intact, but M1 is still pulling back.", gates.get("m1_counter_reason") or f"Wait for M1 RSI > {M1_COUNTER_BUY_RSI:.0f}.")
        if gates.get("rsi_exhausted"):
            trigger = f"Wait for M5 RSI to cool from {m5_rsi:.1f} and re-accelerate higher." if m5_rsi is not None else "Wait for RSI to cool and M5 to re-align bullish."
            return ("The BUY setup is stretched after a strong push and needs a reset before entry.", trigger)
        return ("The BUY setup has directional edge, but the lower timeframe trigger is not aligned yet.", "Wait for fresh M5 continuation in the direction of H4 and H1.")
    if direction == "SELL":
        if context == "countertrend_pullback":
            return (
                "H4 and H1 still favor SELL, but M15 is bouncing against the higher timeframe trend.",
                f"Wait for M5 to flip bearish and RSI to slip below {M5_REVERSAL_SELL_RSI:.0f}.",
            )
        if tfa.get("M5", {}).get("direction") == "BUY":
            return (
                "H4 and H1 are bearish, but M5 is still bouncing higher.",
                f"Wait for M5 bearish reversal, RSI <= {M5_REVERSAL_SELL_RSI:.0f}, and price back below VWAP.",
            )
        if gates.get("m1_counter"):
            return ("The broader SELL setup is intact, but M1 is still bouncing.", gates.get("m1_counter_reason") or f"Wait for M1 RSI < {M1_COUNTER_SELL_RSI:.0f}.")
        if gates.get("rsi_exhausted"):
            trigger = f"Wait for M5 RSI to recover from {m5_rsi:.1f} and roll back over." if m5_rsi is not None else "Wait for RSI to cool and M5 to re-align bearish."
            return ("The SELL setup is stretched after a sharp drop and needs a reset before entry.", trigger)
        return ("The SELL setup has directional edge, but the lower timeframe trigger is not aligned yet.", "Wait for fresh M5 continuation in the direction of H4 and H1.")
    return ("The setup is not actionable yet.", "Wait for stronger directional alignment before entering.")


def _resolve_signal_state(
    raw_candidate: str,
    final_score: float,
    tfa: dict[str, dict[str, Any]],
    tfi: dict[str, dict[str, Any]],
    gates: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    higher_bias, bias_strength, bias_reason = _higher_tf_bias(tfa)
    m15_dir = tfa.get("M15", {}).get("direction", "NO TRADE")
    gates["higher_tf_bias"] = higher_bias
    gates["higher_tf_bias_reason"] = bias_reason
    setup_direction = raw_candidate if raw_candidate in TRADE_SIGNALS else higher_bias
    strong_bias = bias_strength == 2 and higher_bias in TRADE_SIGNALS
    countertrend_pullback = strong_bias and m15_dir not in {higher_bias, "NO TRADE"}

    if strong_bias and raw_candidate in TRADE_SIGNALS and raw_candidate != higher_bias:
        gates["higher_tf_conflict"] = True
        gates["higher_tf_reason"] = bias_reason or f"H4 and H1 favor {higher_bias}, not {raw_candidate}."
        if abs(final_score) < COUNTERTREND_REJECTION_SCORE:
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "countertrend_pullback")
            return WAIT_SIGNAL, higher_bias, "wait_for_pullback_completion", reason, trigger
        return "NO TRADE", higher_bias, "countertrend_rejected", gates["higher_tf_reason"], ""

    if countertrend_pullback and WAIT_SCORE_FLOOR <= abs(final_score) < COUNTERTREND_REJECTION_SCORE:
        reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "countertrend_pullback")
        return WAIT_SIGNAL, higher_bias, "wait_for_pullback_completion", reason, trigger

    continuation_context = higher_bias in TRADE_SIGNALS and m15_dir in {higher_bias, "NO TRADE"}
    if continuation_context:
        if not _m5_reversal_ready(higher_bias, tfi, tfa):
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "m5_reversal")
            return WAIT_SIGNAL, higher_bias, "wait_for_m5_reversal", reason, trigger
        if gates.get("m1_counter"):
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "m1_reset")
            return WAIT_SIGNAL, higher_bias, "wait_for_m1_reset", reason, trigger
        if gates.get("rsi_exhausted"):
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "rsi_reset")
            return WAIT_SIGNAL, higher_bias, "wait_for_rsi_reset", reason, trigger
        if abs(final_score) >= SIGNAL_SCORE_THRESHOLD:
            return higher_bias, higher_bias, "ready", "", ""
        if abs(final_score) >= WAIT_SCORE_FLOOR:
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "score_expansion")
            return WAIT_SIGNAL, higher_bias, "wait_for_score_expansion", reason, trigger

    if raw_candidate in TRADE_SIGNALS:
        if gates.get("m1_counter"):
            reason, trigger = _build_wait_metadata(raw_candidate, tfi, tfa, gates, "m1_reset")
            return WAIT_SIGNAL, raw_candidate, "wait_for_m1_reset", reason, trigger
        if gates.get("rsi_exhausted"):
            reason, trigger = _build_wait_metadata(raw_candidate, tfi, tfa, gates, "rsi_reset")
            return WAIT_SIGNAL, raw_candidate, "wait_for_rsi_reset", reason, trigger
        return raw_candidate, raw_candidate, "ready", "", ""

    if higher_bias in TRADE_SIGNALS and abs(final_score) >= WAIT_SCORE_FLOOR:
        reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "entry_alignment")
        return WAIT_SIGNAL, higher_bias, "wait_for_entry_alignment", reason, trigger

    return "NO TRADE", "NO TRADE", "not_actionable", "", ""


def _calculate_volatility_adjusted_threshold(atr_ratio: float | None) -> float:
    """TIER 2: Adjust SIGNAL_SCORE_THRESHOLD based on volatility regime."""
    if atr_ratio is None:
        return SIGNAL_SCORE_THRESHOLD
    if atr_ratio > 1.2:
        return 4.5  # High vol: stricter
    elif atr_ratio < 0.7:
        return 3.5  # Low vol: looser
    else:
        return 4.0  # Normal


def _calculate_confluence_score(tfa: dict[str, dict[str, Any]], direction: str) -> tuple[float, str]:
    """TIER 2: Score confluence across all timeframes."""
    if direction not in TRADE_SIGNALS:
        return 0.0, ""
    
    agreeing_tfs = 0
    for label in ("H4", "H1", "M15", "M5", "M1"):
        if tfa.get(label, {}).get("direction") == direction:
            agreeing_tfs += 1
    
    if agreeing_tfs == 5:
        return 30.0, "All 5 TFs aligned"
    elif agreeing_tfs == 4:
        return 20.0, "4 of 5 TFs aligned"
    elif agreeing_tfs == 3:
        return 10.0, "3 of 5 TFs aligned"
    elif agreeing_tfs == 2:
        return 5.0, "2 TFs aligned"
    else:
        return -5.0, "Fragmented signal"


def _build_levels(signal: str, tfi: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    """TIER 1: Build entry/stop/target with slippage & spread buffer.
    
    FIX #10: Validates risk/reward symmetry for SELL signals.
    """
    SPREAD_BUFFER = 0.3
    STOP_CUSHION = 0.2
    TARGET_CUSHION = 0.1
    
    if signal not in TRADE_SIGNALS:
        return {"entry_price": None, "stop_loss": None, "take_profit": None, "risk_distance": None}
    
    m1 = tfi.get("M1", {})
    m5 = tfi.get("M5", {})
    m15 = tfi.get("M15", {})
    price = _f(m1.get("close")) or _f(m5.get("close")) or _f(m15.get("close"))
    entry_atr = _f(m1.get("atr_14")) or _f(m5.get("atr_14")) or _f(m15.get("atr_14"))
    pullback_atr = _f(m5.get("atr_14")) or _f(m15.get("atr_14")) or entry_atr
    risk_atr = _f(m15.get("atr_14")) or _f(m5.get("atr_14")) or entry_atr
    
    if price is None or pullback_atr in {None, 0} or risk_atr in {None, 0}:
        return {"entry_price": price, "stop_loss": None, "take_profit": None, "risk_distance": None}
    
    pullback = pullback_atr * ENTRY_PULLBACK_M5_ATR_FACTOR
    anchors = [v for v in (_f(m5.get("ema_20")), _f(m5.get("vwap")), _f(m1.get("ema_20")), _f(m1.get("vwap"))) if v is not None]
    risk_distance = risk_atr * 1.5
    
    if signal == "BUY":
        atr_entry = price - pullback
        supports = [a for a in anchors if a <= atr_entry]
        entry = max(supports + [atr_entry]) if supports else atr_entry
        entry = entry + SPREAD_BUFFER
        stop_loss = entry - risk_distance - STOP_CUSHION
        take_profit = entry + risk_distance * 2 - TARGET_CUSHION
        return {"entry_price": entry, "stop_loss": stop_loss, "take_profit": take_profit, "risk_distance": risk_distance}
    
    # SELL: Validate symmetry (reverse order but same distance)
    atr_entry = price + pullback
    resistances = [a for a in anchors if a >= atr_entry]
    entry = min(resistances + [atr_entry]) if resistances else atr_entry
    entry = entry - SPREAD_BUFFER
    stop_loss = entry + risk_distance + STOP_CUSHION
    take_profit = entry - (risk_distance * 2) + TARGET_CUSHION
    
    # FIX #10: Validate SELL levels are properly ordered
    # For SELL: take_profit < entry < stop_loss (price above entry is risk, below is reward)
    result = {"entry_price": entry, "stop_loss": stop_loss, "take_profit": take_profit, "risk_distance": risk_distance}
    
    # Log warning if levels look inverted
    if take_profit >= entry or entry >= stop_loss:
        log_debug(f"⚠ SELL levels may be inverted: TP {take_profit:.2f} | Entry {entry:.2f} | SL {stop_loss:.2f}")
    
    return result


def get_technical_signal(
    symbol: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    high_impact_news: bool = False,
) -> dict[str, Any]:
    required = set(ENTRY_TIMEFRAMES).union(HIGHER_TIMEFRAMES)
    missing = sorted(required.difference(timeframe_indicators))
    if missing:
        return _empty(f"Missing timeframe data: {', '.join(missing)}.")
    try:
        tfi = timeframe_indicators
        tfa = {label: _evaluate_tf(ind) for label, ind in tfi.items()}
        primary = tfi["M15"]
        
        base_score = _score(primary)
        confirmation = _confirmation_components(tfa)
        live_entry = _live_entry_components(tfi, tfa)
        final_buy = base_score["buy_score"] + confirmation["buy_score"] + live_entry["buy_score"]
        final_sell = base_score["sell_score"] + confirmation["sell_score"] + live_entry["sell_score"]
        final_score = base_score["final_score"] + confirmation["net_score"] + live_entry["net_score"]
        final_score, m15_vol_thin, penalty_points, penalty_reason = _apply_volume_penalty(final_score, tfi, tfa)
        
        # Score log stays explicit so frozen/plateau behavior is easy to inspect live.
        log_debug(
            f"Score components: "
            f"base_buy={base_score['buy_score']:.2f} | "
            f"base_sell={base_score['sell_score']:.2f} | "
            f"conf_buy={confirmation['buy_score']:.2f} | "
            f"conf_sell={confirmation['sell_score']:.2f} | "
            f"live_buy={live_entry['buy_score']:.2f} | "
            f"live_sell={live_entry['sell_score']:.2f} | "
            f"final_buy={final_buy:.2f} | "
            f"final_sell={final_sell:.2f} | "
            f"final_score={final_score:.2f}"
        )
        
        score_direction = "BUY" if final_score > 0 else ("SELL" if final_score < 0 else "NO TRADE")
        
        # FIX #7: Apply session multiplier to threshold
        from risk_manager import get_current_session, SESSION_SCORE_MULTIPLIERS
        session = get_current_session()
        session_multiplier = SESSION_SCORE_MULTIPLIERS.get(session, 1.0)
        adjusted_threshold = SIGNAL_SCORE_THRESHOLD * session_multiplier
        
        raw_candidate = score_direction if score_direction in TRADE_SIGNALS and abs(final_score) >= adjusted_threshold else "NO TRADE"
        # FIX #6: Properly detect mixed signals (conflicting entry timeframe directions)
        mixed = _detect_mixed_signals(tfa) or (final_buy > 0 and final_sell > 0)
        scorecard = {
            "base_buy_score": base_score["buy_score"],
            "base_sell_score": base_score["sell_score"],
            "base_components": base_score["components"],
            "confirmation_buy_score": confirmation["buy_score"],
            "confirmation_sell_score": confirmation["sell_score"],
            "confirmation_net_score": confirmation["net_score"],
            "confirmation_components": confirmation["components"],
            "live_entry_buy_score": live_entry["buy_score"],
            "live_entry_sell_score": live_entry["sell_score"],
            "live_entry_net_score": live_entry["net_score"],
            "live_entry_components": live_entry["components"],
            "buy_score": final_buy,
            "sell_score": final_sell,
            "final_score": final_score,
            "score_direction": score_direction,
            "volume_penalty_applied": m15_vol_thin,
            "volume_penalty_points": penalty_points,
            "volume_penalty_reason": penalty_reason,
        }
        gates: dict[str, Any] = {
            "all_vol_low": _all_vol_low(tfi),
            "m15_volume_thin": m15_vol_thin,
            "m15_volume_reason": penalty_reason,
            "higher_tf_conflict": False,
            "higher_tf_reason": "",
            "higher_tf_bias": "",
            "higher_tf_bias_reason": "",
            "rsi_exhausted": False,
            "rsi_caution": False,
            "m1_counter": False,
            "m1_exhaustion": False,
            "m1_exhaustion_reason": "",
            "exhaustion_reason": "",
            "rsi_caution_reason": "",
            "m1_counter_reason": "",
            "wait_for_confirmation": False,
            "wait_reason": "",
            "wait_trigger": "",
            "entry_timing_state": "not_actionable",
        }
        if raw_candidate in TRADE_SIGNALS:
            gates["higher_tf_conflict"], gates["higher_tf_reason"] = _higher_tf_conflict(raw_candidate, tfa)
        exhaustion_direction = raw_candidate if raw_candidate in TRADE_SIGNALS else score_direction
        if exhaustion_direction in TRADE_SIGNALS:
            exhausted, cautious, reason = _rsi_exhaustion(exhaustion_direction, tfi)
            gates["rsi_exhausted"] = exhausted
            gates["rsi_caution"] = cautious
            if exhausted:
                gates["exhaustion_reason"] = reason
            elif cautious:
                gates["rsi_caution_reason"] = reason
            gates["m1_counter"], gates["m1_counter_reason"] = _m1_counter(exhaustion_direction, tfi)
        m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
        if m1_rsi is not None:
            if exhaustion_direction == "SELL" and m1_rsi < 30.0:
                gates["m1_exhaustion"] = True
                gates["m1_exhaustion_reason"] = f"M1 RSI {m1_rsi:.1f} is oversold."
            elif exhaustion_direction == "BUY" and m1_rsi > 70.0:
                gates["m1_exhaustion"] = True
                gates["m1_exhaustion_reason"] = f"M1 RSI {m1_rsi:.1f} is overbought."
        technical_signal, setup_direction, timing_state, wait_reason, wait_trigger = _resolve_signal_state(raw_candidate, final_score, tfa, tfi, gates)
        gates["entry_timing_state"] = timing_state
        gates["wait_for_confirmation"] = technical_signal == WAIT_SIGNAL
        gates["wait_reason"] = wait_reason
        gates["wait_trigger"] = wait_trigger
        confidence_direction = setup_direction if setup_direction in TRADE_SIGNALS else score_direction
        # GATE #2: Pass thin_volume and higher_tf_conflict flags to confidence calculation
        technical_confidence = _calculate_confidence(
            direction=confidence_direction,
            scorecard=scorecard,
            tfa=tfa,
            tfi=tfi,
            mixed=mixed,
            high_news=high_impact_news,
            rsi_caution=gates["rsi_caution"],
            rsi_exhausted=gates["rsi_exhausted"],
            m1_counter=gates["m1_counter"],
            waiting=technical_signal == WAIT_SIGNAL,
            thin_volume=gates["m15_volume_thin"],
            higher_tf_conflict=gates["higher_tf_conflict"],
        )
        level_direction = setup_direction if setup_direction in TRADE_SIGNALS else technical_signal
        
        # TIER 2: Volatility-adjusted threshold & confluence scoring
        m15_atr_ratio = _f(tfi.get("M15", {}).get("atr_ratio"))
        vol_adj_threshold = _calculate_volatility_adjusted_threshold(m15_atr_ratio)
        confluence_bonus, confluence_reason = _calculate_confluence_score(tfa, level_direction)
        gates["volatility_adjusted_threshold"] = vol_adj_threshold
        gates["confluence_bonus"] = confluence_bonus
        gates["confluence_reason"] = confluence_reason
        
        trade_levels = _build_levels(level_direction, tfi)
        risk_points = 0
        if str(primary.get("volatility_classification", "Normal")) == "High":
            risk_points += 1
        if _m1_vol_high(tfi["M1"]):
            risk_points += 2
        if high_impact_news:
            risk_points += 1
        if mixed:
            risk_points += 1
        if gates["higher_tf_conflict"]:
            risk_points += 1
        if gates["rsi_caution"]:
            risk_points += 1
        if gates["rsi_exhausted"]:
            risk_points += 1
        if gates["m1_counter"]:
            risk_points += 1
        if gates["m15_volume_thin"]:
            risk_points += 1
        risk_level = "High" if risk_points >= 5 else ("Medium" if risk_points >= 2 else "Low")
        
        # FIX: Use session-aware confidence threshold
        from risk_manager import get_current_session
        session = get_current_session()
        session_min_conf = MIN_CONFIDENCE_BY_SESSION.get(session, MIN_CONFIDENCE_THRESHOLD)
        
        if technical_signal in TRADE_SIGNALS and technical_confidence < session_min_conf:
            log_debug(f"Confidence {technical_confidence}% < {session_min_conf}% threshold ({session}) — downgrading {technical_signal} to WAIT")
            gates["confidence_threshold_rejected"] = True
            gates["confidence_threshold_value"] = technical_confidence
            gates["signal_wait_timestamp"] = datetime.now(timezone.utc).isoformat()  # Track when WAIT started
            technical_signal = WAIT_SIGNAL
            gates["wait_for_confirmation"] = True
            gates["wait_reason"] = f"Confidence only {technical_confidence}% (need {session_min_conf}%+ in {session}) — waiting for M1 pullback to confirm {setup_direction}."
            gates["wait_trigger"] = f"Wait for M1 to align: confidence to reach {session_min_conf}%+ on pullback."
        
        log_debug(f"Technical engine: state={technical_signal} | setup={setup_direction} | score={final_score:+.2f} | conf={technical_confidence}% | risk={risk_level} | timing={timing_state}")
        return {
            "technical_signal": technical_signal,
            "setup_direction": setup_direction,
            "weighted_score": final_score,
            "max_score": MAX_WEIGHTED_SCORE,
            "technical_confidence": technical_confidence,
            "scorecard": scorecard,
            "timeframe_analysis": tfa,
            "mixed_signals": mixed,
            "risk_level": risk_level,
            "trade_levels": trade_levels,
            "gates": gates,
            "entry_timing_state": timing_state,
            "wait_reason": wait_reason,
            "wait_trigger": wait_trigger,
        }
    except Exception as exc:
        log_debug(f"Technical engine failed: {exc}")
        return _empty(str(exc))


def _empty(reason: str) -> dict[str, Any]:
    return {
        "technical_signal": "NO TRADE",
        "setup_direction": "NO TRADE",
        "weighted_score": 0.0,
        "max_score": MAX_WEIGHTED_SCORE,
        "technical_confidence": 0,
        "scorecard": {},
        "timeframe_analysis": {},
        "mixed_signals": False,
        "risk_level": "High",
        "trade_levels": {"entry_price": None, "stop_loss": None, "take_profit": None, "risk_distance": None},
        "gates": {
            "all_vol_low": False,
            "m15_volume_thin": False,
            "m15_volume_reason": "",
            "higher_tf_conflict": False,
            "higher_tf_reason": "",
            "higher_tf_bias": "",
            "higher_tf_bias_reason": "",
            "rsi_exhausted": False,
            "rsi_caution": False,
            "m1_counter": False,
            "m1_exhaustion": False,
            "m1_exhaustion_reason": "",
            "exhaustion_reason": "",
            "rsi_caution_reason": "",
            "m1_counter_reason": "",
            "wait_for_confirmation": False,
            "wait_reason": "",
            "wait_trigger": "",
            "entry_timing_state": "not_actionable",
        },
        "entry_timing_state": "not_actionable",
        "wait_reason": "",
        "wait_trigger": "",
        "error": reason,
    }


def format_price(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.4f}"
