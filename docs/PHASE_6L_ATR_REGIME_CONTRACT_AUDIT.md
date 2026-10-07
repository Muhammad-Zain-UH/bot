# Phase 6L — U10: ATR / Regime Contract Audit

**Audit only. No production source, threshold, regime/style mapping, DEAD_CALM,
`trigger_quality` or RR value changed.** U9 not chosen. No baseline
regenerated. No interpretation was selected for producing more signals or for
improving the zero-signal result.

**Input:** Phase 6K-G `6465d09`, which established U10 as the first strategic
dependency because regime classification selects `tp_ratio`, every threshold,
the bypass flags and the allowed styles.

## Labels

**DOCUMENTED** · **STRONG HISTORICAL** · **IMPLEMENTATION** · **TEST** ·
**INFERENCE**

---

# 1. Verdict

**The unit question is answerable, and the answer is the opposite of what U10
assumes.**

**MEASURED:** under a **pips** reading, **100 % of 20,114 M5 bars classify as
INTRADAY_SWING** — the classifier collapses to a single regime. Under the
**dollars** reading as implemented, the bands cut through the middle of the
observed distribution (median ATR **$4.75**, bands at 2.5 / 4.5 / 7.0).

**INFERENCE, and it is strong:** the band *values* can only have been chosen
against a dollar-valued quantity. A pips intent would have produced a degenerate
classifier from the first run. **`PHASE_2_ISSUES.md` U10 records the intended
unit as "pips" and the actual as "dollars"; the measurement shows the intent
cannot have been pips for these bands.** The **label** is wrong, not the
arithmetic.

**So U10, for the M5 regime bands, is a DOCUMENTATION defect — not an
implementation correction and not a strategy decision.**

**But the audit found something larger, and it is not a unit question.**

> ## **DEAD_CALM is 95 % not dead calm.**
>
> **MEASURED:** of 2,269 DEAD_CALM decisions joined to an ATR bar, only **113
> (5.0 %)** have M5 ATR below 2.5. The other **2,156 (95.0 %)** have ATR **at or
> above 2.5** and were classified DEAD_CALM solely because they **failed a
> session test** in the MICRO_SCALP branch and fell through an `else`.
>
> **99.4 % of those are attributable to session**: NewYork 1,386 · Dead 681 ·
> Closed 77 · only 12 in an eligible session.

**`"NewYork"` is not in MICRO_SCALP's eligible session set.** The set is
`{Asian, London, LondonNewYork}`; `get_current_session` returns `"NewYork"` for
13:00–21:00 UTC and **never returns `"LondonNewYork"`** (a dead label recorded
in Phase 4B). **The effective set is `{Asian, London}`**, so 11 of 24 hours are
excluded, and normal-volatility bars in those hours land in a regime named
"dead calm".

---

# 2. Evidence Table

