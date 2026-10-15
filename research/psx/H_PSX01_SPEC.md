# H-PSX-01 — PSX 12–1 month momentum: long-only winners vs the equal-weight liquid universe

One page. Committed alone, before the script that computes its results.

## 1. ID and name
- ID H-PSX-01 · PSX momentum winners vs equal-weight universe · PSX programme: confirmatory hypothesis **#1 of at most 3**,
  each at one-sided α = 0.05/3.

## 2. Mechanism and external evidence
- **Hypothesis:** in PSX's liquid universe, past 12–1 month winners beat the equal-weight universe net of costs, 2015-01 → 2026-09.
- **Mechanism:** investors under-react to firm news. In a retail-heavy market with daily price limits, prices adjust over months rather than days.
- **Prior:** Shah & Shah (2018), *Pakistan Development Review* 57:3. Over 2004–2014 and 581 firms, PSX momentum was significant at about 3–22 months after risk adjustment; short-term reversal came from penny stocks.
- **Against:** momentum is weak or absent in several Asian markets (Griffin, Ji & Martin 2003, *Journal of Finance*). The prior is long–short and risk-adjusted, whereas this test is long-only against an equal-weight benchmark.

## 3. Data, timeframe and holdout
- **Data:** PSX closing files, audited in `research/psx/DATA_PSX.md` (raw `all_files_sha256` 364d79d781d482ca…). The adjusted total-return series is rebuilt by `psx/strategy/h_psx01.py` at commit `07b9e3f`. KSE-100 comes from psxdata histories and is informational only.
- **Period:** holding months 2015-01 → 2026-09 (n = 141). They lie after the prior's sample, so the period is out-of-sample for this rule, and nothing is fitted to our data.
- **Holdout:** there is no TRAIN/DEV/FINAL split. Forward paper trading is the holdout.

## 4. Exact construction (step-2 prompt, section 1, exactly)
| Constant | Value | Constant | Value |
|---|---|---|---|
| Universe | top 100 by median daily close × volume, last 126 days | Price | close ≥ Rs 10 at t |
| History | ≥ 252 trading days; volume > 0 on ≥ 80 % of the last 252 | Signal | adj. total return, month-end t−12 → t−1 |
| Winners | top floor(N/3) by signal, equal weight | Benchmark | equal weight of all N; both reset monthly |
| Commission | max(0.15 % of value, Rs 0.03 per share) + 15 % sales tax on it | Levies | 0.02 % of value |
| Spread | half of Abdi–Ranaldo (2017) close-high-low, last 63 days; negative two-day estimates → 0; full spread ≥ 0.10 % | Costs | per side, both portfolios; 2× = every component doubled (total × 2) |
| Delisting | last official close (primary); −30 % of it (sensitivity) | Excess | winners net − benchmark net, monthly simple returns |

- **Universe:** ordinary shares per the audit filter, without modarabas and REITs, with symbol changes chained. Month-end t is the last trading day of the month in the closing files.
- **Execution:** trades happen at the close of the first trading day after t, and the holding return runs to the next execution close.
  - **Buys:** a buy locked at the upper limit (traded, high = low = close, within 0.5 % of the band plus one tick) is not filled, and its slot stays in cash. A buy with no close that day is treated the same way.
  - **Sells:** a sell locked at the lower limit, or with no close that day, executes at the next close that is not locked.
  - **Cash:** buys are scaled down if cash after costs cannot fund them, and cash earns nothing.
- **Spread estimate:** two-day estimates use consecutive traded rows on adjusted prices, and the square roots are averaged.
- **Delisting:** a holding with no further closes in the files (to 2026-10-13) that is not a symbol change is treated as delisted.

## 5. Primary test
| # | Null | Alternative | Statistic | α |
|---|---|---|---|---|
| 1 | mean monthly net excess at 1× cost ≤ 0 | > 0 | one-sided t, Newey–West (3 lags) SE | 0.05/3 = 0.0167 |

## 6. Robustness (all required)
- Mean net excess ≥ 0 at 2× cost.
- Mean net excess > 0 under the −30 % delisting valuation.
- Mean net excess > 0 in at least 2 of the eras 2015–2018, 2019–2022 and 2023 → 2026-09.
- No era supplies more than 60 % of the cumulative net excess (the sum of the monthly net excess). This check fails if the total is ≤ 0.
- Disclosed: the Sharpe ratio of the excess and its standard error.

## 7. Verdicts
- **SUPPORTED:** primary p < 0.0167 and all robustness checks pass.
- **WEAK SUPPORT:** all robustness checks pass and the mean net excess at 1× cost is > 0, with p ≥ 0.0167. No significance is claimed.
- **NOT SUPPORTED:** otherwise.

SUPPORTED or WEAK SUPPORT leads to 3 months of forward paper trading. NOT SUPPORTED closes H-PSX-01.

## 8. Informational only (no verdict weight)
- A top-60 universe.
- Winners vs KSE-100. KSE-100 is a price index without dividends, so this comparison favours the strategy.
- After-tax annual return, with 15 % CGT on each year's positive realised net gains.
- Max drawdown and CAGR of winners, benchmark and KSE-100.

## 9. Power pre-check (blinded, `research/psx/POWER_H_PSX01.md`, commit `07b9e3f`)
- **Verdict: UNDERPOWERED.** The minimum detectable effect is above the reference effect.
- **Effect sizes:** with n = 141, the Newey–West SE is 0.22 % a month, so MDE = 2.970 × SE = **0.66 %** a month against E_ref = 0.60 % (MDE / E_ref = 1.11). Power at E_ref is 71 %.
- **Costs at 1×, median per month:** winners 0.27 %, benchmark 0.10 %, excess 0.18 %.
- **Dispersion and turnover:** the excess has sd 2.52 % and lag-1 autocorrelation 0.07. The universe holds 100 names every month. Median one-way turnover is 22 % for winners and 7 % for the benchmark.
