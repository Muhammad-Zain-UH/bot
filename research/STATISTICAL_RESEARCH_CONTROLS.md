# Statistical Research Controls — standing standard

This document is binding on all conditional research in this repository. It exists
because a single estimator choice produced a spurious **t = −14.6** that survived
seven artifact controls, a TRAIN→DEV replication, and a block-shift null before it
was caught. The hypothesis was not the problem. The estimator was.

Implementation: `research/phase1_statistical_controls.py`. Run its self-tests with
`python research/phase1_statistical_controls.py` — exit 0 means the guardrails
work, including the two mandated fixtures.

---

## 1. Non-overlapping headline inference

**For any forward horizon *h*, the headline estimate must be computed on
non-overlapping observations** — a sample whose forward label windows are disjoint.

Selection is a deterministic greedy forward scan: accept an observation, then skip
the full *h*-bar window before accepting another (`non_overlapping_indices`).

Any dependence-aware alternative (HAC, cluster-robust, block bootstrap) may be used
as the headline **only if formally justified and named in the output**. An
unweighted mean of per-block means is **never** acceptable as a headline.

## 2. Raw conditional statistics always accompany the headline

Every conditional cell must carry, computed **before** any aggregation:

`n` · `mean` · `median` · `sd` · `se`

A result reported without its raw statistics is not reviewable.

## 3. Block statistics are secondary, and never silent

Block statistics may be reported as robustness diagnostics. They must never
replace the raw or non-overlapping estimate, and they must never appear without
their weighting label.

### The sign-disagreement check

If `sign(block_statistic) != sign(raw_statistic)`, the result is flagged

```
ESTIMATOR_SIGN_DISAGREEMENT
```

and `needs_review = True`. **This is the single check that would have caught the
original failure immediately.** In the clean Phase 1 rerun it fired on **43 of 84
cells**, with cases this stark:

| Cell | raw diff | block diff | block t | **correct headline t** |
|---|---|---|---|---|
| `disp_4@4h` | **+0.0191** | −1.1564 | **−13.93** | **−0.14** |
| `disp_1@2h` | −0.0266 | −0.6094 | −14.62 | −0.33 |

Why it happens: when the number of observations in a block is **endogenous to the
outcome** — a 16-bar block in which price ran up contains mostly high-displacement
bars — equal-block weighting up-weights sparse blocks and manufactures separation.

## 4. Weighting disclosure

Every aggregate carries one of:

- `observation-weighted`
- `equal-block-weighted`
- `non-overlapping (observation-weighted, disjoint windows)`
- `overlapping (observation-weighted, windows share bars)`

Enforced by the `Weighting` class; `block_stats` cannot return a value without one.

## 5. Overlap ratio, reported prominently

Every forward-looking result reports **raw observations**, **non-overlapping
observations**, and the **ratio**. A ratio above 2× raises `HIGH_OVERLAP_<r>x`.

Measured in the clean rerun: **3.3× at 1h, 5.6× at 2h, 8.6× at 4h.**

## 6. Forward-window audit

The headline sample is audited to prove its label windows are disjoint
(`forward_window_audit`): minimum index gap ≥ *h*, zero overlaps. A failure raises
`FORWARD_WINDOW_OVERLAP_IN_HEADLINE`.

## 7. Causal feature construction

Every feature panel is verified by **prefix recomputation**: rebuild the entire
panel from truncated data at random indices and require **exact** agreement. Not
an assertion in a docstring — a test that fails the build.

## 8. TRAIN/DEV isolation and boundary truncation

Panels are **truncated at the relevant boundary before any feature is computed**,
and the truncation is asserted. A label requiring bars past the boundary is `NaN`
with `has_window = False` rather than reaching across it.

Quantile cutoffs and every other threshold are derived from **TRAIN only** and
applied unchanged to DEV. DEV is for **replication**, never discovery.

## 9. FINAL_OOS lock

`research/dataset_access.py` is the only sanctioned loader. It raises
`OOSLockedError` on any FINAL_OOS read without the exact token in
`research_split_manifest.json`. The token is deliberately
`OOS-AUTHORISATION-NOT-ISSUED`, so no caller can unlock it until the manifest is
changed in writing. Opening it must record the date, the git SHA and the candidate
specification SHA, and it is **one look**.

## 10. Multiple-testing discipline

Every scan reports:

- total hypothesis count
- nominal alpha
- **expected** false positives under the null
- observed exceedances at |t| ≥ 2 and ≥ 3
- a **documented correction** — Bonferroni threshold and Benjamini–Hochberg FDR
- corrected survivor count

**A bare count of "cells with |t| > 2" is not evidence.** Neither is "largest
t-statistic". Compare observed against expected, and use a corrected threshold.

## The validation chain

A feature is a *candidate* only after surviving all of:

1. Headline (non-overlapping) |t| ≥ the **corrected** threshold on TRAIN
2. Not mechanically coupled to the label (see below)
3. Displacement-conditioned control
4. Volatility-conditioned control
5. Reference-price control (label measured from `mid[i]`)
6. Delayed-entry control (origin `close[i+1]`)
7. **DEV replication**, same sign
8. **Gross hypothetical trade return positive before costs**

Failing any link is a rejection. `|t| > 2` is not a qualification.

### Mechanical feature/label coupling

A feature whose construction uses `close[i]` while the label is measured from
`close[i]` shares a price term with opposite signs and will correlate for purely
arithmetic reasons. Such features are **excluded by construction**, not tested and
defended. Currently excluded: `close_loc`, `pos_20`, `pos_50`, `dist_high20_atr`,
`dist_low20_atr`, `pos_h1_20`.

Diagnostic for anything suspected: if a feature's effect **flips sign** when the
label origin moves from `close[i]` to `mid[i]`, it is measuring the origin.

### Cost screen ordering

Report gross conditional movement and the gross hypothetical fixed-horizon trade
return **first**. If gross is not positive before costs, the candidate fails at the
gross stage and **no cost optimisation is performed**.

Round-turn spread cost is **1 × spread** (ask = mid + S/2, bid = mid − S/2, so a
long entered at ask and exited at bid pays one spread). Earlier work in this
repository used 2 × spread; that double-counted and is corrected.

## Power disclosure

Non-overlapping inference costs power, and that cost must be stated rather than
discovered later. From the clean rerun:

| Horizon | Median non-overlapping n per tail | Median SE | MDE at 2 SE | MDE at Bonferroni |
|---|---|---|---|---|
| 1h | 2,998 | 0.0384 | 0.077 ATR | 0.132 ATR |
| 2h | 1,778 | 0.0722 | 0.145 ATR | 0.248 ATR |
| 4h | 1,159 | 0.1318 | 0.264 ATR | 0.453 ATR |

A null result at 4h means "no effect larger than ~0.45 ATR", not "no effect".
