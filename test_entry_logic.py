#!/usr/bin/env python3
"""
Test momentum and continuation entry logic to verify they bypass Fibonacci/VWAP
"""
import sys
from datetime import datetime
import json

import config
from mt5_handler import connect_mt5, get_market_data, shutdown_mt5
from indicators import calculate_indicators, calculate_indicators_with_swings
from strategy_engine import get_technical_signal
from utils import log_debug
import MetaTrader5 as mt5

def test_entry_logic():
    print("\n" + "="*70)
    print("TESTING MOMENTUM & CONTINUATION ENTRY LOGIC")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("="*70)
    
    # Connect
    try:
        connect_mt5()
    except Exception as e:
        print(f"❌ MT5 Connection failed: {e}")
        return
    
    # Fetch timeframe data
    _TIMEFRAME_MAP = {
        "H4": mt5.TIMEFRAME_H4,
        "H1": mt5.TIMEFRAME_H1,
        "M15": mt5.TIMEFRAME_M15,
        "M5": mt5.TIMEFRAME_M5,
        "M1": mt5.TIMEFRAME_M1,
        "D1": mt5.TIMEFRAME_D1
    }
    
    print("\n📊 Fetching market data...")
    tfi = {}
    for label, tf in _TIMEFRAME_MAP.items():
        try:
            data = get_market_data(config.SYMBOL, tf, 100)
            if data.empty:
                print(f"⚠️  No data for {label}")
                continue
            
            if label == "M15":
                tfi[label] = calculate_indicators_with_swings(data)
            elif label == "M5":
                ind = calculate_indicators(data)
                ind["raw_data"] = data.copy()
                tfi[label] = ind
            else:
                tfi[label] = calculate_indicators(data)
            
            print(f"✓ {label} trend={tfi[label].get('trend_classification')} | RSI={tfi[label].get('rsi_14', 0):.1f}")
        except Exception as e:
            print(f"❌ {label} error: {e}")
    
    if not tfi:
        print("❌ No indicator data retrieved")
        shutdown_mt5()
        return
    
    # Get signal
    print("\n🔍 Analyzing signals...")
    try:
        tech = get_technical_signal(config.SYMBOL, tfi, high_impact_news=False)
    except Exception as e:
        print(f"❌ Signal analysis error: {e}")
        shutdown_mt5()
        return
    
    # Display results
    print("\n" + "-"*70)
    print("SIGNAL ANALYSIS RESULTS:")
    print("-"*70)
    
    direction = tech.get("setup_direction", "NO TRADE")
    trade_signal = tech.get("technical_signal", "NO TRADE")
    confidence = tech.get("technical_confidence", 0)
    score = tech.get("weighted_score", 0)
    entry_state = tech.get("entry_timing_state", "not_actionable")
    gates = tech.get("gates", {})
    entry_method = gates.get("entry_method", "none")
    
    print(f"\n📌 Direction: {direction}")
    print(f"📌 Signal: {trade_signal}")
    print(f"📌 Confidence: {confidence}%")
    print(f"📌 Score: {score:.2f}")
    print(f"📌 Entry State: {entry_state}")
    print(f"📌 Entry Method: {entry_method}")
    
    if entry_method == "momentum":
        print(f"   → {gates.get('momentum_reason', 'N/A')}")
        print(f"   ✅ MOMENTUM ENTRY DETECTED - Bypassing Fibonacci/VWAP checks!")
    elif entry_method == "continuation":
        print(f"   → {gates.get('continuation_reason', 'N/A')}")
        print(f"   ✅ CONTINUATION ENTRY DETECTED - Bypassing Fibonacci/VWAP checks!")
    else:
        if entry_state == "ready_pullback_await_wick":
            print(f"   → Waiting for M1 wick confirmation (pullback path)")
        else:
            print(f"   → Reason: {tech.get('wait_reason', 'N/A')}")
    
    # Timeframe analysis
    print(f"\n📊 Timeframe Analysis:")
    tfa = tech.get("timeframe_analysis", {})
    for tf in ["H1", "M15", "M5", "M1"]:
        if tf in tfa:
            direction = tfa[tf].get("direction", "N/A")
            strength = tfa[tf].get("strength", "N/A")
            print(f"   {tf}: {direction} ({strength})")
    
    # Risk assessment
    print(f"\n⚠️  Risk Level: {tech.get('risk_level', 'N/A')}")
    print(f"   High-impact news detected: {tech.get('high_impact_news', False)}")
    print(f"   Mixed signals: {tech.get('mixed_signals', False)}")
    
    # Trade levels
    levels = tech.get("trade_levels", {})
    if levels.get("entry_price"):
        print(f"\n💰 Trade Levels:")
        print(f"   Entry: {levels.get('entry_price', 'N/A'):.2f}")
        print(f"   SL: {levels.get('stop_loss', 'N/A'):.2f}")
        print(f"   TP: {levels.get('take_profit', 'N/A'):.2f}")
    
    print("\n" + "="*70)
    print("✅ TEST COMPLETE")
    print("="*70 + "\n")
    
    shutdown_mt5()

if __name__ == "__main__":
    try:
        test_entry_logic()
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
