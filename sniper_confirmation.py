"""
SNIPER CONFIRMATION ENGINE v2 - Professional Grade
Features: RSI Crossover, Strong Candles, Liquidity Sweeps, Smart Money Entry
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils import log_debug

# ─────────────────────────────────────────────────────────────────────────────
# SNIPER THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

SNIPER_BUY_RSI_MIN = 40.0           # Minimum for BUY entry (RSI must cross over this)
SNIPER_BUY_RSI_MAX = 70.0           # Maximum (avoid overbought entry)
SNIPER_SELL_RSI_MAX = 60.0          # Maximum for SELL entry
SNIPER_SELL_RSI_MIN = 30.0          # Minimum (avoid oversold entry)

# Strong Candle Detection
STRONG_CANDLE_BODY_RATIO = 0.70     # Body must be 70%+ of full range
STRONG_CANDLE_VOLUME_MULT = 1.1     # Volume must exceed avg by 10%

# Liquidity Sweep Detection
SWEEP_ZONE_PIPS = 5.0               # How close price must come to key level
SWEEP_RECOVERY_PIPS = 3.0           # Minimum recovery from sweep


# ─────────────────────────────────────────────────────────────────────────────
# STATE STORAGE (Track previous M1 candles for crossover detection)
# ─────────────────────────────────────────────────────────────────────────────

SNIPER_STATE_FILE = Path("sniper_state.json")


def _load_sniper_state() -> dict[str, Any]:
    """Load previous M1 state for crossover detection."""
    if SNIPER_STATE_FILE.exists():
        try:
            return json.loads(SNIPER_STATE_FILE.read_text())
        except Exception as e:
            log_debug(f"Failed to load sniper state: {e}")
    return {
        "m1_rsi_prev": None,
        "m1_low_prev": None,
        "m1_high_prev": None,
        "m1_close_prev": None,
    }


def _save_sniper_state(
    m1_rsi: float | None,
    m1_low: float | None,
    m1_high: float | None,
    m1_close: float | None,
) -> None:
    """Save M1 state for next run's crossover detection."""
    state = {
        "m1_rsi_prev": m1_rsi,
        "m1_low_prev": m1_low,
        "m1_high_prev": m1_high,
        "m1_close_prev": m1_close,
    }
    try:
        SNIPER_STATE_FILE.write_text(json.dumps(state))
    except Exception as e:
        log_debug(f"Failed to save sniper state: {e}")


def _safe_float(value: Any) -> float | None:
    """Safely convert to float."""
    try:
        if value is None:
            return None
        num = float(value)
        return num if num == num else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR 1: RSI CROSSOVER (Not just level, but actual cross momentum)
# ─────────────────────────────────────────────────────────────────────────────


def detect_rsi_crossover(
    direction: str,
    m1_rsi: float | None,
    m1_rsi_prev: float | None,
) -> tuple[bool, str]:
    """
    Detect RSI crossover (not just level).

    BUY: Previous RSI < 40, current RSI > 40 (momentum cross upward)
    SELL: Previous RSI > 60, current RSI < 60 (momentum cross downward)
    """
    if m1_rsi is None or m1_rsi_prev is None:
        return False, f"Cannot detect crossover: current={m1_rsi}, prev={m1_rsi_prev}"

    if direction == "BUY":
        if m1_rsi_prev < SNIPER_BUY_RSI_MIN and m1_rsi > SNIPER_BUY_RSI_MIN:
            return (
                True,
                f"RSI CROSSOVER UP: {m1_rsi_prev:.1f} → {m1_rsi:.1f} (crossed {SNIPER_BUY_RSI_MIN})",
            )
        return False, f"No BUY crossover: prev={m1_rsi_prev:.1f}, curr={m1_rsi:.1f}"

    elif direction == "SELL":
        if m1_rsi_prev > SNIPER_SELL_RSI_MAX and m1_rsi < SNIPER_SELL_RSI_MAX:
            return (
                True,
                f"RSI CROSSOVER DOWN: {m1_rsi_prev:.1f} → {m1_rsi:.1f} (crossed {SNIPER_SELL_RSI_MAX})",
            )
        return False, f"No SELL crossover: prev={m1_rsi_prev:.1f}, curr={m1_rsi:.1f}"

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR 2: STRONG CANDLE (Momentum + Volume confirmation)
# ─────────────────────────────────────────────────────────────────────────────


