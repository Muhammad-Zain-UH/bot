"""Order execution.

Phase 2A contains a **simulator only**. There is no live broker adapter here and
no path from this package to a real order: nothing under ``execution/`` imports
``MetaTrader5`` or calls ``order_send``, and
``tests/execution/test_no_live_execution.py`` enforces that by parsing the AST.

Live execution remains locked by ``core.safety.LIVE_TRADING_ENABLED``.
"""

from __future__ import annotations

__all__: list[str] = []
