# Phase 6C — Strategy Contract Decision / Pre-Phase-7 Gate

**Decision and design pass. Nothing is implemented.** No production code, test,
strategy parameter, specification, fixture or baseline is changed by this
document. `baselines/baseline_004` remains **FROZEN**.

**Inputs:** Phase 6 audit `ee88f84`, Phase 6A `71269f2`, Phase 6B `0c737a2`.

## Labels

**OBSERVED** source · **MEASURED** run/artefact · **DOCUMENTED** stated as intent
in a repository document · **DECIDED** a ruling made here · **INFERRED**
reasoning from stated premises · **UNRESOLVED** deliberately not answered.

## Standing of the decisions below

**DECIDED** entries are **proposals for ratification**, not unilateral changes.
Intent is a fact about what a person meant; no amount of code reading
establishes it. Where a decision rests on a judgement only the strategy owner
can confirm, that is stated in the decision itself. Nothing here is implemented,
so ratification costs nothing and refusal costs nothing.

---

# 1. Decision A — Regime/Style Contract

## 1.1 What is being decided

`entry_engine.py:687-694`, **OBSERVED**:

```python
allowed_styles = ["PULLBACK", "MOMENTUM"]
if reg_name == "MICRO_SCALP":       allowed_styles = ["MOMENTUM"]
elif reg_name == "INTRADAY_SWING":  allowed_styles = ["PULLBACK"]
```

Both candidates are always evaluated; the restriction governs only which may be
*selected*.

## 1.2 Evidence, restated

| # | Evidence | Label |
|---|---|---|
| 1 | `SYSTEM_STRUCTURE_DIAGRAM.md:234` — *"(MICRO_SCALP momentum entries don't need pullback)"* | **DOCUMENTED**, indirect: it justifies the **L3 bypass**, not the L8 restriction |
| 2 | No design document mentions INTRADAY_SWING → PULLBACK | **OBSERVED** — searched `*.md`, `docs/*.md` |
| 3 | The documented regime config has no style field | **OBSERVED** |
| 4 | No test pins `allowed_styles` | **MEASURED** |
| 5 | Originates in commit `c3cf4df` ("update"), no recorded reason | **OBSERVED** |
| 6 | Prior audit #44: AMBIGUOUS, *"Unresolved: why…"* | **DOCUMENTED** |
| 7 | Prior audit #12: L3 computes a setup style read **only by display functions**; L8 decides again from the regime name and ignores it | **DOCUMENTED** contradiction |
| 8 | All 11 affected candidates are MICRO_SCALP; **no INTRADAY_SWING candidate was ever affected** on this dataset | **MEASURED** |
| 9 | All 11 also fail `valid_rr`, so lifting the restriction alone yields **zero** additional signals | **MEASURED** |

## 1.3 Decision

> ### **A — ACCEPT AS-IS**, provisionally, and only for the MICRO_SCALP half.
> The INTRADAY_SWING half is **accepted as frozen behaviour without any claim of
> intent**, and finding #12 is registered as a separate defect.

**DECIDED.** Grounds, in order of weight:

1. **Evidence #1 supports the MICRO_SCALP half.** The one design statement in
   the repository associates MICRO_SCALP with momentum entries. It is indirect,
   but it is the only statement of intent that exists, and it points one way.
2. **Absence of documentation is not evidence of absence of intent.** For the
   INTRADAY_SWING half there is no evidence either way. Changing behaviour on
   the strength of "nobody wrote it down" would substitute my judgement for the
   strategy owner's.
3. **Accepting preserves the measured baseline.** Any change makes the frozen
   decision stream unreproducible; accepting costs nothing observable, because
   of evidence #9.
4. **It is not currently binding.** Evidence #9 means this decision has **no
   effect on signal count today**. It becomes binding only if Decision B
   changes, which is why the two are decided together.

**Explicitly not claimed:** that changing this restriction would create trades
on the current dataset. Evidence #9 shows it would not.

