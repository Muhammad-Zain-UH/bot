# Phase 6K-C — U2: RR Admission Policy

**Evidence audit. No production source, threshold, gate, DEAD_CALM,
`trigger_quality`, baseline or R1 fixture changed.** U4 is not implemented. No
backtest performance, trade count, signal count or profitability figure was used
to choose policy, and none is available.

**Input:** Phase 6K-B `19c68c2`.

**The narrow question:** should a regime-admissibility rule require a minimum
configured RR, and where should that rule live?

## Evidence classes

**DOCUMENTED** — explicit stated intent.
**STRONG HISTORICAL** — explicit historical design or naming evidence.
**IMPLEMENTATION** — observed code behaviour only.
**INFERENCE** — interpretation; not evidence.

---

# 1. The Finding That Settles Most of This

**The original module docstring specified a minimum-RR entry gate in so many
words.** Recovered from `c3cf4df:entry_engine.py:21-36` — a 37-line design
docstring that **does not survive at HEAD**, where it was replaced by a single
line:

```
TAKE PROFIT (1:3 RR for A+):
TP = Entry + (Entry - SL) × 3.0

MINIMUM RR CHECK (Hard Gate):
- If calculated TP doesn't give minimum 1:3 RR → NO TRADE
- Recalculate or wait for better level
```

**DOCUMENTED, and unambiguous on the admission question:** a check labelled
**"Hard Gate"** whose failure outcome is **"NO TRADE"**. This is not target
geometry. It is entry admission, stated as such.

**And it contains its own contradiction.** Two lines above, `TP` is defined as
`Entry + (Entry − SL) × 3.0`. If that is how `TP` is built, then the "calculated
TP" **always** gives exactly 1:3, and the hard gate can never fire.
**"Recalculate or wait for better level"** presupposes a reward that might fall
short — which the construction stated immediately above makes impossible.

**INFERENCE, and it is the crux of U2:** the author intended an entry-admission
minimum-RR rule and simultaneously specified a target construction that makes
the rule vacuous. The intent is real and documented; the *mechanism* never
existed.

---

# 2. Evidence Table

Separating **"RR is the target multiple"** (resolved in 6K-B) from **"RR should
reject an entry"** (the question here).

| # | Source / date / commit | Exact statement | A | B | Class |
|---|---|---|---|---|---|
| 1 | `entry_engine.py:34-36`, `c3cf4df`, 2026-07-01 | *"MINIMUM RR CHECK (Hard Gate): If calculated TP doesn't give minimum 1:3 RR → NO TRADE"* | ✅ **strong** | ❌ | **DOCUMENTED** |
| 2 | `entry_engine.py:36`, `c3cf4df` | *"Recalculate or wait for better level"* | ~ | ~ | **DOCUMENTED** — presupposes a varying reward; see §1 |
| 3 | `entry_engine.py:733`, `c3cf4df` | `"entry_triggered": bool(raw_triggered and entry_levels["valid_rr"])` | ✅ | ❌ | **IMPLEMENTATION** — RR genuinely gated entry |
| 4 | `entry_engine.py:826`, `c3cf4df` | Same conjunction on the momentum path | ✅ | ❌ | **IMPLEMENTATION** |
| 5 | `entry_engine.py:747`, `c3cf4df` | `"PULLBACK FOUND BUT RR TOO LOW - WAIT"` | ✅ **strong** | ❌ | **DOCUMENTED** — explicit admission language: setup found, RR insufficient, wait |
| 6 | `entry_engine.py:967`, `c3cf4df` | Docstring: `"valid_rr": bool,  # True if RR ≥ 1:2` | ✅ | — | **DOCUMENTED** |
| 7 | `entry_engine.py:1001`, `c3cf4df` | `valid_rr = rr >= 2.0  # Minimum 1:2` | ✅ | — | **DOCUMENTED** |
| 8 | `entry_engine.py:31-32`, `c3cf4df` | *"TAKE PROFIT (1:3 RR for A+): TP = Entry + (Entry − SL) × 3.0"* | ✅ geometry | — | **DOCUMENTED** — target geometry, **not** admission |
| 9 | **Docstring says 1:3; code says `>= 2.0`** | `c3cf4df` | The design document and the implementation **disagree on the minimum** | ~ | ~ | **DOCUMENTED conflict** |
| 10 | `architecture.txt:830`, `SYSTEM_STRUCTURE_DIAGRAM.md:365` | *"evaluate_entry_for_regime(): Validates RR ratio"* | ✅ weak | — | DOCUMENTED (weak) — names the activity, no threshold |
| 11 | `evaluate_entry_for_regime`, `4c90b81` → HEAD | **Zero comments in every committed version**; no commit message | neutral | neutral | **Absence of evidence** |
| 12 | Regime thresholds `1.5 / 2.0 / 2.5` | `4c90b81` → HEAD | **No rationale recovered anywhere** | neutral | neutral | **Absence of evidence** |
| 13 | `1:1 / 1:2 / 1:3` ladder, `exit_1_3 = take_profit` | `trade_manager.py`, `order_execution.py`, both diagrams | Every *other* RR usage is **exit management** | — | ✅ weak | **DOCUMENTED** |
| 14 | `rr ≡ tp_ratio` | `c3cf4df` → HEAD, unchanged construction | The gated quantity **is configuration**, not measurement | ✅ | — | **DERIVED** (6K-B) |
| 15 | 37-line design docstring deleted; `rr_ratio` renamed; every intent comment stripped | uncommitted WIP, `c3cf4df` → `4c90b81` | The rationale was removed in one undocumented window | neutral | neutral | **STRONG HISTORICAL** |
| 16 | `config.py:181` `validate_config()` raises — **and is never called** | HEAD | A configuration-invariant mechanism exists and is dead | ~ | — | **IMPLEMENTATION** |
| 17 | `tp_ratio` is **not in `config.py`**; hardcoded in `detect_regime` | HEAD | The values A would validate do not live in configuration | ~ | — | **IMPLEMENTATION** |

