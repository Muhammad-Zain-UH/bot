# Phase 6Q — Close Remaining Behaviour Pins

**Pinning only. No production strategy change.** No threshold, regime/session,
L2/L3/L4/L5 repair, Fibonacci activation, BOS repair, U9-RR decision or
refactoring. `baseline_004`, `baseline_005`, the R1 fixtures and the dataset were
**read only** and are verified unchanged (§10).

**Input:** commit `8ec47e0` (Phase 6P).

**Tests: 1,002 → 1,061 (+59).** Two pre-existing failures, unchanged.

---

# 1. Summary

**The three gaps Phase 6P named are closed, and closing the first one corrected a
Phase 6O-D number.**

| Gap named in 6P | Status |
|---|---|
| L4 behaviour unpinned | **Closed** — 29 tests |
| SELL-side leakage coverage absent | **Closed** — 12 tests |
| `bias` and `sweep` absent from leakage files | **Closed** — 11 tests |

**Correction to Phase 6O-D.** That audit reported the selected liquidity pool is
the highest-scoring candidate *"only 26.9 % of the time"*. That figure was a
**positional rank** in a score-sorted list, and pools frequently share a score,
so position among ties is arbitrary. **Measured as "does the selection carry the
top score": 92 of 120 sampled decisions — 76.7 % do.** Selection differs from
strongest-wins in roughly **23 %** of decisions, not 73 %.

**The rule itself is unchanged and still proven:** `_rank_directional_pool`
returns `(distance, -score, tier_rank)` and selection is `min(...)`, so distance
is primary and score is a tie-break that floating point rarely reaches. The
selection is **nearest-first**. Only the *size* of the observable divergence was
overstated.

**A limitation that changes how this suite should be used** — §11.

---

# 2. L4 Behaviour Pins (Part A)

**29 tests, 1.3 s**, in `tests/backtest/test_behavior_pin_l4.py`.

| Class | Tests | Pins |
|---|---|---|
| `PinnedL4ToleranceIsDollarsNotPips` | 5 | `$1.40` apart **clusters**; `$1.60` does not; at `0.15` (1.5 real pips) the `$1.40` pair **separates** — the two readings cannot both pass. Defaults `1.5 / 2.0 / 100` and all four raw-price comparisons |
| `PinnedL4SingleLinkageClustering` | 7 | Pair · chain of five spanning **$5.60** · chain of thirty spanning **$40.60** · duplicates → one cluster · ascending ≡ descending · a gap splits · a lone point is discarded |
| `PinnedL4PoolSelectionIsNearestNotStrongest` | 3 | Rank key is `(distance, -score, tier_rank)`; `min` not `max`; **empirical: the selection lacks the top score in ~23 %** |
| `PinnedL4ScoreFilterSelfDisables` | 4 | `[score >= 60] or pools`; the truthiness mechanism; thresholds `70/60/60.0`; **`is_fallback` can never be true** — no constructed `pool_type` contains `"fallback"` |
| `PinnedL4PoolTypes` | 4 | `swing_low`/`swing_high` **never constructed** though scored; `h1_level`/`h4_level` **constructed but undocumented** and falling to the `else` bucket |
| `PinnedL4RoundNumberFilterIsInert` | 3 | Five candidates always survive; worst case **$74.99 < $100**; spacing is **$25**, not "25 pips" |
| `PinnedL4DownstreamProvenance` | 3 | `sweep_pool["level"]` → `liquidity_level` **and** `l4_override_level` (the override is a no-op) → sweep wick → `_select_stop_anchor` |

**The tolerance pin is the sharpest.** `_cluster_price_points([(0, 4000.00),
(1, 4001.40)], 1.5)` returns **one cluster**. Under the documented "±1.5 pips"
(`$0.15`) it returns **none**. A future unit correction cannot pass both.

---

# 3. SELL-Side Leakage Coverage (Part B)

**In `tests/backtest/test_leakage_sell_side.py`**, using the existing method:
build one synthetic series, add **+500** to every bar after a cutoff, and assert
pre-cutoff decisions are byte-identical.

