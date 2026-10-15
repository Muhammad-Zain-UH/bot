# Hypothesis 03 — VOLATILITY-STATE TRANSITION

## HYPOTHESIS 03 — NOT SUPPORTED

**0 survivors of 6 declared hypotheses**, and 0 of the accumulated 9, under both
Bonferroni and Benjamini–Hochberg. Maximum |t| in the primary arm was **2.166**
against a promotion threshold of **2.773**.

**Four of the five pre-registered rejection criteria are met.** Any one is
sufficient under §12 of the specification:

| Rejection criterion (§12) | Met? | Evidence |
|---|---|---|
| no corrected evidence **and** effects small vs cost/power | **YES** | 0 survivors; the only power-sufficient cell is **below cost** (+0.0996 vs 0.158 ATR) |
| effect disappears after displacement/drift controls | **YES** | matched-displacement control: TRAIN max \|t\| **1.36**; **4 of 6 cells flip sign** between arms |
| TRAIN/DEV signs unstable | **YES** | after the displacement control, 4 of 6 transition×horizon cells reverse |
| estimator signs materially disagree | no | **0** cells flagged `ESTIMATOR_SIGN_DISAGREEMENT` |
| purely volatility/MFE/MAE expansion, no directional information | **YES** | \|MFE\|−\|MAE\| is **+0.02 to +0.26 ATR** against MFE magnitudes of **0.75–2.69** — 1–10% asymmetry |

**None of the seven SUPPORTED conditions is satisfied** — conditions 1, 4, 5, 6
and 7 all fail. The word "edge" is therefore not used anywhere in this report.

### Why this is NOT SUPPORTED rather than INCONCLUSIVE

Eleven of twelve cells are underpowered against cost, which in H02 produced an
INCONCLUSIVE. The difference here is decisive: **one cell was power-sufficient,
was tested, and failed cleanly.** `TRAIN|CONTRACTION@1h` had a corrected MDE of
**0.128 ATR against a 0.158 cost** — the data could resolve a cost-sized effect
there — and it returned a gross mean of **+0.0996 ATR, below cost**, failing the
corrected threshold (t 2.17 < 2.773), failing the displacement control (t 1.36),
and reversing sign in DEV under that control (−0.0154).

Where the data could decide, it decided against. Elsewhere the controls removed
the effect independently of power.

**FINAL_OOS was not opened.** No tuning occurred on DEV. Production and
`baseline_008` untouched.

---

## A. The frozen specification

`research/hypothesis_03_vol_state_transition.md`, committed at **`140df22`** —
specification only, no script, no results, verified by git inspection.

**6 primary tests** pre-declared (2 transition types × 3 horizons), two-sided.
One state variable, one window pair, one threshold pair, one transition machine,
one displacement window. **No alternative was computed.**

### Prior evidence, disclosed before results and discounted

Phase 1's `vol_transition` (`mean(ATR,5)/mean(ATR,20)`) is structurally the same
short/long volatility-ratio family, tested against the same raw signed label, and
produced the **largest |t| of all 84 cells**: −3.182 at 1h, against a 3.434
threshold.

That is not a lead. Under a pure null with 84 tests the expected max |t| is
**2.69** and `P(max |t| ≥ 3.18) = 0.116` — about **one run in nine** (200,000
simulations, seed 1). H03 was justified by its mechanism, not that statistic.

**Accumulated-burden rule, applied as frozen:** correction is reported over the
declared 6 **and** over the accumulated 9 (the 6 declared plus Phase 1's 3
`vol_transition` cells). Promotion required the accumulated-9 threshold.
**Neither threshold is passed.**

Phase 1's prior sign was *negative*. H03's TRAIN expansion cells are
+0.048, +0.043, −0.036 — not sign-consistent with it either, which is one more
reason to read the Phase 1 cell as the null maximum it almost certainly was.

---

## B. Exact mathematical definitions

