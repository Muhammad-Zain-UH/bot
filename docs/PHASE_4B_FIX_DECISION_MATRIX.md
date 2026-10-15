# Phase 4B — Fix & Decision Matrix

**Analysis and design only.** No `.py`, strategy, entry, SL, TP, RR, `valid_rr`,
risk-sizing, backtest or test change. No optimisation, no WFO, no Monte Carlo,
no ML, no new baseline, no profitability claim. `baseline_004` is **FROZEN**.

**Position in the sequence:**

```
EVIDENCE  ->  TRADE MODEL SPECIFICATION  ->  [ THIS DOCUMENT ]  ->  IMPLEMENTATION  ->  NEW CANONICAL BASELINE
                                              FIX / DECISIONS
```

## Evidence classes

| Tag | Meaning |
|---|---|
| **[REPO]** | Directly established by repository code or documentation |
| **[MEASURED]** | Established by replay or data measurement |
| **[DECISION]** | An explicit design choice is required |
| **[UNRESOLVED]** | Cannot be determined from existing evidence |
| **[FIX]** | Clear implementation correction; intended behaviour is established |
| **[KEEP]** | Investigated and found *not* to be a defect |
| **[BACKTEST]** | Required for model equivalence |
| **[EXPERIMENT]** | Requires controlled outcome evidence |

**Where evidence conflicts, the conflict is shown, not resolved.**

---

# 1. Executive summary

The investigation has produced an unusual result that shapes everything below:
**there is very little to fix and a great deal to decide.**

Almost every candidate that looked like a defect turned out to be either a
deliberate design the repository documents (the fixed-R target), a consequence of
an undecided question (`valid_rr`), or a genuine defect whose *correct* behaviour
the repository never states (the milestone ladder). Only a small set are
unambiguous implementation errors.

Three structural facts dominate:

1. **[REPO]** The trade lifecycle is **split across two entry points and neither
   completes it.** `main_production` creates orders and manages them through
   `order_execution`; `main.py` manages through `trade_manager` and creates
   nothing. The two managers **disagree on behaviour**, not merely on structure.
2. **[REPO][MEASURED]** The documented fixed-R milestone ladder is coherent for
   **one of four regimes**. 88.5 % of decisions sit in regimes where it is tied
   or inverted.
3. **[MEASURED]** The backtest has never simulated the documented model, and
   **zero production trades exist**, so no comparison between them is currently
   possible in principle.

**Consequence for sequencing:** fixing the wiring first would activate whichever
manager happens to be wired, before it has been decided which manager is correct.
The dependency order in §11 therefore puts decisions before repairs.

---

# 2. Full Fix & Decision Matrix

## Component → file key

The *Component* column names functions and symbols; this key gives the file for
each. Locations verified by `grep` at `7466ac6`.

| Component / symbol | File |
|---|---|
| `detect_fvg` (M5, L8), `calculate_entry_levels`, `_select_stop_anchor`, `buffer_pips`, `valid_rr`, `detect_regime`, `_evaluate_momentum_entry`, `_evaluate_pullback_entry`, `price_in_fvg` | `entry_engine.py` |
| `detect_fvg` (M15, POI) | `poi_engine.py` |
| `tp_pool`, `tp_score`, `tp_level` | `liquidity_engine.py` |
| `get_current_session`, `calculate_lot_size_for_symbol` | `risk_manager.py` |
| `execute_entry_signal`, `manage_positions(current_prices)`, `CONFIG["demo_mode"]`, `CONFIG["max_concurrent_trades"]`, `_OPEN_TRADES`, L0 DEAD-session gate | `main_production.py` |
| `manage_positions(open_trades, current_prices)` | `main.py` |
| `manage_open_trade`, `check_partial_exit_1_2`, `check_breakeven_stop`, `CLOSE_BREAKEVEN_PROTECTION`, `TRAIL_SL` (lock-1R meaning) | `trade_manager.py` |
| `execute_order`, `update_current_price`, `OrderType`, `TRAIL_SL` (breakeven meaning), 5 % random failure | `order_execution.py` |
| `PendingOrderIntent` | `core/types.py` |
| `Broker` protocol, `PendingOrder`, `PendingState`, `PositionState` | `execution/broker.py` |
| `PaperBroker`, `submit_limit_order`, `_fill_pending`, R1 | `execution/paper_broker.py` |
| `IntrabarPolicy` | `execution/intrabar.py` |
| `LIVE_TRADING_ENABLED` | `core/safety.py` |
| LIMIT_FVG replay branch | `backtest/replay_engine.py` |
| `max_open_positions`, `baseline_004` harness | `backtest/baseline.py` |

## A. Strategy / Entry

