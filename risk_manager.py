"""Risk management — position sizing, session filter, daily loss limit.

Three layers of protection:
  1. Session filter   — block dead hours, raise score threshold in quieter sessions
  2. Daily loss limit — stop trading if daily drawdown exceeds limit
  3. Position sizing  — risk-based lot size, never fixed

None of these require any API calls.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Any

from utils import log_debug

# ---------------------------------------------------------------------------
# Session definitions (UTC hours)
# ---------------------------------------------------------------------------
SESSIONS = {
    "Asian":           (0,  8),    # 00:00–08:00 UTC  quieter but still tradable
    "London":          (7, 16),    # 07:00–16:00 UTC  best quality for gold
    "NewYork":        (12, 21),    # 12:00–21:00 UTC  high volume, US data driven
    "LondonNewYork":  (13, 16),    # 13:00–16:00 UTC  overlap = highest quality
    "Dead":           (21, 24),    # 21:00–24:00 UTC  very low liquidity
}

# Score threshold multipliers per session (RELAXED for profitability)
# Multipliers APPLY TO THRESHOLD, so lower = easier to pass
SESSION_SCORE_MULTIPLIERS = {
    "LondonNewYork": 0.75,   # Best session - most lenient
    "London":        0.80,   # High liquidity
    "NewYork":       0.85,   # Strong participation
    "Asian":         1.05,   # Quieter but still tradeable (was 1.30)
    "Dead":          1.15,   # Don't block, just slightly stricter (was 2.00)
    "Closed":       99.00,   # Weekend - block all signals
}

# Max daily loss as % of starting balance before trading halts
MAX_DAILY_LOSS_PCT = 3.0

# Max risk per trade as % of account balance
RISK_PER_TRADE_PCT = 1.0

# TIER 5: Consecutive loss limit before pause
MAX_CONSECUTIVE_LOSSES = 3

# TIER 5: Asian thin-volume zone flag
ASIAN_THIN_VOLUME_ZONE = (20, 8)  # 8pm-8am UTC = ultra-low volume

# XAUUSD standard contract size:
# 1.00 lot = 100 oz, so a $1.00 move = about $100 P/L per lot.
DEFAULT_XAUUSD_VALUE_PER_LOT = 100.0

# Hard lot size limits
MIN_LOT = 0.01
MAX_LOT = 1.00


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

def is_market_open() -> bool:
    """Return True when the XAUUSD market is open for trading."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    if weekday == 5:
        return False
    if weekday == 6 and hour < 22:
        return False
    if weekday == 4 and hour >= 22:
        return False
    return True


def get_current_session() -> str:
    """Return the name of the currently active trading session."""
    if not is_market_open():
        return "Closed"

    hour = datetime.now(timezone.utc).hour
    if 13 <= hour < 16:
        return "LondonNewYork"
    if 7 <= hour < 13:
        return "London"
    if 16 <= hour < 21:
        return "NewYork"
    if 0 <= hour < 7:
        return "Asian"
    return "Dead"


def get_session_score_threshold(base_threshold: float = 4.5) -> float:
    """Adjust the minimum score threshold based on current session."""
    session = get_current_session()
    multiplier = SESSION_SCORE_MULTIPLIERS.get(session, 1.0)
    adjusted = base_threshold * multiplier
    log_debug(
        f"Session threshold calc | session={session} | "
        f"base_threshold={base_threshold:.2f} | multiplier={multiplier:.2f} | "
        f"adjusted_threshold={adjusted:.2f}"
    )
    return adjusted


def is_good_trading_session() -> tuple[bool, str]:
    """Return (True, session_name) only for active London/NY/Asian trading windows."""
    session = get_current_session()
    if session in {"Closed", "Dead"}:
        return False, session
    return True, session


# ---------------------------------------------------------------------------
# Daily loss limit
# ---------------------------------------------------------------------------

