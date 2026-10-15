# Architecture Flow - Issues Highlighted

```
XAUUSD TRADING BOT - 11-LAYER ENTRY FLOW WITH IDENTIFIED FLAWS
═══════════════════════════════════════════════════════════════════════

MARKET DATA (H4, H1, M15, M5, M1 candles)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 0: PRE-TRADE GATES                                        │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Spread check                                                 │
│  🔴 FLAW #1: Daily loss check uses abs() - blocks profit days  │
│  ✓ Session detection                                            │
│                                                                 │
│  → If any gate fails: NO_SIGNAL (return)                       │
└─────────────────────────────────────────────────────────────────┘
    │ (All gates pass)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: H4 BIAS ENGINE (Direction Lock)                       │
├─────────────────────────────────────────────────────────────────┤
│  ✓ EMA20/EMA50 distance calculation                            │
│  ✓ Bias strength scoring (0-10)                                │
│  🟠 FLAW #2: Daily invalidation logic exists but never runs   │
│             (validate_bias_with_daily_close orphaned)          │
│                                                                 │
│  → Output: BULLISH | BEARISH | NEUTRAL                        │
│  → If NEUTRAL: REJECT_SIGNAL                                   │
└─────────────────────────────────────────────────────────────────┘
    │ (Bias determined)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2: H1 STRUCTURE ENGINE                                    │
├─────────────────────────────────────────────────────────────────┤
│  🟡 FLAW #3: Swing detection returns oldest fractal, not newest│
│  🟠 FLAW #4: HH/HL validation checks 1 candle, not series     │
│                                                                 │
│  → Validates HH/HL (bullish) or LH/LL (bearish)               │
│  → If broken: Warning (continues anyway)                       │
│  → Output: structure_valid bool, confidence 0-10               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3: M15 PULLBACK DETECTOR                                  │
├─────────────────────────────────────────────────────────────────┤
│  🔴 FLAW #5: Fibonacci calculation inverted                    │
│             (bearish uses swing_high instead of swing_low)     │
│                                                                 │
│  🟠 FLAW #6: LH/LL detection checks 1 candle vs 2, not series │
│                                                                 │
│  → Output: pullback_detected bool                              │
│           pullback_depth_fib (0.236-0.786)                    │
│           pullback_quality (0-10)                              │
│                                                                 │
│  ⚠️  Impact: Entry zones completely wrong due to Fib error    │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 4: LIQUIDITY ENGINE                                       │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Find equal lows/highs (2+ touches)                         │
│  ✓ Find Asian extremes                                         │
│  ✓ Find round numbers (25-pip intervals)                      │
│  ✓ Score pools (0-100)                                        │
│                                                                 │
│  ✓ DIRECTIONAL FILTER: BUY targets above price, SELL below    │
│    (Fixed previously - L4 now working correctly)              │
│                                                                 │
│  🟡 FLAW #7: Recency scoring doesn't penalize stale pools    │
│                                                                 │
│  → Output: liquidity_pools list                               │
│  → If no score ≥70: REJECT_SIGNAL                             │
│  → Select target_pool (highest scoring + directional)         │
└─────────────────────────────────────────────────────────────────┘
    │ (High-quality pool selected)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 5: SWEEP + CHoCH/BOS DETECTOR                            │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Sweep detection (wick penetration + candle close-back)     │
│  🔴 FLAW #8: CHoCH LH/LL finding logic inverted               │
│             (finds ANY lower point, not swing high sequence)  │
│                                                                 │
│  🟡 FLAW #9: BOS uses max/min instead of swing points        │
│             (detects noise spikes, not structure)             │
│                                                                 │
│  🔴 FLAW #15: NO directional validation                      │
│              (could accept bearish sweep on BUY signal)       │
│                                                                 │
│  → Output: sweep_confirmed bool                               │
│           choch_confirmed bool                                │
│           bos_confirmed bool                                  │
│           sweep_quality (0-10)                                │
│                                                                 │
│  → If no sweep/CHoCH: REJECT_SIGNAL                          │
└─────────────────────────────────────────────────────────────────┘
    │ (Sweep/CHoCH confirmed)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 6: POI ENGINE (Order Block/FVG/Fib)                      │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Order block detection (strong displacement)                │
│  🟡 FLAW #10: OB size criteria too loose (5 pips)            │
│              (picks up every small candle)                    │
│                                                                 │
│  ✓ FVG detection (unfilled gaps ≥3 pips)                    │
│  ✓ Fib retracement (0.5 / 0.618 levels)                     │
│  ✓ Scoring formula (0-100)                                   │
│                                                                 │
│  → Output: best_poi with score (0-100)                        │
│  → If score < 70: REJECT_SIGNAL                              │
│  → POI Type: Order Block | FVG | Fib | Breaker               │
└─────────────────────────────────────────────────────────────────┘
    │ (Quality POI identified)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 7: CONFIDENCE SCORE ENGINE                                │
├─────────────────────────────────────────────────────────────────┤
│  ✓ 5-component weighted scoring:                              │
│    • Bias strength (25%)                                      │
│    • Structure confidence (20%)                               │
│    • Sweep quality (20%)                                      │
│    • POI score (20%)                                          │
│    • Session bonus (10%)                                      │
│                                                                 │
│  ✓ Grade assignment: A+ (85-100) | A (70-84) | REJECT (<70) │
│                                                                 │
│  → Output: final_score (0-100), grade                         │
│  → If REJECT: REJECT_SIGNAL                                  │
└─────────────────────────────────────────────────────────────────┘
    │ (Grade assigned)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 8: M5/M1 ENTRY TRIGGERS                                   │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Rejection candle detection (M5 wick ≥2x body)             │
│  🟠 FLAW #12: Momentum doesn't reject extreme RSI             │
│              (enters in overbought/oversold)                  │
│                                                                 │
│  ✓ Momentum confirmation (volume, RSI, MACD)                 │
│  ✓ M1 microstructure flip (HH/LL)                            │
│                                                                 │
│  → Output: entry_triggered bool                              │
│           entry_price, stop_loss, take_profit, RR ratio      │
│                                                                 │
│  → If triggers not all confirmed: REJECT_SIGNAL              │
│                                                                 │
│  ⚠️  If entry_triggered: ENTRY_SIGNAL ✓✓✓                   │
└─────────────────────────────────────────────────────────────────┘
    │ (All layers passed - entry signal generated)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ ORDER EXECUTION (Live or Simulation)                            │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Create order with entry/SL/TP                             │
│  ✓ Position sizing based on risk management                  │
│  ✓ Execute on MT5 or simulation                              │
│  ✓ Track trade ID in state persistence                       │
└─────────────────────────────────────────────────────────────────┘
    │ (Position opened)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 9: TRADE MANAGER                                          │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Check partial exit 1:1 (close 50%, move SL to BE)         │
│  🟡 FLAW #13: 1:1 level validation vs TP missing             │
│                                                                 │
│  ✓ Trail SL at 1:2 RR                                        │
│  ✓ Close remaining at 1:3 RR                                 │
│  ✓ Hit SL on adverse move                                    │
│                                                                 │
│  → Output: Exit signal with P&L, close reason                │
└─────────────────────────────────────────────────────────────────┘
    │ (Position closed)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 10: FEEDBACK LOOP                                         │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Log closed trade (setup type, outcome, session, grade)    │
│  🔴 FLAW #14: Win rate counts breakeven as LOSS              │
│              (metrics completely wrong)                       │
│                                                                 │
│  ✓ Calculate weekly performance by setup type                │
│  ✓ Auto-adjust weights if setup WR < 45%                    │
│                                                                 │
│  → Output: Performance report, weight adjustments            │
│  → Auto-adjust confidence weights for next week              │
│                                                                 │
│  ⚠️  Calibration broken due to Flaw #14                      │
└─────────────────────────────────────────────────────────────────┘
    │
    └─────────────────────────┐
                              │ (Feedback loop cycles)
                              └──→ LAYER 1 (adjusted weights)


═══════════════════════════════════════════════════════════════════════
FLAW IMPACT WATERFALL
═══════════════════════════════════════════════════════════════════════

Flaw #1 (Daily Loss) → Blocks profitable days
Flaw #2 (Bias) ────────→ Ignores daily invalidation → Wrong direction
                              ↓
Flaw #3,4 (Structure) ─→ Stale/loose structure validation
                              ↓
Flaw #5,6 (Pullback) ──→ Wrong entry zones → False pullbacks
                              ↓
Flaw #7 (Liquidity) ───→ Stale pool targets
                              ↓
Flaw #8,9,15 (Sweep) ──→ Random sweeps detected → Wrong direction
                              ↓
Flaw #10 (POI) ────────→ Mediocre order blocks scored high
                              ↓
Flaw #12 (Entry) ──────→ Entries at turning points (extreme RSI)
                              ↓
Flaw #13 (Trade Mgmt) ─→ Exits at 1:1 when TP reachable
                              ↓
Flaw #14 (Feedback) ───→ Metrics broken → Bad auto-adjustment
                              ↓
Result: LOW WIN RATE + POOR CALIBRATION + PROFILE DECAY


═══════════════════════════════════════════════════════════════════════
RECOMMENDED FIX SEQUENCE
═══════════════════════════════════════════════════════════════════════

STOP: Do NOT trade live with current code

STEP 1 (1-2 hours): Critical Production Fixes
  └─ Flaw #1: Daily loss gate
  └─ Flaw #2: Bias invalidation
  └─ Flaw #15: Sweep direction validation

STEP 2 (3-5 hours): Core Logic Fixes
  └─ Flaw #5: Pullback Fib calculation
  └─ Flaw #8: CHoCH detection
  └─ Flaw #14: Win rate metric

STEP 3 (6-8 hours): Layer Robustness
  └─ Flaw #4,6: Structure/Pullback validation
  └─ Flaw #12: Entry RSI rejection
  └─ Flaw #13: Partial exit validation

STEP 4 (9+ hours): Polish & Edge Cases
  └─ Flaw #3: Swing detection
  └─ Flaw #7: Liquidity recency
  └─ Flaw #9: BOS swing points
  └─ Flaw #10: Order block criteria
  └─ Flaw #16: Data validation gates

THEN: Test thoroughly, backtest, then resume live trading

```

