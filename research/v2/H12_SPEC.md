# H12 — Multi-asset time-series momentum on the broker's tradable universe

One page of rules plus the frozen per-symbol constants. Committed alone, before the script that
computes its results. Owner decision (ROADMAP_V2 §8): the final hypothesis; if it fails, the
systematic-strategy programme ends.

## 1. ID and name
- ID: H12. External-prior standard with explicit thresholds (§8 below); no significance test, so
  the V2 test count is unchanged (1, H08). Batch 2 (H10, H11) failed; this extends H10 to breadth.

## 2. Mechanism and external evidence
- Trends persist across futures markets (Moskowitz, Ooi & Pedersen 2012, *JFE*, 58 futures;
  Hurst, Ooi & Pedersen 2017, a century); diversification across many trends is what lifts the
  portfolio Sharpe above any single market's.
- Against: here the universe is 27 FX pairs built from 8 currencies plus gold and silver
  (`research/v2/BREADTH_FEASIBILITY.md`); equity indices, bonds and commodities are not tradable.

## 3. Data, timeframe and arms
- MT5 history of the 29 symbols, server MetaQuotes-Demo, via `gold/data/store.load_h12` (v1b clock
  rule, D1 at the 17:00 New York boundary from H4; fingerprints `research/h12_fingerprints.json`;
  split `research/research_split_manifest_h12.json`). FINAL_OOS is never loaded.
- Universe (29): AUDCAD, AUDCHF, AUDJPY, AUDNZD, AUDUSD, CADCHF, CADJPY, CHFJPY, EURAUD, EURCAD, EURCHF, EURGBP, EURJPY, EURNZD, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPJPY, GBPUSD, NZDCAD, NZDCHF, NZDJPY, NZDUSD, USDCAD, USDCHF, USDJPY, XAGUSD, XAUUSD.
- Each symbol's history starts at its intraday start (earlier bars are daily-only and unused); it
  joins once it has 253 D1 bars of that history.
- TRAIN_D1: P&L from 2004-06-14 to the 2020-12-31 close; earlier intraday bars are lookback only.
  DEV: 2021-01-04 → 2025-09-02 (first session 2021-01-05). Both arms start flat; trailing windows
  may reach back across an arm's start (past data only). Clock-check exceptions (isolated months,
  `h12_fingerprints.json`) are kept: a 1 h shift is negligible for daily data.

## 4. Exact construction (per symbol i, every rule not stated here as in `research/v2/H10_SPEC.md` §4)
- Weekly decision at the symbol's last D1 close of the week, using its D1 bars up to that close only;
  execution at the open of the symbol's first H4 bar starting ≥ 60 minutes after its reopen after the
  decision close; held until the next execution; execution-day P&L split, DST handling and nightly
  accrual exactly as H10.
- s_i = mean(sign R21, sign R63, sign R252), R_k = log(C_t / C_t−k) on the symbol's D1 closes.
- position_i (multiple of equity) = s_i × min(2, (0.10 / √N_t) / σ63_i); N_t = the number of
  symbols active (joined) at that week's decisions; σ63_i = sd(63 daily log returns) × √(D1/yr_i).
- Daily P&L_i = position_i × daily log return_i; portfolio P&L = Σ_i P&L_i per calendar session date.
- Cost per unit |Δposition_i| = cost_i (table: median tick spread 2026-10-05 → 10-09 + round-turn
  commission, floored at 0.7 bp in total). Commission source for **every** symbol: (b) $7 round
  turn per standard lot, in bp of the symbol's lot notional — the account's deal history
  (`history_deals_get`) holds no trades, so source (a) was unavailable. Full spread plus full
  round-turn commission per unit is deliberately about 2× conservative; the 2× case doubles it again.
- Financing: at each session close, |position_i| × (the current broker swap for the side held, as
  an annual fraction of notional, if it is a charge; 0 if it is a credit) × calendar nights to the
  next session close / 365. Swap credits are never income. A crude constant-rate assumption;
  the 2× case doubles financing.

