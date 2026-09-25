# Phase 6O-E — L1 Direction / Bias Deep Audit

**Audit only. No source changed.** No threshold, no refactor, no strategy
optimisation, no regime/session change. U9-RR is not resolved. `baseline_004`,
`baseline_005` and the R1 fixtures were read, never written.

**Input:** commit `3e8d061` (Phase 6O-D). Statistics come from the **frozen**
`baselines/baseline_005/decisions.jsonl` (15,735 records) and the frozen dataset
`433b7e27…`.

---

# 1. Executive Summary

**The primary question was: what exactly decides BUY vs SELL? The answer is not
"L1".**

> **`side` is produced by an EMA20−EMA50 crossover on a timeframe chosen by the
> regime — and is then reversed in 13.03 % of the decisions that reach L2.**

Six findings.

1. **The regime selects the direction timeframe.** `use_fast_bias = regime_name
   in ("MICRO_SCALP", "REGIME_SCALP")`. MICRO_SCALP and REGIME_SCALP take the
   **H1** fast bias; INTRADAY_SWING and DEAD_CALM take the **H4** bias. Since
   the regime is decided by M5 ATR and session (Phase 6M), **M5 volatility and
   the hour of day indirectly determine which timeframe decides BUY vs SELL.**

2. **The two paths block at wildly different rates.** **MEASURED:** MICRO_SCALP
   **7.05 %**, REGIME_SCALP **5.42 %**, INTRADAY_SWING **32.98 %**, DEAD_CALM
   **46.80 %**. The H4 path rejects **six to nine times** more often. Of the
   2,392 L1 blocks, **1,679 (70.19 %) come from the H4 path**, which serves only
   26.2 % of decisions.

3. **`side` is reversed at L2 in 13.03 % of arrivals — and the reversal never
   fails.** The FIX (STRUCTURE-2) "BOS FLIP" fires when H1 structure is BROKEN
   against the bias. **MEASURED over 1,335 L2 arrivals: 174 BROKEN (13.03 %);
   the flip condition was met in 174 of 174; the opposite direction's structure
   validated in 174 of 174.** Every BROKEN structure was rescued by reversing the
   trade. This is why `L2_STRUCTURE` blocks only **7 decisions in 15,735**.

4. **`_bias_to_side` maps anything not `"BULLISH"` to `"SELL"`** —
   `return "BUY" if str(bias_label).upper() == "BULLISH" else "SELL"`. **Already
   registered**: `tests/core/test_types.py:66` names this defect in its own
   docstring and asserts the canonical `Side.from_bias` *raises* instead. The
   canonical type is used by `backtest/replay_engine.py` and **not by the
   strategy path**.

5. **FIX (BIAS-1) is the dominant H4 rejection.** **MEASURED: the
   double-contradiction rule forces NEUTRAL in 92 of 415 H4-path decisions —
   22.17 %.** The daily-close invalidation flip, by contrast, fired **once in
   415 (0.24 %)**.

6. **A boundary asymmetry favours SELL in both engines.** `abs(d) < threshold →
   NEUTRAL`, `d > threshold → BULLISH`, `else → BEARISH`. At **`d == +threshold`
   exactly** the result is **BEARISH**. `bias_engine.py:146` even comments the
   branch `# ema_distance < -ema_threshold`, which is false there. Measure-zero,
   but the code is not symmetric.

**Outcome symmetry:** **BUY 6,693 (50.16 %), SELL 6,650 (49.84 %)** of the
13,343 decisions passing L1 — the most balanced result of any layer audited.
**But the mix swings violently by month: BUY% = 37.2 (Jun), 46.6 (Jul), 69.8
(Aug), 25.7 (Sep).**

---

# 2. Historical Intent Timeline

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | **`c3cf4df`** | `bias_engine.py` created: `calculate_h4_ema_bias`, `validate_bias_with_daily_close`, `get_h4_bias`, `_find_h4_swings`, `_calculate_ema_threshold`. **H4 EMA crossover is the original and only direction contract** |
| 2026-09-16 | **`4c90b81`** | **+93 lines, −1.** Adds **FIX (BIAS-1)** (double-contradiction → NEUTRAL) and **FIX (BIAS-2)** (`get_fast_bias`, the H1 path) |

**Two commits. Both direction mechanisms that reverse a bias were added later or
elsewhere:**

- `validate_bias_with_daily_close` — original (`c3cf4df`)
- **FIX (STRUCTURE-2) BOS flip** — lives in `main_production`, not `bias_engine`

