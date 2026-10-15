# Phase 6A — Zero-Signal Causal Investigation

**Documentation only.** No production code, test, strategy parameter,
specification, fixture or baseline was modified. `baselines/baseline_004` was
read and not regenerated. Nothing was loosened, tuned or made to produce
signals.

**Starting state:** Phase 6 audit `ee88f84`; Phase 5 code `139518c`.
**Question:** why does `baseline_004` contain 15,735 decisions and zero signals?

## Evidence labels

| Label | Meaning |
|---|---|
| **OBSERVED** | Read directly from repository source |
| **MEASURED** | Produced by running code, or read from a frozen artefact |
| **IMPLEMENTATION DEFECT** | Code does not do what its own names/structure claim |
| **DATA/PROVENANCE ISSUE** | The inputs or their record are inconsistent |
| **STRATEGY DESIGN BEHAVIOR** | Working as designed; zero is the design's answer |
| **CONFIGURATION ISSUE** | A setting, not logic |
| **UNKNOWN** | Not established; **not** guessed |

---

# A. Executive Conclusion

**There is no single cause. There are four, and they are separable.**

The pipeline is not broken and does not fail early. All 15,735 decisions flow
through eight layers; 1,265 (8.04 %) reach L8; **L8 rejects 100 % of them.**
Every elimination is accounted for — the eight per-layer block counts sum to
exactly 15,735.

At L8, `entry_triggered = raw_triggered AND valid_rr`. Measured on **current
code**, over the same dataset:

| Population at L8 | N | % of L8 | What actually blocked it |
|---|---|---|---|
| `raw=False`, `valid_rr=False` | 979 | 77.39 % | Both terms |
| `raw=False`, `valid_rr=True` | 271 | 21.42 % | **`raw_triggered`** |
| `raw=True`, `valid_rr=False` — pullback | 11 | 0.87 % | **Regime style restriction** |
| `raw=True`, `valid_rr=False` — momentum | **4** | **0.32 %** | **`valid_rr`, solely** |
| `raw=True`, `valid_rr=True` | **0** | 0 % | — |

**Three findings change the picture established in Phase 6:**

**1. `baseline_004` does not measure the current decision path.**
`core_trigger` lost its `price_in_fvg` term in Phase 4A Step 4, after the
baseline was generated. Re-running the current code over the byte-identical
dataset turns momentum `raw_triggered` from **0 → 4**. This is case **F** of the
brief's classification and it is **MEASURED**, not suspected.

**2. `valid_rr` is now causally responsible for exactly 4 would-be signals.**
On `baseline_004` it blocked nothing — the previous audit's reading was correct
*for that artefact*. On current code, 4 MICRO_SCALP decisions reach L8 with
`core_trigger = True` and are stopped by `valid_rr` alone. **This is the first
time in this repository's recorded history that `valid_rr` has bound anything.**

**3. The result is still zero signals on current code.** Removing
`price_in_fvg` did not produce entries; it moved the binding term from the FVG
pair to `valid_rr` for 4 decisions, and to regime style restriction for 11.

**"No opportunities" vs "implementation prevented them" — the honest split:**

- **1,250 of 1,265 (98.8 %) is STRATEGY DESIGN BEHAVIOR.** The trigger
  conjunctions require several individually uncommon events to coincide. They
  did not. No defect is needed to explain this and none should be claimed.
- **15 of 1,265 (1.2 %) were prevented by implementation/configuration**, not by
  price action: 4 by the `valid_rr` tautology, 11 by a regime that permits only
  the style that did not fire while discarding the one that did.
- **One genuine IMPLEMENTATION DEFECT exists** in `detect_fvg`/`price_in_fvg`
  (§I.1). At `baseline_004` it made `price_in_fvg` true in 943 cases where no
  FVG existed. It is no longer on the binding path, because the term was
  removed — but the defect itself is still in the code.

**Nothing here is a reason to change the strategy.** §N states what must not move.

---

# B. Exact Baseline Provenance

**MEASURED — provenance is complete and the run is reproducible.**

