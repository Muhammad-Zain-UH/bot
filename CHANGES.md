# Trading Bot Restructure — CHANGES.md

## Overview

The XAUUSD trading bot has been completely restructured from a single-run, one-time execution model into a **continuous monitoring loop** with three-stage gates that control expensive API calls. The bot now runs forever until stopped with Ctrl+C, checking conditions multiple times per minute and only firing expensive APIs (news, AI) when cheap gates pass.

## Key Changes

### 1. **Architecture: Single Run → Continuous Loop**

**BEFORE:**
- `main.py` runs once, outputs a signal, then exits
- Every run fetches ALL data (MT5, news, RSS, OpenAI)
- OpenAI API called on EVERY execution, causing rate limit 429 errors
- User must manually re-run `python main.py` to check again

**AFTER:**
- `main.py` now runs an infinite `while True` loop
- Bot fetches multi-timeframe data continuously
- Expensive API calls (news, AI) only fire AFTER cheap gates pass
- `Ctrl+C` to stop gracefully
- All existing indicator logic and CSV logging preserved

### 2. **Three-Stage Gate System**

The new architecture implements **three sequential gates** that control information flow:

#### **STAGE 1: CHEAP SCAN** (Always runs every iteration)
- Fetch multi-timeframe MT5 data (H4, H1, M15, M5, M1)
- Calculate all indicators: EMA, RSI, ATR, VWAP, volume
- Run technical signal engine (pure Python, no API calls)
- Calculate score and confidence

**GATE 1 CHECK:**
- If confidence < 45% → Print monitor status line and sleep
  - Sleep time is dynamic based on gap to threshold:
    - Gap > 20% → sleep 120 seconds
    - Gap 10-20% → sleep 60 seconds
    - Gap < 10% → sleep 30 seconds (very close)
- If confidence >= 45% → Proceed to STAGE 2

#### **STAGE 2: INTERMARKET CHECK** (Only if Stage 1 passes)
- Fetch EURUSD, XAGUSD, US500 correlation data
- Calculate intermarket score

**HARD BLOCKS** (Absolute vetoes — trigger immediate continue):
- **BLOCK A:** XAGUSD is "Strong Bearish" AND direction is BUY → sleep 120s
- **BLOCK B:** M1 RSI > 70 AND direction is BUY → sleep 60s
- **BLOCK C:** M1 RSI < 30 AND direction is SELL → sleep 60s
- **BLOCK D:** Intermarket score ≤ -3 → sleep 90s

**GATE 2 CHECK:**
- If any hard block triggered → sleep and continue loop
- If intermarket score < -2 (headwind) → Apply confidence penalty, proceed

#### **STAGE 3: EXPENSIVE APIs** (Only if Stages 1+2 pass)
- Fetch news sentiment (economic calendar + RSS headlines)
- Call Claude API for AI verification (parallel execution)

**GATE 3 CHECK:**
- If AI says do not trade OR news sentiment ≤ -3 → sleep 120s, continue
- If both pass → Proceed to execution

#### **EXECUTION** (Only if all 3 gates pass)
- Place trade in MT5 with entry, SL, TP
- Log full trade to CSV
- Sleep 300 seconds (post-trade cooldown)

### 3. **OpenAI → Anthropic Claude API**

**REMOVED:**
- All OpenAI API calls
- OpenAI imports and configuration

**ADDED:**
- Anthropic Claude API integration
- Model: `claude-sonnet-4-20250514`
- Reads `ANTHROPIC_API_KEY` from environment automatically
- Graceful fallback to technical-only signal if API unavailable

**Configuration:**
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

### 4. **File Structure**

**New files created:**
```
main.py                  ← Continuous loop orchestrator (completely replaced)
stage1.py               ← Technical scan + GATE 1
stage2.py               ← Intermarket analysis + hard blocks (GATE 2)
stage3.py               ← News + AI verification (GATE 3)
utils/
  display.py            ← Console output formatting
  sleep.py              ← Dynamic sleep calculation
```

**Modified files:**
```
config.py               ← Updated with ANTHROPIC_API_KEY (removed OPENAI_API_KEY)
requirements.txt        ← Added anthropic, removed openai
```

**Preserved files** (all existing logic intact):
```
technical_engine.py     ← All indicator calculations preserved
indicators.py           ← EMA, RSI, ATR, VWAP, volume
intermarket.py          ← Correlation analysis
mt5_handler.py          ← MT5 connection and data fetching
news_handler.py         ← Economic calendar
rss_feed.py             ← RSS headlines
risk_manager.py         ← Session filter, daily loss limit
signal_logger.py        ← CSV logging
key_levels.py           ← Pivot calculations
geopolitics.py          ← Keyword-based sentiment
sniper_confirmation.py  ← Sniper engine
confidence_calibrator.py← Technical confidence calibration
utils.py                ← Logging helpers
```

### 5. **Console Output**

**NEW monitoring output** (during WAIT states):
```
[MONITOR 23:14:05] BUY | Score: 5.95/12.5 | Conf: 33% (need 49%) | 
H4: Strong Bull | M1 RSI: 68.6 | Gap: -16% | Next check: 60s
```

