"""Canonical domain types.

Why this module exists
----------------------
The Phase 1 audit found the entire pipeline passing ``dict[str, Any]`` between
eight layers, accessed with ``.get(key, default)``. A mistyped key does not
raise -- it yields the default, and the pipeline continues with a silently
fabricated zero. ``poi.get("score", 0)``, ``sweep.get("sweep_quality", 0.0)`` and
``.get(...) or 0.0`` appear throughout.

These types replace guessing with validation at construction. Several encode a
specific audit finding as an invariant that can no longer be violated:

* :class:`StopLoss` rejects a stop on the wrong side of entry. Today
  ``entry_engine.calculate_entry_levels`` computes ``risk_distance =
  abs(entry - stop)`` with no side check, so an inverted trade passes validation
  as normal.
* :class:`MarketBar` rejects ``high < low`` and a close outside the bar range.
* :class:`MarketPrice` rejects a crossed book (``ask < bid``) and exposes
  :meth:`~MarketPrice.price_for`, so the executable side of the book is chosen
  explicitly rather than by using a mid price for both directions.
* :class:`RiskParameters` rejects non-positive risk.

Phase 0/1 scope
---------------
These types are **not** yet threaded through the strategy engines. Migrating
eight layers of dict access at once is exactly the "change everything
simultaneously" failure mode this project is avoiding. They are the foundation
the Phase 2+ migration will move onto, one boundary at a time.

Design notes
------------
Frozen dataclasses with ``slots=True`` throughout: values are immutable, cheap,
and comparable. No third-party dependency -- ``pydantic`` is present in the
virtualenv but absent from ``requirements.txt``, so relying on it would
introduce an undeclared dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.symbols import SymbolSpecification
from core.units import Percentage, PriceDistance

__all__ = [
    "DomainInvariantError",
    "FairValueGap",
    "FairValueGapKind",
    "LiquidityLevel",
    "LiquidityLevelKind",
    "LiquiditySweep",
    "MarketBar",
    "MarketPrice",
    "OrderBlock",
    "OrderKind",
    "OrderRequest",
    "OrderResult",
    "OrderResultStatus",
    "Position",
    "PositionStatus",
    "RiskParameters",
    "Side",
    "Signal",
    "SignalType",
    "StopLoss",
    "SwingPoint",
    "SwingType",
    "TakeProfit",
    "bar_from_mapping",
    "Timeframe",
    "TradingSetup",
]


class DomainInvariantError(ValueError):
    """Raised when a domain object would violate one of its invariants."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Side(Enum):
    """Trade direction.

    Replaces the free-form strings currently in use (``"BUY"``/``"SELL"``,
    ``"BULLISH"``/``"BEARISH"``, ``"bullish_sweep"``/``"bearish_sweep"``), which
    are compared with ``.lower()`` and substring matching in
    ``main_production.analyze_entry``.
    """

    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """``+1`` for :attr:`BUY`, ``-1`` for :attr:`SELL`.

        Lets direction-dependent arithmetic be written once instead of as
        mirrored ``if``/``else`` branches -- the pattern that produced the
        inverted SELL partial-exit levels in ``order_execution.create_order``.
        """
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        """The opposing direction."""
        return Side.SELL if self is Side.BUY else Side.BUY

    @classmethod
    def from_bias(cls, bias: str) -> Side:
        """Map a legacy bias string onto a :class:`Side`.

        Args:
            bias: One of ``"BULLISH"``/``"BUY"`` or ``"BEARISH"``/``"SELL"``,
                case-insensitive.

        Returns:
            The corresponding side.

        Raises:
            DomainInvariantError: If ``bias`` is neutral or unrecognised. The
                legacy helper ``main_production._bias_to_side`` maps *anything*
                that is not ``"BULLISH"`` to ``SELL``, silently turning
                ``"NEUTRAL"`` into a short.
        """
        normalised = str(bias).strip().upper()
        if normalised in {"BULLISH", "BUY", "LONG"}:
            return cls.BUY
        if normalised in {"BEARISH", "SELL", "SHORT"}:
            return cls.SELL
        raise DomainInvariantError(
            f"cannot derive a trade side from bias {bias!r}; "
            f"expected BULLISH/BUY/LONG or BEARISH/SELL/SHORT"
        )


