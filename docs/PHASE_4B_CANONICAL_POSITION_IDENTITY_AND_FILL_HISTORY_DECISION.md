# Phase 4B — Canonical Position Identity and Fill History

**Design and evidence only.** No production Python, test, baseline,
`core/trade_model.py` or canonical specification is changed. No adapter, no
`PaperBroker` change, no ledger change. `trade_manager` is not retired.
`baseline_004` remains **FROZEN**. R1–R4, U5/R8 and U6/R9 are untouched.

**The three domain-level issues I1 exposed:**

1. `TradeState` has no identity field.
2. `TradeState` stores one `closure_fill_price`, so a partial execution price is
   not represented in the domain.
3. `SimulatedPosition.risk_distance` reads the **current** stop, which can
   invalidate `risk_amount` and `r_multiple` once a stop promotion occurs.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `54899ea` |
| **[MEASURED]** | Established by running existing code read-only |
| **[DECISION]** | A design proposal for review — not implemented |
| **[UNRESOLVED]** | Cannot be settled from existing evidence |

---

# A. Position Identity

## A.1 How identity works today

| Layer | Identifier | Minted where | Reproducible in replay? | Kind |
|---|---|---|---|---|
| **`core.trade_model.TradeState`** | **none** | — | — | **Absent** |
| `SimulatedPosition` | `position_id = f"SIM-{counter:06d}"` | `paper_broker._open_position` | **Yes** — a run-scoped counter | Local |
| `SimulatedTrade` | `trade_id = position.position_id` | `trade_from_position` | Yes, aliased | Local |
| `SimulatedFill` | **none** | — | — | **Absent** |
| `PendingOrder` | `order_id`, plus `sequence` for deterministic ordering | `submit_limit_order` | Yes | Local order |
| `order_execution` | `order_id = f"XAUUSD_{datetime.now():%Y%m%d_%H%M%S}_{counter}"` | `generate_order_id` | **No — wall clock** | Local order |
| `order_execution` | `mt5_order_id = random.randint(1000000, 9999999)` in the simulation branch | `execute_order` | **No — unseeded random** | Fabricated broker id |
| `main_production` trade dict | `trade_id = order_id`; `manage_positions` mints `f"{trade_id}_auto_{int(time.time())}"` when `order_id` is missing | `:1173` | **No — wall clock** | Local |
| `main.py` trade dict | `trade_id = f"XAUUSD_{datetime.now():%Y%m%d_%H%M%S}"` | `:899` | **No — wall clock, and collides within one second** | Local |
| Live MT5 | `pos.ticket` | broker | n/a | Broker position id |

**[REPO]** Two production identity schemes are wall-clock based and one broker
id is `random.randint`, so **no production identifier is reproducible**. The
backtest's `SIM-%06d` is the only reproducible one.

## A.2 The vocabulary already exists in `core.types`, unused

**[REPO]** The repository already distinguishes most of the identities this
section asks about — in validated, tested types that **no production module
imports**:

| Type · field | Documented meaning | Used in production? |
|---|---|---|
| `OrderRequest.client_order_id` | "Caller-side identifier for reconciliation" | **No** |
| `OrderResult.broker_order_id` | "Broker-assigned identifier, when one was issued" | **No** |
| `Position.position_id` | "**Broker ticket or local identifier**" | **No** |
| `PositionStatus` | `PENDING`, `OPEN`, **`PARTIALLY_CLOSED`**, `CLOSED` | **No** |
| `Position.broker_verified` | "Whether this snapshot was confirmed against the broker. Defaults to `False` — unverified until proven otherwise" | **No** |

**[REPO] Contradiction 1 — identity is conflated where it is defined.**
`Position.position_id` is documented as "broker ticket **or** local identifier".
That is precisely the distinction this section must draw, and the type declines
to draw it.

