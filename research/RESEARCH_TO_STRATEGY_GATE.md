# Research-to-Strategy Gate — standing standard

**Status: BINDING.** No market hypothesis may become a strategy-design candidate
except by passing every gate below, in order. **Failure at any gate stops
promotion** — it does not license a retry with adjusted definitions on the same
evidence.

This document defines the promotion path. It does not contain a hypothesis, a
feature, a threshold or a result, and creating it involved no market search.

**Companion:** `research/research_to_strategy_gate.json` — the same gates in
machine-readable form, for scripts to assert against.

**Related standing standards, both binding and not restated here:**

- `research/STATISTICAL_RESEARCH_CONTROLS.md` — the ten statistical guardrails.
- `research/phase1_statistical_controls.py` — their executable form; the only
  sanctioned estimator implementation.
- `research/dataset_access.py` — the only sanctioned dataset loader, and the
  mechanical FINAL_OOS lock.

---

## 0. The existing production strategy is a FROZEN HISTORICAL CONTROL

As of this document, `main_production.py` and its engine stack are **no longer a
subject of optimisation**. They are retained as a historical control: a fixed,
fingerprinted reference against which future work can be compared.

This follows from three completed phases, summarised with their evidence in §14.
It is a change of role, not a judgement that the code is defective.

Consequences that bind immediately:

- No threshold, constant or gate in the production stack is to be tuned.
- The implementation issues recorded in §14.2 are **documented, not repaired**.
  Repairing them would change the control.
- `baselines/baseline_004` and `baselines/baseline_008` remain **FROZEN**.
- A future candidate is **not** required to be an improvement on this control,
  and must not be justified by comparison to it. Beating a control that has no
  demonstrated edge establishes nothing.

---

## 1. The promotion path

```
                    MARKET HYPOTHESIS                 G0
                           |
                    CAUSAL DEFINITION                 G1
                           |
                    PRE-REGISTERED TEST               G2
                           |
                 CORRECT STATISTICAL INFERENCE        G3
                           |
                 MULTIPLE-TESTING CONTROL             G4
                           |
                    TEMPORAL REPLICATION              G5
                           |
                     REGIME ROBUSTNESS                G6
                           |
                   ECONOMIC / COST TEST               G7
                           |
                    EXECUTION REALISM                 G8
                           |
                   FINAL_OOS VALIDATION               G9
                           |
                CONTROLLED STRATEGY DESIGN            G10
                           |
                   PAPER / SHADOW TEST                G11
                           |
                 LIVE READINESS REVIEW                G12
```

### The stop rule

**Failure at any gate ends promotion for that candidate.** Specifically:

1. A failed gate may not be re-attempted by **redefining the feature, label,
   horizon, population or threshold** and re-running on the same data. That is a
   new hypothesis (G0) and it inherits the multiple-testing burden of every
   version attempted (§7.4).
2. A failed gate may not be **skipped** on the grounds that a later gate is more
   important.
3. A gate is passed only when its **required artifacts exist, are committed, and
   predate the results they govern** where this document says so.
4. "INCONCLUSIVE" is **not** a pass. It stops promotion in the same way as NOT
   SUPPORTED. The distinction is for institutional memory: INCONCLUSIVE records
   that the evidence could not decide, which may justify a *better-powered* test
   later; NOT SUPPORTED records that it decided against.

---

## 2. G0 — Market hypothesis

A hypothesis is a claim about *why* the market should behave a certain way. It is
not a feature/label pair with a large statistic attached.

**This is the rule the whole document exists to enforce:**

> **No hypothesis may be created merely because a feature/label combination
> produces a large statistic.** A statistic found first and explained afterwards
> is a post-hoc rationalisation, and it carries none of the evidential weight of
> a mechanism stated in advance.

### Required before any computation

