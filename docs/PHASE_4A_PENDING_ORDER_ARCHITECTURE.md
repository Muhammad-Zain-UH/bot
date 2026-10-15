# LIMIT_FVG pending-order architecture

**Architecture and design only.** No production code, no strategy code, no
replay behaviour change, no backtest, no parameter selection, no optimisation,
no live trading. Nothing here is implemented.

**Specification:** `6df835d`. **Baseline:** `baseline_004`, dataset
`433b7e27…`.

**Objective:** the smallest architecture that lets L8 create a resting
`LIMIT_FVG` order **without making the strategy layer responsible for
execution**.

**Still open and deliberately not decided here:** expiry, invalidation, the
CHoCH override, cross-session survival, minimum gap size, cancellation
conditions, whether the other three AND terms remain, and the M1 bar index.

---

## 1. Current architecture

### Provenance — what is original and what is mine

This distinction matters: Phase 2A scaffolding is **not** evidence of original
design intent, and two of the findings below concern my own code.

| Layer | Files | Added by |
|---|---|---|
| Strategy / decision | `entry_engine.py`, `main_production.py` | **Original** (`c3cf4df`, 2026-07-01) |
| Risk | `risk_manager.py` | **Original** (`2186e66`, 2026-04-22) |
| Live execution | `order_execution.py`, `trade_manager.py` | **Original** (`c3cf4df`) |
| Domain types | `core/types.py` | Phase 0/1 (`893dca6`) |
| Simulated execution | `execution/{broker,paper_broker,intrabar,fills}.py` | **Phase 2A — mine** (`f39faa9`) |
| Replay / ledger / metrics | `backtest/*`, `data/replay_feed.py` | **Phase 2A — mine** (`f39faa9`) |

### Current flow

```
                    ORIGINAL                         PHASE 2A (mine)
                    ========                         ===============

  data/raw CSV ──> HistoricalDataset ──> ReplayFeed ──┐
                                                       │  bars visible at T only
                                                       ▼
  main_production.analyze_entry  <────────────── ReplayEngine._decide
      L1..L7                                           │
      L8: get_entry_trigger (entry_engine)             │  DecisionSnapshot
          core_trigger (5-way AND)                     │  + entry_signal dict
          confirmed_entry_price                        ▼
          entry_mode = "LIMIT_FVG"  ── inert ──> ReplayEngine.run
                                                       │
                                                       ├─ 1. broker.on_bar(just-closed bar)
                                                       │      resolve_intrabar -> exits
                                                       ├─ 2. decide()
                                                       └─ 3. broker.submit_market_order(
                                                              execution_bar = next bar)
                                                                  │
                                                       PaperBroker │ fills at bar OPEN
                                                                  ▼
                                                            SimulatedPosition
                                                                  │
                                                            TradeLedger -> metrics

  order_execution.py (ORIGINAL, unused by replay)
      OrderType = {BUY, SELL}          <- no LIMIT/STOP/PENDING
      create_order() treats the order as filled at signal time
```

### Facts that constrain the design

**[REPO]** `ReplayEngine.run` event order per decision instant T (close of bar N):
1. `broker.on_bar(bar N)` — advance open positions;
2. `_decide(...)` — strategy sees only bars closed at or before T;
3. `broker.submit_market_order(execution_bar = next_bar_after(T))` — fills at
   bar **N+1**'s open.

**[REPO]** `SimulatedFill.__post_init__` raises `DomainInvariantError` when
`entry_bar_time < decision_time` **or** `entry_bar_time <= decision_bar_time`.
The N+1 rule is already enforced at the domain boundary for market orders.

**[REPO]** `PaperBroker.on_bar` begins `if bar_time <= position.entry_time:
continue`. **A position is never evaluated for exits on the bar it filled on.**

**[REPO — and this is mine, Phase 2A]** The stated reason is that "the fill
happened at that bar's open and resolving the same bar's range against it would
double-count the bar". That reasoning is weak even for market fills — the
position genuinely exists for the remainder of that bar — and for a *mid-bar*
limit fill it would be **favourable to the strategy**, which contradicts the
conservative principle. See §7 case 3 and §14 risk R1.

**[REPO]** `PaperBroker.__slots__` already contains `_pending`, initialised to
`[]` and never used. **That is unused Phase 2A scaffolding of mine, not a design
signal.**

