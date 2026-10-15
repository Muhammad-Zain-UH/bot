"""The account-level risk gate must actually be wired into production.

``core/risk_limits.py`` is tested on its own in ``tests/core/test_risk_limits.py``.
This file tests the thing that was actually broken: not the logic, but whether
anything *called* it. Every defect below was a correct-looking gate that no
caller ever supplied with real inputs.

* ``check_pre_trade_gates(account_balance=10000, current_daily_loss=0)`` was
  called as ``check_pre_trade_gates(regime_info=...)``. Both risk arguments took
  their defaults on all 39,709 production cycles, so the breaker evaluated
  ``0 < -500`` and reported "Daily loss OK (0.00 / 500.00)" forever. (R2, R3)
* The spread branch computed ``max_spread`` and ``current_spread`` and then
  compared nothing -- its body was the comment ``# DISABLED SPREAD CHECK``
  followed by an unconditional pass.
* ``execute_entry_signal`` defaulted ``account_balance`` to ``10000`` and its
  only caller passed nothing, so every position was sized against a fictional
  account. (R2)
* Closed trades were dropped from ``_OPEN_TRADES`` with no P&L computed and
  ``save_closed_trade`` never called, so the breaker had no source. (R4)

These tests import ``main_production``, which is safe because ``tests/__init__``
redirects its log and datastore paths to a temporary directory before any
project module loads.
"""

from __future__ import annotations

import inspect
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import main_production as mp
from core.risk_limits import (
    AccountRiskState,
    RiskDecision,
    RiskVerdict,
)
from core.symbols import XAUUSD_2DIGIT


def allow(headroom: float = 0.10) -> RiskDecision:
    return RiskDecision(RiskVerdict.ALLOW, (), headroom)


def healthy_state(**overrides) -> AccountRiskState:
    base = dict(
        balance=10000.0, equity=10000.0, day_opening_balance=10000.0,
        peak_equity=10000.0, realised_pnl_today=0.0, consecutive_losses=0,
        open_positions=0, open_lots=0.0, trading_day=date(2026, 10, 5),
    )
    base.update(overrides)
    return AccountRiskState(**base)


class TheDefaultsAreGoneTests(unittest.TestCase):
    """R2/R3. A defaulted risk input is an assertion the function cannot make."""

    def test_gate_no_longer_accepts_a_defaulted_daily_loss(self) -> None:
        params = inspect.signature(mp.check_pre_trade_gates).parameters
        self.assertNotIn(
            "current_daily_loss", params,
            "current_daily_loss=0 asserted the account had lost nothing, from a "
            "function with no access to the account",
        )
        self.assertNotIn("account_balance", params)

    def test_entry_balance_no_longer_defaults_to_a_number(self) -> None:
        default = inspect.signature(mp.execute_entry_signal).parameters[
            "account_balance"
        ].default
        self.assertIsNone(
            default,
            "account_balance must default to None, not to a balance. 10000 made "
            "every risk figure in the system fictional.",
        )

    def test_entry_declines_without_a_balance(self) -> None:
        signal = {"entry_price": 4000.0, "stop_loss": 3990.0,
                  "take_profit": 4020.0, "position_type": "BUY"}
        with patch.object(mp, "order_executor", object()):
            self.assertIsNone(mp.execute_entry_signal(signal, account_balance=None))


class GateFailsClosedTests(unittest.TestCase):
    """Unknown state must block. This is the inversion that matters."""

    def test_unavailable_account_state_halts(self) -> None:
        with patch.object(mp, "account_risk_state", return_value=None):
            result = mp.check_pre_trade_gates(
                {"max_spread_pips": 7.0, "current_spread": 2.0})
        self.assertFalse(result["all_gates_passed"])
        self.assertEqual(result["risk_verdict"], RiskVerdict.HALT.value)

    def test_bare_call_blocks_rather_than_passing(self) -> None:
        """The exact call production made. It used to pass unconditionally."""
        with patch.object(mp, "account_risk_state", return_value=None):
            self.assertFalse(mp.check_pre_trade_gates()["all_gates_passed"])

    def test_missing_risk_limits_blocks(self) -> None:
        with patch.object(mp, "RISK_LIMITS", None):
            result = mp.check_pre_trade_gates(
                {"max_spread_pips": 7.0, "current_spread": 2.0})
        self.assertFalse(result["all_gates_passed"])
        self.assertEqual(result["risk_verdict"], RiskVerdict.HALT.value)

    def test_healthy_account_is_allowed(self) -> None:
        """The gate must not be unconditionally closed either, or it proves
        nothing about the checks above."""
        with patch.object(mp, "account_risk_state", return_value=healthy_state()):
            result = mp.check_pre_trade_gates(
                {"max_spread_pips": 7.0, "current_spread": 2.0})
        self.assertEqual(result["risk_verdict"], RiskVerdict.ALLOW.value)
        self.assertGreater(result["max_new_lots"], 0.0)


