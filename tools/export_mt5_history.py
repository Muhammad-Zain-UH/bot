"""Read-only MT5 history exporter.

Dumps historical bars to CSV so the replay engine can consume them without any
dependency on a running terminal. **This is the only module permitted to import
MetaTrader5**, and it is strictly read-only:

* uses ``copy_rates_range``, ``copy_rates_from_pos``, ``symbol_info`` and
  ``symbol_info_tick`` -- nothing else
* references no order, position or trade-action API whatsoever
* asserts ``core.safety.LIVE_TRADING_ENABLED is False`` before doing anything

``tests/execution/test_no_live_execution.py`` enforces all of that by parsing
this file's AST, so the guarantee cannot rot.

Two things this tool must get right
-----------------------------------
**1. Server time is not UTC.** MT5 reports every bar's ``time`` in the *broker
server's* timezone, not UTC. The MetaQuotes-Demo server measured at export time
runs **UTC+3**. Labelling those stamps as UTC would shift the whole dataset three
hours, which would silently corrupt the strategy's session logic -- London, New
York and Asian windows are all defined on UTC hours in ``risk_manager``. So the
measured offset is subtracted to produce true UTC.

A consequence worth stating plainly: the broker's native H4 and D1 bars are
**not** aligned to UTC midnight. A D1 bar opening 00:00 server opens 21:00 UTC.
That is preserved rather than re-cut, because re-cutting would replace real
broker candles with synthetic ones.

**2. The terminal caps a single request.** ``terminal_info().maxbars`` (100,000
here) limits one call, and a request spanning more fails outright with
``Invalid params`` rather than returning a partial result. Requests are therefore
chunked, and the chunks are concatenated and de-duplicated.

Usage::

    python -m tools.export_mt5_history --symbol XAUUSD \\
        --from 2026-06-02 --to 2026-09-17 --out data/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core.safety import assert_live_trading_disabled
from core.types import Timeframe
from data.dataset import BAR_COLUMNS, validate_bars
from data.timeframes import MT5_TIMEFRAME_NAMES

__all__ = [
    "BrokerMetadata",
    "detect_server_utc_offset_hours",
    "export_symbol",
    "fetch_timeframe",
    "main",
]

DEFAULT_TIMEFRAMES = (
    Timeframe.M1, Timeframe.M5, Timeframe.M15,
    Timeframe.H1, Timeframe.H4, Timeframe.D1,
)

# Conservative per-request bar budget, kept below terminal maxbars (100,000).
CHUNK_BARS = 40_000


class BrokerMetadata(dict):
    """Broker symbol specification and session facts, captured at export time."""


def detect_server_utc_offset_hours(mt5_module, symbol: str) -> float:  # noqa: ANN001
    """Measure the broker server's offset from UTC, in hours.

    Compares the latest tick's timestamp -- which MT5 reports in server time --
    against the host's UTC clock. Rounded to the nearest quarter hour, since
    broker offsets are always whole or half hours in practice and the tick may
    be a second or two stale.

    Args:
        mt5_module: The imported ``MetaTrader5`` module.
        symbol: The symbol to take a tick from. Must be one that is actually
            quoting -- an arbitrary symbol from ``symbols_get()`` may have no
            tick at all.

    Returns:
        Offset in hours, e.g. ``3.0`` for a UTC+3 server.

    Raises:
        RuntimeError: If no tick is available to measure against.
    """
    tick = mt5_module.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(
            f"no tick available for {symbol!r}; cannot determine the server timezone"
        )
    server_stamp = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    delta_hours = (server_stamp - datetime.now(timezone.utc)).total_seconds() / 3600.0
    return round(delta_hours * 4.0) / 4.0


def fetch_timeframe(
    mt5_module,  # noqa: ANN001
    symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    server_offset_hours: float,
) -> pd.DataFrame:
    """Fetch one timeframe over ``[start, end)``, chunking around the bar cap.

    Args:
        mt5_module: The imported ``MetaTrader5`` module.
        symbol: Broker symbol.
        start: Inclusive UTC start.
        end: Exclusive UTC end.
        timeframe: Timeframe to fetch.
        server_offset_hours: Server offset from UTC, subtracted from bar stamps.

    Returns:
        A frame with :data:`~data.dataset.BAR_COLUMNS`, timestamps in true UTC,
        sorted and de-duplicated. Empty if the broker has no data for the range.
    """
    constant = getattr(mt5_module, MT5_TIMEFRAME_NAMES[timeframe])
    offset = timedelta(hours=server_offset_hours)

    # Request in server time, because that is the clock MT5 interprets.
    window = timedelta(minutes=timeframe.minutes * CHUNK_BARS)
    collected: list[pd.DataFrame] = []
    cursor = start + offset
    server_end = end + offset

    while cursor < server_end:
        chunk_end = min(cursor + window, server_end)
        rates = mt5_module.copy_rates_range(symbol, constant, cursor, chunk_end)
        if rates is not None and len(rates) > 0:
            collected.append(pd.DataFrame(rates))
        cursor = chunk_end

    if not collected:
        return pd.DataFrame(columns=list(BAR_COLUMNS))

    frame = pd.concat(collected, ignore_index=True)
    # MT5 stamps are server-local; interpret then shift to true UTC.
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True) - offset
    frame = frame[list(BAR_COLUMNS)]
    frame = frame.drop_duplicates(subset="time", keep="first")
    frame = frame.sort_values("time").reset_index(drop=True)
    return frame[(frame["time"] >= pd.Timestamp(start)) & (frame["time"] < pd.Timestamp(end))]


def export_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    out_dir: Path,
    timeframes: tuple[Timeframe, ...] = DEFAULT_TIMEFRAMES,
) -> tuple[dict[Timeframe, Path], BrokerMetadata]:
    """Export historical bars for one symbol, one file per timeframe.

    Args:
        symbol: Broker symbol, e.g. ``"XAUUSD"``.
        start: Inclusive UTC start.
        end: Exclusive UTC end.
        out_dir: Destination directory; created if absent.
        timeframes: Timeframes to export.

    Returns:
        ``(written_paths, broker_metadata)``.

    Raises:
        RuntimeError: If the terminal cannot be initialised or the symbol is
            unavailable. The MT5 error is included verbatim.
    """
    assert_live_trading_disabled()

    import MetaTrader5 as mt5  # imported late so the module loads without it

    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 initialize() failed: {mt5.last_error()}\n"
            f"The terminal must be running and logged into a VALID account."
        )

    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol!r} is not available on this account")
        if not info.visible:
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)

        account = mt5.account_info()
        terminal = mt5.terminal_info()
        server_offset = detect_server_utc_offset_hours(mt5, symbol)

        metadata = BrokerMetadata({
            "symbol": info.name,
            "description": info.description,
            "digits": info.digits,
            "point": info.point,
            "trade_tick_size": info.trade_tick_size,
            "trade_tick_value": info.trade_tick_value,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "currency_base": info.currency_base,
            "currency_profit": info.currency_profit,
            "current_spread_points": info.spread,
            "broker": getattr(account, "company", None),
            "server": getattr(account, "server", None),
            "account_currency": getattr(account, "currency", None),
            "terminal_maxbars": getattr(terminal, "maxbars", None),
            "server_utc_offset_hours": server_offset,
            "server_time_note": (
                "MT5 reports bar times in SERVER time. This export subtracts the "
                "measured offset to produce true UTC. Broker-native H4/D1 bars are "
                "therefore NOT aligned to UTC midnight and are preserved as-is."
            ),
            "exported_utc": datetime.now(timezone.utc).isoformat(),
        })

        print(f"[SPEC] {json.dumps(dict(metadata), indent=2, default=str)}")
        print(f"[TZ]   server offset measured at {server_offset:+.2f}h; converting to UTC")

        out_dir.mkdir(parents=True, exist_ok=True)
        written: dict[Timeframe, Path] = {}

        for timeframe in timeframes:
            frame = fetch_timeframe(mt5, symbol, timeframe, start, end, server_offset)
            if frame.empty:
                print(f"[WARN] {timeframe.value}: no data returned for the range")
                continue

            issues = validate_bars(frame, timeframe)
            if issues:
                # Report rather than repair: a silently cleaned export would hide
                # a broker data problem inside the baseline result.
                print(f"[ERROR] {timeframe.value}: {len(issues)} validation issue(s):")
                for issue in issues[:10]:
                    print(f"          {issue}")
                print(f"[ERROR] {timeframe.value}: NOT written.")
                continue

            target = out_dir / f"{symbol}_{timeframe.value}.csv"
            frame.to_csv(target, index=False)
            written[timeframe] = target
            print(
                f"[OK]   {timeframe.value:3s}: {len(frame):>8,} bars  "
                f"{frame['time'].iloc[0]} -> {frame['time'].iloc[-1]}  -> {target.name}"
            )

        (out_dir / "broker_metadata.json").write_text(
            json.dumps(dict(metadata), indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return written, metadata
    finally:
        mt5.shutdown()


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Export MT5 history to CSV (read-only).")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--from", dest="start", required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--out", default="data/raw", help="output directory")
    arguments = parser.parse_args(argv)

    start = datetime.fromisoformat(arguments.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(arguments.end).replace(tzinfo=timezone.utc)

    try:
        written, _ = export_symbol(arguments.symbol, start, end, Path(arguments.out))
    except RuntimeError as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    if not written:
        print("[FAIL] nothing was exported", file=sys.stderr)
        return 1
    print(f"\n[DONE] exported {len(written)} timeframe(s) to {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
