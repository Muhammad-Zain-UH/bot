import unittest

from main_production import build_layer_progress_summary


class ProductionLayerSummaryTests(unittest.TestCase):
    def test_lists_passed_layers_and_current_block_explicitly(self):
        summary = build_layer_progress_summary(
            ["L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY", "L5_SWEEP", "L6_POI", "L7_CONFIDENCE"],
            "L8_SPREAD",
        )

        self.assertIn("7/8 entry layers passed", summary)
        self.assertIn("Completed: L1_BIAS, L2_STRUCTURE, L3_PULLBACK, L4_LIQUIDITY, L5_SWEEP, L6_POI, L7_CONFIDENCE", summary)
        self.assertIn("Current block: L8_SPREAD", summary)


if __name__ == "__main__":
    unittest.main()
