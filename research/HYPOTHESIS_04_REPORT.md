# Hypothesis 04 — LIQUIDITY DISPLACEMENT → ACCEPTANCE / REJECTION

## HYPOTHESIS 04 — NOT SUPPORTED

**0 survivors of 12 declared hypotheses**, 0 of the accumulated 30, and 0 of the
programme-wide 138, under both Bonferroni and Benjamini–Hochberg. Maximum |t| in
the primary arm was **1.973** against a promotion threshold of **3.144**. **Zero**
TRAIN cells reached |t| ≥ 2.

**Six of the seven pre-registered rejection criteria are met.** Any one suffices
under §16 of the specification:

| # | Rejection criterion (§16) | Met? | Evidence |
|---|---|---|---|
| 1 | no corrected TRAIN evidence **and** effects small vs power/cost | **YES** | 0 survivors; **0 of 24** cells powered against cost; every TRAIN cell net-negative after cost |
| 2 | acceptance/rejection adds no information beyond displacement | **YES** | ACCEPT−REJECT contrast max \|t\| **1.50**, and **negative in 4 of 6** cells — the *wrong sign* |
| 3 | displacement-matched controls remove the effect | **YES** | matched magnitude max \|t\| **1.32**; matched recent displacement max \|t\| **1.38** |
| 4 | TRAIN and DEV signs unstable | **YES** | **5 of 12** cells reverse; LONG_ACCEPT flips at all three horizons |
| 5 | estimator signs disagree materially | **YES** | 3 cells flagged; the strongest TRAIN cell's t **halves** under the bootstrap (−1.97 → −0.81) |
| 6 | apparent direction explained by ordinary drift | **YES, decisively** | in DEV **all four states** track their predicted direction's drift sign, and **none exceeds drift** |
| 7 | result depends on one narrow regime | **YES** | the four states are **entangled with regime by construction** (TRAIN SHORT_ACCEPT: 45 bullish vs 340 bearish events) |

**None of the nine SUPPORTED conditions is satisfied** except condition 1 (clean
causal definition) and condition 9 (no endpoint coupling) — both of which this
design achieved, and neither of which is sufficient. **The word "edge" is not used
as a claim anywhere in this report.**

**FINAL_OOS was not opened.** No DEV tuning. M5/M1 not used. Production and
`baseline_008` untouched.

---

## A. The frozen specification

`research/hypothesis_04_liquidity_displacement.md`, committed at **`43dc34c`** —
specification only, verified by git inspection.

**12 primary tests** pre-declared: 4 states × 3 horizons. One area lookback, one
displacement interval, one threshold percentile, one acceptance window, one ATR
length. **No alternative was computed.**

### Accumulated burden, applied as frozen

| | Tests | Bonferroni \|t\| | Survivors |
|---|---|---|---|
| declared | 12 | 2.865 | **0** |
| **accumulated (promotion test)** | **30** = 12 + 18 prior displacement cells | **3.144** | **0** |
| programme-wide (disclosed) | 138 | 3.566 | **0** |

The 18 prior cells are Phase 1's `disp_1/4/8/16` × 3 horizons (12), the
continuation audit's family B (3) and Phase 3's layer C (3) — all of which failed,
and all of which were additionally **endpoint-coupled** (`disp_w` contains
`close[i]`; the label subtracts `close[i]`), a defect H04 does not inherit.

---

## B. Exact mathematical definitions

```
a = 24  area lookback      d = 4  displacement interval      w = 4  accept window

PRIOR_HIGH[e] = max( high[k] : k = e-27 .. e-4 )
PRIOR_LOW [e] = min( low [k] : k = e-27 .. e-4 )
A[k]          = ATR_14[k-1]                                 Wilder, M15

displacement_size[e] = | close[e] - close[e-4] | / A[e]
direction  d_e       = +1 if close[e] > close[e-4],  -1 if <
recent_disp[e]       = ( close[e-4] - close[e-16] ) / A[e-4]

EVENT at e requires:  displacement_size[e] >= TAU
                      AND ( d_e = +1 and close[e] > PRIOR_HIGH[e] )
                       OR ( d_e = -1 and close[e] < PRIOR_LOW [e] )

boundary B = PRIOR_HIGH[e] (LONG) or PRIOR_LOW[e] (SHORT), FIXED at detection

ACCEPTANCE: close[k] beyond B for ALL k in e+1 .. e+4
REJECTION : close[k] back through B for SOME k in e+1 .. e+4

pred_e = +d_e (ACCEPTANCE, continuation) or -d_e (REJECTION, reversal)
P0 = open[e+5]        A0 = A[e+5] = ATR_14[e+4]
R_h = pred_e * ( close[e+4+h] - P0 ) / A0        h = 4, 8, 16
$_h = pred_e * ( close[e+4+h] - P0 )
```

