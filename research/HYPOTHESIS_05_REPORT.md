# Hypothesis 05 — SLOW TREND-CONDITIONAL EXPOSURE

## HYPOTHESIS 05 — NOT SUPPORTED

The trend filter **does** reduce risk, and still fails, because it gives up more
return than risk. Specification frozen at **`60b93e4`**; results at the commit
carrying this report.

| Pre-declared criterion (`hypothesis_05_trend_exposure.md` §5–§6) | TRAIN | DEV | |
|---|---|---|---|
| **max drawdown ≥5.00pp better** | **+4.97pp** | +7.80pp | **FAIL** (TRAIN) |
| **Sharpe not degraded** | 0.260 vs **0.313** | 0.907 vs **1.076** | **FAIL** (both) |
| CAGR give-up stated | −1.990pp | −4.978pp | stated |
| not driven by a single episode | **driven by 2013-16** | — | **FAIL** |
| result stable under SMA50/200 sensitivity | **SMA100 is the worst of the three** | — | **FAIL** |

Four of the five §7 criteria for evidence *against* are met. Under §10, any one
forces NOT SUPPORTED.

### The 4.97 against 5.00, and why I am not relaxing it

TRAIN's drawdown improvement is **+4.97pp** against a threshold of **5.00pp**
declared in advance, in writing, before any number existed. It misses by
**0.03pp**.

**I am not rounding it up, relabelling it "material", or moving the threshold.**
Declaring a bright line in advance and then stepping over it when it is missed by
a hair is precisely the failure mode this programme's entire apparatus exists to
prevent. The criterion is not met. And it does not matter in the end, because the
Sharpe criterion fails outright in both arms by margins far larger than 0.03pp.

---

## 1. What the mechanism actually did

It is not inert. It works as a **risk reducer**:

| | TRAIN strategy | TRAIN hold | DEV strategy | DEV hold |
|---|---|---|---|---|
| CAGR | +3.000% | +4.990% | +12.025% | +17.003% |
| max drawdown | **−40.27%** | −45.24% | **−14.08%** | −21.88% |
| annualised volatility | **11.36%** | 15.56% | **12.51%** | 14.60% |
| longest underwater | **8.93 yr** | **8.93 yr** | 0.85 yr | 1.15 yr |
| Sharpe | 0.260 | 0.313 | 0.907 | 1.076 |
| time in market | 54.8% | 100% | 68.9% | 100% |

Volatility fell **27%** in TRAIN and drawdown improved by 4.97pp. Both real.

**But return fell further than risk.** TRAIN: volatility −27.0%, CAGR **−39.9%**.
Risk-adjusted return therefore *worsened*, which is the whole point of the
exercise and the reason the Sharpe criterion exists.

### The single most damning number

**TRAIN's longest underwater period is 8.93 years — identical to buy-and-hold.**

Shortening the time spent underwater is the main thing anyone would want from a
trend overlay, and it did not improve **at all**. The filter made the hole
shallower without making it shorter.

## 2. Why it fails — the whipsaw, measured

| | TRAIN | DEV |
|---|---|---|
| times it went flat | 87 | 28 |
| flat spans that **avoided a decline** | **13** | **3** |
| flat spans that **missed a rise** | **74** | **25** |
| **wrong, as a share of exits** | **85%** | **89%** |
| **net market move forgone while flat** | **+22.91%** | **+18.99%** |
| worst decline avoided | −20.53% | −8.26% |
| best rise forgone | +3.43% | +4.01% |

The filter is **wrong 85–89% of the times it exits.** It caught one large decline
in TRAIN (2012-12 → 2013-08, **−20.53%**) and paid for it with 74 small
mistakes that sum to a **net +22.91% of market movement given away**.

That is the mechanism of failure, and it is not a cost problem (§5) or a power
problem — it is the signal being wrong far more often than it is right, with the
asymmetry too small to compensate.

## 3. All of the benefit comes from one bear market

| era | strategy CAGR | hold CAGR | strategy maxDD | hold maxDD | **DD improvement** |
|---|---|---|---|---|---|
| TRAIN 2009-12 | +7.154% | +14.431% | −22.45% | −20.55% | **−1.90pp (worse)** |
| **TRAIN 2013-16** | **−3.511%** | **−8.961%** | −29.97% | −38.05% | **+8.08pp** |
| TRAIN 2017-20 | +6.734% | +13.277% | −14.71% | −14.66% | **−0.05pp (none)** |
| DEV 2021-24 | +7.288% | +11.392% | −14.08% | −21.88% | +7.80pp |
| DEV 2025-26 | +42.243% | +53.444% | −10.47% | −10.47% | **+0.00pp (none)** |

