# Phase 4B — DD1: Canonical Trade Manager

**Decision/evidence task only.** No `.py` file, test, strategy, SL/TP, RR,
`valid_rr`, risk sizing or backtest change. Neither manager is wired, repaired or
selected. `baseline_004` remains **FROZEN**. No new baseline.

**Question:** does repository evidence establish which trade-management
implementation is the intended canonical model?

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Directly established by repository code or documentation at `536b350` |
| **[HISTORICAL]** | Established by git history |
| **[MEASURED]** | Established by executing existing code read-only (§16) |
| **[INFERENCE]** | Reasoned from evidence; not directly stated |
| **[DECISION]** | An explicit design choice is required |
| **[UNRESOLVED]** | Cannot be determined from existing evidence |

---

# 1. Executive Summary

## Answer: **CANONICAL NOT ESTABLISHED — DESIGN DECISION REQUIRED**

The repository contains **three** mutually inconsistent specifications of trade
management, not two, and its own architecture document **names one
implementation while describing the behaviour of the other**.

Five findings decide this:

1. **[REPO] The structure document names A and describes B.**
   `SYSTEM_STRUCTURE_DIAGRAM.md:408-409` labels the Layer 9 box
   `trade_manager.py / manage_positions`, then lists the behaviour inside that
   box as `CLOSE_50PCT`, `TRAIL_SL`, `CLOSE_ALL`, `Remove from _OPEN_TRADES` —
   which is `order_execution`'s action vocabulary and `main_production`'s
   removal step, **not** `trade_manager`'s (`PARTIAL_CLOSE_50PCT`,
   `CLOSE_ALL_REMAINING`, `CLOSE_BREAKEVEN_PROTECTION`). The same document's
   dependency tree tags `trade_manager.py [L9]` and `order_execution.py
   [Execution]`, while its mermaid graph wires `order_execution.py` under
   `main_production.py`. The document is internally inconsistent on exactly the
   question DD1 asks.

