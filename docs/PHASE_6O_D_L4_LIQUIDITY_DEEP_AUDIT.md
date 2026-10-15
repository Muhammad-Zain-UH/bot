# Phase 6O-D — L4 Liquidity / Sweep-Pool Deep Audit

**Audit only. No source changed.** No threshold, no refactor, no strategy
optimisation, no regime/session change. U9-RR is not resolved. `baseline_004`,
`baseline_005` and the R1 fixtures were read, never written.

**Input:** commit `1242d4f` (Phase 6O-C). Statistics come from the **frozen**
`baselines/baseline_005/decisions.jsonl` (15,735 records) and the frozen dataset
`433b7e27…`.

---

# 1. Executive Summary

**The question this phase had to answer was whether L4's level is a meaningful
liquidity reference or simply a convenient nearby price. The evidence says the
second, and it says so from four independent directions.**

1. **Selection is by distance, not strength.** `_rank_directional_pool` returns
   `(distance, -score, tier_rank)` and the winner is `min(...)`, so score is only
   a tiebreaker on exactly-equal distance — which never happens in floating
   point. **MEASURED: the selected pool is the highest-scoring candidate only
   26.9 % of the time; the median selected pool ranks 3rd by score, worst
   observed 10th, out of a median 11 candidates.** The entire documented scoring
   formula, tier system and `<60 → Reject` rule survive only as a coarse
   pre-filter.

2. **That pre-filter disables itself.** `above_candidates = [p … if score >= 60]
   **or** above_pools` — when nothing scores 60, **every** pool becomes eligible.
   **MEASURED: this happens in 10.7 % of decisions.**

3. **"Equal highs/lows within ±1.5 pips" is neither.** `tolerance_pips = 1.5` is
   compared against raw dollar prices, so the real tolerance is **$1.50 = 15
   pips — 10× the documented value**. Worse, `_cluster_price_points` is
   **single-linkage against the previous point**, so clusters chain without
   bound. **MEASURED: 54.1 % of "equal" levels span more than the $1.50
   tolerance; median width $1.74, p95 $14.02, maximum $44.07. One level was
   touched by all 100 bars in the window.** A level $44 wide is not a level.

4. **For a BUY, 38.3 % of selected sweep pools are `equal_high` clusters.**
   Selection filters on `level < current_price` and **never on pool type**, so
   the downside liquidity a BUY intends to sweep is, more than a third of the
   time, a cluster of *highs*.

**Three further results.**

- **`liquidity_engine.py` has exactly one commit — `c3cf4df`, 2026-07-01 — and
  is byte-identical to HEAD.** As with `sweep_detector.py`. L3, L4 and L5 all
  originate in that single commit; only L3 has ever been modified, once.

- **L4 is the least binding gate on the main path: 629 blocks of 7,468 reached,
  8.42 %.** The binding term is `tp_score < 60` (72.3 %), not the sweep pool
  (31.3 %); the `max_sweep_distance = 60.0` test binds in **3 cases (0.5 %)**.
  **Median selected-sweep distance is $3.20.**

- **`L4` is the only gate audited so far that is symmetric in outcome as well as
  in code: BUY 8.4 %, SELL 8.4 %.**

**The consequence for L5 is direct.** L5's sweep band starts at **$2.50** and
L4's median sweep level sits **$2.61–$3.20** from price. L5 is asked to validate
"was this level swept" about a level chosen for being *close*, whose own width
routinely exceeds the sweep depth being measured.

---

# 2. Historical Intent Timeline

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | **`c3cf4df`** | **File created.** |
| — | — | **No further commits.** `git diff c3cf4df HEAD -- liquidity_engine.py` is **empty** |

There are no later modifications, no removed conditions and no renamed concepts
to trace. **Every contradiction below is original.**

### 2.1 Documented vs implemented — the five pool types

