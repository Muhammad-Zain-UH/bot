# Phase 6P — Immutable Behaviour Pin

**Pinning only. No strategy behaviour changed.** No threshold, no regime/session
change, no L2 reversal change, no L3/L4/L5 repair, no U9-RR decision, no
Fibonacci activation, no BOS repair, no refactoring. `baseline_004`,
`baseline_005` and the R1 fixtures were **read only**.

**Input:** commit `2683e48` (Phase 6O-F).

**Artifacts added — three files, none of them production source:**

| File | Purpose |
|---|---|
| `tests/backtest/test_behavior_pin.py` | **32 regression tests**, 19 s, production paths |
| `tests/fixtures/behavior_fingerprint.json` | 2.8 KB aggregate reference |
| `tests/fixtures/generate_behavior_fingerprint.py` | Regenerates the fingerprint |

---

# 1. Executive Summary

**The pin is in place, and producing it corrected two numbers from Phase 6O.**

1. **The reversal count is 1,738, not 174.** The 174 was a 1-in-10 sample
   measured in Phase 6O-E. The full population is **1,738 M5 decisions of
   13,343 with a side — 13.03 %**, exactly the sampled rate.

2. **Those 1,738 are not 1,738 independent events.** The brief's caution about
   the seven L2 blocks applies here too, and harder. **MEASURED: they form 154
   consecutive runs over 153 distinct H1 states, with a median run of 12 and a
   maximum of 12.** An H1 bar contains twelve M5 decisions, and the close and
   swing levels do not move within it — so one structure break is re-decided
   twelve times. **The honest count of reversal events is ~153, not 1,738.**

3. **The identity now holds at full population.** `l2_structure_type` counts
   **BROKEN = 1,745**, and **1,745 = 1,738 reversals + 7 L2 blocks**. Every
   BROKEN structure either flipped or was one of the seven rescue failures.
   There is no third outcome. Pinned by
   `test_every_broken_structure_either_flipped_or_is_one_of_the_seven`.

4. **Side-state consistency is confirmed with zero exceptions.** The full matrix:

   | L1 initial | Effective after L2 | Bias used by L3 | Count |
   |---|---|---|---|
   | BUY | BUY | BUY | 5,681 |
   | **BUY** | **SELL** | **BUY** | **726** |
   | **SELL** | **BUY** | **SELL** | **1,012** |
   | SELL | SELL | SELL | 5,924 |
   | — | — | — | 2,392 |

   **For all 1,738 reversals: `L1 ≠ EFFECTIVE` and `L3 == L1`.** Exactly as the
   brief predicted, with no counter-example.

5. **A new fact the pin surfaced: the reversal rebalances the side mix.** L1
   produces **BUY 6,407 / SELL 6,936** — SELL-leaning at 52.0 %. After the flip
   the effective mix is **BUY 6,693 / SELL 6,650** — 50.2 % BUY. **The reversal
   mechanism moves 2 points of directional bias.** Pinned, not endorsed.

6. **The seven L2 blocks are one H1 state**, confirmed at full population:
   `distinct_h1_states: 1`, one distinct reason string.

**Scope limit, stated plainly.** Per-decision L3–L8 intermediates — pullback
percentage, liquidity level, sweep depth, POI score, stop, target, RR — are
**not** captured. Capturing them per decision requires instrumenting
`analyze_entry`, which this phase forbids. Following the brief's instruction not
to fabricate unavailable values, they are pinned as **contracts and invariants**
(§7) rather than as per-decision values.

---

# 2. Behavioural Fingerprint Specification

`tests/fixtures/behavior_fingerprint.json`, 17 top-level keys.

| Source | Fields | Code state described |
|---|---|---|
| **Frozen `baseline_005` stream** | `blocked_at`, `signal_type`, `effective_side`, `regime` | commit **`7b702dd`** |
| **Recomputed, production functions under `frozen_clock`** | `session`, `kill_zone_true`, `m5_atr`, `bias_timeframe`, `bias_label`, `bias_strength`, `l1_initial_side`, `l2_structure_type`, `reversals`, `side_state_matrix`, `l2_blocks` | **current HEAD** |

