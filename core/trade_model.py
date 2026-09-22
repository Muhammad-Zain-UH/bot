"""Canonical trade-management domain model.

Source of truth: ``docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md``. Section
references in this module point there. The contract this satisfies is
``tests/trade_management/test_canonical_trade_management_contract.py``.

What this module is
-------------------
The one canonical state machine for a position's life between entry and
closure. It decides *what should happen*; it never makes it happen. It holds no
broker, no adapter, no clock, no file handle and no cost model, so the same code
drives live, paper and replay execution and can be compared across them
(spec 18).

Two boundaries are load-bearing, and both were clarified after the contract
tests were written:

**Closure is confirmed, never assumed** (spec 11.1a). Detecting that a stop or
target has been reached is not a closure. :func:`evaluate` emits a
``CLOSE_REQUESTED`` event and records :attr:`TradeState.pending_close_reason`;
the position stays ``OPEN``, holding its full remaining quantity, until
:func:`apply_broker_result` receives a confirming :class:`CloseFilled`. Nothing
else may set ``CLOSED``.

**The domain does not price executions** (spec 11.1b). A close request carries
``requested_level`` and ``observed_reference`` and nothing more. The execution
adapter turns the reference into an executable price using its cost model, and
the broker reports the fill that is actually obtained. Spread, slippage and
commission do not appear in this module.

Design notes
------------
Quantity is an integer number of broker volume steps, never a float in lots
(spec 5.1): halving, comparing and decrementing lots as floats invites
representation error exactly at the boundary where a broker rejects an order.
Lots are derived only at that boundary, by :func:`steps_to_lots`.

Every level -- 1R, 2R and the target -- is computed once, at creation, from the
frozen entry price and R, and stored (spec 6.1). Nothing recomputes a level, so
a moved stop cannot drift the geometry.

:func:`evaluate` is a pure function of ``(state, observation)``. It mutates
nothing, reads no clock and performs no I/O, which is what makes replay
deterministic (spec 15.2).

Unresolved questions are refused, not guessed
---------------------------------------------
Where the specification records an open question, this module declines to
invent an answer:

* **U5 / R8** -- the observed reference carried by a *re-requested* close. When
  a close is rejected and re-issued on a later observation, that observation is
  a different bar, and the specification does not say whether the retry carries
  the original reference or the new one. The retry therefore carries
  ``observed_reference=None``, meaning *undetermined*. An adapter must not
  substitute a price of its own choosing.
* **U6 / R9** -- whether an unconfirmed stop promotion blocks the next
  milestone. If a promotion is still outstanding from an earlier observation
  and a further milestone becomes reachable, this module raises
  :class:`UnresolvedCanonicalDecisionError` rather than picking a behaviour.
  Promotions made *within* a single evaluation are not affected: those are
  ordinary ascending processing (spec 6.4).

R1-R4 are likewise unimplemented: there is no reversal protection, no
time-based exit, no continuous trailing and no opposing-position policy beyond
the restriction in :func:`may_open_position`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Iterable

from core.types import DomainInvariantError, Side
from core.units import COMPARISON_TOLERANCE

__all__ = [
    "UnresolvedCanonicalDecisionError",
    "StopState",
    "PositionLifecycle",
    "ClosureReason",
    "Milestone",
    "EventType",
    "PartialCloseRequest",
    "StopModifyRequest",
    "CloseRequest",
    "PriceObservation",
    "TradeState",
    "EvaluationResult",
    "PartialCloseFilled",
    "PartialCloseRejected",
    "StopModifyConfirmed",
    "StopModifyRejected",
    "CloseFilled",
    "CloseRejected",
    "QuantityReconciled",
    "PositionGone",
    "open_position",
    "evaluate",
    "apply_broker_result",
    "steps_to_lots",
    "lots_to_steps",
    "may_open_position",
]


class UnresolvedCanonicalDecisionError(DomainInvariantError):
    """Raised where the specification records an open question.

    Refusing is deliberate. An implementation that quietly picked a behaviour
    would make the open question invisible and would be relied upon before it
    was decided. See the module docstring for the items concerned.
    """


# ---------------------------------------------------------------------------
# Enumerations -- names are fixed by spec 22 and asserted by the contract
# ---------------------------------------------------------------------------


class StopState(Enum):
    """Where the stop sits (spec 7.1).

    Forward only: ``ORIGINAL`` -> ``BREAKEVEN`` -> ``LOCKED_1R``. Tracked twice
    on a position, as intended and as confirmed, because only the broker's
    acknowledgement protects anything (spec 7.3).
    """

    ORIGINAL = "ORIGINAL"
    BREAKEVEN = "BREAKEVEN"
    LOCKED_1R = "LOCKED_1R"


class PositionLifecycle(Enum):
    """Whether the position exists (spec 8.2).

    ``OPEN`` includes a position whose closure has been requested but not yet
    confirmed: the request is visible in
    :attr:`TradeState.pending_close_reason`, and the risk is still real.
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClosureReason(Enum):
    """Why a position closed (spec 8.3). Exactly one is recorded."""

    STOP = "STOP"
    TARGET = "TARGET"
    EXTERNAL = "EXTERNAL"
    END_OF_DATA = "END_OF_DATA"
    MANUAL = "MANUAL"


