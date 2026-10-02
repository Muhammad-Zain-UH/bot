"""Phase 3 -- production path decomposition: unconditional layer reconstruction.

Evaluates every production layer at every eligible M15 bar WITHOUT the
short-circuit, so a layer's contribution can be measured independently of
whether an earlier layer blocked.

Nothing is reimplemented. The production functions are imported and called on
the exact bar windows production passes them (backtest.replay_engine.
DEFAULT_BAR_COUNTS: H4 100, H1 60, M15 50). No threshold is altered.

Frozen specification: research/production_path_spec.md.
Statistical standard: research/STATISTICAL_RESEARCH_CONTROLS.md.

Writes a panel to --panel. Analysis lives in production_path_audit.py; this
file only reconstructs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import load_timeframe, verify_dataset   # noqa: E402

# --- production, imported unmodified ------------------------------------------
from indicators import calculate_indicators                           # noqa: E402
from bias_engine import get_fast_bias                                 # noqa: E402
from structure_engine import get_h1_structure                         # noqa: E402
from pullback_detector import get_m15_pullback                        # noqa: E402
from liquidity_engine import identify_liquidity_pools, assess_liquidity_gate  # noqa: E402
from sweep_detector import get_sweep_and_structure                    # noqa: E402
from poi_engine import identify_poi                                   # noqa: E402
from entry_engine import detect_displacement_candle, _within_kill_zone  # noqa: E402
from confidence_engine import get_confidence_engine                   # noqa: E402
from backtest.replay_engine import DEFAULT_BAR_COUNTS                 # noqa: E402
from core.types import Timeframe                                      # noqa: E402

# Production constants, quoted not chosen.
MIN_PULLBACK_QUALITY = 1.5      # main_production.py:835
DEAD_CALM_H1_ATR = 8.0          # main_production.py:733
N_H4 = DEFAULT_BAR_COUNTS[Timeframe.H4]
N_H1 = DEFAULT_BAR_COUNTS[Timeframe.H1]
N_M15 = DEFAULT_BAR_COUNTS[Timeframe.M15]
HORIZONS = {"1h": 4, "2h": 8, "4h": 16}

SPLIT = json.loads(Path(__file__).with_name("research_split_manifest.json").read_text(encoding="utf-8"))
TRAIN_LO = pd.Timestamp(SPLIT["arms"]["TRAIN"]["from_utc"])
TRAIN_HI = pd.Timestamp(SPLIT["arms"]["TRAIN"]["to_utc"])
DEV_LO = pd.Timestamp(SPLIT["arms"]["DEV"]["from_utc"])
DEV_HI = pd.Timestamp(SPLIT["arms"]["DEV"]["to_utc"])

GATE_KEYS_SIDED = ("gate_C_displacement", "gate_D_structure", "gate_E_sweep",
                   "gate_F_poi", "gate_H_pullback")


def _bar_end(df: pd.DataFrame, delta: pd.Timedelta) -> np.ndarray:
    return (df["time"] + delta).to_numpy("datetime64[ns]")


def build(panel_path: Path, limit: int | None, progress_every: int,
          only_range: tuple[int, int] | None = None) -> None:
    assert SPLIT["FINAL_OOS_LOCKED"] is True, "split manifest no longer declares the OOS lock"
    verify_dataset()

    m15, h1, h4 = (load_timeframe(tf) for tf in ("M15", "H1", "H4"))
    # Hard truncation at the DEV boundary BEFORE anything is computed.
    m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
    h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)
    h4 = h4[h4["time"] <= DEV_HI].reset_index(drop=True)
    for name, df in (("M15", m15), ("H1", h1), ("H4", h4)):
        assert df["time"].max() <= DEV_HI, name + " panel extends past the DEV boundary"
    print("[data] M15 {:,}  H1 {:,}  H4 {:,}  (all <= {})".format(len(m15), len(h1), len(h4), DEV_HI), flush=True)

    # Last CLOSED higher-timeframe bar at each M15 bar close.
    jh1 = np.searchsorted(_bar_end(h1, pd.Timedelta(hours=1)),
                          _bar_end(m15, pd.Timedelta(minutes=15)), side="right") - 1
    jh4 = np.searchsorted(_bar_end(h4, pd.Timedelta(hours=4)),
                          _bar_end(m15, pd.Timedelta(minutes=15)), side="right") - 1

    t = m15["time"]
    in_train = ((t >= TRAIN_LO) & (t <= TRAIN_HI)).to_numpy()
    in_dev = ((t >= DEV_LO) & (t <= DEV_HI)).to_numpy()
    idx = np.arange(len(m15))
    eligible = (idx >= N_M15 - 1) & (jh1 >= N_H1 - 1) & (jh4 >= N_H4 - 1) & (in_train | in_dev)
    if only_range is not None:
        eligible = eligible & (idx >= only_range[0]) & (idx <= only_range[1])
    rows_idx = idx[eligible]
    if limit:
        rows_idx = rows_idx[:limit]
    print("[data] eligible M15 decisions: {:,}  (TRAIN {:,} / DEV {:,})".format(
        len(rows_idx), int(in_train[rows_idx].sum()), int(in_dev[rows_idx].sum())), flush=True)

    # ---- labels: direction-normalised forward return in M15 ATR(14) units ----
    close = m15["close"].to_numpy(float)
    m15_atr = ta.atr(m15["high"], m15["low"], m15["close"], length=14).to_numpy(float)
    fwd = {}
    for name, h in HORIZONS.items():
        nxt = np.full(len(close), np.nan)
        nxt[: len(close) - h] = close[h:]
        with np.errstate(invalid="ignore", divide="ignore"):
            fwd[name] = np.where(np.isfinite(m15_atr) & (m15_atr > 0), (nxt - close) / m15_atr, np.nan)

    # ---- per-H1-bar cache: the H1 window is identical for the 4 M15 bars in an hour ----
    h1_needed = np.unique(jh1[rows_idx])
    print("[h1] caching {:,} H1 windows".format(len(h1_needed)), flush=True)
    h1_cache: dict[int, dict] = {}
    t0 = time.perf_counter()
    for n_done, k in enumerate(h1_needed, 1):
        win = h1.iloc[k - (N_H1 - 1): k + 1].reset_index(drop=True)
        entry: dict = {"fail": ""}
        try:
            ind = calculate_indicators(win)
            b = get_fast_bias(ind, h1_data=win) or {}
            entry["bias"] = b.get("bias", "NEUTRAL")
            entry["bias_strength"] = float(b.get("bias_strength") or 0.0)
        except Exception as exc:                                   # noqa: BLE001
            entry.update(bias="NEUTRAL", bias_strength=0.0, fail="bias:" + type(exc).__name__)
        # production: h1_data["high"].tail(14) - h1_data["low"].tail(14) -> mean
        entry["h1_atr"] = float((win["high"].tail(14) - win["low"].tail(14)).mean())
        entry["struct_type"] = ""
        entry["struct_conf"] = np.nan
        entry["struct_valid"] = False
        if entry["bias"] != "NEUTRAL":
            try:
                s = get_h1_structure(win, entry["bias"]) or {}
                entry["struct_type"] = str(s.get("structure_type") or "")
                entry["struct_conf"] = float(s.get("structure_confidence") or 0.0)
                entry["struct_valid"] = bool(s.get("structure_valid"))
            except Exception as exc:                               # noqa: BLE001
                entry["fail"] += " struct:" + type(exc).__name__
        h1_cache[int(k)] = entry
        if n_done % 2000 == 0:
            el = time.perf_counter() - t0
            print("  [h1] {:,}/{:,}  {:.1f} min  eta {:.1f} min".format(
                n_done, len(h1_needed), el / 60, el / n_done * (len(h1_needed) - n_done) / 60), flush=True)

    # ---- per-M15 decision: every layer, unconditionally ----
    out: list[dict] = []
    t0 = time.perf_counter()
    for n_done, i in enumerate(rows_idx, 1):
        k = int(jh1[i])
        hc = h1_cache[k]
        bias_label = hc["bias"]
        bar_close = m15["time"].iloc[i] + pd.Timedelta(minutes=15)
        rec: dict = {
            "i": int(i),
            "time": m15["time"].iloc[i],
            "arm": "TRAIN" if bool(in_train[i]) else "DEV",
            "bias": bias_label,
            "bias_strength": hc["bias_strength"],
            "h1_atr": hc["h1_atr"],
            "struct_type": hc["struct_type"],
            "struct_conf": hc["struct_conf"],
            "struct_valid": hc["struct_valid"],
            # side-independent gates, defined for NEUTRAL bars too
            "gate_B_h1_regime": bool(hc["h1_atr"] >= DEAD_CALM_H1_ATR),
            "gate_G_session": bool(_within_kill_zone(bar_close.to_pydatetime())),
            "fail": hc["fail"],
        }
        for name in HORIZONS:
            rec["fwd_" + name] = float(fwd[name][i])

        if bias_label == "NEUTRAL":
            for key in GATE_KEYS_SIDED:
                rec[key] = None
            rec.update(side="", poi_score=np.nan, sweep_quality=np.nan,
                       l4_state="", l5_reason="", pullback_quality=np.nan,
                       conf_score=np.nan, conf_grade="", disp_quality=np.nan)
            out.append(rec)
            continue

        side = "BUY" if bias_label == "BULLISH" else "SELL"
        rec["side"] = side
        mw = m15.iloc[i - (N_M15 - 1): i + 1].reset_index(drop=True)
        hw = h1.iloc[k - (N_H1 - 1): k + 1].reset_index(drop=True)
        kk = int(jh4[i])
        h4w = h4.iloc[kk - (N_H4 - 1): kk + 1].reset_index(drop=True)
        price = float(mw["close"].iloc[-1])

        rec["gate_D_structure"] = bool(
            (hc["struct_type"] == "HH/HL" and bias_label == "BULLISH")
            or (hc["struct_type"] == "LH/LL" and bias_label == "BEARISH")
        )

        # L3 pullback
        try:
            p = get_m15_pullback(mw, bias_label) or {}
            q = float(p.get("pullback_quality") or 0.0)
            rec["pullback_quality"] = q
            rec["gate_H_pullback"] = bool(p.get("pullback_detected")) and q >= MIN_PULLBACK_QUALITY
        except Exception as exc:                                   # noqa: BLE001
            rec["pullback_quality"] = np.nan
            rec["gate_H_pullback"] = None
            rec["fail"] += " pull:" + type(exc).__name__

        # L4 liquidity. daily_data=None: D1 is absent from the dataset -- declared in the spec.
        sweep_level = None
        try:
            pools = identify_liquidity_pools(mw, h1_data=hw, h4_data=h4w, daily_data=None,
                                             current_price=price, side=side) or {}
            sp, tp = pools.get("sweep_pool"), pools.get("tp_pool")
            gate = assess_liquidity_gate(sp, tp, price, side) or {}
            rec["l4_state"] = str(gate.get("state") or "")
            sweep_level = (sp or {}).get("level")
        except Exception as exc:                                   # noqa: BLE001
            rec["l4_state"] = ""
            rec["fail"] += " liq:" + type(exc).__name__

        # L5 sweep / CHoCH
        try:
            sw = get_sweep_and_structure(mw, hw, sweep_level, side, l4_override_level=sweep_level) or {}
            gs = str(sw.get("gate_state") or "BLOCK")
            st = str(sw.get("sweep_type") or "").lower()
            wrong_dir = bool(sw.get("sweep_confirmed")) and (
                (side == "BUY" and "bearish" in st) or (side == "SELL" and "bullish" in st)
            )
            rec["sweep_quality"] = float(sw.get("sweep_quality") or 0.0)
            if gs == "WATCH":
                rec["l5_reason"] = "WATCH"
            elif not (sw.get("sweep_confirmed") or sw.get("choch_confirmed")):
                rec["l5_reason"] = "NO_SWEEP"
            elif wrong_dir:
                rec["l5_reason"] = "WRONG_DIR"
            else:
                rec["l5_reason"] = "PASS"
            rec["gate_E_sweep"] = rec["l5_reason"] == "PASS"
        except Exception as exc:                                   # noqa: BLE001
            rec["sweep_quality"] = np.nan
            rec["l5_reason"] = ""
            rec["gate_E_sweep"] = None
            rec["fail"] += " sweep:" + type(exc).__name__

        # L6 POI -- threshold depends on whether L5 confirmed a sweep (production: 60 vs 70)
        try:
            poi = identify_poi(mw, h1_data=hw, direction=side, current_price=price) or {}
            best = poi.get("best_poi") or {}
            sc = float(best.get("score") or 0.0)
            rec["poi_score"] = sc
            need = 60.0 if rec.get("gate_E_sweep") else 70.0
            rec["gate_F_poi"] = bool(sc >= need)
        except Exception as exc:                                   # noqa: BLE001
            rec["poi_score"] = np.nan
            rec["gate_F_poi"] = None
            rec["fail"] += " poi:" + type(exc).__name__

        # Displacement -- DECLARED DEVIATION: production passes M5; M5 has zero bars
        # in TRAIN, so the function is applied literally to the M15 window instead.
        try:
            d = detect_displacement_candle(mw, side) or {}
            rec["gate_C_displacement"] = bool(d.get("displacement_found"))
            rec["disp_quality"] = float(d.get("displacement_quality") or 0.0)
        except Exception as exc:                                   # noqa: BLE001
            rec["gate_C_displacement"] = None
            rec["disp_quality"] = np.nan
            rec["fail"] += " disp:" + type(exc).__name__

        # L7 score -- DESCRIPTIVE ONLY. The regime string cannot be derived (M5 absent
        # in TRAIN), so the function default is used and the gate is not evaluated.
        try:
            c = get_confidence_engine(
                bias_strength=rec["bias_strength"],
                structure_confidence=0.0 if not np.isfinite(rec["struct_conf"]) else rec["struct_conf"],
                sweep_quality=0.0 if not np.isfinite(rec["sweep_quality"]) else rec["sweep_quality"],
                poi_score=0.0 if not np.isfinite(rec["poi_score"]) else rec["poi_score"],
                structure_valid=bool(rec["struct_valid"]),
            ) or {}
            rec["conf_score"] = float(c.get("final_score") or 0.0)
            rec["conf_grade"] = str(c.get("grade") or "")
        except Exception as exc:                                   # noqa: BLE001
            rec["conf_score"] = np.nan
            rec["conf_grade"] = ""
            rec["fail"] += " conf:" + type(exc).__name__

        out.append(rec)
        if n_done % progress_every == 0:
            el = time.perf_counter() - t0
            print("  [m15] {:,}/{:,}  {:.1f} min  eta {:.1f} min".format(
                n_done, len(rows_idx), el / 60, el / n_done * (len(rows_idx) - n_done) / 60), flush=True)

    panel = pd.DataFrame(out)
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_pickle(panel_path)
    nf = int((panel["fail"].astype(str).str.strip() != "").sum())
    print("\n[done] panel {} -> {}".format(panel.shape, panel_path))
    print("[done] rows carrying a production-call failure: {:,} ({:.3f}%)".format(nf, 100 * nf / len(panel)))
    print("[done] max time in panel: {}  (DEV boundary {})".format(panel["time"].max(), DEV_HI))
    assert panel["time"].max() <= DEV_HI



def replicate(panel_path: Path, n_probes: int, seed: int) -> int:
    """Two controls on the harness.

    (a) LOOKAHEAD AUDIT over the whole panel: the higher-timeframe bar each
        decision was mapped to must have CLOSED at or before the M15 decision
        bar close. This is the mapping that would leak the future if the
        searchsorted offset were wrong, so it is checked exhaustively rather
        than sampled.

    (b) DETERMINISM: rebuild a contiguous block of rows from scratch and require
        every recorded cell to match.

    Window causality itself is structural: every frame handed to a production
    function is a prefix slice ending at the decision bar, and the only
    forward-looking quantities in the panel are the fwd_* labels, which are
    never inputs to a gate.

    Returns the number of failures.
    """
    panel = pd.read_pickle(panel_path)
    fails = 0

    print("=" * 78)
    print("HARNESS CONTROLS")
    print("=" * 78)

    # ---- (a) exhaustive lookahead audit -------------------------------------
    m15, h1, h4 = (load_timeframe(tf) for tf in ("M15", "H1", "H4"))
    m15 = m15[m15["time"] <= DEV_HI].reset_index(drop=True)
    h1 = h1[h1["time"] <= DEV_HI].reset_index(drop=True)
    h4 = h4[h4["time"] <= DEV_HI].reset_index(drop=True)
    dec_close = _bar_end(m15, pd.Timedelta(minutes=15))
    h1_end = _bar_end(h1, pd.Timedelta(hours=1))
    h4_end = _bar_end(h4, pd.Timedelta(hours=4))
    jh1 = np.searchsorted(h1_end, dec_close, side="right") - 1
    jh4 = np.searchsorted(h4_end, dec_close, side="right") - 1
    pos = panel["i"].to_numpy(int)
    bad_h1 = int((h1_end[jh1[pos]] > dec_close[pos]).sum())
    bad_h4 = int((h4_end[jh4[pos]] > dec_close[pos]).sum())
    print("  (a) lookahead audit over all {:,} panel rows".format(len(panel)))
    print("      H1 windows ending after the decision bar close: {}".format(bad_h1))
    print("      H4 windows ending after the decision bar close: {}".format(bad_h4))
    print("      max time in panel {} <= DEV boundary {}: {}".format(
        panel["time"].max(), DEV_HI, panel["time"].max() <= DEV_HI))
    fails += bad_h1 + bad_h4 + (0 if panel["time"].max() <= DEV_HI else 1)

    # ---- (b) contiguous-block determinism ----------------------------------
    rng = np.random.default_rng(seed)
    width = min(n_probes, len(panel))
    off = int(rng.integers(0, max(len(panel) - width, 1)))
    blk = panel.iloc[off: off + width]
    lo, hi = int(blk["i"].min()), int(blk["i"].max())
    tmp = panel_path.with_name(panel_path.stem + ".replica.pkl")
    build(tmp, None, 10 ** 9, only_range=(lo, hi))
    rep = pd.read_pickle(tmp).set_index("i")

    cols = [c for c in panel.columns if c not in ("i", "fail")]
    mism, detail = 0, []
    for _, row in blk.iterrows():
        i = int(row["i"])
        if i not in rep.index:
            detail.append("i={} missing from replica".format(i)); mism += 1; continue
        r2 = rep.loc[i]
        for c in cols:
            a, b = row[c], r2[c]
            try:
                same = bool(a == b) or (pd.isna(a) and pd.isna(b))
            except (TypeError, ValueError):
                same = a is b
            if not same:
                mism += 1
                if len(detail) < 12:
                    detail.append("i={} {}: {!r} != {!r}".format(i, c, a, b))
    print("  (b) determinism: rebuilt rows {:,}-{:,} ({:,} rows, {} columns)".format(
        lo, hi, len(blk), len(cols)))
    print("      mismatching cells: {}".format(mism))
    for d in detail:
        print("       ", d)
    tmp.unlink(missing_ok=True)
    fails += mism

    print("  RESULT:", "PASS" if fails == 0 else "FAIL ({} failures)".format(fails))
    return fails

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--progress-every", type=int, default=5000)
    ap.add_argument("--replicate", type=int, default=0,
                    help="instead of building, recompute N random rows of an existing panel")
    ap.add_argument("--seed", type=int, default=31337)
    a = ap.parse_args()
    if a.replicate:
        sys.exit(1 if replicate(Path(a.panel), a.replicate, a.seed) else 0)
    build(Path(a.panel), a.limit, a.progress_every)
