"""AI Analyst — the hybrid decision brain of the trading system.

Architecture
────────────
Python rule engine  →  technical score + hard gates (fast, deterministic, free)
GPT-4.1-mini        →  news sentiment + macro context + FINAL decision

Why this split:
  • Math is better than AI at: EMA crossovers, RSI levels, ATR ratios, volume
    checks. These are deterministic — same input always gives same output.
  • AI is better than math at: reading "Fed signals patience amid tariff uncertainty"
    and knowing that is gold-bullish. Keyword lists cannot match this.
  • The AI sees EVERYTHING: technical score, all indicator values, all headlines,
    all calendar events. It makes the final call with full context.

Two-stage AI call:
  Stage 1 (fast, cheap — GPT-4o-mini):
      News sentiment score (-10 to +10) from headlines only.
      $0.00015 per 1K tokens. Run on every signal candidate.

  Stage 2 (full analysis — GPT-4o-mini):
      Complete picture: technicals + news sentiment + calendar + risk context.
      Outputs final_signal, confidence, reasoning.
      $0.00015 per 1K tokens. Run on BUY/SELL candidates only.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

import config
try:
    from geopolitics import analyze_geopolitics
except ImportError:
    def analyze_geopolitics(headlines: list[str]) -> dict[str, Any]:
        return {
            "Gold Bias": "Neutral",
            "Risk Sentiment": "Neutral",
            "War Risk": "Low",
            "Recession Risk": "Low",
            "Inflation Pressure": "Low",
            "Matched Headlines": headlines[:1],
            "has_data": bool(headlines),
        }
from utils import log_debug

_BASE_URL = "https://api.openai.com/v1/chat/completions"

# Stage 1: cheap/fast model for news sentiment only
_SENTIMENT_MODEL = "gpt-4o-mini"   # cheapest available; fall back to mini
_DECISION_MODEL  = "gpt-4o-mini"   # full decision model

_REQUEST_TIMEOUT = 20
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECS = 2  # Start with 2 sec, double each retry


# ---------------------------------------------------------------------------
# Internal API caller with retry logic and robust JSON parsing
# ---------------------------------------------------------------------------

def _extract_json_from_response(text: str) -> str:
    """Extract JSON from response text, handling markdown fences, arrays, and extra whitespace."""
    if not text or not text.strip():
        return ""
    
    text = text.strip()
    
    # Remove markdown fences
    if text.startswith("```"):
        lines = text.split("```")
        if len(lines) >= 2:
            text = lines[1]
            if text.startswith("json"):
                text = text[4:]
    
    text = text.strip()
    
    # Handle JSON arrays: if response is [{ ... }, { ... }], extract first object
    if text.startswith("["):
        # Find the first complete JSON object in the array
        brace_count = 0
        in_string = False
        escape_next = False
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
            if not in_string:
                if char == "{":
                    brace_count += 1
                    if brace_count == 1:
                        start_idx = i
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0 and 'start_idx' in locals():
                        return text[start_idx:i+1].strip()
        return ""
    
    # Find first { and last }
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1].strip()
    
    return text.strip()


def _validate_json_response(data: dict[str, Any], required_keys: list[str] = None) -> bool:
    """Validate that parsed JSON has required structure."""
    if not isinstance(data, dict):
        return False
    if required_keys:
        return all(key in data for key in required_keys)
    return len(data) > 0


def _calculate_news_alignment(signal: str, sentiment_score: int) -> str:
    """FIX #9: Calculate explicit news alignment judgment.
    
    Returns alignment assessment based on signal direction and news sentiment.
    """
    if signal not in {"BUY", "SELL"}:
        return "N/A"
    
    if signal == "BUY":
        if sentiment_score >= 3:
            return "Strong Alignment - Bullish news supports entry"
        elif sentiment_score >= 1:
            return "Alignment - Neutral to bullish news"
        elif sentiment_score >= -2:
            return "Neutral News - Technical setup leads"
        else:
            return "Conflicted Signal - Bearish news opposes entry"
    
    else:  # SELL
        if sentiment_score <= -3:
            return "Strong Alignment - Bearish news supports entry"
        elif sentiment_score <= -1:
            return "Alignment - Neutral to bearish news"
        elif sentiment_score <= 2:
            return "Neutral News - Technical setup leads"
        else:
            return "Conflicted Signal - Bullish news opposes entry"


def _geo_theme(geo: dict[str, Any]) -> str:
    if geo.get("War Risk") == "High":
        return "Geopolitical risk escalation"
    if geo.get("Recession Risk") == "High":
        return "Growth scare risk-off"
    if geo.get("Gold Bias") == "Bullish":
        return "Keyword safe-haven bid"
    if geo.get("Gold Bias") == "Bearish":
        return "Keyword risk-on pressure"
    return "Keyword macro neutral"


def _geo_sentiment_score(geo: dict[str, Any]) -> int:
    score = 0

    gold_bias = str(geo.get("Gold Bias", "Neutral"))
    risk_sentiment = str(geo.get("Risk Sentiment", "Neutral"))

    if gold_bias == "Bullish":
        score += 4
    elif gold_bias == "Bearish":
        score -= 4

    if risk_sentiment == "Risk OFF":
        score += 2
    elif risk_sentiment == "Risk ON":
        score -= 2

    return max(-10, min(10, score))


def _geo_overlay_fields(geo: dict[str, Any]) -> dict[str, Any]:
    return {
        "geo_gold_bias":          geo.get("Gold Bias", "Neutral"),
        "geo_risk_sentiment":     geo.get("Risk Sentiment", "Neutral"),
        "geo_war_risk":           geo.get("War Risk", "Low"),
        "geo_recession_risk":     geo.get("Recession Risk", "Low"),
        "geo_inflation_pressure": geo.get("Inflation Pressure", "Low"),
        "geo_matched_headlines":  geo.get("Matched Headlines", []),
        "geo_has_data":           bool(geo.get("has_data", False)),
    }


def _sentiment_from_geopolitics(geo: dict[str, Any], headlines: list[str]) -> dict[str, Any]:
    matched = geo.get("Matched Headlines", []) or headlines[:1]
    result = {
        "sentiment_score":  _geo_sentiment_score(geo),
        "dominant_theme":   _geo_theme(geo),
        "key_headline":     str(matched[0])[:100] if matched else "",
        **_geo_overlay_fields(geo),
    }
    log_debug(
        f"Keyword geopolitical fallback: score={result['sentiment_score']:+d} | "
        f"bias={result['geo_gold_bias']} | risk={result['geo_risk_sentiment']}"
    )
    return result


def _call_openai(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 300,
    temperature: float = 0.0,
) -> dict[str, Any] | None:
    """Call OpenAI chat completions and parse JSON response.
    
    Includes retry logic for:
    - Rate limits (429)
    - Connection errors
    - JSON parse failures
    """
    openai_api_key = getattr(config, "OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        log_debug("OPENAI_API_KEY not set — skipping AI call.")
        return None

    retry_count = 0
    backoff_secs = _RETRY_BACKOFF_SECS
    json_parse_error_count = 0

    while retry_count <= _MAX_RETRIES:
        try:
            # Make API request
            resp = requests.post(
                _BASE_URL,
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model,
                    "max_tokens":  max(max_tokens, 500),  # Ensure sufficient tokens
                    "temperature": temperature,
                    "messages": [
                        {"role": "system",  "content": system_prompt},
                        {"role": "user",    "content": user_prompt},
                    ],
                },
                timeout=_REQUEST_TIMEOUT,
            )
            
            # Handle rate limiting with exponential backoff
            if resp.status_code == 429:
                if retry_count < _MAX_RETRIES:
                    log_debug(
                        f"OpenAI rate limited (429) — retry in {backoff_secs}s "
                        f"(attempt {retry_count + 1}/{_MAX_RETRIES})"
                    )
                    time.sleep(backoff_secs)
                    backoff_secs *= 2
                    retry_count += 1
                    continue
                else:
                    log_debug(f"OpenAI rate limit exceeded after {_MAX_RETRIES} retries")
                    return None
            
            # Check for auth/permission errors
            if resp.status_code in (401, 403):
                log_debug(
                    f"OpenAI auth error ({resp.status_code}): Check OPENAI_API_KEY. "
                    f"Response: {resp.text[:200]}"
                )
                return None
            
            # Check for server errors (retry)
            if resp.status_code >= 500:
                if retry_count < _MAX_RETRIES:
                    log_debug(
                        f"OpenAI server error ({resp.status_code}) — retry in {backoff_secs}s"
                    )
                    time.sleep(backoff_secs)
                    backoff_secs *= 2
                    retry_count += 1
                    continue
                else:
                    log_debug(f"OpenAI server error ({resp.status_code}) after retries")
                    return None
            
            resp.raise_for_status()
            
            # Extract response content
            try:
                resp_json = resp.json()
                if "choices" not in resp_json or len(resp_json["choices"]) == 0:
                    log_debug(f"OpenAI empty response: {resp_json}")
                    return None
                
                raw = resp_json["choices"][0]["message"]["content"].strip()
            except (KeyError, ValueError, json.JSONDecodeError, IndexError) as exc:
                log_debug(
                    f"OpenAI response structure error: {exc}. "
                    f"Full response: {resp.text[:500]}"
                )
                return None
            
            # Try to extract JSON from response
            json_str = _extract_json_from_response(raw)
            
            if not json_str:
                log_debug(f"Could not extract JSON from response: {raw[:200]}")
                return None
            
            # Parse JSON with better error context
            try:
                parsed = json.loads(json_str)
                
                # Basic validation
                if not _validate_json_response(parsed):
                    log_debug(f"Response is valid JSON but empty/invalid: {parsed}")
                    return None
                
                log_debug(f"OpenAI call successful ({model})")
                return parsed
                
            except json.JSONDecodeError as exc:
                json_parse_error_count += 1
                # Log full response for debugging
                log_debug(
                    f"JSON decode error (attempt {json_parse_error_count}): {exc}. "
                    f"Raw response preview: {json_str[:300]}"
                )
                
                # Retry on JSON parse errors (might be transient)
                if json_parse_error_count < 2 and retry_count < _MAX_RETRIES:
                    log_debug(f"Retrying due to JSON parse error...")
                    time.sleep(backoff_secs)
                    backoff_secs *= 2
                    retry_count += 1
                    continue
                
                return None

        except requests.exceptions.Timeout:
            if retry_count < _MAX_RETRIES:
                log_debug(
                    f"OpenAI timeout ({model}) — retry in {backoff_secs}s"
                )
                time.sleep(backoff_secs)
                backoff_secs *= 2
                retry_count += 1
                continue
            else:
                log_debug(f"OpenAI timeout ({model}) — connection took too long after retries")
                return None
                
        except requests.exceptions.ConnectionError as exc:
            if retry_count < _MAX_RETRIES:
                log_debug(
                    f"OpenAI connection error: {exc} — retry in {backoff_secs}s"
                )
                time.sleep(backoff_secs)
                backoff_secs *= 2
                retry_count += 1
                continue
            else:
                log_debug(f"OpenAI connection error after retries: {exc}")
                return None
                
        except Exception as exc:
            log_debug(f"OpenAI call failed ({model}): {type(exc).__name__}: {exc}")
            return None

    log_debug(f"OpenAI call exhausted all retries ({_MAX_RETRIES})")
    return None


# ---------------------------------------------------------------------------
# Stage 1 — News sentiment scoring
# ---------------------------------------------------------------------------

_SENTIMENT_SYSTEM = """You are a gold (XAUUSD) macro analyst.
Score the provided headlines for their net impact on gold price RIGHT NOW.

