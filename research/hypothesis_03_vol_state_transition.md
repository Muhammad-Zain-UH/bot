# Hypothesis 03 — VOLATILITY-STATE TRANSITION

**This file is committed BEFORE any label or result is computed.** This commit
contains the specification and nothing else — no analysis script, no panel, no
results, no report.

Governing standards, both binding: `research/RESEARCH_TO_STRATEGY_GATE.md` and
`research/STATISTICAL_RESEARCH_CONTROLS.md`. This is a G0→G2 pre-registration.

**This is a different hypothesis family from H01/H02.** It is not another breakout
threshold, failed-breakout variant, range-re-entry variant, compression percentile
or session-hour filter. The event here is a change in volatility *state*, defined
without reference to any range boundary or breakout.

| Prior hypothesis | Status |
|---|---|
| H01 — compression → breakout → expansion | **NOT SUPPORTED** (`45223cd`) |
| H02 — failed breakout → re-entry → reversal | **INCONCLUSIVE / UNDERPOWERED** (`5230336`) |

---

## 1. The question

> When XAUUSD transitions from one volatility state to another, does the
> transition contain **incremental directional information** about subsequent
> returns, beyond ordinary market drift and volatility?

The primary test is **not** "does volatility expansion predict returns?" It is:
*conditional on a volatility-state transition, is subsequent directional return
different from an appropriate matched baseline?*

**Mechanism claimed.** A volatility-state transition is a change in the market's
information-arrival rate, not a change in price level. When short-horizon realised
volatility rises sharply relative to its daily norm, it is usually because new
information is being absorbed; market makers widen, inventory is repriced, and the
participants who must trade (hedgers, liquidators, index flows) transact against a
thinner book. If that repricing is systematically incomplete at the moment the
state change becomes observable, the residual adjustment would appear as
directional drift over the following hours. Symmetrically, a transition back to
low volatility marks the end of an absorption episode, after which any
overshoot would be expected to partially revert.

**The competing explanation, which this design exists to separate:** *volatility
increased because price was already moving.* A short/long volatility ratio rises
mechanically when recent bars are large, and recent bars are large when price has
been trending. Any apparent directional information could therefore be nothing but
the continuation or reversal of the displacement that caused the volatility change
in the first place. §6 control 3 is built specifically to remove this, and §12
makes its failure a rejection criterion.

**No directional prior is asserted.** Expansion is not assumed bullish or bearish.
All primary tests are **two-sided** (§8).

### Architectural independence — binding

Not used, not imported, not consulted as predictors: `fast_bias`,
`bias_strength`, H1 production bias, CHoCH, production sweep, POI, FVG, production
session gate, production entry trigger, any production threshold, and **any H01 or
H02 construct** (compression ratio, range boundaries, breakout buffer, re-entry).
Production is not modified. The previous architecture remains a frozen historical
control.

---

## 2. Prior evidence on this construct — disclosed, and discounted

**This must be stated before any result, because it would otherwise look like
supporting evidence.**

Phase 1's clean rerun tested a feature named `vol_transition`, defined at
`research/phase1_feature_panel.py:139` as

```
mean(ATR_14 over 5 bars) / mean(ATR_14 over 20 bars)
```

— **structurally the same short/long volatility-ratio family** proposed below,
tested as a quintile contrast against the same raw signed ATR-normalised forward
return. It produced the **largest |t| of all 84 cells** in that scan:

| Cell | Q5−Q1 diff | t | note |
|---|---|---|---|
| `vol_transition@1h` | −0.1185 | **−3.182** | largest \|t\| in the scan |
| `vol_transition@2h` | −0.2179 | −3.14 | |
| `vol_transition@4h` | −0.3235 | −2.56 | carried `ESTIMATOR_SIGN_DISAGREEMENT` |

It did **not** survive the corrected threshold of 3.434, and
`PHASE1_CLEAN_REPORT.md` recorded the scan as NO ROBUST CONDITIONAL STRUCTURE
DETECTED.

