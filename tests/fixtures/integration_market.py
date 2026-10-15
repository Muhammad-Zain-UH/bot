"""Phase-scripted deterministic fixtures for real-strategy integration tests.

**Not market data.** These are constructed price paths whose only purpose is to
satisfy the *existing* L1-L8 conditions, so the real strategy can be driven
through the replay -> PaperBroker -> ledger chain. No number produced from them
says anything about XAUUSD or about whether the strategy makes money.

Why a scripted path rather than a random walk
---------------------------------------------
Phase 2A showed a random walk blocks at L1/L2 essentially always: the strategy
looks for a specific sequence -- trend, impulse, measured retracement, a sweep of
equal lows, then a reclaim -- and a walk produces that only by rare accident.
Rather than change a threshold to admit a walk (forbidden, and it would destroy
the value of the baseline), the fixture is built to the shape the strategy is
already written to find.

The shape, for a long setup
---------------------------
::

    [ warmup uptrend ]  establishes H4 EMA20>EMA50, H1 HH/HL, H1 ATR
            |
    [ impulse up     ]  leaves a clear M15 swing high (the CHoCH reference)
            |
    [ retracement    ]  pulls back into the 38-62% band L3 wants
            |
    [ basing         ]  three M15 candles with equal lows -> a liquidity pool
            |
    [ sweep+reclaim  ]  ONE M15 candle that wicks below those lows and closes
            |           back above the swing high: a sweep for L5, and a CHoCH
    [ trigger window ]  M5 rejection candle, then an M1 break, for L8
            |
    [ resolution     ]  post-decision bars so the position can reach SL or TP

Each element exists because a specific gate demands it:

======  ==============================================================
Gate    What it requires, and which phase supplies it
======  ==============================================================
L1      H4/H1 EMA separation -- the warmup trend
L2      H1 ATR >= 8.0 and HH/HL progression -- warmup volatility + trend
L3      a 38-62% M15 retracement -- impulse then retrace
L4      a pool below price scoring >= 70 (three equal lows) and one above
        scoring >= 60 (a round number within $2 of price, which is why the
        start price is solved -- see :func:`_solve_start_price`)
L5      a sweep: a wick >= $2.50 beyond the pool, closing back past it
L6      POI >= 60. The threshold drops from 70 to 60 once L5 confirms a
        sweep, which is the only reason the Fib POI's 68 suffices here.
L7      weighted confidence >= 70, helped by a weekday London session
L8      an M5 rejection candle plus an M1 break
======  ==============================================================

The one-bar offset that makes this possible
--------------------------------------------
L3 reads ``closed.iloc[-1]`` -- it drops an extra bar -- while L5 reads
``iloc[-1]``. So at the decision instant L3 sees the last basing candle (its low
at the equal-low level, a deep retracement) while L5 sees the sweep candle. A
single fixture satisfies both only because the whole sweep-and-reclaim fits
inside one M15 candle.

Short setups mirror every phase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.timeframes import resample_from_m1

__all__ = [
    "DEFAULT_WARMUP_BARS",
    "INTEGRATION_SEED",
    "INTEGRATION_START",
    "PhaseSpec",
    "Resolution",
    "build_m1_from_phases",
    "expected_decision_time",
    "make_long_setup_dataset",
    "make_short_setup_dataset",
]

UTC = timezone.utc
INTEGRATION_SEED = 20260917
INTEGRATION_START = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)  # a Monday

# Phase lengths in M1 bars. The M15 alignment depends on these exact values.
IMPULSE_BARS = 240   # 16 M15 candles
RETRACE_BARS = 90    # 6 M15 candles
BASE_BARS = 45       # 3 M15 candles -- the equal lows
RECLAIM_BARS = 15    # exactly ONE M15 candle -- the sweep and reclaim
TRIGGER_BARS = 10    # two M5 candles: rejection, then the break
SETUP_BARS = IMPULSE_BARS + RETRACE_BARS + BASE_BARS + RECLAIM_BARS + TRIGGER_BARS

DEFAULT_WARMUP_BARS = 24_510
"""M1 bars of warmup before the setup phases.

Chosen so every constraint lands at once, not by trial and error:

* a multiple of 15, so the sweep candle aligns to an M15 boundary
* ``warmup + 400`` minutes puts the decision instant at
  **2026-03-19 07:10 UTC, a Thursday in the London session**. A weekday matters
  because ``risk_manager.get_current_session`` returns ``"Closed"`` at weekends,
  costing -15 on the L7 confidence score.