| # | Documented | Implemented? |
|---|---|---|
| 1 | **EQUAL LOWS / HIGHS** — *"Same level touched 2+ times (**±1.5 pips** tolerance)"*, base 15 | **Partly.** Base 15 ✓; tolerance is **$1.50**, and single-linkage chaining makes the cluster unbounded (§5) |
| 2 | **ASIAN SESSION EXTREME**, base 20 | **Yes** |
| 3 | **PREVIOUS DAY EXTREME** (PDH/PDL), base 15 | **Yes** |
| 4 | **RECENT SWING LOW/HIGH** — *"Last 20 M15 candles … untested"*, base 20 − age | **NO. Never constructed.** `pool_type="swing_low"/"swing_high"` is scored at `liquidity_engine.py:296` and **passed by no caller** — a dead branch |
| 5 | **ROUND NUMBERS** — *"25-**pip** round numbers"*, base 10 | **Yes**, but they are **$25 = 250 pips**, and the `range_pips=100` filter is inert (§11) |
| — | *(undocumented)* | **`h1_level` and `h4_level` are produced** and fall to the `else: score = 10` bucket. **They appear in no documentation** |

### 2.2 Documented vs implemented — scoring and tiers

The scoring formula (base + touches×15 + round+20 + HTF+25 + recency+10 +
volume+10, capped 100) and the tiers (S 80-100 / A 70-79 / B 60-69 / Reject <60)
**are implemented as written**.

**But they do not select the level (§1.1), and the Reject rule is bypassed
whenever no pool qualifies (§1.2).** *"Reject (<60): Skip this pool"* is
therefore not a property of the system.

**Can the current implementation be historically justified? No.** One version of
the code, one version of the specification, contradicting on the tolerance, one
whole pool type, the round-number unit, and the meaning of the tier system.

---

# 3. The Exact L4 Contract

## 3.1 Pipeline

```
identify_liquidity_pools(m15, h1, h4, daily, current_price, side)
  ├── find_equal_levels(m15, tolerance_pips=1.5, lookback=100)     → equal_high / equal_low
  ├── find_asian_extremes(m15)                                     → asian_high / asian_low
  ├── find_previous_day_extremes(daily)                            → pdh / pdl
  ├── find_round_numbers(current_price, range_pips=100)            → round_number
  ├── h1 / h4 reference levels                                     → h1_level / h4_level
  │      each → score_liquidity_pool(...) → {level, score, tier, pool_type, …}
  ├── de-duplicate → unique_pools
  ├── unique_pools.sort(key=score, reverse=True)   → top_3, recommendation   [DIAGNOSTIC ONLY]
  └── directional selection ──────────────────────────────────────────────────┐
        above_pools = [level > price] ; below_pools = [level < price]         │
        above_candidates = [score >= 60] OR above_pools    ← self-disabling   │
        BUY : sweep = min(below_candidates, key=rank) ; tp = min(above…)      │
        SELL: sweep = min(above_candidates, key=rank) ; tp = min(below…)      │
        rank(pool) = (distance, -score, tier_rank)          ← DISTANCE FIRST  │
assess_liquidity_gate(sweep_pool, tp_pool, current_price, side) ──────────────┘
  ├── missing price/side          → BLOCK
  ├── missing sweep or tp pool    → BLOCK            [0 occurrences]
  ├── directional re-check        → BLOCK            [DEAD — 0 occurrences, §12]
  ├── sweep>=70 ∧ tp>=60 ∧ dist<=60   → PASS
  ├── sweep>=40 ∧ tp>=55 ∧ dist<=75   → WATCH        ← treated as PASS downstream
  └── otherwise                       → BLOCK
```

