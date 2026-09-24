# Phase 6M — Regime Classifier and Session-Semantics Audit

**Audit only.** No production source, threshold, RR value, quality threshold,
DEAD_CALM behaviour or regime/style mapping changed. U9 not chosen. No baseline
regenerated. No count in this document was used to select a policy.

**Input:** commit `2750e98` (Phase 6L).

---

# 0. Corrections to Phase 6L, before anything else

Phase 6M re-derived Phase 6L's findings exactly, against the frozen artifacts.
Three of 6L's claims need correcting, and the first is the important one.

### 0.1 Phase 6L over-claimed novelty. Most of it was already registered.

6L's commit message said the DEAD_CALM session finding was "genuinely new". It
was not. `PHASE_2_ISSUES.md` already contains, from Phase 3A:

| Already registered | Where | What it says |
|---|---|---|
| **D8** | `PHASE_2_ISSUES.md:379` | `LondonNewYork` unreachable; *"during New York hours MICRO_SCALP is reachable only when the kill zone is open, which is why New York shows **72 MICRO_SCALP decisions against London's 2,736**"* |
| **D9** | `PHASE_2_ISSUES.md:374` | The H1 ATR gate *"fired **zero** times"* across 15,735 decisions; all 7 L2 blocks were structure |
| **Session × regime table** | `PHASE_2_ISSUES.md:388-393` | **NewYork: DEAD_CALM 1,459** · **Dead: DEAD_CALM 820** |
| **C20** | `PHASE_6C:227` | *"The L0 DEAD gate is **dead in the decision path**; `LondonNewYork` is **unreachable** — both **UNRESOLVED**"* |
| **G2/U10** | `baseline_005/defect_observations.json` | *"detect_regime classifies on absolute-USD M5 ATR bands"* |

The registered session table already gave the DEAD_CALM-by-session split, more
accurately than 6L's join. **What Phase 6L actually added is narrower: the
cross-tabulation of DEAD_CALM against the ATR bands** — that 95 % of DEAD_CALM
is not low-ATR. That part is new and survives. The mechanism was not.

### 0.2 "11 of 24 hours" is wrong. It is **10**.

**MEASURED**, enumerating every hour of a full week under `frozen_clock`:

```
weekday eligible   (14): 00 01 02 03 04 05 06 07 08 09 10 11 12 13
weekday INELIGIBLE (10): 14 15 16 17 18 19 20 21 22 23
```

**Hour 13 is NewYork but falls inside kill zone `(12,14)`**, so it is eligible.
The effective eligible set is therefore **not** `{Asian, London}` as 6L stated —
it is `{Asian, London} ∪ {kill-zone hours}`, which rescues hour 13. Those 13:00
bars are exactly D8's 72 MICRO_SCALP New York decisions.

### 0.3 U-number collisions. Two, and they matter for reading the register.

| ID | Canonical meaning (`PHASE_4B_STRATEGY_AUDIT.md` §H) | Meaning used in Phases 6K–6L |
|---|---|---|
| **U9** | *"`$8.00` H1-ATR gate labelled pips"* | the **RR minimum threshold** decision |
| **U10** | *"Regime ATR bands in **absolute USD**"* — price-level dependent | *"ATR bands labelled 'pip' … actual dollars"* (`PHASE_2_ISSUES.md:37`) |

**U10 carries two different claims under one ID.** Phase 6L resolved the
*labelling* claim and declared U10 "documentation-only". That verdict does not
extend to the second claim. **The absolute-vs-relative question — that regime
selection is a function of gold's price level rather than of volatility — is
untouched and still open.** It is a design question, not a labelling one.

This document uses **U9 = the RR minimum**, per the user's brief and Phases
6K–6L, and flags the collision rather than renumbering anything.

---

# A. The Classification Contract, Branch by Branch

`entry_engine.detect_regime:64-148`. `A` = `m5_atr` (price units, from
`calculate_indicators(frame)["atr_14"]`, read at `frame.iloc[-1]`);
`S` = `get_current_session()`; `K` = `_within_kill_zone()`.

