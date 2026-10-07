import unittest

from entry_engine import evaluate_entry_for_regime


class EntryQualityGateTests(unittest.TestCase):
    def test_micro_scalp_requires_stronger_quality_and_rr(self):
        entry = {
            "entry_triggered": True,
            "entry_style": "PULLBACK",
            "trigger_quality": 4.2,
            "reward_to_risk_ratio": 1.4,
        }
        regime = {"regime": "MICRO_SCALP", "spread_acceptable": True}

        result = evaluate_entry_for_regime(entry, regime)

        self.assertFalse(result["entry_allowed"])
        self.assertIn("quality", result["reason"].lower())

    def test_regime_scalp_allows_stronger_setup(self):
        entry = {
            "entry_triggered": True,
            "entry_style": "MOMENTUM",
            "trigger_quality": 6.8,
            "reward_to_risk_ratio": 2.4,
        }
        regime = {"regime": "REGIME_SCALP", "spread_acceptable": True}

        result = evaluate_entry_for_regime(entry, regime)

        self.assertTrue(result["entry_allowed"])
        self.assertEqual(result["recommended_mode"], "SCALP")

    def test_intraday_requires_high_quality(self):
        entry = {
            "entry_triggered": True,
            "entry_style": "MOMENTUM",
            "trigger_quality": 7.2,
            "reward_to_risk_ratio": 2.8,
        }
        regime = {"regime": "INTRADAY_SWING", "spread_acceptable": True}

        result = evaluate_entry_for_regime(entry, regime)

        self.assertTrue(result["entry_allowed"])
        self.assertEqual(result["recommended_mode"], "INTRADAY")


if __name__ == "__main__":
    unittest.main()
