"""CANDIDATES -- setup definitions. Pure functions of the feature panel.

No thresholds are tuned. Every constant is fixed by the pre-declared brief and
is reproduced here verbatim. No candidate assigns a side; direction, where a
candidate has one, is applied at evaluation time.
"""
from __future__ import annotations
import numpy as np, pandas as pd

# ---- Candidate E constants. FIXED BY BRIEF. DO NOT TUNE. ----
E_RATIO_MAX = 0.7        # ATR(M5) / ATR_average_20(M5) <= 0.7
E_SUSTAIN = 12           # sustained for >= 12 consecutive M5 bars
E_RANGE_MULT = 1.5       # 12-bar high-low range <= 1.5 * ATR(M5)
E_RANGE_LOOKBACK = 12


def candidate_E(feats: pd.DataFrame) -> np.ndarray:
    """Volatility contraction. Non-directional: returns a mask, never a side.

    Fires at bar i when the compression ratio has held for the 12 bars ending
    at i (inclusive) AND the trailing 12-bar range is tight relative to ATR.
    """
    ratio = feats["atr_ratio"].to_numpy(float)
    compressed = ratio <= E_RATIO_MAX                     # NaN -> False
    sustained = (pd.Series(compressed.astype(float))
                 .rolling(E_SUSTAIN).min().to_numpy() == 1.0)
    sustained = np.where(np.isnan(sustained), False, sustained)
    tight = (feats["range_12"].to_numpy(float)
             <= E_RANGE_MULT * feats["atr_14"].to_numpy(float))
    return sustained & tight & feats["feature_eligible"].to_numpy(bool)


# ---- Candidate B constants. FIXED BY BRIEF. DO NOT TUNE. ----
B_LOOKBACK = 20           # prior-extreme window on M15, exclusive of breakout bar
B_BREAK_ATR = 0.3         # breakout magnitude >= 0.3 * ATR(M15)
B_RETEST_BARS = 12        # search the next 12 M5 bars after the breakout close
B_RETEST_ATR = 0.2        # retest to within 0.2 * ATR(M15) of the breakout level