CRITICAL INSTRUCTIONS:
1. Reply with ONLY ONE SINGLE valid JSON object summarizing ALL headlines combined
2. NOT one JSON object per headline — combine them into ONE summary
3. No markdown, no arrays, no extra text, no explanation
4. Return exactly this structure:

{
  "sentiment_score": <integer from -10 to +10>,
  "dominant_theme": "<3-6 word macro theme>",
  "key_headline": "<exact headline text>"
}

Scoring:
+8-+10: Major risk-off, war, Fed cuts, USD crash
+4-+7: Rate cuts, geopolitical, inflation up, dollar weak
+1-+3: Mildly gold-supportive
0: Neutral / conflicting
-1-3: Mildly gold-negative
-4-7: Strong USD, hawkish Fed, risk-on
-8-10: Major risk-on, rate hikes, strong jobs"""


def get_news_sentiment(headlines: list[str]) -> dict[str, Any]:
    """Stage 1: cheap news sentiment scoring from headlines.

    Returns:
        {sentiment_score, dominant_theme, key_headline}
        or keyword-based geopolitical fallback if the API is unavailable.
    """
    geo = analyze_geopolitics(headlines)

    if not headlines:
        return {
            "sentiment_score": 0,
            "dominant_theme": "No news available",
            "key_headline": "",
            **_geo_overlay_fields(geo),
        }

    prompt = "Rate these gold-relevant headlines:\n\n" + "\n".join(
        f"{i+1}. {h}" for i, h in enumerate(headlines[:15])
    )

    log_debug(f"Calling sentiment API with {len(headlines)} headlines...")
    result = _call_openai(
        system_prompt=_SENTIMENT_SYSTEM,
        user_prompt=prompt,
        model=_SENTIMENT_MODEL,
        max_tokens=200,
        temperature=0.0,  # Deterministic JSON output
    )

    if result is None:
        log_debug("News sentiment API unavailable - using keyword geopolitical fallback.")
        return _sentiment_from_geopolitics(geo, headlines)

    # Validate and extract sentiment fields
    try:
        score = int(result.get("sentiment_score", 0))
        score = max(-10, min(10, score))  # Clamp to valid range
        theme = str(result.get("dominant_theme", "Unknown"))[:60]
        headline = str(result.get("key_headline", ""))[:100]
    except (ValueError, TypeError) as exc:
        log_debug(
            f"Sentiment response validation error: {exc} - "
            "using keyword geopolitical fallback."
        )
        return _sentiment_from_geopolitics(geo, headlines)
    
    log_debug(
        f"News sentiment: {score:+d} | theme: {theme} | "
        f"key: {headline[:60]}"
    )
    return {
        "sentiment_score":  score,
        "dominant_theme":   theme,
        "key_headline":     headline,
        **_geo_overlay_fields(geo),
    }


# ---------------------------------------------------------------------------
# Stage 2 — Full hybrid decision
# ---------------------------------------------------------------------------

_DECISION_SYSTEM = """You are a senior XAUUSD (gold) day trader. Make the FINAL trading decision.

