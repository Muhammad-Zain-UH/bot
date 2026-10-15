# Phase 4B — Trade Management Integration Design

**Architecture investigation and design only.** No production Python, test,
baseline or specification is changed by this document. The canonical model is
**not** wired into any execution path. `baseline_004` remains **FROZEN**.

**Preceding state, verified at `5401d0c`:**

| Fact | Evidence |
|---|---|
| `core/trade_model.py` exists and is pure | [REPO] |
| Canonical contract 88/88, core constraints 8/8 | [MEASURED] |
| Full suite 752 tests, 2 failures, 0 errors, 0 skipped | [MEASURED] |
| **No execution path imports or calls `core.trade_model`** | [REPO] AST sweep, §B |

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `5401d0c` |
| **[MEASURED]** | Established by running existing code read-only |
| **[DECISION]** | A design choice proposed here, for review — **not** implemented |
| **[UNRESOLVED]** | Cannot be settled from existing evidence; stated, not forced |

---

# A. Current Lifecycle Map

Three paths exist. Each is traced from entry decision to statistics. "Reachable"
means reachable **in the shipped configuration**, not merely present.

## A.1 Path 1 — `main_production.py` → `order_execution`

| # | Caller | Callee | File · function | Input | Output | State mutation | Broker | Reachable | Conflicts with canonical |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `main()` | `analyze_entry` | `main_production.py:1424` | frames | `entry_signal` dict | — | none | **Yes** | — |
| 2 | `main()` | `execute_entry_signal` | `main_production.py:1092` | `entry_signal` (**no balance**, so 10 000 is assumed) | `order_id` or `None` | — | none | **Yes** | Sizing basis is fictional (F4); orthogonal to this phase |
| 3 | `execute_entry_signal` | `calculate_lot_size_for_symbol` | `risk_manager.py:5` | balance, risk %, entry, stop | lots | — | none | **Yes** | Quantity arrives in **lots**; canonical wants **steps** (§E.11) |
| 4 | `execute_entry_signal` | `OrderExecutor.create_order` | `order_execution.py:64` | side, entry, SL, TP, size | order dict with `exit_1_1/1_2/1_3` | `self.orders[id]` | none | **Yes** | Milestone levels precomputed and **direction-blind**; canonical computes them direction-aware from the fill (§C) |
| 5 | `execute_entry_signal` | `OrderExecutor.execute_order` | `order_execution.py:127` | `mt5_handler=None`, `simulation=CONFIG["demo_mode"]` = `False` | `(False, "No MT5 handler provided and simulation disabled")` | none | none | **Yes, but always fails** | **Nothing ever fills.** Canonical geometry is frozen at a fill that never happens |
| 6 | `execute_entry_signal` | `_OPEN_TRADES.append` | `main_production.py:1146` | trade dict (`"state": None`) | — | appends | none | **No — unreachable** | Position creation never occurs |
| 7 | `main()` | `manage_positions` | `main_production.py:1431` | **`{}`** | `None` | rebuilds `_OPEN_TRADES` | none | **Yes** | Called with an empty price map |
| 8 | `manage_positions` | *price lookup* | `:1175` | `current_prices.get(trade_id, entry_price)` | **always `entry_price`** | — | none | **Yes** | **No price ever moves.** Canonical needs a real `PriceObservation` (§E.4) |
| 9 | `manage_positions` | `update_current_price` | `order_execution.py:212` | order id, price | actions list | `order["status"]`, `exit_*.triggered` | none | Only if `_OPEN_TRADES` non-empty | No stop check; status doubles as milestone marker |
| 10 | `manage_positions` | action handler | `:1179-1185` | action dicts | log lines | `closed_trades` on `CLOSE_ALL` only | none | Same | `CLOSE_50PCT` and `TRAIL_SL` **change nothing**; canonical requires a broker request and a confirmed result |
| 11 | `main()` | `save_state` → `save_active_trades` | `:1196` | `_OPEN_TRADES` | file | disk | none | Yes | Persists dicts; `TradeState` persistence undefined (§O I2) |
| 12 | `restore_state` | `load_active_trades` | `:1207` | — | `_OPEN_TRADES` | replaces list | none | Yes | Restored trades have **no executor entry**, so `update_current_price` returns `{"status": "error"}` — management is impossible after a restart |
| 13 | `main()` | `shutdown_mgr.shutdown` | `:1254` | `_OPEN_TRADES` | bool | — | none | Yes | Preserves trades; does not close them. Canonical `MANUAL` closure has no producer here |
| 14 | — | `log_closed_trade` / `save_closed_trade` | imported `:78`, `:89` | — | — | — | — | **No — never called** | Layer 10 unreachable: **no closed trade is ever recorded** |