## 2.1 The distinction the brief asked for, applied

| Evidence type | Items |
|---|---|
| RR **is** the target multiple *(already resolved, not evidence for U2)* | 7, 8, 14 |
| RR **should reject an entry** *(the U2 question)* | **1, 3, 4, 5, 6** — and item 1 is explicit |
| RR is **only** exit geometry | 13 — and it is weak, because it shows other *usages* are exits, not that admission was excluded |
| The **later regime gate** was designed | **None.** 11, 12 record its absence |

---

# 3. Configuration-Invariant Precedent in This Project

Asked for as an analogy, and **not claimed as proof of intent.**

**The pattern exists and is used, in the canonical code:**

| Mechanism | Where | Validated |
|---|---|---|
| `SymbolSpecification.__post_init__` | `core/symbols.py:194` | Once, at construction; raises `InvalidSymbolSpecificationError` |
| `UnsupportedCalculationModeError` guard | `core/symbols.py` | At construction and at use |
| `assert_live_trading_disabled()` | `core/safety.py:220` | At startup; raises |
| `validate_execution_environment()` | `core/safety.py:153` | At startup; raises |
| `assert_logs_are_redirected()` | `backtest/baseline.py:688` | Before a run; raises |
| `lots_for_risk` input validation | `core/sizing.py:106` | Per call; raises `SizingInputError` |

**INFERENCE:** the project has an established idiom — *a constraint over
configuration is checked once, at the boundary, and raises rather than degrading
into a silent runtime rejection.* Phase 6F applied it to sizing, Phase 6E to
calculation modes.

**Two facts that qualify the analogy, and must not be glossed:**

- **`config.py:validate_config()` exists, raises, and is never called
  anywhere.** The legacy configuration module's own invariant mechanism is
  dead. **OBSERVED.**
- **`tp_ratio` is not in `config.py`.** It is hardcoded inside
  `entry_engine.detect_regime`'s `if`/`elif` chain. A configuration invariant
  over it would have nowhere established to live without first moving the
  values, which is a separate change.

---

# 4. The Six Explicit Questions

**1. Is there historical evidence that a minimum RR was intended as an ENTRY
ADMISSION requirement?**