| Field | Value |
|---|---|
| Baseline | `baselines/baseline_004` |
| Created | 2026-09-17T06:46:47Z |
| Strategy commit | `04a341daa03de2e8f567b4d01f5c572f7084eb1e` |
| Entry point | `main_production.analyze_entry` |
| Symbol / driving TF | XAUUSD / M5 |
| Dataset range | 2026-06-02 → 2026-09-16 |
| Decision range | 2026-06-24T17:00Z → 2026-09-16T12:35Z |
| Broker / server | MetaQuotes Ltd. / MetaQuotes-Demo |
| Volume | 0.01 lots, **FIXED** — `risk_manager` deliberately not used |
| Spread | 2.0 pips, **ASSUMED** |
| Slippage / commission | 0.0 / 0.0 |
| Intrabar policy | conservative |
| `max_open_positions` | 3 |
| `live_trading_enabled` | `false` |
| Elapsed | 1,658 s, 9.49 decisions/s |

**Dataset integrity — MEASURED.** Recomputing `dataset_fingerprint` over
`data/raw` reproduces the recorded hash exactly:

```
recorded  433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c
recomputed 433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c   MATCH
```

All six per-timeframe hashes match individually (D1, H1, H4, M1, M15, M5). The
data on disk is byte-identical to what produced the baseline.

**Commit `04a341d` is in history**, 45 commits behind `HEAD`.

## B.1 The strategy path HAS changed since — DATA/PROVENANCE ISSUE

**OBSERVED.** `git diff 04a341d..HEAD` over every strategy module touches only
two files, and one change is semantic:

```diff
 core_trigger = bool(
     kill_zone
     and displacement.get("displacement_found")
     and fvg.get("fvg_found")
-    and price_in_fvg
     and m1_choch["m1_choch_confirmed"]
 )
```

The commit documents this as deliberate: *"This changes entry prices and
therefore outcomes; it is not a bug fix."* The momentum `raw_triggered`
conjunction went from **5 terms to 4**.

**Consequence.** `baseline_004` measures a **stricter** momentum trigger than
the shipped code. It remains a valid frozen record of the decision path at
`04a341d`, and its decision *funnel* (L1–L7) is unaffected — but it is **not** a
measurement of what the current code does at L8. Everything in §D/§E below is
therefore reported twice: as frozen, and as re-measured.

---

# C. Actual Production Decision Path

**OBSERVED.** One decision, end to end:

```
ReplayFeed (M5 close, point-in-time availability)
  └─ ReplayEngine._decide                             backtest/replay_engine.py:369
      └─ main_production.analyze_entry                main_production.py
          ├─ L1 BIAS          bias_engine
          ├─ L2 STRUCTURE     structure_engine
          ├─ L3 PULLBACK      pullback_detector
          ├─ L4 LIQUIDITY     liquidity_engine
          ├─ L5 SWEEP/CHoCH   sweep_detector.get_sweep_and_structure
          ├─ L6 POI           poi_engine
          ├─ L7 CONFIDENCE    confidence_engine
          └─ L8 ENTRY         entry_engine.get_entry_trigger      :679
                ├─ allowed_styles by regime                        :688-694
                ├─ _evaluate_pullback_entry                        :696
                │     raw_triggered = rejection_found
                │                     AND m1_choch_confirmed       :499
                ├─ _evaluate_momentum_entry                        :701
                │     core_trigger  = kill_zone
                │                     AND displacement_found
                │                     AND fvg_found
                │                     AND m1_choch_confirmed       :616
                ├─ candidates = styles allowed BY REGIME ONLY      :707-711
                └─ entry_triggered = raw AND valid_rr              :535, :638
  └─ if entry_signal:  _place_order                  replay_engine.py:389
      ├─ MARKET     → PaperBroker.submit_market_order
      └─ LIMIT_FVG  → PaperBroker.submit_limit_order (rests)
  └─ broker.fill_pending_orders → TradeAdapter.on_position_opened
  └─ TradeAdapter.manage → broker verbs → record_then_apply → TradeLedger
```

