# Phase 6O-B — L3 Pullback Detector Deep Audit

**Audit only. No source changed.** No parameter changed, no threshold tuned, no
strategy optimised. The regime/session architecture is untouched and U9-RR is
not resolved. `baseline_004`, `baseline_005` and the R1 fixtures were read, never
written.

**Input:** commit `68e4a52` (Phase 6O). All statistics are computed from the
**frozen** `baselines/baseline_005/decisions.jsonl` (15,735 records) and the
frozen dataset `433b7e27…`.

**The two questions are kept apart throughout.** This document answers
**"what is a pullback in this system?"** It does **not** answer **"should a
pullback be required for entry?"** — that is D-6OB-1, recorded in §13 and
deliberately left open.

---

# 1. Executive Summary

**L3 is the most binding gate in the system, and the thing it measures is not
what its specification describes.**

Six findings.

1. **Three of the four documented pullback rules are not implemented.** The
   docstring — unchanged since `c3cf4df` — leads with *"EMA20 cross below
   EMA50"*. `pullback_detector` reads `closed.iloc[-1].get("ema20")`, but
   `indicators.py` produces **`ema_20`** and the feed supplies only
   `BAR_COLUMNS = (time, open, high, low, close, tick_volume)`. **`ema20` and
   `ema50` are `None` on every decision, live and replay.** The documented
   volume-comparison rule and the 0.618 depth cap are likewise absent.

2. **In the ideal retracement band, `pullback_detected` is unconditionally
   True.** Base quality for `0.382 ≤ pct ≤ 0.618` is `5.5`, and the gate accepts
   `structure OR quality >= 5.0`. **Falsifiable prediction tested: of 3,302
   blocked decisions reporting a retracement, exactly 3 lie in [38.2 %, 61.8 %],
   and all three are at exactly 38.2 % — display rounding of a value below
   0.382.** Structure confirmation is therefore optional precisely where the
   specification calls it *"required for a strong score"*.

3. **`MIN_PULLBACK_QUALITY = 1.5` is unreachable.** `pullback_detected == True`
   implies `pullback_quality >= 5.0` by construction. **MEASURED: the string
   *"Pullback quality too low"* appears 0 times in 15,735 decisions.**

4. **L3 runs one M15 bar behind every other layer.** `closed = recent.iloc[:-1]`
   discards the last bar to avoid *"a forming bar"* — but the replay feed
   supplies only **closed** bars, so under replay it discards the most recent
   **completed** M15 bar. This is information *under*-use, not leakage.

5. **A unit defect in the REGIME_SCALP momentum fallback.** `distance_pips` (a
   pip count) is compared against `1.2 * m5_atr` (**dollars**), making the cap
   **10× too tight** — a median cap of **6.5 pips = $0.65**. **Its behavioural
   impact is small and must not be overstated:** the check is reached in only
   196 of 4,137 failures, and with a corrected 10× cap **just 21 of those 196
   would pass**.

6. **The retracement metric is unbounded and conflates two different states.**
   **MEASURED: 18.5 % of blocked decisions report a retracement above 100 %**,
   up to **369.3 %** — price beyond the impulse origin, i.e. a reversal, not a
   pullback. The detector reports *"no pullback"* rather than *"impulse
   invalidated"*.

**L3 is genuinely binding**: 5,868 blocks (37.29 %), more than L5 and L8
combined. **It is not binding because its threshold is strict.** It is binding
because the retracement almost never lands in the accepted band — **65.3 % of
blocked decisions had retraced less than 23.6 %, and 26.8 % had not retraced at
all (0–5 %).**

---

# 2. Historical Intent Timeline

**`pullback_detector.py` has exactly two commits in its entire history.**

| Date | Commit | Change |
|---|---|---|
| 2026-07-01 | **`c3cf4df`** | File introduced. Docstring as it still reads today. `pullback_detected = 0.236 <= pct <= 0.786 and is_making_lh_ll` — **structure strictly required** |
| 2026-09-16 | **`4c90b81`** | **FIX (PULLBACK-1)**, the only change to the definition: `and (is_making_lh_ll or quality >= 5.0)`. **11 insertions, 4 deletions — 9 of the 11 are the comment** |

**The docstring is byte-identical at `c3cf4df` and HEAD.** The specification has
never been revised, including when the gate was relaxed.

### 2.1 The documented definition (`c3cf4df`, still current)

