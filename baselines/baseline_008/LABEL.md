# baseline_008

> # POST-STOP-ANCHOR REFERENCE — IMMUTABLE
>
> **The frozen reference for the Phase 8 edge-discovery study.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this directory.
`write_artifacts` refuses to write into an existing baseline directory; that guard
is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.**

**`baseline_006` and `baseline_007` remain immutable and untouched.** They are the
pre-P8-10 and post-P8-10 records respectively and are not superseded by this one.

**Not a profitability study.** Four trades. Four is not a sample. No figure here
is evidence about performance in any direction.

---

## 1. Provenance

| | |
|---|---|
| HEAD SHA | `89128c6efc6df23cc14979ebd0a367d5699cc7de` |
| Commit | *fix: enforce entry-aware stop anchor geometry* |
| Branch | `phase-0-1-foundations` |
| Working tree at replay | **clean** |
| Python / platform | 3.13.7 · Windows-10-10.0.19045-SP0 |

### Why this baseline exists

`89128c6` made stop-anchor selection entry-aware. That changed execution geometry
on 25 decisions without changing any decision verdict, so `baseline_007` kept
matching HEAD's *decisions* while diverging on its *trades*. Edge research needs a
reference that matches HEAD on both. **This is an administrative freeze only** —
no strategy question was investigated in producing it.

### Replay command

`docs/BASELINE_005_PROVENANCE.md` §8, unchanged from `baseline_006` and
`baseline_007`: all five log paths redirected **before** importing
`main_production`, `assert_logs_are_redirected()` enforced, stdout to a sink, then
`run_baseline(..., baseline_id="baseline_008", git_commit=<HEAD>, spread_pips=2.0,
spread_is_assumed=True, progress_every=0)` and `write_artifacts(...)` called
**unmodified**, every other argument at default.

### Input data — identical to baseline_006 and baseline_007

Dataset SHA-256 `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c`,
range 2026-06-02 00:00 → 2026-09-16 12:32 UTC, driving timeframe M5.

### Fingerprints

```
run_fingerprint       = see run_fingerprint.txt
decisions_fingerprint = identical to baseline_007
ledger_fingerprint    = differs from baseline_007
dataset_sha256        = 433b7e27…
```

**Verified relationships.** `decisions_fingerprint` and `dataset_sha256` are
**identical to `baseline_007`**, because `89128c6` changed execution only.
`ledger_fingerprint` and `run_fingerprint` **differ from `baseline_007`** and
**match the accepted post-change replay exactly**, across an independent run —
so the replay remains deterministic on this dataset and code state.

---

## 2. Headline

| | |
|---|---|
| Decisions | **15,735** |
| Strategy errors | **0** |
| Signals | **4** (BUY 2 · SELL 2, all MICRO_SCALP / MOMENTUM) |
| Trades / rejected orders | 4 / **0** |

Internal consistency verified: decisions agree across `decision_statistics`,
`layer_funnel`, the `blocked_at` sum and the regime sum; signals agree across
`decision_statistics`, `layer_funnel` and `metrics`.

Regime distribution, funnel, signal identities and execution summary are unchanged
from `baseline_007` except for the stop/target/risk of three trades, which is the
whole content of `89128c6`.

---

## 3. Role in the Phase 8 edge study

This baseline is the **comparison reference** for the edge-discovery study that
follows. That study is diagnostic and read-only: it changes no production code and
creates no further baseline.

**A limitation this baseline shares with every earlier one, and which the study
had to work around:** `analyze_entry` short-circuits at the first failing layer,
so `decisions.jsonl` records only the *first* blocking layer. Whether a decision
blocked at L3 would also have failed L5, L6 or L7 is **not recoverable from these
artefacts**. The study generates that separately with an analysis-only harness
that evaluates every layer unconditionally; nothing in this directory contains it.

---

## 4. Immutability

Future experiments **compare against** this baseline and must not overwrite,
regenerate or modify it — including an experiment that looks better. A baseline
generated after a strategy-contract change receives its own separate identity.

Any performance difference observed later must be compared against the frozen
baselines and **attributed to a specific code or model change**, not asserted.
