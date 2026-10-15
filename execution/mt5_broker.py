"""MetaTrader 5 broker for a **DEMO account only** (forward test S1).

Implements :class:`execution.broker.Broker`. It is the one module under ``execution/`` that can
send an order, and it is narrowly constrained:

* The ``MetaTrader5`` module is **injected**, never imported here, so ``execution/`` stays
  importable without a terminal and contains no ``MetaTrader5`` import.
* Exactly one ``order_send`` call exists, in :meth:`MT5Broker._send`, and it refuses -- before
  every order -- unless ``account_info().trade_mode`` is DEMO and
  ``core.safety.LIVE_TRADING_ENABLED`` is still ``False``. A real-money account is never traded.
* Each instruction carries an ``operation_id`` (the order comment). An instruction whose
  operation already exists on the account is not sent again, so a retry or a restart cannot
  double-open or double-close.

Volume is rounded down to ``volume_step`` (and refused below ``volume_min``), the stop must be at
least ``trade_stops_level`` points away, and the filling mode comes from ``symbol_info``.
Broker timestamps are server wall time; the caller supplies ``server_to_utc``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from core.safety import assert_live_trading_disabled
from core.symbols import SymbolSpecification
from core.types import Side
from execution.broker import (BrokerExecutionResult, ExecutionStatus, FillStatus, PositionState,
                              SimulatedFill, SimulatedPosition)

__all__ = ["MT5Broker", "NotDemoAccountError", "OrderRejectedError"]

ACCOUNT_TRADE_MODE_DEMO = 0           # MT5 ENUM_ACCOUNT_TRADE_MODE
SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2   # symbol_info.filling_mode bit flags
DEAL_ENTRY_OUT = 1
DEAL_REASON_SL = 4


class NotDemoAccountError(RuntimeError):
    """The connected account is not a demo account; no order may be sent."""


class OrderRejectedError(RuntimeError):
    pass


class MT5Broker:
    """Demo-only MT5 execution for one symbol and one magic number."""

    def __init__(self, mt5: Any, spec: SymbolSpecification, *, magic: int,
                 server_to_utc: Callable[[int], datetime], deviation_points: int = 50):
        self._mt5 = mt5
        self._spec = spec
        self._magic = magic
        self._server_to_utc = server_to_utc
        self._deviation = deviation_points
        self._open: dict[str, SimulatedPosition] = {}
        self._closed: list[SimulatedPosition] = []

    @property
    def spec(self) -> SymbolSpecification:
        return self._spec

    def track(self, position: SimulatedPosition) -> None:
        """Track a position known from persisted state (restart), if not tracked already."""
        self._open.setdefault(position.position_id, position)

    # ------------------------------------------------------------ guards
    def require_demo(self) -> None:
        """Raise unless the connected account is a DEMO account."""
        info = self._mt5.account_info()
        demo = getattr(self._mt5, "ACCOUNT_TRADE_MODE_DEMO", ACCOUNT_TRADE_MODE_DEMO)
        if info is None or info.trade_mode != demo:
            mode = None if info is None else info.trade_mode
            raise NotDemoAccountError(
                f"account trade_mode is {mode!r}, not DEMO ({demo}); refusing to send any order")

    def _send(self, request: dict) -> Any:
        """The single order path. Refuses unless DEMO, before every order."""
        self.require_demo()
        assert_live_trading_disabled()
        return self._mt5.order_send(request)

    def filling_mode(self) -> int:
        info = self._mt5.symbol_info(self._spec.symbol)
        flags = int(getattr(info, "filling_mode", 0))
        if flags & SYMBOL_FILLING_FOK:
            return int(getattr(self._mt5, "ORDER_FILLING_FOK", 0))
        if flags & SYMBOL_FILLING_IOC:
            return int(getattr(self._mt5, "ORDER_FILLING_IOC", 1))
        return int(getattr(self._mt5, "ORDER_FILLING_RETURN", 2))

    def min_stop_distance(self) -> float:
        info = self._mt5.symbol_info(self._spec.symbol)
        return float(getattr(info, "trade_stops_level", 0)) * self._spec.point

    # ------------------------------------------------------------ identity
    def _positions(self) -> list:
        return [p for p in (self._mt5.positions_get(symbol=self._spec.symbol) or [])
                if int(p.magic) == self._magic]

    def _position_from_broker(self, p: Any) -> SimulatedPosition:
        side = Side.BUY if int(p.type) == int(getattr(self._mt5, "POSITION_TYPE_BUY", 0)) else Side.SELL
        pos = SimulatedPosition(position_id=str(p.ticket), symbol=self._spec.symbol, side=side,
                                volume=float(p.volume), entry_price=float(p.price_open),
                                stop_loss=float(p.sl), take_profit=(float(p.tp) or None),
                                entry_time=self._server_to_utc(int(p.time)))
        pos.original_stop_price = float(p.sl)
        pos.metadata["operation_id"] = str(p.comment)
        return pos

    def adopt_open_positions(self) -> list[SimulatedPosition]:
        """Track every open position on the account with this magic number (restart)."""
        for p in self._positions():
            self._open.setdefault(str(p.ticket), self._position_from_broker(p))
        return list(self._open.values())

    def deals_for_position(self, position_id: str) -> list:
        return list(self._mt5.history_deals_get(position=int(position_id)) or [])

    # ------------------------------------------------------------ Broker protocol
    def submit_market_order(self, *, side: Side, volume: float, stop_loss: float,
                            take_profit: float | None, decision_time: datetime,
                            decision_bar_time: datetime | None, metadata: dict | None = None) -> SimulatedFill:
        meta = dict(metadata or {})
        op = str(meta.get("operation_id", ""))
        if not op:
            raise ValueError("an operation_id is required for an idempotent order")

        def rejected(reason: str) -> SimulatedFill:
            return SimulatedFill(FillStatus.REJECTED, side, decision_time, decision_bar_time, decision_time,
                                 None, None, None, None, 0.0, reason)

        for p in self._positions():                       # already done: do not send again
            if str(p.comment) == op:
                pos = self._open.setdefault(str(p.ticket), self._position_from_broker(p))
                return SimulatedFill(FillStatus.FILLED, side, decision_time, decision_bar_time, decision_time,
                                     decision_time, decision_time, pos.entry_price, pos.entry_price,
                                     pos.volume, "already open (idempotent)")
        lots = self._spec.round_volume_to_step(volume)
        if lots < self._spec.volume_min:
            return rejected(f"volume {volume} rounds to {lots} < volume_min {self._spec.volume_min}")
        tick = self._mt5.symbol_info_tick(self._spec.symbol)
        price = float(tick.ask if side is Side.BUY else tick.bid)
        if abs(price - stop_loss) < self.min_stop_distance():
            return rejected(f"stop {stop_loss} closer than the broker minimum {self.min_stop_distance()}")
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL, "symbol": self._spec.symbol, "volume": lots,
            "type": self._mt5.ORDER_TYPE_BUY if side is Side.BUY else self._mt5.ORDER_TYPE_SELL,
            "price": price, "sl": float(stop_loss), "tp": float(take_profit or 0.0),
            "deviation": self._deviation, "magic": self._magic, "comment": op,
            "type_time": self._mt5.ORDER_TIME_GTC, "type_filling": self.filling_mode(),
        }
        res = self._send(request)
        if res is None or int(res.retcode) != int(self._mt5.TRADE_RETCODE_DONE):
            return rejected(f"order_send retcode {getattr(res, 'retcode', None)}: {getattr(res, 'comment', '')}")
        pos = SimulatedPosition(position_id=str(res.order), symbol=self._spec.symbol, side=side,
                                volume=float(res.volume), entry_price=float(res.price), stop_loss=float(stop_loss),
                                take_profit=take_profit, entry_time=decision_time,
                                metadata={**meta, "broker_order_id": str(res.order),
                                          "broker_deal_id": str(getattr(res, "deal", "")),
                                          "reference_price": price})
        pos.original_stop_price = float(stop_loss)
        self._open[pos.position_id] = pos
        return SimulatedFill(FillStatus.FILLED, side, decision_time, decision_bar_time, decision_time, decision_time,
                             decision_time, float(res.price), price, float(res.volume))

    def close_position(self, position_id: str, *, operation_id: str, decision_time: datetime) -> BrokerExecutionResult:
        """Close the whole position at market. Idempotent: a position already gone is not re-closed."""
        live = [p for p in self._positions() if str(p.ticket) == str(position_id)]
        if not live:
            return BrokerExecutionResult(ExecutionStatus.REJECTED, position_id, operation_id, 0.0, 0.0, None, None,
                                         decision_time, reason="position not open")
        p = live[0]
        side = Side.BUY if int(p.type) == int(getattr(self._mt5, "POSITION_TYPE_BUY", 0)) else Side.SELL
        tick = self._mt5.symbol_info_tick(self._spec.symbol)
        price = float(tick.bid if side is Side.BUY else tick.ask)
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL, "symbol": self._spec.symbol, "volume": float(p.volume),
            "type": self._mt5.ORDER_TYPE_SELL if side is Side.BUY else self._mt5.ORDER_TYPE_BUY,
            "position": int(p.ticket), "price": price, "deviation": self._deviation, "magic": self._magic,
            "comment": operation_id, "type_time": self._mt5.ORDER_TIME_GTC, "type_filling": self.filling_mode(),
        }
        res = self._send(request)
        if res is None or int(res.retcode) != int(self._mt5.TRADE_RETCODE_DONE):
            return BrokerExecutionResult(ExecutionStatus.REJECTED, position_id, operation_id, float(p.volume), 0.0,
                                         None, price, decision_time,
                                         reason=f"order_send retcode {getattr(res, 'retcode', None)}")
        pos = self._open.pop(str(position_id), None) or self._position_from_broker(p)
        pos.state, pos.exit_price, pos.exit_time, pos.exit_reason = (
            PositionState.CLOSED_TIME, float(res.price), decision_time, "time exit")
        self._closed.append(pos)
        return BrokerExecutionResult(ExecutionStatus.FILLED, position_id, operation_id, float(p.volume),
                                     float(res.volume), float(res.price), price, decision_time,
                                     broker_order_id=str(res.order), broker_deal_id=str(getattr(res, "deal", "")),
                                     closed_position=True)

    def on_bar(self, bar: pd.Series | None = None, bar_time: datetime | None = None) -> list[SimulatedPosition]:
        """Reconcile with the account: positions the server closed (e.g. the stop) are returned."""
        live = {str(p.ticket) for p in self._positions()}
        closed = []
        for pid in [k for k in self._open if k not in live]:
            pos = self._open.pop(pid)
            outs = [d for d in self.deals_for_position(pid) if int(d.entry) == DEAL_ENTRY_OUT]
            if outs:
                d = outs[-1]
                pos.exit_price, pos.exit_time = float(d.price), self._server_to_utc(int(d.time))
                stop = int(getattr(d, "reason", -1)) == int(getattr(self._mt5, "DEAL_REASON_SL", DEAL_REASON_SL))
                pos.state = PositionState.CLOSED_STOP if stop else PositionState.CLOSED_MANUAL
                pos.exit_reason = "stop" if stop else "closed outside this process"
            else:
                pos.state, pos.exit_reason = PositionState.CLOSED_MANUAL, "closed; no exit deal found"
            self._closed.append(pos)
            closed.append(pos)
        return closed

    def open_positions(self) -> list[SimulatedPosition]:
        return list(self._open.values())

    def closed_positions(self) -> list[SimulatedPosition]:
        return list(self._closed)
