# Accessible Bar Dataset — build and validation, 2026-10-01

**ACCEPTANCE: PASS** on every structural check. **Two regime properties of the
proposed split are flagged below and need your decision before any split is
authorised.**

Namespace `data/research_v1/`. `data/raw/` and every `baselines/*` directory were
neither written nor read. Nothing committed.

---

## 1. Exported range and row counts

| TF | Rows | First (UTC) | Last (UTC) | Years | Research role |
|---|---|---|---|---|---|
| **H1** | **100,001** | 2009-08-31 | 2026-10-01 | **17.08** | regime / context, long-history stability |
| **M15** | **100,020** | 2022-06-30 | 2026-10-01 | **4.26** | **PRIMARY discovery** |
| **M5** | **100,058** | 2025-04-25 | 2026-10-01 | **1.44** | entry / confirmation / short-horizon labels |
| **M1** | **100,287** | 2026-06-17 | 2026-10-01 | **0.29** | execution / path / fill only |
| **H4** | **34,174** | 2004-06-11 | 2026-10-01 | **22.31** | optional descriptive context, **not a dependency** |

First timestamps are UTC. Server-time provenance is preserved separately — e.g.
H1 first bar is server `2009-08-31T22:00:00` → UTC `2009-08-31T19:00:00`.

## 2. Validation

| TF | Monotonic | Dupes | OHLC valid | NaN | Non-positive | Zero-vol | **Coverage** |
|---|---|---|---|---|---|---|---|
| H1 | ✓ | 0 | ✓ | 0 | 0 | 0 | 0.6678 |
| M15 | ✓ | 0 | ✓ | 0 | 0 | 0 | 0.6704 |
| M5 | ✓ | 0 | ✓ | 0 | 0 | 0 | 0.6625 |
| M1 | ✓ | 0 | ✓ | 0 | 0 | 0 | 0.6552 |
| H4 | ✓ | 0 | ✓ | 0 | 0 | 0 | 0.6991 |

**The acceptance test that matters:** all five files load through
`data.dataset.load_bars_csv` and pass `validate_bars` with **zero issues**. The
project's existing 6-column contract is honoured exactly, so the whole harness —
`ReplayFeed`, the baseline machinery, the research panels — works on this dataset
unchanged.

## 3. Gaps

| TF | Total | Weekend >48 h | Intraday ≤6 h | Other 6–48 h | Max gap |
|---|---|---|---|---|---|
| H1 | 4,428 | 891 | 3,506 | 31 | 86.0 h |
| M15 | 1,117 | 222 | 889 | 6 | 74.25 h |
| M5 | 411 | 75 | 332 | 4 | 74.08 h |
| M1 | 78 | 15 | 63 | 0 | 53.0 h |
| H4 | 1,255 | 1,164 | 0 | 91 | 112.0 h |

Every gap is structural: weekends, the UTC 19:55 → 22:00 daily break, and holiday
closures. H4 shows **zero** intraday gaps because its 4 h step absorbs the 2 h
daily break. Nothing was interpolated or filled — missing is missing.

## 4. Export method and chunking

**49 chunks**, sized per timeframe so no request approaches the row count at which
`copy_rates_range` returns `Invalid params`:

| TF | Chunk width | Chunks | Largest chunk |
|---|---|---|---|
| H1 | 365 d | 18 | ~5,600 rows |
| M15 | 180 d | 9 | 11,728 rows |
| M5 | 90 d | 6 | 17,561 rows |
| M1 | 30 d | 4 | 28,291 rows |
| H4 | 730 d | 12 | ~3,100 rows |

**Sentinel defence worked and was needed.** Every returned row is filtered to its
requested window; **7 out-of-window rows were caught and dropped**, all in H4 at
chunk seams. `sum(kept)` equals the final row count exactly for all five
timeframes, so **chunking lost nothing at any boundary**.

## 5. Timezone handling

| | |
|---|---|
| Measured server offset | **+3.00 h** (independently, `symbol_info_tick.time` vs wall clock) |
| `raw_server/` | `time_server` **exactly as the API returned it** — never rewritten |
| `bars/` | `time` = `time_server − 3h`, UTC, in the 6-column contract |

Raw provenance and research timestamps live in separate files. Nothing was
silently rewritten.

## 6. Fingerprints

Hashed over **bar values**, not file bytes, so they are independent of CSV
formatting and float repr — the same rule as `backtest.baseline.dataset_fingerprint`.

```
H1   a74e0e5b679fc0fe219102d55a64b3b9bbf6aa53f4a5edde345057eb1361c189  100,001
M15  e37d539588b1493e2b18c0bd70fdd8569f2dfd9a47461b38b490d59d9ee115bf  100,020
M5   ac5c1c39940936522adcd741967ecde7f7bc002cf8b9f968d14533923b7bc4f4  100,058
M1   7b7254a7b9070e1eacf7d19c1e2719c45da129c3f928634031063e0a3b832b7c  100,287
H4   b87154c805cf025bc608eb734aa9e1e513fb97e744fbad2a50ba58bef1262d80   34,174

dataset_sha256  9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca
```

Recorded alongside: `git_sha = 4aebffd10ca1…`, `maxbars = 100,000,000`, full
uncurated `terminal_info` / `account_info` / `symbol_info` dumps, and the complete
49-entry chunk log.

## 7. Storage

| | |
|---|---|
| `raw_server/` | 29 MB |
| `bars/` | 27 MB |
| `meta/` | 24 KB |
| **Total** | **56 MB** |