```
IN BULLISH BIAS:
- M15 closes turn from bullish to bearish (EMA20 cross below EMA50)
- M15 printing LH/LL temporarily (reversal phase)
- Volume on down candles < volume on up candles (weak selling)
- Pullback depth <= 0.618 fib of last bullish move (not too deep)
PULLBACK QUALITY SCORING (0-10):
- Ideal pullback zone (38%-62% retracement): highest score
- Structure confirmation (LH/LL or HH/HL against the bias): required for a strong score
```

| # | Documented rule | Implemented? |
|---|---|---|
| 1 | **EMA20 cross below EMA50** | **NO** — `ema20`/`ema50` are always `None` (§3.4) |
| 2 | M15 printing LH/LL | **Yes**, as `_structure_confirmation` — but **optional** after PULLBACK-1 |
| 3 | **Volume on down candles < volume on up candles** | **NO** — `_volume_context` compares the *first 3* bars of the window to the *last 3*, irrespective of candle direction |
| 4 | **Depth ≤ 0.618 (not too deep)** | **NO** — implemented as `<= 0.786` |
| 5 | Ideal zone 38–62 % scores highest | **Yes** — `5.5` for `[0.382, 0.618]` |
| 6 | Structure *"required for a strong score"* | **Contradicted** — PULLBACK-1 made it optional |

**No conflicting historical definition exists.** There is one specification and
one relaxation, and the relaxation was not written back into the specification.

### 2.2 What PULLBACK-1 actually did

Its stated rationale — structure is *"only a +3.0 bonus rather than a hard
requirement"* in the score — is accurate. But because the ideal band's **base**
quality is `5.5`, already above the `5.0` alternative, the edit did not merely
let *"genuinely good pullbacks"* through: **it made structure confirmation
entirely inoperative for `0.382 ≤ pct ≤ 0.618`.** The commit describes a
narrower change than it made.

---

# 3. The Exact L3 Contract

## 3.1 Verdict

```python
pullback_detected = (
    0.236 <= pullback_percent <= 0.786
    and (is_making_lh_ll or quality >= 5.0)
)
```

Because `quality >= 5.5` whenever `0.382 <= pullback_percent <= 0.618`, this
reduces exactly to:

```
detected  ⟺  0.382 <= pct <= 0.618                               (unconditional)
          ∨  pct ∈ [0.236, 0.382) ∪ (0.618, 0.786]  AND  (structure  ∨  quality >= 5.0)
```

In the outer sub-bands the base is `4.0`, so `quality >= 5.0` needs at least
`+1.0`: structure `+3.0`, declining volume `+1.5`, or RSI extreme `+1.0`.
Stable volume alone (`+0.5`) is not enough.

## 3.2 Inputs

| Input | Source | Note |
|---|---|---|
| Frame | `m15_data` | **M15 only.** No M5, M1, H1, H4 or D1 |
| Window | `recent = m15_data.tail(50).reset_index(drop=True)` | `lookback = 50`, never overridden |
| **Working set** | **`closed = recent.iloc[:-1]`** | **Drops the last bar** (§5.2) |
| `expected_bias` | `bias["bias"]` from L1 | `"BULLISH"` / `"BEARISH"` — a third direction vocabulary |
| Prices | `closed.iloc[-1]` close/low/high | The bar **before** the newest closed bar |
| `ema20`, `ema50` | `closed.iloc[-1].get(...)` | **Always `None`** (§3.4) |
| RSI | `_get_m15_rsi(closed)` | Reads `rsi`/`rsi_14`, else recomputes via `calculate_indicators` |
| Volume | `tick_volume` | |
| ATR | `_estimate_recent_atr(closed, default=10.0)` | **True range, SMA-14 — not Wilder** (D7); silent `10.0` default |
| Swing | `_find_recent_fractal_swing` | 5-bar fractal, 2 left + 2 right |

**No FVG dependency. No momentum dependency. No structure-engine dependency.**
L1 bias is the only cross-layer input.

## 3.3 Branch-by-branch

| # | Gate | BULLISH | BEARISH |
|---|---|---|---|
| G0 | Data | `len(m15_data) >= 10`, then `len(closed) >= 10` | identical |
| G1 | Swing | `_find_recent_fractal_swing(closed,"HIGH")` | `…,"LOW")` |
| G2 | Impulse origin | `swing_low = closed[:pos+1]["low"].min()` | `swing_high = closed[:pos+1]["high"].max()` |
| G3 | **Impulse size** | `impulse_range >= atr_val * 1.2`, else reject | identical |
| G4 | Retracement | `(swing_high − current_low) / impulse_range` | `(current_high − swing_low) / impulse_range` |
| G5 | **Window age** | `len(closed[pos+1:]) >= 3`, else reject | identical |
| G6 | Structure | `_structure_confirmation(window,"BULLISH")` | `…,"BEARISH")` |
| G7 | Volume | `_volume_context(window)` | identical, direction-agnostic |
| G8 | RSI state | favourable `< 35`, adverse `> 70` | favourable `> 65`, adverse `< 30` |
| G9 | Quality | see §3.5 | identical |
| G10 | Verdict | §3.1 | identical |
| G11 | Exception | `pullback_detected: False` | identical |

