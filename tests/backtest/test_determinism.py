"""Determinism tests.

The same historical input must produce the same output on any machine, in any
timezone, at any time of day. Without that, a backtest result cannot be
reproduced or audited, and two runs that disagree cannot be told apart from a
genuine change.

The wall-clock tests matter especially here because the strategy contains four
ambient ``datetime.now()`` reads (N1-N4). :mod:`backtest.clock_patch` neutralises
them; these tests prove it, rather than assuming it.
"""

from __future__ import annotations

import ast
import os
import time
import unittest
from datetime import timedelta
from pathlib import Path

from core.symbols import XAUUSD_2DIGIT
from core.types import Timeframe
from data.replay_feed import ReplayFeed
from execution.paper_broker import PaperBroker
from backtest.metrics import compute_metrics
from backtest.replay_engine import ReplayConfig, ReplayEngine
from tests.fixtures.market import SYNTHETIC_START, make_synthetic_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]


class _StubStrategy:
    """A strategy stand-in with one deterministic, data-dependent rule.

    Used where the real strategy would be too slow to run repeatedly, and where
    the property under test is the *engine's* determinism rather than the
    strategy's. It reads the clock deliberately, so a run that failed to freeze
    time would show up as non-determinism.
    """

    def __init__(self) -> None:
        self.calls = 0

    def detect_regime(self, m5, m15, h1, current_spread=1.0):  # noqa: ANN001
        return {"regime": "REGIME_SCALP", "m5_atr": float(m5["close"].iloc[-1]) % 7,
                "tp_ratio": 2.0, "risk_percent": 1.0, "current_spread": current_spread}

    def analyze_entry(self, h4, h1, m15, m5, m1, daily, current_price=0.0,
                      regime_info=None):  # noqa: ANN001
        import risk_manager

        self.calls += 1
        # Signal on a deterministic property of the data, gated on the session.
        #
        # The session deliberately comes from `risk_manager.get_current_session()`
        # -- a module the replay clock patches -- rather than from a direct
        # `datetime.now()` here. That matters twice over:
        #
        #   * it mirrors how the real strategy reads time, so the test exercises
        #     the same mechanism, and
        #   * a direct `datetime.now()` in THIS module would not be patched
        #     (frozen_clock only covers the strategy modules), making the stub
        #     itself wall-clock dependent. An earlier version did exactly that
        #     and was flaky: it gated on `now.minute % 2`, so it emitted zero
        #     signals on odd minutes and passed or failed depending on when the
        #     suite happened to run.
        #
        # So if the freeze ever stopped working, the session would fall back to
        # wall-clock time and the determinism assertions would fail -- which is
        # precisely what this stub is here to detect.
        session = risk_manager.get_current_session()
        trigger = int(float(m5["close"].iloc[-1]) * 100) % 23 == 0
        if trigger and session in {"London", "NewYork"}:
            entry = float(m5["close"].iloc[-1])
            return {
                "signal_type": "ENTRY_SIGNAL",
                "layers_passed": ["L1_BIAS", "L2_STRUCTURE"],
                "layer_failed": None, "direction": "BUY",
                "entry_signal": {
                    "position_type": "BUY", "entry_price": entry,
                    "stop_loss": entry - 3.0, "take_profit": entry + 6.0,
                    "setup_type": "STUB", "entry_method": "STUB", "grade": "A",
                },
            }
        return {"signal_type": "PRE_ENTRY", "layers_passed": ["L1_BIAS"],
                "layer_failed": "L2_STRUCTURE", "fail_reason": "stub",
                "direction": "BUY", "entry_signal": None}


# Reduced bar counts so a compact fixture can still reach the decision loop.
# Production requires 100 H4 bars (400 hours of market time); satisfying that
# here would need ~25,000 M1 bars per run, and these tests exercise the ENGINE's
# determinism, not production bar sizing. The full-size counts are covered by
# tests/backtest/test_replay_engine.py and by the synthetic fixture run.
TEST_BAR_COUNTS = {
    Timeframe.H4: 20, Timeframe.H1: 20, Timeframe.M15: 20,
    Timeframe.M5: 20, Timeframe.M1: 20, Timeframe.D1: 2,
}


