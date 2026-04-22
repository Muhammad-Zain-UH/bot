"""Signal logger — writes every run to CSV for performance analysis.

Fill in the 'outcome' column manually after each trade closes:
  WIN   = price hit take profit
  LOSS  = price hit stop loss
  SKIP  = signal issued but you chose not to take it
  MISSED = you missed the entry
"""

from __future__ import annotations

import csv
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from utils import log_debug

LOG_FILE = os.getenv("SIGNAL_LOG_FILE", "signal_log.csv")

FIELDS = [
    # Identity
    "timestamp", "symbol", "session",
    # Decision
    "signal", "setup_direction", "entry_timing_state", "confidence", "weighted_score", "risk_level",
    # AI analysis
    "ai_used", "news_sentiment_score", "news_alignment",
    "dominant_theme", "key_headline",
    "geo_gold_bias", "geo_risk_sentiment", "geo_war_risk",
    "geo_recession_risk", "geo_inflation_pressure",
    "macro_context", "entry_rationale", "key_risk", "ai_reasoning",
    # Intermarket correlation
    "intermarket_score", "intermarket_label",
    "dxy_trend", "silver_trend",
    # Trade levels
    "entry_price", "stop_loss", "take_profit", "risk_distance", "lot_size",
    "position_size_factor", "position_size_note",
    # M15 technicals
    "m15_trend", "m15_rsi", "m15_vwap_pos", "m15_vol_class", "m15_vol_ratio",
    "m15_atr_ratio", "m15_volatility",
    # M5 technicals
    "m5_trend", "m5_rsi", "m5_vol_ratio",
    # M1 technicals
    "m1_trend", "m1_rsi", "m1_atr_ratio",
    # Gates & flags
    "all_vol_low", "rsi_caution", "m1_counter", "mixed_signals",
    "high_impact_news", "high_impact_event",
    # TIER 1+: New event/confluence/volatility data
    "event_zone", "event_confidence_adjustment", "asian_zone_penalty",
    "volatility_adjusted_threshold", "confluence_bonus", "confluence_reason",
    # Risk context
    "daily_pnl_pct", "account_balance",
    # Full reason
    "reason", "wait_reason", "wait_trigger",
    # Manual outcome (fill after trade closes)
    "outcome",
    # Optional: fill in actual exit price for P&L calculation
    "actual_exit_price", "actual_pnl_pips",
]


def _s(v: Any, d: int = 4) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        if v != v:
            return ""
        return f"{v:.{d}f}"
    s = str(v).replace("\n", " ")
    s = s.replace("—", "-").replace("–", "-").replace("…", "...")
    return s


def _ensure_log_schema() -> None:
    """Upgrade older signal_log.csv headers to the current field layout."""
    if not os.path.isfile(LOG_FILE):
        return

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            existing_fields = reader.fieldnames or []
            if existing_fields == FIELDS:
                return
            rows = list(reader)

        backup_path = LOG_FILE + ".bak"
        if not os.path.isfile(backup_path):
            shutil.copyfile(LOG_FILE, backup_path)

        with open(LOG_FILE, "w", newline="", encoding="utf-8", errors="replace") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for old_row in rows:
                upgraded_row = {field: old_row.get(field, "") for field in FIELDS}
                writer.writerow(upgraded_row)

        log_debug(
            f"Upgraded signal log schema: {len(existing_fields)} -> {len(FIELDS)} columns "
            f"(backup: {backup_path})"
        )
    except Exception as exc:
        log_debug(f"Signal log schema upgrade failed: {exc}")


def _is_duplicate_signal(
    signal: str,
    setup_direction: str,
    weighted_score: float,
    max_minutes_since_last: int = 5,
) -> bool:
    """Check if this signal is a duplicate of one logged in the last N minutes.
    
    Duplicate detection: Same signal + direction + score within tolerance (±1.0)
    within the last 5 minutes. This prevents minute-by-minute re-logs of the same
    technical setup.
    
    Returns True if this is likely a duplicate.
    """
    if signal not in {"BUY", "SELL", "WAIT_FOR_CONFIRMATION"}:
        return False  # NO_TRADE signals are never duplicates
    
    if not os.path.isfile(LOG_FILE):
        return False
    
    try:
        from datetime import timedelta
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_minutes_since_last)
        
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Check last 5 rows (most recent signals)
        for row in rows[-5:]:
            if not row.get("timestamp"):
                continue
            
            try:
                row_time = datetime.fromisoformat(row["timestamp"])
            except Exception:
                continue
            
            if row_time < cutoff_time:
                continue  # Too old, skip
            
            # Same signal type and direction?
            if row.get("signal") == signal and row.get("setup_direction") == setup_direction:
                # Same score (±1.0 tolerance)?
                try:
                    prev_score = float(row.get("weighted_score", "0"))
                    if abs(prev_score - weighted_score) <= 1.0:
                        log_debug(f"DUPLICATE detected: {signal} {setup_direction} score {weighted_score:.2f} (prev {prev_score:.2f})")
                        return True
                except Exception:
                    pass
        
        return False
    except Exception as exc:
        log_debug(f"Duplicate check failed: {exc}")
        return False


