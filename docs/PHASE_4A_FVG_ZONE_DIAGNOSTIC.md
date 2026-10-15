# Phase 4A — FVG zone / price-test diagnostic

**Read-only.** No strategy file was modified. No entry logic, FVG detection,
threshold, session rule or production code was changed. The defect described
here is **not fixed**.

**Question this answers:** is the zero-entry condition caused by a genuine
absence of price/FVG overlap, an incorrect FVG representation, testing the wrong
price (`current_price` vs `confirmed_entry_price`), or a combination?

**Answer, up front:** overwhelmingly **the wrong price is being tested**. In 103
of the 116 blocked cases the price the gate examines is outside the FVG while the
price the entry would actually use is inside it — and inside *by construction*,
because it **is** the FVG's midpoint. The remaining 13 are genuine non-overlap.
The FVG representation itself is sound in all 117: no inverted bounds, no
midpoint fallbacks.

**Scope:** the 117 decisions among the 1,265 Phase 3A L8 blocks where the
production momentum candidate reported `fvg_found = True` — 116 with
`price_in_fvg = False`, 1 with `price_in_fvg = True`.

**Baseline preserved:** `baselines/baseline_004/` untouched; dataset
`433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c`.

---

## 1. What the production code does between detection and the price test

```
FVG is built from three M5 bars:  left = m5[-3]   middle = m5[-2]   right = m5[-1]

detect_fvg (BUY) : gap_low = left.high,  gap_high = right.low,  needs middle bullish
detect_fvg (SELL): gap_low = right.high, gap_high = left.low,   needs middle bearish
                   gap_valid  = gap_high > gap_low AND middle body direction
                   fvg_found  = gap_valid
                   midpoint   = gap_low + size/2   (None when invalid)

main_production.py:983   confirmed_m5_close = m5[-2].close        <-- the MIDDLE bar
                         passed to get_entry_trigger as current_price

_evaluate_momentum_entry:
    confirmed_entry_price = m5[-1].close
    if fvg.midpoint is not None:   confirmed_entry_price = fvg.midpoint
    if m1_choch_confirmed:         confirmed_entry_price = m1[-1].close

    price_in_fvg tests  current_price  ==  m5[-2].close           <-- NOT the entry price
```

Two distinct prices exist, and the gate does not test the one the trade would use:

| | Value | Role |
|---|---|---|
| `current_price` (as received here) | `m5[-2].close` — the FVG's own **middle candle** | the only price `price_in_fvg` examines |
| `confirmed_entry_price` | `fvg.midpoint`, or `m1[-1].close` under CHoCH | the price the entry is actually built on |

## 2. Method

For each of the 117: replay the instant, run the production decision, then
re-invoke `get_sweep_and_structure` and `get_entry_trigger` with the inputs
`main_production` passes them. **The FVG dict is the production detector's own
return value** (`momentum_entry["fvg"]`); `price_in_fvg`, `entry_price` and every
condition boolean are the production function's outputs. The detector is not
reimplemented.

Two lines are reproduced so the probe can report the inputs production used —
`confirmed_m5_close` and the `min`/`max` + midpoint-fallback normalisation — and
both are checked against production's own outputs:

| Self-check | Result |
|---|---|
| Records captured | 117 / 117 |
| Recomputed `price_in_fvg` != production `price_in_fvg` | **0** |
| `confirmed_entry_price` not attributable to a known override | **0** |

## 3. Structural facts across all 117

| Property | Count |
|---|---|
| Bounds came from the production detector | 117 / 117 |
| **Raw bounds inverted** (`gap_high < gap_low`) | **0** |
| **Midpoint was the caller's fallback** (`(low+high)/2`) | **0** |
| `min`/`max` normalisation altered the interval | 0 |
| Price tested = `m5[-2].close` | 117 / 117 |
| Entry price = `fvg.midpoint` | 104 |
| Entry price = `m1[-1].close` (CHoCH override) | 13 |

**The inverted-bounds and fallback-midpoint pathologies reported in the previous
diagnostic do not occur here.** They belong exclusively to the
`fvg_found = False` population. Where an FVG genuinely exists, its representation
is well formed: `gap_high > gap_low`, real midpoint, no normalisation applied.

The entry-price source determines everything:

| Entry source | N | Entry inside the genuine FVG |
|---|---|---|
| `fvg.midpoint` | 104 | **104 / 104** (by construction — it is the centre) |
| `m1[-1].close` (CHoCH) | 13 | **0 / 13** |

