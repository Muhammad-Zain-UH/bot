# Hypothesis 01 — COMPRESSION → RANGE BREAKOUT → EXPANSION

## HYPOTHESIS 01 — NOT SUPPORTED

**0 survivors of 3 declared hypotheses** under Bonferroni and under
Benjamini–Hochberg. Maximum |t| in the primary arm was **0.644** against a
corrected threshold of **2.394**. **Zero** cells reached |t| ≥ 2, against 0.137
expected by chance.

Three independent pre-registered diagnostics agree, and each was specified as
evidence *against* before any number existed:

1. **DEV point estimates are negative at all three horizons** (−0.0922, −0.0043,
   −0.0607 ATR), so the hypothesis fails the replication requirement regardless
   of significance.
2. **The event population is indistinguishable from randomly chosen bars.** The
   observed mean sits inside the central mass of the direction-balanced random
   baseline in all six cells, and *below* the random median in four of six.
3. **The drift signature fires decisively.** Returns are positive on the LONG
   side and negative on the SHORT side at **every** horizon in **both** arms. A
   genuine breakout-expansion mechanism is direction-neutral; this shape is
   drift in a sample whose arms rose +33.63% and +44.24%.

And the comparison the hypothesis was built to answer:

4. **Compression adds nothing beyond a directional move.** Against breakouts
   *without* compression, the difference reaches |t| 0.78 at best and **flips
   sign between TRAIN and DEV**.

**FINAL_OOS was not opened.** No strategy was designed. No cost screen was run —
correctly, since nothing survived the statistical gate.

---

## 1. What was frozen, and when

`research/hypothesis_01_compression_breakout.md`, committed at **`44419ef`**. That
commit contains the specification and nothing else — no analysis script, no
panel, no results file, no report. Verified by inspection of git history.

**3 hypotheses** were pre-declared: `E[R_h] > 0` at h ∈ {1h, 2h, 4h}. None was
added after results were inspected. One compression window (12), one buffer
(0.10 ATR), one percentile (20), three horizons. **No alternative was computed.**

### Architectural independence — honoured

Nothing from the frozen historical control was imported or consulted: no
`fast_bias`, `bias_strength`, H1 production bias, CHoCH, sweep, POI, FVG,
production session gate, production entry trigger or production threshold. The
analysis script imports only `dataset_access`, the statistical controls module,
`pandas_ta` and numeric libraries. **The breakout alone determined direction.**

---

## 2. Definitions as executed

One causal ATR throughout: **`A[i] = ATR_14[i-1]`** (Wilder, M15), a function of
bars at or before `i-1` only, used for the compression ratio, the breakout
buffer, the label normaliser and the dollar conversion.

```
range_12[i]       = max(high[i-12:i]) - min(low[i-12:i])        bars i-12 .. i-1
compression_ratio = range_12 / A
compressed        ⟺ compression_ratio <= THETA

LONG  breakout:  close[i] >  max(high[i-12:i]) + 0.10 * A[i]
SHORT breakout:  close[i] <  min(low [i-12:i]) - 0.10 * A[i]

R_h = direction * (close[i+h] - close[i]) / A[i]      h = 4, 8, 16 M15 bars
```

### THETA — TRAIN only, frozen

```
THETA = 2.4579083398        20th percentile of compression_ratio
                            over 49,996 eligible TRAIN bars
```

Recorded to full precision in `hypothesis_01_results.json`. Not recalculated on
DEV, not optimised, no alternative percentile tested.

**Sanity check:** applying THETA to TRAIN selects exactly **20.00%** of bars, as
it must. Applied unchanged to DEV it selects **16.78%** — a consequence of
freezing a TRAIN quantity and applying it to a different volatility era (median
ATR $2.085 versus $3.564). This is reported, not corrected.

### Deduplication, as pre-registered

