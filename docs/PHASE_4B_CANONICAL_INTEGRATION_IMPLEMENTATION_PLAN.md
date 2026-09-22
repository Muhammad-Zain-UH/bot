# Phase 4B — Canonical Integration Implementation Plan

**Plan only.** No production Python, test, baseline, `core/trade_model.py`,
canonical specification, adapter, `PaperBroker` or ledger is changed.
`trade_manager` is not retired. `baseline_004` remains **FROZEN**. R1–R4,
U5/R8 and U6/R9 are untouched.

**Settled inputs, not reopened here:**

| Decision source | Commit | Settles |
|---|---|---|
| Integration design | `9792de7` | Adapter boundary; the three current lifecycles |
| Partial-exit representation | `54899ea` | Option 2 — position record plus a fill ledger |
| Identity and fill history | `83fe262` | D1–D6 |
| Identity, idempotency, R semantics | `d15e52c` | D7–D15; the required §16.3 amendment |
| Canonical model and contract | `5401d0c` | `core/trade_model.py`, 88 contract tests |

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `d15e52c` |
| **[DECISION]** | Settled earlier, restated here for planning |
| **[PLAN]** | A sequencing choice made by this document |
| **[UNRESOLVED]** | Still open; **not** resolved to tidy the plan |

---

# A. Implementation Boundary

| # | File | Current responsibility | Future responsibility | Why it changes | Why **not yet** |
|---|---|---|---|---|---|
| 1 | **`execution/trade_adapter.py`** | Does not exist | Owns `TradeState` instances, identity, `PriceObservation` construction, event translation, fill recording, result ingestion, reconciliation | It is the only place the domain and a broker can meet without either importing the other | Its contract depends on the ledger shape (3) and the broker verbs (2), neither of which exists |
| 2 | **`execution/paper_broker.py`** | Fills orders **and decides exits** (`resolve_intrabar`, `_close`) | Fills orders, executes instructions, reports results. **Stops deciding exits** | Two owners of exit semantics would double-close (§E) | Moving the decision requires the adapter to exist to receive it |
| 3 | **`backtest/ledger.py`** | One flat `SimulatedTrade` per closed position; `fingerprint()` over `asdict()` | Position aggregate **plus** append-only fill rows | A canonical position has two exits; one row cannot hold them (`54899ea`) | Changing it now breaks pinned fingerprints for no gain |
| 4 | **`execution/broker.py`** — `SimulatedPosition` | Source of truth for volume, exit, `risk_distance` | Broker-facing projection; mutable remaining quantity; **immutable original stop/R** | `risk_distance` reads the current stop, so `r_multiple` becomes `None` after breakeven (`d15e52c` §D.3) | The correction is only meaningful once the ladder can actually move a stop |
| 5 | **Persistence / recovery** | `trade_persistence.py`: whole-file JSON rewrite with a backup copy | Durable append-only fill log for **live** only | Record-then-apply needs durability across a crash (§C) | **I2 is unresolved**, and the repository has no append-only store (§C.3) |
| 6 | **Integration tests** | None for the adapter | 20 scenarios (§J) | They must exist before wiring | They target an interface that is not yet specified in code |
| 7 | **Production path** (`main_production.py`, `main.py`) | Two half-lifecycles, neither able to manage a real position | One entry point owning the canonical lifecycle | DD2 and the live price feed (I3) | Live scope is a separate phase; `LIVE_TRADING_ENABLED` stays `False` |
| 8 | **`trade_manager.py`, `order_execution.py`** | Legacy managers | Retired | Superseded by the canonical model | **Retiring `trade_manager` removes `CLOSE_BREAKEVEN_PROTECTION`** and R1 is unresolved (§I) |

---

# B. Adapter Contract — conceptual

**No code.** Each responsibility, with the decision that fixes it.

