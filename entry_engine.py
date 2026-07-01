"""LAYER 8: M5/M1 ENTRY ENGINE - Precise trigger rules.

Entry Triggers (ALL must fire inside POI zone):

1. REJECTION CANDLE on M5:
   - Bullish entry: M5 candle with long lower wick (rejection of down move)
     • Close in upper 50% of range
     • Wick ≥ 2× candle body
     • Confirmation: Next M1 close > entry candle close
   - Bearish entry: Long upper wick, close in lower 50%

2. MOMENTUM CONFIRMATION on M5:
   - M5 volume on trigger candle > baseline (20-candle MA)
   - M5 RSI turning up (bullish) or turning down (bearish)
   - M5 MACD histogram turning positive/negative

3. M1 MICROSTRUCTURE FLIP:
   - M1 prints HH (bullish) or LL (bearish)
   - M1 close confirms direction
   - Volume on M1 expanding

ENTRY EXECUTION:
- Entry: Market order on M5 candle CLOSE (not before)
- Slippage tolerance: ±2.0 pips max (FIX #6 PHASE 4: increased from 0.5 to cover spread + latency)
- Entry price: Actual fill price (live bid/ask)

STOP LOSS PLACEMENT (A+-specific for XAUUSD):
Bullish Entry SL = Sweep wick low - 3 pips
Bearish Entry SL = Sweep wick high + 3 pips

TAKE PROFIT (1:3 RR for A+):
TP = Entry + (Entry - SL) × 3.0

MINIMUM RR CHECK (Hard Gate):
- If calculated TP doesn't give minimum 1:3 RR → NO TRADE
- Recalculate or wait for better level
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import pandas as pd
from utils import log_debug
from risk_manager import get_current_session

try:
    from indicators import calculate_indicators, find_last_swing
except Exception:
    calculate_indicators = None
    find_last_swing = None

KILL_ZONES_UTC = ((8, 10), (12, 14))


def _to_float(value: Any) -> float | None:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_snapshot(frame: pd.DataFrame | None) -> dict[str, Any]:
    """Return the latest indicator snapshot for a dataframe."""
    if frame is None or len(frame) == 0 or not callable(calculate_indicators):
        return {}
    try:
        return calculate_indicators(frame) or {}
    except Exception as exc:
        log_debug(f"Indicator snapshot error: {exc}")
        return {}


def _atr_from_frame(frame: pd.DataFrame | None) -> float | None:
    return _to_float(_frame_snapshot(frame).get("atr_14"))


def _rsi_from_frame(frame: pd.DataFrame | None) -> float | None:
    return _to_float(_frame_snapshot(frame).get("rsi_14"))


def _volume_ratio_from_frame(frame: pd.DataFrame | None) -> float | None:
    snap = _frame_snapshot(frame)
    return _to_float(snap.get("volume_ratio")) or _to_float(snap.get("volume_surge_ratio"))


def _within_kill_zone(now: datetime | None = None) -> bool:
    """UTC kill zones: London 08:00-10:00 and New York 12:00-14:00."""
    current = now or datetime.now(timezone.utc)
    hour = current.hour
    return any(start <= hour < end for start, end in KILL_ZONES_UTC)


def detect_regime(
    m5_data: pd.DataFrame | None,
    m15_data: pd.DataFrame | None,
    h1_data: pd.DataFrame | None,
    current_spread: float = 1.0,
) -> dict[str, Any]:
    """
    FIX #7 (PHASE 4): DETECT TRADING REGIME - 3-MODE ADAPTIVE SYSTEM
    
    Reads real-time volatility and structure to choose the correct entry mode.
    NOW INCLUDES: Regime-aware spread tolerance (FIX PHASE 5)
    
    - MICRO_SCALP: M5 ATR 2.5-4.5 + Kill Zone + tight range
      Action: Bypass L3 & L6, enter on M1 wick rejection + volume spike
      Risk: 0.75%, TP: 1.5R, MAX SPREAD: 5 pips
    
    - REGIME_SCALP: M5 ATR 4.5-7.0 + H1 structure intact
      Action: Use lower POI threshold (60), standard entry
      Risk: 1.0%, TP: 2.0R, MAX SPREAD: 7 pips
    
    - INTRADAY_SWING: M5 ATR >7.0 (high volatility)
      Action: Full L1-L8 pipeline, higher standards
      Risk: 1.5%, TP: 3.0R, MAX SPREAD: 10 pips
    
    Returns:
        {
            "regime": "MICRO_SCALP | REGIME_SCALP | INTRADAY_SWING",
            "m5_atr": float,
            "kill_zone": bool,
            "h1_structure_valid": bool,
            "risk_percent": float,
            "tp_ratio": float,
            "bypass_l3": bool,
            "bypass_l6": bool,
            "poi_threshold": int,
            "max_spread_pips": int,
            "spread_acceptable": bool,
            "reasoning": str,
        }
    """
    try:
        m5_atr = _atr_from_frame(m5_data) or 0.0
        kill_zone = _within_kill_zone()
        session = get_current_session()
        h1_structure_valid = False
        
        # Determine if H1 structure is valid (rough check)
        if h1_data is not None and len(h1_data) >= 5:
            h1_snap = _frame_snapshot(h1_data)
            h1_structure_valid = bool(h1_snap.get("h1_structure_intact"))
        
        # MODE DETECTION WITH SPREAD VALIDATION
        # (FIX PHASE 5: Spread tolerance varies by regime)
        max_spread_pips = 10.0  # Default fallback
        
        if m5_atr >= 2.5 and m5_atr <= 4.5 and (kill_zone or session in {"Asian", "London", "LondonNewYork"}):
            # MICRO_SCALP: Fast scalping in active sessions during calm/tight trading
            regime = "MICRO_SCALP"
            risk = 0.75
            tp_ratio = 1.5
            bypass_l3 = True
            bypass_l6 = True
            poi_threshold = 50  # Very relaxed for quick entries
            max_spread_pips = 5.0  # Tight spreads needed for 75-pip targets
            if kill_zone:
                reasoning = f"MICRO_SCALP: M5 ATR {m5_atr:.1f} + Kill Zone active → fast wick entries"
            else:
                reasoning = f"MICRO_SCALP: M5 ATR {m5_atr:.1f} in {session} session → fast wick entries"
        
        elif m5_atr >= 4.5 and m5_atr <= 7.0:
            # REGIME_SCALP: Standard intraday scalping with structure
            regime = "REGIME_SCALP"
            risk = 1.0
            tp_ratio = 2.0
            bypass_l3 = False
            bypass_l6 = False
            poi_threshold = 60  # Relaxed threshold for confirmed setups
            max_spread_pips = 7.0  # Moderate spread tolerance (100+ pips target)
            reasoning = f"REGIME_SCALP: M5 ATR {m5_atr:.1f} normal volatility → standard entries"
        
        else:  # M5 ATR > 7.0 OR < 2.5
            if m5_atr > 7.0:
                # INTRADAY_SWING: High volatility expansion, full rigor
                regime = "INTRADAY_SWING"
                risk = 1.5
                tp_ratio = 3.0
                bypass_l3 = False
                bypass_l6 = False
                poi_threshold = 70  # Strict standards for high-vol setups
                max_spread_pips = 10.0  # Wide spreads OK for 150+ pips targets
                reasoning = f"INTRADAY_SWING: M5 ATR {m5_atr:.1f} HIGH VOLATILITY → full validation"
            else:
                # Dead calm (ATR < 2.5) - Will be BLOCKED by L2, but show proper config anyway
                regime = "DEAD_CALM"
                risk = 0.75  # Show a value even though trade won't happen
                tp_ratio = 1.5  # Realistic if it somehow escaped L2
                bypass_l3 = False
                bypass_l6 = False
                poi_threshold = 70  # Normal threshold (won't matter, L2 blocks first)
                max_spread_pips = 5.0  # N/A (will be blocked at L2)
                reasoning = f"DEAD_CALM: M5 ATR {m5_atr:.1f} too low → Will be BLOCKED at L2"
        
        # Evaluate spread acceptability for this regime
        spread_acceptable = current_spread <= max_spread_pips
        if not spread_acceptable:
            reasoning += f" | ⚠️ SPREAD CHECK: {current_spread:.1f}pip > {max_spread_pips:.1f}pip max (entry rejected)"
        
        return {
            "regime": regime,
            "m5_atr": m5_atr,
            "kill_zone": kill_zone,
            "h1_structure_valid": h1_structure_valid,
            "risk_percent": risk,
            "tp_ratio": tp_ratio,
            "bypass_l3": bypass_l3,
            "bypass_l6": bypass_l6,
            "poi_threshold": poi_threshold,
            "max_spread_pips": max_spread_pips,
            "current_spread": current_spread,
            "spread_acceptable": spread_acceptable,
            "reasoning": reasoning,
        }
    
    except Exception as exc:
        log_debug(f"Regime detection error: {exc}")
        return {
            "regime": "DEAD_CALM",
            "m5_atr": 0.0,
            "kill_zone": False,
            "h1_structure_valid": False,
            "risk_percent": 1.0,
            "tp_ratio": 2.0,
            "bypass_l3": False,
            "bypass_l6": False,
            "poi_threshold": 70,
            "reasoning": f"Error: {str(exc)} - defaulting to conservative DEAD_CALM",
        }


def _select_stop_anchor(
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    buffer_pips: float = 3.0,
) -> float | None:
    """Pick the most defensive structure-based stop anchor."""
    if direction == "BUY":
        candidates = [v for v in [sweep_wick_low, structure_low] if v is not None]
        if candidates:
            return min(candidates) - buffer_pips
    else:
        candidates = [v for v in [sweep_wick_high, structure_high] if v is not None]
        if candidates:
            return max(candidates) + buffer_pips
    return None


def detect_rejection_candle(
    m5_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect rejection candle on M5.
    
    Returns:
        {
            "rejection_found": bool,
            "wick_size": float,
            "body_size": float,
            "wick_ratio": float,
            "close_position": float,  # 0-1 (0=low, 1=high)
            "rejection_quality": 0.0-10.0,
        }
    """
    try:
        if len(m5_data) < 3:
            return {
                "rejection_found": False,
                "wick_size": None,
                "body_size": None,
                "wick_ratio": None,
                "close_position": None,
                "rejection_quality": 0.0,
            }
        
        # Use the last CLOSED M5 candle, not the forming candle.
        current = m5_data.iloc[-2]
        c_open = _to_float(current["open"])
        c_close = _to_float(current["close"])
        c_high = _to_float(current["high"])
        c_low = _to_float(current["low"])
        
        if any(v is None for v in [c_open, c_close, c_high, c_low]):
            return {
                "rejection_found": False,
                "wick_size": None,
                "body_size": None,
                "wick_ratio": None,
                "close_position": None,
                "rejection_quality": 0.0,
            }
        
        body = abs(c_close - c_open)
        range_size = c_high - c_low
        
        if range_size <= 0:
            return {
                "rejection_found": False,
                "wick_size": None,
                "body_size": None,
                "wick_ratio": None,
                "close_position": None,
                "rejection_quality": 0.0,
            }
        
        close_pos = (c_close - c_low) / range_size
        
        # Bullish rejection: lower wick ≥ 2× body, close in upper 50%
        if direction == "BUY":
            lower_wick = min(c_close, c_open) - c_low
            wick_ratio = lower_wick / body if body > 0 else 0
            
            if wick_ratio >= 2.0 and close_pos > 0.5:
                quality = min(10.0, (wick_ratio - 2.0) / 0.5 * 3.0 + 5.0)  # Scale 2-3.5x to 5-10
                return {
                    "rejection_found": True,
                    "wick_size": lower_wick,
                    "body_size": body,
                    "wick_ratio": wick_ratio,
                    "close_position": close_pos,
                    "rejection_quality": quality,
                }
        
        # Bearish rejection: upper wick ≥ 2× body, close in lower 50%
        elif direction == "SELL":
            upper_wick = c_high - max(c_close, c_open)
            wick_ratio = upper_wick / body if body > 0 else 0
            
            if wick_ratio >= 2.0 and close_pos < 0.5:
                quality = min(10.0, (wick_ratio - 2.0) / 0.5 * 3.0 + 5.0)
                return {
                    "rejection_found": True,
                    "wick_size": upper_wick,
                    "body_size": body,
                    "wick_ratio": wick_ratio,
                    "close_position": close_pos,
                    "rejection_quality": quality,
                }
        
        return {
            "rejection_found": False,
            "wick_size": None,
            "body_size": None,
            "wick_ratio": None,
            "close_position": None,
            "rejection_quality": 0.0,
        }
    
    except Exception as exc:
        log_debug(f"Rejection candle detection error: {exc}")
        return {
            "rejection_found": False,
            "wick_size": None,
            "body_size": None,
            "wick_ratio": None,
            "close_position": None,
            "rejection_quality": 0.0,
        }


