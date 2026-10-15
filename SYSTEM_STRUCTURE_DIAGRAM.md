# TRADING BOT SYSTEM STRUCTURE DIAGRAM (UPDATED)
## Copy-Paste Ready Format

---

## 1. HIGH-LEVEL ARCHITECTURE (Mermaid)

```mermaid
graph TB
    subgraph "Main Loop [main_production.py]"
        A[main()<br/>5s循环] --> B[check_pre_trade_gates<br/>L0]
        B -->|PASS| C[Fetch Market Data<br/>MT5]
        C --> D[detect_regime<br/>entry_engine.py]
        D --> E[analyze_entry<br/>L1-L8 Sequential]
        E -->|ENTRY_SIGNAL| F[execute_entry_signal]
        E -->|PRE_ENTRY/ERROR| A
        F --> G[manage_positions<br/>L9]
        G --> H[feedback_loop<br/>L10]
        H --> A
    end

    subgraph "Layer Pipeline [analyze_entry]"
        E --> L1[L1: H4 Bias<br/>bias_engine.py]
        L1 --> L2[L2: H1 Structure<br/>structure_engine.py]
        L2 --> L3[L3: M15 Pullback<br/>pullback_detector.py]
        L3 --> L4[L4: Liquidity<br/>liquidity_engine.py]
        L4 --> L5[L5: Sweep+CHoCH<br/>sweep_detector.py]
        L5 --> L6[L6: POI<br/>poi_engine.py]
        L6 --> L7[L7: Confidence<br/>confidence_engine.py]
        L7 --> L8[L8: Entry Trigger<br/>entry_engine.py]
    end

    subgraph "Execution Stack"
        F --> R1[risk_manager.py<br/>calc_lot_size]
        F --> R2[order_execution.py<br/>OrderExecutor]
        R2 --> R3[MT5 / Simulation]
        F --> R4[trade_persistence.py<br/>save_active_trades]
    end

    subgraph "Support Systems"
        S1[error_recovery.py<br/>SystemMonitor]
        S2[error_recovery.py<br/>GracefulShutdown]
        S3[mt5_handler.py<br/>connect/get_data]
        S4[indicators.py<br/>RSI/MACD/EMA/ATR]
        S5[config.py<br/>CONFIG dict]
    end

    S3 --> C
    S4 --> L1
    S4 --> L2
    S4 --> L3
    S4 --> L7
    S5 --> A
    S1 --> A
    S2 --> A
```

---

## 2. MAIN LOOP FLOW (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  main_production.py :: main()                                              │
│  Loop: while _SHOULD_CONTINUE                                              │
│  Interval: 5 seconds                                                       │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────┐
        │  1. Get current spread from MT5                │
        │     get_current_spread(CONFIG["symbol"])        │
        └───────────────────────┬───────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────┐
        │  2. L0: Pre-Trade Gates                        │
        │     check_pre_trade_gates(spread)               │
        │     ├── Daily loss limit (5%)                   │
        │     ├── Spread monitoring (deferred to L8)      │
        │     └── Session check (Asian/London/NY/Dead)    │
        └───────────────────────┬───────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                 BLOCKED                  PASSED
                    │                       │
                    ▼                       ▼
        ┌───────────────────┐   ┌─────────────────────────────┐
        │ Sleep 60s         │   │ 3. Fetch Market Data         │
        │ Continue loop     │   │ ├── H4: 100 candles          │
        └───────────────────┘   │ ├── H1: 60 candles           │
                                │ ├── M15: 50 candles          │
                                │ ├── M5: 100 candles          │
                                │ ├── M1: 200 candles          │
                                │ ├── D1: 10 candles           │
                                │ └── current_price/spread     │
                                └─────────────┬───────────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │ 4. Regime Detection            │
                              │    detect_regime()             │
                              │    Based on M5 ATR:            │
                              │    • MICRO_SCALP 2.5-4.5       │
                              │    • REGIME_SCALP 4.5-7.0      │
                              │    • INTRADAY_SWING >7.0       │
                              │    • DEAD_CALM <2.5            │
                              └───────────────┬───────────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │ 5. analyze_entry() L1-L8       │
                              │    Sequential pipeline         │
                              └───────────────┬───────────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │ 6. print_run_summary()         │
                              │    log_signal() to CSV         │
                              └───────────────┬───────────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │ 7. ENTRY_SIGNAL?               │
                              └───────────────┬───────────────┘
                                              │
                                ┌─────────────┴─────────────┐
                                │                           │
                             YES                          NO
                                │                           │
                                ▼                           ▼
                ┌───────────────────────────┐   ┌─────────────────────┐
                │ execute_entry_signal()    │   │ Continue loop        │
                │ ├── Risk % by grade       │   │ (next iteration)     │
                │ ├── calc_lot_size()       │   └─────────────────────┘
                │ ├── create_order()        │
                │ ├── execute_order()       │
                │ └── _OPEN_TRADES.append() │
                └─────────────┬─────────────┘
                              │
                ┌─────────────▼─────────────┐
                │ Layer 9: manage_positions │
                │ ├── update_current_price  │
                │ ├── CLOSE_50PCT @ 1:1 RR  │
                │ ├── TRAIL_SL @ 1:2 RR     │
                │ └── CLOSE_ALL @ TP        │
                └─────────────┬─────────────┘
                              │
                ┌─────────────▼─────────────┐
                │ Layer 10: feedback_loop   │
                │ ├── log_closed_trade()    │
                │ └── weekly_performance()  │
                └─────────────┬─────────────┘
                              │
                ┌─────────────▼─────────────┐
                │ Persistence               │
                │ save_active_trades()      │
                │ (every 10 iterations)     │
                └──────────────────────────┘
