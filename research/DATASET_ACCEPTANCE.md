# Research Dataset — Final Acceptance and Freeze

**ACCEPTED AND FROZEN.** `data/research_v1/`, dataset
`9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca`, git `4aebffd`,
MaxBars `100,000,000`.

**FINAL_OOS is LOCKED and the lock is mechanical, not declarative.**

No strategy research has been run. The split remains a **PROPOSAL**.

---

## 1. Acceptance validator — re-run against the written files

Independently re-loaded through `data.dataset.load_bars_csv` and re-validated with
`validate_bars`:

| TF | Rows | Row count | `validate_bars` issues | Fingerprint | Result |
|---|---|---|---|---|---|
| H1 | 100,001 | OK | **0** | **MATCH** | **PASS** |
| M15 | 100,020 | OK | **0** | **MATCH** | **PASS** |
| M5 | 100,058 | OK | **0** | **MATCH** | **PASS** |
| M1 | 100,287 | OK | **0** | **MATCH** | **PASS** |
| H4 | 34,174 | OK | **0** | **MATCH** | **PASS** |

**This confirms the earlier statement about the pandas timezone defect.** It was a
builder-*statistics* defect only: all five fingerprints recomputed from the written
files match the originally reported values **exactly**, and the combined
`dataset_sha256` reproduces bit-for-bit. The exported files were never wrong.

## 2. Fingerprint verification

```
H1   a74e0e5b679fc0fe219102d55a64b3b9bbf6aa53f4a5edde345057eb1361c189  MATCH
M15  e37d539588b1493e2b18c0bd70fdd8569f2dfd9a47461b38b490d59d9ee115bf  MATCH
M5   ac5c1c39940936522adcd741967ecde7f7bc002cf8b9f968d14533923b7bc4f4  MATCH
M1   7b7254a7b9070e1eacf7d19c1e2719c45da129c3f928634031063e0a3b832b7c  MATCH
H4   b87154c805cf025bc608eb734aa9e1e513fb97e744fbad2a50ba58bef1262d80  MATCH

dataset_sha256  9925ff94fb8d8c748e3a4774064b0e7b344da21ffac0efce509d7e3f6ef626ca  MATCH
```

Hashed over **bar values**, not file bytes — independent of CSV formatting and
float repr, the same rule as `backtest.baseline.dataset_fingerprint`.

## 3. `raw_server/` immutability

| File | Bytes | SHA-256 (file) |
|---|---|---|
| `XAUUSD_H1_server.csv` | 7,013,510 | `625203816933a9bda0455930…` |
| `XAUUSD_H4_server.csv` | 2,333,396 | `722fa61a4b2ce8a2551c296e…` |
| `XAUUSD_M15_server.csv` | 6,760,769 | `01b10ad2ac4bf6a6be02099f…` |
| `XAUUSD_M1_server.csv` | 6,737,519 | `27cec436291c3f426ce0b684…` |
| `XAUUSD_M5_server.csv` | 6,754,574 | `c6792213a5f7a47ff4b2db44…` |

Mechanism: the builder **refuses to write into a non-empty `raw_server/`** and
exits — the same guard pattern as `backtest.baseline.write_artifacts`, which is
what has kept `baseline_004` through `baseline_008` intact. Raw server timestamps
are preserved verbatim; UTC normalisation lives in separate files and never
rewrites them.

## 4. `baseline_008` untouched

`git status -- baselines/` is **empty**; `git diff HEAD -- baselines/` is **zero
lines**; `baselines/baseline_008/` still holds its 15 files. Nothing in this work
read or wrote any baseline.

## 5. Production untouched

`git diff --stat HEAD` across `main_production.py`, `bias_engine.py`,
`entry_engine.py`, `confidence_engine.py`, `structure_engine.py`,
`sweep_detector.py`, `poi_engine.py`, `liquidity_engine.py`,
`pullback_detector.py`, `indicators.py`, `risk_manager.py`, `order_execution.py`,
`trade_manager.py`, `mt5_handler.py`, `backtest/`, `core/`, `execution/`,
`tests/`, `data/dataset.py`, `data/replay_feed.py` → **no output: zero tracked
production changes.**

## 6. OOS lock verification

**Has any research code read FINAL_OOS? No — and the verification is stronger than
that.** Every existing research module reads either `data/raw/` (the *old* frozen
16-week dataset, 2026-06-02 → 2026-09-16) or `.pkl` panels derived from it:

| Module | Reads |
|---|---|
| `panel_features`, `panel_state`, `panel_labels`, `panel_path` | `data/raw/` |
| `discover`, `structure`, `shortlist`, `artifact_check`, `phase2`, `evaluate*` | `.pkl` panels |
| `build_accessible_bar_dataset` | **writes** `data/research_v1/`, never reads it for analysis |