---

## C. Causal event timeline, with worked examples

```
bars e-27..e-4        bars e-3..e          bars e+1..e+4        bar e+5 ... e+4+h
|-----------------|  |-----------------|  |-----------------|  |---------------->
   PRIOR AREA          DISPLACEMENT         ACCEPT / REJECT        FORWARD LABEL
   highs & lows        close[e] vs          closes vs B,          anchor open[e+5]
   only                close[e-4]           B fixed at e-4        exit close[e+4+h]

   <----------- FEATURE PERIOD: bars <= e+4 ----------->
                                              <------ LABEL PERIOD: bars >= e+5 ---->
```

### Worked LONG event — TRAIN, bar e = 120

| Step | Bars | Values |
|---|---|---|
| Prior area | 93–116 (2022-07-01 07:15 → 13:00) | `PRIOR_HIGH` **1797.96**, `PRIOR_LOW` 1784.45 |
| Displacement | 117–120 | `close[e-4]` 1792.33 → `close[e]` **1799.67**; `A[e]` 3.7626 |
| | | `displacement_size` **1.9508** ≥ `TAU` 1.5265 ✓; `close[e] > PRIOR_HIGH` ✓ → LONG |
| Classification | 121–124 | closes 1800.59, 1800.84, 1800.78, 1807.39 — **all above 1797.96** → **ACCEPTANCE** |
| Label | anchor bar 125 | `open[125]` = **1807.39**, 2022-07-01 15:15; predicted direction **+1** |

### Worked SHORT event — TRAIN, bar e = 79

| Step | Bars | Values |
|---|---|---|
| Prior area | 52–75 (2022-06-30 20:00 → 2022-07-01 02:45) | `PRIOR_HIGH` 1807.58, `PRIOR_LOW` **1803.49** |
| Displacement | 76–79 | `close[e-4]` 1804.37 → `close[e]` **1801.46**; `A[e]` 1.5583 |
| | | `displacement_size` **1.8674** ≥ `TAU` ✓; `close[e] < PRIOR_LOW` ✓ → SHORT |
| Classification | 80–83 | closes 1801.52, 1802.02, 1801.45, 1802.89 — **all below 1803.49** → **ACCEPTANCE** |
| Label | anchor bar 84 | `open[84]` = **1802.89**, 2022-07-01 05:00; predicted direction **−1** |

In both cases the highest bar index any feature reads is `e+4`, and the lowest bar
index any label price comes from is `e+5`.

---

## D. Threshold derivation — TRAIN only, frozen

| | |
|---|---|
| **`TAU`** (80th pct of `displacement_size`, TRAIN) | **1.5265333579240024** |
| `disp_size` quintile cuts, **TRAIN EVENTS** (baseline D) | 1.7470, 2.0105, 2.4093, 3.0453 |
| `disp_size` quintile cuts, TRAIN population — **degenerate, see §L** | 0.2671, 0.5643, 0.9371, 1.5265 |
| `recent_disp` quintile cuts, TRAIN (baseline E) | from `hypothesis_04_results.json` |
| H1 `z` tercile cuts, TRAIN | −1.0270, +1.4944 |

**Nothing was refit on DEV** — confirmed in the controls file:
`tau_refit_on_dev: false`, `strata_refit_on_dev: false`, `h1_cuts_refit_on_dev: false`.

---

## E–G. Event counts, deduplication accounting, raw / non-overlap counts

| | TRAIN | DEV |
|---|---|---|
| **raw qualifying displacements** | **5,678** | **2,915** |
| suppressed — condition not yet absent (same move) | 3,290 | 1,690 |
| suppressed — inside an unresolved classification window | 317 | 163 |
| **ambiguous (both boundaries)** | **0** | **0** |
| **retained events** | **2,071** | **1,062** |
| invalid (timeline outside arm / bad ATR) | 0 | 1 |
| **valid events** | **2,071** | **1,061** |
| → **ACCEPTANCE** | **1,164 (56.20%)** | **605 (57.02%)** |
| → **REJECTION** | **907** | **456** |

The deduplication machine did the bulk of the work: **64% of raw qualifying
displacements were suppressed**, almost all as continuations of a move already
counted. The declared precedence rule — earlier episode wins — suppressed 317
TRAIN and 163 DEV displacements that arrived inside an unresolved window.

**Acceptance rate is stable across arms** (56.2% vs 57.0%) — a reproducible
descriptive fact.

