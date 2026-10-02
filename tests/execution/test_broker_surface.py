"""The broker-execution surface is inventoried, and cannot grow silently.

``tests/execution/test_no_live_execution.py`` proves the *simulation* packages
cannot reach a broker. It scans ``data/``, ``execution/``, ``backtest/`` and
``tools/`` -- and the Phase 6G audit found that every ``order_send`` in the
repository lives outside all four. The prohibition held exactly where it was
tested and was untested exactly where the calls were.

This module closes that gap: it scans **every production file**, matches each
mutating broker call against
:data:`tests.fixtures.broker_surface.APPROVED_BROKER_CALLS`, and fails when a
call appears that is not inventoried, when an inventoried call moves or
disappears, or when the guards recorded around one are gone.

The inventory is not a bypass. Nothing here weakens a guard, excludes a file or
adds an exception; the approved entries are approved *as legacy risks*, with
their status recorded, and the tests below assert that they remain exactly as
described rather than that they are acceptable.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.broker_surface import (
    APPROVED_BROKER_CALLS,
    APPROVED_MT5_IMPORTERS,
    MUTATING_PRIMITIVES,
    PRODUCTION_GLOBS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _production_files() -> list[Path]:
    """Every shipped Python file, excluding tests and vendored trees."""
    seen: dict[str, Path] = {}
    for pattern in PRODUCTION_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("tests/", "venv/", ".kilo/")):
                continue
            # Root-level ad-hoc test scripts are not shipped modules.
            if "/" not in rel and rel.startswith("test_"):
                continue
            seen[rel] = path
    return [seen[k] for k in sorted(seen)]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _enclosing_function(tree: ast.Module, lineno: int) -> str:
    """Name of the innermost function containing ``lineno``."""
    best: ast.AST | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            if node.lineno <= lineno <= end:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best is not None else "<module>"


def _function_source(tree: ast.Module, name: str, path: Path) -> str:
    """Source of one function, for checking that its guards survive."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])
    return ""


def _mutating_calls(path: Path) -> list[tuple[str, str, str, int]]:
    """Return ``(module, function, call, lineno)`` for every mutating call."""
    tree = _parse(path)
    rel = path.relative_to(REPO_ROOT).as_posix()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in MUTATING_PRIMITIVES:
            base = ast.unparse(func.value)
            found.append((rel, _enclosing_function(tree, node.lineno),
                          f"{base}.{func.attr}", node.lineno))
        elif isinstance(func, ast.Name) and func.id in MUTATING_PRIMITIVES:
            found.append((rel, _enclosing_function(tree, node.lineno),
                          func.id, node.lineno))
    return found


def _imports_metatrader5(path: Path) -> bool:
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "MetaTrader5" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "MetaTrader5":
                return True
    return False


