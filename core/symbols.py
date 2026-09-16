"""Canonical broker symbol specification.

Why this module exists
----------------------
The Phase 1 audit found instrument facts hardcoded across business logic --
``XAUUSD_PIP_SIZE = 0.10`` in ``mt5_handler``, ``pip_size = 0.10`` inline in
``main_production``, an implicit contract size of ``10`` in ``risk_manager``
(the correct value is ``100``), and ``buffer_pips = 3.0`` subtracted directly
from a price in ``entry_engine``.

A :class:`SymbolSpecification` is the single place broker instrument facts live.
Business logic must never assume a value; it must ask the specification.

Point vs pip vs tick
--------------------
These three are routinely conflated and are **not** interchangeable:

``point``
    The smallest representable price increment: ``10 ** -digits``. For XAUUSD
    quoted to 2 decimals this is ``0.01``.

``pip``
    A *convention*, not a derived quantity. For gold the market convention is
    ``$0.10`` -- i.e. **10 points** at 2-digit quoting. For a 5-digit FX pair a
    pip is ``0.0001`` -- **10 points**. For a 4-digit FX pair a pip is ``0.0001``
    -- **1 point**. There is no reliable formula, so ``pip_size`` is an explicit
    required field rather than something this module guesses.

``tick_size``
    The smallest price change the broker actually accepts. Usually equal to
    ``point`` but not guaranteed, which is why it is stored separately.

Getting this wrong is a 10x error in every threshold on a gold symbol. That is
precisely the class of defect this module exists to prevent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "InvalidSymbolSpecificationError",
    "MT5SymbolInfoLike",
    "SymbolSpecification",
    "EURUSD_5DIGIT",
    "XAUUSD_2DIGIT",
    "XAUUSD_3DIGIT",
]

# Tolerance used when checking that one price increment is an exact multiple of
# another. Chosen to absorb IEEE-754 representation error on values such as
# 0.1 / 0.01 while still rejecting genuinely inconsistent specifications.
_MULTIPLE_TOLERANCE = 1e-9


class InvalidSymbolSpecificationError(ValueError):
    """Raised when a :class:`SymbolSpecification` is internally inconsistent."""


@runtime_checkable
class MT5SymbolInfoLike(Protocol):
    """Structural type describing the fields used from an MT5 ``symbol_info``.

    Declared as a :class:`~typing.Protocol` so this module never imports
    ``MetaTrader5``. Any object exposing these attributes -- the real MT5
    namedtuple, a test double, or a recorded fixture -- is accepted.
    """

    name: str
    digits: int
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    currency_base: str
    currency_profit: str


@dataclass(frozen=True, slots=True)
class SymbolSpecification:
    """Immutable description of one tradeable instrument as the broker defines it.

    All conversions in :mod:`core.units` and all position-size arithmetic require
    one of these. Construct it from the broker via
    :meth:`from_mt5_symbol_info`; the module-level constants below exist for
    tests and documentation only.

    Attributes:
        symbol: Broker symbol name, e.g. ``"XAUUSD"``.
        digits: Number of decimal places in a quote.
        point: Smallest representable price increment (``10 ** -digits``).
        pip_size: Price distance of one pip, by market convention. **Explicit,
            never inferred** -- see the module docstring.
        tick_size: Smallest price change the broker accepts.
        tick_value: Value, in ``account_currency``, of a ``tick_size`` move on
            ``1.0`` lot.
        contract_size: Units of the base asset in ``1.0`` lot. XAUUSD is
            typically ``100`` troy ounces.
        volume_min: Smallest permitted order volume, in lots.
        volume_max: Largest permitted order volume, in lots.
        volume_step: Volume increment, in lots.
        base_currency: Base currency / underlying asset code.
        quote_currency: Currency the instrument is quoted in.
        account_currency: Currency ``tick_value`` is denominated in.
    """

    symbol: str
    digits: int
    point: float
    pip_size: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    base_currency: str = ""
    quote_currency: str = ""
    account_currency: str = "USD"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Reject internally inconsistent specifications at construction time.

        Raises:
            InvalidSymbolSpecificationError: If any field is non-positive where a
                positive value is required, or if ``pip_size`` is not a whole
                multiple of ``point``, or if the volume bounds are contradictory.
        """
        if not self.symbol:
            raise InvalidSymbolSpecificationError("symbol must be a non-empty string")
        if self.digits < 0:
            raise InvalidSymbolSpecificationError(
                f"{self.symbol}: digits must be >= 0, got {self.digits}"
            )

        for field_name in ("point", "pip_size", "tick_size", "contract_size", "volume_step"):
            value = getattr(self, field_name)
            if not math.isfinite(value) or value <= 0.0:
                raise InvalidSymbolSpecificationError(
                    f"{self.symbol}: {field_name} must be finite and > 0, got {value!r}"
                )

        if not math.isfinite(self.tick_value) or self.tick_value <= 0.0:
            raise InvalidSymbolSpecificationError(
                f"{self.symbol}: tick_value must be finite and > 0, got {self.tick_value!r}"
            )

        if self.volume_min <= 0.0:
            raise InvalidSymbolSpecificationError(
                f"{self.symbol}: volume_min must be > 0, got {self.volume_min}"
            )
        if self.volume_max < self.volume_min:
            raise InvalidSymbolSpecificationError(
                f"{self.symbol}: volume_max ({self.volume_max}) < "
                f"volume_min ({self.volume_min})"
            )

        # A pip that is not a whole number of points indicates the two values came
        # from different conventions -- exactly the confusion this class prevents.
        points_per_pip = self.pip_size / self.point
        if abs(points_per_pip - round(points_per_pip)) > _MULTIPLE_TOLERANCE:
            raise InvalidSymbolSpecificationError(
                f"{self.symbol}: pip_size ({self.pip_size}) is not a whole multiple "
                f"of point ({self.point}); got {points_per_pip} points per pip"
            )

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def points_per_pip(self) -> float:
        """How many points make up one pip for this instrument.

        ``10.0`` for 2-digit gold and for 5-digit FX; ``1.0`` for 4-digit FX.
        """
        return self.pip_size / self.point

    # ------------------------------------------------------------------
    # Rounding helpers
    # ------------------------------------------------------------------

    def round_to_tick(self, price: float) -> float:
        """Round ``price`` to the nearest valid tick, then to ``digits``.

        Args:
            price: Raw price in quote currency.

        Returns:
            The nearest broker-representable price.

        Raises:
            ValueError: If ``price`` is not finite.
        """
        if not math.isfinite(price):
            raise ValueError(f"price must be finite, got {price!r}")
        ticks = round(price / self.tick_size)
        return round(ticks * self.tick_size, self.digits)

    def round_volume_to_step(self, volume: float) -> float:
        """Round ``volume`` down to the nearest valid volume step.

        Rounding is **downward** on purpose: rounding a position size up would
        take more risk than the risk engine authorised.

        Args:
            volume: Desired volume in lots.

        Returns:
            The largest valid volume not exceeding ``volume``. May be ``0.0``
            if ``volume`` is smaller than one step -- callers must handle that
            rather than silently substituting a minimum.

        Raises:
            ValueError: If ``volume`` is not finite or is negative.
        """
        if not math.isfinite(volume):
            raise ValueError(f"volume must be finite, got {volume!r}")
        if volume < 0.0:
            raise ValueError(f"volume must be >= 0, got {volume!r}")
        steps = math.floor((volume + _MULTIPLE_TOLERANCE) / self.volume_step)
        return round(steps * self.volume_step, 8)

    def clamp_volume(self, volume: float) -> float:
        """Clamp ``volume`` into ``[volume_min, volume_max]`` and snap to step.

        Note:
            Clamping **upward** to ``volume_min`` can increase risk beyond what
            was requested. Callers that must not exceed a risk budget should
            check :meth:`is_volume_tradeable` first and decline the trade rather
            than accept an inflated size. ``risk_manager.calculate_lot_size_for_symbol``
            currently does the unsafe thing (``max(0.01, ...)``); recorded in
            ``PHASE_2_ISSUES.md``, not changed in this phase.

        Args:
            volume: Desired volume in lots.

        Returns:
            A broker-valid volume within the permitted bounds.
        """
        snapped = self.round_volume_to_step(volume)
        if snapped < self.volume_min:
            return self.volume_min
        if snapped > self.volume_max:
            return self.round_volume_to_step(self.volume_max)
        return snapped

    def is_volume_tradeable(self, volume: float) -> bool:
        """Return whether ``volume`` can be traded without being clamped upward.

        Args:
            volume: Desired volume in lots.

        Returns:
            ``True`` if ``volume`` snaps to a valid step at or above
            ``volume_min`` and at or below ``volume_max``.
        """
        if not math.isfinite(volume) or volume < 0.0:
            return False
        snapped = self.round_volume_to_step(volume)
        return self.volume_min <= snapped <= self.volume_max

    # ------------------------------------------------------------------
    # Monetary conversion
    # ------------------------------------------------------------------

    def money_per_price_unit(self, volume: float = 1.0) -> float:
        """Account-currency value of a ``1.0`` price move on ``volume`` lots.

        Derived from ``tick_value / tick_size`` rather than from a hardcoded
        contract size, so it stays correct for brokers whose tick size differs
        from their point size.

        For XAUUSD with ``tick_size=0.01`` and ``tick_value=1.0`` this returns
        ``100.0`` per lot -- the value ``risk_manager`` currently assumes to be
        ``10.0``.

        Args:
            volume: Position size in lots.

        Returns:
            Money value of a one-unit price move.

        Raises:
            ValueError: If ``volume`` is negative or not finite.
        """
        if not math.isfinite(volume) or volume < 0.0:
            raise ValueError(f"volume must be finite and >= 0, got {volume!r}")
        return (self.tick_value / self.tick_size) * volume

    def money_for_price_distance(self, price_distance: float, volume: float = 1.0) -> float:
        """Account-currency value of a ``price_distance`` move on ``volume`` lots.

        This is the primitive correct position sizing will be built on in Phase 2.
        It is **not** wired into ``risk_manager`` in this phase.

        Args:
            price_distance: Distance in quote-currency price units. Sign is
                ignored; magnitude is used.
            volume: Position size in lots.

        Returns:
            Absolute money value of the move.

        Raises:
            ValueError: If either argument is not finite, or ``volume`` < 0.
        """
        if not math.isfinite(price_distance):
            raise ValueError(f"price_distance must be finite, got {price_distance!r}")
        return abs(price_distance) * self.money_per_price_unit(volume)

    # ------------------------------------------------------------------
    # Construction from a broker
    # ------------------------------------------------------------------

    @classmethod
    def from_mt5_symbol_info(
        cls,
        info: MT5SymbolInfoLike | Any,
        *,
        pip_size: float,
        account_currency: str = "USD",
    ) -> SymbolSpecification:
        """Build a specification from an MT5 ``symbol_info`` object.

        ``pip_size`` is a **required keyword argument** with no default. MT5 does
        not report a pip size, and inferring one is the exact mistake this module
        exists to prevent: for gold the answer depends on a market convention the
        terminal knows nothing about. The caller must state it.

        Args:
            info: Any object exposing the attributes in :class:`MT5SymbolInfoLike`.
                Duck-typed so this module never imports ``MetaTrader5``.
            pip_size: Price distance of one pip, e.g. ``0.10`` for XAUUSD.
            account_currency: Currency ``trade_tick_value`` is denominated in.

        Returns:
            A validated :class:`SymbolSpecification`.

        Raises:
            InvalidSymbolSpecificationError: If ``info`` lacks a required
                attribute, or if the resulting specification is inconsistent.
        """
        required = (
            "name",
            "digits",
            "point",
            "trade_tick_size",
            "trade_tick_value",
            "trade_contract_size",
            "volume_min",
            "volume_max",
            "volume_step",
        )
        missing = [attribute for attribute in required if not hasattr(info, attribute)]
        if missing:
            raise InvalidSymbolSpecificationError(
                f"symbol_info object is missing required attributes: {', '.join(missing)}"
            )

        # Some brokers report trade_tick_size == 0; fall back to point in that case.
        raw_tick_size = float(info.trade_tick_size)
        tick_size = raw_tick_size if raw_tick_size > 0.0 else float(info.point)

        return cls(
            symbol=str(info.name),
            digits=int(info.digits),
            point=float(info.point),
            pip_size=float(pip_size),
            tick_size=tick_size,
            tick_value=float(info.trade_tick_value),
            contract_size=float(info.trade_contract_size),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            base_currency=str(getattr(info, "currency_base", "") or ""),
            quote_currency=str(getattr(info, "currency_profit", "") or ""),
            account_currency=account_currency,
        )


