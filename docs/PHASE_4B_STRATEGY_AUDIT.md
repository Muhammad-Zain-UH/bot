# Phase 4B — full strategy audit (READ-ONLY)

**Nothing was changed.** No strategy code, no parameter, no test modified to
pass, no baseline created or altered. `baseline_004` is untouched. Phase 4A
remains frozen at `8a4e010`. RR, `tp_ratio` and `valid_rr` were not touched and
no pending order was manufactured.

**Evidence base:** the real XAUUSD Phase 3A dataset (`433b7e27…`, 15,735
decisions) and the committed Phase 3A/4A diagnostics. Nothing here required a
new replay.

## Evidence classes — kept separate throughout

| Class | Meaning |
|---|---|
| **Documented intent** | What a design doc, docstring or code comment claims |
| **Actual implementation** | What the code does when read |
| **Measured behaviour** | What the real dataset produced |
| **Unresolved interpretation** | Intent that the repository does not record |

---

# A. Executive summary — the actual decision architecture

The system presents as an eight-layer confluence funnel. **Measured, it is a
seven-gate filter followed by a two-input price constructor.**

Of everything L1–L7 compute, only **two values** reach the entry decision:

1. **`side`** — from L1 bias, possibly flipped by L2's BOS check;
2. **`sweep_wick_low` / `sweep_wick_high`** — from L5, used as the stop anchor.

Everything else is a **pass/fail gate**. L3's pullback quality, L4's TP pool,
L6's POI score and bounds, L7's confidence score, grade, Fibonacci confluence
and RSI are computed, stored, logged — and **never influence the entry price,
the stop, the target or the trigger**. The entry price comes from the M5/M1
bars and the FVG; the stop comes from the L5 sweep wick; the target is the stop
distance multiplied by a regime constant.

So the strategy's "confluence" is real as *admission control* and absent as
*construction*. A setup that scrapes through L6 at 60 and one that passes at 95
produce an identical order.

**The binding constraint is now the RR tautology.** Phase 4A removed
`price_in_fvg` from the momentum trigger; four decisions then satisfied the
four-way AND, all MICRO_SCALP, and all four were rejected by `valid_rr` — a test
of `rr >= 2.0` where `rr` equals `tp_ratio` by construction. Zero trades on
15,735 decisions.

---

# B. Component audit table

Line references are to the current working tree at `8a4e010`.

## L1 — Bias

| # | Component | File:line | Class |
|---|---|---|---|
| 1 | `get_h4_bias` / `get_fast_bias` regime switch | `main_production.py:699-707` | **CORRECT** |
| 2 | Daily-midpoint bias confirmation | `bias_engine.py:154-174` | **CORRECT** |
| 3 | `h4_confluence` | `main_production.py:702-703` | **DEAD** |
| 4 | `h4_bias_reference` | `main_production.py:704, 708` | **DEAD** |

**1.** *Implementation:* MICRO_SCALP and REGIME_SCALP gate on H1 fast bias;
INTRADAY_SWING and DEAD_CALM on H4. *Documented:* a code comment (FIX BIAS-2)
explains exactly this. *Agree:* yes. *Depends on:* `detect_regime` (L0).
*Reachable:* yes — **measured 2,392 blocks (15.20%)**, split 1,679 H4-NEUTRAL /
713 H1-fast-NEUTRAL. *Affects entry:* yes, it sets `side`, one of only two
values reaching L8.

**2.** *Implementation:* forces NEUTRAL when both the daily midpoint and the
two-candle close contradict the EMA bias. *Documented:* module docstring.
*Agree:* yes. *Reachable:* yes, visible in measured L1 block reasons.

**3–4.** *Implementation:* computed, written to `analysis`, and **never read by
any code path** (repo-wide grep: written at 702–708, zero readers). *Documented:*
the comment says H4 bias is "kept as a confluence signal for … future confidence
weighting". *Agree:* the comment is candid that it is not yet used. *Affects
entry:* **no** — the confidence engine never receives it.

## L2 — Structure

| # | Component | File:line | Class |
|---|---|---|---|
| 5 | `get_h1_structure` gate | `main_production.py:727-786` | **CORRECT** |
| 6 | H1-ATR "dead calm" gate | `main_production.py:733-739` | **INCORRECT** + **UNREACHABLE** |
| 7 | BOS flip | `main_production.py:740-781` | **CORRECT** (see caveat) |
| 8 | `structure_valid` → L7 | `main_production.py:948` | **CORRECT** |

