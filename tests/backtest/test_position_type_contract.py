"""D-6OF-2A -- the emitted order direction must match the geometry it was built for.

``main_production`` constructs ``entry_price``, ``stop_loss`` and ``take_profit``
from the **effective** side (after any L2 BOS reversal), and
``backtest.replay_engine`` derives the broker order side from the signal's
``position_type``. Until this repair ``position_type`` came from the **pre-L2**
``bias``, so a reversed decision that reached a signal would have opened a trade
in the original direction carrying a stop and target built for the opposite one.

That combination has never occurred -- no reversal has ever produced a signal --
but 250 reversals were blocked at L8, one gate short of emitting it.

These tests run the real production path. Nothing under test is mocked. The four
signal instants and the two reversal instants are real decisions from the frozen
dataset, identified in ``docs/PHASE_6OF_2_SIDE_BIAS_STATE_AUDIT.md``.

**Scope note, stated honestly.** Cases 3 and 4 in the task brief ask for a
reversed decision that *emits a signal*. No such decision exists in this dataset,
so it cannot be produced end to end without fabricating market data. They are
covered instead by three composing facts, each measured on real production code:
the reversal really happens and ``direction`` really is the flipped side
(``ReversedDecisionsCarryTheFlippedSide``); ``position_type`` is now literally
``side`` (``PositionTypeIsDerivedFromTheEffectiveSide``); and the SL/TP geometry
follows ``direction`` in both directions (``EntryGeometryFollowsDirection``).
Together those imply the end-to-end property without asserting a signal that has
never existed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

from backtest.clock_patch import frozen_clock
from core.types import Side, Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed

REPO_ROOT = Path(__file__).resolve().parents[2]

BAR_COUNTS = {
    Timeframe.D1: 10, Timeframe.H1: 60, Timeframe.H4: 100,
    Timeframe.M1: 200, Timeframe.M15: 50, Timeframe.M5: 100,
}

# The decisions that produce a signal on the frozen dataset.
#
# Re-derived from `baselines/baseline_011`, the current configuration, after the
# U1-U12 unit migration changed which decisions reach L8. Previously four, taken
# from `baseline_008`/`baseline_009`:
#
#     2026-07-17T12:40  SELL   -- no longer signals
#     2026-08-06T08:00  BUY    -- unchanged
#     2026-08-12T09:25  BUY    -- no longer signals
#     2026-08-28T08:45  SELL   -- unchanged
#     2026-08-03T12:20  SELL   -- NEW
#
# The contract these instants exercise is unchanged: the emitted order direction
# must match the geometry built for it. Only the sample moved, because U8's
# sweep band and U2/U3/U4's liquidity distances now reject different candidates
# (L4 blocks went 748 -> 2,142, L5 5,000 -> 3,325).
SIGNAL_INSTANTS = {
    "2026-08-03T12:20:00+00:00": "SELL",
    "2026-08-06T08:00:00+00:00": "BUY",
    "2026-08-28T08:45:00+00:00": "SELL",
}

# Real L2 reversals, one in each direction.
REVERSAL_SELL_TO_BUY = "2026-06-25T13:00:00+00:00"
REVERSAL_BUY_TO_SELL = "2026-06-29T10:00:00+00:00"


def _analyse(instant: str):
    """Run the real production decision path at one frozen instant."""
    import entry_engine
    import main_production

    feed = ReplayFeed(
        HistoricalDataset.from_directory(str(REPO_ROOT / "data" / "raw"), "XAUUSD"),
        spread_pips=2.0,
    )
    moment = pd.Timestamp(instant).to_pydatetime()
    frames = {tf: feed.bars(tf, count, moment) for tf, count in BAR_COUNTS.items()}
    price = feed.price_at(moment)
    with frozen_clock(moment):
        regime_info = entry_engine.detect_regime(
            frames[Timeframe.M5], frames[Timeframe.M15], frames[Timeframe.H1],
            current_spread=feed.spread_at(moment),
        )
        analysis = main_production.analyze_entry(
            h4_data=frames[Timeframe.H4], h1_data=frames[Timeframe.H1],
            m15_data=frames[Timeframe.M15], m5_data=frames[Timeframe.M5],
            m1_data=frames[Timeframe.M1], daily_data=frames[Timeframe.D1],
            current_price=price or 0.0, regime_info=regime_info,
        )
    return analysis


class PositionTypeIsDerivedFromTheEffectiveSide(unittest.TestCase):
    """The mechanism: the payload must read ``side``, not ``bias``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REPO_ROOT / "main_production.py").read_text(encoding="utf-8")

    def test_the_payload_does_not_read_bias_for_position_type(self) -> None:
        self.assertNotIn(
            '"position_type": "BUY" if bias["bias"] == "BULLISH" else "SELL"',
            self.source,
            "position_type is reading the pre-L2 bias again",
        )

    def test_the_payload_reads_the_effective_side(self) -> None:
        tree = ast.parse(self.source)
        analyze = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "analyze_entry"
        )
        found = []
        for node in ast.walk(analyze):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "position_type":
                    found.append(ast.unparse(value))
        self.assertEqual(found, ["side"], f"position_type is built from {found}")


