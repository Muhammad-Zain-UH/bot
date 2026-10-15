# Production Path Decomposition Audit

## NO PREDEFINED PRODUCTION LAYER DEMONSTRATES ROBUST INCREMENTAL INFORMATION

**0 survivors of 21 declared hypotheses** under Bonferroni, **0** under
Benjamini–Hochberg. Maximum headline |t| was **1.338**; under a block bootstrap
that does not assume cross-group independence, **1.957**. **Zero** cells reached
|t| ≥ 2 under either estimator, against **0.956** expected by chance.

| Layer | Classification |
|---|---|
| **A — bias alone** (baseline) | **INCONCLUSIVE** |
| **B — bias + H1 regime gate** | **NOT SUPPORTED** |
| **C — bias + displacement** | **NOT SUPPORTED** |
| **D — bias + structure confirmation** | **INCONCLUSIVE** |
| **E — bias + sweep** | **NOT SUPPORTED** |
| **F — bias + POI/FVG** | **NOT SUPPORTED** |
| **G — bias + session gate** | **NOT SUPPORTED** |
| **P — bias + L3 pullback** | **NOT SUPPORTED** |
| **H — bias + entry trigger** | **DESCRIPTIVE ONLY** (untestable) |
| **L7 confidence gate** | **DESCRIPTIVE ONLY** (untestable) |
| **L4 liquidity gate** | **DESCRIPTIVE ONLY** (not among the declared 21) |

Layers are **not ranked** and no "best component" is identified. No cost screen
was run, correctly — nothing survived the statistical screen.

Two findings are structural rather than statistical, and matter more than any
t-statistic in this report:

- **L6 POI does not score anything.** `poi_score` takes 9 distinct values across
  60,638 decisions and equals exactly **68.0 on 89.44%** of them. The threshold
  is 60 when L5 confirmed a sweep and 70 when it did not — and 68 sits between.
  So on those bars L6's verdict is **100%** determined by L5's. Overall the two
  gates agree on **94.38%** of decisions. L6 is a restatement, not a layer.
- **Structure "confirmation" cannot disagree with the bias.** Across 60,638
  sided decisions, `get_h1_structure` returned `HH/HL` for a BEARISH bias **0**
  times and `LH/LL` for a BULLISH bias **0** times. "Confirmed" means only "not
  BROKEN and not UNKNOWN".

**FINAL_OOS was not opened.** Token unchanged, split manifest unchanged, dataset
fingerprints unchanged, `baseline_008` unchanged, production code unchanged. All
ten pre-commit checks pass (§13).

---

## 0. What was frozen, and when

`research/production_path_spec.md`, committed at **`9692a3d`**. That commit
contains the specification and nothing else — no reconstruction script, no
results file, no report. Verified mechanically (check 7).

The spec froze **21 hypotheses**: 7 layers × 3 horizons. No hypothesis was added
after results were inspected; the count in the results file is 21.

### A naming collision worth stating plainly

The authorisation's layer list ran **A** bias alone, **B** H1 regime,
**C** displacement, **D** structure confirmation, **E** sweep, **F** POI/FVG,
**G** session gate, **H** entry trigger.

**The authorisation's H — the entry trigger — is untestable here**, because
`get_entry_trigger` requires M5 *and* M1, and M1 has **zero bars** in TRAIN and
zero in DEV. The frozen spec therefore used the letter H for the **L3 pullback**
layer, which the authorisation's list omits but which is a real production gate
that would otherwise have gone unexamined. This report labels it **P** and keeps
**H** for the entry trigger, classified DESCRIPTIVE ONLY.

So: the authorisation named 8 layers, one of which cannot be tested; this audit
tests 7 — the authorisation's B–G, plus the pullback layer. **L4 liquidity is in
neither list** and is reported descriptively only; it was not tested, because
adding a hypothesis after seeing results is exactly what the standard forbids.

---

## 1. Method — production was executed, not re-described

Every layer state comes from **calling the production function**. No rule was
reimplemented or vectorised.
`research/production_path_reconstruction.py` evaluates **every layer
unconditionally** at every eligible M15 bar — removing the short-circuit, so a
layer's behaviour is observable even where an earlier layer would have blocked.

**74,950 decisions reconstructed, 0 production-call failures (0.000%).**

### The bar windows matter, and this is where an earlier audit went wrong

Production does not compute indicators on full history. It passes
`DEFAULT_BAR_COUNTS` bars: **H4 100, H1 60, M15 50**. With 60 H1 bars,
`ta.ema(close, 50)` is seeded by a 50-bar SMA and advanced only ten steps, so the
seed still carries ~67% of the weight. A full-series EMA at the same calendar bar
has thousands of steps of decay behind it. These are not the same number.

**Phase 2's continuation audit computed the L1 bias from full-series EMAs**
(`research/original_continuation_audit.py:53-54`). Measured divergence from the
production 60-bar window, 400 probes inside the authorised window
(`research/production_path_window_fidelity.py`, seed 20260301):

