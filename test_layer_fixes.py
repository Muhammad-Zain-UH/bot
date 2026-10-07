"""Verify layer 1-5 fixes."""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime

import pandas as pd
import numpy as np

from bias_engine import get_h4_bias, _find_h4_swings, calculate_h4_ema_bias
from structure_engine import find_h1_swings, get_h1_structure
from liquidity_engine import find_equal_levels, identify_liquidity_pools, find_previous_day_extremes, score_liquidity_pool
from pullback_detector import get_m15_pullback
from poi_engine import detect_order_block, detect_fvg
from confidence_engine import calculate_confidence_score, evaluate_poi_fib_confluence
from fibonacci_levels import find_swing_high_low, calculate_fibonacci_levels
from entry_engine import get_entry_trigger, calculate_entry_levels
from sweep_detector import get_sweep_and_structure, detect_sweep
from strategy_engine import _bias_context, _momentum_entry_conditions


def test_h4_swings_not_single_candle():
    n = 60
    base = 4300 + np.cumsum(np.random.default_rng(1).normal(0, 0.3, n))
    h4 = pd.DataFrame({
        "high": base + 2,
        "low": base - 2,
        "close": base,
        "open": base - 0.1,
    })
    swings = _find_h4_swings(h4)
    assert swings["swing_high"] is not None
    assert swings["swing_low"] is not None
    # Should not be limited to only the last candle extremes in all cases
    assert swings["swing_high"] >= h4["high"].iloc[-1] - 50


def test_h4_bias_threshold_scales_with_atr():
    n = 60
    close = np.linspace(100, 130, n)
    h4 = pd.DataFrame({
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "open": close - 0.2,
    })

    base_indicators = {
        "close": float(h4.iloc[-1]["close"]),
        "high": float(h4.iloc[-1]["high"]),
        "low": float(h4.iloc[-1]["low"]),
        "ema20": 105.2,
        "ema50": 100.0,
        "closes_2": [104.8, 105.2],
    }

    high_atr_result = calculate_h4_ema_bias({**base_indicators, "atr_14": 40.0}, daily_data=None, h4_data=h4)
    low_atr_result = calculate_h4_ema_bias({**base_indicators, "atr_14": 10.0}, daily_data=None, h4_data=h4)

    assert high_atr_result["ema_threshold"] == 8.0
    assert high_atr_result["bias"] == "NEUTRAL"
    assert low_atr_result["ema_threshold"] == 5.0
    assert low_atr_result["bias"] == "BULLISH"


def test_h1_swings_scan_backward():
    # Fractal high at index 7 (25) with two confirming bars to the right
    highs = [10, 12, 14, 13, 11, 18, 17, 25, 23, 21]
    lows = [8, 9, 11, 10, 9, 14, 13, 12, 17, 16]
    h1 = pd.DataFrame({"high": highs, "low": lows, "close": highs, "open": lows})
    swings = find_h1_swings(h1, lookback=10)
    assert swings["recent_high"] == 25


def test_h1_structure_uses_progression_not_absolute_peak():
    h1 = pd.DataFrame({
        "open":  [100, 101, 102, 103, 104, 105],
        "high":  [101, 102, 103, 104, 105, 106],
        "low":   [99, 100, 101, 102, 103, 104],
        "close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
    })

    result = get_h1_structure(h1, "BULLISH")
    assert result["structure_valid"] is True
    assert result["structure_type"] == "HH/HL"
    assert result["structure_confidence"] > 0


def test_strategy_bias_uses_h4_primary_direction():
    tfi = {
        "H4": {"trend_strength_ratio": 1.0},
        "H1": {"trend_strength_ratio": 0.9},
    }
    tfa = {
        "H4": {"direction": "BUY", "trend_classification": "Strong Bullish"},
        "H1": {"direction": "SELL", "trend_classification": "Strong Bearish"},
    }

    bias = _bias_context(tfi, tfa)
    assert bias["direction"] == "BUY"
    assert bias["h1_countertrend"] is True
    assert bias["strength"] <= 0.55