**5.** *Reachable:* yes but barely selective — **measured 7 blocks of 13,343
(0.05%)**.

**6.** *Implementation:* `if h1_atr_val < 8.0` blocks with the message
"(… < 8.0 pips)". *Actual units:* `h1_atr` is in quote currency — **$8.00**, not
8 pips (PHASE_2_ISSUES **U9**). *Documented:* the message claims pips. *Agree:*
**no.** *Measured:* fired **0 times in 15,735 decisions** — at gold near $4,000
an $8.00 floor is ~0.2% of price and is always cleared. *Affects entry:* not on
this dataset. *Note:* the same gate causes both pre-existing
`test_layer_gate_logic` failures, which mock `calculate_indicators` to `{}` so
it reads `0.0 < 8.0`.

**7.** *Implementation:* on `BROKEN` structure, if price closed beyond the last
swing against the bias **and** the opposite direction shows valid structure, it
flips `side` and continues. *Documented:* an extensive comment (FIX
STRUCTURE-2). *Agree:* yes. *Affects entry:* **yes — it can invert the trade
direction after L1 has set it.** *Measured:* the flip logs 8,799
`[L2_STRUCTURE] BOS FLIP` lines across the Phase 3A/4A runs; because those runs
share one log file, **the per-decision rate is not separable and is not claimed
here**. *Caveat:* a direction chosen at L1 and reversed at L2 means the L1 gate
and the final direction can disagree, and nothing downstream re-validates the
original bias.

## L3 — Pullback

| # | Component | File:line | Class |
|---|---|---|---|
| 9 | `get_m15_pullback` + `MIN_PULLBACK_QUALITY = 1.5` | `main_production.py:794-800` | **CORRECT** |
| 10 | `bypass_l3` (MICRO_SCALP) | `main_production.py:793, 803-806` | **CORRECT** |
| 11 | REGIME_SCALP momentum fallback | `main_production.py:807-824` | **CORRECT** but near-**UNREACHABLE** |
| 12 | `candidate_entry_style` | `main_production.py:723, 805, 820, 835` | **DEAD** |
| 13 | `pullback_quality` value | `main_production.py:796` | **DEAD** (beyond the gate) |

**9.** *Measured:* the single largest filter — **5,868 blocks (37.29%)**, of
which 1,731 "No confirmed pullback detected".

**11.** *Measured:* **6 occurrences (0.04%)**. It exists, it fires, and it is
statistically negligible on this dataset.

**12.** *Implementation:* set to `"PULLBACK"`, `"MOMENTUM"` or
`"PULLBACK / MOMENTUM"`, and read **only** by `print_trade_context()` (line 249)
and `_log_same_summary()` (line 324) — both display functions. **L8 ignores it
entirely**: `get_entry_trigger` derives `allowed_styles` from the *regime name*,
not from L3's finding (`entry_engine.py:673-679`). *Affects entry:* **no.**
*Contradiction:* L3 decides the setup is a pullback or a momentum continuation,
and L8 then decides again from the regime, with no reference to L3's answer.

**13.** Only the `>= 1.5` comparison matters; the magnitude never reaches
scoring or sizing.

## L4 — Liquidity

| # | Component | File:line | Class |
|---|---|---|---|
| 14 | `identify_liquidity_pools` / `assess_liquidity_gate` | `main_production.py:840-857` | **CORRECT** |
| 15 | `sweep_pool.level` → L5 | `main_production.py:868` | **CORRECT** |
| 16 | **`tp_pool`** | `main_production.py:845, 863` | **DEAD** |
| 17 | Pool-scoring distance thresholds | `liquidity_engine.py:368-380, 753` | **INCORRECT** (units) |

**14.** *Measured:* **629 blocks (4.00%)**.

**16.** *Implementation:* `tp_pool` is selected, **strictly validated** by
`assess_liquidity_gate` as being on the profitable side of price with
`score >= 60`, stored in `analysis["layer_4"]` — and **never passed to L8**.
`get_entry_trigger` takes no such argument. *Documented:* the name and the
validation both assert it is the take-profit target. *Agree:* **no** — the
target is computed as `risk × tp_ratio` instead. *Measured:* all 117 FVG-positive
L8 decisions had a valid `tp_pool` available and discarded; the RR it implies has
a **median of 0.25**, against the 1.5–3.0 the synthetic target assumes. *Affects
entry:* **no.**

