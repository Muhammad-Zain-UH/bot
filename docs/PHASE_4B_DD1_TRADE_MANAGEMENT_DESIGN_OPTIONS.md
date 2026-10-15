# Phase 4B — DD1: Trade Management Design Options

**Decision-enabling document.** No option is selected, recommended, ranked or
scored. No `.py` file, test, baseline, `valid_rr`, risk sizing, SL/TP or backtest
change. No optimisation, no WFO, no Monte Carlo, no profitability claim.
`baseline_004` remains **FROZEN**.

**Predecessor:** `PHASE_4B_DD1_CANONICAL_TRADE_MANAGER.md` (`85590eb`) concluded
**CANONICAL NOT ESTABLISHED — DESIGN DECISION REQUIRED**. This document converts
that evidence into the four available designs and the questions that separate
them.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Directly established by repository code or documentation at `85590eb` |
| **[HISTORICAL]** | Established by git history |
| **[MEASURED]** | Established by executing existing code read-only (§15) |
| **[INFERENCE]** | Reasoned from evidence; not directly stated |
| **[DECISION]** | An explicit design choice is required |
| **[UNRESOLVED]** | Cannot be determined from existing evidence |

## The three categories, applied throughout

| Category | Test applied |
|---|---|
| **EXISTING BEHAVIOUR** | What the repository actually does today |
| **REQUIRED DESIGN DECISION** | The strategy owner must choose; the repository does not answer it |
| **IMPLEMENTATION DEFECT** | Clearly wrong **relative to an intended behaviour the repository itself establishes** — not merely different between A and B |

**A difference between A and B is never by itself called a defect in this
document.**

---

# 1. Executive Summary

Four options are described: **A** (`trade_manager` semantics), **B**
(`order_execution` semantics), **C** (a deliberate hybrid), **D** (a new explicit
broker-agnostic specification with all three existing sources demoted to
historical evidence).

Six findings shape the choice. None of them ranks an option.

1. **[REPO] One axis is already settled and is not part of this decision.**
   Both implementations define risk identically — `|entry − original stop|`,
   fixed at entry — and both derive the final target from `take_profit` as
   supplied by the strategy. Question 1 (the definition of R) and question 12
   (the final TP) therefore have repository answers. The contested axes are what
   happens *between* entry and target.

2. **[MEASURED] B's milestone construction is correct for BUY and inverted for
   SELL.** `create_order` computes `entry + risk` regardless of side. For BUY
   that *is* the 1R level; for SELL the same expression lands on **the stop**.
   This is not a symmetric flaw: BUY behaves as its own docstring describes,
   SELL does not. Adopting B therefore means adopting a repair, not an
   implementation.

3. **[MEASURED] The milestone ladder is out of order in three of four regimes.**
   With `tp_ratio` = 1.5 (MICRO_SCALP, DEAD_CALM) the target sits **below** the
   2R milestone, so trailing is unreachable and measured runs emit only
   `CLOSE_50PCT` then `CLOSE_ALL`. With `tp_ratio` = 2.0 (REGIME_SCALP) the
   target **coincides** with the 2R milestone and all three actions fire in one
   evaluation. Only INTRADAY_SWING (3.0) is ordered. This affects **every**
   option: any model with fixed 1R/2R milestones and a regime-scaled target
   inherits it.

4. **[REPO] Neither implementation can be adopted "as is".** B cannot close a
   losing position and, in the shipped configuration, cannot receive one; A is
   not wired, tracks a fraction with no link to lots, and acts on already-closed
   positions. Every option therefore includes repair work; the options differ in
   **what** is repaired toward, not in whether repair happens.

5. **[REPO] A third specification exists in `config.py`** — trailing activated at
   1× risk with a 0.75 × ATR distance, plus a 240-minute maximum hold and a
   2.0-pip slippage allowance. **No code reads any of them** (§9). It agrees with
   neither manager and is available to any option as a stated intent or
   discardable as dead configuration. That itself is a decision.

6. **[REPO][INFERENCE] A hybrid resolves *where code lives*, not *what the model
   does*.** §5 shows the composable axes are all representational — object model,
   action naming, status, quantity tracking, stop state. Every behavioural axis
   (the 1R stop move, the trailing target, reversal protection, the gap rule, the
   TP/2R tie) still requires exactly the same decisions under C as under A or B.
   Option C does not reduce the number of open questions.

**What this document cannot do:** choose. §10 lists the twenty questions, marked
independent or dependent, whose answers constitute the choice.

---

# 2. Why DD1 Remains Unresolved

Restated from `85590eb`, without re-argument:

| # | Fact | Class |
|---|---|---|
| U1 | `SYSTEM_STRUCTURE_DIAGRAM.md:408-418` labels the Layer 9 box `trade_manager.py` and then describes `order_execution`'s actions inside it | [REPO] |
| U2 | The same document's dependency tree tags `trade_manager.py [L9]` and `order_execution.py [Execution]`, while its mermaid graph wires `order_execution` under `main_production` | [REPO] |
| U3 | `trade_manager.py`, `order_execution.py` and `main_production.py` were all added in one commit, `c3cf4df`; neither manager has been modified since; `main.py` predates them | [HISTORICAL] |
| U4 | No commit message, comment, docstring or test ranks, deprecates or supersedes either module | [HISTORICAL] |
| U5 | `baseline_004` produced **zero trades**; the only persisted trade records are archived as phantom and suspected synthetic | [MEASURED] |
| U6 | Every remaining discriminator — richness, safety, cleanliness, sophistication — is excluded by the standing instruction | [DECISION] |

**[UNRESOLVED]** Which half of the structure document records intent and which
records drift.

---

# 3. Option A — `trade_manager` semantics

**Statement of the option:** the behaviour implemented in `trade_manager.py`
becomes the canonical conceptual model. `order_execution` is reduced to order
placement, matching the `[Execution]` tag in the dependency tree.

## 3.1 What the model would be