The accessible history is ~434,000 bars across five timeframes. Storage was never
the constraint — the 18 GB of free disk is irrelevant at this scale.

## 8. One defect found and fixed

The build-time `validate()` used `t.astype("int64")` on a **tz-aware** Series.
pandas 3.0 handles that differently, and the first manifest carried **wrong**
gap, coverage and monotonicity figures — `gaps_total = 0` for a 4-year M15 series,
and `monotonic = False` while the project's own validator reported no issues.

- **Cause:** `.astype("int64")` on tz-aware datetimes; the correct conversion is
  `to_numpy("datetime64[s]").astype("int64")`.
- **Fixed:** builder patched so a rebuild cannot repeat it; statistics recomputed
  from the written CSVs.
- **Scope:** statistics only. **The exported files were never wrong** — they pass
  `validate_bars` with zero issues and the fingerprints are unchanged.

The contradiction is what exposed it: a reported `gaps_total = 0` over four years
is impossible, and it disagreed with an independent validator. Worth noting that
the cross-check caught it, not the test itself.

---

## 9. Proposed chronological split — PROPOSAL ONLY, NOT AUTHORISED

**Binding range: M15 ∩ H1 = 2022-06-30 → 2026-10-01, 4.25 years.** M15 is the
primary discovery timeframe and is the shorter of the two, so it sets the range.

50/25/25 on M15, purge/embargo **16 M15 bars** (the 4 h horizon) after each
boundary:

| Arm | Rows | From | To | Months | **Net %** | **Median ATR** | 1h blocks | 2h blocks |
|---|---|---|---|---|---|---|---|---|
| TRAIN | 50,010 | 2022-06-30 | 2024-08-09 | 25.3 | **+33.63%** | **$2.085** | 12,502 | 6,251 |
| DEV | 24,989 | 2024-08-11 | 2025-09-02 | 12.7 | **+44.24%** | **$3.564** | 6,247 | 3,123 |
| FINAL_OOS | 24,989 | 2025-09-02 | 2026-10-01 | 12.9 | **+18.24%** | **$8.932** | 6,247 | 3,123 |

### Statistical power — a large improvement

**12,502 non-overlapping 2 h blocks over the full range, against 837 in the old
16-week dataset — roughly 15×.** Since MDE scales as 1/√n, the 2 h minimum
detectable effect falls by about **3.9×**. The power problem that made Candidate F
unmeasurable and left Candidate B marginal is materially reduced.

### Two regime properties you need to decide on

**(a) Every arm is net positive: +33.6%, +44.2%, +18.2%.** Gold rose throughout
2022–2026. **There is no bear regime anywhere in the primary M15 range.** A
long-biased rule will look good in all three arms, and the split cannot detect
that. The old 16-week dataset at least contained a trend flip; this one does not.
H1's 17.08 years *does* contain bear regimes — which is an argument for using H1
for the directional-robustness check rather than treating it as mere context.

**(b) Median ATR rises 4.3× across the arms: $2.09 → $3.56 → $8.93.** TRAIN and
FINAL_OOS are different volatility regimes. Any ATR-normalised feature or
threshold fitted on TRAIN meets a very different distribution in OOS. This is not
a defect in the split — it is a property of the period — but it must be handled
deliberately rather than discovered after the fact.

I am not resolving either. Both are architecture decisions, and (a) in particular
may argue for a different split or for promoting H1 from context to a validation
role.

### Gating rules carried forward

- FINAL_OOS supplies **no** quantile cutoff and **no** feature selection — cutoffs
  come from TRAIN only. Phase 1 computed cutoffs over the whole sample; that was
  acceptable for discovery and is not acceptable here.
- FINAL_OOS stays physically separate behind an explicit authorisation flag.
- **One look.** Record date, git SHA and candidate SHA when it is opened.

---

## 10. Acceptance status

| Check | Result |
|---|---|
| All required timeframes exported over their verified ranges | **PASS** |
| Loads through `load_bars_csv` + `validate_bars`, zero issues | **PASS** (5/5) |
| Monotonic, no duplicates, OHLC valid, no NaN, no non-positive | **PASS** (5/5) |
| Gaps enumerated and classified; nothing interpolated | **PASS** |
| Chunked export; no loss at any seam | **PASS** (`sum(kept)` = rows, 5/5) |
| Sentinel rows caught, not ingested | **PASS** (7 dropped, all H4 seams) |
| Raw server timestamps preserved immutably | **PASS** (write-once, refuses overwrite) |
| UTC normalisation from independently measured offset | **PASS** (+3.00 h) |
| Value-based fingerprints + manifest + chunk log + broker metadata + git SHA + MaxBars | **PASS** |
| `baseline_008` and `data/raw/` untouched | **PASS** |
| Split proposed, **not authorised**; OOS not opened | **PASS** |

**The dataset passes acceptance as a research dataset.** It is not authorised for
strategy research, and the two regime properties in §9 are open questions.

## Files

- `research/build_accessible_bar_dataset.py`
- `research/accessible_bar_dataset_manifest.json`
- `research/accessible_bar_dataset_fingerprints.json`
- `research/proposed_split.json` — proposal only
- `research/ACCESSIBLE_BAR_DATASET_BUILD.md`
- `data/research_v1/{raw_server,bars,meta}/`

All untracked, nothing committed. No production change, no baseline change, no
edge discovery, no candidate strategies, no threshold tuning, no tick/bar mixing.
Ticks were not touched in this build.
