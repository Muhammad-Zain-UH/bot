# Phase 5B — Cut-Over Plan

**Plan only.** No production Python, test, baseline, `core/trade_model.py` or
canonical specification is changed. Phase 5A (`79a2b28`) is untouched.
`baseline_004` remains **FROZEN**.

**What 5B does, in one sentence:** it moves exit authority from `PaperBroker`
to the canonical domain **and** switches the ledger to the Phase 3
execution representation **in the same migration**, because doing either alone
produces a state where canonical partials are authoritative while a ledger that
cannot record them still is.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `79a2b28` |
| **[MEASURED]** | Established by running or counting against the repository |
| **[PLAN]** | A sequencing or design choice proposed here |
| **[UNRESOLVED]** | Open; **not** resolved by this plan |

---

# 1. Authority Transfer

## 1.1 Where the broker stops deciding

**[REPO]** `PaperBroker.on_bar` runs three phases:

```
  Phase A   pending maintenance     -- intentionally empty (experimental control)
  Phase B   _fill_pending(bar)      -- resting orders become positions
  Phase C   for position in open:   -- resolve_intrabar -> _close   <-- EXITS
```

**[PLAN] The cut is Phase C, and only Phase C.** A and B stay in the broker:
filling an order is execution, not management.

**[PLAN]** To avoid silently changing what a method means, `on_bar` is
**renamed**, not repurposed:

| Before | After |
|---|---|
| `on_bar(bar, bar_time) -> list[SimulatedPosition]` (**closed** positions) | `fill_pending_orders(bar, bar_time) -> list[SimulatedPosition]` (**opened** positions) |

Keeping the name while inverting the return from "closed" to "opened" would
leave every existing call site compiling and wrong. The rename makes each call
site a decision.

## 1.2 Where the domain becomes sole authority

**[PLAN]** `ReplayEngine` orchestrates; the broker never imports the adapter:

```
  ReplayEngine
      ├─ broker.fill_pending_orders(bar, bar_time)   -> opened positions
      │     └─ adapter.on_position_opened(p)          (creates TradeState)
      └─ adapter.manage(bar, bar_time)                -> closed positions
            └─ evaluate -> instruct broker -> record fill -> apply result
```

**[PLAN] Invariant CO-1:** after the cut, no code path other than
`ShadowTradeAdapter`'s successor may call `PaperBroker.execute_close`,
`execute_partial_close` or `execute_stop_modify`, and `_close` becomes
reachable **only** from `execute_close` and `close_all_at_end_of_data`.

## 1.3 `resolve_intrabar` after the cut

**[PLAN]** It is **removed as an exit selector** and retained as an annotation
producer. Concretely: the Phase C loop that consulted it is deleted; the
function remains, and the adapter may call it to record *what each policy would
have said*, never to choose.

**[PLAN] Invariant CO-2:** no call to `resolve_intrabar` may appear on any path
that closes a position. Statically checkable: `resolve_intrabar` must not be
referenced in `paper_broker.py` at all after the cut.

**[REPO]** `OPTIMISTIC` and `MIDPOINT_HEURISTIC` therefore cannot affect a
headline result, which matches what the module already says they are —
"sensitivity analysis only; must never be used to produce a headline result"
and "a heuristic, not evidence". `TICK_DATA` still raises.

**[PLAN]** Ambiguity remains recorded: the domain's own
`EvaluationResult.ambiguous` is attached to the execution it caused, and the
position-level flag stays "any exit was ambiguous".

---

# 2. Canonical State Lifecycle

## 2.1 Where production `TradeState` is created

**[REPO]** Every position — market or limit — is constructed by one function,
`PaperBroker._open_position`, reached from `submit_market_order` and from
`_fill_pending`.

**[PLAN]** The production hook is therefore **the fill**, surfaced two ways:

| Entry kind | Position created in | Adapter notified |
|---|---|---|
| Market | `submit_market_order` → `_open_position` | `ReplayEngine` calls `adapter.on_position_opened(p)` with the returned fill's position |
| Limit (LIMIT_FVG) | `_fill_pending` inside `fill_pending_orders` → `_open_position` | `ReplayEngine` calls `adapter.on_position_opened(p)` for each opened position returned |

