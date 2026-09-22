# Phase 4B — Canonical Trade Management Specification

**Specification only. No code, test, backtest, baseline or parameter is
changed by this document.** Neither existing manager is wired, repaired or
deleted. `valid_rr`, risk sizing, SL/TP construction and the LIMIT_FVG
implementation are untouched. `baseline_004` remains **FROZEN**.

**Status:** Option D, selected by the strategy owner. `trade_manager`,
`order_execution` and the `config.py` trailing constants are **historical
evidence**. This document is the canonical source of truth for trade
management.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Directly established by repository code or documentation at `0f73fb2` |
| **[HISTORICAL]** | Established by git history |
| **[MEASURED]** | Established by executing existing code read-only, here or in a cited predecessor |
| **[DECISION]** | A **new canonical design decision** taken in this document. The repository did not establish it |
| **[INFERENCE]** | Mechanically implied by a stated decision; not an independent choice |
| **[UNRESOLVED]** | Cannot be settled from existing evidence; stated, not forced |

**Every `[DECISION]` in this document is new.** None is presented as something
the repository already established.

---

# 1. Purpose

To define one broker-agnostic trade-management model precisely enough that:

1. a single implementation can be written against it,
2. production and replay can be shown to obey the *same* model,
3. the tests that verify it can be written **before** any production code
   changes, and
4. every remaining open question is visible rather than implicit.

**This document does not authorise implementation.** It defines what a future
implementation must satisfy (§24).

## What it replaces

| Source | New status |
|---|---|
| `trade_manager.py` | **Historical evidence.** Its behaviour informed this model; it is not the model |
| `order_execution.py` | **Historical evidence.** Same |
| `config.py` trailing constants | **Historical evidence**, unimplemented and deferred (§9) |

**[REPO]** None of the three is modified or deleted by this document; DD1's
blocked-items list stands until implementation is separately authorised.

---

# 2. Source Evidence

| Document / source | What it contributes |
|---|---|
| `docs/PHASE_4B_DD1_CANONICAL_TRADE_MANAGER.md` (`85590eb`) | The finding that no canonical manager is established; measured behaviour of both; the label-vs-behaviour conflict in `SYSTEM_STRUCTURE_DIAGRAM.md` |
| `docs/PHASE_4B_DD1_TRADE_MANAGEMENT_DESIGN_OPTIONS.md` (`0f73fb2`) | The twenty design questions; the measured four-regime ladder table; the SELL inversion; the dependency derivation |
| `docs/PHASE_4B_FIX_DECISION_MATRIX.md` (`536b350`) | Defect and decision inventory; the blocked-items list |
| `docs/PHASE_4B_TARGET_SEMANTICS.md` | Fixed-R target model established as deliberate; `rr ≡ tp_ratio` |
| `docs/PHASE_4A_LIMIT_FVG_IMPLEMENTATION.md` | The resting-limit design and its experimental controls |
| `docs/PHASE_4A_STEP4_DECISION_EVIDENCE.md` | Why expiry, zone invalidation and cross-session cancellation are disabled controls |
| `docs/PHASE_4A_R1_SAME_BAR_EXIT_MEASUREMENT.md` | The fill bar is evaluated for exits (R1) |
| `execution/broker.py`, `execution/paper_broker.py`, `execution/fills.py`, `execution/intrabar.py` | Existing execution semantics: states, gap rules, cost model, intrabar policy |
| `core/symbols.py` | `volume_min`, `volume_step`, `contract_size`, rounding helpers — the basis of §5 |
| `entry_engine.py`, `backtest/baseline.py` | `tp_ratio` per regime; stop construction |
| `trade_manager.py`, `order_execution.py`, `main.py`, `main_production.py` | Historical behaviour, cited but not inherited |

**No repository evidence is silently overridden.** Where this model departs
from existing behaviour, §24 and §25 say so explicitly.

---

# 3. Canonical Decisions

Given by the strategy owner and adopted verbatim:

| # | Decision | Status |
|---|---|---|
| Q1 | `R = abs(entry_price − original_stop_price)`, frozen at position creation. Moving the stop never redefines R | **DECIDED** [DECISION] |
| Q12 | `TP = entry + tp_ratio × R` (BUY) / `entry − tp_ratio × R` (SELL). `tp_ratio` stays the regime-selected multiple; regime values unchanged | **DECIDED** [DECISION] |
| Q2 | At 1R: close 50 % of the original quantity, retain 50 %. A milestone event, not a closure | **DECIDED** [DECISION] |
| Q4 | After the 1R partial: stop for the remaining quantity moves to `entry_price` — **BREAKEVEN** | **DECIDED** [DECISION] |
| Q5 | At 2R: no further partial; stop moves to `entry + 1R` (BUY) / `entry − 1R` (SELL) | **DECIDED** [DECISION] |
| Q8 | No continuous ATR trailing. The progression is discrete: original → breakeven at 1R → +1R locked at 2R → final TP. The `config.py` constants stay historical and inactive | **DECIDED** [DECISION] |
| Q15 | A gapped stop fills at the **actual executable/observed** price, never at the requested level | **DECIDED** [DECISION] |
| Q16 | A gapped target fills at the **actual executable/observed** price, never automatically at the requested level | **DECIDED** [DECISION] |

Everything below resolves the questions these leave open.

## 3.1 Clarification log

| Revision | Change | Sections |
|---|---|---|
| `adbbb05` | Original specification | — |
| **this revision** | **Closure is confirmed, never assumed.** Detecting a stop, target or protective condition does not mark the position `CLOSED`; `evaluate` emits `CLOSE_REQUESTED`, the position stays `OPEN` with `pending_close_reason` set, and only a confirming broker result closes it | **§8.2, §11.1, §11.1a, §11.3, §17, §22, §23, §24** |
| **this revision** | **The domain does not price executions.** The canonical state machine emits `requested_level` and `observed_reference` only; the execution adapter computes the executable price and the broker supplies the recorded fill. No broker-specific logic in `core/trade_model.py` | **§11.1b, §12.1, §18.2, §23, §24** |
| **this revision** | Two new open items recorded, deliberately **not** resolved: U5/R8 (observed reference on a re-requested close) and U6/R9 (whether an unconfirmed stop promotion blocks the next milestone) | **§24, §25** |

**[DECISION]** Both clarifications state what was already implied by §16 and
§18; neither changes a decided rule, and R1–R4 are untouched. The 84 contract
tests committed at `f4bc150` were written against exactly this reading and
required **no** assertion change.

---

# 4. R Definition

## 4.1 Canonical rule

```
R = abs(entry_price - original_stop_price)

entry_price        = the price the position was ACTUALLY filled at,
                     after execution costs, as reported by the broker
                     (live) or the fill model (paper/replay)
original_stop_price = the structural stop supplied by the strategy,
                     unchanged by the fill
```

**[DECISION]** R is computed **once**, at position creation, and is immutable
for the life of the position. Every milestone level is derived from it at the
same instant and stored. Nothing recomputes a level later.

**[DECISION]** `entry_price` means the **actual fill price**, not the price the
strategy intended. The strategy's intended entry is a *request*; the position's
geometry is defined by what was actually obtained.

**[REPO]** This distinction is material, not theoretical: `execution/fills.py`
adjusts every entry adversely by `spread + slippage` (default spread
`Pips(2.0)` = **$0.20** on gold), and a LIMIT_FVG order that gaps through its
limit fills at the bar open rather than the limit (`paper_broker:362-370`).

## 4.2 The consequence for TP — mechanically implied

**[INFERENCE]** Q1 and Q12 together fix the target once `entry_price` is fixed:

```
R  = |fill_entry - original_stop|
TP = fill_entry ± tp_ratio × R
```

**[REPO] This differs from current behaviour.** Today a filled pending order
carries `take_profit=intent.take_profit` (`paper_broker:374`), computed by the
strategy from the *intended* entry. If the fill price differs from the intent —
which it does by at least the cost adjustment — then the carried target no
longer satisfies `TP = entry ± tp_ratio × R`, and the identity `rr ≡ tp_ratio`
established in `PHASE_4B_TARGET_SEMANTICS.md` no longer holds exactly for that
position.

**[DECISION]** The canonical model **recomputes the target at fill** from the
actual entry, so the identity holds for every position by construction.

| Alternative considered | Why it is not adopted |
|---|---|
| Keep the strategy's target unchanged | `rr` would drift from `tp_ratio` by the cost and gap adjustment, breaking the one target property the repository does establish |
| Define geometry from the *intended* entry | R would not describe the position actually held; a gapped fill would misstate risk |

**Implementation consequence:** this is a **behaviour change** relative to
`8a4e010`. It must be its own commit, and it will change replay artifacts, so
it requires a new canonical baseline (§24, DEFERRED-list).

## 4.3 Degenerate cases

