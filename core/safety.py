"""Execution safety lock.

Why this module exists
----------------------
The Phase 1 audit found production capable of *starting in a live-trading
configuration that could never place an order*:

``main_production.CONFIG["demo_mode"]`` is ``False`` -- declaring live intent --
and ``main()`` logs ``Mode: LIVE``. The order path then calls::

    order_executor.execute_order(order_id, mt5_handler=None, simulation=False)

which ``order_execution.py`` answers with
``(False, "No MT5 handler provided and simulation disabled")``. Even if a handler
*were* passed, the branch calls ``mt5_handler.send_order(...)`` -- a method that
does not exist anywhere in ``mt5_handler.py``.

So the bot ran for 39,709 decision cycles announcing itself as LIVE while being
structurally incapable of trading. That is the failure mode this module ends: an
invalid execution configuration must **stop the process at startup**, loudly,
rather than degrade into a silent no-op that looks like normal operation.

The Phase 0/1 invariant
-----------------------
::

    LIVE TRADING = DISABLED

unconditionally, regardless of ``demo_mode``, environment, or configuration.

:data:`LIVE_TRADING_ENABLED` is a module constant fixed at ``False``. It is
deliberately **not** read from the environment, **not** settable through config,
and has **no override flag**. There is no documented or undocumented way to turn
live trading on from outside this module. Enabling it requires editing source,
which is a reviewable, diffable act -- not an accident.

This is intentional and is not an oversight to be "fixed" by adding a switch.
The broker and execution safety model is Phase 2 work: a real broker adapter,
broker-side stop registration, position reconciliation, and a corrected position
sizer must all exist *before* this constant is allowed to change. Until then,
flipping it would re-enable an execution path that cannot transmit an order and
has no broker-side stop protection.

Design notes
------------
Pure predicate: no I/O, no logging, no MT5 import, no environment access. It can
therefore be unit-tested exhaustively and cannot itself become a source of
non-determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

__all__ = [
    "ExecutionMode",
    "ExecutionState",
    "LIVE_TRADING_ENABLED",
    "PHASE_LOCK_REASON",
    "UnsafeExecutionStateError",
    "assert_live_trading_disabled",
    "describe_execution_state",
    "resolve_execution_mode",
    "validate_execution_environment",
]

LIVE_TRADING_ENABLED: Final[bool] = False
"""Master lock on live order submission. Fixed at ``False`` for Phase 0/1.

Never read from the environment and never overridable at runtime. See the module
docstring for why this has no escape hatch.
"""

PHASE_LOCK_REASON: Final[str] = (
    "Live trading is disabled by the Phase 0/1 safety invariant "
    "(core.safety.LIVE_TRADING_ENABLED is False). The execution layer has known "
    "unresolved P0 defects: orders are never transmitted to the broker "
    "(mt5_handler has no send_order), stops are not registered broker-side, and "
    "local position state is never reconciled against the broker. A real broker "
    "adapter and execution safety model are Phase 2 work."
)
"""Why the lock is in place. Cited verbatim in the startup refusal.

This text previously also listed "position sizing is ~10x oversized". That
defect (``PHASE_2_ISSUES.md`` R1) has since been fixed: ``risk_manager`` now
delegates to ``core.sizing.lots_for_risk`` with a broker-supplied
``SymbolSpecification``, and ``main_production.execute_entry_signal`` declines
to trade when no specification is available rather than assuming the
instrument's economics.

