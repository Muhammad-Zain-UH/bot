"""Forward test S1 with a fake MetaTrader5 module: no terminal, no network, no real orders."""
import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from core.symbols import SymbolSpecification
from core.types import Side
from execution.mt5_broker import MT5Broker, NotDemoAccountError
from gold.live import forward_s1 as f

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
H = timedelta(hours=1)


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def to_server_epoch(t_utc: datetime) -> int:
    """Server wall time (Europe/Athens) stored as an epoch, as MT5 reports it."""
    return int(f.utc_to_server(t_utc).timestamp())


def session_bars(first_ny_day: date, last_ny_day: date) -> list[datetime]:
    """UTC opens of H1 bars on the demo schedule: 18:00 NY -> 15:00 NY bar, closed 16-18 NY
    and Friday 16:00 -> Sunday 18:00 NY."""
    out, d = [], first_ny_day
    while d <= last_ny_day:
        for h in range(24):
            t = datetime(d.year, d.month, d.day, h, tzinfo=NY)
            dow = t.weekday()
            closed = (16 <= h < 18) or dow == 5 or (dow == 4 and h >= 16) or (dow == 6 and h < 18)
            if not closed:
                out.append(t.astimezone(UTC))
        d += timedelta(days=1)
    return sorted(out)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    TRADE_RETCODE_DONE, POSITION_TYPE_BUY, DEAL_REASON_SL = 10009, 0, 4
    TIMEFRAME_H1, TIMEFRAME_D1, COPY_TICKS_ALL = 16385, 16408, -1

    def __init__(self, bar_opens_utc, now_utc):
        self.trade_mode, self.equity = 0, 100_000.0
        self.bid, self.ask = 4000.0, 4000.3
        self.hist_spread = 0.30
        self.now = now_utc
        self.bars = [{"time": to_server_epoch(t), "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.5,
                      "utc": t} for t in bar_opens_utc]
        self.d1 = [{"time": i, "open": 4000.0, "high": 4050.0, "low": 3950.0, "close": 4000.0} for i in range(40)]
        self.positions, self.deals, self.sent, self._ticket = [], [], [], 1000
        self.server_offset_error_h = 0

    def account_info(self):
        return SimpleNamespace(trade_mode=self.trade_mode, equity=self.equity, server="Fake-Demo")

    def symbol_info(self, sym):
        return SimpleNamespace(name=sym, digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=1.0,
                               trade_contract_size=100.0, trade_calc_mode=4, volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, currency_base="XAU", currency_profit="USD", filling_mode=3,
                               trade_stops_level=0)

    def symbol_info_tick(self, sym):
        return SimpleNamespace(time=to_server_epoch(self.now) + 3600 * self.server_offset_error_h,
                               bid=self.bid, ask=self.ask)

    def copy_rates_from_pos(self, sym, tf, start, count):
        if tf == self.TIMEFRAME_H1:
            visible = [b for b in self.bars if b["utc"] <= self.now]
        else:
            visible = self.d1
        end = len(visible) - start
        return visible[max(0, end - count):end]

    def copy_ticks_range(self, sym, a, b, flags):
        return [{"bid": 4000.0, "ask": 4000.0 + self.hist_spread}] * 5

    def positions_get(self, symbol=None, ticket=None):
        return [p for p in self.positions if ticket is None or p.ticket == ticket]

    def history_deals_get(self, position=None):
        return [d for d in self.deals if d.position_id == position]

    def order_send(self, req):
        self.sent.append(req)
        self._ticket += 1
        if "position" not in req:
            p = SimpleNamespace(ticket=self._ticket, magic=req["magic"], type=req["type"], volume=req["volume"],
                                price_open=req["price"], sl=req["sl"], tp=req["tp"], time=to_server_epoch(self.now),
                                comment=req["comment"])
            self.positions.append(p)
            self.deals.append(SimpleNamespace(position_id=p.ticket, entry=0, price=req["price"], profit=0.0,
                                              commission=-3.5, swap=0.0, fee=0.0, time=p.time, reason=0))
        else:
            p = [x for x in self.positions if x.ticket == req["position"]][0]
            self.positions.remove(p)
            self.deals.append(SimpleNamespace(position_id=p.ticket, entry=1, price=req["price"],
                                              profit=(req["price"] - p.price_open) * 100 * p.volume,
                                              commission=-3.5, swap=-1.0, fee=0.0, time=to_server_epoch(self.now),
                                              reason=0))
        return SimpleNamespace(retcode=10009, order=self._ticket, deal=self._ticket, price=req["price"],
                               volume=req["volume"], comment="done")

    def stop_out(self, price):
        p = self.positions.pop()
        self.deals.append(SimpleNamespace(position_id=p.ticket, entry=1, price=price,
                                          profit=(price - p.price_open) * 100 * p.volume, commission=-3.5,
                                          swap=0.0, fee=0.0, time=to_server_epoch(self.now), reason=4))