| Aspect | Behaviour under Option A | Class |
|---|---|---|
| **Entry** | A creates nothing. A trade record is supplied by the caller; `main.py:898-908` builds one with no sizing, no order object and no broker call | EXISTING BEHAVIOUR [REPO] |
| **Original SL** | `original_stop_loss`, passed per call, never mutated; supplied to the 2R check explicitly (`:430`) so later milestones keep the entry-time basis | EXISTING BEHAVIOUR [REPO] |
| **1R** | `entry ± risk`, computed per call, direction-aware (`:59-63`, `:80-84`) | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **2R** | `entry ± 2 × original_risk` (`:152`, `:178`), gated on the 1R partial having been taken (`:427`) | EXISTING BEHAVIOUR [REPO] |
| **Final TP** | `take_profit` as supplied — `entry ± tp_ratio × risk`. Exit reported **at the TP level** | EXISTING BEHAVIOUR [REPO] |
| **Partial close** | `PARTIAL_CLOSE_50PCT` at 1R; `CLOSE_ALL_REMAINING` at TP | EXISTING BEHAVIOUR [REPO] |
| **Remaining quantity** | A **fraction**: 1.0 → 0.5 → 0.0, held in `trade_state["position_size"]` | EXISTING BEHAVIOUR [REPO] |
| **Breakeven** | At 1R the stop moves to entry; `sl_status = "breakeven"` | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Trailing** | At 2R the stop moves to `entry + 1R`, locking 1R; `sl_status = "trailing"` | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Reversal protection** | `check_breakeven_stop`: while the stop is at or above breakeven and the position is open, a return to within **$2.00** of entry closes the remainder as `CLOSE_BREAKEVEN_PROTECTION` | EXISTING BEHAVIOUR [REPO] |
| **Stop-loss handling** | Explicit comparison against `current_sl`, evaluated **first**, returning immediately; exit priced **at the stop level** | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Position closure** | `trade_status` ∈ `OPEN` / `CLOSED` / `CLOSED_SL`, plain strings | EXISTING BEHAVIOUR [REPO] |
| **Repeated milestone handling** | `exit_1_1_taken` and `exit_1_2_status` one-shot flags | EXISTING BEHAVIOUR [REPO] |
| **Event ordering** | stop → 1R → 2R → TP → reversal protection, all reachable within one evaluation | EXISTING BEHAVIOUR [MEASURED] |
| **Gap handling** | Exit reported at the stop or TP **level regardless of gap size** — measured: price 2505 against a 2480 stop still reported 2480.00 | EXISTING BEHAVIOUR [MEASURED] |

## 3.2 What adopting A would require deciding

| # | Question | Class |
|---|---|---|
| A-d1 | How the fraction (0.5) binds to lots — A has no concept of lots anywhere | REQUIRED DESIGN DECISION [DECISION] |
| A-d2 | Whether the exit price of a gapped stop stays at the level | REQUIRED DESIGN DECISION [DECISION] |
| A-d3 | Whether a stop-out after a partial closes the remaining half only (it currently emits `CLOSE_ALL`) and how it is labelled — a breakeven stop-out is reported `"pnl": "LOSS"` | REQUIRED DESIGN DECISION [DECISION] |
| A-d4 | Whether the $2.00 reversal buffer is a price or a pip quantity (the parameter is named `breakeven_trigger_pip_buffer` and subtracted from a price) | REQUIRED DESIGN DECISION [DECISION], same family as F7 |
| A-d5 | Who owns and persists `trade_state` once `main_production` is the entry point | REQUIRED DESIGN DECISION [DECISION] |

## 3.3 Defects that would remain to be repaired under A

| # | Defect | Why it qualifies | Class |
|---|---|---|---|
| A-f1 | The stop check is not gated on `position_size > 0`. Measured: re-called after full closure, A emits `CLOSE_ALL` / `CLOSED_SL` on a closed position | Every other milestone in the same function is guarded; the function's own contract is "manage an **open** trade" | IMPLEMENTATION DEFECT [MEASURED] |
| A-f2 | `main.py:917-918` partitions on `"CLOSED"` and `"OPEN"`, so a `CLOSED_SL` trade is dropped from the open list **and** never counted as closed | The code's own intent is a two-way partition, and it logs "N trade(s) closed" | IMPLEMENTATION DEFECT [REPO] |
| A-f3 | `main.py:913` passes `current_prices = {"spread": 0.5}`, so the manager always receives the **entry price** | The parameter is named `current_prices` and keyed by `trade_id`; the twin of D4 | IMPLEMENTATION DEFECT [REPO] |
| A-f4 | `exit_1_2_status` declares `"completed"` at `:370` and never assigns it | Declared state with no producer | IMPLEMENTATION DEFECT [REPO] |
| A-f5 | `main_production`'s action handler has **no branch** for `PARTIAL_CLOSE_50PCT`, `CLOSE_ALL_REMAINING` or `CLOSE_BREAKEVEN_PROTECTION`; wiring A without extending it would silently drop them | The handler exists to act on actions | IMPLEMENTATION DEFECT [REPO] |

## 3.4 Behavioural consequences

- **[INFERENCE]** Every trade reaching 1R becomes risk-free by construction. This
  changes the shape of the outcome distribution, not only its scale, and no
  measurement in this repository describes that effect.
- **[MEASURED]** In MICRO_SCALP and DEAD_CALM (`tp_ratio` 1.5) the 2R trailing
  step is unreachable: the measured action sequence is
  `PARTIAL_CLOSE_50PCT` → `CLOSE_ALL_REMAINING`.
- **[MEASURED]** In REGIME_SCALP (`tp_ratio` 2.0) `TRAIL_SL` and
  `CLOSE_ALL_REMAINING` fire in the **same** evaluation — the stop is moved on a
  position that closes immediately afterwards.
- **[REPO]** `order_execution` would keep order creation, ids, statuses and the
  execution attempt; only management moves to A.

---

# 4. Option B — `order_execution` / `main_production` semantics

**Statement of the option:** the behaviour implemented in `order_execution.py`,
as driven by `main_production.py`, becomes the canonical conceptual model.

## 4.1 What the model would be

