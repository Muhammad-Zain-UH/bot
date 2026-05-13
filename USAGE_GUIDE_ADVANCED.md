# Trading System Usage Guide - Advanced Features

## Quick Reference: Using the 10 New Components

### 1. Phase Confidence (Graduated 0-100%)

```python
# In technical_engine.py, this is now automatic:
wyckoff_phase, wyckoff_phase_strength, reason, components = WyckoffPhaseDetector.identify_phase(...)

# Outputs:
# - wyckoff_phase_strength = 0-100 (was 0-1 before)
# - components = {'rsi': X, 'volume': X, 'price_action': X, 'time': X, 'supply_demand': X}

# Confidence thresholds:
if wyckoff_phase_strength >= 85:
    confidence_level = "HIGH"  # High conviction phase
elif wyckoff_phase_strength >= 45:
    confidence_level = "BUILDING"  # Medium conviction
else:
    confidence_level = "FALSE"  # Weak signal
```

### 2. Market Structure Database

```python
from market_structure import get_market_structure_database

# Automatically updated every cycle:
market_db = get_market_structure_database()

# Get structural levels:
support_summary = market_db.get_support_summary()
# Returns: [{'price': X, 'touches': N, 'strength': X%, 'break_prob': X%}, ...]

resistance_summary = market_db.get_resistance_summary()

# Find nearest structure:
nearest_support, support_strength = market_db.get_nearest_structure(current_price, "DOWN")
nearest_resistance, resistance_strength = market_db.get_nearest_structure(current_price, "UP")

# Trading logic:
if nearest_support > 0 and support_strength >= 80:
    # Strong support detected - consider BUY
    pass
```

### 3. Effort vs Result Analyzer

```python
from effort_analyzer import get_effort_analyzer

analyzer = get_effort_analyzer()
avg_ratio, summary, reversal_prob = analyzer.analyze_candle_history(ohlc_history, "BUY")

# Interpret:
if reversal_prob >= 70:
    # CRITICAL exhaustion - reversal highly likely in 48-72h
    apply_penalty = -8.0
elif reversal_prob >= 50:
    # Moderate exhaustion
    apply_penalty = -4.0
elif avg_ratio > 1.5:
    # Strong effort-result alignment
    apply_bonus = +2.0
```

### 4. Spring/Shakeout Projection

```python
from projection_engine import calculate_wyckoff_targets

# Automatic for SPRING/SHAKEOUT phases:
targets = calculate_wyckoff_targets(
    phase="SPRING",
    direction="BUY",
    phase_low=2440.50,
    phase_high=2460.00,
    current_price=2435.20,
    volume_ratio=1.25,
    structural_strength=85.0
)

# Outputs:
# targets['projection']['primary_target'] = calculated geometric target
# targets['projection']['stop_loss'] = risk level
# targets['projection']['risk_reward_ratio'] = 1:3 (example)
# targets['geometric_levels'] = all targets + support/resistance
```

### 5. Volume Profile POC Analysis

```python
from volume_profile import analyze_volume_profile_at_price

analysis = analyze_volume_profile_at_price(ohlc_history, current_price)

# Interpret alignment:
if analysis['price_analysis']['alignment'] == 'AT_POC':
    # Strong support/resistance zone
    confidence_bonus = +2.0
elif analysis['price_analysis']['alignment'] == 'FAR_BELOW_POC':
    # Price will be pulled back to POC
    expect_reversal = True
    pullback_target = analysis['profile_summary']['poc_price']
```

### 6. Session Rotation Strategy

```python
from advanced_trading import SessionPhaseStrategy, get_session_adjusted_analysis

# Automatic in technical_engine.py:
session = SessionPhaseStrategy.get_current_session()  # 'ASIAN', 'LONDON', 'NEWYORK', 'OVERLAP'

# Get session-specific confidence:
analysis = get_session_adjusted_analysis(wyckoff_phase, phase_confidence, phase_bonus)

# Thresholds by session:
# ASIAN: 50.0% (most permissive)
# LONDON: 48.0% (active)
# NEWYORK: 47.0% (most active)
# Use for position sizing or entry confirmation
```

### 7. Composite Man Prediction

```python
from advanced_trading import CompositeManSimulator

prediction = CompositeManSimulator.predict_next_move(
    phase=wyckoff_phase,
    phase_confidence=phase_strength,
    price_low=low,
    price_high=high,
    volume_profile={}
)

# Interpret:
# prediction['next_phase'] = what phase comes after current
# prediction['probability'] = confidence in prediction
# prediction['rationale'] = human-readable explanation

# Example: SPRING detected → next_phase=MARKUP (probability 90%)
# Means: After spring shakeout, expect bullish markup
```