def detect_strong_candle(
    direction: str,
    m1: dict[str, Any],
) -> tuple[bool, str]:
    """
    Strong candle = 70%+ of range is body + volume above average.
    Filters weak fake-out candles.
    """
    m1_high = _safe_float(m1.get("high")) or _safe_float(m1.get("atr_14"))  # Fallback
    m1_low = _safe_float(m1.get("low"))
    m1_close = _safe_float(m1.get("close"))
    m1_vol = _safe_float(m1.get("latest_volume"))
    m1_vol_avg = _safe_float(m1.get("average_volume_20"))

    if any(v is None for v in [m1_high, m1_low, m1_close, m1_vol, m1_vol_avg]):
        return False, "Incomplete M1 candle data"

    if m1_vol_avg == 0:
        return False, "Zero average volume"

    # For volume calculation, we need RSI momentum indicator
    m1_rsi = _safe_float(m1.get("rsi_14"))
    if m1_rsi is None:
        return False, "Missing M1 RSI"

    # Calculate candle momentum
    full_range = m1_high - m1_low
    if full_range <= 0:
        return False, "Zero or negative range"

    if direction == "BUY":
        # For BUY: RSI > 40 shows momentum, close near high shows strength
        rsi_ok = m1_rsi > SNIPER_BUY_RSI_MIN
        volume_ok = m1_vol is not None and m1_vol >= m1_vol_avg * STRONG_CANDLE_VOLUME_MULT
        body_height = m1_close - (m1_high - full_range * 0.3)  # Candle in upper 70%
        body_ok = body_height > 0

        is_strong = rsi_ok and volume_ok and body_ok

        if is_strong:
            return True, f"STRONG BUY CANDLE: RSI={m1_rsi:.1f}, vol={m1_vol/m1_vol_avg:.2f}x avg"
        return (
            False,
            f"Weak BUY candle: RSI_ok={rsi_ok} (need >{SNIPER_BUY_RSI_MIN}), vol_ratio={m1_vol/m1_vol_avg:.2f}x (need {STRONG_CANDLE_VOLUME_MULT}x)",
        )

    elif direction == "SELL":
        # For SELL: RSI < 60 shows momentum, close near low shows strength
        rsi_ok = m1_rsi < SNIPER_SELL_RSI_MAX
        volume_ok = m1_vol is not None and m1_vol >= m1_vol_avg * STRONG_CANDLE_VOLUME_MULT
        body_height = (m1_low + full_range * 0.3) - m1_close  # Candle in lower 70%
        body_ok = body_height > 0

        is_strong = rsi_ok and volume_ok and body_ok

        if is_strong:
            return True, f"STRONG SELL CANDLE: RSI={m1_rsi:.1f}, vol={m1_vol/m1_vol_avg:.2f}x avg"
        return (
            False,
            f"Weak SELL candle: RSI_ok={rsi_ok} (need <{SNIPER_SELL_RSI_MAX}), vol_ratio={m1_vol/m1_vol_avg:.2f}x (need {STRONG_CANDLE_VOLUME_MULT}x)",
        )

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR 3: LIQUIDITY SWEEP (Smart money entry - price touches then bounces)
# ─────────────────────────────────────────────────────────────────────────────


def detect_liquidity_sweep(
    direction: str,
    m1_high: float | None,
    m1_low: float | None,
    m1_high_prev: float | None,
    m1_low_prev: float | None,
    m1_close: float | None,
) -> tuple[bool, str]:
    """
    Liquidity sweep = price touched yesterday's low (BUY) or high (SELL),
    then recovered (smart money getting filled before reversal).
    """
    if any(v is None for v in [m1_high, m1_low, m1_close]):
        return False, "Incomplete liquidity data"

    if m1_high_prev is None or m1_low_prev is None:
        return False, "No previous candle data for sweep detection"

    if direction == "BUY":
        # Check if price swept yesterday's low
        swept_low = m1_low < (m1_low_prev + SWEEP_ZONE_PIPS)
        # Check if recovered
        recovered = m1_close > (m1_low + SWEEP_RECOVERY_PIPS)

        if swept_low and recovered:
            return (
                True,
                f"LIQUIDITY SWEEP: Low {m1_low:.2f} swept {m1_low_prev:.2f}, recovered to {m1_close:.2f}",
            )
        return (
            False,
            f"No sweep: low={m1_low:.2f}, prev_low={m1_low_prev:.2f}, close={m1_close:.2f}",
        )

    elif direction == "SELL":
        # Check if price swept yesterday's high
        swept_high = m1_high > (m1_high_prev - SWEEP_ZONE_PIPS)
        # Check if recovered downward
        recovered = m1_close < (m1_high - SWEEP_RECOVERY_PIPS)

        if swept_high and recovered:
            return (
                True,
                f"LIQUIDITY SWEEP: High {m1_high:.2f} swept {m1_high_prev:.2f}, recovered to {m1_close:.2f}",
            )
        return (
            False,
            f"No sweep: high={m1_high:.2f}, prev_high={m1_high_prev:.2f}, close={m1_close:.2f}",
        )

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR 4: PRICE RECLAIM (Confirmation of reversal)
# ─────────────────────────────────────────────────────────────────────────────


