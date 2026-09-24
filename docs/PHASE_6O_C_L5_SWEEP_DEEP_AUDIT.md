# Phase 6O-C — L5 Sweep / CHoCH / BOS Deep Audit

**Audit only. No source changed.** No parameter, no threshold, no strategy
behaviour, no regime/session change. Duplicated code was **not** refactored.
U9-RR is not resolved. `baseline_004`, `baseline_005` and the R1 fixtures were
read, never written.

**Input:** commit `8d36338` (Phase 6O-B). Statistics come from the **frozen**
`baselines/baseline_005/decisions.jsonl` (15,735 records) and the frozen dataset
`433b7e27…`.

**The three questions are kept apart**, as instructed: what the code does (§3),
what the documentation says it should do (§2), and whether the behaviour should
be required at all — **D-6OC-1, recorded in §16 and deliberately unanswered**.

---

# 1. Executive Summary

**L5's specification and its implementation disagreed on the day the file was
written, and the file has never been touched since.**

Seven findings.

1. **`sweep_detector.py` has exactly one commit — `c3cf4df`, 2026-07-01 — and
   is byte-identical to HEAD.** There is no semantic-change history to trace.
   Every documentation/code contradiction below is **original**, not drift.

2. **The documented sweep depth is "3–8 pips". The implemented band is
   `max(2.5, atr*0.12)` to `max(30.0, atr*2.0)` in dollars — $2.50 to $30.00.**
   That is **8× to 25× the documented floor and up to 37× the documented
   ceiling**. Registered as U8 for the floor; **the $30.00 ceiling is newly
   recorded here**.

3. **The documented quality checklist says "must pass 3+". The code requires
   `checks_passed >= 2`.**

4. **BOS cannot independently change any outcome.** `detect_bos` runs *only*
   when CHoCH is confirmed, so `bos_confirmed ⟹ choch_confirmed`, making the
   `bos` term in `_assess_sweep_state`'s disjunction logically redundant. Its
   only other output, `setup_grade`, is **recorded and never read by a gate**.
   The documented grade→risk mapping (*"A+ … 1.5 % risk"*, *"B-Tier … 0.75 %"*)
   is **unimplemented** — risk comes from the regime. **BOS is inert.**

5. **Sweep diagnostics are masked.** `_assess_sweep_state` receives
   `{**sweep_result, **choch_result, **bos_result}`, and both `sweep_result` and
   `choch_result` carry a `reasoning` key. CHoCH's overwrites the sweep's.
   **MEASURED: all 2,441 `L5_SWEEP` blocks report *"M15 CHoCH not confirmed"*
   and not one reports why the sweep failed.** The frozen record therefore
   cannot answer how often `detect_sweep` failed.

6. **The `L5_SWEEP_DIRECTION` guard is structurally unreachable.**
   `detect_sweep` is called with `direction = side`, so a BUY can only ever
   return `bullish_sweep` or `no_sweep`. **Predicted, then measured: 0
   occurrences in 15,735 decisions.**

7. **The L3/L5 fractal routines are the same algorithm and disagree 13.67 % of
   the time in production.** Handed an identical window they agree **6,652 /
   6,652 = 100 %**. As actually called they disagree on **909 of 6,652** windows,
   by a median of **$7.15** and up to **$124.46** — purely because L5 re-tails to
   25 bars internally while L3 passes 49 and the routine does not re-tail.

**L5 blocks 4,075 of the 6,839 decisions that reach it — 59.58 %.** The binding
term is CHoCH, whose confirmation rate measured standalone is **16.4 % (BUY) /
17.5 % (SELL)**, with the close typically **$10.44 / $10.78 short** of the level
it must break. **That is a market-structure fact, not a threshold artefact.**

---

# 2. Historical Intent Timeline

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | **`c3cf4df`** | **File created.** |
| — | — | **No further commits.** `git diff c3cf4df HEAD -- sweep_detector.py` is **empty** |

**There are no subsequent semantic changes, no removed conditions, no renamed
concepts and no conflicting later documentation.** L5 is the original 2026-07-01
implementation, unmodified.

### 2.1 The documented specification (`c3cf4df` docstring, still current)

