# Phase 4B — Exit Ownership: Intrabar Policy, Time Exit and Migration

**Design and evidence only.** No production Python, test, baseline,
`core/trade_model.py` or canonical specification is changed. No adapter is
created. `baseline_004` remains **FROZEN**.

**Why this document exists.** Phase 5 stopped before writing code: moving exit
decisions into the canonical domain cannot be done without answering two
questions the specification leaves open, and the instruction for that phase
forbade answering them silently. This resolves exactly those two, plus the
migration boundary.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `455fa48` |
| **[MEASURED]** | Established by running or counting against the repository |
| **[DECISION]** | A design proposal for review — not implemented |
| **[UNRESOLVED]** | Cannot be settled from existing evidence |

## Two corrections to the blocker report

**[MEASURED]** Two figures I gave when stopping Phase 5 were wrong, in the
conservative direction, and are corrected here:

1. I said "94 test methods" break. That was the **total** in every file whose
   text matched `on_bar` — inflated by `decision_bar_time` and `entry_bar_time`
   matching as substrings. Searching for the actual call `\.on_bar(` gives
   **four** files, one of them production:

   | File | `.on_bar(` call sites |
   |---|---|
   | `tests/execution/test_paper_broker.py` | 24 |
   | `tests/execution/test_pending_limit_orders.py` | 16 |
   | `tests/execution/test_broker_execution_verbs.py` | 9 |
   | `backtest/replay_engine.py` | **1** |

   The genuinely affected set is **44 test methods**, not 94 (§F).

2. I implied the time exit was live. **[REPO]** It is not: `max_bars_held`
   defaults to `None` and **no caller anywhere sets it** — not
   `backtest/baseline.py`, not `backtest/runner.py`, not `replay_engine`. It is
   exercised only by its own two tests.

---

# A. I6 — Intrabar Policy Traced

## A.1 What the policy actually governs

**[REPO]** `execution/intrabar.py:116-190`. `resolve_intrabar` is consulted on
every bar, but the **policy only matters when both levels are touched**:

| Bar situation | Result | Policy consulted? |
|---|---|---|
| Neither level touched | `hit_stop=False, hit_target=False`, `was_ambiguous=False` | **No** |
| Exactly one touched | That one, `was_ambiguous=False` | **No** |
| **Both touched** | Policy decides, `was_ambiguous=True` | **Yes** |

This is the single most important fact in this section: **the four policies
agree on every unambiguous bar and differ only on ambiguous ones.**

## A.2 Each variant, its behaviour and its consumers

| Variant | Behaviour on an ambiguous bar | Repository's own description | Consumers |
|---|---|---|---|
| `CONSERVATIVE` | Resolves to the **stop** | "**The Phase 2A baseline.**" | The default everywhere: `PaperBroker.__init__`, every baseline and replay run |
| `OPTIMISTIC` | Resolves to the **target** | "Sensitivity analysis only; **must never be used to produce a headline result**" | `test_paper_broker.py:312,324`; `test_pending_limit_orders.py:219` |
| `MIDPOINT_HEURISTIC` | Infers from bar direction: a bar closing up is assumed to have traded to its low first | "**A heuristic, not evidence.**" | **No consumer at all** — no test, no caller |
| `TICK_DATA` | **Raises** `NotImplementedError` | "raises if unavailable rather than silently falling back, because a silent fallback would misrepresent the method used" | `test_paper_broker.py:338` asserts it raises |

**[REPO]** `MIDPOINT_HEURISTIC` is implemented and unused. Per the standing
rule, an unused policy is **not** assumed safe to delete — it is simply
recorded as unreferenced.

## A.3 Against canonical §11.2

**[REPO]** The canonical model fixes **adverse-first**: when a stop and a
favourable level are both reachable in one observation and the sequence is
unknowable, the stop is taken. On an ambiguous bar that is **exactly
`CONSERVATIVE`'s answer**.

