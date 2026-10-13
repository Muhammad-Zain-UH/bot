"""Breadth feasibility from MT5 metadata and bar history only -- no strategy returns,
no P&L, no Sharpe for any instrument (a later multi-asset hypothesis must stay blind).

Universe: the broker's Indexes, Metals and Forex groups. Forex is limited to majors and
crosses (both currencies in USD, EUR, JPY, GBP, CHF, AUD, NZD, CAD). The broker offers no
energy, agricultural or bond symbols.

Volatility: the 252 daily log returns of the last 253 D1 closes on or before server date
2025-09-01 (the 2025-09-02 bar already overlaps FINAL_OOS), annualised with the bars per
year measured over that span.

Account size: equal risk at 10 % annual volatility over N symbols, per-symbol target vol =
E x 0.10 / sqrt(N); lots = target vol / (sigma x lot notional). A symbol is tradable at E if
lots >= 2 x volume_min, so E_i(N) = 2 x volume_min x lot notional x sigma x sqrt(N) / 0.10.

    venv\\Scripts\\python.exe research/v2/breadth_feasibility.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT_CSV = REPO / "research" / "v2" / "breadth_metadata.csv"
OUT_JSON = REPO / "research" / "v2" / "breadth_feasibility.json"
GROUPS = {"Indexes": "index", "Metals": "metal", "Forex": "fx"}
MAJORS = ("USD", "EUR", "JPY", "GBP", "CHF", "AUD", "NZD", "CAD")
HISTORY_CUTOFF = datetime(2010, 1, 1, tzinfo=timezone.utc)
VOL_END_SERVER = datetime(2025, 9, 1, 23, 59, tzinfo=timezone.utc)   # server wall time
VOL_RETURNS = 252
PORTFOLIO_VOL = 0.10
MIN_LOTS_MULTIPLE = 2
N_TARGETS = (10, 15, 20, 25)
SWAP_COST_FLAG = 0.05
NIGHTS_PER_YEAR = 365        # approximation: weekday charges plus the triple-swap day
TRADE_MODE_FULL = 4
SWAP_MODE_NAMES = {0: "disabled", 1: "points", 2: "base currency", 3: "margin currency",
                   4: "deposit currency", 5: "interest (current price)", 6: "interest (open price)"}


def in_universe(s) -> str | None:
    group = s.path.split(chr(92))[0]
    cat = GROUPS.get(group)
    if cat == "fx" and not (len(s.name) == 6 and s.name[:3] in MAJORS and s.name[3:] in MAJORS):
        return None
    return cat


RETRIES = 6
RETRY_PAUSE_S = 2.0
HISTORY_FROM = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _retry(fn):
    """MT5 answers empty while it is still downloading history or the first quote."""
    for _ in range(RETRIES):
        out = fn()
        if out is not None and (not hasattr(out, "__len__") or len(out)):
            return out
        time.sleep(RETRY_PAUSE_S)
    return None


def first_bar(mt5, name: str, tf) -> str | None:
    now = datetime.now(timezone.utc)
    r = _retry(lambda: mt5.copy_rates_range(name, tf, HISTORY_FROM, now))
    if r is None:
        return None
    return datetime.fromtimestamp(int(r["time"].min()), tz=timezone.utc).date().isoformat()


def live_bid(mt5, name: str) -> float | None:
    tick = _retry(lambda: (lambda t: t if t is not None and t.bid > 0 else None)(mt5.symbol_info_tick(name)))
    return float(tick.bid) if tick is not None else None


def usd_per(mt5, ccy: str) -> float | None:
    """USD value of one unit of ccy, from current FX bids."""
    if ccy == "USD":
        return 1.0
    for pair, invert in ((f"{ccy}USD", False), (f"USD{ccy}", True)):
        if mt5.symbol_info(pair) is None:
            continue
        mt5.symbol_select(pair, True)
        bid = live_bid(mt5, pair)
        if bid:
            return 1 / bid if invert else bid
    return None


def annual_vol(mt5, name: str, tf) -> float | None:
    r = _retry(lambda: mt5.copy_rates_from(name, tf, VOL_END_SERVER, VOL_RETURNS + 1))
    if r is None or len(r) < VOL_RETURNS + 1:
        return None
    lr = np.diff(np.log(r["close"].astype(float)))
    span_years = (int(r["time"][-1]) - int(r["time"][0])) / 86400 / 365.25
    return float(lr.std(ddof=1) * math.sqrt(len(lr) / span_years))


def lot_values(mt5, s, price: float) -> tuple[float | None, float | None]:
    """(USD notional of 1 lot, USD value of a 1-point move on 1 lot), from MT5's own
    profit calculator (no order is sent). trade_tick_value is not used: for the CFD-mode
    metals this broker reports it 10x too small (XAUUSD 0.1 instead of 1.0 per 0.01)."""
    one_pct = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, s.name, 1.0, price, price * 1.01)
    hundred_pts = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, s.name, 1.0, price, price + 100 * s.point)
    if not one_pct or not hundred_pts:
        return None, None
    return one_pct / 0.01, hundred_pts / 100


def swap_annual(mt5, s, lot_notional_usd: float | None,
                per_point_usd: float | None) -> tuple[float | None, float | None]:
    """(long, short) swap as an annual fraction of notional; negative = cost."""
    if not lot_notional_usd:
        return None, None
    if s.swap_mode == 1:                       # points per lot per night
        f = per_point_usd * NIGHTS_PER_YEAR / lot_notional_usd
    elif s.swap_mode in (2, 3):                # base / margin currency per lot per night
        ccy = s.currency_base if s.swap_mode == 2 else s.currency_margin
        rate = usd_per(mt5, ccy)
        if rate is None:
            return None, None
        f = rate * NIGHTS_PER_YEAR / lot_notional_usd
    elif s.swap_mode in (5, 6):                # annual percent of price
        return s.swap_long / 100, s.swap_short / 100
    else:
        return None, None
    return s.swap_long * f, s.swap_short * f


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 not reachable: {mt5.last_error()}")
        return 1
    try:
        rows = []
        for s in mt5.symbols_get():
            cat = in_universe(s)
            if cat is None:
                continue
            mt5.symbol_select(s.name, True)
            price = live_bid(mt5, s.name) if s.trade_mode == TRADE_MODE_FULL else None
            s = mt5.symbol_info(s.name)
            lot_usd, per_point = lot_values(mt5, s, price) if price else (None, None)
            sl, ss = swap_annual(mt5, s, lot_usd, per_point)
            d1_first = first_bar(mt5, s.name, mt5.TIMEFRAME_D1)
            sigma = annual_vol(mt5, s.name, mt5.TIMEFRAME_D1)
            rows.append({
                "symbol": s.name, "category": cat, "description": s.description,
                "contract_size": s.trade_contract_size, "volume_min": s.volume_min,
                "volume_step": s.volume_step, "tick_value_usd": s.trade_tick_value,
                "tick_size": s.trade_tick_size, "margin_currency": s.currency_margin,
                "spread_points": s.spread, "spread_bp": (s.spread * s.point / price * 1e4) if price else None,
                "swap_mode": SWAP_MODE_NAMES.get(s.swap_mode, str(s.swap_mode)),
                "swap_long_annual": sl, "swap_short_annual": ss, "trade_mode": s.trade_mode,
                "d1_first": d1_first, "h4_first": first_bar(mt5, s.name, mt5.TIMEFRAME_H4),
                "lot_notional_usd": lot_usd, "sigma_annual": sigma,
            })
    finally:
        mt5.shutdown()

    for r in rows:
        r["kept"] = bool(r["trade_mode"] == TRADE_MODE_FULL and r["d1_first"]
                         and r["d1_first"] <= HISTORY_CUTOFF.date().isoformat()
                         and r["sigma_annual"] and r["lot_notional_usd"])
        worst = min(x for x in (r["swap_long_annual"], r["swap_short_annual"], 0.0) if x is not None)
        r["swap_cost_flag"] = bool(worst < -SWAP_COST_FLAG)
        r["unit_cost_usd"] = (MIN_LOTS_MULTIPLE * r["volume_min"] * r["lot_notional_usd"] * r["sigma_annual"]
                              if r["kept"] else None)
    kept = sorted((r for r in rows if r["kept"]), key=lambda r: r["unit_cost_usd"])
    sizes = {}
    for n in N_TARGETS:
        if len(kept) < n:
            sizes[n] = {"reachable": False, "kept_symbols": len(kept)}
            continue
        e = kept[n - 1]["unit_cost_usd"] * math.sqrt(n) / PORTFOLIO_VOL
        sizes[n] = {"reachable": True, "min_equity_usd": e, "symbols": [r["symbol"] for r in kept[:n]]}

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["category"], r["symbol"])))
    summary = {"universe": len(rows), "kept": len(kept),
               "by_category": {c: {"offered": sum(r["category"] == c for r in rows),
                                   "full_trading": sum(r["category"] == c and r["trade_mode"] == TRADE_MODE_FULL for r in rows),
                                   "kept": sum(r["category"] == c and r["kept"] for r in rows)}
                               for c in GROUPS.values()},
               "account_sizes": sizes,
               "swap_cost_flags": [r["symbol"] for r in rows if r["swap_cost_flag"] and r["trade_mode"] == TRADE_MODE_FULL]}
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
