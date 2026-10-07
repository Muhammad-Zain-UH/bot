"""The stop-anchor selector is entry-aware: it never returns a wrong-side anchor.

`_select_stop_anchor` previously selected purely by extremeness -- `min` of the
BUY candidates, `max` of the SELL candidates -- without ever seeing the entry
price. It could therefore return a candidate already on the wrong side of the
entry, leaving the fixed buffer to rescue the geometry or not. Under a midpoint
MOMENTUM entry the displacement origin is the *near* FVG edge and so is
wrong-side by construction; measured across baseline_007 it was wrong-side in
139 of 139 midpoint candidates.

The contract pinned here: a structural candidate is eligible only if it is
**strictly** on the protective side of the entry -- below for BUY, above for
SELL. Among eligible candidates the original most-defensive ordering is
preserved. When none is eligible the selector returns ``None`` and the caller's
existing entry-relative ATR fallback supplies the stop.

**Deliberately not pinned here.** The buffer magnitude and its unit remain
untouched and unresolved (P8-08); ``test_baseline_defects`` still pins the
current value. Nothing here asserts that a wider or narrower stop is preferable,
and no profitability, signal-count or trade-outcome measure may be used to change
these tests.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import entry_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
# Derived from the production constant, never hardcoded. This file's contract is
# the ENTRY-AWARENESS of the selector, and its docstring says the buffer
# magnitude is "deliberately not pinned here" -- so the buffer must not be able
# to break these tests. It previously read `BUFFER = 3.0`, which did exactly
# that when U1 was fixed: five tests failed, each by precisely $2.70, the
# difference between the $3.00 the bare float produced and the $0.30 that 3 pips
# actually is.
BUFFER = entry_engine.STOP_ANCHOR_BUFFER_PIPS.to_price(entry_engine.XAUUSD_SPEC).value


class BuyRejectsCandidatesAtOrAboveEntry(unittest.TestCase):
    """For a BUY the stop must sit below entry, so candidates at or above are out."""

    def test_a_candidate_above_entry_is_not_selected(self) -> None:
        anchor = entry_engine._select_stop_anchor(
            "BUY", 4000.0, sweep_wick_low=4001.0, structure_low=3995.0
        )
        self.assertAlmostEqual(anchor, 3995.0 - BUFFER, places=9)

    def test_all_candidates_above_entry_yields_none(self) -> None:
        self.assertIsNone(entry_engine._select_stop_anchor(
            "BUY", 4000.0, sweep_wick_low=4001.0, structure_low=4002.0
        ))

    def test_a_candidate_equal_to_entry_is_not_eligible(self) -> None:
        """Strictly below: an anchor at the entry is the old zero-risk geometry."""
        self.assertIsNone(
            entry_engine._select_stop_anchor("BUY", 4000.0, sweep_wick_low=4000.0)
        )


class SellRejectsCandidatesAtOrBelowEntry(unittest.TestCase):
    """For a SELL the stop must sit above entry, so candidates at or below are out."""

    def test_a_candidate_below_entry_is_not_selected(self) -> None:
        anchor = entry_engine._select_stop_anchor(
            "SELL", 4000.0, sweep_wick_high=3999.0, structure_high=4005.0
        )
        self.assertAlmostEqual(anchor, 4005.0 + BUFFER, places=9)

    def test_all_candidates_below_entry_yields_none(self) -> None:
        self.assertIsNone(entry_engine._select_stop_anchor(
            "SELL", 4000.0, sweep_wick_high=3999.0, structure_high=3998.0
        ))

    def test_a_candidate_equal_to_entry_is_not_eligible(self) -> None:
        self.assertIsNone(
            entry_engine._select_stop_anchor("SELL", 4000.0, sweep_wick_high=4000.0)
        )


class EligibleCandidatesKeepMostDefensiveOrdering(unittest.TestCase):
    """The original selection rule is preserved among survivors."""

    def test_buy_takes_the_lowest_eligible_candidate(self) -> None:
        anchor = entry_engine._select_stop_anchor(
            "BUY", 4000.0, sweep_wick_low=3990.0, structure_low=3995.0
        )
        self.assertAlmostEqual(anchor, 3990.0 - BUFFER, places=9)

    def test_sell_takes_the_highest_eligible_candidate(self) -> None:
        anchor = entry_engine._select_stop_anchor(
            "SELL", 4000.0, sweep_wick_high=4010.0, structure_high=4005.0
        )
        self.assertAlmostEqual(anchor, 4010.0 + BUFFER, places=9)

    def test_the_survivor_wins_even_when_the_filtered_one_was_more_extreme(self) -> None:
        """For SELL, 3990 is the more extreme value but is on the wrong side."""
        anchor = entry_engine._select_stop_anchor(
            "SELL", 4000.0, sweep_wick_high=4002.0, structure_high=3990.0
        )
        self.assertAlmostEqual(anchor, 4002.0 + BUFFER, places=9)


class NoEligibleAnchorFallsThroughToTheExistingFallback(unittest.TestCase):
    """``None`` hands over to the caller's entry-relative ATR stop, unchanged."""

    def test_buy_with_only_wrong_side_candidates_uses_the_atr_fallback(self) -> None:
        levels = entry_engine.calculate_entry_levels(
            entry_price=4000.0, direction="BUY",
            sweep_wick_low=4001.0, structure_low=4002.0,
            m5_atr=5.0, entry_style="MOMENTUM", tp_ratio=1.5,
        )
        # existing fallback: entry - max(atr*1.5, 8.0) = 4000 - 8.0
        self.assertAlmostEqual(levels["stop_loss"], 4000.0 - 8.0, places=9)
        self.assertLess(levels["stop_loss"], levels["entry_price"])

    def test_sell_with_only_wrong_side_candidates_uses_the_atr_fallback(self) -> None:
        levels = entry_engine.calculate_entry_levels(
            entry_price=4000.0, direction="SELL",
            sweep_wick_high=3999.0, structure_high=3998.0,
            m5_atr=5.0, entry_style="MOMENTUM", tp_ratio=1.5,
        )
        self.assertAlmostEqual(levels["stop_loss"], 4000.0 + 8.0, places=9)
        self.assertGreater(levels["stop_loss"], levels["entry_price"])

    def test_the_fallback_formula_itself_is_untouched(self) -> None:
        """PULLBACK keeps its 6.0 floor and its ATR*1.5 scaling."""
        levels = entry_engine.calculate_entry_levels(
            entry_price=4000.0, direction="BUY",
            sweep_wick_low=4001.0,
            m5_atr=10.0, entry_style="PULLBACK", tp_ratio=1.5,
        )
        self.assertAlmostEqual(levels["stop_loss"], 4000.0 - 15.0, places=9)


