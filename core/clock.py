"""Injectable clock abstraction.

Why this module exists
----------------------
The Phase 1 audit found ``datetime.now()`` called directly inside decision logic:

* ``entry_engine._within_kill_zone`` -- gates momentum entries on the wall clock.
* ``risk_manager.get_current_session`` -- drives the session gate and the
  confidence session bonus.
* ``main_production._count_today_entry_signals`` -- uses naive **local** dates
  while market data is tz-aware **UTC**.
* Every ``timestamp`` field written to state and logs.

Two consequences:

1. **Non-determinism.** The same inputs produce different decisions depending on
   when the code runs, so results cannot be reproduced or tested.
2. **Timezone mixing.** Naive local timestamps are compared against tz-aware UTC
   market data. On a machine that is not on UTC this is silently wrong.

Four distinct notions of time
-----------------------------
``utc``
    The reference timeline. All internal reasoning and all persisted timestamps
    use this. Always tz-aware.

``broker``
    The MT5 server's clock. Bar timestamps arrive on this timeline and brokers
    commonly run UTC+2/UTC+3 with DST. Daily bar boundaries and therefore
    "previous day high/low" depend on it.

``local``
    The operator's wall clock. **Display only.** No trading decision may depend
    on it.

``session``
    Market session derived from UTC. Session classification itself stays in the
    strategy layer in this phase; the clock only supplies the instant.

Phase 0/1 scope
---------------
This module establishes the abstraction and provides a deterministic fake for
tests. It is **not** wired into the strategy engines -- doing so would change
behaviour, which this phase forbids. Violations are catalogued in
``PHASE_2_ISSUES.md``. The replay/backtest clock is explicitly Phase 3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

__all__ = [
    "Clock",
    "FakeClock",
    "SystemClock",
    "UTC",
]

UTC = timezone.utc
"""Canonical reference timezone. Import this rather than re-deriving it."""


@runtime_checkable
class Clock(Protocol):
    """Source of the current instant.

    Every implementation must return **timezone-aware** datetimes. A naive
    datetime from a clock is a bug: it is what allows local time to be compared
    against UTC market data without any error being raised.
    """

    def now_utc(self) -> datetime:
        """Return the current instant as a tz-aware UTC datetime."""
        ...

    def now_broker(self) -> datetime:
        """Return the current instant on the broker's clock, tz-aware."""
        ...

    def now_local(self) -> datetime:
        """Return the operator's wall-clock time, tz-aware. Display only."""
        ...


class SystemClock:
    """Live clock backed by the operating system.

    The broker offset is an explicit constructor argument rather than something
    inferred. Guessing it -- for instance by differencing the newest bar
    timestamp against local time -- produces an offset that silently shifts
    across DST transitions.

    Args:
        broker_utc_offset_hours: The broker server's offset from UTC in hours,
            e.g. ``2.0`` for a UTC+2 server. Defaults to ``0.0``, meaning the
            broker is assumed to run on UTC until a real value is supplied.

    Example:
        >>> clock = SystemClock(broker_utc_offset_hours=2.0)
        >>> clock.now_utc().tzinfo is not None
        True
    """

    __slots__ = ("_broker_offset",)

    def __init__(self, broker_utc_offset_hours: float = 0.0) -> None:
        self._broker_offset = timedelta(hours=broker_utc_offset_hours)

    @property
    def broker_utc_offset(self) -> timedelta:
        """The configured broker offset from UTC."""
        return self._broker_offset

    def now_utc(self) -> datetime:
        """Return the current instant as a tz-aware UTC datetime."""
        return datetime.now(UTC)

    def now_broker(self) -> datetime:
        """Return the current instant on the broker's clock.

        The returned datetime carries a fixed-offset timezone so that it remains
        unambiguous and can be converted back to UTC losslessly.
        """
        return self.now_utc().astimezone(timezone(self._broker_offset))

    def now_local(self) -> datetime:
        """Return the operator's wall-clock time, tz-aware. Display only."""
        return datetime.now().astimezone()

    def __repr__(self) -> str:
        return f"SystemClock(broker_utc_offset_hours={self._broker_offset.total_seconds() / 3600})"


class FakeClock:
    """Deterministic clock for tests.

    Time advances only when :meth:`advance` or :meth:`set_to` is called, so a
    test controls the timeline exactly.

    Args:
        start: The initial instant. Must be tz-aware.
        broker_utc_offset_hours: Broker offset from UTC in hours.
        local_utc_offset_hours: Operator wall-clock offset from UTC in hours.
            Settable independently so tests can reproduce the "local time is not
            UTC" condition that makes timezone bugs visible.

    Raises:
        ValueError: If ``start`` is naive.

    Example:
        >>> from datetime import datetime
        >>> clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
        >>> clock.advance(seconds=30)
        >>> clock.now_utc().minute
        0
    """

    __slots__ = ("_now", "_broker_offset", "_local_offset")

    def __init__(
        self,
        start: datetime,
        broker_utc_offset_hours: float = 0.0,
        local_utc_offset_hours: float = 0.0,
    ) -> None:
        if start.tzinfo is None:
            raise ValueError(
                "FakeClock requires a timezone-aware start datetime; "
                "a naive datetime is exactly the ambiguity this abstraction removes"
            )
        self._now = start.astimezone(UTC)
        self._broker_offset = timedelta(hours=broker_utc_offset_hours)
        self._local_offset = timedelta(hours=local_utc_offset_hours)

    def now_utc(self) -> datetime:
        """Return the current fake instant as a tz-aware UTC datetime."""
        return self._now

    def now_broker(self) -> datetime:
        """Return the current fake instant on the broker's clock."""
        return self._now.astimezone(timezone(self._broker_offset))

    def now_local(self) -> datetime:
        """Return the current fake instant on the operator's clock."""
        return self._now.astimezone(timezone(self._local_offset))

    def advance(
        self,
        *,
        days: float = 0,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
    ) -> None:
        """Move the clock forward.

        Args:
            days: Days to advance.
            hours: Hours to advance.
            minutes: Minutes to advance.
            seconds: Seconds to advance.

        Raises:
            ValueError: If the total delta is negative. Time must not run
                backwards; a test needing an earlier instant should use
                :meth:`set_to`, making the jump explicit.
        """
        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta < timedelta(0):
            raise ValueError(
                f"advance() must not move time backwards (got {delta}); use set_to()"
            )
        self._now = self._now + delta

    def set_to(self, instant: datetime) -> None:
        """Jump the clock to ``instant``.

        Args:
            instant: The new current time. Must be tz-aware.

        Raises:
            ValueError: If ``instant`` is naive.
        """
        if instant.tzinfo is None:
            raise ValueError("set_to() requires a timezone-aware datetime")
        self._now = instant.astimezone(UTC)

    def __repr__(self) -> str:
        return f"FakeClock(now_utc={self._now.isoformat()})"
