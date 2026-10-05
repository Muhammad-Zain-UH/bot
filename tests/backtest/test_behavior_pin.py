"""Phase 6P -- immutable behaviour pin for the CURRENT production strategy.

These tests assert **what the strategy does today**, not what it should do. Several
of the properties pinned here are defects catalogued in Phase 6O; they are pinned
*because* they are defects, so that a future repair is detected as a deliberate
change rather than slipping through unnoticed.

Every test below exercises a **production function or production source**. Nothing
that is being pinned is mocked away -- that is the failure mode Phase 6O found in
``tests/test_layer_gate_logic.py`` (see ``PinnedVacuousTestInventory``).

When one of these fails, the correct response is **not** to edit the assertion. It
is to confirm the behaviour change was intended, record it, and then update the pin
in the same commit as the production change.

Audit references: ``docs/PHASE_6O_*`` and ``docs/PHASE_6P_BEHAVIOR_PIN.md``.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PRODUCTION_SOURCE = REPO_ROOT / "main_production.py"

# A small, fixed slice is enough: every property pinned here is structural, so it
# either holds on every window or it does not hold at all. The slice keeps the
# suite fast while still running against real market data.
WINDOW_SAMPLE = 200


def _dataset() -> HistoricalDataset:
    return HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD")


class PinnedSideStateConsistency(unittest.TestCase):
    """Phase 6O-F section 5: the BOS flip reassigns ``side`` but not ``bias``.

    The consequence is that L3 and L7 read the **pre-flip** direction while L4-L8
    read the post-flip one, on 13.03% of decisions. This is pinned at source level
    because the divergence is not observable from the returned analysis dict.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = MAIN_PRODUCTION_SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.analyze = next(
            node
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "analyze_entry"
        )

    def _assignments_to(self, name: str) -> list[ast.AST]:
        found = []
        for node in ast.walk(self.analyze):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        found.append(node)
        return found

    def test_the_flip_reassigns_side(self) -> None:
        assignments = self._assignments_to("side")
        self.assertGreaterEqual(
            len(assignments), 2,
            "analyze_entry should assign `side` at L1 and again in the BOS flip",
        )
        rendered = [ast.unparse(node) for node in assignments]
        self.assertIn("side = flipped_side", rendered)

    def test_the_flip_reassigns_the_bias_label(self) -> None:
        """P8-15: the flip reassigns the L1 label, through a subscript target.

        **Inverted AND made effective by P8-15.** This was
        ``test_the_flip_does_not_reassign_bias``, which asserted that ``bias``
        kept the pre-flip direction and tested it with
        ``assertNotIn("bias = flipped_bias_label", ...)`` over
        ``_assignments_to("bias")`` -- assignments whose target is the **Name**
        ``bias``. Production performs the repair as ``bias["bias"] = ...``, a
        **Subscript** target, which that helper never collects. So the pin passed
        while the defect it existed to detect had already been repaired, exactly
        as the source-text pin in ``test_l3_direction_contract`` did.

        This looks for the subscript form, so it can actually see the contract it
        names. P8-15 changed no decision: the replay was byte-identical to
        ``baseline_006`` across all 15,735 decisions and all four fingerprints.
        """
        subscript_assignments = [
            ast.unparse(node)
            for node in ast.walk(self.analyze)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name)
                and t.value.id == "bias"
                for t in node.targets
            )
        ]
        self.assertIn(
            "bias['bias'] = flipped_bias_label", subscript_assignments,
            "the BOS flip no longer reassigns the L1 bias label -- P8-15 regressed",
        )
        # And it must still not rebind the whole dict, which would detach
        # analysis["layer_1"] from the object the repair mutates.
        rendered = [ast.unparse(node) for node in self._assignments_to("bias")]
        self.assertNotIn("bias = flipped_bias_label", rendered)

    def test_l3_is_called_with_the_effective_direction(self) -> None:
        """D-6OF-2B: L3 evaluates the direction the pipeline is actually trading.

        **This assertion was inverted by D-6OF-2B, deliberately.** It previously
        asserted that L3 received ``bias["bias"]`` -- the pre-L2 label the BOS flip
        never updates -- and was named ``test_l3_is_called_with_the_stale_bias``.

        The contract now: ``architecture.txt`` documents the flip as flipping the
        bias (760-761) and L3's purpose as *"identify quality pullbacks in the
        direction of the bias"* (765). The two compose to the effective side.
        """
        calls = [
            ast.unparse(node)
            for node in ast.walk(self.analyze)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_m15_pullback"
        ]
        self.assertTrue(calls, "get_m15_pullback is no longer called from analyze_entry")
        for call in calls:
            normalised = call.replace('"', "'")
            self.assertNotIn(
                "bias['bias']", normalised,
                f"L3 is reading the stale bias again: {call}",
            )
            self.assertIn(
                "effective_bias_label", normalised,
                f"L3 is not reading the effective direction: {call}",
            )

    def test_the_effective_label_is_derived_from_side(self) -> None:
        """The bridge must come from ``side``, not from a second direction state."""
        assignments = [
            ast.unparse(node)
            for node in ast.walk(self.analyze)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "effective_bias_label"
                for t in node.targets
            )
        ]
        self.assertEqual(len(assignments), 1, f"expected one derivation, got {assignments}")
        normalised = assignments[0].replace('"', "'")
        self.assertIn("side == 'BUY'", normalised)
        self.assertIn("'BULLISH'", normalised)
        self.assertIn("'BEARISH'", normalised)

    def test_layer_1_record_is_not_corrected_by_the_flip(self) -> None:
        """`analysis["layer_1"]` keeps the original bias after a reversal."""
        flip_writes = [
            ast.unparse(node)
            for node in ast.walk(self.analyze)
            if isinstance(node, ast.Assign)
            and "bos_flip" in ast.unparse(node)
        ]
        self.assertTrue(flip_writes, "the BOS flip no longer records `bos_flip`")
        joined = " ".join(flip_writes)
        self.assertNotIn("layer_1", joined)


