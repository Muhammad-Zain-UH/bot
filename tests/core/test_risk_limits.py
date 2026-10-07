"""Tests for the account-level risk limits.

The defect these guard against is not a mistuned threshold. It is a **default
that meant "all clear"**: ``check_pre_trade_gates(current_daily_loss=0)`` was
called without the argument, so the breaker evaluated ``0 < -500`` on every
cycle and could not fail. Several tests here exist specifically to pin the
behaviour that unknown state must read as STOP, not as safe.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from core.risk_limits import (
    AccountRiskState,
    RiskDecision,
    RiskLimitError,
    RiskLimits,
    RiskVerdict,
    build_state,
    evaluate,
    overdue_positions,
    realised_pnl_for_day,
)
from core.units import Percentage

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def limits(**overrides) -> RiskLimits:
    base = dict(
        max_daily_loss=Percentage(5.0),
        max_drawdown=Percentage(20.0),
        max_concurrent_positions=3,
        max_open_lots=0.30,
        max_lots_per_position=0.10,
        max_consecutive_losses=4,
        max_hold=timedelta(minutes=240),
    )
    base.update(overrides)
    return RiskLimits(**base)


def state(**overrides) -> AccountRiskState:
    base = dict(
        balance=10000.0,
        equity=10000.0,
        day_opening_balance=10000.0,
        peak_equity=10000.0,
        realised_pnl_today=0.0,
        consecutive_losses=0,
        open_positions=0,
        open_lots=0.0,
        trading_day=date(2026, 10, 5),
    )
    base.update(overrides)
    return AccountRiskState(**base)


class UnknownStateIsNotSafeTests(unittest.TestCase):
    """The core rule. Absence of information must not read as permission."""

    def test_none_state_halts(self) -> None:
        decision = evaluate(None, limits())
        self.assertIs(decision.verdict, RiskVerdict.HALT)
        self.assertFalse(decision.may_open)
        self.assertEqual(decision.max_new_lots, 0.0)

    def test_none_state_explains_itself(self) -> None:
        """The operator must be able to tell this from a real breach."""
        (breach,) = evaluate(None, limits()).breaches
        self.assertIn("UNAVAILABLE", breach)
        self.assertIn("assuming the account is flat", breach)

    def test_state_has_no_defaulted_pnl_field(self) -> None:
        """`realised_pnl_today=0` must be an assertion a caller makes, never a
        default the type supplies. This is R3's root cause expressed as a type."""
        with self.assertRaises(TypeError):
            AccountRiskState(  # type: ignore[call-arg]
                balance=1.0, equity=1.0, day_opening_balance=1.0,
                peak_equity=1.0, consecutive_losses=0,
                open_positions=0, open_lots=0.0, trading_day=date(2026, 1, 1),
            )


class DrawdownKillSwitchTests(unittest.TestCase):
    """R7. There was no drawdown limit of any kind."""

    def test_breach_halts_and_does_not_merely_block(self) -> None:
        decision = evaluate(state(equity=7999.0, peak_equity=10000.0), limits())
        self.assertIs(decision.verdict, RiskVerdict.HALT)

    def test_exactly_at_the_limit_halts(self) -> None:
        """20.00% against a 20% limit is a breach, not a pass."""
        decision = evaluate(state(equity=8000.0, peak_equity=10000.0), limits())
        self.assertIs(decision.verdict, RiskVerdict.HALT)

    def test_just_inside_the_limit_allows(self) -> None:
        decision = evaluate(state(equity=8001.0, peak_equity=10000.0), limits())
        self.assertIs(decision.verdict, RiskVerdict.ALLOW)

    def test_drawdown_is_measured_against_peak_not_balance(self) -> None:
        st = state(balance=10000.0, equity=9000.0, peak_equity=12000.0)
        self.assertAlmostEqual(st.drawdown.value, 25.0)

    def test_peak_below_equity_is_rejected(self) -> None:
        """A peak that excludes the present would report negative drawdown."""
        with self.assertRaises(RiskLimitError):
            state(equity=11000.0, peak_equity=10000.0)


