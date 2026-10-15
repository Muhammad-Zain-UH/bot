# The benchmark, and the cost gate on strategy form

Two reference numbers every future candidate must cite. Regenerate with
`python research/benchmark.py`. Read-only; **FINAL_OOS is not inspected**.

## 1. Buy-and-hold gold — the number to beat

On the H1 multi-regime split (`research/research_split_manifest_h1.json`):

| | **TRAIN** 2009-08-31 → 2020-12-31 | **DEV** 2021-01-04 → 2025-09-02 |
|---|---|---|
| bars / years | 66,147 / 11.33 | 27,589 / 4.66 |
| total return (net of one round turn) | **+99.12%** | **+82.55%** |
| **CAGR** | **+6.266%** | **+13.787%** |
| **max drawdown** | **−45.25%** | **−21.87%** |
| **longest underwater** | **8.93 years** | 1.15 years |
| annualised volatility | 15.69% | 14.67% |
| **Sharpe (rf = 0)** | **0.387** | **0.880** |

**A candidate must beat both the Sharpe and the max drawdown, in both arms.**

The two arms are deliberately different — Sharpe 0.387 against 0.880, drawdown
−45.25% against −21.87%. A rule that beats hold in both is robust; one that beats
only DEV has beaten a four-year bull market with two mild down years in it.

### Correction to two figures quoted earlier in this session

I previously reported the TRAIN benchmark as **Sharpe 0.33** and **5.9 years
underwater**. Both were wrong, from the same cause: I annualised hourly returns
with `sqrt(24 × 365.25)` = 8,766 hours.

**Gold trades about 120 hours a week, not 168.** The measured figure is **5,837
bars per year**. Using the calendar basis overstates volatility by **1.23×**
(19.23% instead of 15.69%) and understates Sharpe by the same factor, and it
divides the underwater run by calendar hours rather than trading bars.

Corrected: **Sharpe 0.387** (not 0.33) and **8.93 years underwater** (not 5.9).
The Sharpe is slightly better than I said; the underwater period is substantially
**worse**. Both figures here supersede the earlier ones.

## 2. Transition-cost budget — a hard gate on strategy form

One round turn costs **$0.33** (1 × spread, measured). As a share of capital that
is **0.0240%** per round turn on TRAIN (mean price $1,377) and **0.0154%** on DEV
(mean price $2,150).

| schedule | round turns/yr | annual drag, % of capital | **% of TRAIN CAGR** | verdict |
|---|---|---|---|---|
| twice daily (hour-of-day) | 504 | 12.074% | **192.7%** | **DEAD** |
| daily | 252 | 6.037% | 96.3% | marginal |
| every 2 days | 126 | 3.019% | 48.2% | marginal |
| **weekly** | 52 | 1.246% | **19.9%** | **viable** |
| **fortnightly** | 25 | 0.599% | 9.6% | **viable** |
| **monthly** | 12 | 0.287% | 4.6% | **viable** |
| **quarterly** | 4 | 0.096% | 1.5% | **viable** |

The table above is on **TRAIN**, which binds the gate. DEV is more permissive at
every schedule (higher CAGR, higher price level, so a smaller drag per turn); its
full per-schedule figures are in `research/benchmark_results.json` under
`arms.DEV.budget.schedule_cost` and are not repeated here.

### The gate

> **A candidate may use at most 52 round turns per year.**

Derived as the number that surrenders **20% of the benchmark CAGR** to spread —
a declared threshold, not a fitted one. TRAIN permits 52/yr and DEV permits
179/yr, so **TRAIN binds**. Any strategy form whose capture requires more
transitions than this **is not attempted**, however strong its statistics.

### Per-era budget — the spread is fixed in dollars, the price level is not

| era | bars | mean price | drag per round turn | weekly drag | monthly drag |
|---|---|---|---|---|---|
| 2009-12 | 19,160 | $1,450 | 0.0228% | 1.184% | 0.273% |
| 2013-16 | 23,478 | $1,272 | **0.0259%** | **1.349%** | 0.311% |
| 2017-20 | 23,509 | $1,424 | 0.0232% | 1.205% | 0.278% |
| 2021-24 | 23,645 | $1,984 | 0.0166% | 0.865% | 0.200% |
| 2025-26 | 3,944 | $3,148 | **0.0105%** | 0.545% | 0.126% |

The budget is **2.5× tighter in 2013-16 than in 2025-26**. A rule affordable at
today's price level may not have been affordable in the earlier era, so cost must
be charged at the price level prevailing at each transition — not at a single
average.

## 3. Consequence: which strategy forms are admissible

**Ruled out on cost alone:** intraday timing. An hour-of-day rule has roughly
**3× statistical headroom** per hour bucket (≈3,834 H1 bars each) — the power is
genuinely there — but capturing it needs ~504 round turns/year, which exceeds the
gate by an order of magnitude and costs **192.7% of the entire benchmark return**.

This is an economic rejection, not a statistical one, and it is recorded so the
family is not revisited. It is also the mirror image of the programme's recurring
error: H01–H04 failed on power while the economics went unexamined; intraday
timing has the power and fails on economics.

**Admissible:** forms transitioning weekly or slower — i.e. **slow
regime-conditional exposure**. That is where the next hypothesis belongs.

### What "beating the benchmark" does and does not require

It does **not** require pattern alpha. It requires only that reducing exposure in
bad regimes saves more drawdown than it forgoes in return, net of ≤52 round turns
a year. Against a benchmark with a **−45.25% drawdown and 8.93 years underwater**,
there is real room to improve the risk side without improving the return side.

## 4. Limitations

1. **The $0.33 spread was measured on the 2025-26 feed.** Applying it to 2009-2015
   is optimistic; real spreads were wider, so the true gate is **tighter** than 52
   round turns/year in the early era. The per-era table quantifies the direction.
2. **Drawdown is close-to-close.** Intra-bar excursions were deeper, so −45.25% is
   a floor on the pain, not a ceiling.
3. **Sharpe uses rf = 0.** Over 2009-2024 real rates were mostly near or below
   zero, so this is close to a real-rate Sharpe, but it is not a funding-adjusted
   figure and gold has no carry.
4. **No slippage or financing.** The gate counts spread only. Any real
   implementation pays more, which tightens the gate further.
5. **The benchmark is unlevered, single-unit, long-only gold.** It is the right
   comparison for a gold system; it is not a claim that holding gold is a good
   investment — Sharpe 0.387 with a 45% drawdown and nearly nine years underwater
   is a poor one, which is precisely why there is room to beat it.
