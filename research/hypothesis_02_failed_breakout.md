# Hypothesis 02 — FAILED BREAKOUT → RANGE RE-ENTRY → REVERSAL

**This file is committed BEFORE any label or result is computed.** Git history is
the evidence: this commit contains the specification and nothing else — no
analysis script, no panel, no results file, no report.

Governing standards, both binding: `research/RESEARCH_TO_STRATEGY_GATE.md` and
`research/STATISTICAL_RESEARCH_CONTROLS.md`. This is a G0→G2 pre-registration.

**Hypothesis 01 is CLOSED — NOT SUPPORTED** (`research/HYPOTHESIS_01_REPORT.md`,
results at `45223cd`). This is not a variant of it. Hypothesis 01 tested whether a
breakout continues; this tests whether a breakout that **fails** reverses. The two
make opposite directional claims about overlapping but distinct event populations,
and this specification is not a relaxation of the one that failed.

---

## 1. Economic hypothesis

After XAUUSD experiences a compressed range and breaks one boundary, the first
boundary break does not necessarily establish directional acceptance. If price
subsequently re-enters the prior compressed range, that failed breakout may
contain information about subsequent movement toward the **opposite** side of the
prior range.

```
compression → boundary breakout → failed acceptance / range re-entry
            → subsequent movement OPPOSITE the initial breakout
```

**Mechanism claimed.** A breakout attracts two kinds of participant: breakout
entries in the breakout direction, and stop orders from positions held inside the
range. If the move through the boundary does not attract continuation flow, those
breakout entries are left holding an unprofitable position whose stop sits back
inside the range. Price re-entering the range triggers that inventory in the
*opposite* direction, and the resulting flow is directional. The compression is
what makes the trapped inventory concentrated; the re-entry is what identifies
that acceptance failed, and does so **without** needing to observe the subsequent
move.

**Direction of expected effect: POSITIVE** in the reversal direction, signed in
advance. `E[R_h] > 0`.

This is **not** the old `bias → displacement → continuation` architecture. It is
not assumed to be true, and §12 states in advance what would refute it.

### Architectural independence — binding

Not used, not imported, not consulted: `fast_bias`, `bias_strength`, H1 production
bias, `CHoCH`, production sweep, POI, FVG, production session gate, production
entry trigger, any production threshold. **The breakout itself establishes the
initial direction**, and the reversal direction is its negation.

---

## 2. Data boundaries

Primary structural timeframe **M15**, loaded only through
`research/dataset_access.py`.

| Arm | Window | M15 rows |
|---|---|---|
| **TRAIN** | 2022-06-30 07:00 → 2024-08-09 18:15 | 50,010 |
| **DEV** | 2024-08-11 → 2025-09-02 14:15 | 24,989 |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | **LOCKED** |

**FINAL_OOS remains completely locked.** No M15, H1, M5, M1 or tick data from the
FINAL_OOS period is read, as data or as context. The M15 series is truncated at
the DEV upper boundary **before** any indicator is computed, and the truncation is
asserted in code. Dataset fingerprints
(`dataset_sha256 = 9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca`)
are verified at load.

**H1 is used only if the candidate survives the primary statistical gate**, and
then only as contextual robustness (§16). No FINAL_OOS H1 data under any
circumstance.

**Purge/embargo: 16 M15 bars.** An event is admitted for horizon `h` only if the
label bar lies inside the **same arm** as the event, so no forward window spans
two arms or the embargo gap. Event counts therefore differ slightly across
horizons and are reported per horizon.

---

## 3. The two causal ATR instances

Two distinct instances are used, each as the authorisation specifies. Both are
Wilder `ATR(14)` on M15; they differ only in where they are evaluated.

```
A_i = ATR_14[i-1]      at the bar before the INITIAL BREAKOUT bar i
                       -> compression ratio, breakout buffer

A_j = ATR_14[j-1]      at the bar before the RE-ENTRY bar j
                       -> label normaliser
```

`A_i` is a function of bars at or before `i-1`; `A_j` of bars at or before `j-1`.
Neither contains information from its own anchor bar or from any forward window.

