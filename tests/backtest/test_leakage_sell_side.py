"""Phase 6Q -- SELL-side and bias/sweep temporal coverage.

``tests/backtest/test_leakage.py`` proves per-layer temporal correctness for
indicators, structure, liquidity, POI and pullback -- but every one of those runs
**BULLISH/BUY only**, and Phase 6O measured that ``bias`` and ``sweep`` appear
**zero times** in either leakage file. L1 decides the direction of the whole
pipeline and L5 is the second-largest gate; neither had any temporal test.

This module closes both gaps using the same method: build one synthetic series,
mutate every bar after a cutoff by +500, and assert that decisions taken *before*
the cutoff are byte-identical. A layer that reached forward would change.

Production logic is untouched. Where a layer cannot be tested this way, it is
recorded as a TEST GAP in ``docs/PHASE_6Q_REMAINING_PINS.md`` rather than given
an invented test.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

import pandas as pd

from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from data.timeframes import resample_from_m1
from tests.fixtures.market import SYNTHETIC_START, make_trending_m1

BARS = 6_000
MUTATION_POINT = 4_000


def _dataset_from_m1(m1: pd.DataFrame) -> HistoricalDataset:
    frames = {Timeframe.M1: m1}
    for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
        frames[timeframe] = resample_from_m1(m1, timeframe)
    return HistoricalDataset("XAUUSD", frames)


def _mutate_future(m1: pd.DataFrame, from_index: int) -> pd.DataFrame:
    mutated = m1.copy(deep=True)
    tail = mutated.index >= from_index
    for column in ("open", "high", "low", "close"):
        mutated.loc[tail, column] = mutated.loc[tail, column] + 500.0
    mutated.loc[tail, "tick_volume"] = 9_999.0
    return mutated


class _MutationHarness(unittest.TestCase):
    """Shared original/mutated feeds and the pre-cutoff instants to compare."""

    @classmethod
    def setUpClass(cls) -> None:
        original = make_trending_m1(BARS)
        cls.feed_original = ReplayFeed(_dataset_from_m1(original))
        cls.feed_mutated = ReplayFeed(_dataset_from_m1(_mutate_future(original, MUTATION_POINT)))
        cls.instants = [
            SYNTHETIC_START + timedelta(minutes=minutes)
            for minutes in (2_000, 2_800, 3_500, MUTATION_POINT - 5)
        ]

    def _frames(self, feed: ReplayFeed, now):
        return {
            "h4": feed.bars(Timeframe.H4, 100, now, require_full=False),
            "h1": feed.bars(Timeframe.H1, 60, now, require_full=False),
            "m15": feed.bars(Timeframe.M15, 50, now, require_full=False),
            "m5": feed.bars(Timeframe.M5, 100, now, require_full=False),
            "m1": feed.bars(Timeframe.M1, 200, now, require_full=False),
            "d1": feed.bars(Timeframe.D1, 10, now, require_full=False),
        }

    def _pairs(self, now):
        return self._frames(self.feed_original, now), self._frames(self.feed_mutated, now)


class BiasIsUnaffectedByFutureData(_MutationHarness):
    """Phase 6O-E: L1 had no temporal test at all, and it decides ``side``."""

    def test_h4_bias_is_unchanged(self) -> None:
        from bias_engine import get_h4_bias
        from indicators import calculate_indicators

        compared = 0
        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["h4"].empty:
                    continue
                compared += 1
                indicators_a = calculate_indicators(a["h4"]) or {}
                indicators_b = calculate_indicators(b["h4"]) or {}
                indicators_a["closes_2"] = [float(v) for v in a["h4"]["close"].tail(2).tolist()]
                indicators_b["closes_2"] = [float(v) for v in b["h4"]["close"].tail(2).tolist()]
                self.assertEqual(
                    get_h4_bias(indicators_a, daily_data=a["d1"], h4_data=a["h4"]),
                    get_h4_bias(indicators_b, daily_data=b["d1"], h4_data=b["h4"]),
                )
        self.assertGreater(compared, 0)

    def test_fast_bias_is_unchanged(self) -> None:
        from bias_engine import get_fast_bias
        from indicators import calculate_indicators

        compared = 0
        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["h1"].empty:
                    continue
                compared += 1
                self.assertEqual(
                    get_fast_bias(calculate_indicators(a["h1"]) or {}, h1_data=a["h1"]),
                    get_fast_bias(calculate_indicators(b["h1"]) or {}, h1_data=b["h1"]),
                )
        self.assertGreater(compared, 0)

    def test_the_swing_finder_is_unchanged(self) -> None:
        from bias_engine import _find_h4_swings

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["h4"].empty:
                    continue
                self.assertEqual(_find_h4_swings(a["h4"]), _find_h4_swings(b["h4"]))

    def test_bias_labels_stay_within_the_declared_set(self) -> None:
        """Boundary/neutral pin: only three labels may ever be produced."""
        from bias_engine import get_fast_bias
        from indicators import calculate_indicators

        seen = set()
        for now in self.instants:
            a, _ = self._pairs(now)
            if a["h1"].empty:
                continue
            seen.add(get_fast_bias(calculate_indicators(a["h1"]) or {}, h1_data=a["h1"])["bias"])
        self.assertTrue(seen <= {"BULLISH", "BEARISH", "NEUTRAL"}, seen)

    def test_missing_ema_data_yields_neutral(self) -> None:
        from bias_engine import get_fast_bias

        self.assertEqual(get_fast_bias({}, h1_data=None)["bias"], "NEUTRAL")


class SweepIsUnaffectedByFutureData(_MutationHarness):
    """Phase 6O-C: L5 was the one layer omitted from the mutation suite."""

    def _level(self, frames, direction):
        m15 = frames["m15"]
        return float(m15["low"].min() if direction == "BUY" else m15["high"].max())

    def test_detect_sweep_is_unchanged_both_directions(self) -> None:
        from sweep_detector import detect_sweep

        compared = 0
        for now in self.instants:
            for direction in ("BUY", "SELL"):
                with self.subTest(now=now.isoformat(), direction=direction):
                    a, b = self._pairs(now)
                    if a["m15"].empty:
                        continue
                    compared += 1
                    level = self._level(a, direction)
                    self.assertEqual(
                        detect_sweep(a["m15"], level, direction),
                        detect_sweep(b["m15"], level, direction),
                    )
        self.assertGreater(compared, 0)

    def test_detect_choch_is_unchanged_both_directions(self) -> None:
        from sweep_detector import detect_choch

        for now in self.instants:
            for direction in ("BUY", "SELL"):
                with self.subTest(now=now.isoformat(), direction=direction):
                    a, b = self._pairs(now)
                    if a["m15"].empty:
                        continue
                    self.assertEqual(
                        detect_choch(a["m15"], direction), detect_choch(b["m15"], direction)
                    )

    def test_detect_bos_is_unchanged_both_directions(self) -> None:
        from sweep_detector import detect_bos

        for now in self.instants:
            for direction in ("BUY", "SELL"):
                with self.subTest(now=now.isoformat(), direction=direction):
                    a, b = self._pairs(now)
                    if a["h1"].empty:
                        continue
                    self.assertEqual(
                        detect_bos(a["h1"], direction), detect_bos(b["h1"], direction)
                    )

    def test_get_sweep_and_structure_is_unchanged_both_directions(self) -> None:
        from sweep_detector import get_sweep_and_structure

        for now in self.instants:
            for direction in ("BUY", "SELL"):
                with self.subTest(now=now.isoformat(), direction=direction):
                    a, b = self._pairs(now)
                    if a["m15"].empty or a["h1"].empty:
                        continue
                    level = self._level(a, direction)
                    self.assertEqual(
                        get_sweep_and_structure(a["m15"], a["h1"], level, direction),
                        get_sweep_and_structure(b["m15"], b["h1"], level, direction),
                    )

    def test_penetration_band_is_pips_and_direction_specific(self) -> None:
        """Pins the penetration band and the polarity, deterministically.

        **This test used to pin the defect, and predicted its own inversion.**
        It asserted a $2.50 floor and noted: "Under the documented '3-8 pips'
        reading the first would be far too deep and the second would qualify."
        That reading is now the implemented one (U8, fixed under
        ``research/unit_migration_spec.md`` Rule 1), so the second case does
        qualify and the assertions move to the real band edges.

        The band is ``[max(2.5 pips, atr*0.12), max(30 pips, atr*2.0)]``. On this
        low-volatility fixture (M15 ATR $0.057) the pip floors bind, giving
        **[$0.25, $3.00]**. Correcting the unit is also what made ``atr*0.12``
        reachable at all: at the old $2.50 floor the constant bound on 98.8% of
        real bars, so the one scale-aware term in the module was dead code.
        """
        from sweep_detector import detect_sweep

        def frame(low: float, high: float, close: float) -> pd.DataFrame:
            rows = [
                {"time": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=15 * i),
                 "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.0,
                 "tick_volume": 100.0}
                for i in range(14)
            ]
            rows.append({"time": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=15 * 14),
                         "open": 4000.0, "high": high, "low": low, "close": close,
                         "tick_volume": 300.0})
            return pd.DataFrame(rows)

        # The band edges are DERIVED per frame, not hardcoded. Two reasons, and
        # the second only became visible once the first was fixed:
        #
        # 1. The first version pinned "$0.25" and "$3.00" as literals, which
        #    broke the moment A3 was fixed -- `sweep_max` is
        #    `max(30 pips, m15_atr * 2.0)`, and a correct Wilder ATR is larger
        #    than the close-only surrogate it replaced, so the ceiling moved.
        #
        # 2. `sweep_max` depends on the ATR of THE VERY FRAME whose wick is
        #    being tested. A deeper wick raises that bar's true range, which
        #    raises the ATR, which raises the ceiling -- so the ceiling
        #    partially chases the wick. A single ceiling computed from one probe
        #    frame is therefore wrong for every other frame. Worth recording as
        #    a property of the gate: `sweep_max` is not a fixed level.
        from sweep_detector import (SWEEP_MAX_PIPS, SWEEP_MIN_PIPS, XAUUSD_SPEC,
                                    _estimate_m15_atr)

        def band_for(candidate: pd.DataFrame) -> tuple[float, float]:
            atr = _estimate_m15_atr(candidate)
            self.assertIsNotNone(atr, "the fixture must support an ATR")
            return (max(SWEEP_MIN_PIPS.to_price(XAUUSD_SPEC).value, atr * 0.12),
                    max(SWEEP_MAX_PIPS.to_price(XAUUSD_SPEC).value, atr * 2.0))

        reference = frame(low=3997.50, high=4001.0, close=4000.8)
        ref_floor, ref_ceiling = band_for(reference)
        self.assertLess(ref_floor, ref_ceiling, "the band must be non-empty")

        # Inside the band: each candidate checked against ITS OWN edges.
        for depth in (ref_floor + 0.01,
                      ref_floor + (ref_ceiling - ref_floor) * 0.5):
            candidate = frame(low=4000.0 - depth, high=4001.0, close=4000.8)
            floor, ceiling = band_for(candidate)
            if not floor <= depth <= ceiling:
                continue  # the edges moved past this sample; not a band claim
            result = detect_sweep(candidate, 4000.0, "BUY")
            self.assertTrue(
                result["sweep_confirmed"],
                f"a ${depth:.2f} wick is inside its own "
                f"[${floor:.2f}, ${ceiling:.2f}] band")
            self.assertEqual(result["sweep_type"], "bullish_sweep")

        # Below the floor: too shallow to have taken any stops. A shallower wick
        # cannot raise the ATR, so the floor does not move away from it.
        for depth in (ref_floor * 0.5, ref_floor - 0.01):
            candidate = frame(low=4000.0 - depth, high=4001.0, close=4000.8)
            floor, _ = band_for(candidate)
            self.assertLess(depth, floor)
            self.assertFalse(
                detect_sweep(candidate, 4000.0, "BUY")["sweep_confirmed"],
                f"a ${depth:.2f} wick is below the ${floor:.2f} floor")

        # Above the ceiling: a break, not a sweep. Found by search rather than
        # arithmetic, precisely because the ceiling chases the wick -- the
        # assertion is that such a depth EXISTS and is rejected.
        rejected_above = None
        depth = ref_ceiling
        for _ in range(60):
            depth *= 1.5
            candidate = frame(low=4000.0 - depth, high=4001.0, close=4000.8)
            _, ceiling = band_for(candidate)
            if depth > ceiling:
                rejected_above = (depth, ceiling)
                break
        self.assertIsNotNone(
            rejected_above,
            "no wick depth exceeded the ceiling, so sweep_max never rejects -- "
            "which is what U4's $60 cap did before it was fixed")
        depth, ceiling = rejected_above
        candidate = frame(low=4000.0 - depth, high=4001.0, close=4000.8)
        self.assertFalse(
            detect_sweep(candidate, 4000.0, "BUY")["sweep_confirmed"],
            f"a ${depth:.2f} wick exceeds the ${ceiling:.2f} ceiling")


    def test_a_buy_request_never_returns_a_bearish_sweep(self) -> None:
        from sweep_detector import detect_sweep

        for now in self.instants:
            a, _ = self._pairs(now)
            if a["m15"].empty:
                continue
            for direction, forbidden in (("BUY", "bearish"), ("SELL", "bullish")):
                result = detect_sweep(a["m15"], self._level(a, direction), direction)
                self.assertNotIn(forbidden, str(result.get("sweep_type")))


class SellSidePerLayerTemporalCoverage(_MutationHarness):
    """Every existing per-layer mutation test runs BULLISH/BUY only."""

    def test_structure_is_unchanged_for_bearish(self) -> None:
        from structure_engine import get_h1_structure

        compared = 0
        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["h1"].empty:
                    continue
                compared += 1
                self.assertEqual(
                    get_h1_structure(a["h1"], "BEARISH"), get_h1_structure(b["h1"], "BEARISH")
                )
        self.assertGreater(compared, 0)

    def test_pullback_is_unchanged_for_bearish(self) -> None:
        from pullback_detector import get_m15_pullback

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["m15"].empty:
                    continue
                self.assertEqual(
                    get_m15_pullback(a["m15"], "BEARISH"), get_m15_pullback(b["m15"], "BEARISH")
                )

    def test_liquidity_is_unchanged_for_sell(self) -> None:
        from liquidity_engine import identify_liquidity_pools

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["m15"].empty:
                    continue
                price = self.feed_original.price_at(now)
                self.assertEqual(
                    identify_liquidity_pools(
                        a["m15"], h1_data=a["h1"], h4_data=a["h4"], daily_data=a["d1"],
                        current_price=price, side="SELL",
                    ),
                    identify_liquidity_pools(
                        b["m15"], h1_data=b["h1"], h4_data=b["h4"], daily_data=b["d1"],
                        current_price=price, side="SELL",
                    ),
                )

    def test_poi_is_unchanged_for_sell(self) -> None:
        from poi_engine import identify_poi

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["m15"].empty:
                    continue
                price = self.feed_original.price_at(now)
                self.assertEqual(
                    identify_poi(a["m15"], h1_data=a["h1"], direction="SELL", current_price=price),
                    identify_poi(b["m15"], h1_data=b["h1"], direction="SELL", current_price=price),
                )

    def test_indicators_are_unchanged_on_every_timeframe(self) -> None:
        """The existing test covers M15 only."""
        from indicators import calculate_indicators

        for now in self.instants:
            a, b = self._pairs(now)
            for key in ("h4", "h1", "m15", "m5"):
                with self.subTest(now=now.isoformat(), timeframe=key):
                    if a[key].empty:
                        continue
                    self.assertEqual(calculate_indicators(a[key]), calculate_indicators(b[key]))

    def test_entry_trigger_is_unchanged_for_sell(self) -> None:
        """L8, where practical: the trigger reads M5 and M1 only."""
        from entry_engine import get_entry_trigger

        compared = 0
        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a, b = self._pairs(now)
                if a["m5"].empty or a["m1"].empty:
                    continue
                compared += 1
                price = self.feed_original.price_at(now)
                wick = float(a["m15"]["high"].max()) if not a["m15"].empty else price
                self.assertEqual(
                    get_entry_trigger(a["m5"], a["m1"], price, "SELL", sweep_wick_high=wick),
                    get_entry_trigger(b["m5"], b["m1"], price, "SELL", sweep_wick_high=wick),
                )
        self.assertGreater(compared, 0)


class ConfidenceHasNoTemporalSurface(unittest.TestCase):
    """L7 takes scalars, not frames, so it cannot read a future bar.

    Recorded as a pin rather than a gap: the absence of a frame argument is the
    proof. If a frame is ever added, this test fails and a mutation test becomes
    required.
    """

    def test_get_confidence_engine_takes_no_bar_frame(self) -> None:
        import inspect

        from confidence_engine import get_confidence_engine

        parameters = set(inspect.signature(get_confidence_engine).parameters)
        for frame_like in ("m1_data", "m5_data", "m15_data", "h1_data", "h4_data", "daily_data"):
            self.assertNotIn(frame_like, parameters)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