**[PLAN] Invariant CO-3:** `TradeState` exists before the first management
observation for that position. For a limit fill this is load-bearing: the
position is created in Phase B of a bar and managed later in the same bar, so
creation must happen inside `fill_pending_orders`' return handling, before
`adapter.manage` runs for that bar.

## 2.2 How shadow `adopt()` differs from the production lifecycle

**[REPO]** 5A's `adopt(position)` takes an **already-filled** position and
reconstructs canonical state from it, including deriving `tp_ratio` from the
carried target. That is a convenience for running beside an existing engine.

**[PLAN]** Production differs in three ways, and the plan must not carry the
convenience across:

| | Shadow (5A) | Production (5B) |
|---|---|---|
| When | Any time after the fill | **At** the fill, before any observation |
| `tp_ratio` | **Reconstructed** from the carried target, so canonical target equals legacy | **Supplied by the strategy** — the regime's value, carried on the fill metadata |
| Target | Equal to the legacy target by construction | **Recomputed from the actual fill** (§4.2): `entry ± tp_ratio × R` |

**[PLAN]** This is a second behaviour change landing in 5B, and it must be
named in the audit (§7) separately from the ladder: a cost-adjusted or gapped
fill makes the recomputed target differ slightly from the carried one.

**[UNRESOLVED]** No restart or recovery behaviour is introduced. **I2 remains
unresolved**; a replay that dies is re-run.

---

# 3. Execution Flow — one position, end to end

BUY 1.00 lot, fill 2450.00, original stop 2420.00, `tp_ratio` 3.0. R = 30.00,
so M1R 2480.00, M2R 2510.00, target 2540.00. 1.00 lot = 100 steps.

| # | Stage | Adapter | Broker verb | Broker result | Fill ledger | `TradeState` |
|---|---|---|---|---|---|---|
| 1 | **Entry fill** | `on_position_opened(p)`; mint `position_id`; `open_position(...)` | — (already filled) | — | `FillRecord(ENTRY, 100 steps @ 2450.00)` | created, `OPEN`, 100 steps, stop `ORIGINAL` |
| 2 | **First observation** | build `PriceObservation`; `evaluate` | — | — | — | `last_evaluated_time` advances |
| 3 | **1R reached** | `evaluate` emits `PartialCloseRequest(50)` + `StopModifyRequest(2450.00, BREAKEVEN)` | `execute_partial_close(volume=0.50, reference_price=2480.00, operation_id=…)` | `FILLED`, executed 0.50 @ cost-adjusted price, `remaining_volume` 0.50 | `record_then_apply` → `FillRecord(PARTIAL_EXIT, 50, cause M1R)` | `PartialCloseFilled(50)` → 50 steps remain |
| 4 | **Stop promotion** | same evaluation | `execute_stop_modify(stop_price=2450.00, operation_id=…)` | `BrokerModifyResult` confirmed | **no fill** — a modification transfers no quantity | `StopModifyConfirmed` → `stop_state_confirmed = BREAKEVEN` |
| 5 | **2R reached** | `evaluate` emits `StopModifyRequest(2480.00, LOCKED_1R)` | `execute_stop_modify(2480.00)` | confirmed | no fill | `stop_state_confirmed = LOCKED_1R` |
| 6 | **Target reached** | `evaluate` emits `CloseRequest(TARGET, requested_level=2540.00, observed_reference=…, steps=50)` | `execute_close(reference_price=observed_reference, state=CLOSED_TARGET, reason="TARGET", ambiguous=…)` | `FILLED`, executed 0.50 @ cost-adjusted, `closed_position=True` | `record_then_apply` → `FillRecord(FINAL_EXIT, 50, cause TARGET)` | `CloseFilled` → `CLOSED`, reason `TARGET`, 0 steps |
| 7 | **Aggregate** | `trade_record_from_fills(...)` from the three fills + frozen geometry | — | — | — | terminal; record emitted **once** |

**[PLAN]** Step 4 has no fill row by design — specification §16.3: a stop
modification produces no execution and therefore no execution identity.

