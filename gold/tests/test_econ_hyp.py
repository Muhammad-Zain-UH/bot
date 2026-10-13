"""P2: costs, calibration arithmetic, batch-1 variables, D1 bars -- synthetic data only."""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gold.data import broker_daily, calibrate_cost, store
from gold.econ import costs, power
from gold.hyp import h07_sessions, h08_intraday_momentum, h09_pm_auction
from gold.hyp.anchors import LONDON, NEW_YORK, local_time
from research.dataset_access import OOSLockedError

T0 = pd.Timestamp("2024-03-01", tz="UTC")


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def p(t):
    """Known price path, USD per oz, at UTC instant(s) t."""
    h = (pd.DatetimeIndex(np.atleast_1d(t)) - T0) / pd.Timedelta(hours=1)
    return np.asarray(2000 + 0.37 * h + 3 * np.sin(h), dtype=float)


def trading_hour(t: pd.DatetimeIndex) -> np.ndarray:
    ny = t.tz_convert(NEW_YORK)
    dow, hour = ny.dayofweek, ny.hour
    closed = (dow == 5) | ((dow == 4) & (hour >= 17)) | ((dow == 6) & (hour < 18)) | (hour == 17)
    return ~np.asarray(closed)


def h1_fixture(start="2024-03-03", end="2024-04-06"):
    """Hourly bars over a US DST change (2024-03-10), the EU-only gap weeks and the
    EU change (2024-03-31): open = p(t), close = p(t + 1 h)."""
    t = pd.date_range(ts(start), ts(end), freq="1h", inclusive="left")
    t = t[trading_hour(t)]
    o, c = p(t), p(t + pd.Timedelta(hours=1))
    return pd.DataFrame({"time": t, "open": o, "high": np.maximum(o, c) + 0.1,
                         "low": np.minimum(o, c) - 0.1, "close": c, "tick_volume": 10.0,
                         "spread_usd": 0.1 + 0.01 * (t.hour % 5), "utc_suspect": False})


def lr(a, b):
    return float(np.log(p(ts(b))[0] / p(ts(a))[0]))


def row(df, day):
    sel = df[df["day"] == pd.Timestamp(day)]
    return sel.iloc[0] if len(sel) else None


class TestCosts(unittest.TestCase):
    def test_round_turn(self):
        self.assertAlmostEqual(costs.round_turn_cost_usd(0.3, 0.5, 2.0), 0.8)
        np.testing.assert_allclose(costs.round_turn_cost_usd([0.2, 0.4], [0.2, 0.0], 1.5), [0.3, 0.3])

    def test_cost_in_log_units(self):
        self.assertAlmostEqual(costs.cost_in_log_units(1.0, 2000.0), math.log(2001 / 2000))

    def test_financing(self):
        self.assertAlmostEqual(costs.financing_usd(100_000, 2, "long", 0.05), 100_000 * 0.075 * 2 / 365)
        self.assertAlmostEqual(costs.financing_usd(100_000, 2, "short", 0.05), 100_000 * 0.025 * 2 / 365)
        self.assertAlmostEqual(costs.financing_usd(100_000, 3, "long", 0.0, markup=0.01), 100_000 * 0.01 * 3 / 365)
        with self.assertRaises(ValueError):
            costs.financing_usd(1, 1, "flat", 0.05)


class TestCalibration(unittest.TestCase):
    def test_k_cost_uses_shared_hours_and_floors_at_one(self):
        ticks = pd.DataFrame({"time": [ts("2026-10-05 14:10"), ts("2026-10-05 14:20"),
                                       ts("2026-10-05 15:10"), ts("2026-10-05 16:10")],
                              "bid": [100.0, 100.0, 100.0, 100.0], "ask": [100.4, 100.2, 100.6, 109.0]})
        bars = pd.DataFrame({"time": [ts("2026-10-05 14:00"), ts("2026-10-05 15:00")],
                             "spread_usd": [0.1, 0.1]})
        r = calibrate_cost.k_cost(ticks, bars)            # the 16:00 tick has no bar: ignored
        self.assertAlmostEqual(r["tick_spread_median_usd"], 0.4)
        self.assertAlmostEqual(r["k_cost"], 4.0)
        self.assertEqual(r["hours_used"], 2)
        self.assertEqual(set(r["tick_spread_per_ny_hour"]), {10, 11})   # 14/15 UTC = 10/11 EDT
        bars["spread_usd"] = 1.0
        self.assertEqual(calibrate_cost.k_cost(ticks, bars)["k_cost"], 1.0)
        bars["spread_usd"] = 0.0
        with self.assertRaises(calibrate_cost.CalibrationError):
            calibrate_cost.k_cost(ticks, bars)

    def test_spread_completeness(self):
        h1 = pd.DataFrame({"time": [ts("2021-01-04"), ts("2021-01-05"), ts("2022-01-04")],
                           "spread_usd": [0.0, 0.2, np.nan]})
        self.assertEqual(calibrate_cost.spread_completeness(h1),
                         {2021: {"bars": 2, "zero_or_missing_share": 0.5},
                          2022: {"bars": 1, "zero_or_missing_share": 1.0}})