class Timeframe(Enum):
    """Chart timeframe, with its duration in minutes."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def minutes(self) -> int:
        """Duration of one bar, in minutes."""
        return {
            Timeframe.M1: 1,
            Timeframe.M5: 5,
            Timeframe.M15: 15,
            Timeframe.M30: 30,
            Timeframe.H1: 60,
            Timeframe.H4: 240,
            Timeframe.D1: 1440,
            Timeframe.W1: 10080,
        }[self]


class SwingType(Enum):
    """Whether a swing point is a pivot high or a pivot low."""

    HIGH = "HIGH"
    LOW = "LOW"


class LiquidityLevelKind(Enum):
    """Origin of a liquidity level."""

    EQUAL_HIGH = "equal_high"
    EQUAL_LOW = "equal_low"
    ASIAN_HIGH = "asian_high"
    ASIAN_LOW = "asian_low"
    PREVIOUS_DAY_HIGH = "pdh"
    PREVIOUS_DAY_LOW = "pdl"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    ROUND_NUMBER = "round_number"
    HTF_LEVEL = "htf_level"


class FairValueGapKind(Enum):
    """Direction of the imbalance a fair value gap represents."""

    BULLISH = "bullish"
    BEARISH = "bearish"


class SignalType(Enum):
    """Outcome of one decision pass."""

    ENTRY = "ENTRY_SIGNAL"
    PRE_ENTRY = "PRE_ENTRY"
    NO_SIGNAL = "NO_SIGNAL"


class OrderKind(Enum):
    """How an order is to be placed."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderResultStatus(Enum):
    """Terminal outcome of an order submission."""

    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    NOT_SUBMITTED = "NOT_SUBMITTED"


class PositionStatus(Enum):
    """Lifecycle state of a position."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_finite(value: float, name: str) -> float:
    """Return ``value`` as a float, rejecting NaN and infinity.

    Args:
        value: Candidate number.
        name: Field name, used in the error message.

    Returns:
        ``value`` as a ``float``.

    Raises:
        DomainInvariantError: If ``value`` is not a finite real number.
    """
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainInvariantError(f"{name} must be a real number, got {value!r}") from exc
    if not math.isfinite(as_float):
        raise DomainInvariantError(f"{name} must be finite, got {value!r}")
    return as_float


def _require_positive(value: float, name: str) -> float:
    """Return ``value``, rejecting non-positive numbers.

    Args:
        value: Candidate number.
        name: Field name, used in the error message.

    Returns:
        ``value`` as a ``float``.

    Raises:
        DomainInvariantError: If ``value`` is not finite or is <= 0.
    """
    as_float = _require_finite(value, name)
    if as_float <= 0.0:
        raise DomainInvariantError(f"{name} must be > 0, got {as_float}")
    return as_float


def _require_aware(moment: datetime, name: str) -> datetime:
    """Return ``moment``, rejecting naive datetimes.

    Args:
        moment: Candidate datetime.
        name: Field name, used in the error message.

    Returns:
        ``moment`` unchanged.

    Raises:
        DomainInvariantError: If ``moment`` is not a timezone-aware datetime.
    """
    if not isinstance(moment, datetime):
        raise DomainInvariantError(f"{name} must be a datetime, got {type(moment).__name__}")
    if moment.tzinfo is None:
        raise DomainInvariantError(
            f"{name} must be timezone-aware. Naive timestamps are how local time "
            f"gets compared against UTC market data without any error being raised."
        )
    return moment


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarketBar:
    """One completed OHLC bar.

    Attributes:
        timestamp: Bar open time. Must be timezone-aware.
        open: Opening price.
        high: Highest traded price.
        low: Lowest traded price.
        close: Closing price.
        volume: Tick or real volume. Non-negative.
        timeframe: Which timeframe the bar belongs to, if known.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: Timeframe | None = None

    def __post_init__(self) -> None:
        """Validate OHLC consistency.

        Raises:
            DomainInvariantError: If the timestamp is naive, any price is
                non-positive, ``high < low``, or ``high``/``low`` do not bracket
                both ``open`` and ``close``.
        """
        _require_aware(self.timestamp, "timestamp")
        for name in ("open", "high", "low", "close"):
            _require_positive(getattr(self, name), name)
        if _require_finite(self.volume, "volume") < 0.0:
            raise DomainInvariantError(f"volume must be >= 0, got {self.volume}")

        if self.high < self.low:
            raise DomainInvariantError(
                f"high ({self.high}) < low ({self.low}) at {self.timestamp.isoformat()}"
            )
        body_top = max(self.open, self.close)
        body_bottom = min(self.open, self.close)
        if self.high < body_top:
            raise DomainInvariantError(
                f"high ({self.high}) is below max(open, close) ({body_top}) "
                f"at {self.timestamp.isoformat()}"
            )
        if self.low > body_bottom:
            raise DomainInvariantError(
                f"low ({self.low}) is above min(open, close) ({body_bottom}) "
                f"at {self.timestamp.isoformat()}"
            )

    @property
    def range(self) -> PriceDistance:
        """Full bar range, ``high - low``."""
        return PriceDistance(self.high - self.low)

    @property
    def body(self) -> PriceDistance:
        """Absolute body size, ``|close - open|``."""
        return PriceDistance(abs(self.close - self.open))

    @property
    def upper_wick(self) -> PriceDistance:
        """Distance from the body top to the high."""
        return PriceDistance(self.high - max(self.open, self.close))

    @property
    def lower_wick(self) -> PriceDistance:
        """Distance from the body bottom to the low."""
        return PriceDistance(min(self.open, self.close) - self.low)

    @property
    def is_bullish(self) -> bool:
        """Whether the bar closed above its open."""
        return self.close > self.open

    def close_position(self) -> float:
        """Where the close sits within the range, ``0.0`` (low) to ``1.0`` (high).

        Returns:
            ``0.5`` for a zero-range bar, avoiding a division by zero.
        """
        span = self.high - self.low
        if span <= 0.0:
            return 0.5
        return (self.close - self.low) / span


