"""Forward test S1 on the MetaQuotes-Demo account (research/v2026/FORWARD_S1_SPEC.md, fbb342d).

DEMO ONLY: orders go through execution.mt5_broker.MT5Broker, which refuses any non-demo account
before every order_send; core.safety.LIVE_TRADING_ENABLED stays False. This module never calls
order_send itself.

    venv\\Scripts\\python.exe -m gold.live.forward_s1          # run (Ctrl+C to stop; state is kept)

Each step: hourly clock check (server = Europe/Athens wall time, the v1b rule, measured against
the last tick), reconcile positions by magic number, exit at 11:00 UTC, enter at the first H1 bar
>= 60 minutes after the daily reopen, update the S2 paper log on each closed D1 bar. State is a JSON
file written atomically; trades go to data/forward/s1_trades.csv, S2 to data/forward/s2_signals.csv,
one summary line per trading day to data/forward/s1_daily.log.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from core.sizing import lots_for_risk
from core.symbols import SymbolSpecification
from core.types import Side

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forward"
SYMBOL = "XAUUSD"
MAGIC = 20261015
PIP_SIZE = 0.10
RISK_FRACTION = 0.0025
ATR_N = 14
SPREAD_LOOKBACK_DAYS = 20
SPREAD_MULTIPLE = 3.0
ENTRY_DELAY = timedelta(minutes=60)
EXIT_HOUR_UTC = 11
KILL_R = -6.0
MAX_DD_R = 8.0
FIRST_DAY, LAST_DAY = date(2026, 10, 15), date(2027, 1, 15)
S2_LOOKBACK, S2_HORIZONS = 20, (1, 3, 5)
CLOCK_CHECK_EVERY = timedelta(hours=1)
FRESH_TICK_S = 120
ATHENS = ZoneInfo("Europe/Athens")
UTC = timezone.utc
H = timedelta(hours=1)
TRADE_FIELDS = ["trading_day", "position_id", "entry_time_utc", "entry_bar_open", "entry_fill", "entry_slippage",
                "spread_entry", "stop", "lots", "risk_usd", "exit_time_utc", "exit_bar_close", "exit_fill",
                "exit_slippage", "spread_exit", "exit_reason", "gross_usd", "costs_usd", "net_usd", "net_r",
                "cum_r", "equity_after"]
S2_FIELDS = ["d1_time_utc", "direction", "close", "r_1d", "r_3d", "r_5d"]


# ---------------------------------------------------------------- clock (v1b rule, measured live)
def server_epoch_to_utc(epoch: int) -> datetime:
    """MT5 server timestamp (server wall time stored as epoch) -> UTC, v1b rule after 2020-07."""
    wall = datetime.fromtimestamp(int(epoch), UTC).replace(tzinfo=None)
    return wall.replace(tzinfo=ATHENS).astimezone(UTC)


def utc_to_server(dt_utc: datetime) -> datetime:
    """UTC -> server wall time, as the aware-UTC datetime MT5 range requests expect."""
    return dt_utc.astimezone(ATHENS).replace(tzinfo=UTC)


def expected_offset_hours(now_utc: datetime) -> int:
    return int(now_utc.astimezone(ATHENS).utcoffset().total_seconds() // 3600)


def measured_offset_hours(tick_server_epoch: int, now_utc: datetime) -> int | None:
    """Server - UTC in whole hours, or None when the last tick is not fresh (market closed)."""
    diff = int(tick_server_epoch) - now_utc.timestamp()
    hours = round(diff / 3600)
    return hours if abs(diff - hours * 3600) <= FRESH_TICK_S else None


# ---------------------------------------------------------------- pure rules
def session_reopen(bar_opens_utc: list[datetime], now_utc: datetime) -> datetime | None:
    """Open time of the latest H1 bar that follows at least one missing hour (the daily break or
    the weekend), among bars opened at or before now."""
    opens = [t for t in bar_opens_utc if t <= now_utc]
    for i in range(len(opens) - 1, 0, -1):
        if opens[i] - opens[i - 1] >= 2 * H:
            return opens[i]
    return None


def entry_bar_open(bar_opens_utc: list[datetime], reopen: datetime) -> datetime | None:
    """The first H1 bar opening at or after reopen + 60 minutes."""
    later = [t for t in bar_opens_utc if t >= reopen + ENTRY_DELAY]
    return min(later) if later else None


def trading_day(entry_utc: datetime) -> date:
    """The UTC date of the 11:00 UTC exit that follows an entry."""
    d = entry_utc.astimezone(UTC).date()
    return d if entry_utc.astimezone(UTC).hour < EXIT_HOUR_UTC else d + timedelta(days=1)


def exit_time(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, EXIT_HOUR_UTC, tzinfo=UTC)


def atr(highs, lows, closes, n: int = ATR_N) -> float:
    """Simple mean of the last n true ranges of closed D1 bars (needs n + 1 bars)."""
    h, l, c = (np.asarray(x, float) for x in (highs, lows, closes))
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def spread_skip(spread_now: float, history_spreads) -> tuple[bool, float]:
    med = float(np.median(np.asarray(history_spreads, float))) if len(history_spreads) else float("nan")
    return (not math.isfinite(med)) or spread_now > SPREAD_MULTIPLE * med, med


def killed(cum_r: float) -> bool:
    return cum_r <= KILL_R


def decision(net_r: list[float]) -> dict:
    r = np.asarray(net_r, float)
    if len(r) == 0:
        return {"n": 0, "decision": "STOP", "reason": "no trades"}
    cum = np.cumsum(r)
    max_dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:] - cum))
    sd = float(r.std(ddof=1)) if len(r) > 1 else float("nan")
    t = float(r.mean() / (sd / math.sqrt(len(r)))) if len(r) > 1 and sd > 0 else float("nan")
    go = r.mean() > 0 and max_dd < MAX_DD_R
    return {"n": int(len(r)), "mean_r": float(r.mean()), "sd_r": sd, "t": t, "max_dd_r": max_dd,
            "cum_r": float(cum[-1]), "decision": "CONTINUE" if go else "STOP",
            "note": "about 60 trades give an indication, not proof; no significance is claimed"}


def s2_signal(highs, lows, closes) -> str | None:
    """Direction of a breakout on the last closed D1 bar versus its prior 20 bars."""
    if len(closes) < S2_LOOKBACK + 1:
        return None
    c = closes[-1]
    if c > max(highs[-S2_LOOKBACK - 1:-1]):
        return "long"
    if c < min(lows[-S2_LOOKBACK - 1:-1]):
        return "short"
    return None


# ---------------------------------------------------------------- persistence
def atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


# ---------------------------------------------------------------- runner
@dataclass
class Paths:
    state: Path
    trades: Path
    s2: Path
    daily: Path

    @classmethod
    def under(cls, root: Path) -> "Paths":
        return cls(root / "s1_state.json", root / "s1_trades.csv", root / "s2_signals.csv", root / "s1_daily.log")


class ForwardS1:
    def __init__(self, mt5, broker, paths: Paths):
        self.mt5, self.broker, self.paths = mt5, broker, paths
        self.state = self._load()

    # -- state
    def _load(self) -> dict:
        if self.paths.state.exists():
            return json.loads(self.paths.state.read_text(encoding="utf-8"))
        return {"open": None, "done_days": [], "net_r": [], "killed": False, "clock_ok": None,
                "last_clock_check": None, "last_d1": None, "s2_pending": [], "first_entry_price": None,
                "last_exit_price": None, "skips": {}}

    def save(self) -> None:
        atomic_write_json(self.paths.state, self.state)

    def log_day(self, line: str) -> None:
        self.paths.daily.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.daily.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    # -- market data
    def _rates(self, timeframe, start: int, count: int):
        r = self.mt5.copy_rates_from_pos(SYMBOL, timeframe, start, count)
        return [] if r is None else list(r)

    def h1_opens(self) -> list[tuple[datetime, dict]]:
        return [(server_epoch_to_utc(int(b["time"])), b) for b in self._rates(self.mt5.TIMEFRAME_H1, 0, 80)]

    def spread_history(self, hour_utc: int, before: datetime) -> list[float]:
        spreads, d, days = [], before.date(), 0
        for _ in range(SPREAD_LOOKBACK_DAYS * 2 + 10):
            d -= timedelta(days=1)
            start = datetime(d.year, d.month, d.day, hour_utc, tzinfo=UTC)
            ticks = self.mt5.copy_ticks_range(SYMBOL, utc_to_server(start), utc_to_server(start + H),
                                              self.mt5.COPY_TICKS_ALL)
            if ticks is None or len(ticks) == 0:
                continue
            spreads.extend(float(t["ask"]) - float(t["bid"]) for t in ticks if float(t["bid"]) > 0)
            days += 1
            if days == SPREAD_LOOKBACK_DAYS:
                break
        return spreads

    # -- clock
    def check_clock(self, now: datetime) -> None:
        last = self.state.get("last_clock_check")
        if last and now - datetime.fromisoformat(last) < CLOCK_CHECK_EVERY and self.state.get("clock_ok") is not None:
            return
        tick = self.mt5.symbol_info_tick(SYMBOL)
        measured = measured_offset_hours(int(tick.time), now) if tick is not None else None
        if measured is None:
            return                                     # market closed: keep the last result
        ok = measured == expected_offset_hours(now)
        if ok is not self.state.get("clock_ok"):
            self.log_day(f"{now:%Y-%m-%d %H:%M} CLOCK server-UTC {measured:+d} h, rule {expected_offset_hours(now):+d} h -> "
                         f"{'OK' if ok else 'MISMATCH: entries paused'}")
        self.state["clock_ok"], self.state["last_clock_check"] = ok, now.isoformat()

    # -- reconciliation
    def reconcile(self, now: datetime) -> None:
        self.broker.adopt_open_positions()
        open_ids = {p.position_id for p in self.broker.open_positions()}
        rec = self.state.get("open")
        if rec and rec["position_id"] not in open_ids:
            self.broker.track(self._position_from_record(rec))
        for pos in self.broker.on_bar():
            if rec and pos.position_id == rec["position_id"]:
                self._record_exit(rec, pos.exit_time or now, pos.exit_price, None, pos.exit_reason or "stop")
                rec = None
        if rec is None:
            for pos in self.broker.open_positions():   # an S1 position the state does not know
                if not self.state.get("open"):
                    self.state["open"] = {"position_id": pos.position_id, "trading_day": str(trading_day(pos.entry_time)),
                                          "entry_time_utc": pos.entry_time.isoformat(), "entry_bar_open": "",
                                          "entry_fill": pos.entry_price, "stop": pos.stop_loss, "lots": pos.volume,
                                          "spread_entry": "", "risk_usd": self._risk_usd(pos.volume, pos.entry_price, pos.stop_loss)}
                    self.log_day(f"{now:%Y-%m-%d %H:%M} RECONCILE adopted open position {pos.position_id}")

    def _position_from_record(self, rec: dict):
        from execution.broker import SimulatedPosition
        return SimulatedPosition(position_id=rec["position_id"], symbol=SYMBOL, side=Side.BUY, volume=float(rec["lots"]),
                                 entry_price=float(rec["entry_fill"]), stop_loss=float(rec["stop"]), take_profit=None,
                                 entry_time=datetime.fromisoformat(rec["entry_time_utc"]))

    def _risk_usd(self, lots: float, entry: float, stop: float) -> float:
        return float(self.broker.spec.money_for_price_distance(abs(entry - stop), lots))

    # -- trades
    def _record_exit(self, rec: dict, when: datetime, fill: float | None, bar_close: float | None, reason: str) -> None:
        deals = self.broker.deals_for_position(rec["position_id"])
        gross = sum(float(d.profit) for d in deals)
        costs = sum(float(getattr(d, "commission", 0)) + float(getattr(d, "swap", 0)) + float(getattr(d, "fee", 0))
                    for d in deals)
        outs = [d for d in deals if int(d.entry) == 1]
        if fill is None and outs:
            fill = float(outs[-1].price)
        net = gross + costs
        risk = float(rec["risk_usd"]) or float("nan")
        net_r = net / risk
        self.state["net_r"].append(net_r)
        cum = float(sum(self.state["net_r"]))
        tick = self.mt5.symbol_info_tick(SYMBOL)
        acct = self.mt5.account_info()
        row = {**rec, "exit_time_utc": when.isoformat(), "exit_bar_close": bar_close if bar_close is not None else "",
               "exit_fill": fill, "exit_slippage": (fill - bar_close) if (fill is not None and bar_close is not None) else "",
               "spread_exit": float(tick.ask - tick.bid) if tick is not None else "", "exit_reason": reason,
               "gross_usd": gross, "costs_usd": costs, "net_usd": net, "net_r": net_r, "cum_r": cum,
               "equity_after": float(acct.equity) if acct is not None else ""}
        append_csv(self.paths.trades, TRADE_FIELDS, row)
        self.state["open"] = None
        self.state["last_exit_price"] = fill
        if rec["trading_day"] not in self.state["done_days"]:
            self.state["done_days"].append(rec["trading_day"])
        if killed(cum) and not self.state["killed"]:
            self.state["killed"] = True
            self.log_day(f"{when:%Y-%m-%d} KILL SWITCH cumulative net R {cum:+.2f} <= {KILL_R}: no further entries")
        self.log_day(f"{rec['trading_day']} TRADE {reason}: net {net:+.2f} USD, {net_r:+.2f} R, cum {cum:+.2f} R, "
                     f"n {len(self.state['net_r'])}")

    def try_exit(self, now: datetime, bars: list) -> None:
        rec = self.state.get("open")
        if not rec or now < exit_time(date.fromisoformat(rec["trading_day"])):
            return
        exit_bar = [b for t, b in bars if t == exit_time(date.fromisoformat(rec["trading_day"])) - H]
        res = self.broker.close_position(rec["position_id"], operation_id=f"S1-{rec['trading_day']}-EXIT",
                                         decision_time=now)
        if res.filled:
            self._record_exit(rec, now, res.executed_price, float(exit_bar[0]["close"]) if exit_bar else None, "TIME")
        elif res.reason == "position not open":
            self.broker.on_bar()

    def try_entry(self, now: datetime, bars: list) -> None:
        if self.state.get("open") or self.state["killed"]:
            return
        opens = [t for t, _ in bars]
        reopen = session_reopen(opens, now)
        if reopen is None:
            return
        eb = entry_bar_open(opens, reopen)
        if eb is None or eb > now or now - eb >= H:
            return                                     # only while the entry bar is the forming bar
        day = trading_day(eb)
        key = str(day)
        if key in self.state["done_days"] or key in self.state["skips"]:
            return
        if not (FIRST_DAY <= day <= LAST_DAY):
            return

        def skip(reason: str) -> None:
            self.state["skips"][key] = reason
            self.log_day(f"{key} SKIP {reason}")

        if self.state.get("clock_ok") is not True:
            return skip("server clock not confirmed against the v1b rule")
        tick = self.mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return                                     # no quote yet; try again next step
        spread = float(tick.ask - tick.bid)
        skip_it, med = spread_skip(spread, self.spread_history(eb.hour, eb))
        if skip_it:
            return skip(f"spread {spread:.2f} > {SPREAD_MULTIPLE} x median {med:.3f}")
        d1 = self._rates(self.mt5.TIMEFRAME_D1, 1, ATR_N + 1)
        if len(d1) < ATR_N + 1:
            return skip("fewer than 15 closed D1 bars")
        a = atr([b["high"] for b in d1], [b["low"] for b in d1], [b["close"] for b in d1])
        equity = float(self.mt5.account_info().equity)
        size = lots_for_risk(self.broker.spec, balance=equity, risk_fraction=RISK_FRACTION, stop_distance=a)
        if not size.tradeable:
            return skip(f"size: {size.reason}")
        stop = round(float(tick.ask) - a, self.broker.spec.digits)
        entry_bar = [b for t, b in bars if t == eb][0]
        fill = self.broker.submit_market_order(side=Side.BUY, volume=size.lots, stop_loss=stop, take_profit=None,
                                               decision_time=eb, decision_bar_time=eb - H,
                                               metadata={"operation_id": f"S1-{key}-ENTRY"})
        if fill.status.value != "FILLED":
            return skip(f"order not filled: {fill.reason}")
        pos = [p for p in self.broker.open_positions() if p.metadata.get("operation_id") == f"S1-{key}-ENTRY"][0]
        self.state["open"] = {"trading_day": key, "position_id": pos.position_id, "entry_time_utc": now.isoformat(),
                              "entry_bar_open": float(entry_bar["open"]), "entry_fill": fill.entry_price,
                              "entry_slippage": fill.entry_price - float(entry_bar["open"]), "spread_entry": spread,
                              "stop": stop, "lots": fill.volume,
                              "risk_usd": self._risk_usd(fill.volume, fill.entry_price, stop)}
        if self.state.get("first_entry_price") is None:
            self.state["first_entry_price"] = fill.entry_price
        self.log_day(f"{key} ENTRY {fill.volume} lots at {fill.entry_price} (bar open {entry_bar['open']}), "
                     f"stop {stop}, ATR {a:.2f}, spread {spread:.2f}")

    def update_s2(self) -> None:
        d1 = self._rates(self.mt5.TIMEFRAME_D1, 1, S2_LOOKBACK + 1)
        if not d1:
            return
        last_time = int(d1[-1]["time"])
        if self.state.get("last_d1") == last_time:
            return
        self.state["last_d1"] = last_time
        close = float(d1[-1]["close"])
        for p in self.state["s2_pending"]:
            p["closes"].append(close)
        done = [p for p in self.state["s2_pending"] if len(p["closes"]) >= max(S2_HORIZONS)]
        for p in done:
            sign = 1 if p["direction"] == "long" else -1
            row = {"d1_time_utc": p["d1_time_utc"], "direction": p["direction"], "close": p["close"],
                   **{f"r_{h}d": sign * math.log(p["closes"][h - 1] / p["close"]) for h in S2_HORIZONS}}
            append_csv(self.paths.s2, S2_FIELDS, row)
        self.state["s2_pending"] = [p for p in self.state["s2_pending"] if p not in done]
        sig = s2_signal([b["high"] for b in d1], [b["low"] for b in d1], [b["close"] for b in d1])
        if sig:
            self.state["s2_pending"].append({"d1_time_utc": server_epoch_to_utc(last_time).isoformat(),
                                             "direction": sig, "close": close, "closes": []})

    def step(self, now: datetime) -> None:
        self.check_clock(now)
        self.reconcile(now)
        bars = self.h1_opens()
        self.try_exit(now, bars)
        self.try_entry(now, bars)
        self.update_s2()
        self.save()


def final_report(paths: Paths) -> dict:
    state = json.loads(paths.state.read_text(encoding="utf-8"))
    rep = decision(state["net_r"])
    if state.get("killed"):
        rep["decision"], rep["reason"] = "STOP", "kill switch"
    first, last = state.get("first_entry_price"), state.get("last_exit_price")
    rep["benchmark_hold_log_return"] = math.log(last / first) if first and last else None
    return rep


def main() -> int:
    import MetaTrader5 as mt5
    from execution.mt5_broker import MT5Broker, NotDemoAccountError
    if not mt5.initialize():
        print(f"MT5 not reachable: {mt5.last_error()}")
        return 1
    try:
        spec = SymbolSpecification.from_mt5_symbol_info(mt5.symbol_info(SYMBOL), pip_size=PIP_SIZE)
        broker = MT5Broker(mt5, spec, magic=MAGIC, server_to_utc=server_epoch_to_utc)
        broker.require_demo()                         # refuse to start on a non-demo account
        runner = ForwardS1(mt5, broker, Paths.under(OUT_DIR))
        print(f"forward S1 running on {mt5.account_info().server} (demo), magic {MAGIC}; Ctrl+C to stop", flush=True)
        while True:
            now = datetime.now(UTC)
            try:
                runner.step(now)
            except NotDemoAccountError:
                raise
            except Exception as exc:                  # log and keep running; state is saved each step
                runner.log_day(f"{now:%Y-%m-%d %H:%M} ERROR {type(exc).__name__}: {exc}")
            if now.date() > LAST_DAY + timedelta(days=1) and not runner.state.get("open"):
                atomic_write_json(OUT_DIR / "s1_decision.json", final_report(runner.paths))
                print("period over; decision written to data/forward/s1_decision.json")
                return 0
            time.sleep(10)
    except KeyboardInterrupt:
        print("stopped by user; state saved, any open position keeps its server-side stop")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
