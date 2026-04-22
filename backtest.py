"""Automatic backtest engine — fills in trade outcomes from MT5 historical data.

Run this separately (not during live trading):
    python backtest.py

It reads signal_log.csv, fetches M1 candles from MT5 starting from each
signal timestamp, determines whether SL or TP was hit first, and writes
the outcome back into the CSV.

After running, open signal_log.csv in Excel to analyze:
  - Win rate by session, confidence band, volume class, sentiment score
  - Average R achieved
  - Best/worst conditions
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from confidence_calibrator import get_calibration_status
from utils import log_debug

LOG_FILE   = os.getenv("SIGNAL_LOG_FILE", "signal_log.csv")
SYMBOL     = "XAUUSD"
BARS_AHEAD = 120   # Look 120 M1 bars (2 hours) ahead for SL/TP hit


def _connect() -> bool:
    try:
        if not mt5.initialize():
            log_debug(f"MT5 init failed: {mt5.last_error()}")
            return False
        return True
    except Exception as exc:
        log_debug(f"MT5 connection error: {exc}")
        return False


def _get_candles_after(timestamp: datetime, bars: int = BARS_AHEAD) -> pd.DataFrame | None:
    """Fetch M1 candles starting from a specific timestamp."""
    try:
        rates = mt5.copy_rates_from(
            SYMBOL,
            mt5.TIMEFRAME_M1,
            timestamp,
            bars,
        )
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df
    except Exception as exc:
        log_debug(f"Candle fetch failed for {timestamp}: {exc}")
        return None


def _evaluate_trade(
    candles: pd.DataFrame,
    signal: str,
    entry: float,
    sl: float,
    tp: float,
) -> tuple[str, float | None, float | None]:
    """Walk through candles and return outcome, exit price, and realized PnL."""
    for _, row in candles.iterrows():
        high = float(row["high"])
        low = float(row["low"])

        if signal == "SELL":
            if high >= sl:
                return "LOSS", sl, entry - sl
            if low <= tp:
                return "WIN", tp, entry - tp
        elif signal == "BUY":
            if low <= sl:
                return "LOSS", sl, sl - entry
            if high >= tp:
                return "WIN", tp, tp - entry

    if candles.empty:
        return "OPEN", None, None

    last_close = float(candles.iloc[-1]["close"])
    pnl = (last_close - entry) if signal == "BUY" else (entry - last_close)
    return "OPEN", last_close, pnl


def _safe_float(value: str) -> float | None:
    try:
        v = float(value)
        return v if v == v else None   # NaN check
    except Exception:
        return None


def run_backtest(log_file: str = LOG_FILE) -> None:
    """Main backtest loop — reads CSV, evaluates outcomes, writes results."""
    if not os.path.isfile(log_file):
        log_debug(f"Signal log not found: {log_file}")
        return

    try:
        # Read all rows
        with open(log_file, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            log_debug("Signal log is empty.")
            return

        updated   = 0
        skipped   = 0
        evaluated = 0

        for row in rows:
            # Skip if outcome already filled in
            existing = str(row.get("outcome", "")).strip().upper()
            if existing in {"WIN", "LOSS", "SKIP", "MISSED"}:
                skipped += 1
                continue

            signal = str(row.get("signal", "")).strip().upper()
            if signal not in {"BUY", "SELL"}:
                continue   # WAIT / NO TRADE rows have nothing to evaluate yet

            # Parse required fields
            ts_str = row.get("timestamp", "")
            entry  = _safe_float(row.get("entry_price", ""))
            sl     = _safe_float(row.get("stop_loss", ""))
            tp     = _safe_float(row.get("take_profit", ""))

            if not ts_str or entry is None or sl is None or tp is None:
                log_debug(f"Skipping row with missing fields: {ts_str}")
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                continue

            # Fetch candles starting from signal time
            candles = _get_candles_after(ts, bars=BARS_AHEAD)
            if candles is None or candles.empty:
                log_debug(f"No historical data for {ts_str} — skipping.")
                continue

            outcome, exit_price, pnl = _evaluate_trade(candles, signal, entry, sl, tp)
            row["outcome"] = outcome
            row["actual_exit_price"] = "" if exit_price is None else f"{exit_price:.2f}"

            if pnl is not None:
                row["actual_pnl_pips"] = f"{pnl:.2f}"

            evaluated += 1
            status_icon = "✓" if outcome == "WIN" else ("✗" if outcome == "LOSS" else "~")
            log_debug(
                f"  {status_icon} [{ts_str[:16]}] {signal} @ {entry:.2f} → "
                f"{outcome} | SL={sl:.2f} TP={tp:.2f}"
            )

        # Write updated CSV
        if evaluated > 0:
            fieldnames = list(rows[0].keys())
            # Add any new fields that might be missing from older logs
            for field in ("actual_exit_price", "actual_pnl_pips"):
                if field not in fieldnames:
                    fieldnames.append(field)

            with open(log_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

            log_debug(f"Backtest complete: {evaluated} evaluated, {skipped} already filled.")
            _print_summary(rows)
        else:
            log_debug(f"No new trades to evaluate (skipped {skipped} already filled).")

    except Exception as exc:
        log_debug(f"Backtest failed: {exc}")
    finally:
        mt5.shutdown()


def _print_summary(rows: list[dict[str, str]]) -> None:
    """Print a quick performance summary to console."""
    signal_counts: dict[str, int] = {}
    for row in rows:
        signal = str(row.get("signal", "")).strip().upper() or "UNKNOWN"
        signal_counts[signal] = signal_counts.get(signal, 0) + 1

    trades = [r for r in rows if r.get("signal") in {"BUY", "SELL"}
              and r.get("outcome") in {"WIN", "LOSS"}]

    print(f"\n{'='*50}")
    print("BACKTEST SUMMARY")
    print(f"{'='*50}")
    print("Signal Mix:")
    for signal, count in sorted(signal_counts.items()):
        print(f"  {signal}: {count}")

    if not trades:
        print("\nNo completed BUY/SELL trades to summarize yet.")
        return

    wins   = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    total  = wins + losses
    wr     = wins / total * 100 if total > 0 else 0
    pnl_values = [float(t.get("actual_pnl_pips") or 0.0) for t in trades]
    gross_profit = sum(v for v in pnl_values if v > 0)
    gross_loss = abs(sum(v for v in pnl_values if v < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    expectancy = sum(pnl_values) / total if total > 0 else 0.0

    print(f"\nCompleted Trades: {total}")
    print(f"Win Rate:  {wins}/{total} = {wr:.1f}%")
    print(f"Wins:      {wins}")
    print(f"Losses:    {losses}")
    print(f"Expectancy: {expectancy:+.2f} price units/trade")
    print(f"Profit Factor: {profit_factor:.2f}" if profit_factor != float("inf") else "Profit Factor: inf")

    # Win rate by confidence band
    bands = [(90, 96), (80, 90), (70, 80), (60, 70), (50, 60)]
    print(f"\nWin Rate by Confidence:")
    for lo, hi in bands:
        band_trades = [t for t in trades
                       if lo <= int(t.get("confidence") or 0) < hi]
        if band_trades:
            band_wins = sum(1 for t in band_trades if t["outcome"] == "WIN")
            print(f"  {lo}-{hi}%: {band_wins}/{len(band_trades)} = "
                  f"{band_wins/len(band_trades)*100:.0f}%")

    # Win rate by session
    print(f"\nWin Rate by Session:")
    sessions = set(t.get("session", "") for t in trades)
    for sess in sorted(sessions):
        sess_trades = [t for t in trades if t.get("session") == sess]
        sess_wins   = sum(1 for t in sess_trades if t["outcome"] == "WIN")
        print(f"  {sess}: {sess_wins}/{len(sess_trades)} = "
              f"{sess_wins/len(sess_trades)*100:.0f}%")

    # Win rate by AI news alignment
    print(f"\nWin Rate by News Alignment:")
    for alignment in ("confirms", "neutral", "contradicts"):
        al_trades = [t for t in trades if t.get("news_alignment") == alignment]
        if al_trades:
            al_wins = sum(1 for t in al_trades if t["outcome"] == "WIN")
            print(f"  {alignment}: {al_wins}/{len(al_trades)} = "
                  f"{al_wins/len(al_trades)*100:.0f}%")

    print(f"\nConfidence Calibration:")
    print(f"  {get_calibration_status(LOG_FILE)}")

    print(f"{'='*50}\n")


if __name__ == "__main__":
    log_debug("Running backtest on signal_log.csv...")
    run_backtest()