| | |
|---|---|
| **bias label mismatches** | **52 / 400 = 13.0%** |
| of which outright sign flips (BULLISH↔BEARISH) | 1 |
| directional → NEUTRAL | 32 |
| NEUTRAL → directional | 19 |
| **bias strength mismatches** | **334 / 400 = 83.5%** |
| strength \|diff\| median / p90 / max (0–10 scale) | **0.608** / 1.878 / 5.731 |

**This correction reaches backwards.** Phase 2's conclusion was a null — every CI
straddled zero, max |t| 0.688 — and a population shift does not overturn a null.
But Phase 2's bias series was not the production bias series on roughly one bar
in eight, and its `bias_strength` tercile table was built on a quantity that
differs from production's on 83.5% of bars. Phase 3 does not inherit that: it
calls `get_fast_bias` on production's own 60-bar window, so the L1 state here
**is** the production L1 state by construction.

I could not re-examine Phase 2's verification script — it was a scratchpad file
and no longer exists — so I am not characterising what it compared. The measured
divergence above stands on its own.

### Harness controls — both PASS

| Control | Result |
|---|---|
| **Lookahead audit**, exhaustive over all **74,950** rows: the higher-timeframe bar each decision maps to must have *closed* at or before the M15 decision bar close | **0** H1 violations, **0** H4 violations |
| **Determinism**: a contiguous block of rows rebuilt from scratch, every cell compared | **0** mismatches (300 rows × 27 columns) |
| Panel max time ≤ DEV boundary | `2025-09-02 14:15` = boundary exactly |

Window causality is otherwise structural: every frame handed to a production
function is a prefix slice ending at the decision bar, and the only
forward-looking quantities in the panel are the `fwd_*` labels, which are never
inputs to a gate.

### Metric and test statistic

Direction-normalised forward return, identical to the continuation audit:
`+1 × (close[i+h] − close[i]) / ATR[i]` for BUY, `−1 × …` for SELL, at
h = 4 / 8 / 16 M15 bars. ATR is M15 ATR(14).

The headline for each cell is the **disjoint pass-vs-fail contrast inside the
bias population**, on non-overlapping observations. The spec's declared effect
size — excess over the bias-only population — is reported alongside. They carry
the same information and the same null:

```
mean(pass) − mean(all bias) = (1 − p) · [mean(pass) − mean(fail)],   p = pass rate
```

---

## 2. Data availability — what could not be tested, and why

Frozen in the spec **before** results:

| TF | available from | bars in TRAIN | bars in DEV |
|---|---|---|---|
| H4 | 2004-06-11 | 3,273 | 1,639 |
| H1 | 2009-08-31 | 12,511 | 6,256 |
| M15 | 2022-06-30 | 50,010 | 24,989 |
| **M5** | 2025-04-25 | **0** | 25,126 |
| **M1** | 2026-06-17 | **0** | **0** |
| **D1** | — | **absent from the dataset** | — |

1. **L8 entry trigger — UNTESTABLE.** Needs M5 *and* M1; M1 has zero bars in
   both arms.
2. **`detect_regime` — untestable in TRAIN** (no M5). Every regime-dependent gate
   goes with it: `bypass_l3`, `bypass_l6`, and the L7 threshold (55 MICRO_SCALP,
   else 70, raised to ≥75 on momentum fallback). **The L7 gate is DESCRIPTIVE
   ONLY**; the L7 *score* is computable and reported descriptively using the
   function's default regime.
3. **L4 runs degraded.** `daily_data=None` because D1 is absent, so previous-day
   extremes are missing from the pool set. Literal, declared, not identical to
   production.
4. **Displacement is evaluated on M15, not M5** — the same declared deviation as
   the continuation audit, forced by M5 having zero bars in TRAIN. The function
   body is timeframe-agnostic and unmodified; the input frame changed, no
   threshold did.

---

## 3. Implementation / documentation discrepancies

Recorded, **not fixed**. Items 1–4 were pre-named in the authorisation; 5–8 come
from earlier audits; **9–12 were observed in this phase**.

1. **`detect_choch` is not a textbook CHoCH implementation.**
2. **L6 inherits `side` from L1/L2 and does not independently validate
   direction** — it cannot contradict the bias. **Now quantified: see §9.**
3. **Breaker-block construction is not actually present** despite being
   referenced.
4. **Sweep implementation and documentation disagree.**
5. **`rr ≡ tp_ratio` tautology** — the RR gate compares a constant to itself.
6. **`h1_atr` in the L2 gate is a 14-bar mean of high−low, not a Wilder ATR**
   (`main_production.py:673-676`), so `8.0` is not on the scale the name implies.
7. **L2 BOS flip can change `side`** after L1 set it, so "bias direction" is not
   necessarily the trade direction. Not modelled here; disclosed as an unmodelled
   production behaviour.
8. **`compute_cvd_proxy` reads `tick.last` and `tick.volume`**, both measured at
   0% populated on this broker's XAUUSD feed.
9. **The published funnel merges two different L5 outcomes.**
   `baseline_008/layer_funnel.json` reports one `L5_SWEEP = 5,000`.
   `decisions.jsonl` separates them: **`L5_SWEEP` 3,064 + `L5_SWEEP_WAIT` 1,936
   = 5,000.** The published artifact cannot distinguish "no sweep" from "waiting
   for confirmation" — different statements about the market.
