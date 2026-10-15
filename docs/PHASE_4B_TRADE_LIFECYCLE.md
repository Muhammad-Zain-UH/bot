# Phase 4B — trade-management lifecycle: documented, implemented, wired, measured

**Documentation only.** No strategy code, RR, `tp_ratio`, `valid_rr`, TP, SL,
trade management, threshold or baseline changed. `baseline_004` untouched. No
optimisation, no ML, no profitability claim.

**Milestone reviewed:** `c5a8d6a`. The fixed-R target model is taken as
established; `tp_pool` is treated in its currently implemented
liquidity/feasibility role.

**Four states kept strictly separate throughout:**

| State | Meaning |
|---|---|
| **DOCUMENTED** | A design document, module docstring or comment says so |
| **IMPLEMENTED** | Code exists that does it |
| **WIRED** | A call path reaches that code from an entry point |
| **MEASURED** | It was observed to happen on data |

---

# A. Complete trade-management call graph

Built by AST traversal from each entry point, not by grep.

```
main_production.py :: main()
  └─ execute_entry_signal()                                   [WIRED]
       ├─ order_executor.create_order()                       [WIRED]
       │     builds exit_1_1 = entry + 1.0 x risk
       │            exit_1_2 = entry + 2.0 x risk
       │            exit_1_3 = take_profit  (= entry + tp_ratio x risk)
       └─ order_executor.execute_order(mt5_handler=None,
                                        simulation=CONFIG["demo_mode"])
             CONFIG["demo_mode"] is False (main_production.py:150)
             -> neither the simulation branch nor the MT5 branch is taken
             -> returns (False, "No MT5 handler provided and simulation disabled")
             -> `if success:` is never true
             -> _OPEN_TRADES is NEVER populated                [BLOCKER 1]

main_production.py :: main()
  └─ manage_positions({})                     (main_production.py:1431)
       for trade in _OPEN_TRADES:             <- always empty (BLOCKER 1)
            current_price = current_prices.get(trade["trade_id"],
                                               trade.get("entry_price", 0))
            ^ called with {} so this ALWAYS falls back to entry_price
                                                              [BLOCKER 2]
            order_executor.update_current_price(order_id, current_price)
                 1R check:  BUY  current_price >= entry + risk   -> entry >= entry+risk : FALSE
                 2R check:  gated on 1R having triggered         : FALSE
                 3R check:  BUY  current_price >= take_profit    : FALSE

main_production.py imports trade_manager.manage_open_trade  (line 77)
  └─ NEVER CALLED.  AST reachability from main(): False

main.py :: main()
  └─ manage_positions()
       └─ trade_manager.manage_open_trade()                   [WIRED, other entry point]
  create_order / execute_order: NOT reachable from main.py

backtest / replay
  ReplayEngine -> PaperBroker
       no partial exits, no trailing, no milestones
       PositionState = OPEN | CLOSED_STOP | CLOSED_TARGET |
                       CLOSED_TIME | CLOSED_END_OF_DATA | CLOSED_MANUAL
       every close is a FULL close decided by resolve_intrabar
```

**The single most important structural fact:** the lifecycle is **split across
two entry points, and neither can complete it**.

| | creates orders | manages milestones |
|---|---|---|
| `main_production.py` | **yes** (`create_order`) | via `order_execution.update_current_price` |
| `main.py` | no | via `trade_manager.manage_open_trade` |

There are **two independent implementations** of the same documented model, each
wired into a different entry point, and `main_production` imports the one it does
not use.

# B. Fixed-R lifecycle — intended vs actual

```
 INTENDED (documented)                    ACTUAL (audited path, main_production)

 signal                                   signal            [reachable: 0 on real data]
   │                                        │
 entry @ entry_price                      entry_price computed            OK
   │                                        │
 SL  = sweep/displacement +- 3.00         SL computed                     OK
   │                                        │
 TP  = entry +- risk x tp_ratio           TP computed                     OK
   │                                        │
 order placed                             create_order()                  OK
   │                                        │  builds 1R / 2R / 3R levels
   │                                        │
 1R -> close 50%, SL to breakeven         execute_order() -> False        DEAD
 2R -> trail SL                             _OPEN_TRADES stays empty
 3R -> close all (= TP)                     manage_positions({}) iterates nothing
   │                                        │  and would compare entry vs entry
 final exit                               never occurs
   │                                        │
 ledger                                   no production ledger exists
```