@dataclass(frozen=True, slots=True)
class MarketPrice:
    """A bid/ask quote at an instant.

    Attributes:
        timestamp: Quote time. Must be timezone-aware.
        bid: Best bid.
        ask: Best ask.
    """

    timestamp: datetime
    bid: float
    ask: float

    def __post_init__(self) -> None:
        """Validate the quote.

        Raises:
            DomainInvariantError: If the timestamp is naive, either side is
                non-positive, or the book is crossed (``ask < bid``).
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.bid, "bid")
        _require_positive(self.ask, "ask")
        if self.ask < self.bid:
            raise DomainInvariantError(
                f"crossed quote: ask ({self.ask}) < bid ({self.bid})"
            )

    @property
    def mid(self) -> float:
        """Midpoint of the quote.

        Warning:
            The mid is **not tradeable**. Use :meth:`price_for` to obtain the
            side a given direction actually executes against.
        """
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> PriceDistance:
        """The bid/ask spread as a price distance.

        Convert with ``.to_pips(spec)`` -- never divide by ``point`` and call the
        result pips, which is the error ``mt5_handler.get_current_spread`` was
        fixed for.
        """
        return PriceDistance(self.ask - self.bid)

    def price_for(self, side: Side) -> float:
        """Return the price ``side`` actually executes at.

        A BUY lifts the ask; a SELL hits the bid. Pricing both from the mid
        understates cost by half the spread on entry and again on exit.

        Args:
            side: The trade direction.

        Returns:
            ``ask`` for :attr:`Side.BUY`, ``bid`` for :attr:`Side.SELL`.
        """
        return self.ask if side is Side.BUY else self.bid


# ---------------------------------------------------------------------------
# Market structure / SMC
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwingPoint:
    """A confirmed fractal swing high or low.

    Attributes:
        timestamp: Time of the swing bar. Must be timezone-aware.
        price: The extreme price of the swing.
        swing_type: Whether this is a pivot high or low.
        bars_since: How many closed bars have elapsed since the swing bar.
        confirmation_bars: Bars required on each side to confirm the fractal.
            A swing is only confirmed ``confirmation_bars`` bars after it forms;
            recording it makes that lag explicit rather than implied.
    """

    timestamp: datetime
    price: float
    swing_type: SwingType
    bars_since: int = 0
    confirmation_bars: int = 2

    def __post_init__(self) -> None:
        """Validate the swing point.

        Raises:
            DomainInvariantError: If the timestamp is naive, the price is
                non-positive, or the bar counts are negative.
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.price, "price")
        if self.bars_since < 0:
            raise DomainInvariantError(f"bars_since must be >= 0, got {self.bars_since}")
        if self.confirmation_bars < 0:
            raise DomainInvariantError(
                f"confirmation_bars must be >= 0, got {self.confirmation_bars}"
            )

    @property
    def is_confirmed(self) -> bool:
        """Whether enough bars have elapsed for the fractal to be confirmed."""
        return self.bars_since >= self.confirmation_bars


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    """A price level expected to hold resting orders.

    Attributes:
        price: The level.
        kind: How the level was identified.
        score: Quality score, ``0..100``.
        touches: Number of times price has tested the level.
        timestamp: When the level was formed, if known.
    """

    price: float
    kind: LiquidityLevelKind
    score: float = 0.0
    touches: int = 0
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the level.

        Raises:
            DomainInvariantError: If the price is non-positive, the score falls
                outside ``0..100``, touches are negative, or a supplied
                timestamp is naive.
        """
        _require_positive(self.price, "price")
        score = _require_finite(self.score, "score")
        if not 0.0 <= score <= 100.0:
            raise DomainInvariantError(f"score must be within 0..100, got {score}")
        if self.touches < 0:
            raise DomainInvariantError(f"touches must be >= 0, got {self.touches}")
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")

    def distance_from(self, price: float) -> PriceDistance:
        """Absolute distance from ``price`` to this level.

        Args:
            price: Reference price.

        Returns:
            The distance, as a typed :class:`~core.units.PriceDistance` -- so it
            can never be compared against a bare "pips" threshold by accident.
        """
        return PriceDistance(abs(self.price - price))


@dataclass(frozen=True, slots=True)
class LiquiditySweep:
    """A wick through a liquidity level followed by a close back beyond it.

    Attributes:
        level: The level that was swept.
        side: Direction the sweep implies. A sweep of lows that closes back above
            them implies :attr:`Side.BUY`.
        wick_extreme: The furthest price reached beyond the level.
        close_price: Close of the sweeping bar.
        timestamp: Time of the sweeping bar. Must be timezone-aware.
        quality: Sweep quality score, ``0..10``.
    """

    level: LiquidityLevel
    side: Side
    wick_extreme: float
    close_price: float
    timestamp: datetime
    quality: float = 0.0

    def __post_init__(self) -> None:
        """Validate sweep geometry.

        Raises:
            DomainInvariantError: If prices are non-positive, quality is outside
                ``0..10``, the timestamp is naive, or the wick and close do not
                straddle the level in the direction the sweep claims.
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.wick_extreme, "wick_extreme")
        _require_positive(self.close_price, "close_price")
        quality = _require_finite(self.quality, "quality")
        if not 0.0 <= quality <= 10.0:
            raise DomainInvariantError(f"quality must be within 0..10, got {quality}")

        level_price = self.level.price
        if self.side is Side.BUY:
            if self.wick_extreme >= level_price:
                raise DomainInvariantError(
                    f"bullish sweep must wick BELOW the level: wick_extreme "
                    f"({self.wick_extreme}) >= level ({level_price})"
                )
            if self.close_price <= level_price:
                raise DomainInvariantError(
                    f"bullish sweep must close ABOVE the level: close "
                    f"({self.close_price}) <= level ({level_price})"
                )
        else:
            if self.wick_extreme <= level_price:
                raise DomainInvariantError(
                    f"bearish sweep must wick ABOVE the level: wick_extreme "
                    f"({self.wick_extreme}) <= level ({level_price})"
                )
            if self.close_price >= level_price:
                raise DomainInvariantError(
                    f"bearish sweep must close BELOW the level: close "
                    f"({self.close_price}) >= level ({level_price})"
                )

    @property
    def depth(self) -> PriceDistance:
        """How far the wick travelled beyond the level."""
        return PriceDistance(abs(self.wick_extreme - self.level.price))


