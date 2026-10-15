# Phase 2A–2E — Regime Robustness, Cost Realism, Overlap Control

## EVIDENCE INCONCLUSIVE — DO NOT OPEN FINAL_OOS

Stronger than that, and I want it stated plainly: **the Phase 1 effect does not
exist.** It was an artifact of the estimator I used, not a property of the market.
The Phase 1 headline is **retracted**; that report now carries a retraction banner
with its original text preserved.

FINAL_OOS was never opened. Token unchanged. Dataset, split manifest, production
and `baseline_008` byte-for-byte unchanged.

---

## The error

Phase 1 — and my first pass at Phase 2 — estimated the Q5−Q1 spread as the
difference between **unweighted means of per-block means**, with a block being 16
M15 bars.

**That estimator is biased here**, because the number of Q1/Q5 observations inside
a block is *endogenous to the outcome*: a block in which price ran up contains
mostly Q5 bars. Averaging per-block means without weighting by observation count
therefore up-weights sparse blocks and manufactures separation.

The two estimators disagree catastrophically on TRAIN, `disp_4_lag1`, 4h:

| | Q1 | Q5 | **Spread** |
|---|---|---|---|
| **Raw means** | +0.0642 | +0.1028 | **+0.0386** |
| **Unweighted block means** | +0.5406 | −0.3473 | **−0.8880** |

The block mean of Q1 is **8× its raw mean**. That is the estimator, not the data.

A *paired* within-block version is worse still (spread −1.422, t = −27.66) for a
related reason: Q1 and Q5 bars inside one 16-bar block are a few bars apart and
their 4h forward windows overlap almost entirely, so their difference is dominated
by the within-block path — which is mechanically anti-correlated with their
displacement ranking.

**Corrected estimator used throughout below:** non-overlapping observations only —
a greedy forward scan that accepts a signal then skips the full 16-bar holding
window, so every observation has a disjoint forward window and ordinary standard
errors are valid.

---

## Phase 2A — Long-history H1 regime test

### A feasibility problem, reported rather than worked around

**The M15 structure cannot be tested before 2022-06-30.** M15 history begins there.

| Slice | M15 bars | Status |
|---|---|---|
| 2009–2014 | **0** | **IMPOSSIBLE — no M15 data** |
| 2015–2019 | **0** | **IMPOSSIBLE — no M15 data** |
| 2020–2022 | **0** | **IMPOSSIBLE — no M15 data** |
| 2022–2024 | 49,922 | TESTED |
| 2024–DEV | 24,938 | TESTED |

I did not estimate those three slices. Instead I ran an **H1-native analogue** at a
matched wall-clock horizon (H1 `disp_w_lag1` → 4 H1 bars = 4h, the same 4h as M15 ×
16). It is labelled an analogue throughout: it is **not** the Phase 1 structure and
is evidence only about the same economic hypothesis at coarser resolution.

**6,261 H1 bars fall after the DEV boundary and were excluded** — H1 "context" from
the OOS window would still be an OOS read.

### M15 structure, corrected estimator

| Signal | Arm | n (non-overlap) | Q1 | Q5 | **Spread** | t | **95% CI** |
|---|---|---|---|---|---|---|---|
| `disp_4_lag1` | TRAIN | 3,125 | +0.133 | −0.021 | −0.154 | −0.82 | [−0.521, +0.213] |
| | DEV | 1,561 | +0.299 | +0.119 | −0.180 | −0.77 | [−0.640, +0.281] |
| | **TRAIN+DEV** | 4,686 | +0.189 | +0.031 | **−0.158** | **−1.07** | **[−0.446, +0.130]** |
| `disp_8_lag1` | TRAIN | 3,125 | | | −0.029 | −0.16 | |
| | DEV | 1,561 | | | **+0.178** | +0.77 | |
| | **TRAIN+DEV** | 4,686 | | | **+0.054** | **+0.38** | |

Every confidence interval crosses zero. **`disp_8_lag1` flips sign between TRAIN
and DEV.**

Regime strips (TRAIN+DEV, non-overlapping): `disp_4_lag1` gives H1_BULL −0.068
(t −0.30), H1_NEUTRAL −0.462 (t −0.96), H1_BEAR −0.176 (t −0.77). `disp_8_lag1`
gives +0.093, +0.190, −0.021 — **sign varies by regime**. The Phase 1 claim that
the effect was "present in bull and bear, absent in neutral" does not survive.

### H1-native analogue — 16 years, 23,422 independent observations

| Signal | n | Q1 | Q5 | **Spread** | t | 95% CI |
|---|---|---|---|---|---|---|
| `h1_disp_1_lag1` | 23,422 | +0.0122 | +0.0411 | **+0.0290** | **+0.89** | [−0.035, +0.093] |
| `h1_disp_2_lag1` | 23,422 | +0.0395 | +0.0580 | **+0.0185** | **+0.57** | [−0.045, +0.082] |

| Period | n | Spread | t |
|---|---|---|---|
| 2009–2014 | 7,711 | +0.0354 | +0.60 |
| 2015–2019 | 7,330 | −0.0237 | −0.41 |
| 2020–2022 | 3,674 | +0.0537 | +0.67 |
| 2022–2024 | 3,125 | +0.0963 | +1.08 |
| 2024–DEV | 1,561 | −0.0001 | −0.00 |

| Regime | Spread | t |
|---|---|---|
| H1_BULL | −0.0030 | −0.06 |
| H1_NEUTRAL | +0.1348 | +1.51 |
| H1_BEAR | −0.0049 | −0.09 |

**A clean null across 16 years.** No period or regime reaches |t| = 1.6, and the
pooled sign is **positive** — the opposite of the claimed mean reversion.