| # | Documented | Implemented? |
|---|---|---|
| 1 | *"Wick penetration: **3-8 pips** below pool"* | **NO** — `max(2.5, atr*0.12)` … `max(30.0, atr*2.0)` in **dollars** |
| 2 | *"Candle **CLOSES back ABOVE** pool level"* | **Yes** — `candle_close > liquidity_level` |
| 3 | *"**Close > Open** (bullish confirmation)"* | **NO** — never tested. Close-above-level is tested; close-above-open is not |
| 4 | *"Volume on sweep candle **≥ baseline**"* | **Partly** — a `1.4×` spike is *quality check 2*, not a requirement |
| 5 | *"Real sweep must pass **3+**"* | **NO** — `checks_passed >= 2` |
| 6 | *"Wick ≥ 1.5× candle body"* | **Yes**, as check 1 |
| 7 | *"Close back inside prior range **within 1 candle**"* | **NO** — implemented as check 4, *"next candle continues up"*, a different condition |
| 8 | *"CHoCH: close above last M15 **Lower High** … or below last M15 **Lower Low**"* | **NO** — breaks the most recent fractal in the trade direction, ignoring trend (Phase 6O A3/A4). The docstring is also self-inconsistent |
| 9 | *"BOS … Grade: **A+-Tier (strong setup, 1.5 % risk)**"* | **NO** — `setup_grade` never sets risk |
| 10 | *"CHoCH … Grade: **B-Tier (decent setup, 0.75 % risk)**"* | **NO** — same |

**Can L5's current behaviour be historically justified? No.** There is exactly
one version of the code and one version of the specification, and they
contradict each other on **seven of ten** documented points. **This is not
drift — the implementation never matched its own docstring.**

---

# 3. The Exact L5 Contract

## 3.1 Gate verdict (`main_production.py:867-897`)

```
gate_state = PASS   →  proceed, layers_passed += "L5_SWEEP"
gate_state = WATCH  →  block "L5_SWEEP_WAIT"
gate_state = BLOCK  →  block "L5_SWEEP"   (the explicit re-test below agrees)

explicit re-test:  not (sweep_confirmed OR choch_confirmed)  →  "L5_SWEEP"
direction guard :  BUY+bearish_sweep or SELL+bullish_sweep   →  "L5_SWEEP_DIRECTION"   [UNREACHABLE]
```

`_assess_sweep_state` (`sweep_detector.py:85`):

```
PASS   ⟸ sweep_confirmed ∨ choch_confirmed ∨ bos_confirmed        (bos term redundant — §8.1)
WATCH  ⟸ −near_buffer ≤ distance_to_level ≤ momentum_buffer
         near_buffer     = max(2.5, m15_atr * 0.20)
         momentum_buffer = max(5.0, m15_atr * 0.50)
         BUY : distance = liquidity_level − min(low  of last 12 M15)
         SELL: distance = max(high of last 12 M15) − liquidity_level
BLOCK  ⟸ otherwise
```

**Effective pass condition: `sweep_confirmed ∨ choch_confirmed`.**

## 3.2 `detect_sweep` (`sweep_detector.py:140`)

| Element | Value |
|---|---|
| Timeframe | **M15** |
| Window | `recent = m15_data.tail(15)` — **includes the newest closed bar** |
| Scan | `idx` descending; `candles_ago > 8 → continue`, so **the last 9 bars** |
| Baseline volume | `m15_data["tick_volume"].mean()` — **the whole frame**, not the window |
| ATR | `_estimate_m15_atr` = `close.diff().abs().rolling(14).mean()` — **close-to-close, ignores high/low**; silent default **15.0** |
| **`sweep_min`** | `max(2.5, m15_atr * 0.12)` — **dollars** |
| **`sweep_max`** | `max(30.0, m15_atr * 2.0)` — **dollars** |
| `volume_threshold` | `1.4` |
| **`tolerance_pips = 1.5`** | **Declared, documented, never referenced — DEAD** |
| `l4_override_level` | Overwrites `liquidity_level` when supplied. **Production always supplies it**, equal to the same `sweep_pool["level"]`, so the "hard handshake" is a no-op in practice |
| **BUY trigger** | `sweep_min ≤ (level − low) ≤ sweep_max` **and** `close > level` |
| **SELL trigger** | `sweep_min ≤ (high − level) ≤ sweep_max` **and** `close < level` |
| Check 1 | `wick_ratio = wick/body ≥ 1.5` → +3.0 |
| Check 2 | `volume ≥ baseline × 1.4` → +2.0 |
| Check 3 | BUY `close_pos > 0.5` / SELL `close_pos < 0.5` → +2.0 |
| Check 4 | next candle continues (skipped for the newest bar) → +1.0 |
| **Confirm** | **`checks_passed >= 2`** |

## 3.3 `detect_choch` (`sweep_detector.py:357`)

| Element | Value |
|---|---|
| Timeframe | **M15**, `tail(25).reset_index(drop=True)` |
| Level | `_find_recent_fractal_level(recent, "high"/"low")`, which **re-tails to 25 internally** |
| BUY | `close > fractal_high` · SELL | `close < fractal_low` |
| Fallback | `recent[col].max()` / `.min()` — **unsatisfiable**, 0.22 % / 0.34 % of windows (Phase 6O A2) |
| Trend input | **None** — this is why it is a BOS, not a CHoCH |

