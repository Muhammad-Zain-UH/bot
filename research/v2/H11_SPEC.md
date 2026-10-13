# H11 — Volatility-managed long exposure

One page. Committed alone (with H10), before the script that computes its results.

## 1. ID and name
- ID: H11. Batch 2 (ROADMAP_V2 §6), external-prior confirmation standard (§5 rule 5, D5).
- No significance test is made, so the V2 test count is unchanged (1, H08).

## 2. Mechanism and external evidence
- Volatility is persistent but does not raise expected returns proportionally, so cutting
  exposure when recent volatility is high improves risk-adjusted returns: Moreira & Muir
  (2017), *Journal of Finance*.
- Contrary evidence: Cederburg, O'Doherty, Wang & Yan (2020), *JFE* — out of sample the
  gains largely disappear across many factors. Prior: low to moderate.

## 3. Data, timeframe and arms
Identical to `research/v2/H10_SPEC.md` §3: broker v1b D1 (17:00 New York) from H4, H4 for
execution; TRAIN_D1 2004-06-14 → 2020-12-31; DEV 2021-01-04 → 2025-09-02 (first session
2021-01-05); FINAL_OOS never loaded; utc_suspect D1 bars kept.

## 4. Exact construction
| Constant | Value |
|---|---|
| Bars per year (all annualisation) | 256.65 |
| σ21 | sd(21 daily log returns of D1 closes) × √256.65 |
| σ* | **0.1433** = median σ21 over TRAIN_D1 (4,226 windows), frozen before any return was computed |
| Exposure | min(1.5, σ* / σ21) (long only) |
| Benchmark | buy-and-hold, exposure 1, same start, same cost and financing rules |
| Cost | 1 bp of price per unit of \|Δexposure\| (2× case: 2 bp) |
| Financing | long pays DFF + 2.5 %/yr on notional (`gold/econ/costs.financing_usd`) |

Decision, execution, start, daily P&L and financing rules are exactly those of
`research/v2/H10_SPEC.md` §4: weekly decision at the week's last D1 close using bars up to that
close only; execution at the open of the first H4 bar ≥ 60 minutes after the reopen; each arm
starts flat (TRAIN_D1 at the first weekly close with 253 bars of history, DEV at 2021-01-08);
trailing windows may reach back across an arm's start; the execution-day P&L split; nightly
financing on the position held at each session close, DFF as of each night. The benchmark
enters at the same first execution and is then held.

## 5. Tests and their count
None (external-prior standard). Metrics per arm at 1× and 2× cost, for strategy and benchmark:
net Sharpe (rf = 0), Sharpe SE, CAGR, max drawdown, longest underwater, turnover per year,
correlation with buy-and-hold; net P&L and excess P&L over the benchmark per TRAIN era
(2004-06 → 2008, 2009 → 2012, 2013 → 2016, 2017 → 2020).

## 6. Controls
The benchmark is the control: same data, start, costs and financing, exposure fixed at 1.

## 7. DEV replication rule
In DEV at 1× cost: net Sharpe above the benchmark's and max drawdown below the benchmark's.

## 8. Economics rule
**Pass**: net Sharpe AND max drawdown both better than the benchmark in TRAIN_D1 and in DEV at
1× cost; and TRAIN_D1 excess net P&L over the benchmark > 0 with no TRAIN era above 60 % of
that total.

## 9. Evidence against
Any pass condition failing. Significance is not required and not claimed; Sharpe SEs are reported.

## 10. Power pre-check result (`research/POWER_V2.md`)
TRAIN_D1 864 weeks, 16.55 years, Sharpe SE 0.25–0.26; DEV 244 weeks, 4.65 years, SE 0.47–0.49.
