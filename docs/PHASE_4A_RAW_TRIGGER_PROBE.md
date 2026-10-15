# Phase 4A — `raw_triggered` diagnostic probe

**Read-only.** No strategy file was modified. No threshold, entry condition,
ICT/SMC definition, session rule, RR rule, TP rule, unit, risk or execution
setting was changed. Nothing about D8 was touched.

**Objective:** determine why the allowed L8 entry candidate has
`raw_triggered = False` at all 1,265 decisions the Phase 3A baseline recorded as
blocked at L8.

**Baseline reference:** `baselines/baseline_004/` (canonical), dataset
`433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c`, strategy at
`04a341daa03de2e8f567b4d01f5c572f7084eb1e`.

---

## 1. The production conjunctions

Read from `entry_engine.py`. Both are pure ANDs, so the joint combination of
failed conditions is fully enumerable.

```
pullback.raw_triggered = rejection_found AND m1_choch_confirmed          (2 terms)

momentum.raw_triggered = kill_zone
                         AND displacement_found
                         AND fvg_found
                         AND price_in_fvg
                         AND m1_choch_confirmed                          (5 terms)
```

`momentum_confirmed` is computed on the pullback path but contributes only to
`trigger_type` and quality scoring, **not** to `raw_triggered`.

Which candidate is even evaluated depends on the regime
(`get_entry_trigger`, `allowed_styles`):

| Regime | Allowed styles |
|---|---|
| MICRO_SCALP | **MOMENTUM only** |
| INTRADAY_SWING | **PULLBACK only** |
| REGIME_SCALP, DEAD_CALM | both |

## 2. Method

For each of the 1,265 L8-blocked instants: replay the instant, run the
production decision, then re-invoke `get_sweep_and_structure` and
`get_entry_trigger` with the inputs `main_production` passes them, and read the
condition booleans **out of the dicts those production functions return**.
`_evaluate_pullback_entry` and `_evaluate_momentum_entry` already return their
sub-detector results (`rejection`, `m1_choch`, `displacement`, `fvg`,
`kill_zone`, `price_in_fvg`), so no strategy logic is reimplemented here.

Two self-checks, both reported below, so a silently diverging probe cannot pass
as evidence:

1. the re-invocation must reproduce the `setup_type`, `rr` and `rr_valid` that
   production recorded in `layer_8`;
2. each candidate's `raw_triggered` must equal the AND of the conditions read back.

| Check | Result |
|---|---|
| Records captured | 1,265 / 1,265 |
| Reconstruction mismatches vs production `layer_8` | **0** |
| AND-logic mismatches | **0** |

---

## 3. Pullback candidate

```
N = 1265

rejection_found     = TRUE:   172 (13.60%)   FALSE: 1093 (86.40%)
m1_choch_confirmed  = TRUE:   113 ( 8.93%)   FALSE: 1152 (91.07%)

raw_triggered       = TRUE:    11 ( 0.87%)   FALSE: 1254 (99.13%)
```

### Joint

| `rejection_found` | `m1_choch_confirmed` | N | % |
|---|---|---|---|
| False | False | 991 | 78.34 |
| True | False | 161 | 12.73 |
| False | True | 102 | 8.06 |
| **True** | **True** | **11** | **0.87** |

### Sole blocker — this term false, the other true

| Term | N |
|---|---|
| `rejection_found` | 102 |
| `m1_choch_confirmed` | 161 |

**Reading.** Neither term is binding on its own. Both are individually uncommon
(13.6% and 8.9%), and they are close to independent — under independence the
joint would be about 1.2% (≈15 cases); 0.87% (11) was observed, a slight negative
association. The pullback path fails because it requires the simultaneous
occurrence of two separately uncommon events, not because one condition is
broken. **No single condition can be called the cause here.**

---

## 4. Momentum candidate