**`entry_signal` is only constructed when `entry.get("entry_triggered")` is
true** (`main_production.py:999`). It never was. Execution therefore received
nothing — this is **not** case D or E of the brief.

## C.1 Regime gating — OBSERVED

| Regime | `tp_ratio` | Allowed styles | `valid_rr` reachable (`rr >= 2.0`) |
|---|---|---|---|
| MICRO_SCALP | 1.5 | **MOMENTUM only** | **No** |
| INTRADAY_SWING | 3.0 | **PULLBACK only** | Yes |
| REGIME_SCALP | 2.0 | both | Yes (exactly at threshold) |
| DEAD_CALM | 1.5 | both | **No** |

This table is the hinge of the whole investigation. MICRO_SCALP — the largest L8
population — permits **only** the style that requires a kill zone.

---

# D. Funnel: Decisions → Candidates → Signals → Trades

**MEASURED** from `baselines/baseline_004/layer_funnel.json`. The eight block
counts sum to exactly 15,735, so no decision is unaccounted for.

| Stage | Reached | % of prior | % of all | Blocked here | % of reached |
|---|---|---|---|---|---|
| L1 BIAS | 15,735 | 100.00 % | 100.00 % | 2,392 | 15.20 % |
| L2 STRUCTURE | 13,343 | 84.80 % | 84.80 % | 7 | 0.05 % |
| L3 PULLBACK | 13,336 | 99.95 % | 84.75 % | 5,868 | 44.00 % |
| L4 LIQUIDITY | 7,468 | 56.00 % | 47.46 % | 629 | 8.42 % |
| L5 SWEEP/CHoCH | 6,839 | 91.58 % | 43.46 % | 4,075 | 59.58 % |
| L6 POI | 2,764 | 40.42 % | 17.57 % | 1 | 0.04 % |
| L7 CONFIDENCE | 2,763 | 99.96 % | 17.56 % | 1,498 | 54.22 % |
| **L8 ENTRY** | **1,265** | 45.78 % | 8.04 % | **1,265** | **100.00 %** |
| Signals | **0** | 0 % | 0 % | — | — |
| Pending orders | **0** | — | — | — | — |
| Fills | **0** | — | — | — | — |
| Trades | **0** | — | — | — | — |

**MEASURED, current code, same dataset:** 15,735 decisions, **1,265** trigger
invocations, **0** signals. The L8 population is identical, so the
`price_in_fvg` removal changed nothing upstream of L8.

---

# E. Gate-by-Gate Rejection Counts

## E.1 Upstream layers — MEASURED, frozen artefact

| Layer | N | Dominant recorded reason |
|---|---|---|
| L1 BIAS | 2,392 | HN bias NEUTRAL (1,679); HN fast bias NEUTRAL / EMAs too close (713) |
| L2 STRUCTURE | 7 | HN structure broken |
| L3 PULLBACK | 5,868 | No confirmed pullback (1,731); five further variants |
| L4 LIQUIDITY | 629 | Sweep/TP/distance did not meet requirements |
| L5 SWEEP | 4,075 | **MN CHoCH not confirmed: 2,441** (1,112 BUY + 1,329 SELL); near-liquidity wait 1,634 |
| L6 POI | 1 | POI score too low |
| L7 CONFIDENCE | 1,498 | Confidence score too low |
| **L8 ENTRY** | **1,265** | **"Entry triggers not all confirmed" — one distinct reason, 1,265/1,265** |

L8 by regime (MEASURED): MICRO_SCALP 972, REGIME_SCALP 217, INTRADAY_SWING 54,
DEAD_CALM 22. By side: BUY 708, SELL 557.

## E.2 Inside L8 — MEASURED, current code

Instrumented read-only replay; `entry_engine.get_entry_trigger` wrapped, its
result returned unmodified. **Run twice; both runs identical.**

```
trigger invocations                1265
setup_type   REJECTED              1250   (neither style raised raw_triggered)
             PULLBACK                11
             MOMENTUM                 4
valid_rr     True                   271
             False                  994
raw=False valid_rr=False            979
raw=False valid_rr=True             271
raw=True  valid_rr=False             15
raw=True  valid_rr=True               0
signals                                0
```

