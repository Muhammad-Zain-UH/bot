# Phase 6K-E — New RR Strategy-Contract Decision

**Design decision. No production source, threshold, gate, DEAD_CALM, baseline
or R1 fixture changed.** U4 not implemented. No backtest performance or trade
count was used to select a structure or a value.

**Input:** Phase 6K-D `48c7c5c`. Archaeology is closed; nothing here re-opens it.

**This phase makes a NEW design decision. It does not pretend archaeology
recovered one.**

---

# 1. The Finding That Governs Everything Below

**Under `rr ≡ tp_ratio`, choosing a minimum RR is not an RR policy. It is a
regime-admissibility policy wearing an RR costume.**

**DERIVED** — which regimes each candidate minimum permits:

| Minimum | MICRO_SCALP (1.5) | REGIME_SCALP (2.0) | INTRADAY_SWING (3.0) | DEAD_CALM (1.5) | Permitted |
|---|---|---|---|---|---|
| ≤ 1.5 | PERMIT | PERMIT | PERMIT | PERMIT | **4 / 4** |
| **2.0** | **BAR** | PERMIT | PERMIT | **BAR** | **2 / 4** |
| **2.5** | **BAR** | **BAR** | PERMIT | **BAR** | **1 / 4** |
| **3.0** | **BAR** | **BAR** | PERMIT | **BAR** | **1 / 4** |
| *current per-regime* | PERMIT | PERMIT | PERMIT | **BAR** | **3 / 4** |

Every candidate number is a different answer to *"which regimes may trade?"* —
a question nobody has asked, and one the RR evidence says nothing about.

**This is contract semantics, not a performance statement.** It describes what
each contract permits, not whether permitting it is desirable.

## 1.1 The irreducible gap

**The documented intent was per-opportunity admission** — *"Recalculate or wait
for better level"*. **The available quantity is a per-regime constant.**

**No option closes that gap**, because the intent presupposed a quantity the TP
construction does not produce. Options differ only in how they handle the gap:

| Approach | Handles the gap by |
|---|---|
| Keep the runtime check (C, D, E, and A/B as written) | Preserving the per-opportunity **form** over a per-regime **quantity** |
| Relocate to configuration validation | Preserving the **substance** ("a minimum must hold") and **discarding the form** |
| Remove the gate | Abandoning both — **a strategy-policy change**, per the brief |

**The brief's caution is correct and I am adopting it:** converting to
configuration validation would **permanently foreclose** the per-opportunity
intent. If TP construction were ever changed to a market-derived target, a
runtime gate would immediately begin discriminating per opportunity as
originally intended, with no relocation needed. A configuration check would not.
**That is an architectural reason to keep the gate in place, independent of any
number.** It corrects my Phase 6C lean, which reached the opposite conclusion
without the hard-gate evidence.

---

# 2. Policy Comparison Table

| Criterion | **A** single minimum | **B** regime-specific | **C** retain current, provisional | **D** global 2.0 | **E** global 3.0 |
|---|---|---|---|---|---|
| Consistent with documented hard-gate intent | **Yes** — intent's shape was global | Partly — intent was global, not per-regime | Partly | **Yes** | **Yes** |
| Consistent with the meaning of `rr` | Yes | Yes | Yes | Yes | Yes |
| Preserves per-opportunity admission **form** | **Yes** | Yes | Yes | Yes | Yes |
| Delivers per-opportunity **discrimination** | **No** — per-regime constant | No | No | No | No |
| Redundant mathematics under current TP construction | **Yes** — a constant vs a constant | Yes | Yes | Yes | Yes |
| New strategy-policy assumption required | **One** value | **Four** values | **Four** values + "current is acceptable" | One value, inherited | One value, inherited |
| Assumption statable and testable | **Yes** — one sentence | Yes, ×4 | Yes, but four unexplained numbers | Yes | Yes |
| **Regimes permitted** | depends on value | depends on 4 values | **3 / 4** | **2 / 4** | **1 / 4** |
| Impact on DEAD_CALM | depends | explicit by construction | **barred**, incidentally | **barred** | **barred** |
| Accidental-optimization exposure | **High** — §3 | **Highest** — four dials | **High** — current values are known to admit the 3 signals | High | High |
| Implementation complexity | **Lowest** — one named constant | Four constants + regime mapping | Zero code change, doc only | Low | Low |
| Freezable before Phase 7 | **Yes** | Yes | **Yes, immediately** | Yes | Yes |

---

# 3. The Accidental-Optimization Hazard — Stated Plainly

**This is the most serious risk in this decision, and it is unavoidable now.**

**MEASURED, and already known to everyone reading this:** all three currently
admitted signals are MICRO_SCALP, whose `tp_ratio` is 1.5. Therefore:

- any minimum **≤ 1.5** keeps all three;
- any minimum **≥ 2.0** destroys all three.

**Whoever selects the number now does so knowing exactly what each choice does
to the only signals this repository has ever produced.** The selection cannot be
made blind on this dataset, and a value chosen in that state is not
independent evidence of anything — whichever way it goes.

