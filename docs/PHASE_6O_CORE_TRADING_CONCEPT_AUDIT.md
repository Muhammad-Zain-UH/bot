# Phase 6O — Full Core Trading-Concept Audit

**Audit only. No source changed.** No threshold tuned, no parameter optimised,
no regime/session redesign, U9-RR not selected. `baseline_004`, `baseline_005`
and the R1 fixtures untouched. Trade count is used nowhere as evidence that a
concept is correct.

**Input:** commit `6642203` (Phase 6N). Frozen dataset `433b7e27…`, 15,735
decisions.

---

# 0. Audit Depth — read this before the tables

This pass did **not** reach equal depth everywhere, and saying otherwise would
misrepresent the evidence.

| Depth | Modules |
|---|---|
| **Full** — logic read line by line, symmetry and temporality checked | `entry_engine` (regime, FVG, displacement, triggers, admission gate), `risk_manager` (session), `confidence_engine`, `sweep_detector` (CHoCH, fractal, ATR), `main_production` (layer wiring, L0, L7), `core/*`, `backtest/*`, `data/replay_feed` |
| **Interface only** — call sites, inputs/outputs and reachability confirmed; internal logic **not** line-audited | `liquidity_engine`, `poi_engine`, `pullback_detector`, `bias_engine`, `structure_engine`, `sweep_detector.detect_sweep` / `detect_bos` |

**Every concept whose evidence rests only on the second row is marked
`NOT FULLY AUDITED` and is classified `UNRESOLVED`, never `VERIFIED`.** A
concept is not certified correct because this pass did not look at it.

---

# 1. EXECUTIVE SUMMARY

**The engine is temporally sound and largely symmetric. Its problems are
semantic: several named concepts do not implement the thing they are named
after, and a substantial fraction of the scoring apparatus is inert.**

**Five findings that matter most:**

1. **Fibonacci is fully dead in the decision path.** `evaluate_poi_fib_confluence`
   runs on every decision, feeds `has_fib_confluence` into the A+ checklist —
   and **`final_score` contains no Fibonacci term**, while `main_production`
   reads only `final_score` and `grade`. The checklist changes nothing.
   `fibonacci_levels.py` has **zero test files**. *(New.)*

2. **`detect_choch` does not detect a CHoCH.** It confirms when close breaks the
   most recent 5-bar fractal **in the trade direction** — which is a break of
   structure, not a change of character, and it never consults trend. Its own
   docstring is internally inconsistent: bullish uses *Lower High* (reversal
   semantics), bearish uses *Lower Low* (continuation semantics). The
   **implementation is symmetric; the documentation is not.** *(New.)*

3. **The temporal model is clean and now measured.** 0 future-bar violations
   across 15,735 decisions on six timeframes; minimum lag exactly 0 on M1–H4.
   Displacement reads `iloc[-1]`, FVG reads `iloc[-3..-1]`, the fractal scan is
   a causal 5-bar pattern. **No confirmed look-ahead anywhere in this audit.**

4. **Cohesion is not independent evidence.** `cohesion_component` is computed
   entirely from the same four normalised components it is added to — it counts
   how many of them exceed 70 and adds up to 20 % more score for it. The L7
   score double-counts its own inputs. *(New.)*

5. **The L7 threshold is implemented twice**, in `confidence_engine.py:157-160`
   and `main_production.py:959`, with the same `55 / 70` values reached by
   independent code. They cannot be kept in step by the type system. *(New.)*

**Nothing in this audit changes the Phase 6N conclusion.** D-6N-1 — whether
session eligibility belongs inside regime classification — remains the first
decision, and **U9-RR remains blocked behind it**.

---

# 2. COMPLETE CONCEPT INVENTORY

**68 concepts**, grouped as the brief specifies. Classification key: **V**
verified · **D** implementation defect · **A** intent ambiguous · **X** dead /
non-production · **T** test gap · **N** new design decision · **R** temporal
risk · **U** unresolved (not audited to depth).

---

# 3. CONCEPT-BY-CONCEPT AUDIT TABLE

## A. Market Structure

