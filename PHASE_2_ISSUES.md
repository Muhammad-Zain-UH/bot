# PHASE 2+ ISSUE REGISTER

Defects identified during the Phase 1 audit and confirmed during Phase 0/1
implementation.

## STATUS: the production freeze has been LIFTED

Items below are now being fixed. Each fixed item is marked inline; the original
description is kept verbatim so the record of what was wrong survives the fix.

What has **not** changed:

* No threshold has been selected by backtest performance, trade count or win
  rate. Fixes target each item's **documented intent** -- pips where the name
  says pips, a gate that can fail, a balance that comes from the broker.
* `baselines/baseline_004` and `baseline_008` remain **byte-identical frozen**.
  Their manifests record what was true when they were created, including the
  then-current R1 sizing defect. They are historical records and are not
  rewritten when a defect is fixed.
* FINAL_OOS remains LOCKED.

The original warning still applies to anything that *is* a tuning decision:
without a measured baseline, a change that increases trade count is
indistinguishable from a change that increases losses. See the measurement
constraint recorded at the end of section 11.

Legend — P0 critical · P1 high · P2 medium · P3 low

---

## 1. UNIT CONFUSION (price units vs pips)

The single most widespread defect class. `core/units.py` now makes the correct
form expressible; these call sites have **not** been migrated.

XAUUSD: 1 pip = $0.10 = 10 points. A threshold named "pips" but applied to a raw
price is therefore **10x** its intended size.

| # | Location | Code | Intended | Actual | Priority |
|---|---|---|---|---|---|
| U1 | `entry_engine.py:362` `_select_stop_anchor` | ~~`min(candidates) - buffer_pips` (`buffer_pips=3.0`)~~ **FIXED.** Typed `STOP_ANCHOR_BUFFER_PIPS = Pips(3.0)`, resolved through the spec to $0.30. | 3 pips | ~~$3.00~~ **$0.30** | ~~P0~~ |
| U2 | `liquidity_engine.py:368` `score_liquidity_pool` | ~~`if distance <= 2.0`~~ **FIXED.** `PROXIMITY_BONUS_PIPS = Pips(2.0)` -> $0.20. | 2 pips | ~~$2.00~~ **$0.20** | ~~P1~~ |
| U3 | `liquidity_engine.py:374-380` | ~~`if distance > 50 / > 30`~~ **FIXED.** Typed `Pips(50)` / `Pips(30)` -> $5.00 / $3.00. | 50/30 pips | ~~$50/$30~~ **$5/$3** | ~~P1~~ |
| U4 | `liquidity_engine.py:753` `assess_liquidity_gate` | ~~`max_sweep_distance = 60.0`~~ **FIXED.** `MAX_SWEEP_DISTANCE_PIPS = Pips(60)` -> $6.00, so the cap can reject something for the first time. | 60 pips | ~~$60~~ **$6.00** | ~~P1~~ |
| U5 | `poi_engine.py:437` `score_poi` | ~~`if 5 <= zone_size <= 15`~~ **UNIT FIXED, BAND STILL WRONG.** Now $0.50-$1.50. Measured 2022->2026: the as-is band went 4.49% -> 65.79% of bars while the as-intended band went 36.86% -> **0.03%**. Rule 1 moved it to the second, so the bonus is now near-unreachable. **Open.** | 5-15 pips | ~~$5-$15~~ $0.50-$1.50 | **open** |
| U6 | `poi_engine.py:428` `score_poi` | ~~`if displacement >= 20 / >= 10`~~ **FIXED.** $2.00 / $1.00. It fired on 0.03-3.7% of bars before, i.e. was effectively inert -- see the criterion note in UNIT_MIGRATION_REPORT.md section 2. | 20/10 pips | ~~$20/$10~~ **$2/$1** | ~~P1~~ |
| U7 | `poi_engine.py:194` `detect_order_block` | ~~`if body >= 5`~~ **FIXED.** `ORDER_BLOCK_MIN_BODY_PIPS = Pips(5)` -> $0.50. Fired on 1.4% of bars before. | 5 pips | ~~$5~~ **$0.50** | ~~P1~~ |
| U8 | `sweep_detector.py:196` `detect_sweep` | ~~`sweep_min = max(2.5, atr*0.12)`~~ **FIXED -- the best result of the migration.** Typed to $0.25. The constant bound on **98.82%** of bars, so `atr*0.12`, the only scale-invariant term present, was **dead code**; it now binds on **73.74%**. Correcting the unit made the scale-aware branch live with no coefficient invented. Per Rule 4, `0.12` and `2.0` are now live and have never been validated. | 2.5 pips | ~~$2.50~~ **$0.25** | ~~P0~~ |
| U9 | `main_production.py` L2 gate | ~~described as "pips"~~ **UNIT FIXED; ABSOLUTENESS OPEN.** Named `L2_MIN_H1_RANGE_USD`; all output in dollars. A price-scaled version was built and measured (drift 100.0pp -> 30.1pp) then **REVERTED** -- end to end it took signals 4 -> **0** (`baseline_010`). | 8 pips | $8.00, **absolute** | **open** |
| U10 | `entry_engine.py:76-108` `detect_regime` | **NOT a 10x error** -- in dollars these bands give a sensible regime spread. They are **absolute**, and open. Scaling was built and measured (DEAD_CALM drift 34.6pp -> 16.2pp) then **REVERTED**: ~85% of bars became DEAD_CALM and signals went to 0. Relatively, the `2.5` edge sat at the **84th** percentile of volatility at $1,544 gold and the **12th** at $4,550 -- it was never one threshold. Fixing it needs the regimes **re-derived**, which is strategy design, not a correctness fix. | pips | dollars, **absolute** | **open (P0)** |
| U11 | `main_production.py` `_check_regime_scalp_momentum` | ~~`pip_size = 0.10` hardcoded inline~~ **FIXED.** Reads `XAUUSD_SPEC.pip_size`. | - | - | ~~P2~~ |
| U12 | `mt5_handler.py:150` `get_current_spread` | ~~`XAUUSD_PIP_SIZE = 0.10` hardcoded~~ **FIXED.** Reads `XAUUSD_SPEC.pip_size`, derived from the broker's own `symbol_info`. | - | - | ~~P2~~ |

### Measured: the L2 gate's selectivity is a function of gold's price, not volatility

