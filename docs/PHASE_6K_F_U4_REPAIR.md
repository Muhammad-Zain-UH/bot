# Phase 6K-F — U4: Deterministic RR Representation Repair

**A correctness repair, not a strategy-policy decision.** No threshold, regime
mapping, style gate, quality threshold, `tp_ratio`, stop construction,
`take_profit` construction or DEAD_CALM behaviour was changed. The runtime RR
gate is neither removed nor relocated. **U9 — the numerical minimum — remains
untouched and undecided.** `baseline_004` and `baseline_005` untouched, not
regenerated, not re-pinned. R1 fixtures and fingerprints unchanged.

**Input:** Phase 6K-E `e4f5fb4`.

---

# 1. The Change

**One functional line**, `entry_engine.calculate_entry_levels`:

```diff
- reward_distance = abs(take_profit - entry_price)
+ reward_distance = risk_distance * tp_ratio
```

`rr = reward_distance / risk_distance if risk_distance > 0 else 0` is
**unchanged**, preserving the existing zero-risk contract exactly. No epsilon
was introduced, `rr` is not rounded, and no comparison semantic was altered.

**Why.** `take_profit` is built as `entry_price ± risk_distance * tp_ratio` two
lines above. Recovering the reward by subtracting `entry_price` back out adds a
small quantity to a large one and discards the addend's low bits, in proportion
to `entry_price / (risk_distance * tp_ratio)`. On the 2026-08-06 candidate that
ratio is **1,065×**, costing about four significant digits:

```
risk_distance * tp_ratio              = 3.9974999999999454     the product
|(entry + product) - entry|           = 3.9974999999994907     after the round trip
                                        ^^^^^^^^^^^^^^^ 4.5e-13 destroyed
rr, old = 1.4999999999998295   ->  below 1.5, REJECTED
rr, new = 1.5                  ->  meets 1.5, ADMITTED
```

---

# 2. Measured Effect

**MEASURED.** Full replay of the verified dataset (SHA-256 `433b7e27…`), the
same data behind both baselines, with `capture_all_snapshots=True`.

| Metric | Pre-U4 | Post-U4 | Δ |
|---|---|---|---|
| Decisions | 15,735 | 15,735 | **0** |
| Reached L8 | 1,265 | 1,265 | **0** |
| Blocked at L8 | 1,262 | **1,261** | **−1** |
| **Signals** | 3 | **4** | **+1** |
| Orders | 3 | 4 | +1 |
| L1, L2, L3, L4, L5, L6, L7 blocks | — | **all identical** | **0** |

```
decisions_fingerprint  pre   127fd774d795b1ccdecbed40bca8348615d145161583aa9171258c809f13af3d
                       post  8aef2341c8c8e953c1ff004ca7ef25ba89d0d0329fa297033013c1741fc7950f
```

## 2.1 The complete list of changed decisions — **one**

| Timestamp (UTC) | Regime | Side | Change |
|---|---|---|---|
| **2026-08-06 08:00** | MICRO_SCALP | BUY | blocked at L8 → **ENTRY_SIGNAL** |

**Signals added: 1. Signals removed: 0. Signals kept: 3.**

## 2.2 Explanation of the one changed decision

**It is the candidate this repair was predicted to affect, and the only one.**

| | |
|---|---|
| `trigger_quality` | **10.0** — already passed `>= 5.0` at the maximum |
| `rr`, before | `1.4999999999998295` — failed `>= 1.5` by `1.7e-13` |
| `rr`, after | **`1.5`** — meets the threshold |
| Recorded reason, before | `"micro scalp quality too low (quality=10.0, rr=1.5)"` |
| Recorded reason, after | **gone — that string no longer appears anywhere in the run** |

**The threshold did not move. The candidate's geometry did not move.** Only the
representation of a quantity that was always `1.5` in exact arithmetic changed.
The decision was previously made by floating-point error; it is now made by the
comparison the code says it makes.

**The misattributing message is gone by consequence, not by edit.** It was the
only occurrence of that reason in the entire run, and it disappeared because the
rejection it described no longer happens. `evaluate_entry_for_regime`'s message
text is untouched, and the defect recorded in Phase 6J §G.2 — that it blames
quality when `rr` fails — **still exists** and is still unfixed.

## 2.3 Why nothing else changed

**The 263 MICRO_SCALP candidates measured below `1.5` did not become signals.**
**OBSERVED:** they never reach `evaluate_entry_for_regime`, because
`entry_triggered` is false for them — the gate is reached only after the trigger
has already fired. They were only ever a measure of how wide the artefact was,
not a population awaiting admission. Phase 6J stated this caveat; the measurement
confirms it.

**No signal was removed**, so the repair did not flip anything the other way on
this dataset.

---

# 3. What This Repair Does **Not** Fix

**U4 narrows the boundary hazard by about three orders of magnitude. It does not
remove it.**

**MEASURED:** `(R × k) / R` is **not** exactly `k` for every `R`. Across
1,200,000 random `(R, k)` pairs it differed in **119,549 cases — roughly 10 %** —
always by one ulp, in either direction.

| | Error magnitude |
|---|---|
| Old reconstruction | ~`1.7e-13` |
| New product form | ≤ ~`2.2e-16` (1 ulp) |

