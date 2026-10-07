"""Gated access to the V2 Dukascopy frames. The FINAL_OOS lock is mechanical.

    from gold.data.store import load_v2
    h1 = load_v2("H1", "TRAIN")
    load_v2("H1", "FINAL_OOS")          # raises research.dataset_access.OOSLockedError

Arms are trading days that end at 17:00 America/New_York (ROADMAP_V2 §4). The
first trading day after each boundary is purged: it belongs to no arm. A bar
belongs to an arm only if it lies wholly inside it:
from_utc <= time and time + bar length <= to_utc.

Every load verifies the frame's fingerprint against
research/dukascopy_v1_fingerprints.json (written by gold.data.build_v2).

    venv\\Scripts\\python.exe -m gold.data.store --write-manifest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from gold.data.build_v2 import (BARS_DIR, COLUMNS, D1_BOUNDARY_HOUR_NY, FINGERPRINTS,
                                NEW_YORK, TF_DURATION)
from research.dataset_access import (DatasetIntegrityError, OOSLockedError, _fingerprint,
                                     _split)

REPO = Path(__file__).resolve().parents[2]
MANIFEST_V2 = REPO / "research" / "research_split_manifest_v2.json"
OOS_TOKEN = "OOS-AUTHORISATION-NOT-ISSUED"
# Trading days (17:00 New York close), inclusive -- ROADMAP_V2 §4.
ARM_DAYS = {"TRAIN": (dt.date(2003, 5, 5), dt.date(2016, 12, 30)),
            "DEV": (dt.date(2017, 1, 2), dt.date(2025, 9, 1)),
            "FINAL_OOS": (dt.date(2025, 9, 2), dt.date(2026, 10, 1))}
PURGE_TRADING_DAYS = 1

__all__ = ["load_v2", "build_manifest", "OOSLockedError", "DatasetIntegrityError"]


def close_utc(day: dt.date) -> pd.Timestamp:
    """17:00 New York on `day`, in UTC (DST-correct)."""
    local = dt.datetime.combine(day, dt.time(D1_BOUNDARY_HOUR_NY), tzinfo=NEW_YORK)
    return pd.Timestamp(local).tz_convert("UTC")


def _prev_weekday(day: dt.date) -> dt.date:
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _next_weekday(day: dt.date) -> dt.date:
    day += dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def build_manifest() -> dict:
    arms, purges = {}, []
    names = list(ARM_DAYS)
    for i, name in enumerate(names):
        first, last = ARM_DAYS[name]
        start = _prev_weekday(first)            # the session for `first` opens at this close
        if i > 0:
            prev_last = ARM_DAYS[names[i - 1]][1]
            purged = prev_last
            for _ in range(PURGE_TRADING_DAYS):
                purged = _next_weekday(purged)
            purges.append({"trading_day": purged.isoformat(),
                           "from_utc": close_utc(prev_last).isoformat(),
                           "to_utc": close_utc(purged).isoformat()})
            start = purged
        arms[name] = {"first_trading_day": first.isoformat(),
                      "last_trading_day": last.isoformat(),
                      "from_utc": close_utc(start).isoformat(),
                      "to_utc": close_utc(last).isoformat()}
    return {
        "status": "V2 split -- ROADMAP_V2 §4",
        "dataset": "Dukascopy XAUUSD M1 bid/ask, data/dukascopy_v1/bars",
        "FINAL_OOS_LOCKED": True,
        "oos_authorisation_token": OOS_TOKEN,
        "oos_unlock_requirements": [
            "explicit written authorisation from the owner",
            "record the date, the git SHA and the candidate specification SHA at the moment it is opened",
            "one look only; a revised candidate on a used OOS is a new candidate on a spent arm"],
        "trading_day": "ends 17:00 America/New_York (DST-correct)",
        "membership_rule": "from_utc <= time and time + bar length <= to_utc",
        "purge": {"trading_days_after_each_boundary": PURGE_TRADING_DAYS, "windows": purges},
        "arms": arms,
        "enforcement": "gold/data/store.load_v2 raises research.dataset_access.OOSLockedError "
                       "on any FINAL_OOS read without the manifest token",
    }


def verify_frame(tf: str, df: pd.DataFrame, fingerprints: Path = FINGERPRINTS) -> None:
    if not fingerprints.exists():
        raise DatasetIntegrityError(f"{fingerprints} missing: build the dataset first")
    expect = json.loads(fingerprints.read_text(encoding="utf-8")).get("frames", {}).get(tf)
    if expect is None:
        raise DatasetIntegrityError(f"no fingerprint recorded for {tf}")
    got = _fingerprint(df[COLUMNS])
    if got != expect["values_sha256"]:
        raise DatasetIntegrityError(
            f"{tf} fingerprint mismatch: frozen {expect['values_sha256']} but recomputed {got}")


def load_v2(tf: str, arm: str, oos_authorisation: str | None = None, *,
            bars_dir: Path = BARS_DIR, fingerprints: Path = FINGERPRINTS,
            manifest: Path = MANIFEST_V2) -> pd.DataFrame:
    """Load one arm of one V2 timeframe ("M1", "M15", "H1", "H4", "D1").

    Raises:
        OOSLockedError: FINAL_OOS without the exact manifest token, before any read.
        DatasetIntegrityError: the frame does not match its recorded fingerprint.
    """
    split = _split(manifest)
    arms = split["arms"]
    if arm not in arms:
        raise KeyError(f"unknown arm {arm!r}; expected one of {sorted(arms)}")
    if tf not in TF_DURATION:
        raise KeyError(f"unknown timeframe {tf!r}; expected one of {sorted(TF_DURATION)}")
    if arm == "FINAL_OOS" and split.get("FINAL_OOS_LOCKED", True):
        if oos_authorisation != split.get("oos_authorisation_token"):
            raise OOSLockedError(
                "FINAL_OOS is LOCKED. Loading it requires the manifest's authorisation "
                "token, issued in writing by the owner, and opening it must be recorded "
                "with the date, the git SHA and the candidate specification SHA.")
    df = pd.read_parquet(bars_dir / f"XAUUSD_{tf}.parquet")
    verify_frame(tf, df, fingerprints)
    lo, hi = pd.Timestamp(arms[arm]["from_utc"]), pd.Timestamp(arms[arm]["to_utc"])
    inside = (df["time"] >= lo) & (df["time"] + TF_DURATION[tf] <= hi)
    return df[inside].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-manifest", action="store_true")
    args = ap.parse_args(argv)
    if args.write_manifest:
        MANIFEST_V2.write_text(json.dumps(build_manifest(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST_V2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
