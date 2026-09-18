# Phase 4B — strategy design review: admission vs construction

**Documentation only.** No code, parameter, threshold, test or baseline changed.
`baseline_004` untouched. RR and its threshold untouched. No optimisation, no ML,
no profitability claim, and no ranking of corrections by expected performance.

**Audit reviewed:** `a862408`. **Execution baseline:** `8a4e010`.

---

# 0. The central finding — re-derived, and corrected

The audit claimed:

> Six layers of analysis produce pass/fail admission gates, while the actual
> order construction is primarily based on side, sweep wick, and regime constants.

I traced this again from the code rather than restating it. **The claim is
substantially correct but was incomplete in one respect and imprecise in
another.**

**Correction 1 — displacement also constructs.** `_evaluate_momentum_entry`
passes `structure_low=displacement.get("origin_low")` and
`structure_high=displacement.get("origin_high")` into the level calculation
(`entry_engine.py:604-605`). `_select_stop_anchor` then takes
`min(sweep_wick_low, displacement_origin_low) - 3.00` for a BUY
(`entry_engine.py:364-367`). So on the momentum path the stop is anchored to
**whichever of the sweep wick or the displacement candle's own low is lower**.
The audit listed displacement only as a trigger term (#37) and did **not** record
its construction role. That was an omission.

The pullback path does **not** pass those arguments (`entry_engine.py:509-514`),
so its stop is the sweep wick alone.

**Correction 2 — the claim needs scoping to L1–L7.** Several construction inputs
(the FVG midpoint, displacement origin, the M5/M1 bars, the ATR fallback) are
computed **inside L8 itself**, and `tp_ratio` comes from **L0** `detect_regime`,
which runs before L1. Calling these "regime constants" was right for `tp_ratio`
but blurred where the rest originate.

**The precise statement the evidence supports:**

> Of the seven analysis layers L1–L7, exactly **two** outputs reach order
> construction: **`side`** (L1, invertible by L2) and the **sweep wicks** (L5).
> Every other construction input originates **inside L8** or from the **L0
> regime**. L3, L4's target, L6 and L7 contribute nothing but admission.

**New finding while verifying:** `calculate_entry_levels` declares
`risk_pct: float = 1.5` and **never reads it** (AST-verified). It is a dead
parameter on the construction function.

---

# 1. What each layer calculates

| Layer | Computes |
|---|---|
| **L0** `detect_regime` | regime name, `m5_atr`, `kill_zone`, `risk_percent`, **`tp_ratio`**, `bypass_l3`, `bypass_l6`, `poi_threshold`, `max_spread_pips`, `spread_acceptable` |
| **L1** bias | `bias` (BULLISH/BEARISH/NEUTRAL), `bias_strength`, EMA distances, daily-midpoint and two-candle confirmations, `full_report` |
| **L2** structure | `structure_type` (HH/HL, LH/LL, BROKEN), `structure_confidence`, `structure_valid`, `last_swing_high/low`, `break_reason` |
| **L3** pullback | `pullback_detected`, `pullback_quality`, retracement %, fib %, volume/RSI descriptors, duration, `reasoning` |
| **L4** liquidity | pool list with scores/tiers, **`sweep_pool`**, **`tp_pool`**, gate state, `sweep_distance`, thresholds |
| **L5** sweep | `sweep_confirmed`, `choch_confirmed`, `sweep_type`, `sweep_quality`, **`sweep_wick_low/high`**, `setup_grade`, `gate_state`, `choch_level` |
| **L6** POI | `best_poi` (type, score, `top`, `bottom`, `untested`, breakdown), full POI list |
| **L7** confidence | `final_score`, `grade`, `confidence_breakdown`, `a_plus_checklist`, `poi_fib` (`has_fib_confluence`, matched levels), `intraday_rsi` |
| **L8** entry | rejection, momentum, M1 CHoCH, displacement, FVG, `kill_zone`, `price_in_fvg`, entry/stop/target, `rr`, `valid_rr`, `entry_triggered`, `entry_mode`, `setup_type`, `trigger_quality` |

# 2. Which outputs are consumed by a later layer

| Output | Consumed by | Role |
|---|---|---|
| `regime name` | L1 (bias selector), L8 (`allowed_styles`), L7 (threshold) | control |
| **`tp_ratio`** (L0) | **L8 construction** | **constructs TP** |
| `bypass_l3` / `bypass_l6` | L3 / L6 | control |
| `m5_atr` (L0) | — (L8 recomputes its own) | — |
| **`bias`** (L1) | **`side` → every later layer and L8** | **constructs direction** |
| `bias_strength` | L7 score | admission |
| `structure_confidence`, `structure_valid` | L7 score | admission |
| `last_swing_high/low` (L2) | BOS flip → **`side`** | **constructs direction** |
| `pullback_detected` (L3) | its own gate only | admission |
| **`sweep_pool.level`** (L4) | L5 | admission chain |
| `tp_pool` (L4) | `assess_liquidity_gate` only, then dropped | admission only |
| **`sweep_wick_low/high`** (L5) | **L8 `_select_stop_anchor`** | **constructs SL** |
| `sweep_confirmed` (L5) | L6 threshold (70→60) | admission |
| `sweep_quality` (L5) | L7 score | admission |
| `best_poi.score` (L6) | L7 score | admission |
| `best_poi.top/bottom` (L6) | `evaluate_poi_fib_confluence` → A+ checklist | **nothing** |
| `final_score` (L7) | its own gate only | admission |

# 3. Computed but never used for construction

**Never read by any code:** `h4_confluence`, `h4_bias_reference`, `choch_level`,
`setup_grade`, `a_plus_checklist` / `qualifies_for_a_plus`, `rejection.wick_size`
/ `body_size` / `wick_ratio` / `close_position`, `risk_pct` (parameter of
`calculate_entry_levels`).

**Read only by display/logging:** `candidate_entry_style`
(`print_trade_context`, `_log_same_summary`), regime `poi_threshold`
(`main_production.py:226` → printed at 243), `conf.grade`, `reasoning` strings.

**Used for admission or scoring only, never construction:** `pullback_quality`,
`bias_strength`, `structure_confidence`, `sweep_quality`, `best_poi.score`,
`final_score`, `has_fib_confluence`, `rsi_value`, `rejection_quality`,
`displacement_quality`, `momentum_confirmed`, `price_in_fvg`, `tp_pool`.

**Three POI thresholds coexist and none of the regime ones is used:** L0 sets
50/60/70 per regime (`entry_engine.py:81-112`); L6 uses its own
`60 if sweep_confirmed else 70` (`main_production.py:919`); and MICRO_SCALP —
whose regime threshold is 50 — bypasses L6 entirely.

# 4. What actually determines each order property

| Property | Determined by | Source layer |
|---|---|---|
| **Direction** | `bias` → `_bias_to_side`, then possibly **inverted** by the L2 BOS flip | **L1 + L2** |
| **Entry price** | pullback: `m5[-2].close`, overridden by `m1[-2].close` on M1 CHoCH · momentum: `m5[-1].close`, overridden by **`fvg.midpoint`** | **L8 internal** |
| **Stop loss** | `min/max(sweep_wick, displacement_origin) ∓ 3.00`; fallback `max(m5_atr × 1.5, 8.0 \| 6.0)` | **L5 + L8 internal** |
| **Take profit** | `risk_distance × tp_ratio` | **L0 only** |
| **Position size** | replay: constant 0.01 · live: `risk_manager` from regime `risk_percent` (unreachable, E1/E2) | **neither** |
| **RR** | `reward/risk` ≡ `tp_ratio` | **L0, tautologically** |

# 5. Complete data flow: candles → order

```
M5/M15/H1/H4/D1 candles
   │
   ├─ L0 detect_regime ──> regime, tp_ratio ──────────────────────────┐
   │                        bypass_l3, bypass_l6, kill_zone           │
   │                                                                  │
   ├─ L1 bias_engine ────> bias ──> side ─────────────────────────┐   │
   │                       bias_strength ──> L7                   │   │
   │                                                              │   │
   ├─ L2 structure_engine > structure_type ──> gate               │   │
   │                       last_swing_h/l ──> BOS flip ──> side ──┤   │
   │                       structure_conf/valid ──> L7            │   │
   │                                                              │   │
   ├─ L3 pullback ───────> detected/quality ──> gate ONLY         │   │
   │                       candidate_entry_style ──> display      │   │
   │                                                              │   │
   ├─ L4 liquidity ──────> sweep_pool.level ──> L5                │   │
   │                       tp_pool ──> gate, then DROPPED          │   │
   │                                                              │   │
   ├─ L5 sweep ──────────> confirmed/choch ──> gate               │   │
   │                       sweep_quality ──> L7                   │   │
   │                       sweep_wick_low/high ───────────────┐   │   │
   │                                                          │   │   │
   ├─ L6 poi ────────────> best_poi.score ──> L7              │   │   │
   │                       top/bottom ──> fib ──> checklist    │   │   │
   │                                        (no consumer)      │   │   │
   ├─ L7 confidence ─────> final_score ──> gate ONLY          │   │   │
   │                       fib, RSI ──> checklist (dead)       │   │   │
   │                                                          │   │   │
   └─ L8 entry_engine                                         │   │   │
        rejection ─────> raw_triggered (pullback)             │   │   │
        m1_choch ──────> raw_triggered + entry px (pullback)  │   │   │
        displacement ──> core_trigger + origin ───────────┐   │   │   │
        fvg ───────────> core_trigger + midpoint ─────┐   │   │   │   │
        kill_zone ─────> core_trigger                 │   │   │   │   │
                                                      v   v   v   v   v
                                   ORDER: entry px ◄──┘   │   │   │   │
                                          stop     ◄──────┴───┘   │   │
                                          direction ◄─────────────┘   │
                                          take profit ◄───────────────┘
                                          RR = tp_ratio  (tautology)
                                          size = constant (replay)
```

---

# 6. Intended construction model — documented evidence only

For each concept: what the repository **states** it should do, versus what it
does. Where no statement exists, **UNRESOLVED** — no intent is invented.

| Concept | Documented intent | Actual role | Agree? |
|---|---|---|---|
| **Direction source** | Design docs place L1 bias as the directional gate | L1 sets it; **L2 can invert it** | **No** — the BOS flip is documented only in a code comment, and nothing re-validates the original bias |
| **Structure / BOS** | `SYSTEM_STRUCTURE_DIAGRAM` L2 = "H1 structure"; the flip is explained in a `main_production.py:740-748` comment | Gate + direction inversion | Partly — flip is coded and commented but absent from the design docs |
| **CHoCH** | Listed as an ICT concept; `sweep_detector` treats it as a structural confirmation | L5: gate. M1 CHoCH at L8: trigger term **and** pullback entry price | **UNRESOLVED** — nothing states whether CHoCH should price an entry or only confirm one |
| **Liquidity** | `FLOW_DIAGRAM` L4 = pools; `tp_pool` named and validated as the target | `sweep_pool` feeds L5; **`tp_pool` is dropped** | **No** |
| **Sweep** | ICT liquidity sweep; L5 gate | Gate **and** the sole L1–L7 construction input (stop anchor) | Partly — its construction role is undocumented |
| **Fibonacci** | `poi_engine` docstring: "0.5 or 0.618 retracement… Scoring: Base 25"; also a POI type | Reaches only `has_fib_confluence` → A+ checklist → **no consumer** | **No** — never constrains an entry |
| **POI** | `poi_engine.py:1`: "Scores **entry zones**" | Score gates L6 and feeds L7; **bounds never price an entry** | **No** |
| **FVG** | L6 doc: "unfilled gaps ≥3 pips"; L8 FVG undocumented | Two incompatible detectors; L8's midpoint **is** the entry price | **No** |
| **Rejection** | `FLOW_DIAGRAM:140`: "wick ≥2× body" | Trigger term (pullback) + quality; **wick/body values discarded** | Partly |
| **Displacement** | Not described in any design doc | `core_trigger` term **and stop anchor** | **UNRESOLVED** — undocumented entirely |
| **Confidence** | Docs imply grading drives risk ("A+ = 1.5% risk") | Binary threshold; grade decorates the record; `risk_percent` comes from the regime, not the grade | **No** |
| **Entry price** | `SYSTEM_STRUCTURE` mentions "Entry mode (MARKET/LIMIT)" only | M5/M1 close or FVG midpoint | **UNRESOLVED** |
| **SL** | No document states how a stop should be placed | Sweep wick / displacement origin ∓ $3.00, or ATR fallback | **UNRESOLVED** |
| **TP** | `tp_pool` named as the target; regime docs give "TP Target: N R" | `risk × tp_ratio` — the pool is ignored | **Contradictory**: the repository documents *both* |
| **RR** | Implied to measure trade quality | Equals `tp_ratio` identically | **No** |
| **Session / kill zone** | `SYSTEM_STRUCTURE`: DEAD blocks trading; kill zones undocumented | L0 gate in `main()` only; kill zone gates L8 momentum at formation | **No** — inconsistent between decision and execution |

---

# 7. E9/E10 — the full RR chain

## 7.1 The chain

```
sweep_wick_low/high (L5)  ─┐
displacement origin (L8)  ─┴─> _select_stop_anchor ──> stop_loss      [±3.00 buffer]
                                   (or ATR fallback: max(atr×1.5, 8|6))
entry_price (M5/M1/FVG midpoint) ──┐
                                   ├─> risk_distance = |entry − stop|
tp_ratio (L0 regime) ──────────────┴─> take_profit = entry ± risk × tp_ratio
                                       reward_distance = |tp − entry| = risk × tp_ratio
                                       rr = reward/risk = tp_ratio          ← TAUTOLOGY
                                       valid_rr = rr >= 2.0
core_trigger ──────────────────────────> entry_triggered = core_trigger AND valid_rr
```

## 7.2 Is RR mathematically tautological?

**Yes, and unconditionally.** `reward_distance` is *defined* as
`risk_distance × tp_ratio`, so `rr = (risk × tp_ratio)/risk = tp_ratio` for every
non-zero risk distance. The only other reachable value is `0`, when
`risk_distance == 0`. `valid_rr` therefore tests a configuration constant and
carries no information about the trade, the market, or any of L1–L7.

**Measured:** proved for all four regimes and both sides in
`tests/backtest/test_baseline_defects.py`; observed `rr` in the real run was
exactly `tp_ratio` on every L8-reaching decision, to floating-point noise.

## 7.3 Where does `tp_pool` come from?

`liquidity_engine.identify_liquidity_pools` builds a pool list, then selects
directionally (`liquidity_engine.py:618-645`): for a BUY, `sweep_pool` is the
best candidate **below** price and `tp_pool` the best **above**. "Best" is
`_rank_directional_pool`, which sorts by `(distance, -score, tier)` and takes the
**minimum** — i.e. **the nearest qualifying pool**, preferring score ≥ 60 and
falling back to the nearest of any score.

`assess_liquidity_gate` then requires `tp_pool` to be on the profitable side with
`score >= 60`. After that it is stored in `analysis["layer_4"]` and never passed
to L8.

## 7.4 Why is the pool-implied median RR ≈ 0.25?

Measured across the allowed candidates of the 117 FVG-positive decisions:

| | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| `risk_distance` (entry → stop) | 1.27 | 8.13 | **10.20** | 13.05 | 43.87 |
| pool reward (entry → `tp_pool`) | 0.00 | 1.28 | **2.53** | 4.49 | 36.78 |

`2.53 / 10.20 ≈ 0.25`. The cause is **structural asymmetry in how the two
distances are chosen**:

- the **target** is the *nearest* pool, by explicit design (`_rank_directional_pool`);
- the **stop** is a *swept extreme* plus a buffer, which is typically far.

One end is minimised, the other is not.

## 7.5 Implementation defect, design, or both?

**Both — and design dominates.** Decomposed:

| Scenario | Median risk | Median RR |
|---|---|---|
| As implemented ($3.00 buffer) | 10.20 | **0.25** |
| With the buffer as 3 pips ($0.30), U1 corrected | 7.20 | **0.34** |

The $3.00 buffer is **29.4%** of median risk, so the unit defect is material —
but correcting it moves the median RR from 0.25 to **0.34**, nowhere near 2.0.

**Conclusion:** the unit defect (U1) is a genuine implementation bug that
inflates risk by ~30%. The remaining gap is a **design consequence**: a
nearest-pool target and a swept-extreme stop cannot produce a high reward-to-risk
ratio, because the design minimises the numerator and not the denominator. **No
threshold change can reconcile that**, which is why the threshold question is
premature.

## 7.6 Is SL/TP construction consistent with the L1–L7 analysis?

**No, in three specific ways.**

1. **The TP ignores the only market-derived target the system computes.** L4
   selects and validates `tp_pool`; L8 replaces it with an arithmetic multiple of
   the stop. The system does locate a liquidity target and then declines to use it.
2. **The stop uses L5's sweep wick but nothing from L2.** `_select_stop_anchor`'s
   parameters are named `structure_low`/`structure_high`, but L2's
   `last_swing_high/low` are never passed; the momentum path supplies the
   **displacement candle's own high/low** instead. The names suggest market
   structure; the values are a single M5 candle.
3. **The risk that sizing would use is never connected.** `risk_pct` is a dead
   parameter here, and `risk_percent` from the regime reaches only a display line
   and the (unreachable) live sizing path.

## 7.7 So what is RR supposed to measure?

**UNRESOLVED.** The repository documents two mutually exclusive answers and
provides no basis for choosing:

- *"TP Target: N R"* in the regime display implies RR is an **input** — a chosen
  multiple, in which case testing it against 2.0 is meaningless and the gate
  should not exist;
- `tp_pool`, named and validated as the target, implies RR is an **output** — a
  measured relationship between a market target and a structural stop, in which
  case the gate is meaningful but the 2.0 threshold is unjustified and, on this
  data, near-unsatisfiable.

**Missing evidence:** no comment, docstring, test or design document states
whether the target is chosen or measured. Until that is decided, any RR change
would be implementing a guess.

---

# 8. Construction vs admission

| Component | Gates admission? | Constructs order? | Output consumed where | Evidence | Status |
|---|---|---|---|---|---|
| **Fibonacci** | No | No | `has_fib_confluence` → A+ checklist → nothing | `confidence_engine.py:265-273` | **DEAD** |
| **Liquidity — `sweep_pool`** | Yes (L4→L5) | No | `sweep_pool.level` → L5 | `main_production.py:868` | Admission only |
| **Liquidity — `tp_pool`** | Yes (L4 gate) | **No** | validated, then dropped | `main_production.py:845,863` | **DEAD as target** |
| **Sweep** | Yes (L5) | **Yes — stop anchor** | `sweep_wick_*` → `_select_stop_anchor` | `entry_engine.py:364-367` | **Both** |
| **BOS** | Yes (L2) | **Yes — direction** | `last_swing_*` → flip → `side` | `main_production.py:756-781` | **Both** |
| **CHoCH (M15, L5)** | Yes | No | `choch_confirmed` → L5 gate | `main_production.py:880` | Admission only |
| **CHoCH (M1, L8)** | Yes | **Yes — pullback entry price** | `m1_choch` → trigger + `m1[-2].close` | `entry_engine.py:496-499` | **Both** |
| **POI** | Yes (L6) | **No** | score → L7; bounds → fib | `main_production.py:923` | Admission only |
| **Confidence** | Yes (L7) | No | `final_score` → threshold | `main_production.py:963` | Admission only |
| **FVG** | Yes (L8 trigger) | **Yes — entry price** | `fvg.midpoint` → entry | `entry_engine.py:580-581` | **Both** |
| **Rejection** | Yes (pullback trigger) | No | `rejection_found` → `raw_triggered` | `entry_engine.py:499` | Admission only |
| **Displacement** | Yes (momentum trigger) | **Yes — stop anchor** | `origin_low/high` → `_select_stop_anchor` | `entry_engine.py:604-605` | **Both** |
| **Volume** | No | No | ratio → quality scores only | `entry_engine.py:194-217` | Score only |
| **RSI** | No | No | → A+ checklist | `confidence_engine.py:232-235` | **DEAD** |
| **MACD** | No | No | absent | repo-wide grep | **DEAD** (documented only) |
| **Kill zone** | Yes (L8 momentum) | No | `kill_zone` → `core_trigger` | `entry_engine.py:614` | Admission only |
| **`tp_ratio`** | **Yes** (via `valid_rr`) | **Yes — TP** | → TP and RR | `entry_engine.py:403-409` | **Both** |

**Answer to the question posed:** of the nine concepts named, **five construct
trade geometry** — sweep (stop), BOS (direction), M1 CHoCH (pullback entry),
FVG (momentum entry), displacement (stop). **Four only reduce the candidate
count** — Fibonacci (not even that), liquidity's target, POI, confidence.

---

# 9. Correction candidates — classified, none implemented

| # | Candidate | Class | Changes | Evidence | Admission / construction | Invalidates `baseline_004`? | New experiment needed? |
|---|---|---|---|---|---|---|---|
| 1 | **E9/E10 RR tautology** | **D — design decision** (not A) | What `rr` measures, and whether the gate exists at all | §7 | **Both** | **Yes** | **Yes** — and §7.7 must be answered first |
| 2 | **D1 contract size vs tick value (10×)** | **A — implementation defect** | Every currency figure | `broker_metadata.json` | Neither (reporting) | No (0 trades) | Yes, once trades exist |
| 3 | **U1 $3.00 stop buffer** | **A** | Stop distance, ~30% of median risk | §7.5 | **Construction** | **Yes** | **Yes** |
| 4 | **U8/U9/U10/U2/U3/U4 unit defects** | **A** | Gate selectivity and regime mix | audit §H | **Admission** | **Yes** | **Yes** |
| 5 | **`tp_pool` discarded** | **D** | TP becomes market-derived | §7.3–7.5 | **Construction** | **Yes** | **Yes** |
| 6 | **L3 style vs L8 regime override** | **C — semantic inconsistency** | Which entry style is taken | §2, audit #12/#44 | Both | Yes | Yes |
| 7 | **Session gate not in decision path** | **C** | Dead-session decisions | `main_production.py:1373` AST | **Admission** | **Yes** | **Yes** |
| 8 | **DEAD window 21:00 vs 22:00 disagreement** | **A** | Session boundary | `risk_manager` vs `:512` | Admission | Yes | Yes |
| 9 | **POI / Fibonacci influence nothing** | **D** | Whether they price entries | §8 | Construction (if changed) | Yes | Yes |
| 10 | **Dead outputs** (`h4_confluence`, `choch_level`, `setup_grade`, `risk_pct`, A+ checklist, `candidate_entry_style`) | **B — dead code** | Nothing, if removed | §3 | Neither | **No** | No |
| 11 | **MACD documented, absent** | **C** | Documentation or code | repo grep | Neither | No | No |
| 12 | **`L5_SWEEP_DIRECTION`, L2 ATR gate unreachable** | **E — unresolved** | Unknown | 0/15,735 | Admission | No | **Yes** — longer history |
| 13 | **Three unused POI thresholds** | **C** | Which threshold applies | §3 | Admission | Yes | Yes |
| 14 | **Stop params named `structure_*` but fed a single candle** | **C** | Naming, or the values | §7.6 | Construction | Yes if values change | Yes |

**Class counts:** A (implementation defect) 4 · B (dead code) 1 · C (semantic
inconsistency) 5 · D (design decision) 3 · E (unresolved) 1.

**Only candidate 10 is safe to action without a new controlled experiment**, and
only because removing genuinely unread values cannot change behaviour — which
would itself need to be demonstrated by byte-identical reproduction of
`baseline_004`, not assumed.

---

# 10. Summary for the decision

The strategy performs **seven layers of admission control and then builds an
order from five inputs**, two of which (`side`, sweep wicks) come from those
layers and three of which (FVG midpoint, displacement origin, `tp_ratio`)
originate at L8 or L0.

The most consequential structural fact is not the RR tautology itself but what
sits behind it: **the system computes a market-derived target and discards it**,
substituting a multiple of the stop, then tests that multiple against a constant.
Correcting the arithmetic without deciding what RR is *for* (§7.7) would replace
a tautology with an arbitrary threshold — and the measurement says a genuine
`>= 2.0` test against the current target selection would reject ~99% of setups.

**That is a design question, and it is unresolved in the repository.**

---

# 11. Verification

**664 tests, 2 failures, 0 errors** — identical to `a862408` and to `8a4e010`.
No test was modified, and nothing in this review could invalidate one, because
nothing was changed.

Both failures are the long-standing `tests/test_layer_gate_logic.py` pair that
reproduces at `04a341d`. They are caused by the L2 H1-ATR gate: both patch
`calculate_indicators` to `{}`, so the gate reads `0.0 < 8.0` and blocks before
the layer under test. Left failing and unmodified.

---

*Design review only. Nothing changed, nothing implemented, no threshold proposed, no ranking by expected performance. Stopping for approval.*