| Item | Component | Current behaviour | Evidence | Class | Depends on | Decision / fix required | Must NOT change |
|---|---|---|---|---|---|---|---|
| A1 | L1–L8 architecture | Seven admission gates; only `side` and sweep wicks reach construction | [REPO][MEASURED] | **KEEP** | — | None. Structure is as designed, if under-documented | Layer order |
| A2 | Direction / BOS flip | L1 sets `side`; L2 can invert it on a fresh break | [REPO] | **KEEP** | — | Works as commented. Rate not separable from the shared log | The flip itself |
| A3 | Sweep | Gates L5 **and** anchors the stop | [REPO] | **KEEP** | — | Its construction role should be documented | Behaviour |
| A4 | M1 CHoCH | Gates L8 trigger; sets pullback entry price via `m1[-2]` | [REPO] | **DECISION** | C-group | Whether CHoCH should price an entry or only confirm one | Both roles, until decided |
| A5 | FVG (L8) | 3-bar M5 detector; midpoint is the momentum entry price | [REPO] | **KEEP** | — | — | Detector |
| A6 | FVG invalid bounds returned | Returns `zone_low/high` when `fvg_found` is False | [REPO][MEASURED] 943 cases | **FIX** | none | Return no bounds when no gap exists | — |
| A7 | Displacement | Gates momentum trigger **and** anchors the stop | [REPO] | **KEEP** | — | Undocumented; should be recorded | Behaviour |
| A8 | Pullback entry | `m5[-2].close`, overridden by `m1[-2].close` | [REPO] | **DECISION** | A4 | Bar-index disagreement with momentum (`[-1]`) | Until A4 |
| A9 | Momentum entry / LIMIT_FVG | Resting limit at the FVG midpoint | [REPO] Phase 4A spec | **KEEP** | — | Implemented and tested | — |
| A10 | CHoCH entry-price override | **Removed** from the momentum path in Phase 4A | [REPO][MEASURED] 13/13 on the wrong side | **KEEP** | — | Already actioned; recorded as a strategy change | Do not reinstate |
| A11 | Formation vs later touch | Separated in the Phase 4A spec and implementation | [REPO] | **KEEP** | — | — | — |
| A12 | FVG invalidation | **None implemented** | [MEASURED] every zone rule fires at or after the fill | **DECISION** | C-group | Must be non-geometric, or absent | Do not import POI's 50 % rule |
| A13 | Pending-order creation | On the formation bar, from `PendingOrderIntent` | [REPO] | **KEEP** | — | — | — |
| A14 | Pending-order fill | Direction-aware reach; earliest bar N+1 | [REPO] | **KEEP** | — | — | Timing invariant |
| A15 | Pending-order expiry | **Disabled — experimental control** | [REPO] labelled | **EXPERIMENT** | D-group, E-group | Cannot be evidence-based until fills exist | Not a live policy |
| A16 | Cross-session pending | **Survives — experimental control** | [MEASURED] 19 % cross a session, 2.6 % a weekend | **DECISION + EXPERIMENT** | A17 | Decide jointly with expiry | Not a live policy |
| A17 | DEAD/closed session | L0 gate exists **only in `main()`**, not in the decision path | [REPO] AST; [MEASURED] 1,380 Dead decisions reached L1 | **DECISION** | — | Does the prohibition bind a resting order or only a new decision? | — |
| A18 | DEAD window disagreement | Gate says 22:00–03:00; `get_current_session` says 21:00–24:00 | [REPO] | **FIX** | A17 | Make them agree; which one is correct is part of A17 | — |
| A19 | `price_in_fvg` | Removed from the trigger; still computed and returned | [REPO][MEASURED] co-occurred 1/1,265 | **KEEP** | — | Retained as a diagnostic by decision | Do not re-add to the trigger |
| A20 | `detect_regime` session label `"LondonNewYork"` | MICRO_SCALP admits `session in {"Asian", "London", "LondonNewYork"}`; `get_current_session` never returns `"LondonNewYork"`, so in New York MICRO_SCALP needs the kill zone | [REPO][MEASURED] `TestLondonNewYorkIsADeadSessionLabel` enumerates every hour | **DECISION** | A17 | Removing the label changes nothing; replacing it with `"NewYork"` changes which decisions reach MICRO_SCALP. Which was intended is **[UNRESOLVED]** | Do not substitute `"NewYork"` silently |

## B. Risk / Geometry

