"""Downloader behaviour with a fake transport: write-once, resumable, rate-limited, no network."""
import gzip
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from psx.data import download as d


class FakeClock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def closing_file(day: date, symbols) -> bytes:
    tag = day.strftime("%d%b%Y").upper()
    return gzip.compress("\n".join(f"{tag}|{s}|0801|{s} Ltd|10|11|9|10.5|1000|10|||" for s in symbols).encode())


class FakePSX:
    """Serves a symbol list, one payouts page, closing files (404 on 2013-01-02) and histories."""
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, data))
        if path == "/symbols":
            return 200, json.dumps([{"symbol": "AAA"}, {"symbol": "BBB"}]).encode()
        if path == "/payouts":
            return 200, b"<table><tr><th>Symbol</th></tr></table>Showing 1 to 1 of 1 entries"
        if path.startswith("/download/mkt_summary/"):
            day = date.fromisoformat(path.rsplit("/", 1)[1][:-2])
            if day == date(2013, 1, 2):
                return 404, b"not found"
            return 200, closing_file(day, ["AAA", "OLD", "OLD-OCT"])
        if path == "/historical":
            return 200, f"<table><tr><th>DATE</th></tr>{data['symbol']}</table>".encode()
        if path.startswith("/company/"):
            return 200, b"<div class='quote__name'>X<div class='tag'>DELISTED</div></div>"
        return 404, b""


class TestDownloader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.raw, self.log = root / "raw", root / "logs" / "log.csv"
        self.clock = FakeClock()

    def tearDown(self):
        self.tmp.cleanup()

    def downloader(self, send):
        return d.Downloader(send, self.raw, self.log, gap_s=1.5, clock=self.clock, sleep=self.clock.sleep,
                            backoff_s=30)

    def test_save_once_refuses_to_overwrite(self):
        p = self.raw / "a.bin"
        d.save_once(p, b"one")
        with self.assertRaises(FileExistsError):
            d.save_once(p, b"two")
        self.assertEqual(p.read_bytes(), b"one")

    def test_requests_are_spaced_and_existing_files_skipped(self):
        fake = FakePSX()
        dl = self.downloader(fake)
        self.assertEqual(dl.fetch("x/a.html", "POST", "/historical", {"symbol": "A"}), "ok")
        self.assertEqual(dl.fetch("x/b.html", "POST", "/historical", {"symbol": "B"}), "ok")
        self.assertEqual(self.clock.slept, [1.5])                       # second request waited the full gap
        self.assertEqual(dl.fetch("x/a.html", "POST", "/historical", {"symbol": "A"}), "exists")
        self.assertEqual(len(fake.calls), 2)

    def test_404_is_logged_and_not_requested_again_after_restart(self):
        fake = FakePSX()
        self.assertEqual(self.downloader(fake).fetch("m/2013-01-02.Z", "GET", "/download/mkt_summary/2013-01-02.Z"), "404")
        again = self.downloader(fake)                                    # a new process reads the log
        self.assertEqual(again.fetch("m/2013-01-02.Z", "GET", "/download/mkt_summary/2013-01-02.Z"), "missing")
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse((self.raw / "m/2013-01-02.Z").exists())

    def test_error_body_with_status_200_is_not_stored_and_retried_later(self):
        replies = iter([(200, b"error"), (200, b"<table><tr><td>x</td></tr></table>")])
        dl = self.downloader(lambda m, p, data=None: next(replies))
        self.assertEqual(dl.fetch("historical/s/ENGRO.html", "POST", "/historical", {"symbol": "ENGRO"}), "invalid")
        self.assertFalse((self.raw / "historical/s/ENGRO.html").exists())
        again = self.downloader(lambda m, p, data=None: next(replies))   # a rerun asks again
        self.assertEqual(again.fetch("historical/s/ENGRO.html", "POST", "/historical", {"symbol": "ENGRO"}), "ok")

    def test_server_errors_back_off_and_are_not_stored(self):
        replies = iter([(503, b""), (429, b""), (200, b"body")])
        dl = self.downloader(lambda m, p, data=None: next(replies))
        self.assertEqual(dl.fetch("x/c.html", "GET", "/x"), "ok")
        self.assertIn(30, self.clock.slept)
        self.assertIn(60, self.clock.slept)
        failing = self.downloader(lambda m, p, data=None: (500, b""))
        self.assertEqual(failing.fetch("x/d.html", "GET", "/x"), "error")
        self.assertFalse((self.raw / "x/d.html").exists())

    def test_run_downloads_listed_index_and_unlisted_symbols_and_resumes(self):
        fake = FakePSX()
        with mock.patch.object(d, "FIRST_DAY", date(2013, 1, 1)), mock.patch.object(d, "KNOWN_DELISTED", ("OLD",)):
            res = d.run(self.downloader(fake), date(2013, 1, 4), progress=lambda m: None)
            hist = sorted(p.stem for p in (self.raw / "historical" / "2013-01-04").glob("*.html"))
            self.assertEqual(hist, ["AAA", "BBB", "KSE100", "OLD"])     # futures name OLD-OCT excluded
            self.assertEqual(res["results"]["mkt_summary"], {"ok": 2, "404": 1})
            n = len(fake.calls)
            again = d.run(self.downloader(fake), date(2013, 1, 4), progress=lambda m: None)
            self.assertEqual(len(fake.calls), n)                         # nothing fetched twice
            self.assertEqual(again["results"]["mkt_summary"], {"exists": 2, "missing": 1})

    def test_fingerprints_change_when_a_file_changes(self):
        d.save_once(self.raw / "a.bin", b"one")
        before = d.fingerprints(self.raw)
        (self.raw / "a.bin").write_bytes(b"onf")
        self.assertNotEqual(before["all_files_sha256"], d.fingerprints(self.raw)["all_files_sha256"])
        out = Path(self.tmp.name) / "fp.json"
        d.write_fingerprints(before, out)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), before)


if __name__ == "__main__":
    unittest.main()