10. **All four signals record `confidence = 0.0` in the ledger while carrying
    `grade = "A"`.** L7 admits on `conf["final_score"] >= 55`, so the ledger's
    `confidence` field does not hold the score L7 gated on.
11. **The L1 bias depends on the 60-bar window** in a way documented nowhere, and
    differing from a full-history EMA on 13% of bars (§1). A property of the
    design, not a defect — but undocumented, and it has already caused one
    research error.
12. **The L2 `8.0` threshold is an absolute dollar amount on a non-stationary
    price series**, so its selectivity is a function of the gold price level
    rather than of market condition (§9).

---

## 4. The four historical trades — forensic only

`baseline_008`, frozen. **n = 4. No statistic is computed from these trades, no
threshold is derived from them, and they are not used as evidence for or against
any layer.**

A boundary note I am flagging rather than leaving to be discovered: these trades
fall in **2026-07-17 → 2026-08-28**, inside the *calendar* window later
designated FINAL_OOS (2025-09-02 → 2026-10-01). They are read from the
already-committed `baseline_008` artifacts, which derive from `data/raw` and were
frozen long before the split existed. **No FINAL_OOS arm of `data/research_v1`
was read, and `dataset_access` was not used to reach it.** (The spec said these
trades began 2026-06-02; the ledger's first *trade* is 2026-07-17, and 2026-06-24
is the first *decision* of the run. Corrected here rather than by editing the
frozen spec.)

| # | decision bar | side | regime | entry | grade | ledger `confidence` | exit | R | net |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-17 12:35 | SELL | MICRO_SCALP | MOMENTUM | A | 0.0 | STOP | −1.02 | −8.40 |
| 2 | 2026-08-06 07:55 | BUY | MICRO_SCALP | MOMENTUM | A | 0.0 | TARGET | +1.48 | +12.10 |
| 3 | 2026-08-12 09:20 | BUY | MICRO_SCALP | MOMENTUM | A | 0.0 | STOP | −0.07 | −0.57 |
| 4 | 2026-08-28 08:40 | SELL | MICRO_SCALP | MOMENTUM | A | 0.0 | TARGET | +1.48 | +12.90 |

**All four took an identical layer path:**

```
L1_BIAS  L2_STRUCTURE  L3_PULLBACK_BYPASSED  L4_LIQUIDITY
L5_SWEEP  L6_POI_BYPASSED  L7_CONFIDENCE  L8_ENTRY
```

Every one was MICRO_SCALP, every one used the MOMENTUM entry, and every one
**bypassed L3 and L6 through the regime flags**. No layer eliminated eligibility
for any of them — that is what made them signals.

**The documented eight-layer path has never produced a trade.** The only path
that ever produced one evaluated **six** of the eight layers.

### The funnel, for context

15,735 decisions, 2026-06-24 → 2026-09-16, first blocking layer only — which is
all the short-circuit records, and why the unconditional harness was necessary:

| blocked at | n | % |
|---|---|---|
| L3_PULLBACK | 5,044 | 32.06 |
| L5_SWEEP | 3,064 | 19.47 |
| L5_SWEEP_WAIT | 1,936 | 12.30 |
| L7_CONFIDENCE | 1,835 | 11.66 |
| L8_ENTRY | 1,585 | 10.07 |
| L1_BIAS | 1,505 | 9.56 |
| L4_LIQUIDITY | 748 | 4.75 |
| L2_STRUCTURE | 12 | 0.08 |
| L6_POI | 2 | 0.01 |
| **NONE (signal)** | **4** | **0.03** |

Regimes: MICRO_SCALP 7,314 (46.5%), REGIME_SCALP 6,492 (41.3%), INTRADAY_SWING
1,810 (11.5%), DEAD_CALM 119 (0.8%).

**L6_POI blocked 2 decisions out of 15,735** — 0.013%. §9 explains why that is
not an accident.

---

## 5. Neutral accounting

Reported **before** the directional analysis. Neutral observations are not
dropped from the denominator, and no inference is drawn that excluding them helps.

| | total | BULLISH | BEARISH | **NEUTRAL** |
|---|---|---|---|---|
| **All** | **74,950** | 34,127 (45.53%) | 26,511 (35.37%) | **14,312 (19.10%)** |
| TRAIN | 49,961 | 21,225 | 17,737 | **10,999 (22.02%)** |
| DEV | 24,989 | 12,902 | 8,774 | **3,313 (13.26%)** |

**L1 removes 19.1% of all eligible decisions as NEUTRAL** — those produce no
observation, which is the production mapping. Production-call failures: **0**.

The directional population is **60,638** sided decisions. Note the BULLISH:BEARISH
imbalance (1.29:1 overall, 1.47:1 in DEV) in a sample whose arms rose +33.6% and
+44.2%.

---

## 6. Results — the 21 declared tests

### Baseline: bias alone (reported, not a hypothesis)

