import importlib
import unittest

SUBPACKAGES = ("data", "econ", "stats", "hyp", "sim", "sleeves", "portfolio", "live")


class SmokeTest(unittest.TestCase):
    def test_gold_subpackages_import(self):
        for name in SUBPACKAGES:
            with self.subTest(name=name):
                self.assertIsNotNone(importlib.import_module(f"gold.{name}"))


if __name__ == "__main__":
    unittest.main()
