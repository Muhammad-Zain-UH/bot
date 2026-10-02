# Hypothesis 04 — LIQUIDITY DISPLACEMENT → ACCEPTANCE / REJECTION

**Committed BEFORE any label or result is computed.** This commit contains the
specification and nothing else.

Governing standards, both binding: `research/RESEARCH_TO_STRATEGY_GATE.md` and
`research/STATISTICAL_RESEARCH_CONTROLS.md`. A G0→G2 pre-registration.

| Prior hypothesis | Status |
|---|---|
| H01 — compression → breakout → expansion | **NOT SUPPORTED** (`45223cd`) |
| H02 — failed breakout → re-entry → reversal | **INCONCLUSIVE / UNDERPOWERED** (`5230336`) |
| H03 — volatility-state transition | **NOT SUPPORTED** (`7b59b95`) |

**Nothing from H01, H02 or H03 is reused**: no compression ratio, no 12-bar
compression window, no breakout buffer, no range re-entry, no volatility-state
ratio, no session-hour filter. No production bias, structure or POI layer is
consulted. Production and `baseline_008` are untouched.

---

## 1. The question, and what it is not

> When price makes an unusually large directional displacement into a recently
> established price area, does the market subsequently show directional
> **ACCEPTANCE** or **REJECTION** that predicts forward returns?

**This is not "large candles predict continuation."** That claim has already been
tested in this programme and failed (§2). The novel content here is the
**acceptance/rejection classification** — a mechanically defined, causally closed
judgement about what happened *after* the displacement reached the prior area,
made before any forward return is measured.

```
DISPLACEMENT → INTERACTION WITH PRIOR PRICE AREA
             → ACCEPTANCE vs REJECTION
             → SUBSEQUENT DIRECTIONAL IMBALANCE
```

**Mechanism claimed.** A prior price area is where inventory was built. A large
displacement that carries price beyond that area's boundary forces a decision on
everyone holding against it: the boundary either holds as support/resistance from
the other side, or it does not. If price stays beyond the boundary for a further
hour, the participants who were positioned inside the area have been unable to
reclaim it, and their remaining inventory must be covered in the displacement
direction — acceptance, hence continuation. If price returns through the boundary
within that hour, the displacement was absorbed: the move was liquidity-taking
without follow-through, the breakout entrants are offside, and their covering runs
against the displacement — rejection, hence reversal.

**Direction of expected effect, signed in advance per state (§6):** acceptance
predicts continuation, rejection predicts reversal. These are directional
predictions fixed before any outcome is seen, not fitted.

**The competing explanation this design exists to defeat:** that any apparent
effect is just displacement itself — a large move continuing or reverting
regardless of the area. Baselines B, C, D and E (§8) exist for that, and §16
makes their failure a rejection criterion.

---

## 2. Prior testing history on the displacement construct — disclosed and carried

Displacement has been tested repeatedly in this programme. Stating it before
results, so it cannot later be cited as corroboration, and so the correction can
carry it:

| Source | Construct | Cells |
|---|---|---|
| Phase 1 clean rerun | `disp_1`, `disp_4`, `disp_8`, `disp_16` (M15 displacement / ATR) × 3 horizons | **12** |
| Original continuation audit | family B, bias + displacement × 3 horizons | **3** |
| Phase 3 production path | layer C, displacement × 3 horizons | **3** |
| | **prior M15-displacement cells** | **18** |

All failed. Phase 1's clean displacement cells were `disp_4@4h` −0.14,
`disp_4@2h` −0.19, `disp_8@4h` −0.30, `disp_8@2h` −1.58, `disp_1@2h` −0.33 — every
interval straddling zero.

**A note on why those carry even less information than their t-values suggest.**
Phase 1 defined `disp_w = (close[i] − close[i−w]) / atr[i]` against the label
`(close[i+h] − close[i]) / atr[i]`. **Both contain `close[i]`**, so that family had
endpoint coupling, and it was not among the six features Phase 1 excluded on those
grounds. The coupling biases such estimates negative — which is the sign every one
of them had. H04 is built to have **no endpoint coupling at all** (§5, §10), so it
does not inherit that defect.