`h1_atr < 8.0` against the 14-bar mean H1 high-low range on
`data/research_v1/bars/XAUUSD_H1.csv` (100,001 bars, 2009-08-31 to 2026-10-01):

| year | mean price | mean H1 range | **% of bars BLOCKED at L2** |
|---|---|---|---|
| 2009 | $1,075 | $3.53 | 98.8% |
| 2014 | $1,267 | $3.02 | 99.7% |
| 2015 | $1,160 | $2.90 | 99.9% |
| **2017** | $1,258 | $2.34 | **100.0%** |
| **2018** | $1,269 | $2.31 | **100.0%** |
| 2020 | $1,773 | $6.02 | 82.8% |
| 2023 | $1,943 | $4.29 | 97.3% |
| 2025 | $3,443 | $11.48 | 31.4% |
| **2026** | $4,550 | $24.01 | **0.0%** |

Same code, opposite behaviour, because gold quadrupled. In 2017-2018 the gate
admitted **no bars at all**; in 2026 it admits every one. It is not a volatility
filter, it is a proxy for the price level.

The same applies to U10's regime bands on M5 (2025-04-25 to 2026-10-01, the full
extent of M5 history). Over 13 months, with no code change:

| | 2025 (mean $3,673) | 2026 (mean $4,550) |
|---|---|---|
| `DEAD_CALM` (atr < 2.5) | 35.1% | **0.5%** |
| `MICRO_SCALP` (2.5-4.5) | 43.0% | 31.9% |
| `REGIME_SCALP` (4.5-7.0) | 17.4% | 40.0% |
| `INTRADAY_SWING` (> 7.0) | 4.6% | **27.6%** |

The regime selects the risk percentage (0.75% / 1.0% / 1.5%), so the account's
risk-per-trade escalated because gold got expensive. Note the bands are *not*
mislabelled by a factor of ten the way U9's threshold was -- in dollars they
produce a sensible spread of regimes. The defect is that they are **absolute**,
not that they are the wrong size.

**U8 and U10 are the highest-leverage items in this register.** U8 sets the
minimum wick depth for a sweep and is one of the busiest rejection gates
(9,238 of 39,709 decisions blocked at L5). U10 determines which regime is
selected, and therefore which thresholds, risk and bypasses apply.

**Do not fix these individually.** They interact: correcting U8 alone changes the
sweep rate, which changes L5/L7 pass rates, which changes everything downstream.
They should be migrated together onto `core.units`, behind a backtest that can
measure the result.

> **DONE, and this warning was right -- more right than it knew.** Migrated
> together under `research/unit_migration_spec.md` (pre-registered before any
> implementation) and measured as `baseline_010` and `baseline_011` against
> `baseline_009`.
>
> The interaction was not only downstream. Scaling the regime bands changed
> **L1_BIAS blocks from 1,505 to 5,950** without touching L1 at all, because
> `use_fast_bias` is true only for the scalp regimes -- so reclassifying bars as
> DEAD_CALM silently switched L1 from the H1 fast bias to the stricter H4 one.
> An **upstream** gate moved because a **downstream** classifier changed.
>
> Result: `research/UNIT_MIGRATION_REPORT.md`.

---

## 2. POSITION SIZING AND RISK

| # | Location | Issue | Priority |
|---|---|---|---|
| R1 | `risk_manager.py:18` | ~~`lot = risk_amount / (stop_distance * 10.0)`. XAUUSD contract size is **100**, not 10, so every position is **~10x oversized**.~~ **FIXED.** `risk_manager.calculate_lot_size_for_symbol` now delegates to `core.sizing.lots_for_risk` with a required broker `SymbolSpecification`, and returns `0.0` rather than a substituted minimum. `main_production.execute_entry_signal` declines when no spec is available. The stale claim has been removed from `core.safety.PHASE_LOCK_REASON`. | ~~P0~~ |
| R2 | `main_production.py` | ~~`account_balance: float = 10000` hardcoded. `mt5.account_info()` is called once for a log line and discarded. Every risk figure is fictional.~~ **FIXED.** `execute_entry_signal(account_balance=None)` now **declines to trade** without a balance; the main loop supplies `mt5.account_info().balance` via `account_risk_state()`. | ~~P0~~ |
| R3 | `main_production.py` `check_pre_trade_gates` | ~~Called without `current_daily_loss`, so it defaults to `0` and `0 < -max_daily_loss` is never true. The daily-loss breaker cannot fire.~~ **FIXED.** Both defaulted risk parameters are **removed** rather than corrected -- a defaulted risk input is an assertion the function cannot support. The gate now calls `core.risk_limits.evaluate()`, which returns `HALT` when state is unknown. | ~~P0~~ |
| R4 | system-wide | ~~No realised-P&L tracking anywhere. Nothing knows whether the account is up or down.~~ **FIXED.** `main_production.realised_pnl()` values closes from `contract_size`, and `_record_close()` persists them via `save_closed_trade`. A P&L that cannot be computed is recorded as `None`, which the risk gate treats as a hard error rather than as zero. | ~~P0~~ |
| R5 | `risk_manager.py:22` | ~~`max(0.01, round(lot,2))` silently inflates a sub-minimum size instead of declining the trade.~~ **FIXED** with R1: `lots_for_risk` returns a non-tradeable decision and the adapter returns `0.0`. | ~~P1~~ |
| R6 | `risk_manager.py:23` | ~~`min(lot, 1.0)` ignores `config.INTRADAY_LOT_SIZE_MAX = 0.1`.~~ **FIXED.** `core.sizing` caps at the **broker's** `volume_max` only; the project's own cap is now applied by `RISK_LIMITS.max_lots_per_position` and enforced through `execute_entry_signal(max_lots=...)`. | ~~P1~~ |
| R7 | system-wide | ~~No max-drawdown limit, no consecutive-loss limit, no equity-curve kill switch.~~ **FIXED.** `core/risk_limits.py` adds all three. A drawdown breach returns `HALT`, which is deliberately **not** self-clearing, unlike the daily cap. Limits in `config.py`: `MAX_DRAWDOWN_PERCENT`, `MAX_CONSECUTIVE_LOSSES`, `MAX_DAILY_LOSS_PERCENT`. | ~~P1~~ |
| R8 | `main_production.py` | ~~`max_concurrent_trades = 3` on one symbol is 3x the same risk; no exposure cap.~~ **FIXED.** `config.MAX_OPEN_LOTS` caps total open volume -- the limit a position *count* cannot express. The count cap is retained alongside it. | ~~P1~~ |
| R9 | `config.py` | ~~`INTRADAY_MAX_HOLD_MINUTES = 240` defined, never enforced. No time stop.~~ **FIXED.** `core.risk_limits.overdue_positions()` is called each cycle, **before** the gate's `continue`, so a halted account can still time out its positions. An unparseable entry time raises rather than reading as "young". | ~~P1~~ |

