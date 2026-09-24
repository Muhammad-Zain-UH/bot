"""The RR gate is retired, and nothing took its place.

Phase 6I removed one conjunct from ``entry_triggered``. These tests pin what
that did and -- more importantly -- what it did not do: no threshold moved, no
other gate loosened, no candidate became eligible for any reason except that the
retired term is gone.

What was removed, and why, is in ``docs/VALID_RR_CONTRACT.md``. The short form:
``take_profit`` is built as ``risk_distance * tp_ratio``, so ``rr`` was
``tp_ratio``, and comparing it to ``2.0`` asked whether the configured value was
the configured value.

**No minimum-RR value is defined anywhere, and none is introduced here.**
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import entry_engine
from backtest.baseline import REGIME_TP_RATIO

SOURCE = Path(entry_engine.__file__)
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))

EVALUATORS = ("_evaluate_pullback_entry", "_evaluate_momentum_entry")


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in entry_engine")


def _dict_value(func: ast.FunctionDef, key: str) -> str | None:
    """Source of the value assigned to ``key`` in a returned dict literal."""
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    return ast.unparse(v)
    return None


class EntryTriggerIsTheRawTrigger(unittest.TestCase):
    """B: a low ``tp_ratio`` no longer rejects an otherwise valid candidate."""

    def test_pullback_entry_triggered_is_exactly_its_raw_trigger(self) -> None:
        self.assertEqual(
            _dict_value(_function("_evaluate_pullback_entry"), "entry_triggered"),
            "bool(raw_triggered)",
        )

    def test_momentum_entry_triggered_is_exactly_its_core_trigger(self) -> None:
        self.assertEqual(
            _dict_value(_function("_evaluate_momentum_entry"), "entry_triggered"),
            "bool(core_trigger)",
        )

    def test_neither_evaluator_reads_an_rr_verdict(self) -> None:
        for name in EVALUATORS:
            with self.subTest(function=name):
                source = ast.unparse(_function(name))
                self.assertNotIn("valid_rr", source)
                self.assertNotIn("rr_valid", source)


class TheArithmeticIsUnchanged(unittest.TestCase):
    """A and C: removing a gate must not disturb the geometry it read."""

    def test_rr_still_equals_tp_ratio(self) -> None:
        for regime, tp_ratio in REGIME_TP_RATIO.items():
            for entry, wick, side in (
                (2500.0, 2490.0, "BUY"), (4000.0, 3997.5, "BUY"),
            ):
                with self.subTest(regime=regime, entry=entry):
                    levels = entry_engine.calculate_entry_levels(
                        entry_price=entry, sweep_wick_low=wick,
                        direction=side, tp_ratio=tp_ratio,
                    )
                    self.assertAlmostEqual(
                        levels["reward_to_risk_ratio"], tp_ratio, places=9
                    )

    def test_target_is_still_risk_times_ratio_from_the_entry(self) -> None:
        """The construction the gate was redundant with is untouched."""
        for tp_ratio in (1.5, 2.0, 3.0):
            for side, wick_kw in (("BUY", "sweep_wick_low"), ("SELL", "sweep_wick_high")):
                with self.subTest(tp_ratio=tp_ratio, side=side):
                    wick = 2490.0 if side == "BUY" else 2512.0
                    levels = entry_engine.calculate_entry_levels(
                        entry_price=2500.0, direction=side,
                        tp_ratio=tp_ratio, **{wick_kw: wick},
                    )
                    risk = levels["risk_distance"]
                    sign = 1.0 if side == "BUY" else -1.0
                    self.assertAlmostEqual(
                        levels["take_profit"],
                        levels["entry_price"] + sign * tp_ratio * risk,
                        places=9,
                    )

    def test_a_one_point_five_ratio_produces_a_normal_target(self) -> None:
        """The ratio that the retired threshold made unenterable."""
        levels = entry_engine.calculate_entry_levels(
            entry_price=2500.0, sweep_wick_low=2490.0, direction="BUY", tp_ratio=1.5,
        )
        self.assertAlmostEqual(levels["reward_to_risk_ratio"], 1.5, places=9)
        self.assertGreater(levels["take_profit"], levels["entry_price"])
        self.assertNotIn("valid_rr", levels)


class ObservabilityIsPreserved(unittest.TestCase):
    """The geometry must still be reportable; only the verdict is gone."""

    def test_the_diagnostics_survive(self) -> None:
        levels = entry_engine.calculate_entry_levels(
            entry_price=2500.0, sweep_wick_low=2490.0, direction="BUY", tp_ratio=1.5,
        )
        for key in ("entry_price", "stop_loss", "take_profit",
                    "risk_distance", "reward_distance", "reward_to_risk_ratio"):
            self.assertIn(key, levels)
            self.assertIsNotNone(levels[key])

    def test_both_evaluators_still_report_the_geometry(self) -> None:
        for name in EVALUATORS:
            for key in ("risk_distance", "reward_distance", "reward_to_risk_ratio"):
                with self.subTest(function=name, key=key):
                    self.assertIsNotNone(_dict_value(_function(name), key))

    def test_the_decision_record_reports_geometry_not_a_verdict(self) -> None:
        """main_production must not claim an RR gate was evaluated."""
        import main_production

        source = Path(main_production.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        analyze = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "analyze_entry"
        )
        body = ast.unparse(analyze)
        self.assertNotIn("rr_valid", body)
        self.assertNotIn("valid_rr", body)
        self.assertIn("tp_ratio", body)


class NothingElseBecameEligible(unittest.TestCase):
    """D and E: only the one conjunct changed."""

    def test_scoring_no_longer_reads_a_verdict(self) -> None:
        source = inspect.getsource(entry_engine._score_entry_candidate)
        self.assertNotIn("valid_rr", source)

    def test_the_removed_scoring_bonus_could_never_have_decided_a_winner(self) -> None:
        """Why removing it cannot change which candidate is selected.

        The bonus was ``2.0 if candidate["valid_rr"]``, and ``valid_rr`` was
        ``rr >= 2.0`` where ``rr == tp_ratio``. Both candidates in a decision
        are evaluated at the same ``regime_tp_ratio``, so both received the
        same bonus, so it cancelled in every comparison. Asserted rather than
        argued: two candidates at one ratio score identically apart from the
        terms that are supposed to separate them.
        """
        for tp_ratio in (1.5, 2.0, 3.0):
            with self.subTest(tp_ratio=tp_ratio):
                pullback = {"raw_triggered": True, "entry_style": "PULLBACK",
                            "trigger_quality": 5.0, "reward_to_risk_ratio": tp_ratio}
                momentum = {"raw_triggered": True, "entry_style": "MOMENTUM",
                            "trigger_quality": 5.0, "reward_to_risk_ratio": tp_ratio}
                gap = (entry_engine._score_entry_candidate(pullback)
                       - entry_engine._score_entry_candidate(momentum))
                # The only asymmetry left is the 0.5 PULLBACK style bonus.
                self.assertAlmostEqual(gap, 0.5, places=9)

    def test_regime_and_style_rules_are_untouched(self) -> None:
        """The restriction Phase 6C froze must still be exactly as it was."""
        func = _function("get_entry_trigger")
        source = ast.unparse(func)
        self.assertIn("allowed_styles = ['MOMENTUM']", source)
        self.assertIn("allowed_styles = ['PULLBACK']", source)
        self.assertIn("MICRO_SCALP", source)
        self.assertIn("INTRADAY_SWING", source)

    def test_regime_tp_ratios_are_unchanged(self) -> None:
        self.assertEqual(
            REGIME_TP_RATIO,
            {"MICRO_SCALP": 1.5, "REGIME_SCALP": 2.0,
             "INTRADAY_SWING": 3.0, "DEAD_CALM": 1.5},
        )

    def test_no_minimum_rr_value_was_introduced(self) -> None:
        """G: the decision explicitly left the minimum UNRESOLVED."""
        source = SOURCE.read_text(encoding="utf-8")
        for token in ("MIN_RR", "MINIMUM_RR", "RR_THRESHOLD", "min_rr"):
            self.assertNotIn(token, source, f"a minimum-RR setting appeared: {token}")


class ASecondRrGateStillExistsAndIsUnchanged(unittest.TestCase):
    """``evaluate_entry_for_regime`` also tests ``rr``, and was NOT removed.

    Recorded here so it cannot be mistaken for the retired one, and so that
    "the RR gate is gone" is never read as "no RR comparison remains". This is
    a **different, pre-existing gate**: per-regime, conjoined with
    ``trigger_quality``, and applied after ``entry_triggered`` rather than as
    part of it. Phase 6I had no authority to touch it, and did not.

    Its consequence is material and is **UNRESOLVED**: the DEAD_CALM regime has
    no branch of its own, so it falls to the default ``rr >= 2.0``. With
    ``tp_ratio = 1.5`` that can never pass, so DEAD_CALM remains structurally
    unable to enter -- for the same tautological reason the retired gate did,
    through a different function.
    """

    THRESHOLDS = {
        "MICRO_SCALP": (5.0, 1.5),
        "REGIME_SCALP": (6.0, 2.0),
        "INTRADAY_SWING": (7.0, 2.5),
    }

    def _gate(self, regime: str, quality: float, rr: float) -> dict:
        return entry_engine.evaluate_entry_for_regime(
            {"trigger_quality": quality, "reward_to_risk_ratio": rr,
             "entry_triggered": True},
            {"regime": regime},
        )

    def test_the_per_regime_thresholds_are_exactly_as_before(self) -> None:
        for regime, (quality, rr) in self.THRESHOLDS.items():
            with self.subTest(regime=regime):
                self.assertTrue(self._gate(regime, quality, rr)["entry_allowed"])
                self.assertFalse(
                    self._gate(regime, quality - 0.1, rr)["entry_allowed"]
                )
                self.assertFalse(self._gate(regime, quality, rr - 0.1)["entry_allowed"])

    def test_micro_scalp_rr_is_satisfied_by_its_own_tp_ratio(self) -> None:
        """1.5 >= 1.5, so quality is the binding term for MICRO_SCALP."""
        self.assertGreaterEqual(REGIME_TP_RATIO["MICRO_SCALP"], self.THRESHOLDS["MICRO_SCALP"][1])
        self.assertTrue(self._gate("MICRO_SCALP", 5.0, REGIME_TP_RATIO["MICRO_SCALP"])["entry_allowed"])

    def test_dead_calm_still_cannot_pass_this_gate(self) -> None:
        """UNRESOLVED, and not introduced by Phase 6I.

        DEAD_CALM has no branch, so the default ``rr >= 2.0`` applies to a
        ``tp_ratio`` of 1.5. No quality can rescue it.
        """
        self.assertEqual(REGIME_TP_RATIO["DEAD_CALM"], 1.5)
        for quality in (5.0, 7.0, 10.0):
            with self.subTest(quality=quality):
                result = self._gate("DEAD_CALM", quality, REGIME_TP_RATIO["DEAD_CALM"])
                self.assertFalse(result["entry_allowed"])

    def test_micro_scalp_admission_turns_on_floating_point_noise(self) -> None:
        """Observation, pinned as-is. **Not endorsed, and not fixed here.**

        MICRO_SCALP's threshold is ``rr >= 1.5`` and its ``tp_ratio`` is 1.5,
        so ``rr`` lands exactly on the boundary and the comparison is decided by
        representation error. The candidate at 2026-08-06 08:00 was refused
        this way while three others at or just above 1.5 were admitted.

        The message is also misleading: it reports ``quality too low`` and
        prints ``rr=1.5``, when quality was 10.0 and it was ``rr`` that failed.

        Reproduced from the candidate's **own** geometry, as the Phase 6A probe
        recorded it, using the same arithmetic ``calculate_entry_levels``
        performs. Phase 6J §E identifies the mechanism.

        Phase 6I had no authority to change this gate, its threshold or its
        message. Pinned so the behaviour is visible rather than a surprise.
        """
        entry, stop, tp_ratio = 4257.775, 4255.11, 1.5
        risk = abs(entry - stop)
        take_profit = entry + risk * tp_ratio
        rr = abs(take_profit - entry) / risk

        self.assertEqual(rr, 1.4999999999998295)
        self.assertLess(rr, 1.5)
        self.assertAlmostEqual(rr, 1.5, places=12)
        result = self._gate("MICRO_SCALP", 10.0, rr)
        self.assertFalse(result["entry_allowed"])
        self.assertIn("quality too low", result["reason"])
        self.assertIn("rr=1.5", result["reason"])

    def test_the_loss_is_the_round_trip_through_take_profit(self) -> None:
        """E: a deterministic minimal reproduction of the mechanism.

        ``reward_distance`` is rebuilt as ``|take_profit - entry_price|`` after
        ``take_profit`` was formed by adding a small quantity to a large one.
        That addition rounds to the grid of the large value, so the low bits of
        the addend are lost and cannot be recovered by subtracting it back.

        The quantity was already in hand: ``risk_distance * tp_ratio`` divided
        by ``risk_distance`` is **exactly** the ratio, with no error at all.
        """
        entry, stop, tp_ratio = 4257.775, 4255.11, 1.5
        risk = abs(entry - stop)
        product = risk * tp_ratio

        round_tripped = abs((entry + product) - entry)
        self.assertNotEqual(product, round_tripped)
        self.assertAlmostEqual(product, round_tripped, places=11)

        self.assertEqual(product / risk, 1.5)             # no error
        self.assertLess(round_tripped / risk, 1.5)        # error, and it decides

        # The magnitude gap is what destroys the low bits.
        self.assertGreater(entry / product, 1000.0)

    def test_an_unconfirmed_trigger_is_still_refused_here(self) -> None:
        result = entry_engine.evaluate_entry_for_regime(
            {"trigger_quality": 10.0, "reward_to_risk_ratio": 3.0,
             "entry_triggered": False},
            {"regime": "MICRO_SCALP"},
        )
        self.assertFalse(result["entry_allowed"])
        self.assertEqual(result["reason"], "entry trigger not confirmed")


if __name__ == "__main__":
    unittest.main()


class U4RewardIsTheConstructionQuantity(unittest.TestCase):
    """U4: reward distance is the product, not a reconstruction.

    ``take_profit`` is built as ``entry ± risk_distance * tp_ratio``. Recovering
    the reward by subtracting ``entry_price`` back out adds a small number to a
    large one and loses the addend's low bits. The product is already in hand.

    **This is a representation repair, not a policy change.** No threshold,
    regime rule, stop construction, ``tp_ratio`` or gate semantic is altered by
    it. What the minimum RR should be is U9 and remains undecided.
    """

    def _levels(self, *, entry, wick, direction, tp_ratio):
        kw = {"sweep_wick_low": wick} if direction == "BUY" else {"sweep_wick_high": wick}
        return entry_engine.calculate_entry_levels(
            entry_price=entry, direction=direction, tp_ratio=tp_ratio, **kw
        )

    def test_reward_distance_is_risk_times_ratio(self) -> None:
        for direction, entry, wick in (
            ("BUY", 2500.0, 2490.0), ("SELL", 2500.0, 2512.0),
            ("BUY", 4257.775, 4250.0), ("SELL", 1850.0, 1861.0),
        ):
            for tp_ratio in (1.5, 2.0, 2.5, 3.0):
                with self.subTest(direction=direction, entry=entry, tp_ratio=tp_ratio):
                    levels = self._levels(
                        entry=entry, wick=wick, direction=direction, tp_ratio=tp_ratio
                    )
                    self.assertEqual(
                        levels["reward_distance"],
                        levels["risk_distance"] * tp_ratio,
                        "reward_distance must be the product, exactly",
                    )

    def test_non_integer_ratios_behave_the_same(self) -> None:
        for tp_ratio in (1.25, 1.75, 2.33, 2.75, 3.5):
            with self.subTest(tp_ratio=tp_ratio):
                levels = self._levels(
                    entry=4257.775, wick=4250.0, direction="BUY", tp_ratio=tp_ratio
                )
                self.assertEqual(
                    levels["reward_distance"], levels["risk_distance"] * tp_ratio
                )
                self.assertAlmostEqual(
                    levels["reward_to_risk_ratio"], tp_ratio, places=12
                )

    def test_take_profit_is_unchanged_by_the_repair(self) -> None:
        """U4 touches the reward only. The target construction is untouched."""
        for direction, entry, wick, sign in (
            ("BUY", 2500.0, 2490.0, 1.0), ("SELL", 2500.0, 2512.0, -1.0),
        ):
            with self.subTest(direction=direction):
                levels = self._levels(
                    entry=entry, wick=wick, direction=direction, tp_ratio=3.0
                )
                self.assertAlmostEqual(
                    levels["take_profit"],
                    levels["entry_price"] + sign * levels["risk_distance"] * 3.0,
                    places=12,
                )

    def test_the_zero_risk_contract_is_unchanged(self) -> None:
        """``rr`` is 0 when risk is not positive. Existing semantics, not new.

        Reached when the stop anchor lands exactly on the entry: for a BUY the
        stop is ``wick - 3.0``, so a wick 3.0 above the entry gives a zero-width
        stop. U4 changes ``reward_distance`` from ``0.0`` (the old subtraction)
        to ``0.0`` (``0.0 * tp_ratio``), and the guarded division still yields
        ``0``. **No new semantics are introduced.**
        """
        levels = entry_engine.calculate_entry_levels(
            entry_price=2500.0, sweep_wick_low=2503.0, direction="BUY", tp_ratio=3.0,
        )
        self.assertEqual(levels["risk_distance"], 0.0)
        self.assertEqual(levels["reward_distance"], 0.0)
        self.assertEqual(levels["reward_to_risk_ratio"], 0)

    def test_a_missing_anchor_still_falls_back_to_the_atr_stop(self) -> None:
        """Unchanged by U4, and pinned because it is easily mistaken for the
        zero-risk path: with no wick and no structure the stop comes from ATR."""
        levels = entry_engine.calculate_entry_levels(
            entry_price=2500.0, direction="BUY", tp_ratio=3.0,
        )
        self.assertEqual(levels["risk_distance"], 30.0)
        self.assertEqual(levels["reward_distance"], 90.0)
        self.assertEqual(levels["reward_to_risk_ratio"], 3.0)


class U4TheBoundaryCandidate(unittest.TestCase):
    """The 2026-08-06 MICRO_SCALP candidate, before and after U4."""

    ENTRY, STOP, TP_RATIO = 4257.775, 4255.11, 1.5

    def test_the_old_reconstruction_fell_below_the_threshold(self) -> None:
        """Preserved as history: what the lossy form produced."""
        risk = abs(self.ENTRY - self.STOP)
        old = abs((self.ENTRY + risk * self.TP_RATIO) - self.ENTRY) / risk
        self.assertEqual(old, 1.4999999999998295)
        self.assertLess(old, 1.5)

    def test_the_construction_quantity_reaches_the_threshold(self) -> None:
        """After U4 the same candidate evaluates from the product."""
        risk = abs(self.ENTRY - self.STOP)
        new = (risk * self.TP_RATIO) / risk
        self.assertEqual(new, 1.5)
        self.assertGreaterEqual(new, 1.5)

    def test_the_gate_now_admits_it_on_rr(self) -> None:
        """Its quality was already 10.0; rr was the failing term."""
        risk = abs(self.ENTRY - self.STOP)
        rr = (risk * self.TP_RATIO) / risk
        result = entry_engine.evaluate_entry_for_regime(
            {"trigger_quality": 10.0, "reward_to_risk_ratio": rr,
             "entry_triggered": True},
            {"regime": "MICRO_SCALP"},
        )
        self.assertTrue(result["entry_allowed"])

    def test_the_boundary_is_narrowed_but_not_removed(self) -> None:
        """**U4 does not make the comparison safe.**

        ``(R * k) / R`` is not exactly ``k`` for every ``R``: it differs by one
        ulp for a substantial minority of values. U4 shrinks the error from
        ~1.7e-13 to ~2e-16, roughly three orders of magnitude, but MICRO_SCALP's
        threshold still equals its own ``tp_ratio``, so a candidate can still
        land one ulp below it.

        Pinned so the repair is not mistaken for a fix to the threshold
        coincidence, which is U9.
        """
        inexact = [
            r for r in (45.365599541799085, 212.26534937936555, 473.85499413907826)
            if (r * 1.5) / r != 1.5
        ]
        self.assertEqual(len(inexact), 3, "expected these to be inexact")
        self.assertTrue(any((r * 1.5) / r < 1.5 for r in inexact),
                        "at least one rounds down, i.e. would still be rejected")