---

# F. `raw_triggered` Investigation

## F.1 Predicates — OBSERVED

```
pullback.raw_triggered = rejection_found AND m1_choch_confirmed          (2 terms)
momentum.core_trigger  = kill_zone AND displacement_found
                         AND fvg_found AND m1_choch_confirmed            (4 terms, was 5)
```

## F.2 At `baseline_004` — MEASURED

From `docs/PHASE_4A_RAW_TRIGGER_PROBE.md`, N = 1,265, self-checked (0
reconstruction mismatches, 0 AND-logic mismatches, byte-identical across two
runs):

| Term | TRUE | % |
|---|---|---|
| `rejection_found` | 172 | 13.60 % |
| `m1_choch_confirmed` | 113 | 8.93 % |
| `kill_zone` | 340 | 26.88 % |
| `displacement_found` | 192 | 15.18 % |
| `fvg_found` | 117 | 9.25 % |
| `price_in_fvg` | 944 | 74.62 % |
| **pullback `raw_triggered`** | **11** | 0.87 % |
| **momentum `raw_triggered`** | **0** | 0.00 % |

The binding constraint was `fvg_found ∧ price_in_fvg`, which **co-occurred once
in 1,265**. All 16 one-term-away cases were missing an FVG term.

## F.3 On current code — MEASURED, this investigation

| | `baseline_004` | current | Δ |
|---|---|---|---|
| Decisions | 15,735 | 15,735 | 0 |
| Reaching L8 | 1,265 | 1,265 | 0 |
| pullback `raw_triggered` | 11 | 11 | 0 |
| **momentum `raw_triggered`** | **0** | **4** | **+4** |
| Total `raw=True` | 11 | 15 | +4 |
| **Signals** | **0** | **0** | **0** |

Removing `price_in_fvg` produced 4 momentum triggers where there had been none.

## F.4 The complete `raw=True` population — MEASURED

All 15, per record. **Every one is MICRO_SCALP with `tp_ratio = 1.5`.**

| # | setup | `pb_raw` | `mo_raw` | `pb_entry_trig` | `mo_entry_trig` | `valid_rr` | `trigger_type` |
|---|---|---|---|---|---|---|---|
| 1,2,3,5,8,9,10,13,14,15 | PULLBACK | True | False | False | False | False | `momentum_outside_killzone` |
| 6 | PULLBACK | True | False | False | False | False | `momentum_wait` |
| **4,7,11,12** | **MOMENTUM** | False | **True** | False | **False** | **False** | **`momentum+fvg+choch`** |

**Reading, and it is measured rather than inferred:**

- **The 11 PULLBACK cases are blocked by regime style restriction.**
  MICRO_SCALP sets `allowed_styles = ["MOMENTUM"]`, so the pullback candidate is
  never placed in `candidates` and cannot be selected — regardless of
  `valid_rr`. The one path that satisfied its conjunction was discarded for
  being the wrong style.
- **The 4 MOMENTUM cases are blocked by `valid_rr` alone.** MICRO_SCALP
  *permits* MOMENTUM, so the candidate **is** evaluated;
  `core_trigger = True`; `entry_triggered = core_trigger AND valid_rr = False`
  **solely because** `tp_ratio 1.5 < 2.0`. Had `valid_rr` been true, these four
  would have become entry signals.

## F.5 Is `raw_triggered` always false? — Classification

**No.** It is true 15 times in 1,265 (1.19 %) on current code. Classification of
why it is rarely true:

| Component | Classification |
|---|---|
| Pullback needs two uncommon, near-independent events to coincide (13.6 % × 8.9 %) | **STRATEGY DESIGN BEHAVIOR** |
| Momentum needs a 4-way conjunction including `kill_zone` | **STRATEGY DESIGN BEHAVIOR** |
| `kill_zone` cannot be true in the Asian session (`KILL_ZONES_UTC = ((8,10),(12,14))`) while MICRO_SCALP permits only MOMENTUM — **689 decisions structurally unenterable** | **CONFIGURATION ISSUE** (structural unreachability) |
| `price_in_fvg` computed from an inverted, non-existent gap | **IMPLEMENTATION DEFECT** — §I.1 |

