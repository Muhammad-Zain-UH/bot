"""MetaTrader 5 connectivity and market data utilities."""
from __future__ import annotations
import MetaTrader5 as mt5
import pandas as pd
import config
from utils import log_debug
from datetime import datetime, timedelta


def _timeframe_minutes(timeframe: int) -> int:
    mapping = {
        mt5.TIMEFRAME_M1: 1,
        mt5.TIMEFRAME_M5: 5,
        mt5.TIMEFRAME_M15: 15,
        mt5.TIMEFRAME_H1: 60,
        mt5.TIMEFRAME_H4: 240,
        mt5.TIMEFRAME_D1: 1440,
        mt5.TIMEFRAME_W1: 10080,
    }
    return mapping.get(timeframe, 15)


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

def get_market_data(
    symbol: str,
    timeframe: int,
    n_candles: int,
    max_retries: int = 3,
    closed_only: bool = True,
) -> pd.DataFrame:
    """
    Fetch market data with comprehensive fallback logic.
    
    1. Primary: copy_rates_from_pos (last closed candle + N candles by default)
    2. Fallback: copy_rates_range (time range)
    3. Last resort: copy_rates_from_pos for genuinely tiny requests only
    
    The default excludes the forming candle. MT5's zero bar is still changing,
    so using it for H1/M15/M5 structure creates repainting scalping signals.
    """
    try:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise ValueError(f"Symbol '{symbol}' not available.")
        if not symbol_info.visible and not mt5.symbol_select(symbol, True):
            raise ValueError(f"Cannot select symbol '{symbol}'.")
        
        # PRIMARY: Try copy_rates_from_pos (most reliable)
        for attempt in range(max_retries):
            try:
                start_pos = 1 if closed_only else 0
                rates = mt5.copy_rates_from_pos(symbol, timeframe, start_pos, n_candles)
                if rates is not None and len(rates) >= n_candles:
                    data = pd.DataFrame(rates)
                    required = ["time", "open", "high", "low", "close", "tick_volume"]
                    data = data[required].copy()
                    data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
                    data = data.dropna().reset_index(drop=True)
                    if len(data) >= n_candles:
                        # Suppress verbose debug logging for cleaner terminal output
                        # log_debug(f"[DATA] {symbol} {n_candles} candles fetched (primary method)")
                        return data
            except Exception as e:
                # Suppress verbose retry failures - only log critical failures
                # log_debug(f"[DATA] Primary fetch attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.3)
        
        # FALLBACK 1: copy_rates_range (time-based)
        try:
            to_time = datetime.now()
            minutes = _timeframe_minutes(timeframe)
            from_time = to_time - timedelta(minutes=max(minutes * n_candles * 3, 60))
            
            rates = mt5.copy_rates_range(symbol, timeframe, from_time, to_time)
            if rates is not None and len(rates) > 0:
                data = pd.DataFrame(rates)
                required = ["time", "open", "high", "low", "close", "tick_volume"]
                data = data[required].copy()
                data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
                data = data.dropna().reset_index(drop=True)
                
                if closed_only and len(data) > 0:
                    data = data.iloc[:-1].reset_index(drop=True)
                
                if len(data) >= n_candles:
                    data = data.tail(n_candles).reset_index(drop=True)
                    # Suppress verbose fallback success logs
                    # log_debug(f"[DATA] {symbol} {len(data)} candles fetched (fallback: time range)")
                    return data
        except Exception as e:
            # Suppress verbose fallback failure logs
            # log_debug(f"[DATA] Fallback 1 (time range) failed: {e}")
            pass
        
        # FALLBACK 2: Last resort - just 2 candles from current position
        try:
            if n_candles > 2:
                log_debug(f"[DATA] Insufficient fallback data for {symbol}; refusing low-quality {n_candles}-candle request")
                return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])

            start_pos = 1 if closed_only else 0
            rates = mt5.copy_rates_from_pos(symbol, timeframe, start_pos, n_candles)
            if rates is not None and len(rates) >= n_candles:
                data = pd.DataFrame(rates)
                required = ["time", "open", "high", "low", "close", "tick_volume"]
                data = data[required].copy()
                data["time"] = pd.to_datetime(data["time"], unit="s", utc=True)
                data = data.dropna().reset_index(drop=True)
                # Suppress verbose emergency fallback logs
                # log_debug(f"[DATA] ⚠️ Emergency fallback: {symbol} only {len(data)} candles (low data quality)")
                return data
        except Exception as e:
            # Suppress verbose fallback failure logs
            # log_debug(f"[DATA] Fallback 2 (last resort) failed: {e}")
            pass
        
        # ALL METHODS FAILED - Return empty
        log_debug(f"[DATA] ❌ CRITICAL: Cannot fetch {symbol} data after all retries")
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])
        
    except Exception as exc:
        log_debug(f"[DATA] Market data error: {exc}")
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


def get_current_price(symbol: str, direction: str | None = None) -> float | None:
    """Return the executable-side price: ask for BUY, bid for SELL, mid otherwise."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    if direction == "BUY":
        return float(tick.ask)
    if direction == "SELL":
        return float(tick.bid)
    return float((tick.ask + tick.bid) / 2)


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
