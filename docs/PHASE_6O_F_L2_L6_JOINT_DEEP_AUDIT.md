# Phase 6O-F — L2 + L6 Joint Deep Audit

**Audit only. No source changed.** No threshold, no refactor, no strategy
optimisation, no regime/session change. U9-RR is not resolved. `baseline_004`,
`baseline_005` and the R1 fixtures were read, never written.

**Input:** commit `e5ce520` (Phase 6O-E). Statistics come from the **frozen**
`baselines/baseline_005/decisions.jsonl` (15,735 records) and the frozen dataset
`433b7e27…`.

---

# 1. Executive Summary

**L2's 174-of-174 rescue rate is not an empirical coincidence. It is a
mathematical identity, and this audit proves it.**

`structure_engine.validate_h1_structure` returns `BROKEN` under exactly two
conditions, and there are no others:

```
BULLISH  BROKEN  ⟺  current_close < last_low      (structure_engine.py:243)
BEARISH  BROKEN  ⟺  current_close > last_high     (structure_engine.py:311)
```

`main_production`'s BOS flip fires under:

```
side==BUY   ∧  h1_close < last_swing_low          (main_production.py:760)
side==SELL  ∧  h1_close > last_swing_high         (main_production.py:758)
```

`h1_close` **is** `current_close`; `last_swing_low/high` **are** `last_low/high`
from the same call. **The predicates are identical. `BROKEN` therefore *implies*
the flip condition, always, by construction.** The only genuinely empirical term
is the opposite-side revalidation — and that failed **7 times in 15,735
decisions**.

**Eight findings.**

1. **The documented remedy for BROKEN is not reversal.** `structure_engine`'s
   docstring, unchanged since `c3cf4df`: *"If H1 closes beyond last HL (bullish)
   or LH (bearish) → structure broken. **Bot waits 3+ candles for new structure
   to form before resuming**."* **Reversal appears in no documentation.**

2. **The flip did not exist originally.** **MEASURED: 0 matches for
   `STRUCTURE-2`/`bos_flip` at `c3cf4df` and at `a6f9f4b` (both 2026-07-01); 4
   matches at `4c90b81` (2026-09-16).**

3. **1,738 of 13,343 decisions — 13.03 % — carry a direction opposite to the one
   L1 chose.** Established two independent ways that agree exactly: direct
   measurement of `BROKEN` (174/1,335 = 13.03 %), and comparison of a recomputed
   L1 bias against the frozen recorded side across all 15,735 records
   (1,738/13,343 = 13.03 %).

4. **`SELL→BUY` 1,012 vs `BUY→SELL` 726** — 58.2 % / 41.8 %, from provably
   symmetric code, over a period in which gold rose 18.6 %.

5. **L2 blocks 7 decisions in 15,735 — and all 7 are one market event.**
   **MEASURED: every one carries the identical reason string,
   `"Close 4089.40 > last_high 4082.04"`** — seven consecutive M5 decisions
   inside a single H1 bar. **L2 rejected exactly one distinct event in the entire
   dataset.**

6. **L6 blocks 1 decision in 15,735.** Of 2,764 arrivals, **1,740 are bypassed**
   (MICRO_SCALP) and only **1,024 evaluated — of which 1,023 pass (99.90 %)**.

7. **L6 does not validate L2.** `poi_engine` contains **no structure input, no
   fractal routine and no reference to L2's output**. It inherits `side` — the
   post-flip side — and therefore **cannot disagree with the reversal**.

8. **`detect_regime`'s `poi_threshold` (50/60/70) is dead.** The L6 gate uses
   `poi_threshold = 60 if sweep_confirmed else 70` (`main_production.py:919`),
   ignoring the regime value entirely. The regime field survives only in display.

**And the fractal count is now four.** `bias_engine._find_h4_swings`,
`structure_engine.find_h1_swings`, `pullback_detector._find_recent_fractal_swing`,
`sweep_detector._find_recent_fractal_level`. **MEASURED: on identical 25-bar
windows all four agree 1,621 / 1,621 = 100.00 %.**

---

# 2. L2 — Historical Intent

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | `c3cf4df` | `structure_engine.py` created. Docstring as it still reads. **No flip anywhere** |
| 2026-07-01 | `a6f9f4b` | **No flip** (verified) |
| 2026-09-16 | **`4c90b81`** | **FIX (STRUCTURE-1)**: HH/HL progression loosened from `>= 2` to `>= 1` in both series. **FIX (STRUCTURE-2): the BOS flip appears in `main_production`** |

### 2.1 The documented contract