@dataclass(frozen=True, slots=True)
class OrderBlock:
    """The last opposing candle body before a displacement move.

    Attributes:
        top: Upper bound of the zone.
        bottom: Lower bound of the zone.
        side: Direction the block is expected to support.
        timestamp: Time of the originating bar. Must be timezone-aware.
        is_mitigated: Whether price has already traded back into the zone.
        score: Quality score, ``0..100``.
    """

    top: float
    bottom: float
    side: Side
    timestamp: datetime
    is_mitigated: bool = False
    score: float = 0.0

    def __post_init__(self) -> None:
        """Validate zone geometry.

        Raises:
            DomainInvariantError: If bounds are non-positive, ``top < bottom``,
                the score is outside ``0..100``, or the timestamp is naive.
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.top, "top")
        _require_positive(self.bottom, "bottom")
        if self.top < self.bottom:
            raise DomainInvariantError(f"top ({self.top}) < bottom ({self.bottom})")
        score = _require_finite(self.score, "score")
        if not 0.0 <= score <= 100.0:
            raise DomainInvariantError(f"score must be within 0..100, got {score}")

    @property
    def height(self) -> PriceDistance:
        """Vertical size of the zone."""
        return PriceDistance(self.top - self.bottom)

    @property
    def midpoint(self) -> float:
        """Centre of the zone."""
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        """Whether ``price`` falls inside the zone, bounds inclusive.

        Args:
            price: Price to test.

        Returns:
            ``True`` if ``bottom <= price <= top``.
        """
        return self.bottom <= price <= self.top


@dataclass(frozen=True, slots=True)
class FairValueGap:
    """A three-bar price imbalance left unfilled by a displacement move.

    Attributes:
        top: Upper bound of the gap.
        bottom: Lower bound of the gap.
        kind: Direction of the imbalance.
        timestamp: Time of the middle (displacement) bar. Must be tz-aware.
        fill_fraction: Portion of the gap already retraced, ``0.0``-``1.0``.
    """

    top: float
    bottom: float
    kind: FairValueGapKind
    timestamp: datetime
    fill_fraction: float = 0.0

    def __post_init__(self) -> None:
        """Validate gap geometry.

        Raises:
            DomainInvariantError: If bounds are non-positive, ``top <= bottom``
                (a gap with no height is not a gap), ``fill_fraction`` is outside
                ``0..1``, or the timestamp is naive.
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.top, "top")
        _require_positive(self.bottom, "bottom")
        if self.top <= self.bottom:
            raise DomainInvariantError(
                f"a fair value gap must have height: top ({self.top}) "
                f"<= bottom ({self.bottom})"
            )
        fill = _require_finite(self.fill_fraction, "fill_fraction")
        if not 0.0 <= fill <= 1.0:
            raise DomainInvariantError(f"fill_fraction must be within 0..1, got {fill}")

    @property
    def height(self) -> PriceDistance:
        """Vertical size of the gap."""
        return PriceDistance(self.top - self.bottom)

    @property
    def midpoint(self) -> float:
        """Centre of the gap."""
        return (self.top + self.bottom) / 2.0

    @property
    def is_filled(self) -> bool:
        """Whether the gap has been fully retraced."""
        return self.fill_fraction >= 1.0


