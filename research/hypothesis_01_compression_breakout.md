# Hypothesis 01 — COMPRESSION → RANGE BREAKOUT → EXPANSION

**This file is committed BEFORE any label or result is computed.** Git history is
the evidence: this commit contains the specification and nothing else — no
analysis script, no panel, no results file, no report. Nothing in it is derived
from an observed outcome.

Governing standards, both binding: `research/RESEARCH_TO_STRATEGY_GATE.md` and
`research/STATISTICAL_RESEARCH_CONTROLS.md`. This is a G0→G2 pre-registration
under that gate.

---

## 1. Economic hypothesis

When XAUUSD spends a sufficiently compressed period inside a narrow recent price
range, a subsequent genuine breakout beyond that range may produce directional
expansion in the breakout direction.

**The question tested:** does a genuine breakout following a pre-existing
compression regime produce positive directional-normalised forward returns?

**Mechanism claimed.** A compressed range concentrates resting orders just beyond
its boundaries — stops of positions taken inside the range, and breakout entries.
A move through a boundary executes that inventory, and the resulting
liquidity-taking flow is directional and must be absorbed by market makers who
widen and reprice rather than mean-revert immediately. The compression is what
makes the inventory concentrated: a boundary that has held for 12 bars has
accumulated more resting interest than one that has just formed.

**Direction of expected effect: POSITIVE**, signed in advance. `E[R_h] > 0`.

**This hypothesis is not assumed to be true.** It is equally interesting if the
mechanism is absent, and the most likely competing explanation is stated in §12.

### Architectural independence — binding

This hypothesis does **not** use, and must not be implemented with:
`fast_bias`, `bias_strength`, H1 production bias, CHoCH, sweep, POI, FVG, the
production session gate, the production entry trigger, or any production
threshold. **The breakout itself determines direction.** The previous production
architecture is a frozen historical control and is not consulted, compared
against, or repaired here.

---

## 2. Data boundaries

Primary structural timeframe: **M15**. Loaded only through
`research/dataset_access.py`.

| Arm | Window | M15 rows |
|---|---|---|
| **TRAIN** | 2022-06-30 07:00 → 2024-08-09 18:15 | 50,010 |
| **DEV** | 2024-08-11 → 2025-09-02 14:15 | 24,989 |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | **LOCKED** |

**FINAL_OOS remains LOCKED.** No M15, H1, M5, M1 or tick data from the FINAL_OOS
period is read, as data or as context of any kind. The M15 series is truncated at
the DEV upper boundary **before** any indicator is computed, and the truncation is
asserted in code. Dataset fingerprints
(`research/accessible_bar_dataset_fingerprints.json`,
`dataset_sha256 = 9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca`)
are verified at load.

**Purge/embargo: 16 M15 bars**, per the split manifest. An event is admitted for
horizon `h` only if bar `i+h` lies inside the **same arm** as bar `i`, so no
forward window spans two arms or the embargo gap. Event counts therefore differ
slightly across horizons and are reported per horizon.

---

## 3. The one causal ATR

A single quantity is used for the compression ratio, the breakout buffer, the
label normaliser and the dollar conversion:

```
A[i] = ATR_14[i-1]        Wilder ATR(14) on M15, evaluated at bar i-1
```

`A[i]` is a function of bars at or before `i-1` only. It therefore contains **no
information from bar `i`** and none from the forward window. Using one ATR
everywhere, rather than a different convention per quantity, is deliberate: it
removes a degree of freedom.

An event is **excluded** if `A[i]` is NaN or `A[i] <= 0`; exclusions are counted
and reported.

---

## 4. Compression definition

For each M15 bar `i`, the pre-breakout compression window is the **previous 12
completed M15 bars**. Bar `i` is **not** included.

```
range_12[i] = max(high[i-12 : i]) - min(low[i-12 : i])      # bars i-12 .. i-1
compression_ratio[i] = range_12[i] / A[i]
```

Python half-open slice semantics are intended and exact: `[i-12 : i]` is the 12
bars `i-12` through `i-1` inclusive, and excludes `i`.

**Compression condition:**

