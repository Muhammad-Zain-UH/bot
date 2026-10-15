# H06 — real-yield-conditional gold exposure: **NOT SUPPORTED**

Specification: `research/hypothesis_06_real_yield_exposure.md`, committed alone
at `a4c95c8` before the analysis script existed.
Results: `research/hypothesis_06_results.json`.
Dataset: `data/cross_asset_v1`, `dataset_sha256` `540d63a0…c300da7`, verified
6/6. **FINAL_OOS was not loaded.**

---

## Verdict

**NOT SUPPORTED.** The rule passed all five pre-declared criteria on TRAIN and
failed DEV on Sharpe. Per spec §5 that is not partial credit, and the
specification forbids re-specifying to rescue it.

| | TRAIN (11.33 yr) | DEV (4.66 yr) |
|---|---|---|
| | strategy / hold | strategy / hold |
| CAGR | 6.119% / 6.267% | **1.683% / 13.593%** |
| **Sharpe** | **0.442 / 0.383** ✓ | **0.193 / 0.868** ✗ |
| max drawdown | **−36.03% / −44.91%** ✓ | **−13.71% / −20.20%** ✓ |
| annualised vol | 13.44% / 15.88% | 8.67% / 14.69% |
| longest underwater | 8.69 yr / 8.88 yr | 3.79 yr / 1.15 yr |
| round turns / year | 0.66 (budget 52) ✓ | 0.97 (budget 52) ✓ |
| exposure long | 63.2% of days | 35.8% of days |

Power guards (spec §7) were satisfied, so this is a **negative result, not an
inconclusive one**: 15 state changes on TRAIN against a minimum of 6, and a
dominant state of 63.2% against a 90% ceiling.

Worth noting how cheap it was: **0.66 round turns a year** against a budget of
52. Cost was never remotely the binding constraint, which is a first for this
programme — `BENCHMARK_REPORT.md` killed intraday timing on cost alone.

## The result that matters is not the headline

Had only TRAIN existed, this would read as a success: better Sharpe, 8.9
percentage points less drawdown, almost no trading cost. **DEV is the reason the
programme has two arms**, and this is the clearest demonstration of it so far.

But the interesting part is *why* DEV failed, and it is not what a failed
hypothesis usually looks like.

### The mechanism did not break. The functional form did.

| | TRAIN 2009–2020 | DEV 2021–2025 |
|---|---|---|
| real yield, start → end | +1.76% → **−1.06%** (−2.82pp) | −1.08% → **+1.87%** (+2.95pp) |
| gold, start → end | $951 → $1,894 (**+99.2%**) | $1,939 → $3,511 (**+81.1%**) |
| **corr(monthly gold return, monthly Δ real yield)** | **−0.543** (n=136) | **−0.434** (n=56) |
| days with a rising 12-month real yield | 36.8% | **80.1%** |

**The correlation stayed negative, and of similar magnitude.** Month to month,
rising real yields still coincided with weaker gold in DEV exactly as the
mechanism predicts. The economic relationship H06 was built on is visible in
both arms.

What changed is the **drift of the conditioning variable**. Real yields rose
through 80.1% of DEV — the 2022–23 hiking cycle took the 10-year real yield from
roughly −1% to +2% — so a sign test on their direction held the rule flat for
most of the period. Gold rose 81% anyway.

So the rule did not fail because the signal was uninformative. It failed because
**a binary long-or-flat sign test throws away gold's unconditional drift.** When
the conditioning variable trends one way for years, a 0/1 rule spends those
years in cash while the asset appreciates for every other reason — central-bank
buying, reserve diversification and inflation-hedging demand, none of which
enters through the real-rate channel.

Two figures make the same point from different directions: the strategy's DEV
volatility was 8.67% against the benchmark's 14.69%, so it *did* reduce risk as
designed; and its CAGR was 1.683% against 13.593%, so it paid for that reduction
with almost all of the return.

### The diagnostics confirm it is not a parameter problem

Eight cells, Bonferroni α′ = 0.00625, declared in advance as diagnostics and
**not** as selection candidates:

