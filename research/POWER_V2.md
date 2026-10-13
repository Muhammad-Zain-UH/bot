# V2 power pre-check — broker v1b (H07–H11)

**Verdict: batch 1 = H08 alone (owner decision 2026-10-13, blind to outcomes). H08 is
TESTABLE in TRAIN (MDE / cost 0.87 at z = 1.96); DEV has 62 % power at an effect of 1×
cost. H07 and H09 are parked. H10 and H11 follow the external-prior standard (§5 rule 5).**

Data: `data/research_v1b` (`load_broker_v1b`); statistics on TRAIN 2009-08-31 → 2020-12-31,
costs on DEV. Blinded: counts, sds and costs only (`gold/econ/power.py`, `research/power_v2.json`).

## Cost calibration

k_cost = **4.625** = median tick spread $0.37 / median H1 bar spread $0.08 (108 hours,
1,982,669 ticks, 2026-10-05 → 2026-10-09 21:00 UTC, after FINAL_OOS; `gold/data/calibrate_cost.py`).
Cost = k_cost × (bar spread at entry + at exit) / 2 in log units; a zero bar spread is missing.

## Batch 1 as first proposed — z = 2.734 (Bonferroni two-sided, α = 0.05, 8 tests)

MDE = z × sd / √N, log return per trade (×10⁻⁴). "N needed" = days at which MDE = cost.

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

## Batch 1 = H08 only (1 test)

Cost per the H08 spec (12:00 and 13:00 NY bar spreads, zero/missing → that hour's DEV median): 1.271 × 10⁻⁴.

| Arm | N | sd | z | MDE (×10⁻⁴) | MDE / cost | Power at 1× / 1.5× cost |
|---|---|---|---|---|---|---|
| TRAIN | 2,798 | 0.00298 | 1.960 (two-sided) | 1.10 | **0.87** — TESTABLE | — |
| DEV | 1,191 | 0.00225 | 1.645 (one-sided) | 1.07 | 0.84 | 0.62 / 0.90 |

## Batch 2 — Sharpe standard error ≈ √((1 + SR²/2) / years)

| Arm | Weeks | Years | SE at SR 0.3 | SE at SR 0.5 |
|---|---|---|---|---|
| TRAIN_D1 (2004-06-14 → 2020-12-31) | 864 | 16.55 | 0.251 | 0.261 |
| DEV (2021-01-05 → 2025-09-01) | 244 | 4.65 | 0.474 | 0.492 |

SR 0.3–0.5 cannot be significant in either arm (D5); D1 bars from H4, pre-2009 clock unconfirmed.

## Limitations

- DEV power is 62 % at an effect equal to cost: a TRAIN pass with a DEV miss is INCONCLUSIVE.
- k_cost assumes the October 2026 tick-to-bar spread ratio held through DEV; bar spread_usd
  is zero or missing in 100 % (2009), 85 % (2010), 18–26 % (2021–22) of H1 bars, ≤ 7 % otherwise.
- In the calibration week the broker's daily break was 16:00–18:00 NY (DEV: 17:00–18:00);
  intraday sleeves must be flat by 15:55 NY (ROADMAP §7).

## Changes
- 2026-10-13: batch 1 reduced to H08 by owner decision; H08-only power added.