class Milestone(Enum):
    """A price level that fires at most once per position (spec 6)."""

    M1R = "M1R"
    M2R = "M2R"
    TARGET = "TARGET"


class EventType(Enum):
    """What the domain asks the execution layer to do (spec 11.1).

    These are requests, not outcomes. Nothing here has happened yet.
    """

    PARTIAL_CLOSE_REQUESTED = "PARTIAL_CLOSE_REQUESTED"
    STOP_MODIFY_REQUESTED = "STOP_MODIFY_REQUESTED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"


# ---------------------------------------------------------------------------
# Events emitted by evaluate()
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartialCloseRequest:
    """Close ``steps`` of the position, leaving the remainder open.

    Attributes:
        steps: How many volume steps to close. Never more than half the
            original size, and never zero -- a zero-step partial is not
            requested at all (spec 5.2).
    """

    steps: int
    type: EventType = EventType.PARTIAL_CLOSE_REQUESTED


@dataclass(frozen=True, slots=True)
class StopModifyRequest:
    """Move the stop to ``stop_price``.

    Attributes:
        stop_price: The new stop price.
        to_state: The stop state this price represents.
    """

    stop_price: float
    to_state: StopState
    type: EventType = EventType.STOP_MODIFY_REQUESTED


@dataclass(frozen=True, slots=True)
class CloseRequest:
    """Close the whole remaining position.

    Carries the two prices the domain is entitled to know and no others
    (spec 11.1b). The executable price is the adapter's to compute and the
    fill is the broker's to report.

    Attributes:
        reason: Why closure was requested.
        requested_level: The price the model asked for -- the stop, or the
            target.
        observed_reference: The first price available at or beyond that level:
            the level itself, or the bar open where the bar gapped through it.
            ``None`` on a re-issued request, where the specification has not
            decided which reference applies (U5 / R8).
        steps: The whole remaining quantity.
    """

    reason: ClosureReason
    requested_level: float
    observed_reference: float | None
    steps: int
    type: EventType = EventType.CLOSE_REQUESTED


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One price observation: a bar in replay, a sample in live execution.

    Invalid ranges are rejected at construction rather than producing a
    plausible-looking evaluation (CONVENTIONS section 6).

    Attributes:
        time: When the observation begins. Aware UTC by convention; supplied,
            never read from a clock.
        open: Opening price. The gap reference (spec 12).
        high: Highest price reached.
        low: Lowest price reached.
        close: Closing price. The model never uses it to decide whether a level
            was reached -- the range does that (spec 6.2).
    """

    time: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise DomainInvariantError(
                f"high {self.high} is below low {self.low}"
            )
        if not (self.low <= self.open <= self.high):
            raise DomainInvariantError(
                f"open {self.open} is outside the range "
                f"[{self.low}, {self.high}]"
            )
        if not (self.low <= self.close <= self.high):
            raise DomainInvariantError(
                f"close {self.close} is outside the range "
                f"[{self.low}, {self.high}]"
            )

    @classmethod
    def from_price(cls, time: datetime, price: float) -> PriceObservation:
        """A single price with no range, for tick or sample driven execution."""
        return cls(time=time, open=price, high=price, low=price, close=price)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeState:
    """Everything the model knows about one position.

    Immutable. :func:`evaluate` and :func:`apply_broker_result` return a new
    instance rather than mutating this one, so a state can be held, compared or
    replayed without surprise (spec 15.2).

    Geometry -- ``entry_price`` through ``tp_ratio`` -- is frozen at creation
    and never recomputed.

    Attributes:
        side: Trade direction.
        entry_price: The price actually filled at, after costs. Not the price
            the strategy intended (spec 4.1).
        original_stop_price: The structural stop, unchanged by the fill.
        r: ``abs(entry_price - original_stop_price)``, frozen for the life of
            the position.
        m1r: The 1R level.
        m2r: The 2R level.
        target: The final target, ``entry +/- tp_ratio * r``.
        tp_ratio: The regime-selected target multiple.
        steps_at_entry: Original size in broker volume steps. The denominator
            of the 50 % rule.
        steps_remaining: Current size in steps.
        opened_at: When the position came into existence. Observations before
            this are not its concern.
        milestones_consumed: Which milestones have fired. Each fires once.
        stop_state_intended: What the model has decided the stop should be.
        stop_state_confirmed: What the broker has acknowledged. Risk statements
            use this one (spec 7.3).
        confirmed_stop_price: The price behind ``stop_state_confirmed``.
        lifecycle: ``OPEN`` or ``CLOSED``.
        closure_reason: Set only once closure is confirmed.
        closure_fill_price: The recorded fill, as reported by the broker.
        pending_close_reason: Set while a close has been requested and not yet
            confirmed. Blocks milestone processing (spec 11.1a).
        pending_close_level: The requested level of that outstanding close.
        stop_modify_was_rejected: True once the broker has refused a stop
            move that is still outstanding, cleared when one is confirmed.
            Distinguishes "the broker said no" from "the broker has not
            answered yet", which the intended/confirmed pair alone cannot. Only
            the first of those is the undecided case U6 / R9.
        last_evaluated_time: Guards against repeated or out-of-order
            observations.
        anomalies: Divergences between what the model expected and what the
            broker reported. Recorded, never silently reconciled (spec 16.2).
            Severity is deliberately not graded: that is R4.
    """

    side: Side
    entry_price: float
    original_stop_price: float
    r: float
    m1r: float
    m2r: float
    target: float
    tp_ratio: float
    steps_at_entry: int
    steps_remaining: int
    opened_at: datetime
    milestones_consumed: frozenset[Milestone] = frozenset()
    stop_state_intended: StopState = StopState.ORIGINAL
    stop_state_confirmed: StopState = StopState.ORIGINAL
    confirmed_stop_price: float = 0.0
    lifecycle: PositionLifecycle = PositionLifecycle.OPEN
    closure_reason: ClosureReason | None = None
    closure_fill_price: float | None = None
    pending_close_reason: ClosureReason | None = None
    pending_close_level: float | None = None
    stop_modify_was_rejected: bool = False
    last_evaluated_time: datetime | None = None
    anomalies: tuple[str, ...] = ()

    @property
    def effective_stop_price(self) -> float:
        """The stop that is actually protecting the position.

        The confirmed one. An intended promotion the broker has not
        acknowledged protects nothing (spec 7.3).
        """
        return self.confirmed_stop_price

    @property
    def is_open(self) -> bool:
        """True while the position exists, including with a close outstanding."""
        return self.lifecycle is PositionLifecycle.OPEN

    @property
    def is_closed(self) -> bool:
        """True only once the broker has confirmed closure."""
        return self.lifecycle is PositionLifecycle.CLOSED


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """What one observation produced.

    Attributes:
        state: The new state. The input state is untouched.
        events: Requests for the execution layer, in the order they were
            decided.
        ambiguous: True when the observation reached both the stop and an
            unconsumed favourable level, so the true sequence within it is
            unknowable and the adverse-first policy decided the outcome
            (spec 11.4). Recorded so the proportion stays measurable.
    """

    state: TradeState
    events: tuple[object, ...]
    ambiguous: bool


# ---------------------------------------------------------------------------
# Broker results -- the only things that may change confirmed facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartialCloseFilled:
    """The broker closed ``steps_closed`` steps. May be fewer than asked."""

    steps_closed: int


@dataclass(frozen=True, slots=True)
class PartialCloseRejected:
    """The broker refused the partial. The quantity is unchanged."""

    reason: str


@dataclass(frozen=True, slots=True)
class StopModifyConfirmed:
    """The broker moved the stop and is now protecting it at this price."""

    stop_price: float
    to_state: StopState


@dataclass(frozen=True, slots=True)
class StopModifyRejected:
    """The broker refused the move. The old stop is still the effective one."""

    reason: str


@dataclass(frozen=True, slots=True)
class CloseFilled:
    """The broker closed the position. The only thing that produces ``CLOSED``."""

    reason: ClosureReason
    fill_price: float
    steps_closed: int


@dataclass(frozen=True, slots=True)
class CloseRejected:
    """The broker refused the close. The position is still open and at risk."""

    reason: str


@dataclass(frozen=True, slots=True)
class QuantityReconciled:
    """The broker reports a different remaining quantity. The broker wins."""

    steps_remaining: int


@dataclass(frozen=True, slots=True)
class PositionGone:
    """The broker no longer has the position, for a cause the model did not start."""


# ---------------------------------------------------------------------------
# Quantity boundary
# ---------------------------------------------------------------------------


def steps_to_lots(steps: int, volume_step: float) -> float:
    """Convert steps to lots for the broker boundary.

    Args:
        steps: Quantity in volume steps.
        volume_step: The broker's volume increment.

    Returns:
        The equivalent size in lots.
    """
    return round(steps * volume_step, 8)


def lots_to_steps(lots: float, volume_step: float) -> int:
    """Convert lots to steps, rounding **down**.

    Rounding a size up would take more risk than was authorised
    (CONVENTIONS section 9).

    Args:
        lots: Size in lots.
        volume_step: The broker's volume increment.

    Returns:
        The largest whole number of steps that fits within ``lots``.
    """
    if volume_step <= 0.0:
        raise DomainInvariantError(f"volume_step must be positive, got {volume_step}")
    return int((lots + COMPARISON_TOLERANCE) // volume_step)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def open_position(
    *,
    side: Side,
    fill_price: float,
    original_stop_price: float,
    tp_ratio: float,
    steps: int,
    opened_at: datetime,
) -> TradeState:
    """Create a position, freezing its geometry (spec 4, 6.1).

    R and all three levels are computed here and never again. ``fill_price`` is
    the price actually obtained, so a gapped or cost-adjusted fill defines the
    geometry of the position that actually exists.

    Args:
        side: Trade direction.
        fill_price: The price actually filled at, after costs.
        original_stop_price: The structural stop from the strategy.
        tp_ratio: The regime-selected target multiple.
        steps: Size in broker volume steps.
        opened_at: When the position came into existence.

    Returns:
        A fresh :class:`TradeState` with the stop confirmed at the original.

    Raises:
        DomainInvariantError: If the size or ratio is not positive, or if the
            fill destroyed the geometry -- zero R, or a stop on the wrong side
            of the entry. Such a fill is rejected, never clamped (spec 4.3).
    """
    if steps <= 0:
        raise DomainInvariantError(f"steps must be positive, got {steps}")
    if tp_ratio <= 0.0:
        raise DomainInvariantError(f"tp_ratio must be positive, got {tp_ratio}")

    r = abs(fill_price - original_stop_price)
    if r <= COMPARISON_TOLERANCE:
        raise DomainInvariantError(
            f"R is zero: the stop {original_stop_price} coincides with the fill "
            f"{fill_price}"
        )
    if side is Side.BUY and original_stop_price >= fill_price:
        raise DomainInvariantError(
            f"a BUY stop must sit below the fill: stop {original_stop_price}, "
            f"fill {fill_price}"
        )
    if side is Side.SELL and original_stop_price <= fill_price:
        raise DomainInvariantError(
            f"a SELL stop must sit above the fill: stop {original_stop_price}, "
            f"fill {fill_price}"
        )

    sign = side.sign
    return TradeState(
        side=side,
        entry_price=fill_price,
        original_stop_price=original_stop_price,
        r=r,
        m1r=fill_price + sign * r,
        m2r=fill_price + sign * 2.0 * r,
        target=fill_price + sign * tp_ratio * r,
        tp_ratio=tp_ratio,
        steps_at_entry=steps,
        steps_remaining=steps,
        opened_at=opened_at,
        confirmed_stop_price=original_stop_price,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _stop_price_for(state: TradeState, stop_state: StopState) -> float:
    """The price a stop state represents for this position."""
    if stop_state is StopState.ORIGINAL:
        return state.original_stop_price
    if stop_state is StopState.BREAKEVEN:
        return state.entry_price
    return state.entry_price + state.side.sign * state.r


def _reached(state: TradeState, observation: PriceObservation, level: float) -> bool:
    """Whether a favourable level was reached within the observation's range."""
    if state.side is Side.BUY:
        return observation.high >= level
    return observation.low <= level