## 4. Classification of the 116 `fvg_found=True, price_in_fvg=False` cases

Mutually exclusive, evaluated in order.

| Cat | Definition | N | % |
|---|---|---|---|
| **F** | **Wrong price tested.** `m5[-2].close` outside the genuine FVG, `confirmed_entry_price` inside it — and inside because it *is* `fvg.midpoint`. | **103** | **88.8** |
| **A** | Both genuinely outside. `confirmed_entry_price` came from the M1 CHoCH override and landed outside the zone. | **13** | **11.2** |
| B | Current outside, entry inside, entry **not** the midpoint | 0 | 0 |
| C | Current inside the genuine FVG yet production reports `price_in_fvg` False | 0 | 0 |
| D | Invalid / inverted bounds | 0 | 0 |
| E | FVG exists but zone construction inconsistent | 0 | 0 |
| G | Other | 0 | 0 |

No category was invented and none was needed: every one of the 116 falls into F
or A, and the split is exactly the entry-source split (103 = the 104 midpoint
cases minus the 1 that passed; 13 = all CHoCH cases).

### How far outside was the tested price?

| | USD |
|---|---|
| Distance from zone, min / median / max | 0.01 / **0.79** / 11.87 |
| Zone width, min / median / max | 0.01 / 0.94 / 10.39 |
| Distance as a multiple of zone width, median | **1.1x** |

These are not marginal misses. The tested price typically sits about one full
zone-width outside — consistent with it being the *middle* candle's close while
the zone is the gap between the candles on either side of it.

## 5. The single `fvg_found=True AND price_in_fvg=True` case

| Field | Value |
|---|---|
| Timestamp | **2026-08-28 03:40:00 UTC** |
| Symbol / timeframe | XAUUSD / M5 |
| Side / FVG type | SELL / bearish |
| Regime / session | MICRO_SCALP / Asian |
| Raw `zone_low` / `zone_high` | 4584.24 / 4586.50 |
| Raw midpoint | 4585.37 (real, not fallback) |
| Bounds inverted | No |
| Normalised zone | 4584.24 – 4586.50 (unchanged) |
| Zone width / tolerance band | 2.26 / 0.791 |
| Price tested by `price_in_fvg` | **4584.26** (`m5[-2].close`) |
| Decision price | 4582.88 |
| `confirmed_entry_price` | 4585.37 — source `fvg.midpoint` |
| `current_price` inside genuine FVG | **True** (by 0.02) |
| `confirmed_entry_price` inside genuine FVG | True |
| `fvg_found` / `price_in_fvg` | True / True |
| `m1_choch_confirmed` | **False** |
| `displacement_found` | **False** |
| `kill_zone` | **False** |
| `raw_triggered` | **False** |
| M5 bars | left H/L 4590.04 / 4586.50; mid O/C 4587.96 / 4584.26; right H/L 4584.24 / 4582.20 |

The one case where both FVG conditions aligned did so by 2 cents, and still did
not fire: `kill_zone`, `displacement_found` and `m1_choch_confirmed` were all
false. It is in the Asian session, where the kill zone cannot be true.

## 6. Determinism

| | Run 1 | Run 2 |
|---|---|---|
| Records | 117 | 117 |
| Recompute mismatches | 0 | 0 |
| Fingerprint | `20f05f00b8633aa7c188ac2b4c482e0743437ee446f9a860c3cb23cc6e393a2a` | same |

Output files **byte-identical**.

## 7. Causal conclusion

Stated only now that all 117 are classified.

**It is a combination, but not an even one.**

1. **Testing the wrong price accounts for 103 of 116 (88.8%).** `price_in_fvg`
   examines `m5[-2].close` — the close of the FVG's own middle candle, which sits
   between the two bars forming the gap and is therefore structurally unlikely to
   be inside it. Meanwhile `confirmed_entry_price` is set to `fvg.midpoint`,
   which is inside the zone by definition. The gate rejects the setup on the
   grounds that price is not in the zone, while the entry it would have placed
   sits at the zone's exact centre. The two prices are never compared.
2. **Genuine non-overlap accounts for 13 of 116 (11.2%)** — precisely the cases
   where the CHoCH override replaced the midpoint with `m1[-1].close`, which fell
   outside. For these the gate's verdict and the entry price agree.