**[REPO] Contradiction 2 — two `core` vocabularies disagree about partial
closure.** `core.types.PositionStatus` has `PARTIALLY_CLOSED`, while the
canonical specification §8.2 states there is **no** distinct partially-closed
position state: a partially closed position is `OPEN` with fewer steps. Both
live in `core`. They can coexist only if `Position` is understood as the
**broker's snapshot** and `TradeState` as the **canonical machine** — which is
what `Position`'s own docstring says ("The broker is the authority on positions.
This type is a snapshot to be reconciled against `positions_get()`, never a
substitute for it"). The mapping must be stated explicitly at integration, not
assumed.

## A.3 The four identities, named

| # | Identity | What it names | Exists today? |
|---|---|---|---|
| 1 | **Canonical `position_id`** | The canonical position, from entry through partial to final close | **No** |
| 2 | **Broker order / request id** | One submission attempt. `client_order_id` outbound, `broker_order_id` inbound | **Types only**, unused |
| 3 | **Broker position / deal id** | The broker's own position — MT5 `ticket` | Only as `pos.ticket` in the two shutdown paths |
| 4 | **Execution / fill id** | One execution against a position | **No — nowhere in the repository** |

## A.4 Where canonical identity should be generated

| Option | Assessment | Evidence |
|---|---|---|
| **(a) Generated when the canonical position opens** | Viable. Identity exists exactly when the thing it names exists — at the fill (spec 13) | `SIM-%06d` already does this and is reproducible |
| **(b) Supplied by the execution layer (broker id)** | **Not viable as the canonical id.** The broker ticket is unknown until the fill is *confirmed*, so the position would be identity-less during its first evaluation; and on a netting account the broker may merge positions, changing the ticket — R2, unresolved | `Position` docstring; R2 |
| **(c) Separate domain and broker identifiers, mapped** | Viable, and matches the vocabulary already present | `client_order_id` vs `broker_order_id` are already two fields |

**[DECISION]** Propose **(a) combined with (c)**: the canonical `position_id` is
minted by the adapter when the canonical position is created — at the fill — and
is reproducible in replay; broker identifiers are recorded **alongside** it, never
as a substitute. This preserves identity across entry → partial fill → remaining
position → final close, because the id belongs to the position, not to any one
execution or broker object.

**[DECISION]** In this phase `TradeState` stays id-free and the adapter owns the
`position_id → TradeState` mapping, because adding a field to `TradeState` would
require changing `core/trade_model.py` and the specification, both of which are
prohibited here. **Recorded as a recommended follow-up:** an embedded id would
let the domain name the position in its own anomalies and errors — today
`UnresolvedCanonicalDecisionError` cannot say *which* position it refused — and
would make a persisted state self-describing (§F). That is a specification
amendment, proposed, not taken.

---

# B. Fill History

## B.1 What the domain actually decides with

**[REPO]** Reading `evaluate` and `apply_broker_result`, every decision uses:
`lifecycle`, `pending_close_reason`, `last_evaluated_time`, `opened_at`,
geometry (`entry_price`, `r`, `m1r`, `m2r`, `target`), `milestones_consumed`,
`steps_at_entry`, `steps_remaining`, `stop_state_intended`,
`stop_state_confirmed`, `confirmed_stop_price` and `stop_modify_was_rejected`.

**No past fill price is read by any decision.** The domain needs prices only to
*report* the terminal one.

## B.2 The three representations

| # | Representation | State reconstruction | Restart / persistence | Idempotency | Broker result handling | P&L | Quantity reconciliation | Auditability | Backtest determinism |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Fill history inside `TradeState`** | Complete from one object | One object to persist, but unbounded growth | Unchanged | Unchanged | Computable in-domain | Computable in-domain | Complete | State equality becomes history-sensitive — **[REPO]** the contract asserts `first.state == second.state` for a repeated evaluation, which still holds, but two positions with identical decision state and different fill histories would no longer compare equal |
| 2 | **Terminal info in the domain + immutable external fill ledger** | Domain state plus ledger | Snapshot + append-only fills | Unchanged | Unchanged | **Ledger owns it** | Ledger is authoritative, domain holds `steps_remaining` | Complete, in one append-only place | Domain state stays minimal and comparable |
| 3 | **A compact realised accumulator in the domain** (closed steps + weighted average price) | Partial — individual fills lost | Small | Unchanged | Unchanged | Approximate; weighted average discards per-fill timing | Duplicates the ledger | **Incomplete** | Same as 2 |