## 3.4 `detect_bos` (`sweep_detector.py:434`)

| Element | Value |
|---|---|
| Timeframe | **H1**, `tail(30)`; requires `len(h1) >= 20` |
| Invoked | **Only when `choch_confirmed`** |
| Candidates | `for i in range(len(highs) - 5)` — the **last 5 bars are excluded as centres** |
| Touch test | `sum(1 for h in highs[i:i+15] if abs(h - highs[i]) <= 2.0) >= 2` — **the comment says "within 2 pips"; `2.0` is dollars = 20 pips** |
| Self-count | `highs[i]` is inside its own slice, so it always contributes 1 — `>= 2` means **one other bar within $2.00** |
| Level | `max(swing_candidates)` / `min(swing_candidates)` |
| Fallback | `recent["high"].max()` — unsatisfiable. **MEASURED: candidates are empty in 0 of 1,641 H1 windows** |
| Confirm | `close > swing_high` / `close < swing_low` |

## 3.5 Dependencies

**Inputs:** M15 frame, H1 frame, `liquidity_level` from **L4**, `direction` from
L1 bias. **No FVG, no momentum, no pullback, no regime, no session input.**

---

# 4. Production Call Graph

```
main_production.analyze_entry  (L5 block, main_production.py:867-905)
  └── get_sweep_and_structure(m15, h1, l4_sweep_level, side, l4_override_level=l4_sweep_level)
        ├── detect_sweep(m15, level, direction, l4_override_level)
        │     └── _estimate_m15_atr              (close-to-close; default 15.0)
        ├── detect_choch(m15, direction)          ← always evaluated
        │     └── _find_recent_fractal_level      ← SHARED ALGORITHM WITH L3 (§7)
        ├── detect_bos(h1, direction)             ← ONLY if choch_confirmed
        └── _assess_sweep_state(m15, level, direction, {**sweep, **choch, **bos})
              └── _estimate_m15_atr               (second call, same statistic)
```

`sweep_detector` is imported by `main_production` and `main.py` only. No other
production module uses it.

---

# 5. Reachability — all 15,735 decisions

| L5 outcome | Count | Share of all |
|---|---|---|
| Never reached (blocked L1–L4) | 8,896 | 56.54 % |
| **PASSED** | **2,764** | 17.57 % |
| **`L5_SWEEP`** (BLOCK) | **2,441** | 15.51 % |
| **`L5_SWEEP_WAIT`** (WATCH) | **1,634** | 10.38 % |
| **`L5_SWEEP_DIRECTION`** | **0** | **0.00 %** |

**Reached L5: 6,839. Total L5 blocks: 4,075 — 59.58 % of those that reach it.**
This reproduces Phase 6O's figure exactly (2,441 + 1,634).

## 5.1 By regime

| Regime | Passed | `L5_SWEEP` | `L5_SWEEP_WAIT` | Reached |
|---|---|---|---|---|
| **MICRO_SCALP** | 1,740 | 1,506 | 1,067 | **4,313 (63 %)** |
| REGIME_SCALP | 765 | 698 | 429 | 1,892 |
| INTRADAY_SWING | 150 | 71 | 31 | 252 |
| DEAD_CALM | 109 | 166 | 107 | 382 |

**MICRO_SCALP supplies 63 % of L5's traffic** — a direct consequence of its L3
bypass (Phase 6O-B §7.1), which routes 4,760 decisions straight to L4/L5.

## 5.2 By side and session

| Side | Reached | Passed | `L5_SWEEP` | `WAIT` | Block rate |
|---|---|---|---|---|---|
| **BUY** | 3,236 | 1,382 | 1,112 | 742 | **57.3 %** |
| **SELL** | 3,603 | 1,382 | 1,329 | 892 | **61.6 %** |

| Session | L5 blocks |
|---|---|
| London | 1,643 |
| Asian | 1,628 |
| NewYork | 614 |
| Dead | 140 |
| Closed | 50 |

---

# 6. Explanation of the 4,075 Blocks

| Reason family | Count | Share |
|---|---|---|
| **A — *"M15 CHoCH not confirmed for {side}"*** (BLOCK) | **2,441** | 59.90 % |
| **B — *"… zone is near liquidity …, waiting for wick/close confirmation"*** (WATCH) | **1,634** | 40.10 % |

**Family A is not what it appears to be.** Because of the `reasoning` key
collision (§1.5), **every** BLOCK reports CHoCH regardless of whether the sweep
also failed. The true statement is: *neither sweep nor CHoCH confirmed, and the
message can only name CHoCH.*