| Item | Component | Current behaviour | Evidence | Class | Depends on | Decision / fix required | Must NOT change |
|---|---|---|---|---|---|---|---|
| B1 | Price vs pip units | Thresholds commented as pips, compared in price units | [REPO] U1–U12 | **FIX** | B2 | Migrate through `core.units` as one coherent change | Piecemeal edits |
| B2 | Stop buffer | `buffer_pips = 3.0` subtracted from a price → **$3.00** | [REPO][MEASURED] 29.4 % of median risk | **FIX** | — | Correct the unit. **Changes construction** | — |
| B3 | Stop construction | `min/max(sweep wick, displacement origin) ∓ buffer`; ATR fallback | [REPO] | **KEEP** | — | Parameters named `structure_*` are fed a single candle — naming defect only | Anchors |
| B4 | Entry price | M5/M1 close or FVG midpoint | [REPO] | **KEEP** | A4/A8 | — | — |
| B5 | Risk calculation | `|entry − stop|`, fixed at entry | [REPO] explicit | **KEEP** | — | — | The R basis |
| B6 | Position sizing — two formulas | `risk_manager`: `risk/(stop×10.0)`; `main_production` fallback: `risk/(stop×100.0)` | [REPO] | **FIX** | B7 | **They differ by 10×.** One is wrong | Do not pick before B7 |
| B7 | Broker contract size vs tick value | `contract_size=100`, `tick_value=0.1` → `money_per_price_unit=10` | [REPO] broker metadata | **DECISION** | — | Which broker field is authoritative. B6 follows | — |
| B8 | Hardcoded balance | `execute_entry_signal(..., account_balance=10000)`; **called without it** at `:1424` | [REPO] | **FIX** | — | Query the account. Currently every size is computed from a fictional 10,000 | — |
| B9 | `risk_pct` in `calculate_entry_levels` | Declared, **never read** | [REPO] AST | **FIX** (removal) | — | Remove, or wire | — |
| B10 | `risk_manager` sizing comments | Comments contradict each other and the code | [REPO] | **FIX** | B7 | Correct once B7 decides | — |
| B11 | `tp_ratio` | Regime constant → TP multiple | [REPO] | **KEEP** | — | Classified as the final TP multiple, not a milestone controller | — |
| B12 | Fixed-R TP semantics | **Deliberate**, documented in 2 docs and 2 modules | [REPO] | **KEEP** | — | Established | Do not reinterpret |
| B13 | `valid_rr` | `rr ≡ tp_ratio`; per-decision comparison of a constant | [REPO][MEASURED] | **DECISION** | B12, C-group | See §6 | **Do not change** |
| B14 | `tp_pool` discarded | Validated on side and score, never on distance; never reaches L8 | [REPO] | **KEEP** | — | Feasibility check, not a discarded target. Naming is the defect | Do not use to redefine RR |
| B15 | Market-derived vs fixed-R | Fixed-R established | [REPO] | **KEEP** | — | Closed | Do not reopen without new evidence |
| B16 | `tp_pool` naming | `tp_pool`/`tp_score`/`tp_level` assert a role the code does not give them | [REPO] | **FIX** (rename) | B14 | Rename to reflect feasibility | Behaviour |

## C. Trade Management

**The two managers are not duplicates.** They disagree on substance:

| Aspect | `trade_manager` | `order_execution` (wired) | Class |
|---|---|---|---|
| 1R position | close 50 % | `CLOSE_50PCT` action | agree |
| **1R stop** | → breakeven | **no stop change** | **CONFLICT** |
| **2R stop** | → entry + 1R (locks 1R) | → entry (locks 0) | **CONFLICT** |
| **Stop-loss check** | explicit, first, returns | **absent** | **CONFLICT** |
| Breakeven reversal | `check_breakeven_stop` | absent | **CONFLICT** |
| Remaining quantity | fraction 1.0/0.5/0.0 | not tracked | **CONFLICT** |
| R basis | `original_stop_loss`, explicit | stop at creation | agree in effect |

| Item | Component | Current behaviour | Evidence | Class | Depends on | Decision / fix required | Must NOT change |
|---|---|---|---|---|---|---|---|
| C1 | 1R milestone | Hardcoded `entry ± 1×risk` | [REPO] | **KEEP** | — | Level itself is unambiguous | — |
| C2 | 2R milestone | Hardcoded `entry ± 2×risk` | [REPO] | **KEEP** | C5 | Level unambiguous; reachability is not | — |
| C3 | Final TP | `entry ± tp_ratio×risk`; also `exit_1_3` | [REPO] | **KEEP** | — | — | — |
| C4 | Partial-close quantities | 50 % at 1R, 0 % at 2R, remainder at TP | [REPO] | **KEEP** | D1 | Established by `trade_manager` only | — |
| C5 | **Ladder ordering** | 1R/2R hardcoded while the 3rd scales | [REPO][MEASURED] 88.5 % not ordered | **FIX + DECISION** | B11, D1 | Defect is clear; the **remedy** is a decision — scale the milestones, or floor `tp_ratio` | Do not pick silently |
| C6 | Remaining quantity | Fraction in one manager, untracked in the other | [REPO] | **DECISION** | D1 | Fraction or lots; one position or two | — |
| C7 | Original stop | Fixed at entry, threaded correctly | [REPO] | **KEEP** | — | See §5 — a suspected defect that was disproved | — |
| C8 | Breakeven stop | 1R → breakeven (`trade_manager` only) | [REPO] **CONFLICT** | **DECISION** | D1 | Which manager's semantics | — |
| C9 | Trailing stop / `TRAIL_SL` | **Two meanings**, both logged "1:2 RR" | [REPO] **CONFLICT** | **DECISION** | D1 | Lock 1R, or move to breakeven | — |
| C10 | Breakeven reversal protection | `CLOSE_BREAKEVEN_PROTECTION`, implemented, **undocumented** | [REPO] | **DECISION** | D1 | Is it part of the model at all? | Do not delete before deciding |
| C11 | **Stop-loss comparison** | **Absent** from the wired manager | [REPO] | **FIX** | D1 | It cannot close a loser. Clear defect — but fix in whichever manager becomes canonical | — |
| C12 | Stop vs milestone ordering | `trade_manager`: stop first, returns immediately | [REPO] | **KEEP** | D1 | Established for one manager only | — |
| C13 | Milestone vs milestone | 1R and 2R can both fire in one call | [REPO] | **KEEP** | — | — | — |
| C14 | TP vs stop ordering | `trade_manager` stop-first; backtest `IntrabarPolicy` CONSERVATIVE → stop | [REPO] agree | **KEEP** | — | — | — |
| C15 | Same-bar 1R-then-stop | Stop check returns first, so the partial is skipped entirely | [REPO] | **DECISION** | C12 | Arguably unintended; needs a ruling | — |
| C16 | Gap through stop | `trade_manager` exits at the *level*; backtest at the *bar open* | [REPO] **CONFLICT** | **DECISION** | D1, E-group | Which is correct | — |
| C17 | Gap through milestone | Fill price unspecified | [UNRESOLVED] | **DECISION** | C16 | — | — |