---

## 3. BAR CONVENTION VIOLATIONS

`core/candles.py` defines the canonical convention. Because
`get_market_data(closed_only=True)` already drops the forming bar, `iloc[-1]`
**is** the last closed bar. These sites disagree:

| # | Location | Uses | Effect | Priority |
|---|---|---|---|---|
| B1 | `entry_engine.py:158` `detect_rejection_candle` | `iloc[-2]` | **UNRESOLVED -- implemented, measured, reverted.** For: the variable is named `current`; `get_market_data(closed_only=True)` drops the forming bar on all three fetch paths; `detect_displacement_candle` in the same module reads `iloc[-1]` and the two are alternative confirmations on one pass; `core/candles.py` lists it as stale. Against: **both** integration fixtures place the rejection at `iloc[-2]` and the break at `iloc[-1]`, and `TRIGGER_BARS` is commented "two M5 candles: rejection, then the break" -- the only statement of intent anywhere. Changing it took both fixtures to zero signals (60 of 64 failures). **Decisive measurement:** `baseline_014` (iloc[-2]) and `baseline_013` (last closed bar) have IDENTICAL funnels at all eight layers across 15,735 real decisions -- B1 moves not one gate decision, and only the two synthetic fixtures were sensitive to it. Resolving it needs both fixtures rebuilt to clear all eight layers with the rejection candle last -- a separate measured pass. | **open** |
| B2 | `entry_engine.py:196` `detect_momentum_confirmation` | ~~`iloc[:-1].tail(3)`~~ **FIXED.** `closed_bars().tail(3)`, so `current_volume` is the current bar's. **`prev_rsi`'s `iloc[:-1]` is deliberately unchanged** -- it wants the previous bar's RSI to compare against `curr_rsi`, which is the intent, not the bug. | ~~P1~~ |
| B3 | `entry_engine.py:~490` `_evaluate_pullback_entry` | ~~`iloc[-2]["close"]` as entry price~~ **FIXED.** `last_closed_bar()` on both the M5 and M1 legs (the M1 one was 2 minutes stale). A pullback was priced off a five-minute-old bar while a momentum entry on the same pass used the current one. | ~~P0~~ |
| B4 | `main_production.py` `confirmed_m5_close` | ~~`iloc[-2]["close"]`~~ **FIXED.** `last_closed_bar()`. The live tick is still fetched, logged and discarded -- that part is unaddressed and belongs with the E-items. | ~~P0~~ |
| B5 | `pullback_detector.py:221` | ~~`recent.iloc[:-1]` -- **double-drop**~~ **FIXED.** `closed_bars(recent)`, which is a no-op under `CLOSED_ONLY` and therefore idempotent. Detection had been running **two** bars stale. `core/candles.py`'s own docstring already named this bug. | ~~P1~~ |
| B6 | `entry_engine.py:228` `detect_displacement_candle` | ~~`iloc[-1]` -- correct, but inconsistent with B1/B2~~ **RESOLVED by fixing B1/B2.** Unchanged; it was already right, and the inconsistency is gone because the others moved to it. | ~~P1~~ |

B3/B4 mean a **pullback entry is priced off a bar that closed five minutes ago
while a momentum entry uses the current one**, on a strategy targeting 15–25 pip
moves.

Additionally: `_evaluate_momentum_entry` checks `price_in_fvg` against the stale
`current_price` it was handed, not the live tick — which *is* fetched, logged,
and then discarded.

---

## 3a. NEW -- found during the A/B migration, deliberately NOT fixed

Found while migrating A3, recorded rather than folded in. Widening a
pre-registered change mid-flight is how a measured correctness fix becomes an
unmeasured one, so these are new items with their own future measurement.

| # | Location | Code | Intended | Actual | Priority |
|---|---|---|---|---|---|
| U13 | `sweep_detector.py` `assess_liquidity_gate` | `near_buffer = max(2.5, m15_atr * 0.20)` | 2.5 pips? | **$2.50 = 25 pips** | P1 |
| U14 | `sweep_detector.py` `assess_liquidity_gate` | `momentum_buffer = max(5.0, m15_atr * 0.50)` | 5 pips? | **$5.00 = 50 pips** | P1 |

Same shape as U1-U12 -- a bare float compared against a quote-currency distance
-- but **not in that register's enumeration**, so they were outside the scope of
`research/atr_bar_convention_spec.md` and outside the unit migration's too.

Two things make them worth a separate pass rather than an immediate fix:

1. **Their intent is unrecorded**, exactly as U1's was. Nothing names these as
   pips. U1 is the precedent for what happens when a name is treated as a
   specification: the "correction" put a stop $0.95 from entry and the fixture
   was stopped out on the next bar. These get measured before they get changed.
2. **They now sit beside a corrected ATR.** The `x0.20` and `x0.50` terms act on
   a true Wilder ATR after A3's fix, roughly 2.1x its previous value, so their
   *relative* weight against the constants has already shifted. Whatever is done
   to the constants should be measured against the post-A3 baseline, not the one
   before it.

---

## 4. ATR FRAGMENTATION

`core/indicators.atr_wilder` is the canonical definition. Four incompatible
implementations remain live:

