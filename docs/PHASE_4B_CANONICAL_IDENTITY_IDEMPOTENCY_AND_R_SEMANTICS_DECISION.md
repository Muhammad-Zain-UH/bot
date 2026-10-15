# Phase 4B — Canonical Identity, Result Idempotency and R Semantics

**Design and evidence only.** No production Python, test, baseline,
`core/trade_model.py`, canonical specification, adapter, `PaperBroker` or ledger
is changed. `trade_manager` is not retired. `baseline_004` remains **FROZEN**.
R1–R4, U5/R8 and U6/R9 are untouched (§K).

**The three issues under investigation:**

1. Canonical position identity is minted by the adapter while `TradeState` is
   id-free.
2. Broker result application is not idempotent against a duplicate
   `PartialCloseFilled` or `CloseFilled`.
3. `risk_amount` / `r_multiple` depend on the **current** stop distance and
   become invalid after breakeven promotion.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `83fe262` |
| **[MEASURED]** | Established by running existing code read-only |
| **[DECISION]** | A design proposal for review — not implemented |
| **[UNRESOLVED]** | Cannot be settled from existing evidence |

---

# A. Identity Model

## A.1 What exists

| Identifier | Defined in | Meaning as documented | Used in production? |
|---|---|---|---|
| `OrderRequest.client_order_id` | `core/types.py:1033+` | "Caller-side identifier for reconciliation" | **No** |
| `OrderResult.broker_order_id` | `core/types.py:1114+` | "Broker-assigned identifier, when one was issued" | **No** |
| `Position.position_id` | `core/types.py:1205` | "**Broker ticket or local identifier**" — ambiguous by construction | **No** |
| `SimulatedPosition.position_id` | `execution/broker.py` | `SIM-%06d`, a run-scoped counter | Backtest only |
| `SimulatedTrade.trade_id` | `backtest/ledger.py:244` | Alias of `position_id` | Backtest only |
| `PendingOrder.order_id` + `sequence` | `execution/broker.py` | Simulator order identity and deterministic ordering | Backtest only |
| `order_execution` `order_id` | `order_execution.py:58-62` | `XAUUSD_{wall clock}_{counter}` | **Yes** |
| `order_execution` `mt5_order_id` | `order_execution.py:160` | `random.randint(1000000, 9999999)` in simulation | **Yes** |
| MT5 `pos.ticket` | `main.py:767`, `main_production.py:1243` | Broker position ticket | Only in the two shutdown paths |
| **`TradeState`** | `core/trade_model.py` | **No identifier at all** | — |
| **Execution / deal id** | — | **Does not exist anywhere** | — |

## A.2 The five identities, kept apart

| # | Identity | Names | Lifetime | Issued by |
|---|---|---|---|---|
| 1 | **canonical `position_id`** | One canonical position, entry → partial → remainder → close | The position | The adapter, at position creation |
| 2 | **`operation_id`** (client operation/request id) | One *instruction* the domain produced: this partial close, this stop move, this final close | One operation, across retries | The adapter, before submission |
| 3 | **`broker_order_id`** | The broker's record of the order created by that operation | The order | Broker |
| 4 | **`broker_deal_id`** (execution) | One execution against the position. A single order may produce several | The execution | Broker |
| 5 | **`fill_id`** | The ledger's key for one recorded execution | Forever (append-only) | The adapter, derived from 4 where the broker supplies one |

**[REPO]** The repository currently has (1) only in the simulator, (2) and (3)
as unused types, (4) nowhere at all, and (5) nowhere at all.

**[DECISION]** 4 and 5 are kept distinct deliberately: a paper broker has no
deal id, so `fill_id` must be derivable without one; and a live deal id is the
broker's, so it cannot be the ledger's primary key across venues. Where a deal
id exists, `fill_id` carries it as an attribute and dedupe uses it.

## A.3 Which identifiers each operation requires

| Operation | position_id | operation_id | broker_order_id | broker_deal_id | fill_id |
|---|---|---|---|---|---|
| **Entry** | created here | yes — the submission | yes, once accepted | one or more | one per execution |
| **Partial close** | references it | yes | yes | one or more | one per execution |
| **Stop modification** | references it | yes | modification may reuse or create one | **none** — no execution occurs | **none** |
| **Final close** | references it | yes | yes | one or more | one per execution |

