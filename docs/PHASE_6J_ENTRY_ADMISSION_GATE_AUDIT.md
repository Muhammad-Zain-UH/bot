# Phase 6J — `evaluate_entry_for_regime` Admission Gate Audit

**Audit only.** No trading behaviour, threshold, regime rule or gate was
changed. Nothing was removed or optimised. `baseline_004` and `baseline_005`
untouched, not regenerated, not re-pinned. R1 fixtures unmodified.

**Input:** Phase 6I `8c5724c`, which retired the per-candidate `valid_rr` gate
and identified this surviving gate.

## Labels

**OBSERVED** source · **MEASURED** from a run or a frozen artefact ·
**DERIVED** arithmetic from stated inputs · **DOCUMENTED** stated as intent ·
**UNRESOLVED** deliberately not answered.

---

# Executive Summary

**Five findings.**

**1. The gate is canonical and has one production caller.** No alternate
function performs equivalent admission logic. §A.

**2. `rr` is tautologically derived from `tp_ratio` here too — but not
exactly.** The algebra gives `rr ≡ tp_ratio`; the *implementation* loses the
identity to floating-point error, and the error is the same order as the
distance to the threshold for two of four regimes. §B.

**3. Two of four regimes have a threshold set exactly equal to their own
`tp_ratio`, so admission is decided by representation error.** **MEASURED:** all
972 MICRO_SCALP and all 217 REGIME_SCALP L8 candidates sit within `1e-9` of
their threshold. **263 of 972 MICRO_SCALP candidates (27.1 %) fall below it** —
on nothing but rounding. REGIME_SCALP happened to round the other way in all 217
cases. §C, §E, §G.

**4. The floating-point loss is caused by formula construction, not by binary
representation as such.** `reward_distance` is rebuilt as
`|take_profit − entry_price|` after `take_profit` was formed by adding a small
quantity to a large one. `(risk_distance × tp_ratio) / risk_distance` is
**exactly** the ratio; the round-trip is what destroys it. §E.

**5. DEAD_CALM's fall-through is undocumented, and the one documented
assumption about DEAD_CALM is contradicted by measurement.** The design document
says its config does not matter because it "will be blocked at L2 anyway".
**MEASURED: 22 DEAD_CALM decisions reached L8.** §D.

**Plus a correction to my own Phase 6I output.** The `rr` figure I cited for the
2026-08-06 candidate was computed from a different stop than the candidate had.
Corrected here; the conclusion is unchanged. §G.3.

---

# A. Call-Site and Reachability Audit

**OBSERVED.** Every reference in the repository:

| Site | Kind |
|---|---|
| `entry_engine.py:750` | definition |
| `main_production.py:76` | import |
| **`main_production.py:1021`** | **the only production call** |
| `tests/test_entry_quality_gate.py` (×3) | dedicated tests |
| `tests/backtest/test_valid_rr_retired.py` (×2) | Phase 6I pins |
| `tests/test_layer_gate_logic.py:82` | **mocked out** |

## A.1 The production path

```
main_production.analyze_entry
  └─ entry = get_entry_trigger(...)            L8 candidate construction
  └─ if not entry["entry_triggered"]:          -> block, "Entry triggers not all confirmed"
  └─ gate_result = evaluate_entry_for_regime(entry, regime_info)   :1021
  └─ if not gate_result["entry_allowed"]:      -> block, gate_result["reason"]
  └─ analysis["signal_type"] = "ENTRY_SIGNAL"
```

**DERIVED:** the gate is reached **only** when `entry_triggered` is already
true. It is therefore the **last** admission decision before a signal exists.

## A.2 Is it canonical?

**Yes, by exclusion.** **OBSERVED:** no other function in the repository
performs regime-keyed entry admission. `main.py` does not call it — and `main.py`
places no orders at all (Phase 6G). The backtest reaches it through
`ReplayEngine → main_production.analyze_entry`, the same single path, so
**production and replay share this gate exactly.**

