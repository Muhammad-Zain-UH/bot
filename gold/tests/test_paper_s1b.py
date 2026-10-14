"""S1b paper log on synthetic data: a fake MT5 with no order functions at all."""
import csv
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from gold.live import paper_s1b as p
from gold.tests.test_forward_s1 import BARS, to_server_epoch, utc

UTC = timezone.utc


class ReadOnlyFakeMT5:
    """Bars and ticks only: no order_send, positions_get or any other trading call exists."""
    TIMEFRAME_H1, COPY_TICKS_ALL = 16385, -1

    def __init__(self, bar_opens):
        self.bars = [{"time": to_server_epoch(t)} for t in bar_opens]

    def copy_rates_range(self, sym, tf, a, b):
        return [x for x in self.bars if a.timestamp() <= x["time"] <= b.timestamp()]

    def copy_ticks_range(self, sym, a, b, flags):
        out, t = [], a
        while t <= b:                                 # one tick per minute; spread $10 in the first 5 minutes
            minutes = int((t - a).total_seconds() // 60)
            bid = 4000.0 + 0.1 * minutes
            spread = 10.0 if minutes < 5 else 0.3
            out.append({"time_msc": int(t.timestamp() * 1000), "bid": bid, "ask": bid + spread})
            t += timedelta(minutes=1)
        return out


class TestPaperS1b(unittest.TestCase):
    def test_reopens_labelled_as_s1_across_the_dst_change(self):
        r = p.reopens_by_day(BARS)
        self.assertEqual(r[date(2026, 10, 30)], utc("2026-10-29T22:00:00"))   # 18:00 EDT
        self.assertEqual(r[date(2026, 11, 2)], utc("2026-11-01T23:00:00"))    # Sunday 18:00 EST

    def test_row_arithmetic(self):
        t = utc("2026-10-29T22:00:00")
        first = {"time": t, "bid": 3990.0, "ask": 4004.0}
        at60 = {"time": t + timedelta(minutes=60), "bid": 4000.0, "ask": 4000.4}
        at11 = {"time": utc("2026-10-30T11:00:00"), "bid": 4010.0, "ask": 4010.4}
        row = p.make_row(date(2026, 10, 30), t, first, at60, at11)
        self.assertAlmostEqual(row["r_first_hour"], math.log(4000.2 / 4004.0))
        self.assertAlmostEqual(row["r_rest"], math.log(4010.2 / 4000.2))
        self.assertAlmostEqual(row["r_total"], math.log(4010.2 / 4004.0))
        self.assertAlmostEqual(row["spread_first"], 14.0)

    def test_due_days_skip_weekends_and_written_days(self):
        days = p.due_days({"2026-10-15"}, utc("2026-10-19T12:00:00"))
        self.assertEqual(days, [date(2026, 10, 16), date(2026, 10, 19)])

    def test_step_writes_rows_from_ticks_without_any_order_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s1b.csv"
            logger = p.PaperS1b(ReadOnlyFakeMT5(BARS), out)
            from unittest import mock
            with mock.patch.object(p, "FIRST_DAY", date(2026, 10, 30)), \
                    mock.patch.object(p, "LAST_DAY", date(2026, 11, 2)):
                self.assertEqual(logger.step(utc("2026-11-02T12:00:00")), 2)
                self.assertEqual(logger.step(utc("2026-11-02T12:05:00")), 0)    # nothing written twice
            with out.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([r["trading_day"] for r in rows], ["2026-10-30", "2026-11-02"])
            self.assertAlmostEqual(float(rows[0]["spread_first"]), 10.0)        # first ask paid the wide spread
            self.assertLess(float(rows[0]["r_first_hour"]), 0)


if __name__ == "__main__":
    unittest.main()