| # | Requirement | What counts as satisfying it |
|---|---|---|
| 1 | **Economic mechanism** | Who is on the other side, what constraint or behaviour produces the effect, and why it is not already arbitraged away. Named participants or frictions, not "momentum exists". |
| 2 | **Direction of expected effect** | Signed, stated in advance. A two-sided "something happens" hypothesis doubles the test count and usually indicates no mechanism. |
| 3 | **Observable causal variables** | The market quantities the mechanism acts through, named before any feature is written. |
| 4 | **Exact feature definition** | Code-level: window lengths, which bar, which timeframe, how missing values behave. No free parameters. |
| 5 | **Exact label definition** | Code-level: horizon, normalisation, direction convention, what happens at series end. |
| 6 | **Forecast horizon** | Chosen from the mechanism's own timescale, not scanned. If the mechanism does not imply a horizon, the hypothesis is not specific enough to test. |
| 7 | **Eligible population** | Which bars are observations, stated as a rule evaluable before the label. |
| 8 | **Exclusions** | Which bars are excluded and why — and the exclusion must be causally justifiable, never outcome-based. |
| 9 | **Baseline** | The comparison population, frozen **before** the layer or condition is evaluated (§6.2). |
| 10 | **Expected effect scale** | A number, in ATR units, with its reasoning. Feeds the power pre-check in §4.3. |
| 11 | **Why it should survive costs** | Expected effect compared to the measured round-turn cost (§9) **in advance**. A hypothesis whose own predicted effect is smaller than the cost is not worth testing. |
| 12 | **Required data timeframe** | Per the role table in §10.1. Must be available over the required period — verified, not assumed. |
| 13 | **Required historical regimes** | Which regimes the mechanism needs to be observable in, and whether the dataset contains them. If it does not, say so here rather than discovering it in G6. |

### Reject at G0 if

