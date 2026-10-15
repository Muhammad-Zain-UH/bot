"""Shared harness for the Phase 2A.1 integration tests.

Builds the fixtures once and caches them: each dataset is ~25,000 M1 bars and
the start-price solver builds the path three times, so rebuilding per test would
dominate the suite's runtime.

Everything here wires together **real** Phase 2A components. The strategy is the
genuine ``main_production`` module; nothing about it is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from backtest.clock_patch import frozen_clock
from backtest.ledger import TradeLedger
from backtest.metrics import BacktestMetrics, compute_metrics
from backtest.replay_engine import DEFAULT_BAR_COUNTS, ReplayConfig, ReplayEngine, ReplayResult
from core.symbols import XAUUSD_2DIGIT
from core.types import Timeframe
from core.units import Pips
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import DEFAULT_SIMULATED_VOLUME, PaperBroker
from tests.fixtures.integration_market import (
    Resolution,
    expected_decision_time,
    make_long_setup_dataset,
    make_short_setup_dataset,
)

__all__ = [
    "SPEC",
    "SPREAD_PIPS",
    "analyse_at",
    "decision_instant",
    "frames_at",
    "long_dataset",
    "run_replay",
    "short_dataset",
]

SPEC = XAUUSD_2DIGIT
SPREAD_PIPS = 2.0

# Decisions start shortly before the setup so the replay stays fast; the
# resolution phase after it still runs, so positions can reach SL or TP.
LEAD_IN = timedelta(minutes=30)


@lru_cache(maxsize=8)
def long_dataset(resolution: str = Resolution.TARGET) -> HistoricalDataset:
    """Return the cached long-setup dataset for a resolution mode."""
    return make_long_setup_dataset(resolution=resolution)


@lru_cache(maxsize=8)
def short_dataset(resolution: str = Resolution.TARGET) -> HistoricalDataset:
    """Return the cached short-setup dataset for a resolution mode."""
    return make_short_setup_dataset(resolution=resolution)


def decision_instant() -> datetime:
    """Return the instant both fixtures are built to trigger at."""
    return expected_decision_time()


def frames_at(feed: ReplayFeed, moment: datetime) -> dict[Timeframe, pd.DataFrame]:
    """Return the bar frames visible at ``moment``, at production bar counts."""
    return {
        timeframe: feed.bars(timeframe, count, moment)
        for timeframe, count in DEFAULT_BAR_COUNTS.items()
    }


def analyse_at(
    dataset: HistoricalDataset,
    moment: datetime,
) -> tuple[dict[str, Any], dict[str, Any], dict[Timeframe, pd.DataFrame], float]:
    """Run the **real** strategy once at ``moment``.

    Calls ``main_production.detect_regime`` and ``main_production.analyze_entry``
    directly, with frames shaped exactly as ``mt5_handler.get_market_data``
    produces them. Nothing is mocked.

    Args:
        dataset: The fixture to read from.
        moment: Replay instant.

    Returns:
        ``(analysis, regime_info, frames, current_price)``.
    """
    import main_production

    feed = ReplayFeed(dataset, spread_pips=SPREAD_PIPS)
    frames = frames_at(feed, moment)
    price = feed.price_at(moment)
    with frozen_clock(moment):
        regime = main_production.detect_regime(
            frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
            current_spread=SPREAD_PIPS,
        )
        analysis = main_production.analyze_entry(
            frames[Timeframe.H4], frames[Timeframe.H1], frames[Timeframe.M15],
            frames[Timeframe.M5], frames[Timeframe.M1], frames[Timeframe.D1],
            current_price=price, regime_info=regime,
        )
    return analysis, regime, frames, price


def run_replay(
    dataset: HistoricalDataset,
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE,
    lead_in: timedelta = LEAD_IN,
) -> tuple[ReplayResult, TradeLedger, BacktestMetrics, PaperBroker]:
    """Run a full replay of the **real** strategy into the PaperBroker.

    Args:
        dataset: The fixture to replay.
        intrabar_policy: Ambiguous-bar policy for the broker.
        lead_in: How long before the setup decisions should begin.

    Returns:
        ``(result, ledger, metrics, broker)``.
    """
    feed = ReplayFeed(dataset, spread_pips=SPREAD_PIPS)
    broker = PaperBroker(
        SPEC,
        fill_model=FillModel(spread=Pips(SPREAD_PIPS)),
        intrabar_policy=intrabar_policy,
    )
    engine = ReplayEngine(
        feed, broker, SPEC,
        ReplayConfig(
            driving_timeframe=Timeframe.M5,
            start=decision_instant() - lead_in,
            volume=DEFAULT_SIMULATED_VOLUME,
        ),
        strategy=None,  # None => the real main_production module
    )
    result = engine.run()
    metrics = compute_metrics(
        result.ledger.trades, result.signals, len(result.ledger.rejections)
    )
    return result, result.ledger, metrics, broker