```
A = atr_14 of the last CLOSED M5 bar          S = session(now)    K = kill zone(now)
│
├─ B1  2.5 ≤ A ≤ 4.5  AND  (K OR S ∈ {Asian, London, LondonNewYork})
│        └─► MICRO_SCALP   tp 1.5  risk 0.75  bypass_l3 ✓ bypass_l6 ✓  poi 50  spread 5
│
├─ B2  4.5 ≤ A ≤ 7.0                                    ← no session term
│        └─► REGIME_SCALP  tp 2.0  risk 1.00  bypass ✗ ✗             poi 60  spread 7
│
└─ else ─┬─ B3  A > 7.0                                 ← no session term
         │      └─► INTRADAY_SWING tp 3.0 risk 1.50 bypass ✗ ✗       poi 70  spread 10
         │
         └─ B4  everything else                         ← the catch-all
                └─► DEAD_CALM     tp 1.5  risk 0.75  bypass ✗ ✗      poi 70  spread 5

  B5  any exception  ─► DEAD_CALM  tp 2.0  risk 1.00  poi 70  ... and NO max_spread_pips key
```

| Branch | Exact condition | Regime | Session dependency | Documented? | Tested? |
|---|---|---|---|---|---|
| **B1** | `A >= 2.5 and A <= 4.5 and (K or S in {Asian, London, LondonNewYork})` | MICRO_SCALP | **Yes** — the only regime with one | **Partially.** `architecture.txt:402` documents *"2.5 <= ATR <= 4.5 **+ killzone**"* — **the session alternative is documented nowhere** | **No boundary test.** D8 tests only that `LondonNewYork` is unreachable |
| **B2** | `A >= 4.5 and A <= 7.0` | REGIME_SCALP | None | `architecture.txt:405` says **`4.5 < ATR <= 7.0`** — exclusive, while code is **inclusive**. Immaterial only because B1 claims 4.5 first when eligible | **No** |
| **B3** | `A > 7.0` | INTRADAY_SWING | None | `architecture.txt:408` *"ATR > 7.0"* — **matches** | **No** |
| **B4** | `not B1 and not B2 and A <= 7.0` | DEAD_CALM | **Yes, indirectly** — reached whenever B1's session test fails in band 2.5–4.5 | **No.** `architecture.txt:410` documents *"ATR < 2.5 (blocked at L2)"*, which is **not the implemented condition** | **No** |
| **B5** | any `Exception` | DEAD_CALM | — | **No** | **No** |

**Three properties a reader would not infer from the code:**

1. **`A = 4.5` matches B1 and B2.** B1 wins when the session permits; otherwise
   B2. So a bar at exactly 4.5 in an ineligible session becomes REGIME_SCALP,
   **not** DEAD_CALM — the only band-B value that escapes B4.
2. **B4 is a catch-all, not "A < 2.5".** Its true condition is
   `A ≤ 7.0 AND NOT B1 AND NOT B2`, which includes all of `2.5 ≤ A ≤ 4.5`
   whenever the session test fails.
3. **B5 is a second DEAD_CALM with different config** — `tp_ratio 2.0`,
   `risk 1.0`, and **no `max_spread_pips`, `current_spread` or
   `spread_acceptable` key at all**. Any caller reading those keys gets a
   `KeyError` or a default. It is indistinguishable from B4 by regime name.

### Downstream of the regime

`tp_ratio` → `calculate_entry_levels` target construction → `rr` (tautologically
equal to `tp_ratio`, E9/E10) → `evaluate_entry_for_regime`'s RR admission gate.
`bypass_l3`/`bypass_l6` → skips L3 and L6 entirely. `poi_threshold` → L6.
`max_spread_pips` → **computed, never read** (S9: spread is enforced nowhere).

---

# B. Volatility vs Session — Which Model Does the Architecture Intend?

**Answer: Model 1, and the documentation is explicit rather than inferred.**