### Accumulated-burden rule, frozen here

Per gate §6.6, repeated attempts on a construct accumulate. H04 declares **12**
primary tests (§11). Correction is reported **three** ways:

| | Tests | Role |
|---|---|---|
| **declared** | **12** | reported for completeness |
| **accumulated** | **30** = 12 declared + 18 prior displacement cells | **the promotion test** |
| programme-wide context | **138** = 126 prior tests on this TRAIN arm (Phase 1: 84, continuation audit: 9, Phase 3: 21, H01: 3, H02: 3, H03: 6) + 12 declared | disclosed interpretive bound, **not** the promotion test |

**Promotion requires surviving the accumulated-30 threshold.** The programme-wide
figure is disclosed because 126 tests have now been run against this same TRAIN
arm and any reader is entitled to that denominator; it is not used as the gate,
because correcting over every test ever run would make discovery impossible and is
not standard practice.

The accumulated count includes the prior displacement cells because the
ACCEPTANCE states predict **continuation of the displacement**, which is precisely
what those 18 cells tested. The rejection states are closer to novel, but the
conservative treatment is applied to both.

---

## 3. Data boundaries

Primary research timeframe **M15**, loaded only via `research/dataset_access.py`.

| Arm | Window | M15 rows | Role |
|---|---|---|---|
| **TRAIN** | 2022-06-30 07:00 → 2024-08-09 18:15 | 50,010 | formal discovery, headline inference |
| **DEV** | 2024-08-11 → 2025-09-02 14:15 | 24,989 | blind replication of the frozen definition |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | 24,989 | **LOCKED** |

**FINAL_OOS remains LOCKED** — no M15, H1, M5, M1 or tick data from that period,
as data or as context. The M15 series is truncated at the DEV upper boundary
**before** any indicator is computed, and the truncation is asserted. Dataset
fingerprints (`dataset_sha256 = 9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca`)
verified at load.

**H1 is used only for regime robustness** (§15), from H1 bars that **closed** at or
before the event. **M5 and M1 are not used at all** — they cannot be used to
manufacture the signal, and M1 has zero bars in both arms regardless.

**No DEV tuning.** No threshold, window, stratum boundary or event definition is
refit on DEV.

**Purge/embargo 16 M15 bars.** An event is admitted at horizon `h` only if its
entire timeline — through `e+w+h` — lies inside the **same arm**.

---

## 4. The causal ATR

```
A[k] = ATR_14[k-1]        Wilder ATR(14) on M15
```

The same convention as H01–H03, reused so effect sizes stay comparable in ATR
units across the programme. `A[k]` is a function of bars at or before `k-1`.

Two instances are used and are **not interchangeable**:

- `A[e]` — normalises the displacement size (§6);
- `A[e+w+1]` — normalises the label (§7).

An event is **excluded** if either is NaN or `<= 0`; exclusions are counted.

---

## 5. The causal event timeline — the hard gate

Three frozen integer windows:

```
a = 24   AREA_LOOKBACK    prior price area, in completed M15 bars  (6 hours)
d =  4   DISP_INTERVAL    displacement interval, completed bars    (1 hour)
w =  4   ACCEPT_WINDOW    acceptance/rejection window, completed bars (1 hour)
```

Schematic timeline for a displacement event detected at bar `e`:

```
bars e-27 .. e-4      bars e-3 .. e        bars e+1 .. e+4      bar e+5 ... e+4+h
|-------------------| |------------------| |------------------| |---------------->
   PRIOR AREA           DISPLACEMENT          ACCEPT/REJECT         FORWARD LABEL
   (a = 24 bars)        (d = 4 bars)          (w = 4 bars)
   built from highs      close[e] vs          closes vs the         anchor =
   and lows only         close[e-4];          SAME boundary         open[e+5]
                         boundary break                             exit  =
                                                                    close[e+4+h]

   <------------------ FEATURE PERIOD: bars <= e+4 ------------------>
                                                      <--- LABEL PERIOD: >= e+5 --->
```