**That near-miss is not evidence for H03, and H03 is not a follow-up on a
promising lead.** Under a pure null with 84 independent tests, the expected
maximum |t| is **2.69**, and `P(max |t| ≥ 3.18) = 0.116` — about **one run in
nine** (200,000 simulations, seed 1). A maximum of 3.18 from an 84-cell scan is
what a null scan routinely produces. Treating it as a lead would be precisely the
error the Research-to-Strategy Gate §2 forbids: a statistic found first and a
mechanism attached afterwards.

**H03 is justified by the mechanism in §1, not by that statistic.** The disclosure
exists so the prior result cannot later be cited as corroboration, and so the
multiple-testing burden can be carried honestly:

> **Accumulated-burden rule, frozen here.** Per gate §6.6, repeated attempts on a
> construct accumulate. H03 declares **6** primary tests (§8). Correction is
> reported **twice**: over the declared 6, and over the **accumulated 9** —
> the 6 declared plus the 3 Phase 1 `vol_transition` cells already spent on this
> construct family. **Promotion requires surviving the accumulated-9 threshold.**
> The declared-6 figure is reported for completeness, not as the promotion test.

**Interpretive note, declared in advance.** Phase 1's quintile contrast was
**negative** at all three horizons, i.e. higher short/long volatility associated
with *lower* subsequent signed return. If H03's expansion effect is negative, that
is sign-consistent with the prior cell; if positive, it contradicts it. Neither
outcome is treated as support on its own, and the sign prior does **not** make the
primary tests one-sided.

---

## 3. Data boundaries

Primary structural timeframe **M15**, loaded only through
`research/dataset_access.py`.

| Arm | Window | M15 rows | Role |
|---|---|---|---|
| **TRAIN** | 2022-06-30 07:00 → 2024-08-09 18:15 | 50,010 | derive thresholds; test |
| **DEV** | 2024-08-11 → 2025-09-02 14:15 | 24,989 | replication of the identical definition only |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | 24,989 | **LOCKED** |

**FINAL_OOS remains LOCKED.** No M15, H1, M5, M1 or tick data from the FINAL_OOS
period is read, as data or as context. The M15 series is truncated at the DEV
upper boundary **before** any indicator is computed, and the truncation is
asserted in code. Dataset fingerprints
(`dataset_sha256 = 9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca`)
are verified at load.

**H1** is used for regime conditioning (§11) only, and only from H1 bars that
**closed** at or before the event bar's close. **No tuning occurs on DEV**: no
threshold, window, horizon or definition is refit there. M5/M1 are not used —
there is no execution or path claim in this hypothesis that requires them, and M1
has zero bars in both arms in any case.

**Purge/embargo: 16 M15 bars.** An event is admitted for horizon `h` only if bar
`i+h` lies inside the **same arm**, so no forward window spans two arms or the
embargo gap. Counts therefore differ slightly across horizons and are reported per
horizon.

---

## 4. The causal ATR

```
A[i] = ATR_14[i-1]        Wilder ATR(14) on M15, evaluated at bar i-1
```

The same convention as H01 and H02, reused deliberately so that effect sizes are
comparable across the three hypotheses in ATR units. `A[i]` is a function of bars
at or before `i-1`.

An event is **excluded** if `A[i]` is NaN or `<= 0`; exclusions are counted.

---

## 5. Mechanism definition — ONE primary specification

### 5.1 The state variable

True range, the standard definition, at each completed bar `k`:

```
TR[k] = max( high[k] - low[k],  |high[k] - close[k-1]|,  |low[k] - close[k-1]| )
```

```
short_vol[i] = mean( TR[k] for k in i-4  .. i-1 )          N_short =  4  (1 hour)
long_vol[i]  = mean( TR[k] for k in i-96 .. i-1 )          N_long  = 96  (24 hours)

VOL_RATIO[i] = short_vol[i] / long_vol[i]
```

**Both windows end at `i-1` and exclude bar `i` entirely.**

**Why these two windows, chosen for reasons that are not about results.**
`N_short = 4` is one hour — the shortest window that averages more than a couple
of bars, and exactly the shortest forecast horizon tested. `N_long = 96` is one
full 24-hour trading day, the natural volatility reference for an intraday
instrument, and the window this codebase already uses for its own daily baseline
(`average_volume_96`, `indicators.py:127`). **No window pair is searched. No
alternative pair is computed.**