| Cell | raw n | non-overlap n | overlap |
|---|---|---|---|
| TRAIN LONG_ACCEPT 1h/2h/4h | 624 | 624 / 569 / 502 | 1.0× / 1.1× / 1.2× |
| TRAIN LONG_REJECT | 470 | 470 / 449 / 414 | 1.0× / 1.0× / 1.1× |
| TRAIN SHORT_ACCEPT | 540 | 540 / 492 / 448 | 1.0× / 1.1× / 1.2× |
| TRAIN SHORT_REJECT | 437 | 437 / 424 / 399 | 1.0× / 1.0× / 1.1× |
| DEV LONG_ACCEPT | 363 | 363 / 334 / 292 | 1.0× / 1.1× / 1.2× |
| DEV LONG_REJECT | 236 | 236 / 230 / 213 | 1.0× / 1.0× / 1.1× |
| DEV SHORT_ACCEPT | 242 | 242 / 223 / 196 | 1.0× / 1.1× / 1.2× |
| DEV SHORT_REJECT | 220 | 220 / 204 / 188 | 1.0× / 1.1× / 1.2× |

**Overlap 1.0–1.2× throughout.** Every cell exceeds the 100-event minimum. The
nulls are not artefacts of discarded observations.

---

## H–I. Returns at 1h / 2h / 4h, all four directional states

Headline: direction-normalised `R_h`, non-overlapping events. `$` is the raw
dollar return in the predicted direction.

| Cell | mean (ATR) | median | sd | se | **t** | **$** |
|---|---|---|---|---|---|---|
| TRAIN LONG_ACCEPT@1h | −0.0559 | −0.0836 | 1.626 | 0.0651 | −0.86 | −0.068 |
| TRAIN LONG_ACCEPT@2h | −0.0554 | −0.0594 | 2.356 | 0.0988 | −0.56 | −0.037 |
| TRAIN LONG_ACCEPT@4h | −0.0025 | +0.0799 | 3.428 | 0.1530 | −0.02 | +0.286 |
| TRAIN LONG_REJECT@1h | −0.0306 | +0.0597 | 1.725 | 0.0796 | −0.38 | −0.124 |
| TRAIN LONG_REJECT@2h | −0.0887 | +0.0651 | 2.381 | 0.1123 | −0.79 | −0.182 |
| **TRAIN LONG_REJECT@4h** | **−0.3215** | +0.0346 | 3.315 | 0.1629 | **−1.97** | −0.455 |
| TRAIN SHORT_ACCEPT@1h | +0.0972 | +0.0276 | 1.398 | 0.0602 | +1.62 | +0.312 |
| TRAIN SHORT_ACCEPT@2h | +0.0146 | −0.1367 | 1.887 | 0.0851 | +0.17 | +0.106 |
| TRAIN SHORT_ACCEPT@4h | −0.0452 | −0.0185 | 3.188 | 0.1506 | −0.30 | +0.049 |
| TRAIN SHORT_REJECT@1h | +0.1054 | −0.0275 | 1.538 | 0.0736 | +1.43 | +0.216 |
| TRAIN SHORT_REJECT@2h | +0.0272 | −0.0060 | 2.176 | 0.1057 | +0.26 | −0.007 |
| TRAIN SHORT_REJECT@4h | +0.0444 | −0.0773 | 3.019 | 0.1511 | +0.29 | +0.180 |
| DEV LONG_ACCEPT@1h | +0.1057 | +0.1553 | 1.475 | 0.0774 | +1.37 | +0.401 |
| DEV LONG_ACCEPT@2h | +0.2208 | +0.2915 | 2.116 | 0.1158 | +1.91 | +0.711 |
| DEV LONG_ACCEPT@4h | +0.2285 | +0.2377 | 2.933 | 0.1716 | +1.33 | +0.634 |
| **DEV LONG_REJECT@1h** | **−0.3522** | −0.2812 | 1.666 | 0.1085 | **−3.25** | −1.190 |
| DEV LONG_REJECT@2h | −0.2974 | −0.1925 | 2.146 | 0.1415 | −2.10 | −1.160 |
| **DEV LONG_REJECT@4h** | **−0.5003** | −0.3204 | 2.759 | 0.1891 | **−2.65** | −1.470 |
| DEV SHORT_ACCEPT@1h | −0.1314 | −0.2091 | 1.532 | 0.0985 | −1.33 | −0.663 |
| DEV SHORT_ACCEPT@2h | −0.0890 | −0.4536 | 2.051 | 0.1374 | −0.65 | −0.345 |
| DEV SHORT_ACCEPT@4h | −0.2048 | −0.3759 | 2.543 | 0.1816 | −1.13 | −0.923 |
| DEV SHORT_REJECT@1h | +0.0495 | −0.0079 | 1.614 | 0.1088 | +0.46 | +0.019 |
| DEV SHORT_REJECT@2h | +0.1351 | +0.1413 | 2.395 | 0.1677 | +0.81 | +0.193 |
| DEV SHORT_REJECT@4h | +0.0804 | +0.1284 | 3.051 | 0.2225 | +0.36 | +0.048 |