**Ratification required on:** whether INTRADAY_SWING → PULLBACK-only is
intended. I am accepting it as *frozen behaviour*, not asserting it is designed.
If the strategy owner says it was never intended, this decision should be
revisited before any baseline is frozen.

## 1.4 Consequential registration

**DECIDED:** finding #12 — L3 computes a setup style that L8 ignores entirely —
is registered as a distinct open item. It is an internal inconsistency
independent of whether the restriction is intended: two layers decide the same
question by different means and only one is consulted. **Not resolved here.**

---

# 2. Decision B — `valid_rr` Contract

## 2.1 What is being decided

`entry_engine.py:403-409`, **OBSERVED**:

```
take_profit = entry ± (risk_distance × tp_ratio)
rr          = reward_distance / risk_distance      # ≡ tp_ratio
valid_rr    = rr >= 2.0                            # ≡ (tp_ratio >= 2.0)
```

## 2.2 The decisive evidence

**E1 — It cannot be an independent gate. This is arithmetic, not intent.**
**MEASURED** to ~1e-13 across all 1,265 L8 decisions and proved against the
production function by six tests. `rr` is a *chosen input*; comparing it to a
constant asks whether the value selected is the value selected.

**E2 — A documented expectation is contradicted by the gate. DOCUMENTED +
MEASURED.** `SYSTEM_STRUCTURE_DIAGRAM.md:234` describes *"MICRO_SCALP momentum
entries"* as a thing that occurs. The current contract makes a MICRO_SCALP entry
**structurally impossible** — `tp_ratio = 1.5` can never satisfy `>= 2.0`. This
is not undocumented intent; it is documented intent **contradicted by**
implementation.

**E3 — The configuration is internally incoherent. OBSERVED.** MICRO_SCALP
carries a fully elaborated configuration: `risk_percent 0.75`, `tp_ratio 1.5`,
`bypass_l3 True`, `bypass_l6 True`, `poi_threshold 50`, `max_spread_pips 5.0`,
plus its own L7 confidence threshold of 55 and its own ATR band. **MEASURED:**
it is the second-largest regime by decision count (5,121 of 15,735, 32.5 %;
REGIME_SCALP is larger at 6,492) but by far the largest **at L8** — 972 of
1,265, **76.8 %** of everything that reaches the entry gate. Elaborating six
parameters, two bypasses and a dedicated confidence threshold for a regime that
can never produce a trade — and which supplies three-quarters of all entry
candidates — is not a coherent design. DEAD_CALM is in the same position at
`tp_ratio 1.5`.

**E4 — No rationale exists for either number.** **OBSERVED**: no document,
comment, docstring or commit message explains the `2.0` threshold or the
`1.5 / 2.0 / 3.0` ratios.

**E5 — The register already frames the remedy.** **DOCUMENTED**: DD5 offers
*"scale milestones with `tp_ratio`, or floor `tp_ratio` above 2.0"* — the second
option dissolves this question by construction.

## 2.3 Decision

> ### **B — REMOVE/CHANGE.** `valid_rr` is not an independent gate and cannot be
> one under the fixed-R construction. The minimum-RR idea is a **constraint on
> regime configuration**, not a per-decision test.

**DECIDED.**

**The reason is E1–E3, not trade count.** Under the deliberately adopted fixed-R
target model (`PHASE_4B_TARGET_SEMANTICS.md` §8, classification C), a
per-decision RR test is a category error. E2 shows the gate contradicts a
documented expectation, and E3 shows the surrounding configuration only makes
sense if MICRO_SCALP was expected to trade.

**Stated as a consequence, not a justification:** removing the gate would admit
the 4 MICRO_SCALP momentum candidates measured in Phase 6B. It would **not**
admit the 11 pullback candidates, which remain blocked by Decision A. That is a
measurement to be verified after implementation, not a reason for this ruling,
and **no claim is made about what those 4 would do.**

## 2.4 The intended semantic contract, in plain language

**Not implemented. Stated for ratification.**