Answering 7(a)–(d) directly: **(a)** not present in genuine H1 bear periods
(t −0.09); **(b)** not present in H1 bull periods (t −0.06); **(c)** the neutral
"disappearance" is not a disappearance because there is nothing elsewhere to
disappear from; **(d)** the sign varies across periods and regimes without pattern,
consistent with noise.

---

## Phase 2C — Overlap and dependence

| Signal | Raw tail obs | Non-overlapping | **Ratio** | 4h blocks |
|---|---|---|---|---|
| `disp_4_lag1` | 30,392 | 4,034 | **7.53×** | 4,592 |
| `disp_8_lag1` | 30,491 | 3,821 | **7.98×** | 4,500 |

Raw counts overstate independence by about **7.5×**. Method: greedy forward scan —
accept a signal, then skip the full 16-bar holding window.

**This control is what eliminated the effect.** The apparent significance was
entirely a product of correlated overlapping observations combined with the biased
block estimator.

---

## Phase 2B — Cost realism

### A convention correction

Earlier reports in this programme quoted a round-turn spread cost of **2 × S**.
That double-counted. With ask = mid + S/2 and bid = mid − S/2, a long entered at
ask and exited at bid pays **(ask − bid) = 1 × S**. Round-turn spread cost is
**1 × S = $0.33** at the measured median; both 1× and a conservative 2× bound are
reported.

Spread source: **measured**, 2026-09-24 M1-resolved tick sample, 520,012 ticks —
median **$0.33**, p99 $0.67.

### The diagnostic hypothetical

Non-optimised: extreme-tail signal, direction **opposite** the displacement, fixed
4h hold, no stop, no target, no compounding, **non-overlapping trades only**.

`disp_4_lag1`, TRAIN+DEV, 4,034 trades, median ATR $2.495:

| | Value |
|---|---|
| **Gross mean** | **−$0.246 (−0.0865 ATR)** |
| Gross median | −$0.060 |
| Win rate | 49.7% |
| Block t | −1.66, CI [−0.189, +0.016] ATR |
| sd / p10 / p90 | $9.57 / −$9.96 / +$9.14 |

**The gross mean is negative before any cost is applied.** Cost sensitivity
therefore cannot be meaningfully assessed — there is no positive gross effect for
costs to erode. For completeness, net means under the four slippage assumptions run
from −$0.576 (1× spread, no slippage) to −$1.566 (2× spread, 1.0× slippage), with
net block t from −4.40 to −12.58.

**Answering the required question — do costs consume a negligible, material, or
most of the movement?** The question does not arise: there is **no measured
conditional movement to consume**. For scale, the round-turn cost of $0.33 is
**0.158 ATR in TRAIN** (median ATR $2.09) and **0.093 ATR in DEV** ($3.56) — so a
fixed dollar cost is a *larger* ATR burden in TRAIN, and any future candidate must
clear ~0.16 ATR there before it is worth anything.

### Three quantities the brief asked me to keep distinct

1. **Conditional distribution separation** — Q5−Q1 = −0.158 ATR, CI crossing zero.
2. **Expected return of a hypothetical trade** — −0.087 ATR gross, **negative**.
3. **Realised strategy expectancy** — not estimated; no strategy exists, and none
   should be built on this.

Phase 1 conflated (1) with (2). They are not the same quantity, and here neither is
positive.

---

## Phase 2D — Multiple-testing discipline

Only `disp_4_lag1` and `disp_8_lag1` were tested, plus the pre-specified regime,
cost and overlap diagnostics. **No new candidate features were introduced**, no
thresholds were searched, and no trading rule was created.

---

## Required answers

| # | Question | Answer |
|---|---|---|
| 1 | Survives longer H1 bull/bear context? | **FAIL** — clean null over 16 years, \|t\| ≤ 1.08 in every period |
| 2 | Survives realistic spread/slippage? | **NOT REACHED** — gross is negative before costs |
| 3 | Distinguishable from zero after overlap control? | **FAIL** — every CI crosses zero |
| 4 | Enough to justify strategy design? | **NO** |
| 5 | Any reason to open FINAL_OOS? | **NO** — there is nothing to validate |

**Verdict: EVIDENCE INCONCLUSIVE — DO NOT OPEN FINAL_OOS.**

---

## Limitations and scope of the retraction

- **The flawed estimator was used throughout the Phase 1 scan**, so every
  t-statistic in `phase1_structure_results.json` is unreliable — including the
  controls that produced Phase 1's rejections.
- Phase 1's *rejections* are unaffected **in substance**: the correction removes a
  false positive rather than creating new ones, and the corrected estimator finds
  nothing here either. But I have **not** re-run the full scan, so I cannot claim
  that rigorously, and I am not claiming it.
- The 2026 spread is applied to 2022–2024, where ATR is 4× lower. That assumption
  makes costs a larger ATR fraction in TRAIN than the figures suggest for DEV.
- The H1 analogue is a different signal on a different timeframe. Its null is
  strong contextual evidence, not a direct test of the M15 structure.
- The M15 sample still contains no multi-year bear market; that limitation is
  unchanged, though it is now moot.

## What I would do differently, carried forward

The failure mode was not a bad hypothesis — it was a **bad estimator applied to
overlapping data**. Two rules follow, and both belong in the standing controls
alongside `artifact_check.py`:

1. **Report the raw conditional means next to any block statistic.** A block
   statistic that disagrees in *sign* with the raw means is a red flag, and that
   single check would have caught this immediately.
2. **Compute the headline on non-overlapping observations.** Where forward windows
   overlap by 16×, the non-overlapping estimate is the one that corresponds to
   anything tradable; block corrections to the overlapping estimate do not.

Stopping here as instructed. FINAL_OOS remains locked.
