# Original Continuation Hypothesis — Audit Report

## Final classification: **NOT SUPPORTED**

| Family | Classification |
|---|---|
| **A — bias alone** | **INCONCLUSIVE** |
| **B — bias + displacement** | **NOT SUPPORTED** |
| **C — bias + structure** | **NOT SUPPORTED** |
| **Overall** | **NOT SUPPORTED** |

The architecture's two confirmation layers — displacement and structure — do not
merely fail to help. They **subtract** from bias alone at every horizon tested.
The base directional premise is undecided rather than refuted, because the
confidence intervals remain wide enough to contain a cost-relevant effect.

FINAL_OOS was not opened. No strategy was constructed, no threshold chosen.

---

## 1. Frozen hypothesis

`research/original_continuation_hypothesis.md`, committed at **`1110636`**, which
contains the specification **and no results file** — the audit script and results
did not exist at that commit. Nine hypotheses were pre-declared: three families ×
three horizons.

## 2. Data boundaries

`data/research_v1/` via `dataset_access` only. M15 primary, H1 context.
**TRAIN 2022-06-30 → 2024-08-09, DEV 2024-08-11 → 2025-09-02.** Panels truncated
at the DEV boundary before computation; asserted. **No FINAL_OOS bar used,
including as H1 context.**

## 3–4. Definitions — verified literal

The production rules were not re-described, they were **executed**. Where a rule
was evaluated vectorised for tractability, it was checked against the production
function itself:

| Production function | Verification | Result |
|---|---|---|
| `bias_engine.get_fast_bias` | 120 probes vs vectorised rule | **0 bias mismatches, 0 strength mismatches** |
| `entry_engine.detect_displacement_candle` | 200 probes × 2 sides = 400 checks | **0 mismatches** |
| `structure_engine.get_h1_structure` | called directly per H1 bar, not reimplemented | n/a |

**Declared deviation, frozen in advance:** `detect_displacement_candle` is called
with **M15** rather than the production **M5**, because M15 is the authorised
primary timeframe for this audit. The function body is timeframe-agnostic. The
input frame changed; the rule and every threshold did not.

**Labels.** Direction-normalised forward return, `+1 × (close[i+h] − close[i])/ATR[i]`
for BUY and `−1 × …` for SELL, at h = 4 / 8 / 16 M15 bars.

## 5–7. Results — raw, non-overlapping, and overlap ratios

Headline is the **non-overlapping** estimate throughout.

| Family | Hor | raw n | **non-overlap n** | **overlap** | **mean (ATR)** | se | **t** | **95% CI** |
|---|---|---|---|---|---|---|---|---|
| A bias alone | 1h | 36,469 | 9,122 | 4.0× | +0.0041 | 0.0159 | 0.26 | [−0.027, +0.035] |
| A | 2h | 36,469 | 4,614 | 7.9× | +0.0119 | 0.0324 | 0.37 | [−0.051, +0.075] |
| A | 4h | 36,469 | 2,362 | **15.4×** | +0.0413 | 0.0655 | 0.63 | [−0.087, +0.170] |
| B bias+displacement | 1h | 5,890 | 4,042 | 1.5× | **−0.0170** | 0.0246 | −0.69 | [−0.065, +0.031] |
| B | 2h | 5,890 | 2,801 | 2.1× | **−0.0185** | 0.0413 | −0.45 | [−0.099, +0.062] |
| B | 4h | 5,890 | 1,771 | 3.3× | +0.0018 | 0.0782 | 0.02 | [−0.151, +0.155] |
| C bias+structure | 1h | 29,978 | 7,498 | 4.0× | +0.0038 | 0.0175 | 0.22 | [−0.031, +0.038] |
| C | 2h | 29,978 | 3,934 | 7.6× | +0.0041 | 0.0350 | 0.12 | [−0.065, +0.073] |
| C | 4h | 29,978 | 2,119 | 14.1× | +0.0258 | 0.0682 | 0.38 | [−0.108, +0.159] |

Population: 75,015 M15 bars, all with H1 context. Bias BULLISH 32,134, BEARISH
25,123, **NEUTRAL 17,758 excluded** (no observation, per the production mapping).
Displacement aligned on 9,330 bars; structure confirmed on 47,130.

**Every confidence interval straddles zero.** Maximum |t| across all nine is
**0.688**.

## 8. Multiple testing

| | |
|---|---|
| Pre-declared hypotheses | **9** |
| Nominal alpha | 0.05 |
| Expected \|t\| ≥ 2 under null | **0.41** |
| **Observed \|t\| ≥ 2** | **0** |
| Bonferroni threshold | \|t\| ≥ **2.773** |
| **Bonferroni survivors** | **0** |
| **Benjamini–Hochberg survivors** | **0** |

Zero exceedances where 0.41 are expected. This is not a marginal failure.

### The confirmation layers subtract

Excess over the **direction-conditioned** baseline — the test of whether a layer
adds anything beyond "the bias already said long/short":

| Family | 1h | 2h | 4h |
|---|---|---|---|
| **B bias + displacement** | **−0.0211** | **−0.0305** | **−0.0395** |
| **C bias + structure** | −0.0004 | **−0.0078** | **−0.0155** |