## A.3 It is mocked in the layer-gate tests

**OBSERVED.** `tests/test_layer_gate_logic.py:82` patches it to return
`entry_allowed: True`. Those are two of the suite's two known failures, and both
fail upstream (at L1/L2) without reaching this gate — so the mock currently
exercises nothing either way.

---

# B. Mathematical Audit

## B.1 How `rr` is constructed

**OBSERVED**, `entry_engine.calculate_entry_levels`:

```python
risk_distance   = abs(entry_price - stop_loss)
take_profit     = entry_price ± (risk_distance * tp_ratio)      # sign by direction
reward_distance = abs(take_profit - entry_price)
rr              = reward_distance / risk_distance if risk_distance > 0 else 0
```

The gate then reads `entry["reward_to_risk_ratio"]`, which is this `rr`
propagated unchanged through `_evaluate_*_entry` and `get_entry_trigger`.

## B.2 The algebra

Let `R = risk_distance`, `k = tp_ratio`, `E = entry_price`, and take BUY:

```
take_profit     = E + R·k
reward_distance = |(E + R·k) − E| = R·k          (R > 0, k > 0)
rr              = (R·k) / R = k
```

SELL is the mirror: `take_profit = E − R·k`, `|E − R·k − E| = R·k`, same result.

> **`rr ≡ tp_ratio` exactly, in real arithmetic, for every regime and both
> directions. It carries no information about price, stop, structure or
> volatility.**

**MEASURED confirmation** — 1,265 L8 decisions, maximum deviation from the
regime constant `~3.6e-13`, i.e. float error only.

## B.3 Where `rr` *can* differ materially from `tp_ratio`

**OBSERVED.** Four cases, and only one occurs in practice:

| # | Condition | `rr` | Occurs? |
|---|---|---|---|
| 1 | `risk_distance <= 0` | `0` (guard) | Not on this dataset — a zero-width stop |
| 2 | `calculate_entry_levels` raises | `0.0` (error branch) | Not measured; the branch also returns `stop_loss=None`, which `replay_engine` rejects earlier |
| 3 | The key is absent | `0.0` (`.get` default) | Not on the production path |
| 4 | **Floating-point error in the round-trip** | `k ± ~1e-13` | **Yes — on every decision** |

**DERIVED:** case 4 is the only live one, and it is material **only because two
thresholds are set exactly at `k`**. At a threshold strictly inside `(k−δ, k)`
or `(k, k+δ)` for any `δ ≫ 1e-13`, the error would be irrelevant.

---

# C. Threshold Audit

**OBSERVED** thresholds; **MEASURED** rejection capability.

| Regime | `tp_ratio` | quality ≥ | rr ≥ | Can the rr term reject a mathematically valid candidate? | Evidence |
|---|---|---|---|---|---|
| **MICRO_SCALP** | 1.5 | 5.0 | **1.5** | **YES — and does.** `rr` equals the threshold in exact arithmetic, so the comparison is decided by rounding | 263 of 972 fall below; the 2026-08-06 candidate refused at `1.4999999999998295` |
| **REGIME_SCALP** | 2.0 | 6.0 | **2.0** | **YES in principle — did not on this data.** Same exact equality | 216 of 217 land exactly on `2.0`; one at `2.000000000000023`; **none** below |
| **INTRADAY_SWING** | 3.0 | 7.0 | 2.5 | **No.** `3.0 > 2.5` with a margin of `0.5`, ~12 orders of magnitude above the error | 54 of 54 pass |
| **DEAD_CALM** *(default branch)* | 1.5 | 5.0 | **2.0** | **Not "reject a valid candidate" — it rejects every candidate.** `1.5 < 2.0` structurally | 0 of 22 pass; distance `0.5`, not noise |

**No intent is inferred.** The table records what the code does.

## C.1 The shape of the problem

**DERIVED.** Ordering the regimes by `tp_ratio − rr_threshold`:

| Regime | margin | consequence |
|---|---|---|
| INTRADAY_SWING | `+0.5` | rr term is inert |
| MICRO_SCALP | `0.0` | **decided by rounding** |
| REGIME_SCALP | `0.0` | **decided by rounding** |
| DEAD_CALM | `−0.5` | **always fails** |

Two regimes sit exactly on a knife edge and one sits permanently on the wrong
side. Only one has a margin that makes the comparison meaningful — and there it
can never bind.

---

# D. DEAD_CALM

## D.1 Why it falls through

**OBSERVED.** `evaluate_entry_for_regime` tests `regime_name` against
`"MICRO_SCALP"`, `"REGIME_SCALP"` and `"INTRADAY_SWING"` in sequence. There is
**no `DEAD_CALM` branch**, so control reaches the final unconditional block:

```python
entry_allowed = trigger_quality >= 5.0 and rr >= 2.0
return {..., "reason": "default entry gate", ...}
```

`regime_name` defaults to `"DEFAULT"` when no regime dict is supplied, so the
final block serves both the unknown-regime case and DEAD_CALM.

**DERIVED:** with `tp_ratio = 1.5`, `rr ≈ 1.5 < 2.0` always. **No trigger
quality can admit a DEAD_CALM entry through this gate.**

## D.2 Classification: **undocumented behaviour**, with a contradicted assumption

| Evidence | Finding |
|---|---|
| A `DEAD_CALM` branch | **Does not exist** |
| A comment explaining the fall-through | **None** |
| A document stating DEAD_CALM should use the default | **None found** |
| A document stating DEAD_CALM should be unable to enter | **None found** for *this* gate |
| `tests/test_entry_quality_gate.py` | Tests MICRO_SCALP, REGIME_SCALP, INTRADAY_SWING — **never DEAD_CALM** |
| `SYSTEM_STRUCTURE_DIAGRAM.md:486` | **DOCUMENTED:** DEAD_CALM's config is annotated *"(Will be blocked at L2 anyway)"* |
| `docs/PHASE_4B_TRADE_LIFECYCLE.md:180` | States DEAD_CALM had *"no entry possible, ever"* — but that table is about the **retired `valid_rr`** gate, not this one |

**The one documented assumption is contradicted by measurement.**
**MEASURED:** 22 DEAD_CALM decisions reached L8, and L2_STRUCTURE blocked only
**7** decisions in total across all regimes. DEAD_CALM is not "blocked at L2
anyway".

**Classification: undocumented behaviour that coincides with an outcome a
retired gate used to produce.** It is not an obvious coding slip — the default
branch is deliberate for unknown regimes — but nothing records a decision that
DEAD_CALM should share it. **Not fixed.**

---

# E. Floating-Point Behaviour

## E.1 The cause is formula construction

**DERIVED**, reproduced exactly from the 2026-08-06 candidate's own geometry:

```
entry_price   = 4257.775
stop_loss     = 4255.11
risk_distance = 2.6649999999999636
tp_ratio      = 1.5

risk_distance * tp_ratio              = 3.9974999999999454      <- correct product
take_profit = 4257.775 + 3.99749...   = 4261.772499999999       <- rounds to the grid of 4261
reward_distance = |4261.7724... - 4257.775| = 3.9974999999994907 <- 4.5e-13 has been destroyed

rr = 3.9974999999994907 / 2.6649999999999636 = 1.4999999999998295   -> REJECTED
```

**The same quantity computed without the round-trip:**

```
(risk_distance * tp_ratio) / risk_distance = 1.5   exactly.  -> would be ADMITTED
```

**So the answer to the audit question is: formula construction.** Not binary
representation in the abstract, and not rounding order in the division. The
identity is destroyed by *reconstructing* `reward_distance` from `take_profit`
when the product was already in hand. `entry_price` is **1,065×** larger than
the product, so the addition discards roughly four significant digits of it, and
subtracting `entry_price` back cannot recover them.

