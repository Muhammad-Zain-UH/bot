# baseline_010

> # FULL SCALE-INVARIANCE — MEASURED AND REVERTED — IMMUTABLE
>
> **The record of what price-scaled volatility thresholds do: zero signals.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_009` remain immutable and
untouched.

## What this measured

The U1–U12 unit migration with **both** rules of
`research/unit_migration_spec.md` applied:

* **Rule 1** — ten thresholds restored to the pips their names always claimed,
  via `core.units.Pips` and the instrument specification.
* **Rule 2** — the L2 volatility floor (U9) and the regime bands (U10) scaled by
  the prevailing price, calibrated to be unchanged at the H1 median close
  ($1,544.08).

Same dataset (`data/raw`) and same assumptions as `baseline_009`, which is the
pre-migration control.

## Result: zero signals

| blocked at | 009 | 010 | delta |
|---|---|---|---|
| L1_BIAS | 1,505 | **5,950** | +4,445 |
| L2_STRUCTURE | 12 | **7,533** | +7,521 |
| L3_PULLBACK | 5,044 | 962 | −4,082 |
| L4_LIQUIDITY | 748 | 536 | −212 |
| L5_SWEEP | 5,000 | 409 | −4,591 |
| L6_POI | 2 | 0 | −2 |
| L7_CONFIDENCE | 1,835 | 208 | −1,627 |
| L8_ENTRY | 1,585 | 137 | −1,448 |
| **signals** | **4** | **0** | **−4** |
| decisions | 15,735 | 15,735 | 0 |

**85.7% of all decisions died at L1 or L2.**

### The mechanism

Gold's M5 ATR has a median of **0.1016% of price**. The scaled MICRO_SCALP floor
sits at **0.1619%** — the **84th percentile** of relative volatility — so ~85%
of bars classify `DEAD_CALM`, which blocks at L2.

The L1 jump is **indirect** and was not predicted before the run.
`entry_engine.detect_regime`'s output feeds `use_fast_bias`, which is true only
for the scalp regimes. Reclassifying bars as `DEAD_CALM` therefore also switches
L1 from the H1 fast bias to the stricter H4 bias. Nothing in L1 was modified;
its block count nearly quadrupled anyway. The funnel is what made that visible.

### What it establishes

Expressed relatively, the inherited `2.5` regime edge sat at the **84th
percentile** of volatility at $1,544 gold and the **12th percentile** at $4,550.
**It was never one threshold.**

So the strategy produced signals at all only because its thresholds happened to
be calibrated to a particular price level — the recent, high one. There is no
price-scaled form that preserves an intent these numbers never carried.

## Why Rule 2 was reverted after this run

A reference price that kept the strategy trading was available: the M5 median
($4,175) rather than the H1 median ($1,544) gives a far looser gate. Choosing it
would have been selecting a threshold by its effect on signal count, which
`research/unit_migration_spec.md` forbids explicitly.

So Rule 2 is reverted for U9 and U10 and the absoluteness is documented in place
at both sites. **Rule 1 is kept everywhere.** `core/thresholds.py` is retained,
tested, and unused by the gates: the tool is correct and the problem it solves
remains open.

This baseline is the evidence for that decision, which is why it is kept rather
than discarded.

## Not a profitability study

**Zero trades.** No figure here is evidence about performance in any direction,
and neither is `baseline_009`'s four. The measurement that carries weight is the
**funnel** — 15,735 decisions through eight layers, which is well-powered for
showing where the pipeline blocks and how a change redistributes that.

## Scope limit

The window is **2026-06-02 → 2026-09-16**, bound by the broker's M1 floor of
2026-06-17, with gold above $4,000 throughout. That is the era in which the
*absolute* thresholds are at their least restrictive, so this window understates
how differently the two configurations would behave across 2009–2024. It cannot
be widened: the broker holds no deeper M1, so re-exporting does not help.