| Layer | SELL-side mutation test | Result |
|---|---|---|
| **L1 bias** | `get_h4_bias`, `get_fast_bias`, `_find_h4_swings` | **Unchanged** |
| **L2 structure** | `get_h1_structure(h1, "BEARISH")` | **Unchanged** |
| **L3 pullback** | `get_m15_pullback(m15, "BEARISH")` | **Unchanged** |
| **L4 liquidity** | `identify_liquidity_pools(..., side="SELL")` | **Unchanged** |
| **L5 sweep** | `detect_sweep` · `detect_choch` · `detect_bos` · `get_sweep_and_structure`, both directions | **Unchanged** |
| **L6 POI** | `identify_poi(..., direction="SELL")` | **Unchanged** |
| **L7 confidence** | **Not a mutation test** — see below | **Pinned structurally** |
| **L8 entry** | `get_entry_trigger(..., "SELL")` | **Unchanged** |
| Indicators | All four timeframes, not just M15 | **Unchanged** |

**L7 has no temporal surface to test.** `get_confidence_engine` takes scalars —
`bias_strength`, `structure_confidence`, `sweep_quality`, `poi_score`, `session`,
`regime` — and **no bar frame**. A mutation test would be vacuous. Pinned instead
by `test_get_confidence_engine_takes_no_bar_frame`, which fails if a frame
argument is ever added, at which point a mutation test becomes required. **This
is a pin, not a gap.**

---

# 4. Bias and Sweep Coverage (Part C)

Both were at **zero** references in either leakage file.

**Bias — 5 tests:** H4 bias unchanged under mutation · fast bias unchanged ·
`_find_h4_swings` unchanged · labels confined to `{BULLISH, BEARISH, NEUTRAL}` ·
missing EMA data yields `NEUTRAL`. Both directions arise naturally, since the
bias engine produces the direction rather than consuming it.

**Sweep — 6 tests:** `detect_sweep`, `detect_choch`, `detect_bos` and
`get_sweep_and_structure` unchanged under mutation **for BUY and SELL** ·
polarity (a BUY request never returns a bearish sweep) · **penetration band**.

**The penetration test is deterministic and unit-revealing.** On a crafted frame,
a wick **$2.50** below the level with a close above it **is** a sweep; a wick
**$0.50** below is **not**. Under the documented "3–8 pips" ($0.30–$0.80) the
first would be far too deep and the second would qualify. The current dollar
semantics are pinned exactly.

---

# 5. Vacuous-Test Findings and Disposition (Part D)

**Nothing deleted. No historical evidence removed.**

| Test | Classification | Disposition |
|---|---|---|
| `test_layer_gate_logic.test_broken_h1_structure_blocks_at_l2` | **MISLEADING** — its mock omits `last_swing_low`/`last_swing_high`, which the real function always supplies with `BROKEN`, so the flip would fire and the block would not happen | **RETAIN + SUPPLEMENT.** Supplemented by `test_broken_always_carries_both_swing_levels` and `test_broken_always_satisfies_the_flip_condition` |
| `test_pullback_gate_requires_real_pullback_detection` | **VACUOUS** — mocks `get_m15_pullback`; currently fails at L2 because mocked indicators make `h1_atr = 0.0 < 8.0`; never reaches L3 | **RETAIN (marked stale) + SUPPLEMENT** by `PinnedL3Contract` |
| `test_micro_scalp_l7_confidence_uses_55_threshold` | **VACUOUS** — same cause; never reaches L7 | **RETAIN (marked stale).** Its subject, the duplicated `55/70` threshold, is **still unpinned** — §11 |
| `test_layer_gate_logic` L5 mock returning `"sweep_type": "bullish"` | **STALE** — the real function returns `"bullish_sweep"` | **RETAIN (marked stale) + SUPPLEMENT** by the polarity tests |
| `tests/test_entry_quality_gate.py` — `rr` of 1.4 / 2.4 / 2.8 | **STALE** — `rr` is always the regime `tp_ratio`; these cannot occur | **RETAIN (marked stale) + SUPPLEMENT** by `test_rr_equals_tp_ratio_for_every_regime`. Rewriting it is U7 and belongs with the gate's own decision |
| `tests/core/test_types.py` liquidity tests | **MISSING INTEGRATION COVERAGE** — test a canonical type no production module imports | **RETAIN + SUPPLEMENT** by the 29 L4 tests |
| `tests/core/test_types.py:66` | **VALID UNIT TEST**, honestly labelled — its docstring names the production divergence | **RETAIN unchanged** |
| `test_result_is_independent_of_the_machine_timezone` | **VACUOUS on Windows** — `time.tzset` absent | **RETAIN + SUPPLEMENT** by the explicit platform pin |
| `test_leakage` per-layer tests | **VALID**, incomplete — BUY/BULLISH only | **RETAIN + SUPPLEMENT** by §3 |