| # | Location | Definition | Priority |
|---|---|---|---|
| A1 | `indicators.py:130` | `pandas_ta.atr` -- true Wilder ATR (correct) | ~~P2~~ **VERIFIED.** Asserted equal to `core.indicators.atr_wilder` to 6 dp on real H1 bars rather than edited (`tests/core/test_atr_single_definition.py`). |
| A2 | `pullback_detector.py:69` `_estimate_recent_atr` | ~~correct true range, but **SMA-14**, not Wilder~~ **FIXED.** Delegates to `atr_wilder`. Had two faults: SMA rather than Wilder smoothing, and `min_periods=3` silently producing a "14-period ATR" from three observations. | ~~P1~~ |
| A3 | `sweep_detector.py:51` `_estimate_m15_atr` | ~~`close.diff().abs().rolling(14).mean()` -- **ignores high/low entirely**~~ **FIXED.** Delegates to `atr_wilder`. Measured over all 100,020 M15 bars it understated true Wilder ATR by **2.1x** (median $1.516 vs $3.084). This was the P0: once U8's unit fix moved `sweep_min`'s floor from $2.50 to $0.25, `m15_atr * 0.12` began to bind -- so a non-ATR set the busiest gate in the system. | ~~P0~~ |
| A4 | `main_production.py` `h1_atr` | ~~`mean(high - low)` over 14 bars -- **ignores gaps**~~ **FIXED.** Delegates to `atr_wilder`. Also had two faults: no previous-close terms (so every session gap was invisible) and SMA rather than Wilder. Aggregate effect is modest (L2 block rate 87.60% -> 88.25% over all H1 bars) but per-bar the ratio spans 0.77-1.40. **Note:** this changes what `L2_MIN_H1_RANGE_USD` is compared against -- the floor's value is unchanged but the quantity is now gap-aware, so its meaning shifted. Recorded at that constant. | ~~P1~~ |

A3 is the most serious: it cannot see intrabar range at all, so on a wide-range
bar it reports a small value. That understated ATR sets `sweep_min` (U8).

A2/A3/A4 also return silent defaults (`15.0`, `10.0`, `default=10.0`) when data
is short, **fabricating a volatility reading**. `atr_wilder` raises instead.

**Not migrated in Phase 1.** Switching A3 to true Wilder ATR would immediately
change `sweep_min` and therefore the sweep detection rate. That is a behavioural
change requiring a baseline.

---

## 5. EXECUTION AND STATE

| # | Location | Issue | Priority |
|---|---|---|---|
| E1 | `order_execution.py:181` | `execute_order(mt5_handler=None, simulation=False)` always returns `False`. **No order has ever been sent.** Now gated by `core.safety`; the underlying path is unfixed. | **P0** |
| E2 | `order_execution.py:170` | The "real" branch calls `mt5_handler.send_order()` — **a method that does not exist** in `mt5_handler.py` (a module of free functions, not a class). | **P0** |
| E3 | `order_execution.py:110-111` | `exit_1_1` / `exit_1_2` computed as `entry + risk` regardless of direction. **For a SELL these are loss levels, and the trigger test fires immediately on open.** | **P0** |
| E4 | `main_production.py:1349` | `manage_positions({})` — empty dict means `current_price` falls back to `entry_price`, so no exit can ever trigger. | **P0** |
| E5 | system-wide | No broker reconciliation. `mt5.positions_get()` is called only at shutdown. Local state can diverge permanently — as it did, with two phantom positions surviving every restart. | **P0** |
| E6 | system-wide | Stops/targets are never registered broker-side. A position would be unprotected if the process died. | **P0** |
| E7 | `main_production.py` | `trade_manager.manage_open_trade`, `close_position`, `feedback_loop.log_closed_trade`, `calculate_weekly_performance`, `save_closed_trade` are **imported but never called**. Layers 9 and 10 are dead. | P1 |
| E8 | `main_production.py` | `ConnectionManager` is instantiated but `reconnect()` is never called. If MT5 drops mid-session the bot loops forever on empty frames. | P1 |
| E9 | `entry_engine.py:406` | `valid_rr = rr >= 2.0`, but `rr == tp_ratio` by construction (TP is derived as `risk × tp_ratio`). The RR check is a tautology testing a config constant. | **P0** |
| E10 | `entry_engine.py` | MICRO_SCALP (`tp_ratio=1.5`) therefore **can never produce an entry** — 55% of observed runtime. | **P0** |
| E11 | `entry_engine.py:374` | No check that the stop is on the correct side of entry. `StopLoss` in `core/types.py` now enforces this; the engine does not use it. | P1 |
| E12 | system-wide | Entry never accounts for spread or slippage. `config.MAX_SLIPPAGE_PIPS = 2.0` is defined and never referenced. | P1 |

---

## 6. SIGNAL / SETUP INTEGRITY

| # | Location | Issue | Priority |
|---|---|---|---|
| S1 | `poi_engine.py:643-666` | The "Fibonacci 0.618" POI is built from a **rolling** `tail(20)` high/low, so the zone **repaints every M15 bar**. It is generated unconditionally and frequently becomes `best_poi`. | **P0** |
| S2 | `structure_engine.py:231` | L2 "HH/HL" compares **adjacent candle** highs/lows over 5 bars, not swing structure. The condition is near-always true, making the gate close to a no-op — yet it feeds 20–30% of the confidence score. `find_h1_swings()` sits unused directly above it. | **P0** |
| S3 | system-wide | No signal deduplication or cooldown. The loop re-evaluates every 5 s and `detect_sweep` accepts sweeps up to 8 bars old, so one setup could fire repeatedly across its validity window. | P1 |
| S4 | `main_production.py:825` | L4 returns PASS/WATCH/BLOCK but only `BLOCK` is checked, so `WATCH` silently passes — contradicting its own docstring. (L5 handles WATCH correctly; inconsistent.) | P1 |
| S5 | `liquidity_engine.py` | `tp_pool` is computed and then discarded; TP comes from `tp_ratio` instead. The system locates where liquidity actually sits, then targets an arbitrary multiple. | P2 |
| S6 | `confidence_engine.py:245` | `has_fib_confluence` and `rsi_value` reach only `check_a_plus_checklist`, which feeds a cosmetic string. **Neither affects `final_score`**, the only thing L7 gates on. | P2 |
| S7 | `main_production.py` `_bias_to_side` | Maps anything not `"BULLISH"` to `SELL`, silently turning `NEUTRAL` into a short. `Side.from_bias()` in `core/types.py` rejects it. | P1 |
| S8 | system-wide | No news gate. `news_handler.py` (745 lines) and `config.HIGH_IMPACT_NEWS_BLACKOUT_MINUTES` exist; neither `main` imports them. The bot would trade into NFP/CPI. | P1 |
| S9 | L0 / L8 | Spread is enforced **nowhere**: L0 logs `[CHECK DISABLED]`, L8 defers to L0, and `evaluate_entry_for_regime` hardcodes `spread_ok = True`. `regime_info["spread_acceptable"]` is computed and never read. | P1 |