### Pattern classification (§9 requires exactly one label)

**DRIFT-DRIVEN, and UNSTABLE between arms.** Not continuation, not reversal, not a
coherent asymmetry.

The reasoning is in §J. The decisive observation: **in DEV every state's sign
equals the sign its *predicted direction* would earn from drift alone** —

| State | predicted | DEV means (1h/2h/4h) | sign |
|---|---|---|---|
| LONG_ACCEPT | **long** | +0.106, +0.221, +0.229 | all **+** |
| LONG_REJECT | **short** | −0.352, −0.297, −0.500 | all **−** |
| SHORT_ACCEPT | **short** | −0.131, −0.089, −0.205 | all **−** |
| SHORT_REJECT | **long** | +0.050, +0.135, +0.080 | all **+** |

Every predicted-long state is positive; every predicted-short state is negative.
That is what a rising market does to long and short positions, with **no
contribution from acceptance or rejection at all**.

**TRAIN is not even drift-consistent.** `LONG_ACCEPT` (predicted long) is
**negative** at all three horizons while long drift is +0.029/+0.057/+0.105, and
`SHORT_ACCEPT` (predicted short) is **positive** at 1h while short drift is
−0.029. TRAIN and DEV therefore contradict each other as well as the hypothesis.

### TRAIN → DEV sign stability (§R)

| State | TRAIN | DEV | stable? |
|---|---|---|---|
| LONG_ACCEPT | −, −, − | +, +, + | **flips at all 3** |
| LONG_REJECT | −, −, − | −, −, − | same (both *wrong* sign) |
| SHORT_ACCEPT | +, +, − | −, −, − | **flips at 1h, 2h** |
| SHORT_REJECT | +, +, + | +, +, + | same |

**5 of 12 cells reverse sign.** The two "stable" states are stable in the *wrong*
direction or at drift magnitude: `LONG_REJECT` is negative in both arms, meaning
the predicted reversal **failed** — price continued upward after a rejected
upside breakout; `SHORT_REJECT` is positive in both arms at or below long drift.

---

## J. Unconditional baseline (A) — the drift that explains it

| Cell | uncond long-side | uncond short-side | q(pred long) | side-matched |
|---|---|---|---|---|
| TRAIN@1h | +0.0292 | −0.0292 | 0.512 | +0.0007 |
| TRAIN@2h | +0.0568 | −0.0568 | 0.512 | +0.0014 |
| TRAIN@4h | +0.1049 | −0.1049 | 0.512 | +0.0026 |
| DEV@1h | +0.0589 | −0.0589 | 0.549 | +0.0058 |
| DEV@2h | +0.1200 | −0.1200 | 0.549 | +0.0119 |
| DEV@4h | **+0.2358** | −0.2358 | 0.549 | +0.0233 |

The side-matched figure is near zero because the four states split roughly evenly
between predicted-long and predicted-short — which is exactly why the
**per-state** comparison in §H, not the side-matched aggregate, is the one that
exposes the drift.

Against the unconditional side means, **nothing exceeds drift**:
`DEV LONG_ACCEPT@4h` is **+0.2285** against long drift of **+0.2358** — slightly
*below* it. `DEV SHORT_REJECT@4h` is +0.080 against +0.236 — well below.
`DEV LONG_REJECT@4h` is −0.500 against short drift of −0.236 — i.e. **twice as
bad as simply being short**.

## K. Displacement baseline (B) and the area-interaction control (C)

| Cell | **B** all break events (displacement dir.) | **C** big displacement, NO area interaction | break − no-break |
|---|---|---|---|
| TRAIN@1h | −0.0068 (t −0.20) | **−0.0839 (t −2.69)** | +0.0771 (t +1.66) |
| TRAIN@2h | −0.0019 (t −0.04) | **−0.1158 (t −2.34)** | +0.1139 (t +1.57) |
| TRAIN@4h | +0.0725 (t +0.84) | −0.0512 (t −0.63) | +0.1237 (t +1.05) |
| DEV@1h | +0.0743 (t +1.54) | −0.0474 (t −1.08) | +0.1217 (t +1.87) |
| DEV@2h | +0.0771 (t +1.06) | −0.0243 (t −0.36) | +0.1014 (t +1.02) |
| DEV@4h | +0.1419 (t +1.30) | +0.0754 (t +0.66) | +0.0665 (t +0.42) |