class DailyLossBreakerActuallyFiresTests(unittest.TestCase):
    """R3. The breaker that evaluated `0 < -500` for 39,709 cycles."""

    def test_a_losing_day_blocks_new_entries(self) -> None:
        loss = -(10000.0 * mp.RISK_LIMITS.max_daily_loss.as_fraction()) - 1.0
        state = healthy_state(realised_pnl_today=loss,
                              balance=10000.0 + loss, equity=10000.0 + loss)
        with patch.object(mp, "account_risk_state", return_value=state):
            result = mp.check_pre_trade_gates(
                {"max_spread_pips": 7.0, "current_spread": 2.0})
        self.assertFalse(result["all_gates_passed"])
        self.assertTrue(any("DAILY LOSS" in g for g in result["gates_failed"]))

    def test_drawdown_breach_halts_not_merely_blocks(self) -> None:
        state = healthy_state(equity=8000.0, peak_equity=10000.0, balance=8000.0)
        with patch.object(mp, "account_risk_state", return_value=state):
            result = mp.check_pre_trade_gates(
                {"max_spread_pips": 7.0, "current_spread": 2.0})
        self.assertEqual(result["risk_verdict"], RiskVerdict.HALT.value)


class SpreadCheckIsLiveTests(unittest.TestCase):
    """The branch whose body was `# DISABLED SPREAD CHECK`."""

    def test_excessive_spread_blocks(self) -> None:
        result = mp.check_pre_trade_gates(
            {"max_spread_pips": 5.0, "current_spread": 9.0}, risk=allow())
        self.assertFalse(result["all_gates_passed"])
        self.assertTrue(any("SPREAD" in g for g in result["gates_failed"]))

    def test_acceptable_spread_passes(self) -> None:
        result = mp.check_pre_trade_gates(
            {"max_spread_pips": 7.0, "current_spread": 2.0}, risk=allow())
        self.assertTrue(any("Spread OK" in g for g in result["gates_passed"]))

    def test_unknown_spread_blocks_rather_than_assuming_tight(self) -> None:
        """The old code defaulted to 0.5 pip, asserting a tight market on no
        evidence."""
        result = mp.check_pre_trade_gates({"max_spread_pips": 5.0}, risk=allow())
        self.assertFalse(result["all_gates_passed"])
        self.assertTrue(
            any("SPREAD UNKNOWN" in g for g in result["gates_failed"]))

    def test_no_regime_info_blocks(self) -> None:
        result = mp.check_pre_trade_gates(None, risk=allow())
        self.assertFalse(result["all_gates_passed"])

    def test_the_spread_values_are_actually_compared(self) -> None:
        """Structural, not textual. The original defect was that both figures
        were computed and then *nothing compared them*, so a text search for a
        marker string proves nothing -- and would match this file's own comments
        describing the defect. Assert the AST contains a real comparison whose
        operands are the two spread names.
        """
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(mp.check_pre_trade_gates)))
        names = {"current_spread", "max_spread"}
        compared = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            found = set()
            for operand in operands:
                for inner in ast.walk(operand):
                    if isinstance(inner, ast.Name) and inner.id in names:
                        found.add(inner.id)
            if found == names:
                compared = True
        self.assertTrue(
            compared,
            "check_pre_trade_gates must contain a comparison between "
            "current_spread and max_spread; computing both and comparing "
            "neither is the original defect",
        )


class ExposureCapIsAppliedTests(unittest.TestCase):
    """R6/R8. core.sizing caps at the BROKER's volume_max, not ours."""

    def _signal(self):
        return {"entry_price": 4000.0, "stop_loss": 3999.0,
                "take_profit": 4020.0, "position_type": "BUY",
                "risk_percent": 100.0}

    def test_size_is_capped_to_the_headroom(self) -> None:
        captured = {}

        class FakeExecutor:
            def create_order(self, **kw):
                captured.update(kw)
                return {"order_id": "X", "entry_price": kw["entry_price"],
                        "stop_loss": kw["stop_loss"],
                        "take_profit": kw["take_profit"],
                        "position_size": kw["position_size"],
                        "order_type": "BUY"}

            def execute_order(self, *a, **k):
                return False, "simulated: not executed"

        with patch.object(mp, "order_executor", FakeExecutor()), \
                patch.object(mp, "_live_symbol_specification",
                             return_value=XAUUSD_2DIGIT):
            mp.execute_entry_signal(self._signal(), account_balance=1_000_000.0,
                                    max_lots=0.05)

        self.assertIn("position_size", captured)
        self.assertLessEqual(
            captured["position_size"], 0.05,
            "a 100% risk budget on a $1m account must still be capped by the "
            "account exposure limit",
        )