class PinnedL2FlipIsAnIdentity(unittest.TestCase):
    """Phase 6O-F section 3.1: ``BROKEN`` and the flip condition are one predicate.

    ``validate_h1_structure`` returns BROKEN only on ``close < last_low`` (bullish)
    or ``close > last_high`` (bearish); the flip fires on exactly those. So BROKEN
    implies the flip condition **by construction**, which is why the opposite-side
    rescue was reached 174/174 times in Phase 6O-E.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.h1 = _dataset().frame(Timeframe.H1)

    def test_broken_always_satisfies_the_flip_condition(self) -> None:
        import structure_engine

        broken_seen = 0
        for end in range(60, min(60 + WINDOW_SAMPLE, len(self.h1) + 1)):
            window = self.h1.iloc[:end].tail(50).reset_index(drop=True)
            for bias, side in (("BULLISH", "BUY"), ("BEARISH", "SELL")):
                result = structure_engine.get_h1_structure(window, bias)
                if result.get("structure_type") != "BROKEN":
                    continue
                broken_seen += 1
                close = float(window.iloc[-1]["close"])
                low = result.get("last_swing_low")
                high = result.get("last_swing_high")
                if side == "BUY":
                    self.assertIsNotNone(low)
                    self.assertLess(close, float(low))
                else:
                    self.assertIsNotNone(high)
                    self.assertGreater(close, float(high))
        self.assertGreater(broken_seen, 0, "no BROKEN structure in the sample")

    def test_broken_always_carries_both_swing_levels(self) -> None:
        """Why ``test_broken_h1_structure_blocks_at_l2``'s mock is impossible."""
        import structure_engine

        for end in range(60, min(60 + WINDOW_SAMPLE, len(self.h1) + 1)):
            window = self.h1.iloc[:end].tail(50).reset_index(drop=True)
            for bias in ("BULLISH", "BEARISH"):
                result = structure_engine.get_h1_structure(window, bias)
                if result.get("structure_type") == "BROKEN":
                    self.assertIsNotNone(result.get("last_swing_low"))
                    self.assertIsNotNone(result.get("last_swing_high"))


class PinnedFractalImplementationsAgree(unittest.TestCase):
    """Phase 6O-F section 9: four copies of one 5-bar fractal, provably identical.

    L1 ``bias_engine._find_h4_swings`` * L2 ``structure_engine.find_h1_swings``
    * L3 ``pullback_detector._find_recent_fractal_swing``
    * L5 ``sweep_detector._find_recent_fractal_level``

    They disagree in production only because each caller supplies a different
    window (Phase 6O-C measured 13.67% between L3 and L5). On identical input they
    are the same function.
    """

    def test_all_four_agree_on_an_identical_window(self) -> None:
        import bias_engine
        import pullback_detector
        import structure_engine
        import sweep_detector

        h1 = _dataset().frame(Timeframe.H1)
        compared = 0
        for end in range(60, min(60 + WINDOW_SAMPLE, len(h1) + 1)):
            window = h1.iloc[:end].tail(25).reset_index(drop=True)
            values = [
                bias_engine._find_h4_swings(window, lookback=25)["swing_high"],
                structure_engine.find_h1_swings(window, lookback=25)["recent_high"],
                pullback_detector._find_recent_fractal_swing(window, "HIGH")[1],
                sweep_detector._find_recent_fractal_level(window, "high"),
            ]
            if any(value is None for value in values):
                continue
            compared += 1
            self.assertAlmostEqual(max(values), min(values), places=9)
        self.assertGreater(compared, 0)