**The mixture is deliberate and must be understood before trusting the file.**
`baseline_005` predates **U4** (`7b1c5f1`), so its `signal_type` is
**`PRE_ENTRY` × 15,735 — zero signals**, while current HEAD admits **four**
(Phase 6K-F). U4 touched only `calculate_entry_levels`, so every recomputed
field is unaffected. **The divergence is confined to the L8 admission and is
recorded here rather than hidden.**

### 2.1 Checksums

| Name | Value (SHA-256) |
|---|---|
| `regime_session_side` | `cf1d7661270780e91475aff937aa8d335cc3429027eb961c6de27cac80d48701` |
| `layer_outcome` | `bfcff429d4e20be6bd63b5e9e7ba3cb31473b5c953feaec28342cb33a8830ad4` |
| `reversal_set` | `2a8bb246b90a4152edc39c7b4a371d96e4aabf44e0ba20dcb62f9927e83af047` |
| `full_record` | `594e548df4380e3c5295c8d5ae5aaf030ff01c5057420408e1dab455cb27e638` |

The 10.5 MB per-decision record they digest is **not committed** — it is
regenerable in ~20 minutes by `generate_behavior_fingerprint.py`. The checksums
make that regeneration verifiable.

---

# 3. Layer-by-Layer Pinned Behaviour

## L1 — direction

| Pinned | Value |
|---|---|
| Bias timeframe split | **H1 11,613 · H4 4,122** |
| Bias labels | BEARISH 6,936 · BULLISH 6,407 · **NEUTRAL 2,392** |
| Initial side | BUY 6,407 · SELL 6,936 |
| Bias strength | min 0.0 · median **6.736** · max 10.0 |
| L1 blocks | **2,392** — every one `bias == "NEUTRAL"` |

## L2 — structure and reversal

| Pinned | Value |
|---|---|
| Structure types | HH/HL 5,252 · LH/LL 5,547 · **BROKEN 1,745** · UNKNOWN 799 · n/a 2,392 |
| **Reversals** | **1,738** (13.03 % of sided decisions) |
| Direction | **SELL→BUY 1,012 · BUY→SELL 726** |
| **Distinct H1 states** | **153** · 154 runs · run length min 1 / median 12 / max 12 |
| Blocks | **7 decisions, 1 distinct H1 state, 1 distinct reason** |
| Identity | `BROKEN = reversals + blocks` → `1,745 = 1,738 + 7` |

## L3 – L8 — funnel

| Layer | Blocked |
|---|---|
| L1_BIAS | 2,392 |
| L2_STRUCTURE | **7** |
| L3_PULLBACK | 5,868 |
| L4_LIQUIDITY | 629 |
| L5_SWEEP | 2,441 |
| L5_SWEEP_WAIT | 1,634 |
| L6_POI | **1** |
| L7_CONFIDENCE | 1,498 |
| L8_ENTRY | 1,265 |

## Regime / session

| Pinned | Value |
|---|---|
| Regimes | DEAD_CALM 2,312 · INTRADAY_SWING 1,810 · MICRO_SCALP 5,121 · REGIME_SCALP 6,492 |
| Sessions | Asian 5,040 · London 4,316 · NewYork 4,999 · Dead 1,104 · **Closed 276** |
| Kill zone true | **2,864 (18.2 %)** |
| M5 ATR | min 1.967 · p25 3.819 · median **4.600** · p75 5.696 · max 15.600 |

---

# 4. The Reversal Pin (brief §4)

**Pinned exactly**, with the correction that the population is 1,738, not 174.

| By regime | | By session | | Terminal layer | |
|---|---|---|---|---|---|
| REGIME_SCALP | 880 | NewYork | 617 | L3_PULLBACK | 944 |
| MICRO_SCALP | 620 | London | 609 | L8_ENTRY | 200 |
| INTRADAY_SWING | 190 | Asian | 466 | L5_SWEEP | 191 |
| DEAD_CALM | 48 | Dead | 46 | L7_CONFIDENCE | 176 |
| | | | | L4_LIQUIDITY | 127 |
| | | | | L5_SWEEP_WAIT | 100 |