### 8. Bracket Prediction

```python
from advanced_trading import BracketPredictorEngine

brackets = BracketPredictorEngine.predict_stop_hunt_brackets(
    phase=wyckoff_phase,
    phase_low=low,
    phase_high=high,
    volume_profile={}
)

# Returns: [{'level': X, 'intensity': 'LIGHT'}, {'level': Y, 'intensity': 'HEAVY'}, ...]
# Strategy: Place profit targets 5-10pts BEFORE bracket levels
# Avoid placing stops within predicted bracket zones
```

### 9. Market Stress Volatility Index (SVI)

```python
from advanced_trading import AdvancedVolatilityIndex

svi = AdvancedVolatilityIndex.calculate_svi(atr_ratio, recent_range, expected_range)
stress = AdvancedVolatilityIndex.classify_market_stress(svi)

# Stress levels:
# CALM (<0.8): Reduce risk, take profits early
# NORMAL (0.8-1.2): Standard position sizing
# ELEVATED (1.2-1.5): Tighten stops, watch for breakouts
# STRESS (>1.5): Reduce position sizes 20-30%, higher risk management

if stress == 'STRESS':
    reduce_position_size_by = 0.25  # Use 75% of normal size
```

### 10. Multi-Touch Support Confirmation

```python
from advanced_trading import MultiTouchSupportConfirm

strength_level, strength_pct = MultiTouchSupportConfirm.calculate_support_strength(
    level_price=2440.0,
    touch_count=5,
    rejection_count=4,
    break_count=1
)

# Strength levels:
# VERY_STRONG (90%): 5+ touches, 80%+ rejections - ENTER IMMEDIATELY
# STRONG (75%): 5+ touches, 50%+ rejections - ENTER
# MODERATE (55%): 3-4 touches - ENTER with confirmation
# WEAK (35%): 2 touches - WAIT for more confirmation
# VERY_WEAK (20%): 1 touch - HIGH RISK

if strength_level in ['VERY_STRONG', 'STRONG']:
    take_trade = True
elif strength_level == 'MODERATE' and price_near_level:
    take_trade = True
    use_reduced_position = True
else:
    take_trade = False
    reason = f"Insufficient structure: {strength_level}"
```

---

## Real-World Trading Example

```python
# Scenario: Current price 2445.00, H4 HOLD, H1 Weak Bullish

# 1. PHASE DETECTION
phase = "SPRING"  # Spring detected (M5 RSI 28)
confidence = 78.0  # 78% graduated confidence
components = {
    'rsi': 85,           # Perfect RSI alignment
    'volume': 65,        # Moderate volume
    'price_action': 68,  # Good price action
    'time': 30,          # Brief consolidation
    'supply_demand': 75  # Good momentum
}

# 2. MARKET STRUCTURE
market_db check:
- Nearest support: 2440.00 (87% strength, 5 touches)
- Nearest resistance: 2450.00 (72% strength, 3 touches)

# 3. EFFORT VS RESULT
- Effort ratio: 0.38 (exhaustion!)
- Reversal probability: 68%
- Alert: "Exhaustion signal but SPRING phase contradicts"
- Judgment: Spring is higher confidence than exhaustion

# 4. PROJECTION ENGINE
- Accumulation range: 50pts (2440-2490)
- Volume ratio: 1.2
- Structural touches: 5
- Multiplier: 1.8
- Target: 2440 + (50 × 1.8) = 2530 (90pts reward)
- Risk-Reward: 1:3.6 (excellent)

# 5. POC ANALYSIS
- POC: 2435.00
- Current: 2445.00
- Distance: +10pts above POC
- Alignment: "ABOVE_POC"
- Magnet strength: 60%
- Interpretation: Price will naturally hold above POC

# 6. SESSION CHECK
- Current: LONDON (spring/shakeout focus)
- Bonus: +25% (SPRING is focus phase)
- Adjusted confidence: 78 + 1.5 = 79.5%

# 7. COMPOSITE MAN
- Current phase: SPRING
- Prediction: MARKUP next
- Probability: 92%
- Rationale: "Spring trapped shorts - composite will push higher"

# 8. STOP HUNT BRACKETS
- Predicted light bracket: 2448
- Predicted moderate bracket: 2453
- Predicted heavy bracket: 2458
- Strategy: Take profit at 2452 (before bracket), not 2458

# 9. MARKET STRESS
- SVI: 1.1 (NORMAL)
- No stress adjustments needed

# 10. STRUCTURE CONFIRMATION
- Support strength: VERY_STRONG (92%)
- Recommendation: "Trade immediately at support"

# ═══════════════════════════════════════════════════════════
# FINAL DECISION: BUY ✅
# ═══════════════════════════════════════════════════════════
# Entry: 2445.00
# Stop Loss: 2439.00 (6pt risk = 0.024%)
# Primary Target: 2530.00 (85pt reward)
# Risk-Reward: 1:14.2 (EXCEPTIONAL)
# Confidence: 79.5% (HIGH)
# Rationale: "SPRING 79.5% + STRONG structure + exhaustion fades + 
#            MARKUP next + excellent R:R + LONDON session favorable"
```

