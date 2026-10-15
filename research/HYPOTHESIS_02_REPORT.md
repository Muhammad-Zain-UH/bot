# Hypothesis 02 — FAILED BREAKOUT → RANGE RE-ENTRY → REVERSAL

## HYPOTHESIS 02 — INCONCLUSIVE / UNDERPOWERED

**0 survivors of 3 declared hypotheses** under Bonferroni and Benjamini–Hochberg.
Maximum |t| in the primary arm was **0.459** against a corrected threshold of
**2.394**. **Zero** cells reached |t| ≥ 2, against 0.137 expected.

**No cell in either arm was powered to detect a cost-sized effect.** The minimum
detectable effect at the corrected threshold ranges from **0.169 ATR** (TRAIN@1h,
against a 0.158 cost) to **0.530 ATR** (DEV@4h, against a 0.093 cost). The
pre-registration reserves the INCONCLUSIVE classification for exactly this case,
and §12 of it forbids claiming that such a null excludes effects below the
measured sensitivity.

**INCONCLUSIVE here means "this test could not decide", not "promising."** Two
pre-registered criteria for evidence *against* the hypothesis are met, and they
are the two that matter most:

| | |
|---|---|
| **The incremental claim is NOT SUPPORTED.** Against breakouts that did *not* fail, re-entry adds nothing: max \|t\| **0.81**, and the difference **flips sign between arms** at 1h and 4h. | §8 |
| **The effect is one-sided.** Reversal-LONG is positive in **all six** cells and reversal-SHORT negative in **all six**. A trapped-inventory mechanism is direction-neutral; this is the drift signature, pre-declared as refutation. | §9 |

What the hypothesis got right, and which distinguishes it from Hypothesis 01:
**TRAIN and DEV agree in sign at all three horizons** (+/+ at 1h, +/+ at 2h, −/−
at 4h), so the §21 "TRAIN positive, DEV negative" rejection does not apply. But
the magnitudes — **+0.0196 and +0.0485 ATR** in TRAIN — are a fifth to a third of
the round-turn cost, against standard errors three times larger than the
estimates themselves.

**FINAL_OOS was not opened.** H1 was not used. No cost screen, temporal or regime
analysis was run — all are reserved for survivors. No strategy was designed.

---

## 1. What was frozen, and when

`research/hypothesis_02_failed_breakout.md`, committed at **`9c59e7b`**. That
commit contains the specification and nothing else — verified by git inspection.

**3 hypotheses** pre-declared: `E[R_h] > 0` at h ∈ {1h, 2h, 4h}. One compression
window (12), one percentile (20), one buffer (0.10 ATR), one failure window
(4 bars), three horizons. **No alternative was computed.** Exactly one hypothesis
was tested.

### Architectural independence

No production module is imported. The script's imports are stdlib, numpy, pandas,
pandas_ta, `dataset_access`, the statistical controls module, and the Hypothesis
01 module (for the inherited compression definition). No `fast_bias`,
`bias_strength`, H1 production bias, CHoCH, production sweep, POI, FVG,
production session gate or production entry trigger. **The breakout established
the initial direction; the reversal direction is its negation.**

### THETA reproduced bit-for-bit

The compression definition was **imported from the Hypothesis 01 module rather
than retyped**, so "the exact frozen definition" is literally true and cannot
drift. THETA was recomputed from TRAIN and compared with H01's committed value:

```
recomputed   2.4579083397631636
H01 committed 2.4579083397631636      relative difference 0.00e+00
```

**Bit-identical.** See §13 note 1 for a transcription error this check caught.

---

## 2. Definitions as executed

Two distinct causal ATR instances, declared in advance so they could not be
silently interchanged. Both are Wilder ATR(14) on M15, and both are the same
shifted array evaluated at different anchors:

```
A[k] = ATR_14[k-1]

A_i = A[i]   at the initial breakout bar   -> compression ratio, breakout buffer
A_j = A[j]   at the re-entry bar           -> label normaliser
```