**[REPO] Net effect of path 1:** a decision can be taken and an order object
built, and nothing after step 5 happens. Statistics are never produced.

## A.2 Path 2 — `main.py` → `trade_manager`

| # | Caller | Callee | File · function | Input | Output | State mutation | Broker | Reachable | Conflicts with canonical |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `main()` | `analyze_entry` | `main.py:866` | frames | analysis | — | none | Yes | — |
| 2 | `main()` | `open_trades.append` | `main.py:898-908` | analysis | trade dict (`"state": None`) | appends | **none** | **Yes** | Creates a **record**, never an order. No sizing, no fill, so there is no actual fill price for canonical R |
| 3 | `main()` | `manage_positions` | `main.py:914` | `open_trades`, `{"spread": 0.5}` | list | per-trade | none | Yes | Mock price map |
| 4 | `manage_positions` | *price lookup* | `main.py:716` | `current_prices.get(trade_id, entry_price)` | **always `entry_price`** | — | none | Yes | Same defect as path 1 step 8 |
| 5 | `manage_positions` | `manage_open_trade` | `trade_manager.py:337` | prices, `original_stop_loss`, `trade_state` | result dict | writes `trade["state"]` | none | Yes | Full milestone ladder runs **in-process with no broker**; canonical requires broker confirmation before any state is believed |
| 6 | `main()` | closure filter | `main.py:917-918` | `status` | two lists | drops trades | none | Yes | `CLOSED_SL` matches **neither** filter and vanishes |
| 7 | — | `close_position`, `log_closed_trade` | imported `:47-48` | — | — | — | — | **No — never called** | Layer 10 unreachable here too |
| 8 | `signal_handler` | `close_all_positions` | `main.py:747` | — | bool | — | **`mt5.order_send`** | Only on signal | The only live-order call site in this path; out of scope and unchanged |

## A.3 Path 3 — Backtest / replay (`PaperBroker`)

| # | Caller | Callee | File · function | Input | Output | State mutation | Broker | Reachable | Conflicts with canonical |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `ReplayEngine.run` | `PaperBroker.on_bar` | `replay_engine.py:260` | bar, bar_time | list of **closed** positions | fills pending, advances positions, closes them | paper | **Yes** | **`on_bar` owns exit semantics the canonical model now also owns** (§N R1) |
| 2 | `on_bar` | `_fill_pending` | `paper_broker.py:328` | bar | opened positions | `PendingOrder.mark_filled`, opens position | paper | Yes | Fill price = limit, or bar open when gapped. Canonical agrees; this is the hand-off point (§E.2) |
| 3 | `on_bar` | `resolve_intrabar` | `paper_broker.py:449` | bar, stop, target, policy | resolution | — | — | Yes | Decides stop-vs-target; canonical §11.2 decides the same question. **Two owners** |
| 4 | `on_bar` | `_close` | `paper_broker.py:546` | raw exit price, state, reason | — | sets `exit_price/time/reason`, moves to closed | paper | Yes | Closure is immediate and unconditional. Canonical requires request → confirmation (§C) |
| 5 | `ReplayEngine.run` | `trade_from_position` | `ledger.py:196` | closed position | `SimulatedTrade` | ledger append | — | Yes | **One position → exactly one exit.** A canonical 1R partial produces **two** (§N R1) |
| 6 | `ReplayEngine._submit` | `submit_market_order` / `submit_limit_order` | `paper_broker.py:125` / `:297` | intent | `SimulatedFill` / `PendingOrder` | opens or rests | paper | Yes | The natural creation point for `TradeState` (§E.2) |
| 7 | `ReplayEngine.run` | `close_all_at_end_of_data` | `paper_broker.py:515` | final bar | closed positions | closes all | paper | Yes | Maps to canonical `END_OF_DATA`; the adapter must emit it, not the domain (§G) |

**[REPO]** The backtest is the **only** path where a position is created,
managed and recorded end to end.

---

