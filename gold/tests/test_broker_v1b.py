"""Broker v1b: two-period server-time conversion and the weekly utc_suspect
check, on synthetic data only."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gold.data import build_broker_v1b as b1b, store
from research.dataset_access import DatasetIntegrityError, OOSLockedError, _fingerprint


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def server(*s):
    return pd.Series([f"{x}+00:00" for x in s])


def raw_frame(times):
    n = len(times)
    return pd.DataFrame({"time_server": [f"{t}+00:00" for t in times],
                         "open": [1.0] * n, "high": [2.0] * n, "low": [0.5] * n,
                         "close": [1.5] * n, "tick_volume": [10] * n,
                         "spread": list(range(n)), "real_volume": [0] * n})


def week_h1(monday: dt.date, shift_h: int = 0) -> pd.Series:
    """UTC H1 bar opens of one trading week (Sun 18:00 -> Fri 17:00 New York,
    daily break 17:00-18:00), mislabelled by shift_h hours."""
    out = []
    for d in range(-1, 5):
        day = monday + dt.timedelta(days=d)
        hours = range(18, 24) if d == -1 else [h for h in range(24) if h != 17]
        if d == 4:
            hours = range(0, 17)
        out += [pd.Timestamp(dt.datetime.combine(day, dt.time(h)), tz=b1b.NEW_YORK)
                for h in hours]
    t = pd.Series(out).dt.tz_convert("UTC") + pd.Timedelta(hours=shift_h)
    return t.astype("datetime64[ns, UTC]")


class TestServerToUtc(unittest.TestCase):
    def check(self, cases):
        got = b1b.server_to_utc(server(*[a for a, _ in cases]))
        self.assertEqual(list(got), [ts(u) for _, u in cases])

    def test_us_rule_around_2019_us_dst_changes(self):
        self.check([
            ("2019-03-08 23:00", "2019-03-08 21:00"),   # Fri 16:00 EST
            ("2019-03-11 01:00", "2019-03-10 22:00"),   # Sun 18:00 EDT; EU still winter
            ("2019-11-01 23:00", "2019-11-01 20:00"),   # Fri 16:00 EDT; EU already winter
            ("2019-11-04 01:00", "2019-11-03 23:00"),   # Sun 18:00 EST
        ])

    def test_eu_rule_around_2024_us_dst_changes(self):
        self.check([
            ("2024-03-08 23:00", "2024-03-08 21:00"),   # Fri 16:00 EST, server GMT+2
            ("2024-03-11 00:00", "2024-03-10 22:00"),   # Sun 18:00 EDT, server still GMT+2
            ("2024-04-01 01:00", "2024-03-31 22:00"),   # Sun 18:00 EDT, server GMT+3
            ("2024-11-01 23:00", "2024-11-01 21:00"),   # Fri 17:00 EDT -- closed; GMT+2 since 10-27
            ("2024-11-04 01:00", "2024-11-03 23:00"),   # Sun 18:00 EST
        ])

    def test_owner_cases_in_the_us_eu_gap(self):
        self.check([("2019-03-11 01:00", "2019-03-10 22:00"),     # old rule
                    ("2021-03-15 00:00", "2021-03-14 22:00")])    # new rule

    def test_winter_monday_0100_server_is_sunday_2300_utc(self):
        for monday in ("2019-01-07", "2024-01-08"):
            got = b1b.server_to_utc(server(f"{monday} 01:00")).iloc[0]
            self.assertEqual(got, ts(f"{monday} 01:00") - pd.Timedelta(hours=2))
            self.assertEqual(got.day_name(), "Sunday")

    def test_rule_switch_is_continuous(self):
        got = b1b.server_to_utc(server("2020-06-30 23:00", "2020-07-01 00:00"))
        self.assertEqual(list(got), [ts("2020-06-30 20:00"), ts("2020-06-30 21:00")])

    def test_nonexistent_and_ambiguous_local_hours_fail(self):
        for bad in ("2019-03-10 09:30",    # 02:30 New York does not exist
                    "2019-11-03 08:30",    # 01:30 New York occurs twice
                    "2024-03-31 03:30",    # 03:30 Athens does not exist
                    "2024-10-27 03:30"):   # 03:30 Athens occurs twice
            with self.subTest(bad), self.assertRaises(ValueError):
                b1b.server_to_utc(server(bad))

    def test_truncation(self):
        times = pd.date_range("2020-06-29 20:00", "2020-07-02 04:00", freq="1h")
        times = [t.strftime("%Y-%m-%d %H:%M") for t in times]
        full = b1b.convert(raw_frame(times), 0.01)
        for k in (1, 30, 70, len(times) - 1):
            pd.testing.assert_frame_equal(b1b.convert(raw_frame(times[:k]), 0.01),
                                          full.iloc[:k].reset_index(drop=True))


class TestUtcSuspect(unittest.TestCase):
    def setUp(self):
        self.w1, self.w2, self.w3 = (dt.date(2024, 1, 8), dt.date(2024, 1, 15),
                                     dt.date(2024, 1, 22))
        self.h1 = pd.concat([week_h1(self.w1), week_h1(self.w2, shift_h=1),
                             week_h1(self.w3, shift_h=-1)], ignore_index=True)

    def test_weeks_whose_reopens_disagree_are_flagged(self):
        w = b1b.reopen_weeks(self.h1).set_index("week")
        self.assertEqual(w.loc[pd.Timestamp(self.w1), "implied_offset_h"], 0)
        self.assertEqual(w.loc[pd.Timestamp(self.w2), "implied_offset_h"], 1)
        self.assertEqual(w.loc[pd.Timestamp(self.w3), "implied_offset_h"], -1)
        self.assertEqual(list(w["utc_suspect"]), [False, True, True])
        # Sunday + Mon..Thu reopens; the series' first bar has no gap before it
        self.assertEqual(w.loc[pd.Timestamp(self.w1), "reopens"], 4)
        self.assertEqual(w.loc[pd.Timestamp(self.w2), "reopens"], 5)

    def test_flag_marks_every_bar_of_the_week_and_shifts_nothing(self):
        frame = pd.DataFrame({"time": self.h1})
        for c in b1b.COLUMNS[1:]:
            frame[c] = 1.0
        w = b1b.reopen_weeks(self.h1)
        flagged = b1b.flag(frame, set(w.loc[w.utc_suspect, "week"]))
        pd.testing.assert_series_equal(flagged["time"], frame["time"])
        n1, n2 = len(week_h1(self.w1)), len(week_h1(self.w2))
        self.assertFalse(flagged["utc_suspect"].iloc[:n1].any())
        self.assertTrue(flagged["utc_suspect"].iloc[n1:].all())

    def test_truncation_for_complete_weeks(self):
        full = b1b.reopen_weeks(self.h1)
        n1 = len(week_h1(self.w1))
        for k in (n1, n1 + 40, len(self.h1) - 10):
            pre = b1b.reopen_weeks(self.h1.iloc[:k])
            pd.testing.assert_frame_equal(pre.iloc[:1], full.iloc[:1])


class TestBuild(unittest.TestCase):
    def test_columns_spread_flag_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir, out_dir = Path(tmp) / "raw", Path(tmp) / "out"
            raw_dir.mkdir()
            for tf in b1b.TIMEFRAMES:
                raw_frame(["2024-01-08 01:00", "2024-01-08 02:00"]).to_csv(
                    raw_dir / f"XAUUSD_{tf}_server.csv", index=False)
            frames, weeks = b1b.build(raw_dir, out_dir, 0.01)
            h1 = pd.read_parquet(out_dir / "XAUUSD_H1.parquet")
            pd.testing.assert_frame_equal(h1, frames["H1"])
            self.assertEqual(list(h1.columns), b1b.COLUMNS)
            self.assertEqual(list(h1.spread_usd), [0.0, 0.01])
            self.assertEqual(list(h1.time), [ts("2024-01-07 23:00"), ts("2024-01-08 00:00")])
            self.assertEqual(list(h1.utc_suspect), [False, False])
            before = (out_dir / "XAUUSD_H1.parquet").read_bytes()
            with self.assertRaises(b1b.OutputExistsError):
                b1b.build(raw_dir, out_dir, 0.01)
            self.assertEqual((out_dir / "XAUUSD_H1.parquet").read_bytes(), before)


class TestLoader(unittest.TestCase):
    def test_committed_split_copies_h1_boundaries_and_lock(self):
        h1 = json.loads(b1b.H1_MANIFEST.read_text(encoding="utf-8"))
        v1b = json.loads(store.MANIFEST_H1_V1B.read_text(encoding="utf-8"))
        self.assertEqual(v1b, json.loads(json.dumps(b1b.split_manifest(h1))))
        for arm, v in h1["arms"].items():
            self.assertEqual((v1b["arms"][arm]["from_utc"], v1b["arms"][arm]["to_utc"]),
                             (v["from_utc"], v["to_utc"]))
        self.assertEqual(v1b["purge_embargo"], h1["purge_embargo"])
        self.assertEqual(v1b["oos_authorisation_token"], "OOS-AUTHORISATION-NOT-ISSUED")
        self.assertTrue(v1b["FINAL_OOS_LOCKED"])

    def test_final_oos_is_locked_before_any_read(self):
        missing = Path(tempfile.gettempdir()) / "no-such-v1b-dir"
        for token in (None, "", "wrong"):
            with self.assertRaises(OOSLockedError):
                store.load_broker_v1b("H1", "FINAL_OOS", token, bars_dir=missing)

    def test_arm_slice_and_fingerprint(self):
        h1 = b1b.convert(raw_frame(["2020-12-31 19:00", "2020-12-31 20:00",
                                    "2021-01-04 05:00"]), 0.01)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            h1.to_parquet(d / "XAUUSD_H1.parquet", index=False)
            fp = d / "fp.json"
            fp.write_text(json.dumps({"frames": {"H1": {
                "values_sha256": _fingerprint(h1[b1b.COLUMNS])}}}))
            train = store.load_broker_v1b("H1", "TRAIN", bars_dir=d, fingerprints=fp)
            dev = store.load_broker_v1b("H1", "DEV", bars_dir=d, fingerprints=fp)
            self.assertEqual(list(train.time), [ts("2020-12-31 17:00")])   # 18:00 is past TRAIN
            self.assertEqual(list(dev.time), [ts("2021-01-04 03:00")])
            fp.write_text(json.dumps({"frames": {"H1": {"values_sha256": "0" * 64}}}))
            with self.assertRaises(DatasetIntegrityError):
                store.load_broker_v1b("H1", "TRAIN", bars_dir=d, fingerprints=fp)


if __name__ == "__main__":
    unittest.main()