**Why the windows are these values, for reasons that are not about results.**
`d = 4` and `w = 4` are both one hour — the shortest forecast horizon tested, and
the natural unit on which a decision about a one-hour move would be made.
`a = 24` is six hours, a third of a trading day: long enough to be a *previously
established* area rather than the move itself, and deliberately **not** H01's
12-bar window, so H04 is not a reparameterisation of a failed hypothesis. **No
window is searched and no alternative is computed.**

### The separation, stated precisely

- The **area** uses bars `e-27 … e-4` — strictly before the displacement interval.
  The displacement bar's own high, low and close play **no part** in building the
  area it is judged against (§3 of the authorisation).
- The **displacement** uses bars `e-4 … e`.
- The **classification** uses closes of bars `e+1 … e+4` against a boundary fixed
  at `e-4`. It is fully determined at the close of bar `e+4`.
- The **label clock starts at `open[e+5]`** — the first price after the
  classification is complete.

**No feature contains `open[e+5]` or any later price. No label contains any price
at or before `close[e+4]`.** The feature and label periods are disjoint and share
**no price point whatsoever** — not even the anchor, because the anchor is an open
that no feature reads. This satisfies the authorisation's §9 hard gate by
construction rather than by audit, and it is why SUPPORTED condition 9 can be met.

---

## 6. Prior area, displacement, and the area interaction

```
PRIOR_HIGH[e] = max( high[k] : k = e-d-a+1 .. e-d )      = max over bars e-27..e-4
PRIOR_LOW[e]  = min( low [k] : k = e-d-a+1 .. e-d )      = min over bars e-27..e-4

displacement_size[e] = | close[e] - close[e-d] | / A[e]

direction  d_e = +1 (LONG)  if close[e] > close[e-d]
                 -1 (SHORT) if close[e] < close[e-d]
```

**Displacement threshold:** `displacement_size[e] >= TAU`, where `TAU` is the
**TRAIN-only 80th percentile** of `displacement_size` over TRAIN bars where it is
finite, `numpy.percentile(..., 80, method="linear")`. Frozen, recorded to full
precision, **never recalculated on DEV, never optimised, no alternative percentile
tested.** The 80th percentile continues the tail convention already frozen in
H01–H03.

**Area interaction — the displacement must carry price beyond the prior
boundary:**

```
LONG  event requires:  close[e] >  PRIOR_HIGH[e]
SHORT event requires:  close[e] <  PRIOR_LOW[e]
```

> Reading recorded, not silently resolved: the authorisation's §1 says
> "displacement **into** a recently established price area", while its §5 defines
> acceptance as price remaining "on / **beyond** the relevant side of the prior
> area". The acceptance/rejection language requires a *boundary* to be on one side
> or the other, so the operative construction is displacement **through** a
> boundary of the prior area. That is what is implemented.

**Ambiguity.** If both conditions hold at `e` the event is **excluded and
counted**. (Since `PRIOR_LOW <= PRIOR_HIGH`, this cannot occur; the check is
implemented and reported rather than assumed.)

---

## 7. Acceptance / rejection, and the labels

The boundary is **fixed at detection** — `B = PRIOR_HIGH[e]` for a LONG event,
`PRIOR_LOW[e]` for a SHORT event — and is not recomputed during the window.

```
LONG  ACCEPTANCE:  close[k] >  B  for ALL k in e+1 .. e+4
LONG  REJECTION :  close[k] <= B  for SOME k in e+1 .. e+4

SHORT ACCEPTANCE:  close[k] <  B  for ALL k in e+1 .. e+4
SHORT REJECTION :  close[k] >= B  for SOME k in e+1 .. e+4
```

Acceptance and rejection are **exhaustive and mutually exclusive**, so the two
classes partition the event population — which is what makes the incremental
contrast in §8 clean.

**The full window always elapses before the label clock starts, for both
classes.** A rejection detected at `e+2` still anchors at `open[e+5]`. This is a
deliberate, declared choice: anchoring rejections at their first breach would give
the two classes different elapsed times since displacement and confound the
comparison with a timing difference of up to three bars. Comparability is
preferred, and the cost — that some rejection information is three bars stale — is
accepted and disclosed.