**A worked example of a run**, the first reversal sequence in the dataset:

```
2026-06-25T13:00 .. 13:55   twelve consecutive M5 decisions
regime INTRADAY_SWING · bias BEARISH · L1 side SELL · effective side BUY
h1_close 4012.35 · last_swing_high 4002.03 · last_swing_low 3971.49
break_reason "Close 4012.35 > last_high 4002.03"     ← identical on all twelve
all twelve blocked at L3_PULLBACK
```

**One H1 bar, one structure break, twelve reversals recorded.** This is why the
distinct-state count (153) is the meaningful figure and the decision count
(1,738) is not.

**The seven rescue failures** are pinned as a single event by
`test_the_seven_l2_blocks_are_one_market_event`: 7 decisions, 1 distinct H1
state, reason `"H1 structure is broken (Close 4089.40 > last_high 4082.04)"`.

---

# 5. L3 – L8 Contract Pins (brief §§5–10)

Per-decision values being unavailable (§1), these pin the **contracts** using
production functions on real data.

| Layer | Pinned property | Test |
|---|---|---|
| **L3** | `pullback_detected ⟹ quality >= 5.0` — so `MIN_PULLBACK_QUALITY = 1.5` can never bind | `test_min_pullback_quality_is_unreachable` |
| **L3** | `ema20`/`ema50` are **always `None`** — the name mismatch against `ema_20`/`ema_50` | `test_the_ema_fields_are_always_none` |
| **L3** | The accepted band is `[0.236, 0.786]`, not the documented `≤ 0.618` | `test_the_documented_depth_cap_is_0786_not_0618` |
| **L5** | `detect_sweep` never returns the opposite polarity — why `L5_SWEEP_DIRECTION` measured 0 | `test_detect_sweep_never_returns_the_opposite_polarity` |
| **L5** | The `reasoning` key collision masks sweep diagnostics | `test_the_reasoning_key_collision_masks_sweep_diagnostics` |
| **L6** | `best_poi` is never `None` with ≥ 20 M15 bars | `test_best_poi_is_never_none_with_twenty_bars` |
| **L6** | The gate ignores the regime `poi_threshold` | `test_the_regime_poi_threshold_is_ignored_by_the_gate` |
| **L8** | `rr == tp_ratio` exactly, for four ratios × both directions | `test_rr_equals_tp_ratio_for_every_regime` |

**L4 note.** Its distinctive behaviour — nearest-not-strongest selection,
single-linkage chaining, the self-disabling `≥ 60` pre-filter — is measured in
Phase 6O-D but **not pinned by a test here**, because each requires a multi-minute
sweep over the dataset. **Recorded as an outstanding pin**, §13.

---

# 6. Regime / Session Pin (brief §11)

| Pinned property | Test |
|---|---|
| Session names are exactly `{Asian, London, NewYork, Dead, Closed}` | `test_session_names_are_exactly_these_five` |
| **MICRO_SCALP eligible hours are 0–13** — hour 13 is NewYork but inside kill zone `(12,14)` | `test_micro_scalp_eligible_hours_are_zero_to_thirteen` |
| The kill zone **ignores the weekday** | `test_the_kill_zone_ignores_the_weekday` |
| DEAD_CALM is the `else` branch, not an ATR test | `test_dead_calm_is_the_else_branch_not_an_atr_test` |

**D-6N-1 is untouched.** These pin the current classification so that changing it
is visible.

---

# 7. Aggregate Fingerprints (brief §12)

The committed file carries counts and categorical distributions for: the full
dataset, each regime, each session, each side, each layer, the bias timeframes,
the structure types, the reversal population and the signal types — plus numeric
summaries for `m5_atr` and `bias_strength`, and four SHA-256 checksums.

**Six of these are recomputed from the frozen stream on every test run**
(decision count, regime distribution, layer funnel, effective side, plus the two
derived identities), so drift in the frozen artifact itself is caught
immediately. The rest are compared against the stored reference.

---

# 8. New Regression Tests