**[PLAN] Invariant CO-4:** every quantity-changing result passes through
`record_then_apply`. Nothing calls `apply_broker_result` directly.

---

# 4. Ledger Cut-Over

**[PLAN]** `TradeLedger` gains a canonical store and the existing one becomes a
view:

| Member | After the cut |
|---|---|
| `record_canonical(TradeRecord)` | **New.** The authoritative append |
| `records` | **New.** The canonical records |
| `trades` | Becomes a **projection**: `[r.to_simulated_trade() for r in records]` |
| `fingerprint()` | Hashes the **canonical** records, so executions are covered |
| `write_jsonl` | Writes canonical records, executions nested |
| `record(SimulatedTrade)` | Retained for rejections/compatibility paths that still build flat rows |

**[PLAN]** Consequences, each an invariant:

| # | Invariant |
|---|---|
| CO-5 | Every partial **and** final execution appears as a `TradeExecution` row |
| CO-6 | One canonical position produces exactly **one** `TradeRecord`; `len(records)` keeps the meaning `total_trades` has today |
| CO-7 | A redelivered execution is a no-op: the `FillLog` key gate runs **before** the domain sees it |
| CO-8 | `price_risk` and `risk_amount` come from `original_stop_price`, never from the promoted stop |
| CO-9 | Per-fill P&L and commission are lossless: aggregate equals the sum over executions, and commission sums to one round turn |
| CO-10 | `SimulatedTrade` is produced **only** by `to_simulated_trade()` for consumers that need a flat row; it is never authoritative |

**[REPO]** `backtest/metrics.py` consumes `ledger.trades`, so keeping `trades`
as a projection means metrics need no change and `total_trades` keeps its
meaning.

---

# 5. Position Projection

**[PLAN]** After the cut, `SimulatedPosition` is broker-facing only.

| Field | Status |
|---|---|
| `position_id`, `symbol`, `side`, `entry_price`, `entry_time`, `fill`, `metadata` | **Authoritative broker facts** — the fill happened |
| `volume` (entry size), `volume_closed`, `remaining_volume` | **Authoritative broker quantity** — what the broker still holds. Canonical quantity is `TradeState.steps_remaining`; the two are reconciled, never inferred from one another |
| `stop_loss` | **Broker-facing current stop** — where protection sits |
| `original_stop_price` | **Authoritative** — the immutable entry stop (§4, D13) |
| `take_profit` | Broker-facing target |
| `bars_held` | **Authoritative, position-level** — incremented by the broker as today |
| `state`, `exit_price`, `exit_time`, `exit_reason`, `was_ambiguous_exit` | **Set only by an adapter-instructed close.** No longer inferred from a broker decision |
| `is_partially_closed` | Broker view of a partial |

**[PLAN] Invariant CO-11:** these canonical facts must **not** be read off the
projection: remaining canonical quantity, milestone state, stop state, R,
closure reason, and whether a position is canonically closed. Each has exactly
one owner in `TradeState`.

---

# 6. Time Exit

**[PLAN] Retire the `max_bars_held` closure during the cut-over**, per D20 and
the standing instruction.

**[REPO]** It is inert: `max_bars_held` defaults to `None` and **no caller
anywhere sets it** — not `baseline.py`, not `runner.py`, not `replay_engine`.
Only two tests configure it directly.

**[PLAN]** What changes:

| Item | Treatment |
|---|---|
| The `max_bars_held` block in the Phase C loop | **Removed** with Phase C |
| The `max_bars_held` constructor parameter and slot | **Removed** |
| `PositionState.CLOSED_TIME`, `TradeOutcome.TIME_EXIT` | **Kept as defined-but-unproduced vocabulary**, exactly as `PendingState.EXPIRED`/`INVALIDATED`/`CANCELLED` already are |
| `tests/backtest/test_ledger_and_metrics.py` mapping assertions | **Unchanged** — they assert the mapping, which survives |

**[PLAN]** Leaving it would create a second closure authority, which CO-1
forbids. No canonical time exit is introduced; D2 stays deferred. **No
`EXTERNAL` mapping is invented, and R3 is untouched.**

---

# 7. Fingerprint and Regression Boundary

## 7.1 Classification

