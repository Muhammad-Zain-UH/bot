# Breadth feasibility — broker metadata only

**Verdict: breadth at this broker means FX plus two metals. 29 symbols pass the filters (27 FX majors/
crosses, XAUUSD, XAGUSD); all 26 index CFDs are disabled for trading on this account, and no energy,
agricultural or bond CFD is offered. An equal-risk book at 10 % volatility needs about $4.8k of equity for
10 symbols, $9.1k for 20, $42.5k for 25 and $86.6k for all 29 (including gold and silver).**

Source: MT5 metadata, `order_calc_profit` (no order sent) and D1/H4 history, 2026-10-13 (`research/v2/breadth_feasibility.py`;
all fields per symbol in `breadth_metadata.csv`). No strategy return, P&L or Sharpe was computed for any instrument.

## Universe (account currency USD, leverage 1:100)
| Category | Offered | Full trading | D1 history ≤ 2010-01-01 and full trading |
|---|---|---|---|
| Indices | 26 | 0 | 0 |
| Metals | 10 | 7 | 2 |
| FX majors/crosses (8 currencies) | 28 | 28 | 27 |
| Energies, agriculturals, bonds | 0 | — | — |

Excluded: all indices (trade_mode 0); GBPNZD (D1 from 2010-05-10); XAUEUR, XAGEUR (2012), XPDUSD, XPTUSD (2015),
XAUAUD (2017); XAGAUD, XAUCHF, XAUGBP (disabled). Swap mode for every kept symbol: points per lot per night,
converted to % of notional with MT5's per-point value × 365 nights. MT5's `trade_tick_value` is 10× too small
for XAUUSD/XAGUSD (as `core/symbols.py` already documents), so notional uses `order_calc_profit`.

## Kept symbols (sorted by the equity each one needs)
σ = annualised vol of 252 D1 returns ending 2025-09-01; E₁ = 2 × volume_min × lot notional × σ / 0.10 (×√N);
volume_min 0.01 lots except NZDCAD, NZDCHF, NZDJPY (0.1). Margin currency and the rest: CSV.
| Symbol | Spread bp | Swap L / S %/yr | First D1 | σ | E₁ $ | Symbol | Spread bp | Swap L / S %/yr | First D1 | σ | E₁ $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDNZD | 0.24 | -0.73 / -4.46 | 1993-04-05 | 0.041 | 569 | AUDCAD ⚠ | 0.50 | +2.35 / -5.65 | 1993-04-27 | 0.075 | 1,046 |
| CADCHF | 1.20 | +0.13 / -0.75 | 1993-05-19 | 0.081 | 1,135 | USDCAD | 0.00 | -0.21 / -0.10 | 1993-04-28 | 0.058 | 1,152 |
| NZDUSD | 0.18 | +1.82 / -4.36 | 1994-02-01 | 0.104 | 1,167 | EURGBP | 0.12 | -0.52 / -0.17 | 1993-05-03 | 0.054 | 1,206 |
| EURCHF | 0.32 | +0.04 / -0.67 | 1993-04-28 | 0.055 | 1,229 | CADJPY | 0.63 | -0.36 / -0.30 | 2007-02-12 | 0.102 | 1,436 |
| AUDUSD ⚠ | 0.14 | +3.30 / -7.75 | 1993-04-27 | 0.104 | 1,448 | AUDCHF ⚠ | 0.52 | +4.46 / -9.93 | 1993-05-14 | 0.108 | 1,512 |
| EURCAD | 0.19 | -0.25 / -0.21 | 1999-08-02 | 0.069 | 1,534 | EURNZD | 0.35 | -3.13 / +1.21 | 1999-01-05 | 0.074 | 1,653 |
| AUDJPY | 0.27 | +1.85 / -4.24 | 1993-05-17 | 0.119 | 1,665 | GBPCAD | 0.32 | -1.28 / +0.35 | 2007-08-21 | 0.065 | 1,732 |
| USDCHF | 0.24 | +0.04 / -0.44 | 1971-01-04 | 0.093 | 1,847 | EURAUD ⚠ | 0.19 | -5.35 / +2.18 | 2004-06-17 | 0.084 | 1,876 |
| EURUSD | 0.00 | -0.23 / -0.33 | 1971-01-04 | 0.086 | 1,931 | CHFJPY | 0.37 | -0.10 / -0.02 | 1992-02-19 | 0.081 | 1,949 |
| EURJPY | 0.17 | -0.04 / -0.25 | 1993-04-27 | 0.088 | 1,969 | GBPAUD | 0.42 | -4.02 / +1.38 | 2007-08-21 | 0.077 | 2,033 |
| GBPUSD | 0.08 | -0.06 / -0.61 | 1993-05-12 | 0.077 | 2,047 | GBPCHF | 0.27 | +0.26 / -1.03 | 1993-04-07 | 0.078 | 2,079 |
| USDJPY | 0.13 | -0.02 / -0.14 | 1971-01-04 | 0.110 | 2,174 | GBPJPY | 0.29 | +0.05 / -0.38 | 1993-04-19 | 0.094 | 2,499 |
| NZDCAD | 0.63 | -1.37 / -3.24 | 2007-08-20 | 0.076 | 8,501 | NZDCHF ⚠ | 0.64 | -2.19 / -5.32 | 2007-08-21 | 0.097 | 10,907 |
| NZDJPY | 0.56 | -1.15 / -2.51 | 2007-02-12 | 0.109 | 12,284 | XAUUSD | 1.05 | -1.10 / -0.40 | 2004-06-11 | 0.174 | 14,546 |
| XAGUSD | 2.99 | -1.39 / +0.12 | 2008-11-07 | 0.267 | 16,090 |  |  |  |  |  |  |