```
compressed[i]  ⟺  compression_ratio[i] <= THETA
```

`THETA` is the **20th percentile of `compression_ratio` over TRAIN only**,
computed over TRAIN bars where `compression_ratio` is finite, using
`numpy.percentile(..., 20, method="linear")`.

**THETA is frozen once computed.** It is recorded to full precision in
`hypothesis_01_results.json`. It is **not** recalculated on DEV. The percentile is
**not** optimised, and **no alternative percentile is tested** — the value 20 is
part of this pre-registered hypothesis.

`compression_ratio` is a feature-only quantity. Deriving THETA from TRAIN uses no
label information, and THETA is fixed before any label is computed.

---

## 5. Range definition

```
range_high[i] = max(high[i-12 : i])
range_low[i]  = min(low[i-12 : i])
```

Bar `i` is excluded. No future information enters the range.

---

## 6. Breakout definition

A breakout occurs on M15 bar `i` when:

```
LONG :  close[i] >  range_high[i] + 0.10 * A[i]
SHORT:  close[i] <  range_low[i]  - 0.10 * A[i]
```

The **0.10 ATR buffer is frozen**. It is not optimised and no alternative buffer
is tested.

```
direction = +1  if the upper boundary breaks
direction = -1  if the lower boundary breaks
```

No bias of any kind is consulted. The breakout determines direction.

**Ambiguity.** If both conditions hold on the same bar the event is **excluded and
counted**. (Since `range_low <= range_high` always, `range_low - 0.10·A <
range_high + 0.10·A`, so this should never occur; the check is implemented and its
count reported rather than assumed to be zero.)

---

## 7. One event per compression episode — exact deduplication rule

A deterministic single-pass state machine, run independently within each arm in
ascending time order:

```
armed = True                              at the first eligible bar of the arm

for each eligible bar i in ascending order:
    if armed and compressed[i] and (long_break[i] XOR short_break[i]):
        emit event at i
        armed = False
    else if not compressed[i]:
        armed = True
```

In words: **a new compression episode must be established before another event can
fire.** After an event, the series must first *leave* compression
(`compressed[j] == False` for some `j > i`) and then *re-enter* it before a
further breakout counts. Repeated bars continuing the same breakout cannot
produce a second event.

The re-arm test is evaluated on every bar, including bars that are themselves
breakouts, so a breakout bar that is not compressed re-arms the machine.

`armed` is reset to `True` at the start of each arm and **does not carry across
the TRAIN/DEV boundary**, so no state crosses the embargo gap.

Reported: events emitted, bars suppressed by the armed flag, ambiguous exclusions,
and invalid-ATR exclusions.

---

## 8. Primary labels

For each event at bar `i`:

```
R_h = direction * (close[i+h] - close[i]) / A[i]
```

Horizons, frozen: **1h = 4 M15 bars · 2h = 8 · 4h = 16**. No other horizon is
computed or reported.

### A declared coupling, and why it is adverse rather than favourable

The breakout condition reads `close[i]`, and the label subtracts `close[i]`.
**These share a price point**, which is the endpoint-coupling failure mode named
in the Research-to-Strategy Gate (§14.3 item 7). It is declared here rather than
discovered later.

It cannot be removed without abandoning the hypothesis: a breakout *is* a
statement about where price closed, and a forward return must start from the
price at which the condition became true. What can be done is to state its
direction in advance.

The selection picks bars where `close[i]` sits unusually high above a 12-bar range
(LONG) or unusually low below it (SHORT). Any mean reversion in the series then
makes `close[i+h] - close[i]` negative for LONG and positive for SHORT; after
multiplying by `direction`, **both contribute negatively to `R_h`**. The coupling
therefore biases the measured effect **against** the hypothesis. A positive result
would be obtained in spite of it, not because of it.

**Declared control, not a hypothesis.** A secondary label anchored one bar later
removes the shared term entirely:

```
R'_h = direction * (close[i+h] - open[i+1]) / A[i]
```

