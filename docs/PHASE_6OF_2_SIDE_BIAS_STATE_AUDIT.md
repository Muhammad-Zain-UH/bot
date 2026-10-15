# Phase 6OF-2 — L2 Side/Bias State-Consistency Audit

**Audit only. No production source changed.** No threshold, regime/session or
U9-RR change. `baseline_004`, `baseline_005`, the R1 fixtures and the dataset
were read only.

**Input:** commit `92283b8` (D-6N-1).

---

# 0. A correction to the brief's premise

The brief presents two populations — *"1,738 L2 reversals"* and *"1,845
decisions where L3 uses a direction the pipeline abandoned"* — and asks whether
they are the same.

**They are the same measurement at two different commits.** 1,738 was the
reversal count **before** D-6N-1; 1,845 is the count **after** it. The rise
follows from 887 more decisions passing L1 and therefore reaching L2 at all, not
from any change to L2. At HEAD there is one number: **1,845**.

**But the underlying instinct is right, and there is a real split** — just not
that one. It is measured in §3.

---

# 1. Executive Summary

**The question splits in two, and the two halves have different answers.**

## 1.1 The finding that changes the priority

`main_production.py:1056`, inside the entry-signal payload:

```python
"position_type": "BUY" if bias["bias"] == "BULLISH" else "SELL",
```

**`position_type` is derived from the stale `bias`, and it is what sets the
broker's order side** — `backtest/replay_engine.py:408` does
`Side.from_bias(str(entry_signal.get("position_type", "")))` and nothing else
determines the side.

Meanwhile `entry_price`, `stop_loss` and `take_profit` in the same dict come
from `get_entry_trigger(..., direction=side)` — the **reversed** side.

> **On a reversed decision that produced a signal, the order would be opened in
> the original direction while its stop and target were constructed for the
> opposite one.** A BUY with its stop above entry and its target below.

**Exposure: 250 reversals were blocked at L8 — one gate short of emitting it.**
**Occurrences: 0.** All four signals have `bos_flip = False`, so
`direction == position_type` on every one. **The defect is real, severe and has
never fired.**

## 1.2 The author said bias should follow

The flip's own comment, `main_production.py:746`:

> *"…if the break is fresh (this candle) and the OPPOSITE direction shows valid
> structure of its own, **flip side/bias** and continue the pipeline…"*

**The comment claims it flips bias. The code flips only `side`.** That is
contemporaneous evidence of intent, in the commit that introduced the flip.

## 1.3 The L3 half is genuinely open

Reassigning `bias` changes which direction L3 measures a pullback in.
**MEASURED counterfactually: 294 of the 1,070 decisions where L3's verdict binds
would change — 27.5 %, nearly balanced (161 newly pass, 133 newly blocked).**

No document states which direction L3 should validate. **That half is a design
decision, not a defect.**

## 1.4 `bias_strength` cannot be transformed

It is `min(10.0, abs(ema20 - ema50) / threshold)` — **a magnitude with no sign**.
Direction lives entirely in the label. On the **H1 fast path there are no
direction-dependent terms at all**, so a flip leaves it unchanged; on the **H4
path** the −2.0 midpoint and −1.5 two-candle penalties are direction-dependent
and would have to be **recomputed, not negated**.

**MEASURED: 1,655 of 1,845 reversals are on the H1 path.** MODEL 3 therefore
differs from MODEL 2 for at most **190** decisions, and even there no safe
arithmetic transformation exists. **MODEL 3 is UNRESOLVED.**

---

# 2. Historical Evidence (Part A)

| Source | Evidence |
|---|---|
| `c3cf4df`, `a6f9f4b` (2026-07-01) | **No flip.** 0 matches for `bos_flip` / `STRUCTURE-2` |
| **`4c90b81`** (2026-09-16) | **The only commit that introduces or touches the flip.** 4 matches |
| `main_production.py:746` (that commit) | *"flip **side/bias** and continue"* — **states bias should follow; the code does not** |
| `structure_engine` docstring (`c3cf4df`, unchanged) | *"Bot waits 3+ candles for new structure to form before resuming"* — **reversal is documented nowhere** |
| **`PHASE_4B_STRATEGY_AUDIT.md:107`** | BOS flip classified **"CORRECT (see caveat)"** |
| **`PHASE_4B_STRATEGY_AUDIT.md:124-130`** | *"**Caveat:** a direction chosen at L1 and reversed at L2 means the L1 gate and the final direction can disagree, and nothing downstream re-validates the original bias."* |
| `PHASE_4B_STRATEGY_AUDIT.md:47-52` | *"Of everything L1–L7 compute, only **two values** reach the entry decision: `side` … and `sweep_wick_low`/`high`. Everything else is a **pass/fail gate**."* |