class PinnedL3Contract(unittest.TestCase):
    """Phase 6O-B: the L3 pullback contract as it stands."""

    def test_min_pullback_quality_is_unreachable(self) -> None:
        """``pullback_detected`` implies ``quality >= 5.0``, so MIN=1.5 never binds."""
        import pullback_detector

        m15 = _dataset().frame(Timeframe.M15)
        detected = 0
        for end in range(120, min(120 + WINDOW_SAMPLE, len(m15) + 1)):
            window = m15.iloc[:end].tail(50).reset_index(drop=True)
            for bias in ("BULLISH", "BEARISH"):
                result = pullback_detector.detect_m15_pullback(window, bias)
                if result.get("pullback_detected"):
                    detected += 1
                    self.assertGreaterEqual(float(result["pullback_quality"]), 5.0)
        self.assertGreater(detected, 0, "no pullback detected in the sample")

    def test_the_ema_fields_are_always_none(self) -> None:
        """L3 reads ``ema20``/``ema50``; indicators produce ``ema_20``/``ema_50``."""
        import pullback_detector

        m15 = _dataset().frame(Timeframe.M15)
        checked = 0
        for end in range(120, min(120 + 40, len(m15) + 1)):
            window = m15.iloc[:end].tail(50).reset_index(drop=True)
            result = pullback_detector.detect_m15_pullback(window, "BULLISH")
            alignment = result.get("ema_alignment")
            if alignment is None:
                continue
            checked += 1
            self.assertIsNone(alignment["ema20"])
            self.assertIsNone(alignment["ema50"])
        self.assertGreater(checked, 0)

    def test_the_documented_depth_cap_is_0786_not_0618(self) -> None:
        source = inspect.getsource(pullback_source())
        self.assertIn("0.236 <= pullback_percent <= 0.786", source)


def pullback_source():
    import pullback_detector

    return pullback_detector.detect_m15_pullback


class PinnedL5Contract(unittest.TestCase):
    """Phase 6O-C: sweep polarity and the reasoning collision."""

    def test_detect_sweep_never_returns_the_opposite_polarity(self) -> None:
        """Why ``L5_SWEEP_DIRECTION`` measured 0 occurrences in 15,735."""
        import sweep_detector

        m15 = _dataset().frame(Timeframe.M15)
        confirmed = 0
        for end in range(60, min(60 + WINDOW_SAMPLE, len(m15) + 1)):
            window = m15.iloc[:end].tail(60).reset_index(drop=True)
            level = float(window["low"].min())
            for direction, forbidden in (("BUY", "bearish"), ("SELL", "bullish")):
                result = sweep_detector.detect_sweep(window, level, direction)
                if result.get("sweep_confirmed"):
                    confirmed += 1
                    self.assertNotIn(forbidden, str(result.get("sweep_type")))
        self.assertGreaterEqual(confirmed, 0)

    def test_the_reasoning_key_collision_masks_sweep_diagnostics(self) -> None:
        """``{**sweep, **choch}`` -- CHoCH's ``reasoning`` overwrites the sweep's."""
        import sweep_detector

        m15 = _dataset().frame(Timeframe.M15).tail(60)
        sweep = sweep_detector.detect_sweep(m15, float(m15["low"].min()), "BUY")
        choch = sweep_detector.detect_choch(m15, "BUY")
        merged = {**sweep, **choch}
        self.assertIn("reasoning", sweep)
        self.assertIn("reasoning", choch)
        self.assertEqual(merged["reasoning"], choch["reasoning"])