**[REPO]** §11.2 is explicit that this is *not* inherited from
`resolve_intrabar`: "It is **not** adopted because `paper_broker`'s
`IntrabarPolicy.CONSERVATIVE` does the same… It is adopted because an
unknowable sequence resolved in the favourable direction would systematically
overstate results." The agreement is a coincidence of conclusion, not of
authority.

**[REPO]** §11.4 additionally requires that ambiguity be **flagged and
countable**, and states that "where tick data is available, the true sequence
supersedes the policy."

## A.4 Is the clean architecture viable?

**[DECISION] Yes**, and the evidence is §A.1: because the policy only speaks on
ambiguous bars, and because the domain's answer on those bars equals
`CONSERVATIVE`'s, a split is available that keeps one decision-maker:

```
  canonical domain   decides every exit, always adverse-first (§11.2)
  broker / backtest  supplies the bar, and annotates each resolution with
                     "was this bar ambiguous, and what would each policy have
                      said?" -- information, not authority
```

Answering the specific questions:

| Question | Answer | Evidence |
|---|---|---|
| Does `OPTIMISTIC` still alter executable outcome? | **No.** Outcomes become `CONSERVATIVE`'s in every case | The domain decides; the policy is not consulted |
| Does `MIDPOINT_HEURISTIC` still alter executable outcome? | **No**, same reason. It has no consumer today, so nothing observable changes | [REPO] unreferenced |
| Does `TICK_DATA` remain a separate mode? | **Yes**, unchanged. It still raises when asked to resolve, and §11.4 already reserves the meaning "true sequence supersedes the policy" for when ticks exist | [REPO] + §11.4 |
| Can the policies remain as annotations without becoming a second decision engine? | **Yes** — provided the annotation is *recorded* and never *read back* to choose an exit. That is a testable prohibition | [DECISION] |
| What tests would necessarily change? | 5 in `AmbiguousBarTests`, plus one in `test_pending_limit_orders` (§F) | [MEASURED] |
| What historical behaviour is intentionally lost? | **Sensitivity analysis by re-running under `OPTIMISTIC`** — see §A.5 | [REPO] |

## A.5 The one thing genuinely lost, stated plainly

**[REPO]** Today, running a backtest with `OPTIMISTIC` produces a *different
result*, which is what makes it a sensitivity tool. Once the domain decides,
that capability disappears: the run would produce `CONSERVATIVE` outcomes
whatever the policy says.

**[DECISION]** What survives is the **bound**, not the alternative: §11.4
already requires every ambiguous resolution to be flagged and counted, so the
number of positions whose outcome was decided by policy rather than evidence
remains measurable. What is lost is the counterfactual P&L of resolving them
the other way.

Three ways to keep it, for the record — **none adopted here**:

| Option | Cost |
|---|---|
| Accept the loss; report the ambiguity count | Nothing to build; the bound is weaker than the counterfactual |
| Compute a counterfactual report from the flagged bars | New reporting work, no behaviour change |
| Give the domain a policy parameter | **Would require a canonical amendment** — §11.2 fixes adverse-first deliberately |

---

# B. I6 Decision — validated against the repository

The direction under investigation was:

> "IntrabarPolicy remains an observation/ambiguity policy, while canonical
> trade-management decisions always use the canonical adverse-first ordering."

**[DECISION] Validated. It works, with one honest cost and no hidden semantic
change**, because:

1. **[REPO]** Policies differ only on ambiguous bars (§A.1), so nothing changes
   on any unambiguous bar under any policy.
2. **[REPO]** On ambiguous bars the domain's answer is `CONSERVATIVE`'s, which
   is the default and the baseline, so the default configuration's outcomes are
   unchanged by *this* decision. (Outcomes do change in Phase 5A, but from the
   milestone ladder — §E.3 — not from intrabar ordering.)
3. **[REPO]** The modules' own docstrings already deny `OPTIMISTIC` and
   `MIDPOINT_HEURISTIC` any authority over headline results: "sensitivity
   analysis only; must never be used to produce a headline result", and "a
   heuristic, not evidence". Demoting them to annotations matches what the
   repository already says they are.
