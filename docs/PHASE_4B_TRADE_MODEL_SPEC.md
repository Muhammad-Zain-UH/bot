# Phase 4B — formal trade model specification

**Documentation only.** No `.py`, test, strategy, RR, `tp_ratio`, `valid_rr`, TP,
SL, trade-management, parameter or baseline change. `baseline_004` untouched. No
optimisation, no ML, no profitability claim.

**Milestone reviewed:** the trade-management audit. `valid_rr` is **left
unchanged** and nothing is proposed to replace it.

## Statement classes — every claim below carries one

| Class | Meaning |
|---|---|
| **REPOSITORY EVIDENCE** | Directly readable in code, a docstring or a design document |
| **MEASURED** | Observed on data |
| **DESIGN DECISION** | Not established by the repository; someone must choose |
| **UNRESOLVED** | Insufficient evidence, and no basis on which to choose yet |

---

# A. Trade lifecycle specification

## A.1 The milestone model as the repository states it

**REPOSITORY EVIDENCE — `trade_manager.py`**, the fuller of the two
implementations. Its own docstrings describe the model:

| Question | Answer | Source |
|---|---|---|
| What happens at 1R? | Close 50 % of the position **and** move SL to breakeven | `check_partial_exit_1_1` returns `position_size_close: 0.5`, `new_stop_loss: entry_price` |
| Percentage closed at 1R | **50 %** | `position_size_close: 0.5`; `manage_open_trade` sets `position_size = 0.5` |
| SL at 1R | → **entry price** (breakeven); `sl_status = "breakeven"`; `new_risk: 0.0` | same function |
| What happens at 2R? | **No close.** SL trails only | `check_partial_exit_1_2` returns no `position_size_close` |
| Percentage closed at 2R | **0 %** | same |
| SL at 2R | → **entry + 1 × original_risk**, described as *"50 % of leg 2"*; `sl_status = "trailing"`; `locked_profit = 1R` | same |
| What does `TRAIL_SL` mean? | **Ambiguous between implementations** — see §A.2 | — |
| What happens at 3R? | Close **100 %** of what remains, at `take_profit` | `check_final_exit_1_3` returns `position_size_close: 1.0` |
| Is 3R always the final TP? | The code calls `take_profit` *"Full 1:3 TP level"* and labels the action `"TP (1:3 RR)"`, i.e. it **assumes** 3R | `manage_open_trade` docstring; `order_execution.py:271` |
| Ladder ordered regardless of regime? | **The repository never says.** The model is written as though `tp_ratio = 3` always | see §E |

**REPOSITORY EVIDENCE — R is measured from the original risk.** `manage_open_trade`'s
docstring for `original_stop_loss`: *"Original SL (**never changes**, for RR
calculation)"*, and it passes `original_stop_loss` — not the moved stop — into the
2R check. So the R unit is fixed at entry.

**REPOSITORY EVIDENCE — a fifth event exists that the design documents omit.**
`manage_open_trade` also calls `check_breakeven_stop(...)`, emitting
`CLOSE_BREAKEVEN_PROTECTION` when price reverses to a breakeven/trailing stop.
Neither design document mentions it.

### `tp_ratio` boundary behaviour

| Case | What the repository establishes |
|---|---|
| `tp_ratio > 2` | Ladder 1R < 2R < TP is ordered. Only INTRADAY_SWING (3.0). **REPOSITORY EVIDENCE** |
| `tp_ratio = 2` | The 3rd level **coincides** with the 2R trail. Which fires first is not stated. **UNRESOLVED** |
| `tp_ratio < 2` | The TP sits **below** the 2R trail level, so the 2R trail is unreachable — in `order_execution` the 3R check is ungated and would fire first; in `trade_manager` the 2R check is gated on 1R but not on TP. **REPOSITORY EVIDENCE** for the geometry; the intended resolution is **UNRESOLVED** |
| Should the ladder stay ordered? | **DESIGN DECISION.** Nothing states an invariant, and the milestones are hardcoded at 1R/2R while only the third scales |

## A.2 The two implementations disagree

**REPOSITORY EVIDENCE.** Both implement the same documented model and differ on
substance, not only structure:

| Aspect | `trade_manager` | `order_execution` |
|---|---|---|
| 1R: position | close 50 % | `CLOSE_50PCT` action |
| **1R: stop** | → **breakeven** | **no stop change at all** |
| 2R: position | none | none |
| **2R: stop** | → **entry + 1R** (locks 1R) | → **entry** (breakeven, locks 0) |
| 2R gating | 1R taken **and** `sl_status ∈ {original, breakeven}` | `exit_1_1` triggered |
| 3R | `CLOSE_ALL_REMAINING` at `take_profit` | `CLOSE_ALL` at `take_profit` |
| **Stop-loss check** | **explicit, evaluated first, returns immediately** | **absent** |
| Breakeven reversal protection | `check_breakeven_stop` | absent |
| R basis | `original_stop_loss`, explicitly fixed | `order["stop_loss"]` at creation |
| Remaining quantity | tracked as a fraction (1.0 → 0.5 → 0.0) | not tracked |

**Two consequences worth stating plainly.**

*`TRAIL_SL` means different things.* In `trade_manager` it locks 1R of profit; in
`order_execution` it moves to breakeven, locking nothing. Both are logged as
*"1:2 RR"*. **Which is intended is UNRESOLVED.**

*The wired implementation cannot close a loser.* `update_current_price` checks
only the three profit milestones — `stop_loss` appears once, inside the
`profit_locked` arithmetic, never in a comparison. **REPOSITORY EVIDENCE.** In
`main_production`'s path, a losing position would be closed only by a
broker-side stop, which is never placed.

## A.3 Lifecycle as specified

```
SIGNAL          entry_signal from L8
ENTRY           entry_price (M5/M1 close, or FVG midpoint on the momentum path)
INITIAL SL      min/max(sweep wick, displacement origin) -+ 3.00, or ATR fallback
                original_risk = |entry - initial SL|        <- the R unit, fixed here
FINAL TP        entry +- original_risk x tp_ratio
1R              entry +- 1.0 x original_risk   (hardcoded)
2R              entry +- 2.0 x original_risk   (hardcoded)
3R / TP         entry +- tp_ratio x original_risk
PARTIAL EXITS   50 % at 1R; 0 % at 2R; 100 % of remainder at TP
SL MOVEMENT     1R -> breakeven; 2R -> entry +- 1R        [per trade_manager]
FINAL EXIT      TP, stop, or breakeven-reversal protection
LEDGER          no production ledger exists; the backtest ledger records one
                full exit per position
```

---

# B. State machine — derived, not assumed

**REPOSITORY EVIDENCE** for the states: `trade_state` carries `position_size`,
`current_sl`, `sl_status ∈ {original, breakeven, trailing}`, `exit_1_1_taken`,
`exit_1_2_status ∈ {pending, sl_trailed, completed}`. `order_execution` carries
`OrderStatus ∈ {PENDING, SENT, OPEN, PARTIAL_CLOSE, TRAILING_SL, CLOSED, …}`.

The brief's example states are close but not exact: the repository distinguishes
**stop status** from **position status**, and the two are not the same axis.

```
                 ┌──────────┐
                 │ PENDING  │  order created, not executed
                 └────┬─────┘
                      │ execute / limit reached
                      v
                 ┌──────────┐   qty = 1.0   sl = original
                 │   OPEN   │
                 └────┬─────┘
          ┌───────────┼────────────────────────┐
          │ stop hit  │ 1R reached             │ TP reached
          v           v                        v
   ┌────────────┐  ┌──────────────────┐   ┌──────────┐
   │ CLOSED_SL  │  │ PARTIAL_1R       │   │ CLOSED_TP│
   └────────────┘  │ qty 0.5          │   └──────────┘
                   │ sl -> breakeven  │
                   └────┬─────────────┘
                        │ 2R reached
                        v
                   ┌──────────────────┐
                   │ TRAILING         │   qty 0.5
                   │ sl -> entry + 1R │   (trade_manager)
                   └────┬─────────────┘   or -> entry (order_execution)
             ┌──────────┼──────────────┐
             │ TP       │ trailing stop│ breakeven reversal
             v          v              v
       ┌──────────┐ ┌──────────┐ ┌──────────────────┐
       │ CLOSED_TP│ │CLOSED_SL │ │ CLOSED_BREAKEVEN │
       └──────────┘ └──────────┘ └──────────────────┘
```