### 2.1 The earliest documented direction contract

`get_h4_bias`'s docstring (`c3cf4df`, unchanged): *`"bias": "BULLISH | BEARISH |
NEUTRAL"`*, from *"H4 bias determination: EMA-based bias + daily invalidation
check"*.

`calculate_h4_ema_bias` documents **FIX #4**: *"Daily midpoint confirmation …
2-candle close validation"*.

**FIX (BIAS-2)'s docstring is the clearest statement of intent in the
repository** and it is candid: the H4 threshold *"is the wrong tool for
MICRO_SCALP/REGIME_SCALP … a choppy multi-day H4 range (normal, frequent market
behavior) blocked every regime simultaneously"*. **The measured block rates
(§1.2) confirm the diagnosis and show it was fixed only for two of four
regimes.**

**Can the current direction logic be historically justified?** **Partly.** The
EMA-crossover core and the H1/H4 split are documented and reasoned. **The
regime-selects-timeframe coupling is not stated anywhere as a design principle**
— it is a consequence of where the `if` was placed. And **no document mentions
that L2 can reverse the direction L1 chose.**

---

# 3. Complete Side / Direction Call Graph

```
market data (H4, H1, D1 frames cut at T)
  │
  ├── detect_regime(M5, M15, H1)                      ← M5 ATR + session + kill zone
  │     └── regime  ──────────────────────┐
  │                                        │ selects the timeframe
  ├── calculate_indicators(H4) ────────────┤
  │     + closes_2 injected at main_production.py:693
  │                                        │
  │   use_fast_bias = regime ∈ {MICRO_SCALP, REGIME_SCALP}
  │                                        │
  ├── TRUE  → calculate_indicators(H1) → get_fast_bias(H1)      [bias_engine:318]
  │             EMA20−EMA50 vs max(2.0, atr×0.12)
  │             └── _find_h4_swings(H1, 50)            ← 3rd copy of the fractal
  │
  └── FALSE → get_h4_bias(H4, D1)                               [bias_engine:398]
                ├── calculate_h4_ema_bias                        [bias_engine:82]
                │     EMA20−EMA50 vs max(3.0, atr×0.20)
                │     + daily-midpoint check   (−2.0 strength)
                │     + 2-candle close check   (−1.5 strength)
                │     + FIX(BIAS-1): both fail → NEUTRAL         ← 22.17 % of H4 path
                │     └── _find_h4_swings(H4, 50)
                └── validate_bias_with_daily_close               ← FLIP #1, 0.24 %
                      BULLISH ∧ daily_close < swing_low  → BEARISH
                      BEARISH ∧ daily_close > swing_high → BULLISH
  │
  ├── L1 GATE: bias is None or "NEUTRAL" → BLOCK "L1_BIAS"       ← 2,392 (15.20 %)
  │
  ├── side = _bias_to_side(bias)          "BULLISH"→BUY, EVERYTHING ELSE→SELL
  │
  ├── L2: get_h1_structure(H1, bias)
  │     └── if BROKEN → **BOS FLIP**                             ← FLIP #2, 13.03 %
  │           side reversed, struct replaced, pipeline continues
  │
  └── side → L3 expected_bias · L4 side · L5 direction · L6 · L7 · L8
```

| Function | Caller | Affects `side`? | Overwritten later? |
|---|---|---|---|
| `detect_regime` | `analyze_entry` | **Indirectly — selects the timeframe** | No |
| `calculate_indicators` | `analyze_entry` | Yes — supplies EMAs | No |
| `get_h4_bias` | `analyze_entry` | **Yes** (INTRADAY_SWING, DEAD_CALM) | **Yes — by the BOS flip** |
| `calculate_h4_ema_bias` | `get_h4_bias` | Yes | **Yes — by daily invalidation, then the BOS flip** |
| `validate_bias_with_daily_close` | `get_h4_bias` | **Yes — can reverse** | **Yes — by the BOS flip** |
| `get_fast_bias` | `analyze_entry` | **Yes** (MICRO_SCALP, REGIME_SCALP) | **Yes — by the BOS flip** |
| `_find_h4_swings` | both engines | Indirectly — feeds the daily flip | — |
| `_calculate_ema_threshold` | both engines | Yes — sets the NEUTRAL band | — |
| `_bias_to_side` | `analyze_entry` | **Yes — the mapping itself** | **Yes** |
| `get_h1_structure` | `analyze_entry` (L2) | **Yes — the BOS flip** | No — final |
| `h4_bias` when `use_fast_bias` | `analyze_entry` | **No** — only `h4_confluence` | — |