def test_momentum_requires_h1_confirmation():
    tfi = {
        "M5": {"rsi_14": 65.0},
        "M1": {
            "close": 105.0,
            "prev_high": 104.0,
            "prev_low": 102.0,
            "high": 105.6,
            "low": 103.8,
            "atr_14": 1.2,
            "body": 0.9,
            "latest_volume": 2200.0,
            "average_volume_20": 1000.0,
            "price_vs_vwap": "Above",
        },
    }
    tfa = {
        "H1": {"direction": "SELL"},
        "M15": {"direction": "BUY"},
        "M5": {"direction": "BUY"},
        "M1": {"direction": "BUY"},
    }
    bias = {"direction": "BUY"}
    volume = {"dead": False}

    result = _momentum_entry_conditions("BUY", bias, tfi, tfa, volume)
    assert result["momentum_ready"] is False
    assert "H1 structure" in result["reason"]


def test_equal_levels_dedup():
    df = pd.DataFrame({
        "high": [100.0, 100.1, 100.2, 101.0, 100.15, 100.05],
        "low": [99.0, 98.0, 97.0, 96.0, 95.0, 94.0],
    })
    levels = find_equal_levels(df, tolerance_pips=0.25, lookback=6)
    high_clusters = [lvl for lvl in levels if lvl["type"] == "equal_high"]
    assert high_clusters
    assert high_clusters[0]["touches"] <= 6


def test_pdh_pdl():
    daily = pd.DataFrame({
        "high": [100, 110, 120],
        "low": [90, 95, 100],
        "close": [95, 105, 115],
    })
    prev = find_previous_day_extremes(daily)
    assert prev["pdh"] == 110
    assert prev["pdl"] == 95


def test_sweep_type_returned():
    m15 = pd.DataFrame({
        "open": [100, 100, 100],
        "high": [108, 101, 100],
        "low": [99, 99, 99],
        "close": [99.5, 99.8, 99.5],
        "tick_volume": [2000, 1500, 1200],
    })
    h1 = m15.copy()
    result = get_sweep_and_structure(m15, h1, 100.0, "SELL")
    assert "sweep_type" in result
    assert result["sweep_confirmed"] is True
    assert result["sweep_type"] == "bearish_sweep"


def test_sweep_uses_dynamic_range_and_volume_gate():
    m15_low_volume = pd.DataFrame({
        "open":  [100.4, 100.2, 100.1, 100.0, 100.2, 100.1, 100.0, 100.3, 100.4, 100.4],
        "high":  [120.0, 100.6, 100.4, 100.3, 100.5, 100.4, 100.2, 100.5, 120.0, 120.0],
        "low":   [85.0, 99.8, 99.9, 99.8, 99.9, 99.8, 99.7, 99.9, 85.0, 99.8],
        "close": [100.6, 100.3, 100.2, 100.1, 100.3, 100.2, 100.1, 100.4, 100.6, 100.4],
        "tick_volume": [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1200, 1000],
    })
    m15_high_volume = m15_low_volume.copy()
    m15_high_volume.loc[8, "tick_volume"] = 2200

    low_volume_result = detect_sweep(m15_low_volume, 100.0, "BUY")
    high_volume_result = detect_sweep(m15_high_volume, 100.0, "BUY")

    assert low_volume_result["sweep_confirmed"] is False
    assert high_volume_result["sweep_confirmed"] is True
    assert high_volume_result["sweep_candle_idx"] == 8


def test_liquidity_picks_nearest_directional_pool():
    closes = [100, 100.5, 101, 100.8, 100.6, 99.0, 99.2, 99.1, 100.2, 100.4, 95.0, 95.1, 95.0, 100.8, 101.0, 100.9, 99.0, 99.1, 99.0, 100.2, 100.4, 95.0, 95.1, 95.0, 100.8]
    m15 = pd.DataFrame({
        "open": [c - 0.1 for c in closes],
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.2 for c in closes],
        "close": closes,
        "tick_volume": [1500] * len(closes),
    })

    result = identify_liquidity_pools(m15, current_price=100.0, side="BUY")
    sweep_pool = result.get("sweep_pool")

    assert sweep_pool is not None
    assert sweep_pool["level"] > 98.0


def test_sweep_detector_confirms_real_bullish_sweep():
    prices = [100, 100.2, 100.4, 100.6, 100.8, 101.0, 100.9, 101.1, 101.3, 101.5, 101.7, 101.9]
    rows = []
    for idx, price in enumerate(prices):
        if idx == 6:
            rows.append({
                "open": 98.4,
                "high": 101.2,
                "low": 97.0,
                "close": 100.6,
                "tick_volume": 3000,
            })
        else:
            rows.append({
                "open": price - 0.1,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "tick_volume": 1200,
            })

    m15 = pd.DataFrame(rows)
    result = detect_sweep(m15, 100.0, "BUY")

    assert result["sweep_confirmed"] is True
    assert result["sweep_type"] == "bullish_sweep"


