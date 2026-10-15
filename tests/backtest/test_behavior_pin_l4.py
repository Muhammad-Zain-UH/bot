"""Phase 6Q -- L4 liquidity-engine behaviour pin.

Closes the largest surface Phase 6P left unpinned. Every property asserted here
is **current behaviour**, and most of it is a defect catalogued in Phase 6O-D:
the level is selected by proximity rather than strength, the ``_pips`` parameters
are compared against dollar prices, and single-linkage clustering lets an "equal
high" span many times its own tolerance.

They are pinned **because** they are defects. A future unit correction or
selection-rule change must fail these tests, so that it is a deliberate, visible
decision rather than an accident.

Where a property cannot be proved deterministically from a crafted input, it is
pinned two ways: a source-level assertion of the rule, and an empirical
assertion on the real frozen dataset. Neither alone is sufficient -- the source
check would miss a behavioural change reached another way, and the empirical
check alone could pass by luck.

Audit reference: ``docs/PHASE_6O_D_L4_LIQUIDITY_DEEP_AUDIT.md``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

import liquidity_engine
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

REPO_ROOT = Path(__file__).resolve().parents[2]
LIQUIDITY_SOURCE = (REPO_ROOT / "liquidity_engine.py").read_text(encoding="utf-8")
MAIN_PRODUCTION_SOURCE = (REPO_ROOT / "main_production.py").read_text(encoding="utf-8")

SAMPLE_DECISIONS = 120


def _dataset() -> HistoricalDataset:
    return HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD")


class PinnedL4ToleranceIsDollarsNotPips(unittest.TestCase):
    """Phase 6O-D L4-D1: ``tolerance_pips=1.5`` is compared against a price.

    The documented tolerance is "+/-1.5 pips", which for XAUUSD is **$0.15**. The
    code compares raw prices, so the effective tolerance is **$1.50** -- ten times
    wider. These cases straddle both readings, so they cannot both pass.
    """

    def test_prices_140_apart_cluster(self) -> None:
        """$1.40 apart = 14 pips. Clusters under dollars; would not under pips."""
        clusters = liquidity_engine._cluster_price_points(
            [(0, 4000.00), (1, 4001.40)], 1.5
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_prices_160_apart_do_not_cluster(self) -> None:
        """$1.60 apart exceeds the $1.50 tolerance."""
        clusters = liquidity_engine._cluster_price_points(
            [(0, 4000.00), (1, 4001.60)], 1.5
        )
        self.assertEqual(clusters, [])

    def test_a_true_pip_tolerance_would_reject_what_production_accepts(self) -> None:
        """Pinned contrast: at 0.15 (1.5 real pips) the $1.40 pair separates."""
        as_pips = liquidity_engine._cluster_price_points(
            [(0, 4000.00), (1, 4001.40)], 0.15
        )
        self.assertEqual(as_pips, [], "0.15 should separate them; production uses 1.5")

    def test_every_pips_named_parameter_defaults_are_unchanged(self) -> None:
        import inspect

        signatures = {
            "find_equal_levels": ("tolerance_pips", 1.5),
            "_htf_confluence_strength": ("tolerance_pips", 2.0),
            "find_round_numbers": ("range_pips", 100),
        }
        for function_name, (parameter, expected) in signatures.items():
            function = getattr(liquidity_engine, function_name)
            default = inspect.signature(function).parameters[parameter].default
            self.assertEqual(default, expected, f"{function_name}.{parameter}")

    def test_the_comparisons_use_raw_prices(self) -> None:
        """No pip conversion exists on any of these comparisons."""
        self.assertIn("if point[1] - current[-1][1] <= tolerance_pips:", LIQUIDITY_SOURCE)
        self.assertIn('if abs(existing["level"] - pool["level"]) <= tolerance_pips:', LIQUIDITY_SOURCE)
        self.assertIn("if abs(level - ref) <= tolerance_pips:", LIQUIDITY_SOURCE)
        self.assertIn("if abs(level - current_price) <= range_pips:", LIQUIDITY_SOURCE)


class PinnedL4SingleLinkageClustering(unittest.TestCase):
    """Phase 6O-D L4-D2: clusters chain against the previous point, not the origin.

    Consequence measured on real data: 54.1% of "equal" levels span more than the
    $1.50 tolerance that defines them, to a maximum of $44.07.
    """

    def test_a_simple_pair_clusters(self) -> None:
        clusters = liquidity_engine._cluster_price_points([(0, 4000.0), (1, 4001.0)], 1.5)
        self.assertEqual(len(clusters), 1)

    def test_a_chain_exceeds_the_nominal_tolerance_width(self) -> None:
        """Five points 1.40 apart form ONE cluster spanning $5.60."""
        points = [(index, 4000.0 + 1.4 * index) for index in range(5)]
        clusters = liquidity_engine._cluster_price_points(points, 1.5)
        self.assertEqual(len(clusters), 1)
        width = clusters[0][-1][1] - clusters[0][0][1]
        self.assertAlmostEqual(width, 5.6, places=6)
        self.assertGreater(width, 1.5, "chaining no longer exceeds the tolerance")

    def test_a_long_chain_spans_far_beyond_the_tolerance(self) -> None:
        points = [(index, 4000.0 + 1.4 * index) for index in range(30)]
        clusters = liquidity_engine._cluster_price_points(points, 1.5)
        self.assertEqual(len(clusters), 1)
        self.assertAlmostEqual(clusters[0][-1][1] - clusters[0][0][1], 40.6, places=6)

    def test_duplicate_prices_form_one_cluster(self) -> None:
        clusters = liquidity_engine._cluster_price_points(
            [(0, 4000.0), (1, 4000.0), (2, 4000.0)], 1.5
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)

    def test_ordering_is_by_price_so_input_order_is_irrelevant(self) -> None:
        ascending = [(0, 4000.0), (1, 4001.0), (2, 4002.0)]
        descending = [(0, 4002.0), (1, 4001.0), (2, 4000.0)]
        self.assertEqual(
            [[price for _, price in cluster] for cluster in
             liquidity_engine._cluster_price_points(ascending, 1.5)],
            [[price for _, price in cluster] for cluster in
             liquidity_engine._cluster_price_points(descending, 1.5)],
        )

    def test_a_gap_wider_than_tolerance_splits_the_chain(self) -> None:
        points = [(0, 4000.0), (1, 4001.0), (2, 4010.0), (3, 4011.0)]
        clusters = liquidity_engine._cluster_price_points(points, 1.5)
        self.assertEqual(len(clusters), 2)

    def test_a_lone_point_is_discarded(self) -> None:
        """Clusters require 2+ members, so a solitary price is not a level."""
        self.assertEqual(liquidity_engine._cluster_price_points([(0, 4000.0)], 1.5), [])


class PinnedL4PoolSelectionIsNearestNotStrongest(unittest.TestCase):
    """Phase 6O-D L4-D4: ``min(candidates, key=(distance, -score, tier))``.

    Score is only a tie-break on exactly equal distance, which floating point
    does not produce. Measured: the selected pool is highest-scoring 26.9% of the
    time, median rank 3rd, worst 10th.
    """

    def test_the_rank_key_is_distance_first(self) -> None:
        self.assertIn(
            "return (distance, -float(pool.get(\"score\", 0)), tier_rank)",
            LIQUIDITY_SOURCE,
        )
        self.assertIn('"""Prefer nearest valid pools, then higher score."""', LIQUIDITY_SOURCE)

    def test_selection_uses_min_not_max(self) -> None:
        for line in ("sweep_pool = min(", "tp_pool = min("):
            self.assertIn(line, LIQUIDITY_SOURCE)
        self.assertNotIn("sweep_pool = max(", LIQUIDITY_SOURCE)

    def test_the_selected_pool_is_frequently_not_the_highest_scoring(self) -> None:
        """Empirical counterpart: if selection were by strength this would be 1.0.

        **Correction to Phase 6O-D.** That audit reported "rank 1 only 26.9%",
        computed as a *positional* rank in a score-sorted list. Pools frequently
        share a score, and position among ties is arbitrary, so that figure
        overstates how often a strictly stronger pool was passed over. Measured
        here as "does the selection carry the top score": **76.7%** do, so the
        selection differs from strongest-wins in roughly **23%** of decisions --
        still decisive against strength-selection, but far from 73%.
        """
        dataset = _dataset()
        feed = ReplayFeed(dataset, spread_pips=2.0)
        bar_counts = {
            Timeframe.D1: 10, Timeframe.H1: 60, Timeframe.H4: 100,
            Timeframe.M15: 50, Timeframe.M5: 100,
        }
        rank_one = 0
        sampled = 0
        for index, raw_time in enumerate(feed.decision_times(Timeframe.M5, None, None)):
            if index % 120:
                continue
            if sampled >= SAMPLE_DECISIONS:
                break
            moment = pd.Timestamp(raw_time).to_pydatetime()
            frames = {tf: feed.bars(tf, count, moment) for tf, count in bar_counts.items()}
            if any(len(frame) == 0 for frame in frames.values()):
                continue
            price = float(frames[Timeframe.M5]["close"].iloc[-1])
            result = liquidity_engine.identify_liquidity_pools(
                frames[Timeframe.M15], h1_data=frames[Timeframe.H1],
                h4_data=frames[Timeframe.H4], daily_data=frames[Timeframe.D1],
                current_price=price, side="BUY",
            )
            selected = result.get("sweep_pool")
            below = [p for p in result.get("liquidity_pools", []) if p.get("level", 0) < price]
            if not selected or len(below) < 2:
                continue
            sampled += 1
            best_score = max(p.get("score", 0) for p in below)
            if selected.get("score", 0) == best_score:
                rank_one += 1
        self.assertGreater(sampled, 20, "not enough samples to pin the selection rule")
        self.assertLess(
            rank_one / sampled, 0.95,
            "selection now behaves like strongest-wins -- Phase 6O-D L4-D4 changed",
        )
        self.assertGreater(
            1 - rank_one / sampled, 0.05,
            "the selected pool now always carries the top score -- the rule changed",
        )


class PinnedL4ScoreFilterSelfDisables(unittest.TestCase):
    """Phase 6O-D L4-D5: ``[p for p in pools if score >= 60] or pools``.

    When no pool reaches 60 the filter admits **every** pool, so the documented
    "Reject (<60): Skip this pool" tier rule is not a property of the system.
    Measured: the filter self-disables on 10.7% of decisions.
    """

    def test_the_filter_falls_back_to_all_pools(self) -> None:
        self.assertIn(
            'above_candidates = [p for p in above_pools if p.get("score", 0) >= 60] or above_pools',
            LIQUIDITY_SOURCE,
        )
        self.assertIn(
            'below_candidates = [p for p in below_pools if p.get("score", 0) >= 60] or below_pools',
            LIQUIDITY_SOURCE,
        )

    def test_the_fallback_semantics_are_python_truthiness(self) -> None:
        """Pins the exact mechanism: an empty qualifying list yields the full list."""
        pools = [{"score": 10}, {"score": 55}]
        qualifying = [p for p in pools if p.get("score", 0) >= 60] or pools
        self.assertEqual(qualifying, pools)

        pools_with_one = [{"score": 10}, {"score": 75}]
        qualifying = [p for p in pools_with_one if p.get("score", 0) >= 60] or pools_with_one
        self.assertEqual(qualifying, [{"score": 75}])

    def test_the_score_gate_thresholds_are_unchanged(self) -> None:
        """The SCORE thresholds are untouched by the unit migration."""
        self.assertIn("min_sweep_score = 60 if is_fallback else 70", LIQUIDITY_SOURCE)
        self.assertIn("min_tp_score = 60", LIQUIDITY_SOURCE)

    def test_the_distance_gate_is_now_in_pips_not_price_units(self) -> None:
        """U4 -- **FIXED**. This assertion used to pin the defect as source text.

        It asserted the literal ``max_sweep_distance = 100.0 if is_fallback else
        60.0``, where the value was compared against a distance in QUOTE
        CURRENCY while every surrounding message called it pips. $60 is 600 pips
        on XAUUSD, so the cap could not reject anything -- no M15 liquidity pool
        sits 600 pips from price and still scores.

        Asserted through the constants rather than the source text, so a
        reformatting cannot break it and a unit regression cannot pass it.
        """
        import liquidity_engine
        from core.units import Pips

        self.assertIsInstance(liquidity_engine.MAX_SWEEP_DISTANCE_PIPS, Pips)
        self.assertEqual(liquidity_engine.MAX_SWEEP_DISTANCE_PIPS.value, 60.0)
        self.assertEqual(
            liquidity_engine.MAX_SWEEP_DISTANCE_FALLBACK_PIPS.value, 100.0)

        spec = liquidity_engine.XAUUSD_SPEC
        self.assertAlmostEqual(
            liquidity_engine.MAX_SWEEP_DISTANCE_PIPS.to_price(spec).value,
            6.00, places=9,
            msg="60 pips is $6.00 on XAUUSD; it acted as $60.00 before the fix",
        )
        self.assertAlmostEqual(
            liquidity_engine.MAX_SWEEP_DISTANCE_FALLBACK_PIPS.to_price(spec).value,
            10.00, places=9,
        )

    def test_is_fallback_can_never_be_true(self) -> None:
        """No constructed ``pool_type`` contains "fallback" (Phase 6O-D L4-D12)."""
        import re

        constructed = set(re.findall(r'pool_type="([a-z0-9_]+)"', LIQUIDITY_SOURCE))
        constructed |= {"equal_high", "equal_low"}  # supplied by find_equal_levels
        for pool_type in constructed:
            self.assertNotIn("fallback", pool_type)


class PinnedL4PoolTypes(unittest.TestCase):
    """Phase 6O-D L4-D7 / L4-D8: what is built, and what is only documented."""

    def test_documented_recent_swing_is_never_constructed(self) -> None:
        import re

        constructed = set(re.findall(r'pool_type="([a-z0-9_]+)"', LIQUIDITY_SOURCE))
        self.assertNotIn("swing_low", constructed)
        self.assertNotIn("swing_high", constructed)

    def test_but_the_swing_scoring_branch_still_exists(self) -> None:
        """Dead branch, retained: the documented type is scored by no caller."""
        self.assertIn('elif pool_type == "swing_low" or pool_type == "swing_high":', LIQUIDITY_SOURCE)

    def test_undocumented_htf_types_are_constructed(self) -> None:
        import re

        constructed = set(re.findall(r'pool_type="([a-z0-9_]+)"', LIQUIDITY_SOURCE))
        self.assertIn("h1_level", constructed)
        self.assertIn("h4_level", constructed)

    def test_htf_types_fall_to_the_else_bucket(self) -> None:
        """``h1_level``/``h4_level`` have no base-score branch, so they score 10."""
        for pool_type in ("h1_level", "h4_level"):
            self.assertNotIn(f'pool_type == "{pool_type}"', LIQUIDITY_SOURCE)


class PinnedL4RoundNumberFilterIsInert(unittest.TestCase):
    """Phase 6O-D: ``range_pips=100`` can never exclude a candidate.

    Candidates sit at ``base_round + {0, 25, 50, -25, -50}`` and the price lies in
    ``[base_round, base_round+25)``, so the greatest possible distance is $75.
    """

    def test_all_five_candidates_always_survive(self) -> None:
        for price in (3900.00, 3957.51, 4000.00, 4012.50, 4024.99, 4233.54, 4695.19):
            with self.subTest(price=price):
                rounds = liquidity_engine.find_round_numbers(price)
                self.assertEqual(len(rounds), 5)
                self.assertLess(max(abs(level - price) for level in rounds), 100.0)

    def test_the_worst_case_distance_is_below_the_filter(self) -> None:
        """Just under a $25 boundary is the worst case: $74.99 < $100."""
        rounds = liquidity_engine.find_round_numbers(4024.99)
        self.assertAlmostEqual(max(abs(level - 4024.99) for level in rounds), 74.99, places=2)

    def test_the_spacing_is_dollars_not_pips(self) -> None:
        """Documented "25-pip increments"; the code steps by $25 = 250 pips."""
        rounds = sorted(liquidity_engine.find_round_numbers(4000.0))
        gaps = {round(b - a, 6) for a, b in zip(rounds, rounds[1:])}
        self.assertEqual(gaps, {25.0})


class PinnedL4DownstreamProvenance(unittest.TestCase):
    """Phase 6O-D section 4: the selected level is what L5 and L8 consume."""

    def test_the_l5_call_passes_the_l4_level_twice(self) -> None:
        self.assertIn(
            'l4_sweep_level = sweep_pool.get("level") if sweep_pool else None',
            MAIN_PRODUCTION_SOURCE,
        )
        self.assertIn(
            "get_sweep_and_structure(m15_data, h1_data, l4_sweep_level, side, "
            "l4_override_level=l4_sweep_level)",
            MAIN_PRODUCTION_SOURCE,
        )

    def test_the_override_is_a_no_op_because_both_arguments_are_equal(self) -> None:
        """``detect_sweep`` overwrites ``liquidity_level`` with the same value."""
        self.assertIn("if l4_override_level is not None:", (REPO_ROOT / "sweep_detector.py").read_text(encoding="utf-8"))
        self.assertIn("liquidity_level = l4_override_level", (REPO_ROOT / "sweep_detector.py").read_text(encoding="utf-8"))

    def test_the_stop_anchor_comes_from_the_sweep_wick(self) -> None:
        """L4 level -> L5 sweep candle -> wick -> L8 stop -> R -> lot size."""
        entry_source = (REPO_ROOT / "entry_engine.py").read_text(encoding="utf-8")
        self.assertIn("def _select_stop_anchor(", entry_source)
        self.assertIn("sweep_wick_low", entry_source)
        self.assertIn("sweep_wick_high", entry_source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