```
TR[k]        = max( high[k]-low[k], |high[k]-close[k-1]|, |low[k]-close[k-1]| )

short_vol[i] = mean( TR[k] : k = i-4  .. i-1 )            N_short =  4  (1 hour)
long_vol[i]  = mean( TR[k] : k = i-96 .. i-1 )            N_long  = 96  (24 hours)
VOL_RATIO[i] = short_vol[i] / long_vol[i]

A[i]         = ATR_14[i-1]                                 Wilder, M15
disp_12[i]   = ( close[i-1] - close[i-13] ) / A[i]

state[i]     = HIGH if VOL_RATIO[i] >= THETA_HI
               LOW  if VOL_RATIO[i] <= THETA_LO
               MID  otherwise

EXPANSION   at i: state[i]==HIGH and the most recent non-MID state was LOW
CONTRACTION at i: state[i]==LOW  and the most recent non-MID state was HIGH

S_h = ( close[i+h] - close[i] ) / A[i]       h = 4, 8, 16 M15 bars
```

### No endpoint coupling — a structural improvement over H01 and H02

`VOL_RATIO[i]` draws on `TR[i-96 … i-1]`, whose most recent inputs are
`high[i-1]`, `low[i-1]`, `close[i-2]`. `A[i]` and `disp_12[i]` likewise end at
`i-1`. **`close[i]` appears in no feature.** The label subtracts `close[i]`, so
**feature and label share no price point at all** — the coupling that had to be
declared and controlled in both earlier hypotheses does not arise. No coupling
control was needed and none was introduced.

---

## C. Threshold derivation — TRAIN only, frozen

| | |
|---|---|
| `THETA_HI` (80th pct of `VOL_RATIO`, TRAIN) | **1.275554750274175** |
| `THETA_LO` (20th pct of `VOL_RATIO`, TRAIN) | **0.6114646781361861** |
| `disp_12` quintile cuts (TRAIN) | −1.6387, −0.4421, +0.5495, +1.7896 |
| H1 `z` tercile cuts (TRAIN) | −1.0270, +1.4944 |

**Sanity check:** applied to TRAIN these select exactly **20.00%** HIGH and
**20.00%** LOW bars, as they must. Applied unchanged to DEV they select **20.20%**
HIGH and **15.85%** LOW — the asymmetry that follows from freezing a TRAIN
quantity and applying it to a higher-volatility era (median ATR $2.33 vs $4.05).
Reported, not corrected. **Nothing was refit on DEV.**

---

## D–F. Event counts, raw and non-overlapping counts, overlap ratios

| | TRAIN | DEV |
|---|---|---|
| eligible M15 bars | 50,010 | 24,989 |
| bars HIGH / MID / LOW | 9,983 / 29,947 / 9,983 | 5,048 / 15,981 / 3,960 |
| **EXPANSION events** | **697** | **395** |
| **CONTRACTION events** | **697** | **394** |
| repeat-HIGH bars suppressed | 9,285 | 4,653 |
| repeat-LOW bars suppressed | 9,286 | 3,565 |
| excluded, non-finite features | 97 (whole panel) | |

Expansion and contraction counts are equal in TRAIN and differ by one in DEV,
exactly as the alternating machine requires. The machine did substantial work:
**~9,285 of 9,983 HIGH bars were suppressed** as continuations of a state already
entered, so 93% of HIGH bars are not events.

| | 1h | 2h | 4h |
|---|---|---|---|
| TRAIN EXPANSION raw / non-ov | 697 / **697** | 697 / **696** | 697 / **687** |
| TRAIN CONTRACTION raw / non-ov | 697 / **697** | 697 / **695** | 697 / **689** |
| DEV EXPANSION raw / non-ov | 395 / **395** | 395 / **394** | 395 / **388** |
| DEV CONTRACTION raw / non-ov | 394 / **394** | 394 / **394** | 394 / **387** |
| **overlap ratio, every cell** | **1.0×** | **1.0×** | **1.0×** |

**Overlap is 1.0× throughout** — the MID-traversal requirement spaces events
naturally, so the headline estimator discards essentially nothing. All twelve
cells exceed the 100-event minimum. These nulls are not artefacts of discarded
observations.

---

## G. Primary results — 1h / 2h / 4h

`E[S_h]` two-sided on the raw signed return, non-overlapping events.