# C. Documentation vs implementation vs wiring

| Q | Question | DOCUMENTED | IMPLEMENTED | WIRED | MEASURED |
|---|---|---|---|---|---|
| 1 | What is 1R? | "Close 50% at 1:1 RR, move SL to breakeven" (`trade_manager.py:8`; `SYSTEM_STRUCTURE:414`) | Twice — `trade_manager.check_partial_exit_1_1`; `order_execution` `exit_1_1 = entry + risk` | `order_execution` path only | **Never** |
| 2 | What is 2R? | "Trail SL at 1:2 RR (lock 50% of leg 2)" (`trade_manager.py:9`) | Twice — `check_partial_exit_1_2`; `exit_1_2 = entry + 2 x risk` | `order_execution` path only | **Never** |
| 3 | What is 3R? | "Close remaining at 1:3 RR" (`trade_manager.py:10`; `FLOW_DIAGRAM:173`) | Twice — `check_final_exit_1_3`; `exit_1_3 = take_profit` | `order_execution` path only | **Never** |
| 4 | What is TP? | "TP Target: {tp_ratio}R" (`main_production.py:243`); `exit_1_3` labelled "TP (1:3 RR)" | `entry ± risk × tp_ratio` (`entry_engine.py:403/405`) | Yes — reaches the order | **Never** (0 signals) |
| 5 | How are levels built? | R multiples of the stop distance | 1R and 2R **hardcoded**; 3R = `tp_ratio` | — | — |
| 6 | Who consumes them? | — | `order_execution.update_current_price` | Called by `manage_positions` | Never |
| 7 | Who executes partials? | — | `order_execution` (actions) and `trade_manager` (separately) | `order_execution` only, and only via `main_production` | Never |
| 8 | Partials reachable in the audited path? | — | — | **No — two blockers in series** | — |
| 9 | Is final TP managed by the same mechanism? | Yes — `exit_1_3` is the TP | Yes | Same two blockers | Never |
| 10 | Does the backtest behave the same? | — | **No** | `PaperBroker` does single full closes | See §I |

**Question 10 deserves emphasis.** The backtest implements a *different* trade
model: one stop, one target, one full exit resolved by `resolve_intrabar`. It has
no partial close, no breakeven move, no trailing stop. **So the replay has never
simulated the documented model**, and any future measurement of fixed-R
behaviour under the current backtest would not be measuring what production
documents.

# D. `tp_ratio` lifecycle and classification

Producer `entry_engine.py:78/90/100/109` → `regime_info` → `main_production:993`
→ `get_entry_trigger` → `calculate_entry_levels:403/405` → **TP price**, and
onward to `reward`, `rr`, `valid_rr`. Separately read at `main_production:225`
for the display string at `:243`.

**Classification: B — the final TP R-multiple. It is *not* C.**

Evidence that it does **not** control the milestones: `exit_1_1` and `exit_1_2`
are hardcoded at `entry + risk` and `entry + 2 × risk` (`order_execution.py:118-119`)
and never reference `tp_ratio`. Only `exit_1_3` follows it, because
`exit_1_3 = take_profit`.

**This produces a concrete ordering defect.** The ladder assumes the third level
sits above the second, which holds only when `tp_ratio > 2.0`:

| Regime | `tp_ratio` | 3rd level | Ladder | Decisions |
|---|---|---|---|---|
| INTRADAY_SWING | 3.0 | 3.0R | **ordered** | 1,810 |
| REGIME_SCALP | 2.0 | 2.0R | **tied with the 2R trail** | 6,492 |
| MICRO_SCALP | 1.5 | 1.5R | **INVERTED — TP below the 2R trail** | 5,121 |
| DEAD_CALM | 1.5 | 1.5R | **INVERTED** | 2,312 |

**13,925 of 15,735 decisions (88.5%)** fall in regimes where the documented
1R→2R→3R ladder is not properly ordered. In the two inverted regimes the
`CLOSE_ALL` at 1.5R would fire before the 2R trail could ever be reached, so
`TRAIL_SL` is unreachable by construction there — the 2R check is additionally
gated on 1R having triggered, but the 3R check is not gated at all.

**This is reasoning from code, not observation.** No milestone has ever executed.

# E. `valid_rr` lifecycle