### Predicted direction and the headline metric

```
pred_e = + d_e   for ACCEPTANCE   (continuation)
         - d_e   for REJECTION    (reversal)

P0 = open[e+w+1]                       the anchor, read by no feature
A0 = A[e+w+1] = ATR_14[e+w]            the label normaliser

R_h = pred_e * ( close[e+w+h] - P0 ) / A0          HEADLINE, direction-normalised
$_h = pred_e * ( close[e+w+h] - P0 )               raw dollar return, also reported
```

Horizons, frozen: **1h = 4 M15 bars · 2h = 8 · 4h = 16**. No other horizon.

A common-metric return in the **displacement direction**, used for the incremental
contrast of §8 and for nothing else:

```
C_h = d_e * ( close[e+w+h] - P0 ) / A0
```

so `C_h = +R_h` for acceptance and `−R_h` for rejection. The primary cells and the
incremental contrast are the same information differently arranged, and this is
stated so the two cannot be counted as independent evidence.

### Path diagnostics — descriptive only

`MFE_h` and `MAE_h` in `A0` units over bars `e+w+1 … e+w+h`, measured from `P0` and
signed by `pred_e`. Reported to separate a directional effect from mere movement.
**No stop or target is derived or selected.** 0 hypotheses.

---

## 8. Required baselines — all defined before results

**A — Unconditional directional baseline.** Over all eligible bars in the arm,
the long-side mean and short-side mean of `(close[k+h] − open[k+1]) / A[k+1]`,
combined at the event population's own `pred` long/short mix. The period's drift.

**B — All displacement events.** The pooled event population (acceptance ∪
rejection), measured in the **displacement direction** `C_h`. Answers: does a
displacement that breaks a prior boundary continue, on average, irrespective of
the subsequent classification?

**C — Displacement events WITHOUT the area interaction.** Bars where
`displacement_size >= TAU` but the direction-consistent boundary break **does
not** occur, measured in the displacement direction with the identical timeline
(anchor `open[e+w+1]`) and the identical deduplication machine. **This is the
control for "large candles predict continuation"** — it isolates what the
area-interaction requirement contributes.

**D — Matched displacement magnitude.** All events stratified into **quintiles of
`displacement_size` using TRAIN-only cut points, frozen**. Within each stratum,
`mean(C_h | ACCEPT) − mean(C_h | REJECT)`, aggregated **observation-weighted by
the smaller class count per stratum**, with the standard error from within-stratum
variances. Strata are frozen feature quantiles, so their composition is **not**
endogenous to the outcome, and the aggregation is **never** an equal-weighted mean
of per-stratum means — the Phase 1 failure mode.

**E — Matched recent directional displacement.** The directional move *preceding*
the displacement interval, causal and distinct from `displacement_size`:

```
recent_disp[e] = ( close[e-d] - close[e-d-12] ) / A[e-d]
```

Stratified into **TRAIN-frozen quintiles**, same within-stratum contrast and
weighting as D.

**The incremental question these answer:** does acceptance/rejection carry
directional information **beyond simply having experienced a large move**?

> **Binding interpretive rule.** If the effect disappears after displacement
> matching (D or E), **the mechanism is NOT supported**, whatever the raw means.
> Baselines A–E contribute **0** to the hypothesis count and **none can promote
> the candidate.**

---

## 9. Symmetry — all four causal states

All four are tested; symmetry is **not** assumed:

```
LONG + ACCEPTANCE      SHORT + ACCEPTANCE
LONG + REJECTION       SHORT + REJECTION
```

The report classifies the observed pattern as exactly one of: **continuation ·
reversal · asymmetric · drift-driven · unstable · absent**, with the evidence for
the label stated.

**A result existing on only one side is conditional evidence and is not
generalised.** Pooled ACCEPTANCE and pooled REJECTION figures are reported as
**declared summaries of the same twelve cells** — not as additional independent
tests, and they are not counted in the correction.

---

## 10. Event deduplication — exact rule and precedence

One displacement/interaction episode = one event. A deterministic single-pass
machine, run independently within each arm in ascending time order:

