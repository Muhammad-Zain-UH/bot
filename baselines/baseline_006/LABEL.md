# baseline_006

> # PHASE 7 BASELINE — IMMUTABLE
>
> **This baseline is the frozen reference point for Phase 8 research.**

**IMMUTABLE.** Do not overwrite, regenerate or modify any file in this
directory. `write_artifacts` refuses to write into an existing baseline
directory; that guard is the mechanism, this label is the statement of intent.

This file is the only non-generated file here. It was written alongside the
generated artefacts and **no generated artefact was modified.**

**Not a profitability study.** This baseline contains four trades. Four is not a
sample. Nothing here says the strategy is good, bad, profitable or viable, and
no figure below should be read as evidence in any of those directions.

---

## 1. Provenance

| | |
|---|---|
| HEAD SHA | `a1029a9c609b2d6788978d2a701eb9da2dc2d309` |
| Branch | `phase-0-1-foundations` |
| Working tree at replay | **clean** (`git status --porcelain` empty) |
| Strategy entry point | `main_production.analyze_entry` |
| Python | 3.13.7 |
| Platform | Windows-10-10.0.19045-SP0 |
| Created (UTC) | 2026-09-28T12:49:23 |
| Elapsed | 1,835.87 s (8.57 decisions/s) |

### Replay command

Rebuilt from `docs/BASELINE_005_PROVENANCE.md` §8, step for step. The runner is
not committed, consistent with `baseline_004` and `baseline_005`.

```
python <scratchpad>/run_phase7_baseline.py <logdir> <outroot> baseline_006 a1029a9c…
```

It sets `TRADING_BOT_LOG_FILE`, `TRADING_BOT_MAIN_LOG_FILE`, `SIGNAL_LOG_FILE`,
`MAIN_SIGNAL_LOG_FILE` and `LOG_FILE` to a temporary directory **before
importing `main_production`**, calls `assert_logs_are_redirected()`, redirects
stdout to a sink, then calls `backtest.baseline.run_baseline` and
`write_artifacts` **unmodified**:

```python
run_baseline(ds, spec, baseline_id="baseline_006", git_commit=<HEAD>,
             broker_metadata=meta, spread_pips=2.0, spread_is_assumed=True,
             progress_every=0)
```

Every other argument takes its default. The production log record was not
touched.

### Input data

