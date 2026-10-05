"""R1 regression: the Phase 2A.1 fixture outcomes, pinned at their post-R1 values.

R1 made `PaperBroker.on_bar` evaluate a position on the bar it filled on. The
measurement in `docs/PHASE_4A_R1_SAME_BAR_EXIT_MEASUREMENT.md` predicted, and
this file pins, exactly what that did and did not change on the only two trades
the repository produces:

* **unchanged** -- outcome, exit bar, exit price, realised R, ambiguity flag;
* **changed** -- `bars_held` by exactly +1 per position (23 to 24, 19 to 20),
  and therefore `average_bars_held` and the ledger fingerprint, because
  `SimulatedTrade.to_dict()` is `asdict()` and the fingerprint hashes it.

The fingerprints below are absolute on purpose. Every other fingerprint
assertion in the suite is relative (run A equals run B), which proves
determinism but would not have caught R1's effect at all. These pin the value
itself, so a future change to fill or exit accounting has to be acknowledged
rather than silently absorbed.

That is exactly what happened at §4.2 (Phase 5B-ii). Anchoring the target to
the actual fill moved the target bar in, so the exit bar, exit price, bars_held
and P&L all moved and these assertions failed until each change had been
attributed. The R1 property itself is untouched: `bars_held` still counts the
fill bar. What the file pins has widened accordingly -- the figures upstream of
the target are asserted separately from those downstream of it, so a future
change that moves something upstream cannot hide behind a target recomputation.
"""

from __future__ import annotations

import unittest

from execution.broker import PositionState
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import long_dataset, run_replay, short_dataset

# Re-pinned twice, each time for a single identified reason.
#
# 5B-i, representation only: a trade became a canonical TradeRecord carrying its
# executions where it used to be a flat row. Nothing economic moved -- entry
# fill, exit time, exit price, closure reason, executed quantity, net P&L, R
# multiple, ambiguity and bars_held were byte-identical, UNEXPLAINED = 0.
#
# 5B-ii, one semantic change: §4.2 anchors the target to the ACTUAL FILL rather
# than to the entry the strategy intended. Both fixtures fill better than
# intended, so R shrank and the carried target was left at some other multiple
# of it -- 4.3519R (long) and 6.6225R (short) against a requested 3.0R.
# Re-anchoring moves the target in, so the target bar arrives earlier and every
# figure downstream of the exit moves with it. The audit classified all ten
# moved observables as TARGET_RECOMPUTATION with UNEXPLAINED = 0; the figures
# upstream of the target -- entry price, entry time, price risk, quantity,
# ambiguity -- did not move and are still pinned below at their original values.
#
#   before 5B-i : long  d42a9218d75d45ba03fe7d9c849dc84c13052aa5354d078809ac141b546d821d
#                 short ca9b8a9b2f07b330bbcf9306cd38de9d31ba5d2fd37d5b6bde08f6c728626559
#   before 5B-ii: long  67c95bf0960018afb29e1052fe4191429cd51ec11b3be7060e17fec4ef3aeb82
#                 short 057d9b75b86133a8848e06442243eb1e0d3ab5b5ed0d232e8143a186767b836e
# Re-pinned a third time, for a single identified reason: the A1-A4 ATR
# unification and B5's double-drop fix (research/atr_bar_convention_spec.md).
#
# REPRESENTATION ONLY -- nothing economic moved, and that is checked rather than
# asserted. Every economic field is identical to the previous pin:
#
#     outcome      TARGET_HIT / TARGET_HIT    unchanged
#     bars_held    14 / 5                     unchanged (LONG/SHORT_BARS_HELD)
#     exit_time    08:15:00 / 07:30:00        unchanged
#     exit_price   2545.1130098575254 / 2171.5830098518823   unchanged
#     price_risk   9.14642386182777 / 3.65357613817514        unchanged
#
# The fingerprint hashes `SimulatedTrade.to_dict()`, which is `asdict()` and so
# carries ATR-derived metadata alongside the economics. Four incompatible ATR
# definitions became one, so those fields moved while the trade did not. The
# assertions below on outcome, exit bar, exit price, R and bars_held are the
# ones that would have caught an economic change, and they all still pass
# against their ORIGINAL values.
#   before A1-A4: long  33ac2bb259d5662f386913a97b6ca0524eec7f13a0e3ceb4d455d6f65b010317
#                 short ce733aeb7d6220270b9cc4864a190a2970faa0981286895ef09c990d81228109
LONG_LEDGER_FINGERPRINT = "64dfd91221eefb470090434333b0ff7c3640c4cd323dd2c1032b16bc80a71087"
SHORT_LEDGER_FINGERPRINT = "ecbbcf622dfab37413180b5a2c1efa70da6114084d4a43e94ec67468dab5278c"

# Still includes the fill bar, which is the R1 property this file exists for.
# The counts fell because the target moved in, not because the accounting did:
# long 07:10 -> 08:15 is 13 M5 steps plus the fill bar; short 07:10 -> 07:30 is
# 4 plus the fill bar.
LONG_BARS_HELD = 14     # 23 before R1, 24 after R1, 14 after §4.2
SHORT_BARS_HELD = 5     # 19 before R1, 20 after R1, 5 after §4.2