def log_signal(
    symbol:             str,
    signal:             str,
    confidence:         int,
    weighted_score:     float,
    risk_level:         str,
    trade_levels:       dict[str, Any],
    timeframe_indicators: dict[str, dict[str, Any]],
    ai_decision:        dict[str, Any],
    news_sentiment:     dict[str, Any],
    high_impact_news:   bool,
    high_impact_event:  dict[str, Any] | None,
    session:            str,
    gates:              dict[str, Any],
    mixed_signals:      bool,
    daily_pnl_pct:      float,
    account_balance:    float,
    lot_size:           float,
    reason:             str,
    intermarket_data:   dict[str, Any] | None = None,
) -> None:
    _ensure_log_schema()
    m15 = timeframe_indicators.get("M15", {})
    m5  = timeframe_indicators.get("M5",  {})
    m1  = timeframe_indicators.get("M1",  {})

    row = {
        "timestamp":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol":             symbol,
        "session":            session,
        "signal":             signal,
        "setup_direction":    ai_decision.get("setup_direction", ""),
        "entry_timing_state": ai_decision.get("entry_timing_state", gates.get("entry_timing_state", "")),
        "confidence":         confidence if signal in {"BUY", "SELL", "WAIT_FOR_CONFIRMATION"} else "",
        "weighted_score":     _s(weighted_score),
        "risk_level":         risk_level,
        # AI
        "ai_used":            _s(ai_decision.get("ai_used", False)),
        "news_sentiment_score": _s(news_sentiment.get("sentiment_score", 0), 0),
        "news_alignment":     ai_decision.get("news_alignment", ""),
        "dominant_theme":     news_sentiment.get("dominant_theme", ""),
        "key_headline":       news_sentiment.get("key_headline", "")[:120],
        "geo_gold_bias":      news_sentiment.get("geo_gold_bias", ""),
        "geo_risk_sentiment": news_sentiment.get("geo_risk_sentiment", ""),
        "geo_war_risk":       news_sentiment.get("geo_war_risk", ""),
        "geo_recession_risk": news_sentiment.get("geo_recession_risk", ""),
        "geo_inflation_pressure": news_sentiment.get("geo_inflation_pressure", ""),
        "macro_context":      ai_decision.get("macro_context", ""),
        "entry_rationale":    ai_decision.get("entry_rationale", ""),
        "key_risk":           ai_decision.get("key_risk", ""),
        "ai_reasoning":       ai_decision.get("reasoning", ""),
        # Intermarket
        "intermarket_score":  _s(intermarket_data.get("intermarket_score", 0), 0) if intermarket_data else "",
        "intermarket_label":  intermarket_data.get("alignment_label", "") if intermarket_data else "",
        "dxy_trend":          intermarket_data.get("dxy_trend", "") if intermarket_data else "",
        "silver_trend":       intermarket_data.get("silver_trend", "") if intermarket_data else "",
        # Trade levels
        "entry_price":        _s(trade_levels.get("entry_price")),
        "stop_loss":          _s(trade_levels.get("stop_loss")),
        "take_profit":        _s(trade_levels.get("take_profit")),
        "risk_distance":      _s(trade_levels.get("risk_distance")),
        "lot_size":           _s(lot_size),
        "position_size_factor": _s(ai_decision.get("position_size_factor", 0.0), 2),
        "position_size_note": ai_decision.get("position_size_note", ""),
        # M15
        "m15_trend":          m15.get("trend_classification", ""),
        "m15_rsi":            _s(m15.get("rsi_14"), 2),
        "m15_vwap_pos":       m15.get("price_vs_vwap", ""),
        "m15_vol_class":      m15.get("volume_classification", ""),
        "m15_vol_ratio":      _s(m15.get("volume_ratio"), 3),
        "m15_atr_ratio":      _s(m15.get("atr_ratio"), 3),
        "m15_volatility":     m15.get("volatility_classification", ""),
        # M5
        "m5_trend":           m5.get("trend_classification", ""),
        "m5_rsi":             _s(m5.get("rsi_14"), 2),
        "m5_vol_ratio":       _s(m5.get("volume_ratio"), 3),
        # M1
        "m1_trend":           m1.get("trend_classification", ""),
        "m1_rsi":             _s(m1.get("rsi_14"), 2),
        "m1_atr_ratio":       _s(m1.get("atr_ratio"), 3),
        # Gates
        "all_vol_low":        _s(gates.get("m15_volume_thin", gates.get("all_vol_low", False))),  # m15_volume_thin replaces all_vol_low
        "rsi_caution":        _s(gates.get("rsi_caution", False)),
        "m1_counter":         _s(gates.get("m1_counter", False)),
        "mixed_signals":      _s(mixed_signals),
        "high_impact_news":   _s(high_impact_news),
        "high_impact_event":  high_impact_event.get("event_name", "") if high_impact_event else "",
        # Risk
        "daily_pnl_pct":      _s(daily_pnl_pct, 2),
        "account_balance":    _s(account_balance, 2),
        "reason":             reason[:300],
        "wait_reason":        ai_decision.get("wait_reason", gates.get("wait_reason", ""))[:180],
        "wait_trigger":       ai_decision.get("wait_trigger", gates.get("wait_trigger", ""))[:180],
        "outcome":            "",
        "actual_exit_price":  "",
        "actual_pnl_pips":    "",
    }

    file_exists = os.path.isfile(LOG_FILE) and os.path.getsize(LOG_FILE) > 0
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8", errors="replace") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if not file_exists:
                writer.writeheader()
            # Sanitize string values to remove problematic characters before writing
            sanitized_row = {}
            for k, v in row.items():
                if isinstance(v, str):
                    # Additional sanitization for CSV
                    sanitized_row[k] = v.encode('utf-8', errors='replace').decode('utf-8')
                else:
                    sanitized_row[k] = v
            writer.writerow(sanitized_row)
        log_debug(
            f"Logged: {signal} @ {row['entry_price'] or 'N/A'} | "
            f"conf={row['confidence']} | score={row['weighted_score']} | "
            f"sentiment={row['news_sentiment_score']} | ai={row['ai_used']}"
        )
    except Exception as exc:
        log_debug(f"Signal log write failed: {exc}")
