"""Data-leakage tests -- the highest-priority group in Phase 2A.

A backtest that can see the future is not merely inaccurate, it is actively
misleading: it produces plausible, encouraging numbers that cannot be reproduced
live. These tests attack the invariant empirically rather than trusting any
docstring.

Test A  mutate bars far in the future; every earlier decision must be identical
Test B  at every replay instant, no visible bar may close after that instant
Test C  per-layer -- indicators, structure, liquidity, POI and signals must all
        be unchanged by future mutation, not merely the final verdict
Test D  boundary -- a bar closing exactly at T is visible; one closing a second
        later is not
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
    """Build a full multi-timeframe dataset from one M1 series."""
    frames = {Timeframe.M1: m1}
    for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
        frames[timeframe] = resample_from_m1(m1, timeframe)
    return HistoricalDataset("XAUUSD", frames)


def _mutate_future(m1: pd.DataFrame, from_index: int) -> pd.DataFrame:
    """Return a copy with every bar from ``from_index`` onward violently changed.

    The mutation is large and obvious. A subtle change could pass by luck; a
    +500 shift cannot.
    """
    mutated = m1.copy(deep=True)
    tail = mutated.index >= from_index
    for column in ("open", "high", "low", "close"):
        mutated.loc[tail, column] = mutated.loc[tail, column] + 500.0
    mutated.loc[tail, "tick_volume"] = 9_999.0
    return mutated


class TestBNoFutureBarIsVisible(unittest.TestCase):
    """Test B: at every instant, nothing visible may close after that instant."""

    def setUp(self) -> None:
        self.feed = ReplayFeed(_dataset_from_m1(make_trending_m1(BARS)))

    def test_no_visible_bar_closes_after_the_replay_instant(self) -> None:
        checked = 0
        for minutes in range(1_000, BARS, 250):
            now = SYNTHETIC_START + timedelta(minutes=minutes)
            for timeframe in (
                Timeframe.M1, Timeframe.M5, Timeframe.M15,
                Timeframe.H1, Timeframe.H4, Timeframe.D1,
            ):
                frame = self.feed.bars(timeframe, 200, now, require_full=False)
                if frame.empty:
                    continue
                closes = frame["time"] + timedelta(minutes=timeframe.minutes)
                self.assertTrue(
                    (closes <= pd.Timestamp(now)).all(),
                    f"{timeframe.value} exposed a bar closing after {now}",
                )
                checked += 1
        self.assertGreater(checked, 50, "too few combinations actually checked")

    def test_frame_end_never_exceeds_the_instant(self) -> None:
        for minutes in (1_500, 3_000, 5_000):
            now = SYNTHETIC_START + timedelta(minutes=minutes)
            snapshot = self.feed.availability_snapshot(now)
            for timeframe, availability in snapshot.items():
                with self.subTest(minutes=minutes, timeframe=timeframe.value):
                    if availability.latest_close_time is None:
                        continue
                    self.assertLessEqual(availability.latest_close_time, pd.Timestamp(now))


class TestDBoundaryVisibility(unittest.TestCase):
    """Test D: the close boundary is inclusive, and exact."""

    def setUp(self) -> None:
        self.feed = ReplayFeed(_dataset_from_m1(make_trending_m1(2_000)))

    def test_bar_is_visible_exactly_at_its_close(self) -> None:
        # The M5 bar opening at +100min closes at +105min.
        at_close = SYNTHETIC_START + timedelta(minutes=105)
        frame = self.feed.bars(Timeframe.M5, 1, at_close)
        self.assertEqual(
            pd.Timestamp(frame["time"].iloc[-1]),
            pd.Timestamp(SYNTHETIC_START + timedelta(minutes=100)),
        )

    def test_bar_is_not_visible_one_second_before_its_close(self) -> None:
        just_before = SYNTHETIC_START + timedelta(minutes=104, seconds=59)
        frame = self.feed.bars(Timeframe.M5, 1, just_before)
        self.assertLess(
            pd.Timestamp(frame["time"].iloc[-1]),
            pd.Timestamp(SYNTHETIC_START + timedelta(minutes=100)),
        )

    def test_one_second_of_difference_changes_what_is_visible(self) -> None:
        before = self.feed.bars(
            Timeframe.M5, 1, SYNTHETIC_START + timedelta(minutes=104, seconds=59)
        )
        after = self.feed.bars(Timeframe.M5, 1, SYNTHETIC_START + timedelta(minutes=105))
        self.assertNotEqual(
            pd.Timestamp(before["time"].iloc[-1]), pd.Timestamp(after["time"].iloc[-1])
        )


class TestAFutureMutationTests(unittest.TestCase):
    """Test A: changing the future must not change the past."""

    def setUp(self) -> None:
        self.original = make_trending_m1(BARS)
        self.mutated = _mutate_future(self.original, MUTATION_POINT)
        self.feed_original = ReplayFeed(_dataset_from_m1(self.original))
        self.feed_mutated = ReplayFeed(_dataset_from_m1(self.mutated))
        self.cutoff = SYNTHETIC_START + timedelta(minutes=MUTATION_POINT)

    def test_the_mutation_is_actually_material(self) -> None:
        """Guards against the whole suite passing because nothing changed."""
        after = self.cutoff + timedelta(minutes=500)
        before_frame = self.feed_original.bars(Timeframe.M5, 10, after)
        after_frame = self.feed_mutated.bars(Timeframe.M5, 10, after)
        self.assertFalse(before_frame.equals(after_frame))

    def test_bars_before_the_cutoff_are_identical(self) -> None:
        for minutes in (1_200, 2_000, 3_000, MUTATION_POINT - 10):
            now = SYNTHETIC_START + timedelta(minutes=minutes)
            for timeframe in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1):
                with self.subTest(minutes=minutes, timeframe=timeframe.value):
                    pd.testing.assert_frame_equal(
                        self.feed_original.bars(timeframe, 100, now, require_full=False),
                        self.feed_mutated.bars(timeframe, 100, now, require_full=False),
                    )

    def test_prices_before_the_cutoff_are_identical(self) -> None:
        for minutes in (1_000, 2_500, MUTATION_POINT - 1):
            now = SYNTHETIC_START + timedelta(minutes=minutes)
            with self.subTest(minutes=minutes):
                self.assertEqual(
                    self.feed_original.price_at(now), self.feed_mutated.price_at(now)
                )


class TestCPerLayerTests(unittest.TestCase):
    """Test C: each analysis layer, not only the final signal.

    A final-signal-only test can pass by coincidence -- two different inputs can
    both block at L1. Checking indicators, structure, liquidity and POI
    separately removes that escape route.
    """

    def setUp(self) -> None:
        original = make_trending_m1(BARS)
        mutated = _mutate_future(original, MUTATION_POINT)
        self.feed_original = ReplayFeed(_dataset_from_m1(original))
        self.feed_mutated = ReplayFeed(_dataset_from_m1(mutated))
        self.instants = [
            SYNTHETIC_START + timedelta(minutes=m)
            for m in (2_000, 2_800, 3_500, MUTATION_POINT - 5)
        ]

    def _frames(self, feed: ReplayFeed, now):
        return {
            "h4": feed.bars(Timeframe.H4, 100, now, require_full=False),
            "h1": feed.bars(Timeframe.H1, 60, now, require_full=False),
            "m15": feed.bars(Timeframe.M15, 50, now, require_full=False),
            "m5": feed.bars(Timeframe.M5, 100, now, require_full=False),
            "d1": feed.bars(Timeframe.D1, 10, now, require_full=False),
        }

    def test_indicators_are_unchanged(self) -> None:
        from indicators import calculate_indicators

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a = self._frames(self.feed_original, now)["m15"]
                b = self._frames(self.feed_mutated, now)["m15"]
                if a.empty:
                    continue
                self.assertEqual(calculate_indicators(a), calculate_indicators(b))

    def test_structure_is_unchanged(self) -> None:
        from structure_engine import get_h1_structure

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a = self._frames(self.feed_original, now)["h1"]
                b = self._frames(self.feed_mutated, now)["h1"]
                if a.empty:
                    continue
                self.assertEqual(
                    get_h1_structure(a, "BULLISH"), get_h1_structure(b, "BULLISH")
                )

    def test_liquidity_is_unchanged(self) -> None:
        from liquidity_engine import identify_liquidity_pools

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a = self._frames(self.feed_original, now)
                b = self._frames(self.feed_mutated, now)
                if a["m15"].empty:
                    continue
                price = self.feed_original.price_at(now)
                self.assertEqual(
                    identify_liquidity_pools(
                        a["m15"], h1_data=a["h1"], h4_data=a["h4"],
                        daily_data=a["d1"], current_price=price, side="BUY",
                    ),
                    identify_liquidity_pools(
                        b["m15"], h1_data=b["h1"], h4_data=b["h4"],
                        daily_data=b["d1"], current_price=price, side="BUY",
                    ),
                )

    def test_poi_is_unchanged(self) -> None:
        from poi_engine import identify_poi

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a = self._frames(self.feed_original, now)
                b = self._frames(self.feed_mutated, now)
                if a["m15"].empty:
                    continue
                price = self.feed_original.price_at(now)
                self.assertEqual(
                    identify_poi(a["m15"], h1_data=a["h1"], direction="BUY", current_price=price),
                    identify_poi(b["m15"], h1_data=b["h1"], direction="BUY", current_price=price),
                )

    def test_pullback_is_unchanged(self) -> None:
        from pullback_detector import get_m15_pullback

        for now in self.instants:
            with self.subTest(now=now.isoformat()):
                a = self._frames(self.feed_original, now)["m15"]
                b = self._frames(self.feed_mutated, now)["m15"]
                if a.empty:
                    continue
                self.assertEqual(get_m15_pullback(a, "BULLISH"), get_m15_pullback(b, "BULLISH"))

    def test_layers_do_change_once_the_mutation_is_inside_the_window(self) -> None:
        """The converse: past the cutoff the layers MUST differ.

        Without this, every test above could pass because the layers are
        insensitive to their input rather than because leakage is prevented.
        """
        from indicators import calculate_indicators

        well_after = SYNTHETIC_START + timedelta(minutes=MUTATION_POINT + 800)
        a = self._frames(self.feed_original, well_after)["m15"]
        b = self._frames(self.feed_mutated, well_after)["m15"]
        self.assertNotEqual(calculate_indicators(a), calculate_indicators(b))


if __name__ == "__main__":
    unittest.main()
