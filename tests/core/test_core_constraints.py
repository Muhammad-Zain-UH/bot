"""Structural constraints on the ``core`` package.

These are architectural rules, enforced by parsing the source rather than by
convention. They use :mod:`ast` to inspect real import statements and real calls
-- a naive substring search would match prose in a docstring and produce both
false positives and false negatives.

The rules:

1. **No ``MetaTrader5`` import in ``core``.** ``core`` must be importable and
   testable on a machine with no broker terminal. Broker data enters through
   duck-typed adapters.
2. **No ``datetime.now()`` / ``datetime.today()`` / ``time.time()`` in ``core``,
   except inside ``core/clock.py``.** Time must be injectable, or the system
   cannot be replayed deterministically.
3. **No import cycles within ``core``.**
4. **No third-party dependency beyond what ``requirements.txt`` declares.**
   ``pydantic`` is installed in the virtualenv but undeclared, so importing it
   would create a dependency that does not survive a clean install.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / "core"

ALLOWED_THIRD_PARTY = {"pandas", "numpy"}
"""Third-party packages ``core`` may import. Both are declared in requirements.txt."""

STDLIB_PREFIXES = {
    "__future__", "abc", "ast", "atexit", "collections", "contextlib", "csv",
    "dataclasses", "datetime", "decimal", "enum", "functools", "io", "itertools",
    "json", "logging", "math", "os", "pathlib", "re", "shutil", "statistics",
    "sys", "tempfile", "time", "typing", "warnings", "zoneinfo",
}


def _core_modules() -> list[Path]:
    """Return every Python file in the ``core`` package."""
    return sorted(CORE_DIR.glob("*.py"))


def _parse(path: Path) -> ast.Module:
    """Parse a source file into an AST."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_roots(tree: ast.Module) -> set[str]:
    """Return the root package name of every import in ``tree``."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


class NoBrokerDependencyTests(unittest.TestCase):
    """Rule 1: ``core`` never imports MetaTrader5."""

    def test_core_never_imports_metatrader5(self) -> None:
        offenders = [
            path.name
            for path in _core_modules()
            if "MetaTrader5" in _imported_roots(_parse(path))
        ]
        self.assertEqual(
            offenders,
            [],
            f"core must not import MetaTrader5 (found in: {offenders}). "
            f"Broker data enters via duck-typed adapters such as "
            f"SymbolSpecification.from_mt5_symbol_info.",
        )

    def test_core_modules_all_import_cleanly(self) -> None:
        """Every core module must import without a broker terminal present."""
        import importlib

        for path in _core_modules():
            if path.name == "__init__.py":
                continue
            with self.subTest(module=path.stem):
                importlib.import_module(f"core.{path.stem}")


class NoAmbientClockTests(unittest.TestCase):
    """Rule 2: core logic never reads the wall clock directly."""

    FORBIDDEN = {("datetime", "now"), ("datetime", "today"), ("time", "time")}

    def _ambient_clock_calls(self, tree: ast.Module) -> list[str]:
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if (func.value.id, func.attr) in self.FORBIDDEN:
                    found.append(f"{func.value.id}.{func.attr}()")
        return found

    def test_only_clock_module_may_read_the_wall_clock(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in _core_modules():
            if path.name == "clock.py":
                continue  # the one module whose job this is
            calls = self._ambient_clock_calls(_parse(path))
            if calls:
                offenders[path.name] = calls
        self.assertEqual(
            offenders,
            {},
            f"core modules must obtain time through core.clock, not ambiently: "
            f"{offenders}",
        )

    def test_clock_module_does_read_the_wall_clock(self) -> None:
        """Guards against the rule above passing because the clock was gutted."""
        calls = self._ambient_clock_calls(_parse(CORE_DIR / "clock.py"))
        self.assertTrue(calls, "core/clock.py should be the module that reads real time")


class NoImportCyclesTests(unittest.TestCase):
    """Rule 3: the ``core`` dependency graph stays acyclic."""

    def _internal_graph(self) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {}
        module_names = {path.stem for path in _core_modules()}
        for path in _core_modules():
            tree = _parse(path)
            edges: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    parts = node.module.split(".")
                    if parts[0] == "core" and len(parts) > 1 and parts[1] in module_names:
                        edges.add(parts[1])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        if parts[0] == "core" and len(parts) > 1 and parts[1] in module_names:
                            edges.add(parts[1])
            edges.discard(path.stem)
            graph[path.stem] = edges
        return graph

    def test_no_cycles(self) -> None:
        graph = self._internal_graph()
        visiting: set[str] = set()
        done: set[str] = set()
        cycles: list[list[str]] = []

        def visit(node: str, path: list[str]) -> None:
            if node in done:
                return
            if node in visiting:
                cycles.append(path[path.index(node):] + [node])
                return
            visiting.add(node)
            for neighbour in sorted(graph.get(node, ())):
                visit(neighbour, path + [neighbour])
            visiting.discard(node)
            done.add(node)

        for module in sorted(graph):
            visit(module, [module])

        self.assertEqual(cycles, [], f"import cycle(s) in core: {cycles}")

    def test_init_reexports_nothing(self) -> None:
        """An empty ``__init__`` is what keeps the graph flat and predictable."""
        tree = _parse(CORE_DIR / "__init__.py")
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        non_future = [
            n for n in imports
            if not (isinstance(n, ast.ImportFrom) and n.module == "__future__")
        ]
        self.assertEqual(non_future, [], "core/__init__.py must not re-export submodules")


class NoUndeclaredDependencyTests(unittest.TestCase):
    """Rule 4: ``core`` imports only stdlib, declared third-party, or ``core``."""

    def test_only_declared_dependencies_are_imported(self) -> None:
        offenders: dict[str, set[str]] = {}
        for path in _core_modules():
            roots = _imported_roots(_parse(path))
            unexpected = {
                root
                for root in roots
                if root not in STDLIB_PREFIXES
                and root not in ALLOWED_THIRD_PARTY
                and root != "core"
            }
            if unexpected:
                offenders[path.name] = unexpected
        self.assertEqual(
            offenders,
            {},
            f"core imports undeclared dependencies: {offenders}. "
            f"Allowed third-party: {sorted(ALLOWED_THIRD_PARTY)}.",
        )

    def test_pydantic_is_not_used(self) -> None:
        """Installed in the venv but absent from requirements.txt."""
        for path in _core_modules():
            with self.subTest(module=path.name):
                self.assertNotIn("pydantic", _imported_roots(_parse(path)))


if __name__ == "__main__":
    unittest.main()