| Responsibility | Contract |
|---|---|
| Canonical position creation | On a confirmed entry fill only. An unfilled order produces **no** state (spec 13) |
| `position_id` generation | `{symbol}-{entry_bar_time}-{side}-{sequence:04d}`, minted at creation, deterministic (D12) |
| `operation_id` generation | One per instruction, before submission, stable across retries; submitted as `client_order_id` (D8) |
| `TradeState` ownership | A `position_id → TradeState` map. The domain owns rules; the adapter owns instances (D1) |
| `PriceObservation` construction | Replay: bar OHLC and open time. Live: **no source exists** — I3 |
| Domain evaluation | Exactly once per position per observation, results folded in before the next evaluation |
| `PartialCloseRequest` translation | `steps_to_lots(steps, volume_step)`, then a partial close on that volume |
| `StopModifyRequest` translation | A stop modification. **Produces no fill and no deal** (`d15e52c` §A.3) |
| `CloseRequest` translation | Price `observed_reference` through the cost model, then close the remaining quantity |
| Broker result ingestion | Every broker call returns one of the eight canonical result types |
| `fill_id` creation | Carries `broker_deal_id` where one exists; derived deterministically in paper execution (D10) |
| Duplicate-result detection | By `fill_id`; a known id is a no-op (D11) |
| Fill-ledger recording | **Before** applying to the domain, append-only (D11, §C) |
| Domain result application | `apply_broker_result`, only after a new fill record was written |
| Quantity reconciliation | Broker quantity versus `steps_remaining`; divergence emits `QuantityReconciled` and an anomaly. **Severity is R4, not decided** |
| Position closure | Only on a confirming result; then emit the aggregate record and drop the entry |
| Restart / recovery | §C. **Replay needs none**; live needs I2 |

---

# C. Record-Then-Apply Recovery

## C.1 The four states after a crash

| State | Detectable by | Recovery action |
|---|---|---|
| **Recorded and applied** | The fill is in the log **and** the rebuilt state already reflects it | None |
| **Recorded, not applied** | The fill is in the log but the rebuilt quantity does not include it | Apply it during rebuild. This is the case record-then-apply exists to make safe |
| **Duplicate broker result** | Its `fill_id` is already in the log | Discard |
| **Duplicate fill** | Same — the log is keyed by `fill_id` | The write is a no-op |
| **Stale result from another position** | Its `position_id` does not match | Reject; record as an anomaly |
| **Broker result missing from local history** | Broker reports a quantity the local fills cannot explain | `QuantityReconciled` — the broker wins, the gap is an anomaly. **Severity is R4** |

**[PLAN]** Rebuild order is: load the snapshot, replay fills in `fill_id`
order, then reconcile against the broker. The middle step makes "recorded, not
applied" self-healing, and the last makes a missing fill visible.

## C.2 Replay needs no recovery at all

**[REPO]** `TradeLedger` holds its trades in memory and `write_jsonl` opens the
target with mode `"w"` — a single rewrite at the end of a run. There is no
during-run durability, and none is needed: a crashed replay is **re-run from the
start**, and determinism guarantees the identical result.

**[PLAN]** Therefore record-then-apply in the backtest is an **in-memory
ordering rule**, not a persistence mechanism. Phases 2–7 need no new storage.

## C.3 Live needs a mechanism the repository does not have

**[REPO]** The only persistence is `trade_persistence.py`: it reads the current
file, writes a copy to `active_trades_backup.json`, then writes the new content
over `active_trades.json` with `json.dump`. There is **no temporary file and no
atomic rename**, so a crash during the final write leaves a truncated file and
the backup as the last good copy. It is a whole-file rewrite, **not** an
append-only log.

**[PLAN]** A durable append-only fill log is therefore a **new mechanism**, and
the evidence that one is required is exactly the record-then-apply rule: a
whole-file rewrite cannot guarantee that a fill survives the instant between
being recorded and being applied.

**[UNRESOLVED] What I2 must decide before live restart support can be built:**

1. The serialisation format for `TradeState` — enums, `frozenset`, aware
   datetimes.
2. Whether the durable store is an append-only JSONL file, a rewritten snapshot
   plus a fill log, or something else.
3. Write durability: atomic rename, `fsync`, or accepting a documented loss
   window.
4. Whether the snapshot is authoritative at all, or purely an optimisation over
   replaying fills.
5. How a restored state is marked unverified until reconciled, following
   `core.types.Position.broker_verified`.

**No new persistence mechanism is designed here.**

---

# D. Identity Lifecycle