**[DECISION]** If, after the fill, `R == 0` or the stop lies on the wrong side
of the actual entry, the position is **rejected, not clamped**: no position is
created and the event is recorded with a reason.

**[REPO]** `paper_broker._open_position` already raises `DomainInvariantError`
when the stop coincides with the entry, and `submit_market_order` rejects a
stop on the wrong side after cost adjustment. The canonical rule generalises
that existing behaviour rather than inventing one.

## 4.4 What R is not

**[DECISION]** R is **trade geometry only**. It is not a money amount, not a
lot size, and not a risk budget. The relationship to position sizing is stated
in §21 and deliberately excluded here.

---

# 5. Position Quantity

## 5.1 Authoritative representation

**[DECISION]** Quantity is held internally as an **integer number of volume
steps**, not as a float in lots.

```
steps        : int          # authoritative
lots         = steps * spec.volume_step      # derived, for the broker boundary
```

**Rationale.** Halving, comparing and decrementing lots as floats invites
representation error at exactly the boundary where a broker rejects an order.
`core/symbols.py` already floors to the step (`round_volume_to_step`, `:209`)
and already documents the 10× class of error this prevents. Integers make the
partial-close arithmetic exact and the idempotency guarantee checkable.

**[REPO]** For `XAUUSD_2DIGIT`: `volume_min = 0.01`, `volume_step = 0.01`,
`volume_max = 100.0`, `contract_size = 100.0`.

## 5.2 The 50 % rule, exactly

**[DECISION]**

```
steps_to_close_at_1R = floor(steps_at_entry / 2)
steps_remaining      = steps_at_entry - steps_to_close_at_1R
```

**Rounding is downward**, so "close 50 %" never closes *more* than half. Where
the split is uneven, the **larger** part is retained.

**[DECISION]** If `steps_to_close_at_1R == 0`, **no partial close is attempted
at all.** No order is sent. The 1R milestone is still consumed and the stop
still moves (§5.4).

### Why this case is the normal case, not an edge case

**[REPO]** `config.py` sets `INTRADAY_LOT_SIZE_MIN = 0.01` and
`INTRADAY_LOT_SIZE_MAX = 0.1`, so the intended sizing range is 1 to 10 steps:

| Lots | steps | close at 1R | remaining | Partial possible? |
|---|---|---|---|---|
| 0.01 | 1 | 0 | 1 | **No** |
| 0.02 | 2 | 1 | 1 | Yes, exactly 50 % |
| 0.03 | 3 | 1 | 2 | Yes, 33 % / 67 % |
| 0.04 | 4 | 2 | 2 | Yes, exactly 50 % |
| 0.05 | 5 | 2 | 3 | Yes, 40 % / 60 % |
| 0.06 | 6 | 3 | 3 | Yes, exactly 50 % |
| 0.07 | 7 | 3 | 4 | Yes, 43 % / 57 % |
| 0.08 | 8 | 4 | 4 | Yes, exactly 50 % |
| 0.09 | 9 | 4 | 5 | Yes, 44 % / 56 % |
| 0.10 | 10 | 5 | 5 | Yes, exactly 50 % |

**[INFERENCE]** At the configured minimum size the partial is **impossible**,
and in five of ten configured sizes it is not exactly half. "Close 50 %" is
therefore a *target ratio subject to the broker's step grid*, and the model
must say so rather than assume divisibility.

## 5.3 Close-all semantics

**[DECISION]** A closing event (target, stop, or any future protective event)
closes **all remaining steps** in one request. There is no partial closure of a
remainder, and no minimum-size exemption: if a position exists, its whole
remaining quantity is closeable.

## 5.4 Does a failed or impossible partial block the stop move?

**[DECISION] No. The stop move at 1R is an independent event.**

```
1R reached  ->  event A: partial close of floor(steps/2)   (may be 0, may fail)
            ->  event B: intended stop state = BREAKEVEN   (always)
```

**Rationale.** They are two different risk actions. Coupling them means a
position that has earned 1R but cannot be halved — the configured **minimum
size**, per §5.2 — would remain at full original risk indefinitely. Coupling
also makes the model undefined for the most common size.

| Alternative considered | Consequence |
|---|---|
| Atomic: stop moves only after a confirmed partial fill | The 0.01-lot position never reaches breakeven; a broker reject leaves full risk after a 1R excursion |

**[DECISION]** The *intended* stop state advances immediately; the *confirmed*
stop state advances only when the broker acknowledges the modification (§7.3,
§16). These are two fields, not one.

---

# 6. Milestone Model

## 6.1 Levels

**[DECISION]** All three levels are computed once at creation, from the frozen
entry and R, and stored on the position:

| Milestone | BUY | SELL |
|---|---|---|
| `M1R` | `entry + R` | `entry − R` |
| `M2R` | `entry + 2R` | `entry − 2R` |
| `TARGET` | `entry + tp_ratio × R` | `entry − tp_ratio × R` |

**[MEASURED]** This direction-aware construction is stated explicitly because
the historical `order_execution` computed `entry + risk` for **both** sides,
placing a SELL's "1R" exactly on its stop
(`PHASE_4B_DD1_TRADE_MANAGEMENT_DESIGN_OPTIONS.md` §8.1). No implementation of
this model may derive a level without the side.

## 6.2 Reached conditions

**[DECISION]**

| Observation source | BUY reached when | SELL reached when |
|---|---|---|
| Single price sample | `price >= level` | `price <= level` |
| OHLC bar | `bar.high >= level` | `bar.low <= level` |

**[DECISION]** Reaching is evaluated on the bar **range**, not the close. A
level touched intrabar is reached even if the bar closes back through it.

## 6.3 Consumption

**[DECISION]** Each milestone fires **at most once** per position. A consumed
milestone is never re-evaluated, regardless of later price action (§15).

## 6.4 Ordering within one evaluation

**[DECISION]** When several milestones are reachable in the same evaluation,
they are processed in **ascending distance from entry**: `M1R`, then `M2R`,
then `TARGET`. A skipped milestone is impossible: reaching `M2R` implies `M1R`
was reached, so `M1R` is processed first and consumed in the same evaluation.

---

# 7. Stop-State Model

Stop state is **orthogonal** to position state and is tracked separately.

## 7.1 States

**[DECISION]** Three states. The names are chosen for this model; they are not
inherited from either implementation's vocabulary.

| State | Stop price | Meaning |
|---|---|---|
| `ORIGINAL` | `original_stop_price` | As supplied by the strategy at entry |
| `BREAKEVEN` | `entry_price` | Set when `M1R` fires |
| `LOCKED_1R` | `entry ± R` | Set when `M2R` fires |

## 7.2 Transitions

```
   ORIGINAL ──M1R──► BREAKEVEN ──M2R──► LOCKED_1R
       │                 │                  │
       └── no other transition exists in this model ──┘
```

**[DECISION] Allowed:** `ORIGINAL → BREAKEVEN`, `BREAKEVEN → LOCKED_1R`, and —
within a single evaluation where both milestones fire — the two in sequence.

**[DECISION] Forbidden, and required to raise rather than be silently ignored:**

- `BREAKEVEN → ORIGINAL`, `LOCKED_1R → BREAKEVEN`, or any backward move.
- `ORIGINAL → LOCKED_1R` directly (skipping is impossible by §6.4).
- Any transition on a `CLOSED` position.
- Any stop price assignment that moves the stop **adversely** — further from
  price in the losing direction — for any reason.

**[DECISION] Monotonicity.** The stop is monotonic in the favourable direction
for the life of the position: for a BUY the stop never decreases, for a SELL it
never increases. This is a hard invariant, not a consequence of the transition
list, and applies to any future protective rule as well.

## 7.3 Intended vs confirmed stop

**[DECISION]** Two fields:

| Field | Set by | Meaning |
|---|---|---|
| `stop_state_intended` | the model, when the milestone fires | What the model has decided |
| `stop_state_confirmed` | the broker result | What is actually protecting the position |

**[DECISION]** Risk statements — "this position is at breakeven" — may only be
made from `stop_state_confirmed`. While the two differ, the position is treated
as protected at the **confirmed** level, and the modification is re-attempted on
each evaluation until confirmed. That retry is idempotent because the milestone
is already consumed and the target stop price is fixed (§15, §16).

**[REPO]** In paper and replay execution the two are always equal, because the
paper broker's modification cannot fail. The distinction exists so that the same
state machine is correct under a real broker.

---

# 8. Position-State Model

## 8.1 Why states are not collapsed

**[DECISION]** The model does **not** use compound names such as
`OPEN_BREAKEVEN`. Position state, stop state and remaining quantity are three
independent facts; collapsing them produces a product of artificial states and
still cannot express, for example, "at breakeven, partial not executed because
the size was one step".

## 8.2 Position state

