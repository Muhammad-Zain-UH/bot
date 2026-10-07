# Phase 4B — target semantics: market-derived vs fixed-R

**Documentation only.** No code, parameter, threshold, test or baseline changed.
`baseline_004` untouched. RR, TP and SL untouched. No optimisation, no ML, no
profitability claim, **no threshold recommended**.

**Milestone reviewed:** `d6464b0`.

---

# 0. Headline — the framing in the design review was wrong

The design review said the system *"computes a market-derived target and
discards it"*. The mechanical half of that is confirmed. **The word "discards"
is not supported, and I am withdrawing it.**

"Discard" presumes `tp_pool` was *meant* to be the target. Investigating that
premise turned up **positive evidence for the opposite**: the fixed-R model is
documented in three places and implemented in two modules. Under that model
`tp_pool` is not a discarded target — it is a **feasibility check** whose name
is misleading.

**Classification: C — deliberate fixed-R design**, with two riders in §8.

---

# 1. Target data-flow

```
identify_liquidity_pools (liquidity_engine.py:618-652)
   │  _rank_directional_pool -> NEAREST qualifying pool on the profitable side
   ├─> sweep_pool ──> main_production:868 ──> L5 get_sweep_and_structure
   └─> tp_pool ────> main_production:845
                        │
                        ├─> assess_liquidity_gate(sweep_pool, tp_pool, price, side)
                        │      liquidity_engine:692   both must exist        -> BLOCK
                        │      liquidity_engine:704   tp_level correct side  -> BLOCK
                        │      liquidity_engine:748   tp_score >= 60         -> BLOCK/WATCH
                        │      *** no distance is computed, no RR is derived ***
                        │
                        └─> analysis["layer_4"]["tp_pool"]   (record only)
                                          │
                                          X   NEVER PASSED ONWARD
                                              entry_engine.py contains ZERO
                                              references to tp_pool

detect_regime (entry_engine.py:78-112) ──> tp_ratio (1.5 / 2.0 / 3.0)
   └─> main_production:993 regime_tp_ratio
          └─> get_entry_trigger ──> _evaluate_*_entry ──> calculate_entry_levels
                 take_profit  = entry ± risk_distance × tp_ratio   (:403/:405)
                 reward       = |tp − entry| = risk × tp_ratio     (:407)
                 rr           = reward / risk = tp_ratio           (:408)
                 valid_rr     = rr >= 2.0                          (:409)
                 entry_triggered = core_trigger AND valid_rr       (:535/:628)
```

# 2. `tp_pool` lifecycle — every occurrence

| # | File:line | Producer / consumer | Transformed? | Overwritten? | Reaches order? | Logged only? | Affects admission? |
|---|---|---|---|---|---|---|---|
| 1 | `liquidity_engine.py:618` | init `None` | — | — | No | No | — |
| 2 | `liquidity_engine.py:638` | **producer** — nearest below (SELL) | selection | No | No | No | — |
| 3 | `liquidity_engine.py:642` | **producer** — nearest above (BUY) | selection | No | No | No | — |
| 4 | `liquidity_engine.py:645` | `None` on exception | — | Yes | No | No | — |
| 5 | `liquidity_engine.py:652` | returned in dict | No | No | No | No | — |
| 6 | `liquidity_engine.py:666` | param of `assess_liquidity_gate` | No | No | No | No | **Yes** |
| 7 | `liquidity_engine.py:692` | existence check | No | No | No | No | **Yes — BLOCK** |
| 8 | `liquidity_engine.py:697` | `tp_score` extracted | `.get("score")` | No | No | No | Yes |
| 9 | `liquidity_engine.py:704` | `tp_level` extracted | `.get("level")` | No | No | No | **Yes — side check** |
| 10 | `liquidity_engine.py:748` | `tp_score >= 60` | int cast | No | No | No | **Yes** |
| 11 | `main_production.py:845` | consumer — retrieved | No | No | No | No | — |
| 12 | `main_production.py:848` | passed to the gate | No | No | No | No | **Yes** |
| 13 | `main_production.py:863` | stored in `layer_4` | No | No | **No** | **Yes** | No |
| 14 | `main.py:459-499` | same pattern in the other entry point | — | — | No | Yes | Yes |
| 15 | `debug_l4.py:30` | debug print | — | — | No | Yes | No |

**`entry_engine.py`: 0 occurrences.** The target price computation never sees it.

**What the gate does with it:** existence, **side**, and **score**. It computes
`sweep_distance` for the *sweep* pool but **never a distance for `tp_pool`**, and
never an RR. That is the signature of a feasibility check, not a target.

# 3. `tp_ratio` lifecycle