---

## Key Trading Principles with New System

### Priority Hierarchy (use in order):

1. **Phase Confidence** (Is phase real? 85%+)
2. **Market Structure** (Is level strong? 5+ touches)
3. **Effort vs Result** (Is momentum present? <0.5 = caution)
4. **Projection** (Is risk-reward good? <1:2 = skip)
5. **POC Alignment** (Is price helping? NOT FAR_POC)
6. **Session** (Is session favorable? ±25%)
7. **Composite Prediction** (Is smart money supportive? >85%)
8. **Stop Bracket** (Am I avoiding traps? Yes)
9. **Volatility** (Is stress low? <1.5 SVI)
10. **Structure Confirmation** (Multiple touches? Yes)

### Confidence Calculation

Final confidence = Base (22%) + Components (70%) + Bonuses/Penalties

- Base: 22%
- Technical components: up to +70%
  - Score alignment: up to +14%
  - Trend strength: up to +16%
  - RSI alignment: up to +12%
  - Volume confirmation: up to +12%
  - Volatility adjustment: up to +6%
  - M1 volatility: up to +3%
  - Multi-touch penalty: -15% to 0%
  - Higher TF conflict: -8%
  - Pullback entry: +8%

- Phase bonus: +8 to +15%
  - SPRING/SHAKEOUT: +15%
  - ACCUMULATION/DISTRIBUTION: +12%
  - MARKUP/MARKDOWN: +8%
  - Session adjusted: ±25%

- Market structure: 0 to +3%
- Exhaustion penalty: 0 to -8%
- Composite bonus: 0 to +2%

**Target confidence threshold by session:**
- ASIAN: 50% (low liquidity tolerance)
- LONDON: 48% (active)
- NY: 47% (very active)

---

## Automatic vs Manual Overrides

### Automatic (All 10 components integrated into technical_engine.py):
- Phase confidence calculation ✅
- Structure level identification ✅
- Exhaustion detection ✅
- Projection calculation ✅
- POC analysis ✅
- Session adjustment ✅
- Composite prediction ✅
- Bracket prediction ✅
- Volatility index ✅
- Structure confirmation ✅

### Manual Options (for live trading adjustments):
You can manually set these in gates before final signal generation:
```python
gates['force_phase'] = "SPRING"  # Override phase detection
gates['force_confidence'] = 95.0  # Override confidence calc
gates['disable_exhaustion_check'] = True  # Skip 48-72h check
gates['manual_target'] = 2530.0  # Override projection
gates['force_session'] = 'LONDON'  # Change session logic
```

---

## Monitoring & Performance

Track these metrics to verify system is working:

**Daily Monitoring:**
- [ ] Phase detection accuracy (SPRING/SHAKEOUT most predictive)
- [ ] Structure level holds (support should reject price 70%+)
- [ ] Exhaustion alerts (measure 48-72h reversal rate)
- [ ] Projection accuracy (actual target vs calculated)
- [ ] POC magnet (price returns to POC 65%+ of time)
- [ ] Session phase matching (LONDON springs, NY markups)
- [ ] Composite predictions (next phase occurs 85%+)
- [ ] Stop bracket avoidance (stops outside predicted zones)

**Weekly Review:**
- System score maintained 9.0+
- Win rate 55%+
- Risk-reward average 1:2+
- Confidence calibration (high-confidence trades win 65%+)

---

## Quick Start Checklist

After implementation:

- ✅ All 10 modules imported in technical_engine.py
- ✅ Phase confidence now 0-100 (check logs for "WYCKOFF Phase: X (Y%)")
- ✅ Market structure database auto-created on first run
- ✅ Exhaustion alerts appearing in logs
- ✅ Projection targets included in signal generation
- ✅ Session routing active (check for "[SESSION]" logs)
- ✅ Advanced analysis integrated (all features auto-active)

Run your bot and verify all logs show the new components!
