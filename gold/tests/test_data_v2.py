"""V2 data pipeline on synthetic data only: no network, no real dataset."""
import datetime as dt
import io
import json
import lzma
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gold.data import build_v2, download_dukascopy, download_dukascopy_s3 as s3, store, ticks
from gold.data.build_v2 import COLUMNS, build_m1, d1_session_open, read_cli_csv, resample
from gold.data.validate_v2 import (DatasetValidationError, PriceScaleError, expected_open,
                                   longest_gaps, price_sanity, report_figures, validate_frame)
from research.dataset_access import DatasetIntegrityError, OOSLockedError, _fingerprint

UTC = "UTC"


def ts(s):
    return pd.Timestamp(s, tz=UTC)


def candles(times, close, spread=0.0, volume=10, width=0.2):
    """Candles whose open/close/high/low are consistent; ask = bid + spread."""
    times = pd.DatetimeIndex(pd.to_datetime(list(times), utc=True))
    close = np.asarray(close, dtype=float) + spread
    open_ = close - 0.05
    return pd.DataFrame({"time": times, "open": open_, "high": close + width,
                         "low": open_ - width, "close": close,
                         "volume": np.full(len(times), volume)})


def random_m1(start, end, seed=0, drop=0.1):
    rng = np.random.default_rng(seed)
    t = pd.date_range(ts(start), ts(end), freq="1min", inclusive="left")
    t = t[rng.random(len(t)) > drop]
    mid = 2000 + np.cumsum(rng.normal(0, 0.3, len(t)))
    spread = rng.uniform(0.1, 0.5, len(t))
    bid = candles(t, mid - spread / 2)
    ask = candles(t, mid - spread / 2, spread=0.0)
    for col in ("open", "high", "low", "close"):
        ask[col] = bid[col] + spread
    bid["volume"] = rng.integers(1, 50, len(t))
    return build_m1(bid, ask)[0]


class TestBuildM1(unittest.TestCase):
    def test_inner_join_drops_unpartnered_rows_and_reports_them(self):
        bid = candles(["2024-01-02 00:00", "2024-01-02 00:01", "2024-01-02 00:02"], [10, 11, 12])
        ask = candles(["2024-01-02 00:01", "2024-01-02 00:02", "2024-01-02 00:03"], [10, 11, 12], 0.3)
        m1, rep = build_m1(bid, ask)
        self.assertEqual(list(m1["time"]), [ts("2024-01-02 00:01"), ts("2024-01-02 00:02")])
        r = rep.set_index("year").loc[2024]
        self.assertEqual((r.bid_unmatched, r.ask_unmatched, r.joined), (1, 1, 2))

    def test_flat_zero_volume_candles_are_excluded(self):
        bid = candles(["2024-01-02 00:00", "2024-01-02 00:01", "2024-01-02 00:02"], [10, 11, 12])
        ask = candles(["2024-01-02 00:00", "2024-01-02 00:01", "2024-01-02 00:02"], [10, 11, 12], 0.3)
        bid.loc[1, ["open", "high", "low", "close", "volume"]] = [11, 11, 11, 11, 0]
        bid.loc[2, "volume"] = 0                     # zero volume but a range: not flat
        m1, rep = build_m1(bid, ask)
        self.assertEqual(list(m1["time"]), [ts("2024-01-02 00:00"), ts("2024-01-02 00:02")])
        r = rep.set_index("year").loc[2024]
        self.assertEqual((r.bid_flats, r.ask_flats, r.ask_unmatched), (1, 0, 1))

    def test_mid_and_spread_arithmetic(self):
        bid = pd.DataFrame({"time": [ts("2024-01-02")], "open": [10.0], "high": [12.0],
                            "low": [9.0], "close": [11.0], "volume": [5]})
        ask = pd.DataFrame({"time": [ts("2024-01-02")], "open": [10.4], "high": [12.6],
                            "low": [9.2], "close": [11.5], "volume": [7]})
        row = build_m1(bid, ask)[0].iloc[0]
        self.assertEqual(list(build_m1(bid, ask)[0].columns), COLUMNS)
        for f, want in zip("ohlc", (10.2, 12.3, 9.1, 11.25)):
            self.assertAlmostEqual(row[f"mid_{f}"], want)
        self.assertAlmostEqual(row["spread_c"], 0.5)
        self.assertEqual(row["volume"], 5)

    def test_truncation(self):
        full = random_m1("2024-01-02", "2024-01-03")
        cut = ts("2024-01-02 13:37")
        bid = full.rename(columns={"bid_o": "open", "bid_h": "high", "bid_l": "low",
                                   "bid_c": "close"})[["time", "open", "high", "low", "close", "volume"]]
        ask = full.rename(columns={"ask_o": "open", "ask_h": "high", "ask_l": "low",
                                   "ask_c": "close"})[["time", "open", "high", "low", "close", "volume"]]
        pre = build_m1(bid[bid.time < cut], ask[ask.time < cut])[0]
        pd.testing.assert_frame_equal(pre, full[full.time < cut].reset_index(drop=True))


