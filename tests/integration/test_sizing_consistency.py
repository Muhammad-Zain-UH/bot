"""One sizing contract, shared by every path.

Two claims:

1. **There is only one implementation.** ``risk_manager`` adapts a percentage
   signature; it does not carry arithmetic of its own. The backtest and the
   production caller therefore cannot drift apart, because there is nothing to
   drift.
2. **The quantity survives the journey.** A size computed by the contract
   reaches the broker and the ledger unchanged, and the ledger's own P&L and R
   agree with the economics the size was derived from.

The second claim is the one the Phase 6 audit could not make: it found that the
legacy ``order_execution.execute_order`` never passed a volume to MT5 at all.
That path is legacy and is deliberately not repaired here; these tests pin the
canonical path instead.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from backtest.baseline import spec_from_broker_metadata
from backtest.ledger import TradeLedger
from core.sizing import lots_for_risk
from core.symbols import CalculationMode, XAUUSD_2DIGIT
from core.types import Side
from core.units import Pips
from execution.fills import FillModel
from execution.paper_broker import PaperBroker
from execution.trade_adapter import TradeAdapter
from risk_manager import calculate_lot_size_for_symbol

REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_METADATA = REPO_ROOT / "data" / "raw" / "broker_metadata.json"

T0 = datetime(2026, 3, 19, 9, 5, tzinfo=timezone.utc)
NO_COST = FillModel(spread=Pips(0.0), slippage=Pips(0.0))


def bar(minutes: int, *, open_: float, high: float, low: float, close: float):
    return pd.Series({
        "time": pd.Timestamp(T0 + timedelta(minutes=minutes)),
        "open": open_, "high": high, "low": low, "close": close,
    })


class OneImplementation(unittest.TestCase):
    """The percentage adapter must not introduce arithmetic of its own."""

    def test_risk_manager_agrees_with_the_contract(self) -> None:
        for balance, pct, entry, stop in (
            (10_000.0, 1.0, 2450.0, 2420.0),
            (100_000.0, 2.0, 2450.0, 2400.0),
            (5_000.0, 0.5, 2450.0, 2445.0),
            (250_000.0, 1.0, 2450.0, 2449.0),
        ):
            with self.subTest(balance=balance, pct=pct):
                adapted = calculate_lot_size_for_symbol(
                    "XAUUSD", balance, pct, entry, stop, spec=XAUUSD_2DIGIT
                )
                canonical = lots_for_risk(
                    XAUUSD_2DIGIT, balance=balance, risk_fraction=pct / 100.0,
                    stop_distance=abs(entry - stop),
                )
                self.assertAlmostEqual(adapted, canonical.lots, places=9)

    def test_an_untradeable_size_is_reported_as_zero_not_a_minimum(self) -> None:
        lots = calculate_lot_size_for_symbol(
            "XAUUSD", 100.0, 1.0, 2450.0, 2420.0, spec=XAUUSD_2DIGIT
        )
        self.assertEqual(lots, 0.0)

    def test_the_symbol_must_match_the_specification(self) -> None:
        with self.assertRaises(ValueError):
            calculate_lot_size_for_symbol(
                "EURUSD", 10_000.0, 1.0, 2450.0, 2420.0, spec=XAUUSD_2DIGIT
            )


class LiveAndBacktestEconomicsAgree(unittest.TestCase):
    """The broker-derived specification and the reference one must not disagree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads(BROKER_METADATA.read_text(encoding="utf-8"))
        cls.broker_spec = spec_from_broker_metadata(cls.metadata, pip_size=0.10)

    def test_the_broker_spec_is_cfd_leverage(self) -> None:
        self.assertIs(self.broker_spec.calc_mode, CalculationMode.CFD_LEVERAGE)

    def test_both_specs_price_a_move_identically(self) -> None:
        """Previously 10.0 for the broker spec and 100.0 for the reference one."""
        self.assertAlmostEqual(
            self.broker_spec.money_per_price_unit(1.0),
            XAUUSD_2DIGIT.money_per_price_unit(1.0),
            places=9,
        )
        self.assertAlmostEqual(self.broker_spec.money_per_price_unit(1.0), 100.0, places=9)

    def test_the_inconsistent_tick_value_is_still_carried_but_unused(self) -> None:
        """The field stays as the broker reported it; it just governs nothing."""
        self.assertAlmostEqual(self.broker_spec.tick_value, 0.1, places=9)
        self.assertNotAlmostEqual(
            self.broker_spec.tick_value / self.broker_spec.tick_size,
            self.broker_spec.money_per_price_unit(1.0),
            places=6,
        )

    def test_both_specs_size_identically(self) -> None:
        for balance, fraction, stop in (
            (10_000.0, 0.01, 30.0), (100_000.0, 0.02, 50.0), (2_500.0, 0.01, 7.5),
        ):
            with self.subTest(balance=balance, stop=stop):
                a = lots_for_risk(self.broker_spec, balance=balance,
                                  risk_fraction=fraction, stop_distance=stop)
                b = lots_for_risk(XAUUSD_2DIGIT, balance=balance,
                                  risk_fraction=fraction, stop_distance=stop)
                self.assertAlmostEqual(a.lots, b.lots, places=9)
                self.assertAlmostEqual(a.actual_risk, b.actual_risk, places=9)


