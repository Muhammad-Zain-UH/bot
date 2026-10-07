# baseline_009

> # FUNNEL-NEUTRALITY CONTROL — IMMUTABLE
>
> **Proof that the R1–R9 risk and safety fixes changed no strategy decision.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_008` remain immutable and
untouched; this one supersedes nothing.

## Why it exists

A large batch of correctness and safety work landed on the production path:

* `main_production.py` made startable (`demo_mode = True` → SIMULATION; it had
  resolved to `ExecutionMode.LIVE` and been refused at startup)
* `graceful_shutdown()` gated so it cannot close a position this process did
  not open
* account-level risk limits introduced and wired: daily loss, drawdown kill
  switch, consecutive losses, exposure cap, time stop (`PHASE_2_ISSUES.md`
  R2, R3, R4, R6, R7, R8, R9)
* realised P&L computed and persisted for the first time
* the L2 volatility gate stopped reporting a missing ATR as "too calm", and its
  operator output stopped calling dollars "pips"
* a function-local `import detect_regime` removed, which had shadowed the
  module-level binding

Every one of those is a claim that behaviour did **not** change — that they fixed
what the system *reports and risks*, not what it *decides*. This baseline tests
that claim against `baseline_008`, on the same dataset with the same assumptions.

## Result: identical, to the fingerprint

```
run_fingerprint  e1293df1d7bc3385fffb8fa259ca7e081ada4a0f1d18be4cb0612cfc63fe4e97
```

Byte-identical to `baseline_008`. So is the whole layer funnel:

| blocked at | 008 | 009 | delta |
|---|---|---|---|
| L1_BIAS | 1,505 | 1,505 | 0 |
| L2_STRUCTURE | 12 | 12 | 0 |
| L3_PULLBACK | 5,044 | 5,044 | 0 |
| L4_LIQUIDITY | 748 | 748 | 0 |
| L5_SWEEP | 5,000 | 5,000 | 0 |
| L6_POI | 2 | 2 | 0 |
| L7_CONFIDENCE | 1,835 | 1,835 | 0 |
| L8_ENTRY | 1,585 | 1,585 | 0 |
| NONE (signal) | 4 | 4 | 0 |
| **decisions** | **15,735** | **15,735** | **0** |

All metrics match to six decimal places.

## What this is for

It is the **pre-migration reference** for the U1–U12 unit migration, which *is*
a deliberate behavioural change. Measuring that change against `baseline_008`
would confound it with everything listed above; measuring it against this one
does not, because this is the same strategy at the current commit.

## Not a profitability study

**Four trades. Four is not a sample.** No figure here is evidence about
performance in any direction, and the identical P&L above is evidence only that
nothing changed — not that the result is good.

The funnel is the measurement that carries weight: 15,735 decisions through
eight layers is well-powered for seeing *where* the pipeline blocks. The trade
count is not well-powered for anything.

## Scope limit worth recording

The replay window is **2026-06-02 → 2026-09-16**, about 3.5 months, bound by the
broker's M1 floor of 2026-06-17 (`main_production.py` requires `m1_data` for
L8_ENTRY via `detect_m1_choch`). Over that window gold is at $4,000-plus, which
is precisely the era in which the absolute-dollar thresholds documented in
`research/UNIT_MIGRATION_EVIDENCE.md` are at their *least* restrictive — L2
blocks 0.0% of 2026 bars against 100.0% of 2017-18 bars.

So this baseline cannot exercise the scale-dependence defect, and no run on this
window can. That is a data limit, not a tooling one: re-exporting does not help,
because the broker holds no deeper M1.
