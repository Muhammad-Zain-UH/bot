"""Build the immutable research bar dataset from ACTUALLY API-accessible history.

Namespace: `data/research_v1/` -- a dedicated tree. `data/raw/` and every
`baselines/*` directory are untouched and unread by this script.

    data/research_v1/
      raw_server/   immutable raw API output, SERVER timestamps, write-once
      bars/         UTC-normalised, the project's existing 6-column contract
      meta/         manifest, fingerprints, chunk log, broker metadata

Design decisions that matter
----------------------------
* **Chunked.** One `copy_rates_range` per window, sized per timeframe so no chunk
  approaches the row count at which the API returns `Invalid params`.
* **Sentinel defence.** The probe established that `copy_rates_range` returns a
  1-row sentinel for unmaterialised periods. Every returned row is therefore
  filtered to the requested window and rows outside it are dropped AND counted.
  A chunk returning a single out-of-window row contributes nothing.
* **Raw preserved immutably.** `raw_server/` is write-once; the build refuses to
  overwrite it, mirroring `backtest.baseline.write_artifacts`.
* **Timestamps.** Raw files keep `time_server` exactly as the API returned it.
  Normalised files carry `time` = `time_server - 3h`, the independently measured
  offset. The raw column is never rewritten.
* **Fingerprints hash bar VALUES**, not file bytes, so they are independent of
  CSV formatting and float repr -- the same rule as
  `backtest.baseline.dataset_fingerprint`.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "data" / "research_v1"
SYMBOL = "XAUUSD"
SERVER_OFFSET_HOURS = 3.0          # independently measured, see BAR_HISTORY_PROBE
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)   # exclusive upper bound

# verified API-accessible floors (server time), from the accepted probe
FLOORS = {
    "H1":  datetime(2009, 8, 18, tzinfo=timezone.utc),
    "M15": datetime(2022, 6, 30, tzinfo=timezone.utc),
    "M5":  datetime(2025, 4, 25, tzinfo=timezone.utc),
    "M1":  datetime(2026, 6, 17, tzinfo=timezone.utc),
    "H4":  datetime(2004, 6, 11, tzinfo=timezone.utc),
}
# chunk width chosen so each request stays well under ~20k rows
CHUNK_DAYS = {"M1": 30, "M5": 90, "M15": 180, "H1": 365, "H4": 730}
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}
BAR_COLUMNS = ("time", "open", "high", "low", "close", "tick_volume")


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def fingerprint(df: pd.DataFrame) -> str:
    """Hash bar VALUES, not file bytes."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    return h.hexdigest()


def export_timeframe(mt5, name: str, chunk_log: list) -> pd.DataFrame:
    tf = getattr(mt5, f"TIMEFRAME_{name}")
    start, width = FLOORS[name], timedelta(days=CHUNK_DAYS[name])
    frames, cursor = [], start
    while cursor < NOW:
        end = min(cursor + width, NOW)
        r = mt5.copy_rates_range(SYMBOL, tf, cursor, end)
        rec = {"timeframe": name, "from": cursor.isoformat(), "to": end.isoformat(),
               "returned": 0 if r is None else int(len(r)), "kept": 0, "dropped": 0,
               "error": None if r is not None else str(mt5.last_error())}
        if r is not None and len(r):
            df = pd.DataFrame(r)
            ts = pd.to_datetime(df["time"], unit="s", utc=True)
            # sentinel / out-of-window defence
            inside = (ts >= cursor) & (ts < end)
            rec["kept"] = int(inside.sum())
            rec["dropped"] = int((~inside).sum())
            if inside.any():
                frames.append(df.loc[inside].assign(time_server=ts[inside]))
        chunk_log.append(rec)
        print(f"    {name} {cursor:%Y-%m-%d} -> {end:%Y-%m-%d}: "
              f"returned {rec['returned']:>6} kept {rec['kept']:>6} "
              f"dropped {rec['dropped']}", flush=True)
        cursor = end
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset="time_server").sort_values("time_server")
    return out.reset_index(drop=True)


def validate(df: pd.DataFrame, name: str) -> dict:
    if df.empty:
        return {"rows": 0, "error": "empty"}
    t = df["time"]
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    step = TF_MINUTES[name] * 60
    # pandas 3.0 REFUSES .astype("int64") on a tz-aware Series (TypeError).
    # to_numpy("datetime64[s]") is the correct, tz-safe conversion.
    secs = t.to_numpy("datetime64[s]").astype("int64")
    d = np.diff(secs)
    span_min = (t.iloc[-1] - t.iloc[0]).total_seconds() / 60
    market_min = len(df) * TF_MINUTES[name]
    gaps = d[d > step]
    return {
        "rows": int(len(df)),
        "first_utc": t.iloc[0].isoformat(), "last_utc": t.iloc[-1].isoformat(),
        "years": round((t.iloc[-1] - t.iloc[0]).days / 365.25, 2),
        "monotonic_strict": bool((d > 0).all()),
        "duplicate_timestamps": int(len(df) - t.nunique()),
        "high_lt_low": int((h < l).sum()),
        "high_below_body": int((h < np.maximum(o, c)).sum()),
        "low_above_body": int((l > np.minimum(o, c)).sum()),
        "non_positive_prices": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
        "nan_ohlc": int(np.isnan(np.c_[o, h, l, c]).sum()),
        "zero_tick_volume": int((df["tick_volume"].to_numpy() == 0).sum()),
        "gaps_total": int(len(gaps)),
        "gaps_weekend_gt48h": int((gaps > 48 * 3600).sum()),
        "gaps_intraday_le6h": int((gaps <= 6 * 3600).sum()),
        "gaps_other": int(((gaps > 6 * 3600) & (gaps <= 48 * 3600)).sum()),
        "max_gap_hours": round(float(gaps.max()) / 3600, 2) if len(gaps) else 0.0,
        "market_minutes": int(market_min),
        "calendar_minutes": int(span_min),
        "coverage_ratio": round(market_min / span_min, 4) if span_min else None,
        "ohlc_valid": bool((h >= l).all() and (h >= np.maximum(o, c)).all()
                           and (l <= np.minimum(o, c)).all()),
    }