| State | Meaning | Terminal |
|---|---|---|
| `OPEN` | The position exists and is managed. **Includes a position whose closure has been requested but not yet confirmed by the broker** | No |
| `CLOSED` | The broker has **confirmed** that no quantity remains; never re-evaluated | **Yes** |

**[DECISION]** A partially closed position is `OPEN` with fewer steps. There is
no distinct "partially closed" position state; the partial is visible in
`steps_remaining` and in the consumed-milestone set.

**[DECISION] — clarification.** A position whose stop or target has been reached
is still `OPEN`. Detecting an exit condition is **not** a closure. The
outstanding request is recorded in `pending_close_reason`, which is the only
marker distinguishing "open, closure requested" from "open, nothing
outstanding". No third lifecycle state is introduced: closure is a fact about
the broker's books, and until the broker confirms it, the position exists.

See §11.1a for the canonical sequence and §16 for what happens when the request
fails.

## 8.3 Closure reason

**[DECISION]** Every `CLOSED` position carries exactly one reason:

| Reason | Cause |
|---|---|
| `STOP` | The confirmed stop was reached |
| `TARGET` | The target was reached |
| `EXTERNAL` | The broker reports the position no longer exists, for a cause the model did not initiate (§16) |
| `END_OF_DATA` | Replay only: the dataset ended while the position was open |
| `MANUAL` | An operator or shutdown routine closed it |

**[REPO]** `PositionState` in `execution/broker.py` already distinguishes
`CLOSED_STOP`, `CLOSED_TARGET`, `CLOSED_TIME`, `CLOSED_END_OF_DATA` and
`CLOSED_MANUAL`. The canonical set above maps onto it, except that
`CLOSED_TIME` has **no canonical counterpart** because time-based exit is
deferred (§9). That mapping is a later implementation concern, not a change
authorised here.

---

# 9. Trailing and Deferred Behaviour

**[DECISION]** The canonical model contains **no continuous trailing stop**.
The entire stop progression is the three-state discrete ladder of §7.

## 9.1 The `config.py` constants

**[REPO]** Exact fields, values and comments:

| Field | Value | Comment in source | Line |
|---|---|---|---|
| `TRAILING_STOP_ATR_TRIGGER` | `1.0` | "Activate at 1× risk profit" | `config.py:150` |
| `TRAILING_STOP_ATR_TRAIL` | `0.75` | "Trail by 75% of entry ATR" | `config.py:151` |
| `INTRADAY_MAX_HOLD_MINUTES` | `240` | "Exit by 4-hour mark" | `config.py:157` |
| `INTRADAY_MIN_HOLD_MINUTES` | `5` | "Minimum 5 minutes before trailing" | `config.py:158` |
| `MAX_SLIPPAGE_PIPS` | `2.0` | spread + latency allowance | `config.py:147` |

**[REPO]** No code reads any of them; the only reference is
`test_integration.py:111`, asserting that one attribute exists.
**[HISTORICAL]** `git log -S` places all five in `c3cf4df`, the same commit as
everything else, so history establishes no independent origin.

**[DECISION]** These remain **unimplemented historical configuration**. They
must not become active behaviour through this specification. An implementation
of this model **must not** read them.

## 9.2 Deferred, explicitly

| Deferred item | Status |
|---|---|
| ATR-based continuous trailing | **DEFERRED** — requires its own decision and outcome evidence |
| Time-based exit (240-minute maximum hold) | **DEFERRED** — no time concept exists anywhere in the model or the backtest today [REPO] |
| Minimum hold before trailing (5 minutes) | **DEFERRED** — meaningless without trailing |
| Slippage allowance as a *policy* | **DEFERRED** — the cost *model* exists in `execution/fills.py`; the configured allowance is unused [REPO] |

---

# 10. Reversal Protection

## 10.1 What the historical implementation does

**[REPO]** `trade_manager.check_breakeven_stop` (`:270-330`) closes the
remaining position when, **while the stop is at or above breakeven**, price
returns to within `breakeven_trigger_pip_buffer = 2.0` of entry. It emits
`CLOSE_BREAKEVEN_PROTECTION` (`:467`).

Three properties, verified:

1. **[REPO]** The parameter is named `..._pip_buffer` but is added to a price,
   so it is **$2.00**, not 2 pips ($0.20) — the same unit defect family as
   `buffer_pips` (F7).
2. **[INFERENCE]** For a BUY the trigger window is
   `stop_price < price <= entry + 2.00`. Once the stop is `LOCKED_1R`
   (`entry + R`), the window is **empty whenever R > $2.00**. Phase 4A measured
   the stop buffer at 29.4 % of median risk, implying a median R near $10, so
   the rule is effectively reachable **only in the `BREAKEVEN` state**.
3. **[REPO]** No design document describes it. It appears in no specification,
   no commit message and no test.

## 10.2 What adopting it would mean

**[INFERENCE]** In the `BREAKEVEN` state the stop already sits at entry.
Reversal protection therefore does not add protection — it **tightens the
breakeven stop to `entry + $2.00`**, converting a breakeven exit into a small
fixed-profit exit. That is a strategy parameter, not a safety mechanism.

## 10.3 Canonical status

**[UNRESOLVED]**

The canonical model **does not include reversal protection**, pending an
explicit decision. This is stated as an open question, not as a rejection.

**What must be decided:** whether the model exits the remainder at a fixed
offset above entry once 1R has been achieved, and if so, what that offset is and
in what unit.

**What evidence would settle it:** outcome evidence on positions that reached
1R and then retraced — which requires trades to exist. **[MEASURED]**
`baseline_004` produced zero trades, so this cannot currently be measured.

**[DECISION]** Until decided, an implementation **must not** implement it. If
it is later adopted, §11 Case I fixes its ordering in advance.

---

# 11. Event Ordering

## 11.1 The evaluation algorithm

**[DECISION]** One evaluation consumes one price observation — a bar in replay,
a price sample in live — and applies exactly this order:

```
evaluate(position, observation):

  0. PRECONDITION
     position.state == OPEN, and observation.time > position.last_evaluated_time.
     Otherwise: no-op. (§15)

  1. SNAPSHOT THE EFFECTIVE STOP
     S := stop price as CONFIRMED at the END of the previous evaluation.
     Stop moves made during THIS evaluation do not apply to THIS observation.

  2. ADVERSE FIRST
     If the observation's adverse extreme reaches S
        (BUY: low <= S ; SELL: high >= S):
          emit CLOSE_REQUESTED for ALL remaining steps, carrying
               requested_level    := S
               observed_reference := bar open if gapped, else S   (§12)
          pending_close_reason := STOP
          position stays OPEN -- the domain does NOT mark it CLOSED   (§11.1a)
          RETURN.

  3. FAVOURABLE MILESTONES, ascending (§6.4), each at most once:
       a. M1R reached and not consumed:
            consume M1R
            request partial close of floor(steps_at_entry / 2)   (may be 0)
            stop_state_intended := BREAKEVEN
       b. M2R reached and not consumed:
            consume M2R
            stop_state_intended := LOCKED_1R
       c. TARGET reached and not consumed:
            consume TARGET
            emit CLOSE_REQUESTED for ALL remaining steps, carrying
                 requested_level    := TARGET
                 observed_reference := bar open if gapped, else TARGET   (§12)
            pending_close_reason := TARGET
            position stays OPEN -- the domain does NOT mark it CLOSED   (§11.1a)
            RETURN.

  4. RECONCILE STOP
     If stop_state_confirmed != stop_state_intended:
        request the modification; apply on confirmation only. (§7.3, §16)

  5. position.last_evaluated_time := observation.time
```

## 11.1a Closure is confirmed, never assumed — clarification

**[DECISION]** Detecting an exit condition and closing a position are two
different things, separated by the broker. The canonical sequence is:

```
  evaluate()
      │  the domain detects the condition
      ▼
  CLOSE_REQUESTED                     (requested_level, observed_reference, steps)
      │  position is still OPEN, pending_close_reason is set
      ▼
  execution adapter builds the broker request
      │
      ▼
  broker / paper broker / replay adapter executes
      │
      ▼
  broker confirmation                 (CloseFilled: reason, fill price, steps)
      │
      ▼
  apply_broker_result()
      │
      ▼
  CLOSED                              (closure_reason, recorded fill)
```

**The domain must not claim `CLOSED` before broker confirmation.** This applies
to every closure cause — stop, target, and any protective rule adopted later —
and to a full close as much as to a partial.

**[DECISION]** Consequences, stated so they cannot be read two ways:

1. Between `CLOSE_REQUESTED` and confirmation the position is `OPEN`, holds its
   full `steps_remaining`, and its risk is real. Any position report, exposure
   calculation or concurrency check must count it.
2. `evaluate()` **never** sets `lifecycle = CLOSED`. Only `apply_broker_result`
   does, and only on a confirming result (§16).