```
armed = True
last_event_e = -infinity

for each eligible bar e in ascending order:
    if displacement_and_break(e):                  # size >= TAU and boundary break
        if not armed:
            suppressed_not_armed += 1
        elif e <= last_event_e + w:
            suppressed_within_unresolved_window += 1
        else:
            emit event at e
            last_event_e = e
        armed = False
    else:
        armed = True                               # condition absent -> re-arm
```

**Precedence rule, declared before running:** the **earlier** episode takes
precedence. A qualifying displacement occurring at or before `last_event_e + w` —
i.e. while the previous episode's classification window is still open — is
**suppressed and counted**, never allowed to pre-empt or overwrite the episode in
progress. A new event additionally requires the condition to have been **absent**
for at least one bar, so consecutive bars of one move cannot each fire.

`armed` and `last_event_e` reset at the start of each arm and **do not carry
across the TRAIN/DEV boundary**.

Reported, as the authorisation requires: **raw events · retained events ·
suppressed events** (split by cause) **· ambiguous events · invalid events**.

Deduplication is a function of the feature stream only. It cannot see any label
and therefore **cannot create the result** endogenously.

---

## 11. Primary statistical inference and frozen hypothesis count

**Pre-declared primary hypothesis count: 12.**

| # | State | Predicted direction | Horizons |
|---|---|---|---|
| 1–3 | LONG + ACCEPTANCE | continuation (long) | 1h, 2h, 4h |
| 4–6 | LONG + REJECTION | reversal (short) | 1h, 2h, 4h |
| 7–9 | SHORT + ACCEPTANCE | continuation (short) | 1h, 2h, 4h |
| 10–12 | SHORT + REJECTION | reversal (long) | 1h, 2h, 4h |

Each test is `E[R_h] > 0` on **non-overlapping events**, selected by the
deterministic greedy rule in `research/phase1_statistical_controls.py`.
Overlapping forward windows are **never** the headline estimator.

Reported per cell: **raw n · non-overlapping n · overlap ratio · mean · median ·
standard deviation · 95% CI · analytic t**, weighting named explicitly, raw
(overlapping) statistics alongside, block statistics as secondary diagnostics only.
**No unweighted block mean is used as headline evidence.**

### Estimators

1. **Analytic non-overlapping** — the headline.
2. **Moving-block bootstrap** — blocks of **96** and **480** M15 bars, 4,000
   replicates, seed **20261005**, declared here and not selected on their result.
   Each replicate is **observation-weighted** within resampled contiguous blocks.
   Bootstrap mean, SE, t and **percentile CI** are reported. This is **not** the
   estimator that failed in Phase 1.
3. **Equal-block mean** — the Phase 1 failure mode. Carried **only** as the input
   to the sign-disagreement check, never as evidence.

**If the raw and block estimates materially disagree in sign, the result is
flagged and the hypothesis is flagged. The favourable estimator is not selected.**
Per §16 this is a rejection criterion.

### Multiple testing

**Bonferroni** and **Benjamini–Hochberg** at nominal alpha 0.05, computed from the
**declared** count; a cell with no computable statistic is padded as a
non-rejection, never dropped. Reported over **12**, over the **accumulated 30**
(the promotion test), and with the programme-wide 138 disclosed (§2).

Primary arm **TRAIN**; DEV is blind replication (§14); pooled is descriptive only.

**No test is added after results are observed.** No alternative lookback,
displacement threshold, acceptance window, area width or ATR length. Any
additional diagnostic is labelled **EXPLORATORY** and cannot be promoted.

---

## 12. Power

Per primary cell, reported **before** any null is interpreted:

- non-overlapping n; SE;
- **MDE at 2 SE**; **MDE at the corrected detection threshold** (accumulated 30);
- **empirical spread cost in ATR**: round-turn = **1 × spread**, measured median
  **$0.33** → **0.158 ATR** TRAIN, **0.093 ATR** DEV;
- **whether a cost-sized effect is detectable** in that cell.