4. **[REPO]** `TICK_DATA` needs no change: it raises today, and §11.4 reserves
   its eventual meaning.

**No contradiction found.** The cost is §A.5, and it is a capability loss, not a
semantic conflict.

---

# C. Time Exit Traced

## C.1 Every site

| Site | Content |
|---|---|
| `execution/paper_broker.py:82,88` | `max_bars_held: int | None = None` — **default off** |
| `execution/paper_broker.py:792-800` | After stop and target are resolved: if `bars_held >= max_bars_held`, close at **`bar_close`**, state `CLOSED_TIME`, reason `"time stop after N bars"`, `ambiguous=False` |
| `execution/broker.py:65` | `PositionState.CLOSED_TIME` |
| `backtest/ledger.py:99` | `CLOSED_TIME → TradeOutcome.TIME_EXIT` |
| `backtest/ledger.py:77,91` | `TIME_EXIT` is a member and **counts as a completed trade** |
| `backtest/metrics.py` | Consumes outcomes generically; `TIME_EXIT` appears in `by_outcome` |
| `tests/execution/test_paper_broker.py:262-268` | `test_time_stop` — constructs with `max_bars_held=2`, asserts `CLOSED_TIME` |
| `tests/execution/test_paper_broker.py:446-455` | `test_max_bars_held_fires_at_the_configured_count` |
| `tests/backtest/test_ledger_and_metrics.py:140,150` | Asserts the state→outcome mapping and that `TIME_EXIT` is completed |

**[REPO] No caller sets `max_bars_held`.** Not `baseline.py`, not `runner.py`,
not `replay_engine.py`. It is inert in every real run and exercised only by the
two tests that configure it directly.

## C.2 What it means, and what the canonical model says

**[REPO]** The existing time exit is a **bar-count stop**: hold no longer than
N bars on the driving timeframe, then close at that bar's close. It is not
risk-driven and not strategy-driven.

**[REPO]** The canonical model has **no time-based exit**. §9.2 lists
"Time-based exit (240-minute maximum hold)" as **DEFERRED** (D2), and §8.3
records that `CLOSED_TIME` has "**no canonical counterpart**". No canonical
time-exit concept is invented here.

## C.3 The two treatments

| | **Option A — retire** | **Option B — retain as a non-canonical safety closure** |
|---|---|---|
| Behaviour change | None in any real run: no caller sets it. The capability leaves the simulator | None while unset; if ever set, the broker closes a position the domain did not decide to close |
| Affected tests | `test_time_stop`, `test_max_bars_held_fires_at_the_configured_count` retired. The mapping assertions in `test_ledger_and_metrics` survive if the enum members stay | Same two tests survive, plus new tests for the hand-back contract |
| Affected fingerprints | **None** — nothing produces a time exit today | None while unset |
| Reporting | `TIME_EXIT` becomes an outcome nothing produces | `TIME_EXIT` keeps a producer |
| Two closure authorities? | **No** | **Yes, inherently** — mitigated only by the contract in §C.4 |
| Canonical `CLOSED` compatibility | Clean: every closure is domain-decided | The domain would believe the position open unless the closure is fed back (§C.4) |

**[REPO] Precedent for retiring the mechanism while keeping the labels:**
`PendingState.EXPIRED`, `INVALIDATED` and `CANCELLED` are defined and
deliberately **never produced**, recorded as an experimental control. A
`CLOSED_TIME` that no rule produces would sit in exactly that category.

## C.4 If Option B is chosen — the smallest contract

**[DECISION]** Option B is only safe if all five hold, and they are stated so it
cannot drift into a second trade-management engine:

1. **Off by default.** `max_bars_held is None` unless explicitly configured.
2. **It may not manage.** It never moves a stop, never takes a partial, never
   consumes or advances a milestone.
3. **It is subordinate.** It may only fire on an observation where the domain
   requested nothing and has no outstanding close.