One complete position. **Before** means it exists prior to broker submission;
**after** means it exists only once the broker has answered.

| Step | `position_id` | `operation_id` | `broker_order_id` | `broker_deal_id` | `fill_id` |
|---|---|---|---|---|---|
| **1. Entry** | **Minted after** — at the confirmed fill, because an unfilled order has no position (spec 13) | **Before** submission | After | After, one per execution | After, one per execution |
| **2. 1R partial** | Referenced — exists already | **Before** | After | After | After |
| **3. Stop modification** | Referenced | **Before** | After, if the broker creates one | **None** | **None** |
| **4. Final close** | Referenced | **Before** | After | After | After |

**[PLAN] The consequence of minting `position_id` at the fill:** the entry
*operation* cannot reference it, because the position does not yet exist. The
entry operation is identified by its `operation_id` alone, and the entry fill
row is written with the `position_id` minted at that moment. This keeps a
rejected entry from leaving an orphan identity, which matches spec 13 — a
pending order that never fills carries no management state.

**[REPO]** For a LIMIT_FVG entry the pre-submission identity already exists as
`PendingOrder.order_id`, which is the natural `operation_id` for the entry.

---

# E. Backtest Path

## E.1 Future flow

```
bar
  └─ PaperBroker.on_bar
       ├─ fill resting orders                         (unchanged)
       └─ hand the bar to the adapter                 (new)
            └─ adapter builds PriceObservation
                 └─ evaluate(state, observation)      (domain decides)
                      └─ events: PartialClose / StopModify / Close
                           └─ adapter -> PaperBroker executes the instruction
                                └─ broker result (price, quantity, deal)
                                     ├─ write fill record (append-only, by fill_id)
                                     └─ apply_broker_result -> TradeState
                                          └─ projection updated
                                               └─ on confirmed closure:
                                                    aggregate ledger record
```

## E.2 What moves, and what does not

| Responsibility | Today | Future | Semantics change now? |
|---|---|---|---|
| `resolve_intrabar` | `PaperBroker` decides stop-versus-target | **The domain decides** (spec 11.2, adverse-first). The policy's output survives as the ambiguity flag | **No.** Both resolve stop-first under CONSERVATIVE; only the owner moves |
| `_close` | Decides **and** executes closure | **Executes only**, on instruction | **No** |
| Same-bar exits | R1: the fill bar is evaluated | Unchanged — the domain evaluates from `opened_at` onward | **No** |
| `IntrabarPolicy` | Broker concept with four variants | **I6 — unresolved.** The domain fixes adverse-first; `OPTIMISTIC` and `MIDPOINT_HEURISTIC` have no canonical counterpart | **No** — not decided here |
| Ambiguity | `was_ambiguous_exit` per position | Produced per **evaluation** by the domain, attached to the fill that evaluation caused, with a position-level "any" | Representation only |
| `bars_held` | `position.bars_held += 1` per bar in `on_bar` | Stays **position-level**, incremented by the projection | **No** |

**[PLAN]** Every row above is a change of **owner or representation**, never of
behaviour. Behavioural change in this migration comes from one source only: the
canonical ladder now produces partials and stop promotions that did not exist.

---

# F. Partial Exit Ledger

```
  TradeRecord                  one per canonical position   ← the trade count
    position_id (PK)
    entry provenance, frozen geometry (entry, original stop, R, levels, tp_ratio)
    original quantity
    closure reason, closure time
    aggregate gross / commission / net P&L
    aggregate r_multiple
    bars_held
    any_exit_ambiguous
      │
      └── FillRecord           one per execution            ← the audit trail
            fill_id (PK), position_id (FK), sequence
            kind: ENTRY | PARTIAL_EXIT | FINAL_EXIT
            cause: M1R | STOP | TARGET | EXTERNAL | END_OF_DATA | MANUAL
            requested_level, observed_reference, executed_price
            quantity (steps and lots), time
            commission_share, was_ambiguous
            broker_order_id, broker_deal_id   (null in paper execution)
```