```
N = 1265

kill_zone           = TRUE:   340 (26.88%)   FALSE:  925 (73.12%)
displacement_found  = TRUE:   192 (15.18%)   FALSE: 1073 (84.82%)
fvg_found           = TRUE:   117 ( 9.25%)   FALSE: 1148 (90.75%)
price_in_fvg        = TRUE:   944 (74.62%)   FALSE:  321 (25.38%)
m1_choch_confirmed  = TRUE:   113 ( 8.93%)   FALSE: 1152 (91.07%)

raw_triggered       = TRUE:     0 ( 0.00%)   FALSE: 1265 (100.00%)
```

### How many terms fail at once

| Terms false | N | % |
|---|---|---|
| 1 | 16 | 1.26 |
| 2 | 99 | 7.83 |
| 3 | 327 | 25.85 |
| 4 | 691 | 54.62 |
| 5 | 132 | 10.43 |

### Sole blocker — this term false, all other four true

| Term | N |
|---|---|
| `kill_zone` | 0 |
| `displacement_found` | 0 |
| **`fvg_found`** | **12** |
| **`price_in_fvg`** | **4** |
| `m1_choch_confirmed` | 0 |

Every one of the 16 near-misses was blocked by an FVG term. No decision was ever
one condition away with the FVG pair satisfied.

### The binding interaction: `fvg_found` ∧ `price_in_fvg`

| `fvg_found` | `price_in_fvg` | N | % |
|---|---|---|---|
| False | True | 943 | 74.55 |
| False | False | 205 | 16.21 |
| True | False | 116 | 9.17 |
| **True** | **True** | **1** | **0.08** |

**The two conditions co-occur once in 1,265.** Since `core_trigger` requires
both, the momentum path cannot fire regardless of the other three terms.

The mechanism for the 943 is visible in the source and is not an inference.
`detect_fvg` returns, when `gap_valid` is false:

```python
return {"fvg_found": False, "zone_low": gap_low, "zone_high": gap_high,
        "midpoint": None, "fvg_size": None, "fvg_quality": 0.0}
```

It reports no FVG **but still returns zone bounds** — the *inverted* gap, where
`gap_high < gap_low`. The caller then does not check `fvg_found` before using
them:

```python
if fvg.get("zone_low") is not None and fvg.get("zone_high") is not None ...:
    zone_low  = float(min(fvg["zone_low"], fvg["zone_high"]))
    zone_high = float(max(fvg["zone_low"], fvg["zone_high"]))
    midpoint  = ... if fvg.get("midpoint") is not None else (zone_low + zone_high) / 2
    price_in_fvg = zone_low <= current_price <= zone_high or ...
```

`min`/`max` silently normalises the inverted gap into a valid-looking interval,
and `midpoint` falls back to its centre because the real one is `None`. Price
frequently sits inside that interval — hence `price_in_fvg = True` in 943 cases
where no FVG exists. Those are not near-misses; they are a meaningless zone
being measured against.

For the 116 with a real FVG, `price_in_fvg` was false. That is a statement of
what was measured, not a mechanism claim: the probe records the booleans, and
characterising *why* price sat outside a genuine gap would need the zone bounds
and price, which this probe did not capture.

### `trigger_type`

| Value | N | % |
|---|---|---|
| `momentum_outside_killzone` | 925 | 73.12 |
| `momentum_wait` | 340 | 26.88 |

These mirror `kill_zone` exactly, by construction.

---

## 5. Which conditions are actually binding

Stated carefully, because frequency is not causation:

1. **Momentum — `fvg_found ∧ price_in_fvg` is binding.** Not because either is
   often false, but because they are **near-disjoint**: 1 co-occurrence in 1,265.
   Every one of the 16 one-condition-away cases was missing an FVG term, and no
   other term was ever the sole blocker. This is a structural conjunction
   failure, and the source shows at least part of the mechanism.
2. **Pullback — nothing is individually binding.** Two roughly independent,
   individually uncommon conditions must coincide. It fired 11 times.