| Evidence | Class | What it says |
|---|---|---|
| `architecture.txt:399-412` regime table | **DOCUMENTED** | The table's only classifying column is **"M5 ATR Cond."**. Every regime is defined by ATR alone. MICRO_SCALP's cell reads *"2.5 <= ATR <= 4.5 **+ killzone**"* — a kill-zone **conjunct**, not a session set |
| `architecture.txt:566` layer table | **DOCUMENTED** | **L0** = `check_pre_trade_gates()`, *"Daily loss OK + **session valid**"*, blocking on *"**DEAD session**"*. **Session eligibility is documented as an L0 concern, separate from regime** |
| `main_production.check_pre_trade_gates:509-514` | **IMPLEMENTATION** | `if session == "DEAD": gates_failed.append(...)` — an independent session filter, exactly as documented |
| `c3cf4df` docstring | **STRONG HISTORICAL** | *"**3-MODE ADAPTIVE SYSTEM** … Reads real-time **volatility and structure**"*, and the declared return contract is `"regime": "MICRO_SCALP \| REGIME_SCALP \| INTRADAY_SWING"` |
| `config.INTRADAY_SESSION_MULTIPLIERS` | **DOCUMENTED** | A session-quality model: `LondonNewYork 0.70 # Best session`, `NewYork 0.70`, `London 0.75`, `Asian 1.30 # Avoid (harder)`, `Dead 2.00 # Block` |

**The config entry is decisive against Model 2.** It records the designer's
ranking of sessions: NewYork and LondonNewYork are **"Best"**, Asian is
**"Avoid"**. `detect_regime`'s eligibility set does the opposite — it **admits
Asian and excludes NewYork**. A session set that admits the session the config
calls "Avoid" and excludes the two it calls "Best" is not an expression of
trading-eligibility intent.

*(`INTRADAY_SESSION_MULTIPLIERS` is **dead config** — referenced only by
`test_integration.py:122`, which asserts it exists. It is evidence of intent,
not of behaviour.)*

**Conclusion.** The architecture intends **Model 1**: regime is a volatility
classification; session eligibility is an independent L0 filter. The session
term inside `detect_regime` is **an undocumented widening of a documented
kill-zone conjunct**, and it is the mechanism by which a volatility classifier
acquired a session dependency it was never specified to have.

**Model 3 is also partly true, and that is the defect:** because the taxonomy
has no name for *"micro-scalp volatility at the wrong time of day"*, DEAD_CALM
is serving as the fallback for that state. It is a proxy for a regime that was
never designed.

---

# C. Session Function Audit

`risk_manager.get_current_session:68-85`.

```python
now = datetime.now(timezone.utc); hour = now.hour
if now.weekday() >= 5:   return "Closed"
if   0 <= hour <  7:     return "Asian"
elif 7 <= hour < 13:     return "London"
elif 13 <= hour < 21:    return "NewYork"
else:                    return "Dead"
```

| Property | Finding |
|---|---|
| **Return values** | `Asian`, `London`, `NewYork`, `Dead`, `Closed` — **enumerated in the function's own docstring**, and `LondonNewYork` is not among them |
| **Timezone** | `datetime.now(timezone.utc)` — correct UTC. Under replay, `frozen_clock` supplies the decision instant (N1) |
| **Boundaries** | Half-open `[start, end)`, no gaps, no overlaps. Every hour maps to exactly one session |
| **Overlap handling** | **None.** The real London/NY overlap (13:00–16:00 UTC) is assigned wholly to `NewYork` |
| **NewYork** | 13:00–20:59. Returned normally; **excluded from `detect_regime`'s eligible set** |
| **LondonNewYork** | **Never returned.** No code path produces it |
| **Dead** | 21:00–23:59 |
| **Closed** | Saturday and Sunday, all hours. **Friday 21:00–23:59 is `Dead`, not `Closed`**; **Sunday 22:00–23:59 is `Closed` although the market has reopened** |
| **Weekend** | By `weekday() >= 5` only — no session-open/close instant |
| **DST** | **None anywhere.** Fixed UTC hours year-round, so the windows drift one hour against real London (BST) and New York (EDT) sessions for part of the year. `core/clock.py` has broker-offset/DST machinery; **the legacy strategy does not use it** (`core.clock` is imported only by `core/` and tests) |

### C.1 Why the config contains `LondonNewYork`

**MEASURED** — the label appears in three production files and is produced by
none:

| Site | Use |
|---|---|
| `entry_engine.py:75` | MICRO_SCALP eligibility set |
| `main_production.py:442` | `session_map` — maps it to `"LONDON"` |
| `config.py:125` | `INTRADAY_SESSION_MULTIPLIERS`, `0.70 # Best session` |

**Classification: STALE CONFIGURATION, with an implementation consequence.**