# B. Active Call Graph

Sweep by symbol across every `.py` outside `venv/`, `.kilo/` and `__pycache__`.

| Symbol | A — reachable production | B — unreachable / dead | C — tests only | D — historical / docs |
|---|---|---|---|---|
| `trade_manager` (module) | — | imported at `main.py:47`, `main_production.py:77` | contract test (as a **banned** string), `test_week3_verification.py` | DD1 docs |
| `manage_open_trade` | `main.py:718` **only** | `main_production.py:77` import, never called | `test_week3_verification.py` | — |
| `order_execution` (module) | `main_production.py:71` import | — | `tests/backtest/test_determinism.py` (asserts the simulator cannot reach it) | `core/safety.py` docstrings `:11,198,212` |
| `OrderExecutor` | `main_production.py:393` instantiation | — | — | — |
| `update_current_price` | `main_production.py:1177` | — | — | — |
| `create_order` | `main_production.py:1111` | — | — | `core/types.py` docstring |
| `execute_order` | `main_production.py:1126` — **always returns False** | the success branch below it | — | `core/safety.py:198` |
| `manage_positions` | `main_production.py:1431`, `main.py:914` | — | — | — |
| `_OPEN_TRADES` | 15 references in `main_production.py` | the `append` at `:1146` is unreachable (see §A.1 step 5) | — | — |
| `CLOSE_50PCT` | emitted `order_execution.py:240`, handled `main_production.py:1179` (log only) | — | — | — |
| `TRAIL_SL` | emitted `order_execution.py:256` and `trade_manager.py:434`, handled `main_production.py:1181` (log only) | — | — | — |
| `CLOSE_ALL` | emitted `trade_manager.py:388/452`, `order_execution.py:274`; handled `main_production.py:1183` | — | — | — |
| `close_position` | — | imported `main.py:47`, `main_production.py:77`, never called | `test_week3_verification.py` | **Name collision:** `entry_engine.py` (15×) and `strategy_engine.py` (8×) use `close_position` as a *wick-analysis field*, not this function |
| `core.trade_model` | **none** | — | contract test | this document |

**[REPO] Two findings worth stating plainly.** `core.trade_model` has zero
production references, so integration is purely additive at this point. And the
`close_position` collision means a naive grep overstates the legacy manager's
reach by 23 hits.

---

# C. Old Manager Comparison

Canonical column cites the specification. Nothing is labelled correct or
incorrect unless the specification establishes it.

| Behaviour | `trade_manager` | `order_execution` + `main_production` | Canonical (`core.trade_model`) | Disappears when canonical is authoritative |
|---|---|---|---|---|
| **1R** | `entry ± risk`, per call, direction-aware | `entry + risk` at creation, **direction-blind** | `m1r` frozen at creation, direction-aware (spec 6.1) | The SELL inversion disappears |
| **Partial close** | `PARTIAL_CLOSE_50PCT`, fraction 1.0 → 0.5 | `CLOSE_50PCT` action, **quantity unchanged**, log only | `PartialCloseRequest(floor(steps/2))`, applied only on `PartialCloseFilled` (spec 5.2) | The fraction representation and the log-only partial both disappear |
| **Breakeven** | stop → entry at 1R | none at 1R | `stop_state_intended = BREAKEVEN`, confirmed separately (spec 7.3) | Immediate unconfirmed stop movement disappears |
| **2R** | `entry ± 2×original_risk`, gated on 1R | `entry + 2×risk`, direction-blind | `m2r` frozen, ascending processing (spec 6.4) | — |
| **Locked 1R** | stop → `entry + 1R` | stop → `entry` (locks nothing), never applied | `LOCKED_1R = entry ± R` (spec 7.1) | `order_execution`'s breakeven-at-2R meaning disappears |
| **Target** | exit at the **TP level** | exit at the **observed price** | `CloseRequest(requested_level, observed_reference)`; the adapter prices it (spec 11.1b) | Both pricing behaviours disappear into the adapter |
| **Stop** | explicit check, first, returns | **absent** | Adverse-first, snapshot of the **confirmed** stop (spec 11.1) | `order_execution`'s inability to close a loser disappears |
| **Reversal protection** | `CLOSE_BREAKEVEN_PROTECTION` within $2.00 | none | **Not implemented — R1 [UNRESOLVED]** | **`trade_manager`'s reversal protection disappears and is not replaced.** Explicitly flagged (§N R4) |
| **Gap handling** | exit at the level regardless of gap | observed price only | `observed_reference = bar open when gapped`, adapter prices it (spec 12) | Reporting a fill at an untraded price disappears |
| **Quantity** | fraction, no link to lots | lots, never changed | integer steps, lots derived at the boundary (spec 5.1) | Both representations disappear |
| **Close confirmation** | immediate, in-process | immediate on TP | `CLOSE_REQUESTED` → broker → `CloseFilled` → `CLOSED` (spec 11.1a) | Optimistic closure disappears |
| **Position removal** | `main.py` filter drops `CLOSED_SL` silently | `main_production` removes on `CLOSE_ALL` | Removal only after confirmed closure (§E.14) | The silent drop disappears |
| **Retry / idempotency** | milestone flags; stop check **not** gated on size | `triggered` flags + status gate | consumed set + monotonic evaluation time + terminal `CLOSED` (spec 15) | Acting on an already-closed position disappears |

