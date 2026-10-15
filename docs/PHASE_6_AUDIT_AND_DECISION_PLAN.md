# Phase 6 — Audit and Decision Plan

**Documentation only.** No production code, test, specification, fixture or
baseline is changed by this document. `baselines/baseline_004` remains **FROZEN**
and was read but not regenerated. Nothing here is implemented.

**Starting state:** Phase 5 code at `139518c`, closure report at `dc6edfe`,
5B-i at `83b4124`, 5B-ii at `97363c7`. Full suite 883 tests, 2 known
`test_layer_gate_logic` failures, 0 errors.

## Evidence labels

Every conclusion below carries exactly one:

| Label | Meaning |
|---|---|
| **[FACT]** | Observed directly in repository source at `139518c` |
| **[MEASURED]** | Produced by running code or read from a frozen artefact |
| **[INTERPRETATION]** | Architectural reading of the facts — reasoning, not observation |
| **[UNRESOLVED]** | Open question; **not** answered here |

Gaps are left as **[UNRESOLVED]** rather than filled.

---

# 1. Executive Summary

Five findings dominate. Three were not in the Phase 6 brief and are recorded
because the audit surfaced them.

**1. The sizing discrepancy is a genuine defect, and the repository already
contains the correct formula next to the wrong one.** [FACT]
`main_production.execute_entry_signal` has an `if/else` whose two branches
divide by `10.0` and `100.0` respectively for the same instrument. The
`if` branch (`risk_manager.calculate_lot_size_for_symbol`) is ~10× oversized;
the `else` fallback is correct. Classification **A**, with a **B** unit mismatch
layered on top. §2.

**2. The sizing value never reaches a broker.** [FACT]
`order_execution.execute_order` calls `mt5_handler.send_order(...)` without
passing volume at all, and `mt5_handler.py` defines no `send_order`. The live
branch cannot execute. §2.6, §6.

**3. `baseline_004` contains zero trades and zero signals.** [MEASURED]
15,735 decisions across 2026-06-24 → 2026-09-16, every one `PRE_ENTRY`;
`trade_ledger.json` is `[]`; `total_signals: 0`. The frozen baseline therefore
constrains the *decision* path only. There is no trade-producing baseline
anywhere in the repository. This is the single largest obstacle to historical
performance research and it reframes §3 and §7. §3.4, §7.

**4. Two ungated `mt5.order_send()` call sites exist outside `execution/`.**
[FACT] `main.py:770` and `main_production.py:1245`, both in shutdown
position-closers, guarded by `MT5_AVAILABLE` only — **not** by
`LIVE_TRADING_ENABLED`. §6.2.

**5. Partials are covered at the adapter but have never reached the ledger.**
[FACT] `LadderManagement` exercises a 50-step partial, but every *integration*
fixture trades 0.01 lots, so no `TradeRecord` with more than one exit execution
has ever been produced end to end. §4.

**On `valid_rr`:** the tautology `RR ≡ tp_ratio` is confirmed [FACT], but the
measured evidence **cannot** show it blocking anything, because zero signals
were produced in any regime. §3.

---

# 2. Sizing Audit

## 2.1 Every path traced

### Path A — `risk_manager.calculate_lot_size_for_symbol` [FACT]

`risk_manager.py:5`.

| | |
|---|---|
| **Inputs** | `symbol` (str, unused), `balance` (account currency), `risk_percent` (percent, e.g. `1.0`), `entry`, `stop` (price units) |
| **Intermediate** | `risk_amount = balance * risk_percent / 100.0` → account currency; `stop_distance = abs(entry - stop)` → **price units** |
| **Formula** | `lot_size = risk_amount / (stop_distance * 10.0)` |
| **Post-processing** | `max(0.01, round(lot_size, 2))`, then `min(lot_size, 1.0)` |
| **Output** | lots |
| **Caller** | `main_production.execute_entry_signal` (`main_production.py:1099`) — the only one |
| **Consumer** | `order_executor.create_order(position_size=...)` |

**[FACT]** `pip_value = 0.01` is assigned on line 17 and never read. The five
comment lines around it contradict each other and are openly uncertain
("Actually…", "Let's simplify", "approximate"). The `10.0` on line 20 is a
literal with no derivation.

### Path B — the inline fallback [FACT]

`main_production.py:1106`, the `else` branch of the same statement.

| | |
|---|---|
| **Formula** | `max(0.01, round(risk_amount / (max(stop_distance, 1e-6) * 100.0), 2))` |
| **Output** | lots |
| **Cap** | none |

### Path C — `core.symbols.money_per_price_unit` [FACT]

`core/symbols.py:276`. `(tick_value / tick_size) * volume`. For `XAUUSD_2DIGIT`
(`tick_size=0.01`, `tick_value=1.0`): **100.0 per lot** [MEASURED].