class DailyLossBreakerTests(unittest.TestCase):
    """R3. The breaker that could not fire."""

    def test_breach_blocks_new_entries(self) -> None:
        decision = evaluate(state(realised_pnl_today=-501.0), limits())
        self.assertIs(decision.verdict, RiskVerdict.BLOCK_NEW_ENTRIES)
        self.assertFalse(decision.may_open)

    def test_breach_is_recoverable_not_a_halt(self) -> None:
        """A daily cap clears at the next trading day; a drawdown breach does
        not. Collapsing them would make the kill switch meaningless."""
        decision = evaluate(state(realised_pnl_today=-501.0), limits())
        self.assertIsNot(decision.verdict, RiskVerdict.HALT)

    def test_loss_is_measured_against_the_day_opening_balance(self) -> None:
        """Measuring against the live balance would shrink the cap as losses
        accumulate, so each successive loss would need to be smaller to trip it."""
        st = state(balance=9500.0, equity=9500.0,
                   day_opening_balance=10000.0, realised_pnl_today=-500.0)
        self.assertAlmostEqual(st.daily_loss.value, 5.0)

    def test_a_profitable_day_reports_zero_loss_not_negative(self) -> None:
        st = state(realised_pnl_today=+250.0)
        self.assertEqual(st.daily_loss.value, 0.0)
        self.assertIs(evaluate(st, limits()).verdict, RiskVerdict.ALLOW)


class ExposureCapTests(unittest.TestCase):
    """R8. `max_concurrent_trades = 3` capped a count, not the risk."""

    def test_three_positions_on_one_symbol_hit_the_lot_cap(self) -> None:
        """The count cap permits this; the exposure cap is what stops it."""
        decision = evaluate(state(open_positions=2, open_lots=0.30), limits())
        self.assertIs(decision.verdict, RiskVerdict.BLOCK_NEW_ENTRIES)
        self.assertTrue(any("EXPOSURE" in b for b in decision.breaches))

    def test_headroom_is_the_smaller_of_remaining_and_per_position(self) -> None:
        decision = evaluate(state(open_positions=1, open_lots=0.25), limits())
        self.assertAlmostEqual(decision.max_new_lots, 0.05)

    def test_headroom_is_capped_per_position_when_plenty_remains(self) -> None:
        decision = evaluate(state(open_positions=0, open_lots=0.0), limits())
        self.assertAlmostEqual(decision.max_new_lots, 0.10)

    def test_concurrency_cap_still_applies(self) -> None:
        decision = evaluate(state(open_positions=3, open_lots=0.05), limits())
        self.assertTrue(any("CONCURRENCY" in b for b in decision.breaches))


class ConsecutiveLossTests(unittest.TestCase):
    def test_breach_blocks(self) -> None:
        decision = evaluate(state(consecutive_losses=4), limits())
        self.assertIs(decision.verdict, RiskVerdict.BLOCK_NEW_ENTRIES)

    def test_none_disables_the_check(self) -> None:
        decision = evaluate(state(consecutive_losses=99),
                            limits(max_consecutive_losses=None))
        self.assertIs(decision.verdict, RiskVerdict.ALLOW)


class AllBreachesAreReportedTests(unittest.TestCase):
    """One log line should show everything wrong, not just the first thing."""

    def test_multiple_block_tier_breaches_all_appear(self) -> None:
        decision = evaluate(
            state(realised_pnl_today=-900.0, consecutive_losses=7,
                  open_positions=5, open_lots=0.9),
            limits(),
        )
        joined = " ".join(decision.breaches)
        for expected in ("DAILY LOSS", "CONSECUTIVE LOSSES", "CONCURRENCY", "EXPOSURE"):
            self.assertIn(expected, joined)

    def test_drawdown_short_circuits_because_it_is_terminal(self) -> None:
        """Once halted, the recoverable breaches are not the operator's problem."""
        decision = evaluate(
            state(equity=5000.0, peak_equity=10000.0, realised_pnl_today=-900.0),
            limits(),
        )
        self.assertIs(decision.verdict, RiskVerdict.HALT)
        self.assertEqual(len(decision.breaches), 1)