**Baseline B is null**: a large displacement that breaks a prior boundary does not
continue, max |t| 1.54. So the population this hypothesis selects has no
directional tendency of its own before the classification is applied.

The **break − no-break** contrast is positive in all six cells (+0.07 to +0.12)
but never reaches |t| 1.9. The area-interaction requirement does something at the
margin; it is not statistically distinguishable from nothing.

## L. Displacement-matched controls (D, E) — the decisive test

The hypothesis's core claim is that acceptance continues *more* than rejection,
i.e. the ACCEPT − REJECT contrast in the **displacement direction** should be
**positive**.

| Cell | ACCEPT − REJECT, raw | **D** matched magnitude | **E** matched recent displacement |
|---|---|---|---|
| TRAIN@1h | +0.0500 (t +0.71) | **+0.0397 (t +0.56)** | **+0.0398 (t +0.55)** |
| TRAIN@2h | −0.0689 (t −0.67) | **−0.1000 (t −0.95)** | **−0.0744 (t −0.72)** |
| TRAIN@4h | −0.1618 (t −1.03) | **−0.2131 (t −1.30)** | **−0.1570 (t −1.00)** |
| DEV@1h | −0.1475 (t −1.50) | **−0.1317 (t −1.32)** | **−0.1367 (t −1.38)** |
| DEV@2h | −0.0056 (t −0.04) | **+0.0239 (t +0.17)** | **−0.0030 (t −0.02)** |
| DEV@4h | −0.2031 (t −1.03) | **−0.1455 (t −0.73)** | **−0.2019 (t −1.02)** |

**Maximum |t| is 1.50 raw, 1.32 under D, 1.38 under E. Every interval straddles
zero, and the sign is NEGATIVE — the opposite of the prediction — in 4 of 6 raw
cells, 4 of 6 under D and 5 of 6 under E.**

Acceptance does not continue more than rejection. If anything the point estimates
say the reverse, and matching on displacement magnitude or on the preceding move
does not rescue it. Rejection criteria 2 and 3 are met.

### A degenerate control, found and corrected — disclosed

Baseline D as first implemented stratified events into quintiles of
`displacement_size` computed over the **whole TRAIN population**. That is
degenerate here: every event satisfies `displacement_size ≥ TAU`, and **`TAU` *is*
the 80th-percentile cut**, so all 2,071 TRAIN events landed in one bin
(`n_strata_used = 1`) and the "matched" control reproduced the unstratified
contrast exactly — it performed no matching at all.

The cut points were changed to the quintiles of `displacement_size` **among TRAIN
events**, which is the population being stratified. They remain **TRAIN-only and
frozen before DEV**. Both sets are recorded in the results file. This is the
repair of a control that did nothing, not a re-specification of the hypothesis —
and the corrected control is *less* favourable to the hypothesis than the
degenerate one at 2h and 4h.

The matching matters for a measurable reason: **acceptance rate rises with
displacement magnitude**, from **48%** in the smallest event quintile (198 accept
/ 216 reject) to **64%** in the largest (266 / 149). Acceptance and displacement
size are confounded, so an unmatched comparison partly measures magnitude.

---

## M. Analytic and bootstrap inference

Three estimators, with the Phase 1 distinction maintained: analytic
non-overlapping (headline); moving-block bootstrap (blocks 96 and 480 M15 bars,
4,000 replicates, seed 20261005, **observation-weighted within blocks** — not the
Phase 1 failure mode); and the equal-block mean, carried **only** as the input to
the sign-disagreement check.

| TRAIN cell | analytic t | bootstrap t (96) | bootstrap 95% CI |
|---|---|---|---|
| LONG_ACCEPT@1h | −0.86 | −0.88 | [−0.1815, +0.0676] |
| LONG_ACCEPT@2h | −0.56 | −0.54 | [−0.2421, +0.1294] |
| **LONG_ACCEPT@4h** | **−0.02** | **+0.49** | [−0.2105, +0.3433] |
| LONG_REJECT@1h | −0.38 | −0.41 | [−0.1787, +0.1127] |
| LONG_REJECT@2h | −0.79 | −0.48 | [−0.2722, +0.1466] |
| **LONG_REJECT@4h** | **−1.97** | **−0.81** | [−0.4736, +0.1810] |
| SHORT_ACCEPT@1h | +1.62 | +1.51 | [−0.0279, +0.2228] |
| SHORT_ACCEPT@2h | +0.17 | +0.17 | [−0.1604, +0.2061] |
| SHORT_ACCEPT@4h | −0.30 | −0.02 | [−0.3124, +0.3068] |
| SHORT_REJECT@1h | +1.43 | +1.43 | [−0.0373, +0.2510] |
| SHORT_REJECT@2h | +0.26 | +0.56 | [−0.1355, +0.2522] |
| SHORT_REJECT@4h | +0.29 | +0.35 | [−0.2580, +0.3643] |