---

## 7. TIME AND TIMEZONE

| # | Location | Issue | Priority |
|---|---|---|---|
| T1 | `main_production.py`, `main.py` | `datetime.now()` (naive **local**) used for all timestamps, while market data is tz-aware **UTC**. | P1 |
| T2 | `main_production.py` `_count_today_entry_signals` | Compares a naive local date against those timestamps. On a machine offset far enough from UTC, the daily counter reads the wrong day. | P1 |
| T3 | `entry_engine.py:49` `_within_kill_zone` | Calls `datetime.now(timezone.utc)` directly — not injectable, so kill-zone logic cannot be replayed. | P1 |
| T4 | `risk_manager.py:28` `get_current_session` | Same; drives the session gate and the confidence session bonus. | P1 |
| T5 | `mt5_handler.py:105` | `copy_rates_range` uses naive local `datetime.now()`; MT5 expects server time. | P1 |
| T6 | system-wide | Broker/server timezone offset is never established, so daily bar boundaries (and PDH/PDL) may be wrong. | P1 |

`core/clock.py` provides the abstraction. **No call site has been migrated** —
doing so changes behaviour on any non-UTC machine.

---

## 8. ARCHITECTURE AND PERFORMANCE

| # | Location | Issue | Priority |
|---|---|---|---|
| X1 | `main.py` vs `main_production.py` | Two entry points with duplicated `analyze_entry`, diverged. `main.py` has no regime engine, no BOS flip, no momentum fallback. Phase 0 at least stopped them sharing one log file. | P1 |
| X2 | `main_production.py:560-1035` | `analyze_entry` is ~400 lines inside one `try/except` that converts **any** exception into `signal_type="ERROR"`, silently. | P1 |
| X3 | `entry_engine.py` `_frame_snapshot` | `calculate_indicators` re-runs the full pandas-ta stack plus a row-wise `.apply()` on every call; `_atr_from_frame`, `_rsi_from_frame` and `_volume_ratio_from_frame` each recompute everything. ~10–15 full recomputations per 5 s loop. | P1 |
| X4 | `main_production.py` `_count_today_entry_signals` | Re-read the entire 10.7 MB signal log on every cycle. Mitigated in Phase 0 (the new log starts empty) but the O(file) scan remains. | P2 |
| X5 | `entry_engine.py:196` | `_rsi_from_frame(m5_data.iloc[:-1].tail(6))` — RSI-14 on 6 bars is always NaN, so `prev_rsi` is permanently `None` and `rsi_direction` permanently `"neutral"`. Dead logic. | P1 |
| X6 | `indicators.py:246` `find_last_swing` | `if high_idx > low_idx if low_idx is not None else True` raises `TypeError` when `high_idx` is `None` and `low_idx` is not. | P2 |
| X7 | `indicators.py:262` `anchored_vwap_from_swing` | Uses `data['volume']`, but market frames carry `tick_volume`. Would `KeyError`. Currently unreachable. | P3 |
| X8 | `technical_engine.py:9` | Imports `SESSION_SCORE_MULTIPLIERS` from `risk_manager`, **which does not exist**. Module raises `ImportError`. `stage1.py` is transitively broken. | P2 |
| X9 | repo root | `utils.py` (module) is **shadowed** by `utils/` (package). The root module is dead code, never imported. | P3 |
| X10 | repo-wide | ~4,500 lines orphaned: `strategy_engine.py`, `ai_analyst.py`, `news_handler.py`, `technical_engine.py`, `utils/result_writer.py`, `stage1/2.py`, `key_levels.py`, `pullback_handler.py`, `cvd_divergence.py`, `institutional_patterns.py`. **Not deleted** — deletion needs explicit approval. | P2 |
| X11 | `trading_bot_production.log` | No rotation; 17 MB and growing. `utils/__init__.py` correctly uses `RotatingFileHandler`; the production logger does not. | P2 |
| X12 | root `test_*.py` (7 files) | Script-style, not `unittest`; some import broken modules; `test_entry_logic.py` calls `connect_mt5()`. Not collected by discovery and not run. | P2 |

---

## 9. VALIDATION GAPS

| # | Issue | Priority |
|---|---|---|
| V1 | No backtesting engine. **No threshold in this system has any empirical basis.** | **P0** |
| V2 | No event replay. Engines read live DataFrames; `datetime.now()` is called inside decision logic. `core/clock.py` is the prerequisite, now in place. | **P0** |
| V3 | No outcome labels. No trade has closed; `closed_trades.json` holds one `UNVERIFIED / SUSPECTED SYNTHETIC` record. Nothing to fit or validate against. | **P0** |
| V4 | The `FIX (...)` comment trail (`BIAS-1/2`, `SCALP-1`, `STRUCTURE-1/2`, `PULLBACK-1`, `SPREAD-1`) documents repeated threshold loosening in response to "the bot isn't trading" — tuning against a live feed with no holdout and no outcome data. | P1 |
| V5 | No paper-trading mode. `demo_mode` simulates fills with `random.random() < 0.05` failure injection; it is not a paper-trading environment. | P1 |
| V6 | Strategy-layer test coverage remains near zero. The 2 pre-existing failures in `tests/test_layer_gate_logic.py` are themselves a unit artefact: the fixture prices ~100 while the L2 gate requires `h1_atr >= 8.0` (see U9). | P1 |

---

## 10. UNVERIFIED HISTORICAL DATA

| # | Item | Status |
|---|---|---|
| H1 | `trade_states/closed_trades.json` — one record, `XAUUSD_001`, entry 2450 → exit 2540, pnl 90.0 | **UNVERIFIED / SUSPECTED SYNTHETIC.** Preserved unmodified. Evidence in `archive/README.md`. Final determination deferred to Phase 2 broker reconciliation. |
| H2 | `archive/2026-09-16_signal_log_legacy_mixed_schema.csv` — 39,709 rows, 77-column header over 20-column data | **UNRECOVERABLE.** Not repaired; realigning would fabricate data. Contains no entry signals and no trade outcomes. |

---

---

## 11. OBSERVED DURING PHASE 2A (replay build) -- catalogued, NOT fixed

