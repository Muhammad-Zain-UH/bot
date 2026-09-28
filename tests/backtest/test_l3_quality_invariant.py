"""D-6OF-2H -- the invariant that keeps ``MIN_PULLBACK_QUALITY = 1.5`` inert.

**The invariant:** ``pullback_detected is True`` implies ``pullback_quality >= 4.0``.

Why it matters. The L3 admission gate in ``main_production.py`` reads::

    elif not pullback or not pullback_detected or pullback_quality < MIN_PULLBACK_QUALITY:

Short-circuit evaluation means the third disjunct is only ever reached when
``pullback_detected`` is True. Detection requires ``0.236 <= retracement <= 0.786``,
and that same band floors the *base* quality at 4.0 (5.5 in the ideal zone, 4.0 in
either shoulder) with only non-negative bonuses added on top. So the comparison
against 1.5 cannot fire -- measured 0 times in 15,735 decisions, registered as
**L3-D5** in ``docs/PHASE_6O_B_L3_PULLBACK_DEEP_AUDIT.md``.

That is a property of the current construction, not a guarantee. Lowering a base
score, widening the accepted band, or adding a negative bonus would silently
re-activate a threshold nobody has reasoned about since 2026-07-01, changing
admission with no visible edit to the gate. **L3-T6** recorded that nothing pinned
it. This file is that pin.

D-6OF-2G established that the both-detection-and-quality gate is historically
intentional, so this file pins the *implication*. It does not assert that 1.5 is
the right number, that it should be removed, or anything about signal counts.

The sweep runs the real detector over real M15 windows from the frozen dataset.
Nothing is mocked -- in particular the property under test is computed by
``pullback_detector``, never by this file.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from core.types import Timeframe
from data.dataset import HistoricalDataset

import pullback_detector

REPO_ROOT = Path(__file__).resolve().parents[2]

WINDOW = 50   # the M15 bar count main_production feeds L3
STEP = 25     # stride across the dataset; keeps the sweep near 10s

# The floor the gate's inertness depends on. Not a tuning knob: it is the lowest
# *base* score the accepted retracement band can produce.
QUALITY_FLOOR = 4.0
MIN_PULLBACK_QUALITY = 1.5  # mirrored from main_production.py for the margin check


def _sweep():
    """Every (window, direction) result the real detector produces."""
    frame = HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD")
    m15 = frame.frame(Timeframe.M15)
    results = []
    for end in range(WINDOW, len(m15), STEP):
        window = m15.iloc[end - WINDOW:end]
        for bias in ("BULLISH", "BEARISH"):
            results.append((end, bias, pullback_detector.get_m15_pullback(window, bias)))
    return results


class DetectionImpliesTheQualityFloor(unittest.TestCase):
    """``detected == True`` never coexists with a quality below 4.0."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.results = _sweep()
        cls.detected = [r for r in cls.results if r[2].get("pullback_detected")]

    def test_the_sweep_actually_observed_detections(self) -> None:
        """Anti-vacuity: the invariant below must have something to constrain."""
        self.assertGreater(
            len(self.detected), 50,
            f"only {len(self.detected)} detections in {len(self.results)} calls -- "
            "the invariant test would be near-vacuous; widen the sweep",
        )

    def test_detection_implies_quality_at_least_four(self) -> None:
        """The invariant itself."""
        offenders = [
            (end, bias, res.get("pullback_quality"), res.get("retracement_ratio"))
            for end, bias, res in self.detected
            if float(res.get("pullback_quality", 0.0)) < QUALITY_FLOOR
        ]
        self.assertEqual(
            offenders, [],
            "pullback_detected=True produced a quality below 4.0. MIN_PULLBACK_QUALITY "
            "in main_production.py is no longer inert and the L3 gate's behaviour has "
            "changed. See D-6OF-2G / L3-D5 before adjusting anything.",
        )

    def test_the_premise_holds_detection_implies_the_accepted_band(self) -> None:
        """The band is *why* the floor holds; pin the cause, not just the effect."""
        offenders = [
            (end, bias, res.get("retracement_ratio"))
            for end, bias, res in self.detected
            if not 0.236 <= float(res.get("retracement_ratio", -1.0)) <= 0.786
        ]
        self.assertEqual(
            offenders, [],
            "a detection escaped the 0.236-0.786 band; the quality floor no longer "
            "follows from the band",
        )

    def test_the_gate_comparison_can_never_fire(self) -> None:
        """Restated as the gate sees it, with the margin made explicit."""
        worst = min(
            (float(res.get("pullback_quality", 0.0)) for _, _, res in self.detected),
            default=None,
        )
        self.assertIsNotNone(worst)
        self.assertGreaterEqual(
            worst, MIN_PULLBACK_QUALITY,
            f"lowest quality among detections ({worst}) fell below "
            f"MIN_PULLBACK_QUALITY ({MIN_PULLBACK_QUALITY})",
        )
        self.assertGreaterEqual(worst, QUALITY_FLOOR)


class TheConstructionTheInvariantRestsOn(unittest.TestCase):
    """Source guards, so an edit that breaks the *reasoning* also fails here.

    The sweep can only observe branches the dataset reaches. These assertions
    cover the algebra directly.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REPO_ROOT / "pullback_detector.py").read_text(encoding="utf-8")

    def _present(self, needle: str, source: str, where: str) -> None:
        """assertIn on a whole file dumps the file; report the needle instead."""
        self.assertTrue(
            needle in source,
            f"{where} no longer contains {needle!r} -- the reasoning behind the "
            "quality floor has changed; re-derive it before editing this test",
        )

    def test_the_accepted_band_is_unchanged(self) -> None:
        self._present("0.236 <= pullback_percent <= 0.786", self.source, "pullback_detector.py")

    def test_both_in_band_base_scores_are_at_or_above_the_floor(self) -> None:
        """5.5 in the ideal zone, 4.0 in either shoulder -- the floor is 4.0."""
        self._present("quality = 5.5", self.source, "pullback_detector.py")
        self._present("quality = 4.0", self.source, "pullback_detector.py")

    def test_every_quality_bonus_is_non_negative(self) -> None:
        """A negative bonus would break the floor without touching the band."""
        for bonus in ("quality += 3.0", "quality += 1.5", "quality += 0.5", "quality += 1.0"):
            self._present(bonus, self.source, "pullback_detector.py")
        self.assertNotIn(
            "quality -=", self.source,
            "a negative quality adjustment was introduced; the floor no longer follows",
        )

    def test_min_pullback_quality_is_still_below_the_floor(self) -> None:
        gate = (REPO_ROOT / "main_production.py").read_text(encoding="utf-8")
        self._present(f"MIN_PULLBACK_QUALITY = {MIN_PULLBACK_QUALITY}", gate, "main_production.py")
        self.assertLess(MIN_PULLBACK_QUALITY, QUALITY_FLOOR)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
