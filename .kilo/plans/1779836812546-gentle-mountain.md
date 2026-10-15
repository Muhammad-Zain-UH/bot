# Final Intraday Bot - Structure Analysis

## Overview
This is a sophisticated algorithmic trading bot designed for intraday trading of XAUUSD (Gold) using MetaTrader 5. The bot employs a multi-timeframe analysis approach with multiple confirmation layers to identify high-probability trading setups while implementing rigorous risk management.

## Core Architecture

### Main Components
1. **main.py** - Primary orchestrator running the continuous trading loop
2. **strategy_engine.py** - Core decision-making engine generating trading signals
3. **indicators.py** - Technical indicator calculations
4. **mt5_handler.py** - MetaTrader 5 connectivity and market data handling
5. **risk_manager.py** - Risk management and position sizing logic
6. **news_handler.py** - News filtering and high-impact event detection
7. **config.py** - Centralized configuration management
8. **cvd_divergence.py** - Cumulative Volume Divergence detection for institutional flow
9. **key_levels.py** - Support/resistance calculations and pivot points
10. **institutional_patterns.py** - Smart money concept detection (liquidity sweeps, upthrusts)
11. **fibonacci_levels.py** - Fibonacci retracement and extension level calculations
12. **pullback_handler.py** - Pullback-specific trading logic
13. **utils.py** - Utility functions including logging

## Data Flow

### 1. Market Data Acquisition
- `main.py` fetches OHLCV data from MT5 for multiple timeframes:
  - Higher Timeframes: H4, H1, D1
  - Middle Timeframes: M15, M5
  - Lower Timeframe: M1
- Data retrieved via `mt5_handler.get_market_data()` with fallback mechanisms
- Each timeframe returns a pandas DataFrame with standard OHLCV columns

### 2. Indicator Calculation
- `indicators.calculate_indicators()` processes each timeframe's data:
  - Trend: EMA20, EMA50 crossovers with ATR/price normalization
  - Momentum: RSI(14) with signal classification
  - Volatility: ATR(14) and ATR ratio
  - Volume: Volume ratio (vs 96-period average), volume surge ratio
  - Price Action: Candle body, wick ratios, VWAP deviation
  - Structure: Swing high/low (calculated only for M15 timeframe)
- Special function `calculate_indicators_with_swings()` used for M15 to include swing data

### 3. Signal Generation Process
The `strategy_engine.get_technical_signal()` function implements this workflow:

#### A. Higher Timeframe Bias Establishment
- H1 timeframe is PRIMARY bias source (more weight than H4)
- H4 used only as conflict warning flag
- Bias direction determined from H1 trend classification
- H4/H1 conflict detected and logged but doesn't override H1

#### B. Lower Timeframe Structure Analysis
- Evaluates M15/M5/M1 alignment with higher timeframe bias
- Determines if market is in:
  - Continuation (all timeframes aligned)
  - Pullback (lower timeframes opposing bias)
  - Range/chop (mixed signals)

#### C. Dual Entry Path Evaluation
1. **Momentum Entry Path** (Fast):
   - Requires M5 RSI > 60 (BUY) or < 40 (SELL)
   - Needs aligned H1/M15/M5 directions
   - Requires M1 breakout with volume surge
   - No pullback wait required

2. **Pullback Entry Path** (Conservative):
   - Waits for M15/M5 to pullback (opposite to bias)
   - Waits for pullback completion (M15/M5 flip back to bias direction)
   - Requires M1 rejection wick confirmation
   - Uses Fibonacci levels as entry zones

#### D. Confirmation Gates System
Multiple validation layers that can BLOCK or ADJUST confidence:

**Hard Gates (Blocking):**
- Session rules (no trading in Closed/Dead hours)
- Trend strength minimum (score ≥ 5.0/10, H1 must be Strong)
- M15/M5 alignment requirement
- M1 candle quality (body size, volume, wick structure)
- Price not at extremes (avoiding overbought/oversold)
- Volume surge on entry candle
- Confluence with support/resistance levels
- M5 momentum confirmation
- Entry validation (existing positions, spread, news)

**Confidence Adjusters (Non-blocking):**
- Volume quality (healthy/thin/dead modifiers)
- VWAP alignment (±8% penalty for misalignment)
- M5 trend strength (±12% penalty for weak/opposing)
- Price extremes (±12% penalty for extended entries)
- RSI exhaustion/caution (±6-12% modifiers)
- Institutional patterns (±8-15% based on type)
- CVD divergence (±10% for confirmation, -6% for conflict)
- H4 conflict (±3-12% based on severity)

#### E. Signal Output
Returns dictionary containing:
- `technical_signal`: TRADE signal (BUY/SELL/WAIT_FOR_CONFIRMATION/NO_TRADE)
- `setup_direction`: Intended trade direction
- `execute_signal`: Final execution signal
- `trigger_state`: Entry readiness state
- `weighted_score`: Directional strength (-10 to +10)
- `technical_confidence`: Final confidence % (25-99)
- `trade_levels`: Calculated entry, stop loss, take profit
- `gates`: Detailed gate validation results
- `scorecard`: Component breakdown of directional score
- `risk_level`: Assessed risk (Low/Medium/High)
- `trap_filter_status`: Hard gate validation status

