"""Batch 2 (H10, H11) engine on synthetic data: no lookahead, financing, execution bar."""
import math
import unittest

import numpy as np
import pandas as pd

from gold.hyp import h10_tsmom, h11_vol_managed, weekly
from gold.hyp.anchors import NEW_YORK


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def synthetic_d1(n=600, seed=0, start="2020-01-06"):
    sessions = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = 1500 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    return pd.DataFrame({"session": sessions, "close": close})


def h4_week(sunday: str, grid_hour: int):
    """H4 opens (NY wall) from Sunday grid_hour through Monday, as UTC."""
    wall = pd.date_range(pd.Timestamp(sunday) + pd.Timedelta(hours=grid_hour), periods=8, freq="4h")
    t = wall.tz_localize(NEW_YORK).tz_convert("UTC")
    return pd.DataFrame({"time": t, "open": np.arange(8, dtype=float) + 100})


class TestNoLookahead(unittest.TestCase):
    def test_position_uses_data_up_to_the_decision_close_only(self):
        d1 = synthetic_d1()
        for mod in (h10_tsmom, h11_vol_managed):
            full = mod.targets(d1, d1.session.iloc[0])
            for s in list(full.index)[::7]:
                cut = d1[d1.session <= s]
                self.assertAlmostEqual(mod.targets(cut, d1.session.iloc[0])[s], full[s], msg=mod.__name__)
                garbage = d1.copy()
                garbage.loc[garbage.session > s, "close"] *= 3       # change the future only
                self.assertAlmostEqual(mod.targets(garbage, d1.session.iloc[0])[s], full[s])

    def test_history_gate_and_bounds(self):
        d1 = synthetic_d1()
        t10 = h10_tsmom.targets(d1, d1.session.iloc[0])
        self.assertGreaterEqual(int(np.flatnonzero(d1.session == t10.index[0])[0]), 252)
        self.assertTrue((t10.abs() <= 2).all())
        t11 = h11_vol_managed.targets(d1, d1.session.iloc[0])
        self.assertTrue(((t11 > 0) & (t11 <= 1.5)).all())
        self.assertEqual(list(t11.index), list(t10.index))

    def test_decisions_are_each_weeks_last_session(self):
        d1 = synthetic_d1(20)
        d1 = d1[d1.session != pd.Timestamp("2020-01-17")]            # a closed Friday
        last = d1.session.iloc[weekly.decision_index(d1)]
        self.assertIn(pd.Timestamp("2020-01-16"), set(last))           # Thursday instead
        self.assertIn(pd.Timestamp("2020-01-10"), set(last))


class TestExecutionBar(unittest.TestCase):
    def test_across_dst_and_eu_gap_week(self):
        # 2024-03-08 Fri close 17:00 EST; 2024-03-10 US DST starts; grid 17 -> 21:00 EDT bar
        h4 = h4_week("2024-03-10", 17)
        t, price = weekly.execution(h4, pd.Timestamp("2024-03-08"))
        self.assertEqual(t, ts("2024-03-11 01:00"))                     # 21:00 EDT
        self.assertEqual(price, 101.0)
        # winter week, grid 17: 21:00 EST = 02:00 UTC
        t, _ = weekly.execution(h4_week("2024-01-07", 17), pd.Timestamp("2024-01-05"))
        self.assertEqual(t, ts("2024-01-08 02:00"))
        # EU-only gap week, grid 18: reopen 18:00 EDT, execution at the 22:00 EDT bar
        t, _ = weekly.execution(h4_week("2024-03-17", 18), pd.Timestamp("2024-03-15"))
        self.assertEqual(t, ts("2024-03-18 02:00"))


class TestPnlAndFinancing(unittest.TestCase):
    def setUp(self):
        self.d1 = pd.DataFrame({"session": pd.to_datetime(["2024-03-07", "2024-03-08", "2024-03-11",
                                                            "2024-03-12"]),
                                "close": [100.0, 101.0, 103.0, 102.0]})
        self.h4 = h4_week("2024-03-10", 17)                    # execution open 101.0 (index 1)
        self.h4["open"] = [100.5, 102.0, 0, 0, 0, 0, 0, 0]
        self.dff = pd.Series([5.0], index=pd.to_datetime(["2024-01-01"]))

    def test_execution_day_split_cost_and_weekend_financing(self):
        daily = weekly.run(self.d1, self.h4, pd.Series({pd.Timestamp("2024-03-08"): 1.5}), self.dff)
        mon = daily.iloc[0]
        self.assertEqual(mon["session"], pd.Timestamp("2024-03-11"))
        self.assertAlmostEqual(mon["gross"], 0 * math.log(102 / 101) + 1.5 * math.log(103 / 102))
        self.assertAlmostEqual(mon["cost"], 1.5e-4)
        self.assertAlmostEqual(mon["financing"], 1.5 * (0.05 + 0.025) * 1 / 365)
        tue = daily.iloc[1]
        self.assertAlmostEqual(tue["gross"], 1.5 * math.log(102 / 103))
        self.assertAlmostEqual(tue["net"], tue["gross"] - 1.5 * 0.075 / 365)

    def test_short_pays_markup_only_and_weekend_is_three_nights(self):
        d1 = pd.concat([self.d1, pd.DataFrame({"session": pd.to_datetime(["2024-03-15", "2024-03-18"]),
                                                "close": [100.0, 99.0]})], ignore_index=True)
        daily = weekly.run(d1, self.h4, pd.Series({pd.Timestamp("2024-03-08"): -1.0}), self.dff)
        fri = daily[daily.session == pd.Timestamp("2024-03-15")].iloc[0]
        self.assertAlmostEqual(fri["financing"], 1.0 * 0.025 * 3 / 365)
        self.assertAlmostEqual(daily.iloc[0]["financing"], 0.025 / 365)


class TestMetrics(unittest.TestCase):
    def test_era_rule(self):
        self.assertTrue(weekly.era_rule({"a": 1, "b": 1, "c": 1, "d": 1})["pass"])
        self.assertFalse(weekly.era_rule({"a": 7, "b": 1, "c": 1, "d": 1})["pass"])
        self.assertFalse(weekly.era_rule({"a": -1, "b": -1, "c": 1, "d": 0.5})["pass"])

    def test_drawdown_and_sharpe(self):
        daily = pd.DataFrame({"session": pd.bdate_range("2024-01-01", periods=4),
                              "net": [0.1, -0.2, 0.05, 0.2], "delta": [1, 0, 0, 0],
                              "gold_r": [0.1, -0.1, 0.0, 0.1]})
        m = weekly.metrics(daily)
        self.assertAlmostEqual(m["max_drawdown"], 1 - math.exp(-0.2))
        r = daily.net.to_numpy()
        self.assertAlmostEqual(m["sharpe"], r.mean() / r.std(ddof=1) * math.sqrt(256.65))


if __name__ == "__main__":
    unittest.main()