def _run(seed_dataset, start_offset=5_000, end_offset=8_000) -> tuple:
    """Run one replay and return (fingerprint, metrics dict, decisions, signals)."""
    feed = ReplayFeed(seed_dataset)
    broker = PaperBroker(XAUUSD_2DIGIT)
    engine = ReplayEngine(
        feed, broker, XAUUSD_2DIGIT,
        ReplayConfig(
            driving_timeframe=Timeframe.M5,
            start=SYNTHETIC_START + timedelta(minutes=start_offset),
            end=SYNTHETIC_START + timedelta(minutes=end_offset),
            bar_counts=dict(TEST_BAR_COUNTS),
        ),
        strategy=_StubStrategy(),
    )
    result = engine.run()
    metrics = compute_metrics(
        result.ledger.trades, result.signals, len(result.ledger.rejections)
    )
    return (
        result.ledger.fingerprint(),
        metrics.to_dict(),
        result.decisions,
        result.signals,
    )


class RepeatedRunTests(unittest.TestCase):
    """Two runs over identical data must agree in every respect."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = make_synthetic_dataset(bars=9_000)

    def test_two_runs_produce_identical_ledgers(self) -> None:
        first = _run(self.dataset)
        second = _run(self.dataset)
        self.assertEqual(first[0], second[0], "ledger fingerprints differ")

    def test_two_runs_produce_identical_metrics(self) -> None:
        self.assertEqual(_run(self.dataset)[1], _run(self.dataset)[1])

    def test_two_runs_produce_identical_decision_and_signal_counts(self) -> None:
        first = _run(self.dataset)
        second = _run(self.dataset)
        self.assertEqual((first[2], first[3]), (second[2], second[3]))

    def test_the_run_actually_produced_trades(self) -> None:
        """Guards against determinism passing trivially on an empty ledger."""
        _, metrics, decisions, signals = _run(self.dataset)
        self.assertGreater(decisions, 50)
        self.assertGreater(signals, 0, "stub strategy produced no signals to compare")

    def test_dataset_generation_is_reproducible(self) -> None:
        import pandas as pd

        a = make_synthetic_dataset(bars=500).frame(Timeframe.M1)
        b = make_synthetic_dataset(bars=500).frame(Timeframe.M1)
        pd.testing.assert_frame_equal(a, b)


class WallClockIndependenceTests(unittest.TestCase):
    """Results must not depend on when, or where, the run happened."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = make_synthetic_dataset(bars=9_000)

    def test_result_is_unchanged_across_wall_clock_time(self) -> None:
        first = _run(self.dataset)[0]
        time.sleep(1.1)  # cross a wall-clock second boundary
        self.assertEqual(first, _run(self.dataset)[0])

    def test_result_is_unchanged_across_machine_timezones(self) -> None:
        """A naive local ``datetime.now()`` would make this fail."""
        fingerprints = []
        original = os.environ.get("TZ")
        try:
            for zone in ("UTC", "Asia/Karachi", "America/New_York"):
                os.environ["TZ"] = zone
                if hasattr(time, "tzset"):
                    time.tzset()
                fingerprints.append(_run(self.dataset)[0])
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            if hasattr(time, "tzset"):
                time.tzset()
        self.assertEqual(len(set(fingerprints)), 1, "result varied with machine timezone")


class NoRandomnessTests(unittest.TestCase):
    """No unseeded randomness may reach the simulation packages."""

    PACKAGES = ("data", "execution", "backtest")

    def test_no_random_import_in_simulation_packages(self) -> None:
        offenders: dict[str, str] = {}
        for package in self.PACKAGES:
            for path in (REPO_ROOT / package).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.split(".")[0] == "random":
                                offenders[f"{package}/{path.name}"] = alias.name
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.split(".")[0] == "random":
                            offenders[f"{package}/{path.name}"] = node.module
        self.assertEqual(
            offenders, {},
            f"simulation packages must contain no unseeded randomness: {offenders}",
        )

    def test_order_execution_random_is_not_reachable_from_the_simulator(self) -> None:
        """``order_execution`` injects a 5% random failure; the simulator must not use it."""
        for package in self.PACKAGES:
            for path in (REPO_ROOT / package).glob("*.py"):
                with self.subTest(module=f"{package}/{path.name}"):
                    self.assertNotIn("order_execution", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
