# H15 — Asia vs US session (WGC session definitions)

One page. Committed alone, before the script that computes its results.

## 1. ID and name
- ID: H15. Owner decision 2026-10-15. V2 tests before this spec: 1 (H08; H13/H14 were dropped at the
  power check and never run); after: **2**.

## 2. Mechanism and external evidence
- Gold's gains are reported concentrated in Asian trading hours and pullbacks in US hours: World Gold
  Council (2024) and mid-2026 session analyses. Physical demand and price-insensitive buying in Asia
  versus futures- and ETF-driven selling in New York are the proposed channels.
- Against: a practitioner observation, not established in peer-reviewed work; the WGC samples may
  overlap TRAIN, so TRAIN may not be independent of the hypothesis's origin.

## 3. Data, timeframe and arms
- Broker v1b H1 via `gold/data/store.load_broker_v1b` (DST-correct UTC); `utc_suspect` bars excluded.
- TRAIN 2009-08-31 → 2020-12-31 is the clean test. DEV 2021-01-04 → 2025-09-02 is replication;
  **disclosure: DEV contains 2024, already described by the WGC.**
- **FINAL_OOS is not used for H15** (the WGC mid-2026 report already describes that period). The clean
  out-of-sample is a forward demo test starting 2026-10-15.

## 4. Exact construction (code: `gold/hyp/h15_asia_us.py`)
Sessions exactly as the WGC defines them, fixed UTC, no DST shifts: Asia 22:00 → 11:00 UTC (13 h);
US 14:00 → 22:00 UTC (8 h). Trading day d = the UTC date on which the Asia session ends (weekdays).
- r_asia = log(close of the bar ending 11:00 UTC on d / open of the first bar at or after 22:00 UTC on
  d−1). That bar must open on d−1 (22:00 UTC, or 23:00 UTC when the broker is closed 22:00–23:00 UTC
  in US winter); otherwise the day is dropped.
- r_us = log(close of the last bar ending at or before 22:00 UTC on d (opening 14:00–21:00 UTC) /
  close of the bar ending 14:00 UTC on d).
- **y = r_asia − r_us.** Per-hour contrast = r_asia / 13 − r_us / 8.
- A day needs every hourly bar from the Asia start bar through the US end bar, none `utc_suspect`.

## 5. Tests and their count
| # | Null | Alternative | Rule | Arm |
|---|---|---|---|---|
| 1 | mean(y) = 0 | mean(y) ≠ 0 | daily observations, \|t\| ≥ 2.241 **and** mean(y) > 0 | TRAIN |

- Tests in this spec: 1 · V2 cumulative: 2 (H08, H15) · Bonferroni two-sided α = 0.05 → z = 2.241.
- Secondary estimator: equal-weighted mean of calendar-month means of y, standard error from a
  calendar-month block bootstrap (10,000 draws, seed 20261015). If its sign differs from mean(y):
  ESTIMATOR_SIGN_DISAGREEMENT, which blocks promotion.

## 6. Controls (TRAIN)
- mean(r_asia) and mean(r_us) reported separately.
- Per-hour contrast mean(r_asia) / 13 − mean(r_us) / 8 > 0.
- mean(y) > 0 in each era: 2009-08-31 → 2012-12-31, 2013 → 2016, 2017 → 2020-12-31.

## 7. DEV replication rule
One-sided p < 0.05 for mean(y) > 0 in DEV (daily observations), nothing re-fitted.

## 8. Economics rule (DEV)
Each day, two round trips: **long** from the open of the Asia start bar to the close of the bar ending
11:00 UTC; **short** from the close of the bar ending 14:00 UTC to the close of the US end bar. Gross per
day = (close 11:00 − Asia open) + (close 14:00 − US end close), USD/oz. Cost per leg = `round_turn_cost_usd`
(spread_usd of the leg's entry bar, of its exit bar, k_cost = 4.625); a zero or missing spread takes
that New York hour's DEV median spread_usd. **Pass: mean net per day > 0 at 1× cost and ≥ 0 at 2×.**
The long-Asia-only leg is also reported, for disclosure only.

## 9. Evidence against — and verdict mapping
Evidence against: TRAIN not significant, or significant and negative; per-hour contrast ≤ 0; any era
with mean(y) ≤ 0; ESTIMATOR_SIGN_DISAGREEMENT; DEV one-sided p ≥ 0.05; DEV mean net ≤ 0 at 1× cost.
- NOT SUPPORTED: the TRAIN test or any TRAIN control fails.
- INCONCLUSIVE: TRAIN and its controls pass, but a DEV rule fails (DEV is underpowered, §10).
- SUPPORTED: every rule passes. Live use would still require the forward demo test from 2026-10-15.

## 10. Power pre-check result (`research/POWER_V2.md`)
- TRAIN: N = 2,846 days, sd(y) = 0.0080, MDE = 3.37 × 10⁻⁴ at z = 2.241 vs DEV two-round-trip cost
  2.62 × 10⁻⁴: MDE / cost **1.29** — TESTABLE under the owner's H15 rule (MDE ≤ 2 × cost; the published
  claims put the effect at ≥ 2.5 × cost). Under the earlier MDE ≤ cost rule it would not be testable;
  the 2× rule followed H14's similar power result, so it is not blind to that. No mean has been seen.
- DEV: N = 1,198, one-sided MDE / cost 1.38; power 0.33 / 0.77 / 0.91 at an effect of 1× / 2× / 2.5× cost.