def _stop_reached(state: TradeState, observation: PriceObservation, stop: float) -> bool:
    """Whether the observation's adverse extreme reached the stop."""
    if state.side is Side.BUY:
        return observation.low <= stop
    return observation.high >= stop


def _gapped_through(state: TradeState, bar_open: float, level: float, *, adverse: bool) -> bool:
    """Whether the observation opened already beyond ``level``."""
    if adverse:
        return bar_open < level if state.side is Side.BUY else bar_open > level
    return bar_open > level if state.side is Side.BUY else bar_open < level


_STOP_ORDER = {
    StopState.ORIGINAL: 0,
    StopState.BREAKEVEN: 1,
    StopState.LOCKED_1R: 2,
}

_LADDER = (
    (Milestone.M1R, StopState.BREAKEVEN),
    (Milestone.M2R, StopState.LOCKED_1R),
)


def _level_of(state: TradeState, milestone: Milestone) -> float:
    if milestone is Milestone.M1R:
        return state.m1r
    if milestone is Milestone.M2R:
        return state.m2r
    return state.target


def evaluate(state: TradeState, observation: PriceObservation) -> EvaluationResult:
    """Advance one position against one observation.

    A pure function: nothing is mutated, no clock is read, no I/O occurs. The
    order is fixed by spec 11.1 -- the effective stop is snapshotted first, the
    adverse case is resolved before any favourable one, and milestones are
    processed in ascending distance from entry.

    A stop moved during this call does **not** apply to this observation
    (spec 11.2): within the bar the range is already history, and testing a
    moved stop against it would assert an order of events the data cannot
    support.

    Args:
        state: The position's current state.
        observation: The price observation to apply.

    Returns:
        An :class:`EvaluationResult` holding the new state, the requests for
        the execution layer, and whether the observation was ambiguous.

    Raises:
        UnresolvedCanonicalDecisionError: If a milestone becomes reachable
            while a stop promotion from an earlier observation is still
            unconfirmed. That case is U6 / R9 and has no decided behaviour.
    """
    # 0. Preconditions: a closed position, an observation from before the
    #    position existed, and a repeated or stale observation are all no-ops.
    if state.is_closed:
        return EvaluationResult(state=state, events=(), ambiguous=False)
    if observation.time < state.opened_at:
        return EvaluationResult(state=state, events=(), ambiguous=False)
    if (
        state.last_evaluated_time is not None
        and observation.time <= state.last_evaluated_time
    ):
        return EvaluationResult(state=state, events=(), ambiguous=False)

    advanced = replace(state, last_evaluated_time=observation.time)

    # A close is outstanding: re-issue it and process nothing else
    # (spec 11.1a point 3 and 4).
    if state.pending_close_reason is not None:
        level = state.pending_close_level
        if level is None:  # pragma: no cover - defended, not reachable
            raise DomainInvariantError(
                "a pending close must carry the level it was requested at"
            )
        retry = CloseRequest(
            reason=state.pending_close_reason,
            requested_level=level,
            # U5 / R8: which reference a re-issued close carries is undecided.
            observed_reference=None,
            steps=state.steps_remaining,
        )
        return EvaluationResult(state=advanced, events=(retry,), ambiguous=False)

    # 1. Snapshot the effective stop: the one confirmed before this call.
    stop = state.effective_stop_price
    adverse = _stop_reached(state, observation, stop)

    unconsumed = tuple(
        milestone
        for milestone in (Milestone.M1R, Milestone.M2R, Milestone.TARGET)
        if milestone not in state.milestones_consumed
    )
    reachable = tuple(
        milestone
        for milestone in unconsumed
        if _reached(state, observation, _level_of(state, milestone))
    )
    ambiguous = adverse and bool(reachable)

    # 2. Adverse first (spec 11.2). The stop outranks every favourable event in
    #    the same observation, because the sequence within it is unknowable.
    if adverse:
        gapped = _gapped_through(state, observation.open, stop, adverse=True)
        request = CloseRequest(
            reason=ClosureReason.STOP,
            requested_level=stop,
            observed_reference=observation.open if gapped else stop,
            steps=state.steps_remaining,
        )
        return EvaluationResult(
            state=replace(
                advanced,
                pending_close_reason=ClosureReason.STOP,
                pending_close_level=stop,
            ),
            events=(request,),
            ambiguous=ambiguous,
        )

    # U6 / R9: the broker REFUSED a promotion and a further milestone is now
    # reachable. Whether the ladder continues or waits is not decided, so this
    # refuses rather than choosing.
    #
    # A promotion merely in flight -- requested, not yet answered -- is not this
    # case. Spec 7.3 already governs it: the position counts as protected at the
    # confirmed level and the move is re-attempted each evaluation. Stalling the
    # ladder on ordinary latency would be a behaviour nothing asks for, so the
    # two situations are distinguished by ``stop_modify_was_rejected`` rather
    # than by the intended/confirmed difference, which cannot tell them apart.
    if state.stop_modify_was_rejected and reachable:
        raise UnresolvedCanonicalDecisionError(
            f"{reachable[0].value} became reachable after the broker refused "
            f"the promotion to {state.stop_state_intended.value} (the stop is "
            f"still {state.stop_state_confirmed.value}). Whether an unconfirmed "
            "stop promotion blocks the next milestone is UNRESOLVED (U6 / R9); "
            "see docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md section 24."
        )

    # 3. Favourable milestones, ascending, each at most once.
    events: list[object] = []
    consumed = set(state.milestones_consumed)
    intended = state.stop_state_intended
    promoted_here = False

    for milestone, next_stop in _LADDER:
        if milestone in consumed:
            continue
        if not _reached(state, observation, _level_of(state, milestone)):
            continue
        consumed.add(milestone)
        if milestone is Milestone.M1R:
            # Floor, so "close 50 %" never closes more than half. At the
            # minimum size this is zero steps and no order is sent -- but the
            # milestone is still consumed and the stop still moves, because the
            # two effects are independent (spec 5.2, 5.4).
            steps_to_close = state.steps_at_entry // 2
            if steps_to_close > 0:
                events.append(PartialCloseRequest(steps=steps_to_close))
        intended = next_stop
        events.append(
            StopModifyRequest(
                stop_price=_stop_price_for(state, next_stop), to_state=next_stop
            )
        )
        promoted_here = True

    advanced = replace(
        advanced,
        milestones_consumed=frozenset(consumed),
        stop_state_intended=intended,
    )

    if Milestone.TARGET not in consumed and _reached(state, observation, state.target):
        consumed.add(Milestone.TARGET)
        gapped = _gapped_through(state, observation.open, state.target, adverse=False)
        events.append(
            CloseRequest(
                reason=ClosureReason.TARGET,
                requested_level=state.target,
                observed_reference=observation.open if gapped else state.target,
                steps=state.steps_remaining,
            )
        )
        return EvaluationResult(
            state=replace(
                advanced,
                milestones_consumed=frozenset(consumed),
                pending_close_reason=ClosureReason.TARGET,
                pending_close_level=state.target,
            ),
            events=tuple(events),
            ambiguous=ambiguous,
        )

    # 4. Reconcile an outstanding promotion, idempotently: the same target
    #    price, re-issued, until the broker acknowledges it (spec 7.3).
    if not promoted_here and intended is not state.stop_state_confirmed:
        events.append(
            StopModifyRequest(
                stop_price=_stop_price_for(state, intended), to_state=intended
            )
        )

    return EvaluationResult(state=advanced, events=tuple(events), ambiguous=ambiguous)