| Cell | raw n | non-ov | mean (ATR) | median | sd | se | **t** | 95% CI |
|---|---|---|---|---|---|---|---|---|
| TRAIN EXPANSION@1h | 697 | 697 | +0.0477 | +0.0221 | 1.974 | 0.0748 | +0.64 | [−0.0988, +0.1942] |
| TRAIN EXPANSION@2h | 697 | 696 | +0.0433 | −0.0084 | 2.819 | 0.1068 | +0.41 | [−0.1661, +0.2527] |
| TRAIN EXPANSION@4h | 697 | 687 | −0.0359 | −0.0746 | 3.433 | 0.1310 | −0.27 | [−0.2926, +0.2209] |
| **TRAIN CONTRACTION@1h** | 697 | 697 | **+0.0996** | +0.0565 | 1.214 | 0.0460 | **+2.17** | [+0.0095, +0.1897] |
| TRAIN CONTRACTION@2h | 697 | 695 | +0.0754 | +0.0506 | 1.543 | 0.0585 | +1.29 | [−0.0392, +0.1901] |
| TRAIN CONTRACTION@4h | 697 | 689 | +0.1225 | +0.1806 | 2.521 | 0.0961 | +1.28 | [−0.0657, +0.3108] |
| DEV EXPANSION@1h | 395 | 395 | +0.1421 | +0.0785 | 1.951 | 0.0982 | +1.45 | [−0.0503, +0.3345] |
| **DEV EXPANSION@2h** | 395 | 394 | **+0.3317** | +0.2036 | 2.741 | 0.1381 | **+2.40** | [+0.0610, +0.6023] |
| DEV EXPANSION@4h | 395 | 388 | +0.2128 | +0.1399 | 3.481 | 0.1767 | +1.20 | [−0.1335, +0.5591] |
| DEV CONTRACTION@1h | 394 | 394 | +0.0424 | +0.0510 | 1.079 | 0.0543 | +0.78 | [−0.0641, +0.1489] |
| DEV CONTRACTION@2h | 394 | 394 | +0.1014 | +0.1430 | 1.547 | 0.0779 | +1.30 | [−0.0514, +0.2541] |
| **DEV CONTRACTION@4h** | 394 | 387 | **+0.3687** | +0.3104 | 2.616 | 0.1330 | **+2.77** | [+0.1081, +0.6294] |
| POOLED EXPANSION@1h *(desc.)* | 1,092 | 1,092 | +0.0818 | +0.0402 | 1.965 | 0.0595 | +1.38 | [−0.0347, +0.1984] |
| POOLED EXPANSION@2h *(desc.)* | 1,092 | 1,090 | +0.1475 | +0.1009 | 2.793 | 0.0846 | +1.74 | [−0.0183, +0.3133] |
| POOLED EXPANSION@4h *(desc.)* | 1,092 | 1,075 | +0.0539 | −0.0161 | 3.451 | 0.1053 | +0.51 | [−0.1524, +0.2602] |
| POOLED CONTRACTION@1h *(desc.)* | 1,091 | 1,091 | +0.0789 | +0.0516 | 1.167 | 0.0353 | +2.23 | [+0.0097, +0.1482] |
| POOLED CONTRACTION@2h *(desc.)* | 1,091 | 1,089 | +0.0848 | +0.0776 | 1.543 | 0.0468 | +1.81 | [−0.0068, +0.1765] |
| POOLED CONTRACTION@4h *(desc.)* | 1,091 | 1,076 | +0.2111 | +0.2142 | 2.557 | 0.0780 | +2.71 | [+0.0583, +0.3639] |

**Sixteen of eighteen point estimates are positive.** In a sample whose arms rose
+33.63% and +44.24%, that is the signature of drift, and §H is where it is
measured rather than assumed.

Note the dispersion: contraction cells have **sd 1.21–2.62** against expansion's
**1.95–3.48**. Volatility contraction genuinely predicts *smaller* subsequent
moves — a real and unsurprising volatility fact — and because it shrinks the
standard error it inflates t for the same mean. That is why the largest TRAIN t
appears in a contraction cell with one of the smallest means.

**Long and short outcomes.** For a direction-less event the long-direction
outcome is `+S_h` and the short-direction outcome is `−S_h` — **exact negatives,
a presentational symmetry and not two findings.** No inference is drawn from their
difference.

---

## H. Unconditional baseline comparison (Control 1)