**[REPO]** `FillStatus = {FILLED, REJECTED, NO_EXECUTION_BAR}`;
`PositionState = {OPEN, CLOSED_STOP, CLOSED_TARGET, CLOSED_TIME,
CLOSED_END_OF_DATA, CLOSED_MANUAL}`. Neither has a pending concept.

---

## 2. Proposed architecture

The strategy gains **no** execution knowledge. It emits an *intent*; execution
decides whether and when it becomes a position.

```
  STRATEGY / DECISION LAYER            no knowledge of fills, bars-after-T, or brokers
  ────────────────────────
  entry_engine.get_entry_trigger
      produces ──> PendingOrderIntent        (pure value object, core/types.py)
                     side, limit_price, stop_loss, take_profit,
                     formation_bar_time, decision_time, zone_low/high, metadata
                        │
                        ▼
  ReplayEngine  ── passes intent, never interprets it ──┐
                                                         ▼
  EXECUTION LAYER                                  Broker protocol
  ───────────────                                  submit_limit_order(intent)
                                                         │
                                                         ▼
                                                   PendingOrder          <- owns state
                                                   (execution/broker.py)
                                                         │
                          per bar, in a defined order:   │
                          A. expire / invalidate / cancel│
                          B. attempt fill  ──────────────┤
                          C. exits on open positions     │
                                                         ▼
                                                   SimulatedPosition
                                                         │
                                                   TradeLedger  (formation -> fill provenance)
                                                         │
                                                   BacktestMetrics (+ pending counters)
```

The only new coupling is **one direction**: decision → execution, via an inert
value object. Execution never calls back into the strategy.

---

## 3. Responsibilities — current vs proposed

| Concern | Current owner | Proposed owner | Change |
|---|---|---|---|
| Detect FVG | `entry_engine.detect_fvg` | unchanged | — |
| Decide a setup exists | `entry_engine.get_entry_trigger` | unchanged | — |
| Choose the limit level | `entry_engine` (`fvg.midpoint`) | unchanged — it is a *description*, not an execution act | — |
| Express "place a limit at X" | **does not exist** — the signal is treated as an immediate entry | `PendingOrderIntent` | **New** |
| Decide *whether* an order rests | implicit | Execution (`Broker.submit_limit_order`) | **Moved** |
| Decide *when* it fills | n/a — market fill at next open | Execution (`PendingOrder` + `resolve_intrabar`) | **New** |
| Enforce N+1 timing | `SimulatedFill.__post_init__` (market only) | `PendingOrder` construction + fill guard | **Extended** |
| Hold state between bars | `PaperBroker._open` | `PaperBroker._pending` + `_open` | **Extended** |
| Expire / invalidate / cancel | does not exist | Execution, driven by rules the owner has yet to set | **New** |
| Resolve intrabar ambiguity | `resolve_intrabar` (exits) | unchanged for exits; new entry-side resolution alongside | **Extended** |
| Record provenance | `TradeLedger` (decision → fill) | + formation → pending → fill | **Extended** |
| Count ambiguity | `ambiguous_exits` | + entry-side counters | **Extended** |
| Position sizing | `risk_manager` (bypassed; fixed 0.01) | unchanged | — |
| Live order placement | `order_execution.py` (BUY/SELL only) | unchanged now; §10 for the eventual mapping | — |

---

## 4. Pending-order state machine

Existing terminology is reused where it exists (`FillStatus`, `PositionState`).
`FORMED` is distinct from `PENDING` because §0.1 of the specification requires
formation and order creation to be separable events even though, under the
current design, they occur at the same instant.

```
        [decision bar N]
              │
              ▼
          FORMED ──────── trigger fails ────────▶ (no order; nothing recorded)
              │
              │ Broker.submit_limit_order(intent)
              ▼
          PENDING ◀──────────────┐
              │                  │ survives bar close
              │                  └──────────────┐
              ├── fill condition on bar ≥ N+1 ──┴──▶ FILLED ──▶ OPEN ──▶ CLOSED_*
              ├── expiry rule            ───────────▶ EXPIRED      (terminal)
              ├── invalidation rule      ───────────▶ INVALIDATED  (terminal)
              └── cancellation rule      ───────────▶ CANCELLED    (terminal)
```

