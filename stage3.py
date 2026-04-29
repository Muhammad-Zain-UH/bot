"""STAGE 3: EXPENSIVE APIs — News sentiment + AI verification (parallel execution).

Only runs if STAGE 2 gate passes.
Uses Anthropic Claude API (not OpenAI).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import config
from geopolitics import analyze_geopolitics
from news_handler import check_high_impact_news, fetch_economic_calendar, format_calendar_for_prompt
from rss_feed import get_headline_strings
from utils import log_debug

try:
    import anthropic
except ImportError:
    anthropic = None


def fetch_news_sentiment(headlines: list[str]) -> dict[str, Any]:
    """Score news sentiment from headlines using keyword analysis.
    
    Fast, free alternative when Claude API is unavailable.
    Scores from -10 (very bearish) to +10 (very bullish).
    Includes has_data flag to indicate if relevant headlines were found.
    
    FIX 3: Age-based sentiment discounting:
    - Articles older than 3 hours: 50% of sentiment score
    - Articles older than 6 hours: 25% of sentiment score
    - Newer articles: 100% of sentiment score
    """
    import re
    
    try:
        log_debug("[STAGE 3] Fetching news sentiment (keyword analysis)...")
        
        # Check if we have any headlines at all
        has_data = bool(headlines) and len(headlines) > 0
        
        if not has_data:
            log_debug("[STAGE 3] No gold-relevant headlines found — returning neutral")
            return {
                "sentiment_score": 5,
                "dominant_theme": "Unknown",
                "geo_gold_bias": "Neutral",
                "geo_risk_sentiment": "Neutral",
                "analysis": {},
                "has_data": False,
                "filter_note": "No gold-relevant headlines in RSS feeds",
            }
        
        # FIX 3: Parse age from headline strings and apply discount
        # Headline format: "[source | Xh ago] text"
        age_discounted_headlines = []
        age_discount_log = []
        
        for headline in headlines:
            # Extract age from headline string
            match = re.search(r'\|\s*([\d.]+)h\s+ago\]', headline)
            if match:
                age_hours = float(match.group(1))
                
                # Determine discount multiplier
                if age_hours > 6.0:
                    discount = 0.25
                elif age_hours > 3.0:
                    discount = 0.50
                else:
                    discount = 1.0
                
                # For now, we keep the original headline for analysis
                # The discount will be applied to the sentiment score later
                age_discounted_headlines.append((headline, age_hours, discount))
                
                if discount < 1.0:
                    age_discount_log.append(f"{age_hours:.1f}h ago → {discount*100:.0f}% weight")
            else:
                # No age found in headline, assume recent (100% discount)
                age_discounted_headlines.append((headline, 0, 1.0))
        
        if age_discount_log:
            log_debug(f"[STAGE 3] Age-based sentiment discount applied: {', '.join(age_discount_log)}")
        
        # Use geopolitics module for keyword-based analysis (on original headlines)
        headline_texts = [h[0] for h in age_discounted_headlines]
        geo_analysis = analyze_geopolitics(headline_texts)
        
        # Calculate base sentiment score
        base_sentiment_score = 0
        if "Bullish" in geo_analysis.get("Gold Bias", ""):
            base_sentiment_score = 5
        elif "Bearish" in geo_analysis.get("Gold Bias", ""):
            base_sentiment_score = -5
        else:
            base_sentiment_score = 0
        
        # FIX 3: Apply average age discount to sentiment score
        avg_discount = sum(h[2] for h in age_discounted_headlines) / len(age_discounted_headlines) if age_discounted_headlines else 1.0
        final_sentiment_score = int(base_sentiment_score * avg_discount)
        
        log_debug(
            f"[STAGE 3] News sentiment: base={base_sentiment_score} × avg_discount={avg_discount:.2f} → final={final_sentiment_score}"
        )
        
        return {
            "sentiment_score": final_sentiment_score,
            "dominant_theme": geo_analysis.get("Dominant Theme", "N/A"),
            "geo_gold_bias": geo_analysis.get("Gold Bias", "Neutral"),
            "geo_risk_sentiment": geo_analysis.get("Risk Sentiment", "Neutral"),
            "analysis": geo_analysis,
            "has_data": True,
            "filter_note": f"Scoring based on {len(headline_texts)} gold-relevant articles (age-discounted)",
        }
    
    except Exception as exc:
        log_debug(f"[STAGE 3] News sentiment error: {exc}")
        return {
            "sentiment_score": 0,
            "dominant_theme": "Unknown",
            "geo_gold_bias": "Neutral",
            "geo_risk_sentiment": "Neutral",
            "analysis": {},
            "has_data": False,
            "filter_note": "Error fetching news sentiment",
        }


def call_claude_verification(
    direction: str,
    confidence: int,
    score: float,
    timeframe_indicators: dict[str, dict[str, Any]],
    intermarket_data: dict[str, Any],
    news_sentiment: dict[str, Any],
    headlines: list[str],
) -> dict[str, Any]:
    """Call Claude API for AI verification.
    
    Returns a decision structure with confirmation, confidence adjustment, and reasoning.
    Falls back gracefully if API unavailable or key is missing.
    """
    if not anthropic or not config.ANTHROPIC_API_KEY:
        log_debug("[STAGE 3] Claude API key not configured — skipping AI verification")
        return {
            "confirmed": False,
            "confidence_adjustment": 0,
            "reason": "AI unavailable",
            "risk_note": "Technical setup leads without AI confirmation",
            "suggested_sl_adjustment": 0,
        }
    
    try:
        log_debug("[STAGE 3] Calling Claude API for verification...")
        
        m15 = timeframe_indicators.get("M15", {})
        m1 = timeframe_indicators.get("M1", {})
        h4 = timeframe_indicators.get("H4", {})
        h1 = timeframe_indicators.get("H1", {})
        
        headlines_str = "\n".join(headlines[:5]) if headlines else "No headlines available"
        
        prompt = f"""