```
range_12[i]          = max(high[i-12:i]) - min(low[i-12:i])      bars i-12 .. i-1
compression_ratio[i] = range_12[i] / A_i          compressed ⟺ ratio <= THETA

LONG  breakout:  close[i] >  range_high[i] + 0.10 * A_i
SHORT breakout:  close[i] <  range_low[i]  - 0.10 * A_i

failed breakout: first j in {i+1, i+2, i+3, i+4} with
                 close[j] <= range_high[i]   (initial LONG)
                 close[j] >= range_low[i]    (initial SHORT)

R_h = (-d) * (close[j+h] - close[j]) / A_j        h = 4, 8, 16 M15 bars
```

The failure classification uses only `close[j]` and the range from bars
`i-12 … i-1`. **It is fully knowable at the close of bar `j`.** No future
maximum, minimum or excursion enters it, and no ambiguity was resolved with
future data.

---

## 3. Event accounting

| | TRAIN | DEV |
|---|---|---|
| eligible M15 bars | 50,010 | 24,989 |
| compression rate at frozen THETA | 20.00% | 16.78% |
| **initial breakouts** | **1,052** | **531** |
| **→ FAILED (re-entered within 4 bars)** | **574** | **283** |
| **→ SUCCESSFUL (no re-entry)** | **478** | **248** |
| **failure rate** | **54.56%** | **53.30%** |
| suppressed by deduplication | 233 | 97 |
| failure window outside arm — excluded | 0 | 0 |
| invalid ATR — excluded | 0 | 0 |
| ambiguous (both boundaries) — excluded | **0** | **0** |

The initial-breakout counts reproduce Hypothesis 01's exactly (1,052 / 531), as
they must — the compression and breakout definitions are the imported ones. The
split into failed and successful is new, and the two populations are **disjoint
and jointly exhaustive** by construction: the episode is consumed whether or not
the breakout failed. That is what makes baseline C a clean contrast.

**Roughly 54% of compression breakouts re-entered the range within four bars** in
both arms — a stable descriptive fact across two independent periods.

Non-overlapping counts and overlap ratios:

| | 1h | 2h | 4h |
|---|---|---|---|
| TRAIN raw / non-overlapping | 574 / **574** | 574 / **553** | 574 / **516** |
| TRAIN overlap ratio | **1.0×** | **1.0×** | **1.1×** |
| DEV raw / non-overlapping | 283 / **283** | 283 / **273** | 282 / **257** |
| DEV overlap ratio | **1.0×** | **1.0×** | **1.1×** |

Overlap is 1.0–1.1×, so the headline estimator discards almost nothing. All six
cells exceed the pre-registered 100-event minimum. The nulls here are **not**
artefacts of discarded observations — they are small-sample nulls.

---

## 4. Primary result — `E[R_h] > 0` in the reversal direction

Headline: **non-overlapping** events, observation-weighted, disjoint windows.

| Cell | raw n | non-ov n | overlap | mean (ATR) | median | sd | se | **t** | 95% CI |
|---|---|---|---|---|---|---|---|---|---|
| **TRAIN@1h** | 574 | 574 | 1.0× | **+0.0196** | −0.0107 | 1.692 | 0.0706 | **+0.28** | [−0.1188, +0.1580] |
| **TRAIN@2h** | 574 | 553 | 1.0× | **+0.0485** | +0.0075 | 2.486 | 0.1057 | **+0.46** | [−0.1587, +0.2557] |
| **TRAIN@4h** | 574 | 516 | 1.1× | **−0.0500** | −0.0372 | 3.418 | 0.1505 | **−0.33** | [−0.3449, +0.2449] |
| **DEV@1h** | 283 | 283 | 1.0× | **+0.0139** | −0.0273 | 1.881 | 0.1118 | **+0.12** | [−0.2052, +0.2330] |
| **DEV@2h** | 283 | 273 | 1.0× | **+0.0272** | +0.0916 | 2.663 | 0.1612 | **+0.17** | [−0.2887, +0.3431] |
| **DEV@4h** | 282 | 257 | 1.1× | **−0.0365** | +0.0232 | 3.549 | 0.2214 | **−0.16** | [−0.4703, +0.3974] |
| POOLED@1h *(descriptive)* | 857 | 857 | 1.0× | +0.0177 | −0.0111 | 1.756 | 0.0600 | +0.30 | [−0.0998, +0.1353] |
| POOLED@2h *(descriptive)* | 857 | 826 | 1.0× | +0.0415 | +0.0407 | 2.545 | 0.0885 | +0.47 | [−0.1321, +0.2150] |
| POOLED@4h *(descriptive)* | 856 | 773 | 1.1× | −0.0455 | −0.0243 | 3.460 | 0.1244 | −0.37 | [−0.2894, +0.1984] |