class TestResample(unittest.TestCase):
    def test_intraday_bars_are_left_labelled_utc(self):
        m1 = random_m1("2024-01-02 00:00", "2024-01-02 08:00", drop=0)
        for tf, minute, label in (("M15", "00:14", "00:00"), ("M15", "00:15", "00:15"),
                                  ("H1", "00:59", "00:00"), ("H4", "03:59", "00:00"),
                                  ("H4", "04:00", "04:00")):
            got = build_v2.bar_open(pd.Series([ts(f"2024-01-02 {minute}")]), tf).iloc[0]
            self.assertEqual(got, ts(f"2024-01-02 {label}"), (tf, minute))
        h1 = resample(m1, "H1").iloc[0]
        first = m1[m1.time < ts("2024-01-02 01:00")]
        self.assertEqual(h1["bid_o"], first["bid_o"].iloc[0])
        self.assertEqual(h1["ask_h"], first["ask_h"].max())
        self.assertEqual(h1["bid_l"], first["bid_l"].min())
        self.assertEqual(h1["ask_c"], first["ask_c"].iloc[-1])
        self.assertEqual(h1["volume"], first["volume"].sum())
        self.assertAlmostEqual(h1["mid_h"], (h1["bid_h"] + h1["ask_h"]) / 2)
        self.assertAlmostEqual(h1["spread_c"], h1["ask_c"] - h1["bid_c"])

    def test_d1_boundary_is_1700_new_york_across_2024_dst_changes(self):
        cases = [  # minute (UTC) -> D1 bar open (UTC)
            ("2024-03-08 21:59", "2024-03-07 22:00"),   # 16:59 EST
            ("2024-03-08 22:00", "2024-03-08 22:00"),   # 17:00 EST
            ("2024-03-11 20:59", "2024-03-10 21:00"),   # 16:59 EDT, after 2024-03-10
            ("2024-03-11 21:00", "2024-03-11 21:00"),   # 17:00 EDT
            ("2024-11-01 20:59", "2024-10-31 21:00"),   # 16:59 EDT
            ("2024-11-04 21:59", "2024-11-03 22:00"),   # 16:59 EST, after 2024-11-03
            ("2024-11-04 22:00", "2024-11-04 22:00"),   # 17:00 EST
        ]
        got = d1_session_open(pd.Series([ts(a) for a, _ in cases]))
        self.assertEqual(list(got), [ts(b) for _, b in cases])

    def test_d1_bars_from_m1_split_at_new_york_close(self):
        m1 = random_m1("2024-03-07 20:00", "2024-03-12 00:00", drop=0)
        d1 = resample(m1, "D1")
        self.assertIn(ts("2024-03-07 22:00"), set(d1.time))
        self.assertIn(ts("2024-03-10 21:00"), set(d1.time))
        mon = m1[(m1.time >= ts("2024-03-10 21:00")) & (m1.time < ts("2024-03-11 21:00"))]
        row = d1.set_index("time").loc[ts("2024-03-10 21:00")]
        self.assertEqual(row["bid_o"], mon["bid_o"].iloc[0])
        self.assertEqual(row["bid_c"], mon["bid_c"].iloc[-1])

    def test_truncation_for_complete_bars(self):
        m1 = random_m1("2024-03-07", "2024-03-13", seed=3)
        rng = np.random.default_rng(7)
        for tf in ("M15", "H1", "H4", "D1"):
            full = resample(m1, tf)
            for _ in range(5):
                cut = m1.time.iloc[int(rng.integers(100, len(m1) - 100))]
                pre = resample(m1[m1.time < cut], tf)
                dur = build_v2.TF_DURATION[tf]
                a = pre[pre.time + dur <= cut].reset_index(drop=True)
                b = full[full.time + dur <= cut].reset_index(drop=True)
                pd.testing.assert_frame_equal(a, b, obj=f"{tf} cut {cut}")


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.m1 = random_m1("2024-01-02", "2024-01-04")

    def test_valid_frames_pass_at_every_timeframe(self):
        for tf in build_v2.TIMEFRAMES:
            validate_frame(resample(self.m1, tf), tf)

    def test_each_invariant_fails(self):
        def broken(fn):
            df = self.m1.copy()
            fn(df)
            return df
        cases = {
            "NaN": broken(lambda d: d.__setitem__("bid_c", d["bid_c"].where(d.index != 5))),
            "duplicate": pd.concat([self.m1, self.m1.iloc[[3]]]).sort_values("time", kind="stable"),
            "not increasing": self.m1.iloc[::-1].reset_index(drop=True),
            "bid_h": broken(lambda d: d.loc.__setitem__((7, "bid_h"), d.loc[7, "bid_c"] - 1)),
            "ask_l": broken(lambda d: d.loc.__setitem__((7, "ask_l"), d.loc[7, "ask_o"] + 1)),
            "ask_c < bid_c": broken(lambda d: d.loc.__setitem__((9, "ask_c"), d.loc[9, "bid_c"] - 0.01)),
        }
        for name, df in cases.items():
            with self.subTest(name), self.assertRaises(DatasetValidationError):
                validate_frame(df, "M1")
        with self.assertRaises(DatasetValidationError):
            validate_frame(self.m1.drop(columns="volume"), "M1")

    def test_price_sanity(self):
        def frame(p2011, p2020):
            return pd.DataFrame({"time": [ts("2011-09-06 12:00"), ts("2020-08-07 12:00")],
                                 "mid_h": [p2011, p2020]})
        self.assertEqual(price_sanity(frame(1911.0, 2075.0)),
                         {"2011-09": 1911.0, "2020-08": 2075.0})
        for bad in (frame(19110.0, 20750.0), frame(1.911, 2.075), frame(1911.0, 2200.0)):
            with self.assertRaises(PriceScaleError):
                price_sanity(bad)
        with self.assertRaises(PriceScaleError):
            price_sanity(frame(1911.0, 2075.0).iloc[:1])