---

# 4. The Exact `side` Contract

```
A. TIMEFRAME SELECTION
   use_fast = regime ∈ {MICRO_SCALP, REGIME_SCALP}

B. THRESHOLD
   fast : T = max(2.0, H1_atr14 × 0.12)     [dollars]
   h4   : T = max(3.0, H4_atr14 × 0.20)     [dollars]

C. EMA DECISION   d = ema_20 − ema_50    (both from ta.ema on the chosen frame)
   |d| <  T          → NEUTRAL
    d  >  T          → BULLISH
   otherwise         → BEARISH            ← includes d == +T exactly

D. H4 PATH ONLY — two confirmations, each −strength, both failing ⇒ NEUTRAL
   midpoint  : BULLISH needs h4_close ≥ (D1[-1].high + D1[-1].low)/2 ; BEARISH mirror
   2-candle  : BULLISH needs both of H4.close.tail(2) > ema_20      ; BEARISH mirror
   FIX(BIAS-1): ¬midpoint ∧ ¬two_candle → NEUTRAL, strength 0

E. H4 PATH ONLY — daily-close invalidation  (FLIP #1)
   BULLISH ∧ D1[-1].close < h4_swing_low  → BEARISH
   BEARISH ∧ D1[-1].close > h4_swing_high → BULLISH

F. L1 GATE
   bias is None ∨ bias == "NEUTRAL" → BLOCK "L1_BIAS"

G. MAPPING
   side = "BUY" if bias.upper() == "BULLISH" else "SELL"

H. L2 BOS FLIP  (FLIP #2)
   get_h1_structure(H1, bias).structure_type == "BROKEN"
   ∧ ( side==SELL ∧ h1_close > last_swing_high  →  BUY
     ∨ side==BUY  ∧ h1_close < last_swing_low   →  SELL )
   ∧ get_h1_structure(H1, flipped).structure_type ∈ {HH/HL, LH/LL}
   ⇒ side reversed
```

**Timeframes contributing to `side`:** **H1** (fast EMAs, structure, BOS flip),
**H4** (EMAs, swings, 2-candle), **D1** (midpoint, invalidation close), and
**M5/M15 indirectly** through the regime. **M1 contributes nothing.**

**No RSI, no candle property, no momentum, and no ATR other than inside the
threshold.**

---

# 5. Side Distribution — 15,735 decisions

| Outcome | Count | Share of all | Share of passing |
|---|---|---|---|
| **BUY** | **6,693** | 42.54 % | **50.16 %** |
| **SELL** | **6,650** | 42.26 % | **49.84 %** |
| **Blocked (no side)** | **2,392** | 15.20 % | — |

## 5.1 By regime (passing L1)

| Regime | BUY | SELL | BUY % |
|---|---|---|---|
| MICRO_SCALP | 2,226 | 2,534 | 46.8 % |
| REGIME_SCALP | 3,154 | 2,986 | 51.4 % |
| INTRADAY_SWING | 689 | 524 | **56.8 %** |
| DEAD_CALM | 624 | 606 | 50.7 % |

## 5.2 By month — the widest variation in the system

| Month | BUY | SELL | BUY % |
|---|---|---|---|
| 2026-06 | 383 | 646 | **37.2 %** |
| 2026-07 | 2,194 | 2,516 | 46.6 % |
| 2026-08 | 3,422 | 1,483 | **69.8 %** |
| 2026-09 | 694 | 2,005 | **25.7 %** |

## 5.3 By session

| Session | BUY | SELL | BUY % |
|---|---|---|---|
| Asian | 2,299 | 2,356 | 49.4 % |
| London | 1,911 | 2,084 | 47.8 % |
| NewYork | 1,971 | 1,732 | 53.2 % |
| Dead | 376 | 394 | 48.8 % |
| Closed | 136 | 84 | 61.8 % |

---

# 6. Explanation of the 2,392 L1 Blocks

**All 2,392 are `bias == "NEUTRAL"`.** There is no other L1 failure mode.

| Bias engine | Blocks | Share |
|---|---|---|
| **H4** (`[BIAS]` reasons) | **1,679** | **70.19 %** |
| **H1 fast** (`[FAST_BIAS]` reasons) | **713** | 29.81 % |