**These are deliberately different quantities and are not interchanged.** `A_i`
scales the compression and breakout definitions inherited from Hypothesis 01;
`A_j` scales the label, which begins at `j`. Recording this here prevents a later
substitution being made silently.

An event is **excluded** if `A_i` or `A_j` is NaN or `<= 0`; exclusions are
counted and reported.

---

## 4. Compression — the exact frozen definition from Hypothesis 01

Unchanged, previous 12 completed M15 bars, bar `i` excluded:

```
range_12[i] = max(high[i-12 : i]) - min(low[i-12 : i])      # bars i-12 .. i-1
compression_ratio[i] = range_12[i] / A_i
compressed[i]  ⟺  compression_ratio[i] <= THETA
```

`THETA` is the **20th percentile of `compression_ratio` over TRAIN only**,
computed over TRAIN bars where `compression_ratio` is finite, via
`numpy.percentile(..., 20, method="linear")`.

**The definition and the data are identical to Hypothesis 01, so THETA must
reproduce its published value:**

```
THETA = 2.4579083398        (Hypothesis 01, results committed at 45223cd)
```

The script recomputes THETA from TRAIN and **asserts agreement with this
inherited value to within 1e-12 relative**. A mismatch means the definition
drifted and is a hard failure, not a finding. This is a consistency check on an
inherited constant, not a new estimate.

THETA is not recalculated on DEV, not optimised, and **no alternative percentile
is tested**.

---

## 5. Prior range

For breakout bar `i`, the breakout bar itself excluded:

```
range_high[i] = max(high[i-12 : i])
range_low[i]  = min(low[i-12 : i])
```

---

## 6. Initial breakout

```
LONG :  close[i] >  range_high[i] + 0.10 * A_i
SHORT:  close[i] <  range_low[i]  - 0.10 * A_i
```

The **0.10 ATR buffer is frozen**, not optimised, no alternative tested. Initial
direction `d = +1` (LONG) or `d = -1` (SHORT).

**Ambiguity.** If both conditions hold on the same bar, the breakout is
**excluded and counted**. (Since `range_low <= range_high`, this cannot occur; the
check is implemented and its count reported rather than assumed.) The re-entry
test of §7 is one-sided by construction and therefore cannot be ambiguous.

---

## 7. Failed breakout / range re-entry

A failed breakout occurs **only after a valid initial breakout**. The failure
window is the **next 4 M15 bars**, `j ∈ {i+1, i+2, i+3, i+4}`:

```
initial LONG  (d = +1):   re-entry at the first j with  close[j] <= range_high[i]
initial SHORT (d = -1):   re-entry at the first j with  close[j] >= range_low[i]
```

**The first qualifying bar is the event timestamp.** The event is recorded at `j`.

If no qualifying `j` exists in the window, the breakout **did not fail** and the
episode enters the successful-breakout population (baselines B and C, §11).

### Causality of the failure classification — binding

The classification uses only `close[j]` and `range_high[i]` / `range_low[i]`,
which are functions of bars `i-12 … i-1`. It is therefore **fully knowable at the
close of bar `j`**.

**No information after the re-entry bar defines whether the event occurred.** No
future maximum or minimum is used. No forward excursion is used. Ambiguity is
never resolved using future data.

---

## 8. Opposite-direction label

```
reversal_direction  r = -d        LONG breakout  -> expect SHORT
                                  SHORT breakout -> expect LONG

R_h = r * (close[j+h] - close[j]) / A_j
```

Horizons, frozen: **1h = 4 M15 bars · 2h = 8 · 4h = 16**. No other horizon is
computed or reported.

An event is admitted at horizon `h` only if `j+h` is within the same arm (§2).

### A declared coupling, and its direction

The re-entry condition reads `close[j]`, and the label subtracts `close[j]`.
**These share a price point** — the endpoint-coupling failure mode named in the
Research-to-Strategy Gate. Declared here rather than discovered later.

It cannot be removed without abandoning the hypothesis: the re-entry *is* a
statement about where price closed, and the forward return must start from there.
Its direction can be stated in advance.