3. A rejected close leaves the position `OPEN` with `pending_close_reason`
   intact, and the request is re-issued on the next observation (§16.2).
4. While `pending_close_reason` is set, no milestone is processed: the position
   is on its way out and must not also partial or promote its stop.
5. In paper and replay the adapter performs request and confirmation
   synchronously within one step, so the composed effect is the single
   transition §11.1 describes. That collapse is an adapter property, **not** a
   licence for the domain to short-circuit it.

**Why this clarification exists.** The Phase 4B contract tests found that §11.1
read as though the domain closed the position itself, which contradicts §16 and
MUST NOT #12 ("must not treat a rejected close as a closure"). The reading above
is the one that satisfies both, and it is now the specification rather than an
interpretation.

## 11.1b The domain does not price executions — clarification

**[DECISION]** The canonical state machine does **not** calculate the broker's
executable fill price, and never applies spread, slippage, commission or any
other cost.

| Layer | Produces | Owner |
|---|---|---|
| **Requested level** | The price the model asked for: the stop, or the target | **Domain** |
| **Observed reference** | The first price available at or beyond that level: the level itself, or the bar open when the bar gapped through it | **Domain** |
| **Executable price** | The reference adjusted for spread, slippage and any other cost, per the execution contract | **Execution adapter** |
| **Recorded fill** | What the broker actually reports, returned to the domain through `CloseFilled` | **Broker**, relayed by the adapter |

**[DECISION]** A `CLOSE_REQUESTED` event therefore carries `requested_level` and
`observed_reference` **only**. It carries no executable price, because the
domain has no basis on which to compute one.

**[DECISION]** The domain learns the realised price exactly once, from the
broker result, and stores it as the recorded fill. All statistics use that
value (§12.1).

**[REPO]** The cost model already lives in the execution layer
(`execution/fills.py` applies `spread + slippage` adversely on entry and exit).
Keeping it there also keeps `core` pure under CONVENTIONS §7, which is enforced
by an AST test — so this boundary is machine-checked rather than merely
documented.

**No broker-specific logic may be added to `core/trade_model.py`.**

## 11.2 The two policy choices inside it, named

**[DECISION] — adverse first.** When a stop and a favourable milestone are both
reachable in one observation and the true sequence is unknowable (§11.4), the
stop is taken.

**This is a policy choice, not a historical finding.** It is *not* adopted
because `paper_broker`'s `IntrabarPolicy.CONSERVATIVE` does the same, nor
because `trade_manager` checks the stop first. Those are the behaviours of two
artifacts this model explicitly demotes. It is adopted because an unknowable
sequence resolved in the favourable direction would systematically overstate
results, and a model that overstates results is not usable for research.

**[DECISION] — stop moves take effect from the next observation.** A stop moved
during evaluation *E* is not tested against *E*'s own range.

**Rationale.** Within bar *E* the range is already history. Testing the moved
stop against the same range would assert an order of events — "price reached 1R,
*then* retraced to entry" — that the bar cannot support, and would let a single
bar both promote and stop out a position using two different stop values. The
cost of this rule is explicit: a bar that reaches 1R and then genuinely
collapses to breakeven is not recognised until the following bar.

## 11.3 The nine required cases

Assume a BUY unless stated; SELL is the mirror.

**Reading the "outcome" column.** Per §11.1a the domain emits
`CLOSE_REQUESTED` and the position becomes `CLOSED` only once the broker
confirms. `CLOSED / STOP` below is shorthand for "closure requested with reason
`STOP`, and `CLOSED / STOP` after confirmation". No row licenses the domain to
close a position by itself.

| Case | Situation | Order applied | Partial? | Stop moves? | Remainder continues? | Outcome |
|---|---|---|---|---|---|---|
| **A** | 1R and SL both reachable | Stop first (step 2) | **No** | No | No | `CLOSED / STOP`, full quantity |
| **B** | 2R and SL both reachable | Stop first | No | No | No | `CLOSED / STOP`, quantity as it stood |
| **C** | TP and SL both reachable | Stop first | No | No | No | `CLOSED / STOP` |
| **D** | 1R and 2R reachable, no stop | M1R then M2R (step 3a, 3b) | **Yes**, `floor(steps/2)` | `ORIGINAL → BREAKEVEN → LOCKED_1R` | Yes | `OPEN`, stop `LOCKED_1R` effective next observation |
| **E** | 1R, 2R and TP all reachable | M1R, M2R, then TARGET | **Yes**, then the remainder closes | Both moves recorded, then irrelevant | No | `CLOSED / TARGET` |
| **F** | Partial already executed earlier; SL now reachable | Stop first | No (already done) | No | No | `CLOSED / STOP`, closing **only the remaining steps** |
| **G** | Gap through SL (`open < S`) | Stop first; reference per §12 | No | No | No | `CLOSED / STOP`. The request carries `requested_level = S` and `observed_reference = bar open`; the adapter prices it (§11.1b), so the fill is **not** S |
| **H** | Gap through TP (`open > TARGET`) | Step 3c; reference per §12 | Only if M1R also fired this observation | As per D | No | `CLOSED / TARGET`. Request carries `requested_level = TARGET` and `observed_reference = bar open`; the adapter prices it |
| **I** | Reversal protection and SL both reachable | **Deferred** (§10). If adopted: stop first, protection after, never before | — | — | — | — |

**[INFERENCE]** Cases A, B, C and F all collapse to the same rule — the stop
outranks every favourable event in the same observation — because the stop is
the only adverse event in the model.

## 11.4 Bar data versus event sequence

**[DECISION]** OHLC does not determine the path. A bar whose range spans the
stop, 1R and 2R is consistent with

```
open -> 1R -> 2R -> SL        and        open -> SL -> 1R -> 2R
```

and the recorded data cannot distinguish them.

**[DECISION]** The model therefore does not claim to reconstruct the sequence.
It applies the deterministic policy in §11.2 and **records that the observation
was ambiguous**, so that the proportion of ambiguous resolutions is measurable
and can be reported alongside any result.

**[REPO]** `execution/intrabar.py` already computes and records ambiguity
(`was_ambiguous`), and `IntrabarPolicy.TICK_DATA` raises rather than guessing.
The canonical model requires that an ambiguity flag exists and is recorded; it
does not inherit that module's policy as canonical.

**[DECISION]** Where tick data is available, the true sequence supersedes the
policy. The policy is a fallback for insufficient resolution, not a definition
of the market.

---

# 12. Gap Execution

## 12.1 The four-layer contract

**[DECISION]** Every exit distinguishes four prices. Conflating them is what
produced the historical defect where a stop reported a fill at a price that was
never traded (`trade_manager`, measured: price 2505 against a 2480 stop still
reported 2480.00).

| Layer | Definition | Computed by |
|---|---|---|
| **Requested level** | The price the model asked for: `S`, or `TARGET` | **Domain** |
| **Observed reference** | The first price actually available at or beyond the requested level | **Domain** |
| **Executable price** | The observed reference adjusted for execution costs, adversely | **Execution adapter** (§11.1b) |
| **Recorded fill** | What the broker (live) or the fill model (paper/replay) reports. **This is what the ledger stores and what all statistics use** | **Broker**, relayed to the domain |

**[DECISION]** The canonical state update always uses the **recorded fill**. The
requested level is never used as a fill price.

**[DECISION] — clarification.** The first two layers are the domain's whole
contribution. It emits them on the `CLOSE_REQUESTED` event and stops there. The
third and fourth belong to the execution adapter and the broker, and reach the
domain only through `apply_broker_result` (§11.1b, §16).

## 12.2 Stop gap

```
BUY   gapped if bar_open <  S          SELL  gapped if bar_open >  S
observed reference := bar_open if gapped else S
executable         := observed reference adjusted adversely for costs
```

**[DECISION]** A gapped stop fills **worse** than requested. The model must
never report otherwise.

## 12.3 Target gap

```
BUY   gapped if bar_open >  TARGET     SELL  gapped if bar_open <  TARGET
observed reference := bar_open if gapped else TARGET
executable         := observed reference adjusted adversely for costs
```

**[DECISION]** A gapped target fills **better** than requested, and the model
records that improvement rather than truncating it to the target. This
asymmetry with §12.2 is intentional and correct: both cases take the first
available price, which happens to be adverse for a stop and favourable for a
target.

## 12.4 Backtest approximation, stated as such

**[DECISION]** In replay, `bar_open` is an **approximation** of "the first price
available after the gap". It is not a claim about what a broker would have
filled. The approximation's error is bounded by the distance between the bar
open and the first tick, which the dataset does not contain.

**[REPO]** The paper broker already implements exactly this rule for both stops
and targets (`paper_broker:458-498`), and already annotates the reason with
`GAPPED through stop, filled at bar open`. The canonical model adopts the
**rule**; it does so as a decision, not by inheritance.

