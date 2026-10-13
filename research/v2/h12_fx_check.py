"""H12 step 0 -- independent FX price check (prices only, no strategy returns).

FRED H.10 daily noon buying rates in New York vs the broker D1 closes (17:00 New York) of the
seven USD majors: correlation of Friday-to-Friday weekly log returns over TRAIN_D1 + DEV, from
each symbol's intraday start to the DEV end. Threshold 0.95. FRED values after the DEV end are
dropped before anything is computed; FINAL_OOS broker data is never loaded.

Raw FRED files: data/h12_v1/fred/{ID}.csv (gitignored, write-once); sha256 in the output.

    venv\\Scripts\\python.exe research/v2/h12_fx_check.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from gold.data.build_h12 import FINGERPRINTS                       # noqa: E402
from gold.data.store import load_h12                               # noqa: E402
from research.acquire_cross_asset import fetch                     # noqa: E402

FRED_DIR = REPO / "data" / "h12_v1" / "fred"
OUT = REPO / "research" / "v2" / "h12_fx_check.json"
# FRED series -> broker symbol; all are quoted like the broker pair (no inversion needed)
SERIES = {"DEXUSEU": "EURUSD", "DEXUSUK": "GBPUSD", "DEXJPUS": "USDJPY", "DEXUSAL": "AUDUSD",
          "DEXCAUS": "USDCAD", "DEXSZUS": "USDCHF", "DEXUSNZ": "NZDUSD"}
DEV_END = pd.Timestamp("2025-09-02")
THRESHOLD = 0.95


def fred_series(series_id: str) -> tuple[pd.Series, str]:
    FRED_DIR.mkdir(parents=True, exist_ok=True)
    path = FRED_DIR / f"{series_id}.csv"
    if not path.exists():
        path.write_bytes(fetch(series_id))
    body = path.read_bytes()
    f = pd.read_csv(path)
    s = pd.Series(pd.to_numeric(f.iloc[:, 1], errors="coerce").to_numpy(),
                  index=pd.to_datetime(f.iloc[:, 0])).dropna()
    return s[s.index <= DEV_END], hashlib.sha256(body).hexdigest()


def weekly_log_returns(fridays: pd.Series) -> pd.Series:
    """Friday-to-Friday log returns, only between Fridays exactly 7 days apart."""
    s = fridays[fridays.index.dayofweek == 4].sort_index()
    r = np.log(s).diff()
    gap = s.index.to_series().diff() == pd.Timedelta(days=7)
    return r[gap.to_numpy()]


def main() -> int:
    starts = {k: v["intraday_start"] for k, v in
              json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["symbols"].items()}
    out = {"threshold": THRESHOLD, "dev_end": str(DEV_END.date()), "symbols": {}}
    for sid, sym in SERIES.items():
        fred, sha = fred_series(sid)
        d1 = pd.concat([load_h12(sym, "D1", a) for a in ("TRAIN_D1", "DEV")], ignore_index=True)
        d1 = d1[d1["session"] >= pd.Timestamp(starts[sym])]
        broker = pd.Series(d1["close"].to_numpy(), index=d1["session"])
        rb, rf = weekly_log_returns(broker), weekly_log_returns(fred)
        j = pd.concat([rb.rename("broker"), rf.rename("fred")], axis=1, join="inner").dropna()
        corr = float(j["broker"].corr(j["fred"]))
        out["symbols"][sym] = {"fred_series": sid, "fred_sha256": sha, "weeks": int(len(j)),
                               "first_week": str(j.index[0].date()), "last_week": str(j.index[-1].date()),
                               "weekly_return_corr": round(corr, 4), "pass": corr >= THRESHOLD}
        print(sym, out["symbols"][sym])
    out["all_pass"] = all(v["pass"] for v in out["symbols"].values())
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("ALL PASS" if out["all_pass"] else "BELOW THRESHOLD -- STOP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
