"""Phase 3 -- window fidelity measurement.

Production does not compute H1 indicators on the full H1 series. It passes
`DEFAULT_BAR_COUNTS[H1] = 60` bars to `calculate_indicators`, so `ema_50` is
seeded by a 50-bar SMA and then advanced only ten steps. A full-series EMA at
the same calendar bar has thousands of steps of decay behind it.

Phase 2 (`research/original_continuation_audit.py:53-54`) computed the L1 bias
from FULL-SERIES EMAs. This script measures how far that is from the production
60-bar window, so Phase 3's choice to call the production functions on
production's own windows is evidenced rather than asserted.

Measurement only. No threshold is chosen and no result is interpreted here.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import load_timeframe              # noqa: E402
from indicators import calculate_indicators                     # noqa: E402
from bias_engine import get_fast_bias                           # noqa: E402
from backtest.replay_engine import DEFAULT_BAR_COUNTS           # noqa: E402
from core.types import Timeframe                                # noqa: E402

N_H1 = DEFAULT_BAR_COUNTS[Timeframe.H1]
N_PROBES = 400
SEED = 20260301

SPLIT = json.loads((Path(__file__).with_name("research_split_manifest.json")).read_text(encoding="utf-8"))
TRAIN_LO = pd.Timestamp(SPLIT["arms"]["TRAIN"]["from_utc"])
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])


def main() -> None:
    h1 = load_timeframe("H1")
    h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)

    # The Phase 2 approach: full-series EMAs.
    e20 = ta.ema(h1["close"], length=20).to_numpy(float)
    e50 = ta.ema(h1["close"], length=50).to_numpy(float)
    atr = ta.atr(h1["high"], h1["low"], h1["close"], length=14).to_numpy(float)
    thr = np.where(np.isfinite(atr) & (atr > 0), np.maximum(2.0, atr * 0.12), 2.0)
    d = e20 - e50
    full_bias = np.where(np.abs(d) < thr, "NEUTRAL", np.where(d > thr, "BULLISH", "BEARISH"))
    full_str = np.where(np.abs(d) < thr, 0.0, np.minimum(10.0, np.abs(d) / thr))

    rng = np.random.default_rng(SEED)
    lo = int(h1["time"].searchsorted(TRAIN_LO))
    idx = np.sort(rng.choice(np.arange(max(lo, N_H1), len(h1)), size=N_PROBES, replace=False))

    rows, mm_bias, mm_str = [], 0, 0
    for i in idx:
        win = h1.iloc[i - (N_H1 - 1): i + 1].reset_index(drop=True)
        assert len(win) == N_H1
        prod = get_fast_bias(calculate_indicators(win), h1_data=win) or {}
        pb, ps = prod.get("bias"), float(prod.get("bias_strength") or 0.0)
        vb, vs = str(full_bias[i]), float(full_str[i])
        mm_bias += (pb != vb)
        mm_str += (abs(ps - vs) > 1e-6)
        rows.append((pb, vb, ps, vs))

    sd = np.array([abs(a - b) for _, _, a, b in rows])
    print("=" * 78)
    print("H1 WINDOW FIDELITY -- production 60-bar window vs full-series EMA")
    print("=" * 78)
    print(f"  H1 bars to the DEV boundary : {len(h1):,}")
    print(f"  probes                      : {len(rows)}  (seed {SEED})")
    print(f"  bias label mismatches       : {mm_bias}  ({100 * mm_bias / len(rows):.1f}%)")
    print(f"  bias strength mismatches    : {mm_str}  ({100 * mm_str / len(rows):.1f}%)")
    print(f"  strength |diff| median      : {np.median(sd):.3f}   p90 {np.percentile(sd, 90):.3f}"
          f"   max {sd.max():.3f}   (0-10 scale)")
    print("\n  confusion  production(60-bar) -> full-series:")
    for (a, b), v in sorted(Counter((a, b) for a, b, _, _ in rows).items()):
        flag = "   <-- outright sign flip" if {a, b} == {"BULLISH", "BEARISH"} else ""
        print(f"    {a:8s} -> {b:8s}  {v:4d}{flag}")
    print("\n  Consequence: Phase 3 calls the production functions on production's own")
    print("  bar windows. A full-series vectorisation is not a faithful substitute.")


if __name__ == "__main__":
    main()