| Cell | event mean | **unconditional** | excess |
|---|---|---|---|
| TRAIN EXPANSION@1h | +0.0477 | +0.0296 | +0.018 |
| TRAIN EXPANSION@2h | +0.0433 | +0.0582 | −0.015 |
| TRAIN EXPANSION@4h | −0.0359 | +0.1063 | **−0.142** |
| TRAIN CONTRACTION@1h | +0.0996 | +0.0296 | **+0.070** |
| TRAIN CONTRACTION@2h | +0.0754 | +0.0582 | +0.017 |
| TRAIN CONTRACTION@4h | +0.1225 | +0.1063 | +0.016 |
| DEV EXPANSION@1h | +0.1421 | +0.0606 | +0.082 |
| DEV EXPANSION@2h | +0.3317 | +0.1228 | **+0.209** |
| DEV EXPANSION@4h | +0.2128 | +0.2329 | −0.020 |
| DEV CONTRACTION@1h | +0.0424 | +0.0606 | −0.018 |
| DEV CONTRACTION@2h | +0.1014 | +0.1228 | −0.021 |
| DEV CONTRACTION@4h | +0.3687 | +0.2329 | +0.136 |

**The unconditional drift is large** — up to **+0.2329 ATR** at DEV 4h with no
condition applied at all. Most of every positive event mean is this. Six of the
twelve excesses are negative.

### A failure-mode diagnostic that came back negative

I suspected the ATR normaliser was inflating contraction cells: if `A[i]` were
depressed at a contraction event, the same dollar drift would produce a larger
normalised mean. **It is not.** Mean `A[i]` at contraction events is **1.052×**
unconditional in TRAIN and **1.020×** in DEV — slightly *higher*, not lower,
because `A` is a 14-bar Wilder average while the state is set by a 4-bar window,
and reaching a contraction event requires having come from HIGH, so the 14-bar
average still carries the recent large bars.

The effect is present in dollars too: TRAIN contraction 1h drift is **+$0.2262**
against **+$0.0508** unconditional. So the normaliser is exonerated, and the
controls in §I–§J carry the argument instead. Reported because a diagnostic that
rules out an artifact is worth as much as one that finds it.

---

## I. Volatility-state control (Control 2)

Events compared with bars **in the same volatility state that are not transition
bars** — separating *transitioning into* a state from *being in* it, which is the
hypothesis's actual claim.

| Cell | diff | t | | Cell | diff | t |
|---|---|---|---|---|---|---|
| TRAIN EXP@1h | +0.0294 | +0.36 | | DEV EXP@1h | +0.0761 | +0.71 |
| TRAIN EXP@2h | +0.0573 | +0.47 | | DEV EXP@2h | +0.2167 | +1.37 |
| TRAIN EXP@4h | +0.0067 | +0.04 | | DEV EXP@4h | +0.0520 | +0.24 |
| TRAIN CON@1h | +0.0458 | +0.88 | | DEV CON@1h | −0.0327 | −0.49 |
| TRAIN CON@2h | +0.0369 | +0.49 | | DEV CON@2h | −0.0138 | −0.13 |
| TRAIN CON@4h | −0.0203 | −0.16 | | DEV CON@4h | +0.0773 | +0.41 |

**Maximum |t| 1.37.** Transitioning into a volatility state is statistically
indistinguishable from merely being in it. The contraction cells **flip sign
between arms** at all three horizons.

## J. Displacement / drift control (Control 3) — the decisive test

Events against non-events **within frozen TRAIN quintiles of `disp_12`**,
aggregated **observation-weighted by event count per stratum** — never an
equal-weighted mean of per-stratum means, which is where Phase 1 failed, and the
strata are frozen feature quantiles so their composition is not endogenous to the
outcome. All five strata were populated in every cell.

| Cell | **diff** | se | **t** | 95% CI | | TRAIN↔DEV sign |
|---|---|---|---|---|---|---|
| TRAIN EXPANSION@1h | +0.0241 | 0.0764 | **+0.32** | [−0.1256, +0.1739] | DEV +0.0824 (t +0.82) | same |
| TRAIN EXPANSION@2h | −0.0179 | 0.1109 | **−0.16** | [−0.2352, +0.1994] | DEV +0.2132 (t +1.49) | **FLIP** |
| TRAIN EXPANSION@4h | −0.1473 | 0.1449 | **−1.02** | [−0.4313, +0.1366] | DEV −0.0374 (t −0.19) | same |
| TRAIN CONTRACTION@1h | +0.0660 | 0.0483 | **+1.36** | [−0.0288, +0.1607] | DEV −0.0154 (t −0.27) | **FLIP** |
| TRAIN CONTRACTION@2h | +0.0161 | 0.0660 | **+0.24** | [−0.1133, +0.1454] | DEV −0.0208 (t −0.24) | **FLIP** |
| TRAIN CONTRACTION@4h | −0.0230 | 0.1141 | **−0.20** | [−0.2467, +0.2007] | DEV +0.1336 (t +0.85) | **FLIP** |

