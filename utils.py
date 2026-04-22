"""Shared helpers for logging, formatting, and summary creation."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any

# ---------------------------------------------------------------------------
# Logging setup: writes to both console and a rotating log file
# ---------------------------------------------------------------------------
_LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log")
_LOG_LEVEL = logging.DEBUG

_logger = logging.getLogger("trading_bot")
_logger.setLevel(_LOG_LEVEL)

if not _logger.handlers:
    # Console handler
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(_LOG_LEVEL)
    _console_handler.setFormatter(
        logging.Formatter("[DEBUG %(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _logger.addHandler(_console_handler)

    # Rotating file handler — keeps last 5 files of 2 MB each
    _file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _file_handler.setLevel(_LOG_LEVEL)
    _file_handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _logger.addHandler(_file_handler)


def log_debug(message: str) -> None:
    """Log a debug message to both console and the rotating log file."""
    _logger.debug(message)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_number(value: Any, digits: int = 4) -> str:
    """Format numeric values safely for prompts and console output."""
    try:
        if value is None:
            return "N/A"
        if isinstance(value, float) and value != value:  # NaN check
            return "N/A"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def format_news_event(event: dict[str, Any] | None) -> str:
    """Convert a normalized news event into a readable text line."""
    if not event:
        return "No high-impact event detected."

    event_time = event.get("time")
    time_text = (
        event_time.strftime("%Y-%m-%d %H:%M:%S %Z") if event_time else "Unknown time"
    )
    return (
        f"{event.get('event_name', 'Unknown Event')} | "
        f"{time_text} | "
        f"{event.get('impact', 'Unknown')} | "
        f"{event.get('currency', 'Unknown')}"
    )


def build_summary(
    symbol: str,
    indicators: dict[str, Any],
    news_events: list[dict[str, Any]],
    high_impact_news: bool,
    high_impact_event: dict[str, Any] | None,
    geopolitical_summary: dict[str, Any],
) -> str:
    """Create a structured text summary for display or AI prompt input."""
    upcoming_events = [format_news_event(event) for event in news_events[:5]]
    upcoming_events_text = (
        "\n".join(upcoming_events) if upcoming_events else "No calendar events available."
    )
    matched_headlines = geopolitical_summary.get("Matched Headlines", [])
    headline_text = (
        "; ".join(matched_headlines[:5]) if matched_headlines else "No keyword matches found."
    )

    return "\n".join([
        f"Symbol: {symbol}",
        f"Close Price: {_format_number(indicators.get('close'))}",
        f"EMA 20: {_format_number(indicators.get('ema_20'))}",
        f"EMA 50: {_format_number(indicators.get('ema_50'))}",
        f"RSI 14: {_format_number(indicators.get('rsi_14'), digits=2)}",
        f"ATR 14: {_format_number(indicators.get('atr_14'))}",
        f"VWAP: {_format_number(indicators.get('vwap'))}",
        f"Volume Spike: {'Yes' if indicators.get('volume_spike') else 'No'}",
        f"Indicator Bias: {indicators.get('indicator_bias', 'Neutral')}",
        f"Price vs VWAP: {indicators.get('price_vs_vwap', 'Unknown')}",
        f"High Impact News Window: {'Yes' if high_impact_news else 'No'}",
        f"Nearest High Impact Event: {format_news_event(high_impact_event)}",
        "Upcoming Economic Events:",
        upcoming_events_text,
        f"War Risk: {geopolitical_summary.get('War Risk', 'Low')}",
        f"Recession Risk: {geopolitical_summary.get('Recession Risk', 'Low')}",
        f"Inflation Pressure: {geopolitical_summary.get('Inflation Pressure', 'Low')}",
        f"Gold Bias: {geopolitical_summary.get('Gold Bias', 'Bearish')}",
        f"Risk Sentiment: {geopolitical_summary.get('Risk Sentiment', 'Risk ON')}",
        f"Matched Headlines: {headline_text}",
    ])


def build_news_skip_signal(event: dict[str, Any] | None, within_minutes: int) -> str:
    """Create a fixed NO TRADE output when news risk is too close."""
    event_details = format_news_event(event)
    return "\n".join([
        "Signal:           NO TRADE",
        "Setup Confidence: N/A",
        f"Trade Duration:   Wait {within_minutes} minutes",
        "Risk Level:       High",
        f"Reason:           High-impact news is too close: {event_details}",
    ])
