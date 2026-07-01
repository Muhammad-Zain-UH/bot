# Quick Fix Reference - Code Changes

## Tier 1: Critical Fixes (Implement First)

### Fix #1: Daily Loss Gate - main_production.py (Line 198-201)

**BEFORE (WRONG):**
```python
max_daily_loss = (account_balance * CONFIG["max_daily_loss_percent"] / 100) if account_balance > 0 else 1000
if abs(current_daily_loss) > max_daily_loss:  # ❌ Uses abs()
    gates_failed.append(f"DAILY_LOSS: {current_daily_loss:.2f} > {max_daily_loss:.2f}")
else:
    gates_passed.append(f"Daily loss OK ({abs(current_daily_loss):.2f} / {max_daily_loss:.2f})")
```

**AFTER (CORRECT):**
```python
max_daily_loss = (account_balance * CONFIG["max_daily_loss_percent"] / 100) if account_balance > 0 else 1000
if current_daily_loss < -max_daily_loss:  # ✓ Only blocks on actual losses
    gates_failed.append(f"DAILY_LOSS: {abs(current_daily_loss):.2f} > {max_daily_loss:.2f}")
else:
    gates_passed.append(f"Daily loss OK ({abs(current_daily_loss):.2f} / {max_daily_loss:.2f})")
```

---

### Fix #2: Bias Invalidation - bias_engine.py (End of get_h4_bias function, ~line 245)

**BEFORE (WRONG):**
```python
def get_h4_bias(h4_indicators: dict[str, Any], daily_data: pd.DataFrame | None = None) -> dict[str, Any]:
    ema_bias = calculate_h4_ema_bias(h4_indicators, daily_data)
    
    return ema_bias  # ❌ Missing validation step
```

**AFTER (CORRECT):**
```python
def get_h4_bias(h4_indicators: dict[str, Any], daily_data: pd.DataFrame | None = None) -> dict[str, Any]:
    ema_bias = calculate_h4_ema_bias(h4_indicators, daily_data)
    
    # ✓ Add daily invalidation validation:
    validation = validate_bias_with_daily_close(
        current_bias=ema_bias["bias"],
        daily_data=daily_data,
        h4_swing_high=ema_bias.get("swing_high"),
        h4_swing_low=ema_bias.get("swing_low")
    )
    
    # Update bias if daily flipped it:
    if validation["invalidated"]:
        ema_bias["bias"] = validation["bias"]
        ema_bias["invalidated"] = True
        ema_bias["flip_reason"] = validation["flip_reason"]
    
    return ema_bias
```

---

### Fix #3: Sweep Direction Validation - main_production.py (After L5 sweep check, ~line 340)

**BEFORE (WRONG):**
```python
sweep = (
    get_sweep_and_structure(m15_data, h1_data, target_pool["level"], side)
    if callable(get_sweep_and_structure) and m15_data is not None and h1_data is not None
    else None
)
if not sweep or (not sweep.get("sweep_confirmed") and not sweep.get("choch_confirmed")):
    analysis["layer_failed"] = "L5_SWEEP"
    analysis["fail_reason"] = "No sweep or CHoCH detected"
    analysis["signal_type"] = "PRE_ENTRY"
    return analysis
analysis["layers_passed"].append("L5_SWEEP")
```

**AFTER (CORRECT):**
```python
sweep = (
    get_sweep_and_structure(m15_data, h1_data, target_pool["level"], side)
    if callable(get_sweep_and_structure) and m15_data is not None and h1_data is not None
    else None
)
if not sweep or (not sweep.get("sweep_confirmed") and not sweep.get("choch_confirmed")):
    analysis["layer_failed"] = "L5_SWEEP"
    analysis["fail_reason"] = "No sweep or CHoCH detected"
    analysis["signal_type"] = "PRE_ENTRY"
    return analysis

# ✓ NEW: Validate sweep direction matches entry direction:
if sweep.get("sweep_confirmed"):
    expected_sweep = "bullish_sweep" if side == "BUY" else "bearish_sweep"
    if sweep.get("sweep_type") != expected_sweep:
        analysis["layer_failed"] = "L5_SWEEP_DIRECTION"
        analysis["fail_reason"] = f"Sweep type {sweep['sweep_type']} doesn't match {side} direction"
        analysis["signal_type"] = "PRE_ENTRY"
        return analysis

analysis["layers_passed"].append("L5_SWEEP")
```

---

## Tier 2: Critical Logic Fixes

### Fix #4: Pullback Fib Calculation - pullback_detector.py (Lines 137-142)

**BEFORE (WRONG):**
```python
# Calculate Fib levels for pullback depth
if expected_bias == "BULLISH":
    fibs = calculate_fib_levels(swing_high, current_low)
else:
    fibs = calculate_fib_levels(swing_high, swing_low)  # ❌ Wrong: uses swing_low not current_high
```

**AFTER (CORRECT):**
```python
# Calculate Fib levels for pullback depth
if expected_bias == "BULLISH":
    # Pullback FROM high DOWN to current_low
    fibs = calculate_fib_levels(swing_high, current_low)  # ✓ Correct
else:  # BEARISH
    # Pullback FROM low UP to current_high
    fibs = calculate_fib_levels(swing_low, current_high)  # ✓ Fixed: swing_low, current_high
```

---

### Fix #5: CHoCH Logic - sweep_detector.py (Lines 330-360)