**Every interval straddles zero.** The standard error exceeds the point estimate
by a factor of 2 to 9 in every cell.

**TRAIN and DEV agree in sign at all three horizons** — positive at 1h and 2h,
negative at 4h. This is the one structural respect in which Hypothesis 02
outperforms Hypothesis 01, where DEV was negative at every horizon.

Against the pre-registered qualification test of §15:

| Requirement | Result |
|---|---|
| 1. same directional sign in both arms | **MET** at all three horizons |
| 2. magnitude exceeding 1 × round-turn cost | **FAILED** — best is +0.0485 vs 0.158 ATR (TRAIN), +0.0272 vs 0.093 (DEV) |
| 3. statistical support | **FAILED** — 0 survivors, max \|t\| 0.459 |

---

## 5. Multiple testing

| | |
|---|---|
| Pre-declared hypotheses | **3** |
| With a computable t | 3 (none padded) |
| Nominal alpha | 0.05 |
| **Bonferroni threshold** | **\|t\| ≥ 2.394** |
| **Bonferroni survivors** | **0** |
| **Benjamini–Hochberg survivors** | **0** |
| TRAIN t values | +0.278, +0.459, −0.333 |
| Max \|t\| | **0.459** |
| **Observed \|t\| ≥ 2** | **0** |
| Expected \|t\| ≥ 2 under null | 0.137 |

The strongest cell reaches **19%** of the corrected threshold.

---

## 6. Baseline A — unconditional, side-matched in the reversal direction

| Cell | long-side | short-side | q(reversal LONG) | **side-matched baseline** | event mean |
|---|---|---|---|---|---|
| TRAIN@1h | +0.0289 | −0.0289 | 0.465 | **−0.0020** | +0.0196 |
| TRAIN@2h | +0.0566 | −0.0566 | 0.458 | **−0.0048** | +0.0485 |
| TRAIN@4h | +0.1032 | −0.1032 | 0.459 | **−0.0084** | −0.0500 |
| DEV@1h | +0.0603 | −0.0603 | 0.413 | **−0.0104** | +0.0139 |
| DEV@2h | +0.1211 | −0.1211 | 0.425 | **−0.0182** | +0.0272 |
| DEV@4h | +0.2350 | −0.2350 | 0.432 | **−0.0320** | −0.0365 |

As declared in advance, **drift is adverse to this hypothesis**: the reversal
population is 54–59% short (q(LONG) 0.41–0.47), so the side-matched unconditional
baseline is **negative** in every cell. The event means at 1h and 2h therefore do
exceed baseline A — by +0.022 to +0.053 ATR, all far inside the noise.

This is the opposite situation to Hypothesis 01, where drift flattered the
measured effect. Here it penalises it, which is why §9 rather than §4 carries the
interpretive weight.

---

## 7. Baseline B — breakouts that did NOT fail

Anchored at bar `i+4`, the first bar at which non-failure is knowable, with
normaliser `ATR[i+3]`, labelled in the **same reversal direction** — so both
populations are anchored where their classification became known and are directly
comparable.

| Cell | non-ov n | mean (ATR) |
|---|---|---|
| TRAIN@1h | 477 | +0.0353 |
| TRAIN@2h | 472 | +0.0116 |
| TRAIN@4h | 455 | −0.1207 |
| DEV@1h | 246 | −0.1235 |
| DEV@2h | 245 | −0.0517 |
| DEV@4h | 234 | +0.0463 |

---

## 8. Baseline C — the incremental contrast, and the decisive comparison

The question the hypothesis exists to answer: **does range re-entry contain
information beyond simply observing a breakout?**