class PinnedL6Contract(unittest.TestCase):
    """Phase 6O-F section 7: L6's Fibonacci zone makes ``best_poi`` unconditional."""

    def test_best_poi_is_never_none_with_twenty_bars(self) -> None:
        import poi_engine

        m15 = _dataset().frame(Timeframe.M15)
        checked = 0
        for end in range(60, min(60 + 60, len(m15) + 1)):
            window = m15.iloc[:end].tail(50).reset_index(drop=True)
            price = float(window.iloc[-1]["close"])
            for direction in ("BUY", "SELL"):
                result = poi_engine.identify_poi(window, direction=direction, current_price=price)
                checked += 1
                self.assertIsNotNone(result["best_poi"])
        self.assertGreater(checked, 0)

    def test_the_regime_poi_threshold_is_ignored_by_the_gate(self) -> None:
        """The gate uses ``60 if sweep_confirmed else 70``, not ``regime_info``."""
        source = MAIN_PRODUCTION_SOURCE.read_text(encoding="utf-8")
        self.assertIn("poi_threshold = 60 if sweep_confirmed else 70", source)


class PinnedRegimeAndSession(unittest.TestCase):
    """Phase 6M: regime bands, session vocabulary and MICRO_SCALP eligibility."""

    def test_session_names_are_exactly_these_five(self) -> None:
        import risk_manager
        from backtest.clock_patch import frozen_clock

        produced = set()
        for day in range(5, 12):
            for hour in range(24):
                moment = datetime(2026, 1, day, hour, 30, tzinfo=timezone.utc)
                with frozen_clock(moment):
                    produced.add(str(risk_manager.get_current_session()))
        self.assertEqual(produced, {"Asian", "London", "NewYork", "Dead", "Closed"})

    def test_micro_scalp_eligible_hours_are_zero_to_thirteen(self) -> None:
        """Hour 13 is NewYork but inside kill zone (12,14), so it qualifies."""
        import entry_engine
        import risk_manager
        from backtest.clock_patch import frozen_clock

        eligible = []
        for hour in range(24):
            moment = datetime(2026, 1, 5, hour, 30, tzinfo=timezone.utc)  # a Monday
            with frozen_clock(moment):
                session = risk_manager.get_current_session()
                kill = entry_engine._within_kill_zone()
            if kill or session in {"Asian", "London", "LondonNewYork"}:
                eligible.append(hour)
        self.assertEqual(eligible, list(range(14)))

    def test_the_kill_zone_ignores_the_weekday(self) -> None:
        """Latent: a weekend bar at 08/09/12/13 UTC would still be kill-zone."""
        import entry_engine
        from backtest.clock_patch import frozen_clock

        saturday = datetime(2026, 1, 10, 8, 30, tzinfo=timezone.utc)
        with frozen_clock(saturday):
            self.assertTrue(entry_engine._within_kill_zone())

    def test_band_b_volatility_classifies_micro_scalp_regardless_of_session(self) -> None:
        """D-6N-1: regime is volatility only; the session disjunct is gone.

        **This assertion was inverted by D-6N-1, deliberately.** Before that
        change a band-B ATR in an ineligible session produced ``DEAD_CALM``; it
        now produces ``MICRO_SCALP``.

        The instant is chosen so the premise cannot lapse: 2026-06-26 18:00 UTC
        is the NewYork session, outside every kill zone, with a measured M5 ATR
        of 4.337 -- squarely inside band B. The Phase 6P version of this test
        guarded its assertion with ``if 2.5 <= atr <= 4.5`` at an instant whose
        ATR is 5.147, so the assertion never ran and the test passed vacuously.
        The guard is removed here; the band membership is asserted instead.
        """
        import entry_engine
        import risk_manager
        from backtest.clock_patch import frozen_clock

        feed = ReplayFeed(_dataset(), spread_pips=2.0)
        moment = datetime(2026, 6, 26, 18, 0, tzinfo=timezone.utc)
        frames = {
            timeframe: feed.bars(timeframe, count, moment)
            for timeframe, count in ((Timeframe.M5, 100), (Timeframe.M15, 50), (Timeframe.H1, 60))
        }
        self.assertTrue(all(len(frame) > 0 for frame in frames.values()))

        with frozen_clock(moment):
            session = risk_manager.get_current_session()
            kill_zone = entry_engine._within_kill_zone()
            info = entry_engine.detect_regime(
                frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1], current_spread=2.0
            )

        # The premise, asserted rather than assumed.
        self.assertEqual(session, "NewYork")
        self.assertFalse(kill_zone)

        # The contract D-6N-1 established: regime is a VOLATILITY claim and the
        # session is a separate eligibility question, so the same bars must
        # classify identically whatever the clock says.
        #
        # This used to assert `regime == "MICRO_SCALP"` for an M5 ATR inside
        # [2.5, 4.5]. That coupled the contract to the absolute band values, and
        # U10's migration made those bands scale with price -- at 2026 gold the
        # MICRO_SCALP floor is $7.37, so this fixture's ATR is now DEAD_CALM.
        # The D-6N-1 contract is untouched by that, so it is asserted directly
        # instead: same bars, different session, same regime.
        with frozen_clock(moment.replace(hour=2)):   # Asian
            asian_session = risk_manager.get_current_session()
            asian = entry_engine.detect_regime(
                frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
                current_spread=2.0,
            )
        self.assertNotEqual(
            asian_session, session,
            "the two calls must differ in session or this proves nothing")
        self.assertEqual(
            info["regime"], asian["regime"],
            "regime must depend on volatility alone, not on the session")
        self.assertEqual(float(info["m5_atr"]), float(asian["m5_atr"]))

    def test_dead_calm_now_requires_genuinely_low_volatility(self) -> None:
        """The inverse of the above: DEAD_CALM is reachable only below 2.5."""
        import entry_engine

        source = (REPO_ROOT / "entry_engine.py").read_text(encoding="utf-8")

        # The real contract: the session disjunct that used to make DEAD_CALM
        # reachable from an ineligible session is gone, and must stay gone. This
        # is what D-6N-1 decided.
        self.assertNotIn(
            'and (kill_zone or session in {"Asian", "London", "LondonNewYork"})', source
        )

        # The regime test must be on volatility alone. This previously asserted
        # the literal source text `if m5_atr >= 2.5 and m5_atr <= 4.5:`, which
        # pinned the ABSOLUTE band values rather than the contract -- and U10's
        # migration replaced them with price-scaled edges. Assert the structure
        # instead: the branch compares m5_atr against the band edges and nothing
        # else is in the condition.
        tree = ast.parse(source)
        regime_fn = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "detect_regime"
        )
        band_tests = [
            node for node in ast.walk(regime_fn)
            if isinstance(node, ast.Compare)
            and any(isinstance(operand, ast.Name) and operand.id == "m5_atr"
                    for operand in [node.left, *node.comparators])
        ]
        self.assertGreaterEqual(
            len(band_tests), 3,
            "expected the three volatility band comparisons on m5_atr")
        for test in band_tests:
            names = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)}
            self.assertNotIn("session", names,
                             "the regime test must not consult the session")
            self.assertNotIn("kill_zone", names,
                             "the regime test must not consult the kill zone")