The armed/fired state machine requiring the series to *leave* compression and
*re-enter* it before another event can fire, state reset per arm, never crossing
the embargo gap. It did real work: **233 further breakout bars in TRAIN and 97 in
DEV were suppressed** as continuations of an event already counted.

---

## 3. Event accounting

| | TRAIN | DEV |
|---|---|---|
| eligible M15 bars | 50,010 | 24,989 |
| compression rate at frozen THETA | **20.00%** | **16.78%** |
| **compression-breakout events** | **1,052** | **531** |
| suppressed by deduplication | 233 | 97 |
| baseline-C events (breakout, no compression) | 1,099 | 550 |
| ambiguous (both boundaries) — excluded | **0** | **0** |
| invalid ATR / incomplete window — excluded | 14 (whole panel) | |

Non-overlapping event counts by horizon, and the resulting overlap ratios:

| | 1h | 2h | 4h |
|---|---|---|---|
| TRAIN raw / non-overlapping | 1,052 / **1,044** | 1,052 / **1,012** | 1,052 / **914** |
| TRAIN overlap ratio | **1.0×** | **1.0×** | **1.2×** |
| DEV raw / non-overlapping | 531 / **524** | 531 / **504** | 530 / **461** |
| DEV overlap ratio | **1.0×** | **1.1×** | **1.1×** |

**Overlap is 1.0–1.2×** — the deduplication rule produces a naturally sparse event
set, so the headline estimator loses almost nothing to non-overlapping selection.
This is far better than the 4–15× overlap of the production-path work, and it
means these nulls are not artefacts of discarded observations. Every cell exceeds
the pre-registered 100-event minimum.

---

## 4. Primary result — `E[R_h] > 0` on non-overlapping events

Headline estimator: **non-overlapping**, observation-weighted, disjoint windows.
Raw statistics accompany it. No unweighted block mean is used as headline
evidence.

| Cell | raw n | non-ov n | overlap | mean (ATR) | median | sd | se | **t** | 95% CI |
|---|---|---|---|---|---|---|---|---|---|
| **TRAIN@1h** | 1,052 | 1,044 | 1.0× | **−0.0300** | −0.1120 | 1.775 | 0.0549 | **−0.55** | [−0.1376, +0.0777] |
| **TRAIN@2h** | 1,052 | 1,012 | 1.0× | **−0.0542** | −0.1403 | 2.675 | 0.0841 | **−0.64** | [−0.2190, +0.1106] |
| **TRAIN@4h** | 1,052 | 914 | 1.2× | **+0.0716** | +0.0226 | 3.568 | 0.1180 | **+0.61** | [−0.1597, +0.3029] |
| **DEV@1h** | 531 | 524 | 1.0× | **−0.0922** | −0.1217 | 1.671 | 0.0730 | **−1.26** | [−0.2353, +0.0508] |
| **DEV@2h** | 531 | 504 | 1.1× | **−0.0043** | −0.0653 | 2.674 | 0.1191 | **−0.04** | [−0.2377, +0.2292] |
| **DEV@4h** | 530 | 461 | 1.1× | **−0.0607** | −0.0201 | 3.556 | 0.1656 | **−0.37** | [−0.3854, +0.2639] |
| POOLED@1h *(descriptive)* | 1,583 | 1,568 | 1.0× | −0.0508 | −0.1189 | 1.740 | 0.0440 | −1.16 | [−0.1369, +0.0354] |
| POOLED@2h *(descriptive)* | 1,583 | 1,516 | 1.0× | −0.0376 | −0.0975 | 2.674 | 0.0687 | −0.55 | [−0.1722, +0.0970] |
| POOLED@4h *(descriptive)* | 1,582 | 1,375 | 1.2× | +0.0272 | +0.0038 | 3.563 | 0.0961 | +0.28 | [−0.1611, +0.2156] |

