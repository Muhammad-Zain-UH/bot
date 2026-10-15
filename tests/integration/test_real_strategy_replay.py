"""The real strategy must produce a real signal through the replay.

Critical requirement 1: the signal originates from the actual production
analysis path. ``main_production.analyze_entry`` is called, not mocked; no
signal dictionary is manufactured; L1-L8 are the genuine engines.

If the strategy declined to signal, these tests would report the blocking layer
rather than force one -- see :meth:`BlockDiagnosticsTests.test_report_blocking_layer`.
"""

from __future__ import annotations

import unittest

from core.types import Timeframe
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import analyse_at, decision_instant, long_dataset, short_dataset

ALL_ENTRY_LAYERS = (
    "L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY",
    "L5_SWEEP", "L6_POI", "L7_CONFIDENCE", "L8_ENTRY",
)


class RealStrategyIsNotMockedTests(unittest.TestCase):
    """Guards that these tests exercise the production code, not a stand-in."""

    def test_harness_calls_the_real_main_production(self) -> None:
        import main_production

        import tests.integration._harness as harness

        source = __import__("inspect").getsource(harness.analyse_at)
        self.assertIn("main_production.analyze_entry", source)
        self.assertIn("main_production.detect_regime", source)
        self.assertTrue(callable(main_production.analyze_entry))

    def test_analysis_path_uses_the_genuine_layer_engines(self) -> None:
        """The layer functions must be the real modules, not substitutes."""
        import main_production

        self.assertEqual(main_production.get_h4_bias.__module__, "bias_engine")
        self.assertEqual(main_production.get_h1_structure.__module__, "structure_engine")
        self.assertEqual(main_production.get_m15_pullback.__module__, "pullback_detector")
        self.assertEqual(main_production.identify_liquidity_pools.__module__, "liquidity_engine")
        self.assertEqual(main_production.get_sweep_and_structure.__module__, "sweep_detector")
        self.assertEqual(main_production.identify_poi.__module__, "poi_engine")
        self.assertEqual(main_production.get_confidence_engine.__module__, "confidence_engine")
        self.assertEqual(main_production.get_entry_trigger.__module__, "entry_engine")


class LongSignalTests(unittest.TestCase):
    """A BUY signal, produced by the real L1-L8 path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis, cls.regime, cls.frames, cls.price = analyse_at(
            long_dataset(Resolution.TARGET), decision_instant()
        )

    def test_entry_signal_generated(self) -> None:
        self.assertEqual(
            self.analysis.get("signal_type"), "ENTRY_SIGNAL",
            f"blocked at {self.analysis.get('layer_failed')}: "
            f"{self.analysis.get('fail_reason')}",
        )

    def test_every_entry_layer_passed(self) -> None:
        passed = set(self.analysis.get("layers_passed", []))
        self.assertEqual(set(ALL_ENTRY_LAYERS) - passed, set())

    def test_no_layer_blocked(self) -> None:
        self.assertIsNone(self.analysis.get("layer_failed"))

    def test_direction_is_buy(self) -> None:
        self.assertEqual(self.analysis["entry_signal"]["position_type"], "BUY")

    def test_buy_stop_is_below_entry_and_target_above(self) -> None:
        signal = self.analysis["entry_signal"]
        self.assertLess(signal["stop_loss"], signal["entry_price"])
        self.assertGreater(signal["take_profit"], signal["entry_price"])

    def test_sweep_was_genuinely_confirmed(self) -> None:
        """L5 passed on real detection, not on a bypass."""
        self.assertTrue(self.analysis["layer_5"]["sweep_confirmed"])
        self.assertEqual(self.analysis["layer_5"]["state"], "PASS")

    def test_no_layer_was_bypassed(self) -> None:
        """MICRO_SCALP bypasses L3 and L6; this run must not rely on that."""
        passed = self.analysis.get("layers_passed", [])
        self.assertNotIn("L3_PULLBACK_BYPASSED", passed)
        self.assertNotIn("L6_POI_BYPASSED", passed)
        self.assertNotIn("L3_PULLBACK_MOMENTUM", passed)

    def test_confidence_cleared_the_real_threshold(self) -> None:
        self.assertGreaterEqual(self.analysis["layer_7"]["score"], 70.0)

    def test_regime_is_reported(self) -> None:
        self.assertIn(
            self.regime["regime"],
            {"MICRO_SCALP", "REGIME_SCALP", "INTRADAY_SWING", "DEAD_CALM"},
        )


class ShortSignalTests(unittest.TestCase):
    """A SELL signal, produced by the same real path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis, cls.regime, cls.frames, cls.price = analyse_at(
            short_dataset(Resolution.TARGET), decision_instant()
        )

    def test_entry_signal_generated(self) -> None:
        self.assertEqual(
            self.analysis.get("signal_type"), "ENTRY_SIGNAL",
            f"blocked at {self.analysis.get('layer_failed')}: "
            f"{self.analysis.get('fail_reason')}",
        )

    def test_every_entry_layer_passed(self) -> None:
        passed = set(self.analysis.get("layers_passed", []))
        self.assertEqual(set(ALL_ENTRY_LAYERS) - passed, set())

    def test_direction_is_sell(self) -> None:
        self.assertEqual(self.analysis["entry_signal"]["position_type"], "SELL")

    def test_sell_stop_is_above_entry_and_target_below(self) -> None:
        signal = self.analysis["entry_signal"]
        self.assertGreater(signal["stop_loss"], signal["entry_price"])
        self.assertLess(signal["take_profit"], signal["entry_price"])

    def test_sweep_was_genuinely_confirmed(self) -> None:
        self.assertTrue(self.analysis["layer_5"]["sweep_confirmed"])

    def test_no_layer_was_bypassed(self) -> None:
        passed = self.analysis.get("layers_passed", [])
        self.assertNotIn("L3_PULLBACK_BYPASSED", passed)
        self.assertNotIn("L6_POI_BYPASSED", passed)