| Hor | raw n | non-overlap n | overlap | mean (ATR) | se | t | 95% CI |
|---|---|---|---|---|---|---|---|
| 1h | 60,634 | **15,170** | **4.0×** | +0.0119 | 0.0124 | +0.96 | [−0.0124, +0.0361] |
| 2h | 60,630 | **7,672** | **7.9×** | +0.0272 | 0.0251 | +1.08 | [−0.0220, +0.0765] |
| 4h | 60,622 | **3,916** | **15.5×** | +0.0672 | 0.0506 | +1.33 | [−0.0319, **+0.1663**] |

All three point estimates are positive; none is significant; every interval
straddles zero. The 4h upper bound **+0.1663** sits just above the TRAIN
round-turn cost of **0.158 ATR** — which is why bias alone is **INCONCLUSIVE**
rather than NOT SUPPORTED, exactly as in the continuation audit.

### The 21 cells

`pass %` is of the 60,638 sided decisions. `diff` = mean(pass) − mean(fail),
non-overlapping. `excess` = mean(pass) − mean(bias-only), the spec's declared
effect size.

| Layer | Hor | pass % | raw n | non-ov n | overlap | mean pass | mean fail | diff | se | **t** | 95% CI | excess |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B. H1 regime | 1h | 18.95 | 11,490 | 2,874 | 4.0× | −0.0073 | +0.0159 | −0.0232 | 0.0295 | **−0.79** | [−0.0811, +0.0346] | −0.0192 |
| B | 2h | 18.95 | 11,486 | 1,500 | 7.7× | −0.0090 | +0.0342 | −0.0432 | 0.0591 | **−0.73** | [−0.1591, +0.0726] | −0.0363 |
| B | 4h | 18.95 | 11,478 | 807 | 14.2× | +0.0188 | +0.0860 | −0.0672 | 0.1152 | **−0.58** | [−0.2929, +0.1586] | −0.0483 |
| C. displacement | 1h | 16.11 | 9,768 | 6,701 | 1.5× | +0.0023 | +0.0141 | −0.0118 | 0.0224 | **−0.53** | [−0.0556, +0.0320] | −0.0095 |
| C | 2h | 16.11 | 9,768 | 4,671 | 2.1× | +0.0079 | +0.0316 | −0.0237 | 0.0400 | **−0.59** | [−0.1020, +0.0547] | −0.0194 |
| C | 4h | 16.11 | 9,765 | 2,955 | 3.3× | +0.0226 | +0.0763 | −0.0537 | 0.0785 | **−0.68** | [−0.2076, +0.1001] | −0.0446 |
| **D. structure** | 1h | 81.22 | 49,247 | 12,321 | 4.0× | +0.0174 | −0.0132 | **+0.0306** | 0.0321 | **+0.95** | [−0.0323, +0.0935] | +0.0055 |
| **D** | 2h | 81.22 | 49,243 | 6,472 | 7.6× | +0.0360 | −0.0085 | **+0.0445** | 0.0605 | **+0.74** | [−0.0741, +0.1631] | +0.0087 |
| **D** | 4h | 81.22 | 49,236 | 3,478 | 14.2× | +0.0999 | −0.0276 | **+0.1275** | 0.1062 | **+1.20** | [−0.0807, +0.3357] | +0.0327 |
| E. sweep | 1h | 26.78 | 16,237 | 5,902 | 2.8× | −0.0026 | +0.0206 | −0.0232 | 0.0249 | **−0.93** | [−0.0720, +0.0257] | −0.0144 |
| E | 2h | 26.78 | 16,236 | 3,802 | 4.3× | +0.0022 | +0.0364 | −0.0341 | 0.0453 | **−0.75** | [−0.1228, +0.0546] | −0.0250 |
| E | 4h | 26.78 | 16,230 | 2,525 | 6.4× | −0.0309 | +0.0793 | −0.1102 | 0.0844 | **−1.31** | [−0.2756, +0.0551] | −0.0981 |
| F. POI/FVG | 1h | 32.01 | 19,404 | 6,529 | 3.0× | −0.0048 | +0.0228 | −0.0277 | 0.0241 | **−1.15** | [−0.0748, +0.0195] | −0.0167 |
| F | 2h | 32.01 | 19,403 | 4,065 | 4.8× | +0.0117 | +0.0313 | −0.0197 | 0.0448 | **−0.44** | [−0.1074, +0.0681] | −0.0156 |
| F | 4h | 32.01 | 19,397 | 2,631 | 7.4× | −0.0471 | +0.0644 | −0.1115 | 0.0833 | **−1.34** | [−0.2748, +0.0519] | −0.1143 |
| G. session | 1h | 17.60 | 10,669 | 2,669 | 4.0× | +0.0092 | +0.0110 | −0.0018 | 0.0426 | **−0.04** | [−0.0853, +0.0817] | −0.0026 |
| G | 2h | 17.60 | 10,665 | 1,363 | 7.8× | +0.0124 | +0.0336 | −0.0212 | 0.0918 | **−0.23** | [−0.2011, +0.1588] | −0.0149 |
| G | 4h | 17.60 | 10,662 | 1,362 | 7.8× | +0.0733 | +0.0610 | +0.0122 | 0.1262 | **+0.10** | [−0.2351, +0.2596] | +0.0061 |
| P. L3 pullback | 1h | 31.18 | 18,905 | 6,954 | 2.7× | +0.0038 | +0.0161 | −0.0123 | 0.0228 | **−0.54** | [−0.0570, +0.0325] | −0.0080 |
| P | 2h | 31.18 | 18,902 | 4,366 | 4.3× | +0.0139 | +0.0296 | −0.0156 | 0.0428 | **−0.37** | [−0.0994, +0.0682] | −0.0133 |
| P | 4h | 31.18 | 18,902 | 2,745 | 6.9× | +0.0173 | +0.0714 | −0.0542 | 0.0817 | **−0.66** | [−0.2144, +0.1060] | −0.0499 |