**Specification fields** (derived from both implementations):

| Field | Source | Notes |
|---|---|---|
| `position_state` | `trade_state` / `OrderStatus` | the two implementations use different vocabularies |
| `remaining_quantity` | `trade_state["position_size"]` | a **fraction** (1.0/0.5/0.0), not lots — **REPOSITORY EVIDENCE** |
| `entry_price` | fill price | — |
| `initial_risk` | `|entry − original_sl|` | fixed at entry, never recomputed |
| `current_stop` | `trade_state["current_sl"]` | moves at 1R and 2R |
| `final_tp` | `entry ± initial_risk × tp_ratio` | — |
| `milestone_prices` | 1R, 2R hardcoded; 3rd = TP | — |
| `partial_exit_quantities` | 0.5 at 1R, 0 at 2R, remainder at TP | — |
| `stop_movement` | → breakeven at 1R, → entry+1R at 2R | divergent (§A.2) |
| `final_close` | TP, stop, or breakeven protection | — |

**UNRESOLVED:** whether remaining quantity should be a fraction or a lot size;
whether a partially closed position keeps one identity or becomes two.

---

# C. Production call graph

**A. Which implementation creates positions.** `order_execution.OrderExecutor.create_order`,
called from `main_production.execute_entry_signal`. `main.py` never creates orders.

**B. Which implementation manages positions.** Both exist:
`order_execution.update_current_price` (used by `main_production.manage_positions`)
and `trade_manager.manage_open_trade` (used by `main.manage_positions`).

**C. Reachable from `main_production.main()`** — AST traversal:
`execute_entry_signal` → `create_order` ✓, `execute_order` ✓;
`manage_positions` → `update_current_price` ✓.
**`manage_open_trade` — NOT reachable.** Imported at line 77, zero call sites.

**D. Reachable from `main.main()`:** `manage_positions` → `manage_open_trade` ✓.
`create_order` / `execute_order` — **not reachable**.

**E. Can either path execute the documented lifecycle?** **No.**

- `main_production`: **two blockers in series.** `execute_order` is called with
  `mt5_handler=None` and `simulation=CONFIG["demo_mode"]`, and `demo_mode` is
  `False` (`main_production.py:150`), so it returns
  `(False, "No MT5 handler provided and simulation disabled")` and `_OPEN_TRADES`
  is never populated. Independently, `manage_positions({})` is called with an
  empty dict, so the current price always falls back to `entry_price` and every
  milestone test reduces to `entry ≥ entry + risk`.
- `main.py`: manages positions it cannot create.

**F. Where they diverge:** §A.2 — stop movement at 1R and 2R, the meaning of
`TRAIL_SL`, the presence of a stop-loss check, breakeven protection, and whether
remaining quantity is tracked.

---

# D. Backtest vs production

**Verified — `PaperBroker` / `execution.broker`:**

| Property | Documented production model | Backtest |
|---|---|---|
| Partial exits | 50 % at 1R | **none** — every close is full |
| Stop to breakeven at 1R | yes | **no** |
| Trailing at 2R | yes | **no** |
| Milestone concept | 1R / 2R / 3R | **absent** |
| Exit resolution | price crossing a level | `resolve_intrabar`, one stop and one target |
| Terminal states | CLOSED_SL / partials / breakeven protection | `CLOSED_STOP`, `CLOSED_TARGET`, `CLOSED_TIME`, `CLOSED_END_OF_DATA`, `CLOSED_MANUAL` |
| Ambiguity handling | none specified | explicit `IntrabarPolicy`, counted |
| Remaining quantity | fraction, mutable | fixed volume, immutable |
| Breakeven reversal protection | present | absent |
| Stop-loss check | present in `trade_manager`, **absent** in the wired one | present |

**Evidence required before claiming a backtest result represents the documented
production strategy** — all four, none of which exists today:

1. The backtest must implement partial closes, so a position can exit in parts;
2. it must implement stop movement at 1R and 2R, using whichever `TRAIL_SL`
   semantics is chosen;
3. the intrabar policy must be extended to order a partial exit against a stop
   within one bar (§F);
