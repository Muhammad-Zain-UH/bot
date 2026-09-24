# Phase 6G — Legacy Execution Reachability Audit

**Architecture audit. Documentation only.** No production code, test,
specification, guard or baseline was modified. Nothing was repaired.
`baseline_004` and `baseline_005` untouched. `LIVE_TRADING_ENABLED` remains the
literal `False`.

**Input:** Phase 6F `56f4ada`, which reported that
`order_execution.execute_order` passes no volume to a non-existent `send_order`
and deliberately left it alone.

## Labels

**OBSERVED** read from source · **MEASURED** produced by running or counting ·
**DERIVED** reasoning from stated premises · **UNKNOWN** not established.

---

# 1. Executive Summary

**The legacy MT5 branch is `DEAD`, and it is dead structurally rather than by
convention.** `order_execution.py` **never imports MetaTrader5**. It can only
reach a broker through an `mt5_handler` object passed in by its caller, and the
sole production caller passes **`mt5_handler=None`, hardcoded**
(`main_production.py:1176`). The `elif mt5_handler:` branch containing
`send_order` cannot be entered from any production path, so the missing method
can never be called.

**No path can send a live order.** Four independent mechanisms stop it, any one
of which would suffice (§5).

**But three findings qualify that, and none is a reason to relax:**

**F1 — `main.py` is ungated and can close real positions. REACHABLE-LEGACY.**
It has **no** `core.safety` import at all: no `assert_live_trading_disabled`, no
`validate_execution_environment`. It places no orders — it has no order
executor, no sizing, no `create_order` — but `close_all_positions()` calls
`mt5.order_send` directly, guarded only by `MT5_AVAILABLE`. It is a **close-only
path outside the canonical architecture**. §6.

**F2 — the two safety tests do not cover the files that carry the risk.**
`test_no_live_execution` scans only `("data", "execution", "backtest")`;
`test_no_order_send_anywhere_in_core` scans only `core/*.py`;
`test_import_arms_nothing` imports only `main_production`. **No test asserts
anything about `main.py`, and no test covers `order_execution.py` or
`risk_manager.py`.** The prohibition holds where it is tested and is untested
exactly where the `order_send` calls live. §5.4.

**F3 — `main_production` cannot start as configured.** `CONFIG["demo_mode"] =
False` declares live intent, so `resolve_execution_mode` returns `LIVE` and
`validate_execution_environment` **raises `UnsafeExecutionStateError`** at
startup. This is the Phase 0/1 guard doing its job — but the shipped
configuration is one whose only outcome is a refusal to start. §5.2.

**Answer to the brief's classification:** the legacy path is **C (dead)** for
order entry and **D (superseded)** for management, with one **A (reachable
production behaviour)** exception — `main.py`'s close-only shutdown path.

**Historical research is unaffected. Paper and live are not.** §8, §9.

---

# 2. Call Graph

## 2.1 `order_execution.execute_order` — every caller

**OBSERVED**, repository-wide:

| Caller | Line | Arguments | Status |
|---|---|---|---|
| `main_production.execute_entry_signal` | `1174` | `mt5_handler=None`, `simulation=CONFIG["demo_mode"]` | **The only production caller** |
| `order_execution.demo_order_flow` | `347` | `simulation=True` | Module self-demo |
| `order_execution` (module demo) | `375` | `simulation=True` | Module self-demo |
| `core/safety.py` | `11`, `198` | — | **Prose only**, inside docstrings/messages |
| `tests/integration/test_sizing_consistency.py` | `14` | — | **Prose only**, in a docstring |

**MEASURED: no test and no tool calls `execute_order`.**

## 2.2 The production chain, as it actually is

```
main_production.main()                                    [__main__ only]
  └─ assert_live_trading_disabled()                       GUARD 1
  └─ resolve_execution_mode(demo_mode=False) -> LIVE
  └─ validate_execution_environment(LIVE) -> RAISES       GUARD 2  <-- stops here
       ...if it did not:
  └─ analyze_entry(...)                                   [decision pipeline]
  └─ execute_entry_signal(signal, balance)
       ├─ _live_symbol_specification()   -> spec from mt5.symbol_info  [6F]
       ├─ calculate_lot_size_for_symbol(..., spec=spec)   [6F canonical sizing]
       │    └─ core.sizing.lots_for_risk                  -> lots, or 0.0
       ├─ (lots <= 0) -> log and return None              [6F]
       ├─ order_executor.create_order(position_size=lots) -> self.orders[id]
       └─ order_executor.execute_order(id, mt5_handler=None,
                                       simulation=CONFIG["demo_mode"])
            ├─ simulation=True  -> in-memory fill, random mt5_order_id   REACHABLE
            ├─ elif mt5_handler -> mt5_handler.send_order(...)           DEAD (None)
            └─ else             -> (False, "No MT5 handler provided
                                    and simulation disabled")            REACHABLE
```

