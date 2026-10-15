"""Polite, resumable PSX downloader. Raw files in data/psx/raw/ are write-once.

Source: dps.psx.com.pk (the site psxdata scrapes), with psxdata's X-Req-Id token. One request at a
time, at least MIN_GAP_S seconds apart, with back-off on 429 / 5xx / network errors. A raw file is
never overwritten: a rerun skips every file that exists and every file the server answered 404 for
(data/psx/logs/download_log.csv), so an interrupted run resumes where it stopped.

Order: the symbol list, the payouts listing, one closing file per weekday since FIRST_DAY, then the
full daily history of every listed symbol, KSE100 and every symbol seen in the closing files but no
longer listed, then the company pages of a few known delisted names.

    venv\\Scripts\\python.exe -m psx.data.download --snapshot 2026-10-14
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "psx" / "raw"
LOG = REPO / "data" / "psx" / "logs" / "download_log.csv"
FINGERPRINTS = REPO / "research" / "psx" / "psx_fingerprints.json"
BASE_URL = "https://dps.psx.com.pk"
MIN_GAP_S = 1.5
BACKOFF_S = 30.0
FIRST_DAY = date(2013, 1, 1)          # the server's first closing file is 2013-11-04; earlier dates answer 404
PAYOUT_PAGE = 50
INDEX = "KSE100"
KNOWN_DELISTED = ("ENGRO", "DAWH", "PICT", "BYCO", "ICI", "AGTL", "IGIIL")
LOG_FIELDS = ["utc", "rel", "status", "bytes"]
INVALID = -2                          # logged status of a 200 response whose body is not the expected data

GZIP_MAGIC, ZIP_MAGIC = b"\x1f\x8b", b"PK\x03\x04"
VALID = {                             # a 200 body is stored only if it looks like the data asked for
    "symbols": lambda b: b.lstrip()[:1] == b"[",
    "payouts": lambda b: b"<table" in b,
    "mkt_summary": lambda b: b[:2] == GZIP_MAGIC or b[:4] == ZIP_MAGIC or b.count(b"|") >= 10,
    "historical": lambda b: b"<table" in b,
    "company": lambda b: b"quote__name" in b,
}


def requests_transport():
    """send(method, path, data) -> (status, body) over HTTPS, with psxdata's request token."""
    import requests
    from psxdata.constants import REQUEST_HEADERS, REQUEST_TIMEOUT, TOKEN_HEADER
    from psxdata.scrapers.token import get_default_provider
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    provider = get_default_provider()

    def send(method: str, path: str, data: dict | None = None) -> tuple[int, bytes]:
        for _ in range(2):
            token = provider.get_token()
            r = session.request(method, BASE_URL + path, data=data, timeout=REQUEST_TIMEOUT,
                                headers={TOKEN_HEADER: token} if token else {})
            if r.status_code == 403 and token:
                provider.invalidate(token)                   # token rotated: refresh once
                continue
            break
        return r.status_code, r.content
    return send


def safe_name(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", symbol)


def save_once(target: Path, body: bytes) -> None:
    """Write body to target; refuse to replace an existing file."""
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(body)
    os.rename(tmp, target)                                   # never os.replace: no overwrite


class Downloader:
    def __init__(self, send, raw: Path = RAW, log: Path = LOG, gap_s: float = MIN_GAP_S,
                 clock=time.monotonic, sleep=time.sleep, backoff_s: float = BACKOFF_S):
        self.send, self.raw, self.log, self.gap_s = send, raw, log, gap_s
        self.clock, self.sleep, self.backoff_s = clock, sleep, backoff_s
        self._last: float | None = None
        self.requests = 0
        self.missing = self._logged_404s()

    def _logged_404s(self) -> set[str]:
        if not self.log.exists():
            return set()
        with self.log.open(encoding="utf-8") as fh:
            return {r["rel"] for r in csv.DictReader(fh) if r["status"] == "404"}

    def _log(self, rel: str, status: int, n: int) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        new = not self.log.exists()
        with self.log.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rel": rel,
                        "status": status, "bytes": n})

    def _wait(self) -> None:
        if self._last is not None:
            short = self.gap_s - (self.clock() - self._last)
            if short > 0:
                self.sleep(short)
        self._last = self.clock()

    def fetch(self, rel: str, method: str, path: str, data: dict | None = None) -> str:
        """Store the response body at raw/rel once. Returns 'exists', 'missing', 'ok', '404', 'invalid'
        (a 200 whose body fails VALID[kind]; not stored, retried on the next run) or 'error'."""
        target = self.raw / rel
        if target.exists():
            return "exists"
        if rel in self.missing:
            return "missing"
        status, body = -1, b""
        for attempt in range(3):
            self._wait()
            self.requests += 1
            try:
                status, body = self.send(method, path, data)
            except Exception:                                # network error: back off, retry
                status, body = -1, b""
            if status == 429 or status >= 500 or status == -1:
                self.sleep(self.backoff_s * (attempt + 1))
                continue
            break
        valid = VALID.get(rel.split("/", 1)[0], lambda b: True)
        if status == 200 and not valid(body):
            self._log(rel, INVALID, len(body))
            return "invalid"
        self._log(rel, status, len(body))
        if status == 200:
            save_once(target, body)
            return "ok"
        if status == 404:
            self.missing.add(rel)
            return "404"
        return "error"


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def summary_symbols(raw: Path) -> set[str]:
    """Equity-like symbols in all stored closing files (futures contracts, sector 40 and '-' names, dropped)."""
    from psx.data.parse import parse_mkt_summary
    out = set()
    for p in sorted((raw / "mkt_summary").glob("*.Z")):
        df = parse_mkt_summary(p.read_bytes())
        keep = (df["sector_code"] != "40") & ~df["symbol"].str.contains("-")
        out |= set(df.loc[keep, "symbol"])
    return out


