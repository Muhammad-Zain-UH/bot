"""Contract tests for canonical trade identity and fill recording.

Source of truth: ``docs/PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md`` §16.3 and
the identity decisions D7-D12. These cover the Phase 2 infrastructure only: no
adapter, no broker and no production path uses any of it yet.
"""

from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.types import DomainInvariantError, Side
from execution.trade_identity import (
    FillIdentity,
    FillKind,
    FillLog,
    FillRecord,
    IdentityMinter,
    InsufficientFillIdentityError,
    OperationKind,
    PositionMismatchError,
    record_then_apply,
)

BAR = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
MODULE_SOURCE = (
    Path(__file__).resolve().parents[2] / "execution" / "trade_identity.py"
)


def _fill(
    position_id: str = "XAUUSD-20260319T090500-BUY-0001",
    operation_id: str = "XAUUSD-20260319T090500-BUY-0001#PARTIAL_CLOSE-0002",
    *,
    deal: str | None = None,
    index: int | None = 1,
    kind: FillKind = FillKind.PARTIAL_EXIT,
    steps: int = 50,
    price: float = 2479.80,
    minutes: int = 0,
) -> FillRecord:
    """A partial-exit execution, with identity supplied either way."""
    return FillRecord(
        identity=FillIdentity(
            position_id=position_id,
            operation_id=operation_id,
            broker_deal_id=deal,
            execution_index=index,
        ),
        kind=kind,
        cause="M1R",
        quantity_steps=steps,
        price=price,
        time=BAR + timedelta(minutes=minutes),
    )


class PositionIdentity(unittest.TestCase):
    """D7 / D12: minted at position creation, deterministic, unique."""

    def test_the_identity_has_the_agreed_shape(self) -> None:
        minted = IdentityMinter().next_position_id(
            symbol="XAUUSD", side=Side.BUY, entry_bar_time=BAR
        )
        self.assertEqual(minted, "XAUUSD-20260319T090500-BUY-0001")

    def test_distinct_positions_get_distinct_identities(self) -> None:
        """Uniqueness holds even when every readable component agrees."""
        minter = IdentityMinter()
        first = minter.next_position_id(
            symbol="XAUUSD", side=Side.BUY, entry_bar_time=BAR
        )
        second = minter.next_position_id(
            symbol="XAUUSD", side=Side.BUY, entry_bar_time=BAR
        )
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-0002"))

    def test_the_same_replay_mints_the_same_identities(self) -> None:
        """Two runs over the same data, in the same order, agree exactly."""
        def run() -> list[str]:
            minter = IdentityMinter()
            return [
                minter.next_position_id(
                    symbol="XAUUSD",
                    side=Side.BUY if index % 2 == 0 else Side.SELL,
                    entry_bar_time=BAR + timedelta(minutes=5 * index),
                )
                for index in range(5)
            ]

        self.assertEqual(run(), run())

    def test_the_identity_does_not_vary_with_the_machine_timezone(self) -> None:
        """The same instant expressed in another zone mints the same identity."""
        minter_utc = IdentityMinter()
        minter_offset = IdentityMinter()
        elsewhere = BAR.astimezone(timezone(timedelta(hours=3)))
        self.assertEqual(
            minter_utc.next_position_id(
                symbol="XAUUSD", side=Side.BUY, entry_bar_time=BAR
            ),
            minter_offset.next_position_id(
                symbol="XAUUSD", side=Side.BUY, entry_bar_time=elsewhere
            ),
        )

    def test_a_naive_bar_time_is_refused(self) -> None:
        with self.assertRaises(DomainInvariantError):
            IdentityMinter().next_position_id(
                symbol="XAUUSD", side=Side.BUY,
                entry_bar_time=datetime(2026, 3, 19, 9, 5),
            )


