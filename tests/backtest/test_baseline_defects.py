"""Guards for the defect evidence the Phase 3A baseline reports.

Two things are checked here, and neither of them changes the strategy.

**The mirror cannot drift.** ``backtest.baseline`` carries a copy of the
``tp_ratio`` literals that ``entry_engine.detect_regime`` assigns, because those
literals live inside an ``if``/``elif`` chain and cannot be imported. A stale
copy would make the baseline's defect report quietly wrong, so the real values
are recovered from ``entry_engine``'s AST and compared.

**The tautology is real.** The baseline claims that ``valid_rr`` tests a config
constant rather than the trade. That claim is proved directly against the
production function, for every regime, rather than asserted in prose.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path

import entry_engine
from backtest.baseline import REGIME_TP_RATIO, VALID_RR_THRESHOLD

ENTRY_ENGINE_SOURCE = Path(entry_engine.__file__)


def _regime_tp_ratios_from_source() -> dict[str, float]:
    """Recover ``regime -> tp_ratio`` from ``detect_regime``'s AST.

    Both names are assigned as plain statements in the same branch body, so each
    branch is scanned for a ``regime = "<name>"`` and a ``tp_ratio = <number>``
    and the two are paired. Branches that set only one of them are ignored.

    Returns:
        The mapping as the source actually defines it.
    """
    tree = ast.parse(ENTRY_ENGINE_SOURCE.read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "detect_regime"
    )

    found: dict[str, float] = {}

    def scan(body: list[ast.stmt]) -> None:
        regime: str | None = None
        ratio: float | None = None
        for statement in body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                value = statement.value
                if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
                    if target.id == "regime" and isinstance(value.value, str):
                        regime = value.value
                    elif target.id == "tp_ratio" and isinstance(value.value, (int, float)):
                        ratio = float(value.value)
            elif isinstance(statement, ast.If):
                scan(statement.body)
                scan(statement.orelse)
            elif isinstance(statement, ast.Try):
                # detect_regime wraps its whole if/elif chain in a try block.
                # ``handlers`` is deliberately skipped: the except path returns a
                # DEAD_CALM dict carrying tp_ratio 2.0, which is the error
                # fallback, not the regime's configured ratio.
                scan(statement.body)
                scan(statement.orelse)
        if regime is not None and ratio is not None:
            found[regime] = ratio

    scan(function.body)
    return found


class TestRegimeTpRatioMirror(unittest.TestCase):
    """The baseline's copy of the regime constants must match the source."""

    def test_mirror_matches_entry_engine_source(self) -> None:
        self.assertEqual(_regime_tp_ratios_from_source(), REGIME_TP_RATIO)

    def test_the_retired_threshold_is_gone_from_the_source(self) -> None:
        """``valid_rr = rr >= 2.0`` must no longer exist.

        This test previously recovered the ``2.0`` from the assignment to prove
        the mirror was honest. The assignment is retired (Phase 6I), so the
        test now proves its absence -- the same evidence, inverted. The mirror
        constant is kept in ``backtest.baseline`` as the historical value the
        defect report refers to, not as a live threshold.
        """
        tree = ast.parse(ENTRY_ENGINE_SOURCE.read_text(encoding="utf-8"))
        assignments = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "valid_rr"
        ]
        self.assertEqual(
            assignments, [],
            "entry_engine assigns valid_rr again; the retired RR gate is back",
        )
        self.assertEqual(VALID_RR_THRESHOLD, 2.0, "historical value, for the report")


class TestRrIsATautology(unittest.TestCase):
    """E9: the reported RR restates ``tp_ratio`` and measures nothing.

    The tautology is unchanged by Phase 6I and is the reason the gate was
    retired: ``take_profit`` is built as ``risk_distance * tp_ratio``, so
    ``rr`` is ``tp_ratio`` whatever the price or stop. Removing the gate did
    not change that arithmetic, and these tests prove it still holds.
    """

    def test_reported_rr_equals_tp_ratio_for_every_regime(self) -> None:
        for regime, tp_ratio in REGIME_TP_RATIO.items():
            for entry_price, wick in ((2500.0, 2490.0), (4000.0, 3997.5), (1850.0, 1801.0)):
                with self.subTest(regime=regime, entry=entry_price):
                    levels = entry_engine.calculate_entry_levels(
                        entry_price=entry_price,
                        sweep_wick_low=wick,
                        direction="BUY",
                        tp_ratio=tp_ratio,
                    )
                    self.assertAlmostEqual(
                        levels["reward_to_risk_ratio"], tp_ratio, places=9,
                        msg="RR should be independent of price and stop distance",
                    )

    def test_no_rr_verdict_is_reported(self) -> None:
        """The geometry is reported; the verdict is not.

        A field named ``valid_rr`` would claim an independent feasibility test
        was performed. None is, so none is reported.
        """
        for regime, tp_ratio in REGIME_TP_RATIO.items():
            with self.subTest(regime=regime):
                levels = entry_engine.calculate_entry_levels(
                    entry_price=2500.0,
                    sweep_wick_low=2490.0,
                    direction="BUY",
                    tp_ratio=tp_ratio,
                )
                self.assertNotIn("valid_rr", levels)
                for diagnostic in ("risk_distance", "reward_distance",
                                   "reward_to_risk_ratio"):
                    self.assertIn(diagnostic, levels)

    def test_holds_for_sell_as_well(self) -> None:
        for regime, tp_ratio in REGIME_TP_RATIO.items():
            with self.subTest(regime=regime):
                levels = entry_engine.calculate_entry_levels(
                    entry_price=2500.0,
                    sweep_wick_high=2512.0,
                    direction="SELL",
                    tp_ratio=tp_ratio,
                )
                self.assertAlmostEqual(levels["reward_to_risk_ratio"], tp_ratio, places=9)
                self.assertNotIn("valid_rr", levels)


