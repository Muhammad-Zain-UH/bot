"""Canonical unit system for prices, distances and thresholds.

Why this module exists
----------------------
The Phase 1 audit found the same numeric literal meaning different things in
different files. On a 2-digit gold symbol these three are *not* interchangeable::

    PriceDistance(3.0)   ==  $3.00  ==  30 pips  ==  300 points
    Pips(3.0)            ==  $0.30  ==   3 pips  ==   30 points
    Points(3.0)          ==  $0.03  ==  0.3 pips ==    3 points

Real defects caused by conflating them (all still present in strategy code and
deliberately untouched in this phase -- see ``PHASE_2_ISSUES.md``):

* ``entry_engine._select_stop_anchor`` subtracts ``buffer_pips = 3.0`` directly
  from a price, producing a **$3.00 (30 pip)** stop buffer where 3 pips was
  intended.
* ``liquidity_engine.assess_liquidity_gate`` caps sweep distance at ``60.0``
  "pips", which is **$60 (600 pips)** -- effectively no cap at all.
* ``poi_engine.score_poi`` awards a size bonus for zones of ``5..15`` "pips",
  which is **$5..$15** -- a range an M15 order block essentially never reaches.

The rule this module enforces
-----------------------------
**A bare number is never a distance.** Distances are typed, and every conversion
requires an explicit :class:`~core.symbols.SymbolSpecification` because the
answer is broker- and instrument-dependent. Mixing types raises
:class:`UnitMismatchError` rather than silently producing a wrong number.

Design notes
------------
*Floats, not ``Decimal``.* MT5 returns float64 and the entire data pipeline is
pandas. Introducing ``Decimal`` at this boundary would force a conversion at
every call site for no accuracy gain on quantities that are already
tick-quantised. Precision is instead handled explicitly: comparisons use a
tolerance, and broker-valid values are produced on demand via
:meth:`PriceDistance.quantize`.

*Conversions do not round.* Rounding inside a conversion would silently destroy
sub-tick quantities (``Pips(0.05)`` on 2-digit gold is ``$0.005``). Round only at
the boundary where a broker-representable number is actually required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from core.symbols import SymbolSpecification

__all__ = [
    "AtrMultiple",
    "Percentage",
    "Pips",
    "Points",
    "PriceDistance",
    "UnitMismatchError",
    "COMPARISON_TOLERANCE",
]

COMPARISON_TOLERANCE: Final[float] = 1e-9
"""Absolute tolerance used when comparing two quantities of the same unit."""


class UnitMismatchError(TypeError):
    """Raised when quantities of different units are combined or compared.

    This is deliberately an error rather than an implicit conversion. An implicit
    conversion is what produced the 10x threshold defects this module prevents.
    """


@dataclass(frozen=True, slots=True, eq=False, order=False)
class _Quantity:
    """Base for all typed quantities.

    Subclasses are distinguished by type, not by a tag field, so the type checker
    and the runtime both reject mixing. Arithmetic is permitted only between
    identical subclasses, or between a quantity and a plain scalar.

    Attributes:
        value: The magnitude, in whatever unit the concrete subclass denotes.
    """

    value: float

    def __post_init__(self) -> None:
        """Validate that the magnitude is a finite real number.

        Raises:
            ValueError: If ``value`` is NaN or infinite.
        """
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise ValueError(
                f"{type(self).__name__} value must be a real number, "
                f"got {type(self.value).__name__}"
            )
        if not math.isfinite(float(self.value)):
            raise ValueError(f"{type(self).__name__} value must be finite, got {self.value!r}")
        # Normalise ints to float so `Pips(3) == Pips(3.0)` and repr is stable.
        object.__setattr__(self, "value", float(self.value))

    # -- unit guard ----------------------------------------------------

    def _require_same_unit(self, other: object, operation: str) -> _Quantity:
        """Return ``other`` if it is the same unit, else raise.

        Args:
            other: The right-hand operand.
            operation: Human-readable operation name, used in the message.

        Returns:
            ``other``, narrowed to this quantity's type.

        Raises:
            UnitMismatchError: If ``other`` is a different unit or not a quantity.
        """
        if type(other) is not type(self):
            this = type(self).__name__
            that = type(other).__name__ if isinstance(other, _Quantity) else repr(other)
            raise UnitMismatchError(
                f"cannot {operation} {this} and {that}: units differ. "
                f"Convert explicitly with a SymbolSpecification first."
            )
        return other  # type: ignore[return-value]

    # -- comparison ----------------------------------------------------

    def __eq__(self, other: object) -> bool:
        """Tolerance-aware equality, and only between identical units.

        Returns ``False`` (rather than raising) for a different unit so that
        ``Pips(3) == PriceDistance(3.0)`` is a safe, meaningful ``False`` and
        containers behave sanely.
        """
        if type(other) is not type(self):
            return False
        return math.isclose(
            self.value, other.value, rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE  # type: ignore[attr-defined]
        )

    def __hash__(self) -> int:
        return hash((type(self).__name__, round(self.value, 9)))

    def __lt__(self, other: object) -> bool:
        return self.value < self._require_same_unit(other, "compare").value

    def __le__(self, other: object) -> bool:
        return self.value <= self._require_same_unit(other, "compare").value

    def __gt__(self, other: object) -> bool:
        return self.value > self._require_same_unit(other, "compare").value

    def __ge__(self, other: object) -> bool:
        return self.value >= self._require_same_unit(other, "compare").value

    # -- arithmetic ----------------------------------------------------

    def __add__(self, other: object):  # noqa: ANN204 - concrete type is type(self)
        return type(self)(self.value + self._require_same_unit(other, "add").value)

    def __sub__(self, other: object):  # noqa: ANN204
        return type(self)(self.value - self._require_same_unit(other, "subtract").value)

    def __mul__(self, factor: float):  # noqa: ANN204
        if isinstance(factor, _Quantity):
            raise UnitMismatchError(
                f"cannot multiply {type(self).__name__} by {type(factor).__name__}; "
                f"multiply by a plain scalar instead"
            )
        return type(self)(self.value * float(factor))

    __rmul__ = __mul__

    def __truediv__(self, divisor: object):  # noqa: ANN204
        """Divide by a scalar (-> same unit) or by the same unit (-> plain ratio)."""
        if type(divisor) is type(self):
            denominator = divisor.value  # type: ignore[attr-defined]
            if denominator == 0.0:
                raise ZeroDivisionError(f"division by zero {type(self).__name__}")
            return self.value / denominator
        if isinstance(divisor, _Quantity):
            raise UnitMismatchError(
                f"cannot divide {type(self).__name__} by {type(divisor).__name__}"
            )
        if float(divisor) == 0.0:
            raise ZeroDivisionError("division by zero")
        return type(self)(self.value / float(divisor))

    def __neg__(self):  # noqa: ANN204
        return type(self)(-self.value)

    def __abs__(self):  # noqa: ANN204
        return type(self)(abs(self.value))

    def __bool__(self) -> bool:
        return self.value != 0.0


@dataclass(frozen=True, slots=True, eq=False, order=False)
class PriceDistance(_Quantity):
    """A distance in quote-currency price units. The canonical base unit.

    On XAUUSD, ``PriceDistance(3.0)`` is **$3.00**, which is 30 pips -- not 3.

    Every other distance unit converts through this type.
    """

    def to_pips(self, spec: SymbolSpecification) -> Pips:
        """Convert to pips using the instrument's pip convention.

        Args:
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The equivalent distance in pips.
        """
        return Pips(self.value / spec.pip_size)

    def to_points(self, spec: SymbolSpecification) -> Points:
        """Convert to points using the instrument's point size.

        Args:
            spec: Broker specification supplying ``point``.

        Returns:
            The equivalent distance in points.
        """
        return Points(self.value / spec.point)

    def to_percentage(self, reference_price: float) -> Percentage:
        """Express this distance as a percentage of ``reference_price``.

        Args:
            reference_price: The price the percentage is relative to.

        Returns:
            The equivalent :class:`Percentage`.

        Raises:
            ValueError: If ``reference_price`` is zero or not finite.
        """
        if not math.isfinite(reference_price) or reference_price == 0.0:
            raise ValueError(
                f"reference_price must be finite and non-zero, got {reference_price!r}"
            )
        return Percentage(self.value / reference_price * 100.0)

    def to_atr_multiple(self, atr: PriceDistance) -> AtrMultiple:
        """Express this distance as a multiple of ``atr``.

        Args:
            atr: The ATR value, as a price distance.

        Returns:
            The equivalent :class:`AtrMultiple`.

        Raises:
            UnitMismatchError: If ``atr`` is not a :class:`PriceDistance`.
            ValueError: If ``atr`` is zero.
        """
        if not isinstance(atr, PriceDistance):
            raise UnitMismatchError(
                f"atr must be a PriceDistance, got {type(atr).__name__}"
            )
        if atr.value == 0.0:
            raise ValueError("cannot express a distance as a multiple of a zero ATR")
        return AtrMultiple(self.value / atr.value)

    def quantize(self, spec: SymbolSpecification) -> PriceDistance:
        """Snap to the nearest whole number of ticks.

        Use only where a broker-representable distance is genuinely required;
        quantising early destroys sub-tick precision.

        Args:
            spec: Broker specification supplying ``tick_size`` and ``digits``.

        Returns:
            A tick-aligned :class:`PriceDistance`.
        """
        ticks = round(self.value / spec.tick_size)
        return PriceDistance(round(ticks * spec.tick_size, spec.digits))

    def above(self, price: float) -> float:
        """Return ``price`` moved up by this distance.

        Args:
            price: The reference price.

        Returns:
            ``price + self.value``.
        """
        return price + self.value

    def below(self, price: float) -> float:
        """Return ``price`` moved down by this distance.

        Args:
            price: The reference price.

        Returns:
            ``price - self.value``.
        """
        return price - self.value


@dataclass(frozen=True, slots=True, eq=False, order=False)
class Pips(_Quantity):
    """A distance in pips, by the instrument's market convention.

    A pip is **not** derivable from ``digits``. For gold it is ``$0.10``
    regardless of whether the broker quotes 2 or 3 decimals; for 5-digit FX it is
    ``0.0001``. The value comes from
    :attr:`~core.symbols.SymbolSpecification.pip_size`.
    """

    def to_price(self, spec: SymbolSpecification) -> PriceDistance:
        """Convert to a quote-currency price distance.

        Args:
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The equivalent :class:`PriceDistance`.
        """
        return PriceDistance(self.value * spec.pip_size)

    def to_points(self, spec: SymbolSpecification) -> Points:
        """Convert to points via the instrument's points-per-pip ratio.

        Args:
            spec: Broker specification supplying ``pip_size`` and ``point``.

        Returns:
            The equivalent :class:`Points`.
        """
        return Points(self.value * spec.points_per_pip)


@dataclass(frozen=True, slots=True, eq=False, order=False)
class Points(_Quantity):
    """A distance in points -- the smallest representable price increment.

    ``point == 10 ** -digits``. MT5's raw ``(ask - bid) / point`` spread is in
    points, **not** pips; conflating the two is what
    ``mt5_handler.get_current_spread`` was fixed for (it is now correct).
    """

    def to_price(self, spec: SymbolSpecification) -> PriceDistance:
        """Convert to a quote-currency price distance.

        Args:
            spec: Broker specification supplying ``point``.

        Returns:
            The equivalent :class:`PriceDistance`.
        """
        return PriceDistance(self.value * spec.point)

    def to_pips(self, spec: SymbolSpecification) -> Pips:
        """Convert to pips via the instrument's points-per-pip ratio.

        Args:
            spec: Broker specification supplying ``pip_size`` and ``point``.

        Returns:
            The equivalent :class:`Pips`.
        """
        return Pips(self.value / spec.points_per_pip)


@dataclass(frozen=True, slots=True, eq=False, order=False)
class Percentage(_Quantity):
    """A percentage. ``Percentage(0.5)`` means **0.5 %**, not 50 %.

    Used for risk-per-trade and for price distances expressed relatively. The
    existing config mixes both conventions (``INTRADAY_RISK_PER_TRADE = 0.5``
    meaning 0.5 %, alongside ratios such as ``PULLBACK_RATIO_MIN = 0.38``
    meaning 38 %); this type fixes the meaning to *percent*.
    """

    def to_price(self, reference_price: float) -> PriceDistance:
        """Convert to an absolute price distance relative to ``reference_price``.

        Args:
            reference_price: The price the percentage is relative to.

        Returns:
            The equivalent :class:`PriceDistance`.

        Raises:
            ValueError: If ``reference_price`` is not finite.
        """
        if not math.isfinite(reference_price):
            raise ValueError(f"reference_price must be finite, got {reference_price!r}")
        return PriceDistance(reference_price * self.value / 100.0)

    def as_fraction(self) -> float:
        """Return the value as a plain fraction (``Percentage(0.5) -> 0.005``)."""
        return self.value / 100.0

    @classmethod
    def from_fraction(cls, fraction: float) -> Percentage:
        """Build from a plain fraction (``0.005 -> Percentage(0.5)``).

        Args:
            fraction: The fractional value.

        Returns:
            The equivalent :class:`Percentage`.
        """
        return cls(fraction * 100.0)


@dataclass(frozen=True, slots=True, eq=False, order=False)
class AtrMultiple(_Quantity):
    """A dimensionless multiple of an ATR value.

    Kept distinct from a bare float so that "1.5 ATR" can never be mistaken for
    "1.5 price units". Resolving it to a real distance requires the ATR itself,
    which is why :meth:`to_price` takes one.
    """

    def to_price(self, atr: PriceDistance) -> PriceDistance:
        """Resolve to an absolute price distance using a concrete ATR value.

        Args:
            atr: The ATR, as a price distance. Obtain it from
                :func:`core.indicators.atr_wilder`.

        Returns:
            The equivalent :class:`PriceDistance`.

        Raises:
            UnitMismatchError: If ``atr`` is not a :class:`PriceDistance`.
        """
        if not isinstance(atr, PriceDistance):
            raise UnitMismatchError(
                f"atr must be a PriceDistance, got {type(atr).__name__}. "
                f"An ATR expressed in pips must be converted to price first."
            )
        return PriceDistance(self.value * atr.value)

    def to_pips(self, atr: PriceDistance, spec: SymbolSpecification) -> Pips:
        """Resolve to pips using a concrete ATR value and a symbol specification.

        Args:
            atr: The ATR, as a price distance.
            spec: Broker specification supplying ``pip_size``.

        Returns:
            The equivalent :class:`Pips`.
        """
        return self.to_price(atr).to_pips(spec)
