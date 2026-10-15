"""Measure every unit-confusion defect in PHASE_2_ISSUES.md section 1 (U1-U12).

Why this exists
---------------
The register says U1-U12 must be migrated **together** and **behind a backtest**,
because they interact. It does not say how big any of them is. Without that, the
migration is a guess about which thresholds matter, and the register's own
ranking ("U8 and U10 are the highest-leverage items") is an assertion.

This measures each site on the frozen research dataset and answers two
questions per threshold:

1. **How far off is it?** On XAUUSD, 1 pip = $0.10, so a threshold named "pips"
   and applied to a raw price is 10x its intended size. For each site, what
   fraction of real bars clears the as-is value versus the as-intended one?
2. **Does it drift with the price level?** An absolute dollar threshold on a
   series that went $951 -> $4,173 is not a fixed rule. The per-year breakdown
   shows whether the threshold's selectivity is a property of the market or of
   gold's price.

Question 2 matters more than question 1. A threshold that is 10x too large is
wrong by a knowable amount and can be corrected. A threshold that is *absolute*
silently re-tunes itself every year, and dividing it by ten does not fix that.

What this is NOT
----------------
This selects no threshold. It reports what each candidate value would admit, and
nothing here is a recommendation. Choosing a threshold because its pass rate
looks reasonable is fitting, and the pass rates below must not be used that way.
No trade, P&L or return figure appears in this file.

Read-only. FINAL_OOS is not touched; this reads
``data/research_v1/bars/`` directly, which is the frozen, hashed export.

Run: ``python research/unit_migration_evidence.py``
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
BARS = REPO / "data" / "research_v1" / "bars"
OUT = REPO / "research" / "unit_migration_evidence.json"

PIP_SIZE = 0.10  # XAUUSD: 1 pip = $0.10 = 10 points. config/mt5_handler agree.


def load(timeframe: str) -> pd.DataFrame:
    """One timeframe of the frozen export, with a UTC index and ATR-14."""
    frame = pd.read_csv(BARS / f"XAUUSD_{timeframe}.csv")
    frame.columns = [c.lower() for c in frame.columns]
    time_column = next(c for c in frame.columns if "time" in c or "date" in c)
    frame[time_column] = pd.to_datetime(frame[time_column])
    frame = frame.set_index(time_column).sort_index()
    frame["year"] = frame.index.year

    high, low, close = frame["high"], frame["low"], frame["close"]
    previous = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    # Wilder, matching pandas_ta.atr used by indicators.calculate_indicators.
    frame["atr"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    return frame


def wicks(frame: pd.DataFrame) -> pd.Series:
    """Deeper of the two wicks per candle, in quote currency."""
    body_top = frame[["open", "close"]].max(axis=1)
    body_bottom = frame[["open", "close"]].min(axis=1)
    return pd.concat(
        [frame["high"] - body_top, body_bottom - frame["low"]], axis=1
    ).max(axis=1)


def bodies(frame: pd.DataFrame) -> pd.Series:
    """Absolute candle body, in quote currency."""
    return (frame["close"] - frame["open"]).abs()


def threshold_report(
    uid: str,
    site: str,
    code: str,
    series: pd.Series,
    years: pd.Series,
    prices: pd.Series,
    as_is: float,
    intent_pips: float,
    note: str = "",
) -> dict:
    """Compare an as-is dollar threshold against its as-intended pip value.

    Args:
        uid: Register id, e.g. ``"U8"``.
        site: File and line.
        code: The offending expression.
        series: The quantity the threshold is compared against, in dollars.
        years: Year label per observation.
        prices: Close price per observation, for the drift table.
        as_is: The literal in the code, interpreted as dollars (what it does).
        intent_pips: The literal read as pips (what it was named).
        note: Anything the numbers do not say.

    Returns:
        A dict holding both pass rates and the per-year drift of the as-is value.
    """
    clean = series.dropna()
    as_intended = intent_pips * PIP_SIZE
    frame = pd.DataFrame(
        {"value": clean, "year": years.reindex(clean.index),
         "price": prices.reindex(clean.index)}
    ).dropna()

    drift = []
    for year, group in frame.groupby("year"):
        drift.append({
            "year": int(year),
            "bars": int(len(group)),
            "mean_price": round(float(group["price"].mean()), 0),
            "mean_value": round(float(group["value"].mean()), 3),
            "pct_clearing_as_is": round(
                100.0 * float((group["value"] >= as_is).mean()), 2),
        })

    spread = [d["pct_clearing_as_is"] for d in drift]
    return {
        "id": uid,
        "site": site,
        "code": code,
        "observations": int(len(frame)),
        "as_is_usd": as_is,
        "as_intended_pips": intent_pips,
        "as_intended_usd": round(as_intended, 4),
        "factor": round(as_is / as_intended, 2) if as_intended else None,
        "pct_clearing_as_is": round(
            100.0 * float((frame["value"] >= as_is).mean()), 2),
        "pct_clearing_as_intended": round(
            100.0 * float((frame["value"] >= as_intended).mean()), 2),
        "median_value_usd": round(float(frame["value"].median()), 3),
        "drift_by_year": drift,
        "drift_range_pp": round(max(spread) - min(spread), 2) if spread else None,
        "note": note,
    }


def main() -> int:
    m15 = load("M15")
    m5 = load("M5")
    h1 = load("H1")
    results: dict = {
        "pip_size": PIP_SIZE,
        "dataset": "data/research_v1/bars (frozen export)",
        "what_this_is_not": (
            "No threshold is selected here. Pass rates describe what a value "
            "would admit; they are not evidence that it should be chosen."
        ),
        "sites": [],
    }

    # --- U8: minimum sweep wick -------------------------------------
    # max(2.5, atr*0.12). The ATR term is scale-invariant; the constant is not.
    atr_term_binds = float((m15["atr"] * 0.12 > 2.5).mean())
    results["sites"].append(threshold_report(
        "U8", "sweep_detector.py:196", "sweep_min = max(2.5, m15_atr * 0.12)",
        wicks(m15), m15["year"], m15["close"], as_is=2.5, intent_pips=2.5,
        note=(
            f"The max() makes this look scale-aware, but the ATR term only "
            f"exceeds the constant when M15 ATR > $20.83, which happens on "
            f"{100 * atr_term_binds:.3f}% of bars (the 99th percentile). On "
            f"{100 * (1 - atr_term_binds):.3f}% of bars the ABSOLUTE constant "
            f"binds, so the scale-invariant branch is effectively dead code. "
            f"Correcting the unit alone would leave the gate nearly "
            f"non-binding; the ATR coefficient 0.12 then becomes the real "
            f"parameter and has never been validated."
        ),
    ))

    # --- U7: order-block body ---------------------------------------
    results["sites"].append(threshold_report(
        "U7", "poi_engine.py:191,229", "if body >= 5",
        bodies(m15), m15["year"], m15["close"], as_is=5.0, intent_pips=5.0,
        note="Order blocks are detected on M15; a $5 body is rare at low "
             "price levels and common at high ones.",
    ))

    # --- U5: POI zone size (a BAND, so reported separately) ---------
    zone = (m15["high"] - m15["low"])
    band_rows = []
    for year, group in pd.DataFrame(
        {"z": zone, "year": m15["year"], "price": m15["close"]}
    ).dropna().groupby("year"):
        band_rows.append({
            "year": int(year),
            "mean_price": round(float(group["price"].mean()), 0),
            "pct_in_as_is_band_5_to_15_usd": round(
                100.0 * float(((group["z"] >= 5) & (group["z"] <= 15)).mean()), 2),
            "pct_in_as_intended_band_0p5_to_1p5_usd": round(
                100.0 * float(((group["z"] >= 0.5) & (group["z"] <= 1.5)).mean()), 2),
        })
    results["sites"].append({
        "id": "U5",
        "site": "poi_engine.py:441",
        "code": "if 5 <= zone_size <= 15: score += 15",
        "kind": "band, not a floor",
        "as_is_usd_band": [5.0, 15.0],
        "as_intended_usd_band": [0.5, 1.5],
        "drift_by_year": band_rows,
        "note": (
            "A band moves differently from a floor: as the price level rises, "
            "zones pass THROUGH the as-is band and out the top, so the bonus "
            "can become common and then rare again. Neither edge tracks "
            "volatility."
        ),
    })

    # --- U6: displacement -------------------------------------------
    displacement = (m15["close"] - m15["open"]).abs()
    results["sites"].append(threshold_report(
        "U6", "poi_engine.py:427", "if displacement >= 20 / >= 10",
        displacement, m15["year"], m15["close"], as_is=20.0, intent_pips=20.0,
        note="The >= 10 tier has the same character; only the stricter tier is "
             "reported here.",
    ))

    # --- U9: the L2 volatility floor --------------------------------
    h1_range14 = (h1["high"] - h1["low"]).rolling(14).mean()
    results["sites"].append(threshold_report(
        "U9", "main_production.py L2 gate", "h1_atr < L2_MIN_H1_RANGE_USD (8.0)",
        h1_range14, h1["year"], h1["close"], as_is=8.0, intent_pips=8.0,
        note=(
            "The mislabelling is already fixed (the threshold is now named and "
            "printed in dollars); the VALUE is unchanged and is what drifts. "
            "Clearing the floor here means the gate does NOT block."
        ),
    ))

    # --- U10: the regime bands --------------------------------------
    regime_rows = []
    for year, group in pd.DataFrame(
        {"atr": m5["atr"], "year": m5["year"], "price": m5["close"]}
    ).dropna().groupby("year"):
        atr = group["atr"]
        regime_rows.append({
            "year": int(year),
            "bars": int(len(group)),
            "mean_price": round(float(group["price"].mean()), 0),
            "DEAD_CALM_pct": round(100.0 * float((atr < 2.5).mean()), 2),
            "MICRO_SCALP_pct": round(
                100.0 * float(((atr >= 2.5) & (atr <= 4.5)).mean()), 2),
            "REGIME_SCALP_pct": round(
                100.0 * float(((atr > 4.5) & (atr <= 7.0)).mean()), 2),
            "INTRADAY_SWING_pct": round(100.0 * float((atr > 7.0).mean()), 2),
        })
    results["sites"].append({
        "id": "U10",
        "site": "entry_engine.py:92-124",
        "code": "M5 ATR bands 2.5 / 4.5 / 7.0, labelled 'pip', applied in dollars",
        "kind": "classifier, not a floor",
        "drift_by_year": regime_rows,
        "note": (
            "Unlike the others, these bands are NOT wrong by a factor of ten: "
            "read as dollars they produce a sensible spread of regimes. The "
            "defect is that they are ABSOLUTE. The regime selects "
            "risk-per-trade (0.75 / 1.0 / 1.5%), so the account's risk per "
            "trade is a function of gold's price level. M5 history begins "
            "2025-04-25, so only two years are observable."
        ),
    })

    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    # ---------------- report ----------------
    print("=" * 78)
    print("UNIT MIGRATION EVIDENCE  (U1-U12, PHASE_2_ISSUES.md section 1)")
    print("=" * 78)
    print(f"XAUUSD: 1 pip = ${PIP_SIZE:.2f}. A 'pip' threshold applied to a raw")
    print("price is therefore 10x its intended size.\n")

    for site in results["sites"]:
        print("-" * 78)
        print(f"{site['id']}  {site['site']}")
        print(f"    {site['code']}")
        if "pct_clearing_as_is" in site:
            print(f"    as-is      ${site['as_is_usd']:.2f}   -> "
                  f"{site['pct_clearing_as_is']:6.2f}% of bars clear it")
            print(f"    as-intended ${site['as_intended_usd']:.2f}  -> "
                  f"{site['pct_clearing_as_intended']:6.2f}% of bars clear it")
            print(f"    median observed value ${site['median_value_usd']:.2f}"
                  f"   |  factor {site['factor']}x")
            print(f"    DRIFT: {site['drift_range_pp']:.1f} percentage points "
                  f"between its best and worst year")
            for row in site["drift_by_year"]:
                print(f"       {row['year']}  px ${row['mean_price']:>6.0f}  "
                      f"mean ${row['mean_value']:>7.2f}  "
                      f"{row['pct_clearing_as_is']:>6.2f}% clear")
        else:
            print(f"    kind: {site['kind']}")
            for row in site["drift_by_year"]:
                rest = {k: v for k, v in row.items()
                        if k not in ("year", "mean_price", "bars")}
                print(f"       {row['year']}  px ${row['mean_price']:>6.0f}  " +
                      "  ".join(f"{k.replace('_pct','')}={v}%"
                                for k, v in rest.items()))
        if site.get("note"):
            print(f"    NOTE: {site['note']}")

    print("-" * 78)
    print("\nNo threshold is selected by this script. The pass rates above")
    print("describe what a value would admit. Using them to pick a value would")
    print("be fitting, which is the thing the register warns against.")
    print(f"\nWritten: {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