```
BULLISH STRUCTURE VALID: HH and HL · last H1 swing low NOT broken by a close
                         · H1 ATR expanding · close > previous HL
STRUCTURE INVALIDATION : close beyond last HL (bullish) or LH (bearish) → broken
                         Bot waits 3+ candles for new structure to form before resuming
```

| Documented | Implemented? |
|---|---|
| HH/HL progression | **Yes**, but loosened to `>= 1` of 4 steps in each series |
| Last swing low not broken | **Yes** — this is the `BROKEN` test |
| **H1 ATR expanding** | **NO.** `grep -c "atr\|ATR" structure_engine.py` = **2**, both in the docstring. **No code** |
| close > previous HL | **NO** — not tested separately |
| **Wait 3+ candles** | **NO** — replaced by immediate reversal |

**Intended meaning of BROKEN:** structure invalidated, **pause**.
**Intended meaning of reversal:** *none recorded.* FIX (STRUCTURE-2)'s own
comment is the only statement of intent: *"A confirmed close beyond the last
swing high/low, opposite the current bias, is itself a standard, tradeable
reversal signal."* **That is a claim made in a code comment, corroborated by no
document.**

**Was opposite-side rescue always present? No — it is 2½ months younger than the
layer.** **Was reversal intended to modify the trade or only the analysis?** The
code modifies the trade: `side`, `analysis["direction"]`, `struct` and
`struct_type` are all reassigned and the pipeline continues. **No source states
which was intended.**

---

# 3. The Exact L2 Contract

## 3.1 Three concepts the brief asked to be separated

| Concept | Where | Predicate |
|---|---|---|
| **A. Structure invalid** | `structure_engine.py:243 / 311` | `close < last_low` (bullish) · `close > last_high` (bearish) |
| **B. Reverse direction** | `main_production.py:757-761` | `side==BUY ∧ close < last_swing_low` · `side==SELL ∧ close > last_swing_high` |
| **C. Opposite structure valid** | `main_production.py:764-766` | `get_h1_structure(h1, flipped).structure_type ∈ {HH/HL, LH/LL}` |

> **A and B are the same predicate.** Same close, same swing levels, same
> comparison. **A ⟹ B is a theorem, not an observation.** Only **C** is
> empirical.

## 3.2 Full contract

```
INPUT  : h1_data (60 bars), expected_bias ∈ {BULLISH, BEARISH}
SWINGS : find_h1_swings(h1, lookback=50)      ← 5-bar fractal, 4th copy
         recent_high/low + second_recent_high/low
         fallback (len<5): max/min, and second = recent × 0.995 / × 1.005   [SYNTHETIC]
CLOSE  : h1_data.iloc[-1]["close"]             ← newest CLOSED bar

BULLISH:
  if close < last_low                     → BROKEN     (structure_valid False)
  elif hh_count >= 1 and hl_count >= 1    → HH/HL      confidence = (hh+hl)/8 × 10
  else                                    → UNKNOWN
BEARISH: mirror with last_high, lh_count, ll_count → LH/LL
len(h1) < 5                               → UNKNOWN

hh_count = _count_consecutive_moves(last_5_highs, "up")   ← counts ANY up-step,
                                                            not consecutive runs

GATE (main_production):
  BROKEN → attempt flip (B ∧ C) ; if flip succeeds, continue with reversed side
         → else  block "L2_STRUCTURE"
  UNKNOWN → pass ("proceed with caution", no record)
  HH/HL or LH/LL → pass
```

**No BOS/CHoCH dependency. No L5 dependency. No ATR. No thresholds beyond
`>= 1`.**

**`_count_consecutive_moves` is misnamed** — it counts every up-step among the 4
adjacent pairs, not consecutive runs. With `>= 1` required, **any 5 H1 candles
with one higher high and one higher low anywhere pass.** **MEASURED: `UNKNOWN`
occurs in only 87 of 1,335 arrivals (6.5 %).**

---

# 4. The 1,738 Reversals

**Method.** The frozen `decisions.jsonl` records the **effective** (post-flip)
side. Recomputing L1's bias for all 15,735 records and comparing identifies every
reversal. **Cross-check:** this yields **13.03 %**, identical to the
independently measured `BROKEN` rate among L2 arrivals (174/1,335 = 13.03 %) from
direct `get_h1_structure` calls. **Two independent methods, same figure.**

| | Count | Share |
|---|---|---|
| Decisions with a side (passed L1) | 13,343 | — |
| **REVERSED** | **1,738** | **13.03 %** |
| **SELL → BUY** | **1,012** | 58.2 % of reversals |
| **BUY → SELL** | **726** | 41.8 % |