### Frozen per-symbol constants
| Symbol | Intraday from | Joins | D1/yr | Cost bp | Swap L / S %/yr | Symbol | Intraday from | Joins | D1/yr | Cost bp | Swap L / S %/yr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDCAD | 2007-02-12 | 2008-02-04 | 259.59 | 0.50+1.00→**1.51** | +2.35 / -5.65 | AUDCHF | 2007-05-01 | 2008-04-21 | 258.45 | 0.52+1.00→**1.52** | +4.46 / -9.93 |
| AUDJPY | 1999-01-07 | 1999-12-27 | 257.34 | 0.36+1.00→**1.37** | +1.85 / -4.24 | AUDNZD | 2007-05-01 | 2008-04-21 | 258.45 | 0.32+1.00→**1.32** | -0.73 / -4.46 |
| AUDUSD | 1999-01-04 | 1999-12-22 | 260.02 | 0.14+1.00→**1.15** | +3.30 / -7.75 | CADCHF | 2007-05-10 | 2008-04-30 | 253.12 | 1.38+1.00→**2.37** | +0.13 / -0.75 |
| CADJPY | 2007-02-12 | 2008-02-05 | 258.72 | 0.63+1.00→**1.63** | -0.36 / -0.30 | CHFJPY | 1999-01-08 | 1999-12-28 | 257.38 | 0.37+0.58→**0.95** | -0.10 / -0.02 |
| EURAUD | 2004-06-17 | 2005-06-08 | 259.20 | 0.19+0.63→**0.81** | -5.35 / +2.18 | EURCAD | 2007-05-10 | 2008-04-30 | 259.57 | 0.19+0.63→**0.81** | -0.25 / -0.21 |
| EURCHF | 1999-01-04 | 1999-12-22 | 259.52 | 0.21+0.63→**0.84** | +0.04 / -0.67 | EURGBP | 1999-01-04 | 1999-12-22 | 259.84 | 0.24+0.63→**0.86** | -0.52 / -0.17 |
| EURJPY | 1999-01-04 | 1999-12-22 | 254.25 | 0.11+0.63→**0.74** | -0.04 / -0.25 | EURNZD | 2007-05-14 | 2008-05-02 | 253.18 | 0.40+0.63→**1.03** | -3.13 / +1.21 |
| EURUSD | 1999-01-04 | 1999-12-22 | 260.07 | 0.00+0.63→**0.70** | -0.23 / -0.33 | GBPAUD | 2007-08-21 | 2008-08-14 | 258.17 | 0.42+0.53→**0.95** | -4.02 / +1.38 |
| GBPCAD | 2007-08-21 | 2008-08-14 | 258.47 | 0.32+0.53→**0.85** | -1.28 / +0.35 | GBPCHF | 1999-01-05 | 1999-12-23 | 257.96 | 0.27+0.53→**0.80** | +0.26 / -1.03 |
| GBPJPY | 1999-01-04 | 1999-12-22 | 260.07 | 0.43+0.53→**0.96** | +0.05 / -0.38 | GBPUSD | 1999-01-04 | 1999-12-22 | 260.02 | 0.00+0.53→**0.70** | -0.06 / -0.61 |
| NZDCAD | 2007-08-20 | 2008-08-08 | 257.52 | 0.50+1.25→**1.75** | -1.37 / -3.24 | NZDCHF | 2007-08-21 | 2008-08-11 | 258.99 | 0.65+1.25→**1.89** | -2.19 / -5.32 |
| NZDJPY | 2007-02-12 | 2008-02-01 | 259.66 | 0.56+1.25→**1.81** | -1.15 / -2.51 | NZDUSD | 2000-01-03 | 2000-12-20 | 259.98 | 0.18+1.25→**1.43** | +1.82 / -4.36 |
| USDCAD | 1999-01-04 | 1999-12-22 | 260.07 | 0.07+0.71→**0.78** | -0.21 / -0.10 | USDCHF | 1999-01-04 | 1999-12-22 | 259.98 | 0.12+0.71→**0.83** | +0.04 / -0.44 |
| USDJPY | 1999-01-04 | 1999-12-22 | 260.02 | 0.13+0.71→**0.83** | -0.02 / -0.14 | XAGUSD | 2008-11-10 | 2009-11-03 | 257.50 | 3.06+0.23→**3.29** | -1.39 / +0.12 |
| XAUUSD | 2004-06-11 | 2005-06-13 | 256.59 | 0.88+0.17→**1.05** | -1.10 / -0.40 |  |  |  |  |  |  |

Cost bp = tick spread + commission → total (floor 0.7). D1/yr = D1 bars per year in TRAIN_D1 from
the intraday start. Swaps: `research/h12_costs.json` (MT5, 2026-10-13).

## 5. Tests and their count
None. Reported per arm at 1× and 2× cost: gross, net of cost, net of cost + financing; portfolio
net Sharpe (rf = 0, annualised with the measured portfolio sessions per year of the arm) and SE
√((1 + SR²/2) / years), CAGR, max drawdown, longest underwater, realised volatility, turnover
(Σ |Δposition| / years); net P&L per TRAIN era (2004-06 → 2008, 2009 → 2012, 2013 → 2016,
2017 → 2020) and per symbol.

## 6. Controls
Per-era and per-symbol P&L shares (§8); gross vs net shows what cost and financing take.

## 7. DEV replication rule
DEV net Sharpe > 0 at 1× cost, net of cost and financing, nothing re-fitted.

## 8. Economics rule — PASS requires all, at 1× cost, net of cost and financing
- TRAIN_D1 net Sharpe ≥ 0.30;
- DEV net Sharpe > 0;
- TRAIN net P&L > 0, and no TRAIN era above 60 % of it;
- no single symbol above 30 % of TRAIN net P&L.

## 9. Evidence against
Any condition failing. No significance test is made or claimed; Sharpe SEs are reported.
Live subset rule, declared now and used only if H12 passes: live trading uses the largest set of
symbols tradable at the owner's equity, taken in ascending order of minimum-equity requirement
from `research/v2/BREADTH_FEASIBILITY.md`; that subset is re-run on DEV for disclosure only, never
for selection.

## 10. Power pre-check result
TRAIN_D1 P&L span 16.55 years: Sharpe SE ≈ 0.26 at SR 0.3–0.5; DEV 4.65 years: SE ≈ 0.47–0.49
(`research/POWER_V2.md`). The 0.30 TRAIN threshold is about 1.2 SE; DEV can only check the sign.
