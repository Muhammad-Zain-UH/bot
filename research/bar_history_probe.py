"""BAR HISTORY PROBE -- read-only measurement of API-accessible broker bar depth.

Answers, by measurement rather than inference:
  * how many years of XAUUSD bar history each timeframe actually serves THROUGH
    THE API -- the `.hcc` cache going back to 2004 proves presence on disk, not
    retrievability;
  * whether `copy_rates_range` is bound by MaxBars the way `copy_rates_from_pos`
    is (the previous probe showed every timeframe returning exactly 99,999 rows);
  * internal consistency, gap structure, market-minute coverage;
  * native bar timezone / session alignment, derived from the data;
  * M1 -> M5 -> M15 -> H1 cross-timeframe agreement;
  * the exact contiguous recent tick interval and the location of the 2025-12
    density break.

Read-only. Writes nothing to `data/`, touches no production module, no baseline,
no order function, and parses no `.hcc`/`.tkc` file. It does cause the terminal
to cache whatever history it is asked for -- unavoidable when probing via the
API, and the reason every window here is deliberately small.

DEPTH PROBING USES A FULL YEAR-BY-YEAR SCAN, NOT BISECTION. The tick probe
learned that availability is not monotonic in age; bisection on a non-monotonic
predicate produced a wrong answer that had to be retracted.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PRIOR_MAXBARS = 100_000
SYMBOL = "XAUUSD"
TF_NAMES = ("M1", "M5", "M15", "H1", "H4")
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}
# bars expected in a 7-day window: 5 trading days x ~22 market hours.
# A return at or below 1 is a SENTINEL STUB, never historical data.
EXPECTED_7DAY = {"M1": 6600, "M5": 1320, "M15": 440, "H1": 110, "H4": 27}
DEPTH_SCAN_YEARS = range(2003, 2027)
DEPTH_WINDOW_DAYS = 7
CONSISTENCY_BARS = 50_000


def _utc(ts) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _frame(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    df["t"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def probe_depth(mt5, tf_name: str) -> dict:
    """Year-by-year scan with copy_rates_range -- is old history retrievable?"""
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    years: dict[str, int] = {}
    for y in DEPTH_SCAN_YEARS:
        a = datetime(y, 6, 1, tzinfo=timezone.utc)
        b = a + timedelta(days=DEPTH_WINDOW_DAYS)
        r = mt5.copy_rates_range(SYMBOL, tf, a, b)
        years[str(y)] = 0 if r is None else int(len(r))
    exp = EXPECTED_7DAY[tf_name]
    real = [int(y) for y, n in years.items() if n > exp * 0.3]
    stub = [int(y) for y, n in years.items() if 0 < n <= 1]
    zero = [int(y) for y, n in years.items() if n == 0]
    return {"years_with_data": years,
            "expected_count_per_window": exp,
            "real_years": real, "stub_years": stub, "zero_years": zero,
            "earliest_real_year": min(real) if real else None,
            "latest_real_year": max(real) if real else None,
            "real_years_count": len(real),
            "real_contiguous": (sorted(real) == list(range(min(real), max(real) + 1))
                                if real else None)}


def probe_from_pos_cap(mt5, tf_name: str) -> dict:
    """Does copy_rates_from_pos stop exactly at MaxBars?"""
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    out = {}
    for req in (99_999, 150_000, 500_000):
        r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, req)
        out[str(req)] = {"rows": 0 if r is None else int(len(r)),
                         "error": None if r is not None else str(mt5.last_error())}
    return out


def probe_range_unbounded(mt5, tf_name: str, earliest_year: int | None) -> dict:
    """Pull the widest range the API will serve, to see if it exceeds MaxBars."""
    if earliest_year is None:
        return {"skipped": "no served year found"}
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    a = datetime(earliest_year, 1, 1, tzinfo=timezone.utc)
    b = datetime.now(timezone.utc)
    r = mt5.copy_rates_range(SYMBOL, tf, a, b)
    if r is None or len(r) == 0:
        return {"rows": 0, "error": str(mt5.last_error())}
    # Memory guard: with MaxBars at 1e8 an M1 pull from 2003 is ~7.6M bars, and
    # building a DataFrame from it would allocate ~1GB. The count and span are
    # the measurement; the frame is not needed for them.
    if len(r) > 1_000_000:
        return {"rows": int(len(r)),
                "earliest_utc": _utc(r[0]["time"]).isoformat(),
                "latest_utc": _utc(r[-1]["time"]).isoformat(),
                "years": round((_utc(r[-1]["time"]) - _utc(r[0]["time"])).days / 365.25, 2),
                "exceeds_maxbars": bool(len(r) > PRIOR_MAXBARS),
                "note": "frame skipped above 1M rows (memory guard)"}
    df = _frame(r)
    return {"rows": int(len(df)),
            "earliest_utc": df["t"].iloc[0].isoformat(),
            "latest_utc": df["t"].iloc[-1].isoformat(),
            "years": round((df["t"].iloc[-1] - df["t"].iloc[0]).days / 365.25, 2),
            "exceeds_maxbars": bool(len(df) > PRIOR_MAXBARS)}


def consistency(mt5, tf_name: str) -> dict:
    """Validation checks mirroring data.dataset.validate_bars, plus gap census."""
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}")
    r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, CONSISTENCY_BARS)
    if r is None or len(r) == 0:
        return {"error": str(mt5.last_error())}
    df = _frame(r)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    step = TF_MINUTES[tf_name] * 60
    d = np.diff(df["time"].to_numpy(dtype="int64"))
    weekend = int((d > 48 * 3600).sum())
    daily = int(((d > step) & (d <= 6 * 3600)).sum())
    other = int(((d > 6 * 3600) & (d <= 48 * 3600)).sum())
    market_min = len(df) * TF_MINUTES[tf_name]
    span_min = (df["t"].iloc[-1] - df["t"].iloc[0]).total_seconds() / 60
    return {
        "rows": int(len(df)),
        "earliest_utc": df["t"].iloc[0].isoformat(),
        "latest_utc": df["t"].iloc[-1].isoformat(),
        "monotonic": bool((d > 0).all()),
        "duplicate_timestamps": int(len(df) - df["time"].nunique()),
        "high_lt_low": int((h < l).sum()),
        "high_below_body": int((h < np.maximum(o, c)).sum()),
        "low_above_body": int((l > np.minimum(o, c)).sum()),
        "non_positive_prices": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
        "nan_ohlc": int(np.isnan(np.c_[o, h, l, c]).sum()),
        "zero_tick_volume": int((df["tick_volume"].to_numpy() == 0).sum()),
        "gaps": {"weekend_sized_gt48h": weekend, "intraday_le6h": daily,
                 "other_6h_to_48h": other,
                 "max_gap_hours": round(float(d.max()) / 3600, 2)},
        "coverage": {"market_minutes_present": int(market_min),
                     "calendar_minutes_spanned": int(span_min),
                     "ratio": round(market_min / span_min, 4) if span_min else None},
    }


def session_alignment(mt5) -> dict:
    """Derive the session calendar FROM THE BARS -- never inherited."""
    r = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 60_000)
    if r is None or len(r) == 0:
        return {"error": str(mt5.last_error())}
    df = _frame(r)
    hr = df["t"].dt.hour
    mn = df["t"].dt.minute
    per_hour = {int(k): int(v) for k, v in hr.value_counts().sort_index().items()}
    missing_hours = [h for h in range(24) if per_hour.get(h, 0) == 0]
    d = np.diff(df["time"].to_numpy(dtype="int64"))
    idx = np.flatnonzero((d > 300) & (d <= 6 * 3600))
    breaks = {}
    for i in idx:
        key = f"{df['t'].iloc[i]:%H:%M} -> {df['t'].iloc[i+1]:%H:%M}"
        breaks[key] = breaks.get(key, 0) + 1
    widx = np.flatnonzero(d > 48 * 3600)
    weekends = {}
    for i in widx:
        key = f"{df['t'].iloc[i]:%a %H:%M} -> {df['t'].iloc[i+1]:%a %H:%M}"
        weekends[key] = weekends.get(key, 0) + 1
    # a bar opening exactly on the hour at :00 means hour-aligned; check H1
    rh = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 2000)
    h1_min = sorted({int(x) for x in _frame(rh)["t"].dt.minute}) if rh is not None else None
    return {"m5_bars_sampled": int(len(df)),
            "bars_per_utc_hour": per_hour,
            "utc_hours_with_zero_bars": missing_hours,
            "m5_minute_offsets": sorted({int(x) for x in mn}),
            "h1_minute_offsets": h1_min,
            "intraday_break_windows": dict(sorted(breaks.items(), key=lambda kv: -kv[1])[:5]),
            "weekend_windows": dict(sorted(weekends.items(), key=lambda kv: -kv[1])[:5])}


def cross_timeframe(mt5) -> dict:
    """Resample M1 -> M5/M15/H1 and compare against the broker's native bars."""
    out = {}
    r1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 40_000)
    if r1 is None or len(r1) == 0:
        return {"error": str(mt5.last_error())}
    m1 = _frame(r1).set_index("t")
    for name, rule in (("M5", "5min"), ("M15", "15min"), ("H1", "1h")):
        tf = getattr(mt5, f"TIMEFRAME_{name}")
        rn = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 20_000)
        if rn is None or len(rn) == 0:
            out[name] = {"error": str(mt5.last_error())}
            continue
        nat = _frame(rn).set_index("t")
        agg = m1.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        common = agg.index.intersection(nat.index)
        if len(common) < 50:
            out[name] = {"overlap_bars": int(len(common)), "note": "insufficient overlap"}
            continue
        a, b = agg.loc[common], nat.loc[common]
        diffs = {k: float(np.abs(a[k].to_numpy() - b[k].to_numpy()).max())
                 for k in ("open", "high", "low", "close")}
        exact = {k: int((np.abs(a[k].to_numpy() - b[k].to_numpy()) < 1e-9).sum())
                 for k in ("open", "high", "low", "close")}
        out[name] = {"overlap_bars": int(len(common)),
                     "max_abs_diff_usd": diffs,
                     "exact_match_counts": exact,
                     "exact_match_pct": {k: round(v / len(common) * 100, 2)
                                         for k, v in exact.items()}}
    return out