---

## Flaw Dependency Graph

```
              ENTRY SIGNAL
                   ▲
                   │
        ┌──────────┼──────────┐
        │          │          │
    [L7 CONF]  [L8 ENTRY]  [L6 POI]
        ▲          ▲          ▲
        │          │          │
        └──────────┼──────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
    [L5 SWEEP] [L4 LIQ]   [L3 PULL]
        ▲          ▲          ▲
  (FLAW #8,9,15)  │      (FLAW #5,6)
        │          │          │
        └──────────┼──────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
    [L2 STRUCT] [L1 BIAS]  [L0 GATES]
        ▲          ▲          ▲
    (FLAW #3,4) (FLAW #2)  (FLAW #1)


MEANING:
- Flaw #1 (Gates) blocks ALL trading
- Flaw #2 (Bias) affects direction of ALL layers
- Flaws #3,4 (Structure) affects L5 and L7 decisions
- Flaws #5,6 (Pullback) affects L4,L6,L7 decisions
- Flaws #8,9,15 (Sweep) blocks L5 and L6 from validating properly
- Others have localized impact


PRIORITY: Fix in dependency order (bottom-up):
  1. Gates (L0) - Tier 1
  2. Bias (L1) - Tier 1
  3. Sweep (L5) - Tier 1
  4. Pullback (L3) - Tier 2
  5. Others - Tier 3
```

