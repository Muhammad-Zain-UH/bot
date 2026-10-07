# baseline_014

> # THE SHIPPED CONFIGURATION — IMMUTABLE
>
> **This is the current reference.** `baseline_010`, `011` and `013` record
> configurations that were measured and then not shipped.

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_013` remain immutable and
untouched.

## What this measures

The configuration kept after the A1–A4 / B1–B6 migration
(`research/atr_bar_convention_spec.md`, result in
`research/UNIT_MIGRATION_REPORT.md` and this directory):

* **A2, A3, A4 → `core.indicators.atr_wilder`.** Four incompatible ATR
  definitions became one. A1 was already correct and is asserted equal rather
  than edited.
* **Fabricated ATR defaults removed.** `15.0` and `10.0` are gone; a short frame
  returns `None` and the caller declines.
* **B2, B3, B4, B5 → `core.candles`.** Entry prices and L8's `current_price`
  come from the last closed bar; `pullback_detector`'s double-drop is gone.
* **B1 reverted, recorded UNRESOLVED.** See below.
* Unchanged from `baseline_012`: U9's L2 floor and U10's regime bands remain
  absolute by decision; U1's stop buffer remains $3.00.

Same dataset (`data/raw`) and assumptions as `baseline_009`: 2.0 pip assumed
spread, zero slippage and commission, 0.01 lots, 3 concurrent, conservative
intrabar. Run from a clean tree, so its recorded commit is reproducible.

## Result

| blocked at | 009 | 012 | 013 | **014** |
|---|---|---|---|---|
| | pre-migration | +units | +A/B **incl. B1** | **shipped** |
| L1_BIAS | 1,505 | 1,505 | 1,505 | **1,505** |
| L2_STRUCTURE | 12 | 12 | 12 | **12** |
| L3_PULLBACK | 5,044 | 5,044 | 5,039 | **5,039** |
| L4_LIQUIDITY | 748 | 2,142 | 2,089 | **2,089** |
| L5_SWEEP | 5,000 | 3,325 | 3,411 | **3,411** |
| L6_POI | 2 | 0 | 0 | **0** |
| L7_CONFIDENCE | 1,835 | 1,787 | 1,688 | **1,688** |
| L8_ENTRY | 1,585 | 1,917 | 1,985 | **1,985** |
| **signals** | **4** | **3** | **6** | **6** |
| decisions | 15,735 | 15,735 | 15,735 | 15,735 |

### B1 changed no gate decision on real data

**The funnel is identical to `baseline_013` at every layer**, and `013` is the
run that *included* B1. So B1 — the change that took both integration fixtures
to zero signals and caused 60 of 64 test failures — moved **not one decision**
across 15,735 on real bars.

That is the clearest statement of why it was left UNRESOLVED rather than fought
over: the only thing sensitive to it was two synthetic fixtures tuned against
the previous bar index, and on real data it is invisible at the gate level.

It is *not* invisible at the fill level. The same six signals resolved
differently — `013` recorded 2 wins and 4 losses, `014` records 4 wins and 2
losses — because `detect_rejection_candle` feeds the pullback entry's geometry,
so entry, stop and target prices differ. **Six trades carries no performance
information in either direction**, and this difference is explicitly not
evidence that either reading of B1 is better. It is recorded because the
fingerprints differ and a reader comparing them deserves to know why.

### What the migration did change, against `baseline_012`

* **L4_LIQUIDITY 2,142 → 2,089** and **L5_SWEEP 3,325 → 3,411.** A3's correction
  roughly doubled `m15_atr`, which raises `sweep_min` through the `×0.12` term
  and `sweep_max` through `×2.0`. Net on real M15 bars the band *widens* — the
  ceiling moves more than the floor — so the effect is small either way.
* **L7_CONFIDENCE 1,787 → 1,688** and **L8_ENTRY 1,917 → 1,985.** More
  candidates reach the later layers.
* **L3_PULLBACK 5,044 → 5,039.** B5's double-drop fix gives the detector one
  more closed bar.
* **L1_BIAS and L2_STRUCTURE are byte-identical** to every prior baseline, which
  confirms nothing upstream was disturbed.

### The prediction this run falsified

`research/atr_bar_convention_spec.md` §6 recorded, before the work:
*"L5_SWEEP should tighten… signals may fall below `baseline_012`'s 3"*, and
*"if signals reach zero… it will be measured, reported and put to the user."*

On real data L5 tightened by **86** decisions, L7 **loosened** by 99, and signals
**doubled to 6**. The zero-signal outcome observed in the integration fixtures
was a **fixture artefact**. Without this measurement the fixture result would
have been reported as the real one.

Also measured: **zero** "ATR unavailable" events across 15,735 decisions, so
removing the fabricated defaults cost nothing on real data.

## Not a profitability study

**Six trades.** No figure here is evidence about performance in any direction.
The win/loss split differing from `baseline_013` is a property of six samples,
not of either configuration. The **funnel** — 15,735 decisions through eight
layers — is the measurement that carries weight.

## Scope limit

Window **2026-06-02 → 2026-09-16**, bound by the broker's M1 floor of
2026-06-17, with gold above $4,000 throughout. U9's L2 floor and U10's regime
bands are still absolute, so this window continues to understate how differently
this configuration would behave across 2009–2024. It cannot be widened: the
broker holds no deeper M1.
