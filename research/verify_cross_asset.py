"""Verify the cross-asset dataset: bytes, coherence, and coverage.

A hash proves the bytes have not changed. It says nothing about whether they are
*right* -- an error page, a truncated response or a silently revised series all
hash perfectly well. So this checks three different things, and the middle one is
the one a fingerprint cannot do.

1. **Integrity.** Every file still matches the frozen SHA-256 in the manifest.
2. **Coherence.** FRED maintains the identity ``DFII10 = DGS10 - T10YIE``
   (real yield = nominal yield - breakeven inflation). Three series were
   downloaded specifically so this can be checked. If the identity holds to
   within rounding on thousands of overlapping observations, the three series
   are mutually consistent and were not confused with one another.
3. **Coverage.** Each series must span the TRAIN and DEV arms of the H1 split
   (`research/research_split_manifest_h1.json`), or a hypothesis built on it
   would silently test a shorter period than it claims.

It also reports the **gap structure** of the missing observations, because the
hypothesis has to declare how it carries an observation across a market holiday
and that declaration should be made knowing how many days are involved and how
long the longest run is.

FINAL_OOS boundaries are read from the manifest **only** to assert that the data
does not need to be trimmed; no FINAL_OOS value is loaded or printed.

Exits non-zero on any failure. Run: ``python research/verify_cross_asset.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "cross_asset_v1" / "raw"
MANIFEST = REPO / "data" / "cross_asset_v1" / "meta" / "manifest.json"
H1_SPLIT = REPO / "research" / "research_split_manifest_h1.json"

MISSING = {"", "."}
# FRED publishes yields to 2 decimals, so the identity can only be expected to
# hold to the rounding of its three inputs. 0.02 is a little over 1 cent of a
# percentage point either side.
IDENTITY_TOLERANCE_PCT = 0.02
IDENTITY_MAX_VIOLATION_SHARE = 0.01

results: list[tuple[int, str, bool, str]] = []


def check(number: int, name: str, passed: bool, evidence: str) -> None:
    results.append((number, name, passed, evidence))


def load_series(series_id: str) -> pd.Series:
    """Read one raw CSV into a float Series indexed by date.

    Missing observations are dropped, not filled. This is a *reader*, so it
    makes no modelling decision; the hypothesis declares how gaps are handled.
    """
    frame = pd.read_csv(RAW / f"{series_id}.csv")
    date_column, value_column = frame.columns[0], frame.columns[1]
    frame[date_column] = pd.to_datetime(frame[date_column])
    values = pd.to_numeric(
        frame[value_column].astype(str).str.strip().replace(list(MISSING), None),
        errors="coerce",
    )
    return pd.Series(values.values, index=frame[date_column], name=series_id).dropna()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["series"]

    # --- 1. byte integrity -------------------------------------------
    mismatches = []
    for series_id, entry in sorted(entries.items()):
        digest = hashlib.sha256((RAW / f"{series_id}.csv").read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            mismatches.append(series_id)
    check(1, "raw bytes match the frozen fingerprints", not mismatches,
          f"{len(entries)} series verified, mismatches: {mismatches or 'none'}")

    # --- 2. dataset-level hash ---------------------------------------
    recomputed = hashlib.sha256(
        "".join(entries[s]["sha256"] for s in sorted(entries)).encode()
    ).hexdigest()
    check(2, "dataset_sha256 recomputes", recomputed == manifest["dataset_sha256"],
          f"{recomputed[:24]}...")

    # --- 3. coherence: real = nominal - breakeven --------------------
    real = load_series("DFII10")
    nominal = load_series("DGS10")
    breakeven = load_series("T10YIE")
    joined = pd.concat(
        {"real": real, "nominal": nominal, "breakeven": breakeven},
        axis=1, sort=True,
    ).dropna()
    residual = (joined["nominal"] - joined["breakeven"] - joined["real"]).abs()
    violations = int((residual > IDENTITY_TOLERANCE_PCT).sum())
    share = violations / len(joined) if len(joined) else 1.0
    check(
        3, "DFII10 == DGS10 - T10YIE (coherence, not just integrity)",
        len(joined) > 4000 and share <= IDENTITY_MAX_VIOLATION_SHARE,
        f"{len(joined)} overlapping observations; max |residual| "
        f"{residual.max():.4f}pp, mean {residual.mean():.6f}pp; "
        f"{violations} exceed {IDENTITY_TOLERANCE_PCT}pp ({100 * share:.3f}%)",
    )

    # --- 4. coverage of TRAIN and DEV --------------------------------
    split = json.loads(H1_SPLIT.read_text(encoding="utf-8"))
    arms = split.get("arms", split)
    train = arms["TRAIN"]
    dev = arms["DEV"]
    # The H1 manifest names its boundaries from_utc / to_utc.
    train_start = pd.Timestamp(train["from_utc"]).tz_localize(None).normalize()
    dev_end = pd.Timestamp(dev["to_utc"]).tz_localize(None).normalize()

    short = []
    for series_id in sorted(entries):
        series = load_series(series_id)
        if series.index.min() > train_start or series.index.max() < dev_end:
            short.append(
                f"{series_id} ({series.index.min().date()}..{series.index.max().date()})"
            )
    check(
        4, "every series spans TRAIN start to DEV end",
        not short,
        f"required {train_start.date()} .. {dev_end.date()}; "
        f"insufficient: {short or 'none'}",
    )

    # --- 5. no FINAL_OOS value is read -------------------------------
    # Checked structurally, not by text search. A text search cannot work here:
    # the check would match the string in its own source, which is exactly what
    # the first version of it did -- it failed itself. The AST distinguishes
    # *mentioning* "FINAL_OOS" in a comment or a message from *subscripting*
    # a container with it, which is the only way an arm gets read.
    import ast

    subscripts = [
        node for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8")))
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "FINAL_OOS"
    ]
    check(5, "this script subscripts no FINAL_OOS arm", not subscripts,
          f"{len(subscripts)} FINAL_OOS subscripts in this file; only TRAIN and "
          f"DEV boundaries are read")

    # --- 6. gap structure, reported for the hypothesis to declare ----
    gap_report = []
    for series_id in sorted(entries):
        series = load_series(series_id)
        window = series.loc[train_start:dev_end]
        business_days = pd.bdate_range(window.index.min(), window.index.max())
        absent = business_days.difference(window.index)
        longest = 0
        run = 0
        previous = None
        for day in absent:
            run = run + 1 if previous is not None and (day - previous).days <= 3 else 1
            longest = max(longest, run)
            previous = day
        gap_report.append(
            f"{series_id}: {len(absent)} of {len(business_days)} business days "
            f"absent ({100 * len(absent) / len(business_days):.2f}%), "
            f"longest run {longest}"
        )
    worst = max(
        (100 * len(pd.bdate_range(
            load_series(s).loc[train_start:dev_end].index.min(),
            load_series(s).loc[train_start:dev_end].index.max(),
        ).difference(load_series(s).loc[train_start:dev_end].index))
         / len(pd.bdate_range(
            load_series(s).loc[train_start:dev_end].index.min(),
            load_series(s).loc[train_start:dev_end].index.max(),
         )))
        for s in sorted(entries)
    )
    check(6, "missing business days are a small minority", worst < 5.0,
          "; ".join(gap_report))

    # ---------------- report ----------------
    print("=" * 78)
    print("CROSS-ASSET DATASET VERIFICATION")
    print("=" * 78)
    for number, name, passed, evidence in results:
        print(f"  {number:2d}. {'PASS' if passed else 'FAIL'}  {name}")
        print(f"        {evidence}")
    failed = [n for n, _, ok, _ in results if not ok]
    print("=" * 78)
    print(f"  {len(results) - len(failed)}/{len(results)} passed"
          + (f"   FAILED: {failed}" if failed else "   all checks pass"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