> A minimum reward-to-risk requirement is a statement about how the strategy is
> **configured**, not about an individual decision. Under fixed-R the target is
> `entry ± tp_ratio × R` by construction, so every trade in a regime realises
> that regime's `tp_ratio` as its target multiple, known before any price is
> read. The requirement therefore belongs where `tp_ratio` is chosen.
>
> **Contract:** every regime's `tp_ratio` must satisfy the minimum the strategy
> requires. This is a **configuration invariant**, checked once, not a runtime
> gate evaluated per decision. `entry_triggered` reduces to `raw_triggered`.
>
> A regime whose `tp_ratio` is below the minimum is a **configuration error to
> be corrected**, not a regime to be silently prevented from trading.

**Two consequences requiring separate rulings, neither made here:**

1. **What is the minimum, and does one exist at all?** **UNRESOLVED** — E4. The
   `2.0` has no recorded rationale and must not be carried forward by inertia.
2. **If the minimum is retained, MICRO_SCALP and DEAD_CALM violate it at 1.5.**
   Either their `tp_ratio` changes or the minimum does. This is **exactly DD5**
   and is **UNRESOLVED**. Both options are strategy changes.

## 2.5 Blocking constraint on implementation

**DOCUMENTED.** `PHASE_4B_FIX_DECISION_MATRIX.md` §6: *"`valid_rr` **must not be
changed** until DD1, DD2 and DD5 are settled."*

| | Status |
|---|---|
| DD1 — which manager is canonical | **Settled** — Option D, selected by the strategy owner |
| DD2 — who owns the lifecycle | **UNRESOLVED** |
| DD5 — ladder-ordering remedy | **UNRESOLVED**, and directly coupled (§2.4 consequence 2) |

**Deciding the semantics is not changing the code.** This document decides what
`valid_rr` is *supposed to mean*; the moratorium stands, and implementation
remains blocked on DD2 and DD5.

---

# 3. Intended Strategy Contract

**For a future Phase 7 baseline.** Items that cannot be stated from repository
evidence are marked **UNRESOLVED** and are **not invented**.

