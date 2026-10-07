"""Ledger and metrics tests.

Covers P&L arithmetic, R-multiples, drawdown against a hand-computed equity
curve, and the empty-input edge cases that must not divide by zero or fabricate
a misleading ``0.0``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest.ledger import (
    SimulatedTrade,
    TradeLedger,
    TradeOutcome,
    trade_from_position,
)
from backtest.metrics import compute_metrics
from core.symbols import XAUUSD_2DIGIT
from core.types import Side
from execution.broker import FillStatus, PositionState, SimulatedFill, SimulatedPosition

UTC = timezone.utc
T0 = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


def make_position(
    *,
    side: Side = Side.BUY,
    entry: float = 2400.0,
    stop: float = 2390.0,
    target: float | None = 2420.0,
    exit_price: float = 2420.0,
    state: PositionState = PositionState.CLOSED_TARGET,
    volume: float = 0.01,
    ambiguous: bool = False,
) -> SimulatedPosition:
    """Build a closed position for ledger tests."""
    fill = SimulatedFill(
        status=FillStatus.FILLED, side=side, decision_time=T0,
        decision_bar_time=T0 - timedelta(minutes=5), signal_time=T0,
        entry_available_time=T0 + timedelta(minutes=5),
        entry_bar_time=T0 + timedelta(minutes=5),
        entry_price=entry, reference_price=entry, volume=volume,
    )
    return SimulatedPosition(
        position_id="SIM-000001", symbol="XAUUSD", side=side, volume=volume,
        entry_price=entry, stop_loss=stop, take_profit=target,
        entry_time=T0 + timedelta(minutes=5), state=state,
        exit_price=exit_price, exit_time=T0 + timedelta(minutes=30),
        exit_reason="test", was_ambiguous_exit=ambiguous, bars_held=5, fill=fill,
        metadata={"regime": "REGIME_SCALP", "setup_type": "PULLBACK"},
    )


class PnlArithmeticTests(unittest.TestCase):
    """P&L derives from the broker spec, never from ``risk_manager``."""

    def test_winning_buy(self) -> None:
        trade = trade_from_position(make_position(), XAUUSD_2DIGIT)
        # +$20 move * 0.01 lots * $100 per $1 per lot = $20
        self.assertAlmostEqual(trade.gross_pnl, 20.0)
        self.assertAlmostEqual(trade.net_pnl, 20.0)

    def test_losing_buy(self) -> None:
        trade = trade_from_position(
            make_position(exit_price=2390.0, state=PositionState.CLOSED_STOP),
            XAUUSD_2DIGIT,
        )
        self.assertAlmostEqual(trade.net_pnl, -10.0)

    def test_winning_sell(self) -> None:
        trade = trade_from_position(
            make_position(side=Side.SELL, stop=2410.0, target=2380.0, exit_price=2380.0),
            XAUUSD_2DIGIT,
        )
        self.assertAlmostEqual(trade.net_pnl, 20.0)

    def test_losing_sell(self) -> None:
        trade = trade_from_position(
            make_position(
                side=Side.SELL, stop=2410.0, target=2380.0,
                exit_price=2410.0, state=PositionState.CLOSED_STOP,
            ),
            XAUUSD_2DIGIT,
        )
        self.assertAlmostEqual(trade.net_pnl, -10.0)

    def test_r_multiple_is_size_independent(self) -> None:
        """The reason R is the primary metric: it survives the fixed-size choice."""
        small = trade_from_position(make_position(volume=0.01), XAUUSD_2DIGIT)
        large = trade_from_position(make_position(volume=1.00), XAUUSD_2DIGIT)
        self.assertAlmostEqual(small.r_multiple, 2.0)
        self.assertAlmostEqual(large.r_multiple, 2.0)
        self.assertNotAlmostEqual(small.net_pnl, large.net_pnl)

    def test_full_loss_is_minus_one_r(self) -> None:
        trade = trade_from_position(
            make_position(exit_price=2390.0, state=PositionState.CLOSED_STOP),
            XAUUSD_2DIGIT,
        )
        self.assertAlmostEqual(trade.r_multiple, -1.0)

    def test_commission_reduces_net_but_not_gross(self) -> None:
        trade = trade_from_position(make_position(), XAUUSD_2DIGIT, commission=1.5)
        self.assertAlmostEqual(trade.gross_pnl, 20.0)
        self.assertAlmostEqual(trade.net_pnl, 18.5)

    def test_risk_amount_uses_the_broker_spec(self) -> None:
        trade = trade_from_position(make_position(), XAUUSD_2DIGIT)
        self.assertAlmostEqual(trade.price_risk, 10.0)
        self.assertAlmostEqual(trade.risk_amount, 10.0)  # $10 risk on 0.01 lots

    def test_open_position_cannot_be_recorded(self) -> None:
        position = make_position()
        position.state = PositionState.OPEN
        with self.assertRaises(ValueError):
            trade_from_position(position, XAUUSD_2DIGIT)

    def test_timing_provenance_survives_into_the_ledger(self) -> None:
        trade = trade_from_position(make_position(), XAUUSD_2DIGIT)
        self.assertEqual(trade.decision_time, T0.isoformat())
        self.assertEqual(
            trade.entry_bar_time, (T0 + timedelta(minutes=5)).isoformat()
        )
        self.assertLess(trade.decision_bar_time, trade.entry_bar_time)


class OutcomeLabelTests(unittest.TestCase):
    """Labels come from the simulated future, never from judgement."""

    def test_states_map_to_outcomes(self) -> None:
        cases = {
            PositionState.CLOSED_STOP: TradeOutcome.STOPPED,
            PositionState.CLOSED_TARGET: TradeOutcome.TARGET_HIT,
            PositionState.CLOSED_TIME: TradeOutcome.TIME_EXIT,
            PositionState.CLOSED_END_OF_DATA: TradeOutcome.END_OF_DATA,
        }
        for state, expected in cases.items():
            with self.subTest(state=state.value):
                trade = trade_from_position(make_position(state=state), XAUUSD_2DIGIT)
                self.assertIs(trade.outcome_enum, expected)

    def test_end_of_data_is_not_a_completed_trade(self) -> None:
        self.assertFalse(TradeOutcome.END_OF_DATA.is_completed_trade)
        for outcome in (TradeOutcome.STOPPED, TradeOutcome.TARGET_HIT, TradeOutcome.TIME_EXIT):
            self.assertTrue(outcome.is_completed_trade)

    def test_end_of_data_is_excluded_from_statistics(self) -> None:
        trades = [
            trade_from_position(make_position(), XAUUSD_2DIGIT),
            trade_from_position(
                make_position(state=PositionState.CLOSED_END_OF_DATA), XAUUSD_2DIGIT
            ),
        ]
        metrics = compute_metrics(trades)
        self.assertEqual(metrics.total_trades, 2)
        self.assertEqual(metrics.completed_trades, 1)
        self.assertEqual(metrics.open_at_end, 1)


class MetricsTests(unittest.TestCase):
    """Descriptive statistics, checked against hand-computed values."""

    def _trades(self, pnls: list[float]) -> list[SimulatedTrade]:
        """Build trades with the given net P&L, each risking $10 (1R)."""
        result = []
        for index, pnl in enumerate(pnls):
            exit_price = 2400.0 + pnl / (XAUUSD_2DIGIT.money_per_price_unit(0.01))
            state = PositionState.CLOSED_TARGET if pnl > 0 else PositionState.CLOSED_STOP
            position = make_position(exit_price=exit_price, state=state)
            position.position_id = f"SIM-{index:06d}"
            result.append(trade_from_position(position, XAUUSD_2DIGIT))
        return result

    def test_win_rate_and_counts(self) -> None:
        metrics = compute_metrics(self._trades([20.0, -10.0, 20.0, -10.0]))
        self.assertEqual((metrics.wins, metrics.losses), (2, 2))
        self.assertAlmostEqual(metrics.win_rate, 0.5)

    def test_net_pnl_and_expectancy(self) -> None:
        metrics = compute_metrics(self._trades([20.0, -10.0, 20.0, -10.0]))
        self.assertAlmostEqual(metrics.net_pnl, 20.0)
        self.assertAlmostEqual(metrics.expectancy, 5.0)

    def test_average_win_and_loss(self) -> None:
        metrics = compute_metrics(self._trades([20.0, -10.0, 30.0, -20.0]))
        self.assertAlmostEqual(metrics.average_win, 25.0)
        self.assertAlmostEqual(metrics.average_loss, -15.0)

    def test_profit_factor(self) -> None:
        metrics = compute_metrics(self._trades([20.0, -10.0]))
        self.assertAlmostEqual(metrics.profit_factor, 2.0)

    def test_profit_factor_is_undefined_without_losses(self) -> None:
        """Undefined, not infinite -- an `inf` invites over-reading."""
        self.assertIsNone(compute_metrics(self._trades([20.0, 30.0])).profit_factor)

    def test_average_r(self) -> None:
        metrics = compute_metrics(self._trades([20.0, -10.0, 20.0, -10.0]))
        self.assertAlmostEqual(metrics.average_r, 0.5)  # (2 - 1 + 2 - 1) / 4

    def test_max_drawdown_against_a_hand_computed_curve(self) -> None:
        # Cumulative: 10, 0, -20, -10, 20. Peak 10, trough -20 -> drawdown 30.
        metrics = compute_metrics(self._trades([10.0, -10.0, -20.0, 10.0, 30.0]))
        self.assertAlmostEqual(metrics.max_drawdown, 30.0)

    def test_drawdown_is_zero_when_never_below_a_peak(self) -> None:
        self.assertAlmostEqual(compute_metrics(self._trades([10.0, 10.0])).max_drawdown, 0.0)

    def test_consecutive_runs(self) -> None:
        metrics = compute_metrics(
            self._trades([10.0, 10.0, 10.0, -10.0, -10.0, 10.0])
        )
        self.assertEqual(metrics.max_consecutive_wins, 3)
        self.assertEqual(metrics.max_consecutive_losses, 2)

    def test_empty_input_is_safe_and_honest(self) -> None:
        """No division by zero, and no fabricated 0.0 win rate."""
        metrics = compute_metrics([])
        self.assertEqual(metrics.completed_trades, 0)
        self.assertIsNone(metrics.win_rate)
        self.assertIsNone(metrics.expectancy)
        self.assertIsNone(metrics.profit_factor)
        self.assertAlmostEqual(metrics.max_drawdown, 0.0)

    def test_ambiguity_is_surfaced(self) -> None:
        trades = [
            trade_from_position(make_position(ambiguous=True), XAUUSD_2DIGIT),
            trade_from_position(make_position(ambiguous=False), XAUUSD_2DIGIT),
        ]
        metrics = compute_metrics(trades)
        self.assertEqual(metrics.ambiguous_exits, 1)
        self.assertAlmostEqual(metrics.ambiguous_exit_fraction, 0.5)

    def test_breakdowns_by_direction_and_regime(self) -> None:
        buy = trade_from_position(make_position(), XAUUSD_2DIGIT)
        sell = trade_from_position(
            make_position(side=Side.SELL, stop=2410.0, target=2380.0, exit_price=2380.0),
            XAUUSD_2DIGIT,
        )
        metrics = compute_metrics([buy, sell])
        self.assertEqual(metrics.by_direction, {"BUY": 1, "SELL": 1})
        self.assertEqual(metrics.by_regime, {"REGIME_SCALP": 2})
        self.assertEqual(metrics.by_setup, {"PULLBACK": 2})


class LedgerPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

    def test_jsonl_round_trip(self) -> None:
        ledger = TradeLedger()
        ledger.record(trade_from_position(make_position(), XAUUSD_2DIGIT))
        path = ledger.write_jsonl(self.directory / "out" / "trades.jsonl")
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["trade_id"], "SIM-000001")

    def test_fingerprint_is_stable_and_discriminating(self) -> None:
        first, second = TradeLedger(), TradeLedger()
        first.record(trade_from_position(make_position(), XAUUSD_2DIGIT))
        second.record(trade_from_position(make_position(), XAUUSD_2DIGIT))
        self.assertEqual(first.fingerprint(), second.fingerprint())
        second.record(trade_from_position(make_position(exit_price=2410.0), XAUUSD_2DIGIT))
        self.assertNotEqual(first.fingerprint(), second.fingerprint())

    def test_rejections_are_recorded(self) -> None:
        ledger = TradeLedger()
        ledger.record_rejection(
            decision_time=T0, side="BUY",
            outcome=TradeOutcome.REJECTED, reason="max open positions",
        )
        self.assertEqual(len(ledger.rejections), 1)
        self.assertEqual(ledger.rejections[0]["reason"], "max open positions")

    def test_ledger_never_writes_into_trade_states(self) -> None:
        """Simulated trades must not mix with production trade history.

        Checked over string literals in executable code only -- the module
        docstring legitimately mentions ``trade_states`` to explain why it is
        avoided, and a substring search would flag that.
        """
        import ast
        from pathlib import Path

        import backtest.ledger as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
        }
        offenders = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
            and "trade_states" in node.value
        ]
        self.assertEqual(offenders, [], f"ledger references production state: {offenders}")

    def test_ledger_writes_only_where_it_is_told(self) -> None:
        ledger = TradeLedger()
        ledger.record(trade_from_position(make_position(), XAUUSD_2DIGIT))
        target = self.directory / "results" / "trades.jsonl"
        self.assertEqual(ledger.write_jsonl(target), target)
        self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