**Option C is the sharpest case.** "Retain current values provisionally" is
retaining precisely the configuration that admits the three known signals. Even
with an honest label, the selection is the one that preserves the known outcome.

**INFERENCE:** this hazard is not a reason to prefer any particular value. It is
a reason to **separate the structural decision from the numerical one**, and to
require that the number be justified by something other than this dataset.

---

# 4. Historical Facts vs New Design Decisions

| Statement | Status |
|---|---|
| `rr` is the configured reward/risk multiple used to construct TP | **HISTORICAL FACT** (6K-B) |
| A minimum-RR **entry-admission** rule was intended | **HISTORICAL FACT** (6K-C) |
| The intent's wording was **per-opportunity** | **HISTORICAL FACT** (6K-C) |
| The historical implementation made the test vacuous | **HISTORICAL FACT** (6K-C) |
| A minimum of **1:3** was documented | **HISTORICAL FACT** — never implemented |
| A minimum of **2.0 / "1:2"** was implemented | **HISTORICAL FACT** — contradicts the docstring |
| The intent was **global**, not per-regime | **HISTORICAL FACT** — both historical values are global; per-regime has zero provenance |
| **1.5 / 2.0 / 2.5 are per-regime** | **HISTORICAL FACT that they exist** — **NO** fact about why |
| **Which number to adopt now** | **NEW DESIGN DECISION** |
| **Whether the minimum is global or per-regime** | **NEW DESIGN DECISION** |
| **Whether the gate stays runtime or moves to configuration** | **NEW DESIGN DECISION** |
| **Whether DEAD_CALM may trade** | **NEW DESIGN DECISION** — never decided, only inherited |

**Everything in the lower block is new.** No option may be presented as
restoring intent.

---

# 5. Recommended Contract Architecture

**Structure only. No number is recommended — see §6.**

> ### Recommended: **Option A structure** — a single, named, strategy-wide minimum, evaluated where the gate already is.
>
> 1. **Keep the admission check in `evaluate_entry_for_regime`.** Do not remove
>    it (removal is a policy change the evidence does not support) and do not
>    relocate it to configuration validation (that forecloses the documented
>    per-opportunity intent — §1.1).
> 2. **One minimum, not four.** Both historical values were global. Per-regime
>    thresholds have **no provenance at any strength**, and a per-regime
>    structure introduces **four** unjustified parameters where one suffices.
>    This is a parsimony argument, not a historical-precedence one.
> 3. **The threshold is a single named constant**, referenced once, not four
>    bare literals in four branches.
> 4. **The contract states plainly what the check currently does:** under the
>    present TP construction it evaluates identically for every candidate within
>    a regime, so it functions as regime admissibility. Recording that is what
>    keeps the contract honest while preserving the form.

**Why not B/C:** both require four unexplained numbers. C additionally adopts
the exact configuration that preserves the known signals (§3).

**Why not D/E as *structures*:** they are values, not structures. Either fits
inside A. Adopting one *as a decision* is §6's question.

**What this recommendation does not do:** it does not say the gate is useful. It
says removal and relocation are both policy changes that need their own
justification, and that of the structures which keep it, one named constant is
the cleanest.

---

# 6. Can a Number Be Responsibly Selected Now? — **No**

**Three independent reasons, none of which is about trade count.**

**6.1 The number is not an RR decision.** §1 shows it selects which regimes may
trade. Deciding that requires evidence about regimes, not about reward/risk.

**6.2 The evidence needed is circular.** Justifying "MICRO_SCALP may/may not
trade" requires knowing how MICRO_SCALP setups behave — which requires trades —
which requires the gate to be set. **Zero trades have ever been executed, held
or closed.**

**6.3 The selection is contaminated.** §3: every candidate's effect on the only
known signals is already known to the decider.

> **A numerical threshold cannot responsibly be selected without a new research
> protocol, or an explicitly stated risk preference from the strategy owner that
> is acknowledged as a preference rather than a finding.**

**This is not a refusal to decide.** The structural decision is made in §5. The
number is deferred because deferring it is the only way it can later be
justified by anything.

## 6.1 Minimum information required before a number is committed

Any one of these three would suffice; **none exists today.**

| # | Route | What it requires |
|---|---|---|
| **R1** | **Stated risk preference** | The owner states, as a preference: *"a regime whose target is below N× risk is not worth trading"*, with N and the reasoning recorded. **Cheapest, available immediately, and must be labelled a preference, not evidence.** |
| **R2** | **Forward evidence** | Trades exist; per-regime realised R is measured; the minimum is set from observed behaviour. **Blocked** — requires trades, which require the gate to be set. **Circular unless the gate is first set provisionally and explicitly marked as such.** |
| **R3** | **Reframe the quantity** | TP construction changes so `rr` becomes market-derived, at which point the minimum is a genuine per-opportunity test. **A much larger strategy change** (Phase 6K-A Option B), with its own evidence requirements |

