"""Technical indicator calculations with session‑aware volume and anchored VWAP."""
from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from utils import log_debug

TREND_STRENGTH_ATR_THRESHOLD = 0.35
TREND_STRENGTH_PRICE_THRESHOLD = 0.0015
VOLUME_SPIKE_MULTIPLIER = 1.5
LOW_VOLUME_RATIO = 0.5      # Was 0.85; now uses session baseline

def _to_float(val):
    try:
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None

def _classify_trend(ema_20, ema_50, close, atr):
    if ema_20 is None or ema_50 is None:
        return "Neutral", "Neutral", None, None
    ema_strength = ema_20 - ema_50
    if abs(ema_strength) < 1e-9:
        return "Neutral", "Neutral", 0.0, 0.0
    normalized = None
    is_strong = False
    if atr not in (None, 0):
        normalized = abs(ema_strength) / atr
        is_strong = normalized >= TREND_STRENGTH_ATR_THRESHOLD
    elif close not in (None, 0):
        normalized = abs(ema_strength) / close
        is_strong = normalized >= TREND_STRENGTH_PRICE_THRESHOLD
    direction = "Bullish" if ema_strength > 0 else "Bearish"
    strength_label = "Strong" if is_strong else "Weak"
    return direction, f"{strength_label} {direction}", ema_strength, normalized

def _classify_rsi(rsi):
    if rsi is None:
        return "Unavailable"
    if 50 <= rsi <= 65:
        return "Bullish Continuation"
    if 35 <= rsi < 50:
        return "Bearish Continuation"
    if rsi > 65:
        return "Overbought"
    if rsi < 35:
        return "Oversold"
    return "Neutral"

def _classify_volatility(atr_val, atr_avg):
    if atr_val in (None, 0) or atr_avg in (None, 0):
        return "Normal", None
    ratio = atr_val / atr_avg
    return ("High" if atr_val > atr_avg else "Normal"), ratio

def _classify_volume(volume_ratio):
    if volume_ratio is None:
        return "Unknown"
    if volume_ratio >= 1.5:
        return "High"
    if volume_ratio < LOW_VOLUME_RATIO:
        return "Low"
    return "Normal"

def _compute_session_vwap(frame: pd.DataFrame) -> pd.Series:
    # Use pandas_ta if available
    vwap = ta.vwap(high=frame["high"], low=frame["low"], close=frame["close"], volume=frame["volume"])
    if vwap is not None and not vwap.dropna().empty:
        return vwap
    # Fallback: anchor to the latest date only (single session)
    latest_date = frame.index[-1].date()
    session_mask = frame.index.date == latest_date
    session = frame[session_mask].copy()
    if session.empty:
        session = frame.iloc[-50:].copy()
    typical = (session["high"] + session["low"] + session["close"]) / 3
    cum_vol = session["volume"].cumsum().replace(0, float("nan"))
    session_vwap = (typical * session["volume"]).cumsum() / cum_vol
    return session_vwap.reindex(frame.index)

def calculate_indicators(data: pd.DataFrame) -> dict:
    try:
        if data.empty:
            return {}
        frame = data.copy()
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        frame["volume"] = frame["tick_volume"].fillna(0)
        frame = frame.set_index("time")
        # Use a longer rolling window for volume baseline (96 periods = 24h on M15)
        frame["average_volume_96"] = frame["volume"].rolling(window=96, min_periods=48).mean()
        frame["ema_20"] = ta.ema(frame["close"], length=20)
        frame["ema_50"] = ta.ema(frame["close"], length=50)
        frame["rsi_14"] = ta.rsi(frame["close"], length=14)
        frame["atr_14"] = ta.atr(frame["high"], frame["low"], frame["close"], length=14)
        frame["vwap"] = _compute_session_vwap(frame)
        frame["average_volume_20"] = frame["volume"].rolling(window=20, min_periods=5).mean()
        frame["atr_average_20"] = frame["atr_14"].rolling(window=20, min_periods=5).mean()
        latest = frame.iloc[-1]
        # Compute volume ratio using 96‑period baseline (session aware)
        avg_vol_96 = _to_float(latest["average_volume_96"])
        latest_vol = _to_float(latest["volume"])
        vol_ratio = None
        if avg_vol_96 and avg_vol_96 > 100 and latest_vol:
            vol_ratio = min(5.0, latest_vol / avg_vol_96)
        return {
            "close": _to_float(latest["close"]),
            "ema_20": _to_float(latest["ema_20"]),
            "ema_50": _to_float(latest["ema_50"]),
            "ema_strength": _to_float(latest["ema_20"] - latest["ema_50"]) if latest["ema_20"] is not None else None,
            "trend_strength_ratio": _to_float(latest.get("trend_strength_ratio")),
            "indicator_bias": "Bullish" if _to_float(latest["ema_20"]) > _to_float(latest["ema_50"]) else "Bearish" if _to_float(latest["ema_20"]) is not None else "Neutral",
            "trend_classification": _classify_trend(_to_float(latest["ema_20"]), _to_float(latest["ema_50"]), _to_float(latest["close"]), _to_float(latest["atr_14"]))[1],
            "rsi_14": _to_float(latest["rsi_14"]),
            "rsi_signal": _classify_rsi(_to_float(latest["rsi_14"])),
            "atr_14": _to_float(latest["atr_14"]),
            "atr_average_20": _to_float(latest["atr_average_20"]),
            "atr_ratio": _to_float(latest["atr_14"] / latest["atr_average_20"]) if latest["atr_average_20"] not in (None,0) else None,
            "volatility_classification": _classify_volatility(_to_float(latest["atr_14"]), _to_float(latest["atr_average_20"]))[0],
            "vwap": _to_float(latest["vwap"]),
            "latest_volume": latest_vol,
            "average_volume_20": _to_float(latest["average_volume_20"]),
            "volume_ratio": vol_ratio,
            "volume_classification": _classify_volume(vol_ratio),
            "price_vs_vwap": "Above" if latest["close"] > latest["vwap"] else "Below" if latest["vwap"] else "Unknown",
        }
    except Exception as exc:
        log_debug(f"Indicator calculation failed: {exc}")
        return {}


