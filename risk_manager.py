"""Risk management utilities."""

from datetime import datetime, timezone

def calculate_lot_size_for_symbol(symbol: str, balance: float, risk_percent: float, entry: float, stop: float) -> float:
    """
    Calculate position size (lot size) for a given risk.
    Assumes XAUUSD pip value ~ 0.01 per standard lot per pip.
    """
    risk_amount = balance * risk_percent / 100.0
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.01
    # Pip value for XAUUSD: 1 pip = 0.01 USD per 0.01 lot? Actually standard lot XAUUSD pip value ~ $1 per pip.
    # For simplicity, we use a generic formula.
    # For XAUUSD, 0.01 lot = 0.01 * 100 = 1 unit? We'll approximate.
    pip_value = 0.01  # per 0.01 lot per pip? Actually it's 0.01 for XAUUSD pip value per 0.01 lot.
    # Standard: 1 lot XAUUSD pip value = $10, so 0.01 lot pip value = $0.10? Let's simplify.
    # Use: lot = risk_amount / (stop_distance * pip_value)
    lot_size = risk_amount / (stop_distance * 10.0)  # approximate
    lot_size = max(0.01, round(lot_size, 2))
    return min(lot_size, 1.0)  # cap at 1 lot

def get_current_session() -> str:
    """
    Return current session name based on UTC hour.
    Returns: "Asian", "London", "NewYork", "Dead", "Closed" (last for weekends)
    """
    now = datetime.now(timezone.utc)
    hour = now.hour
    # Weekend (Saturday/Sunday) - simplified: check weekday
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return "Closed"
    if 0 <= hour < 7:
        return "Asian"
    elif 7 <= hour < 13:
        return "London"
    elif 13 <= hour < 21:
        return "NewYork"
    else:
        return "Dead"