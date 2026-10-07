"""D-6N-1 PRE vs POST decision diff. Read-only."""
import json, collections, sys
import pandas as pd
from backtest.clock_patch import frozen_clock
import risk_manager, entry_engine

pre={r["t"]:r for r in json.load(open("audit/d6n1/pre.json"))}
post={r["t"]:r for r in json.load(open("audit/d6n1/post.json"))}
keys=sorted(set(pre)&set(post))
print(f"PRE {len(pre)}  POST {len(post)}  matched {len(keys)}")
assert len(pre)==len(post)==len(keys), "decision sets differ -- replay not comparable"

def cnt(d,f): return dict(sorted(collections.Counter(str(r[f]) for r in d.values()).items()))
print("\n== REGIME ==")
a,b=cnt(pre,"regime"),cnt(post,"regime")
for k in sorted(set(a)|set(b)):
    print(f"  {k:<16} {a.get(k,0):>6} -> {b.get(k,0):>6}   ({b.get(k,0)-a.get(k,0):+d})")
print("\n== REGIME TRANSITIONS (only where changed) ==")
tr=collections.Counter((pre[k]["regime"],post[k]["regime"]) for k in keys if pre[k]["regime"]!=post[k]["regime"])
for (o,n),c in tr.most_common(): print(f"  {o:<16} -> {n:<16} {c:>6}")
print(f"  total regime changes: {sum(tr.values())}")

FIELDS=["regime","tp_ratio","risk_percent","bypass_l3","bypass_l6","poi_threshold_regime",
        "bias","direction","bos_flip","style","signal","blocked","momentum_fallback",
        "entry_price","stop_loss","take_profit","risk_distance","reward_distance","rr",
        "quality","entry_style","passed"]
changed=[k for k in keys if any(pre[k][f]!=post[k][f] for f in FIELDS)]
print(f"\n== CHANGED DECISIONS: {len(changed)}  ({100*len(changed)/len(keys):.2f}%) ==")

print("\n== WHICH FIELDS CHANGED ==")
fc=collections.Counter()
for k in changed:
    for f in FIELDS:
        if pre[k][f]!=post[k][f]: fc[f]+=1
for f,c in fc.most_common(): print(f"  {f:<22}{c:>6}")

def klass(k):
    p,q=pre[k],post[k]
    if p["signal"]!=q["signal"]: return "E: final signal changed"
    if p["blocked"]!=q["blocked"]: return "D: gate outcome changed"
    if p["direction"]!=q["direction"]: return "C: side changed"
    if p["regime"]!=q["regime"] and p["style"]!=q["style"]: return "B: regime + style changed"
    if p["regime"]!=q["regime"]: return "A: regime changed only"
    return "F: other"
print("\n== CHANGE CLASSIFICATION ==")
for k,c in collections.Counter(klass(k) for k in changed).most_common():
    print(f"  {c:>6}  {k}")

def first_div(k):
    p,q=pre[k],post[k]
    if p["regime"]!=q["regime"]: return "L0_REGIME"
    if p["bias"]!=q["bias"]: return "L1_BIAS"
    if p["direction"]!=q["direction"]: return "L2_SIDE"
    pa,qa=p["passed"],q["passed"]
    for i in range(max(len(pa),len(qa))):
        x=pa[i] if i<len(pa) else None; y=qa[i] if i<len(qa) else None
        if x!=y: return f"passed[{i}] {x} -> {y}"
    if p["blocked"]!=q["blocked"]: return f"blocked {p['blocked']} -> {q['blocked']}"
    return "downstream-only"
print("\n== FIRST DIVERGENCE POINT ==")
for k,c in collections.Counter(first_div(k) for k in changed).most_common(12):
    print(f"  {c:>6}  {k}")

print("\n== BLOCKED-AT DISTRIBUTION ==")
a,b=cnt(pre,"blocked"),cnt(post,"blocked")
for k in sorted(set(a)|set(b)):
    print(f"  {k:<18} {a.get(k,0):>6} -> {b.get(k,0):>6}   ({b.get(k,0)-a.get(k,0):+d})")

print("\n== FINAL SIGNALS ==")
ps=[k for k in keys if pre[k]["signal"]=="ENTRY_SIGNAL"]
qs=[k for k in keys if post[k]["signal"]=="ENTRY_SIGNAL"]
print(f"  PRE {len(ps)}   POST {len(qs)}   delta {len(qs)-len(ps):+d}")
print(f"  removed: {sorted(set(ps)-set(qs))}")
print(f"  added  : {sorted(set(qs)-set(ps))}")
for k in sorted(set(qs)-set(ps)):
    q=post[k]
    print(f"    {k} regime={q['regime']} side={q['direction']} style={q['entry_style']} "
          f"rr={q['rr']} quality={q['quality']} risk={q['risk_distance']}")

print("\n== SESSION SAFETY: session/kill-zone of every POST signal ==")
for k in qs:
    t=pd.Timestamp(k).to_pydatetime()
    with frozen_clock(t):
        s=risk_manager.get_current_session(); kz=entry_engine._within_kill_zone()
    print(f"    {k} session={s} kill_zone={kz} regime={post[k]['regime']}")

print("\n== SESSION SAFETY: did any Dead/Closed decision become a signal? ==")
bad=[]
for k in qs:
    t=pd.Timestamp(k).to_pydatetime()
    with frozen_clock(t):
        s=risk_manager.get_current_session()
    if s in ("Dead","Closed"): bad.append((k,s))
print(f"    signals in Dead/Closed: {len(bad)} {bad}")

print("\n== REGIME MIX BY SESSION, PRE -> POST ==")
sess={}
for k in keys:
    t=pd.Timestamp(k).to_pydatetime()
    with frozen_clock(t): sess[k]=risk_manager.get_current_session()
for s in sorted(set(sess.values())):
    ks=[k for k in keys if sess[k]==s]
    pa=collections.Counter(pre[k]["regime"] for k in ks); pb=collections.Counter(post[k]["regime"] for k in ks)
    line=" ".join(f"{g}:{pa[g]}->{pb[g]}" for g in ("DEAD_CALM","MICRO_SCALP","REGIME_SCALP","INTRADAY_SWING"))
    print(f"  {s:<9} n={len(ks):<6} {line}")
