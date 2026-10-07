"""The approved broker-execution surface: every site that can reach a broker.

This is an **inventory, not a permission**. Listing a call here does not make it
safe and does not authorise live trading -- ``core.safety.LIVE_TRADING_ENABLED``
is still the literal ``False`` and every guard recorded below is still in force.
What the inventory does is make the surface *countable*: a call that is not
listed fails the scan, and a listed call whose guards have disappeared fails it
too.

The alternative -- excluding files, adding ``# noqa``, or widening a regex --
would make the surface smaller on paper and unchanged in fact. That is
specifically what this file exists to prevent.

Produced by AST scan of every production file at Phase 6H, cross-checked against
the Phase 6G reachability audit
(``docs/PHASE_6G_LEGACY_EXECUTION_REACHABILITY.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "APPROVED_BROKER_CALLS",
    "APPROVED_MT5_IMPORTERS",
    "BrokerCallSite",
    "MUTATING_PRIMITIVES",
    "PRODUCTION_GLOBS",
]

#: Calls that can change broker state. Any occurrence must be in the inventory.
#: ``send_order`` is included although no such method exists anywhere: the call
#: is written, and a future ``mt5_handler`` gaining the method would arm it
#: silently.
MUTATING_PRIMITIVES = frozenset({
    "order_send",
    "order_check",
    "send_order",
    "position_close",
    "position_close_by",
    "order_close",
    "Buy",
    "Sell",
})

#: Where production code lives. Tests, the virtualenv and untracked worktrees
#: are excluded because they are not shipped, not because they are trusted.
PRODUCTION_GLOBS = (
    "*.py",
    "core/*.py",
    "data/*.py",
    "execution/*.py",
    "backtest/*.py",
    "tools/*.py",
)


@dataclass(frozen=True, slots=True)
class BrokerCallSite:
    """One approved site that can reach a broker.

    Attributes:
        module: Repo-relative path, forward-slashed.
        function: Enclosing function, or ``"<module>"``.
        call: The call as written, e.g. ``"mt5.order_send"``.
        operation: ``OPEN``, ``CLOSE``, ``MODIFY`` or ``READ``.
        lineage: ``CANONICAL`` or ``LEGACY``.
        reachable: Whether a production path can execute it, per Phase 6G.
        guards: Identifiers that must still appear in the enclosing function.
            If one disappears, the safety contract around the call has changed
            and the scan fails.
        why: Why the call exists.
        status: Whether it is approved permanently or tolerated for now.
    """

    module: str
    function: str
    call: str
    operation: str
    lineage: str
    reachable: bool
    guards: tuple[str, ...]
    why: str
    status: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity used to match a scanned call against the inventory."""
        return (self.module, self.function, self.call)


APPROVED_BROKER_CALLS: tuple[BrokerCallSite, ...] = (
    BrokerCallSite(
        module="main.py",
        function="close_all_positions",
        call="mt5.order_send",
        operation="CLOSE",
        lineage="LEGACY",
        reachable=True,
        guards=("CLOSE_POSITIONS_ON_SHUTDOWN", "LIVE_TRADING_ENABLED",
                "MT5_AVAILABLE", "_OWNED_TICKETS"),
        why=(
            "Shutdown position flattener, now GATED. It previously closed every "
            "open position on the configured symbol -- INCLUDING positions this "
            "system did not open -- on Ctrl-C and on normal loop exit, while "
            "main.py imported core.safety NOWHERE. It is now guarded four ways, "
            "any one of which stops every order: CLOSE_POSITIONS_ON_SHUTDOWN is "
            "False by default; core.safety.LIVE_TRADING_ENABLED is False with no "
            "override; MT5_AVAILABLE; and only tickets in _OWNED_TICKETS are "
            "touched. main.py places NO orders -- no order executor, no sizing, "
            "no create_order -- so it can never populate _OWNED_TICKETS, which "
            "makes the close path unreachable in practice as well as gated."
        ),
        status=(
            "TEMPORARY. Phase 6G risk R1 is MITIGATED (remediation item 3, 'gate "
            "or remove main.py's close path'). Item 2 -- whether main.py is a "
            "second entry point or is superseded by main_production -- REMAINS "
            "OPEN, and the gating was written so as not to presuppose either "
            "answer: it is correct behaviour whichever way item 2 is decided, "
            "which is why fixing item 3 first does not resolve item 2 by "
            "accident. See PHASE_6G section 7."
        ),
    ),
    BrokerCallSite(
        module="main_production.py",
        function="graceful_shutdown",
        call="mt5.order_send",
        operation="CLOSE",
        lineage="LEGACY",
        reachable=True,
        guards=("MT5_AVAILABLE",),
        why=(
            "Shutdown position flattener, the same operation as main.py's and "
            "with the same reach: it closes whatever the terminal holds, not "
            "only canonical positions. Unlike main.py this module IS gated -- "
            "main() calls assert_live_trading_disabled() and then "
            "validate_execution_environment(), which raises on LIVE. With the "
            "shipped CONFIG['demo_mode'] = False that gate refuses startup, so "
            "the handler installing this path is never reached."
        ),
        status=(
            "TEMPORARY. Phase 6G risk R2. LIVE_TRADING_ENABLED does not gate "
            "this call directly; the startup refusal and the __main__ "
            "requirement do. Retained so that a future relaxation of either is "
            "visible rather than silent."
        ),
    ),
    BrokerCallSite(
        module="order_execution.py",
        function="execute_order",
        call="mt5_handler.send_order",
        operation="OPEN",
        lineage="LEGACY",
        reachable=False,
        guards=("mt5_handler", "simulation"),
        why=(
            "The only written path that could open a position outside the "
            "canonical adapter. It is STRUCTURALLY DEAD: order_execution.py "
            "never imports MetaTrader5, so it can only reach a broker through "
            "a handler its caller supplies, and the sole production caller "
            "(main_production.execute_entry_signal) passes mt5_handler=None as "
            "a hardcoded literal. mt5_handler.py defines no send_order, so "
            "even a supplied handler would raise AttributeError. It also "
            "passes no volume, so canonical sizing would not reach the broker."
        ),
        status=(
            "TEMPORARY. Phase 6G risks R3 and R4. UNRESOLVED: whether "
            "order_execution is retired or repaired. Listed rather than deleted "
            "so that supplying a handler, or adding send_order to mt5_handler, "
            "fails this inventory instead of quietly arming an unsized order."
        ),
    ),
)

#: Modules permitted to import MetaTrader5. Importing is not executing -- every
#: mutating call is inventoried above -- but an unlisted importer is a new
#: surface and must be declared.
APPROVED_MT5_IMPORTERS: dict[str, str] = {
    "main.py": "Live entry point. Reads market data; closes on shutdown (above).",
    "main_production.py": "Live entry point. Reads market data and symbol_info.",
    "mt5_handler.py": "Read-only broker access: connect, quotes, bars. No mutating call.",
    "tools/export_mt5_history.py": (
        "The read-only history exporter. Separately constrained to "
        "copy_rates_*/symbol_info and asserted to reference no trade constant."
    ),
    "debug_l4.py": "Developer diagnostic script. No mutating call.",
    "stage1.py": "Developer diagnostic script. No mutating call.",
}
