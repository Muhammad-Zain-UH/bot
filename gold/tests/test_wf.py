"""W01 walk-forward machinery on synthetic H1 sessions (18:00 -> 16:00 New York)."""
import unittest

import numpy as np
import pandas as pd

from gold.data.broker_daily import session_of
from gold.wf import menu as M
from gold.wf import select as S
from gold.wf.bars import Bars

NY = "America/New_York"


def synthetic(days=90, seed=0, start="2020-01-06"):
    rng = np.random.default_rng(seed)
    times = []
    for d in pd.bdate_range(start, periods=days):
        open_ny = pd.Timestamp(d - pd.Timedelta(days=1)).tz_localize(NY) + pd.Timedelta(hours=18)
        times += [(open_ny + pd.Timedelta(hours=k)).tz_convert("UTC") for k in range(23)]
    n = len(times)
    c = 2000 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.concatenate([[2000.0], c[:-1]]) * (1 + rng.normal(0, 0.0005, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    h1 = pd.DataFrame({"time": pd.DatetimeIndex(times), "open": o, "high": h, "low": l, "close": c, "spread_usd": 0.3})
    g = h1.groupby(session_of(h1["time"]).rename("session"))
    d1 = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return Bars(h1, d1)


def tiny(o, h, l, c):
    t = pd.date_range("2020-01-07 00:00", periods=len(o), freq="h", tz="UTC")
    h1 = pd.DataFrame({"time": t, "open": o, "high": h, "low": l, "close": c, "spread_usd": 0.3})
    d1 = pd.DataFrame({"session": pd.to_datetime(["2020-01-07"]), "open": [o[0]], "high": [max(h)], "low": [min(l)],
                       "close": [c[-1]]})
    return Bars(h1, d1)


B = synthetic()


class TestMenu(unittest.TestCase):
    def test_counts(self):
        v = M.menu()
        self.assertEqual(len(v), 102)
        self.assertEqual(len({x.name for x in v}), 102)
        fam = pd.Series([x.family for x in v]).value_counts().to_dict()
        self.assertEqual(fam, {"a_donchian": 24, "b_ma_trend": 24, "g_time_of_day": 20, "c_mean_reversion": 16,
                               "f_fvg": 8, "e_sweep": 6, "d_session_breakout": 4})


class TestManage(unittest.TestCase):
    def test_stop_first_gap_fill_target_and_time(self):
        b = tiny([100, 100, 95, 100], [101, 106, 96, 101], [99, 97, 94, 99], [100, 100, 95, 100])
        self.assertEqual(M.manage(b, 1, 100, 1, 98, 105), (1, 98, "stop"))       # both in one bar: the stop
        self.assertEqual(M.manage(b, 0, 100, 1, 96.5, 110), (2, 95, "stop"))     # bar 1 low 97 holds; bar 2 gaps to 95
        b2 = tiny([100, 100, 90, 100], [101, 101, 91, 101], [99, 99, 89, 99], [100, 100, 90, 100])
        self.assertEqual(M.manage(b2, 0, 100, 1, 95), (2, 90, "stop"))            # gap through: filled at the open
        self.assertEqual(M.manage(b2, 0, 100, -1, 105, 92), (2, 92, "target"))
        self.assertEqual(M.manage(b2, 0, 100, 1, 50, None, None, 1), (1, 100, "time"))


class TestRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = {v.vid: M.trades(B, v) for v in M.menu()}

    def test_every_family_trades_and_no_entry_on_a_reopen_bar(self):
        fams = {v.family for v in M.menu() if len(self.tr[v.vid])}
        self.assertEqual(len(fams), 7)
        for v in M.menu():
            t = self.tr[v.vid]
            self.assertFalse(B.reopen[t["entry_idx"].to_numpy(int)].any(), v.name)
            self.assertTrue((t["exit_idx"] >= t["entry_idx"]).all())
            self.assertTrue(((t["entry"] - t["stop"]) * t["side"] > 0).all(), v.name)

    def test_d1_entries_start_an_hour_after_the_reopen(self):
        for v in M.menu():
            if dict(v.params).get("tf") == "D1" and len(self.tr[v.vid]):
                e = self.tr[v.vid]["entry_idx"].to_numpy(int)
                ny = B.h1["time"].iloc[e].dt.tz_convert(NY).dt.hour
                self.assertTrue((ny == 19).all(), v.name)

    def test_session_and_block_exits(self):
        for v in M.menu():
            t = self.tr[v.vid]
            if v.family == "d_session_breakout" and len(t):
                h = B.h1["time"].iloc[t["exit_idx"].to_numpy(int)].dt.tz_convert(NY).dt.hour
                self.assertTrue((h <= 14).all())
            if v.family == "g_time_of_day" and len(t):
                self.assertTrue(((t["exit_idx"] - t["entry_idx"]) <= 3).all())

    def test_trades_use_no_data_after_t(self):
        cut = B.h1["time"].iloc[23 * 60]                       # a session open
        early = B.truncate(cut)
        for v in M.menu():
            full = self.tr[v.vid]
            part = M.trades(early, v)
            lim = cut - pd.Timedelta(days=3)
            a = full[full["exit_time"] < lim][["entry_time", "exit_time", "entry", "exit", "stop"]].reset_index(drop=True)
            b = part[part["exit_time"] < lim][["entry_time", "exit_time", "entry", "exit", "stop"]].reset_index(drop=True)
            pd.testing.assert_frame_equal(a, b, check_dtype=False, obj=v.name)


class TestNetR(unittest.TestCase):
    def test_cost_and_financing(self):
        tr = pd.DataFrame({"entry_idx": [20], "exit_idx": [30], "side": [1], "entry": [2000.0], "exit": [2010.0],
                           "stop": [1995.0]})
        dff = pd.Series([4.0], index=pd.to_datetime(["2019-12-01"]))
        r = M.net_r(tr, B, dff, 4.625)
        t = B.h1["time"]
        nights = (session_of(t.iloc[[30]]).iloc[0] - session_of(t.iloc[[20]]).iloc[0]).days
        fin = 2000 * (0.04 + 0.025) * nights / 365
        self.assertEqual(nights, 1)
        self.assertAlmostEqual(r[0], (10 - 4.625 * 0.3 - fin) / 5)
        self.assertAlmostEqual(M.net_r(tr, B, dff, 4.625, 2.0)[0], (10 - 2 * (4.625 * 0.3 + fin)) / 5)


class TestSelect(unittest.TestCase):
    def frame(self):
        rows = []
        for m in pd.period_range("2020-01", "2020-12", freq="M"):
            for vid, r in ((0, 1.0), (1, -0.5), (2, 0.2)):
                for k in range(6):
                    e = pd.Timestamp(m.start_time, tz="UTC") + pd.Timedelta(days=k + 1)
                    rows.append({"vid": vid, "entry_time": e, "exit_time": e + pd.Timedelta(hours=5),
                                 "r": r + 0.01 * k})
        late = pd.Timestamp("2020-06-30 20:00", tz="UTC")
        rows.append({"vid": 1, "entry_time": late, "exit_time": late + pd.Timedelta(days=2), "r": 99.0})
        return pd.DataFrame(rows)

    def test_scores_only_use_closed_trades(self):
        tr = self.frame()
        sc = S.scores(tr, pd.Period("2020-07", "M"))
        self.assertEqual(S.ranked(sc), [0, 2, 1])               # the open 99 R trade is not yet known
        self.assertLess(sc[1], 0)
        self.assertGreater(S.scores(tr, pd.Period("2020-08", "M"))[1], sc[1])

    def test_walk_ic_and_random_control(self):
        tr = self.frame()
        months = pd.period_range("2020-03", "2020-12", freq="M")
        res, elig = S.walk(tr, [0, 1, 2], months, lookback=2)
        self.assertEqual(res["chosen"].iloc[0], [0])
        R = S.monthly_r(tr, [0, 1, 2], months)
        self.assertAlmostEqual(res["r"].iloc[0], R.iloc[0][0])
        self.assertTrue(res["ic"].isna().all())                 # fewer than 5 eligible variants
        paths = S.random_control(R, elig, 500, 1)
        np.testing.assert_array_equal(paths, S.random_control(R, elig, 500, 1))
        self.assertTrue(((paths >= R.min(axis=1).mean() - 1e-9) & (paths <= R.max(axis=1).mean() + 1e-9)).all())
        self.assertAlmostEqual(S.spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]), 1.0)


if __name__ == "__main__":
    unittest.main()
