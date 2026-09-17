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

**994 of the 1,265 L8 blocks (78.6%) were decided before the market was
consulted.** `calculate_entry_levels` sets the target as
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