Phase 2A ran the unmodified strategy over a deterministic synthetic fixture.
These are observations from that run. **Nothing below was changed.** The
synthetic fixture is not market data and none of this is a performance statement.

| # | Observation | Relates to | Priority |
|---|---|---|---|
| P1 | Over 3,201 decisions the strategy produced **0 entry signals** and **0 errors**. All decisions blocked at L1_BIAS (2,016) or L2_STRUCTURE (1,185). Consistent with the live record: 39,709 production decisions also produced zero entry signals. | E10, S2, U9 | — |
| P2 | Every decision classified as **DEAD_CALM**. The fixture's H1 ATR is ~$5.0 against the `h1_atr < 8.0` gate, and its M5 ATR ~$1.2 against the `m5_atr >= 2.5` MICRO_SCALP floor. Those thresholds are absolute USD, so regime classification depends on the **price level**, not on relative volatility. | **U10, U9, G2** | **P0** |
| P3 | The L2 block message reads `H1 ATR too calm (5.0 < 8.0 pips)` while the compared values are quote-currency dollars. The unit mislabelling is visible in the operator-facing output. | U9 | P1 |
| P4 | `main_production.analyze_entry` reads the wall clock in four places (N1-N4), so it is not replayable without intervention. Phase 2A neutralises this with a scoped patch; it is not a fix. | T1-T4 | P1 |
| P5 | Replay throughput is ~18 decisions/sec with the real strategy, dominated by uncached `calculate_indicators` calls. A year of M5 replay would take roughly 1.6 hours. | X3 | P2 |
| P6 | `get_market_data` returns an **empty** frame when history is short, never a partial one. The replay feed mirrors this. Worth knowing: production therefore makes no decisions at all until ~17 days of H4 history exists. | — | — |

### Controlled price-level comparison (evidence for P2 / U9 / U10)

Same seed, same bar shapes, same *relative* volatility; only the absolute dollar
scale differs (`base_price` and `volatility_scale` moved together). Any
difference in behaviour is therefore attributable solely to thresholds expressed
in absolute USD.

| | gold@2400 (H1 ATR ~$5.4) | gold@4000 (H1 ATR ~$9.0) |
|---|---|---|
| Decisions | 3,201 | 3,201 |
| Signals | 0 | 0 |
| Errors | 0 | 0 |
| Regime | `DEAD_CALM` 3,201 | `DEAD_CALM` 3,201 |
| `L1_BIAS` | 2,016 | **2,016** |
| `L2_STRUCTURE` | 1,185 | **453** |
| `L3_PULLBACK` | 0 | **651** |
| `L5_SWEEP_WAIT` | 0 | **59** |
| `L5_SWEEP` | 0 | **22** |

Observations, stated without inference beyond the measurement:

* **The L2 ATR gate is price-level dependent.** `h1_atr < 8.0` blocked 1,185
  decisions at $2,400 and 453 at $4,000. 732 decisions that the gate rejected at
  one price level passed at the other, on identical relative price action. This
  is U9 measured directly.
* **L1_BIAS blocked an identical 2,016 decisions at both scales.** The H4 bias
  threshold is ATR-scaled (`_calculate_ema_threshold`, ratio 0.20), so it is
  scale-invariant here. Its `floor=3.0` was not the binding constraint at either
  level.
* **Regime did not change.** Both runs classified every decision `DEAD_CALM`:
  M5 ATR was ~$1.2 and ~$2.0, both below the `m5_atr >= 2.5` MICRO_SCALP floor.
  U10 is not contradicted by this -- the bands are still absolute USD -- but this
  comparison does not exercise a regime transition, and no claim is made that it
  does.
* Once past L2, decisions reached L3 and L5, so the deeper layers are reachable
  in replay. Neither run produced an entry signal.

Nothing was changed in response to any of this.

### Data acquisition blocker (not a code defect)

`mt5.initialize()` fails with `(-6, 'Authorization failed')`. The terminal log
reports `authorization on MetaQuotes-Demo failed (Invalid account)`. The terminal
holds cached XAUUSD history for 2004-2026 (~413 MB of `.hcc`), which becomes
readable via `tools/export_mt5_history.py` once the terminal is logged into a
valid account. The `.hcc` format is **not** parsed -- an undocumented parser
could mis-read silently, and a corrupted baseline is worse than none.

### Test defect found and fixed within Phase 2A scope

A determinism test stub gated on `datetime.now().minute % 2`. Because
`frozen_clock` patches only the strategy modules, the stub read the real wall
clock and emitted zero signals on odd minutes -- passing or failing depending on
when the suite ran. Fixed by routing the read through `risk_manager`, which the
replay clock does patch. No strategy code was involved.

---

## 12. OBSERVED DURING PHASE 2A.1 (real-strategy integration) -- catalogued, NOT fixed

Phase 2A.1 drove the unmodified strategy end to end on a purpose-built
deterministic fixture. It reached an entry signal on both sides, which let
several defects be observed in operation rather than only by reading the source.
**Nothing below was changed.** The fixture is not market data and none of this is
a performance statement.

| # | Observation | Relates to | Priority |
|---|---|---|---|
| Q1 | **Realised R != the strategy's reported RR.** The strategy reports RR 3.0 but the simulated fill produced R 4.33 (long) and 6.57 (short). It computes risk and reward against an entry price it is not filled at: the fill is the next bar's open, while the strategy assumes a stale M5 close. On the long trade intended risk was $12.24 and realised risk $9.15. | **B3, B4, E9** | **P0** |
| Q2 | The reported `rr_ratio` was exactly `3.0` on every signal, because the target is derived as `risk x tp_ratio`. It re-states the regime constant and measures nothing about the trade. | E9 | **P0** |
| Q3 | Only `INTRADAY_SWING` could produce a signal. `MICRO_SCALP` and `DEAD_CALM` both carry `tp_ratio = 1.5`, so `valid_rr = rr >= 2.0` is false by construction and `entry_triggered` can never be true. Reaching a tradeable regime required M5 ATR above $7.00. | **E10, U10** | **P0** |
| Q4 | Reaching L6 required a **confirmed sweep**, purely because that drops the POI threshold from 70 to 60. The Fib POI scored 68 -- above 60, below 70 -- so a CHoCH-only setup blocks at L6 while an otherwise identical swept setup passes. The 2-point margin is arbitrary. | S1, U5, U6 | P1 |
| Q5 | The Fib POI is capped near 68 in this shape: it is mid-range by construction, so `_zone_touched` is always true (no +30 untested) and `_calc_htf_confluence` returns 0 because H1 extremes cluster at turning points, not mid-range. The POI that most often wins selection is the one least able to score well. | S1 | P1 |
| Q6 | The stop came from `sweep_wick_low - 3.0`, i.e. a **$3.00** buffer where 3 pips was intended -- confirmed in the live values: sweep wick $2511.73, stop $2508.73. | **U1** | **P0** |
| Q7 | `detect_sweep` passed on 2 of 4 quality checks (volume + close position). The wick/body check failed because the sweep candle's body was large, so a decisive reclaim candle scores *worse* on wick ratio than a feeble one. | A3, U8 | P1 |
| Q8 | L7 scored 80.35 with `sweep_quality` contributing only 4.0/10 and `has_fib_confluence` false. Fib confluence and RSI are computed and passed in, but reach only the cosmetic A+ checklist -- they cannot affect the score the gate reads. | S6 | P2 |