| Must **not** change | Expected to change |
|---|---|
| Candidate generation (L1–L8) | `ledger_fingerprint` |
| `decisions_fingerprint` | `run_fingerprint` (contains the ledger hash) |
| `baseline_004` and its artifacts — never regenerated | Realised P&L and quantities, where a partial now exists |
| `bars_held` **semantics** and values | Trade **record shape** (executions nested) |

**[PLAN] Invariant CO-12:** `decisions_fingerprint` is byte-identical before and
after. Trade management runs after L1–L8 and cannot touch the decision stream.
If it moves, the cut-over is wrong and must stop.

**[PLAN] Invariant CO-13:** `bars_held` per position is unchanged. A partial
does not end a position, and the broker still increments it. If a value moves,
that is a defect, not a re-pin.

## 7.2 How the difference is audited **before** any hash is re-pinned

**[PLAN]** 5A's shadow run is the oracle. The audit is a three-step comparison,
run on the existing fixtures and on the real-data replay:

1. **Pre-cut baseline capture.** At `79a2b28`, record for every fixture: the
   `decisions_fingerprint`, the ledger fingerprint, and per position the entry
   price/time, exit price/time/reason, `bars_held`, and the **5A shadow event
   stream**.
2. **Post-cut capture.** The same, with the adapter authoritative.
3. **Classification.** Every difference must fall into exactly one bucket:

   | Bucket | Accepted when |
   |---|---|
   | `IDENTICAL` | Entry, `bars_held`, and — before the first promotion — exits match |
   | `NEW_CANONICAL_EVENT` | A partial or a stop promotion, present post-cut and impossible pre-cut |
   | `DIVERGENT_AFTER_PROMOTION` | An exit differing **after** a recorded promotion, traceable to the promoted stop |
   | `TARGET_RECOMPUTATION` | An exit price differing because §4.2 recomputed the target from the fill (§2.2) |
   | **`UNEXPLAINED`** | **Must be empty.** Any member blocks the cut-over |

**[PLAN] Invariant CO-14:** hashes are re-pinned only after `UNEXPLAINED` is
empty, and the re-pin commit records the before and after values and the bucket
each change fell into.

**[PLAN]** The post-cut real event stream must **equal** the 5A shadow event
stream on the same fixtures. That is the strongest available check: 5A recorded
what the domain would do; 5B must do exactly that.

---

# 8. Same-Bar and R1 Behaviour

**[REPO]** R1 (`a4f7141`) established that a position **is** evaluated on the
bar it filled on: the guard is `bar_time < position.entry_time`, so equality is
allowed, and `bars_held` counts the fill bar.

**[PLAN]** The canonical domain preserves this exactly, by the same shape of
guard: `evaluate` returns a no-op when `observation.time < state.opened_at`, and
`opened_at` is the fill bar's open time. Equality is allowed, so the fill bar is
managed.

**[PLAN]** Ordering after the cut, per bar:

```
  1. Phase A  pending maintenance        broker, still intentionally empty
  2. Phase B  fill_pending_orders        broker: resting orders become positions
  3.          adapter.on_position_opened  canonical state created for each
  4.          adapter.manage(bar)         evaluate every position, including
                                          those opened in step 2 on this bar
```

| Requirement | Preserved by |
|---|---|
| Pending maintenance before fill | Step 1 before step 2, unchanged |
| Pending fill before management | Step 2 before step 4 — the same order `on_bar` has today |
| Same-bar stop handling | Step 4 evaluates the fill bar; adverse-first applies |
| Entry-bar behaviour of `a4f7141` | `opened_at` equality allowed in `evaluate` |

**[PLAN] Invariant CO-15:** a position filled on bar N is evaluated on bar N,
and `bars_held` counts that bar.

---

# 9. Test Migration

**[MEASURED]** 66 methods change because the authoritative exit path changes.
**This is required semantic migration, not cleanup.**

