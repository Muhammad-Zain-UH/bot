# baseline_005

> **Current-path diagnostic baseline; zero-trade result; not a profitability
> study.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. It was added after generation and
**no generated artefact was modified.**

## What this is

A frozen record of the **current** strategy decision path (commit
`7b702ddda0b0061eab03d39403c3747784b8735a`) over the same verified dataset that
produced `baseline_004`. It exists because `baseline_004` was generated at
`04a341daa03de2e8f567b4d01f5c572f7084eb1e`, **before** `price_in_fvg` was
removed from `core_trigger` in Phase 4A Step 4 — so `baseline_004` could not be
assumed to represent the shipped trigger path.

## What it is not

- **Not a performance or profitability study.** It contains zero trades, so it
  contains zero evidence about performance, in either direction.
- **Not a replacement for `baseline_004`**, which remains frozen, untouched and
  the original production record.
- **Not a research baseline.** Any baseline generated after a strategy-contract
  change must receive its own separate identity.

## Headline result

| | |
|---|---|
| Decisions | 15,735 |
| Reached L8 | 1,265 |
| Signals | **0** |
| Pending orders / fills / trades | **0 / 0 / 0** |
| Strategy errors | 0 |
| `decisions_fingerprint` | `e9421f30331e5b3bf1688fc8f74289248059692075b882e328d9ff3eb7825c75` |
| `run_fingerprint` | `1276a31f673a5a82b2879ea5113b12e486da0d2491d03127b30370fd59f2d991` |
| `dataset_sha256` | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` |

**The zero-trade result is the expected and verified outcome**, not a failure of
the run. It was produced twice, deterministically.

**The decision stream is byte-identical to `baseline_004`.** See
`docs/BASELINE_005_PROVENANCE.md` §5 for why that is so despite the trigger
change, and for the limitation it exposes in what these artefacts record.

Full provenance: `docs/BASELINE_005_PROVENANCE.md`.