def tick_interval(mt5) -> dict:
    """Exact contiguous recent interval and the density-break location."""
    def count(day: datetime) -> int:
        t = mt5.copy_ticks_range(SYMBOL, day, day + timedelta(hours=24),
                                 mt5.COPY_TICKS_ALL)
        return 0 if t is None else int(len(t))

    # (a) walk forward from 2025-04 to find the first day with ticks
    first = None
    probe_log = []
    day = datetime(2025, 4, 1, tzinfo=timezone.utc)
    while day < datetime(2025, 8, 1, tzinfo=timezone.utc):
        if day.weekday() < 5:
            n = count(day)
            probe_log.append({"date": day.strftime("%Y-%m-%d"), "ticks": n})
            if n > 0 and first is None:
                first = day
                break
        day += timedelta(days=3)
    # narrow to the exact first weekday once a hit is found
    if first is not None:
        back = first - timedelta(days=1)
        while back > first - timedelta(days=10):
            if back.weekday() < 5 and count(back) > 0:
                first = back
            back -= timedelta(days=1)

    # (b) density curve across the suspected break, sampled every 3rd day
    density = []
    day = datetime(2025, 9, 1, tzinfo=timezone.utc)
    while day < datetime(2026, 3, 1, tzinfo=timezone.utc):
        if day.weekday() < 5:
            density.append({"date": day.strftime("%Y-%m-%d"), "ticks": count(day)})
        day += timedelta(days=3)
    return {"forward_scan": probe_log,
            "first_contiguous_day": first.strftime("%Y-%m-%d") if first else None,
            "density_curve": density}


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/bar_history_probe.json")
    rep: dict = {"probe_utc": datetime.now(timezone.utc).isoformat(),
                 "prior_maxbars_recorded": PRIOR_MAXBARS}
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        rep["status"] = "MT5_IMPORT_FAILED"
        rep["error"] = f"{type(exc).__name__}: {exc}"
        out_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(json.dumps(rep, indent=2)); return

    rep["mt5_python_package"] = mt5.__version__
    if not mt5.initialize(timeout=60000):
        rep["status"] = "IPC_BLOCKED"
        rep["last_error"] = str(mt5.last_error())
        out_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(json.dumps({"status": rep["status"], "err": rep["last_error"]}, indent=2)); return

    try:
        ti = mt5.terminal_info()
        live_maxbars = getattr(ti, "maxbars", None)
        rep["maxbars"] = {"prior_recorded": PRIOR_MAXBARS,
                          "live_terminal_info": live_maxbars,
                          "raised": bool(live_maxbars and live_maxbars > PRIOR_MAXBARS)}
        rep["terminal_build"] = getattr(ti, "build", None)
        si = mt5.symbol_info(SYMBOL)
        if si is None:
            rep["status"] = "SYMBOL_UNAVAILABLE"
        else:
            if not si.visible:
                mt5.symbol_select(SYMBOL, True)
            rep["depth_year_scan"] = {}
            rep["from_pos_cap"] = {}
            rep["range_widest"] = {}
            rep["consistency"] = {}
            for name in TF_NAMES:
                print(f"  depth scan {name}...", flush=True)
                rep["depth_year_scan"][name] = probe_depth(mt5, name)
                rep["from_pos_cap"][name] = probe_from_pos_cap(mt5, name)
                rep["range_widest"][name] = probe_range_unbounded(
                    mt5, name, rep["depth_year_scan"][name]["earliest_real_year"])
                rep["consistency"][name] = consistency(mt5, name)
            print("  session alignment...", flush=True)
            rep["session_alignment"] = session_alignment(mt5)
            print("  cross-timeframe...", flush=True)
            rep["cross_timeframe"] = cross_timeframe(mt5)
            print("  tick interval...", flush=True)
            rep["tick_interval"] = tick_interval(mt5)
            rep["status"] = "PROBE_COMPLETE"
    finally:
        mt5.shutdown()

    out_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps({"status": rep.get("status"), "maxbars": rep.get("maxbars")}, indent=2))


if __name__ == "__main__":
    main()