| Regime | Blocked | of | Rate | Engine |
|---|---|---|---|---|
| MICRO_SCALP | 361 | 5,121 | **7.05 %** | fast |
| REGIME_SCALP | 352 | 6,492 | **5.42 %** | fast |
| INTRADAY_SWING | 597 | 1,810 | **32.98 %** | H4 |
| **DEAD_CALM** | **1,082** | 2,312 | **46.80 %** | H4 |

**The block rate is a property of the engine, not the market.** The two H4-path
regimes carry 26.2 % of decisions and 70.2 % of the blocks.

**Two NEUTRAL sources inside the H4 path, measured over 415 sampled H4-path
decisions:**

| Cause | Count | Share of H4 path |
|---|---|---|
| **FIX (BIAS-1) double-contradiction → forced NEUTRAL** | **92** | **22.17 %** |
| EMA distance below threshold | remainder | — |

**By session:** NewYork **1,296** of 2,392 (54.2 %), Asian 385, Dead 334,
London 321, Closed 56. NewYork dominates because it holds most DEAD_CALM
decisions (Phase 6M), and DEAD_CALM runs the strict H4 engine.

---

# 7. BUY/SELL Symmetry

## 7.1 In code — symmetric except in two places

| Element | BULLISH | BEARISH | Mirror? |
|---|---|---|---|
| EMA comparison | `d > T` | `else` | **NO — `d == +T` gives BEARISH** |
| NEUTRAL band | `abs(d) < T` | same | Yes |
| Strength | `min(10, abs(d)/T)` | same | Yes |
| Midpoint check | `close ≥ mid` | `close ≤ mid` | Yes |
| 2-candle check | both `> ema20` | both `< ema20` | Yes |
| FIX(BIAS-1) | shared | shared | Yes |
| Daily invalidation | `close < swing_low` | `close > swing_high` | Yes |
| **Swing fallback (H4)** | `h4_high` else **`ema20 + 20`** | `h4_low` else **`ema50 − 20`** | **NO — different EMAs** |
| **Swing fallback (H1)** | `h1_high` else **`ema20 + 10`** | `h1_low` else **`ema50 − 10`** | **NO — different EMAs** |
| `_bias_to_side` | `== "BULLISH"` | **everything else** | **NO — defaults to SELL** |
| BOS flip | `h1_close > last_high` | `h1_close < last_low` | Yes |
| Fractal scan | `>` all four | `<` all four | Yes |

**Three code asymmetries, all favouring SELL**, all of measure zero or
zero-occurrence under current inputs.

## 7.2 In outcome — the most symmetric layer audited

**BUY 50.16 % / SELL 49.84 %** across 13,343 decisions — a gap of 0.32 points,
against 6.4 at L3 and 4.3 at L5.

## 7.3 Bearing on the unresolved L3/L5 asymmetry

**The side mix is balanced in aggregate but swings from 25.7 % to 69.8 % BUY
across four months (§5.2).** A layer whose pass rate depends on prevailing market
structure will therefore see different BUY and SELL populations even with
perfectly symmetric code.

**This is consistent with a market cause and inconsistent with a code cause in
L1** — but it does **not** establish that it explains L3's or L5's gaps. Testing
that requires holding the month mix fixed, which this phase did not do.
**Still UNRESOLVED.**

---

# 8. Multi-Timeframe Alignment

| TF | Contributes | Closed at decision? | Can it change after the timestamp? |
|---|---|---|---|
| **M1** | **Nothing** | — | — |
| **M5** | Regime → timeframe selection | Yes | No |
| **M15** | Regime only | Yes | No |
| **H1** | Fast EMAs, ATR, swings, structure, BOS flip | Yes | No |
| **H4** | EMAs, ATR, swings, `closes_2` | Yes | No |
| **D1** | Midpoint (`high`,`low`), invalidation (`close`) | Yes | No |

**Every frame is cut by `bar.open_time + duration <= T`, so only completed bars
are visible.** Both bias engines read `calculate_indicators(...)`, which uses
`frame.iloc[-1]` — the newest **closed** bar. **Unlike L3, L1 does not discard
it, so L1 is current.**

**One alignment caveat specific to L1.** Per D3 (and measured in Phase 6M),
**H4 bars open at 01/05/09/13/17/21 UTC and D1 at 21:00 UTC** — broker UTC+3,
preserved rather than re-cut. So:

- the H4 EMAs are computed on bars offset 3 hours from a UTC-aligned H4 grid;
- **the "daily midpoint" and "daily close" are those of a 21:00→21:00 session**,
  not a UTC day.