This path does **not** size positions. It converts price distance to money, and
is what the canonical ledger uses for P&L and R (`backtest/ledger.py:236, 780,
815`).

### Path D — backtest sizing [FACT]

**There is none.** `ReplayEngine` takes `volume: float = DEFAULT_SIMULATED_VOLUME`
and passes it unchanged to every order (`replay_engine.py:134, 487, 494`).
`backtest/runner.py:276` prints it as `lots (FIXED)`. No risk-based sizing
exists in the backtest.

### Path E — `main.py` [FACT]

`main.py` contains **no sizing path at all**. It does not import
`risk_manager` for sizing and computes no lot size.

## 2.2 The ~10× discrepancy, quantified [MEASURED]

Both branches of the same `if/else`, same inputs:

| balance | risk % | stop ($) | Path A (`10.0`) | Path B (`100.0`) | ratio | actual risk at Path A size |
|---|---|---|---|---|---|---|
| 10,000 | 1.0 | 30.00 | **0.33** | 0.03 | 11.0× | $990.00 = **9.90 %** (intended 1 %) |
| 10,000 | 1.0 | 3.00 | **1.00** | 0.33 | 3.0× | $300.00 = **3.00 %** (intended 1 %) |
| 50,000 | 2.0 | 50.00 | **1.00** | 0.20 | 5.0× | $5,000.00 = **10.00 %** (intended 2 %) |
| 1,000 | 1.0 | 10.00 | **0.10** | 0.01 | 10.0× | $100.00 = **10.00 %** (intended 1 %) |

**[INTERPRETATION]** The ratio is not always 10× because two post-processing
steps mask it: `round(…, 2)` at the 0.01 floor, and the `min(…, 1.0)` cap. In
rows 2 and 3 the cap is binding, so the reported ratio (3×, 5×) understates the
formula error while still delivering ~10× the intended risk. **The cap converts
a sizing error into a different arbitrary size rather than preventing it.**

## 2.3 Classification

**A — a genuine defect.** Not B, C, D or E, for four reasons:

1. **[FACT]** The correct constant is present in the same statement's `else`
   branch. Two branches of one conditional cannot be "two intentionally
   different concepts".
2. **[FACT]** `core/symbols.py:283-285` names the contradiction in its own
   docstring: *"this returns 100.0 per lot — the value `risk_manager` currently
   assumes to be 10.0."*
3. **[FACT]** `tests/core/test_symbols.py:136-140` asserts 100.0 and documents
   in its docstring: *"`risk_manager.calculate_lot_size_for_symbol` divides by
   10.0, making every position ~10x oversized. Recorded in PHASE_2_ISSUES.md;
   not changed in this phase."*
4. **[FACT]** Path A is not dead: it is reached whenever `RISK_MANAGER_AVAILABLE`
   is true, which is the normal import outcome.

A **category B unit mismatch is layered on top**: `order_execution.create_order`
documents `position_size: % of account to risk (0.5-1.0)` (`order_execution.py:83`)
while `main_production` passes **lots**. `order_execution.py:334` passes
`position_size=0.5`, consistent with the percent reading. [FACT] The parameter
is stored in the order dict and used for nothing else, so the mismatch is
currently inert — but the two callers disagree about the unit.

## 2.4 Which path is authoritative

| Context | Authoritative sizing | Evidence |
|---|---|---|
| **Current backtest** | **None.** Fixed `volume` in lots, never risk-derived. | [FACT] `replay_engine.py:134` |
| **Current production/live code** | Path A when `RISK_MANAGER_AVAILABLE`, else Path B. | [FACT] `main_production.py:1097-1108` |
| **Paper/simulation** | **None.** `PaperBroker` receives the volume it is given. | [FACT] `paper_broker.py` |

**[INTERPRETATION]** The defect therefore **cannot** affect any current
backtest result, `decisions_fingerprint`, ledger fingerprint or `baseline_004`.
It is quarantined to a production entry point that (per §2.5) cannot reach a
broker. This is why it is a Phase 6 correctness item and not a Phase 5
regression.

## 2.5 The size never reaches a broker [FACT]

`order_execution.execute_order` (`order_execution.py:127`):

- the `simulation=True` branch fabricates `mt5_order_id = random.randint(...)`
  and injects a 5 % artificial failure rate via `random.random()`;
- the `elif mt5_handler:` branch calls
  `mt5_handler.send_order(order_type=…, entry_price=…, stop_loss=…,
  take_profit=…, comment=…)` — **with no volume argument**;
- **`mt5_handler.py` defines no `send_order` method and no class.**

**[INTERPRETATION]** The live branch would raise `AttributeError` on first use.
Position size is computed, stored in the order dict, and dropped. Any future
repair of this path must re-derive the unit contract from scratch (§2.3 B).

## 2.6 What remains unknown