`open[i+1]` appears nowhere in the feature. `R'_h` is reported alongside `R_h` at
all three horizons as a **control**, contributes **0** to the hypothesis count,
and **cannot promote the candidate on its own**. If `R_h` and `R'_h` disagree in
sign, the coupling is material and that is reported as such. (`R'_h` is also the
more executable anchor, since `close[i]` is not tradable once bar `i` has closed —
but it is introduced here as a coupling control, not as an execution improvement.)

An event is admitted at horizon `h` only if `i+h` is within the same arm (§2).

---

## 9. Secondary path labels — diagnostic only

In ATR units, over the same three horizons, using bars `i+1 … i+h`:

```
LONG :  MFE_h = (max(high[i+1 : i+h+1]) - close[i]) / A[i]
        MAE_h = (min(low [i+1 : i+h+1]) - close[i]) / A[i]

SHORT:  MFE_h = (close[i] - min(low [i+1 : i+h+1])) / A[i]
        MAE_h = (close[i] - max(high[i+1 : i+h+1])) / A[i]
```

Sign convention: `MFE_h >= 0` is favourable excursion, `MAE_h <= 0` is adverse
excursion.

**These are diagnostics.** They are **not** converted into a stop or a target, and
**no stop or target is selected from them**. They contribute 0 hypotheses.

---

## 10. Baselines — all defined before results

The question is not "are breakout returns positive?" but **"does compression +
breakout contain information beyond simply observing a directional move?"**

**A — Unconditional forward return.** Mean of
`direction · (close[i+h] - close[i]) / A[i]` over all eligible bars in the arm,
**side-matched** to the event population: compute the long-side mean `m₊` (taking
`direction = +1` on every eligible bar) and the short-side mean `m₋`
(`direction = -1` on every eligible bar), then report
`p·m₊ + (1-p)·m₋` where `p` is the LONG fraction among the arm's non-overlapping
events. This removes the period's net drift at the event population's own side mix.

**B — Direction-balanced random-event baseline.** For each arm and horizon:
let `n` be the non-overlapping event count and `p` the LONG fraction. Repeat
**2,000** times with seed **20261002**: draw bars one at a time uniformly at
random from the arm's eligible set, rejecting any bar within `h` bars of an
already-drawn bar, until `n` bars are drawn (abandoning a replicate after 1,000
consecutive rejections); assign `direction = +1` to `round(n·p)` of them chosen at
random and `-1` to the rest; compute the mean `R_h`. Report the replicate
distribution's mean, SD and 2.5/97.5 percentiles, and the **empirical percentile
rank of the observed event mean** within it. This answers directly: is this better
than picking bars at random and calling them breakouts?

**C — Directional-movement baseline (the decisive comparison).** The population of
bars satisfying the **breakout condition of §6 but NOT the compression condition
of §4** (`compression_ratio[i] > THETA`), with the same deduplication machine, the
same labels and the same exclusions. Contrasting the two isolates the contribution
of **compression** from the contribution of **a directional move beyond a recent
range**.

Baseline C is a disjoint two-sample contrast, so per the gate it additionally
reports cross-group forward-window overlap and a moving-block bootstrap
re-estimate (blocks of **96** and **480** M15 bars, 4,000 replicates, declared
here and not selected on their result).

**Baselines A, B and C contribute 0 to the hypothesis count.** They are declared
comparisons, reported at every horizon, and **none can promote the candidate on
its own**: a candidate is promoted only by the primary tests of §13, and a primary
failure stops promotion regardless of any baseline comparison.

---

## 11. TRAIN / DEV protocol

**TRAIN** — estimate THETA (feature-only); evaluate the hypothesis.
**DEV** — apply the **frozen** TRAIN THETA. Do not refit the threshold. Do not
alter any definition.

Reported separately: **TRAIN**, **DEV**, and **TRAIN+DEV descriptive only**.

The compression *rate* in DEV will differ from 20% because THETA is a TRAIN
quantity applied to a different volatility era (median ATR $2.085 in TRAIN versus
$3.564 in DEV). This is expected, is reported, and is **not** corrected.

**To qualify, a candidate must show in BOTH TRAIN and DEV:**

