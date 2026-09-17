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
"""

from __future__ import annotations

import unittest

from execution.broker import PositionState
from tests.fixtures.integration_market import Resolution
from tests.integration._harness import long_dataset, run_replay, short_dataset

# Post-R1 values, measured before and after the change (see the report).
LONG_LEDGER_FINGERPRINT = "d42a9218d75d45ba03fe7d9c849dc84c13052aa5354d078809ac141b546d821d"
SHORT_LEDGER_FINGERPRINT = "ca9b8a9b2f07b330bbcf9306cd38de9d31ba5d2fd37d5b6bde08f6c728626559"

LONG_BARS_HELD = 24     # was 23 before R1
SHORT_BARS_HELD = 20    # was 19 before R1


class _FixtureChecks:
    """Shared assertions. Not a TestCase, so it is never collected on its own."""

    builder = None
    expected_fingerprint = ""
    expected_bars_held = 0
    expected_exit_time = ""
    expected_exit_price = 0.0
    expected_side = ""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.ledger, cls.metrics, cls.broker = run_replay(cls.builder(Resolution.TARGET))

    # --- unchanged by R1 -------------------------------------------------

    def test_exactly_one_trade(self) -> None:
        self.assertEqual(len(self.ledger.trades), 1)

    def test_outcome_is_still_target(self) -> None:
        self.assertEqual(self.ledger.trades[0].outcome, "TARGET_HIT")
        self.assertIs(self.broker.closed_positions()[0].state, PositionState.CLOSED_TARGET)

    def test_exit_bar_is_unchanged(self) -> None:
        self.assertEqual(str(self.ledger.trades[0].exit_time), self.expected_exit_time)

    def test_exit_price_is_unchanged(self) -> None:
        self.assertAlmostEqual(
            self.ledger.trades[0].exit_price, self.expected_exit_price, places=9
        )

    def test_exit_was_not_ambiguous(self) -> None:
        self.assertFalse(self.ledger.trades[0].was_ambiguous_exit)
        self.assertEqual(self.metrics.ambiguous_exits, 0)

    # --- changed by R1, pinned at the new values -------------------------

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
    expected_exit_time = "2026-03-19T09:05:00+00:00"
    expected_exit_price = 2557.4780567698713
    expected_side = "BUY"

    def test_side(self) -> None:
        self.assertEqual(self.ledger.trades[0].side, "BUY")


class ShortFixtureTests(_FixtureChecks, unittest.TestCase):
    """SELL setup: filled, ran to target."""

    builder = staticmethod(short_dataset)
    expected_fingerprint = SHORT_LEDGER_FINGERPRINT
    expected_bars_held = SHORT_BARS_HELD
    expected_exit_time = "2026-03-19T08:45:00+00:00"
    expected_exit_price = 2158.3480567642223
    expected_side = "SELL"

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
