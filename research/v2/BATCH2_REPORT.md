# V2 batch 2 — H10 time-series momentum, H11 volatility-managed exposure — report

Specs: `research/v2/H10_SPEC.md`, `research/v2/H11_SPEC.md` at commit `3fffc24` · Script:
`research/v2/run_batch2.py` · Results: `research/v2/batch2_results.json` · Engine: `gold/hyp/weekly.py`,
`gold/hyp/h10_tsmom.py`, `gold/hyp/h11_vol_managed.py` · Data: broker v1b D1 (17:00 NY) from H4;
TRAIN_D1 and DEV only, FINAL_OOS never loaded. Standard: external-prior confirmation (§5 rule 5).

## Verdict
**H10 NOT SUPPORTED** — net Sharpe is positive in both arms (TRAIN_D1 0.27, DEV 0.03), but
2009–2012 supplies 62.6 % of TRAIN net P&L, above the 60 % cap.
**H11 NOT SUPPORTED** — its max drawdown is worse than buy-and-hold in both arms (56.3 % vs
50.5 %; 25.4 % vs 22.6 %), its DEV Sharpe is below buy-and-hold's (0.535 vs 0.549), and its
TRAIN excess P&L over buy-and-hold is negative.

## Pre-declared results (1× cost; no significance test, Sharpe SE disclosed)
| Hypothesis | Condition | TRAIN_D1 | DEV | Required | Result |
|---|---|---|---|---|---|
| H10 | net Sharpe (SE) | 0.266 (0.258) | 0.030 (0.463) | > 0 in both | pass |
| H10 | TRAIN net P&L total; largest era share | +0.355 log; 62.6 % | — | > 0; ≤ 60 % | **FAIL** |
| H11 | net Sharpe vs benchmark | 0.320 vs 0.308 | 0.535 vs 0.549 | above in both | **FAIL** (DEV) |
| H11 | max drawdown vs benchmark | 56.3 % vs 50.5 % | 25.4 % vs 22.6 % | below in both | **FAIL** |
| H11 | TRAIN excess net P&L total | −0.096 log | — | > 0, no era > 60 % | **FAIL** |

## Metrics per arm
From the first execution (TRAIN_D1 2005-06-20, after 253 bars of history; DEV 2021-01-11) to the
arm's end. Net of 1 bp per unit of |Δposition| (2×: 2 bp) and nightly financing (long DFF + 2.5 %,
short 2.5 %). Benchmark = buy-and-hold, exposure 1, same rules.

| Arm | Series | Cost | Net Sharpe | SE | CAGR | Max DD | Longest underwater | Turnover / yr | Corr. with B&H |
|---|---|---|---|---|---|---|---|---|---|
| TRAIN_D1 | H10 | 1× | 0.266 | 0.258 | 2.3 % | 32.1 % | 2,744 d | 9.17 | 0.34 |
| TRAIN_D1 | H10 | 2× | 0.255 | 0.258 | 2.2 % | 32.5 % | 2,744 d | 9.17 | 0.34 |
| TRAIN_D1 | H11 | 1× | 0.320 | 0.260 | 5.1 % | 56.3 % | 3,419 d | 4.61 | 0.92 |
| TRAIN_D1 | H11 | 2× | 0.317 | 0.260 | 5.1 % | 56.4 % | 3,419 d | 4.61 | 0.92 |
| TRAIN_D1 | Buy-and-hold | 1× | 0.308 | 0.260 | 5.8 % | 50.5 % | 3,405 d | 0.06 | 1.00 |
| DEV | H10 | 1× | 0.030 | 0.463 | 0.3 % | 25.6 % | 1,552 d | 8.41 | 0.51 |
| DEV | H10 | 2× | 0.021 | 0.463 | 0.2 % | 25.8 % | 1,552 d | 8.41 | 0.51 |
| DEV | H11 | 1× | 0.535 | 0.495 | 8.5 % | 25.4 % | 769 d | 5.40 | 0.97 |
| DEV | H11 | 2× | 0.532 | 0.494 | 8.4 % | 25.4 % | 773 d | 5.40 | 0.97 |
| DEV | Buy-and-hold | 1× | 0.549 | 0.496 | 8.4 % | 22.6 % | 763 d | 0.21 | 1.00 |

## Controls — net P&L per TRAIN era (1×, log units)
| Era | H10 net | H10 share | H11 net | Buy-and-hold net | H11 excess |
|---|---|---|---|---|---|
| 2004-06 → 2008 (from 2005-06-20) | +0.168 | 47.5 % | +0.371 | +0.453 | −0.082 |
| 2009 → 2012 | +0.222 | **62.6 %** | +0.626 | +0.555 | +0.072 |
| 2013 → 2016 | −0.137 | −38.7 % | −0.651 | −0.482 | −0.169 |
| 2017 → 2020 | +0.101 | 28.6 % | +0.426 | +0.343 | +0.083 |
| Total | +0.355 | | +0.773 | +0.869 | −0.096 |

Buy-and-hold era values are H11 minus H11 excess. Broker swap today (MT5 symbol_info, reference
only, not used): swap_long −12.6, swap_short −4.6 (swap_mode 1, points).

## Economics
Costs barely matter at these turnovers: 2× cost moves H10's Sharpe by about 0.01 and H11's by ≤ 0.004.
Financing is the larger drag on long exposure (DFF + 2.5 %/yr on notional).

## Evidence against (spec §9) — observed
H10: the era rule fails (2009–2012 above 60 %), and DEV Sharpe 0.03 is near zero with SE 0.46.
H11: drawdown worse than buy-and-hold in both arms; DEV Sharpe below buy-and-hold; TRAIN excess
P&L negative, losing in 2004–08 and 2013–16.

## Limitations
- One instrument: Sharpe SEs of 0.26 (TRAIN_D1) and 0.46–0.50 (DEV) are as large as the Sharpes;
  the external-prior standard judges signs and era balance, not significance.
- Broker bars only (bid prices); D1 built from H4; the pre-2009 clock convention is unconfirmed
  (negligible at daily resolution).
- Costs are a flat 1 bp of price per unit traded, not measured historical spreads.
- Financing is the spec's model (DFF + 2.5 % / 2.5 %), not the broker's historical swaps.
- The 2004–08 era starts 2005-06-20 because H10/H11 need 253 bars of history.

## Changes
