"""MetaTrader 5 connectivity and market data utilities."""
from __future__ import annotations
import MetaTrader5 as mt5
import pandas as pd
import config
from utils import log_debug
from datetime import datetime, timedelta

def connect_mt5() -> bool:
    try:
        initialize_kwargs: dict[str, str] = {}
        if config.MT5_PATH:
            initialize_kwargs["path"] = config.MT5_PATH
        if not mt5.initialize(**initialize_kwargs):
            log_debug(f"MT5 init failed: {mt5.last_error()}")
            return False
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            if not mt5.login(config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
                log_debug(f"MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False
        account_info = mt5.account_info()
        if account_info:
            log_debug(f"Connected to MT5 account {account_info.login}.")
        return True
    except Exception as exc:
        log_debug(f"MT5 connection error: {exc}")
        return False

def get_market_data(symbol: str, timeframe: int, n_candles: int) -> pd.DataFrame:
    try:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise ValueError(f"Symbol '{symbol}' not available.")
        if not symbol_info.visible and not mt5.symbol_select(symbol, True):
            raise ValueError(f"Cannot select symbol '{symbol}'.")
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_candles)
        if rates is None or len(rates) == 0:
            raise ValueError(f"No market data for '{symbol}'.")
        data = pd.DataFrame(rates)
        required = ["time", "open", "high", "low", "close", "tick_volume"]
        data = data[required].copy()
        data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
        data = data.dropna().reset_index(drop=True)
        return data
    except Exception as exc:
        log_debug(f"Failed to fetch market data: {exc}")
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])

def shutdown_mt5() -> None:
    try:
        mt5.shutdown()
        log_debug("MT5 connection closed.")
    except Exception as exc:
        log_debug(f"MT5 shutdown error: {exc}")

def get_current_spread(symbol: str) -> float:
    """Return spread in points (e.g., 30 for 0.30 USD)."""
    info = mt5.symbol_info(symbol)
    if info:
        return (info.ask - info.bid) / info.point
    return 999.0

def compute_cvd_proxy(symbol: str, lookback_minutes: int = 5) -> float:
    """Approximate CVD using price‑direction tick classification. Weighted at 0.4."""
    from datetime import datetime, timedelta
    to_time = datetime.now()
    from_time = to_time - timedelta(minutes=lookback_minutes)
    ticks = mt5.copy_ticks_range(symbol, from_time, to_time, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return 0.0
    delta = 0
    prev_price = None
    for t in ticks:
        price = t['last']
        if prev_price is not None:
            if price > prev_price:
                delta += t['volume']
            elif price < prev_price:
                delta -= t['volume']
        prev_price = price
    # Normalize to range -100..100
    return max(-100.0, min(100.0, delta / 1000.0))