class LimitValidationTests(unittest.TestCase):
    """A silently corrected risk limit is how 5% becomes 50%."""

    def test_bare_float_percentage_is_rejected(self) -> None:
        with self.assertRaises(RiskLimitError) as caught:
            limits(max_daily_loss=5.0)
        self.assertIn("ambiguous", str(caught.exception))

    def test_zero_and_over_100_percent_rejected(self) -> None:
        for bad in (Percentage(0.0), Percentage(100.01), Percentage(-1.0)):
            with self.assertRaises(RiskLimitError):
                limits(max_daily_loss=bad)

    def test_total_below_per_position_is_rejected(self) -> None:
        """Otherwise one permitted position immediately breaches the total."""
        with self.assertRaises(RiskLimitError) as caught:
            limits(max_open_lots=0.05, max_lots_per_position=0.10)
        self.assertIn("single permitted position", str(caught.exception))

    def test_non_positive_lot_caps_rejected(self) -> None:
        for bad in (0.0, -0.1, float("inf"), float("nan")):
            with self.assertRaises(RiskLimitError):
                limits(max_open_lots=bad)

    def test_zero_balance_account_is_rejected(self) -> None:
        with self.assertRaises(RiskLimitError) as caught:
            state(balance=0.0)
        self.assertIn("already gone", str(caught.exception))


class RealisedPnlForDayTests(unittest.TestCase):
    def test_sums_only_the_requested_day(self) -> None:
        trades = [
            {"trade_id": "a", "pnl": -100.0, "exit_time": "2026-10-05T09:00:00+00:00"},
            {"trade_id": "b", "pnl": -50.0, "exit_time": "2026-10-05T23:59:59+00:00"},
            {"trade_id": "c", "pnl": -999.0, "exit_time": "2026-10-04T23:59:59+00:00"},
        ]
        total, counted = realised_pnl_for_day(trades, date(2026, 10, 5))
        self.assertAlmostEqual(total, -150.0)
        self.assertEqual(counted, 2)

    def test_naive_timestamps_are_read_as_utc(self) -> None:
        """Production wrote `datetime.now().isoformat()`, which has no offset."""
        trades = [{"trade_id": "a", "pnl": -10.0, "exit_time": "2026-10-05T09:00:00"}]
        total, counted = realised_pnl_for_day(trades, date(2026, 10, 5))
        self.assertAlmostEqual(total, -10.0)
        self.assertEqual(counted, 1)

    def test_unparseable_close_time_is_skipped_not_guessed(self) -> None:
        trades = [{"trade_id": "a", "pnl": -10.0, "exit_time": "not a date"}]
        total, counted = realised_pnl_for_day(trades, date(2026, 10, 5))
        self.assertEqual((total, counted), (0.0, 0))

    def test_missing_pnl_on_a_counted_day_raises(self) -> None:
        """Treating it as zero would understate the day's loss, which is the one
        direction a risk gate must never err in."""
        trades = [{"trade_id": "a", "exit_time": "2026-10-05T09:00:00+00:00"}]
        with self.assertRaises(RiskLimitError) as caught:
            realised_pnl_for_day(trades, date(2026, 10, 5))
        self.assertIn("understate", str(caught.exception))

    def test_non_numeric_pnl_raises(self) -> None:
        trades = [{"trade_id": "a", "pnl": "-10.0",
                   "exit_time": "2026-10-05T09:00:00+00:00"}]
        with self.assertRaises(RiskLimitError):
            realised_pnl_for_day(trades, date(2026, 10, 5))