CRITICAL: Reply with ONLY valid JSON, no markdown, no explanation, no extra text.

{
  "final_signal": "BUY" or "SELL" or "WAIT_FOR_CONFIRMATION" or "NO TRADE",
  "confidence": <integer 40-95>,
  "news_alignment": "confirms" or "contradicts" or "neutral",
  "macro_context": "<2 sentences on gold macro>",
  "entry_rationale": "<why trade NOW>",
  "key_risk": "<biggest risk>",
  "reasoning": "<3-4 sentences>"
}

RULES:
- Higher timeframe technical bias is primary. News is secondary.
- CRITICAL SELL BIAS: When conflicted between BUY and SELL signals, STRONGLY prefer SELL. BUY is the riskier call in intraday. False BUY signals cost more than false SELLs.
- NEVER veto a strong technical setup only because headlines contradict it.
- If news contradicts technicals, reduce confidence or prefer WAIT_FOR_CONFIRMATION.
- Use WAIT_FOR_CONFIRMATION when H4/H1 bias exists but M5/M1 timing is not aligned yet.
- If high_impact_news=True and the event is within 15 minutes, prefer WAIT_FOR_CONFIRMATION instead of forcing a new trade.
- Thin volume lowers confidence. It is not a hard block by itself.
- Respect H1/H4 trend context; avoid BUY into bearish higher timeframes or SELL into bullish ones
- Factor nearby daily/weekly pivot support and resistance into the decision
- For borderline scores, news sentiment is only a secondary tiebreaker
- Confidence 85-95: textbook with alignment
- Confidence 70-84: solid, minor concerns
- Confidence 55-69: marginal
- Confidence 45-54: weak but valid only as WAIT_FOR_CONFIRMATION
- Use NO TRADE only when there is no meaningful edge or the setup is clearly invalidated.