| Must be preserved | How |
|---|---|
| One canonical position/trade count | `len(TradeRecord)` — a partial is **not** a trade |
| Multiple fills | `FillRecord` rows |
| Exact fill quantities and prices | On each row, never averaged |
| Per-fill P&L | Computed per row at its own executed price |
| Aggregate P&L | Sum of exit rows, written once at confirmed closure |
| Commission | Pro-rata per exit fill, summing to one round turn (`commission_per_lot × original volume`) |
| Slippage | Already inside `executed_price`; **[REPO]** the reporting field is inert today |
| Original R | On `TradeRecord`, from `TradeState.r` — never derived from a current stop |
| Aggregate `r_multiple` | `total_net_pnl / money_for_price_distance(R_original, quantity_original)`, once at closure (D14) |
| Closure reason | Final `FillRecord.cause`, copied to `TradeRecord` |
| `bars_held` | Position-level on `TradeRecord` |
| Ambiguity | Per fill, plus `any_exit_ambiguous` on the record |

---

# G. R Accounting Migration

Every site found at `d15e52c`.

| # | Site | Current source | Future source | Reason |
|---|---|---|---|---|
| 1 | `execution/broker.py:271` `SimulatedPosition.risk_distance` | `abs(entry_price - stop_loss)` — **current** stop | An immutable `original_stop_price` (or `r`) field on the projection | The current stop becomes `entry` at 1R, so the distance collapses to zero |
| 2 | `backtest/ledger.py:233` `price_risk` | `position.risk_distance` | The immutable R | Inherits site 1 |
| 3 | `backtest/ledger.py:234` `risk_amount` | `money_for_price_distance(price_risk, position.volume)` | `money_for_price_distance(R_original, quantity_original)` | Same primitive, corrected inputs |
| 4 | `backtest/ledger.py:235` `r_multiple` | `net_pnl / risk_amount` | `total_net_pnl / risk_amount`, computed once at closure | Aggregate over fills (D14) |
| 5 | `backtest/metrics.py:204,206` | aggregates `r_multiple` | Unchanged | Consumes the corrected value |
| 6 | `backtest/baseline.py:550-557` `realised_r` | compares to nominal `tp_ratio` | Unchanged | Consumes the corrected value |

**[PLAN]** The formula is not altered beyond replacing a mutable input with the
immutable one already defined by spec §4.1. **R is not reinterpreted.**

---

# H. Position Projection

**[PLAN]** `SimulatedPosition` becomes the broker-facing projection.

| Field | Future status |
|---|---|
| `position_id` | **Kept** — the same value as the canonical id, not a second scheme |
| `symbol`, `side`, `entry_price`, `entry_time` | **Kept**, copied at creation, immutable |
| `stop_loss` | **Kept** as the **current** broker-side stop |
| **`original_stop_price`** | **New, immutable** — required by §G site 1 |
| `take_profit` | **Kept** — the broker-side target |
| `volume` | **Split**: `volume_at_entry` immutable, `volume_remaining` mutable, both projections of `TradeState` steps |
| `state` | **Derived** from `TradeState.lifecycle` and `closure_reason` |
| `exit_price`, `exit_time`, `exit_reason` | **Derived** — the final `FillRecord` |
| `was_ambiguous_exit` | **Derived** — `any_exit_ambiguous` |
| `bars_held` | **Kept and owned here** — position lifecycle (D6) |
| `fill`, `metadata` | **Kept** — provenance |
| `risk_distance` | **Redefined** to read the immutable original stop |

**It must not become a second source of truth for** canonical quantity,
milestones, geometry, original R or closure state. Each of those is owned by
`TradeState`; the projection carries copies for the broker's benefit and is
never consulted to make a decision.

---

# I. Existing Managers

**Nothing is retired. This is a map, not an action.**

