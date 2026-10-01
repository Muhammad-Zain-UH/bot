> # RETRACTED -- see PHASE2_REGIME_COST_REPORT.md
>
> **The headline conclusion of this report is withdrawn.** Phase 2A-2C established
> that the Q5-Q1 statistic used throughout was computed as an **unweighted mean of
> per-block means**, which is biased here because the number of Q1/Q5 observations
> inside a 16-bar block is endogenous to the outcome.
>
> Under the correct estimator -- non-overlapping observations with disjoint forward
> windows -- `disp_4_lag1` gives spread **-0.158, t = -1.07, CI [-0.446, +0.130]**,
> and the H1 analogue over 16 years and 23,422 independent observations gives
> **+0.029, t = +0.89**. There is **no robust conditional structure**.
>
> The original text is preserved below unaltered, as the record of what was done.
> Every t-statistic in it is unreliable.

# Phase 1 — Conditional Structure Discovery

## ONE ROBUST CANDIDATE STRUCTURE DETECTED

**Short-horizon mean reversion of recent displacement**, measured with a feature
that shares **no price point** with the label. It survives every control applied,
is stable across all six TRAIN segments, replicates in DEV, and is present in both
H1-bullish and H1-bearish states.

**48 of 50 screened effects were rejected** — as re-encodings of the same
phenomenon, or as endpoint-coupling artifacts.

No trading rule was built. No threshold chosen. No profitability claimed.
**FINAL_OOS was never touched.**

---

## A. Dataset

`data/research_v1/`, dataset `9925ff94…`, loaded only through
`research/dataset_access.py`. Token untouched.

| | |
|---|---|
| Primary | **M15** |
| Context | **H1** (last H1 bar *closed* at or before the M15 close) |
| Not used | M5, M1, ticks, H4 — per the brief |
| Panel span | 2022-06-30 → **2025-09-02** (= DEV end) |
| TRAIN rows (eligible) | **49,961** |
| DEV rows (eligible) | **24,989** |

**OOS isolation is structural, not procedural.** Both panels are truncated at the
DEV boundary *before any feature is computed*, and the truncation is asserted. A
label needing bars past the boundary is `NaN` with `has_window = False`, so the
last 16 M15 bars carry no 4h label — computing them would have required reading
FINAL_OOS.

## B. Feature families — 37 features

All causal. **Causality verified, not asserted:** the entire panel was rebuilt from
truncated data at 60 random indices and required to agree exactly —
**0.0 deviation on all 37**.

| Family | Features |
|---|---|
| 1 Displacement | `disp_1/4/8/16`, `persist_8/16` |
| 2 Volatility | `atr`, `atr_ratio`, `atr_short_long`, `range20_atr`, `range_expansion`, `ntr` |
| 3 Candle/range | `body_ratio`, `upper_wick`, `lower_wick`, `close_loc` |
| 4 Trend/state | `ma20_dist_atr`, `ma50_dist_atr`, `ma_spread_atr`, `slope20_atr`, `slope50_atr` |
| 5 Location | `pos_20`, `pos_50`, `dist_high20_atr`, `dist_low20_atr` |
| 6 Compression | `compression`, `expansion_state`, `vol_transition` |
| 7 Session/time | `utc_hour`, `weekday`, `session`, `bars_since_reopen` |
| 8 H1 context | `h1_disp_4`, `h1_disp_12`, `h1_atr_ratio`, `h1_trend`, `pos_h1_20`, `h1_trend_x_m15_disp` |

Six features were tagged `couples_with_close` in advance — `close_loc`, `pos_20`,
`pos_50`, `dist_high20_atr`, `dist_low20_atr`, `pos_h1_20` — because they are
functions of `close[i]`'s position and the label subtracts `close[i]`. **Tagging
them before looking at results is why the artifact was caught rather than
published.**

## C. Labels

Horizons **1h = 4**, **2h = 8**, **4h = 16** M15 bars. 8h deliberately absent.
Per horizon: forward return in dollars and in ATR, direction, MFE/MAE in ATR, and
the forward return measured from **four origins** — `close[i]`, `mid[i]`,
`close[i+1]`, `close[i+2]` — so the reference-price and delayed-entry controls need
no recomputation.

`phase1_label_panel.py` imports nothing from the feature module; it reads one
column (`atr`) from the pickle. Features → labels, never the reverse.

## D. Conditional baselines

Unconditional arm mean; **displacement-conditioned** (`disp_8` quintile strips,
inverse-variance pooled); **volatility-conditioned** (`atr_ratio` strips). All
cutoffs from **TRAIN only**, applied unchanged to DEV.

## E–F. Cells tested and multiple-testing treatment

**102 Q5−Q1 spread tests** on TRAIN (37 features × 3 horizons, minus cells with
insufficient population). The Q5−Q1 spread is the correct test for a monotonic
relationship; per-quintile cells are reported for shape only.