def run(dl: Downloader, snapshot: date, progress=print) -> dict:
    from psx.data.parse import payouts_total
    snap = snapshot.isoformat()
    counts: dict[str, dict[str, int]] = {}
    tally = lambda kind, res: counts.setdefault(kind, {}).__setitem__(res, counts[kind].get(res, 0) + 1)

    tally("symbols", dl.fetch(f"symbols/{snap}.json", "GET", "/symbols"))
    listed = [x["symbol"] for x in json.loads((dl.raw / f"symbols/{snap}.json").read_bytes())]

    off = 0
    while True:
        rel = f"payouts/{snap}/offset_{off:05d}.html"
        tally("payouts", dl.fetch(rel, "POST", "/payouts", {"symbol": "", "count": PAYOUT_PAGE, "offset": off}))
        total = payouts_total((dl.raw / rel).read_text(encoding="utf-8")) if (dl.raw / rel).exists() else None
        off += PAYOUT_PAGE
        if total is None or off >= total:
            break

    days = weekdays(FIRST_DAY, snapshot - timedelta(days=1))
    for i, d in enumerate(days):
        tally("mkt_summary", dl.fetch(f"mkt_summary/{d}.Z", "GET", f"/download/mkt_summary/{d}.Z"))
        if i % 250 == 0:
            progress(f"mkt_summary {d} ({i + 1}/{len(days)}) {counts['mkt_summary']}")

    gone = sorted(summary_symbols(dl.raw) - set(listed))
    symbols = sorted(set(listed)) + [INDEX] + [s for s in gone if s != INDEX]
    for i, s in enumerate(symbols):
        tally("historical", dl.fetch(f"historical/{snap}/{safe_name(s)}.html", "POST", "/historical", {"symbol": s}))
        if i % 100 == 0:
            progress(f"historical {s} ({i + 1}/{len(symbols)}) {counts['historical']}")

    for s in KNOWN_DELISTED:
        tally("company", dl.fetch(f"company/{snap}/{safe_name(s)}.html", "GET", f"/company/{s}"))
    return {"snapshot": snap, "listed": len(listed), "unlisted_seen_in_closing_files": len(gone),
            "requests": dl.requests, "results": counts}


def fingerprints(raw: Path = RAW) -> dict:
    """sha256 and size of every raw file, plus one digest over the sorted list."""
    files = {}
    for p in sorted(x for x in raw.rglob("*") if x.is_file() and not x.name.endswith(".part")):
        files[p.relative_to(raw).as_posix()] = [p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()]
    digest = hashlib.sha256("\n".join(f"{k} {v[1]}" for k, v in files.items()).encode()).hexdigest()
    return {"root": "data/psx/raw", "files_count": len(files), "bytes": sum(v[0] for v in files.values()),
            "all_files_sha256": digest, "files": files}


def write_fingerprints(fp: dict, out: Path = FINGERPRINTS) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in fp.items() if k != "files"}
    lines = [json.dumps(head, indent=1)[:-2] + ',\n "files": {']
    lines += [f' {json.dumps(k)}: {json.dumps(v)},' for k, v in fp["files"].items()]
    if fp["files"]:
        lines[-1] = lines[-1].rstrip(",")
    out.write_text("\n".join(lines) + "\n }\n}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", type=date.fromisoformat, required=True,
                    help="date of this download; names the symbol list and per-symbol folders")
    ap.add_argument("--fingerprints-only", action="store_true")
    a = ap.parse_args(argv)
    if not a.fingerprints_only:
        res = run(Downloader(requests_transport()), a.snapshot, progress=lambda m: print(m, flush=True))
        print(json.dumps(res, indent=1), flush=True)
    fp = fingerprints()
    write_fingerprints(fp)
    print(f"fingerprints: {fp['files_count']} files, {fp['bytes']:,} bytes, {fp['all_files_sha256'][:16]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