| Cell | failed n / mean | successful n / mean | **diff** | se | **t** | boot t (96) | 95% CI | x-overlap |
|---|---|---|---|---|---|---|---|---|
| TRAIN@1h | 574 / +0.0196 | 477 / +0.0353 | **−0.0157** | 0.1043 | **−0.15** | −0.16 | [−0.2201, +0.1887] | 0.17% |
| TRAIN@2h | 553 / +0.0485 | 472 / +0.0116 | **+0.0369** | 0.1467 | **+0.25** | +0.28 | [−0.2507, +0.3246] | 1.81% |
| TRAIN@4h | 516 / −0.0500 | 455 / −0.1207 | **+0.0707** | 0.2031 | **+0.35** | +0.26 | [−0.3273, +0.4687] | 12.60% |
| DEV@1h | 283 / +0.0139 | 246 / −0.1235 | **+0.1374** | 0.1687 | **+0.81** | +0.88 | [−0.1932, +0.4680] | 1.06% |
| DEV@2h | 273 / +0.0272 | 245 / −0.0517 | **+0.0789** | 0.2352 | **+0.34** | +0.32 | [−0.3822, +0.5400] | 4.40% |
| DEV@4h | 257 / −0.0365 | 234 / +0.0463 | **−0.0827** | 0.3143 | **−0.26** | −0.05 | [−0.6987, +0.5333] | 12.45% |

**The incremental claim is NOT SUPPORTED.** Maximum |t| is **0.81** (DEV@1h), the
difference **flips sign between arms** at 1h (−0.0157 TRAIN, +0.1374 DEV) and at
4h (+0.0707 TRAIN, −0.0827 DEV), and every interval straddles zero by a wide
margin.

Cross-group forward-window overlap is **0.17%–12.6%** — very low, because failed
and successful breakouts are temporally separated by construction. The analytic
pooled standard error is therefore nearly valid here, and the block bootstrap
(blocks of 96 and 480 M15 bars, 4,000 replicates, declared in advance) agrees
closely with it in every cell. This is a cleaner two-sample comparison than
anything in the production-path work, where cross-group overlap reached 99.97%.

Per the binding interpretive rule in §11 of the pre-registration: because the
failed population is not distinguishable from the successful population, **the
conclusion is that re-entry carries no incremental information, whatever the raw
mean.**

---

## 9. Direction-neutrality — the pre-declared refutation diagnostic

§12 stated in advance: *a genuine trapped-inventory mechanism is
direction-neutral — it should be positive both when reversing a failed upside
breakout and when reversing a failed downside one. An effect present on only one
side is reported as drift or one-sided market asymmetry, not as support.*

| Cell | reversal-LONG n | **LONG mean** | reversal-SHORT n | **SHORT mean** |
|---|---|---|---|---|
| TRAIN@1h | 267 | **+0.1451** | 307 | **−0.0896** |
| TRAIN@2h | 264 | **+0.2393** | 302 | **−0.1038** |
| TRAIN@4h | 254 | **+0.0609** | 292 | **−0.1198** |
| DEV@1h | 117 | **+0.2664** | 166 | **−0.1640** |
| DEV@2h | 117 | **+0.1015** | 162 | **−0.0454** |
| DEV@4h | 113 | **+0.2273** | 153 | **−0.2893** |

**Positive on reversal-LONG in all six cells, negative on reversal-SHORT in all
six.** Reversing a failed *downside* breakout (buying) worked; reversing a failed
*upside* breakout (selling) did not. The two sides largely cancel, which is why
the combined means in §4 sit near zero.

That is the drift signature, for the third time in this programme. But the
diagnostic deserves one more turn of the screw, because baseline A lets the
one-sidedness be measured *against* drift rather than merely attributed to it:

| Cell | rev-LONG | uncond. long-side | **LONG excess** | rev-SHORT | uncond. short-side | **SHORT excess** |
|---|---|---|---|---|---|---|
| TRAIN@1h | +0.1451 | +0.0289 | **+0.116** | −0.0896 | −0.0289 | **−0.061** |
| TRAIN@2h | +0.2393 | +0.0566 | **+0.183** | −0.1038 | −0.0566 | **−0.047** |
| TRAIN@4h | +0.0609 | +0.1032 | **−0.042** | −0.1198 | −0.1032 | **−0.017** |
| DEV@1h | +0.2664 | +0.0603 | **+0.206** | −0.1640 | −0.0603 | **−0.104** |
| DEV@2h | +0.1015 | +0.1211 | **−0.020** | −0.0454 | −0.1211 | **+0.076** |
| DEV@4h | +0.2273 | +0.2350 | **−0.008** | −0.2893 | −0.2350 | **−0.054** |