3. **Incorrect FVG representation accounts for 0 of 116.** Where an FVG exists,
   its bounds are well formed. The inversion/fallback defect reported in the
   previous diagnostic is confined to the `fvg_found = False` population, where
   it is masked by `fvg_found` failing the AND anyway.

So the earlier finding that `fvg_found ∧ price_in_fvg` co-occurs once in 1,265 is
now explained: not because price is rarely near a fair-value gap, but because the
condition is evaluated against a price that is structurally almost never inside
one — the middle candle of the very pattern being tested.

### What this does NOT establish

- **It does not establish that correcting the price test would produce trades,
  and no such claim is made.** Of the 117, `kill_zone` was false in most,
  `displacement_found` false in most, and `m1_choch_confirmed` false in 104. The
  momentum trigger is a five-way AND; removing one obstacle reveals the next,
  which is unmeasured.
- **It does not establish which price *ought* to be tested.** That `m5[-2].close`
  is a poor choice follows from the pattern's geometry; what the correct choice
  is is a design decision, not a measurement. Note that testing
  `confirmed_entry_price` would be close to vacuous whenever that price is the
  midpoint, since the result would be true by construction — a second tautology,
  of the same family as the RR one. Neither option should be adopted without
  first deciding what the check is *for*.
- **Nothing about profitability.** No trade was simulated.
- **Nothing about the 1,148 decisions where `fvg_found` was false.**

## 8. Integrity

No strategy file modified. The probe lives in the session scratchpad. The
production record was not touched: output paths are redirected to a temporary
directory before `main_production` is imported.

---

## Appendix — all 117 records

Full per-record JSON with every captured field, including the raw M5 bars:
`docs/phase_4a_fvg_records.json`.

Columns: `cur in` / `ent in` = inside the genuine FVG interval;
`p_in_fvg` = production `price_in_fvg`; `cat` = classification.

