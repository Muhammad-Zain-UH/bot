"""Tests for the canonical unit system.

The central requirement: on XAUUSD, ``$3``, ``3 pips`` and ``30 pips`` are three
different quantities and the type system must never let one stand in for another.
That confusion is the single most widespread defect the Phase 1 audit found.
"""

from __future__ import annotations

import unittest

from core.symbols import EURUSD_5DIGIT, XAUUSD_2DIGIT, XAUUSD_3DIGIT
from core.units import (
    AtrMultiple,
    Percentage,
    Pips,
    Points,
    PriceDistance,
    UnitMismatchError,
)


class ThreeDollarsIsNotThreePipsTests(unittest.TestCase):
    """The headline case, stated directly.

    ``entry_engine._select_stop_anchor`` does ``min(candidates) - buffer_pips``
    with ``buffer_pips = 3.0``, producing a $3.00 stop buffer where 3 pips was
    meant -- a 10x error on every stop the system places.
    """

    def test_three_price_units_is_thirty_pips_on_gold(self) -> None:
        self.assertEqual(PriceDistance(3.0).to_pips(XAUUSD_2DIGIT), Pips(30.0))

    def test_three_pips_is_thirty_cents_on_gold(self) -> None:
        self.assertEqual(Pips(3.0).to_price(XAUUSD_2DIGIT), PriceDistance(0.30))

    def test_the_three_quantities_are_mutually_distinct(self) -> None:
        dollars_3 = PriceDistance(3.0)
        pips_3 = Pips(3.0)
        pips_30 = Pips(30.0)

        self.assertNotEqual(pips_3, pips_30)
        self.assertNotEqual(dollars_3, pips_3)
        self.assertNotEqual(dollars_3, pips_30)
        # $3.00 and 30 pips are the same distance, but only after an explicit
        # conversion that names the instrument.
        self.assertEqual(dollars_3.to_pips(XAUUSD_2DIGIT), pips_30)

    def test_bare_float_cannot_substitute_for_a_typed_distance(self) -> None:
        with self.assertRaises(UnitMismatchError):
            Pips(3.0) + PriceDistance(3.0)

    def test_the_buffer_bug_is_reproducible_and_the_fix_is_expressible(self) -> None:
        """Reproduce the live defect, then show the typed form that prevents it."""
        swing_low = 4000.00

        # What entry_engine does today: subtract "3.0 pips" straight from a price.
        buggy_stop = swing_low - 3.0
        self.assertAlmostEqual(buggy_stop, 3997.00)
        actual_buffer = PriceDistance(swing_low - buggy_stop).to_pips(XAUUSD_2DIGIT)
        self.assertEqual(actual_buffer, Pips(30.0))  # intended 3

        # The typed form cannot express the mistake.
        correct_stop = Pips(3.0).to_price(XAUUSD_2DIGIT).below(swing_low)
        self.assertAlmostEqual(correct_stop, 3999.70)