2. **[REPO] `config.py` specifies a third trailing model that neither manager
   implements.** `TRAILING_STOP_ATR_TRIGGER = 1.0` ("Activate at 1× risk
   profit") and `TRAILING_STOP_ATR_TRAIL = 0.75` ("Trail by 75% of entry ATR"),
   plus `INTRADAY_MAX_HOLD_MINUTES = 240` ("Exit by 4-hour mark"). A trails at
   **2R to entry + 1R**; B trails at **2R to entry**; the configuration says
   **1R, ATR-based**, and neither implements a time-based exit. No manager reads
   these constants — only `test_integration.py:111` asserts one exists.

3. **[MEASURED] B's milestone levels are direction-blind.** `create_order`
   computes `exit_1_1 = entry + risk_distance` and `exit_1_2 = entry +
   2 × risk_distance` **without regard to side**. For a SELL at 2450 with a stop
   at 2480, `exit_1_1` is **2480.00 — the stop level itself** (the correct 1R is
   2420). Because the SELL comparison is `current_price <= exit_1_1`, a measured
   SELL emits `CLOSE_50PCT` **and** `TRAIL_SL` on the first price update at the
   entry price, with no favourable move at all.

4. **[MEASURED] Neither path can currently close a losing position, for
   different reasons.** B has no stop comparison at all: at the stop level it
   emitted **no action** and stayed `TRAILING`. A has a correct stop check, but
   `main.py:913` passes `current_prices = {"spread": 0.5}`, so
   `current_prices.get(trade_id, entry_price)` always yields the **entry price**
   — the same defect the Fix & Decision Matrix recorded as D4 for
   `manage_positions({})` alone. Both paths feed their manager a price that
   cannot move.

5. **[HISTORICAL] History cannot rank them.** `trade_manager.py`,
   `order_execution.py` and `main_production.py` were **all added in one
   commit**, `c3cf4df` (2026-07-01), and neither manager has been modified
   since. `main.py` predates them (`2186e66`, 2026-04-22). There is no
   supersession event, no migration commit, and no commit message that mentions
   either module.

**Consequence.** Each implementation is established as canonical on some axes by
some evidence, and disqualified on others. A carries the Layer 9 label, the only
verification script, the state the persistence layer keeps, and the only stop
check; B carries the wiring, the action vocabulary the documentation describes,
the only real order object, and the only re-entry guard. **No evidence chain
selects one implementation as a whole.** This is a strategy-design decision
(§12), not a finding.

---

# 2. A vs B Implementation Comparison

**A** = `trade_manager.py` · **B** = `order_execution.py` as driven by
`main_production.py`. Line references are at `536b350`.

| # | Axis | A — `trade_manager` | B — `order_execution` / `main_production` | Evidence |
|---|---|---|---|---|
| 1 | **Position creation** | Creates nothing. `main.py:898-908` appends a trade **record** — no sizing, no order object, no broker call | `execute_entry_signal` sizes the position, builds an order object, calls `execute_order`, appends to `_OPEN_TRADES` **only on success** (`:1132-1146`) | [REPO] |
| 2 | **Position state** | `trade_state` dict passed in and returned; the **caller** persists it (`main.py:731`) | State lives inside `OrderExecutor.orders` (in memory). `main_production`'s parallel trade dict carries `"state": None` (`:1144`) which is **never populated** | [REPO] |
| 3 | **Stop state** | `sl_status` ∈ `original` / `breakeven` / `trailing`, and `current_sl` is mutated | **None.** `order["stop_loss"]` is never written after creation; no stop-status field exists | [REPO][MEASURED] |
| 4 | **Original stop** | `original_stop_loss` parameter, never mutated; passed explicitly to the 2R check (`:430`) | `order["stop_loss"]` stays original **because nothing ever changes it** — preserved by omission, not by design | [REPO] |
| 5 | **1R milestone** | Computed per call, **direction-aware**: `entry ± risk` (`:59-63`, `:80-84`) | Precomputed at creation, **direction-blind**: `entry + risk_distance` (`:117`). For SELL 2450/2480 this is **2480.00**, the stop level; correct is 2420 | [REPO][MEASURED] |
| 6 | **2R milestone** | `entry ± 2 × original_risk`, direction-aware, from the **original** stop (`:152`, `:178`) | `entry + 2 × risk_distance` (`:118`), direction-blind. SELL case: 2510, beyond the stop | [REPO][MEASURED] |
| 7 | **Final TP** | `take_profit` as supplied; exit reported **at the TP level** (`:240`) | `exit_1_3.price = take_profit` (`:119`); exit reported **at the observed price** (`:276`) | [REPO][MEASURED] |
| 8 | **Partial exits** | `PARTIAL_CLOSE_50PCT`; `position_size` 1.0 → 0.5 (`:422`) | `CLOSE_50PCT` action + status `PARTIAL`; **no quantity change**. `main_production:1179-1180` **logs it and does nothing else** | [REPO][MEASURED] |
| 9 | **Remaining quantity** | Tracked as a fraction: 1.0 / 0.5 / 0.0 | **Not tracked.** `order["position_size"]` (lots) is written once at creation and never again | [REPO][MEASURED] |
| 10 | **Breakeven** | At **1R**: `current_sl = entry`, `sl_status = "breakeven"` (`:423-424`) | Never at 1R. At 2R it *emits* `new_sl = entry`, but `main_production:1181-1182` **only logs** it — no stop is moved anywhere in the system | [REPO] |
| 11 | **Trailing stop** | At **2R**: `current_sl = entry + 1R` — locks 1R (`:158`, `:440`) | At **2R**: `new_sl = entry` — locks **nothing** (`:255`). `config.py:150-151` specifies a **third** model: activate at 1R, trail 0.75 × ATR, implemented nowhere | [REPO] |
| 12 | **Stop-loss detection** | Explicit, **first**, returns immediately (`:386-404`) | **Absent.** Measured: at the stop level, zero actions, status still `TRAILING` | [REPO][MEASURED] |
| 13 | **Breakeven reversal protection** | `check_breakeven_stop` (`:270`), gated on `sl_status` ∈ {breakeven, trailing} | **Absent**; no equivalent exists | [REPO] |
| 14 | **`CLOSE_BREAKEVEN_PROTECTION`** | Emitted (`:467`); sets `position_size = 0` | No such action. `main_production`'s handler has **no branch** for it, so if A were wired in place of B the action would be silently dropped | [REPO] |
| 15 | **`TRAIL_SL`** | Same action name; `new_sl = entry + 1R`; `profit_locked` = 1R | Same action name; `new_sl = entry`; `profit_locked = abs(entry − stop)` = **the full risk**, though moving to entry locks zero | [REPO] |
| 16 | **`OrderStatus`** | None. Plain strings: `OPEN`, `CLOSED`, `CLOSED_SL` | `OrderStatus` enum, 8 members. `SENT` appears only in a filter list (`:300`); `EXPIRED` is **never referenced at all** | [REPO] |
| 17 | **`trade_state`** | 6 keys; `exit_1_2_status` declares `"completed"` in its comment but that value is **never assigned** (only `"sl_trailed"`, `:442`) | No equivalent. Milestone flags live in the order dict as `exit_1_x.triggered` | [REPO] |
| 18 | **Multiple milestone handling** | Sequential within **one** evaluation. Measured: one jump from entry to TP produced `PARTIAL_CLOSE_50PCT` + `TRAIL_SL` + `CLOSE_ALL_REMAINING` | Same shape. Measured: `CLOSE_50PCT` + `TRAIL_SL` + `CLOSE_ALL`, all priced at 2540.00 | [MEASURED] |
| 19 | **Repeated milestone protection** | `exit_1_1_taken` and `exit_1_2_status` flags — but the **stop check is not gated on `position_size > 0`**. Measured: re-called after full closure, A emitted `CLOSE_ALL` / `CLOSED_SL` on a closed position | `triggered` flags **plus** a status gate: measured, a re-call after `CLOSED` returned `{"status": "inactive"}` | [MEASURED] |
| 20 | **Position closure** | `position_size = 0`; `trade_status` = `CLOSED` or `CLOSED_SL`. `main.py:917-918` recognises only `"CLOSED"` — a **`CLOSED_SL` trade is dropped from the open list and never counted as closed** | Status `CLOSED`; `main_production:1185` removes the trade from `_OPEN_TRADES` on `CLOSE_ALL` only | [REPO] |
| 21 | **Quantity after partial close** | 0.5 — a **fraction** of an unstated base; no lots anywhere in path A | Unchanged lots. The partial is a log line | [MEASURED] |
| 22 | **Gap-through-stop** | Reports the exit **at the stop level regardless of gap size**. Measured: price 2505 against a 2480 stop still reported `exit_price` 2480.00 | No stop detection, so the case does not arise | [MEASURED] |
| 23 | **Same-bar behaviour** | No bar concept — evaluation is per price sample. Stop and 1R in one call → **only the stop**, because the stop check returns immediately | No stop, so no contention. All three milestones fire in one call | [REPO][MEASURED] |
| 24 | **Event ordering** | stop → 1R → 2R → TP → breakeven-protection | 1R → 2R → TP | [REPO] |

## Axes where each is the *only* implementation

| Only A has | Only B has |
|---|---|
| A stop-loss comparison | A real order object and an execution attempt |
| Stop state (`sl_status`) and a mutated stop | Position sizing (lots) |
| Remaining-quantity tracking | A re-entry guard (`inactive` once closed) |
| Breakeven reversal protection | A status enum |
| Direction-aware milestone levels | Persistence of the trade list to disk |
| Persisted management state (`trade["state"]`) | Removal of closed trades from the open list |

**[INFERENCE]** Neither column is a subset of the other. A union would be a
**third** implementation, which is why §12 offers a hybrid option.

---

# 3. Call Graph A — `main.py` → `trade_manager`

```
main.main()                                         main.py:796
  └─ while _SHOULD_CONTINUE:
       ├─ check_pre_trade_gates()                   L0 (incl. DEAD session)
       ├─ if len(open_trades) < CONFIG["max_concurrent_trades"]   (3)
       │    ├─ get_market_data() x6                 MT5 or None
       │    ├─ analyze_entry(...)                   L1-L8
       │    └─ if signal_type == "ENTRY_SIGNAL":
       │         └─ open_trades.append({...,"status":"OPEN","state":None})   :898-908
       │              *** creates a RECORD: no sizing, no order, no broker ***
       └─ if open_trades:
            ├─ current_prices = {"spread": 0.5}     :913   *** mock ***
            ├─ manage_positions(open_trades, current_prices)          :914
            │    └─ for trade in open_trades:                          :714
            │         ├─ current_price = current_prices.get(trade_id, entry_price)
            │         │      *** key never present -> ALWAYS entry_price ***
            │         └─ manage_open_trade(                            :718
            │              original_stop_loss=trade["stop_loss"],      :722
            │              trade_state=trade.get("state"))             :726
            │              ├─ stop check vs trade_state["current_sl"]  :386
            │              │     -> CLOSE_ALL, trade_status=CLOSED_SL, RETURN
            │              ├─ check_partial_exit_1_1  -> PARTIAL_CLOSE_50PCT
            │              │     size 1.0->0.5, current_sl->entry, sl_status=breakeven
            │              ├─ check_partial_exit_1_2(original_stop_loss, sl_status)
            │              │     -> TRAIL_SL, current_sl->entry+1R, sl_status=trailing
            │              ├─ check_final_exit_1_3 -> CLOSE_ALL_REMAINING, size 0
            │              └─ check_breakeven_stop -> CLOSE_BREAKEVEN_PROTECTION, size 0
            │         └─ trade["status"|"actions"|"state"] written back :729-731
            └─ closed = [status == "CLOSED"]; open = [status == "OPEN"]  :917-918
                   *** "CLOSED_SL" matches NEITHER filter ***
```

**Imported but never called in path A** — [REPO]:
`close_position` (`main.py:47`), `log_closed_trade` and
`calculate_weekly_performance` (`main.py:48`). Layer 10 is therefore unreachable
from A, so no closed trade is ever recorded.

**No broker call exists anywhere in path A.** The only `mt5.order_send` in
`main.py` is in `close_all_positions()` (`:770`), reached only from the shutdown
signal handler.

---

# 4. Call Graph B — `main_production.py` → `order_execution`

```
main_production.main()
  ├─ initialize(): order_executor = OrderExecutor()                    :393
  └─ loop:
       ├─ if signal_type == "ENTRY_SIGNAL":
       │    └─ execute_entry_signal(analysis["entry_signal"])          :1424
       │         *** called with ONE argument -> account_balance = 10000 ***
       │         ├─ calculate_lot_size_for_symbol(...) | fallback      :1099-1109
       │         ├─ order_executor.create_order(...)                   :1111
       │         │     └─ exit_1_1 = entry + risk        (direction-blind)  oe:117
       │         │        exit_1_2 = entry + 2*risk      (direction-blind)  oe:118
       │         │        exit_1_3 = take_profit                            oe:119
       │         ├─ order_executor.execute_order(order_id,
       │         │        mt5_handler=None,
       │         │        simulation=CONFIG["demo_mode"])              :1126-1130
       │         │     CONFIG["demo_mode"] is False                    :150
       │         │     -> `if simulation:` False
       │         │     -> `elif mt5_handler:` None
       │         │     -> else: return (False, "No MT5 handler provided
       │         │                              and simulation disabled")  oe:190
       │         └─ success is False -> log error -> return None       :1151-1155
       │              *** _OPEN_TRADES.append() at :1146 IS NEVER REACHED ***
       └─ manage_positions({})                                         :1431
            └─ for trade in _OPEN_TRADES:                              :1170
                 ├─ current_price = current_prices.get(trade_id, entry_price)
                 │      *** {} -> ALWAYS entry_price ***
                 └─ order_executor.update_current_price(order_id, price)   :1177
                      ├─ status gate: OPEN | PARTIAL | TRAILING else "inactive"
                      ├─ 1:1 -> CLOSE_50PCT      -> main_production LOGS ONLY :1179
                      ├─ 1:2 -> TRAIL_SL         -> main_production LOGS ONLY :1181
                      └─ 1:3 -> CLOSE_ALL        -> log + closed_trades.append :1183
            └─ _OPEN_TRADES = [t for t in _OPEN_TRADES if t not in closed_trades]
```

**Imported but never called in path B** — [REPO]:
`manage_open_trade`, `close_position` (`:77`), `log_closed_trade`,
`calculate_weekly_performance` (`:78`), `save_closed_trade` (`:89`).

**[REPO] Management state is not persisted in B.** `OrderExecutor.orders` is an
in-memory dict. `restore_state()` (`:1207`) reloads `_OPEN_TRADES` from disk, but
the executor's order table is empty after a restart, so
`update_current_price` returns `{"status": "error", "message": "Order not
found"}` for every restored trade. **A restored position in path B can never be
managed again.** Path A persists its management state inside the trade record
itself (`trade["state"]`), so it survives a restart.

## Required determinations

| Question | Answer | Evidence |
|---|---|---|
| Which path is currently wired? | **B.** `main_production` calls `order_executor.update_current_price`; `manage_open_trade` is imported and never called | [REPO] |
| Which path can actually receive positions? | **A** — it appends records unconditionally. **B cannot**: `execute_order` returns `False` in the shipped configuration, so `_OPEN_TRADES.append` is unreachable. B can only see trades restored from disk, which it then cannot manage | [REPO] |
| Which path can close a losing position? | **Neither.** A has the only stop check, but `main.py` feeds it the entry price forever. B has no stop check at all | [REPO][MEASURED] |
| Which path tracks quantity? | **A** (fraction). B writes lots once and never changes them | [REPO][MEASURED] |
| Which path tracks stop state? | **A** only | [REPO] |
| Which path has reversal protection? | **A** only | [REPO] |
| Which functions are imported but unreachable? | A-path: `close_position`, `log_closed_trade`, `calculate_weekly_performance`. B-path: `manage_open_trade`, `close_position`, `log_closed_trade`, `calculate_weekly_performance`, `save_closed_trade` | [REPO] |

**Correction to an earlier document.** `PHASE_4B_FIX_DECISION_MATRIX.md` M16 says
`main.py` "manages positions it never creates", and
`PHASE_4B_TRADE_MODEL_SPEC.md:174` says "`main.py` never creates orders". The
second is exact; the first is imprecise. `main.py` **does** create the trade
records it manages (`:898-908`); what it never creates is an **order**. The
distinction matters for DD2: path A is a complete record lifecycle with no
execution, not a half lifecycle.

---

# 5. Repository Intent Evidence

| # | Source | What it says | Points to | Class |
|---|---|---|---|---|
| I1 | `trade_manager.py:1-13` docstring | "LAYER 9: TRADE MANAGEMENT ENGINE … Partial exits at 1:1, 1:2, 1:3 RR with SL management + breakeven protection" | **A** | [REPO] |
| I2 | `order_execution.py:1-5` docstring | "Order Execution & Management Layer. Handles live order placement, execution, tracking, and error recovery" — claims execution **and** management | **B** (dual role) | [REPO] |
| I3 | `SYSTEM_STRUCTURE_DIAGRAM.md:689,693` | `trade_manager.py [L9]` vs `order_execution.py [Execution]` — a **role split** | **A** for management | [REPO] |
| I4 | `SYSTEM_STRUCTURE_DIAGRAM.md:408-409` | Box labelled "Layer 9: Position Management / trade_manager.py" | **A** | [REPO] |
| I5 | …the **contents** of that same box (`:411-418`) | "1:1 RR → CLOSE_50PCT, 1:2 RR → TRAIL_SL, 1:3 RR → CLOSE_ALL, Remove from `_OPEN_TRADES`" — B's action names and `main_production`'s removal | **B** | [REPO] |
| I6 | `SYSTEM_STRUCTURE_DIAGRAM.md:10,35` mermaid | `Main Loop [main_production.py]` → `order_execution.py / OrderExecutor` under "Execution Stack" | **B** | [REPO] |
| I7 | `SYSTEM_STRUCTURE_DIAGRAM.md:137-141` | "Layer 9: manage_positions / update_current_price / CLOSE_50PCT / TRAIL_SL / CLOSE_ALL" | **B** | [REPO] |
| I8 | `ARCHITECTURE_ANALYSIS_FLAWS.md:528-532` | Section "LAYER 9: TRADE MANAGER", located at `trade_manager.py`. `order_execution` is **not analysed as Layer 9 anywhere in that document** | **A** | [REPO] |
| I9 | `test_week3_verification.py:1-26` | "Test Layer 9 (Trade Manager) … Verification of complete 10-layer system before paper trading", importing only `trade_manager` | **A** | [REPO][HISTORICAL] |
| I10 | `main.py:706` and `main_production.py:1164` | **Both** section headers read "POSITION MANAGEMENT (Layer 9)" | neither | [REPO] |
| I11 | `main_production.py:1144` | The trade record carries `"state": None` — a field shaped exactly like A's `trade_state`, never populated in B | **A** (weak) | [INFERENCE] |
| I12 | `main_production.py:1179-1185` | The action handler branches on `CLOSE_50PCT` / `TRAIL_SL` / `CLOSE_ALL` — **B's vocabulary**. A's `PARTIAL_CLOSE_50PCT` and `CLOSE_ALL_REMAINING` would match no branch | **B** | [REPO] |
| I13 | `config.py:149-158` | A **third** trailing specification: activate at 1× risk, trail 0.75 × ATR, plus a 240-minute max hold. Read by no manager | **neither** | [REPO] |
| I14 | `trade_persistence.py:245-256` | Demo records use `position_size` 0.5 and 1.0 — fraction-shaped values, matching A's semantics; `main_production` stores lots | **A** (weak) | [INFERENCE] |
| I15 | Both modules' `__main__` demos | Both self-test **BUY only** (`trade_manager.py:551-593`, `order_execution.py:329-361`) | neither | [REPO] |
| I16 | No `README`, launcher script, or run instruction naming an entry point | — | neither | [REPO] |

## The conflict, stated plainly

**[REPO]** Every *label* in the repository assigns trade management to A: the
module docstring, the dependency tree's `[L9]` tag, the flaws document's Layer 9
section, the only verification script, and the Layer 9 box title in the flow
diagram. **Every *behavioural description*** in the same documents is B's: the
action names, `update_current_price`, the removal from `_OPEN_TRADES`, and the
mermaid wiring.

**[UNRESOLVED]** The documentation was evidently written against a system in
which one module was called Layer 9 and another performed it. Nothing in the
repository states which half of that description is the intent and which is the
drift. **Naming alone is explicitly not accepted as proof**, per the brief — and
naming is precisely what distinguishes I1/I3/I4/I8/I9 from I5/I6/I7/I12.

---

# 6. Historical Git Evidence

| # | Fact | Class |
|---|---|---|
| H1 | The repository has **45 commits**, from `2186e66` (2026-04-22) to `536b350` | [HISTORICAL] |
| H2 | `main.py` was added in the **initial commit**, `2186e66` (2026-04-22) | [HISTORICAL] |
| H3 | `trade_manager.py`, `order_execution.py` **and** `main_production.py` were **all added in `c3cf4df`** (2026-07-01, message: "update") | [HISTORICAL] |
| H4 | Neither manager has been touched since: `git log -- trade_manager.py` and `-- order_execution.py` each return **exactly one commit** | [HISTORICAL] |
| H5 | `main.py`'s `from trade_manager import …` also first appears in `c3cf4df` — the import was added **with** the module, not retrofitted | [HISTORICAL] |
| H6 | `main_production.py`'s `from trade_manager import …` **and** its `OrderExecutor` usage also both first appear in `c3cf4df` | [HISTORICAL] |
| H7 | The four original analysis documents (`ARCHITECTURE_ANALYSIS_FLAWS.md`, `ANALYSIS_EXECUTIVE_SUMMARY.md`, `FLOW_DIAGRAM_WITH_FLAWS.md`, `QUICK_FIX_REFERENCE.md`) arrived in the **same commit** `c3cf4df` | [HISTORICAL] |
| H8 | No commit message in the history mentions either module, a migration, a deprecation or a supersession | [HISTORICAL] |

**[HISTORICAL] What history establishes:** `main_production` is the **later**
entry point, and `main.py` the original. **What it does not establish:** any
ordering between the managers. They are the same age, by the same commit, and
neither was ever revised. There is **no supersession event** to appeal to.

**[HISTORICAL] Prior versions.** There are none. `git log --diff-filter=A`
confirms a single addition for each file and no subsequent modification, so
"previous versions of `trade_manager`/`order_execution`" do not exist in this
repository.

## Archived runtime evidence

**[HISTORICAL][MEASURED]** `archive/2026-09-16_active_trades_phantom.json`
contains two trade records whose `order_id` carries the `_auto_` suffix minted by
`main_production.manage_positions:1173` — so **path B processed them at some
point**. But their prices (2450 / 2420 / 2540) are exactly the two modules'
`__main__` demo values, the archive README classifies them as *phantom* and the
closed-trade file as *UNVERIFIED — SUSPECTED SYNTHETIC*, and their schema
(`trade_id, entry_price, exit_price, pnl, pnl_pct, reward_to_risk, closed_at`)
matches **neither** manager's output shape. They establish that B ran; they do
not establish that B was intended, and they are not evidence of real trading.

---

# 7. State Machine A — `trade_manager`

A maintains **three separate** state variables. They are not collapsed here.

## A.1 Position status — `result["trade_status"]`

```
          ┌──────────────────────────────────────────┐
          │                                          │
   (entry)│                                          │
      ────▼────                                      │
     │  OPEN   │───── stop hit ──────────────► CLOSED_SL
     │         │        (returns immediately)        ▲
     │         │                                     │
     │         │── TP hit (size -> 0) ───────► CLOSED │
     │         │── BE-protection (size -> 0) ► CLOSED │
      ─────────                                      │
          │                                          │
          └── re-called after closure ───────────────┘
              *** MEASURED: emits CLOSE_ALL / CLOSED_SL
                  on an already-closed position, because
                  the stop check is not gated on size > 0 ***
```

Values are **plain strings**, not an enum. `CLOSED_SL` is recognised by neither
of `main.py`'s two filters (`:917-918`).

## A.2 Stop status — `trade_state["sl_status"]`

```
  original ──1R reached──► breakeven ──2R reached──► trailing
     │                         │                        │
  current_sl =            current_sl =             current_sl =
  original_stop             entry                  entry + 1R
```

`original → trailing` directly is **impossible**: the 2R block is gated on
`exit_1_1_taken` (`:427`). Within a single call both transitions can occur.

## A.3 Trade state — `trade_state`

| Key | Domain | Notes |
|---|---|---|
| `position_size` | 1.0 → 0.5 → 0.0 | Fraction of an unstated base |
| `current_sl` | price | The only mutated stop in the system |
| `sl_status` | original / breakeven / trailing | §A.2 |
| `exit_1_1_taken` | bool | One-shot guard |
| `exit_1_2_status` | pending / sl_trailed | `"completed"` is declared in the comment at `:370` and **never assigned** |
| `profit_locked_1_2` | price distance | Reported, never used downstream |

**[REPO]** A has **no** concept of a bar, a broker, an order id beyond the string
passed in, or lots.

---

# 8. State Machine B — `order_execution`

B has **one** state variable, and it doubles as the milestone marker.

## B.1 Order status — `OrderStatus`

```
  PENDING ──execute_order success──► OPEN ──1:1──► PARTIAL ──1:2──► TRAILING
     │                                 │             │                │
     │                                 └──────── 1:3 ─┴────────────────┘
     │                                                 │
     │                                                 ▼
     │                                              CLOSED ──► re-call returns
     │                                                          {"status":"inactive"}
     └── retries exhausted ──► REJECTED

  SENT     : referenced only in the get_all_open_orders filter (:300); never assigned
  EXPIRED  : never referenced anywhere
```

**[REPO]** In the shipped configuration the `PENDING → OPEN` edge is
**unreachable**: `execute_order` takes the `else` branch and returns `False`
without raising, so the status is not even set to `REJECTED` — the order stays
`PENDING` forever and the trade is never recorded.

## B.2 Stop status

**Does not exist.** `order["stop_loss"]` is written at creation and never again;
`TRAIL_SL` is emitted as an *action* and applied by no one.

## B.3 Quantity

**Not tracked.** `position_size` (lots) is set at creation. `PARTIAL` is a
status, not a quantity.

## C. Difference matrix — state and event

| State / event | A behaviour | B behaviour | Evidence | Conflict | Canonical status |
|---|---|---|---|---|---|
| Entry | record appended by `main.py` | order created, execution attempted and **fails**, nothing recorded | [REPO] | **Yes** | [DECISION] |
| Stop hit | `CLOSE_ALL`, exit at the stop **level**, `CLOSED_SL`, returns | **no detection** | [REPO][MEASURED] | **Yes** | [DECISION] — DD1 |
| 1R | partial to 0.5, stop → entry, `sl_status=breakeven` | `CLOSE_50PCT` + status `PARTIAL`; quantity and stop unchanged | [REPO][MEASURED] | **Yes** | [DECISION] — DD4/DD8 |
| 2R | stop → entry + 1R (`trailing`) | stop *suggested* → entry; never applied | [REPO] | **Yes** | [DECISION] — DD3 |
| TP | `CLOSE_ALL_REMAINING`, exit at the **TP level**, size 0 | `CLOSE_ALL`, exit at the **observed price**, status `CLOSED`, trade removed | [REPO][MEASURED] | **Yes** | [DECISION] — DD9 |
| Reversal after breakeven | `CLOSE_BREAKEVEN_PROTECTION` | nothing | [REPO] | **Yes** | [DECISION] — DD7 |
| Re-call after closure | **emits a spurious `CLOSE_ALL`** | returns `inactive` | [MEASURED] | **Yes** | [DECISION] — B is safer **on this axis only** |
| Restart with restored trades | state restored from the trade record; management continues | `order_id` unknown to the executor → `{"status": "error"}`; **unmanageable** | [REPO] | **Yes** | [DECISION] |
| Direction handling | direction-aware throughout | **direction-blind milestones**; SELL 1R = the stop level | [MEASURED] | **Yes** | [DECISION] — B requires repair under any choice |

---

# 9. Event Ordering

## 9.1 What the repository establishes

| Event pair | A | B | Repository-established? |
|---|---|---|---|
| stop + 1R in one evaluation | **Stop wins**; the function returns before the 1R block (`:386-404`) | undefined — no stop exists | **For A only.** [REPO] |
| stop + 2R | Stop wins, same mechanism | undefined | **For A only.** [REPO] |
| stop + TP | Stop wins, same mechanism | undefined | **For A only.** [REPO] |
| 1R + 2R | Both fire, 1R first, in the **same** call — measured | Both fire, 1:1 first, same call — measured | **Yes, both agree.** [MEASURED] |
| Multiple milestones | 1R → 2R → TP → BE-protection, all reachable in one call | 1:1 → 1:2 → 1:3 in one call | **Yes, both agree on order.** [MEASURED] |
| Reversal after breakeven | Last, and only while `size > 0` and `sl_status` ∈ {breakeven, trailing} | not implemented | **For A only.** [REPO] |
| Gap through stop | Exit reported at the **stop level** | not implemented | **For A only.** [REPO][MEASURED] |
| Gap through TP | Exit reported at the **TP level** | Exit reported at the **observed price** | **Conflict.** [MEASURED] |
| Partial close + stop | The stop closes **everything** (`CLOSE_ALL`), not the remaining half, and pnl is labelled `"LOSS"` even when the stop sits at breakeven or above | not implemented | **[UNRESOLVED]** — A's behaviour is implemented but never documented as intended |
| Repeated evaluation after a milestone | Guarded per milestone, **not** for the stop | Guarded by the status gate | **Conflict.** [MEASURED] |
| Same-bar events | **No bar concept exists in either manager.** Both evaluate a single price sample per call | — | **Neither.** [REPO] |

## 9.2 Backtest policy — kept separate

**[REPO]** `execution/paper_broker.py` with `IntrabarPolicy` CONSERVATIVE
resolves a bar where both the stop and the target are touched **in favour of the
stop**, and records `was_ambiguous`. R1 makes the fill bar itself eligible for
exit evaluation.

**This is a backtest policy, not production intent.** It was chosen in Phase 2A
as the conservative resolution of an ambiguity that tick data would settle. It
happens to agree with A's stop-first ordering, and that agreement is **not
evidence for A** — the policy was written against a bar series, while A was
written against a price sample. Importing it as intent would be circular.

## 9.3 Unresolved live/broker semantics

**[UNRESOLVED]** Neither manager models: partial fills, slippage
(`MAX_SLIPPAGE_PIPS = 2.0` is configured and read by nobody), broker-side stop
orders, requotes, or the fact that a real stop is an **order at the broker** that
fills without the bot observing anything. Both managers assume the bot observes a
price and then acts, which is a polling model, not a resting-order model — even
though Phase 4A introduced resting limit orders on the backtest side.

---

# 10. Gap Handling

## 10.1 What each actually does

| Implementation | Non-gapped | Gapped through the level | Evidence |
|---|---|---|---|
| **A** `trade_manager` | Exit at the stop / TP **level** | **Still the level.** Measured: price 2505 vs a 2480 stop → `exit_price` 2480.00 | [MEASURED] |
| **B** `order_execution` | Exit at the **observed price** | Same — the observed price is all it uses | [MEASURED] |
| **Backtest** `paper_broker:458-498` | Exit at the level | **Bar open**, with the reason annotated `GAPPED through stop, filled at bar open` | [REPO] |

## 10.2 Is either documented as intended?

**[UNRESOLVED]** No. No document states a gap policy for production. The
backtest's rule is documented in its own code comment ("the realistic fill is the
open, which is worse than the stop") and is a **Phase 2A implementation
decision**, not a strategy-owner ruling.

## 10.3 Design decision or implementation mismatch?

**Both, and they separate cleanly:**

- **Implementation mismatch** — A reporting a fill at a price that was never
  traded is not a defensible model of any broker. Whatever DD1 decides, a stop
  cannot fill better than the market. **[INFERENCE]**
- **Design decision** — whether the canonical model prices a gapped exit at the
  **bar open** (the backtest's rule), at the **first observed price** (B's rule),
  or at a **slippage-adjusted level** (`MAX_SLIPPAGE_PIPS`, currently unread) is
  a modelling choice with no repository answer. **[DECISION]** = DD9.

**Can it be resolved now?** **No.** The fill rule belongs to the execution model,
and until DD1 fixes which manager owns exits there is nothing to attach it to.
Note that the backtest already implements a **hybrid** — level when not gapped,
bar open when gapped — which is the only gap rule in the repository that is
tested. That makes it a *candidate*, not a default.

**Not changed by this document.**

---

# 11. Canonical Determination

> **Does repository evidence establish which implementation is the intended
> canonical trade-management model?**

## **C — No. Repository evidence is insufficient.**

### What conflicts

| Conflict | A side | B side |
|---|---|---|
| Label vs behaviour in the same document | `SYSTEM_STRUCTURE_DIAGRAM.md:408` names `trade_manager.py` | `:411-418` describes B's actions, `:137` names `update_current_price`, `:35` wires `order_execution` |
| Role assignment vs wiring | Dependency tree: `trade_manager [L9]`, `order_execution [Execution]` | `main_production` calls B for management and never calls A |
| Docstring claims | A claims Layer 9 trade management | B claims "Execution **& Management**" |
| Verification | `test_week3_verification.py` verifies A as Layer 9 | No verification script exists for B's management |
| Action vocabulary | A emits `PARTIAL_CLOSE_50PCT` / `CLOSE_ALL_REMAINING` / `CLOSE_BREAKEVEN_PROTECTION` | `main_production`'s handler only understands B's `CLOSE_50PCT` / `TRAIL_SL` / `CLOSE_ALL` |
| Trailing semantics | 2R → entry + 1R | 2R → entry — and `config.py` says 1R → ATR × 0.75, agreeing with neither |

### What is missing

- **[UNRESOLVED]** Any statement — in code, docs, comments, commit messages or
  tests — that ranks the two, deprecates one, or describes a migration.
- **[UNRESOLVED]** Any executed trade produced by either path. `baseline_004`
  produced **zero trades**; the only persisted records are archived as phantom
  and synthetic.
- **[UNRESOLVED]** A stated intent for the 1R stop move, the trailing target, the
  quantity representation, or reversal protection, independent of the two
  implementations.
- **[UNRESOLVED]** Any reason for the third (ATR) trailing specification in
  `config.py`, or for the 240-minute max hold that nothing implements.

### Why neither can legitimately be declared canonical

1. **[REPO]** B's milestone levels are **wrong for SELL** — the 1R level equals
   the stop. Declaring B canonical would canonise a direction bug; repairing it
   first is a change, not a reading of intent.
2. **[REPO]** B cannot close a losing position and, in the shipped
   configuration, cannot receive one either. An implementation that cannot
   complete the lifecycle cannot define it.
3. **[REPO]** A is not wired, has never been called by either entry point in this
   configuration, tracks a *fraction* with no link to lots, emits a spurious
   `CLOSE_ALL` on an already-closed position, and reports fills at prices that
   were never traded.
4. **[REPO]** The only document that describes Layer 9 in detail **names A and
   describes B**, so appealing to it selects whichever half one quotes.
5. **[HISTORICAL]** Both arrived in one commit and neither was revised, so
   "the later one wins" has no referent.
6. **[INFERENCE]** Selecting on richness, safety, cleanliness or apparent
   sophistication is explicitly excluded by the brief — and those are the only
   remaining discriminators.

### The explicit design decision required

> **Which trade-management semantics are the intended model:** A's
> (stop check, 1R → breakeven, 2R → lock 1R, fractional quantity, reversal
> protection), B's (no stop check, status-only milestones, 2R → breakeven, lots
> untracked), the configuration's (1R activation, ATR trailing, 240-minute max
> hold), or a **stated new model** that takes named elements from each?

