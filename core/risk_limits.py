"""Account-level risk limits, and the state needed to evaluate them.

Why this module exists
----------------------
The Phase 1 audit found that every account-level risk control in the system was
**structurally incapable of firing**. Not mistuned -- unreachable:

* ``main_production.check_pre_trade_gates(account_balance=10000,
  current_daily_loss=0)`` was called as ``check_pre_trade_gates(regime_info=...)``.
  Both risk inputs therefore took their defaults on every call, so the breaker
  evaluated ``0 < -500`` forever. It could not fail. (``PHASE_2_ISSUES.md`` R3)
* ``account_balance`` defaulted to ``10000`` with no caller supplying it, so
  every risk figure in the system was computed from a number that had nothing to
  do with the account. ``mt5.account_info()`` was called once, for a log line,
  and discarded. (R2)
* Nothing anywhere tracked realised P&L, so no component could answer "is the
  account down today?" (R4)
* There was no drawdown limit, no consecutive-loss limit and no equity kill
  switch of any kind. (R7)
* ``max_concurrent_trades = 3`` capped the position *count* on a single symbol,
  which is three times the same directional risk, and no lot-level exposure cap
  existed. (R8)
* ``config.INTRADAY_LOT_SIZE_MAX = 0.1`` and
  ``config.INTRADAY_MAX_HOLD_MINUTES = 240`` were defined and enforced nowhere.
  ``core.sizing`` caps at the *broker's* ``volume_max``, which is a different and
  far larger limit. (R6, R9)

The design rule: absence of information means STOP
--------------------------------------------------
The root cause of R3 was not a wrong threshold. It was a **default that meant
"all clear"**. ``current_daily_loss: float = 0`` is an assertion that the account
has lost nothing, made by a function that had no way to know.

So every entry point here either receives the real figure or refuses. There is no
"assume flat" default, :class:`AccountRiskState` has no defaulted P&L field, and
:func:`evaluate` returns :attr:`RiskVerdict.HALT` when state is unavailable
rather than falling through to permission. A risk gate that cannot prove the
account is safe must not report that it is.

Scope
-----
These are **account-level** limits, deliberately separate from
:class:`core.types.RiskParameters`, which is the per-*trade* budget. One trade
sized correctly against a 1% risk budget can still be the trade that breaches a
daily loss cap; they are different questions and are kept apart.

Design notes
------------
Pure predicate, following ``core/safety.py``: no I/O, no logging, no MT5 import,
no clock access except through an injected ``now``. Every function is therefore
exhaustively unit-testable and cannot itself introduce non-determinism. Callers
in ``main_production`` do the I/O and pass values in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Mapping, Sequence

from core.units import Percentage

__all__ = [
    "AccountRiskState",
    "RiskDecision",
    "RiskLimitError",
    "RiskLimits",
    "RiskVerdict",
    "build_state",
    "evaluate",
    "overdue_positions",
    "realised_pnl_for_day",
]


class RiskLimitError(ValueError):
    """Raised when a limit set or a state snapshot cannot describe a real account.

    Deliberately an error rather than a clamp. A silently corrected risk limit is
    how a 5% daily cap becomes a 50% one.
    """


class RiskVerdict(Enum):
    """What the account is permitted to do right now.

    Attributes:
        ALLOW: New positions may be opened, subject to per-trade sizing.
        BLOCK_NEW_ENTRIES: Existing positions may be managed and closed, but no
            new position may be opened. The recoverable state -- a daily loss cap
            or a concurrency cap clears on its own.
        HALT: Stop trading and require human attention. Reached by a drawdown
            breach or by state that could not be determined. Not self-clearing.
    """

    ALLOW = "ALLOW"
    BLOCK_NEW_ENTRIES = "BLOCK_NEW_ENTRIES"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Account-level limits.

    Attributes:
        max_daily_loss: Realised loss in one trading day, as an account
            percentage of the day's opening balance. Breach blocks new entries
            until the next trading day.
        max_drawdown: Peak-to-current equity decline, as a percentage of peak
            equity. Breach HALTS -- this is the kill switch.
        max_consecutive_losses: Consecutive losing closes before new entries are
            blocked. ``None`` disables the check.
        max_concurrent_positions: Simultaneous open position cap.
        max_open_lots: Total open volume cap across all positions, in lots. This
            is the exposure limit a position *count* cannot express: three 0.10
            lot positions on one symbol are 0.30 lots of the same risk.
        max_lots_per_position: Per-position volume cap, in lots. Applied on top
            of the broker's own ``volume_max``, which is far larger.
        max_hold: How long a position may stay open before the time stop applies.
            ``None`` disables the time stop.
    """

    max_daily_loss: Percentage
    max_drawdown: Percentage
    max_concurrent_positions: int
    max_open_lots: float
    max_lots_per_position: float
    max_consecutive_losses: int | None = None
    max_hold: timedelta | None = None

    def __post_init__(self) -> None:
        """Validate the limit set.

        Raises:
            RiskLimitError: If any limit is absent, mistyped or non-positive, or
                if a percentage exceeds 100.
        """
        for name in ("max_daily_loss", "max_drawdown"):
            value = getattr(self, name)
            if not isinstance(value, Percentage):
                raise RiskLimitError(
                    f"{name} must be a Percentage, got {type(value).__name__}. "
                    f"A bare float is ambiguous between 5% and 500%."
                )
            if not 0.0 < value.value <= 100.0:
                raise RiskLimitError(
                    f"{name} must be in (0, 100]%, got {value.value}%"
                )
        if self.max_concurrent_positions < 1:
            raise RiskLimitError(
                f"max_concurrent_positions must be >= 1, got "
                f"{self.max_concurrent_positions}"
            )
        for name in ("max_open_lots", "max_lots_per_position"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RiskLimitError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value) or value <= 0.0:
                raise RiskLimitError(f"{name} must be finite and > 0, got {value!r}")
        if self.max_open_lots < self.max_lots_per_position:
            raise RiskLimitError(
                f"max_open_lots ({self.max_open_lots}) is below "
                f"max_lots_per_position ({self.max_lots_per_position}), so a "
                f"single permitted position would breach the total cap"
            )
        if self.max_consecutive_losses is not None and self.max_consecutive_losses < 1:
            raise RiskLimitError(
                f"max_consecutive_losses must be >= 1 or None, got "
                f"{self.max_consecutive_losses}"
            )
        if self.max_hold is not None and self.max_hold <= timedelta(0):
            raise RiskLimitError(f"max_hold must be positive, got {self.max_hold}")