def candidate_B(m5: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    """Breakout -> retest -> continuation. Returns one row per BREAKOUT event.

    Event model, stated so it cannot be misread:

    * One M15 bar that breaks its prior 20-bar extreme by >= 0.3*ATR(M15) is
      ONE breakout event, whether or not it ever retests.
    * The retest is searched over the next 12 M5 bars opening at or after the
      breakout bar's CLOSE time. The FIRST qualifying M5 bar is the event; later
      retests of the same breakout are discarded. This is what stops a 12-bar
      window from manufacturing 12 "independent" observations.
    * Invalidation is checked on every M5 close in the window up to AND
      INCLUDING the candidate retest bar, and on every M15 close in the same
      span. "Back through" means strictly beyond the level: `close < level` for
      an upside breakout, `close > level` for a downside one. A touch of the
      level is not a close through it.
    * The decision instant is the CLOSE of the qualifying retest M5 bar.

    Every column is computable from bars at or before the row's own timestamp.
    """
    m5_t = pd.to_datetime(m5["time"], utc=True).to_numpy("datetime64[ns]")
    m5_hi, m5_lo, m5_cl = (m5[k].to_numpy(float) for k in ("high", "low", "close"))
    m15_t = pd.to_datetime(m15["time"], utc=True).to_numpy("datetime64[ns]")
    m15_cl = m15["close"].to_numpy(float)
    atr15 = m15["atr_14"].to_numpy(float)
    ph, pl = m15["prior_high"].to_numpy(float), m15["prior_low"].to_numpy(float)
    elig15 = m15["eligible"].to_numpy(bool)
    FIFTEEN = np.timedelta64(15, "m"); FIVE = np.timedelta64(5, "m")

    up = elig15 & (m15_cl > ph) & ((m15_cl - ph) >= B_BREAK_ATR * atr15)
    dnb = elig15 & (m15_cl < pl) & ((pl - m15_cl) >= B_BREAK_ATR * atr15)

    rows = []
    for j in np.flatnonzero(up | dnb):
        is_up = bool(up[j])
        level = float(ph[j] if is_up else pl[j])
        band = B_RETEST_ATR * float(atr15[j])
        t_break = m15_t[j] + FIFTEEN                    # breakout bar's close
        k0 = int(np.searchsorted(m5_t, t_break, side="left"))
        window = range(k0, min(k0 + B_RETEST_BARS, len(m5_t)))
        rec = {"m15_idx": int(j), "t_break": t_break, "side": "BUY" if is_up else "SELL",
               "level": level, "atr15": float(atr15[j]),
               "break_magnitude_atr": float((m15_cl[j] - level if is_up else level - m15_cl[j])
                                            / atr15[j]),
               "m5_window_bars": len(list(window)), "retest_idx": -1,
               "outcome": "NO_RETEST"}
        if not len(list(window)):
            rec["outcome"] = "NO_M5_WINDOW"; rows.append(rec); continue
        for k in window:
            # invalidation on M5 closes up to and including k
            m5_closes = m5_cl[k0:k + 1]
            bad5 = (m5_closes < level).any() if is_up else (m5_closes > level).any()
            # invalidation on M15 closes that completed in the same span
            a = int(np.searchsorted(m15_t, t_break, side="left"))
            b = int(np.searchsorted(m15_t, m5_t[k] + FIVE - FIFTEEN, side="right"))
            seg = m15_cl[a:b]
            bad15 = (seg < level).any() if is_up else (seg > level).any()
            if bad5 or bad15:
                rec["outcome"] = "INVALIDATED"
                rec["invalidated_by"] = "M5_CLOSE" if bad5 else "M15_CLOSE"
                break
            touched = (m5_lo[k] <= level + band) if is_up else (m5_hi[k] >= level - band)
            if touched:
                rec["retest_idx"] = int(k)
                rec["t_event"] = m5_t[k] + FIVE          # decision instant
                rec["bars_to_retest"] = int(k - k0) + 1
                rec["outcome"] = "RETEST"
                break
        rows.append(rec)
    return pd.DataFrame(rows)


# ---- Candidate D constants. FIXED BY BRIEF. DO NOT TUNE. ----
D_LOOKBACK = 20           # prior-extreme window on M15, exclusive of breakout bar
D_RECLAIM_BARS = 6        # search the next 6 M15 bars after the breakout
D_RECLAIM_ATR = 0.2       # close back inside the range by >= 0.2 * ATR(M15)


def candidate_D(m15: pd.DataFrame) -> pd.DataFrame:
    """False breakout -> reclaim -> reversal. One row per BREAKOUT event.

    Event model:

    * A breakout is the bar on which close first moves beyond the prior 20-bar
      range having been inside on the previous bar. A run of consecutive bars
      still outside the range is ONE breakout, not many -- the brief's "one
      INITIAL M15 breakout = one event". Both counts are reported.
    * Unlike Candidate B there is NO minimum breakout magnitude: any close
      beyond the prior extreme qualifies.
    * The reclaim is searched over M15 bars j+1..j+6 (the breakout bar itself is
      excluded -- "after the breakout"). The FIRST qualifying bar is the event.
    * The range and the ATR are frozen at the breakout bar, so the target a
      reclaim is measured against cannot drift with later data.
    * Direction reverses the breakout: upside false breakout -> SELL.
    * The decision instant is the CLOSE of the reclaiming M15 bar.
    """
    t = pd.to_datetime(m15["time"], utc=True).to_numpy("datetime64[ns]")
    cl = m15["close"].to_numpy(float)
    atr = m15["atr_14"].to_numpy(float)
    ph, pl = m15["prior_high"].to_numpy(float), m15["prior_low"].to_numpy(float)
    elig = m15["eligible"].to_numpy(bool)
    FIFTEEN = np.timedelta64(15, "m")

    out_any = elig & (cl > ph)
    out_dn = elig & (cl < pl)
    prev_up = np.r_[False, out_any[:-1]]
    prev_dn = np.r_[False, out_dn[:-1]]
    init_up = out_any & ~prev_up          # fresh transition to outside
    init_dn = out_dn & ~prev_dn

    rows = []
    for j in np.flatnonzero(init_up | init_dn):
        is_up = bool(init_up[j])
        a = float(atr[j])
        hi_lvl, lo_lvl = float(ph[j]), float(pl[j])
        broken = hi_lvl if is_up else lo_lvl
        opposite = lo_lvl if is_up else hi_lvl
        rec = {"m15_idx": int(j), "t_break": t[j] + FIFTEEN,
               "side": "SELL" if is_up else "BUY",     # reversal of the breakout
               "break_dir": "UP" if is_up else "DOWN",
               "atr15": a, "level_broken": broken, "level_opposite": opposite,
               "range_width_atr": float((hi_lvl - lo_lvl) / a),
               "break_dist_atr": float((cl[j] - hi_lvl) / a if is_up else (lo_lvl - cl[j]) / a),
               "reclaim_idx": -1, "outcome": "NO_RECLAIM"}
        band = D_RECLAIM_ATR * a
        for k in range(j + 1, min(j + 1 + D_RECLAIM_BARS, len(cl))):
            inside = (cl[k] < hi_lvl - band) if is_up else (cl[k] > lo_lvl + band)
            if inside:
                rec.update(reclaim_idx=int(k), t_event=t[k] + FIFTEEN,
                           bars_to_reclaim=int(k - j),
                           reclaim_dist_atr=float((hi_lvl - cl[k]) / a if is_up
                                                  else (cl[k] - lo_lvl) / a),
                           reclaim_close=float(cl[k]), outcome="RECLAIM")
                break
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.attrs["all_breakout_bars"] = int((out_any | out_dn).sum())
    df.attrs["initial_breakouts"] = int((init_up | init_dn).sum())
    return df
