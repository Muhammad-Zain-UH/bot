"""Download Dukascopy XAUUSD daily tick files from the official S3 export.

    venv\\Scripts\\python.exe -m gold.data.download_dukascopy_s3 --dry-run
    venv\\Scripts\\python.exe -m gold.data.download_dukascopy_s3

Bucket cfg-public-proper-wallaby (eu-west-1) is Requester Pays: every request
carries RequestPayer='requester' and is billed to the caller's AWS account.
Keys are SYMBOL/YEAR/MONTH/DD_ticks.bi5 with a 0-based month. Each file is
mirrored to data/dukascopy_v1/raw_s3/<key>.

Raw files are write-once: a day already on disk that decodes is skipped; one
that does not decode is refused, never overwritten. Each file is written to
_tmp/ and renamed into place only after it decodes. A missing key (NoSuchKey)
means no ticks that day and is recorded as absent. A day that fails after every
retry is logged and the run continues; the summary lists it, a rerun retries it,
and the exit code is 1. --dry-run makes no AWS call: it prints what a run would
request.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from gold.data.ticks import decode_bi5, ticks_to_m1

REPO = Path(__file__).resolve().parents[2]
RAW_S3_ROOT = REPO / "data" / "dukascopy_v1" / "raw_s3"
BUCKET = "cfg-public-proper-wallaby"
REGION = "eu-west-1"
SYMBOL = "XAUUSD"                     # VERIFY ON FIRST LISTING of the bucket
FIRST_DAY = dt.date(2003, 5, 5)
LAST_DAY = dt.date(2026, 10, 1)
ATTEMPTS = 3
BACKOFF_S = (30, 120)                 # pause before attempts 2, 3

log = logging.getLogger("download_dukascopy_s3")


class RawFileExistsError(RuntimeError):
    """An existing raw file does not decode; it is never overwritten."""


class DayFailed(RuntimeError):
    """A day could not be fetched or did not decode after every attempt."""


def s3_key(day: dt.date) -> str:
    return f"{SYMBOL}/{day.year:04d}/{day.month - 1:02d}/{day.day:02d}_ticks.bi5"


def day_from_path(path: Path) -> dt.date:
    """Inverse of s3_key for a local mirror path .../YEAR/MM0/DD_ticks.bi5."""
    return dt.date(int(path.parent.parent.name), int(path.parent.name) + 1,
                   int(path.name.split("_")[0]))


def days(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def fetch_day(client, root: Path, day: dt.date, sleep=time.sleep) -> tuple[str, int]:
    """Return ("present" | "done" | "absent", ticks). Raises RawFileExistsError, DayFailed."""
    from botocore.exceptions import BotoCoreError, ClientError
    final = root / s3_key(day)
    if final.exists():
        try:
            return "present", len(decode_bi5(final.read_bytes(), day))
        except ValueError as exc:
            raise RawFileExistsError(f"{final} exists but does not decode ({exc}); raw "
                                     "files are never overwritten -- inspect it by hand") from exc
    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            resp = client.get_object(Bucket=BUCKET, Key=s3_key(day), RequestPayer="requester")
            body = resp["Body"].read()
            n = len(decode_bi5(body, day))
            tmp = root / "_tmp" / f"{s3_key(day).replace('/', '_')}.partial"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(body)
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(final)               # final did not exist; Windows refuses to replace
            return "done", n
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return "absent", 0
            error = f"{exc.response.get('Error', {}).get('Code')}: {exc}"
        except (BotoCoreError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        log.warning("%s attempt %d/%d failed: %s", day, attempt, ATTEMPTS, error)
        if attempt < ATTEMPTS:
            sleep(BACKOFF_S[attempt - 1])
    raise DayFailed(error)


def run(client, root: Path, first: dt.date, last: dt.date, sleep=time.sleep) -> dict:
    """Fetch every day in [first, last]; never stops for one day. Returns the summary."""
    summary = {"done": 0, "present": 0, "absent_weekdays": [], "absent_weekend_days": 0,
               "failed": [], "ticks_per_year": {}}
    for day in days(first, last):
        try:
            status, n = fetch_day(client, root, day, sleep)
        except (DayFailed, RawFileExistsError) as exc:
            summary["failed"].append((day.isoformat(), str(exc)))
            log.error("%s FAILED, continuing: %s", day, exc)
            continue
        if status == "absent":
            if day.weekday() < 5:
                summary["absent_weekdays"].append(day.isoformat())
            else:
                summary["absent_weekend_days"] += 1
            continue
        summary[status] += 1
        summary["ticks_per_year"][day.year] = summary["ticks_per_year"].get(day.year, 0) + n
        if status == "done":
            log.info("%s: %d ticks", day, n)
    return summary


def dry_run(root: Path, first: dt.date, last: dt.date) -> dict:
    """What a run would request; no AWS call."""
    todo = [d for d in days(first, last) if not (root / s3_key(d)).exists()]
    return {"days_in_range": len(days(first, last)), "on_disk": len(days(first, last)) - len(todo),
            "to_request": len(todo), "first_keys": [s3_key(d) for d in todo[:3]],
            "last_key": s3_key(todo[-1]) if todo else None}


def load_tick_candles(root: Path = RAW_S3_ROOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every mirrored day decoded to M1 (bid candles, ask candles)."""
    bids, asks = [], []
    for path in sorted((root / SYMBOL).glob("*/*/*_ticks.bi5"), key=day_from_path):
        b, a = ticks_to_m1(decode_bi5(path.read_bytes(), day_from_path(path)))
        bids.append(b)
        asks.append(a)
    return pd.concat(bids, ignore_index=True), pd.concat(asks, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="first", type=dt.date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--to", dest="last", type=dt.date.fromisoformat, default=LAST_DAY)
    ap.add_argument("--out", type=Path, default=RAW_S3_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        for k, v in dry_run(args.out, args.first, args.last).items():
            print(f"{k}: {v}")
        return 0
    import boto3
    args.out.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(args.out / "download_log.txt", encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    s = run(boto3.client("s3", region_name=REGION), args.out, args.first, args.last)
    log.info("SUMMARY: %d days downloaded now, %d already present, %d absent weekend days, "
             "%d absent weekdays, %d failed", s["done"], s["present"],
             s["absent_weekend_days"], len(s["absent_weekdays"]), len(s["failed"]))
    log.info("  absent weekdays: %s", ", ".join(s["absent_weekdays"]) or "none")
    for day, why in s["failed"]:
        log.info("  FAILED %s: %s", day, why)
    for year, n in sorted(s["ticks_per_year"].items()):
        log.info("  ticks %d: %d", year, n)
    return 1 if s["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
