"""Parsers on synthetic raw files shaped like dps.psx.com.pk responses."""
import gzip
import io
import math
import unittest
import zipfile
from datetime import date

import pandas as pd

from psx.data import parse as p


class TestParse(unittest.TestCase):
    def test_ex_flags(self):
        self.assertEqual(p.ex_flags("Golden ArrowXD"), ("Golden Arrow", True, False, False))
        self.assertEqual(p.ex_flags("Fecto Cement XB"), ("Fecto Cement", False, True, False))
        self.assertEqual(p.ex_flags("Pak ElektronXDXR"), ("Pak Elektron", True, False, True))
        self.assertEqual(p.ex_flags("Pak Synthetics"), ("Pak Synthetics", False, False, False))

    def test_closing_file(self):
        raw = gzip.compress(b"17OCT2016|OGDC|0820|Oil & Gas Dev.XD|143.5|146|143|145.9|1000|143.14|||\n"
                            b"17OCT2016|TRG-CDEC|40|TRG-CDEC|0|45.94|0|45.94|0|48.15|||\n"
                            b"17OCT2016|BAHL|8350|Bank AL-Habib||48.73|48.1|48.46|147500|48.55|||\n")
        df = p.parse_mkt_summary(raw, date(2016, 10, 17))
        self.assertEqual(list(df.columns), p.MKT_COLUMNS)
        r = df.iloc[0]
        self.assertEqual((r["symbol"], r["name"], bool(r["xd"])), ("OGDC", "Oil & Gas Dev.", True))
        self.assertEqual((r["close"], r["volume"], r["ldcp"]), (145.9, 1000.0, 143.14))
        self.assertEqual(df["date"].iloc[0], pd.Timestamp("2016-10-17"))
        self.assertTrue(math.isnan(df["open"].iloc[2]))                     # empty field -> NaN
        self.assertEqual(df["close"].iloc[2], 48.46)
        with self.assertRaises(ValueError):
            p.parse_mkt_summary(raw, date(2016, 10, 18))
        buf = io.BytesIO()                                                   # zip format (mixed with gzip from 2018)
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("closing11.lis", gzip.decompress(raw))
        pd.testing.assert_frame_equal(p.parse_mkt_summary(buf.getvalue()), df)
        buf = io.BytesIO()                                                   # 2023-05-17 layout: inside a folder
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("20230517_new.lis/", b"")
            z.writestr("20230517_new.lis/closing11.lis", gzip.decompress(raw))
        pd.testing.assert_frame_equal(p.parse_mkt_summary(buf.getvalue()), df)
        with self.assertRaises(ValueError):                                  # unknown format: never zero rows silently
            p.parse_mkt_summary(b"\x00\x01garbage")
        self.assertEqual(p.parse_mkt_summary(gzip.compress(b""))["close"].dtype, float)

    def test_historical_table_is_ascending_and_numeric(self):
        html = ("<table><tr><th>DATE</th><th>OPEN</th><th>HIGH</th><th>LOW</th><th>CLOSE</th><th>VOLUME</th></tr>"
                "<tr><td>Jan 3, 2025</td><td>1,481.99</td><td>1,496.00</td><td>474.01</td><td>485.38</td><td>4,496,408</td></tr>"
                "<tr><td>Jan 2, 2025</td><td>452.00</td><td>484.00</td><td>451.51</td><td>478.30</td><td>3,602,326</td></tr></table>")
        df = p.parse_historical(html)
        self.assertEqual(list(df["date"]), [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")])
        self.assertEqual(df["open"].iloc[1], 1481.99)
        self.assertEqual(df["volume"].iloc[0], 3602326.0)
        self.assertTrue(p.parse_historical("<div>no table</div>").empty)

    def test_payouts_page(self):
        html = ("<table><tr><th>Symbol</th></tr>"
                "<tr><td>LUCK</td><td>Lucky Cement</td><td>CEMENT</td><td>250%(F) (D)</td>"
                "<td>August 10, 2026 4:15 PM</td><td>18/09/2026  - 25/09/2026</td></tr>"
                "<tr><td>XYZ</td><td>X Co</td><td>TEXTILE</td><td>10% (B)</td>"
                "<td>June 1, 2025 1:05 PM</td><td>01/07/2025  - 07/07/2025</td></tr>"
                "<tr><td>ABC</td><td>A Co</td><td>BANK</td><td>DIVIDEND =25%(F)</td>"
                "<td>June 2, 2025 1:05 PM</td><td></td></tr></table>"
                "Showing  1 to 2 of 723 entries")
        df = p.parse_payouts(html)
        self.assertEqual(list(df["symbol"]), ["LUCK", "XYZ", "ABC"])
        self.assertEqual(list(df["dividend"]), [True, False, True])
        self.assertTrue(pd.isna(df["bc_from"].iloc[2]))
        self.assertEqual(df["bc_from"].iloc[0], pd.Timestamp("2026-09-18"))
        self.assertEqual(df["bc_to"].iloc[1], pd.Timestamp("2025-07-07"))
        self.assertEqual(df["announced"].iloc[0], pd.Timestamp("2026-08-10 16:15"))
        self.assertEqual((bool(df["dividend"].iloc[0]), bool(df["bonus"].iloc[1])), (True, True))
        self.assertEqual(p.payouts_total(html), 723)

    def test_company_badge_ignores_navigation_text(self):
        html = ("<nav>Suspended companies DELISTED list</nav><div class='quote__name'>Engro Corporation"
                "<div class='tag tag--del'>DELISTED</div></div>")
        self.assertEqual(p.company_status(html), "DELISTED")
        self.assertIsNone(p.company_status("<nav>DELISTED</nav><div class='quote__name'>Lucky</div>"))


if __name__ == "__main__":
    unittest.main()
