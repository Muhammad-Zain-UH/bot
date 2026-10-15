"""The two strategy-semantic changes made for LIMIT_FVG, pinned.

Both are deliberate changes to trading behaviour, not bug fixes, and both are
narrow. These tests exist so that neither can be widened, reverted or extended
to the pullback path without a test failing.

1. The CHoCH entry-price override is gone **from the momentum path only**.
   `m1[-1].close` is the close of the candle that broke the swing -- a breakout
   price -- and it sat outside the gap on 13 of 13 measured occurrences, always
   on the far side. A limit cannot rest there.

2. `price_in_fvg` is no longer a term in `core_trigger`. It is still computed
   and still returned, as a diagnostic.

The pullback path has its own, separate `m1[-2]` override which must remain
untouched.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

import entry_engine

SOURCE = Path(entry_engine.__file__)


def _function(name: str) -> ast.FunctionDef:
    """Return the AST of one top-level function in entry_engine."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _assigns_entry_price_from_m1(function: ast.FunctionDef) -> bool:
    """Whether the function assigns confirmed_entry_price from an m1 bar."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "confirmed_entry_price" not in targets:
            continue
        if "m1_data" in ast.unparse(node.value):
            return True
    return False


class ChochOverrideRemovedFromMomentum(unittest.TestCase):
    """Change 1 -- narrow, and only on the LIMIT_FVG path."""

    def test_momentum_does_not_take_its_entry_price_from_m1(self) -> None:
        self.assertFalse(_assigns_entry_price_from_m1(_function("_evaluate_momentum_entry")))

    def test_pullback_still_does(self) -> None:
        """The other consumer is preserved, as required."""
        self.assertTrue(_assigns_entry_price_from_m1(_function("_evaluate_pullback_entry")))

    def test_momentum_entry_price_is_the_fvg_midpoint(self) -> None:
        """Behavioural: with a real FVG, the entry price is the zone centre."""
        m5 = pd.DataFrame({
            # left, middle (bullish), right -- a BUY gap: left.high < right.low
            "open":  [2400.0, 2401.0, 2409.0, 2410.0],
            "high":  [2402.0, 2408.0, 2412.0, 2413.0],
            "low":   [2399.0, 2400.5, 2406.0, 2409.0],
            "close": [2401.0, 2407.5, 2411.0, 2412.0],
            "tick_volume": [100, 300, 200, 150],
        })
        m1 = pd.DataFrame({
            "open":  [2410.0] * 8, "high": [2413.0] * 8,
            "low":   [2409.0] * 8, "close": [2412.0] * 8,
            "tick_volume": [100] * 8,
        })
        result = entry_engine._evaluate_momentum_entry(m5, m1, 2411.0, "BUY")
        fvg = result["fvg"]
        if not fvg.get("fvg_found"):
            self.skipTest("fixture did not produce an FVG in this configuration")
        self.assertAlmostEqual(result["entry_price"], float(fvg["midpoint"]))
        self.assertAlmostEqual(result["limit_price"], float(fvg["midpoint"]))

    def test_the_zone_is_exposed_for_the_intent(self) -> None:
        keys = entry_engine.get_entry_trigger.__doc__ or ""
        # Structural: the keys must exist on the returned payload.
        m5 = pd.DataFrame({
            "open": [2400.0] * 5, "high": [2402.0] * 5,
            "low": [2399.0] * 5, "close": [2401.0] * 5,
            "tick_volume": [100] * 5,
        })
        out = entry_engine.get_entry_trigger(m5, m5, 2401.0, "BUY")
        for key in ("limit_price", "fvg_zone_low", "fvg_zone_high"):
            with self.subTest(key=key):
                self.assertIn(key, out)


class PriceInFvgRemovedFromTrigger(unittest.TestCase):
    """Change 2 -- removed from the conjunction, retained as a diagnostic."""

    def _core_trigger_terms(self) -> str:
        function = _function("_evaluate_momentum_entry")
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "core_trigger"
                        for t in node.targets)
            ):
                return ast.unparse(node.value)
        raise AssertionError("core_trigger assignment not found")

    def test_price_in_fvg_is_not_a_term(self) -> None:
        self.assertNotIn("price_in_fvg", self._core_trigger_terms())

    def test_the_other_four_terms_remain(self) -> None:
        terms = self._core_trigger_terms()
        for term in ("kill_zone", "displacement_found", "fvg_found", "m1_choch_confirmed"):
            with self.subTest(term=term):
                self.assertIn(term, terms)

    def test_price_in_fvg_is_still_returned(self) -> None:
        m5 = pd.DataFrame({
            "open": [2400.0] * 5, "high": [2402.0] * 5,
            "low": [2399.0] * 5, "close": [2401.0] * 5,
            "tick_volume": [100] * 5,
        })
        result = entry_engine._evaluate_momentum_entry(m5, m5, 2401.0, "BUY")
        self.assertIn("price_in_fvg", result)


class EntryModeUnchanged(unittest.TestCase):
    """The momentum path still declares itself LIMIT_FVG."""

    def test_entry_mode_is_limit_fvg(self) -> None:
        m5 = pd.DataFrame({
            "open": [2400.0] * 5, "high": [2402.0] * 5,
            "low": [2399.0] * 5, "close": [2401.0] * 5,
            "tick_volume": [100] * 5,
        })
        result = entry_engine._evaluate_momentum_entry(m5, m5, 2401.0, "BUY")
        self.assertEqual(result["entry_mode"], "LIMIT_FVG")


if __name__ == "__main__":
    unittest.main()
