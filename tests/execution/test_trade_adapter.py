"""Integration tests for the canonical trade adapter.

Phase 5B-i. The adapter is the **sole exit authority**: the broker fills resting
orders, counts bars and executes instructions, and decides nothing. These tests
pin both halves -- that the domain drives every exit, and that the broker no
longer acts on its own.

They replace ``test_shadow_equivalence.py``, whose central claim ("the shadow
changes nothing") stopped being true the moment the adapter became
authoritative. The equivalence oracle it carried lives on as the cut-over audit.

Phase 5B-ii adds :class:`CanonicalTargetRecomputation`, which pins §4.2: the
target is rebuilt from the actual fill and the carried level has no authority.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core.symbols import XAUUSD_2DIGIT
from core.trade_model import ClosureReason, PositionLifecycle, StopState
from core.types import PendingOrderIntent, Side
from core.units import Pips
from execution.broker import PositionState
from execution.fills import FillModel
from execution.intrabar import IntrabarPolicy
from execution.paper_broker import PaperBroker
from execution.trade_adapter import TradeAdapter, TradeEventKind
from execution.trade_identity import FillKind

SPEC = XAUUSD_2DIGIT
T0 = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
NO_COST = FillModel(spread=Pips(0.0), slippage=Pips(0.0))

ENTRY = 2450.0
STOP = 2420.0          # R = 30
TARGET = 2540.0        # 2450 + 3.0 x 30: the §4.2 target for this fill
ONE_R = 2480.0
TWO_R = 2510.0


def bar(minutes: int, *, open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series(
        {
            "time": pd.Timestamp(T0 + timedelta(minutes=minutes)),
            "open": open_, "high": high, "low": low, "close": close,
        }
    )


class AdapterHarness(unittest.TestCase):
    """A broker with one open BUY, managed by the canonical adapter."""

    policy = IntrabarPolicy.CONSERVATIVE
    volume = 1.00
    target: float | None = TARGET

    def setUp(self) -> None:
        self.broker = PaperBroker(SPEC, NO_COST, intrabar_policy=self.policy)
        self.adapter = TradeAdapter(self.broker)
        self.broker.submit_market_order(
            side=Side.BUY,
            volume=self.volume,
            stop_loss=STOP,
            take_profit=self.target,
            decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=ENTRY, high=2451.0, low=2449.0, close=2450.5),
            metadata={"strategy_rr_ratio": 3.0},
        )
        self.position = self.broker.open_positions()[0]
        self.canonical_id = self.adapter.on_position_opened(self.position)

    def feed(self, *bars: pd.Series) -> list:
        """Drive one bar at a time: broker fills and counts, adapter manages."""
        closed = []
        for candidate in bars:
            bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
            opened = self.broker.fill_pending_orders(candidate, bar_time)
            for position in opened:
                self.adapter.on_position_opened(position)
            closed.extend(self.adapter.manage(candidate, bar_time))
        return closed

    def first(self, kind: TradeEventKind):
        for event in self.adapter.events:
            if event.kind is kind:
                return event
        return None

    def all_of(self, kind: TradeEventKind) -> list:
        return [e for e in self.adapter.events if e.kind is kind]


class PositionCreation(AdapterHarness):
    """State is created at the fill, from the fill."""

    def test_the_canonical_position_is_created_with_identity(self) -> None:
        self.assertIsNotNone(self.canonical_id)
        self.assertTrue(self.canonical_id.startswith("XAUUSD-20260319T090500-BUY-"))

    def test_geometry_comes_from_the_actual_fill(self) -> None:
        state = self.adapter.state_for(self.position.position_id)
        self.assertAlmostEqual(state.entry_price, ENTRY, places=9)
        self.assertAlmostEqual(state.original_stop_price, STOP, places=9)
        self.assertAlmostEqual(state.r, 30.0, places=9)
        self.assertAlmostEqual(state.m1r, ONE_R, places=9)
        self.assertAlmostEqual(state.m2r, TWO_R, places=9)

    def test_the_target_is_three_r_from_the_fill(self) -> None:
        """§4.2. This harness fills at the intended entry, so it cannot tell
        the two anchors apart -- :class:`CanonicalTargetRecomputation` is where
        that is pinned. Here it only has to hold that the target is 3R out."""
        state = self.adapter.state_for(self.position.position_id)
        self.assertAlmostEqual(state.target, ENTRY + 3.0 * 30.0, places=9)
        self.assertAlmostEqual(state.target, TARGET, places=9)
        self.assertAlmostEqual(self.position.take_profit, TARGET, places=9)

    def test_the_entry_is_recorded_as_an_execution(self) -> None:
        fills = self.adapter.fill_log.fills_for(self.canonical_id)
        self.assertEqual(len(fills), 1)
        self.assertIs(fills[0].kind, FillKind.ENTRY)
        self.assertEqual(fills[0].quantity_steps, 100)

    def test_creation_is_idempotent(self) -> None:
        again = self.adapter.on_position_opened(self.position)
        self.assertEqual(again, self.canonical_id)
        self.assertEqual(len(self.all_of(TradeEventKind.POSITION_OPENED)), 1)


class CanonicalTargetRecomputation(unittest.TestCase):
    """§4.2: the target is anchored to the actual fill, not the intended entry.

    Phase 5B-ii. Every case here fills **materially away** from the entry the
    strategy intended and carries a ``take_profit`` computed from that intended
    entry, so the legacy level and the canonical one cannot coincide. If the
    adapter ever reads the carried target again, these fail.
    """

    INTENDED = 2450.0

    # Long: a fill 6.00 better than intended. R shrinks 30 -> 24, so the legacy
    # target sits at 4.0R -- |2540 - 2444| / 24 -- and the canonical one at
    # exactly 3R. Both ratios are measured from the ACTUAL fill in units of the
    # ACTUAL R, which is the only anchoring that means anything here.
    L_FILL, L_STOP, L_R = 2444.0, 2420.0, 24.0
    L_LEGACY = 2540.0                 # 2450 + 3 x 30, off the INTENDED entry
    L_CANONICAL = 2516.0              # 2444 + 3 x 24, off the ACTUAL fill

    # Short, mirrored: a fill 6.00 better than intended.
    S_FILL, S_STOP, S_R = 2456.0, 2480.0, 24.0
    S_LEGACY = 2360.0                 # 2450 - 3 x 30
    S_CANONICAL = 2384.0              # 2456 - 3 x 24

    RATIO = 3.0

    def _open(self, *, side: Side, fill: float, stop: float,
              carried: float | None, ratio: float = RATIO):
        """Fill `side` at `fill` while the signal intended ``INTENDED``."""
        broker = PaperBroker(SPEC, NO_COST)
        adapter = TradeAdapter(broker)
        broker.submit_market_order(
            side=side,
            volume=1.00,
            stop_loss=stop,
            take_profit=carried,
            decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            # The bar opens away from the intended entry, so the fill does too.
            execution_bar=bar(
                0, open_=fill, high=fill + 1.0, low=fill - 1.0, close=fill
            ),
            metadata={
                "strategy_rr_ratio": ratio,
                "strategy_entry_price": self.INTENDED,
                "strategy_take_profit": carried,
                "strategy_stop_loss": stop,
            },
        )
        position = broker.open_positions()[0]
        adapter.on_position_opened(position)
        return broker, adapter, position

    # -- the contract itself ---------------------------------------------

    def test_long_target_is_fill_plus_ratio_times_original_r(self) -> None:
        _, adapter, position = self._open(
            side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP, carried=self.L_LEGACY
        )
        state = adapter.state_for(position.position_id)
        self.assertAlmostEqual(state.entry_price, self.L_FILL, places=9)
        self.assertAlmostEqual(state.r, self.L_R, places=9)
        self.assertAlmostEqual(
            state.target, self.L_FILL + self.RATIO * self.L_R, places=9
        )
        self.assertAlmostEqual(state.target, self.L_CANONICAL, places=9)

    def test_short_target_is_fill_minus_ratio_times_original_r(self) -> None:
        _, adapter, position = self._open(
            side=Side.SELL, fill=self.S_FILL, stop=self.S_STOP, carried=self.S_LEGACY
        )
        state = adapter.state_for(position.position_id)
        self.assertAlmostEqual(state.entry_price, self.S_FILL, places=9)
        self.assertAlmostEqual(state.r, self.S_R, places=9)
        self.assertAlmostEqual(
            state.target, self.S_FILL - self.RATIO * self.S_R, places=9
        )
        self.assertAlmostEqual(state.target, self.S_CANONICAL, places=9)

    def test_the_canonical_target_is_not_the_carried_one(self) -> None:
        """The premise of every case here: the two levels really do differ."""
        for side, fill, stop, legacy, canonical in (
            (Side.BUY, self.L_FILL, self.L_STOP, self.L_LEGACY, self.L_CANONICAL),
            (Side.SELL, self.S_FILL, self.S_STOP, self.S_LEGACY, self.S_CANONICAL),
        ):
            with self.subTest(side=side):
                self.assertNotAlmostEqual(legacy, canonical, places=6)
                _, adapter, position = self._open(
                    side=side, fill=fill, stop=stop, carried=legacy
                )
                state = adapter.state_for(position.position_id)
                self.assertNotAlmostEqual(state.target, legacy, places=6)
                self.assertAlmostEqual(state.target, canonical, places=9)

    # -- independence from the carried level ------------------------------

    def test_changing_the_carried_target_does_not_move_the_canonical_one(self) -> None:
        """Three different legacy levels, one canonical target."""
        for carried in (self.L_LEGACY, 2600.0, 2470.0):
            with self.subTest(carried=carried):
                _, adapter, position = self._open(
                    side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP, carried=carried
                )
                state = adapter.state_for(position.position_id)
                self.assertAlmostEqual(state.target, self.L_CANONICAL, places=9)

    def test_removing_the_carried_target_does_not_move_the_canonical_one(self) -> None:
        for side, fill, stop, canonical in (
            (Side.BUY, self.L_FILL, self.L_STOP, self.L_CANONICAL),
            (Side.SELL, self.S_FILL, self.S_STOP, self.S_CANONICAL),
        ):
            with self.subTest(side=side):
                _, adapter, position = self._open(
                    side=side, fill=fill, stop=stop, carried=None
                )
                state = adapter.state_for(position.position_id)
                self.assertAlmostEqual(state.target, canonical, places=9)

    def test_a_position_with_no_ratio_is_skipped_not_guessed(self) -> None:
        """Without the strategy's ratio there is no §4.2 input. The carried
        target must not be used to invent one."""
        broker = PaperBroker(SPEC, NO_COST)
        adapter = TradeAdapter(broker)
        broker.submit_market_order(
            side=Side.BUY, volume=1.00, stop_loss=self.L_STOP,
            take_profit=self.L_LEGACY, decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=self.L_FILL, high=2445.0,
                              low=2443.0, close=self.L_FILL),
            metadata={},
        )
        position = broker.open_positions()[0]
        self.assertIsNone(adapter.on_position_opened(position))
        self.assertIsNone(adapter.state_for(position.position_id))

    # -- the anchors ------------------------------------------------------

    def test_the_anchor_is_the_fill_not_the_intended_entry(self) -> None:
        _, adapter, position = self._open(
            side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP, carried=self.L_LEGACY
        )
        state = adapter.state_for(position.position_id)
        intended_r = abs(self.INTENDED - self.L_STOP)
        self.assertNotAlmostEqual(state.r, intended_r, places=6)
        self.assertNotAlmostEqual(
            state.target, self.INTENDED + self.RATIO * intended_r, places=6
        )

    def test_r_comes_from_the_original_stop_not_the_promoted_one(self) -> None:
        """The stop moves to breakeven at 1R; R and the target do not."""
        broker, adapter, position = self._open(
            side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP, carried=self.L_LEGACY
        )
        state = adapter.state_for(position.position_id)
        one_r = state.m1r
        self.assertAlmostEqual(one_r, self.L_FILL + self.L_R, places=9)

        # A bar that reaches 1R without reaching the target.
        reach = bar(5, open_=self.L_FILL, high=one_r + 0.5,
                    low=self.L_FILL - 0.5, close=one_r)
        bar_time = pd.Timestamp(reach["time"]).to_pydatetime()
        broker.fill_pending_orders(reach, bar_time)
        adapter.manage(reach, bar_time)

        after = adapter.state_for(position.position_id)
        self.assertIs(after.stop_state_confirmed, StopState.BREAKEVEN)
        self.assertGreater(after.confirmed_stop_price, self.L_STOP)
        # R and the target are frozen at creation (§6.1) and must not follow.
        self.assertAlmostEqual(after.original_stop_price, self.L_STOP, places=9)
        self.assertAlmostEqual(after.r, self.L_R, places=9)
        self.assertAlmostEqual(after.target, self.L_CANONICAL, places=9)

    def test_the_ratio_is_the_strategys_own(self) -> None:
        for ratio in (1.5, 2.0, 4.5):
            with self.subTest(ratio=ratio):
                _, adapter, position = self._open(
                    side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP,
                    carried=self.L_LEGACY, ratio=ratio,
                )
                state = adapter.state_for(position.position_id)
                self.assertAlmostEqual(state.tp_ratio, ratio, places=9)
                self.assertAlmostEqual(
                    state.target, self.L_FILL + ratio * self.L_R, places=9
                )

    def test_reward_over_r_equals_the_ratio(self) -> None:
        """The property the recomputation exists to guarantee."""
        for side, fill, stop in (
            (Side.BUY, self.L_FILL, self.L_STOP),
            (Side.SELL, self.S_FILL, self.S_STOP),
        ):
            for ratio in (1.5, 3.0, 4.5):
                with self.subTest(side=side, ratio=ratio):
                    _, adapter, position = self._open(
                        side=side, fill=fill, stop=stop, carried=None, ratio=ratio
                    )
                    state = adapter.state_for(position.position_id)
                    reward = abs(state.target - state.entry_price)
                    self.assertAlmostEqual(reward / state.r, ratio, places=9)

    def test_the_broker_projection_follows_the_canonical_target(self) -> None:
        """The carried level is overwritten, so nothing downstream can read it."""
        _, _, position = self._open(
            side=Side.BUY, fill=self.L_FILL, stop=self.L_STOP, carried=self.L_LEGACY
        )
        self.assertAlmostEqual(position.take_profit, self.L_CANONICAL, places=9)


class BrokerDecidesNothing(AdapterHarness):
    """CO-16: the broker closes nothing on its own."""

    def test_a_stop_bar_alone_closes_nothing_without_the_adapter(self) -> None:
        candidate = bar(5, open_=2440.0, high=2445.0, low=2419.0, close=2425.0)
        bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
        opened = self.broker.fill_pending_orders(candidate, bar_time)
        self.assertEqual(opened, [], "fill_pending_orders returns opened, not closed")
        self.assertTrue(self.position.is_open)
        self.assertEqual(self.broker.closed_positions(), [])

    def test_a_target_bar_alone_closes_nothing_without_the_adapter(self) -> None:
        candidate = bar(5, open_=2500.0, high=2545.0, low=2499.0, close=2542.0)
        bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
        self.broker.fill_pending_orders(candidate, bar_time)
        self.assertTrue(self.position.is_open)

    def test_the_broker_still_counts_bars(self) -> None:
        candidate = bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0)
        bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
        self.broker.fill_pending_orders(candidate, bar_time)
        self.assertEqual(self.position.bars_held, 1)


class DomainDrivesExits(AdapterHarness):
    """The adapter instructs; the broker executes."""

    def test_the_domain_closes_on_the_stop(self) -> None:
        closed = self.feed(bar(5, open_=2440.0, high=2445.0, low=2419.0, close=2425.0))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        event = self.first(TradeEventKind.POSITION_CLOSED)
        self.assertIs(event.reason, ClosureReason.STOP)

    def test_the_domain_closes_on_the_target(self) -> None:
        closed = self.feed(bar(5, open_=2500.0, high=2545.0, low=2499.0, close=2542.0))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)

    def test_a_gapped_stop_fills_at_the_observed_reference(self) -> None:
        closed = self.feed(bar(5, open_=2400.0, high=2405.0, low=2395.0, close=2402.0))
        request = self.first(TradeEventKind.CLOSE_REQUESTED)
        self.assertAlmostEqual(request.requested_level, STOP, places=9)
        self.assertAlmostEqual(request.observed_reference, 2400.0, places=9)
        self.assertAlmostEqual(closed[0].exit_price, 2400.0, places=9)

    def test_a_bar_touching_neither_level_leaves_it_open(self) -> None:
        closed = self.feed(bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0))
        self.assertEqual(closed, [])
        self.assertTrue(self.position.is_open)

    def test_closed_only_after_the_broker_confirms(self) -> None:
        self.feed(bar(5, open_=2500.0, high=2545.0, low=2499.0, close=2542.0))
        state = self.adapter.state_for(self.position.position_id)
        self.assertIs(state.lifecycle, PositionLifecycle.CLOSED)
        self.assertIs(state.closure_reason, ClosureReason.TARGET)
        self.assertIsNotNone(state.closure_fill_price)


class LadderManagement(AdapterHarness):
    """The partial and the stop promotions now really happen."""

    def test_1r_takes_a_partial_and_moves_the_broker_stop(self) -> None:
        self.feed(bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0))
        partial = self.first(TradeEventKind.PARTIAL_CLOSE)
        self.assertIsNotNone(partial)
        self.assertEqual(partial.steps, 50)
        self.assertAlmostEqual(self.position.remaining_volume, 0.50, places=9)
        self.assertAlmostEqual(self.position.stop_loss, ENTRY, places=9)
        self.assertAlmostEqual(self.position.original_stop, STOP, places=9)

    def test_2r_locks_one_r(self) -> None:
        self.feed(bar(5, open_=2460.0, high=2515.0, low=2459.0, close=2512.0))
        promotions = self.all_of(TradeEventKind.STOP_PROMOTED)
        self.assertEqual(len(promotions), 2)
        self.assertIs(promotions[-1].stop_state, StopState.LOCKED_1R)
        self.assertAlmostEqual(self.position.stop_loss, ONE_R, places=9)

    def test_the_promoted_stop_binds_from_the_next_bar(self) -> None:
        closed = self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2470.0, high=2472.0, low=2449.0, close=2452.0),
        )
        self.assertEqual(len(closed), 1)
        request = [e for e in self.adapter.events
                   if e.kind is TradeEventKind.CLOSE_REQUESTED][-1]
        self.assertAlmostEqual(request.requested_level, ENTRY, places=9)

    def test_a_single_step_position_promotes_without_a_partial(self) -> None:
        """floor(1/2) is zero, so no order is sent, but the stop still moves."""
        broker = PaperBroker(SPEC, NO_COST)
        adapter = TradeAdapter(broker)
        broker.submit_market_order(
            side=Side.BUY, volume=0.01, stop_loss=STOP, take_profit=TARGET,
            decision_time=T0, decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=ENTRY, high=2451.0, low=2449.0, close=2450.5),
            metadata={"strategy_rr_ratio": 3.0},
        )
        position = broker.open_positions()[0]
        adapter.on_position_opened(position)
        candidate = bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0)
        bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
        broker.fill_pending_orders(candidate, bar_time)
        adapter.manage(candidate, bar_time)

        self.assertEqual(
            [e for e in adapter.events if e.kind is TradeEventKind.PARTIAL_CLOSE], []
        )
        self.assertAlmostEqual(position.remaining_volume, 0.01, places=9)
        self.assertAlmostEqual(position.stop_loss, ENTRY, places=9)


class OneRecordPerPosition(AdapterHarness):
    """Phase 3 ledger: a partial is an execution, never a second trade."""

    def test_a_partial_and_a_final_make_one_record_with_three_executions(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        )
        self.assertEqual(len(self.adapter.records), 1, "one position, one trade")
        record = self.adapter.records[0]
        self.assertEqual(len(record.executions), 3, "entry, partial, final")
        self.assertEqual(len(record.exit_executions), 2)
        self.assertEqual(record.closed_quantity_steps, 100)

    def test_aggregate_pnl_is_the_sum_of_the_executions(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        )
        record = self.adapter.records[0]
        self.assertAlmostEqual(
            record.gross_pnl, sum(e.gross_pnl for e in record.executions), places=9
        )

    def test_risk_uses_the_original_stop_after_promotion(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        )
        record = self.adapter.records[0]
        self.assertAlmostEqual(record.price_risk, 30.0, places=9)
        self.assertAlmostEqual(record.original_stop_price, STOP, places=9)
        self.assertAlmostEqual(record.final_stop_price, ONE_R, places=9)
        self.assertIsNotNone(record.r_multiple)

    def test_bars_held_is_position_level_and_not_doubled(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        )
        self.assertEqual(self.adapter.records[0].bars_held, 2)


class Idempotency(AdapterHarness):
    """Record-then-apply, and the duplicate gate in front of the domain."""

    def test_every_execution_is_recorded_once(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2490.0, high=2545.0, low=2489.0, close=2542.0),
        )
        fills = self.adapter.fill_log.fills_for(self.canonical_id)
        self.assertEqual(len(fills), 3)
        self.assertEqual(len({f.fill_id for f in fills}), 3)

    def test_the_milestone_fires_once_across_many_bars(self) -> None:
        self.feed(
            bar(5, open_=2460.0, high=2485.0, low=2459.0, close=2482.0),
            bar(10, open_=2482.0, high=2486.0, low=2481.0, close=2484.0),
            bar(15, open_=2484.0, high=2487.0, low=2483.0, close=2485.0),
        )
        self.assertEqual(len(self.all_of(TradeEventKind.PARTIAL_CLOSE)), 1)
        self.assertAlmostEqual(self.position.remaining_volume, 0.50, places=9)

    def test_a_closed_position_is_not_managed_again(self) -> None:
        self.feed(bar(5, open_=2500.0, high=2545.0, low=2499.0, close=2542.0))
        before = len(self.adapter.events)
        self.feed(bar(10, open_=2550.0, high=2560.0, low=2545.0, close=2555.0))
        self.assertEqual(len(self.adapter.events), before)


class AmbiguityAndPolicy(AdapterHarness):
    """D16: the policy annotates; the domain resolves adverse-first."""

    policy = IntrabarPolicy.OPTIMISTIC

    def test_the_domain_resolves_adverse_first_whatever_the_policy(self) -> None:
        closed = self.feed(bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0))
        self.assertEqual(len(closed), 1)
        self.assertIs(
            closed[0].state, PositionState.CLOSED_STOP,
            "the broker policy is OPTIMISTIC and must not change the outcome",
        )
        event = self.first(TradeEventKind.POSITION_CLOSED)
        self.assertIs(event.reason, ClosureReason.STOP)
        self.assertTrue(event.ambiguous)

    def test_ambiguity_reaches_the_record(self) -> None:
        self.feed(bar(5, open_=2450.0, high=2545.0, low=2419.0, close=2430.0))
        self.assertTrue(self.adapter.records[0].was_ambiguous_exit)


class EndOfData(AdapterHarness):
    """The adapter supplies the reason; the domain has no dataset concept."""

    def test_an_open_position_closes_as_end_of_data(self) -> None:
        self.feed(bar(5, open_=2460.0, high=2470.0, low=2455.0, close=2465.0))
        closed = self.adapter.close_all_at_end_of_data(2465.0, T0 + timedelta(minutes=10))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_END_OF_DATA)
        record = self.adapter.records[0]
        self.assertEqual(record.outcome, "END_OF_DATA")
        self.assertEqual(record.closed_quantity_steps, 100)


class LimitFillHandsOffToManagement(unittest.TestCase):
    """R1 for a limit fill: the fill bar is managed, by the domain.

    Moved here from the pending-order suite, which now covers filling only.
    The broker fills in phase B and the adapter manages the same bar, so a
    position can still exit on the bar it filled on -- the behaviour commit
    a4f7141 established.
    """

    ZONE_LOW, ZONE_HIGH = 2398.0, 2406.0
    MID = 2402.0
    FORMATION = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)
    NEXT = FORMATION + timedelta(minutes=5)

    # The limit fills at MID, so R = 6.00 against the 2396.00 stop and the
    # §4.2 target is 2402 + 3 x 6 = 2420.00. The carried target below is
    # deliberately somewhere else: these bars must be built around the
    # canonical level, not the one the intent happens to carry.
    STOP = 2396.0
    CANONICAL_TARGET = 2420.0
    CARRIED_TARGET = 2404.5

    def _intent(self, *, stop: float, target: float) -> PendingOrderIntent:
        return PendingOrderIntent(
            side=Side.BUY, limit_price=self.MID, stop_loss=stop, take_profit=target,
            zone_low=self.ZONE_LOW, zone_high=self.ZONE_HIGH,
            formation_bar_time=self.FORMATION, decision_time=self.FORMATION,
        )

    def _bar(self, o: float, h: float, l: float, c: float) -> pd.Series:
        return pd.Series(
            {"time": pd.Timestamp(self.NEXT), "open": o, "high": h, "low": l, "close": c}
        )

    def _run(self, *, stop: float, target: float, candidate: pd.Series):
        broker = PaperBroker(SPEC, NO_COST)
        adapter = TradeAdapter(broker)
        broker.submit_limit_order(
            self._intent(stop=stop, target=target),
            volume=0.01,
            metadata={"strategy_rr_ratio": 3.0},
        )
        filled = []
        for position in broker.fill_pending_orders(candidate, self.NEXT):
            adapter.on_position_opened(position)
            filled.append(position.position_id)
        closed = adapter.manage(candidate, self.NEXT)
        self.assertEqual(len(filled), 1, "the limit should have filled")
        return adapter, filled[0], closed

    def test_the_fill_bar_geometry_is_canonical(self) -> None:
        """The premise of the bars below: the limit fills at MID and the
        target is recomputed from it, not taken from the intent."""
        adapter, pid, _ = self._run(
            stop=self.STOP, target=self.CARRIED_TARGET,
            candidate=self._bar(2403.0, 2405.0, 2401.0, 2404.0),
        )
        state = adapter.state_for(pid)
        self.assertAlmostEqual(state.entry_price, self.MID, places=9)
        self.assertAlmostEqual(state.r, 6.0, places=9)
        self.assertAlmostEqual(state.target, self.CANONICAL_TARGET, places=9)

    def test_fill_then_stop_on_the_same_bar(self) -> None:
        _, _, closed = self._run(
            stop=self.STOP, target=self.CARRIED_TARGET,
            candidate=self._bar(2404.0, 2405.0, 2395.0, 2397.0),
        )
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertAlmostEqual(closed[0].exit_price, self.STOP, places=9)

    def test_fill_then_target_on_the_same_bar(self) -> None:
        # The bar reaches the canonical 2420.00, not the carried 2404.50.
        _, _, closed = self._run(
            stop=self.STOP, target=self.CARRIED_TARGET,
            candidate=self._bar(2403.0, 2421.0, 2401.0, 2420.5),
        )
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_TARGET)
        self.assertAlmostEqual(closed[0].exit_price, self.CANONICAL_TARGET, places=9)

    def test_reaching_only_the_carried_target_does_not_close(self) -> None:
        """§4.2 from the other side: the carried level has no authority."""
        adapter, pid, closed = self._run(
            stop=self.STOP, target=self.CARRIED_TARGET,
            candidate=self._bar(2403.0, 2405.0, 2401.0, 2404.8),
        )
        self.assertEqual(closed, [])
        state = adapter.state_for(pid)
        self.assertIs(state.lifecycle, PositionLifecycle.OPEN)

    def test_fill_then_both_resolves_adverse_first_and_flags_it(self) -> None:
        adapter, pid, closed = self._run(
            stop=self.STOP, target=self.CARRIED_TARGET,
            candidate=self._bar(2403.0, 2421.0, 2395.0, 2400.0),
        )
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertTrue(closed[0].was_ambiguous_exit)

    def test_the_broker_policy_cannot_change_that_outcome(self) -> None:
        """The same bar under OPTIMISTIC still resolves to the stop."""
        broker = PaperBroker(SPEC, NO_COST, intrabar_policy=IntrabarPolicy.OPTIMISTIC)
        adapter = TradeAdapter(broker)
        broker.submit_limit_order(
            self._intent(stop=self.STOP, target=self.CARRIED_TARGET),
            volume=0.01,
            metadata={"strategy_rr_ratio": 3.0},
        )
        candidate = self._bar(2403.0, 2421.0, 2395.0, 2400.0)
        for position in broker.fill_pending_orders(candidate, self.NEXT):
            adapter.on_position_opened(position)
        closed = adapter.manage(candidate, self.NEXT)
        self.assertIs(closed[0].state, PositionState.CLOSED_STOP)
        self.assertTrue(closed[0].was_ambiguous_exit)


class CutOverInvariants(unittest.TestCase):
    """Static guards that the old exit authority cannot come back.

    These read the source rather than run it, because the thing being
    prevented is a future edit reinstating a second decision-maker.
    """

    BROKER = Path(__file__).resolve().parents[2] / "execution" / "paper_broker.py"
    ADAPTER = Path(__file__).resolve().parents[2] / "execution" / "trade_adapter.py"
    REPLAY = Path(__file__).resolve().parents[2] / "backtest" / "replay_engine.py"

    def test_the_broker_no_longer_references_the_intrabar_resolver(self) -> None:
        """CO-2: the policy may annotate, but it may not select an exit."""
        self.assertNotIn("resolve_intrabar", self.BROKER.read_text(encoding="utf-8"))

    def test_the_broker_has_no_time_based_closure(self) -> None:
        """CO: max_bars_held retired; CLOSED_TIME stays defined but unproduced."""
        source = self.BROKER.read_text(encoding="utf-8")
        self.assertNotIn("max_bars_held", source)
        self.assertNotIn("CLOSED_TIME", source)

    def test_closed_time_vocabulary_still_exists(self) -> None:
        """Retiring the mechanism must not remove the label."""
        from backtest.ledger import TradeOutcome

        self.assertTrue(hasattr(PositionState, "CLOSED_TIME"))
        self.assertTrue(hasattr(TradeOutcome, "TIME_EXIT"))

    def test_only_the_adapter_instructs_the_close_verbs(self) -> None:
        """CO-1: a second caller would be a second exit authority."""
        callers = []
        root = Path(__file__).resolve().parents[2]
        for path in list((root / "execution").glob("*.py")) + list(
            (root / "backtest").glob("*.py")
        ):
            if path.name in ("paper_broker.py", "trade_adapter.py"):
                continue
            text = path.read_text(encoding="utf-8")
            for verb in ("execute_close(", "execute_partial_close(",
                         "execute_stop_modify("):
                if verb in text:
                    callers.append(f"{path.name}:{verb}")
        self.assertEqual(callers, [])

    def test_canonical_results_are_applied_only_through_the_adapter(self) -> None:
        """CO-4: everything quantity-changing goes through record_then_apply."""
        root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in list((root / "execution").glob("*.py")) + list(
            (root / "backtest").glob("*.py")
        ):
            if path.name == "trade_adapter.py":
                continue
            if "apply_broker_result" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_replay_engine_drives_the_adapter_not_the_old_exit_path(self) -> None:
        source = self.REPLAY.read_text(encoding="utf-8")
        self.assertIn("adapter.manage(", source)
        self.assertIn("record_canonical(", source)
        self.assertNotIn(".on_bar(", source)

    def test_the_adapter_records_before_it_applies(self) -> None:
        """CO-17/18: record and apply are inseparable, in that order."""
        source = self.ADAPTER.read_text(encoding="utf-8")
        self.assertIn("record_then_apply(", source)
        self.assertEqual(
            source.count("record_then_apply("), 3,
            "one call per quantity-changing result: partial, close, end of data",
        )


if __name__ == "__main__":
    unittest.main()