**This is not a look-ahead** — the bars are closed and the values are fixed. It
is a semantic offset, undocumented at the L1 call sites.

---

# 9. Temporal Audit

**Verdict: no confirmed violation, no latent risk identified — and no test
coverage whatsoever.**

| Question | Answer |
|---|---|
| Future bars? | **No** — Phase 6M measured **0 future-bar violations across 15,735 decisions on six timeframes**; L1's inputs are a subset |
| Future highs/lows? | **No** — `tail(50)` of already-cut H1/H4; `D1.iloc[-1]` is the last closed daily |
| Future indicators? | **No** — `calculate_indicators` reads `frame.iloc[-1]` |
| Forming-bar values? | **No under replay** — the feed materialises only closed bars |
| Future higher-timeframe values? | **No** — H4 and D1 come through the same cut |
| Ambient clock? | **No** — `bias_engine` reads no clock and is correctly absent from `PATCHED_MODULES` |

**Confirmed violations: 0. Latent risks: none identified. Zero-occurrence risks:
none identified.**

**TEST GAP — MEASURED: the string `bias` appears 0 times in
`tests/backtest/test_leakage.py` and 0 times in
`tests/integration/test_integration_leakage.py`.** The per-layer future-mutation
suite covers indicators, structure, liquidity, POI and pullback. **Bias and sweep
are the two layers with no temporal test — and bias decides the direction of
everything downstream.**

---

# 10. Indicator Audit

| Indicator | Source | Formula | Units | Matches docs? |
|---|---|---|---|---|
| **EMA20 / EMA50** | `indicators.py:127-128`, `ta.ema(close, 20/50)` | Standard EMA on close | dollars | **Yes.** L1 reads `ema_20`/`ema_50` **correctly** — unlike `pullback_detector`, which reads `ema20`/`ema50` and always gets `None` (Phase 6O-B L3-D1) |
| **ATR14** | `ta.atr(high, low, close, 14)` | True Wilder ATR | **dollars** | The canonical definition of the four (`core/indicators.py`) |
| **`_calculate_ema_threshold`** | `max(floor, atr_14 × ratio)` | H1 `(2.0, 0.12)`, H4 `(3.0, 0.20)` | **dollars on both sides — consistent** | Undocumented values, but **no unit defect** |
| **RSI** | — | **Not used by L1** | — | — |
| `_find_h4_swings` | 5-bar fractal, `lookback=50` | 2 left + 2 right | dollars | **Third copy** of the algorithm in L1/L3/L5 |

> **L1 is the only layer audited so far with no pip-vs-dollar defect.** Both
> sides of every comparison are price units.

**`bias_strength` after a daily flip is stale.** `get_h4_bias` returns
`ema_result["bias_strength"]` while `bias` comes from `validation["bias"]`, so a
flipped bias carries the **pre-flip** strength. That value feeds L7's `bias`
component. **1 occurrence in 415 sampled (0.24 %).**

---

# 11. Neutral / Block Semantics

| Cause | Frequency | Intentional? | Notes |
|---|---|---|---|
| `abs(d) < threshold` | the remainder of 2,392 | **Yes** — the documented NEUTRAL band | The only cause on the fast path |
| **FIX (BIAS-1) double contradiction** | **22.17 % of the H4 path** | **Yes** — added deliberately at `4c90b81` with a stated rationale | The single largest identified H4 rejection |
| Missing EMA/close | 0 observed | Defensive | `get_fast_bias` returns NEUTRAL |
| Exception | 0 observed | Defensive | Both engines return NEUTRAL |
| `bias is None` | 0 observed | Defensive | Only if `get_*_bias` is not callable |

**Inherited rather than chosen:** **DEAD_CALM's 46.80 % L1 block rate.** DEAD_CALM
is not in `use_fast_bias`, so it inherits the strict H4 engine by falling through
the `if` — the same default-inheritance pattern Phase 6M found for its `tp_ratio`
and Phase 6O-B found for its L3 strictness. **No document says DEAD_CALM should
use H4 conviction.**

**Unreachable branches:** none found in the L1 gate itself.

---

# 12. Downstream Dependency Map