### 5.2 Thresholds — TRAIN only, frozen

```
THETA_HI = 80th percentile of VOL_RATIO over TRAIN bars where it is finite
THETA_LO = 20th percentile of VOL_RATIO over TRAIN bars where it is finite
```

via `numpy.percentile(..., method="linear")`. The 80/20 pair mirrors the 20th
percentile already frozen in H01/H02, applied symmetrically to both tails, so it
is not a fresh arbitrary choice.

Both values are recorded to full precision in `hypothesis_03_results.json`.
**They are not recalculated on DEV, not optimised, and no alternative percentile
pair is tested.** No grid is searched and no threshold is selected for strength.

`VOL_RATIO` is a feature-only quantity, so deriving thresholds from TRAIN uses no
label information, and they are fixed before any label is computed.

### 5.3 States and transitions

```
state[i] = HIGH  if VOL_RATIO[i] >= THETA_HI
           LOW   if VOL_RATIO[i] <= THETA_LO
           MID   otherwise
```

An event is **the first causal crossing into a state after having been in the
opposite state**, so repeated bars within one episode are never counted as
separate events:

```
EXPANSION   event at i:  state[i] == HIGH  and the most recent non-MID state
                         before i was LOW
CONTRACTION event at i:  state[i] == LOW   and the most recent non-MID state
                         before i was HIGH
```

Implemented as a deterministic single-pass machine, run independently within each
arm in ascending time order:

```
last_extreme = None                       at the first eligible bar of the arm

for each eligible bar i in ascending order:
    s = state[i]
    if s == HIGH:
        if last_extreme == LOW:  emit EXPANSION event at i
        last_extreme = HIGH
    elif s == LOW:
        if last_extreme == HIGH: emit CONTRACTION event at i
        last_extreme = LOW
    # MID leaves last_extreme unchanged
```

This requires a **genuine traversal** of the MID band, not threshold flickering,
and makes expansion and contraction events alternate strictly. `last_extreme`
resets to `None` at the start of each arm and **does not carry across the
TRAIN/DEV boundary**.

Reported: expansion events, contraction events, bars in each state, bars
suppressed because `last_extreme` already matched the state, and exclusions.

### 5.4 No endpoint coupling — a structural improvement over H01/H02

`VOL_RATIO[i]` is built from `TR[i-96 … i-1]`, whose most recent inputs are
`high[i-1]`, `low[i-1]` and `close[i-2]`. `A[i]` uses bars up to `i-1`. **`close[i]`
appears nowhere in the event definition.**

The label (§7) is `(close[i+h] − close[i]) / A[i]`. **Feature and label therefore
share no price point at all**, so the endpoint-coupling failure mode that had to be
declared and controlled in both H01 and H02 **does not arise here**. No coupling
control label is needed, and none is introduced.

---

## 6. Controls — the heart of this design

Every control is defined here, before results. The purpose is to separate three
things that a naive test conflates:

```
A) volatility expansion itself
B) directional displacement / drift
C) genuine directional information   <- only this would be a finding
```

**Control 1 — Unconditional directional baseline.** Mean of `S_h` over all
eligible bars in the arm. This is the period's drift, and the quantity every
event mean must be compared against.

**Control 2 — Same-volatility-state bars without a transition.** For expansion:
bars with `state == HIGH` that are **not** expansion event bars. For contraction:
bars with `state == LOW` that are not contraction event bars. This separates *being
in* a volatility state from *transitioning into* it — i.e. isolates the
transition, which is what the hypothesis is about.

**Control 3 — Matched recent-displacement bucket.** The control that addresses
"volatility increased because price was already moving." Causal displacement,
sharing no price point with the label:

```
disp_12[i] = ( close[i-1] - close[i-13] ) / A[i]
```

All eligible bars are stratified into **quintiles of `disp_12` using TRAIN-only
cut points, frozen**. Within each stratum the mean `S_h` is computed for
transition events and for non-transition bars, and the control statistic is the
**event-count-weighted** average of the within-stratum differences, with its
standard error from the within-stratum variances.