### What this phase demonstrated works

The replay -> strategy -> PaperBroker -> ledger chain connects correctly. The real
L1-L8 path produced a BUY and a SELL signal; both filled on the next bar, resolved
against SL and TP, and reached the ledger with correct R-multiples. No look-ahead
was detected at integration level, and the run is deterministic across repeats and
machine timezones.


---

## 13. OBSERVED DURING PHASE 3A (real XAUUSD baseline) -- catalogued, NOT fixed

Phase 3A ran the unmodified strategy over **real broker history** for the first
time: XAUUSD from MetaQuotes-Demo, exported read-only, validated, and replayed
bar by bar. No strategy file was touched -- all 110 tracked modules are
byte-identical to commit `04a341d`. The run produced **zero entry signals and
zero trades**, so there is no performance statement to make here, and none is
made. What follows is measurement.

Artifacts: `baselines/baseline_004/` (canonical -- its `defect_observations.json`
matches the committed harness) with `baselines/baseline_003/` and
`baselines/baseline_002/` as independent repeats. All three produced a
byte-identical 15,735-line decision stream. Fingerprints are in each directory's
`run_fingerprint.txt`.

### The binding observation: L8 is unreachable in most of the runtime

15,735 decisions were evaluated. 1,265 of them cleared L1-L7 and blocked at L8
with `Entry triggers not all confirmed`. Broken down by regime:

| Regime | `tp_ratio` | Decisions | Reached L8 | Can satisfy `valid_rr`? |
|---|---|---|---|---|
| MICRO_SCALP | 1.5 | 5,121 | 972 | **No -- structurally impossible** |
| DEAD_CALM | 1.5 | 2,312 | 22 | **No -- structurally impossible** |
| REGIME_SCALP | 2.0 | 6,492 | 217 | Yes |
| INTRADAY_SWING | 3.0 | 1,810 | 54 | Yes |

> **CORRECTION (2026-09-17, Phase 4A pre-analysis).** The paragraph below
> originally read "994 of the 1,265 L8 blocks (78.6%) were decided before the
> market was consulted". **That causal claim is withdrawn.** At all 1,265 L8
> blocks the allowed candidate had `raw_triggered = False`, so the RR gate was
> never the binding term and blocked **0** decisions. 994 is the count of
> L8-reaching decisions *in* an unreachable regime, not a count the gate
> blocked. The tautology below is real but **latent**. See
> `docs/PHASE_3A_BASELINE_REPORT.md` Addendum.

**994 of the 1,265 L8 blocks (78.6%) were in a regime where `valid_rr` is
unsatisfiable** — a measure of unenterable runtime, not of what blocked them. `calculate_entry_levels` sets the target as
`take_profit = entry +/- risk_distance * tp_ratio` and then tests
`valid_rr = (reward / risk) >= 2.0`. Those two lines make `rr` identically equal
to `tp_ratio`, so the test reads a configuration constant. Since
`entry_triggered = raw_triggered and valid_rr`, no decision in a
`tp_ratio < 2.0` regime can ever produce an entry, whatever the price action
did. This is E9 and E10 confirmed on real data at scale, and it is why Q3 was
not a fixture artefact.

Proved directly against the production function, for every regime and both
sides, in `tests/backtest/test_baseline_defects.py`. That file also parses
`entry_engine`'s AST so the copy of these constants in `backtest/baseline.py`
cannot silently drift from the source.

### New observations