The LONG excess over unconditional drift is positive in three cells and negative
in three; the SHORT excess is negative in five of six. **There is no stable
excess on either side.** So the one-sidedness is not even a clean "long-only
effect" — it is drift plus noise, with no consistent residual.

These are point estimates without intervals, offered as interpretation of
declared baseline A, not as additional tests.

---

## 10. The endpoint-coupling control

The re-entry condition reads `close[j]` and the label subtracts `close[j]`. The
pre-registration declared this, declared the coupling adverse on both sides, and
declared a control re-anchored at `open[j+1]`, which appears nowhere in the event
definition.

| Cell | primary (close[j] anchor) | **control (open[j+1] anchor)** | sign |
|---|---|---|---|
| TRAIN@1h | +0.0196 (t +0.28) | +0.0190 (t +0.27) | same |
| TRAIN@2h | +0.0485 (t +0.46) | +0.0479 (t +0.45) | same |
| TRAIN@4h | −0.0500 (t −0.33) | −0.0509 (t −0.34) | same |
| DEV@1h | +0.0139 (t +0.12) | +0.0098 (t +0.09) | same |
| DEV@2h | +0.0272 (t +0.17) | +0.0236 (t +0.15) | same |
| DEV@4h | −0.0365 (t −0.16) | −0.0405 (t −0.18) | same |
| POOLED@1h *(descriptive)* | +0.0177 (t +0.30) | +0.0160 (t +0.27) | same |
| POOLED@2h *(descriptive)* | +0.0415 (t +0.47) | +0.0398 (t +0.45) | same |
| POOLED@4h *(descriptive)* | −0.0455 (t −0.37) | −0.0474 (t −0.38) | same |

**Signs agree in all nine cells**, and the largest shift is 0.004 ATR. The
coupling is not driving the result — a cleaner outcome than Hypothesis 01, where
one of nine cells flipped.

---

## 11. Opposite-boundary diagnostics — descriptive, and uninterpretable alone

Over the 16 M15 bars after `j`, whether price touched the opposite range boundary
(`range_low` for a reversal-SHORT, `range_high` for a reversal-LONG):

| | TRAIN (n=574) | DEV (n=282) |
|---|---|---|
| reached within 4 bars | 31.5% | 28.7% |
| reached within 8 bars | 43.2% | 43.6% |
| **reached within 16 bars** | **52.3%** | **57.5%** |
| never within 16 bars | 47.7% | 42.6% |
| time to boundary (median / q25 / q75 bars) | 3.0 / 2.0 / 7.0 | 4.5 / 1.0 / 8.0 |

About half of failed breakouts do traverse the range to the opposite boundary
within four hours, with a median of 3–4.5 bars among those that do.

**This cannot be read as support, and I am not reading it as such.** No baseline
for this statistic was pre-registered, so there is no basis for calling 52% high
or low — the comparable figure for a randomly chosen bar, or for a successful
breakout, was not declared and is therefore not computed here. Adding it now
would be a post-hoc test. The statistic is reported because the pre-registration
required it as descriptive mechanism evidence, and it is left at that.

The directional labels in §4 are the pre-registered test, and they are ~0.

---

## 12. Power — the binding constraint

Computed from the actual non-overlapping event counts, reported before
interpreting the null, as pre-registered.

| Cell | non-ov n | se | MDE at 2 SE | **MDE at Bonferroni** | cost (ATR) | cost-sized effect detectable? |
|---|---|---|---|---|---|---|
| TRAIN@1h | 574 | 0.0706 | 0.141 | **0.169** | 0.158 | **no** (misses by 0.011) |
| TRAIN@2h | 553 | 0.1057 | 0.211 | **0.253** | 0.158 | no |
| TRAIN@4h | 516 | 0.1505 | 0.301 | **0.360** | 0.158 | no |
| DEV@1h | 283 | 0.1118 | 0.224 | **0.268** | 0.093 | no |
| DEV@2h | 273 | 0.1612 | 0.322 | **0.386** | 0.093 | no |
| DEV@4h | 257 | 0.2214 | 0.443 | **0.530** | 0.093 | no |