| Aspect | Behaviour under Option B | Class |
|---|---|---|
| **Entry** | `execute_entry_signal` sizes the position, `create_order` builds an order object carrying its three exit levels, `execute_order` attempts execution | EXISTING BEHAVIOUR [REPO] |
| **Original SL** | `order["stop_loss"]`, written once and never modified — preserved by omission rather than by rule | EXISTING BEHAVIOUR [REPO] |
| **1R** | `entry + risk_distance`, fixed at creation, **not** direction-aware (`:117`) | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **2R** | `entry + 2 × risk_distance`, fixed at creation, not direction-aware (`:118`) | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Final TP** | `exit_1_3.price = take_profit` — correct for both directions. Exit priced **at the observed price**, not the level | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Partial close** | `CLOSE_50PCT` action and status `PARTIAL`. `main_production:1179-1180` **logs it and changes nothing** | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Remaining quantity** | Not tracked. `position_size` (lots) is written at creation and never again | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Breakeven** | No move at 1R. At 2R a stop at entry is *suggested* via the action payload and applied by no one | EXISTING BEHAVIOUR [REPO] |
| **Trailing** | `TRAIL_SL` at 2R with `new_sl = entry` — locking nothing. `profit_locked` reports `abs(entry − stop)`, the full risk | EXISTING BEHAVIOUR [REPO] |
| **Reversal protection** | None | EXISTING BEHAVIOUR [REPO] |
| **Stop-loss handling** | **No comparison exists.** Measured: at the stop level, zero actions, status unchanged | EXISTING BEHAVIOUR [REPO][MEASURED] |
| **Position closure** | `OrderStatus` enum; `CLOSED` on TP; `main_production:1185` removes the trade from `_OPEN_TRADES` | EXISTING BEHAVIOUR [REPO] |
| **Repeated milestone handling** | `triggered` flags plus a status gate that returns `{"status": "inactive"}` once `CLOSED` | EXISTING BEHAVIOUR [MEASURED] |
| **Event ordering** | 1R → 2R → TP, all reachable in one evaluation; no stop step exists | EXISTING BEHAVIOUR [MEASURED] |
| **Gap handling** | Always the observed price; the stop case does not arise because there is no stop check | EXISTING BEHAVIOUR [MEASURED] |

## 4.2 The measured defects and ambiguities, as they currently exist

**Not repaired here. Consequences only.**

| # | Item | Consequence as it exists | Class |
|---|---|---|---|
| B-f1 | **Direction-blind `exit_1_1`** | For SELL the 1R level **equals the stop** (§8). The trigger `current_price <= exit_1_1` is satisfied at every price at or below the stop, so `CLOSE_50PCT` fires on the first update — including on a position sitting at a full loss, where it reports "1:1 RR reached" | IMPLEMENTATION DEFECT [MEASURED] — wrong against the function's own "1:1 RR" contract, and against its own BUY branch |
| B-f2 | **Direction-blind `exit_1_2`** | For SELL the 2R level is `entry + 2 × risk` = 2510, **beyond the stop on the losing side**. Measured: `TRAIL_SL` fires in the same first update as `CLOSE_50PCT`, at the entry price | IMPLEMENTATION DEFECT [MEASURED] |
| B-f3 | **No stop-loss comparison** | A losing position is never closed by the manager. The only closure is TP. Measured: at the stop, no action; status stays `PARTIAL`/`TRAILING` indefinitely | EXISTING BEHAVIOUR [REPO][MEASURED] — becomes a REQUIRED DESIGN DECISION (is the stop delegated to a broker-side order?) |
| B-f4 | **`TRAIL_SL` semantics** | Moves the stop to entry (locks zero) while reporting `profit_locked` = the full risk. A names the same action and moves to `entry + 1R` | Payload is wrong against its own field name: IMPLEMENTATION DEFECT [REPO]. Which *level* is intended: REQUIRED DESIGN DECISION |
| B-f5 | **No quantity tracking** | `PARTIAL` is a status, not a size. After a partial, the recorded position is still the full lot size | EXISTING BEHAVIOUR [REPO] — REQUIRED DESIGN DECISION |
| B-f6 | **No reversal protection** | A position that runs to 1R and reverses gives back the move; nothing intervenes | EXISTING BEHAVIOUR [REPO] |
| B-f7 | **Hardcoded 1R/2R while TP scales with `tp_ratio`** | The ladder is ordered only for INTRADAY_SWING (§8.3) | EXISTING BEHAVIOUR [MEASURED] — REQUIRED DESIGN DECISION (DD5) |
| B-f8 | **Actions are log-only** | `CLOSE_50PCT` and `TRAIL_SL` reach `main_production`, which writes a log line and changes nothing. Adopting B unchanged means **no partials and no trailing occur at all** | IMPLEMENTATION DEFECT [REPO] against the actions' declared meaning — though it also reads as unfinished scope; **[UNRESOLVED]** which |
| B-f9 | **Management state is not persisted** | `OrderExecutor.orders` is in memory. After a restart, `restore_state()` reloads trades whose `order_id` the executor does not know, and `update_current_price` returns `{"status": "error"}` — restored positions are unmanageable | EXISTING BEHAVIOUR [REPO] |
| B-f10 | **`execute_order` cannot succeed** | `simulation=False`, `mt5_handler=None` → the `else` branch returns `False` without raising, so the order stays `PENDING`, `_OPEN_TRADES.append` is unreachable, and no position is ever recorded | IMPLEMENTATION DEFECT [REPO] (D3) |
| B-f11 | **Dead statuses** | `SENT` appears only in a filter list; `EXPIRED` is never referenced | EXISTING BEHAVIOUR [REPO] |

## 4.3 What happens when TP is below a milestone — measured

See §8.3 for the full table. Summary: with `tp_ratio` 1.5 the 2R level lies
beyond the target, so `TRAIL_SL` never fires; with `tp_ratio` 2.0 the 2R level
**is** the target and `TRAIL_SL` and `CLOSE_ALL` fire in the same evaluation.

## 4.4 BUY and SELL separately