TP_RATIO = 3.0          # what both fixtures' signals asked for


class _FixtureChecks:
    """Shared assertions. Not a TestCase, so it is never collected on its own."""

    builder = None
    expected_fingerprint = ""
    expected_bars_held = 0
    expected_exit_time = ""
    expected_exit_price = 0.0
    expected_side = ""
    expected_entry_price = 0.0
    expected_price_risk = 0.0

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.ledger, cls.metrics, cls.broker = run_replay(cls.builder(Resolution.TARGET))

    # --- upstream of the target: unmoved by R1 and by §4.2 ---------------

    def test_exactly_one_trade(self) -> None:
        self.assertEqual(len(self.ledger.trades), 1)

    def test_outcome_is_still_target(self) -> None:
        self.assertEqual(self.ledger.trades[0].outcome, "TARGET_HIT")
        self.assertIs(self.broker.closed_positions()[0].state, PositionState.CLOSED_TARGET)

    def test_entry_fill_is_unchanged(self) -> None:
        self.assertAlmostEqual(
            self.ledger.trades[0].entry_price, self.expected_entry_price, places=9
        )

    def test_price_risk_is_unchanged(self) -> None:
        """Original R. The stop never moved, so neither did this."""
        self.assertAlmostEqual(
            self.ledger.trades[0].price_risk, self.expected_price_risk, places=9
        )

    def test_exit_was_not_ambiguous(self) -> None:
        self.assertFalse(self.ledger.trades[0].was_ambiguous_exit)
        self.assertEqual(self.metrics.ambiguous_exits, 0)

    # --- downstream of the target: moved by §4.2, pinned at the new values -

    def test_the_target_is_the_ratio_times_original_r_from_the_fill(self) -> None:
        """§4.2, and the reason every figure below it moved. This is what makes
        the pinned values derived rather than merely observed."""
        position = self.broker.closed_positions()[0]
        risk = abs(position.entry_price - position.original_stop)
        sign = 1.0 if self.expected_side == "BUY" else -1.0
        self.assertAlmostEqual(risk, self.expected_price_risk, places=9)
        self.assertAlmostEqual(
            position.take_profit,
            position.entry_price + sign * TP_RATIO * risk,
            places=9,
        )
        # The level the strategy carried is NOT the one that was used.
        carried = (position.metadata or {}).get("strategy_take_profit")
        self.assertIsNotNone(carried)
        self.assertNotAlmostEqual(position.take_profit, carried, places=6)

    def test_exit_bar_is_pinned(self) -> None:
        self.assertEqual(str(self.ledger.trades[0].exit_time), self.expected_exit_time)

    def test_exit_price_is_pinned(self) -> None:
        self.assertAlmostEqual(
            self.ledger.trades[0].exit_price, self.expected_exit_price, places=9
        )

    def test_bars_held_includes_the_fill_bar(self) -> None:
        self.assertEqual(self.ledger.trades[0].bars_held, self.expected_bars_held)

    def test_average_bars_held_matches(self) -> None:
        self.assertAlmostEqual(self.metrics.average_bars_held, float(self.expected_bars_held))

    def test_ledger_fingerprint_is_pinned(self) -> None:
        self.assertEqual(self.ledger.fingerprint(), self.expected_fingerprint)


class LongFixtureTests(_FixtureChecks, unittest.TestCase):
    """BUY setup: filled, ran to target."""

    builder = staticmethod(long_dataset)
    expected_fingerprint = LONG_LEDGER_FINGERPRINT
    expected_bars_held = LONG_BARS_HELD
    # 09:05 and 2557.4780567698713 before §4.2, off the 4.3519R carried target.
    expected_exit_time = "2026-03-19T08:15:00+00:00"
    expected_exit_price = 2545.1130098575254
    expected_side = "BUY"
    expected_entry_price = 2517.873738272042
    expected_price_risk = 9.14642386182777

    def test_side(self) -> None:
        self.assertEqual(self.ledger.trades[0].side, "BUY")


class ShortFixtureTests(_FixtureChecks, unittest.TestCase):
    """SELL setup: filled, ran to target."""

    builder = staticmethod(short_dataset)
    expected_fingerprint = SHORT_LEDGER_FINGERPRINT
    expected_bars_held = SHORT_BARS_HELD
    # 08:45 and 2158.3480567642223 before §4.2, off the 6.6225R carried target.
    expected_exit_time = "2026-03-19T07:30:00+00:00"
    expected_exit_price = 2171.5830098518823
    expected_side = "SELL"
    expected_entry_price = 2182.343738266408
    expected_price_risk = 3.65357613817514

    def test_side(self) -> None:
        self.assertEqual(self.ledger.trades[0].side, "SELL")


class DeterminismAfterR1Tests(unittest.TestCase):
    """R1 must not have introduced any run-to-run variation."""

    def test_repeated_runs_agree(self) -> None:
        first = run_replay(long_dataset(Resolution.TARGET))[1].fingerprint()
        second = run_replay(long_dataset(Resolution.TARGET))[1].fingerprint()
        self.assertEqual(first, second)
        self.assertEqual(first, LONG_LEDGER_FINGERPRINT)


if __name__ == "__main__":
    unittest.main()
