# Phase 6N — Regime/Session Contract and ATR-Band Architecture Decision

**Audit and design pass. No source changed.** No threshold, RR value, quality
threshold, DEAD_CALM behaviour, regime/style mapping or baseline touched.
U9-RR not chosen. No count was used to select an option.

**Input:** commit `69d4076` (Phase 6M).

**Terminology** as given: **U9-H1** (H1 ATR gate) · **U9-RR** (RR minimum,
unresolved) · **U10-A** (pips-vs-dollars labelling, resolved) · **U10-B**
(absolute vs relative bands, unresolved).

---

# 0. Corrections

### 0.1 The brief's regime totals are transposed

The brief's item 1 lists `MICRO_SCALP 2312 / REGIME_SCALP 1810 /
INTRADAY_SWING 5121 / DEAD_CALM 6492`. Those values are correct but the labels
are rotated — and item 1 contradicts the brief's own item 2, which gives
DEAD_CALM = 2,312.

**`baselines/baseline_005/regime_statistics.json`, frozen:**

| Regime | Decisions | Share |
|---|---|---|
| **DEAD_CALM** | **2,312** | 14.69 % |
| **INTRADAY_SWING** | **1,810** | 11.50 % |
| **MICRO_SCALP** | **5,121** | 32.55 % |
| **REGIME_SCALP** | **6,492** | 41.26 % |

Also: item 2 says *"at the decision-level join"*. Phase 6M used **no join** — it
re-executed `detect_regime` at every decision instant and reproduced the frozen
totals exactly. The distinction matters because the join was 6L's error.

### 0.2 Phase 6L measured the wrong H1 statistic

6L reported *"H1 ATR min 11.68"* from `ta.atr(...)`. **Production does not use
ATR for this gate.** `main_production.py:675-676` computes

```python
ranges_h1 = h1_data["high"].tail(14) - h1_data["low"].tail(14)
h1_atr = ranges_h1.mean()          # mean(high - low) — ignores gaps; not ATR
```

**MEASURED with the production formula over all 15,735 decisions:** min
**10.903**, p1 11.591, median 18.426, max 39.829.

| `h1_atr < 8.0` read as | Decisions blocked |
|---|---|
| dollars (as implemented) | **0** |
| pips = $0.80 | **0** |

**The conclusion is unchanged — 0 firings under both readings, corroborating
D9 — but the number and the statistic in 6L were wrong.**

`core/indicators.py:8-20` already registers this as one of **four mutually
incompatible ATR implementations**; this H1 one is *"`mean(high - low)` over 14
bars — **ignores gaps**"*.

### 0.3 Phase 6M undercounted the session vocabularies

6M said five. **There are seven**, two of which 6M missed
(`confidence_engine._get_session_adjustment`, `strategy_engine`) — see §D.3.

---

# 1. Evidence Table

| # | Source | Class | What it establishes |
|---|---|---|---|
| 1 | `architecture.txt:399-412` | **DOCUMENTED** | Regime table classifies on **"M5 ATR Cond." alone**; MICRO_SCALP is *"2.5 <= ATR <= 4.5 **+ killzone**"* — no session set |
| 2 | `architecture.txt:566` | **DOCUMENTED** | **L0** = *"Daily loss OK + **session valid**"*, blocks *"DEAD session"* — session eligibility is an L0 concern |
| 3 | `c3cf4df` docstring | **STRONG HISTORICAL** | *"**3-MODE ADAPTIVE SYSTEM**"*; return contract `"MICRO_SCALP \| REGIME_SCALP \| INTRADAY_SWING"` — **DEAD_CALM absent** |
| 4 | `c3cf4df` branch comment | **STRONG HISTORICAL** | `else:  # M5 ATR > 7.0 OR < 2.5` — **false**, because B1's session test diverts band-B bars there |
| 5 | `confidence_engine.REGIME_WEIGHTS:13-35` | **IMPLEMENTATION** | Keys: MICRO_SCALP, REGIME_SCALP, INTRADAY_SWING, **DEFAULT**. **No DEAD_CALM** |
| 6 | `entry_engine.py:684-690` | **IMPLEMENTATION** | `allowed_styles`: MICRO_SCALP→`["MOMENTUM"]`, INTRADAY_SWING→`["PULLBACK"]`, **everything else→both**. No DEAD_CALM branch |
| 7 | `entry_engine.evaluate_entry_for_regime:781+` | **IMPLEMENTATION** | Branches for the same three regimes; **DEAD_CALM falls to the default** |
| 8 | **`strategy_engine._validate_session_rules:1202`** | **IMPLEMENTATION** | **A complete Model-1 session gate**: *"`Asian`: Only BUY · `Dead`: Restricted entries · `Closed`: NO ENTRIES"*. Called first in `_run_entry_validations` — *"Hard pre-entry checks"*. **`strategy_engine` is not imported by `main_production`** |
| 9 | `entry_engine.py:618-623` | **IMPLEMENTATION** | `core_trigger = bool(kill_zone and displacement and fvg and m1_choch)` — **every MOMENTUM entry requires the kill zone** |
| 10 | `indicators.py:61-65, 189-190` | **IMPLEMENTATION** | `atr_ratio = atr_14 / atr_average_20` and `volatility_classification` — **a scale-free volatility measure already computed on the same frame** |
| 11 | `entry_engine.py:534` | **IMPLEMENTATION** | `if m5_snapshot.get("atr_ratio") >= 1.0: quality += 0.5` — **`entry_engine` itself consumes the relative measure** |
| 12 | `bias_engine.py:71-79` | **IMPLEMENTATION** | `_calculate_ema_threshold` → `max(floor, atr_14 * atr_ratio)` — **ATR-proportional threshold with an absolute floor** |
| 13 | `technical_engine.py:66` | **IMPLEMENTATION** | `atr_ratio < 0.7` — a relative threshold |
| 14 | `indicators._classify_trend:30-43` | **IMPLEMENTATION** | Normalises by ATR (`0.35`) or by price (`0.0015`) — **two scale-free idioms in the file that computes `atr_14`** |
| 15 | `config.py:80` | **DOCUMENTED** | `SYMBOL: str = "XAUUSD"` — single instrument. Intermarket symbols are reference feeds, not tradeable |
| 16 | `core/indicators.py:24-27` | **DOCUMENTED** | *"the consuming thresholds (`m5_atr >= 2.5`, `h1_atr < 8.0`) are written **as though the value were pips** when it is in fact quote-currency price"* |
| 17 | **MEASURED** — price quintiles | **IMPLEMENTATION** | Regime mix is **stable** across the dataset's 18.6 % price range; `corr(price, m5_atr) = 0.149` (§E.3) |
| 18 | **MEASURED** — kill-zone reachability | **IMPLEMENTATION** | **3,803 of 5,121 MICRO_SCALP decisions (74.3 %) cannot produce an entry** (§C.3) |
| 19 | `config.INTRADAY_SESSION_MULTIPLIERS` | **DOCUMENTED** | `LondonNewYork 0.70 # Best`, `NewYork 0.70`, `Asian 1.30 # Avoid`. **Dead config** — read only by `test_integration.py:122` |
| 20 | `confidence_engine._get_session_adjustment:52-60` | **IMPLEMENTATION** | **LONDON and NEWYORK both Tier 1 (+8.0)**; ASIAN 0.0; DEAD −15.0 |

