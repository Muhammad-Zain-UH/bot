"""Broker bars with DST-correct UTC: data/research_v1/raw_server -> data/research_v1b.

data/research_v1 converted server time with a fixed -3 h, which is right only in
US summer. The broker clock is GMT+2 in winter and GMT+3 in summer, but its
switch dates changed in 2020 (measured from the daily 18:00 New York reopen in
the weeks when only the US is on summer time):

    server time before 2020-07-01: New York time + 7 h (US switch dates)
    server time from 2020-07-01:   Europe/Athens time  (EU switch dates)

The two rules agree everywhere between 2020-03-29 and 2020-10-25, so the exact
switch date inside that window does not change any bar. A bar that falls in a
nonexistent or ambiguous local hour (the Sunday DST switches, when gold is
closed) fails the build. data/research_v1 is read only and never modified.

utc_suspect: an independent weekly check, never used to set the offset. Each
daily and weekend reopen should land at 18:00 America/New_York. For every
trading week the offset implied by its reopens (their median) is compared with
the rule; if they disagree, every bar of that week, in every timeframe, gets
utc_suspect = True. Bars are never shifted. The flag is a weekly label (a bar
can be flagged by a reopen later in its week): use it to exclude bars from
session-based tests, never as a feature. H4 before the H1 history (2004-06 ->
2009-08) cannot be checked and stays False; its clock convention is unconfirmed.

Output: data/research_v1b/bars/XAUUSD_{TF}.parquet with time (UTC), open, high,
low, close, tick_volume, spread_usd, utc_suspect. spread_usd = MT5 bar spread x
symbol point, stored as delivered; the exact definition of the MT5 bar spread
(e.g. minimum or last within the bar) is broker-dependent. H4 bars keep the
broker's server-midnight alignment, so their UTC opens are not multiples of 4 h.

    venv\\Scripts\\python.exe -m gold.data.build_broker_v1b
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "research_v1" / "raw_server"
V1_MANIFEST = REPO / "data" / "research_v1" / "meta" / "manifest.json"
OUT_DIR = REPO / "data" / "research_v1b" / "bars"
FINGERPRINTS = REPO / "research" / "broker_v1b_fingerprints.json"
H1_MANIFEST = REPO / "research" / "research_split_manifest_h1.json"
H1_V1B_MANIFEST = REPO / "research" / "research_split_manifest_h1_v1b.json"
NEW_YORK = ZoneInfo("America/New_York")
ATHENS = ZoneInfo("Europe/Athens")
SERVER_MINUS_NEW_YORK = pd.Timedelta(hours=7)
RULE_SWITCH_SERVER = pd.Timestamp("2020-07-01 00:00")      # server wall time
SESSION_CLOSE_HOUR_NY = 17
REOPEN_HOUR_NY = 18
REOPEN_WINDOW_H = 3          # a bar after a gap within +-3 h of 18:00 NY is a reopen
TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4")
COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread_usd", "utc_suspect"]
RULE = ("server time before 2020-07-01: UTC = (server - 7 h) localised to "
        "America/New_York; from 2020-07-01: server time localised to Europe/Athens; "
        "both converted to UTC")
SPREAD_NOTE = ("spread_usd = MT5 bar 'spread' field x symbol_info.point, stored as "
               "delivered; the exact definition of the MT5 bar spread is broker-dependent")


class OutputExistsError(RuntimeError):
    """Built output is write-once."""


def _localise(wall: pd.Series, tz: ZoneInfo) -> pd.Series:
    try:
        return wall.dt.tz_localize(tz, ambiguous="raise", nonexistent="raise")
    except Exception as exc:          # pandas raises its own ValueError subclasses
        raise ValueError(f"server time maps to a nonexistent or ambiguous {tz.key} "
                         f"hour: {exc}") from exc


def server_to_utc(server: pd.Series) -> pd.Series:
    """Broker server wall time -> UTC under the two-period rule. Raises
    ValueError on a nonexistent or ambiguous local hour."""
    wall = pd.to_datetime(server, utc=True).dt.tz_localize(None).reset_index(drop=True)
    old = wall < RULE_SWITCH_SERVER
    parts = []
    if old.any():
        parts.append(_localise(wall[old] - SERVER_MINUS_NEW_YORK, NEW_YORK).dt.tz_convert("UTC"))
    if (~old).any():
        parts.append(_localise(wall[~old], ATHENS).dt.tz_convert("UTC"))
    out = pd.concat(parts) if parts else pd.Series([], dtype="datetime64[ns, UTC]")
    return out.sort_index().astype("datetime64[ns, UTC]")


def trading_week(time: pd.Series) -> pd.Series:
    """Monday date of the trading week. Sessions end 17:00 New York, so Sunday
    evening belongs to Monday's session."""
    session = (time.dt.tz_convert(NEW_YORK).dt.tz_localize(None)
               + pd.Timedelta(hours=24 - SESSION_CLOSE_HOUR_NY)).dt.normalize()
    return session - pd.to_timedelta(session.dt.dayofweek, unit="D")