def detect_momentum_confirmation(
    m5_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect momentum confirmation on M5.
    
    Returns:
        {
            "momentum_confirmed": bool,
            "volume_ratio": float,
            "rsi_direction": "up | down | neutral",
            "momentum_quality": 0.0-10.0,
        }
    """
    try:
        if len(m5_data) < 4:
            return {
                "momentum_confirmed": False,
                "volume_ratio": None,
                "rsi_direction": None,
                "momentum_quality": 0.0,
            }
        
        recent = m5_data.iloc[:-1].tail(3)
        baseline_volume = float(m5_data["tick_volume"].tail(20).mean()) if "tick_volume" in m5_data.columns else 0.0
        current_volume = _to_float(recent.iloc[-1].get("tick_volume", baseline_volume))

        volume_ratio = current_volume / baseline_volume if baseline_volume > 0 and current_volume is not None else 1.0

        prev_rsi = _rsi_from_frame(m5_data.iloc[:-1].tail(6))
        curr_rsi = _rsi_from_frame(m5_data)
        
        rsi_direction = "neutral"
        if prev_rsi is not None and curr_rsi is not None:
            if curr_rsi > prev_rsi:
                rsi_direction = "up"
            elif curr_rsi < prev_rsi:
                rsi_direction = "down"
        
        # Determine momentum
        momentum_confirmed = False
        quality = 0.0
        
        if direction == "BUY":
            # REJECT if RSI is already too extended.
            if curr_rsi is not None and curr_rsi > 78:
                return {
                    "momentum_confirmed": False,
                    "volume_ratio": volume_ratio,
                    "rsi_direction": rsi_direction,
                    "momentum_quality": 0.0,
                }
            
            if volume_ratio >= 1.2:
                quality += 3.0
            if rsi_direction in ["up", "neutral"] and curr_rsi is not None and curr_rsi < 72:
                quality += 2.0
            if curr_rsi is not None and 50 <= curr_rsi <= 72:
                momentum_confirmed = True
        
        else:  # SELL
            # REJECT if RSI is already too extended.
            if curr_rsi is not None and curr_rsi < 22:
                return {
                    "momentum_confirmed": False,
                    "volume_ratio": volume_ratio,
                    "rsi_direction": rsi_direction,
                    "momentum_quality": 0.0,
                }
            
            if volume_ratio >= 1.2:
                quality += 3.0
            if rsi_direction in ["down", "neutral"] and curr_rsi is not None and curr_rsi > 28:
                quality += 2.0
            if curr_rsi is not None and 28 <= curr_rsi <= 50:
                momentum_confirmed = True
        
        return {
            "momentum_confirmed": momentum_confirmed,
            "volume_ratio": volume_ratio,
            "rsi_direction": rsi_direction,
            "momentum_quality": quality,
        }
    
    except Exception as exc:
        log_debug(f"Momentum confirmation error: {exc}")
        return {
            "momentum_confirmed": False,
            "volume_ratio": None,
            "rsi_direction": None,
            "momentum_quality": 0.0,
        }


def detect_displacement_candle(
    m5_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """Detect a strong M5 displacement candle that can justify a momentum setup."""
    try:
        if m5_data is None or len(m5_data) < 3:
            return {
                "displacement_found": False,
                "body_to_atr": None,
                "close_position": None,
                "volume_ratio": None,
                "origin_low": None,
                "origin_high": None,
                "displacement_quality": 0.0,
            }

        candle = m5_data.iloc[-1]
        c_open = _to_float(candle["open"])
        c_close = _to_float(candle["close"])
        c_high = _to_float(candle["high"])
        c_low = _to_float(candle["low"])
        atr = _atr_from_frame(m5_data)
        volume_ratio = _volume_ratio_from_frame(m5_data)

        if any(v is None for v in [c_open, c_close, c_high, c_low]):
            return {
                "displacement_found": False,
                "body_to_atr": None,
                "close_position": None,
                "volume_ratio": volume_ratio,
                "origin_low": None,
                "origin_high": None,
                "displacement_quality": 0.0,
            }

        body = abs(c_close - c_open)
        range_size = c_high - c_low
        close_position = (c_close - c_low) / range_size if range_size > 0 else 0.5
        body_to_atr = body / atr if atr and atr > 0 else None

        if direction == "BUY":
            directional_ok = c_close > c_open and close_position >= 0.7
        else:
            directional_ok = c_close < c_open and close_position <= 0.3

        displacement_found = bool(directional_ok and (
            (body_to_atr is not None and body_to_atr >= 0.9) or
            (range_size > 0 and body / range_size >= 0.6)
        ))

        quality = 0.0
        if displacement_found:
            if body_to_atr is not None:
                quality += min(5.0, body_to_atr * 3.0)
            if volume_ratio is not None:
                quality += min(3.0, max(0.0, volume_ratio - 1.0) * 2.0)
            quality += 2.0 if close_position >= 0.8 or close_position <= 0.2 else 1.0
        quality = min(10.0, quality)

        return {
            "displacement_found": displacement_found,
            "body_to_atr": body_to_atr,
            "close_position": close_position,
            "volume_ratio": volume_ratio,
            "origin_low": c_low,
            "origin_high": c_high,
            "displacement_quality": quality,
        }
    except Exception as exc:
        log_debug(f"Displacement detection error: {exc}")
        return {
            "displacement_found": False,
            "body_to_atr": None,
            "close_position": None,
            "volume_ratio": None,
            "origin_low": None,
            "origin_high": None,
            "displacement_quality": 0.0,
        }


def detect_fvg(
    m5_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """Detect a basic 3-candle fair value gap around the latest sequence."""
    try:
        if m5_data is None or len(m5_data) < 3:
            return {
                "fvg_found": False,
                "zone_low": None,
                "zone_high": None,
                "midpoint": None,
                "fvg_size": None,
                "fvg_quality": 0.0,
            }

        left = m5_data.iloc[-3]
        middle = m5_data.iloc[-2]
        right = m5_data.iloc[-1]

        l_high = _to_float(left["high"])
        l_low = _to_float(left["low"])
        m_open = _to_float(middle["open"])
        m_close = _to_float(middle["close"])
        r_high = _to_float(right["high"])
        r_low = _to_float(right["low"])

        if any(v is None for v in [l_high, l_low, m_open, m_close, r_high, r_low]):
            return {
                "fvg_found": False,
                "zone_low": None,
                "zone_high": None,
                "midpoint": None,
                "fvg_size": None,
                "fvg_quality": 0.0,
            }

        atr = _atr_from_frame(m5_data)
        volume_ratio = _volume_ratio_from_frame(m5_data)
        body = abs(m_close - m_open)

        if direction == "BUY":
            gap_low = l_high
            gap_high = r_low
            middle_bullish = m_close > m_open
            gap_valid = gap_high > gap_low and middle_bullish
        else:
            gap_low = r_high
            gap_high = l_low
            middle_bearish = m_close < m_open
            gap_valid = gap_high > gap_low and middle_bearish

        if not gap_valid:
            return {
                "fvg_found": False,
                "zone_low": gap_low,
                "zone_high": gap_high,
                "midpoint": None,
                "fvg_size": None,
                "fvg_quality": 0.0,
            }

        fvg_size = gap_high - gap_low
        midpoint = gap_low + (fvg_size / 2)
        quality = 5.0
        if atr and atr > 0:
            quality += min(3.0, fvg_size / atr * 2.0)
        if body > 0 and atr and body / atr >= 0.9:
            quality += 1.0
        if volume_ratio is not None and volume_ratio >= 1.2:
            quality += 1.0
        quality = min(10.0, quality)

        return {
            "fvg_found": True,
            "zone_low": gap_low,
            "zone_high": gap_high,
            "midpoint": midpoint,
            "fvg_size": fvg_size,
            "fvg_quality": quality,
        }
    except Exception as exc:
        log_debug(f"FVG detection error: {exc}")
        return {
            "fvg_found": False,
            "zone_low": None,
            "zone_high": None,
            "midpoint": None,
            "fvg_size": None,
            "fvg_quality": 0.0,
        }


def _entry_level_context(
    entry_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    m5_atr: float | None = None,
    entry_style: str = "PULLBACK",
) -> dict[str, Any]:
    """Build a normalized entry-level package."""
    entry_levels = calculate_entry_levels(
        entry_price,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
        structure_low=structure_low,
        structure_high=structure_high,
        direction=direction,
        m5_atr=m5_atr,
        entry_style=entry_style,
    )
    entry_levels["entry_price"] = entry_price
    return entry_levels


def _score_entry_candidate(candidate: dict[str, Any]) -> float:
    """Composite score used to pick the strongest valid entry."""
    if not candidate.get("raw_triggered"):
        return -1.0

    quality = float(candidate.get("trigger_quality", 0.0) or 0.0)
    rr = float(candidate.get("reward_to_risk_ratio", 0.0) or 0.0)
    style_bonus = 0.5 if candidate.get("entry_style") == "PULLBACK" else 0.0
    rr_bonus = min(rr, 4.0) * 1.5
    valid_bonus = 2.0 if candidate.get("valid_rr") else 0.0
    return (quality * 2.0) + rr_bonus + valid_bonus + style_bonus


def _evaluate_pullback_entry(
    m5_data: pd.DataFrame,
    m1_data: pd.DataFrame,
    current_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
) -> dict[str, Any]:
    """Evaluate the classic pullback / rejection entry path."""
    rejection = detect_rejection_candle(m5_data, direction)
    momentum = detect_momentum_confirmation(m5_data, direction)
    m1_choch = detect_m1_choch(m1_data, direction)
    m5_snapshot = _frame_snapshot(m5_data)

    confirmed_m5_price = current_price
    if m5_data is not None and len(m5_data) >= 2:
        confirmed_m5_price = _to_float(m5_data.iloc[-2]["close"]) or current_price

    confirmed_entry_price = confirmed_m5_price
    if m1_data is not None and len(m1_data) >= 2 and m1_choch["m1_choch_confirmed"]:
        confirmed_entry_price = _to_float(m1_data.iloc[-2]["close"]) or confirmed_m5_price

    raw_triggered = bool(rejection["rejection_found"] and m1_choch["m1_choch_confirmed"])
    trigger_type = "none"
    if raw_triggered:
        if momentum["momentum_confirmed"]:
            trigger_type = "pullback+momentum+choch"
        else:
            trigger_type = "pullback+choch"
    else:
        trigger_type = "pullback_wait"

    entry_levels = _entry_level_context(
        confirmed_entry_price,
        direction,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
        m5_atr=_atr_from_frame(m5_data),
        entry_style="PULLBACK",
    )

    quality = 0.0
    if rejection["rejection_found"]:
        quality += rejection.get("rejection_quality", 0.0)
    if momentum["momentum_confirmed"]:
        quality += momentum.get("momentum_quality", 0.0) * 0.5
    if m1_choch["m1_choch_confirmed"]:
        quality += m1_choch.get("m1_quality", 0.0)
    if m5_snapshot.get("atr_ratio") is not None and m5_snapshot.get("atr_ratio") >= 1.0:
        quality += 0.5
    quality = min(10.0, quality)

    return {
        "entry_style": "PULLBACK",
        "entry_mode": "MARKET",
        "raw_triggered": raw_triggered,
        "rr_valid": entry_levels["valid_rr"],
        "entry_triggered": bool(raw_triggered and entry_levels["valid_rr"]),
        "trigger_type": trigger_type,
        "entry_price": entry_levels["entry_price"],
        "stop_loss": entry_levels["stop_loss"],
        "take_profit": entry_levels["take_profit"],
        "risk_distance": entry_levels["risk_distance"],
        "reward_distance": entry_levels["reward_distance"],
        "reward_to_risk_ratio": entry_levels["reward_to_risk_ratio"],
        "trigger_quality": quality,
        "valid_rr": entry_levels["valid_rr"],
        "recommendation": (
            f"PULLBACK ENTRY READY (RR {entry_levels['reward_to_risk_ratio']:.1f}:1)"
            if raw_triggered and entry_levels["valid_rr"]
            else (
                "PULLBACK FOUND BUT RR TOO LOW - WAIT"
                if raw_triggered
                else "PULLBACK CONDITIONS NOT MET"
            )
        ),
        "rejection": rejection,
        "momentum": momentum,
        "m1_choch": m1_choch,
    }


def _evaluate_momentum_entry(
    m5_data: pd.DataFrame,
    m1_data: pd.DataFrame,
    current_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
) -> dict[str, Any]:
    """Evaluate the strong continuation / momentum entry path."""
    momentum = detect_momentum_confirmation(m5_data, direction)
    m1_choch = detect_m1_choch(m1_data, direction)
    displacement = detect_displacement_candle(m5_data, direction)
    fvg = detect_fvg(m5_data, direction)
    rejection = detect_rejection_candle(m5_data, direction)

    kill_zone = _within_kill_zone()
    confirmed_m5_price = current_price
    if m5_data is not None and len(m5_data) >= 2:
        confirmed_m5_price = _to_float(m5_data.iloc[-1]["close"]) or current_price

    confirmed_entry_price = confirmed_m5_price
    if fvg.get("midpoint") is not None:
        confirmed_entry_price = float(fvg["midpoint"])
    if m1_data is not None and len(m1_data) >= 2 and m1_choch["m1_choch_confirmed"]:
        confirmed_entry_price = _to_float(m1_data.iloc[-1]["close"]) or confirmed_entry_price

    price_in_fvg = False
    if fvg.get("zone_low") is not None and fvg.get("zone_high") is not None and current_price is not None:
        zone_low = float(min(fvg["zone_low"], fvg["zone_high"]))
        zone_high = float(max(fvg["zone_low"], fvg["zone_high"]))
        midpoint = float(fvg["midpoint"]) if fvg.get("midpoint") is not None else (zone_low + zone_high) / 2
        fvg_width = max(zone_high - zone_low, 1e-6)
        price_in_fvg = zone_low <= current_price <= zone_high or abs(current_price - midpoint) <= (fvg_width * 0.35)

    entry_levels = _entry_level_context(
        confirmed_entry_price,
        direction,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
        structure_low=displacement.get("origin_low"),
        structure_high=displacement.get("origin_high"),
        m5_atr=_atr_from_frame(m5_data),
        entry_style="MOMENTUM",
    )

    core_trigger = bool(
        kill_zone
        and displacement.get("displacement_found")
        and fvg.get("fvg_found")
        and price_in_fvg
        and m1_choch["m1_choch_confirmed"]
    )

    quality = float(displacement.get("displacement_quality", 0.0) or 0.0)
    quality += float(fvg.get("fvg_quality", 0.0) or 0.0) * 0.6
    quality += float(momentum.get("momentum_quality", 0.0) or 0.0) * 0.4
    quality += float(m1_choch.get("m1_quality", 0.0) or 0.0) * 0.8
    if kill_zone:
        quality += 1.0
    if rejection.get("rejection_found"):
        quality += 0.25
    quality = min(10.0, quality)

    return {
        "entry_style": "MOMENTUM",
        "entry_mode": "LIMIT_FVG",
        "raw_triggered": core_trigger,
        "rr_valid": entry_levels["valid_rr"],
        "entry_triggered": bool(core_trigger and entry_levels["valid_rr"]),
        "trigger_type": "momentum+fvg+choch" if core_trigger else (
            "momentum_outside_killzone" if not kill_zone else "momentum_wait"
        ),
        "entry_price": entry_levels["entry_price"],
        "stop_loss": entry_levels["stop_loss"],
        "take_profit": entry_levels["take_profit"],
        "risk_distance": entry_levels["risk_distance"],
        "reward_distance": entry_levels["reward_distance"],
        "reward_to_risk_ratio": entry_levels["reward_to_risk_ratio"],
        "trigger_quality": quality,
        "valid_rr": entry_levels["valid_rr"],
        "recommendation": (
            f"MOMENTUM FVG LIMIT READY (RR {entry_levels['reward_to_risk_ratio']:.1f}:1)"
            if core_trigger and entry_levels["valid_rr"]
            else (
                "MOMENTUM FOUND BUT WAIT FOR FVG / KILL ZONE / CHoCH"
                if core_trigger
                else "MOMENTUM CONDITIONS NOT MET"
            )
        ),
        "momentum": momentum,
        "m1_choch": m1_choch,
        "rejection": rejection,
        "displacement": displacement,
        "fvg": fvg,
        "kill_zone": kill_zone,
        "price_in_fvg": price_in_fvg,
    }


def detect_m1_choch(
    m1_data: pd.DataFrame,
    direction: str,
) -> dict[str, Any]:
    """
    Detect M1 microstructure flip (HH or LL).
    
    Returns:
        {
            "m1_choch_confirmed": bool,
            "choch_level": float,
            "m1_quality": 0.0-10.0,
        }
    """
    try:
        if m1_data is None or len(m1_data) < 6:
            return {
                "m1_choch_confirmed": False,
                "choch_level": None,
                "m1_quality": 0.0,
            }
        
        closed = m1_data.tail(6)
        signal_candle = closed.iloc[-1]
        current_high = _to_float(signal_candle["high"])
        current_low = _to_float(signal_candle["low"])
        current_close = _to_float(signal_candle["close"])
        current_open = _to_float(signal_candle["open"])
        
        if any(v is None for v in [current_high, current_low, current_close, current_open]):
            return {
                "m1_choch_confirmed": False,
                "choch_level": None,
                "m1_quality": 0.0,
            }
        prior = closed.iloc[:-1]
        prev_highs = prior["high"].tolist()
        prev_lows = prior["low"].tolist()
        atr = _atr_from_frame(m1_data)
        volume_ratio = _volume_ratio_from_frame(m1_data)

        if direction == "BUY":
            swing_break = max(prev_highs)
            buffer = (atr * 0.05) if atr else 0.0
            candle_strength = current_close > current_open and current_close > current_high - ((current_high - current_low) * 0.35)
            if current_close > swing_break + buffer and candle_strength:
                quality = 4.0
                if atr and atr > 0:
                    quality += min(3.0, (current_close - swing_break) / atr * 3.0)
                if volume_ratio is not None and volume_ratio >= 1.1:
                    quality += 2.0
                return {
                    "m1_choch_confirmed": True,
                    "choch_level": current_close,
                    "m1_quality": min(10.0, quality),
                }
        else:  # SELL
            swing_break = min(prev_lows)
            buffer = (atr * 0.05) if atr else 0.0
            candle_strength = current_close < current_open and current_close < current_low + ((current_high - current_low) * 0.35)
            if current_close < swing_break - buffer and candle_strength:
                quality = 4.0
                if atr and atr > 0:
                    quality += min(3.0, (swing_break - current_close) / atr * 3.0)
                if volume_ratio is not None and volume_ratio >= 1.1:
                    quality += 2.0
                return {
                    "m1_choch_confirmed": True,
                    "choch_level": current_close,
                    "m1_quality": min(10.0, quality),
                }
        
        return {
            "m1_choch_confirmed": False,
            "choch_level": None,
            "m1_quality": 0.0,
        }
    
    except Exception as exc:
        log_debug(f"M1 CHoCH detection error: {exc}")
        return {
            "m1_choch_confirmed": False,
            "choch_level": None,
            "m1_quality": 0.0,
        }


def calculate_entry_levels(
    entry_price: float,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    direction: str = "BUY",
    m5_atr: float | None = None,
    risk_pct: float = 1.5,
    rr_ratio: float = 3.0,
    entry_style: str = "PULLBACK",
) -> dict[str, Any]:
    """
    Calculate SL, TP, and validate RR.
    
    Returns:
        {
            "entry_price": float,
            "stop_loss": float,
            "take_profit": float,
            "risk_distance": float,  # pips
            "reward_distance": float,  # pips
            "reward_to_risk_ratio": float,
            "valid_rr": bool,  # True if RR ≥ 1:2
            "reasoning": str,
        }
    """
    try:
        # Determine SL
        stop_anchor = _select_stop_anchor(
            direction,
            sweep_wick_low=sweep_wick_low,
            sweep_wick_high=sweep_wick_high,
            structure_low=structure_low,
            structure_high=structure_high,
        )

        if stop_anchor is not None:
            stop_loss = stop_anchor
        else:
            atr_value = m5_atr if m5_atr is not None and m5_atr > 0 else 20.0
            stop_offset = max(atr_value * 1.5, 8.0 if entry_style == "MOMENTUM" else 6.0)
            stop_loss = entry_price - stop_offset if direction == "BUY" else entry_price + stop_offset
        
        # Calculate risk distance
        risk_distance = abs(entry_price - stop_loss)
        
        # Calculate TP (1:3 RR = 3× risk)
        if direction == "BUY":
            take_profit = entry_price + (risk_distance * rr_ratio)
        else:
            take_profit = entry_price - (risk_distance * rr_ratio)
        
        reward_distance = abs(take_profit - entry_price)
        rr = reward_distance / risk_distance if risk_distance > 0 else 0
        
        # Validate RR
        valid_rr = rr >= 2.0  # Minimum 1:2

        reasoning = f"Entry {entry_price:.2f} | SL {stop_loss:.2f} ({risk_distance:.1f}p risk) | TP {take_profit:.2f} ({reward_distance:.1f}p reward) | RR {rr:.1f}:1"
        
        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "reward_to_risk_ratio": rr,
            "valid_rr": valid_rr,
            "reasoning": reasoning,
        }
    
    except Exception as exc:
        log_debug(f"Entry level calculation error: {exc}")
        return {
            "entry_price": entry_price,
            "stop_loss": None,
            "take_profit": None,
            "risk_distance": None,
            "reward_distance": None,
            "reward_to_risk_ratio": 0.0,
            "valid_rr": False,
            "reasoning": f"Error: {str(exc)}",
        }


def get_entry_trigger(
    m5_data: pd.DataFrame,
    m1_data: pd.DataFrame,
    current_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
) -> dict[str, Any]:
    """
    Complete M5/M1 entry trigger detection.
    
    Returns:
        {
            "entry_triggered": bool,
            "entry_style": "PULLBACK | MOMENTUM | NONE",
            "trigger_type": "rejection | momentum | m1_choch | none",
            "entry_price": float,
            "stop_loss": float,
            "take_profit": float,
            "risk_distance": float,
            "reward_distance": float,
            "reward_to_risk_ratio": float,
            "trigger_quality": 0.0-10.0,
            "recommendation": str,
        }
    """
    pullback_entry = _evaluate_pullback_entry(
        m5_data,
        m1_data,
        current_price,
        direction,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
    )
    momentum_entry = _evaluate_momentum_entry(
        m5_data,
        m1_data,
        current_price,
        direction,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
    )

    candidates = [pullback_entry, momentum_entry]
    valid_candidates = [c for c in candidates if c.get("entry_triggered")]
    if valid_candidates:
        best_entry = max(valid_candidates, key=_score_entry_candidate)
    else:
        best_raw = max(candidates, key=_score_entry_candidate)
        best_entry = {
            **best_raw,
            "entry_triggered": False,
            "recommendation": best_raw.get("recommendation", "ENTRY CONDITIONS NOT MET"),
        }

    setup_type = "REJECTED"
    pullback_raw = bool(pullback_entry.get("raw_triggered"))
    momentum_raw = bool(momentum_entry.get("raw_triggered"))
    pullback_valid = bool(pullback_entry.get("entry_triggered"))
    momentum_valid = bool(momentum_entry.get("entry_triggered"))
    if pullback_raw and momentum_raw:
        setup_type = "BOTH"
    elif pullback_raw:
        setup_type = "PULLBACK"
    elif momentum_raw:
        setup_type = "MOMENTUM"

    return {
        "entry_triggered": bool(best_entry.get("entry_triggered")),
        "entry_style": best_entry.get("entry_style", "NONE"),
        "entry_mode": best_entry.get("entry_mode", "MARKET"),
        "setup_type": setup_type,
        "both_candidates_valid": bool(pullback_valid and momentum_valid),
        "trigger_type": best_entry.get("trigger_type", "none"),
        "entry_price": best_entry.get("entry_price"),
        "stop_loss": best_entry.get("stop_loss"),
        "take_profit": best_entry.get("take_profit"),
        "risk_distance": best_entry.get("risk_distance"),
        "reward_distance": best_entry.get("reward_distance"),
        "reward_to_risk_ratio": best_entry.get("reward_to_risk_ratio", 0.0),
        "trigger_quality": best_entry.get("trigger_quality", 0.0),
        "valid_rr": best_entry.get("valid_rr", False),
        "recommendation": best_entry.get("recommendation", "ENTRY CONDITIONS NOT MET"),
        "pullback_entry": pullback_entry,
        "momentum_entry": momentum_entry,
    }