| Old responsibility | Canonical replacement | Adapter | Broker | Reporting | R1 dependency |
|---|---|---|---|---|---|
| `trade_manager` 1R partial and stop-to-breakeven | `evaluate` → `PartialCloseRequest` + `StopModifyRequest` | Translates and submits | Executes | Fill rows | — |
| `trade_manager` 2R trail to `entry + 1R` | `LOCKED_1R` promotion | Same | Same | — | — |
| `trade_manager` stop check | Adverse-first in `evaluate` | Same | Same | — | — |
| **`trade_manager` `CLOSE_BREAKEVEN_PROTECTION`** | **None — R1 is unresolved** | — | — | — | **Retirement removes this behaviour with nothing replacing it** |
| `trade_manager.close_position` P&L | `FillRecord` + `TradeRecord` | — | — | Ledger | — |
| `order_execution.create_order` | `PendingOrderIntent` / market submission | Builds the request | — | — | — |
| `order_execution.execute_order` | Broker submission | Submits | Executes | — | — |
| `order_execution.update_current_price` milestones | `evaluate` | Drives it | — | — | — |
| `order_execution` `OrderStatus` | `TradeState.lifecycle` + stop states | Maps | — | — | — |
| `main_production.manage_positions` | Adapter loop | Owns it | — | — | — |
| `main_production._OPEN_TRADES` | Adapter registry | Owns it | — | — | — |
| `main.py` trade records and filters | Retired with the path | — | — | — | — |
| Layer 10 (`log_closed_trade`) | `TradeRecord` emission | Emits | — | Ledger | — |

**[REPO] Preserved finding:** retiring `trade_manager` removes
`CLOSE_BREAKEVEN_PROTECTION`. **It is not replaced, recreated or reinterpreted
here.** R1 must be answered before retirement, or the removal must be an
explicit, recorded acceptance.

---

# J. Integration Test Strategy

**Designed, not written.** All twenty precede production wiring.

| # | Scenario | Asserts |
|---|---|---|
| 1 | Entry | `TradeState` created from the actual fill; geometry frozen; `position_id` minted |
| 2 | 1R partial | One partial request for `floor(steps/2)`; quantity unchanged until confirmed |
| 3 | Remaining quantity | `steps_remaining` correct after confirmation; projection agrees |
| 4 | Final close | Remaining quantity closed; `CLOSED` only on confirmation |
| 5 | **Duplicate `PartialCloseFilled`** | Second application is a no-op; quantity reduced once |
| 6 | **Duplicate `CloseFilled`** | Second application does not double-close |
| 7 | **Record-then-apply recovery** | A fill recorded but not applied is applied exactly once on rebuild |
| 8 | Broker rejection | Quantity unchanged; anomaly recorded; stop still promoted where independent |
| 9 | Quantity mismatch | Broker value adopted; anomaly recorded; **severity not asserted — R4** |
| 10 | Stop promotion | Intended advances immediately; confirmed only on acknowledgement |
| 11 | Same-bar partial and final | Ordering per spec 11.1; a pending close blocks milestones |
| 12 | Gap through stop | `observed_reference` is the bar open; executed price differs from the level |
| 13 | Gap through target | Same, on the favourable side |
| 14 | Ambiguous bar | Flag set on the evaluation and carried to the fill |
| 15 | `bars_held` | Position-level, not double-counted across two exits |
| 16 | Aggregate P&L | Sum of fills, commission summing to one round turn |
| 17 | Aggregate R | `total_net_pnl / money_for_price_distance(R_original, quantity_original)` |
| 18 | Identity continuity | One `position_id` across entry, partial and final |
| 19 | Replay determinism | Two runs produce identical ids, fills and records |
| 20 | Restart/recovery | Snapshot plus fills rebuilds the state; **live scope only, gated on I2** |

---

# K. Fingerprint and Baseline Strategy

**[PLAN] The migration legitimately changes fingerprints**, because the
executable trade-management model is changing: positions that previously ran to
a single exit now take a partial at 1R and move their stop. A changed
fingerprint here is evidence the change took effect, not evidence of a defect.

**What must be compared, and what each comparison means:**

| Comparison | Expectation |
|---|---|
| Strategy candidate generation | **Byte-identical.** Trade management does not touch L1–L8 |
| Entry decisions (`decisions_fingerprint`) | **Byte-identical.** Same evidence |
| Fill decisions (which bar, which price) | Identical for entries; new rows appear for partial exits |
| Exit decisions | **Changed by design** — stop promotions alter where exits occur |
| Quantities | Changed by design — partials exist |
| P&L | Changed by design |
| Trade count | **Unchanged** — one position remains one `TradeRecord` |
| R distribution | Changed by design, **and comparable for the first time**, since §G fixes the `None` collapse |
| Ambiguity | Comparable in kind; counted per fill |
| `bars_held` | Comparable — still position-level |