**Every interval straddles zero.** Five of the six TRAIN/DEV point estimates are
**negative**, and **every median is negative** except TRAIN@4h (+0.0226) and
DEV@4h is −0.0201. The one positive mean, TRAIN@4h, has a **negative counterpart
in DEV** (−0.0607), so it fails replication on its own terms.

The pre-registered requirement was *same sign in TRAIN and DEV, with magnitude
exceeding 1 × round-turn cost*. **No horizon satisfies the sign condition**, and
no point estimate anywhere approaches the cost thresholds (0.158 ATR TRAIN,
0.093 ATR DEV).

---

## 5. Multiple testing

Primary arm **TRAIN**, correction over the declared 3.

| | |
|---|---|
| Pre-declared hypotheses | **3** |
| With a computable t | 3 (none padded) |
| Nominal alpha | 0.05 |
| **Bonferroni threshold** | **\|t\| ≥ 2.394** |
| **Bonferroni survivors** | **0** |
| **Benjamini–Hochberg survivors** | **0** |
| TRAIN t values | −0.545, −0.644, +0.607 |
| Max \|t\| | **0.644** |
| **Observed \|t\| ≥ 2** | **0** |
| Expected \|t\| ≥ 2 under null | 0.137 |

The threshold shown is two-sided, which is conservative for a one-sided
directional claim; the strongest cell reaches **27%** of it, so the choice of
tails changes nothing.

---

## 6. Baseline A — unconditional, side-matched

| Cell | long-side mean | short-side mean | p(LONG) from events | side-matched baseline | n pool | event mean |
|---|---|---|---|---|---|---|
| TRAIN@1h | +0.0289 | −0.0289 | 0.5345 | +0.0020 | 49,992 | −0.0300 |
| TRAIN@2h | +0.0566 | −0.0566 | 0.5395 | +0.0045 | 49,988 | −0.0542 |
| TRAIN@4h | +0.1032 | −0.1032 | 0.5394 | +0.0081 | 49,980 | +0.0716 |
| DEV@1h | +0.0603 | −0.0603 | 0.5668 | +0.0081 | 24,985 | −0.0922 |
| DEV@2h | +0.1211 | −0.1211 | 0.5615 | +0.0149 | 24,981 | −0.0043 |
| DEV@4h | **+0.2350** | −0.2350 | 0.5618 | +0.0291 | 24,973 | −0.0607 |

The two side means are exact negatives by construction; they are both shown to
make that explicit rather than to imply two independent measurements. The
side-matched combination is small (≤ 0.029 ATR) because the near-50/50 LONG/SHORT
event mix cancels most of the drift.

### The long-side column is the whole story

The **unconditional long-side drift** is large and grows with horizon — **+0.2350
ATR at DEV@4h**, with no condition applied at all. Comparing the event side means
from §9 against it:

| Cell | event LONG | uncond. long-side | **LONG excess** | event SHORT | uncond. short-side | **SHORT excess** |
|---|---|---|---|---|---|---|
| TRAIN@1h | +0.0603 | +0.0289 | **+0.031** | −0.1253 | −0.0289 | **−0.096** |
| TRAIN@2h | +0.1205 | +0.0566 | **+0.064** | −0.2702 | −0.0566 | **−0.214** |
| TRAIN@4h | +0.1609 | +0.1032 | **+0.058** | −0.1133 | −0.1032 | **−0.010** |
| DEV@1h | +0.0061 | +0.0603 | **−0.054** | −0.1993 | −0.0603 | **−0.139** |
| DEV@2h | +0.1479 | +0.1211 | **+0.027** | −0.1912 | −0.1211 | **−0.070** |
| DEV@4h | +0.2622 | +0.2350 | **+0.027** | −0.2964 | −0.2350 | **−0.061** |

On the **LONG** side, compression breakouts beat simply holding long for the same
period by **+0.03 to +0.06 ATR** — and in DEV@1h they do **worse** (−0.054). On
the **SHORT** side they are worse than the unconditional short-side return in
**all six** cells.