**Every bootstrap interval contains zero.** Two cells matter:

- **`LONG_REJECT@4h`, the largest TRAIN |t|, falls from −1.97 to −0.81** under the
  bootstrap — it loses more than half its t once block dependence is carried.
- **`LONG_ACCEPT@4h` changes sign** between estimators (−0.02 → +0.49).

**`ESTIMATOR_SIGN_DISAGREEMENT`: 3 of 36 cells** — `TRAIN|LONG_ACCEPT@4h`,
`TRAIN|SHORT_ACCEPT@2h`, `POOLED|LONG_ACCEPT@4h`. Per §11 the result is flagged
and the favourable estimator is **not** selected. Rejection criterion 5 is met.

## N. Multiple-testing correction

TRAIN t-values: LONG_ACCEPT −0.859, −0.561, −0.017; LONG_REJECT −0.385, −0.790,
**−1.973**; SHORT_ACCEPT +1.616, +0.172, −0.300; SHORT_REJECT +1.432, +0.258,
+0.294.

| | |
|---|---|
| Max \|t\| | **1.973** |
| **Observed \|t\| ≥ 2** | **0** |
| Expected \|t\| ≥ 2 under null (12 / 30 / 138) | 0.55 / 1.37 / 6.28 |
| Bonferroni \|t\| (12 / 30 / 138) | 2.865 / **3.144** / 3.566 |
| **Survivors, all three** | **0** |
| Benjamini–Hochberg, all three | **0** |

The strongest cell reaches **63%** of the promotion threshold. Zero exceedances at
|t| ≥ 2 where chance alone predicts 1.37 across the accumulated 30.

## O–P. Power and execution-cost screen

Round-turn = **1 × spread**, measured median **$0.33** → **0.158 ATR** TRAIN,
**0.093 ATR** DEV.

| TRAIN cell | non-ov n | se | **MDE corrected** | cost | gross | **net** | detectable? |
|---|---|---|---|---|---|---|---|
| LONG_ACCEPT@1h | 624 | 0.0651 | 0.205 | 0.158 | −0.0559 | −0.2139 | **no** |
| LONG_ACCEPT@2h | 569 | 0.0988 | 0.310 | 0.158 | −0.0554 | −0.2134 | no |
| LONG_ACCEPT@4h | 502 | 0.1530 | 0.481 | 0.158 | −0.0025 | −0.1605 | no |
| LONG_REJECT@1h | 470 | 0.0796 | 0.250 | 0.158 | −0.0306 | −0.1886 | no |
| LONG_REJECT@2h | 449 | 0.1123 | 0.353 | 0.158 | −0.0887 | −0.2467 | no |
| LONG_REJECT@4h | 414 | 0.1629 | 0.512 | 0.158 | −0.3215 | −0.4795 | no |
| SHORT_ACCEPT@1h | 540 | 0.0602 | **0.189** | 0.158 | +0.0972 | −0.0608 | no |
| SHORT_ACCEPT@2h | 492 | 0.0851 | 0.268 | 0.158 | +0.0146 | −0.1434 | no |
| SHORT_ACCEPT@4h | 448 | 0.1506 | 0.473 | 0.158 | −0.0452 | −0.2032 | no |
| SHORT_REJECT@1h | 437 | 0.0736 | 0.231 | 0.158 | +0.1054 | −0.0526 | no |
| SHORT_REJECT@2h | 424 | 0.1057 | 0.332 | 0.158 | +0.0272 | −0.1308 | no |
| SHORT_REJECT@4h | 399 | 0.1511 | 0.475 | 0.158 | +0.0444 | −0.1136 | no |

**Not one of the 24 TRAIN+DEV cells is powered to resolve a cost-sized effect.**
The closest is `SHORT_ACCEPT@1h` at 0.189 against 0.158 — short by 20%. **Every
TRAIN cell is net-negative after cost**, including the three with positive gross
means.

Every null in §H is therefore a **bound**, not an absence: TRAIN bounds run
**0.189–0.512 ATR**, DEV bounds **0.243–0.667 ATR**.

> These net figures are **not expected returns** and must not be read as such for
> cells that failed the statistical screen. `RESEARCH_TO_STRATEGY_GATE.md` §9.1
> defers the cost screen until after the statistical screen for exactly that
> reason; this authorisation requires it as output P, so it is reported with the
> caveat rather than omitted — the same resolution recorded in H03.

## Q. H1 regime robustness