* 103 H4 bars and 17 D1 bars, clearing the 100-H4 / 10-D1 minimums that
  ``get_market_data`` requires before it will return a frame at all
"""

ROUND_NUMBER_INCREMENT = 25.0
"""Spacing of the levels ``liquidity_engine.find_round_numbers`` emits."""

ROUND_NUMBER_OFFSET = 1.50
"""Distance from the adjacent round number at which the fixture finishes.

Inside the $2.00 window ``score_liquidity_pool`` rewards with a +25 proximity
bonus, lifting a round-number pool to 66 and clearing L4's minimum of 60 for a
take-profit pool. Without it the fixture ends at its own extreme, the only pool
beyond price is a distant round number scoring 41, and L4 blocks on ``TP 41/100``.
"""

SWEEP_DEPTH = 4.0
"""How far the sweep candle wicks beyond the equal lows, in price units.

``detect_sweep`` requires ``sweep_min <= depth <= sweep_max`` where
``sweep_min = max(2.5, m15_atr * 0.12)``. $4.00 clears the $2.50 floor with
margin while staying far below the $30 ceiling.
"""


class Resolution:
    """How the post-decision bars resolve an open position."""

    TARGET = "target"
    STOP = "stop"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class PhaseSpec:
    """One segment of a scripted price path.

    Attributes:
        name: Label, used in diagnostics.
        bars: Number of M1 bars in the segment.
        drift_per_bar: Price change added to every bar's close.
        noise: Standard deviation of per-bar random movement.
        wick: Scale of the random high/low extension beyond the body.
    """

    name: str
    bars: int
    drift_per_bar: float
    noise: float
    wick: float


def expected_decision_time(warmup_bars: int = DEFAULT_WARMUP_BARS) -> datetime:
    """Return the instant the setup is built to trigger at.

    Args:
        warmup_bars: Warmup length used to build the fixture.

    Returns:
        The decision instant, tz-aware UTC.
    """
    return INTEGRATION_START + timedelta(minutes=warmup_bars + SETUP_BARS)


def build_m1_from_phases(
    phases: list[PhaseSpec],
    start_price: float,
    start_time: datetime = INTEGRATION_START,
    seed: int = INTEGRATION_SEED,
) -> pd.DataFrame:
    """Build an M1 series by walking a list of phases.

    Each bar's high and low bracket its own open and close, so the result always
    satisfies the dataset validator. A fixture that failed validation would be
    testing the validator rather than the strategy.

    Args:
        phases: Segments to walk, in order.
        start_price: Opening price of the first bar.
        start_time: Timestamp of the first bar. Must be tz-aware.
        seed: RNG seed. Fixed input, fixed output.

    Returns:
        A frame with ``time, open, high, low, close, tick_volume``.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[float, float, float, float]] = []
    price = start_price

    for phase in phases:
        for _ in range(phase.bars):
            open_price = price
            close_price = open_price + phase.drift_per_bar + float(
                rng.normal(0.0, phase.noise)
            )
            high = max(open_price, close_price) + abs(float(rng.normal(0.0, phase.wick)))
            low = min(open_price, close_price) - abs(float(rng.normal(0.0, phase.wick)))
            rows.append((open_price, high, low, close_price))
            price = close_price

    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    frame.insert(0, "time", [start_time + timedelta(minutes=i) for i in range(len(rows))])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame["tick_volume"] = [120 + (i * 53) % 640 for i in range(len(rows))]
    return frame


def _set_bar(
    frame: pd.DataFrame,
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float | None = None,
) -> None:
    """Replace one M1 bar in place, keeping OHLC internally consistent.

    The values written are ordinary OHLC. Nothing here bypasses a strategy
    check -- it only arranges the price action the check is written to detect.

    Args:
        frame: The M1 frame to edit.
        index: Positional index of the bar.
        open_price: New open.
        high: New high; raised if needed to bracket the body.
        low: New low; lowered if needed to bracket the body.
        close: New close.
        volume: Optional tick volume.
    """
    body_top = max(open_price, close)
    body_bottom = min(open_price, close)
    frame.loc[index, "open"] = open_price
    frame.loc[index, "close"] = close
    frame.loc[index, "high"] = max(high, body_top)
    frame.loc[index, "low"] = min(low, body_bottom)
    if volume is not None:
        frame.loc[index, "tick_volume"] = volume