**Family B is the WATCH state:** price sits within
`[−max(2.5, atr·0.20), +max(5.0, atr·0.50)]` of the L4 level — close enough to
be "waiting" rather than rejected. These are not failures of a structural test;
they are a deliberate deferral.

## 6.1 Why CHoCH does not confirm — MEASURED

Sampling every third M15 bar (n = 2,218 windows), applying the production
`_find_recent_fractal_level` and the production comparison:

| Side | Confirmed | close − level (BUY) / level − close (SELL), dollars |
|---|---|---|
| **BUY** | **364 (16.41 %)** | min −118.56 · p25 **−18.94** · median **−10.44** · p75 −3.47 · max 115.23 |
| **SELL** | **388 (17.49 %)** | min −153.83 · p25 **−20.95** · median **−10.78** · p75 −3.35 · max 124.43 |

> **The median decision sits about $10.5 short of the fractal extreme it must
> break.** CHoCH fails because price has not broken structure — a genuine market
> condition, not a tuning artefact. **No threshold change is implied or
> recommended.**

---

# 7. Fractal Duplication Analysis — L3 vs L5

**This was the priority item. The answer is precise.**

| Question | Answer |
|---|---|
| Literally duplicated code? | **Yes.** `sweep_detector._find_recent_fractal_level` and `pullback_detector._find_recent_fractal_swing` share an identical loop `for i in range(len(recent) - 3, 1, -1)` and an identical 5-bar test (`center` vs `l1, l2, r1, r2`) |
| Identical outputs? | **On identical input, yes — 6,652 / 6,652 = 100.00 % agreement** |
| Identical windows? | **No.** L5 re-tails to **25** bars *inside* the routine; L3 does **not** re-tail and receives **49** bars (`tail(50)` minus the dropped newest bar) |
| Identical indexing? | **No.** L5 returns a **value**; L3 returns **`(index, value)`** and its fallback uses `idxmax()` (a label) as a position — safe only because the caller resets the index (Phase 6O-B L3-D11) |
| Have they drifted? | **Yes, in the caller, not the algorithm.** **MEASURED: as called in production they disagree on 909 of 6,652 windows — 13.67 %** — by a median of **$7.15**, p95 **$43.19**, max **$124.46** |

**Two copies of one algorithm, provably equivalent, returning materially
different levels in production because each caller supplies a different window
and one of them silently re-tails.** Nothing in the codebase asserts they agree,
and neither module imports the other.

## 7.1 Is the same price event counted twice?

**No — it is *used* twice, for opposite purposes.**

A single M15 fractal high is read by **L3** as the *origin of a retracement*
(price should fall away from it) and by **L5** as a *level to break* (price
should close above it). **These are mutually opposed conditions on the same
price point.** Passing both means price retraced from the fractal *and* then
closed beyond it — a sequence, not a double count.

**Because L3's and L5's windows differ 13.67 % of the time, they are frequently
not even reasoning about the same fractal.**

**No downstream score inflation results**: `pullback_quality` never reaches L7
(Phase 6O-B §9), and `sweep_quality` reaches L7 as a single component.

---

# 8. Dependency and Double-Counting Analysis

## 8.1 Conditions that can never independently change the result

| # | Condition | Why |
|---|---|---|
| **1** | **`bos_confirmed` in the PASS disjunction** | `detect_bos` is called **only when `choch_confirmed`**, so `bos ⟹ choch`. The `∨ bos` term is **logically implied** by the term beside it |
| **2** | **`L5_SWEEP_DIRECTION` guard** | `detect_sweep(direction=side)` cannot return a sweep of the opposite polarity. **MEASURED: 0 occurrences** |
| **3** | **`tolerance_pips`** | Declared and documented, never referenced |
| **4** | **`setup_grade`** | Stored in `analysis["layer_5"]`; **no gate reads it**. The documented grade→risk mapping is unimplemented |
| **5** | **`l4_override_level`** | Production passes exactly the value already passed as `liquidity_level`, so the override is a no-op |

## 8.2 Shared inputs with other layers

| Layer | Shared with L5 | Independent? |
|---|---|---|
| **L1 bias** | `side` drives `direction` in all three detectors | **Input, not duplication** |
| **L2 structure** | `structure_engine` reads **H1**; `detect_bos` reads **H1** | **Two independent H1 structure notions.** L2 asks "is structure intact", L5 asks "was it broken". **Not reconciled anywhere** |
| **L3 pullback** | **The fractal routine (§7)** | **Duplicated code, opposed use, drifted windows** |
| **L4 liquidity** | `sweep_pool["level"]` **is** L5's `liquidity_level` | **Hard dependency.** L5 cannot be evaluated without L4's choice of pool. A correlated gate: an L4 pool selection error propagates directly |
| **L6 POI** | None | Independent |
| **L7 confidence** | `sweep_quality` → `sweep` component, weighted 0.35 (MICRO_SCALP) / 0.20 / 0.15 | Single use, **but see below** |
| **L8 entry** | `sweep_wick_low` / `sweep_wick_high` → **the stop anchor** | **The sweep wick sets the stop, hence R, hence position size** |
| **Cohesion** | `sweep_norm >= 70` is one of four `strong_components` | **`sweep_quality` is counted twice inside L7** — once as its own weighted component and again inside `cohesion_component` (Phase 6O H1) |

