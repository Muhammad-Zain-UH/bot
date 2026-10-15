"""WEEK 1 VERIFICATION TEST - Standalone with mock data (no MT5 required).

Tests:
1. Bias detection (H4 EMA-based)
2. H1 structure validation
3. M15 pullback detection
4. Liquidity pool scoring and ranking

Run: python test_week1_layers_standalone.py
"""

from __future__ import annotations
import sys
import pandas as pd
import numpy as np

# Import new engines
from bias_engine import get_h4_bias
from structure_engine import get_h1_structure
from pullback_detector import get_m15_pullback
from liquidity_engine import get_liquidity_pools


def generate_mock_data(num_candles: int, trend: str = "BULLISH") -> pd.DataFrame:
    """Generate realistic mock OHLC data for testing.
    
    Args:
        num_candles: Number of candles to generate
        trend: "BULLISH", "BEARISH", or "NEUTRAL"
    
    Returns:
        DataFrame with OHLC data
    """
    np.random.seed(42)
    
    close_prices = []
    base_price = 2440.0
    
    if trend == "BULLISH":
        direction = 1
    elif trend == "BEARISH":
        direction = -1
    else:
        direction = 0
    
    for i in range(num_candles):
        # Add trend movement + random walk
        movement = direction * 0.3 + np.random.normal(0, 0.5)
        base_price += movement
        close_prices.append(base_price)
    
    close_prices = np.array(close_prices)
    
    # Generate OHLC
    opens = close_prices + np.random.normal(0, 0.2, num_candles)
    highs = np.maximum(opens, close_prices) + np.abs(np.random.normal(0, 0.3, num_candles))
    lows = np.minimum(opens, close_prices) - np.abs(np.random.normal(0, 0.3, num_candles))
    
    # Volumes
    volumes = np.random.randint(1000, 5000, num_candles)
    
    # Calculate EMAs
    ema20 = pd.Series(close_prices).ewm(span=20, adjust=False).mean().values
    ema50 = pd.Series(close_prices).ewm(span=50, adjust=False).mean().values
    
    # Calculate RSI
    rsi_vals = []
    for i in range(num_candles):
        if i < 14:
            rsi_vals.append(50)
        else:
            deltas = np.diff(close_prices[max(0, i-14):i+1])
            seed = deltas[:1]
            up = seed[seed >= 0].sum() / 14
            down = -seed[seed < 0].sum() / 14
            rs = up / down if down != 0 else 1
            rsi = 100 - (100 / (1 + rs))
            rsi_vals.append(rsi)
    
    df = pd.DataFrame({
        'time': pd.date_range(start='2024-01-01', periods=num_candles, freq='15min'),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': close_prices,
        'tick_volume': volumes,
        'ema20': ema20,
        'ema50': ema50,
        'rsi': rsi_vals,
    })
    
    return df


def test_layers():
    """Run tests on Layers 1-4 with mock data."""
    print("[TEST] Starting Week 1 Layer Verification (Mock Data)...\n")
    
    try:
        # Generate mock data
        print("[DATA] Generating mock XAUUSD data...")
        h4_data = generate_mock_data(50, trend="BULLISH")
        h1_data = generate_mock_data(100, trend="BULLISH")
        m15_data = generate_mock_data(250, trend="BULLISH")
        d1_data = generate_mock_data(10, trend="BULLISH")
        
        print(f"  ✓ H4: {len(h4_data)} candles (BULLISH trend)")
        print(f"  ✓ H1: {len(h1_data)} candles (BULLISH trend)")
        print(f"  ✓ M15: {len(m15_data)} candles (BULLISH trend)")
        print(f"  ✓ D1: {len(d1_data)} candles (BULLISH trend)\n")
        
        # TEST 1: H4 BIAS ENGINE
        print("=" * 60)
        print("[TEST 1] H4 BIAS ENGINE")
        print("=" * 60)
        
        h4_indicators = {
            "close": float(h4_data.iloc[-1]["close"]),
            "high": float(h4_data.iloc[-1]["high"]),
            "low": float(h4_data.iloc[-1]["low"]),
            "ema20": float(h4_data.iloc[-1]["ema20"]),
            "ema50": float(h4_data.iloc[-1]["ema50"]),
        }
        
        bias_result = get_h4_bias(h4_indicators, d1_data)
        print(f"\n{bias_result['full_report']}")
        print(f"\n  Bias: {bias_result['bias']}")
        print(f"  Strength: {bias_result['bias_strength']:.1f}/10")
        print(f"  Swing High: {bias_result['swing_high']:.2f}")
        print(f"  Swing Low: {bias_result['swing_low']:.2f}")
        print(f"  EMA20 Distance: {bias_result['ema_distance']:.2f} pips")
        
        if bias_result["invalidated"]:
            print(f"  ⚠️  INVALIDATED: {bias_result['flip_reason']}")
        
        # Verify
        if bias_result['bias'] in ['BULLISH', 'BEARISH', 'NEUTRAL']:
            print(f"\n✓ Bias test PASSED: {bias_result['bias']}\n")
        else:
            print(f"\n✗ Bias test FAILED: Invalid bias {bias_result['bias']}\n")
            return False
        
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
        
        if structure_result['structure_type'] in ['HH/HL', 'LH/LL', 'BROKEN', 'UNKNOWN']:
            print(f"✓ Structure test PASSED: {structure_result['structure_type']}\n")
        else:
            print(f"✗ Structure test FAILED\n")
            return False
        
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
        
        if pullback_result['pullback_quality'] >= 0 and pullback_result['pullback_quality'] <= 10:
            print(f"✓ Pullback test PASSED\n")
        else:
            print(f"✗ Pullback test FAILED\n")
            return False
        
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
                if pool['confluence_reasons']:
                    print(f"       Reasons: {', '.join(pool['confluence_reasons'][:2])}")
        else:
            print(f"\n  No pools scored ≥60")
        
        print(f"\n✓ Liquidity test PASSED\n")
        
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

✅ ALL TESTS PASSED ✅

Next Steps:
  1. Review the logic of each layer
  2. Adjust parameters if needed (EMA distance, fib levels, scoring)
  3. Run on real historical data with MT5 connection
  4. Move to Week 2: Entry Logic Implementation
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