def _shape_basing_candle(
    frame: pd.DataFrame,
    group_start: int,
    pooled_low: float | None = None,
    pooled_high: float | None = None,
    floor: float | None = None,
    ceiling: float | None = None,
) -> None:
    """Shape one 15-minute basing candle.

    Two jobs, and the second is easy to overlook:

    1. Pin the pooled extreme (``pooled_low`` for a long setup,
       ``pooled_high`` for a short) so the three basing candles form an
       equal-level cluster that ``find_equal_levels`` scores as a liquidity pool.
    2. Clamp the **opposite** extreme with ``floor``/``ceiling``. Without this,
       random noise inside the basing range creates a fractal on that side, and
       ``pullback_detector._find_recent_fractal_swing`` anchors to it instead of
       to the impulse swing. The measured retracement then collapses -- observed
       on the short setup as ``retracement_ratio=0.071`` and
       ``"Swing too recent (2 bars)"``.

    Args:
        frame: The M1 frame to edit in place.
        group_start: Index of the candle's first M1 bar.
        pooled_low: Exact low to pin, for a long setup.
        pooled_high: Exact high to pin, for a short setup.
        floor: Minimum low for every bar in the candle.
        ceiling: Maximum high for every bar in the candle.
    """
    for offset in range(15):
        index = group_start + offset
        if floor is not None and float(frame.loc[index, "low"]) < floor:
            frame.loc[index, "low"] = floor
            for column in ("open", "close", "high"):
                if float(frame.loc[index, column]) < floor:
                    frame.loc[index, column] = floor
        if ceiling is not None and float(frame.loc[index, "high"]) > ceiling:
            frame.loc[index, "high"] = ceiling
            for column in ("open", "close", "low"):
                if float(frame.loc[index, column]) > ceiling:
                    frame.loc[index, column] = ceiling

    anchor = group_start + 7
    open_price = float(frame.loc[anchor, "open"])
    close_price = float(frame.loc[anchor, "close"])
    if pooled_low is not None:
        _set_bar(frame, anchor, open_price, float(frame.loc[anchor, "high"]),
                 pooled_low, close_price)
    if pooled_high is not None:
        _set_bar(frame, anchor, open_price, pooled_high,
                 float(frame.loc[anchor, "low"]), close_price)


def _assemble(m1: pd.DataFrame, symbol: str = "XAUUSD") -> HistoricalDataset:
    """Resample an M1 series into a full multi-timeframe dataset."""
    frames = {Timeframe.M1: m1}
    for timeframe in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1):
        frames[timeframe] = resample_from_m1(m1, timeframe)
    dataset = HistoricalDataset(symbol=symbol, frames=frames)
    dataset.derived.update(
        {Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1}
    )
    return dataset


def _solve_start_price(
    build: Callable[[float], pd.DataFrame],
    target_close: float,
    measure_index: int,
    nominal_start: float = 2000.0,
) -> float:
    """Return the start price that puts ``measure_index``'s close at ``target_close``.

    Drift, noise and the shaped candles are all additive and independent of price
    level, so shifting the start price shifts the whole path by a constant.
    Building once to measure the realised move, then offsetting, is exact rather
    than iterative.

    Args:
        build: Builds the full M1 series, including all shaping, from a price.
        target_close: Desired close at ``measure_index``.
        measure_index: Positional index of the bar to pin.
        nominal_start: Any starting price, used only to measure the move.

    Returns:
        The start price to use.
    """
    probe = build(nominal_start)
    realised = float(probe["close"].iloc[measure_index]) - nominal_start
    return target_close - realised


def _round_number_below(price: float, increment: float = ROUND_NUMBER_INCREMENT) -> float:
    """Return the largest ``increment`` multiple at or below ``price``."""
    return float(int(price / increment) * increment)


# ---------------------------------------------------------------------------
# Long setup
# ---------------------------------------------------------------------------