```
risk_distance  = |entry − stop|                              entry_engine.py:406
take_profit    = entry ± risk_distance × tp_ratio            :403 / :405
reward_distance= |take_profit − entry| = risk × tp_ratio     :407
rr             = reward / risk = tp_ratio                    :408
valid_rr       = rr >= 2.0                                   :409
entry_triggered= core_trigger AND valid_rr                   :535 / :628
```

**What does the gate actually protect against?** Given `rr ≡ tp_ratio`, and
`tp_ratio` a per-regime constant chosen in `detect_regime`, `valid_rr` evaluates
to a **fixed boolean per regime**, decided before any market data is read:

| Regime | `valid_rr` | Consequence |
|---|---|---|
| INTRADAY_SWING | always True | gate never blocks |
| REGIME_SCALP | always True | gate never blocks |
| MICRO_SCALP | always False | **no entry possible, ever** |
| DEAD_CALM | always False | **no entry possible, ever** |

It protects against nothing that varies. It cannot reject a poor trade or accept
a good one, because it never sees a trade.

**Classification: category error.**

It is not a *feasibility check* — it measures no feasibility. It is not
*configuration validation* — validation would run once at configuration time and
report a misconfiguration, whereas this runs per decision and silently suppresses
entries. It is not *redundant* — a redundant check duplicates a real one, and
there is no other RR check. It is not *dead* — it is reached and it decides
outcomes; Phase 4A measured four candidates rejected by it. It is not
*ambiguous* — the arithmetic admits one reading.

It asks whether the value the operator chose is the value the operator chose, and
suppresses trading in two of four regimes when the answer is no. The nearest
honest description is a **configuration assertion mislocated into the per-decision
hot path**.

# F. `manage_open_trade` reachability — verified exhaustively

| Check | Result |
|---|---|
| Imported by `main_production.py:77` | Yes |
| AST-reachable from `main_production.main()` | **No** |
| AST-reachable from `main_production.analyze_entry()` | **No** |
| Any call site in `main_production.py` | **None** |
| AST-reachable from `main.py:main()` | **Yes**, via `manage_positions` |
| Non-test call sites repo-wide | `main.py:718`, `trade_manager.py:568` (self-demo) |

**The previous audit's claim is confirmed**, and the call graph adds the reason it
matters: `main_production` does have position management, but it is a *different*
implementation (`order_execution.update_current_price`), so `trade_manager` is
not merely uncalled — it is **superseded** in the audited path.

# G. 1R / 2R / 3R partial-exit reachability

**Unreachable in the audited path, behind two independent blockers in series:**

**Blocker 1 — no order ever executes.** `execute_order` is called with
`mt5_handler=None` and `simulation=CONFIG["demo_mode"]`, and `demo_mode` is
`False` (`main_production.py:150`). Neither branch is taken, so it returns
`(False, "No MT5 handler provided and simulation disabled")`, `if success:` is
never true, and `_OPEN_TRADES` is never appended to. `manage_positions` therefore
iterates an empty list.

**Blocker 2 — the price fed to management cannot move.** Even with an executed
order, `manage_positions({})` is called with an **empty dict**
(`main_production.py:1431`), so
`current_prices.get(trade["trade_id"], trade.get("entry_price", 0))` always
returns `entry_price`. Every milestone test then reduces to
`entry >= entry + risk`, which is false for any positive risk.

Removing either blocker alone leaves the model inert.

**A third, conditional blocker:** even with both fixed, §D shows the 2R trail is
unreachable in MICRO_SCALP and DEAD_CALM because the 1.5R TP fires first.

**Non-determinism, noted not fixed:** the simulation branch contains
`if random.random() < 0.05: raise` — a deliberate 5% failure injection. Were
`demo_mode` enabled, the order path would be non-deterministic, which would break
the reproducibility guarantees the replay relies on.

# H. Final TP reachability

The TP **price** is constructed and reaches the order (`create_order`), and in the
backtest it reaches `PaperBroker` and is enforced by `resolve_intrabar`.

The TP **as the 3R milestone** (`exit_1_3`, "CLOSE_ALL") is unreachable for the
same two blockers. So the target exists as a price level in both paths, but the
documented "close all at 3R" event has never been reachable in production and
does not exist at all in the backtest.

# I. Real-data measurements

**Real data (Phase 3A, 15,735 decisions):**