**MICRO_SCALP's threshold still equals its own `tp_ratio` exactly**, so a
candidate whose `(R × 1.5) / R` rounds one ulp low would still be rejected. None
did on this dataset — all four gate-reaching candidates evaluate to exactly
`1.5` — but the structural coincidence is unchanged.

**That coincidence is U9, not U4.** This repair makes the comparison
deterministic and auditable; it does not make a threshold set equal to the
quantity it tests a sound design. Pinned by
`test_the_boundary_is_narrowed_but_not_removed`.

**Also unchanged, and still open:** the misattributing rejection message
(Phase 6J item 9), DEAD_CALM's admissibility (U5), the quality thresholds (U1),
and the numerical minimum (U9).

---

# 4. Tests

**9 added**, all in `tests/backtest/test_valid_rr_retired.py`.

**`U4RewardIsTheConstructionQuantity`**

| Test | Asserts |
|---|---|
| `test_reward_distance_is_risk_times_ratio` | `reward_distance == risk_distance * tp_ratio` **exactly**, across 4 entry/stop geometries × 4 ratios, **both directions** |
| `test_non_integer_ratios_behave_the_same` | Same for `1.25, 1.75, 2.33, 2.75, 3.5` |
| `test_take_profit_is_unchanged_by_the_repair` | The target construction is untouched, both directions |
| `test_the_zero_risk_contract_is_unchanged` | A zero-width stop still yields `rr == 0`. **Existing semantics, not new** |
| `test_a_missing_anchor_still_falls_back_to_the_atr_stop` | Pins the ATR fallback, which is easily mistaken for the zero-risk path |

**`U4TheBoundaryCandidate`**

| Test | Asserts |
|---|---|
| `test_the_old_reconstruction_fell_below_the_threshold` | Preserves the historical value `1.4999999999998295` |
| `test_the_construction_quantity_reaches_the_threshold` | The product form gives exactly `1.5` |
| `test_the_gate_now_admits_it_on_rr` | The gate admits it, quality having always passed |
| `test_the_boundary_is_narrowed_but_not_removed` | §3 — the repair is not a fix to the threshold coincidence |

**One existing test was corrected, and it was my own error.**
`test_the_zero_risk_contract_is_unchanged` was first written to reach the
zero-risk path by omitting the anchor. It does not: with no wick and no
structure the stop comes from the **ATR fallback** (`risk = 30.0`). The test now
reaches the real path — a BUY wick `3.0` above the entry, giving a stop exactly
at the entry — and a second test pins the ATR fallback so the two are not
confused again.

**No test that uses impossible `rr` values was modified.**
`tests/test_entry_quality_gate.py` still passes `rr` of 1.4 / 2.4 / 2.8 against
regimes whose `tp_ratio` is 1.5 / 2.0 / 3.0 — values that cannot occur in
production (Phase 6J §F.1). **U4 does not make those tests valid and did not
need to change them**, so they were left alone; rewriting them is U7 and belongs
with the gate's own decision.

---

# 5. Validation

| | |
|---|---|
| **Full suite** | **969 tests, 2 failures, 0 errors** |
| The 2 failures | `test_micro_scalp_l7_confidence_uses_55_threshold`, `test_pullback_gate_requires_real_pullback_detection` — **both pre-existing**, unchanged by U4, and both fail upstream at L1/L2 without reaching this code |
| **R1 fixtures** | **25/25 pass, fingerprints unchanged.** Checked before committing, as a STOP condition |
| Focused U4 tests | 29/29 in the file |

**Why R1 is unaffected.** Both fixtures run at `tp_ratio 3.0` against
INTRADAY_SWING's `2.5` threshold — a margin of `0.5`, roughly twelve orders of
magnitude above either error. Their ledger fingerprints are pinned and
unchanged.

**Baselines.** Neither was regenerated or re-pinned. They contain zero trades,
so the changed decision affects no figure in either artefact. Their recorded
`decisions_fingerprint` (`e9421f30…`) describes the strategy path as it was at
`04a341d` and is not comparable to current code — established in Phase 6D.

---

# 6. Scope Confirmation

| | |
|---|---|
| U9 (the numerical minimum) | **UNTOUCHED.** No value chosen, proposed or implied |
| Thresholds `1.5 / 2.0 / 2.5` | **Unchanged** |
| Quality thresholds `5.0 / 6.0 / 7.0` | **Unchanged** |
| `tp_ratio` values | **Unchanged** |
| DEAD_CALM | **Unchanged** — still barred at `1.5 < 2.0`, still by accident (6K-E §7) |
| The runtime RR gate | **Neither removed nor relocated** |
| `take_profit`, stop construction, regime mapping, style gates | **Unchanged** |
| Epsilon / tolerance / rounding of `rr` | **None introduced** |
| `baseline_004` / `baseline_005` | **Untouched** |
| R1 fixtures | **Untouched** |

**The one changed decision is the expected and intended consequence of
correcting the arithmetic representation**, and it was not suppressed to
preserve a fingerprint. **No profitability conclusion is drawn or available:**
the four admitted signals have never been executed, held or closed in any
measurement.
