"""Tests for price-relative thresholds.

This module is **retained but not currently applied to any gate.** Scaling the
L2 volatility floor and the regime bands with it was implemented, measured as
`baselines/baseline_010`, and reverted: it took the strategy from 4 signals to
zero. See `research/UNIT_MIGRATION_REPORT.md` section 3.

It is kept, and tested, because the problem it solves is real and still open —
`main_production.L2_MIN_H1_RANGE_USD` and `entry_engine`'s regime bands are
absolute dollar thresholds on an instrument that went $951 to $4,173, and both
record that in place. When those are re-derived properly, this is the arithmetic
they will need.

Tested to the same standard as the code that does run, because untested retained
code is how a correct tool becomes a wrong one by the time it is picked up.
"""

from __future__ import annotations

import unittest

from core.thresholds import (
    REFERENCE_PRICE,
    ThresholdError,
    as_fraction,
    at_price,
    describe,
)


class ReferenceIsUnchangedAtTheReferenceTests(unittest.TestCase):
    """The defining property: scaling must be a no-op at the anchor."""

    def test_threshold_is_identical_at_the_reference_price(self) -> None:
        for threshold in (0.25, 3.0, 8.0, 60.0):
            self.assertAlmostEqual(
                at_price(threshold, REFERENCE_PRICE), threshold, places=9)

    def test_zero_is_zero_everywhere(self) -> None:
        self.assertEqual(at_price(0.0, 4550.0), 0.0)
        self.assertEqual(as_fraction(0.0), 0.0)


class ScalingIsProportionalTests(unittest.TestCase):
    def test_double_the_price_doubles_the_threshold(self) -> None:
        self.assertAlmostEqual(
            at_price(8.0, 2 * REFERENCE_PRICE), 16.0, places=9)

    def test_half_the_price_halves_the_threshold(self) -> None:
        self.assertAlmostEqual(
            at_price(8.0, REFERENCE_PRICE / 2), 4.0, places=9)

    def test_the_fraction_is_the_ratio_to_the_reference(self) -> None:
        self.assertAlmostEqual(as_fraction(8.0), 8.0 / REFERENCE_PRICE, places=12)

    def test_fraction_and_at_price_agree(self) -> None:
        for price in (1000.0, 1544.08, 4550.0):
            self.assertAlmostEqual(
                at_price(8.0, price), as_fraction(8.0) * price, places=9)

    def test_the_measured_era_values(self) -> None:
        """The figures quoted in the migration report, pinned.

        The L2 floor of $8.00 at the reference becomes these at real price
        levels, which is the whole point: one rule, different dollar amounts.
        """
        self.assertAlmostEqual(at_price(8.0, 1258.0), 6.52, places=2)   # 2017
        self.assertAlmostEqual(at_price(8.0, 2389.0), 12.38, places=2)  # 2024
        self.assertAlmostEqual(at_price(8.0, 4550.0), 23.57, places=2)  # 2026


class RejectsWhatCannotBeScaledTests(unittest.TestCase):
    """Errors, not clamps. A silently corrected threshold is the original bug."""

    def test_non_positive_price_raises(self) -> None:
        """A defaulted price would silently restore an absolute threshold --
        which is exactly the defect this module exists to remove."""
        for bad in (0.0, -1.0, -4550.0):
            with self.assertRaises(ThresholdError) as caught:
                at_price(8.0, bad)
            self.assertIn("must be > 0", str(caught.exception))

    def test_non_finite_price_raises(self) -> None:
        for bad in (float("inf"), float("-inf"), float("nan")):
            with self.assertRaises(ThresholdError):
                at_price(8.0, bad)

    def test_negative_threshold_raises(self) -> None:
        with self.assertRaises(ThresholdError):
            as_fraction(-1.0)
        with self.assertRaises(ThresholdError):
            at_price(-1.0, 4550.0)

    def test_non_finite_threshold_raises(self) -> None:
        for bad in (float("inf"), float("nan")):
            with self.assertRaises(ThresholdError):
                as_fraction(bad)

    def test_non_numeric_raises(self) -> None:
        for bad in ("8.0", None, [8.0], {}):
            with self.assertRaises(ThresholdError):
                at_price(bad, 4550.0)  # type: ignore[arg-type]
            with self.assertRaises(ThresholdError):
                at_price(8.0, bad)  # type: ignore[arg-type]

    def test_bool_is_not_a_number(self) -> None:
        """True == 1 in Python, so a bool would scale silently."""
        with self.assertRaises(ThresholdError):
            at_price(True, 4550.0)  # type: ignore[arg-type]
        with self.assertRaises(ThresholdError):
            at_price(8.0, True)  # type: ignore[arg-type]


class ReferencePriceProvenanceTests(unittest.TestCase):
    """The anchor is a declared choice, and the code must keep saying so."""

    def test_the_reference_is_the_h1_median(self) -> None:
        self.assertAlmostEqual(REFERENCE_PRICE, 1544.08, places=2)

    def test_the_docstring_records_that_it_is_a_choice(self) -> None:
        """A reader who takes this for a derived constant would conclude the
        resulting thresholds were inevitable. They are not -- anchoring at the
        M5 median instead gives 0.1916% of price where the H1 median gives
        0.5181%, which is most of the difference between a gate that blocks 95%
        of bars and one that blocks far fewer.
        """
        import core.thresholds as module

        doc = module.__doc__ or ""
        annotation = getattr(module, "__annotations__", {})
        self.assertIn("declared", (doc + str(annotation)).lower())


class DescribeTests(unittest.TestCase):
    def test_describe_names_both_the_scaled_and_reference_values(self) -> None:
        text = describe(8.0, 4550.0)
        self.assertIn("23.57", text)
        self.assertIn("8.0000", text)
        self.assertIn("1544.08", text)
        self.assertNotIn("\n", text)

    def test_describe_rejects_an_unusable_price(self) -> None:
        with self.assertRaises(ThresholdError):
            describe(8.0, 0.0)


class NotWiredIntoAnyGateTests(unittest.TestCase):
    """Pins the current decision, so re-applying it is a deliberate act.

    Rule 2 was reverted after measurement. If a future change wires this back
    into a volatility gate, that must be done knowingly -- with a fresh
    baseline -- rather than by an import quietly reappearing.
    """

    def test_main_production_does_not_scale_its_l2_floor(self) -> None:
        import inspect

        import main_production

        source = inspect.getsource(main_production)
        self.assertNotIn("core.thresholds", source)
        self.assertIn("L2_MIN_H1_RANGE_USD", source)

    def test_entry_engine_does_not_scale_its_regime_bands(self) -> None:
        import inspect

        import entry_engine

        source = inspect.getsource(entry_engine)
        self.assertNotIn("core.thresholds", source)
        self.assertIn("if m5_atr >= 2.5 and m5_atr <= 4.5:", source)

    def test_both_sites_still_record_the_defect_as_open(self) -> None:
        """The absoluteness is unfixed; the code must not fall silent about it."""
        import inspect

        import entry_engine
        import main_production

        for module in (main_production, entry_engine):
            source = inspect.getsource(module)
            self.assertIn(
                "baseline_010", source,
                f"{module.__name__} must cite the measurement that justified "
                f"leaving its threshold absolute",
            )


if __name__ == "__main__":
    unittest.main()