4. **It must be fed back.** When it fires, the adapter must inform the domain,
   or canonical state diverges from the broker. **[REPO]** The canonical model
   already has the mechanism: `PositionGone` → `ClosureReason.EXTERNAL`, which
   is defined as a closure "for a cause the model did not initiate". Nothing new
   is invented.
5. **It must be labelled distinctly** in reporting, so it can never be read as a
   strategy exit.

**[REPO] A gap this exposes, recorded not solved:** canonical
`ClosureReason.EXTERNAL` has **no counterpart** in `PositionState` or
`TradeOutcome`. Under Option B a time exit would reach the ledger as `EXTERNAL`
with nowhere to map, or as `TIME_EXIT` with no canonical origin. That mapping
belongs to the ledger wiring phase.

---

# D. Time-Exit Proposed Decision

**[DECISION] Option A — retire the time-exit mechanism during the canonical
migration; keep `PositionState.CLOSED_TIME` and `TradeOutcome.TIME_EXIT` as
defined-but-unproduced labels.**

Evidence:

1. **[REPO]** It is inert. No caller sets `max_bars_held`, so retiring changes
   no real run and no fingerprint.
2. **[REPO]** The canonical model has no time exit and defers the concept
   (§9.2 D2). Keeping a broker-side one would be a capability the canonical
   model does not know about.
3. **[REPO]** Option B necessarily creates a second closure authority, and even
   with the §C.4 contract it needs a feedback path and a ledger mapping that
   does not exist (`EXTERNAL` has no `TradeOutcome`).
4. **[REPO]** Keeping the labels unproduced follows the existing `PendingState`
   precedent, so the vocabulary survives for a future canonical decision on D2
   without a mechanism running underneath it.

**Cost, stated:** the simulator loses an unused safety valve. If a time exit is
ever wanted it should arrive canonically, through D2, not as a broker rule.

**If the strategy owner prefers Option B**, §C.4 is the contract it must be
built to, and the `EXTERNAL` mapping gap must be closed first.

---

# E. Fingerprint Migration

## E.1 How fingerprints are produced

| Fingerprint | Produced by | Covers |
|---|---|---|
| `decisions_fingerprint` | `backtest/baseline.py` `decision_stream_fingerprint(snapshots)` | The ordered decision stream: time, regime, signal type, direction, layers passed, layer failed, fail reason |
| `ledger_fingerprint` | `TradeLedger.fingerprint()` — SHA-256 over `[t.to_dict() for t in trades]` | Every field of every trade record |
| `run_fingerprint` | `baseline.py` — folds the overall hash, the decisions hash and the ledger fingerprint together | Both of the above |

## E.2 Classification

| # | Class | Members |
|---|---|---|
| 1 | **MUST remain identical** | Strategy candidate generation; `decisions_fingerprint`. Trade management touches neither: the decision stream is produced by L1–L8 before any position exists |
| 2 | **Expected to change** | `ledger_fingerprint` and therefore `run_fingerprint`; every metric derived from exits — P&L, R distribution, `by_outcome`, ambiguity counts |
| 3 | **Untouched, never regenerated** | `baseline_004` and all its artifacts |
| 4 | **Deliberately re-pinned, with provenance** | `tests/integration/test_r1_same_bar_regression.py`: `LONG_LEDGER_FINGERPRINT = d42a9218…`, `SHORT_LEDGER_FINGERPRINT = ca9b8a9b…` |
| 5 | **Assertions rewritten** | The exit-decision tests in §F categories 2, 5 and 6 |

## E.3 Why class 2 changes — the cause, named

**[INFERENCE]** Not from intrabar ordering (§B shows that is unchanged for
`CONSERVATIVE`), and not from the gap rule (the domain's matches the broker's).
It changes because **the canonical model takes a partial at 1R and promotes the
stop**, which the simulator has never done. Any position that reaches its target
passes 1R first, so its record gains a partial execution and its remainder
exits against a moved stop.

**[MEASURED]** `baseline_004` contains **zero trades**, so no baseline figure is
affected. The change is visible only in fixtures that actually open positions —
principally the two R1 regression fixtures, whose positions end `TARGET_HIT`
and therefore pass 1R.