1. the **same sign**;
2. an **economically meaningful magnitude** — defined in advance as a point
   estimate exceeding **1 × round-turn cost** in that arm's ATR units
   (**0.158 ATR** in TRAIN, **0.093 ATR** in DEV; §15);
3. statistical support consistent with the Research-to-Strategy Gate.

**A TRAIN-only result does not qualify.**

---

## 12. What would constitute evidence AGAINST the hypothesis

Stated before results, so the outcome cannot be reinterpreted:

- `E[R_h] <= 0` on the non-overlapping headline estimate;
- a 95% CI straddling zero after multiple-testing correction;
- the effect vanishing against **baseline C** — i.e. compression adds nothing
  beyond a directional move beyond a recent range;
- the observed mean falling inside the central mass of **baseline B** — i.e.
  indistinguishable from randomly chosen bars with matched sides;
- sign instability across the pre-specified temporal segments;
- `ESTIMATOR_SIGN_DISAGREEMENT` on a headline cell;
- `R_h` and `R'_h` disagreeing in sign (§8);
- **the competing explanation surviving instead**: that any positive result is
  drift, not expansion. The diagnostic is the LONG/SHORT split. A genuine
  breakout-expansion mechanism is **direction-neutral** — it should be positive on
  both the long and short side in a direction-normalised metric. An effect that is
  positive LONG and negative SHORT, in a sample whose arms rose +33.63% and
  +44.24%, is the signature of **drift**, and will be reported as drift rather
  than as support. This is exactly the shape that defeated the previous
  architecture's continuation claim.

### What would constitute an INCONCLUSIVE result

- a positive point estimate failing the corrected threshold, with a CI wide
  enough to contain an economically relevant effect — i.e. the test lacked power;
- fewer than **100 non-overlapping events** in a cell;
- support at some horizons but not others with no coherent pattern.

A positive point estimate that fails correction is **INCONCLUSIVE**, never
SUPPORTED.

---

## 13. Primary statistical test and frozen hypothesis count

**Pre-declared hypothesis count: 3.**

| # | Hypothesis | Test |
|---|---|---|
| 1 | `E[R_1h] > 0` | non-overlapping mean vs zero |
| 2 | `E[R_2h] > 0` | non-overlapping mean vs zero |
| 3 | `E[R_4h] > 0` | non-overlapping mean vs zero |

The headline statistic uses **NON-OVERLAPPING breakout events**, selected by the
deterministic greedy rule in `research/phase1_statistical_controls.py`
(`non_overlapping_indices`). Overlapping forward windows are **never** the
headline estimator.

Correction over the declared 3, computed from the declared count (not from the
number of cells that happen to yield a statistic; a cell with no computable
statistic is padded as a non-rejection):

- **Bonferroni** at nominal alpha 0.05;
- **Benjamini–Hochberg** at FDR 0.05.

**No horizon, compression window, breakout buffer or percentile threshold is added
after seeing results.** The primary arm for the corrected test is **TRAIN**, with
DEV as the replication requirement of §11; TRAIN+DEV pooled is descriptive only.

Reported for every cell, per the standing controls:

```
raw event count · non-overlapping event count · overlap ratio
mean · median · standard deviation · 95% confidence interval · headline t
weighting method (named explicitly)
raw statistics (overlapping) alongside, never as headline
block statistics as secondary diagnostics only
```

Controls run and reported: **estimator sign-disagreement check**,
**forward-window audit**, **causal reconstruction (prefix rebuild, deviation must
be exactly 0.0)**, **multiple-testing correction**. **No unweighted block mean is
used as headline evidence.**

---

## 14. Temporal stability — survivors only

Only for a candidate surviving the primary screen. Segments are **pre-specified
here**, by equal row count, and are not chosen after seeing results:

- **TRAIN → 4 segments** (Q1–Q4 by equal M15 row count);
- **DEV → 2 segments** (H1–H2 by equal M15 row count).

Reported per segment: `n`, mean, 95% CI, sign. Every period is **not** required to
be positive — the mechanism does not imply that — but **instability is reported
explicitly** and no favourable period is selected.

---