## 3.4 The EMA rule is unreachable — proof

| Fact | Evidence |
|---|---|
| L3 reads `ema20` / `ema50` | `pullback_detector.py:244-245` |
| `indicators.py` produces `ema_20` / `ema_50` | `indicators.py:127-128` |
| The frame carries neither | `data/dataset.py:44` — `BAR_COLUMNS = ("time","open","high","low","close","tick_volume")`, documented as *"Exact column layout produced by `mt5_handler.get_market_data`"* |

**Therefore `ema20 is None` always**, the `+0.5` alignment bonus has **0
occurrences**, and documented rule #1 is never evaluated. The returned
`ema_alignment` dict reports `{"ema20": None, "ema50": None, …}` on every
decision.

## 3.5 Quality (0–10)

| Component | Value |
|---|---|
| `0.382 ≤ pct ≤ 0.618` | **5.5** |
| `0.236 ≤ pct < 0.382` or `0.618 < pct ≤ 0.786` | 4.0 |
| `pct < 0.236` | 1.0 |
| `pct > 0.786` | 2.5 |
| Structure confirmed | **+3.0** |
| Volume declining / stable / rising | +1.5 / +0.5 / +0.0 |
| RSI at an extreme | +1.0 |
| **EMA alignment** | **+0.5 — DEAD** |
| Cap | `min(10.0, …)` |

## 3.6 Dead or inert inside L3

| Item | Status |
|---|---|
| `calculate_fib_levels` → `fibs` | **Computed, never read.** `pullback_fib` comes from bucket comparisons on `pullback_percent` |
| EMA alignment bonus | **Dead** (§3.4) |
| `MIN_PULLBACK_QUALITY = 1.5` | **Unreachable** — 0 occurrences in 15,735 |
| `pullback_in_progress` | Returned; **no production consumer** |
| `pullback_depth_fib`, `volume_warning`, `rsi_value`, `swing_point` | Returned; consumed only in the reason string |
| `_get_m15_rsi` synthetic-time branch | `pd.Timestamp.now()` — unreachable because `time` is always present (§5.4) |

---

# 4. Production Call Graph

```
main_production.analyze_entry
  └── L3 block, main_production.py:794-836
        ├── bypass_l3 = regime_info["bypass_l3"]            # MICRO_SCALP only
        ├── get_m15_pullback(m15_data, bias["bias"])         # pullback_detector.py:485
        │     └── detect_m15_pullback(m15_data, expected_bias, lookback=50)
        │           ├── _estimate_recent_atr      (true range, SMA-14, default 10.0)
        │           ├── _find_recent_fractal_swing(5-bar fractal; idxmax fallback)
        │           ├── _get_m15_rsi              (→ indicators.calculate_indicators)
        │           ├── _structure_confirmation   ("BULLISH"/"BEARISH")
        │           ├── _volume_context           (first-3 vs last-3 tick_volume)
        │           └── calculate_fib_levels      ← DEAD
        └── _check_regime_scalp_momentum(...)                # REGIME_SCALP only
```

**`detect_m15_pullback` is called exactly once per decision, from one site.**
No other production module imports `pullback_detector`.

---

# 5. Temporal Audit

**Verdict: VERIFIED — no look-ahead. L3 is temporally conservative to a fault.**

| Question | Answer | Evidence |
|---|---|---|
| Current bar before it completes? | **No** | The feed materialises only bars with `open_time + duration <= T`; L3 then drops one more |
| Future bars? | **No** | `test_leakage.test_pullback_is_unchanged` calls the real `get_m15_pullback` under a post-cutoff mutation and asserts equality |
| Future swing points / fractals? | **No** | Centre `i` needs `i+1`, `i+2`, scanned `i = len-3 → 2`; confirmed 2 bars late |
| Future FVG / structure? | **No** | L3 reads neither |
| Wall clock? | **No, but by luck** | §5.4 |

## 5.1 Measured

Phase 6M measured **0 future-bar violations across all 15,735 decisions on six
timeframes**, minimum lag exactly `0:00:00` on M1–H4. L3's inputs are a strict
subset.

## 5.2 L3 is one M15 bar stale — a live/replay divergence

