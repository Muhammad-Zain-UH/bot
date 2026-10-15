"""Tests for the scoped replay clock.

The patch is **temporary Phase 2A infrastructure**, so it must be provably
surgical: it applies only inside its context, restores unconditionally, and
changes nothing about how the strategy computes -- only which instant it reads.
"""

from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest.clock_patch import PATCHED_MODULES, build_frozen_datetime, frozen_clock

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]


class FrozenDateTimeTests(unittest.TestCase):
    """The substitute must behave like ``datetime`` in every respect but ``now``."""

    def setUp(self) -> None:
        self.instant = datetime(2024, 3, 6, 9, 30, tzinfo=UTC)
        self.frozen = build_frozen_datetime(self.instant)

    def test_now_returns_the_replay_instant(self) -> None:
        self.assertEqual(self.frozen.now(UTC), self.instant)

    def test_naive_now_matches_the_utc_reading(self) -> None:
        """Naive, but derived from UTC -- never from the host's local zone."""
        self.assertEqual(self.frozen.now(), self.instant.replace(tzinfo=None))

    def test_utcnow_and_today(self) -> None:
        self.assertEqual(self.frozen.utcnow(), self.instant.replace(tzinfo=None))
        self.assertEqual(self.frozen.today(), self.instant.replace(tzinfo=None))

    def test_it_is_still_a_datetime(self) -> None:
        self.assertTrue(issubclass(self.frozen, datetime))
        self.assertIsInstance(self.frozen.now(UTC), datetime)

    def test_construction_still_works(self) -> None:
        self.assertEqual(self.frozen(2020, 1, 2).year, 2020)

    def test_arithmetic_still_works(self) -> None:
        self.assertEqual(
            self.frozen.now(UTC) + timedelta(hours=1),
            self.instant + timedelta(hours=1),
        )

    def test_fromisoformat_still_works(self) -> None:
        self.assertEqual(self.frozen.fromisoformat("2021-06-01T00:00:00").year, 2021)

    def test_repeated_reads_are_identical(self) -> None:
        self.assertEqual(self.frozen.now(UTC), self.frozen.now(UTC))

    def test_naive_instant_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_frozen_datetime(datetime(2024, 3, 6, 9, 30))


class ScopeAndRestorationTests(unittest.TestCase):
    """The patch must not outlive its context, under any circumstance."""

    def setUp(self) -> None:
        import entry_engine
        import risk_manager

        self.risk_manager = risk_manager
        self.entry_engine = entry_engine
        self.original_rm = risk_manager.datetime
        self.original_ee = entry_engine.datetime

    def test_restored_on_normal_exit(self) -> None:
        with frozen_clock(datetime(2024, 3, 6, 9, 30, tzinfo=UTC)):
            self.assertIsNot(self.risk_manager.datetime, self.original_rm)
        self.assertIs(self.risk_manager.datetime, self.original_rm)
        self.assertIs(self.entry_engine.datetime, self.original_ee)

    def test_restored_after_an_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with frozen_clock(datetime(2024, 3, 6, 9, 30, tzinfo=UTC)):
                raise RuntimeError("boom")
        self.assertIs(self.risk_manager.datetime, self.original_rm)
        self.assertIs(self.entry_engine.datetime, self.original_ee)

    def test_nesting_unwinds_cleanly(self) -> None:
        outer = datetime(2024, 3, 6, 9, 30, tzinfo=UTC)
        inner = datetime(2024, 3, 6, 13, 30, tzinfo=UTC)
        with frozen_clock(outer):
            self.assertEqual(self.risk_manager.datetime.now(UTC), outer)
            with frozen_clock(inner):
                self.assertEqual(self.risk_manager.datetime.now(UTC), inner)
            self.assertEqual(self.risk_manager.datetime.now(UTC), outer)
        self.assertIs(self.risk_manager.datetime, self.original_rm)

    def test_unknown_module_is_skipped_not_fatal(self) -> None:
        with frozen_clock(
            datetime(2024, 3, 6, 9, 30, tzinfo=UTC),
            module_names=("definitely_not_a_module",),
        ):
            pass  # must not raise


