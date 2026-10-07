"""Deterministic replay engine.

Drives the **unmodified** production strategy over historical bars.

What it does not do
-------------------
It does not reimplement, wrap, patch or fork any strategy logic. It calls
``main_production.detect_regime`` and ``main_production.analyze_entry`` exactly
as the live loop does, with frames shaped exactly as
``mt5_handler.get_market_data`` produces them. If it did anything else, the
resulting numbers would describe a different strategy from the one in production.

Determinism
-----------
The engine is event-driven on bar closes. There is no ``time.sleep`` and no
wall-clock read: :mod:`backtest.clock_patch` freezes the ambient clock inside the
strategy modules for the duration of each decision, so the same dataset produces
the same output on any machine, in any timezone, at any time of day.

Signal snapshots are captured at the moment of the decision
------------------------------------------------------------
Everything needed to describe a decision -- regime, layers passed, entry levels,
what each timeframe could see -- is recorded **while it is being made**, never
reconstructed afterwards from historical data. Reconstruction would risk
rebuilding the decision with information that arrived later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from backtest.clock_patch import frozen_clock
from backtest.ledger import TradeLedger, TradeOutcome
from execution.trade_adapter import TradeAdapter
from core.symbols import SymbolSpecification
from core.types import DomainInvariantError, PendingOrderIntent, Side, Timeframe
from data.replay_feed import BarAvailability, ReplayFeed
from execution.broker import FillStatus
from execution.paper_broker import DEFAULT_SIMULATED_VOLUME, PaperBroker

__all__ = ["DecisionSnapshot", "ReplayConfig", "ReplayEngine", "ReplayResult"]


# Bar counts requested per timeframe, mirroring main_production.CONFIG exactly.
# Changing these would change what the strategy sees, so they are pinned here
# and asserted against CONFIG in tests/backtest/test_replay_engine.py.
DEFAULT_BAR_COUNTS: dict[Timeframe, int] = {
    Timeframe.H4: 100,
    Timeframe.H1: 60,
    Timeframe.M15: 50,
    Timeframe.M5: 100,
    Timeframe.M1: 200,
    Timeframe.D1: 10,
}


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    """Everything known at one replay instant, captured as the decision is made.

    Attributes:
        replay_time: The decision instant.
        availability: What each timeframe could see, per timeframe.
        current_price: Price handed to the strategy.
        spread_pips: Spread handed to the strategy.
        regime: Regime the strategy reported.
        signal_type: ``ENTRY_SIGNAL`` / ``PRE_ENTRY`` / ``NO_SIGNAL`` / ``ERROR``.
        direction: Side the strategy was considering.
        layers_passed: Layers the decision cleared.
        layer_failed: Layer that blocked it, if any.
        fail_reason: The strategy's own explanation.
        entry_signal: The entry payload, when one was produced.
    """

    replay_time: datetime
    availability: dict[Timeframe, BarAvailability]
    current_price: float | None
    spread_pips: float
    regime: str
    signal_type: str
    direction: str
    layers_passed: tuple[str, ...]
    layer_failed: str
    fail_reason: str
    entry_signal: dict | None = None

    def describe(self) -> str:
        """Return a multi-line description for debugging and integrity checks.

        Includes the latest closed bar per timeframe, so a reader can verify by
        inspection that no timeframe was ahead of ``replay_time``.
        """
        lines = [f"replay_time  = {self.replay_time.isoformat()}"]
        for timeframe in sorted(self.availability, key=lambda tf: -tf.minutes):
            lines.append(f"  {self.availability[timeframe].describe()}")
        price = "N/A" if self.current_price is None else f"{self.current_price:.2f}"
        lines.append(f"  current_price={price} spread={self.spread_pips:.1f}pip")
        lines.append(
            f"  regime={self.regime} signal={self.signal_type} side={self.direction} "
            f"passed={','.join(self.layers_passed) or 'NONE'} blocked={self.layer_failed}"
        )
        if self.fail_reason:
            lines.append(f"  reason={self.fail_reason}")
        return "\n".join(lines)


@dataclass(slots=True)
class ReplayConfig:
    """Parameters for one replay run.

    Attributes:
        driving_timeframe: Timeframe whose bar closes trigger decisions.
        start: Optional first decision instant.
        end: Optional last decision instant.
        max_open_positions: Concurrency cap, mirroring production.
        volume: Fixed simulated size in lots. See
            :data:`~execution.paper_broker.DEFAULT_SIMULATED_VOLUME`.
        bar_counts: Bars requested per timeframe.
        capture_all_snapshots: Retain a snapshot for every decision. Useful for
            debugging and required by the leakage tests; memory-hungry over long
            runs, so the runner disables it for full datasets.
        warmup_bars: Decisions to skip at the start so every frame is populated.
        progress_every: Emit a progress callback every N decisions.
    """

    driving_timeframe: Timeframe = Timeframe.M5
    start: datetime | None = None
    end: datetime | None = None
    max_open_positions: int = 3
    volume: float = DEFAULT_SIMULATED_VOLUME
    bar_counts: dict[Timeframe, int] = field(
        default_factory=lambda: dict(DEFAULT_BAR_COUNTS)
    )
    capture_all_snapshots: bool = False
    warmup_bars: int = 0
    progress_every: int = 0


@dataclass(slots=True)
class ReplayResult:
    """Output of one replay run.

    Attributes:
        ledger: Simulated trades and rejections.
        snapshots: Decision snapshots retained during the run.
        decisions: Total decisions evaluated.
        signals: Entry signals generated.
        errors: Decisions whose strategy call raised.
        first_decision_time: First decision instant.
        last_decision_time: Last decision instant.
        pending_orders: Every pending order created, in creation order,
            including those that never filled. Populated at the end of a run so
            the research layer can distinguish created / still-waiting /
            reached / filled without reaching into the broker.
    """

    ledger: TradeLedger
    snapshots: list[DecisionSnapshot] = field(default_factory=list)
    decisions: int = 0
    signals: int = 0
    pending_orders: list = field(default_factory=list)
    errors: int = 0
    first_decision_time: datetime | None = None
    last_decision_time: datetime | None = None


class ReplayEngine:
    """Runs the production strategy over historical bars.

    Args:
        feed: Historical data feed.
        broker: Paper broker for simulated fills.
        spec: Broker symbol specification.
        config: Replay parameters.
        strategy: Object exposing ``detect_regime`` and ``analyze_entry``.
            Defaults to the real ``main_production`` module. Injectable so tests
            can substitute a stub without importing MetaTrader5.
    """

    __slots__ = ("_feed", "_broker", "_spec", "_config", "_strategy", "_adapter")

    def __init__(
        self,
        feed: ReplayFeed,
        broker: PaperBroker,
        spec: SymbolSpecification,
        config: ReplayConfig | None = None,
        strategy: Any | None = None,
    ) -> None:
        self._feed = feed
        self._broker = broker
        self._adapter: TradeAdapter | None = None
        self._spec = spec
        self._config = config or ReplayConfig()
        self._strategy = strategy

    def _load_strategy(self) -> Any:
        """Return the strategy module, importing it lazily.

        Imported on first use rather than at module scope so the engine can be
        constructed and unit-tested in environments without MetaTrader5.

        Returns:
            The strategy object.
        """
        if self._strategy is None:
            import main_production

            self._strategy = main_production
        return self._strategy

    def _frames_at(self, as_of: datetime) -> dict[Timeframe, pd.DataFrame]:
        """Return the bar frames visible at ``as_of``.

        Args:
            as_of: Replay time.

        Returns:
            One frame per configured timeframe.
        """
        return {
            timeframe: self._feed.bars(timeframe, count, as_of)
            for timeframe, count in self._config.bar_counts.items()
        }

    def run(self, on_progress: Callable[[int, datetime], None] | None = None) -> ReplayResult:
        """Execute the replay.

        Args:
            on_progress: Optional callback receiving ``(decision_index, time)``.

        Returns:
            A :class:`ReplayResult`.
        """
        strategy = self._load_strategy()
        config = self._config
        ledger = TradeLedger()
        result = ReplayResult(ledger=ledger)
        # The canonical domain owns every exit decision from here; the broker
        # executes what this adapter instructs and decides nothing.
        adapter = TradeAdapter(self._broker)
        self._adapter = adapter

        decision_times = self._feed.decision_times(
            config.driving_timeframe, config.start, config.end
        )
        if config.warmup_bars:
            decision_times = decision_times[config.warmup_bars:]

        rejected = 0

        for index, raw_time in enumerate(decision_times):
            replay_time = pd.Timestamp(raw_time).to_pydatetime()

            # 1. Advance open positions on the bar that just closed. This runs
            #    before the new decision so a position can close on the same bar
            #    that triggers the next evaluation, as it would live.
            just_closed = self._feed.bars(config.driving_timeframe, 1, replay_time)
            if len(just_closed) > 0:
                bar = just_closed.iloc[-1]
                bar_time = pd.Timestamp(bar["time"]).to_pydatetime()
                for opened in self._broker.fill_pending_orders(bar, bar_time):
                    adapter.on_position_opened(opened)
                adapter.manage(bar, bar_time)
                for record in adapter.drain_records():
                    ledger.record_canonical(record)

            # 2. Take a decision using only what is visible now.
            frames = self._frames_at(replay_time)
            availability = self._feed.availability_snapshot(
                replay_time, list(config.bar_counts)
            )
            current_price = self._feed.price_at(replay_time)
            spread = self._feed.spread_at(replay_time)

            if any(len(frame) == 0 for frame in frames.values()):
                continue  # warmup: not every timeframe has data yet

            snapshot, entry_signal = self._decide(
                strategy, frames, availability, current_price, spread, replay_time
            )
            result.decisions += 1
            result.first_decision_time = result.first_decision_time or replay_time
            result.last_decision_time = replay_time

            if snapshot.signal_type == "ERROR":
                result.errors += 1
            if config.capture_all_snapshots:
                result.snapshots.append(snapshot)

            # 3. Act on an entry signal, filling on the NEXT bar's open.
            if entry_signal:
                result.signals += 1
                if not config.capture_all_snapshots:
                    result.snapshots.append(snapshot)
                rejected += self._submit(
                    entry_signal, snapshot, replay_time, availability, ledger
                )

            if on_progress and config.progress_every and index % config.progress_every == 0:
                on_progress(index, replay_time)

        # 4. Close anything still open; flagged END_OF_DATA and reported apart.
        #
        # Priced at the last decision instant, never at the wall clock. An
        # earlier version fell back to `datetime.now()` when no decision had
        # been taken; that value could never actually be used (the guard below
        # requires a decision to exist), but a wall-clock read inside a
        # deterministic engine is a hazard waiting for a future edit to reach.
        # Snapshot pending state before the end-of-data sweep, so orders that
        # never filled are still visible as PENDING rather than lost.
        collect = getattr(self._broker, "all_pending_orders", None)
        if callable(collect):
            result.pending_orders = collect()

        if result.last_decision_time is not None:
            final_price = self._feed.price_at(result.last_decision_time)
            if final_price is not None:
                adapter.close_all_at_end_of_data(final_price, result.last_decision_time)
                for record in adapter.drain_records():
                    ledger.record_canonical(record)

        return result

    def _decide(
        self,
        strategy: Any,
        frames: dict[Timeframe, pd.DataFrame],
        availability: dict[Timeframe, BarAvailability],
        current_price: float | None,
        spread: float,
        replay_time: datetime,
    ) -> tuple[DecisionSnapshot, dict | None]:
        """Run one strategy evaluation under a frozen clock.

        Args:
            strategy: The strategy module.
            frames: Bars visible at ``replay_time``.
            availability: Visibility snapshot, for the record.
            current_price: Reference price.
            spread: Spread in pips.
            replay_time: The decision instant.

        Returns:
            ``(snapshot, entry_signal_or_None)``.
        """
        with frozen_clock(replay_time):
            regime_info = strategy.detect_regime(
                frames[Timeframe.M5],
                frames[Timeframe.M15],
                frames[Timeframe.H1],
                current_spread=spread,
            )
            analysis = strategy.analyze_entry(
                frames[Timeframe.H4],
                frames[Timeframe.H1],
                frames[Timeframe.M15],
                frames[Timeframe.M5],
                frames[Timeframe.M1],
                frames[Timeframe.D1],
                current_price=current_price or 0.0,
                regime_info=regime_info,
            )

        entry_signal = analysis.get("entry_signal")
        snapshot = DecisionSnapshot(
            replay_time=replay_time,
            availability=availability,
            current_price=current_price,
            spread_pips=spread,
            regime=str(regime_info.get("regime", "UNKNOWN")),
            signal_type=str(analysis.get("signal_type", "NO_SIGNAL")),
            direction=str(analysis.get("direction", "")),
            layers_passed=tuple(analysis.get("layers_passed", [])),
            layer_failed=str(analysis.get("layer_failed") or "NONE"),
            fail_reason=str(analysis.get("fail_reason", "")),
            entry_signal=dict(entry_signal) if entry_signal else None,
        )
        if analysis.get("signal_type") == "ENTRY_SIGNAL" and entry_signal:
            return snapshot, dict(entry_signal)
        return snapshot, None

    def _submit(
        self,
        entry_signal: dict,
        snapshot: DecisionSnapshot,
        replay_time: datetime,
        availability: dict[Timeframe, BarAvailability],
        ledger: TradeLedger,
    ) -> int:
        """Submit an entry signal to the paper broker.

        Args:
            entry_signal: The strategy's entry payload.
            snapshot: The decision snapshot.
            replay_time: Decision instant.
            availability: Visibility snapshot, used for the decision bar time.
            ledger: Ledger to record rejections into.

        Returns:
            ``1`` if the order was rejected or unfillable, else ``0``.
        """
        try:
            side = Side.from_bias(str(entry_signal.get("position_type", "")))
        except Exception:
            ledger.record_rejection(
                decision_time=replay_time, side="UNKNOWN",
                outcome=TradeOutcome.REJECTED,
                reason=f"unrecognised position_type {entry_signal.get('position_type')!r}",
            )
            return 1

        stop_loss = entry_signal.get("stop_loss")
        take_profit = entry_signal.get("take_profit")
        if not stop_loss:
            ledger.record_rejection(
                decision_time=replay_time, side=side.value,
                outcome=TradeOutcome.REJECTED,
                reason="entry signal carried no stop loss",
            )
            return 1

        driving = self._config.driving_timeframe
        execution_bar = self._feed.next_bar_after(driving, replay_time)
        decision_bar_time = availability[driving].latest_open_time
        metadata = {
            "regime": snapshot.regime,
            "setup_type": entry_signal.get("setup_type", ""),
            "entry_method": entry_signal.get("entry_method", ""),
            "confidence": entry_signal.get("confidence_score", 0.0),
            "grade": entry_signal.get("grade", ""),
            "strategy_entry_price": entry_signal.get("entry_price"),
            # The strategy's OWN reported ratio, kept as a diagnostic only. It is
            # not an outcome measure: entry_engine derives the target as
            # risk x tp_ratio, so this always equals the regime constant
            # (PHASE_2_ISSUES E9). Realised R is computed from the actual fill.
            "strategy_rr_ratio": entry_signal.get("rr_ratio"),
            "strategy_stop_loss": entry_signal.get("stop_loss"),
            "strategy_take_profit": entry_signal.get("take_profit"),
            "layers_passed": list(snapshot.layers_passed),
        }

        # LIMIT_FVG: rest an order at the FVG midpoint instead of filling at
        # the next bar's open. Execution decides whether and when it fills; the
        # strategy only described where it should wait.
        if str(entry_signal.get("entry_mode", "")).upper() == "LIMIT_FVG":
            zone_low = entry_signal.get("fvg_zone_low")
            zone_high = entry_signal.get("fvg_zone_high")
            limit_price = entry_signal.get("limit_price")
            if zone_low is None or zone_high is None or limit_price is None:
                ledger.record_rejection(
                    decision_time=replay_time, side=side.value,
                    outcome=TradeOutcome.REJECTED,
                    reason="LIMIT_FVG signal carried no zone or limit price",
                    metadata=metadata,
                )
                return 1
            try:
                intent = PendingOrderIntent(
                    side=side,
                    limit_price=float(limit_price),
                    stop_loss=float(stop_loss),
                    take_profit=float(take_profit) if take_profit else None,
                    zone_low=float(zone_low),
                    zone_high=float(zone_high),
                    formation_bar_time=(
                        pd.Timestamp(decision_bar_time).to_pydatetime()
                        if decision_bar_time is not None
                        else replay_time
                    ),
                    decision_time=replay_time,
                    metadata=metadata,
                )
            except DomainInvariantError as error:
                ledger.record_rejection(
                    decision_time=replay_time, side=side.value,
                    outcome=TradeOutcome.REJECTED,
                    reason=f"LIMIT_FVG intent rejected: {error}",
                    metadata=metadata,
                )
                return 1
            self._broker.submit_limit_order(
                intent, volume=self._config.volume, metadata=metadata
            )
            return 0

        known = {p.position_id for p in self._broker.open_positions()}
        fill = self._broker.submit_market_order(
            side=side,
            volume=self._config.volume,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit) if take_profit else None,
            decision_time=replay_time,
            decision_bar_time=(
                pd.Timestamp(decision_bar_time).to_pydatetime()
                if decision_bar_time is not None
                else None
            ),
            execution_bar=execution_bar,
            metadata=metadata,
        )

        if fill.status is FillStatus.FILLED and self._adapter is not None:
            for position in self._broker.open_positions():
                if position.position_id not in known:
                    self._adapter.on_position_opened(position)

        if fill.status is not FillStatus.FILLED:
            outcome = (
                TradeOutcome.NO_EXECUTION_BAR
                if fill.status is FillStatus.NO_EXECUTION_BAR
                else TradeOutcome.REJECTED
            )
            ledger.record_rejection(
                decision_time=replay_time, side=side.value,
                outcome=outcome, reason=fill.reason, metadata=metadata,
            )
            return 1
        return 0