# ---------------------------------------------------------------------------
# Trade construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StopLoss:
    """A protective stop, validated against its entry and direction.

    This type exists to make an inverted trade unrepresentable. The current
    ``entry_engine.calculate_entry_levels`` computes ``risk_distance =
    abs(entry_price - stop_loss)`` with no side check, so a stop placed above
    entry on a BUY produces a positive risk distance and flows onward as a
    perfectly normal trade.

    Attributes:
        price: The stop price.
        entry_price: The entry the stop protects.
        side: Direction of the trade.
    """

    price: float
    entry_price: float
    side: Side

    def __post_init__(self) -> None:
        """Validate that the stop sits on the losing side of entry.

        Raises:
            DomainInvariantError: If either price is non-positive, or the stop is
                on the wrong side of, or exactly at, the entry price.
        """
        _require_positive(self.price, "price")
        _require_positive(self.entry_price, "entry_price")
        if self.side is Side.BUY and self.price >= self.entry_price:
            raise DomainInvariantError(
                f"BUY stop loss ({self.price}) must be BELOW entry "
                f"({self.entry_price}); a stop at or above entry is not a stop"
            )
        if self.side is Side.SELL and self.price <= self.entry_price:
            raise DomainInvariantError(
                f"SELL stop loss ({self.price}) must be ABOVE entry "
                f"({self.entry_price}); a stop at or below entry is not a stop"
            )

    @property
    def risk_distance(self) -> PriceDistance:
        """Distance from entry to stop -- the ``1R`` unit for this trade."""
        return PriceDistance(abs(self.entry_price - self.price))


@dataclass(frozen=True, slots=True)
class TakeProfit:
    """A profit target, validated against its entry and direction.

    Attributes:
        price: The target price.
        entry_price: The entry the target belongs to.
        side: Direction of the trade.
    """

    price: float
    entry_price: float
    side: Side

    def __post_init__(self) -> None:
        """Validate that the target sits on the profitable side of entry.

        Raises:
            DomainInvariantError: If either price is non-positive, or the target
                is on the wrong side of, or exactly at, the entry price.
        """
        _require_positive(self.price, "price")
        _require_positive(self.entry_price, "entry_price")
        if self.side is Side.BUY and self.price <= self.entry_price:
            raise DomainInvariantError(
                f"BUY take profit ({self.price}) must be ABOVE entry ({self.entry_price})"
            )
        if self.side is Side.SELL and self.price >= self.entry_price:
            raise DomainInvariantError(
                f"SELL take profit ({self.price}) must be BELOW entry ({self.entry_price})"
            )

    @property
    def reward_distance(self) -> PriceDistance:
        """Distance from entry to target."""
        return PriceDistance(abs(self.price - self.entry_price))


@dataclass(frozen=True, slots=True)
class RiskParameters:
    """Risk budget for a single trade.

    Attributes:
        risk_per_trade: Account percentage to risk. ``Percentage(1.0)`` is 1 %.
        max_concurrent_positions: Simultaneous position cap.
        max_daily_loss: Daily loss limit, as an account percentage.
        max_positions_per_day: Daily new-position cap. ``None`` means unlimited.
    """

    risk_per_trade: Percentage
    max_concurrent_positions: int = 1
    max_daily_loss: Percentage = field(default_factory=lambda: Percentage(5.0))
    max_positions_per_day: int | None = None

    def __post_init__(self) -> None:
        """Validate the risk budget.

        Raises:
            DomainInvariantError: If risk is non-positive or exceeds 100 %, or
                if any cap is non-positive.
        """
        if not isinstance(self.risk_per_trade, Percentage):
            raise DomainInvariantError(
                f"risk_per_trade must be a Percentage, got "
                f"{type(self.risk_per_trade).__name__}. A bare float is ambiguous "
                f"between 1% and 100%."
            )
        if self.risk_per_trade.value <= 0.0:
            raise DomainInvariantError(
                f"risk_per_trade must be > 0, got {self.risk_per_trade.value}%"
            )
        if self.risk_per_trade.value > 100.0:
            raise DomainInvariantError(
                f"risk_per_trade must be <= 100%, got {self.risk_per_trade.value}%"
            )
        if not isinstance(self.max_daily_loss, Percentage):
            raise DomainInvariantError("max_daily_loss must be a Percentage")
        if self.max_daily_loss.value <= 0.0:
            raise DomainInvariantError("max_daily_loss must be > 0")
        if self.max_concurrent_positions < 1:
            raise DomainInvariantError(
                f"max_concurrent_positions must be >= 1, got {self.max_concurrent_positions}"
            )
        if self.max_positions_per_day is not None and self.max_positions_per_day < 1:
            raise DomainInvariantError(
                f"max_positions_per_day must be >= 1 or None, got {self.max_positions_per_day}"
            )