class StrategyBehaviourUnderFrozenClockTests(unittest.TestCase):
    """The strategy's own rules must run unchanged, on the replayed instant."""

    def test_session_follows_replay_time(self) -> None:
        import risk_manager

        cases = {3: "Asian", 9: "London", 15: "NewYork", 23: "Dead"}
        for hour, expected in cases.items():
            with self.subTest(hour=hour):
                with frozen_clock(datetime(2024, 3, 6, hour, 0, tzinfo=UTC)):
                    self.assertEqual(risk_manager.get_current_session(), expected)

    def test_weekend_still_reports_closed(self) -> None:
        """Unmodified logic: Saturday is 'Closed' regardless of hour."""
        import risk_manager

        with frozen_clock(datetime(2024, 3, 9, 12, 0, tzinfo=UTC)):  # a Saturday
            self.assertEqual(risk_manager.get_current_session(), "Closed")

    def test_kill_zone_follows_replay_time(self) -> None:
        import entry_engine

        inside = datetime(2024, 3, 6, 9, 0, tzinfo=UTC)   # 08-10 window
        outside = datetime(2024, 3, 6, 17, 0, tzinfo=UTC)
        with frozen_clock(inside):
            self.assertTrue(entry_engine._within_kill_zone())
        with frozen_clock(outside):
            self.assertFalse(entry_engine._within_kill_zone())

    def test_two_different_instants_can_give_different_answers(self) -> None:
        """Confirms the patch is actually driving the result."""
        import risk_manager

        with frozen_clock(datetime(2024, 3, 6, 3, 0, tzinfo=UTC)):
            first = risk_manager.get_current_session()
        with frozen_clock(datetime(2024, 3, 6, 15, 0, tzinfo=UTC)):
            second = risk_manager.get_current_session()
        self.assertNotEqual(first, second)


class CoverageOfAmbientClockReadsTests(unittest.TestCase):
    """Every ambient clock read in the strategy path must be covered.

    Parses the strategy modules and asserts that any module containing a
    ``datetime.now()`` call reachable from the decision path is in
    :data:`PATCHED_MODULES`. A newly introduced read would fail this rather than
    silently reintroducing wall-clock dependence.
    """

    STRATEGY_MODULES = (
        "risk_manager", "entry_engine", "main_production", "bias_engine",
        "structure_engine", "liquidity_engine", "sweep_detector",
        "poi_engine", "confidence_engine", "indicators",
    )

    def _has_ambient_clock_call(self, path: Path) -> bool:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    if (node.func.value.id, node.func.attr) in {
                        ("datetime", "now"), ("datetime", "today"), ("datetime", "utcnow")
                    }:
                        return True
        return False

    def test_every_ambient_reader_is_patched(self) -> None:
        unpatched: list[str] = []
        for module in self.STRATEGY_MODULES:
            path = REPO_ROOT / f"{module}.py"
            if not path.is_file():
                continue
            if self._has_ambient_clock_call(path) and module not in PATCHED_MODULES:
                unpatched.append(module)
        self.assertEqual(
            unpatched, [],
            f"these strategy modules read the wall clock but are not patched "
            f"during replay: {unpatched}. Add them to PATCHED_MODULES.",
        )

    def test_patched_modules_actually_need_patching(self) -> None:
        """Keeps the list honest in the other direction too."""
        for module in PATCHED_MODULES:
            path = REPO_ROOT / f"{module}.py"
            with self.subTest(module=module):
                self.assertTrue(path.is_file())
                self.assertTrue(
                    self._has_ambient_clock_call(path),
                    f"{module} is patched but has no ambient clock read",
                )


if __name__ == "__main__":
    unittest.main()
