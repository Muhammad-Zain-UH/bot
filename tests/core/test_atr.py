"""Tests for the canonical Wilder ATR.

Every expected value here is derived by hand in ``tests/fixtures/bars.py`` so the
assertions can be checked against arithmetic rather than against a previous run
of the same code.

These tests also pin the behaviours that distinguish the canonical
implementation from the three non-ATR variants still live in the codebase:
true range accounts for gaps, insufficient data raises instead of silently
returning a fabricated default, and the returned unit is price, not pips.
"""

from __future__ import annotations

import unittest

import pandas as pd

from core.candles import BarConvention, InsufficientBarsError
from core.indicators import (
    ATR_METHOD_WILDER_RMA,
    DEFAULT_ATR_PERIOD,
    AtrResult,
    atr_wilder,
    true_range,
)
from core.symbols import EURUSD_5DIGIT, XAUUSD_2DIGIT
from core.units import Pips, PriceDistance
from tests.fixtures.bars import ATR_FIXTURE_EXPECTED, FLAT_BARS, atr_fixture_bars, make_bars


class GoldenValueTests(unittest.TestCase):
    """Against the hand-derived fixture."""

    def test_matches_the_hand_computed_value(self) -> None:
        result = atr_wilder(atr_fixture_bars(), period=3)
        self.assertAlmostEqual(result.value.value, ATR_FIXTURE_EXPECTED, places=12)

    def test_expected_value_is_the_stated_rational(self) -> None:
        """Guards the fixture constant itself against silent edits."""
        self.assertAlmostEqual(ATR_FIXTURE_EXPECTED, 31.0 / 9.0, places=15)

    def test_true_range_series_matches_the_derivation(self) -> None:
        ranges = true_range(atr_fixture_bars()).tolist()
        self.assertEqual([round(v, 10) for v in ranges], [3.0, 3.0, 3.0, 5.0, 3.0])

    def test_first_bar_is_excluded_not_approximated(self) -> None:
        """Bar 0 has no previous close, so its true range is undefined."""
        bars = atr_fixture_bars()
        self.assertEqual(len(true_range(bars)), len(bars) - 1)

    def test_seed_only_case(self) -> None:
        """With exactly ``period`` true ranges the result is their simple mean."""
        bars = make_bars(
            [(10.0, 10.0, 9.0, 9.5), (9.5, 11.0, 10.0, 10.5), (10.5, 12.0, 11.0, 11.5)]
        )
        self.assertAlmostEqual(atr_wilder(bars, period=2).value.value, 1.5, places=12)


class TrueRangeSemanticsTests(unittest.TestCase):
    """True range accounts for gaps; a naive high-minus-low does not."""

    def test_gap_up_is_captured(self) -> None:
        bars = make_bars([(100.0, 101.0, 99.0, 100.0), (110.0, 111.0, 109.0, 110.0)])
        ranges = true_range(bars).tolist()
        # |111 - 100| = 11, far larger than the 2.0 intrabar range.
        self.assertAlmostEqual(ranges[0], 11.0)

    def test_gap_down_is_captured(self) -> None:
        bars = make_bars([(100.0, 101.0, 99.0, 100.0), (90.0, 91.0, 89.0, 90.0)])
        self.assertAlmostEqual(true_range(bars).tolist()[0], 11.0)

    def test_close_to_close_variant_understates_a_wide_bar(self) -> None:
        """Why ``sweep_detector._estimate_m15_atr`` is not ATR.

        It uses ``close.diff().abs()``, which cannot see intrabar range at all.
        Recorded in PHASE_2_ISSUES.md; that module is not migrated in this phase.
        """
        bars = make_bars(
            [(100.0, 100.5, 99.5, 100.0), (100.0, 120.0, 80.0, 100.0)]
        )
        canonical = true_range(bars).tolist()[0]
        close_to_close = abs(100.0 - 100.0)
        self.assertAlmostEqual(canonical, 40.0)
        self.assertAlmostEqual(close_to_close, 0.0)
        self.assertGreater(canonical, close_to_close)

    def test_flat_bars_give_zero_not_nan(self) -> None:
        result = atr_wilder(make_bars(FLAT_BARS), period=2)
        self.assertAlmostEqual(result.value.value, 0.0)


