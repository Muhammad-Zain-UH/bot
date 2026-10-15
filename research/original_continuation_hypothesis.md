# Original Continuation Hypothesis — frozen specification

**This file is committed BEFORE any result is generated.** Nothing in it is
derived from an observed outcome. Git history is the evidence: this commit
contains no results file.

The hypothesis uses only definitions that already exist in the production
codebase, quoted below with their source. Where the production call site and the
function's own generality differ, the ambiguity is documented rather than
silently resolved.

---

## 1. What constitutes directional displacement

Two existing production notions are in scope, tested separately.

### 1a. L1 directional bias — `bias_engine.get_fast_bias`

The production *direction decision* for the scalp regimes. Operates on H1.

```
ema_threshold = max(2.0, atr_14 * 0.12)            # _calculate_ema_threshold(floor=2.0, atr_ratio=0.12)
d             = ema20 - ema50

|d| <  ema_threshold  ->  NEUTRAL,  strength 0
 d  >  ema_threshold  ->  BULLISH,  strength = min(10, |d| / ema_threshold)
 d  < -ema_threshold  ->  BEARISH,  strength = min(10, |d| / ema_threshold)
```

Source: `bias_engine.py::get_fast_bias` and `_calculate_ema_threshold`.
**BULLISH maps to BUY, BEARISH to SELL** — the production mapping.

### 1b. Displacement candle — `entry_engine.detect_displacement_candle`

```
close_position = (close - low) / (high - low)

BUY  directional_ok = close > open  and  close_position >= 0.7
SELL directional_ok = close < open  and  close_position <= 0.3

displacement_found = directional_ok AND ( body/atr >= 0.9  OR  body/range >= 0.6 )
```

Source: `entry_engine.py::detect_displacement_candle`.

> **Documented ambiguity — not silently reinterpreted.** The production call site
> passes an **M5** frame (`detect_displacement_candle(m5_data, direction)`). The
> function body is timeframe-agnostic: it reads `.iloc[-1]` and an ATR from
> whatever frame it is given. This audit's primary timeframe is **M15** by
> instruction, and the authorised data boundary excludes M5 as a directional
> source. I therefore apply the function **literally, unmodified, to M15 bars**,
> and record this as a deviation from the production call site. It is a change of
> input frame, not of rule. No threshold is altered.

### 1c. H1 structure confirmation — `structure_engine.get_h1_structure`

Returns `structure_type` in `{HH/HL, LH/LL, BROKEN, UNKNOWN}` and
`structure_valid`. Structure is **confirmed** when `structure_type == "HH/HL"` for
a BULLISH bias or `"LH/LL"` for a BEARISH bias. Source:
`structure_engine.py::validate_h1_structure`.

## 2. What constitutes continuation

Price continues in the already-established direction. Operationally, the
**direction-normalised forward return**:

```
r_signed = +1 * (close[i+h] - close[i]) / ATR[i]   when the predicted direction is BUY
r_signed = -1 * (close[i+h] - close[i]) / ATR[i]   when SELL
```

Continuation is present if `E[r_signed] > 0` **and** exceeds the baselines in §5.

## 3. Horizons tested

**1h = 4 M15 bars · 2h = 8 · 4h = 16.** No 8h. M15 is the primary timeframe; H1
supplies the bias, structure and regime context only. M1 and ticks are not used.

## 4. Direction predicted

The direction the production system would have taken: **BUY when L1 bias is
BULLISH, SELL when BEARISH.** NEUTRAL bars produce no observation. This is a
directional prediction fixed in advance, not fitted.

## 5. Baselines

Three, in increasing severity. The purpose is to see whether continuation carries
information **beyond the fact that price has already moved**.

1. **Unconditional** — mean signed-long forward return over all eligible bars,
   side-matched to the tested subset's BUY/SELL composition.
2. **Direction-conditioned** — for a BUY observation, the mean return of all
   eligible BUY-side bars; likewise SELL. Removes the period's net drift.
3. **Displacement-conditioned** — within quintile strips of `disp_8`
   (8-bar M15 displacement), so a continuation signal must add information beyond
   recent directional movement itself.

## 6. What would constitute evidence AGAINST continuation

Any of:

- `E[r_signed] <= 0` on the non-overlapping headline estimate;
- a 95% confidence interval that straddles zero after multiple-testing correction;
- the effect disappearing under the direction- or displacement-conditioned
  baseline, i.e. continuation adds nothing beyond prior movement;
- sign instability across the pre-specified temporal segments;
- `ESTIMATOR_SIGN_DISAGREEMENT` on the headline cell.

## 7. What would constitute an INCONCLUSIVE result

- Headline point estimate positive but not surviving the corrected threshold,
  with a confidence interval wide enough to contain economically relevant effects
  — i.e. the audit lacked the power to decide;
- survival on some horizons but not others with no coherent pattern;
- insufficient non-overlapping observations (< 100 per cell).

A positive point estimate that fails correction is **INCONCLUSIVE**, not SUPPORTED.

---

## Pre-declared hypothesis set — frozen for multiple-testing correction

**9 primary hypotheses.** No others will be tested; no feature search will occur.

| # | Hypothesis | Condition at the M15 bar close | Horizons |
|---|---|---|---|
| A1–A3 | **Bias alone** | L1 fast-bias is BULLISH or BEARISH | 1h, 2h, 4h |
| B1–B3 | **Bias + displacement** | as A, **and** `detect_displacement_candle` on M15 returns `displacement_found` in the bias direction | 1h, 2h, 4h |
| C1–C3 | **Bias + structure** | as A, **and** `get_h1_structure` confirms HH/HL (bullish) or LH/LL (bearish) | 1h, 2h, 4h |

Secondary, reported but **not** counted as discovery and **not** used to select a
candidate: the same three families split by H1 regime (bull/bear/neutral) and by
pre-specified temporal segment, and a bias-strength tercile breakdown using the
existing `bias_strength` scale.

## Statistical standard

`research/STATISTICAL_RESEARCH_CONTROLS.md` applies in full and is mandatory:
non-overlapping headline inference, raw statistics alongside, block statistics
secondary with weighting disclosed, estimator-sign-disagreement check, overlap
ratios, forward-window audit, Bonferroni and Benjamini–Hochberg correction across
the 9 pre-declared hypotheses, confidence intervals and sample counts throughout.

## Data boundaries

`data/research_v1/`, loaded only via `research/dataset_access.py`.
**TRAIN 2022-06-30 → 2024-08-09; DEV 2024-08-11 → 2025-09-02.** Panels truncated
at the DEV boundary before any computation. **No H1 bar from the FINAL_OOS window
may be used, including as context.** FINAL_OOS remains locked.

## Cost diagnostic

Runs **only if** the gross continuation effect survives the statistical screen.
Round-turn spread cost = **1 × spread** ($0.33 measured median), with slippage at
0, 0.25, 0.5 and 1.0 × spread. No execution assumption will be optimised.

## What this audit does not do

No entry threshold, confirmation-bar count, stop, target, reward/risk ratio,
session filter, position size, leverage or spread filter is chosen or optimised.
No EA rule set is produced. The audit answers one question: **does the original
continuation hypothesis have measurable support?**
