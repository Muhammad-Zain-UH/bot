# Phase 5 — Closure Report

**Documentation only.** No production Python, test, specification or baseline is
changed by this document. `baselines/baseline_004` remains **FROZEN** and was
not regenerated at any point in Phase 5. `LIVE_TRADING_ENABLED` remains the
literal `False`.

**What Phase 5 did, in one sentence:** it moved exit authority from
`PaperBroker` to the canonical trade-management domain, switched the ledger to
the Phase 3 lossless execution representation, and then — as a separately
audited second step — anchored the target to the price actually filled at.

| Commit | Scope | Files | Suite |
|---|---|---|---|
| `83b4124` | 5B-i architecture/ledger cut-over, carried target held fixed | 10 files, +1159 −990 | 864 tests, 2 known failures |
| `97363c7` | 5B-ii §4.2 target recomputation | 3 files, +366 −66 | 883 tests, 2 known failures |

The split was deliberate and is the reason this report can make causal claims at
all. Recomputing the target moves the exit bar, and therefore `bars_held` and
every figure below the exit. Had that landed in the same commit as the authority
and ledger migration, no measurement could have separated "the architecture
changed the numbers" from "the target definition changed the numbers". 5B-i
holds the target fixed and proves the migration moved nothing; 5B-ii moves the
target alone and attributes every consequence.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `97363c7` |
| **[MEASURED]** | Established by running or counting against the repository |
| **[UNRESOLVED]** | Open; **not** resolved by Phase 5 or by this document |

---

# 1. Final Architecture

## 1.1 The authoritative flow

**[REPO]** One bar, in order (`backtest/replay_engine.py:266`):

```
for opened in broker.fill_pending_orders(bar, bar_time):   # phase B
        adapter.on_position_opened(opened)                 # canonical creation
adapter.manage(bar, bar_time)                              # canonical decision
for record in adapter.drain_records():
        ledger.record_canonical(record)                    # lossless append
```

| Step | Owner | What it may decide |
|---|---|---|
| Fill a resting order | `PaperBroker.fill_pending_orders` | Whether the bar reached the level. **Returns opened positions.** |
| Count the bar | `PaperBroker`, phase C | `bars_held += 1`. Nothing else. |
| Create canonical state | `TradeAdapter.on_position_opened` | Geometry, from the fill (§4.2, §13) |
| Choose what happens | `core.trade_model.evaluate` | Milestones, stop promotion, closure, ambiguity |
| Execute | `PaperBroker` verbs | Nothing — it performs and reports |
| Record | `FillLog` then canonical state | Order is fixed: record, then apply |
| Append | `TradeLedger.record_canonical` | One `TradeRecord` per position |

**[REPO]** The broker's phase C retains exactly two responsibilities: the R1
guard (`bar_time < position.entry_time` is skipped) and the `bars_held`
increment. `resolve_intrabar` and the internal close path are gone from it
entirely, and `max_bars_held` is retired.

## 1.2 Why the fill bar is still managed

**[REPO]** Filling happens in phase B and management in the adapter, both
against the same bar, so a position filled on a bar remains eligible for its own
stop or target on that bar. This is the R1 behaviour established at `a4f7141`
and it survived both commits unchanged.

## 1.3 Record-then-apply

**[REPO]** Every quantity-changing broker result passes through
`execution.trade_identity.record_then_apply` — three call sites: partial close,
close, and end-of-data close. The result is written to the `FillLog` **before**
it reaches canonical state, so a redelivered execution is recognised at the log
and cannot produce a second economic effect (§16.3, at-most-once).

**[REPO]** A stop modification is deliberately **not** one of the three. It
produces no fill and no deal, so there is nothing for the log to deduplicate.

## 1.4 Broker rejections

**[REPO]** `TradeAdapter` raises `BrokerRejectionNotHandled` rather than
absorbing a rejection. Absorbing one would require choosing semantics for U5/R8
or U6/R9, both of which are **[UNRESOLVED]**. Raising keeps the gap visible
instead of resolving it by default.

## 1.5 The ledger

**[REPO]** `TradeLedger` holds one `TradeRecord` per canonical position, each
carrying its `TradeExecution` rows. `ledger.trades` is a **projection**
(`ledger.py:351`) — `to_simulated_trade()` per record — so every existing metric
keeps its meaning while the underlying record stops discarding partials.

## 1.6 IntrabarPolicy

**[REPO]** The policy annotates; it does not select. The domain fixes
adverse-first ordering, and the policy is consulted only to flag ambiguity. This
was the I6 decision (`71d1204`) and it is now implemented, so **I6 is no longer
in the unresolved set** (§7).