**DERIVED:** the `elif mt5_handler:` branch is unreachable from production
because the argument is a literal `None` at the only call site. The missing
`send_order` method is therefore a latent defect, not an active one.

## 2.3 `main.py` — a separate, ungated entry point

```
main.py  __main__
  └─ main()
       ├─ signal.signal(SIGINT/SIGTERM, signal_handler)   [inside main(), line 812]
       ├─ <decision loop>                                 [no order placement]
       ├─ signal_handler  -> close_all_positions()        line 787
       └─ end of loop     -> close_all_positions()        line 937
                                └─ mt5.order_send(close_request)   line 770
```

**OBSERVED: `main.py` contains no `order_executor`, no `execute_order`, no
`create_order`, no `execute_entry_signal`, no sizing call and no
`position_size`.** It cannot open a position. Its only broker mutation is
closing.

---

# 3. MT5 Execution Inventory

**MEASURED** — every real order-entry or mutation call site in the repository,
excluding `venv` and the untracked worktree:

| # | Site | Operation | Guarded by | Class |
|---|---|---|---|---|
| 1 | `main.py:770` (`close_all_positions`) | `mt5.order_send` — **close** | `MT5_AVAILABLE` only | **REACHABLE-LEGACY** |
| 2 | `main_production.py:1293` (`graceful_shutdown`) | `mt5.order_send` — **close** | `MT5_AVAILABLE`; reached only from a handler installed inside `main()` | **REACHABLE-LEGACY** (unreachable in practice, §5.3) |
| 3 | `order_execution.py:169` | `mt5_handler.send_order` — **open** | caller passes `None` | **DEAD** |
| 4 | `execution/paper_broker.py` | simulated fills only | — | **REACHABLE-CANONICAL** |
| 5 | `execution/trade_adapter.py` | broker verbs: close, partial close, stop modify | — | **REACHABLE-CANONICAL** |

**No other `order_send`, `send_order`, `position_close`, pending submission or
stop modification exists.** Sites 1–3 are the entire legacy surface.

**OBSERVED — a structural fact that matters more than any guard:**
`order_execution.py` imports `json, datetime, typing, logging, enum, time,
random`. **It never imports MetaTrader5.** It has no independent route to a
broker; it can only use a handler it is given.

## 3.1 Canonical execution

**OBSERVED:** `execution/` and `backtest/` contain **no** `order_send` call.
The three textual occurrences there are docstrings stating the prohibition.
`tests/execution/test_no_live_execution.py` enforces it (7 tests, passing).

---

# 4. Volume-Flow Inventory

| Path | Volume source | Flow | Defect |
|---|---|---|---|
| **Canonical backtest** | `ReplayConfig.volume`, fixed | → `submit_market_order(volume=)` → `SimulatedPosition.volume` → adapter steps → ledger `quantity` | none |
| **Canonical adapter** | `steps_at_entry` from the fill | → broker verbs → `record_then_apply` → ledger | none |
| **Production entry (post-6F)** | `lots_for_risk` → `calculate_lot_size_for_symbol` | → `create_order(position_size=lots)` → `order["position_size"]` | **stops there** — §4.1 |
| **Legacy MT5 branch** | — | `send_order(order_type, entry_price, stop_loss, take_profit, comment)` | **volume absent entirely** — DEAD |
| **Legacy simulation branch** | — | sets `status`, `execution_price`, `mt5_order_id` | **volume ignored** — §4.2 |

## 4.1 Volume reaches the order dict and goes no further

**OBSERVED:** `execute_order` reads `self.orders[order_id]` and writes
`status`, `sent_at`, `executed_at`, `execution_price`, `mt5_order_id`. **It
never reads `order["position_size"]`.** The 6F sizing result is stored and then
unused by execution.

**DERIVED:** correct sizing is now computed and recorded, but on the legacy
execution path it has **no effect on anything**, because no branch consumes it.
That is a consequence of the branch being dead, not a second defect.

## 4.2 The simulation branch invents identity