| | BUY | SELL |
|---|---|---|
| 1R level | `entry + risk` — **correct** | `entry + risk` — **equals the stop** |
| 2R level | `entry + 2 × risk` — **correct** | `entry + 2 × risk` — beyond the stop |
| TP level | `take_profit` — correct | `take_profit` — correct |
| Measured first update at the entry price | no action | `CLOSE_50PCT` **and** `TRAIL_SL` |
| Measured at the true 1R | `CLOSE_50PCT` | nothing (already consumed) |
| Measured at the stop | nothing | nothing |

---

# 5. Option C — Deliberate Hybrid

**Question posed:** can a coherent hybrid be specified **without inventing
undocumented behaviour**?

## 5.1 Component-by-component

| Component | Source | Composable without invention? | Class |
|---|---|---|---|
| Order object, order id, `OrderStatus`, re-entry guard | B | **Yes** — self-contained, no behavioural conflict with A | [REPO] |
| Milestone **naming** (`CLOSE_50PCT` / `TRAIL_SL` / `CLOSE_ALL`) | B | **Yes** — naming is orthogonal to semantics; `main_production`'s handler already branches on these names | [REPO] |
| **TP configuration** (`exit_1_3 = take_profit`, from `tp_ratio`) | B | **Yes, and trivially** — A uses the identical value. **The two implementations do not differ on this axis at all** | [REPO] |
| Stop-loss **check** | A | **Yes**, but it requires a mutable stop field, which B's order object lacks. Adding the field is representational, not behavioural | [INFERENCE] |
| Partial **quantity tracking** | A | **Yes** as a mechanism — but A's fraction has no defined relationship to B's lots. The mapping `fraction × initial lots` is stated **nowhere** | [DECISION] |
| **Reversal protection** | A | Mechanically yes. But adopting it is **choosing A's answer** to "does reversal protection exist", not composing | [DECISION] |
| Direction-aware milestone **construction** | A | Required, since B's SELL levels are inverted — this is a **repair**, not a composition | [REPO] |
| **Gap rule** (level when not gapped, bar open when gapped) | `paper_broker` | Available and **tested**, but importing a backtest policy into production intent was flagged as circular as *evidence*; as a *choice* it is open | [DECISION] |
| Intrabar contention (stop wins) | `paper_broker` | Same status | [DECISION] |
| ATR trailing at 1R, 240-minute hold, slippage | `config.py` | **No implementation exists anywhere** (§9). Adopting these would be new design, i.e. Option D | [UNRESOLVED] |

## 5.2 What a hybrid does **not** resolve

**[INFERENCE]** Every axis below remains exactly as open under C as under A or B,
because the two implementations give contradictory answers and neither answer is
established:

| Axis | A says | B says | Still a decision under C? |
|---|---|---|---|
| Stop position after 1R | breakeven | unchanged | **Yes** |
| Trailing target at 2R | `entry + 1R` | `entry` | **Yes** |
| Does reversal protection exist? | yes | no | **Yes** |
| Quantity base | fraction | lots, unchanged | **Yes** |
| Gapped exit price | the level | observed price | **Yes** |
| TP = 2R tie | both fire | both fire | Agreed — **no** |
| Definition of R | `\|entry − original stop\|` | same | Agreed — **no** |

## 5.3 Conclusion for Option C

**[INFERENCE]** A hybrid **is** specifiable without invention, but only on the
**representational** axes: object model, action naming, status enum, quantity
*mechanism*, stop-state *field*, and the TP source on which A and B already
agree. **Every behavioural axis still requires the same decisions.** Option C
therefore changes where the code lives and what it is called; it does not reduce
the open-question count in §10.

**[REPO]** Option C also necessarily includes at least one repair — B's SELL
milestone construction — so it is not reducible to "assembling existing parts".

---

# 6. Option D — New Explicit Canonical Trade Model

**Statement of the option:** neither implementation becomes the source of truth.
`trade_manager`, `order_execution` and the `config.py` constants are all demoted
to **historical evidence**. A new broker-agnostic trade-management specification
becomes canonical, and both implementations are later aligned to it or replaced.

**The model itself is not designed here.**

## 6.1 Why this option exists

| # | Reason | Class |
|---|---|---|
| D-r1 | **"Adopt as-is" is not actually available.** B cannot close a loser or receive a position; A is unwired, acts on closed positions and tracks a fraction with no link to lots. Every option includes repair | [REPO] |
| D-r2 | **The documentation names one implementation and describes the other**, so neither is a faithful record of intent | [REPO] |
| D-r3 | **A third specification exists** in `config.py` and agrees with neither | [REPO] |
| D-r4 | **The backtest already holds exit semantics neither production manager has** — the gap rule, `IntrabarPolicy`, R1 fill-bar evaluation — and Phase 4A added a pending-order lifecycle with no production counterpart. A specification is the only artifact that can bind both sides | [REPO] |
| D-r5 | **No empirical record ties either implementation to results.** `baseline_004` produced zero trades; archived records are phantom and suspected synthetic | [MEASURED] |
| D-r6 | The ladder disorder (§8.3) is a property of the *model*, not of either implementation, and would survive adopting either one unchanged | [MEASURED] |

## 6.2 What must be answered before such a specification can be written

**[DECISION]** All twenty questions in §10. In addition, four that are specific to
writing a specification rather than choosing an implementation:

| # | Question | Class |
|---|---|---|
| D-q1 | Is the model **polling-based** (the bot observes a price and acts, as both managers assume) or **resting-order-based** (stops and targets live at the broker and fill without observation)? The two produce different fills for the same market path | [DECISION] |
| D-q2 | Is the unit of management a **position** (one record whose size shrinks) or **several orders** (each closed independently)? A assumes the first; B's status enum implies the first; the milestone vocabulary implies the second | [DECISION] |
| D-q3 | What is the authoritative **quantity unit** — lots, fraction, or both with a stated mapping? | [DECISION] |
| D-q4 | Does the specification bind **production and backtest identically**, and what test demonstrates the binding? | [DECISION] |

## 6.3 Decisions that would have to be explicit

**[DECISION]** Under D nothing may be inherited silently: each of the twenty
questions receives a stated answer with a stated rationale, including the answers
that happen to match A, B or `config.py`. The distinguishing property of Option D
is not that the answers differ — it is that **no answer is inherited by default**.

---