---

# 2. 5B-i Causal Result — `83b4124`

**[MEASURED]** Both R1 fixtures, captured before and after the cut-over:

| Observable | Result |
|---|---|
| `decisions_fingerprint` | **IDENTICAL** — `bf174068…` (long), `a033d076…` (short) |
| Decisions / signals | 187 / 2 and 187 / 1, unchanged |
| Entry fill price and time | IDENTICAL |
| Final exit time | IDENTICAL |
| Final exit price | IDENTICAL |
| Closure reason | IDENTICAL — `TARGET_HIT` |
| Total executed quantity | IDENTICAL — 0.01 |
| Net P&L | IDENTICAL — 39.6043185 / 23.9956815 |
| R multiple | IDENTICAL — 4.33003315 / 6.5677245 |
| Ambiguity | IDENTICAL |
| **`bars_held`** | **IDENTICAL — 24 / 20** |
| Price risk | IDENTICAL |
| Trade count | IDENTICAL — 1 |

**A) representation-only changes: 2** — the two ledger fingerprints.
**B) economic/behaviour changes: 0.**
**UNEXPLAINED = 0.**

```
long   d42a9218d75d45ba…  ->  67c95bf0960018af…
short  ca9b8a9b2f07b330…  ->  057d9b75b86133a8…
```

**[MEASURED]** The ledger fingerprint changed for one identified reason: a trade
became a `TradeRecord` carrying its executions where it had been a flat row, and
`fingerprint()` hashes that structure. Nothing economic moved.

**[MEASURED]** Two canonical events per position became real that had not
existed before — stop promotions at 1R and 2R. Zero partials, because both
fixtures trade 0.01 lots, which is one volume step, and `floor(1/2) = 0`. The
milestone is still consumed and the stop still promotes; neither promotion
caused an early stop-out, which is why the exits did not move.

---

# 3. 5B-ii Causal Result — `97363c7`

## 3.1 What changed

**[REPO]** One logic change in production code: `tp_ratio` is read from the
strategy's own metadata instead of being reconstructed from the carried
`take_profit`. `core.trade_model.open_position` already computed
`target = fill ± tp_ratio × r`, so no domain change was required.

## 3.2 Direct contract tests — 11/11 pass

**[MEASURED]** `tests/execution/test_trade_adapter.CanonicalTargetRecomputation`
fills materially away from the intended entry and carries a deliberately
different legacy target, long and short:

| | long (BUY) | short (SELL) |
|---|---|---|
| intended entry | 2450.0 | 2450.0 |
| actual fill | 2444.0 | 2456.0 |
| original stop | 2420.0 | 2480.0 |
| original R | 24.0 (intended: 30.0) | 24.0 (intended: 30.0) |
| carried legacy target | 2540.0 = **4.0R** | 2360.0 = **4.0R** |
| canonical §4.2 target | **2516.0 = 3.0R** | **2384.0 = 3.0R** |

Ratios are measured the only way that is meaningful — from the **actual fill**,
in units of the **actual** R: `|2540 − 2444| / 24 = 4.0`.

> **Correction against `97363c7`.** A source comment in
> `tests/execution/test_trade_adapter.py` describes this legacy target as
> sitting at "3.75R". That figure is wrong. 3.75 is `|2540 − 2450| / 24`, which
> divides the reward measured from the *intended* entry by the R of the *actual*
> fill — a mixed-anchor quantity that describes nothing. The correct figure is
> 4.0R. **The error is confined to that comment**: every assertion in the class
> uses absolute prices (2540.0, 2516.0) and none depends on the ratio, so the
> tests are correct and pass as written. This document does not amend the test,
> because Phase 5 is closed and this report is documentation-only; the
> correction is recorded here for whoever next edits that file.

The eleven cases assert: the target is `fill ± ratio × R` on both sides; it is
not the carried level; three different carried levels and a removed one all
yield the same canonical target; a promoted stop does not move R or the target;
`reward / R == tp_ratio` across ratios 1.5, 3.0 and 4.5 on both sides; the
broker projection follows the canonical target; and a position with no ratio is
skipped rather than guessed.

## 3.3 Fixture attribution

**[MEASURED]** Both fixtures fill **better** than intended, so R shrank and the
carried target — still anchored to the intended entry — was left at some other
multiple of the R that actually exists:

| | long (BUY) | short (SELL) |
|---|---|---|
| intended entry → actual fill | 2520.965 → 2517.874 | 2179.035 → 2182.344 |
| original R | 12.238 → **9.14642386** | 6.962 → **3.65357614** |
| `tp_ratio` requested | 3.0 | 3.0 |
| old target (carried) | 2557.678 = **4.3519R** | 2158.148 = **6.6225R** |
| new target (§4.2) | 2545.313 = **3.0000R** | 2171.383 = **3.0000R** |
| exit bar | 09:05 → **08:15** | 08:45 → **07:30** |
| exit price | 2557.478 → 2545.113 | 2158.348 → 2171.583 |
| `bars_held` | 24 → **14** | 20 → **5** |
| net P&L | 39.6043185 → 27.23927159 | 23.9956815 → 10.76072841 |
| R multiple | 4.33003315 → 2.97813353 | 6.5677245 → 2.94525911 |

**Classification: IDENTICAL 14, TARGET_RECOMPUTATION 10, UNEXPLAINED = 0.**

**[MEASURED]** `decisions_fingerprint` **unchanged**, byte-identical on both
fixtures. Decisions and signals unchanged at 187 / 2 and 187 / 1.

**[MEASURED]** Unmoved, and asserted separately from the figures below the exit:
entry fill price, entry fill time, price risk (original R), executed quantity,
ambiguity, closure reason, trade count.

## 3.4 `bars_held`

**[MEASURED]** `bars_held` changed because the target bar arrived earlier, not
because the accounting changed. Long: 07:10 → 08:15 is 13 M5 steps plus the fill
bar = 14. Short: 07:10 → 07:30 is 4 plus the fill bar = 5. The R1 property — the
fill bar is counted — holds in both.

## 3.5 Determinism

**[MEASURED]** The post-change capture was taken twice and the two JSON captures
are byte-identical. The audit re-run against the second capture reports
UNEXPLAINED = 0. The new pinned values are reproducible, not incidental.

## 3.6 Final ledger fingerprints and provenance

```
long   before 5B-i   d42a9218d75d45ba03fe7d9c849dc84c13052aa5354d078809ac141b546d821d
       before 5B-ii  67c95bf0960018afb29e1052fe4191429cd51ec11b3be7060e17fec4ef3aeb82
       FINAL         33ac2bb259d5662f386913a97b6ca0524eec7f13a0e3ceb4d455d6f65b010317

short  before 5B-i   ca9b8a9b2f07b330bbcf9306cd38de9d31ba5d2fd37d5b6bde08f6c728626559
       before 5B-ii  057d9b75b86133a8848e06442243eb1e0d3ab5b5ed0d232e8143a186767b836e
       FINAL         ce733aeb7d6220270b9cc4864a190a2970faa0981286895ef09c990d81228109

decisions_fingerprint, unchanged throughout Phase 5:
long   bf174068e992a9cf6c8b42a161bf449120fd3423bba5293761a37c007bfec7c6
short  a033d076987b8baaeae4993f70e0c1735961042f3eecedd7c6e9a04f3d92f212
```

**[REPO]** Both re-pins carry their provenance in
`tests/integration/test_r1_same_bar_regression.py`, including the superseded
values and the reason each was superseded.

---

# 4. Target Semantics

**[REPO]** The canonical rule, as implemented at `97363c7`:

```
original_R = |actual_fill - original_stop|
target     = actual_fill + tp_ratio * original_R     (long)
             actual_fill - tp_ratio * original_R     (short)
```

1. **Original R uses the original stop.** R is computed once, at creation, from
   the structural stop the strategy supplied. A stop promoted to breakeven or to
   1R does not change R, and does not change the target. Pinned by
   `test_r_comes_from_the_original_stop_not_the_promoted_one`.

2. **The target anchors on the actual fill**, not the entry the strategy
   intended. The intended entry is a *request*; the geometry belongs to the
   position that actually exists. Pinned by
   `test_the_anchor_is_the_fill_not_the_intended_entry`.

3. **`tp_ratio` is the strategy's supplied ratio**, carried on the fill metadata
   as `strategy_rr_ratio`. Pinned by `test_the_ratio_is_the_strategys_own`.

4. **The carried legacy target is no longer a source of canonical truth.** It
   takes no part in the geometry, and the adapter overwrites `take_profit` with
   the canonical target, so causality runs one way — canonical to broker — and
   nothing downstream can read the legacy level. Pinned by four tests, including
   the removal and variation cases.

5. **Realised R may differ from target R.** The target sits at exactly
   `tp_ratio × R`, but the *executed* price is filled through spread and
   slippage. On the fixtures the exit fills 0.20 off the target level, so
   realised R is 2.978 and 2.945 against a target at exactly 3.0000R. This is
   the execution cost appearing where it belongs — in the fill — and not a
   defect in the target definition.