---

# D. Canonical Integration Boundary

**[DECISION]** The smallest boundary that keeps `core` pure:

```
  STRATEGY  (entry_engine, L1-L8)                        unchanged
      │  entry_signal / PendingOrderIntent
      ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  TRADE MANAGEMENT ADAPTER          << the only new component >>│
  │                                                              │
  │  owns:  TradeState per position, the mapping to broker ids,  │
  │         PriceObservation construction, event translation,    │
  │         cost model invocation, result plumbing               │
  └───────────┬──────────────────────────────────┬───────────────┘
              │ pure calls                       │ broker calls
              ▼                                  ▼
   core.trade_model                    execution/paper_broker   (replay)
   evaluate / apply_broker_result      live broker adapter      (later)
   open_position / may_open_position
```

**[DECISION] The adapter is responsible for:** broker requests; executable
prices via the cost model; fills; confirmations and rejections; MT5-specific
behaviour; lots ↔ steps conversion; building `PriceObservation`; translating
domain events into broker actions; feeding results into `apply_broker_result`.

**[DECISION] The adapter is *not* responsible for:** milestone levels, R, stop
progression, ordering, idempotency, or any decision about what *should* happen.
Those belong to the domain and must not be duplicated (spec 24 MUST NOT 8).

**[DECISION]** Proposed location: a new `execution/trade_adapter.py`. It may
import `core.trade_model` and `execution/*`; `core.trade_model` must never
import it. The existing `tests/core/test_core_constraints.py` enforces the
direction automatically, since a `core` → `execution` import would be an
undeclared dependency.

---

# E. Adapter Design — the sixteen questions

**Proposed. Not implemented.**