**The classification itself is pinned** by `PinnedVacuousTestInventory`, so a
future repair of any of these is a visible change rather than a silent one.

---

# 6. Corrected L2 Population Pins (Part E)

`PinnedCorrectedL2Population` — 8 tests.

| Pinned | Value |
|---|---|
| Sided decisions | **13,343** |
| Reversals | **1,738** |
| Reversal rate | **13.0256 %** |
| `BROKEN` | **1,745** |
| Rescue failures | **7** |
| Reconciliation | `1,745 = 1,738 + 7` — no third outcome |
| **Distinct H1 break states** | **153** |
| Run length | min 1 · median **12** · max **12** |
| The seven rescue failures | **1 distinct H1 state** |

**`test_decision_level_reversals_are_not_market_events` asserts
`distinct_h1_states < count / 10`.** The brief's instruction is honoured: the
suite pins 1,738 **decision-level** reversals and **153** distinct break states,
and asserts nowhere that there are 1,738 market events.

---

# 7. Side-State Inconsistency Pin (Part F)

`PinnedSideStateInconsistencyHasZeroExceptions` — 4 tests.

| Assertion | Result |
|---|---|
| Exactly **5** combinations occur | `L1=BUY\|EFF=BUY\|L3=BUY` 5,681 · `L1=BUY\|EFF=SELL\|L3=BUY` **726** · `L1=SELL\|EFF=BUY\|L3=SELL` **1,012** · `L1=SELL\|EFF=SELL\|L3=SELL` 5,924 · none 2,392 |
| `L3 == L1` in **every** combination | **Zero exceptions** |
| No combination where `L3` tracks the **effective** side | **Zero offenders** |
| Reversed combinations sum to the reversal count | **726 + 1,012 = 1,738** ✓ |

**Not repaired.** The pin exists so that D-6OF-2 — reassigning `bias` on flip —
fails here and is recognised as an intentional change.

---

# 8. Test Count and Failures

| | Before | After | Δ |
|---|---|---|---|
| Total | **1,002** | **1,061** | **+59** |
| L4 pins | 0 | 29 | +29 |
| SELL-side / bias / sweep | 0 | 18 | +18 |
| Corrected L2 population | 0 | 8 | +8 |
| State inconsistency | 0 | 4 | +4 |
| **Failures** | **2** | **2** | **0** |
| Pin-suite runtime | 19 s | **23 s** | +4 s |

**The two failures are the pre-existing `test_layer_gate_logic` pair**, unchanged
and classified in §5. **No new test failed, and no existing test changed
outcome.**

**No defect was fixed in this phase.** Two were newly *exposed* by writing the
pins and are reported rather than repaired: the Phase 6O-D rank figure (§1) and
the fact that `is_fallback` can never be true, which makes L4's `60/100`
threshold pair unreachable (already recorded as L4-D12, now pinned).

---

# 9. Baseline Integrity (Part G)

| Check | Result |
|---|---|
| `git diff HEAD -- '*.py' ':!tests/'` | **empty — no production source change** |
| `git status -- baselines/` | **empty — untouched** |
| `git status -- data/` | **empty — untouched** |
| `git status -- tests/integration/` | **empty — R1 untouched** |
| `baseline_004` / `baseline_005` `run_fingerprint` | `1276a31f673a5a82b2879ea5113b12e486da0d2491d0…` — unchanged |
| Dataset hash | `433b7e2713babdef…` — unchanged |
| Thresholds / configuration | **unchanged** |
| Regime / session behaviour | **unchanged** |
| Files touched | 1 modified + 2 added, **all under `tests/`**, plus this document |

**U4 (`7b1c5f1`) remains the only production behaviour difference relative to
`baseline_005`.** The fingerprint's mixed-state warning stands and is restated
here: `blocked_at` and `signal_type` describe commit `7b702dd` (**zero
signals**); the recomputed fields describe current HEAD (**four signals**). U4
touched only `calculate_entry_levels`, so every recomputed field is unaffected.

---

# 10. Remaining Unpinned Behaviour