class TestReportFigures(unittest.TestCase):
    def test_gaps_exclude_weekend_and_daily_break(self):
        grid = pd.Series(pd.date_range(ts("2024-03-03 23:00"), ts("2024-03-15 20:00"), freq="1min"))
        t = grid[expected_open(grid).to_numpy()]
        hole = (t >= ts("2024-03-06 12:00")) & (t < ts("2024-03-06 13:00"))
        m1 = pd.DataFrame({c: np.ones(int((~hole).sum())) for c in COLUMNS})
        m1["time"] = t[~hole].to_numpy()
        gaps = longest_gaps(m1)
        self.assertEqual(gaps, {2024: [{"start_utc": "2024-03-06T12:00:00+00:00",
                                        "end_utc": "2024-03-06T12:59:00+00:00",
                                        "missing_minutes": 60}]})

    def test_spread_tables_use_new_york_hour(self):
        m1 = pd.DataFrame({c: [1.0, 1.0] for c in COLUMNS})
        m1["time"] = [ts("2024-01-10 14:00"), ts("2024-07-10 13:00")]   # both 09:00 NY
        m1["spread_c"] = [0.2, 0.4]
        fig = report_figures(m1)
        self.assertEqual(list(fig["spread_c_per_ny_hour"]), [9])
        self.assertAlmostEqual(fig["spread_c_per_ny_hour"][9]["median_usd"], 0.3)
        self.assertEqual(fig["bars_per_year"], {2024: 2})