---

# G. `valid_rr` Investigation

## G.1 The tautology — OBSERVED, confirmed

`entry_engine.py:403-409`: `take_profit = entry ± risk_distance × tp_ratio`,
then `rr = reward_distance / risk_distance`, then `valid_rr = rr >= 2.0`.
Therefore `rr ≡ tp_ratio` and `valid_rr ≡ (tp_ratio >= 2.0)`.

**MEASURED — the tautology holds exactly in the data.** Observed `rr` values,
by regime, across all 1,265 L8 decisions:

| Regime | `tp_ratio` | Distinct observed `rr` | Max deviation from `tp_ratio` |
|---|---|---|---|
| MICRO_SCALP | 1.5 | all 1.5 ± float noise | ~3.6e-13 |
| DEAD_CALM | 1.5 | all 1.5 ± float noise | ~8.0e-14 |
| REGIME_SCALP | 2.0 | 2.0 (216), 2.0000000000000231 (1) | ~2.3e-14 |
| INTRADAY_SWING | 3.0 | 3.0 (52), two at 2.99999999999998 | ~1.9e-14 |

`rr` never deviates from the regime constant by more than floating-point error.
**It measures configuration, not market attainability** — no market quantity
enters it.

## G.2 Reachability and causality — MEASURED

| Question | Answer |
|---|---|
| Candidates reaching `valid_rr` | **1,265** (every L8 decision) |
| Rejected by `valid_rr` (`valid_rr = False`) | **994** (78.58 %) |
| …of which `raw_triggered` was **also** false | **979** — `valid_rr` redundant |
| …of which `raw_triggered` was **true** | **15** |
| …of those 15, blocked by style restriction anyway | **11** |
| **…of those 15, blocked by `valid_rr` ALONE** | **4** |
| Is `valid_rr` reachable on observed candidates? | **Yes** — true on 271 of 1,265 |

**Is `valid_rr` causally responsible for zero signals?**

**On `baseline_004`: no.** Momentum `raw_triggered` was 0/1265 and all 11
pullback successes were discarded by style restriction. Removing `valid_rr`
entirely would have produced **zero** additional signals. *The Phase 6 reading
was correct for that artefact.*

**On current code: partially, and for the first time.** Removing `valid_rr`
would have produced **4** signals — the 4 MICRO_SCALP momentum triggers. It
would **not** have produced the other 1,261. So:

> **`valid_rr` is a sufficient blocker for 4 of 1,265 decisions and explains
> none of the remaining 1,261. It cannot, by itself, explain the zero-signal
> result — but it is no longer true that it blocks nothing.**

**No change to `valid_rr` is proposed here.** §N.

---

# H. First Causal Bottleneck(s)

Against the brief's classification, **multiple causes exist and are separated**:

| Case | Applies? | Evidence |
|---|---|---|
| **A** — zero candidates generated | **No** | 1,265 candidates reach L8 |
| **B** — eliminated by one gate | **Partly** | All 1,265 die at L8, but at L8 *different terms bind different subsets* |
| **C** — reach signal construction, fail another condition | **No** | Signal construction is gated on `entry_triggered`; never entered |
| **D** — signals lost before execution | **No** | Zero signals existed |
| **E** — execution rejects signals | **No** | Execution received nothing |
| **F** — **artefact generated by a different path** | **YES** | §B.1 — `price_in_fvg` removed since; momentum raw 0 → 4 |
| **G** — data/config makes result invalid | **Partly** | Data verified sound (§B). But two structural unreachabilities exist (§F.5, §K.2) |

**Ordered bottlenecks, current code:**

1. **L8 is the sole elimination point.** 100 % of what reaches it is rejected;
   every upstream layer passes some traffic.
