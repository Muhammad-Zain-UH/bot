"""Canonical domain foundations for the trading system.

This package deliberately re-exports **nothing**. Import the specific module you
need::

    from core.symbols import SymbolSpecification
    from core.units import Pips, PriceDistance

Keeping ``__init__`` empty guarantees a strict, acyclic dependency graph::

    symbols  ->  (stdlib only)
    units    ->  symbols
    candles  ->  (stdlib + pandas)
    indicators -> candles, symbols, units
    types    ->  symbols, units
    clock    ->  (stdlib only)
    safety   ->  (stdlib only)
    signal_log -> (stdlib only)

Hard rules for every module in this package:

* **No ``MetaTrader5`` import.** ``core`` must be importable and testable on a
  machine with no broker terminal installed. Broker data enters through plain
  duck-typed adapters (see :func:`core.symbols.SymbolSpecification.from_mt5_symbol_info`).
* **No ``datetime.now()``.** Time is obtained through :mod:`core.clock` so the
  system can be driven deterministically by a replay or fake clock later.
* **No magic-number unit conversions.** Every price/pip/point conversion goes
  through :mod:`core.units` and requires an explicit
  :class:`~core.symbols.SymbolSpecification`.
* **No hidden global mutable state.**

Phase 0/1 scope note: this package is additive. Existing strategy modules have
not been migrated onto it. See ``docs/CONVENTIONS.md`` and ``PHASE_2_ISSUES.md``.
"""

from __future__ import annotations

__all__: list[str] = []
