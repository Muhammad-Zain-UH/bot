# Phase 1 — Clean Rerun

## NO ROBUST CONDITIONAL STRUCTURE DETECTED

**0 survivors** under Bonferroni, **0** under Benjamini–Hochberg. Maximum headline
|t| across 84 hypotheses was **3.18**, below the corrected threshold of **3.434**.
Observed |t| ≥ 2 was **6** against **3.82** expected under the null.

Nothing was imported from the retracted Phase 1: no rankings, no survivor list, no
rejection classifications. Only the feature *definitions* were reused — those were
never in question.

**FINAL_OOS was not opened.** Token unchanged, dataset and split manifest
unchanged, `baseline_008` and production unchanged.

---

## Part A — Guardrails

All ten implemented in `research/phase1_statistical_controls.py`; the standing
standard is `research/STATISTICAL_RESEARCH_CONTROLS.md`. Self-tests exit 0.

| # | Guardrail | Status |
|---|---|---|
| 1 | Raw conditional statistics before any aggregation | PASS |
| 2 | Non-overlapping headline estimator | PASS |
| 3 | Block statistics secondary + sign-disagreement check | PASS |
| 4 | Weighting disclosure on every aggregate | PASS |
| 5 | Overlap ratio reported prominently | PASS |
| 6 | Forward-window audit | PASS |
| 7 | Causal reconstruction test retained | PASS |
| 8 | TRAIN/DEV truncation before feature computation | PASS |
| 9 | FINAL_OOS lock | PASS |
| 10 | Multiple-testing discipline | PASS |

### Required fixtures — both caught

**Estimator sign disagreement.** Constructed so that observation-weighting and
equal-block-weighting must disagree: 12 observations at +0.5 in dense blocks, 1 at
−4.0 in sparse blocks.

```
raw mean   +0.1515   (observation-weighted)
block mean -1.7511   (equal-block-weighted)
flags      ['ESTIMATOR_SIGN_DISAGREEMENT', 'HIGH_OVERLAP_6.5x']
needs_review True
```

**Overlapping labels.** 800 contiguous observations at horizon 16:

```
raw n 800  ->  non-overlapping n 50  ->  ratio 16.0x   HIGH_OVERLAP flagged
```

Plus four further fixtures: forward-window audit detects a 4-bar-gap sample as
non-disjoint; `non_overlapping_indices` is deterministic and idempotent;
multiple-testing arithmetic reproduces the Bonferroni threshold to 3 d.p.; and
`block_stats` cannot return a value without a weighting label.

---

## Part B — Clean discovery

**Dataset.** `data/research_v1/`, loaded only through `dataset_access`. M15
primary, H1 context, panel truncated at the DEV boundary (`2025-09-02 14:15`).
TRAIN 49,961 eligible rows, DEV 24,989.

**Features.** The eight planned causal families, 37 features, definitions frozen
before any label was touched. Causality verified by prefix rebuild: **0.0
deviation on all 37**.

**Labels.** 1h / 2h / 4h (4 / 8 / 16 M15 bars), future-only. Cutoffs from **TRAIN
only**, applied unchanged to DEV.

**Hypotheses.** 31 features × 3 horizons = **84 cells** after Part C exclusions.

### Headline result

| | |
|---|---|
| Hypotheses | **84** |
| Nominal alpha | 0.05 |
| **Bonferroni threshold** | **\|t\| ≥ 3.434** |
| **Bonferroni survivors** | **0** |
| **Benjamini–Hochberg survivors** | **0** |
| Max headline \|t\| | **3.182** (`vol_transition@1h`) |
| Observed \|t\| ≥ 2 | **6** |
| **Expected \|t\| ≥ 2 under null** | **3.82** |

Six exceedances where chance predicts 3.82 is not a signal. The strongest cell
does not reach the corrected threshold.

### Strongest cells, for the record

| Feature | Hor | diff | se | t | n hi/lo | overlap |
|---|---|---|---|---|---|---|
| `vol_transition` | 1h | −0.1185 | 0.0372 | **−3.18** | 2852/2740 | 3.5× |
| `vol_transition` | 2h | −0.2179 | 0.0693 | −3.14 | 1659/1526 | 6.0× |
| `vol_transition` | 4h | −0.3235 | 0.1262 | −2.56 | 995/946 | 10.0× |
| `lower_wick` | 1h | −0.0627 | 0.0272 | −2.30 | 6219/6155 | 1.6× |
| `atr_ratio` | 2h | −0.1614 | 0.0721 | −2.24 | 1739/1558 | 5.7× |
| `atr_ratio` | 1h | −0.0860 | 0.0385 | −2.23 | 2968/2776 | 3.4× |

None qualifies. `vol_transition@4h` additionally carries
`ESTIMATOR_SIGN_DISAGREEMENT`.