**Every one of the 21 intervals straddles zero.** **17 of 21** point estimates
are negative — the layer's pass population moves *less* in the bias direction
than its fail population. Only **D** is positive at all three horizons.

### The independence problem, and a bootstrap that does not assume it

The analytic contrast pools two standard errors as if the samples were
independent. They are internally non-overlapping, but **their forward windows
overlap each other** — measured per cell, up to **99.97%**:

| cell | cross-group overlap | cell | cross-group overlap |
|---|---|---|---|
| B@1h | 0.31% | C@2h | **99.94%** |
| D@1h | 0.19% | C@4h | **99.97%** |
| G@1h | 0.86% | E@4h | **99.80%** |
| B@2h | 11.33% | H@4h | **99.85%** |
| D@2h | 15.99% | G@4h | **98.83%** |
| B@4h | 27.39% | H@2h | **98.44%** |
| D@4h | 39.19% | F@4h | **96.31%** |

Ignoring a positive covariance **overstates** the SE of a difference, so the
analytic t-statistics may be conservative. A moving-block bootstrap (blocks of
**96** and **480** M15 bars — 24 h and 1 week, both pre-stated, neither selected
on its result; 4,000 replicates; all observations) carries that dependence:

| cell | analytic t | boot t (96) | boot t (480) | | cell | analytic t | boot t (96) | boot t (480) |
|---|---|---|---|---|---|---|---|---|
| B@1h | −0.79 | −0.41 | −0.44 | | F@1h | −1.15 | −1.36 | −1.36 |
| B@2h | −0.73 | −0.19 | −0.20 | | F@2h | −0.44 | −0.57 | −0.54 |
| B@4h | −0.58 | **+0.16** | **+0.18** | | F@4h | −1.34 | **+0.17** | **+0.16** |
| C@1h | −0.53 | −0.72 | −0.72 | | G@1h | −0.04 | −0.20 | −0.21 |
| C@2h | −0.59 | −1.20 | −1.17 | | G@2h | −0.23 | −0.22 | −0.23 |
| C@4h | −0.68 | −1.14 | −1.12 | | G@4h | +0.10 | **−0.09** | **−0.08** |
| D@1h | +0.95 | **+1.72** | **+1.74** | | P@1h | −0.54 | −1.28 | −1.31 |
| D@2h | +0.74 | +1.66 | +1.72 | | P@2h | −0.37 | −1.87 | −1.94 |
| D@4h | +1.20 | +1.32 | +1.41 | | P@4h | −0.66 | −1.75 | **−1.96** |

As expected, bootstrap SEs are **smaller** and several |t| grow. The largest
across all 42 bootstrap estimates is **1.957** (P@4h, 1-week blocks).
**0 of 42 reach |t| ≥ 2.** The conclusion survives dropping the independence
assumption.

**Four cells change sign** between the two estimators (B@4h, E@4h, F@4h, G@4h).
The bootstrap point estimate uses all observations while the headline uses a
non-overlapping subsample, so these are different estimators of the same
quantity — and when an effect's *sign* is not stable across them, the effect is
noise. This is disclosed, not reconciled in favour of whichever reads better.

---

## 7. Multiple testing

| | |
|---|---|
| Pre-declared hypotheses | **21** |
| With a computable t | 21 |
| Nominal alpha | 0.05 |
| **Bonferroni threshold** | **\|t\| ≥ 3.038** |
| **Bonferroni survivors** | **0** |
| **Benjamini–Hochberg survivors** | **0** |
| Max headline \|t\| | **1.338** (F@4h) |
| Max bootstrap \|t\| | **1.957** (P@4h) |
| **Observed \|t\| ≥ 2** | **0** |
| **Expected \|t\| ≥ 2 under null** | **0.956** |

Zero exceedances where chance predicts about one. Not a marginal failure — the
strongest cell reaches 44% of the corrected threshold.

**13 of 24 cells carry `ESTIMATOR_SIGN_DISAGREEMENT`** between the raw and
equal-block statistics: C@1h, C@2h, C@4h, D@2h, D@4h, E@2h, E@4h, F@2h, F@4h,
G@1h, P@1h, P@2h, P@4h. None is a headline — the headline is non-overlapping
throughout. The flags are recorded, not suppressed. All 24 cells carry at least
one flag (mostly `HIGH_OVERLAP`).