class SignalDirectionMatchesItsGeometry(unittest.TestCase):
    """Cases 1 and 2: the four real signals, end to end.

    A BUY must have ``stop_loss < entry_price < take_profit``; a SELL the
    mirror. The order side the broker would receive is derived exactly as
    ``replay_engine`` derives it.
    """

    def test_every_signal_is_internally_consistent(self) -> None:
        seen = {"BUY": 0, "SELL": 0}
        for instant, expected in SIGNAL_INSTANTS.items():
            with self.subTest(instant=instant):
                analysis = _analyse(instant)
                self.assertEqual(analysis.get("signal_type"), "ENTRY_SIGNAL")
                signal = analysis["entry_signal"]
                direction = analysis["direction"]

                self.assertEqual(direction, expected)
                self.assertEqual(signal["position_type"], expected)
                self.assertEqual(signal["position_type"], direction)

                # The side the broker would actually receive.
                self.assertIs(
                    Side.from_bias(str(signal["position_type"])),
                    Side.BUY if expected == "BUY" else Side.SELL,
                )

                entry = float(signal["entry_price"])
                stop = float(signal["stop_loss"])
                target = float(signal["take_profit"])
                if expected == "BUY":
                    self.assertLess(stop, entry)
                    self.assertLess(entry, target)
                else:
                    self.assertLess(target, entry)
                    self.assertLess(entry, stop)
                seen[expected] += 1

        # The point of the tally is that BOTH directions are exercised, so the
        # geometry assertions above are not all one-sided. It previously pinned
        # the literal {"BUY": 2, "SELL": 2}, which broke when the unit migration
        # changed which decisions reach L8 -- a count of the sample, not a
        # property of it. Derived from SIGNAL_INSTANTS instead.
        from collections import Counter

        expected_tally = Counter(SIGNAL_INSTANTS.values())
        self.assertEqual(dict(seen), dict(expected_tally))
        self.assertEqual(
            set(seen), {"BUY", "SELL"},
            "both directions must appear, or the geometry check is one-sided")
        self.assertEqual(sum(seen.values()), len(SIGNAL_INSTANTS))