## Minimum equity for N tradable symbols (target position ≥ 2 × volume_min)
| N | Min equity | Symbols added beyond the previous row |
|---|---|---|
| 10 | $4,780 | AUDNZD, AUDCAD, CADCHF, USDCAD, NZDUSD, EURGBP, EURCHF, CADJPY, AUDUSD, AUDCHF |
| 15 | $7,155 | EURCAD, EURNZD, AUDJPY, GBPCAD, USDCHF |
| 20 | $9,092 | EURAUD, EURUSD, CHFJPY, EURJPY, GBPAUD |
| 25 | $42,507 | GBPUSD, GBPCHF, USDJPY, GBPJPY, NZDCAD |

⚠ = swap costs more than 5 %/yr on one side: AUDCAD, AUDCHF, AUDUSD, EURAUD, NZDCHF.

## Limitations
- 27 of 29 kept symbols are FX built from 8 currencies, so the effective number of independent bets is far below 27.
- The asset classes of the external evidence for breadth (equity indices, bonds, commodities) are not tradable here.
- Notional, spreads, swaps are today's; σ is the year to 2025-09-01; the N = 25 jump is NZDCAD's 0.1-lot minimum.
- Gold's broker swap today is −1.10 %/yr long, far below the V2 financing model (DFF + 2.5 %).

## Index CFDs (2026-10-13; `research/v2/breadth_indices.py`, all fields in `breadth_indices.csv`)
All 26 have trade_mode **0 = disabled**. First D1 = first H4 for each; spread in bp of live bid; swap %/yr of notional.
| Index | First D1/H4 | Contract | vol min/step | Spread bp | Swap L / S % | Index | First D1/H4 | Contract | vol min/step | Spread bp | Swap L / S % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AUS200 | 2019-04-29 | 10 | 0.1/0.1 | 2.27 | -2.83 / -0.17 | CA60 | 2020-04-29 | 1 | 1/1 | 3.81 | -1.39 / -1.04 |
| CHINA50 | 2007-01-04 | 1 | 0.1/0.1 | 4.22 | -2.96 / -2.45 | CHINAH | 2017-03-13 | 1 | 1/1 | 3.67 | -5.00 / +0.31 |
| DE40 | 2012-08-06 | 1 | 0.1/0.1 | 0.20 | -1.01 / -1.61 | ESP35 | 2019-04-29 | 1 | 1/1 | 24.64 | disabled |
| EUSTX50 | 2019-04-29 | 1 | 1/1 | 3.06 | disabled | FRA40 | 2019-04-29 | 1 | 1/1 | 2.04 | disabled |
| HK50 | 2019-10-23 | 1 | 1/1 | 3.70 | disabled | IT40 | 2012-08-06 | 1 | 0.1/0.1 | 1.99 | -0.85 / -1.36 |
| JPN225 | 2019-04-29 | 100 | 1/1 | 1.33 | disabled | MIDDE50 | 2014-11-13 | 1 | 1/1 | 6.61 | -1.76 / -2.81 |
| NETH25 | 2011-09-20 | 1 | 1/1 | 0.88 | -1.29 / -1.93 | NOR25 | 2020-04-29 | 1 | 1/1 | 4.54 | -2.21 / -0.74 |
| SA40 | 2020-04-28 | 1 | 1/1 | 0.98 | -3.94 / +0.57 | SE30 | 2020-04-20 | 1 | 1/1 | 1.34 | -1.89 / -1.00 |
| SWI20 | 2012-03-22 | 1 | 1/1 | 0.57 | -1.38 / -2.42 | TECHDE30 | 2015-06-01 | 1 | 1/1 | 163.16 | -1.48 / -2.31 |
| UK100 | 2020-09-23 | 10 | 0.1/0.1 | 1.08 | -1.82 / -0.71 | US2000 | 2012-08-06 | 1 | 1/1 | 19.63 | -1.95 / -1.82 |
| US30 | 2012-08-06 | 1 | 0.1/0.1 | 0.23 | -1.55 / -1.40 | US30M | 2021-11-22 | 0.1 | 1/1 | 0.38 | disabled |
| US500 | 2012-08-06 | 1 | 0.1/0.1 | 0.64 | -1.45 / -1.22 | US500M | 2019-12-17 | 10 | 1/1 | 4.48 | disabled |
| USTEC | 2022-07-06 | 1 | 0.1/0.1 | 0.33 | -0.98 / -0.90 | USTECH100M | 2020-06-01 | 1 | 1/1 | 0.92 | disabled |

Only **CHINA50** (D1 from 2007) meets the 2010 rule; as if enabled: N = 10/15/20 unchanged, N = 25 $37,228 (was $42,507), all 30 $88,127.