def test_sweep_prefers_recent_over_stale():
    m15 = pd.DataFrame({
        "open":  [100.4, 100.1, 100.1, 100.1, 100.1, 100.1, 100.1, 100.1, 100.4, 100.2],
        "high":  [120.0, 100.4, 100.3, 100.3, 100.3, 100.3, 100.3, 100.3, 120.0, 100.4],
        "low":   [85.0, 99.9, 99.9, 99.9, 99.9, 99.9, 99.9, 99.9, 85.0, 99.9],
        "close": [100.6, 100.2, 100.2, 100.2, 100.2, 100.2, 100.2, 100.2, 100.6, 100.2],
        "tick_volume": [2500, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 2500, 1000],
    })

    result = detect_sweep(m15, 100.0, "BUY")
    assert result["sweep_confirmed"] is True
    assert result["sweep_candle_idx"] == 8


def test_fvg_direction_is_correct():
    bullish = pd.DataFrame({
        "open":  [100, 104, 105, 106, 107],
        "high":  [102, 107, 108, 109, 110],
        "low":   [99, 105, 106, 107, 108],
        "close": [101, 106, 107, 108, 109],
        "tick_volume": [1000, 1000, 1000, 1000, 1000],
    })
    bearish = pd.DataFrame({
        "open":  [105, 98, 97, 96, 95],
        "high":  [107, 100, 99, 98, 97],
        "low":   [103, 97, 96, 95, 94],
        "close": [104, 99, 98, 97, 96],
        "tick_volume": [1000, 1000, 1000, 1000, 1000],
    })

    bullish_result = detect_fvg(bullish, "BUY")
    bearish_result = detect_fvg(bearish, "SELL")

    assert bullish_result["fvg_found"] is True
    assert bullish_result["fvg_top"] > bullish_result["fvg_bottom"]
    assert bearish_result["fvg_found"] is True
    assert bearish_result["fvg_top"] > bearish_result["fvg_bottom"]


def test_order_block_requires_unmitigated_displacement():
    m15 = pd.DataFrame({
        "open":  [100, 100.1, 100.0, 100.2, 100.1, 100.0, 100.2, 100.0, 110.0, 107.0],
        "high":  [100.8, 100.8, 100.7, 100.9, 100.8, 100.7, 100.9, 109.0, 116.0, 109.0],
        "low":   [99.6, 99.7, 99.6, 99.8, 99.7, 99.6, 99.8, 99.0, 109.0, 106.0],
        "close": [100.3, 100.2, 100.1, 100.3, 100.2, 100.1, 100.3, 108.0, 115.0, 108.0],
        "tick_volume": [1000] * 10,
    })

    result = detect_order_block(m15, "BUY")
    assert result["ob_found"] is False


def test_liquidity_uses_h4_and_daily():
    m15 = pd.DataFrame({
        "high": np.linspace(100, 110, 30),
        "low": np.linspace(99, 109, 30),
        "close": np.linspace(99.5, 109.5, 30),
        "open": np.linspace(99.5, 109.5, 30),
        "tick_volume": np.full(30, 1000),
    })
    h1 = m15.copy()
    h4 = m15.copy()
    daily = pd.DataFrame({
        "high": [105, 108, 112],
        "low": [100, 102, 106],
        "close": [103, 107, 110],
    })
    result = identify_liquidity_pools(m15, h1, h4, daily, current_price=105.0, side="SELL")
    types = {p["pool_type"] for p in result["liquidity_pools"]}
    assert "pdh" in types
    assert "pdl" in types
    assert result.get("sweep_pool") is not None or result.get("tp_pool") is not None


def test_liquidity_pool_scoring_penalizes_distance():
    near = score_liquidity_pool(
        level=112.0,
        pool_type="pdl",
        current_price=100.0,
        age_hours=0.0,
        volume_ratio=1.0,
    )
    far = score_liquidity_pool(
        level=160.0,
        pool_type="pdl",
        current_price=100.0,
        age_hours=0.0,
        volume_ratio=1.0,
    )
    too_close = score_liquidity_pool(
        level=103.0,
        pool_type="pdl",
        current_price=100.0,
        age_hours=0.0,
        volume_ratio=1.0,
    )

    assert far["score"] < near["score"]
    assert too_close["score"] < near["score"]