| # | File:line | Role | Reaches order? |
|---|---|---|---|
| 1 | `entry_engine.py:78, 90, 100, 109` | **producer** — 1.5 / 2.0 / 3.0 / 1.5 per regime | — |
| 2 | `entry_engine.py:126` | returned in `regime_info` | — |
| 3 | `entry_engine.py:143` | `2.0` on the exception path | — |
| 4 | `main_production.py:225` → `243` | **display only** — `"TP Target: {tp_ratio:.1f}R"` | No |
| 5 | `main_production.py:993` | passed as `regime_tp_ratio` | — |
| 6 | `entry_engine.py:699, 704` | into both evaluators | — |
| 7 | `entry_engine.py:471, 516, 608` | into `_entry_level_context` | — |
| 8 | `entry_engine.py:383` | parameter of `calculate_entry_levels` | — |
| 9 | **`entry_engine.py:403/405`** | **`take_profit = entry ± risk × tp_ratio`** | **YES — constructs TP** |
| 10 | `entry_engine.py:407-409` | reward, `rr`, `valid_rr` | **YES — admission** |

**`tp_ratio` is the only input to the target price.** It is a regime constant.

# 4. RR derivation

```
risk_distance   = |entry − stop|                                   (:406)
take_profit     = entry ± risk_distance × tp_ratio                 (:403/405)
reward_distance = |take_profit − entry| = risk_distance × tp_ratio (:407)

rr = reward_distance / risk_distance
   = (risk_distance × tp_ratio) / risk_distance
   = tp_ratio                                for all risk_distance > 0
   = 0                                       when risk_distance == 0

valid_rr = rr >= 2.0   ==   tp_ratio >= 2.0   ==   a constant per regime
```

`rr` cannot take any value other than `tp_ratio` or `0`. It is independent of
price, stop, target, and every L1–L7 output. **Confirmed unconditionally.**

# 5. Historical and documentation evidence

**Git history yields nothing.** All strategy code arrived in one bulk commit
(`c3cf4df`, "update", 51 files, 43,719 insertions). No commit message, before
this project's own phases, mentions TP, target, reward or RR.

**Documentation — evidence FOR fixed-R (model B):**

| Source | Statement |
|---|---|
| `trade_manager.py:4` | *"Implements: Partial exits at **1:1, 1:2, 1:3 RR** with SL management"* |
| `trade_manager.py:8-10` | *"Close 50% at 1:1 RR"*, *"Trail SL at 1:2 RR"*, *"Close remaining at 1:3 RR"* |
| `order_execution.py:118-120` | `exit_1_1 = entry + risk`, `exit_1_2 = entry + risk×2`, **`exit_1_3 = take_profit`** |
| `SYSTEM_STRUCTURE_DIAGRAM.md:413-416` | *"Check RR milestones: 1:1 → CLOSE_50PCT, 1:2 → TRAIL_SL, 1:3 → CLOSE_ALL (TP)"* |
| `FLOW_DIAGRAM_WITH_FLAWS.md:172-173` | *"Trail SL at 1:2 RR"*, *"Close remaining at 1:3 RR"* |
| `main_production.py:243` | *"TP Target: {tp_ratio:.1f}R"* |

This is a **coherent, self-consistent R-multiple management model**, documented
in two design documents and implemented in two modules. `exit_1_3 = take_profit`
is the decisive detail: the third milestone *is* the take-profit, which holds
exactly when TP is a fixed R multiple. Under a market-derived target that
identity would be a coincidence.

**Documentation — evidence FOR market-derived (model A):**

| Source | Statement |
|---|---|
| naming | `tp_pool`, `tp_score`, `tp_level` — "TP" conventionally means take profit |
| `liquidity_engine.py:678-679` | *"For SELL: … `tp_pool` MUST be below"* — framed directionally as a target |
| `liquidity_engine.py:428` | pool recommendation strings ("Hunt S-Tier") imply pools are objectives |

**Weighing them.** You instructed that names alone are not proof of intent, and
that is the whole of model A's evidence: a name, plus a directional validation
that is **equally explicable as a feasibility check** — and which computes no
distance and no RR, which a target selection would need.

Model B's evidence is substantive and independent of naming: a documented
management model, its implementation, and an identity (`exit_1_3 == take_profit`)
that only holds under B.

**A material caveat:** the management half is **not reachable from
`main_production`**. `manage_open_trade` is imported at `main_production.py:77`
and **never called**; its only non-test call site is `main.py:718`, a different
entry point. So `main_production` *constructs* the R milestones
(`create_order` at `:1111` builds `exit_1_1/1_2/1_3`) and never acts on them.
The fixed-R model is **documented, constructed, and unmanaged** in the audited
path.

# 6. Quantitative comparison — real XAUUSD

Same population as the Phase 4B analysis: **1,504 allowed candidates** drawn
from the 1,265 L8-blocked decisions.

| # | Measure | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| 1 | Entry → swept-extreme stop | 1.27 | 8.13 | **10.20** | 13.05 | 43.87 |
| 2 | Entry → `tp_pool` | 0.00 | 1.28 | **2.53** | 4.49 | 36.78 |
| 3 | Market-derived RR (2 ÷ 1) | 0.00 | 0.10 | **0.25** | 0.45 | 6.70 |
| 4 | Current fixed RR | — | — | **1.5 ×1016 · 2.0 ×434 · 3.0 ×54** | — | — |
| 5 | Difference (fixed − market), median | — | — | **1.36** | — | — |

**Threshold satisfaction — descriptive only, no threshold is proposed:**