| # | Concept | Class | Evidence / production path |
|---|---|---|---|
| A1 | 5-bar fractal detection | **V** | `sweep_detector._find_recent_fractal_level:63`. 2 left + 2 right, scanned `i = len-3 → 2`. Causal, symmetric by column |
| A2 | **Fractal fallback is unsatisfiable** | **D** | When no fractal exists it returns `max(high)` / `min(low)` over the same 25-bar window that contains the current bar. `close > max(high)` is arithmetically impossible. **MEASURED: fires in 15/6,687 (0.22 %) BUY and 23/6,687 (0.34 %) SELL windows — latent, not a driver.** Impact: those decisions can never confirm CHoCH |
| A3 | **CHoCH is a BOS** | **D** | `sweep_detector.detect_choch:357`. Confirms on `close` beyond the most recent fractal **in the trade direction**; never reads trend. That is continuation, not change-of-character |
| A4 | CHoCH docstring self-inconsistency | **D (doc)** | *"Bullish CHoCH: close above last **Lower High**"* vs *"Bearish CHoCH: close below last **Lower Low**"*. LH is reversal semantics, LL is continuation. Not mirror images |
| A5 | CHoCH long/short symmetry | **V** | BUY `close > fractal_high`; SELL `close < fractal_low`; identical fallbacks. Implementation **is** symmetric |
| A6 | CHoCH lookback = 25 M15 bars | **A** | `m15_data.tail(25)`. No document states 25 or why |
| A7 | BOS (`detect_bos`, H1) | **U** | `sweep_detector:434`. Reached via `get_sweep_and_structure`. **NOT FULLY AUDITED** |
| A8 | Liquidity sweep (`detect_sweep`) | **U** | `sweep_detector:140`. **NOT FULLY AUDITED** |
| A9 | Sweep ATR is not ATR | **D** | `_estimate_m15_atr:51` = `close.diff().abs().rolling(14).mean()` — **ignores high/low entirely**. Registered in `core/indicators.py:8-20` as one of four incompatible ATR implementations, *"materially understates"* |
| A10 | Sweep ATR silent default `15.0` | **D** | Returns `15.0` on any failure — fabricates a volatility reading. `core/indicators.py:44-46` names this exact anti-pattern |
| A11 | Sweep buffers use ATR-proportional-with-floor | **V** | `near_buffer = max(2.5, atr*0.20)`, `momentum_buffer = max(5.0, atr*0.50)`. Scale-aware idiom, applied consistently — **but built on A9's wrong ATR** |
| A12 | Liquidity pools | **U** | `liquidity_engine.identify_liquidity_pools`. **NOT FULLY AUDITED** |
| A13 | Liquidity gate | **U** | `liquidity_engine.assess_liquidity_gate`. L4 blocked 629. **NOT FULLY AUDITED** |
| A14 | Equal highs / lows | **U** | Not located as a distinct concept in this pass. **UNRESOLVED** |
| A15 | H1 structure | **U** | `structure_engine.get_h1_structure`. L2 blocked 7, all *"HN structure is broken"*. **NOT FULLY AUDITED** |
| A16 | Structure invalidation | **U** | **UNRESOLVED** |
| A17 | Direction vocabulary fragmentation | **A** | Four vocabularies: `"BUY"/"SELL"` (entry, sweep, liquidity, poi), `"BULLISH"` (pullback_detector), `"up"` lowercase (structure_engine), `"NEUTRAL"` (bias_engine). Mapping correctness **not** verified in this pass |

## B. Price Action / Entry Construction

| # | Concept | Class | Evidence / production path |
|---|---|---|---|
| B1 | L8 FVG geometry | **V** | `entry_engine.detect_fvg:263`. BUY: `gap_low=left.high`, `gap_high=right.low`, middle bullish. SELL: exact mirror. **Correct 3-candle FVG, symmetric** |
| B2 | L8 FVG has no minimum size | **D** | `gap_valid = gap_high > gap_low` — a $0.01 gap qualifies. L6 documents *"unfilled gap ≥ 3 pips"*. Registered: *"two detectors disagree"* |
| B3 | Two FVG definitions coexist | **D** | `entry_engine.detect_fvg` (L8) and `poi_engine.detect_fvg:273` (L6) are different functions with different rules |
| B4 | FVG mitigation / expiry / invalidation | **X** | **None exist.** The FVG is always the last three bars, so an older gap can never be revisited. Documented in-code: *"unfilled is vacuous for a gap formed on the last three bars"* |
| B5 | `price_in_fvg` when `fvg_found` is False | **D** | `detect_fvg` returns bounds even when the flag is False; a consumer read them unguarded → **`price_in_fvg = True` in 943 cases with no FVG**. Registered in `PHASE_4A_MOMENTUM_ENTRY_SPEC.md:177-182` |
| B6 | Entry at FVG midpoint | **V** | Decided and documented, `PHASE_4A_MOMENTUM_ENTRY_SPEC.md:38-40`; **MEASURED** 104/104 midpoint-sourced entries inside the zone |
| B7 | CHoCH-override entry price removed | **V** | Phase 4A Step 4; comment at `entry_engine.py:583-591`. Was outside the gap on 13/13 |
| B8 | Must entry stay inside the FVG? | **N** | **[UNRESOLVED]** in the spec itself, `:211` |
| B9 | Displacement geometry | **V** | `entry_engine.detect_displacement_candle:228`. BUY `close>open and close_position>=0.7`; SELL `close<open and close_position<=0.3`. **Symmetric** |
| B10 | Displacement threshold is an OR | **A** | `body_to_atr >= 0.9` **OR** `body/range >= 0.6`. The second admits an ordinary small candle, defeating the "impulsive move" concept. No document states the OR was intended |
| B11 | Displacement bar ≠ FVG impulse bar | **A** | Displacement reads `iloc[-1]`; the FVG's impulse (middle) candle is `iloc[-2]`. In SMC the displacement candle *is* the gap-creating candle. Not documented either way |
| B12 | Market vs pending-limit semantics | **V** | `PHASE_4A_PENDING_ORDER_ARCHITECTURE.md`, `PHASE_4A_MARKET_VS_LIMIT_DECISION_BRIEF.md`; `LIMIT_FVG` path tested |
| B13 | Same-bar ordering | **V** | `replay_engine.run:256-269` — positions advance on the just-closed bar **before** the new decision, with the reason stated in-code |
| B14 | Entry fills on next bar open | **V** | `manifest.execution_assumptions.entry_timing = "next_bar_open"` |
| B15 | Duplicate / repeated signals | **U** | Not audited. `max_open_positions = 3` and `may_open_position` exist. **UNRESOLVED** |

