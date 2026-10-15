"""Audit functions on synthetic closing rows; truncation tests for every data function."""
import unittest

import numpy as np
import pandas as pd

from psx.data import audit as a


def rows(spec):
    """spec: (symbol, day, close, ldcp, volume[, flag]) -> closing-file rows."""
    out = []
    for s in spec:
        sym, day, close, ldcp, vol = s[:5]
        flag = s[5] if len(s) > 5 else ""
        out.append({"date": pd.Timestamp(day), "symbol": sym, "sector_code": "0801", "name": sym,
                    "open": close, "high": close, "low": close, "close": float(close), "volume": float(vol),
                    "ldcp": float(ldcp), "xd": flag == "XD", "xb": flag == "XB", "xr": flag == "XR"})
    return pd.DataFrame(out)


CLOSING = rows([
    ("AAA", "2020-01-01", 100, 99, 10), ("AAA", "2020-01-02", 102, 100, 10),
    ("AAA", "2020-01-03", 98, 97, 10, "XD"),                 # Rs 5 dividend: LDCP 102 -> 97
    ("AAA", "2020-01-06", 99, 98, 10), ("AAA", "2020-01-07", 49.5, 49.5, 10, "XB"),   # 100 % bonus
    ("BBB", "2020-01-02", 5, 5, 10), ("BBB", "2020-01-03", 6, 5, 10), ("BBB", "2020-01-06", 6, 6, 0),
])


class TestLoadClosing(unittest.TestCase):
    def test_holiday_file_carrying_the_next_day_is_reported_and_deduplicated(self):
        import gzip, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            (raw / "mkt_summary").mkdir()
            line = "{}|AAA|0801|AAA Ltd|10|11|9|{}|1000|10|||"
            (raw / "mkt_summary" / "2016-12-12.Z").write_bytes(gzip.compress(line.format("13DEC2016", 10.5).encode()))
            (raw / "mkt_summary" / "2016-12-13.Z").write_bytes(gzip.compress(line.format("13DEC2016", 10.6).encode()))
            (raw / "mkt_summary" / "2016-12-14.Z").write_bytes(gzip.compress(line.format("14DEC2016", 10.7).encode()))
            df, info = a.load_closing(raw)
        self.assertEqual(list(df["date"].dt.day), [13, 14])
        self.assertEqual(df["close"].iloc[0], 10.6)                       # the correctly named file wins
        self.assertEqual(info["mislabelled_files"], [{"file": "2016-12-12.Z", "line_dates": ["2016-12-13"], "rows": 1}])
        self.assertEqual(info["duplicate_rows_within_correct_files"], 0)


class TestAdjusted(unittest.TestCase):
    def test_ex_dates_are_taken_out_of_the_chain(self):
        adj = a.adjusted(CLOSING).set_index(["symbol", "date"])
        A = adj.loc["AAA"]
        self.assertAlmostEqual(A.loc["2020-01-03", "adj_close"], 102 * 98 / 97)
        self.assertAlmostEqual(A.loc["2020-01-07", "adj_close"], 102 * 98 / 97 * 99 / 98 * 49.5 / 49.5)
        self.assertEqual(list(A["ref_adjusted"]), [False, False, True, False, True])
        self.assertAlmostEqual(A.loc["2020-01-03", "adj_factor"], 97 / 102)
        self.assertEqual(adj.loc[("BBB", pd.Timestamp("2020-01-06")), "adj_close"], 6.0)   # official close, no trade
        self.assertEqual(list(A["ref_reason"]), ["", "", "ex_flag", "", "ex_flag"])

    def test_unflagged_split_versus_relisting_after_a_long_gap(self):
        df = rows([("DDD", "2020-01-01", 100, 100, 10), ("DDD", "2020-01-02", 10.5, 10, 10),     # 10:1 split, no flag
                   ("EEE", "2020-01-01", 100, 100, 10), ("EEE", "2020-06-01", 50, 50, 10)])      # back after 5 months
        adj = a.adjusted(df, 0.10).set_index("symbol")
        self.assertAlmostEqual(adj.loc["DDD", "adj_close"].iloc[1], 105.0)
        self.assertEqual(adj.loc["DDD", "ref_reason"].iloc[1], "beyond_limit")
        self.assertAlmostEqual(adj.loc["EEE", "adj_close"].iloc[1], 50.0)     # a move the limit allows: kept

    def test_unflagged_ldcp_change_is_not_applied(self):
        # 01-02's closing file missing: LDCP on 01-03 is 01-02's close (105), not 01-01's (100)
        df = rows([("CCC", "2020-01-01", 100, 100, 10), ("CCC", "2020-01-03", 106, 105, 10)])
        adj = a.adjusted(df)
        self.assertAlmostEqual(adj["adj_close"].iloc[1], 106.0)            # chained on the last close
        self.assertEqual((bool(adj["ldcp_mismatch_unflagged"].iloc[1]), bool(adj["ref_adjusted"].iloc[1])),
                         (True, False))

    def test_truncation_never_changes_past_values(self):
        full = a.adjusted(CLOSING)
        for cut in CLOSING["date"].unique():
            part = a.adjusted(CLOSING[CLOSING["date"] <= cut])
            ref = full[full["date"] <= cut].reset_index(drop=True)
            pd.testing.assert_frame_equal(part.reset_index(drop=True), ref)


