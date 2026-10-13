# V2 power pre-check — broker v1b (H07–H11)

**Verdict: no batch-1 hypothesis is testable on broker H1. All eight tests have a
minimum detectable effect above the DEV round-turn cost; batch 1 is empty
(0 tests, no z). H10 and H11 proceed under the external-prior standard (§5 rule 5).**

Data: `data/research_v1b` (`load_broker_v1b`); statistics on TRAIN 2009-08-31 → 2020-12-31,
costs on DEV. Blinded: counts, sds and costs only (`gold/econ/power.py`, `research/power_v2.json`).

## Cost calibration

k_cost = **4.625** = median tick spread $0.37 / median H1 bar spread $0.08 (108 hours,
1,982,669 ticks, 2026-10-05 → 2026-10-09 21:00 UTC, after FINAL_OOS; `gold/data/calibrate_cost.py`).
Cost = k_cost × (bar spread at entry + at exit) / 2 in log units; a zero bar spread is missing.

## Batch 1 — z = 2.734 (Bonferroni two-sided, α = 0.05, 8 tests)

MDE = z × sd / √N, in log return per trade (×10⁻⁴). "N needed" = days at which MDE = cost.

| Test | N (TRAIN days) | sd | MDE | DEV cost | MDE / cost | N needed | Verdict |
|---|---|---|---|---|---|---|---|
| H07 B1 18–22 | 2,360 | 0.00301 | 1.70 | 1.31 | 1.29 | 3,945 | NOT TESTABLE |
| H07 B2 22–02 | 2,360 | 0.00284 | 1.60 | 1.29 | 1.24 | 3,619 | NOT TESTABLE |
| H07 B3 02–06 | 2,360 | 0.00378 | 2.13 | 1.28 | 1.66 | 6,491 | NOT TESTABLE |
| H07 B4 06–10 | 2,360 | 0.00533 | 3.00 | 1.26 | 2.38 | 13,334 | NOT TESTABLE |
| H07 B5 10–14 | 2,360 | 0.00511 | 2.88 | 1.27 | 2.27 | 12,168 | NOT TESTABLE |
| H07 B6 14–17 | 2,360 | 0.00283 | 1.59 | 1.29 | 1.24 | 3,609 | NOT TESTABLE |
| H08 (12–14 NY) | 2,798 | 0.00298 | 1.54 | 1.27 | 1.22 | 4,142 | NOT TESTABLE |
| H09 (old-fix era) | 1,382 | 0.00352 | 2.59 | 1.22 | 2.12 | 6,188 | NOT TESTABLE |

All eight are dropped: batch-1 test count **0**, no z. DEV rows without a usable spread: 11–16 %.

## Batch 2 — Sharpe standard error ≈ √((1 + SR²/2) / years)

| Arm | Weeks | Years | SE at SR 0.3 | SE at SR 0.5 |
|---|---|---|---|---|
| TRAIN_D1 (2004-06-14 → 2020-12-31) | 864 | 16.55 | 0.251 | 0.261 |
| DEV (2021-01-05 → 2025-09-01) | 244 | 4.65 | 0.474 | 0.492 |

As D5 expects, SR 0.3–0.5 cannot be significant in either arm; H10/H11 are judged on sign in
both arms and the 60 % era rule. TRAIN_D1 D1 bars come from H4 (pre-2009 clock unconfirmed).

## spread_usd completeness, v1b H1 (share zero or missing)

2009 100 %, 2010 85 %, 2011 11 %, 2012 7 %, 2013–2020 ≤ 2.2 %, 2021 18.5 %,
2022 26 %, 2023 4.1 %, 2024–2025 0.1 %.

## Limitations

- The closest cases (B2, B6, H08: MDE/cost 1.22–1.24) would need about 3,600–4,100 TRAIN
  days; Dukascopy 2003–2016 has about 3,400, so it would not make them testable by itself.
- k_cost assumes the tick-to-bar spread ratio of October 2026 held through DEV;
  the bar spread field is a broker-defined summary and is zero in 18–26 % of 2021–22 bars.
- H07 needs the 16:00 New York bar, which is missing on most 2010 days and on about 8 % of
  Mon–Thu days in other years; this cuts H07's N to 2,360 (H08: 2,798).
- In the calibration week the broker's daily break was 16:00–18:00 New York (DEV shows
  17:00–18:00); live sessions end an hour earlier than the research data assumes.
- H09 also drops days with r_pre = 0, by analogy with H08's r_early rule.

## Changes
