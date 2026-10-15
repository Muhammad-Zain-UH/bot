"""H12 data build on synthetic data: conversion, D1, intraday start, clock check, costs, lock."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gold.data import build_h12 as h12, store
from research.dataset_access import OOSLockedError


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def raw(times, spread=2):
    n = len(times)
    return pd.DataFrame({"time_server": [f"{t}+00:00" for t in times], "open": np.arange(n) + 1.0,
                         "high": np.arange(n) + 2.0, "low": np.arange(n) + 0.5, "close": np.arange(n) + 1.5,
                         "tick_volume": 10, "spread": spread, "real_volume": 0})


class TestConvertAndDaily(unittest.TestCase):
    def test_v1b_rule_and_spread_in_price_units(self):
        out = h12.convert(raw(["2019-03-11 00:00", "2024-01-08 00:00"]), 0.00001)
        self.assertEqual(list(out.time), [ts("2019-03-10 21:00"), ts("2024-01-07 22:00")])  # 17:00 NY both
        self.assertAlmostEqual(out.spread_px.iloc[0], 2e-5)
        self.assertFalse(out.utc_suspect.any())

    def test_truncation(self):
        times = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2024-03-04", periods=60, freq="4h")]
        full = h12.convert(raw(times), 0.01)
        for k in (1, 17, 59):
            pd.testing.assert_frame_equal(h12.convert(raw(times[:k]), 0.01), full.iloc[:k].reset_index(drop=True))

    def test_d1_at_new_york_close_with_price_unit_spread(self):
        times = [t.strftime("%Y-%m-%d %H:%M") for t in pd.date_range("2024-01-08", periods=12, freq="4h")]
        d1 = h12.d1_from_h4(h12.convert(raw(times), 0.01))
        self.assertIn("spread_px", d1.columns)
        self.assertEqual(list(d1.n_h4), [6, 6])
        self.assertEqual(d1.time.iloc[0], ts("2024-01-07 22:00"))


class TestIntradayStart(unittest.TestCase):
    def test_first_session_after_the_last_daily_only_run(self):
        sessions = pd.bdate_range("2006-01-02", periods=30)
        n_h4 = [1] * 12 + [6] * 3 + [1] * 6 + [6] * 9       # a second daily-only run ends at row 20
        d1 = pd.DataFrame({"session": sessions, "n_h4": n_h4})
        self.assertEqual(h12.intraday_start(d1), sessions[21])
        d1.loc[25, "n_h4"] = 1                                # a lone holiday bar is not a run
        self.assertEqual(h12.intraday_start(d1), sessions[21])


class TestClockCheck(unittest.TestCase):
    def week_h1(self, sunday_ny_hour, sunday):
        start = pd.Timestamp(f"{sunday} {sunday_ny_hour:02d}:00").tz_localize("America/New_York").tz_convert("UTC")
        return pd.Series(pd.date_range(start, periods=100, freq="1h"))

    def test_reopen_hour_matches_or_is_reported(self):
        good = pd.concat([self.week_h1(17, d) for d in ("2019-01-06", "2019-01-13", "2019-01-20")], ignore_index=True)
        r = h12.clock_check("EURUSD", good, ts("2018-01-01"))
        self.assertEqual(r["months_off"], {})
        self.assertEqual(r["weeks_at_expected"], 2)          # the first bar has no gap before it
        bad = pd.concat([self.week_h1(16, d) for d in ("2019-02-03", "2019-02-10", "2019-02-17")], ignore_index=True)
        self.assertEqual(h12.clock_check("EURUSD", bad, ts("2018-01-01"))["months_off"], {"2019-02": 16})
        self.assertEqual(h12.clock_check("XAUUSD", good, ts("2018-01-01"))["months_off"], {"2019-01": 17})


class TestCosts(unittest.TestCase):
    def test_tick_spread_bp(self):
        ticks = pd.DataFrame({"bid": [100.0, 100.0, 100.0, 0.0], "ask": [100.01, 100.02, 100.03, 1.0]})
        self.assertAlmostEqual(h12.tick_spread_bp(ticks), 2.0)


class TestStoreAndManifest(unittest.TestCase):
    def test_final_oos_locked_before_any_read(self):
        missing = Path(tempfile.gettempdir()) / "no-such-h12-dir"
        for tf in ("H4", "D1"):
            with self.assertRaises(OOSLockedError):
                store.load_h12("EURUSD", tf, "FINAL_OOS", bars_dir=missing)

    def test_committed_manifest_matches_the_builder(self):
        on_disk = json.loads(h12.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, json.loads(json.dumps(h12.split_manifest())))
        v1b = json.loads(h12.V1B_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["arms"]["DEV"], v1b["arms"]["DEV"])
        self.assertEqual(on_disk["arms"]["FINAL_OOS"], v1b["arms"]["FINAL_OOS"])
        self.assertTrue(on_disk["FINAL_OOS_LOCKED"])

    def test_symbol_list_matches_breadth_file(self):
        h12.check_symbol_list()
        self.assertEqual(len(h12.SYMBOLS), 29)


if __name__ == "__main__":
    unittest.main()
