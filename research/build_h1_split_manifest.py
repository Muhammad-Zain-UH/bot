"""Build the H1 multi-regime split manifest.

The frozen M15 manifest already recorded, at creation time:

    "H1 spans 17.08 years and DOES contain bear regimes; it is the designated
     directional-robustness layer for that reason."

That plan was written and then not executed: H01-H04 all ran on M15, whose
authorised range contains ZERO down years (see research/VIABILITY_REPORT.md).
This manifest makes the H1 history usable as a primary research arm.

What it does:
  - extends TRAIN *backwards* to the start of H1 history (2009-08-31)
  - leaves DEV and FINAL_OOS boundary dates EXACTLY as the frozen manifest has
    them, so FINAL_OOS is untouched and the lock is unchanged
  - carries the lock, token, unlock requirements and prohibitions verbatim

Extending TRAIN backwards cannot touch FINAL_OOS: the OOS window is bounded by
forward dates that are copied unchanged.

The frozen `research_split_manifest.json` is READ, never written.
FINAL_OOS market statistics are deliberately NOT computed here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.dataset_access import load_timeframe, verify_dataset        # noqa: E402

M15_MANIFEST = Path(__file__).with_name("research_split_manifest.json")
OUT = Path(__file__).with_name("research_split_manifest_h1.json")

PURGE_H1_BARS = 4        # longest GO horizon on H1 is 4h = 4 bars (VIABILITY_REPORT section 2)


def arm_stats(h1: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp,
              with_market_stats: bool, literal_from: str | None = None,
              literal_to: str | None = None) -> dict:
    sub = h1[(h1["time"] >= lo) & (h1["time"] <= hi)]
    if sub.empty:
        return {"h1_rows": 0}
    idx = h1.index[(h1["time"] >= lo) & (h1["time"] <= hi)]
    out: dict = {
        # FINAL_OOS carries the SOURCE strings byte-for-byte, so "copied verbatim"
        # is literally true rather than only the same instant in a different format.
        "from_utc": literal_from if literal_from is not None else str(lo),
        "to_utc": literal_to if literal_to is not None else str(hi),
        "h1_rows": int(len(sub)),
        "h1_index_range": [int(idx.min()), int(idx.max())],
        "months": round((hi - lo).days / 30.4375, 2),
        "years": round((hi - lo).days / 365.25, 2),
        "blocks_1h": int(len(sub) // 1), "blocks_2h": int(len(sub) // 2),
        "blocks_4h": int(len(sub) // 4),
    }
    if not with_market_stats:
        out["net_pct"] = None
        out["median_atr_usd"] = None
        out["regime"] = None
        out["market_stats_withheld"] = (
            "FINAL_OOS is locked; net return, median ATR and regime composition are "
            "deliberately NOT computed. Only structural metadata (dates, row count, "
            "index range) is recorded, which the lock needs in order to function.")
        return out
    out["net_pct"] = round(float(100 * (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1)), 2)
    out["median_atr_usd"] = round(float(sub["atr"].median()), 4)
    g = sub.groupby(sub["time"].dt.year)["close"].agg(["first", "last", "count"])
    g["ret"] = g["last"] / g["first"] - 1
    down = g[g.ret < 0]
    out["regime"] = {
        "years_total": int(len(g)), "years_up": int((g.ret > 0).sum()),
        "years_down": int(len(down)),
        "down_years": [int(y) for y in down.index],
        "bars_in_down_years": int(g.loc[down.index, "count"].sum()),
        "pct_bars_in_down_years": round(
            100 * float(g.loc[down.index, "count"].sum()) / float(g["count"].sum()), 2)}
    return out


def main() -> None:
    verify_dataset()
    m15m = json.loads(M15_MANIFEST.read_text(encoding="utf-8"))
    arms_m15 = m15m["arms"]

    h1 = load_timeframe("H1")
    h1["atr"] = ta.atr(h1["high"], h1["low"], h1["close"], length=14)

    TRAIN_HI = pd.Timestamp(arms_m15["TRAIN"]["to_utc"])
    DEV_LO = pd.Timestamp(arms_m15["DEV"]["from_utc"])
    DEV_HI = pd.Timestamp(arms_m15["DEV"]["to_utc"])
    OOS_LO = pd.Timestamp(arms_m15["FINAL_OOS"]["from_utc"])
    OOS_HI = pd.Timestamp(arms_m15["FINAL_OOS"]["to_utc"])
    TRAIN_LO = h1["time"].min()                      # extend backwards to H1 origin

    gap_h = (DEV_LO - TRAIN_HI).total_seconds() / 3600
    print(f"[boundaries] TRAIN {TRAIN_LO} -> {TRAIN_HI}")
    print(f"[boundaries] DEV   {DEV_LO} -> {DEV_HI}   (gap after TRAIN: {gap_h:.2f} h)")
    print(f"[boundaries] OOS   {OOS_LO} -> {OOS_HI}   (copied verbatim, not inspected)")
    assert gap_h >= PURGE_H1_BARS, "TRAIN/DEV gap is smaller than the H1 embargo"
    assert TRAIN_LO < pd.Timestamp(arms_m15["TRAIN"]["from_utc"]), (
        "TRAIN was not extended backwards; nothing gained")
    assert TRAIN_HI < OOS_LO, "TRAIN end is at or past the OOS start"

    man = {
        "status": "H1 MULTI-REGIME SPLIT -- derived from the frozen M15 manifest",
        "derived_from": {
            "manifest": "research/research_split_manifest.json",
            "manifest_git_sha": m15m.get("git_sha"),
            "rationale": m15m["regime_warnings"][-1],
        },
        "purpose": (
            "H01-H04 were tested on M15, whose authorised range contains ZERO down "
            "years. H1 spans 17 years with 6 down years and the 2013-2015 decline. "
            "research/VIABILITY_REPORT.md shows 1h|H1 is the only combination with "
            "substantial headroom against spread cost (9.37x)."),
        "FINAL_OOS_LOCKED": True,
        "oos_authorisation_token": m15m["oos_authorisation_token"],
        "oos_unlock_requirements": m15m["oos_unlock_requirements"],
        "oos_prohibitions": m15m["oos_prohibitions"],
        "oos_boundaries_unchanged": (
            "FINAL_OOS from_utc and to_utc are copied verbatim from the frozen M15 "
            "manifest. TRAIN is extended BACKWARDS only, which cannot reach the OOS "
            "window. Asserted at build time."),
        "primary_timeframe": "H1",
        "context_timeframe": "H4",
        "timeframe_roles": {
            "H1": "primary feature/label research and signal discovery, 2009-2026",
            "H4": "longer-horizon context and robustness, 2004-2026",
            "M15": "replication only; its range has no bear regime",
            "M5": "not usable -- 0.4 years to the DEV boundary",
            "M1": "not usable -- zero bars in the authorised window"},
        "binding_range": {
            "basis": "H1 -- primary and the longest usable intraday history",
            "from_utc": str(TRAIN_LO), "to_utc": str(OOS_HI),
            "years": round((OOS_HI - TRAIN_LO).days / 365.25, 2)},
        "purge_embargo": {
            "h1_bars": PURGE_H1_BARS, "equivalent_hours": PURGE_H1_BARS,
            "rationale": (
                "the longest GO horizon on H1 is 4h = 4 bars (VIABILITY_REPORT s.2); "
                "dropped AFTER each boundary so no forward window spans two arms. The "
                f"existing TRAIN/DEV gap is {gap_h:.1f} h, already far larger.")},
        "viability": {
            "source": "research/VIABILITY_REPORT.md",
            "go_combinations_on_this_manifest": {
                "1h|H1": {"headroom_x": 9.37, "min_events": 1067, "min_event_rate": 0.0114},
                "4h|H1": {"headroom_x": 2.37, "min_events": 4163, "min_event_rate": 0.0444}},
            "binding_constraint": (
                "every hypothesis using this manifest must cite a GO row and declare an "
                "expected event rate at or above its minimum")},
        "arms": {
            "TRAIN": arm_stats(h1, TRAIN_LO, TRAIN_HI, True),
            "DEV": arm_stats(h1, DEV_LO, DEV_HI, True),
            "FINAL_OOS": arm_stats(h1, OOS_LO, OOS_HI, False,
                                   literal_from=arms_m15["FINAL_OOS"]["from_utc"],
                                   literal_to=arms_m15["FINAL_OOS"]["to_utc"])},
        "dataset_fingerprints": {k: v for k, v in m15m["dataset_fingerprints"].items()
                                 if k in ("H1", "H4")},
        "dataset_sha256": m15m["dataset_sha256"],
        "server_offset_hours": m15m["server_offset_hours"],
        "enforcement": m15m["enforcement"],
    }
    tr, dv = man["arms"]["TRAIN"], man["arms"]["DEV"]
    man["regime_warnings"] = [
        (f"TRAIN contains {tr['regime']['years_down']} down years "
         f"{tr['regime']['down_years']} and {tr['regime']['pct_bars_in_down_years']}% of "
         f"its bars inside them. This is the property the M15 range lacks entirely "
         f"(0.0%), and the reason this manifest exists."),
        (f"DEV is short ({dv['years']} years, {dv['h1_rows']:,} H1 bars) and contains "
         f"{dv['regime']['years_down']} down years. It can test sign agreement; it "
         f"cannot independently establish regime robustness."),
        ("TRAIN spans a 4x change in gold's dollar volatility (2009 ~$950 to 2024 "
         "~$2400). An absolute-dollar threshold fitted anywhere in TRAIN meets a very "
         "different distribution elsewhere in it. Thresholds must be scale-relative."),
        ("TRAIN is 15 years and DEV is 1 year. A result that holds in TRAIN and fails "
         "in DEV may be a DEV sample-size artefact rather than a failure; a result that "
         "holds in DEV and fails in TRAIN is almost certainly noise."),
    ]

    OUT.write_text(json.dumps(man, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"\n[arms] TRAIN {tr['h1_rows']:>7,} bars  {tr['years']:>5.1f} yr  net {tr['net_pct']:+8.1f}%  "
          f"down years {tr['regime']['years_down']} {tr['regime']['down_years']}  "
          f"bars in down {tr['regime']['pct_bars_in_down_years']}%")
    print(f"[arms] DEV   {dv['h1_rows']:>7,} bars  {dv['years']:>5.1f} yr  net {dv['net_pct']:+8.1f}%  "
          f"down years {dv['regime']['years_down']} {dv['regime']['down_years']}")
    print(f"[arms] OOS   {man['arms']['FINAL_OOS']['h1_rows']:>7,} bars  "
          f"-- market statistics deliberately withheld")
    print(f"\n[blocks] TRAIN independent windows: 1h {tr['blocks_1h']:,}  4h {tr['blocks_4h']:,}")
    print(f"[wrote] {OUT}")

    # Post-write verification: the claim "FINAL_OOS copied verbatim" is checked
    # against the file as written, not against an in-memory variable.
    written = json.loads(OUT.read_text(encoding="utf-8"))
    src, dst = arms_m15["FINAL_OOS"], written["arms"]["FINAL_OOS"]
    checks = {
        "FINAL_OOS from_utc byte-identical": src["from_utc"] == dst["from_utc"],
        "FINAL_OOS to_utc byte-identical": src["to_utc"] == dst["to_utc"],
        "token byte-identical": m15m["oos_authorisation_token"] == written["oos_authorisation_token"],
        "FINAL_OOS_LOCKED true": written["FINAL_OOS_LOCKED"] is True,
        "FINAL_OOS market stats withheld": dst["net_pct"] is None and dst["median_atr_usd"] is None,
        "TRAIN extended backwards": pd.Timestamp(written["arms"]["TRAIN"]["from_utc"]) < pd.Timestamp(src["from_utc"]),
    }
    print()
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    assert all(checks.values()), "post-write verification failed"


if __name__ == "__main__":
    main()