class BothDirectionsTests(unittest.TestCase):
    """BUY and SELL semantics must mirror each other."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.long_analysis, *_ = analyse_at(long_dataset(Resolution.TARGET), decision_instant())
        cls.short_analysis, *_ = analyse_at(short_dataset(Resolution.TARGET), decision_instant())

    def test_both_directions_produce_signals(self) -> None:
        self.assertEqual(self.long_analysis["entry_signal"]["position_type"], "BUY")
        self.assertEqual(self.short_analysis["entry_signal"]["position_type"], "SELL")

    def test_risk_is_positive_on_both_sides(self) -> None:
        for name, analysis in (("long", self.long_analysis), ("short", self.short_analysis)):
            with self.subTest(side=name):
                signal = analysis["entry_signal"]
                self.assertGreater(abs(signal["entry_price"] - signal["stop_loss"]), 0.0)

    def test_reported_reward_risk_matches_the_regime_ratio(self) -> None:
        """Documents a known defect rather than asserting correctness.

        ``entry_engine`` derives the target as ``risk x tp_ratio``, so its
        reported ``rr_ratio`` is always exactly the regime constant and measures
        nothing about the trade (PHASE_2_ISSUES E9). Pinning it here makes the
        tautology visible; it is NOT evidence the ratio is meaningful.
        """
        for name, analysis in (("long", self.long_analysis), ("short", self.short_analysis)):
            with self.subTest(side=name):
                self.assertAlmostEqual(analysis["entry_signal"]["rr_ratio"], 3.0, places=6)


class BlockDiagnosticsTests(unittest.TestCase):
    """When the strategy declines, the reason must be reportable -- not forced."""

    def test_report_blocking_layer(self) -> None:
        """Ten minutes before the setup, the strategy should not yet signal.

        Asserting a *block* here is as important as asserting the signal: it
        shows the fixture is not simply making the strategy say yes everywhere,
        and it demonstrates the diagnostic path used when a setup fails.
        """
        from datetime import timedelta

        early = decision_instant() - timedelta(minutes=10)
        analysis, _, _, _ = analyse_at(long_dataset(Resolution.TARGET), early)
        self.assertNotEqual(analysis.get("signal_type"), "ENTRY_SIGNAL")
        self.assertIsNotNone(analysis.get("layer_failed"))
        self.assertTrue(str(analysis.get("fail_reason")))

    def test_frames_match_the_production_contract(self) -> None:
        _, _, frames, _ = analyse_at(long_dataset(Resolution.TARGET), decision_instant())
        for timeframe, frame in frames.items():
            with self.subTest(timeframe=timeframe.value):
                self.assertEqual(
                    list(frame.columns),
                    ["time", "open", "high", "low", "close", "tick_volume"],
                )
                self.assertIsNotNone(frame["time"].dt.tz)

    def test_production_bar_counts_were_delivered(self) -> None:
        _, _, frames, _ = analyse_at(long_dataset(Resolution.TARGET), decision_instant())
        self.assertEqual(len(frames[Timeframe.H4]), 100)
        self.assertEqual(len(frames[Timeframe.H1]), 60)
        self.assertEqual(len(frames[Timeframe.M15]), 50)
        self.assertEqual(len(frames[Timeframe.M5]), 100)
        self.assertEqual(len(frames[Timeframe.M1]), 200)
        self.assertEqual(len(frames[Timeframe.D1]), 10)


if __name__ == "__main__":
    unittest.main()