**[UNRESOLVED]** Which of `main.py`, `main_production.py` and `order_execution.py`
is intended to own entry execution. Until that is answered, "fix the sizing
formula" is ambiguous — it is not known which module should hold the corrected
one, or whether `risk_manager.calculate_lot_size_for_symbol` should be repaired,
replaced by `money_per_price_unit`, or deleted.

**[UNRESOLVED]** Whether `min(lot_size, 1.0)` is a risk control or an artefact.
Nothing states its purpose.

---

# 3. `valid_rr` Audit

## 3.1 Lifecycle [FACT]

**Calculated** — `entry_engine.py:403-409`:

```
take_profit = entry_price ± (risk_distance * tp_ratio)
reward_distance = abs(take_profit - entry_price)
rr = reward_distance / risk_distance
valid_rr = rr >= 2.0
```

`reward_distance` is `risk_distance * tp_ratio` by construction, so
`rr ≡ tp_ratio` exactly, and `valid_rr ≡ (tp_ratio >= 2.0)`. **It reads a
configuration constant.** The error branch (`entry_engine.py:429`) sets
`valid_rr: False` with `stop_loss: None`.

**Consumed** — three places:

| Site | Use |
|---|---|
| `entry_engine.py:535, 638` | `entry_triggered = raw_triggered and valid_rr` — the gate |
| `entry_engine.py:445` | `valid_bonus = 2.0 if candidate.get("valid_rr")` — candidate scoring |
| `main_production.py:1008, 1025, 1038` | `rr_valid` reporting only |

**Regimes affected** [FACT] (`entry_engine.py:76-112`):

| Regime | `tp_ratio` | `valid_rr` reachable |
|---|---|---|
| MICRO_SCALP | 1.5 | **No** |
| DEAD_CALM | 1.5 | **No** |
| REGIME_SCALP | 2.0 | Yes (exactly at threshold) |
| INTRADAY_SWING | 3.0 | Yes |

**Can it measure market attainability?** **No.** [INTERPRETATION] Attainability
is a property of price action after entry. `valid_rr` is computed before entry
from two numbers whose ratio is fixed by the regime table. No market quantity
enters it.

## 3.2 Measured evidence — and its limit [MEASURED]

From frozen `baselines/baseline_004/defect_observations.json`:

| Regime | `tp_ratio` | decisions | reached L8 | signals |
|---|---|---|---|---|
| MICRO_SCALP | 1.5 | 5,121 | 972 | **0** |
| REGIME_SCALP | 2.0 | 6,492 | 217 | **0** |
| DEAD_CALM | 1.5 | 2,312 | 22 | **0** |
| INTRADAY_SWING | 3.0 | 1,810 | 54 | **0** |
| **Total** | | **15,735** | **1,265** | **0** |

994 of 1,265 L8-reaching decisions (78.6 %, derived) occurred in a regime where
`valid_rr` is unreachable.

**This is not an attribution, and must not be read as one.** The repository
states so itself (`backtest/baseline.py:531-534`): *"entry_triggered =
raw_triggered AND valid_rr; these counts do not establish which term blocked a
decision."* And `baseline.py:521-527` records that **at every L8 block measured,
`raw_triggered` was already false**, so on that evidence the gate blocked
nothing.

**[MEASURED]** Zero signals were produced in **any** regime, including the two
where `valid_rr` passes. Whatever is preventing entries is therefore not
`valid_rr` alone.

**[UNRESOLVED]** `raw_triggered` has never been measured directly across the
baseline. Until it is, the contribution of `valid_rr` cannot be isolated.

## 3.3 Options, evaluated neutrally

Assessed on what each measures, not on trade count or P&L.

### A — Remove `valid_rr` as a gate

| | |
|---|---|
| **Measures** | Nothing; removal deletes a term that reads a constant |
| **Changes** | `entry_triggered` loses one conjunct. On current evidence this changes nothing, since `raw_triggered` was already false at every measured block. `valid_bonus` in scoring would also need a decision. |
| **Evidence needed** | Direct `raw_triggered` measurement; confirmation the scoring bonus is not load-bearing |
| **Nature** | **Correctness correction** — removes a tautology, not a market judgement |

### B — Replace with a genuine target-attainability test

| | |
|---|---|
| **Measures** | Whether the target is plausibly reachable — e.g. against ATR, structural distance, or session range |
| **Changes** | Introduces a new, real gate. Could admit or reject setups on grounds never previously applied. |
| **Evidence needed** | A defined attainability metric; a threshold derived from data, not chosen; validation that it is not a second tautology |
| **Nature** | **Strategy change.** Excluded by §10 of this audit and by the standing constraint. |

### C — Retain with a documented purpose

| | |
|---|---|
| **Measures** | That the regime's configured `tp_ratio` clears 2.0 — i.e. a regime admissibility switch, honestly named |
| **Changes** | No behaviour. Renames and documents. Makes explicit that MICRO_SCALP and DEAD_CALM are structurally barred from entry. |
| **Evidence needed** | Confirmation that barring those two regimes is intended |
| **Nature** | **Correctness correction** (documentation of existing behaviour) |

