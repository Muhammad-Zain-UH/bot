# Hypothesis 06 — real-yield-conditional gold exposure

**Pre-registered.** This document is committed **alone**, before the analysis
script exists and before any result has been computed, as H01–H05 were. Git is
the evidence.

Dataset: `data/cross_asset_v1` (`dataset_sha256`
`540d63a0d8f36f955991f45e3918a6a17abe4a2f92fc688d94e30d153c300da7`), verified
6/6 by `research/verify_cross_asset.py`, including the coherence identity
`DFII10 = DGS10 − T10YIE` holding to **0.0000pp** across 5,942 observations.
Gold: the H1 arms of `research/research_split_manifest_h1.json`.

---

## 1. Why this is different from H01–H05

All five previous hypotheses tested **patterns in gold's own price**: compression
breakouts, failed breakouts, volatility-state transitions, liquidity
displacement, and a trend overlay. 138 statistical tests, 0 survivors. The
feature class is exhausted, and the programme's own infrastructure explains why
the cheap remaining variations are not worth running —
`research/VIABILITY_REPORT.md` shows which horizons can decide anything at all,
and `research/BENCHMARK_REPORT.md` rules out intraday timing on cost before any
statistics are computed.

This is the first hypothesis built on **exogenous** information, and on a stated
economic mechanism rather than a shape found in a chart:

> Gold is a zero-coupon real asset. It pays no coupon, no dividend and no rent,
> and it has a storage cost rather than a yield. The opportunity cost of holding
> it is therefore the **real** interest rate — the return available on a
> risk-free asset after inflation. When real yields rise, holding gold becomes
> more expensive relative to the alternative; when they fall, less.

This is the standard academic and practitioner account of gold's price level,
and it is testable here because `DFII10` — the 10-year Treasury
Inflation-Indexed constant-maturity yield — is a direct daily observation of that
real rate, published by a third party, with no dependence on gold.

**It is not a trend-following rule on gold.** H05 tested that and it failed: the
overlay was wrong 85% of the times it exited, gave up 40% of return for 27% less
risk, and left the 8.93-year underwater period unchanged. The signal here is
exogenous, so H05's whipsaw-on-gold's-own-direction failure mode cannot occur
by construction.

## 2. The primary specification — declared, and the only one that counts

**Signal.** The 12-month change in the 10-year real yield:

```
delta(t) = DFII10(t) - DFII10(t - 12 months)
```

**Exposure.** Long-or-flat, unlevered, rebalanced monthly:

```
exposure(month M) = 1.0  if delta <= 0   (real yields falling or flat)
                    0.0  if delta >  0   (real yields rising)
```

**Why 12 months and no smoothing.** The lookback is the only free parameter, so
it is declared once with a reason rather than searched. Twelve months is the
conventional macro horizon for the *direction* of interest rates, it matches the
monthly rebalance, and a 12-month difference needs **no moving average**, which
avoids introducing a second parameter. A faster signal is also inadmissible on
cost grounds before any statistics: see §4.

**Exposure bounds.** `0.0` to `1.0`. No leverage, no shorting — the mandate fixed
earlier in this programme.

## 3. Decisions that must be declared before results, and are

**Missing observations.** FRED leaves a market holiday blank or `.`. The rule is
**last observation carried forward**: a yield that was not published did not
change, because the market was closed. Magnitude, measured before this was
chosen: 4.17% of TRAIN+DEV business days absent for `DFII10`, **longest run 1
day**. Interpolation is *not* used, because interpolating between two dates uses
the later one — which is look-ahead.

**Look-ahead embargo.** Exposure for month `M` is computed from data up to and
including the **last business day of month M − 1**, then applied from the first
trading day of month `M`. A further **1 business day** is withheld on top of
that, so the signal can never use a value published on or after the day it
trades. `DFII10` is published the same evening via H.15, so one day is
sufficient and costs almost nothing.

**Return alignment.** Gold daily closes are resampled from the frozen H1 bars of
the arm being tested. Exposure applies to the **next** day's return, never the
same day's.

**Cost.** One round turn = **1 × spread = $0.33** measured, charged at the price
level prevailing at each transition, as `research/BENCHMARK_REPORT.md`
establishes. A change of exposure from 0 to 1 or 1 to 0 is half a round turn
(`S/2`); a full out-and-back is one.

**Drawdown sign.** Drawdowns are **negative** percentages, so a shallower
(better) drawdown is the **larger** number. Improvement is
`strategy_maxdd − benchmark_maxdd`, positive when the strategy is better. This
is stated explicitly because computing it the other way round is a mistake this
programme has already made once, in H05, and caught before publication.

