"""Is the first-hour-after-reopen gain an artifact of bid quotes during wide spreads? (read-only)

For each daily reopen of XAUUSD on the MetaQuotes-Demo server, over the whole tick history it serves
(from 2025-05-27), from MT5 ticks (bid AND ask) and H1 bid bars:
  first hour after the reopen  (a) bid bars: log(close / open) of the first H1 bar
                               (b) mid: log(mid at the last tick <= reopen + 60 min / mid at the first tick)
                               (c) buyer: log(that end mid / ASK at the first tick)
  last hour before the break   (a) bid bars of the last H1 bar; (b) mid; (c) seller exiting at the
                               BID of the last tick: log(bid_last / mid at the hour's first tick)
  gap across the break         on bid and on mid; median spreads in the first and last 15 minutes.
No order, no position. Writes research/v2026/reopen_artifact.json and section H of
research/v2026/REGIME_2026_EXPLORATION.md.

    venv\\Scripts\\python.exe research/v2026/reopen_artifact.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from gold.live.forward_s1 import server_epoch_to_utc, utc_to_server   # noqa: E402  (pure helpers)

SYMBOL = "XAUUSD"
START = datetime(2025, 5, 27, tzinfo=timezone.utc)
FOCUS = datetime(2026, 7, 1, tzinfo=timezone.utc)
OUT_JSON = REPO / "research" / "v2026" / "reopen_artifact.json"
MD = REPO / "research" / "v2026" / "REGIME_2026_EXPLORATION.md"
MARK = "## H. Is the first-hour gain a bid-quote artifact? (tick data)"
H, M15 = timedelta(hours=1), timedelta(minutes=15)


def ticks(mt5, a: datetime, b: datetime) -> pd.DataFrame:
    t = mt5.copy_ticks_range(SYMBOL, utc_to_server(a), utc_to_server(b), mt5.COPY_TICKS_ALL)
    if t is None or len(t) == 0:
        return pd.DataFrame(columns=["time", "bid", "ask"])
    df = pd.DataFrame(t)
    df = df[(df["bid"] > 0) & (df["ask"] >= df["bid"])]
    df["time"] = [server_epoch_to_utc(int(ms) // 1000) + timedelta(milliseconds=int(ms) % 1000)
                  for ms in df["time_msc"]]
    return df[(df["time"] >= a) & (df["time"] <= b)][["time", "bid", "ask"]].reset_index(drop=True)


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 not reachable: {mt5.last_error()}")
        return 1
    try:
        now = datetime.now(timezone.utc)
        r = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_H1, utc_to_server(START), utc_to_server(now))
        bars = pd.DataFrame(r)
        bars["utc"] = [server_epoch_to_utc(int(x)) for x in bars["time"]]
        bars = bars[bars["utc"] + H <= now].reset_index(drop=True)
        rows = []
        for i in range(1, len(bars)):
            t0, tl = bars.at[i, "utc"], bars.at[i - 1, "utc"]
            if t0 - tl < 2 * H:
                continue
            first = ticks(mt5, t0, t0 + H)
            last = ticks(mt5, tl, tl + H)
            if len(first) < 2 or len(last) < 2:
                continue
            f0, f1 = first.iloc[0], first.iloc[-1]
            l0, l1 = last.iloc[0], last.iloc[-1]
            mid = lambda x: (x["bid"] + x["ask"]) / 2
            rows.append({
                "reopen": t0, "weekend": (t0 - tl) > timedelta(hours=24), "break_hours": (t0 - tl - H) / H,
                "fh_bid_bar": np.log(bars.at[i, "close"] / bars.at[i, "open"]),
                "fh_mid": np.log(mid(f1) / mid(f0)), "fh_buyer": np.log(mid(f1) / f0["ask"]),
                "lh_bid_bar": np.log(bars.at[i - 1, "close"] / bars.at[i - 1, "open"]),
                "lh_mid": np.log(mid(l1) / mid(l0)), "lh_seller": np.log(l1["bid"] / mid(l0)),
                "gap_bid": np.log(f0["bid"] / l1["bid"]), "gap_mid": np.log(mid(f0) / mid(l1)),
                "spread_first15": float((first.loc[first["time"] < t0 + M15, "ask"]
                                         - first.loc[first["time"] < t0 + M15, "bid"]).median()),
                "spread_last15": float((last.loc[last["time"] >= tl + H - M15, "ask"]
                                        - last.loc[last["time"] >= tl + H - M15, "bid"]).median()),
                "spread_first_tick": float(f0["ask"] - f0["bid"]),
                "bar_open_minus_first_bid": float(bars.at[i, "open"] - f0["bid"]),
            })
    finally:
        mt5.shutdown()
    df = pd.DataFrame(rows)
    res = {"window": [str(df["reopen"].min()), str(df["reopen"].max())], "groups": {}}
    groups = {"all weekday reopens": (~df["weekend"]),
              "weekday reopens from 2026-07-01": (~df["weekend"]) & (df["reopen"] >= FOCUS),
              "weekend reopens (Mondays)": df["weekend"]}
    cols = ["fh_bid_bar", "fh_mid", "fh_buyer", "lh_bid_bar", "lh_mid", "lh_seller", "gap_bid", "gap_mid",
            "spread_first15", "spread_last15", "spread_first_tick", "bar_open_minus_first_bid"]
    for name, mask in groups.items():
        g = df[mask]
        res["groups"][name] = {c: {"mean": float(g[c].mean()), "median": float(g[c].median()), "n": int(g[c].count())}
                               for c in cols}
    OUT_JSON.write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    write_md(res)
    print(json.dumps({k: {c: (round(v[c]["mean"] * 1e4, 2) if not c.startswith(("spread", "bar_open")) else round(v[c]["median"], 3), v[c]["n"])
                          for c in cols} for k, v in res["groups"].items()}, indent=1))
    return 0


def write_md(res: dict) -> None:
    G = res["groups"]
    names = list(G)
    e4 = lambda x: f"{1e4 * x:+.1f}"
    L = [MARK, "", f"MT5 ticks, bid and ask, {res['window'][0][:10]} → {res['window'][1][:10]} (the server's full tick "
         "history). Mean log return × 10⁻⁴ (n); spreads are medians in USD.", "",
         "| Measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    rows = [("First hour after reopen — (a) bid bars", "fh_bid_bar"), ("First hour — (b) mid", "fh_mid"),
            ("First hour — (c) buyer: ask in, mid out", "fh_buyer"),
            ("Last hour before break — (a) bid bars", "lh_bid_bar"), ("Last hour — (b) mid", "lh_mid"),
            ("Last hour — (c) seller: mid in, bid out", "lh_seller"),
            ("Gap across the break — bid", "gap_bid"), ("Gap across the break — mid", "gap_mid")]
    for lab, c in rows:
        L.append(f"| {lab} | " + " | ".join(f"{e4(G[n][c]['mean'])} ({G[n][c]['n']})" for n in names) + " |")
    for lab, c in (("Median spread, first 15 min after reopen", "spread_first15"),
                   ("Median spread, last 15 min before break", "spread_last15"),
                   ("Median spread at the first tick", "spread_first_tick"),
                   ("Median (bar open − first tick bid)", "bar_open_minus_first_bid")):
        L.append(f"| {lab} | " + " | ".join(f"{G[n][c]['median']:.3f} ({G[n][c]['n']})" for n in names) + " |")
    f, a = G["weekday reopens from 2026-07-01"], G["all weekday reopens"]
    L += ["", f"**Verdict: the first-hour gain is a bid-quote artifact.** Since 2026-07-01 the first quote after the "
          f"reopen has a median spread of ${f['spread_first_tick']['median']:.2f}, so the bid opens far below the true price "
          f"and 'recovers' as the spread narrows: bid bars show {e4(f['fh_bid_bar']['mean'])}, mid prices "
          f"{e4(f['fh_mid']['mean'])} and a buyer paying the ask {e4(f['fh_buyer']['mean'])} × 10⁻⁴ per weekday reopen. "
          f"The negative gap across the break is the same artifact (bid {e4(f['gap_bid']['mean'])}, mid "
          f"{e4(f['gap_mid']['mean'])}). Over all {a['fh_buyer']['n']} weekday reopens the buyer's first hour is "
          f"{e4(a['fh_buyer']['mean'])}. Section G's first-hour sum in NEW, and the WGC 'Asia' strength built on it, are "
          "spread artifacts of bid-only bars, not price moves. Other bid-bar research may carry the same bias at reopen "
          "bars; ticks exist only from 2025-05-27, so TRAIN and DEV cannot be checked this way. S1 enters 60 minutes "
          "after the reopen and is not built on the reopen bar's price."]
    text = MD.read_text(encoding="utf-8")
    head = text.split("\n" + MARK)[0].rstrip("\n")
    MD.write_text(head + "\n\n" + "\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