class BuildStateTests(unittest.TestCase):
    TRADES = [
        {"trade_id": "a", "pnl": -120.0, "exit_time": "2026-10-05T09:00:00+00:00"},
        {"trade_id": "b", "pnl": -200.0, "exit_time": "2026-10-05T10:00:00+00:00"},
        {"trade_id": "c", "pnl": +50.0, "exit_time": "2026-10-04T10:00:00+00:00"},
    ]

    def _build(self, **kw):
        base = dict(balance=9730.0, equity=9730.0, closed_trades=self.TRADES,
                    open_positions=1, open_lots=0.10, now=NOW)
        base.update(kw)
        return build_state(**base)

    def test_day_opening_balance_excludes_todays_pnl(self) -> None:
        st = self._build()
        self.assertAlmostEqual(st.realised_pnl_today, -320.0)
        self.assertAlmostEqual(st.day_opening_balance, 10050.0)

    def test_consecutive_losses_counts_back_from_the_latest_close(self) -> None:
        st = self._build()
        self.assertEqual(st.consecutive_losses, 2)

    def test_a_win_resets_the_consecutive_count(self) -> None:
        trades = self.TRADES + [
            {"trade_id": "d", "pnl": +5.0, "exit_time": "2026-10-05T11:00:00+00:00"}
        ]
        self.assertEqual(self._build(closed_trades=trades).consecutive_losses, 0)

    def test_naive_now_is_rejected(self) -> None:
        """A naive clock would resolve the trading day in the host timezone."""
        with self.assertRaises(RiskLimitError) as caught:
            self._build(now=datetime(2026, 10, 5, 12, 0))
        self.assertIn("timezone-aware", str(caught.exception))

    def test_supplied_peak_equity_is_honoured(self) -> None:
        st = self._build(peak_equity=12000.0)
        self.assertAlmostEqual(st.peak_equity, 12000.0)
        self.assertAlmostEqual(st.drawdown.value, 100.0 * (12000.0 - 9730.0) / 12000.0)

    def test_derived_peak_is_never_below_equity(self) -> None:
        """Without external tracking the peak cannot see unrealised highs. It
        must still never fall below current equity, which would make drawdown
        negative."""
        st = self._build(balance=20000.0, equity=20000.0, peak_equity=None)
        self.assertGreaterEqual(st.peak_equity, st.equity)
        self.assertGreaterEqual(st.drawdown.value, 0.0)

    def test_derived_equity_curve_terminates_at_the_current_balance(self) -> None:
        """The reconstruction invariant. Applying every close in order to the
        implied starting balance must land exactly on `balance`; if it does not,
        the curve is not the account's and neither is the peak drawn from it.

        The first implementation started the walk at `day_opening_balance`,
        which already reflects every prior close, so it double-counted the
        history and reported a peak no trade sequence could produce.
        """
        trades = [
            {"trade_id": "a", "pnl": +500.0, "exit_time": "2026-10-01T10:00:00+00:00"},
            {"trade_id": "b", "pnl": -300.0, "exit_time": "2026-10-02T10:00:00+00:00"},
            {"trade_id": "c", "pnl": -120.0, "exit_time": "2026-10-05T09:00:00+00:00"},
        ]
        balance = 10080.0
        st = build_state(balance=balance, equity=balance, closed_trades=trades,
                         open_positions=0, open_lots=0.0, now=NOW, peak_equity=None)
        start = balance - sum(t["pnl"] for t in trades)
        running, peak = start, max(start, balance)
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
        self.assertAlmostEqual(running, balance, places=9)
        self.assertAlmostEqual(st.peak_equity, peak, places=9)

    def test_derived_peak_captures_a_realised_high_before_a_loss(self) -> None:
        """A win then a loss means the peak is above the present balance, so the
        drawdown must be positive rather than zero."""
        trades = [
            {"trade_id": "w", "pnl": +1000.0, "exit_time": "2026-10-01T10:00:00+00:00"},
            {"trade_id": "l", "pnl": -400.0, "exit_time": "2026-10-02T10:00:00+00:00"},
        ]
        st = build_state(balance=10600.0, equity=10600.0, closed_trades=trades,
                         open_positions=0, open_lots=0.0, now=NOW, peak_equity=None)
        self.assertAlmostEqual(st.peak_equity, 11000.0)
        self.assertAlmostEqual(st.drawdown.value, 100.0 * 400.0 / 11000.0)

    def test_empty_history_is_a_flat_day_not_an_error(self) -> None:
        st = self._build(closed_trades=[])
        self.assertEqual(st.realised_pnl_today, 0.0)
        self.assertEqual(st.consecutive_losses, 0)

    def test_trading_day_is_utc(self) -> None:
        """23:30 in UTC+05:00 is the following UTC day."""
        st = self._build(
            closed_trades=[],
            now=datetime(2026, 10, 5, 23, 30,
                         tzinfo=timezone(timedelta(hours=5))),
        )
        self.assertEqual(st.trading_day, date(2026, 10, 5))


