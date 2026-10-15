"""MT5 DATA ACQUISITION PROBE -- read-only measurement of available history.

Measures what this broker/account actually holds. Does NOT export a dataset, does
not touch `data/raw`, does not touch production code or any baseline.

READ-ONLY GUARANTEE
-------------------
The only MT5 calls used are `initialize`, `shutdown`, `symbol_info`,
`symbol_select`, `terminal_info`, `account_info`, `copy_rates_*` and
`copy_ticks_range`. No order function, no account modification, and no `.hcc` or
`.tkc` file is parsed -- cached-history depth is inferred from directory listings
only (filenames and sizes), never from file contents.

Run:
    python research/data_acquisition_probe.py research/data_acquisition_probe.json

Prerequisites, both manual and both GUI-only:
    1. terminal logged in to the trading account
    2. Tools > Options > Charts > "Max bars in chart" raised from 100000
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PRIOR_MAXBARS = 100_000          # recorded in the 2026-09-16 broker_metadata.json
TERMINAL_DATA_DIR = Path(
    r"C:\Users\admin\AppData\Roaming\MetaQuotes\Terminal"
    r"\D0E8209F77C8CF37AD8BF550E51FF075"
)
# progressively larger lookbacks, in days -- never one huge request
TICK_PROBE_DAYS = (1, 7, 30, 90, 180, 365, 730, 1095)
TICK_PROBE_WINDOW_HOURS = 6      # each probe samples a bounded window at that age
BAR_TIMEFRAMES = ("M1", "M5", "M15", "H1")


def _asdict(obj):
    if obj is None:
        return None
    try:
        return {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
                for k, v in obj._asdict().items()}
    except Exception:
        return {"repr": str(obj)}


def cached_history_inventory() -> dict:
    """Depth implied by the terminal's own cache. Listing only -- no parsing."""
    out: dict = {"note": "filenames and sizes only; .hcc/.tkc contents never read"}
    for server in sorted((TERMINAL_DATA_DIR / "bases").glob("*")):
        if not server.is_dir():
            continue
        for kind in ("history", "ticks", "History"):
            d = server / kind / "XAUUSD"
            if not d.is_dir():
                continue
            files = sorted(
                ({"name": f.name, "bytes": f.stat().st_size,
                  "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
                 for f in d.iterdir() if f.is_file()),
                key=lambda r: r["name"])
            out[f"{server.name}/{kind}"] = {
                "files": files,
                "count": len(files),
                "total_bytes": sum(f["bytes"] for f in files),
            }
    return out


def probe_bars(mt5, symbol: str) -> dict:
    res: dict = {}
    for name in BAR_TIMEFRAMES:
        tf = getattr(mt5, f"TIMEFRAME_{name}")
        entry: dict = {"timeframe": name}
        try:
            # ask for far more than any plausible holding to find the real floor
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, 10_000_000)
            if rates is None or len(rates) == 0:
                entry["error"] = f"no rates; last_error={mt5.last_error()}"
            else:
                t0 = datetime.fromtimestamp(int(rates[0]["time"]), tz=timezone.utc)
                t1 = datetime.fromtimestamp(int(rates[-1]["time"]), tz=timezone.utc)
                entry.update(
                    rows=int(len(rates)),
                    earliest_utc=t0.isoformat(),
                    latest_utc=t1.isoformat(),
                    calendar_days=round((t1 - t0).total_seconds() / 86400, 1),
                    calendar_years=round((t1 - t0).total_seconds() / 86400 / 365.25, 2),
                )
                # gap census on bar open times
                import numpy as np
                times = np.array([int(r["time"]) for r in rates], dtype="int64")
                step = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}[name]
                d = np.diff(times)
                entry["gaps_gt_1_bar"] = int((d > step).sum())
                entry["gaps_gt_1_day"] = int((d > 86400).sum())
                entry["max_gap_hours"] = round(float(d.max()) / 3600, 2) if len(d) else None
                entry["monotonic"] = bool((d > 0).all())
        except Exception as exc:
            entry["exception"] = f"{type(exc).__name__}: {exc}"
        res[name] = entry
    return res


