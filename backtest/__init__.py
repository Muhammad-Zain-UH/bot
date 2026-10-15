"""Deterministic historical replay and descriptive backtest reporting.

Drives the **unmodified** production strategy over historical bars and records
what it did. Reports descriptive measurements only -- it does not rank, score or
judge a strategy, and it draws no forward-looking conclusion.

Live trading remains locked by ``core.safety.LIVE_TRADING_ENABLED``; nothing in
this package can place a real order.
"""

from __future__ import annotations

__all__: list[str] = []