class TestEntryTriggerNoLongerRequiresValidRr(unittest.TestCase):
    """E10 retired: ``entry_triggered`` is the raw trigger and nothing else."""

    def test_entry_triggered_is_not_conjoined_with_any_rr_verdict(self) -> None:
        """Inverts the test that pinned the defect.

        It required at least two ``... and entry_levels["valid_rr"]``
        conjunctions, one per evaluation path. Zero are permitted now.
        """
        tree = ast.parse(ENTRY_ENGINE_SOURCE.read_text(encoding="utf-8"))
        conjunctions = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.BoolOp)
            and isinstance(node.op, ast.And)
            and any(
                isinstance(value, ast.Subscript)
                and isinstance(value.slice, ast.Constant)
                and value.slice.value in ("valid_rr", "rr_valid")
                for value in node.values
            )
        ]
        self.assertEqual(
            conjunctions, [],
            "entry_triggered is gated on an RR verdict again",
        )

    def test_no_rr_threshold_comparison_gates_an_entry(self) -> None:
        """G: the retired threshold is not reused silently elsewhere.

        Any ``>=`` against a bare float inside the entry-evaluation functions
        would be a candidate for a reinstated gate, so the RR-shaped ones are
        enumerated and required to be absent.
        """
        tree = ast.parse(ENTRY_ENGINE_SOURCE.read_text(encoding="utf-8"))
        offenders = []
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            if func.name not in ("calculate_entry_levels", "_evaluate_pullback_entry",
                                 "_evaluate_momentum_entry", "get_entry_trigger"):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Compare):
                    continue
                left = ast.unparse(node.left)
                if "reward_to_risk" in left or left in ("rr", "reward_distance"):
                    offenders.append(f"{func.name}: {ast.unparse(node)}")
        self.assertEqual(
            offenders, [],
            "an RR quantity is being compared to a threshold inside the entry "
            f"path, which is the retired gate returning: {offenders}",
        )


class TestLondonNewYorkIsADeadSessionLabel(unittest.TestCase):
    """D8: a session name that cannot occur -- **partially closed by D-6N-1**.

    **Original defect.** ``detect_regime`` admitted MICRO_SCALP when the kill
    zone was active *or* the session was one of ``Asian``, ``London``,
    ``LondonNewYork``. The last of those is never produced:
    ``risk_manager.get_current_session`` returns only ``Asian``, ``London``,
    ``NewYork``, ``Dead`` or ``Closed``. The practical effect was that during
    the New York session -- the most active gold hours -- MICRO_SCALP was
    reachable only when the kill zone happened to be open.

    Established behaviourally, by enumerating every hour of every weekday under
    a frozen clock, rather than by reading the function.

    **Resolution.** D-6N-1 removed the entire session disjunct from
    ``detect_regime``, so the dead label no longer gates anything. That part of
    D8 is closed. The label still exists at two other sites -- ``config.py``
    (dead configuration) and ``main_production.get_session_name`` (a map entry
    for a value that never arrives) -- so **D8 is not closed repo-wide**, and
    those sites are pinned below rather than forgotten.
    """

    def test_session_function_never_returns_it(self) -> None:
        import risk_manager

        from backtest.clock_patch import frozen_clock

        produced = set()
        # A full week, hour by hour, so weekdays and weekend are both covered.
        for day in range(5, 12):          # 2026-01-05 is a Monday
            for hour in range(24):
                moment = datetime(2026, 1, day, hour, 30, tzinfo=timezone.utc)
                with frozen_clock(moment):
                    produced.add(str(risk_manager.get_current_session()))

        self.assertNotIn("LondonNewYork", produced)
        self.assertEqual(
            produced, {"Asian", "London", "NewYork", "Dead", "Closed"},
            "the set of reachable session names changed; revisit the dead-label claim",
        )

    def test_detect_regime_no_longer_references_it(self) -> None:
        """D-6N-1 removed the session disjunct, taking the dead label with it.

        This assertion was inverted by that change, deliberately. Before it, the
        test asserted the label was **still present** and carried the note "if
        this stops matching, the defect was fixed and D8 can be closed". It has
        stopped matching, so it is closed here -- for ``entry_engine`` only.
        """
        source = ENTRY_ENGINE_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("LondonNewYork", source)

    def test_the_label_survives_outside_the_regime_classifier(self) -> None:
        """D8 is not closed repo-wide: two sites still expect a dead value."""
        root = ENTRY_ENGINE_SOURCE.parent
        self.assertIn(
            '"LondonNewYork": 0.70', (root / "config.py").read_text(encoding="utf-8")
        )
        self.assertIn(
            '"LondonNewYork": "LONDON"',
            (root / "main_production.py").read_text(encoding="utf-8"),
        )


class TestStopBufferIsAppliedInPriceUnits(unittest.TestCase):
    """Q6 / U1: the 'buffer_pips' default is subtracted from a price directly."""

    def test_buffer_is_three_price_units_not_three_pips(self) -> None:
        anchor = entry_engine._select_stop_anchor("BUY", sweep_wick_low=2511.73)
        self.assertAlmostEqual(anchor, 2508.73, places=9)

    def test_default_is_still_three(self) -> None:
        default = inspect.signature(entry_engine._select_stop_anchor).parameters["buffer_pips"]
        self.assertEqual(default.default, 3.0)


if __name__ == "__main__":
    unittest.main()