## C. Fibonacci / Location

| # | Concept | Class | Evidence / production path |
|---|---|---|---|
| C1 | **Fibonacci is inert in the decision path** | **X** | `main_production.py:933` calls it; `:951` passes `has_fib_confluence` into `get_confidence_engine`; it reaches only `check_a_plus_checklist:225`. **`final_score` (`confidence_engine.py:147-153`) has no Fibonacci term**, and `main_production` reads only `final_score` (`:958`) and `grade` (`:970`). **The A+ checklist is never read by any gate** |
| C2 | Fib level set | **V (as written)** | `fibonacci_levels.FIB_LEVELS` = 0.236/0.382/0.500/0.618/0.786. Confluence tests only `0.500` and `0.618` |
| C3 | Fib anchoring | **U** | `find_swing_high_low(h1_data)`. **NOT FULLY AUDITED** |
| C4 | Premium / discount | **X** | No implementation found anywhere |
| C5 | Pullback-depth fib cap | **U** | `pullback_detector` documents *"depth ≤ 0.618 fib"*. **NOT FULLY AUDITED** |
| C6 | Fib test coverage | **T** | **`fibonacci_levels` is referenced by 0 test files** |

## D. Momentum / Pullback

| # | Concept | Class | Evidence / production path |
|---|---|---|---|
| D1 | **Momentum requires the kill zone** | **V** | `entry_engine.py:618-623`: `core_trigger = bool(kill_zone and displacement and fvg and m1_choch)` |
| D2 | **MICRO_SCALP is momentum-only** | **V** | `entry_engine.py:684-690`. Combined with D1: **MICRO_SCALP can only enter during hours 8, 9, 12, 13** |
| D3 | **74.3 % of MICRO_SCALP cannot enter** | **D** | **MEASURED**: 3,803 of 5,121 outside the kill zone — Asian 2,313 entire, London 1,490. Only 18.2 % of all decisions are inside a kill zone |
| D4 | **DEAD_CALM is less restrictive than MICRO_SCALP** | **D** | DEAD_CALM → both styles (default); MICRO_SCALP → MOMENTUM only. The "dead" regime can attempt pullbacks at any hour |
| D5 | Style mapping vs documented intent | **A** | `architecture.txt:222` says *"MICRO_SCALP momentum entries don't need pullback"* — consistent. INTRADAY_SWING → PULLBACK-only is **not** documented |
| D6 | Pullback detection | **U** | `pullback_detector.get_m15_pullback`. **L3 is the largest gate: 5,868 blocks (37.3 %)**. **NOT FULLY AUDITED — the single largest unaudited surface** |
| D7 | Pullback ATR is not ATR | **D** | `pullback_detector._estimate_recent_atr` — *"correct true range, but SMA-14, not Wilder"* (`core/indicators.py:11`) |
| D8 | Pullback / momentum mutual exclusivity | **V** | `entry_engine.py:703-730`: both are evaluated, filtered by `allowed_styles`, best by `_score_entry_candidate`; `setup_type` can be `BOTH`. **Not exclusive by design** |
| D9 | Momentum fallback raises the L7 bar | **V** | `main_production.py:960-972`, commented `FIX (SCALP-1)`; also demotes `A+ → A` |

## E. Multi-Timeframe

| # | Timeframe | Class | Contribution / consumption |
|---|---|---|---|
| E1 | **M1** | **V** | 200 bars. M1 CHoCH + entry refinement in `entry_engine`. Causal |
| E2 | **M5** | **V** | 100 bars. ATR/regime, FVG, displacement, rejection, triggers. Causal |
| E3 | **M15** | **V** | 50 bars. Pullback, sweep, CHoCH, liquidity. Causal |
| E4 | **H1** | **V** | 60 bars. Bias, structure, `h1_atr` gate, fib swing. Causal |
| E5 | **H4** | **V** | 100 bars. `get_h4_bias`, conflict flag only. Causal |
| E6 | **D1** | **A** | 10 bars requested and passed to `analyze_entry`. **Whether any consumer reads it was not established in this pass** |
| E7 | **H4/D1 are not UTC-aligned** | **A** | **MEASURED**: H4 opens at 01/05/09/13/17/21 UTC; D1 at 21. Broker UTC+3, preserved rather than re-cut (D3). **Does not affect regime/session, which read only M5/M15/H1** |
| E8 | Timeframe relationship documented | **A** | `architecture.txt` documents the ladder; the **bar counts** are documented only in the run manifest |
| E9 | Higher-timeframe leakage | **V** | `test_integration_leakage.MultiTimeframeIntegrityTests` — each timeframe shows only closed bars; ladder monotonic; higher-TF bars aggregate their children |

