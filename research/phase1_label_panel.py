"""PHASE 1 LABEL PANEL -- FUTURE INFORMATION. Strictly after the decision point.

Horizons, in M15 bars: 1h = 4, 2h = 8, 4h = 16. 8h is deliberately absent -- it is
not a Phase 1 research horizon.

Separation
----------
This module imports nothing from `phase1_feature_panel`. It reads the feature
panel's pickle for exactly ONE column, `atr`, used as the normalisation
denominator. That is features -> labels, the permitted direction. Nothing flows
back, and no label value is ever visible to a feature.

OOS isolation
-------------
The feature panel is already truncated at the DEV end, so bars beyond it do not
exist here. A label needing bars past the end is therefore NaN with
`has_window = False` -- the last 16 M15 bars of DEV carry no 4h label. That is the
correct outcome: computing them would require reading FINAL_OOS.

Alternative reference points
----------------------------
Phases 1 and 2 of the previous programme were each wrecked by a feature built from
`close[i]` correlating with a label that subtracts `close[i]`. This panel therefore
emits the forward return measured from FOUR origins so the scan can run the
reference-price and delayed-entry controls without recomputing anything:

    close[i]      the conventional origin, and the coupling-exposed one
    mid[i]        (high[i] + low[i]) / 2 -- does not privilege the closing tick
    close[i+1]    one full bar later; removes close[i] from the label entirely
    close[i+2]    two bars later
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = {4: "1h", 8: "2h", 16: "4h"}
DELAYS = (0, 1, 2)


def build_labels(panel: pd.DataFrame) -> pd.DataFrame:
    c = panel["close"].to_numpy(float)
    h = panel["high"].to_numpy(float)
    l = panel["low"].to_numpy(float)
    atr = panel["atr"].to_numpy(float)
    n = len(c)
    mid = (h + l) / 2.0
    out: dict[str, np.ndarray] = {"idx": panel["idx"].to_numpy()}

    for hb, lab in HORIZONS.items():
        has = np.zeros(n, bool)
        has[: n - hb] = True
        out[f"has_window_{lab}"] = has

        # exit price is close[i+hb]; only the ORIGIN varies
        exit_px = np.full(n, np.nan)
        exit_px[: n - hb] = c[hb:]

        for d in DELAYS:
            origin = np.full(n, np.nan)
            m = n - hb - d
            if m > 0:
                origin[:m] = c[d:][:m]
            ret = exit_px - origin
            out[f"ret_d{d}_{lab}"] = ret
            out[f"ret_atr_d{d}_{lab}"] = np.where(
                np.isfinite(atr) & (atr > 0), ret / atr, np.nan)

        ret_mid = exit_px - mid
        out[f"ret_mid_{lab}"] = ret_mid
        out[f"ret_atr_mid_{lab}"] = np.where(
            np.isfinite(atr) & (atr > 0), ret_mid / atr, np.nan)

        # direction and path, from the conventional origin
        out[f"dir_{lab}"] = np.sign(out[f"ret_d0_{lab}"])
        up = np.full(n, np.nan)
        dn = np.full(n, np.nan)
        for i in range(n - hb):
            w_h = h[i + 1:i + 1 + hb]
            w_l = l[i + 1:i + 1 + hb]
            up[i] = w_h.max() - c[i]
            dn[i] = c[i] - w_l.min()
        out[f"mfe_atr_{lab}"] = np.where(np.isfinite(atr) & (atr > 0), up / atr, np.nan)
        out[f"mae_atr_{lab}"] = np.where(np.isfinite(atr) & (atr > 0), dn / atr, np.nan)
    return pd.DataFrame(out)


def main() -> None:
    panel_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    panel = pd.read_pickle(panel_path)
    lab = build_labels(panel)
    lab.to_pickle(out)

    hsh = hashlib.sha256()
    hsh.update(pd.util.hash_pandas_object(lab, index=False).values.tobytes())
    meta = {
        "rows": int(len(lab)),
        "horizons_m15_bars": {str(k): v for k, v in HORIZONS.items()},
        "origins": ["close[i]", "mid[i]", "close[i+1]", "close[i+2]"],
        "source_panel": str(panel_path.name),
        "source_panel_last_utc": panel["time"].iloc[-1].isoformat(),
        "labels_with_window": {v: int(lab[f"has_window_{v}"].sum())
                               for v in HORIZONS.values()},
        "oos_isolation": ("source panel truncated at DEV end, so a label needing bars "
                          "past it is NaN; the last 16 M15 bars carry no 4h label"),
        "imports_from_feature_module": "none; reads only the `atr` column from the pickle",
        "fingerprint_sha256": hsh.hexdigest(),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