```

---

## 3. DETAILED LAYER PIPELINE (L0-L8)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  L0: PRE-TRADE GATES                                                       │
│  File: main_production.py :: check_pre_trade_gates()                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Gate 1: Daily Loss Limit                                            │   │
│  │   current_daily_loss < -(balance * 5%)                              │   │
│  │   FAIL → BLOCK ALL → sleep 60s                                      │   │
│  │                                                                      │   │
│  │ Gate 2: Spread Monitoring                                           │   │
│  │   NOT checked here (deferred to L8 Entry Trigger)                   │   │
│  │   Reason: spread tolerance is REGIME-SPECIFIC                       │   │
│  │                                                                      │   │
│  │ Gate 3: Session Validation                                           │   │
│  │   DEAD (22:00-03:00 UTC) → BLOCK                                    │   │
│  │   LONDON / NY → PASS (Prime tier)                                   │   │
│  │   ASIAN → PASS (Tier 2, regime applies risk)                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │ PASS                                       │
└────────────────────────────────┼───────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────────────────┐
│  L1: H4 BIAS                                                               │
│  File: bias_engine.py :: get_h4_bias()                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Input: H4 indicators (EMA20, EMA50, ATR, close) + Daily data        │   │
│  │                                                                    │   │
│  │ Rules:                                                             │   │
│  │ • EMA20 vs EMA50 separation > ATR-scaled threshold                 │   │
│  │ • Last 2 closes vs EMA20 confirmation                              │   │
│  │ • Daily midpoint confirmation (price vs daily H/L mid)             │   │
│  │ • Daily close invalidation (flip if broken)                         │   │
│  │                                                                    │   │
│  │ Output: BULLISH | BEARISH | NEUTRAL + strength 0-10               │   │
│  │         + swing_high, swing_low, ema_distance                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                    NEUTRAL ─────┘                                            │
│                     BLOCK → return analysis                                  │
│                     BULLISH/BEARISH → continue                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L2: H1 STRUCTURE                                                           │
│  File: structure_engine.py :: get_h1_structure()                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Input: H1 data + expected_bias (from L1)                            │   │
│  │                                                                    │   │
│  │ Rules:                                                             │   │
│  │ • Find H1 swing highs/lows (fractal pattern)                       │   │
│  │ • BULLISH: last 5 candles show HH/HL progression                   │   │
│  │ • BEARISH: last 5 candles show LH/LL progression                   │   │
│  │ • ATR check: H1 ATR < 8 pips = DEAD CALM → BLOCK                   │   │
│  │ • Close beyond last swing = BROKEN → BLOCK                         │   │
│  │                                                                    │   │
│  │ Output: VALID | BROKEN | UNKNOWN + confidence 0-10                 │   │
│  │         + last_swing_high, last_swing_low                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│              BROKEN/DEAD CALM ────┘                                          │
│               BLOCK → return analysis                                        │
│               UNKNOWN → WARN but PASS (confidence=0)                         │
│               VALID → continue                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L3: M15 PULLBACK                                                           │
│  File: pullback_detector.py :: get_m15_pullback()                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Input: M15 data + expected_bias + regime_info                       │   │
│  │                                                                    │   │
│  │ Bypass Logic:                                                      │   │
│  │ • If regime_info["bypass_l3"] == True → SKIP gate                  │   │
│  │   (MICRO_SCALP momentum entries don't need pullback)               │   │
│  │                                                                    │   │
│  │ Standard Rules (when not bypassed):                                │   │
│  │ • Detect counter-trend phase on M15                                │   │
│  │ • Retracement accepted 23.6%-78.6% of the last impulse             │   │
│  │ • Ideal zone 38.2%-61.8% -> top base score (5.5)                   │   │
│  │ • 61.8% is the ideal-zone edge, NOT a rejection cutoff             │   │
│  │ • 61.8%-78.6% accepted, scored 4.0                                 │   │
│  │ • Structure LH/LL / HH/HL: +3.0 bonus, NOT required                │   │
│  │ • Volume contraction over window: +1.5/+0.5/+0.0                   │   │
│  │   (temporal, direction-blind; not a standalone gate)               │   │
│  │ • EMA alignment +0.5 -- NOT an EMA20/50 crossover;                 │   │
│  │   inert: raw M15 frame carries no ema20/ema50                      │   │
│  │                                                                    │   │
│  │ Output: pullback_detected (bool) + quality (0.0-10.0)              │   │
│  │         + volume_warning flag                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                     NOT DETECTED ────┘                                       │
│                      BLOCK → return analysis                                 │
│                      QUALITY < 1.5 → inert, cannot fire (L3-D5)              │
│                      PASS → continue                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L4: LIQUIDITY POOLS                                                        │
│  File: liquidity_engine.py                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ identify_liquidity_pools():                                         │   │
│  │   • sweep_pool: stop-loss cluster level + score                     │   │
│  │   • tp_pool: take-profit cluster level + score                      │   │
│  │                                                                    │   │
│  │ assess_liquidity_gate():                                            │   │
│  │   • sweep_score threshold                                           │   │
│  │   • sweep_distance from current price                               │   │
│  │   • tp_score quality                                                │   │
│  │                                                                    │   │
│  │ Output: pools_found + sweep_pool + tp_pool + state (PASS/BLOCK)     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                          BLOCK ────┘                                         │
│                           BLOCK → return analysis                            │
│                           PASS → continue                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L5: SWEEP + STRUCTURE                                                      │
│  File: sweep_detector.py :: get_sweep_and_structure()                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Input: M15 + H1 data + L4 sweep level + bias direction              │   │
│  │                                                                    │   │
│  │ Rules:                                                             │   │
│  │ • Price sweeps liquidity pool (stop hunt)                           │   │
│  │ • CHoCH / BOS detection                                             │   │
│  │ • Sweep direction matches bias?                                     │   │
│  │                                                                    │   │
│  │ Output: gate_state (PASS | WATCH | BLOCK)                           │   │
│  │         + sweep_confirmed + setup_grade + gate_reason               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                    WATCH ─────────┘                                          │
│                     WAIT → return analysis (L5_SWEEP_WAIT)                   │
│                     NOT CONFIRMED → BLOCK                                    │
│                     WRONG DIRECTION → BLOCK                                  │
│                     PASS → continue                                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L6: POI QUALITY                                                            │
│  File: poi_engine.py :: identify_poi()                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Input: M15 + H1 data + direction + current_price                    │   │
│  │                                                                    │   │
│  │ Bypass Logic:                                                      │   │
│  │ • If regime_info["bypass_l6"] == True → SKIP gate                  │   │
│  │   (MICRO_SCALP doesn't need POI confluence)                        │   │
│  │                                                                    │   │
│  │ Standard Rules:                                                    │   │
│  │ • Order blocks (OB) identification                                 │   │
│  │ • Fair value gaps (FVG)                                            │   │
│  │ • Dynamic threshold:                                               │   │
│  │   - sweep_confirmed=True → threshold = 60                          │   │
│  │   - else → threshold = 70                                          │   │
│  │                                                                    │   │
│  │ Output: best_poi + score + type + zone bounds                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                     NO POI / SCORE LOW ────┘                                │
│                      BLOCK → return analysis                                 │
│                      PASS → continue                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L7: CONFIDENCE SCORE                                                       │
│  File: confidence_engine.py :: get_confidence_engine()                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Formula:                                                            │   │
│  │   bias_component    = bias_strength * 0.24                          │   │
│  │   structure_component = structure_confidence * 0.20                 │   │
│  │   sweep_component   = sweep_quality * 0.20                          │   │
│  │   poi_component     = poi_score * 0.20                              │   │
│  │   cohesion_component = min(16, strong_signals * 4)                  │   │
│  │   session_bonus     = +8 (LONDON/NY), 0 (ASIAN), -15 (DEAD)        │   │
│  │   + Fib confluence bonus                                            │   │
│  │   + RSI neutral bonus                                               │   │
│  │                                                                    │   │
│  │ Output: final_score (0-100) + grade + reasoning                     │   │
│  │   • A+ : >= 85                                                      │   │
│  │   • A  : >= 70 (REGIME_SCALP) or >= 55 (MICRO_SCALP)               │   │
│  │   • REJECT: below threshold                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                     SCORE < THRESHOLD                                         │
│                      BLOCK → return analysis (L7_CONFIDENCE)                 │
│                      PASS → continue                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  L8: ENTRY TRIGGER + REGIME SPREAD CHECK                                    │
│  File: entry_engine.py :: get_entry_trigger() + detect_regime()             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 1: Spread Check (Regime-Specific)                              │   │
│  │   • MICRO_SCALP: max 5 pips                                        │   │
│  │   • REGIME_SCALP: max 7 pips                                       │   │
│  │   • INTRADAY_SWING: max 10 pips                                    │   │
│  │   Exceeds → REJECTED                                                │   │
│  │                                                                    │   │
│  │ Step 2: Entry Trigger Detection                                     │   │
│  │   • Rejection candle (wick >= 2x body)                              │   │
│  │   • Close in upper 50% (BUY) or lower 50% (SELL)                   │   │
│  │   • Next M1 close confirmation                                      │   │
│  │   • Volume > 20-candle baseline                                     │   │
│  │   • RSI turning up/down                                             │   │
│  │   • MACD histogram flip                                             │   │
│  │                                                                    │   │
│  │ Step 3: evaluate_entry_for_regime()                                 │   │
│  │   • RR validation                                                   │   │
│  │   • Entry mode (MARKET/LIMIT)                                       │   │
│  │                                                                    │   │
│  │ Output: entry_triggered (bool) + setup_type + rr_ratio              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                     SPREAD WIDE ────┘                                        │
│                      REJECTED → return analysis                              │
│                      TRIGGER NOT FIRED → WAIT                                │
│                      ALL PASS → ENTRY_SIGNAL                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. EXECUTION & MANAGEMENT FLOW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXECUTION PIPELINE                                                         │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                 │
│  │ entry_signal │───▶│ Risk Manager │───▶│ OrderExecutor│                 │
│  │ (from L8)    │    │ calc_lot_size│    │ create_order │                 │
│  └──────────────┘    │ for_symbol() │    │ + execute    │                 │
│                      └──────────────┘    └──────┬───────┘                 │
│                             │                   │                         │
│                      risk_pct:                 │                         │
│                      • A+ grade = 1.5%         ▼                         │
│                      • A grade  = 1.0%   ┌──────────────┐                 │
│                      • MICRO_SCALP     │ MT5 Live     │                 │
│                        uses grade      │ or Sim mode   │                 │
│                      thresholds         └──────┬───────┘                 │
│                             │                   │                         │
│                             │                   ▼                         │
│                             │            ┌──────────────┐                 │
│                             │            │ Trade Persist│                 │
│                             │            │ save_active_  │                 │
│                             │            │ trades()      │                 │
│                             │            └──────┬───────┘                 │
│                             │                   │                         │
│                             ▼                   ▼                         │
│                      ┌──────────────────────────────────┐                  │
│                      │ Layer 9: Position Management     │                  │
│                      │ trade_manager.py / manage_positions│                │
│                      │                                    │                │
│                      │ For each open trade:               │                │
│                      │ • Update current price             │                │
│                      │ • Check RR milestones:             │                │
│                      │   - 1:1 RR → CLOSE_50PCT          │                │
│                      │   - 1:2 RR → TRAIL_SL             │                │
│                      │   - 1:3 RR → CLOSE_ALL (TP)       │                │
│                      │ • Close position at TP             │                │
│                      │ • Remove from _OPEN_TRADES         │                │
│                      └────────────────┬─────────────────┘                  │
│                                       │                                   │
│                                       ▼                                   │
│                      ┌──────────────────────────────────┐                  │
│                      │ Layer 10: Feedback Loop          │                  │
│                      │ feedback_loop.py                 │                  │
│                      │                                    │                │
│                      │ • log_closed_trade()              │                │
│                      │ • calculate_weekly_performance()  │                │
│                      │ • Auto-adjust parameters          │                │
│                      └──────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. REGIME DETECTION DETAIL

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  detect_regime() [entry_engine.py]                                          │
│  Called BEFORE L1 in analyze_entry()                                        │
│                                                                             │
│  Inputs: M5 ATR, kill_zone, session, H1 structure valid, current_spread     │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ MICRO_SCALP                                                          │   │
│  │ Condition: M5 ATR 2.5-4.5 AND (kill_zone OR active session)         │   │
│  │ Config:                                                              │   │
│  │   risk_percent = 0.75%                                               │   │
│  │   tp_ratio = 1.5R                                                    │   │
│  │   bypass_l3 = True                                                   │   │
│  │   bypass_l6 = True                                                   │   │
│  │   poi_threshold = 50                                                 │   │
│  │   max_spread_pips = 5.0                                              │   │
│  │   spread_acceptable = current_spread <= 5.0                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ REGIME_SCALP                                                         │   │
│  │ Condition: M5 ATR 4.5-7.0                                            │   │
│  │ Config:                                                              │   │
│  │   risk_percent = 1.0%                                                │   │
│  │   tp_ratio = 2.0R                                                    │   │
│  │   bypass_l3 = False                                                  │   │
│  │   bypass_l6 = False                                                  │   │
│  │   poi_threshold = 60                                                 │   │
│  │   max_spread_pips = 7.0                                              │   │
│  │   spread_acceptable = current_spread <= 7.0                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ INTRADAY_SWING                                                       │   │
│  │ Condition: M5 ATR > 7.0                                              │   │
│  │ Config:                                                              │   │
│  │   risk_percent = 1.5%                                                │   │
│  │   tp_ratio = 3.0R                                                    │   │
│  │   bypass_l3 = False                                                  │   │
│  │   bypass_l6 = False                                                  │   │
│  │   poi_threshold = 70                                                 │   │
│  │   max_spread_pips = 10.0                                             │   │
│  │   spread_acceptable = current_spread <= 10.0                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ DEAD_CALM                                                            │   │
│  │ Condition: M5 ATR < 2.5                                              │   │
│  │ Config: (Will be blocked at L2 anyway)                               │   │
│  │   risk_percent = 0.75%                                               │   │
│  │   tp_ratio = 1.5R                                                    │   │
│  │   bypass_l3 = False                                                  │   │
│  │   bypass_l6 = False                                                  │   │
│  │   poi_threshold = 70                                                 │   │
│  │   max_spread_pips = 5.0                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. DATA STRUCTURES (UPDATED)

### 6.1 Analysis Result Dict
```python
analysis = {
    "timestamp": str,                    # ISO timestamp
    "signal_type": str,                  # "ENTRY_SIGNAL" | "PRE_ENTRY" | "REJECTED" | "ERROR"
    "layers_passed": list[str],          # e.g. ["L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_BYPASSED", ...]
    "layer_failed": str | None,          # e.g. "L7_CONFIDENCE" | "L3_PULLBACK" | "L5_SWEEP_WAIT"
    "fail_reason": str,                  # Human-readable failure reason
    "direction": str,                    # "BUY" | "SELL"
    "current_price": float | None,
    "regime_info": dict | None,          # From detect_regime()
    "candidate_entry_style": str,        # "PULLBACK" | "MOMENTUM" | "PULLBACK / MOMENTUM"
    "layer_1": dict,                     # bias result
    "layer_2": dict,                     # structure result
    "layer_3": dict | None,              # pullback result
    "layer_4": dict | None,              # liquidity result
    "layer_5": dict | None,              # sweep result
    "layer_6": dict | None,              # poi result
    "layer_7": dict | None,              # confidence result
    "layer_8": dict | None,              # entry trigger result
    "entry_signal": dict | None,         # Final entry details (if ENTRY_SIGNAL)
}
```

### 6.2 Regime Info Dict
```python
regime_info = {
    "regime": str,                # "MICRO_SCALP" | "REGIME_SCALP" | "INTRADAY_SWING" | "DEAD_CALM"
    "m5_atr": float,              # M5 ATR value
    "kill_zone": bool,            # In London 08-10 or NY 12-14 UTC
    "h1_structure_valid": bool,   # Rough H1 structure check
    "risk_percent": float,        # 0.75, 1.0, 1.5
    "tp_ratio": float,            # 1.5, 2.0, 3.0
    "bypass_l3": bool,            # Skip pullback gate?
    "bypass_l6": bool,            # Skip POI gate?
    "poi_threshold": int,         # 50, 60, or 70
    "max_spread_pips": float,     # 5.0, 7.0, or 10.0
    "current_spread": float,      # Actual spread
    "spread_acceptable": bool,    # current_spread <= max_spread_pips
    "reasoning": str,             # Human-readable regime detection reason
}
```

### 6.3 Entry Signal Dict
```python
entry_signal = {
    "position_type": str,         # "BUY" | "SELL"
    "entry_price": float,
    "stop_loss": float,
    "take_profit": float,
    "rr_ratio": float,            # 1:3.0 for A+, 1:2.0 for A
    "grade": str,                 # "A+" | "A"
    "setup_type": str,            # e.g. "SWEEP_PULLBACK"
    "entry_method": str,          # "PULLBACK" | "MOMENTUM"
    "entry_mode": str,            # "MARKET" | "LIMIT"
    "trigger_type": str,          # "REJECTION_CANDLE" | "MOMENTUM_BREAK"
    "rr_valid": bool,
    "poi_type": str,              # "ORDER_BLOCK" | "FVG" | "N/A"
    "timestamp": str,             # ISO timestamp
}
```

### 6.4 Open Trade Dict
```python
trade = {
    "trade_id": str,              # Unique trade ID
    "order_id": str,              # MT5 order ticket
    "entry_price": float,
    "stop_loss": float,
    "take_profit": float,
    "position_type": str,         # "BUY" | "SELL"
    "entry_time": str,            # ISO timestamp
    "status": str,                # "OPEN"
    "position_size": float,       # Lot size
    "state": dict | None,         # Trade state object
    "last_check": str,            # ISO timestamp of last management check
}
```

### 6.5 Confidence Result Dict
```python
confidence_result = {
    "final_score": float,         # 0-100
    "grade": str,                 # "A+" | "A" | "REJECT"
    "confidence_breakdown": {
        "bias_component": float,      # 0-24
        "structure_component": float, # 0-20
        "sweep_component": float,     # 0-20
        "poi_component": float,       # 0-20
        "cohesion_component": float,  # 0-16
        "session_bonus": float,       # -15 to +8
    },
    "reasoning": str,             # e.g. "Bias 80% (x0.24=19.2) | Structure 0% ..."
    "a_plus_checklist": {
        "checks_passed": int,     # 0-7
        "qualifies_for_a_plus": bool,
    },
    "recommendation": str,
}
```

---

## 7. CONFIGURATION CONSTANTS (EXACT)

```python
CONFIG = {
    # Symbol & Mode
    "symbol": "XAUUSD",
    "demo_mode": False,           # LIVE trading

    # Position Limits
    "max_concurrent_trades": 3,
    "max_daily_loss_percent": 5.0,

    # Risk per Trade (% of balance)
    "risk_per_trade_a_plus": 1.5,   # A+ grade
    "risk_per_trade_a": 1.0,        # A grade

    # Data Requirements (candles)
    "h4_candles_required": 100,
    "h1_candles_required": 60,
    "m15_candles_required": 50,
    "m5_candles_required": 100,
    "m1_candles_required": 200,
}