---

## 8. Temporal robustness

**Not run — correctly.** The standard reserves it for layers that survive the
primary screen, and none did. The per-arm breakdown below is reported for
completeness and was **not used to select a period or a layer**.

| Layer | 1h TRAIN | 1h DEV | 2h TRAIN | 2h DEV | 4h TRAIN | 4h DEV |
|---|---|---|---|---|---|---|
| B. H1 regime | −0.095 (−1.64) | −0.024 (−0.59) | −0.166 (−1.39) | −0.053 (−0.66) | −0.332 (−1.39) | −0.069 (−0.44) |
| C. displacement | −0.018 (−0.63) | −0.001 (−0.02) | −0.048 (−0.94) | +0.019 (+0.30) | −0.059 (−0.59) | −0.045 (−0.36) |
| D. structure | +0.015 (+0.38) | +0.058 (+1.10) | +0.024 (+0.32) | +0.080 (+0.81) | +0.093 (+0.71) | +0.188 (+1.05) |
| E. sweep | −0.029 (−0.86) | −0.019 (−0.50) | −0.036 (−0.59) | −0.042 (−0.62) | −0.170 (−1.57) | −0.031 (−0.23) |
| F. POI/FVG | −0.032 (−0.98) | −0.029 (−0.79) | −0.017 (−0.28) | −0.042 (−0.61) | −0.149 (−1.40) | −0.081 (−0.60) |
| G. session | −0.035 (−0.62) | **+0.057 (+0.89)** | −0.087 (−0.71) | **+0.096 (+0.72)** | +0.024 (+0.14) | −0.010 (−0.05) |
| P. L3 pullback | +0.001 (+0.02) | −0.036 (−0.98) | −0.006 (−0.11) | −0.033 (−0.49) | −0.027 (−0.26) | −0.104 (−0.78)|

No |t| reaches 1.65 in any arm. **D keeps its sign in both arms at all three
horizons** — the only layer that does. **G flips sign between arms** at 1h and
2h. Nothing here is significant and nothing is selected.

---

## 9. Descriptive only

### L6 POI is a gate that restates L5

| | |
|---|---|
| distinct `poi_score` values across 60,638 decisions | **9** |
| `poi_score == 68.0` exactly | **54,232 = 89.44%** |
| next values: 78.0 / 88.0 / 58.0 / 100.0 | 8.95% / 1.15% / 0.24% / 0.17% |
| **within `poi_score == 68.0`, does L6 agree with L5?** | **100.00%** |
| overall L6 ≡ L5 agreement | **94.38%** |

The mechanism is arithmetic, not statistical. The L6 threshold is **60 if L5
confirmed a sweep, else 70**, and the score is **68** nine times in ten. So 68
passes whenever L5 passed and fails whenever it did not. Cross-tab:

| | L6 fail | L6 pass |
|---|---|---|
| **L5 fail** | 41,109 | 3,288 |
| **L5 pass** | 121 | **16,120** |

L6 carries information independent of L5 on about **5.6%** of decisions. This
explains the frozen funnel's `L6_POI = 2 / 15,735`: by the time L6 is reached,
L5 has already decided its answer.

### Structure confirmation cannot contradict the bias

| bias | HH/HL | LH/LL | BROKEN | UNKNOWN |
|---|---|---|---|---|
| BULLISH (34,127) | **28,460** | **0** | 3,611 | 2,056 |
| BEARISH (26,511) | **0** | **20,791** | 3,920 | 1,800 |

`get_h1_structure` takes the bias as an input and classifies relative to it.
Across 60,638 sided decisions it returned a structure contradicting the bias
**zero** times. "Structure confirms the bias" therefore means only "structure is
not BROKEN and not UNKNOWN" — which is true of **81.22%** of decisions.

### The H1 regime gate is a price-level gate, not a volatility gate

`h1_atr < 8.0` where `h1_atr` is a 14-bar mean of high−low, in dollars, on an
instrument that went from ~1,800 to ~4,600 over the record:

| period | median `h1_atr` | share of all bars below 8.0 | gate pass rate (sided) |
|---|---|---|---|
| **TRAIN** (2022-06→2024-08) | 4.40 | **94.33%** | **6.19%** |
| **DEV** (2024-08→2025-09) | 7.35 | 59.16% | **41.90%** |
| all sided | — | — | 18.96% |

And in the 2026 `baseline_008` run the dead-calm gate blocked **nothing at all**:
all 12 `L2_STRUCTURE` blocks carry the reason *"H1 structure is broken"*, and no
*"too calm"* reason appears anywhere in the frozen funnel — **0 of 15,735**.

The same unchanged constant rejects 94% of TRAIN decisions and **zero** 2026
decisions. Its selectivity is determined by the gold price level, not by whether
the market is calm.

### L5 admits without sweep quality