def reopen_weeks(h1_time: pd.Series) -> pd.DataFrame:
    """Per trading week: reopen events and the offset they imply, in hours
    (0 = consistent with the rule). A reopen is the first H1 bar after a gap of
    at least 2 h whose New York wall time lies within REOPEN_WINDOW_H of 18:00."""
    t = h1_time.reset_index(drop=True)
    gap = t.diff()
    ny = t.dt.tz_convert(NEW_YORK)
    off = ny.dt.hour + ny.dt.minute / 60 - REOPEN_HOUR_NY
    ev = pd.DataFrame({"week": trading_week(t), "offset_h": off})
    ev = ev[(gap >= pd.Timedelta(hours=2)) & (off.abs() <= REOPEN_WINDOW_H)]
    weeks = ev.groupby("week")["offset_h"].agg(
        reopens="size", implied_offset_h="median",
        reopens_off_rule=lambda s: int((s != 0).sum()))
    weeks["utc_suspect"] = weeks["implied_offset_h"] != 0
    return weeks.reset_index()


def flag(frame: pd.DataFrame, suspect_weeks: set) -> pd.DataFrame:
    out = frame.copy()
    out["utc_suspect"] = trading_week(out["time"]).isin(suspect_weeks).to_numpy()
    return out[COLUMNS]


def convert(raw: pd.DataFrame, point: float) -> pd.DataFrame:
    """One raw_server frame -> the v1b frame (same rows, same order), unflagged."""
    out = pd.DataFrame({"time": server_to_utc(raw["time_server"])})
    for c in ("open", "high", "low", "close", "tick_volume"):
        out[c] = raw[c].astype(float).to_numpy()
    out["spread_usd"] = raw["spread"].astype(float).to_numpy() * point
    out["utc_suspect"] = False
    if not out["time"].is_monotonic_increasing or out["time"].duplicated().any():
        raise ValueError("converted times are not unique and increasing")
    return out[COLUMNS]