def get_daily_pnl_pct(log_file: str = "signal_log.csv") -> float:
    """Calculate today's P&L % from logged trades with outcomes.

    Reads the signal_log.csv and sums WIN/LOSS outcomes for today.
    Assumes 1:2 R:R — WIN = +1R, LOSS = -1R, RISK_PER_TRADE_PCT per trade.
    """
    if not os.path.isfile(log_file):
        return 0.0

    today = datetime.now(timezone.utc).date()
    pnl_pct = 0.0

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp", "")
                outcome = str(row.get("outcome", "")).strip().upper()
                if not ts or not outcome:
                    continue
                try:
                    trade_date = datetime.fromisoformat(ts).date()
                except Exception:
                    continue
                if trade_date != today:
                    continue
                if outcome == "WIN":
                    pnl_pct += RISK_PER_TRADE_PCT * 2   # 2R reward
                elif outcome == "LOSS":
                    pnl_pct -= RISK_PER_TRADE_PCT        # 1R loss
    except Exception as exc:
        log_debug(f"Daily P&L calculation failed: {exc}")

    return pnl_pct


def is_daily_loss_limit_hit(log_file: str = "signal_log.csv") -> tuple[bool, float]:
    """Check if today's losses exceed the daily limit.

    Returns (limit_hit, current_daily_pnl_pct).
    """
    pnl = get_daily_pnl_pct(log_file)
    hit = pnl <= -MAX_DAILY_LOSS_PCT
    if hit:
        log_debug(
            f"Daily loss limit hit: {pnl:.2f}% <= -{MAX_DAILY_LOSS_PCT}% — "
            "trading halted for the rest of the day."
        )
    return hit, pnl


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def _get_value_per_lot_per_price_unit(symbol: str) -> float:
    """Return account-currency P/L for a 1.0 price move on 1.00 lot."""
    fallback_value = DEFAULT_XAUUSD_VALUE_PER_LOT

    try:
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0) if info else 0.0
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0) if info else 0.0

        if tick_value > 0 and tick_size > 0:
            value_per_lot = tick_value / tick_size
            log_debug(
                f"Lot sizing metadata: {symbol} tick_value={tick_value:.4f} | "
                f"tick_size={tick_size:.4f} | value_per_lot={value_per_lot:.2f}"
            )
            return value_per_lot
    except Exception as exc:
        log_debug(f"MT5 symbol sizing lookup failed for {symbol}: {exc}")

    log_debug(
        f"Using fallback lot value for {symbol}: "
        f"${fallback_value:.2f} per 1.0 price move per lot."
    )
    return fallback_value

def calculate_lot_size(
    account_balance: float,
    risk_pct: float,
    stop_distance: float,
    symbol: str = "XAUUSD",
) -> float:
    """Risk-based position sizing.

    Formula:
        risk_amount = account_balance * (risk_pct / 100)
        lot_size    = risk_amount / (stop_distance * value_per_lot_per_price_unit)

    For XAUUSD:
        stop_distance is in raw price units (e.g. 10.0 = $10.00 move)
        so a $1.00 move = about $100 P/L per lot
        1.00 lot = 100 oz

    Args:
        account_balance: current account balance in USD
        risk_pct:        risk per trade as % of balance
        stop_distance:   distance to stop loss in price units (not pips)
    """
    if account_balance <= 0 or stop_distance <= 0:
        log_debug("Invalid inputs for lot size calculation — using minimum.")
        return MIN_LOT

    risk_amount = account_balance * (risk_pct / 100)
    # stop_distance comes from ATR-based price units, not broker pip counts.
    # Use MT5 tick metadata or the XAUUSD fallback for a full 1.0 price move.
    value_per_lot = _get_value_per_lot_per_price_unit(symbol)
    raw_lot = risk_amount / (stop_distance * value_per_lot)
    lot_size = max(MIN_LOT, min(MAX_LOT, round(raw_lot, 2)))

    log_debug(
        f"Position size: balance={account_balance:.0f} | "
        f"risk={risk_pct}% (${risk_amount:.0f}) | "
        f"symbol={symbol} | "
        f"stop_dist={stop_distance:.2f} | "
        f"value_per_lot={value_per_lot:.2f} | "
        f"lot_size={lot_size}"
    )
    return lot_size