def _long_phases(
    warmup_bars: int, volatility: float, resolution_bars: int, resolution_drift: float
) -> list[PhaseSpec]:
    """Phase script for a long setup."""
    return [
        PhaseSpec("warmup_uptrend", warmup_bars, 0.030, volatility, volatility * 0.55),
        PhaseSpec("impulse_up", IMPULSE_BARS, 0.240, volatility * 0.9, volatility * 0.5),
        PhaseSpec("retrace", RETRACE_BARS, -0.380, volatility * 0.7, volatility * 0.45),
        PhaseSpec("basing", BASE_BARS, -0.040, volatility * 0.30, volatility * 0.25),
        PhaseSpec("reclaim", RECLAIM_BARS, 0.000, volatility * 0.10, volatility * 0.10),
        PhaseSpec("trigger_window", TRIGGER_BARS, 0.000, volatility * 0.10, volatility * 0.10),
        PhaseSpec(
            "resolution", resolution_bars, resolution_drift,
            volatility * 0.5, volatility * 0.35,
        ),
    ]


def _shape_long_setup(m1: pd.DataFrame, warmup_bars: int, volatility: float) -> None:
    """Carve the equal lows, the sweep candle and the entry trigger.

    Args:
        m1: The M1 frame to edit in place.
        warmup_bars: Warmup length, used to locate the phases.
        volatility: Scale for the constructed candles.
    """
    base_start = warmup_bars + IMPULSE_BARS + RETRACE_BARS
    reclaim_start = base_start + BASE_BARS
    trigger_start = reclaim_start + RECLAIM_BARS

    # --- three M15 candles with equal lows -> a liquidity pool for L4 and L5 ---
    # The lows land within $0.80 of each other, inside find_equal_levels' $1.50
    # tolerance, giving a 3-touch cluster: 15 base + 45 touches + 10 recency = 70.
    pool_level = float(m1.loc[base_start, "open"]) - 1.0
    # Anchor the ceilings to the candle immediately BEFORE basing, so they are
    # guaranteed to bind. Deriving them from the basing open left them below the
    # natural highs, making the clamp a silent no-op.
    previous_high = float(m1.loc[base_start - 15:base_start - 1, "high"].max())
    for group in range(BASE_BARS // 15):
        _shape_basing_candle(
            m1,
            group_start=base_start + group * 15,
            pooled_low=pool_level + group * 0.40,
            # Highs step DOWN across the three candles and stay below the prior
            # candle's high, so the most recent fractal HIGH remains the impulse
            # swing high rather than a basing high.
            ceiling=previous_high - 0.20 - group * 1.20,
        )

    # --- one M15 candle: wick below the pool, then close above the swing high ---
    # Its low becomes sweep_wick_low, which _select_stop_anchor uses for the stop.
    swing_high = float(m1.loc[warmup_bars: warmup_bars + IMPULSE_BARS, "high"].max())
    reclaim_close = swing_high + volatility * 3.0
    sweep_low = pool_level - SWEEP_DEPTH

    open_price = float(m1.loc[reclaim_start, "open"])
    _set_bar(m1, reclaim_start, open_price, open_price + 0.2, sweep_low + 0.6, sweep_low + 1.0)
    _set_bar(m1, reclaim_start + 1, sweep_low + 1.0, sweep_low + 1.2, sweep_low, sweep_low + 0.4)
    _set_bar(m1, reclaim_start + 2, sweep_low + 0.4, sweep_low + 2.0, sweep_low + 0.2, sweep_low + 1.8)

    span = reclaim_close - (sweep_low + 1.8)
    step = span / 12.0
    price = sweep_low + 1.8
    for offset in range(3, RECLAIM_BARS):
        nxt = price + step
        _set_bar(m1, reclaim_start + offset, price, nxt + abs(step) * 0.15,
                 price - abs(step) * 0.10, nxt, volume=760.0)
        price = nxt

    # --- trigger window: an M5 rejection candle, then the M1 break ---
    base = float(m1.loc[trigger_start, "open"])
    depth = volatility * 5.0
    _set_bar(m1, trigger_start + 0, base, base + 0.1, base - depth * 0.55, base - depth * 0.50)
    _set_bar(m1, trigger_start + 1, base - depth * 0.50, base - depth * 0.40, base - depth, base - depth * 0.90)
    _set_bar(m1, trigger_start + 2, base - depth * 0.90, base - depth * 0.30, base - depth * 0.95, base - depth * 0.35)
    _set_bar(m1, trigger_start + 3, base - depth * 0.35, base + 0.30, base - depth * 0.40, base + 0.20)
    _set_bar(m1, trigger_start + 4, base + 0.20, base + 0.80, base + 0.10, base + 0.70)

    step = volatility * 0.45
    price = base + 0.70
    for offset in range(5, TRIGGER_BARS - 1):
        nxt = price + step
        _set_bar(m1, trigger_start + offset, price, nxt + step * 0.2, price - step * 0.15, nxt)
        price = nxt

    last = trigger_start + TRIGGER_BARS - 1
    prior_high = float(m1.loc[last - 5:last - 1, "high"].max())
    breakout_close = prior_high + volatility * 1.6
    _set_bar(m1, last, price, breakout_close + volatility * 0.12,
             price - volatility * 0.10, breakout_close, volume=900.0)


def make_long_setup_dataset(
    warmup_bars: int = DEFAULT_WARMUP_BARS,
    volatility: float = 1.5,
    resolution: str = Resolution.TARGET,
    resolution_bars: int = 900,
    seed: int = INTEGRATION_SEED,
    start_price: float = 2000.0,
) -> HistoricalDataset:
    """Build a dataset shaped to satisfy the existing long-side L1-L8 conditions.

    Args:
        warmup_bars: M1 bars of trend before the setup. Must be a multiple of 15
            and long enough for 100 H4 bars. See :data:`DEFAULT_WARMUP_BARS`.
        volatility: Per-bar noise scale, which sets M5 and H1 ATR and therefore
            which regime the strategy selects.
        resolution: How the post-decision bars behave -- ``Resolution.TARGET``
            rallies toward the take profit, ``Resolution.STOP`` declines toward
            the stop, ``Resolution.NEITHER`` drifts sideways.
        resolution_bars: How many M1 bars follow the decision.
        seed: RNG seed.
        start_price: Nominal price, refined by the start-price solver.

    Returns:
        A validated multi-timeframe dataset.
    """
    drift = {
        Resolution.TARGET: 0.30,
        Resolution.STOP: -0.30,
        Resolution.NEITHER: 0.0,
    }[resolution]
    phases = _long_phases(warmup_bars, volatility, resolution_bars, drift)
    decision_index = warmup_bars + SETUP_BARS - 1

    def build(from_price: float) -> pd.DataFrame:
        frame = build_m1_from_phases(phases, start_price=from_price, seed=seed)
        _shape_long_setup(frame, warmup_bars, volatility)
        return frame

    natural_close = float(build(start_price)["close"].iloc[decision_index])
    target_close = (
        _round_number_below(natural_close) + ROUND_NUMBER_INCREMENT - ROUND_NUMBER_OFFSET
    )
    return _assemble(build(_solve_start_price(build, target_close, decision_index)))


# ---------------------------------------------------------------------------
# Short setup -- the mirror of the long
# ---------------------------------------------------------------------------

def _short_phases(
    warmup_bars: int, volatility: float, resolution_bars: int, resolution_drift: float
) -> list[PhaseSpec]:
    """Phase script for a short setup."""
    return [
        PhaseSpec("warmup_downtrend", warmup_bars, -0.030, volatility, volatility * 0.55),
        PhaseSpec("impulse_down", IMPULSE_BARS, -0.240, volatility * 0.9, volatility * 0.5),
        PhaseSpec("retrace", RETRACE_BARS, 0.380, volatility * 0.7, volatility * 0.45),
        PhaseSpec("basing", BASE_BARS, 0.040, volatility * 0.30, volatility * 0.25),
        PhaseSpec("reclaim", RECLAIM_BARS, 0.000, volatility * 0.10, volatility * 0.10),
        PhaseSpec("trigger_window", TRIGGER_BARS, 0.000, volatility * 0.10, volatility * 0.10),
        PhaseSpec(
            "resolution", resolution_bars, resolution_drift,
            volatility * 0.5, volatility * 0.35,
        ),
    ]


def _shape_short_setup(m1: pd.DataFrame, warmup_bars: int, volatility: float) -> None:
    """Mirror of :func:`_shape_long_setup` for the short side."""
    base_start = warmup_bars + IMPULSE_BARS + RETRACE_BARS
    reclaim_start = base_start + BASE_BARS
    trigger_start = reclaim_start + RECLAIM_BARS

    pool_level = float(m1.loc[base_start, "open"]) + 1.0
    # Anchor the floors to the candle immediately BEFORE basing, so they are
    # guaranteed to bind. Deriving them from the basing open left them below the
    # natural lows, so the clamp did nothing and a fractal low formed inside the
    # basing range -- which is what produced retracement_ratio=0.071.
    previous_low = float(m1.loc[base_start - 15:base_start - 1, "low"].min())
    for group in range(BASE_BARS // 15):
        _shape_basing_candle(
            m1,
            group_start=base_start + group * 15,
            pooled_high=pool_level - group * 0.40,
            # Lows step UP across the three candles and stay above the prior
            # candle's low, so the most recent fractal LOW remains the impulse
            # swing low rather than a basing low.
            floor=previous_low + 0.20 + group * 1.20,
        )

    swing_low = float(m1.loc[warmup_bars: warmup_bars + IMPULSE_BARS, "low"].min())
    reclaim_close = swing_low - volatility * 3.0
    sweep_high = pool_level + SWEEP_DEPTH

    open_price = float(m1.loc[reclaim_start, "open"])
    _set_bar(m1, reclaim_start, open_price, sweep_high - 0.6, open_price - 0.2, sweep_high - 1.0)
    _set_bar(m1, reclaim_start + 1, sweep_high - 1.0, sweep_high, sweep_high - 1.2, sweep_high - 0.4)
    _set_bar(m1, reclaim_start + 2, sweep_high - 0.4, sweep_high - 0.2, sweep_high - 2.0, sweep_high - 1.8)

    span = (sweep_high - 1.8) - reclaim_close
    step = span / 12.0
    price = sweep_high - 1.8
    for offset in range(3, RECLAIM_BARS):
        nxt = price - step
        _set_bar(m1, reclaim_start + offset, price, price + abs(step) * 0.10,
                 nxt - abs(step) * 0.15, nxt, volume=760.0)
        price = nxt

    base = float(m1.loc[trigger_start, "open"])
    height = volatility * 5.0
    _set_bar(m1, trigger_start + 0, base, base + height * 0.55, base - 0.1, base + height * 0.50)
    _set_bar(m1, trigger_start + 1, base + height * 0.50, base + height, base + height * 0.40, base + height * 0.90)
    _set_bar(m1, trigger_start + 2, base + height * 0.90, base + height * 0.95, base + height * 0.30, base + height * 0.35)
    _set_bar(m1, trigger_start + 3, base + height * 0.35, base + height * 0.40, base - 0.30, base - 0.20)
    _set_bar(m1, trigger_start + 4, base - 0.20, base - 0.10, base - 0.80, base - 0.70)

    step = volatility * 0.45
    price = base - 0.70
    for offset in range(5, TRIGGER_BARS - 1):
        nxt = price - step
        _set_bar(m1, trigger_start + offset, price, price + step * 0.15, nxt - step * 0.2, nxt)
        price = nxt

    last = trigger_start + TRIGGER_BARS - 1
    prior_low = float(m1.loc[last - 5:last - 1, "low"].min())
    breakdown_close = prior_low - volatility * 1.6
    _set_bar(m1, last, price, price + volatility * 0.10,
             breakdown_close - volatility * 0.12, breakdown_close, volume=900.0)


def make_short_setup_dataset(
    warmup_bars: int = DEFAULT_WARMUP_BARS,
    volatility: float = 1.5,
    resolution: str = Resolution.TARGET,
    resolution_bars: int = 900,
    seed: int = INTEGRATION_SEED,
    start_price: float = 3200.0,
) -> HistoricalDataset:
    """Build a dataset shaped to satisfy the existing short-side L1-L8 conditions.

    Args:
        warmup_bars: M1 bars of trend before the setup.
        volatility: Per-bar noise scale.
        resolution: How the post-decision bars behave. For a short,
            ``Resolution.TARGET`` declines toward the take profit.
        resolution_bars: How many M1 bars follow the decision.
        seed: RNG seed.
        start_price: Nominal price, refined by the start-price solver. Higher
            than the long fixture so the downtrend stays well clear of zero.

    Returns:
        A validated multi-timeframe dataset.
    """
    drift = {
        Resolution.TARGET: -0.30,
        Resolution.STOP: 0.30,
        Resolution.NEITHER: 0.0,
    }[resolution]
    phases = _short_phases(warmup_bars, volatility, resolution_bars, drift)
    decision_index = warmup_bars + SETUP_BARS - 1

    def build(from_price: float) -> pd.DataFrame:
        frame = build_m1_from_phases(phases, start_price=from_price, seed=seed)
        _shape_short_setup(frame, warmup_bars, volatility)
        return frame

    natural_close = float(build(start_price)["close"].iloc[decision_index])
    target_close = _round_number_below(natural_close) + ROUND_NUMBER_OFFSET
    return _assemble(build(_solve_start_price(build, target_close, decision_index)))
