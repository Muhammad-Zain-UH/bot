"""Gated access to the frozen research dataset. The OOS lock is MECHANICAL here.

`research_split_manifest.json` declares `FINAL_OOS_LOCKED = true`. A declaration
in a file is not an enforcement mechanism, so this module is the enforcement: it
is the only sanctioned way to load an arm of the dataset, and it **raises** on any
attempt to read FINAL_OOS without an explicit authorisation token.

    from research.dataset_access import load_arm, verify_dataset

    verify_dataset()                      # fingerprints must match the freeze
    m15 = load_arm("M15", "TRAIN")        # fine
    m15 = load_arm("M15", "DEV")          # fine
    m15 = load_arm("M15", "FINAL_OOS")    # raises OOSLockedError

Unlocking is deliberately awkward. It requires the exact token string recorded in
the manifest, which exists so that opening OOS is a decision someone has to make
in writing rather than a default that happens by accident.

Nothing here computes a feature, a label, a threshold or a result.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core.types import Timeframe
from data.dataset import load_bars_csv

DATA_ROOT = REPO / "data" / "research_v1"
BARS = DATA_ROOT / "bars"
SPLIT_MANIFEST = Path(__file__).with_name("research_split_manifest.json")
FINGERPRINTS = Path(__file__).with_name("accessible_bar_dataset_fingerprints.json")

TF_ENUM = {"M1": Timeframe.M1, "M5": Timeframe.M5, "M15": Timeframe.M15,
           "H1": Timeframe.H1, "H4": Timeframe.H4}


class OOSLockedError(RuntimeError):
    """Raised on any attempt to read FINAL_OOS without written authorisation."""


class DatasetIntegrityError(RuntimeError):
    """Raised when a file no longer matches the frozen fingerprint."""


def _split() -> dict:
    return json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))


def _fingerprint(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    return h.hexdigest()


def load_timeframe(tf: str) -> pd.DataFrame:
    """Load a whole timeframe. No arm filtering -- callers must slice responsibly."""
    if tf not in TF_ENUM:
        raise KeyError(f"unknown timeframe {tf!r}; expected one of {sorted(TF_ENUM)}")
    return load_bars_csv(BARS / f"XAUUSD_{tf}.csv", TF_ENUM[tf])


def verify_dataset(strict: bool = True) -> dict:
    """Recompute every fingerprint and compare against the freeze record."""
    expect = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    result = {}
    for tf in TF_ENUM:
        df = load_timeframe(tf)
        got = _fingerprint(df[["time", "open", "high", "low", "close", "tick_volume"]])
        ok = got == expect[tf]["values_sha256"]
        result[tf] = {"match": ok, "rows": int(len(df)),
                      "expected": expect[tf]["values_sha256"], "got": got}
        if strict and not ok:
            raise DatasetIntegrityError(
                f"{tf} fingerprint mismatch: frozen {expect[tf]['values_sha256']} "
                f"but recomputed {got}")
    combined = hashlib.sha256()
    for k in sorted(TF_ENUM):
        combined.update(expect[k]["values_sha256"].encode())
    result["dataset_sha256"] = combined.hexdigest()
    result["dataset_match"] = combined.hexdigest() == expect["dataset_sha256"]
    if strict and not result["dataset_match"]:
        raise DatasetIntegrityError("dataset_sha256 mismatch")
    return result


def load_arm(tf: str, arm: str, oos_authorisation: str | None = None) -> pd.DataFrame:
    """Load one chronological arm of one timeframe.

    Args:
        tf: "M1" | "M5" | "M15" | "H1" | "H4".
        arm: "TRAIN" | "DEV" | "FINAL_OOS".
        oos_authorisation: required only for FINAL_OOS, and only matches the exact
            token in the split manifest.

    Raises:
        OOSLockedError: for FINAL_OOS without the correct token.
    """
    split = _split()
    arms = split["arms"]
    if arm not in arms:
        raise KeyError(f"unknown arm {arm!r}; expected one of {sorted(arms)}")
    if arm == "FINAL_OOS" and split.get("FINAL_OOS_LOCKED", True):
        token = split.get("oos_authorisation_token")
        if oos_authorisation != token:
            raise OOSLockedError(
                "FINAL_OOS is LOCKED. No feature, candidate, threshold, label or "
                "result may inspect it until an explicit OOS authorisation is "
                "issued. Loading it requires the manifest's authorisation token, "
                "and opening it must be recorded with the date, the git SHA and "
                "the candidate specification SHA."
            )
    bounds = arms[arm]
    df = load_timeframe(tf)
    lo = pd.Timestamp(bounds["from_utc"])
    hi = pd.Timestamp(bounds["to_utc"])
    return df[(df["time"] >= lo) & (df["time"] <= hi)].reset_index(drop=True)


if __name__ == "__main__":
    print(json.dumps(verify_dataset(), indent=2))
    for arm in ("TRAIN", "DEV"):
        d = load_arm("M15", arm)
        print(f"  M15 {arm}: {len(d):,} rows "
              f"{d['time'].iloc[0]:%Y-%m-%d} -> {d['time'].iloc[-1]:%Y-%m-%d}")
    try:
        load_arm("M15", "FINAL_OOS")
    except OOSLockedError as exc:
        print(f"  M15 FINAL_OOS: LOCKED as expected -- {type(exc).__name__}")
