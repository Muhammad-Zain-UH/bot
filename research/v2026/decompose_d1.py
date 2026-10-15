"""Reconcile the WGC session returns with the D1 returns (descriptive, exploratory).

Each 17:00-New-York D1 session's log return telescopes exactly into:
  gap        previous session's last H1 close -> this session's first H1 open
             (the daily break; on Mondays the weekend);
  first hour first H1 bar after the reopen (open -> close);
  Asia rest  close of that first bar -> close of the bar ending 11:00 UTC;
  Europe     11:00 -> 14:00 UTC;  US  14:00 UTC -> the session's last H1 close.
The residual (D1 return minus the components) must be zero.

Writes research/v2026/decomposition_d1.json and replaces section G of
research/v2026/REGIME_2026_EXPLORATION.md.

    venv\\Scripts\\python.exe research/v2026/decompose_d1.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research" / "v2026"))

import regime_2026 as R                                            # noqa: E402
from gold.data.broker_daily import session_of                      # noqa: E402
from gold.hyp.anchors import NEW_YORK                              # noqa: E402

OUT_JSON = REPO / "research" / "v2026" / "decomposition_d1.json"
MD = REPO / "research" / "v2026" / "REGIME_2026_EXPLORATION.md"
MARK = "## G. Reconciliation of session returns with D1 returns"
COMPONENTS = ("gap", "first_hour", "asia_rest", "europe", "us")


def decompose(h1: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    h1 = h1.copy()
    h1["session"] = session_of(h1["time"]).to_numpy()
    h1 = h1[h1["session"].isin(set(d1["session"]))].sort_values("time")
    rows, prev_close = [], None
    for s, b in h1.groupby("session", sort=True):
        day = pd.Timestamp(s, tz="UTC")
        c11 = b.loc[b["time"] == day + pd.Timedelta(hours=10), "close"]
        c14 = b.loc[b["time"] == day + pd.Timedelta(hours=13), "close"]
        if prev_close is not None and len(c11) and len(c14):
            f = b.iloc[0]
            rows.append({"session": s, "weekend": s.dayofweek == 0,
                         "first_bar_ny_hour": int(f["time"].tz_convert(NEW_YORK).hour),
                         "last_bar_ny_hour": int(b["time"].iloc[-1].tz_convert(NEW_YORK).hour),
                         "gap": np.log(f["open"] / prev_close), "first_hour": np.log(f["close"] / f["open"]),
                         "asia_rest": np.log(c11.iloc[0] / f["close"]), "europe": np.log(c14.iloc[0] / c11.iloc[0]),
                         "us": np.log(b["close"].iloc[-1] / c14.iloc[0])})
        prev_close = b["close"].iloc[-1]
    df = pd.DataFrame(rows)
    df["d1"] = df["session"].map(R.d1_returns(d1))
    df["resid"] = df["d1"] - df[list(COMPONENTS)].sum(axis=1)
    return df


def summarise(df: pd.DataFrame) -> dict:
    out = {"sessions": int(len(df)), "max_abs_residual": float(df["resid"].abs().max()), "components": {}}
    for c in ("d1", *COMPONENTS):
        out["components"][c] = {"sum": float(df[c].sum()), "mean": float(df[c].mean()), "n": int(len(df))}
    for name, mask in (("gap_weekday", ~df["weekend"]), ("gap_weekend", df["weekend"])):
        g = df.loc[mask, "gap"]
        out["components"][name] = {"sum": float(g.sum()), "mean": float(g.mean()), "median": float(g.median()),
                                   "share_neg": float((g < 0).mean()), "n": int(len(g))}
    fh = df.loc[~df["weekend"], "first_hour"]
    out["first_hour_weekday"] = {"mean": float(fh.mean()), "median": float(fh.median()),
                                 "share_pos": float((fh > 0).mean()), "n": int(len(fh))}
    by_m = df.groupby(df["session"].dt.to_period("M"))
    out["monthly"] = [{"month": str(m), "n": int(len(g)), "d1": float(g["d1"].sum()),
                       "gap_weekday": float(g.loc[~g["weekend"], "gap"].sum()),
                       "first_hour": float(g["first_hour"].sum()), "asia_rest": float(g["asia_rest"].sum()),
                       "last_bar_15_ny": int((g["last_bar_ny_hour"] == 15).sum()),
                       "last_bar_16_ny": int((g["last_bar_ny_hour"] == 16).sum())} for m, g in by_m]
    return out


def render(res: dict) -> list[str]:
    N, D = res["NEW"], res["DEV"]
    p = lambda x: f"{100 * x:+.2f}"
    L = [MARK, "",
         f"Exact telescoping of each D1 session (17:00 NY): max |residual| {max(N['max_abs_residual'], D['max_abs_residual']):.1e} — no arithmetic error.",
         "", "| Component (sum, %) | NEW | n | DEV | n |", "|---|---|---|---|---|"]
    labels = {"d1": "D1 return", "gap_weekday": "Gap, daily break (weekdays)", "gap_weekend": "Gap, weekend (Mondays)",
              "first_hour": "First hour after reopen", "asia_rest": "Asia after the first hour (to 11:00 UTC)",
              "europe": "Europe 11–14 UTC", "us": "US 14 UTC → session close"}
    for k, lab in labels.items():
        a, c = N["components"][k], D["components"][k]
        L.append(f"| {lab} | {p(a['sum'])} | {a['n']} | {p(c['sum'])} | {c['n']} |")
    a, c = N["first_hour_weekday"], D["first_hour_weekday"]
    L += ["", f"Weekday first hour after reopen: NEW mean {1e4 * a['mean']:+.1f} × 10⁻⁴ ({100 * a['share_pos']:.0f} % > 0, n {a['n']}); "
          f"DEV {1e4 * c['mean']:+.1f} × 10⁻⁴ ({100 * c['share_pos']:.0f} % > 0, n {c['n']}).", "",
          "| Month (NEW) | n | D1 | Gap (weekdays) | First hour | Asia rest | Sessions ending 15:00 / 16:00 NY bar |",
          "|---|---|---|---|---|---|---|"]
    for m in N["monthly"]:
        L.append(f"| {m['month']} | {m['n']} | {p(m['d1'])} | {p(m['gap_weekday'])} | {p(m['first_hour'])} | {p(m['asia_rest'])} | "
                 f"{m['last_bar_15_ny']} / {m['last_bar_16_ny']} |")
    return L


def main() -> int:
    g = R.gold_frames()
    res = {w: summarise(decompose(g[w]["H1"], g[w]["D1"])) for w in ("NEW", "DEV")}
    OUT_JSON.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    text = MD.read_text(encoding="utf-8")
    head = text.split("\n" + MARK)[0].rstrip("\n")
    MD.write_text(head + "\n\n" + "\n".join(render(res)) + "\n", encoding="utf-8")
    print(json.dumps({w: {k: round(v["sum"] * 100, 2) for k, v in res[w]["components"].items()} for w in res}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