## F. Volatility / Regime *(established in 6L/6M/6N — not re-litigated)*

| # | Concept | Class | Evidence |
|---|---|---|---|
| F1 | M5 ATR source | **V** | `ta.atr(length=14)`, read at `frame.iloc[-1]` — closed bar, price units |
| F2 | ATR bands calibrated in dollars (U10-A) | **V** | 6L: a pips reading gives 100 % INTRADAY_SWING |
| F3 | Band **label** says pips | **D (doc)** | `main_production.py:216` prints `pip`; `core/indicators.py:24-27` records it |
| F4 | **U10-B absolute vs relative** | **N** | 6N §6.4: **MIXED** idioms, bands **UNDOCUMENTED**, never changed since `c3cf4df` |
| F5 | `atr_ratio` exists and regime ignores it | **D** | `indicators.py:189-190` returns `atr_ratio` + `volatility_classification` on the same frame; `entry_engine.py:534` uses `atr_ratio`; `detect_regime` does not |
| F6 | Price-level dependence (G2) | **A** | **MEASURED**: mix flat across 4 of 5 price quintiles over an 18.6 % range; `corr = 0.149`. **G2 is sound in theory, not demonstrated here** |
| F7 | H1 gate statistic is not ATR | **D** | `main_production.py:675` = `mean(high-low)` over 14 bars |
| F8 | H1 gate never fires (U9-H1) | **X** | **MEASURED** with the production formula: min **10.903**; **0 blocks** at 8.0 and at 0.80. Corroborates D9 |
| F9 | L2 name hides a volatility gate | **D** | Blocks as `L2_STRUCTURE` with reason *"H1 ATR too calm"* |
| F10 | DEAD_CALM is a catch-all | **D** | 6M: 2,193 of 2,312 (94.85 %) are band-B, session-diverted |
| F11 | DEAD_CALM absent from every consumer | **D** | Four sources name three regimes + default |
| F12 | Regime error path is a second DEAD_CALM | **D** | `entry_engine.py:136-148`: `tp_ratio 2.0`, `risk 1.0`, **no `max_spread_pips` key**. **0 occurrences** |
| F13 | Session inside a volatility classifier | **D** | B1 only; undocumented widening of a documented `+ killzone` conjunct |

## G. Session / Kill Zone *(6M/6N)*

| # | Concept | Class | Evidence |
|---|---|---|---|
| G1 | Session intervals | **V** | Asian `[0,7)`, London `[7,13)`, NewYork `[13,21)`, Dead `[21,24)`, Closed = weekend. Contiguous, disjoint |
| G2 | `LondonNewYork` never returned | **D** | D8. Gated on at `entry_engine.py:75`; mapped at `main_production.py:442`; best multiplier at `config.py:125` |
| G3 | Overlap handling | **A** | The real 13:00–16:00 overlap is folded into `NewYork` |
| G4 | Kill zone ignores weekday | **D** | `_within_kill_zone` reads `.hour` only. **Latent: 0 occurrences** — weekend bars exist only at hours 22–23 |
| G5 | Session is **not** an independent gate in the decision path | **X** | Both implementations dead: L0 is called from `main()`, not `analyze_entry` (C20); `strategy_engine._validate_session_rules` is in a module nothing imports |
| G6 | `Dead` vs `Closed` | **D** | Produced distinct; `get_session_name` maps **both → `"DEAD"`**; only the dead `strategy_engine` distinguishes them |
| G7 | No DST handling | **A** | Fixed UTC hours; `core/clock.py` has the machinery and the legacy path does not use it |
| G8 | DEAD-window message wrong at both ends | **D (doc)** | *"22:00 and 03:00"* vs implemented 21:00–23:59 |
| G9 | Seven session vocabularies | **D** | 6N §5.3 |
| G10 | Session long/short symmetry | **V** | No live session rule branches on direction. *(The dead `strategy_engine` has *"Asian: Only BUY"* — asymmetric, unreachable)* |
| G11 | Session affects regime classification | **D** | It does, via B1 — contrary to `architecture.txt:566` |

## H. Entry Quality / Scoring

| # | Concept | Class | Evidence |
|---|---|---|---|
| H1 | **Cohesion double-counts its own inputs** | **D** | `confidence_engine.py:135-143`: `strong_components` counts how many of bias/structure/sweep/poi exceed 70, then adds up to `weights["cohesion"]*100` (10–20 % of the score). **Not independent evidence** |
| H2 | **L7 threshold implemented twice** | **D** | `confidence_engine.py:157-160` and `main_production.py:959` independently compute `55 / 70` |
| H3 | A+ checklist is inert | **X** | Feeds only `recommendation` and `a_plus_checklist`; neither is read by any gate |
| H4 | Session bonus tables disagree | **D** | `confidence_engine._get_session_adjustment`: LONDON/NEWYORK +8, ASIAN 0, DEAD −15. `main_production.get_session_bonus` duplicates it. Root `test_layer_fixes.py:358` asserts ASIAN **−5.0** — a value neither implementation produces |
| H5 | Quality saturation | **D** | `quality = min(10.0, quality)` in every detector. 6K-F's boundary candidate had `trigger_quality = 10.0` — the maximum, so the gate `>= 5.0` carried no information there |
| H6 | L8 quality thresholds 5.0/6.0/7.0 | **A** | No archaeology recovers them (6K-D) |
| H7 | `atr_ratio >= 1.0` → +0.5 quality | **V** | `entry_engine.py:534`. Scale-free, symmetric |
| H8 | POI score | **U** | `poi_engine`. L6 blocked **1** decision in 15,735. **NOT FULLY AUDITED** |
| H9 | Bias strength | **U** | `bias_engine`. L1 blocked 2,392 (15.2 %). **NOT FULLY AUDITED** |
| H10 | Spread never enforced | **X** | S9: L0 logs `[CHECK DISABLED]`, `evaluate_entry_for_regime` hardcodes `spread_ok = True`, `regime_info["spread_acceptable"]` never read |