**[DECISION]** Propose **representation 2**. Evidence:

- **[REPO]** The domain reads no historical fill price, so holding one buys no
  decision quality (§B.1).
- **[REPO]** Option 3 would make realised P&L computable in two places — the
  domain's accumulator and the ledger — which violates the single-owner rule in
  §E, and loses per-fill timing that the ledger needs anyway.
- **[REPO]** Option 1 is defensible but grows the state object without a decision
  that needs it, and makes `TradeState` equality depend on history rather than on
  the situation. The canonical contract compares states directly.
- **[REPO]** Spec 16 already routes every execution outcome through
  `apply_broker_result`, so the adapter necessarily sees each fill. Writing it to
  a ledger at that moment costs nothing and loses nothing.

**Consequence, stated plainly:** the partial execution price lives in the **fill
ledger**, not in the domain. `TradeState.closure_fill_price` keeps its present
meaning — the **final** fill — and is not asked to carry a history it was not
designed for.

---

# C. Canonical Risk Semantics

## C.1 Every current use

| Site | Expression | Basis |
|---|---|---|
| `execution/broker.py:271` | `SimulatedPosition.risk_distance = abs(entry_price - stop_loss)` | **Current** stop — the field is mutable in principle |
| `backtest/ledger.py:233` | `price_risk = position.risk_distance` | Inherits the above |
| `backtest/ledger.py:234` | `risk_amount = money_for_price_distance(price_risk, position.volume)` | Inherits |
| `backtest/ledger.py:235` | `r_multiple = net_pnl / risk_amount if risk_amount > 0.0 else None` | Inherits |
| `backtest/metrics.py:204,206` | aggregates `r_multiple` | Inherits |
| `backtest/baseline.py:309,550-557` | `realised_r` vs nominal `tp_ratio` | Inherits |
| `core.types.StopLoss.risk_distance` | `abs(entry_price - price)` on a **frozen, validated** object | **Entry-time, immutable** |
| `core.types.Signal.risk_distance` | delegates to `StopLoss` | Immutable |
| `core.trade_model.TradeState.r` | `abs(entry_price - original_stop_price)`, frozen at creation | **Entry-time, immutable** |
| `entry_engine.calculate_entry_levels` | `take_profit = entry ± risk_distance * tp_ratio` | Entry-time |

## C.2 Classification

| Value | Class |
|---|---|
| `entry_price`, `original_stop_price`, `r`, `m1r`, `m2r`, `target`, `tp_ratio`, `steps_at_entry` | **1 — immutable entry-time facts** |
| `stop_state_intended`, `stop_state_confirmed`, `confirmed_stop_price`, `steps_remaining`, `milestones_consumed`, `pending_close_reason`, `stop_modify_was_rejected` | **2 — mutable management state** |
| `price_risk`, `risk_amount`, `gross_pnl`, `net_pnl`, `r_multiple`, `bars_held`, ambiguity counts | **3 — derived reporting metrics** |

## C.3 Can the projection compute risk after a stop promotion?

**No. [REPO] Contradiction 3, and it is severe.**

`SimulatedPosition.risk_distance` reads `self.stop_loss`. Under the canonical
ladder the stop is promoted to **breakeven = entry_price** at 1R. Then:

```
risk_distance = abs(entry_price - stop_loss) = abs(entry - entry) = 0.0
risk_amount   = money_for_price_distance(0.0, volume) = 0.0
r_multiple    = None            # the `if risk_amount > 0.0` guard
```

**[REPO]** So **every position that reaches 1R would report `r_multiple = None`**,
and `metrics.py` filters `None` out of `r_values` and `r_series` — the R
distribution would silently be computed over only those positions that never
reached 1R. Nothing raises; the statistic just quietly describes a biased subset.

It is latent today because nothing moves a stop. It becomes live on the first
day the ladder is wired.

**[DECISION] What must become immutable or separately stored** — not
implemented:

| Requirement | Why |
|---|---|
| The projection must carry the **original** stop, or `R` itself, as an immutable field distinct from the current stop | `risk_distance` must not be derived from a value that management mutates |
| `price_risk` and `risk_amount` must be computed from the **original** R and the **original** quantity | Spec 4.1: R is frozen and stop movement never redefines it |
| The current stop must remain visible separately | It is needed to know where protection sits (spec 7.3) |

---

# D. Partial-Exit Accounting

**Conceptual only. No code.** BUY 1.00 lot at 2450.00, original stop 2420.00,
`tp_ratio` 3.0. **[REPO]** `volume_step = 0.01`, so 1.00 lot = **100 steps** and
the 1R partial is `floor(100/2) = 50` steps = **0.50 lots**.

```
R = |2450.00 - 2420.00| = 30.00      M1R = 2480.00    TARGET = 2540.00
```

| Concept | Value / definition |
|---|---|
| Original quantity | 100 steps (1.00 lot), immutable |
| Remaining quantity | 100 → 50 after the partial is **confirmed** → 0 after the final close is confirmed |
| Cumulative closed quantity | 0 → 50 → 100 steps. Always `original − remaining` |
| Fill 1 quantity / price / time | Entry: 100 steps, the actual entry fill price, the fill bar's time |
| Fill 2 quantity / price / time | Partial exit: 50 steps, the broker's executed price, the observation that confirmed it. Cause: `M1R` |
| Fill 3 quantity / price / time | Final exit: 50 steps, the broker's executed price, its observation. Cause: `TARGET` or `STOP` |
| Realised P&L per fill | `(exit_price − entry_price) × side.sign × money_per_price_unit(fill_quantity)`, minus that fill's share of costs |
| Total realised P&L | The sum over exit fills. Not recomputed from an average price |
| Final trade P&L | The same sum, recorded once on the position record when closure is confirmed |
| R multiple | `total_net_pnl / risk_amount`, where `risk_amount = money_for_price_distance(R, original_quantity)` — **original** R, **original** quantity, so the figure stays size-independent and comparable, exactly as `ledger.py:26` describes it |

**[DECISION]** The R multiple is a property of the **position**, not of any
fill. A per-fill R would divide by a risk that fill never carried: the 0.50-lot
remainder never risked 1.00 lot.

---

# E. Source of Truth

**[DECISION]** One authoritative owner per fact. "Derived" means computed from
the owner, never stored competitively.

| Concept | Canonical domain (`TradeState`) | Fill ledger | Position projection (`SimulatedPosition`/`Position`) | Broker |
|---|---|---|---|---|
| Position identity | — (adapter-owned map, §A.4) | references it | references it | — |
| Broker identity | — | records it per fill | records it | **Owner** |
| Original quantity | **Owner** (`steps_at_entry`) | — | derived | — |
| Remaining quantity | **Owner** (`steps_remaining`) | derivable as a cross-check | derived | reconciles against it (§F) |
| Original stop | **Owner** (`original_stop_price`) | — | must store it immutably (§C.3) | — |
| Current stop | **Owner of intent**; broker owns what is live | — | derived | **Owner of fact** (`stop_state_confirmed` mirrors it) |
| Original risk (R) | **Owner** (`r`) | — | derived or copied immutably | — |
| Fill price | terminal one only (`closure_fill_price`) | **Owner** | — | reports it |
| Fill quantity | — | **Owner** | — | reports it |
| Fill timestamp | — | **Owner** | — | reports it |
| Partial-close reason | milestone that caused it (`milestones_consumed`) | **Owner** of the recorded cause | — | — |
| Final-close reason | **Owner** (`closure_reason`) | records it | derived | — |
| Realised P&L | — | **Owner** (per fill), summed onto the trade record | — | — |
| `r_multiple` | — | — | — | — → **Owner: the aggregate trade record**, from domain R and total P&L |
| Ambiguity | **Owner** per evaluation (`EvaluationResult.ambiguous`) | records it per fill | — | — |
| `bars_held` | — | — | **Owner** (position lifecycle) | — |

**[REPO]** Two competing owners exist **today** and would persist if nothing
changed: `risk_distance` is computed by the projection from a mutable stop while
`r` is owned by the domain (§C.3), and `steps_remaining` in the domain would
compete with `volume` in the projection. Both are resolved by the table above.