## D. Execution Architecture

| Item | Component | Current behaviour | Evidence | Class | Depends on | Decision / fix required | Must NOT change |
|---|---|---|---|---|---|---|---|
| D1 | **Canonical manager** | Two managers, conflicting semantics, one wired | [REPO] | **DECISION** | — | The repository does **not** establish which is canonical, so this is a decision — **not** to be made on which looks better | Do not delete either yet |
| D2 | Lifecycle ownership | Split: `main_production` creates, `main.py` manages | [REPO] AST | **DECISION** | D1 | One entry point must own both | — |
| D3 | `execute_order` unreachable | `mt5_handler=None`, `demo_mode=False` → always False | [REPO] | **FIX** | D1, D2 | Clear defect — but fixing it activates whichever manager is wired | **Fix only after D1/D2** |
| D4 | `manage_positions({})` | Empty dict → current price ≡ entry price | [REPO] | **FIX** | D1, D2 | Clear defect, same ordering caveat | Same |
| D5 | `trade_manager` imported, never called | Superseded in the audited path | [REPO] | **DECISION** | D1 | Remove or adopt — follows D1 | — |
| D6 | 5 % random failure injection | `random.random() < 0.05` in the simulation branch | [REPO] | **FIX** | — | Non-deterministic; must not sit on any replayable path | — |
| D7 | `paper_broker` | Single full exits, `IntrabarPolicy` | [REPO] | **BACKTEST** | D1 | Must model the canonical manager | — |
| D8 | `PendingOrderIntent` / `PendingOrder` | Broker-agnostic intent; execution owns lifecycle | [REPO] | **KEEP** | — | Works as specified | — |
| D9 | Broker abstraction | `Broker` protocol; `submit_market_order`/`submit_limit_order` | [REPO] | **KEEP** | — | Live adapter is future work | — |
| D10 | Live execution wiring | `OrderType` has BUY/SELL only; no LIMIT | [REPO] | **DEFER** | D1–D4 | Needed only if live is ever enabled | `LIVE_TRADING_ENABLED` stays False |
| D11 | Position lifecycle | `PositionState` — 5 terminal states, all full closes | [REPO] | **BACKTEST** | D1, C4 | Needs partial states if the ladder is adopted | — |
| D12 | Pending lifecycle | `PendingState` — terminal states defined, none produced | [REPO] | **KEEP** | A12, A15 | Deliberate control | — |

---

# 3. FIX NOW

Clear implementation defects whose intended behaviour **is** established. Ordered
by dependency, not importance.

| # | Item | Why it is unambiguous | Blocked by |
|---|---|---|---|
| F1 | **A6** — `detect_fvg` returns bounds when no gap exists | A zone that does not exist has no bounds. Caused `price_in_fvg` to be true 943 times with no FVG | none |
| F2 | **B9** — `risk_pct` declared and never read | Dead parameter on a construction function | none |
| F3 | **D6** — 5 % random failure injection | Non-determinism in the simulation execution path. The replay does not take that path today, but any replay of production execution would, and it contradicts the reproducibility guarantee | none |
| F4 | **B8** — hardcoded `account_balance = 10000` | `execute_entry_signal` is called without a balance, so every size derives from a fictional account | none |
| F5 | **B16** — `tp_pool` naming | The name asserts a role the code does not implement, and it misled this project's own review | B14 (settled) |
| F6 | **A18** — DEAD-window disagreement | 22:00–03:00 vs 21:00–24:00 cannot both be right | A17 decides which |
| F7 | **B2 + B1** — unit migration | Thresholds compared in the wrong unit. Must be one coherent change | B7 for sizing units |
| F8 | **C11** — missing stop-loss check | A manager that cannot close a loser is unambiguously incomplete | **D1** |
| F9 | **C5** — ladder ordering defect | The defect is certain; the remedy is a decision | **C5-decision** |
| F10 | **D3 + D4** — the two wiring blockers | Both are clear defects | **D1, D2** |

**F8–F10 are listed as fixes but are gated.** Repairing wiring before choosing a
canonical manager would activate untested, conflicting semantics.

---

# 4. DESIGN DECISION REQUIRED

