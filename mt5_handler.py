"""MetaTrader 5 connectivity and market data utilities."""

from __future__ import annotations

import MetaTrader5 as mt5
import pandas as pd

import config
from utils import log_debug


def connect_mt5() -> bool:
    """Initialize MetaTrader 5 and optionally log in with configured credentials."""
    try:
        initialize_kwargs: dict[str, str] = {}
        if config.MT5_PATH:
            initialize_kwargs["path"] = config.MT5_PATH

        log_debug("Initializing MetaTrader 5 connection.")
        if not mt5.initialize(**initialize_kwargs):
            error = mt5.last_error()
            log_debug(
                f"MT5 initialize() failed: {error}\n"
                f"Make sure MetaTrader 5 terminal is running before starting the bot.\n"
                f"If MT5 is not available, ensure it's installed at: {config.MT5_PATH}"
            )
            return False

        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            log_debug("Logging in to the configured MT5 account.")
            if not mt5.login(
                config.MT5_LOGIN,
                password=config.MT5_PASSWORD,
                server=config.MT5_SERVER,
            ):
                log_debug(f"MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False
        else:
            log_debug("Using the currently opened MT5 terminal session.")

        account_info = mt5.account_info()
        if account_info:
            log_debug(f"Connected to MT5 account {account_info.login}.")
        else:
            log_debug("Connected to MT5, but account information is unavailable.")

        return True
    except Exception as exc:
        log_debug(f"Unexpected MT5 connection error: {exc}")
        return False


def get_market_data(symbol: str, timeframe: int, n_candles: int) -> pd.DataFrame:
    """Fetch candle data from MT5 and return a clean DataFrame."""
    try:
        log_debug(
            f"Requesting {n_candles} candles for {symbol} on timeframe {timeframe}."
        )

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise ValueError(f"Symbol '{symbol}' is not available in MT5.")

        if not symbol_info.visible and not mt5.symbol_select(symbol, True):
            raise ValueError(f"Unable to select symbol '{symbol}' in MT5.")

        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_candles)
        if rates is None or len(rates) == 0:
            raise ValueError(f"No market data returned for symbol '{symbol}'.")

        data = pd.DataFrame(rates)
        required_columns = ["time", "open", "high", "low", "close", "tick_volume"]
        missing_columns = [column for column in required_columns if column not in data]
        if missing_columns:
            raise ValueError(
                f"Market data is missing required columns: {', '.join(missing_columns)}."
            )

        data = data[required_columns].copy()
        data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
        data = data.dropna().reset_index(drop=True)

        if data.empty:
            raise ValueError("Market data became empty after cleaning.")

        log_debug(f"Received {len(data)} cleaned candles for {symbol}.")
        return data
    except Exception as exc:
        log_debug(f"Failed to fetch market data: {exc}")
        return pd.DataFrame(
            columns=["time", "open", "high", "low", "close", "tick_volume"]
        )


def shutdown_mt5() -> None:
    """Close the MetaTrader 5 connection cleanly."""
    try:
        mt5.shutdown()
        log_debug("MetaTrader 5 connection closed.")
    except Exception as exc:
        log_debug(f"Failed to close MetaTrader 5 cleanly: {exc}")