TIER 1 HARD VETO CONDITIONS (OVERRIDE TO WAIT_FOR_CONFIRMATION):
1. If M15 volume_classification=\"Low\" AND volume_ratio < 0.4:
   VETO: Thin-volume ghost town. confidence < 60% forces WAIT.
   
2. If high_impact_event within ±10 minutes:
   VETO: Pre/post-event liquidity hole. confidence < 70% forces WAIT.
   
3. If all_vol_low=True AND mixed_signals=True AND confidence < 65%:
   VETO: Ambiguous direction + thin volume. Force WAIT.
   
4. If RSI_caution=True AND M1_counter=True (both gates active):
   VETO: Double negation (both overbought AND counter signal). Force WAIT.
   
5. If setup_direction=\"BUY\" AND H4_trend contains \"Weak\" (not \"Strong\"):
   CAP confidence at 65% max (weak trend = weak setup).

INTERMARKET RULES:
- If intermarket_score >= +5 AND technical signal is BUY: confidence floor rises to 70%
- If intermarket_score >= +5 AND technical signal is SELL: confidence floor rises to 70%
- If intermarket_score <= -3 AND technical signal is BUY: reduce confidence by 15 points
- If intermarket_score <= -3 AND technical signal is SELL: reduce confidence by 15 points
- If intermarket_score <= -4: output NO TRADE regardless of technical signal
- A strong intermarket confirmation (+5 or higher) can override a borderline technical score that would otherwise be NO TRADE
"""


def get_final_decision(
    symbol:               str,
    technical_signal:     str,
    setup_direction:      str,
    technical_score:      float,
    max_score:            float,
    technical_confidence: int,
    timeframe_indicators: dict[str, dict[str, Any]],
    key_levels_text:      str,
    news_sentiment:       dict[str, Any],
    headlines:            list[str],
    calendar_events:      str,
    high_impact_news:     bool,
    high_impact_event:    dict[str, Any] | None,
    all_volume_low:       bool,
    mixed_signals:        bool,
    rsi_caution:          bool,
    m1_counter:           bool,
    entry_timing_state:   str = "not_actionable",
    wait_reason:          str = "",
    wait_trigger:         str = "",
    intermarket_data:     dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 2: full hybrid decision using all available context.

    Returns rich decision dict or falls back to technical-only signal.
    """
    h4  = timeframe_indicators.get("H4",  {})
    h1  = timeframe_indicators.get("H1",  {})
    m15 = timeframe_indicators.get("M15", {})
    m5  = timeframe_indicators.get("M5",  {})
    m1  = timeframe_indicators.get("M1",  {})

    def _f(v: Any, d: int = 2) -> str:
        try:
            return f"{float(v):.{d}f}" if v is not None else "N/A"
        except Exception:
            return "N/A"

    minutes_away_text = "N/A"
    if high_impact_event and high_impact_event.get("minutes_away") is not None:
        minutes_away_text = f"{float(high_impact_event['minutes_away']):.0f}"

    # Build the user prompt — structured, dense, complete
    prompt = f"""=== XAUUSD TRADING DECISION REQUEST ===

TECHNICAL ANALYSIS (Python rule engine)
  Setup Direction:      {setup_direction}
  Weighted Score:       {technical_score:+.1f} / {max_score:.1f}
  Technical Confidence: {technical_confidence}%
  Mixed Timeframes:     {mixed_signals}
  RSI Caution Active:   {rsi_caution}
  M1 Counter-Signal:    {m1_counter}
  Entry Timing State:   {entry_timing_state}
  Wait Reason:          {wait_reason or 'N/A'}
  Wait Trigger:         {wait_trigger or 'N/A'}
  M15 Volume Thin:      {all_volume_low}
  High-Impact News Now: {high_impact_news}
  {f"Nearest Event:        {high_impact_event.get('event_name')} in {minutes_away_text} min" if high_impact_event else ""}
  Technical Signal:     {technical_signal} (⚠️ SELL-BIAS CORRECTION: If conflicted between BUY and SELL, prefer SELL—reduce false buying in rallies)

H4 TIMEFRAME (macro structure)
  Trend:          {h4.get('trend_classification', 'N/A')}
  RSI(14):        {_f(h4.get('rsi_14'))}
  Price vs VWAP:  {h4.get('price_vs_vwap', 'N/A')}
  ATR Ratio:      {_f(h4.get('atr_ratio'))}

H1 TIMEFRAME (intraday bias)
  Trend:          {h1.get('trend_classification', 'N/A')}
  RSI(14):        {_f(h1.get('rsi_14'))}
  Price vs VWAP:  {h1.get('price_vs_vwap', 'N/A')}
  ATR Ratio:      {_f(h1.get('atr_ratio'))}

M15 TIMEFRAME (primary signal timeframe)
  Close:          {_f(m15.get('close'), 4)}
  Trend:          {m15.get('trend_classification', 'N/A')}
  RSI(14):        {_f(m15.get('rsi_14'))}
  RSI Signal:     {m15.get('rsi_signal', 'N/A')}
  VWAP:           {_f(m15.get('vwap'), 4)}
  Price vs VWAP:  {m15.get('price_vs_vwap', 'N/A')}
  EMA20:          {_f(m15.get('ema_20'), 4)}
  EMA50:          {_f(m15.get('ema_50'), 4)}
  ATR(14):        {_f(m15.get('atr_14'))}
  ATR Ratio:      {_f(m15.get('atr_ratio'))}
  Volume Ratio:   {_f(m15.get('volume_ratio'))}
  Volume Class:   {m15.get('volume_classification', 'N/A')}
  Volatility:     {m15.get('volatility_classification', 'N/A')}

M5 TIMEFRAME (entry timing)
  Trend:         {m5.get('trend_classification', 'N/A')}
  RSI(14):       {_f(m5.get('rsi_14'))}
  Price vs VWAP: {m5.get('price_vs_vwap', 'N/A')}
  Volume Ratio:  {_f(m5.get('volume_ratio'))}

M1 TIMEFRAME (immediate momentum)
  Trend:         {m1.get('trend_classification', 'N/A')}
  RSI(14):       {_f(m1.get('rsi_14'))}
  ATR Ratio:     {_f(m1.get('atr_ratio'))}
  Price vs VWAP: {m1.get('price_vs_vwap', 'N/A')}

KEY LEVELS (daily/weekly pivots from last closed sessions)
{key_levels_text}

NEWS SENTIMENT (AI-scored from real-time headlines)
  Sentiment Score:  {news_sentiment.get('sentiment_score', 0):+d} / 10
  Dominant Theme:   {news_sentiment.get('dominant_theme', 'N/A')}
  Key Headline:     {news_sentiment.get('key_headline', 'None')[:120]}

KEYWORD GEOPOLITICAL OVERLAY (fast rule-based)
  Gold Bias:          {news_sentiment.get('geo_gold_bias', 'N/A')}
  Risk Sentiment:     {news_sentiment.get('geo_risk_sentiment', 'N/A')}
  War Risk:           {news_sentiment.get('geo_war_risk', 'N/A')}
  Recession Risk:     {news_sentiment.get('geo_recession_risk', 'N/A')}
  Inflation Pressure: {news_sentiment.get('geo_inflation_pressure', 'N/A')}
  Matched Headlines:  {', '.join(news_sentiment.get('geo_matched_headlines', [])[:3]) or 'None'}

ECONOMIC CALENDAR (today's high-impact events)
{calendar_events}

{intermarket_data.get('prompt_text', '') if intermarket_data else "INTERMARKET CORRELATION: Not analyzed this run."}

TOP HEADLINES (most recent first)
{chr(10).join(f"  • {h}" for h in headlines[:8])}

Based on all of the above, make your final trading decision."""

    log_debug(f"Calling decision API for {technical_signal} candidate...")
    result = _call_openai(
        system_prompt=_DECISION_SYSTEM,
        user_prompt=prompt,
        model=_DECISION_MODEL,
        max_tokens=500,
        temperature=0.0,  # Deterministic JSON output
    )

    if result is None:
        log_debug("AI decision unavailable — falling back to technical signal.")
        return _technical_fallback(technical_signal, technical_confidence, technical_score)

    # Validate response structure
    try:
        final_signal = str(result.get("final_signal", technical_signal)).upper().strip()
        if final_signal not in {"BUY", "SELL", "WAIT_FOR_CONFIRMATION", "NO TRADE"}:
            log_debug(f"Invalid signal '{final_signal}' in response — using technical signal")
            final_signal = technical_signal

        confidence = int(result.get("confidence", technical_confidence))
        confidence = max(40, min(95, confidence))
    except (ValueError, TypeError) as exc:
        log_debug(f"Decision response parsing error: {exc} — using technical signal")
        return _technical_fallback(technical_signal, technical_confidence, technical_score)

    minutes_away = high_impact_event.get("minutes_away") if high_impact_event else None
    imminent_event = bool(
        high_impact_news
        and high_impact_event
        and minutes_away is not None
        and minutes_away <= 15
    )

    if technical_signal == "WAIT_FOR_CONFIRMATION" and final_signal in {"BUY", "SELL"}:
        final_signal = "WAIT_FOR_CONFIRMATION"

    if imminent_event and final_signal in {"BUY", "SELL"}:
        log_debug("High-impact event is too close for immediate execution — downgrading to WAIT.")
        final_signal = "WAIT_FOR_CONFIRMATION"

    if confidence < 55 and final_signal in {"BUY", "SELL"}:
        log_debug(f"AI confidence {confidence}% < 55 — downgrading to WAIT.")
        final_signal = "WAIT_FOR_CONFIRMATION"

    # Determine alignment based on technical signal and sentiment
    raw_alignment = str(result.get("news_alignment", "neutral")).lower().strip()
    if raw_alignment not in {"confirms", "contradicts", "neutral"}:
        raw_alignment = "neutral"
    
    sent_score = news_sentiment.get("sentiment_score", 0)
    
    # FIX #9: Use explicit alignment formula instead of naive comparison
    alignment = _calculate_news_alignment(final_signal, sent_score)
    
    # If AI returned explicit alignment, respect it; otherwise use formula
    if raw_alignment in {"confirms", "contradicts"}:
        alignment = raw_alignment

    if alignment == "contradicts":
        if final_signal in {"BUY", "SELL"}:
            confidence = max(45, confidence - 6)
        elif final_signal == "WAIT_FOR_CONFIRMATION":
            confidence = max(40, confidence - 4)

    if (
        technical_signal in {"BUY", "SELL"}
        and abs(technical_score) >= 6.0
        and final_signal == "NO TRADE"
        and not imminent_event
    ):
        log_debug("Strong technical score preserved despite contradictory macro — converting NO TRADE to WAIT.")
        final_signal = "WAIT_FOR_CONFIRMATION"

    if technical_signal == "WAIT_FOR_CONFIRMATION" and final_signal == "NO TRADE" and setup_direction in {"BUY", "SELL"}:
        final_signal = "WAIT_FOR_CONFIRMATION"
    
    # ===== INTERMARKET CORRELATION RULES =====
    if intermarket_data:
        im_score = intermarket_data.get("intermarket_score", 0)
        
        # Strong confirmation: raise confidence floor to 70%
        if im_score >= 5 and final_signal in {"BUY", "SELL"}:
            confidence = max(confidence, 70)
            log_debug(f"Intermarket strong confirmation (+{im_score}) — confidence floor raised to 70%")
        
        # Significant headwind: reduce confidence by 15 points
        if im_score <= -3 and final_signal in {"BUY", "SELL"}:
            confidence = max(45, confidence - 15)
            log_debug(f"Intermarket headwind ({im_score}) — confidence reduced by 15 points to {confidence}%")
        
        # Very strong headwind: force NO TRADE
        if im_score <= -4 and final_signal in {"BUY", "SELL"}:
            log_debug(f"Intermarket very strong headwind ({im_score}) — forcing NO TRADE")
            final_signal = "NO TRADE"
        
        # Strong confirmation can override NO TRADE on borderline technicals
        if im_score >= 5 and final_signal == "NO TRADE" and technical_signal in {"BUY", "SELL"} and not imminent_event:
            log_debug(f"Intermarket strong confirmation (+{im_score}) overrides borderline NO TRADE — converting to WAIT")
            final_signal = "WAIT_FOR_CONFIRMATION"
            confidence = max(confidence, 60)
    
    # ===== TIER 1: AI VETO SYSTEM =====
    vetoed = False
    veto_reason = ""
    
    # Veto 1: Thin volume zone
    m15_vol_ratio = float(timeframe_indicators.get("M15", {}).get("volume_ratio") or 0.5)
    m15_vol_class = str(timeframe_indicators.get("M15", {}).get("volume_classification", ""))
    if (m15_vol_class == "Low" and m15_vol_ratio < 0.4):
        if confidence < 60:
            vetoed = True
            veto_reason = "Thin volume zone (ratio < 0.4)"
    
    # Veto 2: Pre/post event
    if high_impact_event and high_impact_event.get("minutes_away") is not None:
        mins_away = float(high_impact_event.get("minutes_away", 999))
        if -10 <= mins_away <= 10:
            if confidence < 70:
                vetoed = True
                veto_reason = f"Pre/post-event zone ({high_impact_event.get('event_name', 'Event')})"
    
    # Veto 3: Low vol + mixed signals
    if all_volume_low and mixed_signals and confidence < 65:
        vetoed = True
        veto_reason = "Low volume + mixed signals"
    
    # Veto 4: Both RSI gates fired
    if rsi_caution and m1_counter:
        vetoed = True
        veto_reason = "Double negation (RSI caution + M1 counter)"
    
    # Veto 5: Weak trend for BUY
    h4_trend = str(timeframe_indicators.get("H4", {}).get("trend_classification", ""))
    if setup_direction == "BUY" and "Weak" in h4_trend and "Strong" not in h4_trend:
        confidence = min(65, confidence)
        log_debug(f"Confidence capped at 65 due to weak H4 trend")
    
    if vetoed and final_signal in {"BUY", "SELL"}:
        log_debug(f"🚫 AI VETO: {veto_reason} — forcing WAIT_FOR_CONFIRMATION")
        final_signal = "WAIT_FOR_CONFIRMATION"
        confidence = max(40, confidence - 15)
    
    decision = {
        "final_signal":    final_signal,
        "confidence":      confidence,
        "news_alignment":  alignment,
        "macro_context":   result.get("macro_context", ""),
        "entry_rationale": result.get("entry_rationale", ""),
        "key_risk":        result.get("key_risk", ""),
        "reasoning":       result.get("reasoning", ""),
        "ai_used":         True,
        "news_sentiment":  news_sentiment.get("sentiment_score", 0),
    }

    log_debug(
        f"AI decision: {final_signal} | confidence={confidence}% | "
        f"news_alignment={decision['news_alignment']} | "
        f"sentiment={decision['news_sentiment']:+d}"
    )
    return decision