**[DECISION]** `LONG_BARS_HELD = 24` and `SHORT_BARS_HELD = 20` should **not**
change: `bars_held` stays position-level and a partial does not end a position.
If either moves, that is a defect, not a re-pin.

---

# F. Test Migration Plan

**[MEASURED]** 44 affected test methods, by category. Categories follow the
scheme given: 1 preserve, 2 replace with a canonical-domain assertion, 3 re-pin
with provenance, 4 remove as obsolete, 5 move to the adapter/domain suite,
6 ambiguity-only rewrite, 7 time-exit per §D.

## F.1 `tests/execution/test_paper_broker.py` — 24 of 35 affected

| Class | Tests | Category |
|---|---|---|
| `EntryTimingTests` (6) | all | **Unaffected** — entry path unchanged |
| `FillCostTests` (5) | all | **Unaffected** — cost model unchanged |
| `ExitTests` | `test_stop_hit`, `test_target_hit`, `test_gap_through_stop_fills_at_the_open_not_the_stop`, `test_gap_through_target_fills_at_the_open`, `test_bar_touching_neither_level_keeps_the_position_open`, `test_entry_bar_is_evaluated`, `test_sell_stop_and_target` (7) | **5** — move to the adapter suite; the same outcomes, decided by the domain |
| `ExitTests` | `test_time_stop` | **7** — retire per §D |
| `ExitTests` | `test_end_of_data_close_is_labelled_separately` | **1** — `close_all_at_end_of_data` is a separate verb, not an `on_bar` decision |
| `ExitTests` | `test_concurrency_cap_is_enforced` | **1** — entry-side capacity |
| `AmbiguousBarTests` | `test_conservative_resolves_to_the_stop`, `test_unambiguous_bar_is_not_flagged` | **1** — still true of `resolve_intrabar` as an annotation |
| `AmbiguousBarTests` | `test_optimistic_resolves_to_the_target`, `test_the_two_policies_genuinely_disagree` | **6** — rewrite to assert the **annotation** differs while the **outcome** does not |
| `AmbiguousBarTests` | `test_tick_policy_raises_rather_than_silently_using_ohlc` | **1** — unchanged |
| `SameBarExitTests` | `test_fill_bar_covering_the_stop_closes_on_that_bar`, `…the_target…`, `…both_uses_the_existing_policy`, `…neither_leaves_the_position_open`, `…gapping_through_the_stop_exits_at_the_open` (5) | **5** — move; R1 semantics are preserved by the domain evaluating from `opened_at` |
| `SameBarExitTests` | `test_bars_held_counts_the_fill_bar`, `test_a_bar_before_the_fill_is_still_never_applied`, `test_timing_invariant_still_raises` | **1** |
| `SameBarExitTests` | `test_max_bars_held_fires_at_the_configured_count` | **7** |

## F.2 `tests/execution/test_pending_limit_orders.py` — 4 of 25 affected

**[REPO]** 21 of these concern the **pending-order fill path**, which stays in
the broker and is untouched: `IntentTests` (4), `PendingCreationTests` (3),
`SameBarFillIsImpossibleTests` (3), `ReachAndFillTests` (5),
`OrderingAndCapacityTests` (2), `ExperimentalControlTests` (4). They call
`on_bar` only to drive fills.

| Class | Tests | Category |
|---|---|---|
| `FillThenExitOnTheSameBarTests` | `test_fill_then_stop_on_the_same_bar`, `test_fill_then_target_on_the_same_bar`, `test_fill_then_both_uses_the_existing_policy` | **5** |
| `FillThenExitOnTheSameBarTests` | `test_optimistic_policy_still_reaches_the_target` | **6** |

## F.3 `tests/execution/test_broker_execution_verbs.py` — 5 of 30 affected

