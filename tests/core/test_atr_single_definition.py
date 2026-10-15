"""One ATR definition, one bar convention, and no fabricated volatility.

These are the structural success criteria of
`research/atr_bar_convention_spec.md`, which was committed before the migration.
None of them is a performance figure.

The defects they close:

**A — four incompatible ATR definitions.** `core/indicators.atr_wilder` is
canonical. `sweep_detector._estimate_m15_atr` (A3) computed
`close.diff().abs().rolling(14).mean()`, a mean absolute close-to-close change
which is **not** an ATR -- it could not see intrabar range at all, and measured
over 100,020 M15 bars it understated true Wilder ATR by ~2.1x (median $1.516
against $3.084). `pullback_detector._estimate_recent_atr` (A2) had correct true
range but SMA smoothing. `main_production`'s `h1_atr` (A4) used
`mean(high - low)`, ignoring gaps, **and** an SMA.

A3 mattered more than it looks: `sweep_min` is
`max(2.5 pips, m15_atr * 0.12)`, and once U8's unit fix moved that floor from
$2.50 to $0.25 the ATR term began to bind -- so a non-ATR set the busiest gate
in the system.

**A2/A3 also fabricated readings**, returning `default=10.0` / `default=15.0` on
a short frame or any exception. At `x0.12` a default of 15.0 is a $1.80 sweep
floor, seven times the pip floor, invented from no data.

**B — six disagreeing bar accesses.** `get_market_data(closed_only=True)` drops
MT5's forming bar on all three of its fetch paths, so `iloc[-1]` **is** the last
closed bar. Sites using `iloc[-2]` were one bar stale and
`pullback_detector`'s `recent.iloc[:-1]` was a double-drop, two bars stale.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules in the strategy path that must not define their own volatility.
STRATEGY_MODULES = (
    "sweep_detector.py",
    "pullback_detector.py",
    "entry_engine.py",
    "main_production.py",
)


def real_bars(timeframe: str = "M15", count: int = 400) -> pd.DataFrame:
    """A slice of the frozen export, so these test real data, not a fixture."""
    frame = pd.read_csv(
        REPO_ROOT / "data" / "research_v1" / "bars" / f"XAUUSD_{timeframe}.csv")
    frame.columns = [column.lower() for column in frame.columns]
    return frame.tail(count).reset_index(drop=True)


class EveryAtrIsTheCanonicalOneTests(unittest.TestCase):
    """A1–A4 collapse onto `core.indicators.atr_wilder`."""

    def test_a3_sweep_detector_agrees_with_atr_wilder(self) -> None:
        import sweep_detector
        from core.indicators import atr_wilder

        bars = real_bars("M15")
        self.assertAlmostEqual(
            sweep_detector._estimate_m15_atr(bars),
            float(atr_wilder(bars, period=14).value.value),
            places=9,
        )

    def test_a2_pullback_detector_agrees_with_atr_wilder(self) -> None:
        import pullback_detector
        from core.indicators import atr_wilder

        bars = real_bars("M15")
        self.assertAlmostEqual(
            pullback_detector._estimate_recent_atr(bars),
            float(atr_wilder(bars, period=14).value.value),
            places=9,
        )

    def test_a2_and_a3_agree_with_each_other(self) -> None:
        """They were two different statistics on the same bars."""
        import pullback_detector
        import sweep_detector

        bars = real_bars("M15")
        self.assertAlmostEqual(
            sweep_detector._estimate_m15_atr(bars),
            pullback_detector._estimate_recent_atr(bars),
            places=9,
        )

    def test_a1_pandas_ta_agrees_with_atr_wilder(self) -> None:
        """A1 was already correct. Asserted rather than edited, per the spec."""
        from core.indicators import atr_wilder
        from indicators import calculate_indicators

        bars = real_bars("H1", 300).copy()
        time_column = next(c for c in bars.columns if "time" in c or "date" in c)
        bars["time"] = pd.to_datetime(bars[time_column])
        reported = calculate_indicators(bars).get("atr_14")
        self.assertIsNotNone(reported)
        self.assertAlmostEqual(
            float(reported), float(atr_wilder(bars, period=14).value.value),
            places=6,
        )


class NoModuleRollsItsOwnAtrTests(unittest.TestCase):
    """Structural: the surrogates must not come back.

    Checked against the AST rather than by text search, so a mention in a
    comment -- including the comments in this file's own docstring explaining
    what the surrogates were -- cannot trigger it.
    """

    def _calls(self, filename: str) -> list[str]:
        source = (REPO_ROOT / filename).read_text(encoding="utf-8")
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                found.append(node.func.attr)
        return found

    def test_no_strategy_module_calls_rolling_on_a_diff(self) -> None:
        """`close.diff().abs().rolling(14).mean()` was A3 exactly."""
        for filename in STRATEGY_MODULES:
            source = (REPO_ROOT / filename).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "rolling"):
                    continue
                # Walk the receiver chain looking for a .diff() beneath it.
                chain = [n.func.attr for n in ast.walk(node.func.value)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute)]
                self.assertNotIn(
                    "diff", chain,
                    f"{filename}: a rolling mean over a diff is an ATR "
                    f"surrogate, not an ATR -- use core.indicators.atr_wilder",
                )

    def test_strategy_modules_import_the_canonical_atr(self) -> None:
        """Those that compute an ATR at all must get it from core."""
        for filename in ("sweep_detector.py", "pullback_detector.py",
                         "main_production.py"):
            source = (REPO_ROOT / filename).read_text(encoding="utf-8")
            imported = {
                alias.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom)
                and node.module == "core.indicators"
                for alias in node.names
            }
            self.assertIn("atr_wilder", imported, f"{filename}")


class UnavailableAtrDeclinesTests(unittest.TestCase):
    """No fabricated volatility. A short frame must yield None, not a default."""

    def test_sweep_detector_returns_none_on_a_short_frame(self) -> None:
        import sweep_detector

        self.assertIsNone(sweep_detector._estimate_m15_atr(real_bars("M15", 3)))

    def test_pullback_detector_returns_none_on_a_short_frame(self) -> None:
        import pullback_detector

        self.assertIsNone(
            pullback_detector._estimate_recent_atr(real_bars("M15", 3)))

    def test_neither_estimator_takes_a_default_argument(self) -> None:
        """`default=15.0` and `default=10.0` are how the fabrication happened."""
        import inspect

        import pullback_detector
        import sweep_detector

        for function in (sweep_detector._estimate_m15_atr,
                         pullback_detector._estimate_recent_atr):
            parameters = inspect.signature(function).parameters
            self.assertNotIn(
                "default", parameters,
                f"{function.__qualname__} must not be able to invent a "
                f"volatility reading",
            )

    def test_none_input_returns_none(self) -> None:
        import pullback_detector
        import sweep_detector

        self.assertIsNone(sweep_detector._estimate_m15_atr(None))
        self.assertIsNone(pullback_detector._estimate_recent_atr(None))

    def test_the_sweep_gate_declines_rather_than_guessing(self) -> None:
        """A3's caller must not proceed with no ATR."""
        import sweep_detector

        result = sweep_detector.detect_sweep(real_bars("M15", 3), 4000.0, "BUY")
        self.assertFalse(result["sweep_confirmed"])


