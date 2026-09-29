# baseline_007

> # POST-P8-10 HISTORICAL REFERENCE — IMMUTABLE
>
> **This baseline is the frozen reference point for research after P8-10.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. It was written alongside the
generated artefacts and **no generated artefact was modified.**

**`baseline_006` remains immutable and untouched.** It is the historical
evidence for the **pre-P8-10** state and is not superseded, replaced or
deprecated by this baseline. `baseline_004` remains the original production
record; `baseline_005` the pre-U4, zero-signal record.

**Not a profitability study.** This baseline contains four trades. Four is not a
sample. Nothing here says the strategy is good, bad, profitable or viable, and
no figure below should be read as evidence in any of those directions.

---

## 1. Provenance

| | |
|---|---|
| HEAD SHA | `9c295917d3f61fef74445df47b3db6280f4a4a7b` |
| Commit | *fix: normalize regime scalp momentum cap units* (P8-10) |
| Branch | `phase-0-1-foundations` |
| Working tree at replay | **clean** |
| Strategy entry point | `main_production.analyze_entry` |
| Python | 3.13.7 · Windows-10-10.0.19045-SP0 |
| Created (UTC) | 2026-09-29T10:50:10 |
| Elapsed | 1,954.04 s (8.05 decisions/s) |

### Why this baseline exists

P8-10 corrected a unit mismatch in `_check_regime_scalp_momentum` check 4:

```
- max_allowed_pips = 1.2 * m5_atr
+ max_allowed_pips = 1.2 * m5_atr / pip_size
```

That changed **22 decision verdicts** and moved both the `decisions` and `run`
fingerprints, so `baseline_006` no longer describes the current code state. A
baseline generated after a strategy-contract change must receive its own
identity rather than being folded into an existing one — the same rule that gave
`baseline_005` a separate identity from `baseline_004`.

### Replay command

Rebuilt from `docs/BASELINE_005_PROVENANCE.md` §8, step for step, unchanged from
the procedure that produced `baseline_006`. The runner is not committed,
consistent with `baseline_004`, `_005` and `_006`.

All five log paths (`TRADING_BOT_LOG_FILE`, `TRADING_BOT_MAIN_LOG_FILE`,
`SIGNAL_LOG_FILE`, `MAIN_SIGNAL_LOG_FILE`, `LOG_FILE`) redirected to a temporary
directory **before importing `main_production`**, `assert_logs_are_redirected()`
enforced, stdout redirected to a sink, then:

```python
run_baseline(ds, spec, baseline_id="baseline_007", git_commit=<HEAD>,
             broker_metadata=meta, spread_pips=2.0, spread_is_assumed=True,
             progress_every=0)
```

`run_baseline` and `write_artifacts` called **unmodified**; every other argument
at default. The production log record was not touched.

### Input data — identical to baseline_006