| # | Question | Proposed answer | Class |
|---|---|---|---|
| 1 | Who owns `TradeState`? | The adapter, in a `dict[position_id, TradeState]`. The domain owns the *rules*; someone must own the *instances*, and it cannot be `core` because that would need a registry with lifetime | [DECISION] |
| 2 | Where is `TradeState` created after a fill? | At the fill, not the decision: in the adapter's `on_fill`, from `SimulatedFill.entry_price` (paper/replay) or the broker's reported fill (live). Market and limit fills share one code path (spec 13) | [DECISION] |
| 3 | Who calls `evaluate()`? | The adapter, once per position per observation. In replay, driven from `on_bar`; in live, from the price-polling loop | [DECISION] |
| 4 | How is a `PriceObservation` constructed? | Replay: directly from the bar's OHLC and open time. Live: **no source exists today** — `manage_positions({})` supplies nothing (§A.1 step 8). A price feed must be built; that is not adapter work | [DECISION] + [UNRESOLVED] §O I3 |
| 5 | `PartialCloseRequest` → broker | `steps_to_lots(steps, spec.volume_step)`, then a partial-close call. **`PaperBroker` cannot do this today** (§N R1) | [DECISION] |
| 6 | `StopModifyRequest` → broker | A stop-modification call. In paper, mutate `SimulatedPosition.stop_loss` and confirm synchronously | [DECISION] |
| 7 | `CloseRequest` → broker | The adapter converts `observed_reference` into an executable price via `FillModel.exit_price`, then closes the remaining quantity | [DECISION] |
| 8 | How does the result return? | Every broker call returns one of the eight result types; the adapter folds each through `apply_broker_result` **before** the next `evaluate` | [DECISION] |
| 9 | Where is the executable price determined? | The adapter, via `execution/fills.py` — never the domain (spec 11.1b) | [REPO] + [DECISION] |
| 10 | Where is the actual fill recorded? | `CloseFilled.fill_price` → `TradeState.closure_fill_price`, and into the ledger record | [DECISION] |
| 11 | Quantity reconciliation | The adapter compares the broker's remaining quantity against `steps_remaining` and sends `QuantityReconciled` on divergence. Conversion uses `SymbolSpecification.volume_step`, never a literal | [DECISION] |
| 12 | Where is idempotency state persisted? | `TradeState` is the idempotency state. Replay needs no persistence. Live needs a serialisation format — enums, `frozenset`, aware datetimes — which does not exist | [DECISION] + [UNRESOLVED] §O I2 |
| 13 | How are pending broker operations represented? | `pending_close_reason` covers an outstanding close. An outstanding *partial* or *stop modify* is represented by the gap between intended and confirmed state, re-requested each evaluation | [DECISION] |
| 14 | How is a `CLOSED` position removed? | Only when `state.is_closed`, i.e. only after `CloseFilled` or `PositionGone`. The adapter then emits the ledger record and drops the entry | [DECISION] |
| 15 | How does `PaperBroker` implement the same contract? | Through the same adapter interface, with synchronous always-successful results — except where the broker genuinely cannot comply (capacity, unsupported partial) | [DECISION] |
| 16 | How does replay avoid a second implementation? | `PaperBroker.on_bar` stops deciding exits and becomes price delivery plus order execution; the domain decides. This is a **behavioural change to the backtest** (§I, §N R2) | [DECISION] |

---

# F. State Ownership

| State | Owner today | Owner after integration | Note |
|---|---|---|---|
| Milestone flags | `order["exit_*"]["triggered"]` / `trade_state` | `TradeState.milestones_consumed` | Single source |
| Stop position | `order["stop_loss"]` (never written) / `trade_state["current_sl"]` | `TradeState.stop_state_confirmed` + broker | Two fields, intended and confirmed |
| Quantity | lots in the order dict / fraction in `trade_state` | `TradeState.steps_remaining`; lots only at the boundary | — |
| Position identity | `order_id` string | broker id ↔ `TradeState` map in the adapter | — |
| Open-position collection | `_OPEN_TRADES` list of dicts / `PaperBroker._open` | adapter registry, authoritative | `_OPEN_TRADES` becomes a projection, or is retired |
| Closed-trade record | never written (production) / `SimulatedTrade` | ledger record built by the adapter | Production gains statistics it has never had |
| Ambiguity flag | `SimulatedPosition.was_ambiguous_exit` | `EvaluationResult.ambiguous`, carried to the record | Domain decides, adapter records |

---

# G. Event Translation

| Domain event | Adapter action | Broker result | Fed back as |
|---|---|---|---|
| `PartialCloseRequest(steps)` | close `steps_to_lots(steps)` at market | filled / partially filled / rejected | `PartialCloseFilled(steps_closed)` / `PartialCloseRejected(reason)` |
| `StopModifyRequest(stop_price, to_state)` | modify the stop | confirmed / rejected | `StopModifyConfirmed(stop_price, to_state)` / `StopModifyRejected(reason)` |
| `CloseRequest(reason, requested_level, observed_reference, steps)` | price the reference via the cost model, close the remainder | filled / rejected | `CloseFilled(reason, fill_price, steps_closed)` / `CloseRejected(reason)` |
| *(no event)* — broker-initiated | reconciliation poll | quantity differs | `QuantityReconciled(steps_remaining)` |
| *(no event)* — broker-initiated | reconciliation poll | position absent | `PositionGone()` |
| *(no event)* — replay-initiated | end of dataset | — | `CloseFilled(reason=END_OF_DATA, ...)` — the **adapter** supplies this reason, since the domain has no concept of a dataset |

---

# H. PaperBroker Integration Design

**[DECISION]** `PaperBroker` keeps: the fill model, the spec, capacity,
pending-order lifecycle, and gap-aware fill pricing. It **loses** exit
decision-making.

**[REPO] What must change, and why it is not adapter-only:**

