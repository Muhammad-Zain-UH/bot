"""Write formatted trading signal report to result.txt for Claude review.

After both Stage 1 and Stage 2 gates pass, writes a complete, formatted signal
report that the user can copy-paste into Claude for free AI analysis.

The file contains 11 sections with all necessary context, conflict detection,
and 5 questions for Claude to answer.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from utils import log_debug


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value: Any, default: str = "N/A") -> str:
    """Safely convert value to string."""
    if value is None:
        return default
    return str(value).strip() or default


def _get_tf_trend(indicators: dict[str, dict[str, Any]], tf: str) -> str:
    """Get trend classification for a timeframe."""
    return _safe_str(
        indicators.get(tf, {}).get("trend_classification"),
        "N/A"
    )


def _get_tf_rsi(indicators: dict[str, dict[str, Any]], tf: str) -> float | None:
    """Get RSI for a timeframe."""
    rsi = indicators.get(tf, {}).get("rsi_14")
    if rsi is None:
        return None
    try:
        return float(rsi)
    except (ValueError, TypeError):
        return None


def _get_tf_vwap(indicators: dict[str, dict[str, Any]], tf: str) -> str:
    """Get VWAP position for a timeframe."""
    return _safe_str(
        indicators.get(tf, {}).get("price_vs_vwap"),
        "N/A"
    )


def _get_tf_volume(indicators: dict[str, dict[str, Any]], tf: str) -> str:
    """Get volume classification for a timeframe."""
    return _safe_str(
        indicators.get(tf, {}).get("volume_classification"),
        "N/A"
    )


def _get_atm_m15(indicators: dict[str, dict[str, Any]]) -> float | None:
    """Get ATR for M15."""
    atr = indicators.get("M15", {}).get("atr_14")
    if atr is None:
        return None
    try:
        return float(atr)
    except (ValueError, TypeError):
        return None


def _describe_stop_location(
    direction: str,
    sl_price: float | None,
    key_levels: dict[str, Any] | None,
) -> str:
    """
    Returns a human-readable description of where the stop loss is relative
    to key structural levels.
    """
    if not sl_price or not key_levels:
        return "ATR-based (no nearby structure level)"
    
    daily_levels = key_levels.get("daily", {}) or {}
    current_price = _safe_float(key_levels.get("current_price"))
    
    levels = {
        "Daily R2": _safe_float(daily_levels.get("r2")),
        "Daily R1": _safe_float(daily_levels.get("r1")),
        "Daily PP": _safe_float(daily_levels.get("pivot")),
        "Daily S1": _safe_float(daily_levels.get("s1")),
        "Daily S2": _safe_float(daily_levels.get("s2")),
        "Weekly R1": _safe_float(key_levels.get("weekly", {}).get("r1")),
        "Weekly PP": _safe_float(key_levels.get("weekly", {}).get("pivot")),
        "Weekly S1": _safe_float(key_levels.get("weekly", {}).get("s1")),
    }
    
    closest_label = None
    closest_dist = float("inf")
    
    for label, price in levels.items():
        if price is None:
            continue
        dist = abs(sl_price - price)
        if dist < closest_dist:
            closest_dist = dist
            closest_label = label
    
    if closest_label is None:
        return "ATR-based (no nearby structure level)"
    
    position = "above" if sl_price > (current_price or 0) else "below"
    
    if closest_dist <= 3.0:
        return (f"At {closest_label} @ {levels[closest_label]:.2f} "
                f"({closest_dist:.1f} pts — tight to structure)")
    elif closest_dist <= 8.0:
        return (f"Near {closest_label} @ {levels[closest_label]:.2f} "
                f"({closest_dist:.1f} pts away)")
    else:
        return (f"ATR-based — nearest level is {closest_label} "
                f"@ {levels[closest_label]:.2f} "
                f"({closest_dist:.1f} pts away)")


def _calculate_distance_pips(entry: float, target: float) -> float:
    """Calculate distance in pips (assuming XAUUSD is quoted in 0.01 increments)."""
    if entry is None or target is None:
        return 0.0
    return abs(target - entry)


def _calculate_alignment_score(direction: str, indicators: dict[str, dict[str, Any]]) -> int:
    """Count how many timeframes support the signal direction."""
    if direction not in {"BUY", "SELL"}:
        return 0
    
    bullish_trends = {"Strong Bullish", "Weak Bullish"}
    bearish_trends = {"Strong Bearish", "Weak Bearish"}
    target_trends = bullish_trends if direction == "BUY" else bearish_trends
    
    count = 0
    for tf in ("H4", "H1", "M15", "M5", "M1"):
        trend = _get_tf_trend(indicators, tf)
        if trend in target_trends:
            count += 1
    
    return count


def _calculate_macro_confirmation(
    direction: str,
    intermarket_data: dict[str, Any]
) -> tuple[int, int]:
    """Count how many intermarket assets support the signal.
    
    NEW RULES:
    - EURUSD: YES/NO based on correlation with direction
    - XAGUSD: YES/NO based on correlation with direction  
    - US500: NEUTRAL (doesn't count for or against)
    
    Returns: (confirmed_count, total_available)
    where total_available excludes NEUTRAL assets
    """
    if direction not in {"BUY", "SELL"}:
        return 0, 0
    
    bullish_trends = {"Strong Bullish", "Weak Bullish"}
    bearish_trends = {"Strong Bearish", "Weak Bearish"}
    
    confirmed = 0
    total = 0
    
    # EURUSD: For SELL, want Bearish EURUSD (strong dollar)
    #         For BUY, want Bullish EURUSD (weak dollar)
    eurusd_trend = _safe_str(intermarket_data.get("dxy_trend"), "")
    if eurusd_trend and eurusd_trend != "N/A" and "Neutral" not in eurusd_trend:
        total += 1
        if (direction == "SELL" and any(b in eurusd_trend for b in bearish_trends)) or \
           (direction == "BUY" and any(b in eurusd_trend for b in bullish_trends)):
            confirmed += 1
    
    # XAGUSD (Silver): Should match gold direction
    xagusd_trend = _safe_str(intermarket_data.get("silver_trend"), "")
    if xagusd_trend and xagusd_trend != "N/A" and "Neutral" not in xagusd_trend:
        total += 1
        target = bullish_trends if direction == "BUY" else bearish_trends
        if any(t in xagusd_trend for t in target):
            confirmed += 1
    
    # US500: NEUTRAL — doesn't count toward confirmation
    # (no code needed, just skip it)
    
    return confirmed, total


def _calculate_trade_viability_score(
    direction: str,
    tf_alignment: int,
    macro_confirm: int,
    macro_total: int,
    confidence: int,
    h4_trend: str,
    gold_bias: str,
    events: list[dict[str, Any]] | None,
    news_has_data: bool,
    calendar_is_fallback: bool,
    conflict_count: int,
) -> tuple[int, str, dict[str, Any]]:
    """Calculate Trade Viability Score (0-100).
    
    Combines multiple factors:
    - Timeframe alignment (0-10 pts)
    - Macro confirmation (0-10 pts)
    - Confidence level (0-8 pts)
    - H4 direction alignment (0 to -10 pts)
    - News/Gold bias alignment (0 to -8 pts)
    - Economic events risk (-5 to +3 pts)
    - Conflict penalties (-8 pts each)
    - Blind spots (-5 pts each)
    """
    score = 50  # Base score
    breakdown = {}
    
    # TF ALIGNMENT: 0-10 pts
    if tf_alignment >= 5:
        tf_points = 10
    elif tf_alignment >= 4:
        tf_points = 7
    elif tf_alignment >= 3:
        tf_points = 3
    else:
        tf_points = 0
    score += tf_points
    breakdown["TF Alignment"] = tf_points
    
    # MACRO CONFIRMATION: 0-10 pts
    if macro_total > 0:
        conf_ratio = macro_confirm / macro_total
        if conf_ratio >= 1.0:
            macro_points = 10
        elif conf_ratio >= 0.66:
            macro_points = 6
        elif conf_ratio >= 0.33:
            macro_points = 2
        else:
            macro_points = 0
    else:
        macro_points = 0
    score += macro_points
    breakdown["Macro Confirm"] = macro_points
    
    # CONFIDENCE: 0-8 pts
    if confidence >= 70:
        conf_points = 8
    elif confidence >= 60:
        conf_points = 5
    elif confidence >= 50:
        conf_points = 2
    else:
        conf_points = 0
    score += conf_points
    breakdown["Confidence"] = conf_points
    
    # H4 DIRECTION: +5 to -10
    if direction in {"BUY", "SELL"}:
        if (direction == "BUY" and "Bullish" in h4_trend) or \
           (direction == "SELL" and "Bearish" in h4_trend):
            h4_points = 5
        elif (direction == "BUY" and "Bearish" in h4_trend) or \
             (direction == "SELL" and "Bullish" in h4_trend):
            h4_points = -10
        else:
            h4_points = 0
    else:
        h4_points = 0
    score += h4_points
    breakdown["H4 Direction"] = h4_points
    
    # NEWS/GOLD BIAS: +5 to -8
    if direction in {"BUY", "SELL"}:
        if (direction == "BUY" and "Bullish" in gold_bias) or \
           (direction == "SELL" and "Bearish" in gold_bias):
            news_points = 5
        elif (direction == "BUY" and "Bearish" in gold_bias) or \
             (direction == "SELL" and "Bullish" in gold_bias):
            news_points = -8
        else:
            news_points = 0
    else:
        news_points = 0
    score += news_points
    breakdown["News Alignment"] = news_points
    
    # ECONOMIC EVENTS: -5 to +3
    event_points = 3  # Default: no nearby events
    if events:
        for event in events:
            mins_away = event.get("minutes_away", 999)
            if abs(mins_away) <= 60:
                event_points = -5
                break
            elif abs(mins_away) <= 240:
                event_points = -3
                break
    score += event_points
    breakdown["Event Risk"] = event_points
    
    # CONFLICT PENALTIES: -8 per warning
    conflict_penalty = conflict_count * -8
    score += conflict_penalty
    breakdown["Conflict Penalty"] = conflict_penalty
    
    # BLIND SPOT PENALTIES
    if not news_has_data:
        score -= 5
        breakdown["News Blind"] = -5
    else:
        breakdown["News Blind"] = 0
    
    if calendar_is_fallback:
        score -= 5
        breakdown["Calendar Blind"] = -5
    else:
        breakdown["Calendar Blind"] = 0
    
    # CLAMP SCORE 0-100
    final_score = max(0, min(100, int(score)))
    
    # Interpret score
    if final_score >= 81:
        interpretation = "STRONG — high confidence, full position size"
    elif final_score >= 66:
        interpretation = "GOOD — solid setup, normal position size"
    elif final_score >= 51:
        interpretation = "CAUTION — tradeable but manage size carefully"
    elif final_score >= 31:
        interpretation = "WAIT — conditions improving but not ready"
    else:
        interpretation = "DO NOT TRADE — too many conflicts"
    
    return final_score, interpretation, breakdown


def _detect_conflicts(
    direction: str,
    confidence: int,
    indicators: dict[str, dict[str, Any]],
    intermarket_data: dict[str, Any],
    news_data: dict[str, Any] | None,
) -> list[str]:
    """Detect and return list of conflict warnings."""
    warnings = []
    
    if direction not in {"BUY", "SELL"}:
        return warnings
    
    # CONFLICT 1: H4 opposes signal direction
    h4_trend = _get_tf_trend(indicators, "H4")
    if direction == "SELL" and "Strong Bullish" in h4_trend:
        warnings.append(
            "⚠ WARNING: Selling against Strong Bullish H4 trend\n"
            "             — counter-trend trade, higher risk"
        )
    elif direction == "BUY" and "Strong Bearish" in h4_trend:
        warnings.append(
            "⚠ WARNING: Buying against Strong Bearish H4 trend\n"
            "             — counter-trend trade, higher risk"
        )
    
    # CONFLICT 2: News opposes signal
    if news_data:
        gold_bias = _safe_str(news_data.get("gold_bias"), "")
        if direction == "SELL" and "Bullish" in gold_bias:
            warnings.append(
                "⚠ WARNING: News/macro is Bullish on gold but signal is SELL\n"
                "             — news opposes trade direction"
            )
        elif direction == "BUY" and "Bearish" in gold_bias:
            warnings.append(
                "⚠ WARNING: News/macro is Bearish on gold but signal is BUY\n"
                "             — news opposes trade direction"
            )
    
    # CONFLICT 3: War risk on SELL
    if news_data:
        war_risk = _safe_str(news_data.get("war_risk"), "")
        if direction == "SELL" and "High" in war_risk:
            warnings.append(
                "⚠ WARNING: High war risk detected — gold typically rallies\n"
                "             on geopolitical tension. Selling gold is dangerous."
            )
    
    # CONFLICT 4: Silver divergence
    xagusd_trend = _safe_str(intermarket_data.get("silver_trend"), "")
    if direction == "BUY" and "Bearish" in xagusd_trend:
        warnings.append(
            "⚠ WARNING: Silver is Bearish while signal is BUY\n"
            "             — gold/silver divergence detected"
        )
    elif direction == "SELL" and "Bullish" in xagusd_trend:
        warnings.append(
            "⚠ WARNING: Silver is Bullish while signal is SELL\n"
            "             — gold/silver divergence detected"
        )
    
    # CONFLICT 5: M1 overbought/oversold
    m1_rsi = _get_tf_rsi(indicators, "M1")
    if m1_rsi is not None:
        if m1_rsi > 68 and direction == "BUY":
            warnings.append(
                f"⚠ WARNING: M1 RSI at {m1_rsi:.1f} — overbought on entry\n"
                "             timeframe. Pullback risk before target."
            )
        elif m1_rsi < 32 and direction == "SELL":
            warnings.append(
                f"⚠ WARNING: M1 RSI at {m1_rsi:.1f} — oversold on entry\n"
                "             timeframe. Bounce risk before target."
            )
    
    return warnings


def _calculate_grade(
    tf_alignment: int,
    macro_confirm: int,
    macro_total: int,
    conflict_count: int,
) -> str:
    """Calculate overall setup grade."""
    # Normalize macro_confirm to out of 3 (assuming max 3 available)
    macro_score = (macro_confirm / max(macro_total, 1)) * 3 if macro_total > 0 else 0
    
    if tf_alignment >= 5 and macro_score >= 3 and conflict_count == 0:
        return "A+ GRADE"
    elif tf_alignment >= 4 and macro_score >= 2 and conflict_count == 0:
        return "A  GRADE"
    elif tf_alignment >= 3 and macro_score >= 2 and conflict_count <= 1:
        return "B  GRADE"
    elif tf_alignment >= 3 and macro_score >= 1 and conflict_count <= 2:
        return "C  GRADE"
    else:
        return "D  GRADE"


def _format_headline_list(news_data: dict[str, Any] | None) -> str:
    """Format headlines for the report."""
    if not news_data:
        return "  No live headlines — RSS feeds offline. Manual news check recommended."
    
    headlines = news_data.get("headlines", [])
    if not headlines:
        return "  No live headlines — RSS feeds offline. Manual news check recommended."
    
    lines = []
    for i, hl in enumerate(headlines[:5], 1):
        lines.append(f"  {i}. {hl}")
    
    return "\n".join(lines) if lines else "  No live headlines — RSS feeds offline. Manual news check recommended."


def _format_economic_events(news_data: dict[str, Any] | None) -> str:
    """Format economic events for the report."""
    if not news_data:
        return "  No high-impact events scheduled next 4h"
    
    events = news_data.get("events", [])
    if not events:
        return "  No high-impact events scheduled next 4h"
    
    lines = []
    for event in events[:10]:
        time_str = event.get("time", "Unknown")
        name = event.get("event_name", "Unknown")
        impact = event.get("impact", "")
        lines.append(f"  • {time_str} {name} ({impact})")
    
    return "\n".join(lines) if lines else "  No high-impact events scheduled next 4h"


def write_result_txt(
    tech: dict[str, Any],
    intermarket: dict[str, Any],
    news: dict[str, Any] | None,
    key_levels: dict[str, Any] | None,
    session: str,
) -> None:
    """Write complete signal report to result.txt.
    
    Args:
        tech: Technical signal dict from stage1 (has indicators, trade_levels, etc.)
        intermarket: Intermarket analysis dict from stage2
        news: News/geopolitics data (may be None or incomplete)
        key_levels: Key levels data from key_levels module
        session: Current session name ("London", "NewYork", etc.)
    """
    try:
        # Extract data with safe fallbacks
        direction = _safe_str(tech.get("setup_direction"), "WAIT")
        confidence = int(tech.get("confidence", 0))
        score = _safe_float(tech.get("score"), 0.0)
        max_score = _safe_float(tech.get("max_score"), 12.5)
        risk_level = _safe_str(tech.get("risk_level"), "Unknown")
        indicators = tech.get("indicators", {})
        trade_levels = tech.get("trade_levels", {})
        
        entry_price = _safe_float(trade_levels.get("entry_price"))
        stop_loss = _safe_float(trade_levels.get("stop_loss"))
        take_profit = _safe_float(trade_levels.get("take_profit"))
        risk_distance = _safe_float(trade_levels.get("risk_distance"))
        
        # Calculate reward distance and risk/reward
        reward_distance = _calculate_distance_pips(entry_price, take_profit)
        risk_reward_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0
        
        # News fallbacks
        if not news:
            news = {}
        news_sentiment_score = int(news.get("sentiment_score", 0)) if news.get("sentiment_score") else 0
        gold_bias = _safe_str(news.get("gold_bias"), "Unknown — RSS offline")
        risk_sentiment = _safe_str(news.get("risk_sentiment"), "Neutral")
        war_risk = _safe_str(news.get("war_risk"), "Unknown")
        recession_risk = _safe_str(news.get("recession_risk"), "Unknown")
        inflation_pressure = _safe_str(news.get("inflation_pressure"), "Unknown")
        
        # Calculate alignment and macro scores
        tf_alignment = _calculate_alignment_score(direction, indicators)
        macro_confirm, macro_total = _calculate_macro_confirmation(direction, intermarket)
        
        # Detect conflicts
        conflicts = _detect_conflicts(direction, confidence, indicators, intermarket, news)
        
        # Calculate grade
        grade = _calculate_grade(tf_alignment, macro_confirm, macro_total, len(conflicts))
        
        # Get ATR
        atr_m15 = _get_atm_m15(indicators)
        atr_str = f"{atr_m15:.1f} pts" if atr_m15 else "N/A pts"
        
        # Current price from intermarket or trade_levels
        current_price = entry_price or _safe_float(indicators.get("M15", {}).get("close"))
        
        # Key levels formatting
        daily_levels = key_levels.get("daily", {}) if key_levels else None
        weekly_levels = key_levels.get("weekly", {}) if key_levels else None
        current_price_from_levels = _safe_float(key_levels.get("current_price")) if key_levels else current_price
        
        # Build the report
        lines = []
        
        # SECTION 1: Header
        lines.append("=" * 66)
        lines.append("  XAUUSD SIGNAL — READY FOR CLAUDE REVIEW")
        lines.append(f"  Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Session   : {session}")
        
        # Add AI verification status
        try:
            import config
            if not hasattr(config, 'ANTHROPIC_API_KEY') or not config.ANTHROPIC_API_KEY:
                lines.append("  ⚠ AI OFFLINE — manual review required")
            else:
                lines.append("  [AI status to be updated by Stage 3]")
        except Exception:
            lines.append("  ⚠ AI OFFLINE — manual review required")
        
        lines.append("")
        lines.append("  HOW TO USE: Open this file → Ctrl+A → Ctrl+C →")
        lines.append("  Paste into Claude chat → Get free AI verdict")
        lines.append("=" * 66)
        lines.append("")
        
        # SECTION 2: Claude Instruction Block
        lines.append("You are a professional XAUUSD trading analyst with 15 years")
        lines.append("experience. Review this live trading signal completely and")
        lines.append("give your verdict. Be direct and specific.")
        lines.append("Do not give generic advice. Answer the 5 questions at")
        lines.append("the bottom of this report.")
        lines.append("")
        
        # SECTION 3: Signal Summary Box
        lines.append("=" * 66)
        lines.append("  SIGNAL SUMMARY")
        lines.append("=" * 66)
        lines.append("")
        lines.append(f"  Direction       : {direction}")
        lines.append(f"  Confidence      : {confidence}%")
        lines.append(f"  Technical Score : {score:.2f} / {max_score:.1f}")
        lines.append(f"  Risk Level      : {risk_level}")
        lines.append(f"  Session         : {session}")
        
        entry_str = f"{entry_price:.2f}" if entry_price else "N/A"
        stop_str = f"{stop_loss:.2f}" if stop_loss else "N/A"
        take_str = f"{take_profit:.2f}" if take_profit else "N/A"
        risk_str = f"{risk_distance:.1f}" if risk_distance else "N/A"
        reward_str = f"{reward_distance:.1f}" if reward_distance else "N/A"
        rr_str = f"1:{risk_reward_ratio:.1f}" if risk_reward_ratio > 0 else "N/A"
        
        lines.append(f"  Entry Price     : {entry_str}")
        lines.append(f"  Stop Loss       : {stop_str}  ({risk_str} pts from entry)")
        lines.append(f"  Take Profit     : {take_str}  ({reward_str} pts from entry)")
        lines.append(f"  Risk/Reward     : {rr_str}")
        lines.append(f"  ATR (M15)       : {atr_str}")
        lines.append("")
        
        # SECTION 4: Timeframe Alignment Table
        lines.append("=" * 66)
        lines.append("  TIMEFRAME ALIGNMENT")
        lines.append("=" * 66)
        lines.append("")
        lines.append("  TF   | Trend           | RSI   | vs VWAP | Volume")
        lines.append("  " + "─" * 60)
        
        for tf in ("H4", "H1", "M15", "M5", "M1"):
            trend = _get_tf_trend(indicators, tf)
            rsi = _get_tf_rsi(indicators, tf)
            vwap = _get_tf_vwap(indicators, tf)
            volume = _get_tf_volume(indicators, tf)
            
            rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
            trend_padded = trend.ljust(15)
            rsi_padded = rsi_str.rjust(5)
            vwap_padded = vwap.ljust(7)
            volume_padded = volume.ljust(6)
            
            lines.append(f"  {tf:3} | {trend_padded} | {rsi_padded} | {vwap_padded} | {volume_padded}")
        
        lines.append("")
        lines.append(f"  Alignment score: {tf_alignment}/5 timeframes support {direction} direction")
        lines.append("")
        
        # SECTION 5: Key Price Levels
        lines.append("=" * 66)
        lines.append("  KEY PRICE LEVELS")
        lines.append("=" * 66)
        lines.append("")
        
        display_price = current_price_from_levels or current_price or entry_price or 0
        lines.append(f"  Current Price    : {display_price:.2f}")
        
        if daily_levels:
            daily_pivot = _safe_float(daily_levels.get("pivot"))
            daily_r1 = _safe_float(daily_levels.get("r1"))
            daily_r2 = _safe_float(daily_levels.get("r2"))
            daily_s1 = _safe_float(daily_levels.get("s1"))
            daily_s2 = _safe_float(daily_levels.get("s2"))
            
            lines.append(f"  Daily Pivot PP   : {daily_pivot:.2f}  ({_calculate_distance_pips(display_price, daily_pivot):.1f} pts away)")
            lines.append(f"  Daily R1         : {daily_r1:.2f}  ({_calculate_distance_pips(display_price, daily_r1):.1f} pts away)")
            lines.append(f"  Daily R2         : {daily_r2:.2f}  ({_calculate_distance_pips(display_price, daily_r2):.1f} pts away)")
            lines.append(f"  Daily S1         : {daily_s1:.2f}  ({_calculate_distance_pips(display_price, daily_s1):.1f} pts away)")
            lines.append(f"  Daily S2         : {daily_s2:.2f}  ({_calculate_distance_pips(display_price, daily_s2):.1f} pts away)")
        else:
            lines.append("  Daily Pivot PP   : N/A")
            lines.append("  Daily R1         : N/A")
            lines.append("  Daily R2         : N/A")
            lines.append("  Daily S1         : N/A")
            lines.append("  Daily S2         : N/A")
        
        if weekly_levels:
            weekly_pivot = _safe_float(weekly_levels.get("pivot"))
            weekly_r1 = _safe_float(weekly_levels.get("r1"))
            weekly_s1 = _safe_float(weekly_levels.get("s1"))
            
            lines.append(f"  Weekly PP        : {weekly_pivot:.2f}  ({_calculate_distance_pips(display_price, weekly_pivot):.1f} pts away)")
            lines.append(f"  Weekly R1        : {weekly_r1:.2f}  ({_calculate_distance_pips(display_price, weekly_r1):.1f} pts away)")
            lines.append(f"  Weekly S1        : {weekly_s1:.2f}  ({_calculate_distance_pips(display_price, weekly_s1):.1f} pts away)")
        else:
            lines.append("  Weekly PP        : N/A")
            lines.append("  Weekly R1        : N/A")
            lines.append("  Weekly S1        : N/A")
        
        lines.append("  " + "─" * 60)
        
        entry_level_str = f"{entry_price:.2f}" if entry_price else "N/A"
        risk_level_str = f"{risk_distance:.1f}" if risk_distance else "N/A"
        reward_level_str = f"{reward_distance:.1f}" if reward_distance else "N/A"
        
        lines.append(f"  Planned Entry    : {entry_level_str}")
        lines.append(f"  Entry → Stop     : {risk_level_str} pts")
        lines.append(f"  Entry → Target   : {reward_level_str} pts")
        
        # Describe stop loss location relative to structural levels
        stop_description = _describe_stop_location(direction, stop_loss, key_levels)
        lines.append(f"  Stop location    : {stop_description}")
        lines.append("")
        
        # SECTION 6: Intermarket Correlation
        lines.append("=" * 66)
        lines.append("  INTERMARKET CORRELATION")
        lines.append("=" * 66)
        lines.append("")
        
        intermarket_score = intermarket.get("intermarket_score", 0)
        intermarket_label = intermarket.get("alignment_label", "Neutral")
        score_label = f"+{intermarket_score}" if intermarket_score >= 0 else str(intermarket_score)
        lines.append(f"  Overall Score  : {score_label}  ({intermarket_label})")
        lines.append("")
        lines.append("  Symbol   | Trend           | RSI   | Supports {0}?".format(direction))
        lines.append("  " + "─" * 55)
        
        # EURUSD (USD Index)
        eurusd_trend = _safe_str(intermarket.get("dxy_trend"), "N/A")
        eurusd_rsi = _safe_float(intermarket.get("dxy_rsi"))
        eurusd_rsi_str = f"{eurusd_rsi:.1f}" if eurusd_rsi else "N/A"
        
        # For SELL: want Bearish EURUSD (strong dollar)
        # For BUY: want Bullish EURUSD (weak dollar)
        if eurusd_trend != "N/A":
            if (direction == "SELL" and "Bearish" in eurusd_trend) or (direction == "BUY" and "Bullish" in eurusd_trend):
                supports = "YES"
            elif "Neutral" in eurusd_trend or eurusd_trend == "Neutral":
                supports = "NEUTRAL"
            else:
                supports = "NO"
        else:
            supports = "N/A"
        
        eurusd_trend_padded = eurusd_trend.ljust(15)
        lines.append(f"  EURUSD   | {eurusd_trend_padded} | {eurusd_rsi_str:>5} | {supports}")
        
        # XAGUSD (Silver)
        xagusd_trend = _safe_str(intermarket.get("silver_trend"), "N/A")
        xagusd_rsi = _safe_float(intermarket.get("silver_rsi"))
        xagusd_rsi_str = f"{xagusd_rsi:.1f}" if xagusd_rsi else "N/A"
        
        # Silver should match gold direction
        if xagusd_trend != "N/A":
            if (direction == "BUY" and "Bullish" in xagusd_trend) or (direction == "SELL" and "Bearish" in xagusd_trend):
                supports = "YES"
            elif "Neutral" in xagusd_trend or xagusd_trend == "Neutral":
                supports = "NEUTRAL"
            else:
                supports = "NO"
        else:
            supports = "N/A"
        
        xagusd_trend_padded = xagusd_trend.ljust(15)
        lines.append(f"  XAGUSD   | {xagusd_trend_padded} | {xagusd_rsi_str:>5} | {supports}")
        
        # US500 (Equities/Risk Sentiment)
        us500_trend = _safe_str(intermarket.get("sp500_trend"), "N/A")
        us500_rsi = _safe_float(intermarket.get("sp500_rsi"))
        us500_rsi_str = f"{us500_rsi:.1f}" if us500_rsi else "N/A"
        
        # For BUY (risk-off), want Bearish US500
        # For SELL (risk-on), want Bullish US500
        if us500_trend != "N/A":
            if (direction == "BUY" and "Bearish" in us500_trend) or (direction == "SELL" and "Bullish" in us500_trend):
                supports = "YES"
            elif "Neutral" in us500_trend or us500_trend == "Neutral":
                supports = "NEUTRAL"
            else:
                supports = "NO"
        else:
            supports = "N/A"
        
        us500_trend_padded = us500_trend.ljust(15)
        lines.append(f"  US500    | {us500_trend_padded} | {us500_rsi_str:>5} | {supports}")
        
        lines.append("")
        lines.append(f"  Macro confirmation: {macro_confirm}/{macro_total} correlated assets support signal")
        lines.append("")
        
        # SECTION 7: News and Geopolitical Context
        lines.append("=" * 66)
        lines.append("  NEWS AND GEOPOLITICAL CONTEXT")
        lines.append("=" * 66)
        lines.append("")
        lines.append(f"  Sentiment Score     : {news_sentiment_score}/10")
        lines.append(f"  Gold Bias           : {gold_bias}")
        lines.append(f"  Risk Sentiment      : {risk_sentiment}")
        lines.append(f"  War Risk            : {war_risk}")
        lines.append(f"  Recession Risk      : {recession_risk}")
        lines.append(f"  Inflation Pressure  : {inflation_pressure}")
        lines.append("")
        lines.append("  Top 5 Headlines:")
        lines.append(_format_headline_list(news))
        lines.append("")
        lines.append("  Economic Events Next 4 Hours:")
        lines.append(_format_economic_events(news))
        lines.append("")
        
        # SECTION 8: Trade Viability Score
        lines.append("=" * 66)
        lines.append("  TRADE VIABILITY SCORE")
        lines.append("=" * 66)
        lines.append("")
        
        # Check if calendar is using fallback (estimated events)
        calendar_is_fallback = False
        if news and news.get("events"):
            calendar_is_fallback = all(
                event.get("estimated", False) 
                for event in news.get("events", [])
            )
        
        # Get news has_data flag
        news_has_data = bool(news) and news.get("has_data", True)
        
        # Calculate viability score
        h4_trend = _get_tf_trend(indicators, "H4")
        viability_score, interpretation, breakdown = _calculate_trade_viability_score(
            direction=direction,
            tf_alignment=tf_alignment,
            macro_confirm=macro_confirm,
            macro_total=macro_total,
            confidence=confidence,
            h4_trend=h4_trend,
            gold_bias=gold_bias,
            events=news.get("events", []) if news else [],
            news_has_data=news_has_data,
            calendar_is_fallback=calendar_is_fallback,
            conflict_count=len(conflicts),
        )
        
        lines.append(f"  Score: {viability_score} / 100")
        lines.append(f"  Rating: {interpretation}")
        lines.append("")
        lines.append("  Score breakdown:")
        for component, points in breakdown.items():
            if points != 0:
                sign = "+" if points > 0 else ""
                lines.append(f"    {component:<20} : {sign}{points:3d} pts")
        
        lines.append(f"    {'─' * 40}")
        lines.append(f"    {'Total':<20} : {viability_score:3d} / 100")
        lines.append("")
        
        # SECTION 9: Conflict Warnings
        lines.append("=" * 66)
        lines.append("  CONFLICT WARNINGS")
        lines.append("=" * 66)
        lines.append("")
        
        if conflicts:
            for warning in conflicts:
                lines.append(warning)
                lines.append("")
        else:
            lines.append("  ✓ No major conflicts detected in this setup")
            lines.append("")
        
        # SECTION 10: Quick Stats Summary
        lines.append("=" * 66)
        lines.append("  QUICK STATS SUMMARY")
        lines.append("=" * 66)
        lines.append("")
        lines.append(f"  TF Alignment    : {tf_alignment}/5 support {direction} direction")
        lines.append(f"  Macro Confirm   : {macro_confirm}/{macro_total} intermarket assets confirm")
        lines.append(f"  Conflict Count  : {len(conflicts)} warnings detected")
        lines.append("")
        lines.append(f"  Overall Setup Quality: {grade}")
        lines.append("")
        
        # SECTION 11: Five Questions for Claude
        lines.append("=" * 66)
        lines.append("  FIVE QUESTIONS FOR CLAUDE")
        lines.append("=" * 66)
        lines.append("")
        lines.append("Please answer all 5 questions:")
        lines.append("")
        lines.append(f"Q1. Should I EXECUTE this {direction} trade, SKIP it, or")
        lines.append("    WAIT for a better entry? Give ONE clear answer.")
        lines.append("")
        lines.append("Q2. What is the single biggest risk with this specific")
        lines.append("    setup right now — not generic risk, THIS setup.")
        lines.append("")
        lines.append(f"Q3. Does the current news and macro environment support")
        lines.append(f"    or oppose this {direction} on gold right now?")
        lines.append("")
        
        q4_price_str = f"{entry_price:.2f}" if entry_price else "N/A"
        lines.append(f"Q4. Is {q4_price_str} a good entry, or should I wait for a")
        lines.append("    specific price level? If so, what level and why?")
        lines.append("")
        lines.append("Q5. Rate this setup overall: A / B / C / D and explain")
        lines.append("    in one sentence why.")
        lines.append("")
        lines.append("Answer in this exact format — nothing else:")
        lines.append("Q1 VERDICT    : EXECUTE / SKIP / WAIT")
        lines.append("Q2 RISK       : [one sentence]")
        lines.append("Q3 MACRO      : SUPPORTS / OPPOSES / NEUTRAL + one reason")
        lines.append("Q4 ENTRY      : GOOD / WAIT FOR [price]")
        lines.append("Q5 GRADE      : [A/B/C/D] — [one sentence reason]")
        lines.append("EXTRA NOTE    : [anything critical I should know]")
        lines.append("")
        
        # SECTION 11: Footer
        lines.append("=" * 66)
        lines.append(f"Generated by XAUUSD Trading Bot | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("Bot continues monitoring — file updates on 5%+ conf change")
        lines.append("Check live MT5 price before executing — may be up to 5 min old")
        lines.append("=" * 66)
        
        # Write file
        content = "\n".join(lines)
        # Get bot root: result_writer.py is in utils/, so go up 2 levels
        result_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "result.txt"
        )
        
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        log_debug(f"[RESULT] Signal report written to {result_path}")
    
    except Exception as exc:
        log_debug(f"[RESULT] ERROR writing result.txt: {exc}")
        raise


def write_signal_expired(reason: str, old_direction: str, old_conf: int) -> None:
    """Write signal expired message to result.txt.
    
    Called when a previously written signal degrades (confidence drops or direction changes).
    """
    try:
        content = f"""================================================================
  XAUUSD SIGNAL — EXPIRED / CONDITIONS CHANGED
  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}
================================================================

PREVIOUS SIGNAL HAS EXPIRED

Reason    : {reason}
Old Setup : {old_direction} at {old_conf}% confidence
Status    : Conditions no longer met — DO NOT EXECUTE

Bot is continuing to monitor for a new setup.
This file will be updated when a new signal is ready.
================================================================
"""
        bot_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result_path = os.path.join(bot_root, "result.txt")
        
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        log_debug(f"[RESULT] Signal expired — result.txt updated")
    
    except Exception as exc:
        log_debug(f"[RESULT] ERROR writing signal expired message: {exc}")
