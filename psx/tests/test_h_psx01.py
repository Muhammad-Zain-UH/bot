"""H-PSX-01 construction on synthetic panels: universe, signal, frictions, simulation; truncation tests."""
import math
import unittest

import numpy as np
import pandas as pd

from psx.strategy import h_psx01 as h
from psx.strategy import blind


def make_rows(paths: dict, days: pd.DatetimeIndex, volume=None, bars=None) -> pd.DataFrame:
    """paths: symbol -> list of closes (None = no row). Flat bars (high = low = close) unless `bars` gives
    {(symbol, k): (high, low)}; LDCP = the previous close; volume 1,000 unless volume[(symbol, k)]."""
    out = []
    for s, closes in paths.items():
        prev = None
        for k, c in enumerate(closes):
            if c is None:
                continue
            hi, lo = (bars or {}).get((s, k), (c, c))
            out.append({"symbol": s, "date": days[k], "close": float(c), "high": float(hi), "low": float(lo),
                        "volume": float((volume or {}).get((s, k), 1000.0)), "ldcp": float(prev if prev else c),
                        "adj_close": float(c)})
            prev = c
    return pd.DataFrame(out)


def make_panel(paths, days, limit=0.10, **kw) -> h.Panel:
    return h.Panel.from_rows(make_rows(paths, days, **kw), days, limit)


DAYS = pd.bdate_range("2019-01-01", "2020-12-31")          # 524 trading days


def universe_paths():
    n = len(DAYS)
    rng = np.random.default_rng(7)
    walk = lambda start: list(start * np.exp(np.cumsum(rng.normal(0, 0.01, n))))
    return {"AAA": walk(20), "BBB": walk(5),                                   # BBB below Rs 10
            "CCC": [None] * 400 + walk(30)[400:],                              # too little history
            "DDD": walk(40), "EEE": walk(50), "FFF": walk(25)}


class TestCalendar(unittest.TestCase):
    def test_schedule_executes_on_the_first_day_after_month_end(self):
        plans = h.schedule(DAYS, pd.Period("2020-02", "M"), pd.Period("2020-03", "M"))
        p = plans[0]
        self.assertEqual(DAYS[p.t_pos], pd.Timestamp("2020-01-31"))
        self.assertEqual(DAYS[p.exec_pos], pd.Timestamp("2020-02-03"))
        self.assertEqual(DAYS[p.next_pos], pd.Timestamp("2020-03-02"))
        self.assertEqual(plans[1].exec_pos, p.next_pos)


class TestUniverseAndSignal(unittest.TestCase):
    def setUp(self):
        paths = universe_paths()
        n = len(DAYS)
        vol = {("DDD", k): 0.0 for k in range(n) if k % 10 < 3}               # trades on 70 % of days
        vol.update({("EEE", k): 9000.0 for k in range(n)})                      # most traded
        vol.update({("AAA", k): 4000.0 for k in range(n)})                      # second
        self.P = make_panel(paths, DAYS, volume=vol)
        self.t = h.month_end_positions(DAYS)[pd.Period("2020-11", "M")]

    def test_filters_and_ranking(self):
        u, sig = h.universe(self.P, self.t, top_n=2)
        self.assertEqual([self.P.names[i] for i in u], ["EEE", "AAA"])        # EEE most traded, then AAA (Rs 20)
        u_all, _ = h.universe(self.P, self.t)
        self.assertEqual(sorted(self.P.names[i] for i in u_all), ["AAA", "EEE", "FFF"])

    def test_momentum_skips_the_latest_month(self):
        me = h.month_end_positions(DAYS)
        sig = h.momentum(self.P, self.t)
        i = self.P.names.index("AAA")
        a, b = me[pd.Period("2020-10", "M")], me[pd.Period("2019-11", "M")]
        self.assertAlmostEqual(sig[i], self.P.adj[a, i] / self.P.adj[b, i] - 1)

    def test_winners_are_the_top_third(self):
        sig = np.array([0.1, 0.5, -0.2, 0.3, 0.0, 0.4, 0.2])
        self.assertEqual(list(h.winners(np.arange(7), sig)), [1, 5])

    def test_signal_and_universe_use_no_data_after_t(self):
        rng = np.random.default_rng(1)
        for m in ("2019-12", "2020-06", "2020-11"):
            t = h.month_end_positions(DAYS)[pd.Period(m, "M")]
            u, sig = h.universe(self.P, t)
            cut = self.P.truncate(t)                                            # rows after t removed
            u2, sig2 = h.universe(cut, t)
            np.testing.assert_array_equal(u, u2)
            np.testing.assert_array_equal(sig, sig2)
            garbled = h.Panel(DAYS, self.P.names, *[x.copy() for x in (self.P.close, self.P.high, self.P.low,
                              self.P.volume, self.P.ldcp, self.P.adj)], self.P.limit.copy())
            for arr in (garbled.close, garbled.volume, garbled.adj):           # rows after t replaced
                arr[t + 1:] = rng.uniform(1, 1e6, arr[t + 1:].shape)
            garbled.__post_init__()
            u3, sig3 = h.universe(garbled, t)
            np.testing.assert_array_equal(u, u3)
            np.testing.assert_array_equal(sig, sig3)


