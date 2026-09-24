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
        representation error. A real candidate from the verified dataset
        (2026-08-06 08:00) computed ``rr = 1.4999999999999196`` -- below 1.5 by
        about 8e-14 -- and was refused, while three others at or just above 1.5
        were admitted.

        The message is also misleading: it reports ``quality too low`` and
        prints ``rr=1.5``, when quality was 10.0 and it was ``rr`` that failed.

        Phase 6I has no authority to change this gate, its threshold or its
        message. It is pinned so the behaviour is visible rather than a
        surprise in a later measurement.
        """
        levels = entry_engine.calculate_entry_levels(
            entry_price=4257.775, sweep_wick_low=4255.11,
            direction="BUY", tp_ratio=1.5,
        )
        rr = levels["reward_to_risk_ratio"]
        self.assertLess(rr, 1.5)
        self.assertAlmostEqual(rr, 1.5, places=12)
        result = self._gate("MICRO_SCALP", 10.0, rr)
        self.assertFalse(result["entry_allowed"])
        self.assertIn("quality too low", result["reason"])
        self.assertIn("rr=1.5", result["reason"])

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
