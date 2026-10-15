import logging
import os
import tempfile
import unittest

import main_production as mp


class TestProductionLogOutput(unittest.TestCase):
    def test_print_run_summary_writes_summary_to_log_file(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp_path = tmp.name

        handler = logging.FileHandler(tmp_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        mp.logger.addHandler(handler)

        try:
            analysis = {
                "signal_type": "PRE_ENTRY",
                "layers_passed": ["L1_BIAS"],
                "layer_failed": "L3_PULLBACK",
                "fail_reason": "No confirmed pullback detected",
                "regime_info": {"regime": "REGIME_SCALP"},
                "direction": "BUY",
                "candidate_entry_style": "PULLBACK / MOMENTUM",
            }

            mp.print_run_summary(analysis)
            handler.flush()

            with open(tmp_path, "r", encoding="utf-8") as fh:
                content = fh.read()

            self.assertIn("[DECISION]", content)
            self.assertIn("price=", content)
            self.assertIn("side=BUY", content)
            self.assertIn("blocked=L3_PULLBACK", content)
            self.assertIn("passed=L1_BIAS", content)
        finally:
            mp.logger.removeHandler(handler)
            handler.close()
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