### D — Separate the two roles [INTERPRETATION]

The audit surfaced one option not in the brief. `valid_rr` is used as **both** a
hard gate and a **scoring bonus** (`entry_engine.py:445`). These are independent
and could be decided separately — e.g. retire the gate (A or C) while deciding
the bonus on its own evidence.

| | |
|---|---|
| **Measures** | Unchanged; separates two uses currently coupled by one flag |
| **Changes** | None by itself; enables the gate and the bonus to be decided independently |
| **Evidence needed** | Whether `valid_bonus = 2.0` ever changes which candidate wins `_score_entry_candidate` |
| **Nature** | **Correctness correction** (decoupling), then a separate decision per role |

**No option is chosen here.**

---

# 4. Partial-Exit Audit

## 4.1 What is already covered [FACT]

Contrary to the brief's premise, partials **are** exercised — at the adapter
level. `tests/execution/test_trade_adapter.LadderManagement` uses `volume=1.00`
(100 steps) and asserts a 50-step partial, `remaining_volume == 0.50`, the
breakeven promotion, the 2R `LOCKED_1R` promotion, and that the promoted stop
binds from the next bar.

**The real gap is narrower and should be stated precisely:** no partial has ever
reached the **ledger**. Every *integration* fixture uses
`DEFAULT_SIMULATED_VOLUME` (`tests/integration/_harness.py:143`), and the R1
fixtures trade 0.01 lots = 1 step, so `1 // 2 = 0`. No `TradeRecord` carrying
more than one exit `TradeExecution` has ever been produced end to end through
`ReplayEngine` → `TradeLedger` → metrics.

## 4.2 The partial rule [FACT]

`core/trade_model.py:760`:

```
steps_to_close = state.steps_at_entry // 2
```

**Anchored on `steps_at_entry`, not `steps_remaining`.** Floor division, so a
partial never closes more than half. If zero, no order is sent but the milestone
is still consumed and the stop still promotes (spec 5.2, 5.4).

## 4.3 Proposed fixture — exact expected values

**Not implemented.** Setup: `volume = 1.00`, entry 2450.00, original stop
2420.00, `tp_ratio` 3.0, no costs. R = 30.00 → 1R 2480, 2R 2510, target 2540.

| Stage | Expected |
|---|---|
| Entry quantity | 100 steps = 1.00 lots |
| Partial quantity | `100 // 2` = **50 steps = 0.50 lots** @ 2480.00 |
| Remaining | **50 steps = 0.50 lots** |
| Stop after M1R | intended **BREAKEVEN**, confirmed BREAKEVEN @ 2450.00 |
| Stop after M2R | intended **LOCKED_1R**, confirmed LOCKED_1R @ 2480.00 |
| Final close | 50 steps = 0.50 lots @ 2540.00 |
| Broker instructions | `execute_partial_close`(50), `execute_stop_modify`(2450, BREAKEVEN), `execute_stop_modify`(2480, LOCKED_1R), `execute_close`(50) |
| Fill identities | 3 `FillRecord`s: 1 ENTRY (100), 2 exits (50, 50), distinct `fill_id` and `operation_id` |
| Ledger executions | **3 `TradeExecution` rows in one `TradeRecord`** |
| Final trade record | 1 record, `quantity` 1.00, outcome TARGET_HIT |

**Aggregate P&L and R** [MEASURED, computed from `core.symbols`]:

```
partial  (2480 - 2450) * money_per_price_unit(0.50) = 30 * 50 = $1,500.00
final    (2540 - 2450) * money_per_price_unit(0.50) = 90 * 50 = $4,500.00
gross                                                          $6,000.00
risk_amount = money_for_price_distance(30.00, 1.00)           = $3,000.00
r_multiple  = 6000 / 3000                                     = 2.0
```

## 4.4 Hidden assumptions that appear only when quantity > 1 step

**[INTERPRETATION] The most important one: `r_multiple` is 2.0, not 3.0.**
A laddered position banks half at 1R and half at 3R, so realised R is
`0.5×1 + 0.5×3 = 2.0`. The §4.2 identity `reward / R == tp_ratio` constrains the
**target level**; it says nothing about realised R once a partial occurs. Any
fixture, metric or research conclusion that expects `r_multiple ≈ tp_ratio` will
be wrong for every laddered trade — and the only trades the repository has ever
produced are un-laddered single-step ones, so this has never surfaced.

**[FACT]** `r_multiple = net_pnl / risk_amount` where `risk_amount` is computed
on `original_quantity` (`ledger.py:815`). The denominator is full original risk,
which is what makes the blended figure meaningful — but it must be documented.

