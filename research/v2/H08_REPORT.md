# H08 — Intraday momentum into the COMEX settlement — report

Spec: `research/v2/H08_SPEC.md` at commit `f6dab74` · Script: `research/v2/run_h08.py` ·
Results: `research/v2/h08_results.json` · Data: broker v1b H1 (`load_broker_v1b`), TRAIN and DEV only.

## Verdict
**NOT SUPPORTED** — mean(y) in TRAIN is +0.27 × 10⁻⁴ per day with t = 0.48 (p = 0.63, N = 2,798),
far from |t| ≥ 1.96; one leg and one era also go the wrong way, and DEV net is negative.

## Pre-declared results
y = sign(r_early) × r_late, log return per day; r_early 18:00 (d−1) → 12:00 NY, r_late 12:00 → 14:00 NY.

| # | Test | Arm | n | Estimate (×10⁻⁴) | SE (×10⁻⁴) | t | p | Threshold | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | mean(y) ≠ 0, must be > 0 | TRAIN | 2,798 | +0.269 | 0.564 | 0.48 | 0.633 (two-sided) | \|t\| ≥ 1.96 and > 0 | **FAIL** |
| 1 | mean(y) > 0 (replication) | DEV | 1,191 | +0.431 | 0.651 | 0.66 | 0.254 (one-sided) | p < 0.05 | **FAIL** |

V2 cumulative test count: 1. p from the normal approximation (N > 1,000).

## Controls
| Control | Arm | Estimate (×10⁻⁴) | Required | Result |
|---|---|---|---|---|
| Secondary: mean of 136 calendar-month means, bootstrap SE 0.596 (10,000 draws, seed 20261013) | TRAIN | +0.497 (t 0.83) | same sign as headline | agrees (no ESTIMATOR_SIGN_DISAGREEMENT) |
| Leg: mean(r_late \| r_early > 0), n = 1,422 | TRAIN | −0.111 | > 0 | **FAIL** |
| Leg: mean(r_late \| r_early < 0), n = 1,376 | TRAIN | −0.662 | < 0 | pass |
| Era 2009-08-31 → 2012, n = 794 | TRAIN | +1.226 | > 0 | pass |
| Era 2013 → 2016, n = 1,004 | TRAIN | −0.482 | > 0 | **FAIL** |
| Era 2017 → 2020, n = 1,000 | TRAIN | +0.263 | > 0 | pass |

The two legs together show no momentum: after an up morning the 12:00–14:00 return is slightly
negative, and after a down morning it is negative too — a small downward drift in the window,
not a continuation of the morning's direction.

## Economics
Entry at the 12:00 NY close in direction sign(r_early), exit at the 14:00 NY close. Cost =
k_cost 4.625 × (spread_usd of the 12:00 bar + of the 13:00 bar) / 2; 126 of 1,191 days had a zero
or missing spread on both bars, filled with the DEV hour median ($0.05).

| Arm | Trades | Gross / trade | Cost / trade (1×) | Net 1× | Net 2× | Result |
|---|---|---|---|---|---|---|
| DEV | 1,191 | +$0.104 | $0.313 | **−$0.208** | −$0.521 | **FAIL** (needs > 0 and ≥ 0) |

Units: USD per oz per trade.

## Evidence against (spec §9) — observed
TRAIN not significant · leg r_early > 0 in the wrong direction · era 2013–2016 negative ·
DEV one-sided p = 0.254 ≥ 0.05 · DEV mean net ≤ 0 at 1× cost. No estimator sign disagreement.

## Limitations
- H1 bars cannot isolate the 13:30 COMEX settlement; the 12:00–14:00 window dilutes a
  settlement-specific effect, if one exists, with an hour and a half of other trading.
- Mid prices are broker bar closes; costs use bar spread_usd × k_cost calibrated on one
  October 2026 week, with zero bar spreads filled by the hour median.
- TRAIN starts in 2009 (broker H1 history); 2003–2009 is not covered.
- DEV had 62 % power at an effect equal to cost; DEV alone could not have decided H08.

## Changes