| # | Term | Contract | Label |
|---|---|---|---|
| C1 | **Valid raw trigger — pullback** | `rejection_found AND m1_choch_confirmed` | **OBSERVED**, unchanged |
| C2 | **Valid raw trigger — momentum** | `kill_zone AND displacement_found AND fvg_found AND m1_choch_confirmed` | **OBSERVED**, unchanged post-4A |
| C3 | **Regime/style eligibility** | MICRO_SCALP → MOMENTUM; INTRADAY_SWING → PULLBACK; others both | **DECIDED** §1 — accepted as-is, provisionally |
| C4 | **`tp_ratio` source** | `detect_regime`: 1.5 / 2.0 / 3.0 / 1.5 by regime | **OBSERVED**. Rationale **UNRESOLVED** (E4) |
| C5 | **Minimum RR requirement** | A configuration invariant over `tp_ratio`, not a per-decision gate | **DECIDED** §2.4 |
| C6 | **…its value** | **UNRESOLVED** — the `2.0` has no recorded rationale and is not carried forward by default |
| C7 | **Is `valid_rr` independent or derived?** | **Derived.** `rr ≡ tp_ratio` identically | **MEASURED** + **DECIDED** |
| C8 | **Entry price — market** | Next bar open after the decision bar | **OBSERVED** |
| C9 | **Entry price — LIMIT_FVG** | Resting limit at the FVG midpoint; fills on reach, earliest bar N+1 | **OBSERVED** |
| C10 | **Entry price — pullback M1 index** | `m1[-2].close`; momentum's `m1[-1]` override was removed in 4A. The two paths disagree with **no recorded reason** | **UNRESOLVED** (audit #43) |
| C11 | **Stop semantics** | Structural stop from `_select_stop_anchor`, minus a `3.0` buffer; ATR fallback | **OBSERVED**. The buffer is `$3.00`, not 3 pips — **U1, a known P0 unit defect, UNRESOLVED** |
| C12 | **Original R** | `\|actual_fill − original_stop\|`, frozen at creation | **OBSERVED** — canonical spec §4.1 |
| C13 | **Target semantics** | `actual_fill ± tp_ratio × original_R` (§4.2), anchored to the **actual fill** | **OBSERVED** — implemented Phase 5B-ii |
| C14 | **Management** | Canonical domain is sole exit authority; adverse-first; stop moves effective next observation | **OBSERVED** — Phase 5B-i |
| C15 | **Stop ladder** | ORIGINAL → BREAKEVEN at 1R → LOCKED_1R at 2R, forward only | **OBSERVED** |
| C16 | **Partial exits** | `floor(steps_at_entry / 2)` at 1R; zero steps sends no order but still consumes the milestone and promotes the stop | **OBSERVED**. **Never exercised end-to-end** — Phase 6 §4 |
| C17 | **Realised R for laddered trades** | Money-weighted against **original** risk; **does not equal `tp_ratio`** once a partial fires (worked example: 2.0R for a 3R target) | **MEASURED**. Documentation **UNRESOLVED** |
| C18 | **Cost model** | Spread 2.0 pips **ASSUMED**; slippage 0; commission 0 — zeroed so their effects stay attributable | **OBSERVED**. Never validated against a real fill — **UNRESOLVED** |
| C19 | **Sizing** | **UNRESOLVED — CONTRACT AMBIGUITY.** Which broker field is authoritative (DD11) is undecided; the backtest uses a **fixed** 0.01 lots and does not size | **See §6** |
| C20 | **Session rules** | `get_current_session` by UTC hour; `KILL_ZONES_UTC = ((8,10),(12,14))`, zero overlap with the Asian session | **OBSERVED**. The L0 DEAD gate is **dead in the decision path**; `"LondonNewYork"` is **unreachable** — both **UNRESOLVED** |
| C21 | **Pending orders** | LIMIT_FVG rests; direction-aware reach; fill no earlier than N+1; R1 — the fill bar is managed | **OBSERVED** |
| C22 | **What constitutes a trade** | One canonical position → one `TradeRecord` holding every `TradeExecution`; `trades` is a one-row-per-position projection | **OBSERVED** — Phase 3/5B |
| C23 | **Concurrency** | `max_open_positions = 3`, matching production's cap. **Who owns it is I7, UNRESOLVED** | **OBSERVED** |

**Eleven of twenty-three terms carry an unresolved element.** That is the honest
state of the contract, and it is why §5 does not open Phase 7.

---

# 4. Decision D — Baseline Strategy

## 4.1 Decision

> ### **Option 3 — establish both.** A frozen "as-currently-defined" zero-trade
> baseline now, and a separately versioned research baseline only after an
> explicitly approved contract change.

**DECIDED**, on provenance and research validity.

**`baseline_005` — the as-currently-defined baseline.**

| | |
|---|---|
| Path | Current code at the approved commit — **not** `04a341d` |
| Dataset | `data/raw`, hash `433b7e27…`, verified byte-identical |
| Expected | **Zero trades.** That is the correct and expected result |
| Purpose | Freeze the current decision path (Phase 6B prerequisite P1) |
| Relation to `baseline_004` | Additive. `baseline_004` stays frozen and is never regenerated |

**INFERRED, premises in Phase 6A §B.1:** `baseline_004` cannot serve this role
because `core_trigger` changed after it was generated. A separate artefact is
required, not a reinterpretation of the existing one.

## 4.2 Why not Option 1

Option 1 — preserve the contract and find a period where it naturally trades —
is rejected **as a baseline-selection method**, on a research-validity ground
that has nothing to do with trade counts:

> **Selecting a dataset because it produces trades conditions every subsequent
> result on that selection.** Any performance figure measured on a period chosen
> for producing trades is biased by the choice, and the bias cannot be removed
> afterwards. This is dataset selection on the dependent variable.

