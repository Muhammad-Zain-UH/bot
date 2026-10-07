# Phase 4A — forward replay: did price return to each freshly formed L8 FVG?

**Read-only.** No strategy or production file was modified; `poi_engine` was
imported, not altered. No baseline artifact changed. Nothing implemented, tuned
or decided.

**Baseline:** `9ea0c5d`.

**The single question this answers:** after each of the 117 freshly formed L8
FVGs, did subsequent price action actually return to the zone, and how quickly,
measured with the repository's existing zone-touch semantics?

**It does not** decide market vs limit, does not show either design correct or
incorrect, does not infer profitability, and does not select an expiry.

---

## 1. Semantics — the real function, not a reimplementation

Touch is decided by **calling `poi_engine._zone_touched` directly**. It is
reusable here without modification for two reasons:

- it is timeframe-agnostic — the `m15_data` parameter is only indexed, so an M5
  frame is a valid argument;
- it scans `range(after_idx + 1, len(frame))`, which *is* the required "strictly
  after formation, never backward" rule.

Horizons are imposed by truncating the frame **positionally** before the call —
`full.iloc[:formation_idx + 1 + H]` makes the function examine exactly `H` bars
after formation. Bars-to-first-touch is found by exponential expansion then
bisection on `H`, valid because "touched within H bars" is monotone in `H`.
**Every touch answer in this report is the return value of the production
function.**

`confirmed_entry_price` reachability uses the same function with a zero-width
zone (`top = bottom = price`), which reduces exactly to `low <= p and high >= p`.

### The one documented reproduction

The fill fraction is computed *inline* inside `poi_engine.detect_fvg`
(lines 322-331 BUY, 347-352 SELL) and is not exposed as a callable, so it is
reproduced in form:

```
BUY  : fill = max over subsequent bars of min(1.0, (top - bar.low) / size),  counted where bar.low  < top
SELL : fill = max over subsequent bars of min(1.0, (bar.high - bottom) / size), counted where bar.high > bottom
```

The penetrated edge is fixed by geometry, not chosen: poi's BUY zone has
`fvg_top = curr_low` (gap below price, entered downward through the top); its
SELL zone has `fvg_bottom = curr_high` (gap above, entered upward through the
bottom). Two deviations, stated rather than hidden: poi scans a fixed 10-bar M15
window whereas this scans the requested horizons on M5, and poi applies the
fraction to its own 2-candle M15 gaps whereas this applies it to entry_engine's
3-candle M5 gaps — the zones actually under investigation.

### Formation point and the no-look-back rule

The FVG is complete when its **right** bar closes — `m5[-1]` as of the decision.
Formation index is the last M5 bar with `open + 5min <= decision_time`. All touch
analysis begins at `formation_idx + 1`. This is what separates *"price was
already in or near the zone at formation"* from *"price subsequently returned"*.

### Self-check — it caught a real error

The located formation bar must reproduce the `right_high`/`right_low`/
`right_close` already recorded in `docs/phase_4a_fvg_records.json`.

The first run reported **117/117 mismatches**. The cause was a unit bug: the
dataset's time column is `datetime64[us]` while `pd.Timestamp.value` is
nanoseconds, so an integer comparison mis-scaled by 1000 and selected the last
bar of the dataset every time. Fixed by comparing Timestamps via
`DatetimeIndex.searchsorted`. **Final run: 0 mismatches.** Had the check not been
there, this report would have contained entirely fabricated numbers.

---

## 2. Overall result — all 117

| Horizon after formation | Touched | % |
|---|---|---|
| 1 bar | 59 | **50.4** |
| 3 bars | 76 | 65.0 |
| 6 bars | 85 | 72.6 |
| 12 bars | 94 | 80.3 |
| 24 bars | 100 | 85.5 |
| **until end of data** | **116** | **99.1** |
| **never touched** | **1** | **0.9** |

## 3. Breakdown

| Group | n | ≤6 bars | ≤24 bars | eventually |
|---|---|---|---|---|
| BUY | 64 | 47 | 52 | 63 (98.4%) |
| SELL | 53 | 38 | 48 | 53 (100.0%) |
| MICRO_SCALP | 90 | 63 | 77 | 89 (98.9%) |
| Other regimes | 27 | 22 | 23 | 27 (100.0%) |
| Midpoint-sourced entry | 104 | 76 | 89 | 103 (99.0%) |
| CHoCH-overridden entry | 13 | 9 | 11 | 13 (100.0%) |

No group differs markedly from the whole.

## 4. Bars to first touch (116 touched cases)

| | Value |
|---|---|
| min | 1 |
| p25 | 1 |
| **median** | **1** |
| p75 | 7 |
| max | 1,464 |