## I. Risk / Stop / Target *(6J/6K)*

| # | Concept | Class | Evidence |
|---|---|---|---|
| I1 | Stop buffer applied in price units | **D** | U1/Q6: `_select_stop_anchor(buffer_pips=3.0)` subtracts **$3.00**. Pinned by `TestStopBufferIsAppliedInPriceUnits` |
| I2 | ATR fallback stop | **A** | Risk 30.0 when no anchor. Pinned by `test_a_missing_anchor_still_falls_back_to_the_atr_stop` |
| I3 | Structural stop from sweep wick | **V** | Anchored to the sweep wick, symmetric |
| I4 | Target construction | **V** | `take_profit = entry ± risk_distance * tp_ratio` |
| I5 | **`rr ≡ tp_ratio` tautology** | **D** | E9/E10. `rr` is **not market-derived**; it restates the regime constant |
| I6 | RR representation repaired (U4) | **V** | 6K-F: `reward_distance = risk_distance * tp_ratio`; error ~1.7e-13 → ≤1 ulp |
| I7 | Boundary hazard narrowed, not removed | **A** | `(R×k)/R ≠ k` in ~10 % of random pairs, always 1 ulp. MICRO_SCALP's threshold **equals its own `tp_ratio`** |
| I8 | **RR admission policy (U9-RR)** | **N** | 6K-D: no value recoverable. **Blocked behind D-6N-1** |
| I9 | RR meaning vs RR policy | **V (distinction established)** | 6K-E: meaning is tautological (I5); policy is a separate open decision (I8) |
| I10 | Canonical R frozen at creation | **V** | `R = \|actual fill − original stop\|`; §4.2 target recomputation |
| I11 | Sizing contract | **V** | 6E/6F: calc-mode abstraction, live-captured `order_calc_profit`, `SIZING_CONTRACT.md` |
| I12 | Baseline uses fixed size, not `risk_manager` | **V** | Manifest states it, with the reason (R1 10× defect) |
| I13 | Long/short RR symmetry | **V** | `test_reward_distance_is_risk_times_ratio` asserts both directions exactly |

## J. Execution / Lifecycle

| # | Concept | Class | Evidence |
|---|---|---|---|
| J1 | Canonical domain owns every exit | **V** | `replay_engine.run:253-254`; `evaluate` is pure, reads no clock |
| J2 | `PendingOrderIntent` → fill | **V** | `tests/execution/test_pending_limit_orders.py` |
| J3 | Partial exits | **V** | `PartialCloseRequest/Filled/Rejected`; *"never zero — a zero-step partial is not"* |
| J4 | Breakeven / LOCKED_1R | **V** | `StopState` forward-only `ORIGINAL → BREAKEVEN → LOCKED_1R` |
| J5 | **Reversal protection** | **X** | `core/trade_model.py:64` — *"R1-R4 are likewise unimplemented: there is no reversal protection…"* |
| J6 | **Time-based exit / max holding** | **X** | Same line — *"no time-based exit"* |
| J7 | **Continuous trailing** | **X** | Same line — *"no continuous trailing"* |
| J8 | **Session-close / weekend exit** | **X** | Not implemented. `END_OF_DATA` closes at the last decision instant |
| J9 | `END_OF_DATA` priced at last decision | **V** | `replay_engine:300-310`, with the wall-clock hazard removed and commented |
| J10 | **U5/R8** — re-requested close reference | **N** | Module refuses to guess; carries `observed_reference=None` |
| J11 | **U6/R9** — unconfirmed promotion blocking a milestone | **N** | Raises `UnresolvedCanonicalDecisionError` rather than picking |
| J12 | Live execution impossible | **V** | 6G/6H: `LIVE_TRADING_ENABLED = False` literal, AST-scanned allow-list, 20 tests |

## K. Temporal Correctness