So the positive LONG means in §9 are very nearly just the drift. Conditioning on
compression and a genuine breakout adds almost nothing to the long side and
actively subtracts on the short side. These are point estimates without intervals
and are offered as interpretation of declared baseline A, not as additional tests.

## 7. Baseline B — direction-balanced random events

2,000 replicates, seed 20261002, drawing the same number of bars with the same
LONG fraction and the same minimum spacing, with direction assigned at random.

| Cell | observed | random mean | random sd | random 95% band | **percentile rank** | p(random ≥ observed) |
|---|---|---|---|---|---|---|
| TRAIN@1h | −0.0300 | +0.0021 | 0.0498 | [−0.0926, +0.1012] | **26.9** | 0.731 |
| TRAIN@2h | −0.0542 | +0.0057 | 0.0712 | [−0.1333, +0.1499] | **19.9** | 0.801 |
| TRAIN@4h | +0.0716 | +0.0088 | 0.1107 | [−0.2029, +0.2210] | **71.5** | 0.285 |
| DEV@1h | −0.0922 | +0.0068 | 0.0661 | [−0.1258, +0.1399] | **6.3** | 0.937 |
| DEV@2h | −0.0043 | +0.0116 | 0.0952 | [−0.1700, +0.1946] | **43.4** | 0.567 |
| DEV@4h | −0.0607 | +0.0260 | 0.1396 | [−0.2303, +0.3021] | **27.1** | 0.730 |

**Every observed mean falls inside the random 95% band.** Percentile ranks span
6.3 to 71.5 — four of six **below** the random median. The one-sided empirical
p-values range from 0.285 to 0.937.

Identifying a compression regime and waiting for a genuine breakout produced
forward returns **indistinguishable from picking bars at random and assigning
sides to match**. This is the cleanest single statement of the result.

---

## 8. Baseline C — the decisive comparison

Compression + breakout **versus breakout without compression**. This isolates the
contribution of *compression* from the contribution of *a directional move beyond
a recent range*. Baseline C's deduplication uses the structural analogue of the
pre-registered machine, with the gate inverted (§13 limitation 4).

| Cell | compression n / mean | no-compression n / mean | diff | **t** | boot t (96) | cross-group overlap |
|---|---|---|---|---|---|---|
| TRAIN@1h | 1,044 / −0.0300 | 1,097 / −0.0336 | +0.0036 | **+0.04** | +0.13 | 33.7% |
| TRAIN@2h | 1,012 / −0.0542 | 1,090 / −0.1138 | +0.0597 | **+0.50** | +0.59 | 54.4% |
| TRAIN@4h | 914 / +0.0716 | 1,035 / −0.0594 | +0.1309 | **+0.78** | +0.69 | 75.2% |
| DEV@1h | 524 / −0.0922 | 550 / +0.0223 | **−0.1145** | **−1.05** | −1.15 | 31.5% |
| DEV@2h | 504 / −0.0043 | 547 / +0.1064 | **−0.1107** | **−0.68** | −0.86 | 55.6% |
| DEV@4h | 461 / −0.0607 | 522 / +0.1206 | **−0.1813** | **−0.81** | −1.18 | 78.5% |

**The difference flips sign between arms** — positive at all three horizons in
TRAIN, negative at all three in DEV — and no |t| exceeds 1.18 under either the
analytic or the block-bootstrap estimator. Cross-group forward-window overlap is
reported per the gate and reaches 78.5%; the bootstrap (blocks of 96 and 480 M15
bars, 4,000 replicates, declared in advance) does not change the picture.

**Compression contributes no detectable information beyond the breakout itself**,
and the sign of its non-significant contribution is not stable across arms.

Baseline C is a declared comparison contributing 0 hypotheses; it could not have
promoted the candidate, and it does not.

---

## 9. The drift diagnostic — pre-registered as evidence against