def test_liquidity_no_fallback_pool_created():
    m15 = pd.DataFrame({
        "open": [100, 100.1, 99.9, 100.2, 100.0, 100.1, 99.8, 100.0, 100.2, 99.9],
        "high": [100.2, 100.3, 100.1, 100.4, 100.2, 100.3, 100.0, 100.2, 100.4, 100.1],
        "low": [99.8, 99.9, 99.7, 99.9, 99.8, 99.9, 99.6, 99.8, 99.9, 99.7],
        "close": [100, 100.1, 99.9, 100.2, 100.0, 100.1, 99.8, 100.0, 100.2, 99.9],
        "tick_volume": [1000] * 10,
    })
    result = identify_liquidity_pools(m15, current_price=100.0, side="SELL")
    sweep_pool = result.get("sweep_pool")
    assert sweep_pool is None or "fallback" not in sweep_pool.get("pool_type", "")


def test_confidence_sessions_penalize_low_quality_hours():
    london = calculate_confidence_score(8, 8, 8, 80, session="LONDON")
    asian = calculate_confidence_score(8, 8, 8, 80, session="ASIAN")
    dead = calculate_confidence_score(8, 8, 8, 80, session="DEAD")

    assert london["confidence_breakdown"]["session_bonus"] == 8.0
    assert asian["confidence_breakdown"]["session_bonus"] == -5.0
    assert dead["confidence_breakdown"]["session_bonus"] == -15.0


def test_poi_fib_confluence_uses_h1_impulse():
    h1 = pd.DataFrame({
        "open":  [100, 102, 104, 106, 108, 110, 112, 114, 116, 114, 112, 110, 108, 106, 104, 102],
        "high":  [101, 103, 105, 107, 109, 116, 114, 115, 117, 115, 113, 111, 109, 107, 105, 103],
        "low":   [99, 101, 103, 105, 107, 109, 110, 111, 112, 110, 108, 106, 104, 102, 100, 98],
        "close": [100.5, 102.5, 104.5, 106.5, 108.5, 112.0, 113.0, 114.0, 116.0, 113.0, 111.0, 109.0, 107.0, 105.0, 103.0, 101.0],
    })

    swing_high, swing_low, _, _ = find_swing_high_low(h1, lookback=16)
    fib_levels = calculate_fibonacci_levels(swing_high, swing_low, "BUY")
    fib_618 = fib_levels["0.618"]

    result = evaluate_poi_fib_confluence(h1, fib_618 + 1.0, fib_618 - 1.0, "BUY")
    assert result["has_fib_confluence"] is True
    assert "0.618" in [level["level"] for level in result["matched_levels"]]


def test_pullback_rejects_range_high_without_impulse():
    closes = [100, 103, 100, 103, 100, 103, 100, 103, 100, 102]
    m15 = pd.DataFrame({
        "open": closes,
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.2 for c in closes],
        "close": closes,
        "tick_volume": [1000, 980, 1020, 970, 1010, 960, 1005, 955, 990, 940],
    })

    result = get_m15_pullback(m15, "BULLISH")
    assert result["pullback_detected"] is False
    assert "No genuine impulse" in result["reasoning"]


def test_pullback_waits_when_swing_is_too_recent():
    closes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 115]
    m15 = pd.DataFrame({
        "open": closes,
        "high": [c + 0.3 for c in closes],
        "low": [c - 0.3 for c in closes],
        "close": closes,
        "tick_volume": [900, 920, 940, 960, 980, 1000, 1020, 1040, 1060, 990],
    })

    result = get_m15_pullback(m15, "BULLISH")
    assert result["pullback_detected"] is False
    assert "Swing too recent" in result["reasoning"]