@dataclass(frozen=True, slots=True)
class TradingSetup:
    """Structural evidence supporting a potential trade, before triggering.

    Groups what the analysis layers found so a :class:`Signal` can carry its
    justification rather than the loose ``analysis["layer_N"]`` dicts used today.

    Attributes:
        side: Direction the setup supports.
        timeframe: Timeframe the setup was identified on.
        timestamp: When the setup was assessed. Must be timezone-aware.
        swing_points: Supporting swing structure.
        liquidity_levels: Relevant liquidity levels.
        sweep: The confirming sweep, if any.
        order_block: The supporting order block, if any.
        fair_value_gap: The supporting imbalance, if any.
        notes: Free-form diagnostics. Explicitly *not* a place for values that
            drive decisions -- those belong in typed fields.
    """

    side: Side
    timeframe: Timeframe
    timestamp: datetime
    swing_points: tuple[SwingPoint, ...] = ()
    liquidity_levels: tuple[LiquidityLevel, ...] = ()
    sweep: LiquiditySweep | None = None
    order_block: OrderBlock | None = None
    fair_value_gap: FairValueGap | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate setup coherence.

        Raises:
            DomainInvariantError: If the timestamp is naive, or a contained
                sweep or order block points the opposite way to the setup.
        """
        _require_aware(self.timestamp, "timestamp")
        if self.sweep is not None and self.sweep.side is not self.side:
            raise DomainInvariantError(
                f"setup side ({self.side.value}) contradicts sweep side "
                f"({self.sweep.side.value})"
            )
        if self.order_block is not None and self.order_block.side is not self.side:
            raise DomainInvariantError(
                f"setup side ({self.side.value}) contradicts order block side "
                f"({self.order_block.side.value})"
            )


@dataclass(frozen=True, slots=True)
class Signal:
    """A fully specified trade intention, ready for risk sizing.

    A ``Signal`` cannot be constructed with an inverted stop, a target on the
    wrong side, or mismatched entry prices -- :class:`StopLoss` and
    :class:`TakeProfit` enforce their own geometry and this class checks that all
    three agree.

    Attributes:
        side: Trade direction.
        entry_price: Intended entry.
        stop_loss: Protective stop.
        take_profit: Profit target. Optional; a trade may be managed to exit.
        signal_type: Decision outcome this signal represents.
        timestamp: When the signal was produced. Must be timezone-aware.
        symbol: Instrument symbol.
        setup: Supporting structural evidence.
        confidence: Heuristic score, ``0..100``.

    Note:
        ``confidence`` is an **uncalibrated heuristic**, not a probability. It has
        never been validated against realised outcomes. Naming it here does not
        make it a probability; a calibrated probability engine is explicitly out
        of scope until a labelled trade dataset exists.
    """

    side: Side
    entry_price: float
    stop_loss: StopLoss
    take_profit: TakeProfit | None
    signal_type: SignalType
    timestamp: datetime
    symbol: str = ""
    setup: TradingSetup | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        """Validate that entry, stop and target are mutually consistent.

        Raises:
            DomainInvariantError: If the timestamp is naive, the entry price is
                non-positive, confidence is outside ``0..100``, or the stop /
                target disagree with the signal's own side or entry price.
        """
        _require_aware(self.timestamp, "timestamp")
        _require_positive(self.entry_price, "entry_price")
        confidence = _require_finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 100.0:
            raise DomainInvariantError(f"confidence must be within 0..100, got {confidence}")

        if self.stop_loss.side is not self.side:
            raise DomainInvariantError(
                f"signal side ({self.side.value}) != stop loss side "
                f"({self.stop_loss.side.value})"
            )
        if self.stop_loss.entry_price != self.entry_price:
            raise DomainInvariantError(
                f"stop loss entry_price ({self.stop_loss.entry_price}) != signal "
                f"entry_price ({self.entry_price})"
            )
        if self.take_profit is not None:
            if self.take_profit.side is not self.side:
                raise DomainInvariantError(
                    f"signal side ({self.side.value}) != take profit side "
                    f"({self.take_profit.side.value})"
                )
            if self.take_profit.entry_price != self.entry_price:
                raise DomainInvariantError(
                    f"take profit entry_price ({self.take_profit.entry_price}) != "
                    f"signal entry_price ({self.entry_price})"
                )
        if self.setup is not None and self.setup.side is not self.side:
            raise DomainInvariantError(
                f"signal side ({self.side.value}) != setup side ({self.setup.side.value})"
            )

    @property
    def risk_distance(self) -> PriceDistance:
        """The ``1R`` unit: distance from entry to stop."""
        return self.stop_loss.risk_distance

    @property
    def reward_risk_ratio(self) -> float | None:
        """Reward-to-risk ratio, or ``None`` when there is no target.

        Note:
            This is a genuine measurement of the two distances. The legacy
            ``entry_engine`` computes its ratio from a target *derived* as
            ``risk x tp_ratio``, making its "RR check" a tautology that only
            re-tests a configuration constant.
        """
        if self.take_profit is None:
            return None
        risk = self.risk_distance.value
        if risk <= 0.0:
            return None
        return self.take_profit.reward_distance.value / risk


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An order about to be submitted to a broker.

    Note:
        Constructing one of these does **not** submit anything. Live execution is
        disabled for Phase 0/1; see :mod:`core.safety`.

    Attributes:
        symbol: Instrument to trade.
        side: Trade direction.
        volume: Size in lots. Must be positive.
        kind: Market, limit or stop.
        entry_price: Required for limit/stop orders; ignored for market orders.
        stop_loss: Stop price to register with the broker.
        take_profit: Target price to register with the broker.
        max_slippage: Slippage tolerance, as a typed distance.
        comment: Broker order comment.
        client_order_id: Caller-side identifier for reconciliation.
    """

    symbol: str
    side: Side
    volume: float
    kind: OrderKind = OrderKind.MARKET
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    max_slippage: PriceDistance | None = None
    comment: str = ""
    client_order_id: str = ""

    def __post_init__(self) -> None:
        """Validate the request.

        Raises:
            DomainInvariantError: If the symbol is empty, the volume is
                non-positive, a non-market order has no entry price, or
                ``max_slippage`` is not a typed :class:`~core.units.PriceDistance`.
        """
        if not self.symbol:
            raise DomainInvariantError("symbol must be a non-empty string")
        _require_positive(self.volume, "volume")
        if self.kind is not OrderKind.MARKET and self.entry_price is None:
            raise DomainInvariantError(
                f"{self.kind.value} order requires an explicit entry_price"
            )
        if self.entry_price is not None:
            _require_positive(self.entry_price, "entry_price")
        if self.stop_loss is not None:
            _require_positive(self.stop_loss, "stop_loss")
        if self.take_profit is not None:
            _require_positive(self.take_profit, "take_profit")
        if self.max_slippage is not None and not isinstance(self.max_slippage, PriceDistance):
            raise DomainInvariantError(
                f"max_slippage must be a PriceDistance, got "
                f"{type(self.max_slippage).__name__}; a bare number is ambiguous "
                f"between price units and pips"
            )

    def validated_for(self, spec: SymbolSpecification) -> None:
        """Check the request against a broker specification.

        Args:
            spec: The broker specification for :attr:`symbol`.

        Raises:
            DomainInvariantError: If the symbol does not match, or the volume is
                outside the broker's permitted range or off its step grid.
        """
        if spec.symbol != self.symbol:
            raise DomainInvariantError(
                f"specification is for {spec.symbol}, request is for {self.symbol}"
            )
        if not spec.is_volume_tradeable(self.volume):
            raise DomainInvariantError(
                f"volume {self.volume} is not tradeable for {spec.symbol} "
                f"(min={spec.volume_min}, max={spec.volume_max}, step={spec.volume_step})"
            )