| # | Source / date / commit | ATR quantity | Unit | Boundary | Comparison | Class | Confidence |
|---|---|---|---|---|---|---|---|
| 1 | `indicators.py:130`, HEAD | `ta.atr(high, low, close, 14)` | **price units (dollars)** — pandas_ta returns the same units as its inputs | — | — | **IMPLEMENTATION** | High |
| 2 | `entry_engine.py:39-40`, HEAD | `_atr_from_frame` → `atr_14` | inherits #1 | — | — | **IMPLEMENTATION** | High |
| 3 | `entry_engine.py:74`, HEAD | `m5_atr` | **unlabelled** | 2.5, 4.5 | `>= 2.5 and <= 4.5` | **IMPLEMENTATION** | High |
| 4 | `entry_engine.py:86`, HEAD | `m5_atr` | **unlabelled** | 4.5, 7.0 | `>= 4.5 and <= 7.0` | **IMPLEMENTATION** | High |
| 5 | `entry_engine.py:96`, HEAD | `m5_atr` | **unlabelled** | 7.0 | `> 7.0` | **IMPLEMENTATION** | High |
| 6 | `entry_engine.py:107`, HEAD | — | — | — | **`else` catch-all** | **IMPLEMENTATION** | High — §4.1 |
| 7 | `c3cf4df`, 2026-07-01, `detect_regime` docstring | *"MICRO_SCALP: M5 ATR 2.5-4.5"*, *"REGIME_SCALP: M5 ATR 4.5-7.0"*, *"INTRADAY_SWING: M5 ATR >7.0"* | **no unit given** — while the **same lines** say *"MAX SPREAD: 5 pips"* | as above | — | **DOCUMENTED** | High — the omission is the evidence |
| 8 | `main_production.py:183/218`, `c3cf4df` → `4c90b81` | display | **labelled "pip"**: `f"M5 ATR: {m5_atr:.1f}pip"` | — | — | **DOCUMENTED** | High |
| 9 | `architecture.txt:549`, `SYSTEM_STRUCTURE_DIAGRAM.md:644` | config block | **`# L2 ATR Thresholds (pips)`** — `DEAD_CALM_ATR_THRESHOLD = 8.0`, `HIGH_VOLATILITY_ATR = 15.0` | 8.0, 15.0 | — | **DOCUMENTED** | High — but these are **H1/L2**, not the M5 bands |
| 10 | `architecture.txt:202/758`, `SYSTEM_STRUCTURE_DIAGRAM.md:213` | H1 ATR | *"H1 ATR < 8 pips = DEAD CALM → BLOCK"* | 8.0 | `<` | **DOCUMENTED** | High |
| 11 | `backtest/baseline.py:614`, HEAD | H1 ATR | *"main_production gates on `h1_atr < 8.0` and reports it as 'pips'; the value is quote-currency dollars"* | 8.0 | `<` | **DOCUMENTED** — the repo already records this | High |
| 12 | `core/indicators.py:41`, HEAD | canonical ATR | *"never pips. Convert with `AtrResult.to_pips`"* | — | — | **DOCUMENTED** | High — the canonical module states the rule the legacy path breaks |
| 13 | **Measured**, 20,114 M5 bars | ATR-14 | dollars | — | — | **IMPLEMENTATION** | High — §3 |
| 14 | **Measured**, 1,667 H1 bars | ATR-14 | dollars, min **11.68** | 8.0 | `<` | **IMPLEMENTATION** | High — the gate is **inert**, §4.3 |
| 15 | `tests/` | — | — | — | — | **TEST** | **No test exercises any ATR boundary.** Searched |
| 16 | `risk_manager.get_current_session`, `entry_engine._within_kill_zone` | wall clock, patched under replay by `backtest/clock_patch.py` | — | — | — | **IMPLEMENTATION** | High — replay uses bar time, documented |

---

# 3. A. The Current Mathematical Classification Contract

**OBSERVED**, `entry_engine.detect_regime:74-114`. `A` = `m5_atr` in **price
units**; `S` = session; `K` = kill zone.

```
if 2.5 <= A <= 4.5  AND  (K or S ∈ {Asian, London, LondonNewYork}):
        MICRO_SCALP      tp 1.5  risk 0.75  bypass_l3 ✓  bypass_l6 ✓  poi 50  spread 5
elif 4.5 <= A <= 7.0:
        REGIME_SCALP     tp 2.0  risk 1.00  bypass ✗ ✗                poi 60  spread 7
else:
    if A > 7.0:
        INTRADAY_SWING   tp 3.0  risk 1.50  bypass ✗ ✗                poi 70  spread 10
    else:
        DEAD_CALM        tp 1.5  risk 0.75  bypass ✗ ✗                poi 70  spread 5
```

**Three properties of this contract that are not obvious from reading it:**

1. **`A = 4.5` matches two branches.** Both use closed intervals; the `if` wins,
   so 4.5 is MICRO_SCALP when the session permits and REGIME_SCALP otherwise.
2. **The `else` is a catch-all, not an "ATR < 2.5" branch.** It receives every
   decision the first two did not match, including the whole of `2.5 ≤ A ≤ 4.5`
   whenever the session test fails. **DEAD_CALM's condition is therefore
   `A ≤ 7.0 AND NOT (the two branches above)`**, which is not what its name, its
   `reasoning` string (*"M5 ATR too low"*) or its docstring says.
3. **Session is a term in a volatility classifier.** MICRO_SCALP is the only
   regime with a non-ATR term, and its failure mode is not "no regime" but
   "DEAD_CALM".

---

# 4. B–D. Unit Evidence, Ambiguity, and Consequences

## 4.1 The ambiguity, stated exactly