| # | Decision | Why the repository cannot answer it |
|---|---|---|
| DD1 | **Which manager is canonical** (D1) | Both implement the documented model; both are wired somewhere; neither is marked authoritative. Nothing in code, docs or history ranks them |
| DD2 | **Who owns the lifecycle** (D2) | Two entry points, each with half |
| DD3 | **`TRAIL_SL` semantics** (C9) | Lock 1R or move to breakeven — both implemented, both logged identically |
| DD4 | **Stop position at 1R** (C8) | Breakeven in one manager, unchanged in the other |
| DD5 | **Ladder-ordering remedy** (C5) | Scale milestones with `tp_ratio`, or floor `tp_ratio` above 2.0. Both fix it; they differ in what they change |
| DD6 | **`tp_ratio = 2` tie** | TP coincides with the 2R trail; precedence unstated |
| DD7 | **Breakeven reversal protection** (C10) | Implemented, undocumented — is it part of the model? |
| DD8 | **Remaining-quantity representation** (C6) | Fraction or lots; one position or two |
| DD9 | **Gap fill price** (C16/C17) | Level vs bar open — the managers and the backtest disagree |
| DD10 | **Same-bar 1R-then-stop** (C15) | Currently the partial is skipped; unstated whether intended |
| DD11 | **Broker field authority** (B7) | `contract_size` vs `tick_value` — a 10× difference, both from the broker |
| DD12 | **CHoCH's role** (A4/A8) | Confirmation only, or entry pricing; and which M1 bar index |
| DD13 | **Session binding for resting orders** (A17) | Does the DEAD prohibition bind a resting order or only a new decision? |
| DD14 | **FVG invalidation basis** (A12) | Must be non-geometric; nothing suggests what |
| DD15 | **`valid_rr`** (B13) | See §6 |
| DD16 | **`"LondonNewYork"` label** (A20) | A dead label either written in error for `"NewYork"` or left over from a retired session name. Nothing records which |

---

# 5. KEEP — investigated and disproved

| # | Suspicion | What the investigation found |
|---|---|---|
| K1 | "`tp_pool` is a discarded target" | **Withdrawn.** Fixed-R is documented in 2 docs and 2 modules; `exit_1_3 = take_profit` holds only under it. `tp_pool` is validated on side and score, **never on distance** — a feasibility check |
| K2 | "`check_partial_exit_1_2` is disabled once 1R moves the stop" | **False.** `manage_open_trade` passes `original_stop_loss`, not the moved stop. A latent API hazard for a direct caller, not an orchestration bug |
| K3 | "Only `side` and sweep wicks reach construction" | **Incomplete.** Displacement origin also anchors the momentum stop. Corrected in the design review |
| K4 | "The RR tautology caused the 1,265 L8 blocks" | **Withdrawn.** `raw_triggered` was already false at all 1,265; the gate blocked none of them |
| K5 | "No test covers the fill-bar skip" | **False.** `test_entry_bar_is_not_re_evaluated` pinned the old behaviour and failed the moment R1 landed |
| K6 | "L1–L8 is a confluence funnel" | Partly — real as admission, absent as construction. Not a defect, but not what the documents imply |
| K7 | `price_in_fvg` retained as a diagnostic | Deliberate; not dead code by accident |

---

# 6. `valid_rr` — evidence only, NO CHANGE

**Established, and restated without modification:**

- **[REPO]** `reward = risk × tp_ratio`, so `rr ≡ tp_ratio` for any non-zero risk.
  The value is independent of price, stop, target and every L1–L7 output.
- **[REPO]** The fixed-R TP model is deliberate (§5 K1), so `rr` is a **selected
  configuration multiple**, not a measured relationship.
- **[REPO]** `valid_rr = rr >= 2.0` therefore evaluates to a **fixed boolean per
  regime**, decided before any market data is read: always true for
  INTRADAY_SWING and REGIME_SCALP, always false for MICRO_SCALP and DEAD_CALM.
- **[MEASURED]** The four real XAUUSD LIMIT_FVG candidates — all MICRO_SCALP —
  were rejected by this gate. It is the current binding constraint.
- **[MEASURED]** A market-derived RR against `tp_pool` has a median of **0.25**;
  ≥ 2.0 on 1.26 % of candidates. Correcting the $3.00 buffer moves the median to
  0.34, so the gap is design, not only unit error.

**The three possible decisions, and what each would require. None is selected.**

| Option | What it would need |
|---|---|
| **1. Remove the gate** | A ruling that a chosen R needs no validation. Evidence required: a decision on DD5 (ladder) and DD15, plus a controlled experiment showing what the four candidates do once admitted — **[EXPERIMENT]** |
| **2. Replace with an attainability test** | A definition of "attainable" the repository does not contain. Would give `tp_pool` a real role. Evidence required: forward measurement of whether a fixed-R target is reached before the stop, which needs trades to exist — **[EXPERIMENT]**, blocked by D1–D4 |
| **3. Keep and justify the threshold** | A rationale for `2.0` that the repository does not contain, and acceptance that two regimes stay permanently unenterable. Evidence required: a stated risk preference — a **[DECISION]**, not a measurement |

**`valid_rr` must not be changed until DD1, DD2 and DD5 are settled**, because
what "R" means downstream depends on them.

---

# 7. BACKTEST ALIGNMENT

Every difference between production behaviour and the replay.

