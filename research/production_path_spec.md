# Production Decision Path — frozen specification

**Committed BEFORE any result is generated.** Git history is the evidence: this
commit contains the specification and no reconstruction script, results file or
report. Nothing here is derived from an observed outcome.

The path is documented **as implemented**, from `main_production.analyze_entry`
(line 604) and the engines it calls. Where an implementation differs from its
documentation, the literal behaviour is recorded and the discrepancy noted.
**Nothing is repaired in this phase.**

---

## 1. The path, in execution order

`analyze_entry` **short-circuits**: it returns at the first failing layer, so a
decision blocked at L3 was never evaluated against L5–L8.

| # | Layer | Function | Data required | Gate |
|---|---|---|---|---|
| 0 | Daily limit | `_count_today_entry_signals` | — | `trades_today >= MAX_INTRADAY_TRADES_PER_DAY` (4) → `DAILY_LIMIT` |
| 0b | Regime | `entry_engine.detect_regime` | **M5**, M15, H1 | sets `regime`, `tp_ratio`, `bypass_l3`, `bypass_l6` |
| 1 | **L1 bias** | `bias_engine.get_fast_bias` (scalp regimes) or `get_h4_bias` | H1 (fast) / H4+D1 | `NEUTRAL` → `L1_BIAS` |
| 2a | **L2 H1 regime gate** | inline | H1 | `h1_atr < 8.0` → `L2_STRUCTURE` ("too calm") |
| 2b | **L2 structure** | `structure_engine.get_h1_structure` | H1 | `structure_type == "BROKEN"` → `L2_STRUCTURE`; `UNKNOWN` passes |
| 2c | **L2 BOS flip** | `get_h1_structure` re-call | H1 | a fresh confirmed break opposite the bias **changes `side`** |
| 3 | **L3 pullback** | `pullback_detector.get_m15_pullback` | M15 | `not detected or quality < MIN_PULLBACK_QUALITY` → `L3_PULLBACK`; REGIME_SCALP momentum fallback; `bypass_l3` skips |
| 4 | **L4 liquidity** | `identify_liquidity_pools` → `assess_liquidity_gate` | M15, H1, H4, **D1** | gate `state == "BLOCK"` → `L4_LIQUIDITY` |
| 5 | **L5 sweep / CHoCH** | `sweep_detector.get_sweep_and_structure` | M15, H1 | `WATCH` → `L5_SWEEP_WAIT`; no sweep/CHoCH → `L5_SWEEP`; wrong direction → `L5_SWEEP_DIRECTION` |
| 6 | **L6 POI** | `poi_engine.identify_poi` | M15, H1 | `score < 60` if sweep confirmed else `< 70` → `L6_POI`; `bypass_l6` skips |
| 7 | **L7 confidence** | `confidence_engine.get_confidence_engine` | scalars + **regime** | `score < 55` (MICRO_SCALP) else `< 70`; `max(.,75)` on momentum fallback → `L7_CONFIDENCE` |
| 8 | **L8 entry trigger** | `entry_engine.get_entry_trigger` → `evaluate_entry_for_regime` | **M5, M1** | not triggered or regime gate disallows → `L8_ENTRY` |

**A trade is created only when all of L1–L8 pass in sequence**, the daily limit is
not reached, and the regime gate admits the entry style. Session/time gating is
not a standalone layer: `_within_kill_zone()` (`hour in [8,10) or [12,14)` UTC,
`entry_engine.py:16`) is consumed *inside* `detect_regime` and
`get_entry_trigger`.

## 2. Literal definitions used in this audit

- **L1 bias** — `ema_threshold = max(2.0, atr_14 × 0.12)` on H1;
  `|ema20−ema50| < threshold` → NEUTRAL; else BULLISH/BEARISH;
  `strength = min(10, |d|/threshold)`. BULLISH→BUY, BEARISH→SELL.
- **H1 regime gate** — `h1_atr < 8.0` blocks, where `h1_atr` is the production
  mean of the last 14 H1 high−low ranges (**not** a Wilder ATR).
- **Structure confirmation** — `structure_type == "HH/HL"` with BULLISH, or
  `"LH/LL"` with BEARISH.
- **Displacement** — `entry_engine.detect_displacement_candle`: `close>open` and
  `close_position ≥ 0.7` (BUY) / `close<open` and `≤ 0.3` (SELL), **and**
  (`body/atr ≥ 0.9` or `body/range ≥ 0.6`).
- **Sweep** — `get_sweep_and_structure(m15, h1, level, side)`; passing requires
  `gate_state != "WATCH"`, (`sweep_confirmed` or `choch_confirmed`), and not
  wrong-direction.
- **POI** — `identify_poi(m15, h1, direction, current_price)`, `best_poi.score`
  against 60/70.
- **Session gate** — `_within_kill_zone()`, hour in `[8,10) ∪ [12,14)` UTC.
- **Pullback** — `get_m15_pullback(m15, effective_bias_label)`,
  `pullback_detected` and `pullback_quality ≥ MIN_PULLBACK_QUALITY`.

## 3. Data availability — what can and cannot be tested

Measured against `data/research_v1` inside the authorised window
(TRAIN 2022-06-30→2024-08-09, DEV 2024-08-11→2025-09-02):