class TestH07(unittest.TestCase):
    def setUp(self):
        self.h1 = h1_fixture()
        self.res = h07_sessions.block_returns(self.h1)

    def test_blocks_follow_new_york_time_across_the_us_dst_change(self):
        fri = row(self.res, "2024-03-08")          # EST: day starts Thu 23:00 UTC
        self.assertAlmostEqual(fri["r_B1"], lr("2024-03-07 23:00", "2024-03-08 03:00"))
        self.assertAlmostEqual(fri["r_B6"], lr("2024-03-08 19:00", "2024-03-08 22:00"))
        mon = row(self.res, "2024-03-11")          # EDT: day starts Sun 22:00 UTC
        self.assertAlmostEqual(mon["r_B1"], lr("2024-03-10 22:00", "2024-03-11 02:00"))
        self.assertAlmostEqual(mon["r_B4"], lr("2024-03-11 10:00", "2024-03-11 14:00"))
        self.assertAlmostEqual(mon["p_start_usd"], p(ts("2024-03-10 22:00"))[0])
        total = sum(mon[f"r_{b}"] for b, _, _ in h07_sessions.BLOCKS)
        self.assertAlmostEqual(total, lr("2024-03-10 22:00", "2024-03-11 21:00"))

    def test_missing_or_suspect_bar_drops_the_day(self):
        h1 = self.h1[self.h1.time != ts("2024-03-14 05:00")].copy()
        h1.loc[h1.time == ts("2024-03-19 20:00"), "utc_suspect"] = True
        res = h07_sessions.block_returns(h1)
        self.assertIsNone(row(res, "2024-03-14"))
        self.assertIsNone(row(res, "2024-03-19"))
        self.assertIsNotNone(row(res, "2024-03-13"))
        self.assertIsNotNone(row(res, "2024-03-20"))


class TestH08(unittest.TestCase):
    def test_windows_and_zero_early_return(self):
        h1 = h1_fixture()
        r = row(h08_intraday_momentum.momentum(h1), "2024-03-12")      # EDT
        self.assertAlmostEqual(r["r_early"], lr("2024-03-11 22:00", "2024-03-12 16:00"))
        self.assertAlmostEqual(r["r_late"], lr("2024-03-12 16:00", "2024-03-12 18:00"))
        self.assertAlmostEqual(r["y"], np.sign(r["r_early"]) * r["r_late"])
        flat = h1.copy()                     # make the 12:00 close equal the 18:00 open
        flat.loc[flat.time == ts("2024-03-13 15:00"), "close"] = p(ts("2024-03-12 22:00"))[0]
        res = h08_intraday_momentum.momentum(flat)
        self.assertIsNone(row(res, "2024-03-13"))
        self.assertIsNotNone(row(h07_sessions.block_returns(flat), "2024-03-13"))


class TestH09(unittest.TestCase):
    def test_london_hours_across_the_eu_only_gap_and_eu_change(self):
        res = h09_pm_auction.auction(h1_fixture())
        gap = row(res, "2024-03-12")         # US on summer time, London still GMT
        self.assertAlmostEqual(gap["r_pre"], lr("2024-03-12 14:00", "2024-03-12 15:00"))
        self.assertAlmostEqual(gap["r_post"], lr("2024-03-12 15:00", "2024-03-12 16:00"))
        self.assertAlmostEqual(gap["y"], -np.sign(gap["r_pre"]) * gap["r_post"])
        bst = row(res, "2024-04-02")         # London on BST
        self.assertAlmostEqual(bst["r_pre"], lr("2024-04-02 13:00", "2024-04-02 14:00"))

    def test_missing_or_suspect_bar_drops_the_day(self):
        h1 = h1_fixture()
        h1 = h1[h1.time != ts("2024-03-14 13:00")].copy()
        h1.loc[h1.time == ts("2024-03-15 15:00"), "utc_suspect"] = True
        h1 = h1[h1.time != ts("2024-03-18 05:00")]                 # not a bar H09 needs
        res = h09_pm_auction.auction(h1)
        self.assertIsNone(row(res, "2024-03-14"))
        self.assertIsNone(row(res, "2024-03-15"))
        self.assertIsNotNone(row(res, "2024-03-18"))