---

## Part C — Features excluded by construction

Six features use `close[i]` while the label is measured from `close[i]`, so they
share a price term with opposite signs and correlate arithmetically. They were
**excluded, not tested and defended**:

`close_loc` · `pos_20` · `pos_50` · `dist_high20_atr` · `dist_low20_atr` ·
`pos_h1_20`

---

## Part D — Multiple testing

Reported as required: hypothesis count, nominal alpha, expected null exceedances,
observed exceedances at two thresholds, Bonferroni threshold, BH FDR, and
corrected survivor counts. **Neither "largest t" nor "number of significant cells"
was used as a result.** No candidate reached the controls stage, so the remaining
chain links (displacement/volatility conditioning, reference-price, delayed-entry,
DEV replication, gross-return screen) were not exercised.

---

## The guardrails earned their place immediately

**43 of 84 cells raised `ESTIMATOR_SIGN_DISAGREEMENT`.** 81 of 84 need review.
That is how pervasive the retracted failure mode was — and it is now impossible to
report such a cell without the flag attached.

The worst cases are the retracted Phase 1 "discoveries":

| Cell | raw diff | block diff | block t | **correct headline t** |
|---|---|---|---|---|
| `disp_4@4h` | **+0.0191** | −1.1564 | **−13.93** | **−0.14** |
| `disp_1@2h` | −0.0266 | −0.6094 | **−14.62** | **−0.33** |
| `disp_4@2h` | −0.0412 | −0.6923 | −14.30 | −0.19 |
| `ma20_dist_atr@4h` | **+0.0389** | −1.2817 | −12.19 | −0.12 |

In two of these the raw difference is **positive** while the block statistic is
strongly negative. The block estimator was not noisy — it was pointing the wrong
way.

### Every retracted candidate under the clean estimator

| Feature | Hor | Phase 1 claimed t | **Clean t** | **95% CI** |
|---|---|---|---|---|
| `disp_4` | 4h | −13.93 | **−0.14** | [−0.222, +0.192] |
| `disp_4` | 2h | −14.30 | **−0.19** | [−0.131, +0.108] |
| `disp_8` | 4h | −12.78 | **−0.30** | [−0.268, +0.196] |
| `disp_8` | 2h | −12.75 | −1.58 | [−0.249, +0.027] |
| `disp_1` | 2h | −14.62 | −0.33 | [−0.120, +0.085] |
| `ma20_dist_atr` | 1h | −11.88 | −1.21 | [−0.125, +0.030] |

Every confidence interval straddles zero.

---

## Part E / F — not reached

No candidate cleared the corrected statistical screen, so temporal and H1-regime
robustness were not run, and **no cost screen was performed** — correctly, since
the standard requires the gross-return stage only for candidates that survive the
statistics.

---

## Power disclosure

Non-overlapping inference costs power, and the cost is stated rather than
discovered later.

| Horizon | Median non-overlapping n per tail | Median SE | MDE (2 SE) | MDE at Bonferroni |
|---|---|---|---|---|
| 1h | 2,998 | 0.0384 | **0.077 ATR** | 0.132 ATR |
| 2h | 1,778 | 0.0722 | **0.145 ATR** | 0.248 ATR |
| 4h | 1,159 | 0.1318 | **0.264 ATR** | 0.453 ATR |

Measured overlap ratios: **3.3× (1h), 5.6× (2h), 8.6× (4h)**.

**A null at 4h means "no effect larger than about 0.45 ATR", not "no effect".**
At 1h the scan could have detected roughly 0.13 ATR. For scale, round-turn spread
cost is 0.158 ATR in TRAIN — so at 1h the scan was sensitive to effects near the
cost threshold, and at 4h it was not.

---

## Limitations

1. **Power, as above.** A moderate 4h effect could hide below 0.45 ATR.
2. **Feature families are the planned eight.** A structure outside them would not
   have been seen; this is not a universal null.
3. **Quintile binning** assumes a monotone tail contrast. A non-monotone or
   interaction effect could be missed.
4. **No multi-year bear market** in the M15 sample. Unchanged, and moot here.
5. **The retracted Phase 1 rejections were not re-derived.** The clean scan is a
   fresh run, so nothing depends on them — but I am not claiming they were
   independently re-confirmed.

---

## Verdict

**NO ROBUST CONDITIONAL STRUCTURE DETECTED.**

Stopping as the decision rule requires. FINAL_OOS not opened, no strategy
designed, no thresholds optimised, no stops or targets created, production and
`baseline_008` untouched.

The durable output of this phase is not a candidate — it is
`phase1_statistical_controls.py` and the standing standard. The original failure
produced t = −14.6 from nothing and survived seven controls; the sign-disagreement
check alone would have caught it in the first run, and now does, automatically, on
every cell.