class OperationIdentity(unittest.TestCase):
    """D8: one identity per instruction, stable across retries of it."""

    def test_an_operation_identity_is_scoped_and_numbered(self) -> None:
        minted = IdentityMinter().next_operation_id(
            scope="XAUUSD-20260319T090500-BUY-0001",
            kind=OperationKind.PARTIAL_CLOSE,
        )
        self.assertEqual(
            minted, "XAUUSD-20260319T090500-BUY-0001#PARTIAL_CLOSE-0001"
        )

    def test_a_retry_reuses_the_identity_rather_than_minting_another(self) -> None:
        """The identity belongs to the instruction, not to an attempt at it.

        Minting is therefore done once and the value reused; minting again
        yields a different identity, which is exactly how a genuine second
        instruction stays distinguishable from a retry of the first.
        """
        minter = IdentityMinter()
        instruction = minter.next_operation_id(
            scope="POS-1", kind=OperationKind.FINAL_CLOSE
        )
        first_attempt = instruction
        second_attempt = instruction  # a retry carries the value it was given
        self.assertEqual(first_attempt, second_attempt)

        a_different_instruction = minter.next_operation_id(
            scope="POS-1", kind=OperationKind.FINAL_CLOSE
        )
        self.assertNotEqual(instruction, a_different_instruction)

    def test_distinct_operations_get_distinct_identities(self) -> None:
        minter = IdentityMinter()
        minted = [
            minter.next_operation_id(scope="POS-1", kind=kind)
            for kind in OperationKind
        ]
        self.assertEqual(len(set(minted)), len(minted))

    def test_an_entry_operation_may_be_scoped_before_a_position_exists(self) -> None:
        """Spec 13: the position is created at the fill, so an entry
        instruction cannot reference a position_id that does not exist yet."""
        minted = IdentityMinter().next_operation_id(
            scope="XAUUSD-20260319T090500-BUY", kind=OperationKind.ENTRY
        )
        self.assertTrue(minted.startswith("XAUUSD-20260319T090500-BUY#ENTRY-"))


class FillIdentityRules(unittest.TestCase):
    """D10 / §16.3: an execution must be distinguishable from a redelivery."""

    def test_a_deal_id_identifies_the_execution(self) -> None:
        identity = FillIdentity(
            position_id="POS-1", operation_id="OP-1", broker_deal_id="D-77"
        )
        self.assertEqual(identity.fill_id, "POS-1#deal:D-77")

    def test_without_a_deal_id_the_execution_index_identifies_it(self) -> None:
        identity = FillIdentity(
            position_id="POS-1", operation_id="OP-1", execution_index=2
        )
        self.assertEqual(identity.fill_id, "OP-1#exec:02")

    def test_fill_identities_are_unique_across_operations_and_executions(self) -> None:
        ids = {
            FillIdentity(position_id="POS-1", operation_id="OP-1", execution_index=1).fill_id,
            FillIdentity(position_id="POS-1", operation_id="OP-1", execution_index=2).fill_id,
            FillIdentity(position_id="POS-1", operation_id="OP-2", execution_index=1).fill_id,
            FillIdentity(position_id="POS-1", operation_id="OP-3", broker_deal_id="D-1").fill_id,
        }
        self.assertEqual(len(ids), 4)

    def test_an_execution_with_no_identity_at_all_is_refused(self) -> None:
        """It must not be silently deduplicated, and must not be silently
        accepted: neither answer is knowable, so construction fails."""
        with self.assertRaises(InsufficientFillIdentityError):
            FillIdentity(position_id="POS-1", operation_id="OP-1")

    def test_an_execution_index_below_one_is_refused(self) -> None:
        with self.assertRaises(DomainInvariantError):
            FillIdentity(position_id="POS-1", operation_id="OP-1", execution_index=0)

    def test_a_record_requires_a_positive_quantity_and_an_aware_time(self) -> None:
        for label, kwargs in (
            ("zero quantity", {"quantity_steps": 0}),
            ("naive time", {"time": datetime(2026, 3, 19, 9, 5)}),
        ):
            with self.subTest(case=label):
                base = dict(
                    identity=FillIdentity(
                        position_id="POS-1", operation_id="OP-1", execution_index=1
                    ),
                    kind=FillKind.PARTIAL_EXIT,
                    cause="M1R",
                    quantity_steps=50,
                    price=2479.80,
                    time=BAR,
                )
                base.update(kwargs)
                with self.assertRaises(DomainInvariantError):
                    FillRecord(**base)  # type: ignore[arg-type]