**Maximum |t| across all twelve controlled cells is 1.49; TRAIN's maximum is
1.36.** Every interval straddles zero. **Four of six transition×horizon cells
reverse sign between TRAIN and DEV.**

DEV standard errors are omitted from the table for width and are recorded in
`hypothesis_03_results.json` under
`controls.*.C3_matched_displacement_stratum.aggregate`, together with the
per-stratum counts, means and differences for all five strata in every cell.

This is the control the hypothesis was built to survive — the competing
explanation that *volatility increased because price was already moving.* Once
recent displacement is matched, nothing remains.

The two cells that looked strongest in §G collapse here:
`DEV|CONTRACTION@4h` falls from t **+2.77** to **+0.85**, and its TRAIN
counterpart is **−0.0230** — the opposite sign. `DEV|EXPANSION@2h` falls from
**+2.40** to **+1.49**, and its TRAIN counterpart is **−0.0179**.

## Control 4 — opposite transition

| Cell | diff vs opposite | t | | Cell | diff | t |
|---|---|---|---|---|---|---|
| TRAIN EXP@1h | −0.0519 | −0.59 | | DEV EXP@1h | +0.0997 | +0.89 |
| TRAIN EXP@2h | −0.0322 | −0.26 | | DEV EXP@2h | +0.2303 | +1.45 |
| TRAIN EXP@4h | −0.1584 | −0.98 | | DEV EXP@4h | −0.1559 | −0.71 |

**Maximum |t| 1.45**, and the sign reverses between arms at 1h and 2h. Expansion
and contraction are not distinguishable from each other.

Only the expansion rows are shown because the contraction rows are their **exact
negatives** by construction — TRAIN CON@1h is +0.0519 against TRAIN EXP@1h's
−0.0519 — so printing both would present one comparison as two. All twelve are in
`hypothesis_03_results.json` under `controls.*.C4_opposite_transition`.

---

## K. H1 regime conditioning

Event means by H1 regime, frozen TRAIN terciles of `z = (h1_close − h1_sma50)/h1_atr14`,
from the last H1 bar closed at or before the event bar. H1 never assigned
direction and never selected or weighted events.

| Cell | BULLISH | NEUTRAL | BEARISH |
|---|---|---|---|
| TRAIN EXPANSION@1h | −0.015 (236) | **+0.187** (232) | −0.029 (229) |
| TRAIN EXPANSION@2h | −0.074 (236) | **+0.241** (232) | −0.036 (228) |
| TRAIN EXPANSION@4h | −0.024 (234) | **+0.138** (232) | **−0.280** (223) |
| TRAIN CONTRACTION@1h | +0.103 (238) | +0.118 (210) | +0.081 (249) |
| TRAIN CONTRACTION@2h | +0.013 (238) | +0.045 (209) | +0.161 (248) |
| TRAIN CONTRACTION@4h | **−0.163** (237) | +0.254 (209) | +0.289 (247) |
| DEV EXPANSION@1h | +0.180 (151) | +0.173 (131) | +0.056 (113) |
| DEV EXPANSION@2h | +0.339 (151) | +0.168 (130) | **+0.510** (113) |
| DEV EXPANSION@4h | +0.321 (148) | −0.112 (128) | +0.454 (113) |
| DEV CONTRACTION@1h | +0.022 (150) | +0.076 (125) | +0.033 (119) |
| DEV CONTRACTION@2h | +0.272 (150) | −0.062 (125) | +0.057 (119) |
| DEV CONTRACTION@4h | +0.278 (147) | **+0.493** (125) | +0.260 (118) |

**The whole TRAIN expansion effect lives in the NEUTRAL regime** — +0.187, +0.241,
+0.138 against roughly zero or negative in BULLISH and BEARISH. That is
single-regime dependency, which §12 makes evidence against rather than for.

**And the regime pattern does not replicate.** In DEV the expansion effect is
*largest in BEARISH* at 2h (+0.510) and in BULLISH at 4h (+0.321), while
TRAIN BEARISH@4h is **−0.280**. The regime structure inverts between arms.