| Threshold | Observed | Expected under null |
|---|---|---|
| \|t\| ≥ 2.0 | **53** | 4.6 |
| \|t\| ≥ 2.5 | **50** | 1.3 |
| \|t\| ≥ 3.0 | **43** | 0.3 |
| max \|t\| | **14.62** | — |
| **Bonferroni α=0.05** | **\|t\| ≥ 3.486** | — |

Fifty survivors where 1.3 are expected is **not fifty discoveries**. It is the
signature of one pervasive effect plus arithmetic coupling, and §I shows it is
exactly that. Pre-declared screen: \|t\| ≥ 2.5 on TRAIN, then all controls.

## G. Strongest effects (TRAIN, pre-control)

| Feature | Hor | Spread | t | Couples? |
|---|---|---|---|---|
| `disp_1` | 2h | −0.609 | **−14.62** | no |
| `disp_4` | 2h | −0.692 | −14.30 | no |
| `disp_4` | 4h | −1.156 | −13.93 | no |
| `pos_20` | 2h | −0.797 | −13.91 | **yes** |
| `disp_8` | 4h | −1.188 | −12.78 | no |
| `ma20_dist_atr` | 2h | −0.752 | −12.47 | no |
| `dist_high20_atr` | 2h | +0.701 | +12.05 | **yes** |

Every large effect is a **negative** spread on a displacement- or
position-type feature. One phenomenon, measured many ways.

## H. Effects surviving the controls

**Candidate: lagged displacement mean reversion.**

```
feature  disp_w_lag1 = (close[i-1] - close[i-1-w]) / atr[i-1]    w in {4, 8}
label    (close[i+h] - close[i]) / atr[i]                        h in {4, 8, 16}
         -> the feature ends at close[i-1]; it shares NO price point with the label
```

**Control 1 — no shared price point.** The decisive test.

| Feature | Hor | lag0 | **lag1** | **lag2** | retention (lag1/lag0) |
|---|---|---|---|---|---|
| `disp_4` | 1h | −12.24 | −4.53 | −1.35 | 0.37 |
| `disp_4` | 2h | −14.30 | **−8.40** | −5.05 | 0.59 |
| `disp_4` | **4h** | −13.93 | **−10.83** | **−8.94** | **0.78** |
| `disp_8` | 4h | −12.78 | **−9.10** | −6.82 | 0.71 |
| `disp_16` | 4h | −8.81 | −6.29 | −4.59 | 0.71 |

**A large part of the raw effect was coupling** — retention is only 0.27–0.42 at
1h, and `disp_16@1h` reaches t = +0.15 at lag2, i.e. gone. **A substantial
component survives at 2h and especially 4h**, with a two-bar gap.

**Control 2 — ATR denominator.** Feature and label both divide by ATR, so a shared
`1/atr` could manufacture correlation. Re-run with a **raw dollar** label:

| Feature | Hor | ATR-normalised | **Dollar** |
|---|---|---|---|
| `disp_4` | 4h | −10.83 | **−10.61** |
| `disp_8` | 4h | −9.10 | **−9.13** |

**Not a denominator artifact** — at 4h the dollar result is indistinguishable.

**Control 4 — volatility-conditioned.** `disp_4@4h`: H1-high-vol **−6.7**,
H1-low-vol **−5.4**. Survives both halves.

**Control 5 — temporal stability (TRAIN).**

| Feature | H1 | H2 | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|---|
| `disp_4@4h` | −7.6 | −7.7 | −5.5 | −5.3 | −5.2 | **−5.8** |
| `disp_8@4h` | −6.6 | −6.3 | −4.5 | −4.9 | −3.9 | −5.1 |
| `disp_4@1h` | −3.3 | −3.2 | −3.4 | **−1.1** | **−1.6** | −3.0 |

**4h is stable** — same sign, near-identical magnitude, all six segments. **1h is
not** and should not be carried forward.

**Control 6 — TRAIN → DEV replication.**

| Feature | Hor | TRAIN | **DEV** |
|---|---|---|---|
| `disp_4` | 4h | −10.83 | **−7.78** |
| `disp_8` | 4h | −9.10 | **−6.53** |
| `disp_4` | 2h | −8.40 | −5.60 |
| `disp_16` | 4h | −6.29 | −4.35 |

Same sign at every cell; magnitude attenuated ~25–35%.

**Control 7 — block-shift null.** 50 fixed-seed circular shifts: null max \|t\|
1.05–4.60, `p_exceed = 0.000`. **Caveat I want on the record:** this null breaks
*time alignment*, so it cannot detect arithmetic coupling, which exists at every
time point. Controls 1 and 2 are what addressed coupling; this one only rules out
chance alignment.

## I. Effects rejected as artifacts — 48 of 50

**Category D — explained by another family (the majority).** Within `disp_8`
quintile strips, the position and MA-distance families collapse:

| Feature | Raw t | **Within disp strips** |
|---|---|---|
| `disp_4@2h` | −14.30 | **−0.58** |
| `pos_20@2h` | −13.91 | **+0.64** |
| `ma20_dist_atr@2h` | −12.47 | **−0.42** |
| `pos_50@4h` | −9.74 | **−0.57** |
| `dist_high20_atr@4h` | +11.23 | **+1.05** |

`pos_20`, `pos_50`, `ma20_dist_atr`, `ma50_dist_atr`, `dist_high20_atr`,
`dist_low20_atr` **re-encode recent displacement**. They are not independent
structures and must never be counted as separate evidence.

**Category C — coupling artifact.** Two features **flip sign** when the label's
origin moves from `close[i]` to `mid[i]`:

| Feature | from `close[i]` | from `mid[i]` |
|---|---|---|
| `disp_1@1h` | −13.07 | **+18.91** |
| `close_loc@2h` | −10.85 | **+11.23** |

A feature whose sign depends on where the label's origin is placed is measuring the
origin. `disp_1` had the **largest t-statistic in the entire scan (−14.62)** and is
rejected outright.

## J. TRAIN/DEV stability

Reported in Control 6. Sign carries at every cell; attenuation 25–35% is consistent
with mild TRAIN-side selection, not with an artifact.

## K. H1 regime stability

| Feature | H1_BULL | **H1_NEUT** | H1_BEAR |
|---|---|---|---|
| `disp_4@4h` | **−6.5** | **−0.0** | **−5.3** |
| `disp_8@4h` | −5.6 | **+0.5** | −4.1 |
| TRAIN population | 23,178 (46.4%) | 6,767 (13.5%) | 20,016 (40.1%) |

**Present in both H1-bull and H1-bear; absent in H1-neutral.** This matters more
than it looks: all three dataset arms are net-positive, so a long-bias artifact was
the main worry. An effect that holds in H1 *downtrends* as well as uptrends is
**not** a long-bias artifact. H1_NEUT carries only 13.5% of rows so its power is
lower, but t = −0.0 / +0.5 is a clean zero rather than a weak signal.

## L. Remaining limitations

1. **This is not a novel discovery.** Short-horizon mean reversion in
   ATR-normalised returns is a well-documented market-microstructure property. The
   contribution here is that it was isolated from coupling and shown stable — not
   that it is new.
2. **No multi-year bear market in the M15 sample.** All three arms are net-positive
   (+33.6 / +44.2 / +18.2%). The H1_BEAR strip shows the effect in H1 downtrends,
   but those are downtrends *inside* a rising market, not a 2013- or 2015-style
   bear regime. Stated as a limitation, not hidden.
3. **Median ATR rises 4.3× across arms** ($2.09 → $3.56 → $8.93), so TRAIN and DEV
   are different volatility regimes. The effect survives both, which is reassuring,
   but FINAL_OOS is more extreme still.
4. **1h does not qualify.** Weak retention under the gap control and unstable across
   TRAIN quarters. Only 2h and 4h carry.
5. **Magnitude is reported, tradability is not.** `disp_4@4h` lag1 Q5−Q1 spread is
   **−0.887 ATR**; at TRAIN median ATR $2.085 that is ≈ **$1.85** between extreme
   quintiles, against a measured round-turn spread cost of ≈ **$0.66**. A Q5−Q1
   spread is **not** a per-trade edge and I am not converting it into one. No
   profitability claim is made or implied.
6. **H1 pre-2022 was not used.** It is available (17.08 years) and is the obvious
   next regime test, but it cannot serve as M15 OOS and was not treated as such.
7. **Still one effect, not a strategy.** No entry, exit, stop, target, sizing or
   risk model exists, and none was explored.

## M. Shortlist

**One structure, at two horizons:**

| # | Structure | Horizons | Status |
|---|---|---|---|
| **1** | `disp_w_lag1` (w = 4, 8 M15 bars) → negative forward return | **2h, 4h** | **A — robust candidate** |

Everything else is **B/C/D/E**: 48 rejected as coupling or as re-encodings, the
session/time and compression families produced nothing above the Bonferroni
threshold, and H1-context features added no independent signal.

### If Phase 2 is authorised, the honest next steps

1. **Regime test on H1 pre-2022** — contextual evidence only, never M15 OOS.
2. **Cost realism** before anything else. The effect is ~2.8× the round-turn spread
   at the Q5−Q1 extreme; a per-signal edge will be far smaller, and the measured
   $0.33 median spread is itself 58% above the $0.20 the old baselines assumed.
3. **Decide whether mean reversion is the intended direction of travel.** This is
   the opposite of the original system's design, which was continuation-based.

**FINAL_OOS remains locked. I did not open it, and I am not recommending it be
opened yet** — one structure at two horizons, with no cost model, does not justify
spending the single look.
