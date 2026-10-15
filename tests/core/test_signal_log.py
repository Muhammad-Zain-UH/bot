"""Tests for the schema-versioned signal log.

The central case reproduces the live corruption: a file whose header describes a
different schema from the rows being appended to it. The legacy writer appended
regardless, producing 39,709 rows whose values do not match their column names.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from core.signal_log import (
    SCHEMA_VERSION_COLUMN,
    SIGNAL_LOG_COLUMNS,
    SIGNAL_LOG_SCHEMA_VERSION,
    SignalLogSchemaError,
    append_signal_row,
    ensure_signal_log,
    iter_signal_rows,
    read_header,
    rotate_mismatched_log,
)

LEGACY_77_COLUMN_HEADER = (
    "timestamp,symbol,session,signal,setup_direction,entry_timing_state,confidence,"
    "weighted_score,risk_level,ai_used,news_sentiment_score,news_alignment,"
    "dominant_theme,key_headline,geo_gold_bias,wyckoff_phase,outcome,actual_pnl_pips\n"
)
"""An abridged stand-in for the real legacy header. Shape is what matters."""


class TempLogTestCase(unittest.TestCase):
    """Base providing an isolated temporary directory per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.log_path = self.directory / "signal_log_v2.csv"


class SchemaDefinitionTests(TempLogTestCase):
    """The schema is explicit and versioned."""

    def test_version_is_stamped_on_every_row(self) -> None:
        append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})
        rows = list(iter_signal_rows(self.log_path))
        self.assertEqual(rows[0][SCHEMA_VERSION_COLUMN], str(SIGNAL_LOG_SCHEMA_VERSION))

    def test_version_column_is_first(self) -> None:
        self.assertEqual(SIGNAL_LOG_COLUMNS[0], SCHEMA_VERSION_COLUMN)

    def test_legacy_production_fields_are_preserved(self) -> None:
        """Phase 0 adds a version column and changes nothing else."""
        legacy = {
            "timestamp", "signal_type", "layers_passed", "layer_failed", "fail_reason",
            "l6_poi_type", "l6_poi_score", "entry_grade", "setup_type", "entry_method",
            "entry_mode", "trigger_type", "rr_valid", "entry_price", "stop_loss",
            "take_profit", "rr_ratio", "session", "position_type", "order_id",
        }
        self.assertEqual(set(SIGNAL_LOG_COLUMNS), legacy | {SCHEMA_VERSION_COLUMN})

    def test_caller_supplied_version_is_ignored(self) -> None:
        """A row cannot lie about which schema wrote it."""
        append_signal_row(self.log_path, {SCHEMA_VERSION_COLUMN: 999, "signal_type": "X"})
        rows = list(iter_signal_rows(self.log_path))
        self.assertEqual(rows[0][SCHEMA_VERSION_COLUMN], str(SIGNAL_LOG_SCHEMA_VERSION))


class CorruptionPreventionTests(TempLogTestCase):
    """The failure that produced the unusable legacy log."""

    def _write_legacy_file(self) -> None:
        self.log_path.write_text(
            LEGACY_77_COLUMN_HEADER + "2026-01-01,XAUUSD,LONDON,BUY,a,b,c,d,e,f,g,h,i,j,k,l,m,n\n",
            encoding="utf-8",
        )

    def test_mismatched_header_is_rotated_not_appended_to(self) -> None:
        self._write_legacy_file()
        append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})

        rotated = self.directory / "signal_log_v2.schema-mismatch.csv"
        self.assertTrue(rotated.exists(), "legacy file must be preserved, not discarded")
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)

    def test_rotated_file_retains_the_original_bytes(self) -> None:
        self._write_legacy_file()
        original = self.log_path.read_bytes()
        append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})
        rotated = self.directory / "signal_log_v2.schema-mismatch.csv"
        self.assertEqual(rotated.read_bytes(), original)

    def test_legacy_behaviour_would_have_corrupted_the_file(self) -> None:
        """Demonstrates what the old writer did, for contrast."""
        self._write_legacy_file()
        with self.log_path.open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(
                handle, fieldnames=["timestamp", "signal_type"], extrasaction="ignore"
            ).writerow({"timestamp": "2026-01-02", "signal_type": "PRE_ENTRY"})

        with self.log_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        # The field labelled 'symbol' now holds a signal type.
        self.assertEqual(rows[-1]["symbol"], "PRE_ENTRY")

    def test_repeated_rotations_do_not_clobber_each_other(self) -> None:
        for index in range(3):
            self.log_path.write_text(f"bad,header,{index}\n", encoding="utf-8")
            append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})
        rotated = sorted(p.name for p in self.directory.glob("*schema-mismatch*"))
        self.assertEqual(len(rotated), 3, f"expected 3 preserved files, got {rotated}")

    def test_strict_mode_raises_instead_of_rotating(self) -> None:
        self._write_legacy_file()
        with self.assertRaises(SignalLogSchemaError):
            ensure_signal_log(self.log_path, rotate_on_mismatch=False)
        self.assertTrue(self.log_path.exists())

    def test_reading_never_mutates_the_file(self) -> None:
        self._write_legacy_file()
        before = self.log_path.read_bytes()
        with self.assertRaises(SignalLogSchemaError):
            list(iter_signal_rows(self.log_path))
        self.assertEqual(self.log_path.read_bytes(), before)

    def test_header_is_verified_on_every_append_not_just_creation(self) -> None:
        """The legacy writer only checked at creation, which is why it drifted."""
        append_signal_row(self.log_path, {"signal_type": "A"})
        self.log_path.write_text("totally,different,header\n", encoding="utf-8")
        append_signal_row(self.log_path, {"signal_type": "B"})
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)


