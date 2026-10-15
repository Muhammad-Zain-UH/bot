"""Broker symbol fixtures.

The reference :class:`~core.symbols.SymbolSpecification` constants live in
``core.symbols`` because production code needs them for documentation and
fallbacks. What lives here is the *broker-side* fixture: a stand-in for an MT5
``symbol_info`` object, so ``from_mt5_symbol_info`` can be tested without
MetaTrader5 installed and without a terminal running.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "FakeMT5SymbolInfo",
    "eurusd_symbol_info",
    "xauusd_symbol_info",
]


@dataclass(frozen=True)
class FakeMT5SymbolInfo:
    """Stand-in for MetaTrader5's ``symbol_info`` namedtuple.

    Only the attributes ``SymbolSpecification.from_mt5_symbol_info`` reads are
    defined. Being a plain dataclass rather than a mock keeps the test honest:
    if the production code starts reading a new attribute, construction here
    fails loudly instead of silently returning a ``Mock``.
    """

    name: str
    digits: int
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_contract_size: float
    trade_calc_mode: int
    volume_min: float
    volume_max: float
    volume_step: float
    currency_base: str = ""
    currency_profit: str = ""


def xauusd_symbol_info(digits: int = 2) -> FakeMT5SymbolInfo:
    """Return a realistic XAUUSD ``symbol_info`` as a broker would report it.

    Args:
        digits: Quote precision. ``2`` and ``3`` are both real in the wild; the
            pip size is ``$0.10`` either way, which is exactly why pip size
            cannot be derived from ``digits``.

    Returns:
        A fake ``symbol_info`` for XAUUSD.

    Raises:
        ValueError: If ``digits`` is not 2 or 3.
    """
    if digits == 2:
        return FakeMT5SymbolInfo(
            name="XAUUSD",
            digits=2,
            point=0.01,
            trade_tick_size=0.01,
            trade_tick_value=1.0,
            trade_contract_size=100.0,
            trade_calc_mode=4,   # CFD_LEVERAGE, captured from MetaQuotes-Demo
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            currency_base="XAU",
            currency_profit="USD",
        )
    if digits == 3:
        return FakeMT5SymbolInfo(
            name="XAUUSD",
            digits=3,
            point=0.001,
            trade_tick_size=0.001,
            trade_tick_value=0.1,
            trade_contract_size=100.0,
            trade_calc_mode=4,   # CFD_LEVERAGE, captured from MetaQuotes-Demo
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            currency_base="XAU",
            currency_profit="USD",
        )
    raise ValueError(f"no XAUUSD fixture for digits={digits}")


def eurusd_symbol_info() -> FakeMT5SymbolInfo:
    """Return a realistic 5-digit EURUSD ``symbol_info``.

    Present so tests can prove conversions are driven by the specification and
    not hardcoded to gold.
    """
    return FakeMT5SymbolInfo(
        name="EURUSD",
        digits=5,
        point=0.00001,
        trade_tick_size=0.00001,
        trade_tick_value=0.1,
        trade_contract_size=100_000.0,
        trade_calc_mode=0,   # FOREX
        volume_min=0.01,
        volume_max=200.0,
        volume_step=0.01,
        currency_base="EUR",
        currency_profit="USD",
    )