Until that is answered by the strategy owner, **no implementation may be
declared canonical and neither may be wired, repaired or deleted.**

---

# 12. Design Decision Brief

**Not ranked.** Presented for the strategy owner's choice.

## Option A — adopt `trade_manager` semantics

**What it would mean.** The canonical model becomes: stop checked first and
exclusively; 1R closes 50 % and moves the stop to breakeven; 2R moves the stop to
entry + 1R; the remainder exits at `tp_ratio × risk`; a reversal to within $2.00
of entry closes the rest while the stop sits at or above breakeven; quantity is a
fraction of the original position.

**Behavioural consequences.**
- Every trade that reaches 1R becomes **risk-free by construction**; the
  distribution of outcomes changes shape, not merely scale.
- A stop-out after a partial closes the **remaining** half but is still reported
  as `CLOSE_ALL` with `"pnl": "LOSS"`, even at breakeven — reporting must be
  corrected.
- `CLOSED_SL` must be added to `main.py`'s closure filters, or stop-outs keep
  vanishing from both lists.
- The spurious `CLOSE_ALL` on a closed position must be gated on `size > 0`.
- The fraction must be bound to lots somewhere, since A has no notion of lots.
- Exit pricing at the level must be reconciled with gaps (§10).
- `order_execution` would be demoted to **order placement only**, which matches
  `SYSTEM_STRUCTURE_DIAGRAM.md`'s `[Execution]` tag.

