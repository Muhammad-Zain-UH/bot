"""Main orchestrator — continuous monitoring loop with 3 staged gates.

New architecture:
  WHILE TRUE:
    STAGE 1 (cheap) → If gate 1 fails, sleep and continue
    STAGE 2 (intermarket) → If gate 2 fails (hard blocks), sleep and continue
    STAGE 3 (expensive) → If gate 3 fails, sleep and continue
    EXECUTION → Place trade if all gates pass

All expensive API calls (news, AI) only fire after cheap gates pass.
Bot runs forever until stopped with Ctrl+C.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import config
import stage1
import stage2
import stage3
from confidence_calibrator import is_calibration_complete, get_calibration_progress, format_calibration_status
from indicators import calculate_indicators
from key_levels import build_pivot_context
from mt5_handler import connect_mt5, get_market_data, shutdown_mt5
from risk_manager import (
    get_current_session,
    get_daily_pnl_pct,
    get_session_score_threshold,
    is_daily_loss_limit_hit,
    is_good_trading_session,
    is_market_open,
    get_calibration_micro_lot,
)
from signal_logger import log_signal
from utils import log_debug, log_monitor
from utils.display import (
    format_cooldown,
    format_error,
    format_execute_header,
    format_hard_block,
    format_monitor_status_line,
)
from utils.result_writer import write_result_txt, write_signal_expired
from utils.sleep import calculate_sleep_time
import MetaTrader5 as mt5



# Global control flag for graceful shutdown
_SHOULD_CONTINUE = True

# Track result.txt state to avoid duplicate writes
_LAST_WRITTEN_CONF = 0
_LAST_WRITTEN_DIRECTION = None
_RESULT_TXT_ACTIVE = False
_RESULT_TXT_WRITE_TIME = 0  # Unix timestamp when result.txt was last written

# Intermarket hard block streak tracking (for BLOCK D)
_INTERMARKET_BLOCK_STREAK = 0
_INTERMARKET_BLOCK_STREAK_CYCLES = []  # Track which cycles had blocks

# H1 EMA Strength Recovery Tracker (early warning for trend flips)
_H1_EMA_HISTORY = []  # Rolling list of last 20 H1 EMA strength values
_H1_NEGATIVE_STREAK = 0  # Count of consecutive negative H1 EMA strength values
_H1_RECOVERY_WATCH = False  # True when EMA trending toward zero
_H1_RECOVERY_TRIGGERED_AT = None  # EMA strength value when recovery watch triggered
_H1_RECOVERY_TRIGGERED_CYCLE = None  # Loop count when triggered

# H4 EMA Strength Recovery Tracker (same logic as H1)
_H4_EMA_HISTORY = []  # Rolling list of last 20 H4 EMA strength values
_H4_NEGATIVE_STREAK = 0  # Count of consecutive negative H4 EMA strength values
_H4_RECOVERY_WATCH = False  # True when EMA trending toward zero
_H4_RECOVERY_TRIGGERED_AT = None  # EMA strength value when recovery watch triggered
_H4_RECOVERY_TRIGGERED_CYCLE = None  # Loop count when triggered

# M1 RSI Recovery Bounce Tracking
_PREV_M1_RSI = None  # Previous cycle's M1 RSI value
_RSI_BOUNCE_DETECTED = False  # True when M1 bounces from oversold
_PREV_CYCLE_SCORE = None  # Previous cycle's score to detect collapse

# Intermarket and session tracking
_LAST_INTERMARKET_SCORE = None  # Track last score to detect changes
_LAST_SESSION = None  # Track session to reset streak on session change

# Calibration mode tracking (for detecting exit from calibration)
_PREV_CALIBRATION_COUNT = None  # Previous cycle's completed trade count
_CALIBRATION_MODE_EXITED = False  # True once we transition from <50 to >=50 trades


def _signal_handler(signum: int, frame: Any) -> None:
    """Handle Ctrl+C gracefully."""
    global _SHOULD_CONTINUE
    _SHOULD_CONTINUE = False
    log_debug("\n[SHUTDOWN] Ctrl+C detected — stopping monitoring loop...")
    print("\n[SHUTDOWN] Ctrl+C detected — stopping monitoring loop...")


def _safe_print(text: str) -> None:
    """Print text with encoding error handling."""
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = text.encode('ascii', errors='replace').decode('ascii')
        print(safe_text)


def _validate_config_and_session() -> tuple[bool, str]:
    """Validate configuration and check if market is open.
    
    Returns:
        (is_valid, reason_if_invalid)
    """
    # Validate config
    try:
        config.validate_config()
    except ValueError as exc:
        return False, f"Config error: {exc}"
    
    # Check if market is open
    if not is_market_open():
        return False, "Market is closed (weekend). Gold opens Sunday 22:00 UTC."
    
    # Check session suitability
    good_session, session = is_good_trading_session()
    if not good_session:
        return False, f"Session {session} not suitable for XAUUSD day trading."
    
    return True, ""


def _check_daily_loss_limit() -> tuple[bool, str]:
    """Check if daily loss limit is hit.
    
    Returns:
        (is_hit, reason)
    """
    loss_hit, daily_pnl = is_daily_loss_limit_hit()
    if loss_hit:
        return True, f"Daily loss limit reached ({daily_pnl:.2f}%)"
    return False, ""


def main_loop() -> None:
    """Main continuous monitoring loop with three-stage gates.
    
    Runs forever until stopped by user (Ctrl+C) or market closure.
    """
    global _SHOULD_CONTINUE, _LAST_WRITTEN_CONF, _LAST_WRITTEN_DIRECTION, _RESULT_TXT_ACTIVE
    global _INTERMARKET_BLOCK_STREAK, _INTERMARKET_BLOCK_STREAK_CYCLES, _LAST_INTERMARKET_SCORE, _LAST_SESSION
    global _H1_EMA_HISTORY, _H1_NEGATIVE_STREAK, _H1_RECOVERY_WATCH, _H1_RECOVERY_TRIGGERED_AT, _H1_RECOVERY_TRIGGERED_CYCLE
    global _H4_EMA_HISTORY, _H4_NEGATIVE_STREAK, _H4_RECOVERY_WATCH, _H4_RECOVERY_TRIGGERED_AT, _H4_RECOVERY_TRIGGERED_CYCLE
    global _PREV_M1_RSI, _RSI_BOUNCE_DETECTED, _PREV_CYCLE_SCORE
    global _PREV_CALIBRATION_COUNT, _CALIBRATION_MODE_EXITED
    
    # Install signal handler for graceful Ctrl+C
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    
    log_debug("="*70)
    log_debug("Starting XAUUSD trading bot — continuous monitoring mode")
    log_debug("="*70)
    
    # Pre-loop validation
    valid, reason = _validate_config_and_session()
    if not valid:
        _safe_print(reason)
        return
    
    loss_hit, reason = _check_daily_loss_limit()
    if loss_hit:
        _safe_print(reason)
        return
    
    # Connect to MT5
    if not connect_mt5():
        _safe_print("Unable to connect to MetaTrader 5.")
        return
    
    log_debug("MT5 connection established. Starting monitoring loop...")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # TEST DXY AVAILABILITY AT TRUE SYSTEM STARTUP (BUG FIX 3)
    # ─────────────────────────────────────────────────────────────────────────────
    from intermarket import test_dxy_availability_at_startup
    test_dxy_availability_at_startup()
    log_debug("[INIT] System initialization complete — DXY availability tested")
    
    loop_count = 0
    _PREV_CALIBRATION_COUNT = None  # Initialize for exit detection
    
    try:
        while _SHOULD_CONTINUE:
            loop_count += 1
            now = datetime.now(timezone.utc)
            
            # Periodic re-checks of market status
            if loop_count % 10 == 0:  # Every 10 iterations (~1 min if 6s loops)
                if not is_market_open():
                    log_debug("Market has closed — exiting")
                    _safe_print("Market closed. Exiting.")
                    break
                
                loss_hit, _ = _check_daily_loss_limit()
                if loss_hit:
                    log_debug("Daily loss limit hit — exiting")
                    _safe_print("Daily loss limit reached. Exiting.")
                    break
            
            session = get_current_session()
            
            # Reset intermarket streak if session changed
            if _LAST_SESSION is not None and _LAST_SESSION != session:
                log_debug(f"[STREAK] Session changed from {_LAST_SESSION} to {session} — resetting intermarket block streak")
                _INTERMARKET_BLOCK_STREAK = 0
                _LAST_INTERMARKET_SCORE = None
                # Also reset EMA recovery watches on session change
                _H1_RECOVERY_WATCH = False
                _H1_NEGATIVE_STREAK = 0
                _H1_EMA_HISTORY.clear()
                _H4_RECOVERY_WATCH = False
                _H4_NEGATIVE_STREAK = 0
                _H4_EMA_HISTORY.clear()
            
            _LAST_SESSION = session
            
            # ────────────────────────────────────────────────────────────
            # FIX 6: CALIBRATION MODE THRESHOLDS + MILESTONE TRACKING
            # ────────────────────────────────────────────────────────────
            is_calibrated, completed_trades = is_calibration_complete()
            
            # Check for calibration mode exit (transition from <50 to >=50 trades)
            if _PREV_CALIBRATION_COUNT is not None and _PREV_CALIBRATION_COUNT < 50 and completed_trades >= 50 and not _CALIBRATION_MODE_EXITED:
                _CALIBRATION_MODE_EXITED = True
                log_debug("")
                log_debug("╔════════════════════════════════════════════════════════════════╗")
                log_debug(f"║ 🎯 CALIBRATION COMPLETE: {completed_trades} trades accumulated      ║")
                log_debug("║ ✅ Confidence model activated                                  ║")
                log_debug("║ 📊 Switching to production thresholds (score 4.5+)             ║")
                log_debug("║ 🚀 Full-size positions now enabled                             ║")
                log_debug("╚════════════════════════════════════════════════════════════════╝")
                log_debug("")
            
            # Get calibration progress for logging
            cal_progress_count, milestone_msg, is_milestone = get_calibration_progress()
            
            # Log milestone messages on first detection
            if is_milestone and _PREV_CALIBRATION_COUNT != completed_trades:
                log_debug(f"[CALIBRATION MILESTONE] {milestone_msg}")
            
            cal_mode_label = ""
            
            if completed_trades < 50:
                # CALIBRATION MODE: Relaxed thresholds to accumulate first 50 trades
                cal_mode_label = f"[CAL MODE {completed_trades}/50]"
                
                # Reduce score threshold from 3.60 (London) to 3.00 for calibration
                if session == "London":
                    session_threshold = 3.00
                else:
                    session_threshold = get_session_score_threshold(3.00)  # 3.00 base for calibration
                
                log_debug(
                    f"{cal_mode_label} Using relaxed thresholds to accumulate calibration data — "
                    f"score threshold: 3.00 | lot size: micro (0.01 only) — {milestone_msg}"
                )
            else:
                # PRODUCTION MODE: Full thresholds
                session_threshold = get_session_score_threshold(4.5)
                if completed_trades == 50:
                    log_debug(f"[CALIBRATION COMPLETE] Switching to full production thresholds")
            
            daily_pnl = get_daily_pnl_pct()
            
            # Session summary header at cycle start
            try:
                current_price = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 1).iloc[-1]["close"]
                m15_indicators = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M15, 20)
                m15_atr = calculate_indicators(m15_indicators).get("atr_14", "?")
                atr_display = f"{m15_atr:.2f}" if isinstance(m15_atr, (int, float)) else str(m15_atr)
            except Exception:
                current_price = "?"
                atr_display = "?"
            
            log_debug("═" * 70)
            log_debug(f"[CYCLE {now.strftime('%H:%M:%S')}] Session: {session} | {config.SYMBOL}: {current_price} | ATR: {atr_display}")
            log_debug("═" * 70)
            
            try:
                # ────────────────────────────────────────────────────────────
                # STAGE 1: CHEAP SCAN (always runs)
                # ────────────────────────────────────────────────────────────
                stage1_result = stage1.run_stage1(
                    config.SYMBOL,
                    config.N_CANDLES,
                    high_impact_news=False,  # TODO: track from previous run
                )
                
                if stage1_result.get("error"):
                    sleep_time = calculate_sleep_time(stage="hard_block")
                    msg = format_error(
                        "MT5 Error",
                        stage1_result["error"],
                        sleep_time
                    )
                    log_debug(msg)
                    time.sleep(sleep_time)
                    continue
                
                trade_signal = stage1_result["technical_signal"]
                confidence = stage1_result["confidence"]
                confidence_display = stage1_result.get("confidence_display", f"{confidence}%")
                score = stage1_result["score"]
                max_score = stage1_result["max_score"]
                direction = stage1_result["setup_direction"]
                indicators = stage1_result["indicators"]
                trade_levels = stage1_result["trade_levels"]
                risk_level = stage1_result["risk_level"]
                
                # ────────────────────────────────────────────────────────────
                # FIX 5: ALL TIMEFRAMES LOW VOLUME CHECK
                # ────────────────────────────────────────────────────────────
                low_volume_timeframes = []
                for timeframe in ["H4", "H1", "M15", "M5", "M1"]:
                    tf_ind = indicators.get(timeframe, {})
                    vol_class = tf_ind.get("volume_classification", "Unknown")
                    if vol_class == "Low":
                        low_volume_timeframes.append(timeframe)
                
                if len(low_volume_timeframes) == 5:
                    # Score-aware SESSION HOLD override — strong signals override volume hold
                    score_strength = abs(score)
                    
                    if score_strength >= 8.0:
                        # Very strong signal — volume hold reduced to warning only
                        log_debug(
                            f"[VOLUME CAUTION] All 5 timeframes Low volume but score={score_strength:.2f} is strong — "
                            f"reducing sleep to 30s (override)"
                        )
                        sleep_time = 30
                    elif score_strength >= 5.0:
                        # Moderate signal — reduce sleep duration
                        log_debug(
                            f"[VOLUME CAUTION] All 5 timeframes Low volume, score={score_strength:.2f} moderate — "
                            f"sleeping 60s instead of 180s"
                        )
                        sleep_time = 60
                    else:
                        # Weak signal — full session hold as before
                        log_debug(
                            f"[SESSION HOLD] All 5 timeframes Low volume and score={score_strength:.2f} weak — "
                            f"suspending trade evaluation for 180s"
                        )
                        sleep_time = 180
                    
                    time.sleep(sleep_time)
                    continue
                elif len(low_volume_timeframes) >= 4:
                    log_debug(
                        f"[VOLUME WARNING] 4/5 timeframes Low volume ({', '.join(low_volume_timeframes)}) — "
                        "confidence penalized additionally (-10%)"
                    )
                    # Apply extra -10% confidence penalty
                    confidence = max(0, confidence - 10)
                    confidence_display = f"{confidence}% (volume penalty -10%)"
                
                # ────────────────────────────────────────────────────────────
                # H1 & H4 EMA STRENGTH RECOVERY TRACKING (early warning system)
                # ────────────────────────────────────────────────────────────
                h1_ind = indicators.get("H1", {})
                h4_ind = indicators.get("H4", {})
                
                h1_ema_strength = h1_ind.get("ema_strength")
                h4_ema_strength = h4_ind.get("ema_strength")
                
                # Update H1 history
                if h1_ema_strength is not None:
                    _H1_EMA_HISTORY.append(h1_ema_strength)
                    if len(_H1_EMA_HISTORY) > 20:
                        _H1_EMA_HISTORY.pop(0)
                    
                    # Track negative streak
                    if h1_ema_strength < 0:
                        _H1_NEGATIVE_STREAK += 1
                    else:
                        if _H1_RECOVERY_WATCH:
                            log_debug(f"[H1 RECOVERY CONFIRMED] EMA strength crossed zero: {h1_ema_strength:.3f} — H1 trend flip in progress")
                        _H1_NEGATIVE_STREAK = 0
                        _H1_RECOVERY_WATCH = False
                    
                    # Check for recovery pattern (trending toward zero)
                    if _H1_NEGATIVE_STREAK >= 10 and len(_H1_EMA_HISTORY) >= 3:
                        last_3 = _H1_EMA_HISTORY[-3:]
                        if last_3[-1] > last_3[-2] > last_3[-3]:  # Moving toward zero
                            if not _H1_RECOVERY_WATCH:
                                _H1_RECOVERY_WATCH = True
                                _H1_RECOVERY_TRIGGERED_AT = last_3[-3]
                                _H1_RECOVERY_TRIGGERED_CYCLE = loop_count
                                log_debug(
                                    f"[H1 RECOVERY WATCH] H1 EMA strength trending toward zero: "
                                    f"{last_3[-3]:.3f} → {last_3[-2]:.3f} → {last_3[-1]:.3f} — "
                                    f"bearish pressure weakening, potential trend flip developing. BUY setup may emerge."
                                )
                            else:
                                # Check acceleration
                                recovery_rate = last_3[-1] - last_3[-3]
                                if recovery_rate > 0.15:
                                    log_debug(
                                        f"[H1 RECOVERY ACCELERATING] Rate: +{recovery_rate:.3f}/cycle — "
                                        f"flip timeline shortening. Watch for H1 classification change within 5-8 cycles."
                                    )
                    
                    # Check for false recovery (moving away from zero again)
                    if _H1_RECOVERY_WATCH and len(_H1_EMA_HISTORY) >= 2:
                        if _H1_EMA_HISTORY[-1] < _H1_EMA_HISTORY[-2]:  # Getting more negative
                            log_debug(
                                f"[H1 RECOVERY STALLED] EMA strength reversed direction: "
                                f"{_H1_EMA_HISTORY[-2]:.3f} → {_H1_EMA_HISTORY[-1]:.3f} — "
                                f"false recovery, resuming bearish watch."
                            )
                            _H1_RECOVERY_WATCH = False
                
                # Update H4 history (same logic as H1)
                if h4_ema_strength is not None:
                    _H4_EMA_HISTORY.append(h4_ema_strength)
                    if len(_H4_EMA_HISTORY) > 20:
                        _H4_EMA_HISTORY.pop(0)
                    
                    # Track negative streak
                    if h4_ema_strength < 0:
                        _H4_NEGATIVE_STREAK += 1
                    else:
                        if _H4_RECOVERY_WATCH:
                            log_debug(f"[H4 RECOVERY CONFIRMED] EMA strength crossed zero: {h4_ema_strength:.3f} — H4 trend flip in progress")
                        _H4_NEGATIVE_STREAK = 0
                        _H4_RECOVERY_WATCH = False
                    
                    # Check for recovery pattern (trending toward zero)
                    if _H4_NEGATIVE_STREAK >= 10 and len(_H4_EMA_HISTORY) >= 3:
                        last_3 = _H4_EMA_HISTORY[-3:]
                        if last_3[-1] > last_3[-2] > last_3[-3]:  # Moving toward zero
                            if not _H4_RECOVERY_WATCH:
                                _H4_RECOVERY_WATCH = True
                                _H4_RECOVERY_TRIGGERED_AT = last_3[-3]
                                _H4_RECOVERY_TRIGGERED_CYCLE = loop_count
                                log_debug(
                                    f"[H4 RECOVERY WATCH] H4 EMA strength trending toward zero: "
                                    f"{last_3[-3]:.3f} → {last_3[-2]:.3f} → {last_3[-1]:.3f} — "
                                    f"bearish pressure weakening, potential trend flip developing. BUY setup may emerge."
                                )
                            else:
                                # Check acceleration
                                recovery_rate = last_3[-1] - last_3[-3]
                                if recovery_rate > 0.15:
                                    log_debug(
                                        f"[H4 RECOVERY ACCELERATING] Rate: +{recovery_rate:.3f}/cycle — "
                                        f"flip timeline shortening. Watch for H4 classification change within 5-8 cycles."
                                    )
                    
                    # Check for false recovery (moving away from zero again)
                    if _H4_RECOVERY_WATCH and len(_H4_EMA_HISTORY) >= 2:
                        if _H4_EMA_HISTORY[-1] < _H4_EMA_HISTORY[-2]:  # Getting more negative
                            log_debug(
                                f"[H4 RECOVERY STALLED] EMA strength reversed direction: "
                                f"{_H4_EMA_HISTORY[-2]:.3f} → {_H4_EMA_HISTORY[-1]:.3f} — "
                                f"false recovery, resuming bearish watch."
                            )
                            _H4_RECOVERY_WATCH = False
                    
                    # Log current H4 EMA recovery status (Fix 9: H4 recovery tracker)
                    if _H4_RECOVERY_WATCH:
                        log_debug(
                            f"[H4 RECOVERY ONGOING] Monitoring recovery progression — "
                            f"EMA strength: {h4_ema_strength:.3f}, "
                            f"cycles in recovery: {loop_count - _H4_RECOVERY_TRIGGERED_CYCLE if _H4_RECOVERY_TRIGGERED_CYCLE is not None else 0}"
                        )
                
                # ────────────────────────────────────────────────────────────
                # M1 RSI RECOVERY BOUNCE DETECTION
                # ────────────────────────────────────────────────────────────
                m1_rsi_current = indicators.get("M1", {}).get("rsi_14")
                
                if m1_rsi_current is not None:
                    # Check for bounce from oversold to recovery
                    if _PREV_M1_RSI is not None and _PREV_M1_RSI < 35 and m1_rsi_current > 50:
                        _RSI_BOUNCE_DETECTED = True
                        log_debug(
                            f"[SIGNAL SHIFT] M1 RSI recovery bounce detected: {_PREV_M1_RSI:.1f} → {m1_rsi_current:.1f} — "
                            f"SELL setup invalidating, score may collapse"
                        )
                    
                    # Check for score collapse due to bounce
                    if _RSI_BOUNCE_DETECTED and _PREV_CYCLE_SCORE is not None:
                        score_move = score - _PREV_CYCLE_SCORE
                        if score_move > 2.0:  # Score moved toward zero by more than 2.0
                            log_debug(
                                f"[SCORE COLLAPSE] Score moved from {_PREV_CYCLE_SCORE:.2f} to {score:.2f} "
                                f"(+{score_move:.2f}) due to M1 RSI bounce — setup no longer valid"
                            )
                    
                    # Reset bounce flag when M1 RSI returns below 45
                    if m1_rsi_current < 45:
                        if _RSI_BOUNCE_DETECTED:
                            log_debug(f"[RSI BOUNCE RESET] M1 RSI returned below 45 ({m1_rsi_current:.1f}) — bounce recovery ending")
                        _RSI_BOUNCE_DETECTED = False
                    
                    _PREV_M1_RSI = m1_rsi_current
                
                _PREV_CYCLE_SCORE = score
                
                # Track calibration progress for next cycle's exit detection
                _PREV_CALIBRATION_COUNT = completed_trades
                
                # Determine required confidence based on calibration mode
                if completed_trades < 50:
                    # CALIBRATION MODE: Reduced confidence requirement
                    if session == "London":
                        required_confidence = 42  # More relaxed in best session
                    else:
                        required_confidence = 45  # Standard for other sessions
                else:
                    # PRODUCTION MODE: Standard confidence requirement
                    required_confidence = 45
                
                if confidence < required_confidence or trade_signal == "NO TRADE":
                    h4_trend = indicators.get("H4", {}).get("trend_classification", "Unknown")
                    m1_rsi = indicators.get("M1", {}).get("rsi_14")
                    
                    # Get buy/sell scores from scorecard
                    scorecard = stage1_result.get("scorecard", {})
                    buy_score = scorecard.get("buy_score", 0)
                    sell_score = scorecard.get("sell_score", 0)
                    
                    # Determine blocking reason
                    blocking_reason = ""
                    if trade_signal == "NO TRADE":
                        if abs(score) < 2.0:
                            log_debug(f"{cal_mode_label} [NO TRADE] Score {score:.2f} too close to zero | BuyScore={buy_score:.2f} vs SellScore={sell_score:.2f} — no directional conviction")
                            # FIX A: Set direction to NO TRADE to prevent stale setup display
                            direction = "NO TRADE"
                        else:
                            gates_info = stage1_result.get("gates", {})
                            if gates_info.get("confidence_floor_block"):
                                log_debug(f"{cal_mode_label} [BLOCKED] Reason: HARD SKIP — confidence {confidence}% below floor of 35%")
                                blocking_reason = f"confidence {confidence}% below 35% floor"
                            else:
                                log_debug(f"{cal_mode_label} [BLOCKED] Reason: Score {score:.2f} < threshold {session_threshold:.2f}")
                                blocking_reason = f"score {score:.2f} < {session_threshold:.2f}"
                    elif confidence < required_confidence:
                        log_debug(f"{cal_mode_label} [BLOCKED] Reason: confidence {confidence}% < {required_confidence}% minimum threshold")
                        blocking_reason = f"confidence {confidence}% < {required_confidence}%"
                    
                    sleep_time = calculate_sleep_time(
                        confidence=confidence,
                        required_confidence=required_confidence,
                        stage=1
                    )
                    
                    status = format_monitor_status_line(
                        direction=direction if direction in {"BUY", "SELL"} else "WAIT",
                        score=score,
                        required_score=session_threshold,
                        confidence=confidence,
                        required_confidence=required_confidence,
                        h4_trend=h4_trend,
                        m1_rsi=m1_rsi,
                        next_sleep_secs=sleep_time,
                        result_txt_active=_RESULT_TXT_ACTIVE,
                        h1_recovery_watch=_H1_RECOVERY_WATCH,
                        h4_recovery_watch=_H4_RECOVERY_WATCH,
                        buy_score=buy_score,
                        sell_score=sell_score,
                        blocking_reason=blocking_reason,
                        rsi_bounce_detected=_RSI_BOUNCE_DETECTED,
                    )
                    
                    log_monitor(status)
                    _safe_print(status)
                    time.sleep(sleep_time)
                    continue
                
                log_debug(f"[GATE 1] PASS: {confidence_display}")
                
                # Check if previously written signal has expired
                if _RESULT_TXT_ACTIVE and (_LAST_WRITTEN_DIRECTION != direction or confidence < _LAST_WRITTEN_CONF - 15):
                    if _LAST_WRITTEN_DIRECTION != direction:
                        reason = f"Direction changed from {_LAST_WRITTEN_DIRECTION} to {direction}"
                    else:
                        reason = f"Confidence dropped from {_LAST_WRITTEN_CONF}% to {confidence}%"
                    
                    write_signal_expired(reason, _LAST_WRITTEN_DIRECTION, _LAST_WRITTEN_CONF)
                    _RESULT_TXT_ACTIVE = False
                
                # ────────────────────────────────────────────────────────────
                # STAGE 2: INTERMARKET CHECK (only if stage 1 passes)
                # ────────────────────────────────────────────────────────────
                stage2_result = stage2.run_stage2(direction, indicators)
                
                # Hard block check
                if stage2_result["hard_block"]:
                    hard_block = stage2_result["hard_block"]
                    reason = stage2_result["hard_block_reason"]
                    
                    # BLOCK D: Intermarket score unchanged — apply streak logic
                    if hard_block == "D":
                        current_score = stage2_result.get("intermarket_score")
                        
                        # Check if this is the same score as last time
                        if _LAST_INTERMARKET_SCORE == current_score and current_score <= -3:
                            # Same block condition — increment streak
                            _INTERMARKET_BLOCK_STREAK += 1
                        elif current_score < _LAST_INTERMARKET_SCORE if _LAST_INTERMARKET_SCORE is not None else True:
                            # Score got worse — increment (still bad)
                            _INTERMARKET_BLOCK_STREAK += 1
                        else:
                            # Score improved (less negative or no longer <= -3) — reset
                            _INTERMARKET_BLOCK_STREAK = 0
                        
                        _LAST_INTERMARKET_SCORE = current_score
                        
                        # Calculate adjusted sleep time based on streak
                        if _INTERMARKET_BLOCK_STREAK >= 4:
                            sleep_time = 600  # 10 minutes
                        elif _INTERMARKET_BLOCK_STREAK >= 2:
                            sleep_time = 300  # 5 minutes
                        else:
                            sleep_time = calculate_sleep_time(stage="hard_block")
                        
                        log_debug(
                            f"[HARD BLOCK D] Intermarket STRONG HEADWIND (score={current_score}) | "
                            f"streak={_INTERMARKET_BLOCK_STREAK} consecutive blocks — sleeping {sleep_time}s"
                        )
                    else:
                        # Blocks A, B, C — no streak logic needed
                        sleep_time = calculate_sleep_time(stage="hard_block")
                    
                    log_debug(f"[BLOCKED] Reason: HARD BLOCK {hard_block} — {reason}")
                    msg = format_hard_block(hard_block, reason, sleep_time)
                    log_debug(msg)
                    _safe_print(msg)
                    time.sleep(sleep_time)
                    continue
                
                # Headwind check (not a hard block, but flag for later)
                headwind_detected = stage2_result.get("headwind_detected", False)
                if headwind_detected:
                    log_debug(stage2_result.get("headwind_reason", "Headwind detected"))
                    confidence = max(30, confidence - 10)  # Penalty
                
                # Reset intermarket block streak on successful gate pass
                if _INTERMARKET_BLOCK_STREAK > 0:
                    log_debug(f"[STREAK] Intermarket gate passed — resetting block streak from {_INTERMARKET_BLOCK_STREAK} to 0")
                    _INTERMARKET_BLOCK_STREAK = 0
                    _LAST_INTERMARKET_SCORE = None
                
                log_debug(f"[GATE 2] PASS: no hard blocks, intermarket={stage2_result['intermarket_label']}")
                intermarket_data = stage2_result.get("data", {})
                
                # ────────────────────────────────────────────────────────────
                # RESULT WRITER: Write formatted signal to result.txt
                # ────────────────────────────────────────────────────────────
                
                # FIX 10: VIABILITY SCORE GATE — Suppress low-quality signals
                # Calculate viability before deciding to write
                from utils.result_writer import (
                    _calculate_alignment_score,
                    _calculate_macro_confirmation,
                    _calculate_trade_viability_score,
                    _detect_conflicts,
                )
                
                tf_alignment = _calculate_alignment_score(direction, indicators)
                macro_confirm, macro_total = _calculate_macro_confirmation(direction, intermarket_data)
                conflict_list = _detect_conflicts(direction, confidence, indicators, intermarket_data, None)
                conflict_count = len(conflict_list)
                h4_trend = indicators.get("H4", {}).get("trend_classification", "Unknown")
                gold_bias = "Neutral"
                
                viability_score, viability_interpretation, viability_breakdown = _calculate_trade_viability_score(
                    direction=direction,
                    tf_alignment=tf_alignment,
                    macro_confirm=macro_confirm,
                    macro_total=macro_total,
                    confidence=confidence,
                    h4_trend=h4_trend,
                    gold_bias=gold_bias,
                    events=None,
                    news_has_data=True,
                    calendar_is_fallback=False,
                    conflict_count=conflict_count,
                )
                
                log_debug(f"[VIABILITY GATE] Score: {viability_score}/100 | {viability_interpretation}")
                
                # Check if we should write result.txt
                should_write = (
                    not os.path.exists("result.txt")
                    or abs(confidence - _LAST_WRITTEN_CONF) >= 5
                    or direction != _LAST_WRITTEN_DIRECTION
                )
                
                # FIX B: Suppress result.txt write if direction is NO TRADE (score too close to zero)
                if direction == "NO TRADE":
                    if should_write and _RESULT_TXT_ACTIVE:
                        # Previous signal exists but score collapsed — warn about staleness
                        log_debug(
                            f"[VIABILITY GATE SUPPRESSED] Signal {_LAST_WRITTEN_DIRECTION} would be stale — "
                            f"score collapsed to {score:.2f} (no genuine setup). Previous direction invalidated."
                        )
                    should_write = False
                
                # GATE: Suppress result.txt write if viability too low (threshold: 40/100)
                elif direction in {"BUY", "SELL"} and viability_score < 40:
                    if should_write:
                        log_debug(
                            f"[VIABILITY GATE SUPPRESSED] {direction} signal at {viability_score}/100 viability — "
                            f"insufficient confluence (minimum 40/100). Waiting for stronger setup."
                        )
                    should_write = False
                
                if should_write:
                    # Fetch key levels for the report
                    try:
                        daily_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_D1, 20)
                        weekly_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_W1, 20)
                        key_levels = build_pivot_context(daily_data, weekly_data, current_price=None)
                    except Exception:
                        key_levels = {}
                    
                    # Fetch news data for the report
                    try:
                        from stage3 import fetch_news_sentiment
                        from rss_feed import get_headline_strings
                        headlines = get_headline_strings(limit=20)
                        news_sentiment = fetch_news_sentiment(headlines)
                        news_data = {
                            "sentiment_score": news_sentiment.get("sentiment_score", 0),
                            "dominant_theme": news_sentiment.get("dominant_theme", "Unknown"),
                            "gold_bias": news_sentiment.get("geo_gold_bias", "Neutral"),
                            "risk_sentiment": news_sentiment.get("geo_risk_sentiment", "Neutral"),
                            "analysis": news_sentiment.get("analysis", {}),
                            "headlines": headlines[:5],
                            "events": [],
                        }
                    except Exception as exc:
                        log_debug(f"[RESULT] News fetch error: {exc}")
                        news_data = None
                    
                    # Write the signal report
                    write_result_txt(
                        tech=stage1_result,
                        intermarket=intermarket_data,
                        news=news_data,
                        key_levels=key_levels,
                        session=session,
                    )
                    
                    _LAST_WRITTEN_CONF = confidence
                    _LAST_WRITTEN_DIRECTION = direction
                    _RESULT_TXT_ACTIVE = True
                    _RESULT_TXT_WRITE_TIME = time.time()  # Track write timestamp
                    
                    # Get micro lot info for calibration mode
                    micro_lot = get_calibration_micro_lot(completed_trades < 50)
                    
                    # Print clear console notification — only if viability gate passed
                    print("=" * 60)
                    print("[RESULT] *** SIGNAL READY — result.txt UPDATED ***")
                    print(f"[RESULT] Direction : {direction}")
                    print(f"[RESULT] Confidence: {confidence}%")
                    print(f"[RESULT] Viability : {viability_score}/100 ({viability_interpretation})")
                    if completed_trades < 50:
                        print(f"[RESULT] Lot Size   : {micro_lot} (MICRO — calibration mode {completed_trades}/50)")
                    else:
                        print(f"[RESULT] Lot Size   : Risk-based (production mode)")
                    print(f"[RESULT] Entry     : {stage1_result.get('trade_levels', {}).get('entry_price', 'N/A')}")
                    print("[RESULT] Open result.txt → paste into Claude chat")
                    print("=" * 60)
                else:
                    if direction in {"BUY", "SELL"} and viability_score < 40:
                        print(f"[RESULT] ⚠ VIABILITY SUPPRESSED: {viability_score}/100 (need ≥40) — waiting for stronger setup")
                    else:
                        print(f"[RESULT] No significant change — result.txt unchanged")
                        print(f"[RESULT] Conf={confidence}% | Dir={direction} | Last written conf={_LAST_WRITTEN_CONF}%")
                
                # Check for price staleness warning
                if _RESULT_TXT_ACTIVE and _RESULT_TXT_WRITE_TIME > 0:
                    staleness_seconds = time.time() - _RESULT_TXT_WRITE_TIME
                    if staleness_seconds > 180:  # older than 3 minutes
                        print(
                            f"[RESULT] ⚠ result.txt is "
                            f"{int(staleness_seconds/60)}m old — "
                            f"price may have moved. Check live price before entry."
                        )
                
                # Bot continues monitoring — does NOT stop or execute here
                time.sleep(60)
                continue
            
            except Exception as exc:
                sleep_time = calculate_sleep_time(stage="hard_block")
                msg = format_error("Unhandled Exception", str(exc), sleep_time)
                log_debug(msg)
                _safe_print(msg)
                time.sleep(sleep_time)
    
    except KeyboardInterrupt:
        log_debug("KeyboardInterrupt — exiting")
    finally:
        shutdown_mt5()
        log_debug("Monitoring loop ended. MT5 connection closed.")
        _safe_print("\n[SHUTDOWN] Bot stopped.")


def main() -> None:
    """Entry point."""
    main_loop()


if __name__ == "__main__":
    main()