# 7. Full Behaviour Comparison

Cells describe. They do not evaluate. "**Must be specified**" means the option
provides no answer by construction.

| Behaviour | Option A — `trade_manager` | Option B — `order_execution` | Option C — Hybrid | Option D — New model |
|---|---|---|---|---|
| **Initial SL** | From the strategy; `original_stop_loss`, never mutated | From the strategy; `order["stop_loss"]`, never written again | Same value; held in B's object with A's mutable-stop field added | Must be specified (Q1 basis) |
| **Risk / R definition** | `\|entry − original stop\|`, fixed at entry | `abs(entry − stop)`, fixed at creation | Identical — **A and B agree** | Must be stated; the repository answer is available |
| **1R event** | Computed per call, direction-aware | Precomputed, direction-blind (**SELL = the stop**) | A's construction required (B's is inverted for SELL) | Must be specified |
| **1R SL movement** | → breakeven (entry) | none | **Decision — unresolved by composition** | Must be specified (Q4) |
| **1R partial** | Close 50 %; fraction 1.0 → 0.5 | `CLOSE_50PCT` emitted; **nothing closes**; size unchanged | Mechanism from A, naming from B; the **percentage** is still a decision | Must be specified (Q3) |
| **2R event** | `entry ± 2 × original_risk`, gated on the 1R partial | Precomputed, direction-blind; **not** gated on side | A's construction; B's gating is equivalent | Must be specified |
| **2R SL movement** | → `entry + 1R` (locks 1R) | → `entry` (locks nothing), never applied | **Decision — three candidate values incl. `config.py`** | Must be specified (Q7) |
| **2R partial** | None — 2R is a stop move only | None — status change only | None in either source | Must be specified (Q6) |
| **Final TP** | `take_profit` (= `tp_ratio × risk`); exit **at the level** | `take_profit`; exit **at the observed price** | Same value; the **pricing rule** is a decision | Must be specified (Q12) |
| **Trailing** | One step at 2R, to `entry + 1R` | One step at 2R, to `entry`; log-only | Decision; a continuous ATR trail exists only in `config.py`, unimplemented | Must be specified (Q8-Q10) |
| **Breakeven protection** | Stop to entry at 1R | None | Decision | Must be specified (Q4) |
| **Reversal protection** | `CLOSE_BREAKEVEN_PROTECTION` within $2.00 of entry while the stop ≥ breakeven | None | Decision — adopting A's is choosing, not composing | Must be specified (Q11) |
| **Remaining quantity** | Fraction 1.0 / 0.5 / 0.0, no link to lots | Lots, never changed | Mechanism composable; **the lots↔fraction mapping is stated nowhere** | Must be specified (Q17, D-q3) |
| **Stop-loss check** | Explicit, in-manager | **Absent** | A's check, if the stop is a bot responsibility | Must be specified (Q14, D-q1) |
| **Stop vs milestone ordering** | Stop first, returns immediately | No stop step exists | Follows whichever stop model is chosen | Must be specified (Q14) |
| **Gap-through-stop** | Exit **at the level**, regardless of gap size | No stop check | Backtest rule available (level, or bar open when gapped) — tested | Must be specified (Q15-Q16) |
| **Same-bar events** | No bar concept; per price sample. Multiple milestones fire in one evaluation | Same | Same — **neither source models a bar** | Must be specified (D-q1, Q20) |
| **Multiple positions** | `main.py` caps at `CONFIG["max_concurrent_trades"] = 3` | `main_production` caps at 3 | Identical; backtest `max_open_positions = 3` | Must be stated; all three sources agree on 3 |
| **Position closure** | `CLOSED` / `CLOSED_SL` strings; `main.py` drops `CLOSED_SL` | `OrderStatus.CLOSED`; trade removed from `_OPEN_TRADES` | B's enum with A's terminal reasons | Must be specified (Q18) |
| **Pending LIMIT_FVG hand-off** | **None.** A has no pending concept | **None.** `OrderType` has BUY/SELL only | **None in either source.** Only `paper_broker` fills a resting order, into a position managed by stop/TP alone | Must be specified (Q19) |
| **Backtest representation** | Not modelled: no partials, no trailing, no breakeven, no reversal | Not modelled either; the backtest's stop handling has no production counterpart | Whatever is composed still needs E5-E12 | Specification binds both sides by construction (D-q4) |

---

# 8. SELL / BUY Geometry Analysis

Measured with entry 2450.00 and risk 30.00, across all four regime `tp_ratio`
values. **Nothing was fixed.**

## 8.1 SELL — the measured case

```
SELL
entry = 2450.00
stop  = 2480.00          (above entry)
risk  = 30.00

correct 1R = entry - risk      = 2420.00
correct 2R = entry - 2 x risk  = 2390.00

existing (order_execution.create_order:117-118):
exit_1_1 = entry + risk_distance     = 2480.00   <-- THE STOP LEVEL
exit_1_2 = entry + 2 x risk_distance = 2510.00   <-- beyond the stop
exit_1_3 = take_profit                            <-- correct
```

**Consequence — [MEASURED].** The SELL trigger is
`current_price <= exit_1_1["price"]`. Since `exit_1_1` is 2480.00, that
comparison is true at **every price at or below the stop**, which includes the
entry price itself. A measured first update at 2450.00 — no favourable move at
all — emitted:

```
["CLOSE_50PCT", "TRAIL_SL"]      order status -> TRAILING
```

Because `exit_1_2` (2510.00) is also above the entry, `TRAIL_SL` fires in the
same call. Both flags are then consumed, so the position's real 1R (2420.00)
later passes **unremarked**: measured actions at 2420.00 were `[]`.

Two further consequences:

- **[MEASURED]** A SELL that goes straight to a loss reports `CLOSE_50PCT` with
  `"level": "1:1 RR"` — a profit-taking action on a losing position.
- **[MEASURED]** `exit_1_3` (the target) is taken from the strategy and is
  **correct for SELL**, so the only closure path B has works; the two milestones
  in front of it do not.

## 8.2 BUY — the equivalent analysis