**In every route the record must contain:** the value; whether it is global or
per-regime; **why that value and not its neighbours**; which regimes it permits
(the §1 table, recomputed); what evidence would falsify it; and an explicit
statement that it is a new decision, not recovered intent.

---

# 7. DEAD_CALM Under the Chosen Contract

**Not decided here — the brief forbids modifying it — but the contract must say
what happens to it, and the honest answer is that its current status is an
accident.**

**HISTORICAL FACTS:** its `tp_ratio = 1.5` is a documented **fallback** —
*"Realistic if it somehow escaped L2"* — chosen on the belief that L2 would
block the regime. **MEASURED:** 22 DEAD_CALM decisions reached L8; L2 blocked 7
decisions in total. The belief was wrong.

**Its present exclusion is therefore the product of a fallback value meeting an
unexplained threshold, inside a gate the author expected it never to reach.
Three accidents in series. It is not a decision.**

**What the contract must require:** DEAD_CALM's admissibility becomes an
**explicit** statement, whichever way it falls. Three coherent positions exist,
and this phase selects none:

1. **Explicitly excluded from entry** — then say so in the regime definition,
   and the RR minimum is not the mechanism.
2. **Explicitly admissible** — then its `tp_ratio` needs to be a designed value
   rather than a fallback, which is a separate decision.
3. **Explicitly unresolved** — then it is a **STOP condition for Phase 7**,
   because 14.7 % of all decisions occur in a regime whose status is unknown.

**Under the §5 architecture with any global minimum > 1.5, DEAD_CALM is barred —
and so is MICRO_SCALP.** That coupling must be stated whenever a number is
proposed: **no global minimum can bar DEAD_CALM without also barring
MICRO_SCALP**, because they share `tp_ratio = 1.5`. A contract that wants to
separate them **cannot be global**, which is the one genuine argument for a
per-regime structure and is recorded here for completeness.

---

# 8. U2 / U3 / U4 — Defined Separately So They Cannot Be Bundled

| | Question | Status | May be implemented |
|---|---|---|---|
| **U3** | What does `rr` measure? | **RESOLVED** — the configured reward/risk multiple used to construct TP. Not a market measurement | n/a — a fact, not a change |
| **U4** | Should `reward_distance` be `risk_distance × tp_ratio` rather than reconstructed from `take_profit`? | **RESOLVED conceptually** (6K-A). A numerical-correctness repair; introduces no policy | **Yes — first, alone, with its own before/after audit.** Blocked on nothing |
| **U2** | Should the gate exist, and where? | **DECIDED HERE (structure):** keep the runtime check; single named minimum; do not remove; do not relocate to configuration | **Only after U4.** Implementing it before U4 means writing policy over a comparison decided by rounding |
| **U9** *(new)* | **What is the number?** | **DEFERRED** — §6. Requires R1, R2 or R3 | **Not until §6.1's record exists** |
| **U5** | May DEAD_CALM trade? | **UNRESOLVED** — §7. Coupled to U9 for any global minimum | **Must be explicit, never a side effect** |

## 8.1 Implementation order, and why

```
1. U4   numerical repair, alone            -> the comparison becomes deterministic
2. U9   the number, via R1/R2/R3           -> requires a recorded rationale
3. U2   structural change to a named const -> only meaningful once 1 and 2 exist
4. U5   DEAD_CALM, explicitly              -> never as a consequence of 2
```

**U4 first is not a preference.** Until it lands, the gate's outcome for
MICRO_SCALP is decided by floating-point error in 263 of 972 measured cases. A
policy written over that is a policy over rounding.

## 8.2 STOP conditions

Carried forward from 6K-C, plus two new ones:

1. **STOP if a number is committed without §6.1's record.**
2. **STOP if U4 and U2 land in the same commit.**
3. **STOP if DEAD_CALM's admissibility changes as a side effect of a number.**
4. **STOP if `tp_ratio` values are altered to satisfy a minimum** — that inverts
   the dependency and is a strategy change.
5. **STOP if the R1 fixture fingerprints move.**
6. **STOP if `baseline_004` or `baseline_005` is modified or re-pinned.**
7. **NEW — STOP if a value is justified by its effect on the three known
   signals**, in either direction. §3.
8. **NEW — STOP if any option is described as "restoring" the historical
   intent.** Every number available is a new decision (§4).

---

# 9. Confirmation

| | |
|---|---|
| Source changes | **None.** No `.py` file modified |
| Threshold changes | **None** |
| Baseline / R1 changes | **None** |
| U4 implementation | **Not done** |
| DEAD_CALM behaviour | **Unchanged** |
| Backtest optimization | **None run** |
| Working tree | Clean; this commit adds one document |

**What this phase decided:** the contract **structure** — keep the runtime
admission check, one named global minimum, no relocation to configuration, no
removal.

**What it deliberately did not decide:** the number, and DEAD_CALM.

**No profitability conclusion is drawn or available.** Zero trades have ever
been executed, held or closed; the three admitted signals have never been
carried to an outcome.