**DERIVED:** the error is proportional to `entry_price`, not to the stop. A
higher-priced instrument, or a tighter stop, widens it.

## E.2 Deterministic minimal reproduction

Added as `test_the_loss_is_the_round_trip_through_take_profit`
(`tests/backtest/test_valid_rr_retired.py`). It asserts the product and the
round-tripped value differ, that `product / risk` is exactly `1.5`, and that
`round_tripped / risk` is strictly below it. No production code is touched.

## E.3 Not fixed

Changing `reward_distance` to `risk_distance * tp_ratio`, or comparing with a
tolerance, would alter admission for **263 measured candidates**. That is a
strategy change and is outside this audit. §H.

---

# F. Documentation and Contract Evidence

**Documented intent is nearly absent. Observed behaviour is fully determined.**

| Question | Documented intent | Observed |
|---|---|---|
| Why does this gate exist? | **Nothing found** | Last admission step before a signal |
| Why `quality >= 5.0 / 6.0 / 7.0`? | **No rationale anywhere** | Rises with regime timeframe |
| Why `rr >= 1.5 / 2.0 / 2.5`? | **No rationale anywhere** | Two equal `tp_ratio`; one below; one above |
| Should DEAD_CALM be admissible? | **Nothing found**; only the contradicted "blocked at L2 anyway" | Never admissible |
| Is `rr` meant to be independent here? | **Nothing found** | It is not; §B |

## F.1 The dedicated tests use inputs that cannot occur

**OBSERVED.** `tests/test_entry_quality_gate.py` is the only test written *for*
this gate. It passes `reward_to_risk_ratio` values of `1.4`, `2.4` and `2.8`
against regimes whose `tp_ratio` is `1.5`, `2.0` and `3.0`.

**DERIVED:** since `rr ≡ tp_ratio`, **none of those three `rr` values can ever
occur in production for the regime it is paired with.** The tests pass, and they
exercise the gate with impossible inputs. They therefore provide **no evidence
about production behaviour** — and in particular could never have surfaced the
boundary problem, because no case is placed near a threshold.

`test_micro_scalp_requires_stronger_quality_and_rr` also fails **both** terms at
once (`quality 4.2`, `rr 1.4`), so it cannot distinguish which one bound, and it
asserts on the message text that §G.2 shows to be misattributing.

## F.2 Prior repository findings that bear on this

- `PHASE_2_ISSUES.md` records `U10`: the regime ATR bands are labelled "pip" but
  applied in dollars — **P0**, and it determines which regime a decision lands
  in, hence which row of §C applies. **Unresolved, untouched.**
- `docs/PHASE_4B_DESIGN_REVIEW.md:86` lists `trigger_quality` among L8 outputs
  without stating a threshold rationale.

---

# G. Historical Impact

**MEASURED**, from deterministic evidence already in hand: the Phase 6A probe
(three identical runs) and the Phase 6I replay.

## G.1 How many candidates actually reached the gate

| Stage | Count |
|---|---|
| Decisions | 15,735 |
| Reached L8 | 1,265 |
| `entry_triggered` true → **reached `evaluate_entry_for_regime`** | **4** |
| Admitted (became signals) | **3** |
| Rejected by the gate | **1** |
| Blocked before the gate (`entry_triggered` false) | 1,261 |

**DERIVED:** the gate has decided **4 cases in the whole dataset**. Of the 15
raw-triggered candidates, 11 are MICRO_SCALP pullbacks that the frozen
style restriction excludes from selection, so their `entry_triggered` is false
and they never reach it.

## G.2 The single rejection

| | |
|---|---|
| Timestamp | **2026-08-06 08:00 UTC** |
| Regime / style | MICRO_SCALP / MOMENTUM (LIMIT_FVG) |
| `trigger_quality` | **10.0** — the maximum; passes `>= 5.0` comfortably |
| `rr` | **1.4999999999998295** — fails `>= 1.5` by `1.7e-13` |
| Recorded reason | `"micro scalp quality too low (quality=10.0, rr=1.5)"` |