def get_calibration_micro_lot(is_calibration_mode: bool) -> float:
    """Return micro lot size during calibration mode, normal MIN_LOT otherwise.
    
    During calibration (trades < 50), use smallest possible lot (0.01) to minimize
    risk while accumulating the first 50 completed trades needed for confidence
    calibration. This ensures each calibration trade has minimal market impact.
    
    Args:
        is_calibration_mode: True if in calibration mode (trades < 50)
    
    Returns:
        0.01 if calibration mode, else MIN_LOT (same value but semantic clarity)
    """
    if is_calibration_mode:
        log_debug("[CAL MODE] Using micro lot size: 0.01 (smallest safe position)")
        return 0.01
    return MIN_LOT


def get_account_info_mt5() -> dict[str, float]:
    """Safely get MT5 account balance and equity."""
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
        if info:
            return {
                "balance": float(info.balance),
                "equity":  float(info.equity),
                "margin":  float(info.margin),
            }
    except Exception as exc:
        log_debug(f"MT5 account info failed: {exc}")
    return {"balance": 0.0, "equity": 0.0, "margin": 0.0}


def scale_position_size(
    base_lot_size: float,
    confidence: int,
    news_alignment: str,
    risk_level: str,
    gates: dict[str, Any],
    high_impact_news: bool = False,
) -> tuple[float, float, list[str]]:
    """Scale exposure instead of blocking trades when risk overlays disagree."""
    if base_lot_size <= 0:
        return 0.0, 0.0, []

    scale = 1.0
    reasons: list[str] = []
    alignment = str(news_alignment or "neutral").lower()

    if alignment == "contradicts":
        scale *= 0.65
        reasons.append("news contradicts technical bias")
    elif alignment == "neutral":
        scale *= 0.90

    if high_impact_news:
        scale *= 0.80
        reasons.append("high-impact event nearby")
    if gates.get("m15_volume_thin"):
        scale *= 0.90
        reasons.append("thin M15 volume")
    if gates.get("higher_tf_conflict"):
        scale *= 0.85
        reasons.append("higher timeframe conflict")
    if confidence < 65:
        scale *= 0.85
        reasons.append("moderate confidence")
    if risk_level == "High":
        scale *= 0.85
        reasons.append("high risk regime")

    scale = max(0.35, min(1.00, scale))
    scaled_lot = max(MIN_LOT, min(MAX_LOT, round(base_lot_size * scale, 2)))
    log_debug(
        f"Position scaling: base={base_lot_size:.2f} | scale={scale:.2f} | "
        f"lot={scaled_lot:.2f} | reasons={', '.join(reasons) or 'none'}"
    )
    return scaled_lot, scale, reasons


# ---------------------------------------------------------------------------
# Risk summary for logging
# ---------------------------------------------------------------------------

def build_risk_summary(
    signal: str,
    confidence: int,
    trade_levels: dict[str, Any],
    session: str,
    daily_pnl_pct: float,
    lot_size: float,
) -> str:
    """Build a one-line risk summary for the signal log."""
    if signal not in {"BUY", "SELL"}:
        return f"NO TRADE | session={session} | daily_pnl={daily_pnl_pct:+.1f}%"

    entry = trade_levels.get("entry_price")
    sl    = trade_levels.get("stop_loss")
    tp    = trade_levels.get("take_profit")
    rd    = trade_levels.get("risk_distance")

    rr_text = "N/A"
    if rd and rd > 0:
        rr_text = f"1:{(rd * 2 / rd):.1f}"   # always 1:2 by construction

    return (
        f"session={session} | conf={confidence}% | "
        f"lot={lot_size} | RR={rr_text} | "
        f"daily_pnl={daily_pnl_pct:+.1f}%"
    )


