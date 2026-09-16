import unittest
from unittest.mock import patch

import pandas as pd

import main_production as mp


class LayerGateLogicTests(unittest.TestCase):
    def _make_frames(self):
        m5 = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [101.5, 102.5, 103.5],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "tick_volume": [100, 120, 140],
            }
        )
        m15 = m5.copy()
        h1 = m5.copy()
        h4 = m5.copy()
        daily = pd.DataFrame({"high": [105.0], "low": [95.0]})
        return m5, m15, h1, h4, daily

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