**The one genuine double count is inside L7**, not between L3 and L5: a high
`sweep_quality` raises both `sweep_component` and `cohesion_component`.

**The most consequential coupling is L5 → L8**: `sweep_wick_low/high` becomes
the stop anchor, so `detect_sweep`'s wick — found under a `$2.50–$30.00` depth
band — determines risk distance and therefore lot size.

---

# 9. BUY/SELL Symmetry

Compared mathematically, not asserted.

| Element | BUY | SELL | Mirror? |
|---|---|---|---|
| Sweep depth | `level − low` | `high − level` | **Yes** |
| `sweep_min` / `sweep_max` | identical constants | identical | **Yes** |
| Close test | `close > level` | `close < level` | **Yes** |
| Wick | `level − low` | `high − level` | **Yes** |
| Check 1 | `wick/body ≥ 1.5` | identical | **Yes** |
| Check 2 | `vol ≥ baseline × 1.4` | identical | **Yes** |
| Check 3 | `close_pos > 0.5` | `close_pos < 0.5` | **Yes** — `0.5` fails both |
| Check 4 | next close **>** | next close **<** | **Yes** |
| Confirm | `>= 2` | `>= 2` | **Yes** |
| CHoCH | `close > fractal_high` | `close < fractal_low` | **Yes** |
| CHoCH fallback | `max(high)` | `min(low)` | **Yes** — both unsatisfiable |
| BOS candidates | `highs`, `<= 2.0`, `>= 2` | `lows`, `<= 2.0`, `>= 2` | **Yes** |
| BOS level | `max(candidates)` | `min(candidates)` | **Yes** |
| WATCH distance | `level − min(low, 12)` | `max(high, 12) − level` | **Yes** |
| WATCH buffers | `max(2.5, atr·0.20)`, `max(5.0, atr·0.50)` | identical | **Yes** |

> **No code asymmetry exists in L5. Every constant, inequality, index and
> fallback mirrors exactly.**

**The outcome is asymmetric**, and in the **opposite direction to L3**:

| | BUY blocked | SELL blocked |
|---|---|---|
| **L3** | **47.2 %** | 40.8 % |
| **L5** | 57.3 % | **61.6 %** |

More SELL decisions survive L3 (3,603 vs 3,236 reach L5) and proportionally more
are then blocked at L5. **With the code proven symmetric at both layers, the
cause lies in the inputs — the L1 bias distribution, the L4 pool selection, or
the market itself over a period in which gold rose 18.6 %. This audit did not
establish which, and does not guess. UNRESOLVED.**

---

# 10. Temporal Audit

**Verdict: no confirmed violation. One structural observation, and the worst
test coverage of any audited layer.**

| Question | Answer | Evidence |
|---|---|---|
| Future bars? | **No** | Every frame is cut at `T` by the feed; Phase 6M measured **0 future-bar violations across 15,735 decisions on six timeframes** |
| Future highs/lows? | **No** | All windows are `tail(n)` of an already-cut frame |
| Future fractals? | **No** | Centre `i` requires `i+1`, `i+2`, both inside the cut window; confirmed two bars late |
| **Check 4 reads `recent.iloc[idx + 1]`** | **Not look-ahead** | `idx` addresses a **historical** sweep candle; `idx+1` is a later but **already closed** bar. For the newest bar (`idx == len-1`) the check is skipped |
| Forming bar? | **Not applicable under replay** | The feed supplies only closed bars. **L5 uses `tail(15)` including the newest closed bar — unlike L3, which discards it (Phase 6O-B L3-D6). L5 is the correct one here; L3 is a bar stale** |
| Unclosed higher timeframe? | **No** | `detect_bos` reads H1 through the same cut |
| Ambient clock? | **No** | `sweep_detector` reads no clock; it is correctly absent from `PATCHED_MODULES` |

## 10.1 Test coverage — the finding

> **MEASURED: the string `sweep` appears 0 times in `tests/backtest/test_leakage.py`
> and 0 times in `tests/integration/test_integration_leakage.py`.**

The per-layer future-mutation suite covers **indicators, structure, liquidity,
POI and pullback** — **sweep is the one layer omitted**, and it is the
second-largest gate in the system. **L5 has no temporal test at all.**

