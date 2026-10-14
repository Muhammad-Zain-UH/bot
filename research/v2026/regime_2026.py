"""Descriptive exploration of the 2025-09-02 -> 2026-10-14 regime vs DEV (2021-2025).

DESCRIPTIVE ONLY: no strategy backtests, no parameter search. FINAL_OOS opened 2026-10-14 by owner
decision (token OPENED-2026-10-14-EXPLORATION); it is no longer a clean validation set.

Data: broker v1b XAUUSD (DEV, FINAL_OOS), H12 XAGUSD/EURUSD/USDJPY/GBPUSD/AUDUSD (DEV, FINAL_OOS),
and data/live_2026q4/b2 from 2026-09-30 21:00 UTC (it replaces the overlapping FINAL_OOS bars,
including v1b's incomplete last gold bar). FRED DGS10, DFII10, DTWEXBGS from data/live_2026q4/fred.

    venv\\Scripts\\python.exe research/v2026/regime_2026.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from gold.data.broker_daily import daily_bars                      # noqa: E402
from gold.data.build_h12 import d1_from_h4                         # noqa: E402
from gold.data.store import load_broker_v1b, load_broker_v1b_d1, load_h12   # noqa: E402
from gold.hyp.anchors import Bars                                  # noqa: E402
from gold.hyp.h15_asia_us import asia_us                           # noqa: E402

TOKEN = "OPENED-2026-10-14-EXPLORATION"
LIVE = REPO / "data" / "live_2026q4" / "b2" / "bars"
FRED = REPO / "data" / "live_2026q4" / "fred"
OUT_JSON = REPO / "research" / "v2026" / "regime_2026.json"
FX = ("XAGUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD")
FOMC = ["2025-09-17", "2025-10-29", "2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29",
        "2026-06-17", "2026-07-29", "2026-09-16"]
ATR_N, BREAK_N, ROLL_N = 14, 20, 60
HORIZONS = (1, 3, 5)


# ---------------------------------------------------------------- data
def _live(sym: str, tf: str) -> pd.DataFrame:
    return pd.read_parquet(LIVE / f"{sym}_{tf}.parquet")


def _splice(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    old = old[old["time"] < new["time"].iloc[0]]
    cols = [c for c in new.columns if c in old.columns]
    return pd.concat([old[cols], new[cols]], ignore_index=True)


def gold_frames() -> dict:
    h1_new = _splice(load_broker_v1b("H1", "FINAL_OOS", TOKEN), _live("XAUUSD", "H1"))
    h4_new = _splice(load_broker_v1b("H4", "FINAL_OOS", TOKEN), _live("XAUUSD", "H4"))
    return {"NEW": {"H1": h1_new, "H4": h4_new, "D1": complete_sessions(daily_bars(h4_new), h4_new)},
            "DEV": {"H1": load_broker_v1b("H1", "DEV"), "H4": load_broker_v1b("H4", "DEV"),
                    "D1": load_broker_v1b_d1("DEV")}}


def fx_frames(sym: str) -> dict:
    h1_new = _splice(load_h12(sym, "H1", "FINAL_OOS", TOKEN), _live(sym, "H1"))
    h4_new = _splice(load_h12(sym, "H4", "FINAL_OOS", TOKEN), _live(sym, "H4"))
    return {"NEW": {"H1": h1_new, "H4": h4_new, "D1": complete_sessions(d1_from_h4(h4_new), h4_new)},
            "DEV": {"H1": load_h12(sym, "H1", "DEV"), "H4": load_h12(sym, "H4", "DEV"),
                    "D1": load_h12(sym, "D1", "DEV")}}


def complete_sessions(d1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    """Sessions that opened after the window start and closed before the last bar ended."""
    close = d1["time"] + pd.Timedelta(days=1)
    last_end = h4["time"].iloc[-1] + pd.Timedelta(hours=4)
    first = h4["time"].iloc[0]
    return d1[(d1["time"] >= first) & (close <= last_end)].reset_index(drop=True)


def fred(series: str) -> pd.Series:
    f = pd.read_csv(FRED / f"{series}.csv")
    return pd.Series(pd.to_numeric(f.iloc[:, 1], errors="coerce").to_numpy(),
                     index=pd.to_datetime(f.iloc[:, 0])).dropna()


# ---------------------------------------------------------------- helpers
def d1_returns(d1: pd.DataFrame) -> pd.Series:
    return pd.Series(np.log(d1["close"]).diff().to_numpy(), index=d1["session"]).dropna()


def h1_returns(h1: pd.DataFrame) -> pd.Series:
    return pd.Series(np.log(h1["close"]).diff().to_numpy(), index=h1["time"]).dropna()


def bars_per_year(index: pd.Index) -> float:
    years = (index[-1] - index[0]).days / 365.25
    return len(index) / years


def monthly_table(d1: pd.DataFrame, h1: pd.DataFrame, with_atr: bool) -> list[dict]:
    r_d = d1_returns(d1)
    r_h = h1_returns(h1)
    bpy = bars_per_year(r_h.index)
    if with_atr:
        prev = d1["close"].shift(1)
        tr = pd.concat([d1["high"] - d1["low"], (d1["high"] - prev).abs(), (d1["low"] - prev).abs()], axis=1).max(axis=1)
        atr = pd.Series(tr.rolling(ATR_N).mean().to_numpy(), index=d1["session"])
    rows = []
    for m, rd in r_d.groupby(r_d.index.to_period("M")):
        rh = r_h[r_h.index.tz_convert(None).to_period("M") == m]
        closes = h1.loc[h1["time"].dt.tz_convert(None).dt.to_period("M") == m, "close"].to_numpy()
        dd = float((1 - closes / np.maximum.accumulate(closes)).max()) if len(closes) else float("nan")
        row = {"month": str(m), "ret": float(rd.sum()), "n_d1": int(len(rd)),
               "vol_ann": float(rh.std(ddof=1) * math.sqrt(bpy)) if len(rh) > 1 else float("nan"),
               "n_h1": int(len(rh)), "max_dd": dd}
        if with_atr:
            a = atr[atr.index.to_period("M") == m].dropna()
            px = d1.set_index("session")["close"][a.index]
            row.update({"atr_usd": float(a.mean()), "atr_pct": float((a / px).mean()), "n_atr": int(len(a))})
        rows.append(row)
    return rows


def stats(x: pd.Series) -> dict:
    x = pd.Series(x).dropna()
    return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None,
            "median": float(x.median()) if len(x) else None,
            "sd": float(x.std(ddof=1)) if len(x) > 1 else None,
            "share_pos": float((x > 0).mean()) if len(x) else None}


def acf(r: pd.Series, lags) -> dict:
    x = r.to_numpy()
    return {int(k): {"rho": float(np.corrcoef(x[:-k], x[k:])[0, 1]), "n": int(len(x) - k)} for k in lags}


def variance_ratio(r: pd.Series, q: int = 5) -> dict:
    x = r.to_numpy()
    rq = pd.Series(x).rolling(q).sum().dropna().to_numpy()
    return {"vr": float(rq.var(ddof=1) / (q * x.var(ddof=1))), "n": int(len(x))}


# ---------------------------------------------------------------- sections
def sessions(h1: pd.DataFrame) -> dict:
    d = asia_us(h1)
    bars = Bars(h1)
    t11 = (d["day"] + pd.Timedelta(hours=11)).dt.tz_localize("UTC").astype("datetime64[ns, UTC]")
    t14 = (d["day"] + pd.Timedelta(hours=14)).dt.tz_localize("UTC").astype("datetime64[ns, UTC]")
    d["r_eu"] = np.log(bars.close_at(t14) / bars.close_at(t11))
    monthly = []
    for m, g in d.groupby(d["day"].dt.to_period("M")):
        monthly.append({"month": str(m), "asia": float(g["r_asia"].sum()), "europe": float(g["r_eu"].sum()),
                        "us": float(g["r_us"].sum()), "n_days": int(len(g))})
    sigma = float(d["r_us"].std(ddof=1))
    nxt = d["r_asia"].shift(-1)
    consecutive = (d["day"].shift(-1) - d["day"]) <= pd.Timedelta(days=4)
    cond = {}
    for name, mask in (("US fell > 1σ", d["r_us"] < -sigma), ("US within ±1σ", d["r_us"].abs() <= sigma),
                       ("US rose > 1σ", d["r_us"] > sigma)):
        cond[name] = stats(nxt[mask & consecutive])
    tot = {k: stats(d[c]) for k, c in (("asia", "r_asia"), ("europe", "r_eu"), ("us", "r_us"))}
    return {"monthly": monthly, "sigma_us": sigma, "next_asia_after_us": cond, "totals": tot}


def breakouts(d1: pd.DataFrame) -> dict:
    c, hi, lo = d1["close"], d1["high"], d1["low"]
    up = c > hi.shift(1).rolling(BREAK_N).max()
    dn = c < lo.shift(1).rolling(BREAK_N).min()
    out = {}
    for name, mask in (("above 20-day high", up), ("below 20-day low", dn)):
        out[name] = {}
        for h in HORIZONS:
            fwd = np.log(c.shift(-h) / c)
            out[name][f"{h}d"] = stats(fwd[mask & fwd.notna()])
    return out


def macro(d1: pd.DataFrame) -> dict:
    g = d1_returns(d1)
    x = pd.DataFrame({"gold": g})
    x["dgs10_bp"] = fred("DGS10").diff().mul(100)
    x["dfii10_bp"] = fred("DFII10").diff().mul(100)
    x["dtwex_log"] = np.log(fred("DTWEXBGS")).diff()
    x = x.dropna()
    out = {"n_days": int(len(x)), "series": {}}
    for col in ("dgs10_bp", "dfii10_bp", "dtwex_log"):
        corr = x["gold"].rolling(ROLL_N).corr(x[col]).dropna()
        beta = (x["gold"].rolling(ROLL_N).cov(x[col]) / x[col].rolling(ROLL_N).var()).dropna()
        full_beta = float(np.cov(x["gold"], x[col])[0, 1] / x[col].var(ddof=1))
        out["series"][col] = {"corr_full": float(x["gold"].corr(x[col])), "beta_full": full_beta,
                              "rolling_corr": {"n": int(len(corr)), "min": float(corr.min()), "median": float(corr.median()),
                                               "max": float(corr.max()), "last": float(corr.iloc[-1])},
                              "rolling_beta_median": float(beta.median())}
    both = (x["dgs10_bp"] > 10) & (x["dtwex_log"] > 0)
    out["dgs10_up_10bp_and_dollar_up"] = stats(x.loc[both, "gold"])
    out["all_days"] = stats(x["gold"])
    return out


def first_fridays(sessions: pd.Series) -> set:
    s = pd.Series(sorted(sessions))
    fr = s[s.dt.dayofweek == 4]
    return set(fr.groupby(fr.dt.to_period("M")).min())


def events(d1: pd.DataFrame, fomc: list[str] | None) -> dict:
    prev = d1["close"].shift(1)
    move = np.log(d1["close"] / prev).abs()
    rng = (d1["high"] - d1["low"]) / prev
    s = d1["session"]
    nfp = s.isin(first_fridays(s))
    fom = s.isin(pd.to_datetime(fomc)) if fomc else pd.Series(False, index=s.index)
    out = {}
    for name, mask in (("FOMC", fom), ("NFP (first Friday)", nfp), ("other days", ~fom & ~nfp)):
        if mask.any():
            out[name] = {"abs_move": stats(move[mask]), "range": stats(rng[mask])}
    return out


def main() -> int:
    gold = gold_frames()
    fx = {s: fx_frames(s) for s in FX}
    res = {"windows": {}, "notes": "descriptive only; FINAL_OOS opened 2026-10-14 (exploratory)"}
    for w in ("NEW", "DEV"):
        G = gold[w]
        res["windows"][w] = {
            "span": {"d1_first": str(G["D1"]["session"].iloc[0].date()), "d1_last": str(G["D1"]["session"].iloc[-1].date()),
                     "n_d1": int(len(G["D1"])), "n_h1": int(len(G["H1"]))},
            "A_gold_monthly": monthly_table(G["D1"], G["H1"], True),
            "B_sessions": sessions(G["H1"]),
            "C_acf_d1": acf(d1_returns(G["D1"]), range(1, 6)),
            "C_acf_h4": acf(h1_returns(G["H4"]), range(1, 7)),
            "C_breakouts": breakouts(G["D1"]),
            "D_macro": macro(G["D1"]),
            "E_events": events(G["D1"], FOMC if w == "NEW" else None),
            "F": {}}
        gr = d1_returns(G["D1"])
        res["windows"][w]["F"]["XAUUSD"] = {"vr5": variance_ratio(gr), "vol_ann": float(gr.std(ddof=1) * math.sqrt(bars_per_year(gr.index)))}
        for s in FX:
            F = fx[s][w]
            r = d1_returns(F["D1"])
            j = pd.concat([gr.rename("g"), r.rename("x")], axis=1, sort=True).dropna()
            j26 = j[j.index >= pd.Timestamp("2026-01-01")]
            res["windows"][w]["F"][s] = {
                "monthly": monthly_table(F["D1"], F["H1"], False) if w == "NEW" else None,
                "vol_ann": float(r.std(ddof=1) * math.sqrt(bars_per_year(r.index))), "n_d1": int(len(r)),
                "corr_gold": {"r": float(j["g"].corr(j["x"])), "n": int(len(j))},
                "corr_gold_2026": ({"r": float(j26["g"].corr(j26["x"])), "n": int(len(j26))} if len(j26) > 2 else None),
                "vr5": variance_ratio(r)}
    OUT_JSON.write_text(json.dumps(res, indent=2, default=float) + "\n", encoding="utf-8")
    print("written", OUT_JSON)
    return 0


if __name__ == "__main__":
    sys.exit(main())