class TestFrictions(unittest.TestCase):
    def test_locked_at_the_band(self):
        d = DAYS[:3]
        P = make_panel({"UP": [100, 110, 110], "DN": [100, 90, 90], "PEN": [8, 9, 9]}, d, limit=0.10)
        up, dn, pen = (P.names.index(s) for s in ("UP", "DN", "PEN"))
        self.assertTrue(h.locked(P, 1, up, "up"))
        self.assertFalse(h.locked(P, 1, up, "down"))
        self.assertTrue(h.locked(P, 1, dn, "down"))
        self.assertTrue(h.locked(P, 1, pen, "up"))                     # Rs 1 floor: 8 -> 9 is the band
        self.assertFalse(h.locked(P, 2, up, "up"))                     # flat day
        P5 = make_panel({"UP": [100, 110, 110]}, d, limit=0.15)
        self.assertFalse(h.locked(P5, 1, 0, "up"))                     # 10 % is inside a 15 % band
        Pv = make_panel({"UP": [100, 110, 110]}, d, limit=0.10, volume={("UP", 1): 0.0})
        self.assertFalse(h.locked(Pv, 1, 0, "up"))                     # no trade: not a lock

    def test_spread_abdi_ranaldo(self):
        d = DAYS[:4]
        bars = {("X", 0): (101, 99), ("X", 1): (102, 100), ("X", 2): (101, 99), ("X", 3): (100, 98)}
        P = make_panel({"X": [100.5, 100.0, 100.2, 99.0]}, d, bars=bars)
        c, eta = np.log([100.5, 100.0, 100.2, 99.0]), np.log([np.sqrt(101 * 99), np.sqrt(102 * 100),
                                                               np.sqrt(101 * 99), np.sqrt(100 * 98)])
        s2 = 4 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
        want = max(np.sqrt(np.maximum(s2, 0)).sum() / 3, h.SPREAD_FLOOR)
        self.assertAlmostEqual(h.spread(P, 3, 0), want)
        self.assertTrue((s2 < 0).any())                                # negatives were set to zero
        flat = make_panel({"Y": [10, 10, 10, 10]}, d)
        self.assertEqual(h.spread(flat, 3, 0), h.SPREAD_FLOOR)

    def test_spread_uses_no_data_after_p(self):
        P = make_panel(universe_paths(), DAYS)
        for p in (100, 300, 500):
            for i in range(len(P.names)):
                self.assertEqual(h.spread(P, p, i), h.spread(P.truncate(p), p, i))

    def test_cost_rate(self):
        self.assertAlmostEqual(h.cost_rate(100.0, 0.002), 0.0015 * 1.15 + 0.0002 + 0.001)
        self.assertAlmostEqual(h.cost_rate(10.0, 0.002), 0.003 * 1.15 + 0.0002 + 0.001)   # Rs 0.03 a share binds
        self.assertAlmostEqual(h.cost_rate(10.0, 0.002, 2.0), 2 * h.cost_rate(10.0, 0.002))