| TF | From | Bars in TRAIN | Bars in DEV |
|---|---|---|---|
| H4 | 2004-06-11 | 3,273 | 1,639 |
| H1 | 2009-08-31 | 12,511 | 6,256 |
| M15 | 2022-06-30 | 50,010 | 24,989 |
| **M5** | 2025-04-25 | **0** | 25,126 |
| **M1** | 2026-06-17 | **0** | **0** |
| **D1** | — | **not in the dataset** | — |

**Consequences, frozen before results:**

- **L8 entry trigger is UNTESTABLE.** It requires M5 **and** M1; M1 has **zero**
  bars in TRAIN *and* DEV. Classified **DESCRIPTIVE ONLY**.
- **`detect_regime` is untestable over TRAIN** (no M5), so every regime-dependent
  gate — `bypass_l3`, `bypass_l6`, the L7 threshold — is unavailable there.
  **L7's gate is DESCRIPTIVE ONLY**; its score is computable.
- **L4 runs degraded**: `daily_data` is an Optional parameter and will be passed
  `None`, so previous-day extremes are absent from the pool set. Literal, but
  not identical to production. Recorded, not repaired.

## 4. Known implementation / documentation discrepancies — carried forward, not fixed

Established by earlier audits in this programme and re-stated here because they
materially affect interpretation:

1. **`detect_choch` is not a textbook CHoCH implementation.**
2. **L6 inherits `side` from L1/L2 and does not independently validate direction** —
   it cannot contradict the bias.
3. **Breaker-block construction is not actually present** despite being referenced.
4. **Sweep implementation and documentation disagree.**
5. **`rr ≡ tp_ratio` tautology** — the RR gate compares a constant to itself, so
   entry/stop geometry cannot reach admission through it.
6. **`h1_atr` in the L2 gate is a 14-bar mean range, not a Wilder ATR**, so the
   "8.0 pips" threshold is not on the scale its name implies.
7. **L2 BOS flip can change `side`** after L1 has set it, so "bias direction" is
   not necessarily the direction a trade is taken in.
8. **`compute_cvd_proxy` reads `tick.last` and `tick.volume`**, both measured at
   **0% populated** on this broker's XAUUSD feed.

## 5. Frozen hypothesis set — 21 tests

**Baseline (not a hypothesis): bias alone.** Every layer is measured as **excess
over the bias-only population**, which is the critical quantity: a filter that
selects a subset can show a different mean purely by sampling a different part of
the drift distribution.

| Layer | Condition added to bias ≠ NEUTRAL | Horizons |
|---|---|---|
| B. H1 regime gate | `h1_atr ≥ 8.0` | 1h, 2h, 4h |
| C. Displacement | `detect_displacement_candle` aligned with bias | 1h, 2h, 4h |
| D. Structure confirmation | HH/HL (bull) or LH/LL (bear) | 1h, 2h, 4h |
| E. Sweep | L5 passes | 1h, 2h, 4h |
| F. POI | L6 passes | 1h, 2h, 4h |
| G. Session gate | `_within_kill_zone()` | 1h, 2h, 4h |
| H. Pullback | L3 passes | 1h, 2h, 4h |

**7 layers × 3 horizons = 21 hypotheses.** No other combination is tested. Only
combinations that already exist as the production path would be admissible, and
the production path cannot be run end-to-end here because L8 is untestable.

**L8 entry trigger and the L7 gate contribute 0 hypotheses — DESCRIPTIVE ONLY.**

## 6. Metric and statistical standard

Direction-normalised forward return, `+1 × (close[i+h] − close[i])/ATR[i]` for
BUY and `−1 × …` for SELL, at h = 4 / 8 / 16 M15 bars.

`research/STATISTICAL_RESEARCH_CONTROLS.md` applies in full: **non-overlapping
headline inference**, raw statistics alongside, block statistics secondary with
weighting disclosed, estimator-sign-disagreement check, overlap ratios,
forward-window audit, **Bonferroni and Benjamini–Hochberg over the 21 declared
tests**, confidence intervals and sample counts throughout.

**Neutral accounting.** Total eligible M15 observations, bullish, bearish and
neutral counts with percentages are reported **before** the directional analysis.
Neutral observations are not silently dropped from the denominator, and no
inference is drawn that excluding them is beneficial.

## 7. Four-trade forensic trace — scope and a caveat I want recorded

Section D of the authorisation asks for a causal trace of the four `baseline_008`
signals. Those trades occurred **2026-06-02 → 2026-09-16**, which falls inside
the *calendar* window later designated FINAL_OOS (2025-09-02 → 2026-10-01).

They are traced from the **already-committed `baseline_008` artifacts**, which are
a frozen historical record created long before the split existed and already
examined repeatedly in this programme. **No new read of `data/research_v1`'s
FINAL_OOS arm occurs**, and `dataset_access` is not used to reach it.

I am flagging the calendar overlap so it can be judged rather than discovered
later. The trace is **forensic and descriptive only**: n=4 is not evidence, no
statistic is computed from it, and no threshold or rule is derived from it.

## 8. What this phase does not do

No threshold is optimised, no combination is searched, no layer is ranked, no
"best component" is selected, no new feature or indicator is introduced, no
replacement rule is invented, no strategy is created, and no profitability claim
is made. Layers are classified only as **SUPPORTED · NOT SUPPORTED ·
INCONCLUSIVE · DESCRIPTIVE ONLY**.