Cell sizes are 113–249 events, well below the 100-event floor in no case but far
too small for these splits to be anything but descriptive. No optimisation around
regime was performed.

---

## L. Analytic and bootstrap estimates

Three estimators per cell, with the Phase 1 distinction maintained explicitly:

1. **Analytic non-overlapping** — the headline (§G).
2. **Moving-block bootstrap** — blocks of 96 and 480 M15 bars, 4,000 replicates,
   seed 20261004, declared in advance. Each replicate is **observation-weighted**
   within resampled contiguous blocks. **This is not the estimator that failed in
   Phase 1.**
3. **Equal-block mean** — an unweighted mean of per-block means, whose per-block
   counts are endogenous. This *is* the Phase 1 failure mode, and it is carried
   **only** as the input to the sign-disagreement check, never as evidence.

**`ESTIMATOR_SIGN_DISAGREEMENT`: 0 of 18 cells.** The raw and block estimators
agree in sign throughout, so no cell required the "flag the hypothesis rather
than choose the favourable estimator" rule. Full per-cell bootstrap means, SEs,
t-values and intervals are in `hypothesis_03_results.json` under
`primary.*.bootstrap`.

## M. Multiple-testing results

| | declared 6 | **accumulated 9 (promotion test)** |
|---|---|---|
| Bonferroni threshold \|t\| | 2.638 | **2.773** |
| **Bonferroni survivors** | **0** | **0** |
| **Benjamini–Hochberg survivors** | **0** | **0** |
| Expected \|t\| ≥ 2 under null | 0.273 | 0.410 |

TRAIN t-values: EXPANSION +0.638, +0.405, −0.274; CONTRACTION **+2.166**, +1.289,
+1.276. **Max |t| 2.166**, observed |t| ≥ 2 is **1** against 0.41 expected — one
exceedance where chance predicts about half of one.

---

## N. Power and MDE

| Cell | non-ov n | se | MDE 2 SE | **MDE corrected** | cost (ATR) | detectable? |
|---|---|---|---|---|---|---|
| TRAIN EXPANSION@1h | 697 | 0.0747 | 0.149 | 0.207 | 0.158 | no |
| TRAIN EXPANSION@2h | 696 | 0.1068 | 0.214 | 0.296 | 0.158 | no |
| TRAIN EXPANSION@4h | 687 | 0.1310 | 0.262 | 0.363 | 0.158 | no |
| **TRAIN CONTRACTION@1h** | 697 | 0.0460 | 0.092 | **0.128** | 0.158 | **YES** |
| TRAIN CONTRACTION@2h | 695 | 0.0585 | 0.117 | 0.162 | 0.158 | no (just) |
| TRAIN CONTRACTION@4h | 689 | 0.0961 | 0.192 | 0.266 | 0.158 | no |
| DEV EXPANSION@1h | 395 | 0.0982 | 0.196 | 0.272 | 0.093 | no |
| DEV EXPANSION@2h | 394 | 0.1381 | 0.276 | 0.383 | 0.093 | no |
| DEV EXPANSION@4h | 388 | 0.1767 | 0.353 | 0.490 | 0.093 | no |
| DEV CONTRACTION@1h | 394 | 0.0544 | 0.109 | 0.151 | 0.093 | no |
| DEV CONTRACTION@2h | 394 | 0.0779 | 0.156 | 0.216 | 0.093 | no |
| DEV CONTRACTION@4h | 387 | 0.1330 | 0.266 | 0.369 | 0.093 | no |

**One cell of twelve was powered to resolve a cost-sized effect**, and it is the
one that carried the largest TRAIN t. For the other eleven, every null is a bound
of **0.151–0.490 ATR**, not an absence, and is stated as such.

## O. Cost screen

Round-turn spread cost = **1 × spread**, measured median **$0.33**:
**0.158 ATR** in TRAIN, **0.093 ATR** in DEV.

| Cell | gross (ATR) | cost | \|gross\| − cost |
|---|---|---|---|
| **TRAIN CONTRACTION@1h** (only powered cell) | +0.0996 | 0.158 | **−0.058** |
| TRAIN CONTRACTION@4h | +0.1225 | 0.158 | −0.036 |
| TRAIN EXPANSION@1h | +0.0477 | 0.158 | −0.110 |
| DEV CONTRACTION@4h | +0.3687 | 0.093 | +0.276 |
| DEV EXPANSION@2h | +0.3317 | 0.093 | +0.239 |

