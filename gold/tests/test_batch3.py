"""Batch 3 (H13 round levels, H14 overnight vs NY) on synthetic data only."""
import math
import unittest

import numpy as np
import pandas as pd

from gold.econ import power
from gold.hyp import h13_round_levels as h13, h14_overnight as h14
from gold.tests.test_econ_hyp import h1_fixture, lr, row


def bars(highs, lows, closes, start="2024-01-02 00:00"):
    n = len(closes)
    return pd.DataFrame({"time": pd.date_range(start, periods=n, freq="1h", tz="UTC"),
                         "open": closes, "high": highs, "low": lows, "close": closes,
                         "spread_usd": 0.1, "utc_suspect": False})


def path(n_before=30, touch=1951.0, after=(1952.0, 1953.0, 1949.0, 1948.0, 1947.0, 1946.0)):
    """Closes at 1940 for n_before bars, a touch bar closing at `touch`, then `after`."""
    closes = [1940.0] * n_before + [touch] + list(after)
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    highs[n_before] = max(touch, 1950.5)
    return bars(highs, lows, closes)


class TestLevels(unittest.TestCase):
    def test_round_and_control_levels(self):
        lv = h13.levels(1940, 2010)
        self.assertEqual(sorted(lv[lv.kind == "round"].level), [1950.0, 2000.0])
        self.assertEqual(sorted(lv[lv.kind == "control"].level), [1967.0, 1983.0])


class TestEvents(unittest.TestCase):
    def test_fresh_touch_from_below(self):
        ev = h13.events(path())
        e = ev[(ev.level == 1950.0) & (ev.d == 1)]
        self.assertEqual(list(e.t), [30])
        self.assertEqual(e.kind.iloc[0], "round")
        self.assertEqual(e.close_t4.iloc[0], 1948.0)   # t+4 = 4th bar after the touch

    def test_not_fresh_if_touched_within_24_bars(self):
        df = path()
        df.loc[10, "high"] = 1950.0                     # an earlier touch 20 bars before
        ev = h13.events(df)
        self.assertTrue(ev[(ev.level == 1950.0) & (ev.t == 30)].empty)

    def test_fresh_touch_from_above(self):
        closes = [1960.0] * 30 + [1949.0, 1948.0, 1952.0, 1953.0, 1954.0, 1955.0]
        df = bars([c + 1 for c in closes], [c - 1 for c in closes], closes)
        ev = h13.events(df)
        e = ev[(ev.level == 1950.0) & (ev.t == 30)]
        self.assertEqual(list(e.d), [-1])

    def test_suspect_window_and_arm_end_drop(self):
        df = path()
        df.loc[33, "utc_suspect"] = True                 # inside t-24 .. t+4
        self.assertTrue(h13.events(df)[lambda e: e.t == 30].empty)
        short = path(after=(1952.0, 1953.0, 1949.0))     # only 3 bars after the touch
        self.assertTrue(h13.events(short)[lambda e: e.t == 30].empty)

    def test_y_definitions(self):
        ev = h13.events(path())
        a = h13.h13a(ev)
        e = a[(a.level == 1950.0) & (a.t == 30)].iloc[0]
        self.assertAlmostEqual(e.y, -1 * math.log(1948.0 / 1950.0))
        b = h13.h13b(ev)
        e = b[(b.level == 1950.0) & (b.t == 30)].iloc[0]       # closed 1951 > 1950: a break
        self.assertAlmostEqual(e.y, math.log(1948.0 / 1951.0))
        no_break = h13.h13b(h13.events(path(touch=1949.0)))
        self.assertTrue(no_break[(no_break.level == 1950.0) & (no_break.t == 30)].empty)

    def test_truncation(self):
        rng = np.random.default_rng(4)
        c = 1950 + np.cumsum(rng.normal(0, 3, 600))
        df = bars(c + rng.uniform(0, 4, 600), c - rng.uniform(0, 4, 600), c)
        full = h13.events(df)
        for cut in (150, 333, 520):
            pre = h13.events(df.iloc[:cut])
            want = full[full.t + h13.HORIZON_BARS < cut].reset_index(drop=True)
            pd.testing.assert_frame_equal(pre, want)


class TestH14(unittest.TestCase):
    def test_windows_across_us_dst(self):
        res = h14.overnight_vs_ny(h1_fixture())
        fri = row(res, "2024-03-08")          # EST: 18:00 Thu = 23:00 UTC, 08:00 = 13:00 UTC
        self.assertAlmostEqual(fri["r_on"], lr("2024-03-07 23:00", "2024-03-08 13:00"))
        self.assertAlmostEqual(fri["r_ny"], lr("2024-03-08 13:00", "2024-03-08 20:00"))
        mon = row(res, "2024-03-11")          # EDT
        self.assertAlmostEqual(mon["r_on"], lr("2024-03-10 22:00", "2024-03-11 12:00"))
        self.assertAlmostEqual(mon["y"], mon["r_on"] - mon["r_ny"])

    def test_missing_or_suspect_bar_drops_day(self):
        h1 = h1_fixture()
        h1 = h1[h1.time != pd.Timestamp("2024-03-13 15:00", tz="UTC")].copy()
        h1.loc[h1.time == pd.Timestamp("2024-03-14 02:00", tz="UTC"), "utc_suspect"] = True
        res = h14.overnight_vs_ny(h1)
        self.assertIsNone(row(res, "2024-03-13"))
        self.assertIsNone(row(res, "2024-03-14"))
        self.assertIsNotNone(row(res, "2024-03-12"))

    def test_truncation(self):
        from gold.hyp.anchors import NEW_YORK, local_time
        h1 = h1_fixture()
        full = h14.overnight_vs_ny(h1)
        end = local_time(full["day"], 15, NEW_YORK)
        for k in (300, 517):
            cut = h1.time.iloc[k]
            pd.testing.assert_frame_equal(h14.overnight_vs_ny(h1[h1.time < cut]),
                                          full[(end <= cut).to_numpy()].reset_index(drop=True))


class TestSpreadFill(unittest.TestCase):
    def test_zero_or_missing_takes_the_hour_median(self):
        hm = pd.Series({9: 0.2, 10: 0.3})
        t = pd.to_datetime(["2024-01-10 14:00", "2024-01-10 15:00", "2024-01-10 15:30"], utc=True)  # 09, 10, 10 EST
        np.testing.assert_allclose(power.filled([0.0, np.nan, 0.5], t, hm), [0.2, 0.3, 0.5])
        idx = [7, 3, 11]                                 # a filtered frame keeps its old index
        np.testing.assert_allclose(power.filled(pd.Series([0.0, np.nan, 0.5], index=idx),
                                                pd.Series(t, index=idx), hm), [0.2, 0.3, 0.5])


if __name__ == "__main__":
    unittest.main()