This is a **TEST GAP**, not a defect: the property holds by construction of the
feed. But it is unpinned, and a future edit to `detect_sweep` that reached
beyond the frame would not be caught by the leakage suite.

---

# 11. Style / Regime Interaction

| Regime | L5 bypass? | Reached L5 | Passed | Blocked |
|---|---|---|---|---|
| MICRO_SCALP | **No** | 4,313 | 1,740 | 2,573 |
| REGIME_SCALP | **No** | 1,892 | 765 | 1,127 |
| INTRADAY_SWING | **No** | 252 | 150 | 102 |
| DEAD_CALM | **No** | 382 | 109 | 273 |

> **L5 is the only layer with no bypass and no fallback for any regime.**
> L3 has `bypass_l3` (MICRO_SCALP) and a REGIME_SCALP momentum fallback; L6 has
> `bypass_l6` (MICRO_SCALP). **L5 is universally required.**

`regime_info` is never passed to `get_sweep_and_structure`, and no regime name
appears in `sweep_detector.py`. **L5 is entirely regime-blind.**

**The interaction that matters is indirect:** MICRO_SCALP's L3 bypass delivers
4,760 decisions to L4/L5 that would otherwise have been filtered, making
MICRO_SCALP **63 % of L5's traffic** and **63 % of its blocks**. **Whether a
universally-required L5 is correct is not decided here** — see D-6OC-1.

---

# 12. Distribution Analysis

Descriptive only. **No threshold is evaluated for tuning.**

**CHoCH margin (n = 2,218 windows, every third M15 bar):** §6.1.

**Fractal-level disagreement, L3 vs L5 (n = 6,652):** disagree 909 (13.67 %);
median $7.15, p95 $43.19, max $124.46.

**BOS candidate sets (n = 1,641 H1 windows):** empty in **0** — the
unsatisfiable fallback is latent only, unlike CHoCH's (0.22 % / 0.34 %).

**Boundary concentrations and unusual values:**

| Observation | Note |
|---|---|
| `sweep_max = max(30.0, atr·2.0)` | `_estimate_m15_atr` is close-to-close and small, so **the ceiling is effectively the constant $30.00** on every decision — `atr·2.0` would need ATR > $15 to bind |
| `sweep_min = max(2.5, atr·0.12)` | Likewise **effectively the constant $2.50** — `atr·0.12` would need ATR > $20.8 |
| **Consequence** | **The "dynamic XAUUSD range" comment describes a band that is constant in practice: $2.50–$30.00** |
| `checks_passed >= 2` | Checks 1 and 3 are the cheap ones; a wick ≥1.5× body with a close in the favourable half passes without any volume or follow-through |
| `touches >= 2` in BOS | Self-counting makes this "one other H1 bar within $2.00" |

**BUY/SELL distributions** are reported in §5.2 and §6.1 and differ only in
outcome, not in form.

---

# 13. Test Audit

| Test | Exercises L5? | Assessment |
|---|---|---|
| `tests/test_layer_gate_logic.py:72` | **No** — `get_sweep_and_structure` is **mocked** with `{"gate_state": "PASS", …}` | **Vacuous for L5.** It asserts `main_production`'s wiring only. It also supplies `"sweep_type": "bullish"`, a value the real function never returns (it returns `"bullish_sweep"`) — **the mock does not match the contract it stands in for** |
| `tests/backtest/test_leakage.py` | **No** — zero references | **The only layer omitted from the per-layer mutation suite** |
| `tests/integration/test_integration_leakage.py` | **No** — zero references | — |
| `tests/integration/test_real_strategy_replay.py` | Indirectly, through a full replay | Does not assert any L5 property |
| `test_week2_layers_standalone.py` | Calls the real functions | **Root-level, not under `tests/`, not run by `unittest discover -s tests`** |

**There is no test anywhere in the suite that calls `detect_sweep`,
`detect_choch`, `detect_bos` or `get_sweep_and_structure` and asserts a
property of the result.**

| ID | Gap |
|---|---|
| **L5-T1** | **No direct test of any L5 function** |
| **L5-T2** | **No temporal test** — the one layer missing from the mutation suite |
| **L5-T3** | No boundary test at `sweep_min`, `sweep_max`, `checks_passed == 2`, `wick_ratio == 1.5`, `close_pos == 0.5` |
| **L5-T4** | No negative test |
| **L5-T5** | No BUY/SELL pair test |
| **L5-T6** | No test of any fallback — CHoCH's `max/min`, BOS's, `_estimate_m15_atr`'s `15.0`, the exception handlers |
| **L5-T7** | **Nothing pins `L5_SWEEP_DIRECTION`'s unreachability**, so a future edit could silently activate a guard that has never run |
| **L5-T8** | **Nothing asserts the L3 and L5 fractal routines agree** (§7) |
| **L5-T9** | **Nothing detects the `reasoning` key collision** that masks sweep diagnostics |
| **L5-T10** | **False confidence:** `test_layer_gate_logic.py:72`'s mock returns a `sweep_type` the real code cannot produce, so the direction guard is exercised against an impossible value |