@dataclass(frozen=True, slots=True)
class AccountRiskState:
    """What the account has actually done, as far as can be established.

    Every field is required. There is deliberately no default for any P&L or
    equity figure: a defaulted ``realised_pnl_today = 0.0`` is exactly the defect
    this module exists to remove. Build instances with :func:`build_state`, which
    derives the derived fields from a closed-trade history.

    Attributes:
        balance: Account balance in the account currency, from the broker.
        equity: Account equity (balance plus open P&L), from the broker.
        day_opening_balance: Balance at the start of the current trading day. The
            daily loss cap is a percentage of this, not of the live balance,
            so the cap does not shrink as the day's losses accumulate.
        peak_equity: Highest equity observed. The drawdown denominator.
        realised_pnl_today: Realised P&L for ``trading_day``, account currency.
            Negative is a loss.
        consecutive_losses: Losing closes since the last win.
        open_positions: Count of currently open positions.
        open_lots: Total open volume across all positions, in lots.
        trading_day: The day ``realised_pnl_today`` covers, in UTC.
    """

    balance: float
    equity: float
    day_opening_balance: float
    peak_equity: float
    realised_pnl_today: float
    consecutive_losses: int
    open_positions: int
    open_lots: float
    trading_day: date

    def __post_init__(self) -> None:
        """Validate the snapshot.

        Raises:
            RiskLimitError: If a monetary field is not finite, a balance is
                non-positive, a count is negative, or ``peak_equity`` is below
                ``equity`` (which would make drawdown negative).
        """
        for name in (
            "balance", "equity", "day_opening_balance",
            "peak_equity", "realised_pnl_today", "open_lots",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RiskLimitError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value):
                raise RiskLimitError(f"{name} must be finite, got {value!r}")
        for name in ("balance", "equity", "day_opening_balance", "peak_equity"):
            if getattr(self, name) <= 0.0:
                raise RiskLimitError(
                    f"{name} must be > 0, got {getattr(self, name)!r}. A "
                    f"zero or negative account cannot be risk-managed; it is "
                    f"already gone."
                )
        for name in ("consecutive_losses", "open_positions"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise RiskLimitError(f"{name} must be an int, got {value!r}")
            if value < 0:
                raise RiskLimitError(f"{name} must be >= 0, got {value}")
        if self.open_lots < 0.0:
            raise RiskLimitError(f"open_lots must be >= 0, got {self.open_lots}")
        if self.peak_equity < self.equity:
            raise RiskLimitError(
                f"peak_equity ({self.peak_equity}) is below equity "
                f"({self.equity}); the peak must include the present"
            )
        if not isinstance(self.trading_day, date):
            raise RiskLimitError(
                f"trading_day must be a date, got {type(self.trading_day).__name__}"
            )

    @property
    def drawdown(self) -> Percentage:
        """Current peak-to-equity decline, as a percentage of peak equity."""
        if self.peak_equity <= 0.0:  # pragma: no cover - barred by __post_init__
            return Percentage(0.0)
        return Percentage(
            100.0 * (self.peak_equity - self.equity) / self.peak_equity
        )

    @property
    def daily_loss(self) -> Percentage:
        """Today's realised loss as a percentage of the day's opening balance.

        ``Percentage(0.0)`` when the day is flat or up -- this reports loss, not
        signed return, because that is what the limit is expressed against.
        """
        if self.realised_pnl_today >= 0.0:
            return Percentage(0.0)
        return Percentage(
            100.0 * (-self.realised_pnl_today) / self.day_opening_balance
        )


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The outcome of one risk evaluation.

    Attributes:
        verdict: What the account may do.
        breaches: Human-readable breach descriptions, most severe first. Empty
            when ``verdict`` is :attr:`RiskVerdict.ALLOW`.
        max_new_lots: Headroom for a new position, in lots, after the
            concurrency and exposure caps. ``0.0`` whenever opening is barred.
    """

    verdict: RiskVerdict
    breaches: tuple[str, ...]
    max_new_lots: float

    @property
    def may_open(self) -> bool:
        """Whether a new position may be opened at all."""
        return self.verdict is RiskVerdict.ALLOW and self.max_new_lots > 0.0

    def describe(self) -> str:
        """Render as a single log-friendly line."""
        if not self.breaches:
            return f"{self.verdict.value} headroom={self.max_new_lots:.2f} lots"
        return f"{self.verdict.value}: " + " | ".join(self.breaches)


def evaluate(state: AccountRiskState | None, limits: RiskLimits) -> RiskDecision:
    """Decide what the account may do.

    Args:
        state: The account snapshot, or ``None`` when it could not be
            established (no broker connection, no account info, no trade
            history). ``None`` is **not** treated as a flat account.
        limits: The limits to apply.

    Returns:
        A :class:`RiskDecision`. Checks are evaluated in severity order and all
        breaches are reported, so one log line shows everything that is wrong
        rather than only the first thing found.

    Example:
        >>> evaluate(None, _example_limits()).verdict
        <RiskVerdict.HALT: 'HALT'>
    """
    if not isinstance(limits, RiskLimits):
        raise RiskLimitError(
            f"limits must be a RiskLimits, got {type(limits).__name__}"
        )

    if state is None:
        # The defect this module exists to prevent. Unknown is not safe.
        return RiskDecision(
            verdict=RiskVerdict.HALT,
            breaches=(
                "ACCOUNT STATE UNAVAILABLE: cannot establish balance, equity or "
                "realised P&L, so no risk limit can be evaluated. Refusing to "
                "trade rather than assuming the account is flat.",
            ),
            max_new_lots=0.0,
        )

    breaches: list[str] = []

    # --- HALT tier: not self-clearing ---------------------------------
    drawdown = state.drawdown
    if drawdown.value >= limits.max_drawdown.value:
        breaches.append(
            f"MAX DRAWDOWN: equity {state.equity:.2f} is {drawdown.value:.2f}% "
            f"below peak {state.peak_equity:.2f} "
            f"(limit {limits.max_drawdown.value:.2f}%) -- trading halted"
        )
        return RiskDecision(RiskVerdict.HALT, tuple(breaches), 0.0)

    # --- BLOCK tier: clears on its own --------------------------------
    daily_loss = state.daily_loss
    if daily_loss.value >= limits.max_daily_loss.value:
        breaches.append(
            f"DAILY LOSS: {state.realised_pnl_today:.2f} realised on "
            f"{state.trading_day.isoformat()} is {daily_loss.value:.2f}% of the "
            f"day's opening balance {state.day_opening_balance:.2f} "
            f"(limit {limits.max_daily_loss.value:.2f}%)"
        )

    if (
        limits.max_consecutive_losses is not None
        and state.consecutive_losses >= limits.max_consecutive_losses
    ):
        breaches.append(
            f"CONSECUTIVE LOSSES: {state.consecutive_losses} "
            f"(limit {limits.max_consecutive_losses})"
        )

    if state.open_positions >= limits.max_concurrent_positions:
        breaches.append(
            f"CONCURRENCY: {state.open_positions} open "
            f"(limit {limits.max_concurrent_positions})"
        )

    lot_headroom = limits.max_open_lots - state.open_lots
    if lot_headroom <= 0.0:
        breaches.append(
            f"EXPOSURE: {state.open_lots:.2f} lots open "
            f"(limit {limits.max_open_lots:.2f})"
        )

    if breaches:
        return RiskDecision(RiskVerdict.BLOCK_NEW_ENTRIES, tuple(breaches), 0.0)

    return RiskDecision(
        verdict=RiskVerdict.ALLOW,
        breaches=(),
        max_new_lots=min(lot_headroom, limits.max_lots_per_position),
    )


def realised_pnl_for_day(
    closed_trades: Iterable[Mapping[str, object]],
    day: date,
    *,
    pnl_key: str = "pnl",
    time_key: str = "exit_time",
) -> tuple[float, int]:
    """Sum realised P&L for one UTC trading day.

    Args:
        closed_trades: Closed-trade records. Each needs a numeric ``pnl_key`` and
            an ISO-8601 ``time_key``.
        day: The UTC date to total.
        pnl_key: Field holding realised P&L.
        time_key: Field holding the close time.

    Returns:
        ``(total_pnl, trades_counted)``.

    Raises:
        RiskLimitError: If a record carries a close time on ``day`` but a P&L
            that is absent or non-numeric. Skipping it would understate the day's
            loss, which is the one direction a risk gate must never err in.
    """
    total = 0.0
    counted = 0
    for record in closed_trades:
        moment = _parse_utc(record.get(time_key))
        if moment is None or moment.date() != day:
            continue
        raw = record.get(pnl_key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise RiskLimitError(
                f"closed trade {record.get('trade_id', '<no id>')!r} closed on "
                f"{day.isoformat()} has {pnl_key}={raw!r}, which is not a "
                f"number. Treating it as zero would understate the day's loss."
            )
        if not math.isfinite(float(raw)):
            raise RiskLimitError(
                f"closed trade {record.get('trade_id', '<no id>')!r} has "
                f"non-finite {pnl_key}={raw!r}"
            )
        total += float(raw)
        counted += 1
    return total, counted


def build_state(
    *,
    balance: float,
    equity: float,
    closed_trades: Sequence[Mapping[str, object]],
    open_positions: int,
    open_lots: float,
    now: datetime,
    peak_equity: float | None = None,
    pnl_key: str = "pnl",
    time_key: str = "exit_time",
) -> AccountRiskState:
    """Assemble an :class:`AccountRiskState` from broker figures and history.

    Args:
        balance: Broker-reported balance.
        equity: Broker-reported equity.
        closed_trades: Full closed-trade history, oldest first or unordered;
            ordering is established from ``time_key``.
        open_positions: Count of open positions, from the broker.
        open_lots: Total open volume in lots, from the broker.
        now: Current time. Must be timezone-aware -- the trading day is a UTC
            date and a naive clock would silently pick the host's timezone.
        peak_equity: Highest equity ever observed, if tracked externally.
            Defaults to the running peak implied by ``closed_trades`` and the
            current equity, which is a **lower bound** on the true peak: it
            cannot see unrealised highs. A conservative peak understates
            drawdown, so pass the tracked figure when there is one.
        pnl_key: Field holding realised P&L in ``closed_trades``.
        time_key: Field holding the close time in ``closed_trades``.

    Returns:
        The assembled state.

    Raises:
        RiskLimitError: If ``now`` is naive, or if any assembled field fails
            :class:`AccountRiskState` validation.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise RiskLimitError(
            "now must be timezone-aware; the trading day is a UTC date and a "
            "naive clock would resolve it in the host's local timezone"
        )
    today = now.astimezone(timezone.utc).date()

    realised_today, _ = realised_pnl_for_day(
        closed_trades, today, pnl_key=pnl_key, time_key=time_key
    )

    ordered = sorted(
        (r for r in closed_trades if _parse_utc(r.get(time_key)) is not None),
        key=lambda r: _parse_utc(r.get(time_key)),  # type: ignore[arg-type]
    )

    consecutive = 0
    for record in reversed(ordered):
        raw = record.get(pnl_key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            break
        if float(raw) < 0.0:
            consecutive += 1
        else:
            break

    # The day's opening balance is today's balance with today's realised P&L
    # removed. Expressing the daily cap against this rather than against the
    # live balance stops the cap shrinking as the day's losses accumulate.
    day_opening_balance = balance - realised_today

    if peak_equity is None:
        # Reconstruct the realised equity curve backwards from the CURRENT
        # balance, so the walk is self-consistent: starting at
        # `balance - sum(all pnl)` and applying every close in order
        # terminates exactly at `balance`.
        #
        # Starting from `day_opening_balance` instead would double-count --
        # that figure already reflects every prior close, so re-applying the
        # history walked the curve to the wrong endpoint and reported a peak
        # (and therefore a drawdown) that no sequence of trades could produce.
        history = [
            float(r[pnl_key]) for r in ordered
            if isinstance(r.get(pnl_key), (int, float))
            and not isinstance(r.get(pnl_key), bool)
            and math.isfinite(float(r[pnl_key]))
        ]
        running = balance - sum(history)
        peak = max(running, equity)
        for pnl in history:
            running += pnl
            peak = max(peak, running)
        peak_equity = max(peak, equity)

    return AccountRiskState(
        balance=balance,
        equity=equity,
        day_opening_balance=day_opening_balance,
        peak_equity=max(peak_equity, equity),
        realised_pnl_today=realised_today,
        consecutive_losses=consecutive,
        open_positions=open_positions,
        open_lots=open_lots,
        trading_day=today,
    )


def overdue_positions(
    open_trades: Iterable[Mapping[str, object]],
    *,
    now: datetime,
    max_hold: timedelta | None,
    time_key: str = "entry_time",
    id_key: str = "trade_id",
) -> tuple[tuple[str, timedelta], ...]:
    """Identify positions held past the time stop.

    ``config.INTRADAY_MAX_HOLD_MINUTES`` has existed, unenforced, since it was
    written. This is the predicate that makes it mean something; the caller
    performs the exit.

    Args:
        open_trades: Open-trade records with an ISO-8601 ``time_key``.
        now: Current time, timezone-aware.
        max_hold: The holding limit. ``None`` disables the check.
        time_key: Field holding the entry time.
        id_key: Field holding the trade identifier.

    Returns:
        ``((trade_id, held_for), ...)`` for positions past the limit, longest
        held first. Empty when ``max_hold`` is ``None``.

    Raises:
        RiskLimitError: If ``now`` is naive, or if a record's entry time cannot
            be parsed. An unparseable entry time means the position's age is
            unknown, and an unknown age must not silently read as "young".
    """
    if max_hold is None:
        return ()
    if now.tzinfo is None or now.utcoffset() is None:
        raise RiskLimitError("now must be timezone-aware")

    overdue: list[tuple[str, timedelta]] = []
    for record in open_trades:
        raw = record.get(time_key)
        moment = _parse_utc(raw)
        if moment is None:
            raise RiskLimitError(
                f"open trade {record.get(id_key, '<no id>')!r} has "
                f"{time_key}={raw!r}, which cannot be parsed as a timestamp. "
                f"Its age is therefore unknown and the time stop cannot be "
                f"applied."
            )
        held = now.astimezone(timezone.utc) - moment
        if held >= max_hold:
            overdue.append((str(record.get(id_key, "<no id>")), held))
    overdue.sort(key=lambda pair: pair[1], reverse=True)
    return tuple(overdue)


def _parse_utc(value: object) -> datetime | None:
    """Parse a timestamp to an aware UTC datetime, or ``None`` if not a time.

    Naive values are assumed UTC, matching how the production records were
    written (``datetime.now().isoformat()``).
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _example_limits() -> RiskLimits:
    """Limit set used by the doctest above. Not a recommended configuration."""
    return RiskLimits(
        max_daily_loss=Percentage(5.0),
        max_drawdown=Percentage(20.0),
        max_concurrent_positions=1,
        max_open_lots=0.1,
        max_lots_per_position=0.1,
    )