def make(now, bar_opens, tmp):
    fake = FakeMT5(bar_opens, now)
    spec = SymbolSpecification.from_mt5_symbol_info(fake.symbol_info("XAUUSD"), pip_size=0.1)
    broker = MT5Broker(fake, spec, magic=f.MAGIC, server_to_utc=f.server_epoch_to_utc)
    return fake, broker, f.ForwardS1(fake, broker, f.Paths.under(Path(tmp)))


BARS = session_bars(date(2026, 10, 25), date(2026, 11, 3))


class TestPureRules(unittest.TestCase):
    def test_reopen_entry_and_trading_day_across_the_us_dst_change(self):
        # Thu 2026-10-29 (EDT; Athens already on winter time): reopen 18:00 EDT = 22:00 UTC
        now = utc("2026-10-29T23:00:30")
        reopen = f.session_reopen(BARS, now)
        self.assertEqual(reopen, utc("2026-10-29T22:00:00"))
        self.assertEqual(f.entry_bar_open(BARS, reopen), utc("2026-10-29T23:00:00"))
        self.assertEqual(f.trading_day(utc("2026-10-29T23:00:00")), date(2026, 10, 30))
        # Sunday 2026-11-01 after the US change: reopen 18:00 EST = 23:00 UTC, entry 00:00 UTC Monday
        now = utc("2026-11-02T00:00:30")
        reopen = f.session_reopen(BARS, now)
        self.assertEqual(reopen, utc("2026-11-01T23:00:00"))
        self.assertEqual(f.entry_bar_open(BARS, reopen), utc("2026-11-02T00:00:00"))
        self.assertEqual(f.trading_day(utc("2026-11-02T00:00:00")), date(2026, 11, 2))
        self.assertEqual(f.exit_time(date(2026, 11, 2)), utc("2026-11-02T11:00:00"))

    def test_clock_rule(self):
        now = utc("2026-10-26T12:00:00")                     # Athens on winter time (UTC+2)
        self.assertEqual(f.expected_offset_hours(now), 2)
        self.assertEqual(f.measured_offset_hours(to_server_epoch(now), now), 2)
        self.assertIsNone(f.measured_offset_hours(to_server_epoch(now - timedelta(hours=5, minutes=30)), now))

    def test_atr_spread_kill_and_decision(self):
        # true ranges: max(12-9, |12-9.5|, |9-9.5|) = 3; max(11-10, |11-11|, |10-11|) = 1
        self.assertAlmostEqual(f.atr([10, 12, 11], [9, 9, 10], [9.5, 11, 10.5], n=2), (3 + 1) / 2)
        self.assertEqual(f.spread_skip(1.0, [0.3] * 10)[0], True)
        self.assertEqual(f.spread_skip(0.8, [0.3] * 10)[0], False)
        self.assertTrue(f.killed(-6.0))
        self.assertFalse(f.killed(-5.9))
        d = f.decision([0.5, -0.2, 0.3, 0.1])
        self.assertEqual(d["decision"], "CONTINUE")
        self.assertAlmostEqual(d["t"], d["mean_r"] / (d["sd_r"] / 2))
        self.assertEqual(f.decision([-1.0] * 9)["decision"], "STOP")           # drawdown 9 R
        self.assertEqual(f.decision([2.0, -8.5, 7.0])["decision"], "STOP")     # mean > 0 but drawdown 8.5 R

    def test_s2_signal(self):
        highs, lows = [10.0] * 20 + [11.0], [9.0] * 20 + [9.5]
        self.assertEqual(f.s2_signal(highs, lows, [9.5] * 20 + [10.5]), "long")
        self.assertEqual(f.s2_signal(highs, lows, [9.5] * 20 + [8.5]), "short")
        self.assertIsNone(f.s2_signal(highs, lows, [9.5] * 21))