def test_dead_session_is_hard_block_and_daily_counter_counts_entries():
    import main as main_module
    import main_production as production_module

    original_main_session = main_module.get_session_name
    original_prod_session = production_module.get_session_name
    try:
        main_module.get_session_name = lambda: "DEAD"
        production_module.get_session_name = lambda: "DEAD"

        main_gates = main_module.check_pre_trade_gates()
        prod_gates = production_module.check_pre_trade_gates()

        assert main_gates["all_gates_passed"] is False
        assert prod_gates["all_gates_passed"] is False
        assert any("DEAD SESSION" in reason for reason in main_gates["gates_failed"])
        assert any("DEAD SESSION" in reason for reason in prod_gates["gates_failed"])
    finally:
        main_module.get_session_name = original_main_session
        production_module.get_session_name = original_prod_session

    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - pd.Timedelta(days=1)).date().isoformat()

    with tempfile.TemporaryDirectory() as temp_dir:
        log_path = os.path.join(temp_dir, "signal_log.csv")
        with open(log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "signal_type"])
            writer.writeheader()
            writer.writerow({"timestamp": f"{today}T10:00:00", "signal_type": "ENTRY_SIGNAL"})
            writer.writerow({"timestamp": f"{today}T12:00:00", "signal_type": "PRE_ENTRY"})
            writer.writerow({"timestamp": f"{yesterday}T10:00:00", "signal_type": "ENTRY_SIGNAL"})

        assert main_module._count_today_entry_signals(log_path) == 1
        assert production_module._count_today_entry_signals(log_path) == 1


def test_entry_engine_uses_closed_bars_and_atr_stop():
    m5 = pd.DataFrame({
        "open":  [100, 101, 100.5, 100.2, 100.1, 102.0, 101.2],
        "high":  [101, 102, 101.2, 100.8, 100.7, 103.6, 101.5],
        "low":   [99.5, 100.4, 100.0, 99.8, 99.7, 98.0, 100.8],
        "close": [100.8, 101.5, 100.9, 100.4, 100.2, 103.0, 101.0],
        "tick_volume": [1000, 1100, 1050, 1080, 1090, 2400, 900],
        "rsi": [48, 50, 51, 52, 53, 56, 54],
    })
    m1 = pd.DataFrame({
        "open":  [100, 100.5, 101, 101.4, 101.8, 102.2],
        "high":  [100.8, 101.1, 101.6, 102.0, 102.5, 103.6],
        "low":   [99.8, 100.2, 100.7, 101.1, 101.6, 102.0],
        "close": [100.6, 101.0, 101.4, 101.8, 102.3, 103.4],
        "tick_volume": [900, 920, 940, 960, 980, 1500],
    })

    result = get_entry_trigger(
        m5_data=m5,
        m1_data=m1,
        current_price=999.0,
        direction="BUY",
        sweep_wick_low=None,
        sweep_wick_high=None,
    )

    assert result["entry_triggered"] is True
    assert result["trigger_type"] in {"rejection+choch", "rejection+momentum", "rejection+momentum+choch"}
    assert result["entry_price"] == float(m1.iloc[-2]["close"])
    assert result["stop_loss"] < result["entry_price"]
    assert result["stop_loss"] == result["entry_price"] - (20.0 * 1.5)


def test_entry_engine_supports_atr_fallback_levels():
    levels = calculate_entry_levels(
        entry_price=100.0,
        direction="SELL",
        sweep_wick_low=None,
        sweep_wick_high=None,
        m5_atr=18.0,
    )

    assert levels["stop_loss"] == 127.0
    assert levels["take_profit"] == 19.0
    assert levels["valid_rr"] is True


if __name__ == "__main__":
    test_h4_swings_not_single_candle()
    test_h1_swings_scan_backward()
    test_equal_levels_dedup()
    test_pdh_pdl()
    test_strategy_bias_uses_h4_primary_direction()
    test_momentum_requires_h1_confirmation()
    test_sweep_type_returned()
    test_sweep_uses_dynamic_range_and_volume_gate()
    test_sweep_prefers_recent_over_stale()
    test_fvg_direction_is_correct()
    test_order_block_requires_unmitigated_displacement()
    test_liquidity_uses_h4_and_daily()
    test_liquidity_pool_scoring_penalizes_distance()
    test_liquidity_no_fallback_pool_created()
    test_confidence_sessions_penalize_low_quality_hours()
    test_poi_fib_confluence_uses_h1_impulse()
    test_pullback_rejects_range_high_without_impulse()
    test_pullback_waits_when_swing_is_too_recent()
    test_dead_session_is_hard_block_and_daily_counter_counts_entries()
    test_entry_engine_uses_closed_bars_and_atr_stop()
    test_entry_engine_supports_atr_fallback_levels()
    print("All layer fix tests passed.")