---

# 14. Defects

| ID | Defect | Class | Occurrences | Baseline affected? |
|---|---|---|---|---|
| **L5-D1** | Sweep depth band **$2.50–$30.00** vs documented **3–8 pips** | **IMPLEMENTATION DEFECT** (U8 + new ceiling) | Every decision | **Yes** — and it sets the stop anchor |
| **L5-D2** | `checks_passed >= 2` vs documented **3+** | **IMPLEMENTATION DEFECT** | Every confirmed sweep | Yes |
| **L5-D3** | Documented *"Close > Open"* never tested | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L5-D4** | Documented *"close back inside prior range within 1 candle"* replaced by *"next candle continues"* | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L5-D5** | **`reasoning` key collision masks sweep diagnostics** | **IMPLEMENTATION DEFECT** | **All 2,441 blocks** | Diagnostics only |
| **L5-D6** | **BOS gated behind CHoCH** → redundant disjunct | **IMPLEMENTATION DEFECT** | Every decision | No |
| **L5-D7** | **`setup_grade` never read**; documented grade→risk unimplemented | **DEAD** | Every decision | No |
| **L5-D8** | **`L5_SWEEP_DIRECTION` unreachable** | **DEAD** | **0** | No |
| **L5-D9** | **`tolerance_pips` declared, documented, unused** | **DEAD** | Every call | No |
| **L5-D10** | **`l4_override_level` is a no-op** — production passes the same value twice | **DEAD** | Every call | No |
| **L5-D11** | `_estimate_m15_atr` is close-to-close, **not ATR**; silent `15.0` default | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L5-D12** | **Band is "dynamic" in name only** — `max()` floors dominate at all observed ATR | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L5-D13** | `detect_bos` *"within 2 pips"* implemented as **$2.00 = 20 pips** | **IMPLEMENTATION DEFECT** | Every BOS call | No (BOS inert) |
| **L5-D14** | `touches >= 2` **self-counts** | **IMPLEMENTATION DEFECT** | Every BOS call | No |
| **L5-D15** | `detect_choch` implements a **BOS, not a CHoCH**; docstring self-inconsistent | **IMPLEMENTATION DEFECT** | Every decision | Yes — 2,441 blocks |
| **L5-D16** | CHoCH fallback unsatisfiable | **IMPLEMENTATION DEFECT** (latent) | 0.22 % / 0.34 % | Marginal |
| **L5-D17** | BOS fallback unsatisfiable | **IMPLEMENTATION DEFECT** (latent) | **0 of 1,641** | No |
| **L5-D18** | **Fractal routine duplicated; windows drifted — 13.67 % disagreement** | **IMPLEMENTATION DEFECT** | 909 / 6,652 | Yes |
| **L5-D19** | No-sweep message says *"last 10 candles"*; code scans **9** | **IMPLEMENTATION DEFECT** (doc) | Every block | No |
| **L5-D20** | `baseline_volume` from the **whole frame**, sweep from `tail(15)` — mismatched scopes | **INTENT AMBIGUOUS** | Every decision | Yes |
| **L5-D21** | BUY blocked 57.3 % vs SELL 61.6 % with symmetric code | **UNRESOLVED** | — | — |

---

# 15. Ambiguities

| ID | Question |
|---|---|
| **A-6OC-1** | Is the sweep band meant to be dollars or pips? Every other reading in the file (`2.0` in BOS, `tolerance_pips`) suggests the author thought in pips while writing dollars |
| **A-6OC-2** | Should `baseline_volume` be the whole frame or the scan window? (L5-D20) |
| **A-6OC-3** | Is the WATCH state a rejection or a deferral? It ends the decision identically to a block, but its name and reason say otherwise |
| **A-6OC-4** | Should `sweep_quality` feed L7 given it is also inside `cohesion` (§8.2)? |

---

# 16. Design Decisions

