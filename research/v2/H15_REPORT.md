# H15 — Asia vs US session (WGC definitions) — report

Spec: `research/v2/H15_SPEC.md` at commit `46a0e93` · Script: `research/v2/run_h15.py` · Results:
`research/v2/h15_results.json` · Data: broker v1b H1 (`load_broker_v1b`), TRAIN and DEV; FINAL_OOS not
used (asserted) — the clean out-of-sample would have been a forward demo test from 2026-10-15.

## Verdict
**NOT SUPPORTED** — in TRAIN mean(y) = mean(r_asia − r_us) is -0.265 × 10⁻⁴ per day, t = -0.18
(p = 0.86, N = 2,846): the wrong sign and far from |t| ≥ 2.241. Gold rose in both sessions
in TRAIN, slightly more in US hours; the per-hour contrast and two of three eras are negative too.

## Pre-declared results (log return per day, ×10⁻⁴)
| # | Test | Arm | n | Estimate | SE | t | p | Threshold | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | mean(y) ≠ 0, must be > 0 | TRAIN | 2,846 | -0.265 | 1.506 | -0.18 | 0.860 (two-sided) | \|t\| ≥ 2.241 and > 0 | **FAIL** |
| 1 | mean(y) > 0 (replication) | DEV | 1,198 | +1.122 | 2.192 | 0.51 | 0.304 (one-sided) | p < 0.05 | **FAIL** |

V2 cumulative test count: 2 (H08, H15). p from the normal approximation (N > 1,000).

## Controls (TRAIN unless stated)
| Control | Estimate (×10⁻⁴) | Required | Result |
|---|---|---|---|
| mean(r_asia), 22:00 → 11:00 UTC | +0.315 | reported | — |
| mean(r_us), 14:00 → 22:00 UTC | +0.580 | reported | — |
| Per-hour contrast mean(r_asia)/13 − mean(r_us)/8 | -0.0483 | > 0 | **FAIL** |
| Secondary: mean of 136 month means, bootstrap SE 1.451 (10,000 draws, seed 20261015) | -0.448 (t -0.31) | same sign as headline | agrees (no disagreement) |
| Era 2009-08-31 → 2012-12-31, n = 797 | -1.790 | > 0 | **FAIL** |
| Era 2013-01-01 → 2016-12-31, n = 1023 | -1.811 | > 0 | **FAIL** |
| Era 2017-01-01 → 2020-12-31, n = 1026 | +2.460 | > 0 | pass |
| DEV mean(r_asia) / mean(r_us) | +3.046 / +1.923 | reported | — |

## Economics (DEV, USD/oz per day)
Long from the Asia start bar's open to the 11:00 UTC close; short from the 14:00 UTC close to the US end
close. Cost per leg = k_cost 4.625 × (entry + exit bar spread_usd) / 2; zero or missing spreads (110–140
per bar of 1,198 days) filled with the New York hour's DEV median.

| Arm | Days | Gross / day | Cost / day (1×) | Net 1× | Net 2× | Result |
|---|---|---|---|---|---|---|
| DEV, two round trips | 1,198 | +0.176 | 0.620 | **-0.444** | -1.064 | **FAIL** (needs > 0 and ≥ 0) |
| DEV, long-Asia-only (disclosure only) | 1,198 | +0.759 | 0.312 | +0.447 | +0.135 | not a test |

The long-Asia-only leg is positive in DEV only because gold's 2021–2025 rise was large in Asian hours
(and the WGC described 2024); it was not pre-registered, is untested in TRAIN, and supports nothing.

## Evidence against (spec §9) — observed
TRAIN not significant and of the wrong sign · per-hour contrast ≤ 0 · eras 2009–12 and 2013–16 negative ·
DEV one-sided p = 0.30 ≥ 0.05 · DEV mean net ≤ 0 at 1× cost. No estimator sign disagreement.

## Disclosures (from the spec)
- **Power rule**: the H15 rule (MDE ≤ 2 × cost) was set after H14's similar variable measured
  1.72 × cost; under the earlier MDE ≤ cost rule H15 (1.29) would not have been run. No mean was seen
  before the spec was committed. The rule cannot have produced this result: TRAIN failed on sign.
- **TRAIN cleanliness**: if the WGC's samples cover 2009–2020, TRAIN was not independent of the
  hypothesis's origin; that would have favoured the hypothesis, and it still failed.
- **DEV power**: 0.33 at an effect of 1× cost, 0.77 at 2×, 0.91 at 2.5×.

## Limitations
- Broker H1 bars (bid), UTC from the v1b rule; the WGC sessions are fixed UTC, so the broker's daily
  break moves the Asia start to 23:00 UTC and the US end to 22:00 UTC in US winter (21:00 in summer).
- Costs use bar spread_usd × k_cost from one October 2026 demo-server week.
- The WGC finding may rest on another price series (LBMA / COMEX) or period; this tests it on broker data.

## Changes