**[FACT]** Both stop promotions and the partial can fire on a **single bar** if
that bar reaches 2R: the `_LADDER` loop consumes M1R (partial + BREAKEVEN) then
M2R (LOCKED_1R). Exactly one partial is sent.

**[UNRESOLVED]** No integration evidence exists for commission or slippage
apportionment across multiple exit executions. `ledger.py:797-799` charges
`commission_per_lot * lots` per exit execution; with a partial this bills in two
instalments. Arithmetically consistent, never verified end to end.

## 4.5 Quantity-step rounding

| Risk | Possible? | Evidence |
|---|---|---|
| **Zero partial** | **Yes, by design.** `1 // 2 = 0`. Milestone still consumed, stop still promotes. | [FACT] `trade_model.py:760`; pinned by `test_a_single_step_position_promotes_without_a_partial` |
| **Full-position partial** | **No.** `n // 2 == n` only when `n == 0`, and `open_position` rejects `steps <= 0`. | [FACT] `trade_model.py:538` |
| **Unexpected remainder** | **Yes, and it is correct.** Odd steps leave the larger half: 3 steps → partial 1, remaining 2. | [FACT] floor division |
| **Over-close** | **Guarded.** `steps_closed > steps_remaining` raises `DomainInvariantError`. | [FACT] `trade_model.py:862` |
| **Off-step broker mismatch** | **Detected, severity undecided.** Reconciliation adopts the broker value and records an anomaly. | [FACT] `trade_model.py:914-922`; severity is **R4** |

**[UNRESOLVED]** `SymbolSpecification.clamp_volume` clamps *upward* to
`volume_min`, which its own docstring (`core/symbols.py:237-240`) notes can
**increase risk beyond what was requested**. Not reachable from the canonical
backtest (fixed volume), but live on any future sizing path.

---

# 5. Remaining R / I / U Decisions

Scope and status verified against the source at `139518c`. **None is resolved
or reinterpreted here.**

| Item | Scope | Known now | Still unknown | Classification |
|---|---|---|---|---|
| **R1** Reversal protection | Retiring `trade_manager` removes `CLOSE_BREAKEVEN_PROTECTION` with no canonical replacement | [FACT] `trade_manager` is still imported by `main.py:47` and `main_production.py:77`, so nothing is removed yet | Whether the behaviour must be replaced or may lapse | **3 — live integration** (gates retirement, Phase 9) |
| **R2** Netting vs hedging | Opposing positions stay refused | [FACT] `may_open_position` enforces the restriction | Broker-side netting semantics | **3 — live** |
| **R3** Session/weekend handling of open positions | Undecided | [FACT] Backtest ends with `close_all_at_end_of_data`; no session logic | What a live path does over a weekend | **3 — live** |
| **R4** Quantity-mismatch severity | Detection designed, grading not | [FACT] Reconciliation adopts broker value, records anomaly (`trade_model.py:914`) | How severe, and what acts on it | **2 — paper trading** (first real broker quantities) |
| **U5/R8** Observed reference on a re-requested close | Retry carries `observed_reference=None` | [FACT] `trade_model.py:684` explicitly `None` with a U5/R8 comment | Which reference is correct | **2 — paper trading** (needs a broker that can fail a close) |
| **U6/R9** Rejected stop promotion | Domain raises `UnresolvedCanonicalDecisionError` | [FACT] `trade_model.py:736-742`; `PaperBroker` never rejects, so unreachable in backtest | Whether an unconfirmed promotion blocks the next milestone | **2 — paper trading** |
| **I2** Restart/persistence | No append-only store exists | [FACT] `trade_persistence.py` exists but is outside the canonical stack | Format, durability, snapshot authority | **3 — live** |
| **I3** Live observation source and cadence | Production has never fed a moving price | [FACT] No live feed path | Source, cadence, gap handling | **3 — live** |
| **I7** Concurrency/capacity ownership | Undecided between config, adapter and `may_open_position` | [FACT] `may_open_position` exists in the domain; the adapter manages a dict of live positions and imposes no cap | Which layer owns the limit | **1 — required before historical research** |

**[INTERPRETATION] I7 is the only one of the nine that gates historical
research**, because a multi-position backtest must know who enforces capacity.
The current fixtures hold one position each, so the question has never been
forced. Every other item requires a real broker or a restart to become
observable.

**[FACT]** I6 (`IntrabarPolicy` survival) was decided at `71d1204` and
implemented in `83b4124`; it is not in this table and is not reopened.

---

# 6. Dead / Duplicate Path Audit

Nothing is removed. Classification only.

## 6.1 Findings