**[DECISION]** A stop modification produces **no** fill and **no** deal. It is
an operation whose result is a confirmation, which is why §B treats
`StopModifyConfirmed` differently from the two quantity-changing results.

---

# B. Result Idempotency

## B.1 What the domain guards today

**[REPO]** `TradeState` guards the **observation** axis: `last_evaluated_time`
rejects a repeated or earlier observation, `milestones_consumed` fires each
milestone once, and a `CLOSED` position is never evaluated.

**[REPO]** It does **not** guard the **result** axis. `apply_broker_result`
computes `steps_remaining - result.steps_closed` with no notion of whether that
result was already seen. Applying the same `PartialCloseFilled(steps_closed=50)`
twice reduces quantity twice. The only accidental protection is that a second
`CloseFilled` raises, because the position is already `CLOSED` — a loud failure
rather than a silent double-count, and only for the final close.

## B.2 Four cases that must not be confused

| Case | What it is | Correct handling |
|---|---|---|
| **Duplicate request** | The adapter submits the same instruction twice | Prevented before submission: at most one outstanding operation per (position, operation kind), carrying a stable `operation_id` |
| **Duplicate broker result** | The same execution is *delivered* twice — a retry, a reconnect, a restart replay | **Discarded.** Identified by `broker_deal_id`, or by `(operation_id, sequence)` where no deal id exists |
| **Duplicate execution / deal** | The broker genuinely executed twice | **Not a duplicate.** Two deals, two fills, both applied |
| **Legitimate multiple fills for one request** | One close request filled in several pieces | All applied; their volumes sum to at most the requested quantity, and the excess is an anomaly, not a silent accept |

**[REPO]** The distinction between the second and third is unrepresentable
today, because no execution identity exists (§A.1). This is the mechanism gap,
not a policy gap.

## B.3 Where idempotency belongs

| Candidate | Assessment |
|---|---|
| **`TradeState`** | **No.** It would need an unbounded set of seen result ids, which is execution bookkeeping rather than a decision input — and adding it means changing `core/trade_model.py` and the specification, both prohibited here |
| **The fill ledger** | **Partly — it is the natural key store.** Append-only and keyed by `fill_id`, it already answers "has this execution been recorded?" |
| **The adapter** | **Yes — it enforces.** It is the only component that sees a broker result before the domain does |
| **Combination** | **Proposed** |

**[DECISION] The contract, in four rules:**

1. Every quantity-changing broker result carries a `fill_id`.
2. The adapter **writes the fill record first**, append-only and keyed by
   `fill_id`; a write whose key already exists is a no-op.
3. Only if the write was new does the adapter call `apply_broker_result`.
4. On restart, state is rebuilt from the snapshot **plus** the recorded fills,
   so a fill recorded but not yet applied is applied exactly once on recovery.

**[DECISION]** Rule 2 before rule 3 is deliberate. The reverse order — apply,
then record — loses the fill if the process dies between them, and the position
would then be rebuilt with a quantity the broker does not agree with. Recording
first can only ever duplicate a *record*, which rule 2 makes harmless.

**[DECISION]** A stale result naming another position is rejected by comparing
its `position_id`; without one, a result cannot be attributed at all. This is
why identity is a correctness mechanism here, not a convenience.

---

# C. Replay Determinism

## C.1 Non-deterministic identifiers today

**[REPO]**

| Source | Why it is not reproducible |
|---|---|
| `order_execution.generate_order_id` | `datetime.now()` |
| `order_execution` `mt5_order_id` | `random.randint`, unseeded |
| `main_production.manage_positions` `_auto_` suffix | `int(time.time())` |
| `main.py` trade id | `datetime.now()`, and it collides within one second |

**[REPO]** Deterministic today: `SimulatedPosition.position_id` (`SIM-%06d` from
a run-scoped counter) and `PendingOrder.sequence`.

## C.2 Deterministic inputs available at position creation

**[REPO]** At the moment a canonical position is created — the fill — the
adapter has, all of them deterministic in replay: `symbol`; `side`;
`entry_bar_time`; `decision_time`; `decision_bar_time`; `entry_price`; `volume`;
and a monotonic creation counter.

## C.3 Proposed scheme and its collision requirements

**[DECISION]** A composite, human-readable, content-derived id:

```
  position_id = f"{symbol}-{entry_bar_time:%Y%m%dT%H%M%S}-{side}-{sequence:04d}"
```

| Property | Why it holds |
|---|---|
| Deterministic in replay | Every component is a deterministic input (§C.2) |
| Stable across re-runs of the same data | No wall clock, no randomness |
| Unique within a run | `sequence` is monotonic per run and breaks every tie |
| Collision requirement | Two positions may share symbol, bar, and side — two signals filling on the same bar — so `sequence` is **required**, not decorative |
| Comparable across baselines | Two runs over the same period produce the same ids, which makes a diff between baselines readable |

**[UNRESOLVED]** Live use needs a `sequence` that survives a restart — a
persisted counter, or a different tail. That is part of I2 and is **not**
designed here. Replay determinism, which is what was asked, is achievable with
the architecture as it stands.

---

# D. R Semantics

## D.1 Every use traced

| Site | Expression | Basis |
|---|---|---|
| `core.trade_model.TradeState.r` | `abs(entry_price - original_stop_price)`, frozen at creation | **Original** |
| `core.types.StopLoss.risk_distance` | `abs(entry_price - price)` on a frozen validated object | **Original** |
| `core.types.Signal.risk_distance` | delegates to `StopLoss` | **Original** |
| `entry_engine.calculate_entry_levels` | `take_profit = entry ± risk_distance * tp_ratio` | **Original**, at entry |
| `execution/broker.py:271` `SimulatedPosition.risk_distance` | `abs(entry_price - stop_loss)` | **Current stop** |
| `backtest/ledger.py:233` `price_risk` | `= position.risk_distance` | **Current stop** |
| `backtest/ledger.py:234` `risk_amount` | `money_for_price_distance(price_risk, position.volume)` | **Current stop** |
| `backtest/ledger.py:235` `r_multiple` | `net_pnl / risk_amount if risk_amount > 0.0 else None` | **Current stop** |
| `backtest/ledger.py:230-231` `gross_pnl` / `net_pnl` | `price_move(exit_price) * money_per_price_unit(volume)`; `net = gross - commission` | Exit vs entry |
| `backtest/metrics.py:204,206` | aggregates `r_multiple` | Inherited |
| `backtest/baseline.py:550-557` | `realised_r` vs nominal `tp_ratio` | Inherited |

**[REPO]** Four sites derive R from the **current** stop; all of them are
downstream of the one property at `execution/broker.py:271`.

## D.2 Immutable facts versus mutable state

| Value | Class | Proposed home |
|---|---|---|
| Original entry price | **Immutable** | `TradeState.entry_price`; copied onto the trade record |
| Original stop | **Immutable** | `TradeState.original_stop_price`; **must be copied onto the projection** (§D.3) |
| Original quantity | **Immutable** | `TradeState.steps_at_entry` |
| Original price risk / R | **Immutable** | `TradeState.r` |
| Current stop | **Mutable management state** | `TradeState.confirmed_stop_price` (fact) and `stop_state_intended` (intent) |
| Remaining quantity | **Mutable management state** | `TradeState.steps_remaining` |
| Cumulative realised P&L | **Derived, accumulating** | Sum over the fill ledger |
| Total net P&L | **Derived, terminal** | Written once on the trade record at confirmed closure |

**[DECISION]** The canonical semantic is unchanged and not reinterpreted:
**R = absolute distance from the actual fill price to the original stop**,
frozen at creation.

## D.3 The defect, restated precisely

**[REPO]** Because `price_risk` reads the current stop, a position promoted to
breakeven has `risk_distance = abs(entry - entry) = 0`, hence `risk_amount = 0`,
hence `r_multiple = None` — and `metrics.py` filters `None` out, so the R
distribution would be computed over only the positions that never reached 1R.

**[DECISION]** The fix is representational, not semantic: the projection and the
trade record must carry the original stop, or `R` itself, as a field distinct
from the current stop, and `price_risk` must be that value.

---

# E. The R-Multiple Formula

## E.1 Consistency check against repository conventions

Proposed (D5, restated as D14 here):

```
r_multiple = total_net_pnl / money_for_price_distance(R_original, quantity_original)
```