| Consumer | Uses `side` for | Silently assumes BUY/SELL semantics? |
|---|---|---|
| **L2** `get_h1_structure(h1, bias["bias"])` | Which structure pattern counts as intact | **And can reverse it** |
| **L3** `get_m15_pullback(m15, bias["bias"])` | `expected_bias` — which direction is the impulse | Yes — `"BULLISH"`/`"BEARISH"` vocabulary |
| **L4** `identify_liquidity_pools(..., side=side)` | Which side of price the sweep/TP pool sits | Yes |
| **L5** `get_sweep_and_structure(..., direction=side)` | Sweep polarity, CHoCH direction, BOS direction | Yes |
| **L6** `identify_poi(..., direction=side)` | POI polarity | Yes |
| **L7** `get_confidence_engine(...)` | Indirectly, via bias strength and structure | `bias_strength` weighted 0.20–0.25 |
| **L8** `get_entry_trigger(..., direction)` | Displacement, FVG, rejection, CHoCH polarity | Yes |
| **Stop** | `_select_stop_anchor` — wick low for BUY, wick high for SELL | Yes |
| **Target** | `entry ± risk_distance × tp_ratio` | Yes |
| **RR** | Tautological, but the **money** value of R follows the stop | — |
| **Execution** | `Side.from_bias(position_type)` at `replay_engine.py:408` | **The canonical type — which rejects NEUTRAL** |

**Does changing `side` change more than direction? Yes, substantially.** It
changes which structure pattern is "intact" (L2), which impulse L3 measures,
which side of price L4 searches, sweep polarity (L5), POI polarity (L6),
`bias_strength` (L7) and the stop anchor (L8) — hence R, lot size and target.
**The BOS flip therefore rewrites the entire downstream evaluation for 13.03 % of
L2 arrivals**, and it does so *after* L1 recorded a different `analysis["layer_1"]`.

---

# 13. Double-Counting Analysis

| Evidence | Used at | Independent downstream? |
|---|---|---|
| **H1/H4 EMA20−EMA50** | L1 bias **and** L7 `bias_component` (weight 0.20–0.25) **and** L7 `cohesion` (`bias_norm ≥ 70` is one of four `strong_components`) | **No — counted three times inside L7's score** |
| **H1 structure** | L2 gate, **and** L7 `structure_component`, **and** L7 `cohesion` | **No — twice in L7** |
| **5-bar fractal** | `_find_h4_swings` (L1) · `_find_recent_fractal_swing` (L3) · `_find_recent_fractal_level` (L5) | **Three independent copies of one algorithm**, extending Phase 6O-C's finding |
| **H1 swing high/low** | L1 daily invalidation **and** L2 BOS flip **and** L3's `break_reference` | Same price points, three roles |
| **RSI** | Not used by L1 | — |
| **Momentum** | Not used by L1 | — |

**Logical implications — gates partially implied by earlier ones:**

1. **L2's BROKEN block is almost entirely implied away by its own flip.**
   **MEASURED: 174 of 174 BROKEN structures were rescued.** L2 blocked **7 of
   15,735** in the full run. **A gate that rejects 0.04 % is not a filter.**
2. **L1 ⟹ L2 partially.** The bias is an EMA20/EMA50 relationship on H1 or H4;
   `get_h1_structure` evaluates HH/HL vs LH/LL on H1. These are correlated
   descriptions of the same trend, and L1's NEUTRAL band already removes the
   choppy cases most likely to produce BROKEN.
3. **L7 re-scores L1 and L2's own verdicts** rather than adding independent
   evidence, then adds `cohesion` computed from those same components
   (Phase 6O H1).

---

# 14. Test Audit

| Test | Exercises L1? | Assessment |
|---|---|---|
| `tests/test_layer_gate_logic.py` | **No** — `get_h4_bias` is **mocked** to `{"bias": "BULLISH", "bias_strength": 8.0}` | Tests wiring only. **Both of its failing tests never reach L1's logic** |
| `tests/backtest/test_leakage.py` | **No** — `bias` appears **0 times** | **The temporal gap** |
| `tests/integration/test_integration_leakage.py` | **No** — 0 references | — |
| `tests/integration/test_real_strategy_replay.py` | Indirectly, via full replay | No L1 property asserted |
| `tests/backtest/test_clock_patch.py` | Incidental | — |
| **`tests/core/test_types.py:66`** `test_neutral_bias_is_rejected_rather_than_becoming_a_short` | **No** | **Documents the defect it does not fix.** Its docstring reads *"`main_production._bias_to_side` maps anything not BULLISH to SELL."* It asserts the **canonical** `Side.from_bias` raises `DomainInvariantError`. That type is used by `replay_engine`, **not by the strategy path**. **False confidence** — but honestly labelled, so it is a registered divergence rather than a misleading test |