4. a production run must exist whose trades can be compared against a replay of
   the same period — there are **MEASURED: zero** production trades, so no such
   comparison is currently possible in principle, not merely in practice.

Until then, **backtest results describe a single-exit strategy that production
does not implement.**

---

# E. Regime milestone table

| Regime | `tp_ratio` | Documented ladder | Actual milestones | Ordered? | Unreachable milestone | `valid_rr` permits? | Decisions (MEASURED) |
|---|---|---|---|---|---|---|---|
| INTRADAY_SWING | 3.0 | 1R → 2R → 3R | 1R, 2R, **3.0R** | **Yes** | none | **Yes** (3.0 ≥ 2.0) | 1,810 (11.5 %) |
| REGIME_SCALP | 2.0 | 1R → 2R → 3R | 1R, 2R, **2.0R** | **Tied** — TP coincides with the 2R trail | order between them **UNRESOLVED** | **Yes** (2.0 ≥ 2.0) | 6,492 (41.3 %) |
| MICRO_SCALP | 1.5 | 1R → 2R → 3R | 1R, 2R, **1.5R** | **No — inverted** | **2R trail unreachable** (TP fires first) | **No** — entry impossible | 5,121 (32.6 %) |
| DEAD_CALM | 1.5 | 1R → 2R → 3R | 1R, 2R, **1.5R** | **No — inverted** | **2R trail unreachable** | **No** — entry impossible | 2,312 (14.7 %) |

**MEASURED:** 13,925 of 15,735 decisions (**88.5 %**) fall in regimes where the
ladder is not strictly ordered. The ladder is coherent only for INTRADAY_SWING.

**Note the compounding:** the two regimes with an inverted ladder are exactly the
two where `valid_rr` already forbids entry. **REPOSITORY EVIDENCE** for both
facts; whether that is coincidence or a shared root cause in the choice of
`tp_ratio = 1.5` is **UNRESOLVED**.

---

# F. Event ordering

**REPOSITORY EVIDENCE exists for exactly one rule.** `manage_open_trade` checks
the stop **first** and returns immediately:

```python
if position_type == "BUY" and current_price <= trade_state["current_sl"]:
    ... CLOSE_ALL, "SL HIT" ...
    return result          # nothing else is evaluated on this tick
```

So **within one evaluation, the stop takes precedence over every milestone** — in
`trade_manager`. `order_execution` has no stop check, so it establishes nothing.

| Case | Repository position | Class |
|---|---|---|
| 1R and SL in one bar | `trade_manager`: **stop wins**, whole position closed | **REPOSITORY EVIDENCE** (that implementation only) |
| 2R and SL in one bar | same rule — stop wins | **REPOSITORY EVIDENCE** (same) |
| TP and SL in one bar | same rule in `trade_manager`; the backtest resolves it via `IntrabarPolicy` (CONSERVATIVE → stop) | **REPOSITORY EVIDENCE**, and the two agree |
| 1R and 2R in one bar | `manage_open_trade` evaluates both sequentially in one call, so **both can fire on one tick** | **REPOSITORY EVIDENCE** |
| 1R and TP in one bar | both can fire in one call: 50 % at 1R, then the remainder at TP | **REPOSITORY EVIDENCE** |
| Gap through a milestone | Nothing specifies a fill price. `trade_manager` reports `exit_price = the level`, not the gapped price | **DESIGN DECISION** |
| Gap through SL | `trade_manager` reports `exit_price = current_sl`, not the open. The backtest fills a gapped stop at the **bar open** | **Contradiction** — the two disagree; **DESIGN DECISION** |
| Partial exit then SL in one bar | Both can fire in one call, but the SL check runs **first** and returns — so on a single tick the partial is skipped entirely | **REPOSITORY EVIDENCE**, and arguably unintended: a bar that reaches 1R *and* later the stop is treated as a pure loss |

**DESIGN DECISION — the ordering the repository does not settle:** whether a bar
that touches both a milestone and the stop should be resolved by price path
(which OHLC cannot supply), conservatively against the position, or by the
existing `IntrabarPolicy`. The backtest already faces exactly this problem for a
single stop/target pair and resolves it explicitly; extending that to a
three-milestone ladder is not specified anywhere.

---

# G. Unresolved design decisions