> Weighting is declared explicitly because this is exactly where the Phase 1
> estimator failure occurred. The aggregation is **observation-weighted by event
> count per stratum**, never an equal-weighted mean of per-stratum means. Strata
> are defined by a frozen TRAIN feature quantile, so their composition is **not**
> endogenous to the outcome.

**Control 4 — Opposite transition.** Expansion events contrasted against
contraction events. If a transition carries directional information, the two
directions of transition should not behave identically.

**Control 5 — H1 directional regime.** §11.

**Causal separation.** Every feature, threshold, state and stratum boundary is a
function of bars at or before `i-1`. No feature contains the forward label, and no
label value is visible to any feature. Verified by prefix reconstruction (§13).

---

## 7. Labels

### 7.1 Primary — raw signed return

```
S_h = ( close[i+h] - close[i] ) / A[i]           h = 4, 8, 16 M15 bars (1h, 2h, 4h)
```

**Raw and signed, not direction-normalised**, because a volatility-state
transition has **no intrinsic direction**. This is the quantity the primary
hypothesis is about, and it is tested **two-sided** against the controls of §6.

### 7.2 On "directional-normalised" returns, and why long/short are not two findings

For a direction-less event, the long-direction outcome is `+S_h` and the
short-direction outcome is `−S_h`. **These are exact negatives of each other**, so
reporting both is a presentational symmetry, not two independent measurements, and
no inference may be drawn from their difference. Both are reported, with this
statement attached, so the symmetry cannot be mistaken for evidence.

The substantive content of a symmetric directional test is therefore: **is
`E[S_h]` distinguishable from its matched baseline at all?** If not, any
large MFE/MAE is volatility expansion without directional information — which §12
makes an explicit rejection criterion.

### 7.3 Secondary, EXPLORATORY — displacement-continuation direction

One single pre-declared direction convention, to answer the directional form of
the competing explanation: does a volatility transition continue the move that
preceded it?

```
D_h = sign(disp_12[i]) * S_h
```

**6 exploratory cells** (2 transition types × 3 horizons), corrected separately,
**labelled exploratory throughout, and incapable of promoting H03 to SUPPORTED
under any result.** `sign(disp_12)` is causal and shares no price point with the
label. No other direction convention is tested.

### 7.4 Path diagnostics — descriptive only

```
MFE_h = ( max(high[i+1 : i+h+1]) - close[i] ) / A[i]        >= 0
MAE_h = ( min(low [i+1 : i+h+1]) - close[i] ) / A[i]        <= 0
```

Reported to distinguish *volatility-only* expansion from *directional*
information. **No stop or target is derived or selected from them.** 0 hypotheses.

---

## 8. Primary statistical inference and frozen hypothesis count

**Pre-declared primary hypothesis count: 6.**

| # | Transition | Horizon | Test |
|---|---|---|---|
| 1–3 | **EXPANSION** | 1h, 2h, 4h | `E[S_h]` vs matched baseline, **two-sided** |
| 4–6 | **CONTRACTION** | 1h, 2h, 4h | `E[S_h]` vs matched baseline, **two-sided** |

Headline inference uses **NON-OVERLAPPING events**, selected by the deterministic
greedy rule in `research/phase1_statistical_controls.py`. Overlapping forward
windows are **never** the headline estimator.

Reported for every cell: **raw event count · non-overlapping count · overlap ratio
· mean · median · standard deviation · 95% CI · headline t**, weighting named
explicitly, raw (overlapping) statistics alongside, block statistics as secondary
diagnostics only. **No unweighted block mean is used as headline evidence.**

### Estimators, and the Phase 1 distinction

Three estimates are reported for every cell, and the distinction between the last
two is stated because the user's warning depends on it:

1. **Analytic, non-overlapping** — the headline.
2. **Moving-block bootstrap** — blocks of **96** and **480** M15 bars, 4,000
   replicates, seed 20261004, declared here and not selected on their result. Each
   replicate computes an **observation-weighted** mean over resampled contiguous
   blocks. This is **not** the estimator that failed in Phase 1.
3. **Equal-block mean** — the estimator that *did* fail in Phase 1: an unweighted
   mean of per-block means, whose per-block observation counts are endogenous.
   Carried **only** as the input to the sign-disagreement check, never as evidence.

