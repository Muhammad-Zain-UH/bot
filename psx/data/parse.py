"""Parsers for raw PSX files (data/psx/raw/). Pure functions: bytes or text in, DataFrame out.

mkt_summary/<day>.Z is PSX's daily closing file: one line per instrument traded that day,
    date|symbol|sector_code|name|open|high|low|close|volume|ldcp|||
compressed as gzip or (from 2018, mixed) as a zip holding one closing11.lis. LDCP is the exchange's
reference price for the day (the last close, reduced on an ex-date). The name carries ex-entitlement
suffixes such as "XD" (ex-dividend), "XB" (ex-bonus) and "XR" (ex-right). Prices are in Pakistani
rupees (Rs) per share; volume in shares.
"""
from __future__ import annotations

import gzip
import io
import re
import zipfile
from datetime import date, datetime

import pandas as pd
from bs4 import BeautifulSoup

MKT_COLUMNS = ["date", "symbol", "sector_code", "name", "open", "high", "low", "close", "volume", "ldcp",
               "xd", "xb", "xr"]
_SUFFIX = re.compile(r"((?:\s*-?\s*X[DBR])+)\s*$")


def ex_flags(name: str) -> tuple[str, bool, bool, bool]:
    """Company name without its ex-entitlement suffix, and the (xd, xb, xr) flags it carried."""
    m = _SUFFIX.search(name)
    if not m:
        return name.strip(), False, False, False
    tag = m.group(1)
    return name[:m.start()].strip(), "XD" in tag, "XB" in tag, "XR" in tag


def parse_mkt_summary(raw: bytes, day: date | None = None) -> pd.DataFrame:
    """One day's closing file -> rows dated as the lines say; with `day`, raises if a line's date differs
    (the server answers some holidays with another day's file)."""
    text = closing_text(raw)
    rows = []
    for line in text.splitlines():
        f = line.split("|")
        if len(f) < 10 or not f[1].strip():
            continue
        d = datetime.strptime(f[0].strip(), "%d%b%Y").date()
        if day is not None and d != day:
            raise ValueError(f"line dated {d} in the file for {day}: {line!r}")
        name, xd, xb, xr = ex_flags(f[3])
        rows.append([d, f[1].strip(), f[2].strip(), name, *(_num(x) for x in f[4:10]), xd, xb, xr])
    if not rows and text.strip():
        raise ValueError(f"no closing lines parsed from a non-empty file: {text[:80]!r}")
    df = pd.DataFrame(rows, columns=MKT_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    return df.astype({c: float for c in ("open", "high", "low", "close", "volume", "ldcp")})


def closing_text(raw: bytes) -> str:
    """The closing11.lis text inside a closing file (gzip, or a zip holding one closing11.lis, at times
    inside a folder)."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if len(names) != 1 or names[0].rsplit("/", 1)[-1] != "closing11.lis":
                raise ValueError(f"expected one closing11.lis in the closing zip, got {names}")
            raw = z.read(names[0])
    return raw.decode("latin-1")


def _table(html: str) -> tuple[list[str], list[list[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    tb = soup.find("table")
    if tb is None:
        return [], []
    head = [th.get_text(" ", strip=True) for th in tb.find_all("th")]
    rows = [[td.get_text(" ", strip=True) for td in tr.find_all("td")] for tr in tb.find_all("tr")]
    return head, [r for r in rows if r]


def _num(s: str) -> float:
    s = s.replace(",", "").strip()
    return float(s) if s not in ("", "-") else float("nan")


def parse_historical(html: str) -> pd.DataFrame:
    """POST /historical response -> date, open, high, low, close, volume (unadjusted, ascending)."""
    head, rows = _table(html)
    cols = ["date", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), **{c: pd.Series(dtype=float) for c in cols[1:]}})
    if [h.upper() for h in head[:6]] != [c.upper() for c in cols]:
        raise ValueError(f"unexpected historical header {head}")
    df = pd.DataFrame([r[:6] for r in rows], columns=cols)
    df["date"] = pd.to_datetime(df["date"], format="%b %d, %Y")
    for c in cols[1:]:
        df[c] = df[c].map(_num)
    return df.sort_values("date").reset_index(drop=True)


PAYOUT_COLUMNS = ["symbol", "company", "sector", "details", "announced", "bc_from", "bc_to",
                  "dividend", "bonus", "right"]


def parse_payouts(html: str) -> pd.DataFrame:
    """POST /payouts listing page -> one row per announcement; kind flags from the (D)/(B)/(R) tags."""
    _, rows = _table(html)
    out = []
    for r in rows:
        if len(r) < 6:
            continue
        bc = [x.strip() for x in r[5].split("-")] if r[5] else ["", ""]
        to_day = lambda s: pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
        out.append([r[0], r[1], r[2], r[3], pd.to_datetime(r[4], format="%B %d, %Y %I:%M %p", errors="coerce"),
                    to_day(bc[0]), to_day(bc[-1]), "(D)" in r[3] or "DIVIDEND" in r[3].upper(),
                    "(B)" in r[3], "(R)" in r[3]])
    return pd.DataFrame(out, columns=PAYOUT_COLUMNS)


def payouts_total(html: str) -> int | None:
    """The 'of N entries' count on a /payouts page."""
    m = re.search(r"of\s+([\d,]+)\s+entries", BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    return int(m.group(1).replace(",", "")) if m else None


def company_status(html: str) -> str | None:
    """The status badge next to the name on a /company/<symbol> page, e.g. 'DELISTED', or None."""
    tags = BeautifulSoup(html, "html.parser").select(".quote__name .tag")
    return " ".join(t.get_text(" ", strip=True) for t in tags) or None
