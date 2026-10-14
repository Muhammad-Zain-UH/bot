# Gold and V2 programme — conclusion

**Programme closed 2026-10-13: no strategy survived.** Every pre-registered test, from the legacy
audits through V2 batch 2 and the final multi-asset hypothesis H12, failed its own pre-declared
rules. Per the owner decision under ROADMAP_V2 §8 the systematic-strategy programme has ended;
there is no live trading.

**FINAL_OOS (2025-09-02 → 2026-10-01) was never opened** by any test in the programme. It remains
unspent and available for one genuinely new hypothesis, pre-registered before it is touched.

## Every pre-registered test in the programme (one line each: verdict — deciding number)

| Test | Verdict | Deciding number |
|---|---|---|
| Production-path audit (21 SMC/ICT layer hypotheses) | NOT SUPPORTED | 0 of 21 survive Bonferroni/BH; max \|t\| 1.338 |
| Original continuation audit (bias + displacement/structure) | NOT SUPPORTED | confirmation layers subtract from bias alone at every horizon |
| H01 compression → breakout → expansion | NOT SUPPORTED | max \|t\| 0.644 vs corrected 2.394; DEV negative at all horizons |
| H02 failed breakout → reversal | INCONCLUSIVE (underpowered) | max \|t\| 0.459 vs 2.394; MDE 0.169–0.530 ATR vs cost 0.093–0.158 |
| H03 volatility-state transition | NOT SUPPORTED | max \|t\| 2.166 vs 2.773; only powered cell +0.0996 ATR < cost 0.158 |
| H04 liquidity displacement | NOT SUPPORTED | max \|t\| 1.973 vs 3.144; 0 of 138 programme tests survive |
| H05 slow trend-conditional exposure | NOT SUPPORTED | TRAIN drawdown gain 4.97 pp vs 5.00 pp required; Sharpe 0.260 vs hold 0.313 |
| H06 real-yield-conditional exposure | NOT SUPPORTED | DEV Sharpe 0.193 vs hold 0.868 |
| H08 intraday momentum into COMEX settlement | NOT SUPPORTED | TRAIN t = 0.48 (p = 0.63, N 2,798); DEV net −$0.21/oz per trade |
| H10 time-series momentum (long/short) | NOT SUPPORTED | 2009–12 = 62.6 % of TRAIN P&L (cap 60 %); DEV Sharpe 0.03 |
| H11 volatility-managed long exposure | NOT SUPPORTED | max drawdown worse than hold (56.3 % vs 50.5 % TRAIN; 25.4 % vs 22.6 % DEV) |
| H12 multi-asset TSMOM (27 FX + gold + silver) | NOT SUPPORTED | net Sharpe −0.28 TRAIN (≥ 0.30 required), −0.97 DEV; gross TRAIN Sharpe −0.001 |

H07 and H09 were parked before any outcome was seen (not testable on broker H1, `research/POWER_V2.md`).

## Buy-and-hold, the bar every exposure rule had to beat
Broker v1b D1, net of financing (DFF + 2.5 %/yr) and 1 bp entry cost (H11 benchmark,
`research/v2/batch2_results.json`):

| Arm | Period | Net Sharpe (SE) | Max drawdown | CAGR |
|---|---|---|---|---|
| TRAIN_D1 | 2005-06-20 → 2020-12-31 | 0.308 (0.260) | 50.5 % | 5.8 % |
| DEV | 2021-01-11 → 2025-09-01 | 0.549 (0.496) | 22.6 % | 8.4 % |

H05 and H06 used the earlier H1 split without financing (hold Sharpe 0.313 / 1.076 and 0.383 /
0.868), so their hold figures differ from these.

## Data facts established along the way
- **Broker clock**: server = New York + 7 h before 2020-07-01, Europe/Athens time from then on
  (US switch dates, then EU switch dates). `data/research_v1`'s fixed −3 h labels US-winter
  bars 1 h early; `data/research_v1b` corrects it, with `utc_suspect` flagging 7 TRAIN weeks.
- **Costs**: k_cost = 4.625 (median tick spread $0.37 / median H1 bar spread $0.08, week of
  2026-10-05). Bar spread_usd is zero or missing in 85–100 % of 2009–10 and 18–26 % of 2021–22.
- **Sessions**: the broker's daily break is now 16:00–18:00 New York (17:00–18:00 through DEV);
  intraday sleeves must be flat by 15:55 NY.
- **Data reach**: broker H1 from 2009-08, H4 from 2004-06; Dukascopy (2003–) remains blocked.
- **Reopen bid artifact** (REGIME_2026_EXPLORATION §H): first quote after the reopen at a $13.78 median spread since July 2026; first hour +30.8 × 10⁻⁴ on bid bars, −1.1 on mid, −33.4 for a buyer at the ask (all 285 weekday
  reopens: −4.2). It inflates "Asia up, US down", so H15's NOT SUPPORTED is conservative (H14 never ran); ticks start 2025-05-27, so TRAIN/DEV bias is unmeasured.

## What this does and does not show
- It shows that none of these rules beat cash (long/short) or holding gold (exposure rules) in
  both arms, after realistic cost and financing.
- It does not show that gold has no edge at all: single-instrument Sharpe SEs of 0.26–0.50
  cannot resolve a true Sharpe of 0.3–0.5. Breadth (H12) was tried on everything tradable at
  this broker and its signal earned nothing even before cost.