```
BUY
entry = 2450.00
stop  = 2420.00          (below entry)
risk  = 30.00

correct 1R = 2480.00 ; correct 2R = 2510.00
existing:  exit_1_1 = 2480.00 ; exit_1_2 = 2510.00      <-- both correct
```

**[MEASURED]** For BUY the direction-blind expression coincides with the correct
levels, because `entry + risk` *is* the BUY 1R. Measured: no action at the entry
price, `CLOSE_50PCT` at 2480.00, `[]` at the stop (no stop check).

**[INFERENCE]** The defect is therefore **not symmetric**. B's BUY path behaves
as its own docstring describes; only SELL is inverted. This matters for any
option that adopts B's construction: the repair is one-sided, and no existing
test or demo would have exposed it, because **neither module's `__main__` demo
drives a SELL through the milestone path**. `trade_manager`'s demo is BUY-only
(`:551-593`); `order_execution`'s creates SELL orders at `:368` but never calls
`update_current_price` on them — it only counts open orders.

**[MEASURED]** A is direction-aware in both branches: measured SELL and BUY
produce mirror-image behaviour, and A's stop check fired correctly on both sides
(`CLOSE_ALL`, `CLOSED_SL`, exit priced at the stop level).

## 8.3 The ladder against each regime's `tp_ratio`

`REGIME_TP_RATIO` — [REPO] `entry_engine.detect_regime`, mirrored in
`backtest/baseline.py:336-341`.

| Regime | `tp_ratio` | TP vs 2R | Measured A on a single jump to TP | Measured B on a single jump to TP |
|---|---|---|---|---|
| MICRO_SCALP | 1.5 | **TP below 2R** | `PARTIAL_CLOSE_50PCT` → `CLOSE_ALL_REMAINING` — **no trail** | `CLOSE_50PCT` → `CLOSE_ALL` — **no trail** |
| DEAD_CALM | 1.5 | **TP below 2R** | same | same |
| REGIME_SCALP | 2.0 | **TP equals 2R** | `PARTIAL_CLOSE_50PCT` → `TRAIL_SL` → `CLOSE_ALL_REMAINING`, one evaluation | `CLOSE_50PCT` → `TRAIL_SL` → `CLOSE_ALL`, one evaluation |
| INTRADAY_SWING | 3.0 | TP above 2R | ordered | ordered |

**[MEASURED]** In three of four regimes the fixed 1R/2R ladder is not ordered
with respect to the regime-scaled target: trailing is unreachable in two and
simultaneous with closure in one. **[INFERENCE]** This is a property of the
*model* — fixed milestones plus a scaled target — so it survives into any option
that keeps both, including C and D.

---

# 9. `config.py` — The Third Specification

## 9.1 Exact fields

| Field | Value | Comment in source | Line |
|---|---|---|---|
| `TRAILING_STOP_ATR_TRIGGER` | `1.0` | "Activate at 1× risk profit" | `config.py:150` |
| `TRAILING_STOP_ATR_TRAIL` | `0.75` | "Trail by 75% of entry ATR" | `config.py:151` |
| `INTRADAY_MAX_HOLD_MINUTES` | `240` | "Exit by 4-hour mark" | `config.py:157` |
| `INTRADAY_MIN_HOLD_MINUTES` | `5` | "Minimum 5 minutes before trailing" | `config.py:158` |
| `MAX_SLIPPAGE_PIPS` | `2.0` | "Covers realistic spread (1.5pips) + latency (was 0.5)" | `config.py:147` |

## 9.2 Findings

| # | Question | Finding | Class |
|---|---|---|---|
| C1 | Are they read anywhere? | **No.** The only reference in the repository is `test_integration.py:111`, which asserts the attribute *exists* — it does not use the value | [REPO] |
| C2 | Does any manager implement them? | **No.** Neither manager references ATR, elapsed time or slippage. A trails one step to `entry + 1R` at 2R; B suggests `entry` at 2R | [REPO] |
| C3 | Does documentation refer to them? | Only as already-recorded defects: `PHASE_2_ISSUES.md` R9 ("`INTRADAY_MAX_HOLD_MINUTES = 240` defined, never enforced. No time stop") and E12 (`MAX_SLIPPAGE_PIPS` "defined and never referenced"). **No design document describes an ATR trailing model** | [REPO] |
| C4 | Does git history establish their origin? | **No.** `git log -S` places all five in `c3cf4df` (2026-07-01) — the same single commit that added both managers, `main_production` and the four analysis documents. There is no separate introduction, no later revision, and no commit message about them | [HISTORICAL] |
| C5 | Is a time-based exit implemented anywhere? | **No.** Neither manager, nor the backtest, has any notion of elapsed holding time | [REPO] |

## 9.3 What this does and does not establish

**[UNRESOLVED]** Existence is not intent. These constants are equally consistent
with (i) a trailing model that was specified and never built, (ii) constants
copied from another system, and (iii) an abandoned direction. Nothing in the
repository distinguishes these readings.

**[DECISION]** Whether the ATR trailing model, the 240-minute maximum hold and
the slippage allowance are part of the canonical model is itself a decision,
available under **every** option — including the decision to declare them dead
configuration and remove them.

**[INFERENCE]** They are relevant to DD1 because they contradict the trailing
semantics of both implementations on the axis where A and B already contradict
each other: **what happens to the stop as the position runs.**

---

# 10. Required Design Questions

Twenty questions, each marked **INDEPENDENT** (answerable now, in any order) or
**DEPENDENT** (requires an earlier answer).