class BarConventionIsExplicitTests(unittest.TestCase):
    """B1–B6 read the bar they claim to read."""

    def test_b1_is_the_only_current_bar_read_from_minus_two(self) -> None:
        """B1 is a recorded UNRESOLVED exception; nothing else may join it.

        This asserted that NO site assigns `iloc[-2]` to a variable named
        `current`. B1 was then reverted as UNRESOLVED -- its intent is
        two-sided and both integration fixtures encode `iloc[-2]` -- so the
        assertion is narrowed to "B1 and only B1", rather than deleted.

        A new instance of the same mistake still fails here. And B1 must keep
        its UNRESOLVED record, so the exception cannot quietly become the norm.
        """
        offenders = []
        for filename in STRATEGY_MODULES:
            source = (REPO_ROOT / filename).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Assign):
                    continue
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if not targets:
                    continue
                text = ast.unparse(node.value)
                if "iloc[-2]" in text and any(
                    name in ("current", "confirmed_m5_close",
                             "confirmed_m5_price", "confirmed_entry_price")
                    for name in targets
                ):
                    offenders.append((filename, tuple(targets)))

        self.assertEqual(
            offenders, [("entry_engine.py", ("current",))],
            "exactly one such site is permitted -- B1 in "
            "entry_engine.detect_rejection_candle, recorded UNRESOLVED. Any "
            "other is the defect B3/B4 fixed: a bar named 'current' or "
            "'confirmed' that is not the last closed bar.",
        )

    def test_b1_carries_its_unresolved_record(self) -> None:
        """The exception above is only acceptable while it is documented."""
        source = (REPO_ROOT / "entry_engine.py").read_text(encoding="utf-8")
        block = source[source.index("def detect_rejection_candle"):]
        block = block[:block.index("def detect_momentum_confirmation")]
        self.assertIn("UNRESOLVED", block)
        self.assertIn("B1", block)
        # The evidence on both sides must stay with it, so a future reader does
        # not have to rediscover why it was left alone.
        self.assertIn("detect_displacement_candle", block)
        self.assertIn("TRIGGER_BARS", block)

    def test_the_double_drop_is_gone(self) -> None:
        """B5: `recent.iloc[:-1]` removed a real bar from a closed-only frame."""
        source = (REPO_ROOT / "pullback_detector.py").read_text(encoding="utf-8")
        self.assertNotIn("recent.iloc[:-1]", source)
        self.assertIn("closed_bars(recent)", source)

    def test_migrated_modules_use_the_canonical_helpers(self) -> None:
        for filename, expected in (
            ("entry_engine.py", {"closed_bars", "last_closed_bar"}),
            ("pullback_detector.py", {"closed_bars"}),
            ("main_production.py", {"last_closed_bar"}),
        ):
            source = (REPO_ROOT / filename).read_text(encoding="utf-8")
            imported = {
                alias.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.ImportFrom) and node.module == "core.candles"
                for alias in node.names
            }
            self.assertTrue(
                expected <= imported,
                f"{filename}: expected {expected}, imported {imported}",
            )

    def test_closed_bars_is_idempotent_on_a_closed_only_frame(self) -> None:
        """The property that makes B5's bug unrepeatable."""
        from core.candles import closed_bars

        bars = real_bars("M15", 50)
        once = closed_bars(bars)
        twice = closed_bars(closed_bars(bars))
        self.assertEqual(len(once), len(bars))
        self.assertEqual(len(twice), len(bars))


class TheFetchPremiseHoldsTests(unittest.TestCase):
    """B1–B6 rest on closed_only dropping the forming bar. Pin that premise.

    Verified in the source rather than assumed, because the whole B-section is
    wrong if any fetch path returns a frame that still contains bar 0 -- then
    `iloc[-1]` would mean different things depending on which path fired.
    """

    def test_closed_only_defaults_to_true(self) -> None:
        import inspect

        import mt5_handler

        parameters = inspect.signature(mt5_handler.get_market_data).parameters
        self.assertIs(parameters["closed_only"].default, True)

    def test_every_fetch_path_honours_closed_only(self) -> None:
        source = (REPO_ROOT / "mt5_handler.py").read_text(encoding="utf-8")
        body = source[source.index("def get_market_data"):]
        body = body[:body.index("\ndef ", 10)]
        # Primary and last-resort offset the start position; the range fallback
        # trims the trailing forming bar.
        self.assertEqual(
            body.count("start_pos = 1 if closed_only else 0"), 2,
            "both copy_rates_from_pos paths must offset by closed_only")
        self.assertIn("if closed_only and len(data) > 0:", body)
        self.assertIn("data.iloc[:-1]", body)


if __name__ == "__main__":
    unittest.main()
