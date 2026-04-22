"""Central configuration — defaults live here, secrets load from .env/env vars."""

from __future__ import annotations

import os
from pathlib import Path


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_local_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without overriding real env vars."""
    if not path.is_file():
        return

    try:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            if not name:
                continue

            os.environ.setdefault(name, _strip_env_quotes(value))
    except Exception:
        # Config loading should stay non-fatal; validate_config() handles missing values.
        return


_load_local_env_file(Path(__file__).with_name(".env"))


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = _env_str(name)
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# API keys & models
# ---------------------------------------------------------------------------
# Claude API (Anthropic) — replaced OpenAI
ANTHROPIC_API_KEY: str = _env_str("ANTHROPIC_API_KEY")

# Optional NewsAPI — RSS feeds are the primary news source (no key needed)
NEWS_API_KEY: str = _env_str("NEWS_API_KEY")

# FMP kept for compatibility — both endpoints require paid plan
NEWS_CALENDAR_ENDPOINTS: tuple[str, ...] = (
    "https://financialmodelingprep.com/stable/economic-calendar",
    "https://financialmodelingprep.com/api/v3/economic_calendar",
)

# ---------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------
SYMBOL:    str   = "XAUUSD"
LOT_SIZE:  float = 0.01
N_CANDLES: int   = 250

# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------
MT5_LOGIN:    int | None = _env_int("MT5_LOGIN")
MT5_PASSWORD: str        = _env_str("MT5_PASSWORD")
MT5_SERVER:   str        = _env_str("MT5_SERVER", "MetaQuotes-Demo")
MT5_PATH:     str        = _env_str("MT5_PATH", "C:/Program Files/MetaTrader 5/terminal64.exe")

# ---------------------------------------------------------------------------
# Intermarket Correlation
# ---------------------------------------------------------------------------
INTERMARKET_ENABLED:        bool = _env_str("INTERMARKET_ENABLED", "true").lower() == "true"
INTERMARKET_DXY_SYMBOL:     str  = _env_str("INTERMARKET_DXY_SYMBOL", "DXY")
INTERMARKET_SILVER_SYMBOL:  str  = _env_str("INTERMARKET_SILVER_SYMBOL", "XAGUSD")
INTERMARKET_YIELD_SYMBOL:   str  = _env_str("INTERMARKET_YIELD_SYMBOL", "US10Y")
INTERMARKET_SP500_SYMBOL:   str  = _env_str("INTERMARKET_SP500_SYMBOL", "US500")

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT:     int = 15
NEWS_LOOKAHEAD_DAYS: int = 1


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def validate_config() -> None:
    """Validate that required configuration is set before trading."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.strip() == "":
        raise ValueError(
            "ANTHROPIC_API_KEY is not configured. Set it in .env file or environment."
        )
    raw_mt5_login = _env_str("MT5_LOGIN")
    if raw_mt5_login and MT5_LOGIN is None:
        raise ValueError(
            "MT5_LOGIN must be a valid integer in .env file or environment."
        )
    # MT5 login is optional if using active terminal session
    # Uncomment below to enforce MT5 credentials:
    # if not MT5_LOGIN:
    #     raise ValueError(
    #         "MT5_LOGIN is not configured. Set it in .env file or environment."
    #     )
    # if not MT5_PASSWORD or MT5_PASSWORD.strip() == "":
    #     raise ValueError(
    #         "MT5_PASSWORD is not configured. Set it in .env file or environment."
    #     )