**Not one cell could detect an effect the size of the round-turn cost.** Every
null in §4 is therefore a bound, not an absence:

- TRAIN: no effect larger than **0.169 / 0.253 / 0.360 ATR** at 1h / 2h / 4h
- DEV: no effect larger than **0.268 / 0.386 / 0.530 ATR**

### What a decisive test would require

Events needed for the corrected MDE to fall to that arm's round-turn cost, at the
observed dispersion:

| Cell | sd | events now | **events needed** | multiple |
|---|---|---|---|---|
| **TRAIN@1h** | 1.692 | 574 | **657** | **1.1×** |
| TRAIN@2h | 2.486 | 553 | 1,419 | 2.6× |
| TRAIN@4h | 3.418 | 516 | 2,682 | 5.2× |
| DEV@1h | 1.881 | 283 | 2,344 | 8.3× |
| DEV@2h | 2.663 | 273 | 4,700 | 17.2× |
| DEV@4h | 3.549 | 257 | 8,345 | 32.5× |

**TRAIN@1h is within 14% of being decisive** — 657 events needed against 574
held. The rest are 2.6× to 32.5× away.

This is a **data-availability limit, not a methodology limit**. At the observed
event rate — 574 failed breakouts in 50,010 TRAIN bars, roughly one per 87 bars —
reaching 1,419 events at 2h would need about 2.6× the TRAIN period, some 5.5
years of additional M15 history. That history exists on the H1 and H4 timeframes
in this dataset but **not on M15**, which begins 2022-06-30. No amount of
re-analysis closes the gap.

---

## 13. Controls

| Control | Frozen tolerance | Observed | Result |
|---|---|---|---|
| `range_high`, `range_low` prefix rebuild | **exactly 0.0** | **0.000e+00** | **PASS** |
| `ATR_14` prefix rebuild | relative **1e-12** | **4.95e-16** | **PASS** |
| `compression_ratio` prefix rebuild | relative **1e-12** | **5.27e-16** | **PASS** |
| `compressed` classification | 0 disagreements | **0** | **PASS** |
| `breakout` classification | 0 disagreements | **0** | **PASS** |
| `re-entry` classification | 0 disagreements | **0** | **PASS** |
| Forward-window audit | disjoint | **0 of 6** non-disjoint | **PASS** |
| `ESTIMATOR_SIGN_DISAGREEMENT` | investigate before promotion | **0 cells** | — |
| Unweighted block means as headline | never | never used | — |
| FINAL_OOS opened | no | **no** | — |
| H1 used | only if survives | **not used** | — |
| Panel truncation | at DEV boundary | asserted at `2025-09-02 14:15` | **PASS** |
| Exactly one hypothesis tested | yes | 1 window, 1 percentile, 1 buffer, 1 failure window, 3 horizons | **PASS** |

**Causal reconstruction PASSES against tolerances frozen before the analysis ran**
(60 probes, seed 20261003). The §14 redesign worked: Hypothesis 01's standard of
"exactly 0.0" was unmeetable for a recursive estimator and produced a disclosed
near-miss; this time the tolerance was derived from the contraction property of
Wilder's recursion — error reaches a steady state of order 14·ε ≈ 3.1e-15 rather
than accumulating as n·ε — and the observed 4.95e-16 sits comfortably inside it.
**Zero** boolean classifications disagreed, so no threshold-tie exclusions were
needed.

### Note 1 — a transcription error this check caught

The pre-registration quotes THETA as `2.4579083398`, which is the true value
rounded to ten decimal places. The script initially compared its full-precision
recomputation against that literal at the frozen 1e-12 relative tolerance **and
the assertion fired**, because the rounding alone is 1.5e-11.

The definition had not drifted. The fix was to source the reference from
**`hypothesis_01_results.json`, the committed artifact, at full precision**,
rather than from a hand-transcribed literal — which is a strictly stronger check
— and to additionally assert that the recomputed value's 10-dp rendering equals
the figure printed in the specification. **The 1e-12 tolerance was not changed.**
Recomputed THETA is bit-identical to H01's committed value.

