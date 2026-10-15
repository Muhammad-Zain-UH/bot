# baseline_013

> # INCLUDES B1, WHICH WAS NOT SHIPPED — IMMUTABLE
>
> **Not the retained configuration.** It is the measurement that decided B1.
> `baseline_014` is what ships.

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_012` remain immutable and
untouched.

## What this measured

The full A1–A4 / B1–B6 migration of `research/atr_bar_convention_spec.md`,
**including B1** — `detect_rejection_candle` reading the last closed bar instead
of the one before it.

Same dataset (`data/raw`) and assumptions as `baseline_012`, the pre-migration
control.

## Why it is not the shipped configuration

**B1 was reverted after this run.** Its intent is genuinely two-sided and the
repo has a precedent for exactly that situation (U1's stop buffer):

* *For* it being a defect: the variable is named `current`;
  `get_market_data(closed_only=True)` drops the forming bar on all three fetch
  paths, so `iloc[-1]` **is** the last closed bar;
  `detect_displacement_candle` in the same module reads `iloc[-1]` and the two
  are alternative confirmations on a single pass; `core/candles.py` lists the
  site as "one bar stale".
* *Against*: **both** integration fixtures place the rejection candle at
  `iloc[-2]` and the break at `iloc[-1]`, and
  `tests/fixtures/integration_market.TRIGGER_BARS` is commented *"two M5
  candles: rejection, then the break"* — a coherent entry pattern and the only
  statement of intent anywhere.

Changing it took both fixtures to **zero signals** and the suite from 4 failures
to 64. Resolving it needs both fixtures rebuilt to clear all eight layers with
the rejection candle last, which is a separate measured pass. Recorded as
**UNRESOLVED** at the site and in `PHASE_2_ISSUES.md` B1.

So the figures below carry B1's effect as well as A2–A4 and B2–B6.

## Result

| blocked at | 009 | 012 | **013** |
|---|---|---|---|
| | pre-migration | +units | +ATR/bars **incl. B1** |
| L1_BIAS | 1,505 | 1,505 | 1,505 |
| L2_STRUCTURE | 12 | 12 | 12 |
| L3_PULLBACK | 5,044 | 5,044 | 5,039 |
| L4_LIQUIDITY | 748 | 2,142 | 2,089 |
| L5_SWEEP | 5,000 | 3,325 | **3,411** |
| L6_POI | 2 | 0 | 0 |
| L7_CONFIDENCE | 1,835 | 1,787 | **1,688** |
| L8_ENTRY | 1,585 | 1,917 | 1,985 |
| **signals** | **4** | **3** | **6** |
| decisions | 15,735 | 15,735 | 15,735 |

### What it establishes, and this part is independent of B1

**The spec's prediction was wrong, and this is what corrected it.** It said
*"L5_SWEEP should tighten… signals may fall below `baseline_012`'s 3"* and
*"if signals reach zero… put it to the user"*. On real data L5 tightened by only
**86 decisions**, L7 *loosened* by 99, and signals **doubled to 6**.

The zero-signal outcome seen in the integration fixtures was therefore a
**fixture artefact**, not a property of the change. The fixtures are synthetic
constructions tuned against the previous ATR; `data/raw` is not. Without this
run the fixture result would have looked like the real one.

Also recorded: the migration produced **zero** "ATR unavailable" events across
15,735 decisions, so removing the fabricated defaults (`15.0`, `10.0`) did not
cost a single decision on real data.

## Not a profitability study

**Six trades.** No figure here is evidence about performance in any direction.
`average_r` of −0.0224 against `baseline_012`'s 0.6428 is **not** a finding —
six observations cannot separate a change in edge from a change in which six
bars were sampled, and the migration changed no threshold that could create or
destroy one. The **funnel** is the measurement that carries weight.

## Scope limit

Window **2026-06-02 → 2026-09-16**, bound by the broker's M1 floor of
2026-06-17, gold above $4,000 throughout. U9's L2 floor and U10's regime bands
remain absolute by decision, so this window continues to understate how
differently the configuration would behave across 2009–2024.
