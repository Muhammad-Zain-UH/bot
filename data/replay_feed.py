"""Historical replay feed -- where the no-look-ahead invariant is enforced.

The hard invariant
------------------
At replay time ``T`` the strategy may see a bar if and only if::

    bar.open_time + timeframe.duration <= T

Future bars are **not materialised** into the frame handed to the strategy.
They are absent, not hidden behind a flag -- strategy code cannot reach past the
end of a frame it was given, so there is nothing to reach.

Three layers of enforcement:

1. The cut is computed with ``searchsorted`` on a precomputed close-time array,
   so it is exact and does not depend on any strategy-side discipline.
2. The returned frame is a **defensive copy** with a fresh ``RangeIndex``. A
   strategy that retained a reference could not observe it growing later.
3. :meth:`ReplayFeed.availability_snapshot` exposes exactly what was visible at
   each decision, so a test can assert the invariant empirically rather than
   trusting this docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from core.types import Timeframe
from data.dataset import BAR_COLUMNS, HistoricalDataset
from data.timeframes import duration

__all__ = ["DEFAULT_REPLAY_SPREAD_PIPS", "BarAvailability", "ReplayFeed"]

DEFAULT_REPLAY_SPREAD_PIPS: float = 2.0
"""Baseline assumed spread, in gold pips ($0.20).