| ID | Gap |
|---|---|
| **L1-T1** | **No test calls `get_fast_bias` or `get_h4_bias` and asserts a bias** |
| **L1-T2** | **No temporal test** — the layer that decides direction has none |
| **L1-T3** | No boundary test at `d == ±threshold` — the asymmetry in §7.1 is unpinned |
| **L1-T4** | **No BEARISH/SELL test** — the only bias in any test is `"BULLISH"` |
| **L1-T5** | No NEUTRAL test, and none for FIX (BIAS-1) |
| **L1-T6** | **Nothing tests the BOS flip** — the mechanism that reverses 13.03 % of directions is entirely untested |
| **L1-T7** | No test that the regime selects the bias timeframe |
| **L1-T8** | No missing-data / indicator-initialisation test |
| **L1-T9** | No test that the three fractal copies agree |
| **L1-T10** | Nothing pins `bias_strength` staleness after a daily flip |

---

# 15. Defects

| ID | Defect | Class | Occurrences | Baseline affected? |
|---|---|---|---|---|
| **L1-D1** | **`_bias_to_side` defaults everything non-BULLISH to SELL** | **IMPLEMENTATION DEFECT** | 0 reachable today (L1 blocks NEUTRAL first) | No — **already registered** by `test_types.py:66` |
| **L1-D2** | **`d == +threshold` → BEARISH**; comment `# ema_distance < -ema_threshold` is false there | **IMPLEMENTATION DEFECT** | measure-zero | No |
| **L1-D3** | **Swing fallback uses `ema20 + n` for the high but `ema50 − n` for the low** (both engines) | **IMPLEMENTATION DEFECT** | 0 observed | No |
| **L1-D4** | **`bias_strength` is stale after a daily flip** — describes the pre-flip bias, feeds L7 | **IMPLEMENTATION DEFECT** | 0.24 % of H4 path | Yes, marginally |
| **L1-D5** | **The BOS flip reverses `side` after `analysis["layer_1"]` is recorded** — the record and the traded direction disagree | **IMPLEMENTATION DEFECT** | **13.03 % of L2 arrivals** | **Yes** |
| **L1-D6** | **L2's BROKEN block is rescued 174/174** — the gate rejects 7 of 15,735 | **INTENT AMBIGUOUS** | Every BROKEN | **Yes** |
| **L1-D7** | **Regime selects the direction timeframe**, documented nowhere as a principle | **INTENT AMBIGUOUS** | Every decision | **Yes** |
| **L1-D8** | **DEAD_CALM inherits the strict H4 engine by falling through an `if`** — 46.80 % blocked | **INTENT AMBIGUOUS** | 1,082 blocks | **Yes** |
| **L1-D9** | **H4/D1 bars are broker-aligned (21:00 UTC)** — "daily midpoint" is a 21→21 session | **INTENT AMBIGUOUS** | Every H4-path decision | Yes |
| **L1-D10** | **Third copy of the 5-bar fractal** (`_find_h4_swings`) | **IMPLEMENTATION DEFECT** | Every decision | No |
| **L1-D11** | **`h4_bias` computed then discarded** when `use_fast_bias`; only `h4_confluence` survives — and **`h4_confluence` has no consumer** | **DEAD** | 73.8 % of decisions | No |
| **L1-D12** | `_calculate_ema_threshold`'s `(2.0, 0.12)` / `(3.0, 0.20)` are undocumented | **INTENT AMBIGUOUS** | Every decision | Yes |

---

# 16. Ambiguities

| ID | Question |
|---|---|
| **A-6OE-1** | Should the direction timeframe be chosen by regime, or fixed? |
| **A-6OE-2** | Should DEAD_CALM and INTRADAY_SWING use the H4 engine, or was FIX (BIAS-2) meant to cover all regimes? |
| **A-6OE-3** | Is a 13 %-of-arrivals direction reversal at L2 a feature or an escape hatch that disabled L2 as a gate? |
| **A-6OE-4** | Should `analysis["layer_1"]` be corrected when the BOS flip fires? |
| **A-6OE-5** | Should the daily midpoint/close use a UTC day rather than the broker's 21→21 session? |
| **A-6OE-6** | Should `bias_strength` be recomputed after a flip? |

---

# 17. Design Decisions

