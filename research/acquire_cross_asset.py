"""Acquire the cross-asset daily series from FRED, with provenance.

Why this exists
---------------
Five pre-registered hypotheses (H01-H05) tested 138 statistical tests against
**gold's own price history** and found nothing. That is one feature class, and it
is now exhausted: `research/VIABILITY_REPORT.md` shows which horizons can decide
anything, `research/BENCHMARK_REPORT.md` rules out intraday timing on cost, and
H05 showed a slow trend overlay on gold alone gives up more return than risk.

This brings in the first **exogenous** information the programme has had. Gold is
a zero-coupon real asset with no cash flows, so its opportunity cost is the real
interest rate; it is priced in dollars, so the dollar's level enters
mechanically; and it is held as a safe haven, so risk sentiment matters. Those
are economic mechanisms, not patterns found in a price series.

What this does and does not do
------------------------------
It downloads and **preserves raw bytes**. It computes no feature, no label, no
threshold and no result, and it transforms nothing -- the same separation
`tools/export_mt5_history.py` keeps for the MT5 bars. Missing values are
*recorded*, never filled: how to handle a market holiday is a modelling decision
and belongs in the hypothesis, where it can be declared before results exist.

Series, and why each
--------------------
``DFII10``    10-year Treasury Inflation-Indexed yield. **The primary series.**
              Gold's opportunity cost. Daily from 2003-01-02.
``DFII5``     5-year equivalent, for a robustness check at a different maturity.
``DTWEXBGS``  Nominal Broad U.S. Dollar Index. Daily from 2006-01-02.
``VIXCLS``    CBOE VIX. Risk sentiment. Daily from 1990-01-02.
``T10YIE``    10-year breakeven inflation. Supporting, and part of the identity
              below.
``DGS10``     Nominal 10-year Treasury yield. Supporting, and part of the
              identity below.

``SP500`` is deliberately **absent**. FRED serves only a rolling 10 years of it
(2016-10-03 onwards), which does not reach TRAIN's 2009 start. ``VIXCLS`` carries
the risk-sentiment mechanism instead and has 1990-onwards coverage.

The integrity check this set makes possible
-------------------------------------------
FRED maintains ``DFII10 ~= DGS10 - T10YIE`` (real = nominal - breakeven). Holding
all three means the download can be checked for **coherence**, not merely for
having arrived -- a hash proves bytes are unchanged, and says nothing about
whether they are right. See ``research/verify_cross_asset.py``.

Run: ``python research/acquire_cross_asset.py``
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "cross_asset_v1" / "raw"
META = REPO / "data" / "cross_asset_v1" / "meta"
MANIFEST = META / "manifest.json"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = "xauusd-research/1.0 (cross-asset acquisition; contact via repo)"
TIMEOUT_SECONDS = 60

SERIES: dict[str, str] = {
    "DFII10": "10-Year Treasury Inflation-Indexed Security, Constant Maturity",
    "DFII5": "5-Year Treasury Inflation-Indexed Security, Constant Maturity",
    "DTWEXBGS": "Nominal Broad U.S. Dollar Index",
    "VIXCLS": "CBOE Volatility Index: VIX",
    "T10YIE": "10-Year Breakeven Inflation Rate",
    "DGS10": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
}

# FRED writes a lone "." for a missing observation in some series and an empty
# field in others. Both mean "no observation", and neither is a zero.
MISSING = {"", "."}


class AcquisitionError(RuntimeError):
    """Raised when a series cannot be acquired or does not look like FRED CSV."""


def fetch(series_id: str) -> bytes:
    """Download one series as raw CSV bytes.

    Args:
        series_id: The FRED series identifier.

    Returns:
        The response body, unmodified.

    Raises:
        AcquisitionError: On any network or HTTP failure. Deliberately fatal:
            a partially acquired dataset must not be silently frozen.
    """
    url = FRED_CSV.format(series_id=series_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise AcquisitionError(
                    f"{series_id}: HTTP {response.status} from {url}")
            return response.read()
    except urllib.error.URLError as error:
        raise AcquisitionError(f"{series_id}: {error}") from error


def describe(series_id: str, body: bytes) -> dict:
    """Summarise a downloaded series without transforming it.

    Args:
        series_id: The FRED series identifier.
        body: The raw CSV bytes.

    Returns:
        Provenance and shape facts: byte hash, row counts, coverage, and the
        number of missing observations.

    Raises:
        AcquisitionError: If the payload does not have the expected FRED shape.
            Checked because a redirect or an error page is still bytes, and
            would otherwise be hashed and frozen as though it were data.
    """
    text = body.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise AcquisitionError(f"{series_id}: fewer than two lines; not a series")

    header = [field.strip() for field in lines[0].split(",")]
    if len(header) != 2 or series_id not in header[1].upper():
        raise AcquisitionError(
            f"{series_id}: unexpected header {header!r}. An error page or a "
            f"redirect would also be bytes; refusing to freeze it as data."
        )

    dates: list[str] = []
    missing = 0
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            raise AcquisitionError(f"{series_id}: malformed row {line!r}")
        dates.append(parts[0].strip())
        if parts[1].strip() in MISSING:
            missing += 1

    if dates != sorted(dates):
        raise AcquisitionError(f"{series_id}: dates are not ascending")
    if len(set(dates)) != len(dates):
        raise AcquisitionError(f"{series_id}: duplicate observation dates")

    return {
        "series_id": series_id,
        "title": SERIES[series_id],
        "source_url": FRED_CSV.format(series_id=series_id),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "rows": len(dates),
        "missing_observations": missing,
        "observed_rows": len(dates) - missing,
        "first_date": dates[0],
        "last_date": dates[-1],
        "value_column": header[1].strip(),
    }


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("CROSS-ASSET ACQUISITION (FRED)")
    print("=" * 78)

    entries: dict[str, dict] = {}
    for series_id in SERIES:
        body = fetch(series_id)
        entry = describe(series_id, body)
        target = RAW / f"{series_id}.csv"
        target.write_bytes(body)  # raw bytes, byte-for-byte as served
        entries[series_id] = entry
        print(
            f"  {series_id:<10} {entry['rows']:>6} rows  "
            f"{entry['observed_rows']:>6} observed  "
            f"{entry['missing_observations']:>4} missing   "
            f"{entry['first_date']} -> {entry['last_date']}"
        )

    manifest = {
        "namespace": "data/cross_asset_v1",
        "source": "FRED (Federal Reserve Bank of St. Louis), public CSV endpoint",
        "acquired_utc": datetime.now(timezone.utc).isoformat(),
        "acquisition_script": "research/acquire_cross_asset.py",
        "raw_preserved": True,
        "transformations_applied": "none",
        "missing_value_policy": (
            "RECORDED, NOT FILLED. FRED leaves a market holiday blank or '.'. "
            "How to carry an observation across a non-trading day is a "
            "modelling decision and is declared in the hypothesis "
            "specification, not here."
        ),
        "sp500_excluded_because": (
            "FRED serves only a rolling 10 years of SP500 (from 2016-10-03), "
            "which does not reach TRAIN's 2009-08-31 start. VIXCLS carries the "
            "risk-sentiment mechanism instead, with coverage from 1990."
        ),
        "series": entries,
        "dataset_sha256": hashlib.sha256(
            "".join(entries[s]["sha256"] for s in sorted(entries)).encode()
        ).hexdigest(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("-" * 78)
    print(f"  dataset_sha256 = {manifest['dataset_sha256']}")
    print(f"  written: {MANIFEST.relative_to(REPO)}")
    print("\nNothing is transformed, filled or interpolated. Verify next:")
    print("  python research/verify_cross_asset.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
