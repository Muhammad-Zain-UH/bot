# H08 — Intraday momentum into the COMEX settlement

One page. Committed alone, before the script that computes its results.

## 1. ID and name
- ID: H08. Name: intraday momentum into the COMEX settlement (ROADMAP_V2 §6).
- Batch 1 = H08 only (owner, 2026-10-13). V2 tests before this spec: 0; after: **1**.

## 2. Mechanism and external evidence
- Hedging and late-informed trading in the session's last hours follow the day's earlier
  move; for gold the main liquidity event is the COMEX settlement at 13:30 New York.
- Gao, Han, Li & Zhou (2018), *Journal of Financial Economics*: the first half-hour
  return predicts the last half-hour return (US equity ETFs). No gold-specific evidence is cited.

## 3. Data, timeframe and arms
- Broker v1b H1 bars via `gold/data/store.load_broker_v1b` (DST-correct UTC, fingerprints
  in `research/broker_v1b_fingerprints.json`). Bars with `utc_suspect` = True are excluded.
- TRAIN 2009-08-31 → 2020-12-31 (statistics); DEV 2021-01-04 → 2025-09-02 (replication,
  economics); split `research/research_split_manifest_h1_v1b.json`. FINAL_OOS is not read.

## 4. Exact construction (code: `gold/hyp/h08_intraday_momentum.py`)
| Constant | Value | Unit / time zone |
|---|---|---|
| Day | 18:00 (day d−1) → 17:00 (day d), weekdays | America/New_York |
| Start price | open of the H1 bar opening 18:00, day d−1 | USD/oz |
| Split price | close of the bar ending 12:00 (opening 11:00), day d | USD/oz |
| End price | close of the bar ending 14:00 (opening 13:00), day d | USD/oz |
| Required bars | every H1 bar opening 18:00 (d−1) … 13:00 (d), none `utc_suspect` | — |

- r_early = log(split / start); r_late = log(end / split); **y = sign(r_early) × r_late**.
- A day is dropped if any required bar is missing or `utc_suspect`, or if r_early = 0.

## 5. Tests and their count
| # | Null | Alternative | Rule | Arm |
|---|---|---|---|---|
| 1 | mean(y) = 0 | mean(y) ≠ 0 | daily observations, \|t\| ≥ 1.96 **and** mean(y) > 0 | TRAIN |

- Tests in this spec: 1 · V2 cumulative: 1 · α = 0.05 two-sided, z = 1.96. A significant
  negative mean is evidence against the mechanism, not a pass.
- Secondary estimator: equal-weighted mean of calendar-month means of y, standard error from
  a calendar-month block bootstrap (10,000 draws, seed 20261013). If its sign differs from
  mean(y): ESTIMATOR_SIGN_DISAGREEMENT, which blocks promotion.

## 6. Controls
- Legs, point estimates in TRAIN: mean(r_late | r_early > 0) > 0 and mean(r_late | r_early < 0) < 0.
- Eras: mean(y) > 0 in each of 2009-08-31 → 2012-12-31, 2013 → 2016, 2017 → 2020-12-31.

## 7. DEV replication rule
One-sided p < 0.05 for mean(y) > 0 in DEV (daily observations), no re-fitting of anything.

## 8. Economics rule (DEV)
Each DEV day: enter at the 12:00 close in direction sign(r_early), exit at the 14:00 close.
Gross = direction × (close at 14:00 − close at 12:00), USD/oz. Cost = `round_turn_cost_usd`
(spread_usd of the bar opening 12:00, spread_usd of the bar opening 13:00, k_cost = 4.625);
a missing or zero spread is replaced by that New York hour's DEV median spread_usd.
Pass: mean net > 0 at 1× cost **and** mean net ≥ 0 at 2× cost.

## 9. Evidence against
TRAIN not significant, or significant and negative; either leg in the wrong direction; any
era with mean(y) ≤ 0; ESTIMATOR_SIGN_DISAGREEMENT; DEV one-sided p ≥ 0.05; DEV mean net ≤ 0 at 1× cost.

## 10. Power pre-check result (`research/POWER_V2.md`)
- TRAIN: N = 2,798, sd(y) = 0.00298, MDE = 1.10 × 10⁻⁴ vs DEV cost 1.27 × 10⁻⁴ (ratio 0.87): **PASS**.
- DEV: N = 1,191, one-sided MDE / cost = 0.84; power 0.62 at an effect of 1× cost, 0.90 at 1.5×.
  DEV is underpowered at 1× cost, so a TRAIN pass with a DEV miss is reported **INCONCLUSIVE**,
  not SUPPORTED.