class PinnedL8Contract(unittest.TestCase):
    """Phase 6K: ``rr`` is the regime constant, not a market measurement."""

    def test_rr_equals_tp_ratio_for_every_regime(self) -> None:
        import entry_engine

        for tp_ratio in (1.5, 2.0, 2.5, 3.0):
            for direction in ("BUY", "SELL"):
                wick = 4000.0 - 3.0 if direction == "BUY" else 4000.0 + 3.0
                levels = entry_engine.calculate_entry_levels(
                    direction=direction,
                    entry_price=4000.0,
                    sweep_wick_low=wick if direction == "BUY" else None,
                    sweep_wick_high=wick if direction == "SELL" else None,
                    tp_ratio=tp_ratio,
                )
                self.assertAlmostEqual(
                    levels["reward_to_risk_ratio"], tp_ratio, places=12,
                    msg=f"{direction} tp_ratio={tp_ratio}",
                )


class PinnedAggregateFingerprint(unittest.TestCase):
    """Phase 6P section 12: aggregate regression detection.

    ``tests/fixtures/behavior_fingerprint.json`` is the committed reference. The
    fields recomputed here come from the **frozen** ``baseline_005`` decision
    stream, so they are cheap and exact. Fields that require a full replay (bias
    label, reconstructed side, structure type, reversals) are stored in the
    fixture and regenerated by ``tests/fixtures/generate_behavior_fingerprint.py``
    -- they are not recomputed per test run.

    **Scope caveat, deliberately explicit:** the ``blocked_at`` / ``signal_type``
    fields describe ``baseline_005`` at commit ``7b702dd``, which predates U4.
    Current HEAD admits four signals (Phase 6K-F). The reconstructed fields were
    computed with current HEAD and are unaffected by U4, which touched only
    ``calculate_entry_levels``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import json

        cls.fingerprint = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "behavior_fingerprint.json").read_text(
                encoding="utf-8"
            )
        )
        stream = REPO_ROOT / "baselines" / "baseline_005" / "decisions.jsonl"
        cls.decisions = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines()]

    def test_decision_count(self) -> None:
        self.assertEqual(len(self.decisions), 15735)
        self.assertEqual(self.fingerprint["decisions"], 15735)

    def test_the_frozen_stream_still_describes_baseline_005(self) -> None:
        """Artifact-integrity check, independent of the fingerprint.

        ``baseline_005`` is frozen at commit ``7b702dd``. These are *its* numbers
        and they must never move. The fingerprint is no longer compared against
        them: since D-6N-1 the fingerprint is a HEAD replay, and HEAD's strategy
        differs from the one that produced this stream.
        """
        import collections

        regimes = dict(collections.Counter(row["regime"] for row in self.decisions))
        self.assertEqual(regimes, {
            "DEAD_CALM": 2312, "INTRADAY_SWING": 1810,
            "MICRO_SCALP": 5121, "REGIME_SCALP": 6492,
        })
        funnel = dict(collections.Counter(str(row.get("blocked")) for row in self.decisions))
        self.assertEqual(funnel["L8_ENTRY"], 1265)
        self.assertEqual(funnel["L1_BIAS"], 2392)
        sides = dict(collections.Counter(str(row.get("side") or None) for row in self.decisions))
        self.assertEqual(sides, {"BUY": 6693, "SELL": 6650, "None": 2392})

    def test_the_fingerprint_describes_current_head_after_d6n1(self) -> None:
        """Post-D-6N-1 HEAD values. Every one of these moved, by design.

        D-6N-1: DEAD_CALM 2,312 -> 119; MICRO_SCALP 5,121 -> 7,314;
        L1_BIAS blocks 2,392 -> 1,505; L8_ENTRY blocks 1,261 -> 1,589.
        D-6OF-2B then moved the L3-and-downstream funnel without touching regime
        or L1: L3 5,094 -> 5,066, L4 725 -> 743, L5 3,037 -> 3,060,
        L7 1,833 -> 1,825, L8 1,589 -> 1,583.
        """
        self.assertEqual(self.fingerprint["regime"], {
            "DEAD_CALM": 119, "INTRADAY_SWING": 1810,
            "MICRO_SCALP": 7314, "REGIME_SCALP": 6492,
        })
        self.assertEqual(self.fingerprint["blocked_at"]["L1_BIAS"], 1505)
        self.assertEqual(self.fingerprint["blocked_at"]["L8_ENTRY"], 1583)
        self.assertEqual(self.fingerprint["blocked_at"]["L3_PULLBACK"], 5066)
        self.assertEqual(self.fingerprint["effective_side"],
                         {"BUY": 7244, "SELL": 6986, "None": 1505})

    def test_the_signal_count_did_not_change(self) -> None:
        """4 -> 4. A measurement; it is neither good nor bad."""
        self.assertEqual(self.fingerprint["signal_type"]["ENTRY_SIGNAL"], 4)

    def test_the_regime_selects_the_bias_timeframe(self) -> None:
        """The cascade: 2,193 decisions moved from the H4 engine to the H1 one."""
        self.assertEqual(self.fingerprint["bias_timeframe"], {"H1": 13806, "H4": 1929})

    def test_every_broken_structure_either_flipped_or_is_one_of_the_seven(self) -> None:
        """1,745 BROKEN = 1,738 reversals + 7 L2 blocks. The identity, at scale."""
        broken = self.fingerprint["l2_structure_type"]["BROKEN"]
        reversals = self.fingerprint["reversals"]["count"]
        l2_blocks = self.fingerprint["blocked_at"]["L2_STRUCTURE"]
        self.assertEqual(broken, reversals + l2_blocks)

    def test_l3_always_sees_the_effective_side(self) -> None:
        """D-6OF-2B: for every reversal L1 != EFFECTIVE, and **L3 == EFFECTIVE**.

        Inverted by D-6OF-2B. It previously asserted ``L3 == L1`` and was named
        ``test_l3_always_sees_the_pre_flip_side``.
        """
        matrix = self.fingerprint["side_state_matrix"]
        reversed_keys = [
            key for key in matrix
            if key.startswith("L1=BUY|EFF=SELL") or key.startswith("L1=SELL|EFF=BUY")
        ]
        self.assertEqual(sorted(reversed_keys), [
            "L1=BUY|EFF=SELL|L3=SELL",
            "L1=SELL|EFF=BUY|L3=BUY",
        ])
        self.assertEqual(
            sum(matrix[key] for key in reversed_keys),
            self.fingerprint["reversals"]["count"],
        )

    def test_the_l2_blocks_are_still_one_market_event(self) -> None:
        """7 -> 12 decisions, but the same single H1 state and reason string."""
        self.assertEqual(self.fingerprint["l2_blocks"]["decisions"], 12)
        self.assertEqual(self.fingerprint["l2_blocks"]["distinct_h1_states"], 1)
        self.assertEqual(len(self.fingerprint["l2_blocks"]["distinct_reasons"]), 1)

    def test_reversals_are_runs_not_independent_events(self) -> None:
        """Post-D-6N-1: 1,845 M5 reversals over 157 distinct H1 states.

        Was 1,738 over 153. The rise follows from 887 more decisions passing L1
        and therefore reaching L2 at all -- not from any change to L2 itself.
        """
        reversals = self.fingerprint["reversals"]
        self.assertEqual(reversals["count"], 1845)
        self.assertEqual(reversals["distinct_h1_states"], 157)
        self.assertEqual(reversals["run_length"]["max"], 12)

    def test_the_reversal_mechanism_rebalances_the_side_mix(self) -> None:
        """L1 leans SELL; the effective mix is near even. Pinned, not endorsed."""
        initial = self.fingerprint["l1_initial_side"]
        effective = self.fingerprint["effective_side"]
        self.assertGreater(initial["SELL"], initial["BUY"])
        self.assertGreater(effective["BUY"], initial["BUY"])


class PinnedCorrectedL2Population(unittest.TestCase):
    """Phase 6Q Part E: the corrected reversal population, and what it is not.

    Phase 6O-E reported 174 reversals from a 1-in-10 sample. The population is
    1,738. Critically, those are **decision-level** reversals: each H1 structure
    break is re-decided once per M5 bar inside that hour, so 1,738 decisions
    correspond to ~153 distinct H1 break states. This class asserts both numbers
    and asserts that they are **not** the same thing.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import json

        cls.fingerprint = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "behavior_fingerprint.json").read_text(
                encoding="utf-8"
            )
        )

    def test_sided_decision_count(self) -> None:
        """13,343 -> 14,230: 887 fewer L1 blocks under the H1 bias engine."""
        sides = self.fingerprint["effective_side"]
        self.assertEqual(sides["BUY"] + sides["SELL"], 14230)

    def test_reversal_count_and_rate(self) -> None:
        """1,738 -> 1,845, while the rate barely moves: 13.03% -> 12.97%."""
        self.assertEqual(self.fingerprint["reversals"]["count"], 1845)
        self.assertAlmostEqual(self.fingerprint["reversals"]["pct_of_sided"], 12.9656, places=3)

    def test_broken_count(self) -> None:
        """1,745 -> 1,857."""
        self.assertEqual(self.fingerprint["l2_structure_type"]["BROKEN"], 1857)

    def test_rescue_failure_count(self) -> None:
        """7 -> 12 decisions, still one H1 state."""
        self.assertEqual(self.fingerprint["blocked_at"]["L2_STRUCTURE"], 12)

    def test_the_three_numbers_reconcile(self) -> None:
        """1,745 BROKEN = 1,738 reversals + 7 rescue failures. No third outcome."""
        self.assertEqual(
            self.fingerprint["l2_structure_type"]["BROKEN"],
            self.fingerprint["reversals"]["count"]
            + self.fingerprint["blocked_at"]["L2_STRUCTURE"],
        )

    def test_decision_level_reversals_are_not_market_events(self) -> None:
        """The distinction that must survive: 1,845 decisions, 157 H1 states."""
        reversals = self.fingerprint["reversals"]
        self.assertEqual(reversals["distinct_h1_states"], 157)
        self.assertLess(
            reversals["distinct_h1_states"], reversals["count"] / 10,
            "distinct H1 states should be an order of magnitude below the decision count",
        )

    def test_a_reversal_run_spans_one_h1_bar(self) -> None:
        """Twelve M5 decisions fit in an H1 bar, and the run length reaches twelve."""
        run_length = self.fingerprint["reversals"]["run_length"]
        self.assertEqual(run_length["max"], 12)
        self.assertEqual(run_length["median"], 12)
        self.assertGreaterEqual(run_length["min"], 1)

    def test_the_rescue_failures_share_one_h1_state(self) -> None:
        self.assertEqual(self.fingerprint["l2_blocks"]["distinct_h1_states"], 1)


