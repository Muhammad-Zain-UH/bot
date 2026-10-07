"""Checks that run against the exported real XAUUSD history.

These skip when ``data/raw/`` is absent, which is the normal case: the raw
export is gitignored, so a fresh clone has no broker data to test against.
Re-export with ``tools.export_mt5_history`` to enable them.

Two things are established here, and neither can be established on synthetic
fixtures.

**Real data does not leak.** For decision instants spread across the dataset,
every bar at or after the instant is shifted by a large amount and the same
decision is re-run. The strategy's answer must be byte-identical. A synthetic
fixture can hide look-ahead that real, noisy data exposes, because a fixture's
future is often a smooth continuation of its past.

**The export is native, not resampled.** A baseline over re-cut candles is a
baseline of synthetic data wearing a broker's name.

One trap is worth stating, because it already produced a vacuous pass once. The
strategy prints box-drawing characters. ``open(os.devnull, "w")`` on Windows
opens as cp1252, which raises ``UnicodeEncodeError`` on the first banner -- and
``analyze_entry``'s blanket ``except`` converts that into a ``layer_failed ==
"ERROR"`` result. Both the baseline and the mutated run then "agree", on an
error, and the comparison establishes nothing. Hence ``encoding="utf-8"``
below, and hence an ``ERROR`` decision is raised rather than compared.
"""

from __future__ import annotations

import contextlib
import json
import os
import unittest
from datetime import timedelta
from pathlib import Path

import pandas as pd

from backtest.baseline import spec_from_broker_metadata
from backtest.clock_patch import frozen_clock
from backtest.replay_engine import DEFAULT_BAR_COUNTS
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "data" / "raw"
METADATA = RAW / "broker_metadata.json"

# Decision indices spread across the usable range, past the warm-up.
SAMPLE_INDICES = (5_000, 8_000, 11_000, 14_000, 17_000, 19_500)
FUTURE_SHIFT = 500.0
SPREAD_PIPS = 2.0


def _available() -> bool:
    """Return whether a broker export is present to test against."""
    return METADATA.exists() and any(RAW.glob("XAUUSD_*.csv"))


