"""Structural guarantee that ``main.py`` cannot close a position it did not open.

Before this guard, ``main.close_all_positions()`` fired ``mt5.order_send``
against **every** open position on the symbol -- and ``main.py`` has no opening
path, so every position it could have found belonged to something else. It ran
on ``Ctrl-C`` (``signal_handler``) *and* on normal loop exit, and ``main.py`` did
not even import ``core.safety``.

Enforced by parsing the AST rather than by importing ``main``, matching
``test_no_live_execution.py``. Importing ``main`` would run ``logging.basicConfig``
and open the production log files as a side effect, which is exactly why no test
in this suite imports it.

The rules:

1. ``main.py`` imports ``core.safety`` -- the omission was the root cause.
2. ``CLOSE_POSITIONS_ON_SHUTDOWN`` exists and is literally ``False``.
3. Inside ``close_all_positions``, the opt-in flag, the live-trading lock and the
   ownership set are all consulted **before** any ``order_send`` is reached.
4. The ownership test is a real ``not in _OWNED_TICKETS`` comparison.
5. ``main()`` calls ``assert_live_trading_disabled()`` as a startup tripwire.
6. ``main.py`` still has no *opening* order: every ``order_send`` payload it
   builds carries a ``position`` key, i.e. it is a close.
7. ``core.safety.LIVE_TRADING_ENABLED`` remains ``False``.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"

GUARD_FLAG = "CLOSE_POSITIONS_ON_SHUTDOWN"
LOCK_NAME = "LIVE_TRADING_ENABLED"
OWNED_NAME = "_OWNED_TICKETS"
TRIPWIRE = "assert_live_trading_disabled"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"main.py no longer defines {name}()")


def _first_line_of_name(scope: ast.AST, name: str) -> int | None:
    """Lowest line number at which `name` is referenced inside `scope`."""
    lines = [n.lineno for n in ast.walk(scope)
             if isinstance(n, ast.Name) and n.id == name]
    return min(lines) if lines else None


def _order_send_lines(scope: ast.AST) -> list[int]:
    out = []
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "order_send":
            out.append(n.lineno)
    return out


class MainImportsSafetyTests(unittest.TestCase):
    """Rule 1. The missing import was the root cause of the hazard."""

    def test_main_imports_core_safety(self) -> None:
        tree = _tree()
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "core.safety":
                imported.update(a.name for a in node.names)
        self.assertIn(
            LOCK_NAME, imported,
            "main.py must import core.safety.LIVE_TRADING_ENABLED; its absence is "
            "why close_all_positions() was unguarded",
        )
        self.assertIn(TRIPWIRE, imported)


class ShutdownFlagTests(unittest.TestCase):
    """Rule 2. Closing is opt-in, and the default must stay off."""

    def test_flag_exists_and_defaults_to_false(self) -> None:
        tree = _tree()
        found = False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == GUARD_FLAG:
                        found = True
                        self.assertIsInstance(node.value, ast.Constant)
                        self.assertIs(
                            node.value.value, False,
                            f"{GUARD_FLAG} must default to False",
                        )
        self.assertTrue(found, f"main.py must define {GUARD_FLAG} at module level")

    def test_owned_tickets_set_exists(self) -> None:
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn(f"{OWNED_NAME}: set[int] = set()", src)


class ClosePositionsGuardTests(unittest.TestCase):
    """Rules 3 and 4. Every guard must be reached before any order."""

    def setUp(self) -> None:
        self.fn = _function(_tree(), "close_all_positions")
        self.sends = _order_send_lines(self.fn)

    def test_function_still_sends_orders_so_the_test_is_meaningful(self) -> None:
        """If the order_send disappeared, the guard tests below would pass
        vacuously. Assert the thing being guarded is still there."""
        self.assertEqual(
            len(self.sends), 1,
            "expected exactly one order_send in close_all_positions; if the close "
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
            ok,
            f"close_all_positions must skip tickets with `not in {OWNED_NAME}`",
        )

    def test_guards_return_early(self) -> None:
        """Each guard must return, not merely log."""
        returns = [n for n in ast.walk(self.fn) if isinstance(n, ast.Return)]
        before = [r for r in returns if r.lineno < min(self.sends)]
        self.assertGreaterEqual(
            len(before), 4,
            "expected at least four early returns (opt-in, live lock, MT5 "
            "availability, empty ownership set) before the order path",
        )


class StartupTripwireTests(unittest.TestCase):
    """Rule 5. Mirrors main_production.py's startup refusal."""

    def test_main_calls_assert_live_trading_disabled(self) -> None:
        fn = _function(_tree(), "main")
        called = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == TRIPWIRE
        ]
        self.assertTrue(called, f"main() must call {TRIPWIRE}() before connecting")


class NoOpeningOrderTests(unittest.TestCase):
    """Rule 6. main.py must remain unable to OPEN a position."""

    def test_every_order_send_payload_is_a_close(self) -> None:
        tree = _tree()
        payload_keys: list[set[str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                keys = {k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if "action" in keys and "symbol" in keys:
                    payload_keys.append(keys)
        self.assertTrue(payload_keys, "no order payload found in main.py")
        for keys in payload_keys:
            self.assertIn(
                "position", keys,
                "an order payload without a `position` key would be an OPENING "
                "order; main.py must only ever close",
            )


class SafetyConstantTests(unittest.TestCase):
    """Rule 7. core.safety is stdlib-only, so importing it is side-effect free."""

    def test_live_trading_remains_disabled(self) -> None:
        from core.safety import LIVE_TRADING_ENABLED

        self.assertIs(LIVE_TRADING_ENABLED, False)


if __name__ == "__main__":
    unittest.main()