class TestStore(unittest.TestCase):
    def test_committed_manifest_matches_the_computed_split(self):
        on_disk = json.loads(store.MANIFEST_V2.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, json.loads(json.dumps(store.build_manifest())))

    def test_arms_end_at_new_york_close_and_purge_one_trading_day(self):
        m = store.build_manifest()
        arms, purge = m["arms"], m["purge"]["windows"]
        for a in arms.values():
            for k in ("from_utc", "to_utc"):
                ny = pd.Timestamp(a[k]).tz_convert(build_v2.NEW_YORK)
                self.assertEqual((ny.hour, ny.minute), (17, 0))
        self.assertEqual(purge[0]["from_utc"], arms["TRAIN"]["to_utc"])
        self.assertEqual(purge[0]["to_utc"], arms["DEV"]["from_utc"])
        self.assertEqual(purge[1]["from_utc"], arms["DEV"]["to_utc"])
        self.assertEqual(purge[1]["to_utc"], arms["FINAL_OOS"]["from_utc"])
        self.assertEqual([p["trading_day"] for p in purge], ["2017-01-02", "2025-09-02"])
        self.assertEqual(m["oos_authorisation_token"], "OOS-AUTHORISATION-NOT-ISSUED")
        self.assertTrue(m["FINAL_OOS_LOCKED"])

    def test_final_oos_is_locked_before_any_read(self):
        missing = Path(tempfile.gettempdir()) / "no-such-bars-dir"
        for token in (None, "", "wrong"):
            with self.assertRaises(OOSLockedError):
                store.load_v2("H1", "FINAL_OOS", token, bars_dir=missing)

    def _write(self, d, h1):
        h1.to_parquet(d / "XAUUSD_H1.parquet", index=False)
        fp = d / "fp.json"
        fp.write_text(json.dumps({"frames": {"H1": {"values_sha256": _fingerprint(h1[COLUMNS])}}}))
        return fp

    def test_arm_membership_purge_and_fingerprint(self):
        h1 = resample(random_m1("2016-12-30 19:00", "2017-01-03 00:00", drop=0), "H1")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            fp = self._write(d, h1)
            train = store.load_v2("H1", "TRAIN", bars_dir=d, fingerprints=fp)
            dev = store.load_v2("H1", "DEV", bars_dir=d, fingerprints=fp)
            self.assertEqual(train.time.max(), ts("2016-12-30 21:00"))   # ends 22:00 = 17:00 EST
            self.assertEqual(dev.time.min(), ts("2017-01-02 22:00"))     # purge day skipped
            self.assertEqual(len(train) + len(dev),
                             len(h1) - len(h1[(h1.time >= ts("2016-12-30 22:00"))
                                              & (h1.time < ts("2017-01-02 22:00"))]))
            fp.write_text(json.dumps({"frames": {"H1": {"values_sha256": "0" * 64}}}))
            with self.assertRaises(DatasetIntegrityError):
                store.load_v2("H1", "TRAIN", bars_dir=d, fingerprints=fp)
            with self.assertRaises(DatasetIntegrityError):
                store.load_v2("H1", "TRAIN", bars_dir=d, fingerprints=d / "absent.json")


def bi5(records):
    raw = np.array(records, dtype=ticks.RECORD).tobytes()
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