def main() -> None:
    raw_dir, bar_dir, meta_dir = (OUT_ROOT / "raw_server", OUT_ROOT / "bars",
                                  OUT_ROOT / "meta")
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise SystemExit(f"REFUSING to overwrite immutable raw export at {raw_dir}")
    for d in (raw_dir, bar_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=60000):
        raise SystemExit(f"IPC failed: {mt5.last_error()}")

    manifest: dict = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL, "namespace": str(OUT_ROOT.relative_to(REPO)),
        "git_sha": git_sha(),
        "server_offset_hours_applied": SERVER_OFFSET_HOURS,
        "mt5_python_package": mt5.__version__,
        "verified_floors_server": {k: v.isoformat() for k, v in FLOORS.items()},
        "chunk_days": CHUNK_DAYS,
        "timeframes": {},
    }
    fingerprints: dict = {}
    chunk_log: list = []
    try:
        ti, ai, si = mt5.terminal_info(), mt5.account_info(), mt5.symbol_info(SYMBOL)
        for label, obj in (("terminal_info", ti), ("account_info", ai),
                           ("symbol_info", si)):
            manifest[label] = {k: (v if isinstance(v, (int, float, str, bool, type(None)))
                                   else str(v)) for k, v in obj._asdict().items()}
        manifest["maxbars"] = getattr(ti, "maxbars", None)

        for name in ("H1", "M15", "M5", "M1", "H4"):
            print(f"  exporting {name} ...", flush=True)
            raw = export_timeframe(mt5, name, chunk_log)
            if raw.empty:
                manifest["timeframes"][name] = {"error": "no rows returned"}
                continue
            # --- immutable raw, SERVER timestamps preserved verbatim ---
            rawfile = raw_dir / f"{SYMBOL}_{name}_server.csv"
            raw_out = raw[["time_server", "open", "high", "low", "close",
                           "tick_volume", "spread", "real_volume"]].copy() \
                if "spread" in raw.columns else \
                raw[["time_server", "open", "high", "low", "close", "tick_volume"]].copy()
            raw_out.to_csv(rawfile, index=False)
            # --- UTC-normalised, existing 6-column contract ---
            norm = pd.DataFrame({
                "time": raw["time_server"] - pd.Timedelta(hours=SERVER_OFFSET_HOURS),
                "open": raw["open"].astype(float), "high": raw["high"].astype(float),
                "low": raw["low"].astype(float), "close": raw["close"].astype(float),
                "tick_volume": raw["tick_volume"].astype(float)})
            norm = norm[list(BAR_COLUMNS)]
            normfile = bar_dir / f"{SYMBOL}_{name}.csv"
            norm.to_csv(normfile, index=False)

            v = validate(norm, name)
            v["raw_file"] = str(rawfile.relative_to(REPO))
            v["normalised_file"] = str(normfile.relative_to(REPO))
            v["raw_bytes"] = rawfile.stat().st_size
            v["normalised_bytes"] = normfile.stat().st_size
            v["first_server"] = raw["time_server"].iloc[0].isoformat()
            v["last_server"] = raw["time_server"].iloc[-1].isoformat()
            manifest["timeframes"][name] = v
            fingerprints[name] = {
                "values_sha256": fingerprint(norm),
                "rows": int(len(norm)),
                "first_utc": v["first_utc"], "last_utc": v["last_utc"]}
            print(f"    -> {len(norm):,} rows  {v['first_utc'][:10]} -> "
                  f"{v['last_utc'][:10]}  fp={fingerprints[name]['values_sha256'][:16]}")
    finally:
        mt5.shutdown()

    manifest["chunk_log"] = chunk_log
    manifest["chunk_count"] = len(chunk_log)
    manifest["sentinel_rows_dropped"] = int(sum(c["dropped"] for c in chunk_log))
    combined = hashlib.sha256()
    for k in sorted(fingerprints):
        combined.update(fingerprints[k]["values_sha256"].encode())
    fingerprints["dataset_sha256"] = combined.hexdigest()

    (meta_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (meta_dir / "fingerprints.json").write_text(json.dumps(fingerprints, indent=2), encoding="utf-8")
    Path(REPO / "research" / "accessible_bar_dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    Path(REPO / "research" / "accessible_bar_dataset_fingerprints.json").write_text(
        json.dumps(fingerprints, indent=2), encoding="utf-8")
    print(f"\n  chunks={len(chunk_log)}  sentinel rows dropped="
          f"{manifest['sentinel_rows_dropped']}")
    print(f"  dataset_sha256 = {fingerprints['dataset_sha256']}")


if __name__ == "__main__":
    main()