class TestDemoOnly(unittest.TestCase):
    def test_a_real_account_is_refused_before_any_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, _ = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            fake.trade_mode = fake.ACCOUNT_TRADE_MODE_REAL
            with self.assertRaises(NotDemoAccountError):
                broker.submit_market_order(side=Side.BUY, volume=0.02, stop_loss=3900.0, take_profit=None,
                                           decision_time=fake.now, decision_bar_time=fake.now - H,
                                           metadata={"operation_id": "S1-test"})
            with self.assertRaises(NotDemoAccountError):
                broker.require_demo()
            self.assertEqual(fake.sent, [])


class TestRunner(unittest.TestCase):
    def run_to(self, fake, runner, *times):
        for t in times:
            fake.now = utc(t)
            runner.step(fake.now)

    def test_entry_and_exit_timing_across_the_dst_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T22:30:00"), BARS, tmp)
            self.run_to(fake, runner, "2026-10-29T22:30:00")
            self.assertEqual(fake.sent, [])                                    # before the entry bar
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            self.assertEqual(len(fake.sent), 1)
            req = fake.sent[0]
            self.assertEqual((req["type"], req["volume"], req["comment"]), (0, 0.02, "S1-2026-10-30-ENTRY"))
            self.assertAlmostEqual(req["sl"], 4000.3 - 100.0)                  # ATR(14) = 100
            self.run_to(fake, runner, "2026-10-30T10:59:00")
            self.assertEqual(len(fake.sent), 1)                                # not yet
            self.run_to(fake, runner, "2026-10-30T11:00:30")
            self.assertEqual(len(fake.sent), 2)
            self.assertEqual(fake.sent[1]["comment"], "S1-2026-10-30-EXIT")
            # after the US change: Sunday 23:00 UTC reopen, entry at 00:00 UTC Monday
            self.run_to(fake, runner, "2026-11-01T23:30:00")
            self.assertEqual(len(fake.sent), 2)
            self.run_to(fake, runner, "2026-11-02T00:00:30", "2026-11-02T11:00:30")
            self.assertEqual([r["comment"] for r in fake.sent[2:]], ["S1-2026-11-02-ENTRY", "S1-2026-11-02-EXIT"])
            rows = (Path(tmp) / "s1_trades.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 3)                                     # header + 2 trades

    def test_spread_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            fake.ask = fake.bid + 1.0                                          # 1.0 > 3 x 0.30
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            self.assertEqual(fake.sent, [])
            self.assertIn("spread", runner.state["skips"]["2026-10-30"])
            self.run_to(fake, runner, "2026-10-29T23:20:00")                   # not retried that day
            self.assertEqual(fake.sent, [])

    def test_clock_mismatch_pauses_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            fake.server_offset_error_h = 1
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            self.assertEqual(fake.sent, [])
            self.assertIn("clock", runner.state["skips"]["2026-10-30"])

    def test_kill_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            runner.state["net_r"] = [-1.0] * 5
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            self.assertEqual(len(fake.sent), 1)
            fake.now = utc("2026-10-30T03:00:00")
            fake.stop_out(3900.3)                                               # about -1 R
            runner.step(fake.now)
            self.assertTrue(runner.state["killed"])
            self.run_to(fake, runner, "2026-11-02T00:00:30")
            self.assertEqual(len(fake.sent), 1)                                # no entry after the kill

    def test_restart_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            self.assertEqual(len(fake.sent), 1)
            # restart: a new broker and runner on the same account and state file
            spec = broker.spec
            broker2 = MT5Broker(fake, spec, magic=f.MAGIC, server_to_utc=f.server_epoch_to_utc)
            runner2 = f.ForwardS1(fake, broker2, f.Paths.under(Path(tmp)))
            self.run_to(fake, runner2, "2026-10-29T23:30:00")
            self.assertEqual(len(fake.sent), 1)                                # adopted, no second order
            self.assertEqual(len(broker2.open_positions()), 1)
            fake.now = utc("2026-10-30T04:00:00")
            fake.stop_out(3900.3)                                               # stopped while running
            runner2.step(fake.now)
            rows = (Path(tmp) / "s1_trades.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn("stop", rows[1])
            self.assertIsNone(json.loads((Path(tmp) / "s1_state.json").read_text())["open"])

    def test_state_lost_but_position_open_is_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            self.run_to(fake, runner, "2026-10-29T23:00:30")
            (Path(tmp) / "s1_state.json").unlink()
            broker2 = MT5Broker(fake, broker.spec, magic=f.MAGIC, server_to_utc=f.server_epoch_to_utc)
            runner2 = f.ForwardS1(fake, broker2, f.Paths.under(Path(tmp)))
            self.run_to(fake, runner2, "2026-10-29T23:40:00")
            self.assertEqual(len(fake.sent), 1)
            self.assertEqual(runner2.state["open"]["trading_day"], "2026-10-30")
            self.run_to(fake, runner2, "2026-10-30T11:00:30")
            self.assertEqual(fake.sent[-1]["comment"], "S1-2026-10-30-EXIT")


class TestBroker(unittest.TestCase):
    def test_volume_rounding_filling_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, _ = make(utc("2026-10-29T23:00:30"), BARS, tmp)
            self.assertEqual(broker.filling_mode(), fake.ORDER_FILLING_FOK)
            kw = dict(side=Side.BUY, stop_loss=3900.0, take_profit=None, decision_time=fake.now,
                      decision_bar_time=fake.now - H)
            r = broker.submit_market_order(volume=0.009, metadata={"operation_id": "op-a"}, **kw)
            self.assertEqual(r.status.value, "REJECTED")
            self.assertEqual(fake.sent, [])
            r = broker.submit_market_order(volume=0.027, metadata={"operation_id": "op-b"}, **kw)
            self.assertEqual((r.status.value, fake.sent[0]["volume"]), ("FILLED", 0.02))
            broker.submit_market_order(volume=0.027, metadata={"operation_id": "op-b"}, **kw)
            self.assertEqual(len(fake.sent), 1)                                # same operation: not resent
            pid = broker.open_positions()[0].position_id
            self.assertTrue(broker.close_position(pid, operation_id="op-c", decision_time=fake.now).filled)
            self.assertFalse(broker.close_position(pid, operation_id="op-c", decision_time=fake.now).filled)
            self.assertEqual(len(fake.sent), 2)


class TestS2Log(unittest.TestCase):
    def test_signal_then_horizons(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, broker, runner = make(utc("2026-10-28T12:00:00"), BARS, tmp)
            base = [{"time": i, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for i in range(30)]
            fake.d1 = base + [{"time": 30, "open": 100.0, "high": 103.0, "low": 100.0, "close": 102.0},
                              {"time": 31, "open": 0, "high": 0, "low": 0, "close": 0}]   # last = forming
            runner.update_s2()
            self.assertEqual(runner.state["s2_pending"][0]["direction"], "long")
            for i, c in enumerate((103.0, 101.0, 104.0, 105.0, 106.0)):
                fake.d1.insert(-1, {"time": 32 + i, "open": c, "high": c, "low": c, "close": c})
                runner.update_s2()
            rows = (Path(tmp) / "s2_signals.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)
            r1, r3, r5 = (float(x) for x in rows[1].split(",")[3:6])
            self.assertAlmostEqual(r1, math.log(103 / 102))
            self.assertAlmostEqual(r3, math.log(104 / 102))
            self.assertAlmostEqual(r5, math.log(106 / 102))


if __name__ == "__main__":
    unittest.main()