```python
closed = recent.iloc[:-1].copy() if len(recent) > 1 else recent.copy()
# "Use the latest closed candle so the detector is not whipsawed by a forming bar."
```

**Live:** `mt5_handler.get_market_data` returns a *forming* final bar, so
dropping it is correct.
**Replay:** the feed supplies only completed bars, so this discards the most
recent **completed** M15 bar.

**Consequence:** L3 decides on data up to `T − 15min`, while L8 reads
`m5[-1]` at `T`. Under replay the two layers disagree about "now" by up to one
M15 bar. **This is under-use of information, not leakage — it cannot
manufacture a signal.** Classified **IMPLEMENTATION DEFECT (live/replay
divergence)**, not **TEMPORAL RISK**.

## 5.3 `idxmax()` label used as a positional index — safe, but only by accident

`_find_recent_fractal_swing`'s fallback does
`fallback_idx = int(recent[column].idxmax())` then `recent.iloc[fallback_idx]`
— mixing a **label** with a **position**. It is currently safe **only because**
`detect_m15_pullback` calls `.reset_index(drop=True)` first, making labels equal
positions. `closed = recent.iloc[:-1]` preserves that alignment. **Any future
caller that omits the reset would produce a silent wrong swing or an
`IndexError` swallowed by the outer `except`.** Latent, 0 occurrences.

## 5.4 A wall-clock read inside the strategy path

`_get_m15_rsi` contains `pd.date_range(end=pd.Timestamp.now(tz="UTC"), …)` when
the frame has no `time` column. **`pullback_detector` is NOT in
`clock_patch.PATCHED_MODULES`** (`risk_manager`, `entry_engine`,
`main_production`), whose docstring claims the list *"still covers every ambient
clock read reachable from the strategy"*.

It is unreachable today because `BAR_COLUMNS` always includes `time`, and even
if reached it would affect only VWAP, which L3 does not read. **A latent gap in
the clock-patch coverage claim, 0 occurrences.**

---

# 6. BUY/SELL Symmetry

Compared condition by condition rather than asserted.

| Condition | BULLISH | BEARISH | Mirror? |
|---|---|---|---|
| Fractal | `c > l1,l2,r1,r2` | `c < l1,l2,r1,r2` | **Yes** |
| Fractal fallback | `idxmax` | `idxmin` | **Yes** |
| Impulse origin | `min(low)` up to pos | `max(high)` up to pos | **Yes** |
| Impulse gate | `>= atr*1.2` | `>= atr*1.2` | **Yes — identical constant** |
| Retracement | `(swing_high − current_low)/range` | `(current_high − swing_low)/range` | **Yes** |
| Window age | `>= 3` | `>= 3` | **Yes** |
| Structure count | `LH` or `LL` ≥ threshold | `HH` or `HL` ≥ threshold | **Yes** |
| Structure threshold | `max(2, min(4, len//2))` | identical | **Yes** |
| Volume | direction-agnostic | same call | **Yes** (and wrong for both — §2.1 rule 3) |
| **RSI favourable** | **`< 35`** | **`> 65`** | **Yes** — mirrors about 50 |
| **RSI adverse** | **`> 70`** | **`< 30`** | **Yes** — mirrors about 50 |
| Quality bands | shared code | shared code | **Yes** |
| EMA bonus | `ema20>=ema50 and close>=ema20` | `ema20<=ema50 and close<=ema20` | **Yes** (both dead) |
| Verdict | shared code | shared code | **Yes** |
| Momentum fallback — sustained | `last>prev>prev2` | `last<prev<prev2` | **Yes** |
| Momentum fallback — RSI | `55 ≤ rsi ≤ 75` | `25 ≤ rsi ≤ 45` | **Yes** — mirrors about 50 |
| Momentum fallback — volume, extension | direction-agnostic | identical | **Yes** |

> **No code asymmetry exists in L3. Every constant, inequality, index and
> fallback mirrors exactly.**

**But the outcome is asymmetric**, and the cause is not in L3:

| Side | Reached L3 | Blocked | Rate |
|---|---|---|---|
| **BUY** | 6,693 | 3,159 | **47.2 %** |
| **SELL** | 6,643 | 2,709 | **40.8 %** |

**6.4 points apart on near-identical populations.** With the code proven
symmetric, the cause lies in the inputs — the L1 bias distribution, or the
market's own behaviour over a period in which gold rose 18.6 %. **This audit did
not establish which. UNRESOLVED.**

---

# 7. Reachability — all 15,735 decisions

