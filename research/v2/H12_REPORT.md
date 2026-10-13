# H12 — Multi-asset time-series momentum (29 symbols) — report

Spec: `research/v2/H12_SPEC.md` at commit `724eb6f` · Script: `research/v2/run_h12.py` · Results:
`research/v2/h12_results.json` · Engine: `gold/hyp/h12_multi_tsmom.py`, `gold/hyp/weekly.py` · Data:
`load_h12` (v1b clock rule, D1 at 17:00 New York), TRAIN_D1 and DEV only; FINAL_OOS never loaded.

**Disclosure: costs, commission and swaps come from MetaQuotes-Demo; a live-broker check is required
before any live use.**

## Verdict
**NOT SUPPORTED** — all four pass conditions fail: TRAIN_D1 net Sharpe -0.28 (≥ 0.30 required),
DEV net Sharpe -0.97 (> 0 required), TRAIN net P&L -0.875 log (> 0 required). Gross of all
costs the TRAIN Sharpe is -0.001: the signal itself earned nothing before cost and financing.
Per the owner decision (ROADMAP_V2 §8), the systematic-strategy programme ends here.

## Pre-declared results (1× cost, net of cost and financing; no significance test)
| Condition | TRAIN_D1 | DEV | Required | Result |
|---|---|---|---|---|
| Net Sharpe (SE) | -0.280 (0.251) | -0.970 (0.563) | TRAIN ≥ 0.30, DEV > 0 | **FAIL** both |
| TRAIN net P&L; largest era share | -0.875 log | — | > 0; ≤ 60 % | **FAIL** (total < 0) |
| Largest symbol share of TRAIN net P&L | total < 0 | — | ≤ 30 % of a positive total | **FAIL** |

## Metrics per arm (portfolio, annualised with the measured sessions per year)
TRAIN_D1 2004-06-21 → 2020-12-31 (259.9 sessions/yr); DEV 2021-01-11 → 2025-09-01. 2× doubles cost and financing.

| Arm | Series | Cost | Sharpe | SE | CAGR | Max DD | Longest underwater | Realised vol | Turnover/yr |
|---|---|---|---|---|---|---|---|---|---|
| TRAIN_D1 | gross | — | -0.001 | 0.246 | -0.0 % | 46.2 % | 1,956 d | 18.9 % | 90.2 |
| TRAIN_D1 | net of cost | 1× | -0.053 | 0.246 | -1.0 % | 49.5 % | 1,956 d | 18.9 % | 90.2 |
| TRAIN_D1 | net of cost + financing | 1× | -0.280 | 0.251 | -5.2 % | 67.7 % | 3,431 d | 18.9 % | 90.2 |
| TRAIN_D1 | net of cost | 2× | -0.105 | 0.247 | -2.0 % | 52.6 % | 1,956 d | 18.9 % | 90.2 |
| TRAIN_D1 | net of cost + financing | 2× | -0.560 | 0.265 | -10.0 % | 84.8 % | 5,880 d | 18.9 % | 90.2 |
| DEV | gross | — | -0.526 | 0.495 | -8.9 % | 45.7 % | 1,615 d | 17.8 % | 112.0 |
| DEV | net of cost | 1× | -0.599 | 0.504 | -10.1 % | 48.5 % | 1,650 d | 17.8 % | 112.0 |
| DEV | net of cost + financing | 1× | -0.970 | 0.563 | -15.9 % | 61.0 % | 1,650 d | 17.8 % | 112.0 |
| DEV | net of cost | 2× | -0.672 | 0.514 | -11.3 % | 51.1 % | 1,650 d | 17.8 % | 112.0 |
| DEV | net of cost + financing | 2× | -1.414 | 0.657 | -22.3 % | 72.7 % | 1,650 d | 17.8 % | 112.0 |

N_t: TRAIN 13–29 active symbols (29 in 576 of 864 weeks); DEV 29 throughout.