| ID | Decision |
|---|---|
| **D-6OE-1** | **Should L2 be permitted to reverse L1's direction at all?** The central question. It fires on 13.03 % of arrivals, succeeds 100 % of the time, and reduces L2 to a 0.04 % filter. **No document mentions it outside its own code comment.** |
| **D-6OE-2** | Should the bias timeframe follow the regime (A-6OE-1)? |
| **D-6OE-3** | Should FIX (BIAS-2)'s fast path extend to INTRADAY_SWING and DEAD_CALM? |
| **D-6OE-4** | Should `_bias_to_side` reject non-BULLISH/BEARISH input as `Side.from_bias` does? |
| **D-6OE-5** | Should L1, L3 and L5 share one fractal implementation? *(Extends D-6OC-4 to three copies.)* |
| **D-6OE-6** | Should L7 re-score bias and structure, given L1 and L2 already gated on them? |

**None resolved here. None should be resolved by counting how many decisions the
alternative would admit.**

---

# 18. Items Safe to Freeze

**L1's temporal correctness** (§9) — no look-ahead, and L1 reads the newest
closed bar rather than discarding it. · **Unit consistency** — **the only layer
audited with no pip-vs-dollar defect**; both sides of every comparison are price
units. · **EMA naming** — L1 reads `ema_20`/`ema_50` correctly, the case L3 gets
wrong. · **Outcome symmetry** — BUY 50.16 % / SELL 49.84 %, the most balanced
layer. · **The EMA-crossover core and the NEUTRAL band** as implementations of
their documented contract. · **Determinism** — no clock, no randomness.

---

# 19. Items That Must Remain Unresolved

**D-6OE-1 … D-6OE-6** and **A-6OE-1 … A-6OE-6** — above all whether L2 may
reverse L1, which must not be settled by trade count. · **The L3/L5 outcome
asymmetry** — §7.3 narrows it (side is balanced in aggregate, violently
time-varying) but does **not** establish it. · **Every threshold**: `2.0`,
`0.12`, `3.0`, `0.20`, `lookback=50`, `−2.0`, `−1.5`, `closes_2`. ·
**D-6OD-1** (nearest vs strongest), **D-6OC-1** (is a sweep required),
**D-6OB-1** (is a pullback required), **D-6N-1** (regime/session), **U9-RR**,
**U10-B** — all untouched.

---

# 20. Classification Summary

| Class | Count | Items |
|---|---|---|
| **VERIFIED** | **6** | Temporal correctness · unit consistency · EMA naming · outcome symmetry · EMA-crossover contract · determinism |
| **IMPLEMENTATION DEFECT** | **6** | L1-D1, D2, D3, D4, D5, D10 |
| **INTENT AMBIGUOUS** | **5** | L1-D6, D7, D8, D9, D12 |
| **DEAD / NON-PRODUCTION** | **1** | L1-D11 |
| **TEST GAP** | **10** | L1-T1 … L1-T10 |
| **DESIGN DECISION** | **6** | D-6OE-1 … D-6OE-6 |
| **TEMPORAL RISK** | **0** | None identified |
| **UNRESOLVED** | **1** | The L3/L5 outcome asymmetry, narrowed but not closed |

**Total L1 components classified: 35.**

---

# 21. Exact Next Audit Target

> **Audit L2 and L6 together — `structure_engine.get_h1_structure` and
> `poi_engine` — documentation-only. They are the last two unaudited main-path
> layers, and L2 is no longer a small target.**

**Why L2 is now urgent rather than trivial.** It looked negligible at 7 blocks.
This audit shows why: **its BROKEN verdict is overturned 174 times out of 174 by
a flip that reverses the trade direction.** L2 is not a weak gate — it is a
**direction-reversal mechanism wearing a gate's name**, and `get_h1_structure`
is called **twice per flip** with opposite biases, yet has never been read.

**Why L6 belongs with it.** `poi_engine` blocked **1** decision in 15,735, and
`bypass_l6` skips it for MICRO_SCALP entirely. It also holds the **second FVG
definition** (`poi_engine.detect_fvg`, Phase 6O B3) that disagrees with L8's.
It is small, but it completes the map.

After L2/L6 the whole main path is audited. Then: pin L1–L5 behaviour in tests,
**then** decide D-6N-1, **then** U9-RR.

**Do not implement any L1 change, do not refactor the fractal copies, do not
alter a threshold, and do not resolve D-6OE-1 or U9-RR until L2 and L6 are
audited.**

---

# 22. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| Refactoring | **None** |
| Parameters / thresholds | **Untouched** |
| Regime / session architecture | **Untouched** |
| U9-RR | **Not resolved** |
| Baselines and R1 fixtures | **Read only** |
| Cause inferred for outcome asymmetry without evidence | **No** — §7.3 states the limit explicitly |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
