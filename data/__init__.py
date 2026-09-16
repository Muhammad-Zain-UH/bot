"""Market data: historical datasets, validation, and the replay feed.

The :class:`~data.feed.MarketDataFeed` protocol is the seam that lets the same
strategy run against live MT5 bars, a historical replay, or a paper-trading
session without knowing which it is.

Phase 2A ships only the replay implementation. No live adapter exists here --
this phase must remain incapable of live trading.
"""

from __future__ import annotations

__all__: list[str] = []