class RealisedPnlIsRecordedTests(unittest.TestCase):
    """R4. Nothing tracked realised P&L, so the breaker had no source."""

    def _trade(self, side="BUY"):
        return {"trade_id": "t1", "entry_price": 4000.0, "position_size": 0.01,
                "position_type": side, "order_id": "o1"}

    def test_pnl_signs_are_correct_for_both_sides(self) -> None:
        spec = XAUUSD_2DIGIT
        self.assertAlmostEqual(
            mp.realised_pnl(self._trade("BUY"), 4010.0, spec), 10.0)
        self.assertAlmostEqual(
            mp.realised_pnl(self._trade("BUY"), 3990.0, spec), -10.0)
        self.assertAlmostEqual(
            mp.realised_pnl(self._trade("SELL"), 3990.0, spec), 10.0)
        self.assertAlmostEqual(
            mp.realised_pnl(self._trade("SELL"), 4010.0, spec), -10.0)

    def test_unknown_side_is_none_not_zero(self) -> None:
        """Zero would be a claim that the trade broke even."""
        self.assertIsNone(
            mp.realised_pnl(self._trade("SIDEWAYS"), 4010.0, XAUUSD_2DIGIT))

    def test_missing_specification_is_none_not_zero(self) -> None:
        with patch.object(mp, "_live_symbol_specification", return_value=None):
            self.assertIsNone(mp.realised_pnl(self._trade(), 4010.0))

    def test_record_close_stamps_pnl_and_exit_fields(self) -> None:
        trade = self._trade()
        with patch.object(mp, "_live_symbol_specification",
                          return_value=XAUUSD_2DIGIT), \
                patch.object(mp, "PERSISTENCE_AVAILABLE", False), \
                patch.object(mp, "LAYERS_AVAILABLE", False):
            mp._record_close(trade, 4010.0, "CLOSE_ALL")
        self.assertAlmostEqual(trade["pnl"], 10.0)
        self.assertEqual(trade["status"], "CLOSED")
        self.assertEqual(trade["exit_reason"], "CLOSE_ALL")
        self.assertEqual(trade["exit_price"], 4010.0)
        datetime.fromisoformat(trade["exit_time"])  # must parse

    def test_record_close_persists_the_trade(self) -> None:
        trade = self._trade()
        saved = []
        with patch.object(mp, "_live_symbol_specification",
                          return_value=XAUUSD_2DIGIT), \
                patch.object(mp, "PERSISTENCE_AVAILABLE", True), \
                patch.object(mp, "save_closed_trade", saved.append), \
                patch.object(mp, "LAYERS_AVAILABLE", False):
            mp._record_close(trade, 4010.0, "CLOSE_ALL")
        self.assertEqual(len(saved), 1,
                         "save_closed_trade was never called before this fix")

    def test_unknown_pnl_is_still_persisted_as_unknown(self) -> None:
        """So the risk gate refuses the day rather than reading it as flat."""
        trade = self._trade("SIDEWAYS")
        saved = []
        with patch.object(mp, "_live_symbol_specification",
                          return_value=XAUUSD_2DIGIT), \
                patch.object(mp, "PERSISTENCE_AVAILABLE", True), \
                patch.object(mp, "save_closed_trade", saved.append), \
                patch.object(mp, "LAYERS_AVAILABLE", False):
            mp._record_close(trade, 4010.0, "CLOSE_ALL")
        self.assertIsNone(saved[0]["pnl"])


class TimeStopIsConfiguredTests(unittest.TestCase):
    """R9. config.INTRADAY_MAX_HOLD_MINUTES was enforced nowhere."""

    def test_limits_carry_the_configured_hold(self) -> None:
        import config

        self.assertEqual(
            mp.RISK_LIMITS.max_hold,
            timedelta(minutes=config.INTRADAY_MAX_HOLD_MINUTES),
        )

    def test_limits_carry_the_configured_lot_cap(self) -> None:
        import config

        self.assertEqual(mp.RISK_LIMITS.max_lots_per_position,
                         config.INTRADAY_LOT_SIZE_MAX)

    def test_main_loop_applies_the_time_stop(self) -> None:
        """The predicate must be called from the loop, not merely exist."""
        source = inspect.getsource(mp.main)
        self.assertIn("overdue_positions", source)
        self.assertIn("time_stop_due", source)


class AccountStateIsReadOnlyTests(unittest.TestCase):
    """The state gatherer must not place orders or change the account."""

    def test_only_read_only_mt5_calls_appear(self) -> None:
        source = inspect.getsource(mp.account_risk_state)
        for forbidden in ("order_send", "order_check", "account_login"):
            self.assertNotIn(forbidden, source)
        self.assertIn("account_info", source)
        self.assertIn("positions_get", source)


if __name__ == "__main__":
    unittest.main()