class DuplicateHandling(unittest.TestCase):
    """§16.3: a redelivery is a no-op; two executions are two fills."""

    def setUp(self) -> None:
        self.log = FillLog()

    def test_a_new_execution_is_recorded(self) -> None:
        self.assertTrue(self.log.record(_fill(), for_position=_fill().position_id))
        self.assertEqual(len(self.log), 1)

    def test_a_redelivered_execution_is_a_no_op(self) -> None:
        fill = _fill()
        self.assertTrue(self.log.record(fill, for_position=fill.position_id))
        self.assertFalse(self.log.record(fill, for_position=fill.position_id))
        self.assertEqual(len(self.log), 1)
        self.assertEqual(self.log.steps_closed_for(fill.position_id), 50)

    def test_a_redelivery_cannot_double_the_recorded_quantity(self) -> None:
        fill = _fill(steps=50)
        for _ in range(5):
            self.log.record(fill, for_position=fill.position_id)
        self.assertEqual(self.log.steps_closed_for(fill.position_id), 50)

    def test_two_genuine_executions_of_one_request_stay_separate(self) -> None:
        """One request filled in two pieces is not a duplicate."""
        first = _fill(index=1, steps=30)
        second = _fill(index=2, steps=20)
        self.assertTrue(self.log.record(first, for_position=first.position_id))
        self.assertTrue(self.log.record(second, for_position=second.position_id))
        self.assertEqual(len(self.log), 2)
        self.assertEqual(self.log.steps_closed_for(first.position_id), 50)

    def test_two_distinct_deals_stay_separate(self) -> None:
        first = _fill(deal="D-1", index=None, steps=30)
        second = _fill(deal="D-2", index=None, steps=20)
        self.log.record(first, for_position=first.position_id)
        self.log.record(second, for_position=second.position_id)
        self.assertEqual(self.log.steps_closed_for(first.position_id), 50)

    def test_a_fill_naming_another_position_is_rejected(self) -> None:
        fill = _fill(position_id="POS-A")
        with self.assertRaises(PositionMismatchError):
            self.log.record(fill, for_position="POS-B")
        self.assertEqual(len(self.log), 0)

    def test_the_entry_fill_is_not_counted_as_closed_quantity(self) -> None:
        entry = _fill(kind=FillKind.ENTRY, steps=100, index=1,
                      operation_id="OP-ENTRY")
        exit_fill = _fill(kind=FillKind.PARTIAL_EXIT, steps=50, index=1)
        self.log.record(entry, for_position=entry.position_id)
        self.log.record(exit_fill, for_position=exit_fill.position_id)
        self.assertEqual(self.log.steps_closed_for(entry.position_id), 50)

    def test_fills_are_returned_per_position_in_recording_order(self) -> None:
        first = _fill(index=1, minutes=0)
        second = _fill(index=2, minutes=5)
        other = _fill(position_id="POS-B", operation_id="OP-B", index=1)
        for fill in (first, second, other):
            self.log.record(fill, for_position=fill.position_id)
        self.assertEqual(
            [f.fill_id for f in self.log.fills_for(first.position_id)],
            [first.fill_id, second.fill_id],
        )


class RecordThenApply(unittest.TestCase):
    """The ordering contract: record first, then apply -- never the reverse."""

    def setUp(self) -> None:
        self.log = FillLog()

    def test_the_execution_is_recorded_before_apply_runs(self) -> None:
        fill = _fill()
        seen_during_apply: list[bool] = []

        def apply(applied: FillRecord) -> None:
            seen_during_apply.append(self.log.holds(applied.fill_id))

        self.assertTrue(
            record_then_apply(
                self.log, fill, for_position=fill.position_id, apply=apply
            )
        )
        self.assertEqual(seen_during_apply, [True])

    def test_a_redelivery_never_reaches_apply(self) -> None:
        fill = _fill()
        applications: list[str] = []

        def apply(applied: FillRecord) -> None:
            applications.append(applied.fill_id)

        record_then_apply(self.log, fill, for_position=fill.position_id, apply=apply)
        result = record_then_apply(
            self.log, fill, for_position=fill.position_id, apply=apply
        )
        self.assertFalse(result)
        self.assertEqual(applications, [fill.fill_id])

    def test_a_mismatched_position_neither_records_nor_applies(self) -> None:
        fill = _fill(position_id="POS-A")
        applications: list[str] = []

        with self.assertRaises(PositionMismatchError):
            record_then_apply(
                self.log, fill, for_position="POS-B",
                apply=lambda applied: applications.append(applied.fill_id),
            )
        self.assertEqual(len(self.log), 0)
        self.assertEqual(applications, [])


class NoAmbientIdentitySources(unittest.TestCase):
    """D12: identity must not come from a clock or a random source."""

    def setUp(self) -> None:
        self.tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))

    def test_no_random_source(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                with self.subTest(imported=root):
                    self.assertNotEqual(root, "random")

    def test_no_wall_clock_read(self) -> None:
        """An identity derived from the clock would not survive a replay."""
        offenders: list[str] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"now", "today", "time"}:
                offenders.append(f"line {node.lineno}: .{func.attr}()")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
