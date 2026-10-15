"""Deterministic synthetic market fixtures.

**These are not market data and must never be reported as a trading baseline.**
They exist to prove the replay machinery is correct: ordering, availability,
synchronisation, fills, ledger arithmetic, leakage and determinism. A real
baseline requires real XAUUSD history, which this environment does not yet have.

Everything is generated from a fixed seed, so a failure reproduces exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.timeframes import resample_from_m1

__all__ = [
    "SYNTHETIC_SEED",
    "SYNTHETIC_START",
    "make_m1_series",
    "make_synthetic_dataset",
    "make_trending_m1",
]

UTC = timezone.utc
SYNTHETIC_SEED = 20260916
SYNTHETIC_START = datetime(2026, 5, 4, 0, 0, tzinfo=UTC)  # a Monday


def make_m1_series(
    bars: int = 20_000,
    start: datetime = SYNTHETIC_START,
    base_price: float = 2400.0,
    step: float = 0.35,
    seed: int = SYNTHETIC_SEED,
    drift_per_bar: float = 0.0,
) -> pd.DataFrame:
    """Generate a deterministic synthetic M1 series.

    A random walk with a configurable drift. Each bar's high/low bracket its own
    open and close, so the result always satisfies the dataset validator -- a
    fixture that failed validation would be testing the validator, not the
    replay.

    Args:
        bars: Number of M1 bars.
        start: Timestamp of the first bar, tz-aware.
        base_price: Starting price.
        step: Standard deviation of the per-bar close change.
        seed: RNG seed. Fixed input, fixed output.
        drift_per_bar: Constant added to each step, to induce a trend.

    Returns:
        A frame with ``time, open, high, low, close, tick_volume``.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[float, float, float, float]] = []
    price = base_price
    for _ in range(bars):
        open_price = price
        close_price = open_price + drift_per_bar + float(rng.normal(0.0, step))
        wick_up = abs(float(rng.normal(0.0, step * 0.6)))
        wick_down = abs(float(rng.normal(0.0, step * 0.6)))
        high = max(open_price, close_price) + wick_up
        low = min(open_price, close_price) - wick_down
        rows.append((open_price, high, low, close_price))
        price = close_price

    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    frame.insert(0, "time", [start + timedelta(minutes=i) for i in range(bars)])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    # Deterministic, non-constant volume so volume-sensitive layers see variation.
    frame["tick_volume"] = [50 + (i * 37) % 400 for i in range(bars)]
    return frame


def make_trending_m1(
    bars: int = 20_000,
    seed: int = SYNTHETIC_SEED,
    leg_bars: int = 2_000,
    leg_drift: float = 0.06,
    base_price: float = 2400.0,
    volatility_scale: float = 1.0,
) -> pd.DataFrame:
    """Generate M1 data with alternating trend legs.

    A pure random walk rarely produces the impulse-then-retrace shape the
    strategy's pullback and sweep layers look for, so most decisions would block
    at L1 or L3 and the deeper machinery would go untested. Alternating drift
    legs exercise more of the pipeline.

    This shapes the data to exercise code paths -- it is **not** tuned to make
    the strategy perform well, and no result from it is a performance statement.

    Args:
        bars: Total M1 bars.
        seed: RNG seed.
        leg_bars: Bars per directional leg.
        leg_drift: Drift magnitude within a leg.
        base_price: Starting price level.
        volatility_scale: Multiplier on per-bar movement. Scaling this together
            with ``base_price`` keeps *relative* volatility constant while
            changing the absolute dollar figures -- which is how the
            price-level dependence of the strategy's absolute-USD thresholds
            (PHASE_2_ISSUES G2/U10) can be demonstrated as a controlled
            comparison rather than asserted.

    Returns:
        A frame with ``time, open, high, low, close, tick_volume``.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[float, float, float, float]] = []
    price = base_price
    for index in range(bars):
        leg = index // leg_bars
        drift = (leg_drift if leg % 2 == 0 else -leg_drift) * volatility_scale
        open_price = price
        close_price = open_price + drift + float(rng.normal(0.0, 0.30 * volatility_scale))
        high = max(open_price, close_price) + abs(
            float(rng.normal(0.0, 0.18 * volatility_scale))
        )
        low = min(open_price, close_price) - abs(
            float(rng.normal(0.0, 0.18 * volatility_scale))
        )
        rows.append((open_price, high, low, close_price))
        price = close_price

    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    frame.insert(0, "time", [SYNTHETIC_START + timedelta(minutes=i) for i in range(bars)])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame["tick_volume"] = [50 + (i * 37) % 400 for i in range(bars)]
    return frame


def make_synthetic_dataset(
    bars: int = 20_000,
    symbol: str = "XAUUSD",
    trending: bool = True,
    seed: int = SYNTHETIC_SEED,
    base_price: float = 2400.0,
    volatility_scale: float = 1.0,
) -> HistoricalDataset:
    """Build a full multi-timeframe synthetic dataset.

    Higher timeframes are resampled from the M1 series, so they are internally
    consistent by construction -- an H1 bar's high really is the max of its
    sixty M1 highs. That property matters: inconsistent timeframes would make a
    leakage test fail for the wrong reason.

    Args:
        bars: Number of M1 bars to generate.
        symbol: Symbol name to tag the dataset with.
        trending: Use alternating trend legs rather than a pure random walk.
        seed: RNG seed.
        base_price: Starting price level.
        volatility_scale: Multiplier on per-bar movement. Scale it alongside
            ``base_price`` to hold *relative* volatility constant while varying
            the absolute dollar figures.

    Returns:
        A validated :class:`~data.dataset.HistoricalDataset` with M1, M5, M15,
        H1, H4 and D1.
    """
    m1 = (
        make_trending_m1(
            bars, seed=seed, base_price=base_price, volatility_scale=volatility_scale
        )
        if trending
        else make_m1_series(
            bars, seed=seed, base_price=base_price, step=0.35 * volatility_scale
        )
    )
    frames = {Timeframe.M1: m1}
    for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
        frames[timeframe] = resample_from_m1(m1, timeframe)
    dataset = HistoricalDataset(symbol=symbol, frames=frames)
    dataset.derived.update(
        {Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1}
    )
    return dataset
