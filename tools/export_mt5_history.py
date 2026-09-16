"""Read-only MT5 history exporter.

Dumps historical bars to CSV so the replay engine can consume them without any
dependency on a running terminal. **This is the only module in Phase 2A
permitted to import MetaTrader5**, and it is strictly read-only:

* uses ``copy_rates_range`` and ``symbol_info`` and nothing else
* references no order, position or trade-action API whatsoever
* asserts ``core.safety.LIVE_TRADING_ENABLED is False`` before doing anything

``tests/execution/test_no_live_execution.py`` enforces all of that by parsing
this file's AST, so the guarantee cannot rot.

Current status in this environment
----------------------------------
``mt5.initialize()`` fails with ``(-6, 'Authorization failed')``. The terminal
log reports::

    'MetaQuotes-Demo' ... authorization ... failed (Invalid account)

The terminal itself holds cached XAUUSD history for 2004-2026
(``bases/MetaQuotes-Demo/history/XAUUSD/*.hcc``, ~413 MB), which becomes
readable through this tool as soon as the terminal is logged into a valid
account. The ``.hcc`` files are a proprietary format and are **not** parsed
here -- an undocumented, version-fragile parser could mis-read data silently,
and a corrupted baseline is worse than no baseline.

Usage::

    python -m tools.export_mt5_history --symbol XAUUSD \\
        --from 2024-01-01 --to 2025-01-01 --out data/raw
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.safety import assert_live_trading_disabled
from core.types import Timeframe
from data.dataset import BAR_COLUMNS, validate_bars
from data.timeframes import MT5_TIMEFRAME_NAMES

__all__ = ["export_symbol", "main"]

DEFAULT_TIMEFRAMES = (
    Timeframe.M1, Timeframe.M5, Timeframe.M15,
    Timeframe.H1, Timeframe.H4, Timeframe.D1,
)


def export_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    out_dir: Path,
    timeframes: tuple[Timeframe, ...] = DEFAULT_TIMEFRAMES,
) -> dict[Timeframe, Path]:
    """Export historical bars for one symbol, one file per timeframe.

    Args:
        symbol: Broker symbol, e.g. ``"XAUUSD"``.
        start: Inclusive UTC start.
        end: Exclusive UTC end.
        out_dir: Destination directory; created if absent.
        timeframes: Timeframes to export.

    Returns:
        Mapping of timeframe to the file written.

    Raises:
        RuntimeError: If the terminal cannot be initialised, or the symbol is
            unavailable. The MT5 error is included verbatim -- an authorization
            failure needs to be seen, not summarised.
    """
    assert_live_trading_disabled()

    import MetaTrader5 as mt5  # imported late so the module loads without it

    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 initialize() failed: {mt5.last_error()}\n"
            f"The terminal must be running and logged into a VALID account. "
            f"A cached history is not readable while authorization is failing."
        )

    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol!r} is not available on this account")
        if not info.visible:
            mt5.symbol_select(symbol, True)

        print(
            f"[SPEC] {symbol}: digits={info.digits} point={info.point} "
            f"tick_size={info.trade_tick_size} tick_value={info.trade_tick_value} "
            f"contract_size={info.trade_contract_size}"
        )
        print(
            "[SPEC] Record these in a SymbolSpecification. Note that pip_size is "
            "NOT reported by MT5 and must be stated explicitly (XAUUSD: 0.10)."
        )

        out_dir.mkdir(parents=True, exist_ok=True)
        written: dict[Timeframe, Path] = {}

        for timeframe in timeframes:
            constant = getattr(mt5, MT5_TIMEFRAME_NAMES[timeframe])
            rates = mt5.copy_rates_range(symbol, constant, start, end)
            if rates is None or len(rates) == 0:
                print(f"[WARN] {timeframe.value}: no data returned for the range")
                continue

            frame = pd.DataFrame(rates)
            frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
            frame = frame[list(BAR_COLUMNS)].dropna().reset_index(drop=True)

            issues = validate_bars(frame, timeframe)
            if issues:
                # Report rather than repair: a silently cleaned export would
                # hide a broker data problem inside the backtest result.
                print(f"[ERROR] {timeframe.value}: {len(issues)} validation issue(s):")
                for issue in issues[:10]:
                    print(f"          {issue}")
                print(f"[ERROR] {timeframe.value}: NOT written.")
                continue

            target = out_dir / f"{symbol}_{timeframe.value}.csv"
            frame.to_csv(target, index=False)
            written[timeframe] = target
            print(
                f"[OK]   {timeframe.value}: {len(frame):>8,} bars  "
                f"{frame['time'].iloc[0]} -> {frame['time'].iloc[-1]}  -> {target.name}"
            )

        return written
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
        written = export_symbol(arguments.symbol, start, end, Path(arguments.out))
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