In the **three bull eras** the filter delivered **zero or negative** drawdown
benefit while giving up roughly **half the return** (7.15 vs 14.43; 6.73 vs
13.28; 42.24 vs 53.44).

Its only real contribution is 2013-16, where it genuinely helped: it turned a
−8.961% CAGR into −3.511% and cut the drawdown by 8.08pp. **That is one bear
market.** §7 of the specification named "the drawdown improvement attributable to
one episode, with the rest neutral or harmful" as evidence against, and that is
exactly what the data show.

## 4. The sensitivity reports make it worse, not better

Declared in advance as disclosure, **never as alternatives to select from**:

| window | TRAIN CAGR vs hold | TRAIN DD imp | TRAIN Sharpe vs hold | DEV CAGR vs hold | DEV DD imp | DEV Sharpe vs hold | RT/yr |
|---|---|---|---|---|---|---|---|
| SMA50 | +3.515% vs +5.503% | **+13.11pp** | 0.305 vs 0.342 | +8.833% vs +16.791% | +7.14pp | 0.716 vs 1.067 | 11.2 |
| **SMA100 (primary)** | +3.000% vs +4.990% | **+4.97pp** | 0.260 vs 0.313 | +12.025% vs +17.003% | +7.80pp | 0.907 vs 1.076 | 7.9 |
| SMA200 | **+5.063% vs +4.869%** | **+12.48pp** | **0.415 vs 0.307** | +13.860% vs +18.041% | +4.59pp | 1.002 vs 1.139 | 3.8 |

Note the benchmark CAGR differs slightly per row because each window has a
different warmup length, so the benchmark is recomputed on each window's own
evaluation period for a fair comparison.

**The pre-registered primary is the worst of the three on TRAIN drawdown.** Its
neighbours at 50 and 200 both improve drawdown by roughly 13pp while SMA100
manages 4.97pp. SMA100 sits in a **hole, not on a plateau**.

§7 named exactly this: *"the result reversing under the SMA50/SMA200 sensitivity
reports, which would indicate SMA100 sits on a knife edge rather than a plateau."*
A parameter surface that swings from +4.97pp to +13.11pp between adjacent windows
is **evidence against the mechanism being robust** — not an invitation to adopt
the better window.

### And no window passes anyway

| window | drawdown ≥5pp both arms | Sharpe not degraded both arms |
|---|---|---|
| SMA50 | **yes** (+13.11, +7.14) | **no** — fails both arms |
| SMA100 | no (TRAIN +4.97) | **no** — fails both arms |
| SMA200 | no (DEV +4.59) | **no** — improves TRAIN (0.415 vs 0.307), fails DEV |

**No configuration satisfies both criteria in both arms.** The one Sharpe
improvement anywhere in the study is SMA200 on TRAIN (0.415 vs 0.307) — and it
degrades in DEV (1.002 vs 1.139), so it does not replicate.

## 5. Cost is not the problem

| slippage | TRAIN CAGR | TRAIN Sharpe | cost $/unit | DEV CAGR | DEV Sharpe |
|---|---|---|---|---|---|
| 0 | +3.000% | 0.260 | $28.71 | +12.025% | 0.907 |
| 0.25 × spread | +2.950% | 0.256 | $35.89 | +11.995% | 0.905 |
| 0.50 × spread | +2.900% | 0.252 | $43.07 | +11.966% | 0.903 |
| 1.00 × spread | +2.801% | 0.243 | $57.42 | +11.906% | 0.899 |

DEV transition costs across the same grid are $9.07 / $11.34 / $13.61 / $18.15
per unit, and are in `hypothesis_05_results.json` under `slippage_grid`.

At a full extra spread of slippage, TRAIN CAGR falls only from 3.000% to 2.801%.
**Transaction cost is irrelevant here**: 7.9 round turns/year against a gate of
52. The design constraint I spent two stages establishing turned out not to bind
at all for this strategy form — the signal quality is the binding problem.

## 6. Paired Sharpe test

| arm | Sharpe Δ | correlation | SE of Δ | t | significant at 2 SE |
|---|---|---|---|---|---|
| TRAIN | −0.053 | 0.730 | 0.229 | −0.23 | no |
| DEV | −0.168 | 0.857 | 0.359 | −0.47 | no |

As the specification predicted, this test is **underpowered** — a Δ of ±0.46
(TRAIN) would be needed for significance. So the Sharpe *degradation* is also not
statistically significant. The criterion was "must not degrade", and the point
estimates degrade in both arms; no significance claim is made in either
direction.

## 7. Controls — all pass

