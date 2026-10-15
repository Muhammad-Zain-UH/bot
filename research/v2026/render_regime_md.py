"""Render research/v2026/REGIME_2026_EXPLORATION.md from research/v2026/regime_2026.json.

    venv\\Scripts\\python.exe research/v2026/render_regime_md.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
IN_JSON = REPO / "research" / "v2026" / "regime_2026.json"
OUT_MD = REPO / "research" / "v2026" / "REGIME_2026_EXPLORATION.md"
FX = ("XAGUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD")


def p(x, d=2):
    return "n/a" if x is None or x != x else f"{100 * x:+.{d}f}"


def q(x, d=1):
    return "n/a" if x is None or x != x else f"{100 * x:.{d}f}"


def b(x):
    return "n/a" if x is None else f"{1e4 * x:+.1f}"


def render(res: dict) -> str:
    N, D = res["windows"]["NEW"], res["windows"]["DEV"]
    L = ["# 2026 regime exploration — FINAL_OOS opened (exploratory, descriptive only)", "",
         f"NEW = {N['span']['d1_first']} → {N['span']['d1_last']} ({N['span']['n_d1']} D1 sessions); DEV = "
         f"{D['span']['d1_first']} → {D['span']['d1_last']} ({D['span']['n_d1']}). MetaQuotes-Demo, v1b clock rule, D1 at 17:00 NY.",
         "Descriptive only. FINAL_OOS is no longer clean; new strategies need a forward demo test from 2026-10-15. Log returns in %, vol annualised %, n = observations.", ""]
    L += ["## A. Gold by month (NEW)", "",
          "| Month | Return | n D1 | Realised vol (H1) | n H1 | ATR(14) $ | ATR % | n ATR | Max intra-month DD |",
          "|---|---|---|---|---|---|---|---|---|"]
    for m in N["A_gold_monthly"]:
        L.append(f"| {m['month']} | {p(m['ret'])} | {m['n_d1']} | {q(m['vol_ann'])} | {m['n_h1']} | {m['atr_usd']:.1f} | "
                 f"{q(m['atr_pct'], 2)} | {m['n_atr']} | {q(m['max_dd'])} |")
    L += ["", "DEV by year (sum of monthly returns; mean of monthly vol and ATR %; worst monthly DD):", "",
          "| Year | Months | Return | Mean vol | Mean ATR % | Worst DD | n D1 |", "|---|---|---|---|---|---|---|"]
    years: dict = {}
    for m in D["A_gold_monthly"]:
        years.setdefault(m["month"][:4], []).append(m)
    for y, ms in years.items():
        atr = [m["atr_pct"] for m in ms if m["atr_pct"] == m["atr_pct"]]
        L.append(f"| {y} | {len(ms)} | {p(sum(m['ret'] for m in ms), 1)} | {q(np.mean([m['vol_ann'] for m in ms]))} | "
                 f"{q(np.mean(atr), 2)} | {q(max(m['max_dd'] for m in ms))} | {sum(m['n_d1'] for m in ms)} |")
    L += ["", "## B. Gold sessions (WGC fixed UTC: Asia 22–11, Europe 11–14, US 14–22)", "",
          "| Month (NEW) | Asia | Europe | US | n days |", "|---|---|---|---|---|"]
    for m in N["B_sessions"]["monthly"]:
        L.append(f"| {m['month']} | {p(m['asia'])} | {p(m['europe'])} | {p(m['us'])} | {m['n_days']} |")
    L += ["", "| Mean per day (×10⁻⁴ log) | NEW | n | DEV | n |", "|---|---|---|---|---|"]
    for k in ("asia", "europe", "us"):
        a, c = N["B_sessions"]["totals"][k], D["B_sessions"]["totals"][k]
        L.append(f"| {k.capitalize()} | {b(a['mean'])} | {a['n']} | {b(c['mean'])} | {c['n']} |")
    L += ["", f"Next Asia session after the US session (σ of US returns: NEW {q(N['B_sessions']['sigma_us'], 2)} %, "
          f"DEV {q(D['B_sessions']['sigma_us'], 2)} %), ×10⁻⁴ log:", "",
          "| US session | NEW mean | NEW sd | n | DEV mean | DEV sd | n |", "|---|---|---|---|---|---|---|"]
    for k in N["B_sessions"]["next_asia_after_us"]:
        a, c = N["B_sessions"]["next_asia_after_us"][k], D["B_sessions"]["next_asia_after_us"][k]
        L.append(f"| {k} | {b(a['mean'])} | {1e4 * a['sd']:.0f} | {a['n']} | {b(c['mean'])} | {1e4 * c['sd']:.0f} | {c['n']} |")
    L += ["", "## C. Persistence", "", "| Lag | D1 ρ NEW (n) | D1 ρ DEV (n) | H4 ρ NEW (n) | H4 ρ DEV (n) |",
          "|---|---|---|---|---|"]
    for k in range(1, 7):
        def cell(w, f):
            v = w[f].get(str(k))
            return f"{v['rho']:+.3f} ({v['n']})" if v else "—"
        L.append(f"| {k} | {cell(N, 'C_acf_d1')} | {cell(D, 'C_acf_d1')} | {cell(N, 'C_acf_h4')} | {cell(D, 'C_acf_h4')} |")
    L += ["", "| Window | D1 close beyond prior 20-day | Next k days | n | Mean | Median | Share > 0 |", "|---|---|---|---|---|---|---|"]
    for wn, W in (("NEW", N), ("DEV", D)):
        for sig, hs in W["C_breakouts"].items():
            for h, s in hs.items():
                L.append(f"| {wn} | {sig} | {h} | {s['n']} | {p(s['mean'])} | {p(s['median'])} | {q(s['share_pos'], 0)} % |")
    L += ["", "## D. Macro (daily gold return vs daily change: DGS10, DFII10 in bp; DTWEXBGS in log)", "",
          "| Window | Series | Corr | Beta | 60-day corr min / median / max (n) | n days |", "|---|---|---|---|---|---|"]
    for wn, W in (("NEW", N), ("DEV", D)):
        for s, v in W["D_macro"]["series"].items():
            rc = v["rolling_corr"]
            L.append(f"| {wn} | {s} | {v['corr_full']:+.2f} | {v['beta_full']:+.4f} | "
                     f"{rc['min']:+.2f} / {rc['median']:+.2f} / {rc['max']:+.2f} ({rc['n']}) | {W['D_macro']['n_days']} |")
    L += ["", "| Window | Days | n | Mean gold return | Share > 0 |", "|---|---|---|---|---|"]
    for wn, W in (("NEW", N), ("DEV", D)):
        for lab, s in (("DGS10 > +10 bp and dollar up", W["D_macro"]["dgs10_up_10bp_and_dollar_up"]),
                       ("all days", W["D_macro"]["all_days"])):
            L.append(f"| {wn} | {lab} | {s['n']} | {p(s['mean'], 3)} | {q(s['share_pos'], 0)} % |")
    L += ["", "## E. Events (NFP = first Friday; BLS dates not fetched, HTTP 403; FOMC dates as given, NEW only)", "",
          "| Window | Days | n | Mean \\|move\\| | Median \\|move\\| | Mean range |", "|---|---|---|---|---|---|"]
    for wn, W in (("NEW", N), ("DEV", D)):
        for k, v in W["E_events"].items():
            L.append(f"| {wn} | {k} | {v['abs_move']['n']} | {q(v['abs_move']['mean'], 2)} | "
                     f"{q(v['abs_move']['median'], 2)} | {q(v['range']['mean'], 2)} |")
    L += ["", "## F. Silver and FX — monthly return / realised vol, NEW (n D1 in brackets; gold in A)", "",
          "| Month | " + " | ".join(FX) + " |", "|---|" + "---|" * len(FX)]
    for mo in [m["month"] for m in N["A_gold_monthly"]]:
        cells = []
        for s in FX:
            mm = {m["month"]: m for m in N["F"][s]["monthly"]}.get(mo)
            cells.append(f"{p(mm['ret'], 1)} / {q(mm['vol_ann'])} ({mm['n_d1']})" if mm else "—")
        L.append(f"| {mo} | " + " | ".join(cells) + " |")
    L += ["", "| Symbol | Vol NEW | Vol DEV | Corr with gold NEW (n) | 2026 (n) | DEV (n) | VR(5) NEW (n) | VR(5) DEV (n) |",
          "|---|---|---|---|---|---|---|---|"]
    for s in ("XAUUSD", *FX):
        a, c = N["F"][s], D["F"][s]

        def cg(v, k):
            return f"{v[k]['r']:+.2f} ({v[k]['n']})" if v.get(k) else "—"
        L.append(f"| {s} | {q(a['vol_ann'])} | {q(c['vol_ann'])} | {cg(a, 'corr_gold')} | {cg(a, 'corr_gold_2026')} | "
                 f"{cg(c, 'corr_gold')} | {a['vr5']['vr']:.2f} ({a['vr5']['n']}) | {c['vr5']['vr']:.2f} ({c['vr5']['n']}) |")
    return "\n".join(L) + "\n"


def main() -> int:
    OUT_MD.write_text(render(json.loads(IN_JSON.read_text(encoding="utf-8"))), encoding="utf-8")
    print("written", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
