"""Verifies that a test run cannot write into production trading data.

The Phase 1 audit found four fabricated ``ENTRY SIGNAL GENERATED`` records in
``trading_bot_production.log`` -- fixtures from ``tests/test_layer_gate_logic.py``
that reached the permanent record simply because importing the module under test
opened the production log for append.

That is not a tidiness problem. It put invented trade data into the only record
of what the system had done, and it is why the audit initially appeared to show
four entry signals when the real count was zero.

These tests are the regression guard.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import tests as tests_package

REPO_ROOT = Path(__file__).resolve().parents[2]


class EnvironmentRedirectionTests(unittest.TestCase):
    """Importing the test package must redirect every output path."""

    REDIRECTED_VARIABLES = (
        "TRADING_BOT_LOG_FILE",
        "TRADING_BOT_MAIN_LOG_FILE",
        "SIGNAL_LOG_FILE",
        "MAIN_SIGNAL_LOG_FILE",
        "LOG_FILE",
    )

    def test_every_output_variable_is_set(self) -> None:
        for variable in self.REDIRECTED_VARIABLES:
            with self.subTest(variable=variable):
                self.assertIsNotNone(
                    os.environ.get(variable),
                    f"{variable} must be redirected before any project module imports",
                )

    def test_every_output_path_is_inside_the_temporary_directory(self) -> None:
        temporary = Path(tests_package.TEST_OUTPUT_DIR).resolve()
        for variable in self.REDIRECTED_VARIABLES:
            with self.subTest(variable=variable):
                target = Path(os.environ[variable]).resolve()
                self.assertEqual(
                    target.parent,
                    temporary,
                    f"{variable} points outside the test output directory",
                )

    def test_no_output_path_is_inside_the_repository(self) -> None:
        for variable in self.REDIRECTED_VARIABLES:
            with self.subTest(variable=variable):
                target = Path(os.environ[variable]).resolve()
                self.assertFalse(
                    target.is_relative_to(REPO_ROOT),
                    f"{variable} would write into the repository at {target}",
                )


class ProductionArtifactTests(unittest.TestCase):
    """The production files themselves must be untouched by a test run."""

    def test_production_paths_are_not_targeted(self) -> None:
        targeted = {Path(os.environ[v]).name for v in EnvironmentRedirectionTests.REDIRECTED_VARIABLES}
        for production_name in tests_package.PRODUCTION_PATHS:
            with self.subTest(path=production_name):
                # A same-named file inside the temp dir is fine; what matters is
                # that nothing resolves to the repository copy.
                repository_copy = (REPO_ROOT / production_name).resolve()
                for variable in EnvironmentRedirectionTests.REDIRECTED_VARIABLES:
                    self.assertNotEqual(Path(os.environ[variable]).resolve(), repository_copy)
        self.assertTrue(targeted)

    def test_legacy_corrupt_signal_log_is_no_longer_in_the_repository_root(self) -> None:
        """It was archived during Phase 0 and must not be recreated."""
        self.assertFalse(
            (REPO_ROOT / "signal_log.csv").exists(),
            "signal_log.csv reappeared; it should live only under archive/",
        )

    def test_archived_legacy_log_is_still_present(self) -> None:
        archived = REPO_ROOT / "archive" / "2026-09-16_signal_log_legacy_mixed_schema.csv"
        self.assertTrue(archived.exists(), "the archived legacy log must be preserved")


class ImportSideEffectTests(unittest.TestCase):
    """Importing the production orchestrators must not write to production paths."""

    def test_importing_main_production_writes_only_to_the_temporary_directory(self) -> None:
        production_log = REPO_ROOT / "trading_bot_production.log"
        size_before = production_log.stat().st_size if production_log.exists() else None

        import main_production  # noqa: F401  (import IS the behaviour under test)

        self.assertEqual(
            Path(main_production.log_file_path).resolve().parent,
            Path(tests_package.TEST_OUTPUT_DIR).resolve(),
        )
        if size_before is not None:
            self.assertEqual(
                production_log.stat().st_size,
                size_before,
                "importing main_production appended to the production log",
            )

    def test_main_production_signal_log_is_redirected(self) -> None:
        import main_production

        self.assertEqual(
            Path(main_production._SIGNAL_LOG_FILE).resolve().parent,
            Path(tests_package.TEST_OUTPUT_DIR).resolve(),
        )


if __name__ == "__main__":
    unittest.main()