For an initial LONG breakout, re-entry selects `close[j] <= range_high`, i.e.
`close[j]` is bounded **above** — selected low relative to where price just was.
The label is `r·(close[j+h] − close[j]) = −(close[j+h] − close[j]) = close[j] −
close[j+h]`. Any mean reversion then raises `close[j+h]` above `close[j]` and
makes the label **negative**. The mirror argument holds for an initial SHORT
breakout. **The coupling is adverse to the hypothesis on both sides**, so a
positive result would be obtained in spite of it.

**Declared control, 0 hypotheses.** A label re-anchored one bar later removes the
shared term entirely, since `open[j+1]` appears nowhere in the event definition:

```
R'_h = r * (close[j+h] - open[j+1]) / A_j
```

`R'_h` is reported alongside `R_h` at all three horizons as a **control**. It
contributes **0** to the hypothesis count and **cannot promote the candidate**. If
`R_h` and `R'_h` disagree in sign, the coupling is material and that is reported.

---

## 9. Secondary range-target diagnostics — descriptive only

The **opposite range boundary** is the one the reversal moves toward:

```
initial LONG  breakout -> opposite boundary = range_low[i]
initial SHORT breakout -> opposite boundary = range_high[i]
```

Measured over the **16 M15 bars following `j`** (the longest primary horizon),
using bars `j+1 … j+16`. Reported:

- **fraction reaching** the opposite boundary within 4, 8 and 16 bars;
- **fraction not reaching** it within 16 bars;
- **time-to-opposite-boundary** in M15 bars — median and quartiles among those
  that reach it.

"Reaching" means the bar's `low <= range_low` (reversal SHORT) or
`high >= range_high` (reversal LONG), i.e. touched intrabar.

**This is descriptive mechanism evidence only.** It is **not** turned into an
optimised target, and **no stop or target is chosen** from it. It contributes 0
hypotheses.

---

## 10. Event deduplication — exact rule

A deterministic single-pass state machine, run independently within each arm in
ascending time order. It is the Hypothesis 01 machine with the re-entry search
appended:

```
armed = True                              at the first eligible bar of the arm

for each eligible bar i in ascending order:
    if armed and compressed[i] and (long_break[i] XOR short_break[i]):
        d = +1 if long_break[i] else -1
        search j over {i+1, i+2, i+3, i+4} for the FIRST re-entry:
              d = +1 :  close[j] <= range_high[i]
              d = -1 :  close[j] >= range_low[i]
        if found : record ONE failed-breakout event at j
        else     : record ONE successful breakout, anchored per section 11
        armed = False                     # the episode is consumed either way
    if not compressed[i]:
        armed = True
```

In words: **one initial breakout can produce only one failed-breakout event**, and
**a new event requires a genuinely new compression episode** — the series must
*leave* compression and *re-enter* it before another breakout counts. Subsequent
bars of the same episode are ignored.

The episode is consumed whether or not the breakout failed, so the failed and
successful populations are **disjoint and jointly exhaustive** over initial
breakouts — which is what makes baseline C a clean contrast.

`armed` resets to `True` at the start of each arm and **does not carry across the
TRAIN/DEV boundary**. A breakout is only admitted if its whole failure window
`i+1 … i+4` lies within the same arm.

Reported: initial breakouts, failed events, successful breakouts, bars suppressed
by the armed flag, ambiguous exclusions, invalid-ATR exclusions.

---

## 11. Baselines — all defined before results

The key question: **does range re-entry contain information beyond simply
observing a breakout?**

**A — Unconditional forward return in the reversal direction.** Over all eligible
bars in the arm, compute the long-side mean `m₊` (taking `r = +1` everywhere) and
the short-side mean `m₋` (`r = −1` everywhere) using the same `ATR[·-1]`
normalising convention, then report `q·m₊ + (1−q)·m₋`, where `q` is the fraction
of non-overlapping events whose **reversal** direction is LONG. This removes the
period's net drift at the event population's own side mix.

> Note stated in advance: because roughly half of breakouts are upward, the
> reversal population will be roughly half short. In a sample whose arms rose
> +33.63% and +44.24%, **drift is adverse to this hypothesis** — the opposite of
> the situation in Hypothesis 01. Baseline A quantifies that rather than leaving
> it to interpretation.