3. **`kill_zone` is binding only in a restricted sense** — see below. It was
   never a sole blocker, so removing it alone would change nothing here.
4. **`m1_choch_confirmed` (8.93%) and `displacement_found` (15.18%) are
   infrequent but never sole blockers.** They are not the constraint on this data.

---

## 6. Session and kill-zone correlation — reported, not interpreted causally

`KILL_ZONES_UTC = ((8, 10), (12, 14))` — four hours per day.

| Session (UTC) | `kill_zone` True | False | n |
|---|---|---|---|
| Asian 00–07 | **0** | 430 | 430 |
| London 07–13 | 295 | 312 | 607 |
| NewYork 13–21 | 45 | 183 | 228 |

No `Dead` rows appear because no Dead-session decision reached L8 in the baseline.

The kill zones have **zero overlap with the Asian session** (00–07 vs 08–10 and
12–14), so `kill_zone` is false for every Asian decision as a matter of clock
arithmetic.

This interacts with regime eligibility:

| | N |
|---|---|
| MICRO_SCALP decisions at L8 | 972 |
| …with `kill_zone` True | 283 |
| …with `kill_zone` **False** | **689** |

MICRO_SCALP permits **only** MOMENTUM, and MOMENTUM requires `kill_zone`.
So those **689 decisions could not have produced an entry under any price
action** — a second structural unreachability, and unlike the RR tautology this
one is on the binding path.

Two caveats. This is a **correlation with a structural explanation**, not a
demonstrated cause of the 1,265 blocks: `kill_zone` was never a *sole* blocker,
so the remaining 283 in-kill-zone MICRO_SCALP decisions still failed on the FVG
pair. And `LondonNewYork` (D8) is **not** implicated here — `get_current_session`
never returns it, and it plays no part in `core_trigger`. Its only role is in
regime *admission*. **Not investigated further, not changed.**

---

## 7. The 11 pullback near-misses

All 11 are MICRO_SCALP, where `allowed_styles = ["MOMENTUM"]`. The pullback
candidate satisfied its full conjunction and **was not evaluated**, because it is
not an allowed style for the regime. The momentum candidate was the only one
scored, and it failed.

| # | Timestamp (UTC) | Regime | Session | Side | Allowed | Momentum terms false |
|---|---|---|---|---|---|---|
| 1 | 2026-06-30 10:15 | MICRO_SCALP | London | BUY | MOMENTUM | kill_zone, displacement, fvg |
| 2 | 2026-07-08 04:55 | MICRO_SCALP | Asian | SELL | MOMENTUM | kill_zone, displacement, fvg |
| 3 | 2026-07-08 05:50 | MICRO_SCALP | Asian | SELL | MOMENTUM | kill_zone, displacement, fvg |
| 4 | 2026-07-23 05:30 | MICRO_SCALP | Asian | BUY | MOMENTUM | kill_zone, fvg |
| 5 | 2026-07-23 12:15 | MICRO_SCALP | London | SELL | MOMENTUM | displacement, fvg |
| 6 | 2026-08-11 00:45 | MICRO_SCALP | Asian | BUY | MOMENTUM | kill_zone, displacement, fvg |
| 7 | 2026-08-12 04:05 | MICRO_SCALP | Asian | BUY | MOMENTUM | kill_zone, displacement, fvg |
| 8 | 2026-08-12 04:45 | MICRO_SCALP | Asian | BUY | MOMENTUM | kill_zone, displacement, fvg |
| 9 | 2026-09-01 04:00 | MICRO_SCALP | Asian | SELL | MOMENTUM | kill_zone, displacement, fvg |
| 10 | 2026-09-08 05:05 | MICRO_SCALP | Asian | SELL | MOMENTUM | kill_zone, displacement, fvg |
| 11 | 2026-09-15 06:00 | MICRO_SCALP | Asian | SELL | MOMENTUM | kill_zone, fvg |

