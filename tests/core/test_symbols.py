"""Tests for the canonical broker symbol specification.

Covers tick size, point, tick value, contract size and volume constraints, plus
the monetary primitive that correct position sizing will be built on in Phase 2.
"""

from __future__ import annotations

import unittest

from core.symbols import (
    EURUSD_5DIGIT,
    XAUUSD_2DIGIT,
    XAUUSD_3DIGIT,
    InvalidSymbolSpecificationError,
    SymbolSpecification,
)
from tests.fixtures.symbols import eurusd_symbol_info, xauusd_symbol_info


class SpecificationValidationTests(unittest.TestCase):
    """A specification that cannot be internally consistent must not exist."""

    def _valid_kwargs(self, **overrides: object) -> dict:
        base = dict(
            symbol="XAUUSD",
            digits=2,
            point=0.01,
            pip_size=0.10,
            tick_size=0.01,
            tick_value=1.0,
            contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )
        base.update(overrides)
        return base

    def test_valid_specification_constructs(self) -> None:
        self.assertEqual(SymbolSpecification(**self._valid_kwargs()).symbol, "XAUUSD")

    def test_empty_symbol_rejected(self) -> None:
        with self.assertRaises(InvalidSymbolSpecificationError):
            SymbolSpecification(**self._valid_kwargs(symbol=""))

    def test_non_positive_sizes_rejected(self) -> None:
        for field in ("point", "pip_size", "tick_size", "contract_size", "volume_step"):
            with self.subTest(field=field):
                with self.assertRaises(InvalidSymbolSpecificationError):
                    SymbolSpecification(**self._valid_kwargs(**{field: 0.0}))

    def test_negative_digits_rejected(self) -> None:
        with self.assertRaises(InvalidSymbolSpecificationError):
            SymbolSpecification(**self._valid_kwargs(digits=-1))

    def test_volume_max_below_min_rejected(self) -> None:
        with self.assertRaises(InvalidSymbolSpecificationError):
            SymbolSpecification(**self._valid_kwargs(volume_min=1.0, volume_max=0.5))

    def test_pip_not_a_whole_multiple_of_point_rejected(self) -> None:
        """A pip that is 3.7 points means the two values came from different conventions."""
        with self.assertRaises(InvalidSymbolSpecificationError):
            SymbolSpecification(**self._valid_kwargs(pip_size=0.037))

    def test_specification_is_immutable(self) -> None:
        with self.assertRaises(Exception):
            XAUUSD_2DIGIT.pip_size = 0.01  # type: ignore[misc]


class TickAndPointTests(unittest.TestCase):
    """Point, pip and tick are three separate things."""

    def test_gold_two_digit_relationships(self) -> None:
        self.assertEqual(XAUUSD_2DIGIT.point, 0.01)
        self.assertEqual(XAUUSD_2DIGIT.pip_size, 0.10)
        self.assertEqual(XAUUSD_2DIGIT.tick_size, 0.01)
        self.assertEqual(XAUUSD_2DIGIT.points_per_pip, 10.0)

    def test_gold_three_digit_has_same_pip_but_different_point(self) -> None:
        self.assertEqual(XAUUSD_3DIGIT.pip_size, XAUUSD_2DIGIT.pip_size)
        self.assertNotEqual(XAUUSD_3DIGIT.point, XAUUSD_2DIGIT.point)
        self.assertEqual(XAUUSD_3DIGIT.points_per_pip, 100.0)

    def test_round_to_tick(self) -> None:
        self.assertAlmostEqual(XAUUSD_2DIGIT.round_to_tick(4000.126), 4000.13)
        self.assertAlmostEqual(XAUUSD_2DIGIT.round_to_tick(4000.124), 4000.12)

    def test_round_to_tick_respects_precision(self) -> None:
        self.assertAlmostEqual(XAUUSD_3DIGIT.round_to_tick(4000.1236), 4000.124)
        self.assertAlmostEqual(EURUSD_5DIGIT.round_to_tick(1.234567), 1.23457)

    def test_round_to_tick_rejects_non_finite(self) -> None:
        with self.assertRaises(ValueError):
            XAUUSD_2DIGIT.round_to_tick(float("nan"))