**[PLAN] Old fingerprints are not automatically re-pinned.** Each change is
re-pinned in the same commit that causes it, with before and after recorded and
the cause named. **`baseline_004` is untouched and is not regenerated**; it
contains **zero trades**, so a future run producing trades is a different
executable model, never an improvement.

---

# L. Implementation Sequence

| Phase | Content | Files allowed | Files forbidden | Tests required | Stopping condition |
|---|---|---|---|---|---|
| **1 — Spec amendment** | Apply the §16.3 result-at-most-once amendment (§N) | The canonical spec only | All code | Contract suite unchanged, 88/88 | Amendment reviewed and committed |
| **2 — Fill and identity infrastructure** | `FillRecord`, `fill_id`, `position_id` scheme, in-memory append-only fill log | New module(s) under `backtest/` or `execution/` | `core/trade_model.py`, `PaperBroker`, `ledger.py`, production | New unit tests for identity determinism and dedupe | Ids reproducible across two runs; duplicate writes are no-ops |
| **3 — Ledger representation** | `TradeRecord` + fill rows; aggregate P&L and R; §G sites 2–4 | `backtest/ledger.py`, `backtest/metrics.py` | `core/trade_model.py`, production | Ledger unit tests; metrics tests | Trade count semantics unchanged; fingerprints re-pinned deliberately |
| **4 — Projection and broker verbs** | `SimulatedPosition` split and immutable original stop (§G site 1, §H); partial-close and stop-modify verbs; a rejection path | `execution/broker.py`, `execution/paper_broker.py` | `core/trade_model.py`, production | `tests/execution/test_paper_broker.py` extended | Broker can execute instructions; **still decides no exits** |
| **5 — Adapter** | `execution/trade_adapter.py`; `PaperBroker.on_bar` stops deciding exits; `ReplayEngine` drives the adapter | `execution/trade_adapter.py`, `paper_broker.py`, `backtest/replay_engine.py` | `core/trade_model.py`, production | §J 1–19 | `decisions_fingerprint` **byte-identical**; exit changes attributed |
| **6 — Integration tests complete** | Remaining §J scenarios | tests only | all production | §J 1–19 green | No scenario unwritten |
| **7 — Backtest validation** | Run on real XAUUSD; produce a **new** canonical baseline under a new id | `backtest/` artifacts | `baseline_004` | Full suite | Comparison per §K recorded; no profitability claim |
| **8 — Live integration** | Price feed (I3), `execute_order` repair, entry-point ownership (DD2), live persistence (I2) | production paths | `core/trade_model.py`, `baseline_004` | Live-path tests | `LIVE_TRADING_ENABLED` still `False`; gated on I2 and I3 |
| **9 — Retirement** | Remove the superseded managers | `trade_manager.py`, `order_execution.py`, `main.py` | — | Full suite | **Gated on R1** (§I) |

**[PLAN] One deviation from the suggested order.** Phase 4 splits the
projection and broker verbs out ahead of the adapter, because the adapter cannot
be tested without a broker able to execute a partial close, and the projection
change (§G site 1) is a prerequisite for any R-related assertion. The suggested
sequence folded these into "PaperBroker integration"; separating them keeps each
commit's blast radius to one concern.

---

# M. Open Blockers

| # | Blocker | Blocks | Status |
|---|---|---|---|
| **I2** | Restart/persistence: format, store, durability, snapshot authority | Phase 8; §J test 20 | **[UNRESOLVED]** — and the repository has **no** append-only store (§C.3) |
| **I3** | Live observation source and cadence | Phase 8 | **[UNRESOLVED]** — production has never fed a moving price |
| **I6** | `IntrabarPolicy` survival | Phase 5 | **[UNRESOLVED]** — the domain fixes adverse-first; the other variants have no counterpart |
| **I7** | Concurrency/capacity ownership | Phase 5 | **[UNRESOLVED]** — config, adapter or `may_open_position` |
| **R1** | Reversal protection | **Phase 9** | **[UNRESOLVED]** — retirement removes a behaviour |
| **R2** | Netting vs hedging | Phase 8 | **[UNRESOLVED]** — opposing positions stay refused |
| **R3** | Session/weekend handling of open positions | Phase 8 | **[UNRESOLVED]** |
| **R4** | Quantity-mismatch severity | Phase 8 | **[UNRESOLVED]** — detection is designed, grading is not |
| **U5/R8** | Observed reference on a re-requested close | Phase 5 | **[UNRESOLVED]** — the retry carries `None` |
| **U6/R9** | Rejected stop promotion behaviour | Phase 5 | **[UNRESOLVED]** — the domain raises |