| Convention | Evidence | Consistent? |
|---|---|---|
| Money conversion | `money_for_price_distance(d, v) = abs(d) * money_per_price_unit(v)`, itself `tick_value / tick_size * v` — **100.0 per lot** for XAUUSD | **Yes** — the same primitive the ledger uses today |
| Deliberate avoidance of `risk_manager` | `ledger.py:26` and `symbols.py:284`: the ledger uses the broker's tick value precisely because `risk_manager` assumes a contract size wrong by ~10× | **Yes** — unchanged |
| Denominator quantity | Today `risk_amount` uses `position.volume`, the **full** size | **Yes** — `quantity_original` is that same quantity |
| Denominator distance | Today `price_risk` is the **current** stop distance | **This is the only change**, and it is the §D.3 correction, not a new convention |
| Numerator | Today `net_pnl = gross_pnl - commission` | **Yes**, provided "total net P&L" sums every exit fill's P&L and subtracts total commission |
| Commission | `commission_for(volume) = commission_per_lot * volume`, **round turn**, default `0.0` | **Yes, and it composes**: charging pro-rata per exit fill gives `0.5 + 0.5 = 1.0 × commission_per_lot`, identical to today's single charge on the full volume |
| Slippage | `slippage_cost` is a reporting field; `replay_engine` never passes it, so it is **always 0.0**, because slippage is already inside the fill price | **Yes** — unchanged, and worth knowing the field is inert today |

**[REPO] No contradiction found.** The proposed denominator matches the existing
convention in every respect except the one value it deliberately corrects.

**[REPO] One convention worth stating, not a defect:** the numerator is **net**
of commission while the denominator is **gross** risk. A position stopped at
exact breakeven therefore reports a slightly negative R once commission is
non-zero. That is the existing repository convention and is preserved.

## E.2 When should it be calculated?

| Option | Assessment |
|---|---|
| Continuously | **No.** R-multiple is a realised outcome; an open position has no realised total. `metrics.py` already computes over `completed` trades only |
| At each fill | **No.** A per-fill R would divide by a risk that fill never carried — the 0.50-lot remainder never risked 1.00 lot |
| **Once, at confirmed closure, on the aggregate trade record** | **Yes.** `trade_from_position` already raises if the position is still open, so "R exists only at terminal state" is an existing repository rule, not a new one |

**[REPO] The previous proposal is verified against repository semantics and
stands.**

---

# F. Partial P&L Reconstruction

**Conceptual. No code.** BUY 1.00 lot, entry fill 2450.00, original stop
2420.00, `tp_ratio` 3.0. `volume_step = 0.01`, so 1.00 lot = 100 steps and the
1R partial is `floor(100/2) = 50` steps = 0.50 lots. `money_per_price_unit(1.0
lot) = 100.0`.

| Quantity | Value |
|---|---|
| Entry quantity | 100 steps = 1.00 lot |
| Partial quantity | 50 steps = 0.50 lot |
| Remaining quantity | 50 steps = 0.50 lot |

**Per-fill P&L**, each at its own executed price, with direction carried by
`side.sign`:

```
fill_pnl(f) = (f.executed_price - entry_price) * side.sign
              * money_per_price_unit(f.quantity_in_lots)
```

Worked, with the partial executed at 2479.80 and the remainder at 2539.80 —
both a touch below their levels because exits cross the spread
(`apply_spread_on_exit = True`, default spread 2.0 pips = $0.20):

```
partial : (2479.80 - 2450.00) * (+1) * 100.0 * 0.50 = +1490.00
final   : (2539.80 - 2450.00) * (+1) * 100.0 * 0.50 = +4490.00
gross total                                          = +5980.00
commission = commission_per_lot * 1.00 total exit volume   (default 0.00)
net total  = gross total - commission                = +5980.00
```

| Concept | Definition |
|---|---|
| Aggregate gross P&L | Sum of `fill_pnl` over **exit** fills. Never recomputed from an average exit price |
| Commission | Charged per exit fill on that fill's volume; the sum equals one round turn on the original quantity |
| Slippage | Already inside the executed price; the reporting field stays 0.0 (§E.1) |
| Direction | Carried by `side.sign`, once, in the per-fill formula |
| Total net P&L | Aggregate gross minus total commission, written once at confirmed closure |
| R multiple | `total_net_pnl / money_for_price_distance(30.00, 1.00 lot)` = `5980.00 / 3000.00` = **1.993** |