## Option B — adopt `order_execution` semantics

**What it would mean.** The canonical model becomes: milestones are status
transitions on an order object; 1R marks `PARTIAL`; 2R marks `TRAILING` and
suggests a stop at entry; TP closes and the trade is removed; the stop is left
entirely to the broker-side SL attached to the order.

**Behavioural consequences.**
- The direction bug **must** be fixed first (SELL 1R currently equals the stop),
  otherwise every SELL partials immediately.
- Something must actually apply `CLOSE_50PCT` and `TRAIL_SL`; today they are log
  lines, so adopting B as-is means **no partials and no trailing at all**.
- A loss can only be closed by a **broker-side stop**, which this repository
  never sends and — under the standing safety rule — must not send. The backtest
  would then be simulating a mechanism production does not possess.
- Quantity semantics must be defined from scratch; `PARTIAL` carries no size.
- Management state must be persisted, or restarts orphan every position.
- Reversal protection and the breakeven move would be **dropped** from the model
  unless separately re-specified.

## Option C — a hybrid, and what the repository actually supports

**[REPO]** Only these hybrid elements have repository backing; anything else
would be new design:

| Element | Source | Status |
|---|---|---|
| Order object, order id, status enum, re-entry guard | B | implemented |
| Explicit stop check, stop state, fractional quantity, reversal protection | A | implemented |
| Direction-aware milestone construction | A | implemented |
| Gap rule: level when not gapped, bar open when gapped | `paper_broker` | implemented **and tested** |
| Intrabar contention: stop wins | `paper_broker` CONSERVATIVE | implemented and tested |
| ATR trailing at 1R, 240-minute max hold, 2.0-pip slippage | `config.py` | **specified, implemented nowhere** |

