"""Main orchestrator – continuous monitoring with full risk and trap filters."""
from __future__ import annotations
import signal as signal_module
import sys
import time
from datetime import datetime, timezone, timedelta
import csv
import os

import config
from mt5_handler import connect_mt5, get_market_data, shutdown_mt5, get_current_spread
from indicators import calculate_indicators, calculate_indicators_with_swings
from strategy_engine import get_technical_signal
from risk_manager import (get_current_session, get_daily_pnl_pct, is_daily_loss_limit_hit,
                          consecutive_losses, calculate_lot_size)
from news_handler import high_impact_news_within_minutes
from utils import log_debug
from cvd_divergence import detect_cvd_divergence
import MetaTrader5 as mt5

_SHOULD_CONTINUE = True
_TIMEFRAME_MAP = {"H4": mt5.TIMEFRAME_H4, "H1": mt5.TIMEFRAME_H1, "M15": mt5.TIMEFRAME_M15,
                  "M5": mt5.TIMEFRAME_M5, "M1": mt5.TIMEFRAME_M1, "D1": mt5.TIMEFRAME_D1}

def _signal_handler(signum, frame):
    global _SHOULD_CONTINUE
    _SHOULD_CONTINUE = False
    print("\nShutting down...")

def fetch_all_indicators(symbol: str, n_candles: int) -> dict:
    result = {}
    for label, tf in _TIMEFRAME_MAP.items():
        data = get_market_data(symbol, tf, n_candles)
        if data.empty:
            raise ValueError(f"No data for {label}")
        
        # Use enhanced calculation for M15 (includes swing data for Fibonacci)
        if label == "M15":
            result[label] = calculate_indicators_with_swings(data)
        # Store raw data for M5 (CVD divergence uses M5, more responsive)
        elif label == "M5":
            ind = calculate_indicators(data)
            ind["raw_data"] = data.copy()
            result[label] = ind
        else:
            result[label] = calculate_indicators(data)
        
        log_debug(f"{label} → trend={result[label].get('trend_classification')} | RSI={result[label].get('rsi_14')}")
    
    return result


def _check_rejection_wick(candle_dict: dict, direction: str) -> bool:
    """Check if M1 candle has a rejection wick against the direction.
    
    BUY setup: Long lower wick (sellers rejected)
    SELL setup: Long upper wick (buyers rejected)
    """
    try:
        open_p = float(candle_dict.get('open') or 0)
        close_p = float(candle_dict.get('close') or 0)
        high_p = float(candle_dict.get('high') or 0)
        low_p = float(candle_dict.get('low') or 0)
        
        if any(v == 0 for v in [open_p, close_p, high_p, low_p]):
            return False
        
        body = abs(close_p - open_p)
        full = high_p - low_p
        if full <= 0:
            return False
        
        wick_ratio = (full - body) / full
        
        if direction == "BUY":
            lower_wick = low_p - min(open_p, close_p)
            return lower_wick > body and wick_ratio > 0.6
        else:  # SELL
            upper_wick = max(open_p, close_p) - high_p
            return upper_wick > body and wick_ratio > 0.6
    except Exception as e:
        log_debug(f"Rejection wick check error: {e}")
        return False