It is not an intentional naming mismatch: `main_production.get_session_name`
bothers to map `"LondonNewYork" → "LONDON"`, and `config.py` assigns it the best
multiplier. Both are written by someone who expected the value to occur. It is
not merely a documentation defect either, because `entry_engine.py:75` **gates
on it** — a dead disjunct in a live condition. The natural referent is the
13:00–16:00 overlap, which `get_current_session` collapses into `NewYork`;
**whether that overlap should be a distinct session is an unresolved design
decision**, and it is the same decision as §G.4.

Already registered as **D8** with a full-week enumeration test
(`tests/backtest/test_baseline_defects.py:217`).

### C.2 Five vocabularies for one concept

| # | Site | Vocabulary | Live? |
|---|---|---|---|
| 1 | `risk_manager.get_current_session` | `Asian / London / NewYork / Dead / Closed` | **Yes** — the only producer |
| 2 | `entry_engine.detect_regime` | `{Asian, London, LondonNewYork}` | **Yes** — MICRO_SCALP only |
| 3 | `main_production.get_session_name` | `ASIAN / LONDON / NY / DEAD` (`Closed`→`DEAD`, `LondonNewYork`→`LONDON`) | **Yes** — L0 gate, L7 bonus |
| 4 | `main_production._normalize_session_for_conf` | `LONDON / NEWYORK / ASIAN / DEAD / OTHER` | **Yes** — confidence engine |
| 5 | `config.INTRADAY_SESSION_MULTIPLIERS` | `LondonNewYork / London / NewYork / Asian / Dead` | **No** — dead config |