**Yes, and it is the strongest evidence in this audit.** Item 1 — *"MINIMUM RR
CHECK (Hard Gate) … → NO TRADE"* — is a design-document statement that a minimum
RR rejects an entry. Corroborated by items 3–6: it was conjoined into
`entry_triggered` on both paths, and the user-facing string read *"RR TOO LOW -
WAIT"*.

**2. Is there historical evidence that RR was intended only as TARGET/EXIT
geometry?**

**No — and this is a change from what the earlier phases could see.** Item 13
shows every *other* RR usage is exit management, but that is evidence about
other usages, not evidence that admission was excluded. Item 1 directly
contradicts an "only geometry" reading. **Phase 6C's framing — that a minimum-RR
requirement is a configuration property rather than a per-decision gate — was
sound reasoning, but it was reached without this evidence, which shows the
author did intend an admission rule.**

**3. Is there evidence supporting a configuration-level invariant?**

**Indirect, and honestly labelled.** No document proposes one. What supports it
is the combination of item 1 (an admission rule was intended) with item 14
(`rr ≡ tp_ratio`, so the gated quantity is configuration). **INFERENCE:** if the
requirement is real and the quantity is configuration, the requirement is a
configuration constraint. The project's own idiom (§3) is how such constraints
are expressed here. **This is derivation, not documented intent.**

**4. Is there evidence supporting no admission gate?**

**Weak, and it is item 2.** *"Recalculate or wait for better level"* presupposes
a reward that can fall short — which the fixed construction forbids. **INFERENCE:**
one reading is that the author's true intent was a *measured* reward, making the
whole check inapplicable to the code as written. 6K-B found no implementation of
that anywhere in 80 commits, so it remains a reading of one clause, not evidence
of design. **It is the strongest thing that can be said for B, and it is not
strong.**

**5. Is the evidence sufficient to choose A or B?**

**Sufficient to reject B as "no rule was ever intended". Not sufficient to fix
the rule's value.**

- **B is contradicted** by item 1. A minimum-RR entry rule was explicitly
  designed as a hard gate.
- **A is the only form the intent can take** under the resolved `rr ≡ tp_ratio`:
  a constraint on a configured constant is a configuration invariant.
- **But the value is genuinely undetermined.** The repository gives **three
  different answers and reconciles none of them**:

| Source | Minimum |
|---|---|
| Design docstring (item 1) | **1:3** |
| Original code (item 7) | **1:2** (`>= 2.0`) |
| Surviving regime gate (item 12) | **1.5 / 2.0 / 2.5**, no rationale |

**6. If insufficient, what remains a design decision?**

> **What the minimum RR is, and whether it is global or per-regime.**
>
> The design document says 1:3, the code that implemented it said 1:2, and the
> gate that replaced it says three different values with no recorded reason.
> Nothing reconciles them. Choosing among them — or choosing none — is a
> strategy decision that no repository evidence can make.

Downstream of that, and equally undecided:

- **Whether MICRO_SCALP and DEAD_CALM's `tp_ratio = 1.5` should change, or the
  minimum should.** 6K-B established DEAD_CALM's `1.5` was a cosmetic fallback
  (*"Realistic if it somehow escaped L2"*), so it carries **no weight** as a
  designed value. MICRO_SCALP's `1.5` has no comment either way.
- **Whether `tp_ratio` should move into configuration** so an invariant has
  somewhere to live (§3).

---

# 5. A-vs-B Assessment

| | Option A — configuration invariant | Option B — no RR admission rule |
|---|---|---|
| **Historical support** | The intent it would preserve is **documented** (item 1); the *form* is derived, not documented | **Contradicted** by item 1 |
| **Consistency with `rr ≡ tp_ratio`** | Full — checks configuration where configuration lives | Full — but discards a documented requirement |
| **Consistency with project idiom** | Matches `core/symbols`, `core/safety`, `core/sizing` (§3) | Matches Phase 6C's retirement of `valid_rr` |
| **What it needs before implementation** | **A value**, which does not exist (§4.6), and a home for `tp_ratio` | **A ruling** that the documented hard gate is abandoned, which is a strategy decision |
| **What it would change today** | Nothing at runtime; it would reject configurations, not candidates | Removes the gate's `rr` term; **DEAD_CALM becomes admissible**, deciding U5 implicitly |

