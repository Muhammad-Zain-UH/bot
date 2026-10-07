"""Contract tests for risk-based position sizing.

The central claim is one sentence: **a sized position never risks more than the
budget**. Everything else here exists to make that claim hard to break --
rounding direction, the minimum-volume decision, the maximum cap, and the
refusal to price an instrument whose economics are not implemented.

The worked example is pinned because it is the one that was wrong. Before this
module, $10,000 at 1 % with a $30 stop produced 0.33 lots, which on the real
XAUUSD contract is $990 -- 9.9 % of the account against an instruction of 1 %.
"""

from __future__ import annotations

import unittest

from core.sizing import SizingDecision, SizingInputError, lots_for_risk
from core.symbols import (
    CalculationMode,
    EURUSD_5DIGIT,
    SymbolSpecification,
    UnsupportedCalculationModeError,
    XAUUSD_2DIGIT,
)

GOLD = XAUUSD_2DIGIT


def gold_like(**overrides) -> SymbolSpecification:
    """A gold specification with fields overridden, for bounds tests."""
    base = dict(
        symbol="XAUUSD", digits=2, point=0.01, pip_size=0.10,
        tick_size=0.01, tick_value=1.0, contract_size=100.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        calc_mode=CalculationMode.CFD_LEVERAGE,
    )
    base.update(overrides)
    return SymbolSpecification(**base)


class TheWorkedExample(unittest.TestCase):
    """$10,000 · 1 % · $30 stop · contract size 100."""

    def setUp(self) -> None:
        self.d = lots_for_risk(
            GOLD, balance=10_000.0, risk_fraction=0.01, stop_distance=30.0
        )

    def test_risk_budget_is_one_percent(self) -> None:
        self.assertAlmostEqual(self.d.risk_budget, 100.0, places=9)

    def test_money_risk_per_lot(self) -> None:
        """$30 stop × $100 per price unit per lot."""
        self.assertAlmostEqual(self.d.money_per_lot, 3_000.0, places=9)

    def test_raw_lots(self) -> None:
        self.assertAlmostEqual(self.d.raw_lots, 100.0 / 3_000.0, places=12)
        self.assertAlmostEqual(self.d.raw_lots, 0.0333333333333, places=10)

    def test_normalised_lots_floor_to_the_step(self) -> None:
        """0.0333… floors to 0.03, never 0.04."""
        self.assertAlmostEqual(self.d.lots, 0.03, places=9)
        self.assertTrue(self.d.tradeable)

    def test_actual_risk_after_normalisation(self) -> None:
        """0.03 lots × $30 × $100 = $90, under the $100 budget."""
        self.assertAlmostEqual(self.d.actual_risk, 90.0, places=9)
        self.assertLess(self.d.actual_risk, self.d.risk_budget)

    def test_the_old_answer_is_not_produced(self) -> None:
        """0.33 lots would have been $990 -- 9.9 % against an instruction of 1 %."""
        self.assertNotAlmostEqual(self.d.lots, 0.33, places=6)
        self.assertAlmostEqual(30.0 * GOLD.money_per_price_unit(0.33), 990.0, places=9)


class RiskIsNeverExceeded(unittest.TestCase):
    """The invariant the whole module exists for."""

    def test_across_balances_fractions_and_stops(self) -> None:
        for balance in (500.0, 1_000.0, 10_000.0, 100_000.0, 1_000_000.0):
            for fraction in (0.001, 0.005, 0.01, 0.02, 0.05, 1.0):
                for stop in (0.5, 3.0, 9.14642386182777, 30.0, 250.0):
                    with self.subTest(balance=balance, fraction=fraction, stop=stop):
                        d = lots_for_risk(
                            GOLD, balance=balance, risk_fraction=fraction,
                            stop_distance=stop,
                        )
                        if d.tradeable:
                            self.assertLessEqual(d.actual_risk, d.risk_budget + 1e-9)
                        else:
                            self.assertEqual(d.lots, 0.0)

    def test_rounding_is_downward_never_nearest(self) -> None:
        """A raw size just under a step boundary must not round up."""
        # 0.0399 lots: nearest-rounding would give 0.04 and overshoot.
        d = lots_for_risk(GOLD, balance=11_970.0, risk_fraction=0.01, stop_distance=30.0)
        self.assertAlmostEqual(d.raw_lots, 0.0399, places=9)
        self.assertAlmostEqual(d.lots, 0.03, places=9)
        self.assertLessEqual(d.actual_risk, d.risk_budget)

    def test_exact_multiples_are_kept(self) -> None:
        d = lots_for_risk(GOLD, balance=9_000.0, risk_fraction=0.01, stop_distance=30.0)
        self.assertAlmostEqual(d.raw_lots, 0.03, places=9)
        self.assertAlmostEqual(d.lots, 0.03, places=9)
        self.assertAlmostEqual(d.actual_risk, d.risk_budget, places=9)


