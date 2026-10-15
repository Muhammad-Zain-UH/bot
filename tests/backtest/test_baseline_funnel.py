"""The L1-L8 funnel must stay monotonic.

Reached-counts are cumulative: a decision cannot reach L7 without having reached
L6. So the counts must be non-increasing from L1 to L8, and a funnel that is not
is reporting something impossible.

This has already gone wrong once. The strategy does not emit bare layer names --
it emits ``L6_POI_BYPASSED`` when MICRO_SCALP skips a layer, ``L3_PULLBACK_MOMENTUM``
when REGIME_SCALP takes the momentum path, ``L5_SWEEP_WAIT`` while waiting for
confirmation. Matching layer names exactly made bypassed layers look unreached,
and the funnel showed L6 reached by fewer decisions than L7. The fix was prefix
matching; these tests keep it fixed.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backtest.baseline import ENTRY_LAYERS, _funnel
from backtest.replay_engine import DecisionSnapshot


def _snapshot(passed: tuple[str, ...], blocked: str, minute: int = 0) -> DecisionSnapshot:
    """Build a decision snapshot with a given layer trace."""
    return DecisionSnapshot(
        replay_time=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute),
        availability={},
        current_price=3900.0,
        spread_pips=2.0,
        regime="MICRO_SCALP",
        signal_type="PRE_ENTRY",
        direction="BUY",
        layers_passed=passed,
        layer_failed=blocked,
        fail_reason="reason",
    )


def _assert_monotonic(case: unittest.TestCase, funnel: dict) -> None:
    """Reached-counts must not increase as the layers advance."""
    reached = funnel["reached_layer"]
    counts = [reached[layer] for layer in ENTRY_LAYERS]
    for earlier, later in zip(ENTRY_LAYERS, ENTRY_LAYERS[1:]):
        case.assertGreaterEqual(
            reached[earlier], reached[later],
            f"{earlier} reached {reached[earlier]} but {later} reached {reached[later]}",
        )
    case.assertEqual(counts, sorted(counts, reverse=True))


class TestBypassLabelsCountAsReached(unittest.TestCase):
    """A bypassed layer was reached; it just was not evaluated."""

    def test_micro_scalp_bypass_trace_is_monotonic(self) -> None:
        """MICRO_SCALP bypasses L3 and L6 -- the classic non-monotonic case."""
        trace = (
            "L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_BYPASSED", "L4_LIQUIDITY",
            "L5_SWEEP", "L6_POI_BYPASSED", "L7_CONFIDENCE",
        )
        funnel = _funnel([_snapshot(trace, "L8_ENTRY", minute=i) for i in range(10)])
        _assert_monotonic(self, funnel)
        self.assertEqual(funnel["reached_layer"]["L3_PULLBACK"], 10)
        self.assertEqual(funnel["reached_layer"]["L6_POI"], 10)
        self.assertEqual(funnel["reached_layer"]["L8_ENTRY"], 10)

    def test_variant_pass_labels_count_as_reached(self) -> None:
        trace = ("L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_MOMENTUM")
        funnel = _funnel([_snapshot(trace, "L4_LIQUIDITY")])
        self.assertEqual(funnel["reached_layer"]["L3_PULLBACK"], 1)
        _assert_monotonic(self, funnel)

    def test_a_layer_blocked_at_still_counts_as_reached(self) -> None:
        funnel = _funnel([_snapshot(("L1_BIAS",), "L2_STRUCTURE")])
        self.assertEqual(funnel["reached_layer"]["L2_STRUCTURE"], 1)


class TestMixedTracesStayMonotonic(unittest.TestCase):
    """A realistic mixture of traces, the shape the real run produced."""

    def setUp(self) -> None:
        snapshots = []
        minute = 0

        def add(trace, blocked, times):
            nonlocal minute
            for _ in range(times):
                snapshots.append(_snapshot(trace, blocked, minute))
                minute += 5

        add((), "L1_BIAS", 40)
        add(("L1_BIAS",), "L2_STRUCTURE", 5)
        add(("L1_BIAS", "L2_STRUCTURE"), "L3_PULLBACK", 30)
        add(("L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_BYPASSED"), "L4_LIQUIDITY", 10)
        add(("L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY"), "L5_SWEEP", 25)
        add(
            ("L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_BYPASSED", "L4_LIQUIDITY",
             "L5_SWEEP", "L6_POI_BYPASSED"),
            "L7_CONFIDENCE", 12,
        )
        add(
            ("L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK_BYPASSED", "L4_LIQUIDITY",
             "L5_SWEEP", "L6_POI_BYPASSED", "L7_CONFIDENCE"),
            "L8_ENTRY", 8,
        )
        self.funnel = _funnel(snapshots)
        self.total = len(snapshots)

    def test_funnel_is_monotonic(self) -> None:
        _assert_monotonic(self, self.funnel)

    def test_l1_is_reached_by_everything_that_was_not_blocked_before_it(self) -> None:
        reached = self.funnel["reached_layer"]
        self.assertEqual(reached["L1_BIAS"], self.total)

    def test_blocked_counts_sum_to_the_total(self) -> None:
        self.assertEqual(sum(self.funnel["blocked_at"].values()), self.total)

    def test_no_layer_is_reached_more_often_than_there_are_decisions(self) -> None:
        for layer, count in self.funnel["reached_layer"].items():
            with self.subTest(layer=layer):
                self.assertLessEqual(count, self.total)


class TestEmptyInput(unittest.TestCase):
    """An empty run must not divide by zero or invent counts."""

    def test_empty_funnel_is_all_zero(self) -> None:
        funnel = _funnel([])
        self.assertEqual(funnel["total_decisions"], 0)
        self.assertEqual(set(funnel["reached_layer"].values()), {0})
        self.assertEqual(funnel["blocked_at"], {})
        self.assertEqual(funnel["blocked_at_percent"], {})


if __name__ == "__main__":
    unittest.main()