**OBSERVED**, `order_execution.py:160`:
`order["mt5_order_id"] = random.randint(1000000, 9999999)`, plus
`if random.random() < 0.05: raise` — a 5 % artificial failure rate.

**DERIVED:** the reachable simulation branch is **non-deterministic** and
fabricates broker identity. It must never be used to produce a research result.
It has no bearing on the backtest, which does not use it.

---

# 5. Live Guard Inventory

## 5.1 `LIVE_TRADING_ENABLED`

**OBSERVED**, `core/safety.py:69`: `LIVE_TRADING_ENABLED: Final[bool] = False` —
not read from the environment, not settable through config, no override flag.
`assert_live_trading_disabled()` raises if it is anything else.

## 5.2 The startup gate — and what it currently does

**OBSERVED**, `main_production.main()`:

```
assert_live_trading_disabled()                          # GUARD 1
execution_mode = resolve_execution_mode(demo_mode=CONFIG["demo_mode"], ...)
validate_execution_environment(mode=execution_mode, ...)  # GUARD 2 -> raises on LIVE
```

**OBSERVED:** `CONFIG["demo_mode"] = False` (`main_production.py:150`, commented
*"Set to False for live trading"*). `resolve_execution_mode` returns
`ExecutionMode.LIVE` when `demo_mode` is false, and `validate_execution_environment`
raises `UnsafeExecutionStateError` for `LIVE`.

**DERIVED: `main_production.main()` refuses to start as shipped.** The guard is
working exactly as designed — it converts a configuration that once ran 39,709
cycles announcing "Mode: LIVE" while structurally unable to trade into a loud
startup refusal. The observation to record is that the **committed configuration
is one whose only outcome is that refusal**, which is safe but means the
production entry point is currently non-runnable rather than merely non-trading.

## 5.3 Shutdown-path arming

**OBSERVED:** both modules install `signal.signal(SIGINT/SIGTERM, ...)` **inside
`main()`** (`main.py:812`, `main_production.py:1375`), both gate execution behind
`if __name__ == "__main__"`, and **neither registers `atexit` at module scope**.

**DERIVED:** importing either module does not arm its close path. A backtest that
imports `main_production` for `analyze_entry` cannot trigger
`graceful_shutdown`. `tests/execution/test_import_arms_nothing.py` asserts this
against a real interpreter in a subprocess — but **only for `main_production`**.

## 5.4 Where the safety tests actually look

| Test | Scope | Covers `main.py`? | Covers `order_execution.py`? |
|---|---|---|---|
| `test_no_live_execution` | `data/`, `execution/`, `backtest/` | **No** | **No** |
| `test_no_order_send_anywhere_in_core` | `core/*.py` | **No** | **No** |
| `test_import_arms_nothing` | imports `main_production` | **No** | n/a |

**DERIVED:** the enforcement is real but **disjoint from the risk**. Every
`order_send` call in the repository sits in a file no safety test examines. The
invariant is currently maintained by the audits, not by the suite.

## 5.5 Can any path send a live order without the canonical architecture?

**No — for opening. Yes — for closing, in principle.**

| Operation | Possible outside canonical? | Why |
|---|---|---|
| **Open a position** | **No** | `order_execution` cannot reach a broker (no import); the one caller passes `None`; guards 1 and 2 stop startup; `main.py` has no order path at all |
| **Close a position** | **Yes, in principle** | `main.py:770` and `main_production.py:1293` call `mt5.order_send` directly, gated only on `MT5_AVAILABLE`, reached only by running the module as `__main__` and then shutting it down |
| **Modify a stop** | **No** | No such call exists outside `execution/` |
| **Partially close** | **No** | Legacy `CLOSE_50PCT` is **logged, never executed** (§6.3) |

**DERIVED:** the close asymmetry is real. Opening is blocked four ways; closing
is blocked only by nobody running `main.py` against a live terminal. Both
shutdown closers flatten **whatever positions the terminal holds** — they are
not restricted to positions this system opened.

---

# 6. Classification

