# Execution Safety Surface

The enforced invariant: **every site in this repository that can change broker
state is inventoried, and the inventory is checked by the test suite.**

**This document and its inventory are not permission to trade.**
`core.safety.LIVE_TRADING_ENABLED` is the literal `False`. Listing a call makes
it *countable*, not *approved for use*.

**Phase 6H.** Test and documentation hardening only. No production code,
strategy behaviour, sizing, `valid_rr`, trade management, guard or baseline was
changed.

---

# 1. Why this exists

Phase 6G found that the safety tests and the risk were disjoint:

| Test | Scanned | Contains an `order_send`? |
|---|---|---|
| `test_no_live_execution` | `data/`, `execution/`, `backtest/`, `tools/` | No |
| `test_no_order_send_anywhere_in_core` | `core/*.py` | No |
| `test_import_arms_nothing` | imports `main_production` | n/a |
| **`main.py`** | **nothing** | **Yes** |
| **`main_production.py`** | **nothing** | **Yes** |
| **`order_execution.py`** | **nothing** | **Yes** |

The prohibition held exactly where it was tested, and was untested exactly where
the calls lived. The invariant was maintained by audits — by someone
remembering to look — rather than by the suite.

---

# 2. The invariant

> A call that can change broker state must appear in
> `tests/fixtures/broker_surface.py`. The scan fails if a call is not
> inventoried, if an inventoried call moves or disappears, if the guards
> recorded around it are gone, or if a production module imports MetaTrader5
> without being declared.

Enforced by `tests/execution/test_broker_surface.py`, which parses the AST of
**every** production file — root modules, `core/`, `data/`, `execution/`,
`backtest/`, `tools/`.

## 2.1 The allow-list is not a bypass

No file is excluded, no `# noqa` is used, no regex exception is added, and no
existing guard is weakened. The three approved entries are approved **as
recorded legacy risks**, each carrying its status. The tests assert they remain
*exactly as described* — not that they are acceptable.

Making the surface smaller on paper while leaving it unchanged in fact is the
specific failure this design rejects.

---

# 3. The inventory

**Three mutating call sites. Produced by AST scan, cross-checked against Phase 6G.**

| # | Site | Operation | Lineage | Reachable | Guards |
|---|---|---|---|---|---|
| 1 | `main.py` → `close_all_positions` → `mt5.order_send` | **CLOSE** | LEGACY | **Yes** | `MT5_AVAILABLE` only |
| 2 | `main_production.py` → `graceful_shutdown` → `mt5.order_send` | **CLOSE** | LEGACY | Yes, behind gates | `MT5_AVAILABLE` |
| 3 | `order_execution.py` → `execute_order` → `mt5_handler.send_order` | **OPEN** | LEGACY | **No — structurally dead** | `mt5_handler`, `simulation` |

**Declared MetaTrader5 importers (6):** `main.py`, `main_production.py`,
`mt5_handler.py`, `tools/export_mt5_history.py`, `debug_l4.py`, `stage1.py`.
The last two were not in the 6G inventory and were found by this scan; both are
developer diagnostics with **no mutating call**. `mt5_handler.py` is read-only:
connect, quotes, bars.

**No module in `core/`, `data/`, `execution/` or `backtest/` imports
MetaTrader5 or contains a mutating call.** Asserted directly.

---

# 4. `main.py` — close-only, ungated. **UNRESOLVED.**

**Recorded, not fixed. It is not classified as safe.**

| | |
|---|---|
| Call | `mt5.order_send(close_request)`, `main.py:770` |
| Operation | **Closes every open position on the configured symbol** |
| Scope | **Including positions this system did not open.** It reads `mt5.positions_get(symbol=...)` and closes what it finds |
| Guard | `if not MT5_AVAILABLE: return True` — **that is all** |
| `LIVE_TRADING_ENABLED` | **Does not participate.** `main.py` contains no `core.safety` import and no reference to the constant. Asserted by `test_main_py_is_recorded_as_having_no_safety_gate` |
| Startup gate | **None.** No `assert_live_trading_disabled`, no `validate_execution_environment` |
| Reached from | `signal_handler` (`:787`) and end of `main()` (`:937`) |
| Armed by import? | **No.** Handlers install inside `main()`; execution is behind `if __name__ == "__main__"`; no module-scope `atexit`. Asserted in a subprocess |
| Can it open? | **No.** No order executor, no sizing, no `create_order`, no `execute_entry_signal` |

**Why it is not guarded here.** Adding a guard purely to satisfy a test would
answer, by accident, a question that is open: *is `main.py` a second entry point
or is it superseded by `main_production`?* That is Phase 6G remediation item 2
and belongs to review. A guard added now would also make the surface look
resolved while leaving the question unanswered.

**Status: TEMPORARY.** Phase 6G risk **R1**, the highest recorded.

---

# 5. `main_production.py` — close-only, gated. **UNRESOLVED.**