@dataclass(frozen=True, slots=True)
class OrderResult:
    """The broker's response to an :class:`OrderRequest`.

    Attributes:
        status: Outcome of the submission.
        request: The request this responds to.
        broker_order_id: Broker-assigned identifier, when one was issued.
        filled_volume: Volume actually filled, in lots.
        fill_price: Average fill price, when filled.
        timestamp: When the result was received. Must be timezone-aware.
        message: Broker message or error text.
        retcode: Raw broker return code, preserved for diagnosis.
    """

    status: OrderResultStatus
    request: OrderRequest
    broker_order_id: str | None = None
    filled_volume: float = 0.0
    fill_price: float | None = None
    timestamp: datetime | None = None
    message: str = ""
    retcode: int | None = None

    def __post_init__(self) -> None:
        """Validate the result.

        Raises:
            DomainInvariantError: If the filled volume is negative or exceeds the
                requested volume, a supplied timestamp is naive, or a filled
                result carries no fill price.
        """
        filled = _require_finite(self.filled_volume, "filled_volume")
        if filled < 0.0:
            raise DomainInvariantError(f"filled_volume must be >= 0, got {filled}")
        if filled > self.request.volume:
            raise DomainInvariantError(
                f"filled_volume ({filled}) exceeds requested volume "
                f"({self.request.volume})"
            )
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")
        if self.status is OrderResultStatus.FILLED:
            if self.fill_price is None:
                raise DomainInvariantError("a FILLED result must carry a fill_price")
            _require_positive(self.fill_price, "fill_price")

    @property
    def is_success(self) -> bool:
        """Whether any volume was filled."""
        return self.status in (OrderResultStatus.FILLED, OrderResultStatus.PARTIALLY_FILLED)

    def slippage_against(self, intended_price: float) -> PriceDistance | None:
        """Distance between ``intended_price`` and the actual fill.

        Args:
            intended_price: The price the signal expected to trade at.

        Returns:
            The absolute difference, or ``None`` if nothing was filled. Typed, so
            it cannot be compared against a "pips" threshold by accident.
        """
        if self.fill_price is None:
            return None
        return PriceDistance(abs(self.fill_price - intended_price))