Negative at every horizon, monotonically worse as the horizon lengthens.

> *A's excess is 0.0000 by construction* — A *is* the direction-conditioned
> population, so that comparison is degenerate. Stated rather than presented as a
> null. A is tested against the unconditional mean, in the table above.

**Displacement-conditioned baseline:** no family reaches |t| = 1.5 (max 1.44).
Nothing adds information beyond recent directional movement.

## 9. Temporal stability

`A_bias_alone@4h`, pre-specified segments:

| TRAIN_Q1 | TRAIN_Q2 | TRAIN_Q3 | TRAIN_Q4 | DEV |
|---|---|---|---|---|
| +0.001 (0.01) | **−0.088 (−0.65)** | **+0.237 (1.77)** | +0.015 (0.12) | +0.181 (2.19) |

**Sign flips across quarters.** Reported as instability; no period selected.

## 10. H1 regime context — the most informative result

Secondary by the frozen specification: reported, **not counted as discovery, not
used to select anything**.

| Cell | H1_BULL | H1_NEUTRAL | H1_BEAR |
|---|---|---|---|
| A@2h | **+0.124 (t 3.39, n 3774)** | −0.015 (−0.18) | **−0.074 (−1.96, n 2971)** |
| A@4h | **+0.242 (t 3.32, n 2003)** | −0.067 (−0.47) | −0.069 (−0.95) |
| C@2h | +0.124 (3.20) | +0.098 (0.91) | −0.054 (−1.32) |

**The returns here are already direction-normalised.** Genuine continuation would
be positive in *both* regimes — positive when following an uptrend long, and
positive when following a downtrend short. Instead it is **positive long and
negative short**, in a sample whose three arms are all net-positive
(+33.6 / +44.2 / +18.2%).

That is the signature of **drift**, not of a continuation mechanism. The
production system following its own bias would have been collecting the gold
uptrend, not exploiting continuation.

### Bias strength runs the wrong way

Secondary; all |t| ≤ 1.02, so no claim of significance:

| Horizon | low strength | mid | high |
|---|---|---|---|
| 1h | **+0.0191** | −0.0023 | −0.0053 |
| 2h | **+0.0571** | −0.0163 | −0.0166 |
| 4h | **+0.0784** | +0.0232 | +0.0199 |

**Continuation does not increase with `bias_strength` — the point estimates run
the other way.** This matters for the architecture specifically: `bias_strength`
feeds the confidence model, and the A+ checklist requires `strength ≥ 8.0`. The
premise that stronger bias means better continuation finds no support here, though
nothing is significant.

## 11. Cost diagnostic — **not run**, correctly

No family produced a positive gross effect surviving the corrected threshold, so
the cost analysis was stopped as the specification requires. Had it run, the
convention would have been round-turn = 1 × spread ($0.33).

## 12. Limitations

1. **Power.** The 4h CI upper bound is **+0.170 ATR** against a round-turn cost of
   **0.158 ATR in TRAIN**. A cost-relevant effect is only just inside the
   interval — which is precisely why family A is INCONCLUSIVE and not NOT
   SUPPORTED. Non-overlapping inference at 4h leaves 2,362 observations from
   36,469 raw.
2. **No multi-year bear market** in the M15 sample. The H1_BEAR strips are
   downtrends inside a rising market, not a bear regime. Not manufactured, and not
   claimed to be one.
3. **The M15 displacement deviation** is declared, verified exact, and may still
   behave differently from the M5 original — displacement is a fast-timeframe
   concept and M15 bars are coarser.
4. **Five of nine cells carry `ESTIMATOR_SIGN_DISAGREEMENT`** between the raw and
   equal-block statistics. None is a headline; the headline is non-overlapping
   throughout. The flags are recorded, not suppressed.
5. **This audits the hypothesis, not every production path.** Regime selection,
   session gating, sweep/POI/FVG layers and the entry trigger were not evaluated.
6. **NEUTRAL bars are excluded**, which is the production mapping — 17,758 of
   75,015 bars, nearly a quarter.

## 13. Final classification

**NOT SUPPORTED.**

The reasoning, separated by family because the evidence differs:

- **A (bias alone) — INCONCLUSIVE.** Seven of nine cells have a positive point
  estimate, but max |t| is 0.69, zero survive correction, the sign flips across
  quarters, and the 4h interval is wide enough to contain a cost-relevant effect.
  The audit could not decide this one; it did not refute it either.
- **B (bias + displacement) — NOT SUPPORTED.** Excess over the direction baseline
  is negative at all three horizons. Adding the displacement filter made
  continuation *worse*.
- **C (bias + structure) — NOT SUPPORTED.** Same pattern, smaller magnitude.
  Structure confirmation adds nothing, trending negative with horizon.

The overall classification is NOT SUPPORTED because the hypothesis under audit is
the *architecture's* continuation claim — bias confirmed by displacement and
structure — and both confirmation layers measurably subtract. The strongest
apparent signal in the whole audit, the H1_BULL regime cell, is one that a genuine
continuation mechanism would not produce, because it reverses sign on the short
side.

No profitability or performance claim is made or implied. The next phase requires
separate authorisation.