class TestLimits(unittest.TestCase):
    HIST = pd.DataFrame({"symbol": ["P"] * 4 + ["Q"] * 3,
                         "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"] * 1
                                                + ["2020-01-01", "2020-01-02", "2020-01-03"]),
                         "close": [100, 110, 125, 120, 5, 6, 7.2]})

    def test_band_with_rupee_floor(self):
        br = a.breaches(self.HIST, 0.10)
        got = list(zip(br["symbol"], br["date"].dt.strftime("%m-%d")))
        self.assertEqual(got, [("P", "01-03"), ("Q", "01-03")])   # 110->125 > 10 %; 6->7.2 > Rs 1; 5->6 = Rs 1 ok

    def test_breaches_truncation(self):
        full = a.breaches(self.HIST, 0.10)
        for cut in self.HIST["date"].unique():
            part = a.breaches(self.HIST[self.HIST["date"] <= cut], 0.10)
            pd.testing.assert_frame_equal(part, full[full["date"] <= cut].reset_index(drop=True))

    def test_day_limits_cover_the_largest_move_and_hold_through_quiet_days(self):
        days = pd.DatetimeIndex(pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]))
        m = pd.DataFrame({"date": days[[0, 0, 1, 3, 3, 4, 4]], "ldcp": [100.0, 100, 100, 100, 5, 100, 100],
                          "move": [0.05, -0.03, 0.02, 0.10, 0.4, 0.05, 0.01]})
        lim = a.observed_limits(m, days, window=2)
        self.assertEqual(list(lim), [0.05, 0.05, 0.05, 0.10, 0.10])   # quiet days keep 5 %; LDCP 5 ignored
        self.assertEqual(list(a.observed_limits(m, days, window=1)), [0.05, 0.05, 0.05, 0.10, 0.05])
        for cut in days:                                             # truncation
            part = a.observed_limits(m[m["date"] <= cut], days[days <= cut], window=2)
            pd.testing.assert_series_equal(part, lim[lim.index <= cut])
        hist = pd.DataFrame({"symbol": ["P"] * 3, "date": days[[0, 1, 3]], "close": [100.0, 107.0, 115.0]})
        br = a.breaches(hist, lim)
        self.assertEqual(list(br["date"]), [days[1]])               # 7 % beyond 5 %; 7.5 % within 10 %

    def test_rs1_floor_check(self):
        lim = pd.Series([0.10], index=pd.to_datetime(["2020-01-01"]))
        m = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"] * 3), "ldcp": [5.0, 5.0, 50.0],
                          "close": [6.0, 5.2, 55.0]})
        self.assertEqual(a.floor_check(m, lim), {"rows_with_pct_band_under_rs1": 2, "moved_more_than_pct": 1,
                                                 "max_move_rs": 1.0, "moved_more_than_rs1": 0})

    def test_limit_table_counts_locks(self):
        m = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"] * 4), "ldcp": [100.0] * 4,
                          "move": [0.10, -0.10, 0.02, 0.12]})
        t = a.limit_table(m)[2020]
        self.assertEqual((t["at_0.1"], t["beyond_0.1"], t["beyond_0.05"]), (2, 1, 3))

    def test_classify(self):
        days = pd.DatetimeIndex(sorted(CLOSING["date"].unique()))
        adj = a.adjusted(CLOSING)
        br = pd.DataFrame({"symbol": ["AAA", "AAA", "BBB", "ZZZ", "BBB", "BBB", "BBB"],
                           "date": pd.to_datetime(["2020-01-03", "2020-01-06", "2020-01-02", "2020-01-02", "2020-01-03",
                                                   "2020-01-03", "2020-01-06"]),
                           "prev_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-01", "2020-01-01", "2020-01-02",
                                                        "2020-01-02", "2020-01-02"]),
                           "prev_close": [102.0, 98.0, 4.0, 1.0, 5.0, 4.0, 6.0],
                           "close": [98.0, 99.0, 5.0, 1.0, 9.0, 6.0, 6.0],
                           "gap": [1, 1, 1, 1, 1, 1, 2]})
        payouts = pd.DataFrame({"symbol": ["ZZZ"], "bc_from": [pd.Timestamp("2020-01-08")]})
        got = list(a.classify(br, adj, payouts, days))
        self.assertEqual(got, ["exchange_adjusted", "ex_flag_nearby", "unexplained", "payout_window",
                               "source_mismatch", "history_prev_differs", "after_gap"])


