"""Tests for the canonical bar convention.

The convention exists because the audit found four different answers to "which
row is the current bar?" in a single decision pass. These tests pin the two
failure modes it prevents:

* **Staleness** -- using ``iloc[-2]`` on a frame that contains only closed bars,
  which costs a full bar of lag for nothing.
* **Double-drop** -- applying ``.iloc[:-1]`` to a frame whose forming bar was
  already removed, silently discarding a real bar.
"""

from __future__ import annotations

import unittest

import pandas as pd

from core.candles import (
    HLC_COLUMNS,
    OHLC_COLUMNS,
    BarConvention,
    InsufficientBarsError,
    closed_bars,
    forming_bar,
    has_ohlc_columns,
    last_closed_bar,
    previous_closed_bar,
)
from tests.fixtures.bars import make_bars, simple_bars


class ConventionSelectsDifferentRowsTests(unittest.TestCase):
    """The same frame yields different bars under different conventions."""

    def setUp(self) -> None:
        self.frame = simple_bars()  # closes: 100.5, 101.5, 102.5

    def test_closed_only_last_is_the_final_row(self) -> None:
        bar = last_closed_bar(self.frame, BarConvention.CLOSED_ONLY)
        self.assertAlmostEqual(float(bar["close"]), 102.5)

    def test_includes_forming_last_is_the_penultimate_row(self) -> None:
        bar = last_closed_bar(self.frame, BarConvention.INCLUDES_FORMING)
        self.assertAlmostEqual(float(bar["close"]), 101.5)

    def test_the_two_conventions_disagree_by_exactly_one_bar(self) -> None:
        closed = last_closed_bar(self.frame, BarConvention.CLOSED_ONLY)
        forming = last_closed_bar(self.frame, BarConvention.INCLUDES_FORMING)
        self.assertNotAlmostEqual(float(closed["close"]), float(forming["close"]))

    def test_default_convention_is_closed_only(self) -> None:
        """Matches ``get_market_data(closed_only=True)``, the project default."""
        self.assertAlmostEqual(
            float(last_closed_bar(self.frame)["close"]),
            float(last_closed_bar(self.frame, BarConvention.CLOSED_ONLY)["close"]),
        )

    def test_previous_closed_bar(self) -> None:
        self.assertAlmostEqual(
            float(previous_closed_bar(self.frame, BarConvention.CLOSED_ONLY)["close"]),
            101.5,
        )
        self.assertAlmostEqual(
            float(previous_closed_bar(self.frame, BarConvention.INCLUDES_FORMING)["close"]),
            100.5,
        )

    def test_forming_bar_present_only_under_that_convention(self) -> None:
        self.assertIsNone(forming_bar(self.frame, BarConvention.CLOSED_ONLY))
        bar = forming_bar(self.frame, BarConvention.INCLUDES_FORMING)
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(float(bar["close"]), 102.5)


class StalenessAndDoubleDropTests(unittest.TestCase):
    """Reproduce the two live defects, then show the convention prevents them."""

    def test_stale_indexing_costs_a_full_bar(self) -> None:
        """``iloc[-2]`` on a CLOSED_ONLY frame is one bar behind, for no benefit.

        Live in ``entry_engine.detect_rejection_candle`` and in
        ``main_production``'s ``confirmed_m5_close``.
        """
        frame = simple_bars()
        legacy = float(frame.iloc[-2]["close"])
        canonical = float(last_closed_bar(frame, BarConvention.CLOSED_ONLY)["close"])
        self.assertAlmostEqual(legacy, 101.5)
        self.assertAlmostEqual(canonical, 102.5)
        self.assertNotAlmostEqual(legacy, canonical)

    def test_closed_bars_is_idempotent_under_closed_only(self) -> None:
        """Applying it twice is safe; ``.iloc[:-1]`` twice is not."""
        frame = simple_bars()
        once = closed_bars(frame, BarConvention.CLOSED_ONLY)
        twice = closed_bars(once, BarConvention.CLOSED_ONLY)
        self.assertEqual(len(frame), len(once))
        self.assertEqual(len(once), len(twice))

    def test_manual_double_drop_loses_a_real_bar(self) -> None:
        """What ``pullback_detector`` does: drop a forming bar that is not there."""
        frame = simple_bars()
        double_dropped = frame.iloc[:-1].iloc[:-1]
        self.assertEqual(len(frame) - len(double_dropped), 2)
        self.assertEqual(len(closed_bars(frame, BarConvention.CLOSED_ONLY)), len(frame))

    def test_includes_forming_removes_exactly_one_row(self) -> None:
        frame = simple_bars()
        self.assertEqual(
            len(closed_bars(frame, BarConvention.INCLUDES_FORMING)), len(frame) - 1
        )


class ValidationTests(unittest.TestCase):
    """Missing data raises rather than returning a silent ``None``."""

    def test_empty_frame_raises(self) -> None:
        empty = pd.DataFrame(columns=list(OHLC_COLUMNS))
        with self.assertRaises(InsufficientBarsError):
            last_closed_bar(empty)

    def test_single_bar_has_no_previous_closed_bar(self) -> None:
        frame = make_bars([(100.0, 101.0, 99.0, 100.5)])
        self.assertIsNotNone(last_closed_bar(frame))
        with self.assertRaises(InsufficientBarsError):
            previous_closed_bar(frame)

    def test_single_bar_frame_has_no_closed_bar_when_it_is_forming(self) -> None:
        frame = make_bars([(100.0, 101.0, 99.0, 100.5)])
        with self.assertRaises(InsufficientBarsError):
            last_closed_bar(frame, BarConvention.INCLUDES_FORMING)

    def test_missing_column_is_named_in_the_error(self) -> None:
        frame = simple_bars().drop(columns=["low"])
        with self.assertRaises(InsufficientBarsError) as ctx:
            last_closed_bar(frame)
        self.assertIn("low", str(ctx.exception))

    def test_non_dataframe_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            last_closed_bar([1, 2, 3])  # type: ignore[arg-type]

    def test_required_columns_can_be_narrowed(self) -> None:
        """Range-based indicators need H/L/C but not ``open``."""
        frame = simple_bars().drop(columns=["open"])
        self.assertFalse(has_ohlc_columns(frame, OHLC_COLUMNS))
        self.assertTrue(has_ohlc_columns(frame, HLC_COLUMNS))
        self.assertEqual(
            len(closed_bars(frame, BarConvention.CLOSED_ONLY, required_columns=HLC_COLUMNS)),
            len(frame),
        )


class ConventionMetadataTests(unittest.TestCase):
    """The enum itself carries the row arithmetic."""

    def test_forming_row_count(self) -> None:
        self.assertEqual(BarConvention.CLOSED_ONLY.forming_row_count, 0)
        self.assertEqual(BarConvention.INCLUDES_FORMING.forming_row_count, 1)

    def test_conventions_are_distinct(self) -> None:
        self.assertIsNot(BarConvention.CLOSED_ONLY, BarConvention.INCLUDES_FORMING)


if __name__ == "__main__":
    unittest.main()