def probe_ticks(mt5, symbol: str) -> dict:
    """Bounded windows at progressively greater age. Never one large request."""
    now = datetime.now(timezone.utc)
    out: dict = {"window_hours": TICK_PROBE_WINDOW_HOURS, "probes": []}
    fields_seen: dict[str, int] = {}
    for days in TICK_PROBE_DAYS:
        end = now - timedelta(days=days)
        start = end - timedelta(hours=TICK_PROBE_WINDOW_HOURS)
        rec = {"age_days": days, "from_utc": start.isoformat(), "to_utc": end.isoformat()}
        try:
            ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
            if ticks is None:
                rec.update(count=0, last_error=str(mt5.last_error()))
            else:
                rec["count"] = int(len(ticks))
                if len(ticks):
                    rec["first_utc"] = datetime.fromtimestamp(
                        int(ticks[0]["time"]), tz=timezone.utc).isoformat()
                    rec["last_utc"] = datetime.fromtimestamp(
                        int(ticks[-1]["time"]), tz=timezone.utc).isoformat()
                    names = list(ticks.dtype.names)
                    rec["dtype_fields"] = names
                    pop = {}
                    for f in names:
                        col = ticks[f]
                        nz = int((col != 0).sum())
                        pop[f] = {"nonzero": nz,
                                  "pct": round(nz / len(ticks) * 100, 2)}
                        fields_seen[f] = fields_seen.get(f, 0) + nz
                    rec["field_population"] = pop
                    if "ask" in names and "bid" in names:
                        sp = ticks["ask"] - ticks["bid"]
                        rec["spread"] = {
                            "median": round(float(__import__("numpy").median(sp)), 4),
                            "p99": round(float(__import__("numpy").percentile(sp, 99)), 4),
                            "min": round(float(sp.min()), 4),
                            "crossed_or_zero": int((sp <= 0).sum()),
                        }
        except Exception as exc:
            rec["exception"] = f"{type(exc).__name__}: {exc}"
        out["probes"].append(rec)
    out["fields_ever_populated"] = {k: v for k, v in fields_seen.items()}
    return out


def find_earliest_tick(mt5, symbol: str, max_years: int = 12) -> dict:
    """Bisect on age to locate the oldest obtainable tick. Bounded windows only."""
    now = datetime.now(timezone.utc)

    def has_ticks(days: int) -> bool:
        end = now - timedelta(days=days)
        start = end - timedelta(hours=24)
        t = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
        return t is not None and len(t) > 0

    lo, hi = 0, int(max_years * 365.25)
    if not has_ticks(1):
        return {"status": "no ticks even at age 1 day"}
    if has_ticks(hi):
        return {"status": f"ticks available at least {max_years}y back",
                "earliest_age_days_at_least": hi}
    for _ in range(14):                       # bisection, <=14 bounded requests
        mid = (lo + hi) // 2
        if mid in (lo, hi):
            break
        if has_ticks(mid):
            lo = mid
        else:
            hi = mid
    return {"status": "bisected",
            "deepest_age_with_ticks_days": lo,
            "shallowest_age_without_ticks_days": hi,
            "approx_earliest_utc": (now - timedelta(days=lo)).isoformat(),
            "approx_years": round(lo / 365.25, 2)}


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/data_acquisition_probe.json")
    report: dict = {
        "probe_utc": datetime.now(timezone.utc).isoformat(),
        "prior_maxbars_recorded": PRIOR_MAXBARS,
        "cached_history_inventory": cached_history_inventory(),
    }
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        report["status"] = "MT5_IMPORT_FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"]}, indent=2))
        return

    report["mt5_python_package"] = mt5.__version__
    # bounded: an unbounded initialize() hung past 300s while the terminal
    # was saturating on a history download
    if not mt5.initialize(timeout=60000):
        report["status"] = "MT5_IPC_FAILED"
        report["last_error"] = str(mt5.last_error())
        report["remedy"] = ("terminal must be running AND logged in to the trading "
                            "account; a terminal sitting at a login prompt refuses IPC")
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "last_error": report["last_error"]},
                         indent=2))
        return

    try:
        ti, ai = mt5.terminal_info(), mt5.account_info()
        report["terminal_info"] = _asdict(ti)
        report["account_info"] = _asdict(ai)
        maxbars = getattr(ti, "maxbars", None)
        report["maxbars"] = {
            "before_recorded": PRIOR_MAXBARS,
            "after_measured": maxbars,
            "raised": (maxbars is not None and maxbars > PRIOR_MAXBARS),
        }
        sym = "XAUUSD"
        si = mt5.symbol_info(sym)
        if si is None:
            report["status"] = "SYMBOL_UNAVAILABLE"
        else:
            if not si.visible:
                mt5.symbol_select(sym, True)
                si = mt5.symbol_info(sym)
            report["symbol_info"] = _asdict(si)
            report["bars"] = probe_bars(mt5, sym)
            report["ticks"] = probe_ticks(mt5, sym)
            report["earliest_tick"] = find_earliest_tick(mt5, sym)
            report["status"] = "PROBE_COMPLETE"
    finally:
        mt5.shutdown()

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report.get("status"),
                      "maxbars": report.get("maxbars"),
                      "bars": {k: {kk: v.get(kk) for kk in
                                   ("rows", "earliest_utc", "calendar_years")}
                               for k, v in report.get("bars", {}).items()}}, indent=2))


if __name__ == "__main__":
    main()