**The M5 band values carry no unit anywhere in code, in any commit.** The
quantity they compare is **displayed** with a `pip` suffix (#8) and the
neighbouring **H1** thresholds are documented `(pips)` (#9, #10). So a reader has
a label pointing one way and an implementation pointing the other.

**That is the whole of the ambiguity, and it is resolvable by measurement.**

## 4.2 D/E. Consequences of each interpretation — MEASURED

**M5 ATR-14 across 20,114 bars, price units:**

```
min 1.97 · p5 3.08 · p25 3.89 · median 4.75 · p75 5.95 · p95 8.86 · max 19.17
in pips (÷0.10):  p5 30.8 · median 47.5 · p95 88.6
```

| Interpretation | MICRO band | REGIME band | INTRADAY | DEAD_CALM |
|---|---|---|---|---|
| **Dollars** *(as implemented)* | 8,591 · **42.7 %** | 8,545 · **42.5 %** | 2,843 · **14.1 %** | 135 · **0.7 %** |
| **Pips** *(as labelled)* | 0 · **0.0 %** | 0 · **0.0 %** | **20,114 · 100.0 %** | 0 · **0.0 %** |

*(ATR-band membership only; MICRO_SCALP additionally requires the session test,
so its dollar figure is an upper bound.)*

**Under a pips reading every bar in three months is INTRADAY_SWING**, because
the smallest ATR observed is 19.7 pips against a top band of 7.0. The
classifier would have exactly one output, `tp_ratio` would always be 3.0, and
three regimes would be unreachable.

**INFERENCE:** the bands were calibrated against dollars. **This is not a
preference for the interpretation that produces more signals** — under the
dollars reading the dataset produced **zero** signals for its entire history,
and four only after Phases 6I and 6K-F. It is a statement that one
interpretation partitions the data and the other does not.

## 4.3 The H1 gate is inert under **both** readings

**MEASURED**, 1,667 H1 bars: ATR-14 **min 11.68**, median 18.87, max 35.48.

| `h1_atr < 8.0` read as | Bars blocking |
|---|---|
| dollars *(as implemented)* | **0** |
| pips = $0.80 | **0** |

**Corroborated:** `L2_STRUCTURE` blocked **7** decisions in the whole baseline,
and its only recorded reason is *"HN structure is broken"* — never an ATR
reason. **The documented *"H1 ATR < 8 pips = DEAD CALM → BLOCK"* rule has never
fired.** It is the rule DEAD_CALM's cosmetic config was predicated on (Phase
6K-B: *"Will be BLOCKED by L2"*), and it does not work.

## 4.4 The finding that matters more than the units

**MEASURED**, joining the frozen decision stream to M5 ATR (15,674 of 15,735
decisions joined; ~5 % point-in-time offset noise, far below the effect size):

| Regime | ATR < 2.5 | 2.5–4.5 | 4.5–7.0 | > 7.0 | total |
|---|---|---|---|---|---|
| MICRO_SCALP | 6 | **4,896** | 216 | 2 | 5,120 |
| REGIME_SCALP | 0 | 283 | **6,108** | 86 | 6,477 |
| INTRADAY_SWING | 0 | 0 | 100 | **1,708** | 1,808 |
| **DEAD_CALM** | **113** | **2,118** | 38 | 0 | **2,269** |

**DEAD_CALM: 113 genuinely below 2.5 (5.0 %); 2,156 at 2.5 or above (95.0 %).**

**Attribution of those 2,156, by the bar's own session:**

| Session | Count | Share | MICRO_SCALP eligible? |
|---|---|---|---|
| **NewYork** | 1,386 | 64.3 % | **No** |
| **Dead** | 681 | 31.6 % | **No** |
| **Closed** (weekend) | 77 | 3.6 % | **No** |
| Asian | 8 | 0.4 % | yes — join noise |
| London | 4 | 0.2 % | yes — join noise |

**99.4 % is session fall-through.** An independent check needing no join: the
documented criterion *"ATR < 2.5"* predicts **0.7 %** of bars; the observed
DEAD_CALM share is **14.7 %** — a 21× discrepancy no join error explains.

**INFERENCE:** DEAD_CALM is predominantly *"normal volatility, outside the
Asian and London sessions"*. Its `tp_ratio = 1.5`, chosen as *"realistic if it
somehow escaped L2"* for a genuinely dead market, is being applied to 2,156
ordinary New-York-session decisions. **This is a regime-semantics defect, not a
unit defect, and it must not be bundled with U10.**

---

# 5. F. What Resolving U10 Actually Is

**Three separable items. Only the first is U10.**

| # | Item | Classification | Why |
|---|---|---|---|
| **1** | **The M5 band unit label** | **DOCUMENTATION-ONLY** | The values are dollar-calibrated (§4.2); a pips reading is degenerate. Fix the label — the `pip` suffix in the display, and the absent unit in the docstring. **No behaviour changes** |
| **2** | **The H1 `< 8.0` "pips" gate** | **DOCUMENTATION defect + DEAD CODE** | Inert under both readings (§4.3). Relabelling changes nothing; making it fire would be a **new strategy decision** |
| **3** | **DEAD_CALM as an `else` catch-all** | **NEW STRATEGY DECISION** | §4.4. 95 % of the regime is misclassified relative to its own name and documentation. Not a unit question |

**U10 itself — the unit question — is documentation-only and does not block
U9.** The regime boundaries are what they have always been in effect; naming
them correctly changes no classification.

**Item 3 does block U9**, and more directly than U10 did: `tp_ratio = 1.5` and
the `rr >= 2.0` default apply to 2,269 decisions, 95 % of which are not the
market condition that value was chosen for. **Choosing a minimum RR for
DEAD_CALM before knowing what DEAD_CALM contains would be setting a threshold
for a regime that does not mean what its name says.**

---

# 6. Answers to the Numbered Questions

1. **Where ATR is calculated** — `indicators.py:130`, `ta.atr(high, low, close, 14)`.
2. **Units of ATR** — **price units (dollars)** for XAUUSD. pandas_ta returns the units of its inputs.
3. **Units of each boundary** — **unlabelled in code**; dollar-calibrated in effect.
4. **Comparison operators** — `>= 2.5 and <= 4.5`; `>= 4.5 and <= 7.0`; `> 7.0`; then an `else`. Closed intervals overlap at 4.5.
5. **Configuration names/comments** — the M5 bands are **not in `config.py`**; they are literals in `detect_regime`. The documented `# L2 ATR Thresholds (pips)` block covers only the H1 values.
6. **Described as** — **nothing** for the M5 bands; **"pip"** for the displayed value (#8) and the H1 thresholds (#9, #10).
7. **XAUUSD-specific or general?** — **XAUUSD-specific in effect and unstated in code.** No symbol conditioning exists; the values would be meaningless on an instrument with a different price scale.
8. **Spread / tick size / digits involved?** — **No.** `current_spread` is compared to `max_spread_pips` **separately, after** classification. Neither `tick_size`, `digits` nor `pip_size` enters `detect_regime`. It never consults a `SymbolSpecification`.
9. **Did the boundaries change historically?** — **No.** `2.5 / 4.5 / 7.0` are identical at `c3cf4df`, `4c90b81` and HEAD.
10. **Earliest introduction and comments** — `c3cf4df`, with a docstring stating the bands and, on the same lines, spreads in pips. Historical comments explain DEAD_CALM's *config* (*"Will be BLOCKED by L2"*) but never the ATR units.
11. **Documentation explaining the units?** — **For the H1 thresholds, yes ("pips"), and it is wrong (#11). For the M5 bands, no documentation of units exists at all.**
12. **Tests exercising the boundaries?** — **None.** No test in the suite passes an ATR value to `detect_regime`.
13. **Can the classifier be shown to classify differently on unit interpretation alone?** — **Yes, decisively**: 42.7 / 42.5 / 14.1 / 0.7 % under dollars versus **0 / 0 / 100 / 0 %** under pips (§4.2).

---

# 7. Confirmation

| | |
|---|---|
| Source changes | **None.** No `.py` file modified |
| U9 / RR thresholds / quality thresholds | **Untouched** |
| DEAD_CALM, regime/style mappings | **Unchanged** |
| Baselines | **Not regenerated** |
| Interpretation chosen for producing signals | **No.** §4.2 — the dollars reading is the zero-signal one |
| Working tree | Clean; this commit adds one document |

**New evidence recorded:** the measured ATR distributions establishing that the
bands are dollar-calibrated and that a pips reading is degenerate; that the H1
`< 8.0` gate is inert under **both** readings and has never fired; that
`detect_regime` never consults a symbol specification; that no test exercises
any ATR boundary; and the quantified finding that **95 % of DEAD_CALM is a
session fall-through rather than low volatility**, with `"NewYork"` absent from
MICRO_SCALP's eligible session set.

**No profitability conclusion is drawn or available.**