**[INFERENCE]** A hybrid of B's object model with A's state machine is the only
combination in which every element already exists somewhere in the repository.
That is an observation about availability, **not** a recommendation.

## Which later decisions depend on DD1

DD2, DD3, DD4, DD5, DD6, DD7, DD8, DD9, DD10 — and, through the ladder, DD15
(`valid_rr`). See §13.

## Which current defects must remain untouched until DD1 is resolved

F8 (missing stop check), F9 (ladder ordering), F10 (D3 + D4 wiring), M3
(`trade_manager` import), M9 (`TRAIL_SL` log text), M10
(`check_partial_exit_1_2` parameter name), M15 and M16 (removal of the losing
implementation), plus the two newly recorded defects N1 and N2 in §14.

---

# 13. Downstream Dependencies

```
                         ┌──────────────────────────────┐
                         │  DD1  CANONICAL MANAGER      │
                         │  [DECISION] — unresolved     │
                         └───────────────┬──────────────┘
                                         │
        ┌────────────────┬───────────────┼───────────────┬────────────────┐
        ▼                ▼               ▼               ▼                ▼
  DD2 lifecycle    DD4 1R stop     DD8 remaining    DD7 reversal    DD9 gap fill
  owner            (BE or not)     quantity         protection      (level/open/slip)
        │                │          (fraction/lots)       │                │
        │                ▼                │               │                │
        │          DD3 TRAIL_SL           │               │                │
        │          (lock 1R / BE /        │               │                │
        │           ATR per config)       │               │                │
        │                │                │               │                │
        ▼                ▼                ▼               ▼                ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  CANONICAL TRADE MODEL  (one state machine, production + backtest)       │
  └───────────────────────────────┬──────────────────────────────────────────┘
                                  │
     ┌───────────────┬────────────┼─────────────┬──────────────────┐
     ▼               ▼            ▼             ▼                  ▼
  D11 position   E5 partials   E6 trailing   E7 breakeven      E9 stops
  lifecycle      E12 quantity  E10 gap       E8 reversal       E11 intrabar
  (partial                                                      ambiguity
   states)                          │
                                    ▼
                    ┌───────────────────────────────┐
                    │  BACKTEST EQUIVALENCE (Tier 4) │
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │  NEW CANONICAL BASELINE        │
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │  DD15 valid_rr  (options 1/2)  │
                    └───────────────────────────────┘

  LIMIT_FVG lifecycle:  PendingOrder fill ──► ??? ──► management
                        [UNRESOLVED] the hand-off target is whichever
                        manager DD1 selects; today a filled pending order
                        is managed only by paper_broker, and by nothing
                        in production.

  Risk sizing: DEPENDS ONLY PARTIALLY ON DD1.
    - DD11 (broker field authority) and F4 (account balance) are independent.
    - The quantity REPRESENTATION (fraction vs lots) is DD8, which needs DD1.
```