**[DECISION]** In live execution the broker's reported fill is authoritative and
replaces every approximation. The model must not second-guess it, and must not
reconstruct a "should have been" price.

## 12.5 Costs

**[REPO]** `execution/fills.py` applies `spread + slippage` adversely on entry
and, when `apply_spread_on_exit` is true (the default), on exit as well. Default
spread is `Pips(2.0)` = **$0.20** on gold; default slippage is zero.

**[DECISION]** The canonical model requires that costs be applied to entries and
exits through one shared cost model, and that the model be the *same object* in
paper and replay. Live costs are whatever the broker reports.

---

# 13. LIMIT_FVG Hand-off

**No change to the LIMIT_FVG implementation is made here.** This section states
how a filled resting order enters the canonical model.

```
L8 decision
   ↓  (strategy: side, intended entry, structural stop, tp_ratio)
PendingOrderIntent           -- broker-agnostic, no lots, no broker concepts
   ↓
PendingOrder                 -- execution layer owns the lifecycle
   ↓  limit reached on a bar strictly after the formation bar
LIMIT FILL                   -- fill price = limit, or bar open if gapped, cost-adjusted
   ↓
POSITION CREATED             -- *** R, levels and TP are frozen HERE ***
   ↓
TRADE MANAGEMENT             -- §11 evaluation, from this bar onward (R1)
```

| Question | Canonical rule | Class |
|---|---|---|
| When is R calculated? | At **position creation**, i.e. at fill — never at intent time | [DECISION] |
| Which price is the entry price? | The **actual fill price**: the limit, or the bar open if the bar gapped through it, in both cases cost-adjusted | [DECISION]; matches `paper_broker:362-370` [REPO] |
| Original SL source | `intent.stop_loss`, the structural stop, **unchanged by the fill** | [DECISION] |
| Final TP | **Recomputed** at fill: `entry ± tp_ratio × R` (§4.2). Differs from today's carried `intent.take_profit` | [DECISION] — behaviour change |
| Position quantity | The volume fixed at submission, converted to steps (§5) | [DECISION] |
| Does the formation/decision bar matter? | Yes, as a **timing guard only**: a resting order may not fill on its formation bar | [REPO] `PendingOrder.may_fill_on` |
| May management occur on the fill bar? | **Yes.** The position exists from the fill onward and is exposed to the rest of that bar's range | [REPO] R1, `PHASE_4A_R1_SAME_BAR_EXIT_MEASUREMENT.md` |
| Same-bar fill and SL/TP | Handled by the normal §11 algorithm on the fill bar, with the stop snapshot = `ORIGINAL`. Adverse-first applies | [DECISION] |
| Pending → position state | The pending lifecycle (`PendingState`) and the position lifecycle are **separate machines**. `FILLED` is terminal for the order and is the *creation event* for the position | [REPO] + [DECISION] |
| Does an unfilled order have trade-management state? | **No.** No R, no levels, no stop state, no quantity accounting. A pending order that never fills produces no position record | [DECISION] |
| A fill that invalidates geometry | Rejected, not clamped (§4.3) | [DECISION] |

**[REPO]** Expiry, zone invalidation and cross-session cancellation remain
**disabled experimental controls** (`PHASE_4A_STEP4_DECISION_EVIDENCE.md`).
This specification does not change that and does not depend on it: those rules
govern whether a fill happens, not what happens afterwards.

---

# 14. Multiple Positions

| Question | Canonical rule | Class |
|---|---|---|
| Positions per accepted signal | **Exactly one.** A signal that is accepted creates one position; nothing splits a signal into several | [DECISION] |
| Multiple positions simultaneously | **Yes**, each with a fully independent state machine. No shared state, no netting of R, no cross-position stop logic | [DECISION] |
| Multiple pending orders | **Yes** | [REPO] measured in the LIMIT_FVG experiment |
| Several positions in the same direction | **Permitted by the model**; limited only by the concurrency cap | [DECISION] |
| Opposing positions simultaneously | **[UNRESOLVED]** | — |
| Concurrency cap | A **configuration parameter**, not a model rule. Current values agree at 3: `main.py:63`, `main_production.py:141`, `backtest/baseline.py:718` | [REPO] configuration ≠ canon |

## 14.1 The unresolved item

**[UNRESOLVED]** Whether opposing positions may be held simultaneously cannot be
decided from this repository. On a **netting** account the broker would offset
them into a single position, silently invalidating both positions' R, stop state
and milestone flags; on a **hedging** account they coexist. Nothing in the
repository records which account type is targeted, and there is no live account
metadata to inspect under the read-only constraint.

**What must be decided:** the account model. **Until it is,** an implementation
**must not** open an opposing position while one is open, because on a netting
account the canonical state would be provably wrong.

---

# 15. Idempotency

## 15.1 Required per-position state

**[DECISION]** The minimum state that makes repeated evaluation safe:

| Field | Purpose |
|---|---|
| `position_state` | `OPEN` / `CLOSED` — a closed position is never evaluated |
| `steps_at_entry` | Denominator of the 50 % rule; immutable |
| `steps_remaining` | Current quantity |
| `entry_price`, `original_stop_price`, `R` | Immutable geometry |
| `M1R`, `M2R`, `TARGET` | Immutable levels |
| `milestones_consumed` | Set; each milestone at most once |
| `stop_state_intended`, `stop_state_confirmed` | §7.3 |
| `last_evaluated_time` | Monotonicity guard |

## 15.2 Guarantees

**[DECISION]** A repeated or out-of-order evaluation **must not**:

| Scenario | Required behaviour |
|---|---|
| Price stays above 1R for 10 bars | The partial fires on the **first** bar only; the other nine produce no quantity change |
| 1R already executed | `M1R ∈ milestones_consumed` → never re-evaluated |
| 2R already executed | Same |
| Stop already at breakeven | The move is not re-requested once confirmed; while unconfirmed it is re-requested **to the same price** — idempotent by construction |
| Partial already completed | `steps_remaining` already reflects it; no second partial is possible because the milestone is consumed |
| TP already closed the position | `position_state == CLOSED` → evaluation is a no-op |
| The same bar is replayed | `observation.time <= last_evaluated_time` → no-op |

**[MEASURED] The failure this rule exists to prevent is real:** the historical
`trade_manager` emits `CLOSE_ALL` / `CLOSED_SL` when re-called on a position
whose quantity is already zero, because its stop check is not gated on remaining
quantity (`PHASE_4B_DD1_CANONICAL_TRADE_MANAGER.md` §16).

**[DECISION]** Evaluation is a **pure function** of
`(position_state, observation)` returning `(new_state, events)`. It performs no
I/O, reads no clock, and consults no global state. This is what makes replay
deterministic and the equivalence test of §18 possible.

---

# 16. Broker Failure Semantics

## 16.1 The four layers

**[DECISION]**

```
INTENT             what the model decided        (e.g. "close 3 steps at 1R")
   ↓
EXECUTION REQUEST  what the adapter sent         (broker-specific)
   ↓
BROKER RESULT      what came back                (filled / partial / rejected / error)
   ↓
CANONICAL STATE    what the model now believes   (updated ONLY from the result)
```

**[DECISION]** The canonical state is **never** updated optimistically from an
intent. Quantity and stop protection are statements about the world, and the
broker is the authority on the world.

**[REPO]** In paper and replay the adapter is the paper broker, whose results
are deterministic and always successful, so the two collapse — which is why the
distinction must be specified now rather than discovered at live wiring.

## 16.2 Required behaviour per failure