### 4. Risk Management
Handled by `risk_manager.py`:
- Position sizing based on account risk percentage
- Daily loss limit monitoring
- Consecutive loss detection with timed pauses
- Regime validation after loss pauses
- Lot size calculation respecting symbol constraints

### 5. Trade Execution
Managed in `main.py`:
- Position existence check (prevents overlapping trades)
- Cooldown management after trade exits (longer after SL)
- Trailing stop management (breakeven + ATR trailing)
- Market order execution via `_place_limit_order()`
- Trade logging to CSV with comprehensive metrics
- Signal logging for performance analysis

### 6. News Filtering
- `news_handler.high_impact_news_within_minutes()`
- Checks economic calendar for high-impact events
- Configurable blackout periods (default: 15 minutes)
- Uses multiple news sources (RSS primary, NewsAPI/FMP secondary)

## Key Features

### 1. Multi-Timeframe Congruence
- Higher timeframes (H4/H1) establish directional bias
- Middle timeframes (M15/M5) confirm structure and momentum
- Lower timeframe (M1) provides precision entry timing
- Requires alignment across timeframes for high-confidence setups

### 2. Institutional Flow Detection
- CVD divergence identifies smart money vs retail flows
- Institutional pattern detection (Wyckoff springs/upthrusts)
- Volume analysis reveals participation quality
- These features act as both directional confirmations and confidence adjusters

### 3. Adaptive Entry Logic
- Momentum path for strong, trending moves
- Pullback path for higher-probability retracement entries
- Dynamic switching based on market structure
- Entry method tracked and logged for performance analysis

### 4. Advanced Risk Controls
- Multi-layered confirmation reduces false signals
- Hard gates prevent trades in unfavorable conditions
- Trailing stops protect profits and manage risk
- Session-aware parameters adjust to market conditions
- News avoidance reduces fundamental risk exposure

### 5. Professional Logging & Analytics
- Comprehensive CSV logging of all signals and trades
- Detailed debug logging for troubleshooting
- Performance metrics tracking (win rate, profit factor, etc.)
- Configuration transparency through centralized config

## Configuration System

### Centralized in `config.py`:
- **API Keys**: ANTHROPIC_API_KEY (for news sentiment, replaces OpenAI)
- **MT5 Connection**: Login credentials, server, path
- **Trading Parameters**: Symbol (XAUUSD), lot sizes, candle counts
- **Intraday Optimizations**:
  - Session-specific multipliers (London/New York favored)
  - Higher confidence thresholds (62% intraday vs 45% swing)
  - Reduced hold times (max 240 minutes)
  - Strict risk per trade (0.5%)
  - Daily trade limits (4 max intraday)
- **Feature Toggles**:
  - Institutional pattern requirements
  - CVD divergence requirements
  - News filter sensitivity
- **Environment Variable Support**: `.env` file for secrets

## Implementation Details

### Main Loop Execution (`main.py`):
1. **Initialization**: Connect to MT5, load configuration
2. **Continuous Loop** (60-second intervals):
   - Session check (skip if Closed)
   - Risk limit checks (daily loss, consecutive losses)
   - News blackout check
   - Spread validation
   - Multi-timeframe data fetch
   - Indicator calculation for all timeframes
   - Signal generation via strategy engine
   - Gate validation and confidence adjustment
   - Trade execution if all conditions met
   - Existing position management (trailing stops)
   - Trade and signal logging
   - Sleep until next cycle

### Error Handling & Robustness:
- Multiple data fetch fallbacks in MT5 handler
- Graceful degradation when indicators unavailable
- Comprehensive exception handling with logging
- Validation checks at each processing stage
- Recovery mechanisms for connection issues

## Performance Characteristics

### Signal Generation Logic:
- High-bar entry requirements (typically 65%+ confidence)
- Multiple timeframe confirmation reduces overtrading
- Adaptive thresholds based on market conditions
- Professional risk-reward targeting (typically 1:2 minimum)
- Session-aware performance optimization

### Risk Management Features:
- Dynamic position sizing based on volatility
- Loss-based trading pauses with market validation
- Profit protection via trailing stops
- Maximum holding periods prevent stale positions
- News avoidance reduces gap risk

## Summary
This trading bot implements a professional-grade algorithmic trading system that combines:
- Institutional smart money concepts
- Multi-timeframe technical analysis
- Volume-price relationship analysis
- Rigorous risk management
- Adaptive entry logic
- Comprehensive performance tracking

The architecture prioritizes signal quality over quantity, using multiple confirmation layers to filter for high-probability setups while implementing professional risk controls to preserve capital.