| cell | TRAIN Sharpe vs hold | DEV Sharpe vs hold |
|---|---|---|
| `DFII10_3m` | 0.478 / 0.383 ✓ | 0.304 / 0.868 ✗ |
| `DFII10_6m` | 0.460 / 0.383 ✓ | 0.101 / 0.868 ✗ |
| `DFII10_12m` **(primary)** | 0.442 / 0.383 ✓ | 0.193 / 0.868 ✗ |
| `DFII10_24m` | 0.387 / 0.383 ✓ | 0.044 / 0.868 ✗ |
| `DFII5_12m` | 0.464 / 0.383 ✓ | 0.390 / 0.868 ✗ |
| `DTWEXBGS_12m` | 0.182 / 0.383 ✗ | 0.362 / 0.868 ✗ |
| `VIXCLS_vs_12m_median` | 0.244 / 0.383 ✗ | 0.741 / 0.868 ✗ |

**Not one cell beats hold on DEV. Zero of eight.** Every real-yield variant beats
hold on TRAIN and loses on DEV, across four lookbacks (3, 6, 12, 24 months) and
two maturities (5-year and 10-year).

That uniformity is the useful part. It eliminates "the lookback was wrong" as an
explanation — which is precisely the escape hatch the pre-registration existed to
close, and the diagnostics show there was nothing on the other side of it. The
dollar and VIX variants fail on TRAIN as well, so neither substitutes for the
real-yield mechanism.

## What this does and does not license

**Does not license:** any claim that gold timing on real yields works. It failed
its pre-declared test. The TRAIN result is in-sample and the specification is
explicit that beating one arm is insufficient.

**Does not license H07.** The obvious next thought — that the information lives
in the *continuous* relationship rather than its sign, so exposure should be a
declining function of the real-yield change instead of 0/1 — is a **new
hypothesis**. Spec §6 forbids converting a diagnostic into one without separate
pre-registration and authorisation, and that prohibition binds hardest exactly
when the idea looks good. It is recorded here as an idea, not pursued.

**Does record, as measured fact:** the real-yield/gold relationship is present in
both arms at a correlation of −0.43 to −0.54 on monthly data. That is the first
quantified, out-of-sample-persistent relationship this programme has found in
118 months and 56 months of independent data respectively. It is not a trading
rule, and a correlation of that size with gold's volatility leaves enormous
residual risk. But it is not nothing, and it is not something H01–H05 produced.

## Running total

**Six pre-registered hypotheses. Six nulls.** 138 statistical tests across
H01–H05 plus H06's five criteria and eight diagnostics.

What H06 changes is the *character* of the null. H01–H04 failed on power — they
were tested on a combination needing 8,149 independent observations where 4,688
exist, inside a sample with zero bear-market years. H05 failed on mechanism: a
trend overlay on gold's own price was wrong 85% of the times it exited. H06
failed on **functional form**, with the mechanism intact and adequate power.

That is a more specific finding than the previous five, and it narrows where to
look next rather than just removing another candidate.

## Honest assessment of the prior

Spec §9 predicted "well under even odds" for three stated reasons. Two were
right and one was wrong, which is worth recording:

1. *"This relationship is extremely well known. Anything this legible is
   priced."* — **Partly wrong.** The relationship is still measurably there in
   both arms. What is arbitraged away is not the correlation but the ability to
   trade it with a naive rule.
2. *"The real-yield link explains gold's level far better than its changes, and a
   tradeable rule needs the latter."* — **Right, and this is the whole result.**
3. *"11.33 years at monthly resolution is a small effective sample."* — **Right
   in principle but not binding here.** The power guards passed, and the DEV
   failure was decisive rather than marginal.

The spec also predicted that failure would point "at breadth across instruments,
not at more conditioning variables on gold." H06's result sharpens that: the
conditioning variable was *fine*. What a single instrument cannot supply is
enough independent regime-changes to fit a functional form to — TRAIN and DEV
between them contain roughly one and a half real-yield cycles.