class TheProductionCallerForwardsTheStrategyEntry(unittest.TestCase):
    """The filter is worthless if the caller omits the entry it filters against."""

    def test_calculate_entry_levels_forwards_its_entry_price(self) -> None:
        levels = entry_engine.calculate_entry_levels(
            entry_price=4000.0, direction="BUY",
            sweep_wick_low=4001.0,          # above entry: ineligible
            m5_atr=5.0, entry_style="MOMENTUM", tp_ratio=1.5,
        )
        self.assertNotAlmostEqual(levels["stop_loss"], 4001.0 - BUFFER, places=9)
        self.assertLess(levels["stop_loss"], levels["entry_price"])

    def test_entry_price_is_a_required_argument(self) -> None:
        """Omission must be impossible, not silently disable the filter."""
        with self.assertRaises(TypeError):
            entry_engine._select_stop_anchor("BUY", sweep_wick_low=3990.0)

    def test_entry_price_has_no_default(self) -> None:
        param = inspect.signature(entry_engine._select_stop_anchor).parameters["entry_price"]
        self.assertIs(param.default, inspect.Parameter.empty)


class TheDefensiveZeroRiskGuardIsRetained(unittest.TestCase):
    """Unreachable by construction, kept deliberately -- not deleted."""

    def test_the_guarded_division_is_still_present(self) -> None:
        source = (REPO_ROOT / "entry_engine.py").read_text(encoding="utf-8")
        self.assertIn(
            "rr = reward_distance / risk_distance if risk_distance > 0 else 0", source,
            "the defensive zero-risk guard was removed; it is defence-in-depth and "
            "must be retained even though the entry-aware invariant makes it "
            "unreachable",
        )

    def test_risk_is_strictly_positive_on_both_paths(self) -> None:
        """Why the guard is unreachable: every path floors risk above zero."""
        cases = (
            # anchor path: eligible candidate, risk = |entry-candidate| + buffer
            dict(entry_price=4000.0, direction="BUY", sweep_wick_low=3999.99),
            dict(entry_price=4000.0, direction="SELL", sweep_wick_high=4000.01),
            # fallback path: only wrong-side candidates
            dict(entry_price=4000.0, direction="BUY", sweep_wick_low=4001.0),
            dict(entry_price=4000.0, direction="SELL", sweep_wick_high=3999.0),
        )
        for kwargs in cases:
            with self.subTest(**kwargs):
                levels = entry_engine.calculate_entry_levels(
                    m5_atr=5.0, entry_style="MOMENTUM", tp_ratio=1.5, **kwargs
                )
                self.assertGreater(levels["risk_distance"], 0.0)
                self.assertNotEqual(levels["reward_to_risk_ratio"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
