"""Structural summary of the discovery scan.

Selection is by STRUCTURE, never by magnitude or maximum t. The score is fixed
here before any result is inspected:

    score = mean|rho| x horizon_consistency x (0.5 + 0.5*half_consistency)
            x quarter_consistency

  rho                   Spearman correlation between quintile rank (1..5) and
                        the quintile's diff_C -- monotonicity.
  horizon_consistency   fraction of {30m,1h,2h} whose Q5-Q1 spread carries the
                        modal sign.
  half_consistency      1 if the 1h Q5-Q1 spread has the same sign in H1 and H2.
  quarter_consistency   fraction of Q1..Q4 whose 1h spread carries that sign.

Gated on >=100 effective blocks in every quintile. Magnitude is reported but
never enters the score.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _spearman(y) -> float:
    """Spearman rho of y against its own position index. No scipy dependency.

    Pearson correlation on ranks; ties get average ranks.
    """
    y = np.asarray(y, float)
    if len(y) < 3 or not np.isfinite(y).all():
        return float("nan")
    x = np.arange(len(y), dtype=float)
    ry = pd.Series(y).rank().to_numpy()
    xs, ys = x - x.mean(), ry - ry.mean()
    den = np.sqrt((xs ** 2).sum() * (ys ** 2).sum())
    return float(xs.dot(ys) / den) if den > 0 else float("nan")


V = Path(sys.argv[1])
d = json.loads((V / "discovery.json").read_text())
df = pd.DataFrame(d["rows"])
PRIMARY = ("30m", "1h", "2h")

FAMILY = {}
for f in df.feature.unique():
    if f.startswith("disp_"):
        FAMILY[f] = "A directional displacement"
    elif f.startswith(("atr", "rng")):
        FAMILY[f] = "B volatility state"
    elif f.startswith(("pos_", "dist_")):
        FAMILY[f] = "C range position"
    elif f in ("body_ratio", "upper_wick_ratio", "lower_wick_ratio", "close_loc",
               "up_frac_6", "up_frac_12", "alt_freq_12", "consec_same"):
        FAMILY[f] = "D candle/path structure"
    elif f in ("utc_hour", "session_bucket", "mins_since_open"):
        FAMILY[f] = "E session/time"
    else:
        FAMILY[f] = "F interaction"


def spread_and_rho(sub, col="diff_C"):
    s = sub.sort_values("quintile")
    v = s[col].to_numpy(float)
    if len(v) < 3 or not np.isfinite(v).all():
        return None, None
    rho = _spearman(v)
    return float(v[-1] - v[0]), (float(rho) if np.isfinite(rho) else None)


out = []
for feat, g in df.groupby("feature"):
    full = g[g.segment == "FULL"]
    rhos, spreads, minblocks = [], {}, []
    for hlab in PRIMARY:
        sub = full[full.horizon == hlab]
        if sub.empty:
            continue
        sp, rho = spread_and_rho(sub)
        if rho is not None:
            rhos.append(abs(rho))
            spreads[hlab] = sp
        minblocks.append(int(sub.blocks.min()))
    if not rhos or not spreads:
        continue
    signs = [np.sign(v) for v in spreads.values() if v is not None]
    modal = np.sign(np.sum(signs)) if signs else 0
    hc = float(np.mean([s == modal for s in signs])) if signs and modal != 0 else 0.0

    def seg_spread(tag):
        sub = g[(g.segment == tag) & (g.horizon == "1h")]
        return spread_and_rho(sub)[0] if not sub.empty else None

    sH1, sH2 = seg_spread("H1"), seg_spread("H2")
    half = 1.0 if (sH1 is not None and sH2 is not None
                   and np.sign(sH1) == np.sign(sH2) == modal) else 0.0
    qs = [seg_spread(f"Q{i+1}") for i in range(4)]
    qc = float(np.mean([q is not None and np.sign(q) == modal for q in qs]))
    score = float(np.mean(rhos) * hc * (0.5 + 0.5 * half) * qc)
    mb = min(minblocks) if minblocks else 0
    # race monotonicity as an independent structural check
    r1h = full[full.horizon == "1h"].sort_values("quintile")
    rr = r1h["race_up_pct"].to_numpy(float)
    race_rho = _spearman(rr) if len(rr) >= 3 else float('nan')
    race_rho = None if not np.isfinite(race_rho) else float(race_rho)
    out.append({
        "feature": feat, "family": FAMILY[feat], "min_blocks": mb,
        "mean_abs_rho": float(np.mean(rhos)), "horizon_consistency": hc,
        "half_consistency": half, "quarter_consistency": qc, "score": score,
        "spread_30m": spreads.get("30m"), "spread_1h": spreads.get("1h"),
        "spread_2h": spreads.get("2h"), "spread_H1": sH1, "spread_H2": sH2,
        "quarter_spreads": qs, "race_rho": race_rho,
        "disp_family": bool(g.disp_family.iloc[0]),
        "max_abs_tC": float(np.nanmax(np.abs(
            full[full.horizon.isin(PRIMARY)]["t_C"].to_numpy(float)))),
    })

res = pd.DataFrame(out).sort_values("score", ascending=False)
res.to_json(V / "structure.json", orient="records", indent=2)

pd.set_option("display.width", 200)
print("STRUCTURAL SUMMARY -- ranked by structure, never by magnitude")
print(f"{'feature':<22} {'family':<27} {'blk':>5} {'|rho|':>6} {'hz':>5} {'hf':>4} "
      f"{'qt':>5} {'SCORE':>6} {'sp30m':>7} {'sp1h':>7} {'sp2h':>7} {'raceR':>6} {'|tC|':>5}")
for _, r in res.iterrows():
    gate = "" if r.min_blocks >= 100 else "  <100blk"
    print(f"{r.feature:<22} {r.family:<27} {r.min_blocks:>5} {r.mean_abs_rho:>6.2f} "
          f"{r.horizon_consistency:>5.2f} {r.half_consistency:>4.0f} {r.quarter_consistency:>5.2f} "
          f"{r.score:>6.3f} "
          f"{(r.spread_30m if r.spread_30m is not None else float('nan')):>7.3f} "
          f"{(r.spread_1h if r.spread_1h is not None else float('nan')):>7.3f} "
          f"{(r.spread_2h if r.spread_2h is not None else float('nan')):>7.3f} "
          f"{(r.race_rho if r.race_rho is not None else float('nan')):>6.2f} "
          f"{r.max_abs_tC:>5.2f}{gate}")

print("\nBY FAMILY -- median structural score")
fam = res.groupby("family").agg(n=("feature", "size"), med_score=("score", "median"),
                                max_score=("score", "max"),
                                med_rho=("mean_abs_rho", "median"))
print(fam.to_string())