DAY = dt.date(2024, 1, 2)
RECS = [  # ms offset, ask, bid (points), ask vol, bid vol
    (1_000, 2_064_300, 2_064_000, 1.0, 2.0),
    (20_000, 2_064_900, 2_064_500, 1.0, 1.0),
    (59_999, 2_063_800, 2_063_500, 1.0, 1.0),
    (60_000, 2_065_000, 2_064_700, 1.0, 1.0),
    (185_000, 2_066_000, 2_065_600, 1.0, 1.0),     # minute 00:02 is empty
]


class TestTicks(unittest.TestCase):
    def test_decode(self):
        df = ticks.decode_bi5(bi5(RECS), DAY)
        self.assertEqual(df["time"].iloc[0], ts("2024-01-02 00:00:01"))
        self.assertEqual(df["time"].iloc[-1], ts("2024-01-02 00:03:05"))
        self.assertAlmostEqual(df["ask"].iloc[0], 2064.3)
        self.assertAlmostEqual(df["bid"].iloc[0], 2064.0)
        self.assertEqual(len(ticks.decode_bi5(b"", DAY)), 0)

    def test_corrupt_files_raise(self):
        with self.assertRaises(ValueError):
            ticks.decode_bi5(b"not lzma at all", DAY)
        with self.assertRaises(ValueError):
            ticks.decode_bi5(lzma.compress(b"x" * 21, format=lzma.FORMAT_ALONE), DAY)

    def test_m1_candles_from_ticks(self):
        bid, ask = ticks.ticks_to_m1(ticks.decode_bi5(bi5(RECS), DAY))
        self.assertEqual(list(bid.time), [ts("2024-01-02 00:00"), ts("2024-01-02 00:01"),
                                          ts("2024-01-02 00:03")])
        self.assertEqual(list(bid.iloc[0][["open", "high", "low", "close"]]),
                         [2064.0, 2064.5, 2063.5, 2063.5])
        self.assertEqual(list(ask.iloc[0][["open", "high", "low", "close"]]),
                         [2064.3, 2064.9, 2063.8, 2063.8])
        self.assertEqual(list(bid.volume), [3, 1, 1])
        m1 = build_m1(bid, ask)[0]
        self.assertAlmostEqual(m1["spread_c"].iloc[0], 2063.8 - 2063.5)
        validate_frame(m1, "M1")

    def test_truncation(self):
        tk = ticks.decode_bi5(bi5(RECS), DAY)
        cut = ts("2024-01-02 00:01")
        full_bid, full_ask = ticks.ticks_to_m1(tk)
        pre_bid, pre_ask = ticks.ticks_to_m1(tk[tk.time < cut])
        pd.testing.assert_frame_equal(pre_bid, full_bid[full_bid.time < cut])
        pd.testing.assert_frame_equal(pre_ask, full_ask[full_ask.time < cut])