| Market-derived RR | Candidates | % |
|---|---|---|
| ≥ 1.0 | 88 / 1,504 | 5.85 |
| ≥ 1.5 | 37 / 1,504 | 2.46 |
| ≥ 2.0 | 19 / 1,504 | **1.26** |

**By regime — the mismatch is systematic, not regime-specific:**

| Regime | n | Market RR (median) | Fixed `tp_ratio` |
|---|---|---|---|
| MICRO_SCALP | 972 | 0.24 | 1.5 |
| REGIME_SCALP | 434 | 0.25 | 2.0 |
| INTRADAY_SWING | 54 | **0.18** | **3.0** |
| DEAD_CALM | 44 | 0.32 | 1.5 |

INTRADAY_SWING has the **largest** fixed ratio and the **smallest** market-derived
one — the two models diverge most exactly where the strategy intends its most
ambitious target.

# 7. Market-derived vs fixed-R — behavioural comparison

| | Fixed-R (current) | Market-derived (hypothetical) |
|---|---|---|
| TP price | `entry ± risk × tp_ratio` | `tp_pool.level` |
| TP distance | proportional to the stop | independent of the stop |
| RR | constant `tp_ratio` | measured, median **0.25** |
| `valid_rr` | tests a constant — always true or always false per regime | a real filter — would admit **1.26%** at 2.0 |
| Effect of a wider stop | target moves further away | target unchanged; RR falls |
| `tp_pool` role | feasibility (side + score) | the target itself |
| Consistency with `exit_1_1/1_2/1_3` | **exact** — milestones are R multiples | broken — milestones would not align with TP |
| Reachability of the target | unmeasured | measured: 99.1% touched, median 1 bar (Phase 4A) |

The last row matters: Phase 4A already measured that price returns to these
zones almost always and almost immediately. **Neither model has been tested for
whether its target is actually hit**, because zero trades exist.

# 8. Classification

**C — deliberate fixed-R design.**

Grounds: the R-multiple management model is documented in two design documents,
implemented in two modules, and produces the identity `exit_1_3 == take_profit`
that only holds under a fixed-R target. `tp_pool` is validated on side and score
but never on distance, which is what a feasibility check looks like and not what
a target selection looks like.

**Rider 1 — the naming is a genuine semantic inconsistency (class C in the audit
taxonomy).** `tp_pool` / `tp_score` / `tp_level` assert a role the code does not
give them. This misled my own design review into the word "discards". It should
be recorded as a naming defect, not as evidence of a different intent.

**Rider 2 — E9/E10 remains a defect under *either* model, and its character is
now sharper.** Under fixed-R, `rr` is a **chosen input**. Testing a chosen input
against `2.0` is not a weak check — it is a **category error**: the gate asks
whether the value you selected is the value you selected. That is independent of
the target-model question and is unaffected by this classification.

**What is NOT claimed:** that fixed-R is correct, better, or profitable. Only
that it is what the repository designed and documents.

# 9. Missing evidence

1. **No statement of purpose for `tp_pool`.** No comment, docstring or document
   says whether it is a target or a feasibility check. The classification rests
   on what the gate *does* with it, not on a recorded intent.
2. **No rationale for `2.0`.** Nothing explains the threshold, and under fixed-R
   it cannot be satisfied at all in two of four regimes.
3. **No rationale for the per-regime ratios** 1.5 / 2.0 / 3.0.
4. **No evidence on target attainment.** Zero trades; neither model's target has
   ever been tested against price.
5. **No record of why `manage_open_trade` is unreachable from
   `main_production`** — whether the omission is deliberate or an oversight.

# 10. The decision that must eventually be made

Given classification C, the open question is **not** "which target model" — the
evidence answers that. It is:

> **Under a deliberately fixed-R target, what should `valid_rr` do?**

The three coherent positions, stated without recommendation:

1. **Remove the gate.** If R is chosen, validating it is a category error.
   Consequence: `entry_triggered` reduces to `core_trigger`, and the four
   MICRO_SCALP candidates measured in Phase 4A would become signals.
2. **Replace it with an attainability test.** Keep the fixed-R target, but ask
   whether it can plausibly be reached — which is a question `tp_pool` could
   actually answer, giving it a real role instead of a misleading name.
   Requires deciding what "attainable" means, which the repository does not say.
3. **Keep the gate and justify the constant.** Requires a rationale for 2.0 that
   the repository does not contain, and would leave two regimes permanently
   unenterable.

Each changes admission; only (2) would also change construction. **All three
invalidate `baseline_004` and require a new controlled experiment.** No
threshold is proposed here, and none should be chosen from the distributions in
§6 — those describe what the data did, not what the strategy should require.

---

# 11. Verification

**664 tests, 2 failures, 0 errors** — identical to `d6464b0`, `a862408` and
`8a4e010`. No test modified; nothing here could invalidate one, because nothing
was changed. Both failures are the long-standing `test_layer_gate_logic` pair
caused by the L2 H1-ATR gate, reproducing at `04a341d`.

---

*Investigation only. Nothing changed, nothing implemented, no threshold recommended. Stopping for approval.*