`raw_triggered` state for each: pullback **True** in all 11; momentum **False**
in all 11. Eight are Asian (where `kill_zone` cannot be true); one (#5) had
`kill_zone` true and still failed on displacement and FVG. **`fvg_found` is false
in all 11.** Their eligibility was not changed.

---

## 8. Determinism

The diagnostic was run twice.

| | Run 1 | Run 2 |
|---|---|---|
| Records | 1,265 | 1,265 |
| Reconstruction mismatches | 0 | 0 |
| AND-logic mismatches | 0 | 0 |
| Diagnostic fingerprint | `f570631ce6ad842883341427de88d0db1b0b23af3d78d81c9cdb7df8ec4e4b95` | same |
| Output file SHA-256 | `303088c82a4e3354b5c57383715a8892037bdd8db2783bd8480f30f855a77fe1` | same |

The two output files are **byte-identical**. All 1,265 also reproduced their
recorded L8 block exactly, which independently re-confirms the Phase 3A replay.

---

## 9. Integrity

No strategy file was modified. The probe lives in the session scratchpad and is
not part of the repository. Working tree at the time of the run was clean at
`b864893`, whose only changes since the Phase 3A baseline are documentation and
the renamed `defect_observations` field.

The probe redirects `TRADING_BOT_LOG_FILE` and the other output paths to a
temporary directory **before** importing `main_production`, so the production
record was not touched (per the guard added in `a8b8092`).

---

## 10. Conclusions

1. **The binding constraint at L8 is the momentum path's FVG pair.**
   `fvg_found ∧ price_in_fvg` co-occurred once in 1,265 decisions. Since
   `core_trigger` ANDs both, momentum could not fire, and every one of the 16
   one-condition-away cases was missing an FVG term.
2. **Part of that is a code defect, not a market fact.** `detect_fvg` returns
   zone bounds while reporting `fvg_found: False`, and the caller uses them
   without checking the flag, `min`/`max`-normalising an inverted gap into a
   plausible-looking interval. `price_in_fvg` was true in 943 cases where no FVG
   existed. That does not by itself cause the blocks — the AND fails on
   `fvg_found` anyway — but it means `price_in_fvg` is not measuring what its
   name says, and any future work on this path must not read it as evidence that
   price was in a gap.
3. **The pullback path has no single binding condition.** It needs two
   independently uncommon events to coincide, and did so 11 times.
4. **689 MICRO_SCALP decisions were structurally unenterable** because the regime
   permits only MOMENTUM and MOMENTUM requires a kill zone that cannot be true in
   the Asian session. This is a second unreachability, on the binding path.
5. **All 11 pullback successes were discarded by regime style restriction.** The
   one path that satisfied its conjunction was not an allowed style.

### What this does NOT establish

- **Nothing about profitability.** No trade was simulated; this is a diagnostic
  of gate behaviour only.
- **No causal claim for `kill_zone`, `displacement_found` or
  `m1_choch_confirmed`.** None was ever a sole blocker.
- **No claim that fixing the FVG pair would produce entries.** It would remove
  the binding conjunction; what then becomes binding is unmeasured. The other
  four momentum terms co-occur rarely, and the sole-blocker table only describes
  the current configuration.
- **Nothing about the 13,205 decisions blocked before L8.** This probe covers the
  1,265 that reached L8.
- **Nothing about D8.** `LondonNewYork` plays no part in `core_trigger`.

### Suggested next measurement — not a fix

Characterise the FVG pair directly: for the 116 decisions where a real FVG was
found, record the zone bounds, the price tested, and the distance from the zone.
That distinguishes "the gap is real but price has left it" from "the wrong price
is being tested against the zone" — `price_in_fvg` is evaluated against the raw
`current_price` argument, whereas the entry itself is priced off
`confirmed_entry_price`. Both readings are consistent with the evidence so far,
and they imply different fixes, so the measurement should precede any change.

---

*Read-only diagnostic complete. No strategy change made. Stopping for review.*
