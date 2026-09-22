"""Canonical trade identity and fill recording.

Phase 2 of ``docs/PHASE_4B_CANONICAL_INTEGRATION_IMPLEMENTATION_PLAN.md``. This
module supplies the identity and duplicate-detection infrastructure that the
future trade adapter will need. **It wires nothing**: no broker, no ledger and
no production path uses it yet.

The five identities, kept apart
-------------------------------
Specification §16.3 requires five identities that must never collapse into one.
This module owns the two the system mints for itself and the key under which an
execution is recorded; the other two come from the broker and are carried
through untouched:

==========================  ====================================  ============
Identity                    Names                                 Minted by
==========================  ====================================  ============
canonical ``position_id``   One position, entry to final close    here
``operation_id``            One instruction, stable over retries  here
``broker_order_id``         The broker's order                    broker
``broker_deal_id``          One execution against the position    broker
``fill_id``                 The key one execution is recorded at  here
==========================  ====================================  ============

Why identity is a correctness mechanism, not bookkeeping
--------------------------------------------------------
Spec §16.3: a broker may deliver the same execution twice -- on a retry, a
reconnection or a restart -- and a redelivery must not reduce quantity twice,
advance milestone state twice, change closure state twice, or create a second
economic effect. Distinguishing *one execution delivered twice* from *two
executions of one request* is only possible with an identity that separates
them, which is why :class:`FillIdentity` refuses to exist without one.

Determinism and its scope
-------------------------
Position identity is ``{symbol}-{entry_bar_time}-{side}-{sequence:04d}``, as
settled in the identity investigation. Uniqueness inside a run is guaranteed by
``sequence`` alone; the other three components make the id readable and make a
diff between two runs legible.

**The scope this holds over is a fixed replay scope.** Two runs over the same
data from the same starting point mint identical ids, because every input is
deterministic and the mint order is deterministic. A run that starts elsewhere,
or with different warmup, shifts the sequence and therefore the ids: they are
reproducible, not globally unique across differently-scoped runs. Nothing here
depends on a wall clock, a random source or a broker-assigned value.

Live restart sequencing -- a counter that survives a process death -- is **I2
and unresolved**, and is deliberately absent.

What this module does not do
----------------------------
No durable storage of any kind: the fill log is in memory, exactly as the
backtest's own ledger is. Spec §16.3 prescribes no storage, format or recovery
mechanism, and none is invented here. Recovery belongs to live integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Iterator

from core.types import DomainInvariantError, Side

__all__ = [
    "InsufficientFillIdentityError",
    "PositionMismatchError",
    "OperationKind",
    "FillKind",
    "FillIdentity",
    "FillRecord",
    "IdentityMinter",
    "FillLog",
    "record_then_apply",
]


class InsufficientFillIdentityError(DomainInvariantError):
    """Raised when an execution cannot be told apart from a redelivery.

    Refusing is the point. An execution carrying neither a broker deal id nor
    an execution index cannot be compared with anything, so treating it as new
    risks a second economic effect and treating it as a duplicate risks losing
    a real one. Spec §16.3 forbids guessing either way.
    """


class PositionMismatchError(DomainInvariantError):
    """Raised when a fill is recorded against a position it does not name.

    Spec §16.3: "A result that names a different position is rejected, not
    applied."
    """


class OperationKind(Enum):
    """What an instruction asks the broker to do."""

    ENTRY = "ENTRY"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    STOP_MODIFY = "STOP_MODIFY"
    FINAL_CLOSE = "FINAL_CLOSE"


class FillKind(Enum):
    """Which part of a position's life an execution belongs to.

    A stop modification never appears here: it moves protection without
    transferring quantity, so it produces no execution and no fill (§16.3).
    """

    ENTRY = "ENTRY"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    FINAL_EXIT = "FINAL_EXIT"


@dataclass(frozen=True, slots=True)
class FillIdentity:
    """Everything needed to tell one execution from another.

    Attributes:
        position_id: The canonical position the execution belongs to.
        operation_id: The instruction it answers.
        broker_deal_id: The broker's execution identifier, where the venue
            supplies one. Preferred, because it is the broker's own statement
            that two deliveries describe one execution.
        execution_index: Ordinal of this execution within its operation,
            starting at 1. Used where no deal id exists -- paper execution, for
            instance -- so that two genuine executions of one request stay
            distinct.

    Raises:
        DomainInvariantError: If either identifier is empty, or the execution
            index is not positive.
        InsufficientFillIdentityError: If neither a deal id nor an execution
            index is supplied.
    """

    position_id: str
    operation_id: str
    broker_deal_id: str | None = None
    execution_index: int | None = None

    def __post_init__(self) -> None:
        if not self.position_id:
            raise DomainInvariantError("position_id must be a non-empty string")
        if not self.operation_id:
            raise DomainInvariantError("operation_id must be a non-empty string")
        if self.execution_index is not None and self.execution_index < 1:
            raise DomainInvariantError(
                f"execution_index starts at 1, got {self.execution_index}"
            )
        if self.broker_deal_id is None and self.execution_index is None:
            raise InsufficientFillIdentityError(
                f"an execution for {self.position_id} carries neither a broker "
                "deal id nor an execution index, so a redelivery could not be "
                "told from a second execution; see specification section 16.3"
            )

    @property
    def fill_id(self) -> str:
        """The key this execution is recorded under.

        A broker deal id wins when present: it identifies the execution itself,
        so two deliveries of one deal produce one key whichever operation the
        caller believes it answers.
        """
        if self.broker_deal_id is not None:
            return f"{self.position_id}#deal:{self.broker_deal_id}"
        return f"{self.operation_id}#exec:{self.execution_index:02d}"


@dataclass(frozen=True, slots=True)
class FillRecord:
    """One execution, as recorded.

    Phase 2 holds what identity and quantity accounting need. Money -- P&L,
    commission, slippage attribution -- belongs to the ledger representation and
    is deliberately absent here.

    Attributes:
        identity: Who this execution is.
        kind: Entry, partial exit or final exit.
        cause: Why it happened, in the domain's vocabulary -- ``M1R``, ``STOP``,
            ``TARGET`` and so on. Free text at this phase; the ledger will
            constrain it.
        quantity_steps: Size in broker volume steps. The authoritative unit
            (spec §5.1); lots are derived at the broker boundary.
        price: The price actually executed at, as the broker reported it.
        time: When the execution occurred. Timezone-aware.
        broker_order_id: The broker's order identifier, where one exists.

    Raises:
        DomainInvariantError: If the quantity is not positive or the timestamp
            is naive.
    """

    identity: FillIdentity
    kind: FillKind
    cause: str
    quantity_steps: int
    price: float
    time: datetime
    broker_order_id: str | None = None

    def __post_init__(self) -> None:
        if self.quantity_steps <= 0:
            raise DomainInvariantError(
                f"quantity_steps must be positive, got {self.quantity_steps}"
            )
        if self.time.tzinfo is None:
            raise DomainInvariantError("time must be timezone-aware")

    @property
    def fill_id(self) -> str:
        """The key this execution is recorded under."""
        return self.identity.fill_id

    @property
    def position_id(self) -> str:
        """The canonical position this execution belongs to."""
        return self.identity.position_id

    @property
    def operation_id(self) -> str:
        """The instruction this execution answers."""
        return self.identity.operation_id


class IdentityMinter:
    """Mints canonical position and operation identities.

    One minter per run. Both counters are monotonic, so uniqueness holds by
    construction and does not depend on the readable components agreeing to
    differ.
    """

    __slots__ = ("_positions", "_operations")

    def __init__(self) -> None:
        self._positions = 0
        self._operations = 0

    @property
    def positions_minted(self) -> int:
        """How many position identities have been issued."""
        return self._positions

    @property
    def operations_minted(self) -> int:
        """How many operation identities have been issued."""
        return self._operations

    def next_position_id(
        self, *, symbol: str, side: Side, entry_bar_time: datetime
    ) -> str:
        """Mint a canonical position identity.

        Called when the position is created -- at the confirmed entry fill, not
        at submission, because an order that never fills has no position
        (spec §13).

        Args:
            symbol: Instrument.
            side: Trade direction.
            entry_bar_time: Open time of the bar filled against. Must be
                timezone-aware; it is normalised to UTC before formatting so
                the identity cannot vary with the machine's timezone.

        Returns:
            ``{symbol}-{entry_bar_time}-{side}-{sequence:04d}``.

        Raises:
            DomainInvariantError: If the symbol is empty or the time is naive.
        """
        if not symbol:
            raise DomainInvariantError("symbol must be a non-empty string")
        if entry_bar_time.tzinfo is None:
            raise DomainInvariantError(
                "entry_bar_time must be timezone-aware, or the identity would "
                "depend on the machine's timezone"
            )
        self._positions += 1
        stamp = entry_bar_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{symbol}-{stamp}-{side.value}-{self._positions:04d}"

    def next_operation_id(self, *, scope: str, kind: OperationKind) -> str:
        """Mint an identity for one instruction.

        The identity belongs to the *instruction*, not to an attempt at it: a
        retry of the same instruction reuses the value it was given, which is
        what makes a retry distinguishable from a new request (spec §16.3).
        This method is therefore called once per instruction, by whoever holds
        it.

        Args:
            scope: What the instruction concerns. The canonical ``position_id``
                once the position exists; for an entry, any deterministic
                submission scope, since the position has not been created yet.
            kind: Which instruction this is.

        Returns:
            ``{scope}#{kind}-{sequence:04d}``.

        Raises:
            DomainInvariantError: If the scope is empty.
        """
        if not scope:
            raise DomainInvariantError("scope must be a non-empty string")
        self._operations += 1
        return f"{scope}#{kind.value}-{self._operations:04d}"


class FillLog:
    """An append-only, in-memory record of executions.

    Append-only in the sense that matters here: a recorded execution is never
    amended or removed, and re-recording one is a no-op rather than a second
    entry. There is no durability -- the backtest's own ledger holds its trades
    in memory too, and a crashed replay is re-run rather than recovered. Durable
    restart is I2 and unresolved.
    """

    __slots__ = ("_records", "_by_id", "_by_position")

    def __init__(self) -> None:
        self._records: list[FillRecord] = []
        self._by_id: dict[str, FillRecord] = {}
        self._by_position: dict[str, list[FillRecord]] = {}

    def record(self, fill: FillRecord, *, for_position: str) -> bool:
        """Record one execution, ignoring a redelivery of one already held.

        ``for_position`` is required rather than inferred: attribution is the
        check spec §16.3 asks for, and taking it from the record itself would
        make the check vacuous.

        Args:
            fill: The execution to record.
            for_position: The canonical position the caller is applying this
                execution to.

        Returns:
            ``True`` if the execution was newly recorded, ``False`` if it was
            already held and this call changed nothing.

        Raises:
            PositionMismatchError: If the fill names a different position.
        """
        if fill.position_id != for_position:
            raise PositionMismatchError(
                f"fill {fill.fill_id} names position {fill.position_id}, but was "
                f"offered for {for_position}; a result that names a different "
                "position is rejected, not applied"
            )
        if fill.fill_id in self._by_id:
            return False
        self._records.append(fill)
        self._by_id[fill.fill_id] = fill
        self._by_position.setdefault(fill.position_id, []).append(fill)
        return True

    def holds(self, fill_id: str) -> bool:
        """Whether an execution with this key has been recorded."""
        return fill_id in self._by_id

    def fills_for(self, position_id: str) -> tuple[FillRecord, ...]:
        """Every execution recorded against one position, in recording order."""
        return tuple(self._by_position.get(position_id, ()))

    def steps_closed_for(self, position_id: str) -> int:
        """Total exit quantity recorded against one position.

        The independent check on quantity: what the broker is known to have
        closed, derived from executions rather than from a running counter.
        """
        return sum(
            fill.quantity_steps
            for fill in self._by_position.get(position_id, ())
            if fill.kind is not FillKind.ENTRY
        )

    def __contains__(self, fill_id: object) -> bool:
        return isinstance(fill_id, str) and fill_id in self._by_id

    def __iter__(self) -> Iterator[FillRecord]:
        return iter(tuple(self._records))

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[FillRecord, ...]:
        """Every execution recorded, in recording order."""
        return tuple(self._records)


def record_then_apply(
    log: FillLog,
    fill: FillRecord,
    *,
    for_position: str,
    apply: Callable[[FillRecord], None],
) -> bool:
    """Record an execution, then apply it -- in that order, never the reverse.

    The ordering is the contract. Applying first and recording afterwards loses
    the execution if the process dies between the two, leaving a position whose
    quantity the broker does not agree with; recording first can only ever
    duplicate a record, which :meth:`FillLog.record` makes harmless. A
    redelivery is recognised before ``apply`` is reached, so it produces no
    second economic effect (spec §16.3).

    Args:
        log: Where executions are recorded.
        fill: The execution.
        for_position: The canonical position being applied to.
        apply: What to do with a genuinely new execution. Called at most once,
            and only after the execution has been recorded.

    Returns:
        ``True`` if the execution was new and ``apply`` ran, ``False`` if it was
        a redelivery and nothing happened.

    Raises:
        PositionMismatchError: If the fill names a different position. Raised
            before anything is recorded or applied.
    """
    if not log.record(fill, for_position=for_position):
        return False
    apply(fill)
    return True