**Permitted, and separately valuable:** running the current contract over other
periods as a **diagnostic** — to answer "does this contract ever fire, and how
often?" (Phase 6B Q10). That is a measurement about the contract, not a baseline.
Its result must not be used to choose the research period.

## 4.3 Why not Option 2

Option 2 — change the contract first, then baseline — discards the only
opportunity to prove that the contract change is the cause of whatever changes.
Without a frozen current-path baseline there is nothing to attribute against.
The same reasoning split Phase 5B into 5B-i and 5B-ii, and it worked.

## 4.4 Versioning

**DECIDED:** any research baseline after a contract change gets its own
identifier, records the specific contract terms it was generated under, and is
compared against **both** `baseline_005` (same code lineage, pre-change) and
`baseline_004` (the original production record). No baseline is ever overwritten.

---

# 5. Decision E — Phase 7 Entry Gate

> ### **Phase 7 may NOT begin.**

Determinism is not the criterion and is not in question — the path is
deterministic and fully measured. The criterion is whether a trade-level result
would mean anything. It would not.

| # | Prerequisite | Status after 6C | What remains |
|---|---|---|---|
| P1 | Current decision path frozen | **NOT MET** | Generate `baseline_005` (§4.1) |
| P2 | Current trigger behaviour measured | **MET** | — |
| P3 | Regime/style contract decided | **DECIDED, ratification pending** | §1.3 |
| P4 | `valid_rr` contract decided | **DECIDED, ratification pending; implementation blocked** | §2.5 — DD2, DD5 |
| P5 | Sizing semantics sufficient for meaningful risk/P&L | **NOT MET** | **DD11 needs evidence the repository does not contain** (§6) |
| P6 | Baseline generation path established | **MET** | — |
| P7 | Trade-level baseline exists | **NOT MET** | Requires P4 implemented, which requires DD2 + DD5 |
| P8 | Execution semantics frozen | **MET** | Phase 5B-i/ii; C8–C16, C21–C22 |
| P9 | Ledger semantics frozen | **MET** | Phase 3 + 5B-i; C22 |
| P10 | Costs frozen | **PARTIAL** | Frozen *as assumptions* (C18) and recorded as such; never validated |
| P11 | Provenance complete | **MET** | Dataset hash verified on all six timeframes |
| P12 | Chosen dataset exercises the strategy sufficiently | **NOT MET** | Zero trades; depends on P7 |
| P13 | No unresolved correctness issue capable of materially corrupting results | **NOT MET** | DD11 scales every money figure 10×; U1 `$3.00` buffer; `detect_fvg` defect; U10 ATR bands |

**Unmet: P1, P5, P7, P12, P13. Partial: P10. Pending ratification: P3, P4.**

**The critical path is short and specific:**

```
ratify P3 + P4  →  settle DD2 and DD5  →  implement B  →  trades exist (P7, P12)
settle DD11 (needs EXTERNAL broker evidence)  →  P5, P13
generate baseline_005 (can start now, independent)  →  P1
```

**P5 is the hardest**, and not for engineering reasons: DD11 asks which of two
broker-reported fields is authoritative, and the only evidence in the repository
is the self-contradictory export itself. **This requires evidence from outside
the repository** — a broker contract specification, a second export, or a trade
confirmation. No amount of code work resolves it.

**INFERRED:** P13 cannot be met while P5 is open, because a 10× error in
money-per-price-unit corrupts every currency and R figure a performance study
would produce.

---

# 6. Unresolved Decisions

**None is resolved here.**