def _technical_fallback(
    signal: str, confidence: int, score: float
) -> dict[str, Any]:
    """Used when OpenAI is unavailable or Stage 2 AI review is skipped."""
    if signal == "WAIT_FOR_CONFIRMATION":
        return {
            "final_signal":    signal,
            "confidence":      max(40, confidence),
            "news_alignment":  "neutral",
            "macro_context":   "AI unavailable — technical analysis only.",
            "entry_rationale": "Directional setup is valid, but entry timing needs confirmation.",
            "key_risk":        "Lower timeframe trigger has not aligned yet.",
            "reasoning":       (
                f"Technical score {score:+.1f} shows directional edge, but the engine flagged "
                "this setup as a wait state until lower timeframes confirm."
            ),
            "ai_used":         False,
            "news_sentiment":  0,
        }
    return {
        "final_signal":    signal,
        "confidence":      confidence,
        "news_alignment":  "neutral",
        "macro_context":   "AI unavailable — technical analysis only.",
        "entry_rationale": f"Technical score {score:+.1f} cleared threshold.",
        "key_risk":        "No news context available — increased uncertainty.",
        "reasoning":       (
            f"Technical score {score:+.1f} with {confidence}% rule-based confidence. "
            "AI confirmation unavailable — treat this signal with extra caution."
        ),
        "ai_used":         False,
        "news_sentiment":  0,
    }
