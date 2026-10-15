"""Dataset validation tests.

The policy under test: **corrupt data is reported, never repaired.** Silently
dropping a duplicate or clamping an impossible high would hide a data-quality
problem inside a backtest result, where it becomes indistinguishable from a
strategy effect.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core.types import Timeframe
from data.dataset import (
    BAR_COLUMNS,
    DataValidationError,
    HistoricalDataset,
    load_bars_csv,
    validate_bars,
)

UTC = timezone.utc
START = datetime(2026, 5, 4, tzinfo=UTC)


def make_frame(rows: int = 10, start: datetime = START, minutes: int = 1) -> pd.DataFrame:
    """Build a small valid bar frame."""
    times = [start + timedelta(minutes=minutes * i) for i in range(rows)]
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(times, utc=True),
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "tick_volume": [100.0] * rows,
        }
    )
    return frame


class ValidFrameTests(unittest.TestCase):
    def test_clean_frame_has_no_issues(self) -> None:
        self.assertEqual(validate_bars(make_frame(), Timeframe.M1), [])

    def test_dataset_accepts_clean_frames(self) -> None:
        dataset = HistoricalDataset("XAUUSD", {Timeframe.M1: make_frame()})
        self.assertEqual(len(dataset.frame(Timeframe.M1)), 10)


class RejectionTests(unittest.TestCase):
    """Every corruption class must be reported, with the offending row named."""

    def _kinds(self, frame: pd.DataFrame) -> set[str]:
        return {issue.kind for issue in validate_bars(frame, Timeframe.M1)}

    def test_duplicate_timestamp_rejected(self) -> None:
        frame = make_frame()
        frame.loc[5, "time"] = frame.loc[4, "time"]
        self.assertIn("duplicate_timestamp", self._kinds(frame))

    def test_duplicate_issue_names_the_row(self) -> None:
        frame = make_frame()
        frame.loc[5, "time"] = frame.loc[4, "time"]
        issues = [i for i in validate_bars(frame, Timeframe.M1) if i.kind == "duplicate_timestamp"]
        self.assertTrue(all(i.row_index is not None for i in issues))

    def test_non_monotonic_rejected(self) -> None:
        frame = make_frame()
        frame.loc[5, "time"] = frame.loc[1, "time"] - timedelta(minutes=1)
        self.assertIn("non_monotonic", self._kinds(frame))

    def test_high_below_low_rejected(self) -> None:
        frame = make_frame()
        frame.loc[3, "high"] = frame.loc[3, "low"] - 1.0
        self.assertIn("high_below_low", self._kinds(frame))

    def test_high_below_body_rejected(self) -> None:
        frame = make_frame()
        frame.loc[3, "high"] = frame.loc[3, "close"] - 0.5
        self.assertIn("high_below_body", self._kinds(frame))

    def test_low_above_body_rejected(self) -> None:
        frame = make_frame()
        frame.loc[3, "low"] = frame.loc[3, "open"] + 0.5
        self.assertIn("low_above_body", self._kinds(frame))

    def test_nan_rejected(self) -> None:
        frame = make_frame()
        frame.loc[3, "close"] = float("nan")
        self.assertIn("nan_ohlc", self._kinds(frame))

    def test_non_positive_price_rejected(self) -> None:
        frame = make_frame()
        frame.loc[3, "low"] = -1.0
        self.assertIn("non_positive_price", self._kinds(frame))

    def test_naive_timestamps_rejected(self) -> None:
        frame = make_frame()
        frame["time"] = frame["time"].dt.tz_localize(None)
        self.assertIn("naive_timestamps", self._kinds(frame))

    def test_missing_column_rejected(self) -> None:
        frame = make_frame().drop(columns=["low"])
        self.assertIn("missing_columns", self._kinds(frame))

    def test_empty_frame_rejected(self) -> None:
        empty = pd.DataFrame(columns=list(BAR_COLUMNS))
        self.assertIn("empty", self._kinds(empty))

    def test_dataset_construction_raises_on_corruption(self) -> None:
        frame = make_frame()
        frame.loc[5, "time"] = frame.loc[4, "time"]
        with self.assertRaises(DataValidationError):
            HistoricalDataset("XAUUSD", {Timeframe.M1: frame})

    def test_error_reports_all_issues_not_just_the_first(self) -> None:
        frame = make_frame()
        frame.loc[3, "high"] = frame.loc[3, "low"] - 1.0
        frame.loc[5, "close"] = float("nan")
        with self.assertRaises(DataValidationError) as ctx:
            HistoricalDataset("XAUUSD", {Timeframe.M1: frame})
        self.assertGreaterEqual(len(ctx.exception.issues), 2)

    def test_corrupt_data_is_never_silently_repaired(self) -> None:
        """A duplicate must raise, not be de-duplicated behind the caller's back."""
        frame = make_frame()
        frame.loc[5, "time"] = frame.loc[4, "time"]
        rows_before = len(frame)
        with self.assertRaises(DataValidationError):
            HistoricalDataset("XAUUSD", {Timeframe.M1: frame})
        self.assertEqual(len(frame), rows_before)


class CsvLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

    def test_round_trip(self) -> None:
        path = self.directory / "XAUUSD_M1.csv"
        make_frame().to_csv(path, index=False)
        loaded = load_bars_csv(path, Timeframe.M1)
        self.assertEqual(list(loaded.columns), list(BAR_COLUMNS))
        self.assertEqual(len(loaded), 10)
        self.assertIsNotNone(loaded["time"].dt.tz)

    def test_volume_column_alias_accepted(self) -> None:
        path = self.directory / "XAUUSD_M1.csv"
        make_frame().rename(columns={"tick_volume": "volume"}).to_csv(path, index=False)
        self.assertIn("tick_volume", load_bars_csv(path, Timeframe.M1).columns)

    def test_corrupt_csv_raises(self) -> None:
        frame = make_frame()
        frame.loc[3, "high"] = frame.loc[3, "low"] - 5.0
        path = self.directory / "XAUUSD_M1.csv"
        frame.to_csv(path, index=False)
        with self.assertRaises(DataValidationError):
            load_bars_csv(path, Timeframe.M1)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_bars_csv(self.directory / "nope.csv", Timeframe.M1)

    def test_from_directory_finds_files(self) -> None:
        make_frame().to_csv(self.directory / "XAUUSD_M1.csv", index=False)
        make_frame(minutes=5).to_csv(self.directory / "XAUUSD_M5.csv", index=False)
        dataset = HistoricalDataset.from_directory(self.directory, "XAUUSD")
        self.assertIn(Timeframe.M1, dataset.frames)
        self.assertIn(Timeframe.M5, dataset.frames)

    def test_from_directory_raises_when_empty(self) -> None:
        with self.assertRaises(FileNotFoundError):
            HistoricalDataset.from_directory(self.directory, "XAUUSD")


class CoverageTests(unittest.TestCase):
    def test_coverage_reports_bounds(self) -> None:
        dataset = HistoricalDataset("XAUUSD", {Timeframe.M1: make_frame(rows=5)})
        first, last = dataset.coverage(Timeframe.M1)
        self.assertEqual(first, pd.Timestamp(START))
        self.assertEqual(last, pd.Timestamp(START + timedelta(minutes=4)))

    def test_missing_timeframe_raises_with_a_helpful_message(self) -> None:
        dataset = HistoricalDataset("XAUUSD", {Timeframe.M1: make_frame()})
        with self.assertRaises(KeyError) as ctx:
            dataset.frame(Timeframe.H4)
        self.assertIn("M1", str(ctx.exception))

    def test_ensure_timeframes_derives_from_m1(self) -> None:
        dataset = HistoricalDataset("XAUUSD", {Timeframe.M1: make_frame(rows=300)})
        dataset.ensure_timeframes([Timeframe.M5])
        self.assertIn(Timeframe.M5, dataset.frames)
        self.assertIn(Timeframe.M5, dataset.derived)

    def test_ensure_timeframes_without_m1_raises(self) -> None:
        dataset = HistoricalDataset("XAUUSD", {Timeframe.M5: make_frame(minutes=5)})
        with self.assertRaises(KeyError):
            dataset.ensure_timeframes([Timeframe.H1])


if __name__ == "__main__":
    unittest.main()