| ID | Decision | Why unresolvable from the repository |
|---|---|---|
| **D-6OC-1** | **Should a sweep/CHoCH be required for entry at all?** | **The third question of this phase, deliberately unanswered.** L5 is the only layer with no bypass and no fallback, and **no document states that it should be universal.** MICRO_SCALP bypasses L3 and L6 but not L5 — no source explains why |
| **D-6OC-2** | Should `detect_choch` be a real CHoCH (trend-aware) or be renamed BOS? | Carried from Phase 6O D-6O-1; the docstring is self-inconsistent |
| **D-6OC-3** | Should BOS gate anything, or be removed? | It is computed, inert, and its documented purpose (risk grading) is unimplemented |
| **D-6OC-4** | Should L3 and L5 share one fractal implementation and one window? | §7. **Not to be refactored in this phase** |
| **D-6OC-5** | Should the documented sweep rules (3–8 pips, 3+ checks, close>open, close-back-inside) be implemented, or removed from the specification? | They have been documented and unimplemented since `c3cf4df` |
| **D-6OC-6** | Is WATCH a distinct outcome deserving different downstream handling? | A-6OC-3 |

**None of these is resolved here, and none should be resolved by observing how
many decisions the alternative would admit.**

---

# 17. Items That Should Be Frozen as Correct

**L5's long/short symmetry** — verified element by element (§9), including the
`0.5` close-position boundary that fails both sides. · **L5's temporal
correctness** (§10) — no look-ahead; check 4's `idx+1` reads a closed bar; the
`tail(15)` window correctly **includes** the newest closed bar. · **The 5-bar
fractal geometry** — causal, and **provably identical to L3's on identical
input (6,652/6,652)**. · **The gate reduction `PASS ⟺ sweep ∨ choch`** —
derived from the code and confirmed by 0 `L5_SWEEP_DIRECTION` occurrences. ·
**L5's regime-blindness** — it takes no regime input and applies one rule.

---

# 18. Items That Must Remain Unresolved

**D-6OC-1 … D-6OC-6** and **A-6OC-1 … A-6OC-4**, above — in particular whether
a sweep/CHoCH should be required at all, which must not be settled by trade
count. · **L5-D21**, the BUY/SELL outcome gap, whose cause lies outside L5 and
runs opposite to L3's. · **Every threshold** in §3.2–3.4: `2.5`, `30.0`, `0.12`,
`2.0`, `1.5`, `1.4`, `0.5`, `>= 2`, `8` candles, `15`/`25`/`30`-bar windows,
`12`-bar WATCH window, `0.20`/`0.50` buffers. · **D-6OB-1** (is a pullback
required), **D-6N-1** (regime/session), **U9-RR**, **U10-B** — all untouched.

---

# 19. Classification Summary

| Class | Count | Items |
|---|---|---|
| **VERIFIED** | **5** | Symmetry · temporal correctness · fractal geometry · gate reduction · regime-blindness |
| **IMPLEMENTATION DEFECT** | **12** | L5-D1…D6, D11…D16, D18, D19 *(counted once each)* |
| **INTENT AMBIGUOUS** | **4** | A-6OC-1 … A-6OC-4 |
| **DEAD / NON-PRODUCTION** | **4** | L5-D7, D8, D9, D10 |
| **TEST GAP** | **10** | L5-T1 … L5-T10 |
| **DESIGN DECISION** | **6** | D-6OC-1 … D-6OC-6 |
| **TEMPORAL RISK** | **0 confirmed** | Coverage gap only (L5-T2) |
| **UNRESOLVED** | **1** | L5-D21 |

**Total L5 components classified: 42.**

---

# 20. Exact Next Audit Target

> **Audit L4 — `liquidity_engine.identify_liquidity_pools` and
> `assess_liquidity_gate` — documentation-only.**

**Why L4 and not a fix.** L5 cannot be evaluated without L4: `liquidity_level`
**is** `sweep_pool["level"]`, and every L5 outcome — the sweep band, the WATCH
distance, the stop anchor that reaches L8 — is measured **relative to a level L4
chose**. §8.2 records this as a hard dependency and a correlated gate. Auditing
L5's thresholds before knowing how the level is selected would measure the wrong
thing.

L4 is also the last unaudited gate on the main path (629 blocks) and is already
implicated: `PHASE_2_ISSUES` records *"`tp_pool` validated then discarded"*
(117/117) and *"U2/U3/U4 — liquidity distance thresholds in price units"*.

After L4: **L1 bias** (2,392 blocks, `bias_engine`, still unaudited), then pin
L3/L5 behaviour in tests, **then** decide D-6N-1, **then** U9-RR.

**Do not implement any L5 change, do not refactor the duplicated fractal, do not
alter a threshold, and do not resolve D-6OC-1 or U9-RR until L4 is audited.**

---

# 21. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| Duplicated code | **Not refactored** |
| Parameters / thresholds | **Untouched** |
| Regime / session architecture | **Untouched** |
| U9-RR | **Not resolved** |
| Baselines and R1 fixtures | **Read only** |
| "More passes" treated as better | **No** — §6.1 states the CHoCH margin is a market condition and declines to imply a threshold change |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