**The only power-sufficient cell is below cost.** Two DEV cells exceed cost gross,
but both fail correction, both collapse under the displacement control (§J), and
both have TRAIN counterparts of the opposite sign.

> These net figures are **not expected returns** and must not be read as such for
> cells that failed the statistical screen. My own Research-to-Strategy Gate §9.1
> defers the cost screen until after the statistical screen passes, precisely to
> avoid that reading; this authorisation requested the cost screen as output O, so
> it is reported here with the caveat attached rather than omitted. No execution
> model is implied and no cost was optimised.

## P. TRAIN → DEV replication

The identical frozen definitions were applied to DEV. Nothing was refit —
confirmed in `hypothesis_03_controls.json`: `thresholds_refit_on_dev: false`,
`strata_refit_on_dev: false`, `h1_cuts_refit_on_dev: false`.

| Quantity | Result |
|---|---|
| raw same-sign replication | 5 of 6 (TRAIN EXPANSION@4h negative, DEV positive) |
| **same-sign after the displacement control** | **2 of 6** |
| magnitude stability | poor: DEV magnitudes are 2–8× TRAIN's at matching cells |
| survives cost | no cell survives both correction and cost |
| survives H1 conditioning | no — the regime structure inverts between arms (§K) |

TRAIN was null and underpowered at eleven of twelve cells, and **no DEV rescue was
attempted.** DEV's two nominally significant cells are reported as the chance
outcomes they are: with 12 cells examined and a two-sided α of 0.05, about 0.6
nominal exceedances are expected, and both vanish under the pre-registered
controls.

## Q. Failure-mode diagnostics

**The decisive one — volatility expansion without direction.** MFE and MAE in ATR
units:

| Cell | MFE | MAE | **\|MFE\|−\|MAE\|** | asymmetry as % of MFE |
|---|---|---|---|---|
| TRAIN EXPANSION@1h | +1.532 | −1.469 | +0.063 | 4.1% |
| TRAIN EXPANSION@2h | +2.116 | −2.036 | +0.081 | 3.8% |
| TRAIN EXPANSION@4h | +2.692 | −2.671 | **+0.021** | **0.8%** |
| TRAIN CONTRACTION@1h | +0.750 | −0.644 | +0.106 | 14.2% |
| TRAIN CONTRACTION@2h | +1.090 | −0.987 | +0.103 | 9.5% |
| TRAIN CONTRACTION@4h | +1.792 | −1.595 | +0.198 | 11.0% |
| DEV EXPANSION@1h | +1.412 | −1.339 | +0.073 | 5.2% |
| DEV EXPANSION@2h | +2.007 | −1.826 | +0.181 | 9.0% |
| DEV EXPANSION@4h | +2.567 | −2.493 | +0.074 | 2.9% |
| DEV CONTRACTION@1h | +0.796 | −0.825 | **−0.029** | −3.7% |
| DEV CONTRACTION@2h | +1.189 | −1.247 | **−0.058** | −4.9% |
| DEV CONTRACTION@4h | +2.082 | −1.818 | +0.264 | 12.7% |

A volatility expansion moves price **2.7 ATR in both directions within four
hours** and the favourable/adverse asymmetry is **0.8%** of that. The transition
does exactly what it says — it changes the amount of movement — and carries no
usable directional component. §12 makes this an explicit rejection criterion, and
it is met.

Contraction cells confirm the mirror image: MFE/MAE of 0.64–0.83 at 1h, roughly
half the expansion figures. **The state variable predicts volatility well and
direction not at all.** Two DEV contraction cells have *negative* asymmetry.

**Other diagnostics.** The ATR-normaliser artifact was tested and **ruled out**
(§H). Causal reconstruction **passed** (§ below). `ESTIMATOR_SIGN_DISAGREEMENT`
occurred in **0** cells. Forward-window audits were disjoint in **0 of 18**
failures. The exploratory displacement-direction labels (§7.3 of the spec) are
recorded in `hypothesis_03_results.json` under `exploratory_disp_direction`,
labelled exploratory, and **were not used in any classification decision**.

### Causal reconstruction — tolerances frozen before the run