| TRAIN cell | BULLISH | NEUTRAL | BEARISH |
|---|---|---|---|
| LONG_ACCEPT@1h | −0.054 (359) | −0.050 (178) | −0.076 (87) |
| LONG_ACCEPT@4h | −0.001 (295) | +0.121 (162) | −0.123 (76) |
| LONG_REJECT@4h | −0.242 (193) | −0.178 (167) | **−0.851 (66)** |
| SHORT_ACCEPT@1h | **−0.305 (45)** | +0.113 (155) | +0.143 (340) |
| SHORT_ACCEPT@4h | **−0.637 (43)** | −0.178 (140) | +0.139 (283) |
| SHORT_REJECT@4h | +0.215 (70) | +0.309 (155) | **−0.229 (181)** |

| DEV cell | BULLISH | NEUTRAL | BEARISH |
|---|---|---|---|
| LONG_ACCEPT@4h | +0.481 (188) | **−0.352 (90)** | +0.400 (27) |
| LONG_REJECT@4h | −0.562 (105) | −0.622 (76) | **+0.018 (37)** |
| SHORT_ACCEPT@4h | −0.500 (11) | −0.021 (70) | −0.250 (126) |
| SHORT_REJECT@4h | +0.284 (44) | −0.063 (73) | +0.144 (76) |

**The states are entangled with regime by construction.** TRAIN `SHORT_ACCEPT` has
**45** bullish events against **340** bearish; DEV `SHORT_ACCEPT` has **11**
bullish. Short displacements occur in falling markets and long displacements in
rising ones, so a state's apparent "directional information" is partly just which
regime it occurs in — which is the same drift finding from a second angle.

Signs reverse across regimes inside a single arm (`TRAIN SHORT_ACCEPT@1h`: −0.305
bullish vs +0.143 bearish) and the whole of `TRAIN LONG_REJECT@4h` (−0.3215) is
carried by **66 bearish events at −0.851**. Cell sizes of 11–359 make these
descriptive only. Rejection criterion 7 is met.

## R. TRAIN → DEV replication

Identical frozen definitions; nothing refit. **5 of 12 signs reverse** (§I).
Magnitude stability is poor: DEV magnitudes are 2–10× TRAIN's at matching cells
(`LONG_REJECT@1h`: −0.031 → −0.352). No cell survives both correction and cost in
either arm. Regime structure differs between arms (§Q).

**TRAIN was null, and DEV was not searched for a rescue.** DEV's three nominally
significant cells are all `LONG_REJECT`, all in the *wrong* direction for the
hypothesis — they say a rejected upside breakout **continues up**, not that it
reverses. Across 24 cells at two-sided α = 0.05, about 1.2 nominal exceedances are
expected; three appeared, all in one state, all contradicting the prediction, and
none survives correction.

## S. Endpoint-coupling audit

**Structural — no shared price point.**

| Side | Reads |
|---|---|
| `prior_high/low` | `high`, `low` of bars e−27…e−4 |
| `disp_size`, `direction` | `close[e]`, `close[e−4]`, `ATR_14[e−1]` |
| `recent_disp` | `close[e−4]`, `close[e−16]`, `ATR_14[e−5]` |
| acceptance | closes of bars e+1…e+4, boundary fixed at e−4 |
| **max feature bar index** | **e+4** |
| label anchor | `open[e+5]` |
| label exit | `close[e+4+h]` |
| **min label price bar index** | **e+5** |

`e+4 < e+5`, and **`open[e+5]` is read by no feature**. SUPPORTED condition 9 is
satisfied — the only one besides condition 1 that is.

**Empirical.** Recomputing the headline with the *coupled* anchor `close[e+w]`
instead of `open[e+w+1]`: **1 of 24 cells changes sign** (`TRAIN|LONG_ACCEPT@4h`,
a cell whose analytic t is −0.02). The clean design was worth having, and it did
not materially alter the conclusion — which is the honest outcome to report for an
audit of something that was built correctly.

### Causal reconstruction — tolerances frozen before the run

| Quantity | Frozen tolerance | Observed | Result |
|---|---|---|---|
| `PRIOR_HIGH`, `PRIOR_LOW` | **exactly 0.0** | **0.0** | PASS |
| `displacement_size` | relative 1e-12 | 4.83e-16 | PASS |
| `recent_disp` | relative 1e-12 | 4.55e-16 | PASS |
| `ATR_14` | relative 1e-12 | 4.80e-16 | PASS |
| direction / break / **acceptance** classification | 0 disagreements | **0 / 0 / 0** | PASS |

60 probes, seed 20261005. The area bounds reconstruct **exactly**; only
ATR-derived quantities show float64-level deviation, as the frozen tolerances
anticipated. **Zero** classification disagreements — including acceptance, the one
that matters most.

