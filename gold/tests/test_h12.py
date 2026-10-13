"""H12 on synthetic data: no lookahead per symbol, staggered joins, N_t, cost and swap arithmetic."""
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gold.hyp import h12_multi_tsmom as h12, weekly
from gold.hyp.anchors import NEW_YORK

SPEC = Path(__file__).resolve().parents[2] / "research" / "v2" / "H12_SPEC.md"


def d1(start, n, seed):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"session": pd.bdate_range(start, periods=n),
                         "close": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.006, n)))})


def consts(symbols, bpy=260.0):
    return pd.DataFrame({"d1_per_year": bpy, "cost_bp": 1.0, "swap_long": -0.02, "swap_short": 0.01},
                        index=list(symbols))


class TestTargets(unittest.TestCase):
    def setUp(self):
        self.d1s = {"AAA": d1("2010-01-04", 700, 1), "BBB": d1("2010-09-06", 520, 2)}  # BBB starts later
        self.c = consts(self.d1s)
        self.first = pd.Timestamp("2010-01-04")

    def test_staggered_join_and_n_t(self):
        tg, n_week = h12.targets(self.d1s, self.c, self.first)
        b_first = tg["BBB"].index.min()
        rows_before = int((self.d1s["BBB"]["session"] <= b_first).sum())
        self.assertGreaterEqual(rows_before, 253)                    # BBB enters only after 253 bars
        self.assertLess(int((self.d1s["BBB"]["session"] <= b_first - pd.Timedelta(days=7)).sum()), 253)
        self.assertEqual(int(n_week.iloc[0]), 1)
        week = b_first - pd.Timedelta(days=b_first.dayofweek)
        self.assertEqual(int(n_week[week]), 2)                       # N_t rises when BBB joins
        self.assertTrue((n_week[n_week.index < week] == 1).all())
        self.assertEqual(sorted(set(n_week)), [1, 2])

    def test_position_scales_with_n_t(self):
        tg, n_week = h12.targets(self.d1s, self.c, self.first)
        a = self.d1s["AAA"]
        for s in (tg["AAA"].index[0], tg["AAA"].index[-1]):
            i = int(np.flatnonzero(a["session"] == s)[0])
            sig, vol = h12.signal_and_vol(a["close"].to_numpy(), i, 260.0)
            n = int(n_week[s - pd.Timedelta(days=s.dayofweek)])
            self.assertAlmostEqual(tg["AAA"][s], sig * min(2, (0.10 / math.sqrt(n)) / vol))

    def test_no_lookahead_per_symbol(self):
        tg, _ = h12.targets(self.d1s, self.c, self.first)
        for s in list(tg["AAA"].index)[::9]:
            changed = {k: v.assign(close=np.where(v["session"] > s, v["close"] * 5, v["close"]))
                       for k, v in self.d1s.items()}
            tg2, _ = h12.targets(changed, self.c, self.first)
            self.assertAlmostEqual(tg2["AAA"][s], tg["AAA"][s])
            if s in tg["BBB"].index:
                self.assertAlmostEqual(tg2["BBB"][s], tg["BBB"][s])


class TestCostAndSwap(unittest.TestCase):
    def test_swap_charges_and_ignored_credits(self):
        fn = h12.swap_charge_fn(-0.0365, 0.02)
        self.assertAlmostEqual(fn(2.0, 1), 2.0 * 0.0365 / 365)        # long pays
        self.assertAlmostEqual(fn(-1.0, 3), 0.0)                        # short credit ignored
        self.assertAlmostEqual(h12.swap_charge_fn(-0.0365, 0.02, level=2)(1.0, 3), 2 * 3 * 0.0365 / 365)
        self.assertAlmostEqual(h12.swap_charge_fn(0.01, -0.05)(-0.5, 1), 0.5 * 0.05 / 365)
        self.assertEqual(fn(0.0, 3), 0.0)

    def test_cost_and_financing_in_the_daily_run(self):
        d = pd.DataFrame({"session": pd.to_datetime(["2024-03-07", "2024-03-08", "2024-03-11", "2024-03-12"]),
                          "close": [100.0, 101.0, 103.0, 102.0]})
        wall = pd.date_range(pd.Timestamp("2024-03-10 17:00"), periods=6, freq="4h")
        h4 = pd.DataFrame({"time": wall.tz_localize(NEW_YORK).tz_convert("UTC"), "open": [100.5, 102.0, 0, 0, 0, 0]})
        out = weekly.run(d, h4, pd.Series({pd.Timestamp("2024-03-08"): 0.8}), None,
                         cost_per_unit=1.5e-4, financing_fn=h12.swap_charge_fn(-0.05, 0.0))
        mon = out.iloc[0]
        self.assertAlmostEqual(mon["gross"], 0.8 * math.log(103 / 102))
        self.assertAlmostEqual(mon["cost"], 1.5e-4 * 0.8)
        self.assertAlmostEqual(mon["financing"], 0.8 * 0.05 * 1 / 365)
        self.assertAlmostEqual(mon["net"], mon["gross"] - mon["cost"] - mon["financing"])


class TestSpecAndPortfolio(unittest.TestCase):
    def test_spec_constants_parse(self):
        c = h12.spec_constants(SPEC.read_text(encoding="utf-8"))
        self.assertEqual(len(c), 29)
        self.assertEqual(c.at["EURUSD", "cost_bp"], 0.70)
        self.assertEqual(c.at["XAGUSD", "cost_bp"], 3.29)
        self.assertEqual(c.at["XAUUSD", "d1_per_year"], 256.59)
        self.assertEqual(c.at["AUDCHF", "swap_short_pct"], -9.93)
        self.assertEqual(str(c.at["XAGUSD", "join"].date()), "2009-11-03")

    def test_portfolio_sums_by_session(self):
        a = pd.DataFrame({"session": pd.to_datetime(["2024-01-02", "2024-01-03"]), "gross": [0.01, 0.02],
                          "cost": [0.001, 0.0], "financing": [0.0, 0.001], "net": [0.009, 0.019], "delta": [1.0, 0.0]})
        b = a.iloc[1:].copy()
        p = h12.portfolio({"A": a, "B": b})
        self.assertEqual(list(p["gross"]), [0.01, 0.04])
        self.assertAlmostEqual(p["net_of_cost"].iloc[0], 0.009)
        self.assertEqual(list(p["abs_delta"]), [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