---

# F. Restart / Rehydration

**Minimum information to reconstruct a `TradeState`:**

| Field | Recoverable from fills alone? | Recoverable from broker alone? |
|---|---|---|
| `entry_price`, `original_stop_price`, `r`, levels, `tp_ratio` | Entry price yes; **stop and `tp_ratio` no** | Stop yes (if registered); **R and `tp_ratio` no** |
| `steps_at_entry`, `steps_remaining` | **Yes** — entry minus exits | Remaining yes; original **no** |
| `milestones_consumed` | **No** — a consumed milestone whose partial was zero steps or rejected leaves **no fill** | **No** |
| `stop_state_confirmed`, `confirmed_stop_price` | **No** | Price yes; which *state* it represents **no** |
| `stop_modify_was_rejected` | **No** — a rejection produces no fill | **No** |
| `pending_close_reason` | **No** | **No** |
| `last_evaluated_time` | **No** | **No** |

**[DECISION] Answer: an immutable position snapshot plus fill history, then
reconciled against broker state.** Specifically:

- **Fill history alone is insufficient.** Milestone consumption, stop state and
  rejection flags leave no fill — most sharply the one-step position, where the
  1R milestone is consumed and **no partial is sent at all** (spec 5.2).
- **Broker state alone is insufficient.** The broker knows quantity and the live
  stop; it does not know R, `tp_ratio`, which milestones fired, or that a
  promotion was refused.
- **Snapshot alone is insufficient for audit**, though sufficient for decisions.
  The fill history is what makes P&L and quantity independently checkable.

**[REPO]** The repository already insists on the reconciliation step:
`core.types.Position.broker_verified` defaults to `False`, and its docstring
records the motivating failure — "the Phase 1 audit found local state diverging
permanently from the broker, with two fabricated positions surviving every
restart". A restored `TradeState` must therefore be treated as unverified until
checked against the broker, exactly as that type prescribes.

**[UNRESOLVED]** The serialisation format — enums, `frozenset`, aware datetimes
— remains I2 and is not designed here.

---

# G. Identity and Idempotency

**[REPO]** The canonical requirements (spec 15.2, enforced by the contract):
a milestone fires once; a repeated or earlier observation is a no-op; a closed
position is never evaluated; state changes only from broker results.

**[REPO]** `TradeState` guards the **observation** axis — `last_evaluated_time`
and `milestones_consumed`. It has no guard on the **result** axis: nothing
prevents the same `PartialCloseFilled` being applied twice, which would
decrement `steps_remaining` twice.

| Case | What the adapter must distinguish it by | Available today? |
|---|---|---|
| **Duplicate broker result** | A result identity — an execution/fill id, or the `client_order_id` of the request it answers | **No** — neither exists (§A.3) |
| **Duplicate partial fill** | Fill id, or (position id, request id, sequence) | **No** |
| **Duplicate close fill** | Same, plus `pending_close_reason` already cleared | Partly — the domain would raise on a second `apply_broker_result` to a `CLOSED` position, which converts a silent double-count into a loud failure |
| **Stale result from another position** | Canonical `position_id` on the result | **No** |
| **Broker retry** | `client_order_id` stable across retries — its documented purpose, "caller-side identifier for reconciliation" | **Type exists, unused** |
| **Restart replay** | Fill ids, so already-applied fills are skipped on rehydration | **No** |

**[DECISION]** Identity is therefore not merely a convenience for the ledger: it
is the mechanism that makes result handling idempotent. Without a fill id, "has
this result already been applied?" is unanswerable. **Not implemented.**

---

# H. Downstream Consequences

