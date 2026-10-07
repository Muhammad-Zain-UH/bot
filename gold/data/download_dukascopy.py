"""Download Dukascopy XAUUSD M1 bid and ask, one calendar month per file.

    venv\\Scripts\\python.exe -m gold.data.download_dukascopy
    venv\\Scripts\\python.exe -m gold.data.download_dukascopy --from 2024-01-01 --to 2024-01-31 --out <dir>

Writes <out>/{bid,ask}/{year}/XAUUSD_m1_{side}_{year}-{mm}.csv (default out:
data/dukascopy_v1/raw). Dates are inclusive UTC days; the CLI's --date-to is
exclusive, so one day is added when calling it.

Raw files are write-once. A month whose file exists and passes the sanity check
is skipped (resumable); a month whose file exists and fails it is refused, never
overwritten -- inspect and delete it by hand. Each month is downloaded into
_tmp/ and renamed into place only after it passes the check, so an interrupted
run never leaves a partial raw file.

A month that still fails after every retry is logged with the tail of the
CLI's output and the run CONTINUES; the summary lists it, and a rerun retries
only missing or failed months. Exit code 1 if any month failed.

The CLI makes one request per day to jetta.dukascopy.com. Days cached by
CloudFront return 200; a cache miss can get HTTP 429 from the origin, and one
such day fails the whole month. The CLI's day cache (--cache, kept in
data/dukascopy_v1/cache, never in raw/) holds every day already fetched, so a
retry or rerun only requests the missing days.

Two CLI settings would drop failed days silently and are never used:
--no-fail-after-retries, and --retries 0 (with zero retries a non-200 response
becomes an empty day and the CLI still exits 0). Flat (zero-volume) candles are
excluded by the CLI default (no --flats flag).
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO / "data" / "dukascopy_v1" / "raw"
CACHE_ROOT = REPO / "data" / "dukascopy_v1" / "cache"
CLI = "dukascopy-node@1.50.0"
INSTRUMENT = "xauusd"
SIDES = ("bid", "ask")
FIRST_DAY = dt.date(2003, 5, 5)
LAST_DAY = dt.date(2026, 10, 1)
MIN_ROWS_PER_WEEKDAY = 100          # sanity floor; 2003 has ~450, a modern weekday ~1,380
# Measured 2026-10-06: 429s hit individual uncached days at any pace and with
# any User-Agent, and can repeat for the same day for 30+ minutes.
CLI_RETRIES = 4                     # must be >= 1: zero retries drops failed days silently
CLI_PACING = ["-bs", "2", "-bp", "1500", "-r", str(CLI_RETRIES), "-rp", "45000"]
PAUSE_BETWEEN_MONTHS_S = 3
ATTEMPTS = 3
BACKOFF_S = (300, 900)              # pause before attempts 2, 3
TAIL_LINES = 20
HEADER = ["timestamp", "open", "high", "low", "close", "volume"]

log = logging.getLogger("download_dukascopy")


class RawFileExistsError(RuntimeError):
    """An existing raw file fails the sanity check; it is never overwritten."""


class ChunkFailed(RuntimeError):
    """The CLI or the sanity check failed for one month; message holds the tail."""


def month_ranges(first: dt.date, last: dt.date) -> list[tuple[int, int, dt.date, dt.date]]:
    """Split [first, last] (inclusive) into calendar-month pieces."""
    out = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        lo = max(first, dt.date(y, m, 1))
        hi = min(last, dt.date(y, m, calendar.monthrange(y, m)[1]))
        out.append((y, m, lo, hi))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def raw_path(root: Path, side: str, year: int, month: int) -> Path:
    return root / side / str(year) / f"XAUUSD_m1_{side}_{year}-{month:02d}.csv"


def weekdays(lo: dt.date, hi: dt.date) -> int:
    return sum(1 for i in range((hi - lo).days + 1)
               if (lo + dt.timedelta(days=i)).weekday() < 5)


def check_file(path: Path, lo: dt.date, hi: dt.date) -> tuple[bool, int, str]:
    """Header, row count floor, and every timestamp inside [lo, hi] UTC."""
    lo_ms = int(dt.datetime(lo.year, lo.month, lo.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    hi_ms = lo_ms + ((hi - lo).days + 1) * 86_400_000
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        if next(reader, None) != HEADER:
            return False, 0, "bad header"
        n, first, last = 0, None, None
        for row in reader:
            ts = int(row[0])
            first = ts if first is None else first
            last = ts
            n += 1
    if n == 0:
        return False, 0, "no rows"
    if first < lo_ms or last >= hi_ms:
        return False, n, "timestamps outside the requested range"
    floor = MIN_ROWS_PER_WEEKDAY * weekdays(lo, hi)
    if n < floor:
        return False, n, f"{n} rows < floor {floor}"
    return True, n, "ok"


def run_cli(side: str, lo: dt.date, hi: dt.date, tmp_dir: Path, name: str,
            cache_dir: Path) -> Path:
    if CLI_RETRIES < 1:
        raise ValueError("CLI_RETRIES must be >= 1; zero retries drops failed days silently")
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx not found; install Node.js >= 18")
    cmd = [npx, "--yes", CLI, "-i", INSTRUMENT,
           "-from", lo.isoformat(), "-to", (hi + dt.timedelta(days=1)).isoformat(),
           "-t", "m1", "-p", side, "-f", "csv", "-v", "-vu", "units",
           *CLI_PACING, "-ch", "-chpath", str(cache_dir),
           "-dir", str(tmp_dir), "-fn", name]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace")
    out = tmp_dir / f"{name}.csv"
    if proc.returncode != 0 or not out.exists():
        tail = "\n".join(proc.stdout.strip().splitlines()[-TAIL_LINES:])
        raise ChunkFailed(f"CLI exit {proc.returncode}:\n{tail}")
    return out


def download_month(root: Path, side: str, y: int, m: int, lo: dt.date, hi: dt.date,
                   cache_dir: Path = CACHE_ROOT, sleep=time.sleep) -> tuple[int, bool]:
    """Return (rows, downloaded_now). Raises RawFileExistsError or ChunkFailed."""
    final = raw_path(root, side, y, m)
    if final.exists():
        ok, n, why = check_file(final, lo, hi)
        if ok:
            return n, False
        raise RawFileExistsError(
            f"{final} exists but fails the sanity check ({why}). Raw files are "
            "never overwritten; inspect it and delete it by hand to re-download.")
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = root / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    name = f"XAUUSD_m1_{side}_{y}-{m:02d}.partial"
    for attempt in range(1, ATTEMPTS + 1):
        (tmp_dir / f"{name}.csv").unlink(missing_ok=True)
        try:
            out = run_cli(side, lo, hi, tmp_dir, name, cache_dir)
            ok, n, why = check_file(out, lo, hi)
            if not ok:
                raise ChunkFailed(f"downloaded file fails the sanity check: {why}")
            out.rename(final)               # never replaces: final did not exist
            return n, True
        except ChunkFailed as exc:
            log.warning("%s %d-%02d attempt %d/%d failed:\n%s", side, y, m,
                        attempt, ATTEMPTS, exc)
            (tmp_dir / f"{name}.csv").unlink(missing_ok=True)
            if attempt == ATTEMPTS:
                raise
            sleep(BACKOFF_S[attempt - 1])
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="first", type=dt.date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--to", dest="last", type=dt.date.fromisoformat, default=LAST_DAY)
    ap.add_argument("--sides", nargs="+", choices=SIDES, default=list(SIDES))
    ap.add_argument("--out", type=Path, default=RAW_ROOT)
    ap.add_argument("--cache", type=Path, default=CACHE_ROOT)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(args.out / "download_log.txt", encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)

    rows: dict[tuple[str, int], int] = {}
    done, skipped, failed = 0, 0, []
    for y, m, lo, hi in month_ranges(args.first, args.last):
        for side in args.sides:
            try:
                n, fresh = download_month(args.out, side, y, m, lo, hi, args.cache)
            except (ChunkFailed, RawFileExistsError) as exc:
                failed.append((side, y, m, str(exc).strip().splitlines()[-1]))
                log.error("%s %d-%02d FAILED, continuing: %s", side, y, m, exc)
                continue
            rows[(side, y)] = rows.get((side, y), 0) + n
            if fresh:
                done += 1
                log.info("%s %d-%02d: %d rows", side, y, m, n)
                time.sleep(PAUSE_BETWEEN_MONTHS_S)
            else:
                skipped += 1

    log.info("SUMMARY: %d months downloaded now, %d already present, %d failed",
             done, skipped, len(failed))
    for side, y, m, why in failed:
        log.info("  FAILED %s %d-%02d: %s", side, y, m, why)
    for side in args.sides:
        for (s, y), n in sorted(rows.items()):
            if s == side:
                log.info("  rows %s %d: %d", side, y, n)
    if failed:
        log.info("Rerun the same command to retry only the failed or missing months.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
