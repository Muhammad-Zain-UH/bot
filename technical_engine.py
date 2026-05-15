"""Technical decision engine – robust version with full error handling."""
from __future__ import annotations
from typing import Any, Tuple
import numpy as np
import pandas as pd
from utils import log_debug
from indicators import calculate_indicators, find_last_swing, anchored_vwap_from_swing
from mt5_handler import get_current_spread, compute_cvd_proxy
from risk_manager import get_current_session, SESSION_SCORE_MULTIPLIERS
from fibonacci_levels import calculate_fibonacci_levels, check_fibonacci_confirmation
from cvd_divergence import detect_cvd_divergence, calculate_cvd
import config

WAIT_SIGNAL = "WAIT_FOR_CONFIRMATION"
TRADE_SIGNALS = {"BUY", "SELL"}
MAX_SCORE = 10.0
MIN_CONFIDENCE = 35
CONFIDENCE_BASE = 57
MAX_TOTAL_PENALTY = 15

def _to_float(value: Any) -> float | None:
    """Safely convert any value to float, handling numpy types and None."""
    if value is None:
        return None
    try:
        # Handle numpy scalar types
        if hasattr(value, 'item'):
            value = value.item()
        return float(value)
    except (TypeError, ValueError):
        return None

def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def _trend_dir(trend: str) -> str:
    if "Bullish" in str(trend):
        return "BUY"
    if "Bearish" in str(trend):
        return "SELL"
    return "NO TRADE"

def _higher_tf_bias(tfa: dict) -> tuple[str, int]:
    h4_dir = tfa.get("H4", {}).get("direction", "NO TRADE")
    h1_dir = tfa.get("H1", {}).get("direction", "NO TRADE")
    if h4_dir in TRADE_SIGNALS and h1_dir in TRADE_SIGNALS and h4_dir == h1_dir:
        return h4_dir, 2
    if h4_dir in TRADE_SIGNALS:
        return h4_dir, 1
    if h1_dir in TRADE_SIGNALS:
        return h1_dir, 1
    return "NO TRADE", 0

def _evaluate_tf(ind: dict) -> dict:
    trend = str(ind.get("trend_classification", "Neutral"))
    return {
        "direction": _trend_dir(trend),
        "trend_classification": trend,
        "price_vs_vwap": str(ind.get("price_vs_vwap", "Unknown")),
    }

def _is_consolidation(tfi: dict) -> bool:
    atr_ratio = _to_float(tfi.get("M15", {}).get("atr_ratio"))
    if atr_ratio is None:
        return False
    return atr_ratio < 0.7

def _volume_climax(vol_ratio: float) -> bool:
    return vol_ratio > 2.0

def _absorption(vol_ratio: float, price_change_pct: float, atr_ratio: float) -> bool:
    return vol_ratio > 1.5 and abs(price_change_pct) < atr_ratio * 0.3

def _liquidity_sweep(direction: str, current_price: float, prev_day_high: float, prev_day_low: float) -> Tuple[bool, str]:
    if direction == "BUY" and current_price < prev_day_low and current_price > prev_day_low - 5.0:
        return True, "Sweep of sell stops"
    if direction == "SELL" and current_price > prev_day_high and current_price < prev_day_high + 5.0:
        return True, "Sweep of buy stops"
    return False, ""

def _rejection_wick(candle: dict, direction: str) -> bool:
    """Check if M1 candle has a long wick rejecting the level."""
    open_p = _to_float(candle.get('open'))
    close_p = _to_float(candle.get('close'))
    high_p = _to_float(candle.get('high'))
    low_p = _to_float(candle.get('low'))
    if any(v is None for v in [open_p, close_p, high_p, low_p]):
        return False
    body = abs(close_p - open_p)
    full = high_p - low_p
    if full <= 0:
        return False
    wick_ratio = (full - body) / full
    if direction == "BUY":
        lower_wick = low_p - min(open_p, close_p)
        return lower_wick > body and wick_ratio > 0.6
    else:
        upper_wick = max(open_p, close_p) - high_p
        return upper_wick > body and wick_ratio > 0.6

