"""Structural guarantee that ``main_production.py`` cannot close a foreign position.

``graceful_shutdown()`` called ``mt5.positions_get(symbol=...)`` and then
``mt5.order_send()`` against **every** open position on the symbol, with no
ownership check and no safety guard. It runs on ``SIGINT``/``SIGTERM`` via
``signal_handler`` *and* on normal loop exit, and ``main_production.py`` has no
working opening path -- so every position it could have found belonged to
something else.

This was previously unreachable for an accidental reason: ``CONFIG["demo_mode"]``
was ``False``, which resolved to ``ExecutionMode.LIVE``, which
``validate_execution_environment`` refuses, so the process could not start.
Setting ``demo_mode = True`` so the bot can run in SIMULATION removed that
accident and turned the closer into a live hazard on every Ctrl-C. Hence this
guard, mirroring the one added to ``main.py`` for the same defect (Phase 6G R1).

Enforced by parsing the AST rather than by importing ``main_production``, which
builds a ``logging.FileHandler`` at module scope -- the mechanism that once put
four synthetic test entry signals into the permanent production log (see
``tests/__init__.py``).

The rules:

1. ``CLOSE_POSITIONS_ON_SHUTDOWN`` exists and is literally ``False``.
2. ``_OWNED_TICKETS`` exists as an empty set.
3. ``main_production.py`` imports ``core.safety.LIVE_TRADING_ENABLED``.
4. Inside ``graceful_shutdown``, the opt-in flag, the live-trading lock and the
   ownership set are all consulted **before** any ``order_send`` is reached.
5. The ownership test is a real ``not in _OWNED_TICKETS`` comparison.
6. ``graceful_shutdown`` still contains exactly one ``order_send``, so the rules
   above are not passing vacuously.
7. ``demo_mode`` is ``True``, so the process can start -- the change that made
   this guard necessary. If it is ever set back to ``False`` the guard is still
   required, so this asserts the gate exists rather than that it is unreachable.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "main_production.py"

GUARD_FLAG = "CLOSE_POSITIONS_ON_SHUTDOWN"
LOCK_NAME = "LIVE_TRADING_ENABLED"
OWNED_NAME = "_OWNED_TICKETS"


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"main_production.py no longer defines {name}()")


def _first_line_of_name(scope: ast.AST, name: str) -> int | None:
    lines = [
        n.lineno for n in ast.walk(scope)
        if isinstance(n, ast.Name) and n.id == name
    ]
    return min(lines) if lines else None


def _order_send_lines(scope: ast.AST) -> list[int]:
    return [
        n.lineno for n in ast.walk(scope)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "order_send"
    ]


class ShutdownFlagTests(unittest.TestCase):
    """Rules 1 and 2. Closing is opt-in and the default must stay off."""

    def test_flag_exists_and_defaults_to_false(self) -> None:
        found = False
        for node in _tree().body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == GUARD_FLAG:
                        found = True
                        self.assertIsInstance(node.value, ast.Constant)
                        self.assertIs(
                            node.value.value, False,
                            f"{GUARD_FLAG} must default to False",
                        )
        self.assertTrue(found, f"must define {GUARD_FLAG} at module level")

    def test_owned_tickets_set_exists(self) -> None:
        self.assertIn(
            f"{OWNED_NAME}: set[int] = set()",
            TARGET.read_text(encoding="utf-8"),
        )


class SafetyImportTests(unittest.TestCase):
    """Rule 3. The guard cannot read a lock it has not imported."""

    def test_imports_live_trading_enabled(self) -> None:
        imported: set[str] = set()
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "core.safety":
                imported.update(a.name for a in node.names)
        self.assertIn(LOCK_NAME, imported)


class GracefulShutdownGuardTests(unittest.TestCase):
    """Rules 4, 5 and 6. Every guard must be reached before any order."""

    def setUp(self) -> None:
        self.fn = _function(_tree(), "graceful_shutdown")
        self.sends = _order_send_lines(self.fn)

    def test_function_still_sends_orders_so_the_test_is_meaningful(self) -> None:
        """If the order_send disappeared, the guard tests would pass vacuously."""
        self.assertEqual(
            len(self.sends), 1,
            "expected exactly one order_send in graceful_shutdown; if the close "
            "path was removed or duplicated, revisit these guards",
        )

    def test_opt_in_flag_checked_before_any_order(self) -> None:
        line = _first_line_of_name(self.fn, GUARD_FLAG)
        self.assertIsNotNone(line, f"{GUARD_FLAG} is not consulted at all")
        self.assertLess(line, min(self.sends))

    def test_live_trading_lock_checked_before_any_order(self) -> None:
        line = _first_line_of_name(self.fn, LOCK_NAME)
        self.assertIsNotNone(line, f"{LOCK_NAME} is not consulted at all")
        self.assertLess(line, min(self.sends))

    def test_ownership_checked_before_any_order(self) -> None:
        line = _first_line_of_name(self.fn, OWNED_NAME)
        self.assertIsNotNone(line, f"{OWNED_NAME} is not consulted at all")
        self.assertLess(line, min(self.sends))

    def test_ownership_is_a_real_not_in_comparison(self) -> None:
        """A mention is not a guard -- require `... not in _OWNED_TICKETS`."""
        ok = False
        for node in ast.walk(self.fn):
            if isinstance(node, ast.Compare) and any(
                isinstance(o, ast.NotIn) for o in node.ops
            ):
                for cmp_node in node.comparators:
                    if isinstance(cmp_node, ast.Name) and cmp_node.id == OWNED_NAME:
                        ok = True
        self.assertTrue(
            ok, f"graceful_shutdown must skip tickets `not in {OWNED_NAME}`"
        )

    def test_positions_get_is_not_reached_before_the_guards(self) -> None:
        """Even enumerating positions should sit behind the opt-in, so a
        read-only call cannot be mistaken for permission to act."""
        calls = [
            n.lineno for n in ast.walk(self.fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "positions_get"
        ]
        self.assertTrue(calls, "expected a positions_get call to guard")
        self.assertLess(_first_line_of_name(self.fn, GUARD_FLAG), min(calls))


class StartupModeTests(unittest.TestCase):
    """Rule 7. Records why the guard became necessary."""

    def test_demo_mode_is_true_so_the_process_can_start(self) -> None:
        tree = _tree()
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "demo_mode"
                        and isinstance(value, ast.Constant)
                    ):
                        found = value.value
        self.assertIs(
            found, True,
            "CONFIG['demo_mode'] must be True: False resolves to "
            "ExecutionMode.LIVE, which validate_execution_environment always "
            "refuses, so the process cannot start at all",
        )


class SafetyConstantTests(unittest.TestCase):
    """core.safety is stdlib-only, so importing it is side-effect free."""

    def test_live_trading_remains_disabled(self) -> None:
        from core.safety import LIVE_TRADING_ENABLED as flag

        self.assertIs(flag, False)


if __name__ == "__main__":
    unittest.main()