---

# 2. PART A — Regime/Session Separation

**Model 1 is confirmed, and Phase 6N adds the strongest evidence yet: the
architecture does not merely *document* Model 1, it *implements* it — twice.**

| Mechanism | Where | Reachable from `main_production.analyze_entry`? |
|---|---|---|
| **L0 session gate** — `if session == "DEAD": fail` | `main_production.check_pre_trade_gates:509` | **No** — called from `main()`, the live loop, not from `analyze_entry` (C20) |
| **Session entry-restriction gate** — `_validate_session_rules` | `strategy_engine.py:1202`, first validator in `_run_entry_validations` (*"Hard pre-entry checks"*) | **No** — `strategy_engine` is imported by no production module |

Both take session as an input, both sit **after** signal formation, and neither
touches volatility classification. **That is Model 1, implemented twice, and
dead both times.**

### 2.1 Contrary evidence, stated fairly

**One construct is Model-2-shaped**: B1's `kill_zone or session in {Asian,
London, LondonNewYork}`. Against it:

- `architecture.txt:402` documents MICRO_SCALP as *"+ killzone"* — a conjunct.
  **The session disjunct appears in no document.**
- **B2 and B3 have no session term at all.** If session belonged in
  classification, the three volatility regimes would not disagree about it.
- `config.INTRADAY_SESSION_MULTIPLIERS` ranks NewYork/LondonNewYork **"Best"**
  and Asian **"Avoid"**; B1 admits Asian and excludes NewYork — the **opposite**.
- `confidence_engine._get_session_adjustment` puts **LONDON and NEWYORK in the
  same Tier 1** and Asian below both. B1 disagrees with that too.

**No source states a Model-2 intent.** The disjunct is best read as an ad-hoc
widening of the documented kill-zone conjunct.

**Model 3 — a third explicit architecture — does exist in the repository**: the
`strategy_engine` lineage, in which session is a *direction-and-eligibility*
gate (`Asian`: BUY only; `Dead`: restricted; `Closed`: none). It is a stricter
Model 1, not a distinct model, and it is dead.

**Verdict: Model 1.**

---

# 3. PART B — DEAD_CALM Semantics

### 3.1 Four independent sources agree the taxonomy is three regimes plus a default

| Source | Named regimes | DEAD_CALM |
|---|---|---|
| `c3cf4df` return contract | MICRO_SCALP, REGIME_SCALP, INTRADAY_SWING | **absent** |
| `confidence_engine.REGIME_WEIGHTS` | same three + `DEFAULT` | **absent → DEFAULT** |
| `entry_engine` `allowed_styles` | MICRO_SCALP, INTRADAY_SWING | **absent → both styles** |
| `entry_engine.evaluate_entry_for_regime` | same three | **absent → default 5.0 / 2.0** |

**DEAD_CALM has no branch in any consumer.** Every consumer reached by a
DEAD_CALM decision handles it through the path written for *"a regime I do not
recognise"*.

### 3.2 Every source that *defines* it, defines it by volatility

`c3cf4df` comment *"Dead calm (**ATR < 2.5**)"* · reasoning string, live at
HEAD, *"M5 ATR … **too low**"* · `architecture.txt:101` *"DEAD_CALM **<2.5**"* ·
`architecture.txt:410` *"**ATR < 2.5** (blocked at L2)"*.

**Not one source mentions session.** There is no evidence for "out-of-session"
or "low volatility + out-of-session".

### 3.3 Source-backed contract statement

> ## DEAD_CALM — contract as evidenced
>
> **Intended:** a **volatility state** — M5 ATR below 2.5 price units — that is
> **not a tradeable regime**. It was never part of the declared adaptive-mode
> contract, and every parameter attached to it was written as a placeholder
> (*"Show a value even though trade won't happen"*, *"Realistic if it somehow
> escaped L2"*, *"won't matter, L2 blocks first"*), predicated on an L2 block
> that **has never fired**.
>
> **Implemented:** the **unclassified residue** of the classifier —
> `ATR < 2.5` **OR** (`2.5 ≤ ATR ≤ 4.5` **AND** session ineligible) — carrying
> a full tradeable configuration and handled downstream by every consumer's
> *default* branch.
>
> **Therefore, of the offered categories: intended = "genuinely low volatility",
> implemented = "invalid/unclassified regime". Never "out-of-session" by
> design — that meaning was acquired accidentally, and it is now 94.85 % of the
> population.**

---

# 4. PART C — What Should Happen to Band-B Bars?

### 4.1 The architecture already provides the answer

**Yes — and it is written down twice** (evidence #2, #8): **a bar retains its
volatility regime and is refused by an independent session gate.** Neither gate
reclassifies the regime; both refuse the *entry*. There is no documented
mechanism anywhere for a session failure to change a volatility label.

`strategy_engine._validate_session_rules` is the more complete of the two: it
takes `(session, direction)`, returns `(allowed, reason)`, distinguishes
`Closed` from `Dead`, and runs as a *"hard pre-entry check"* shared by both
entry styles — i.e. exactly the structural outcome *"retain its volatility
regime but fail session eligibility"*.

**The existing architecture answers Part C. The answer is not implemented in the
live path.**

### 4.2 The current arrangement inverts its own intent

| Regime | n | Allowed styles | Can it fire outside the kill zone? |
|---|---|---|---|
| **MICRO_SCALP** | 5,121 | **MOMENTUM only** | **No** — momentum requires `kill_zone` (#9) |
| REGIME_SCALP | 6,492 | PULLBACK + MOMENTUM | Yes, via pullback |
| INTRADAY_SWING | 1,810 | PULLBACK only | Yes |
| **DEAD_CALM** | 2,312 | **PULLBACK + MOMENTUM** | **Yes**, via pullback |

**DEAD_CALM is less restrictive on entry style than MICRO_SCALP.** A band-B bar
in New York becomes DEAD_CALM and may attempt a pullback at any hour; the same
bar in London becomes MICRO_SCALP and is confined to momentum, which needs the
kill zone.

The session disjunct, presumably meant to *enable* Asian/London scalping,
routes those bars into the **more** restricted style regime and leaves the
excluded ones in the permissive default.

### 4.3 MEASURED — how much of MICRO_SCALP can never trade

| | Count | Share |
|---|---|---|
| MICRO_SCALP total | 5,121 | 100 % |
| Inside kill zone — an entry is possible | 1,318 | 25.7 % |
| **Outside kill zone — structurally cannot produce an entry** | **3,803** | **74.3 %** |

Outside-by-session: **Asian 2,313** (hours 0–6 never overlap a kill zone) and
**London 1,490** (hours 7, 10, 11). Only **18.2 %** of all 15,735 decisions fall
inside a kill zone at all.

**The session disjunct changes the label, the thresholds, the `tp_ratio`, the
bypasses and the style for 3,803 decisions that cannot trade either way.**

---

# 5. PART D — Session Contract

### 5.1 The only producer

`risk_manager.get_current_session` — `datetime.now(timezone.utc)`, patched to
the decision instant under replay (N1).

| Session | UTC interval | Notes |
|---|---|---|
| `Closed` | **Sat & Sun, all hours** | Tested by `weekday() >= 5` first, so it pre-empts every hour rule |
| `Asian` | `[00:00, 07:00)` | |
| `London` | `[07:00, 13:00)` | |
| `NewYork` | `[13:00, 21:00)` | |
| `Dead` | `[21:00, 24:00)` | |
| `LondonNewYork` | **never returned** | Enumerated as impossible by the function's own docstring and by D8's full-week test |

**Overlap:** none. Intervals are half-open, contiguous and disjoint; the real
London/NY overlap (13:00–16:00 UTC) is assigned wholly to `NewYork`.

**Kill zone:** `KILL_ZONES_UTC = ((8,10),(12,14))` → hours **8, 9, 12, 13**,
computed from `.hour` **with no weekday test**. Eligibility for B1 is therefore
hours **0–13 on weekdays** (14 hours) and hours **8, 9, 12, 13 on weekends**.

**Weekend:** by weekday only — no session open/close instant. Friday
21:00–23:59 is `Dead`, not `Closed`; Sunday 22:00–23:59 is `Closed` though the
market has reopened.

**DST:** **none anywhere.** Fixed UTC hours year-round, so the windows drift an
hour against real London (BST) and New York (EDT) for part of the year.
`core/clock.py` carries broker-offset/DST machinery and **the legacy strategy
does not use it**.

### 5.2 The three specific questions

**Why is `LondonNewYork` configured but never returned?** — **Stale
configuration with an implementation consequence.** Three sites expect it
(`entry_engine.py:75` gates on it; `main_production.py:442` maps it to
`"LONDON"`; `config.py:125` gives it the best multiplier). Two of the three are
written by someone who expected it to occur, so it is not an intentional
mismatch. Its natural referent — the 13:00–16:00 overlap — is collapsed into
`NewYork`. **Whether that overlap should be a distinct session is an open design
decision** (§7 D-6N-3). Registered as **D8**.

**Should NewYork be eligible?** — **The repository's own evidence says yes, and
the live classifier says no.** `INTRADAY_SESSION_MULTIPLIERS` rates it `0.70`,
tied best; `_get_session_adjustment` puts it in **Tier 1 alongside London
(+8.0)**; `get_session_name` maps it to `NY`, which **passes** the L0 gate; and
it is 31.77 % of all decisions. **Only B1's set excludes it.** Every other
session-aware component in the repository treats NewYork as a first-class
trading session. *This is evidence, not a recommendation — the change itself is
D-6N-1.*

**Are `Dead` and `Closed` intentionally different?** — **Produced as distinct,
consumed as identical everywhere that is live.**

| Consumer | Treatment | Live? |
|---|---|---|
| `get_current_session` | distinct values | **Yes** |
| `main_production.get_session_name` | **both → `"DEAD"`** | **Yes** |
| `detect_regime` B1 | both ineligible | **Yes** |
| `config.INTRADAY_SESSION_MULTIPLIERS` | `Dead: 2.00`; **no `Closed` key** | No — dead config |
| `strategy_engine._validate_session_rules` | **`Closed` → no entries; `Dead` → restricted** — genuinely different | No — dead module |

**The only component that distinguishes them meaningfully is unreachable.** In
the live path the distinction has no consequence. Under replay it has none
either, because the L0 gate is absent — which is why 276 weekend decisions were
evaluated in full and 199 of them reached tradeable regimes.

### 5.3 Seven session vocabularies

| # | Site | Vocabulary | Live? |
|---|---|---|---|
| 1 | `risk_manager.get_current_session` | `Asian/London/NewYork/Dead/Closed` | **Yes** — sole producer |
| 2 | `entry_engine.detect_regime` B1 | `{Asian, London, LondonNewYork}` | **Yes** |
| 3 | `main_production.get_session_name` | `ASIAN/LONDON/NY/DEAD` | **Yes** |
| 4 | `main_production._normalize_session_for_conf` | `LONDON/NEWYORK/ASIAN/DEAD/OTHER` | **Yes** |
| 5 | `confidence_engine._get_session_adjustment` | `LONDON/NEWYORK` Tier 1, `ASIAN`, `DEAD`, `OTHER` | **Yes** |
| 6 | `config.INTRADAY_SESSION_MULTIPLIERS` | `LondonNewYork/London/NewYork/Asian/Dead` | No |
| 7 | `strategy_engine._validate_session_rules` | `Asian/Dead/Closed` | No |

They disagree on membership (#2 vs #3), on ranking (#2 vs #5, #6), and on
whether `Closed` exists (#3 folds it; #6 omits it; #7 acts on it).

---

# 6. PART E — U10-B: Absolute vs Relative Bands

### 6.1 The codebase contains three threshold idioms

| Idiom | Example | Scale-free? |
|---|---|---|
| **Absolute price constants** | regime bands `2.5/4.5/7.0`; `h1_atr < 8.0`; `sweep_min 2.50`; stop buffer `3.0` | No |
| **ATR-proportional with a floor** | `bias_engine._calculate_ema_threshold` → `max(floor, atr_14 * 0.20)` | Partly |
| **Ratio to its own average** | `atr_ratio = atr_14 / atr_average_20`; `technical_engine`: `< 0.7`; `entry_engine:534`: `>= 1.0` | **Yes** |

### 6.2 The relative measure is already computed, and `entry_engine` already uses it

`indicators.calculate_indicators` returns, from the **same call on the same
frame** that `detect_regime` reads:

- `atr_14` — absolute price units → **used by the regime bands**
- `atr_average_20`, `atr_ratio` — relative
- `volatility_classification` — `"High"`/`"Normal"`, derived from the relative
  measure by `_classify_volatility`

**There is already a relative volatility classifier in `indicators.py`, and
`detect_regime` ignores it.** `entry_engine.py:534` — the same module — reads
`atr_ratio >= 1.0` to award quality. `indicators._classify_trend` normalises by
ATR or by price. **Scale-free thresholds were plainly within the author's
vocabulary, in the very files concerned.**

### 6.3 MEASURED — this dataset cannot discriminate the two readings

Price range **$3,957.51 – $4,695.19**, a span of **18.6 %**.
`corr(price, m5_atr) = **0.1492**`.

| Price quintile | n | MICRO | REGIME | SWING | DEAD | median ATR |
|---|---|---|---|---|---|---|
| $3,957–$4,049 | 3,146 | 34.4 % | 40.3 % | 9.8 % | 15.5 % | 4.51 |
| $4,049–$4,114 | 3,146 | 35.1 % | 38.7 % | 8.8 % | 17.4 % | 4.40 |
| $4,114–$4,334 | 3,149 | 32.4 % | 44.0 % | 8.8 % | 14.9 % | 4.57 |
| $4,334–$4,415 | 3,147 | 35.8 % | 39.4 % | 10.2 % | 14.5 % | 4.49 |
| $4,415–$4,695 | 3,147 | 25.1 % | 43.8 % | **19.9 %** | 11.2 % | **5.04** |

**Across the first four quintiles the mix is flat.** The fifth shifts, but its
**median ATR also rises** (4.49 → 5.04), so price level and volatility are
confounded there and the shift cannot be attributed to price. Expressed
relatively, median ATR is likewise flat (≈ 0.103 %–0.113 % of price).

**G2's registered claim — *"regime selection … is a function of gold's price
level, not of relative volatility"* — is theoretically sound but is NOT
demonstrated by this dataset.** An 18.6 % price move produced no systematic
drift. The concern is real for a large price change; it is not observable here.
*Recorded as a correction to the strength of G2's wording, not to its logic.*

For reference: `m5_atr` as a share of price has median **0.1084 %** (p5 0.0724 %,
p95 0.1977 %), and the current band edges sit at **0.0591 % / 0.1063 % /
0.1653 %** of the median price.

### 6.4 Verdict

> ## **U10-B = MIXED**, and the regime bands specifically are **UNDOCUMENTED**.

**MIXED**, because the architecture demonstrably contains both absolute and
relative volatility thresholds — including a relative one inside `entry_engine`
itself — so there is no single prevailing convention to appeal to.

**UNDOCUMENTED** for the regime bands in particular: **no commit message,
comment, docstring or document anywhere states why `2.5 / 4.5 / 7.0` are
absolute**, or records any calibration rationale. The values are identical at
`c3cf4df`, `4c90b81` and HEAD — **they have never been changed**, so there is
not even a revision history to read intent from.

There is **no multi-symbol evidence**: `config.SYMBOL = "XAUUSD"` is the single
trading instrument, and the intermarket symbols are reference feeds. The bands
are XAUUSD-specific in effect and unstated in code — `detect_regime` never
consults a `SymbolSpecification`.

> **Therefore: choosing between absolute and relative/normalized bands is a NEW
> DESIGN DECISION. It cannot be recovered from the repository, and it cannot be
> settled by this dataset.**

---

# 7. PART F — Downstream Dependency Map

Everything below is selected by `detect_regime`'s output.

### 7.1 Via the `regime_info` dict

| Key | Consumer | Effect |
|---|---|---|
| `tp_ratio` | `entry_engine.calculate_entry_levels` | **Target construction**, hence `rr` (≡ `tp_ratio`, E9/E10) |
| `risk_percent` | `main_production.py:1054` | **Position sizing** — 0.75 / 1.0 / 1.5 % |
| `bypass_l3` | `main_production.py:795` | **Skips L3_PULLBACK entirely** |
| `bypass_l6` | `main_production.py:908` | **Skips L6_POI entirely** |
| `poi_threshold` | L6 | 50 / 60 / 70 |
| `max_spread_pips` | `main_production.py:502` | **Computed, never enforced** (S9) |
| `m5_atr` | `main_production.py:816` | Passed into sweep/structure evaluation |

### 7.2 Via the regime **name**

| Site | Effect | MICRO | REGIME | SWING | DEAD |
|---|---|---|---|---|---|
| `main_production.py:697` | **L1 bias mode** — `use_fast_bias` | fast | fast | slow | **slow** |
| `main_production.py:813, 826` | L3 momentum-fallback handling | — | special | — | — |
| `entry_engine.py:684-690` | **Allowed entry styles** | MOMENTUM | both | PULLBACK | **both** |
| `confidence_engine.REGIME_WEIGHTS` | **L7 component weights** | own | own | own | **DEFAULT** |
| `confidence_engine.py:157` | L7 MICRO-specific adjustment | yes | — | — | — |
| `main_production.py:959` | **L7 confidence threshold** | **55** | 70 | 70 | **70** |
| `evaluate_entry_for_regime` | **L8 quality / RR gate** | 5.0 / **1.5** | 6.0 / 2.0 | 7.0 / 2.5 | **5.0 / 2.0** |

### 7.3 The ordering consequence

**Regime selects `tp_ratio`, and `rr ≡ tp_ratio`.** So the regime label chooses
both sides of the RR comparison. For DEAD_CALM that is `1.5 >= 2.0` — false by
construction (Q3/E9/E10), which is why its 22 L8 arrivals produced nothing.

**Reassigning a band-B bar from DEAD_CALM to MICRO_SCALP would change:**

| | DEAD_CALM | MICRO_SCALP | Direction |
|---|---|---|---|
| `tp_ratio` | 1.5 | 1.5 | unchanged |
| `risk_percent` | 0.75 | 0.75 | unchanged |
| L8 quality | 5.0 | 5.0 | unchanged |
| **L8 RR** | **2.0** | **1.5** | **relaxed — from impossible to satisfiable** |
| L7 threshold | 70 | **55** | relaxed |
| POI threshold | 70 | **50** | relaxed |
| L3 / L6 bypass | no | **yes** | relaxed |
| L1 bias | slow | **fast** | changed |
| L7 weights | DEFAULT | MICRO | changed |
| **Allowed styles** | **both** | **MOMENTUM only** | **restricted — requires kill zone** |

**This is why Part A must be settled before U9-RR.** Any regime/session change
moves decisions across the RR gate, and the gate's threshold is the thing U9-RR
is meant to decide. Deciding the threshold first would fix it against a
population that the architecture decision is about to change.

---

# 8. PART G — Implementation Plan (NOT implementation)

**Nothing below is code, and nothing below is approved. It is the smallest
conceptual change the evidence supports, stated so it can be rejected.**

### 8.1 The smallest change

> **Remove the session term from B1, leaving `detect_regime` a pure function of
> M5 ATR — and nothing else, in that step.**
>
> `if 2.5 <= m5_atr <= 4.5:` → MICRO_SCALP.

That single edit makes the implementation match `architecture.txt:402`'s
classifying column, restores DEAD_CALM to its documented meaning, and removes
the catch-all. It touches one boolean expression.

**It must NOT be bundled with**: re-enabling a session gate, changing the
eligible session set, altering `LondonNewYork`, adding a weekday test to the
kill zone, or any threshold.

### 8.2 What would intentionally change

| | Before | After |
|---|---|---|
| **DEAD_CALM** | 2,312 (14.69 %) | **119 (0.76 %)** — the genuinely low-ATR bars only |
| **MICRO_SCALP** | 5,121 | **7,314** — all of band B |
| REGIME_SCALP / INTRADAY_SWING | 6,492 / 1,810 | **unchanged** |
| 2,193 decisions | DEAD_CALM: both styles, L7 70, RR 2.0 (impossible) | MICRO_SCALP: momentum-only, L7 55, RR 1.5, L3/L6 bypassed |
| `decisions_fingerprint` | `8aef2341…` | **will change** |

**These 2,193 decisions move across the L8 RR gate from structurally impossible
to satisfiable.** That is the point of the change and the reason it is a
strategy decision, not a repair. **Its effect on signal count is unknown and
was deliberately not measured** — measuring it before the decision would invert
the order the brief requires.

**Kill-zone reachability limits it**: 1,429 of the 2,193 are NewYork, of which
only hour 13 is inside a kill zone, and MICRO_SCALP is momentum-only. Most
would still be unable to trigger.

### 8.3 What must remain frozen

`tp_ratio` 1.5 / 2.0 / 3.0 · quality 5.0 / 6.0 / 7.0 · **RR 1.5 / 2.0 / 2.5
(U9-RR)** · bands 2.5 / 4.5 / 7.0 (U10-B) · `KILL_ZONES_UTC` · every
`get_current_session` boundary · `LondonNewYork` at all three sites · risk
percentages · bypass flags · `baseline_004` and `baseline_005` · R1 fixtures.

### 8.4 Sequencing

| Step | Content | Gate |
|---|---|---|
| 1 | **Decide D-6N-1** (§9) | User decision. No code |
| 2 | Pin current behaviour in tests: band boundaries, `(ATR, session) → regime`, DEAD_CALM composition, regime/session under future mutation — **all four are TEST GAPs today** | Tests only; must pass **before** any change |
| 3 | The one-line B1 change, its own commit | Full replay; report Δ per regime **and** the new `decisions_fingerprint` |
| 4 | Re-audit the admission surface against the new populations | Audit only |
| 5 | **Then** U9-RR | Requires 1–4 |

### 8.5 Risks

The 2,193 gain L3 and L6 bypasses at once — MICRO_SCALP is the only regime that
bypasses two layers, so the change is larger than the fingerprint suggests.
`INTRADAY_SESSION_MULTIPLIERS` (#19) and `_get_session_adjustment` (#20) remain
mutually inconsistent afterwards. And the change **removes** the only live
session filter without restoring a replacement — after it, **no session
eligibility check operates in the decision path at all**, which is D-6N-2.

---

# 9. Exact Remaining Design Decisions

| ID | Decision | Blocking | Recoverable from the repo? |
|---|---|---|---|
| **D-6N-1** | **Does session eligibility belong inside regime classification?** Evidence points to **no** (Model 1) | **U9-RR, and everything below** | **Answered by evidence** — §2 |
| **D-6N-2** | Where does session eligibility execute, given both implementations are dead (C20, #8)? Revive `_validate_session_rules`, move L0 into `analyze_entry`, or write a new gate | D-6N-1 step 3 onward | **Mechanism yes** (#8); **placement no** |
| **D-6N-3** | Which sessions are eligible, and is the 13:00–16:00 overlap a distinct session (`LondonNewYork`, D8)? | D-6N-2 | **No** — sources contradict each other |
| **D-6N-4** | **U10-B**: absolute or relative bands? | Not blocking D-6N-1 | **No — new design decision** (§6.4) |
| **D-6N-5** | Should the kill zone be weekday-aware? Latent, 0 occurrences | Low | **No** |
| **D-6N-6** | Should MICRO_SCALP remain momentum-only, given 74.3 % cannot trade? | Interacts with D-6N-1 | **No** |
| **D-6N-7** | **U9-RR** — the RR minimum | **Blocked by D-6N-1** | **No** (6K-D: no value recoverable) |

**U9-RR remains blocked.** D-6N-1 changes the DEAD_CALM population by a factor
of nineteen and moves 2,193 decisions across the very gate U9-RR would set.

---

# 10. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| U9-RR / RR values / quality thresholds | **Untouched, undecided** |
| DEAD_CALM behaviour, regime/style mappings | **Unchanged** |
| Baselines | **Not regenerated, not re-pinned** |
| Counts used to choose an option | **None.** §8.2's signal effect was deliberately **not measured** |
| Optimisation for trade count or profitability | **None** |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available.**