class VolumeBounds(unittest.TestCase):
    def test_below_minimum_is_declined_not_raised(self) -> None:
        """Raising to the minimum would exceed the budget. It must decline."""
        d = lots_for_risk(GOLD, balance=100.0, risk_fraction=0.01, stop_distance=30.0)
        self.assertFalse(d.tradeable)
        self.assertEqual(d.lots, 0.0)
        self.assertEqual(d.actual_risk, 0.0)
        self.assertIn("below the", d.reason)
        # The minimum really would have overspent: 0.01 lots is $30 on a $1 budget.
        self.assertGreater(30.0 * GOLD.money_per_price_unit(GOLD.volume_min),
                           d.risk_budget)

    def test_exactly_at_the_minimum_is_tradeable(self) -> None:
        d = lots_for_risk(GOLD, balance=3_000.0, risk_fraction=0.01, stop_distance=30.0)
        self.assertTrue(d.tradeable)
        self.assertAlmostEqual(d.lots, GOLD.volume_min, places=9)

    def test_above_maximum_is_capped_to_the_maximum(self) -> None:
        spec = gold_like(volume_max=0.50)
        d = lots_for_risk(spec, balance=10_000_000.0, risk_fraction=0.01,
                          stop_distance=30.0)
        self.assertTrue(d.tradeable)
        self.assertAlmostEqual(d.lots, 0.50, places=9)
        self.assertGreater(d.raw_lots, spec.volume_max)

    def test_a_coarse_step_still_floors(self) -> None:
        spec = gold_like(volume_step=0.10, volume_min=0.10)
        d = lots_for_risk(spec, balance=100_000.0, risk_fraction=0.01,
                          stop_distance=30.0)
        self.assertAlmostEqual(d.raw_lots, 1.0 / 3.0, places=9)
        self.assertAlmostEqual(d.lots, 0.30, places=9)
        self.assertLessEqual(d.actual_risk, d.risk_budget)


class InvalidInputs(unittest.TestCase):
    def test_zero_stop_distance(self) -> None:
        with self.assertRaises(SizingInputError):
            lots_for_risk(GOLD, balance=10_000.0, risk_fraction=0.01, stop_distance=0.0)

    def test_negative_stop_distance(self) -> None:
        """Callers pass a distance, not a signed difference."""
        with self.assertRaises(SizingInputError):
            lots_for_risk(GOLD, balance=10_000.0, risk_fraction=0.01, stop_distance=-30.0)

    def test_zero_and_negative_balance(self) -> None:
        for balance in (0.0, -10_000.0):
            with self.subTest(balance=balance):
                with self.assertRaises(SizingInputError):
                    lots_for_risk(GOLD, balance=balance, risk_fraction=0.01,
                                  stop_distance=30.0)

    def test_invalid_risk_fractions(self) -> None:
        for fraction in (0.0, -0.01, 1.01, 100.0):
            with self.subTest(fraction=fraction):
                with self.assertRaises(SizingInputError):
                    lots_for_risk(GOLD, balance=10_000.0, risk_fraction=fraction,
                                  stop_distance=30.0)

    def test_a_percentage_passed_as_a_fraction_is_rejected(self) -> None:
        """``1.0`` meaning "1 %" is a real mistake; it means 100 % here."""
        with self.assertRaises(SizingInputError):
            lots_for_risk(GOLD, balance=10_000.0, risk_fraction=5.0, stop_distance=30.0)

    def test_non_finite_inputs(self) -> None:
        for kwargs in (
            {"balance": float("nan")},
            {"balance": float("inf")},
            {"risk_fraction": float("nan")},
            {"stop_distance": float("inf")},
        ):
            with self.subTest(**kwargs):
                base = {"balance": 10_000.0, "risk_fraction": 0.01, "stop_distance": 30.0}
                base.update(kwargs)
                with self.assertRaises(SizingInputError):
                    lots_for_risk(GOLD, **base)