| | |
|---|---|
| Call | `mt5.order_send(close_request)`, `main_production.py:1293` |
| Operation | Same as §4: closes what the terminal holds, **not only canonical positions** |
| Guard at the call | `if MT5_AVAILABLE:` |
| `__main__` requirement | **Yes.** Reached only via a handler installed inside `main()`, and `main()` runs only under `__main__` |
| `LIVE_TRADING_ENABLED` | **Does not gate this call directly.** It gates startup: `main()` calls `assert_live_trading_disabled()`, then `resolve_execution_mode()`, then `validate_execution_environment()` |
| Effective reachability | **Blocked in practice.** `CONFIG["demo_mode"] = False` ⇒ mode `LIVE` ⇒ `validate_execution_environment` raises `UnsafeExecutionStateError` ⇒ startup refused, so the handler is never installed |
| Armed by import? | **No** — same subprocess assertion as §4 |

**The distinction from `main.py` is the whole point:** the same operation, one
behind a startup gate and one behind nothing. Both are inventoried so the
asymmetry is visible.

**Status: TEMPORARY.** Phase 6G risk **R2**.

---

# 6. `order_execution.execute_order` — structurally dead

**Dead by structure, not by convention**, and the structure is asserted:

1. **`order_execution.py` never imports MetaTrader5.** It can only reach a
   broker through an `mt5_handler` its caller supplies.
   → `test_the_dead_open_path_is_still_dead`
2. **The sole production caller passes `mt5_handler=None`, a literal.** The test
   parses the call and asserts the keyword is `ast.Constant(None)`, so supplying
   a handler fails immediately.
3. `mt5_handler.py` defines no `send_order`, so even a handler would raise.
4. It passes **no volume**, so canonical sizing would not reach the broker.

**Status: TEMPORARY.** Phase 6G risks **R3**, **R4**. Listed rather than deleted
so that arming it fails the inventory instead of quietly enabling an unsized
order.

---

# 7. The five invariants

| | Invariant | Enforced by |
|---|---|---|
| **A** | Importing a production module cannot submit an order | `ImportingProductionArmsNothing` — subprocess probes of **both** `main` and `main_production`, asserting neither replaced the SIGINT/SIGTERM handlers. 6G found the existing test covered only `main_production` |
| **B** | Historical replay cannot reach broker execution | `HistoricalReplayCannotReachABroker` — no mutating call in `core/`/`data/`/`execution/`/`backtest/`, and no reference to `OrderExecutor`, `execute_order`, `_OPEN_TRADES` or `order_execution` anywhere in `execution/`/`backtest/` |
| **C** | Canonical entry cannot bypass canonical sizing | `CanonicalEntryCannotBypassSizing` — `execute_entry_signal` must call `calculate_lot_size_for_symbol` **with a `spec=`**, and must contain **no division at all**, which is how the removed second formula was written |
| **D** | A new raw broker call needs an inventory update | `InventoryIsComplete` — unlisted calls fail; the count is pinned at exactly three |
| **E** | Legacy close-only paths are visible, not accidentally invisible | `LegacyClosePathsAreVisible` — both closers declared LEGACY, reachable and TEMPORARY; the single opener asserted **not** reachable |

## 7.1 The tests were verified to fail

A scanner that only ever passes proves nothing. Four violations were injected
and each was caught, then reverted (`main.py` and `main_production.py`
byte-identical to `HEAD` afterwards):

| Injected | Caught by |
|---|---|
| A new file with `mt5.order_send` and an MT5 import | `test_every_mutating_call_is_inventoried`, `test_the_count_is_exactly_three`, `test_no_undeclared_importer` |
| `mt5_handler=None` → `mt5_handler=object()` | `test_the_dead_open_path_is_still_dead` |
| `MT5_AVAILABLE` guard removed from `close_all_positions` | `test_recorded_guards_are_still_present` |

---

# 8. What this does **not** do

- **Does not make the system live-ready.** Live execution remains blocked by
  `LIVE_TRADING_ENABLED = False`, the startup refusal, the `None` handler, and
  the absent `send_order`.
- **Does not resolve the paper blocker.** The only paper path needs
  `demo_mode=True`, is non-deterministic (`random.randint` identities, a 5 %
  injected failure rate), records outside the canonical ledger and ignores the
  sized volume. The canonical `PaperBroker` remains wired only into the backtest.
- **Does not change historical performance semantics.** No strategy rule,
  parameter, sizing, `valid_rr`, target/stop semantics or trade management was
  touched. `baseline_004` and `baseline_005` are untouched. R1 fingerprints are
  unchanged.
- **Does not resolve `main.py`'s status, `order_execution`'s fate, the
  `demo_mode` contradiction, or the `trade_manager` retirement.** Those are
  Phase 6G remediation items 2–7 and remain decisions for review.
- **Does not weaken any guard**, exclude any file, or add any exception.

**What it does do:** every finding in Phase 6G is now an enforced invariant
rather than a fact someone has to remember. A change that would have silently
widened the broker surface now fails the suite.