## 4. The cost gate, applied before any statistics

`BENCHMARK_REPORT.md` fixes the budget at **≤ 52 round turns per year**, derived
as the number that surrenders 20% of the benchmark's CAGR to spread.

A monthly rebalance that changed state at **every** rebalance would be 12 round
turns per year — **inside the gate with room to spare**. A daily rebalance (252
turns) is already ruled out at 96.3% of TRAIN CAGR, which is why the primary
specification is monthly and no faster variant is admissible.

## 5. Pre-declared success criteria

The benchmark is unlevered buy-and-hold gold on the same arms, from
`research/BENCHMARK_REPORT.md`:

| | TRAIN | DEV |
|---|---|---|
| Sharpe (rf = 0) | **0.387** | **0.880** |
| max drawdown | **−45.25%** | **−21.87%** |

**SUPPORTED requires all four, net of cost:**

1. Sharpe **strictly greater** than the benchmark in **TRAIN**
2. Sharpe **strictly greater** than the benchmark in **DEV**
3. Max drawdown **shallower** than the benchmark in **TRAIN**
4. Max drawdown **shallower** than the benchmark in **DEV**

and additionally:

5. Realised transitions **≤ 52 round turns/year** in both arms

**Failing any one of these in either arm is NOT SUPPORTED.** There is no partial
credit, no "promising", and no re-specification to rescue a near miss. Beating
DEV alone is explicitly not enough — DEV is a four-year window with two mild down
years, and a rule that beats only DEV has beaten a bull market.

## 6. Secondary diagnostics — recorded, and NOT selection candidates

These are computed and reported so the primary result can be *interpreted*, not
so a surviving variant can be promoted if the primary fails:

* lookbacks 3, 6 and 24 months on `DFII10`
* `DFII5` in place of `DFII10` (different maturity, same mechanism)
* `DTWEXBGS` 12-month change (the dollar mechanism)
* `VIXCLS` level versus its 12-month median (the safe-haven mechanism)

**Eight diagnostic cells.** Bonferroni-corrected at α = 0.05 → **α' = 0.00625**
per cell. Any diagnostic that appears to work while the primary fails is to be
reported as **what it is** — one cell of eight, surviving in-sample, with no
out-of-sample standing — and **must not** become H07 without a separate
pre-registration and authorisation.

## 7. What would make this uninterpretable rather than negative

Declared in advance so it cannot be invoked afterwards as an excuse:

* **Too few regime changes.** If the primary signal changes state fewer than
  **6 times** across TRAIN, the test is **UNDERPOWERED**, not negative — a rule
  that almost never transitions has not been exercised. TRAIN spans 11.33 years.
* **Degenerate exposure.** If exposure is in one state for more than **90%** of
  TRAIN, the result is **UNINFORMATIVE**: that is close to buy-and-hold or close
  to cash, and the comparison measures nothing.

## 8. Prohibitions

* **FINAL_OOS stays LOCKED.** Not opened, not inspected, not loaded. The token
  `OOS-AUTHORISATION-NOT-ISSUED` is unchanged.
* **No parameter is adjusted after seeing a result.** The lookback is 12 months
  because §2 says so, not because of what it produces.
* **No threshold is introduced** where §2 declares none. `delta <= 0` is a sign
  test; a tuned cutoff is a different hypothesis.
* **No profitability claim** on any result. Beating a benchmark on two arms of
  one instrument is not evidence of profitability, and the benchmark itself is a
  poor investment — Sharpe 0.387 with a 45% drawdown.
* `baseline_004`, `baseline_008`, `baseline_009`, `baseline_012` stay frozen.
  `LIVE_TRADING_ENABLED` stays `False`.

## 9. Honest prior

Better than H01–H05, because the mechanism is real and the information is
exogenous. Still **well under even odds**, for three reasons worth stating before
the result rather than after:

1. This relationship is extremely well known. Anything this legible is priced.
2. The real-yield link explains gold's **level** far better than its **changes**,
   and a tradeable rule needs the latter.
3. TRAIN contains 11.33 years and a monthly rebalance gives ~136 observations
   with perhaps a dozen regime changes. That is a small effective sample however
   many daily bars sit underneath it, and §7 may well bind.

If it fails, that is the sixth pre-registered null, and the honest conclusion
will be that a single instrument conditioned on a single macro series is not
where an edge is — which points at breadth across instruments, not at more
conditioning variables on gold.