## 15. H1 regime context — survivors only

Only for a candidate surviving the primary screen, and purely contextual.

H1 regime is defined **independently of the production bias**, using only H1
information available **before** the breakout — the last H1 bar to have *closed*
at or before the close of M15 bar `i`:

```
z = (h1_close - h1_sma50) / h1_atr14            both at that H1 bar
```

Cutoffs are the **TRAIN terciles of z**, frozen: `BEARISH` below the lower
tercile, `BULLISH` above the upper, `NEUTRAL` between.

**H1 is never used to determine breakout direction.** No FINAL_OOS H1 data is
read.

---

## 16. Cost screen — only if the gross hypothesis survives

Runs **only** if the gross effect survives the statistical gate. Reporting costs
on a null invites reading the cost table as though the effect were real.

**Round-turn spread cost = 1 × spread**, measured median **$0.33**
(`ask = mid + S/2`, `bid = mid - S/2`). Slippage tested at fixed
**0, 0.25, 0.50, 1.00 × spread**, reported as a grid and **never optimised**.

Reported per arm and horizon: **gross mean ATR · cost ATR · net mean ATR · gross
mean dollars · net mean dollars**. Dollar figures are computed **per event** using
that event's own `A[i]` in dollars and then averaged, rather than applying a
single arm-median ATR.

No cost is optimised, no entry is optimised, and **no profitability claim is
made**. This is an economic feasibility test only.

---

## 17. Power check

Computed from the **actual non-overlapping sample size**, and reported before any
null is interpreted:

- **MDE at 2 SE**;
- **MDE at the declared multiple-testing threshold** (Bonferroni over 3).

**If the test cannot detect an economically meaningful effect** — one at least
equal to the round-turn cost in that arm's ATR units — the result is classified
**UNTESTABLE / INCONCLUSIVE** rather than reported as absence of the effect. A
null will be stated as "no effect larger than X ATR", never as "no effect".

---

## 18. No feature mining — binding

Nothing outside the definitions above is searched, computed as a candidate, or
reported as a finding. Specifically **not** searched: RSI, MACD, EMA combinations,
Bollinger Bands, additional ATR ratios, candlestick patterns, session
combinations, alternative lookback windows, alternative breakout buffers,
alternative percentile thresholds.

**If the hypothesis fails, the failure is recorded.** The hypothesis is not
mutated until it passes. Any change to §4–§8 constitutes a new hypothesis
requiring a new pre-registration, and it inherits the accumulated
multiple-testing burden of every version attempted.

---

## 19. Decision rule

| Outcome | Classification |
|---|---|
| Fails the corrected statistical test | **HYPOTHESIS 01 — NOT SUPPORTED**, stop |
| Positive point estimate, insufficient power | **HYPOTHESIS 01 — INCONCLUSIVE / UNDERPOWERED**, stop |
| Survives in TRAIN, replicates in DEV, economically meaningful after the pre-registered cost screen | **HYPOTHESIS 01 — SURVIVES RESEARCH GATE** |

In every case: **FINAL_OOS is NOT opened**, and **no strategy is designed**.
Strategy design requires separate architecture authorisation.

---

## 20. Outputs

`research/hypothesis_01_compression_breakout.py` ·
`research/HYPOTHESIS_01_REPORT.md` · `research/hypothesis_01_results.json` ·
`research/hypothesis_01_controls.json`

Each report carries: dataset fingerprints, exact TRAIN/DEV boundaries, the exact
frozen THETA, the exact compression and breakout definitions, the event
deduplication rule, sample counts, overlap ratios, raw and non-overlapping
statistics, baselines, multiple-testing results, power analysis, temporal
stability, regime results if reached, cost results if reached, and limitations.

## 21. Verification before the results commit

1. this specification committed **before** results; 2. FINAL_OOS token unchanged;
3. FINAL_OOS inaccessible; 4. dataset fingerprints unchanged; 5. split manifest
unchanged; 6. `baseline_008` unchanged; 7. production unchanged; 8. statistical
controls pass; 9. **no alternative hypothesis was tested**; 10. working tree
contains only intended research files.
