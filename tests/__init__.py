"""Test package for the XAUUSD trading system.

PHASE 0.4 -- TEST / PRODUCTION ISOLATION
========================================

Importing this package redirects every log and datastore path the project
writes to into a per-run temporary directory. **This must happen before any
project module is imported**, because several of them resolve their output paths
at import time:

* ``main_production`` builds its ``logging.FileHandler`` at module scope.
* ``main`` calls ``logging.basicConfig`` at module scope.
* ``utils/__init__.py`` reads ``LOG_FILE`` and opens a ``RotatingFileHandler``
  at module scope.

Python imports ``tests`` before ``tests.test_x``, so assigning the environment
here runs early enough. That ordering is load-bearing -- do not move this logic
into a test module or a ``setUp``.

Why this exists
---------------
The Phase 1 audit found test output in the permanent production record. Four
``[ENTRY] ENTRY SIGNAL GENERATED`` entries showing ``Entry: 101.00 / SL: 99.00 /
TP: 104.00`` in ``trading_bot_production.log`` are fixtures from
``tests/test_layer_gate_logic.py``, not real signals -- they were written simply
because importing the module under test opened the production log for append.

That is worse than untidy. It put fabricated trade data into the only record of
what the system had done, and it is why the audit initially appeared to show
four entry signals when the true count was zero.

Verifying the isolation
-----------------------
``tests/core/test_log_isolation.py`` asserts that the production paths are not
in use during a test run.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

__all__ = ["TEST_OUTPUT_DIR", "PRODUCTION_PATHS"]

PRODUCTION_PATHS: tuple[str, ...] = (
    "trading_bot_production.log",
    "trading_bot_main.log",
    "trading_bot.log",
    "signal_log.csv",
    "signal_log_v2.csv",
    "signal_log_main_v2.csv",
)
"""Paths a test run must never write to. Asserted in test_log_isolation.py."""


def _redirect_outputs_to_temporary_directory() -> Path:
    """Point every project output path at a fresh temporary directory.

    Uses ``os.environ.setdefault`` rather than assignment so that a caller who
    has deliberately set one of these keeps control.

    Returns:
        The temporary directory that outputs were redirected into.
    """
    directory = Path(tempfile.mkdtemp(prefix="zoya-tests-"))

    os.environ.setdefault("TRADING_BOT_LOG_FILE", str(directory / "trading_bot_production.log"))
    os.environ.setdefault("TRADING_BOT_MAIN_LOG_FILE", str(directory / "trading_bot_main.log"))
    os.environ.setdefault("SIGNAL_LOG_FILE", str(directory / "signal_log_v2.csv"))
    os.environ.setdefault("MAIN_SIGNAL_LOG_FILE", str(directory / "signal_log_main_v2.csv"))
    # Consumed by utils/__init__.py at import time.
    os.environ.setdefault("LOG_FILE", str(directory / "trading_bot.log"))

    def _cleanup() -> None:
        shutil.rmtree(directory, ignore_errors=True)

    atexit.register(_cleanup)
    return directory


TEST_OUTPUT_DIR: Path = _redirect_outputs_to_temporary_directory()
"""Temporary directory receiving all log and datastore writes during tests."""