**INFERENCE:** A and B are not symmetric. **A preserves a documented intent and
is blocked only on a number. B discards a documented intent and is blocked on a
ruling.** That asymmetry is a reason to prefer A *as the shape of the answer* —
but it does not supply the number, and **the number is the decision.**

**Explicitly not used to reach this:** trade count, signal count, profitability,
or the fact that either option would change the zero-signal result. On the
frozen dataset neither option's effect was consulted.

---

# 6. Recommended Contract Wording — Established Parts Only

Only what evidence supports. **Not implemented.**

> **RR is the configured reward multiple.** `rr` is `tp_ratio`: the multiple of
> risk from which `take_profit` is constructed. It is not a measurement of
> market opportunity and never has been. *(Established — 6K-B.)*
>
> **A minimum-RR requirement was designed as an entry-admission rule.** The
> original design specified a hard gate whose failure outcome was "NO TRADE".
> *(Established — item 1.)*
>
> **Because the quantity is configuration, the requirement is a configuration
> constraint.** A minimum over `tp_ratio` is a property of an admissible regime,
> validated once where the regime is defined, not rediscovered per candidate
> from `calculate_entry_levels`. *(Derived from the two statements above.)*
>
> **The value of the minimum is UNRESOLVED**, and no value is asserted here. The
> repository contains three unreconciled answers — 1:3, 1:2, and a regime-keyed
> 1.5/2.0/2.5 with no rationale — and choosing among them is a strategy
> decision.

**No wording is offered for:** the minimum's value, whether it is global or
per-regime, DEAD_CALM's or MICRO_SCALP's `tp_ratio`, the quality thresholds, or
whether the runtime comparison is removed before or after a value is chosen.

---

# 7. STOP Conditions for Implementation

Binding on any later phase that acts on this.

1. **STOP if a minimum value is chosen without a recorded rationale.** The
   repository already contains three unreconciled values; a fourth chosen
   silently is the defect this project has repeatedly had to unwind.
2. **STOP if the runtime comparison is removed in the same commit as a
   configuration invariant is added.** Those are two behaviours — one changes
   admission, one changes startup — and bundling them makes attribution
   impossible, exactly as 5B-i/5B-ii had to be split.
3. **STOP if DEAD_CALM's admissibility changes as a side effect.** Option B
   decides U5 implicitly; any such change must be a stated decision, not a
   consequence.
4. **STOP if `tp_ratio` values are altered.** Changing a regime's ratio to
   satisfy a minimum is a strategy change requiring its own authorisation.
5. **STOP if the R1 fixture fingerprints move.** Both run at `tp_ratio 3.0`
   against any candidate minimum; movement means something unintended changed.
6. **STOP if `baseline_004` or `baseline_005` is modified or re-pinned.**
7. **STOP if the U4 arithmetic repair is bundled with a U2 decision.** 6K-A
   established the repair is a *precondition* for deciding U2, not part of it.
8. **STOP if an option is justified by trade count, signal count or
   profitability.** None exists: zero trades have ever been executed, held or
   closed.

---

# 8. Confirmation

| | |
|---|---|
| Source changes | **None.** No `.py` file modified |
| Threshold changes | **None** |
| DEAD_CALM, `trigger_quality`, the RR gate | **Unmodified** |
| U4 arithmetic repair | **Not implemented** |
| `baseline_004` / `baseline_005` | **Untouched**, not regenerated, not re-pinned |
| R1 fixtures / fingerprints | **Unchanged** |
| Working tree | Clean; this commit adds one document |

**New evidence recorded by this phase:** the `MINIMUM RR CHECK (Hard Gate)`
design docstring (item 1), the `"RR TOO LOW - WAIT"` admission string (item 5),
the `valid_rr` docstring annotation (item 6), the documented 1:3-vs-1:2 conflict
(item 9), and the dead `validate_config()` mechanism (item 16). **None was
visible at HEAD; all were recovered from `c3cf4df`.**

**No profitability conclusion is drawn or available.**