| # | Aspect | Production (documented) | Backtest | Evidence | Class | Depends on | Change required | Must NOT change |
|---|---|---|---|---|---|---|---|---|
| E1 | Pending orders | none — `OrderType` has BUY/SELL only | `PendingOrder` in `paper_broker` | [REPO] | **Intentional** — the backtest leads here | D10 | None now. A live adapter only if live is ever enabled | `LIVE_TRADING_ENABLED = False` |
| E2 | Limit fills | not implemented | direction-aware reach, earliest bar N+1 | [REPO] | **Intentional** | D10 | None now | `may_fill_on` timing guard |
| E3 | Fill timing | at signal price (`create_order`) | next bar open, or limit reach ≥ N+1 | [REPO] | **Required** — production fills at a price it cannot transact at (Q1) | DD1, DD2 | Production side; the backtest is already correct | `SimulatedFill` invariant `entry_bar_time > decision_bar_time` |
| E4 | Same-bar exits | no bar loop; not modelled | R1: fill bar evaluated | [REPO][MEASURED] | **Required** | DD1 | The canonical manager must be evaluated from the fill onward, as R1 does | R1 and its pinned regression fingerprints |
| E5 | **Partial exits** | 50 % at 1R (both managers) | **none** — single full exit | [REPO] | **Required** | DD1, DD8, D11 | Backtest models the canonical manager's partial; needs partial position states | Do not add before DD1 — it would model an unchosen manager |
| E6 | **Trailing** | at 2R, **two meanings** (C9) | **none** | [REPO] conflict | **Required** | DD1, DD3 | Model the chosen `TRAIL_SL` | Same |
| E7 | **Breakeven move** | at 1R in `trade_manager` only | **none** | [REPO] conflict | **Required** | DD1, DD4 | Model the chosen 1R stop rule | Same |
| E8 | **Reversal protection** | `CLOSE_BREAKEVEN_PROTECTION` in `trade_manager` only | **none** | [REPO] | **Unresolved** | DD7 | Model it only if DD7 adopts it | Do not delete before DD7 |
| E9 | Stop handling | present in `trade_manager`, **absent** in the wired `order_execution` | always present, `IntrabarPolicy` CONSERVATIVE | [REPO] conflict | **Required** | DD1 → F8 | Production side needs the check (F8); the backtest already has it | Backtest stop handling |
| E10 | Gap handling | `trade_manager` exits at the stop *level* | exits at the bar *open* | [REPO] conflict | **Unresolved** | DD9 | Align whichever side DD9 rules against | Do not change the backtest gap fill before DD9 |
| E11 | Intrabar ambiguity | polls one current price per cycle; events between polls are unobserved — a different ambiguity, not an absence of one | explicit policy, counted | [REPO] | **Required** | DD1 | Both sides need a stated rule for events the price sample cannot order | `IntrabarPolicy` default CONSERVATIVE |
| E12 | Position quantity | fraction 1.0/0.5/0.0 in `trade_manager`; untracked in `order_execution` | fixed volume, immutable | [REPO] | **Required** | DD8 | Representation follows DD8 | `SimulatedPosition` immutability until DD8 |
| E13 | Multiple positions | `_OPEN_TRADES` capped by `CONFIG["max_concurrent_trades"] = 3` | `max_open_positions = 3` | [REPO] | **Agree** — the caps match. Only difference: the backtest also rests pending orders beyond the cap | — | None | Both caps |
| E14 | Session transitions | L0 DEAD gate in `main()` only | no session gate | [REPO][MEASURED] 1,380 Dead decisions reached L1 | **Unresolved** | DD13 | Follows DD13 | `baseline_004` decision stream |

**Evidence required before claiming a backtest result represents the canonical
model:** E5, E6, E7, E9, E11 and E12 implemented; E8, E10, E14 decided; and a
production run whose trades can be compared against a replay of the same period.
**[MEASURED]** Zero production trades exist, so that comparison is currently
impossible in principle, not merely in practice.

---

# 8. EXPERIMENT REQUIRED

| # | Question | Why static evidence cannot answer it | Blocked by |
|---|---|---|---|
| X1 | Expiry period (A15) | Encodes how long a setup stays valid; choosing from the fill distribution would fit a parameter to an outcome | D1–D4, E-group |
| X2 | Cross-session survival (A16) | Costs measured (19 % / 8.6 % / 2.6 %) but the ruling needs outcome evidence | DD13, X1 |
| X3 | FVG invalidation basis (A12) | Every geometric rule fires at or after the fill; a non-geometric one has no precedent | X1 |
| X4 | `valid_rr` options 1 and 2 (§6) | Requires knowing what the four candidates do once admitted | DD1, DD2, DD5 |
| X5 | Whether partial exits are wanted at all | Documented, never executed — no evidence either way | D1, E5 |

---

# 9. DEFER — must NOT change yet

| # | Item | Why |
|---|---|---|
| Z1 | `valid_rr` | §6 — three open decisions upstream |
| Z2 | `tp_ratio` values | Changing them alters both admission and the ladder; DD5 first |
| Z3 | RR formula | Meaning depends on DD5 and DD15 |
| Z4 | TP construction | Fixed-R established; do not reopen |
| Z5 | SL anchors | Only the unit (B2) is wrong, not the anchors |
| Z6 | `manage_open_trade` wiring | D1 first, or the wrong manager activates |
| Z7 | Either manager's deletion | D1 first |
| Z8 | `LIVE_TRADING_ENABLED` | Stays `False` throughout |
| Z9 | `baseline_004` | **FROZEN** — see §12 |
| Z10 | POI 50 % fill rule | Must not be imported into L8 |
| Z11 | Layer order / L1–L7 gates | Out of scope for this phase |

---

# 10. DEAD / MISLEADING CODE — removal candidates