| # | Concept | Class | Evidence |
|---|---|---|---|
| K1 | No future bar visible | **V** | `bar.open_time + duration <= T`, `searchsorted(side="right")`, defensive copy. **MEASURED: 0 violations / 15,735 decisions / 6 timeframes** |
| K2 | Boundary visibility | **V** | Minimum lag exactly `0:00:00` on M1–H4 |
| K3 | ATR lookback causal | **V** | `frame.iloc[-1]` = newest closed bar |
| K4 | Fractal scan causal | **V** | Centre at `i`, needs `i+1`, `i+2` — all closed; confirmed 2 bars late |
| K5 | Displacement / FVG causal | **V** | `iloc[-1]` and `iloc[-3..-1]` |
| K6 | Session / kill zone causal | **V** | `frozen_clock` supplies the decision instant (N1/N2) |
| K7 | Future-mutation tests | **V** | Mutate post-cutoff bars; assert decisions, entry/stop/target, every layer payload unchanged |
| K8 | Same-bar SL/TP ambiguity | **V** | `intrabar_policy: "conservative"`, disclosed in the manifest |
| K9 | Pending-order fill ordering | **V** | Fill on next bar open; positions advance before the new decision |
| K10 | **Regime / session absent from leakage tests** | **T** | Neither word appears in either leakage test file |
| K11 | **Timezone-independence test vacuous on Windows** | **T** | `hasattr(time,'tzset')` is **False** here; degrades to a determinism check |

## L. Production Reachability — see §4

## M. Long/Short Symmetry — see §5

## N. Test Audit — see §9

---

# 4. PRODUCTION REACHABILITY MAP

Entry point: **`main_production.analyze_entry`** (per `manifest.strategy_entry_point`).

| Layer | Module / function | Reached | Blocked | Ever changes an outcome? |
|---|---|---|---|---|
| **L0** | `check_pre_trade_gates` | **0** | 0 | **No — called from `main()`, not `analyze_entry`** |
| L1 | `bias_engine` | 15,735 | 2,392 | Yes |
| L2 | `structure_engine` + `h1_atr` | 13,343 | **7** | Structure yes (7); **ATR sub-gate never** |
| L3 | `pullback_detector` | 13,336 | **5,868** | Yes — largest gate |
| L4 | `liquidity_engine` | 7,468 | 629 | Yes |
| L5 | `sweep_detector` | 6,839 | **4,075** | Yes |
| L6 | `poi_engine` | 2,764 | **1** | Barely |
| L7 | `confidence_engine` | 2,763 | 1,498 | Yes — via `final_score` only |
| L8 | `entry_engine` | 1,265 | 1,261 | Yes |

**Dead or inert despite being reachable:**

| Item | Status |
|---|---|
| `fibonacci_levels` + `evaluate_poi_fib_confluence` | **Computed every decision, affects nothing** (C1) |
| `check_a_plus_checklist` | Computed, never read by a gate (H3) |
| `regime_info["max_spread_pips"]` / `spread_acceptable` | Computed, never enforced (H10) |
| `h1_atr < 8.0` | Evaluated 13,343 times, **fired 0** (F8) |
| `"LondonNewYork"` disjunct | Evaluated every decision, **can never be true** (G2) |
| `config.INTRADAY_SESSION_MULTIPLIERS` | Read only by `test_integration.py:122` |
| `strategy_engine` (entire module) | Imported by **no** production module |
| `main.py`, `technical_engine.py` | Predecessor system; not on the `main_production` path |

---

# 5. LONG/SHORT SYMMETRY FINDINGS

**No asymmetry was found in any reachable concept.**

| Concept | BUY | SELL | Verdict |
|---|---|---|---|
| CHoCH | `close > fractal_high` | `close < fractal_low` | **Symmetric** |
| Fractal | `center > l1,l2,r1,r2` | `center < l1,l2,r1,r2` | **Symmetric** |
| FVG | `left.high → right.low`, middle bullish | `right.high → left.low`, middle bearish | **Symmetric** |
| Displacement | `close>open`, `close_position>=0.7` | `close<open`, `close_position<=0.3` | **Symmetric** |
| Displacement quality | `close_position >= 0.8 or <= 0.2` | same expression | **Symmetric** |
| Stop anchor | wick low − buffer | wick high + buffer | **Symmetric** (both in $, I1) |
| Target | `entry + R*k` | `entry − R*k` | **Symmetric**, tested both ways |
| RR | `reward/risk` | identical | **Symmetric** |
| Session / kill zone | no direction branch | — | **Symmetric** |
| Sweep, liquidity, POI, bias, pullback | — | — | **NOT AUDITED** |

**One asymmetry exists and is unreachable:** `strategy_engine._validate_session_rules`
— *"`Asian`: Only BUY (gold buys in Asia)"*. In a dead module.

**Baseline check:** `side_performance.json` exists in every baseline, so the
artifacts can support a symmetry check — but with **0 trades** it is empty, so
symmetry cannot be validated from outcomes, only from code.

---

# 6. TEMPORAL / LOOK-AHEAD FINDINGS

**No confirmed look-ahead. No TEMPORAL RISK item was substantiated.**

Measured: **0 future-bar violations** across 15,735 decisions on six timeframes;
minimum lag exactly `0:00:00` on M1/M5/M15/H1/H4 and `1:05:00` on D1. Every
concept audited to depth reads only closed bars.

**Two residual risks, both test gaps rather than defects:** K10 (regime/session
not covered by the mutation tests) and K11 (timezone test vacuous on Windows).