**32 tests, 19 seconds, all passing.** Every one exercises a production function
or production source. **Nothing under test is mocked** — the failure mode Phase
6O found in `tests/test_layer_gate_logic.py`.

| Class | Tests | Pins |
|---|---|---|
| `PinnedSideStateConsistency` | 4 | AST: the flip reassigns `side` but **not** `bias`; L3 is called with `bias["bias"]`; `layer_1` is not corrected |
| `PinnedL2FlipIsAnIdentity` | 2 | BROKEN ⟹ flip condition, on real H1 windows; BROKEN always carries both swing levels |
| `PinnedFractalImplementationsAgree` | 1 | All four copies agree on identical windows |
| `PinnedL3Contract` | 3 | §5 |
| `PinnedL5Contract` | 2 | §5 |
| `PinnedL6Contract` | 2 | §5 |
| `PinnedRegimeAndSession` | 4 | §6 |
| `PinnedL8Contract` | 1 | §5 |
| `PinnedAggregateFingerprint` | 9 | §7, plus the two identities |
| `PinnedVacuousTestInventory` | 4 | §9 |

The module docstring states the rule explicitly: **when one of these fails, do
not edit the assertion** — confirm the change was intended and update the pin in
the same commit as the production change.

---

# 9. Vacuous and Misleading Tests (brief §14)

**None deleted.** Classified, and the classification itself is pinned.

| Test | Classification | Why |
|---|---|---|
| `test_layer_gate_logic.test_broken_h1_structure_blocks_at_l2` | **MISLEADING** | Its mock returns `BROKEN` **without `last_swing_low`/`last_swing_high`**. The real function *always* supplies both when it returns BROKEN (pinned by `test_broken_always_carries_both_swing_levels`), so the flip would fire. **The test reaches an L2 block only via a state production cannot produce** — and L2 blocks 7 times in 15,735 |
| `test_layer_gate_logic.test_pullback_gate_requires_real_pullback_detection` | **VACUOUS** | Mocks `get_m15_pullback` away; **currently fails** at L2 because mocked indicators make `h1_atr = 0.0 < 8.0` (D7). Never reaches L3 |
| `test_layer_gate_logic.test_micro_scalp_l7_confidence_uses_55_threshold` | **VACUOUS** | Same cause; never reaches L7 |
| `test_layer_gate_logic` L5 mock | **STALE** | Supplies `"sweep_type": "bullish"`; the real function returns `"bullish_sweep"` |
| `tests/test_entry_quality_gate.py` | **STALE** | Passes `rr` of 1.4 / 2.4 / 2.8 against regimes whose `tp_ratio` is 1.5 / 2.0 / 3.0 — values production cannot generate |
| `tests/core/test_types.py` liquidity tests | **MISSING INTEGRATION COVERAGE** | Test `core.types.LiquidityLevel`, imported by no production module |
| `tests/core/test_types.py:66` | **VALID UNIT TEST**, honestly labelled | Asserts canonical `Side.from_bias` raises on NEUTRAL, and its docstring names the production divergence |
| `test_integration_leakage.test_result_is_independent_of_the_machine_timezone` | **VACUOUS on Windows** | `time.tzset` does not exist; degrades to a determinism check |
| `test_leakage` per-layer mutation tests | **VALID**, incomplete | Real production functions, **BUY/BULLISH only**; no `bias`, no `sweep` |

---

# 10. Baseline Integrity (brief §15)