1. **Which `TRAIL_SL` is intended** — lock 1R, or move to breakeven?
2. **Which implementation is canonical** — `trade_manager` or `order_execution`?
3. **Should the ladder remain ordered across regimes**, and if so, do the
   milestones scale with `tp_ratio` or does `tp_ratio` gain a floor?
4. **What happens when `tp_ratio = 2`** and TP coincides with the 2R trail?
5. **Gap fill price** for a milestone and for a stop — the two implementations
   already disagree with the backtest.
6. **Milestone-vs-stop ordering within a bar**, for a ladder rather than a pair.
7. **Should the backtest model the ladder at all**, or should production be
   simplified to what the backtest models?
8. **Is breakeven-reversal protection part of the model?** It is implemented and
   undocumented.
9. **Remaining quantity representation** — fraction or lots; one position or two.
10. **Should a losing trade be closed by management**, given the wired
    implementation cannot?

# H. Clearly evidenced implementation defects

| # | Defect | Evidence |
|---|---|---|
| 1 | `execute_order` cannot succeed: `mt5_handler=None`, `demo_mode=False` | `main_production.py:150, 1126-1129`; `order_execution.py:186` |
| 2 | `manage_positions({})` — empty dict, so current price ≡ entry price | `main_production.py:1431, 1175` |
| 3 | The wired manager has **no stop-loss check** | `order_execution.update_current_price` |
| 4 | 1R/2R hardcoded while the 3rd level scales → ladder inverted in 88.5 % of decisions | `order_execution.py:118-120`; §E |
| 5 | `trade_manager` imported by `main_production` and never called | AST reachability |
| 6 | Two implementations of one model, disagreeing on stop movement | §A.2 |
| 7 | Gap handling contradicts the backtest (level vs bar open) | §F |
| 8 | 5 % random failure injection in the simulation branch — non-deterministic | `order_execution.py:152` |

**Not a defect, corrected here:** I expected `check_partial_exit_1_2` to be
permanently disabled once 1R moved the stop to breakeven, since it derives
`original_risk` from the stop it is passed. **`manage_open_trade` passes
`original_stop_loss`, not the moved stop**, so the orchestrated path is correct.
The hazard is only latent for a direct caller — an API sharp edge, not a bug.

# I. Candidate architectural changes — NOT implemented

Listed for later approval. Each requires a decision from §G first.

1. Choose one canonical management implementation; delete or clearly demote the other.
2. Give the lifecycle a single owner — one entry point that both creates and manages.
3. Lift the model into a broker-agnostic state machine (§B) that production and
   backtest share, so they cannot diverge again.
4. Extend the backtest to model partial exits and stop movement — prerequisite
   for any claim that a backtest result represents the documented strategy.
5. Extend intrabar resolution to a milestone ladder.
6. Resolve the ladder-ordering defect, by whichever of the §G.3 routes is chosen.
7. Fix the two wiring blockers (§H.1, §H.2) — but only after 1 and 2, or the fix
   activates whichever implementation happens to be wired.
8. Remove the non-deterministic failure injection from any path a replay can reach.

**Every one of these changes behaviour and invalidates `baseline_004`.**

---

# J. `valid_rr` — status, unchanged

**REPOSITORY EVIDENCE, established and restated without modification:**

- the fixed-R TP model is deliberate — documented in two design documents and
  implemented in two modules, with `exit_1_3 = take_profit` holding only under it;
- `rr = reward / risk ≡ tp_ratio`, unconditionally, for any non-zero risk;
- `valid_rr` is therefore a **per-decision comparison of a configuration
  constant**, evaluating to a fixed boolean per regime before any market data is
  read;
- it does **not** measure market-derived reward/risk feasibility.

**No replacement is proposed, and none should be chosen before §G.1–G.3 are
settled**, because what "R" means downstream depends on them.

---

# Verification

**664 tests, 2 failures, 0 errors** — identical to `c5a8d6a`, `d6464b0`,
`a862408` and `8a4e010`. No test was modified; nothing here could invalidate
one, because nothing was changed. Both failures are the long-standing
`tests/test_layer_gate_logic.py` pair caused by the L2 H1-ATR gate, which
reproduces at `04a341d`.

---

*Specification only. Nothing changed, nothing implemented, no threshold or ordering chosen. Stopping for approval.*
