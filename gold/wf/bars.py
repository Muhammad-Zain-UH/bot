"""H1 bars with the session map W01 needs (research/v2026/W01_SPEC.md §3-4). Prices USD per oz, bid-based.

A Bars object holds numpy arrays over the H1 bars and the D1 sessions built from H4, plus the indices that
link them: each H1 bar's session, each session's last H1 bar (its D1 close) and the H1 bar that starts
60 minutes after the session's reopen (the D1 entry bar). The reopen bar is the first H1 bar after a gap
of 2 h or more.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gold.data.broker_daily import daily_bars, session_of
from gold.hyp.anchors import NEW_YORK

LONDON = "Europe/London"
REOPEN_GAP = pd.Timedelta(hours=2)
D1_ENTRY_DELAY = pd.Timedelta(minutes=60)
TOKEN = "OPENED-2026-10-14-EXPLORATION"
INCOMPLETE_LAST_BAR = pd.Timestamp("2026-10-01 11:00", tz="UTC")


@dataclass
class Bars:
    h1: pd.DataFrame                      # time (UTC), open, high, low, close, spread_usd (filled)
    d1: pd.DataFrame                      # session (NY close date), open, high, low, close
    t: np.ndarray = field(init=False)
    o: np.ndarray = field(init=False)
    h: np.ndarray = field(init=False)
    l: np.ndarray = field(init=False)
    c: np.ndarray = field(init=False)
    spread: np.ndarray = field(init=False)
    reopen: np.ndarray = field(init=False)
    sess: np.ndarray = field(init=False)          # H1 bar -> D1 row (-1 when its session is not in d1)
    ny_hour: np.ndarray = field(init=False)
    ny_minute: np.ndarray = field(init=False)
    ldn_hour: np.ndarray = field(init=False)
    ny_date: np.ndarray = field(init=False)
    d1_last: np.ndarray = field(init=False)       # D1 row -> its last H1 bar
    d1_entry: np.ndarray = field(init=False)      # D1 row -> H1 bar starting 60 min after its reopen (-1 if none)

    def __post_init__(self):
        h1 = self.h1
        self.t = h1["time"].to_numpy()
        self.o, self.h, self.l, self.c = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.spread = h1["spread_usd"].to_numpy(float)
        gap = h1["time"].diff()
        self.reopen = (gap >= REOPEN_GAP).to_numpy() | (np.arange(len(h1)) == 0)
        ny = h1["time"].dt.tz_convert(NEW_YORK)
        self.ny_hour, self.ny_minute = ny.dt.hour.to_numpy(), ny.dt.minute.to_numpy()
        self.ldn_hour = h1["time"].dt.tz_convert(LONDON).dt.hour.to_numpy()
        self.ny_date = ny.dt.tz_localize(None).dt.normalize().to_numpy()
        row = pd.Series(np.arange(len(self.d1)), index=pd.DatetimeIndex(self.d1["session"]))
        self.sess = row.reindex(session_of(h1["time"])).fillna(-1).astype(int).to_numpy()
        n = len(self.d1)
        self.d1_last = np.full(n, -1)
        self.d1_entry = np.full(n, -1)
        idx = np.arange(len(h1))
        for k, g in pd.Series(idx).groupby(self.sess):
            if k < 0:
                continue
            bars = g.to_numpy()
            self.d1_last[k] = bars[-1]
            first_t = self.t[bars[0]]
            later = bars[self.t[bars] >= first_t + D1_ENTRY_DELAY.to_timedelta64()]
            self.d1_entry[k] = later[0] if len(later) else -1

    @property
    def n(self) -> int:
        return len(self.o)

    def truncate(self, t_end) -> "Bars":
        """The bars as known at t_end: H1 bars opening before t_end, and only the sessions completed before
        it (the session still open at t_end is dropped, since its D1 bar is not yet known)."""
        h1 = self.h1[self.h1["time"] < t_end].reset_index(drop=True)
        last = session_of(h1["time"]).max()
        return Bars(h1, self.d1[self.d1["session"] < last].reset_index(drop=True))


def load() -> Bars:
    """v1b H1 and D1 (from H4) over TRAIN + DEV + FINAL_OOS, the incomplete last bar dropped; zero or missing
    spreads filled with the New York hour's median."""
    from gold.data.store import load_broker_v1b
    from gold.econ.power import filled, hour_median_spread
    arms = ("TRAIN", "DEV", "FINAL_OOS")
    get = lambda tf: pd.concat([load_broker_v1b(tf, a, TOKEN if a == "FINAL_OOS" else None) for a in arms],
                               ignore_index=True).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    h1 = get("H1")
    h1 = h1[h1["time"] < INCOMPLETE_LAST_BAR].reset_index(drop=True)
    h1["spread_usd"] = filled(h1["spread_usd"], h1["time"], hour_median_spread(h1))
    h4 = get("H4")
    h4 = h4[h4["time"] < INCOMPLETE_LAST_BAR].reset_index(drop=True)
    return Bars(h1, daily_bars(h4))


def load_dff() -> pd.Series:
    """Effective fed funds rate, percent, by date (data/cross_asset_v1/raw/DFF.csv)."""
    from gold.data.store import REPO
    f = pd.read_csv(REPO / "data" / "cross_asset_v1" / "raw" / "DFF.csv")
    s = pd.to_numeric(f.iloc[:, 1], errors="coerce")
    return pd.Series(s.to_numpy(), index=pd.to_datetime(f.iloc[:, 0])).dropna().sort_index()
