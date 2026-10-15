"""Replay feed tests: availability, multi-timeframe sync, and no look-ahead.

The invariant under test::

    bar.open_time + timeframe.duration <= T

MetaTrader stamps a bar by its **open** time, so an M5 bar stamped 10:35 closes
at 10:40 and must not be visible at 10:37. Treating the stamp as a close time is
the classic silent look-ahead: it never raises and it makes every result
optimistic.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.types import Timeframe
from data.dataset import BAR_COLUMNS
from data.replay_feed import ReplayFeed
from data.timeframes import (
    bar_close_time,
    is_visible_at,
    latest_visible_open_time,
    resample_from_m1,
)
from tests.fixtures.market import SYNTHETIC_START, make_synthetic_dataset

UTC = timezone.utc


class TimeframeArithmeticTests(unittest.TestCase):
    """The primitive everything else rests on."""

    def test_bar_close_time(self) -> None:
        opened = datetime(2026, 5, 4, 10, 35, tzinfo=UTC)
        self.assertEqual(
            bar_close_time(opened, Timeframe.M5), datetime(2026, 5, 4, 10, 40, tzinfo=UTC)
        )

    def test_bar_stamped_1035_is_not_visible_at_1037(self) -> None:
        """The headline case."""
        opened = datetime(2026, 5, 4, 10, 35, tzinfo=UTC)
        now = datetime(2026, 5, 4, 10, 37, tzinfo=UTC)
        self.assertFalse(is_visible_at(opened, Timeframe.M5, now))

    def test_bar_becomes_visible_exactly_at_its_close(self) -> None:
        opened = datetime(2026, 5, 4, 10, 35, tzinfo=UTC)
        self.assertTrue(
            is_visible_at(opened, Timeframe.M5, datetime(2026, 5, 4, 10, 40, tzinfo=UTC))
        )

    def test_one_second_before_close_is_not_visible(self) -> None:
        opened = datetime(2026, 5, 4, 10, 35, tzinfo=UTC)
        self.assertFalse(
            is_visible_at(
                opened, Timeframe.M5, datetime(2026, 5, 4, 10, 39, 59, tzinfo=UTC)
            )
        )

    def test_worked_example_from_the_docs(self) -> None:
        """Mirrors the table in ``data/timeframes``.

        H4 is the instructive case: the bar opening at 08:00 does not close
        until 12:00, so at 10:37 the newest *visible* H4 bar is the one that
        opened at 04:00 and closed at 08:00.
        """
        now = datetime(2026, 5, 4, 10, 37, tzinfo=UTC)
        expected = {
            Timeframe.M1: "10:36",
            Timeframe.M5: "10:30",
            Timeframe.M15: "10:15",
            Timeframe.H1: "09:00",
            Timeframe.H4: "04:00",
        }
        for timeframe, want in expected.items():
            with self.subTest(timeframe=timeframe.value):
                self.assertEqual(
                    latest_visible_open_time(timeframe, now).strftime("%H:%M"), want
                )

    def test_on_a_boundary_the_opening_bar_is_not_yet_closed(self) -> None:
        now = datetime(2026, 5, 4, 10, 40, tzinfo=UTC)
        self.assertEqual(
            latest_visible_open_time(Timeframe.M5, now).strftime("%H:%M"), "10:35"
        )


class ResamplingTests(unittest.TestCase):
    """Derived bars must be internally consistent with their source."""

    def setUp(self) -> None:
        self.dataset = make_synthetic_dataset(bars=600)

    def test_h1_high_equals_max_of_its_m1_highs(self) -> None:
        m1 = self.dataset.frame(Timeframe.M1)
        h1 = self.dataset.frame(Timeframe.H1)
        first = h1.iloc[0]
        window = m1[
            (m1["time"] >= first["time"])
            & (m1["time"] < first["time"] + timedelta(hours=1))
        ]
        self.assertAlmostEqual(float(first["high"]), float(window["high"].max()), places=9)
        self.assertAlmostEqual(float(first["low"]), float(window["low"].min()), places=9)
        self.assertAlmostEqual(float(first["open"]), float(window["open"].iloc[0]), places=9)
        self.assertAlmostEqual(float(first["close"]), float(window["close"].iloc[-1]), places=9)

    def test_resampling_does_not_invent_bars_for_gaps(self) -> None:
        """A closed market has no bar; filling one would be fabricated data."""
        m1 = self.dataset.frame(Timeframe.M1)
        gapped = pd.concat([m1.iloc[:60], m1.iloc[300:]], ignore_index=True)
        resampled = resample_from_m1(gapped, Timeframe.H1)
        self.assertLess(len(resampled), 10)
        self.assertFalse(resampled[["open", "high", "low", "close"]].isna().any().any())

    def test_cannot_resample_m1_from_m1(self) -> None:
        with self.assertRaises(ValueError):
            resample_from_m1(self.dataset.frame(Timeframe.M1), Timeframe.M1)


class AvailabilityTests(unittest.TestCase):
    """The feed must never hand out a bar that has not closed."""

    def setUp(self) -> None:
        self.dataset = make_synthetic_dataset(bars=4000)
        self.feed = ReplayFeed(self.dataset)

    def test_no_returned_bar_has_closed_after_as_of(self) -> None:
        for offset_minutes in (500, 1500, 2500, 3500):
            now = SYNTHETIC_START + timedelta(minutes=offset_minutes)
            for timeframe in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1):
                with self.subTest(offset=offset_minutes, timeframe=timeframe.value):
                    frame = self.feed.bars(timeframe, 20, now, require_full=False)
                    if frame.empty:
                        continue
                    latest_close = frame["time"].iloc[-1] + timedelta(
                        minutes=timeframe.minutes
                    )
                    self.assertLessEqual(latest_close, pd.Timestamp(now))

    def test_frame_matches_the_production_column_contract(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=2000)
        frame = self.feed.bars(Timeframe.M5, 50, now)
        self.assertEqual(list(frame.columns), list(BAR_COLUMNS))
        self.assertEqual(list(frame.index), list(range(len(frame))))
        self.assertIsNotNone(frame["time"].dt.tz)

    def test_short_history_returns_empty_like_production(self) -> None:
        """``get_market_data`` returns empty rather than a partial frame."""
        near_start = SYNTHETIC_START + timedelta(minutes=10)
        self.assertTrue(self.feed.bars(Timeframe.M5, 100, near_start).empty)

    def test_require_full_false_allows_partial_inspection(self) -> None:
        near_start = SYNTHETIC_START + timedelta(minutes=30)
        partial = self.feed.bars(Timeframe.M5, 100, near_start, require_full=False)
        self.assertGreater(len(partial), 0)
        self.assertLess(len(partial), 100)

    def test_requested_count_is_respected(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=3000)
        self.assertEqual(len(self.feed.bars(Timeframe.M5, 40, now)), 40)

    def test_returned_frame_is_a_defensive_copy(self) -> None:
        """A retained reference must not later reveal future bars."""
        now = SYNTHETIC_START + timedelta(minutes=2000)
        frame = self.feed.bars(Timeframe.M5, 10, now)
        length_before = len(frame)
        frame.loc[0, "close"] = -999.0  # mutate the copy
        again = self.feed.bars(Timeframe.M5, 10, now)
        self.assertEqual(len(frame), length_before)
        self.assertNotEqual(float(again.loc[0, "close"]), -999.0)

    def test_availability_snapshot_is_consistent_with_bars(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=2500)
        snapshot = self.feed.availability_snapshot(now)
        for timeframe, availability in snapshot.items():
            with self.subTest(timeframe=timeframe.value):
                if availability.latest_close_time is None:
                    continue
                self.assertLessEqual(availability.latest_close_time, pd.Timestamp(now))

    def test_multi_timeframe_synchronisation(self) -> None:
        """Every timeframe reports its own latest closed bar at the same instant."""
        now = SYNTHETIC_START + timedelta(days=1, hours=10, minutes=37)
        snapshot = self.feed.availability_snapshot(now)
        for timeframe, availability in snapshot.items():
            with self.subTest(timeframe=timeframe.value):
                if availability.latest_open_time is None:
                    continue
                expected = latest_visible_open_time(timeframe, now)
                self.assertLessEqual(
                    availability.latest_open_time, pd.Timestamp(expected)
                )

    def test_higher_timeframe_lags_lower(self) -> None:
        now = SYNTHETIC_START + timedelta(days=1, hours=10, minutes=37)
        snapshot = self.feed.availability_snapshot(now)
        m1 = snapshot[Timeframe.M1].latest_open_time
        h1 = snapshot[Timeframe.H1].latest_open_time
        self.assertIsNotNone(m1)
        self.assertIsNotNone(h1)
        self.assertLess(h1, m1)

    def test_zero_count_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.feed.bars(Timeframe.M5, 0, SYNTHETIC_START)

    def test_unknown_timeframe_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.feed.bars(Timeframe.W1, 5, SYNTHETIC_START)


class ExecutionBarTests(unittest.TestCase):
    """The next-bar rule that makes fills legitimate."""

    def setUp(self) -> None:
        self.feed = ReplayFeed(make_synthetic_dataset(bars=3000))

    def test_next_bar_opens_at_or_after_the_decision(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=1000)
        bar = self.feed.next_bar_after(Timeframe.M5, now)
        self.assertIsNotNone(bar)
        self.assertGreaterEqual(pd.Timestamp(bar["time"]), pd.Timestamp(now))

    def test_next_bar_is_not_a_bar_the_strategy_already_saw(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=1000)
        visible = self.feed.bars(Timeframe.M5, 10, now)
        execution = self.feed.next_bar_after(Timeframe.M5, now)
        self.assertGreater(
            pd.Timestamp(execution["time"]), pd.Timestamp(visible["time"].iloc[-1])
        )

    def test_returns_none_past_the_end_of_data(self) -> None:
        far_future = SYNTHETIC_START + timedelta(days=3650)
        self.assertIsNone(self.feed.next_bar_after(Timeframe.M5, far_future))


class SpreadAndPriceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = ReplayFeed(make_synthetic_dataset(bars=2000), spread_pips=2.0)

    def test_spread_is_the_configured_assumption(self) -> None:
        self.assertAlmostEqual(
            self.feed.spread_at(SYNTHETIC_START + timedelta(minutes=500)), 2.0
        )

    def test_price_is_none_before_any_bar_closes(self) -> None:
        self.assertIsNone(self.feed.price_at(SYNTHETIC_START - timedelta(days=1)))

    def test_price_comes_from_the_latest_closed_bar(self) -> None:
        now = SYNTHETIC_START + timedelta(minutes=500)
        bars = self.feed.bars(Timeframe.M1, 1, now)
        self.assertAlmostEqual(self.feed.price_at(now), float(bars["close"].iloc[-1]))

    def test_negative_spread_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReplayFeed(make_synthetic_dataset(bars=200), spread_pips=-1.0)


if __name__ == "__main__":
    unittest.main()