§12 of the pre-registration stated: *a genuine breakout-expansion mechanism is
direction-neutral — it should be positive on both the long and short side in a
direction-normalised metric. An effect that is positive LONG and negative SHORT
is the signature of drift, and will be reported as drift rather than as support.*

| Cell | LONG n | **LONG mean** | SHORT n | **SHORT mean** |
|---|---|---|---|---|
| TRAIN@1h | 560 | **+0.0603** | 488 | **−0.1253** |
| TRAIN@2h | 550 | **+0.1205** | 480 | **−0.2702** |
| TRAIN@4h | 525 | **+0.1609** | 457 | **−0.1133** |
| DEV@1h | 299 | **+0.0061** | 228 | **−0.1993** |
| DEV@2h | 289 | **+0.1479** | 225 | **−0.1912** |
| DEV@4h | 274 | **+0.2622** | 216 | **−0.2964** |

**Positive long, negative short, in all six cells, in both arms.** The two sides
nearly cancel, which is why the combined means sit near zero.

This is not a breakout-expansion effect. Both arms of the sample rose
substantially (+33.63%, +44.24%), and a long position after any upward move in a
rising market gains while a short position after any downward move loses. The
pattern is **drift**, exactly as pre-declared, and exactly the shape that
defeated the previous architecture's continuation claim.

The symmetry is worth stating plainly: the hypothesis predicted expansion *in the
breakout direction*. What the data show is expansion in **the market's** direction,
which is a different claim and not the one under test.

---

## 10. The endpoint-coupling control

The pre-registration declared that the breakout condition reads `close[i]` while
the label subtracts `close[i]`, and that the coupling's expected direction is
**adverse**. The declared control re-anchors the label at `open[i+1]`, which
appears nowhere in the feature:

| Cell | primary (close[i] anchor) | **control (open[i+1] anchor)** | sign |
|---|---|---|---|
| TRAIN@1h | −0.0300 (t −0.55) | −0.0251 (t −0.46) | same |
| TRAIN@2h | −0.0542 (t −0.64) | −0.0489 (t −0.58) | same |
| TRAIN@4h | +0.0716 (t +0.61) | +0.0773 (t +0.66) | same |
| DEV@1h | −0.0922 (t −1.26) | −0.0739 (t −1.03) | same |
| DEV@2h | −0.0043 (t −0.04) | +0.0155 (t +0.13) | **flip** |
| DEV@4h | −0.0607 (t −0.37) | −0.0399 (t −0.24) | same |

Signs agree in **8 of 9** cells. The single flip, DEV@2h, is between −0.0043 and
+0.0155 with |t| ≤ 0.13 — both indistinguishable from zero.

**The coupling is not driving the result.** The control shifts every estimate
very slightly *upward*, consistent with the declared adverse direction, by far
too little to matter. The conclusion holds under both anchors.

---

## 11. Path diagnostics — diagnostic only

In ATR units, bars `i+1 … i+h`. **No stop or target is derived from these, and
none is selected.**

| Cell | MFE mean | MFE median | MAE mean | MAE median |
|---|---|---|---|---|
| TRAIN@1h | +1.281 | +0.880 | −1.280 | −0.961 |
| TRAIN@2h | +1.869 | +1.280 | −1.876 | −1.341 |
| TRAIN@4h | +2.532 | +1.790 | −2.534 | −1.832 |
| DEV@1h | +1.209 | +0.847 | −1.304 | −0.996 |
| DEV@2h | +1.884 | +1.313 | −1.959 | −1.359 |
| DEV@4h | +2.625 | +1.975 | −2.737 | −1.949 |

**Favourable and adverse excursions are near-identical in magnitude** at every
horizon in both arms — TRAIN@4h is +2.532 against −2.534. In DEV the adverse
excursion is consistently slightly *larger* than the favourable one.

Expansion does occur after a compression breakout: price travels 2.5+ ATR in both
directions within four hours. It is **not directional**. The hypothesis claimed
directional expansion, and this is the mechanism by which it fails — not an
absence of movement, but movement that is symmetric.