# ===== TIER 5: Operational Safeguards =====

def is_asian_thin_volume_zone() -> tuple[bool, str]:
    """TIER 5: Detect Asian zone (20:00-08:00 UTC) with thin volume.
    
    Returns: (is_thin_zone, reason_text)
    """
    now = datetime.now(timezone.utc)
    hour = now.hour
    
    start, end = ASIAN_THIN_VOLUME_ZONE  # (20, 8)
    
    if start <= hour or hour < end:  # 20:00-23:59 or 00:00-07:59
        return True, f"Asian thin-volume zone (UTC {hour}:00). Volatility 5-10 pips only."
    return False, ""


def apply_asian_zone_penalty(confidence: int, volume_ratio: float | None) -> tuple[int, str]:
    """TIER 5: Apply confidence penalty if in Asian zone with thin volume.
    
    Returns: (adjusted_confidence, reason)
    """
    is_thin, reason = is_asian_thin_volume_zone()
    
    if not is_thin:
        return confidence, ""
    
    vol_ratio = volume_ratio or 1.0
    if vol_ratio < 0.5:
        # Ultra-thin Asian zone
        adjusted = max(30, confidence - 15)
        return adjusted, f"Asian zone penalty: {confidence}% -> {adjusted}%"
    elif vol_ratio < 0.7:
        adjusted = max(30, confidence - 10)
        return adjusted, f"Asian zone: volume thin"
    
    return confidence, ""


def check_consecutive_losses(log_file: str = "signal_log.csv") -> tuple[bool, int, str]:
    """TIER 5: Check if MAX_CONSECUTIVE_LOSSES exceeded.
    
    Returns: (limit_hit, consecutive_count, reason)
    """
    if not os.path.isfile(log_file):
        return False, 0, ""
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return False, 0, ""
        
        # Count recent consecutive losses (most recent rows first)
        consecutive = 0
        for row in reversed(rows[-20:]):  # Check last 20 trades
            outcome = str(row.get("outcome", "")).strip().upper()
            if outcome == "LOSS":
                consecutive += 1
            else:
                break  # Stop at first non-loss
        
        hit = consecutive >= MAX_CONSECUTIVE_LOSSES
        reason = f"{consecutive} consecutive LOSSes" if hit else ""
        return hit, consecutive, reason
        
    except Exception as exc:
        log_debug(f"Consecutive loss check failed: {exc}")
        return False, 0, ""


def smart_signal_throttle(
    signal: str,
    confidence: int,
    log_file: str = "signal_log.csv"
) -> tuple[bool, str]:
    """TIER 5: Smart throttle based on recent signal patterns (not forced trades).
    
    Returns: (should_skip_signal, reason)
    """
    if signal not in {"BUY", "SELL"}:
        return False, ""
    
    # Check consecutive losses
    hit, consecutive, _ = check_consecutive_losses(log_file)
    if hit:
        return True, f"Pause after {consecutive} consecutive losses"
    
    # Check for signal streak (4+ same signals in 60 min with low confidence)
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return False, ""
        
        # Count recent same-signal streak
        streak = 0
        recent_confidence_avg = 0.0
        for row in reversed(rows[-10:]):
            row_signal = str(row.get("signal", "")).strip().upper()
            if row_signal == signal:
                streak += 1
                row_conf = float(row.get("confidence", 0) or 0)
                recent_confidence_avg += row_conf
            else:
                break
        
        if streak >= 4:
            recent_confidence_avg /= streak
            if recent_confidence_avg < 55:
                return True, f"Signal streak detected ({streak}x {signal}, avg conf {recent_confidence_avg:.0f}%)"
    
    except Exception as exc:
        log_debug(f"Smart throttle check failed: {exc}")
    
    return False, ""
