"""Index CFDs at the broker: metadata and bar history only (no returns, P&L or Sharpe).

For each index CFD: trade_mode, first D1/H4 bar, contract size, volume_min/step, current
spread, swaps as annual % of notional. Then the account-size check of
breadth_feasibility.py for FX + metals + the indices whose D1 history starts on or before
2010-01-01, as if indices were enabled. Price: live bid, else the last D1 close.

    venv\\Scripts\\python.exe research/v2/breadth_indices.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "v2"))
import breadth_feasibility as bf                                    # noqa: E402

OUT_CSV = REPO / "research" / "v2" / "breadth_indices.csv"
OUT_JSON = REPO / "research" / "v2" / "breadth_indices.json"
TRADE_MODES = {0: "disabled", 1: "long only", 2: "short only", 3: "close only", 4: "full"}


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 not reachable: {mt5.last_error()}")
        return 1
    try:
        rows = []
        for s in mt5.symbols_get():
            if bf.in_universe(s) != "index":
                continue
            mt5.symbol_select(s.name, True)
            price, source = bf.live_bid(mt5, s.name), "live bid"
            if not price:
                bars = mt5.copy_rates_from_pos(s.name, mt5.TIMEFRAME_D1, 0, 1)
                price, source = (float(bars["close"][-1]), "last D1 close") if bars is not None and len(bars) else (None, None)
            s = mt5.symbol_info(s.name)
            lot_usd, per_point = bf.lot_values(mt5, s, price) if price else (None, None)
            sl, ss = bf.swap_annual(mt5, s, lot_usd, per_point)
            rows.append({
                "symbol": s.name, "description": s.description, "trade_mode": s.trade_mode,
                "trade_mode_meaning": TRADE_MODES.get(s.trade_mode, "?"),
                "d1_first": bf.first_bar(mt5, s.name, mt5.TIMEFRAME_D1),
                "h4_first": bf.first_bar(mt5, s.name, mt5.TIMEFRAME_H4),
                "contract_size": s.trade_contract_size, "volume_min": s.volume_min,
                "volume_step": s.volume_step, "margin_currency": s.currency_margin,
                "price": price, "price_source": source, "spread_points": s.spread,
                "spread_bp": (s.spread * s.point / price * 1e4) if price else None,
                "swap_mode": bf.SWAP_MODE_NAMES.get(s.swap_mode, str(s.swap_mode)),
                "swap_long_raw": s.swap_long, "swap_short_raw": s.swap_short,
                "swap_long_annual": sl, "swap_short_annual": ss,
                "lot_notional_usd": lot_usd, "sigma_annual": bf.annual_vol(mt5, s.name, mt5.TIMEFRAME_D1),
            })
    finally:
        mt5.shutdown()

    cutoff = bf.HISTORY_CUTOFF.date().isoformat()
    units = []
    with (REPO / "research" / "v2" / "breadth_metadata.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["kept"] == "True":
                units.append((r["symbol"], float(r["unit_cost_usd"])))
    for r in rows:
        r["history_ok"] = bool(r["d1_first"] and r["d1_first"] <= cutoff)
        if r["history_ok"] and r["lot_notional_usd"] and r["sigma_annual"]:
            r["unit_cost_usd"] = bf.MIN_LOTS_MULTIPLE * r["volume_min"] * r["lot_notional_usd"] * r["sigma_annual"]
            units.append((r["symbol"], r["unit_cost_usd"]))
        else:
            r["unit_cost_usd"] = None
    units.sort(key=lambda x: x[1])
    sizes = {}
    for n in (*bf.N_TARGETS, len(units)):
        if len(units) >= n:
            sizes[n] = {"min_equity_usd": units[n - 1][1] * math.sqrt(n) / bf.PORTFOLIO_VOL,
                        "symbols": [u[0] for u in units[:n]]}
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["symbol"]))
    summary = {"indices": len(rows), "history_ok": [r["symbol"] for r in rows if r["history_ok"]],
               "trade_modes": {m: sum(r["trade_mode"] == m for r in rows) for m in sorted({r["trade_mode"] for r in rows})},
               "universe_if_enabled": len(units), "account_sizes": sizes,
               "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