## Net P&L per TRAIN era (log units)
| Era | Gross | Net of cost 1× | Net of cost + fin. 1× | Net of cost 2× | Net of cost + fin. 2× |
|---|---|---|---|---|---|
| 2004-06 → 2008 (from 2004-06-21) | +0.232 | +0.199 | +0.107 | +0.166 | -0.019 |
| 2009 → 2012 | -0.032 | -0.066 | -0.180 | -0.100 | -0.328 |
| 2013 → 2016 | +0.126 | +0.083 | -0.137 | +0.040 | -0.400 |
| 2017 → 2020 | -0.329 | -0.381 | -0.664 | -0.434 | -1.000 |
| Total | -0.003 | -0.165 | -0.875 | -0.327 | -1.747 |

## Net P&L per symbol (1×, net of cost and financing, log units)
| Symbol | TRAIN | DEV | Symbol | TRAIN | DEV | Symbol | TRAIN | DEV |
|---|---|---|---|---|---|---|---|---|
| XAUUSD | +0.120 | +0.021 | GBPJPY | +0.105 | -0.015 | EURCHF | +0.075 | -0.021 |
| XAGUSD | +0.058 | -0.061 | EURUSD | +0.036 | +0.003 | USDCAD | +0.034 | -0.018 |
| EURJPY | +0.019 | -0.019 | NZDJPY | -0.000 | -0.044 | USDJPY | -0.004 | +0.058 |
| NZDCAD | -0.005 | -0.086 | GBPUSD | -0.011 | +0.009 | CHFJPY | -0.018 | +0.041 |
| EURGBP | -0.020 | -0.061 | NZDUSD | -0.024 | -0.053 | GBPCAD | -0.031 | -0.037 |
| CADJPY | -0.037 | +0.011 | EURNZD | -0.043 | -0.039 | GBPAUD | -0.056 | -0.048 |
| AUDUSD | -0.061 | -0.063 | GBPCHF | -0.069 | -0.033 | AUDNZD | -0.075 | -0.064 |
| AUDCAD | -0.087 | -0.089 | EURCAD | -0.092 | -0.012 | AUDJPY | -0.098 | -0.040 |
| AUDCHF | -0.105 | -0.066 | USDCHF | -0.107 | +0.006 | EURAUD | -0.117 | -0.055 |
| NZDCHF | -0.127 | -0.018 | CADCHF | -0.133 | -0.010 |  |  |  |
7 of 29 symbols are positive in TRAIN, 7 of 29 in DEV.

## Controls
Independent FX price check (step 0): FRED H.10 noon rates vs broker D1 closes, Friday-to-Friday
weekly log returns, 1999 (NZDUSD 2000) → 2025-08-29, threshold 0.95 — all pass:
| EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | USDCHF | NZDUSD |
|---|---|---|---|---|---|---|
| 0.976 | 0.977 | 0.979 | 0.978 | 0.962 | 0.973 | 0.978 |

## Evidence against (spec §9) — observed
Every pass condition fails. Gross P&L is about zero in TRAIN and negative in DEV, so no cost
assumption could rescue it; costs and financing only deepen the loss.

## Limitations
- The universe is 27 FX pairs from 8 currencies plus gold and silver; the equity-index, bond and
  commodity trends behind the external evidence are not tradable at this broker.
- Financing uses today's demo swaps as constant rates with credits ignored; it is the largest drag
  (TRAIN −0.710 log over 16.5 years, about −4.3 %/yr), and real historical swaps differed.
- Broker history has gaps (AUDJPY/CHFJPY/GBPCHF Oct–Nov 2006, CADCHF/EURNZD Sep–Dec 2008, six
  crosses Jan 2009, EURCHF Jan 2015, NZD crosses single weeks): those symbols skip decisions and
  the held position earns the whole gap on the first session back.
- Positions target 10 %/√N per symbol with no correlation adjustment; realised portfolio volatility
  was 18.9 % (TRAIN) and 17.8 % (DEV).
- Sharpe SEs are about 0.25 (TRAIN) and 0.56 (DEV).

## Changes
