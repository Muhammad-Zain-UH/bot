"""`raw_bias_strength` is diagnostic only and changes nothing.

`bias_strength` is `min(10.0, |ema20 - ema50| / ema_threshold)`. The forensic
study measured 36.2% of evaluated decisions sitting exactly at that clamp, with
the pre-clip ratio running to 31.56 -- so one value was standing for a 3.1x
range, and the information was unrecoverable because `confidence_engine`
re-clamps at 10 as well.

`raw_bias_strength` carries the pre-clip ratio so that range is observable. It is
**never read by any consumer**, which is what these tests pin.

**The exact relationship, stated precisely.** `bias_strength == min(10, raw)`
holds on the H1 fast path always, and on the H4 path only when neither the
daily-midpoint penalty (-2.0) nor the two-candle penalty (-1.5) fires, and when
the bias is not NEUTRAL. The H4 path can also force NEUTRAL (strength 0.0) when
both penalties fire. Those are pre-existing behaviours; this field does not
change them, and the tests below assert the real contract rather than a tidier
one that would be false.

Thresholds differ per path and are unchanged by this work:
    H1 fast: ema_threshold = max(2.0, atr_14 * 0.12)
    H4:      ema_threshold = max(3.0, atr_14 * 0.20)
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import bias_engine
import confidence_engine
from bias_engine import _calculate_ema_threshold, get_fast_bias, get_h4_bias

REPO_ROOT = Path(__file__).resolve().parents[2]


def _h1_frame(n: int = 80, start: float = 4000.0, drift: float = 0.0) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="1h", tz="UTC")
    close = start + np.arange(n) * drift
    return pd.DataFrame({
        "time": idx, "open": close, "high": close + 2.0,
        "low": close - 2.0, "close": close, "tick_volume": 100.0,
    })


class RawIsExactlyThePreClipRatio(unittest.TestCase):
    """Requirement 1: raw == |ema20 - ema50| / ema_threshold."""

    def test_h1_fast_path_matches_the_formula(self) -> None:
        for atr, e20, e50 in ((20.0, 4100.0, 4000.0), (12.0, 4000.0, 4050.0),
                              (30.0, 4000.5, 4000.0)):
            with self.subTest(atr=atr, e20=e20, e50=e50):
                ind = {"ema_20": e20, "ema_50": e50, "close": e20,
                       "high": e20 + 1, "low": e20 - 1, "atr_14": atr}
                res = get_fast_bias(ind, h1_data=_h1_frame())
                thr = _calculate_ema_threshold(atr, floor=2.0, atr_ratio=0.12)
                self.assertAlmostEqual(
                    res["raw_bias_strength"], abs(e20 - e50) / thr, places=9
                )

    def test_the_h1_threshold_parameters_are_unchanged(self) -> None:
        """The ratio is only meaningful against the threshold that produced it."""
        src = inspect.getsource(get_fast_bias)
        self.assertIn("_calculate_ema_threshold(atr_14, floor=2.0, atr_ratio=0.12)", src)


class BiasStrengthIsStillTheClampedRatio(unittest.TestCase):
    """Requirement 2, asserted where the relationship actually holds."""

    def test_h1_strength_is_exactly_min_ten_of_raw(self) -> None:
        for atr, e20, e50 in ((20.0, 4100.0, 4000.0),   # far above the clamp
                              (20.0, 4009.0, 4000.0),   # below the clamp
                              (12.0, 4000.0, 4050.0)):  # bearish, above the clamp
            with self.subTest(e20=e20, e50=e50):
                ind = {"ema_20": e20, "ema_50": e50, "close": e20,
                       "high": e20 + 1, "low": e20 - 1, "atr_14": atr}
                res = get_fast_bias(ind, h1_data=_h1_frame())
                if res["bias"] == "NEUTRAL":
                    continue          # NEUTRAL zeroes strength by design
                self.assertAlmostEqual(
                    res["bias_strength"], min(10.0, res["raw_bias_strength"]), places=9
                )

    def test_the_clamp_itself_is_untouched(self) -> None:
        ind = {"ema_20": 4400.0, "ema_50": 4000.0, "close": 4400.0,
               "high": 4401.0, "low": 4399.0, "atr_14": 20.0}
        res = get_fast_bias(ind, h1_data=_h1_frame())
        self.assertEqual(res["bias_strength"], 10.0)
        self.assertGreater(res["raw_bias_strength"], 10.0)

    def test_the_h4_penalty_exception_is_real_and_documented(self) -> None:
        """On H4, strength may be BELOW min(10, raw). Pinned, not glossed over."""
        src = inspect.getsource(bias_engine.calculate_h4_ema_bias)
        self.assertIn("strength = max(0.0, strength - 2.0)", src)
        self.assertIn("strength = max(0.0, strength - 1.5)", src)


class NoConsumerReadsTheNewField(unittest.TestCase):
    """Requirement 3: raw > 10 cannot alter anything, because nothing reads it."""

    def test_no_production_module_reads_raw_bias_strength(self) -> None:
        offenders = []
        for path in REPO_ROOT.glob("*.py"):
            if path.name == "bias_engine.py":
                continue
            if "raw_bias_strength" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        for sub in ("core", "execution", "backtest", "data", "utils"):
            for path in (REPO_ROOT / sub).rglob("*.py"):
                if "raw_bias_strength" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(
            offenders, [],
            "raw_bias_strength is diagnostic only; a consumer would make it "
            "behavioural and this instrumentation would no longer be neutral",
        )

    def test_confidence_is_insensitive_to_values_above_ten(self) -> None:
        """Even if it were passed through, confidence re-clamps at 10."""
        kw = dict(structure_confidence=6.0, sweep_quality=7.0, poi_score=70.0,
                  session="LONDON", regime="MICRO_SCALP")
        at_ten = confidence_engine.get_confidence_engine(bias_strength=10.0, **kw)
        way_over = confidence_engine.get_confidence_engine(bias_strength=31.56, **kw)
        self.assertEqual(at_ten["final_score"], way_over["final_score"])
        self.assertEqual(at_ten["grade"], way_over["grade"])

    def test_the_a_plus_checklist_is_insensitive_too(self) -> None:
        kw = dict(structure_valid=True, sweep_quality=8.0, poi_score=80.0,
                  has_fib_confluence=True, session="LONDON")
        a = confidence_engine.check_a_plus_checklist(bias_strength=10.0, **kw)
        b = confidence_engine.check_a_plus_checklist(bias_strength=31.56, **kw)
        self.assertEqual(a["checks_list"], b["checks_list"])
        self.assertEqual(a["checks_passed"], b["checks_passed"])
        self.assertEqual(a["qualifies_for_a_plus"], b["qualifies_for_a_plus"])


class DirectionAndShapeAreUnchanged(unittest.TestCase):
    """Requirements 4 and 5: same decisions, same keys plus exactly one."""

    def test_the_bias_label_is_unaffected(self) -> None:
        for e20, e50, expected in ((4100.0, 4000.0, "BULLISH"),
                                   (4000.0, 4100.0, "BEARISH"),
                                   (4000.1, 4000.0, "NEUTRAL")):
            with self.subTest(expected=expected):
                ind = {"ema_20": e20, "ema_50": e50, "close": e20,
                       "high": e20 + 1, "low": e20 - 1, "atr_14": 20.0}
                self.assertEqual(get_fast_bias(ind, h1_data=_h1_frame())["bias"], expected)

    def test_neutral_still_reports_zero_strength_while_raw_is_preserved(self) -> None:
        ind = {"ema_20": 4000.1, "ema_50": 4000.0, "close": 4000.1,
               "high": 4001.0, "low": 3999.0, "atr_14": 20.0}
        res = get_fast_bias(ind, h1_data=_h1_frame())
        self.assertEqual(res["bias"], "NEUTRAL")
        self.assertEqual(res["bias_strength"], 0.0)
        self.assertGreater(res["raw_bias_strength"], 0.0)   # the ratio is still visible

    def test_every_return_path_carries_the_key(self) -> None:
        """Shape stability: callers can rely on the key existing."""
        self.assertIn("raw_bias_strength", get_fast_bias({}, h1_data=None))
        self.assertIn("raw_bias_strength",
                      get_fast_bias({"ema_20": None, "ema_50": None}, h1_data=_h1_frame()))

    def test_the_new_key_is_the_only_addition(self) -> None:
        ind = {"ema_20": 4100.0, "ema_50": 4000.0, "close": 4100.0,
               "high": 4101.0, "low": 4099.0, "atr_14": 20.0}
        keys = set(get_fast_bias(ind, h1_data=_h1_frame()))
        expected = {"bias", "bias_strength", "swing_high", "swing_low", "ema_distance",
                    "ema_threshold", "ema20", "ema50", "invalidated", "flip_reason",
                    "full_report", "raw_bias_strength"}
        self.assertEqual(keys, expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