---

## 12. Power — what this null does and does not mean

Computed from the actual non-overlapping sample sizes, before interpreting the
null, as pre-registered.

| Cell | non-ov n | se | MDE at 2 SE | **MDE at Bonferroni** | cost (ATR) | cost-sized effect detectable? |
|---|---|---|---|---|---|---|
| **TRAIN@1h** | 1,044 | 0.0549 | 0.110 | **0.132** | 0.158 | **YES** |
| TRAIN@2h | 1,012 | 0.0841 | 0.168 | 0.201 | 0.158 | no |
| TRAIN@4h | 914 | 0.1180 | 0.236 | 0.282 | 0.158 | no |
| DEV@1h | 524 | 0.0730 | 0.146 | 0.175 | 0.093 | no |
| DEV@2h | 504 | 0.1191 | 0.238 | 0.285 | 0.093 | no |
| DEV@4h | 461 | 0.1656 | 0.331 | 0.397 | 0.093 | no |

**Only TRAIN@1h was powered to detect a cost-sized effect**, and its point
estimate is **negative** (−0.0300), with the upper CI bound at +0.0777 — below
the 0.158 ATR cost. That cell is a genuinely informative null: *there is no
1-hour effect large enough to pay the spread.*

**The other five cells are underpowered relative to cost**, and their nulls must
be read as bounds, not absences:

- TRAIN@2h: no effect larger than **0.201 ATR**
- TRAIN@4h: no effect larger than **0.282 ATR**
- DEV@1h / @2h / @4h: no effect larger than **0.175 / 0.285 / 0.397 ATR**

This is stated plainly because it is the honest limit of the test. The
classification is nevertheless NOT SUPPORTED rather than INCONCLUSIVE, because
the decision rule's INCONCLUSIVE branch requires a **positive point estimate**
with insufficient power, and what the data show instead is five of six estimates
negative, DEV negative at every horizon, indistinguishability from random events,
and a drift signature in all six cells. Low power did not prevent a conclusion
here; the evidence points against the hypothesis on four independent
pre-registered criteria, not merely failing to point for it.

---

## 13. Controls

| Control | Result |
|---|---|
| **Causal reconstruction (prefix rebuild)** | max deviation **6.66e-16** over 40 probed events |
| — `range_high` / `range_low` | **exactly 0.0** |
| — `A[i] = ATR_14[i-1]` | 8.88e-16 absolute, **3.5e-16 relative** |
| **Forward-window audit** | **0 of 6** cells non-disjoint |
| **Estimator sign-disagreement** | **2 cells**: DEV@2h, DEV@4h |
| **Unweighted block means as headline** | never used |
| **FINAL_OOS opened** | **No** |
| **Panel truncation** | asserted at `2025-09-02 14:15` = DEV boundary |
| **Alternative hypotheses tested** | **none** — 1 window, 1 buffer, 1 percentile, 3 declared horizons |

Four notes, each a place where I am not claiming more than was achieved:

1. **The prefix rebuild was not *exactly* 0.0, as the pre-registration demanded.**
   It was 6.66e-16. The window quantities (`range_high`, `range_low`) matched
   exactly; the entire deviation comes from the Wilder ATR, whose EWM recursion
   accumulates floating-point error differently when the series is sliced. At
   3.5e-16 relative on ATR values near 2.5, this is one double-precision ulp and
   cannot carry information. But the pre-declared standard was "exactly 0.0", and
   it was met for two of three quantities, not three.
2. **`ESTIMATOR_SIGN_DISAGREEMENT` on DEV@2h and DEV@4h** is recorded, not
   suppressed. Neither is a promoting cell — both headline estimates are negative
   and non-significant — so no investigation gates a promotion. The flags are
   listed so the base rate stays visible: 2 of 6 primary cells.