| # | Path | Classification | Evidence |
|---|---|---|---|
| 1 | `risk_manager.calculate_lot_size_for_symbol` | **Active** (production), unreachable from backtest | [FACT] called at `main_production.py:1099` |
| 2 | `main_production.execute_entry_signal` fallback sizing | **Reachable, not used by canonical backtest** | [FACT] `else` branch, correct formula |
| 3 | `order_execution.execute_order` simulation branch | **Reachable, not used by canonical backtest** — fabricates `mt5_order_id` via `random.randint`, 5 % artificial failure | [FACT] `order_execution.py:150-163` |
| 4 | `order_execution.execute_order` live branch | **Dead — broken** | [FACT] calls `mt5_handler.send_order`, which does not exist |
| 5 | `trade_manager.manage_open_trade`, `close_position` | **Active** in `main.py` / `main_production.py`; unreferenced by canonical stack | [FACT] imported at `main.py:47`, `main_production.py:77` |
| 6 | `main.py` position management | **Active** in that entry point only | [FACT] |
| 7 | `main_production` position management | **Active** in that entry point only | [FACT] |
| 8 | `mt5.order_send` in `main.py:770`, `main_production.py:1245` | **Active, ungated** — see §6.2 | [FACT] |
| 9 | `pip_value` local in `risk_manager.py:17` | **Dead** — assigned, never read | [FACT] |
| 10 | `.kilo/worktrees/alive-molasses/` — 20 duplicate modules incl. a second `risk_manager.py` with a *different* `calculate_lot_size` | **Unknown** — untracked by git, present on disk | [FACT] `git ls-files` returns nothing |
| 11 | `PositionState.CLOSED_TIME`, `TradeOutcome.TIME_EXIT` | **Dead by design** — defined, unproduced | [FACT] Phase 5 §5.2 |
| 12 | Legacy carried `take_profit` on `PendingOrderIntent` | **Reachable, inert** — overwritten by the canonical target | [FACT] `trade_adapter.py:322` |

## 6.2 Trade records outside the canonical ledger, and `record_then_apply` bypasses

**[FACT] Yes, both exist — all outside the canonical stack.**

`order_execution.OrderExecutor` maintains its own `self.orders` dict, assigns its
own `order_id`, and in simulation marks orders executed with a random
`mt5_order_id`. These records never reach `TradeLedger`, carry none of the five
canonical identities, and do not pass `record_then_apply`.
`trade_manager.manage_open_trade` likewise manages positions outside the
canonical domain.

**[FACT]** Two `mt5.order_send()` call sites exist outside `execution/`:
`main.py:770` and `main_production.py:1245`, both in shutdown handlers that
close all open positions. Both are guarded by `MT5_AVAILABLE` only.
**`LIVE_TRADING_ENABLED` appears nowhere in either file.**

**[MEASURED]** A repository-wide search for real call sites (excluding
docstrings, `venv` and the untracked worktree) returns **exactly these two**.
Within `execution/`, `backtest/` and `core/` the only occurrences of the string
are docstrings stating the prohibition, and
`tests/execution/test_no_live_execution.py` enforces it — 7 tests, passing at
`139518c`.

**[INTERPRETATION]** The invariant "no `mt5.order_send()`" therefore holds for
the canonical stack, and `core/safety.py` is intact. It does **not** hold for
the two legacy entry-point scripts, which the prohibition test does not cover. Reaching them requires running `main.py` or `main_production.py` with
MetaTrader5 importable and a live terminal attached; neither is part of any test
or backtest path. This is recorded as a finding, not repaired.

**[UNRESOLVED]** Whether these shutdown handlers should be gated, removed, or
routed through the canonical broker contract.

---

# 7. Historical-Performance-Research Readiness

## 7.1 The blocking observation [MEASURED]

`baselines/baseline_004`: 15,735 decisions, `signal_type_counts:
{"PRE_ENTRY": 15735}`, `total_signals: 0`, `trade_ledger.json` = `[]`,
`completed_trades: 0`, every aggregate `null` or `0`.

**[INTERPRETATION]** The frozen baseline constrains the decision path and
nothing else. No trade-level behaviour in this repository has ever been observed
on real data — the only trades that exist anywhere are the two synthetic R1
fixtures. A performance study cannot begin against a baseline with no trades;
the first requirement is a run that produces some.

**[UNRESOLVED]** Why zero entries were produced across three months. §3.2 shows
it is not `valid_rr` alone. This is the single most important open question in
this audit, and it is **not** answered here.

## 7.2 Checklist

### A — MUST be resolved before historical research

| # | Requirement | Status |
|---|---|---|
| A1 | **A run that produces trades**, with the cause of the zero-signal baseline understood | **[UNRESOLVED]** — §7.1 |
| A2 | **Quantity/sizing correctness** — a stated, tested authority for lots | **Defect open** — §2 |
| A3 | **Partial-exit behaviour proven end to end** through ledger and metrics | **Gap** — §4.1 |
| A4 | **Realised-R semantics for laddered trades** documented (2.0R ≠ `tp_ratio`) | **[UNRESOLVED]** — §4.4 |
| A5 | **I7 concurrency/capacity ownership** | **[UNRESOLVED]** — §5 |
| A6 | Deterministic replay | **Met** [MEASURED] — byte-identical re-capture, Phase 5 §3.5 |
| A7 | `decisions_fingerprint` stability | **Met** [MEASURED] — unchanged across all of Phase 5 |
| A8 | Canonical entry/fill behaviour | **Met** [FACT] — creation at fill, §13 |
| A9 | Canonical target semantics | **Met** [FACT] — §4.2, 5B-ii |
| A10 | Stop semantics | **Met** [FACT] — original-stop R, forward-only ladder |
| A11 | Lossless ledger | **Met** [FACT] — one record per position, all executions |
| A12 | Ambiguity handling | **Met** [FACT] — adverse-first, flagged not judged |

