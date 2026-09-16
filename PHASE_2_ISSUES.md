# PHASE 2+ ISSUE REGISTER

Defects identified during the Phase 1 audit and confirmed during Phase 0/1
implementation, that were **deliberately left unchanged**.

Phase 0/1 forbids strategy optimisation, threshold tuning and behavioural change.
Every item below would alter trading behaviour, and there is currently **no
measured baseline** against which to judge whether a change is an improvement.
Fixing them before the backtest harness exists would mean swapping one unvalidated
configuration for another and calling it progress.

**Nothing here has been tuned, adjusted, or "improved".**

Legend — P0 critical · P1 high · P2 medium · P3 low

---

## 1. UNIT CONFUSION (price units vs pips)

The single most widespread defect class. `core/units.py` now makes the correct
form expressible; these call sites have **not** been migrated.

XAUUSD: 1 pip = $0.10 = 10 points. A threshold named "pips" but applied to a raw
price is therefore **10x** its intended size.

| # | Location | Code | Intended | Actual | Priority |
|---|---|---|---|---|---|
| U1 | `entry_engine.py:362` `_select_stop_anchor` | `min(candidates) - buffer_pips` (`buffer_pips=3.0`) | 3 pips | **$3.00 = 30 pips** | **P0** |
| U2 | `liquidity_engine.py:368` `score_liquidity_pool` | `if distance <= 2.0: score += 25` | 2 pips | **$2.00 = 20 pips** | P1 |
| U3 | `liquidity_engine.py:374-380` | `if distance > 50 / > 30: penalty` | 50/30 pips | **$50/$30 = 500/300 pips** | P1 |
| U4 | `liquidity_engine.py:753` `assess_liquidity_gate` | `max_sweep_distance = 60.0` | 60 pips | **$60 = 600 pips — no effective cap** | P1 |
| U5 | `poi_engine.py:437` `score_poi` | `if 5 <= zone_size <= 15: score += 15` | 5–15 pips | **$5–$15 — essentially never fires** | P1 |
| U6 | `poi_engine.py:428` `score_poi` | `if displacement >= 20 / >= 10` | 20/10 pips | **$20/$10** | P1 |
| U7 | `poi_engine.py:194` `detect_order_block` | `if body >= 5` | 5 pips | **$5 M15 body — very rare** | P1 |
| U8 | `sweep_detector.py:196` `detect_sweep` | `sweep_min = max(2.5, atr*0.12)` | 2.5 pips | **$2.50 = 25 pips minimum sweep** | **P0** |
| U9 | `main_production.py` L2 gate | `h1_atr < 8.0` described as "pips" | 8 pips | **$8.00 = 80 pips** | P1 |
| U10 | `entry_engine.py:76-108` `detect_regime` | ATR bands `2.5 / 4.5 / 7.0` labelled "pip" | pips | **dollars** | **P0** |
| U11 | `main_production.py` `_check_regime_scalp_momentum` | `pip_size = 0.10` hardcoded inline | — | duplicates broker data | P2 |
| U12 | `mt5_handler.py:150` `get_current_spread` | `XAUUSD_PIP_SIZE = 0.10` hardcoded | — | **correct today**, but breaks silently if the broker changes quote precision | P2 |

**U8 and U10 are the highest-leverage items in this register.** U8 sets the
minimum wick depth for a sweep and is one of the busiest rejection gates
(9,238 of 39,709 decisions blocked at L5). U10 determines which regime is
selected, and therefore which thresholds, risk and bypasses apply.

**Do not fix these individually.** They interact: correcting U8 alone changes the
sweep rate, which changes L5/L7 pass rates, which changes everything downstream.
They should be migrated together onto `core.units`, behind a backtest that can
measure the result.

---

## 2. POSITION SIZING AND RISK