| Failure | Canonical behaviour | Class |
|---|---|---|
| **Partial close rejected** | Milestone stays consumed; `steps_remaining` unchanged; the position continues with more quantity than the ratio implies; the divergence is **recorded as an anomaly**. No retry in this version | [DECISION] |
| **Broker fills less than requested** | `steps_remaining` := broker-reported remainder. The broker wins | [DECISION] |
| **Stop modification rejected** | `stop_state_confirmed` does **not** advance. Re-requested on the next evaluation, to the same price. The position is treated as protected at the confirmed level until then | [DECISION] |
| **Target modification rejected** | Same pattern. If the target cannot be set, the model still closes on reaching it by its own evaluation — the broker-side target is an optimisation, not the mechanism | [DECISION] |
| **Position close rejected** | The position stays `OPEN` with its state unchanged and the close is re-requested on the next evaluation. It **must not** be marked `CLOSED` on an unconfirmed close | [DECISION] |
| **Stale position** (broker state older than the model's) | The broker's view is authoritative; the model reconciles and records the correction | [DECISION] |
| **Broker reports a different remaining quantity** | Adopt the broker's quantity, record the discrepancy as an anomaly. Never reconcile silently | [DECISION] |
| **Position disappeared from the broker** | `CLOSED` with reason `EXTERNAL`; never re-opened; recorded | [DECISION] |
| **Duplicate management event** | Prevented by §15 | [DECISION] |

**[DECISION] Deferred:** retry policy, backoff, and how many consecutive
rejections constitute an error condition. The model defines *what the state
means* after a failure, not *how hard to try*.

---

# 17. Position Lifecycle

**[DECISION]** Derived, not copied from the illustrative example.

```
  ┌──────────────────────────────────────────────────────────────┐
  │ ORDER LIFECYCLE  (execution layer owns it)                   │
  │                                                              │
  │   PENDING ──reached, bar > formation bar──► FILLED ──────────┼──┐
  │      │                                                       │  │
  │      ├── EXPIRED       (disabled control) [REPO]             │  │
  │      ├── INVALIDATED   (disabled control) [REPO]             │  │
  │      ├── CANCELLED     (disabled control) [REPO]             │  │
  │      └── REJECTED      (geometry invalid at fill, §4.3)      │  │
  │                                                              │  │
  │   A market entry starts at FILLED; it has no PENDING phase.  │  │
  └──────────────────────────────────────────────────────────────┘  │
                                                                    │
       creation event ──────────────────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ POSITION LIFECYCLE  (trade-management domain owns it)        │
  │                                                              │
  │   OPEN ──stop reached────┐                                   │
  │     │ ──target reached───┤                                   │
  │     │                    ▼                                   │
  │     │          OPEN + pending_close_reason                   │
  │     │          (closure REQUESTED, not yet a closure)        │
  │     │                    │                                   │
  │     │       broker confirms (CloseFilled)                    │
  │     │                    ▼                                   │
  │     │            CLOSED / STOP | TARGET                      │
  │     │                                                        │
  │     │       broker rejects -> stays OPEN, pending_close_     │
  │     │       reason intact, re-requested next observation     │
  │     │                                                        │
  │     │ ──broker says it is gone────► CLOSED / EXTERNAL        │
  │     │ ──replay dataset ends───────► CLOSED / END_OF_DATA     │
  │     │ ──operator or shutdown──────► CLOSED / MANUAL          │
  │     │                                                        │
  │     └── stays OPEN through: M1R (quantity falls), M2R,       │
  │         stop promotions, failed partials, failed modifies,   │
  │         and an outstanding close request                     │
  └──────────────────────────────────────────────────────────────┘
```

**[DECISION]** Key properties:

- The two machines are **separate**. `FILLED` is terminal for the order and is
  the creation event for the position; no state is shared.
- A failed fill produces **no** position and therefore no trade-management state.
- `CLOSED` is terminal and absorbing. There is no reopening, no resurrection
  from a broker report, and no transition out of it.
- The three disabled pending-terminal states remain defined and unproduced
  **[REPO]**; this specification neither activates nor removes them.

---

# 18. Live / Backtest Equivalence

## 18.1 The layering contract

**[DECISION]**

```
  STRATEGY                     side, intended entry, structural stop, tp_ratio
      │                        knows: market structure
      │                        knows NOT: lots, brokers, bars, costs
      ▼
  TRADE INTENT                 broker-agnostic request object
      │
      ▼
  EXECUTION ADAPTER            lots, order ids, requests, results, cost model
      │  ▲                     live | paper | replay -- three adapters, one interface
      ▼  │
  BROKER / PAPER BROKER / REPLAY SOURCE
         │  broker results (authoritative)
         ▼
  CANONICAL TRADE STATE MACHINE     §§4-17, pure, deterministic
      │
      ▼
  LEDGER                       every event, every ambiguity flag, every anomaly
```

## 18.2 What belongs where

| Layer | Owns | Must not contain |
|---|---|---|
| **Strategy** | Entry decision, side, intended entry, structural stop, `tp_ratio` selection | Lots, broker calls, bar iteration, cost assumptions |
| **Trade-management domain** | R, levels, milestone consumption, stop-state progression, quantity arithmetic in steps, event emission, idempotency, and — for an exit — the **requested level** and **observed reference** only | **Any MT5 call. Any I/O. Any clock read. Any `pandas` dependence. Any knowledge of which adapter is running. Any spread, slippage, commission or other cost arithmetic. Any transition to `CLOSED` that the broker has not confirmed** |
| **Execution adapter** | Translating intents to requests, **computing the executable price** from the domain's observed reference via the cost/fill model, reporting results, order ids | Strategy logic, milestone rules, R |
| **Broker** | Authoritative fills, quantities, rejections. **The only source of a `CLOSED` position** | — |
| **Backtest / replay** | Ordered bars, driving evaluations, ledger assembly, determinism guarantees | Trade-management rules of its own |

**[DECISION]** The state machine must be the **same code** under all three
adapters. Not an equivalent implementation — the same one.

## 18.3 The equivalence test this enables

**[DECISION]** Equivalence is demonstrated, not asserted: driving the state
machine with the same ordered observations through two different adapters must
produce the **same ordered event stream**, comparable by fingerprint.

**[REPO]** The mechanism already exists — `decisions_fingerprint` hashes an
ordered decision stream, and `run_fingerprint` covers the ledger. An analogous
management-event fingerprint is the natural equivalence artifact.

**[DECISION]** Adapter-specific facts — fill prices, order ids, timestamps — are
**outside** the compared stream. What is compared is the sequence of canonical
events and state transitions.

---

# 19. Regime TP Consequences

**[REPO]** Values unchanged, from `entry_engine.detect_regime`, mirrored in
`backtest/baseline.py:336-341`:

| Regime | `tp_ratio` |
|---|---|
| MICRO_SCALP | 1.5 |
| DEAD_CALM | 1.5 |
| REGIME_SCALP | 2.0 |
| INTRADAY_SWING | 3.0 |

## 19.1 What each means under this model

| `tp_ratio` | Target vs 2R | Ladder actually experienced | `LOCKED_1R` reachable? |
|---|---|---|---|
| **1.5** | **Target below 2R** | `M1R` fires (partial + breakeven), then `TARGET` closes the remainder at 1.5R. `M2R` is never reached | **No** |
| **2.0** | **Target coincides with 2R** | Both are reachable in the same observation. By §6.4 `M2R` is processed first and promotes the stop to `LOCKED_1R`; `TARGET` then closes the remainder in the same evaluation, so the promotion has no effect on the outcome | Reached, but immaterial |
| **3.0** | Target above 2R | Full ladder: partial and breakeven at 1R, `LOCKED_1R` at 2R, remainder closes at 3R | **Yes** |

**[MEASURED]** This matches the behaviour measured on both historical managers
across all four regimes (`PHASE_4B_DD1_TRADE_MANAGEMENT_DESIGN_OPTIONS.md`
§8.3), so the consequence is a property of the **ladder**, not of either
implementation.

## 19.2 Gross R multiple, as arithmetic only

**[INFERENCE]** If a position reaches its target and quantity divides evenly,
the gross outcome in R, **ignoring costs and making no claim about how often
targets are reached**:

| `tp_ratio` | Composition | Gross R if the target is reached |
|---|---|---|
| 1.5 | 50 % at 1R + 50 % at 1.5R | 1.25 R |
| 2.0 | 50 % at 1R + 50 % at 2.0R | 1.50 R |
| 3.0 | 50 % at 1R + 50 % at 3.0R | 2.00 R |

**This is arithmetic, not a performance statement.** It says nothing about win
rate, expectancy or profitability, and §5.2 shows the even split does not hold
at every size.

**[DECISION]** Per the strategy owner's instruction this is **not** classified
as a defect. It is a consequence of pairing fixed 1R/2R milestones with a
regime-scaled target, and whether to change it remains a separate strategy
question (DD5), explicitly **not** decided here.

---

# 20. `valid_rr` Boundary

**[DECISION] `valid_rr` remains a separate DD and is blocked until the canonical
model is finalised and a new baseline exists. It is unchanged by this
document.**

**[INFERENCE]** The canonical model does **not** make any of its three options
mechanically unavoidable:

- The model consumes `tp_ratio` as given and never inspects `rr`.
- `rr ≡ tp_ratio` is preserved by §4.2 — in fact it is made **exact** for every
  position, where today the carried target lets it drift.
- The gate sits at signal admission, before a position exists; this model begins
  at position creation.

**[MEASURED]** The gate currently rejects the two regimes whose `tp_ratio` is
1.5 — MICRO_SCALP and DEAD_CALM — which are exactly the regimes where §19 shows
`LOCKED_1R` is unreachable. **[INFERENCE]** These two facts share a cause
(`tp_ratio < 2`) but neither determines the other, and the coincidence must not
be read as an argument for any `valid_rr` option.

---

# 21. Risk-Sizing Boundary

**[DECISION]** Two distinct concepts, deliberately not merged:

| | Trade-management R | Position-sizing risk |
|---|---|---|
| Defines | Trade **geometry** — where the levels are | **Quantity** — how many lots |
| Unit | Price distance | Lots / money |
| Frozen | At position creation | At order submission |
| Owner | Trade-management domain | Risk/sizing domain |
| This document | Specifies it fully | **Does not decide it** |

**[DECISION]** The only contact point is that sizing produces a volume, which
this model immediately converts to **steps** (§5.1) and then owns.

**Explicitly not resolved here** and unchanged: DD11 (which broker field is
authoritative — `contract_size` vs `tick_value`, a 10× discrepancy), F4 (the
hardcoded `account_balance = 10000`), B6 (the two conflicting sizing formulas).
**[REPO]** These are independent of DD1 and of this specification.

---

# 22. State Machine

**[DECISION]** Three orthogonal machines plus immutable geometry.

```
=====================  IMMUTABLE AT CREATION  =========================
  side, entry_price, original_stop_price, R,
  M1R, M2R, TARGET, steps_at_entry, tp_ratio
=======================================================================

MACHINE 1 -- POSITION STATE
   Every arrow below is completed by a BROKER CONFIRMATION. evaluate()
   only ever emits CLOSE_REQUESTED and sets pending_close_reason; the
   transition itself is made by apply_broker_result.   (§11.1a)

┌────────┐  stop reached, confirmed ┌──────────────────────┐
│  OPEN  │────────────────────────►│ CLOSED / STOP        │
│        │  target reached, confirmed ├────────────────────┤
│        │────────────────────────►│ CLOSED / TARGET      │
│        │   broker: gone          ├──────────────────────┤
│        │────────────────────────►│ CLOSED / EXTERNAL    │
│        │   replay: data ends     ├──────────────────────┤
│        │────────────────────────►│ CLOSED / END_OF_DATA │
│        │   operator / shutdown   ├──────────────────────┤
│        │────────────────────────►│ CLOSED / MANUAL      │
└────────┘                         └──────────────────────┘
   CLOSED is terminal and absorbing.

MACHINE 2 -- STOP STATE     (orthogonal to Machine 1)
┌──────────┐  M1R consumed  ┌───────────┐  M2R consumed  ┌───────────┐
│ ORIGINAL │───────────────►│ BREAKEVEN │───────────────►│ LOCKED_1R │
│  = stop  │                │ = entry   │                │ = entry±R │
└──────────┘                └───────────┘                └───────────┘
   Forward only. Never backward. Never skipped. Never adverse.
   Tracked twice: stop_state_intended  (model)
                  stop_state_confirmed (broker) -- risk claims use this one.

MACHINE 3 -- QUANTITY
  steps_remaining : steps_at_entry ──M1R──► steps_at_entry - floor(steps_at_entry/2)
                                     └────► 0  on any closing event
   Monotonically non-increasing. Never replenished.
   floor(steps_at_entry/2) may be 0; the milestone still fires. (§5.2)

MILESTONE CONSUMPTION (a set, not a state)
  {} -> {M1R} -> {M1R, M2R} -> {M1R, M2R, TARGET}
   Each element added at most once, ever.
```

## 22.1 Worked transition example, `tp_ratio` 3.0, 0.06 lots

```
creation   OPEN | ORIGINAL | 6 steps | {}            R frozen, levels frozen
bar n+2    price reaches M1R
           -> consume M1R; close floor(6/2)=3 steps; intended=BREAKEVEN
           OPEN | ORIGINAL(confirmed) -> BREAKEVEN once acknowledged | 3 | {M1R}
bar n+5    price reaches M2R
           -> consume M2R; no partial; intended=LOCKED_1R
           OPEN | LOCKED_1R (on confirmation) | 3 | {M1R, M2R}
bar n+9    bar_low <= LOCKED_1R stop
           -> adverse first: emit CLOSE_REQUESTED for all 3 steps,
              requested_level = 2480, observed_reference = 2480 (no gap)
           OPEN + pending_close_reason=STOP | 3 steps | {M1R, M2R}
           *** still OPEN: the condition is detected, not executed ***

           adapter prices it, broker confirms CloseFilled(fill 2479.80)
           -> apply_broker_result
           CLOSED / STOP | 0 steps | {M1R, M2R} | recorded fill 2479.80
```

---

# 23. Decision Table

| Decision | Canonical rule | Source | Status |
|---|---|---|---|
| **R** | `abs(entry − original_stop)`, frozen at creation, entry = **actual fill** | Strategy owner Q1 + [DECISION] on which entry | **DECIDED** |
| **1R level** | `entry ± R`, direction-aware, computed once | [DECISION] | **DECIDED** |
| **1R partial** | Close `floor(steps/2)`; may be 0 at minimum size; milestone consumed either way | [DECISION] on rounding; owner Q2 on the ratio | **DECIDED** |
| **SL after 1R** | `BREAKEVEN` = entry, for the remaining quantity; **independent** of partial success | Owner Q4 + [DECISION] on independence | **DECIDED** |
| **2R level** | `entry ± 2R`, direction-aware | [DECISION] | **DECIDED** |
| **SL after 2R** | `LOCKED_1R` = `entry ± R`; no further partial | Owner Q5 | **DECIDED** |
| **Trailing** | None. Discrete ladder only; `config.py` constants inactive | Owner Q8 | **DECIDED / DEFERRED** |
| **Final TP** | `entry ± tp_ratio × R`, **recomputed at fill** | Owner Q12 + [INFERENCE] | **DECIDED** (behaviour change) |
| **Gap SL** | Domain emits requested level + observed reference (bar open when gapped); the adapter prices it; the fill is never the requested level and is worse than requested | Owner Q15 + [DECISION] §11.1b | **DECIDED** |
| **Gap TP** | Same split; better than requested is recorded as such | Owner Q16 + [DECISION] §11.1b | **DECIDED** |
| **Closure confirmation** | `evaluate` emits `CLOSE_REQUESTED` and sets `pending_close_reason`; the position stays `OPEN`; only a confirming broker result makes it `CLOSED` | [DECISION] §11.1a | **DECIDED** |
| **Executable price ownership** | Computed by the execution adapter, never by the domain; no cost arithmetic in `core/trade_model.py` | [DECISION] §11.1b | **DECIDED** |
| **Reversal protection** | **Not in the model.** Implementations must not add it | [UNRESOLVED] | **UNRESOLVED** |
| **Quantity** | Integer steps authoritative; lots derived at the broker boundary; floor rounding; broker-authoritative remainder | [DECISION] | **DECIDED** |
| **Event ordering** | Adverse first; milestones ascending; stop moves effective next observation; ambiguity recorded | [DECISION] | **DECIDED** |
| **LIMIT_FVG hand-off** | R, levels and TP frozen at fill; management may act on the fill bar; unfilled orders carry no management state | [DECISION] + [REPO] R1 | **DECIDED** |
| **Backtest equivalence** | One state machine, three adapters, identical event stream compared by fingerprint | [DECISION] | **DECIDED** |
| **Multiple positions** | One per signal; many concurrent; cap is configuration | [DECISION] | **DECIDED** |
| **Opposing positions** | Not permitted until the account model is known | [UNRESOLVED] | **UNRESOLVED** |
| **Idempotency** | Consumed-milestone set + monotonic evaluation time + terminal CLOSED | [DECISION] | **DECIDED** |
| **Broker failures** | Canonical state updates only from broker results; four named layers; retries deferred | [DECISION] | **DECIDED / partly DEFERRED** |
| **Time-based exit** | Not in the model | [DECISION] | **DEFERRED** |
| **`valid_rr`** | Untouched; separate DD; not made unavoidable by this model | [DECISION] | **BLOCKED** |
| **Risk sizing** | Separate domain; only contact point is volume → steps | [DECISION] | **BLOCKED / separate** |
| **Regime `tp_ratio` values** | Unchanged: 1.5 / 1.5 / 2.0 / 3.0 | [REPO] | **UNCHANGED** |
| **Ladder ordering (DD5)** | Consequences documented (§19); remedy not decided | [DECISION] to defer | **DEFERRED** |

---

# 24. IMPLEMENTATION CONTRACT

This section contains **no code**. It states what a future implementation must
satisfy, and is intended to be turned into tests **before** any production code
is changed.

## MUST

1. **One** canonical trade-management state machine exists, and production,
   paper and replay all drive **that same code**.
2. R is computed once, at position creation, from the **actual fill price** and
   the original stop, and is immutable thereafter.
3. `M1R`, `M2R` and `TARGET` are computed once, at creation, direction-aware,
   and stored. No level is recomputed during the position's life.
4. `TARGET == entry ± tp_ratio × R` holds for **every** position, by
   construction.
5. Quantity is held as integer steps; lots are derived only at the broker
   boundary.
6. The 1R partial closes `floor(steps_at_entry / 2)` steps, **exactly once**,
   and never more than half.
7. The 1R milestone is consumed even when the computed partial is zero steps.
8. The stop progresses `ORIGINAL → BREAKEVEN → LOCKED_1R`, forward only.
9. The stop price never moves adversely, under any rule, at any time.
10. `stop_state_intended` and `stop_state_confirmed` are tracked separately, and
    every statement about how protected a position is uses the **confirmed**
    value.
11. Within one evaluation the stop is tested **before** any favourable
    milestone.
12. A stop moved during an evaluation takes effect from the **next** observation.
13. Every exit distinguishes requested level, observed reference, executable
    price and recorded fill, and stores the **recorded fill**.
13a. `evaluate` emits `CLOSE_REQUESTED` and sets `pending_close_reason`; the
    position remains `OPEN` until a confirming broker result arrives, and only
    `apply_broker_result` may set `CLOSED` (§11.1a).
13b. A `CLOSE_REQUESTED` event carries `requested_level` and
    `observed_reference` and nothing else; the executable price is the
    adapter's (§11.1b).
13c. While `pending_close_reason` is set, no milestone is processed.
14. A gapped stop fills worse than requested; a gapped target fills better; both
    come from the observed reference.
15. Every ambiguous intrabar resolution is **flagged and countable**.
16. Canonical state is updated only from broker results, never optimistically.
17. Evaluation is a pure function of `(state, observation)` with no I/O, no
    clock read and no global state.
18. A `CLOSED` position is never evaluated, never reopened and never mutated.
19. Re-evaluating the same or an earlier observation is a no-op.
20. A management-event stream is produced that is comparable by fingerprint
    across adapters.

## MUST NOT

1. **Must not** contain MT5-specific calls anywhere in the state machine.
2. **Must not** read `TRAILING_STOP_ATR_TRIGGER`, `TRAILING_STOP_ATR_TRAIL`,
   `INTRADAY_MAX_HOLD_MINUTES`, `INTRADAY_MIN_HOLD_MINUTES` or
   `MAX_SLIPPAGE_PIPS`.
3. **Must not** implement reversal protection while §10 is unresolved.
4. **Must not** implement a time-based exit.
5. **Must not** implement continuous or ATR-based trailing.
6. **Must not** open an opposing position while one is open, until §14.1 is
   resolved.
7. **Must not** report a fill at a price that was not available — in particular,
   never at the requested stop level when the bar gapped through it.
8. **Must not** duplicate trade-management logic in more than one module; there
   is no second manager, no fallback path and no "legacy" branch.
9. **Must not** allow the execution layer to call back into the strategy.
10. **Must not** derive a milestone level without the side.
11. **Must not** couple the 1R stop move to the success of the 1R partial.
12. **Must not** treat a rejected close as a closure.
12a. **Must not** set `CLOSED` from `evaluate`, or from any path other than a
    confirming broker result — detecting an exit condition is not a closure
    (§11.1a).
12b. **Must not** compute an executable price, apply spread, slippage or
    commission, or otherwise price a fill anywhere in `core/trade_model.py`
    (§11.1b).
13. **Must not** silently reconcile a broker quantity mismatch; it is recorded
    as an anomaly.
14. **Must not** change `valid_rr`, risk sizing, SL construction, `tp_ratio`
    values or the LIMIT_FVG admission rules as part of implementing this model.

## DEFERRED

| # | Item | Revisit when |
|---|---|---|
| D1 | ATR-based continuous trailing | A trailing decision is taken on its own evidence |
| D2 | Time-based exit (240-minute maximum hold) | The model has a time concept and a reason for one |
| D3 | Retry policy for rejected partials, modifications and closes | Execution architecture is specified |
| D4 | `CLOSED_TIME` mapping in the existing `PositionState` enum | D2 is decided |
| D5 | Ladder remedy — whether milestones should scale with `tp_ratio` (DD5) | A strategy decision on §19 |
| D6 | Removal of the three disabled `PendingState` terminals | The expiry/invalidation experiments conclude |
| D7 | New canonical baseline reflecting the §4.2 target recomputation | Implementation is authorised and lands |

## UNRESOLVED

| # | Item | What must be decided | What would settle it |
|---|---|---|---|
| U1 | **Reversal protection** (§10) | Whether the model exits the remainder at a fixed offset above entry after 1R, and in what unit | Outcome evidence on positions that reached 1R and retraced — requires trades to exist |
| U2 | **Opposing positions / account model** (§14.1) | Netting or hedging | Account metadata, or an explicit product decision |
| U3 | **Session and weekend boundaries for open positions** | Whether an open position is closed, held or frozen across a session close (DD13 already open for resting orders) | A strategy ruling plus measurement of overnight gap exposure |
| U4 | **Anomaly severity** | Whether a broker quantity mismatch is a warning or a halt condition | Operational policy once live execution is contemplated |
| U5 | **Observed reference on a re-requested close** | A rejected close is re-issued on the next observation (§16.2), which is a **different** bar. Whether the re-request carries the original observed reference or the new observation's is not decided. It changes the recorded fill on any retry | A ruling, informed by how a real broker prices a re-submitted close |
| U6 | **Whether an unconfirmed stop promotion blocks the next milestone** | If `BREAKEVEN` is rejected and price then reaches 2R, it is not decided whether `M2R` may fire and advance `stop_state_intended` to `LOCKED_1R` while `stop_state_confirmed` is still `ORIGINAL`, or whether milestone processing pauses until the stop catches up | A ruling on whether the ladder is a price ladder or a protection ladder |

**[UNRESOLVED]** U5 and U6 are **deliberately left open** by this clarification.
The Phase 4B contract tests do not pin either, so no implementation choice is
pre-empted, and neither blocks the two matters §11.1a and §11.1b settle.

---

# 25. Remaining Unresolved Decisions

| # | Decision | Blocks | Class |
|---|---|---|---|
| R1 | Reversal protection in or out (§10) | The final shape of the closure-reason set; nothing else | [UNRESOLVED] |
| R2 | Netting vs hedging (§14.1) | Concurrent opposing positions only | [UNRESOLVED] |
| R3 | Session/weekend handling of **open positions** (§24 U3) | Interacts with DD13, which covers resting orders | [UNRESOLVED] |
| R4 | Anomaly severity policy (§24 U4) | Live operation only | [UNRESOLVED] |
| R5 | Ladder remedy, DD5 (§19) | `valid_rr` (DD15), through what `tp_ratio` controls | **DEFERRED by instruction** |
| R6 | `valid_rr`, DD15 (§20) | Nothing in this model | **BLOCKED** until a new baseline exists |
| R7 | Sizing: DD11, F4, B6 (§21) | Quantity **magnitude**, not quantity **representation** | **Independent of DD1** |
| R8 | Observed reference on a re-requested close (§24 U5) | The recorded fill on a retry only | [UNRESOLVED] |
| R9 | Whether an unconfirmed stop promotion blocks the next milestone (§24 U6) | Milestone processing while the broker lags | [UNRESOLVED] |

**[DECISION]** None of R1–R9 blocks writing the implementation tests for §24.
The MUST and MUST NOT lists are complete and testable as they stand; R1 and R2
appear there as prohibitions, which are themselves testable.

---

# 26. Verification

**Nothing was modified.** No `.py` file, no test, no fixture, no baseline
artifact, no parameter. The only new file is this document. No implementation
was started; neither manager was wired, repaired or deleted.

Read-only inspection covered `trade_manager.py`, `order_execution.py`,
`main.py`, `main_production.py`, `config.py`, `core/symbols.py`,
`execution/broker.py`, `execution/paper_broker.py`, `execution/fills.py`,
`execution/intrabar.py`, `entry_engine.py`, `backtest/baseline.py` and the
committed Phase 4A/4B documents, plus `git log` history.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

### At this revision (after the §11.1a / §11.1b clarifications)

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 523.3 s |
| Failures | **3** |
| Errors | **0** |
| Skipped | **84** |

The 84 skips and one of the failures are the canonical contract tests committed
at `f4bc150`: they skip while `core/trade_model.py` is absent, and
`CanonicalImplementationGate` fails to record that absence. The other two
failures are the pre-existing `test_layer_gate_logic` pair. **The clarification
changed no test and no test result.**

### At `adbbb05` (before the contract tests existed)

| Result | |
|---|---|
| Tests run | **664** |
| Duration | 553.8 s |
| Failures | **2** |
| Errors | **0** |

| Test | Status |
|---|---|
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_micro_scalp_l7_confidence_uses_55_threshold` | Pre-existing L2 H1-ATR mock failure; reproduces at `04a341d` |
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_pullback_gate_requires_real_pullback_detection` | Pre-existing L2 H1-ATR mock failure; reproduces at `04a341d` |

**Matches the expected status exactly** — `664 tests, 2 failures, 0 errors`, both
failures being the two named pre-existing ones. No test was modified or added.

---

*Specification only. No code, test, baseline or parameter changed. No implementation authorised. Stopping for review.*