@unittest.skipUnless(_available(), "no exported broker data in data/raw/")
class RealDataTestCase(unittest.TestCase):
    """Shared dataset loading for the real-data checks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        cls.dataset = HistoricalDataset.from_directory(str(RAW), "XAUUSD")
        cls.spec = spec_from_broker_metadata(cls.metadata, pip_size=0.10)


class TestExportIsNative(RealDataTestCase):
    """The baseline must run on broker candles, not re-cut ones."""

    def test_no_timeframe_was_resampled(self) -> None:
        self.assertEqual(
            [tf.value for tf in self.dataset.derived], [],
            "a derived timeframe means synthetic candles entered the baseline",
        )

    def test_server_offset_was_recorded(self) -> None:
        """Without it, nothing downstream can know the stamps were shifted."""
        self.assertIn("server_utc_offset_hours", self.metadata)
        self.assertIsInstance(self.metadata["server_utc_offset_hours"], (int, float))

    def test_higher_timeframes_are_not_utc_aligned(self) -> None:
        """A UTC-aligned D1 here would mean the candles had been re-cut.

        The broker runs at a non-zero UTC offset, so its native daily candle
        cannot open at 00:00 UTC. If it does, something resampled it.
        """
        offset = float(self.metadata["server_utc_offset_hours"])
        if offset == 0:
            self.skipTest("broker runs at UTC; native and UTC-aligned coincide")
        daily = self.dataset.frames.get(Timeframe.D1)
        if daily is None or daily.empty:
            self.skipTest("no D1 data exported")
        hours = set(pd.to_datetime(daily["time"]).dt.hour.unique())
        self.assertNotEqual(hours, {0}, "D1 opens at 00:00 UTC -- candles were re-cut")

    def test_bar_times_are_timezone_aware(self) -> None:
        for timeframe, frame in self.dataset.frames.items():
            with self.subTest(timeframe=timeframe.value):
                self.assertIsNotNone(pd.to_datetime(frame["time"]).dt.tz)


class TestRealDataHasNoLookAhead(RealDataTestCase):
    """Mutating the future must not change a past decision."""

    def _mutated(self, cutoff) -> HistoricalDataset:
        """Return the dataset with every bar at or after ``cutoff`` shifted."""
        frames = {}
        for timeframe, frame in self.dataset.frames.items():
            copy = frame.copy(deep=True)
            tail = copy["time"] >= pd.Timestamp(cutoff)
            for column in ("open", "high", "low", "close"):
                copy.loc[tail, column] = copy.loc[tail, column] + FUTURE_SHIFT
            frames[timeframe] = copy
        return HistoricalDataset(symbol=self.dataset.symbol, frames=frames)

    def _decide(self, dataset: HistoricalDataset, moment):
        """Run one real strategy decision, or return None if still warming up."""
        import main_production as mp

        feed = ReplayFeed(dataset, spread_pips=SPREAD_PIPS)
        frames = {tf: feed.bars(tf, n, moment) for tf, n in DEFAULT_BAR_COUNTS.items()}
        if any(len(frame) == 0 for frame in frames.values()):
            return None
        price = feed.price_at(moment)

        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), frozen_clock(moment):
                regime = mp.detect_regime(
                    frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
                    current_spread=SPREAD_PIPS,
                )
                analysis = mp.analyze_entry(
                    frames[Timeframe.H4], frames[Timeframe.H1], frames[Timeframe.M15],
                    frames[Timeframe.M5], frames[Timeframe.M1], frames[Timeframe.D1],
                    current_price=price, regime_info=regime,
                )

        if analysis.get("layer_failed") == "ERROR":
            raise RuntimeError(
                "strategy raised during decision at "
                f"{moment}: {analysis.get('fail_reason')}"
            )
        return {
            "regime": regime.get("regime"),
            "signal": analysis.get("signal_type"),
            "blocked": analysis.get("layer_failed"),
            "passed": list(analysis.get("layers_passed", [])),
            "reason": analysis.get("fail_reason"),
            "entry": analysis.get("entry_signal"),
            "l7": (analysis.get("layer_7") or {}).get("score"),
            "l8": analysis.get("layer_8"),
            "price": price,
        }

    def _sample_times(self):
        """Return decision instants spread across the dataset."""
        times = ReplayFeed(self.dataset, spread_pips=SPREAD_PIPS).decision_times(Timeframe.M5)
        return [times[i] for i in SAMPLE_INDICES if i < len(times)]

    def test_the_mutation_is_material(self) -> None:
        """Guard against a pass that only proves the mutation did nothing."""
        samples = self._sample_times()
        self.assertTrue(samples, "no decision times available")
        cutoff = pd.Timestamp(samples[len(samples) // 2]).to_pydatetime()
        later = cutoff + timedelta(hours=6)
        original = ReplayFeed(self.dataset, spread_pips=SPREAD_PIPS).price_at(later)
        shifted = ReplayFeed(self._mutated(cutoff), spread_pips=SPREAD_PIPS).price_at(later)
        self.assertGreater(abs(shifted - original), 100.0)

    def test_decisions_are_unchanged_by_a_mutated_future(self) -> None:
        samples = self._sample_times()
        self.assertTrue(samples, "no decision times available")
        tested = 0
        for sample in samples:
            moment = pd.Timestamp(sample).to_pydatetime()
            with self.subTest(decision_time=moment.isoformat()):
                baseline = self._decide(self.dataset, moment)
                self.assertIsNotNone(
                    baseline,
                    "sample fell inside the warm-up; it would be skipped silently",
                )
                mutated = self._decide(self._mutated(moment), moment)
                self.assertEqual(
                    json.dumps(baseline, sort_keys=True, default=str),
                    json.dumps(mutated, sort_keys=True, default=str),
                )
                tested += 1
        # Equality, not ">= 1": a sample that quietly stopped running would
        # otherwise leave this test passing on less evidence than it claims.
        self.assertEqual(tested, len(samples))


if __name__ == "__main__":
    unittest.main()
