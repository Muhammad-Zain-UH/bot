# H-PSX-01 — blinded power check: **UNDERPOWERED**

Script `psx/strategy/power_h_psx01.py` · numbers `research/psx/power_h_psx01.json` · blinded: no mean, cumulative or annualised return, Sharpe, CAGR or hit rate computed. Max 30 lines.

| Year | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Universe (median; min–max) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) | 100 (100–100) |
| Winners (median) | 33 | 33 | 33 | 33 | 33 | 33 | 33 | 33 | 33 | 33 | 33 | 33 |

| Turnover and costs (monthly) | Winners | Benchmark | Excess |
|---|---|---|---|
| One-way turnover, median / p90 | 22.22 % / 28.45 % | 7.35 % / 10.36 % | |
| Cost per month at 1×, median | 0.27 % | 0.10 % | 0.18 % |
| Full spread in the universe (Abdi–Ranaldo), median / p90 | 0.77 % / 1.17 % | | |

**Counts.** 141 months; universe below 60 names in 0. Unfilled buys locked at the upper limit: winners 2 (new entries 2), benchmark 7 (2). No close on the execution day (slot stays in cash): 17 / 29. Sells deferred, locked at the lower limit: 5 / 6; no close: 12 / 26. Delisting events among holdings: winners 4, benchmark 6.

**Dispersion (net, 1× cost, monthly).** sd of the excess 2.52 %, lag-1 autocorrelation 0.07; sd winners 7.20 %, benchmark 7.94 %, KSE-100 6.32 % (119 months from 2016-11).

**Power (n = 141).** Newey–West (3 lags) SE of the mean excess 0.22 %; MDE = (2.128 + 0.842) × SE = **0.66 %** a month vs E_ref 0.60 % (MDE / E_ref = **1.11**); power at E_ref 71 %. Verdict: **UNDERPOWERED** (TESTABLE if MDE ≤ E_ref).

E_ref = 0.60 % a month net: Shah & Shah (2018) report about 20 % a year long–short gross (2004–2014), about 0.8 % a month long-only gross, less about 0.2 % a month of costs.
