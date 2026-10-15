# baseline_012

> # THE RETAINED CONFIGURATION — IMMUTABLE
>
> **This is the current reference.** `baseline_010` and `baseline_011` record
> configurations that were measured and then rejected.

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. **No generated artefact was
modified.** `baseline_001` through `baseline_011` remain immutable and
untouched.

## What this measures

The configuration kept after the U1–U12 unit migration
(`research/unit_migration_spec.md`, result in
`research/UNIT_MIGRATION_REPORT.md`):

* **Rule 1 applied** at U2–U8, U11, U12 — ten thresholds restored to the pips
  their names claimed, as typed `core.units.Pips` constants.
* **Rule 2 reverted** at U9 and U10. Price-scaling met its criterion and took
  signals to zero (`baseline_010`); the floors stay absolute, documented in
  place.
* **Rule 1 reverted at U1.** The stop buffer stays $3.00, now typed as
  `Pips(30.0)`. Its intent remains UNRESOLVED, as two repo docs already had it.

Same dataset (`data/raw`) and same assumptions as `baseline_009`, the
pre-migration control: 2.0 pip assumed spread, zero slippage and commission,
0.01 lots, 3 concurrent, conservative intrabar.

## Result

| blocked at | 009 pre-mig | 010 both rules | 011 +rejected U1 | **012 retained** |
|---|---|---|---|---|
| L1_BIAS | 1,505 | 5,950 | 1,505 | **1,505** |
| L2_STRUCTURE | 12 | 7,533 | 12 | **12** |
| L3_PULLBACK | 5,044 | 962 | 5,044 | **5,044** |
| L4_LIQUIDITY | 748 | 536 | 2,142 | **2,142** |
| L5_SWEEP | 5,000 | 409 | 3,325 | **3,325** |
| L6_POI | 2 | 0 | 0 | **0** |
| L7_CONFIDENCE | 1,835 | 208 | 1,787 | **1,787** |
| L8_ENTRY | 1,585 | 137 | 1,917 | **1,917** |
| **signals** | **4** | **0** | **3** | **3** |
| decisions | 15,735 | 15,735 | 15,735 | 15,735 |

### Three layers are byte-identical to the pre-migration control

**L1_BIAS, L2_STRUCTURE and L3_PULLBACK match `baseline_009` exactly.** That is
the useful confirmation: Rule 2's revert is complete, and Rule 1 touches nothing
upstream of L4. Every change is confined to the layers whose thresholds were
migrated:

* **L4_LIQUIDITY 748 → 2,142.** U4's sweep-distance cap went from $60 — which
  is 600 pips, so no effective cap at all — to $6.00. It rejects distant pools
  for the first time. U2's proximity bonus and U3's distance penalties are also
  here.
* **L5_SWEEP 5,000 → 3,325.** U8's band moved from $2.50–$30.00 to $0.25–$3.00.
  Correcting the floor also made `m15_atr * 0.12` bind on 73.7% of bars where
  it previously bound on 1.2%, so the module's only scale-invariant term is now
  live rather than dead code.
* **L8_ENTRY 1,585 → 1,917** follows from the above: more candidates reach L8
  and fail there instead of earlier.

### Identical funnel to `baseline_011`, different trades

`011` and `012` differ only in U1's stop buffer, and the funnel is identical
because the buffer affects **stop placement**, which happens after a signal is
decided — not which decisions pass a gate. The trades therefore differ:

| | 011 ($0.30 buffer) | **012 ($3.00 buffer)** |
|---|---|---|
| signals | 3 | 3 |
| wins / losses | 2 / 1 | 2 / 1 |
| **average bars held** | **7.33** | **10.33** |
| run fingerprint | `87a6558d…` | `f5bf2a00…` |

The bars-held difference is the mechanistically meaningful one: a wider stop
survives longer before being hit. That is a structural consequence of stop
distance, not a performance finding.

## Not a profitability study

**Three trades.** No figure here is evidence about performance in any
direction, and the P&L difference between `011` and `012` is **not** evidence
that either buffer is better — three observations cannot separate a change in
edge from a change in which three bars were sampled. U1's buffer was chosen on
the spread and fixture-mechanics argument recorded in
`research/UNIT_MIGRATION_REPORT.md` §1a, explicitly **not** on this P&L.

The **funnel** is the measurement that carries weight: 15,735 decisions through
eight layers is well-powered for showing where the pipeline blocks and how a
change redistributes that.

## Scope limit

Window **2026-06-02 → 2026-09-16**, bound by the broker's M1 floor of
2026-06-17 (`main_production` requires `m1_data` for L8_ENTRY via
`detect_m1_choch`), with gold above $4,000 throughout. That is the era in which
the remaining **absolute** thresholds — U9's L2 floor and U10's regime bands —
are at their least restrictive, so this window understates how differently this
configuration would behave across 2009–2024. It cannot be widened: the broker
holds no deeper M1, so re-exporting does not help.