| Measure | Value |
|---|---|
| Signals | **0** |
| Trades | **0** |
| Orders created | **0** |
| Management events of any kind | **0** |
| Decisions by regime | REGIME_SCALP 6,492 · MICRO_SCALP 5,121 · DEAD_CALM 2,312 · INTRADAY_SWING 1,810 |
| Decisions in regimes with an unordered ladder | **13,925 / 15,735 (88.5%)** |

Configured `tp_ratio` and the implied level geometry, per 1 unit of risk:

| Regime | `tp_ratio` | 1R | 2R | TP (3rd level) | TP distance |
|---|---|---|---|---|---|
| MICRO_SCALP | 1.5 | 1.0R | 2.0R | **1.5R** | 1.5 × risk |
| REGIME_SCALP | 2.0 | 1.0R | 2.0R | **2.0R** | 2.0 × risk |
| INTRADAY_SWING | 3.0 | 1.0R | 2.0R | **3.0R** | 3.0 × risk |
| DEAD_CALM | 1.5 | 1.0R | 2.0R | **1.5R** | 1.5 × risk |

**Constructed-fixture evidence (Phase 2A.1) — clearly distinguished:** the two
fixture trades executed through `PaperBroker`, which has **no milestone concept**.
They closed as single full exits at target. **They do not evidence the documented
fixed-R model in any respect**, and no fixture anywhere exercises 1R/2R partials.

**Everything in §D and §G is reasoning from code.** No milestone has ever fired,
in production or in simulation, so none of it is measured behaviour.

# J. Classification of each issue

| # | Issue | Classification |
|---|---|---|
| 1 | `execute_order` can never succeed (`demo_mode=False`, `mt5_handler=None`) | **Clear implementation defect** (E1/E2) |
| 2 | `manage_positions({})` passes an empty dict, so current price ≡ entry price | **Clear implementation defect** (E4) |
| 3 | `trade_manager` imported by `main_production` and never called | **Dead / unwired code** (E7) |
| 4 | Two independent implementations of the same documented model | **Semantic inconsistency** |
| 5 | Lifecycle split across two entry points, neither complete | **Semantic inconsistency** |
| 6 | 1R/2R hardcoded while the 3rd level follows `tp_ratio` → ladder inverted in 88.5% of decisions | **Clear implementation defect** |
| 7 | Backtest implements a different trade model (single full exit) | **Design decision** — but undocumented, so results are not comparable to the production model |
| 8 | `valid_rr` as a per-decision configuration assertion | **Category error** (see §E) |
| 9 | 5% random failure injection in the simulation branch | **Design decision** with a determinism consequence |
| 10 | Whether partial exits are wanted at all | **Unresolved** — documented but never executed, so no evidence either way |

# K. What must be decided before changing `valid_rr`

`valid_rr` cannot be sensibly changed in isolation, because what it *should* do
depends on decisions that are not yet made.

1. **Should the fixed-R ladder exist at all?** It is documented, implemented
   twice, wired once, blocked twice, and has never run. If partial exits are not
   wanted, `tp_ratio` is simply a TP multiple and the ladder should go — which
   changes what "R" means downstream.
2. **If the ladder stays, what fixes the ordering?** Either `tp_ratio` must
   exceed 2.0 in every regime, or the milestones must scale with it. Both change
   admission (regime reachability) and construction.
3. **Which management implementation survives** — `trade_manager` or
   `order_execution` — and which entry point owns the lifecycle.
4. **Should the backtest model the ladder?** Until it does, no measurement can
   evaluate the fixed-R design, and any result would describe a single-exit
   strategy that production does not implement.
5. **Only then: what should `valid_rr` do?** The three positions from the
   target-semantics report still stand — remove it, replace it with an
   attainability test, or justify the constant. **No threshold is proposed here**,
   and none should be selected from any distribution measured so far.

**Every one of 1–4 changes behaviour and invalidates `baseline_004`.** Item 5
cannot be evaluated before them, because the meaning of R depends on them.

---

# Verification

**664 tests, 2 failures, 0 errors** — identical to `c5a8d6a`, `d6464b0`,
`a862408` and `8a4e010`. No test was modified; nothing here could invalidate
one, because nothing was changed. Both failures are the long-standing
`tests/test_layer_gate_logic.py` pair caused by the L2 H1-ATR gate, which
reproduces at `04a341d`.

---

*Investigation only. Nothing changed, nothing implemented, no threshold proposed. Stopping for approval.*