The claim is removed because an inaccurate safety notice is worse than a
terse one -- a reader who checks one item, finds it stale, and discounts the
rest is the failure mode. The remaining three items are current.
"""


class UnsafeExecutionStateError(RuntimeError):
    """Raised when the process is configured to trade in an unsafe state.

    Deliberately fatal. The alternative -- degrading to a no-op -- is precisely
    the behaviour that let the system report ``Mode: LIVE`` for months while
    placing no orders.
    """


class ExecutionMode(Enum):
    """What the process is permitted to do with signals.

    Attributes:
        ANALYSIS_ONLY: Run the decision pipeline and record results. No order is
            constructed or submitted. The only mode fully safe in Phase 0/1.
        SIMULATION: Construct orders and simulate fills in memory. No broker
            contact. Requires an order executor to be present.
        LIVE: Submit real orders to a broker. **Unreachable in Phase 0/1** --
            requesting it always raises.
    """

    ANALYSIS_ONLY = "ANALYSIS_ONLY"
    SIMULATION = "SIMULATION"
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """Snapshot of how the process intends to execute, for validation and logging.

    Attributes:
        mode: The requested execution mode.
        has_order_executor: Whether an order executor object is available.
        has_broker_handler: Whether a broker handler capable of submitting orders
            is available.
        live_trading_enabled: The value of the module lock at validation time.
    """

    mode: ExecutionMode
    has_order_executor: bool
    has_broker_handler: bool
    live_trading_enabled: bool = LIVE_TRADING_ENABLED


def resolve_execution_mode(demo_mode: bool, execution_available: bool = True) -> ExecutionMode:
    """Map the legacy ``CONFIG["demo_mode"]`` flag onto an explicit mode.

    The legacy flag is a boolean carrying three meanings at once, which is how
    "not demo" came to imply "live" without anything checking that live was
    actually possible.

    Args:
        demo_mode: The legacy ``CONFIG["demo_mode"]`` value. ``False`` declares
            live intent.
        execution_available: Whether the order execution module imported
            successfully.

    Returns:
        :attr:`ExecutionMode.ANALYSIS_ONLY` when execution is unavailable,
        :attr:`ExecutionMode.SIMULATION` when ``demo_mode`` is true, and
        :attr:`ExecutionMode.LIVE` otherwise.
    """
    if not execution_available:
        return ExecutionMode.ANALYSIS_ONLY
    return ExecutionMode.SIMULATION if demo_mode else ExecutionMode.LIVE


def validate_execution_environment(
    *,
    mode: ExecutionMode,
    order_executor: Any | None = None,
    broker_handler: Any | None = None,
) -> ExecutionState:
    """Validate that the process may run in ``mode``, or refuse to continue.

    Call this once at startup, before the main loop. It never returns a boolean
    for the caller to ignore -- it either returns a validated state or raises.

    Args:
        mode: The execution mode the process intends to run in.
        order_executor: The order executor instance, if any.
        broker_handler: The broker handler used to submit orders, if any.

    Returns:
        A validated :class:`ExecutionState`.

    Raises:
        UnsafeExecutionStateError: If ``mode`` is :attr:`ExecutionMode.LIVE`
            (always, in Phase 0/1), or if :attr:`ExecutionMode.SIMULATION` is
            requested without an order executor to simulate with.
        TypeError: If ``mode`` is not an :class:`ExecutionMode`.

    Example:
        >>> validate_execution_environment(mode=ExecutionMode.ANALYSIS_ONLY).mode
        <ExecutionMode.ANALYSIS_ONLY: 'ANALYSIS_ONLY'>
    """
    if not isinstance(mode, ExecutionMode):
        raise TypeError(f"mode must be an ExecutionMode, got {type(mode).__name__}")

    state = ExecutionState(
        mode=mode,
        has_order_executor=order_executor is not None,
        has_broker_handler=broker_handler is not None,
        live_trading_enabled=LIVE_TRADING_ENABLED,
    )

    if mode is ExecutionMode.LIVE:
        raise UnsafeExecutionStateError(
            "REFUSING TO START: live trading was requested but is disabled.\n"
            f"\n{PHASE_LOCK_REASON}\n"
            "\nThis configuration previously started successfully and reported "
            "'Mode: LIVE' while being structurally unable to place an order -- "
            "order_execution.execute_order(mt5_handler=None, simulation=False) "
            "always returns False, and the branch it would otherwise take calls "
            "mt5_handler.send_order(), which does not exist.\n"
            "\nTo run safely now, choose one of:\n"
            "  * ANALYSIS_ONLY - run the decision pipeline and record results "
            "(set CONFIG['demo_mode'] = True and keep signals unexecuted), or\n"
            "  * SIMULATION    - set CONFIG['demo_mode'] = True to simulate fills "
            "in memory.\n"
            "Neither contacts a broker."
        )

    if mode is ExecutionMode.SIMULATION and order_executor is None:
        raise UnsafeExecutionStateError(
            "REFUSING TO START: SIMULATION mode was requested but no order "
            "executor is available (order_execution failed to import). "
            "Running on without one would silently discard every signal. "
            "Use ExecutionMode.ANALYSIS_ONLY if that is what you intend."
        )

    return state


def assert_live_trading_disabled() -> None:
    """Assert the Phase 0/1 invariant still holds.

    A tripwire for use at import time or in tests. If :data:`LIVE_TRADING_ENABLED`
    is ever flipped without the Phase 2 execution safety model in place, this
    fails loudly at the earliest opportunity.

    Raises:
        UnsafeExecutionStateError: If :data:`LIVE_TRADING_ENABLED` is not ``False``.
    """
    if LIVE_TRADING_ENABLED is not False:
        raise UnsafeExecutionStateError(
            "core.safety.LIVE_TRADING_ENABLED has been changed from False. "
            f"{PHASE_LOCK_REASON}"
        )


def describe_execution_state(state: ExecutionState) -> str:
    """Render an :class:`ExecutionState` as a single log-friendly line.

    Args:
        state: The state to describe.

    Returns:
        A human-readable summary for startup logging.
    """
    return (
        f"execution_mode={state.mode.value} "
        f"live_trading_enabled={state.live_trading_enabled} "
        f"order_executor={'yes' if state.has_order_executor else 'no'} "
        f"broker_handler={'yes' if state.has_broker_handler else 'no'}"
    )