**[REPO]** These are the Phase 4 tests. `ExistingBehaviourUnchanged` exists
precisely to pin that Phase 4 changed nothing:
`test_a_target_bar_still_closes_the_position_as_before`,
`test_a_stop_bar_still_closes_the_position_as_before`,
`test_ambiguity_semantics_are_unchanged`,
`test_bars_held_semantics_are_unchanged`,
`test_a_position_created_without_projection_fields_behaves_as_before`.

| Tests | Category |
|---|---|
| The first two | **4** — obsolete by design; they assert the old engine still decides, which is what Phase 5A removes |
| `test_ambiguity_semantics_are_unchanged` | **6** |
| `test_bars_held_semantics_are_unchanged`, `…without_projection_fields…` | **1** |
| The other 25 | **Unaffected** — verb behaviour |

## F.4 `tests/integration/test_r1_same_bar_regression.py` — 11 affected

| Tests | Category |
|---|---|
| The two fingerprint assertions | **3** — re-pin with provenance, cause named (§E.3) |
| `bars_held` assertions | **1** — must **not** move (§E.3) |
| Outcome, exit time and exit price assertions | **2** — the record now carries a partial; assertions become canonical-record assertions |

## F.5 Files that do **not** change

**[MEASURED]** `tests/backtest/test_replay_engine.py`,
`tests/integration/test_signal_timing.py`, `tests/core/test_types.py`,
`tests/backtest/test_ledger_and_metrics.py`,
`tests/integration/test_integration_leakage.py`,
`tests/integration/test_real_strategy_replay.py` and
`tests/fixtures/integration_market.py` **never call `.on_bar(`**. My earlier
report listed them in error, from the substring match described above.
`test_ledger_and_metrics` is affected only if the `TIME_EXIT` labels are
removed, which §D declines to do.

---

# G. Phase Split — evaluated, and found unsound as proposed

The proposed split was:

> **5A:** resolve exit ownership and migrate the active PaperBroker/replay path.
> **5B:** connect the Phase 3 `TradeRecord`/fill ledger through the adapter.

**[REPO] This split does not work, for a concrete reason.** The canonical
model's **first** exit event on any position that reaches its target is the 1R
**partial**. In 5A the ledger would still record through
`trade_from_position`, which reads a single `SimulatedPosition` with one
`exit_price` and one `quantity`. The partial's realised P&L would therefore be
**silently dropped**, and 5A would ship a commit whose recorded P&L is known to
be wrong — with a re-pinned fingerprint certifying it.

**[DECISION] Two sound alternatives**, for the strategy owner to choose:

| | **G1 — one atomic phase** | **G2 — shadow then cut over** |
|---|---|---|
| 5A | Adapter, position creation, observation, domain evaluation, broker instructions, fill recording **and** `TradeRecord` ledger wiring, in one commit | Adapter built and driven in **shadow**: the domain evaluates every observation and its events are recorded, but the **broker still executes** and the ledger is unchanged |
| 5B | — | Cut over: domain events are executed, the old `on_bar` exit path is removed, the ledger switches to `TradeRecord` |
| Attribution | One commit changes behaviour; the cause is unambiguous because nothing else lands with it | 5A changes **nothing** observable — fingerprints identical, a strong proof the plumbing is right — and 5B carries the whole behaviour change |
| Risk | A large commit | Shadow code is written and then removed; two exit *decisions* exist transiently, though only one is *active* |
| Attractive because | Simplest to reason about | Produces evidence that the domain reaches the same decisions as the old engine **before** anything changes |

**[DECISION] Proposed: G2.** It is the only option that produces positive
evidence that the domain and the old engine agree on the cases where they
should agree — every unambiguous bar, and every ambiguous bar under
`CONSERVATIVE` — before any fingerprint moves. The shadow step is temporary
scaffolding, and its removal is part of 5B.

**[DECISION]** Under either option the boundary is the same: **exit ownership
and ledger representation must land together.** They cannot be separated.

---

# H. Safety — nothing else resolved

