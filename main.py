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
from indicators import calculate_indicators
from technical_engine import get_technical_signal
from risk_manager import (get_current_session, get_daily_pnl_pct, is_daily_loss_limit_hit,
                          consecutive_losses, calculate_lot_size)
from news_handler import high_impact_news_within_minutes
from utils import log_debug
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
        result[label] = calculate_indicators(data)
        log_debug(f"{label} → trend={result[label].get('trend_classification')} | RSI={result[label].get('rsi_14')}")
    return result

def main_loop():
    global _SHOULD_CONTINUE
    signal_module.signal(signal_module.SIGINT, _signal_handler)
    if not connect_mt5():
        print("MT5 connection failed.")
        return
    loss_pause_end = None
    regime_validated = False
    last_signal_setup = None  # Track the last identified setup

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

            # Consecutive loss pause (pass log file explicitly)
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

            # ========== MAIN CYCLE (60 second) ==========
            # Fetch indicators
            tfi = fetch_all_indicators(config.SYMBOL, config.N_CANDLES)
            tech = get_technical_signal(config.SYMBOL, tfi)
            trade_signal = tech["technical_signal"]
            direction = tech["setup_direction"]
            confidence = tech["technical_confidence"]
            score = tech["weighted_score"]

            if trade_signal in ("BUY","SELL") and confidence >= 45:
                levels = tech.get("trade_levels", {})
                entry = levels.get("entry_price")
                sl = levels.get("stop_loss")
                tp = levels.get("take_profit")
                account = mt5.account_info()
                balance = account.balance if account else 10000
                stop_dist = abs(entry - sl) if entry and sl else 10.0
                lot = calculate_lot_size(balance, 1.0, stop_dist)

                print("\n" + "="*60)
                print(f"*** SIGNAL READY ***")
                print(f"Direction: {trade_signal}")
                print(f"Confidence: {confidence}%")
                print(f"Score: {score:.2f}/{tech['max_score']}")
                print(f"Entry: {entry} | SL: {sl} | TP: {tp}")
                print(f"Lot size: {lot:.2f}")
                print("="*60 + "\n")

                # Store the setup for intracandle confirmation
                last_signal_setup = {
                    "signal": trade_signal,
                    "direction": direction,
                    "confidence": confidence,
                    "score": score,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "lot": lot,
                    "setup_time": datetime.now(),
                }

                # ========== INTRACANDLE M1 SUB-LOOP (5 seconds) ==========
                # When signal is confirmed, run a tight loop to catch exact M1 entry
                log_debug(f"[ENTRY WINDOW] Starting 5-second intracandle checks for {trade_signal}...")
                intracandle_timeout = datetime.now() + timedelta(seconds=30)  # 30 sec window

                while datetime.now() < intracandle_timeout and _SHOULD_CONTINUE:
                    try:
                        # Fetch fresh M1 data only (fastest update)
                        m1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M1, 5)
                        if not m1_data.empty:
                            m1_current = calculate_indicators(m1_data)
                            m1_close = m1_current.get("close")
                            m1_trend = m1_current.get("trend_classification")

                            log_debug(
                                f"[INTRACANDLE] M1: {m1_close:.2f} | Trend: {m1_trend} | "
                                f"Time: {datetime.now().strftime('%H:%M:%S')}"
                            )

                            # Check for entry confirmation on M1
                            if trade_signal == "BUY" and "Bullish" in str(m1_trend):
                                log_debug(f"✓ [ENTRY CONFIRMED] M1 printed bullish candle → ENTER BUY at {m1_close:.2f}")
                                # Execute trade here (placeholder)
                                break
                            elif trade_signal == "SELL" and "Bearish" in str(m1_trend):
                                log_debug(f"✓ [ENTRY CONFIRMED] M1 printed bearish candle → ENTER SELL at {m1_close:.2f}")
                                # Execute trade here (placeholder)
                                break

                        # Sleep 5 seconds before next M1 check
                        time.sleep(5)

                    except Exception as intra_exc:
                        log_debug(f"Intracandle check error: {intra_exc}")
                        time.sleep(5)

                # Log to CSV (whether entry was executed or timed out)
                log_file = "signal_log.csv"
                file_exists = os.path.isfile(log_file)
                with open(log_file, "a", newline="") as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(["timestamp","symbol","signal","confidence","score","entry","sl","tp","lot","intracandle_confirmed"])
                    intracandle_confirmed = (datetime.now() < intracandle_timeout)
                    writer.writerow([datetime.now().isoformat(), config.SYMBOL, trade_signal, confidence, score, entry, sl, tp, lot, intracandle_confirmed])

                # Reset setup tracking
                last_signal_setup = None

            else:
                # No signal or confidence below threshold
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {session} | {trade_signal} | conf={confidence}% | score={score:.2f}")

            # Main loop sleep (60 seconds baseline)
            time.sleep(60)

        except Exception as e:
            log_debug(f"Main loop error: {e}")
            time.sleep(30)

    shutdown_mt5()

if __name__ == "__main__":
    main_loop()