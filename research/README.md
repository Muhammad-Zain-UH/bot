# Research harness — edge discovery

Analysis-only. **Nothing here is imported by production, and nothing here may
import from a strategy module in order to make a decision.** It imports
production functions only as *feature extractors*, unmodified.

## Architecture

The point of splitting this into four modules is that lookahead becomes
structurally impossible rather than merely intended.

```
panel_features.py   PAST ONLY        -> features.pkl
panel_labels.py     FUTURE ALLOWED   -> labels.pkl
candidates.py       features -> setup masks (pure, no side, no label access)
evaluate.py         joins on index, block-aggregates, reports
```

**The dependency rule is one-directional.** `panel_labels` may read
`features.pkl` — it does, for barrier distances — because features -> labels is
permitted. Nothing ever flows back: `panel_features` imports neither
`panel_labels` nor `candidates`, and emits no forward-looking column.
`candidates` sees features only.

`panel_features` does not *assert* causality, it **verifies** it: every feature
is recomputed on truncated prefixes at 250 random indices and must agree
exactly. It exits non-zero if it does not.

## Running

Panels are generated artefacts and are **not committed** (see `.gitignore`).
Write them outside the repo:

```
python research/panel_features.py  <scratch>/features.pkl
python research/panel_labels.py    <scratch>/features.pkl <scratch>/labels.pkl
python research/evaluate.py
```

`panel_features` ~5s, `panel_labels` ~2min, `evaluate` instant.

## Conventions these modules enforce

- **Independence.** Adjacent M5 bars share forward windows. Every inferential
  number is computed on non-overlapping h-bar blocks, and the headline
  comparison is *paired* — candidate block mean against the same block's
  all-eligible mean — so it controls for when a candidate fired. Raw N is
  reported but never used for inference.
- **Gap honesty.** A horizon of h M5 bars is h*5 *market* minutes, not h*5
  wall-clock minutes. Both spans are recorded per row, and the gap-straddling
  fraction is reported.
- **Barrier resolution on M1.** M5 OHLC cannot resolve barriers below ~0.75 ATR
  (6.1% of races have both barriers inside one M5 bar at 0.5 ATR). M1 begins
  2026-06-02 10:20; rows it does not cover are flagged, never silently
  downgraded.
- **Constants are declared, not tuned.** Every candidate threshold in
  `candidates.py` is a named module-level constant with the brief that fixed it.

## ATR definition

`pandas_ta.atr(length=14)` (Wilder RMA) and
`atr_14.rolling(20, min_periods=5).mean()` — identical calls to production
`indicators.calculate_indicators`, but computed over the full frame rather than
production's 100-bar request window. Both are strictly causal; they differ only
in RMA initialisation. Measured discrepancy: median 0.013%, max 0.154%.