| # | Unpinned | Why it matters |
|---|---|---|
| **1** | **L7 weights, `cohesion` double count, and the duplicated `55/70` threshold** | The one item from 6P's recommendation not closed here. `cohesion_component` counts bias/structure/sweep/POI a second time, and the L7 threshold is computed independently in `confidence_engine.py:157` and `main_production.py:959` — nothing keeps them in step |
| **2** | **Per-decision L3–L8 intermediates** | Pullback %, liquidity level, sweep depth, POI score, stop, target, RR per decision. Capturing them requires instrumenting `analyze_entry`, which every pinning phase has forbidden |
| **3** | **Regime and session under future mutation** | 6O's T2. The classification is pinned; that it is *temporally* immune is not. The inputs are M5 ATR and a patched clock, so the risk is low, but it is untested |
| **4** | **Full `analyze_entry` under SELL-side mutation** | §3 covers each layer in isolation; the assembled path is covered BUY-side only by `test_integration_leakage` |
| **5** | **L4's `assess_liquidity_gate` verdicts** | The selection and clustering are pinned; the PASS/WATCH/BLOCK thresholds are pinned only as source strings |

---

# 11. How This Suite Must Be Used — a limitation

**The aggregate tests are artifact-integrity checks, not HEAD-behaviour checks.**

`PinnedAggregateFingerprint` and `PinnedCorrectedL2Population` compare the
committed fingerprint against the **frozen** `baseline_005` stream. Both are
static files. **They detect tampering with the artifacts. They do not detect a
change in what HEAD computes**, because neither side is recomputed from HEAD.

**The tests that do detect a HEAD change** are the production-path ones: the 29
L4 pins, the 18 SELL/bias/sweep mutation tests, the regime/session classification
pins, the L2 identity, the four-way fractal agreement, and the L3/L5/L6/L8
contract pins. Those call production functions on real or synthetic data and fail
if behaviour moves.

**Therefore, before and after any strategy change, regenerate and diff:**

```
python tests/fixtures/generate_behavior_fingerprint.py   # ~20 minutes
git diff -- tests/fixtures/behavior_fingerprint.json
```

The diff is the answer to *"exactly what behaviour changed?"* at the
distribution level. The test suite is the answer at the contract level. **Both
are needed; neither substitutes for the other.**

---

# 12. Readiness Assessment for D-6N-1

> **Ready, with one required procedural step.**

**What is in place.** D-6N-1 — removing the session term from the MICRO_SCALP
branch — would change the regime classification, and that is the best-pinned area
in the codebase: the eligibility hours (0–13, including the kill-zone rescue of
hour 13), the five session names, the weekday-blind kill zone, DEAD_CALM as an
`else` branch, and the full regime distribution. The predicted effects are
quantified in Phase 6N: DEAD_CALM **2,312 → 119**, MICRO_SCALP **5,121 → 7,314**,
2,193 decisions crossing the L8 RR gate from impossible to satisfiable.

**What is required first.** Per §11, regenerate the fingerprint **at the
pre-change commit** and keep it, then regenerate after the change and diff. The
current fingerprint was generated at `8ec47e0` and is valid as the "before"
reference — **provided no production change lands between now and D-6N-1.**

**What will fail by design when D-6N-1 lands**, and must be updated in the same
commit: `test_micro_scalp_eligible_hours_are_zero_to_thirteen`,
`test_dead_calm_is_the_else_branch_not_an_atr_test`, and the regime distribution
in the fingerprint. **These are the intended detections.**

**What remains blocked.** **U9-RR stays blocked behind D-6N-1**, because D-6N-1
moves 2,193 decisions across the very gate U9-RR would set. Item 1 of §10 (L7)
should be pinned before any L7 change, but it does not block D-6N-1.

---

# 13. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged** |
| Strategy behaviour, thresholds, regime/session, L2 reversal | **Untouched** |
| Defects fixed | **None** — two newly exposed, both reported and pinned |
| U9-RR, D-6N-1 | **Not decided** |
| Baselines, R1, dataset | **Read only; verified unchanged** |
| Vacuous tests | **Classified with disposition; none deleted** |
| Files changed | `tests/backtest/test_behavior_pin.py` (modified), `test_behavior_pin_l4.py`, `test_leakage_sell_side.py` (added), this document |

**No profitability conclusion is drawn or available.**
