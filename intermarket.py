"""Intermarket Correlation Engine — analyzes macro forces affecting gold.

Gold is a reaction instrument. It moves because of:
  • US Dollar strength/weakness (inverse relationship)
  • Treasury yields (inverse relationship)
  • Silver price action (silver leads gold)
  • Risk sentiment in equity markets (safe haven when risk-off)

This module fetches data for four key instruments (DXY, Silver, US10Y, SP500)
and scores how well macro conditions align with a given gold signal direction.
"""

from __future__ import annotations

from typing import Any

import MetaTrader5 as mt5

import config
from indicators import calculate_indicators
from mt5_handler import get_market_data
from utils import log_debug


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-LEVEL DXY AVAILABILITY FLAG
# ─────────────────────────────────────────────────────────────────────────────
# Tested once at system startup. If DXY is unavailable, permanently use EURUSD
# as fallback for the entire session to avoid repeated failed attempts.
_DXY_TESTED = False
_DXY_AVAILABLE = None  # None = not tested, True = available, False = not available


# ---------------------------------------------------------------------------
# Trend classification helpers
# ---------------------------------------------------------------------------

def test_dxy_availability_at_startup() -> None:
    """Test if DXY is available on this broker at system startup.
    
    Called once at true system initialization before first monitoring cycle.
    Sets _DXY_AVAILABLE flag for the entire session.
    """
    global _DXY_TESTED, _DXY_AVAILABLE
    
    if _DXY_TESTED:
        return
    
    try:
        log_debug("[INIT] Testing DXY availability at startup...")
        data = get_market_data(config.INTERMARKET_DXY_SYMBOL, mt5.TIMEFRAME_M15, 10)
        if not data.empty:
            _DXY_AVAILABLE = True
            log_debug("[INIT] ✓ DXY is available on broker")
            _DXY_TESTED = True
            return
    except Exception as exc:
        log_debug(f"[INIT] DXY fetch failed: {exc}")
    
    # DXY is not available — switch to EURUSD permanent fallback
    _DXY_AVAILABLE = False
    log_debug(
        "[INIT] DXY not available on broker — using EURUSD as dollar proxy (permanent for session)"
    )
    
    _DXY_TESTED = True


def _test_dxy_availability() -> bool:
    """Test if DXY is available (uses cached result from startup test).
    
    Returns True if available, False otherwise.
    Should always use the startup test result; this is for backward compatibility.
    """
    global _DXY_TESTED, _DXY_AVAILABLE
    
    if _DXY_TESTED:
        return _DXY_AVAILABLE
    
    # Fallback: perform test now if not done at startup (shouldn't happen normally)
    test_dxy_availability_at_startup()
    return _DXY_AVAILABLE


def _classify_trend_simple(trend_str: str) -> str:
    """Extract classification from trend string (e.g., 'Strong Bullish' -> 'Strong Bullish')."""
    if not trend_str:
        return "Neutral"
    return str(trend_str).strip()


def _is_bullish(trend_str: str) -> bool:
    """Check if trend is bullish or bearish."""
    trend = _classify_trend_simple(trend_str)
    return "Bullish" in trend


def _is_bearish(trend_str: str) -> bool:
    """Check if trend is bearish."""
    trend = _classify_trend_simple(trend_str)
    return "Bearish" in trend


def _is_strong(trend_str: str) -> bool:
    """Check if trend is strong."""
    trend = _classify_trend_simple(trend_str)
    return "Strong" in trend