**One structural observation, not a defect:** H4 and D1 are broker-aligned
(UTC+3), deliberately preserved. The regime/session path reads only M5/M15/H1
and is unaffected.

---

# 7. DEAD / INERT LOGIC

Fibonacci confluence (C1) · A+ checklist (H3) · premium/discount (C4, absent) ·
FVG mitigation/expiry (B4, absent) · spread enforcement (H10) · `h1_atr` gate
(F8) · `"LondonNewYork"` (G2) · L0 session gate (G5) ·
`strategy_engine._validate_session_rules` (G5) · `INTRADAY_SESSION_MULTIPLIERS` ·
reversal protection, time exit, trailing, session-close/weekend exit (J5–J8) ·
regime error path (F12, 0 occurrences) · weekend kill zone (G4, 0 occurrences).

---

# 8. DOCUMENTATION-vs-CODE CONTRADICTIONS

| # | Document says | Code does |
|---|---|---|
| 1 | *"Bearish CHoCH: close below last Lower Low"* | Breaks the recent fractal low — a BOS, and not the mirror of the bullish rule (A3/A4) |
| 2 | *"FVG is an unfilled gap ≥ 3 pips"* (L6) | L8 requires only `gap_high > gap_low` (B2) |
| 3 | `architecture.txt:410` *"DEAD_CALM \| ATR < 2.5 (blocked at L2)"* | Catch-all; L2 block never fires (F10, F8) |
| 4 | `architecture.txt:402` *"2.5 <= ATR <= 4.5 + killzone"* | `kill_zone OR session in {...}` (F13) |
| 5 | `architecture.txt:566` L0 *"session valid"* | L0 not on the decision path (G5) |
| 6 | *"H1 ATR < 8 pips = DEAD CALM → BLOCK"* | `mean(high−low)` in dollars; 0 firings (F7/F8) |
| 7 | `m5_atr … pip` display | Quote-currency dollars (F3) |
| 8 | *"no trading between 22:00 and 03:00 UTC"* | Blocks 21:00–23:59; never 00:00–02:59 (G8) |
| 9 | `c3cf4df` *"3-MODE ADAPTIVE SYSTEM"* | Four regimes emitted (F11) |
| 10 | `else: # M5 ATR > 7.0 OR < 2.5` | Also reached for band B (F10) |
| 11 | `architecture.txt:405` REGIME_SCALP `4.5 <` | Code `>= 4.5` |
| 12 | *"L8 uses volume, RSI, MACD"* | **MACD absent repo-wide** |
| 13 | *"POIs are entry zones"* | **0 entries at a POI** |
| 14 | `test_layer_fixes.py:358` ASIAN bonus `−5.0` | Both implementations produce `0.0` (H4) |

---

# 9. TEST GAPS

**970 tests. Coverage is concentrated on `core/`, `backtest/`, `execution/` and
`data/`; the strategy layer is thin** — registered as V6, *"Strategy-layer test
coverage remains near zero."*

| Gap | Detail |
|---|---|
| **T1** | **No test exercises any ATR band boundary** or any `(ATR, session) → regime` pair |
| **T2** | **Regime and session absent from both leakage test files** (K10) |
| **T3** | **Timezone-independence test vacuous on Windows** (K11) |
| **T4** | Session **boundary** hours (0, 7, 13, 21) untested; only 3/9/15/23 |
| **T5** | **`fibonacci_levels`: 0 test files** |
| **T6** | No test for CHoCH's fractal fallback (A2) or its BOS/CHoCH semantics (A3) |
| **T7** | No test for FVG minimum size, mitigation, expiry (B2/B4) |
| **T8** | No test for the displacement OR-threshold (B10) |
| **T9** | No test that DEAD_CALM's composition is what is claimed |
| **T10** | **Misleading tests:** `tests/test_entry_quality_gate.py` passes `rr` of 1.4/2.4/2.8 against regimes whose `tp_ratio` is 1.5/2.0/3.0 — **values that cannot occur in production** (6J §F.1). Left alone deliberately in 6K-F; retiring them is U7 |
| **T11** | **Two known failures**, `test_layer_gate_logic` — both caused by the `h1_atr` gate reading `0.0 < 8.0` when indicators are mocked (D7). They are themselves an artefact of F7 |
| **T12** | Root-level `test_*.py` (8 files) are **not** in the `tests/` suite and are not run by `unittest discover -s tests` |

---

# 10. NEW DESIGN DECISIONS DISCOVERED

| ID | Decision | Why it cannot be recovered |
|---|---|---|
| **D-6O-1** | Should `detect_choch` implement a CHoCH (trend-aware, counter-trend swing) or be renamed to BOS? | Docstring is self-inconsistent (A4); no other source defines it |
| **D-6O-2** | Should the L8 FVG carry a minimum size, mitigation and expiry — i.e. be the same concept as L6's? | Two detectors, two definitions, no reconciling document (B2/B3) |
| **D-6O-3** | Is displacement `ATR-relative OR body-ratio`, or ATR-relative only? | The OR is undocumented (B10) |
| **D-6O-4** | Should displacement be checked on the FVG's impulse candle rather than the right candle? | Undocumented either way (B11) |
| **D-6O-5** | Should Fibonacci influence the score, or be removed? | It is wired in and inert; no document says which was intended (C1) |
| **D-6O-6** | Should cohesion be independent evidence, or is double-counting intended? | No document (H1) |
| **D-6O-7** | Must the entry price remain inside the FVG? | **[UNRESOLVED]** in the Phase 4A spec itself (B8) |
| **D-6O-8** | U5/R8 and U6/R9 — canonical lifecycle questions | The domain module refuses to guess (J10/J11) |
| — | Carried forward: **D-6N-1..7**, including **U10-B** and **U9-RR** | |