class TestPayoutCheck(unittest.TestCase):
    def test_pct_parsing(self):
        self.assertEqual(a.payout_pct("30%(i) (D)  -  50% (B)", "D"), 30.0)
        self.assertEqual(a.payout_pct("30%(i) (D)  -  50% (B)", "B"), 50.0)
        self.assertEqual(a.payout_pct("250%(F) (D)", "D"), 250.0)
        self.assertEqual(a.payout_pct("DIVIDEND =25%(F)", "D"), 25.0)
        self.assertIsNone(a.payout_pct("40% (R)", "B"))

    def test_sizes_against_ldcp(self):
        adj = a.adjusted(CLOSING)                                  # AAA: Rs 5 dividend 01-03, 100 % bonus 01-07
        payouts = pd.DataFrame({"symbol": ["AAA", "AAA", "AAA"], "details": ["50%(F) (D)", "100% (B)", "40%(F) (D)"],
                                "bc_from": pd.to_datetime(["2020-01-06", "2020-01-08", "2020-03-01"]),
                                "dividend": [True, False, True], "bonus": [False, True, False]})
        res = a.payout_check(adj, payouts)
        self.assertEqual(res["dividend"], {"n": 2, "ex_day_found": 1, "size_matches": 1})
        self.assertEqual(res["bonus"], {"n": 1, "ex_day_found": 1, "size_matches": 1})


class TestUniverseAndLiquidity(unittest.TestCase):
    def test_liquidity_needs_price_and_median_value_over_all_days(self):
        days = pd.bdate_range("2020-01-01", "2020-01-10")                 # 8 trading days
        spec = [("LIQ", d, 20, 20, 300_000) for d in days]               # Rs 6 m every day
        spec += [("THIN", d, 20, 20, 1_000_000) for d in days[:3]]       # Rs 20 m on 3 of 8 days: median 0
        spec += [("PENNY", d, 5, 5, 2_000_000) for d in days]            # Rs 10 m a day but price < Rs 10
        res = a.liquidity_by_year(rows(spec), days)
        self.assertEqual(res[2020], {"trading_days": 8, "traded_symbols": 3, "liquid": 1})

    def test_liquidity_truncation(self):
        days = pd.bdate_range("2020-12-28", "2021-01-08")
        df = rows([("LIQ", d, 20, 20, 300_000 if d.year == 2020 else 1) for d in days])
        full = a.liquidity_by_year(df, days)
        cut = a.liquidity_by_year(df[df["date"] <= "2020-12-31"], days[days <= "2020-12-31"])
        self.assertEqual(cut[2020], full[2020])

    def test_equity_mask(self):
        df = rows([("AAA", "2020-01-01", 1, 1, 1), ("AAA-JAN", "2020-01-01", 1, 1, 1),
                   ("TFC1", "2020-01-01", 1, 1, 1), ("PREFX", "2020-01-01", 1, 1, 1),
                   ("AAAR1", "2020-01-01", 1, 1, 1), ("AAAPS", "2020-01-01", 1, 1, 1),
                   ("CML", "2020-01-01", 1, 1, 1), ("PAKR", "2020-01-01", 1, 1, 1)])
        df.loc[3, "name"] = "Some Co.(Pref)"
        df.loc[6, "name"] = "Colony Mills SPOT"                       # an ordinary stock in the spot segment
        listed = pd.DataFrame({"symbol": ["AAA", "TFC1"], "sectorName": ["CEMENT", "BILLS AND BONDS"],
                               "isDebt": [np.nan, True]})
        self.assertEqual(list(a.equity_mask(df, listed)), [True, False, False, False, False, False, True, True])

    def test_possible_renames(self):
        df = rows([("OLD", "2020-01-01", 50, 50, 1), ("OLD", "2020-01-02", 51, 50, 1),
                   ("NEW", "2020-01-03", 52, 51, 1), ("OTHER", "2020-01-01", 9, 9, 1), ("OTHER", "2020-01-03", 9, 9, 1)])
        days = pd.DatetimeIndex(sorted(df["date"].unique()))
        self.assertEqual(a.possible_renames(a.adjusted(df), days), [("OLD", "NEW", "2020-01-03")])

    def test_per_year_counts(self):
        c = a.per_year_counts(CLOSING)
        self.assertEqual((c[2000], c[2020], c[2026]), (0, 2, 0))


if __name__ == "__main__":
    unittest.main()