| Control | Frozen tolerance | Observed | |
|---|---|---|---|
| `daily_close` rebuild | **exactly 0.0** | **0.0** | PASS |
| `sma[d]` rebuild | relative 1e-13 | **3.46e-16** | PASS |
| `signal` classification | 0 disagreements | **0** | PASS |
| execution bar index | 0 disagreements | **0** | PASS |
| **lookahead audit, exhaustive** | 0 violations | **0** over all bars | PASS |
| FINAL_OOS loaded | no | **no** | — |
| anything refit on DEV | no | **no** | — |

60 probes, seed 20261007. The lookahead audit is exhaustive, not sampled: for
every H1 bar it asserts the exposure in force derives from a daily close whose H1
bar index is strictly lower.

### A bug I caught before committing

My first implementation computed the drawdown improvement as
`benchmark − strategy`. Drawdowns are **negative** percentages, so a shallower
(better) drawdown is the **larger** number and the correct expression is
`strategy − benchmark`. The inverted version reported TRAIN as −4.97pp
("NOT MET") when the strategy had in fact *improved* drawdown by +4.97pp.

It was caught by reading the output against the raw drawdown figures
(−40.27% versus −45.24% is plainly better) before anything was committed, and
fixed at all three sites. The verdict is unchanged — NOT SUPPORTED either way —
but the reason differs, and the corrected figures are the ones above.

---

## 8. Limitations

1. **TRAIN rests on one bear market.** 2013-16 supplies essentially all of the
   drawdown benefit. 88 in-market episodes sounds adequate until you notice the
   benefit concentrates in one of them.
2. **DEV is 4.33 years with one down period.** Its +7.80pp improvement is a
   single 2022 episode (−8.26% avoided), so it is not independent confirmation of
   a general effect.
3. **Sharpe comparisons are underpowered** (§6). Neither the degradation nor any
   improvement could be established statistically on this history.
4. **Warmup cost is real**: SMA100 drops the first 1,866 TRAIN bars and 1,920 DEV
   bars, so the arms shorten to 11.01 and 4.33 years and the benchmark is
   recomputed on the identical window for fairness.
5. **Long-or-flat only, unlevered.** A long/short version would have profited
   from 2013-15 rather than merely sitting out; that is a different hypothesis
   with different risk, and was excluded by design.
6. **One instrument, one broker, one spread assumption.** $0.33 measured on the
   2025-26 feed is optimistic for 2009-2015, but §5 shows cost is not decisive
   here, so the assumption does not drive the verdict.
7. **Accounting is open-to-open** with cost charged at each transition's price;
   the repository's `execution/fills.py` uses a different convention (2× spread,
   in pips). The conflict is recorded in the controls file, not repaired.

## 9. Verdict and what it means

# HYPOTHESIS 05 — NOT SUPPORTED

A slow trend filter on gold reduces volatility by 27% and drawdown by 5–8
percentage points, **and is still not worth having**, because it surrenders 40%
of the return to do it, leaves the longest underwater period completely
unchanged, is wrong 85–89% of the times it exits, derives essentially all its
benefit from a single bear market, and sits on an unstable parameter surface
where the pre-registered window performs worse than both its neighbours.

**This is the most informative result in the programme so far**, because it is
not a null. It is a measured, mechanical account of *why* the most
well-documented risk-management effect in asset pricing does not pay here: gold
spent 2009–2025 in a strong uptrend punctuated by one sustained decline, and a
filter that exits on weakness pays a continuous premium in forgone upside for
insurance it collects on once.

### What I recommend, and what I do not

**I do not recommend adopting SMA200** despite its striking TRAIN figures
(+12.48pp drawdown and a *higher* CAGR than hold). It fails DEV on both criteria,
and choosing it now would be selecting a parameter on observed performance —
exactly what `RESEARCH_TO_STRATEGY_GATE.md` §12.3 forbids and what the whole
apparatus exists to prevent.

**Recorded as an observation requiring separate pre-registration, not a claim:**
SMA200 on TRAIN improved drawdown by 12.48pp *while also beating hold on CAGR*
(+5.063% vs +4.869%). That combination is unusual and may indicate the effect
lives at slower horizons than tested. It is one arm, not replicated, uncorrected,
and chosen post hoc — so under §18 of the specification it is not converted into
a hypothesis here.

**Phase 2 is not entered.** The plan gated building the system on H05 passing. It
did not pass, so no strategy is built, and `LIVE_TRADING_ENABLED` remains
`False`.

No profitability claim is made or implied. FINAL_OOS was not opened. Production,
`baseline_004` and `baseline_008` are untouched.