**[REPO]** The 1.993 figure is arithmetic on invented prices, chosen only to
show the reconstruction. It is not a measurement and makes no claim about
outcomes.

---

# G. Identity Ownership Table

| Concept | Owner | Lifetime | Required for idempotency? | Persistent? |
|---|---|---|---|---|
| `position_id` | Adapter, minted at position creation | The position | **Yes** — attributes every result to one position | **Yes** |
| `operation_id` | Adapter, minted before submission | One instruction, across retries | **Yes** — distinguishes a retry from a new instruction | Yes, while outstanding |
| `client_order_id` | Adapter — **the same value as `operation_id`**, under the name `core.types.OrderRequest` already gives it | Same | Yes | Yes |
| `broker_order_id` | Broker | The order | Supporting — correlates a result to an operation | Recorded |
| `broker_deal_id` | Broker | One execution | **Yes** where available — the natural dedupe key | Recorded |
| `fill_id` | Adapter/ledger, carrying `broker_deal_id` where one exists | Forever, append-only | **Yes** — the ledger's dedupe key | **Yes** |
| `TradeState` identity | **Should not exist as a separate concept** — the state is identified by the `position_id` it is stored under | — | No | Via its key |
| `SimulatedPosition` identity | Projection; **should become the same value** as `position_id` rather than a second scheme | The position | No | Run-scoped |
| `SimulatedTrade` identity | **Should not exist as a separate concept** — it is the `position_id` of the position it records, as it already is today | — | No | Yes |

**[DECISION]** Three concepts are explicitly declined: a `TradeState`-internal
id distinct from its key, a `SimulatedTrade` id distinct from the position's,
and a simulator id scheme distinct from the canonical one. Each would be a
second name for one thing.

---

# H. Canonical Specification Impact

| Requirement | Permitted by the current spec? | Evidence |
|---|---|---|
| **Adapter-owned position identity** | **Yes.** §18.2 gives the execution adapter "order ids"; the spec never places identity in the domain | No amendment required |
| **External append-only fill history** | **Yes.** §18.1 gives the ledger "every event, every ambiguity flag, every anomaly" | No amendment required |
| **Duplicate-result idempotency** | **No — a gap.** §15 covers only the observation axis. §16 requires state to change solely from broker results but never requires a result to be applied at most once | **Amendment required** |
| **Immutable original-R accounting** | **Yes.** §4.1 already freezes R and forbids stop movement from redefining it. The defect is in ledger code, which the spec does not govern | No amendment required |

**[DECISION] Proposed amendment, for a later task — not applied here.**

> Add to §15.1 *Required per-position state*: a row for the identity under which
> the state is held, noting that it is supplied by the adapter and that a
> persisted state is meaningless without it.
>
> Add to §16 a new subsection, *16.3 Results are applied at most once*:
> "Every quantity-changing broker result carries an execution identity. The
> adapter records the execution before applying it and discards a result whose
> identity has already been recorded. A result that names a different position
> is rejected, not applied. Several distinct executions arising from one request
> are not duplicates and are each applied."
>
> Add to §24 MUST: "A quantity-changing broker result is applied at most once,
> identified by its execution identity."

**The specification is not edited in this task.**

---

# I. The `core.types` Contradiction

| Question | Finding |
|---|---|
| Is `Position` broker-facing? | **Yes.** "An open or historical position, **as the broker sees it**… a snapshot to be reconciled against `positions_get()`, never a substitute for it", plus `broker_verified = False` by default |
| Is it a canonical domain representation? | **No.** It holds no milestone state, no R, no `tp_ratio` |
| Is it legacy? | **No** — it is Phase 1 work, validated and tested, simply never wired |
| Mixed semantics? | **In one field only:** `position_id` is documented as "broker ticket **or** local identifier", which spans identities 1 and 3 of §A.2 |
| Is `PARTIALLY_CLOSED` canonical? | **No — broker-facing.** It describes what the broker reports: reduced volume on a live position |

**[DECISION] They can coexist with `TradeState` without ambiguity, provided two
rules are stated:**

1. `Position` is the **broker snapshot**; `TradeState` is the **canonical
   machine**. Neither derives from the other; the adapter reconciles them.
2. In any future use, `Position.position_id` carries the **broker ticket**, and
   the canonical `position_id` is recorded separately. The current docstring
   permits either reading, so the choice must be pinned where the type is used.