**What the evidence supports:**

| Claim | Verdict |
|---|---|
| Reversal should update `side` | **Established** — implemented and assessed CORRECT in Phase 4B |
| Reversal should update `bias` | **Supported by the author's own comment**, contradicted by the code. No other source |
| Reversal should update `bias_strength` | **No evidence whatsoever** |
| Reversal should update nothing | **Contradicted** — `side` is updated today |

**Phase 4B saw the divergence and recorded it as a caveat, not a defect.** It did
not observe the `position_type` consequence — §1.1 is new.

---

# 3. State Model (Part B)

| # | Field | Producer | Consumers **after** the flip | L2 mutates? | Represents |
|---|---|---|---|---|---|
| 1 | `L1_INITIAL_SIDE` | `_bias_to_side(bias)` `:721` | — (superseded) | **overwritten** | execution intent, pre-flip |
| 2 | `L1_BIAS` | `get_fast_bias` / `get_h4_bias` | **L3** `:797` · **`position_type`** `:1056` | **NO** | analysis + (accidentally) execution |
| 3 | `L1_BIAS_STRENGTH` | same | **L7** `:945` | **NO** | analysis confidence |
| 4 | `L2_EFFECTIVE_SIDE` | flip `:774` | L4 `:840` · L5 `:870` · L6 `:911` · L8 trigger · stop anchor | **YES** | execution |
| 5 | `L3_BIAS_INPUT` | `bias["bias"]` `:797` | `get_m15_pullback` | **NO** | analysis |
| 6 | `FINAL_SIDE` | **`position_type`** `:1056` ← `bias` | `Side.from_bias` → broker | **NO** | **execution** |

**`bias` is consumed at exactly three places after the flip** — L3, L7 and
`position_type`. **L4, L5, L6 and L8 all use `side`.**

**`analysis["layer_1"]` is written and never read** by any production module. It
is a record field; its staleness is an observability issue only.

> **The decisive asymmetry: field 4 is the reversed side, field 6 is the
> original. Both are execution state. They are meant to be the same thing.**

---

# 4. Population Reconciliation (Part C)

**A** = L2 reversed the side. **B** = L3 consumed a stale bias **and its verdict
bound the outcome**.

| Set | Count | Composition |
|---|---|---|
| **A** | **1,845** | all reversals |
| **A only** | **775** | **all MICRO_SCALP** — `bypass_l3` is true, so L3 runs on the stale bias and its result is **discarded** |
| **A ∩ B** | **1,070** | REGIME_SCALP 880 · INTRADAY_SWING 190 |
| **B only** | **0** | L3 can read a stale bias only if a reversal occurred |
| **A ∪ B** | **1,845** | |

**The exact state condition producing A-only:** `detect_regime` sets
`bypass_l3 = True` for MICRO_SCALP. `main_production` calls
`get_m15_pullback(m15_data, bias["bias"])` **before** testing `bypass_l3`, so the
stale-bias pullback is always computed; for MICRO_SCALP it is then ignored.

**D-6N-1 enlarged A-only.** MICRO_SCALP grew 5,121 → 7,314, so more reversals now
fall in the regime whose L3 verdict is discarded.

### Exposure

| Reversals reaching | Count |
|---|---|
| L3 (all) | 1,845 |
| L8 — where `position_type` would be emitted | **250** |
| **A signal** | **0** |

---

# 5. Counterfactual Models (Part D)

**No model was implemented.** L3 was evaluated twice per reversal — once with the
stale bias, once with the flipped one — using the production
`get_m15_pullback` and the production gate `detected AND quality >= 1.5`.

| Consumer | MODEL 1 (current) | MODEL 2 (+bias label) | MODEL 3 (+strength) |
|---|---|---|---|
| **L3** direction | stale | **flipped** | **flipped** |
| **L7** `bias_strength` | stale | **unchanged** | **recomputed** |
| **`position_type`** → broker side | **stale** | **flipped** | **flipped** |
| `analysis["layer_1"]` record | stale | stale unless also written | stale unless also written |
| L4 / L5 / L6 / L8 | `side` — **unchanged under every model** | | |
| Entry price / stop / target | `side` — **unchanged under every model** | | |

