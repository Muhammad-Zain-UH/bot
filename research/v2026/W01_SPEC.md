# W01 — walk-forward selection: does the setup that works now keep working?

One page. Committed alone, before the script that computes its results.

## 1. ID and name
- **ID:** W01, a walk-forward selection process on XAUUSD. It tests no paper. It tests the owner's idea that a bot should pick, from current data, the setup that is working now.
- **Status:** a process study under the 2026-10-14 exploration authorisation, which opened FINAL_OOS. No arm is clean; the only clean validation is a forward demo test.

## 2. Mechanism and external evidence
- **For:** factor and strategy returns show momentum (Gupta & Kelly 2019; Ehsani & Linnainmaa 2022). If setups have regimes, recent winners should keep winning.
- **Against:** technical-rule edges shrink after data-snooping control (Sullivan, Timmermann & White 1999). Selecting the best of many backtests mostly selects noise (Bailey et al. 2014).
- **Prior in this repo:** every single-rule gold hypothesis was NOT SUPPORTED (`research/v2/CONCLUSION_GOLD.md`).

## 3. Data and months
- **H1:** broker v1b H1, arms TRAIN, DEV and FINAL_OOS concatenated (token `OPENED-2026-10-14-EXPLORATION`), 2009-08-31 → 2026-10-01. The incomplete last bar (2026-10-01 11:00 UTC) is dropped.
- **D1:** `daily_bars` of v1b H4 over the same arms, with the session boundary at 17:00 New York.
- **Evaluation months:** 2011-01 → 2026-09 (n = 189). Everything earlier is warm-up.

## 4. Exact construction
- **Reopen rule (CLAUDE.md rule 8):**
  - The reopen bar is the first H1 bar after a gap of 2 h or more; it is never a signal bar or an entry bar.
  - H1 signals form at a bar close and enter at the next bar's open; the trade is skipped if that bar is a reopen bar.
  - D1 signals form at the session close and enter at the open of the H1 bar starting 60 minutes after the session's reopen.
- **Trade management:**
  - One trade per variant at a time; new signals are ignored while a trade is open.
  - Stops and targets are checked on H1 bars from the entry bar. A stop fills at the stop, or at the bar's open if the bar gaps through it; a target fills at the target. If both fall in one bar, the stop counts.
  - Signal exits and time exits fill at a bar close (D1: the session's last H1 close). Trades still open at the end of the data close at the last bar's close.
- **ATR(14):** the mean true range of the last 14 bars of the signal timeframe, read at the signal bar.
- **Net R:** (side × (exit − entry) − cost_usd − financing_usd) / |entry − stop|, where:
  - cost_usd = `round_turn_cost_usd(s_entry, s_exit, k_cost = 4.625)`; zero or missing bar spreads are filled with that New York hour's median (`gold.econ.power.filled`);
  - financing_usd = `financing_usd(entry, nights, side, DFF/100)`, where nights = calendar days between the 17:00 New York sessions of entry and exit, and DFF is the effective fed funds rate as of the entry day;
  - at 2× cost, cost and financing are both doubled.

**Menu: 102 variants.** Long and short are separate variants; "k" is the ATR stop multiple, 1.0 or 1.5.
| Family | Rule (signal at a bar close) | Exit (besides the stop) | Parameters | n |
|---|---|---|---|---|
| a Donchian | close > highest high (long) or < lowest low (short) of the previous N bars | close beyond the opposite ⌈N/2⌉-bar extreme; or 2N bars | TF {H1, D1} × N {10, 20, 55} × k × side | 24 |
| b MA trend | SMA(fast) crosses above (long) or below (short) SMA(slow) | opposite cross; or `slow` bars | TF × (fast, slow) {(10,50), (20,100), (50,200)} × k × side | 24 |
| c Mean reversion | RSI(2, Wilder) < 10 (long) or > 90 (short); or close below (long) or above (short) the Bollinger(20, 2) band | close back at SMA(20); or 5 bars | {RSI, Bollinger} × TF × k × side | 16 |
| d Session breakout | range = the H1 bar opening 08:00 Europe/London (London) or 08:00 America/New_York (New York). First H1 close beyond the range from a bar opening before 13:00 NY; stop = the opposite edge of the range | close of the H1 bar opening 14:00 NY (flat by 15:55) | {London, New York} × side | 4 |
| e Liquidity sweep | an H1 bar trades beyond the previous session's high (short) or low (long) and closes back inside; first per session; stop = the sweep bar's extreme | 1R, 2R, or the previous session's midpoint (skipped if not in profit direction); 24 bars | side × target | 6 |
| f Fair value gap | 3-bar gap (bar-1 high < bar-3 low, or the mirror), no reopen bar among the three, gap ≥ 0.25 × ATR(14, H1). Limit at the gap's near edge, valid 24 bars, cancelled if hit on a reopen bar; stop = the far edge | 1R or 2R; 24 bars after entry | side × target × filter {none, D1 close vs SMA(50)} | 8 |
| g Time of day | enter at the open of the H1 bar starting each 4-hour New York block: 19:00, 23:00, 03:00, 07:00, 11:00 (the first block starts 60 minutes after the 18:00 reopen) | close of the block's last H1 bar | block × k × side | 20 |

**Selection (primary, fixed).**
- **Monthly R:** a variant's monthly net R is the sum of net R over trades entered that month, held to their exits.
- **Score:** at each month-end, each variant's score is the t-statistic of its mean net R per trade over trades entered in the last 6 months and closed by then. A variant needs ≥ 5 trades and sd > 0 to be eligible.
- **Trade:** next month, trade only the top-scoring variant (ties go to the lower variant id). If no variant is eligible, the process holds cash (0 R).
- **At 2× cost**, scores and outcomes both use 2× cost.

## 5. Tests (n = 189 months; Newey–West 3 lags; one-sided, Student-t with n − 1 degrees of freedom)
| # | Statistic | Required |
|---|---|---|
| 1 | Mean monthly net R of the process at 1× | > 0, p < 0.05 |
| 2 | Mean monthly net R of the process at 2× | ≥ 0 |
| 3 | Process mean vs 2,000 random paths (each month, a uniformly random eligible variant; seed 20261015) | above the paths' 95th percentile |
| 4 | Mean monthly IC: Spearman of the variants' 6-month scores vs their next-month net R (eligible variants, months with ≥ 5) | > 0, p < 0.05 |
| 5 | Process mean monthly net R by era: 2011–2015, 2016–2020, 2021 → 2026-09 | > 0 in ≥ 2 eras |

## 6. Verdict
**WORKS** only if tests 1–5 all hold; **DOES NOT WORK** otherwise. WORKS would lead only to a forward demo test, never to live trading.

## 7. Informational only (no verdict weight)
- Lookbacks of 3 and 12 months.
- Top-3 equal weight.
- How often each family is chosen.
- Buy-and-hold gold (D1 closes) and cash.
- The 10 best variants over the whole period, labelled "hindsight only — not tradable, chosen after the fact".

## 8. Evidence against / known weaknesses
- With 102 variants, a 6-month lookback rewards luck. The random control (test 3) is the guard against that.
- Bars are bid-based and costs are modelled from bar spreads at k_cost. Intrabar ordering is conservative (stop first).
- No power pre-check was run: the prompt asked for none. A miss with wide confidence intervals would leave the idea untested rather than refuted.
