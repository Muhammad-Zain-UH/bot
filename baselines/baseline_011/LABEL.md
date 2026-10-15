# baseline_011

> # RULE 1 ONLY, INCLUDING THE REJECTED U1 VARIANT — IMMUTABLE
>
> **Not the retained configuration.** See the note below before citing it.

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_010` remain immutable and
untouched.

## What this measured

The U1–U12 unit migration with **Rule 1 only** — thresholds restored to the pips
their names claimed — after Rule 2 (price-scaling, measured in `baseline_010`)
had been reverted.

Same dataset (`data/raw`) and assumptions as `baseline_009`, the pre-migration
control.

## Read this before citing it: it includes a variant that was rejected

This run has **U1's stop buffer at $0.30** (3 pips). That reading was
subsequently **rejected on evidence** and the buffer returned to **$3.00**:

* The repository had already declined to settle U1.
  `docs/BASELINE_005_PROVENANCE.md` lists *"U1 — **is** the $3.00 stop buffer
  intended as 3 pips?"* and `docs/BROKER_SYMBOL_SPECIFICATION_EVIDENCE.md`
  records it **UNRESOLVED**. The parameter's name was the only evidence.
* `execution/fills.py` assumes a 2.0 pip spread, so a 3-pip buffer is about 1.5
  round trips — a stop the bid/ask alone can take out.
* Measured on the integration fixtures: at $0.30 the short fixture's stop sits
  $0.95 from entry and is hit on the **next bar**, turning a TARGET_HIT into a
  STOPPED. Noise decided the outcome rather than structure.

So the figures below carry U1's effect as well as the rest of Rule 1, and the
retained configuration is **not** this one. `baseline_012` is the record of what
was kept.

## Result

| blocked at | 009 | 010 | **011** |
|---|---|---|---|
| | pre-migration | both rules | Rule 1 + rejected U1 |
| L1_BIAS | 1,505 | 5,950 | **1,505** |
| L2_STRUCTURE | 12 | 7,533 | **12** |
| L3_PULLBACK | 5,044 | 962 | **5,044** |
| L4_LIQUIDITY | 748 | 536 | **2,142** |
| L5_SWEEP | 5,000 | 409 | **3,325** |
| L6_POI | 2 | 0 | 0 |
| L7_CONFIDENCE | 1,835 | 208 | 1,787 |
| L8_ENTRY | 1,585 | 137 | 1,917 |
| **signals** | **4** | **0** | **3** |
| decisions | 15,735 | 15,735 | 15,735 |

### What it establishes, and this part is not affected by the U1 variant

**L1, L2 and L3 are byte-identical to `baseline_009`.** That is the useful
result: it confirms Rule 2's revert is complete, and that Rule 1 touches nothing
upstream of L4. The changes are confined to exactly the layers whose thresholds
were migrated:

* **L4_LIQUIDITY 748 → 2,142.** U4's sweep-distance cap went from $60 (600 pips
  — no effective cap) to $6.00, so it rejects distant pools for the first time.
  U2 and U3's proximity bonus and distance penalties also live here.
* **L5_SWEEP 5,000 → 3,325.** U8's band moved from $2.50–$30.00 to $0.25–$3.00,
  and correcting the floor also made `m15_atr * 0.12` bind on 73.7% of bars
  where it previously bound on 1.2%.

Signals fell 4 → 3, so the strategy stays active — unlike under Rule 2.

## Not a profitability study

**Three trades.** No figure here is evidence about performance in any
direction. `average_r` reads higher than `baseline_009`'s and that means
nothing: three observations cannot distinguish a change in edge from a change in
which three bars were sampled. The **funnel** is the measurement that carries
weight.

## Scope limit

Window **2026-06-02 → 2026-09-16**, bound by the broker's M1 floor of
2026-06-17, gold above $4,000 throughout. It cannot be widened — the broker
holds no deeper M1.