1. `SimulatedPosition.volume` is fixed at open and `_close` closes the whole
   position. There is **no partial close**. A canonical 1R partial cannot be
   expressed.
2. `on_bar` currently calls `resolve_intrabar` and `_close` itself. Under the
   canonical model the domain decides, so `on_bar` would have to deliver the
   bar and execute instructions rather than take decisions.

**[DECISION]** Proposed shape, for review:

```
  on_bar(bar, bar_time):
      fill pending orders            (unchanged)
      hand the bar to the adapter    (new)
  adapter.on_bar(bar, bar_time):
      observation = PriceObservation(...)
      for each open position:
          result = evaluate(state, observation)
          for event in result.events:
              broker_result = broker.apply(event)      # new broker verbs
              state = apply_broker_result(state, broker_result)
          if state.is_closed: emit ledger record(s)
```

**[UNRESOLVED]** Whether `IntrabarPolicy` survives as a *broker* concept or
moves wholly into the domain. The domain already fixes adverse-first; the
policy's `OPTIMISTIC` and `MIDPOINT_HEURISTIC` variants have no canonical
counterpart. See §O I6.

---

# I. Backtest Integration Design

**[REPO] The blocking issue.** `SimulatedTrade` carries exactly one
`exit_time`, one `exit_price`, one `exit_reason` and one `quantity`
(`backtest/ledger.py:100-125`). A canonical position closes in **two** events —
half at 1R, the remainder at the target or stop — at different times and
prices. The current ledger cannot represent one canonical position.

**[UNRESOLVED] §O I1.** Three shapes, none implied by the specification:

| Option | Consequence |
|---|---|
| One ledger record per **fill**, linked by position id | Trade counts change meaning: one position yields two records. Every existing statistic that counts rows changes |
| One record per **position**, with a list of exits | Record shape changes; R-multiple and P&L become weighted sums |
| A partial modelled as **two positions** | Breaks position-id continuity, and R would be recomputed for the second, which the specification forbids |

**[DECISION]** Whatever is chosen, the determinism machinery is unaffected in
kind: `decisions_fingerprint` covers the decision stream and is independent of
trade management, and a management-event fingerprint (spec 18.3) would be added
alongside it.

---

# J. Test Plan — written before wiring

All new tests live under `tests/trade_management/` or `tests/integration/`.

## J.1 Adapter integration tests

| # | Test | Asserts |
|---|---|---|
| 1 | Market fill creates a `TradeState` | Created from `SimulatedFill.entry_price`, not the signal price |
| 2 | LIMIT_FVG fill creates a `TradeState` | Same path; geometry frozen at the fill (spec 13) |
| 3 | Fill price differs from intended | The state's entry is the fill, and the intended price appears nowhere in the geometry |
| 4 | R from the actual fill | `r == abs(fill − original stop)` |
| 5 | Target recomputed from the actual fill | `reward / r == tp_ratio` exactly |
| 6 | 1R event becomes a broker request | Exactly one partial-close call, for `floor(steps/2)` lots |
| 7 | Partial-close confirmation | `steps_remaining` falls only after `PartialCloseFilled` |
| 8 | Partial-close rejection | Quantity unchanged, anomaly recorded, stop still promoted |
| 9 | Stop-modify request | One call carrying the breakeven price |
| 10 | Stop-modify confirmation | `stop_state_confirmed` advances; no further request |
| 11 | Stop-modify rejection | Confirmed does not advance; re-requested at the same price |
| 12 | 2R behaviour | Stop to `entry ± R`; no second partial |
| 13 | Target close request | `requested_level` and `observed_reference` present; **no executable price in the event** |
| 14 | Stop close request | Same, with reason `STOP` |
| 15 | Close confirmation | `CLOSED` only here; ledger record emitted |
| 16 | Close rejection | Still `OPEN`, still counted, re-requested next observation |
| 17 | Duplicate broker result | Idempotent; no double decrement |
| 18 | Pending close blocks evaluation | No milestone processed while a close is outstanding |
| 19 | Multiple positions | Independent states; no shared mutation |
| 20 | BUY and SELL | Mirror-image levels and requests |
| 21 | Gap behaviour | `observed_reference` is the bar open; the adapter's executable price differs from the requested level |
| 22 | Quantity step handling | Lots derived via `volume_step`; a one-step position sends no partial |
| 23 | Removal only after confirmed close | The registry still holds the position while a close is outstanding |

