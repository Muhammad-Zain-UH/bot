# H10 — Time-series momentum, long/short, volatility-targeted

One page. Committed alone (with H11), before the script that computes its results.

## 1. ID and name
- ID: H10. Batch 2 (ROADMAP_V2 §6), external-prior confirmation standard (§5 rule 5, D5).
- No significance test is made, so the V2 test count is unchanged (1, H08).

## 2. Mechanism and external evidence
- Trends persist in futures returns, gold included: Moskowitz, Ooi & Pedersen (2012), *JFE*,
  58 futures; Hurst, Ooi & Pedersen (2017), a century of evidence across asset classes.

## 3. Data, timeframe and arms
- Broker v1b: D1 bars at the 17:00 New York boundary from H4 (`load_broker_v1b_d1`), H4 bars
  for execution (`load_broker_v1b`). TRAIN_D1 2004-06-14 → 2020-12-31; DEV 2021-01-04 →
  2025-09-02 (first DEV session 2021-01-05 after the one-day purge). FINAL_OOS is never loaded.
- utc_suspect D1 bars are kept (the flag matters for session-based tests only). The pre-2009
  clock is unconfirmed; a 1 h shift is negligible for daily data.

## 4. Exact construction
| Constant | Value |
|---|---|
| Bars per year (all annualisation) | 256.65 (measured D1 bars per year in TRAIN_D1) |
| Lookbacks | R21, R63, R252 = log(C_t / C_t−k) on D1 closes; σ63 = sd(63 daily log returns) × √256.65 |
| Signal | s = mean(sign(R21), sign(R63), sign(R252)) |
| Position | s × min(2, 0.10 / σ63) (multiple of equity; + long, − short) |
| Cost | 1 bp of price per unit of \|Δposition\| (2× case: 2 bp) |
| Financing markup | 2.5 %/yr; long pays DFF + 2.5 %, short pays 2.5 % (`gold/econ/costs.financing_usd`) |

- **Decision**: at each week's last D1 close (Friday, or the last trading day if Friday is
  closed), using D1 bars up to and including that close only. Trailing windows may reach back
  across an arm's start (past data only; nothing is fitted on it).
- **Execution**: at the open of the first H4 bar starting ≥ 60 minutes after the reopen, the
  reopen being the first bar after the decision close's gap (21:00 NY on 17:00-grid weeks,
  22:00 NY on EU-only gap weeks). Held until the next execution.
- **Start**: each arm starts flat. TRAIN_D1's first decision is the first weekly close with 253
  bars of history; DEV's first decision is its first weekly close (2021-01-08).
- **Daily P&L** (log units): position × daily log return. On an execution day the old position
  earns log(execution price / previous close) and the new one log(close / execution price),
  less cost × \|Δposition\|.
- **Financing**: each session close charges \|position held at that close\| × rate × calendar
  nights to the next session close / 365 (3 over a weekend); DFF (percent / 100) is the latest
  value on or before that night. The broker's current swap_long / swap_short (MT5 symbol_info)
  are recorded for reference only.

## 5. Tests and their count
None (external-prior standard). Metrics per arm at 1× and 2× cost, from the first execution
to the arm's end: net Sharpe (rf = 0), Sharpe SE = √((1 + SR²/2) / years), CAGR, max drawdown,
longest underwater (calendar days), turnover per year (Σ\|Δposition\| / years), correlation of
daily net P&L with buy-and-hold daily log returns; net P&L per TRAIN era: 2004-06 → 2008,
2009 → 2012, 2013 → 2016, 2017 → 2020.

## 6. Controls
Benchmark: cash (P&L 0). Correlation with buy-and-hold is reported.

## 7. DEV replication rule
Net Sharpe > 0 in DEV at 1× cost, same construction, nothing re-fitted.

## 8. Economics rule
Net of cost and financing throughout. **Pass**: net Sharpe > 0 in TRAIN_D1 **and** in DEV at 1×
cost; TRAIN_D1 net P&L total > 0 **and** no TRAIN era above 60 % of that total.

## 9. Evidence against
Any pass condition failing. Significance is not required and not claimed; Sharpe SEs are reported.

## 10. Power pre-check result (`research/POWER_V2.md`)
TRAIN_D1 864 weeks, 16.55 years, Sharpe SE 0.25–0.26 at SR 0.3–0.5; DEV 244 weeks, 4.65 years,
SE 0.47–0.49. A true SR of 0.3–0.5 cannot be shown significant in either arm (D5).