def calculate_indicators_with_swings(data: pd.DataFrame) -> dict:
    """Calculate all indicators AND compute swing highs/lows for Fibonacci levels.
    
    Use this for M15 timeframe when Fibonacci retracement is needed.
    """
    base_indicators = calculate_indicators(data)
    if not base_indicators:
        return base_indicators
    
    try:
        if len(data) >= 20:
            # Find swing high/low using fractal pattern on last 50 candles
            lookback = min(50, len(data))
            recent = data.iloc[-lookback:]
            
            swing_high = recent['high'].max()
            swing_low = recent['low'].min()
            
            base_indicators["swing_high"] = _to_float(swing_high)
            base_indicators["swing_low"] = _to_float(swing_low)
            base_indicators["raw_data"] = data.copy()  # Store for CVD calculation
            
            log_debug(f"[SWINGS] High: {swing_high:.2f} | Low: {swing_low:.2f}")
        else:
            base_indicators["swing_high"] = None
            base_indicators["swing_low"] = None
            base_indicators["raw_data"] = None
    except Exception as exc:
        log_debug(f"Swing calculation error: {exc}")
        base_indicators["swing_high"] = None
        base_indicators["swing_low"] = None
    
    return base_indicators

def find_last_swing(data: pd.DataFrame) -> dict:
    """Return {'type': 'HIGH'/'LOW', 'price': float, 'index': int} using fractal pattern."""
    if len(data) < 5:
        return {"type": "NONE", "price": None, "index": None}
    high_idx = None
    low_idx = None
    for i in range(2, len(data)-2):
        if (data['high'].iloc[i] > data['high'].iloc[i-1] and
            data['high'].iloc[i] > data['high'].iloc[i-2] and
            data['high'].iloc[i] > data['high'].iloc[i+1] and
            data['high'].iloc[i] > data['high'].iloc[i+2]):
            high_idx = i
        if (data['low'].iloc[i] < data['low'].iloc[i-1] and
            data['low'].iloc[i] < data['low'].iloc[i-2] and
            data['low'].iloc[i] < data['low'].iloc[i+1] and
            data['low'].iloc[i] < data['low'].iloc[i+2]):
            low_idx = i
    if high_idx is None and low_idx is None:
        return {"type": "NONE", "price": None, "index": None}
    if high_idx > low_idx if low_idx is not None else True:
        return {"type": "HIGH", "price": data['high'].iloc[high_idx], "index": high_idx}
    else:
        return {"type": "LOW", "price": data['low'].iloc[low_idx], "index": low_idx}

def anchored_vwap_from_swing(data: pd.DataFrame, swing_type: str) -> pd.Series:
    swing = find_last_swing(data)
    if swing['type'] != swing_type or swing['index'] is None:
        return None
    anchor_data = data.iloc[swing['index']:].copy()
    typical = (anchor_data['high'] + anchor_data['low'] + anchor_data['close']) / 3
    cum_vol = anchor_data['volume'].cumsum()
    anchored = (typical * anchor_data['volume']).cumsum() / cum_vol
    return anchored.reindex(data.index, method='ffill')