# Derived Constants
MIN_PULLBACK_QUALITY = 1.5
MICRO_SCALP_THRESHOLD = 55      # Confidence threshold
REGIME_SCALP_THRESHOLD = 70     # Confidence threshold
A_PLUS_THRESHOLD = 85           # Confidence threshold for A+

# Spread Tolerances (pips)
MICRO_SCALP_MAX_SPREAD = 5.0
REGIME_SCALP_MAX_SPREAD = 7.0
INTRADAY_SWING_MAX_SPREAD = 10.0

# TP Ratios (R)
MICRO_SCALP_TP_RATIO = 1.5
REGIME_SCALP_TP_RATIO = 2.0
INTRADAY_SWING_TP_RATIO = 3.0

# L2 ATR Thresholds (pips)
DEAD_CALM_ATR_THRESHOLD = 8.0
HIGH_VOLATILITY_ATR = 15.0

# Kill Zones (UTC hours)
KILL_ZONES_UTC = ((8, 10), (12, 14))  # London 08-10, NY 12-14

# File Paths
SIGNAL_LOG_FILE = "signal_log.csv"
PRODUCTION_LOG = "trading_bot_production.log"
ACTIVE_TRADES_FILE = "active_trades.json"
```

---

## 8. BRANCH DECISION TABLE

| Layer | File | Function | PASS | BLOCK/WAIT |
|-------|------|----------|------|------------|
| L0 | main_production.py | check_pre_trade_gates() | Daily loss OK + session valid | Daily loss exceeded, DEAD session |
| L1 | bias_engine.py | get_h4_bias() | BULLISH or BEARISH | NEUTRAL |
| L2 | structure_engine.py | get_h1_structure() | VALID or UNKNOWN | BROKEN, DEAD CALM (ATR<8) |
| L3 | pullback_detector.py | get_m15_pullback() | detected=True, quality>=1.5 OR bypass_l3 | detected=False, quality<1.5 |
| L4 | liquidity_engine.py | assess_liquidity_gate() | State=PASS | State=BLOCK |
| L5 | sweep_detector.py | get_sweep_and_structure() | sweep_confirmed=True, direction matches | gate_state=WATCH, not confirmed, wrong direction |
| L6 | poi_engine.py | identify_poi() | best_poi.score >= threshold OR bypass_l6 | No POI, score < threshold |
| L7 | confidence_engine.py | get_confidence_engine() | score >= 55 (MICRO) or >= 70 (REGIME) | score < threshold |
| L8 | entry_engine.py | get_entry_trigger() + evaluate_entry_for_regime() | entry_triggered=True + spread OK + gate passes | spread too wide, trigger not ready, gate fails |

---

## 9. FILE IMPORT DEPENDENCIES

```
main_production.py
├── config.py
├── mt5_handler.py
├── bias_engine.py                    [L1]
├── structure_engine.py               [L2]
├── pullback_detector.py              [L3]
├── liquidity_engine.py               [L4]
├── sweep_detector.py                 [L5]
├── poi_engine.py                     [L6]
├── confidence_engine.py              [L7]
├── entry_engine.py                   [L8 + Regime]
├── trade_manager.py                  [L9]
├── feedback_loop.py                  [L10]
├── trade_persistence.py              [Persistence]
├── risk_manager.py                   [Sizing]
├── order_execution.py                [Execution]
├── error_recovery.py                 [Error Handling]
├── indicators.py                     [Indicators]
└── utils.py                          [Helpers]
```

---

## 10. STATE & SIGNAL FLOW

```
START
  │
  ├─▶ load_active_trades() ──▶ _OPEN_TRADES restored
  │
  ├─▶ signal_module.signal(SIGINT, handler)
  ├─▶ signal_module.signal(SIGTERM, handler)
  │
  └─▶ MAIN LOOP ─────────────────────────────────────────────────────────┐
       │                                                                   │
       ├─▶ [L0] check_pre_trade_gates() ──▶ pass/fail                    │
       ├─▶ MT5 data fetch                                                 │
       ├─▶ detect_regime() ──▶ regime_info                                │
       ├─▶ [L1-L8] analyze_entry() ──▶ analysis dict                     │
       │    ├─ signal_type = "ENTRY_SIGNAL"                               │
       │    ├─ signal_type = "PRE_ENTRY"  (most common)                   │
       │    └─ signal_type = "ERROR"                                      │
       ├─▶ print_run_summary()                                            │
       ├─▶ log_signal() ──▶ signal_log.csv                                │
       │                                                                   │
       ├─▶ IF ENTRY_SIGNAL:                                               │
       │    └─▶ execute_entry_signal()                                     │
       │         ├─▶ calculate_lot_size()                                  │
       │         ├─▶ order_executor.create_order()                         │
       │         ├─▶ order_executor.execute_order()                        │
       │         └─▶ _OPEN_TRADES.append(trade)                            │
       │                                                                   │
       ├─▶ [L9] manage_positions({})                                      │
       │    ├─▶ order_executor.update_current_price()                     │
       │    ├─▶ CLOSE_50PCT / TRAIL_SL / CLOSE_ALL                        │
       │    └─▶ _OPEN_TRADES cleanup                                      │
       │                                                                   │
       ├─▶ [L10] feedback_loop (on closed trades)                         │
       │                                                                   │
       ├─▶ save_state() ──▶ every 10 iterations                           │
       │                                                                   │
       └─▶ time.sleep(5)                                                   │
            │                                                               │
            └─▶ LOOP AGAIN                                                 │
                                                                           │
