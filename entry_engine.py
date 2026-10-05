"""LAYER 8: M5/M1 ENTRY ENGINE - Regime-aware triggers."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import pandas as pd
from utils import log_debug
from risk_manager import get_current_session
from core.symbols import XAUUSD_2DIGIT as XAUUSD_SPEC
from core.units import Pips

from core.candles import closed_bars, last_closed_bar

try:
    from indicators import calculate_indicators, find_last_swing
except Exception:
    calculate_indicators = None
    find_last_swing = None

KILL_ZONES_UTC = ((8, 10), (12, 14))

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _frame_snapshot(frame: pd.DataFrame | None) -> dict[str, Any]:
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
    current = now or datetime.now(timezone.utc)
    hour = current.hour
    return any(start <= hour < end for start, end in KILL_ZONES_UTC)

# ============================================================
# REGIME DETECTION
# ============================================================

# U1 (PHASE_2_ISSUES.md). The stop buffer beyond a structural anchor.
#
# **The unit is now explicit. The VALUE is unchanged, deliberately.**
#
# `buffer_pips = 3.0` used to be subtracted directly from a price, so it placed
# a $3.00 buffer under a parameter named for pips. The obvious reading is that
# 3 pips ($0.30) was meant and the application was wrong by 10x. That reading
# was implemented, measured, and **rejected on evidence**:
#
#   * This repository never settled the question. `docs/BASELINE_005_PROVENANCE.md`
#     lists it as "U1 -- IS the $3.00 stop buffer intended as 3 pips?" and
#     `docs/BROKER_SYMBOL_SPECIFICATION_EVIDENCE.md` records it as UNRESOLVED.
#     The parameter's name is the only evidence for "pips", and a name is not a
#     specification.
#
#   * $0.30 is not a plausible stop buffer for gold. `execution/fills.py`
#     assumes a 2.0 pip spread, so a 3 pip buffer is about 1.5 round trips
#     through the spread -- a stop that the bid/ask alone can take out.
#
#   * Measured: at $0.30 the short integration fixture's stop sits $0.95 from
#     entry and is hit on the **next bar**, turning a TARGET_HIT into a
#     STOPPED. At $3.00 it survives to target. Noise, not structure, decided it.
#
# So the value kept is the one actually in use, expressed in the unit it is
# actually in: 30 pips = $3.00. This is NOT an endorsement of 3.0 as a tuned
# figure; it is a refusal to change stop placement on the authority of a
# variable name. Whether the right buffer is 30 pips, or ATR-relative, or
# something else, is a strategy question and is still **UNRESOLVED**.
#
# Typed so the unit can never again be ambiguous at the call site.
STOP_ANCHOR_BUFFER_PIPS = Pips(30.0)

# ----------------------------------------------------------------------
# REGIME VOLATILITY BANDS, in QUOTE CURRENCY (USD). Absolute, deliberately.
#
# This is U10 in PHASE_2_ISSUES.md, and the most consequential item in that
# register, because the regime selects RISK-PER-TRADE (0.75 / 1.0 / 1.5%).
#
# Unlike the rest of section 1 these bands are NOT mislabelled by a factor of
# ten -- read as dollars they produce a sensible spread of regimes. The defect
# is that they are ABSOLUTE, and it is measured and OPEN. Over thirteen months
# of M5 history, with no code change (research/UNIT_MIGRATION_EVIDENCE.md):
#
#                     2025 (mean $3,673)   2026 (mean $4,550)
#     DEAD_CALM             35.06%               0.47%
#     INTRADAY_SWING         4.56%              27.59%
#
# The share of bars in the highest-risk regime rose six-fold because gold got
# expensive. Nobody chose that.
#
# ### A price-scaled version was implemented, measured and REVERTED
#
# Scaling these edges by the prevailing price did reduce the drift as intended
# (DEAD_CALM spread 34.6pp -> 16.2pp, INTRADAY_SWING 23.0pp -> 1.7pp). It was
# reverted because of the end-to-end consequence, measured as
# baselines/baseline_010 against baseline_009 on identical data: signals went
# from 4 to ZERO, with 85.7% of 15,735 decisions dying at L1 or L2.
#
# The mechanism is worth recording. Gold's M5 ATR has a median of 0.1016% of
# price; the scaled MICRO_SCALP floor sits at 0.1619%, the 84th percentile. So
# ~85% of bars classify DEAD_CALM, and DEAD_CALM blocks at L2. There is a
# second, indirect effect: `use_fast_bias` below is true only for the scalp
# regimes, so reclassifying bars as DEAD_CALM also switches L1 from the H1 fast
# bias to the stricter H4 bias, which is why L1_BIAS blocks rose 1,505 -> 5,950.
#
# Expressed relatively, the inherited `2.5` edge sat at the 84th percentile of
# volatility at $1,544 gold and the 12th at $4,550. It was never one threshold,
# so there is no price-scaled form that preserves an intent these numbers never
# carried. Choosing a reference price that kept the strategy trading would have
# been selecting a threshold by its effect on output, which
# research/unit_migration_spec.md forbids.
#
# Fixing this properly means re-deriving the regimes from the volatility
# distribution rather than rescaling inherited constants. That is strategy
# design, not a correctness fix, and is not done here.
#
# Do not change these values to make the strategy trade more.
# ----------------------------------------------------------------------

def detect_regime(
    m5_data: pd.DataFrame | None,
    m15_data: pd.DataFrame | None,
    h1_data: pd.DataFrame | None,
    current_spread: float = 1.0,
) -> dict[str, Any]:
    try:
        m5_atr = _atr_from_frame(m5_data) or 0.0
        kill_zone = _within_kill_zone()
        session = get_current_session()
        h1_structure_valid = False
        if h1_data is not None and len(h1_data) >= 5:
            h1_snap = _frame_snapshot(h1_data)
            h1_structure_valid = bool(h1_snap.get("h1_structure_intact"))

        max_spread_pips = 10.0

        # D-6N-1: regime is a volatility classification, session is a separate
        # eligibility question. The session disjunct that used to sit here made
        # them one test, and its failure did not produce "not eligible" -- it fell
        # through to the else and produced DEAD_CALM, a *different volatility
        # claim*. Measured over the frozen dataset, 2,193 of DEAD_CALM's 2,312
        # decisions were band-B volatility in an ineligible session, so the label
        # was wrong for 94.85% of the regime.
        #
        # `architecture.txt` classifies every regime on "M5 ATR Cond." alone and
        # puts session eligibility at L0; the disjunct appears in no document.
        # This restores that separation and nothing else. Session and kill zone
        # remain computed, remain in the returned dict, and remain in the
        # reasoning string; MOMENTUM entries are still kill-zone gated, which is
        # what actually keeps out-of-session bars from triggering.
        #
        # See docs/PHASE_6N_REGIME_SESSION_CONTRACT_DECISION.md and
        # docs/D_6N_1_REGIME_SESSION_SEPARATION.md.
        if m5_atr >= 2.5 and m5_atr <= 4.5:
            regime = "MICRO_SCALP"
            risk = 0.75
            tp_ratio = 1.5
            bypass_l3 = True
            bypass_l6 = True
            poi_threshold = 50
            max_spread_pips = 5.0
            if kill_zone:
                reasoning = f"MICRO_SCALP: M5 ATR {m5_atr:.1f} + Kill Zone active → fast wick entries"
            else:
                reasoning = f"MICRO_SCALP: M5 ATR {m5_atr:.1f} in {session} session → fast wick entries"
        elif m5_atr >= 4.5 and m5_atr <= 7.0:
            regime = "REGIME_SCALP"
            risk = 1.0
            tp_ratio = 2.0
            bypass_l3 = False
            bypass_l6 = False
            poi_threshold = 60
            max_spread_pips = 7.0
            reasoning = f"REGIME_SCALP: M5 ATR {m5_atr:.1f} normal volatility → standard entries"
        else:
            if m5_atr > 7.0:
                regime = "INTRADAY_SWING"
                risk = 1.5
                tp_ratio = 3.0
                bypass_l3 = False
                bypass_l6 = False
                poi_threshold = 70
                max_spread_pips = 10.0
                reasoning = f"INTRADAY_SWING: M5 ATR {m5_atr:.1f} HIGH VOLATILITY → full validation"
            else:
                regime = "DEAD_CALM"
                risk = 0.75
                tp_ratio = 1.5
                bypass_l3 = False
                bypass_l6 = False
                poi_threshold = 70
                max_spread_pips = 5.0
                reasoning = f"DEAD_CALM: M5 ATR {m5_atr:.1f} too low → Will be BLOCKED at L2"

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

# ============================================================
# CANDLE DETECTION FUNCTIONS (unchanged)
# ============================================================

def detect_rejection_candle(m5_data: pd.DataFrame, direction: str) -> dict[str, Any]:
    try:
        if len(m5_data) < 3:
            return {"rejection_found": False, "wick_size": None, "body_size": None, "wick_ratio": None, "close_position": None, "rejection_quality": 0.0}
        # B1 (PHASE_2_ISSUES.md) -- **UNRESOLVED**. Reads the bar BEFORE the last
        # closed one, and that is left in place deliberately.
        #
        # The change to `last_closed_bar(m5_data)` was implemented and measured,
        # then reverted, because the evidence is genuinely two-sided and the
        # repo has a precedent for this exact situation (U1's stop buffer).
        #
        # FOR it being a defect:
        #   * the variable is named `current`, and this is not the current bar;
        #   * `get_market_data(closed_only=True)` drops MT5's forming bar on all
        #     three of its fetch paths, so `iloc[-1]` IS the last closed bar;
        #   * `detect_displacement_candle` in THIS module reads `iloc[-1]`, and
        #     the two are alternative entry confirmations evaluated on the same
        #     pass -- so they examine different bars for no stated reason;
        #   * `core/candles.py`, the canonical convention module, lists this site
        #     as "one bar stale".
        #
        # AGAINST:
        #   * BOTH integration fixtures are constructed with the rejection
        #     candle at `iloc[-2]` and the break at `iloc[-1]`, and
        #     `tests/fixtures/integration_market.TRIGGER_BARS` is commented
        #     "two M5 candles: rejection, then the break" -- a coherent entry
        #     pattern, and the only statement of INTENT anywhere;
        #   * changing it took both fixtures to zero signals, 60 of 64 test
        #     failures, because a rejection-then-break sequence stops existing.
        #
        # The fixtures are derived evidence -- they were written to satisfy the
        # code -- so they do not settle it. But nothing states the detector's
        # intended bar either, and U1 is the precedent for what happens when a
        # variable name is treated as a specification.
        #
        # Measured, so the cost of deciding later is known: reverting this alone
        # takes the suite from 64 failures to 4. A2-A4 and B2-B6 are unaffected
        # and shipped. Resolving B1 needs the two fixtures rebuilt to clear all
        # eight layers with the rejection candle last, which is a separate
        # measured pass -- see PHASE_2_ISSUES.md B1.
        current = m5_data.iloc[-2]
        c_open = _to_float(current["open"])
        c_close = _to_float(current["close"])
        c_high = _to_float(current["high"])
        c_low = _to_float(current["low"])
        if any(v is None for v in [c_open, c_close, c_high, c_low]):
            return {"rejection_found": False, "wick_size": None, "body_size": None, "wick_ratio": None, "close_position": None, "rejection_quality": 0.0}
        body = abs(c_close - c_open)
        range_size = c_high - c_low
        if range_size <= 0:
            return {"rejection_found": False, "wick_size": None, "body_size": None, "wick_ratio": None, "close_position": None, "rejection_quality": 0.0}
        close_pos = (c_close - c_low) / range_size
        if direction == "BUY":
            lower_wick = min(c_close, c_open) - c_low
            wick_ratio = lower_wick / body if body > 0 else 0
            if wick_ratio >= 2.0 and close_pos > 0.5:
                quality = min(10.0, (wick_ratio - 2.0) / 0.5 * 3.0 + 5.0)
                return {"rejection_found": True, "wick_size": lower_wick, "body_size": body, "wick_ratio": wick_ratio, "close_position": close_pos, "rejection_quality": quality}
        elif direction == "SELL":
            upper_wick = c_high - max(c_close, c_open)
            wick_ratio = upper_wick / body if body > 0 else 0
            if wick_ratio >= 2.0 and close_pos < 0.5:
                quality = min(10.0, (wick_ratio - 2.0) / 0.5 * 3.0 + 5.0)
                return {"rejection_found": True, "wick_size": upper_wick, "body_size": body, "wick_ratio": wick_ratio, "close_position": close_pos, "rejection_quality": quality}
        return {"rejection_found": False, "wick_size": None, "body_size": None, "wick_ratio": None, "close_position": None, "rejection_quality": 0.0}
    except Exception as exc:
        log_debug(f"Rejection candle detection error: {exc}")
        return {"rejection_found": False, "wick_size": None, "body_size": None, "wick_ratio": None, "close_position": None, "rejection_quality": 0.0}

def detect_momentum_confirmation(m5_data: pd.DataFrame, direction: str) -> dict[str, Any]:
    try:
        if len(m5_data) < 4:
            return {"momentum_confirmed": False, "volume_ratio": None, "rsi_direction": None, "momentum_quality": 0.0}
        # B2. `iloc[:-1]` dropped the last CLOSED bar, so `current_volume`
        # below was the volume of the bar before the current one. The frame is
        # already closed-only; use it as given.
        recent = closed_bars(m5_data).tail(3)
        baseline_volume = float(m5_data["tick_volume"].tail(20).mean()) if "tick_volume" in m5_data.columns else 0.0
        current_volume = _to_float(recent.iloc[-1].get("tick_volume", baseline_volume))
        volume_ratio = current_volume / baseline_volume if baseline_volume > 0 and current_volume is not None else 1.0
        # Deliberately NOT changed by B2. This one wants the RSI as of the
        # PREVIOUS bar, so that comparing it against `curr_rsi` below gives a
        # direction. Dropping the last bar is the intent here, not a bug.
        prev_rsi = _rsi_from_frame(m5_data.iloc[:-1].tail(6))
        curr_rsi = _rsi_from_frame(m5_data)
        rsi_direction = "neutral"
        if prev_rsi is not None and curr_rsi is not None:
            if curr_rsi > prev_rsi:
                rsi_direction = "up"
            elif curr_rsi < prev_rsi:
                rsi_direction = "down"
        momentum_confirmed = False
        quality = 0.0
        if direction == "BUY":
            if curr_rsi is not None and curr_rsi > 78:
                return {"momentum_confirmed": False, "volume_ratio": volume_ratio, "rsi_direction": rsi_direction, "momentum_quality": 0.0}
            if volume_ratio >= 1.2:
                quality += 3.0
            if rsi_direction in ["up", "neutral"] and curr_rsi is not None and curr_rsi < 72:
                quality += 2.0
            if curr_rsi is not None and 50 <= curr_rsi <= 72:
                momentum_confirmed = True
        else:
            if curr_rsi is not None and curr_rsi < 22:
                return {"momentum_confirmed": False, "volume_ratio": volume_ratio, "rsi_direction": rsi_direction, "momentum_quality": 0.0}
            if volume_ratio >= 1.2:
                quality += 3.0
            if rsi_direction in ["down", "neutral"] and curr_rsi is not None and curr_rsi > 28:
                quality += 2.0
            if curr_rsi is not None and 28 <= curr_rsi <= 50:
                momentum_confirmed = True
        return {"momentum_confirmed": momentum_confirmed, "volume_ratio": volume_ratio, "rsi_direction": rsi_direction, "momentum_quality": quality}
    except Exception as exc:
        log_debug(f"Momentum confirmation error: {exc}")
        return {"momentum_confirmed": False, "volume_ratio": None, "rsi_direction": None, "momentum_quality": 0.0}

def detect_displacement_candle(m5_data: pd.DataFrame, direction: str) -> dict[str, Any]:
    try:
        if m5_data is None or len(m5_data) < 3:
            return {"displacement_found": False, "body_to_atr": None, "close_position": None, "volume_ratio": None, "origin_low": None, "origin_high": None, "displacement_quality": 0.0}
        candle = m5_data.iloc[-1]
        c_open = _to_float(candle["open"])
        c_close = _to_float(candle["close"])
        c_high = _to_float(candle["high"])
        c_low = _to_float(candle["low"])
        atr = _atr_from_frame(m5_data)
        volume_ratio = _volume_ratio_from_frame(m5_data)
        if any(v is None for v in [c_open, c_close, c_high, c_low]):
            return {"displacement_found": False, "body_to_atr": None, "close_position": None, "volume_ratio": volume_ratio, "origin_low": None, "origin_high": None, "displacement_quality": 0.0}
        body = abs(c_close - c_open)
        range_size = c_high - c_low
        close_position = (c_close - c_low) / range_size if range_size > 0 else 0.5
        body_to_atr = body / atr if atr and atr > 0 else None
        if direction == "BUY":
            directional_ok = c_close > c_open and close_position >= 0.7
        else:
            directional_ok = c_close < c_open and close_position <= 0.3
        displacement_found = bool(directional_ok and ((body_to_atr is not None and body_to_atr >= 0.9) or (range_size > 0 and body / range_size >= 0.6)))
        quality = 0.0
        if displacement_found:
            if body_to_atr is not None:
                quality += min(5.0, body_to_atr * 3.0)
            if volume_ratio is not None:
                quality += min(3.0, max(0.0, volume_ratio - 1.0) * 2.0)
            quality += 2.0 if close_position >= 0.8 or close_position <= 0.2 else 1.0
        quality = min(10.0, quality)
        return {"displacement_found": displacement_found, "body_to_atr": body_to_atr, "close_position": close_position, "volume_ratio": volume_ratio, "origin_low": c_low, "origin_high": c_high, "displacement_quality": quality}
    except Exception as exc:
        log_debug(f"Displacement detection error: {exc}")
        return {"displacement_found": False, "body_to_atr": None, "close_position": None, "volume_ratio": None, "origin_low": None, "origin_high": None, "displacement_quality": 0.0}

def detect_fvg(m5_data: pd.DataFrame, direction: str) -> dict[str, Any]:
    try:
        if m5_data is None or len(m5_data) < 3:
            return {"fvg_found": False, "zone_low": None, "zone_high": None, "midpoint": None, "fvg_size": None, "fvg_quality": 0.0}
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
            return {"fvg_found": False, "zone_low": None, "zone_high": None, "midpoint": None, "fvg_size": None, "fvg_quality": 0.0}
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
            return {"fvg_found": False, "zone_low": gap_low, "zone_high": gap_high, "midpoint": None, "fvg_size": None, "fvg_quality": 0.0}
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
        return {"fvg_found": True, "zone_low": gap_low, "zone_high": gap_high, "midpoint": midpoint, "fvg_size": fvg_size, "fvg_quality": quality}
    except Exception as exc:
        log_debug(f"FVG detection error: {exc}")
        return {"fvg_found": False, "zone_low": None, "zone_high": None, "midpoint": None, "fvg_size": None, "fvg_quality": 0.0}

def detect_m1_choch(m1_data: pd.DataFrame, direction: str) -> dict[str, Any]:
    try:
        if m1_data is None or len(m1_data) < 6:
            return {"m1_choch_confirmed": False, "choch_level": None, "m1_quality": 0.0}
        closed = m1_data.tail(6)
        signal_candle = closed.iloc[-1]
        current_high = _to_float(signal_candle["high"])
        current_low = _to_float(signal_candle["low"])
        current_close = _to_float(signal_candle["close"])
        current_open = _to_float(signal_candle["open"])
        if any(v is None for v in [current_high, current_low, current_close, current_open]):
            return {"m1_choch_confirmed": False, "choch_level": None, "m1_quality": 0.0}
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
                return {"m1_choch_confirmed": True, "choch_level": current_close, "m1_quality": min(10.0, quality)}
        else:
            swing_break = min(prev_lows)
            buffer = (atr * 0.05) if atr else 0.0
            candle_strength = current_close < current_open and current_close < current_low + ((current_high - current_low) * 0.35)
            if current_close < swing_break - buffer and candle_strength:
                quality = 4.0
                if atr and atr > 0:
                    quality += min(3.0, (swing_break - current_close) / atr * 3.0)
                if volume_ratio is not None and volume_ratio >= 1.1:
                    quality += 2.0
                return {"m1_choch_confirmed": True, "choch_level": current_close, "m1_quality": min(10.0, quality)}
        return {"m1_choch_confirmed": False, "choch_level": None, "m1_quality": 0.0}
    except Exception as exc:
        log_debug(f"M1 CHoCH detection error: {exc}")
        return {"m1_choch_confirmed": False, "choch_level": None, "m1_quality": 0.0}

# ============================================================
# ENTRY LEVEL CALCULATION (with tp_ratio)
# ============================================================

def _select_stop_anchor(
    direction: str,
    entry_price: float,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    buffer_pips: float | None = None,
) -> float | None:
    """Most defensive structural stop candidate that is valid against the entry.

    ``entry_price`` is required. Selecting by extremeness alone could return a
    candidate already on the wrong side of the entry -- under a midpoint MOMENTUM
    entry the displacement origin is the *near* FVG edge and is wrong-side by
    construction -- leaving the fixed buffer to rescue the geometry or not.

    A candidate is eligible only when **strictly** on the protective side:
    ``candidate < entry_price`` for BUY, ``candidate > entry_price`` for SELL.
    Among eligible candidates the original most-defensive ordering is preserved.
    When none is eligible this returns ``None`` and the caller's existing
    entry-relative ATR fallback applies, unchanged. The buffer is unchanged and
    is still applied exactly as before.

    Consequence, relied on by the zero-risk annotation in
    ``calculate_entry_levels``: an eligible candidate is strictly beyond the
    entry, so ``risk_distance`` on this path is ``|entry - candidate| +
    buffer``, hence strictly greater than the buffer.

    Args:
        buffer_pips: Buffer beyond the anchor, in **price units**. ``None`` uses
            ``STOP_ANCHOR_BUFFER_PIPS`` converted through the instrument
            specification -- $0.30, which is the 3 pips the parameter name has
            always claimed. It previously defaulted to the bare float ``3.0``
            and was subtracted straight from a price, giving a **$3.00** buffer:
            ten times the intended distance (U1, P0).
    """
    buffer = (
        STOP_ANCHOR_BUFFER_PIPS.to_price(XAUUSD_SPEC).value
        if buffer_pips is None else float(buffer_pips)
    )
    if direction == "BUY":
        candidates = [
            v for v in [sweep_wick_low, structure_low]
            if v is not None and v < entry_price
        ]
        if candidates:
            return min(candidates) - buffer
    else:
        candidates = [
            v for v in [sweep_wick_high, structure_high]
            if v is not None and v > entry_price
        ]
        if candidates:
            return max(candidates) + buffer
    return None

def calculate_entry_levels(
    entry_price: float,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    direction: str = "BUY",
    m5_atr: float | None = None,
    risk_pct: float = 1.5,
    tp_ratio: float = 3.0,
    entry_style: str = "PULLBACK",
) -> dict[str, Any]:
    try:
        stop_anchor = _select_stop_anchor(
            direction,
            entry_price,
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

        risk_distance = abs(entry_price - stop_loss)
        if direction == "BUY":
            take_profit = entry_price + (risk_distance * tp_ratio)
        else:
            take_profit = entry_price - (risk_distance * tp_ratio)

        # U4: the reward distance IS the quantity take_profit was built from,
        # two lines above. Recovering it as |take_profit - entry_price| adds a
        # small number to a large one and subtracts the large one back, which
        # discards the addend's low bits in proportion to
        # entry_price / (risk_distance * tp_ratio) -- about 1.7e-13 on gold.
        # That error was the same order as the distance between rr and two of
        # the four regime thresholds, so it decided admissions.
        # See docs/PHASE_6K_F_U4_REPAIR.md.
        reward_distance = risk_distance * tp_ratio
        # rr is reported here, never judged. take_profit is constructed from
        # risk_distance * tp_ratio, so rr IS tp_ratio; the per-candidate gate
        # that compared it to a constant is retired (docs/VALID_RR_CONTRACT.md).
        # The surviving regime gate still compares it -- that is U2/U9, untouched.
        # DEFENCE IN DEPTH, UNREACHABLE BY CONSTRUCTION. The `else 0` branch
        # needs risk_distance == 0, i.e. stop_loss == entry_price. Since
        # _select_stop_anchor became entry-aware, neither path can produce that:
        # an eligible candidate is strictly beyond the entry, so the anchor path
        # gives risk > buffer_pips; the ATR fallback gives risk >= 6.0. Before
        # that change it was reachable only when a candidate sat exactly
        # buffer_pips on the wrong side of the entry -- measured 0 times in
        # 15,735 decisions, smallest observed risk 0.555.
        # Retained deliberately, not deleted: it is the guard that keeps this
        # division safe if the anchor invariant is ever relaxed, and the same
        # state is independently refused downstream by
        # PendingOrderIntent.__post_init__ and PaperBroker.open_position.
        rr = reward_distance / risk_distance if risk_distance > 0 else 0
        reasoning = f"Entry {entry_price:.2f} | SL {stop_loss:.2f} ({risk_distance:.1f}p risk) | TP {take_profit:.2f} ({reward_distance:.1f}p reward) | RR {rr:.1f}:1"
        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "reward_to_risk_ratio": rr,
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
            "reasoning": f"Error: {str(exc)}",
        }

# ============================================================
# SCORE HELPER
# ============================================================

def _score_entry_candidate(candidate: dict[str, Any]) -> float:
    if not candidate.get("raw_triggered"):
        return -1.0
    quality = float(candidate.get("trigger_quality", 0.0) or 0.0)
    rr = float(candidate.get("reward_to_risk_ratio", 0.0) or 0.0)
    style_bonus = 0.5 if candidate.get("entry_style") == "PULLBACK" else 0.0
    rr_bonus = min(rr, 4.0) * 1.5
    return (quality * 2.0) + rr_bonus + style_bonus

# ============================================================
# ENTRY EVALUATION FUNCTIONS (with tp_ratio)
# ============================================================

def _entry_level_context(
    entry_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    structure_low: float | None = None,
    structure_high: float | None = None,
    m5_atr: float | None = None,
    entry_style: str = "PULLBACK",
    tp_ratio: float = 3.0,
) -> dict[str, Any]:
    entry_levels = calculate_entry_levels(
        entry_price,
        sweep_wick_low=sweep_wick_low,
        sweep_wick_high=sweep_wick_high,
        structure_low=structure_low,
        structure_high=structure_high,
        direction=direction,
        m5_atr=m5_atr,
        tp_ratio=tp_ratio,
        entry_style=entry_style,
    )
    entry_levels["entry_price"] = entry_price
    return entry_levels

def _evaluate_pullback_entry(
    m5_data: pd.DataFrame,
    m1_data: pd.DataFrame,
    current_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    tp_ratio: float = 3.0,
) -> dict[str, Any]:
    rejection = detect_rejection_candle(m5_data, direction)
    momentum = detect_momentum_confirmation(m5_data, direction)
    m1_choch = detect_m1_choch(m1_data, direction)
    m5_snapshot = _frame_snapshot(m5_data)

    confirmed_m5_price = current_price
    if m5_data is not None and len(m5_data) >= 2:
        # B3 (P0). This priced the entry off `iloc[-2]` -- a bar that closed
        # five minutes ago -- while a MOMENTUM entry on the same pass used the
        # current one. On a strategy targeting 15-25 pip moves that is a
        # material difference in entry price between two paths that are supposed
        # to be alternatives.
        confirmed_m5_price = _to_float(last_closed_bar(m5_data)["close"]) or current_price

    confirmed_entry_price = confirmed_m5_price
    if m1_data is not None and len(m1_data) >= 2 and m1_choch["m1_choch_confirmed"]:
        # B3, M1 leg: two minutes stale for the same reason.
        confirmed_entry_price = _to_float(last_closed_bar(m1_data)["close"]) or confirmed_m5_price

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
        tp_ratio=tp_ratio,
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
        "entry_triggered": bool(raw_triggered),
        "trigger_type": trigger_type,
        "entry_price": entry_levels["entry_price"],
        "stop_loss": entry_levels["stop_loss"],
        "take_profit": entry_levels["take_profit"],
        "risk_distance": entry_levels["risk_distance"],
        "reward_distance": entry_levels["reward_distance"],
        "reward_to_risk_ratio": entry_levels["reward_to_risk_ratio"],
        "trigger_quality": quality,
        "recommendation": (
            f"PULLBACK ENTRY READY (RR {entry_levels['reward_to_risk_ratio']:.1f}:1)"
            if raw_triggered
            else "PULLBACK CONDITIONS NOT MET"
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
    tp_ratio: float = 3.0,
) -> dict[str, Any]:
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
    # STRATEGY-SEMANTIC CHANGE (Phase 4A, Step 4). The CHoCH override that
    # replaced this price with m1[-1].close is removed from the LIMIT_FVG path.
    # That value is the close of the candle that BROKE the swing -- a breakout
    # price -- and measurement found it outside the gap on 13 of 13 occurrences,
    # always on the far side (BUY above, SELL below). A limit cannot rest there.
    # This changes entry prices and therefore outcomes; it is not a bug fix.
    # The pullback path keeps its own, separate m1[-2] override, untouched.
    # See docs/PHASE_4A_STEP4_DECISION_EVIDENCE.md section C.

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
        tp_ratio=tp_ratio,
    )

    # price_in_fvg is deliberately NOT a term here. Under a resting-limit design
    # it has no purpose at signal time: asserting price is already in the zone
    # contradicts the reason for resting an order, and asserting the zone is
    # unfilled is vacuous for a gap formed on the last three bars. It is still
    # computed and returned as a diagnostic. See the momentum entry spec.
    core_trigger = bool(
        kill_zone
        and displacement.get("displacement_found")
        and fvg.get("fvg_found")
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
        "entry_triggered": bool(core_trigger),
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
        "recommendation": (
            f"MOMENTUM FVG LIMIT READY (RR {entry_levels['reward_to_risk_ratio']:.1f}:1)"
            if core_trigger
            else "MOMENTUM CONDITIONS NOT MET"
        ),
        "momentum": momentum,
        "m1_choch": m1_choch,
        "rejection": rejection,
        "displacement": displacement,
        "fvg": fvg,
        "kill_zone": kill_zone,
        "price_in_fvg": price_in_fvg,
        # Carried so the execution layer can build a pending-order intent
        # without reaching back into the strategy.
        "limit_price": confirmed_entry_price,
        "fvg_zone_low": fvg.get("zone_low") if fvg.get("fvg_found") else None,
        "fvg_zone_high": fvg.get("zone_high") if fvg.get("fvg_found") else None,
    }

# ============================================================
# MAIN ENTRY TRIGGER (Regime-aware)
# ============================================================

def get_entry_trigger(
    m5_data: pd.DataFrame,
    m1_data: pd.DataFrame,
    current_price: float,
    direction: str,
    sweep_wick_low: float | None = None,
    sweep_wick_high: float | None = None,
    regime: dict | None = None,
    regime_tp_ratio: float = 3.0,
) -> dict[str, Any]:
    # Determine which entry styles are allowed for this regime
    allowed_styles = ["PULLBACK", "MOMENTUM"]
    if regime:
        reg_name = regime.get("regime", "DEFAULT")
        if reg_name == "MICRO_SCALP":
            allowed_styles = ["MOMENTUM"]
        elif reg_name == "INTRADAY_SWING":
            allowed_styles = ["PULLBACK"]

    pullback_entry = _evaluate_pullback_entry(
        m5_data, m1_data, current_price, direction,
        sweep_wick_low, sweep_wick_high,
        tp_ratio=regime_tp_ratio
    )
    momentum_entry = _evaluate_momentum_entry(
        m5_data, m1_data, current_price, direction,
        sweep_wick_low, sweep_wick_high,
        tp_ratio=regime_tp_ratio
    )

    candidates = []
    if "PULLBACK" in allowed_styles:
        candidates.append(pullback_entry)
    if "MOMENTUM" in allowed_styles:
        candidates.append(momentum_entry)

    valid_candidates = [c for c in candidates if c.get("entry_triggered")]
    if valid_candidates:
        best_entry = max(valid_candidates, key=_score_entry_candidate)
    else:
        best_raw = max(candidates, key=_score_entry_candidate) if candidates else pullback_entry
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
        "limit_price": best_entry.get("limit_price"),
        "fvg_zone_low": best_entry.get("fvg_zone_low"),
        "fvg_zone_high": best_entry.get("fvg_zone_high"),
        "recommendation": best_entry.get("recommendation", "ENTRY CONDITIONS NOT MET"),
        "pullback_entry": pullback_entry,
        "momentum_entry": momentum_entry,
    }

# ============================================================
# ENTRY GATE FOR REGIME
# ============================================================

def evaluate_entry_for_regime(entry: dict[str, Any], regime: dict[str, Any] | None = None) -> dict[str, Any]:
    regime_name = (regime or {}).get("regime", "DEFAULT")
    spread_ok = True

    if not spread_ok:
        return {
            "entry_allowed": False,
            "recommended_mode": "WAIT",
            "reason": "spread too wide for current regime",
            "regime": regime_name,
        }

    trigger_quality = float(entry.get("trigger_quality", 0.0) or 0.0)
    rr = float(entry.get("reward_to_risk_ratio", 0.0) or 0.0)
    entry_triggered = bool(entry.get("entry_triggered", False))

    if not entry_triggered:
        return {
            "entry_allowed": False,
            "recommended_mode": "WAIT",
            "reason": "entry trigger not confirmed",
            "regime": regime_name,
        }

    if regime_name == "MICRO_SCALP":
        entry_allowed = trigger_quality >= 5.0 and rr >= 1.5
        return {
            "entry_allowed": entry_allowed,
            "recommended_mode": "SCALP",
            "reason": "micro scalp entry allowed" if entry_allowed else f"micro scalp quality too low (quality={trigger_quality:.1f}, rr={rr:.1f})",
            "regime": regime_name,
            "quality": trigger_quality,
            "rr": rr,
        }

    if regime_name == "REGIME_SCALP":
        entry_allowed = trigger_quality >= 6.0 and rr >= 2.0
        return {
            "entry_allowed": entry_allowed,
            "recommended_mode": "SCALP",
            "reason": "regime scalp entry allowed" if entry_allowed else f"regime scalp quality too low (quality={trigger_quality:.1f}, rr={rr:.1f})",
            "regime": regime_name,
            "quality": trigger_quality,
            "rr": rr,
        }

    if regime_name == "INTRADAY_SWING":
        entry_allowed = trigger_quality >= 7.0 and rr >= 2.5
        return {
            "entry_allowed": entry_allowed,
            "recommended_mode": "INTRADAY",
            "reason": "intraday entry allowed" if entry_allowed else f"intraday quality too low (quality={trigger_quality:.1f}, rr={rr:.1f})",
            "regime": regime_name,
            "quality": trigger_quality,
            "rr": rr,
        }

    entry_allowed = trigger_quality >= 5.0 and rr >= 2.0
    return {
        "entry_allowed": entry_allowed,
        "recommended_mode": "WAIT" if not entry_allowed else "SCALP",
        "reason": "default entry gate",
        "regime": regime_name,
        "quality": trigger_quality,
        "rr": rr,
    }