`sweep_quality == 0.0` on **87.41%** of sided decisions (7 distinct values).
Among decisions where L5 *passes*, the **median `sweep_quality` is 0.0** and the
mean is 2.15. L5's reasons: `WATCH` 32,008 (52.8%), `PASS` 16,241 (26.8%),
`NO_SWEEP` 12,389 (20.4%). Admission therefore comes largely via
`choch_confirmed`, consistent with discrepancy 1.

### L7 confidence — DESCRIPTIVE ONLY

The gate could not be evaluated (regime underivable; §2). The score, computed
with the function's default regime:

| p1 | p5 | p25 | **p50** | p75 | p95 | p99 |
|---|---|---|---|---|---|---|
| 16.66 | 19.15 | 28.28 | **35.69** | 44.64 | 60.60 | 71.35 |

Share reaching each production threshold: **≥55: 9.05%**, **≥70: 1.28%**,
**≥75: 0.48%**. Grades: REJECT 59,860, A 766, A+ 12.

### L4 liquidity — DESCRIPTIVE ONLY, not among the declared 21

`PASS` 34,285 (56.5%), `WATCH` 12,520 (20.6%), `BLOCK` 13,833 (22.8%).
Production blocks only on `BLOCK`. Running degraded (`daily_data=None`).

### L8 entry trigger and the regime gates — UNTESTABLE

`get_entry_trigger` requires M5 and M1; M1 has zero bars in both arms.
`detect_regime` requires M5, absent in TRAIN, so `bypass_l3`, `bypass_l6` and the
L7 threshold cannot be evaluated. **These are the two components the four
historical trades depended on most** — the entry trigger fired for all four, and
the regime bypass is what let all four skip L3 and L6. That they are precisely
the untestable components is the sharpest limitation of this audit.

---

## 10. Costs

**No cost screen was run.** No layer produced a positive incremental effect
surviving the corrected threshold, so the standard stops the analysis there.

Reference scale, for interpreting the power disclosure only: round turn =
**1 × spread**, measured median **$0.33** (ask = mid + S/2, bid = mid − S/2),
which is **0.158 ATR** in TRAIN and **0.093 ATR** in DEV.

---

## 11. The seven questions

**1. What exactly creates a production trade?**
Formally: all of L1–L8 pass in sequence, the daily cap of 4 is unmet, and the
regime admits the entry style; a single failure short-circuits the rest.
Empirically: in the only run that produced trades, all four took one identical
path — **MICRO_SCALP regime, L3 and L6 bypassed by regime flags, MOMENTUM
entry**. The realised generator is fast H1 EMA bias → H1 structure not broken →
*(pullback skipped)* → liquidity `PASS` → sweep/CHoCH → *(POI skipped)* →
confidence ≥ 55 → momentum trigger on M5/M1. **The documented eight-layer path
has never produced a trade.**

**2. Which layers actually filter the population?**
By volume, over 60,638 sided decisions: **L7 confidence** is by far the most
restrictive (only 9.05% reach even the lowest threshold of 55, 0.48% reach 75);
then **L5/L6** (26.8% / 32.0% pass), **L3 pullback** (31.2%), **L4** (22.8%
blocked), **C displacement** (16.1%), **G session** (17.6% — a fixed 4 of 24
hours, i.e. 16.7% by construction), and **B H1 regime** (18.95% overall, but
**6.19%** in TRAIN versus **41.90%** in DEV). **D structure** barely filters at all (81.2% pass).
L1 removes 19.1% as NEUTRAL before any of this.

**3. Does any predefined layer add measurable information beyond bias alone?**
**No.** 0 of 21 survive Bonferroni or BH. Max headline |t| 1.338, max bootstrap
|t| 1.957, zero cells at |t| ≥ 2 against 0.956 expected. 17 of 21 point estimates
are negative. The closest to an exception is **D structure confirmation** —
positive at all three horizons, sign-stable across both arms and both estimators,
bootstrap |t| up to 1.74 — which is why it is INCONCLUSIVE rather than NOT
SUPPORTED, not because it demonstrated anything.

**4. Are the four historical trades representative of anything?**
Descriptively: of MICRO_SCALP momentum entries with L3 and L6 bypassed, taken in
a 2026 volatility regime where the absolute $8 H1-ATR gate blocked **nothing**
(0 of 15,735, versus 94.33% of TRAIN bars below the threshold). Two reached
target, two stopped; R +1.48, +1.48, −1.02, −0.07. **n = 4. Nothing is
generalised from them and no statistic is computed from them.**

**5. Which production components are merely gates versus actual information
layers?**
On this evidence, **none of the seven behaved as an information layer**. Four are
demonstrably gates by construction, independent of any statistic:
- **L6 POI** — restates L5 on 94.4% of decisions, 100% where the score is its
  modal 68.0.
- **D structure confirmation** — cannot contradict the bias; 0 contradicting
  classifications in 60,638 decisions.
- **G session gate** — a clock: fixed UTC hours, |t| ≤ 0.23 analytic and ≤ 0.21
  bootstrap.
- **B H1 regime gate** — an absolute dollar threshold, so a price-level gate
  whose selectivity ranged from **6.19%** to **41.90%** pass across two adjacent
  periods, and which blocked **0** decisions in the 2026 production run.