**None is resolved here.** Phases 2–7 are reachable with all ten open; phases 8
and 9 are not.

---

# N. Canonical Specification Amendment

**Not applied. Documented only.**

**Why required.** §15 guarantees idempotency on the **observation** axis only.
§16 requires state to change solely from broker results but never requires a
result to be applied **at most once**. **[REPO]** `apply_broker_result` computes
`steps_remaining - result.steps_closed` unconditionally, so the same
`PartialCloseFilled` applied twice reduces quantity twice. Record-then-apply
(D11) is unsound without a specification that mandates it.

**Exact proposed semantic** — as drafted at `d15e52c` §H:

> **§16.3 Results are applied at most once.** Every quantity-changing broker
> result carries an execution identity. The adapter records the execution before
> applying it and discards a result whose identity has already been recorded. A
> result that names a different position is rejected, not applied. Several
> distinct executions arising from one request are not duplicates and are each
> applied.
>
> **§24 MUST:** a quantity-changing broker result is applied at most once,
> identified by its execution identity.
>
> **§15.1:** add a row for the identity under which the state is held, noting
> that it is adapter-supplied and that a persisted state is meaningless without
> it.

**Affected tests.** The three spec-guard tests in the contract module read the
specification text; none asserts §16 wording, so **no existing test breaks**.
New contract tests for at-most-once application would be added with the
amendment.

**When it must be applied.** **Phase 1 — before any adapter or fill
infrastructure exists**, so the mechanism is built against a specification that
requires it rather than being retrofitted.

---

# O. DO NOT IMPLEMENT UNTIL

- [ ] **This implementation plan is reviewed and approved.**
- [ ] **The canonical §16.3 amendment is reviewed** and applied in Phase 1.
- [ ] **I2 restart semantics resolved enough for the chosen scope** — for
      phases 2–7, "replay only, no persistence" is a sufficient resolution and
      must be stated as such; live scope needs the full five answers in §C.3.
- [ ] **I3 live observation source and cadence resolved** — required only for
      phase 8.
- [ ] **I6 `IntrabarPolicy` resolved** — required for phase 5.
- [ ] **I7 concurrency ownership resolved** — required for phase 5.
- [ ] **R1–R4 explicitly scoped** — R1 gates phase 9; R2–R4 gate phase 8.
- [ ] **U5/R8 and U6/R9 explicitly scoped** — both surface in phase 5; the
      current refusals must be accepted as interim behaviour or answered.
- [ ] **Integration tests designed** — §J reviewed.
- [ ] **Baseline and fingerprint strategy approved** — §K reviewed, including
      that `baseline_004` is never regenerated.

**An unresolved item is not permission to choose a behaviour silently.** Where
the plan meets one, the implementation either refuses, as the domain already
does for U6, or stops for a decision.

---

# P. Verification

**Nothing was modified.** The only new file is this document. No production
Python, test, baseline, `core/trade_model.py` or canonical specification was
changed; no adapter was built; `PaperBroker` and the ledger are unchanged;
`trade_manager` was not retired.

Read-only inspection covered `trade_persistence.py`, `backtest/ledger.py`,
`backtest/metrics.py`, `backtest/replay_engine.py`, `execution/broker.py`,
`execution/paper_broker.py`, `execution/fills.py`, `core/trade_model.py`,
`core/types.py`, `core/symbols.py`, `order_execution.py`, `trade_manager.py`,
`main_production.py` and `main.py`.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 520.3 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`d15e52c`, as expected for a documentation-only phase.

---

*Plan only. No code changed, no adapter built, no ledger altered, no specification edited, no manager retired. Stopping for review.*
