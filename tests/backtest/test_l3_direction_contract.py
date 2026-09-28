"""D-6OF-2B -- L3 evaluates the direction the pipeline is actually trading.

``bias`` is L1's pre-L2 label and the BOS flip never updates it. Before this
change a reversed decision asked L3 to find a retracement of an impulse in the
direction the pipeline had just abandoned.

The contract, composed from two statements in ``architecture.txt`` written in the
same commit as the flip: the BOS Flip *"check[s] if opposite direction has
confirmed structure and **flip[s] bias**"* (760-761), and L3's *"Purpose:
Identify quality pullbacks **in the direction of the bias**"* (765).

These tests run the real production path. Nothing under test is mocked. The two
reversal instants are genuine L2 reversals from the frozen dataset, chosen
because the stale and effective readings of the same bars give clearly different
retracements -- so the assertion can tell which direction L3 actually received:

    2026-06-25T17:15  SELL->BUY   stale BEARISH 97.5%  vs  effective BULLISH 27.8%
    2026-06-29T10:00  BUY->SELL   stale BULLISH 95.1%  vs  effective BEARISH 16.6%

Both are REGIME_SCALP, which is what makes them observable: only that regime's
L3 failure message embeds the pullback reasoning (and with it the retracement),
so the test can read back which direction L3 actually evaluated rather than
inferring it.

**Out of scope, deliberately.** ``bias`` and ``bias_strength`` are still not
reassigned by the flip, so ``analysis["layer_1"]`` and L7's ``bias_strength``
still carry the pre-flip values. That is D-6OF-2 models 2/3 and remains open.
The L3 rule discrepancies catalogued in D-6OF-2C -- the unimplemented EMA
condition, the volume rule, the 0.618/0.786 cap and the redundant
``MIN_PULLBACK_QUALITY`` -- are also untouched.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from backtest.clock_patch import frozen_clock
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

REPO_ROOT = Path(__file__).resolve().parents[2]

BAR_COUNTS = {
    Timeframe.D1: 10, Timeframe.H1: 60, Timeframe.H4: 100,
    Timeframe.M1: 200, Timeframe.M15: 50, Timeframe.M5: 100,
}

REVERSAL_SELL_TO_BUY = "2026-06-25T17:15:00+00:00"
REVERSAL_BUY_TO_SELL = "2026-06-29T10:00:00+00:00"

# Two real non-reversal decisions, one per side, for the normal paths.
NORMAL_BUY = "2026-08-06T08:00:00+00:00"
NORMAL_SELL = "2026-07-17T12:40:00+00:00"


def _frames_and_price(instant: str):
    feed = ReplayFeed(
        HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD"),
        spread_pips=2.0,
    )
    moment = pd.Timestamp(instant).to_pydatetime()
    frames = {tf: feed.bars(tf, count, moment) for tf, count in BAR_COUNTS.items()}
    return frames, feed.price_at(moment), feed.spread_at(moment), moment


def _analyse(instant: str):
    import entry_engine
    import main_production

    frames, price, spread, moment = _frames_and_price(instant)
    with frozen_clock(moment):
        regime_info = entry_engine.detect_regime(
            frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
            current_spread=spread,
        )
        analysis = main_production.analyze_entry(
            h4_data=frames[Timeframe.H4], h1_data=frames[Timeframe.H1],
            m15_data=frames[Timeframe.M15], m5_data=frames[Timeframe.M5],
            m1_data=frames[Timeframe.M1], daily_data=frames[Timeframe.D1],
            current_price=price or 0.0, regime_info=regime_info,
        )
    return analysis, frames




class ReversalsEvaluateTheEffectiveDirection(unittest.TestCase):
    """The two genuine reversals, end to end, one per direction."""

    def _check(self, instant: str, stale_bias: str, effective_side: str) -> None:
        import pullback_detector

        analysis, frames = _analyse(instant)
        effective_bias = "BULLISH" if effective_side == "BUY" else "BEARISH"

        # The reversal really happened.
        self.assertTrue(analysis.get("bos_flip"), "this instant is no longer a reversal")
        self.assertEqual(analysis["layer_1"]["bias"], stale_bias)
        self.assertEqual(analysis["direction"], effective_side)

        # What L3 returns for each reading of the same bars. REGIME_SCALP's L3
        # failure message embeds the detector's own `reasoning` verbatim, so the
        # production path reports which direction it evaluated.
        stale = pullback_detector.get_m15_pullback(frames[Timeframe.M15], stale_bias)
        effective = pullback_detector.get_m15_pullback(frames[Timeframe.M15], effective_bias)
        stale_reason = str(stale.get("reasoning"))
        effective_reason = str(effective.get("reasoning"))
        self.assertNotEqual(
            stale_reason, effective_reason,
            "the two readings no longer differ; this instant cannot discriminate",
        )

        observed = str(analysis.get("fail_reason"))
        self.assertIn(
            effective_reason, observed,
            "L3 did not evaluate the effective direction",
        )
        self.assertNotIn(
            stale_reason, observed,
            "L3 is still evaluating the abandoned direction",
        )

    def test_sell_to_buy_reversal_evaluates_bullish(self) -> None:
        self._check(REVERSAL_SELL_TO_BUY, stale_bias="BEARISH", effective_side="BUY")

    def test_buy_to_sell_reversal_evaluates_bearish(self) -> None:
        self._check(REVERSAL_BUY_TO_SELL, stale_bias="BULLISH", effective_side="SELL")


class NonReversalsAreUnaffected(unittest.TestCase):
    """Where no flip occurs, ``bias`` and ``side`` already agree."""

    def _check(self, instant: str, side: str, bias: str) -> None:
        analysis, _ = _analyse(instant)
        self.assertFalse(analysis.get("bos_flip"), "this instant is now a reversal")
        self.assertEqual(analysis["direction"], side)
        self.assertEqual(analysis["layer_1"]["bias"], bias)
        # The bridge and the stale label coincide, so the change is a no-op here.
        self.assertEqual("BULLISH" if side == "BUY" else "BEARISH", bias)

    def test_normal_buy_path(self) -> None:
        self._check(NORMAL_BUY, side="BUY", bias="BULLISH")

    def test_normal_sell_path(self) -> None:
        self._check(NORMAL_SELL, side="SELL", bias="BEARISH")


class TheChangeIsScopedToL3(unittest.TestCase):
    """Nothing else the flip touches was altered."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REPO_ROOT / "main_production.py").read_text(encoding="utf-8")

    def test_bias_is_still_not_reassigned_by_the_flip(self) -> None:
        """D-6OF-2 model 2 remains open; only L3's input changed."""
        self.assertNotIn("bias = flipped_bias_label", self.source)

    def test_l7_still_reads_the_pre_flip_bias_strength(self) -> None:
        """D-6OF-2 model 3 remains open and explicitly out of scope."""
        self.assertIn('bias_strength=bias.get("bias_strength", 0.0)', self.source)

    def test_the_flip_itself_is_unchanged(self) -> None:
        self.assertIn("side = flipped_side", self.source)
        self.assertIn(
            'flipped_bias_label = "BULLISH" if flipped_side == "BUY" else "BEARISH"',
            self.source,
        )

    def test_scalp_1_is_unchanged(self) -> None:
        self.assertIn('if regime_name == "REGIME_SCALP":', self.source)
        self.assertIn("MIN_PULLBACK_QUALITY = 1.5", self.source)

    def test_the_deferred_l3_rules_are_untouched(self) -> None:
        """D-6OF-2C's four discrepancies are explicitly not repaired here."""
        detector = (REPO_ROOT / "pullback_detector.py").read_text(encoding="utf-8")
        self.assertIn('_to_float(closed.iloc[-1].get("ema20"))', detector)   # EMA rule
        self.assertIn("0.236 <= pullback_percent <= 0.786", detector)        # depth cap
        self.assertIn("def _volume_context(window", detector)                # volume rule


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