| L3 outcome | Count | Share |
|---|---|---|
| **BLOCKED** | **5,868** | **37.29 %** |
| **BYPASSED** (MICRO_SCALP) | 4,760 | 30.25 % |
| **PASSED** (style = PULLBACK) | 2,702 | 17.17 % |
| Never reached (blocked at L1/L2) | 2,399 | 15.25 % |
| **MOMENTUM_FALLBACK** | **6** | **0.04 %** |

**Reached L3: 13,336.**

## 7.1 By regime

| Regime | Blocked | Passed | Bypassed | Mom. fallback | Reached |
|---|---|---|---|---|---|
| **MICRO_SCALP** | **0** | **0** | **4,760** | 0 | 4,760 |
| **REGIME_SCALP** | **4,137** | 1,990 | 0 | **6** | 6,133 |
| INTRADAY_SWING | 911 | 302 | 0 | 0 | 1,213 |
| DEAD_CALM | 820 | 410 | 0 | 0 | 1,230 |

**MICRO_SCALP never evaluates L3 at all** — 4,760 of 4,760 bypassed.
**REGIME_SCALP supplies 70.5 % of every L3 block.**

## 7.2 By session

| Session | L3 blocks |
|---|---|
| NewYork | 2,482 |
| Asian | 1,599 |
| London | 1,093 |
| Dead | 547 |
| Closed | 147 |

## 7.3 Is L3 binding?

**Yes, decisively.** 5,868 blocks — more than L5 (4,075) and L8 (1,265)
combined. Of decisions that reach it and are not bypassed, **68.5 % are
rejected**.

---

# 8. Explanation of the 5,868 Blocks

## 8.1 Two reason families

| Family | Count | Share |
|---|---|---|
| **B** — REGIME_SCALP: *"No pullback (…) and momentum fallback failed: …"* | **4,137** | 70.50 % |
| **A** — *"No confirmed pullback detected"* (all other regimes) | **1,731** | 29.50 % |
| **F** — *"Pullback quality too low"* | **0** | **0.00 %** |

Both families have the same root: `pullback_detected == False`. Family B is
REGIME_SCALP's second chance also failing.

## 8.2 Why `pullback_detected` is False — the retracement distribution

**MEASURED** over the 3,302 blocked decisions whose reason reports a
retracement:

| Retracement | Count | Share | |
|---|---|---|---|
| 0–5 % | **885** | **26.80 %** | no retracement at all |
| 5–10 % | 234 | 7.09 % | |
| 10–23.6 % | **1,036** | **31.37 %** | |
| **< 23.6 % (too shallow)** | **2,155** | **65.26 %** | |
| 23.6–38.2 % | 150 | 4.54 % | in range; failed the secondary test |
| **38.2–61.8 %** | **3** | **0.09 %** | display rounding only — §8.3 |
| 61.8–78.6 % | 21 | 0.64 % | in range; failed the secondary test |
| 78.6–100 % | 363 | 10.99 % | too deep |
| **100–200 %** | **527** | **15.96 %** | **beyond the impulse origin** |
| **200–1000 %** | **83** | **2.51 %** | max observed **369.3 %** |
| **> 78.6 % (too deep)** | **973** | **29.47 %** | |

Summary: `n = 3,302 · min 0.0 % · p25 2.9 % · median 17.4 % · p75 85.7 % ·
max 369.3 %`.

> **The 5,868 blocks are not the product of a strict threshold. They are the
> product of a bimodal distribution that almost never visits the accepted band:
> 65.3 % had barely retraced, 29.5 % had retraced too far, and only 5.4 % were
> inside `[23.6 %, 78.6 %]` at all.**

## 8.3 A falsifiable prediction, tested

From §3.1, `0.382 ≤ pct ≤ 0.618` should make `pullback_detected` **True
unconditionally**, so no blocked decision should report a retracement in that
band.

**Result: 3 of 3,302 — all at exactly `38.2 %`.** The reason string formats
`{pct:.1%}` while the code compares the unrounded value, so these are values
just below `0.382` displayed as `38.2 %`. **The prediction holds exactly**, and
of the 177 in-band-but-blocked cases **171 have `structure=False`** — consistent
with the outer sub-bands requiring a secondary signal.

## 8.4 The momentum fallback, and a unit defect

Of REGIME_SCALP's 4,137 fallback failures:

| Check | Failures | Share |
|---|---|---|
| **1. Sustained direction** (`last>prev>prev2`) | **3,176** | **76.77 %** |
| 2. Volume below its 20-candle baseline | 510 | 12.33 % |
| 3. RSI outside 55–75 (BUY) / 25–45 (SELL) | 255 | 6.16 % |
| **4. Overextended** | **196** | **4.74 %** |

**Check 4 carries a unit defect:**