| State | Created by | Owned by | Transitioned by | Required data | Transition established by | Persisted | On replay restart |
|---|---|---|---|---|---|---|---|
| **FORMED** | Strategy (`entry_engine`) | Decision layer, transiently | — (not a stored state) | side, limit, SL, TP, zone bounds, `formation_bar_time`, `decision_time` | close of bar **N** | No — it is the intent, recorded in the decision snapshot | Recomputed from the same bars; deterministic |
| **PENDING** | `Broker.submit_limit_order` | **Execution** (`PaperBroker._pending`) | Execution only | the intent + a monotonic `sequence` for deterministic ordering | accepted at decision instant **T** | In the ledger as a pending record | Replay is deterministic and stateless across runs; no resume semantics exist and none are proposed |
| **FILLED** | Execution | Execution | Execution | fill bar, fill price, ambiguity flag | the **fill bar** (≥ N+1) | Ledger | — |
| **OPEN** | Execution | Execution (`_open`) | Execution | existing `SimulatedPosition` | fill bar | Ledger on close | — |
| **CLOSED_\*** | Execution | Execution (`_closed`) | Execution | existing fields | exit bar | Ledger | — |
| **EXPIRED** | Execution | Execution | Execution | expiry rule **[UNRESOLVED]** | the bar the rule fires on | Ledger (terminal, no trade) | — |
| **INVALIDATED** | Execution | Execution | Execution | invalidation rule **[UNRESOLVED]** | the bar the rule fires on | Ledger (terminal, no trade) | — |
| **CANCELLED** | Execution | Execution | Execution | cancellation rule **[UNRESOLVED]** | the bar the rule fires on | Ledger (terminal, no trade) | — |

**Replay restart.** The replay is a pure function of dataset + code; it does not
checkpoint and cannot resume mid-run. Pending state therefore lives only in
memory for the duration of a run. **No persistence-across-restart is proposed**,
and adding it would create a resume path that could diverge from a clean run —
which the determinism guarantee exists to prevent.

---

## 5. Domain objects

### `PendingOrderIntent` — new, `core/types.py`

A frozen value object. **Knows nothing about bars, brokers, fills or MT5.**

| Field | Purpose |
|---|---|
| `side` | `Side.BUY` / `Side.SELL` |
| `limit_price` | where the order rests (the FVG midpoint, per spec §0) |
| `stop_loss`, `take_profit` | levels the strategy nominates |
| `formation_bar_time` | open time of bar **N** — the invariant anchor |
| `decision_time` | replay instant the intent was produced |
| `zone_low`, `zone_high` | the FVG, carried for invalidation once that rule exists |
| `metadata` | strategy context for the ledger |

Validation at construction (the same style as existing `StopLoss`/`TakeProfit`
in `core/types.py`): the stop must sit on the correct side of `limit_price`, and
`limit_price` must lie within `[zone_low, zone_high]` **if** the CHoCH-override
decision keeps it there — that check is **[UNRESOLVED]** and must not be
hard-coded until decided.

### `PendingOrder` — new, `execution/broker.py`

The execution-side entity that owns lifecycle state: the intent, a `PendingState`
enum, a monotonic `sequence`, and the terminal outcome with its bar and reason.

**It enforces the temporal invariant itself.** A `fill(bar_time, …)` method
raises `DomainInvariantError` when `bar_time <= intent.formation_bar_time`,
mirroring `SimulatedFill.__post_init__`. The guard lives on the object, not in
the caller — §9 of the brief requires exactly this.

### `PendingState` — new enum

