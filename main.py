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
from key_levels import build_pivot_context
from mt5_handler import connect_mt5, get_market_data, shutdown_mt5
from risk_manager import (
    get_current_session,
    get_daily_pnl_pct,
    get_session_score_threshold,
    is_daily_loss_limit_hit,
    is_good_trading_session,
    is_market_open,
)
from signal_logger import log_signal
from utils import log_debug
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
    
    loop_count = 0
    
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
            session_threshold = get_session_score_threshold(4.5)
            daily_pnl = get_daily_pnl_pct()
            
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
                score = stage1_result["score"]
                max_score = stage1_result["max_score"]
                direction = stage1_result["setup_direction"]
                indicators = stage1_result["indicators"]
                trade_levels = stage1_result["trade_levels"]
                risk_level = stage1_result["risk_level"]
                
                # GATE 1: Check confidence vs session threshold
                if confidence < 45 or trade_signal == "NO TRADE":
                    h4_trend = indicators.get("H4", {}).get("trend_classification", "Unknown")
                    m1_rsi = indicators.get("M1", {}).get("rsi_14")
                    
                    sleep_time = calculate_sleep_time(
                        confidence=confidence,
                        required_confidence=45,
                        stage=1
                    )
                    
                    status = format_monitor_status_line(
                        direction=direction if direction in {"BUY", "SELL"} else "WAIT",
                        score=score,
                        required_score=session_threshold,
                        confidence=confidence,
                        required_confidence=45,
                        h4_trend=h4_trend,
                        m1_rsi=m1_rsi,
                        next_sleep_secs=sleep_time,
                        result_txt_active=_RESULT_TXT_ACTIVE,
                    )
                    
                    log_debug(status)
                    _safe_print(status)
                    time.sleep(sleep_time)
                    continue
                
                log_debug(f"[GATE 1] PASS: confidence {confidence}% >= 45%")
                
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
                    sleep_time = calculate_sleep_time(stage="hard_block")
                    
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
                
                log_debug(f"[GATE 2] PASS: no hard blocks, intermarket={stage2_result['intermarket_label']}")
                intermarket_data = stage2_result.get("data", {})
                
                # ────────────────────────────────────────────────────────────
                # RESULT WRITER: Write formatted signal to result.txt
                # ────────────────────────────────────────────────────────────
                
                # Check if we should write result.txt
                should_write = (
                    not os.path.exists("result.txt")
                    or abs(confidence - _LAST_WRITTEN_CONF) >= 5
                    or direction != _LAST_WRITTEN_DIRECTION
                )
                
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
                    
                    # Print clear console notification
                    print("=" * 60)
                    print("[RESULT] *** SIGNAL READY — result.txt UPDATED ***")
                    print(f"[RESULT] Direction : {direction}")
                    print(f"[RESULT] Confidence: {confidence}%")
                    print(f"[RESULT] Entry     : {stage1_result.get('trade_levels', {}).get('entry_price', 'N/A')}")
                    print("[RESULT] Open result.txt → paste into Claude chat")
                    print("=" * 60)
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
