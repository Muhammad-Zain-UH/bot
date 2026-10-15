"""Scoped replay clock -- **temporary Phase 2A infrastructure**.

Why this exists
---------------
Four wall-clock reads sit inside the strategy path. Under replay they would
answer with *today's* time while the strategy reasons about bars from months or
years earlier:

===  =================================================  ==========================
ID   Location                                           What it decides
===  =================================================  ==========================
N1   ``risk_manager.get_current_session()``             L0 session gate; the L7
                                                        session bonus (+8/0/-15);
                                                        also reached via
                                                        ``entry_engine.detect_regime``
N2   ``entry_engine._within_kill_zone()``               gates **every** MOMENTUM
                                                        entry (08-10, 12-14 UTC).
                                                        MICRO_SCALP is
                                                        momentum-only, so this
                                                        alone decides whether 55%
                                                        of regime-time can trade
N3   ``main_production._count_today_entry_signals()``   the daily-trade limit
N4   ``main_production`` analysis timestamps            output determinism
===  =================================================  ==========================

Why patching rather than injection
----------------------------------
Phase 2A's entire purpose is to measure the **existing** strategy. Its value
depends on the strategy files being provably untouched, so a baseline cannot be
contaminated by a refactor. Adding a ``now=`` parameter to ``get_current_session``
and ``_within_kill_zone`` is the better long-term design and is planned for
Phase 3 -- but it edits two strategy modules, which this phase forbids.

This is therefore **deliberately temporary**. It is scoped, explicit and tested,
not ambient monkey-patching:

* patched only for the duration of a single decision
* restored in a ``finally`` block, so an exception cannot leak the patch
* re-entrant-safe and verified restored by
  ``tests/backtest/test_clock_patch.py``
* replaces only the module-level ``datetime`` **name**; the substitute is a
  ``datetime`` subclass, so construction, arithmetic and ``isinstance`` all
  behave exactly as before. Only ``now()``/``today()``/``utcnow()`` change.

What it does not do
-------------------
It changes no logic. ``get_current_session()`` runs its own unmodified
comparisons -- it simply receives the replayed instant instead of the wall clock.
The session boundaries, the kill-zone hours and the daily-limit rule are all
untouched.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import datetime, timezone, tzinfo
from typing import Any

__all__ = ["PATCHED_MODULES", "build_frozen_datetime", "frozen_clock"]

PATCHED_MODULES: tuple[str, ...] = (
    "risk_manager",
    "entry_engine",
    "main_production",
)
"""Modules whose ``datetime`` name is substituted during a replay decision.

Derived from the audit of N1-N4. ``tests/backtest/test_clock_patch.py`` asserts
this list still covers every ambient clock read reachable from the strategy, so
a newly introduced one cannot slip through unnoticed.
"""


def build_frozen_datetime(instant: datetime) -> type:
    """Return a ``datetime`` subclass whose ``now()`` answers ``instant``.

    Subclassing rather than substituting a stand-in keeps every other use of the
    name working unchanged: ``datetime(2026, 1, 1)``, ``fromisoformat``,
    ``timedelta`` arithmetic and ``isinstance`` checks all behave as before.

    Args:
        instant: The replay time to report. Must be timezone-aware.

    Returns:
        A ``datetime`` subclass with frozen ``now``/``today``/``utcnow``.

    Raises:
        ValueError: If ``instant`` is naive. A naive replay instant would
            reintroduce the timezone ambiguity this whole design removes.
    """
    if instant.tzinfo is None:
        raise ValueError(
            "replay instant must be timezone-aware; a naive instant is exactly "
            "the ambiguity the replay clock exists to eliminate"
        )

    utc_instant = instant.astimezone(timezone.utc)

    class _FrozenDateTime(datetime):
        """A ``datetime`` frozen at one replay instant."""

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            """Return the replay instant.

            Mirrors the stdlib contract: aware when ``tz`` is supplied, naive
            otherwise. The naive form uses the UTC wall-clock reading rather
            than a machine-local one, so results do not depend on the host
            timezone.
            """
            if tz is None:
                return utc_instant.replace(tzinfo=None)
            return utc_instant.astimezone(tz)

        @classmethod
        def utcnow(cls) -> datetime:  # type: ignore[override]
            """Return the replay instant as a naive UTC datetime."""
            return utc_instant.replace(tzinfo=None)

        @classmethod
        def today(cls) -> datetime:  # type: ignore[override]
            """Return the replay instant as a naive datetime."""
            return utc_instant.replace(tzinfo=None)

    return _FrozenDateTime


@contextlib.contextmanager
def frozen_clock(
    instant: datetime,
    module_names: tuple[str, ...] = PATCHED_MODULES,
) -> Iterator[type]:
    """Freeze the ambient clock in the strategy modules for one decision.

    Substitutes the module-level ``datetime`` name in each target module, then
    restores the original in a ``finally`` block. An exception inside the body
    cannot leave a module patched.

    Modules that are not imported are skipped silently -- ``main_production``
    imports ``MetaTrader5``, which is unavailable in some environments, and the
    replay must still work for the rest.

    Args:
        instant: The replay time to report. Must be timezone-aware.
        module_names: Modules to patch. Defaults to :data:`PATCHED_MODULES`.

    Yields:
        The frozen ``datetime`` subclass, for assertions in tests.

    Raises:
        ValueError: If ``instant`` is naive.

    Example:
        >>> from datetime import datetime, timezone
        >>> moment = datetime(2024, 3, 1, 9, 30, tzinfo=timezone.utc)
        >>> with frozen_clock(moment):
        ...     import risk_manager
        ...     risk_manager.get_current_session()
        'London'
    """
    import sys

    frozen = build_frozen_datetime(instant)
    originals: list[tuple[Any, str, Any]] = []

    try:
        for name in module_names:
            module = sys.modules.get(name)
            if module is None:
                continue
            if not hasattr(module, "datetime"):
                continue
            originals.append((module, "datetime", module.datetime))
            module.datetime = frozen  # type: ignore[attr-defined]
        yield frozen
    finally:
        # Restore in reverse so nested use unwinds cleanly.
        for module, attribute, original in reversed(originals):
            setattr(module, attribute, original)