| Decision / item | Depends on DD1? | Why |
|---|---|---|
| Partial-close quantities (C4, DD8) | **Yes** | A tracks a fraction; B tracks nothing |
| Stop progression (C8, DD4) | **Yes** | 1R → breakeven exists only in A |
| Trailing semantics (C9, DD3) | **Yes** | Two implementations, three specifications |
| Breakeven protection (C10, DD7) | **Yes** | Exists only in A |
| Gap handling (C16, DD9) | **Yes** | Needs an owner before a rule can attach |
| Backtest equivalence (E5-E12) | **Yes** | The backtest must model the chosen manager |
| Position lifecycle (D11) | **Yes** | Partial states are needed only if the ladder is adopted |
| `valid_rr` (B13, DD15) | **Yes, indirectly** | Through DD5: what "R" means downstream depends on the ladder, which depends on DD1 |
| Risk sizing (B6, B7, DD11) | **Partially** | The 10× formula conflict is independent; the **representation** of a partial is not |
| LIMIT_FVG fill → management | **Yes** | A filled resting order has no production manager to hand off to |

---

# 14. Items Explicitly Blocked Until DD1

| # | Item | Why blocked |
|---|---|---|
| B1 | **F8** — add the missing stop-loss check | Adding it to B canonises B; adding it to A activates an unwired manager |
| B2 | **F10** (D3 + D4) — repair `execute_order` and `manage_positions({})` | Would activate whichever manager is wired, before the choice is made |
| B3 | **F9** — ladder ordering | The remedy (DD5) is defined against the canonical ladder |
| B4 | **M3** — remove the `trade_manager` import from `main_production` | Removal presumes B wins |
| B5 | **M15 / M16** — delete either manager or `main.py`'s lifecycle half | Deleting the loser presumes a winner |
| B6 | **M9** — unify the `TRAIL_SL` log text | The text follows the semantics (DD3) |
| B7 | **M10** — rename `check_partial_exit_1_2`'s `stop_loss` parameter | Only meaningful if A survives |
| B8 | **N1 (new)** — B's direction-blind milestone levels | A real defect, but repairing B is an investment in an unchosen manager |
| B9 | **N2 (new)** — A's stop check not gated on `position_size > 0` | Same reasoning, mirrored |
| B10 | **N3 (new)** — `main.py:913` mock `current_prices = {"spread": 0.5}` | The twin of D4; both feed the entry price forever |
| B11 | **N4 (new)** — `main.py:917-918` drops `CLOSED_SL` trades | Fixing it presumes A's status vocabulary is canonical |
| B12 | **N5 (new)** — B's management state is not persisted | The fix depends on which state machine persists |
| B13 | Backtest partials, trailing, breakeven, reversal (E5-E8) | The backtest must model the chosen manager |
| B14 | `valid_rr` | Unchanged, per Phase 4B §6 and the standing instruction |