| # | Question | Status | Repository answer available? |
|---|---|---|---|
| Q1 | What is the canonical definition of R? | **INDEPENDENT** | **Yes — [REPO].** Both implementations use `\|entry − original stop\|`, fixed at entry. Confirmation is still required, but no conflict exists |
| Q2 | What happens at 1R? | **INDEPENDENT** | No — A partials and moves the stop; B marks a status |
| Q3 | What percentage is closed at 1R? | Depends on Q2 | Both say 50 % **where anything closes at all**; B closes nothing |
| Q4 | What happens to the SL after 1R? | **INDEPENDENT** | No — breakeven (A) vs unchanged (B) |
| Q5 | What happens at 2R? | **INDEPENDENT** | No — stop move (A) vs status + unapplied suggestion (B) |
| Q6 | What percentage is closed at 2R? | Depends on Q5 | Both say none |
| Q7 | What happens to the SL after 2R? | Depends on Q4 | No — `entry + 1R` (A) vs `entry` (B) vs ATR trail (`config.py`) |
| Q8 | Is there trailing at all? | **INDEPENDENT** | No — one discrete step in both managers; a continuous ATR trail in `config.py`, unimplemented |
| Q9 | When does trailing activate? | Depends on Q8 | No — 2R (both managers) vs 1× risk (`config.py`) |
| Q10 | What is the trailing distance? | Depends on Q8, Q9 | No — a fixed level in both managers vs `0.75 × ATR` in `config.py` |
| Q11 | What happens on reversal after breakeven? | Depends on Q4 | No — `CLOSE_BREAKEVEN_PROTECTION` within $2.00 (A) vs nothing (B). The $2.00 unit is itself undecided |
| Q12 | What is the final TP? | **INDEPENDENT** | **Yes — [REPO].** `entry ± tp_ratio × risk`, identical in both |
| Q13 | What happens when TP is below a milestone? | Depends on Q2, Q5, Q12 | No — measured behaviour exists (§8.3) but no rule is stated |
| Q14 | What happens if the SL and a milestone are both reachable? | Depends on Q2 | Partly — A returns on the stop first; B has no stop. The backtest resolves stop-first under CONSERVATIVE, which is a backtest policy |
| Q15 | What happens on a gap through the SL? | **INDEPENDENT** | No — the level (A), nothing (B), the bar open (backtest) |
| Q16 | What happens on a gap through the TP? | **INDEPENDENT** | No — the level (A), the observed price (B), the bar open (backtest) |
| Q17 | What happens to the remaining quantity after partial exits? | Depends on Q3 | No — fraction (A) vs untracked (B); no lots↔fraction mapping anywhere |
| Q18 | How are repeated milestone events prevented? | Depends on Q2, Q5 | Partly — one-shot flags in both; A's stop check is ungated and re-fires on closed positions |
| Q19 | How does a LIMIT_FVG fill enter the management lifecycle? | Depends on Q1-Q18 | **No — no production path exists.** Only `paper_broker` fills a resting order, into a position managed by stop/TP alone |
| Q20 | How does the model map identically into backtest and live execution? | Depends on **all** of the above | No — and the polling vs resting-order question (D-q1) must be answered first |

**Independent set (answerable immediately, in any order):**
Q1, Q2, Q4, Q5, Q8, Q12, Q15, Q16 — plus D-q1 and D-q2 if Option D is taken.

**[INFERENCE]** Q1 and Q12 are confirmations rather than open choices; the
repository gives a single consistent answer for each. The genuinely open
independent questions are **Q2, Q4, Q5, Q8, Q15, Q16**. Everything else follows.

---

# 11. Dependency Graph

## 11.1 The proposed chain, tested

The chain suggested in the brief was:

```
Canonical R -> Milestone levels -> Partial quantities -> Stop movement
   -> Trailing -> Position closure -> Backtest equivalence
```

**[INFERENCE] Two of those links are not real dependencies:**

- **Milestone levels → partial quantities: NOT a dependency.** How much is closed
  does not follow from where the level sits. Both depend separately on "what
  happens at this milestone" (Q2/Q5).
- **Partial quantities → stop movement: NOT a dependency.** The stop move at 1R
  is independent of the fraction closed there; A performs both, but neither
  determines the other.

**Two links hold:**

- **Canonical R → milestone levels: holds.** Levels are multiples of R.
- **Stop movement → trailing: holds.** Trailing is a continuation of the stop
  rule; `entry + 1R` is only coherent if the stop already moved to entry.

## 11.2 Derived graph

```
        Q1  CANONICAL R   [REPO answer available: |entry - original stop|]
                 |
                 v
        MILESTONE LEVELS  (1R, 2R, tp_ratio x R)   [REPO]
                 |
        +--------+--------------------------+
        v                                   v
   Q2/Q5 WHAT HAPPENS AT EACH MILESTONE     Q12 FINAL TP  [REPO]
        |                                   |
   +----+----+                              |
   v         v                              |
 Q3/Q6     Q4/Q7                            |
 CLOSE     STOP MOVE                        |
 FRACTION  (breakeven? lock 1R?)            |
   |         |                              |
   |         v                              |
   |    Q8/Q9/Q10 TRAILING <--- config.py third spec [UNRESOLVED]
   |         |                              |
   |         v                              |
   |    Q11 REVERSAL PROTECTION             |
   |         |                              |
   v         v                              v
 Q17 QUANTITY   Q14 STOP vs MILESTONE   Q13 TP BELOW MILESTONE
 REPRESENTATION     ORDERING                (ladder ordering, DD5)
        |              |                          |
        +------+-------+--------------------------+
               v
        Q18 REPEATED-EVENT PREVENTION
               |
               v
        POSITION CLOSURE  (terminal states, reasons)
               |
        +------+-------------------+
        v                          v
  Q15/Q16 GAP RULES         Q19 LIMIT_FVG FILL -> MANAGEMENT
  [INDEPENDENT of the           (needs an owner: DD1/DD2)
   ladder; a pricing rule]           |
        |                            |
        +-------------+--------------+
                      v
        Q20 BACKTEST <-> LIVE EQUIVALENCE   (E5-E12)
                      |
                      v
              NEW CANONICAL BASELINE
                      |
                      v
              DD15 valid_rr  (options 1 and 2 need outcome evidence)
```

## 11.3 Where the named items attach