| # | Path | Class | Notes |
|---|---|---|---|
| 1 | `execution/` + `backtest/` canonical stack | **REACHABLE-CANONICAL** | Sole exit authority; lossless ledger |
| 2 | `main.py` `close_all_positions` → `mt5.order_send` | **REACHABLE-LEGACY** | Ungated; close-only; §7 R1 |
| 3 | `main_production` `graceful_shutdown` → `mt5.order_send` | **REACHABLE-LEGACY** | Same call, but behind guards 1–2 and `__main__`; §7 R2 |
| 4 | `order_execution.execute_order` MT5 branch | **DEAD** | Caller passes `None`; module never imports MT5; target method does not exist |
| 5 | `order_execution.execute_order` simulation branch | **REACHABLE-LEGACY** | Only if `demo_mode=True`, which currently contradicts the shipped config; non-deterministic; §7 R3 |
| 6 | `order_execution.update_current_price` management | **REACHABLE-LEGACY, inert** | Touches no broker; §6.3 |
| 7 | `main_production._OPEN_TRADES` registry | **REACHABLE-LEGACY** | Duplicate state; §6.2 |
| 8 | `order_execution.OrderExecutor.orders` registry | **REACHABLE-LEGACY** | Duplicate state; §6.2 |
| 9 | `trade_manager.manage_open_trade` / `close_position` | **REACHABLE-LEGACY** | Imported by both mains; superseded by the canonical adapter (DD1 Option D) |
| 10 | `order_execution.demo_order_flow` and module demo | **TEST-ONLY** | `simulation=True`, self-demo |
| 11 | `.kilo/worktrees/alive-molasses/` (20 untracked modules) | **UNKNOWN** | Untracked; not imported by anything in the repository |

## 6.1 Duplicate execution authority — the §5 answer

**Can a legacy path independently open, close, modify or partially close outside
the canonical adapter/ledger?**

| | Legacy capability | Effect on a real broker |
|---|---|---|
| Open | `create_order` + `execute_order(simulation=True)` | **None** — in-memory only |
| Close | `close_all_positions` / `graceful_shutdown` | **Yes** — real `order_send` |
| Modify stop | `TRAIL_SL` action | **None** — logged only |
| Partial close | `CLOSE_50PCT` action | **None** — logged only |

**DERIVED:** legacy code holds a **real close capability** and only **simulated**
open/modify/partial capability. It is not a parallel trading system; it is a
parallel *bookkeeping* system with one live verb attached.

## 6.2 Duplicate state, outside the canonical ledger

**OBSERVED:** `main_production._OPEN_TRADES` (a list of dicts, persisted by
`save_active_trades`) and `OrderExecutor.self.orders` (keyed by
`XAUUSD_<timestamp>_<counter>`).

Neither carries the five canonical identities, neither passes
`record_then_apply`, and neither reaches `TradeLedger`. **A "trade" recorded
there is not a canonical trade and must never be mixed into a research result.**

## 6.3 The legacy manager is inert

**OBSERVED:** `manage_positions` calls `order_executor.update_current_price`,
which reads `self.orders` and returns `actions`. The caller **logs** each
`CLOSE_50PCT`, `TRAIL_SL` and `CLOSE_ALL` and, for `CLOSE_ALL`, removes the dict
from `_OPEN_TRADES`. **No broker call occurs anywhere in that chain.**

---

# 7. Risks

Stated for each **REACHABLE-LEGACY** path. **None is repaired here.**

**R1 — `main.py` can flatten a live account, ungated. (highest)**
Running `python main.py` with MetaTrader5 importable and a terminal attached
will, on Ctrl-C or loop exit, close **every open position on the symbol** —
including positions this system did not open. It never consults
`LIVE_TRADING_ENABLED`, and no test asserts anything about it. The exposure is
closing, not opening, so it cannot create risk — but it can destroy a position
someone else's process is managing.

**R2 — the same call in `main_production`, behind guards.**
Blocked in practice because `main()` cannot pass the startup gate with the
shipped configuration, and the handler is installed inside `main()`. The risk is
that a future change relaxing guard 2, or moving the `signal.signal` calls to
module scope, silently arms it for **every process that imports the module,
including every backtest**. `test_import_arms_nothing` guards exactly this, for
this module only.

**R3 — the simulation branch is non-deterministic and fabricates identity.**
`random.randint` for `mt5_order_id` and a 5 % `random.random()` failure rate. If
it were ever used to produce evidence, two runs would disagree. It is not on the
backtest path.

**R4 — correct sizing now exists but the legacy path ignores it.**
`execute_order` never reads `order["position_size"]`. No current consequence,
because no reachable branch sends a volume anywhere; the risk is that repairing
the MT5 branch later without wiring volume would produce orders sized by the
broker's default rather than by the contract.

