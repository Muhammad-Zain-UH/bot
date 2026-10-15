"""S1b paper log (research/v2026/FORWARD_S1B_PAPER.md, f7c4d96). READ-ONLY: no orders.

A separate process from forward test S1. It reads MT5 H1 bars and tick history only; it sends no
order and holds no position. For each trading day of the S1 period, once 11:00 UTC has passed, it
records what a buyer at the daily reopen would have got: the first ask after the reopen, the mid at
reopen + 60 minutes and the mid at 11:00 UTC, to data/forward/s1b_paper.csv. Rows come from the
server's tick history, so missed days are back-filled after a restart.

    venv\\Scripts\\python.exe -m gold.live.paper_s1b          # Ctrl+C to stop
"""
from __future__ import annotations

import csv
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from gold.live.forward_s1 import (ENTRY_DELAY, FIRST_DAY, LAST_DAY, SYMBOL, exit_time, server_epoch_to_utc,
                                  trading_day, utc_to_server)

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "forward" / "s1b_paper.csv"
UTC = timezone.utc
H = timedelta(hours=1)
FIELDS = ["trading_day", "reopen_utc", "first_tick_utc", "first_bid", "first_ask", "spread_first",
          "t60_tick_utc", "mid_60", "spread_60", "t11_tick_utc", "mid_11",
          "r_first_hour", "r_rest", "r_total"]


def reopens_by_day(bar_opens_utc: list[datetime]) -> dict[date, datetime]:
    """Trading day -> its reopen (first H1 bar after at least one missing hour), labelled as in S1."""
    out = {}
    for prev, cur in zip(bar_opens_utc, bar_opens_utc[1:]):
        if cur - prev >= 2 * H:
            out[trading_day(cur + ENTRY_DELAY)] = cur
    return out


def make_row(day: date, reopen: datetime, first: dict, at60: dict, at11: dict) -> dict:
    """first / at60 / at11: ticks as {"time": UTC datetime, "bid": float, "ask": float}."""
    mid = lambda t: (t["bid"] + t["ask"]) / 2
    return {"trading_day": str(day), "reopen_utc": reopen.isoformat(),
            "first_tick_utc": first["time"].isoformat(), "first_bid": first["bid"], "first_ask": first["ask"],
            "spread_first": first["ask"] - first["bid"], "t60_tick_utc": at60["time"].isoformat(),
            "mid_60": mid(at60), "spread_60": at60["ask"] - at60["bid"], "t11_tick_utc": at11["time"].isoformat(),
            "mid_11": mid(at11), "r_first_hour": math.log(mid(at60) / first["ask"]),
            "r_rest": math.log(mid(at11) / mid(at60)), "r_total": math.log(mid(at11) / first["ask"])}


def due_days(done: set[str], now: datetime) -> list[date]:
    """Weekdays of the period whose 11:00 UTC has passed and that have no row yet."""
    out, d = [], FIRST_DAY
    while d <= LAST_DAY and exit_time(d) <= now:
        if d.weekday() < 5 and str(d) not in done:
            out.append(d)
        d += timedelta(days=1)
    return out


class PaperS1b:
    def __init__(self, mt5, out: Path = OUT):
        self.mt5, self.out = mt5, out

    def _ticks(self, a: datetime, b: datetime) -> list[dict]:
        t = self.mt5.copy_ticks_range(SYMBOL, utc_to_server(a), utc_to_server(b), self.mt5.COPY_TICKS_ALL)
        rows = []
        for x in ([] if t is None else t):
            if float(x["bid"]) > 0 and float(x["ask"]) >= float(x["bid"]):
                ms = int(x["time_msc"])
                ts = server_epoch_to_utc(ms // 1000) + timedelta(milliseconds=ms % 1000)
                if a <= ts <= b:
                    rows.append({"time": ts, "bid": float(x["bid"]), "ask": float(x["ask"])})
        return rows

    def done(self) -> set[str]:
        if not self.out.exists():
            return set()
        with self.out.open(encoding="utf-8") as fh:
            return {r["trading_day"] for r in csv.DictReader(fh)}

    def step(self, now: datetime) -> int:
        days = due_days(self.done(), now)
        if not days:
            return 0
        start = datetime.combine(days[0] - timedelta(days=4), datetime.min.time(), UTC)
        r = self.mt5.copy_rates_range(SYMBOL, self.mt5.TIMEFRAME_H1, utc_to_server(start), utc_to_server(now))
        opens = [server_epoch_to_utc(int(b["time"])) for b in ([] if r is None else r)]
        reopens = reopens_by_day(opens)
        written = 0
        for d in days:
            reopen = reopens.get(d)
            if reopen is None:
                continue                               # no session that day (holiday) or bars not yet synced
            first = self._ticks(reopen, reopen + H)
            at60 = self._ticks(reopen, reopen + ENTRY_DELAY)
            at11 = self._ticks(exit_time(d) - H, exit_time(d))
            if not first or not at60 or not at11:
                continue
            row = make_row(d, reopen, first[0], at60[-1], at11[-1])
            self.out.parent.mkdir(parents=True, exist_ok=True)
            new = not self.out.exists()
            with self.out.open("a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
            written += 1
            print(f"{d} S1b paper: first ask {row['first_ask']} (spread {row['spread_first']:.2f}), "
                  f"r_first_hour {1e4 * row['r_first_hour']:+.1f}e-4, r_total {1e4 * row['r_total']:+.1f}e-4", flush=True)
        return written


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 not reachable: {mt5.last_error()}")
        return 1
    logger = PaperS1b(mt5)
    print("S1b paper logger running (read-only, no orders); Ctrl+C to stop", flush=True)
    try:
        while True:
            now = datetime.now(UTC)
            try:
                logger.step(now)
            except Exception as exc:                  # keep logging; rows are back-filled later
                print(f"{now:%Y-%m-%d %H:%M} ERROR {type(exc).__name__}: {exc}", flush=True)
            if exit_time(LAST_DAY) < now - timedelta(days=1):
                return 0
            time.sleep(60)
    except KeyboardInterrupt:
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