2. **`raw_triggered` is the dominant term** — false in 1,250 of 1,265 (98.8 %).
   **STRATEGY DESIGN BEHAVIOR.**
3. **Regime style restriction** discards 11 satisfied pullback triggers.
   **CONFIGURATION ISSUE / STRATEGY DESIGN BEHAVIOR** — not decided here.
4. **`valid_rr`** solely blocks 4. **IMPLEMENTATION DEFECT** in the sense that
   the gate does not measure what its name implies; the *effect* is
   configuration.

---

# I. Implementation Defects

## I.1 `detect_fvg` returns zone bounds while reporting no FVG — IMPLEMENTATION DEFECT

**OBSERVED.** When `gap_valid` is false, `detect_fvg` returns
`{"fvg_found": False, "zone_low": gap_low, "zone_high": gap_high,
"midpoint": None, ...}` — an **inverted** gap where `gap_high < gap_low`. The
caller does not check `fvg_found` before using the bounds, and
`min`/`max`-normalises the inversion into a plausible interval; `midpoint` falls
back to that interval's centre.

**MEASURED consequence at `baseline_004`:** `price_in_fvg` was **true in 943
cases where no FVG existed** (74.55 % of all L8 decisions).

**Current status:** `price_in_fvg` is **no longer a term in `core_trigger`**, so
this is off the binding path. The defect is still in the code and
`price_in_fvg` is still computed and returned as a diagnostic. **Anything that
reads it as evidence price was inside a gap will be wrong.**

## I.2 `valid_rr` does not measure what it is named — IMPLEMENTATION DEFECT

`rr` is constructed from `tp_ratio` and then tested against a constant.
Confirmed to ~1e-13 in the data (§G.1). Recorded in the frozen baseline as
defect E9/E10/Q3. **Not changed.**

## I.3 Not a defect: the L8 funnel

The funnel is exact — block counts sum to the decision total, and the current
re-run reproduces the L8 population (1,265) precisely. **No instrumentation or
accounting error was found.**

---

# J. Data / Provenance Issues

## J.1 `baseline_004` predates a semantic strategy change — DATA/PROVENANCE ISSUE

§B.1. The baseline remains a valid frozen record of `04a341d`; it is **not** a
measurement of current L8 behaviour. Its L1–L7 funnel is unaffected.

## J.2 Broker metadata is internally inconsistent by exactly 10× — DATA/PROVENANCE ISSUE

**MEASURED**, `data/raw/broker_metadata.json`:

```
trade_contract_size 100.0   trade_tick_size 0.01   trade_tick_value 0.1

tick_size x contract_size = 1.0      <- implied tick_value
broker-reported tick_value = 0.1     <- INCONSISTENT, ratio exactly 10
money per $1 move per lot: 10.0 (from tick_value) vs 100.0 (from contract_size)
```

**OBSERVED.** `SymbolSpecification.__post_init__` validates each field for
positivity but **never cross-checks `tick_value ≈ tick_size × contract_size`**,
so the inconsistent spec was accepted silently. `baseline_004` ran with
`money_per_price_unit_per_lot: 10.0`.

**This materially qualifies the Phase 6 sizing finding and is recorded as a
correction.** Phase 6 classified the `risk_manager` 10.0-vs-100.0 discrepancy as
"**A** — a genuine defect", reasoning from `contract_size = 100`. That reasoning
was incomplete: `risk_manager`'s `10.0` **agrees with the broker's own reported
`tick_value`**, and `core/symbols.XAUUSD_2DIGIT`'s `100.0` agrees with
`contract_size`. The broker's export contains both and they disagree.

> **Amended classification:** the disagreement between the two code paths is
> real and unchanged, but **which value is correct cannot be settled from the
> repository alone** — it depends on an unresolved question about the broker's
> metadata. The correct label is **A (genuine defect: two paths disagree)
> compounded by DATA/PROVENANCE ISSUE (the source data is self-contradictory)**.
> Phase 6's confidence that `100.0` is simply right was overstated.

**No figure in `baseline_004` is affected**, because it contains zero trades.