**B — Initial breakouts that did NOT fail.** The disjoint complement from §10.
Anchoring must be comparable, so it is declared explicitly: a successful breakout
is anchored at **bar `i+4`**, the first bar at which non-failure is known, with
normaliser `ATR[i+3]`, and labelled in the **same reversal direction** `r = −d`:

```
R_h(successful) = r * (close[i+4+h] - close[i+4]) / ATR[i+3]
```

Both populations are therefore anchored at the moment their classification became
knowable, labelled in the same direction, and normalised by the ATR one bar before
their own anchor. Anchoring successful breakouts at `i` instead would confound the
comparison with a timing difference of up to four bars, so it is not used.

**C — The incremental contrast: failed versus successful.** The explicit
difference `mean(failed) − mean(successful)` at each horizon, on non-overlapping
events, with its standard error, t and 95% interval. Per the gate, because this is
a disjoint two-sample contrast it **additionally** reports cross-group
forward-window overlap and a moving-block bootstrap re-estimate (blocks of **96**
and **480** M15 bars, 4,000 replicates, declared here and not selected on their
result).

**Baselines A, B and C contribute 0 to the hypothesis count.** None can promote
the candidate: promotion comes only from the primary tests of §13, and a primary
failure stops promotion regardless.

> **Binding interpretive rule:** a positive failed-breakout mean is **not** called
> an edge without the baseline comparison. If the failed population is positive
> but not distinguishable from the successful population, the conclusion is that
> **re-entry carries no incremental information**, whatever the raw mean.

---

## 12. What would constitute evidence AGAINST the hypothesis

Stated before results, so the outcome cannot be reinterpreted:

- `E[R_h] <= 0` on the non-overlapping headline estimate;
- a 95% CI straddling zero after multiple-testing correction;
- **TRAIN and DEV disagreeing in sign** — explicitly NOT SUPPORTED per §20;
- the effect vanishing against **baseline C**, i.e. re-entry adds nothing beyond
  observing a breakout;
- sign instability across the pre-specified temporal segments;
- `ESTIMATOR_SIGN_DISAGREEMENT` on a headline cell;
- `R_h` and `R'_h` disagreeing in sign (§8);
- **the competing explanation surviving instead.** A genuine
  trapped-inventory mechanism is **direction-neutral**: it should be positive both
  when reversing a failed upside breakout and when reversing a failed downside
  one. The LONG/SHORT split of the reversal direction is therefore reported for
  every cell. An effect present on only one side is reported as **drift or
  one-sided market asymmetry, not as support** — this is the diagnostic that
  defeated both the original continuation claim and Hypothesis 01.

### What would constitute an INCONCLUSIVE result

- a positive point estimate failing the corrected threshold, with a CI wide enough
  to contain an economically relevant effect — i.e. the test lacked power;
- fewer than **100 non-overlapping events** in a cell;
- support at some horizons but not others with no coherent pattern.

A positive point estimate that fails correction is **INCONCLUSIVE**, never
SUPPORTED.

> **Power is expected to be the binding constraint and is flagged now, not later.**
> Hypothesis 01 recorded 1,052 initial breakouts in TRAIN and 531 in DEV
> (`45223cd`). The failed subset is necessarily smaller, so non-overlapping counts
> will be lower than Hypothesis 01's and the minimum detectable effect
> correspondingly larger. §14 reports this explicitly, and a null that cannot
> exclude a cost-sized effect will be classified INCONCLUSIVE / UNDERPOWERED
> rather than as absence of the effect.

---

## 13. Primary statistical test and frozen hypothesis count

**Pre-declared hypothesis count: 3.**

| # | Hypothesis | Test |
|---|---|---|
| 1 | `E[R_1h] > 0` | non-overlapping mean vs zero |
| 2 | `E[R_2h] > 0` | non-overlapping mean vs zero |
| 3 | `E[R_4h] > 0` | non-overlapping mean vs zero |

Headline inference uses **NON-OVERLAPPING events**, selected by the deterministic
greedy rule in `research/phase1_statistical_controls.py`. Overlapping forward
windows are **never** the headline estimator.