def _format_optional_number(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


# ---------------------------------------------------------------------------
# Instrument data fetching
# ---------------------------------------------------------------------------

def _fetch_instrument_data(
    symbol: str,
    timeframe: int = mt5.TIMEFRAME_M15,
    n_candles: int = 100,
    fallback_symbols: list[str] | None = None,
    is_inverse_dxy: bool = False,
) -> dict[str, Any] | None:
    """Fetch and calculate indicators for a single instrument with fallback support.
    
    Args:
        symbol: Primary symbol to fetch
        timeframe: Timeframe to use
        n_candles: Number of candles
        fallback_symbols: List of fallback symbols to try if primary fails
        is_inverse_dxy: If True, this is EURUSD/proxy for DXY (used for score logic only)
    
    Returns None if symbol is unavailable, otherwise returns dict with:
      - trend_classification: str (the ACTUAL trend as calculated)
      - rsi_14: float or None
      - price: float or None
      - used_symbol: str (actual symbol that was fetched)
      - is_inverse_dxy: bool (for scoring logic)
    """
    if fallback_symbols is None:
        fallback_symbols = []
    
    symbols_to_try = [symbol] + fallback_symbols
    
    for try_symbol in symbols_to_try:
        try:
            log_debug(f"Fetching intermarket data for {try_symbol}...")
            data = get_market_data(try_symbol, timeframe, n_candles)
            
            if data.empty:
                log_debug(f"  {try_symbol} returned no data, trying next fallback...")
                continue
            
            indicators = calculate_indicators(data)
            trend = indicators.get("trend_classification", "Neutral")
            
            # DO NOT invert the trend label — it should show the ACTUAL trend
            # The inversion logic applies only to score calculation, not label display
            
            rsi = indicators.get("rsi_14")
            
            log_debug(
                f"  {try_symbol}: trend={trend} | RSI={_format_optional_number(rsi, 2)}"
            )
            
            return {
                "trend_classification": trend,
                "rsi_14": rsi,
                "price": data.iloc[-1]["close"] if "close" in data else None,
                "used_symbol": try_symbol,
                "is_inverse_dxy": is_inverse_dxy,
            }
        except Exception as exc:
            log_debug(f"  Intermarket data fetch failed for {try_symbol}: {exc}")
            continue
    
    log_debug(f"All symbols failed for {symbol} and fallbacks {fallback_symbols}")
    return None


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _score_intermarket_alignment(
    gold_signal: str,
    dxy_data: dict[str, Any] | None,
    silver_data: dict[str, Any] | None,
    us10y_data: dict[str, Any] | None,
    oil_data: dict[str, Any] | None,
    sp500_data: dict[str, Any] | None,
) -> tuple[int, str]:
    """Score how well macro conditions align with the gold signal.
    
    Uses exact rules table per the specification:
    - EURUSD/XAGUSD: Direct correlation with gold
    - US10Y: Treasury yields — rising yields pressure gold lower
    - Oil: Risk sentiment indicator — oil spike = risk-off = gold bid
    - US500: Complex relationship (mostly NEUTRAL except extremes)
    
    FIX 5: Added US10Y (Treasury yields) and Oil (energy/risk indicator)
    
    Returns: (score, alignment_label)
    
    Score range: -8 to +9
    Positive = confirms the signal
    Negative = opposes the signal
    """
    score = 0
    
    if gold_signal not in {"BUY", "SELL"}:
        return 0, "NEUTRAL — no signal to evaluate"
    
    # --------------- EURUSD (DXY Proxy) ---------------
    # Remember: EURUSD is inverse of DXY
    # EURUSD UP = Dollar WEAK = Gold UP = SUPPORTS BUY, OPPOSES SELL
    # EURUSD DOWN = Dollar STRONG = Gold DOWN = SUPPORTS SELL, OPPOSES BUY
    if dxy_data:
        trend = dxy_data.get("trend_classification", "Neutral")
        is_inverse = dxy_data.get("is_inverse_dxy", True)  # EURUSD is inverse proxy
        
        # For scoring: need to know if DOLLAR is strong or weak
        # If we have EURUSD directly (inverted), "Bullish EURUSD" = "Weak Dollar"
        # If we somehow had real DXY (non-inverted), "Bullish DXY" = "Strong Dollar"
        
        if is_inverse:
            # trend shows actual EURUSD direction
            # For SELL (gold down), want Dollar STRONG = EURUSD DOWN = Bearish EURUSD
            # For BUY (gold up), want Dollar WEAK = EURUSD UP = Bullish EURUSD
            if gold_signal == "SELL":
                if "Strong Bearish" in trend:
                    score += 2
                    log_debug(f"  EURUSD Strong Bearish (+2): strong dollar supports SELL")
                elif "Weak Bearish" in trend:
                    score += 1
                    log_debug(f"  EURUSD Weak Bearish (+1): weak dollar supports SELL")
                elif "Neutral" in trend:
                    score += 0
                    log_debug(f"  EURUSD Neutral (0): no dollar impact")
                elif "Weak Bullish" in trend:
                    score -= 1
                    log_debug(f"  EURUSD Weak Bullish (-1): weak dollar opposes SELL")
                elif "Strong Bullish" in trend:
                    score -= 2
                    log_debug(f"  EURUSD Strong Bullish (-2): strong dollar headwind opposes SELL")
            else:  # BUY
                if "Strong Bullish" in trend:
                    score += 2
                    log_debug(f"  EURUSD Strong Bullish (+2): weak dollar supports BUY")
                elif "Weak Bullish" in trend:
                    score += 1
                    log_debug(f"  EURUSD Weak Bullish (+1): weak dollar supports BUY")
                elif "Neutral" in trend:
                    score += 0
                    log_debug(f"  EURUSD Neutral (0): no dollar impact")
                elif "Weak Bearish" in trend:
                    score -= 1
                    log_debug(f"  EURUSD Weak Bearish (-1): strong dollar opposes BUY")
                elif "Strong Bearish" in trend:
                    score -= 2
                    log_debug(f"  EURUSD Strong Bearish (-2): strong dollar opposes BUY")
    
    # --------------- XAGUSD (Silver — Direct correlation) ---------------
    if silver_data:
        trend = silver_data.get("trend_classification", "Neutral")
        
        if gold_signal == "SELL":
            if "Strong Bearish" in trend:
                score += 2
                log_debug(f"  XAGUSD Strong Bearish (+2): silver confirms SELL")
            elif "Weak Bearish" in trend:
                score += 1
                log_debug(f"  XAGUSD Weak Bearish (+1): silver confirms SELL")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  XAGUSD Neutral (0): silver neutral")
            elif "Weak Bullish" in trend:
                score -= 1
                log_debug(f"  XAGUSD Weak Bullish (-1): silver opposes SELL")
            elif "Strong Bullish" in trend:
                score -= 2
                log_debug(f"  XAGUSD Strong Bullish (-2): silver strongly opposes SELL")
        else:  # BUY
            if "Strong Bullish" in trend:
                score += 2
                log_debug(f"  XAGUSD Strong Bullish (+2): silver confirms BUY")
            elif "Weak Bullish" in trend:
                score += 1
                log_debug(f"  XAGUSD Weak Bullish (+1): silver confirms BUY")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  XAGUSD Neutral (0): silver neutral")
            elif "Weak Bearish" in trend:
                score -= 1
                log_debug(f"  XAGUSD Weak Bearish (-1): silver opposes BUY")
            elif "Strong Bearish" in trend:
                score -= 2
                log_debug(f"  XAGUSD Strong Bearish (-2): silver strongly opposes BUY")
    
    # --------------- US10Y (Treasury yields — FIX 5) ---------------
    # Rising yields = stronger dollar = gold pressure
    # Falling yields = weaker dollar + safe-haven demand = gold bid
    if us10y_data:
        trend = us10y_data.get("trend_classification", "Neutral")
        
        if gold_signal == "SELL":
            # For SELL (gold down), rising yields support this
            if "Strong Bullish" in trend:
                score += 2
                log_debug(f"  US10Y Strong Bullish (+2): rising yields pressure gold down")
            elif "Weak Bullish" in trend:
                score += 1
                log_debug(f"  US10Y Weak Bullish (+1): yields rising supports SELL")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  US10Y Neutral (0): no yield impact")
            elif "Weak Bearish" in trend:
                score -= 1
                log_debug(f"  US10Y Weak Bearish (-1): falling yields oppose SELL")
            elif "Strong Bearish" in trend:
                score -= 2
                log_debug(f"  US10Y Strong Bearish (-2): falling yields strongly oppose SELL")
        else:  # BUY
            # For BUY (gold up), falling yields support this
            if "Strong Bearish" in trend:
                score += 2
                log_debug(f"  US10Y Strong Bearish (+2): falling yields support BUY")
            elif "Weak Bearish" in trend:
                score += 1
                log_debug(f"  US10Y Weak Bearish (+1): yields falling supports BUY")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  US10Y Neutral (0): no yield impact")
            elif "Weak Bullish" in trend:
                score -= 1
                log_debug(f"  US10Y Weak Bullish (-1): rising yields oppose BUY")
            elif "Strong Bullish" in trend:
                score -= 2
                log_debug(f"  US10Y Strong Bullish (-2): rising yields strongly oppose BUY")
    
    # --------------- Oil (Energy/Risk sentiment — FIX 5) ---------------
    # Oil spike = geopolitical risk = risk-off = gold bid
    # Oil collapse = risk-on = gold sell
    if oil_data:
        trend = oil_data.get("trend_classification", "Neutral")
        
        if gold_signal == "SELL":
            # For SELL (gold down), lower oil supports this (risk-on)
            if "Strong Bearish" in trend:
                score += 1
                log_debug(f"  Oil Strong Bearish (+1): low oil signals risk-on opposes SELL")
            elif "Weak Bearish" in trend:
                score += 0
                log_debug(f"  Oil Weak Bearish (0): mild oil weakness neutral for SELL")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  Oil Neutral (0): no oil impact")
            elif "Weak Bullish" in trend:
                score -= 1
                log_debug(f"  Oil Weak Bullish (-1): oil rising supports SELL")
            elif "Strong Bullish" in trend:
                score -= 2
                log_debug(f"  Oil Strong Bullish (-2): oil spike signals risk-off opposes SELL")
        else:  # BUY
            # For BUY (gold up), higher oil supports this (risk-off/geopolitical)
            if "Strong Bullish" in trend:
                score += 2
                log_debug(f"  Oil Strong Bullish (+2): oil spike signals risk-off supports BUY")
            elif "Weak Bullish" in trend:
                score += 1
                log_debug(f"  Oil Weak Bullish (+1): oil rising supports BUY")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  Oil Neutral (0): no oil impact")
            elif "Weak Bearish" in trend:
                score -= 1
                log_debug(f"  Oil Weak Bearish (-1): low oil signals risk-on opposes BUY")
            elif "Strong Bearish" in trend:
                score -= 1
                log_debug(f"  Oil Strong Bearish (-1): oil collapse signals risk-on opposes BUY")
    
    # --------------- US500 (Equities — Complex relationship) ---------------
    # Complex: Risk-ON reduces safe-haven demand; Risk-OFF increases it but also panic-sells
    if sp500_data:
        trend = sp500_data.get("trend_classification", "Neutral")
        
        if gold_signal == "SELL":
            # For SELL: want lower equities (risk-off drives gold down longer term)
            # But only mild confirmation
            if "Strong Bullish" in trend:
                score += 0
                log_debug(f"  US500 Strong Bullish (0): risk-on is NEUTRAL for SELL")
            elif "Weak Bullish" in trend:
                score += 0
                log_debug(f"  US500 Weak Bullish (0): risk-on is NEUTRAL for SELL")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  US500 Neutral (0): no equity impact")
            elif "Weak Bearish" in trend:
                score += 1
                log_debug(f"  US500 Weak Bearish (+1): mild risk-off supports SELL")
            elif "Strong Bearish" in trend:
                score -= 1
                log_debug(f"  US500 Strong Bearish (-1): panic money INTO gold opposes SELL")
        else:  # BUY
            # For BUY: want lower equities (risk-off = safe-haven gold demand)
            if "Strong Bearish" in trend:
                score += 1
                log_debug(f"  US500 Strong Bearish (+1): strong risk-off supports BUY")
            elif "Weak Bearish" in trend:
                score += 0.5  # Note: we'll round this
                log_debug(f"  US500 Weak Bearish (+0.5): mild risk-off supports BUY")
            elif "Neutral" in trend:
                score += 0
                log_debug(f"  US500 Neutral (0): no equity impact")
            elif "Weak Bullish" in trend:
                score += 0
                log_debug(f"  US500 Weak Bullish (0): risk-on is NEUTRAL for BUY")
            elif "Strong Bullish" in trend:
                score -= 1
                log_debug(f"  US500 Strong Bullish (-1): risk-on opposes BUY")
    
    # Cap the score
    score = max(-8, min(9, int(score)))
    
    # Generate alignment label using new labels
    if score >= 5:
        label = "STRONG CONFIRMATION — macro strongly supports"
    elif score in [3, 4]:
        label = "MODERATE CONFIRMATION — macro supports signal"
    elif score in [1, 2]:
        label = "WEAK CONFIRMATION — macro is neutral"
    elif score in [-1, 0]:
        label = "NEUTRAL — macro mixed"
    elif score in [-2, -3]:
        label = "MILD HEADWIND — macro slightly opposes"
    else:  # score <= -4
        label = "STRONG HEADWIND — macro directly contradicts"
    
    return score, label


# ---------------------------------------------------------------------------
# Interpretation builders
# ---------------------------------------------------------------------------

def _interpret_instrument(data: dict[str, Any] | None, symbol_name: str) -> str:
    """Build a one-sentence interpretation of an instrument's current state."""
    if data is None:
        return f"{symbol_name} data unavailable"
    
    trend = data.get("trend_classification", "Neutral")
    rsi = data.get("rsi_14")
    
    if rsi is None:
        rsi_text = ""
    else:
        rsi_text = f"(RSI {rsi:.0f})"
    
    if "Strong" in trend:
        momentum = "strong"
    elif "Weak" in trend:
        momentum = "weak"
    else:
        momentum = "mixed"
    
    if "Bullish" in trend:
        direction = "bullish"
    elif "Bearish" in trend:
        direction = "bearish"
    else:
        direction = "neutral"
    
    return f"{symbol_name} shows {momentum} {direction} momentum {rsi_text}".strip()


# ---------------------------------------------------------------------------
# Main public interface
# ---------------------------------------------------------------------------

def get_intermarket_analysis(gold_signal_direction: str) -> dict[str, Any]:
    """Analyze intermarket alignment for a gold trading signal.
    
    Args:
        gold_signal_direction: "BUY", "SELL", or "NEUTRAL"
    
    Returns:
        dict with keys:
          intermarket_score        — int, alignment score (-5 to +7)
          alignment_label          — str, human-readable label
          dxy_trend                — str, trend classification or None
          dxy_rsi                  — float or None
          silver_trend             — str, trend classification or None
          silver_rsi               — float or None
          us10y_trend              — str or None
          sp500_trend              — str or None
          symbols_available        — list of str, which symbols were found
          symbols_missing          — list of str, which symbols were not found
          prompt_text              — str, formatted block for AI prompt injection
          error                    — str or None, any non-fatal error message
    """
    
    if not config.INTERMARKET_ENABLED:
        log_debug("Intermarket correlation disabled in config.")
        return _neutral_result("Intermarket analysis disabled.")
    
    if gold_signal_direction not in {"BUY", "SELL", "NEUTRAL"}:
        log_debug(
            f"Invalid gold_signal_direction '{gold_signal_direction}' - normalizing to NEUTRAL."
        )
        error_msg = f"Invalid signal direction '{gold_signal_direction}' normalized to NEUTRAL."
        gold_signal_direction = "NEUTRAL"
    else:
        error_msg = None
    
    symbols_available = []
    symbols_missing = []
    
    # ─────────────────────────────────────────────────────────────────────
    # TEST DXY AVAILABILITY ONCE AT STARTUP
    # ─────────────────────────────────────────────────────────────────────
    if not _DXY_TESTED:
        _test_dxy_availability()
    
    # Fetch DXY data with fallback strategy based on availability test
    # If DXY is not available, skip it entirely and go straight to EURUSD
    if _DXY_AVAILABLE:
        # DXY is available — try it as primary
        dxy_data = _fetch_instrument_data(
            config.INTERMARKET_DXY_SYMBOL,
            fallback_symbols=["EURUSD", "GBPUSD"],
            is_inverse_dxy=True,
        )
    else:
        # DXY is not available — skip directly to EURUSD fallback
        log_debug("[INTERMARKET] DXY disabled for session — using EURUSD as dollar proxy")
        dxy_data = _fetch_instrument_data(
            "EURUSD",
            fallback_symbols=["GBPUSD"],
            is_inverse_dxy=True,
        )
    
    if dxy_data:
        used_sym = dxy_data.get("used_symbol", config.INTERMARKET_DXY_SYMBOL)
        symbols_available.append(f"{config.INTERMARKET_DXY_SYMBOL}({used_sym})")
    else:
        symbols_missing.append(config.INTERMARKET_DXY_SYMBOL)
    
    # Fetch Silver data
    silver_data = _fetch_instrument_data(config.INTERMARKET_SILVER_SYMBOL)
    if silver_data:
        symbols_available.append(config.INTERMARKET_SILVER_SYMBOL)
    else:
        symbols_missing.append(config.INTERMARKET_SILVER_SYMBOL)
    
    # FIX 5: Fetch US10Y (Treasury yields)
    # Try US10Y as primary, fall back to yield proxies if unavailable
    us10y_data = _fetch_instrument_data(
        config.INTERMARKET_YIELD_SYMBOL,
        fallback_symbols=["USDX", "EURJPY"],  # Fallbacks if US10Y unavailable
    )
    if us10y_data:
        symbols_available.append(f"{config.INTERMARKET_YIELD_SYMBOL}({us10y_data.get('used_symbol', config.INTERMARKET_YIELD_SYMBOL)})")
    else:
        symbols_missing.append(f"{config.INTERMARKET_YIELD_SYMBOL} (yield proxy)")
    
    # FIX 5: Fetch Oil (WTIUSD or BRENT)
    # Oil is important: spike = risk-off = gold bid; fall = risk-on = gold sell
    oil_data = _fetch_instrument_data(
        config.INTERMARKET_OIL_SYMBOL,
        fallback_symbols=["UKOUSD", "CNHUSD"],  # Fallbacks: Brent oil or alternative
    )
    if oil_data:
        symbols_available.append(f"{config.INTERMARKET_OIL_SYMBOL}({oil_data.get('used_symbol', config.INTERMARKET_OIL_SYMBOL)})")
    else:
        symbols_missing.append(f"{config.INTERMARKET_OIL_SYMBOL} (energy)")
    
    # Fetch SP500 data
    sp500_data = _fetch_instrument_data(config.INTERMARKET_SP500_SYMBOL)
    if sp500_data:
        symbols_available.append(config.INTERMARKET_SP500_SYMBOL)
    else:
        symbols_missing.append(config.INTERMARKET_SP500_SYMBOL)
    
    # If no symbols were found, return neutral
    if not symbols_available:
        log_debug("No intermarket symbols were available on this broker.")
        return _neutral_result(
            "No intermarket instruments available. System will operate on technical signals only."
        )
    
    # Score the alignment
    score, label = _score_intermarket_alignment(
        gold_signal_direction,
        dxy_data,
        silver_data,
        us10y_data,
        oil_data,
        sp500_data,
    )
    
    # Extract individual values for the response
    dxy_trend = dxy_data.get("trend_classification") if dxy_data else None
    dxy_rsi = dxy_data.get("rsi_14") if dxy_data else None
    silver_trend = silver_data.get("trend_classification") if silver_data else None
    silver_rsi = silver_data.get("rsi_14") if silver_data else None
    us10y_trend = us10y_data.get("trend_classification") if us10y_data else None
    oil_trend = oil_data.get("trend_classification") if oil_data else None
    oil_rsi = oil_data.get("rsi_14") if oil_data else None
    sp500_trend = sp500_data.get("trend_classification") if sp500_data else None
    
    # Build interpretations
    dxy_interp = _interpret_instrument(dxy_data, "DXY")
    silver_interp = _interpret_instrument(silver_data, "Silver")
    us10y_interp = _interpret_instrument(us10y_data, "US10Y")
    oil_interp = _interpret_instrument(oil_data, "Oil")
    sp500_interp = _interpret_instrument(sp500_data, "SP500")
    
    # Build the macro interpretation — one sentence explaining what this means for gold
    macro_interp = _build_macro_interpretation(
        gold_signal_direction, score, dxy_data, silver_data, us10y_data, oil_data, sp500_data
    )
    
    # Build the prompt_text block exactly as specified (FIX 5: added US10Y and Oil)
    prompt_text = (
        f"INTERMARKET CORRELATION:\n"
        f"  DXY:    {dxy_trend or 'N/A'} | RSI {_format_optional_number(dxy_rsi, 0)} | {dxy_interp}\n"
        f"  Silver: {silver_trend or 'N/A'} | RSI {_format_optional_number(silver_rsi, 0)} | {silver_interp}\n"
        f"  US10Y:  {us10y_trend or 'N/A'} | {us10y_interp}\n"
        f"  Oil:    {oil_trend or 'N/A'} | RSI {_format_optional_number(oil_rsi, 0)} | {oil_interp}\n"
        f"  SP500:  {sp500_trend or 'N/A'} | {sp500_interp}\n"
        f"\n"
        f"  Intermarket Score: {score:+d}/9 — {label}\n"
        f"\n"
        f"  Macro interpretation: {macro_interp}"
    )
    
    log_debug(
        f"Intermarket analysis complete: score={score:+d} | label={label} | "
        f"available={symbols_available} | missing={symbols_missing}"
    )
    
    return {
        "intermarket_score": score,
        "alignment_label": label,
        "dxy_trend": dxy_trend,
        "dxy_rsi": dxy_rsi,
        "silver_trend": silver_trend,
        "silver_rsi": silver_rsi,
        "us10y_trend": us10y_trend,
        "oil_trend": oil_trend,
        "oil_rsi": oil_rsi,
        "sp500_trend": sp500_trend,
        "symbols_available": symbols_available,
        "symbols_missing": symbols_missing,
        "prompt_text": prompt_text,
        "error": error_msg,
    }


def _neutral_result(error_msg: str) -> dict[str, Any]:
    """Return a neutral intermarket result with an error message."""
    return {
        "intermarket_score": 0,
        "alignment_label": "NEUTRAL — macro inconclusive",
        "dxy_trend": None,
        "dxy_rsi": None,
        "silver_trend": None,
        "silver_rsi": None,
        "us10y_trend": None,
        "oil_trend": None,
        "oil_rsi": None,
        "sp500_trend": None,
        "symbols_available": [],
        "symbols_missing": [
            config.INTERMARKET_DXY_SYMBOL,
            config.INTERMARKET_SILVER_SYMBOL,
            config.INTERMARKET_YIELD_SYMBOL,
            config.INTERMARKET_OIL_SYMBOL,
            config.INTERMARKET_SP500_SYMBOL,
        ],
        "prompt_text": (
            f"INTERMARKET CORRELATION:\n"
            f"  {error_msg}\n"
            f"\n"
            f"  Intermarket Score: 0/9 — NEUTRAL — macro inconclusive"
        ),
        "error": error_msg,
    }


def _build_macro_interpretation(
    signal: str,
    score: int,
    dxy_data: dict[str, Any] | None,
    silver_data: dict[str, Any] | None,
    us10y_data: dict[str, Any] | None,
    oil_data: dict[str, Any] | None,
    sp500_data: dict[str, Any] | None,
) -> str:
    """Build a one-sentence macro interpretation of what intermarket conditions mean for gold.
    
    FIX 5: Includes US10Y (yields) and Oil (energy/risk) in macro interpretation.
    """
    
    if score >= 5:
        # Strong confirmation
        conditions = []
        if dxy_data and _is_bearish(dxy_data.get("trend_classification", "")):
            conditions.append("dollar weakness")
        if silver_data and _is_bullish(silver_data.get("trend_classification", "")):
            conditions.append("silver leadership")
        if us10y_data and _is_bearish(us10y_data.get("trend_classification", "")):
            conditions.append("falling yields")
        if oil_data and _is_bullish(oil_data.get("trend_classification", "")):
            conditions.append("geopolitical risk")
        if sp500_data and _is_bearish(sp500_data.get("trend_classification", "")):
            conditions.append("risk-off demand")
        
        if conditions:
            cond_str = ", ".join(conditions)
            if signal == "BUY":
                return f"{cond_str.capitalize()} creates ideal conditions for gold continuation higher."
            else:
                return f"{cond_str.capitalize()} creates ideal conditions for gold continuation lower."
        else:
            return "All major intermarket drivers align strongly with this signal."
    
    elif score >= 1:
        # Weak to moderate confirmation
        return f"Macro backdrop provides supportive conditions for a {signal.lower()} signal in gold."
    
    elif score <= -3:
        # Significant or strong headwind
        conditions = []
        if dxy_data and _is_bullish(dxy_data.get("trend_classification", "")):
            conditions.append("strong dollar")
        if us10y_data and _is_bullish(us10y_data.get("trend_classification", "")):
            conditions.append("rising yields")
        if oil_data and _is_bearish(oil_data.get("trend_classification", "")):
            conditions.append("low energy prices")
        if sp500_data and _is_bullish(sp500_data.get("trend_classification", "")):
            conditions.append("risk-on sentiment")
        
        if conditions:
            cond_str = ", ".join(conditions)
            if signal == "BUY":
                return f"Macro headwinds ({cond_str}) fight against the {signal.lower()} thesis — use caution."
            else:
                return f"Macro headwinds ({cond_str}) support gold strength — {signal.lower()} may struggle."
        else:
            return f"Major macro factors directly oppose the {signal.lower()} signal — reconsider positioning."
    
    else:  # -2 to 0
        return "Macro conditions are mixed — rely more heavily on technical confirmation."