@dataclass(frozen=True, slots=True)
class Position:
    """An open or historical position, as the broker sees it.

    Note:
        The broker is the authority on positions. This type is a snapshot to be
        reconciled against ``positions_get()``, never a substitute for it. The
        Phase 1 audit found local state diverging permanently from the broker,
        with two fabricated positions surviving every restart.

    Attributes:
        position_id: Broker ticket or local identifier.
        symbol: Instrument.
        side: Direction.
        volume: Current open volume in lots.
        entry_price: Average entry price.
        stop_loss: Current stop, if registered.
        take_profit: Current target, if registered.
        opened_at: Open time. Must be timezone-aware.
        status: Lifecycle state.
        realised_pnl: Realised profit/loss in account currency.
        broker_verified: Whether this snapshot was confirmed against the broker.
            Defaults to ``False`` -- unverified until proven otherwise.
    """

    position_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    opened_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
    status: PositionStatus = PositionStatus.OPEN
    realised_pnl: float = 0.0
    broker_verified: bool = False

    def __post_init__(self) -> None:
        """Validate the position snapshot.

        Raises:
            DomainInvariantError: If identifiers are empty, prices or volume are
                invalid, or ``opened_at`` is naive. An open position must have
                positive volume; a closed one must have zero.
        """
        if not self.position_id:
            raise DomainInvariantError("position_id must be a non-empty string")
        if not self.symbol:
            raise DomainInvariantError("symbol must be a non-empty string")
        _require_aware(self.opened_at, "opened_at")
        _require_positive(self.entry_price, "entry_price")

        volume = _require_finite(self.volume, "volume")
        if volume < 0.0:
            raise DomainInvariantError(f"volume must be >= 0, got {volume}")
        if self.status is PositionStatus.CLOSED and volume != 0.0:
            raise DomainInvariantError(
                f"a CLOSED position must have zero volume, got {volume}"
            )
        if self.status in (PositionStatus.OPEN, PositionStatus.PARTIALLY_CLOSED) and volume <= 0.0:
            raise DomainInvariantError(
                f"an {self.status.value} position must have volume > 0, got {volume}"
            )

        if self.stop_loss is not None:
            _require_positive(self.stop_loss, "stop_loss")
        if self.take_profit is not None:
            _require_positive(self.take_profit, "take_profit")

    @property
    def is_protected(self) -> bool:
        """Whether a stop is registered with the broker.

        An unprotected open position carries unbounded loss if the process dies.
        """
        return self.stop_loss is not None

    def unrealised_price_move(self, current_price: float) -> PriceDistance:
        """Signed favourable move from entry to ``current_price``.

        Args:
            current_price: Current market price for the position's side.

        Returns:
            A :class:`~core.units.PriceDistance`; positive when in profit,
            negative when in loss, for either direction.
        """
        return PriceDistance((current_price - self.entry_price) * self.side.sign)


def bar_from_mapping(row: Any, timeframe: Timeframe | None = None) -> MarketBar:
    """Build a :class:`MarketBar` from a mapping or pandas Series.

    Bridges the existing pandas pipeline to the typed domain without requiring
    the strategy engines to be rewritten. Accepts either ``volume`` or the MT5
    ``tick_volume`` column name.

    Args:
        row: Mapping-like object exposing ``time``/``timestamp``, ``open``,
            ``high``, ``low``, ``close`` and optionally ``volume``/``tick_volume``.
        timeframe: Timeframe to tag the bar with, if known.

    Returns:
        A validated :class:`MarketBar`.

    Raises:
        DomainInvariantError: If a required field is missing, the timestamp is
            naive, or the OHLC values are inconsistent.
    """
    def _pick(*names: str) -> Any:
        for name in names:
            try:
                value = row[name]
            except (KeyError, IndexError, TypeError):
                continue
            if value is not None:
                return value
        return None

    timestamp = _pick("time", "timestamp")
    if timestamp is None:
        raise DomainInvariantError("row has no 'time' or 'timestamp' field")
    if not isinstance(timestamp, datetime):
        timestamp = getattr(timestamp, "to_pydatetime", lambda: timestamp)()
    if not isinstance(timestamp, datetime):
        raise DomainInvariantError(
            f"timestamp must be a datetime, got {type(timestamp).__name__}"
        )

    missing = [name for name in ("open", "high", "low", "close") if _pick(name) is None]
    if missing:
        raise DomainInvariantError(f"row is missing OHLC field(s): {', '.join(missing)}")

    raw_volume = _pick("volume", "tick_volume")
    return MarketBar(
        timestamp=timestamp,
        open=float(_pick("open")),
        high=float(_pick("high")),
        low=float(_pick("low")),
        close=float(_pick("close")),
        volume=float(raw_volume) if raw_volume is not None else 0.0,
        timeframe=timeframe,
    )
