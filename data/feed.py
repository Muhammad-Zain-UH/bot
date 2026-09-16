"""Market data feed protocol.

The strategy must not be able to tell whether its bars come from a live MT5
terminal, a historical replay, or a paper-trading session. That is the whole
point of this interface: the same ``analyze_entry`` call runs against any of
them.

Only :class:`~data.replay_feed.ReplayFeed` implements this in Phase 2A. A live
adapter wrapping ``mt5_handler.get_market_data`` is Phase 3 work and is
deliberately absent -- this phase must remain incapable of live trading.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from core.types import Timeframe

__all__ = ["MarketDataFeed"]


@runtime_checkable
class MarketDataFeed(Protocol):
    """Supplies bars and prices as they were known at a given instant.

    Every method takes an explicit ``as_of``. There is no implicit "now" --
    that is what makes replay deterministic and what stops a live-shaped call
    from accidentally reading the future during a backtest.
    """

    @property
    def symbol(self) -> str:
        """Instrument this feed serves."""
        ...

    def bars(
        self,
        timeframe: Timeframe,
        count: int,
        as_of: datetime,
    ) -> pd.DataFrame:
        """Return the last ``count`` bars **closed at or before** ``as_of``.

        The returned frame must match ``mt5_handler.get_market_data`` exactly:
        columns ``time, open, high, low, close, tick_volume``; ``time`` tz-aware
        UTC bar-open times; a fresh ``RangeIndex``; the forming bar excluded.

        Args:
            timeframe: Timeframe to fetch.
            count: Maximum number of bars to return, newest last.
            as_of: Replay time. No bar closing after this may appear.

        Returns:
            A bar frame, possibly shorter than ``count`` near the start of the
            dataset.
        """
        ...

    def price_at(self, as_of: datetime) -> float | None:
        """Return the reference price at ``as_of``.

        Args:
            as_of: Replay time.

        Returns:
            The price, or ``None`` if no bar is available yet.
        """
        ...

    def spread_at(self, as_of: datetime) -> float:
        """Return the spread in **pips** at ``as_of``.

        Pips, not points, to match ``mt5_handler.get_current_spread``, which
        returns real gold pips.

        Args:
            as_of: Replay time.

        Returns:
            Spread in pips.
        """
        ...
