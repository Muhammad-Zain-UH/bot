"""Trading costs in USD per oz and in log-return units (ROADMAP_V2 §5, rule 1).

Spreads and costs are USD per oz; a round turn pays half the spread at entry
and half at exit, scaled by k_cost (broker tick spread / bar spread, from
gold.data.calibrate_cost). Financing is charged on notional per calendar night
held past 17:00 New York.
"""
from __future__ import annotations

import numpy as np

FINANCING_MARKUP = 0.025            # per year, on notional (ROADMAP_V2 §6 financing model)
DAYS_PER_YEAR = 365
SIDES = ("long", "short")


def round_turn_cost_usd(spread_entry_usd, spread_exit_usd, k_cost: float):
    """k_cost x (spread at entry + spread at exit) / 2, USD per oz."""
    return k_cost * (np.asarray(spread_entry_usd, dtype=float)
                     + np.asarray(spread_exit_usd, dtype=float)) / 2


def cost_in_log_units(cost_usd, price_usd):
    """A cost of cost_usd per oz on a price_usd position, as a log return:
    log(1 + cost / price) (= cost / price to first order)."""
    return np.log1p(np.asarray(cost_usd, dtype=float) / np.asarray(price_usd, dtype=float))


def financing_usd(notional_usd, nights, side: str, dff_annual, markup: float = FINANCING_MARKUP):
    """Overnight financing paid, USD. Rates are annual fractions (0.05 = 5 %):
    a long pays dff_annual + markup, a short pays markup, prorated by calendar
    nights / 365."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    rate = (np.asarray(dff_annual, dtype=float) + markup) if side == "long" else markup
    return np.asarray(notional_usd, dtype=float) * rate * np.asarray(nights, dtype=float) / DAYS_PER_YEAR