| # | Question | Now resolved | Still unresolved | Constraint introduced |
|---|---|---|---|---|
| **I2** | `TradeState` persistence | The **content** is settled: an immutable snapshot plus fill history, reconciled against the broker (§F) | The **format** — enums, `frozenset`, aware datetimes | A restored state must be treated as unverified until broker-checked, per `Position.broker_verified` |
| **I4** | `SimulatedPosition` as source of truth | **Resolved in principle**: it becomes a projection. `steps_remaining` in the domain is authoritative for quantity | Whether the class survives or is replaced by `core.types.Position` | It **must** carry the original stop or R immutably, or `r_multiple` breaks (§C.3) |
| **I5** | Position-id continuity | **Resolved in principle**: a canonical `position_id`, minted by the adapter at position creation, reproducible, with broker ids recorded alongside (§A.4) | Whether the id is promoted into `TradeState` — a specification amendment | Production's wall-clock and random identifiers are **replay-incompatible** and cannot be reused |
| **I8** | `bars_held` and ambiguity | `bars_held` stays position-level; ambiguity is recorded per fill with a position-level "any" | What `metrics.ambiguous_exits` counts once there are two exits | Ambiguity is produced per **evaluation** by the domain, so the adapter must attach it to the fill that evaluation caused |

**Is Option 2 still viable?** **Yes, and it is strengthened.** Each finding
supports it rather than undermining it: the missing partial price (§B) is exactly
what an external fill ledger supplies; the missing identity (§A, §G) is what a
fill ledger needs anyway and what makes result handling idempotent; and the
`risk_distance` defect (§C) is a property of the projection, which Option 2
demotes from source of truth. **No finding requires revisiting I1.**

---

# I. Required Decisions — proposed for review

**Proposals only. None is implemented.**

| # | Decision | Proposal | Principal evidence |
|---|---|---|---|
| **D1** | Canonical position identity | A canonical `position_id`, minted by the **adapter** when the position is created at the fill, reproducible in replay; broker order id and broker ticket recorded **alongside**, never as substitutes. `TradeState` stays id-free this phase; promoting the id into it is a recommended follow-up requiring a spec amendment | Broker ids are unknown at first evaluation and may change on netting (R2); production ids are wall-clock or `random` and replay-incompatible; `client_order_id` vs `broker_order_id` already model the split |
| **D2** | Fill-history ownership | An **immutable, append-only fill ledger outside the domain** owns the execution history. The domain keeps only what it decides with | No decision in `evaluate` or `apply_broker_result` reads a past fill price (§B.1) |
| **D3** | Partial execution price ownership | The **fill ledger** owns every executed price. `TradeState.closure_fill_price` keeps its present meaning — the final fill — and is not extended | Spec 16 routes every execution through `apply_broker_result`, so the adapter already sees each price |
| **D4** | Immutable original-risk representation | The projection and the trade record must store the **original** stop, or `R` copied from `TradeState.r`, as a field distinct from the current stop. `risk_distance` must never be derived from a mutable stop | Otherwise `r_multiple` is `None` for every position that reaches 1R, and the R distribution silently describes a biased subset (§C.3) |
| **D5** | `r_multiple` calculation source | Computed **once, on the aggregate trade record**, as total net P&L over `money_for_price_distance(R_original, quantity_original)`. Never per fill | A per-fill R divides by a risk the fill never carried (§D) |
| **D6** | Position projection responsibilities | The projection owns `bars_held` and the broker-facing view — identity mapping, live stop, live quantity for reconciliation. It owns **no** geometry, **no** milestone state and **no** authoritative quantity | §E leaves exactly these to it once the domain owns state and the ledger owns history |

---

# J. Verification

**Nothing was modified.** The only new file is this document. No production
Python, test, baseline, `core/trade_model.py` or canonical specification was
touched; no adapter was built; `PaperBroker` and the ledger are unchanged;
`trade_manager` was not retired; R1–R4, U5/R8 and U6/R9 are untouched.

Read-only inspection covered `core/trade_model.py`, `core/types.py`,
`core/symbols.py`, `execution/broker.py`, `execution/paper_broker.py`,
`backtest/ledger.py`, `backtest/metrics.py`, `backtest/baseline.py`,
`backtest/replay_engine.py`, `order_execution.py`, `trade_manager.py`,
`main_production.py`, `main.py` and `trade_persistence.py`.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 552.3 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`54899ea`, as expected for a documentation-only phase.

---

*Design and evidence only. No code changed, no identity minted, no fill ledger built, no risk field altered. Stopping for review.*