**6. Which implementation/documentation discrepancies materially affect
interpretation?**
All twelve in §3. The three that most affect interpretation: the **L1 60-bar
window** (discrepancy 11), which makes a full-series vectorisation unfaithful and
already corrupted one earlier audit's population; the **L6 threshold/score
interaction** (2), which makes L6 non-independent by arithmetic; and the
**absolute $8 L2 threshold** (12), which makes one gate's behaviour a function of
the price era rather than of the market.

**7. Is there enough evidence to justify strategy redesign?**
That is a decision for separate authorisation, and I am not proposing one. What
the evidence supports, stated plainly: **the existing layer stack has not been
shown to earn its complexity.** No predefined layer adds measurable information
beyond bias alone; several cannot, by construction, contradict the bias they are
documented to confirm; and the two components the historical trades actually
depended on are untestable on this dataset. What the evidence does **not**
support is any particular replacement — Phase 1 found no robust conditional
structure across 84 cells, Phase 2 found the continuation premise NOT SUPPORTED,
and this phase adds no candidate. **Evidence that the current architecture is
unsupported is not evidence for a different one.**

---

## 12. Limitations

1. **The two most load-bearing components are untestable.** L8 entry trigger
   (M1: zero bars) and the regime bypasses (M5: zero bars in TRAIN) are exactly
   what the four historical trades relied on. This audit cannot speak to them.
2. **Power.** MDE at the Bonferroni threshold is **0.076 ATR (1h)**,
   **0.138 (2h)**, **0.256 (4h)**, against a round-turn cost of 0.158 ATR
   (TRAIN) / 0.093 (DEV). At 1h the scan was sensitive well below cost, so that
   null is informative. **At 4h it was not** — a cost-relevant 4h effect could
   hide below 0.256 ATR. The 4h results are the weakest in the report.
3. **L4 ran degraded.** D1 is absent from the dataset, so `daily_data=None` and
   previous-day extremes were missing from the pool set. L4's real behaviour may
   differ, and L4 was not among the declared hypotheses in any case.
4. **Displacement was evaluated on M15, not M5.** Declared in advance and forced
   by data availability, but displacement is a fast-timeframe concept and M15
   bars are coarser.
5. **The L2 BOS flip was not modelled.** Production can change `side` after L1
   sets it; this audit holds the L1 side fixed. Disclosed, not corrected.
6. **High overlap is intrinsic at 4h** (14–15× raw-to-non-overlapping), and
   cross-group overlap reaches 99.97%. The bootstrap addresses the independence
   assumption but cannot create independent observations that do not exist.
7. **No multi-year bear market** in the M15 sample. Both arms rose. Unchanged
   from earlier phases.
8. **The BULLISH:BEARISH imbalance** (1.29:1, and 1.47:1 in DEV) means the
   direction-normalised statistics are not side-balanced, in a rising sample.
9. **Only the production definitions were tested.** This is not a statement about
   whether some other displacement, sweep or POI definition would carry
   information.
10. **Phase 2's bias population was not production's** (§1). The null it reported
    is not overturned, but its `bias_strength` analysis in particular rested on a
    quantity differing from production's on 83.5% of bars.

---

## 13. Verification

Run by `research/production_path_verification.py`, which exits non-zero on any
failure. **10/10 PASS.**

| # | Check | Result |
|---|---|---|
| 1 | FINAL_OOS token unchanged | PASS — `OOS-AUTHORISATION-NOT-ISSUED` |
| 2 | FINAL_OOS inaccessible | PASS — `OOSLockedError` raised |
| 3 | Dataset fingerprints unchanged | PASS — 7 timeframes, 0 mismatches |
| 4 | Split manifest unchanged | PASS — git diff empty |
| 5 | `baseline_008` unchanged | PASS — git status clean |
| 6 | Production code unchanged | PASS — 11 files clean |
| 7 | `production_path_spec.md` predates results | PASS — `9692a3d` contains only the spec |
| 8 | Hypothesis count frozen at 21 before testing | PASS — spec declares 21, results declare 21 |
| 9 | Statistical guardrails pass | PASS — self-tests exit 0 |
| 10 | Working tree contains only research changes | PASS — nothing outside `research/` |

Plus the two harness controls in §1: **0** lookahead violations across all 74,950
rows, **0** determinism mismatches.

---

## Verdict

**NO PREDEFINED PRODUCTION LAYER DEMONSTRATES ROBUST INCREMENTAL INFORMATION.**

Stopping here, as the decision rule requires. FINAL_OOS not opened, no threshold
optimised, no combination searched, no layer ranked, no best component selected,
no strategy designed, no profitability claim made. Production and `baseline_008`
untouched.

The durable output of this phase is not a surviving layer. It is the observation
that three of the layers could not have been information layers whatever the
data said — L6 restates L5 by arithmetic, structure confirmation cannot
contradict the bias it confirms, and the session gate is a clock — together with
a reconstruction harness that calls production on production's own bar windows,
which is what made the earlier full-series error visible.

Strategy redesign requires separate authorisation.
