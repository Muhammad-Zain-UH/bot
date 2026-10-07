"""Validation (the build fails) and report figures (reported, never fail) for V2.

validate_frame: unique increasing time; high >= max(open, close) and
low <= min(open, close) for bid, ask and mid; ask >= bid on every field; no NaN.
price_sanity: max mid_h in 2011-09 and 2020-08 inside known bands, which catches
a wrong price divisor.
report_figures: bars per year, longest gaps per year (weekends and the
17:00-18:00 New York break excluded), spread_c median and p95 per year and per
New York hour.
"""
from __future__ import annotations

import pandas as pd

from gold.data.build_v2 import COLUMNS, NEW_YORK, OHLC

# (UTC month, lowest allowed max mid_h, highest allowed), USD per oz
PRICE_SANITY_USD = (("2011-09", 1890.0, 1930.0), ("2020-08", 2050.0, 2090.0))
GAPS_PER_YEAR = 5


class DatasetValidationError(RuntimeError):
    """A frame breaks a hard invariant; the build must stop."""


class PriceScaleError(DatasetValidationError):
    """Known historical highs are not where they should be: price scaling is wrong."""


def _first_bad(df: pd.DataFrame, bad: pd.Series) -> str:
    return f"{int(bad.sum())} rows, first at {df.loc[bad, 'time'].iloc[0]}"


def validate_frame(df: pd.DataFrame, tf: str) -> None:
    errors = []
    if list(df.columns) != COLUMNS:
        raise DatasetValidationError(f"{tf}: columns {list(df.columns)} != {COLUMNS}")
    nan = df.isna().any(axis=1)
    if nan.any():
        errors.append(f"NaN: {_first_bad(df, nan)}")
    t = df["time"]
    if t.duplicated().any():
        errors.append(f"duplicate time: {_first_bad(df, t.duplicated())}")
    if not t.is_monotonic_increasing:
        errors.append("time not increasing")
    for side in ("bid", "ask", "mid"):
        o, h, l, c = (df[f"{side}_{f}"] for f in OHLC)
        bad_h = h < pd.concat([o, c], axis=1).max(axis=1)
        bad_l = l > pd.concat([o, c], axis=1).min(axis=1)
        if bad_h.any():
            errors.append(f"{side}_h < max(open, close): {_first_bad(df, bad_h)}")
        if bad_l.any():
            errors.append(f"{side}_l > min(open, close): {_first_bad(df, bad_l)}")
    for f in OHLC:
        crossed = df[f"ask_{f}"] < df[f"bid_{f}"]
        if crossed.any():
            errors.append(f"ask_{f} < bid_{f}: {_first_bad(df, crossed)}")
    if errors:
        raise DatasetValidationError(f"{tf} failed validation:\n  " + "\n  ".join(errors))


def price_sanity(m1: pd.DataFrame) -> dict[str, float]:
    month = m1["time"].dt.strftime("%Y-%m")
    found, errors = {}, []
    for ym, lo, hi in PRICE_SANITY_USD:
        sel = m1.loc[month == ym, "mid_h"]
        if sel.empty:
            errors.append(f"{ym}: no bars")
            continue
        found[ym] = float(sel.max())
        if not lo <= found[ym] <= hi:
            errors.append(f"{ym}: max mid_h {found[ym]:.3f} outside [{lo}, {hi}]")
    if errors:
        raise PriceScaleError("price sanity failed -- check the price scaling:\n  "
                              + "\n  ".join(errors))
    return found


def expected_open(minutes: pd.Series) -> pd.Series:
    """True where the market is normally open: not Fri 17:00 -> Sun 18:00 New York,
    and not the daily 17:00-18:00 New York break."""
    ny = minutes.dt.tz_convert(NEW_YORK)
    dow, hour = ny.dt.dayofweek, ny.dt.hour
    closed = ((dow == 5) | ((dow == 4) & (hour >= 17)) | ((dow == 6) & (hour < 18))
              | (hour == 17))
    return ~closed


def longest_gaps(m1: pd.DataFrame, per_year: int = GAPS_PER_YEAR) -> dict[int, list[dict]]:
    """Per UTC year, the largest runs of normally-open minutes with no bar."""
    t = m1["time"]
    if len(t) < 2:
        return {}
    grid = pd.Series(pd.date_range(t.iloc[0], t.iloc[-1], freq="1min"))
    cum = expected_open(grid).to_numpy().cumsum()
    pos = ((t - t.iloc[0]) // pd.Timedelta(minutes=1)).to_numpy()
    a, b = pos[:-1], pos[1:]
    missing = cum[b - 1] - cum[a]
    gaps = pd.DataFrame({"start": t.iloc[:-1].to_numpy() + pd.Timedelta(minutes=1),
                         "end": t.iloc[1:].to_numpy() - pd.Timedelta(minutes=1),
                         "missing_minutes": missing})
    gaps = gaps[gaps["missing_minutes"] > 0]
    out = {}
    for year, g in gaps.groupby(gaps["start"].dt.year):
        top = g.nlargest(per_year, "missing_minutes")
        out[int(year)] = [{"start_utc": r.start.isoformat(), "end_utc": r.end.isoformat(),
                           "missing_minutes": int(r.missing_minutes)} for r in top.itertuples()]
    return out


def _spread_table(m1: pd.DataFrame, key: pd.Series) -> dict:
    g = m1["spread_c"].groupby(key)
    return {int(k): {"median_usd": float(v.median()), "p95_usd": float(v.quantile(0.95)),
                     "bars": int(v.size)} for k, v in g}


def report_figures(m1: pd.DataFrame) -> dict:
    return {
        "bars_per_year": {int(k): int(v) for k, v in m1.groupby(m1["time"].dt.year).size().items()},
        "longest_gaps_per_year": longest_gaps(m1),
        "spread_c_per_year": _spread_table(m1, m1["time"].dt.year),
        "spread_c_per_ny_hour": _spread_table(m1, m1["time"].dt.tz_convert(NEW_YORK).dt.hour),
    }