**A statistically positive gross effect is not economically useful unless it
clears cost**, and that is stated for each such cell. Every null is stated as "no
effect larger than X ATR", never "no effect". A cell with fewer than **100
non-overlapping events** is INCONCLUSIVE by the standing rule.

> Flagged in advance: splitting events four ways will reduce per-cell counts
> sharply. H02 was underpowered at 574/283 events and H03 at 697/395.
> **Power is the most likely outcome-determining constraint again**, and that is
> recorded now so a null is not later presented as a refutation it cannot support.

---

## 13. Execution-cost screen

Reported per cell alongside power: **gross ATR · cost ATR · net ATR · gross
dollars · net dollars**, dollar figures computed **per event** from that event's
own `A0` and then averaged.

No execution model is implied, no cost is optimised, no strategy is constructed,
and **no profitability claim is made**.

> Noted: `RESEARCH_TO_STRATEGY_GATE.md` §9.1 defers the cost screen until the
> statistical screen passes, to stop net figures being read as expected returns.
> This authorisation requires the screen as output P, so it is reported with that
> caveat attached rather than omitted — the same resolution recorded in H03.

---

## 14. TRAIN → DEV replication

**TRAIN** derives `TAU`, the displacement-magnitude quintile cuts, the
`recent_disp` quintile cuts and the H1 regime terciles, and carries the headline
inference. **DEV** applies the identical frozen definitions. **No threshold,
parameter or event-definition change.**

Reported: **same-sign replication · effect-magnitude stability · confidence
interval · cost viability · regime stability.**

**If TRAIN is null, DEV is not searched for a rescue.** A DEV-only result is
reported as the chance outcome it is, with the expected number of nominal
exceedances stated.

---

## 15. H1 regime robustness

H1 is used **only** to determine whether the relationship depends on broad
directional regime. It is **not** another optimisation variable, does not assign
event direction, and does not select or weight events.

From the last H1 bar to have **closed** at or before the close of bar `e+w`:

```
z = ( h1_close - h1_sma50 ) / h1_atr14
```

Cutoffs are the **TRAIN terciles of z**, frozen: `BEARISH` below the lower
tercile, `BULLISH` above the upper, `NEUTRAL` between. The same frozen H04
definition is reported across all three. **If the effect exists only in one
regime, that is stated clearly** and, per §16, counts against the hypothesis.
**No FINAL_OOS H1 data is read.**

---

## 16. Classification criteria — frozen

### REJECT H04 if ANY of

1. corrected TRAIN evidence is absent **and** effects are small relative to
   power/cost bounds;
2. acceptance/rejection adds no information beyond displacement (baseline B);
3. displacement-matched controls remove the effect (baselines D or E);
4. TRAIN and DEV signs are unstable;
5. estimator signs disagree materially;
6. the apparent direction is explained by ordinary drift (baseline A);
7. the result depends on one narrow H1 regime.

### INCONCLUSIVE if

the data cannot resolve a cost-sized effect, or a cell falls below 100
non-overlapping events.

### SUPPORTED only if ALL NINE hold

1. the causal definition is clean; 2. corrected TRAIN evidence exists (surviving
the **accumulated-30** threshold); 3. acceptance/rejection adds incremental
information; 4. displacement-matched controls retain the effect; 5. estimators
agree; 6. the effect survives realistic cost; 7. DEV replicates without retuning;
8. the effect is not solely one H1 regime; 9. no obvious endpoint coupling exists.

**The word "edge" will not be used unless all nine are met.** A positive point
estimate that fails correction is INCONCLUSIVE, never SUPPORTED.

---

## 17. Causal reconstruction standard — tolerances frozen BEFORE results

Following the H02/H03 redesign. **Derived from float64 precision alone; none is
chosen from an observed difference, and none may be revised after results.**

| Quantity | Frozen tolerance | Justification — numerical, not empirical |
|---|---|---|
| `PRIOR_HIGH`, `PRIOR_LOW` | **exactly 0.0** | `max`/`min` select one of 24 identical float64 inputs; no arithmetic, so no rounding |
| `displacement_size` | **relative 1e-12** | a difference of two exact prices divided by `ATR` |
| `recent_disp` | **relative 1e-12** | as above |
| `ATR_14` | **relative 1e-12** | Wilder's recursion **contracts** by 13/14 per step, so float64 error reaches a steady state of order `14·eps ≈ 3.1e-15`, not `n·eps`; 1e-12 is ~320× that bound and ~4 orders below any meaningful ATR difference |
| direction, break, **acceptance/rejection** classification | **0 disagreements** | boolean |