# ---------------------------------------------------------------------------
# Broker results
# ---------------------------------------------------------------------------


def _assert_forward_stop(state: TradeState, result: StopModifyConfirmed) -> None:
    """Reject a backward or adverse stop move (spec 7.2)."""
    if _STOP_ORDER[result.to_state] < _STOP_ORDER[state.stop_state_confirmed]:
        raise DomainInvariantError(
            f"the stop state may not move backwards: "
            f"{state.stop_state_confirmed.value} -> {result.to_state.value}"
        )
    if state.side is Side.BUY:
        improved = result.stop_price >= state.confirmed_stop_price - COMPARISON_TOLERANCE
    else:
        improved = result.stop_price <= state.confirmed_stop_price + COMPARISON_TOLERANCE
    if not improved:
        raise DomainInvariantError(
            f"the stop may not move adversely: {state.confirmed_stop_price} -> "
            f"{result.stop_price} on a {state.side.value}"
        )


def apply_broker_result(state: TradeState, result: object) -> TradeState:
    """Fold a broker result into the canonical state (spec 16).

    This is the only way a confirmed fact changes. Nothing here is optimistic:
    quantity and protection are statements about the world, and the broker is
    the authority on the world.

    Args:
        state: The position's current state.
        result: One of the broker result types in this module.

    Returns:
        The new state.

    Raises:
        DomainInvariantError: If the position is already closed, or if a stop
            confirmation would move the stop backwards or adversely.
        TypeError: If ``result`` is not a broker result type.
    """
    if state.is_closed:
        raise DomainInvariantError(
            "a closed position accepts no further broker results"
        )

    if isinstance(result, PartialCloseFilled):
        if result.steps_closed < 0:
            raise DomainInvariantError("steps_closed cannot be negative")
        if result.steps_closed > state.steps_remaining:
            raise DomainInvariantError(
                f"the broker closed {result.steps_closed} steps but only "
                f"{state.steps_remaining} were open"
            )
        return replace(state, steps_remaining=state.steps_remaining - result.steps_closed)

    if isinstance(result, PartialCloseRejected):
        # The milestone stays consumed and the stop still moves: the two
        # effects of the 1R event are independent (spec 5.4).
        return replace(
            state,
            anomalies=state.anomalies + (f"partial close rejected: {result.reason}",),
        )

    if isinstance(result, StopModifyConfirmed):
        _assert_forward_stop(state, result)
        return replace(
            state,
            stop_state_confirmed=result.to_state,
            confirmed_stop_price=result.stop_price,
            stop_modify_was_rejected=False,
        )

    if isinstance(result, StopModifyRejected):
        # The confirmed state does not advance. The position is protected at
        # the old stop until the broker says otherwise.
        return replace(
            state,
            stop_modify_was_rejected=True,
            anomalies=state.anomalies + (f"stop modify rejected: {result.reason}",),
        )

    if isinstance(result, CloseFilled):
        return replace(
            state,
            lifecycle=PositionLifecycle.CLOSED,
            closure_reason=result.reason,
            closure_fill_price=result.fill_price,
            steps_remaining=0,
            pending_close_reason=None,
            pending_close_level=None,
        )

    if isinstance(result, CloseRejected):
        # Still open, still at risk, request intact for re-issue.
        return replace(
            state,
            anomalies=state.anomalies + (f"close rejected: {result.reason}",),
        )

    if isinstance(result, QuantityReconciled):
        if result.steps_remaining < 0:
            raise DomainInvariantError("steps_remaining cannot be negative")
        return replace(
            state,
            steps_remaining=result.steps_remaining,
            anomalies=state.anomalies
            + (
                f"quantity reconciled from the broker: {state.steps_remaining} "
                f"-> {result.steps_remaining} steps",
            ),
        )

    if isinstance(result, PositionGone):
        return replace(
            state,
            lifecycle=PositionLifecycle.CLOSED,
            closure_reason=ClosureReason.EXTERNAL,
            steps_remaining=0,
            pending_close_reason=None,
            pending_close_level=None,
            anomalies=state.anomalies + ("the broker no longer has this position",),
        )

    raise TypeError(f"not a broker result: {result!r}")


# ---------------------------------------------------------------------------
# Portfolio-level guard
# ---------------------------------------------------------------------------


def may_open_position(open_states: Iterable[TradeState], side: Side) -> bool:
    """Whether a position may be opened on ``side``.

    An opposing position is refused while one is open. On a netting account the
    broker would merge the two, silently invalidating both positions' R, stop
    state and milestone flags; on a hedging account they would coexist. Which
    applies is R2, and is not decided, so the restriction stands (spec 14.1).

    Args:
        open_states: The positions currently held.
        side: The direction being considered.

    Returns:
        False if any open position is on the opposite side, True otherwise.
    """
    return not any(
        state.is_open and state.side is not side for state in open_states
    )