class TestTruncation(unittest.TestCase):
    """A prefix of the bars yields exactly the full result's rows whose last
    anchor lies inside the prefix (no lookahead)."""

    def test_no_lookahead(self):
        h1 = h1_fixture()
        cases = ((h07_sessions.block_returns, 17, NEW_YORK), (h08_intraday_momentum.momentum, 14, NEW_YORK),
                 (h09_pm_auction.auction, 16, LONDON))
        rng = np.random.default_rng(1)
        for fn, end_hour, tz in cases:
            full = fn(h1)
            end = local_time(full["day"], end_hour, tz)
            for _ in range(6):
                cut = h1.time.iloc[int(rng.integers(50, len(h1) - 50))]
                pre = fn(h1[h1.time < cut])
                want = full[(end <= cut).to_numpy()].reset_index(drop=True)
                pd.testing.assert_frame_equal(pre, want, obj=f"{fn.__module__} cut {cut}")


def h4_from_h1(h1):
    ny = h1.time.dt.tz_convert(NEW_YORK).dt.tz_localize(None)
    wall = ny.dt.floor("1h") - pd.to_timedelta((ny.dt.hour - 17) % 4, unit="h")
    key = wall.dt.tz_localize(NEW_YORK).dt.tz_convert("UTC")
    g = h1.groupby(key.rename("time"))
    return g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                 close=("close", "last"), tick_volume=("tick_volume", "sum"),
                 spread_usd=("spread_usd", "median"), utc_suspect=("utc_suspect", "any")).reset_index()


class TestDaily(unittest.TestCase):
    def test_sessions_close_at_1700_new_york_across_dst(self):
        h1 = h1_fixture()
        d1 = broker_daily.daily_bars(h4_from_h1(h1)).set_index("session")
        fri, mon = d1.loc[pd.Timestamp("2024-03-08")], d1.loc[pd.Timestamp("2024-03-11")]
        self.assertEqual(fri["time"], ts("2024-03-07 22:00"))       # 17:00 EST
        self.assertEqual(mon["time"], ts("2024-03-10 21:00"))       # 17:00 EDT
        self.assertAlmostEqual(mon["open"], p(ts("2024-03-10 22:00"))[0])
        self.assertAlmostEqual(mon["close"], p(ts("2024-03-11 21:00"))[0])
        self.assertTrue((d1.index.dayofweek < 5).all())

    def test_off_grid_h4_fails(self):
        h4 = h4_from_h1(h1_fixture())
        h4.loc[3, "time"] += pd.Timedelta(hours=2)
        with self.assertRaises(ValueError):
            broker_daily.daily_bars(h4)

    def test_truncation_for_complete_sessions(self):
        h4 = h4_from_h1(h1_fixture())
        full = broker_daily.daily_bars(h4)
        close = local_time(full["session"], 17, NEW_YORK)
        for k in (40, 77, 120):
            cut = h4.time.iloc[k]
            pre = broker_daily.daily_bars(h4[h4.time < cut])
            pre_close = local_time(pre["session"], 17, NEW_YORK)
            pd.testing.assert_frame_equal(pre[(pre_close <= cut).to_numpy()].reset_index(drop=True),
                                          full[(close <= cut).to_numpy()].reset_index(drop=True))

    def test_d1_final_oos_is_locked(self):
        missing = Path(tempfile.gettempdir()) / "no-such-v1b-dir"
        with self.assertRaises(OOSLockedError):
            store.load_broker_v1b_d1("FINAL_OOS", bars_dir=missing)


class TestPower(unittest.TestCase):
    def test_mde_sharpe_se_and_cost_median(self):
        self.assertAlmostEqual(power.mde(0.01, 2500, 2.0), 0.0004)
        self.assertAlmostEqual(power.sharpe_se(0.5, 10), math.sqrt(1.125 / 10))
        med, missing = power.median_cost_log([0.1, 0.0, 0.3], [0.1, 0.2, 0.3], [2000, 2000, 2000], 2.0)
        self.assertAlmostEqual(med, math.log1p(0.4 / 2000))     # zero spread row is missing
        self.assertAlmostEqual(missing, 1 / 3)


if __name__ == "__main__":
    unittest.main()
