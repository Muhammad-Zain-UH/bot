"""The decision-stream fingerprint must actually discriminate.

A determinism check is worth nothing if the value it compares cannot change.
``run_fingerprint`` on its own has exactly that weakness on a zero-trade run: it
covers the dataset, the ledger and the metrics, and with no trades the ledger is
empty and every metric is ``None``, so two runs that disagreed on every single
decision would still produce the same digest. These tests establish that
``decision_stream_fingerprint`` does not share that weakness -- each field it
claims to cover is mutated in turn and the digest is required to move.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backtest.baseline import decision_stream_fingerprint
from backtest.replay_engine import DecisionSnapshot


def _snapshot(
    *,
    minute: int = 0,
    regime: str = "REGIME_SCALP",
    signal_type: str = "PRE_ENTRY",
    direction: str = "BUY",
    layers_passed: tuple[str, ...] = ("L1_BIAS", "L2_STRUCTURE"),
    layer_failed: str = "L3_PULLBACK",
    fail_reason: str = "No confirmed pullback detected",
    current_price: float = 3900.0,
) -> DecisionSnapshot:
    """Build a decision snapshot with one field varied at a time."""
    return DecisionSnapshot(
        replay_time=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute),
        availability={},
        current_price=current_price,
        spread_pips=2.0,
        regime=regime,
        signal_type=signal_type,
        direction=direction,
        layers_passed=layers_passed,
        layer_failed=layer_failed,
        fail_reason=fail_reason,
    )


BASE = [_snapshot(minute=0), _snapshot(minute=5), _snapshot(minute=10)]


class TestFingerprintIsStable(unittest.TestCase):
    """Identical streams must agree."""

    def test_same_stream_same_digest(self) -> None:
        self.assertEqual(
            decision_stream_fingerprint(BASE),
            decision_stream_fingerprint([_snapshot(minute=0), _snapshot(minute=5), _snapshot(minute=10)]),
        )

    def test_empty_stream_is_the_empty_digest(self) -> None:
        import hashlib

        self.assertEqual(decision_stream_fingerprint([]), hashlib.sha256(b"").hexdigest())


class TestFingerprintDiscriminates(unittest.TestCase):
    """Every covered field must be able to move the digest."""

    def setUp(self) -> None:
        self.base = decision_stream_fingerprint(BASE)

    def _assert_changes(self, **override) -> None:
        mutated = [_snapshot(minute=0), _snapshot(minute=5, **override), _snapshot(minute=10)]
        self.assertNotEqual(
            decision_stream_fingerprint(mutated), self.base,
            msg=f"digest did not move when {override} changed",
        )

    def test_regime_change_moves_the_digest(self) -> None:
        self._assert_changes(regime="MICRO_SCALP")

    def test_signal_type_change_moves_the_digest(self) -> None:
        self._assert_changes(signal_type="ENTRY_SIGNAL")

    def test_direction_change_moves_the_digest(self) -> None:
        self._assert_changes(direction="SELL")

    def test_blocking_layer_change_moves_the_digest(self) -> None:
        self._assert_changes(layer_failed="L8_ENTRY")

    def test_layers_passed_change_moves_the_digest(self) -> None:
        self._assert_changes(layers_passed=("L1_BIAS",))

    def test_fail_reason_change_moves_the_digest(self) -> None:
        self._assert_changes(fail_reason="Entry triggers not all confirmed")

    def test_decision_time_change_moves_the_digest(self) -> None:
        mutated = [_snapshot(minute=0), _snapshot(minute=6), _snapshot(minute=10)]
        self.assertNotEqual(decision_stream_fingerprint(mutated), self.base)

    def test_ordering_change_moves_the_digest(self) -> None:
        self.assertNotEqual(decision_stream_fingerprint(list(reversed(BASE))), self.base)

    def test_a_dropped_decision_moves_the_digest(self) -> None:
        self.assertNotEqual(decision_stream_fingerprint(BASE[:2]), self.base)

    def test_field_boundaries_cannot_be_smeared(self) -> None:
        """Moving text across the field separator must not collide."""
        left = [_snapshot(regime="AB", signal_type="CD")]
        right = [_snapshot(regime="A", signal_type="BCD")]
        self.assertNotEqual(
            decision_stream_fingerprint(left), decision_stream_fingerprint(right)
        )

    def test_record_boundaries_cannot_be_smeared(self) -> None:
        """Two decisions must not hash the same as one concatenated decision."""
        two = [_snapshot(fail_reason="alpha"), _snapshot(minute=5, fail_reason="beta")]
        one = [_snapshot(fail_reason="alpha|beta")]
        self.assertNotEqual(
            decision_stream_fingerprint(two), decision_stream_fingerprint(one)
        )


class TestPriceIsDeliberatelyExcluded(unittest.TestCase):
    """Price is a function of the dataset, which is fingerprinted separately."""

    def test_price_does_not_move_the_digest(self) -> None:
        mutated = [_snapshot(minute=0), _snapshot(minute=5, current_price=9999.0), _snapshot(minute=10)]
        self.assertEqual(decision_stream_fingerprint(mutated), decision_stream_fingerprint(BASE))


if __name__ == "__main__":
    unittest.main()