**R5 — two shadow registries can be mistaken for results.**
`_OPEN_TRADES` is persisted to disk by `save_active_trades`. A file of "trades"
exists that never passed through the canonical ledger.

**R6 — the safety tests do not cover the files that contain the calls.** §5.4.

---

# 8. Phase 7 Impact — Historical Research

| Question | Answer |
|---|---|
| Does this prevent historical backtesting? | **No.** |
| Can it corrupt a backtest result? | **No**, on current evidence. |
| Can it bypass canonical sizing in a backtest? | **No.** The backtest does not size; it trades a fixed volume. |
| Can it bypass the canonical ledger in a backtest? | **No.** |

**DERIVED:** `ReplayEngine` uses `PaperBroker` and `TradeAdapter` only. It never
constructs an `OrderExecutor`, never calls `execute_order`, and never touches
`_OPEN_TRADES`. It imports `main_production` solely for `analyze_entry` and
`detect_regime`, and §5.3 establishes that importing arms nothing.

**Phase 7 is not blocked by anything in this audit.** The blockers recorded in
Phase 6C §5 — a trade-level baseline (P7), the `valid_rr` decision, DD2 and DD5
— are unchanged and unaffected.

---

# 9. Paper / Live Impact

| Question | Answer |
|---|---|
| Does this prevent **paper** execution? | **Yes, in its current form.** |
| Does this prevent **live** execution? | **Yes — four independent ways.** |

**Paper.** The only paper path is `execute_order(simulation=True)`, which
requires `demo_mode=True`, contradicting the shipped config; is
non-deterministic (§4.2); records into `self.orders` rather than the canonical
ledger; and ignores the sized volume. It is **not usable as an evidence-
producing paper path.** The canonical `PaperBroker` is the one that works — but
it is wired only into the backtest, not into `main_production`.

**Live.** Blocked by: (1) `LIVE_TRADING_ENABLED = False` with
`assert_live_trading_disabled()`; (2) `validate_execution_environment` refusing
`LIVE` at startup; (3) the only caller passing `mt5_handler=None`; (4)
`order_execution` never importing MetaTrader5 and `mt5_handler.send_order` not
existing. **Any one of these alone would prevent it.**

**The exception, restated:** closing is not covered by any of the four. §5.5.

---

# 10. Recommended Remediation Order

**Nothing is authorised by this document.** Ordered by risk reduction per unit
of change.

| # | Action | Addresses | Risk of the change |
|---|---|---|---|
| 1 | **Extend the safety tests to the files that contain the calls** — add `main.py`, `main_production.py`, `order_execution.py`, `risk_manager.py` to a scan, and extend `test_import_arms_nothing` to `main.py` | R6, and pins R1/R2 | None — tests only. **Will fail on the three existing `order_send` sites**, so it needs an explicit allow-list with recorded justification, not a silent pass |
| 2 | **Decide `main.py`'s status** — is it a second entry point, or superseded by `main_production`? | R1 | None — a decision |
| 3 | **Gate or remove `main.py`'s close path** per (2) | R1 | Behavioural: changes shutdown |
| 4 | **Reconcile `CONFIG["demo_mode"] = False`** with a guard that refuses to start on it | F3 | Behavioural: makes the entry point runnable, which is a bigger change than it looks |
| 5 | **Decide whether `order_execution` is retired or repaired** | R3, R4, R5 | Retiring it removes the only non-canonical open path |
| 6 | **If repaired: wire volume, remove `random`, route through the canonical ledger** | R3, R4, R5 | Substantial |
| 7 | **Retire `trade_manager`** | #9 | **Gated on R1 (reversal protection)** — unchanged |

**DERIVED:** item 1 is the only one with no behavioural risk and it converts
every finding here into an enforced invariant. Items 2–7 are decisions first.

---

# 11. Explicit Non-Goals

This document does **not**:

- repair `order_execution.execute_order`, wire volume into it, or add the
  missing `send_order`;
- gate, move or remove either `mt5.order_send` shutdown call;
- change any guard, `LIVE_TRADING_ENABLED`, `demo_mode`, or startup behaviour;
- extend, weaken or modify any safety test;
- retire `trade_manager`, `order_execution`, `main.py` or any legacy module;
- change sizing, strategy rules, `valid_rr`, or trade management;
- modify `baseline_004` or `baseline_005`;
- start Phase 7;
- make any profitability or performance claim. **Nothing here concerns strategy
  outcomes**; it concerns which code can reach a broker.
