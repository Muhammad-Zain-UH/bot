"""Key level utilities for pivot-point context."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _closed_bar_from_frame(frame: pd.DataFrame) -> dict[str, Any] | None:
    """Return the last fully closed candle from an MT5 DataFrame."""
    if frame is None or frame.empty or len(frame) < 2:
        return None

    row = frame.iloc[-2]
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    close = _to_float(row.get("close"))

    if high is None or low is None or close is None:
        return None

    return {
        "time": row.get("time"),
        "high": high,
        "low": low,
        "close": close,
    }


def calculate_classic_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Calculate classic floor-trader pivot levels."""
    pivot = (high + low + close) / 3.0
    price_range = high - low

    return {
        "pivot": pivot,
        "r1": (2 * pivot) - low,
        "s1": (2 * pivot) - high,
        "r2": pivot + price_range,
        "s2": pivot - price_range,
        "r3": high + 2 * (pivot - low),
        "s3": low - 2 * (high - pivot),
    }


def _nearest_level(
    levels: dict[str, float],
    current_price: float,
    *,
    side: str,
) -> dict[str, float | str] | None:
    if side == "support":
        candidates = [(name, price) for name, price in levels.items() if price <= current_price]
    else:
        candidates = [(name, price) for name, price in levels.items() if price >= current_price]

    if not candidates:
        return None

    name, price = min(candidates, key=lambda item: abs(item[1] - current_price))
    return {
        "name": name.upper(),
        "price": price,
        "distance": abs(price - current_price),
    }


def build_pivot_context(
    daily_data: pd.DataFrame,
    weekly_data: pd.DataFrame,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Build daily/weekly pivot context from the last closed D1/W1 bars."""
    context: dict[str, Any] = {
        "current_price": current_price,
        "daily": None,
        "weekly": None,
    }

    for label, frame in (("daily", daily_data), ("weekly", weekly_data)):
        bar = _closed_bar_from_frame(frame)
        if not bar:
            continue

        pivots = calculate_classic_pivots(bar["high"], bar["low"], bar["close"])
        level_context: dict[str, Any] = {
            "source_time": bar["time"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            **pivots,
        }

        if current_price is not None:
            pivot_levels = {name: value for name, value in pivots.items()}
            level_context["nearest_support"] = _nearest_level(
                pivot_levels, current_price, side="support"
            )
            level_context["nearest_resistance"] = _nearest_level(
                pivot_levels, current_price, side="resistance"
            )

        context[label] = level_context

    return context


def format_pivot_context_for_prompt(context: dict[str, Any]) -> str:
    """Format pivot context for compact inclusion in the AI prompt."""
    daily = context.get("daily")
    weekly = context.get("weekly")
    current_price = context.get("current_price")

    if not daily and not weekly:
        return "Key levels unavailable."

    lines: list[str] = []
    if current_price is not None:
        lines.append(f"  Reference Price: {current_price:.2f}")

    for label, data in (("Daily", daily), ("Weekly", weekly)):
        if not data:
            continue

        source_time = data.get("source_time")
        source_text = (
            source_time.strftime("%Y-%m-%d %H:%M UTC")
            if hasattr(source_time, "strftime")
            else "unknown"
        )

        lines.append(
            f"  {label} Pivots ({source_text}): "
            f"PP={data['pivot']:.2f} | S1={data['s1']:.2f} | S2={data['s2']:.2f} | "
            f"R1={data['r1']:.2f} | R2={data['r2']:.2f}"
        )

        support = data.get("nearest_support")
        resistance = data.get("nearest_resistance")
        if support:
            lines.append(
                f"    Nearest support: {support['name']} @ {support['price']:.2f} "
                f"({support['distance']:.2f} away)"
            )
        if resistance:
            lines.append(
                f"    Nearest resistance: {resistance['name']} @ {resistance['price']:.2f} "
                f"({resistance['distance']:.2f} away)"
            )

    return "\n".join(lines)