class TestS3Download(unittest.TestCase):
    def setUp(self):
        import boto3
        from botocore.stub import Stubber
        self.client = boto3.client("s3", region_name=s3.REGION, aws_access_key_id="testing",
                                   aws_secret_access_key="testing")
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.stub.deactivate()
        self.tmp.cleanup()

    def _ok(self, day, body):
        from botocore.response import StreamingBody
        self.stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(body), len(body))},
                               {"Bucket": s3.BUCKET, "Key": s3.s3_key(day),
                                "RequestPayer": "requester"})

    def test_keys_use_zero_based_month(self):
        self.assertEqual(s3.s3_key(dt.date(2024, 1, 5)), "XAUUSD/2024/00/05_ticks.bi5")
        self.assertEqual(s3.s3_key(dt.date(2003, 12, 31)), "XAUUSD/2003/11/31_ticks.bi5")
        for day in (dt.date(2024, 1, 5), dt.date(2003, 12, 31)):
            self.assertEqual(s3.day_from_path(self.root / s3.s3_key(day)), day)

    def test_download_writes_mirror_with_requester_pays(self):
        self._ok(DAY, bi5(RECS))
        self.assertEqual(s3.fetch_day(self.client, self.root, DAY), ("done", len(RECS)))
        self.assertEqual((self.root / s3.s3_key(DAY)).read_bytes(), bi5(RECS))
        self.assertEqual(list((self.root / "_tmp").iterdir()), [])
        self.stub.assert_no_pending_responses()

    def test_missing_key_is_absent(self):
        self.stub.add_client_error("get_object", service_error_code="NoSuchKey",
                                   http_status_code=404)
        self.assertEqual(s3.fetch_day(self.client, self.root, DAY), ("absent", 0))
        self.assertFalse((self.root / s3.s3_key(DAY)).exists())

    def test_existing_files_are_never_requested_or_overwritten(self):
        good = self.root / s3.s3_key(DAY)
        good.parent.mkdir(parents=True)
        good.write_bytes(bi5(RECS))
        self.assertEqual(s3.fetch_day(self.client, self.root, DAY), ("present", len(RECS)))
        bad_day = dt.date(2024, 1, 3)
        bad = self.root / s3.s3_key(bad_day)
        bad.write_bytes(b"garbage")
        with self.assertRaises(s3.RawFileExistsError):
            s3.fetch_day(self.client, self.root, bad_day)
        self.assertEqual(bad.read_bytes(), b"garbage")
        self.stub.assert_no_pending_responses()           # no S3 call was made

    def test_failed_day_is_logged_and_the_run_continues(self):
        bad, good = dt.date(2024, 1, 2), dt.date(2024, 1, 3)
        for _ in range(s3.ATTEMPTS):
            self._ok(bad, b"corrupt")
        self._ok(good, bi5(RECS))
        with self.assertLogs(s3.log, level="WARNING"):
            summary = s3.run(self.client, self.root, bad, good, sleep=lambda s: None)
        self.assertEqual(summary["done"], 1)
        self.assertEqual([d for d, _ in summary["failed"]], ["2024-01-02"])
        self.assertFalse((self.root / s3.s3_key(bad)).exists())
        self.assertTrue((self.root / s3.s3_key(good)).exists())

    def test_dry_run_makes_no_call(self):
        plan = s3.dry_run(self.root, dt.date(2024, 1, 1), dt.date(2024, 1, 31))
        self.assertEqual((plan["days_in_range"], plan["to_request"]), (31, 31))
        self.assertEqual(plan["first_keys"][0], "XAUUSD/2024/00/01_ticks.bi5")
        self.stub.assert_no_pending_responses()

    def test_load_tick_candles_from_mirror(self):
        p = self.root / s3.s3_key(DAY)
        p.parent.mkdir(parents=True)
        p.write_bytes(bi5(RECS))
        bid, ask = s3.load_tick_candles(self.root)
        self.assertEqual(len(bid), 3)
        self.assertEqual(bid.time.iloc[0], ts("2024-01-02 00:00"))


class TestCliSource(unittest.TestCase):
    def test_read_cli_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.csv"
            p.write_text("timestamp,open,high,low,close,volume\n"
                         "1704153660000,2.0,3.0,1.0,2.5,7\n1704153600000,1.0,2.0,0.5,1.5,6\n")
            df = read_cli_csv([p])
        self.assertEqual(list(df.columns), ["time", "open", "high", "low", "close", "volume"])
        self.assertEqual(list(df.time), [ts("2024-01-02 00:00"), ts("2024-01-02 00:01")])

    def test_cli_month_ranges_and_refusal(self):
        r = download_dukascopy.month_ranges(dt.date(2003, 5, 5), dt.date(2003, 7, 1))
        self.assertEqual([(y, m, lo.day, hi.day) for y, m, lo, hi in r],
                         [(2003, 5, 5, 31), (2003, 6, 1, 30), (2003, 7, 1, 1)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = download_dukascopy.raw_path(root, "bid", 2003, 5)
            p.parent.mkdir(parents=True)
            p.write_text("garbage\n")
            with self.assertRaises(download_dukascopy.RawFileExistsError):
                download_dukascopy.download_month(root, "bid", 2003, 5, dt.date(2003, 5, 5),
                                                  dt.date(2003, 5, 31))
            self.assertEqual(p.read_text(), "garbage\n")


if __name__ == "__main__":
    unittest.main()
