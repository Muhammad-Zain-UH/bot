"""Keyword-based geopolitical analysis for trading context.

STATUS: INTEGRATED AS A SUPPLEMENTAL OVERLAY
─────────────────────────────────
This module now runs alongside the Stage 1 OpenAI headline sentiment pass.
It provides a fast, free keyword-based geopolitical overlay for:
  1. fallback sentiment when the API is unavailable
  2. extra context for the final AI decision prompt
  3. additional logging/visibility in the live output

The OpenAI analysis remains the primary sentiment model; this module acts as
a lightweight safety net and structured macro context layer.

FIXES vs previous version
──────────────────────────
1. Empty headlines now return Neutral Gold Bias + Neutral Risk Sentiment
   instead of "Bearish" / "Risk ON", which was silently biasing every run
   that had no news feed against BUY signals.

2. Added gold-specific keywords: "dollar", "fed", "tariff", "safe haven",
   "rate cut", "rate hike" — the previous keyword set missed the most common
   gold-moving catalysts.

3. Score threshold for "High" risk lowered from 2 → 1 hit so a single
   clear headline (e.g. just "invasion") registers correctly.
"""

from __future__ import annotations

from typing import Any

from utils import log_debug

WAR_KEYWORDS = (
    "war",
    "conflict",
    "missile",
    "attack",
    "military",
    "invasion",
    "sanction",
    "ceasefire",
    "tension",
    "nuclear",
    "airstrike",
    "troops",
)

RECESSION_KEYWORDS = (
    "recession",
    "slowdown",
    "contraction",
    "job losses",
    "unemployment",
    "gdp miss",
    "credit stress",
    "layoffs",
    "default",
    "bank crisis",
)

INFLATION_KEYWORDS = (
    "inflation",
    "cpi",
    "ppi",
    "price pressure",
    "rate hike",
    "hawkish",
    "sticky prices",
    "tariff",
    "trade war",
    "import duties",
)

# Keywords that directly push gold demand — used for Gold Bias
GOLD_BULLISH_KEYWORDS = (
    "safe haven",
    "gold rally",
    "gold surge",
    "rate cut",
    "dovish",
    "dollar falls",
    "dollar weakens",
    "usd drops",
    "risk off",
    "fear",
    "uncertainty",
    "geopolitical",
)

GOLD_BEARISH_KEYWORDS = (
    "dollar rally",
    "dollar strengthens",
    "usd rises",
    "risk on",
    "rate hike",
    "tightening",
    "hawkish fed",
    "gold drops",
    "gold falls",
)


def _score_keywords(headlines: list[str], keywords: tuple[str, ...]) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    for headline in headlines:
        text = headline.lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            score += hits
            matched.append(headline)
    return score, matched


def _level_from_score(score: int) -> str:
    """FIX: threshold lowered from 2 → 1 so single clear hits register."""
    return "High" if score >= 1 else "Low"


def analyze_geopolitics(headlines: list[str]) -> dict[str, Any]:
    """Analyze headlines and return a geopolitical trading summary.

    FIX: returns Neutral bias when headlines list is empty so the caller
    can distinguish 'no data' from 'data says Bearish'.
    """
    try:
        if not headlines:
            log_debug("No headlines supplied — returning Neutral geopolitical summary.")
            return {
                "War Risk":          "Low",
                "Recession Risk":    "Low",
                "Inflation Pressure":"Low",
                "Gold Bias":         "Neutral",
                "Risk Sentiment":    "Neutral",
                "Matched Headlines": [],
                "has_data":          False,
            }

        war_score,       war_headlines       = _score_keywords(headlines, WAR_KEYWORDS)
        recession_score, recession_headlines = _score_keywords(headlines, RECESSION_KEYWORDS)
        inflation_score, inflation_headlines = _score_keywords(headlines, INFLATION_KEYWORDS)
        gold_bull_score, gold_bull_hl        = _score_keywords(headlines, GOLD_BULLISH_KEYWORDS)
        gold_bear_score, gold_bear_hl        = _score_keywords(headlines, GOLD_BEARISH_KEYWORDS)

        # Gold Bias: combine macro safe-haven score with direct gold keyword score
        safe_haven_score = war_score + recession_score + gold_bull_score
        net_gold_score   = safe_haven_score - gold_bear_score

        if net_gold_score > 0:
            gold_bias = "Bullish"
        elif net_gold_score < 0:
            gold_bias = "Bearish"
        else:
            gold_bias = "Neutral"

        # Risk Sentiment
        risk_off_score = war_score + recession_score
        risk_on_score  = gold_bear_score
        if risk_off_score > risk_on_score:
            risk_sentiment = "Risk OFF"
        elif risk_on_score > risk_off_score:
            risk_sentiment = "Risk ON"
        else:
            risk_sentiment = "Neutral"

        all_matched = (
            war_headlines + recession_headlines + inflation_headlines
            + gold_bull_hl + gold_bear_hl
        )
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped_matched: list[str] = []
        for h in all_matched:
            if h not in seen:
                seen.add(h)
                deduped_matched.append(h)

        analysis = {
            "War Risk":           _level_from_score(war_score),
            "Recession Risk":     _level_from_score(recession_score),
            "Inflation Pressure": _level_from_score(inflation_score),
            "Gold Bias":          gold_bias,
            "Risk Sentiment":     risk_sentiment,
            "Matched Headlines":  deduped_matched[:5],
            "has_data":           True,
        }
        log_debug(f"Geopolitical analysis: {analysis}")
        return analysis

    except Exception as exc:
        log_debug(f"Geopolitical analysis failed: {exc}")
        return {
            "War Risk":          "Low",
            "Recession Risk":    "Low",
            "Inflation Pressure":"Low",
            "Gold Bias":         "Neutral",
            "Risk Sentiment":    "Neutral",
            "Matched Headlines": [],
            "has_data":          False,
        }