- the mechanism is a restatement of the feature ("prices continue because
  displacement predicts continuation");
- the direction is unstated or "either";
- any of items 4–8 contains a parameter to be chosen later;
- item 10 is absent, or item 11 shows the predicted effect below cost;
- the required data (12) or regimes (13) do not exist in the dataset.

---

## 3. G1 — Causal definition

**Requirement: explicit proof that feature information ends before label
information begins.**

### Mandatory checks, all five

| # | Check | Failure |
|---|---|---|
| 1 | **No shared price point.** The feature must not read any price the label also uses. | REJECT |
| 2 | **No future-derived normalisation.** Scalers, ATRs, quantile cutoffs and z-scores must be computed from data at or before the decision bar. | REJECT |
| 3 | **No future regime classification.** Regime labels must be computable at the decision bar. | REJECT |
| 4 | **No accidental full-series leakage.** Any indicator must be computed on the window the consumer will actually have, not on the whole series. | REJECT |
| 5 | **Prefix reconstruction test.** Recompute the feature from data truncated at each decision bar and require **0.0** deviation from the panel value. | REJECT |

### Why check 1 is listed first

The most common failure is arithmetic, not subtle. A feature containing
`close[i]` while the label is `close[i+h] − close[i]` shares a price term with
opposite signs and will correlate **with no market content whatsoever**. Six
features were excluded on exactly these grounds in Phase 1 (§14.1); they were
excluded by construction, not tested and defended.

### Why check 4 is listed

See §14.2 item 6 and §14.3 item 2. An indicator computed on the full series can
differ materially from the same indicator computed on the window production
passes it — measured at **13.0% of bias labels** and **83.5% of bias strengths**
in this codebase. A research population built the wrong way is not the
population the strategy would face.

**The prefix test (check 5) does not substitute for check 4.** A full-series
computation can be perfectly causal and still be the wrong number. State
explicitly which window each indicator is computed on, and why that is the window
the consumer will have.

### Required artifact

A causality section in the pre-registration naming each feature, its window, and
the result of the prefix test. Deviations other than exactly 0.0 are reported, not
rounded.

---

## 4. G2 — Pre-registered test

### 4.1 The pre-registration must predate the results, mechanically

The hypothesis specification is committed in a commit that contains **no results
file, no analysis script and no panel**. This is verified by inspection of git
history, not by assertion:

```
git log -1 --format=%H -- <spec file>          # the spec's commit
git show --name-only --format= <that SHA>      # must contain only the spec
```

Both completed pre-registrations in this programme satisfy this —
`original_continuation_hypothesis.md` at `1110636` and
`production_path_spec.md` at `9692a3d` — and the check is implemented in
`research/production_path_verification.py` (check 7) as a reusable pattern.

### 4.2 Frozen before computation

- the **exact hypothesis count**;
- the **family structure** (which cells belong to which family);
- the **correction method**;
- the **significance threshold**;
- the **decision rule** — what result would constitute support, what would
  constitute evidence against, and what would be INCONCLUSIVE, each written out
  before any number exists.

### 4.3 Power pre-check — a gate, not a footnote

Compare the declared expected effect scale (G0 item 10) to the **minimum
detectable effect** at that horizon and sample size.

Current measured reference, from Phase 3 over ~60,638 sided M15 decisions:

| Horizon | median SE | MDE at 2 SE | **MDE at the corrected threshold** |
|---|---|---|---|
| 1h | 0.0249 | 0.050 ATR | **0.076 ATR** |
| 2h | 0.0453 | 0.091 ATR | **0.138 ATR** |
| 4h | 0.0844 | 0.169 ATR | **0.256 ATR** |

Round-turn cost for comparison: **0.158 ATR** (TRAIN), **0.093 ATR** (DEV).

**If the declared expected effect is below the MDE at its horizon, the test
cannot inform the hypothesis and must not be run as though it could.** Either
obtain more data, lengthen the horizon, or record the hypothesis as UNTESTABLE
with this dataset. Running it anyway produces a null that means nothing.

This cuts both ways and must be stated in every report: **at 4h a null means "no
effect larger than about 0.26 ATR", not "no effect"** — and 0.26 ATR is well
above the round-turn cost, so a tradable 4h effect can hide below this
programme's 4h resolution. At 1h the resolution is below cost and the null is
genuinely informative.

### Reject at G2 if

- the spec commit contains results;
- the hypothesis count, families, method or threshold are not frozen;
- the power pre-check shows the declared effect is undetectable.

---

## 5. G3 — Correct statistical inference

`research/STATISTICAL_RESEARCH_CONTROLS.md` applies in full. The Phase 1
estimator failure (§14.3 item 1) makes the following **permanent rules**.

### 5.1 Every result must report

| | |
|---|---|
| **raw observation statistics** | observation-weighted, overlapping — reported, never the headline |
| **non-overlapping headline statistics** | **the number that counts** |
| **overlap ratio** | raw n ÷ non-overlapping n, prominently |
| **weighting method** | named explicitly on every aggregate |
| **block statistics** | **secondary diagnostics only** |

### 5.2 Unweighted block means may never be used as the headline estimator

Not as a headline, not as a tiebreak, not as a robustness check that overrides
the headline. Per-block observation counts are endogenous — a condition that
fires more often in some periods than others makes equal-block weighting a
different estimand, not a more robust one.

### 5.3 ESTIMATOR_SIGN_DISAGREEMENT requires investigation before promotion

When the raw and equal-block statistics disagree in sign, the cell is flagged and
**the disagreement must be explained before the candidate advances**. It may not
be reported silently, suppressed, or resolved by preferring whichever estimator
is more favourable.

Base rates so far: **43 of 84 cells** in the Phase 1 clean rerun, **5 of 9** in
the continuation audit, **13 of 24** in Phase 3. A flag is therefore common and
is not itself disqualifying — but an unexplained flag on a *promoting* cell is.

### 5.4 Two-sample contrasts: cross-group dependence must be measured

A pass-vs-fail contrast draws two samples that are each internally
non-overlapping but whose **forward windows may overlap each other**. Measured in
Phase 3 at up to **99.97%**. The pooled standard error
`sqrt(se_a² + se_b²)` assumes cross-group independence and is then wrong.

**Required for any two-sample contrast:**

1. report the cross-group forward-window overlap per cell;
2. re-estimate with a **moving-block bootstrap** over contiguous calendar blocks,
   with block length ≥ several times the horizon, stated in advance;
3. report both estimators. Where they **disagree in sign**, the effect is noise
   and must be reported as such — not reconciled in favour of the better-looking
   one. Four of 21 Phase 3 cells flipped sign this way.

### 5.5 Confidence intervals and sample counts

On every reported cell, without exception. A point estimate without an interval
and an n is not a result.

---

## 6. G4 — Multiple-testing control

### 6.1 Frozen before computation

Hypothesis count, family structure, correction method, significance threshold —
see §4.2. **No post-hoc hypothesis addition, under any framing.**

### 6.2 The baseline is frozen before the condition is evaluated

A layer or condition is measured as an increment over a baseline population
defined **in advance**. Choosing the baseline after seeing the layer's behaviour
converts a test into a selection.

### 6.3 Required reporting

| | |
|---|---|
| pre-declared hypothesis count | the frozen number |
| nominal alpha | |
| **observed exceedances** | at \|t\| ≥ 2 and at the corrected threshold |
| **expected null exceedances** | `0.0455 × declared count` at \|t\| ≥ 2 |
| Bonferroni threshold | computed from the **declared** count |
| **corrected survivors** | Bonferroni and Benjamini–Hochberg separately |

### 6.4 Cells that produce no statistic are padded, not dropped

If a declared cell yields no computable t — an empty group, say — it is **padded
as a non-rejection** so that `m` remains the declared count. Dropping it shrinks
`m` and makes Benjamini–Hochberg more liberal. This was a real defect caught in
Phase 3 before results were reported.

### 6.5 Neither "largest t" nor "number of significant cells" is a result

Both are selection statistics. The result is the corrected survivor count.

### 6.6 Repeated attempts accumulate

Every version of a hypothesis tested on the same data counts toward the
correction burden. A candidate on its fourth redefinition is not a fresh test at
alpha 0.05.

---

## 7. G5 — Temporal replication

A candidate must survive, with its sign intact:

1. **TRAIN**;
2. **DEV**;
3. **pre-defined temporal segments** — declared in the pre-registration, never
   chosen after inspecting results;
4. **appropriate H1 regime context**;
5. **relevant volatility regimes**.

**A candidate that exists only in one favourable period cannot be promoted.**

### Sign instability is a failure, not noise to average over

Phase 2's strongest family flipped sign across TRAIN quarters
(+0.001, −0.088, +0.237, +0.015). That was reported as instability and no period
was selected. Doing otherwise is period-picking.

### Asymmetry is permitted when the mechanism predicts it

Do **not** require artificial long/short or regime symmetry if the economic
mechanism genuinely predicts asymmetry. **Document the reason in the
pre-registration, before results.** An asymmetry discovered afterwards and
explained as predicted is a post-hoc rationalisation (§2).

The converse matters too: an effect that is **positive long and negative short in
a direction-normalised metric** is the signature of **drift**, not of the claimed
mechanism. The continuation audit's strongest cell had exactly this shape and was
reported as drift rather than as support.

---

## 8. G6 — Regime robustness

The regimes the mechanism requires (G0 item 13) must be **present in the data**,
and the candidate must hold in them.

### Standing dataset limitation, to be restated in every report

**The M15 research sample contains no multi-year bear market.** TRAIN +33.63%,
DEV +44.24%, FINAL_OOS +18.24%. Downtrend strips inside a rising market are not a
bear regime, and must not be described as one. A candidate whose mechanism
depends on falling markets **cannot be validated on this dataset** and must be
recorded as UNTESTABLE rather than tested in a proxy regime.

Median ATR differs by arm — **$2.085** (TRAIN), **$3.564** (DEV), **$8.932**
(FINAL_OOS) — so any absolute-dollar threshold has era-dependent selectivity by
construction (§14.2 item 4). Thresholds must be expressed in ATR or another
scale-relative unit, with the choice justified in the pre-registration.

---

## 9. G7 — Economic / cost test

Runs **only after** G3–G6 pass. A candidate that fails the statistical screen
gets no cost analysis — reporting costs on a null invites reading the cost
analysis as if the effect were real.

### 9.1 Minimum contents

| | |
|---|---|
| **spread** | measured, not assumed |
| **slippage** | reported over a grid: 0, 0.25, 0.5, 1.0 × spread. Never optimised |
| **expected holding-period cost** | including any financing or per-bar cost the horizon implies |
| **expected movement** | gross, in ATR units |
| **expected net movement** | gross minus cost, with its confidence interval |

### 9.2 The measured cost convention

**Round turn = 1 × spread**, measured median **$0.33** on this instrument and
broker, where `ask = mid + S/2` and `bid = mid − S/2`. In ATR units: **0.158**
(TRAIN), **0.093** (DEV).

This convention was wrong in several earlier reports, stated as 2 × spread
(§14.3 item 5). One spread, not two.

### 9.3 Quintile separation is not expected return

> **Do not confuse Q5−Q1 separation with the expected return of a tradable
> rule.**

A Q5−Q1 spread of 0.10 ATR does **not** mean a rule earns 0.10 ATR. A rule that
trades Q5 earns `mean(Q5) − cost`, and `mean(Q5)` is typically a fraction of the
separation — it may even be negative while the separation is large, because the
separation can be produced entirely by Q1. The quantity that must clear cost is
**the traded cell's own mean**, with its interval.

The same applies to a pass-vs-fail difference: what a rule earns is
`mean(pass) − cost`, not `mean(pass) − mean(fail)`.

### 9.4 Stop rule

**A candidate that does not survive gross economics stops here.** No execution
work, no strategy design, no FINAL_OOS.

---

## 10. G8 — Execution realism

### 10.1 Timeframe roles — binding

| Timeframe | Sanctioned role |
|---|---|
| **M15** | primary structural research |
| **M5** | entry / confirmation |
| **M1** | execution / path |
| **ticks** | spread and execution-cost evidence |

### 10.2 Prohibitions

- **Do not use M1 or tick data to manufacture a directional edge.** They are
  execution evidence. A directional claim must stand on the structural timeframe.
- **Do not use third-party data for execution or fill claims.** Fills, spreads
  and rejections are broker-specific; evidence must come from the broker the
  strategy would trade on.
- **Do not parse `.hcc` or `.tkc` files.** Standing prohibition.
- MT5 interaction remains **read-only** history and metadata.

### 10.3 Availability must be verified, not assumed

Before an execution claim, verify the required timeframe exists over the required
period. In the current dataset, inside the authorised window: **M1 has zero
bars** and **M5 has zero bars in TRAIN**; **D1 is absent entirely**. Phase 3's
L8 entry trigger was untestable for exactly this reason.

Availability probes must validate expected bar counts. A 1-row response from
`copy_rates_range` is a **sentinel for an unmaterialised period**, not data
(§14.3 item 4), and availability is **not monotonic** in lookback, so bisection
over it is invalid (§14.3 item 3).

### 10.4 Clock discipline

MT5 server time is **UTC + 3.00h**, measured. Every timestamp in a report states
its zone. Session and kill-zone logic is UTC-based; reading server time as UTC
once produced a false conclusion that the broker session schedule had changed.

---

## 11. G9 — FINAL_OOS validation

**FINAL_OOS is a single validation resource.** `2025-09-02 → 2026-10-01`,
24,989 M15 rows. Enforcement is mechanical in `research/dataset_access.py`, which
raises `OOSLockedError`; the token is `OOS-AUTHORISATION-NOT-ISSUED`.

### 11.1 It remains locked until all six hold

1. the hypothesis is **frozen**;
2. TRAIN/DEV evidence is **sufficient** (G3–G6 passed);
3. statistical controls **pass**;
4. the economic screen **passes** (G7);
5. execution assumptions are **frozen** (G8);
6. strategy design is **frozen**.

Plus, per the split manifest: **explicit written authorisation from the strategy
architect**, and a record of the date, the git SHA and the candidate
specification SHA at the moment it is opened.

### 11.2 Opening FINAL_OOS is validation, not discovery

It supplies **no** quantile cutoff, **no** feature selection, **no** threshold
selection, **no** candidate selection and **no** parameter tuning.

**One look only.** A revised candidate on a used OOS is a new candidate on a
spent arm.

### 11.3 Any failure in FINAL_OOS ends that candidate

Not "suggests a refinement". Ends it.

### 11.4 The purge/embargo is part of the lock

**16 M15 bars** (4h, the longest horizon under consideration) are dropped after
each boundary so that no forward window spans two arms. Panels are truncated at
the arm boundary **before** any feature or label is computed, and the truncation
is asserted, not assumed.

---

## 12. G10 — Controlled strategy design

Only a candidate that has passed G0–G9 may become a strategy-design candidate.

### 12.1 Each of these is frozen separately, in writing, before it is implemented

```
entry        exit        stop        target      sizing
risk         execution   session     failure handling
```

Separately, because freezing them together allows a choice in one to be justified
by an outcome in another.

### 12.2 Optimisation is strictly separated from validation

- Any parameter chosen by search is chosen on **TRAIN only**, and the search
  space is declared in advance.
- DEV measures the chosen configuration; it does not select it.
- FINAL_OOS measures the frozen design once (§11).
- A parameter that must be re-chosen after seeing DEV returns the candidate to
  G2 as a new pre-registration.

### 12.3 Never used to select between options

**Backtest performance, signal count, win rate and trade frequency.**

These are outcomes, not evidence about mechanism. In particular the following
statements are prohibited as reasoning anywhere in this programme:

- "more signals is better";
- "fewer signals is worse";
- "profitability improved";
- any claim that a strategy choice is **optimal**;
- any claim of **profitability**.

Where evidence is insufficient, record **UNRESOLVED** or **INCONCLUSIVE**. Do not
force a classification.

### 12.4 The four historical trades are not evidence

`baseline_008`'s four signals may be used for forensic illustration only. They
support no statistic, no threshold and no selection. n = 4.

---

## 13. G11–G12 — Paper/shadow test and live readiness review

### 13.1 Standing safety invariant — not a gate, a precondition

**Live trading must remain impossible throughout research.**

- `core/safety.py:69` — `LIVE_TRADING_ENABLED: Final[bool] = False`, a literal
  with **no environment override**.
- No `mt5.order_send()`. No live or demo orders. No account modification.
- MT5 access is read-only history and metadata.

Nothing in G11 or G12 authorises changing this. Relaxing it is a separate
decision with its own authorisation, outside this document.

### 13.2 G11 — Paper/shadow period

A frozen strategy runs against live market data **without placing orders**, for a
pre-declared duration and acceptance criteria set **before** the period begins.
Its purpose is to detect divergence between replay and live behaviour — not to
re-estimate the edge.

Required: a documented comparison of paper decisions against deterministic replay
over the same period, and an explanation of every divergence.

### 13.3 G12 — Live readiness review

Every item must be demonstrated, with evidence:

| # | Requirement |
|---|---|
| 1 | **Deterministic replay** — identical inputs produce identical decisions, fingerprinted |
| 2 | **No lookahead** — exhaustive window-mapping audit, not sampled |
| 3 | **Broker execution validation** — against the actual broker |
| 4 | **Spread / slippage validation** — measured, matching the G7 assumptions |
| 5 | **Order rejection handling** |
| 6 | **Reconnect handling** |
| 7 | **Duplicate-order protection** |
| 8 | **Position-state reconciliation** |
| 9 | **Logging** — sufficient to reconstruct any decision after the fact |
| 10 | **Kill switch** |
| 11 | **Paper/shadow period completed** (G11) |

### 13.4 Live readiness is never implied by backtest performance

A passing backtest is not evidence for any item in §13.3. Each is demonstrated on
its own terms or the gate fails.

---

## 14. Current architecture status — institutional memory

Factual record. Figures are from the committed reports named in each row.

### 14.1 Completed phases

| Phase | Outcome | Evidence |
|---|---|---|
| **Phase 1** (clean rerun) | **NO ROBUST CONDITIONAL STRUCTURE DETECTED** | 84 hypotheses, Bonferroni \|t\| ≥ 3.434, **0 survivors**, 0 under BH. Max \|t\| **3.182** (`vol_transition@1h`). Observed \|t\| ≥ 2 = **6** vs **3.82** expected. 6 features excluded for endpoint coupling. `PHASE1_CLEAN_REPORT.md` |
| **Phase 2** (infrastructure correction) | **Phase 1 headline RETRACTED; estimator failure identified and fixed** | The original t = **−14.62** became **−0.33** under the corrected estimator. Every retracted candidate's CI straddles zero. **43 of 84** cells flagged `ESTIMATOR_SIGN_DISAGREEMENT` in the clean rerun. `PHASE1_CLEAN_REPORT.md`, `STATISTICAL_RESEARCH_CONTROLS.md` |
| **Original continuation hypothesis** | **NOT SUPPORTED** | 9 pre-declared hypotheses, Bonferroni \|t\| ≥ 2.773, **0 survivors**. Max \|t\| **0.688**. Both confirmation layers *subtract* from bias alone at every horizon. Bias alone **INCONCLUSIVE**. `ORIGINAL_CONTINUATION_AUDIT_REPORT.md` |
| **Phase 3** (production path decomposition) | **NO PREDEFINED PRODUCTION LAYER DEMONSTRATES ROBUST INCREMENTAL INFORMATION** | 21 pre-declared hypotheses, Bonferroni \|t\| ≥ 3.038, **0 survivors**, 0 under BH. Max \|t\| **1.338**; **1.957** under block bootstrap. **0** cells at \|t\| ≥ 2 vs **0.956** expected. 17 of 21 point estimates negative. `PRODUCTION_PATH_AUDIT_REPORT.md` |

Phase 3 classifications: bias alone **INCONCLUSIVE**; H1 regime, displacement,
sweep, POI, session gate and L3 pullback **NOT SUPPORTED**; structure confirmation
**INCONCLUSIVE**; entry trigger, the L7 gate and L4 **DESCRIPTIVE ONLY**
(untestable or undeclared).

### 14.2 Discovered implementation issues — documented, NOT repaired

Repairing these would alter the frozen historical control (§0). They are recorded
because they change how past and future evidence must be read.

1. **L6 restates L5.** `poi_score` takes 9 distinct values across 60,638
   decisions and equals exactly **68.0 on 89.44%** of them. The L6 threshold is
   60 with a confirmed sweep and 70 without — and 68 lies between. On those bars
   L6's verdict is **100%** determined by L5's; overall agreement **94.38%**.
   This is arithmetic, not statistics: L6 could not have been an information
   layer whatever the data said.
2. **Structure confirmation cannot contradict the bias.** `get_h1_structure`
   takes the bias as an input. Across 60,638 sided decisions it returned a
   contradicting classification **0 times**. "Confirmed" means only "not BROKEN
   and not UNKNOWN", true of **81.22%**.
3. **The session gate is clock-based.** Fixed UTC hours (`KILL_ZONES_UTC =
   ((8, 10), (12, 14))`), 17.60% pass, \|t\| ≤ 0.23 analytic and ≤ 0.21
   bootstrap. It is a clock, not a market condition.
4. **The L2 `8.0` threshold is price-level based.** `h1_atr` is a 14-bar mean of
   high−low **in dollars** (not a Wilder ATR), on an instrument that went from
   ~1,800 to ~4,600. The same unchanged constant passed **6.19%** of TRAIN but
   **41.90%** of DEV sided decisions, and blocked **0 of 15,735** decisions in
   the 2026 production run.
5. **The historical trades used a bypassed micro-scalp path.** All four
   `baseline_008` signals were MICRO_SCALP MOMENTUM entries on one identical
   path with **L3 and L6 bypassed** by regime flags — six of eight layers
   evaluated. **The documented eight-layer path has never produced a trade.**
6. **Production EMA initialisation differs from full-series EMA research.**
   Production passes 60 H1 bars, so `ema_50` is SMA-seeded and advanced ten
   steps. Research computed on the full series differs on **13.0%** of bias
   labels (one outright sign flip) and **83.5%** of bias strengths, median
   \|diff\| **0.608** on a 0–10 scale.

Further recorded discrepancies, same status: `detect_choch` is not a textbook
CHoCH implementation; breaker-block construction is not present despite being
referenced; sweep implementation and documentation disagree; `rr ≡ tp_ratio` is a
tautology so entry/stop geometry cannot earn admission; the L2 BOS flip can
change `side` after L1 sets it; `compute_cvd_proxy` reads `tick.last` and
`tick.volume`, both 0% populated on this feed; `layer_funnel.json` merges
`L5_SWEEP` (3,064) with `L5_SWEEP_WAIT` (1,936) into one bucket of 5,000; and all
four trades record `confidence = 0.0` while graded "A", so the ledger field does
not hold the score L7 gated on.

### 14.3 Named research failure modes — each rule above has an incident behind it

| # | Failure | What it produced | Rule it created |
|---|---|---|---|
| 1 | **Unweighted block means as headline** | t = **−14.62** from nothing, surviving seven artifact controls | §5.1, §5.2, §5.3 |
| 2 | **Full-series indicator leakage** | a research bias population differing from production's on 13% of bars | §3 check 4 |
| 3 | **Bisection over non-monotonic availability** | a false "7.74 years of tick history" | §10.3 |
| 4 | **1-row sentinels counted as data** | a false "24 years API-accessible, contiguous" | §10.3 |
| 5 | **Round-turn cost stated as 2 × spread** | overstated costs across several reports | §9.2 |
| 6 | **Server time read as UTC** | a false conclusion that the broker session schedule had changed | §10.4 |
| 7 | **Endpoint coupling** | features correlating with labels by arithmetic | §3 check 1 |
| 8 | **Cross-group forward-window overlap ignored** | standard errors assuming an independence that was 99.97% violated | §5.4 |
| 9 | **Dropping uncomputable cells from the correction** | a Benjamini–Hochberg procedure made silently more liberal | §6.4 |

Each was found and corrected inside this programme. The point of recording them
is that none was obvious in advance, and the controls that catch them now exist
because something got through first.

---

## 15. Verification required at every commit

| # | Check |
|---|---|
| 1 | FINAL_OOS token unchanged |
| 2 | FINAL_OOS inaccessible (`OOSLockedError` raised) |
| 3 | Dataset fingerprints unchanged |
| 4 | Split manifest unchanged |
| 5 | Frozen baselines unchanged — `baseline_008` is asserted by the script; `baseline_004` is frozen by standing constraint and not yet covered by it |
| 6 | Production code unchanged |
| 7 | Pre-registration predates results (git history) |
| 8 | Exact hypothesis count frozen before testing |
| 9 | Statistical guardrail self-tests pass |
| 10 | Working tree contains only intended research changes |

`research/production_path_verification.py` implements all ten and exits non-zero
on any failure. Commit only after all pass.

---

## 16. What this document does not do

It does not propose a hypothesis, identify a candidate, suggest where an edge
might be found, or rank anything. It makes no profitability claim and no claim
that any strategy choice is optimal.

It defines what a future hypothesis must demonstrate. Nothing in it should be
read as a prediction that something will.