**New defects recorded by this investigation (N1-N5) are recorded only.** None is
fixed here, and each must be added to the Fix & Decision Matrix when DD1 is
resolved.

---

# 15. Evidence Classification

| Class | Count | Items |
|---|---|---|
| **[REPO]** | 24 | Comparison axes 1-24; call graphs §3-§4; intent items I1-I16 |
| **[HISTORICAL]** | 8 | H1-H8 |
| **[MEASURED]** | 11 | SELL direction defect; SELL at stop → no action; A stop exit at level; A gapped exit at level; A 1R and 2R transitions; A triple-milestone call; A spurious post-closure `CLOSE_ALL`; B triple-milestone call; B `inactive` after close; B levels 2480/2510 vs correct 2420/2390; suite result §16 |
| **[INFERENCE]** | 5 | Union-is-a-third-implementation; `"state": None` as a vestige; `position_size` 0.5 in persistence demos; gap fill at an untraded price is not defensible; hybrid availability |
| **[DECISION]** | 1 | **DD1 itself**, plus the dependents listed in §13 |
| **[UNRESOLVED]** | 6 | Which half of the structure document is intent; the ATR trailing specification's status; partial-close-then-stop semantics; production gap policy; live/broker semantics; whether reversal protection belongs to the model |

**Explicitly not treated as proof:** module names, function names, the `[L9]`
tag, docstring self-descriptions, and which implementation appears richer, safer,
cleaner or more sophisticated.