**Mapping, for the record:** `TradeState.lifecycle = OPEN` with
`steps_remaining < steps_at_entry` corresponds to
`PositionStatus.PARTIALLY_CLOSED`. There is no conflict once the two are
understood as answering different questions — what the model decided, and what
the broker reports.

**Neither type is changed.**

---

# J. Required Decisions

| # | Decision | Proposal | Spec status |
|---|---|---|---|
| **D7** | Canonical position identity | Adapter-minted at position creation, deterministic (§C.3), referenced by every fill and result | **Fits the current spec.** An amendment to §15.1 is *recommended* for self-describing persisted state, not required |
| **D8** | Operation/request identity | One `operation_id` per instruction, stable across retries, submitted as `client_order_id` — the field `core.types` already defines for this | **Fits** |
| **D9** | Broker execution identity | `broker_order_id` correlates a result to an operation; `broker_deal_id` identifies the execution. Both recorded, neither used as the canonical id | **Fits** |
| **D10** | Fill identity | Every recorded execution has a `fill_id`, carrying `broker_deal_id` where one exists and derived deterministically where none does, as in paper execution | **Fits** |
| **D11** | Duplicate-result idempotency owner | **Adapter enforces, fill ledger stores the keys, `TradeState` unchanged.** Record the fill first, then apply; a known `fill_id` is a no-op | **Requires the §16.3 amendment in §H** |
| **D12** | Deterministic replay identity | `{symbol}-{entry_bar_time}-{side}-{sequence:04d}`; `sequence` is required to break same-bar ties | **Fits.** Live restart sequencing remains I2, **[UNRESOLVED]** |
| **D13** | Immutable original-R representation | The projection and trade record carry the original stop, or `R` copied from `TradeState.r`, distinct from the current stop; `price_risk` is that value | **Fits** — §4.1 already freezes R |
| **D14** | Aggregate `r_multiple` | `total_net_pnl / money_for_price_distance(R_original, quantity_original)`, computed **once** at confirmed closure. Verified against every existing convention (§E.1) | **Fits** |
| **D15** | Partial-fill P&L accounting | Per-fill P&L at each executed price, summed; commission pro-rata per exit fill summing to one round turn; slippage already inside the price | **Fits** |

**One amendment is required in total**, and it concerns D11 alone.

---

# K. Safety Check

Each decision checked against the six items that must stay open.

| Item | Touched? | Why not |
|---|---|---|
| **R1** reversal protection | **No** | No decision adds, removes or reinterprets a protective exit. A protection exit, were R1 ever to add one, would simply be another fill cause |
| **R2** netting vs hedging | **No** | §A.4 of the predecessor cites netting as a *reason* the broker ticket cannot be the canonical id. Citing an unresolved question as a constraint is not answering it; no decision here states which account model applies, and D9 records the ticket without depending on its stability |
| **R3** session/weekend handling | **No** | Nothing here concerns when a position may be held or closed |
| **R4** broker quantity-mismatch severity | **No** | D11 makes a mismatch *detectable and non-duplicative*; it does not grade it. Whether a mismatch warns or halts is untouched |
| **U5/R8** close re-request observed reference | **No** | D8 gives a re-request a stable `operation_id`; which **price reference** it carries is a separate question and stays open |
| **U6/R9** rejected stop promotion behaviour | **No** | A stop modification produces no fill and no deal (§A.3), so none of the identity or idempotency rules reaches it |

**All six remain unresolved and untouched.**

---

# L. Verification

**Nothing was modified.** The only new file is this document. No production
Python, test, baseline, `core/trade_model.py` or canonical specification was
changed; no adapter was built; `PaperBroker` and the ledger are unchanged;
`trade_manager` was not retired.

Read-only inspection covered `core/trade_model.py`, `core/types.py`,
`core/symbols.py`, `core/units.py`, `execution/broker.py`,
`execution/paper_broker.py`, `execution/fills.py`, `backtest/ledger.py`,
`backtest/metrics.py`, `backtest/baseline.py`, `backtest/replay_engine.py`,
`order_execution.py`, `main_production.py` and `main.py`.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 538.1 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`83fe262`, as expected for a documentation-only phase.

---

*Design and evidence only. No code changed, no identifier minted, no idempotency mechanism built, no risk field altered, no specification edited. Stopping for review.*