**If the raw and block estimators materially disagree in sign, the cell is flagged
`ESTIMATOR_SIGN_DISAGREEMENT` and the hypothesis is flagged — the favourable
estimator is not chosen.** Per §12 this is a rejection criterion, not a caveat.

### Multiple testing

- **Bonferroni** and **Benjamini–Hochberg** at nominal alpha 0.05, computed from
  the **declared** count; a cell with no computable statistic is padded as a
  non-rejection, never dropped.
- Reported over the **declared 6** and over the **accumulated 9** (§2).
  **Promotion requires surviving the accumulated-9 threshold.**
- Exploratory cells (§7.3) are corrected separately and cannot promote.

Primary arm is **TRAIN**; DEV is replication (§10); pooled is descriptive only.

**No test is added after results are observed.** No alternative window pair,
percentile pair, horizon or transition definition.

---

## 9. Power

Computed from the actual non-overlapping event counts and reported **before** any
null is interpreted:

- non-overlapping n; expected null SE;
- **MDE at 2 SE**; **MDE at the corrected detection threshold** (accumulated 9);
- both compared with the **round-turn spread cost = 1 × spread**, measured median
  **$0.33**, which is **0.158 ATR** in TRAIN and **0.093 ATR** in DEV.

**An effect is not called economically interesting unless it is large enough to
survive realistic execution cost.** A null is always stated as "no effect larger
than X ATR", never as "no effect". If the data cannot resolve a cost-sized effect,
the classification is **INCONCLUSIVE** (§12).

A cell with fewer than **100 non-overlapping events** is INCONCLUSIVE by the
standing rule.

> Flagged in advance: event counts are expected to be modest, because an event
> requires a full traversal of the MID band. H02 was underpowered at 574 and 283
> events, and **power is the most likely outcome-determining constraint here
> too.** This is stated now so a null is not later presented as a refutation it
> cannot support.

---

## 10. TRAIN → DEV replication

**TRAIN** derives `THETA_HI`, `THETA_LO` and the `disp_12` quintile cut points,
and carries the primary tests. **DEV** applies the **identical frozen
definitions**. No threshold, window, horizon or stratum boundary is refit on DEV.

Reported separately: **TRAIN**, **DEV**, **TRAIN+DEV descriptive only**. For DEV:
same-sign replication, magnitude stability, confidence interval, whether the
effect survives cost, and whether it survives H1 regime conditioning.

**If TRAIN is null or underpowered, no DEV rescue is attempted.** A DEV-only
result is not a finding, and will be reported as the chance outcome it is.

---

## 11. H1 regime robustness

H1 divides the market into broad directional regimes. **The purpose is not to
create another predictor** — it is to answer: *is the H03 relationship dependent
on one directional regime?*

From the last H1 bar to have **closed** at or before the close of event bar `i`:

```
z = ( h1_close - h1_sma50 ) / h1_atr14
```

Cutoffs are the **TRAIN terciles of z**, frozen: `BEARISH` below the lower
tercile, `BULLISH` above the upper, `NEUTRAL` between.

H1 **does not assign event direction** and is **not** used to select or weight
events. **If the effect exists only in one regime, that is reported explicitly**
and, per §12, counts against the hypothesis rather than for it. No optimisation
around the regime occurs. **No FINAL_OOS H1 data is read.**

---

## 12. Classification criteria — frozen

### H03 is REJECTED (NOT SUPPORTED) if

- no corrected statistical evidence exists **and** observed effects are small
  relative to cost and power bounds; **or**
- the apparent effect disappears after the displacement/drift controls (§6
  control 3); **or**
- TRAIN/DEV signs are unstable; **or**
- estimator signs materially disagree; **or**
- the effect is purely volatility/MFE/MAE expansion with no directional
  information.

### H03 is INCONCLUSIVE if

the data cannot resolve a cost-sized effect — i.e. the corrected MDE exceeds the
round-turn cost — or a cell has fewer than 100 non-overlapping events.

### H03 is SUPPORTED only if ALL SEVEN hold

1. statistically credible TRAIN evidence (surviving the **accumulated-9**
   corrected threshold);
