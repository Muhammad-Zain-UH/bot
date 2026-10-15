import unittest
from unittest.mock import patch

import pandas as pd

import main_production as mp


class LayerGateLogicTests(unittest.TestCase):
    def setUp(self):
        # Scalp regimes gate L1 on the H1 FAST bias, not the H4 bias
        # (main_production.py BIAS-2 branch: `use_fast_bias = regime_name in
        # ("MICRO_SCALP", "REGIME_SCALP")`). Every test below sets a scalp
        # regime, so patching only `get_h4_bias` left L1 reading the real
        # `get_fast_bias`, which needs H1 EMAs the fixture has not got and
        # returned NEUTRAL -- blocking at L1.
        #
        # This went unnoticed because `analyze_entry` re-imported
        # `detect_regime` locally, shadowing the patch, so the regime was never
        # actually a scalp regime and this branch was never taken.
        patcher = patch.object(
            mp, "get_fast_bias",
            return_value={
                "bias": "BULLISH", "bias_strength": 8.0,
                "ema20": 101.0, "ema50": 100.0, "ema_distance": 1.0,
                "ema_threshold": 0.2, "invalidated": False, "flip_reason": "",
                "full_report": "[FAST_BIAS] test fixture: BULLISH",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # The L2 volatility floor reads `h1_data` DIRECTLY, not the patched
    # `calculate_indicators`:
    #
    #     h1_atr = None
    #     if h1_data is not None and len(h1_data) >= 14:
    #         h1_atr = (h1_data["high"].tail(14) - h1_data["low"].tail(14)).mean()
    #
    # The previous fixture had THREE bars, so `h1_atr` stayed None and every test
    # died at L2 before reaching the layer it meant to exercise. Two of the three
    # failed outright; the third passed for the wrong reason. Hence: >= 14 bars,
    # and a per-bar range above main_production.L2_MIN_H1_RANGE_USD.
    BARS = 20
    BAR_RANGE_USD = 12.0  # > L2_MIN_H1_RANGE_USD (8.0), so L2 is not the blocker

    def _make_frames(self):
        n = self.BARS
        lows = [100.0 + i for i in range(n)]
        highs = [lo + self.BAR_RANGE_USD for lo in lows]
        m5 = pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC"),
                "open": [lo + 1.0 for lo in lows],
                "high": highs,
                "low": lows,
                "close": [lo + self.BAR_RANGE_USD - 1.0 for lo in lows],
                "tick_volume": [100 + 10 * i for i in range(n)],
            }
        )
        m15 = m5.copy()
        h1 = m5.copy()
        h4 = m5.copy()
        daily = pd.DataFrame({"high": [highs[-1] + 5.0], "low": [lows[0] - 5.0]})
        return m5, m15, h1, h4, daily

    def test_fixture_clears_the_l2_volatility_floor(self):
        """Guard the guard: if this breaks, every test below blocks at L2 again."""
        _, _, h1, _, _ = self._make_frames()
        self.assertGreaterEqual(len(h1), 14)
        h1_atr = (h1["high"].tail(14) - h1["low"].tail(14)).mean()
        self.assertGreater(h1_atr, mp.L2_MIN_H1_RANGE_USD)

    def test_broken_h1_structure_blocks_at_l2(self):
        m5, m15, h1, h4, daily = self._make_frames()

        with patch.object(mp, "calculate_indicators", return_value={}), patch.object(
            mp, "detect_regime", return_value={"regime": "REGIME_SCALP", "spread_acceptable": True, "max_spread_pips": 7.0}
        ), patch.object(mp, "get_h4_bias", return_value={"bias": "BULLISH", "bias_strength": 8.0}), patch.object(
            mp, "get_h1_structure", return_value={"structure_type": "BROKEN", "structure_confidence": 2.0, "structure_valid": False}
        ):
            analysis = mp.analyze_entry(h4_data=h4, h1_data=h1, m15_data=m15, m5_data=m5, m1_data=m5, daily_data=daily, current_price=102.0)

        self.assertEqual(analysis.get("layer_failed"), "L2_STRUCTURE")
        self.assertEqual(analysis.get("signal_type"), "PRE_ENTRY")
        # Assert the REASON, not just the layer. This test previously passed
        # while L2 was rejecting on the volatility floor, so it proved nothing
        # about broken-structure handling.
        reason = analysis.get("fail_reason", "")
        self.assertIn("structure is broken", reason)
        self.assertNotIn("too calm", reason)
        self.assertNotIn("unavailable", reason)

    def test_pullback_gate_requires_real_pullback_detection(self):
        m5, m15, h1, h4, daily = self._make_frames()

        with patch.object(mp, "calculate_indicators", return_value={}), patch.object(
            mp, "detect_regime", return_value={"regime": "REGIME_SCALP", "spread_acceptable": True, "max_spread_pips": 7.0}
        ), patch.object(mp, "get_h4_bias", return_value={"bias": "BULLISH", "bias_strength": 8.0}), patch.object(
            mp, "get_h1_structure", return_value={"structure_type": "HH/HL", "structure_confidence": 8.0, "structure_valid": True}
        ), patch.object(
            mp, "get_m15_pullback", return_value={"pullback_quality": 2.0, "pullback_detected": False, "reasoning": "No pullback confirmed"}
        ):
            analysis = mp.analyze_entry(h4_data=h4, h1_data=h1, m15_data=m15, m5_data=m5, m1_data=m5, daily_data=daily, current_price=102.0)

        self.assertEqual(analysis.get("layer_failed"), "L3_PULLBACK")
        self.assertEqual(analysis.get("signal_type"), "PRE_ENTRY")

    def test_micro_scalp_l7_confidence_uses_55_threshold(self):
        m5, m15, h1, h4, daily = self._make_frames()

        with patch.object(mp, "calculate_indicators", return_value={}), patch.object(
            mp, "detect_regime", return_value={"regime": "MICRO_SCALP", "spread_acceptable": True, "max_spread_pips": 5.0}
        ), patch.object(mp, "get_h4_bias", return_value={"bias": "BULLISH", "bias_strength": 8.0}), patch.object(
            mp, "get_h1_structure", return_value={"structure_type": "HH/HL", "structure_confidence": 8.0, "structure_valid": True}
        ), patch.object(
            mp, "get_m15_pullback", return_value={"pullback_quality": 2.0, "pullback_detected": True, "reasoning": "Good pullback"}
        ), patch.object(
            mp, "identify_liquidity_pools", return_value={
                "liquidity_pools": [{"score": 80, "level": 100.0, "pool_type": "SWEEP"}],
                "sweep_pool": {"score": 80, "level": 100.0, "pool_type": "SWEEP"},
                "tp_pool": {"score": 75, "level": 105.0, "pool_type": "TP"},
            }
        ), patch.object(
            mp, "assess_liquidity_gate", return_value={"state": "PASS", "reason": "ok", "sweep_score": 80, "tp_score": 75, "sweep_distance": 2.0, "thresholds": {}}
        ), patch.object(
            mp, "get_sweep_and_structure", return_value={"gate_state": "PASS", "sweep_confirmed": True, "sweep_quality": 8.0, "setup_grade": "A+", "setup_valid": True, "sweep_wick_low": 100.0, "sweep_wick_high": 102.0, "sweep_type": "bullish"}
        ), patch.object(
            mp, "identify_poi", return_value={"best_poi": {"score": 75.0}} 
        ), patch.object(
            mp, "build_poi_layer_data", return_value={"score": 75.0}
        ), patch.object(
            mp, "get_confidence_engine", return_value={"final_score": 56.5, "grade": "A"}
        ), patch.object(
            mp, "get_entry_trigger", return_value={"entry_triggered": True, "trigger_quality": 6.0, "reward_to_risk_ratio": 1.6, "entry_price": 101.0, "stop_loss": 99.0, "take_profit": 104.0}
        ), patch.object(
            mp, "evaluate_entry_for_regime", return_value={"entry_allowed": True, "recommended_mode": "SCALP", "reason": "micro scalp entry allowed", "regime": "MICRO_SCALP", "quality": 6.0, "rr": 1.6}
        ):
            analysis = mp.analyze_entry(h4_data=h4, h1_data=h1, m15_data=m15, m5_data=m5, m1_data=m5, daily_data=daily, current_price=102.0)

        self.assertNotEqual(analysis.get("layer_failed"), "L7_CONFIDENCE")
        self.assertIn("L7_CONFIDENCE", analysis.get("layers_passed", []))


if __name__ == "__main__":
    unittest.main()