```python
pip_size = 0.10
distance_pips   = abs(last_close - break_reference) / pip_size   # PIPS
max_allowed_pips = 1.2 * m5_atr                                  # m5_atr is DOLLARS
if distance_pips > max_allowed_pips: reject
```

`m5_atr` is quote-currency dollars (U10-A). **MEASURED** across the 196: cap
median **6.5 "pips" = $0.65**; observed distance median **202.3 pips**.

**The impact is small and must not be overstated.** The check is reached only
after checks 1–3 pass, and with a corrected ×10 cap **only 21 of the 196 would
pass** — the rest are extended far beyond even the corrected limit. Those 21
would still have to clear L4–L8. **This is a correctness defect in the same
family as U1/U8/U9/U10, not a suppressed source of trades.**

**The fallback succeeded 6 times in 4,143 attempts (0.14 %).**

---

# 9. Double-Counting and Dependency Analysis

| Shared with | Overlap | Verdict |
|---|---|---|
| **L1 bias** | L3 consumes `bias["bias"]` as `expected_bias` | **Legitimate input**, not double-counting |
| **L2 structure** | `structure_engine` works on **H1**; L3's `_structure_confirmation` on **M15** | **Different timeframes — not duplicated** |
| **L5 CHoCH** | Both locate a 5-bar fractal on M15 with **identical** logic (`sweep_detector._find_recent_fractal_level` vs `pullback_detector._find_recent_fractal_swing`) | **Duplicated code, opposite use.** L3 wants price to *retrace from* the fractal; L5 wants price to *break* it. **Two copies of one algorithm that must stay in step and nothing enforces that** |
| **L4/L5 liquidity & sweep** | L3 has no liquidity or sweep input | **Independent** |
| **L6 POI / FVG** | L3 has no FVG input | **Independent** |
| **L7 confidence** | L7 scores bias, structure, sweep, POI, cohesion. **`pullback_quality` is not among them** | **L3's score never reaches L7** |
| **L8 quality** | L8 rebuilds its own `trigger_quality` from rejection/momentum/CHoCH/`atr_ratio` | **Independent** |
| **RSI** | L3 uses M15 RSI; the momentum fallback uses M5 RSI; L7's A+ checklist uses an RSI band | **Three RSI readings on two timeframes, none shared** |

**The one genuine same-price-event counting:** a single M15 fractal high is
evaluated by **L3** (as the origin of a retracement) and by **L5** (as a level
to break) within the same decision, through two independent copies of the same
fractal routine. They are used for **opposite** purposes, so this is not score
inflation — but it is **duplicated logic with no shared source of truth**.

**`pullback_quality` influences nothing beyond L3's own gate** — and since
`MIN_PULLBACK_QUALITY` is unreachable, it influences only the `quality >= 5.0`
disjunct inside `pullback_detected`.

---

# 10. Style / Regime Interaction

| Regime | `bypass_l3` | Fallback | L3 required? |
|---|---|---|---|
| **MICRO_SCALP** | **True** | — | **Never evaluated.** 4,760/4,760 bypassed |
| **REGIME_SCALP** | False | **Yes** — `_check_regime_scalp_momentum` | Required, with a second chance that works 0.14 % of the time |
| **INTRADAY_SWING** | False | **No** | **Strictly required** — 911 blocked, 302 passed |
| **DEAD_CALM** | False | **No** | **Strictly required** — 820 blocked, 410 passed |

**A pullback is therefore style-specific, not universal.**

**Two interactions worth recording:**

1. **MICRO_SCALP's bypass is consistent with `architecture.txt:222`** —
   *"MICRO_SCALP momentum entries don't need pullback"* — and with its
   MOMENTUM-only style. **VERIFIED.**
2. **INTRADAY_SWING is PULLBACK-only *and* has no L3 fallback**, so L3 is an
   absolute precondition for it. **DEAD_CALM inherits the same strictness by
   falling through to the default**, which — as Phase 6M established — is a
   regime that is 94.85 % band-B session-diverted decisions. **No document
   states that DEAD_CALM should require a pullback; it does so by default, not
   by design.**

---

# 11. Test Audit

| Test | Exercises production? | Assessment |
|---|---|---|
| `test_leakage.test_pullback_is_unchanged` | **Yes** — calls the real `get_m15_pullback` under a post-cutoff mutation | **The only genuine L3 test.** **BULLISH only** |
| `test_layer_gate_logic.test_pullback_gate_requires_real_pullback_detection` | **No** — `get_m15_pullback` is **mocked**; `calculate_indicators` mocked to `{}` | **Vacuous for L3.** It tests `main_production`'s wiring, and **currently fails**, blocking at `L2_STRUCTURE` because the mocked indicators make `h1_atr = 0.0 < 8.0` (D7). It never reaches L3 |
| `test_limit_fvg_semantics.test_pullback_still_does` | Partially | Concerns the L8 pullback **entry style**, not L3 |
| `test_valid_rr_retired.test_pullback_entry_triggered_is_exactly_its_raw_trigger` | Yes | L8 entry style, not L3 |