Objective 6 of the brief. **Nothing here is removed by this document.** Each row
states what would have to be verified first.

**Removal criterion, for every row.** A removal is only permitted when the
replay reproduces `baseline_004` **byte-identically**, including
`decisions_fingerprint`, and the full suite is unchanged. Where a row says a
removal is *behaviour-preserving*, that is a claim to be **tested, not assumed**.

| # | Component / file | Current behaviour | Evidence | Class | Depends on | What is required | Must NOT change |
|---|---|---|---|---|---|---|---|
| M1 | `risk_pct` — `entry_engine.calculate_entry_levels` | Declared, never read | [REPO] AST | **FIX** (= F2) | none | Remove the parameter, or wire it; check every call site first | Caller behaviour |
| M2 | `"LondonNewYork"` — `entry_engine.py:75`, `config.py:125`, `main_production.py:442` | A session name `get_current_session` never returns | [REPO][MEASURED] test enumerates every hour | **DECISION** (DD16) | A20 | Deleting the label is behaviour-preserving; replacing it with `"NewYork"` is **not**. Decide which was intended | Do not substitute `"NewYork"` silently |
| M3 | `from trade_manager import ...` — `main_production.py:77` | Imported, never called anywhere in the file | [REPO] grep | **DECISION** (= D5) | DD1 | Remove the import if `order_execution` is canonical; wire it if `trade_manager` is | The module itself, until DD1 |
| M4 | `random.random() < 0.05` — `order_execution.py:152` | Injects a 5 % failure in the simulation branch | [REPO] | **FIX** (= F3) | none | Remove. Non-determinism must not sit on an execution path | Real failure handling |
| M5 | `tp_pool` / `tp_score` / `tp_level` — `liquidity_engine.py` | Names assert a target role the code does not implement | [REPO] | **FIX** (rename, = F5) | B14 settled | Rename to feasibility terms | Behaviour — rename only |
| M6 | `buffer_pips` — `entry_engine.py:362` | Named pips, subtracted from a price → $3.00 | [REPO][MEASURED] test asserts 2511.73 → 2508.73 | **FIX** (part of F7) | DD11 | Rename **and** convert as one change; renaming alone leaves the defect, converting alone changes stop construction | Do not split the two halves across commits |
| M7 | `structure_low` / `structure_high` — `entry_engine.py:360` | Named for structure, fed a single displacement candle | [REPO] | **FIX** (rename) | none | Rename to name the displacement origin | Anchor values |
| M8 | Sizing comments — `risk_manager.calculate_lot_size_for_symbol` | Comments contradict each other and the code | [REPO] | **FIX** (= B10) | DD11 | Rewrite once DD11 fixes which broker field is authoritative | The formula, until DD11 |
| M9 | `"1:2 RR"` log text — `trade_manager.py:435`, `order_execution.py:24` | Identical text for two different stop moves | [REPO] conflict | **DECISION** (= C9/DD3) | DD3 | Correct the text once the semantics are chosen | Do not unify the text before the semantics |
| M10 | `stop_loss` parameter — `trade_manager.check_partial_exit_1_2` | Named as if current, must receive the **original** stop | [REPO]; `manage_open_trade` passes it correctly (K2) | **KEEP** + rename | DD1 | Orchestration is correct. Rename to `original_stop_loss` for direct callers | Do not change what `manage_open_trade` passes |
| M11 | `detect_fvg` bounds — `entry_engine.py:289` | Returns `zone_low`/`zone_high` on the `not gap_valid` path | [REPO][MEASURED] 943 cases | **FIX** (= F1) | none | Return no bounds when no gap exists | — |
| M12 | `price_in_fvg` — `entry_engine.py` | Computed, returned, no longer in the trigger | [REPO] | **KEEP** — **not** a removal candidate | — | Retained as a diagnostic by decision (K7) | Do not re-add to the trigger |
| M13 | `PendingState.EXPIRED` / `INVALIDATED` / `CANCELLED` — `execution/broker.py:67` | Defined, never produced | [REPO] labelled | **KEEP** — **not** dead by accident | A12, A15 | Deliberate experimental control | Do not delete as "unused" |
| M14 | Two functions named `detect_fvg` — `entry_engine.py:263` (M5), `poi_engine.py:273` (M15) | Both are called; different timeframes and semantics | [REPO] | **KEEP** | — | Name collision only. Worth disambiguating, not removing | Do not merge them; do not import POI's 50 % rule into L8 (Z10) |
| M15 | The losing manager — `trade_manager.py` **or** `order_execution.py` | Two live implementations, conflicting semantics | [REPO] | **DEFER** | DD1, DD2, Tier 4 | Whichever loses DD1 may only be removed after the winner is proven equivalent in the backtest | **Delete neither now** |
| M16 | `main.py` lifecycle half — `manage_positions(open_trades, current_prices)` | Manages positions it never creates | [REPO] | **DEFER** | DD2 | Follows the ownership decision | Do not delete before DD2 |

**Not listed as dead:** `LIVE_TRADING_ENABLED`, the L2 H1-ATR gate (0 firings but
a real gate with a unit defect — F7), the L5 sweep-direction check (**[MEASURED]**
0/15,735 on this data; unreachable *here* is not unreachable *in principle*), and
every `[EXPERIMENTAL CONTROL]` label. Absence of firing on one dataset is not
evidence of dead code.