| Check | Result |
|---|---|
| `git status -- baselines/` | **empty — untouched** |
| `baseline_004` / `baseline_005` `run_fingerprint` | `1276a31f673a5a82b2879ea5113b12e486da0d2491d03127` — unchanged |
| Dataset hash | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` — unchanged |
| R1 fixtures | `tests/integration/test_r1_same_bar_regression.py` untouched; ledger fingerprints pinned and passing |
| Production source | `git diff -- '*.py'` **empty** |
| Thresholds / configuration | **unchanged** |
| Files added | 3, all under `tests/` |

---

# 11. Remaining Unresolved Strategy Decisions

**None resolved by this phase.** Carried forward in dependency order:

| ID | Decision |
|---|---|
| **D-6N-1** | Does session eligibility belong inside regime classification? |
| **D-6OB-1** | Should a pullback be required for entry? |
| **D-6OC-1** | Should a sweep/CHoCH be required? |
| **D-6OD-1** | Nearest or strongest liquidity level? |
| **D-6OE-1 / D-6OF-1** | May L2 reverse L1's direction? |
| **D-6OF-2** | If reversal stays, must `bias` be reassigned? |
| **U9-RR** | The RR minimum — blocked behind D-6N-1 |
| **U10-B** | Absolute or relative ATR bands |
| Plus | D-6OB-2…7, D-6OC-2…6, D-6OD-2…6, D-6OE-2…6, D-6OF-3…7 |

---

# 12. What This Pin Would Detect

| Change | Detected by |
|---|---|
| Removing or altering the BOS flip | `PinnedSideStateConsistency` (3 tests) + the BROKEN identity |
| Reassigning `bias` on flip (D-6OF-2) | `test_the_flip_does_not_reassign_bias` |
| Passing `side` to L3 instead of `bias["bias"]` | `test_l3_is_called_with_the_stale_bias` |
| Any change to the BROKEN predicate | `test_broken_always_satisfies_the_flip_condition` |
| Unifying the four fractal copies, or changing one | `PinnedFractalImplementationsAgree` |
| Fixing L3's `ema20` name mismatch | `test_the_ema_fields_are_always_none` |
| Raising `MIN_PULLBACK_QUALITY` above 5.0 | `test_min_pullback_quality_is_unreachable` |
| Changing the L3 depth band | `test_the_documented_depth_cap_is_0786_not_0618` |
| Honouring the regime `poi_threshold` | `test_the_regime_poi_threshold_is_ignored_by_the_gate` |
| Adding a minimum-size or mitigation rule to L6's POI | `test_best_poi_is_never_none_with_twenty_bars` |
| Repairing the L5 `reasoning` collision | `test_the_reasoning_key_collision_masks_sweep_diagnostics` |
| Making `rr` market-derived (breaking the tautology) | `test_rr_equals_tp_ratio_for_every_regime` |
| Any regime-band, session-boundary or kill-zone change | `PinnedRegimeAndSession` (4 tests) |
| Any shift in the regime mix, layer funnel or side mix | `PinnedAggregateFingerprint` |
| Editing the frozen decision stream | The four checksums + 4 recomputation tests |

**What it would not detect**, and should be closed next: a change to L4's
selection rule, clustering tolerance or pre-filter; a change to the L7 weights or
cohesion; a change in per-decision stop, target or RR values; and any SELL-side
behaviour not mirrored in the BUY-side leakage tests.

---

# 13. Recommended Next Step

> **Phase 6Q — close the remaining pins, tests only. Then D-6N-1.**

Three gaps, in order:

1. **L4** — pin nearest-not-strongest selection, the `$1.50` dollar tolerance,
   single-linkage chaining and the self-disabling `≥ 60` pre-filter. These are
   measured in Phase 6O-D and are the largest unpinned surface.
2. **SELL-side leakage tests** — every per-layer mutation test is BUY/BULLISH
   only, and `bias` and `sweep` have none at all. **L1 and L5 are the two layers
   with no temporal test, and L1 decides direction.**
3. **L7** — pin the weights, the cohesion double count and the duplicated
   `55/70` threshold.

**Only then decide D-6N-1, and only after that U9-RR.** The ordering matters
because D-6N-1 changes the DEAD_CALM population nineteenfold and moves 2,193
decisions across the L8 RR gate that U9-RR would set.

---

# 14. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff -- '*.py'` empty |
| Strategy behaviour | **Unchanged** |
| Thresholds / regime / session / L2 reversal | **Untouched** |
| U9-RR, D-6N-1 | **Not decided** |
| Baselines, R1 fixtures, dataset | **Read only; verified unchanged (§10)** |
| Files added | `tests/backtest/test_behavior_pin.py`, `tests/fixtures/behavior_fingerprint.json`, `tests/fixtures/generate_behavior_fingerprint.py` |
| Vacuous tests | **Classified, none deleted** |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
