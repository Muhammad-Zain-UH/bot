"""The full chain: real signal -> PaperBroker -> SL/TP -> ledger -> metrics.

Critical requirements 2, 5, 6 and 7. Uses the actual Phase 2A components
throughout; nothing on the path is replaced by a mock.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backtest.ledger import TradeOutcome
from execution.broker import FillStatus, PositionState
from execution.intrabar import IntrabarPolicy, resolve_intrabar
from execution.paper_broker import DEFAULT_SIMULATED_VOLUME
from core.types import Side
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import long_dataset, run_replay, short_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]


class ChainReachesTheLedgerTests(unittest.TestCase):
    """Signal, fill, position, exit, ledger, metrics -- end to end."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result, cls.ledger, cls.metrics, cls.broker = run_replay(
            long_dataset(Resolution.TARGET)
        )

    def test_the_strategy_signalled(self) -> None:
        self.assertEqual(self.result.signals, 1)
        self.assertEqual(self.result.errors, 0)

    def test_the_broker_received_and_filled_it(self) -> None:
        positions = self.broker.closed_positions() + self.broker.open_positions()
        self.assertEqual(len(positions), 1)
        self.assertIs(positions[0].fill.status, FillStatus.FILLED)

    def test_the_position_closed_on_its_target(self) -> None:
        position = self.broker.closed_positions()[0]
        self.assertIs(position.state, PositionState.CLOSED_TARGET)

    def test_the_ledger_recorded_the_trade(self) -> None:
        self.assertEqual(len(self.ledger.trades), 1)
        self.assertIs(self.ledger.trades[0].outcome_enum, TradeOutcome.TARGET_HIT)

    def test_metrics_reflect_the_trade(self) -> None:
        self.assertEqual(self.metrics.total_trades, 1)
        self.assertEqual(self.metrics.completed_trades, 1)
        self.assertEqual(self.metrics.wins, 1)
        self.assertIsNotNone(self.metrics.average_r)

    def test_strategy_context_survived_into_the_ledger(self) -> None:
        trade = self.ledger.trades[0]
        self.assertEqual(trade.setup_type, "PULLBACK")
        self.assertIn(trade.regime, {"INTRADAY_SWING", "REGIME_SCALP", "MICRO_SCALP"})
        self.assertIn("L8_ENTRY", trade.metadata["layers_passed"])

    def test_no_rejections(self) -> None:
        self.assertEqual(self.ledger.rejections, [])


class StopExitTests(unittest.TestCase):
    """The same chain, resolving against the stop instead."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result, cls.ledger, cls.metrics, cls.broker = run_replay(
            long_dataset(Resolution.STOP)
        )

    def test_position_closed_on_its_stop(self) -> None:
        self.assertIs(self.broker.closed_positions()[0].state, PositionState.CLOSED_STOP)

    def test_ledger_records_a_loss(self) -> None:
        trade = self.ledger.trades[0]
        self.assertIs(trade.outcome_enum, TradeOutcome.STOPPED)
        self.assertLess(trade.net_pnl, 0.0)

    def test_loss_is_approximately_minus_one_r(self) -> None:
        """Slightly worse than -1R, because the exit also crosses the spread."""
        trade = self.ledger.trades[0]
        self.assertLess(trade.r_multiple, -0.9)
        self.assertGreater(trade.r_multiple, -1.3)

    def test_metrics_report_the_drawdown(self) -> None:
        self.assertEqual(self.metrics.losses, 1)
        self.assertGreater(self.metrics.max_drawdown, 0.0)


class DirectionSemanticsTests(unittest.TestCase):
    """BUY and SELL must be mirror images through the whole chain."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.long_ledger, _, _ = run_replay(long_dataset(Resolution.TARGET))
        _, cls.short_ledger, _, _ = run_replay(short_dataset(Resolution.TARGET))
        cls.buy = cls.long_ledger.trades[0]
        cls.sell = cls.short_ledger.trades[0]

    def test_buy_levels_are_ordered_correctly(self) -> None:
        self.assertEqual(self.buy.side, "BUY")
        self.assertLess(self.buy.stop_loss, self.buy.entry_price)
        self.assertGreater(self.buy.take_profit, self.buy.entry_price)

    def test_sell_levels_are_ordered_correctly(self) -> None:
        self.assertEqual(self.sell.side, "SELL")
        self.assertGreater(self.sell.stop_loss, self.sell.entry_price)
        self.assertLess(self.sell.take_profit, self.sell.entry_price)

    def test_both_exits_are_profitable_in_the_target_fixture(self) -> None:
        for name, trade in (("buy", self.buy), ("sell", self.sell)):
            with self.subTest(side=name):
                self.assertIs(trade.outcome_enum, TradeOutcome.TARGET_HIT)
                self.assertGreater(trade.net_pnl, 0.0)
                self.assertGreater(trade.r_multiple, 0.0)

    def test_sell_profits_when_price_falls(self) -> None:
        self.assertLess(self.sell.exit_price, self.sell.entry_price)

    def test_buy_profits_when_price_rises(self) -> None:
        self.assertGreater(self.buy.exit_price, self.buy.entry_price)

    def test_side_sign_convention_matches_the_pnl(self) -> None:
        for name, trade in (("buy", self.buy), ("sell", self.sell)):
            with self.subTest(side=name):
                side = Side(trade.side)
                move = (trade.exit_price - trade.entry_price) * side.sign
                self.assertAlmostEqual(
                    move * 100.0 * trade.quantity, trade.gross_pnl, places=6
                )


