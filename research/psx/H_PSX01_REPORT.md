# H-PSX-01 — PSX 12–1 month momentum winners vs the equal-weight liquid universe — report

Spec: `research/psx/H_PSX01_SPEC.md` at commit `521cfde` · Construction: `psx/strategy/h_psx01.py` at `07b9e3f` · Script: `psx/strategy/results_h_psx01.py` · Numbers: `research/psx/h_psx01_results.json` · Max 120 lines.

## Verdict
**NOT SUPPORTED** — mean monthly net excess of winners over the equal-weight universe at 1× cost +0.28 % (Newey–West t = 1.24, one-sided p = 0.1084 vs α = 0.0167), 141 months 2015-01 → 2026-09. Robustness: 3 of 4 pass (failed: no_era_over_60pct; spec §7 then rules out WEAK SUPPORT too).

## Pre-declared results
| # | Test | Period | n | Estimate (per month) | SE | t | p (one-sided) | Threshold | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Mean net excess, 1× cost | 2015-01 → 2026-09 | 141 | +0.28 % | 0.23 % | 1.24 | 0.1084 | p < 0.0167 | FAIL |

## Controls (robustness, all required)
| Control | Estimate | Required | Result |
|---|---|---|---|
| Mean net excess at 2× cost | +0.11 % | ≥ 0 | PASS |
| Mean net excess, delisted holdings at −30 % | +0.27 % | > 0 | PASS |
| Eras with mean net excess > 0 | 2 of 3 | ≥ 2 | PASS |
| Largest era share of the cumulative net excess | 73 % (total +39.57 %) | ≤ 60 %, total > 0 | FAIL |

| Era | Months | Mean net excess | Sum | Share of cumulative sum |
|---|---|---|---|---|
| 2015–2018 | 48 | +0.60 % | +28.78 % | 73 % |
| 2019–2022 | 48 | -0.16 % | -7.51 % | -19 % |
| 2023 → 2026-09 | 45 | +0.41 % | +18.30 % | 46 % |

Disclosed (Lo 2002, NW 3 lags): annualised Sharpe of the excess 0.35 (SE 0.29; monthly 0.112, SE 0.095; η = 3.12).

## Economics
| Portfolio | Median cost / month (1×) | Net CAGR | Max drawdown |
|---|---|---|---|
| Winners (33 names) | 0.27 % | +17.18 % | 46.82 % |
| Benchmark (100 names) | 0.10 % | +12.68 % | 57.09 % |

Gross (0× cost) mean excess +0.46 % a month vs net +0.28 %: costs take 0.18 % a month. Returns are simple, in PKR, monthly between execution closes.

## Informational only — no verdict weight
- Top-60 universe: mean net excess +0.23 % (t = 0.92, p = 0.178).
- Winners − KSE-100 from 2016-11 (119 months; KSE-100 is a price index without dividends, so this favours the strategy): +0.06 % a month (t = 0.18).

| From 2016-11 | Net CAGR | Max drawdown |
|---|---|---|
| Winners | +15.07 % | 46.82 % |
| Benchmark | +10.43 % | 57.09 % |
| KSE-100 (price index) | +15.24 % | 40.34 % |

| Year | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Mean net excess / month | +0.55 % | +0.14 % | +0.60 % | +1.11 % | -0.36 % | -0.54 % | -0.76 % | +1.04 % | -0.07 % | +1.09 % | +0.58 % | -0.09 % |
| Winners pre-tax | +24.61 % | +52.35 % | -15.49 % | +5.11 % | -4.42 % | +32.00 % | -16.08 % | -11.97 % | +64.40 % | +94.93 % | +45.76 % | -12.26 % |
| Winners after 15 % CGT | +23.86 % | +48.32 % | -17.05 % | +4.21 % | -4.42 % | +30.38 % | -18.41 % | -11.97 % | +61.60 % | +85.33 % | +38.33 % | -12.70 % |

After-tax CAGR of winners +14.95 % (CGT on each year's positive realised net gains, paid at year end; 2026 covers 9 months).

## Limitations
- Underpowered by design: the blinded power check put the MDE at 0.66 % a month against a 0.60 % reference (power 71 %), so a miss does not show the effect is absent.
- One price source (PSX closing files), 2015–2026 only; the 12 inferred missing trading days are chained over, and symbol changes are detected heuristically (51 chained); others count as delistings.
- Costs are modelled (Abdi–Ranaldo spread, published commission), not measured fills; no market impact beyond half the spread; locked-limit and no-close rules approximate execution.
- Benchmark and winners are equal-weighted with no size or risk adjustment, unlike the prior's long–short, risk-adjusted test.
- KSE-100 comparisons use a price index without dividends; the after-tax figures ignore tax on dividends.

## Changes
- (none)