### B — SHOULD be resolved before historical research

| # | Requirement | Status |
|---|---|---|
| B1 | **Transaction costs** — spread/slippage/commission calibrated and stated | Mechanism exists; values unvalidated **[UNRESOLVED]** |
| B2 | **Data-quality requirements** — gap, holiday and missing-bar policy | **[UNRESOLVED]** |
| B3 | **Provenance/fingerprint requirements** for a new baseline | Mechanism exists (`run_fingerprint`, `dataset_manifest`); protocol undefined |
| B4 | `valid_rr` disposition | **[UNRESOLVED]** — §3.3 |
| B5 | Dead-path quarantine so no non-canonical record can be mistaken for a result | **[UNRESOLVED]** — §6 |
| B6 | `raw_triggered` measured directly | **[UNRESOLVED]** — §3.2 |

### C — May remain unresolved until paper/live work

R2, R3, R4, U5/R8, U6/R9, I2, I3 (§5); the `order_execution` live branch (§2.5);
the ungated `order_send` shutdown handlers (§6.2) — **provided** neither
`main.py` nor `main_production.py` is run during research; `clamp_volume`
upward-clamping (§4.5).

---

# 8. Proposed Phase 6 Implementation Sequence

**Nothing below is implemented.** One causal change per commit. Ordered so that
each commit's evidence is interpretable independently.

### 6.1 — Evidence: why zero signals

| | |
|---|---|
| **Purpose** | Measure `raw_triggered` and each `entry_triggered` conjunct directly across the baseline window |
| **Semantic question** | None — measurement only |
| **Files** | `backtest/baseline.py` (observation only), or a scratch probe |
| **Tests** | None if scratch; observation test if it lands in `baseline.py` |
| **Fingerprint impact** | **None.** No decision input changes. |
| **Invariants** | `decisions_fingerprint`, ledger fingerprints, `baseline_004` all unchanged |
| **Evidence before commit** | Per-layer counts; confirmation `decisions_fingerprint` is unchanged |

**[INTERPRETATION]** This must come first. Every later choice — `valid_rr`,
sizing authority, research design — depends on knowing what actually blocks
entries, and §7.1 shows that is currently unknown.

### 6.2 — Partial-exit integration fixture

| | |
|---|---|
| **Purpose** | Drive a partial through `ReplayEngine` → `TradeLedger` → metrics |
| **Semantic question** | None — coverage only. Asserts existing behaviour. |
| **Files** | `tests/integration/` (new fixture), possibly `tests/integration/_harness.py` for a volume parameter |
| **Tests** | The new fixture; §4.3 expected values |
| **Fingerprint impact** | **None** on existing fixtures. New fixture gets its own pins. |
| **Invariants** | R1 fixtures untouched; `decisions_fingerprint` unchanged; existing ledger fingerprints unchanged |
| **Evidence before commit** | 3 executions in 1 record; P&L $6,000; **r_multiple 2.0**; commission split verified |

### 6.3 — Document realised-R semantics for laddered trades

| | |
|---|---|
| **Purpose** | Record that `r_multiple` is money-weighted against original risk and does not equal `tp_ratio` once a partial fires |
| **Semantic question** | None — documents existing behaviour |
| **Files** | Docstrings in `backtest/ledger.py`; possibly a spec note **only if** a genuine contradiction is found |
| **Tests** | None |
| **Fingerprint impact** | **None** |
| **Invariants** | All |
| **Evidence before commit** | 6.2's measured 2.0R |

### 6.4 — Sizing authority decision (documentation)

| | |
|---|---|
| **Purpose** | Decide which module owns sizing and which formula is canonical. **Decision, not repair.** |
| **Semantic question** | Which of repair / replace with `money_per_price_unit` / delete; and the lots-vs-percent unit contract (§2.3 B) |
| **Files** | `docs/` only |
| **Tests** | None |
| **Fingerprint impact** | **None** |
| **Invariants** | All |
| **Evidence before commit** | §2 of this audit; an answer to the entry-point ownership question (§2.6) |

### 6.5 — Sizing correction (implementation)

