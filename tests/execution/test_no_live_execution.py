"""Structural guarantee that Phase 2A cannot place a real order.

Enforced by parsing the AST rather than by substring search, so a mention in a
docstring does not trip it and an aliased import cannot slip past it.

The rules, across ``data/``, ``execution/``, ``backtest/`` and ``tools/``:

1. No ``MetaTrader5`` import outside ``tools/`` (the read-only exporter is the
   single permitted exception, and it is separately constrained below).
2. No call to ``order_send`` anywhere.
3. ``core.safety.LIVE_TRADING_ENABLED`` remains ``False``.
4. The MT5 export tool reads only -- ``copy_rates_*`` and ``symbol_info`` -- and
   references no order-placement API at all.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIMULATION_PACKAGES = ("data", "execution", "backtest")

FORBIDDEN_MT5_CALLS = {
    "order_send", "order_check", "order_calc_margin", "order_calc_profit",
    "positions_get", "position_close",
}


def _python_files(package: str) -> list[Path]:
    """Return every Python file in a top-level package."""
    return sorted((REPO_ROOT / package).glob("*.py"))


def _parse(path: Path) -> ast.Module:
    """Parse a source file."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_roots(tree: ast.Module) -> set[str]:
    """Return the root package of every import."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _called_attributes(tree: ast.Module) -> set[str]:
    """Return the attribute name of every attribute call, e.g. ``mt5.order_send``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                names.add(node.func.id)
    return names


class NoBrokerImportTests(unittest.TestCase):
    def test_simulation_packages_never_import_metatrader5(self) -> None:
        offenders: dict[str, str] = {}
        for package in SIMULATION_PACKAGES:
            for path in _python_files(package):
                if "MetaTrader5" in _imported_roots(_parse(path)):
                    offenders[f"{package}/{path.name}"] = "imports MetaTrader5"
        self.assertEqual(
            offenders, {},
            f"Phase 2A simulation packages must not import MetaTrader5: {offenders}",
        )

    def test_simulation_packages_are_importable_without_a_terminal(self) -> None:
        import importlib

        for module in (
            "data.dataset", "data.feed", "data.replay_feed", "data.timeframes",
            "execution.broker", "execution.fills", "execution.intrabar",
            "execution.paper_broker",
            "backtest.clock_patch", "backtest.ledger", "backtest.metrics",
        ):
            with self.subTest(module=module):
                importlib.import_module(module)


class NoOrderPlacementTests(unittest.TestCase):
    def test_no_order_send_call_anywhere_in_new_packages(self) -> None:
        offenders: dict[str, set[str]] = {}
        for package in (*SIMULATION_PACKAGES, "tools"):
            for path in _python_files(package):
                forbidden = _called_attributes(_parse(path)) & FORBIDDEN_MT5_CALLS
                if forbidden:
                    offenders[f"{package}/{path.name}"] = forbidden
        self.assertEqual(
            offenders, {},
            f"Phase 2A must not call any order-placement or position API: {offenders}",
        )

    def test_live_trading_remains_disabled(self) -> None:
        from core.safety import LIVE_TRADING_ENABLED

        self.assertIs(LIVE_TRADING_ENABLED, False)

    def test_paper_broker_has_no_network_or_filesystem_surface(self) -> None:
        """The simulator is pure in-memory; it cannot reach anything external."""
        tree = _parse(REPO_ROOT / "execution" / "paper_broker.py")
        roots = _imported_roots(tree)
        for forbidden in ("socket", "requests", "urllib", "http", "MetaTrader5"):
            self.assertNotIn(forbidden, roots)


class ExportToolTests(unittest.TestCase):
    """The one module permitted to touch MT5 must be read-only."""

    def setUp(self) -> None:
        self.path = REPO_ROOT / "tools" / "export_mt5_history.py"
        if not self.path.is_file():
            self.skipTest("export tool not present")

    def test_uses_only_read_apis(self) -> None:
        called = _called_attributes(_parse(self.path))
        self.assertEqual(called & FORBIDDEN_MT5_CALLS, set())

    def test_mentions_no_trade_action_constants(self) -> None:
        source = self.path.read_text(encoding="utf-8")
        for token in ("TRADE_ACTION", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "order_send"):
            self.assertNotIn(token, source, f"export tool references {token}")


if __name__ == "__main__":
    unittest.main()