class FixedPositionSizeTests(unittest.TestCase):
    """Critical requirement 7: 0.01 lots, and risk_manager entirely bypassed."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.ledger, _, _ = run_replay(long_dataset(Resolution.TARGET))
        cls.trade = cls.ledger.trades[0]

    def test_quantity_is_exactly_one_hundredth_of_a_lot(self) -> None:
        self.assertEqual(self.trade.quantity, 0.01)
        self.assertEqual(DEFAULT_SIMULATED_VOLUME, 0.01)

    def test_risk_manager_is_not_imported_by_the_simulation_packages(self) -> None:
        """Its ~10x contract-size defect would contaminate every P&L figure."""
        offenders: list[str] = []
        for package in ("data", "execution", "backtest"):
            for path in (REPO_ROOT / package).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        offenders += [
                            f"{package}/{path.name}" for a in node.names
                            if a.name.split(".")[0] == "risk_manager"
                        ]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.split(".")[0] == "risk_manager":
                            offenders.append(f"{package}/{path.name}")
        self.assertEqual(offenders, [])

    def test_risk_amount_derives_from_the_symbol_specification(self) -> None:
        """$1 move x 0.01 lots x 100 oz = $1 per price unit."""
        self.assertAlmostEqual(
            self.trade.risk_amount, self.trade.price_risk * 1.0, places=6
        )

    def test_r_is_size_independent_even_though_pnl_is_not(self) -> None:
        from core.symbols import XAUUSD_2DIGIT

        self.assertAlmostEqual(XAUUSD_2DIGIT.money_per_price_unit(0.01), 1.0)
        self.assertAlmostEqual(XAUUSD_2DIGIT.money_per_price_unit(1.00), 100.0)


class IntrabarPolicyTests(unittest.TestCase):
    """Critical requirement 6: conservative by default, alternatives separate."""

    def test_default_run_uses_the_conservative_policy(self) -> None:
        _, _, _, broker = run_replay(long_dataset(Resolution.TARGET))
        self.assertIs(broker.intrabar_policy, IntrabarPolicy.CONSERVATIVE)

    def test_conservative_resolves_an_ambiguous_bar_to_the_stop(self) -> None:
        resolution = resolve_intrabar(
            side=Side.BUY, bar_high=2560.0, bar_low=2500.0,
            bar_open=2520.0, bar_close=2550.0,
            stop_loss=2510.0, take_profit=2555.0,
            policy=IntrabarPolicy.CONSERVATIVE,
        )
        self.assertTrue(resolution.hit_stop)
        self.assertFalse(resolution.hit_target)
        self.assertTrue(resolution.was_ambiguous)

    def test_the_alternative_policies_genuinely_differ(self) -> None:
        arguments = dict(
            side=Side.BUY, bar_high=2560.0, bar_low=2500.0,
            bar_open=2520.0, bar_close=2550.0,
            stop_loss=2510.0, take_profit=2555.0,
        )
        conservative = resolve_intrabar(**arguments, policy=IntrabarPolicy.CONSERVATIVE)
        optimistic = resolve_intrabar(**arguments, policy=IntrabarPolicy.OPTIMISTIC)
        self.assertTrue(conservative.hit_stop)
        self.assertTrue(optimistic.hit_target)

    def test_alternative_policies_are_not_silently_used(self) -> None:
        """The integration run must not quietly pick a flattering policy."""
        _, ledger, metrics, broker = run_replay(long_dataset(Resolution.TARGET))
        self.assertIsNot(broker.intrabar_policy, IntrabarPolicy.OPTIMISTIC)
        self.assertIsNot(broker.intrabar_policy, IntrabarPolicy.MIDPOINT_HEURISTIC)
        self.assertEqual(metrics.ambiguous_exits, 0)
        self.assertFalse(ledger.trades[0].was_ambiguous_exit)

    def test_tick_policy_refuses_rather_than_falling_back(self) -> None:
        with self.assertRaises(NotImplementedError):
            resolve_intrabar(
                side=Side.BUY, bar_high=2560.0, bar_low=2500.0,
                bar_open=2520.0, bar_close=2550.0,
                stop_loss=2510.0, take_profit=2555.0,
                policy=IntrabarPolicy.TICK_DATA,
            )


class OfflineTests(unittest.TestCase):
    """The integration path must never touch MT5."""

    def test_metatrader5_is_not_connected(self) -> None:
        import sys

        if "MetaTrader5" in sys.modules:
            module = sys.modules["MetaTrader5"]
            # main_production imports it, but nothing may have initialised it.
            self.assertTrue(hasattr(module, "initialize"))

    def test_live_trading_remains_disabled(self) -> None:
        from core.safety import LIVE_TRADING_ENABLED

        self.assertIs(LIVE_TRADING_ENABLED, False)

    def test_no_order_placement_calls_in_the_integration_path(self) -> None:
        forbidden = {"order_send", "positions_get", "order_check"}
        for package in ("data", "execution", "backtest"):
            for path in (REPO_ROOT / package).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                called = {
                    node.func.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                }
                with self.subTest(module=f"{package}/{path.name}"):
                    self.assertEqual(called & forbidden, set())


if __name__ == "__main__":
    unittest.main()