class QuantityReachesTheBrokerAndTheLedger(unittest.TestCase):
    """Sizing -> order intent -> adapter -> broker -> ledger, one quantity."""

    ENTRY, STOP = 2450.0, 2420.0          # R = 30
    BALANCE, FRACTION = 100_000.0, 0.01   # -> 0.33 lots, $990 risk

    def setUp(self) -> None:
        self.decision = lots_for_risk(
            XAUUSD_2DIGIT, balance=self.BALANCE, risk_fraction=self.FRACTION,
            stop_distance=abs(self.ENTRY - self.STOP),
        )
        self.assertTrue(self.decision.tradeable)
        self.broker = PaperBroker(XAUUSD_2DIGIT, NO_COST)
        self.adapter = TradeAdapter(self.broker)
        self.broker.submit_market_order(
            side=Side.BUY,
            volume=self.decision.lots,
            stop_loss=self.STOP,
            take_profit=None,
            decision_time=T0,
            decision_bar_time=T0 - timedelta(minutes=5),
            execution_bar=bar(0, open_=self.ENTRY, high=2451.0, low=2449.0,
                              close=2450.5),
            metadata={"strategy_rr_ratio": 3.0},
        )
        self.position = self.broker.open_positions()[0]
        self.adapter.on_position_opened(self.position)

    def test_the_sized_quantity_is_what_the_broker_holds(self) -> None:
        self.assertAlmostEqual(self.decision.lots, 0.33, places=9)
        self.assertAlmostEqual(self.position.volume, 0.33, places=9)

    def test_the_canonical_state_carries_it_as_steps(self) -> None:
        state = self.adapter.state_for(self.position.position_id)
        self.assertEqual(state.steps_at_entry, 33)   # 0.33 / 0.01
        self.assertEqual(state.steps_remaining, 33)

    def test_the_ledger_records_the_same_quantity_and_risk(self) -> None:
        """Run to the stop: the realised loss must be the sized risk, at -1R."""
        ledger = TradeLedger()
        closed = []
        for candidate in (
            bar(5, open_=2445.0, high=2446.0, low=2419.0, close=2421.0),
        ):
            bar_time = pd.Timestamp(candidate["time"]).to_pydatetime()
            self.broker.fill_pending_orders(candidate, bar_time)
            closed.extend(self.adapter.manage(candidate, bar_time))
        self.assertEqual(len(closed), 1)
        for record in self.adapter.drain_records():
            ledger.record_canonical(record)

        trade = ledger.trades[0]
        self.assertAlmostEqual(trade.quantity, 0.33, places=9)
        self.assertAlmostEqual(trade.price_risk, 30.0, places=9)
        # The loss at the stop is exactly the money the sizing authorised.
        self.assertAlmostEqual(trade.net_pnl, -self.decision.actual_risk, places=6)
        self.assertAlmostEqual(trade.net_pnl, -990.0, places=6)
        self.assertAlmostEqual(trade.r_multiple, -1.0, places=9)

    def test_the_risk_taken_is_within_the_budget(self) -> None:
        self.assertLessEqual(
            self.decision.actual_risk, self.decision.risk_budget + 1e-9
        )
        self.assertAlmostEqual(self.decision.risk_budget, 1_000.0, places=9)
        self.assertAlmostEqual(self.decision.actual_risk, 990.0, places=9)


if __name__ == "__main__":
    unittest.main()