SHUTDOWN SIGNAL (SIGINT/SIGTERM) ─────────────────────────────────────────┘
  │
  └─▶ graceful_shutdown()
       ├─▶ Close all MT5 positions
       ├─▶ save_active_trades()
       ├─▶ shutdown_mt5()
       └─▶ shutdown_mgr.shutdown(_OPEN_TRADES, monitor)
```

---

## 11. KNOWN ISSUES FROM CODE ANALYSIS

| # | Issue | Location | Description |
|---|-------|----------|-------------|
| 1 | L2 passes UNKNOWN with 0 confidence | main_production.py:699-703 | L2 allows UNKNOWN structure through but passes `structure_confidence=0` to L7 |
| 2 | L7 unreachable threshold | main_production.py:869-875 | With structure=0, max possible score is ~48, but threshold is 55/70 |
| 3 | bypass_l3 not honored (FIXED) | main_production.py:720-723 | Was bypassed; now correctly checked at line 720 |
| 4 | bypass_l6 not honored (FIXED) | main_production.py:851-853 | Was bypassed; now correctly checked at line 851 |
| 5 | Pullback detected flag | pullback_detector.py | quality can be 7.0 but `detected=False` causes block |
| 6 | Bias midpoint weak penalty | bias_engine.py:166-170 | Close < midpoint only reduces strength by 2, doesn't block |
| 7 | Unexpected restarts | main_production.py:1305 | SIGTERM handler active; external watchdog may trigger |
| 8 | Hardcoded confidence_score | main_production.py:1063 | Uses 80.0 instead of actual conf.get("final_score") |

---

Generated: 2026-07-07
System: zoyaintraday_bot_v2 (10-Layer Production Trading Bot)
File: main_production.py + 10 layer modules
