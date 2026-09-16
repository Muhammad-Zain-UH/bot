"""Tests for the injectable clock.

Determinism is the point: the same inputs must produce the same decisions
regardless of when the code runs. These tests also pin the timezone-awareness
requirement, because naive local timestamps compared against tz-aware UTC market
data is a silent, machine-dependent bug.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from core.clock import UTC, Clock, FakeClock, SystemClock


class FakeClockDeterminismTests(unittest.TestCase):
    """A fake clock moves only when told to."""

    def setUp(self) -> None:
        self.start = datetime(2026, 3, 15, 8, 30, tzinfo=UTC)
        self.clock = FakeClock(self.start)

    def test_time_does_not_pass_on_its_own(self) -> None:
        first = self.clock.now_utc()
        for _ in range(1000):
            pass
        self.assertEqual(first, self.clock.now_utc())

    def test_repeated_reads_are_identical(self) -> None:
        self.assertEqual(self.clock.now_utc(), self.clock.now_utc())

    def test_advance_moves_forward_by_exactly_the_delta(self) -> None:
        self.clock.advance(minutes=15)
        self.assertEqual(self.clock.now_utc(), self.start + timedelta(minutes=15))

    def test_advance_accumulates(self) -> None:
        self.clock.advance(hours=1)
        self.clock.advance(minutes=30)
        self.clock.advance(seconds=45)
        self.assertEqual(
            self.clock.now_utc(),
            self.start + timedelta(hours=1, minutes=30, seconds=45),
        )

    def test_advance_refuses_to_run_backwards(self) -> None:
        with self.assertRaises(ValueError):
            self.clock.advance(minutes=-1)

    def test_set_to_makes_a_backwards_jump_explicit(self) -> None:
        earlier = self.start - timedelta(days=1)
        self.clock.set_to(earlier)
        self.assertEqual(self.clock.now_utc(), earlier)

    def test_naive_start_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FakeClock(datetime(2026, 3, 15, 8, 30))

    def test_naive_set_to_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.clock.set_to(datetime(2026, 3, 15, 8, 30))

    def test_a_non_utc_start_is_normalised_to_utc(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        clock = FakeClock(datetime(2026, 3, 15, 10, 30, tzinfo=plus_two))
        self.assertEqual(clock.now_utc(), datetime(2026, 3, 15, 8, 30, tzinfo=UTC))


class TimelineSeparationTests(unittest.TestCase):
    """UTC, broker and local time are distinct and must not be conflated."""

    def setUp(self) -> None:
        self.clock = FakeClock(
            datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
            broker_utc_offset_hours=2.0,
            local_utc_offset_hours=5.0,
        )

    def test_all_three_describe_the_same_instant(self) -> None:
        self.assertEqual(
            self.clock.now_utc().timestamp(), self.clock.now_broker().timestamp()
        )
        self.assertEqual(
            self.clock.now_utc().timestamp(), self.clock.now_local().timestamp()
        )

    def test_wall_clock_readings_differ(self) -> None:
        self.assertEqual(self.clock.now_utc().hour, 12)
        self.assertEqual(self.clock.now_broker().hour, 14)
        self.assertEqual(self.clock.now_local().hour, 17)

    def test_naive_comparison_across_timelines_would_be_wrong(self) -> None:
        """Demonstrates the bug the abstraction prevents.

        ``main_production._count_today_entry_signals`` compares a naive local
        date against UTC-derived data. On a machine offset far enough from UTC
        the calendar date differs, so the daily trade counter reads the wrong day.
        """
        clock = FakeClock(
            datetime(2026, 3, 15, 23, 30, tzinfo=UTC), local_utc_offset_hours=5.0
        )
        self.assertEqual(clock.now_utc().date().day, 15)
        self.assertEqual(clock.now_local().date().day, 16)

    def test_every_reading_is_timezone_aware(self) -> None:
        for name in ("now_utc", "now_broker", "now_local"):
            with self.subTest(method=name):
                self.assertIsNotNone(getattr(self.clock, name)().tzinfo)

    def test_broker_offset_is_explicit_not_inferred(self) -> None:
        default = FakeClock(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
        self.assertEqual(default.now_broker().hour, 12)
        offset = FakeClock(
            datetime(2026, 3, 15, 12, 0, tzinfo=UTC), broker_utc_offset_hours=3.0
        )
        self.assertEqual(offset.now_broker().hour, 15)


class SystemClockTests(unittest.TestCase):
    """The live clock, checked for shape rather than for a specific value."""

    def test_readings_are_timezone_aware(self) -> None:
        clock = SystemClock(broker_utc_offset_hours=2.0)
        for name in ("now_utc", "now_broker", "now_local"):
            with self.subTest(method=name):
                self.assertIsNotNone(getattr(clock, name)().tzinfo)

    def test_utc_reading_is_actually_utc(self) -> None:
        self.assertEqual(SystemClock().now_utc().utcoffset(), timedelta(0))

    def test_time_advances(self) -> None:
        clock = SystemClock()
        self.assertLessEqual(clock.now_utc(), clock.now_utc())

    def test_broker_offset_is_applied(self) -> None:
        clock = SystemClock(broker_utc_offset_hours=3.0)
        self.assertEqual(clock.now_broker().utcoffset(), timedelta(hours=3))

    def test_broker_offset_is_exposed(self) -> None:
        self.assertEqual(
            SystemClock(broker_utc_offset_hours=2.5).broker_utc_offset,
            timedelta(hours=2.5),
        )


class ProtocolConformanceTests(unittest.TestCase):
    """Both implementations must satisfy the same protocol."""

    def test_both_implementations_conform(self) -> None:
        for clock in (SystemClock(), FakeClock(datetime(2026, 1, 1, tzinfo=UTC))):
            with self.subTest(implementation=type(clock).__name__):
                self.assertIsInstance(clock, Clock)

    def test_fake_is_substitutable_for_system(self) -> None:
        """A function taking a Clock must not care which one it received."""

        def hour_of(clock: Clock) -> int:
            return clock.now_utc().hour

        self.assertEqual(hour_of(FakeClock(datetime(2026, 1, 1, 7, tzinfo=UTC))), 7)
        self.assertIsInstance(hour_of(SystemClock()), int)


if __name__ == "__main__":
    unittest.main()
