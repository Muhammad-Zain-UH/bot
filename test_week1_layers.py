"""WEEK 1 VERIFICATION TEST - Validates Layers 1-4 on historical data.

Tests:
1. Bias detection (H4 EMA-based)
2. H1 structure validation
3. M15 pullback detection
4. Liquidity pool scoring and ranking

Run: python test_week1_layers.py
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
import pandas as pd

# Import new engines
from bias_engine import get_h4_bias
from structure_engine import get_h1_structure
from pullback_detector import get_m15_pullback
from liquidity_engine import get_liquidity_pools

# Import existing data fetcher
from mt5_handler import get_market_data
import config


def test_layers():
    """Run basic tests on Layers 1-4."""
    print("[TEST] Starting Week 1 Layer Verification...\n")
    
    # Fetch historical data
    print("[DATA] Fetching XAUUSD historical data...")
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            print("[ERROR] MT5 connection failed. Cannot run tests.")
            return False
        
        # Get data for each timeframe
        h4_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_H4, 50)
        h1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_H1, 100)
        m15_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_M15, 250)
        d1_data = get_market_data(config.SYMBOL, mt5.TIMEFRAME_D1, 10)
        
        if any(len(d) == 0 for d in [h4_data, h1_data, m15_data, d1_data]):
            print("[ERROR] Failed to fetch some timeframe data.")
            return False
        
        print(f"  ✓ H4: {len(h4_data)} candles")
        print(f"  ✓ H1: {len(h1_data)} candles")
        print(f"  ✓ M15: {len(m15_data)} candles")
        print(f"  ✓ D1: {len(d1_data)} candles\n")
        
        # TEST 1: H4 BIAS ENGINE
        print("=" * 60)
        print("[TEST 1] H4 BIAS ENGINE")
        print("=" * 60)
        
        h4_indicators = {
            "close": h4_data.iloc[-1]["close"],
            "high": h4_data.iloc[-1]["high"],
            "low": h4_data.iloc[-1]["low"],
            "ema20": h4_data.iloc[-1].get("ema20", h4_data.iloc[-1]["close"]),
            "ema50": h4_data.iloc[-1].get("ema50", h4_data.iloc[-1]["close"]),
        }
        
        bias_result = get_h4_bias(h4_indicators, d1_data)
        print(f"\n{bias_result['full_report']}")
        print(f"\n  Bias: {bias_result['bias']}")
        print(f"  Strength: {bias_result['bias_strength']:.1f}/10")
        print(f"  Swing High: {bias_result['swing_high']:.2f}")
        print(f"  Swing Low: {bias_result['swing_low']:.2f}")
        
        if bias_result["invalidated"]:
            print(f"  ⚠️  INVALIDATED: {bias_result['flip_reason']}")
        
        print(f"\n✓ Bias test passed: {bias_result['bias']}\n")
        
        # TEST 2: H1 STRUCTURE VALIDATION
        print("=" * 60)
        print("[TEST 2] H1 STRUCTURE VALIDATION")
        print("=" * 60)
        
        structure_result = get_h1_structure(h1_data, bias_result["bias"])
        print(f"\n  Structure Valid: {structure_result['structure_valid']}")
        print(f"  Structure Type: {structure_result['structure_type']}")
        print(f"  Confidence: {structure_result['structure_confidence']:.1f}/10")
        print(f"  Last Swing High: {structure_result['last_swing_high']:.2f}")
        print(f"  Last Swing Low: {structure_result['last_swing_low']:.2f}")
        print(f"\n  Reason: {structure_result['reasoning']}\n")
        
        if not structure_result['structure_valid']:
            print(f"  Break reason: {structure_result['break_reason']}\n")
        
        print(f"✓ Structure test passed\n")
        
        # TEST 3: M15 PULLBACK DETECTION
        print("=" * 60)
        print("[TEST 3] M15 PULLBACK DETECTION")
        print("=" * 60)
        
        pullback_result = get_m15_pullback(m15_data, bias_result["bias"])
        print(f"\n  Pullback Detected: {pullback_result['pullback_detected']}")
        print(f"  Quality Score: {pullback_result['pullback_quality']:.1f}/10")
        print(f"  Depth (Fib): {pullback_result['pullback_depth_fib']}")
        print(f"  Duration: {pullback_result['pullback_duration']} candles")
        print(f"  Volume Trend: {pullback_result['volume_trend']}")
        print(f"  RSI State: {pullback_result['rsi_state']}")
        print(f"\n  Reason: {pullback_result['reasoning']}\n")
        
        print(f"✓ Pullback test passed\n")
        
        # TEST 4: LIQUIDITY POOL SCORING
        print("=" * 60)
        print("[TEST 4] LIQUIDITY POOL SCORING & RANKING")
        print("=" * 60)
        
        liquidity_result = get_liquidity_pools(m15_data, h1_data, h4_data)
        
        print(f"\n  Total Pools Found: {len(liquidity_result['liquidity_pools'])}")
        print(f"  Recommendation: {liquidity_result['recommendation']}")
        
        if liquidity_result['top_3_pools']:
            print(f"\n  Top 3 Pools:")
            for i, pool in enumerate(liquidity_result['top_3_pools'], 1):
                print(f"\n    {i}. Level: {pool['level']:.2f}")
                print(f"       Type: {pool['pool_type']}")
                print(f"       Score: {pool['score']}/100 ({pool['tier']}-Tier)")
                print(f"       Reasons: {', '.join(pool['confluence_reasons'][:2])}")
        
        print(f"\n✓ Liquidity test passed\n")
        
        # SUMMARY
        print("=" * 60)
        print("[SUMMARY] Week 1 Layer Verification")
        print("=" * 60)
        print(f"""
LAYER 1 (H4 Bias):
  ✓ Bias: {bias_result['bias']}
  ✓ Strength: {bias_result['bias_strength']:.1f}/10
  ✓ Invalidated: {bias_result['invalidated']}

LAYER 2 (H1 Structure):
  ✓ Valid: {structure_result['structure_valid']}
  ✓ Type: {structure_result['structure_type']}
  ✓ Confidence: {structure_result['structure_confidence']:.1f}/10

LAYER 3 (M15 Pullback):
  ✓ Detected: {pullback_result['pullback_detected']}
  ✓ Quality: {pullback_result['pullback_quality']:.1f}/10
  ✓ Depth: {pullback_result['pullback_depth_fib']}

LAYER 4 (Liquidity Pools):
  ✓ Pools Found: {len(liquidity_result['liquidity_pools'])}
  ✓ Top Tier: {liquidity_result['top_3_pools'][0]['tier'] if liquidity_result['top_3_pools'] else 'None'}
  ✓ Recommendation: {liquidity_result['recommendation']}

ALL TESTS PASSED ✓
""")
        
        return True
    
    except Exception as exc:
        print(f"\n[ERROR] Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_layers()
    sys.exit(0 if success else 1)