**[REPO]** No specification amendment was required. §4.2 already states
`TP = fill_entry ± tp_ratio × R`, already carries the `[DECISION]` that the
canonical model recomputes the target at fill, and already names the
`take_profit=intent.take_profit` behaviour as the defect being corrected. The
implementation moved to meet the specification; the specification was not moved
to accommodate the implementation.

---

# 5. Behavioural Boundaries

## 5.1 No positive `tp_ratio`

**[REPO]** A position whose fill metadata carries no positive `tp_ratio` is
**skipped** — no canonical state is created, and a `SKIPPED` event records why.
It is not managed off the carried target.

**[REPO]** This is a genuine consequence of 5B-ii, not a fixture artefact. Under
the 5B-i migration control such a position would have been managed using a ratio
reconstructed from the carried level. That fallback is gone, because
reconstructing the ratio from the carried target is precisely the coupling §4.2
removes. Reinstating it as an error path would reinstate the defect.

**[MEASURED]** The normal gated production path does not generate one.
`main.py:681` always populates `rr_ratio`; `valid_rr = rr >= 2.0` gates
`entry_triggered`, so a non-positive ratio cannot reach an entry signal; and the
`calculate_entry_levels` error branch returns no stop loss, which
`replay_engine` rejects before any position exists.

**[REPO]** Pinned by `test_a_position_with_no_ratio_is_skipped_not_guessed` —
the assertion is that it skips, and that it does **not** guess.

**No new policy is created here for malformed or unadmitted positions.** Skip
is the existing `_skip` path, already used for zero R, sub-step volume and a
geometry the domain refuses. Whether such a position *should* exist at all, and
what a live path should do when one appears, is a design question and is not
answered by Phase 5.

## 5.2 Retired vocabulary

**[REPO]** `max_bars_held` is retired and the broker produces no time-based
closure. `PositionState.CLOSED_TIME` and `TradeOutcome.TIME_EXIT` remain
**defined but unproduced**, on the existing `PendingState` precedent. Retiring
the mechanism did not remove the label.

---

# 6. Test Status

**[MEASURED]** At `97363c7`:

```
Ran 883 tests
FAILED (failures=2)
  test_micro_scalp_l7_confidence_uses_55_threshold
  test_pullback_gate_requires_real_pullback_detection
errors=0
```

Both failures are the pre-existing `tests/test_layer_gate_logic` failures
carried unchanged through the whole of Phase 5. They were failing before
`83b4124` and are failing in the same way after `97363c7`.

| | 5B-i | 5B-ii |
|---|---|---|
| Tests | 864 | 883 (+19) |
| Failures | 2 known | 2 known |
| Errors | 0 | 0 |

**[MEASURED]** The 19 added tests are 13 in the adapter suite
(`CanonicalTargetRecomputation` 11, `LimitFillHandsOffToManagement` +2) and 6 in
the R1 regression file (three per fixture, separating what sits upstream of the
target from what sits downstream).

**[REPO]** `baselines/baseline_004` untouched and not regenerated — all twelve
artefacts carry their original timestamps and git reports no change to the
directory across either commit.

**[REPO]** No specification amendment required (§4).

---

# 7. Unresolved Items

**Preserved exactly. None is resolved, reinterpreted or narrowed by Phase 5 or
by this document.**

| # | Item | Gates | Status |
|---|---|---|---|
| **I2** | Restart/persistence: format, store, durability, snapshot authority | Phase 8 | **[UNRESOLVED]** — the repository has no append-only store |
| **I3** | Live observation source and cadence | Phase 8 | **[UNRESOLVED]** — production has never fed a moving price |
| **I7** | Concurrency/capacity ownership | Phase 5 | **[UNRESOLVED]** — config, adapter or `may_open_position` |
| **R1** | Reversal protection | Phase 9 | **[UNRESOLVED]** — retirement removes a behaviour |
| **R2** | Netting vs hedging | Phase 8 | **[UNRESOLVED]** — opposing positions stay refused |
| **R3** | Session/weekend handling of open positions | Phase 8 | **[UNRESOLVED]** |
| **R4** | Quantity-mismatch severity | Phase 8 | **[UNRESOLVED]** — detection is designed, grading is not |
| **U5/R8** | Observed reference on a re-requested close | Phase 5 | **[UNRESOLVED]** — the retry carries `None` |
| **U6/R9** | Rejected stop promotion behaviour | Phase 5 | **[UNRESOLVED]** — the domain raises |

**[REPO]** I7, U5/R8 and U6/R9 are recorded as surfacing in Phase 5 and were
**not** resolved by it. The adapter's raising behaviour (§1.4) is what keeps
U5/R8 and U6/R9 open rather than settled by default.