**Gaps:**

| ID | Gap |
|---|---|
| **L3-T1** | **No BEARISH/SELL test of any kind** — the only real test is BULLISH-only |
| **L3-T2** | **No boundary test** at `0.236`, `0.382`, `0.618`, `0.786`, or the `atr*1.2` impulse gate |
| **L3-T3** | **No test that the ideal band auto-detects** — the property proven in §8.3 is unpinned |
| **L3-T4** | **No negative test** — nothing asserts `detected == False` for a shallow, deep, or `>100 %` retracement |
| **L3-T5** | **No test of any fallback branch** — fractal fallback, `_estimate_recent_atr`'s `10.0` default, the exception handler |
| **L3-T6** | **Nothing pins `MIN_PULLBACK_QUALITY`'s unreachability**, so a future edit could silently activate it |
| **L3-T7** | **Nothing detects that `ema20`/`ema50` are always `None`** — a name-mismatch test would have caught it |
| **L3-T8** | **No test asserts L3 and L5 fractal routines agree** |
| **L3-T9** | `pullback_detector` is absent from `clock_patch.PATCHED_MODULES` and no test flags the ambient `pd.Timestamp.now()` |

---

# 12. Defects

| ID | Defect | Class | Occurrences | Baseline affected? |
|---|---|---|---|---|
| **L3-D1** | **EMA rule unimplemented** — `ema20` vs `ema_20`, and the feed has neither | **IMPLEMENTATION DEFECT** | Every decision | Yes — the bonus never applied |
| **L3-D2** | **Volume rule not as documented** — first-3 vs last-3 bars, not up- vs down-candles | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L3-D3** | **Depth cap is 0.786, documented 0.618** | **IMPLEMENTATION DEFECT** | Every decision | Yes |
| **L3-D4** | **Structure optional in the ideal band**, contradicting *"required for a strong score"* | **IMPLEMENTATION DEFECT** | Ideal-band decisions | Yes — since `4c90b81` |
| **L3-D5** | **`MIN_PULLBACK_QUALITY = 1.5` unreachable** | **DEAD** | **0** | No |
| **L3-D6** | **L3 is one M15 bar stale** under replay | **IMPLEMENTATION DEFECT** (live/replay divergence) | Every decision | Yes |
| **L3-D7** | **Momentum-fallback cap compares pips to dollars — 10× too tight** | **IMPLEMENTATION DEFECT** | 196 reached it; ≤21 would flip | Marginally |
| **L3-D8** | **Retracement unbounded** — up to 369 %; reversal reported as "no pullback" | **IMPLEMENTATION DEFECT** | **610 (18.5 %)** above 100 % | Yes |
| **L3-D9** | **`calculate_fib_levels` computed, never read** | **DEAD** | Every decision | No |
| **L3-D10** | **`_estimate_recent_atr` is SMA-14, not Wilder**, with a silent `10.0` default | **IMPLEMENTATION DEFECT** | Unmeasured | Yes |
| **L3-D11** | **`idxmax()` label used as a position** — safe only via the caller's `reset_index` | **IMPLEMENTATION DEFECT** (latent) | 0 | No |
| **L3-D12** | **Ambient `pd.Timestamp.now()` outside `PATCHED_MODULES`** | **TEMPORAL RISK** (latent) | **0** | No |
| **L3-D13** | **Fractal algorithm duplicated** in L3 and L5 with no shared source | **IMPLEMENTATION DEFECT** | Every decision | No |
| **L3-D14** | **`pullback_in_progress` has no consumer** | **DEAD** | Every decision | No |
| **L3-D15** | **BUY blocked 47.2 % vs SELL 40.8 %** with provably symmetric code | **UNRESOLVED** | — | — |

---

# 13. Ambiguities and Design Decisions