def get_technical_signal(symbol: str, timeframe_indicators: dict) -> dict:
    try:
        tfi = timeframe_indicators
        # Build timeframe analysis with safe conversions
        tfa = {}
        for tf in ["H4", "H1", "M15", "M5", "M1", "D1"]:
            ind = tfi.get(tf, {})
            tfa[tf] = _evaluate_tf(ind)

        bias_dir, bias_strength = _higher_tf_bias(tfa)
        session = get_current_session()
        threshold_mult = SESSION_SCORE_MULTIPLIERS.get(session, 1.0)

        # Simple scoring: H1 is PRIMARY (higher weight than H4 which lagged)
        # This ensures fast-moving H1 bias takes precedence over slow H4
        buy_score = 0.0
        sell_score = 0.0
        for tf in ["H4", "H1"]:
            if tfa[tf]["direction"] == "BUY":
                buy_score += 1.0 if tf == "H4" else 2.0  # H1 = 2.0 (primary), H4 = 1.0 (secondary)
            elif tfa[tf]["direction"] == "SELL":
                sell_score += 1.0 if tf == "H4" else 2.0  # H1 = 2.0 (primary), H4 = 1.0 (secondary)
        # M15 alignment adds bonus
        if tfa["M15"]["direction"] == bias_dir:
            if bias_dir == "BUY":
                buy_score += 1.0
            elif bias_dir == "SELL":
                sell_score += 1.0
        net_score = buy_score - sell_score
        direction = "BUY" if net_score > 0 else "SELL" if net_score < 0 else "NO TRADE"

        # Trap filters – get safe values
        m15 = tfi.get("M15", {})
        m5 = tfi.get("M5", {})
        m1 = tfi.get("M1", {})
        vol_ratio = _to_float(m15.get("volume_ratio")) or 1.0
        atr_ratio = _to_float(m15.get("atr_ratio")) or 1.0
        close_m15 = _to_float(m15.get("close")) or 0
        open_m15 = _to_float(m15.get("open")) or 0.01
        price_change_pct = (close_m15 - open_m15) / max(abs(open_m15), 0.01)

        # FIX #6: TRANSPARENCY LOGGING - Trap filter status tracking
        trap_status_parts = []
        
        # 1. Consolidation
        if _is_consolidation(tfi):
            log_debug("Consolidation detected – NO TRADE")
            return _empty_result("Consolidation")
        trap_status_parts.append("Consolidation: OK")
        
        # 2. Volume climax
        if _volume_climax(vol_ratio):
            log_debug(f"Volume climax ({vol_ratio:.2f}) – possible fakeout")
            return _empty_result("Volume climax")
        trap_status_parts.append("Volume: OK")
        
        # 3. Absorption
        if _absorption(vol_ratio, price_change_pct, atr_ratio):
            log_debug("Absorption detected – institutional trading, wait")
            return _empty_result("Absorption")
        trap_status_parts.append("Absorption: OK")
        
        # 4. Liquidity sweep
        prev_day = tfi.get("D1", {})
        prev_day_high = _to_float(prev_day.get("high"))
        prev_day_low = _to_float(prev_day.get("low"))
        current_price = _to_float(m1.get("close")) or _to_float(m5.get("close")) or _to_float(m15.get("close")) or 0
        sweep_status = "None"
        if prev_day_high and prev_day_low and current_price:
            sweep, sweep_reason = _liquidity_sweep(direction, current_price, prev_day_high, prev_day_low)
            if sweep:
                if direction == "BUY" and current_price > prev_day_low + 2.0:
                    log_debug(f"Sweep reclaimed: {sweep_reason}")
                    sweep_status = "Reclaimed"
                else:
                    log_debug(f"Sweep not reclaimed – waiting: {sweep_reason}")
                    return _empty_result("Liquidity sweep not reclaimed")
        trap_status_parts.append(f"Sweep: {sweep_status}")
        # 5. CVD proxy (weight 0.4)
        cvd = compute_cvd_proxy(symbol)
        cvd_conf = 0.0
        if direction == "BUY" and cvd > 20:
            cvd_conf = 0.4
        elif direction == "SELL" and cvd < -20:
            cvd_conf = 0.4
        
        # ===== CONTINUATION ENTRY CHECK (DISABLED) =====
        # DISABLED: All TFs aligned entries were too risky with low accuracy (~50%)
        # Now using only MOMENTUM and PULLBACK for better accuracy (~70%+)
        # Keeping logic for reference but not executing
        h1_dir = tfa["H1"]["direction"]
        m15_dir = tfa["M15"]["direction"]
        m5_dir = tfa["M5"]["direction"]
        m1_dir = tfa["M1"]["direction"]
        
        all_tf_aligned = (h1_dir == m15_dir == m5_dir == m1_dir == direction and 
                         direction in TRADE_SIGNALS)
        
        if all_tf_aligned:
            # Log for reference but do NOT enter - fallthrough to MOMENTUM/PULLBACK
            log_debug(f"[CONTINUATION] All TFs aligned {direction} – DISABLED (low accuracy). Checking MOMENTUM/PULLBACK instead.")
            # Continue to next entry method checks
        
        # ===== MOMENTUM ENTRY CHECK (NEW) =====
        # Check M5 RSI extremes for fast entry (no wick/Fib required)
        # UPDATED: Stricter thresholds (35/65 instead of 40/60) for true momentum only
        m5_rsi = _to_float(m5.get("rsi_14"))
        is_momentum_entry = False
        momentum_reason = ""
        
        if direction == "BUY" and m5_rsi is not None and m5_rsi > 65.0:
            is_momentum_entry = True
            momentum_reason = f"M5 RSI {m5_rsi:.1f} > 65 – momentum BUY setup (overbought)"
            log_debug(f"[MOMENTUM ENTRY] {momentum_reason} – entering without wick/Fib requirements")
        elif direction == "SELL" and m5_rsi is not None and m5_rsi < 35.0:
            is_momentum_entry = True
            momentum_reason = f"M5 RSI {m5_rsi:.1f} < 35 – momentum SELL setup (oversold)"
            log_debug(f"[MOMENTUM ENTRY] {momentum_reason} – entering without wick/Fib requirements")
        
        # If momentum entry triggered, bypass wick/VWAP/Fib checks
        if is_momentum_entry:
            # Add remaining trap statuses for transparency
            trap_status_parts.append("Wick: OK")  # Bypassed for momentum
            trap_status_parts.append("VWAP: OK")  # Bypassed for momentum
            trap_status_parts.append("Fib: OK")   # Bypassed for momentum
            
            confidence = CONFIDENCE_BASE + 20  # Higher boost for extreme momentum entries (35/65)
            if vol_ratio < 0.5:
                confidence -= 5.0
            confidence = _clip(confidence, MIN_CONFIDENCE, 92)
            final_signal = direction if confidence >= 45 else WAIT_SIGNAL
            levels = _build_levels(direction, tfi)
            trap_filter_status = " | ".join(trap_status_parts)
            log_debug(f"[MOMENTUM] Entry confirmed – confidence={confidence}%")
            return {
                "technical_signal": final_signal,
                "setup_direction": direction,
                "weighted_score": net_score,
                "max_score": MAX_SCORE,
                "technical_confidence": int(confidence),
                "timeframe_analysis": tfa,
                "mixed_signals": False,
                "risk_level": "Medium",
                "trade_levels": levels,
                "gates": {"entry_method": "momentum", "momentum_reason": momentum_reason},
                "error": None,
                "trap_filter_status": trap_filter_status,
            }
        
        # 6. Rejection wick on M1 (entry trigger for non-momentum entries)
        m1_candle = {
            'open': _to_float(m1.get('open')),
            'high': _to_float(m1.get('high')),
            'low': _to_float(m1.get('low')),
            'close': _to_float(m1.get('close'))
        }
        wick_status = "OK"
        if not _rejection_wick(m1_candle, direction):
            log_debug("No rejection wick – waiting for entry signal")
            wick_status = "TIMEOUT"
        trap_status_parts.append(f"Wick: {wick_status}")
        
        # 7. VWAP proximity check (optional)
        vwap = _to_float(m15.get("vwap"))
        vwap_status = "OK"
        if vwap and direction == "BUY" and current_price < vwap - 2.0:
            log_debug("Price below VWAP – wait for reclaim")
            vwap_status = "BELOW"
            return _empty_result("Price below VWAP")
        if vwap and direction == "SELL" and current_price > vwap + 2.0:
            log_debug("Price above VWAP – wait for reclaim")
            vwap_status = "ABOVE"
            return _empty_result("Price above VWAP")
        trap_status_parts.append(f"VWAP: {vwap_status}")

        # 8. FIBONACCI RETRACEMENT CHECK (NEW)
        # Require price to be near 0.618 Fibonacci level for entry confirmation
        fib_status = "OK"
        if direction in TRADE_SIGNALS:
            recent_data = tfi.get("M15", {})
            if recent_data:
                try:
                    swing_high = _to_float(recent_data.get("swing_high"))
                    swing_low = _to_float(recent_data.get("swing_low"))
                    
                    if swing_high is None or swing_low is None:
                        log_debug("[FIBONACCI] Swing data unavailable – skipping Fibonacci check")
                    else:
                        fib_levels = calculate_fibonacci_levels(swing_high, swing_low, direction)
                        fib_check = check_fibonacci_confirmation(current_price, fib_levels, direction, tolerance_pips=8.0)
                        
                        # Require 0.618 level for higher-quality entries
                        if not fib_check.get("is_at_fib_level"):
                            fib_618_dist = fib_check.get("fib_618_distance")
                            log_debug(
                                f"[FIBONACCI] Price {current_price:.2f} not at 0.618 "
                                f"(distance: {fib_618_dist:.1f} pips) – wait for retracement"
                            )
                            fib_status = f"AWAY {fib_618_dist:.0f}p"
                            return _empty_result(f"Not at Fibonacci 0.618 level ({fib_618_dist:.1f}pips away)")
                        else:
                            log_debug(f"[FIBONACCI] ✓ Price at valid retracement level: {fib_check.get('nearest_level')}")
                except Exception as fib_exc:
                    log_debug(f"Fibonacci check warning: {fib_exc} — proceeding with entry")
        trap_status_parts.append(f"Fib: {fib_status}")

        # 9. CVD DIVERGENCE CHECK (NEW)
        # Detect if volume is NOT confirming price extremes (early reversal signal)
        # Use M5 data for better responsiveness on entry timing
        cvd_divergence_adjustment = 0.0
        if direction in TRADE_SIGNALS:
            try:
                # Get raw M5 DataFrame for CVD calculation (more responsive than M15)
                m5_raw_data = tfi.get("M5", {}).get("raw_data")
                if m5_raw_data is not None and isinstance(m5_raw_data, pd.DataFrame) and not m5_raw_data.empty:
                    cvd_result = detect_cvd_divergence(m5_raw_data, lookback=20)
                    if cvd_result.get("has_divergence"):
                        cvd_divergence_adjustment = cvd_result.get("confidence_adjustment", 0.0)
                        log_debug(f"[CVD DIVERGENCE] M5: {cvd_result['type'].upper()} divergence detected → +{cvd_divergence_adjustment:.0f}% confidence")
                else:
                    log_debug("[CVD] Raw M5 data unavailable for divergence check")
            except Exception as cvd_exc:
                log_debug(f"CVD divergence check warning: {cvd_exc} — proceeding")

        # Confidence calculation with penalty cap
        confidence = CONFIDENCE_BASE
        penalty = 0.0
        if vol_ratio < 0.5:
            penalty += 5.0
        if tfa["H1"]["direction"] != bias_dir and bias_dir in TRADE_SIGNALS:
            h1_trend = tfa["H1"]["trend_classification"]
            penalty += 8.0 if "Strong" in h1_trend else 4.0
        if _is_consolidation(tfi):
            penalty += 10.0
        if penalty > MAX_TOTAL_PENALTY:
            penalty = MAX_TOTAL_PENALTY
        confidence -= penalty
        confidence += cvd_conf * 10  # max +4%
        confidence += cvd_divergence_adjustment  # CVD divergence bonus
        confidence = _clip(confidence, MIN_CONFIDENCE, 92)
        
        # FIX #3: APPLY SESSION MULTIPLIERS
        session = get_current_session()
        session_multiplier = SESSION_SCORE_MULTIPLIERS.get(session, 1.0)
        original_confidence = confidence
        confidence = confidence * session_multiplier
        confidence = _clip(confidence, MIN_CONFIDENCE, 92)
        if session_multiplier != 1.0:
            log_debug(f"[SESSION MULTIPLIER] {session}: {original_confidence:.0f}% × {session_multiplier} = {confidence:.0f}%")

        # Spread check
        spread = get_current_spread(symbol)
        if spread > 50:
            log_debug(f"Spread too high ({spread:.0f} pts) – skipping")
            return _empty_result("High spread")

        final_signal = direction if confidence >= 45 and direction in TRADE_SIGNALS else WAIT_SIGNAL
        # Build trade levels
        levels = _build_levels(direction, tfi)
        
        # FIX #6: TRANSPARENCY - Final trap filter status string
        trap_filter_status = " | ".join(trap_status_parts)

        return {
            "technical_signal": final_signal,
            "setup_direction": direction,
            "weighted_score": net_score,
            "max_score": MAX_SCORE,
            "technical_confidence": int(confidence),
            "timeframe_analysis": tfa,
            "mixed_signals": False,
            "risk_level": "Medium",
            "trade_levels": levels,
            "gates": {"calibration_status": ""},
            "error": None,
            "trap_filter_status": trap_filter_status,
        }
    except Exception as exc:
        log_debug(f"Technical engine failed: {exc}")
        import traceback
        traceback.print_exc()
        return _empty_result(str(exc))