**[REPO]** I6 (`IntrabarPolicy` survival) was decided at `71d1204` and
implemented in `83b4124`, and is therefore not carried forward. It is named here
only so its absence from this table is not mistaken for an omission.

---

# 8. Performance Interpretation

**The fixture P&L changed. That is an implementation and semantics consequence
of correcting the target definition. It is NOT a profitability conclusion, in
either direction.**

Net P&L fell on both fixtures — 39.60 → 27.24 and 24.00 → 10.76 — for one
reason: the targets were previously sitting at 4.35R and 6.62R because they were
anchored to an entry that was never filled, and §4.2 brings them back to the
3.0R the strategy actually asked for. A smaller target is reached sooner and
banks less. This says nothing about whether 3.0R is the right ratio, whether the
strategy is profitable, or whether either fixture is representative.

Specifically, **none of the following is claimed or supported**:

- that the strategy is profitable, or was more profitable before;
- that 5B-ii improved or degraded performance;
- that `tp_ratio = 3.0` is well chosen, or that any target multiple is optimal;
- that two fixtures, each holding a single position, carry any statistical
  weight whatsoever.

**[MEASURED]** The correct reading is narrower and is the only one the evidence
supports: before §4.2, `reward / R` was 4.3519 and 6.6225 against a requested
3.0; after, it is 3.0000 on both. An identity the repository claims to hold now
holds by construction. That is a correctness result about the geometry, not a
performance result about the strategy.

Any performance evaluation must be run against a **new canonical baseline**,
compared against frozen `baseline_004`, with the difference attributed to the
code and model changes recorded here. No such baseline exists yet, and this
document does not create one.

---

# 9. Next-Phase Readiness

**No next phase is chosen or implemented here.** What follows is the set of
engineering and design questions that remain open, stated as questions.

## 9.1 Gating live deployment

Every item in §7 marked Phase 8 or 9 gates live deployment and is listed there,
not repeated here. Beyond those:

| # | Question |
|---|---|
| 1 | **Entry-point ownership.** `main.py`, `main_production.py` and `order_execution.py` still carry their own entry, target and RR construction. Which of them is authoritative, and which is retired? |
| 2 | **`trade_manager` retirement.** It is superseded but not removed, and its `CLOSE_BREAKEVEN_PROTECTION` has no canonical replacement. Retirement is gated on R1. |
| 3 | **Live execution path.** `execute_order` has never been exercised against the canonical adapter. What does the four-layer broker contract require of it? |
| 4 | **Partials have never executed.** Both fixtures trade one volume step, so `floor(1/2) = 0` and no partial close has ever been sent. The path is tested in isolation but has no integration evidence. |
| 5 | **Rejection semantics.** The adapter raises. Before a live path exists, U5/R8 and U6/R9 must be answered, or the raise must be an explicit deployment-blocking choice. |

## 9.2 Gating broader performance evaluation

| # | Question |
|---|---|
| 6 | **A new canonical baseline.** What dataset, period and manifest define it, and what is the comparison protocol against frozen `baseline_004`? |
| 7 | **Fixture coverage.** Two single-position fixtures cannot exercise partials, multiple concurrent positions, stop-outs after promotion, ambiguous exits or end-of-data closure with an open position. What fixture set would? |
| 8 | **The two known failures.** `test_micro_scalp_l7_confidence_uses_55_threshold` and `test_pullback_gate_requires_real_pullback_detection` have been carried for the whole phase. Are they defects in the tests or in the gates? |
| 9 | **`tp_ratio` provenance.** It is the regime constant, and `valid_rr = rr >= 2.0` therefore tests that constant rather than any property of the setup — recorded as defect E9/E10/Q3 against `baseline_004`. §4.2 makes the target honest about the ratio; it does not address where the ratio comes from. |
| 10 | **Realised R versus target R.** Execution cost now shows up as the gap between a 3.0000R target and a 2.978R realisation. Is that gap a cost model to be calibrated, or an accepted property? |

**None of these is answered here.** They are recorded so that the next phase is
chosen with the open set visible, rather than discovered during it.

---

# 10. Closure Statement

**[MEASURED]** Phase 5 moved exit authority and the ledger representation
without changing a single economic figure (`83b4124`, UNEXPLAINED = 0), and then
changed the target definition alone, with every consequence attributed
(`97363c7`, UNEXPLAINED = 0). The decisions fingerprint is byte-identical across
the entire phase on both fixtures, which establishes that nothing in the
strategy's decision path was disturbed by either commit.

`baseline_004` is untouched. The canonical specification is unamended. Nine
unresolved items are carried forward unchanged. No profitability claim is made.