This is worth recording because the failure mode was mine, not the data's: a
rounded constant in a specification cannot be compared against a full-precision
computation at full-precision tolerance. Future pre-registrations should quote
inherited constants by **artifact reference**, not by printed digits.

---

## 14. Cost screen, temporal robustness, H1 regime — NOT run

All three are reserved by the pre-registration for candidates surviving the
primary statistical gate. None did.

Running them anyway would be searching for a favourable subset of a null, which
§17, §18 and §19 of the pre-registration prohibit. Had the cost screen run, the
convention was fixed in advance: round turn = **1 × spread**, measured median
**$0.33**, slippage at 0, 0.25, 0.50, 1.00 × spread. For scale: **0.158 ATR**
TRAIN, **0.093 ATR** DEV — above every point estimate in §4.

---

## 15. Limitations

1. **Power is the binding constraint, and it is decisive.** No cell could detect
   a cost-sized effect (§12). The nulls are bounds of 0.169–0.530 ATR, not
   absences. This is the primary reason the classification is INCONCLUSIVE rather
   than NOT SUPPORTED.
2. **M15 history begins 2022-06-30**, so the event counts cannot be increased by
   re-analysis. A decisive 2h test needs ≈2.6× the TRAIN period.
3. **Two pre-registered criteria for evidence against are met** — the baseline-C
   null and the one-sidedness. INCONCLUSIVE should not be read as neutral: the
   balance of what evidence exists leans against the hypothesis, and §9 shows
   there is no stable excess over drift on either side.
4. **One instrument, one broker, one era.** XAUUSD, 2022-06 → 2025-09, both arms
   rising, **no multi-year bear market**. The one-sidedness in §9 cannot be
   separated from the sample's upward trend by this data.
5. **The boundary statistic has no pre-registered baseline** (§11) and is
   therefore uninterpretable on its own. It is not evidence either way.
6. **One parameterisation only** — 12-bar window, 20th percentile, 0.10 ATR
   buffer, **4-bar failure window**, three horizons. The 4-bar window is the
   genuinely new free parameter in this hypothesis and it was fixed by
   authorisation, not chosen. A different window is a different hypothesis
   requiring its own pre-registration, and per the Research-to-Strategy Gate it
   would inherit the multiple-testing burden of this attempt. **No alternative
   was tried.**
7. **Both populations are measured at a close that is not tradable.** The
   `open[j+1]` control in §10 is the executable anchor and agrees throughout, but
   neither includes spread, slippage or fill uncertainty — no execution realism
   work was done, because the gate stops before it.
8. **Successful breakouts are anchored at `i+4`** by declared choice. Anchoring
   at `i` would have confounded the contrast with a timing difference of up to
   four bars; the choice was pre-registered, but it is a choice.

---

## 16. Verdict

**HYPOTHESIS 02 — INCONCLUSIVE / UNDERPOWERED.**

The mechanism proposed that breakout entries left offside by a failed breakout
are stopped out as price re-enters the range, producing directional flow toward
the opposite boundary. **The test could not decide it.** No cell was powered to
detect an effect the size of the spread, and the point estimates — +0.0196 and
+0.0485 ATR at 1h and 2h, sign-consistent across TRAIN and DEV — are a fifth to a
third of the round-turn cost with standard errors several times larger.

What can be said: **the hypothesis's distinctive claim is not supported.** Failed
breakouts are statistically indistinguishable from successful ones at every
horizon, with the difference flipping sign between arms. Whatever the raw mean,
re-entry carries no measurable incremental information beyond observing the
breakout. And the only positive signal is one-sided, with no stable excess over
drift on either side.

Stopping here, as the decision rule requires. **FINAL_OOS was not opened.** H1 was
not used. No cost screen, no temporal analysis, no regime analysis, no strategy
design, no threshold optimised, no alternative parameter tested, no feature
searched. The hypothesis is **not** mutated in search of a version that passes.

A future attempt at this mechanism would need more M15 events, not a different
specification — and this dataset cannot supply them.

No profitability claim is made or implied.
