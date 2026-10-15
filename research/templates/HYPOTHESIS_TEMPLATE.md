# H?? — <name>

One page. Committed alone, before the script that computes its results.

## 1. ID and name
- ID:
- Name:
- Batch / V2 cumulative test count before this spec:

## 2. Mechanism and external evidence
- Mechanism (who trades, why the effect should exist):
- External evidence (author, year, journal; contrary evidence too):

## 3. Data, timeframe and arms
- Dataset and fingerprint:
- Timeframe / bar:
- Arms used: TRAIN (statistics) · DEV (replication, economics). FINAL_OOS not read.

## 4. Exact construction
Every constant listed; no unnamed numbers in the code.

| Constant | Value | Unit / time zone |
|---|---|---|
| | | |

- Variable(s) (log returns `r_*`, prices `*_usd`):
- Anchor rule and missing-data rule:

## 5. Tests and their count
| # | Null | Alternative | Sidedness | Arm |
|---|---|---|---|---|
| 1 | | | | TRAIN |

- Tests in this spec:  · V2 cumulative after this spec:  · Bonferroni α:

## 6. Controls
- Drift control / legs reported separately:
- Era stability (sign in each TRAIN era):

## 7. DEV replication rule
One-sided p < 0.05 in the direction fixed by TRAIN, no re-fitting.

## 8. Economics rule
Net per trade = gross − `(spread_entry + spread_exit)/2 × k_cost` (+ financing
past 17:00 NY). Pass: > 0 at 1× DEV cost and ≥ 0 at 2×.

## 9. Evidence against
-

## 10. Power pre-check result
- Required n / minimum detectable effect vs cost:
- Result: PASS / FAIL