def detect_price_reclaim(
    direction: str,
    m1_close: float | None,
    m1_ema20: float | None,
    m1_ema50: float | None,
) -> tuple[bool, str]:
    """
    Price must reclaim EMA20 (key dynamic support/resistance).
    """
    if any(v is None for v in [m1_close, m1_ema20, m1_ema50]):
        return False, "Incomplete price data"

    if direction == "BUY":
        if m1_close > m1_ema20 and m1_ema20 > m1_ema50:
            return (
                True,
                f"BULLISH STRUCTURE: close {m1_close:.2f} > EMA20 {m1_ema20:.2f} > EMA50 {m1_ema50:.2f}",
            )
        return (
            False,
            f"No bullish structure: close={m1_close:.2f}, EMA20={m1_ema20:.2f}, EMA50={m1_ema50:.2f}",
        )

    elif direction == "SELL":
        if m1_close < m1_ema20 and m1_ema20 < m1_ema50:
            return (
                True,
                f"BEARISH STRUCTURE: close {m1_close:.2f} < EMA20 {m1_ema20:.2f} < EMA50 {m1_ema50:.2f}",
            )
        return (
            False,
            f"No bearish structure: close={m1_close:.2f}, EMA20={m1_ema20:.2f}, EMA50={m1_ema50:.2f}",
        )

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN: SNIPER CONFIRMATION
# ─────────────────────────────────────────────────────────────────────────────