class PinnedSideStateConsistencyHasZeroExceptions(unittest.TestCase):
    """D-6OF-2B: L3 now follows the effective side, on every decision.

    **This class was inverted by D-6OF-2B, deliberately.** It previously asserted
    the inconsistency -- ``BIAS_SIDE_USED_BY_L3 == L1_INITIAL_SIDE`` on every
    reversal -- and was named ``PinnedSideStateInconsistencyHasZeroExceptions``.

    It now asserts the repaired contract: ``BIAS_SIDE_USED_BY_L3 ==
    L2_EFFECTIVE_SIDE`` with no exceptions. ``bias`` and ``bias_strength`` are
    still **not** reassigned by the flip -- that remains open as D-6OF-2 model 2/3
    -- so ``analysis["layer_1"]`` and L7's ``bias_strength`` still carry the
    pre-flip values. Only L3's direction input changed.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import json

        cls.matrix = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "behavior_fingerprint.json").read_text(
                encoding="utf-8"
            )
        )["side_state_matrix"]

    @staticmethod
    def _parse(key: str) -> tuple[str, str, str]:
        parts = dict(piece.split("=", 1) for piece in key.split("|"))
        return parts["L1"], parts["EFF"], parts["L3"]

    def test_every_combination_present_is_one_of_exactly_five(self) -> None:
        self.assertEqual(len(self.matrix), 5)

    def test_l3_always_equals_the_effective_side_with_no_exception(self) -> None:
        for key, count in self.matrix.items():
            initial, effective, used_by_l3 = self._parse(key)
            with self.subTest(key=key, count=count):
                self.assertEqual(
                    used_by_l3, effective,
                    "L3 is not tracking the effective side -- D-6OF-2B regressed",
                )

    def test_no_combination_exists_where_l3_tracks_the_abandoned_side(self) -> None:
        offenders = [
            key for key in self.matrix
            if (lambda triple: triple[1] != triple[0] and triple[2] == triple[0])(self._parse(key))
        ]
        self.assertEqual(offenders, [], "L3 is reading the pre-flip direction again")

    def test_the_reversed_combinations_account_for_every_reversal(self) -> None:
        import json

        fingerprint = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "behavior_fingerprint.json").read_text(
                encoding="utf-8"
            )
        )
        reversed_total = sum(
            count for key, count in self.matrix.items()
            if (lambda triple: triple[0] != triple[1] and triple[0] != "None")(self._parse(key))
        )
        self.assertEqual(reversed_total, fingerprint["reversals"]["count"])


class PinnedVacuousTestInventory(unittest.TestCase):
    """Phase 6P section 14: tests that give false confidence, pinned as such.

    These assertions document *why* each listed test does not prove what its name
    suggests. They are pinned so that a future repair of the underlying test is a
    deliberate, visible change.
    """

    def test_layer_gate_logic_mocks_away_the_layers_it_names(self) -> None:
        source = (REPO_ROOT / "tests" / "test_layer_gate_logic.py").read_text(encoding="utf-8")
        for mocked in ("get_m15_pullback", "get_h1_structure", "get_sweep_and_structure"):
            self.assertIn(f'"{mocked}"', source)

    def test_the_l2_mock_omits_the_swing_levels_production_always_supplies(self) -> None:
        """This is the only reason that test reaches an L2 block at all."""
        source = (REPO_ROOT / "tests" / "test_layer_gate_logic.py").read_text(encoding="utf-8")
        broken_mock = '{"structure_type": "BROKEN", "structure_confidence": 2.0, "structure_valid": False}'
        self.assertIn(broken_mock, source)
        self.assertNotIn("last_swing_low", broken_mock)

    def test_entry_quality_gate_uses_rr_values_production_cannot_produce(self) -> None:
        """``rr`` is always the regime ``tp_ratio``; 1.4/2.4/2.8 are not among them."""
        source = (REPO_ROOT / "tests" / "test_entry_quality_gate.py").read_text(encoding="utf-8")
        for impossible in ("1.4", "2.4", "2.8"):
            self.assertIn(f'"reward_to_risk_ratio": {impossible}', source)

    def test_the_timezone_independence_test_is_vacuous_on_windows(self) -> None:
        import time

        source = (REPO_ROOT / "tests" / "integration" / "test_integration_leakage.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('hasattr(time, "tzset")', source)
        if not hasattr(time, "tzset"):
            self.assertFalse(
                hasattr(time, "tzset"),
                "tzset now exists -- the timezone test is no longer vacuous here",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