The live feed never recorded real spread, so no historical value exists. This is
an explicit, configurable assumption that every run manifest discloses -- it is
never silently applied.
"""


@dataclass(frozen=True, slots=True)
class BarAvailability:
    """What was visible on one timeframe at one replay instant.

    Exists so replay integrity is inspectable rather than asserted. Recorded per
    decision and used directly by the leakage tests.

    Attributes:
        timeframe: The timeframe described.
        bar_count: How many bars were handed to the strategy.
        latest_open_time: Open time of the newest visible bar, if any.
        latest_close_time: Close time of that bar -- must be ``<= as_of``.
        latest_close_price: Close price of that bar.
    """

    timeframe: Timeframe
    bar_count: int
    latest_open_time: pd.Timestamp | None
    latest_close_time: pd.Timestamp | None
    latest_close_price: float | None

    def describe(self) -> str:
        """Return a compact one-line description for logs."""
        if self.latest_open_time is None:
            return f"{self.timeframe.value}: no bars"
        return (
            f"{self.timeframe.value}: n={self.bar_count} "
            f"open={self.latest_open_time.isoformat()} "
            f"close={self.latest_close_time.isoformat()} "
            f"px={self.latest_close_price:.2f}"
        )


class ReplayFeed:
    """Serves historical bars as they were known at a given instant.

    Implements :class:`~data.feed.MarketDataFeed`.

    Args:
        dataset: Validated historical data.
        spread_pips: Assumed spread in pips, applied uniformly.

    Note:
        Close times are precomputed once per timeframe at construction, so each
        lookup is a binary search rather than a scan. This matters: a month of
        M1 replay performs tens of thousands of lookups per timeframe.
    """

    __slots__ = ("_dataset", "_spread_pips", "_close_times", "_frames")

    def __init__(
        self,
        dataset: HistoricalDataset,
        spread_pips: float = DEFAULT_REPLAY_SPREAD_PIPS,
    ) -> None:
        if spread_pips < 0.0:
            raise ValueError(f"spread_pips must be >= 0, got {spread_pips}")
        self._dataset = dataset
        self._spread_pips = float(spread_pips)
        self._frames: dict[Timeframe, pd.DataFrame] = {}
        self._close_times: dict[Timeframe, np.ndarray] = {}

        for timeframe, frame in dataset.frames.items():
            ordered = frame[list(BAR_COLUMNS)].reset_index(drop=True)
            self._frames[timeframe] = ordered
            closes = ordered["time"] + duration(timeframe)
            self._close_times[timeframe] = closes.to_numpy(dtype="datetime64[ns]")

    # ------------------------------------------------------------------
    # MarketDataFeed
    # ------------------------------------------------------------------

    @property
    def symbol(self) -> str:
        """Instrument this feed serves."""
        return self._dataset.symbol

    @property
    def spread_pips(self) -> float:
        """The assumed spread, in pips."""
        return self._spread_pips

    def _visible_count(self, timeframe: Timeframe, as_of: datetime) -> int:
        """Return how many bars of ``timeframe`` have closed by ``as_of``.

        Args:
            timeframe: Timeframe to query.
            as_of: Replay time.

        Returns:
            Count of fully closed bars.

        Raises:
            KeyError: If the dataset lacks that timeframe.
        """
        if timeframe not in self._close_times:
            raise KeyError(
                f"replay feed has no {timeframe.value} data for {self.symbol}"
            )
        boundary = np.datetime64(pd.Timestamp(as_of).tz_convert("UTC").tz_localize(None), "ns")
        # side="right" makes a bar closing exactly at `as_of` visible: at
        # 10:37:00 the bar that closed at 10:37:00 is complete.
        return int(np.searchsorted(self._close_times[timeframe], boundary, side="right"))

    def bars(
        self,
        timeframe: Timeframe,
        count: int,
        as_of: datetime,
        require_full: bool = True,
    ) -> pd.DataFrame:
        """Return the last ``count`` bars closed at or before ``as_of``.

        Matches ``mt5_handler.get_market_data``'s contract exactly, including
        its behaviour when history is short. That function returns an **empty**
        frame rather than a partial one: its primary path requires
        ``len(rates) >= n_candles``, its range fallback requires the same, and
        its last-resort branch explicitly refuses any request for more than two
        bars ("refusing low-quality N-candle request"). Returning a short frame
        here would feed the strategy something production never sees, and the
        difference would show up as a warmup-period artefact in the baseline.

        Args:
            timeframe: Timeframe to fetch.
            count: Number of bars to return, newest last.
            as_of: Replay time.
            require_full: Return an empty frame unless ``count`` bars are
                available. ``True`` mirrors production; ``False`` is for tests
                that need to inspect partial history.

        Returns:
            A defensive copy matching ``mt5_handler.get_market_data``'s layout,
            or an empty frame with the same columns.

        Raises:
            ValueError: If ``count`` is not positive.
            KeyError: If the dataset lacks that timeframe.
        """
        if count <= 0:
            raise ValueError(f"count must be > 0, got {count}")

        available = self._visible_count(timeframe, as_of)
        if available == 0 or (require_full and available < count):
            return pd.DataFrame(columns=list(BAR_COLUMNS))

        start = max(0, available - count)
        # .copy() is deliberate: the strategy must not hold a view that could
        # later reflect rows beyond `as_of`.
        return self._frames[timeframe].iloc[start:available].copy().reset_index(drop=True)

    def price_at(self, as_of: datetime) -> float | None:
        """Return the close of the newest visible bar on the finest timeframe.

        The finest available timeframe is used because it is the closest
        approximation to a live tick that bar data permits.

        Args:
            as_of: Replay time.

        Returns:
            The price, or ``None`` if nothing has closed yet.
        """
        for timeframe in sorted(self._frames, key=lambda tf: tf.minutes):
            available = self._visible_count(timeframe, as_of)
            if available > 0:
                return float(self._frames[timeframe]["close"].iloc[available - 1])
        return None

    def spread_at(self, as_of: datetime) -> float:  # noqa: ARG002 - constant by design
        """Return the assumed spread in pips.

        Constant in Phase 2A: no historical spread series exists. The parameter
        is retained so a future implementation can vary spread by time of day
        without changing any call site.

        Args:
            as_of: Replay time. Unused.

        Returns:
            The configured spread in pips.
        """
        return self._spread_pips

    # ------------------------------------------------------------------
    # Replay integrity
    # ------------------------------------------------------------------

    def availability(self, timeframe: Timeframe, as_of: datetime) -> BarAvailability:
        """Describe what was visible on ``timeframe`` at ``as_of``.

        Args:
            timeframe: Timeframe to describe.
            as_of: Replay time.

        Returns:
            A :class:`BarAvailability` snapshot.
        """
        available = self._visible_count(timeframe, as_of)
        if available == 0:
            return BarAvailability(timeframe, 0, None, None, None)
        row = self._frames[timeframe].iloc[available - 1]
        open_time = pd.Timestamp(row["time"])
        return BarAvailability(
            timeframe=timeframe,
            bar_count=available,
            latest_open_time=open_time,
            latest_close_time=open_time + duration(timeframe),
            latest_close_price=float(row["close"]),
        )

    def availability_snapshot(
        self,
        as_of: datetime,
        timeframes: list[Timeframe] | None = None,
    ) -> dict[Timeframe, BarAvailability]:
        """Describe every timeframe's visibility at ``as_of``.

        Args:
            as_of: Replay time.
            timeframes: Which timeframes to include. Defaults to all present.

        Returns:
            A snapshot per timeframe, for logging and leakage assertions.
        """
        wanted = timeframes or sorted(self._frames, key=lambda tf: -tf.minutes)
        return {tf: self.availability(tf, as_of) for tf in wanted}

    def next_bar_after(
        self,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> pd.Series | None:
        """Return the first bar of ``timeframe`` that **opens at or after** ``as_of``.

        This is the execution bar: a decision taken at ``as_of`` can only be
        filled by a bar that had not yet started. Using the bar the decision was
        made on would be look-ahead.

        Args:
            timeframe: Timeframe to search.
            as_of: Decision time.

        Returns:
            The next bar, or ``None`` if the dataset ends first.

        Raises:
            KeyError: If the dataset lacks that timeframe.
        """
        if timeframe not in self._frames:
            raise KeyError(f"replay feed has no {timeframe.value} data")
        frame = self._frames[timeframe]
        open_times = frame["time"].to_numpy(dtype="datetime64[ns]")
        boundary = np.datetime64(pd.Timestamp(as_of).tz_convert("UTC").tz_localize(None), "ns")
        position = int(np.searchsorted(open_times, boundary, side="left"))
        if position >= len(frame):
            return None
        return frame.iloc[position]

    def bars_between(
        self,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return bars opening in ``[start, end)``.

        Used by the paper broker to walk an open position forward. It is not
        part of the strategy-facing surface and must never be called with an
        ``end`` beyond the current replay time.

        Args:
            timeframe: Timeframe to fetch.
            start: Inclusive lower bound on bar open time.
            end: Exclusive upper bound on bar open time.

        Returns:
            The matching bars.
        """
        frame = self._frames[timeframe]
        times = frame["time"]
        mask = (times >= pd.Timestamp(start)) & (times < pd.Timestamp(end))
        return frame[mask].copy().reset_index(drop=True)

    def decision_times(
        self,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[pd.Timestamp]:
        """Return the bar-close instants that drive the replay.

        The replay is event-driven: one decision per bar close on the driving
        timeframe. There is no ``time.sleep`` and no wall-clock involvement.

        Args:
            timeframe: Driving timeframe, typically the finest in use.
            start: Optional inclusive lower bound on the close instant.
            end: Optional inclusive upper bound.

        Returns:
            Close instants in ascending order.
        """
        closes = self._frames[timeframe]["time"] + duration(timeframe)
        if start is not None:
            closes = closes[closes >= pd.Timestamp(start)]
        if end is not None:
            closes = closes[closes <= pd.Timestamp(end)]
        return list(closes)