---

# 11. PRIORITIZED BLOCKERS BEFORE PHASE 7

| # | Blocker | Why it blocks |
|---|---|---|
| **1** | **D-6N-1** — does session eligibility belong inside regime classification? | Changes the DEAD_CALM population 19× and moves 2,193 decisions across the L8 RR gate |
| **2** | **Audit L3 to depth** (`pullback_detector`) | **5,868 blocks, 37.3 %** — the largest gate in the system and **NOT FULLY AUDITED**. No contract can be called established while the biggest filter is unexamined |
| **3** | **Audit L5 to depth** (`detect_sweep`, `detect_bos`) | 4,075 blocks, and it runs on a non-ATR statistic with a fabricated default (A9/A10) |
| **4** | Close **T1/T2** before any regime change | Pinning tests must exist *before* behaviour moves |
| **5** | **D-6O-1** (CHoCH semantics) | 2,441 L5 blocks come from a gate that does not implement its own name |
| **6** | **D-6N-2** — where session eligibility executes | After (1); both implementations are dead |
| **7** | **U9-RR** | Blocked behind (1) |

---

# 12. ITEMS THAT SHOULD BE FROZEN AS CORRECT

The temporal model in full (K1–K9): visibility invariant, boundary rule,
defensive copies, future-mutation tests, same-bar ordering, next-bar fills,
`END_OF_DATA` pricing. · The canonical trade domain (J1–J4, J9): purity,
forward-only stop states, partial-close representation, frozen R, §4.2 targets.
· Execution safety (J12). · Sizing (I11, I12). · FVG and displacement
**geometry and symmetry** (B1, B9) — geometry only, not thresholds. · Long/short
symmetry of every audited concept (§5). · U4's RR representation repair (I6). ·
Determinism and fingerprinting.

---

# 13. ITEMS THAT MUST NOT YET BE CHANGED

Every ATR band (2.5/4.5/7.0) · every RR threshold (1.5/2.0/2.5) · every quality
threshold (5.0/6.0/7.0) · every `tp_ratio` · L7 thresholds (55/70) · POI
thresholds (50/60/70) · `KILL_ZONES_UTC` · every `get_current_session` boundary ·
`"LondonNewYork"` at all three sites · DEAD_CALM in any respect · regime↔style
mappings · the stop buffer · the ATR fallback · `baseline_004`, `baseline_005`,
R1 fixtures and every fingerprint · the two known `test_layer_gate_logic`
failures (they are evidence of F7).

---

# 14. COUNTS

| Metric | Count |
|---|---|
| **Total concepts audited** | **68** |
| **VERIFIED** | **26** |
| **IMPLEMENTATION DEFECT** | **21** |
| **INTENT AMBIGUOUS** | **12** |
| **DEAD / NON-PRODUCTION** | **9** (plus 5 inert items counted under their own class) |
| **TEST GAP** | **12** (T1–T12; K10/K11 also carried in the concept table) |
| **DESIGN DECISION** | **8 new** (D-6O-1..8) **+ 7 carried** (D-6N-1..7) = **15** |
| **TEMPORAL RISK** | **0 confirmed** — 2 test-coverage risks only |
| **UNRESOLVED / not audited to depth** | **14** |

*Concepts carrying more than one class are counted under the most severe.*

---

# 15. THE EXACT NEXT ENGINEERING ACTION

> **Audit `pullback_detector` (L3) to the same depth this pass reached for
> `entry_engine` — as a documentation-only phase, changing nothing.**

**Why this and not the regime change.** L3 blocks **5,868 decisions, 37.3 %** —
more than any other gate, more than L5 and L8 combined. It is the single largest
determinant of what this system does, and it is the largest surface this audit
did **not** examine. Phase 6N's D-6N-1 would move 2,193 decisions into a regime
whose entries must still pass L3, and its consequences cannot be predicted while
L3's contract is unknown.

**Scope:** the same treatment applied here — documented intent vs implementation,
reachability, temporal correctness, long/short symmetry, units, gate
interactions, test coverage — plus specifically the SMA-14 "ATR" (D7), the
0.618 depth cap (C5), and the `"BULLISH"` direction vocabulary (A17).

**Do not implement D-6N-1, do not select U9-RR, and do not change any threshold
until L3 and L5 are audited to depth.**

---

# 16. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| Thresholds / parameters / regime / session | **Untouched** |
| U9-RR | **Not selected** |
| Baselines and R1 fixtures | **Not regenerated, not re-pinned** |
| Trade count used as evidence of correctness | **No** |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