class CalculationModeGoverns(unittest.TestCase):
    """Which formula applies is the instrument's property, not a default."""

    def test_unsupported_mode_raises_rather_than_borrowing_the_formula(self) -> None:
        futures = gold_like(calc_mode=1)  # SYMBOL_CALC_MODE_FUTURES, tick-based
        with self.assertRaises(UnsupportedCalculationModeError):
            lots_for_risk(futures, balance=10_000.0, risk_fraction=0.01,
                          stop_distance=30.0)

    def test_every_supported_mode_uses_contract_size(self) -> None:
        for mode in CalculationMode:
            with self.subTest(mode=mode.name):
                spec = gold_like(calc_mode=mode)
                self.assertAlmostEqual(spec.money_per_price_unit(1.0), 100.0, places=9)

    def test_tick_value_is_not_consulted(self) -> None:
        """The live server reports a tick value inconsistent by 10x."""
        broken = gold_like(tick_value=0.1)   # exactly what MetaQuotes-Demo reports
        self.assertAlmostEqual(broken.money_per_price_unit(1.0), 100.0, places=9)
        d = lots_for_risk(broken, balance=10_000.0, risk_fraction=0.01,
                          stop_distance=30.0)
        self.assertAlmostEqual(d.lots, 0.03, places=9)

    def test_a_forex_instrument_sizes_on_its_own_contract(self) -> None:
        d = lots_for_risk(EURUSD_5DIGIT, balance=10_000.0, risk_fraction=0.01,
                          stop_distance=0.0050)
        self.assertAlmostEqual(d.money_per_lot, 500.0, places=9)
        self.assertAlmostEqual(d.raw_lots, 0.2, places=9)
        self.assertAlmostEqual(d.lots, 0.20, places=9)


class GoldenSizingFixture(unittest.TestCase):
    """A pinned correctness fixture. **Not profitability evidence.**

    Deterministic inputs to deterministic quantities and monetary risk. It
    exists so a future change to the economics cannot pass unnoticed.
    """

    # balance, risk_fraction, entry, original_stop, lots, risk, R at 1R
    CASES = (
        (10_000.0, 0.01,  2450.00, 2420.00, 0.03,   90.00),
        (10_000.0, 0.01,  2450.00, 2447.00, 0.33,   99.00),
        (100_000.0, 0.01, 2450.00, 2420.00, 0.33,  990.00),
        (100_000.0, 0.02, 2450.00, 2400.00, 0.40, 2000.00),
        (5_000.0, 0.005,  2450.00, 2445.00, 0.05,   25.00),
    )

    def test_pinned_quantities_and_risk(self) -> None:
        for balance, fraction, entry, stop, lots, risk in self.CASES:
            with self.subTest(balance=balance, fraction=fraction, stop=entry - stop):
                d = lots_for_risk(
                    GOLD, balance=balance, risk_fraction=fraction,
                    stop_distance=abs(entry - stop),
                )
                self.assertTrue(d.tradeable)
                self.assertAlmostEqual(d.lots, lots, places=9)
                self.assertAlmostEqual(d.actual_risk, risk, places=6)
                self.assertLessEqual(d.actual_risk, d.risk_budget + 1e-9)

    def test_r_multiple_is_one_at_the_stop(self) -> None:
        """Risk at the stop is 1R by definition; R is unchanged by sizing."""
        for balance, fraction, entry, stop, _lots, risk in self.CASES:
            with self.subTest(balance=balance):
                d = lots_for_risk(
                    GOLD, balance=balance, risk_fraction=fraction,
                    stop_distance=abs(entry - stop),
                )
                price_risk = abs(entry - stop)
                self.assertAlmostEqual(
                    GOLD.money_for_price_distance(price_risk, d.lots), risk, places=6
                )

    def test_side_makes_no_difference(self) -> None:
        """Sizing depends on distance, so long and short agree."""
        long_ = lots_for_risk(GOLD, balance=10_000.0, risk_fraction=0.01,
                              stop_distance=abs(2450.0 - 2420.0))
        short = lots_for_risk(GOLD, balance=10_000.0, risk_fraction=0.01,
                              stop_distance=abs(2420.0 - 2450.0))
        self.assertEqual(long_, short)
        self.assertIsInstance(long_, SizingDecision)


if __name__ == "__main__":
    unittest.main()