## J.3 `XAUUSD_2DIGIT` is not the production spec — OBSERVED

`core/symbols.py` marks it *"Test/documentation use only"*; the baseline builds
its spec from broker metadata via `spec_from_broker_metadata`. Every fixture and
test uses the reference constant. **The tests and the baseline do not share a
symbol specification.**

---

# K. Strategy-Behavior Findings

**Stated as behaviour, not defect.**

## K.1 The conjunctions are simply rarely satisfied — STRATEGY DESIGN BEHAVIOR

1,250 of 1,265 L8 decisions had **neither** style's `raw_triggered` true. The
pullback path needs two roughly independent events at 13.6 % and 8.9 % to
coincide; momentum needs a 4-way conjunction. Under independence the pullback
joint would be ~1.2 %; 0.87 % was observed. **No defect is required to explain
this, and none should be claimed.** On this dataset, under this design, the
strategy found almost no setups meeting its own definition.

## K.2 Two structural unreachabilities — CONFIGURATION ISSUE

Neither is a market fact; both are consequences of configuration interacting
with regime rules.

**(a) MICRO_SCALP × kill zone — 689 decisions.** `KILL_ZONES_UTC =
((8,10),(12,14))` has **zero overlap with the Asian session** (00–07).
MICRO_SCALP permits only MOMENTUM; MOMENTUM requires `kill_zone`. **MEASURED:**
of 972 MICRO_SCALP L8 decisions, 689 had `kill_zone = False` and **could not
have produced an entry under any price action.**

**(b) `tp_ratio < 2.0` × `valid_rr >= 2.0` — 994 decisions.** MICRO_SCALP and
DEAD_CALM configure `tp_ratio = 1.5` against a threshold of 2.0. Entry is
structurally impossible in those regimes. **MEASURED:** 994 of 1,265 L8
decisions. For 979 it was redundant; for 4 it was the sole binding term.

## K.3 A satisfied trigger discarded for being the wrong style — 11 decisions

**MEASURED.** All 11 pullback successes occurred in MICRO_SCALP, which permits
only MOMENTUM. The candidate that met its full conjunction was never scored.
Whether this is intended is **UNKNOWN** — §L.

---

# L. Unknowns and Blockers

| # | Unknown | Why it matters |
|---|---|---|
| 1 | Is MICRO_SCALP's `MOMENTUM`-only restriction intended, given it discarded all 11 satisfied pullback triggers? | Decides whether K.3 is design or defect |
| 2 | Is `tp_ratio = 1.5` against a 2.0 threshold intended for MICRO_SCALP and DEAD_CALM? | Decides whether K.2(b) is design or configuration error |
| 3 | Which is correct for this broker: `tick_value = 0.1` or `contract_size = 100`? | Blocks the Phase 6 sizing fix (§J.2) |
| 4 | For the 116 decisions with a **real** FVG, why was price outside it? | Not captured by any probe; needed before FVG work |
| 5 | Would a different dataset period produce signals? | Only one 3-month window has ever been measured |
| 6 | Is 15,735 decisions over ~3 months a large enough sample to conclude anything about trigger rarity? | Bears on whether K.1 generalises |
| 7 | Does `LondonNewYork` (D8) ever occur? `get_current_session` never returns it | Affects regime admission; **not investigated, not changed** |

**Blocker for Phase 7:** there is no dataset/configuration combination known to
produce a single trade. Until one exists, historical performance research has
nothing to measure.

---

# M. What Must Be Fixed Before Phase 7

Ordered by what blocks what. **None is implemented here.**

| # | Item | Why it blocks Phase 7 | Kind |
|---|---|---|---|
| M1 | **Decide questions L-1 and L-2** (regime style restriction; `tp_ratio` vs threshold) | Until decided, zero signals cannot be called design or defect, and no research result is interpretable | Decision |
| M2 | **Resolve L-3** (broker `tick_value` vs `contract_size`) | Every money and R figure scales by 10× on the answer | Decision + data |
| M3 | **Add the missing spec cross-check** `tick_value ≈ tick_size × contract_size` | A self-contradictory spec is currently accepted silently | Correctness |
| M4 | **A new canonical baseline on current code** | `baseline_004` no longer measures the shipped L8 path (§B.1) | Evidence |
| M5 | **At least one configuration producing trades** | Otherwise there is nothing to study | Evidence |
| M6 | Partial-exit integration coverage; I7 capacity ownership | Carried from Phase 6 §7 | Correctness |