| File | Affected | Category |
|---|---|---|
| `tests/execution/test_paper_broker.py` | `ExitTests` 7 exit cases, `SameBarExitTests` 5 exit cases | Move to the adapter suite: same outcomes, decided by the domain |
| | `ExitTests::test_time_stop`, `SameBarExitTests::test_max_bars_held_fires_at_the_configured_count` | **Retired** with §6 |
| | `AmbiguousBarTests::test_optimistic_resolves_to_the_target`, `::test_the_two_policies_genuinely_disagree` | Rewritten: the **annotation** differs, the **outcome** does not |
| | `AmbiguousBarTests` conservative/unambiguous/tick (3), `SameBarExitTests` `bars_held`/pre-fill/timing (3), `ExitTests` end-of-data + capacity (2) | **Preserved** |
| | `EntryTimingTests` (6), `FillCostTests` (5) | **Unaffected** |
| `tests/execution/test_pending_limit_orders.py` | `FillThenExitOnTheSameBarTests` (4) | Move to the adapter suite; one is a policy-annotation rewrite |
| | The other 21 | **Unaffected** — the fill path stays in the broker, though calls rename to `fill_pending_orders` |
| `tests/execution/test_broker_execution_verbs.py` | `ExistingBehaviourUnchanged`: the two "still closes as before" tests | **Obsolete by design** — they pin the old engine deciding |
| | `test_ambiguity_semantics_are_unchanged` | Rewritten as an annotation assertion |
| | The other 27 | **Unaffected** |
| `tests/integration/test_r1_same_bar_regression.py` (11) | Both pinned fingerprints | **Re-pinned with provenance**, only after §7.2 |
| | `bars_held` assertions | **Must not move** (CO-13) |
| | Outcome/exit assertions | Become canonical-record assertions |
| `tests/execution/test_shadow_equivalence.py` (22) | `ShadowChangesNothing`, `PolicyIsAnnotationOnly`, `NewCanonicalEvents::test_the_broker_stop_is_not_moved_by_the_shadow` | **Migrate**: "shadow changes nothing" is false once the adapter is authoritative. The comparison oracle is preserved as the cut-over audit (§7.2) |
| | The rest | Become the adapter integration suite |

**[PLAN]** The two `tests/test_layer_gate_logic.py` failures are preserved
untouched. No unrelated test is modified.

---

# 10. Safety Checks — cut-over invariants

| # | Risk | Invariant | How it is checked |
|---|---|---|---|
| CO-1 | Two exit authorities | Only the adapter may call the close/partial/modify verbs; `_close` reachable only from `execute_close` and end-of-data | AST test over `paper_broker.py` and `replay_engine.py` |
| CO-2 | Policy still selecting exits | `resolve_intrabar` is not referenced in `paper_broker.py` | AST/source test |
| CO-16 | Broker closes a position on its own | `fill_pending_orders` returns only **opened** positions and closes nothing | Test: a bar covering stop and target closes nothing without the adapter |
| CO-4 | A result applied twice | Every result goes through `record_then_apply`; `apply_broker_result` is called nowhere else | AST test over the adapter |
| CO-7 | Duplicate delivery | A known `fill_id` is a no-op before the domain is reached | Existing Phase 2 tests plus an adapter-level test |
| CO-17 | Recorded but not applied | Not possible: `record_then_apply` applies only after a new record, and the rebuild path replays fills | Test: fill-log count equals quantity-changing applications |
| CO-18 | Applied but not recorded | Same mechanism, from the other side | Same test |
| CO-19 | Two records for one position | One `TradeRecord` per canonical closure, emitted once | Test: partial + final ⇒ one record, two executions |

---

# 11. Remaining Blockers

**None of the following is resolved by this plan.**

| Item | 5B dependency | Status |
|---|---|---|
| **I2** persistence/restart | **None** — replay is re-run, not recovered | **[UNRESOLVED]** |
| **I3** live observation cadence | **None** — backtest only | **[UNRESOLVED]** |
| **I7** concurrency ownership | **None** — `has_capacity` is entry-side and unchanged | **[UNRESOLVED]** |
| **R1** reversal protection | **None** — not implemented, not replaced | **[UNRESOLVED]** |
| **R2** netting vs hedging | **None** | **[UNRESOLVED]** |
| **R3** session/weekend | **None** — §6 introduces no time or session rule | **[UNRESOLVED]** |
| **R4** anomaly severity | **None** — anomalies recorded, not graded | **[UNRESOLVED]** |
| **U5/R8** retry reference | **Latent, see below** | **[UNRESOLVED]** |
| **U6/R9** rejected promotion | **Latent, see below** | **[UNRESOLVED]** |