class VolumeConstraintTests(unittest.TestCase):
    """Volume must land on the broker's grid, and must round DOWN."""

    def test_round_volume_snaps_down_not_up(self) -> None:
        """Rounding a size up would take more risk than the risk engine allowed."""
        self.assertAlmostEqual(XAUUSD_2DIGIT.round_volume_to_step(1.679), 1.67)
        self.assertAlmostEqual(XAUUSD_2DIGIT.round_volume_to_step(0.0199), 0.01)

    def test_round_volume_is_exact_on_grid_values(self) -> None:
        for volume in (0.01, 0.10, 1.00, 12.34):
            with self.subTest(volume=volume):
                self.assertAlmostEqual(XAUUSD_2DIGIT.round_volume_to_step(volume), volume)

    def test_sub_step_volume_rounds_to_zero_rather_than_a_minimum(self) -> None:
        """Returning 0 forces the caller to decide; substituting a minimum hides risk."""
        self.assertAlmostEqual(XAUUSD_2DIGIT.round_volume_to_step(0.004), 0.0)

    def test_round_volume_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            XAUUSD_2DIGIT.round_volume_to_step(-0.5)

    def test_clamp_volume_bounds(self) -> None:
        self.assertAlmostEqual(XAUUSD_2DIGIT.clamp_volume(0.001), XAUUSD_2DIGIT.volume_min)
        self.assertAlmostEqual(XAUUSD_2DIGIT.clamp_volume(500.0), XAUUSD_2DIGIT.volume_max)
        self.assertAlmostEqual(XAUUSD_2DIGIT.clamp_volume(0.5), 0.5)

    def test_is_volume_tradeable(self) -> None:
        self.assertTrue(XAUUSD_2DIGIT.is_volume_tradeable(0.01))
        self.assertTrue(XAUUSD_2DIGIT.is_volume_tradeable(50.0))
        self.assertFalse(XAUUSD_2DIGIT.is_volume_tradeable(0.004))
        self.assertFalse(XAUUSD_2DIGIT.is_volume_tradeable(500.0))
        self.assertFalse(XAUUSD_2DIGIT.is_volume_tradeable(-1.0))


class MonetaryValueTests(unittest.TestCase):
    """The primitive correct position sizing depends on."""

    def test_gold_dollar_move_is_one_hundred_per_lot(self) -> None:
        """XAUUSD: 1 lot = 100 oz, so a $1 move is $100.

        ``risk_manager.calculate_lot_size_for_symbol`` divides by ``10.0``,
        making every position ~10x oversized. Recorded in PHASE_2_ISSUES.md;
        not changed in this phase.
        """
        self.assertAlmostEqual(XAUUSD_2DIGIT.money_per_price_unit(1.0), 100.0)

    def test_money_per_price_unit_scales_with_volume(self) -> None:
        self.assertAlmostEqual(XAUUSD_2DIGIT.money_per_price_unit(0.01), 1.0)
        self.assertAlmostEqual(XAUUSD_2DIGIT.money_per_price_unit(2.0), 200.0)

    def test_money_per_price_unit_is_consistent_across_quote_precisions(self) -> None:
        """The same instrument must be worth the same regardless of decimals shown."""
        self.assertAlmostEqual(
            XAUUSD_2DIGIT.money_per_price_unit(1.0),
            XAUUSD_3DIGIT.money_per_price_unit(1.0),
        )

    def test_money_for_price_distance(self) -> None:
        self.assertAlmostEqual(XAUUSD_2DIGIT.money_for_price_distance(6.0, 0.10), 60.0)

    def test_money_for_price_distance_ignores_sign(self) -> None:
        self.assertAlmostEqual(
            XAUUSD_2DIGIT.money_for_price_distance(-6.0, 0.10),
            XAUUSD_2DIGIT.money_for_price_distance(6.0, 0.10),
        )

    def test_forex_value_differs_from_gold(self) -> None:
        self.assertAlmostEqual(EURUSD_5DIGIT.money_per_price_unit(1.0), 10_000.0)

    def test_negative_volume_rejected(self) -> None:
        with self.assertRaises(ValueError):
            XAUUSD_2DIGIT.money_per_price_unit(-1.0)


class FromMT5SymbolInfoTests(unittest.TestCase):
    """Construction from a broker object, without importing MetaTrader5."""

    def test_builds_from_a_gold_symbol_info(self) -> None:
        spec = SymbolSpecification.from_mt5_symbol_info(
            xauusd_symbol_info(2), pip_size=0.10
        )
        self.assertEqual(spec.symbol, "XAUUSD")
        self.assertEqual(spec.digits, 2)
        self.assertAlmostEqual(spec.contract_size, 100.0)
        self.assertAlmostEqual(spec.money_per_price_unit(1.0), 100.0)

    def test_builds_from_a_forex_symbol_info(self) -> None:
        spec = SymbolSpecification.from_mt5_symbol_info(
            eurusd_symbol_info(), pip_size=0.0001
        )
        self.assertEqual(spec.symbol, "EURUSD")
        self.assertEqual(spec.points_per_pip, 10.0)

    def test_pip_size_has_no_default_and_must_be_supplied(self) -> None:
        """MT5 does not report pip size; inferring it is the error being prevented."""
        with self.assertRaises(TypeError):
            SymbolSpecification.from_mt5_symbol_info(xauusd_symbol_info(2))  # type: ignore[call-arg]

    def test_missing_attributes_are_reported_clearly(self) -> None:
        class Incomplete:
            name = "XAUUSD"
            digits = 2

        with self.assertRaises(InvalidSymbolSpecificationError) as ctx:
            SymbolSpecification.from_mt5_symbol_info(Incomplete(), pip_size=0.10)
        self.assertIn("point", str(ctx.exception))

    def test_zero_tick_size_falls_back_to_point(self) -> None:
        """Some brokers report trade_tick_size == 0."""
        info = xauusd_symbol_info(2)
        broken = type(info)(**{**info.__dict__, "trade_tick_size": 0.0})
        spec = SymbolSpecification.from_mt5_symbol_info(broken, pip_size=0.10)
        self.assertAlmostEqual(spec.tick_size, spec.point)


if __name__ == "__main__":
    unittest.main()