| Regime | Reversals |
|---|---|
| REGIME_SCALP | 880 |
| MICRO_SCALP | 620 |
| INTRADAY_SWING | 190 |
| DEAD_CALM | 48 |

| Month | Reversals | | Session | Reversals |
|---|---|---|---|---|
| 2026-06 | 192 | | NewYork | 617 |
| 2026-07 | **740** | | London | 609 |
| 2026-08 | 386 | | Asian | 466 |
| 2026-09 | 420 | | Dead | 46 |

## 4.1 Where reversed decisions ended

| Terminal layer | Reversed | Non-reversed |
|---|---|---|
| L3_PULLBACK | **54.3 %** | 42.4 % |
| L8_ENTRY | **11.5 %** | 9.2 % |
| L5_SWEEP | 11.0 % | 19.4 % |
| L7_CONFIDENCE | 10.1 % | 11.4 % |
| L4_LIQUIDITY | 7.3 % | 4.3 % |
| L5_SWEEP_WAIT | 5.8 % | 13.2 % |

**Reported descriptively.** Reversed decisions die at L3 more often and reach
L8 more often. **No interpretation is offered and none is implied: a higher L8
arrival rate is not evidence that reversal is correct.**

## 4.2 The 7 rescue failures

**MEASURED: L2 blocked 7 decisions, every one with the identical reason
`"H1 structure is broken (Close 4089.40 > last_high 4082.04)"`** — the same
prices, so **seven consecutive M5 decisions inside one H1 bar.** These are the
cases where condition **C** failed: the opposite direction had no confirmed
structure either.

> **L2 rejected one distinct market event in three and a half months.**

---

# 5. Side Mutation and Record Consistency

## 5.1 The mutation

```python
side = flipped_side                    # local variable
analysis["direction"] = side           # updated
analysis["bos_flip"] = True            # recorded
analysis["bos_flip_reason"] = ...      # recorded
struct = restruct ; struct_type = restruct_type
analysis["layer_2"] = struct           # updated
#  analysis["layer_1"]  ← NOT updated
```

## 5.2 Timeline of every `side` read

| Step | Reads | Sees |
|---|---|---|
| L1 | `_bias_to_side(bias)` | **original** |
| L1 record | `analysis["layer_1"] = bias` | **original — never corrected** |
| L2 | `get_h1_structure(h1, bias["bias"])` | **original** |
| **L2 flip** | reassigns `side`, `analysis["direction"]`, `struct` | — |
| L3 | `get_m15_pullback(m15, bias["bias"])` | **ORIGINAL — `bias` was never reassigned** |
| L4 | `identify_liquidity_pools(..., side=side)` | reversed |
| L5 | `get_sweep_and_structure(..., side)` | reversed |
| L6 | `identify_poi(..., direction=side)` | reversed |
| L7 | `bias_strength=bias.get("bias_strength")` | **ORIGINAL bias object** |
| L8 | `get_entry_trigger(..., direction)` | reversed |
| Stop/target | via L8 | reversed |
| Record | `analysis["direction"]` | reversed |

> ## **L3 and L7 read the ORIGINAL bias after a reversal.**
>
> The flip reassigns `side` but **not `bias`**. `analysis["layer_1"]` is never
> corrected either. So on 1,738 decisions, **L3 measures a pullback against the
> pre-flip direction while L4–L6 and L8 work the post-flip direction**, and L7
> scores the pre-flip `bias_strength`.

This is consistent with §4.1: reversed decisions fail L3 at **54.3 %** against
42.4 % — L3 is being asked to find a retracement in the direction the pipeline
has just abandoned. **The correlation is stated; causation is not established
here.**

## 5.3 Classification

| Aspect | Classification |
|---|---|
| `analysis["layer_1"]` retaining the original bias | **Observability defect** — the record disagrees with the trade |
| **`bias` object not reassigned, consumed by L3 and L7** | **STATE INCONSISTENCY** — two layers act on a direction the pipeline has discarded |
| `analysis["bos_flip"]` recorded | **Intentional analytical history** — correctly captured |
| Whether L3/L7 *should* see the reversed side | **UNRESOLVED** — no document addresses it |

---

# 6. L6 — Historical Intent

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | `c3cf4df` | `poi_engine.py` created |
| 2026-09-16 | `4c90b81` | modified |

**Documented purpose:** *"LAYER 6: POI QUALITY ENGINE — Scores entry zones
(Order Blocks, FVGs, Fibs)"*, with four types — **Order Block (30), Fair Value
Gap (25), Fibonacci (25), Breaker Block (20)** — a 100-point formula, and
**"ENTRY THRESHOLD: ≥ 70"**.