| ID | Question | Why unresolvable from the repository |
|---|---|---|
| **D-6OB-1** | **Should a pullback be required for entry at all?** | **The second question of this phase, deliberately unanswered.** MICRO_SCALP already says no, INTRADAY_SWING and DEAD_CALM say yes absolutely, REGIME_SCALP says "yes, unless momentum". **No document states a system-wide policy.** DEAD_CALM's strictness is inherited by default, not chosen |
| **D-6OB-2** | Is the accepted band `[0.236, 0.786]` or the documented `≤ 0.618`? | Code and docstring have disagreed since `c3cf4df`; neither was ever revised |
| **D-6OB-3** | Is structure confirmation required, or a bonus? | `c3cf4df` required it; `4c90b81` relaxed it; the docstring still says *"required"* |
| **D-6OB-4** | What should happen when retracement exceeds 100 %? | No source contemplates it (L3-D8) |
| **D-6OB-5** | Should the documented EMA and volume rules be implemented or removed from the specification? | Both have been documented and unimplemented since day one |
| **D-6OB-6** | Should L3 use the newest closed bar? | The *"forming bar"* rationale is a live-trading rationale applied under replay (L3-D6) |
| **D-6OB-7** | Should `lookback = 50`, `atr*1.2`, `>= 3` bars be these values? | No archaeology; never changed; never justified |

**None of these is resolved here, and none should be resolved by observing how
many decisions the alternative would admit.**

---

# 14. What Should Be Frozen as Correct

**L3's long/short symmetry** — proven condition by condition (§6), including the
RSI bands that mirror about 50 and the identical `atr*1.2`, `>= 3` and
`max(2,min(4,len//2))` constants. · **L3's temporal correctness** (§5) —
no look-ahead, pinned by a real future-mutation test. · **The 5-bar fractal
geometry** — causal, confirmed two bars late. · **MICRO_SCALP's bypass** —
consistent with `architecture.txt:222` and with its MOMENTUM-only style. ·
**The verdict expression itself as an accurate description of behaviour** — its
reduction in §3.1 was predicted and then confirmed against the frozen data.

---

# 15. What Must Remain Unresolved

**D-6OB-1 through D-6OB-7**, above — in particular the question of whether a
pullback should be required at all, which must not be settled by trade count. ·
**L3-D15**, the BUY/SELL outcome gap, whose cause lies outside L3. · **Whether
`pullback_detector` should be added to `PATCHED_MODULES`** (L3-D12) — it is a
clock-patch scope question, not an L3 question. · **Every threshold named in
§3.5 and §3.2.** · **D-6N-1** and **U9-RR**, untouched by this phase.

---

# 16. Final Classification

| Class | Count | Items |
|---|---|---|
| **VERIFIED** | **5** | Symmetry · temporal correctness · fractal geometry · MICRO_SCALP bypass · contract reduction §3.1 |
| **IMPLEMENTATION DEFECT** | **10** | L3-D1, D2, D3, D4, D6, D7, D8, D10, D11, D13 |
| **INTENT AMBIGUOUS** | **3** | D-6OB-2, D-6OB-3, D-6OB-5 |
| **DEAD / NON-PRODUCTION** | **4** | L3-D5, D9, D14, `_get_m15_rsi` synthetic-time branch |
| **TEST GAP** | **9** | L3-T1 … L3-T9 |
| **DESIGN DECISION** | **7** | D-6OB-1 … D-6OB-7 |
| **TEMPORAL RISK** | **1** (latent, 0 occurrences) | L3-D12 |
| **UNRESOLVED** | **1** | L3-D15 |

**Total L3 components classified: 40.**

---

# 17. Exact Next Audit Target

> **Audit L5 — `sweep_detector.detect_sweep`, `detect_bos` and
> `get_sweep_and_structure` — to this same depth, documentation-only.**

**Why.** L5 is the second-largest gate (**4,075 blocks, 25.9 %**) and the last
large unaudited surface. Phase 6O already found three defects in it from the
interface alone — the close-to-close "ATR" (A9), its silent `15.0` default
(A10), and `detect_choch` implementing a BOS rather than a CHoCH (A3/A4) —
without examining `detect_sweep` at all. **L3 and L5 also share a duplicated
fractal routine (L3-D13)**, so auditing L5 closes that question too.

After L5: pin the L3/L5 behaviour in tests (L3-T1…T9 and Phase 6O's T1/T2),
**then** decide D-6N-1, **then** U9-RR.

**Do not implement any L3 change, do not alter a threshold, and do not resolve
D-6OB-1 or U9-RR until L5 is audited.**

---

# 18. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| Parameters / thresholds | **Untouched** |
| Regime / session architecture | **Untouched** |
| U9-RR | **Not resolved** |
| Baselines and R1 fixtures | **Read only; not regenerated, not re-pinned** |
| Trade count used as evidence of correctness | **No** |
| "More surviving signals" treated as improvement | **No** — §8.4 states the corrected cap would flip at most 21 decisions and declines to call that a benefit |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