class TimeStopTests(unittest.TestCase):
    """R9. `INTRADAY_MAX_HOLD_MINUTES = 240` was enforced nowhere."""

    OPEN = [
        {"trade_id": "old", "entry_time": "2026-10-05T07:00:00+00:00"},
        {"trade_id": "fresh", "entry_time": "2026-10-05T11:30:00+00:00"},
    ]

    def test_identifies_only_positions_past_the_limit(self) -> None:
        overdue = overdue_positions(self.OPEN, now=NOW,
                                    max_hold=timedelta(minutes=240))
        self.assertEqual([t for t, _ in overdue], ["old"])

    def test_exactly_at_the_limit_is_overdue(self) -> None:
        trades = [{"trade_id": "x", "entry_time": "2026-10-05T08:00:00+00:00"}]
        overdue = overdue_positions(trades, now=NOW, max_hold=timedelta(minutes=240))
        self.assertEqual(len(overdue), 1)

    def test_sorted_longest_held_first(self) -> None:
        trades = [
            {"trade_id": "a", "entry_time": "2026-10-05T06:00:00+00:00"},
            {"trade_id": "b", "entry_time": "2026-10-05T04:00:00+00:00"},
        ]
        overdue = overdue_positions(trades, now=NOW, max_hold=timedelta(minutes=240))
        self.assertEqual([t for t, _ in overdue], ["b", "a"])

    def test_none_disables_the_stop(self) -> None:
        self.assertEqual(overdue_positions(self.OPEN, now=NOW, max_hold=None), ())

    def test_unparseable_entry_time_raises_rather_than_reading_as_young(self) -> None:
        trades = [{"trade_id": "x", "entry_time": "whenever"}]
        with self.assertRaises(RiskLimitError) as caught:
            overdue_positions(trades, now=NOW, max_hold=timedelta(minutes=240))
        self.assertIn("age is therefore unknown", str(caught.exception))


class DecisionReportingTests(unittest.TestCase):
    def test_describe_is_a_single_line(self) -> None:
        text = evaluate(state(realised_pnl_today=-900.0), limits()).describe()
        self.assertNotIn("\n", text)
        self.assertTrue(text.startswith("BLOCK_NEW_ENTRIES"))

    def test_allow_with_zero_headroom_does_not_permit_opening(self) -> None:
        """may_open must agree with the headroom, not just the verdict."""
        decision = RiskDecision(RiskVerdict.ALLOW, (), 0.0)
        self.assertFalse(decision.may_open)

    def test_non_risklimits_argument_is_rejected(self) -> None:
        with self.assertRaises(RiskLimitError):
            evaluate(state(), limits=object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
