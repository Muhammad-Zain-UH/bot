"""D-6OF-2 counterfactual: what would L3 return with the post-flip bias?
Read-only. Calls production functions; changes nothing."""
import json, collections, os
import pandas as pd
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from backtest.clock_patch import frozen_clock
import entry_engine, bias_engine, structure_engine, pullback_detector, risk_manager
from indicators import calculate_indicators

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "counterfactual.json")
BC = {Timeframe.D1:10, Timeframe.H1:60, Timeframe.H4:100, Timeframe.M15:50, Timeframe.M5:100}
ds = HistoricalDataset.from_directory("data/raw", "XAUUSD")
feed = ReplayFeed(ds, spread_pips=2.0)

rows = []
n = 0
for raw in feed.decision_times(Timeframe.M5, None, None):
    t = pd.Timestamp(raw).to_pydatetime()
    fr = {tf: feed.bars(tf, c, t) for tf, c in BC.items()}
    if any(len(f) == 0 for f in fr.values()):
        continue
    n += 1
    with frozen_clock(t):
        info = entry_engine.detect_regime(fr[Timeframe.M5], fr[Timeframe.M15], fr[Timeframe.H1], current_spread=2.0)
    reg = str(info.get("regime"))
    fast = reg in ("MICRO_SCALP", "REGIME_SCALP")
    if fast:
        b = bias_engine.get_fast_bias(calculate_indicators(fr[Timeframe.H1]) or {}, h1_data=fr[Timeframe.H1])
    else:
        h4i = calculate_indicators(fr[Timeframe.H4]) or {}
        h4i["closes_2"] = [float(v) for v in fr[Timeframe.H4]["close"].tail(2).tolist()]
        b = bias_engine.get_h4_bias(h4i, daily_data=fr[Timeframe.D1], h4_data=fr[Timeframe.H4])
    bias = str(b.get("bias"))
    if bias == "NEUTRAL":
        continue
    side = "BUY" if bias.upper() == "BULLISH" else "SELL"
    st = structure_engine.get_h1_structure(fr[Timeframe.H1], bias)
    if (st or {}).get("structure_type") != "BROKEN":
        continue
    h1c = float(fr[Timeframe.H1].iloc[-1]["close"])
    lh, ll = (st or {}).get("last_swing_high"), (st or {}).get("last_swing_low")
    flipped = None
    if side == "SELL" and lh is not None and h1c > lh: flipped = "BUY"
    elif side == "BUY" and ll is not None and h1c < ll: flipped = "SELL"
    if not flipped:
        continue
    new_bias = "BULLISH" if flipped == "BUY" else "BEARISH"
    rs = structure_engine.get_h1_structure(fr[Timeframe.H1], new_bias)
    if (rs or {}).get("structure_type") not in ("HH/HL", "LH/LL"):
        continue   # rescue failed -> L2 block, not a reversal

    # counterfactual L3: stale bias (MODEL 1, current) vs flipped bias (MODEL 2/3)
    p_stale = pullback_detector.get_m15_pullback(fr[Timeframe.M15], bias)
    p_flip  = pullback_detector.get_m15_pullback(fr[Timeframe.M15], new_bias)
    MIN = 1.5
    def verdict(p):
        return bool(p and p.get("pullback_detected") and float(p.get("pullback_quality", 0)) >= MIN)
    with frozen_clock(t):
        sess = risk_manager.get_current_session()
    rows.append({
        "t": pd.Timestamp(raw).isoformat(), "regime": reg, "session": sess,
        "bias_stale": bias, "bias_flipped": new_bias,
        "side_effective": flipped, "bias_tf": "H1" if fast else "H4",
        "bias_strength": round(float(b.get("bias_strength") or 0.0), 6),
        "bypass_l3": bool(info.get("bypass_l3")),
        "l3_stale_detected": verdict(p_stale), "l3_flip_detected": verdict(p_flip),
        "l3_stale_quality": round(float(p_stale.get("pullback_quality", 0) or 0), 4),
        "l3_flip_quality": round(float(p_flip.get("pullback_quality", 0) or 0), 4),
        "l3_stale_retr": p_stale.get("retracement_ratio"),
        "l3_flip_retr": p_flip.get("retracement_ratio"),
    })
    if len(rows) % 300 == 0:
        print(f"  reversals {len(rows)} / scanned {n}", flush=True)

json.dump(rows, open(OUT, "w"))
print("scanned:", n, " reversals:", len(rows), " ->", OUT)