| Bucket | n | % |
|---|---|---|
| 1 bar | 59 | 50.9 |
| 2–3 | 17 | 14.7 |
| 4–6 | 9 | 7.8 |
| 7–12 | 9 | 7.8 |
| 13–24 | 6 | 5.2 |
| 25–100 | 8 | 6.9 |
| 101+ | 8 | 6.9 |

**How the touch happened matters as much as whether it did.** Of the 116
touching bars:

| Touching bar relationship to the zone | n |
|---|---|
| **Straddled the zone entirely** (`low < bottom` and `high > top`) | **68** |
| Low inside the zone | 27 |
| High inside the zone | 21 |

Of the 59 that touched on the very next bar, **34 straddled**. In the majority of
cases price did not reach into the zone and stop — it passed through.

## 5. Fill / invalidation under existing `poi_engine` semantics

| | Value |
|---|---|
| Would be invalidated (`fill >= 0.5`) | **116 / 117 (99.1%)** |
| Max fill fraction — min / median / max | 0.000 / **1.000** / 1.000 |
| Touch at or before first invalidation | 116 / 116 |
| `confirmed_entry_price` subsequently touched | **116 / 117 (99.1%)** |

The median zone was **completely filled**. Touch and invalidation are frequently
the *same* bar, which is why touch-before-invalidation is 116/116 — that figure
should not be read as the zone surviving.

### Zone sizes

| | USD |
|---|---|
| min / median / max | 0.01 / **0.94** / 10.39 |

On gold near $4,000, the median zone is about **0.02% of price**.

### The one zone never touched

| Field | Value |
|---|---|
| Decision / formation | 2026-08-05 05:30 / 05:25 UTC |
| Side / regime / session | BUY / MICRO_SCALP / Asian |
| Zone | 4138.01 – 4138.09 — **$0.08 wide** |
| Bars available after formation | 7,987 |
| Max fill fraction | 0.000 |
| `confirmed_entry_price` (4138.05) touched | No |

The slowest touch was 1,464 bars (decision 2026-08-07 08:05, zone 4286.90–4288.90).

## 6. Excursion beyond `confirmed_entry_price` (item 17)

**This is not a performance measure and must not be read as one.** It records
only the maximum favourable movement past the recorded entry price, in the trade
direction. It ignores adverse movement entirely, assumes a fill at a price whose
validity is the open design question, and applies no stop, target, spread or
cost.

| Horizon | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| 1 bar | 117 | −0.03 | 2.71 | 4.46 | 5.79 | 13.59 |
| 3 bars | 117 | −0.03 | 3.19 | 5.68 | 8.10 | 22.77 |
| 6 bars | 117 | −0.03 | 3.91 | 6.88 | 10.77 | 40.77 |
| 12 bars | 117 | −0.03 | 5.66 | 9.48 | 15.86 | 72.92 |
| 24 bars | 117 | −0.03 | 6.45 | 12.60 | 23.23 | 78.78 |

The relevant context is §5: a median zone of $0.94 against a median single-bar
excursion of $4.46 means these gaps are small relative to bar range.

## 7. Determinism

| | Run 1 | Run 2 |
|---|---|---|
| Records | 117 | 117 |
| Formation-bar mismatches | **0** | **0** |
| Fingerprint | `34b1246a6e67893335ff7954fe9ee84348b60602a53d5956ccb2d7519ebf7899` | same |

Machine-readable output **byte-identical**:
`docs/phase_4a_forward_replay_records.json` (117 records, all 17 requested fields).

## 8. Answer to the question asked

**Yes — price returned to these zones, almost always, and almost immediately.**
99.1% were touched before the data ended; 50.4% on the very next bar; the median
wait was 1 bar. One zone, $0.08 wide, was never touched in 7,987 bars.

Two qualifications are part of the measurement, not commentary on it:

1. **The touch is usually a traverse, not a reach.** 68 of 116 touching bars
   straddled the zone completely, 34 of them on the first bar after formation.
2. **The zones do not survive.** Under the repository's own `fill >= 0.5`
   criterion, 116 of 117 would be invalidated, and the median zone filled
   completely.

### What this does not establish

- **Nothing about market vs limit.** Both readings are compatible with these
  numbers, and this measurement was not built to separate them.
- **Nothing about profitability.** No trade was simulated; §6 is an excursion
  record with no adverse side, no costs and no exits.
- **No expiry period.** The horizons are descriptive. Choosing one because it
  maximises touches would be selecting a parameter from an outcome, which is
  exactly what this phase exists to avoid.
- **Nothing about the 1,148 decisions where `fvg_found` was false.**
- **Nothing about whether a fill would have been obtainable.** A bar whose range
  covers a level is not proof that an order at that level would have filled at
  that price; the replay models fills at bar open, and no tick data exists.

---

*Read-only diagnostic complete. No implementation, no tuning, no design chosen. Stopping for review.*