| Item | Status |
|---|---|
| I2 persistence | **[UNRESOLVED]** — untouched; §C.4's feedback path is a backtest concern |
| I3 live observation cadence | **[UNRESOLVED]** — untouched; this is backtest only |
| I7 concurrency ownership | **[UNRESOLVED]** — untouched |
| R1 reversal protection | **[UNRESOLVED]** — untouched; nothing here adds or removes a protective exit |
| R2 netting vs hedging | **[UNRESOLVED]** |
| R3 session/weekend handling | **[UNRESOLVED]** — note this is *not* the time exit; §C concerns a bar-count stop |
| R4 quantity-mismatch severity | **[UNRESOLVED]** |
| U5/R8, U6/R9 | **[UNRESOLVED]** — untouched |

**No unresolved item is used here as grounds for inventing behaviour.**

---

# I. Required Decisions

| # | Decision | Repository evidence | Proposed semantic | Spec amendment? | Implement in |
|---|---|---|---|---|---|
| **D16** | IntrabarPolicy ownership | Policy speaks only on ambiguous bars (`intrabar.py:130-190`); §11.2 fixes adverse-first independently | The **domain decides every exit**. `IntrabarPolicy` becomes an observation/ambiguity annotation: recorded, never read back to choose an exit | **No** | 5A (shadow) / 5B (cutover) |
| **D17** | `OPTIMISTIC` after migration | "Sensitivity analysis only; must never be used to produce a headline result" | Retained as an annotation. **No longer alters outcome.** The sensitivity capability is lost and the loss is recorded (§A.5) | **No** | 5B |
| **D18** | `MIDPOINT_HEURISTIC` after migration | "A heuristic, not evidence"; **no consumer** | Same as D17. Nothing observable changes, since nothing uses it | **No** | 5B |
| **D19** | `TICK_DATA` after migration | Raises today; §11.4 reserves "true sequence supersedes the policy" | **Unchanged.** Remains a distinct mode that raises rather than falling back | **No** | — |
| **D20** | `max_bars_held` ownership | Default `None`; **no caller sets it**; only two tests | **Retired** with the migration. The broker holds no closure authority | **No** | 5B |
| **D21** | Time-exit representation | `PendingState` precedent of defined-but-unproduced labels | `CLOSED_TIME` and `TIME_EXIT` **kept as labels nothing produces**, awaiting a canonical decision on D2 | **No** | 5B |
| **D22** | Fingerprint migration boundary | `decisions_fingerprint` covers only the decision stream; `ledger_fingerprint` hashes every trade field | `decisions_fingerprint` and candidate generation **must not move**; `ledger_fingerprint` and `run_fingerprint` change, caused by the 1R partial and stop promotion, re-pinned once with provenance. `baseline_004` never regenerated | **No** | 5B |
| **D23** | Test migration boundary | 44 affected methods, categorised in §F | Categories 1 preserved; 2 and 5 moved to the adapter suite; 3 re-pinned with provenance; 4 removed; 6 rewritten as annotation assertions; 7 retired per D20 | **No** | 5B |
| **D24** | Phase 5A/5B split | The first canonical exit event is a partial the current ledger cannot record (§G) | **G2:** 5A wires the adapter in shadow with **zero** observable change; 5B cuts over, removes the old exit path and switches the ledger — exit ownership and ledger land **together** | **No** | — |

**[DECISION] No canonical-specification amendment is required by any of D16–D24.**

---

# J. Verification

**Nothing was modified.** The only new file is this document. No production
Python, test, baseline, `core/trade_model.py` or canonical specification was
changed; no adapter was created.

Read-only inspection covered `execution/intrabar.py`,
`execution/paper_broker.py`, `execution/broker.py`, `backtest/ledger.py`,
`backtest/metrics.py`, `backtest/replay_engine.py`, `backtest/baseline.py`,
`core/trade_model.py`, and the affected test modules.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **844** |
| Duration | 539.7 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`455fa48`, as expected for a documentation-only phase.

---

*Design and evidence only. No code changed, no adapter built, no policy retired, no fingerprint re-pinned, no specification edited. Stopping for review.*
