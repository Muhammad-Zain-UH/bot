"""A written baseline must be immutable.

A baseline is the reference point later runs are compared against. If a rerun
could overwrite one in place, then "the baseline" would silently mean whatever
was measured most recently, and every comparison drawn against it afterwards
would be unfalsifiable. So ``write_artifacts`` refuses to touch a directory that
already exists, and that refusal is tested here rather than merely documented.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtest.baseline import BaselineArtifacts, write_artifacts
from backtest.ledger import TradeLedger
from backtest.metrics import compute_metrics


def _artifacts(baseline_id: str = "baseline_test") -> BaselineArtifacts:
    """Build an empty-but-valid artifacts object."""
    ledger = TradeLedger()
    return BaselineArtifacts(
        baseline_id=baseline_id,
        manifest={"baseline_id": baseline_id, "live_trading_enabled": False},
        dataset_manifest={"dataset_sha256": "0" * 64},
        metrics=compute_metrics([]),
        ledger=ledger,
        decision_statistics={"total_decisions": 0, "total_signals": 0},
        layer_funnel={"reached": {}, "blocked_at": {}},
        regime_statistics={"decisions_by_regime": {}},
        exit_statistics={"by_outcome": {}},
        defect_observations={},
        decisions_fingerprint="a" * 64,
        run_fingerprint="b" * 64,
        snapshots=[],
    )


class TestBaselinesAreImmutable(unittest.TestCase):
    """Writing over an existing baseline must fail, not succeed quietly."""

    def test_second_write_to_the_same_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_artifacts(_artifacts(), root)
            with self.assertRaises(FileExistsError):
                write_artifacts(_artifacts(), root)

    def test_the_original_survives_a_refused_overwrite(self) -> None:
        """The refusal must not have partially clobbered the first write."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = write_artifacts(_artifacts(), root)
            before = (directory / "run_fingerprint.txt").read_text(encoding="utf-8")

            second = _artifacts()
            second.run_fingerprint = "c" * 64
            with self.assertRaises(FileExistsError):
                write_artifacts(second, root)

            self.assertEqual(
                (directory / "run_fingerprint.txt").read_text(encoding="utf-8"), before
            )

    def test_a_new_id_writes_alongside_rather_than_replacing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = write_artifacts(_artifacts("baseline_001"), root)
            second = write_artifacts(_artifacts("baseline_002"), root)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())


class TestFingerprintFileRecordsBothDigests(unittest.TestCase):
    """``run_fingerprint`` alone cannot prove a zero-trade run repeated."""

    def test_decisions_fingerprint_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = write_artifacts(_artifacts(), Path(temp))
            text = (directory / "run_fingerprint.txt").read_text(encoding="utf-8")
            for key in ("run_fingerprint=", "dataset_sha256=", "decisions_fingerprint=", "ledger_fingerprint="):
                with self.subTest(key=key):
                    self.assertIn(key, text)

    def test_every_line_is_a_single_key_value_pair(self) -> None:
        """Guards against an escape sequence landing in the file literally."""
        with tempfile.TemporaryDirectory() as temp:
            directory = write_artifacts(_artifacts(), Path(temp))
            text = (directory / "run_fingerprint.txt").read_text(encoding="utf-8")
            lines = [line for line in text.splitlines() if line]
            self.assertEqual(len(lines), 4)
            for line in lines:
                with self.subTest(line=line):
                    self.assertEqual(line.count("="), 1)
                    key, value = line.split("=")
                    self.assertTrue(key and value)


class TestManifestRecordsTheSafetyState(unittest.TestCase):
    """A baseline must carry proof that live trading was off when it ran."""

    def test_manifest_is_written_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = write_artifacts(_artifacts(), Path(temp))
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["live_trading_enabled"], False)


if __name__ == "__main__":
    unittest.main()