class UnitTests(unittest.TestCase):
    """ATR is returned in price units and converts explicitly."""

    def test_value_is_a_typed_price_distance(self) -> None:
        self.assertIsInstance(atr_wilder(atr_fixture_bars(), period=3).value, PriceDistance)

    def test_conversion_to_pips_is_instrument_specific(self) -> None:
        bars = make_bars(
            [(10.0, 10.0, 9.0, 9.5), (9.5, 11.0, 10.0, 10.5), (10.5, 12.0, 11.0, 11.5)]
        )
        result = atr_wilder(bars, period=2)
        self.assertEqual(result.value, PriceDistance(1.5))
        self.assertEqual(result.to_pips(XAUUSD_2DIGIT), Pips(15.0))
        self.assertEqual(result.to_pips(EURUSD_5DIGIT), Pips(15000.0))

    def test_price_and_pip_readings_are_not_interchangeable(self) -> None:
        """An ATR of 1.5 price units is 15 pips on gold, not 1.5."""
        result = atr_wilder(
            make_bars(
                [(10.0, 10.0, 9.0, 9.5), (9.5, 11.0, 10.0, 10.5), (10.5, 12.0, 11.0, 11.5)]
            ),
            period=2,
        )
        self.assertNotEqual(result.to_pips(XAUUSD_2DIGIT), Pips(result.value.value))


class InsufficientDataTests(unittest.TestCase):
    """Missing data raises; it never fabricates a volatility reading."""

    def test_too_few_bars_raises(self) -> None:
        bars = make_bars([(100.0, 101.0, 99.0, 100.0)] * 3)
        with self.assertRaises(InsufficientBarsError):
            atr_wilder(bars, period=14)

    def test_exactly_period_plus_one_bars_is_enough(self) -> None:
        bars = make_bars([(100.0, 101.0, 99.0, 100.0)] * 4)
        self.assertIsInstance(atr_wilder(bars, period=3), AtrResult)

    def test_no_silent_default_is_returned(self) -> None:
        """The legacy helpers return 15.0 / 10.0 when data is short."""
        bars = make_bars([(100.0, 101.0, 99.0, 100.0)] * 2)
        with self.assertRaises(InsufficientBarsError):
            atr_wilder(bars, period=14)

    def test_single_bar_has_no_true_range(self) -> None:
        with self.assertRaises(InsufficientBarsError):
            true_range(make_bars([(100.0, 101.0, 99.0, 100.0)]))

    def test_invalid_period_raises(self) -> None:
        with self.assertRaises(ValueError):
            atr_wilder(atr_fixture_bars(), period=0)

    def test_nan_values_are_reported_not_silently_dropped(self) -> None:
        bars = atr_fixture_bars()
        bars.loc[:, "high"] = float("nan")
        with self.assertRaises(InsufficientBarsError):
            atr_wilder(bars, period=3)


class DeterminismAndProvenanceTests(unittest.TestCase):
    """Results are reproducible and carry the metadata needed to compare them."""

    def test_repeated_calls_are_identical(self) -> None:
        bars = atr_fixture_bars()
        first = atr_wilder(bars, period=3)
        second = atr_wilder(bars, period=3)
        self.assertEqual(first.value, second.value)

    def test_input_frame_is_not_mutated(self) -> None:
        bars = atr_fixture_bars()
        before = bars.copy(deep=True)
        atr_wilder(bars, period=3)
        pd.testing.assert_frame_equal(bars, before)

    def test_result_records_its_provenance(self) -> None:
        result = atr_wilder(atr_fixture_bars(), period=3)
        self.assertEqual(result.period, 3)
        self.assertEqual(result.method, ATR_METHOD_WILDER_RMA)
        self.assertEqual(result.bars_used, 6)

    def test_default_period_is_fourteen(self) -> None:
        """Phase 1 names the existing period; it does not change it."""
        self.assertEqual(DEFAULT_ATR_PERIOD, 14)

    def test_forming_bar_is_excluded_so_atr_does_not_repaint(self) -> None:
        bars = atr_fixture_bars()
        closed_only = atr_wilder(bars, period=3, convention=BarConvention.CLOSED_ONLY)
        with_forming = atr_wilder(
            bars, period=3, convention=BarConvention.INCLUDES_FORMING
        )
        self.assertNotAlmostEqual(closed_only.value.value, with_forming.value.value)
        self.assertEqual(with_forming.bars_used, closed_only.bars_used - 1)


if __name__ == "__main__":
    unittest.main()