**The recorded reason is wrong in two ways.** It attributes the rejection to
quality, which passed at the maximum value; and it prints the failing `rr` as
`1.5` — the exact value it failed to reach — because the message formats with
`:.1f`. A reader of the decision log cannot discover why this candidate was
refused. **Not fixed.**

## G.3 Correction to Phase 6I

Phase 6I's document and test cited `rr = 1.4999999999999196` for this candidate.
That value comes from passing `4255.11` as a *sweep wick*, which
`calculate_entry_levels` converts into a stop of `4252.11` by subtracting the
`3.0` buffer — a different geometry. The candidate's own stop **was**
`4255.11`, giving `rr = 1.4999999999998295`.

**The conclusion is unchanged** — both are below `1.5` and both are rejected —
but the figure was not the candidate's. Corrected in
`docs/VALID_RR_CONTRACT.md` and in the test, which now reproduces the
candidate's own geometry.

## G.4 Candidates within floating-point tolerance of a threshold

**MEASURED** across all 1,265 L8 decisions:

| Regime | n | threshold | `tp_ratio` | `rr >= thr` | `rr < thr` | exactly `== thr` | **within 1e-9 of thr** |
|---|---|---|---|---|---|---|---|
| MICRO_SCALP | 972 | 1.5 | 1.5 | 709 | **263** | 457 | **972 (100 %)** |
| REGIME_SCALP | 217 | 2.0 | 2.0 | 217 | 0 | 216 | **217 (100 %)** |
| INTRADAY_SWING | 54 | 2.5 | 3.0 | 54 | 0 | 0 | 0 |
| DEAD_CALM | 22 | 2.0 | 1.5 | 0 | **22** | 0 | 0 |

**Findings:**

- **1,189 of 1,265 candidates (94 %) sit within `1e-9` of their threshold.**
- **263 MICRO_SCALP candidates — 27.1 % of that regime — fall below on rounding
  alone.** Every one would be admitted by the exact arithmetic.
- **REGIME_SCALP passed 217 of 217, but with zero margin.** 216 landed exactly
  on `2.0`; one landed `2.3e-14` above. None happened to round down. This is not
  robustness; it is the rounding going one way on this dataset.
- DEAD_CALM's 22 failures are **not** a tolerance issue — the gap is `0.5`.

**Caveat, stated because it limits the claim:** these `rr` values are for the
selected candidate at each L8 decision, most of which never reached the gate.
The table describes the **population the gate would face** if more candidates
became `entry_triggered`, which is exactly what Phase 7 would do. It is not a
claim that 263 entries were refused.

---

# H. Decision Status

| # | Finding | Classification |
|---|---|---|
| 1 | The gate is the sole, canonical, last admission step | **KEEP / behaviour established, intent undocumented** |
| 2 | `rr ≡ tp_ratio`; the gate's rr term carries no market information | **KEEP / behaviour established, intent undocumented** |
| 3 | Quality thresholds `5.0 / 6.0 / 7.0` have no recorded rationale | **NEEDS DESIGN DECISION** |
| 4 | RR thresholds `1.5 / 2.0 / 2.5` have no recorded rationale | **NEEDS DESIGN DECISION** |
| 5 | MICRO_SCALP and REGIME_SCALP thresholds equal their own `tp_ratio`, so admission is decided by rounding | **IMPLEMENTATION DEFECT** *(and a design decision to fix properly)* |
| 6 | `reward_distance` round-trip destroys the identity that `(R·k)/R` preserves exactly | **IMPLEMENTATION DEFECT** |
| 7 | DEAD_CALM falls through to a threshold its `tp_ratio` can never meet | **NEEDS DESIGN DECISION** |
| 8 | "Will be blocked at L2 anyway" is contradicted — 22 DEAD_CALM decisions reached L8 | **DATA/MEASUREMENT ISSUE** *(stale documentation)* |
| 9 | The rejection message misattributes to quality and prints the failing value as the threshold | **IMPLEMENTATION DEFECT** |
| 10 | The gate's only dedicated tests use `rr` values that cannot occur | **IMPLEMENTATION DEFECT** *(test validity)* |
| 11 | Phase 6I cited an `rr` from the wrong geometry | **DATA/MEASUREMENT ISSUE** — corrected in this commit |