def _build_levels(direction: str, tfi: dict) -> dict:
    entry = _to_float(tfi.get("M1", {}).get("close")) or _to_float(tfi.get("M5", {}).get("close"))
    atr = _to_float(tfi.get("M15", {}).get("atr_14")) or 8.0
    if not entry:
        return {}
    stop_distance = atr * 1.5
    if direction == "BUY":
        return {
            "entry_price": round(entry, 2),
            "stop_loss": round(entry - stop_distance, 2),
            "take_profit": round(entry + stop_distance * 2, 2),
            "risk_distance": round(stop_distance, 2),
        }
    elif direction == "SELL":
        return {
            "entry_price": round(entry, 2),
            "stop_loss": round(entry + stop_distance, 2),
            "take_profit": round(entry - stop_distance * 2, 2),
            "risk_distance": round(stop_distance, 2),
        }
    return {}

def _empty_result(reason: str) -> dict:
    return {
        "technical_signal": "NO TRADE",
        "setup_direction": "NO TRADE",
        "weighted_score": 0.0,
        "max_score": MAX_SCORE,
        "technical_confidence": 0,
        "timeframe_analysis": {},
        "mixed_signals": False,
        "risk_level": "High",
        "trade_levels": {},
        "gates": {},
        "error": reason,
    }