---

# 11. Dependency order — derived

Derived from what each item requires, not from perceived importance.

```
TIER 0 — decisions with no code dependencies
   DD11 broker field authority ─────────────┐
   DD1  canonical manager ──┬───────────────┤
   DD2  lifecycle owner ────┘               │
   DD3/DD4 TRAIL_SL + 1R stop ──> follow DD1│
   DD5  ladder remedy ──> needs DD1         │
                                            │
TIER 1 — fixes with no gating               │
   F1 detect_fvg bounds                     │
   F2 risk_pct removal                      │
   F3 remove randomness                     │
   F5 tp_pool rename                        │
                                            │
TIER 2 — depends on Tier 0                  v
   F4 account balance ───────────────> needs DD11
   F7 unit migration (B1+B2) ────────> needs DD11 for sizing units
   F9 ladder ordering ───────────────> needs DD5
   F8 stop-loss check ───────────────> needs DD1
   F6 DEAD window ───────────────────> needs DD13

TIER 3 — canonical model
   Single state machine shared by production and backtest (D1, D2, DD3-DD10)

TIER 4 — backtest alignment
   E5 partials, E6 trailing, E7 breakeven, E9 stops, E11 ambiguity, E12 quantity

TIER 5 — wiring
   F10 (D3 + D4)   *** only after Tier 3, or the wrong manager activates ***

TIER 6 — new canonical baseline on real XAUUSD

TIER 7 — valid_rr decision (§6) informed by Tier 6

TIER 8 — experiments X1-X5 (expiry, invalidation, cross-session)

TIER 9 — OOS / walk-forward / robustness   [NOT part of this phase]
```

**Changes that must happen before others — explicitly:**

- **DD1 before F8, F10, D5, and any manager deletion.** Fixing wiring first
  activates untested, conflicting semantics.
- **DD11 before F4 and the sizing half of F7.** Two formulas differ by 10×;
  correcting either without deciding authority just picks one.
- **DD5 before F9.** The defect is certain, the remedy is not.
- **Tier 3 before Tier 4.** The backtest cannot model a manager that has not been
  chosen.
- **Tier 4 before Tier 6.** A baseline measured under a non-equivalent model
  would not describe the canonical strategy.
- **Tier 6 before Tier 7.** `valid_rr` options 1 and 2 need outcome evidence.

---

# 12. Baseline protection

**`baseline_004` is FROZEN.**

- Never overwritten, never silently modified, never mixed with corrected results.
- Its artifacts are committed and immutable; `write_artifacts` refuses to
  overwrite, and that refusal is tested.
- Every implementation change gets its own commit with before/after fingerprints.
- After approved fixes, a **new canonical baseline** is created under a new id.
- **[MEASURED]** `baseline_004` produced **zero trades**, so any future result
  showing trades is not an improvement over it — it is a different model. Nothing
  may be attributed to "performance" until a like-for-like comparison exists, and
  §7 shows one currently cannot.

---

# 13. Proposed next implementation phase

**Not approved; proposed for review.**

**Phase 4C — Tier 0 decisions + Tier 1 fixes.**

*Decisions to be taken by the strategy owner:* DD1, DD2, DD11, and — following
DD1 — DD3, DD4, DD5.

*Fixes to implement, each in its own commit with byte-identical verification
against `baseline_004` where behaviour should not change:* F1, F2, F3, F5.

**Why these four.** Each has established intended behaviour, none depends on an
open decision, and all four are expected to leave the decision stream unchanged —
F1 affects a value only read when `fvg_found` is false, F2 and F5 are inert, F3
affects a path the replay never takes. **That expectation must be verified, not
assumed:** the pass criterion is byte-identical reproduction of `baseline_004`,
including `decisions_fingerprint`.

Everything else waits on Tier 0.

The §10 removal candidates are **not** part of Phase 4C beyond F1, F2, F3 and
F5. Every other removal there waits on a decision or on backtest equivalence.

---

# 14. Verification

This document is analysis only, so verification means demonstrating that
**nothing changed** and that the claims above still hold at this commit.

**Read-only checks performed**

- Every component named in §2 located by `grep` at `7466ac6`; file paths recorded
  in the Component → file key.
- No `.py` file modified: `git status` reported one untracked file, this
  document, and no modifications.
- No baseline produced, no replay run, no parameter varied.

**Existing test suite, run unmodified**

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **664** |
| Duration | 591 s |
| Failures | **2** |
| Errors | 0 |

**Both failures are pre-existing and unrelated to this document:**

| Test | Status |
|---|---|
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_micro_scalp_l7_confidence_uses_55_threshold` | Pre-existing — reproduces at `04a341d` |
| `tests.test_layer_gate_logic.LayerGateLogicTests.test_pullback_gate_requires_real_pullback_detection` | Pre-existing — reproduces at `04a341d` |

**[MEASURED]** Both fail because the L2 H1-ATR gate rejects the mocked
indicators these tests supply; they were failing before Phase 4A and are recorded
here as the known state, **not** fixed — fixing a test is outside this task.

No test was modified. No new test was added.

---

*Analysis and design only. No code changed, nothing implemented, no decision taken, no parameter chosen. Stopping for review.*