You are a professional XAUUSD trading analyst reviewing a setup for execution.

TECHNICAL SIGNAL:
- Direction: {direction}
- Score: {score:.2f}/12.5
- Confidence: {confidence}%

TIMEFRAME ALIGNMENT:
- H4: {h4.get('trend_classification', 'Unknown')}
- H1: {h1.get('trend_classification', 'Unknown')}
- M15: {m15.get('trend_classification', 'Unknown')}
- M1 RSI: {m1.get('rsi_14', 'N/A')}

INTERMARKET CORRELATION:
- Score: {intermarket_data.get('intermarket_score', 0)} ({intermarket_data.get('alignment_label', 'Neutral')})
- Silver (XAGUSD): {intermarket_data.get('silver_trend', 'Unknown')}
- DXY/USD Index: {intermarket_data.get('dxy_trend', 'Unknown')}

NEWS SENTIMENT:
- Score: {news_sentiment.get('sentiment_score', 0)}/10
- Theme: {news_sentiment.get('dominant_theme', 'N/A')}
- Gold Bias: {news_sentiment.get('geo_gold_bias', 'Neutral')}

RECENT HEADLINES:
{headlines_str}

Based on this analysis, decide if the setup should execute.

Reply with ONLY a JSON object (no other text):
{{
    "confirmed": true or false,
    "confidence_adjustment": number between -20 and +20,
    "reason": "one sentence explanation",
    "risk_note": "one sentence on biggest risk",
    "suggested_sl_adjustment": 0
}}
"""
        
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        raw = response.content[0].text.strip()
        
        # Extract JSON from response
        result = json.loads(raw)
        
        log_debug(
            f"[STAGE 3] Claude response: confirmed={result.get('confirmed')} | "
            f"adjustment={result.get('confidence_adjustment', 0):+d}%"
        )
        
        return result
    
    except json.JSONDecodeError as exc:
        log_debug(f"[STAGE 3] Claude JSON parse error: {exc} — retrying...")
        # Retry once
        time.sleep(1)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text.strip()
            result = json.loads(raw)
            return result
        except Exception:
            log_debug("[STAGE 3] Claude retry failed — falling back")
            return {
                "confirmed": False,
                "confidence_adjustment": 0,
                "reason": "AI verification failed",
                "risk_note": "Technical setup only — no AI confirmation available",
                "suggested_sl_adjustment": 0,
            }
    
    except Exception as exc:
        log_debug(f"[STAGE 3] Claude API error: {exc} — falling back to technical-only")
        return {
            "confirmed": False,
            "confidence_adjustment": 0,
            "reason": "API unavailable",
            "risk_note": "Technical setup only",
            "suggested_sl_adjustment": 0,
        }


def run_stage3(
    direction: str,
    confidence: int,
    score: float,
    timeframe_indicators: dict[str, dict[str, Any]],
    intermarket_data: dict[str, Any],
) -> dict[str, Any]:
    """Execute STAGE 3: Expensive APIs in parallel.
    
    Fetches:
    1. News sentiment (economic calendar + RSS headlines)
    2. AI verification (Claude API)
    
    Returns:
        {
            "passed": bool,  # Whether GATE 3 is passed
            "ai_decision": dict,  # Claude response
            "news_sentiment": dict,  # News sentiment score
            "gates": dict,  # Gate information
            "error": str | None,
        }
    """
    try:
        log_debug("[STAGE 3] Starting expensive API calls (news + AI)...")
        
        # Fetch in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Task 1: News sentiment
            news_future = executor.submit(lambda: {
                "sentiment": fetch_news_sentiment(get_headline_strings(limit=20)),
                "events": fetch_economic_calendar(),
                "headlines": get_headline_strings(limit=20),
            })
            
            # Task 2: AI verification
            ai_future = executor.submit(
                call_claude_verification,
                direction=direction,
                confidence=confidence,
                score=score,
                timeframe_indicators=timeframe_indicators,
                intermarket_data=intermarket_data,
                news_sentiment={},  # Will be filled after news fetch
                headlines=[],  # Will be filled after news fetch
            )
            
            # Wait for news first
            news_data = news_future.result()
            sentiment = news_data["sentiment"]
            headlines = news_data["headlines"]
            events = news_data["events"]
            
            # Now call AI with actual news sentiment
            ai_decision = call_claude_verification(
                direction=direction,
                confidence=confidence,
                score=score,
                timeframe_indicators=timeframe_indicators,
                intermarket_data=intermarket_data,
                news_sentiment=sentiment,
                headlines=headlines,
            )
        
        log_debug(f"[STAGE 3] News sentiment: {sentiment.get('sentiment_score', 0)}/10")
        log_debug(f"[STAGE 3] AI confirmed: {ai_decision.get('confirmed')}")
        
        # GATE 3 CHECK
        news_score = sentiment.get("sentiment_score", 0)
        ai_confirmed = ai_decision.get("confirmed", False)
        
        gate3_passed = ai_confirmed and news_score > -3
        
        if not ai_confirmed:
            log_debug(f"[STAGE 3] AI rejected the setup: {ai_decision.get('reason')}")
        
        if news_score <= -3:
            log_debug(f"[STAGE 3] News sentiment too bearish ({news_score}) — blocking entry")
        
        return {
            "passed": gate3_passed,
            "ai_decision": ai_decision,
            "news_sentiment": sentiment,
            "headlines": headlines,
            "events": events,
            "gates": {
                "ai_confirmed": ai_confirmed,
                "news_sentiment_score": news_score,
            },
            "error": None,
        }
    
    except Exception as exc:
        log_debug(f"[STAGE 3] ERROR: {exc}")
        # On error, don't block the signal — cap confidence at 45% instead
        return {
            "passed": True,  # Allow through with reduced confidence
            "ai_decision": {
                "confirmed": False,
                "confidence_adjustment": -20,  # Cap at 45% if originally 65%+
                "reason": "API error — reduced confidence",
                "risk_note": "Insufficient data for full verification",
                "suggested_sl_adjustment": 0,
            },
            "news_sentiment": {
                "sentiment_score": 0,
                "dominant_theme": "Unknown",
                "geo_gold_bias": "Neutral",
            },
            "headlines": [],
            "events": [],
            "gates": {},
            "error": str(exc),
        }