3. **Baseline C's deduplication required a reading.** The pre-registration said
   "the same deduplication machine" without specifying how a
   leave-and-re-enter rule applies when the gate is inverted. I used the
   structural analogue — the series must leave the *non-compressed* regime and
   re-enter it — and recorded that choice here rather than trying both and
   reporting the better one. Baseline C contributes 0 hypotheses and cannot
   promote the candidate, so the reading cannot change the verdict.
4. **The random baseline's rejection test was reimplemented, not redefined.** The
   pre-registered rule `all(|cand − c| ≥ h)` was evaluated via a blocked-position
   array instead of a pairwise scan: identical rule, identical draw order,
   identical seed, O(1) instead of O(n). The original form did not finish in
   reasonable time at ~1,000 draws per replicate.

---

## 14. Cost screen — NOT run

**Correctly not run.** The pre-registration gates the cost screen on the gross
hypothesis surviving the statistical test, and it did not. Reporting a cost table
on a null invites reading it as though the effect were real.

Had it run, the convention was fixed in advance: round turn = **1 × spread**,
measured median **$0.33**, with slippage at 0, 0.25, 0.50 and 1.00 × spread. For
scale only: **0.158 ATR** in TRAIN, **0.093 ATR** in DEV. No point estimate in §4
reaches either figure.

## 15. Temporal stability and H1 regime context — NOT run

Both are reserved by the pre-registration for candidates surviving the primary
screen. None did. Running them anyway would be searching for a favourable subset,
which §14 and §15 of the pre-registration prohibit.

---

## 16. Limitations

1. **Power, as in §12.** Only TRAIN@1h was sensitive below the cost threshold.
   Five cells bound the effect at 0.175–0.397 ATR rather than excluding it. A
   larger effect at 2h or 4h would have been seen; a cost-sized one at 4h would
   not.
2. **One instrument, one broker, one era.** XAUUSD, 2022-06 → 2025-09. Both arms
   rose. There is **no multi-year bear market** in the sample, so the drift
   finding in §9 cannot be separated from the sample's upward trend by this data.
   A falling-market sample could in principle show the mirror image.
3. **The hypothesis tested one parameterisation.** 12-bar window, 20th percentile,
   0.10 ATR buffer, three horizons. A different compression definition is a
   different hypothesis requiring its own pre-registration — and per the
   Research-to-Strategy Gate it would inherit the multiple-testing burden of this
   attempt. **No alternative was tried here**, and the absence of an effect at
   this parameterisation is not evidence about others.
4. **Baseline C reading**, as in §13 note 3.
5. **The prefix-rebuild deviation**, as in §13 note 1.
6. **M15 close as the decision point.** `close[i]` is not tradable once bar `i`
   has closed. The `open[i+1]` control in §10 is the executable anchor and gives
   the same answer, but neither includes spread, slippage or fill uncertainty —
   no execution realism work was done, because the gate stops before it.
7. **Direction-normalised returns in a trending sample** make the LONG/SHORT
   split the primary interpretive tool rather than the combined mean. That is why
   §9 carries more weight than §4 here.

---

## 17. Verdict

**HYPOTHESIS 01 — NOT SUPPORTED.**

The economic mechanism proposed concentrated resting inventory just beyond a
compressed range, executed by a genuine breakout, producing directional
expansion. The data show that expansion occurs — 2.5+ ATR of travel within four
hours — but that it is **symmetric**. Favourable and adverse excursions match to
within 0.1%. The directional component is indistinguishable from the sample's
drift, and compression adds nothing measurable beyond the breakout itself.

Stopping here, as the decision rule requires. **FINAL_OOS was not opened.** No
strategy was designed, no threshold optimised, no alternative hypothesis tested,
no feature searched. The hypothesis is **not** mutated in search of a version
that passes; any change to its definitions is a new hypothesis requiring a new
pre-registration.

No profitability claim is made or implied.