**M1 and M2 are decisions for review, not engineering tasks.** They are first
because every downstream measurement depends on them.

---

# N. What Must NOT Be Changed Yet

Explicitly preserved by this investigation, and not to be changed on the
strength of it:

- **Candidate generation, entry rules, filters and all parameter values** —
  including `KILL_ZONES_UTC`, the regime `tp_ratio` table, the 2.0 `valid_rr`
  threshold, FVG rules, CHoCH rules and session rules;
- **`valid_rr` itself.** It now demonstrably blocks 4 decisions — that is a
  reason to *decide* about it, not to remove it. Removing it would create 4
  signals and would be a **strategy change**, not a correctness fix;
- **The regime style restriction**, pending L-1;
- **`detect_fvg`**, despite I.1 being a real defect: it is off the binding path,
  and changing it alters `price_in_fvg` for 943 decisions with unknown
  downstream effect;
- **`baselines/baseline_004`** — frozen, not regenerated, not reinterpreted;
- **The canonical trade-management specification** — no contradiction found;
- **Any profitability conclusion.** Zero trades means zero evidence about
  performance. Nothing here says the strategy is or is not viable.

---

# O. Recommended Next Implementation Order

Evidence-first; one causal change per step. **Nothing is implemented here and
no step is approved by this document.**

| Step | Purpose | Kind | Fingerprint impact |
|---|---|---|---|
| **1** | **Review decision on L-1, L-2, L-3** (documentation) | Decision | None |
| **2** | Add the `tick_value` vs `contract_size` cross-check to `SymbolSpecification`, with the current broker file as an explicit known-inconsistent case | Correctness | None on fixtures; **may reject the current broker metadata** — must be measured before committing |
| **3** | Generate a **new canonical baseline** on current code, same dataset, alongside frozen `baseline_004` | Evidence | New artefact; `baseline_004` untouched |
| **4** | Sizing correction, per Phase 6 §8.5, gated on step 1's answer to L-3 | Correctness | Expected none — must be proven |
| **5** | Partial-exit integration fixture (Phase 6 §8.2) | Coverage | None on existing fixtures |
| **6** | Whatever step 1 decides about `valid_rr` / style restriction | **Strategy change** — separate authorisation, its own audit | **Expected: signals appear.** Must be measured against the step-3 baseline |

Step 6 is deliberately last and deliberately flagged. It is the only step that
would change what the strategy does.

---

# P. Diagnostic Integrity

**OBSERVED / MEASURED.** The instrumented replay:

- **wrapped** `entry_engine.get_entry_trigger` and returned the real function's
  result unmodified — no strategy logic reimplemented, no behaviour altered;
- set `TRADING_BOT_LOG_FILE` and the other output paths to the session
  scratchpad **before** importing `main_production`, so the production record
  was not touched;
- wrote exactly one JSON file, into the scratchpad. **No repository file, no
  baseline artefact and no production log was written;**
- reproduced the decision count (15,735) and the L8 population (1,265) of the
  frozen baseline exactly, which cross-validates it against the artefact;
- was **run twice. Both runs produced identical counts** — signals 0, setup_type
  {REJECTED 1250, PULLBACK 11, MOMENTUM 4}, raw×valid_rr {979, 271, 15, 0}.

The diagnostic is **not committed**. It is scratchpad-only, as §7 of the brief
permits, and is fully described here so it can be rebuilt: wrap
`get_entry_trigger`, record `setup_type`, `valid_rr`, `reward_to_risk_ratio` and
each candidate's `raw_triggered`/`entry_triggered`, then replay the M5 driving
timeframe over `data/raw`.