**17.** `if distance <= 2.0`, `> 50 / > 30`, `max_sweep_distance = 60.0` are
commented as pips but compared against price units (U2/U3/U4).

## L5 — Sweep

| # | Component | File:line | Class |
|---|---|---|---|
| 18 | `get_sweep_and_structure` gate | `main_production.py:867-884` | **CORRECT** |
| 19 | `WATCH` state | `main_production.py:875-879` | **CORRECT** |
| 20 | Directional sweep check | `main_production.py:886-897` | **UNREACHABLE** (measured) |
| 21 | **`sweep_wick_low/high` → L8** | `main_production.py:993-994` | **CORRECT** |
| 22 | `detect_sweep` wick/body quality check | `sweep_detector.py:196` | **INCORRECT** (units, U8) |
| 23 | `setup_grade` | `main_production.py:900` | **DEAD** |

**18–19.** *Measured:* **2,441 blocks (15.51%)** plus **1,634 `L5_SWEEP_WAIT`
(10.38%)** — the second-largest filter.

**20.** *Implementation:* rejects a bearish sweep on a BUY and vice versa.
*Measured:* **0 occurrences in 15,735 decisions.** Either the sweep detector
never returns a contradicting type after L4 has already selected a directional
pool, or the combination cannot arise. *Affects entry:* not on this dataset.

**21.** **The only L1–L7 output that reaches L8's price construction.** It is the
stop anchor: `_select_stop_anchor` takes `min(candidates) - buffer` for BUY.

**22.** `sweep_min = max(2.5, atr*0.12)` — 2.5 is commented as pips, compared in
price units, i.e. a **$2.50** minimum sweep (U8).

## L6 — POI

| # | Component | File:line | Class |
|---|---|---|---|
| 24 | `identify_poi` + threshold 60/70 | `main_production.py:908-928` | **CORRECT** but non-selective |
| 25 | `bypass_l6` (MICRO_SCALP) | `main_production.py:909, 921-922` | **CORRECT** |
| 26 | Sweep-conditional threshold | `main_production.py:919` | **AMBIGUOUS** |
| 27 | `best_poi` bounds → entry price | — | **DEAD** |
| 28 | `_zone_touched` / `fill_percent` | `poi_engine.py:56-73, 322-331` | **CORRECT** (for L6 scoring) |
| 29 | `poi_engine.detect_fvg` | `poi_engine.py:273-370` | **AMBIGUOUS** |

**24.** *Measured:* **1 block of 1,024 evaluated (0.10%)**, against 1,740
bypasses. As a filter it is effectively inert; 63% of L6 "passes" are bypasses.

**26.** The threshold drops from 70 to 60 when a sweep is confirmed. *Documented:*
nowhere. *Unresolved:* why a confirmed sweep should lower the POI bar by exactly
10 points. Phase 2A.1 observed a setup scoring 68 passing or failing purely on
this.

**27.** *Implementation:* `best_poi["top"]` / `["bottom"]` reach only
`evaluate_poi_fib_confluence` and the L7 score. **The entry price is never
placed at the POI.** *Documented:* the module docstring calls POIs "entry
zones". *Agree:* **no.**

**29.** A second, independent FVG detector: M15, adjacent-pair (2-candle) gaps,
`>= 3` minimum, with fill and touch tracking — none of which matches
`entry_engine.detect_fvg` (M5, 3-candle, no minimum, no fill concept), and with
**opposite polarity** (untested scores +30 here; L8 required price *inside*).

## L7 — Confidence

| # | Component | File:line | Class |
|---|---|---|---|
| 30 | `calculate_confidence_score` → gate | `confidence_engine.py:256-263` | **CORRECT** |
| 31 | Threshold 55 (MICRO_SCALP) / 70, raised to 75 on momentum fallback | `main_production.py:958-961` | **CORRECT** |
| 32 | `has_fib_confluence` | `confidence_engine.py:265-273` | **DEAD** |
| 33 | `rsi_value` | `confidence_engine.py:265-273` | **DEAD** |
| 34 | `check_a_plus_checklist` output | `confidence_engine.py:287-291` | **DEAD** |
| 35 | Confidence *magnitude* | — | **DEAD** beyond the threshold |
| 36 | Fibonacci (whole subsystem) | `fibonacci_levels.py` → `confidence_engine.py:62-113` | **DEAD** |

