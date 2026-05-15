"""Risk management – position sizing, daily limit, consecutive loss pause."""
from __future__ import annotations
import csv
import os
from datetime import datetime, timezone, timedelta
from typing import Any
from utils import log_debug

SESSIONS = {
    "Asian": (0,8), "London": (7,16), "NewYork": (12,21),
    "LondonNewYork": (13,16), "Dead": (21,24), "Closed": None
}
SESSION_SCORE_MULTIPLIERS = {
    "LondonNewYork": 0.75, "London": 0.80, "NewYork": 0.85,
    "Asian": 1.05, "Dead": 1.15, "Closed": 99.0
}
MAX_DAILY_LOSS_PCT = 2.0
RISK_PER_TRADE_PCT = 1.0
MAX_CONSECUTIVE_LOSSES = 3
MIN_LOT = 0.01
MAX_LOT = 1.00
DEFAULT_XAUUSD_VALUE_PER_LOT = 100.0

def get_current_session() -> str:
    hour = datetime.now(timezone.utc).hour
    if 13 <= hour < 16: return "LondonNewYork"
    if 7 <= hour < 13: return "London"
    if 16 <= hour < 21: return "NewYork"
    if 0 <= hour < 7: return "Asian"
    return "Dead"

def get_session_score_threshold(base: float = 4.5) -> float:
    return base * SESSION_SCORE_MULTIPLIERS.get(get_current_session(), 1.0)

def get_daily_pnl_pct(log_file: str = "signal_log.csv") -> float:
    if not os.path.isfile(log_file): return 0.0
    today = datetime.now(timezone.utc).date()
    pnl = 0.0
    try:
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp")
                outcome = (row.get("outcome") or "").strip().upper()
                if not ts or outcome not in ("WIN","LOSS"):
                    continue
                if datetime.fromisoformat(ts).date() != today:
                    continue
                if outcome == "WIN":
                    pnl += RISK_PER_TRADE_PCT * 2
                else:
                    pnl -= RISK_PER_TRADE_PCT
    except Exception as e:
        log_debug(f"Daily P&L error: {e}")
    return pnl

def is_daily_loss_limit_hit(log_file: str = "signal_log.csv") -> tuple[bool, float]:
    pnl = get_daily_pnl_pct(log_file)
    return pnl <= -MAX_DAILY_LOSS_PCT, pnl

def consecutive_losses(log_file: str = "signal_log.csv", max_losses: int = 3) -> tuple[bool, int]:
    if not os.path.isfile(log_file):
        return False, 0
    with open(log_file, "r") as f:
        rows = list(csv.DictReader(f))
    losses = 0
    for row in reversed(rows[-20:]):
        outcome = (row.get("outcome") or "").strip().upper()
        if outcome == "LOSS":
            losses += 1
        else:
            break
    return losses >= max_losses, losses

def calculate_lot_size(account_balance: float, risk_pct: float, stop_distance: float) -> float:
    if account_balance <= 0 or stop_distance <= 0:
        return MIN_LOT
    risk_amount = account_balance * (risk_pct / 100)
    raw_lot = risk_amount / (stop_distance * DEFAULT_XAUUSD_VALUE_PER_LOT)
    return max(MIN_LOT, min(MAX_LOT, round(raw_lot, 2)))

def calculate_dynamic_stop(entry: float, direction: str, atr: float, multiplier: float = 1.5) -> float:
    dist = atr * multiplier
    if direction == "BUY":
        return round(entry - dist, 2)
    else:
        return round(entry + dist, 2)