**Gate status messages:**
```
[GATE 1] PASS: confidence 52% >= 45%
[GATE 2] PASS: no hard blocks, intermarket=Aligned
[HARD BLOCK] A: Silver (XAGUSD) is Strong Bearish — BUY blocked → sleep 120s
[GATE 3] BLOCK: AI rejected | News too bearish (-5) → sleep 120s
[EXECUTE] BUY | Confidence: 67% | Placing trade...
[COOLDOWN] Post-trade sleep 300s
```

### 6. **Dynamic Sleep Logic**

Sleep times are calculated based on **how close the setup is to passing**:

```python
def calculate_sleep_time(confidence, required_confidence, stage):
    gap = required_confidence - confidence
    gap_pct = (gap / required_confidence * 100)
    
    if stage == 1:  # GATE 1
        if gap_pct > 20: return 120   # Far from threshold
        elif gap_pct > 10: return 60  # Moderately close
        else: return 30               # Very close → frequent checks
    elif stage == 2: return 90        # Intermarket headwind
    elif stage == "hard_block": return 120
    elif stage == "post_trade": return 300
```

This means:
- **Setup far from threshold** → Longer sleeps (bot waits)
- **Setup very close to threshold** → Shorter sleeps (bot checks frequently)
- **Hard block triggered** → Always 120s
- **Post-trade** → Always 300s cooldown

### 7. **Error Handling**

Each stage has its own try/except:
- **Stage 1 MT5 error** → Log, sleep, continue (never crashes)
- **Stage 2 error** → Allow through with neutral intermarket (don't hard-block)
- **Stage 3 API error** → Allow through with reduced confidence (cap at 45%)

The bot never crashes on exceptions. All errors are logged and the loop continues.

### 8. **Logging**

**Console output:**
- Clean single-line monitor status during WAIT states
- Gate pass/fail messages
- Hard block messages
- Execution messages

**File logging** (`trading_bot.log`):
- Full debug logs of every stage
- All gate decisions
- API responses
- Error stack traces
- Rotating file handler: 5 files × 2MB each

### 9. **CSV Logging**

All existing CSV logging preserved:
- Logs every signal (BUY, SELL, WAIT, NO TRADE)
- Records technical score, confidence, AI decision, news sentiment
- Includes all gate information for post-analysis
- Supports manual outcome tracking (WIN/LOSS/SKIP/MISSED)

## Installation & Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

This will install:
- `anthropic>=0.28.0` (NEW)
- `MetaTrader5==5.0.45`
- `pandas>=1.5.0`
- `pandas-ta>=0.3.14`
- `requests>=2.28.0`
- `feedparser>=6.0.10`
- `numpy>=1.23.0`

(Removed: `openai>=1.3.0`)

### 2. Get Anthropic API Key

1. Go to https://console.anthropic.com/
2. Sign up or log in
3. Create an API key
4. Set environment variable:

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-xxxxx..."
python main.py
```

**Windows (Command Prompt):**
```cmd
set ANTHROPIC_API_KEY=sk-ant-xxxxx...
python main.py
```

**Or create a `.env` file in the bot directory:**
```
ANTHROPIC_API_KEY=sk-ant-xxxxx...
```

### 3. Run the bot
```bash
python main.py
```

The bot will start monitoring and print status lines every 30-120 seconds until:
- User presses `Ctrl+C`
- Market closes
- Daily loss limit is hit

## Backwards Compatibility

✅ **All existing functionality preserved:**
- Technical indicators unchanged
- CSV logging unchanged
- Risk management unchanged
- Session filtering unchanged
- Daily loss limit unchanged
- All pivot calculations unchanged
- All indicator calculations unchanged

❌ **Breaking changes:**
- OpenAI library removed (replaced with Anthropic)
- Old `ai_analyst.py` functions no longer used (but kept in codebase for reference)
- Old `get_final_decision()` replaced with Claude implementation in `stage3.py`

## Performance Improvements

| Metric | Before | After |
|--------|--------|-------|
| API calls per run | 3-4 (news, news, OpenAI) | 0-2 (only if gates pass) |
| Run frequency | Manual (user re-runs) | Continuous (auto-check) |
| Rate limit risk | Very high (every run) | Very low (smart gating) |
| Time to react | Minutes (manual re-run) | 30-120 seconds (automatic) |
| Bot operation | One-time | Continuous 24/5 |

## Troubleshooting

**Bot not starting:**
- Check MT5 is running and you're logged in
- Check config.py for correct MT5_LOGIN, MT5_SERVER
- Check ANTHROPIC_API_KEY is set

**Too many API calls (still rate limited):**
- Confidence threshold is too low (check GATE 1)
- Hard blocks not triggering (check stage2.py logic)
- Reduce loop frequency by increasing base sleep time

**Missing signals:**
- Check that confidence >= 45% (GATE 1 requirement)
- Check that M1 RSI is not in exhaustion zones (hard blocks B/C)
- Check intermarket score > -2 (GATE 2 headwind penalty)
- Check news sentiment > -3 (GATE 3)

## Next Steps

1. Test in live market during paper trading hours
2. Monitor `trading_bot.log` for any issues
3. Tune confidence thresholds for your trading style
4. Track outcomes in signal_log.csv and analyze results

---

**Questions?** Check `QUICK_REFERENCE.md` for existing documentation or review the inline code comments in `main.py`, `stage1.py`, `stage2.py`, `stage3.py`.
