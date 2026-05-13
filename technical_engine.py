"""Improved technical decision engine for intraday XAUUSD."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from confidence_calibrator import calibrate_technical_confidence
from utils import log_debug
from setup_tracker import (
    register_setup,
    check_setup_expiry,
    reset_daily_bias,
    clear_setup,
    get_active_setup,
)
from wyckoff import (
    WyckoffPhaseDetector,
    find_imbalance_zones,
    apply_wyckoff_confidence_adjustment,
    validate_entry_with_wyckoff,
    get_wyckoff_summary,
)
from institutional_patterns import detect_institutional_patterns, get_patterns_summary
from pullback_handler import (
    detect_pullback_in_progress,
    check_pullback_reversal_ready,
    calculate_pullback_target_zone,
    apply_pullback_state_to_gates,
)
from market_structure import get_market_structure_database
from effort_analyzer import get_effort_analyzer
from volume_profile import analyze_volume_profile_at_price
from projection_engine import calculate_wyckoff_targets
from advanced_trading import (
    SessionPhaseStrategy,
    CompositeManSimulator,
    BracketPredictorEngine,
    AdvancedVolatilityIndex,
    MultiTouchSupportConfirm,
    get_session_adjusted_analysis,
)

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
H4_BASE_SCORE_MULTIPLIER = 2.5  # Scale H4 trend strength to base score contribution
LOW_VOLUME_RATIO = 0.40  # FIXED: Changed from 0.70. Now 0.85 volume = normal, not low
GENUINELY_DEAD_VOLUME_RATIO = 0.35  # Only penalize truly dead volume (<35%)
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
TIMEFRAME_CONFIRM_WEIGHTS = {"H4": 8.0, "H1": 4.0, "M5": 1.0, "M1": 0.5}
# HIERARCHY: H4 (structural) >> H1 (confirms) >> M5 (pullback) > M1 (entry timing)
# H4:M1 ratio of 16:1 ensures that temporary pullbacks cannot flip the structural trend

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


def _is_structured_pullback_reentry(
    direction: str,
    tfa: dict[str, dict[str, Any]],
) -> bool:
    """Treat weak countertrend labels as pullbacks once price action re-aligns."""
    if direction not in TRADE_SIGNALS:
        return False

    h4 = tfa.get("H4", {})
    h1 = tfa.get("H1", {})
    m15 = tfa.get("M15", {})
    m5 = tfa.get("M5", {})
    m1 = tfa.get("M1", {})

    if direction == "BUY":
        h4_supportive = h4.get("direction") == "BUY"
        lower_ready = (
            m5.get("direction") == "BUY"
            and m1.get("direction") == "BUY"
            and m5.get("price_vs_vwap") == "Above"
            and m1.get("price_vs_vwap") == "Above"
        )
        h1_soft = h1.get("trend_classification") == "Weak Bearish" and h1.get("price_vs_vwap") == "Above"
        m15_soft = m15.get("trend_classification") == "Weak Bearish" and m15.get("price_vs_vwap") == "Above"
        h1_ok = h1.get("direction") in {"BUY", "NO TRADE"} or h1_soft
        m15_ok = m15.get("direction") in {"BUY", "NO TRADE"} or m15_soft
        return bool(h4_supportive and lower_ready and h1_ok and m15_ok)

    h4_supportive = h4.get("direction") == "SELL"
    lower_ready = (
        m5.get("direction") == "SELL"
        and m1.get("direction") == "SELL"
        and m5.get("price_vs_vwap") == "Below"
        and m1.get("price_vs_vwap") == "Below"
    )
    h1_soft = h1.get("trend_classification") == "Weak Bullish" and h1.get("price_vs_vwap") == "Below"
    m15_soft = m15.get("trend_classification") == "Weak Bullish" and m15.get("price_vs_vwap") == "Below"
    h1_ok = h1.get("direction") in {"SELL", "NO TRADE"} or h1_soft
    m15_ok = m15.get("direction") in {"SELL", "NO TRADE"} or m15_soft
    return bool(h4_supportive and lower_ready and h1_ok and m15_ok)


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


def _score(primary: dict[str, Any], h4_indicators: dict[str, Any] | None = None) -> dict[str, Any]:
    """ARCHITECTURAL FIX: Dynamic base score derived from H4 structure.
    
    Instead of hardcoded 1.50/3.50, base scores now reflect H4 directional strength.
    H4 Strong Bullish → base_buy weighted higher
    H4 Strong Bearish → base_sell weighted higher
    H4 Neutral → balanced baseline
    """
    buy = 0.0
    sell = 0.0
    components = {key: 0.0 for key in WEIGHTS}
    
    # STEP 1: Calculate M15 contribution
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
    
    # STEP 2: Add H4 directional bias (NEW)
    # This makes base scores dynamic instead of frozen
    if h4_indicators is not None:
        h4_trend = str(h4_indicators.get("trend_classification", "Neutral"))
        h4_strength = _f(h4_indicators.get("trend_strength_ratio")) or 0.0
        
        if h4_trend == "Strong Bullish":
            h4_bias = min(1.5, h4_strength * H4_BASE_SCORE_MULTIPLIER)
            buy += h4_bias
            components["h4_bias"] = h4_bias
        elif h4_trend == "Strong Bearish":
            h4_bias = min(1.5, h4_strength * H4_BASE_SCORE_MULTIPLIER)
            sell += h4_bias
            components["h4_bias"] = -h4_bias
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
    # FIX 8: Cap confirmation score at 6.0 to prevent score inflation
    # Raw sum can reach 13.5 (8.0+4.0+1.0+0.5 when all bullish) which destabilizes scoring
    # Confirmation should reinforce base score, not dominate it
    # IMPORTANT: This cap is stored before Wyckoff check. If Wyckoff is blocked,
    # the caller (_calculate_confidence) will recalculate without this cap.
    buy_uncapped = buy
    sell_uncapped = sell
    buy = min(buy, 6.0)
    sell = min(sell, 6.0)
    net = buy - sell  # BUG FIX: Recalculate net_score after capping buy/sell to maintain consistency
    net = _clip(net, -6.0, 6.0)
    return {"buy_score": buy, "sell_score": sell, "net_score": net, "components": components, "buy_uncapped": buy_uncapped, "sell_uncapped": sell_uncapped}


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
    h1_rsi = _f(tfi.get("H1", {}).get("rsi_14"))
    m15_rsi = _f(tfi.get("M15", {}).get("rsi_14"))
    m5_rsi = _f(tfi.get("M5", {}).get("rsi_14"))
    m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
    
    if signal == "SELL":
        # FIX 1: H1 RSI EXHAUSTION DETECTION
        # When H1 RSI < 25 (extreme oversold), check for exhaustion risk using volume + M1 confirmation
        if h1_rsi is not None and h1_rsi < 25.0:
            h1_vol_ratio = _f(tfi.get("H1", {}).get("volume_ratio"))
            m1_rsi_val = _f(tfi.get("M1", {}).get("rsi_14"))
            
            # OVERSOLD EXHAUSTION RISK: H1 RSI below 25 AND volume thin AND M1 RSI not confirming continuation
            if h1_vol_ratio is not None and h1_vol_ratio < 0.6 and m1_rsi_val is not None and m1_rsi_val > 40.0:
                return True, False, (
                    f"OVERSOLD EXHAUSTION RISK: H1 RSI {h1_rsi:.1f} below 25 with thin volume ({h1_vol_ratio:.3f}) "
                    f"and M1 RSI {m1_rsi_val:.1f} not confirming continuation. "
                    f"Require confirmed M15 candle close below current low."
                )
        
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


def _m1_confirmation_ready(direction: str, tfi: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    """
    TIGHT M1 CONFIRMATION: BUY/SELL only valid when M1 confirms reversal with ALL THREE conditions.
    (ARCHITECTURAL FIX: Previously only checked 1-2 conditions, allowing premature entries)
    
    For BUY (all must pass):
      1. M1 RSI > 40 AND ticking upward (current RSI > previous RSI)
      2. Latest M1 close is above M1 VWAP
      3. M1 trend_classification is NOT Strong Bearish
    
    For SELL (all must pass):
      1. M1 RSI < 60 AND ticking downward (current RSI < previous RSI)  
      2. Latest M1 close is below M1 VWAP
      3. M1 trend_classification is NOT Strong Bullish
    
    Returns (is_ready, reason_if_blocked)
    If ANY condition fails, return False with that specific reason.
    """
    if direction not in {"BUY", "SELL"}:
        return False, ""
    
    # Load M1 data
    m1 = tfi.get("M1", {})
    m1_rsi = _f(m1.get("rsi_14"))
    m1_pvwap = str(m1.get("price_vs_vwap", "Unknown"))
    m1_trend = str(m1.get("trend_classification", "Neutral"))
    
    if m1_rsi is None:
        return False, f"M1 RSI data unavailable"
    
    # Load previous M1 RSI from sniper state
    try:
        sniper_state_file = Path("sniper_state.json")
        if sniper_state_file.exists():
            state = json.loads(sniper_state_file.read_text())
            m1_rsi_prev = _f(state.get("m1_rsi_prev"))
        else:
            m1_rsi_prev = None
    except Exception as e:
        log_debug(f"Failed to load sniper state for M1 confirmation: {e}")
        m1_rsi_prev = None
    
    if direction == "BUY":
        # ARCHITECTURAL FIX: Check ALL three conditions before returning True
        # If any fails, return False immediately with specific reason
        
        # Condition 1: M1 RSI > 40 AND ticking upward
        rsi_condition = m1_rsi > 40.0
        if m1_rsi_prev is not None:
            rsi_ticking = m1_rsi > m1_rsi_prev
        else:
            rsi_ticking = True  # If no previous, assume OK (first candle)
        
        if not rsi_condition:
            return False, f"M1 RSI {m1_rsi:.1f} ≤40 - not ready for BUY"
        if not rsi_ticking:
            return False, f"M1 RSI {m1_rsi:.1f} not ticking up (prev={m1_rsi_prev:.1f}) - momentum not confirmed"
        
        # Condition 2: M1 close above VWAP
        if m1_pvwap != "Above":
            return False, f"M1 price {m1_pvwap} VWAP (below) - price structure broken"
        
        # Condition 3: M1 trend NOT Strong Bearish
        if m1_trend == "Strong Bearish":
            return False, f"M1 trend {m1_trend} - strong bearish rejection"
        
        # All three conditions passed
        return True, ""
    
    elif direction == "SELL":
        # ARCHITECTURAL FIX: Check ALL three conditions before returning True
        
        # Condition 1: M1 RSI < 60 AND ticking downward
        rsi_condition = m1_rsi < 60.0
        if m1_rsi_prev is not None:
            rsi_ticking = m1_rsi < m1_rsi_prev
        else:
            rsi_ticking = True  # If no previous, assume OK (first candle)
        
        if not rsi_condition:
            return False, f"M1 RSI {m1_rsi:.1f} ≥60 - not ready for SELL"
        if not rsi_ticking:
            return False, f"M1 RSI {m1_rsi:.1f} not ticking down (prev={m1_rsi_prev:.1f}) - momentum not confirmed"
        
        # Condition 2: M1 close below VWAP
        if m1_pvwap != "Below":
            return False, f"M1 price {m1_pvwap} VWAP (above) - price structure broken"
        
        # Condition 3: M1 trend NOT Strong Bullish
        if m1_trend == "Strong Bullish":
            return False, f"M1 trend {m1_trend} - strong bullish rejection"
        
        # All three conditions passed
        return True, ""
    
    return False, ""


def _h4_price_vs_ema_reality(h4_ind: dict[str, Any]) -> tuple[float, str]:
    """
    Reality check: H4 trend label may be misleading if price is far from EMAs.
    
    Returns: (penalty_points, reason)
    - If H4 close < EMA50: return (-2.0, "H4 Price Bearish — label misleading")
    - If H4 close < EMA20 but >= EMA50: return (-1.0, "H4 Price below EMA20")
    - Otherwise: return (0.0, "")
    
    Only applied to BUY signals (caller responsibility).
    """
    close = _f(h4_ind.get("close"))
    ema20 = _f(h4_ind.get("ema_20"))
    ema50 = _f(h4_ind.get("ema_50"))
    
    if close is None or ema20 is None or ema50 is None:
        return 0.0, ""
    
    # Condition 1: Price below EMA50 (strongest bearish contradiction)
    if close < ema50:
        return -2.0, f"H4 Price Bearish — close {close:.2f} below EMA50 {ema50:.2f}"
    
    # Condition 2: Price below EMA20 but above EMA50 (weaker bearish signal)
    if close < ema20:
        return -1.0, f"H4 Price below EMA20 {ema20:.2f} (caution: correction risk)"
    
    return 0.0, ""


def _h1_strong_bearish_block(direction: str, tfa: dict[str, dict[str, Any]], h4_trend: str = "Neutral") -> tuple[str, float, str]:
    """
    FIX: H1 pullback logic — graduated penalty instead of hard block.
    
    In a Strong Bullish H4, H1 bearish = pullback, not reversal.
    Rules:
    - BUY + H1 Strong Bearish + H4 Strong Bullish → Allow, apply -15% confidence penalty (pullback caution)
    - BUY + H1 Strong Bearish + H4 NOT Bullish → Hard block (genuine reversal risk)
    - BUY + H1 Weak Bearish → Allow, apply -8% confidence penalty
    - SELL + H1 trends → No block or penalty (SELL is lower risk)
    
    Returns: (block_signal, penalty_confidence, reason)
    - block_signal: "NO TRADE" if hard block, "" if allowed
    - penalty_confidence: Confidence penalty (0.0 if no penalty)
    - reason: Explanation
    """
    if direction not in {"BUY", "SELL"}:
        return "", 0.0, ""
    
    h1_trend = str(tfa.get("H1", {}).get("trend_classification", "Neutral"))
    
    # FIX: H1 Strong Bearish in Strong Bullish H4 = pullback, not reversal
    if direction == "BUY" and h1_trend == "Strong Bearish":
        if "Strong Bullish" in str(h4_trend):
            # This is a pullback inside uptrend — allow with pullback caution penalty
            return "", -15.0, f"H1 Strong Bearish inside H4 Strong Bullish (pullback context) — confidence penalty -15%"
        else:
            # Genuine reversal risk — hard block
            return "NO TRADE", 0.0, f"HARD BLOCK: H1 Strong Bearish + H4 not bullish — genuine reversal risk"
    
    # H1 Weak Bearish is allowed but penalized
    if direction == "BUY" and h1_trend == "Weak Bearish":
        if _is_structured_pullback_reentry(direction, tfa):
            return "", 0.0, "H1 Weak Bearish is a structured pullback continuation - confidence penalty waived"
        return "", -8.0, f"H1 Weak Bearish — confidence penalty -8%"
    
    return "", 0.0, ""


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

    if _is_structured_pullback_reentry(signal, tfa):
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
    higher_bias: str = "",
    pullback_in_progress: bool = False,
    pullback_reversal_ready: bool = False,
    structured_pullback_reentry: bool = False,
    wyckoff_phase: str = "NEUTRAL",
    wyckoff_phase_strength: float = 0.0,
    wyckoff_imbalances: list = None,
    patterns_adjustment: float = 0.0,
) -> int:
    primary = tfi.get("M15", {})
    m1 = tfi.get("M1", {})
    m5 = tfi.get("M5", {})
    h4 = tfa.get("H4", {})
    h1 = tfa.get("H1", {})
    tsr = _f(primary.get("trend_strength_ratio")) or 0.0
    rsi_val = _f(primary.get("rsi_14"))
    atr_ratio = _f(primary.get("atr_ratio")) or 1.0
    m1_atr = _f(m1.get("atr_ratio")) or 1.0
    
    # FIX #2: Detect bearish divergence (H4/H1 strong vs M5/M1 weak opposite trend)
    h4_rsi = _f(h4.get("rsi"))
    h1_rsi = _f(h1.get("rsi"))
    m5_rsi = _f(m5.get("rsi_14"))
    m1_rsi = _f(m1.get("rsi_14"))
    h4_trend = str(h4.get("trend_classification", "Neutral"))
    m5_trend = str(m5.get("trend_classification", "Neutral"))
    m1_trend = str(m1.get("trend_classification", "Neutral"))
    bearish_divergence_penalty = 0.0
    
    if direction == "BUY":
        # Check if higher TF (H4/H1) strong bullish RSI but lower TF (M5/M1) weak or bearish
        h_strong = (h4_rsi and h4_rsi > 60) or (h1_rsi and h1_rsi > 60)
        l_weak_bearish = ("Bearish" in m5_trend) or ("Bearish" in m1_trend)
        if h_strong and l_weak_bearish:
            bearish_divergence_penalty = -15.0
            log_debug(f"[BEARISH DIVERGENCE] H4/H1 strong bullish (RSI {h4_rsi or h1_rsi:.1f}) vs M5/M1 bearish trend — SEVERE risk of pullback into reversal. Apply -15% penalty.")
    elif direction == "SELL":
        h_strong = (h4_rsi and h4_rsi < 40) or (h1_rsi and h1_rsi < 40)
        l_weak_bullish = ("Bullish" in m5_trend) or ("Bullish" in m1_trend)
        if h_strong and l_weak_bullish:
            bearish_divergence_penalty = -15.0
            log_debug(f"[BULLISH DIVERGENCE] H4/H1 strong bearish (RSI {h4_rsi or h1_rsi:.1f}) vs M5/M1 bullish trend — SEVERE risk of bounce into reversal. Apply -15% penalty.")
    
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
    
    # FIX 1: Track total penalties to cap at -12% max (prevents stacking to -20%)
    total_penalties = 0.0
    if mixed:
        penalty = -2.0  # Reduced from 4.0 - pullbacks in trends are normal
        total_penalties += abs(penalty)
        confidence += penalty
    if high_news:
        penalty = -4.0  # Reduced from 6.0
        total_penalties += abs(penalty)
        confidence += penalty
    if rsi_caution:
        penalty = -3.0  # Reduced from 5.0
        total_penalties += abs(penalty)
        confidence += penalty
    if rsi_exhausted:
        penalty = -5.0  # Reduced from 7.0
        total_penalties += abs(penalty)
        confidence += penalty
    # FIX #2: Apply bearish divergence penalty (-15% for severe pullback risk)
    if bearish_divergence_penalty != 0.0:
        total_penalties += abs(bearish_divergence_penalty)
        confidence += bearish_divergence_penalty
    if m1_counter:
        penalty = -3.0  # Reduced from 4.0
        total_penalties += abs(penalty)
        confidence += penalty
    if waiting and not pullback_reversal_ready:
        penalty = -2.0  # Reduced from 5.0
        total_penalties += abs(penalty)
        confidence += penalty
    if pullback_reversal_ready:
        confidence += 4.0
        log_debug("[PULLBACK RECOVERY BONUS] Reversal confirmed — confidence bonus +4%")
    elif pullback_in_progress:
        confidence -= 2.0
        log_debug("[PULLBACK IN PROGRESS] Confidence penalty -2% until reversal confirms")
    
    # Enforce penalty cap
    if total_penalties > 12.0:
        log_debug(f"[PENALTY CAP] Combined penalties {total_penalties:.0f}% exceeds cap — capping to 12.0%")
    
    retracement_bonus = 0.0
    if higher_tf_conflict and higher_bias in TRADE_SIGNALS:
        m1_rsi = tfi.get("M1", {}).get("rsi_14", 50)
        m1_oversold_in_buy = (higher_bias == "BUY" and m1_rsi < 35)
        m1_overbought_in_sell = (higher_bias == "SELL" and m1_rsi > 65)
        
        if m1_oversold_in_buy or m1_overbought_in_sell:
            retracement_bonus = 3.0
            log_debug(
                f"[M1 PULLBACK ENTRY] M1 RSI={m1_rsi:.1f} "
                f"{'oversold' if m1_oversold_in_buy else 'overbought'} "
                f"within {higher_bias} HTF trend — "
                f"tf_conflict_penalty=0, +3% confidence bonus"
            )
        else:
            # FIX 2: Volume penalty inversion — only apply -10% when score is BELOW 8.0 AND volume thin
            final_score_val = scorecard.get("final_score", 0.0)
            if final_score_val < 8.0 and thin_volume:
                confidence -= 10.0
                log_debug(f"[VOLUME WARNING] Score {final_score_val:.1f} < 8.0 + thin volume + TF conflict — apply -10% penalty")
            else:
                confidence -= 8.0
                log_debug(
                    f"[TF CONFLICT] M1 contradicts majority {higher_bias} at score {final_score_val:.1f} "
                    f"— apply standard -8% penalty"
                )
    elif higher_tf_conflict:
        # FIX 1 APPLIED: Weighted TF conflict penalty
        # Check if H4 is NEUTRAL phase (weak conviction)
        h4_phase_strength = wyckoff_phase_strength if higher_bias == "H4" else 0.0
        final_score_val = scorecard.get("final_score", 0.0)
        
        if final_score_val < 8.0 and thin_volume:
            confidence -= 10.0
            log_debug(f"[VOLUME WARNING] Score {final_score_val:.1f} < 8.0 + thin volume — apply -10% penalty")
        elif h4_phase_strength < 15.0:
            confidence -= 2.0  # Light penalty for neutral H4
            log_debug(f"[TF CONFLICT - WEIGHTED] H4 phase {h4_phase_strength:.0f}% neutral → penalty -2%")
        else:
            confidence -= 8.0  # Full penalty for strong H4
            log_debug(f"[TF CONFLICT - WEIGHTED] H4 phase {h4_phase_strength:.0f}% strong → penalty -8%")
    
    if structured_pullback_reentry:
        confidence += 3.0
        log_debug("[STRUCTURED PULLBACK] H4 trend intact + M5/M1 re-aligned - confidence bonus +3%")
    confidence += retracement_bonus
    
    # ═══════════════════════════════════════════════════════════════
    # WYCKOFF METHODOLOGY INTEGRATION
    # ═══════════════════════════════════════════════════════════════
    # ARCHITECTURAL FIX: Wyckoff disabled cleanly
    # Returns 0.0 bonus (neutral) instead of penalties or hard blocks
    # This removes dead weight from decision tree
    if wyckoff_imbalances is None:
        wyckoff_imbalances = []
    
    if wyckoff_phase != "NEUTRAL" and False:  # Disabled - returns only noise currently
        # UPGRADE 3A: Wyckoff volume handling - use penalty instead of hard block
        # Changed from hard block (0.65) to penalty system for more flexibility in thin-volume sessions
        # Precious metals naturally have lower volume during certain hours - apply penalty instead
        m15_volume_ratio = tfi.get("M15", {}).get("volume_ratio", 1.0) or 1.0
        wyckoff_volume_penalty = 0.0
        wyckoff_volume_check = True
        
        if wyckoff_phase == "MARKUP" and m15_volume_ratio < 0.50:
            # Only hard block on VERY thin volume (<50% of avg)
            wyckoff_phase_strength = 0.0
            wyckoff_volume_check = False
            log_debug(f"[WYCKOFF BLOCKED] MARKUP phase blocked due to very thin volume ({m15_volume_ratio:.3f} < 0.50 hard threshold)")
            log_debug(f"[WYCKOFF BLOCKED] No confidence bonus applied — volume critically low for Wyckoff methodology")
        elif wyckoff_phase == "MARKUP" and m15_volume_ratio < 0.65:
            # Moderate penalty for thin volume (50-65%)
            wyckoff_volume_penalty = 3  # Reduce confidence bonus by 3%
            log_debug(f"[WYCKOFF PENALTY] MARKUP volume thin ({m15_volume_ratio:.3f} < 0.65 soft threshold) — confidence penalty: -{wyckoff_volume_penalty}%")
        
        if wyckoff_volume_check or wyckoff_phase != "MARKUP":
            wyckoff_confidence, wyckoff_reason = apply_wyckoff_confidence_adjustment(
                base_confidence=confidence,
                direction=direction,
                phase=wyckoff_phase,
                phase_confidence=wyckoff_phase_strength,  # Now passing 0-100 graduated confidence
                imbalances=wyckoff_imbalances
            )
            # Apply volume penalty if applicable
            if wyckoff_volume_penalty > 0:
                wyckoff_confidence = max(0, wyckoff_confidence - wyckoff_volume_penalty)
            confidence_adjustment = wyckoff_confidence - confidence
            confidence = wyckoff_confidence
            log_debug(f"[WYCKOFF] {wyckoff_reason}")
    
    # ═══════════════════════════════════════════════════════════════
    # INSTITUTIONAL PATTERNS ADJUSTMENT
    # ═══════════════════════════════════════════════════════════════
    if patterns_adjustment != 0.0:
        confidence += patterns_adjustment
        if patterns_adjustment > 0:
            log_debug(f"[PATTERNS] Liquidity sweep bonus +{patterns_adjustment:.1f}%")
        else:
            log_debug(f"[PATTERNS] Upthrust penalty {patterns_adjustment:.1f}%")
    
    # ═══════════════════════════════════════════════════════════════
    # CONFIDENCE STACKING CAP - Prevent overconfidence
    # ═══════════════════════════════════════════════════════════════
    MAX_BONUS_TOTAL = 25.0  # Max total bonus from all sources
    BASE_CONFIDENCE = 22.0  # Base confidence level
    
    if confidence - BASE_CONFIDENCE > MAX_BONUS_TOTAL:
        log_debug(f"[CAP] Confidence stacking capped: {confidence:.0f}% -> {BASE_CONFIDENCE + MAX_BONUS_TOTAL:.0f}%")
        confidence = BASE_CONFIDENCE + MAX_BONUS_TOTAL
    
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
        if context == "m1_confirmation":
            m1_reason = gates.get("m1_confirmation_reason", "M1 not ready for entry")
            return (
                "M15/M5 are bullish, but M1 must confirm reversal first.",
                f"{m1_reason}",
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
        if context == "m1_confirmation":
            m1_reason = gates.get("m1_confirmation_reason", "M1 not ready for entry")
            return (
                "M15/M5 are bearish, but M1 must confirm reversal first.",
                f"{m1_reason}",
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
    # CRITICAL FIX: Reject signal if it contradicts the score sign
    # Cannot fire BUY if final_score is negative (SELL stronger)
    # Cannot fire SELL if final_score is positive (BUY stronger)
    if raw_candidate in TRADE_SIGNALS:
        if raw_candidate == "BUY" and final_score < 0:
            log_debug(f"VALIDATION FAIL: BUY signal fired but final_score {final_score:.2f} is NEGATIVE (SELL stronger). Downgrading to WAIT.")
            gates["score_contradiction"] = True
            return "WAIT_FOR_CONFIRMATION", "NO TRADE", "score_contradiction", f"Score {final_score:.2f} contradicts BUY — wait for pullback completion", "M5+M1 alignment"
        if raw_candidate == "SELL" and final_score > 0:
            log_debug(f"VALIDATION FAIL: SELL signal fired but final_score {final_score:.2f} is POSITIVE (BUY stronger). Downgrading to WAIT.")
            gates["score_contradiction"] = True
            return "WAIT_FOR_CONFIRMATION", "NO TRADE", "score_contradiction", f"Score {final_score:.2f} contradicts SELL — wait for pullback completion", "M5+M1 alignment"
    
    higher_bias, bias_strength, bias_reason = _higher_tf_bias(tfa)
    m15_dir = tfa.get("M15", {}).get("direction", "NO TRADE")
    gates["higher_tf_bias"] = higher_bias
    gates["higher_tf_bias_reason"] = bias_reason
    setup_direction = raw_candidate if raw_candidate in TRADE_SIGNALS else higher_bias
    
    # FIX: H1 pullback logic — graduated penalty or hard block
    h4_trend_str = str(tfa.get("H4", {}).get("trend_classification", "Neutral"))
    h1_block_signal, h1_penalty, h1_block_reason = _h1_strong_bearish_block(setup_direction, tfa, h4_trend_str)
    if h1_block_signal == "NO TRADE":
        log_debug(f"[HARD BLOCK] {h1_block_reason}")
        gates["h1_strong_bearish_block"] = True
        gates["h1_block_reason"] = h1_block_reason
        return "NO TRADE", "NO TRADE", "h1_hard_block", h1_block_reason, ""
    
    # Store H1 pullback penalty in gates to apply to confidence later
    gates["h1_pullback_penalty"] = h1_penalty
    if h1_penalty != 0.0:
        log_debug(f"[H1 PULLBACK] {h1_block_reason}")
    
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
            # CRITICAL: Check M1 confirmation before allowing entry
            m1_ready, m1_reason = _m1_confirmation_ready(higher_bias, tfi)
            if not m1_ready:
                log_debug(f"M1 confirmation blocked {higher_bias}: {m1_reason}")
                gates["m1_confirmation_blocked"] = True
                gates["m1_confirmation_reason"] = m1_reason
                reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "m1_confirmation")
                return WAIT_SIGNAL, higher_bias, "wait_for_m1_confirmation", reason, trigger
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
        # CRITICAL: Check M1 confirmation before allowing entry
        m1_ready, m1_reason = _m1_confirmation_ready(raw_candidate, tfi)
        if not m1_ready:
            log_debug(f"M1 confirmation blocked {raw_candidate}: {m1_reason}")
            gates["m1_confirmation_blocked"] = True
            gates["m1_confirmation_reason"] = m1_reason
            reason, trigger = _build_wait_metadata(raw_candidate, tfi, tfa, gates, "m1_confirmation")
            return WAIT_SIGNAL, raw_candidate, "wait_for_m1_confirmation", reason, trigger
        return raw_candidate, raw_candidate, "ready", "", ""

    if higher_bias in TRADE_SIGNALS and abs(final_score) >= WAIT_SCORE_FLOOR:
        # BUG FIX 2: M1 confirmation must apply to SELL direction too, not just BUY
        m1_ready, m1_reason = _m1_confirmation_ready(higher_bias, tfi)
        if not m1_ready:
            log_debug(f"M1 confirmation blocked {higher_bias}: {m1_reason}")
            gates["m1_confirmation_blocked"] = True
            gates["m1_confirmation_reason"] = m1_reason
            reason, trigger = _build_wait_metadata(higher_bias, tfi, tfa, gates, "m1_confirmation")
            return WAIT_SIGNAL, higher_bias, "wait_for_m1_confirmation", reason, trigger
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
    FIX #5: Entry ABOVE/BELOW pivot (not AT pivot) for better entry mechanics.
    FIX #3: Pullback depth measurement using Daily S1/R1 + ATR.
    """
    SPREAD_BUFFER = 0.3
    STOP_CUSHION = 0.2
    TARGET_CUSHION = 0.1
    PIVOT_OFFSET_ABOVE = 8.0  # Enter 8pts ABOVE pivot for BUY (better odds)
    PIVOT_OFFSET_BELOW = 8.0  # Enter 8pts BELOW pivot for SELL
    
    if signal not in TRADE_SIGNALS:
        return {"entry_price": None, "stop_loss": None, "take_profit": None, "risk_distance": None, "pullback_target": None}
    
    m1 = tfi.get("M1", {})
    m5 = tfi.get("M5", {})
    m15 = tfi.get("M15", {})
    price = _f(m1.get("close")) or _f(m5.get("close")) or _f(m15.get("close"))
    entry_atr = _f(m1.get("atr_14")) or _f(m5.get("atr_14")) or _f(m15.get("atr_14"))
    pullback_atr = _f(m5.get("atr_14")) or _f(m15.get("atr_14")) or entry_atr
    risk_atr = _f(m15.get("atr_14")) or _f(m5.get("atr_14")) or entry_atr
    
    # FIX #3: Get Daily pivot levels for entry adjustment and pullback depth measurement
    daily_s1 = _f(tfi.get("D1", {}).get("daily_s1"))
    daily_r1 = _f(tfi.get("D1", {}).get("daily_r1"))
    daily_pivot = _f(tfi.get("D1", {}).get("daily_pivot"))
    
    if price is None or pullback_atr in {None, 0} or risk_atr in {None, 0}:
        return {"entry_price": price, "stop_loss": None, "take_profit": None, "risk_distance": None, "pullback_target": None}
    
    pullback = pullback_atr * ENTRY_PULLBACK_M5_ATR_FACTOR
    anchors = [v for v in (_f(m5.get("ema_20")), _f(m5.get("vwap")), _f(m1.get("ema_20")), _f(m1.get("vwap"))) if v is not None]
    risk_distance = risk_atr * 1.5
    
    # FIX #3: Calculate pullback depth target (expected pullback zone)
    pullback_target = None
    if signal == "BUY" and daily_s1 is not None:
        # Expected pullback goes down to Daily S1 + (M15 ATR * 1.5 for buffer)
        pullback_depth = pullback_atr * 1.5
        pullback_target = daily_s1 + pullback_depth
        log_debug(f"[PULLBACK DEPTH] BUY setup: Daily S1 {daily_s1:.2f} + depth {pullback_depth:.1f} = pullback target {pullback_target:.2f}")
    elif signal == "SELL" and daily_r1 is not None:
        pullback_depth = pullback_atr * 1.5
        pullback_target = daily_r1 - pullback_depth
        log_debug(f"[PULLBACK DEPTH] SELL setup: Daily R1 {daily_r1:.2f} - depth {pullback_depth:.1f} = pullback target {pullback_target:.2f}")
    
    if signal == "BUY":
        atr_entry = price - pullback
        supports = [a for a in anchors if a <= atr_entry]
        entry = max(supports + [atr_entry]) if supports else atr_entry
        entry = entry + SPREAD_BUFFER
        
        # FIX #5: Adjust entry ABOVE pivot for better entry mechanics (not AT pivot)
        if daily_pivot is not None:
            entry_above_pivot = daily_pivot + PIVOT_OFFSET_ABOVE
            if entry < entry_above_pivot:
                log_debug(f"[ENTRY ADJUSTMENT] BUY entry adjusted from {entry:.2f} to {entry_above_pivot:.2f} (ABOVE daily pivot {daily_pivot:.2f})")
                entry = entry_above_pivot
        
        stop_loss = entry - risk_distance - STOP_CUSHION
        take_profit = entry + risk_distance * 2 - TARGET_CUSHION
        return {"entry_price": entry, "stop_loss": stop_loss, "take_profit": take_profit, "risk_distance": risk_distance, "pullback_target": pullback_target}
    
    # SELL: Validate symmetry (reverse order but same distance)
    atr_entry = price + pullback
    resistances = [a for a in anchors if a >= atr_entry]
    entry = min(resistances + [atr_entry]) if resistances else atr_entry
    entry = entry - SPREAD_BUFFER
    
    # FIX #5: Adjust entry BELOW pivot for SELL (not AT pivot)
    if daily_pivot is not None:
        entry_below_pivot = daily_pivot - PIVOT_OFFSET_BELOW
        if entry > entry_below_pivot:
            log_debug(f"[ENTRY ADJUSTMENT] SELL entry adjusted from {entry:.2f} to {entry_below_pivot:.2f} (BELOW daily pivot {daily_pivot:.2f})")
            entry = entry_below_pivot
    
    stop_loss = entry + risk_distance + STOP_CUSHION
    take_profit = entry - (risk_distance * 2) + TARGET_CUSHION
    
    # FIX #10: Validate SELL levels are properly ordered
    # For SELL: take_profit < entry < stop_loss (price above entry is risk, below is reward)
    result = {"entry_price": entry, "stop_loss": stop_loss, "take_profit": take_profit, "risk_distance": risk_distance, "pullback_target": pullback_target}
    
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
        
        # ARCHITECTURAL FIX: Pass H4 indicators to make base score dynamic
        base_score = _score(primary, h4_indicators=tfi.get("H4"))
        confirmation = _confirmation_components(tfa)
        live_entry = _live_entry_components(tfi, tfa)
        final_buy = base_score["buy_score"] + confirmation["buy_score"] + live_entry["buy_score"]
        final_sell = base_score["sell_score"] + confirmation["sell_score"] + live_entry["sell_score"]
        final_score = base_score["final_score"] + confirmation["net_score"] + live_entry["net_score"]
        final_score, m15_vol_thin, penalty_points, penalty_reason = _apply_volume_penalty(final_score, tfi, tfa)
        
        # Apply H1 Weak Bearish penalty (-1.0 for BUY signals)
        h1_trend = str(tfa.get("H1", {}).get("trend_classification", "Neutral"))
        h1_weak_penalty = 0.0
        if final_score > 0 and h1_trend == "Weak Bearish":  # Only penalize BUY-leaning scores
            if _is_structured_pullback_reentry("BUY", tfa):
                log_debug("H1 Weak Bearish score penalty waived: structured BUY pullback continuation confirmed")
            else:
                h1_weak_penalty = -1.0
                final_score += h1_weak_penalty
                log_debug(f"H1 Weak Bearish penalty applied: -1.0 to score (now {final_score:.2f})")
        
        # Apply H4 price vs EMA reality check (CRITICAL FIX 3)
        # Penalty only applies to BUY-leaning signals (final_score > 0)
        h4_ind = tfi.get("H4", {})
        h4_ema_penalty, h4_ema_reason = _h4_price_vs_ema_reality(h4_ind)
        h4_ema_flag = ""
        if final_score > 0 and h4_ema_penalty != 0.0:
            final_score += h4_ema_penalty
            h4_ema_flag = h4_ema_reason
            log_debug(f"H4 price vs EMA penalty applied: {h4_ema_penalty:.1f} to BUY score ({h4_ema_reason})")
        
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
        
        # BUG FIX 1: Negative score does not mean SELL — must have genuine sell confluence
        # Distinguish between "no setup" (<1.0), "building" (1.0 to threshold), and "ready" (>= threshold)
        if abs(final_score) < 1.0:
            raw_candidate = "NO TRADE"
            log_debug(f"Score too close to zero ({final_score:.2f}): no genuine setup in either direction")
        elif score_direction in TRADE_SIGNALS and abs(final_score) >= adjusted_threshold:
            raw_candidate = score_direction
        elif score_direction in TRADE_SIGNALS and 1.0 <= abs(final_score) < adjusted_threshold:
            direction_label = "BUY" if score_direction == "BUY" else "SELL"
            log_debug(f"{direction_label} setup building — score {abs(final_score):.2f} below threshold {adjusted_threshold:.2f}, monitoring")
            raw_candidate = score_direction
        else:
            raw_candidate = "NO TRADE"
        # ARCHITECTURAL FIX: Check if active setup should expire
        # Setups can't live forever - if conditions deteriorate or timeout passes, clear it
        setup_should_expire, expiry_reason = check_setup_expiry(final_score, tfi.get("H4", {}).get("trend_strength_ratio", 50) or 50)
        if setup_should_expire:
            log_debug(expiry_reason)
            clear_setup()
        
        # Register new setup if candidate is SELL or BUY
        if raw_candidate in TRADE_SIGNALS and get_active_setup() != raw_candidate:
            h4_strength = _f(tfi.get("H4", {}).get("trend_strength_ratio")) or 50.0
            register_setup(
                direction=raw_candidate,
                score=final_score,
                h4_strength=h4_strength,
                current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
        
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
            "h1_weak_bearish_warning": False,
            "h1_weak_bearish_reason": "",
            "h4_price_ema_flag": h4_ema_flag,
            "wait_for_confirmation": False,
            "wait_reason": "",
            "wait_trigger": "",
            "entry_timing_state": "not_actionable",
            "structured_pullback_reentry": False,
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
        # FIX 1: Enhanced M1 RSI exhaustion hard block with trend verification
        m1_rsi = _f(tfi.get("M1", {}).get("rsi_14"))
        m1_trend = str(tfi.get("M1", {}).get("trend_classification", "Neutral"))
        if m1_rsi is not None:
            if exhaustion_direction == "SELL" and m1_rsi < 30.0 and "Bullish" in m1_trend:
                gates["m1_exhaustion"] = True
                gates["m1_exhaustion_reason"] = f"M1 RSI {m1_rsi:.1f} is oversold (extreme reversal risk for SELL). HARD BLOCK until recovery."
                log_debug(f"[M1 EXHAUSTION BLOCK] SELL blocked: M1 RSI {m1_rsi:.1f} oversold + bullish trend = buyers ready for bounce")
            elif exhaustion_direction == "BUY" and m1_rsi > 65.0 and "Bearish" in m1_trend:
                gates["m1_exhaustion"] = True
                gates["m1_exhaustion_reason"] = f"M1 RSI {m1_rsi:.1f} is overbought + bearish trend (CRITICAL: buyers exhausted, imminent pullback). HARD BLOCK."
                log_debug(f"[M1 EXHAUSTION BLOCK] BUY blocked: M1 RSI {m1_rsi:.1f} overbought + bearish trend = severe exhaustion risk, wait for pullback completion")
        technical_signal, setup_direction, timing_state, wait_reason, wait_trigger = _resolve_signal_state(raw_candidate, final_score, tfa, tfi, gates)
        gates["entry_timing_state"] = timing_state
        gates["wait_for_confirmation"] = technical_signal == WAIT_SIGNAL
        gates["wait_reason"] = wait_reason
        gates["wait_trigger"] = wait_trigger
        confidence_direction = setup_direction if setup_direction in TRADE_SIGNALS else score_direction
        
        # ════════════════════════════════════════════════════════════════════
        # FIX #4: PULLBACK DETECTION & CONFIRMATION SYSTEM
        # ════════════════════════════════════════════════════════════════════
        # Check if setup is in progress during a pullback (don't enter yet)
        if confidence_direction in TRADE_SIGNALS:
            apply_pullback_state_to_gates(confidence_direction, tfa, tfi, gates)
            if gates.get("pullback_in_progress", False) and not gates.get("pullback_reversal_ready", False):
                log_debug(f"[PULLBACK CONFIRMATION WAIT] {gates.get('pullback_detection_reason', 'Pullback detected')}")
        structured_pullback_reentry = _is_structured_pullback_reentry(confidence_direction, tfa)
        gates["structured_pullback_reentry"] = structured_pullback_reentry
        if structured_pullback_reentry:
            log_debug("[STRUCTURED PULLBACK] Higher-timeframe trend intact and lower-timeframe continuation re-confirmed")

        # Compute higher_bias for M1 pullback detection
        higher_bias, _, _ = _higher_tf_bias(tfa)
        
        # Build trade levels early for Wyckoff validation
        level_direction = setup_direction if setup_direction in TRADE_SIGNALS else technical_signal
        trade_levels = _build_levels(level_direction, tfi)
        
        # ════════════════════════════════════════════════════════════════════
        # WYCKOFF ANALYSIS: DISABLED
        # ════════════════════════════════════════════════════════════════════
        # ARCHITECTURAL FIX: Wyckoff disabled cleanly - returns only NEUTRAL (0% confidence)
        # Reason: Analyzing M15/M5 timeframes is insufficient for Wyckoff structure detection
        # Wyckoff requires daily/4H chart analysis which is not in scope for entry timing
        # Current implementation only adds noise and penalties without useful information
        wyckoff_phase = "NEUTRAL"
        wyckoff_phase_strength = 0.0
        wyckoff_phase_reason = "[WYCKOFF DISABLED] Not applicable to M15/M5 entry analysis"
        wyckoff_components = {}
        
        wyckoff_phase_strength_0_1 = 0.0  # No confidence bonus
        wyckoff_imbalances = []
        is_wyckoff_valid, wyckoff_validation = True, "Wyckoff validation bypassed (disabled)"
        
        gates["wyckoff_phase"] = wyckoff_phase
        gates["wyckoff_phase_strength"] = wyckoff_phase_strength  # Now stores 0-100 graduated confidence
        gates["wyckoff_phase_reason"] = wyckoff_phase_reason
        gates["wyckoff_imbalances"] = wyckoff_imbalances
        gates["wyckoff_valid"] = is_wyckoff_valid
        gates["wyckoff_validation"] = wyckoff_validation
        
        log_debug(f"[WYCKOFF] Phase: {wyckoff_phase} ({wyckoff_phase_strength:.0f}%) - {wyckoff_phase_reason}")
        if not is_wyckoff_valid and confidence_direction in TRADE_SIGNALS:
            log_debug(f"[WYCKOFF GATE] Warning: {wyckoff_validation}")
        
        # ════════════════════════════════════════════════════════════════════
        # MARKET STRUCTURE DATABASE: 20-day levels, test counting, break probability
        # ════════════════════════════════════════════════════════════════════
        try:
            market_db = get_market_structure_database()
            
            # Build OHLC history from M15 data (if available)
            recent_ohlc = []
            m15_data = tfi.get("M15", {})
            if isinstance(m15_data.get("candle_history"), list) and len(m15_data["candle_history"]) > 0:
                recent_ohlc = m15_data["candle_history"]
            
            current_price = m15_data.get("close", 0) or tfi.get("M5", {}).get("close", 0)
            current_time = datetime.now(timezone.utc).isoformat()
            
            # Identify structural levels from recent price action
            if recent_ohlc and current_price > 0:
                market_db.identify_structural_levels(recent_ohlc, current_price, current_time)
                
                # Get nearest structural support/resistance
                nearest_support, support_strength = market_db.get_nearest_structure(current_price, "DOWN")
                nearest_resistance, resistance_strength = market_db.get_nearest_structure(current_price, "UP")
                
                # Store in gates for confidence calculation
                gates["nearest_support"] = round(nearest_support, 2) if nearest_support > 0 else None
                gates["support_strength"] = round(support_strength, 1) if nearest_support > 0 else 0.0
                gates["nearest_resistance"] = round(nearest_resistance, 2) if nearest_resistance > 0 else None
                gates["resistance_strength"] = round(resistance_strength, 1) if nearest_resistance > 0 else 0.0
                
                # Apply structural strength bonus/penalty
                structural_bonus = 0.0
                if confidence_direction == "BUY" and nearest_support > 0:
                    structural_bonus = (support_strength / 100.0) * 3.0  # Max +3% for strong support
                    gates["structural_signal"] = f"BUY supported by {support_strength:.0f}% strong level at {nearest_support}"
                elif confidence_direction == "SELL" and nearest_resistance > 0:
                    structural_bonus = (resistance_strength / 100.0) * 3.0  # Max +3% for strong resistance
                    gates["structural_signal"] = f"SELL resisted by {resistance_strength:.0f}% strong level at {nearest_resistance}"
                
                gates["structural_bonus"] = structural_bonus
                
                # Log structure summary
                support_summary = market_db.get_support_summary()
                resistance_summary = market_db.get_resistance_summary()
                log_debug(f"[STRUCTURE] Supports: {len(support_summary)} | Resistances: {len(resistance_summary)} | Bonus: +{structural_bonus:.1f}%")
                
                # Save database periodically
                market_db.save_to_disk()
        except Exception as e:
            log_debug(f"[STRUCTURE ERROR] Market structure analysis failed: {e}")
            gates["structural_bonus"] = 0.0
        
        # ════════════════════════════════════════════════════════════════════
        # EFFORT VS RESULT ANALYZER: Detect exhaustion 48-72 hours early
        # ════════════════════════════════════════════════════════════════════
        try:
            effort_analyzer = get_effort_analyzer()
            
            # Build OHLC history from M15 data
            recent_ohlc = []
            m15_data = tfi.get("M15", {})
            if isinstance(m15_data.get("candle_history"), list) and len(m15_data["candle_history"]) > 0:
                recent_ohlc = m15_data["candle_history"]
            
            if recent_ohlc:
                avg_ratio, exhaustion_summary, reversal_prob = effort_analyzer.analyze_candle_history(
                    recent_ohlc, confidence_direction
                )
                
                gates["effort_ratio"] = round(avg_ratio, 2)
                gates["exhaustion_summary"] = exhaustion_summary
                gates["reversal_probability"] = round(reversal_prob, 1)
                
                # Apply exhaustion penalty to confidence
                exhaustion_penalty = 0.0
                if reversal_prob >= 70.0:
                    # Critical exhaustion: hard block unless confirmed on pullback
                    exhaustion_penalty = -8.0
                    log_debug(f"[EXHAUSTION] CRITICAL: Reversal probability {reversal_prob:.0f}% — confidence penalty: -8%")
                    gates["exhaustion_alert"] = "CRITICAL"
                elif reversal_prob >= 50.0:
                    # Moderate exhaustion: apply penalty
                    exhaustion_penalty = -4.0
                    log_debug(f"[EXHAUSTION] Reversal probability {reversal_prob:.0f}% — confidence penalty: -4%")
                    gates["exhaustion_alert"] = "MODERATE"
                elif avg_ratio > 1.5:
                    # Strong effort-result alignment: confidence bonus
                    exhaustion_penalty = 2.0
                    log_debug(f"[STRONG EFFORT] Effort-result ratio {avg_ratio:.2f} > 1.5 — confidence bonus: +2%")
                    gates["exhaustion_alert"] = "STRONG"
                
                gates["exhaustion_penalty"] = exhaustion_penalty
        except Exception as e:
            log_debug(f"[EFFORT ERROR] Effort vs result analysis failed: {e}")
            gates["exhaustion_penalty"] = 0.0
        
        # ════════════════════════════════════════════════════════════════════
        # INSTITUTIONAL PATTERNS: Upthrust & Liquidity Sweep Detection
        # ════════════════════════════════════════════════════════════════════
        patterns = detect_institutional_patterns(
            direction=confidence_direction,
            tfi=tfi,
            tfa=tfa
        )
        
        gates["is_upthrust"] = patterns["is_upthrust"]
        gates["upthrust_severity"] = patterns["upthrust_severity"]
        gates["is_liquidity_sweep"] = patterns["is_liquidity_sweep"]
        gates["sweep_type"] = patterns["sweep_type"]
        gates["sweep_severity"] = patterns["sweep_severity"]
        gates["patterns_adjustment"] = patterns["confidence_adjustment"]
        
        patterns_summary = get_patterns_summary(patterns)
        if patterns_summary:
            log_debug(f"{patterns_summary}")
        
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
            higher_bias=higher_bias,
            pullback_in_progress=gates.get("pullback_in_progress", False),
            pullback_reversal_ready=gates.get("pullback_reversal_ready", False),
            structured_pullback_reentry=gates.get("structured_pullback_reentry", False),
            wyckoff_phase=wyckoff_phase,
            wyckoff_phase_strength=wyckoff_phase_strength,
            wyckoff_imbalances=wyckoff_imbalances,
            patterns_adjustment=patterns["confidence_adjustment"],
        )
        
        # TIER 2: Volatility-adjusted threshold & confluence scoring
        m15_atr_ratio = _f(tfi.get("M15", {}).get("atr_ratio"))
        vol_adj_threshold = _calculate_volatility_adjusted_threshold(m15_atr_ratio)
        confluence_bonus, confluence_reason = _calculate_confluence_score(tfa, level_direction)
        gates["volatility_adjusted_threshold"] = vol_adj_threshold
        gates["confluence_bonus"] = confluence_bonus
        gates["confluence_reason"] = confluence_reason
        
        # TIER 2B: Apply structural bonus from market structure database
        structural_bonus = gates.get("structural_bonus", 0.0)
        technical_confidence += structural_bonus
        if structural_bonus > 0.0:
            log_debug(f"[STRUCTURE BONUS] Applied +{structural_bonus:.1f}% to confidence (now {technical_confidence:.1f}%)")
        
        # TIER 2B2: Apply H1 pullback penalty if present
        h1_penalty = gates.get("h1_pullback_penalty", 0.0)
        if h1_penalty != 0.0:
            technical_confidence += h1_penalty
            log_debug(f"[H1 PULLBACK] Applied {h1_penalty:.1f}% penalty to confidence (now {technical_confidence:.1f}%)")
        
        # TIER 2C: Apply exhaustion penalty from effort vs result analysis
        exhaustion_penalty = gates.get("exhaustion_penalty", 0.0)
        technical_confidence += exhaustion_penalty
        if exhaustion_penalty != 0.0:
            log_debug(f"[EFFORT RESULT] Applied {exhaustion_penalty:+.1f}% to confidence (now {technical_confidence:.1f}%)")
        
        # TIER 2D: Session-adjusted Wyckoff analysis
        session_analysis = get_session_adjusted_analysis(
            wyckoff_phase, wyckoff_phase_strength, 0.0  # Base bonus is already in phase_strength
        )
        session_adjustment = session_analysis['adjusted_confidence'] - session_analysis['original_confidence']
        if session_adjustment != 0.0:
            technical_confidence += session_adjustment
            log_debug(f"[SESSION] {session_analysis['session']} session adjustment: {session_adjustment:+.1f}% (now {technical_confidence:.1f}%)")
        
        gates['current_session'] = session_analysis['session']
        
        # TIER 2E: Advanced analysis - Composite man prediction, stop hunt brackets, volatility index
        try:
            # Composite man prediction
            composite_prediction = CompositeManSimulator.predict_next_move(
                wyckoff_phase, wyckoff_phase_strength, 0.0, 0.0, {}  # Simplified call
            )
            gates['composite_next_phase'] = composite_prediction['next_phase']
            gates['composite_probability'] = composite_prediction['probability']
            
            # Stop hunt bracket prediction
            brackets = BracketPredictorEngine.predict_stop_hunt_brackets(
                wyckoff_phase, 0.0, 0.0, {}
            )
            if brackets:
                gates['predicted_brackets'] = [b['level'] for b in brackets]
                gates['bracket_intensity'] = [b['intensity'] for b in brackets]
            
            # Advanced volatility index
            atr_ratio = tfi.get("M15", {}).get("atr_ratio", 1.0)
            recent_range = tfi.get("M15", {}).get("high", 0) - tfi.get("M15", {}).get("low", 0)
            svi = AdvancedVolatilityIndex.calculate_svi(atr_ratio, recent_range, recent_range)
            market_stress = AdvancedVolatilityIndex.classify_market_stress(svi)
            gates['svi_index'] = round(svi, 2)
            gates['market_stress'] = market_stress
            
        except Exception as e:
            log_debug(f"[ADVANCED] Composite/bracket/SVI analysis failed: {e}")
        
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
        
        # FIX 10: Improved WAIT vs READY logic
        # A signal is READY only if:
        # 1. Score exceeds signal threshold (1.0+)
        # 2. Confidence meets session requirement
        # 3. No critical gates are blocking (RSI exhaustion, m1_counter, etc.)
        # Otherwise it's WAIT (building setup) or NO TRADE (invalid)
        critical_gates_active = (
            gates.get("rsi_exhausted", False) or
            gates.get("m1_counter", False) or
            gates.get("m1_exhaustion", False) or
            high_impact_news
        )
        
        if technical_signal in TRADE_SIGNALS:
            if critical_gates_active:
                log_debug(f"WAIT state: {technical_signal} blocked by critical gate(s) (exhaustion/counter/news)")
                technical_signal = WAIT_SIGNAL
                gates["wait_for_confirmation"] = True
                blocked_reason = ""
                if gates.get("rsi_exhausted"): blocked_reason = "RSI exhaustion"
                elif gates.get("m1_counter"): blocked_reason = "M1 counter"
                elif gates.get("m1_exhaustion"): blocked_reason = "M1 exhaustion"
                elif high_impact_news: blocked_reason = "high-impact news event"
                gates["wait_reason"] = f"Setup building — {blocked_reason} active. Wait for confirmation."
                gates["wait_trigger"] = f"Await {blocked_reason} resolution before entry."
            elif technical_confidence < session_min_conf:
                log_debug(f"WAIT state: Confidence {technical_confidence}% < {session_min_conf}% threshold ({session})")
                gates["confidence_threshold_rejected"] = True
                gates["confidence_threshold_value"] = technical_confidence
                gates["signal_wait_timestamp"] = datetime.now(timezone.utc).isoformat()  # Track when WAIT started
                technical_signal = WAIT_SIGNAL
                gates["wait_for_confirmation"] = True
                gates["wait_reason"] = f"Confidence only {technical_confidence}% (need {session_min_conf}%+ in {session}) — waiting for M1 pullback to confirm {setup_direction}."
                gates["wait_trigger"] = f"Wait for M1 to align: confidence to reach {session_min_conf}%+ on pullback."
            else:
                # All conditions met — signal is READY
                gates["wait_for_confirmation"] = False

        gates["wait_for_confirmation"] = technical_signal == WAIT_SIGNAL
        
        wait_reason = gates.get("wait_reason", wait_reason)
        wait_trigger = gates.get("wait_trigger", wait_trigger)

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
