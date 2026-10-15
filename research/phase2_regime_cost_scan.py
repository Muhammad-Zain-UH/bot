"""PHASE 2A-2E -- regime robustness, cost realism, overlap control.

Scope is fixed: ONLY disp_4_lag1 and disp_8_lag1. No new candidate features, no
threshold search, no trading rule.

Two hard constraints discovered before writing this
---------------------------------------------------
1. **The M15 structure cannot be tested before 2022-06-30.** M15 history begins
   there; the 2009-2014, 2015-2019 and 2020-2022 slices contain ZERO M15 bars.
   Those slices are reported IMPOSSIBLE for the M15 structure, not estimated.
   A separate H1-NATIVE ANALOGUE is run over the long history at matched
   wall-clock horizons, and is labelled an analogue throughout -- it is NOT the
   Phase 1 structure and is not evidence about it, only about the same economic
   hypothesis at coarser resolution.

2. **H1 extends into the FINAL_OOS window.** 6,261 H1 bars fall after the DEV
   boundary. Every H1 series here is truncated at that boundary, so no OOS bar is
   read even for "context".

Spread convention, corrected
----------------------------
Earlier reports in this programme stated a round-turn spread cost of "2 x spread".
That double-counted. With ask = mid + S/2 and bid = mid - S/2, a long entered at
ask and exited at bid pays (ask - bid) = **1 x S** in total. Round-turn spread cost
is therefore 1 x S; slippage adds per side, so total = S + 2 * slip. Both the 1x
and a conservative 2x bound are reported.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))
from dataset_access import load_timeframe, _split

NQ = 5
M15_H = 16                 # 4h horizon in M15 bars
H1_H = 4                   # the same 4h in H1 bars
SPREAD_USD = 0.33          # measured median, 2026-09-24 tick sample
SPREAD_P99 = 0.67
SLIP_FRACTIONS = (0.0, 0.25, 0.5, 1.0)
OUT = Path(__file__).parent / "phase2"
OUT.mkdir(exist_ok=True)

split = _split()
TRAIN_HI = pd.Timestamp(split["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(split["arms"]["DEV"]["from_utc"])
DEV_END = pd.Timestamp(split["arms"]["DEV"]["to_utc"])


def wilder_atr(h, l, c, n=14):
    tr = np.full(len(c), np.nan)
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]),
                                np.abs(l[1:] - c[:-1])])
    atr = np.full(len(c), np.nan)
    if len(c) <= n:
        return atr
    atr[n] = np.nanmean(tr[1:n + 1])
    for i in range(n + 1, len(c)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def lagged_disp(c, atr, w, lag=1):
    out = np.full(len(c), np.nan)
    for i in range(lag + w, len(c)):
        a = atr[i - lag]
        if np.isfinite(a) and a > 0:
            out[i] = (c[i - lag] - c[i - lag - w]) / a
    return out


def block_stats(v, pos, h):
    bm = pd.DataFrame({"b": pos // h, "v": v}).groupby("b")["v"].mean().to_numpy()
    if len(bm) < 2:
        return dict(n_blocks=len(bm), mean=np.nan, se=np.nan, t=np.nan, ci=[None, None])
    m = float(bm.mean())
    se = float(bm.std(ddof=1) / np.sqrt(len(bm)))
    return dict(n_blocks=int(len(bm)), mean=m, se=se,
                t=(m / se if se > 0 else np.nan),
                ci=[m - 1.96 * se, m + 1.96 * se])


def spread_test(y, ok, q, h):
    lo, hi = ok & (q == 0), ok & (q == NQ - 1)
    if lo.sum() < 40 or hi.sum() < 40:
        return None
    a = block_stats(y[lo], np.flatnonzero(lo), h)
    b = block_stats(y[hi], np.flatnonzero(hi), h)
    if not (np.isfinite(a["se"]) and np.isfinite(b["se"])):
        return None
    sp = b["mean"] - a["mean"]
    se = float(np.sqrt(a["se"] ** 2 + b["se"] ** 2))
    return dict(spread=sp, se=se, t=(sp / se if se > 0 else np.nan),
                n_lo=int(lo.sum()), n_hi=int(hi.sum()),
                blocks_lo=a["n_blocks"], blocks_hi=b["n_blocks"],
                ci95=[sp - 1.96 * se, sp + 1.96 * se],
                mean_lo=a["mean"], mean_hi=b["mean"],
                median_lo=float(np.median(y[lo])), median_hi=float(np.median(y[hi])))


def qcut_train(x, train_mask):
    tr = x[train_mask & np.isfinite(x)]
    if len(tr) < 500:
        return np.full(len(x), -1), []
    cuts = np.unique(np.quantile(tr, np.linspace(0, 1, NQ + 1)[1:-1]))
    b = np.full(len(x), -1)
    ok = np.isfinite(x)
    b[ok] = np.searchsorted(cuts, x[ok], side="right")
    return b, [float(v) for v in cuts]


# ====================================================================== loading
m15 = load_timeframe("M15")
h1 = load_timeframe("H1")
m15 = m15[m15["time"] <= DEV_END].reset_index(drop=True)
h1 = h1[h1["time"] <= DEV_END].reset_index(drop=True)
assert m15["time"].max() <= DEV_END and h1["time"].max() <= DEV_END

mc = m15["close"].to_numpy(float)
m_atr = wilder_atr(m15["high"].to_numpy(float), m15["low"].to_numpy(float), mc)
mt = m15["time"]
hc = h1["close"].to_numpy(float)
h_atr = wilder_atr(h1["high"].to_numpy(float), h1["low"].to_numpy(float), hc)
h_ma50 = pd.Series(hc).rolling(50).mean().to_numpy(float)
h_regime = np.where(np.isfinite(h_atr) & (h_atr > 0), (hc - h_ma50) / h_atr, np.nan)
ht = h1["time"]

# M15 forward label and signals
m_y = np.full(len(mc), np.nan)
m_y[: len(mc) - M15_H] = (mc[M15_H:] - mc[: len(mc) - M15_H]) / m_atr[: len(mc) - M15_H]
m_y_usd = np.full(len(mc), np.nan)
m_y_usd[: len(mc) - M15_H] = mc[M15_H:] - mc[: len(mc) - M15_H]
SIG = {"disp_4_lag1": lagged_disp(mc, m_atr, 4, 1),
       "disp_8_lag1": lagged_disp(mc, m_atr, 8, 1)}
IS_TRAIN = (mt <= TRAIN_HI).to_numpy()
IS_DEV = ((mt >= DEV_LO) & (mt <= DEV_END)).to_numpy()
BASE_OK = np.isfinite(m_y) & np.isfinite(m_atr) & (m_atr > 0)

# map each M15 bar to the H1 regime of the last CLOSED H1 bar
h1_close_t = (ht + pd.Timedelta(hours=1)).to_numpy("datetime64[ns]")
m15_close_t = (mt + pd.Timedelta(minutes=15)).to_numpy("datetime64[ns]")
j = np.searchsorted(h1_close_t, m15_close_t, side="right") - 1
m_reg = np.where(j >= 50, h_regime[np.clip(j, 0, len(h_regime) - 1)], np.nan)

results: dict = {
    "provenance": {
        "dataset_sha256": json.loads(
            (REPO / "research" / "accessible_bar_dataset_fingerprints.json").read_text()
        )["dataset_sha256"],
        "split_manifest_token": split["oos_authorisation_token"],
        "FINAL_OOS_LOCKED": split["FINAL_OOS_LOCKED"],
        "train_end": str(TRAIN_HI), "dev_start": str(DEV_LO), "dev_end": str(DEV_END),
        "m15_span": [str(mt.iloc[0]), str(mt.iloc[-1])],
        "h1_span_truncated": [str(ht.iloc[0]), str(ht.iloc[-1])],
        "h1_bars_excluded_as_OOS": 6261,
    },
    "definitions": {
        "disp_4_lag1": "(close[i-1] - close[i-5]) / ATR[i-1]  on M15",
        "disp_8_lag1": "(close[i-1] - close[i-9]) / ATR[i-1]  on M15",
        "label": "(close[i+16] - close[i]) / ATR[i]  on M15 (4h)",
        "h1_regime": "(h1_close - h1_MA50) / h1_ATR14; bull > +0.5, bear < -0.5, else neutral",
        "quintile_cutoffs": "from TRAIN only, applied unchanged everywhere",
    },
    "phase2a_m15": {}, "phase2a_feasibility": {}, "phase2a_h1_analogue": {},
    "phase2b_cost": {}, "phase2c_overlap": {}, "verdicts": {},
}

# ============================================== 2A  M15 structure by H1 regime
REG = {"H1_BULL": m_reg > 0.5, "H1_NEUTRAL": (m_reg >= -0.5) & (m_reg <= 0.5),
       "H1_BEAR": m_reg < -0.5}
for name, x in SIG.items():
    q, cuts = qcut_train(x, IS_TRAIN)
    entry = {"train_cutoffs": cuts, "regimes": {}, "periods": {}}
    for rname, rmask in REG.items():
        ok = BASE_OK & (q >= 0) & rmask & (IS_TRAIN | IS_DEV)
        s = spread_test(m_y, ok, q, M15_H)
        entry["regimes"][rname] = (s | {"n_total": int(ok.sum())}) if s else {
            "n_total": int(ok.sum()), "note": "insufficient population"}
    # descriptive period slices
    for pname, a, b in (("2009-2014", "2009-01-01", "2014-12-31"),
                        ("2015-2019", "2015-01-01", "2019-12-31"),
                        ("2020-2022", "2020-01-01", "2022-06-29"),
                        ("2022-2024", "2022-06-30", "2024-08-09"),
                        ("2024-DEV", "2024-08-11", "2025-09-02")):
        A, B = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
        pm = ((mt >= A) & (mt <= B)).to_numpy()
        ok = BASE_OK & (q >= 0) & pm
        if ok.sum() < 500:
            entry["periods"][pname] = {"n": int(ok.sum()),
                                       "status": "IMPOSSIBLE -- no M15 data in this period"}
            continue
        s = spread_test(m_y, ok, q, M15_H)
        entry["periods"][pname] = (s | {"n_total": int(ok.sum()), "status": "TESTED"}) \
            if s else {"n": int(ok.sum()), "status": "insufficient"}
    results["phase2a_m15"][name] = entry

results["phase2a_feasibility"] = {
    "m15_history_begins": str(mt.iloc[0]),
    "pre_2022_m15_bars": 0,
    "conclusion": ("The M15 structure CANNOT be tested before 2022-06-30. The three "
                   "pre-2022 slices contain zero M15 bars. They are reported IMPOSSIBLE, "
                   "not estimated."),
}

# ====================================== 2A  H1-NATIVE ANALOGUE (long history)
h_y = np.full(len(hc), np.nan)
h_y[: len(hc) - H1_H] = (hc[H1_H:] - hc[: len(hc) - H1_H]) / h_atr[: len(hc) - H1_H]
H1_SIG = {"h1_disp_1_lag1 (analogue of disp_4_lag1)": lagged_disp(hc, h_atr, 1, 1),
          "h1_disp_2_lag1 (analogue of disp_8_lag1)": lagged_disp(hc, h_atr, 2, 1)}
H1_TRAIN = (ht <= TRAIN_HI).to_numpy()
H1_BASE = np.isfinite(h_y) & np.isfinite(h_atr) & (h_atr > 0) & np.isfinite(h_regime)
H1_REG = {"H1_BULL": h_regime > 0.5, "H1_NEUTRAL": (h_regime >= -0.5) & (h_regime <= 0.5),
          "H1_BEAR": h_regime < -0.5}
for name, x in H1_SIG.items():
    # cutoffs from the pre-2022 long history so this analogue is not fitted on TRAIN
    pre = (ht < pd.Timestamp("2022-06-30", tz="UTC")).to_numpy()
    q, cuts = qcut_train(x, pre)
    entry = {"cutoffs_from": "H1 history before 2022-06-30", "cutoffs": cuts,
             "regimes": {}, "periods": {}}
    for rname, rmask in H1_REG.items():
        ok = H1_BASE & (q >= 0) & rmask
        s = spread_test(h_y, ok, q, H1_H)
        entry["regimes"][rname] = (s | {"n_total": int(ok.sum())}) if s else {
            "n_total": int(ok.sum()), "note": "insufficient"}
    for pname, a, b in (("2009-2014", "2009-01-01", "2014-12-31"),
                        ("2015-2019", "2015-01-01", "2019-12-31"),
                        ("2020-2022", "2020-01-01", "2022-06-29"),
                        ("2022-2024", "2022-06-30", "2024-08-09"),
                        ("2024-DEV", "2024-08-11", "2025-09-02")):
        A, B = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
        pm = ((ht >= A) & (ht <= B)).to_numpy()
        ok = H1_BASE & (q >= 0) & pm
        s = spread_test(h_y, ok, q, H1_H)
        entry["periods"][pname] = (s | {"n_total": int(ok.sum())}) if s else {
            "n": int(ok.sum()), "status": "insufficient"}
    results["phase2a_h1_analogue"][name] = entry

# ================================================== 2C  overlap / dependence
for name, x in SIG.items():
    q, _ = qcut_train(x, IS_TRAIN)
    ok = BASE_OK & (q >= 0) & (IS_TRAIN | IS_DEV)
    tail = ok & ((q == 0) | (q == NQ - 1))
    idx = np.flatnonzero(tail)
    # greedy non-overlap: take a signal, then skip the holding window
    keep, last = [], -10 ** 9
    for i in idx:
        if i - last >= M15_H:
            keep.append(i)
            last = i
    results["phase2c_overlap"][name] = {
        "raw_tail_observations": int(len(idx)),
        "non_overlapping_observations": int(len(keep)),
        "overlap_ratio": round(len(idx) / max(len(keep), 1), 2),
        "holding_bars": M15_H,
        "block_count_at_4h": int(len(np.unique(idx // M15_H))),
        "method": ("greedy forward scan: accept a signal, then skip the full 16-bar "
                   "holding window before accepting another"),
        "non_overlap_indices_saved": True,
    }
    np.save(OUT / f"nonoverlap_{name}.npy", np.array(keep, dtype=np.int64))

# ======================================================= 2B  cost realism
def hypothetical(name: str, x: np.ndarray, arm_mask: np.ndarray, arm: str) -> dict:
    """Non-optimised diagnostic. Direction opposite the displacement. No stop/target."""
    q, _ = qcut_train(x, IS_TRAIN)
    ok = BASE_OK & (q >= 0) & arm_mask
    tail = ok & ((q == 0) | (q == NQ - 1))
    idx = np.flatnonzero(tail)
    keep, last = [], -10 ** 9
    for i in idx:
        if i - last >= M15_H:
            keep.append(i)
            last = i
    keep = np.array(keep, dtype=int)
    if len(keep) < 30:
        return {"n": int(len(keep)), "status": "insufficient"}
    side = np.where(q[keep] == 0, 1.0, -1.0)      # opposite the displacement
    gross_usd = side * m_y_usd[keep]
    gross_atr = side * m_y[keep]
    atr_here = m_atr[keep]
    bs = block_stats(gross_atr, keep, M15_H)
    out = {
        "arm": arm, "n_trades_non_overlapping": int(len(keep)),
        "median_atr_usd": float(np.median(atr_here)),
        "gross_mean_usd": float(gross_usd.mean()),
        "gross_median_usd": float(np.median(gross_usd)),
        "gross_mean_atr": float(gross_atr.mean()),
        "gross_median_atr": float(np.median(gross_atr)),
        "win_rate_pct": float((gross_usd > 0).mean() * 100),
        "p10_usd": float(np.percentile(gross_usd, 10)),
        "p90_usd": float(np.percentile(gross_usd, 90)),
        "sd_usd": float(gross_usd.std(ddof=1)),
        "block_mean_atr": bs["mean"], "block_se_atr": bs["se"],
        "block_t_atr": bs["t"], "block_ci95_atr": bs["ci"], "blocks": bs["n_blocks"],
        "costs": {},
    }
    for frac in SLIP_FRACTIONS:
        cost_1x = SPREAD_USD + 2.0 * frac * SPREAD_USD
        cost_2x = 2.0 * SPREAD_USD + 2.0 * frac * SPREAD_USD
        for label_, cost in (("round_turn_1x_spread", cost_1x),
                             ("conservative_2x_spread", cost_2x)):
            net = gross_usd - cost
            net_atr = net / atr_here
            nb = block_stats(net_atr, keep, M15_H)
            out["costs"][f"slip_{frac}x::{label_}"] = {
                "cost_usd": round(cost, 4),
                "cost_in_atr_at_median": round(cost / float(np.median(atr_here)), 4),
                "net_mean_usd": float(net.mean()),
                "net_median_usd": float(np.median(net)),
                "net_mean_atr": float(net_atr.mean()),
                "net_win_rate_pct": float((net > 0).mean() * 100),
                "net_block_t": nb["t"], "net_block_ci95_atr": nb["ci"],
                "cost_as_pct_of_gross_mean": (
                    round(cost / gross_usd.mean() * 100, 1)
                    if gross_usd.mean() > 0 else None),
            }
    return out


for name, x in SIG.items():
    results["phase2b_cost"][name] = {
        "TRAIN": hypothetical(name, x, IS_TRAIN, "TRAIN"),
        "DEV": hypothetical(name, x, IS_DEV, "DEV"),
        "TRAIN+DEV": hypothetical(name, x, IS_TRAIN | IS_DEV, "TRAIN+DEV"),
    }
results["phase2b_cost"]["assumptions"] = {
    "spread_median_usd": SPREAD_USD, "spread_p99_usd": SPREAD_P99,
    "spread_source": "measured, 2026-09-24 M1-resolved tick sample, 520,012 ticks",
    "spread_convention_note": (
        "ask = mid + S/2, bid = mid - S/2, so a long entered at ask and exited at bid "
        "pays 1 x S for the round turn. Earlier reports in this programme said 2 x S; "
        "that double-counted and is corrected here. Both are reported."),
    "slippage_fractions_of_spread": list(SLIP_FRACTIONS),
    "total_cost_formula": "spread_component + 2 * slip_fraction * spread",
    "limitation": ("the spread is measured in 2026 where median ATR is ~$8.9; TRAIN sits at "
                   "~$2.1 ATR. Applying a 2026 spread to 2022-2024 is an assumption, and it "
                   "makes costs a LARGER fraction of ATR in TRAIN than in DEV."),
}

out_json = Path(__file__).parent / "phase2_regime_cost_results.json"
out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print(f"wrote {out_json.name}  sha256 {hashlib.sha256(out_json.read_bytes()).hexdigest()[:16]}")
print(json.dumps(results["phase2a_feasibility"], indent=2))