---

# 16. Verification Results

**Nothing was modified.** No `.py` file, no test, no fixture, no baseline
artifact. The only new file is this document.

## Read-only measurement

A scratchpad probe (outside the repository, never committed) imported
`order_execution` and `trade_manager` and exercised them in memory. It wrote no
file and touched no repository state. It set `order["status"]` directly in its
own in-memory object to reach `update_current_price` **without** invoking
`execute_order`'s 5 % random-failure path, so the measurement is deterministic.

| Measurement | Result |
|---|---|
| B, SELL 2450 / SL 2480 / TP 2360 | `exit_1_1.price = 2480.00` (**the stop level**), `exit_1_2.price = 2510.00`; correct values are 2420.00 and 2390.00 |
| B, first update at the entry price | actions `["CLOSE_50PCT", "TRAIL_SL"]`, status `TRAILING`, `position_size` unchanged at 0.10, `stop_loss` unchanged at 2480.00 |
| B, price at the stop level | actions `[]`, status still `TRAILING` |
| A, SELL at the entry price | actions `[]`, `OPEN`, size 1.0 |
| A, SELL at the stop level | `CLOSE_ALL`, `exit_price` 2480.00, `CLOSED_SL` |
| A, SELL gapped to 2505 | `exit_price` still **2480.00** |
| A, BUY at 1R | `PARTIAL_CLOSE_50PCT`, size 0.5, `current_sl` 2450.00, `sl_status` `breakeven` |
| A, BUY at 2R | `TRAIL_SL`, `current_sl` 2480.00 (= entry + 1R), `sl_status` `trailing` |
| A, BUY single jump to TP | `["PARTIAL_CLOSE_50PCT", "TRAIL_SL", "CLOSE_ALL_REMAINING"]`, size 0.0, `CLOSED` |
| A, re-called after closure | **`CLOSE_ALL` / `CLOSED_SL` on a closed position** |
| B, BUY single jump to TP | `["CLOSE_50PCT", "TRAIL_SL", "CLOSE_ALL"]`, all priced 2540.00, `position_size` unchanged |
| B, re-called after closure | `{"status": "inactive"}` |

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **664** |
| Duration | 592.6 s |
| Failures | **2** |
| Errors | **0** |

| Test | Status |
|---|---|
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_micro_scalp_l7_confidence_uses_55_threshold` | Pre-existing — reproduces at `04a341d` |
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_pullback_gate_requires_real_pullback_detection` | Pre-existing — reproduces at `04a341d` |

**This matches the expected status exactly** — `664 tests, 2 pre-existing
failures, 0 errors`. Nothing differs, so there is nothing further to
investigate. **[MEASURED]** Both failures are caused by the L2 H1-ATR gate
rejecting the indicators those tests mock; they predate Phase 4A. No test was
modified, and no test was added.

**[REPO]** Note for completeness: `test_week3_verification.py` (§5, I9) lives at
the repository root, not under `tests/`, so `unittest discover -s tests` does not
execute it. It is a print-based script with no assertions and is cited here as
**documentary** evidence of intent, not as a passing test.

---

*Decision evidence only. No code changed, no manager selected, no defect repaired, no parameter chosen. DD1 remains open and blocks the items in §14. Stopping for review.*