def check_sniper_confirmation(
    setup_direction: str,
    current_signal: str,
    timeframe_indicators: dict[str, dict[str, Any]],
    gates: dict[str, Any],
) -> tuple[str, str, bool]:
    """
    MAIN SNIPER ENGINE

    Returns: (final_signal, sniper_reason, is_execution)

    Criteria for execution:
    1. ✅ RSI Crossover (momentum indication)
    2. ✅ Strong Candle (no weak fake-outs)
    3. ✅ Liquidity Sweep (smart money confirmation) - OPTIONAL
    4. ✅ Price Reclaim (structural confirmation)
    5. ✅ No critical blocks
    """

    if (
        current_signal != "WAIT_FOR_CONFIRMATION"
        or setup_direction not in {"BUY", "SELL"}
    ):
        return current_signal, "", False

    # Check if this is an M1-related wait
    wait_reason = gates.get("wait_reason", "").lower()
    is_m1_wait = (
        "m1" in wait_reason or "pullback" in wait_reason or "bounce" in wait_reason
    )

    if not is_m1_wait:
        return current_signal, "Not an M1 wait state", False

    # Load M1 data
    m1 = timeframe_indicators.get("M1", {})
    m1_rsi = _safe_float(m1.get("rsi_14"))
    m1_close = _safe_float(m1.get("close"))
    m1_ema20 = _safe_float(m1.get("ema_20"))
    m1_ema50 = _safe_float(m1.get("ema_50"))
    m1_high = _safe_float(m1.get("high"))
    m1_low = _safe_float(m1.get("low"))
    m1_vol = _safe_float(m1.get("latest_volume"))

    if m1_rsi is None or m1_close is None:
        return current_signal, "Incomplete M1 data", False

    # Load previous state for crossover detection
    prev_state = _load_sniper_state()
    m1_rsi_prev = prev_state.get("m1_rsi_prev")
    m1_low_prev = prev_state.get("m1_low_prev")
    m1_high_prev = prev_state.get("m1_high_prev")

    # Check gates (re-validate before executing)
    critical_blocks = (
        gates.get("higher_tf_conflict", False)
        or gates.get("rsi_exhausted", False)
        or gates.get("all_vol_low", False)
    )

    if critical_blocks:
        log_debug("Sniper: Critical gate blocked execution")
        return current_signal, "Critical gate blocked", False

    # ─────────────────────────────────────────────────────────────────────────
    # BUY CONFIRMATION
    # ─────────────────────────────────────────────────────────────────────────
    if setup_direction == "BUY":
        # Detector 1: RSI Crossover
        rsi_cross_ok, rsi_cross_reason = detect_rsi_crossover(
            "BUY", m1_rsi, m1_rsi_prev
        )

        # Detector 2: Strong Candle
        strong_candle_ok, strong_candle_reason = detect_strong_candle("BUY", m1)

        # Detector 3: Liquidity Sweep (optional but preferred)
        liquidity_ok, liquidity_reason = detect_liquidity_sweep(
            "BUY", m1_high, m1_low, m1_high_prev, m1_low_prev, m1_close
        )

        # Detector 4: Price Reclaim
        reclaim_ok, reclaim_reason = detect_price_reclaim(
            "BUY", m1_close, m1_ema20, m1_ema50
        )

        # Create detailed reason
        reasons = []
        if rsi_cross_ok:
            reasons.append(f"✓ {rsi_cross_reason}")
        else:
            reasons.append(f"✗ {rsi_cross_reason}")

        if strong_candle_ok:
            reasons.append(f"✓ {strong_candle_reason}")
        else:
            reasons.append(f"✗ {strong_candle_reason}")

        if liquidity_ok:
            reasons.append(f"✓ {liquidity_reason}")

        if reclaim_ok:
            reasons.append(f"✓ {reclaim_reason}")
        else:
            reasons.append(f"✗ {reclaim_reason}")

        full_reason = " | ".join(reasons)

        # Execute if core criteria met (RSI cross + Strong Candle + Price Reclaim)
        # Liquidity sweep is bonus but not required
        if rsi_cross_ok and strong_candle_ok and reclaim_ok:
            sniper_reason = f"🎯 BUY SNIPER CONFIRMED: {full_reason}"
            log_debug(sniper_reason)

            # Save state for next run
            _save_sniper_state(m1_rsi, m1_low, m1_high, m1_close)

            return "BUY", sniper_reason, True

        # Still waiting
        log_debug(f"BUY sniper waiting: {full_reason}")
        return (
            current_signal,
            f"Waiting for BUY confirmation: {full_reason}",
            False,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # SELL CONFIRMATION
    # ─────────────────────────────────────────────────────────────────────────
    if setup_direction == "SELL":
        # Detector 1: RSI Crossover
        rsi_cross_ok, rsi_cross_reason = detect_rsi_crossover(
            "SELL", m1_rsi, m1_rsi_prev
        )

        # Detector 2: Strong Candle
        strong_candle_ok, strong_candle_reason = detect_strong_candle("SELL", m1)

        # Detector 3: Liquidity Sweep
        liquidity_ok, liquidity_reason = detect_liquidity_sweep(
            "SELL", m1_high, m1_low, m1_high_prev, m1_low_prev, m1_close
        )

        # Detector 4: Price Reclaim
        reclaim_ok, reclaim_reason = detect_price_reclaim(
            "SELL", m1_close, m1_ema20, m1_ema50
        )

        # Create detailed reason
        reasons = []
        if rsi_cross_ok:
            reasons.append(f"✓ {rsi_cross_reason}")
        else:
            reasons.append(f"✗ {rsi_cross_reason}")

        if strong_candle_ok:
            reasons.append(f"✓ {strong_candle_reason}")
        else:
            reasons.append(f"✗ {strong_candle_reason}")

        if liquidity_ok:
            reasons.append(f"✓ {liquidity_reason}")

        if reclaim_ok:
            reasons.append(f"✓ {reclaim_reason}")
        else:
            reasons.append(f"✗ {reclaim_reason}")

        full_reason = " | ".join(reasons)

        # Execute if core criteria met
        if rsi_cross_ok and strong_candle_ok and reclaim_ok:
            sniper_reason = f"🎯 SELL SNIPER CONFIRMED: {full_reason}"
            log_debug(sniper_reason)

            # Save state for next run
            _save_sniper_state(m1_rsi, m1_low, m1_high, m1_close)

            return "SELL", sniper_reason, True

        # Still waiting
        log_debug(f"SELL sniper waiting: {full_reason}")
        return (
            current_signal,
            f"Waiting for SELL confirmation: {full_reason}",
            False,
        )

    return current_signal, "", False
