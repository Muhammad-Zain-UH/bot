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

## Batch 3 — H13a, H13b, H14 (owner decision 2026-10-14) — z = 2.498 (Bonferroni, 4 V2 tests)

H13: round-minus-control difference, SE = √(sd_r²/N_r + sd_c²/N_c); cost = DEV round-level events.
H14: cost per day = two round trips. Costs k_cost 4.625, zero spread → NY-hour DEV median. ×10⁻⁴ log.

| Test | TRAIN N (round / control) | sd (round / control) | MDE | DEV cost | MDE / cost | DEV MDE / cost | DEV power 1× / 1.5× | Verdict |
|---|---|---|---|---|---|---|---|---|
| H13a | 568 / 1168 | 0.0078 / 0.0074 | 9.83 | 1.22 | 8.07 | 4.71 | 0.10 / 0.13 | NOT TESTABLE |
| H13b | 305 / 535 | 0.0055 / 0.0065 | 10.58 | 1.22 | 8.69 | 6.75 | 0.08 / 0.10 | NOT TESTABLE |
| H14 | 2,775 days | 0.0094 | 4.45 | 2.60 | 1.72 | 1.59 | 0.27 / 0.46 | NOT TESTABLE |

**All three dropped**: the V2 test count returns to 1 (H08) and z to 1.96. Even at z = 1.96 none would
be testable (H14 MDE / cost 1.35; H13a 6.3; H13b 6.8). Nothing in batch 3 is pre-registered.

## H15 — Asia vs US session (owner decision 2026-10-15) — z = 2.241 (Bonferroni, 2 V2 tests: H08, H15)

Cost = two round trips per day (median DEV 2.62 × 10⁻⁴ log; long-Asia-only 1.30).
Owner power rule for H15, declared before this check: TESTABLE if MDE ≤ 2 × cost (published claims put the effect ≥ 2.5 × cost).

| Arm | N days | sd(y) | z | MDE (×10⁻⁴) | MDE / cost | DEV power at 1× / 2× / 2.5× cost |
|---|---|---|---|---|---|---|
| TRAIN | 2,846 | 0.0080 | 2.241 (two-sided) | 3.37 | **1.29** — TESTABLE (≤ 2) | — |
| DEV | 1,198 | 0.0076 | 1.645 (one-sided) | 3.61 | 1.38 | 0.33 / 0.77 / 0.91 |

Under the earlier rule (MDE ≤ cost) H15 would not be testable; the 2× rule follows H14 (a similar
variable, MDE / cost 1.72 at z = 2.498), so it is not blind to that power result. No mean has been seen.

## Changes
- 2026-10-13: batch 1 reduced to H08 by owner decision; H08-only power added.
- 2026-10-14: batch 3 power check added (all NOT TESTABLE).
- 2026-10-15: H15 power check added (TESTABLE under the owner's 2 × cost rule).
