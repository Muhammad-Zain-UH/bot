"""Risk management utilities."""

from datetime import datetime, timezone

from core.sizing import SizingInputError, lots_for_risk
from core.symbols import SymbolSpecification


def calculate_lot_size_for_symbol(
    symbol: str,
    balance: float,
    risk_percent: float,
    entry: float,
    stop: float,
    *,
    spec: SymbolSpecification,
) -> float:
    """Calculate position size in lots for a given risk.

    Delegates to :func:`core.sizing.lots_for_risk`, which is the single
    implementation of the sizing contract. This function only adapts the
    percentage-based signature the production caller uses.

    ``spec`` is a **required keyword argument with no default**. The previous
    implementation hardcoded ``10.0`` as the money value of a one-dollar move on
    one lot; the terminal's own ``order_calc_profit`` reports ``100.0`` for
    XAUUSD on MetaQuotes-Demo, so every position it sized was ten times the
    intended risk. Instrument economics cannot be assumed -- the caller must
    supply the instrument. See ``docs/SIZING_CONTRACT.md``.

    Args:
        symbol: Symbol name, used only to check it matches ``spec``.
        balance: Account balance in the account currency.
        risk_percent: Risk as a **percentage**, e.g. ``1.0`` for 1 %.
        entry: Intended entry price.
        stop: Original stop price.
        spec: The instrument's specification.

    Returns:
        Lots to trade, floored to the volume step. **``0.0`` when the budget
        cannot buy a tradeable size** -- the caller must check for it rather
        than treating it as a size. A minimum is never substituted, because
        doing so would exceed the risk budget.

    Raises:
        SizingInputError: If an input cannot describe a real position.
        ValueError: If ``symbol`` does not match ``spec.symbol``.
        UnsupportedCalculationModeError: If the instrument's calculation mode
            has no implemented economics.
    """
    if symbol != spec.symbol:
        raise ValueError(
            f"symbol {symbol!r} does not match the supplied specification "
            f"{spec.symbol!r}; sizing must not guess the instrument"
        )
    stop_distance = abs(entry - stop)
    try:
        decision = lots_for_risk(
            spec,
            balance=balance,
            risk_fraction=risk_percent / 100.0,
            stop_distance=stop_distance,
        )
    except SizingInputError:
        raise
    return decision.lots if decision.tradeable else 0.0

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