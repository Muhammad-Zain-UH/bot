"""Technical indicator calculations for the trading assistant."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas_ta as ta

from utils import log_debug

TREND_STRENGTH_ATR_THRESHOLD = 0.35
TREND_STRENGTH_PRICE_THRESHOLD = 0.0015
VOLUME_SPIKE_MULTIPLIER = 1.5
LOW_VOLUME_RATIO_THRESHOLD = 0.85


def _to_float(value: Any) -> float | None:
    """Convert a value to float while preserving missing values as None."""
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _classify_trend(
    ema_20: float | None,
    ema_50: float | None,
    close_price: float | None,
    atr_value: float | None,
) -> tuple[str, str, float | None, float | None]:
    """Classify trend direction and strength from EMA spread."""
    if ema_20 is None or ema_50 is None:
        return "Neutral", "Neutral", None, None

    ema_strength = ema_20 - ema_50
    if abs(ema_strength) < 1e-9:
        return "Neutral", "Neutral", 0.0, 0.0

    normalized_strength: float | None = None
    is_strong = False

    if atr_value not in (None, 0):
        normalized_strength = abs(ema_strength) / atr_value
        is_strong = normalized_strength >= TREND_STRENGTH_ATR_THRESHOLD
    elif close_price not in (None, 0):
        normalized_strength = abs(ema_strength) / close_price
        is_strong = normalized_strength >= TREND_STRENGTH_PRICE_THRESHOLD

    direction = "Bullish" if ema_strength > 0 else "Bearish"
    strength_label = "Strong" if is_strong else "Weak"
    return direction, f"{strength_label} {direction}", ema_strength, normalized_strength


def _classify_rsi(rsi_value: float | None) -> str:
    """Classify RSI with a continuation-first trend-following bias."""
    if rsi_value is None:
        return "Unavailable"
    if 50 <= rsi_value <= 65:
        return "Bullish Continuation"
    if 35 <= rsi_value < 50:
        return "Bearish Continuation"
    if rsi_value > 65:
        return "Overbought"
    if rsi_value < 35:
        return "Oversold"
    return "Neutral"


def _classify_volatility(
    atr_value: float | None,
    atr_average: float | None,
) -> tuple[str, float | None]:
    """Compare current ATR with its recent average to detect volatility expansion."""
    if atr_value in (None, 0) or atr_average in (None, 0):
        return "Normal", None

    atr_ratio = atr_value / atr_average
    if atr_value > atr_average:
        return "High", atr_ratio
    return "Normal", atr_ratio


def _classify_volume(volume_ratio: float | None) -> str:
    """Classify volume so downstream logic can reward or penalise participation."""
    if volume_ratio is None:
        return "Unknown"
    # Fix: Clamp extreme ratios from data issues (ratio shouldn't exceed 5x or drop below 0.1x)
    safe_ratio = max(0.1, min(5.0, volume_ratio))
    if safe_ratio > VOLUME_SPIKE_MULTIPLIER:
        return "High"
    if safe_ratio < LOW_VOLUME_RATIO_THRESHOLD:
        return "Low"
    return "Normal"


def _build_empty_snapshot() -> dict[str, Any]:
    """Return a safe empty indicator structure when calculation fails."""
    return {
        "close": None,
        "ema_20": None,
        "ema_50": None,
        "ema_strength": None,
        "trend_strength_ratio": None,
        "indicator_bias": "Neutral",
        "trend_classification": "Neutral",
        "rsi_14": None,
        "rsi_signal": "Unavailable",
        "atr_14": None,
        "atr_average_20": None,
        "atr_ratio": None,
        "volatility_classification": "Normal",
        "vwap": None,
        "latest_volume": None,
        "average_volume_20": None,
        "volume_ratio": None,
        "volume_classification": "Unknown",
        "volume_spike": False,
        "price_vs_vwap": "Unknown",
    }


def _compute_session_vwap(frame: pd.DataFrame) -> pd.Series:
    """Compute VWAP anchored to the current trading session only.

    BUG FIX: the original fallback VWAP ran cumsum() across all 250 candles
    which spans multiple days/sessions, producing stale reference prices.
    We now anchor VWAP to the most recent calendar date so the reference
    price is always fresh and meaningful.
    """
    # Attempt pandas_ta session-aware VWAP first
    vwap_series = ta.vwap(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        volume=frame["volume"],
    )
    if vwap_series is not None and not vwap_series.dropna().empty:
        return vwap_series

    # Fallback: anchor to the latest date only (single-session cumsum)
    log_debug("pandas_ta VWAP unavailable — using single-session fallback VWAP.")
    latest_date = frame.index[-1].date()
    session_mask = frame.index.date == latest_date  # type: ignore[attr-defined]
    session = frame[session_mask].copy()

    if session.empty:
        # Nothing for today — fall back to last 50 candles at minimum
        session = frame.iloc[-50:].copy()

    typical_price = (session["high"] + session["low"] + session["close"]) / 3
    cum_vol = session["volume"].cumsum().replace(0, float("nan"))
    session_vwap = (typical_price * session["volume"]).cumsum() / cum_vol

    # Reindex back to the full frame (pre-session rows get NaN, that's correct)
    return session_vwap.reindex(frame.index)


def calculate_indicators(data: pd.DataFrame) -> dict[str, Any]:
    """Calculate the latest indicator readings from market data."""
    try:
        if data.empty:
            raise ValueError("Cannot calculate indicators from empty market data.")

        required_columns = {"time", "high", "low", "close", "tick_volume"}
        missing_columns = sorted(required_columns.difference(data.columns))
        if missing_columns:
            raise ValueError(
                f"Indicator calculation is missing columns: {', '.join(missing_columns)}."
            )

        log_debug(
            "Calculating EMA strength, trend classification, RSI, ATR, VWAP, and volume metrics."
        )
        frame = data.copy()
        frame["time"] = pd.to_datetime(frame["time"], utc=True)

        numeric_columns = ["high", "low", "close", "tick_volume"]
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=["high", "low", "close"]).copy()
        frame["volume"] = frame["tick_volume"].fillna(0)
        frame = frame.set_index("time")

        frame["ema_20"] = ta.ema(frame["close"], length=20)
        frame["ema_50"] = ta.ema(frame["close"], length=50)
        frame["rsi_14"] = ta.rsi(frame["close"], length=14)
        frame["atr_14"] = ta.atr(frame["high"], frame["low"], frame["close"], length=14)

        # BUG FIX: use session-anchored VWAP helper
        frame["vwap"] = _compute_session_vwap(frame)

        frame["average_volume_20"] = frame["volume"].rolling(window=20, min_periods=5).mean()
        frame["atr_average_20"] = frame["atr_14"].rolling(window=20, min_periods=5).mean()

        latest_row = frame.iloc[-1]

        close_price = _to_float(latest_row["close"])
        ema_20 = _to_float(latest_row["ema_20"])
        ema_50 = _to_float(latest_row["ema_50"])
        rsi_14 = _to_float(latest_row["rsi_14"])
        atr_14 = _to_float(latest_row["atr_14"])
        atr_average_20 = _to_float(latest_row["atr_average_20"])
        vwap = _to_float(latest_row["vwap"])
        latest_volume = _to_float(latest_row["volume"])
        average_volume = _to_float(latest_row["average_volume_20"])

        indicator_bias, trend_classification, ema_strength, trend_strength_ratio = (
            _classify_trend(
                ema_20=ema_20,
                ema_50=ema_50,
                close_price=close_price,
                atr_value=atr_14,
            )
        )
        rsi_signal = _classify_rsi(rsi_14)
        volatility_classification, atr_ratio = _classify_volatility(
            atr_value=atr_14,
            atr_average=atr_average_20,
        )

        volume_ratio = None
        if latest_volume is not None and average_volume not in (None, 0):
            # Fix: Only compute ratio if average_volume is reasonable (>100 ticks)
            # This prevents division artifacts from dead zones
            if average_volume > 100:
                volume_ratio = min(5.0, latest_volume / average_volume)  # Cap at 5x to avoid outliers
            else:
                volume_ratio = 1.0  # Assume normal if average is too low

        volume_spike = bool(
            volume_ratio is not None and volume_ratio > VOLUME_SPIKE_MULTIPLIER
        )
        volume_classification = _classify_volume(volume_ratio)

        if close_price is not None and vwap is not None:
            if close_price > vwap:
                price_vs_vwap = "Above"
            elif close_price < vwap:
                price_vs_vwap = "Below"
            else:
                price_vs_vwap = "At"
        else:
            price_vs_vwap = "Unknown"

        indicator_values = {
            "close": close_price,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_strength": ema_strength,
            "trend_strength_ratio": trend_strength_ratio,
            "indicator_bias": indicator_bias,
            "trend_classification": trend_classification,
            "rsi_14": rsi_14,
            "rsi_signal": rsi_signal,
            "atr_14": atr_14,
            "atr_average_20": atr_average_20,
            "atr_ratio": atr_ratio,
            "volatility_classification": volatility_classification,
            "vwap": vwap,
            "latest_volume": latest_volume,
            "average_volume_20": average_volume,
            "volume_ratio": volume_ratio,
            "volume_classification": volume_classification,
            "volume_spike": volume_spike,
            "price_vs_vwap": price_vs_vwap,
        }

        log_debug(f"Latest indicator snapshot: {indicator_values}")
        return indicator_values
    except Exception as exc:
        log_debug(f"Indicator calculation failed: {exc}")
        return _build_empty_snapshot()