They disagree on membership (#2 vs #3), on ranking (#2 vs #5), and on whether
`Closed` exists at all (#3 folds it into `DEAD`; #5 omits it).

### C.3 The DEAD-window message is wrong at both ends

`main_production.py:512` fails L0 with *"DEAD SESSION: no trading between
**22:00 and 03:00** UTC"*, while `get_current_session` returns `Dead` for
**21:00–23:59** and `Asian` for 00:00–06:59. The gate blocks 21:00–23:59 and
never blocks 00:00–02:59. Registered in `PHASE_4B_STRATEGY_AUDIT.md` §H as
*"DEAD-session window disagreement — 21:00 vs 22:00"*; this audit adds that the
`03:00` end is wrong too.

---

# D. Historical Archaeology

### D.1 DEAD_CALM was never a designed regime

The earliest implementation, `c3cf4df` (2026-07-01), declares its contract as:

```
FIX #7 (PHASE 4): DETECT TRADING REGIME - 3-MODE ADAPTIVE SYSTEM
Reads real-time volatility and structure to choose the correct entry mode.
  - MICRO_SCALP:    M5 ATR 2.5-4.5 + Kill Zone + tight range
  - REGIME_SCALP:   M5 ATR 4.5-7.0 + H1 structure intact
  - INTRADAY_SWING: M5 ATR >7.0 (high volatility)
Returns: { "regime": "MICRO_SCALP | REGIME_SCALP | INTRADAY_SWING", ... }
```

**Three modes. DEAD_CALM is absent from the declared return contract**, though
the code below it produces DEAD_CALM. It was implemented as a fallback and never
promoted into the documented taxonomy.

### D.2 The author's own comment proves the fall-through was not intended

Same commit, the branch that produces DEAD_CALM:

```python
else:  # M5 ATR > 7.0 OR < 2.5
    ...
    else:
        # Dead calm (ATR < 2.5) - Will be BLOCKED by L2, but show proper config anyway
        regime = "DEAD_CALM"
        risk = 0.75          # Show a value even though trade won't happen
        tp_ratio = 1.5       # Realistic if it somehow escaped L2
        poi_threshold = 70   # Normal threshold (won't matter, L2 blocks first)
        max_spread_pips = 5.0  # N/A (will be blocked at L2)
```

**`else:  # M5 ATR > 7.0 OR < 2.5` is false, and it is false because of the
session test the author wrote four lines above.** The `else` is also reached
whenever `2.5 ≤ A ≤ 4.5` and the session test fails. **The author did not
anticipate that band-B bars could arrive here.** That comment is the single
clearest piece of evidence in the repository that the catch-all is an
implementation defect rather than a design choice. It no longer exists at HEAD;
the logic does.

The config comments confirm, independently, that **DEAD_CALM was never intended
to trade** — every value is annotated as cosmetic, predicated on L2 blocking
first. (Consistent with Phases 6K-B and 6K-E.)

### D.3 Answer to the specific question

> Was DEAD_CALM ever intended to mean: (1) low volatility, (2) outside trading
> session, (3) both, (4) fallback/default, (5) something else?

**(1) and (4). Never (2), and there is no evidence for (3) or (5).**

| Source | Stated meaning |
|---|---|
| `c3cf4df` comment | *"Dead calm (**ATR < 2.5**)"* |
| `c3cf4df` reasoning string, unchanged at HEAD | *"DEAD_CALM: M5 ATR {…} **too low** → Will be BLOCKED at L2"* |
| `architecture.txt:101` | *"DEAD_CALM **<2.5**"* |
| `architecture.txt:410` | *"DEAD_CALM \| **ATR < 2.5** \| (blocked at L2)"* |
| `architecture.txt:202` | *"H1 ATR < 8 pips = **DEAD CALM** -> BLOCK"* |
| `c3cf4df` docstring | absent from the 3-mode contract → **(4) fallback** |

**Every source that defines DEAD_CALM defines it by volatility alone. Not one
mentions session.**

### D.4 Corroboration that the bands are dollars, from the same commit

`c3cf4df` annotates the spread limits: MICRO_SCALP *"Tight spreads needed for
**75-pip** targets"*, REGIME_SCALP *"**100+ pips** target"*, INTRADAY_SWING
*"**150+ pips** targets"*. At `tp_ratio` 1.5 / 2.0 / 3.0 each implies a stop
distance **R ≈ 50 pips = $5.00**.

A $5.00 stop against an ATR band of $2.5–7.0 is roughly 0.7–2× ATR — ordinary.
Against a band of 2.5–7.0 **pips** ($0.25–0.70) it would be 7–20× ATR. **This is
independent evidence, written at the same moment by the same author, that the
bands are dollars** — and it did not come from measuring the current dataset.

---

# E. Frozen-Data Decomposition

**MEASURED.** `detect_regime` was re-executed over the frozen dataset
(`433b7e27…`) at every decision instant under `frozen_clock`, recording
`(session, kill_zone, m5_atr, regime)` per decision. **This is not a join.**

**Verification:** the run reproduced **15,735 decisions** and the regime totals
**2,312 / 1,810 / 5,121 / 6,492**, identical to `baseline_005`
`regime_statistics.json`. The instrument is exact.

### E.1 Session × regime

| Session | DEAD_CALM | INTRADAY_SWING | MICRO_SCALP | REGIME_SCALP | Total |
|---|---|---|---|---|---|
| Asian | 18 | 327 | 2,313 | 2,382 | 5,040 (32.03 %) |
| London | 15 | 121 | **2,736** | 1,444 | 4,316 (27.43 %) |
| NewYork | **1,459** | 1,277 | **72** | 2,191 | 4,999 (31.77 %) |
| Dead | 743 | 44 | 0 | 317 | 1,104 (7.02 %) |
| Closed | 77 | 41 | 0 | 158 | 276 (1.75 %) |
| **Total** | **2,312** | **1,810** | **5,121** | **6,492** | **15,735** |

**London 2,736 vs New York 72 reproduces D8 exactly.**

*Register correction:* `PHASE_2_ISSUES.md:388-393` lists *"Dead (21-24 UTC)
1,380"* and has no `Closed` row. **1,104 + 276 = 1,380** — that table computed
session by hour and dropped the weekday test, folding `Closed` into `Dead`.
Asian, London and NewYork match exactly.

### E.2 DEAD_CALM decomposition — the requested quantities

| Quantity | Count | Share of DEAD_CALM |
|---|---|---|
| **Genuinely low-ATR** (`A < 2.5`) | **119** | **5.15 %** |
| **Normal-ATR classified DEAD_CALM** (`2.5 ≤ A ≤ 4.5`) | **2,193** | **94.85 %** |
| — of which **session-driven**, NewYork | 1,429 | 61.81 % |
| — of which **session-driven**, Dead | 687 | 29.71 % |
| — of which **weekend/Closed** | 77 | 3.33 % |
| — of which in an **eligible** session | **0** | **0 %** |
| **High-ATR classified DEAD_CALM** (`A > 4.5`) | **0** | 0 % |
| **Other fallback path** (B5, exception) | **0** | 0 % — no decision errored |

**100 % of the 2,193 are in sessions that fail B1's test**, and **zero** are in
an eligible one. The 12 stray "eligible" entries in Phase 6L were join noise.

The 119 genuinely-calm bars split Dead 56 · NewYork 30 · Asian 18 · London 15.

**Zero DEAD_CALM above 4.5 is structural, not incidental**: band C always
matches B2, which has no session term, so nothing in 4.5–7.0 can reach B4.
DEAD_CALM is therefore exactly `(A < 2.5) ∪ (band B ∧ ¬eligible)`.

### E.3 The diversion rate — what the session test does to band B

| Band B (`2.5 ≤ A ≤ 4.5`) | Count | Share |
|---|---|---|
| → MICRO_SCALP | 5,121 | **70.02 %** |
| → DEAD_CALM | 2,193 | **29.98 %** |
| **Total** | **7,314** | |

| Session | Band-B bars | → MICRO_SCALP | → DEAD_CALM | Diverted |
|---|---|---|---|---|
| Asian | 2,313 | 2,313 | 0 | 0 % |
| London | 2,736 | 2,736 | 0 | 0 % |
| **NewYork** | **1,501** | **72** | **1,429** | **95.20 %** |
| Dead | 687 | 0 | 687 | 100 % |
| Closed | 77 | 0 | 77 | 100 % |

**Three in ten bars at micro-scalp volatility are classified "dead calm". In
New York, 95 % of them are.** The 72 survivors are hour 13, inside kill zone
`(12,14)`.

### E.4 Weekend behaviour — a latent hole with zero occurrences

**MEASURED:** 276 weekend decisions, all `Closed`, **all at hours 22 and 23
only**, and `kill_zone` was **True in 0 of them**.

`_within_kill_zone` inspects `.hour` and **never checks the weekday**, so a
weekend bar at 08, 09, 12 or 13 UTC would satisfy B1 and classify **MICRO_SCALP
with both bypasses**, while `get_current_session` says `Closed`. **This dataset
contains no weekend bars at those hours, so the path has never been taken.**
Latent, not active — stated here so it is not mistaken for an observed effect.

Separately, **199 weekend decisions did reach tradeable regimes** —
REGIME_SCALP 158 and INTRADAY_SWING 41 — because **B2 and B3 have no session
term at all**. They were not blocked, because the L0 session gate is not in the
replayed path (§G.2).

---

# F. Temporal Correctness

**MEASURED across all 15,735 decisions, on all six timeframes:**

```
future-bar violations (last visible bar's close_time > replay_time):  0

smallest (replay_time − last_bar_close):
  M1 0:00:00   M5 0:00:00   M15 0:00:00   H1 0:00:00   H4 0:00:00   D1 1:05:00
```

A minimum of exactly zero is the documented boundary rule working: a bar closing
**at** the instant is visible, one closing after it is not.

| Check | Finding |
|---|---|
| **Bar visibility** | `bar.open_time + duration <= T`, by `searchsorted(..., side="right")` on a precomputed close-time array. Future bars are **not materialised**; the frame is a defensive `.copy()` with a fresh index |
| **ATR lookback** | `calculate_indicators` reads `frame.iloc[-1]` — the newest **closed** bar. `ta.atr(length=14)` is strictly backward-looking |
| **Timezone conversions** | All comparisons in UTC; `frozen_clock` supplies a tz-aware instant and converts with `astimezone(timezone.utc)` |
| **Session / kill-zone boundaries** | Derived from the replay instant via N1/N2, not the wall clock. Both are pure functions of that instant |
| **Higher-timeframe alignment** | **H4 opens at 01, 05, 09, 13, 17, 21 UTC; D1 opens at 21 UTC** — broker-native UTC+3, exactly as **D3** documents, preserved rather than re-cut. **`detect_regime` reads only M5, M15 and H1, all UTC-aligned, so the regime path is unaffected** |
| **No look-ahead** | Future-mutation tests in `tests/backtest/test_leakage.py` and `tests/integration/test_integration_leakage.py` mutate bars after a cutoff and assert decisions, entry/stop/target and every layer payload are unchanged |

**Verdict: VERIFIED CORRECT.** No look-ahead in the regime or session path.

**Two test gaps, not correctness defects:**

1. **`regime` and `session` appear in neither leakage test file.** The suite
   pins entry price, stop, target, direction, signal type and layer payloads
   under future mutation — **but never asserts that the regime classification is
   unchanged.** The property holds by construction; nothing tests it.
2. **`test_result_is_independent_of_the_machine_timezone` is vacuous on
   Windows.** It sets `os.environ["TZ"]` and calls `time.tzset()` only
   `if hasattr(time, "tzset")`. **MEASURED: `hasattr(time, "tzset")` is `False`
   on this platform**, so the three runs are identical and the assertion cannot
   fail for the reason it names. It degrades to a determinism check here.

---

# G. Final Classification

### G.1 Issue-by-issue

| # | Issue | Classification | Registered as |
|---|---|---|---|
| 1 | **DEAD_CALM's `else` is a catch-all**; 94.85 % of it is band-B, session-diverted | **IMPLEMENTATION DEFECT** — the `# M5 ATR > 7.0 OR < 2.5` comment shows the author did not intend it (§D.2) | **New** (mechanism in D8) |
| 2 | **No regime exists for "band-B volatility, ineligible session"** | **DESIGN AMBIGUITY** — the taxonomy has no name for the state | **New** |
| 3 | `LondonNewYork` gated on but never produced | **IMPLEMENTATION DEFECT** (dead disjunct) + **STALE CONFIGURATION** | **D8**, UNRESOLVED |
| 4 | Session term inside a volatility classifier, undocumented | **IMPLEMENTATION DEFECT** — `architecture.txt` documents *"+ killzone"* only | **New** |
| 5 | Eligibility set contradicts `INTRADAY_SESSION_MULTIPLIERS` (admits "Avoid", excludes "Best") | **DESIGN AMBIGUITY** | **New** |
| 6 | L0 DEAD-session gate absent from the replayed path | **UNUSED/DEAD LOGIC** (in replay) | **C20**, UNRESOLVED |
| 7 | H1 `< 8.0` "pips" gate — 0 firings, inert under both unit readings | **UNUSED/DEAD LOGIC** + **DOCUMENTATION DEFECT** | **D9 / U9(canonical)** |
| 8 | DEAD-session message *"22:00 and 03:00"* vs implemented 21:00–23:59 | **DOCUMENTATION DEFECT** | registered (21:00 vs 22:00); 03:00 is **new** |
| 9 | `INTRADAY_SESSION_MULTIPLIERS` never read | **UNUSED/DEAD LOGIC** | **New** |
| 10 | Five session vocabularies disagreeing on membership and ranking | **DESIGN AMBIGUITY** | **New** |
| 11 | No DST handling; `core.clock` exists and is unused by the strategy | **DESIGN AMBIGUITY** (deliberate legacy/canonical split) | partially, via `core/` |
| 12 | `_within_kill_zone` ignores weekday — weekend MICRO_SCALP possible | **IMPLEMENTATION DEFECT**, **latent: 0 occurrences** | **New** |
| 13 | B2/B3 classify tradeable regimes on weekends (199 decisions) | **IMPLEMENTATION DEFECT**, consequence of #6 | **New** |
| 14 | B5 error path returns DEAD_CALM with different config and missing keys | **IMPLEMENTATION DEFECT**, **latent: 0 occurrences** | **New** |
| 15 | `architecture.txt` says REGIME_SCALP `4.5 <`, code says `>= 4.5` | **DOCUMENTATION DEFECT**, immaterial | **New** |
| 16 | `regime`/`session` absent from leakage tests | **TEST GAP** | **New** |
| 17 | No test exercises any ATR boundary or any (ATR, session) → regime pair | **TEST GAP** | **New** (6L) |
| 18 | Timezone-independence test vacuous on Windows | **TEST GAP** | **New** |
| 19 | Session boundary hours (0, 7, 13, 21) untested; only mid-range hours 3/9/15/23 | **TEST GAP** | **New** |
| 20 | Temporal correctness of the regime path | **VERIFIED CORRECT** (§F) | — |
| 21 | Regime totals reproduce `baseline_005` exactly | **VERIFIED CORRECT** | — |

### G.2 What the current system actually means by DEAD_CALM

> **DEAD_CALM = `M5 ATR < 2.5` **OR** `2.5 ≤ M5 ATR ≤ 4.5` outside
> {Asian, London, kill-zone hours}.**
>
> In the frozen data that is **5.15 % low volatility and 94.85 % "normal
> volatility at the wrong hour"** — predominantly the New York session.

It is not a volatility regime. It is the union of one volatility state and one
calendar state, sharing a name and a `tp_ratio` chosen for the first.

### G.3 What the evidence says it was intended to mean

> **Low volatility only — `M5 ATR < 2.5` — and never a tradeable regime.**

Four independent sources agree (§D.3): the earliest comment, the reasoning
string still live at HEAD, and two places in `architecture.txt`. None mentions
session. The `c3cf4df` config comments show it was expected to be blocked at L2
and its parameters were written as placeholders.

### G.4 Do they agree? **No.**

The disagreement is not a matter of degree. The implemented condition is
**disjoint in kind** from the documented one, and the documented backstop that
made the mismatch harmless — *"will be BLOCKED at L2"* — **has never fired once
in 15,735 decisions** (D9). So DEAD_CALM's cosmetic parameters are live
parameters on 2,312 decisions, 2,193 of which are not dead calm.

### G.5 The exact decision required before Phase 7

**One decision, with two parts. It is a strategy decision, not a repair.**

> **D-6M-1 — Does session eligibility belong inside regime classification?**
>
> **(a)** If **no** (Model 1, which the architecture documents): the session
> term leaves B1, `detect_regime` becomes a pure volatility classifier, and
> session eligibility must be enforced somewhere that is actually in the
> decision path — which requires resolving **C20**, because the L0 gate is not.
> Band B then classifies MICRO_SCALP at all hours, and DEAD_CALM reverts to its
> documented meaning (119 decisions, 0.76 %).
>
> **(b)** If **yes** (Model 2): the taxonomy needs a **name for band-B volatility
> in an ineligible session**, because overloading DEAD_CALM is what produced this
> defect. The eligible set must then be stated deliberately — and reconciled with
> `INTRADAY_SESSION_MULTIPLIERS`, which ranks the sessions in the opposite order.

**Subordinate to whichever is chosen**, and not decidable before it:

1. What `LondonNewYork` was meant to name, and whether the 13:00–16:00 overlap
   is a distinct session (**D8**).
2. Whether the kill zone should be weekday-aware (#12).
3. Whether B2/B3 should have any session term at all (#13).

**Not part of this decision:** the ATR band *values*, the band *units*
(documentation-only, Phase 6L), the RR minimum (U9), and the quality
thresholds.

### G.6 Can U9 proceed?

**U9 remains blocked, and this audit strengthens the reason rather than
weakening it.**

DEAD_CALM carries `tp_ratio = 1.5` against the default `rr >= 2.0` gate. Both
numbers were chosen for a regime the author expected never to trade. They now
apply to **2,312 decisions, 2,193 of which are not the market condition either
number was chosen for**. Choosing a minimum RR for DEAD_CALM before D-6M-1 means
setting a threshold for a population whose composition is about to change by a
factor of nineteen — 2,312 decisions under option (b), 119 under option (a).

**After D-6M-1 is decided, U9 can proceed**, because the regime populations
become stable and each regime's threshold would then apply to the market
condition it names. **Nothing in this audit selects between (a) and (b).**

---

# 8. Scope Confirmation

| | |
|---|---|
| Production source | **Unchanged.** `git diff` empty for all `*.py` |
| U9 / RR values / quality thresholds | **Untouched** |
| DEAD_CALM behaviour, regime/style mappings | **Unchanged** |
| Baselines | **Not regenerated, not re-pinned, not read-modified** |
| Counts used to choose a policy | **None.** §G.5 presents (a) and (b) without preference |
| Optimisation for trade count or profitability | **None** |
| Temporary instrumentation | Run from the scratchpad, removed; tree clean |

**No profitability conclusion is drawn or available:** the four admitted signals
have never been executed, held or closed in any measurement.