| | |
|---|---|
| Symbol | XAUUSD |
| Dataset SHA-256 | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` |
| Dataset range | 2026-06-02 00:00 → 2026-09-16 12:32 UTC |
| Replay range (first/last decision) | 2026-06-24T17:00 → 2026-09-16T12:35 UTC |
| Driving timeframe | M5 |
| Bar counts | D1 10 · H4 100 · H1 60 · M15 50 · M5 100 · M1 200 |

### Fingerprints

```
run_fingerprint       = 83dbdd1b48ee0d23deb2badb4c03e12d6b742d52fd4486dbdf79545cdf029de6
decisions_fingerprint = 879ba77105d87cae0ddd4147ca3cbe9a1ca3ad973ca5fe6813214e94ed3a1f38
ledger_fingerprint    = 6d10c00e2fd7abd63418f9b6b98f3d9fa998a68451973721a3617629e19a9208
dataset_sha256        = 433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c
```

Against `baseline_006`: `dataset_sha256` and `ledger_fingerprint` **identical**
(same data, no trade changed); `decisions_fingerprint` and `run_fingerprint`
**differ**, as P8-10 requires.

**Determinism, verified.** These four values reproduce the independent P8-10
experiment replay **exactly**, across a separate ~32-minute run. The replay is
deterministic on this dataset and code state.

---

## 2. Decision stream

| | |
|---|---|
| Decisions | **15,735** |
| Strategy errors | **0** |
| ENTRY_SIGNAL | **4** |
| PRE_ENTRY | 15,731 |

### Regime distribution — unchanged from baseline_006

| Regime | Decisions | % | Signals |
|---|---|---|---|
| MICRO_SCALP | 7,314 | 46.48 | **4** |
| REGIME_SCALP | 6,492 | 41.26 | 0 |
| INTRADAY_SWING | 1,810 | 11.50 | 0 |
| DEAD_CALM | 119 | 0.76 | 0 |

### L1–L8 funnel, against baseline_006

`reached` counts decisions that passed, were blocked at, or bypassed the layer.
Variant labels (`L5_SWEEP_WAIT`, `L3_PULLBACK_MOMENTUM`, `L6_POI_BYPASSED`) fold
into their parent layer.

| Layer | Reached (b006 → b007) | Blocked (b006 → b007) | Δ blocked |
|---|---|---|---|
| L1_BIAS | 15,735 → 15,735 | 1,505 → 1,505 | — |
| L2_STRUCTURE | 14,230 → 14,230 | 12 → 12 | — |
| **L3_PULLBACK** | 14,218 → 14,218 | 5,066 → **5,044** | **−22** |
| L4_LIQUIDITY | 9,152 → **9,174** | 743 → **748** | **+5** |
| L5_SWEEP | 8,409 → **8,426** | 4,996 → **5,000** | **+4** |
| L6_POI | 3,413 → **3,426** | 1 → **2** | **+1** |
| L7_CONFIDENCE | 3,412 → **3,424** | 1,825 → **1,835** | **+10** |
| L8_ENTRY | 1,587 → **1,589** | 1,583 → **1,585** | **+2** |
| **Signal (NONE)** | — | 4 → **4** | — |

Blocked deltas balance exactly: 5 + 4 + 1 + 10 + 2 = **22**.

---

## 3. Signals — identities unchanged from baseline_006

Four. All MICRO_SCALP, all MOMENTUM, all bypassing L3 and L6. **BUY 2 · SELL 2.**

| # | Decision time (UTC) | Side | Regime | Decision price |
|---|---|---|---|---|
| 1 | 2026-07-17T12:40:00Z | SELL | MICRO_SCALP | 3977.75 |
| 2 | 2026-08-06T08:00:00Z | BUY | MICRO_SCALP | 4262.66 |
| 3 | 2026-08-12T09:25:00Z | BUY | MICRO_SCALP | 4423.52 |
| 4 | 2026-08-28T08:45:00Z | SELL | MICRO_SCALP | 4603.47 |

None of the 22 decisions P8-10 admitted became a signal.

---

## 4. Execution / trade summary — unchanged from baseline_006

| | |
|---|---|
| Orders / trades / completed | 4 / 4 / 4 |
| Rejected orders | 0 |
| Open at end | 0 |
| Outcomes | TARGET_HIT 2 · STOPPED 2 |
| By direction | BUY 2 · SELL 2 |
| By regime / setup | MICRO_SCALP 4 / MOMENTUM 4 |
| Ambiguous exits | **1 of 4 (25%)** |
| Average bars held | 5.5 |

Per-trade geometry is in `trade_ledger.csv` / `trade_ledger.json`, byte-identical
to `baseline_006`. Currency and R figures are in `metrics.json` and are
deliberately **not** reproduced here as headline numbers: with four trades, one
of which has an ambiguous exit, they carry no inferential weight.

---

## 5. What P8-10 changed, recorded for attribution

**22 L3 verdict changes**, all REGIME_SCALP, each moving from blocked at
`L3_PULLBACK` to passed via `L3_PULLBACK_MOMENTUM`. Verified against
`baseline_006`:

- regime changes: **0**
- side changes: **0**
- non-REGIME_SCALP verdict changes: **0**
- L1 / L2 decisions involved: **0**
- signal identities: **unchanged**

Terminal layer of those 22: L4 5 · L5 4 · L6 1 · L7 10 · L8 2 · **signals 0**.

A further **173 decisions differ only in their `reason` text** between the two
baselines, with identical verdict, layer and side: `max_allowed_pips` is
interpolated into check 4's message, so the printed cap now reads in the units
it claims (e.g. `7.8 pip cap` → `77.9 pip cap`). This is why
`decisions_fingerprint` moved on more rows than the 22 — that fingerprint hashes
the strategy's stated reason. **A line-diff that does not separate verdict from
message text will misread the blast radius as 195.**

---

## 6. Test-suite state

**Measured in the P8-10 acceptance task at this exact HEAD, not rerun during
baseline creation:**

```
Ran 1098 tests
FAILED (failures=2)
  test_micro_scalp_l7_confidence_uses_55_threshold
  test_pullback_gate_requires_real_pullback_detection
```

Those two are the long-carried known failures. No new failure. The count rose
from 1,092 to 1,098 because P8-10's acceptance added six behavioural tests in
`tests/backtest/test_p8_10_momentum_cap_units.py`.

---

## 7. Known assumptions

Unchanged from `baseline_006`; all from `manifest.json`.

| Assumption | Value | Note |
|---|---|---|
| Spread | 2.0 pips | **ASSUMED.** No historical spread series exists for this account |
| Slippage | 0.0 | Zero so its effect stays attributable later |
| Commission | 0.0 per lot | Same reason |
| Position size | **fixed 0.01 lots** | `risk_manager` is **not** used; its ~10× contract-size defect (PHASE_2_ISSUES R1) would contaminate every currency figure |
| Entry timing | next bar open | |
| Intrabar policy | conservative | |
| Max open positions | 3 | |
| Spread applied on exit | true | |
| `money_per_price_unit_per_lot` | 100.0 | DD11 resolution; `contract_size` governs XAUUSD profit |
| `live_trading_enabled` | **false** | |

---

## 8. Known unresolved issues

Unchanged from `baseline_006` §6 and `docs/PHASE_8_RESEARCH_LEDGER.md`, which
remains the authoritative register. Nothing in this task repaired,
reinterpreted or re-litigated any of them.

Two are specific to P8-10 and are **explicitly still open** despite the repair:

1. **The historically intended unit is not established.** The code was
   dimensionally inconsistent and the repair reconciles the units; it does
   **not** establish that the author intended pips. Same family as P8-07 and
   P8-08.
2. **Whether the `1.2` multiplier was itself calibrated against the accidentally
   tighter implementation** is unknown. If it was, correcting the units silently
   changed what `1.2` meant. No evidence either way.

`defect_observations.json` in this directory carries the machine-readable subset
the generator produces.

---

## 9. Immutability

**This baseline is the frozen reference point for research after P8-10.**

- Future experiments **compare against** this baseline; they do not overwrite it.
- Do **not** regenerate it after a strategy change. A baseline generated after a
  strategy-contract change receives its own separate identity.
- Do **not** optimise against it.
- Do **not** modify it because a later experiment produces better-looking
  results.
- `baseline_004`, `baseline_005` and `baseline_006` all remain frozen and
  untouched. `baseline_006` is the pre-P8-10 evidence and stays valid as such.

Any performance difference observed later must be compared against the frozen
baselines and **attributed to a specific code or model change**, not asserted.