### MODEL 2 — measured effect on L3

| Population | n | Same verdict | False→True | True→False | **Changed** |
|---|---|---|---|---|---|
| All reversals | 1,845 | 1,376 (74.6 %) | 238 | 231 | **469 (25.4 %)** |
| **Binding (A ∩ B)** | **1,070** | 776 (72.5 %) | **161** | **133** | **294 (27.5 %)** |

**Nearly balanced in both directions** — 161 newly pass, 133 newly blocked. This
is a redirection of the gate, not a loosening of it.

**L3 quality on the binding population:** stale median **6.50**, flipped median
**2.50**. Measuring a pullback in the newly-traded direction immediately after a
structure break generally finds none — price has just moved impulsively that way
and has not retraced. Measuring in the abandoned direction makes the break itself
look like a deep retracement. **Stated descriptively; it argues for neither
model.**

### MODEL 2 — effect on `position_type`

**On every reversal, `position_type` would change to match `direction`.**
Today they disagree on all 1,845; under MODEL 2 they agree on all 1,845.
**Signal impact: 0 today, because no reversal has ever produced a signal.**

### MODEL 3 — additional effect

Only on the **190** H4-path reversals, and only by recomputation (§6). For the
**1,655** H1-path reversals **MODEL 3 ≡ MODEL 2**.

**Final signal changes under every model: 0** — no reversal reaches a signal, so
no model alters the four.

---

# 6. `bias_strength` (Part E)

```
both engines:  strength = min(10.0, abs(ema20 - ema50) / ema_threshold)
H4 only:       strength = max(0.0, strength - 2.0)   # daily-midpoint conflict
               strength = max(0.0, strength - 1.5)   # 2-candle-close conflict
               strength = 0.0                        # if both (FIX BIAS-1)
```

| Question | Answer |
|---|---|
| Does the sign carry direction? | **No.** `abs()` — always ≥ 0. Direction is only in the label |
| Does magnitude represent confidence? | **Yes** — EMA separation relative to the threshold, capped at 10 |
| Is it safely negatable? | **No.** Negation is meaningless for a magnitude |
| Is it invariant under a flip? | **On the H1 path, yes** — no direction-dependent term exists |
| On the H4 path? | **No.** The midpoint and 2-candle penalties are direction-dependent: a BULLISH bias penalised for `close < midpoint` would, as BEARISH, be *confirmed* by that same condition |

> **There is no transformation, only re-derivation.** Turning a penalised
> BULLISH strength into a BEARISH one requires re-running both confirmations
> against the new direction — which is `calculate_h4_ema_bias` with a different
> label, not arithmetic on a number.
>
> **MODEL 3 is therefore UNRESOLVED**, and it is relevant to at most **190 of
> 1,845** reversals (10.3 %).

---

# 7. Temporal Correctness (Part F)

**The proposed repair introduces no future-data dependency.**

`flipped_side` is derived entirely from values already in hand at the flip point:
`side` (from L1), `h1_close` (`h1_data.iloc[-1]["close"]`, already read for the
BROKEN test) and `last_swing_high`/`last_swing_low` (from the same
`get_h1_structure` call). **Assigning `bias` alongside `side` reads nothing new
and accesses no frame.**

MODEL 3 would call `calculate_h4_ema_bias` a second time on the **same already-cut
H4 and D1 frames** — still no new data access.

**Temporal risk: none.** Confirmed against the leakage suites, which pass
unchanged.

---

# 8. BUY/SELL Symmetry (Part G)

The flip predicates mirror exactly (pinned by `PinnedL2FlipIsAnIdentity`), and
L3 was proven symmetric in Phase 6O-B.

**Counterfactual verdict changes, binding population:**

| Effective side | n | Verdict changes |
|---|---|---|
| BUY | 671 | 171 (**25.5 %**) |
| SELL | 399 | 123 (**30.8 %**) |

**The code is symmetric; the outcome is not, and that difference lives in the
data.** No cause is inferred, and nothing here was chosen to balance the two.

---

# 9. Required Tests (Part H)