**30–31.** *Measured:* **1,498 blocks (9.52%)**.

**32–33, 36.** *Implementation:* `final_score` is computed by
`calculate_confidence_score(bias_strength, structure_confidence, sweep_quality,
poi_score, session, regime)` — which **does not receive** `has_fib_confluence`
or `rsi_value`. Both go only to `check_a_plus_checklist`, whose result affects
only a `recommendation` **string**. *Documented:* the design docs list Fibonacci
as a POI type and RSI as an L8 momentum input. *Agree:* **no.** *Affects entry:*
**no.** Fibonacci therefore **never constrains an entry** anywhere in the chain.

**34.** `a_plus_checklist` and `qualifies_for_a_plus` have **no consumer** outside
`confidence_engine`.

**35.** The score is a binary gate. A 95 and a 71 are treated identically, and
the grade only decorates the signal record.

## L8 — Entry

| # | Component | File:line | Class |
|---|---|---|---|
| 37 | `core_trigger` four-way AND | `entry_engine.py:613-619` | **CORRECT** (post-4A) |
| 38 | **`valid_rr = rr >= 2.0`** | `entry_engine.py:409` | **INCORRECT** — tautology |
| 39 | TP = `risk_distance × tp_ratio` | `entry_engine.py:403-405` | **INCORRECT** |
| 40 | `_select_stop_anchor` buffer 3.0 | `entry_engine.py:361-371` | **INCORRECT** (units, U1) |
| 41 | ATR stop fallback | `entry_engine.py:398-401` | **CORRECT** |
| 42 | Entry price — momentum (LIMIT_FVG) | `entry_engine.py:579-581` | **CORRECT** (post-4A) |
| 43 | Entry price — pullback (MARKET) | `entry_engine.py:495-497` | **AMBIGUOUS** |
| 44 | `allowed_styles` from regime | `entry_engine.py:673-679` | **AMBIGUOUS** |
| 45 | `price_in_fvg` | `entry_engine.py:585-591` | **DEAD** (post-4A, by decision) |
| 46 | `_score_entry_candidate` | `entry_engine.py:443-449` | **DEAD** in 2 of 4 regimes |
| 47 | `entry_mode` | `entry_engine.py:532, 625` | **CORRECT** (post-4A) |
| 48 | MACD | — | **DEAD** — documented, absent |
| 49 | `choch_level` (M1) | `entry_engine.py:335, 346` | **DEAD** |

**38–39.** The established E9/E10 tautology: TP is derived as
`risk × tp_ratio`, so `rr ≡ tp_ratio` and the gate tests a configuration
constant. *Measured:* proved for every regime and both sides in
`tests/backtest/test_baseline_defects.py`. **Now binding** — Phase 4A's four
four-way-AND candidates were all MICRO_SCALP (`tp_ratio = 1.5`) and all rejected
here. *Affects entry:* **yes, decisively.**

**40.** `buffer_pips = 3.0` subtracted directly from a price → a **$3.00**
buffer. Confirmed in live values: sweep wick 2511.73 → stop 2508.73.

**43.** Pullback uses `m1[-2].close`; momentum used `m1[-1].close` before Phase
4A removed it. *Unresolved:* the two paths disagree on bar index with no recorded
reason.