Reported for every cell: **raw n · non-overlapping n · overlap ratio · mean ·
median · standard deviation · 95% CI · headline t**, with the weighting method
named explicitly, raw (overlapping) statistics alongside, and block statistics as
secondary diagnostics only. **No unweighted block mean is used as headline
evidence.**

Also run and reported: **estimator-sign-disagreement check**, **forward-window
audit**, **causal reconstruction** (§14), **multiple-testing correction**.

Correction over the declared 3, computed from the **declared** count — a cell with
no computable statistic is padded as a non-rejection rather than dropped:

- **Bonferroni** at nominal alpha 0.05;
- **Benjamini–Hochberg** at FDR 0.05.

Primary arm for the corrected test is **TRAIN**; DEV is the replication
requirement of §15; TRAIN+DEV pooled is descriptive only.

**No test is added after results are observed.** No alternative compression
window, percentile threshold, breakout buffer, failure window or horizon.

---

## 14. Causal reconstruction standard — tolerance frozen BEFORE results

Hypothesis 01's prefix reconstruction produced a 6.66e-16 deviation arising
solely from floating-point behaviour in the recursive Wilder EWM, against a
pre-declared standard of "exactly 0.0". That standard was wrong for a recursive
estimator. The standard here is **causal information equivalence within an
explicitly defined numerical tolerance**, frozen below.

**The tolerances are derived from float64 precision alone. None is chosen from an
observed market difference, and none may be revised after results.**

| Quantity | Frozen tolerance | Justification — numerical, not empirical |
|---|---|---|
| `range_high`, `range_low` | **exactly 0.0** (bitwise) | `max`/`min` select one of 12 identical float64 inputs. No arithmetic is performed, so no rounding can occur. |
| `ATR_14` | **relative 1e-12** | Wilder's recursion `A_t = A_{t-1}·13/14 + TR_t/14` is **contracting**: a perturbation decays by 13/14 each step, so float64 error reaches a steady state of order `eps/(1−13/14) = 14·eps ≈ 3.1e-15`, not `n·eps`. 1e-12 is ≈320× that bound, giving ample margin for the EWM implementation's internal ordering, while remaining ~4 orders of magnitude below any economically meaningful ATR difference (≈1e-4 relative). |
| `compression_ratio` | **relative 1e-12** | `range_12` is exact; the ratio inherits only ATR's relative error. |
| `compressed` classification | **0 disagreements** | boolean |
| `breakout` classification | **0 disagreements** | boolean |
| `re-entry` classification | **0 disagreements** | boolean |

**Boolean standard.** The three classifications must agree **exactly**. If any
disagreement occurs it is a **FAIL**, unless it is demonstrated that the
comparison margin at that bar was itself below the frozen numerical tolerance — a
genuine threshold tie — in which case the count and each margin are reported and
the cell is excluded. Any discrepancy with a margin **above** tolerance is a
**FAIL** of the whole analysis.

**Method.** For a pre-declared sample of events, every quantity is recomputed from
`m15.iloc[:k]` — bars `0 … k-1` only — and compared with the panel value at `k`,
for `k = i` (breakout quantities) and `k = j` (label normaliser). The probe count
is frozen at **60 events**, drawn with seed **20261003**.

---

## 15. TRAIN / DEV protocol

**TRAIN** — derive THETA (feature-only, and asserted against the inherited value);
test the hypothesis. **DEV** — apply the **frozen** TRAIN THETA. Do not refit.

Not modified, in either arm: the **12-bar window**, the **20th percentile**, the
**0.10 ATR breakout buffer**, the **4-bar failure window**.

Reported separately: **TRAIN**, **DEV**, **TRAIN+DEV descriptive only**.

**To qualify, a candidate must demonstrate in BOTH arms:**

1. the **same directional sign**;
2. **meaningful magnitude** — declared in advance as a point estimate exceeding
   **1 × round-turn cost** in that arm's ATR units (**0.158 ATR** TRAIN,
   **0.093 ATR** DEV);
3. statistical support consistent with the Research-to-Strategy Gate.

**If TRAIN and DEV disagree in sign, the candidate does not survive.**

---

## 16. Power gate

Computed from the **actual non-overlapping event count**, and reported **before**
any null is interpreted:

- **MDE at 2 SE**;
- **MDE at the declared multiple-testing threshold** (Bonferroni over 3);
- both compared against the **measured round-turn spread cost**.

**A null may not be claimed to exclude effects smaller than the measured
sensitivity.** Every null is stated as "no effect larger than X ATR". If the test
cannot detect an economically meaningful effect, the classification is
**INCONCLUSIVE / UNDERPOWERED**, not absence of the effect.

---

## 17. Temporal robustness — survivors only

Only if the primary candidate survives. Segments **pre-specified here**, by equal
M15 row count, never chosen after results: **TRAIN → 4 segments**,
**DEV → 2 segments**. Reported per segment: `n`, mean, 95% CI, sign. Instability
is reported explicitly; no favourable period is selected.

---

## 18. H1 regime robustness — survivors only

Only if the primary candidate survives. H1 regime is defined **independently of
the production bias**, from the last H1 bar to have *closed* at or before the
close of the event bar `j`:

```
z = (h1_close - h1_sma50) / h1_atr14
```

Cutoffs are the **TRAIN terciles of z**, frozen: `BEARISH` below the lower
tercile, `BULLISH` above the upper, `NEUTRAL` between.

**H1 does not determine trade direction.** **FINAL_OOS H1 data is forbidden.**

---

## 19. Cost screen — only if the candidate survives

Round-turn spread cost = **1 × spread**, measured median **$0.33**
(`ask = mid + S/2`, `bid = mid − S/2`). Fixed slippage tested at
**0, 0.25, 0.50, 1.00 × spread**, reported as a grid and never optimised.

Reported per arm and horizon: **gross ATR · cost ATR · net ATR · gross dollars ·
net dollars**. Dollar figures are computed **per event** using that event's own
`A_j` in dollars, then averaged.

**No execution optimisation. No strategy construction. No profitability claim.**

---

## 20. No feature mining — binding

Nothing outside the definitions above is searched, computed as a candidate, or
reported as a finding. Specifically **not** searched: RSI, MACD, EMA combinations,
alternative ATR formulas, alternative range windows, alternative failure windows,
alternative breakout buffers, session filters, candlestick patterns, additional
indicators.

**If Hypothesis 02 fails, the failure is recorded.** It is not mutated until it
passes. Any change to §4–§10 constitutes a new hypothesis requiring a new
pre-registration, inheriting the accumulated multiple-testing burden of every
version attempted.

---

## 21. Decision rule

| Outcome | Classification |
|---|---|
| Fails statistical validation | **HYPOTHESIS 02 — NOT SUPPORTED**, stop |
| Positive point estimate, underpowered | **HYPOTHESIS 02 — INCONCLUSIVE / UNDERPOWERED**, stop |
| **TRAIN positive but DEV negative** | **HYPOTHESIS 02 — NOT SUPPORTED**, stop |
| Survives TRAIN + DEV + statistical controls, economically meaningful after the pre-registered cost screen | **HYPOTHESIS 02 — SURVIVES RESEARCH GATE** |

In every case: **FINAL_OOS is NOT opened**, and **no complete strategy is
designed**. Strategy design requires separate authorisation.

---

## 22. Outputs

`research/hypothesis_02_failed_breakout.py` · `research/HYPOTHESIS_02_REPORT.md` ·
`research/hypothesis_02_results.json` · `research/hypothesis_02_controls.json`

The report carries: exact fingerprints, exact TRAIN/DEV boundaries, the frozen
threshold, event definitions, deduplication, sample counts, overlap ratios, raw
statistics, non-overlapping statistics, baselines, **incremental contrasts**,
power analysis, multiple-testing results, temporal results if reached, H1 results
if reached, cost results if reached, and limitations.

## 23. Verification before the results commit

1. this specification committed **before** results, containing the specification
   only; 2. FINAL_OOS token unchanged; 3. FINAL_OOS inaccessible; 4. dataset
fingerprints unchanged; 5. split manifest unchanged; 6. `baseline_008` unchanged;
7. production unchanged; 8. statistical controls pass; 9. **exactly one hypothesis
tested**; 10. **no alternative parameters tested**; 11. **causal reconstruction
tolerance frozen before results** (§14); 12. working tree contains only intended
research changes.