class PipAndPointConversionTests(unittest.TestCase):
    """Pips, points and price must round-trip, per instrument."""

    def test_price_to_pips_round_trip(self) -> None:
        for spec in (XAUUSD_2DIGIT, XAUUSD_3DIGIT, EURUSD_5DIGIT):
            with self.subTest(symbol=spec.symbol, digits=spec.digits):
                original = PriceDistance(1.2345)
                self.assertEqual(original.to_pips(spec).to_price(spec), original)

    def test_price_to_points_round_trip(self) -> None:
        for spec in (XAUUSD_2DIGIT, XAUUSD_3DIGIT, EURUSD_5DIGIT):
            with self.subTest(symbol=spec.symbol, digits=spec.digits):
                original = PriceDistance(0.5)
                self.assertEqual(original.to_points(spec).to_price(spec), original)

    def test_pips_to_points_round_trip(self) -> None:
        for spec in (XAUUSD_2DIGIT, XAUUSD_3DIGIT, EURUSD_5DIGIT):
            with self.subTest(symbol=spec.symbol):
                self.assertEqual(Pips(7.0).to_points(spec).to_pips(spec), Pips(7.0))

    def test_points_per_pip_is_broker_specific_not_hardcoded(self) -> None:
        """Same instrument, different quote precision, different points-per-pip."""
        self.assertEqual(XAUUSD_2DIGIT.points_per_pip, 10.0)
        self.assertEqual(XAUUSD_3DIGIT.points_per_pip, 100.0)
        self.assertEqual(EURUSD_5DIGIT.points_per_pip, 10.0)

    def test_pip_size_is_identical_across_gold_quote_precisions(self) -> None:
        """A gold pip is $0.10 whether the broker quotes 2 or 3 decimals.

        This is why pip size cannot be derived from ``digits``.
        """
        self.assertEqual(
            Pips(10.0).to_price(XAUUSD_2DIGIT), Pips(10.0).to_price(XAUUSD_3DIGIT)
        )

    def test_same_pip_count_is_a_different_price_distance_across_instruments(self) -> None:
        gold = Pips(10.0).to_price(XAUUSD_2DIGIT)
        forex = Pips(10.0).to_price(EURUSD_5DIGIT)
        self.assertEqual(gold, PriceDistance(1.0))
        self.assertEqual(forex, PriceDistance(0.001))
        self.assertNotEqual(gold, forex)

    def test_mt5_raw_spread_is_points_not_pips(self) -> None:
        """``(ask - bid) / point`` yields POINTS.

        Reading that number as pips is the 10x error that made a normal 2.3 pip
        London spread log as '23.0pip' before the SPREAD-1 fix.
        """
        raw = (4000.30 - 4000.00) / XAUUSD_2DIGIT.point
        self.assertAlmostEqual(raw, 30.0, places=6)
        self.assertEqual(Points(raw).to_pips(XAUUSD_2DIGIT), Pips(3.0))


class PercentageTests(unittest.TestCase):
    """``Percentage(0.5)`` is 0.5 %, never 50 %."""

    def test_percentage_to_price(self) -> None:
        self.assertEqual(Percentage(1.0).to_price(4000.0), PriceDistance(40.0))

    def test_price_to_percentage_round_trip(self) -> None:
        self.assertEqual(PriceDistance(40.0).to_percentage(4000.0), Percentage(1.0))

    def test_fraction_conversions_are_inverse(self) -> None:
        self.assertAlmostEqual(Percentage(0.5).as_fraction(), 0.005)
        self.assertEqual(Percentage.from_fraction(0.005), Percentage(0.5))

    def test_percent_and_fraction_are_not_interchangeable(self) -> None:
        """``INTRADAY_RISK_PER_TRADE = 0.5`` means 0.5 %, not 50 %."""
        self.assertNotEqual(Percentage(0.5), Percentage.from_fraction(0.5))
        self.assertEqual(Percentage.from_fraction(0.5), Percentage(50.0))

    def test_zero_reference_price_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PriceDistance(1.0).to_percentage(0.0)


class AtrMultipleTests(unittest.TestCase):
    """An ATR multiple is dimensionless until resolved against a real ATR."""

    def test_resolves_against_a_price_distance(self) -> None:
        self.assertEqual(AtrMultiple(1.5).to_price(PriceDistance(2.0)), PriceDistance(3.0))

    def test_round_trip_through_price(self) -> None:
        atr = PriceDistance(2.5)
        self.assertEqual(PriceDistance(5.0).to_atr_multiple(atr), AtrMultiple(2.0))

    def test_resolves_to_pips(self) -> None:
        self.assertEqual(
            AtrMultiple(2.0).to_pips(PriceDistance(1.5), XAUUSD_2DIGIT), Pips(30.0)
        )

    def test_refuses_an_atr_that_is_not_a_price_distance(self) -> None:
        """An ATR in pips must be converted before use, not passed through."""
        with self.assertRaises(UnitMismatchError):
            AtrMultiple(1.5).to_price(Pips(15.0))  # type: ignore[arg-type]

    def test_zero_atr_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PriceDistance(5.0).to_atr_multiple(PriceDistance(0.0))