| # | Observation | Relates to | Priority |
|---|---|---|---|
| D1 | **Broker tick value contradicts contract size.** `symbol_info` reports `trade_contract_size = 100.0` but `trade_tick_value = 0.1` with `trade_tick_size = 0.01`, giving `money_per_price_unit(1 lot) = 10.0` where the contract size implies 100.0 -- a factor of 10. The baseline uses the broker's own tick value rather than silently substituting the contract size. Any P&L figure from any source that assumes one while the broker reports the other is off by 10x. | R1 | **P0** |
| D2 | **M1 is the binding coverage constraint.** The broker serves 100,002 M1 bars (2026-06-02 to 2026-09-16, about 3.5 months) while D1 reaches back further. The replay drives on M5 and needs M1, so the usable window is ~3.5 months regardless of what the higher timeframes hold. No claim of multi-year coverage is supportable from this export. | V1 | P1 |
| D3 | **Server time is not UTC.** The MetaQuotes-Demo server runs UTC+3. Bar stamps are shifted to true UTC at export. A consequence: broker-native H4 and D1 candles are not UTC-aligned (D1 opens 21:00 UTC, H4 at 01:00/05:00/09:00). They are preserved as-is rather than re-cut, because re-cutting would replace real candles with synthetic ones. Session logic in `risk_manager` is defined on UTC hours, so mislabelling these stamps would have shifted every session window by three hours. | T1-T6 | **P0 (handled at export)** |
| D4 | **Spread is ASSUMED, not historical.** The broker serves OHLC bars with no bid/ask history. The baseline applies a flat 2.0 pip spread and records `spread_is_assumed: true` in every manifest. The broker reported a live spread of 39 points at export time, which at `pip_size = 0.10` is 3.9 pips -- nearly double the assumption, so the assumption is not conservative. No spread-sensitive conclusion can be drawn from this baseline. | E12 | P1 |
| D9 | **The L2 H1-ATR gate did not bind on real data.** `main_production` blocks at L2 when `h1_atr < 8.0`. Across 15,735 decisions it fired **zero** times; all 7 L2 blocks were `H1 structure is broken`. The threshold is absolute USD, so at gold near $3,900 an $8.00 floor is about 0.2% of price and is always cleared. It is not harmless -- it is simply not selective at this price level, and its selectivity would change with the price level rather than with volatility. Note the two pre-existing unit-test failures (D7) are caused by this same gate firing at 0.0 when indicators are mocked away. | U9, G2 | P1 |
| D5 | **L3 and L5 dominate the attrition ahead of L8.** 5,868 decisions (37.3%) blocked at L3 and 4,075 (25.9%) at L5, against 1,265 (8.0%) at L8. Even if the L8 tautology were removed, most decisions would not reach it. Fixing E9/E10 alone would not make this strategy trade at the rate the layer structure implies. | S1, A3 | P1 |
| D6 | **`run_fingerprint` was not sufficient to prove determinism.** As originally written it hashed dataset + ledger + metrics. On a zero-trade run the ledger is empty and every metric is `None`, so two runs that disagreed on every decision would still have matched. A `decisions_fingerprint` over the ordered decision stream was added, and `tests/backtest/test_baseline_fingerprint.py` mutates each covered field in turn to prove the digest moves. Found by inspection during Phase 3A; the earlier Phase 3A determinism claim rested partly on count comparisons, not on this digest. | V2 | P1 (harness, not strategy) |
| D7 | **Two pre-existing test failures, unrelated to Phase 3A.** `tests/test_layer_gate_logic.py::test_pullback_gate_requires_real_pullback_detection` and `::test_micro_scalp_l7_confidence_uses_55_threshold` both fail at commit `04a341d` with zero Phase 3A changes applied (verified in a clean worktree). Both patch `calculate_indicators` to `{}`, so L2's H1-ATR sub-gate reads `0.0 < 8.0` and blocks before the layer under test is reached. They are left failing: repairing them means editing assertions about strategy gate behaviour, which a measurement phase must not do. Note the sub-gate itself -- L2 is named `L2_STRUCTURE` but carries a volatility gate that its name does not disclose. | U9, X-docs | P2 |

| D8 | **`LondonNewYork` is a session name that cannot occur.** `detect_regime` admits MICRO_SCALP when `kill_zone or session in {"Asian", "London", "LondonNewYork"}`, but `risk_manager.get_current_session` returns only `Asian`, `London`, `NewYork`, `Dead`, `Closed`. The label also appears in `config.py:125` and `main_production.py:442`. Effect on the baseline: during New York hours MICRO_SCALP is reachable only when the kill zone is open, which is why New York shows 72 MICRO_SCALP decisions against London's 2,736. Proved by enumerating every hour of a full week under a frozen clock in `tests/backtest/test_baseline_defects.py`. | T1-T6 | P1 |
| D10 | **The baseline wrote to the production log.** `main_production` builds its `logging.FileHandler` at module scope from `TRADING_BOT_LOG_FILE`, defaulting to `trading_bot_production.log`. The baseline runner redirected stdout but not logging, so baselines 001-004 appended **8,860 lines** to the permanent record across 2026-09-15..17 (8,799 `[L2_STRUCTURE]`, 31 `[L3_PULLBACK]`, 24 `[INIT]`, 4 `[BOT]`, 2 `[DECISION]`). **No fabricated signal entered the record** -- the run produced none, and the file's `ENTRY SIGNAL GENERATED` count is still the same 4 July entries the Phase 1 audit attributed to `tests/test_layer_gate_logic.py`. This is the Phase 0.4 failure mode recurring outside the test harness, which `tests/__init__.py` does not cover. Fixed in the harness, not the strategy: `run_baseline` now calls `assert_logs_are_redirected()` and refuses to start. The polluted lines are left in place rather than edited out, per the standing rule that the record is preserved. | X-logging | P1 (harness) |

### Where the strategy spent its attention

Derived post-hoc from the immutable decision stream (sessions are not a stored
artifact, because with zero trades `exit_statistics.by_outcome_and_session` is
empty).

| Session | Decisions | Reached L8 | Dominant regime |
|---|---|---|---|
| Asian (00-07 UTC) | 5,040 (32.0%) | 430 | REGIME_SCALP 2,382 / MICRO_SCALP 2,313 |
| NewYork (13-21 UTC) | 4,999 (31.8%) | 228 | REGIME_SCALP 2,191 / DEAD_CALM 1,459 |
| London (07-13 UTC) | 4,316 (27.4%) | 607 | **MICRO_SCALP 2,736** |
| Dead (21-24 UTC) | 1,380 (8.8%) | 0 | DEAD_CALM 820 |

The session that got furthest through the layer stack is London, and London is
dominated by the one regime in which an entry is structurally impossible. Of its
607 L8 arrivals, the great majority were decided by `tp_ratio = 1.5` rather than
by the market.

### What this phase establishes

The export, validation, replay and measurement chain works on real broker data
and repeats exactly. The strategy, as it stands, produced no trades over ~3.5
months of real XAUUSD history, and the largest single identified cause is a
comparison against a configuration constant rather than against the market.
Nothing here was fixed.

## RECOMMENDED SEQUENCE

Ordered so that **safety precedes correctness, and measurement precedes tuning**.

1. **Phase 2 — execution safety model.** E1, E2, E3, E5, E6 + R1, R2, R3, R4.
   A real broker adapter, broker-side stops, reconciliation, correct sizing.
   Only after this may `LIVE_TRADING_ENABLED` be reconsidered.
2. **Phase 3 — backtest harness.** V1, V2 + migrate T1–T6 onto `core.clock`.
   Port L1–L8 unchanged. **Do not tune.** Establish the first baseline.
3. **Phase 4 — unit migration, measured.** U1–U12, A1–A4, B1–B6 together, one
   coherent change, measured against the Phase 3 baseline.
4. **Phase 5 — structural correctness.** S1, S2, S3, S7 + S8, S9.
5. **Phase 6 — validation.** Walk-forward, Monte Carlo, parameter sensitivity.
6. **Cleanup, in parallel.** X8, X10, X11, X12.

**Never tune a threshold before step 2 exists.** Without a baseline, a change that
increases trade count is indistinguishable from a change that increases losses.
