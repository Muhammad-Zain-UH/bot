"""Tests for the canonical domain types.

Focus is on invariants. Each type exists to make a specific audit finding
unrepresentable, so the tests assert that the invalid construction *raises*
rather than merely that the valid one works.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from core.clock import UTC
from core.symbols import XAUUSD_2DIGIT
from core.types import (
    DomainInvariantError,
    FairValueGap,
    FairValueGapKind,
    LiquidityLevel,
    LiquidityLevelKind,
    LiquiditySweep,
    MarketBar,
    MarketPrice,
    OrderBlock,
    OrderKind,
    OrderRequest,
    OrderResult,
    OrderResultStatus,
    Position,
    PositionStatus,
    RiskParameters,
    Side,
    Signal,
    SignalType,
    StopLoss,
    SwingPoint,
    SwingType,
    TakeProfit,
    Timeframe,
    TradingSetup,
    bar_from_mapping,
)
from core.units import Percentage, Pips, PriceDistance

MOMENT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 6, 1, 12, 0)


class SideTests(unittest.TestCase):
    """Direction is an enum, not a free-form string."""

    def test_sign_and_opposite(self) -> None:
        self.assertEqual(Side.BUY.sign, 1)
        self.assertEqual(Side.SELL.sign, -1)
        self.assertIs(Side.BUY.opposite, Side.SELL)
        self.assertIs(Side.SELL.opposite, Side.BUY)

    def test_from_bias_accepts_known_synonyms(self) -> None:
        for text in ("BULLISH", "bullish", "BUY", "long"):
            with self.subTest(text=text):
                self.assertIs(Side.from_bias(text), Side.BUY)
        for text in ("BEARISH", "sell", "SHORT"):
            with self.subTest(text=text):
                self.assertIs(Side.from_bias(text), Side.SELL)

    def test_neutral_bias_is_rejected_rather_than_becoming_a_short(self) -> None:
        """``main_production._bias_to_side`` maps anything not BULLISH to SELL."""
        for text in ("NEUTRAL", "", "UNKNOWN"):
            with self.subTest(text=text):
                with self.assertRaises(DomainInvariantError):
                    Side.from_bias(text)

    def test_sign_removes_the_need_for_mirrored_branches(self) -> None:
        entry, distance = 4000.0, 10.0
        self.assertAlmostEqual(entry + distance * Side.BUY.sign, 4010.0)
        self.assertAlmostEqual(entry + distance * Side.SELL.sign, 3990.0)


class TimeframeTests(unittest.TestCase):
    def test_minutes(self) -> None:
        self.assertEqual(Timeframe.M5.minutes, 5)
        self.assertEqual(Timeframe.H4.minutes, 240)
        self.assertEqual(Timeframe.D1.minutes, 1440)

    def test_every_member_has_a_duration(self) -> None:
        for timeframe in Timeframe:
            with self.subTest(timeframe=timeframe.value):
                self.assertGreater(timeframe.minutes, 0)


class MarketBarTests(unittest.TestCase):
    """OHLC consistency is enforced at construction."""

    def _bar(self, **overrides: object) -> MarketBar:
        base = dict(timestamp=MOMENT, open=100.0, high=105.0, low=99.0, close=104.0)
        base.update(overrides)
        return MarketBar(**base)  # type: ignore[arg-type]

    def test_valid_bar(self) -> None:
        self.assertAlmostEqual(self._bar().close, 104.0)

    def test_high_below_low_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._bar(high=98.0, low=99.0)

    def test_high_below_body_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._bar(high=101.0, close=104.0)

    def test_low_above_body_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._bar(low=101.0, open=100.0)

    def test_naive_timestamp_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._bar(timestamp=NAIVE)

    def test_negative_volume_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._bar(volume=-1.0)

    def test_derived_measures_are_typed(self) -> None:
        bar = self._bar()
        self.assertEqual(bar.range, PriceDistance(6.0))
        self.assertEqual(bar.body, PriceDistance(4.0))
        self.assertEqual(bar.upper_wick, PriceDistance(1.0))
        self.assertEqual(bar.lower_wick, PriceDistance(1.0))

    def test_derived_measures_convert_to_pips(self) -> None:
        self.assertEqual(self._bar().range.to_pips(XAUUSD_2DIGIT), Pips(60.0))

    def test_close_position(self) -> None:
        self.assertAlmostEqual(self._bar().close_position(), 5.0 / 6.0)

    def test_zero_range_bar_does_not_divide_by_zero(self) -> None:
        flat = self._bar(open=100.0, high=100.0, low=100.0, close=100.0)
        self.assertAlmostEqual(flat.close_position(), 0.5)

    def test_is_bullish(self) -> None:
        self.assertTrue(self._bar(open=100.0, close=104.0).is_bullish)
        self.assertFalse(self._bar(open=104.0, close=100.0).is_bullish)

    def test_bar_is_immutable(self) -> None:
        with self.assertRaises(Exception):
            self._bar().close = 1.0  # type: ignore[misc]


class BarFromMappingTests(unittest.TestCase):
    """Bridge from the existing pandas pipeline."""

    def test_builds_from_mt5_style_row(self) -> None:
        bar = bar_from_mapping(
            {"time": MOMENT, "open": 100.0, "high": 105.0,
             "low": 99.0, "close": 104.0, "tick_volume": 250.0},
            timeframe=Timeframe.M5,
        )
        self.assertAlmostEqual(bar.volume, 250.0)
        self.assertIs(bar.timeframe, Timeframe.M5)

    def test_accepts_volume_or_tick_volume(self) -> None:
        bar = bar_from_mapping(
            {"timestamp": MOMENT, "open": 1.0, "high": 2.0,
             "low": 0.5, "close": 1.5, "volume": 7.0}
        )
        self.assertAlmostEqual(bar.volume, 7.0)

    def test_missing_ohlc_is_reported(self) -> None:
        with self.assertRaises(DomainInvariantError) as ctx:
            bar_from_mapping({"time": MOMENT, "open": 1.0, "high": 2.0})
        self.assertIn("low", str(ctx.exception))

    def test_missing_timestamp_is_reported(self) -> None:
        with self.assertRaises(DomainInvariantError):
            bar_from_mapping({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5})

    def test_invalid_ohlc_still_validated_through_the_bridge(self) -> None:
        with self.assertRaises(DomainInvariantError):
            bar_from_mapping(
                {"time": MOMENT, "open": 1.0, "high": 0.4, "low": 0.5, "close": 0.45}
            )


class MarketPriceTests(unittest.TestCase):
    """A quote has two sides, and only one of them is tradeable per direction."""

    def _quote(self, bid: float = 4000.0, ask: float = 4000.3) -> MarketPrice:
        return MarketPrice(timestamp=MOMENT, bid=bid, ask=ask)

    def test_crossed_quote_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._quote(bid=4000.5, ask=4000.0)

    def test_equal_bid_ask_allowed(self) -> None:
        self.assertAlmostEqual(self._quote(bid=4000.0, ask=4000.0).spread.value, 0.0)

    def test_price_for_uses_the_executable_side(self) -> None:
        quote = self._quote()
        self.assertAlmostEqual(quote.price_for(Side.BUY), 4000.3)
        self.assertAlmostEqual(quote.price_for(Side.SELL), 4000.0)

    def test_mid_is_not_the_executable_price(self) -> None:
        """Pricing both directions off the mid understates cost by half a spread."""
        quote = self._quote()
        self.assertNotAlmostEqual(quote.mid, quote.price_for(Side.BUY))
        self.assertNotAlmostEqual(quote.mid, quote.price_for(Side.SELL))

    def test_spread_is_typed_and_converts_to_pips(self) -> None:
        self.assertEqual(self._quote().spread.to_pips(XAUUSD_2DIGIT), Pips(3.0))

    def test_naive_timestamp_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            MarketPrice(timestamp=NAIVE, bid=1.0, ask=1.1)


class StopLossAndTakeProfitTests(unittest.TestCase):
    """The wrong-side-stop gap, closed at the type boundary."""

    def test_valid_buy_stop(self) -> None:
        self.assertEqual(
            StopLoss(price=3990.0, entry_price=4000.0, side=Side.BUY).risk_distance,
            PriceDistance(10.0),
        )

    def test_valid_sell_stop(self) -> None:
        self.assertEqual(
            StopLoss(price=4010.0, entry_price=4000.0, side=Side.SELL).risk_distance,
            PriceDistance(10.0),
        )

    def test_buy_stop_above_entry_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            StopLoss(price=4010.0, entry_price=4000.0, side=Side.BUY)

    def test_sell_stop_below_entry_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            StopLoss(price=3990.0, entry_price=4000.0, side=Side.SELL)

    def test_stop_at_entry_rejected(self) -> None:
        for side in (Side.BUY, Side.SELL):
            with self.subTest(side=side.value):
                with self.assertRaises(DomainInvariantError):
                    StopLoss(price=4000.0, entry_price=4000.0, side=side)

    def test_legacy_abs_distance_masks_an_inverted_trade(self) -> None:
        """``entry_engine`` computes ``abs(entry - stop)`` with no side check."""
        inverted_risk = abs(4000.0 - 4010.0)
        self.assertAlmostEqual(inverted_risk, 10.0)  # looks perfectly normal
        with self.assertRaises(DomainInvariantError):
            StopLoss(price=4010.0, entry_price=4000.0, side=Side.BUY)

    def test_take_profit_side_enforced(self) -> None:
        self.assertEqual(
            TakeProfit(price=4020.0, entry_price=4000.0, side=Side.BUY).reward_distance,
            PriceDistance(20.0),
        )
        with self.assertRaises(DomainInvariantError):
            TakeProfit(price=3990.0, entry_price=4000.0, side=Side.BUY)
        with self.assertRaises(DomainInvariantError):
            TakeProfit(price=4010.0, entry_price=4000.0, side=Side.SELL)


class SignalTests(unittest.TestCase):
    """Entry, stop and target must agree with each other and with the side."""

    def _signal(self, **overrides: object) -> Signal:
        base = dict(
            side=Side.BUY,
            entry_price=4000.0,
            stop_loss=StopLoss(price=3990.0, entry_price=4000.0, side=Side.BUY),
            take_profit=TakeProfit(price=4020.0, entry_price=4000.0, side=Side.BUY),
            signal_type=SignalType.ENTRY,
            timestamp=MOMENT,
        )
        base.update(overrides)
        return Signal(**base)  # type: ignore[arg-type]

    def test_reward_risk_is_a_real_measurement(self) -> None:
        self.assertAlmostEqual(self._signal().reward_risk_ratio, 2.0)

    def test_reward_risk_reflects_actual_levels_not_a_config_constant(self) -> None:
        """Unlike the legacy ratio, which equals ``tp_ratio`` by construction."""
        wide = self._signal(
            take_profit=TakeProfit(price=4050.0, entry_price=4000.0, side=Side.BUY)
        )
        self.assertAlmostEqual(wide.reward_risk_ratio, 5.0)

    def test_signal_without_target_has_no_ratio(self) -> None:
        self.assertIsNone(self._signal(take_profit=None).reward_risk_ratio)

    def test_side_mismatch_with_stop_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._signal(
                side=Side.SELL,
                take_profit=None,
                stop_loss=StopLoss(price=3990.0, entry_price=4000.0, side=Side.BUY),
            )

    def test_entry_price_mismatch_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._signal(entry_price=4001.0)

    def test_confidence_bounds_enforced(self) -> None:
        for bad in (-1.0, 101.0):
            with self.subTest(confidence=bad):
                with self.assertRaises(DomainInvariantError):
                    self._signal(confidence=bad)

    def test_risk_distance_is_typed(self) -> None:
        self.assertEqual(self._signal().risk_distance.to_pips(XAUUSD_2DIGIT), Pips(100.0))


class RiskParametersTests(unittest.TestCase):
    """Risk is a typed percentage, never a bare float."""

    def test_valid(self) -> None:
        params = RiskParameters(risk_per_trade=Percentage(1.0))
        self.assertEqual(params.risk_per_trade, Percentage(1.0))
        self.assertEqual(params.max_daily_loss, Percentage(5.0))

    def test_bare_float_rejected(self) -> None:
        """``1.0`` is ambiguous between 1 % and 100 %."""
        with self.assertRaises(DomainInvariantError):
            RiskParameters(risk_per_trade=1.0)  # type: ignore[arg-type]

    def test_non_positive_risk_rejected(self) -> None:
        for bad in (0.0, -1.0):
            with self.subTest(value=bad):
                with self.assertRaises(DomainInvariantError):
                    RiskParameters(risk_per_trade=Percentage(bad))

    def test_risk_above_one_hundred_percent_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            RiskParameters(risk_per_trade=Percentage(150.0))

    def test_position_caps_must_be_positive(self) -> None:
        with self.assertRaises(DomainInvariantError):
            RiskParameters(risk_per_trade=Percentage(1.0), max_concurrent_positions=0)
        with self.assertRaises(DomainInvariantError):
            RiskParameters(risk_per_trade=Percentage(1.0), max_positions_per_day=0)


class StructureTypeTests(unittest.TestCase):
    """Swings, levels, sweeps, order blocks and gaps."""

    def test_swing_point_confirmation_lag_is_explicit(self) -> None:
        fresh = SwingPoint(timestamp=MOMENT, price=4000.0, swing_type=SwingType.HIGH,
                           bars_since=1, confirmation_bars=2)
        confirmed = SwingPoint(timestamp=MOMENT, price=4000.0, swing_type=SwingType.HIGH,
                               bars_since=2, confirmation_bars=2)
        self.assertFalse(fresh.is_confirmed)
        self.assertTrue(confirmed.is_confirmed)

    def test_liquidity_level_score_bounds(self) -> None:
        with self.assertRaises(DomainInvariantError):
            LiquidityLevel(price=4000.0, kind=LiquidityLevelKind.EQUAL_HIGH, score=101.0)

    def test_liquidity_level_distance_is_typed(self) -> None:
        level = LiquidityLevel(price=4002.0, kind=LiquidityLevelKind.PREVIOUS_DAY_HIGH)
        self.assertEqual(level.distance_from(4000.0).to_pips(XAUUSD_2DIGIT), Pips(20.0))

    def test_valid_bullish_sweep(self) -> None:
        level = LiquidityLevel(price=4000.0, kind=LiquidityLevelKind.EQUAL_LOW)
        sweep = LiquiditySweep(level=level, side=Side.BUY, wick_extreme=3995.0,
                               close_price=4002.0, timestamp=MOMENT)
        self.assertEqual(sweep.depth, PriceDistance(5.0))

    def test_sweep_geometry_enforced(self) -> None:
        level = LiquidityLevel(price=4000.0, kind=LiquidityLevelKind.EQUAL_LOW)
        # bullish sweep must wick below the level
        with self.assertRaises(DomainInvariantError):
            LiquiditySweep(level=level, side=Side.BUY, wick_extreme=4005.0,
                           close_price=4002.0, timestamp=MOMENT)
        # ...and close back above it
        with self.assertRaises(DomainInvariantError):
            LiquiditySweep(level=level, side=Side.BUY, wick_extreme=3995.0,
                           close_price=3998.0, timestamp=MOMENT)

    def test_order_block_bounds(self) -> None:
        block = OrderBlock(top=4010.0, bottom=4000.0, side=Side.BUY, timestamp=MOMENT)
        self.assertEqual(block.height, PriceDistance(10.0))
        self.assertAlmostEqual(block.midpoint, 4005.0)
        self.assertTrue(block.contains(4005.0))
        self.assertFalse(block.contains(3999.0))

    def test_inverted_order_block_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            OrderBlock(top=4000.0, bottom=4010.0, side=Side.BUY, timestamp=MOMENT)

    def test_fair_value_gap_must_have_height(self) -> None:
        with self.assertRaises(DomainInvariantError):
            FairValueGap(top=4000.0, bottom=4000.0,
                         kind=FairValueGapKind.BULLISH, timestamp=MOMENT)

    def test_fair_value_gap_fill(self) -> None:
        gap = FairValueGap(top=4010.0, bottom=4000.0,
                           kind=FairValueGapKind.BULLISH, timestamp=MOMENT,
                           fill_fraction=1.0)
        self.assertTrue(gap.is_filled)
        self.assertAlmostEqual(gap.midpoint, 4005.0)

    def test_fill_fraction_bounds(self) -> None:
        with self.assertRaises(DomainInvariantError):
            FairValueGap(top=4010.0, bottom=4000.0, kind=FairValueGapKind.BULLISH,
                         timestamp=MOMENT, fill_fraction=1.5)

    def test_setup_rejects_contradictory_evidence(self) -> None:
        level = LiquidityLevel(price=4000.0, kind=LiquidityLevelKind.EQUAL_LOW)
        bullish_sweep = LiquiditySweep(level=level, side=Side.BUY, wick_extreme=3995.0,
                                       close_price=4002.0, timestamp=MOMENT)
        with self.assertRaises(DomainInvariantError):
            TradingSetup(side=Side.SELL, timeframe=Timeframe.M15,
                         timestamp=MOMENT, sweep=bullish_sweep)

    def test_setup_accepts_consistent_evidence(self) -> None:
        level = LiquidityLevel(price=4000.0, kind=LiquidityLevelKind.EQUAL_LOW)
        sweep = LiquiditySweep(level=level, side=Side.BUY, wick_extreme=3995.0,
                               close_price=4002.0, timestamp=MOMENT)
        setup = TradingSetup(side=Side.BUY, timeframe=Timeframe.M15,
                             timestamp=MOMENT, sweep=sweep)
        self.assertIs(setup.sweep, sweep)


class ExecutionTypeTests(unittest.TestCase):
    """Order requests, results and positions.

    Constructing these submits nothing; live execution is locked in Phase 0/1.
    """

    def _request(self, **overrides: object) -> OrderRequest:
        base = dict(symbol="XAUUSD", side=Side.BUY, volume=0.10)
        base.update(overrides)
        return OrderRequest(**base)  # type: ignore[arg-type]

    def test_valid_market_request(self) -> None:
        self.assertIs(self._request().kind, OrderKind.MARKET)

    def test_non_positive_volume_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._request(volume=0.0)

    def test_limit_order_requires_entry_price(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._request(kind=OrderKind.LIMIT)

    def test_untyped_slippage_rejected(self) -> None:
        """A bare number is ambiguous between price units and pips."""
        with self.assertRaises(DomainInvariantError):
            self._request(max_slippage=2.0)

    def test_typed_slippage_accepted(self) -> None:
        request = self._request(max_slippage=Pips(2.0).to_price(XAUUSD_2DIGIT))
        self.assertEqual(request.max_slippage, PriceDistance(0.2))

    def test_validated_for_checks_broker_volume_grid(self) -> None:
        self._request(volume=0.10).validated_for(XAUUSD_2DIGIT)
        with self.assertRaises(DomainInvariantError):
            self._request(volume=0.004).validated_for(XAUUSD_2DIGIT)

    def test_validated_for_rejects_symbol_mismatch(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._request(symbol="EURUSD").validated_for(XAUUSD_2DIGIT)

    def test_filled_result_requires_a_fill_price(self) -> None:
        with self.assertRaises(DomainInvariantError):
            OrderResult(status=OrderResultStatus.FILLED, request=self._request(),
                        filled_volume=0.10)

    def test_overfill_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            OrderResult(status=OrderResultStatus.FILLED, request=self._request(volume=0.10),
                        filled_volume=0.20, fill_price=4000.0)

    def test_slippage_measurement_is_typed(self) -> None:
        result = OrderResult(status=OrderResultStatus.FILLED, request=self._request(),
                             filled_volume=0.10, fill_price=4000.5)
        self.assertEqual(result.slippage_against(4000.0), PriceDistance(0.5))
        self.assertTrue(result.is_success)

    def test_unfilled_result_has_no_slippage(self) -> None:
        result = OrderResult(status=OrderResultStatus.NOT_SUBMITTED, request=self._request())
        self.assertIsNone(result.slippage_against(4000.0))
        self.assertFalse(result.is_success)


class PositionTests(unittest.TestCase):
    """Positions default to unverified until reconciled against the broker."""

    def _position(self, **overrides: object) -> Position:
        base = dict(position_id="T-1", symbol="XAUUSD", side=Side.BUY,
                    volume=0.10, entry_price=4000.0, opened_at=MOMENT)
        base.update(overrides)
        return Position(**base)  # type: ignore[arg-type]

    def test_defaults_to_unverified(self) -> None:
        """The phantom positions were trusted precisely because nothing checked."""
        self.assertFalse(self._position().broker_verified)

    def test_open_position_requires_volume(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._position(volume=0.0, status=PositionStatus.OPEN)

    def test_closed_position_requires_zero_volume(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._position(volume=0.10, status=PositionStatus.CLOSED)

    def test_is_protected_reports_missing_stop(self) -> None:
        self.assertFalse(self._position().is_protected)
        self.assertTrue(self._position(stop_loss=3990.0).is_protected)

    def test_unrealised_move_is_signed_by_direction(self) -> None:
        long_position = self._position(side=Side.BUY)
        short_position = self._position(side=Side.SELL)
        self.assertEqual(long_position.unrealised_price_move(4010.0), PriceDistance(10.0))
        self.assertEqual(short_position.unrealised_price_move(4010.0), PriceDistance(-10.0))
        self.assertEqual(short_position.unrealised_price_move(3990.0), PriceDistance(10.0))

    def test_empty_identifiers_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._position(position_id="")
        with self.assertRaises(DomainInvariantError):
            self._position(symbol="")

    def test_naive_open_time_rejected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self._position(opened_at=NAIVE)


if __name__ == "__main__":
    unittest.main()