## J.2 Existing tests — keep, or retire later

| Test | Disposition |
|---|---|
| `tests/trade_management/test_canonical_trade_management_contract.py` | **Keep.** The domain contract |
| `tests/execution/test_pending_limit_orders.py` | **Keep.** Pending lifecycle is unchanged by this phase |
| `tests/execution/test_paper_broker.py` | **Keep, expect edits** when `on_bar` stops deciding exits |
| `tests/integration/test_r1_same_bar_regression.py` | **Keep as a regression on R1 semantics**, but its pinned ledger fingerprints will change once partials exist. Must be re-pinned deliberately, with the change attributed (§N R3) |
| `tests/integration/test_limit_fvg_semantics.py` | **Keep** |
| `tests/backtest/test_determinism.py` | **Keep.** Still forbids the simulator reaching `order_execution` |
| `test_week3_verification.py` (repo root, not collected) | **Retire eventually** — it verifies the superseded manager. Not part of the suite, so retirement is documentation only |
| Any future test of `update_current_price` milestone behaviour | **Would be superseded**; none exists today |

**[REPO]** No existing test asserts the legacy managers' milestone behaviour
inside `tests/`, so retirement is unusually cheap: the superseded behaviour is
pinned only by the uncollected root script.

---

# K. Migration Sequence

**Proposed. Nothing is authorised by this document.**

| Step | Content | Gate |
|---|---|---|
| 0 | **This document** reviewed | — |
| 1 | Resolve §O I1 (ledger/partial representation) | Strategy owner decision |
| 2 | Write adapter integration tests (§J.1) against the not-yet-existing adapter, in the skip-plus-gate pattern already used | Suite stays usable |
| 3 | Implement `execution/trade_adapter.py` | §J.1 green |
| 4 | Extend `PaperBroker` with partial close and stop modification | `tests/execution/test_paper_broker.py` extended |
| 5 | Switch `ReplayEngine` to drive the domain through the adapter | Decision fingerprint **byte-identical**; trade outcomes change and are attributed |
| 6 | **New canonical baseline** on real XAUUSD, under a new id | `baseline_004` untouched (§ below) |
| 7 | Live wiring: price feed, `execute_order` repair, entry-point ownership (DD2) | Separate phase; `LIVE_TRADING_ENABLED` stays `False` |
| 8 | Retire the superseded managers | Only after 5 and 6 |

**Baseline protection.** `baseline_004` is **FROZEN** and is not rewritten.
**[MEASURED]** It produced **zero trades**, so any future run that produces
trades is **not an improvement** — it is a different executable model, and must
be compared like-for-like against a new canonical baseline. No performance or
profitability claim is made anywhere in this plan.

---

# L. Files That Will Eventually Change

**None in this phase.** Listed for planning only.

| File | Expected change | Step |
|---|---|---|
| `execution/trade_adapter.py` | **New** | 3 |
| `execution/paper_broker.py` | Partial close, stop modification; `on_bar` stops deciding exits | 4, 5 |
| `execution/broker.py` | `SimulatedPosition` gains mutable remaining quantity | 4 |
| `backtest/ledger.py` | Partial-exit representation, per §O I1 | 1, 5 |
| `backtest/replay_engine.py` | Drives the adapter | 5 |
| `tests/execution/test_paper_broker.py` | Extended for new verbs | 4 |
| `tests/integration/test_r1_same_bar_regression.py` | Fingerprints re-pinned deliberately | 5 |
| `main_production.py`, `main.py` | Live wiring, entry-point ownership | 7 |
| `trade_manager.py`, `order_execution.py` | Retirement | 8 |

# M. Files That Must Remain Untouched

| File | Why |
|---|---|
| `core/trade_model.py` | The canonical model is settled; integration must not bend it |
| `docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md` | Source of truth |
| `tests/trade_management/test_canonical_trade_management_contract.py` | The contract |
| `entry_engine.py` | Strategy is out of scope |
| `risk_manager.py` | Sizing is DD11/F4, independent |
| `backtest/baseline.py` artifacts for `baseline_004` | **FROZEN** |
| `core/safety.py` | `LIVE_TRADING_ENABLED` stays `False` |

---

# N. Risks