**Not implemented.** These are what a future contract change must be protected
by; the first four already exist as pins of *current* behaviour and would fail by
design.

| # | Test | Status |
|---|---|---|
| 1 | No reversal → `bias`, `side` and `position_type` all unchanged | **New** |
| 2 | BUY → SELL reversal: `side`, `bias`, `position_type` agree | **New** — inverts `test_the_flip_does_not_reassign_bias` |
| 3 | SELL → BUY reversal: same | **New** |
| 4 | **`position_type == direction` on every emitted signal** | **New — the highest-value test in this list.** Would have caught §1.1 |
| 5 | **`position_type` is consistent with `stop_loss` relative to `entry_price`** (BUY ⇒ stop below) | **New** — an independent guard that does not depend on the flip at all |
| 6 | L3 consumes the effective direction | **New** — inverts `test_l3_is_called_with_the_stale_bias` |
| 7 | `bias_strength` contract: recomputed, not transformed | **New**, only if MODEL 3 is chosen |
| 8 | `analysis["layer_1"]` record consistency | **New** — inverts `test_layer_1_record_is_not_corrected_by_the_flip` |
| 9 | Side-state matrix has zero `L3 != L1` rows | **Exists**, inverted |

---

# 10. Classification (Part I)

**The question does not have one answer. It has three.**

| Component | Classification | Basis |
|---|---|---|
| **`position_type` derived from stale `bias`** | **IMPLEMENTATION DEFECT** | The signal payload would declare a direction contradicting its own stop and target. No reading of intent makes a BUY with the stop above entry correct, and the flip's own comment says *"flip side/bias"*. **Latent: 0 occurrences, 250 decisions one gate away** |
| **L3 reading the abandoned direction** | **DESIGN DECISION** | Arguable both ways — validate the new thesis, or re-validate the old before accepting a reversal. **No document states which.** 294 of 1,070 binding verdicts would change |
| **`bias_strength` under a flip** | **INTENT AMBIGUOUS / UNRESOLVED** | No safe transformation exists; only re-derivation. No evidence of intent. Relevant to 190 decisions |
| `analysis["layer_1"]` staleness | **Observability defect** | Written, never read by production |

**The whole question is not "IMPLEMENTATION DEFECT" and not "DESIGN DECISION" —
it is one of each plus an unresolved third.** Treating them as a single change
would bundle a correctness repair with a strategy choice.

---

# 11. Exact Proposed Next Implementation Step

> **Split D-6OF-2. Implement only the `position_type` repair. Leave L3 and
> `bias_strength` alone.**

**Step 1 — correctness, no strategy content.**

```
"position_type": "BUY" if bias["bias"] == "BULLISH" else "SELL",
                 →  derive from `side`
```

**Why it is safe to separate:** `position_type` is consumed only by
`Side.from_bias` to set the broker side. It reaches **no gate**. Changing it
cannot alter which decisions pass, only what an emitted order says — and **no
reversal has ever emitted one**, so the measured behavioural delta is **exactly
zero decisions and zero signals**. It removes a latent contradiction without
touching strategy.

**It should be accompanied by test 5 above** — `position_type` consistent with
the stop's side of entry — which guards the property independently of the flip.

**Step 2 — a separate decision, not bundled:** whether L3 should read the
effective direction (MODEL 2's L3 half). **294 of 1,070 binding verdicts change,
nearly evenly split.** This is a strategy-contract change and needs its own
before/after replay, like D-6N-1.

**Step 3 — deferred:** `bias_strength` (MODEL 3). Unresolvable without deciding
whether the H4 confirmations should be re-derived; 190 decisions.

**U9-RR remains blocked**, but the reason has narrowed. It is blocked by **Step
2**, not by the whole of D-6OF-2 — L3's verdict binds on 1,070 decisions and
would move on 294 of them. **Step 1 does not block U9-RR and could precede it.**

---

# 12. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff -- '*.py'` empty |
| Model chosen | **None** — §5 compares, §11 proposes a split for decision |
| Thresholds / regime / session / U9-RR | **Untouched** |
| Baselines, R1, dataset | **Read only** |
| Counterfactual | Read-only re-evaluation of `get_m15_pullback`; nothing written |
| Artifacts added | `audit/d6of2/cf.py`, `audit/d6of2/counterfactual.json` |

**No profitability conclusion is drawn or available.**