| # | timestamp (UTC) | side | regime | session | zone_low | zone_high | midpoint | tested m5[-2].close | entry price | entry source | cur in | ent in | p_in_fvg | cat |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-25 09:00 | SELL | REGIME_S | London | 3991.18 | 3991.68 | 3991.43 | 3990.80 | 3991.43 | midpoint | n | Y | F | F |
| 2 | 2026-06-25 09:45 | SELL | REGIME_S | London | 3992.08 | 3993.54 | 3992.81 | 3992.02 | 3992.81 | midpoint | n | Y | F | F |
| 3 | 2026-06-25 15:30 | BUY | SWING | NewYork | 4015.67 | 4026.06 | 4020.86 | 4037.93 | 4020.86 | midpoint | n | Y | F | F |
| 4 | 2026-06-25 18:25 | BUY | REGIME_S | NewYork | 4034.70 | 4037.21 | 4035.95 | 4037.94 | 4035.95 | midpoint | n | Y | F | F |
| 5 | 2026-06-25 19:15 | BUY | REGIME_S | NewYork | 4035.99 | 4038.37 | 4037.18 | 4038.80 | 4037.18 | midpoint | n | Y | F | F |
| 6 | 2026-07-01 03:30 | SELL | MICRO_S | Asian | 3983.07 | 3983.33 | 3983.20 | 3982.69 | 3983.20 | midpoint | n | Y | F | F |
| 7 | 2026-07-01 05:20 | SELL | MICRO_S | Asian | 3972.50 | 3972.56 | 3972.53 | 3971.93 | 3972.53 | midpoint | n | Y | F | F |
| 8 | 2026-07-02 09:50 | BUY | MICRO_S | London | 4067.53 | 4068.36 | 4067.95 | 4069.36 | 4067.95 | midpoint | n | Y | F | F |
| 9 | 2026-07-02 11:20 | BUY | MICRO_S | London | 4060.80 | 4062.76 | 4061.78 | 4063.30 | 4061.78 | midpoint | n | Y | F | F |
| 10 | 2026-07-02 11:50 | BUY | MICRO_S | London | 4067.30 | 4067.97 | 4067.64 | 4071.18 | 4067.64 | midpoint | n | Y | F | F |
| 11 | 2026-07-03 04:15 | BUY | MICRO_S | Asian | 4176.59 | 4177.30 | 4176.94 | 4178.11 | 4176.94 | midpoint | n | Y | F | F |
| 12 | 2026-07-06 07:00 | SELL | MICRO_S | London | 4152.76 | 4154.04 | 4153.40 | 4151.96 | 4153.40 | midpoint | n | Y | F | F |
| 13 | 2026-07-06 11:25 | BUY | MICRO_S | London | 4155.13 | 4155.53 | 4155.33 | 4157.52 | 4155.33 | midpoint | n | Y | F | F |
| 14 | 2026-07-06 12:10 | BUY | MICRO_S | London | 4155.95 | 4156.27 | 4156.11 | 4156.42 | 4156.11 | midpoint | n | Y | F | F |
| 15 | 2026-07-08 06:20 | BUY | MICRO_S | Asian | 4125.89 | 4128.85 | 4127.37 | 4131.62 | 4127.37 | midpoint | n | Y | F | F |
| 16 | 2026-07-08 19:50 | SELL | REGIME_S | NewYork | 4084.28 | 4086.26 | 4085.27 | 4084.06 | 4085.27 | midpoint | n | Y | F | F |
| 17 | 2026-07-09 04:20 | SELL | MICRO_S | Asian | 4060.65 | 4061.13 | 4060.89 | 4060.52 | 4060.89 | midpoint | n | Y | F | F |
| 18 | 2026-07-14 07:50 | SELL | MICRO_S | London | 4024.21 | 4024.79 | 4024.50 | 4023.65 | 4024.50 | midpoint | n | Y | F | F |
| 19 | 2026-07-14 12:15 | SELL | MICRO_S | London | 4028.39 | 4029.16 | 4028.77 | 4025.82 | 4028.77 | midpoint | n | Y | F | F |
| 20 | 2026-07-17 00:35 | SELL | MICRO_S | Asian | 3985.06 | 3986.47 | 3985.76 | 3984.76 | 3985.76 | midpoint | n | Y | F | F |
| 21 | 2026-07-17 12:30 | SELL | MICRO_S | London | 3987.81 | 3988.74 | 3988.27 | 3985.69 | 3988.27 | midpoint | n | Y | F | F |
| 22 | 2026-07-17 12:40 | SELL | MICRO_S | London | 3983.09 | 3984.36 | 3983.73 | 3981.70 | 3977.75 | m1 CHoCH | n | n | F | A |
| 23 | 2026-07-20 07:20 | SELL | MICRO_S | London | 4004.61 | 4004.88 | 4004.74 | 4004.26 | 4004.74 | midpoint | n | Y | F | F |
| 24 | 2026-07-21 06:15 | BUY | MICRO_S | Asian | 4066.51 | 4066.67 | 4066.59 | 4067.72 | 4066.59 | midpoint | n | Y | F | F |
| 25 | 2026-07-21 06:20 | BUY | MICRO_S | Asian | 4067.75 | 4068.32 | 4068.03 | 4071.28 | 4068.03 | midpoint | n | Y | F | F |
| 26 | 2026-07-21 07:40 | BUY | MICRO_S | London | 4071.11 | 4072.49 | 4071.80 | 4073.27 | 4071.80 | midpoint | n | Y | F | F |
| 27 | 2026-07-21 12:45 | SELL | MICRO_S | London | 4056.14 | 4059.03 | 4057.59 | 4055.04 | 4057.59 | midpoint | n | Y | F | F |
| 28 | 2026-07-21 13:50 | SELL | REGIME_S | NewYork | 4050.44 | 4050.96 | 4050.70 | 4046.37 | 4050.70 | midpoint | n | Y | F | F |
| 29 | 2026-07-22 00:15 | BUY | MICRO_S | Asian | 4082.80 | 4087.49 | 4085.14 | 4088.10 | 4085.14 | midpoint | n | Y | F | F |
| 30 | 2026-07-22 05:45 | BUY | MICRO_S | Asian | 4128.78 | 4130.08 | 4129.43 | 4132.52 | 4129.43 | midpoint | n | Y | F | F |
| 31 | 2026-07-22 07:20 | BUY | MICRO_S | London | 4115.63 | 4115.91 | 4115.77 | 4116.39 | 4115.77 | midpoint | n | Y | F | F |
| 32 | 2026-07-22 09:00 | BUY | MICRO_S | London | 4116.30 | 4117.46 | 4116.88 | 4117.52 | 4116.88 | midpoint | n | Y | F | F |
| 33 | 2026-07-23 05:35 | BUY | MICRO_S | Asian | 4122.81 | 4123.35 | 4123.08 | 4125.63 | 4123.08 | midpoint | n | Y | F | F |
| 34 | 2026-07-23 05:40 | BUY | MICRO_S | Asian | 4125.63 | 4126.14 | 4125.89 | 4127.54 | 4125.89 | midpoint | n | Y | F | F |
| 35 | 2026-07-23 15:15 | SELL | REGIME_S | NewYork | 4054.05 | 4055.47 | 4054.76 | 4052.06 | 4054.76 | midpoint | n | Y | F | F |
| 36 | 2026-07-24 06:00 | SELL | MICRO_S | Asian | 4023.93 | 4024.53 | 4024.23 | 4023.46 | 4024.23 | midpoint | n | Y | F | F |
| 37 | 2026-07-24 13:15 | SELL | MICRO_S | NewYork | 4049.64 | 4051.49 | 4050.56 | 4046.48 | 4050.56 | midpoint | n | Y | F | F |
| 38 | 2026-07-29 00:55 | SELL | MICRO_S | Asian | 4024.02 | 4024.12 | 4024.07 | 4021.15 | 4024.07 | midpoint | n | Y | F | F |
| 39 | 2026-07-29 07:15 | BUY | MICRO_S | London | 4044.20 | 4044.45 | 4044.32 | 4044.64 | 4044.32 | midpoint | n | Y | F | F |
| 40 | 2026-07-29 12:30 | SELL | MICRO_S | London | 4017.40 | 4018.83 | 4018.11 | 4015.79 | 4013.10 | m1 CHoCH | n | n | F | A |
| 41 | 2026-07-29 13:10 | SELL | MICRO_S | NewYork | 4019.27 | 4021.08 | 4020.18 | 4018.75 | 4020.18 | midpoint | n | Y | F | F |
| 42 | 2026-07-31 05:05 | BUY | MICRO_S | Asian | 4078.10 | 4079.74 | 4078.92 | 4079.91 | 4082.45 | m1 CHoCH | n | n | F | A |
| 43 | 2026-07-31 05:10 | BUY | MICRO_S | Asian | 4080.03 | 4080.95 | 4080.49 | 4082.45 | 4080.49 | midpoint | n | Y | F | F |
| 44 | 2026-07-31 09:15 | SELL | MICRO_S | London | 4058.05 | 4060.35 | 4059.20 | 4057.55 | 4059.20 | midpoint | n | Y | F | F |
| 45 | 2026-07-31 09:20 | SELL | MICRO_S | London | 4057.14 | 4057.55 | 4057.35 | 4056.63 | 4057.35 | midpoint | n | Y | F | F |
| 46 | 2026-08-05 05:30 | BUY | MICRO_S | Asian | 4138.01 | 4138.09 | 4138.05 | 4141.37 | 4138.05 | midpoint | n | Y | F | F |
| 47 | 2026-08-06 05:45 | BUY | REGIME_S | Asian | 4257.82 | 4261.14 | 4259.48 | 4261.91 | 4259.48 | midpoint | n | Y | F | F |
| 48 | 2026-08-06 05:50 | BUY | REGIME_S | Asian | 4262.13 | 4262.18 | 4262.16 | 4263.38 | 4262.16 | midpoint | n | Y | F | F |
| 49 | 2026-08-06 07:15 | BUY | REGIME_S | London | 4256.67 | 4259.42 | 4258.05 | 4259.48 | 4258.05 | midpoint | n | Y | F | F |
| 50 | 2026-08-06 07:20 | BUY | REGIME_S | London | 4260.16 | 4261.13 | 4260.65 | 4263.18 | 4264.36 | m1 CHoCH | n | n | F | A |
| 51 | 2026-08-06 08:00 | BUY | MICRO_S | London | 4257.22 | 4258.33 | 4257.77 | 4259.56 | 4262.66 | m1 CHoCH | n | n | F | A |
| 52 | 2026-08-06 08:05 | BUY | REGIME_S | London | 4259.61 | 4260.22 | 4259.91 | 4262.66 | 4259.91 | midpoint | n | Y | F | F |
| 53 | 2026-08-06 08:20 | BUY | MICRO_S | London | 4264.83 | 4267.72 | 4266.27 | 4268.87 | 4266.27 | midpoint | n | Y | F | F |
| 54 | 2026-08-07 08:05 | BUY | MICRO_S | London | 4286.90 | 4288.90 | 4287.90 | 4289.93 | 4287.90 | midpoint | n | Y | F | F |
| 55 | 2026-08-07 08:10 | BUY | MICRO_S | London | 4291.09 | 4292.22 | 4291.66 | 4292.23 | 4291.66 | midpoint | n | Y | F | F |
| 56 | 2026-08-07 14:25 | BUY | SWING | NewYork | 4341.75 | 4343.53 | 4342.64 | 4345.81 | 4351.25 | m1 CHoCH | n | n | F | A |
| 57 | 2026-08-10 04:20 | BUY | MICRO_S | Asian | 4327.57 | 4330.59 | 4329.08 | 4332.08 | 4333.75 | m1 CHoCH | n | n | F | A |
| 58 | 2026-08-10 04:25 | BUY | MICRO_S | Asian | 4332.67 | 4333.00 | 4332.84 | 4333.75 | 4332.84 | midpoint | n | Y | F | F |
| 59 | 2026-08-11 00:30 | BUY | MICRO_S | Asian | 4407.76 | 4411.60 | 4409.68 | 4412.11 | 4409.68 | midpoint | n | Y | F | F |
| 60 | 2026-08-11 10:30 | BUY | MICRO_S | London | 4375.00 | 4376.38 | 4375.69 | 4377.48 | 4375.69 | midpoint | n | Y | F | F |
| 61 | 2026-08-11 10:35 | BUY | MICRO_S | London | 4377.83 | 4377.99 | 4377.91 | 4378.12 | 4377.91 | midpoint | n | Y | F | F |
| 62 | 2026-08-12 00:20 | BUY | MICRO_S | Asian | 4371.01 | 4373.94 | 4372.48 | 4377.94 | 4379.70 | m1 CHoCH | n | n | F | A |
| 63 | 2026-08-12 01:15 | BUY | MICRO_S | Asian | 4385.20 | 4386.73 | 4385.97 | 4387.05 | 4385.97 | midpoint | n | Y | F | F |
| 64 | 2026-08-12 01:55 | BUY | MICRO_S | Asian | 4393.18 | 4394.81 | 4394.00 | 4395.01 | 4394.00 | midpoint | n | Y | F | F |
| 65 | 2026-08-12 06:45 | BUY | MICRO_S | Asian | 4390.36 | 4393.37 | 4391.86 | 4393.84 | 4391.86 | midpoint | n | Y | F | F |
| 66 | 2026-08-12 07:00 | BUY | MICRO_S | London | 4400.64 | 4401.06 | 4400.85 | 4401.08 | 4400.85 | midpoint | n | Y | F | F |
| 67 | 2026-08-12 07:35 | BUY | MICRO_S | London | 4400.48 | 4401.34 | 4400.91 | 4402.37 | 4400.91 | midpoint | n | Y | F | F |
| 68 | 2026-08-12 09:20 | BUY | MICRO_S | London | 4408.83 | 4412.30 | 4410.57 | 4412.75 | 4410.57 | midpoint | n | Y | F | F |
| 69 | 2026-08-12 09:25 | BUY | MICRO_S | London | 4413.02 | 4413.45 | 4413.24 | 4415.35 | 4423.52 | m1 CHoCH | n | n | F | A |
| 70 | 2026-08-12 11:35 | BUY | MICRO_S | London | 4411.39 | 4412.84 | 4412.11 | 4414.97 | 4412.11 | midpoint | n | Y | F | F |
| 71 | 2026-08-12 14:15 | BUY | SWING | NewYork | 4429.09 | 4429.10 | 4429.10 | 4429.64 | 4429.10 | midpoint | n | Y | F | F |
| 72 | 2026-08-12 16:05 | BUY | SWING | NewYork | 4416.70 | 4418.17 | 4417.43 | 4420.99 | 4417.43 | midpoint | n | Y | F | F |
| 73 | 2026-08-12 16:20 | BUY | REGIME_S | NewYork | 4422.18 | 4422.62 | 4422.40 | 4423.35 | 4422.40 | midpoint | n | Y | F | F |
| 74 | 2026-08-13 08:35 | BUY | MICRO_S | London | 4370.79 | 4371.85 | 4371.32 | 4372.74 | 4371.32 | midpoint | n | Y | F | F |
| 75 | 2026-08-14 12:05 | BUY | MICRO_S | London | 4368.20 | 4369.01 | 4368.60 | 4369.20 | 4368.60 | midpoint | n | Y | F | F |
| 76 | 2026-08-17 18:20 | BUY | DEAD_CALM | NewYork | 4413.14 | 4413.39 | 4413.27 | 4413.76 | 4413.27 | midpoint | n | Y | F | F |
| 77 | 2026-08-18 10:00 | BUY | MICRO_S | London | 4392.28 | 4392.75 | 4392.51 | 4393.97 | 4392.51 | midpoint | n | Y | F | F |
| 78 | 2026-08-18 10:40 | BUY | MICRO_S | London | 4392.18 | 4393.45 | 4392.82 | 4393.61 | 4397.50 | m1 CHoCH | n | n | F | A |
| 79 | 2026-08-20 00:10 | BUY | MICRO_S | Asian | 4513.25 | 4513.91 | 4513.58 | 4514.77 | 4513.58 | midpoint | n | Y | F | F |
| 80 | 2026-08-20 07:40 | BUY | MICRO_S | London | 4486.22 | 4488.99 | 4487.60 | 4489.73 | 4487.60 | midpoint | n | Y | F | F |
| 81 | 2026-08-20 10:35 | BUY | MICRO_S | London | 4490.77 | 4492.46 | 4491.61 | 4493.77 | 4491.61 | midpoint | n | Y | F | F |
| 82 | 2026-08-20 18:30 | BUY | REGIME_S | NewYork | 4516.25 | 4516.34 | 4516.30 | 4516.44 | 4516.30 | midpoint | n | Y | F | F |
| 83 | 2026-08-20 18:35 | BUY | REGIME_S | NewYork | 4518.07 | 4518.39 | 4518.23 | 4519.00 | 4518.23 | midpoint | n | Y | F | F |
| 84 | 2026-08-21 05:40 | BUY | MICRO_S | Asian | 4534.46 | 4535.19 | 4534.82 | 4537.88 | 4534.82 | midpoint | n | Y | F | F |
| 85 | 2026-08-24 17:15 | BUY | SWING | NewYork | 4647.61 | 4649.39 | 4648.50 | 4652.36 | 4648.50 | midpoint | n | Y | F | F |
| 86 | 2026-08-28 03:40 | SELL | MICRO_S | Asian | 4584.24 | 4586.50 | 4585.37 | 4584.26 | 4585.37 | midpoint | Y | Y | T | PASS |
| 87 | 2026-08-28 03:50 | SELL | MICRO_S | Asian | 4582.11 | 4582.20 | 4582.15 | 4581.90 | 4582.15 | midpoint | n | Y | F | F |
| 88 | 2026-08-28 03:55 | SELL | MICRO_S | Asian | 4580.84 | 4580.91 | 4580.88 | 4580.56 | 4580.88 | midpoint | n | Y | F | F |
| 89 | 2026-08-28 04:40 | SELL | MICRO_S | Asian | 4581.89 | 4583.05 | 4582.47 | 4581.64 | 4578.35 | m1 CHoCH | n | n | F | A |
| 90 | 2026-08-28 04:45 | SELL | MICRO_S | Asian | 4580.17 | 4581.62 | 4580.90 | 4578.35 | 4580.90 | midpoint | n | Y | F | F |
| 91 | 2026-08-28 05:15 | SELL | MICRO_S | Asian | 4580.62 | 4582.01 | 4581.32 | 4579.02 | 4581.32 | midpoint | n | Y | F | F |
| 92 | 2026-08-28 08:45 | SELL | MICRO_S | London | 4607.60 | 4607.99 | 4607.80 | 4607.36 | 4603.47 | m1 CHoCH | n | n | F | A |
| 93 | 2026-08-28 08:50 | SELL | MICRO_S | London | 4603.53 | 4606.46 | 4604.99 | 4603.47 | 4604.99 | midpoint | n | Y | F | F |
| 94 | 2026-08-31 09:30 | SELL | MICRO_S | London | 4439.78 | 4440.72 | 4440.25 | 4439.35 | 4440.25 | midpoint | n | Y | F | F |
| 95 | 2026-09-01 04:05 | SELL | MICRO_S | Asian | 4437.66 | 4440.78 | 4439.22 | 4436.58 | 4439.22 | midpoint | n | Y | F | F |
| 96 | 2026-09-01 04:15 | SELL | MICRO_S | Asian | 4432.37 | 4435.54 | 4433.95 | 4431.96 | 4433.95 | midpoint | n | Y | F | F |
| 97 | 2026-09-01 06:05 | SELL | REGIME_S | Asian | 4440.50 | 4440.99 | 4440.74 | 4440.15 | 4440.74 | midpoint | n | Y | F | F |
| 98 | 2026-09-01 06:10 | SELL | REGIME_S | Asian | 4438.59 | 4439.99 | 4439.29 | 4436.41 | 4439.29 | midpoint | n | Y | F | F |
| 99 | 2026-09-01 06:35 | SELL | MICRO_S | Asian | 4430.32 | 4430.88 | 4430.60 | 4428.98 | 4430.60 | midpoint | n | Y | F | F |
| 100 | 2026-09-01 06:55 | SELL | MICRO_S | Asian | 4430.32 | 4432.73 | 4431.52 | 4429.97 | 4431.52 | midpoint | n | Y | F | F |
| 101 | 2026-09-02 03:25 | SELL | REGIME_S | Asian | 4297.80 | 4297.95 | 4297.88 | 4297.74 | 4297.88 | midpoint | n | Y | F | F |
| 102 | 2026-09-04 00:50 | BUY | MICRO_S | Asian | 4479.44 | 4481.24 | 4480.34 | 4482.14 | 4480.34 | midpoint | n | Y | F | F |
| 103 | 2026-09-04 18:30 | BUY | REGIME_S | NewYork | 4422.36 | 4423.30 | 4422.83 | 4424.62 | 4422.83 | midpoint | n | Y | F | F |
| 104 | 2026-09-08 04:25 | SELL | MICRO_S | Asian | 4438.86 | 4439.04 | 4438.95 | 4438.79 | 4438.95 | midpoint | n | Y | F | F |
| 105 | 2026-09-08 04:30 | SELL | MICRO_S | Asian | 4433.95 | 4437.90 | 4435.92 | 4433.38 | 4435.92 | midpoint | n | Y | F | F |
| 106 | 2026-09-08 05:30 | SELL | MICRO_S | Asian | 4425.30 | 4426.20 | 4425.75 | 4424.69 | 4420.46 | m1 CHoCH | n | n | F | A |
| 107 | 2026-09-08 09:30 | SELL | MICRO_S | London | 4396.40 | 4396.66 | 4396.53 | 4394.73 | 4396.53 | midpoint | n | Y | F | F |
| 108 | 2026-09-08 11:55 | SELL | MICRO_S | London | 4402.57 | 4403.32 | 4402.94 | 4399.79 | 4402.94 | midpoint | n | Y | F | F |
| 109 | 2026-09-09 02:30 | SELL | MICRO_S | Asian | 4372.94 | 4373.13 | 4373.03 | 4371.77 | 4373.03 | midpoint | n | Y | F | F |
| 110 | 2026-09-09 12:10 | SELL | MICRO_S | London | 4405.79 | 4405.82 | 4405.81 | 4404.16 | 4405.81 | midpoint | n | Y | F | F |
| 111 | 2026-09-11 10:45 | SELL | MICRO_S | London | 4346.67 | 4347.17 | 4346.92 | 4346.65 | 4346.92 | midpoint | n | Y | F | F |
| 112 | 2026-09-11 12:10 | SELL | MICRO_S | London | 4330.00 | 4330.69 | 4330.34 | 4329.43 | 4330.34 | midpoint | n | Y | F | F |
| 113 | 2026-09-14 11:40 | SELL | MICRO_S | London | 4295.03 | 4295.64 | 4295.34 | 4294.81 | 4295.34 | midpoint | n | Y | F | F |
| 114 | 2026-09-14 12:30 | SELL | REGIME_S | London | 4288.04 | 4289.77 | 4288.91 | 4285.84 | 4288.91 | midpoint | n | Y | F | F |
| 115 | 2026-09-15 01:45 | SELL | REGIME_S | Asian | 4299.69 | 4301.56 | 4300.62 | 4297.32 | 4300.62 | midpoint | n | Y | F | F |
| 116 | 2026-09-15 03:45 | SELL | MICRO_S | Asian | 4310.18 | 4310.50 | 4310.34 | 4309.11 | 4310.34 | midpoint | n | Y | F | F |
| 117 | 2026-09-15 07:45 | SELL | MICRO_S | London | 4286.69 | 4290.01 | 4288.35 | 4285.69 | 4288.35 | midpoint | n | Y | F | F |

---

*Read-only diagnostic complete. No strategy change made. Stopping for review.*
