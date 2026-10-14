"""H15 (Asia vs US session, fixed UTC) on synthetic data only."""
import unittest

import numpy as np
import pandas as pd

from gold.econ import power
from gold.hyp import h15_asia_us as h15
from gold.tests.test_econ_hyp import h1_fixture, lr, row


def ts(s):
    return pd.Timestamp(s, tz="UTC")


class TestH15(unittest.TestCase):
    def setUp(self):
        self.res = h15.asia_us(h1_fixture())

    def test_winter_day_uses_23_utc_start_and_22_utc_end(self):
        fri = row(self.res, "2024-03-08")            # EST: 22:00 UTC is the daily break
        self.assertEqual(fri["asia_start"], ts("2024-03-07 23:00"))
        self.assertEqual(fri["us_end"], ts("2024-03-08 21:00"))          # bar ending 22:00 UTC
        self.assertAlmostEqual(fri["r_asia"], lr("2024-03-07 23:00", "2024-03-08 11:00"))
        self.assertAlmostEqual(fri["r_us"], lr("2024-03-08 14:00", "2024-03-08 22:00"))

    def test_summer_day_uses_22_utc_start_and_21_utc_end(self):
        tue = row(self.res, "2024-03-12")            # EDT: break is 21:00-22:00 UTC
        self.assertEqual(tue["asia_start"], ts("2024-03-11 22:00"))
        self.assertEqual(tue["us_end"], ts("2024-03-12 20:00"))          # bar ending 21:00 UTC
        self.assertAlmostEqual(tue["r_us"], lr("2024-03-12 14:00", "2024-03-12 21:00"))
        self.assertAlmostEqual(tue["y"], tue["r_asia"] - tue["r_us"])
        self.assertAlmostEqual(tue["per_hour"], tue["r_asia"] / 13 - tue["r_us"] / 8)

    def test_monday_starts_on_sunday_evening(self):
        mon = row(self.res, "2024-03-11")
        self.assertEqual(mon["asia_start"], ts("2024-03-10 22:00"))
        self.assertAlmostEqual(mon["r_asia"], lr("2024-03-10 22:00", "2024-03-11 11:00"))

    def test_missing_or_suspect_bar_drops_day(self):
        h1 = h1_fixture()
        h1 = h1[h1.time != ts("2024-03-13 05:00")].copy()
        h1.loc[h1.time == ts("2024-03-14 16:00"), "utc_suspect"] = True
        res = h15.asia_us(h1)
        self.assertIsNone(row(res, "2024-03-13"))
        self.assertIsNone(row(res, "2024-03-14"))
        self.assertIsNotNone(row(res, "2024-03-15"))

    def test_truncation_for_completed_days(self):
        h1 = h1_fixture()
        full = h15.asia_us(h1)
        end = full["us_end"] + pd.Timedelta(hours=1)
        for k in (250, 401, 520):
            cut = h1.time.iloc[k]
            pre = h15.asia_us(h1[h1.time < cut])
            done = full[(end <= cut).to_numpy()].reset_index(drop=True)
            pd.testing.assert_frame_equal(pre[pre.day.isin(done.day)].reset_index(drop=True), done)


class TestH15Cost(unittest.TestCase):
    def test_two_round_trips_and_asia_only(self):
        h1 = h1_fixture()
        h1["spread_usd"] = 0.2
        d = h15.asia_us(h1)
        hm = power.hour_median_spread(h1)
        two, asia = power.h15_cost(d, hm, 2.0)
        np.testing.assert_allclose(asia, np.log1p(0.4 / d["p_asia_start"].to_numpy()))
        np.testing.assert_allclose(two, asia + np.log1p(0.4 / d["p_14"].to_numpy()))


if __name__ == "__main__":
    unittest.main()