class TestSimulate(unittest.TestCase):
    d = DAYS[:6]

    def plans(self, *targets):
        return [h.MonthPlan(pd.Period("2019-01", "M"), 0, 1, 3, np.array(targets[0])),
                h.MonthPlan(pd.Period("2019-02", "M"), 2, 3, 5, np.array(targets[1]))]

    def test_equal_weights_and_costs(self):
        P = make_panel({"A": [10, 10, 15, 20, 20, 20], "B": [10, 10, 10, 10, 10, 10]}, self.d)
        res = h.simulate(P, self.plans([0, 1], [0, 1]))
        ra = rb = h.cost_rate(10.0, h.SPREAD_FLOOR)
        scale = 1.0 / (0.5 * (1 + ra) + 0.5 * (1 + rb))
        self.assertAlmostEqual(res["ret_net"].iloc[0], 0.5 * scale * 2 + 0.5 * scale - 1)
        self.assertAlmostEqual(res["turnover"].iloc[0], 0.5 * scale)
        self.assertAlmostEqual(res["cost"].iloc[0], scale * (0.5 * ra + 0.5 * rb))

    def test_locked_buy_stays_in_cash_and_locked_sell_waits(self):
        P = make_panel({"A": [10, 11, 11, 11, 11, 11], "B": [10, 10, 10, 9, 9.5, 9.5]}, self.d)
        res = h.simulate(P, self.plans([0, 1], [0]))
        self.assertEqual(res["unfilled_locked_buys"].iloc[0], 1)       # A up 10 % at the first execution
        self.assertEqual(res["locked_sells"].iloc[1], 1)               # B down 10 % at the second execution
        self.assertEqual(res["sells_no_close"].iloc[1], 0)
        b = P.names.index("B")
        self.assertFalse(h.locked(P, 4, b, "down"))                   # sold at the next close, 9.5

    def test_delisting_at_last_close_and_haircut(self):
        P = make_panel({"A": [10, 10, 10, 10, 10, 10], "D": [10, 10, 12, None, None, None]}, self.d)
        base = h.simulate(P, self.plans([0, 1], [0, 1]))
        cut = h.simulate(P, self.plans([0, 1], [0, 1]), haircut=0.30)
        self.assertEqual(base["delistings"].iloc[0], 1)
        r = h.cost_rate(10.0, h.SPREAD_FLOOR)
        s = 1 / (1 + r)
        self.assertAlmostEqual(base["ret_net"].iloc[0], 0.5 * s + 0.5 * s * 1.2 - 1)
        self.assertAlmostEqual(cut["ret_net"].iloc[0], 0.5 * s + 0.5 * s * 1.2 * 0.7 - 1)


class TestBlind(unittest.TestCase):
    def test_moments_without_a_mean(self):
        rng = np.random.default_rng(3)
        x = rng.normal(0.01, 0.05, 400)
        self.assertAlmostEqual(blind.gamma0(x), np.var(x))
        self.assertAlmostEqual(blind.sd(x), np.std(x, ddof=1))
        y = np.zeros(3000)
        e = rng.normal(0, 1, 3000)
        for t in range(1, len(y)):
            y[t] = 0.5 * y[t - 1] + e[t]
        self.assertAlmostEqual(blind.autocorr(y, 1), 0.5, delta=0.05)
        self.assertAlmostEqual(blind.nw_se(e, 3), np.std(e) / math.sqrt(len(e)), delta=0.002)

    def test_power_summary(self):
        res = blind.power_summary(0.002, 0.006)
        self.assertAlmostEqual(res["mde"], 2.970 * 0.002)
        self.assertEqual(res["verdict"], "TESTABLE")
        self.assertAlmostEqual(res["power_at_e_ref"], blind.normal_cdf(3 - 2.128))
        self.assertEqual(blind.power_summary(0.0025, 0.006)["verdict"], "UNDERPOWERED")


if __name__ == "__main__":
    unittest.main()
