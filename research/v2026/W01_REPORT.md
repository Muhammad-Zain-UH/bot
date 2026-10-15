# W01 — walk-forward selection on XAUUSD: does the setup that works now keep working? — report

Spec: `research/v2026/W01_SPEC.md` at commit `4d48091` · Code: `gold/wf/` · Script: `gold/wf/run_w01.py` · Numbers: `research/v2026/w01_results.json` · Max 120 lines.

## Verdict
**DOES NOT WORK** — choosing each month the variant with the best 6-month t-statistic earned -0.797 R a month net at 1× cost (Newey–West t = -2.25, one-sided p = 0.987), 100th percentile of 2,000 random-pick paths; mean IC +0.262 (t = 8.95). 2 of 5 pre-declared tests pass.

## Pre-declared results
102 variants, 189 months 2011-01 → 2026-09, net R per month (k_cost 4.625, financing past 17:00 New York).

| # | Test | Estimate | SE | t | p (one-sided) | Threshold | Result |
|---|---|---|---|---|---|---|---|
| 1 | Process mean net R / month, 1× | -0.797 | 0.355 | -2.25 | 0.987 | > 0, p < 0.05 | FAIL |
| 2 | Process mean net R / month, 2× | -1.067 | | | | ≥ 0 | FAIL |
| 3 | Process vs random control (95th pct -3.017) | 100.0 pct | | | | > 95th | PASS |
| 4 | Mean IC (189 months, 83 % positive) | +0.262 | 0.029 | 8.95 | 0.000 | > 0, p < 0.05 | PASS |
| 5 | Eras with a positive process mean | 0 of 3 | | | | ≥ 2 | FAIL |

## Controls
| Process vs random control | Mean net R / month |
|---|---|
| Walk-forward process (top-1, 6 months) | -0.797 |
| Random eligible variant, median of 2,000 paths | -3.788 |
| Random eligible variant, 95th percentile | -3.017 |

Ranking does carry information (tests 3 and 4), but mostly about losers: variants that trade often pay costs every month and stay at the bottom, so the top-ranked variant is the mildest loser, not a winner.

| Era | Months | Process mean net R / month | Sum |
|---|---|---|---|
| 2011–2015 | 60 | -0.776 | -46.6 |
| 2016–2020 | 60 | -0.713 | -42.8 |
| 2021 → 2026-09 | 69 | -0.889 | -61.3 |

| Family chosen | Months |
|---|---|
| c_mean_reversion | 55 |
| a_donchian | 50 |
| b_ma_trend | 49 |
| g_time_of_day | 24 |
| d_session_breakout | 7 |
| e_sweep | 2 |
| f_fvg | 2 |

## Informational only — no verdict weight
- Lookback 3 months: -1.556 R / month (t = -2.95); 12 months: -0.582 (t = -1.63); top-3 equal weight (6 months): -0.714 (t = -2.24).
- Buy-and-hold gold (D1 closes, same months): CAGR +7.1 %, max drawdown 41.9 %; cash 0. Not comparable in R units.
- Trades: 206,279 in total; per variant median 1382, minimum 12.

**Hindsight only — not tradable, chosen after the fact.** The 10 variants with the largest total net R (1×) over 2011-01 → 2026-09:

| Variant | Family | Trades | Total R | Mean R / trade | t |
|---|---|---|---|---|---|
| donchian_D1_N20_k1.0_L | a_donchian | 77 | +82.1 | +1.066 | 2.34 |
| donchian_D1_N20_k1.5_L | a_donchian | 71 | +50.6 | +0.712 | 2.10 |
| donchian_D1_N55_k1.0_L | a_donchian | 48 | +47.3 | +0.986 | 1.05 |
| donchian_D1_N55_k1.5_L | a_donchian | 34 | +42.2 | +1.242 | 1.39 |
| donchian_D1_N10_k1.0_L | a_donchian | 143 | +40.4 | +0.283 | 1.37 |
| ma_D1_10x50_k1.0_L | b_ma_trend | 48 | +32.4 | +0.674 | 1.04 |
| donchian_D1_N10_k1.5_L | a_donchian | 131 | +31.8 | +0.243 | 1.53 |
| ma_D1_10x50_k1.5_L | b_ma_trend | 48 | +16.1 | +0.335 | 0.74 |
| donchian_H1_N55_k1.5_L | a_donchian | 813 | +13.0 | +0.016 | 0.14 |
| donchian_H1_N55_k1.0_L | a_donchian | 948 | +11.7 | +0.012 | 0.08 |

The leaders are long D1 trend rules, which largely carry gold's rise over the period; picked after the fact from 102 variants, their t-statistics (at most 2.3) are within what chance alone produces.

## Limitations
- FINAL_OOS was opened for exploration (2026-10-14), so no period here is a clean holdout; only a forward demo test could validate a WORKS result.
- Bid-based H1 bars; costs are modelled from bar spreads × k_cost 4.625 (one week of ticks, 2026), not measured fills; intrabar order is assumed stop-first.
- The menu is the owner's list with fixed parameters; other rules or parameters could behave differently.
- Months are UTC entry months; a selected variant's trades are held to their exits, so risk can overlap month boundaries.
- Monthly net R sums trades of different counts per variant: high-frequency variants (time of day, H1 rules) dominate both scores and outcomes.

## Changes
- (none)