**44.** `allowed_styles` is decided by regime name alone, overriding L3's
finding (#12). *Unresolved:* why MICRO_SCALP may only take MOMENTUM and
INTRADAY_SWING only PULLBACK.

**46.** Candidate scoring only matters when both styles are allowed —
REGIME_SCALP and DEAD_CALM. In MICRO_SCALP and INTRADAY_SWING there is one
candidate and the score is discarded.

**48.** *Documented:* `FLOW_DIAGRAM_WITH_FLAWS.md:144` and
`SYSTEM_STRUCTURE_DIAGRAM.md:361` both list **MACD** as an L8 momentum input.
*Implementation:* **zero references to MACD anywhere in the repository.**
*Agree:* **no.**

## Cross-cutting

| # | Component | File:line | Class |
|---|---|---|---|
| 50 | `KILL_ZONES_UTC = ((8,10),(12,14))` | `entry_engine.py:16` | **CORRECT** |
| 51 | Kill zone applied at formation only | `entry_engine.py:574, 614` | **AMBIGUOUS** |
| 52 | `"LondonNewYork"` | `entry_engine.py:75`, `config.py:125`, `main_production.py:442` | **UNREACHABLE** |
| 53 | DEAD-session L0 gate | `main_production.py:510-514` | **DEAD** in the decision path |
| 54 | `get_current_session` vs documented DEAD window | `risk_manager.py` vs `main_production.py:512` | **INCORRECT** (disagree) |
| 55 | Regime ATR bands (absolute USD) | `entry_engine.py:75-112` | **INCORRECT** (units, U10) |
| 56 | Layers 9–10 (`trade_manager`, `feedback_loop`) | imported `main_production.py:77-78` | **DEAD** |
| 57 | `technical_engine`, `cvd_divergence`, `institutional_patterns`, `intermarket` | — | **DEAD** (outside L1–L8) |
| 58 | `risk_manager` sizing | — | **DEAD** in replay (bypassed by design) |

**52.** `get_current_session` returns only Asian/London/NewYork/Dead/Closed.
*Measured:* proved by enumerating a full week under a frozen clock. *Effect:*
during New York, MICRO_SCALP is admissible only inside a kill zone — **72
MICRO_SCALP decisions in New York against 2,736 in London**.

**53.** *Implementation:* `check_pre_trade_gates` is called **only from
`main()`** (AST-verified), never from `analyze_entry`. *Measured:* all 1,380
Dead-session decisions reached L1. *Consequence:* the session prohibition applies
to the live loop but **not** to the strategy decision path the replay exercises —
signal generation and execution gating are inconsistent.

**54.** The gate message says "no trading between 22:00 and 03:00 UTC";
`get_current_session` returns `Dead` for 21:00–24:00. They disagree.

---

# C. Dependency / data-flow map

```
detect_regime (L0) ─┬─> regime name ──> L1 bias selector (H4 vs H1 fast)
                    ├─> bypass_l3 ────> L3
                    ├─> bypass_l6 ────> L6
                    ├─> tp_ratio ─────> L8  ** the only regime value reaching price **
                    └─> poi_threshold, risk_percent, max_spread  [poi_threshold unused: L6 uses 60/70]

L1 bias ──> side ───────────────────────────────────────────────> L8   *** REACHES ENTRY ***
        └─> bias_strength ──> L7 score
        └─> h4_confluence ──> (nothing)                                  DEAD

L2 structure ──> structure_confidence, structure_valid ──> L7 score
             └─> last_swing_high/low ──> BOS flip ──> side              *** CAN INVERT ENTRY ***
             └─> break_reason ──> logging only

L3 pullback ──> pass/fail only
            └─> pullback_quality ──> (nothing)                          DEAD
            └─> candidate_entry_style ──> display only                  DEAD

L4 liquidity ──> sweep_pool.level ──> L5
             └─> tp_pool ──> assess_liquidity_gate, then discarded      DEAD
             └─> pool scores ──> pass/fail only

L5 sweep ──> sweep_wick_low/high ──────────────────────────────> L8   *** REACHES STOP ***
         └─> sweep_quality ──> L7 score
         └─> sweep_confirmed ──> L6 threshold (70 -> 60)
         └─> setup_grade, choch_level ──> (nothing)                     DEAD

L6 POI ──> best_poi.score ──> L7 score
       └─> best_poi.top/bottom ──> fib confluence ──> A+ checklist      DEAD
       └─> POI bounds ──> (never reach entry price)                     DEAD

L7 confidence ──> final_score ──> threshold gate only
              └─> grade ──> signal record / logging
              └─> fib, RSI ──> A+ checklist ──> recommendation string   DEAD

L8 entry ──> entry_price  = FVG midpoint (momentum) | m1[-2].close (pullback)
         ──> stop_loss    = sweep wick ± 3.0  (from L5)  | ATR fallback
         ──> take_profit  = |entry - stop| × tp_ratio    (from L0)
         ──> valid_rr     = (tp × risk / risk) >= 2.0    TAUTOLOGY
```

**Inputs to the constructed order: `side` (L1/L2), sweep wicks (L5), M5/M1 bars,
`tp_ratio` (L0). Nothing from L3, L4's target, L6 or L7.**

---

# D. Reachability / funnel — measured, 15,735 decisions

| Layer | Reached | Blocked | % blocked |
|---|---|---|---|
| L1 BIAS | 15,735 | 2,392 | 15.20 |
| L2 STRUCTURE | 13,343 | 7 | 0.04 |
| L3 PULLBACK | 13,336 | 5,868 | **37.29** |
| L4 LIQUIDITY | 7,468 | 629 | 4.00 |
| L5 SWEEP | 6,839 | 2,441 + 1,634 WAIT | **25.90** |
| L6 POI | 2,764 | 1 | 0.01 |
| L7 CONFIDENCE | 2,763 | 1,498 | 9.52 |
| L8 ENTRY | 1,265 | 1,265 | 8.04 |

Variant labels actually observed:

| Label | Passed | Blocked |
|---|---|---|
| `L3_PULLBACK` | 2,702 | — |
| `L3_PULLBACK_BYPASSED` | 4,760 | — |
| `L3_PULLBACK_MOMENTUM` | **6** | — |
| `L5_SWEEP_WAIT` | 0 | 1,634 |
| `L5_SWEEP_DIRECTION` | **0** | **0** |
| `L6_POI` | 1,023 | 1 |
| `L6_POI_BYPASSED` | 1,740 | — |

**Signals: 0. Trades: 0. Errors: 0.**

---

# E. Contradictions, tautologies, redundancies

1. **RR tautology (E9/E10).** `rr ≡ tp_ratio`; the gate tests a constant.
2. **`price_in_fvg` was near-disjoint with `fvg_found`** — co-occurred once in
   1,265. Removed from the trigger in Phase 4A.
3. **The POI 50 %-fill rule coincides exactly with a midpoint fill** —
   `bars_to_midpoint == bars_to_half_fill` in 117/117. Importing it into L8
   would invalidate an order on the bar it fills.
4. **L3 decides the entry style and L8 overrides it from the regime** (#12/#44).
5. **L6 calls POIs "entry zones" but no entry is ever placed at one** (#27).
6. **`tp_pool` is validated as the target and then discarded** (#16).
7. **Two incompatible FVG definitions** with opposite polarity (#29).
8. **Session prohibition applies to the live loop but not the decision path**
   (#53), and its window disagrees with `get_current_session` (#54).
9. **`poi_threshold` from `detect_regime` is unused** — L6 uses its own 60/70.
10. **Redundant M1 CHoCH**: it gates L8's trigger *and* previously set the entry
    price; the two roles were never distinguished.

---

# F. Dead and unreachable components

**Dead — computed, never consumed:** `h4_confluence`, `h4_bias_reference`,
`candidate_entry_style`, `pullback_quality` magnitude, `tp_pool`, `setup_grade`,
`choch_level`, POI bounds as an entry input, `has_fib_confluence`, `rsi_value`
in scoring, `a_plus_checklist`, confidence magnitude, `regime.poi_threshold`.

**Dead — documented but absent:** **MACD**.

**Dead — outside the audited path:** `technical_engine`, `cvd_divergence`,
`institutional_patterns`, `intermarket`, Layers 9–10 (`trade_manager`,
`feedback_loop`), `risk_manager` sizing, the whole Fibonacci subsystem.

**Unreachable — measured:** `L5_SWEEP_DIRECTION` (0/15,735), the L2 H1-ATR gate
(0/15,735), `"LondonNewYork"` (structurally).

**Near-unreachable:** REGIME_SCALP momentum fallback (6/15,735).

---

# G. Ambiguous — require a design decision

1. Why a confirmed sweep lowers the POI threshold by exactly 10 (#26).
2. Why regime dictates entry style, overriding L3 (#44).
3. Pullback `m1[-2]` vs momentum `m1[-1]` bar index (#43).
4. Whether the kill zone should bind at fill time as well as formation (#51).
5. Whether the two FVG definitions should be reconciled (#29).
6. Whether `poi_engine.detect_fvg`'s 2-candle adjacency is the intended FVG.

---

# H. Concrete defects — evidenced, LEFT UNFIXED

| ID | Defect | Evidence |
|---|---|---|
| E9/E10 | RR tautology, now the binding gate | proved in tests; 4 candidates rejected |
| U1 | `$3.00` stop buffer where 3 pips intended | 2511.73 → 2508.73 |
| U8 | `$2.50` minimum sweep | `sweep_detector.py:196` |
| U9 | `$8.00` H1-ATR gate labelled pips | 0 firings measured |
| U10 | Regime ATR bands in absolute USD | regime mix is price-level dependent |
| U2/U3/U4 | Liquidity distance thresholds in price units | `liquidity_engine.py` |
| D1 | Broker `contract_size` 100 vs `tick_value` 0.1 — 10× | `broker_metadata.json` |
| D8 | `LondonNewYork` unreachable | full-week enumeration |
| — | MACD documented, absent | repo-wide grep |
| — | DEAD-session window disagreement | 21:00 vs 22:00 |
| — | `tp_pool` validated then discarded | 117/117 |

---

# I. Documented intent vs implementation vs measurement

| Claim | Documented | Implemented | Measured |
|---|---|---|---|
| L8 uses volume, RSI, MACD | yes | volume yes (quality only), RSI no, **MACD absent** | — |
| Confluence scoring drives entry quality | implied | binary gate only | 1,498 blocks; magnitude unused |
| POIs are "entry zones" | yes | never used as entry price | 0 entries at a POI |
| FVG is an unfilled gap ≥3 pips | yes (L6) | L8 uses a different definition with no minimum | two detectors disagree |
| Fibonacci confluence matters | yes | reaches only a dead checklist | 0 effect |
| DEAD session blocks trading | yes | only in `main()` | 1,380 Dead decisions reached L1 |
| Sweep/liquidity gate entries | yes | yes — L4/L5 are real gates | 629 + 4,075 blocks |
| BOS/CHoCH constrain direction | yes | **yes** — BOS flips side; CHoCH gates L5 and L8 | flip logged 8,799× (rate not separable) |

---

# J. Phase 4B correction candidates — LIST ONLY, NOT IMPLEMENTED

Ordered by evidential strength, not by expected benefit. **None is approved and
none should be actioned without a separate decision.**

1. **E9/E10 — the RR tautology.** Now the binding gate. Any correction must
   decide what `rr` should be measured against; the discarded `tp_pool` is the
   obvious candidate, and its measured median RR of 0.25 means a genuine
   `>= 2.0` test would reject ~99% of setups. **The threshold needs
   justification, not just the formula.**
2. **D1 — contract size vs tick value.** Until resolved no currency figure is
   trustworthy and `risk_manager` cannot be re-enabled.
3. **The unit migration (U1, U2, U3, U4, U8, U9, U10)** as one coherent change
   through `core.units`, measured against `baseline_004`.
4. **Decide whether `tp_pool` is the target** (#16) — this is a design decision,
   not a repair.
5. **Reconcile L3's entry style with L8's regime override** (#12/#44).
6. **Make session handling consistent** between decision and execution (#53/#54).
7. **Decide whether POI/Fibonacci should influence price or remain gates** — at
   present they are neither, which is the least defensible state.
8. **Remove or wire the dead outputs** (§F) — each is either a missing feature or
   a misleading artifact.
9. **MACD** — implement or remove from the documentation.
10. **`L5_SWEEP_DIRECTION` and the L2 ATR gate** — establish whether they are
    genuinely unreachable or merely untriggered on 3.5 months.

---

# Test suite

**664 tests, 2 failures, 0 errors** — identical to the counts at `8a4e010`.
**No test was modified for this audit**, and no assertion was invalidated by it,
because nothing was changed.

Both failures are the long-standing pair in `tests/test_layer_gate_logic.py`:
`test_pullback_gate_requires_real_pullback_detection` and
`test_micro_scalp_l7_confidence_uses_55_threshold`. They reproduce at commit
`04a341d` in a clean worktree, predating every phase of this work.

Their cause is component **#6** in the table above, which makes them evidence
rather than noise: both patch `calculate_indicators` to `{}`, so the L2 H1-ATR
gate reads `0.0 < 8.0` and blocks before the layer under test is reached. The
tests were written against an L2 that did not carry a volatility sub-gate. They
are left failing — repairing them means either editing assertions about strategy
gate behaviour or changing the gate, and this phase does neither.

---

*Read-only audit. Nothing changed, nothing repaired, no baseline created. Stopping for approval.*