**No research module reads `data/research_v1/` at all**, so none can have read
FINAL_OOS. A date-range grep across `research/*.py` for the OOS window
(2025-09-02 → 2026-10-01) found one hit, a docstring in `panel_labels.py`
describing the *old* dataset's M1 start — not an OOS read.

### The lock is mechanical

`research/dataset_access.py` is the sanctioned loader and **raises
`OOSLockedError`** on any FINAL_OOS read without the exact token recorded in the
split manifest. Verified live:

```
M15 TRAIN:     50,010 rows  2022-06-30 -> 2024-08-09
M15 DEV:       24,989 rows  2024-08-11 -> 2025-09-02
M15 FINAL_OOS: LOCKED as expected -- OOSLockedError
verify_dataset(): all five MATCH, dataset_match = true
```

The manifest's token is `OOS-AUTHORISATION-NOT-ISSUED`, so there is no value a
caller can pass that unlocks it until you change the manifest in writing. A flag
in a JSON file is a statement of intent; this is the enforcement.

## 7. Formal split manifest — `research/research_split_manifest.json`

**`status: "PROPOSAL -- NOT AUTHORISED FOR RESEARCH"` · `FINAL_OOS_LOCKED: true`**

Binding range **M15 ∩ H1 = 2022-06-30 → 2026-10-01, 4.25 years** (M15 is primary
and the shorter, so it sets the range). Purge/embargo **16 M15 bars = 4 h**, the
longest horizon under consideration, dropped *after* each boundary so no forward
window spans two arms.

| Arm | From | To | M15 rows | Months | Net % | Median ATR | 1h / 2h / 4h blocks |
|---|---|---|---|---|---|---|---|
| TRAIN | 2022-06-30 | 2024-08-09 | 50,010 | 25.3 | +33.63% | $2.085 | 12,502 / 6,251 / 3,125 |
| DEV | 2024-08-11 | 2025-09-02 | 24,989 | 12.7 | +44.24% | $3.564 | 6,247 / 3,123 / 1,561 |
| **FINAL_OOS** | 2025-09-02 | 2026-10-01 | 24,989 | 12.9 | +18.24% | $8.932 | 6,247 / 3,123 / 1,561 |

Also recorded: timeframe roles, OOS prohibitions (no quantile cutoff, no feature /
threshold / candidate selection, no parameter tuning), unlock requirements, all
fingerprints, git SHA, MaxBars, server offset.

### Regime warnings carried in the manifest

1. **All three arms are net-positive** (+33.63 / +44.24 / +18.24%). No bear regime
   exists anywhere in the primary M15 range, so **chronological validation alone
   cannot establish directional robustness.**
2. **Median ATR rises 4.3×** ($2.085 → $3.564 → $8.932). TRAIN and FINAL_OOS are
   different volatility regimes.
3. **H1 spans 17.08 years and does contain bear regimes** — which is why it is the
   designated directional-robustness layer rather than mere context.

---

## 8. Commit contents, and why the data is not committed

`.gitignore:34` already excludes `data/raw/`, so **the project's established
convention is that raw market data is never committed** — integrity is guaranteed
by a fingerprint recorded in committed metadata, which is exactly how
`baseline_004` … `baseline_008` guarantee their dataset
(`433b7e27…`) without storing bars in git.

`data/research_v1/` (56 MB) therefore follows the same rule: **gitignored, and
frozen by its committed fingerprints.** Committed instead are the builder, the
gated loader, the manifests, the fingerprints and the reports — everything needed
to verify or rebuild, and nothing that duplicates 56 MB of CSV into history.

If you would rather the bars themselves were version-controlled, say so and I will
add them; it is a one-line `.gitignore` change and the repo is only 24 MB of
history today.

## 9. Acceptance summary

| Check | Result |
|---|---|
| 1. Acceptance validator re-run on written files | **PASS** (5/5, 0 issues) |
| 2. Fingerprints verified against the freeze | **PASS** (5/5 + combined) |
| 3. `raw_server/` immutable | **PASS** (hashed; write-once guard) |
| 4. `baseline_008` untouched | **PASS** |
| 5. Production untouched | **PASS** |
| 6. No research code has read FINAL_OOS | **PASS** (no module reads `research_v1`) |
| 7. Formal split manifest, `FINAL_OOS_LOCKED=true` | **PASS** |
| 8. Split still labelled PROPOSAL | **PASS** |
| 9. Commit contains only dataset infra + freeze artifacts | **PASS** |

**The dataset is frozen and accepted. Strategy research has NOT begun and will not
begin without your explicit authorisation.**