2. causal feature/label separation demonstrated (§13);
3. estimator agreement (no material sign disagreement on a headline cell);
4. the effect survives the drift/displacement controls;
5. the effect survives realistic cost;
6. the identical definition replicates in DEV;
7. no obvious single-regime dependency.

**The word "edge" will not be used unless all seven are met.** A positive point
estimate that fails correction is INCONCLUSIVE, never SUPPORTED.

---

## 13. Causal reconstruction standard — tolerances frozen BEFORE results

Following the H02 redesign. **Derived from float64 precision alone; none is chosen
from an observed difference, and none may be revised after results.**

| Quantity | Frozen tolerance | Justification — numerical, not empirical |
|---|---|---|
| `TR`, `short_vol`, `long_vol` | **relative 1e-13** | finite sums of at most 96 float64 terms; error bound ≈ `96·eps ≈ 2.1e-14`. 1e-13 is ~5× that bound. |
| `VOL_RATIO` | **relative 1e-13** | ratio of two such sums; inherits their relative error. |
| `disp_12` | **relative 1e-12** | a difference of two exact prices divided by `ATR` (below). |
| `ATR_14` | **relative 1e-12** | Wilder's recursion is **contracting** by 13/14 per step, so float64 error reaches a steady state of order `14·eps ≈ 3.1e-15`, not `n·eps`. 1e-12 is ~320× that bound and ~4 orders below any economically meaningful ATR difference. |
| `state`, `EXPANSION`, `CONTRACTION` classification | **0 disagreements** | boolean |

**Boolean standard.** Classifications must agree **exactly**. Any disagreement is
a **FAIL**, unless it is demonstrated that the comparison margin at that bar was
below the frozen numerical tolerance — a genuine threshold tie — in which case
each margin is reported and the cell excluded. A disagreement with margin above
tolerance **fails the whole analysis**.

**Method.** For a frozen sample of **60** events (seed **20261004**), every
quantity is recomputed from `m15.iloc[:i]` — bars `0 … i-1` only — and compared
with the panel value at `i`.

**Inherited constants are referenced by artifact, not by printed digits** — the
lesson recorded in `HYPOTHESIS_02_REPORT.md` §13 note 1.

---

## 14. No feature mining — binding

Nothing outside the definitions above is searched, computed as a candidate, or
reported as a finding. **Not** searched: RSI, MACD, EMA combinations, Bollinger
Bands, alternative ATR formulas, alternative volatility-window pairs, alternative
percentile thresholds, additional ratio variants, candlestick patterns, session
filters, additional indicators, or any H01/H02 construct.

**One** state variable, **one** window pair, **one** threshold pair, **one**
transition machine, **three** horizons, **two** transition types.

**If H03 fails, the failure is recorded.** It is not mutated until it passes. Any
change to §5–§7 is a new hypothesis requiring a new pre-registration, and it
inherits the accumulated multiple-testing burden of every version attempted —
which, per §2, already stands at 9 for this construct family.

---

## 15. Outputs

`research/hypothesis_03_vol_state_transition.py` ·
`research/HYPOTHESIS_03_REPORT.md` · `research/hypothesis_03_results.json` ·
`research/hypothesis_03_controls.json`

The report carries, in this order: the frozen specification reference; exact
mathematical definitions; threshold derivation; event counts; raw and
non-overlapping counts; overlap ratios; 1h/2h/4h results; unconditional baseline
comparison; volatility-state control; displacement/drift control; H1 regime
conditioning; analytic and bootstrap estimates; multiple-testing results;
power/MDE; cost screen; TRAIN→DEV replication; failure-mode diagnostics; and the
final classification — **SUPPORTED · INCONCLUSIVE · NOT SUPPORTED**.

## 16. Verification before the results commit

1. this specification committed **before** results, containing the specification
   only; 2. FINAL_OOS token unchanged; 3. FINAL_OOS inaccessible; 4. dataset
fingerprints unchanged; 5. split manifest unchanged; 6. `baseline_008` unchanged;
7. production unchanged; 8. statistical controls pass; 9. exactly one hypothesis
family tested, with no alternative parameters; 10. causal reconstruction
tolerances frozen before results; 11. no DEV tuning; 12. working tree contains
only intended research changes.

**H04 is not begun.** No strategy is designed. Strategy design requires separate
authorisation.