| # | Location | Issue | Priority |
|---|---|---|---|
| R1 | `risk_manager.py:18` | `lot = risk_amount / (stop_distance * 10.0)`. XAUUSD contract size is **100**, not 10, so every position is **~10x oversized**. `SymbolSpecification.money_per_price_unit()` returns the correct `100.0`; it is **not** wired in. | **P0** |
| R2 | `main_production.py:444, :1045` | `account_balance: float = 10000` hardcoded. `mt5.account_info()` is called once for a log line and discarded. Every risk figure is fictional. | **P0** |
| R3 | `main_production.py` `check_pre_trade_gates` | Called without `current_daily_loss`, so it defaults to `0` and `0 < -max_daily_loss` is never true. The daily-loss breaker cannot fire. | **P0** |
| R4 | system-wide | No realised-P&L tracking anywhere. Nothing knows whether the account is up or down. | **P0** |
| R5 | `risk_manager.py:22` | `max(0.01, round(lot,2))` silently inflates a sub-minimum size instead of declining the trade. `SymbolSpecification.is_volume_tradeable()` exists for the correct behaviour. | P1 |
| R6 | `risk_manager.py:23` | `min(lot, 1.0)` ignores `config.INTRADAY_LOT_SIZE_MAX = 0.1`. | P1 |
| R7 | system-wide | No max-drawdown limit, no consecutive-loss limit, no equity-curve kill switch. | P1 |
| R8 | `main_production.py` | `max_concurrent_trades = 3` on one symbol is 3x the same risk; no exposure cap. | P1 |
| R9 | `config.py` | `INTRADAY_MAX_HOLD_MINUTES = 240` defined, never enforced. No time stop. | P1 |

---

## 3. BAR CONVENTION VIOLATIONS

`core/candles.py` defines the canonical convention. Because
`get_market_data(closed_only=True)` already drops the forming bar, `iloc[-1]`
**is** the last closed bar. These sites disagree:

| # | Location | Uses | Effect | Priority |
|---|---|---|---|---|
| B1 | `entry_engine.py:158` `detect_rejection_candle` | `iloc[-2]` | one bar stale (5 min on M5) | P1 |
| B2 | `entry_engine.py:196` `detect_momentum_confirmation` | `iloc[:-1].tail(3)` | one bar stale | P1 |
| B3 | `entry_engine.py:~490` `_evaluate_pullback_entry` | `iloc[-2]["close"]` as entry price | entry priced off a stale bar | **P0** |
| B4 | `main_production.py` `confirmed_m5_close` | `iloc[-2]["close"]` | stale price passed as `current_price` into L8 | **P0** |
| B5 | `pullback_detector.py:221` | `recent.iloc[:-1]` | **double-drop** — removes a forming bar that is not there | P1 |
| B6 | `entry_engine.py:228` `detect_displacement_candle` | `iloc[-1]` | correct — but inconsistent with B1/B2 in the same pass | P1 |

B3/B4 mean a **pullback entry is priced off a bar that closed five minutes ago
while a momentum entry uses the current one**, on a strategy targeting 15–25 pip
moves.

Additionally: `_evaluate_momentum_entry` checks `price_in_fvg` against the stale
`current_price` it was handed, not the live tick — which *is* fetched, logged,
and then discarded.

---

## 4. ATR FRAGMENTATION

`core/indicators.atr_wilder` is the canonical definition. Four incompatible
implementations remain live:

| # | Location | Definition | Priority |
|---|---|---|---|
| A1 | `indicators.py:130` | `pandas_ta.atr` — true Wilder ATR (correct) | P2 |
| A2 | `pullback_detector.py:69` `_estimate_recent_atr` | correct true range, but **SMA-14**, not Wilder | P1 |
| A3 | `sweep_detector.py:51` `_estimate_m15_atr` | `close.diff().abs().rolling(14).mean()` — **ignores high/low entirely** | **P0** |
| A4 | `main_production.py` `h1_atr` | `mean(high - low)` over 14 bars — **ignores gaps** | P1 |

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