| # | Question | Blocks | Register | Needs |
|---|---|---|---|---|
| U1 | Is INTRADAY_SWING → PULLBACK-only intended? | P3 ratification | **New** (§1.3) | Strategy owner |
| U2 | Should L8 respect L3's setup-style finding (#12)? | — | **New** (§1.4) | Strategy owner |
| U3 | What is the minimum RR requirement, if any? | P4 → P7 | §2.4(1) | Strategy owner |
| U4 | If retained, does MICRO_SCALP/DEAD_CALM `tp_ratio` change, or the minimum? | P4 → P7 | **DD5** | Strategy owner |
| U5 | Who owns the trade lifecycle? | P4 (gates DD15) | **DD2** | Design |
| U6 | Which broker field is authoritative? | **P5, P13** | **DD11** | **External evidence** |
| U7 | Rationale for `tp_ratio` 1.5 / 2.0 / 3.0 | C4 | Missing-evidence #3 | Strategy owner |
| U8 | Pullback vs momentum M1 bar index (#43) | C10 | — | Design |
| U9 | Is the `$3.00` stop buffer intended as 3 pips? | C11, P13 | **U1 (P0)** | Strategy owner |
| U10 | Does the current contract ever fire on any period? | P12 diagnostic | **New** (§4.2) | Measurement |
| U11 | Realised-R semantics for laddered trades | C17 | Phase 6 §4.4 | Documentation |
| U12 | Who owns concurrency/capacity? | C23 | **I7** | Design |

**U6 is the only one that cannot be settled by a decision or a measurement
inside this repository.**

---

# 7. Non-Goals

Nothing here proposes, performs or argues for:

- **implementing any decision above** — Decision B in particular remains under
  the DD15 moratorium;
- **removing `valid_rr` in code**, lowering any threshold, or changing
  `tp_ratio`;
- **altering the regime/style restriction** — §1.3 accepts it;
- **changing FVG, CHoCH, trigger, session or parameter values**;
- **fixing sizing** — §6 U6 explicitly forbids resolving it by assumption;
- **selecting a dataset because it produces trades** — §4.2;
- **regenerating or reinterpreting `baseline_004`**;
- **amending the canonical trade-management specification** — no contradiction
  with it was found;
- **any profitability claim or performance prediction.** Zero trades exist.
  Nothing here says what the 4 admitted candidates would do, whether the
  strategy is viable, or whether any contract is better than another. Decision B
  is a ruling about **meaning**, and §2.3 states explicitly that trade count is
  not its justification;
- **ranking strategy alternatives.**

---

# 8. Implementation Implications

**Nothing below is authorised by this document.** Recorded so the next phase can
be scoped.

| Step | Change | Blocked on | Fingerprint impact |
|---|---|---|---|
| I1 | **Generate `baseline_005`** — current path, same dataset, expected zero trades | Ratification of this document only | New artefact. `baseline_004` untouched. Its `decisions_fingerprint` must be compared against `baseline_004`'s `e9421f30331e5b3bf1688fc8f74289248059692075b882e328d9ff3eb7825c75`. **Phase 6A measured the L1–L8 funnel as identical (15,735 / 1,265), so the stream may well match** — but the `price_in_fvg` removal sits inside L8, so the result must be **measured and attributed either way**, never assumed |
| I2 | **Register U2 and the style restriction** in the decision register | — | None |
| I3 | **Document C17** (laddered realised R) | — | None |
| I4 | **Add the `tick_value` vs `tick_size × contract_size` cross-check** | — | None on fixtures; **may reject the current broker metadata** — must be measured first |
| I5 | **Settle DD2, DD5, U3, U4** | Strategy owner | None (documentation) |
| I6 | **Implement Decision B** | I5 | **Expected: signals appear.** Must be measured against `baseline_005`, with every change attributed. Its own audit, its own commit |
| I7 | **Settle DD11 (U6)** | **External evidence** | None (documentation) |
| I8 | **Sizing correction** | I7 | Expected none — backtest does not size. Must be proven |

**I1, I2, I3 and I4 are unblocked by anything except ratification of this
document.** I6 is the only step that changes what the strategy does, and it is
deliberately last among the behavioural items.

**Suggested immediate scope, if ratified:** I1 alone. It is the single
prerequisite (P1) that can be met today, it changes no behaviour, and it
produces the artefact every later attribution needs.