def build(raw_dir: Path, out_dir: Path, point: float) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Convert all timeframes, flag suspect weeks from the H1 reopens, write Parquet."""
    targets = {tf: out_dir / f"XAUUSD_{tf}.parquet" for tf in TIMEFRAMES}
    existing = [str(p) for p in targets.values() if p.exists()]
    if existing:
        raise OutputExistsError(f"refusing to overwrite {existing}")
    frames = {tf: convert(pd.read_csv(raw_dir / f"XAUUSD_{tf}_server.csv"), point)
              for tf in TIMEFRAMES}
    weeks = reopen_weeks(frames["H1"]["time"])
    suspect = set(weeks.loc[weeks["utc_suspect"], "week"])
    frames = {tf: flag(df, suspect) for tf, df in frames.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    for tf, df in frames.items():
        df.to_parquet(targets[tf], index=False)
    return frames, weeks


TRAIN_D1_DAYS = ("2004-06-14", "2020-12-31")      # first and last trading day (17:00 NY close)


def _ny_close_utc(day: str, day_offset: int = 0) -> str:
    wall = pd.Timestamp(day) + pd.Timedelta(days=day_offset, hours=SESSION_CLOSE_HOUR_NY)
    return str(wall.tz_localize(NEW_YORK).tz_convert("UTC"))


def split_manifest(h1: dict) -> dict:
    """research_split_manifest_h1.json with its arm boundaries, purge rule and OOS
    lock copied unchanged; row counts and statistics are not copied (they were
    computed on the fixed -3 h labels). TRAIN_D1 extends TRAIN backwards for
    daily research only; DEV and FINAL_OOS are unchanged."""
    arms = {a: {"from_utc": v["from_utc"], "to_utc": v["to_utc"]} for a, v in h1["arms"].items()}
    first, last = TRAIN_D1_DAYS
    arms["TRAIN_D1"] = {
        "first_trading_day": first, "last_trading_day": last,
        "from_utc": _ny_close_utc(first, -1), "to_utc": _ny_close_utc(last),
        "use": "daily and weekly research (batch 2) only, D1 bars at the 17:00 New York "
               "boundary built from H4 (gold/data/broker_daily.py); backward extension of "
               "TRAIN, ends at the 2020-12-31 close, inside the TRAIN/DEV gap",
        "clock_note": "the broker clock convention before 2009-08 is unconfirmed; a 1 h "
                      "shift is negligible for daily data",
    }
    return {
        "status": "broker v1b split: boundaries copied unchanged from "
                  "research/research_split_manifest_h1.json",
        "dataset": "data/research_v1b/bars (DST-correct UTC), fingerprints in "
                   "research/broker_v1b_fingerprints.json",
        "FINAL_OOS_LOCKED": h1["FINAL_OOS_LOCKED"],
        "oos_authorisation_token": h1["oos_authorisation_token"],
        "oos_unlock_requirements": h1["oos_unlock_requirements"],
        "oos_prohibitions": h1["oos_prohibitions"],
        "purge_embargo": h1["purge_embargo"],
        "membership_rule": "from_utc <= bar open time <= to_utc, as research/dataset_access.load_arm",
        "arms": arms,
        "enforcement": "gold/data/store.load_broker_v1b raises "
                       "research.dataset_access.OOSLockedError on any FINAL_OOS read "
                       "without the manifest token",
    }


def main() -> int:
    from research.dataset_access import _fingerprint
    point = float(json.loads(V1_MANIFEST.read_text(encoding="utf-8"))["symbol_info"]["point"])
    frames, weeks = build(RAW_DIR, OUT_DIR, point)
    record = {
        "rule": RULE,
        "utc_suspect": "weekly reopen check, never used to set the offset; "
                       f"{int(weeks['utc_suspect'].sum())} trading weeks flagged",
        "h4_before_h1_history": "2004-06 -> 2009-08: clock convention unconfirmed (H4 hides "
                                "a 1 h shift); utc_suspect stays False there",
        "source": "data/research_v1/raw_server (unmodified)",
        "symbol_point": point,
        "spread_note": SPREAD_NOTE,
        "columns": COLUMNS,
        "raw_file_sha256": {tf: hashlib.sha256((RAW_DIR / f"XAUUSD_{tf}_server.csv")
                                               .read_bytes()).hexdigest() for tf in TIMEFRAMES},
        "frames": {tf: {"values_sha256": _fingerprint(df[COLUMNS]), "rows": len(df),
                        "first_utc": df["time"].iloc[0].isoformat(),
                        "last_utc": df["time"].iloc[-1].isoformat()}
                   for tf, df in frames.items()},
    }
    FINGERPRINTS.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    h1 = json.loads(H1_MANIFEST.read_text(encoding="utf-8"))
    H1_V1B_MANIFEST.write_text(json.dumps(split_manifest(h1), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["frames"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