class UnitGuardTests(unittest.TestCase):
    """Mixing units raises; it never silently converts."""

    def test_addition_across_units_raises(self) -> None:
        for left, right in (
            (Pips(1.0), Points(1.0)),
            (PriceDistance(1.0), Percentage(1.0)),
            (AtrMultiple(1.0), Pips(1.0)),
        ):
            with self.subTest(left=type(left).__name__, right=type(right).__name__):
                with self.assertRaises(UnitMismatchError):
                    left + right  # type: ignore[operator]

    def test_subtraction_across_units_raises(self) -> None:
        with self.assertRaises(UnitMismatchError):
            Pips(5.0) - PriceDistance(1.0)

    def test_ordering_across_units_raises(self) -> None:
        with self.assertRaises(UnitMismatchError):
            Pips(5.0) < PriceDistance(1.0)  # type: ignore[operator]

    def test_equality_across_units_is_false_not_an_error(self) -> None:
        """Containers and ``==`` must stay usable; only arithmetic is fatal."""
        self.assertFalse(Pips(3.0) == PriceDistance(3.0))
        self.assertNotIn(PriceDistance(3.0), [Pips(3.0), Points(3.0)])

    def test_same_unit_arithmetic_is_allowed(self) -> None:
        self.assertEqual(Pips(3.0) + Pips(4.0), Pips(7.0))
        self.assertEqual(Pips(10.0) - Pips(4.0), Pips(6.0))

    def test_scalar_multiplication_preserves_the_unit(self) -> None:
        self.assertEqual(Pips(3.0) * 2, Pips(6.0))
        self.assertEqual(2 * Pips(3.0), Pips(6.0))

    def test_multiplying_two_quantities_raises(self) -> None:
        with self.assertRaises(UnitMismatchError):
            Pips(3.0) * Pips(2.0)  # type: ignore[operator]

    def test_dividing_same_units_yields_a_plain_ratio(self) -> None:
        ratio = Pips(10.0) / Pips(4.0)
        self.assertIsInstance(ratio, float)
        self.assertAlmostEqual(ratio, 2.5)

    def test_dividing_by_a_scalar_preserves_the_unit(self) -> None:
        self.assertEqual(Pips(10.0) / 4, Pips(2.5))

    def test_division_by_zero_raises(self) -> None:
        with self.assertRaises(ZeroDivisionError):
            Pips(1.0) / 0

    def test_non_finite_values_are_rejected(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    PriceDistance(bad)

    def test_booleans_are_rejected_as_magnitudes(self) -> None:
        """``True`` is an ``int`` in Python; silently becoming 1.0 would be wrong."""
        with self.assertRaises(ValueError):
            Pips(True)  # type: ignore[arg-type]


class PriceDistanceHelperTests(unittest.TestCase):
    """Applying a distance to a price is directional and explicit."""

    def test_above_and_below(self) -> None:
        distance = Pips(20.0).to_price(XAUUSD_2DIGIT)
        self.assertAlmostEqual(distance.above(4000.0), 4002.0)
        self.assertAlmostEqual(distance.below(4000.0), 3998.0)

    def test_quantize_snaps_to_the_tick_grid(self) -> None:
        self.assertEqual(PriceDistance(0.3456).quantize(XAUUSD_2DIGIT), PriceDistance(0.35))

    def test_quantize_respects_instrument_precision(self) -> None:
        self.assertEqual(PriceDistance(0.3456).quantize(XAUUSD_3DIGIT), PriceDistance(0.346))

    def test_abs_and_negation_preserve_the_unit(self) -> None:
        self.assertEqual(abs(PriceDistance(-5.0)), PriceDistance(5.0))
        self.assertEqual(-Pips(5.0), Pips(-5.0))


if __name__ == "__main__":
    unittest.main()