# ---------------------------------------------------------------------------
# Reference specifications
#
# For tests and documentation ONLY. Production code must obtain a specification
# from the broker via `from_mt5_symbol_info`. These constants exist so that unit
# tests can prove conversions behave differently across instruments -- which is
# how we demonstrate nothing is hardcoded to gold.
# ---------------------------------------------------------------------------

XAUUSD_2DIGIT = SymbolSpecification(
    symbol="XAUUSD",
    digits=2,
    point=0.01,
    pip_size=0.10,          # gold convention: 1 pip = $0.10 = 10 points
    tick_size=0.01,
    tick_value=1.0,         # $1.00 per 0.01 move on 1.0 lot => $100 per $1.00 move
    contract_size=100.0,    # 100 troy ounces
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    base_currency="XAU",
    quote_currency="USD",
    account_currency="USD",
)
"""Reference XAUUSD as quoted by a 2-decimal broker. Test/documentation use only."""

XAUUSD_3DIGIT = SymbolSpecification(
    symbol="XAUUSD",
    digits=3,
    point=0.001,
    pip_size=0.10,          # still $0.10 by convention -- now 100 points, not 10
    tick_size=0.001,
    tick_value=0.1,
    contract_size=100.0,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    base_currency="XAU",
    quote_currency="USD",
    account_currency="USD",
)
"""Reference XAUUSD as quoted by a 3-decimal broker.

Exists to prove that ``points_per_pip`` is broker-dependent (``100`` here versus
``10`` for :data:`XAUUSD_2DIGIT`) and must never be hardcoded.
"""

EURUSD_5DIGIT = SymbolSpecification(
    symbol="EURUSD",
    digits=5,
    point=0.00001,
    pip_size=0.0001,        # FX convention: 1 pip = 10 points at 5-digit quoting
    tick_size=0.00001,
    tick_value=0.1,
    contract_size=100_000.0,
    volume_min=0.01,
    volume_max=200.0,
    volume_step=0.01,
    base_currency="EUR",
    quote_currency="USD",
    account_currency="USD",
)
"""Reference 5-digit EURUSD. Test/documentation use only."""