`main_production.py:852-857` blocks **only** on `BLOCK`. **WATCH proceeds**,
contradicting its own docstring (*"should not be treated like a confirmed
liquidity target yet"*).

## 3.2 Parameters

| Element | Value | Unit as used |
|---|---|---|
| Source timeframe | **M15**, plus H1/H4/D1 references | — |
| Lookback | `tail(100)` M15 bars for equal levels | bars |
| Cluster tolerance | `1.5` | **dollars** (documented pips) |
| Merge tolerance | `1.5` | **dollars** |
| HTF confluence tolerance | `2.0` | **dollars** (`_htf_confluence_strength`) |
| Round-number spacing | `25` | **dollars** (documented "25-pip") |
| Round-number range | `100` | **dollars**; **inert** (§11) |
| `min_sweep_score` | **70** always — `is_fallback` is never true | points |
| `min_tp_score` | 60 | points |
| `max_sweep_distance` | **60.0** always | **dollars** |
| `watch_sweep_score` | `max(40, 70-30)` = **40** | points |
| `watch_tp_score` | 55 | points |
| `watch_distance` | `60 × 1.25` = **75.0** | dollars |
| Candidate pre-filter | `score >= 60`, **or all pools if none qualify** | points |

**Swing/fractal construction: none.** Unlike L3 and L5, L4 builds no fractals.
Equal levels are computed from **every bar's** high and low, not from swing
points.

---

# 4. Full Level-Provenance Chain

```
M15 bars (100)                                    ← every bar, not swings
  → (index, high) and (index, low) for ALL bars
  → sort by price
  → SINGLE-LINKAGE chain: keep adding while gap-to-PREVIOUS <= $1.50
  → clusters with >= 2 members                    ← may span $44 (measured)
  → level = arithmetic MEAN of the cluster
  → merge same-type clusters within $1.50 → level = (a+b)/2
  → score_liquidity_pool(...)  → score, tier      ← DOES NOT SELECT
  → de-duplicate → unique_pools
  → split by side of current_price
  → pre-filter score>=60, OR everything if none qualify   ← 10.7% bypass
  → min(candidates, key=(DISTANCE, -score, tier)) ← NEAREST WINS
  → sweep_pool["level"]
      → assess_liquidity_gate thresholds (70/60/$60)
      → L5 liquidity_level and l4_override_level
          → detect_sweep band [$2.50, $30.00] around it
          → _assess_sweep_state WATCH distance around it
          → sweep_wick_low / sweep_wick_high
              → L8 _select_stop_anchor  → stop, R, lot size, target, rr
```

**Eleven transformations from raw price to the stop.** The level that
ultimately sets position size is the mean of a single-linkage price chain,
chosen for proximity.

---

# 5. Equal Highs / Equal Lows

**MEASURED over 942 rolling 100-bar M15 windows.**

| Quantity | Result |
|---|---|
| Equal-levels per window | median **20**, p95 36, max **49** |
| Touches per level | median 4, p75 9, p95 **39**, max **100** |
| **Cluster width (max − min of member prices)** | median **$1.74**, p75 **$4.17**, p95 **$14.02**, max **$44.07** |
| **Width exceeds the $1.50 tolerance** | **54.1 % of levels** |
| Width exceeds $10.00 | 8.4 % |
| Width exceeds $25.00 | 0.7 % |

**The tolerance is price-based, not pip-, ATR- or percentage-based**, and it is
symmetric (the same `1.5` for highs and lows).

**It is not clustered correctly.** `_cluster_price_points` compares each point to
`current[-1]` — the **last point added** — so a chain of prices each within $1.50
of its predecessor forms one cluster of unbounded width. **The median cluster is
already wider than the tolerance that defines it, and 54.1 % exceed it.**

**Can the algorithm select arbitrary levels? Yes, demonstrably.** A level with
**100 touches** means all 100 bars' lows chained into a single "equal low". That
level's price is the mean of the whole window — a moving average, not liquidity.

**Do equal highs/lows occur often enough to matter?** They are the dominant
input: **87.0 % of selected BUY sweep pools are `equal_low` (48.7 %) or
`equal_high` (38.3 %)**.

---

# 6. Relationship to the Sweep Detector (L5)

| Dimension | L4 | L5 `detect_sweep` |
|---|---|---|
| Concept of liquidity | Clustered highs/lows + session/day extremes + round numbers | **None.** It receives a level |
| Source | Every bar's high/low, single-linkage | n/a |
| Fractals | **None** | `detect_choch` uses a 5-bar fractal |
| Timeframe | M15 (100 bars) + H1/H4/D1 | M15 (last 15, scans 9) |
| Tolerance | **$1.50** cluster | **$2.50–$30.00** sweep band |
| Can one generate levels the other cannot? | **L4 generates all levels; L5 generates none** | — |

**Can L5 meaningfully validate the L4 level? Only weakly, and the numbers
explain why.**

L5 asks whether a wick penetrated the level by **$2.50–$30.00** and closed back
across it. L4 supplies a level whose **median distance from price is $3.20** and
whose **own width is a median $1.74 and p95 $14.02**. The level's uncertainty is
of the same order as the penetration being measured; at p95 the cluster is
**wider than the $2.50 minimum sweep by a factor of five**.

**They do not share a concept, a source, a tolerance or a window.** L5 validates
a number, not a liquidity hypothesis.

---

# 7. Reachability — all 15,735 decisions

| L4 outcome | Count | Share |
|---|---|---|
| Never reached (blocked L1–L3) | 8,267 | 52.54 % |
| **PASSED** (PASS or WATCH) | **6,839** | 43.46 % |
| **BLOCKED** | **629** | 4.00 % |

**Reached L4: 7,468. Block rate: 8.42 % — the least binding gate on the path.**

**A liquidity level was produced in every reached decision**: zero blocks cite
*"Missing sweep pool or TP pool"*.

| Regime | Reached | Blocked | Passed |
|---|---|---|---|
| MICRO_SCALP | 4,760 | 447 | 4,313 |
| REGIME_SCALP | 1,996 | 104 | 1,892 |
| INTRADAY_SWING | 302 | 50 | 252 |
| DEAD_CALM | 410 | 28 | 382 |

| Side | Reached | Blocked | Rate |
|---|---|---|---|
| **BUY** | 3,534 | 298 | **8.4 %** |
| **SELL** | 3,934 | 331 | **8.4 %** |

**All 6,839 passing decisions carry an L4 level into L5**, and every one of the
2,764 that pass L5 carries it into L8's stop construction.

## 7.1 Why the 629 block

All 629 are the threshold branch. **MEASURED:**

| Threshold | Fails in |
|---|---|
| `tp_score < 60` | **455 (72.3 %)** |
| `sweep_score < 70` | 197 (31.3 %) |
| `sweep_distance > 60.0` | **3 (0.5 %)** |

| Quantity in blocked decisions | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| `sweep_score` | 32 | 32 | **85** | 100 | 100 |
| `tp_score` | 26 | 33 | **41** | 85 | 100 |
| `sweep_distance` ($) | 0.01 | — | **3.20** | 7.27 | 88.59 |

> **L4 does not mostly reject on the sweep side. It rejects because the *target*
> pool scores below 60 — a pool that plays no part in sweep detection at all.**

---

# 8. Pool Selection — Nearest, not Strongest

**MEASURED over 394 sampled decisions (BUY side).**

| Quantity | Result |
|---|---|
| Candidate pools below price | median **11**, p95 20, max 27 |
| **Selected pool is rank 1 by score** | **26.9 %** |
| Selected pool's median rank by score | **3rd** |
| Worst observed rank selected | **10th** |
| Distance of selected pool | median **$2.61**, p75 $5.10, max $83.65 |
| **`score >= 60` pre-filter self-disabled** | **10.7 %** |

**If selection were by strength, rank 1 would be 100 %.** It is 26.9 %, which is
approximately what proximity alone would produce.

### 8.1 Pool-type mix of the selected BUY sweep pool

| Type | Share |
|---|---|
| `equal_low` | 48.7 % |
| **`equal_high`** | **38.3 %** |
| `round_number` | 9.6 % |
| `asian_low` | 2.3 % |
| `pdl` | 0.5 % |
| `h4_level` / `h1_level` | 0.3 % each |

**For a BUY the sweep pool is meant to be resting sell-side liquidity — stops
below support. 38.3 % of the time it is a cluster of highs.** Selection tests
`level < current_price` and never the pool's own type or polarity.

**Selection rule classification: deterministic, nearest-first, and
undocumented** — the docstring says *"Prefer nearest valid pools, then higher
score"*, which is accurate but appears only as an inner-function docstring, and
the module header describes a scoring/tier system that implies the opposite.

---

# 9. Downstream Impact

| Consumer | Dependence on the L4 level |
|---|---|
| **L5 `detect_sweep`** | `liquidity_level` **and** `l4_override_level` are both this value. The entire $2.50–$30.00 band is measured from it |
| **L5 `_assess_sweep_state`** | The WATCH distance is measured from it — 1,634 `L5_SWEEP_WAIT` blocks |
| **L5 `detect_choch`** | **Independent** — uses its own M15 fractal |
| **L5 `detect_bos`** | **Independent** — H1 |
| **L8 stop anchor** | `sweep_wick_low`/`sweep_wick_high` come from the sweep candle found *relative to this level* → `_select_stop_anchor` |
| **Risk / sizing** | stop → `risk_distance` → `lots_for_risk` |
| **Target / RR** | `take_profit = entry ± risk_distance × tp_ratio`; RR is tautological but the **money value** of R depends on the stop, hence on this level |

**Logically dependent gates:** L5's sweep confirmation and WATCH state, and L8's
stop construction. **Not dependent:** L5 CHoCH and BOS, L6 POI, L7 confidence
(no L4 term enters `final_score`), and the L8 trigger itself.

**The single most consequential path is L4 → L5 wick → L8 stop → lot size.**

---

# 10. Temporal Audit

**Verdict: no confirmed violation, and L4 has genuine temporal coverage.**

| Question | Answer |
|---|---|
| Future bars? | **No** — every frame cut at `T`; Phase 6M measured 0 violations across 15,735 decisions on six timeframes |
| Future swing points / equal highs? | **No** — `tail(100)` of an already-cut frame |
| Future liquidity? | **No** — H1/H4/D1 references come through the same cut |
| Forming bar? | **Not under replay** — the feed supplies only closed bars. L4 uses `tail(100)` **including** the newest closed bar, consistent with L5 and **unlike L3** |
| Future confirmation? | **No** — pools are scored on past touches only |
| Ambient clock? | **No** — `liquidity_engine` reads no clock and is correctly absent from `PATCHED_MODULES` |

**Test coverage: `tests/backtest/test_leakage.py:211 test_liquidity_is_unchanged`
calls the real `identify_liquidity_pools` under a post-cutoff mutation and
asserts the full result is unchanged.** This is a genuine temporal test — **but
BUY only**.

**Latent risks: none identified. Zero-occurrence risks: none identified.**

---

# 11. Unit Audit

**Every parameter named `_pips` in this file is compared against dollar prices.**

| Site | Name | Compared to | Real unit | Documented |
|---|---|---|---|---|
| `_cluster_price_points:75` | `tolerance_pips` | `point[1] - current[-1][1]` | **$1.50 = 15 pips** | *"±1.5 pips"* → **10×** |
| `find_equal_levels:132` | `tolerance_pips` | `abs(level_a - level_b)` | **$1.50** | same |
| `_htf_confluence_strength:173` | `tolerance_pips=2.0` | `abs(level - ref)` | **$2.00 = 20 pips** | undocumented |
| `find_round_numbers:233` | `range_pips=100` | `abs(level - price)` | **$100 = 1000 pips** | *"within range_pips"* |
| `find_round_numbers:229` | `25` spacing | price | **$25 = 250 pips** | *"25-pip increments"* → **10×** |
| `assess_liquidity_gate:754` | `max_sweep_distance` | `abs(level - price)` | **$60 / $100** | unlabelled |

**`find_round_numbers`'s range filter is inert.** Candidates lie at
`base_round ± {0, 25, 50}` and price lies within `[base_round, base_round+25)`,
so the greatest possible distance is **$75 < $100**. **The filter never excludes
anything.**

This is the same defect family as U1, U8, U9-H1 and U10-A, and it is **more
systematic here than anywhere audited so far**: six sites, one file, all
original.

---

# 12. Dead / Inert Logic

| # | Item | Evidence |
|---|---|---|
| **1** | **`swing_low` / `swing_high` pool type** | Scored at `:296`, **passed by no caller**. Documented pool type #4 is never constructed |
| **2** | **Directional re-check in `assess_liquidity_gate`** (FIX #2) | Selection already guarantees the side. **MEASURED: *"directional error"* appears 0 times in 15,735** |
| **3** | **`is_fallback` branch** | No `pool_type` contains `"fallback"`, so `min_sweep_score` is always 70 and `max_sweep_distance` always 60.0. The 60/100 pair is unreachable |
| **4** | **`range_pips` filter in `find_round_numbers`** | Never excludes a candidate (§11) |
| **5** | **`max_sweep_distance = 60.0`** | Binds in **3 of 629 blocks (0.5 %)** |
| **6** | **`tier_rank` in `_rank_directional_pool`** | Third key after distance and score; reachable only on an exact two-way tie |
| **7** | **`top_3_pools`, `recommendation`** | Returned; **no production consumer** |
| **8** | **`score_breakdown`** | Computed per pool; never read by a gate |
| **9** | **The S/A/B tier system** | Affects only the `>= 60` pre-filter, which self-disables 10.7 % of the time |
| **10** | **`get_liquidity_pools` wrapper** | Defined at `:808`; `main_production` calls `identify_liquidity_pools` directly |
| **11** | **L4 `WATCH` as a distinct state** | `main_production` blocks only on `BLOCK`; WATCH is indistinguishable from PASS downstream |

**None removed, as instructed.**

---

# 13. Test Audit

| Test | Exercises L4? | Assessment |
|---|---|---|
| `test_leakage.py:211 test_liquidity_is_unchanged` | **Yes** — real function, future-mutation | **The only genuine L4 test. BUY only** |
| `tests/test_layer_gate_logic.py` | **No** — L4 reached only incidentally; no L4 assertion | — |
| `tests/integration/test_real_strategy_replay.py` | Indirectly, via full replay | No L4 property asserted |
| **`tests/core/test_types.py:353-358`** — `test_liquidity_level_score_bounds`, `test_liquidity_level_distance_is_typed` | **No** | **FALSE CONFIDENCE.** These test `core.types.LiquidityLevel`, a canonical dataclass **imported by no production module** — only by `core/types.py` and its own tests. A reader scanning for "liquidity level score" tests would believe L4's scoring is covered. It is not |

| ID | Gap |
|---|---|
| **L4-T1** | **No test of `find_equal_levels`** — no boundary, no clustering-width, no chaining case |
| **L4-T2** | **No test of `_cluster_price_points`** — the single-linkage behaviour is unpinned |
| **L4-T3** | **No test of the selection rule** — nothing asserts nearest-wins, so a change to strongest-wins would pass silently |
| **L4-T4** | **No test of the self-disabling `>= 60` pre-filter** |
| **L4-T5** | **No SELL test anywhere** — the only real test is BUY only |
| **L4-T6** | **No no-liquidity / empty-pool test** |
| **L4-T7** | **No multiple-candidate test** |
| **L4-T8** | **No unit test** — nothing would catch `tolerance_pips` being dollars |
| **L4-T9** | **Nothing pins the directional re-check's unreachability** (item 2) |
| **L4-T10** | **Nothing asserts a BUY sweep pool is a low-side pool type** — the 38.3 % `equal_high` result is unpinned |

---

# 14. Defects

| ID | Defect | Class | Occurrences | Baseline affected? |
|---|---|---|---|---|
| **L4-D1** | `tolerance_pips=1.5` applied as **$1.50** — 10× documented | **IMPLEMENTATION DEFECT** | Every decision | **Yes** |
| **L4-D2** | **Single-linkage chaining** — 54.1 % of levels exceed their own tolerance; max width **$44.07**; one level with **100 touches** | **IMPLEMENTATION DEFECT** | Every decision | **Yes** |
| **L4-D3** | Equal levels built from **every bar**, not swing points | **INTENT AMBIGUOUS** | Every decision | Yes |
| **L4-D4** | **Selection is nearest, not strongest** — rank 1 only 26.9 % | **INTENT AMBIGUOUS** | Every decision | **Yes** |
| **L4-D5** | **`>= 60` pre-filter self-disables** — the documented Reject tier is not a property of the system | **IMPLEMENTATION DEFECT** | **10.7 %** | Yes |
| **L4-D6** | **BUY sweep pool is an `equal_high` 38.3 % of the time** — no type/polarity check | **IMPLEMENTATION DEFECT** | 38.3 % | **Yes** |
| **L4-D7** | Documented pool type **RECENT SWING never constructed** | **DEAD** | Every decision | Yes |
| **L4-D8** | **`h1_level`/`h4_level` undocumented**, scored in the `else` bucket at 10 | **IMPLEMENTATION DEFECT** (doc) | Every decision | Yes |
| **L4-D9** | `_htf_confluence_strength` tolerance **$2.00**, unlabelled | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L4-D10** | Round numbers are **$25**, documented *"25-pip"*; `range_pips=100` inert | **IMPLEMENTATION DEFECT** | Every decision | Marginal |
| **L4-D11** | **Directional re-check (FIX #2) unreachable** | **DEAD** | **0** | No |
| **L4-D12** | **`is_fallback` never true** — 60/100 thresholds unreachable | **DEAD** | **0** | No |
| **L4-D13** | **`max_sweep_distance = 60.0` near-inert** | **IMPLEMENTATION DEFECT** | 3 of 629 | Marginal |
| **L4-D14** | **WATCH is treated as PASS downstream**, contradicting its docstring | **IMPLEMENTATION DEFECT** | Unmeasured | Yes |
| **L4-D15** | **`tp_score` is the dominant rejection term (72.3 %)** though the TP pool plays no part in sweep detection | **INTENT AMBIGUOUS** | 455 of 629 | Yes |
| **L4-D16** | `top_3_pools`, `recommendation`, `score_breakdown`, `get_liquidity_pools` unconsumed | **DEAD** | Every decision | No |

---

# 15. Ambiguities

| ID | Question |
|---|---|
| **A-6OD-1** | Should the tolerance be pips, dollars, ATR-relative or percentage? Every `_pips` name in the file says pips; every comparison says dollars |
| **A-6OD-2** | Should clustering be single-linkage, complete-linkage, or width-capped? |
| **A-6OD-3** | Should equal levels be built from swing points rather than every bar? |
| **A-6OD-4** | Should a BUY's sweep pool be restricted to low-side pool types? |
| **A-6OD-5** | Is WATCH a distinct outcome, given it currently passes? |
| **A-6OD-6** | Should `tp_score` gate entry at all, given it does not participate in sweep detection? |

---

# 16. Design Decisions

| ID | Decision |
|---|---|
| **D-6OD-1** | **Should the L4 level be selected by proximity or by strength?** This is the central question. The module documents a scoring and tier system; the code selects by distance. **Neither is recoverable as intent — there is one commit and it contains both.** |
| **D-6OD-2** | Should the documented Reject-below-60 rule be enforced rather than self-disabling? |
| **D-6OD-3** | Should the RECENT SWING pool type be implemented or removed from the specification? |
| **D-6OD-4** | Should `h1_level`/`h4_level` be documented and scored explicitly? |
| **D-6OD-5** | Should L4 and L5 share one notion of level width, given L4's cluster width (p95 $14.02) exceeds L5's minimum sweep depth ($2.50)? |
| **D-6OD-6** | **Is a liquidity sweep the right entry premise at all**, given the level is chosen for proximity? *(Related to D-6OC-1; both left open.)* |

**None resolved here. None should be resolved by counting how many decisions
the alternative would admit.**

---

# 17. Items Safe to Freeze

**L4's long/short symmetry** — verified element by element in §18, and **uniquely
among the audited gates it is symmetric in outcome too (8.4 % / 8.4 %)**. ·
**L4's temporal correctness** (§10) — no look-ahead, and pinned by a real
future-mutation test on the production function. · **The `tail(100)` window
including the newest closed bar** — consistent with L5, and correct. ·
**Determinism** — no clock, no randomness, pure function of the frames and price.
· **The scoring formula and tier boundaries as implementations of their own
documented arithmetic** (they compute what the header says; they merely do not
select).

---

# 18. BUY/SELL Symmetry

| Element | BUY | SELL | Mirror? |
|---|---|---|---|
| Equal-level construction | shared code, both columns | shared | **Yes** |
| Cluster tolerance | `1.5` | `1.5` | **Yes** |
| Side split | `level < price` | `level > price` | **Yes** |
| Sweep selection | `min(below_candidates)` | `min(above_candidates)` | **Yes** |
| TP selection | `min(above_candidates)` | `min(below_candidates)` | **Yes** |
| Rank key | `(distance, -score, tier)` | identical | **Yes** |
| Pre-filter | `>= 60 or all` | identical | **Yes** |
| Gate thresholds | 70 / 60 / 60.0 | identical | **Yes** |
| Directional re-check | `sweep < price` | `sweep > price` | **Yes** (both dead) |
| Fallback on exception | `None` | `None` | **Yes** |

> **No code asymmetry, and — unlike L3 and L5 — no outcome asymmetry either:
> BUY 8.42 %, SELL 8.42 %.**

This is informative for the unresolved L3/L5 asymmetries: **the layer that
consumes price levels symmetrically produces symmetric outcomes**, which makes an
upstream cause (L1 bias distribution, or the market itself) more likely than a
hidden L3/L5 code path. **Still not established. UNRESOLVED.**

---

# 19. Classification Summary

| Class | Count | Items |
|---|---|---|
| **VERIFIED** | **5** | Symmetry (code **and** outcome) · temporal correctness · window choice · determinism · scoring arithmetic |
| **IMPLEMENTATION DEFECT** | **10** | L4-D1, D2, D5, D6, D8, D9, D10, D13, D14 + `find_round_numbers` inert filter |
| **INTENT AMBIGUOUS** | **4** | L4-D3, D4, D15 + A-6OD-5 |
| **DEAD / NON-PRODUCTION** | **4** | L4-D7, D11, D12, D16 |
| **TEST GAP** | **10** | L4-T1 … L4-T10 |
| **DESIGN DECISION** | **6** | D-6OD-1 … D-6OD-6 |
| **TEMPORAL RISK** | **0** | None identified — latent or otherwise |
| **UNRESOLVED** | **1** | The L3/L5 outcome asymmetry, now narrowed (§18) |

**Total L4 components classified: 40.**

---

# 20. Items That Must Remain Unresolved

**D-6OD-1 … D-6OD-6** and **A-6OD-1 … A-6OD-6**, above — above all whether the
level should be nearest or strongest, which must not be settled by trade count. ·
**Every threshold** in §3.2: `1.5`, `2.0`, `25`, `100`, `70`, `60`, `60.0`, `40`,
`55`, `1.25`, `lookback=100`. · **D-6OC-1** (is a sweep required),
**D-6OB-1** (is a pullback required), **D-6N-1** (regime/session),
**U9-RR**, **U10-B** — all untouched.

---

# 21. Exact Next Audit Target

> **Audit L1 — `bias_engine.get_h4_bias` and `get_fast_bias` — documentation-only.**

**Why L1 now.** It is the **last unaudited gate on the main path** and the
largest remaining: **2,392 blocks, 15.2 %**, and it is the **only layer every one
of the 15,735 decisions reaches**. It is also the most likely home of the
unresolved BUY/SELL asymmetry: §18 shows L4 is symmetric in both code and
outcome, which points upstream, and **L1 is what decides `side`** for every
downstream layer — including `expected_bias` in L3 and `direction` in L4 and L5.

After L1: **L2** (`structure_engine`, 7 blocks) and **L6** (`poi_engine`, 1
block) are small but complete the map. Then pin L3/L4/L5 behaviour in tests,
**then** decide D-6N-1, **then** U9-RR.

**Do not implement any L4 change, do not refactor the clustering, do not alter a
threshold, and do not resolve D-6OD-1 or U9-RR until L1 is audited.**

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
| Trade count used as evidence of correctness | **No** |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