**[PLAN] Two latent dependencies, unreachable in paper execution.** A rejected
close makes the domain re-request with `observed_reference=None` (U5), and a
rejected stop promotion makes the domain raise when the next milestone becomes
reachable (U6). **[REPO]** `PaperBroker` rejects a close or a modification only
for an unknown position or an unusable price, neither of which the adapter can
produce for a position it is tracking, so **neither path is reachable in the
backtest**.

**[PLAN] Invariant CO-20:** the adapter must not paper over either. On a
rejected close it records the anomaly and leaves the position open without
inventing a reference price; a `UnresolvedCanonicalDecisionError` from the
domain propagates. If a future broker can reject, **U5 and U6 must be answered
before that broker is wired** — 5B does not answer them.

---

# 12. Summary

## 12.1 Proposed file changes

| File | Change |
|---|---|
| `execution/trade_adapter.py` | Shadow adapter becomes authoritative: `on_position_opened`, `manage`, `close_all_at_end_of_data`; instructs the broker instead of self-confirming; emits `TradeRecord` on closure |
| `execution/paper_broker.py` | Phase C removed; `on_bar` → `fill_pending_orders` returning opened positions; `max_bars_held` removed; `resolve_intrabar` import dropped |
| `backtest/ledger.py` | `record_canonical`, `records`, `trades` as projection, `fingerprint` over canonical records, `write_jsonl` nested |
| `backtest/replay_engine.py` | Drives broker then adapter; records `TradeRecord`s |
| `execution/broker.py` | Possibly none; `CLOSED_TIME` retained |
| Tests | §9 — 66 methods across five files |

## 12.2 Migration order

| Step | Content | Gate |
|---|---|---|
| 1 | Capture the pre-cut audit baseline (§7.2 step 1) | Recorded, committed as data |
| 2 | Ledger gains the canonical store; nothing produces it yet | Suite green; fingerprints unchanged |
| 3 | Adapter becomes authoritative; Phase C removed; replay rewired; `max_bars_held` retired | **One commit** — authority and ledger together |
| 4 | Run the audit; classify every difference | `UNEXPLAINED` empty |
| 5 | Re-pin fingerprints with provenance | Recorded before/after and buckets |
| 6 | Migrate tests per §9 | Suite green but for the two known failures |

**[PLAN]** Steps 3 and the ledger switch cannot be separated; step 2 is
preparatory and observable-free.

## 12.3 Exact invariants

CO-1 single exit authority · CO-2 policy never selects · CO-3 state before first
observation · CO-4 all results via `record_then_apply` · CO-5 every execution
represented · CO-6 one record per position · CO-7 duplicate delivery is a no-op
· CO-8 risk from the original stop · CO-9 lossless per-fill economics · CO-10
`SimulatedTrade` never authoritative · CO-11 canonical facts not read off the
projection · CO-12 `decisions_fingerprint` byte-identical · CO-13 `bars_held`
unchanged · CO-14 re-pin only after a clean audit · CO-15 fill bar is managed ·
CO-16 broker closes nothing alone · CO-17/18 record and apply are inseparable ·
CO-19 one record per closure · CO-20 rejection paths not papered over.

## 12.4 Blockers

**None blocks the cut-over.** Two latent dependencies (U5, U6) are unreachable
in paper execution and are guarded by CO-20 rather than decided.

## 12.5 Specification amendment

**Not required.** §16.3 (at-most-once) landed in Phase 1; §11.2 already fixes
adverse-first; §18 already places the cost model and order ids in the adapter;
§8.3 already records that `CLOSED_TIME` has no canonical counterpart. Nothing in
this plan needs a new canonical rule.

---

# 13. Verification

**Nothing was modified.** The only new file is this document. Phase 5A is
untouched.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **866** |
| Duration | 518.7 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`79a2b28`, as expected for a documentation-only phase.

---

*Plan only. No code changed, no authority moved, no ledger switched, no fingerprint re-pinned. Stopping for review.*