| Quantity | Frozen tolerance | Observed | Result |
|---|---|---|---|
| `short_vol`, `long_vol` | relative 1e-13 | **0.0** (exact) | PASS |
| `VOL_RATIO` | relative 1e-13 | **0.0** (exact) | PASS |
| `disp_12` | relative 1e-12 | 4.84e-16 | PASS |
| `ATR_14` | relative 1e-12 | 3.58e-16 | PASS |
| `state` / event classification | 0 disagreements | **0** | PASS |

60 probes, seed 20261004, every quantity rebuilt from `m15.iloc[:i]`. The volatility
sums reconstruct **exactly** — finite sums over identical inputs perform
deterministic arithmetic — and only the two ATR-derived quantities show
float64-level deviation, as the frozen tolerances anticipated.

---

## Limitations

1. **Eleven of twelve cells are underpowered against cost** (§N). Their nulls are
   bounds of 0.151–0.490 ATR. The rejection rests on the one powered cell plus the
   control failures, not on the underpowered nulls.
2. **One instrument, one broker, one era.** XAUUSD, 2022-06 → 2025-09, both arms
   rising, **no multi-year bear market**. The drift that dominates §G cannot be
   separated from the sample's trend by this data.
3. **H1 regime cells are 113–249 events** — descriptive only. The single-regime
   dependency in §K is a real pattern in TRAIN but could not be confirmed or
   refuted at this sample size, and it inverts in DEV.
4. **One parameterisation only** — `N_short=4`, `N_long=96`, 80/20 thresholds,
   `disp_12`, three horizons, two transition types. A different window pair is a
   different hypothesis requiring its own pre-registration, and per the gate it
   would inherit the accumulated burden, which now stands at **15** for this
   construct family (9 before this run, plus the 6 declared here).
5. **The cost screen was run on a null** at this authorisation's request, against
   my own gate's ordering. The caveat is attached in §O; the figures should not be
   cited without it.
6. **`disp_12` is one displacement definition.** Control 3's power to remove the
   "price was already moving" explanation is only as good as that proxy. A longer
   or shorter displacement window could match differently — but testing several
   would be the feature mining the specification forbids.
7. **No execution realism work.** `close[i]` is the decision point and is not
   tradable; no spread, slippage or fill uncertainty is modelled, because the gate
   stops before it.

---

## R. Final classification

# HYPOTHESIS 03 — NOT SUPPORTED

The mechanism proposed that a volatility-state transition marks incomplete
repricing, leaving a residual directional adjustment over the following hours.
**The transition is real and strongly detectable — it just is not directional.**

A volatility expansion reliably doubles subsequent excursion (MFE 2.7 ATR at 4h
against contraction's 1.8), and a contraction reliably halves it (sd 1.21 against
1.97 at 1h). The state variable works, as a *volatility* forecast. But the
favourable/adverse asymmetry after an expansion is **0.8%** of the excursion it
produces, the apparent directional means are mostly the sample's **+0.23 ATR**
unconditional drift, and once recent displacement is matched **nothing survives**:
maximum controlled |t| **1.49** across twelve cells, with four of six reversing
sign between TRAIN and DEV.

Where the data could decide — the one cell powered against cost — the gross
effect came in **below cost** and failed every control.

**Four of five pre-registered rejection criteria are met; none of the seven
SUPPORTED conditions is.** The word "edge" does not appear as a claim anywhere in
this report.

### Should H03 be closed?

**Closed.** Not because the test was weak — it was the cleanest in this
programme: zero endpoint coupling by construction, overlap ratio 1.0× throughout,
zero estimator sign disagreements, exact causal reconstruction of the volatility
sums, and a decisive control that the earlier hypotheses could not deploy.

It should be closed because the **mechanism is refuted in its directional form by
the strongest evidence here**, which is not a p-value but §Q: the transition
produces symmetric movement. A better-powered test of the same construct would
measure the same 0.8% asymmetry more precisely. The remaining uncertainty is about
*magnitude bounds* on eleven underpowered cells, not about the sign or the
mechanism.

**The exact pre-registered test does not warrant further analysis.** What the
evidence does support — and this is a statement about volatility, not direction,
and not a strategy proposal — is that `VOL_RATIO` is an effective **forecaster of
subsequent range**. That is a different hypothesis family with different uses, and
it would require its own authorisation and its own pre-registration.

**H04 is not begun.** FINAL_OOS was not opened. No strategy was designed, no
threshold optimised, no alternative parameter tested, no feature searched. No
profitability claim is made or implied.
