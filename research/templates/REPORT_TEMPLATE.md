# H?? — <name> — report

Spec: `research/...` at commit `<sha>` · Script: `...` · Max 120 lines.

## Verdict
**<PASS / FAIL / INCONCLUSIVE>** — <one line: what was tested, the number that decided it>.

## Pre-declared results
| # | Test | Arm | n | Estimate | SE | t | p | Threshold | Result |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | TRAIN | | | | | | Bonferroni | |
| 1 | | DEV | | | | | | one-sided 0.05 | |

## Controls
| Control | Arm | Estimate | Required | Result |
|---|---|---|---|---|
| Drift-adjusted | | | same sign, abs(t) ≥ 2 | |
| Era 1 / 2 / 3 sign | TRAIN | | identical | |

## Economics
| Arm | Trades | Gross / trade | Cost / trade (1×) | Net 1× | Net 2× | Result |
|---|---|---|---|---|---|---|
| DEV | | | | | | |

Units: `*_usd` per oz, returns as log returns, trade results in R.

## Limitations
- (max 5 bullets)

## Changes
- (one line per in-place correction: date, what changed, why)