| # | Risk | Why it matters | Mitigation |
|---|---|---|---|
| R1 | **The backtest cannot express a partial exit** | `SimulatedPosition` has one volume and `SimulatedTrade` one exit. Integration is therefore **not** adapter-only, contrary to the natural assumption | Resolve §O I1 before any code |
| R2 | **Two owners of exit semantics during migration** | `on_bar` decides exits today; the domain decides them after. Running both would double-close | Step 5 must move the decision in one commit, not incrementally |
| R3 | **Pinned fingerprints will change** | `test_r1_same_bar_regression` pins ledger hashes; partials change trade records | Re-pin deliberately in the same commit, with before/after recorded |
| R4 | **Reversal protection silently disappears** | `trade_manager` has it, canonical does not (R1 unresolved). Retiring the old manager removes a behaviour without a decision | Record it at retirement; R1 must be answered first if it is wanted |
| R5 | **Live has no price feed** | `manage_positions({})` supplies nothing; management has never run on real prices | Step 7 is a separate phase with its own design |
| R6 | **Restart orphans positions** | Executor state is in memory; restored trades are unmanageable today | `TradeState` persistence, §O I2 |
| R7 | **Trade-count semantics change** | If one position yields two ledger rows, every row-counting statistic changes meaning | Define in §O I1; never compare across the change |

---

# O. Open Questions

| # | Question | Blocks | Class |
|---|---|---|---|
| I1 | **How is a partial exit represented in the ledger and the position?** Per-fill rows, one row with several exits, or two positions | Steps 1, 4, 5 — the whole backtest integration | **[UNRESOLVED]** |
| I2 | `TradeState` persistence format for live restart | Step 7 | **[UNRESOLVED]** |
| I3 | Where does a live `PriceObservation` come from, and at what cadence? | Step 7 | **[UNRESOLVED]** |
| I4 | Does `SimulatedPosition` remain the backtest's record of truth, or become a projection of `TradeState`? | Steps 4, 5 | **[UNRESOLVED]** |
| I5 | Position-id continuity across a partial | Steps 1, 5 | **[UNRESOLVED]** |
| I6 | Does `IntrabarPolicy` survive, given the domain fixes adverse-first and the other variants have no canonical counterpart? | Step 5 | **[UNRESOLVED]** |
| I7 | Who owns the concurrency cap — config, adapter, or `may_open_position`? | Step 3 | **[UNRESOLVED]** |
| I8 | `bars_held` and ambiguity counting under a two-exit position | Steps 1, 5 | **[UNRESOLVED]** |

**Unchanged and deliberately not addressed here:** R1 reversal protection, R2
netting vs hedging, R3 session/weekend handling, R4 anomaly severity, U5/R8
re-requested close reference, U6/R9 unconfirmed promotion. **None is resolved by
this document.**

---

# P. DO NOT IMPLEMENT YET

**Nothing in §D–§K is authorised.** Specifically, until the strategy owner
reviews this document and answers §O I1:

- **Do not** create `execution/trade_adapter.py`.
- **Do not** add partial-close or stop-modify verbs to `PaperBroker`.
- **Do not** change `SimulatedPosition`, `SimulatedTrade` or the ledger.
- **Do not** change `ReplayEngine`.
- **Do not** import `core.trade_model` from any production module.
- **Do not** modify `main.py`, `main_production.py`, `trade_manager.py` or
  `order_execution.py`.
- **Do not** delete either legacy manager.
- **Do not** re-pin any fingerprint.
- **Do not** create a baseline.

**The single decision that unblocks the most work is §O I1.** Every other open
question is downstream of how a partial exit is represented.

---

# Q. Verification

**Nothing was modified.** No production Python, no test, no baseline, no
specification. The only new file is this document.

Read-only inspection covered `main.py`, `main_production.py`, `trade_manager.py`,
`order_execution.py`, `error_recovery.py`, `risk_manager.py`, `config.py`,
`core/safety.py`, `core/trade_model.py`, `execution/broker.py`,
`execution/paper_broker.py`, `execution/fills.py`, `execution/intrabar.py`,
`backtest/replay_engine.py`, `backtest/ledger.py` and `backtest/baseline.py`,
plus a repository-wide symbol sweep for §B.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 591.8 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`5401d0c`, as expected for a documentation-only phase.

---

*Design and investigation only. No code changed, no adapter built, no manager wired or retired, no baseline created, no performance claim made. Stopping for review.*