| | |
|---|---|
| **Purpose** | Apply 6.4 |
| **Semantic question** | Lot size per unit of risk |
| **Files** | `risk_manager.py` and/or `main_production.py`, per 6.4 |
| **Tests** | New sizing tests against `money_per_price_unit`; the existing `test_gold_dollar_move_is_one_hundred_per_lot` docstring becomes stale and must be updated in the same commit |
| **Fingerprint impact** | **None expected** — backtest does not size (§2.4). **Must be proven, not assumed.** |
| **Invariants** | `decisions_fingerprint`, both ledger fingerprints, `bars_held`, `baseline_004` |
| **Evidence before commit** | Before/after capture on both R1 fixtures showing every figure identical; if anything moves, **STOP** |

### 6.6 — I7 concurrency/capacity ownership

| | |
|---|---|
| **Purpose** | Decide which layer enforces capacity |
| **Semantic question** | Config vs adapter vs `may_open_position` |
| **Files** | `docs/` first; implementation separately |
| **Fingerprint impact** | **None** while fixtures hold one position; unknown for multi-position runs |
| **Invariants** | Existing fixtures unchanged |
| **Evidence before commit** | Trace of every current capacity check |

**Not sequenced:** `valid_rr` disposition. It depends entirely on 6.1's result
and cannot be planned before it.

---

# 9. Invariants, Fingerprints and Baseline Constraints

Carried into every Phase 6 commit unless a commit's own audit explicitly
authorises the change and attributes it:

| Invariant | Value |
|---|---|
| `decisions_fingerprint` long | `bf174068e992a9cf6c8b42a161bf449120fd3423bba5293761a37c007bfec7c6` |
| `decisions_fingerprint` short | `a033d076987b8baaeae4993f70e0c1735961042f3eecedd7c6e9a04f3d92f212` |
| Ledger fingerprint long | `33ac2bb259d5662f386913a97b6ca0524eec7f13a0e3ceb4d455d6f65b010317` |
| Ledger fingerprint short | `ce733aeb7d6220270b9cc4864a190a2970faa0981286895ef09c990d81228109` |
| `bars_held` | 14 (long), 5 (short) |
| Suite | 883 tests, 2 known failures, 0 errors |
| `baseline_004` | FROZEN — 12 artefacts, never regenerated, never overwritten |
| `LIVE_TRADING_ENABLED` | literal `False`, no env override |

**[INTERPRETATION]** Any performance improvement must be measured against a
**new** canonical baseline and compared with frozen `baseline_004`, with the
difference attributed to specific code or model changes. Per §7.1 the frozen
baseline has no trades, so the first such comparison will be a decision-path
comparison only.

---

# 10. Explicit Non-Goals

Not changed, not proposed, not evaluated on outcome:

- candidate-generation logic;
- strategy entry rules and filters;
- parameter values, including the regime `tp_ratio` table and the 2.0 threshold;
- `baselines/baseline_004`;
- `decisions_fingerprint`;
- the canonical trade-management specification — **no contradiction with §4.2
  or any other section was found by this audit**;
- the nine unresolved R/I/U items — one (**I7**) is argued in §5 to gate
  historical research, which is a scheduling claim, **not** a resolution;
- **any profitability conclusion.** No statement here asserts that the strategy
  is or is not profitable, or that any change would improve results. The sizing
  defect is a correctness finding about risk per trade, not a performance claim.

---

# 11. Open Questions Requiring Review

| # | Question | Why it needs a decision |
|---|---|---|
| 1 | **Why did `baseline_004` produce zero signals in 15,735 decisions?** | Blocks all performance research (§7.1) |
| 2 | Which module owns entry execution — `main.py`, `main_production.py` or `order_execution.py`? | "Fix the sizing formula" is ambiguous until answered (§2.6) |
| 3 | Is `position_size` lots or percent? | Two callers disagree (§2.3) |
| 4 | Should the ungated `mt5.order_send()` shutdown handlers be gated, removed, or routed through the canonical broker? | Live-safety posture (§6.2) |
| 5 | Is `min(lot_size, 1.0)` a risk control or an artefact? | Determines whether it survives a sizing fix (§2.6) |
| 6 | `valid_rr` — A, C, D, or defer? B is a strategy change and is excluded. | Depends on Q1 (§3.3) |
| 7 | Is barring MICRO_SCALP and DEAD_CALM from entry intended? | Determines whether option C is honest (§3.1) |
| 8 | Should `r_multiple` remain money-weighted against original risk for laddered trades? | Changes how every future result is read (§4.4) |
| 9 | Who owns concurrency/capacity (I7)? | Gates multi-position research (§5) |
| 10 | Is `.kilo/worktrees/alive-molasses/` (20 untracked duplicate modules, incl. a divergent `risk_manager`) intended to be present? | Ambiguity risk during research (§6.1 #10) |
| 11 | What defines the next canonical baseline — dataset, period, manifest, comparison protocol? | Required before any study (§7.2 B3) |

**None of these is answered in this document.**