class ReversedDecisionsCarryTheFlippedSide(unittest.TestCase):
    """Cases 3 and 4, the part that can be measured: the reversal is real.

    These two instants are genuine L2 BOS reversals from the frozen dataset.

    **P8-15 update.** Before that repair the pre-L2 bias and the effective
    direction *disagreed*, and these tests pinned the disagreement. The flip now
    reassigns the label (``bias["bias"] = flipped_bias_label``), so the corrected
    contract is that ``layer_1["bias"]`` **agrees** with ``direction``. The
    reversal itself is established by ``bos_flip``, which is what records it --
    not by the former inconsistency. P8-15 changed no decision: the replay was
    byte-identical to ``baseline_006`` across all 15,735 decisions.
    """

    def test_sell_to_buy_reversal(self) -> None:
        analysis = _analyse(REVERSAL_SELL_TO_BUY)
        self.assertTrue(analysis.get("bos_flip"), "this instant is no longer a reversal")
        # P8-15: was "BEARISH" (the abandoned direction) before the repair.
        self.assertEqual(analysis["layer_1"]["bias"], "BULLISH")
        self.assertEqual(analysis["direction"], "BUY")

    def test_buy_to_sell_reversal(self) -> None:
        analysis = _analyse(REVERSAL_BUY_TO_SELL)
        self.assertTrue(analysis.get("bos_flip"), "this instant is no longer a reversal")
        # P8-15: was "BULLISH" (the abandoned direction) before the repair.
        self.assertEqual(analysis["layer_1"]["bias"], "BEARISH")
        self.assertEqual(analysis["direction"], "SELL")

    def test_a_reversed_decision_would_emit_its_effective_side(self) -> None:
        """If either ever reached a signal, ``position_type`` follows ``direction``.

        Asserted through the payload's own expression rather than a fabricated
        signal: ``position_type`` is ``side``, and ``side`` is what
        ``analysis["direction"]`` records.

        **P8-15 update.** This previously proved *"a reversal happened"* by
        asserting that ``direction`` **disagreed** with the side implied by
        ``layer_1["bias"]`` -- it used the stale-bias inconsistency itself as its
        evidence. P8-15 removed that inconsistency, so the proxy is gone. The
        reversal is now established by ``bos_flip``, which is what actually
        records it, and the label is asserted to **agree** with the side.
        """
        for instant, expected in (
            (REVERSAL_SELL_TO_BUY, "BUY"),
            (REVERSAL_BUY_TO_SELL, "SELL"),
        ):
            with self.subTest(instant=instant):
                analysis = _analyse(instant)
                direction = analysis["direction"]
                self.assertTrue(
                    analysis.get("bos_flip"),
                    "this instant is no longer a reversal; the test would prove nothing",
                )
                self.assertEqual(direction, expected)
                self.assertEqual(
                    analysis["layer_1"]["bias"],
                    "BULLISH" if direction == "BUY" else "BEARISH",
                    "P8-15: the L1 label must follow the effective side after a flip",
                )
                signal = analysis.get("entry_signal")
                if signal:  # never true on this dataset; guards a future one
                    self.assertEqual(signal["position_type"], direction)


class EntryGeometryFollowsDirection(unittest.TestCase):
    """The other half of cases 3 and 4: SL/TP orientation is set by direction."""

    def test_buy_places_the_stop_below_and_the_target_above(self) -> None:
        import entry_engine

        levels = entry_engine.calculate_entry_levels(
            direction="BUY", entry_price=4000.0, sweep_wick_low=3997.0, tp_ratio=1.5
        )
        self.assertLess(levels["stop_loss"], levels["entry_price"])
        self.assertLess(levels["entry_price"], levels["take_profit"])

    def test_sell_places_the_stop_above_and_the_target_below(self) -> None:
        import entry_engine

        levels = entry_engine.calculate_entry_levels(
            direction="SELL", entry_price=4000.0, sweep_wick_high=4003.0, tp_ratio=1.5
        )
        self.assertGreater(levels["stop_loss"], levels["entry_price"])
        self.assertGreater(levels["entry_price"], levels["take_profit"])


class BrokerSideFollowsPositionType(unittest.TestCase):
    """``replay_engine`` reads only ``position_type``; nothing else sets the side."""

    def test_replay_engine_derives_the_side_from_position_type(self) -> None:
        source = (REPO_ROOT / "backtest" / "replay_engine.py").read_text(encoding="utf-8")
        self.assertIn(
            'side = Side.from_bias(str(entry_signal.get("position_type", "")))', source
        )

    def test_from_bias_round_trips_both_directions(self) -> None:
        self.assertIs(Side.from_bias("BUY"), Side.BUY)
        self.assertIs(Side.from_bias("SELL"), Side.SELL)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