`PENDING`, `FILLED`, `EXPIRED`, `INVALIDATED`, `CANCELLED`. Kept separate from
`FillStatus` (an outcome of one submission attempt) and `PositionState` (a
position's life), because conflating them would overload two existing enums that
other code already switches on.

### Extended: `Broker` protocol

Add `submit_limit_order(intent) -> PendingOrder`. `submit_market_order` is
untouched, so every existing caller and test is unaffected.

---

## 6. Event ordering

Per decision instant **T** (close of bar **N**). Steps 1–3 are the existing
order; **A/B are new and inserted inside step 1**, before exits.

```
1. broker.on_bar(bar N):
     A. pending maintenance   — expire / invalidate / cancel   [rules UNRESOLVED]
     B. pending fill attempt  — bars ≥ N+1 only (bar N is excluded by the guard)
     C. exits on open positions (existing resolve_intrabar path)
2. decide()  — strategy sees only bars closed at or before T
3. submit_market_order (existing) and/or submit_limit_order (new intent)
```

**Why A before B.** An order that the rules have already killed must not fill on
the same bar; otherwise expiry would depend on evaluation order.

**Why B before C.** A position filled on this bar must be eligible for its own
exit on this bar (§7 case 3). Running C first would defer that to the next bar,
which is the strategy-favourable reading.

**Why the fill attempt cannot see bar N.** A pending order created at T is
submitted in step 3, *after* step 1 has already run for bar N. The earliest
`on_bar` it can experience is bar N+1's. The `PendingOrder.fill` guard enforces
this independently, so the ordering and the invariant agree rather than one
relying on the other.

---

## 7. Intrabar ambiguity

The existing `resolve_intrabar` handles **exits** and must not be altered. Entry
resolution is a *separate* concern evaluated before it.

| # | Case | Resolution | Ambiguous? |
|---|---|---|---|
| 1 | Limit reached, no position exists | Fill at the limit price. Gap case: if the bar **opens** beyond the limit, fill at the open — the existing stop-gap rule's mirror (`on_bar` already fills a gapped stop at the open) | No |
| 2 | Limit reached **and** a different position's exit is reachable on the same bar | Independent objects — **unless capacity binds**. If `max_open_positions` is full and the exit would free the slot, the outcome depends on ordering. §6 puts B before C, so the slot is **not** yet free and the fill is denied | **Yes — new class**, see below |
| 3 | Limit fills and its **own** new stop is reachable on the same bar | **Forced, not a policy choice.** A BUY limit rests below market with its stop below that; to reach the stop price the bar must first pass the limit. So fill-then-stop is the only path consistent with the bar. Mirrored for SELL | No — but only if the position is evaluated on its fill bar (R1) |
| 4 | Several pending orders reachable on the same bar | Deterministic order by the monotonic `sequence`. Only observable when capacity binds | **Yes — same class as case 2** |
| 5 | Limit fills and the **target** is reachable on the same bar | Genuinely ambiguous: price may have run to the target first and only later come back to the limit. Conservative reading — **filled, target not credited on that bar** | **Yes — new class** |
| 6 | Representation | A `PendingResolution` value object mirroring `IntrabarResolution`: `filled`, `was_ambiguous`, `ambiguity_class`, `policy`, `reason`. Reasons carry the `AMBIGUOUS:` prefix already used, so existing log conventions hold | — |
| 7 | Reusable counters | `BacktestMetrics.ambiguous_exits` / `ambiguous_exit_fraction`; `SimulatedTrade.was_ambiguous_exit`; the `IntrabarPolicy` enum itself | — |
| 8 | New counters required | `ambiguous_entries`, `ambiguous_entry_fraction`; `pending_created / filled / expired / invalidated / cancelled`; `fills_denied_by_capacity` | — |

**Is the existing policy sufficient?** For exits, yes — untouched. For entries,
**no**: cases 2, 4 and 5 are ambiguity classes `resolve_intrabar` was never
designed to express, because it assumes exactly two competing levels on an
already-open position. The required extension is **architectural, not a new
policy**: a parallel entry-side resolver that reuses `IntrabarPolicy` as its
policy input and reports through the same ambiguity-counting mechanism. Adding a
new *policy* value is explicitly not proposed.

**One principle does not transfer cleanly, and I am flagging it rather than
resolving it.** "Never resolve in the strategy's favour" is unambiguous for
exits, where one branch is always worse. For case 2/4 it is not: denying a fill
avoids a potential loss *and* forgoes a potential gain. §6's ordering gives a
deterministic answer, but it is a determinism choice, not a conservatism one, and
the document should not pretend otherwise.

---

## 8. Replay-state ownership

| Requirement | Where it is satisfied |
|---|---|
| Pending state between M5 bars | `PaperBroker._pending` — already declared, currently unused |
| Deterministic iteration | Orders carry a monotonic `sequence`; the list is never reordered and is iterated in sequence order |
| No look-ahead | Fills are attempted only inside `on_bar`, which receives one closed bar; the `PendingOrder.fill` guard rejects any bar at or before formation |
| Event ordering | §6, fixed and documented |
| Multiple pending orders | Supported; interaction with `max_open_positions` is case 2/4 |
| Cancellation / expiry / invalidation | Phase A of `on_bar`; **rules [UNRESOLVED]** |
| Exact ledger attribution | §9 |
| Deterministic fingerprints | §11 |

Pending orders live **only** in the broker. The replay engine holds none, the
strategy holds none, and no module-level or global state is introduced — the
Phase 0/1 rule against hidden global state continues to hold.

---

## 9. Persistence and ledger

**[REPO]** `TradeLedger` records `SimulatedTrade`s built by
`trade_from_position`, plus a separate rejections list, and computes a SHA-256
`fingerprint()`.

Required extensions:

- **Pending provenance on a filled trade:** `formation_bar_time`,
  `pending_created_time`, `limit_price`, `bars_pending`, `fill_was_ambiguous`,
  `ambiguity_class`. The existing timing-provenance fields stay as they are.
- **Terminal non-fills:** expired / invalidated / cancelled orders produce **no
  trade** but must still be recorded, otherwise the funnel loses them. The
  existing rejections list is the natural home, or a parallel pending log.
- **`core/signal_log.py`:** pending state columns imply a `SIGNAL_LOG_SCHEMA_VERSION`
  bump; the existing `rotate_mismatched_log` already handles migration.

**A trade's realised R must continue to be computed from the actual fill**, which
for a limit is the limit price (or the gapped open), **not** the strategy's
nominated price. This is the Q1 defect and the design must not reintroduce it.

---

## 10. Live-execution boundary

**Live trading remains disabled.** `core.safety.LIVE_TRADING_ENABLED` is a
literal `False`; nothing here changes that, and no MT5 support is implemented.

The mapping exists conceptually because `PendingOrderIntent` is broker-agnostic:

| Concept | Simulation | Eventual live equivalent |
|---|---|---|
| `PendingOrderIntent` | `PaperBroker.submit_limit_order` | An adapter implementing the same `Broker` method |
| Resting order | `PendingOrder` in `_pending` | `TRADE_ACTION_PENDING` + `ORDER_TYPE_BUY_LIMIT` / `SELL_LIMIT` |
| Fill | `resolve_intrabar` on a bar | The broker's own execution |
| Expiry | Phase A rule | `ORDER_TIME_SPECIFIED` / manual delete |
| Invalidation / cancellation | Phase A rule | `TRADE_ACTION_REMOVE` |

**[REPO]** `order_execution.OrderType` has only `BUY` and `SELL`, so a live path
would need LIMIT members — noted, not proposed.

The strategy layer never learns any of this. It emits an intent; whichever
`Broker` implementation is attached decides the rest. That is the whole point of
routing through the protocol rather than letting `entry_engine` place orders.

---

## 11. Determinism requirements

| Requirement | Mechanism |
|---|---|
| Stable ordering | Monotonic `sequence` per pending order; no set/dict iteration over orders |
| No wall-clock | Pending state derives only from bar data and the frozen replay clock |
| Reproducible fingerprints | `decisions_fingerprint` is unaffected (it covers decisions, not fills). `ledger_fingerprint` gains pending provenance and **will change once orders actually fill** — expected at step 4, not before |
| Ambiguity visible | Entry ambiguity counted and surfaced, per the `intrabar` module's stated principle |
| No float-order sensitivity | Fill comparisons use the same inclusive containment tests as `resolve_intrabar`; no new tolerance is introduced |

---

## 12. Backward compatibility — how steps 1–3 stay non-behavioural

The guarantee is **structural**, not a matter of care:

1. **Nothing constructs a `PendingOrderIntent` until step 4.** `entry_engine` is
   untouched in steps 1–3, so `_pending` is always empty.
2. **Phase A and B of `on_bar` are no-ops on an empty list.** Iterating nothing
   cannot change exits, positions, the ledger or any fingerprint.
3. **`submit_market_order` is not modified**, so the existing market path is
   bit-for-bit unchanged.
4. **New enums and fields are additive.** Existing `FillStatus` and
   `PositionState` members keep their values; ledger fields added with defaults
   leave `trade_from_position` output identical when no pending order exists.

**Pass criterion for each of steps 1–3:** a full replay reproduces
`baseline_004` **byte-identically** — `decisions.jsonl`, `decisions_fingerprint`,
`ledger_fingerprint`, `run_fingerprint` and every summary artifact. Since that
baseline produced **zero trades**, any pending-order code that activated
prematurely would show up immediately as a non-empty ledger.

**A guard worth adding in step 1:** assert that the pending list is empty
whenever no `submit_limit_order` has been called, so "nothing activated early" is
enforced rather than assumed.

Existing tests remain valid because no existing signature changes. New tests
cover the new objects.

---

## 13. Files and functions likely to change later

**Steps 1–3 (non-behavioural)**

| File | Change |
|---|---|
| `core/types.py` | add `PendingOrderIntent` |
| `execution/broker.py` | add `PendingState`, `PendingOrder`, `PendingResolution`; extend `Broker` protocol |
| `execution/paper_broker.py` | `submit_limit_order`; phases A and B inside `on_bar`; use `_pending` |
| `execution/intrabar.py` | entry-side resolver reusing `IntrabarPolicy` — **no new policy value** |
| `backtest/ledger.py` | pending provenance on `SimulatedTrade`; terminal non-fill records |
| `backtest/metrics.py` | entry-ambiguity and pending-lifecycle counters |
| `backtest/replay_engine.py` | pass an intent through when one exists; no interpretation |
| `core/signal_log.py` | pending columns; schema version bump |

**Step 4 (behavioural — the first expected divergence)**

| File | Change |
|---|---|
| `entry_engine.py::_evaluate_momentum_entry` | remove `price_in_fvg`; four-way `core_trigger`; emit an intent |
| `entry_engine.py::detect_fvg` | stop returning bounds when `fvg_found` is false |
| `entry_engine.py::get_entry_trigger` | return the intent alongside the existing payload |
| `main_production.py` L8 (≈983–1010) | surface the intent instead of an immediate `ENTRY_SIGNAL` |

**Not changed:** `poi_engine.py`, `risk_manager.py`, `order_execution.py`,
`trade_manager.py`, and L1–L7 throughout.

---

## 14. Risks and unresolved dependencies

**R1 — the fill-bar exclusion is a blocking architectural dependency.**
`on_bar` skips any position where `bar_time <= entry_time`, so a position is
never evaluated for exits on its fill bar. For a mid-bar limit fill this is
**favourable to the strategy** and defeats §7 case 3. Either the exclusion is
narrowed to market fills, or limit fills must be evaluated on their own fill bar.
**This is my Phase 2A code and my reasoning was weak** — the comment claims
double-counting, but the position genuinely exists for the rest of the bar.
Changing it alters market-order behaviour too and would break baseline
equivalence, so it must be its own measured step, not folded into step 4.

**R2 — entry ambiguity has no conservative default.** For exits, one branch is
always worse. For cases 2 and 4 it is not (§7). §6's ordering is deterministic
but not conservative, and this should be stated in results rather than glossed.

**R3 — capacity coupling.** `max_open_positions = 3` becomes load-bearing once
several orders can rest simultaneously. Denied fills must be counted, or the
funnel will silently under-report reachable entries.

**R4 — the zero-trade baseline is a weak regression test for steps 1–3.** It
proves nothing activated early; it cannot prove the new code is *correct*,
because no trade exercises it. Unit and fixture tests must carry that burden —
the Phase 2A.1 fixtures are the natural vehicle.

**R5 — the RR tautology becomes reachable.** E9/E10 bind the moment an entry can
fire in a `tp_ratio < 2.0` regime. Sequenced last, but it will bind and should
not surprise anyone when it does.

**R6 — four strategy-owner decisions block step 4**, not steps 1–3: invalidation,
expiry, the CHoCH override, and cross-session survival. Phase A of `on_bar`
cannot be finished without the first two.

**R7 — schema migration.** A `signal_log` version bump interacts with
`rotate_mismatched_log`; the existing rotation path should be exercised rather
than assumed.

---

*Architecture design complete. No code written, no behaviour changed, no decisions taken beyond those already recorded in the specification. Stopping for review.*