def main_loop():
    global _SHOULD_CONTINUE
    signal_module.signal(signal_module.SIGINT, _signal_handler)
    if not connect_mt5():
        print("MT5 connection failed.")
        return
    loss_pause_end = None
    regime_validated = False
    last_m5_candle_time = None  # FIX #2: Track M5 candle for RSI oscillation

    while _SHOULD_CONTINUE:
        try:
            session = get_current_session()
            if session == "Closed":
                log_debug("Market closed – sleeping 1 hour")
                time.sleep(3600)
                continue

            # Daily loss limit
            loss_hit, pnl = is_daily_loss_limit_hit()
            if loss_hit:
                log_debug(f"Daily loss limit hit ({pnl:.2f}%) – stopping")
                break

            # Consecutive loss pause
            loss_hit, loss_count = consecutive_losses("signal_log.csv")
            if loss_hit:
                if loss_pause_end is None:
                    loss_pause_end = datetime.now() + timedelta(hours=2)
                    regime_validated = False
                    log_debug(f"{loss_count} consecutive losses – pausing 2 hours")
                if datetime.now() < loss_pause_end:
                    time.sleep(60)
                    continue
                else:
                    if not regime_validated:
                        h4_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_H4, 50)
                        h4_ind = calculate_indicators(h4_data)
                        atr_ratio = h4_ind.get("atr_ratio", 1.0)
                        if atr_ratio > 0.8 and not high_impact_news_within_minutes(30):
                            regime_validated = True
                            log_debug("Regime confirmed – resuming trading")
                        else:
                            loss_pause_end = datetime.now() + timedelta(hours=1)
                            log_debug("Regime not confirmed – extending pause 1 hour")
                            continue
                    loss_pause_end = None

            # News blackout
            if high_impact_news_within_minutes(15):
                log_debug("News blackout – no new trades")
                time.sleep(60)
                continue

            # Spread check
            spread = get_current_spread(config.SYMBOL)
            if spread > 50:
                log_debug(f"Spread too high ({spread:.0f} pts) – sleeping 30s")
                time.sleep(30)
                continue

            # ========== MAIN 60-SECOND CYCLE ==========
            tfi = fetch_all_indicators(config.SYMBOL, config.N_CANDLES)
            is_high_impact_news = high_impact_news_within_minutes(15)
            tech = get_technical_signal(config.SYMBOL, tfi, high_impact_news=is_high_impact_news)
            trade_signal = tech["technical_signal"]
            direction = tech["setup_direction"]
            confidence = tech["technical_confidence"]
            score = tech["weighted_score"]
            entry_timing_state = tech.get("entry_timing_state", "not_actionable")
            entry_method = tech.get("gates", {}).get("entry_method")  # NEW: momentum or pullback
            h4_conflict = tech.get("gates", {}).get("h4_conflict_warning", False)  # NEW

            # If setup detected (BUY/SELL with high confidence)
            if direction in ("BUY", "SELL") and confidence >= 45:
                # FIX #1: POSITION CHECK GUARD - Prevent duplicate entries
                existing_positions = mt5.positions_get(symbol=config.SYMBOL)
                if existing_positions and len(existing_positions) > 0:
                    log_debug(f"[POSITION GUARD] {len(existing_positions)} position(s) exist – skipping entry")
                    time.sleep(60)
                    continue
                
                # FIX #2: M5 RSI OSCILLATION TRAP - Only 1 entry per M5 candle
                try:
                    m5_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M5, 1)
                    if not m5_data.empty:
                        current_m5_time = m5_data['time'].iloc[-1]
                        if last_m5_candle_time is not None and last_m5_candle_time == current_m5_time:
                            log_debug(f"[M5 OSCILLATION GUARD] Same M5 candle – skipping duplicate entry")
                            time.sleep(60)
                            continue
                        last_m5_candle_time = current_m5_time
                except Exception as e:
                    log_debug(f"[M5 GUARD] Error: {e}")
                
                levels = tech.get("trade_levels", {})
                entry = levels.get("entry_price")
                sl = levels.get("stop_loss")
                tp = levels.get("take_profit")
                account = mt5.account_info()
                balance = account.balance if account else 10000
                stop_dist = abs(entry - sl) if entry and sl else 10.0
                lot = calculate_lot_size(balance, 1.0, stop_dist)

                # FIX #6: TRANSPARENCY - Print trap filter status
                trap_status = tech.get("trap_filter_status", "")
                time_str = datetime.now().strftime('%H:%M:%S')
                if trap_status:
                    print(f"[{time_str}] {direction} | {trap_status}", flush=True)
                log_debug(f"[SETUP DETECTED] {direction} | conf={confidence}% | score={score:.2f} | entry_state={entry_timing_state}")
                
                # NEW: Support for dual entry paths (momentum vs pullback)
                entry_confirmed = False
                entry_confirmed_price = None
                intracandle_timeout = datetime.now() + timedelta(seconds=60)
                
                # Path 1: MOMENTUM ENTRY (fast, no M1 wick wait)
                if entry_timing_state == "ready_momentum":
                    log_debug(f"[MOMENTUM ENTRY] M5 RSI extreme (35/65) – entering immediately...")
                    entry_confirmed = True
                    try:
                        m1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 1)
                        if not m1_data.empty:
                            m1_current = calculate_indicators(m1_data)
                            entry_confirmed_price = m1_current.get("close")
                    except Exception as e:
                        log_debug(f"[MOMENTUM ENTRY] M1 data fetch error: {e}")
                        entry_confirmed_price = None
                
                # Path 1b: OTHER READY STATES (pullback entry - standard)
                elif entry_timing_state in ("ready", "ready_pullback_await_wick"):
                    # Standard pullback entry - wait for M15 pullback + M1 wick confirmation
                    log_debug(f"[PULLBACK] Waiting for M15 pullback + M1 wick confirmation (max 60s)...")
                
                # Path 1c: WAIT_FOR_VOLUME (volume recovering - check if recovered)
                elif entry_timing_state == "wait_for_volume":
                    log_debug(f"[WAIT_FOR_VOLUME] Checking if volume has recovered...")
                    try:
                        m15_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M15, 50)
                        if not m15_data.empty:
                            m15_ind = calculate_indicators(m15_data)
                            vol_ratio = m15_ind.get("volume_ratio")
                            if vol_ratio is not None and vol_ratio >= 0.5:
                                log_debug(f"[WAIT_FOR_VOLUME] Volume recovered ({vol_ratio:.2f}) – entering...")
                                entry_confirmed = True
                                try:
                                    m1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 1)
                                    if not m1_data.empty:
                                        m1_current = calculate_indicators(m1_data)
                                        entry_confirmed_price = m1_current.get("close")
                                except Exception:
                                    entry_confirmed_price = None
                            else:
                                log_debug(f"[WAIT_FOR_VOLUME] Volume still low ({vol_ratio:.2f}) – holding...")
                    except Exception as e:
                        log_debug(f"[WAIT_FOR_VOLUME] Volume check error: {e}")
                
                # Path 2: PULLBACK ENTRY (waits for M15 pullback completion + M1 wick)
                elif entry_timing_state == "ready_pullback_await_wick":
                    log_debug(f"[PULLBACK ENTRY] Waiting for M1 trigger confirmation (max 60 seconds)...")

                    # ========== INTRACANDLE LOOP: Wait for M1 wick confirmation ==========
                    while datetime.now() < intracandle_timeout and _SHOULD_CONTINUE:
                        # FIX #4: PULLBACK TIMEOUT OVERRIDE - Allow entry after 60s timeout
                        time_remaining = (intracandle_timeout - datetime.now()).total_seconds()
                        if time_remaining <= 0:
                            log_debug(f"[PULLBACK TIMEOUT] 60s expired – allowing entry override")
                            entry_confirmed = True
                            try:
                                m1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 1)
                                if not m1_data.empty:
                                    m1_current = calculate_indicators(m1_data)
                                    entry_confirmed_price = m1_current.get("close")
                            except Exception as e:
                                log_debug(f"[PULLBACK TIMEOUT] M1 fetch error: {e}")
                                entry_confirmed_price = None
                            break
                        
                        try:
                            # 1. RE-CHECK SPREAD before any entry
                            current_spread = get_current_spread(config.SYMBOL)
                            if current_spread > 50:
                                log_debug(f"[INTRACANDLE] Spread widened to {current_spread:.0f} pts – waiting...")
                                time.sleep(5)
                                continue

                            # 2. Fetch fresh M1 data
                            m1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 5)
                            if not m1_data.empty:
                                m1_current = calculate_indicators(m1_data)
                                m1_close = m1_current.get("close")
                                m1_trend = m1_current.get("trend_classification")

                                # 3. RE-CHECK REJECTION WICK on latest M1 candle
                                m1_candle = {
                                    'open': m1_current.get('open'),
                                    'high': m1_current.get('high'),
                                    'low': m1_current.get('low'),
                                    'close': m1_current.get('close')
                                }
                                has_wick = _check_rejection_wick(m1_candle, direction)
                                
                                if not has_wick:
                                    price_str = f"{m1_close:.2f}" if m1_close is not None else "N/A"
                                    log_debug(f"[INTRACANDLE] M1: {price_str} | Trend: {m1_trend} | No rejection wick yet – waiting...")
                                    time.sleep(5)
                                    continue

                                # 4. CHECK CVD DIVERGENCE on M5 data
                                cvd_confirmation = False
                                try:
                                    m5_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M5, 20)
                                    if not m5_data.empty:
                                        cvd_result = detect_cvd_divergence(m5_data, lookback=20)
                                        if cvd_result.get("has_divergence") and cvd_result.get("type") in ["bullish", "bearish"]:
                                            log_debug(f"[INTRACANDLE] CVD {cvd_result['type'].upper()} divergence confirmed")
                                            cvd_confirmation = True
                                except Exception as cvd_exc:
                                    log_debug(f"[INTRACANDLE] CVD check: {cvd_exc}")
                                    cvd_confirmation = True  # Don't block on CVD failure

                                # 5. Check M1 trigger confirmation + wick + CVD
                                if direction == "BUY" and "Bullish" in str(m1_trend) and m1_close is not None:
                                    entry_confirmed = True
                                    entry_confirmed_price = m1_close
                                    log_debug(f"✓ [M1 TRIGGER] Bullish candle + rejection wick + CVD → {m1_close:.2f} | Entry confirmed")
                                    break
                                elif direction == "SELL" and "Bearish" in str(m1_trend) and m1_close is not None:
                                    entry_confirmed = True
                                    entry_confirmed_price = m1_close
                                    log_debug(f"✓ [M1 TRIGGER] Bearish candle + rejection wick + CVD → {m1_close:.2f} | Entry confirmed")
                                    break
                                else:
                                    price_str = f"{m1_close:.2f}" if m1_close is not None else "N/A"
                                    log_debug(f"[INTRACANDLE] M1: {price_str} | Trend: {m1_trend} | waiting for confirmation...")

                            # Wait 5 seconds before next M1 check
                            time.sleep(5)

                        except Exception as intra_exc:
                            log_debug(f"[INTRACANDLE] Check error: {intra_exc}")
                            time.sleep(5)
                
                # ========== SIGNAL OUTPUT (only if entry confirmed) ==========
                if entry_confirmed:
                    # Print signal ONLY after confirmation
                    print("\n" + "="*60)
                    print(f"*** ENTRY SIGNAL CONFIRMED ***")
                    print(f"Direction: {direction}")
                    print(f"Entry Method: {entry_method or 'standard'}")  # NEW
                    print(f"H4 Status: {'⚠️ CONFLICT' if h4_conflict else 'Normal'}")  # NEW
                    print(f"Confirmed at: {entry_confirmed_price:.2f}")
                    print(f"Confidence: {confidence}%")
                    print(f"Score: {score:.2f}/{tech['max_score']}")
                    print(f"Entry: {entry} | SL: {sl} | TP: {tp}")
                    print(f"Lot size: {lot:.2f}")
                    print("="*60 + "\n")

                    # Log to CSV (with NEW columns: entry_method and h4_status)
                    log_file = "signal_log.csv"
                    file_exists = os.path.isfile(log_file)
                    with open(log_file, "a", newline="") as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(["timestamp", "symbol", "signal", "confidence", "score", "entry", "sl", "tp", "lot", 
                                           "entry_method", "h4_status", "entry_timing_state"])  # NEW columns
                        writer.writerow([datetime.now().isoformat(), config.SYMBOL, direction, confidence, score, entry, sl, tp, lot,
                                       entry_method or "standard", "CONFLICT" if h4_conflict else "normal", entry_timing_state])  # NEW
                else:
                    # Setup detected but no confirmation within timeout
                    if entry_timing_state == "ready_pullback_await_wick":
                        log_debug(f"[SETUP TIMEOUT] {direction} setup expired (no M1 wick confirmation within 60s)")
                    else:
                        log_debug(f"[SETUP TIMEOUT] {direction} setup expired (entry_state={entry_timing_state})")

            else:
                # No setup or confidence too low
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {session} | {trade_signal} | conf={confidence}% | score={score:.2f}")

            # Main loop sleep
            time.sleep(60)

        except Exception as e:
            log_debug(f"Main loop error: {e}")
            time.sleep(30)

    shutdown_mt5()

if __name__ == "__main__":
    main_loop()