| Documented type | Constructed? |
|---|---|
| Order Block | **Yes** |
| Fair Value Gap | **Yes** |
| Fibonacci 0.618 | **Yes** |
| **Breaker Block** | **NO — never constructed.** Documented, base score 20, no producer |

*(The same pattern as L4's `RECENT SWING` pool type, Phase 6O-D.)*

---

# 7. The Exact L6 Contract

```
INPUT : m15_data, h1_data (confluence only), direction = POST-FLIP side, current_price

1. Order Block   : detect_order_block(m15, direction)        → if ob_found
2. Fair Value Gap: detect_fvg(m15, direction)                → if fvg_found
                   untested ⟸ fill_percent < 20 ∧ ¬_zone_touched
3. Fibonacci     : if len(m15) >= 20        ← NO validity test; ALWAYS appended
                   recent_low/high = m15.tail(20).low.min() / .high.max()
                   fib = low + (high-low)×0.618   (BUY)
                       = high - (high-low)×0.618  (SELL)
                   zone = fib ± 2                 ← $2.00, UNLABELLED
                   displacement = |high-low| × 0.382
                   base_score = 25

score_poi(base, untested +30, displacement +20, htf_confluence +20,
          size +15, clarity +15) → cap 100 → tier
poi_zones.sort(score desc) ; best_poi = poi_zones[0]

GATE (main_production.py:919):
  poi_threshold = 60 if sweep_confirmed else 70      ← NOT regime_info["poi_threshold"]
  bypass_l6 (MICRO_SCALP)            → "L6_POI_BYPASSED"
  best_poi is None or score < thresh → block "L6_POI"
  else                               → "L6_POI"
```

**Three consequences.**

1. **`best_poi` is essentially never `None`.** The Fibonacci zone is appended
   unconditionally whenever `len(m15) >= 20`, which always holds (50 bars are
   supplied). **The `"No POI found"` branch is unreachable in production.**
2. **The regime's `poi_threshold` is dead.** `detect_regime` computes 50/60/70
   and `architecture.txt`'s regime table documents it; **the gate ignores it.**
   It survives only in `print_regime_analysis` (`main_production.py:226`).
3. **L6 depends on L5.** `sweep_confirmed` lowers the bar from 70 to 60 — so L5's
   verdict relaxes L6's.

---

# 8. L2 / L6 Dependency Map

```
L1  bias (EMA20−EMA50, regime-selected TF)  ──┬──► side
                                              │
L2  get_h1_structure(h1, bias)                │   ← reads ORIGINAL bias
      BROKEN ⟹ flip condition (identity)      │
      + opposite-structure revalidation       │
      └──► side REVERSED (13.03%) ────────────┤   bias NOT reassigned
                                              │
L3  get_m15_pullback(m15, bias["bias"]) ◄─────┘   ← ORIGINAL direction
L4  identify_liquidity_pools(side=side)           ← reversed
L5  get_sweep_and_structure(direction=side)       ← reversed
      └─► sweep_confirmed ──────────┐
L6  identify_poi(direction=side)    │             ← reversed
      threshold = 60 if sweep ◄─────┘
L7  bias_strength (ORIGINAL) · structure_confidence · poi_score · cohesion
L8  get_entry_trigger(direction=side)             ← reversed
```

## 8.1 The seven questions

| # | Question | Answer |
|---|---|---|
| **1** | Does L2 reverse direction? | **Yes — 1,738 of 13,343, 13.03 %** |
| **2** | Does L6 validate the reversed direction? | **No.** L6 inherits `side` and **cannot disagree**. It has no structure input |
| **3** | Can L6 be satisfied only because L2 reversed? | **Yes in principle** — a reversed decision is scored against POI zones for the opposite direction. **But L6 passes 1,023 of 1,024 real evaluations, so it discriminates almost nothing either way** |
| **4** | Does L6 duplicate L2 evidence? | **No.** `poi_engine` has **no fractal routine** (`grep` = 0), no structure call, and reads H1 only for `_calc_htf_confluence` |
| **5** | Can L2 and L6 independently change the final outcome? | **Formally yes; practically almost never. L2 blocked 7 (one event); L6 blocked 1** |
| **6** | Is any L2/L6 gate mathematically redundant? | **Yes, two.** L2's flip condition is **logically implied** by `BROKEN` (§3.1). L6's `"No POI found"` branch is **unreachable** (§7.1) |
| **7** | Does the quality score count L2/L6 evidence again? | **Yes.** L7 weights `structure_confidence` (0.05–0.30) and `poi_score` (0.20), **and counts both again** inside `cohesion_component` via `strong_components` |

---

# 9. Structure / Fractal Duplication

**Four independent copies of one algorithm.**

| # | Location | Layer | Window supplied | Returns |
|---|---|---|---|---|
| 1 | `bias_engine._find_h4_swings` | **L1** | `tail(50)` | `{swing_high, swing_low}` |
| 2 | `structure_engine.find_h1_swings` | **L2** | `tail(50)` | `{recent_*, second_recent_*}` |
| 3 | `pullback_detector._find_recent_fractal_swing` | **L3** | caller's frame, **no re-tail** | `(idx, value)` |
| 4 | `sweep_detector._find_recent_fractal_level` | **L5** | **re-tails to 25** | `value` |

All four use `for i in range(len(recent) - 3, 1, -1)` and the identical 5-bar
test.

> **MEASURED on identical 25-bar H1 windows: all four agree 1,621 / 1,621 =
> 100.00 %. No pairwise disagreement.**

**The algorithm is not the problem; the call sites are.** Phase 6O-C measured
L3 and L5 disagreeing **13.67 %** of the time *as called*, purely from window
differences. **L6 is the only main-path layer with no copy.**

**Is the same price event counted multiple times?** A single H1 swing high is
read by L1 (daily invalidation), L2 (`BROKEN` test **and** the flip test) and L3
(`break_reference`). **Within L2 the same level is tested twice by the same
predicate** — that is the identity in §3.1. Across layers the roles differ, so
it is sequencing rather than score inflation — **except in L7**, where structure
and POI are each counted twice (§8.1 q7).

---

# 10. Reachability — 15,735 decisions

| | L2 | L6 |
|---|---|---|
| Never reached | 2,392 (15.20 %) | 12,971 (82.43 %) |
| **Passed / bypassed** | **13,336 (84.75 %)** | **2,763 (17.56 %)** |
| **Blocked** | **7 (0.04 %)** | **1 (0.01 %)** |

**L6 breakdown of the 2,764 arrivals:**

| | Count |
|---|---|
| **Bypassed** (MICRO_SCALP, `bypass_l6`) | **1,740 (63.0 %)** |
| **Actually evaluated** | **1,024** |
| — passed | **1,023 (99.90 %)** |
| — blocked | **1** — *"POI score too low (68 < 70)"* |

| L6 arrivals by regime | Reached | Bypassed | Blocked |
|---|---|---|---|
| MICRO_SCALP | 1,740 | **1,740** | 0 |
| REGIME_SCALP | 765 | 0 | **1** |
| INTRADAY_SWING | 150 | 0 | 0 |
| DEAD_CALM | 109 | 0 | 0 |

**By side:** BUY 1,382 reached / 0 blocked; SELL 1,382 reached / 1 blocked.

**Branch reachability:**

| Branch | Status |
|---|---|
| L2 normal pass (HH/HL, LH/LL) | Reached — 1,074 of 1,335 sampled |
| L2 `UNKNOWN` pass | Reached — 87 of 1,335 (6.5 %) |
| L2 reversal attempted | **Every `BROKEN` — identity** |
| L2 reversal accepted | **All but 7 in 15,735** |
| L2 reversal rejected | **7 — one market event** |
| L2 `len(h1) < 5` → UNKNOWN | **0** — 60 bars always supplied |
| `find_h1_swings` `< 5` synthetic fallback (`× 0.995`) | **Unreachable** from `validate_h1_structure` |
| L6 bypass | 1,740 |
| L6 `best_poi is None` | **Unreachable** (§7.1) |
| L6 score-below-threshold | **1** |

---

# 11. Temporal Audit

**Verdict: no confirmed violation in either layer; the reversal decision is
causal.**

| Question | L2 | L6 |
|---|---|---|
| Future bars | **No** — frames cut at `T`; Phase 6M measured 0 violations / 15,735 / 6 TFs | **No** |
| Future swings / fractals | **No** — 5-bar fractal needs `i+1, i+2`, both inside the cut window | n/a |
| Future structure | **No** | **No** |
| Future higher-TF | **No** — H1 only | **No** — H1 for confluence only |
| Forming bar | **No under replay** — `iloc[-1]` is the newest **closed** bar | **No** |
| **Reversal causality** | **Causal.** Both `h1_close` and the swing levels come from the same already-cut frame; the revalidation call re-reads that same frame | — |
| Ambient clock | **No** — neither module reads a clock; both correctly absent from `PATCHED_MODULES` | **No** |

**Test coverage:** both layers **do** have a real future-mutation test —
`test_leakage.test_structure_is_unchanged` (calls `get_h1_structure`) and
`test_poi_is_unchanged` (calls `identify_poi`). **Both are BULLISH/BUY only.**

**`bos_flip` appears in 0 test files.** The reversal has **no temporal test and
no test of any kind**.

---

# 12. BUY/SELL Symmetry

| Element | BULLISH / BUY | BEARISH / SELL | Mirror? |
|---|---|---|---|
| BROKEN | `close < last_low` | `close > last_high` | **Yes** |
| Progression | `hh_count ≥ 1 ∧ hl_count ≥ 1` | `lh_count ≥ 1 ∧ ll_count ≥ 1` | **Yes** |
| Confidence | `(hh+hl)/8 × 10` | `(lh+ll)/8 × 10` | **Yes** |
| Flip condition | `close < last_swing_low` | `close > last_swing_high` | **Yes** |
| Revalidation | `∈ {HH/HL, LH/LL}` | same set | **Yes** |
| Fractal | `>` all four | `<` all four | **Yes** |
| `< 5` fallback | `recent_high × 0.995` | `recent_low × 1.005` | **Yes** (both unreachable) |
| L6 OB / FVG / Fib | direction-parameterised | mirror | **Yes** |
| L6 threshold | 60/70 | identical | **Yes** |

> **No code asymmetry in either layer.**

**Outcome:** L6 is symmetric — BUY 1,382 / SELL 1,382 arrivals, 0 / 1 blocks.
**L2's reversals are not: `SELL→BUY` 1,012 vs `BUY→SELL` 726 (58.2 / 41.8).**
Since the predicates mirror exactly, this reflects the input series — more upside
structure breaks than downside over a period in which gold rose 18.6 %.
**Consistent with a market cause; not established. UNRESOLVED.**

---

# 13. Quality-Score Double Counting

| Evidence | Gated at | Scored again at | Counted a third time? |
|---|---|---|---|
| **H1 structure** | **L2** (pass/fail) | **L7 `structure_component`**, weight 0.05–0.30 | **Yes — `cohesion_component`** via `structure_norm ≥ 70` |
| **POI score** | **L6** (≥ 60/70) | **L7 `poi_component`**, weight 0.20 | **Yes — `cohesion`** via `poi_norm ≥ 70` |
| **Bias** | L1 | L7 `bias_component` | **Yes — `cohesion`** |
| **Sweep** | L5 | L7 `sweep_component` | **Yes — `cohesion`** |

**All four L7 inputs are re-scored verdicts of earlier gates, and `cohesion`
counts all four a second time** (Phase 6O H1). **L7 contains no evidence that has
not already gated a decision.**

**A further coupling:** L5's `sweep_confirmed` sets L6's threshold (70→60), and
both then feed L7 independently.

---

# 14. Test Audit

| Test | Exercises it? | Assessment |
|---|---|---|
| `test_leakage.test_structure_is_unchanged` | **Yes** — real `get_h1_structure`, future mutation | **Genuine. BULLISH only** |
| `test_leakage.test_poi_is_unchanged` | **Yes** — real `identify_poi`, future mutation | **Genuine. BUY only** |
| `tests/test_layer_gate_logic.py` | **No** — `get_h1_structure` and `get_sweep_and_structure` are **mocked** | Wiring only. One of its two failures asserts `layer_failed == "L2_STRUCTURE"` **via a mocked BROKEN structure that the real flip would have rescued** |
| `tests/integration/test_real_strategy_replay.py` | Indirectly | No L2/L6 property asserted |

| ID | Gap |
|---|---|
| **L2-T1** | **`bos_flip` appears in 0 test files** — the mechanism that reverses 13.03 % of directions is wholly untested |
| **L2-T2** | **Nothing asserts the A ⟹ B identity** (§3.1). A future edit to either predicate would silently decouple them |
| **L2-T3** | No test of the revalidation branch — the only path that can reject a flip, and the source of all 7 L2 blocks |
| **L2-T4** | **No BEARISH/SELL test** |
| **L2-T5** | No boundary test at `close == last_low` (strict `<`, so equality passes) |
| **L2-T6** | No test for `hh_count`/`hl_count` at the `>= 1` boundary, nor that `_count_consecutive_moves` counts non-consecutive steps |
| **L2-T7** | **Nothing asserts `analysis["layer_1"]` and `analysis["direction"]` may disagree**, nor that L3/L7 read the original `bias` |
| **L6-T1** | No direct test of `identify_poi`, `score_poi`, `detect_order_block` or `poi_engine.detect_fvg` |
| **L6-T2** | **Nothing pins that the regime `poi_threshold` is ignored** |
| **L6-T3** | No test of the unconditional Fibonacci zone, nor that `best_poi is None` is unreachable |
| **L6-T4** | No SELL test; no boundary test at 60/70 |
| **L6-T5** | **No L2→L6 integration test** — nothing checks that a reversed side reaches L6 |
| **JOINT-T1** | **Nothing asserts the four fractal copies agree** |

---

# 15. Defects

| ID | Defect | Class | Occurrences | Baseline affected? |
|---|---|---|---|---|
| **L2-D1** | **Flip condition logically implied by `BROKEN`** — two names, one predicate | **IMPLEMENTATION DEFECT** | Every `BROKEN` | **Yes** |
| **L2-D2** | **`bias` not reassigned on flip — L3 and L7 use the original direction** | **IMPLEMENTATION DEFECT** (state inconsistency) | **1,738** | **Yes** |
| **L2-D3** | **`analysis["layer_1"]` never corrected** — record disagrees with the trade | **IMPLEMENTATION DEFECT** (observability) | 1,738 | Record only |
| **L2-D4** | **Reversal contradicts the documented "wait 3+ candles"** | **INTENT AMBIGUOUS** | 1,738 | **Yes** |
| **L2-D5** | **"H1 ATR expanding" documented, never implemented** | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L2-D6** | **"close > previous HL" confirmation documented, never implemented** | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L2-D7** | `_count_consecutive_moves` counts non-consecutive steps despite its name and docstring | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L2-D8** | FIX (STRUCTURE-1) loosened `>= 2` to `>= 1`, making `UNKNOWN` rare (6.5 %) | **INTENT AMBIGUOUS** | Every decision | Yes |
| **L2-D9** | **L2 blocks 7 of 15,735, all one event** — it is not functioning as a filter | **INTENT AMBIGUOUS** | 7 | Yes |
| **L2-D10** | `find_h1_swings` synthetic `× 0.995` fallback fabricates a structural level | **DEAD** | **0** | No |
| **L2-D11** | **Fourth copy of the 5-bar fractal** | **IMPLEMENTATION DEFECT** | Every decision | No |
| **L6-D1** | **Regime `poi_threshold` (50/60/70) ignored** by the gate | **DEAD** | Every decision | **Yes** |
| **L6-D2** | **Breaker Block documented, never constructed** | **DEAD** | Every decision | Yes |
| **L6-D3** | **Fibonacci zone appended unconditionally**, no validity test → `best_poi is None` unreachable | **IMPLEMENTATION DEFECT** | Every decision | **Yes** |
| **L6-D4** | Fib zone `fib ± 2` — **$2.00, unlabelled** | **IMPLEMENTATION DEFECT** (units) | Every decision | Yes |
| **L6-D5** | **L6 blocks 1 of 15,735; 63 % bypassed; 99.90 % of evaluations pass** | **INTENT AMBIGUOUS** | 1 | Yes |
| **L6-D6** | Documented `ENTRY THRESHOLD ≥ 70` is 60 when a sweep confirmed | **IMPLEMENTATION DEFECT** (doc) | Every decision | Yes |
| **JOINT-D1** | **L7 re-scores four gate verdicts and `cohesion` counts all four again** | **IMPLEMENTATION DEFECT** | Every L7 evaluation | Yes |
| **JOINT-D2** | `SELL→BUY` 1,012 vs `BUY→SELL` 726 from symmetric code | **UNRESOLVED** | — | — |

---

# 16. Ambiguities

| ID | Question |
|---|---|
| **A-6OF-1** | Should `BROKEN` mean "pause" (documented) or "reverse" (implemented)? |
| **A-6OF-2** | Should L3 and L7 see the reversed side? |
| **A-6OF-3** | Should `analysis["layer_1"]` be corrected, or is the original bias intentional history? |
| **A-6OF-4** | Is `>= 1` progression a structure test at all? |
| **A-6OF-5** | Should L6's threshold come from the regime, as documented? |
| **A-6OF-6** | Should the Fibonacci POI require any validity condition? |
| **A-6OF-7** | Should L7 re-score gates that have already passed? |

---

# 17. Design Decisions

| ID | Decision |
|---|---|
| **D-6OF-1** | **Should L2 be permitted to reverse L1's direction?** Carried from D-6OE-1, now with the identity proof: the flip is not a second test, it is the same test read twice |
| **D-6OF-2** | **If reversal stays, must `bias` be reassigned** so L3 and L7 agree with L4–L8? |
| **D-6OF-3** | Should L2 restore the documented "wait 3+ candles"? |
| **D-6OF-4** | Should L6 gate at all, given it blocks 1 in 15,735? |
| **D-6OF-5** | Should the regime's `poi_threshold` be honoured or removed? |
| **D-6OF-6** | Should the four fractal copies be unified? *(Extends D-6OC-4 and D-6OE-5.)* |
| **D-6OF-7** | Should L7 use only evidence not already gated? |

**None resolved here. None should be resolved by counting how many decisions the
alternative would admit.**

---

# 18. Items Safe to Freeze

**L2 and L6 temporal correctness** (§11) — no look-ahead; the reversal decision
is causal; both pinned by real future-mutation tests on production functions. ·
**Code symmetry** in both layers (§12). · **The 5-bar fractal geometry** — and
the measured fact that **all four copies are functionally identical** (1,621/1,621).
· **L6's structural independence from L2** — no structure input, no fractal, it
cannot silently reinforce the reversal. · **Determinism** — neither module reads
a clock or any randomness. · **The A ⟹ B identity itself as a true description of
current behaviour** — derived from source and confirmed by two independent
measurements agreeing at 13.03 %.

---

# 19. Items That Must Remain Unresolved

**D-6OF-1 … D-6OF-7** and **A-6OF-1 … A-6OF-7** — above all whether L2 may
reverse L1, which must not be settled by trade count, and which **§4.1
deliberately does not argue from the higher L8 arrival rate of reversed
decisions**. · **JOINT-D2**, the reversal-direction imbalance. · **The L3/L5
outcome asymmetry**, still open from 6O-C and 6O-E. · **Every threshold**:
`>= 1` progression, `0.995`/`1.005`, `± 2`, `60`/`70`, `0.618`, `20`-bar fib
window, `lookback=50`. · **D-6OE-1**, **D-6OD-1**, **D-6OC-1**, **D-6OB-1**,
**D-6N-1**, **U9-RR**, **U10-B** — all untouched.

---

# 20. Classification Summary

| Class | L2 | L6 | Joint | Total |
|---|---|---|---|---|
| **VERIFIED** | 4 | 3 | 2 | **9** |
| **IMPLEMENTATION DEFECT** | 7 | 3 | 1 | **11** |
| **INTENT AMBIGUOUS** | 3 | 1 | 0 | **4** |
| **DEAD / NON-PRODUCTION** | 1 | 2 | 0 | **3** |
| **TEST GAP** | 7 | 5 | 1 | **13** |
| **DESIGN DECISION** | 3 | 2 | 2 | **7** |
| **TEMPORAL RISK** | 0 | 0 | 0 | **0** |
| **UNRESOLVED** | 1 | 0 | 0 | **1** |

**Total components classified: 48.**

**With this phase the entire main path — L1 through L8 — has been audited to
depth.**

---

# 21. Exact Next Audit Target

> **No further layer audit. The next action is to pin current behaviour in
> tests, before any decision changes it.**

Every main-path layer is now audited. Across L1–L8 the audits have produced a
consistent picture and a specific, ordered set of blockers. **The single most
dangerous property of the current state is that almost none of the measured
behaviour is pinned**: the four fractal copies, the A ⟹ B identity, the 13.03 %
reversal, the dead `poi_threshold`, the unreachable branches and the
regime/session composition are all facts established only in documents.

**Recommended next phase — `PHASE 6P: BEHAVIOUR PINNING`, tests only, no
production change:**

1. **T1/T2** from Phase 6O — ATR band boundaries and `(ATR, session) → regime`;
   regime/session under future mutation.
2. **L2-T1/T2** — the BOS flip exists, and `BROKEN ⟹ flip condition`.
3. **JOINT-T1** — the four fractal copies agree on identical windows.
4. **L6-T2** — the regime `poi_threshold` is ignored.
5. **L5-T7**, **L4-T9**, **L1-T6** — the unreachable branches stay unreachable.
6. **SELL-side counterparts** for every BUY-only leakage test (L2, L3, L4, L6).

Only then: decide **D-6N-1**, then **U9-RR**.

**Do not implement any L2 or L6 change, do not refactor the four fractal copies,
do not alter a threshold, and do not resolve D-6OF-1 or U9-RR.**

---

# 22. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| Refactoring | **None** |
| Parameters / thresholds | **Untouched** |
| Regime / session architecture | **Untouched** |
| U9-RR | **Not resolved** |
| Baselines and R1 fixtures | **Read only** |
| "More surviving reversals" treated as better | **No** — §4.1 reports the distribution and explicitly declines to interpret it |
| Cause inferred for outcome imbalance | **No** — §12 states the limit |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