| Item | Depends on the canonical trade model? | Precisely how |
|---|---|---|
| **`valid_rr`** | **Yes, indirectly** | Through Q13 / DD5. `rr ≡ tp_ratio`, so the gate's meaning depends on whether `tp_ratio` also controls the ladder. If milestones scale with `tp_ratio`, the gate governs the whole ladder; if `tp_ratio` is floored instead, it governs only the target. **[DECISION]** — unchanged until the model is chosen |
| **Risk sizing** | **Only partially** | The 10× formula conflict (`risk/(stop×10)` vs `risk/(stop×100)`) and the hardcoded balance are **independent** of DD1 — they are DD11 and F4. What *does* depend on DD1 is Q17: whether a partial is expressed in lots or as a fraction |
| **LIMIT_FVG** | **Yes** | A filled resting order must be handed to a manager. Today `paper_broker` manages it with stop/TP only, and production has no pending-order type at all. Q19 |
| **Pending-order lifecycle** | **Partly** | Expiry, zone invalidation and cross-session cancellation are *strategy* decisions (X1-X3), independent of trade management. But what happens **after** a fill is Q19, which is DD1's |

---

# 12. Downstream Decisions

| Decision | Blocked by | Unblocked when |
|---|---|---|
| DD2 lifecycle ownership | DD1 | An option is chosen |
| DD3 `TRAIL_SL` semantics | Q4, Q7, Q8 | Q7 answered |
| DD4 stop position at 1R | Q4 | Q4 answered |
| DD5 ladder-ordering remedy | Q13, Q2, Q5 | Q13 answered |
| DD6 `tp_ratio = 2` tie | Q13 | Q13 answered — measured behaviour is "all three actions in one evaluation" (§8.3) |
| DD7 reversal protection | Q11 | Q11 answered |
| DD8 remaining-quantity representation | Q17 | Q17 answered |
| DD9 gap fill price | Q15, Q16 | Q15/Q16 answered — **independent of everything else** |
| DD10 same-bar 1R-then-stop | Q14 | Q14 answered |
| DD15 `valid_rr` | Q13 → DD5, then outcome evidence | After a new canonical baseline |
| E5-E12 backtest alignment | Q20 | After the model is fixed |
| D11 position lifecycle states | Q3, Q17 | Partial states are needed only if partials exist |
| F8, F9, F10 | DD1 | An option is chosen |

---

# 13. Items Blocked Until DD1

Unchanged from `85590eb` §14, restated for completeness. **None may be touched.**

| # | Item |
|---|---|
| 1 | **F8** — adding the missing stop-loss check |
| 2 | **F10** (D3 + D4) — repairing `execute_order` and `manage_positions({})` |
| 3 | **F9** — ladder ordering |
| 4 | **M3** — removing the `trade_manager` import from `main_production` |
| 5 | **M15 / M16** — deleting either manager or `main.py`'s lifecycle half |
| 6 | **M9** — unifying the `TRAIL_SL` log text |
| 7 | **M10** — renaming `check_partial_exit_1_2`'s `stop_loss` parameter |
| 8 | **N1** — B's SELL milestone inversion (§8.1) |
| 9 | **N2** — A's stop check firing on a closed position |
| 10 | **N3** — `main.py:913` mock `current_prices` |
| 11 | **N4** — `main.py:917-918` dropping `CLOSED_SL` |
| 12 | **N5** — B's management state not being persisted |
| 13 | **E5-E8** — backtest partials, trailing, breakeven, reversal |
| 14 | **`valid_rr`** — unchanged by standing instruction |
| 15 | **New here:** the `config.py` constants (§9) — neither implemented nor removed until the model is chosen |

---

# 14. Evidence Classification

| Class | Where used |
|---|---|
| **[REPO]** | Option A §3.1 (15 rows), Option B §4.1 (14 rows), §5.1 composability, §9.1-9.2 config fields and non-use, §7 comparison, U1-U2 |
| **[HISTORICAL]** | U3-U4; C4 (all five constants originate in `c3cf4df`); the absence of any prior version of either manager |
| **[MEASURED]** | §8 in full — SELL levels 2480/2510 vs correct 2420/2390; SELL actions at the entry price; SELL silence at the true 1R and at the stop; BUY levels correct; A's mirror-image behaviour; the four-regime ladder table; A's gapped exit at the level; A's post-closure `CLOSE_ALL`; B's `inactive` guard; §15 suite result |
| **[INFERENCE]** | The defect is one-sided (BUY correct, SELL inverted); a hybrid resolves representation but not behaviour; ladder disorder is a model property that survives into every option; two of the proposed dependency links are not real; risk-free-after-1R changes distribution shape |
| **[DECISION]** | Q2, Q4, Q5, Q8, Q15, Q16 as the genuinely open independent questions; Q3, Q6, Q7, Q9-Q11, Q13, Q14, Q17-Q20 as dependents; D-q1 to D-q4; the status of the `config.py` specification |
| **[UNRESOLVED]** | Which half of the structure document records intent; whether the ATR specification was intended, copied or abandoned; whether B's log-only actions are a defect or unfinished scope |

**Explicitly not used as evidence:** module or function names on their own, the
`[L9]` tag, docstring self-description, and any judgement of which
implementation is richer, safer, cleaner or more sophisticated.

---

# 15. Verification

**Nothing was modified.** No `.py` file, no test, no fixture, no baseline
artifact. The only new file is this document.

## Read-only measurement

A scratchpad probe (outside the repository, never committed) imported
`order_execution` and `trade_manager` and exercised both across BUY and SELL for
all four regime `tp_ratio` values. It wrote no file and touched no repository
state. It set `order["status"]` on its own in-memory object rather than calling
`execute_order`, avoiding that function's 5 % random-failure path, so every
result is deterministic and reproducible. Results appear in §8.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **664** |
| Duration | 550.0 s |
| Failures | **2** |
| Errors | **0** |

| Test | Status |
|---|---|
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_micro_scalp_l7_confidence_uses_55_threshold` | Pre-existing — L2 H1-ATR mock failure, reproduces at `04a341d` |
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_pullback_gate_requires_real_pullback_detection` | Pre-existing — L2 H1-ATR mock failure, reproduces at `04a341d` |

**Matches the expected status exactly** — `664 tests, 2 failures, 0 errors`, and
the two failures are the two named pre-existing ones. Nothing differs, so there
is nothing further to investigate. No test was modified or added.

---

*Options only. No option selected, recommended, ranked or scored; no code, test, baseline or parameter changed. DD1 remains open pending the strategy owner's choice. Stopping for review.*