| | |
|---|---|
| Symbol | XAUUSD |
| Dataset SHA-256 | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` |
| Dataset range | 2026-06-02 00:00 → 2026-09-16 12:32 UTC |
| First / last decision | 2026-06-24T17:00 → 2026-09-16T12:35 UTC |
| Driving timeframe | M5 |
| Timeframes | D1, H4, H1, M15, M5, M1 |
| Bar counts | D1 10 · H4 100 · H1 60 · M15 50 · M5 100 · M1 200 |

Same frozen dataset as `baseline_004` and `baseline_005`.

### Fingerprints

```
run_fingerprint       = 476bb3581345c57ad8e303b0d7dc45b27f1821bfe68c240b608e9a59eb468a3e
decisions_fingerprint = a5474afcf41ed0269783a915a08ec87f9ee25ab597bb06037d341491510456de
ledger_fingerprint    = 6d10c00e2fd7abd63418f9b6b98f3d9fa998a68451973721a3617629e19a9208
dataset_sha256        = 433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c
```

**Source / strategy fingerprint.** The repository identifies strategy source by
commit: `strategy_version = a1029a9c609b2d6788978d2a701eb9da2dc2d309`. The
independent behavioural checksums in `tests/fixtures/behavior_fingerprint.json`
at this commit are:

```
regime_session_side = 41c1f31ad68113a5a24467437656d2320fad67ad00f15d46c7b483daa84d70dd
layer_outcome       = 31483740e3dc547416835282e8a925e66bf87a0f6f4fd7eeca7fc5a0829a8b8b
reversal_set        = 28ddba838a42b37ff2878a39739030874a69950f27a650b2605568875930cf3a
full_record         = 1fd5c41ca35b7e22abbafc436d9a57f3e0f4707d1d185b14d5271d3a60079109
```

**Configuration fingerprint.** The repository has no separate config-hash
mechanism; configuration is captured in `manifest.json` (`execution_assumptions`,
`symbol_specification_used`, `bar_counts`) and is reproduced under §5 below.

---

## 2. Decision stream

| | |
|---|---|
| Decisions | **15,735** |
| Strategy errors | **0** |
| ENTRY_SIGNAL | **4** |
| PRE_ENTRY | 15,731 |

### Regime distribution

| Regime | Decisions | % | Signals |
|---|---|---|---|
| MICRO_SCALP | 7,314 | 46.48 | **4** |
| REGIME_SCALP | 6,492 | 41.26 | 0 |
| INTRADAY_SWING | 1,810 | 11.50 | 0 |
| DEAD_CALM | 119 | 0.76 | 0 |

### Session distribution

Not produced by the baseline artefacts. Recorded from
`tests/fixtures/behavior_fingerprint.json` at the same commit:

| Session | Decisions |
|---|---|
| Asian | 5,040 |
| NewYork | 4,999 |
| London | 4,316 |
| Dead | 1,104 |
| Closed | 276 |

Kill zone active: 2,864. Bias timeframe: H1 13,806 · H4 1,929.

### L1–L8 funnel

`reached` counts decisions that passed, were blocked at, or bypassed the layer.
Variant labels (`L5_SWEEP_WAIT`, `L3_PULLBACK_MOMENTUM`, `L6_POI_BYPASSED`) are
folded into their parent layer.

| Layer | Reached | Blocked | Blocked % |
|---|---|---|---|
| L1_BIAS | 15,735 | 1,505 | 9.56 |
| L2_STRUCTURE | 14,230 | 12 | 0.08 |
| L3_PULLBACK | 14,218 | 5,066 | 32.20 |
| L4_LIQUIDITY | 9,152 | 743 | 4.72 |
| L5_SWEEP | 8,409 | 4,996 | 31.75 |
| L6_POI | 3,413 | 1 | 0.01 |
| L7_CONFIDENCE | 3,412 | 1,825 | 11.60 |
| L8_ENTRY | 1,587 | 1,583 | 10.06 |
| **NONE (signal)** | — | **4** | 0.03 |

Blocks + signals = 15,731 + 4 = 15,735.

---

## 3. Signals

Four. All MICRO_SCALP, all MOMENTUM, all bypassing L3 and L6 (the MICRO_SCALP
regime rule), all passing L1, L2, L4, L5, L7, L8.

| # | Decision time (UTC) | Side | Regime | Decision price | Layers passed |
|---|---|---|---|---|---|
| 1 | 2026-07-17T12:40:00Z | SELL | MICRO_SCALP | 3977.75 | L1, L2, L3-bypassed, L4, L5, L6-bypassed, L7, L8 |
| 2 | 2026-08-06T08:00:00Z | BUY | MICRO_SCALP | 4262.66 | same |
| 3 | 2026-08-12T09:25:00Z | BUY | MICRO_SCALP | 4423.52 | same |
| 4 | 2026-08-28T08:45:00Z | SELL | MICRO_SCALP | 4603.47 | same |

**BUY 2 · SELL 2.** Setup type: MOMENTUM 4. Entry style: MOMENTUM 4.

Signal #2 (2026-08-06T08:00) is the candidate U4 rescued: before `7b1c5f1` it
computed `rr = 1.4999999999999196`, below MICRO_SCALP's `rr >= 1.5` by 8e-14.

### Full decision-side distribution

BUY 7,244 · SELL 6,986 · none (L1-blocked) 1,505.

---

## 4. Execution / geometry

Produced by the repository's own simulator. **This is the first baseline with a
non-zero trade count** — `baseline_001`–`005` all contain zero trades.

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

Per-trade geometry is in `trade_ledger.csv` / `trade_ledger.json`. Every trade
reports `strategy_rr_ratio = 1.5`, which is MICRO_SCALP's `tp_ratio` — see §6,
item 3.

Currency and R figures are recorded in `metrics.json`. **They are deliberately
not reproduced here as headline numbers.** With four trades, one of which has an
ambiguous exit, they carry no inferential weight, and repeating them in a label
invites exactly the reading this baseline must not be used for.

---

## 5. Known assumptions

All from `manifest.json`, unchanged from the established procedure:

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
| `live_trading_enabled` | **false** | |

### Symbol specification — changed since baseline_005, deliberately

| Field | baseline_005 | **baseline_006** |
|---|---|---|
| `money_per_price_unit_per_lot` | 10.0 | **100.0** |

This is the committed resolution of **DD11**, not drift.
`docs/BROKER_SYMBOL_SPECIFICATION_EVIDENCE.md` §7 resolved that `contract_size`
governs XAUUSD profit on MetaQuotes-Demo ($100.00 per price unit per lot), on
three independent evidence strands including the terminal's own
`order_calc_profit` at three lot sizes on a real bar from this dataset. It was
implemented in `56f4ada`, after `baseline_005`'s commit `7b702dd`.

`baseline_004` and `baseline_005` recorded 10.0 and contain **zero trades**, so
the earlier value multiplied nothing and neither baseline requires
regeneration. Neither was touched. **`baseline_006` is the first baseline where
this value multiplies anything.**

---

## 6. Known unresolved issues

Recorded, **not fixed**. Nothing in this phase repaired, reinterpreted or
re-litigated any of them. Classification is kept explicit.

| # | Item | Class |
|---|---|---|
| 1 | **L3 `0.786` acceptance-ceiling provenance.** The five ratios were inherited wholesale from `fibonacci_levels.py` as the standard Fibonacci set; the accepted band is exactly `[min, max]` of that set. No repository evidence explains why 78.6% was selected as a ceiling | **Unresolved historical provenance** |
| 2 | **Historical RR numerical minimum unrecoverable.** The design docstring specified 1:3; the code that implemented it used `rr >= 2.0` and called it "Minimum 1:2". Both DOCUMENTED, same file, same commit. The three current gate thresholds have no recovered rationale | **Unresolved historical provenance** |
| 3 | **The surviving RR comparison is mathematically degenerate.** `take_profit = risk_distance × tp_ratio`, so `rr ≡ tp_ratio`. `evaluate_entry_for_regime` therefore compares a regime constant against a constant; the verdict is fixed per regime before any price is read | **Confirmed behaviour** |
| 4 | **DEAD_CALM through the surviving RR branch.** DEAD_CALM has no branch in `evaluate_entry_for_regime` and falls to the default `rr >= 2.0` against a `tp_ratio` of 1.5, so it is structurally unable to enter. 119 decisions, 0 reached L8 | **Unresolved strategy-contract question** |
| 5 | **MICRO_SCALP / REGIME_SCALP exact-equality RR boundaries.** `rr >= 1.5` against `tp_ratio` 1.5, and `rr >= 2.0` against 2.0. Admission turns on floating-point equality. This is what made U4's 8e-14 correction change the signal count 3 → 4 | **Mechanical defect** |
| 6 | **`MIN_PULLBACK_QUALITY = 1.5` is inert.** Reaching the comparison requires `pullback_detected`, which implies `quality >= 4.0`. Fired 0 times in 15,735. Retained for traceability; pinned by `tests/backtest/test_l3_quality_invariant.py` | **Obsolete / residual code** |
| 7 | **`tp_ratio = 3.0` defaults and `.get("tp_ratio", 3.0)` fallbacks** are unreachable — `detect_regime` always supplies the key. Residue of the former `rr_ratio` | **Obsolete / residual code** |
| 8 | **`rr_bonus` in `_score_entry_candidate` is inert for selection.** Both candidates in a decision share the regime `tp_ratio`, so the bonus is identical and cancels in `max()` | **Obsolete / residual code** |
| 9 | **G2 / U10-B — absolute regime bands.** `detect_regime` classifies on absolute-USD M5 ATR bands (2.5 / 4.5 / 7.0), so regime selection on this dataset is a function of gold's price level, not relative volatility | **Unresolved strategy-design decision** |
| 10 | **U9-H1 — H1 ATR gate units.** `main_production` gates on `h1_atr < 8.0` and reports it as "pips"; the value is quote-currency dollars | **Mechanical defect** |
| 11 | **Q6 / U1 — stop buffer units.** `_select_stop_anchor` subtracts `buffer_pips = 3.0` directly from a price, giving a $3.00 buffer | **Mechanical defect** |
| 12 | **Q1/Q2 — reported RR vs realised R.** Risk is priced against an entry the strategy is never filled at, so realised R differs from reported RR on every trade. The reported value cannot be used as an outcome measure | **Confirmed behaviour** |
| 13 | **L3 one M15 bar stale under replay** (L3-D6) | **Mechanical defect** |
| 14 | **L3 momentum-fallback cap compares pips to dollars** — 10× too tight (L3-D7) | **Mechanical defect** |
| 15 | **`bias` / `bias_strength` not reassigned on the L2 flip.** D-6OF-2 models 2/3. `analysis["layer_1"]` and L7's `bias_strength` still carry pre-flip values on 1,845 reversals | **Unresolved strategy-contract question** |
| 16 | **SCALP-1 check-4** unit repair, and whether it should extend to INTRADAY_SWING reversals | **Unresolved strategy-contract question** |
| 17 | **Ambiguous exits.** 1 of 4 trades resolved under the conservative intrabar policy rather than from observed sequence | **Confirmed behaviour** (assumption-dependent) |

`defect_observations.json` in this directory carries the machine-readable
subset the generator produces (E9/E10/Q3, G2/U10, Q1/Q2, Q6, U9-H1).

---

## 7. Immutability

**This baseline is the frozen reference point for Phase 8 research.**

- Future experiments **compare against** this baseline; they do not overwrite it.
- Do **not** regenerate it after a strategy change. A baseline generated after a
  strategy-contract change must receive its own separate identity, as
  `baseline_005` did relative to `baseline_004`.
- Do **not** optimise against it.
- Do **not** modify it because a later experiment produces better-looking
  results.
- `baseline_004` remains frozen and untouched as the original production record.
  `baseline_005` remains frozen as the pre-U4, zero-signal current-path record.

Any performance difference observed later must be compared against the frozen
baselines and **attributed to a specific code or model change**, not asserted.