class RoundTripTests(TempLogTestCase):
    """Ordinary writing and reading."""

    def test_creates_file_with_header(self) -> None:
        ensure_signal_log(self.log_path)
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)

    def test_is_idempotent(self) -> None:
        ensure_signal_log(self.log_path)
        append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})
        ensure_signal_log(self.log_path)
        self.assertEqual(len(list(iter_signal_rows(self.log_path))), 1)

    def test_values_round_trip(self) -> None:
        row = {
            "timestamp": "2026-09-16T10:00:00",
            "signal_type": "PRE_ENTRY",
            "layers_passed": "L1_BIAS,L2_STRUCTURE",
            "layer_failed": "L3_PULLBACK",
            "fail_reason": "No confirmed pullback detected",
            "session": "LONDON",
        }
        append_signal_row(self.log_path, row)
        stored = list(iter_signal_rows(self.log_path))[0]
        for key, value in row.items():
            with self.subTest(field=key):
                self.assertEqual(stored[key], value)

    def test_missing_fields_are_written_empty(self) -> None:
        append_signal_row(self.log_path, {"signal_type": "PRE_ENTRY"})
        stored = list(iter_signal_rows(self.log_path))[0]
        self.assertEqual(stored["entry_price"], "")

    def test_unknown_fields_are_dropped(self) -> None:
        append_signal_row(self.log_path, {"signal_type": "X", "not_a_column": "y"})
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)
        self.assertNotIn("not_a_column", list(iter_signal_rows(self.log_path))[0])

    def test_embedded_commas_do_not_break_alignment(self) -> None:
        reason = "Confidence too low (52.1 < 55), regime MICRO_SCALP"
        append_signal_row(self.log_path, {"fail_reason": reason})
        self.assertEqual(list(iter_signal_rows(self.log_path))[0]["fail_reason"], reason)

    def test_appends_accumulate(self) -> None:
        for index in range(5):
            append_signal_row(self.log_path, {"signal_type": f"S{index}"})
        self.assertEqual(len(list(iter_signal_rows(self.log_path))), 5)

    def test_parent_directory_is_created(self) -> None:
        nested = self.directory / "a" / "b" / "signal.csv"
        append_signal_row(nested, {"signal_type": "PRE_ENTRY"})
        self.assertTrue(nested.exists())


class EdgeCaseTests(TempLogTestCase):
    """Absent, empty and unreadable files."""

    def test_missing_file_has_no_header(self) -> None:
        self.assertIsNone(read_header(self.directory / "nope.csv"))

    def test_empty_file_is_treated_as_new(self) -> None:
        self.log_path.write_text("", encoding="utf-8")
        ensure_signal_log(self.log_path)
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)

    def test_iterating_a_missing_file_yields_nothing(self) -> None:
        self.assertEqual(list(iter_signal_rows(self.directory / "nope.csv")), [])

    def test_rotating_a_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            rotate_mismatched_log(self.directory / "nope.csv")

    def test_header_whitespace_is_tolerated(self) -> None:
        self.log_path.write_text(
            ", ".join(SIGNAL_LOG_COLUMNS) + "\n", encoding="utf-8"
        )
        self.assertEqual(read_header(self.log_path), SIGNAL_LOG_COLUMNS)


if __name__ == "__main__":
    unittest.main()