**Boolean standard.** Classifications must agree **exactly**. Any disagreement is
a **FAIL** unless the comparison margin at that bar is demonstrably below the
frozen numerical tolerance — a genuine threshold tie — in which case each margin
is reported and the cell excluded. A disagreement with margin above tolerance
fails the whole analysis.

**Method.** For a frozen sample of **60** events (seed **20261005**), every
quantity is recomputed from `m15.iloc[:k]` — bars `0 … k-1` only — and compared
with the panel value, at `k = e` for the detection quantities and `k = e+w+1` for
the label normaliser. **Inherited constants are referenced by artifact, not by
printed digits** — the lesson recorded in `HYPOTHESIS_02_REPORT.md` §13 note 1.

### Endpoint-coupling audit (output S)

The design has **no** coupling (§5). The audit demonstrates it rather than
asserting it, in two parts:

1. **Structural:** enumerate every bar index each feature reads and each label
   reads, and assert the two sets are disjoint — including that `open[e+w+1]` is
   read by no feature.
2. **Empirical:** recompute the headline with the label anchored at `close[e+w]`
   instead of `open[e+w+1]` — the coupled anchor — and report the difference. This
   is a **declared audit**, 0 hypotheses, and **cannot promote** the candidate; it
   exists to quantify what the clean anchor avoided.

---

## 18. No feature mining — binding

**Not** searched: RSI, MACD, EMA combinations, Bollinger Bands, alternative ATR
lengths, alternative area lookbacks, alternative displacement intervals,
alternative displacement thresholds, alternative acceptance windows, alternative
area widths, session filters, candlestick patterns, additional indicators, or any
H01/H02/H03 construct.

**One** area lookback, **one** displacement interval, **one** threshold
percentile, **one** acceptance window, **one** ATR length, **three** horizons,
**four** states.

**If H04 fails, the failure is recorded.** It is not mutated until it passes. Any
change to §5–§10 is a new hypothesis requiring a new pre-registration, inheriting
the accumulated burden — which, after this run, stands at **30** for this
construct family.

**A diagnostic is not converted into a new hypothesis without separate
authorisation.** If diagnostics surface a genuinely separate mechanism, it is
*reported as an observation* and explicitly **not** tested here.

---

## 19. Outputs

`research/hypothesis_04_liquidity_displacement.py` ·
`research/HYPOTHESIS_04_REPORT.md` · `research/hypothesis_04_results.json` ·
`research/hypothesis_04_controls.json`

The report carries, in the authorisation's order: frozen specification reference;
exact mathematical definitions; **causal event timeline, with one worked LONG and
one worked SHORT example**; threshold derivation; event counts; deduplication
accounting; raw/non-overlap counts; 1h/2h/4h returns; all four directional states;
unconditional baseline; displacement baseline; displacement-matched control;
analytic + bootstrap inference; multiple-testing correction; power/MDE;
execution-cost screen; H1 regime robustness; TRAIN→DEV replication;
**endpoint-coupling audit**; and the final classification — **SUPPORTED ·
INCONCLUSIVE · NOT SUPPORTED**.

## 20. Verification before the results commit

1. this specification committed **before** results, specification only;
2. FINAL_OOS token unchanged; 3. FINAL_OOS inaccessible; 4. dataset fingerprints
unchanged; 5. split manifest unchanged; 6. `baseline_008` unchanged;
7. production unchanged; 8. statistical controls pass; 9. exactly one hypothesis
family tested; 10. no alternative parameters tested; 11. causal tolerances frozen
before results; 12. no DEV tuning; 13. working tree clean except the pre-existing
`research/phase2/` state.

**H05 is not begun.** No strategy is designed. Strategy design requires separate
authorisation.