**BEFORE (WRONG):**
```python
if direction == "BUY":
    highs = recent["high"].values
    
    last_lh = None
    for i in range(len(highs) - 1, 0, -1):
        if highs[i] < highs[i-1]:  # ❌ ANY lower point, not swing high
            last_lh = highs[i]
            break
    
    if last_lh is None:
        last_lh = recent["high"].min()
    
    if current_close > last_lh:
        return {"choch_confirmed": True, ...}
```

**AFTER (CORRECT):**
```python
if direction == "BUY":
    # ✓ NEW: Find actual swing highs (peaks), then check if sequence is LH
    highs = recent["high"].values
    
    # Find swing highs: local maxima
    swing_highs = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            swing_highs.append((i, highs[i]))
    
    # Find true LH: if last swing high < second-to-last swing high
    last_lh = None
    if len(swing_highs) >= 2:
        if swing_highs[-1][1] < swing_highs[-2][1]:
            last_lh = swing_highs[-1][1]
    
    if last_lh is None and len(swing_highs) >= 1:
        last_lh = swing_highs[-1][1] * 0.98  # Use last swing - small buffer
    
    if last_lh and current_close > last_lh:
        return {"choch_confirmed": True, ...}
```

---

### Fix #6: Win Rate Metric - feedback_loop.py (Lines 95-110)

**BEFORE (WRONG):**
```python
for setup_type, records in by_setup.items():
    wins = sum(1 for r in records if r["outcome"] == "WIN")
    losses = sum(1 for r in records if r["outcome"] == "LOSS")
    total = len(records)
    
    win_rate = wins / total * 100 if total > 0 else 0  # ❌ Counts breakeven as loss
```

**AFTER (CORRECT):**
```python
for setup_type, records in by_setup.items():
    # ✓ NEW: Properly categorize outcomes:
    wins = sum(1 for r in records 
               if r["outcome"] == "WIN" or 
               r.get("close_reason") in ["1_1_EXIT", "1_2_EXIT", "1_3_EXIT", "PARTIAL_EXIT"])
    
    losses = sum(1 for r in records 
                 if r["outcome"] == "LOSS" or r.get("close_reason") == "SL_HIT")
    
    breakeven = sum(1 for r in records if r.get("close_reason") == "BREAKEVEN")
    
    # Win rate: only count decisive (win/loss), exclude breakeven:
    total_decisive = wins + losses
    win_rate = wins / total_decisive * 100 if total_decisive > 0 else 0  # ✓ Fixed
```

---

## Tier 3: Robustness Fixes (Example Implementations)

### Fix #7: Structure Validation - structure_engine.py (Lines 155-165)

**BEFORE:**
```python
if is_higher_high and is_higher_low:
    confidence = min(10.0, (current_low - last_low) / 5.0)
    return {
        "structure_valid": True,
        "structure_type": "HH/HL",
        ...
    }
```

**AFTER:**
```python
# ✓ Validate SERIES of HH/HL, not just current candle:
if is_higher_high and is_higher_low:
    # Check last 5 candles to ensure ongoing structure:
    last_5 = h1_data.tail(5)
    hh_count = sum(1 for h in last_5["high"] if h > last_high)
    hl_count = sum(1 for l in last_5["low"] if l > last_low)
    
    # Both HH and HL must appear in last 5 for valid ongoing structure:
    if hh_count >= 2 and hl_count >= 2:
        confidence = min(10.0, (current_low - last_low) / 5.0)
        return {
            "structure_valid": True,
            "structure_type": "HH/HL",
            ...
        }
```

---

### Fix #8: Momentum Extreme RSI Check - entry_engine.py (After line 170)

**BEFORE:**
```python
if direction == "BUY":
    if volume_ratio >= 1.2:
        quality += 3.0
    if rsi_direction in ["up", "neutral"]:
        quality += 2.0
        momentum_confirmed = True
```

**AFTER:**
```python
if direction == "BUY":
    # ✓ NEW: REJECT if RSI already overbought:
    curr_rsi = _to_float(recent.iloc[-1].get("rsi"))
    if curr_rsi and curr_rsi > 80:
        return {
            "momentum_confirmed": False,
            "momentum_quality": 0.0,
            "reason": f"RSI overbought ({curr_rsi:.0f} > 80)"
        }
    
    if volume_ratio >= 1.2:
        quality += 3.0
    if rsi_direction in ["up", "neutral"]:
        quality += 2.0
        momentum_confirmed = True
```

---

## Testing After Fixes

Test cases to verify each fix:

```python
# Test #1: Daily Loss Gate
# Input: current_daily_loss = +500 pips (profit)
# Expected: gates_passed (NOT gates_failed)

# Test #2: Bias Invalidation
# Input: BULLISH bias, daily close BELOW H4 swing low
# Expected: bias flips to BEARISH

# Test #3: Sweep Direction
# Input: BUY signal with bearish_sweep
# Expected: L5_SWEEP_DIRECTION fail (not passed)

# Test #4: Pullback Fib
# Input: BEARISH bias, pullback from low
# Expected: Fib range uses swing_low to current_high (not high to low)

# Test #5: CHoCH
# Input: M15 with random dip but no swing high sequence
# Expected: choch_confirmed = False

# Test #6: Win Rate
# Input: 8 wins, 2 losses, 3 breakeven trades
# Expected: win_rate = 80% (not 53%)
```