class InventoryIsComplete(unittest.TestCase):
    """D: a new raw broker call cannot appear without updating the inventory."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = [c for p in _production_files() for c in _mutating_calls(p)]
        cls.approved = {s.key: s for s in APPROVED_BROKER_CALLS}

    def test_every_mutating_call_is_inventoried(self) -> None:
        unlisted = [c for c in self.observed if c[:3] not in self.approved]
        self.assertEqual(
            unlisted, [],
            "A broker call that can change account state is not in the "
            "inventory. Add it to tests/fixtures/broker_surface.py with its "
            "operation, lineage, guards and status -- do not exclude the file:\n"
            + "\n".join(f"  {m}:{ln} {fn}() -> {call}" for m, fn, call, ln in unlisted),
        )

    def test_every_inventoried_call_still_exists(self) -> None:
        """An approved call that vanished means the inventory is now fiction."""
        present = {c[:3] for c in self.observed}
        missing = sorted(k for k in self.approved if k not in present)
        self.assertEqual(
            missing, [],
            "An inventoried broker call is gone or has moved. If it was "
            "removed, delete its entry and record that in the audit; if it "
            "moved, update the entry: " + repr(missing),
        )

    def test_the_count_is_exactly_three(self) -> None:
        """Phase 6G counted three. A fourth is a material change."""
        self.assertEqual(len(self.observed), 3, sorted(self.observed))

    def test_only_two_can_actually_run(self) -> None:
        reachable = sorted(s.key for s in APPROVED_BROKER_CALLS if s.reachable)
        self.assertEqual(
            reachable,
            [("main.py", "close_all_positions", "mt5.order_send"),
             ("main_production.py", "graceful_shutdown", "mt5.order_send")],
        )


class SafetyContractsSurvive(unittest.TestCase):
    """An approved call whose guards disappeared is no longer the approved call."""

    def test_recorded_guards_are_still_present(self) -> None:
        for site in APPROVED_BROKER_CALLS:
            path = REPO_ROOT / site.module
            source = _function_source(_parse(path), site.function, path)
            with self.subTest(site=site.key):
                self.assertNotEqual(source, "", f"{site.function} not found")
                for guard in site.guards:
                    self.assertIn(
                        guard, source,
                        f"{site.module}:{site.function} no longer references "
                        f"{guard!r}; the safety contract recorded in the "
                        f"inventory has changed",
                    )

    def test_the_dead_open_path_is_still_dead(self) -> None:
        """Its deadness is structural, and the structure is asserted."""
        path = REPO_ROOT / "order_execution.py"
        self.assertFalse(
            _imports_metatrader5(path),
            "order_execution.py now imports MetaTrader5. It could previously "
            "only reach a broker through a handler its caller supplied, which "
            "is what made the send_order branch dead.",
        )
        # The sole production caller must still pass a literal None.
        tree = _parse(REPO_ROOT / "main_production.py")
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "execute_order"
        ]
        self.assertEqual(len(calls), 1, "expected exactly one execute_order call")
        handler = [k for k in calls[0].keywords if k.arg == "mt5_handler"]
        self.assertEqual(len(handler), 1, "execute_order must pass mt5_handler explicitly")
        self.assertIsInstance(handler[0].value, ast.Constant)
        self.assertIsNone(
            handler[0].value.value,
            "main_production now passes a handler to execute_order, which arms "
            "the unsized send_order branch",
        )


class MT5ImportersAreDeclared(unittest.TestCase):
    def test_no_undeclared_importer(self) -> None:
        importers = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in _production_files() if _imports_metatrader5(p)
        }
        undeclared = sorted(importers - set(APPROVED_MT5_IMPORTERS))
        self.assertEqual(
            undeclared, [],
            "A production module imports MetaTrader5 without being declared in "
            "APPROVED_MT5_IMPORTERS: " + repr(undeclared),
        )

    def test_declared_importers_still_import(self) -> None:
        importers = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in _production_files() if _imports_metatrader5(p)
        }
        stale = sorted(set(APPROVED_MT5_IMPORTERS) - importers)
        self.assertEqual(stale, [], f"declared importer no longer imports MT5: {stale}")

    def test_the_canonical_stack_is_not_among_them(self) -> None:
        """B: nothing the replay uses may import a broker."""
        for declared in APPROVED_MT5_IMPORTERS:
            self.assertFalse(
                declared.startswith(("core/", "data/", "execution/", "backtest/")),
                f"{declared} is in the canonical stack and must not import MT5",
            )


class HistoricalReplayCannotReachABroker(unittest.TestCase):
    """B: the backtest path has no route to broker execution."""

    def test_no_mutating_call_in_the_canonical_stack(self) -> None:
        offenders = []
        for package in ("core", "data", "execution", "backtest"):
            for path in sorted((REPO_ROOT / package).glob("*.py")):
                offenders.extend(_mutating_calls(path))
        self.assertEqual(offenders, [], f"canonical stack can mutate a broker: {offenders}")

    def test_the_replay_never_touches_the_legacy_executor(self) -> None:
        forbidden = ("OrderExecutor", "execute_order", "_OPEN_TRADES", "order_execution")
        for package in ("execution", "backtest"):
            for path in sorted((REPO_ROOT / package).glob("*.py")):
                source = path.read_text(encoding="utf-8")
                tree = _parse(path)
                names = {
                    n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                } | {
                    n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                }
                for token in forbidden:
                    with self.subTest(module=path.name, token=token):
                        self.assertNotIn(token, names, source[:0] or token)


class CanonicalEntryCannotBypassSizing(unittest.TestCase):
    """C: the one production entry path sizes through the canonical contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(REPO_ROOT / "main_production.py")
        cls.func = next(
            n for n in ast.walk(cls.tree)
            if isinstance(n, ast.FunctionDef) and n.name == "execute_entry_signal"
        )

    def test_it_calls_the_canonical_sizer(self) -> None:
        called = {
            n.func.id for n in ast.walk(self.func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertIn("calculate_lot_size_for_symbol", called)

    def test_it_supplies_a_specification_rather_than_assuming_one(self) -> None:
        call = next(
            n for n in ast.walk(self.func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "calculate_lot_size_for_symbol"
        )
        self.assertIn("spec", {k.arg for k in call.keywords})

    def test_no_second_sizing_formula_remains(self) -> None:
        """The removed fallback divided by a bare 100.0; nothing may again."""
        divisors = [
            ast.unparse(n.right) for n in ast.walk(self.func)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
        ]
        self.assertEqual(
            divisors, [],
            "execute_entry_signal contains division, which is how the second "
            f"conflicting sizing formula was written: {divisors}",
        )


class ImportingProductionArmsNothing(unittest.TestCase):
    """A: importing a production module must not arm a broker call.

    ``test_import_arms_nothing`` asserts this for ``main_production``. Phase 6G
    found it asserts nothing about ``main.py``, whose close path is the one with
    no ``core.safety`` gate at all.
    """

    PROBE = (
        "import json, signal, sys\n"
        "import {module}\n"
        "print(json.dumps({{\n"
        "  'sigint': signal.getsignal(signal.SIGINT) is signal.default_int_handler,\n"
        "  'sigterm_default': signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None),\n"
        "  'atexit': len(getattr(__import__('atexit'), '_exithandlers', []) or []),\n"
        "}}))\n"
    )

    def _probe(self, module: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            for key in ("TRADING_BOT_LOG_FILE", "TRADING_BOT_MAIN_LOG_FILE",
                        "SIGNAL_LOG_FILE", "MAIN_SIGNAL_LOG_FILE", "LOG_FILE"):
                env[key] = str(Path(tmp) / f"{key.lower()}.log")
            result = subprocess.run(
                [sys.executable, "-c", self.PROBE.format(module=module)],
                capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_importing_main_does_not_install_a_shutdown_handler(self) -> None:
        state = self._probe("main")
        self.assertTrue(
            state["sigint"],
            "importing main.py replaced the SIGINT handler, which would arm "
            "close_all_positions -- and therefore mt5.order_send -- for every "
            "process that imports it, including every backtest",
        )
        self.assertTrue(state["sigterm_default"])

    def test_importing_main_production_does_not_install_one(self) -> None:
        state = self._probe("main_production")
        self.assertTrue(state["sigint"])
        self.assertTrue(state["sigterm_default"])


class LegacyClosePathsAreVisible(unittest.TestCase):
    """E: the close-only legacy surface is declared, not accidentally invisible."""

    def test_both_close_paths_are_declared_legacy_and_reachable(self) -> None:
        closers = [s for s in APPROVED_BROKER_CALLS if s.operation == "CLOSE"]
        self.assertEqual(len(closers), 2)
        for site in closers:
            with self.subTest(module=site.module):
                self.assertEqual(site.lineage, "LEGACY")
                self.assertTrue(site.reachable)
                self.assertTrue(site.status.startswith("TEMPORARY"))

    def test_main_py_close_path_is_gated(self) -> None:
        """Phase 6G R1 is mitigated: main.py now imports the safety lock and
        will not close a position it did not open.

        This test previously asserted the OPPOSITE -- that the gap was unfixed --
        because the gap was deliberately recorded rather than patched. It is now
        inverted, and the architectural question it was protecting (item 2:
        is main.py a second entry point?) is asserted to still be open below.
        """
        source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("core.safety", source)
        self.assertIn("LIVE_TRADING_ENABLED", source)
        self.assertIn("CLOSE_POSITIONS_ON_SHUTDOWN = False", source)
        self.assertIn("_OWNED_TICKETS", source)
        site = next(s for s in APPROVED_BROKER_CALLS if s.module == "main.py")
        self.assertIn("now GATED", site.why)
        self.assertIn("R1 is MITIGATED", site.status)

    def test_main_py_entry_point_question_is_still_open(self) -> None:
        """Gating the close path must not quietly claim item 2 is decided."""
        site = next(s for s in APPROVED_BROKER_CALLS if s.module == "main.py")
        self.assertIn("REMAINS", site.status)
        self.assertIn("second entry point", site.status)

    def test_no_legacy_path_can_open_a_position_that_is_reachable(self) -> None:
        openers = [s for s in APPROVED_BROKER_CALLS if s.operation == "OPEN"]
        self.assertEqual(len(openers), 1)
        self.assertFalse(
            openers[0].reachable,
            "a reachable legacy open path would bypass canonical sizing and "
            "the canonical ledger",
        )

    def test_live_trading_is_still_disabled(self) -> None:
        from core.safety import LIVE_TRADING_ENABLED

        self.assertIs(LIVE_TRADING_ENABLED, False)


if __name__ == "__main__":
    unittest.main()
