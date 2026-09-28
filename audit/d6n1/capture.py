"""D-6N-1 decision capture. Read-only use of production analyze_entry."""
import json, sys
import pandas as pd
from core.types import Timeframe
from data.dataset import HistoricalDataset
from data.replay_feed import ReplayFeed
from backtest.clock_patch import frozen_clock
import main_production as mp
import entry_engine

BC={Timeframe.D1:10,Timeframe.H1:60,Timeframe.H4:100,Timeframe.M1:200,Timeframe.M15:50,Timeframe.M5:100}
LIMIT=int(sys.argv[2]) if len(sys.argv)>2 else 0
OUT=sys.argv[1]

ds=HistoricalDataset.from_directory("data/raw","XAUUSD"); feed=ReplayFeed(ds,spread_pips=2.0)
rows=[]
for raw in feed.decision_times(Timeframe.M5,None,None):
    t=pd.Timestamp(raw).to_pydatetime()
    fr={tf:feed.bars(tf,n,t) for tf,n in BC.items()}
    if any(len(f)==0 for f in fr.values()): continue
    price=feed.price_at(t); spread=feed.spread_at(t)
    with frozen_clock(t):
        info=entry_engine.detect_regime(fr[Timeframe.M5],fr[Timeframe.M15],fr[Timeframe.H1],current_spread=spread)
        a=mp.analyze_entry(h4_data=fr[Timeframe.H4],h1_data=fr[Timeframe.H1],m15_data=fr[Timeframe.M15],
                           m5_data=fr[Timeframe.M5],m1_data=fr[Timeframe.M1],daily_data=fr[Timeframe.D1],
                           current_price=price or 0.0, regime_info=info)
    es=a.get("entry_signal") or {}
    b=a.get("layer_1") or {}
    rows.append({
        "t": pd.Timestamp(raw).isoformat(),
        "regime": str(info.get("regime")), "m5_atr": round(float(info.get("m5_atr") or 0),6),
        "tp_ratio": info.get("tp_ratio"), "risk_percent": info.get("risk_percent"),
        "bypass_l3": info.get("bypass_l3"), "bypass_l6": info.get("bypass_l6"),
        "poi_threshold_regime": info.get("poi_threshold"),
        "bias": b.get("bias"), "bias_strength": b.get("bias_strength"),
        "direction": a.get("direction"), "bos_flip": a.get("bos_flip"),
        "style": a.get("candidate_entry_style"),
        "signal": a.get("signal_type"), "blocked": a.get("layer_failed"),
        "passed": a.get("layers_passed") or [], "reason": a.get("fail_reason"),
        "momentum_fallback": a.get("momentum_fallback"),
        "entry_price": es.get("entry_price"), "stop_loss": es.get("stop_loss"),
        "take_profit": es.get("take_profit"), "risk_distance": es.get("risk_distance"),
        "reward_distance": es.get("reward_distance"), "rr": es.get("reward_to_risk_ratio"),
        "quality": es.get("trigger_quality"), "entry_style": es.get("entry_style"),
        "price": round(float(price),6) if price else None,
    })
    if LIMIT and len(rows)>=LIMIT: break
    if len(rows)%2000==0: print(f"  {len(rows)}",flush=True)
json.dump(rows, open(OUT,"w"))
import collections
print("decisions:",len(rows))
print("regime:",dict(sorted(collections.Counter(r["regime"] for r in rows).items())))
print("signal:",dict(sorted(collections.Counter(str(r["signal"]) for r in rows).items())))
print("blocked:",dict(sorted(collections.Counter(str(r["blocked"]) for r in rows).items())))