**Nothing in this table was acted on.** Items 5, 6 and 9 are defects in the
sense that the code does not do what its shape implies; **fixing any of them
changes admission**, so each needs a decision as well as a repair.

---

# Unresolved Decisions

| # | Question | Blocks |
|---|---|---|
| U1 | What is `trigger_quality` measuring, and what should each threshold be? | Any claim that quality gating is meaningful |
| U2 | Should the gate test `rr` at all, given `rr ≡ tp_ratio`? It is the same tautology Phase 6C retired, in a different function | Phase 7 interpretation |
| U3 | If it keeps testing `rr`, should thresholds be strictly inside the ratio (so rounding cannot decide), or should the comparison carry a tolerance? | 263 candidates |
| U4 | Should `reward_distance` be `risk_distance × tp_ratio` rather than a round-trip? | Changes 263 admissions |
| U5 | Should DEAD_CALM have a branch, a different `tp_ratio`, or no entry? | 22 candidates; **DD5** |
| U6 | Should the rejection message name the term that actually failed? | Diagnostic trust |
| U7 | Should `tests/test_entry_quality_gate.py` use inputs that can occur? | Test validity |
| U8 | `U10` — regime ATR bands in dollars vs pips — decides which regime, hence which thresholds apply | All of the above |

---

# What Must Be Decided Before Phase 7

**Ordered by how badly it corrupts a performance result.**

1. **U2 + U3 + U4 together — the rr term.** With thresholds sitting exactly on
   `tp_ratio`, **27 % of MICRO_SCALP admissions are decided by floating-point
   error**. Any Phase 7 result would be measuring rounding, not strategy. These
   three are one decision: keep the term and make it robust, or remove it as
   Phase 6C removed its twin.

2. **U5 — DEAD_CALM.** 14.7 % of all decisions occur in a regime that cannot
   produce an entry. Whether that is intended changes what a "no trade" result
   means.

3. **U1 — quality thresholds.** `trigger_quality` is now the *only* term in the
   gate that varies with market state. If its thresholds are arbitrary, the gate
   is arbitrary.

4. **U6, U7 — diagnostics and test validity.** Neither changes behaviour, and
   both currently mislead: the log misattributes rejections, and the tests
   cannot fail for the right reason.

5. **U8 — `U10` regime bands.** Upstream of everything here.

**None of these is resolved by this audit, and none should be resolved by
implementation before review.**

---

# No Profitability Conclusion

**No profitability conclusion can be drawn from the 3 newly admitted signals.**

They are three signals over three months, in one regime, on one dataset, under
an assumed spread, with zero slippage and zero commission. **They have not been
executed, held or closed in any measurement.** Nothing in Phase 6I or 6J says
whether they would win, lose, or be reached at all.

Further, the admission boundary that produced *three* rather than *four* is
decided by an arithmetic artefact (§E). A number that can change because of
`1.7e-13` is not a basis for any claim about performance.

---

# Scope

**Changed by this commit:** this document; a corrected `rr` figure and an added
minimal-reproduction test in `tests/backtest/test_valid_rr_retired.py`; the same
figure corrected in `docs/VALID_RR_CONTRACT.md`.

**Not changed:** `evaluate_entry_for_regime` and every threshold in it,
`calculate_entry_levels`, `tp_ratio` values, regime/style rules, candidate
generation, sizing, execution, trade management, the broker surface, both
baselines, and the R1 fixtures.