> An off-by-one in the prefix-reconstruction slice was found and fixed before the
> run: bars `e−27…e−4` require the slice `[−27:−3]`, not `[−28:−4]`. It was
> verified against the rolling definition rather than assumed, and the assertion
> `len(slice) == AREA_LOOKBACK` now guards it. Had it shipped, the causal control
> would have failed loudly — which is what the control is for.

**Forward-window audits:** 0 of 36 non-disjoint.

---

## Limitations

1. **No cell was powered against cost** (§O). Every null is a bound of
   0.189–0.667 ATR. The rejection rests on the **controls and the sign pattern**,
   not on the underpowered nulls — criteria 2, 3, 6 and 7 are about direction and
   confounding, which low power does not excuse.
2. **One instrument, one broker, one era.** XAUUSD 2022-06 → 2025-09, both arms
   rising, **no multi-year bear market**. The drift that explains §H cannot be
   separated from the sample's trend by this data, and the regime entanglement in
   §Q would look different in a falling market.
3. **One parameterisation only** — `a=24`, `d=4`, `w=4`, 80th-percentile `TAU`,
   ATR(14), three horizons. A different window set is a different hypothesis
   needing its own pre-registration, and it would inherit an accumulated burden
   now standing at **30**.
4. **The full acceptance window always elapses before the clock starts**, by
   declared design, so rejection information is up to three bars stale at the
   anchor. Chosen for comparability between classes; the cost is real.
5. **Baseline D was degenerate as first written** (§L). Corrected, disclosed, and
   the corrected version is less favourable to the hypothesis.
6. **H1 regime cells are 11–359 events** — descriptive only.
7. **No execution realism beyond the spread convention.** The `open[e+5]` anchor
   is executable in principle, but no slippage, fill or queue model is applied,
   because the gate stops before it.

---

## T. Final classification

# HYPOTHESIS 04 — NOT SUPPORTED

The mechanism proposed that holding beyond a prior area forces inventory to cover
in the displacement direction, while a return through the boundary strands
breakout entrants and reverses it. **The classification is real, stable and
reproducible — and it carries no directional information.**

Acceptance happens on **56.2%** of events in TRAIN and **57.0%** in DEV, and its
rate rises monotonically with displacement size, from 48% to 64%. Those are solid
descriptive facts. But acceptance does not continue more than rejection: the
contrast is **negative in 4 of 6 raw cells and 5 of 6 after matching on the
preceding move**, with a maximum |t| of **1.50** — the opposite sign to the
prediction. Zero of 12 declared tests survive at any of the three correction
levels. And in DEV **all four states sit at or below the drift their predicted
direction would earn anyway**, which is the whole of the apparent effect.

The one cell that looks arresting — `DEV LONG_REJECT@1h`, t **−3.25** — points the
**wrong way**: after a failed upside breakout, price continued **up**. That is a
refutation of the rejection→reversal claim, not evidence for it, and it echoes
H02's finding on a differently defined failed breakout.

**Six of seven rejection criteria met. Two of nine SUPPORTED conditions met**
(clean causal definition, no endpoint coupling) — both methodological, neither
evidential.

### Should the hypothesis be closed?

**Closed.** The causal construction was the strongest in this programme: zero
shared price points proved by index enumeration, exact reconstruction of the area
bounds, zero classification disagreements, overlap 1.0–1.2×, and a four-way state
split that still cleared the event-count floor in every cell. The design cannot be
blamed. A better-powered version would measure the same wrong-signed contrast more
precisely.

### A genuinely separate mechanism observed in diagnostics — reported, NOT tested

**Baseline C is the only place in this study where |t| exceeded 2.** Large
displacements that did **not** break a prior area moved *against* the displacement
direction: **−0.0839 (t −2.69)** at TRAIN 1h and **−0.1158 (t −2.34)** at TRAIN
2h.

That is a **mean-reversion** claim about displacement *without* area interaction —
the mirror image of what H04 tested, and a different mechanism. It was produced as
a control, not as a hypothesis; it is one arm only; it has not been corrected for
multiplicity, matched, bootstrapped, replicated in DEV, or cost-screened; and the
DEV counterparts are −0.0474 (t −1.08) and −0.0243 (t −0.36), i.e. much weaker.

Per §18 of the specification and the authorisation's closing instruction, **I am
not converting this diagnostic into a new hypothesis.** It is recorded here as an
observation requiring separate authorisation, and the honest prior is that it is
most likely another instance of what this programme has now found five times: a
nominally interesting control statistic that dissolves under matching and
replication.

**H05 is not begun.** FINAL_OOS was not opened. No DEV tuning, no strategy
designed, no threshold optimised, no alternative parameter tested, no feature
searched. No profitability claim is made or implied.
