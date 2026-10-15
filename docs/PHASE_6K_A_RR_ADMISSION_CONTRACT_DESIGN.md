# Phase 6K-A — RR Admission Contract: Design Analysis

**Design analysis. No production behaviour changed.** No threshold tuned, no
option chosen for the number of trades it produces, no experiment run to
improve any outcome. `baseline_004` and `baseline_005` untouched, not
regenerated, not re-pinned.

**Input:** Phase 6J `a01ac95`.

## Labels

**DOCUMENTED INTENT** — a repository document states it as a design intention.
**OBSERVED BEHAVIOR** — read from source or measured from a run/artefact.
**DERIVED MATHEMATICS** — algebra from stated definitions.
**INFERENCE** — reasoning from the above; the premises are given each time.

---

# 1. Summary of the Answer

**U4 is answerable from repository evidence. U2 and U3 are not.**

**U4 — `reward_distance` construction.** The code computes
`take_profit = entry ± risk_distance × tp_ratio`, then *reconstructs*
`reward_distance = |take_profit − entry|` from it. **DERIVED:** the product is
already in hand one line earlier, and the round-trip provably destroys
information the direct form preserves exactly. Recommending the direct form
requires no statement of intent — it makes the implementation agree with its own
algebra. §5.

**U2 / U3 — whether the gate should test `rr` at all, and what it measures.**
**The repository contains one sentence of documented intent** — a box label
reading "RR validation" — and **no rationale for any of the three thresholds,
no definition of an independent reward quantity, and no commit message on the
subject.** That is not enough to write a contract. §4, §8.

**A structural point that determines the sequencing.** Repairing the arithmetic
(Option C) converts the `rr` term from *decided by rounding* into *a
deterministic per-regime boolean*:

| Regime | `rr` after repair | `rr >= threshold` |
|---|---|---|
| MICRO_SCALP | exactly 1.5 | 1.5 ≥ 1.5 → **always True** |
| REGIME_SCALP | exactly 2.0 | 2.0 ≥ 2.0 → **always True** |
| INTRADAY_SWING | exactly 3.0 | 3.0 ≥ 2.5 → **always True** |
| DEAD_CALM | exactly 1.5 | 1.5 ≥ 2.0 → **always False** |

**INFERENCE:** the term then *is* the regime-admissibility switch Phase 6C
described — a configuration invariant over `tp_ratio`, expressed as a runtime
comparison. Deciding U2 on that basis is a policy question. Deciding it while
the term is decided by `1.7e-13` is not. **The repair is a precondition for
deciding U2, not an answer to it.**

---

# 2. Repository Evidence Search

Searched: `docs/*.md`, root design documents, all production source, all tests,
and git history.

## 2.1 DOCUMENTED INTENT — everything found

| # | Source | Text | Weight |
|---|---|---|---|
| 1 | `SYSTEM_STRUCTURE_DIAGRAM.md:365` | *"Step 3: evaluate_entry_for_regime() • RR validation • Entry mode (MARKET/LIMIT)"* | **The only statement that this function validates RR.** A box label. Names the activity; states no quantity, threshold, direction or rationale |
| 2 | `SYSTEM_STRUCTURE_DIAGRAM.md:364` | Output: *"entry_triggered (bool) + setup_type + rr_ratio"* | Confirms `rr` is an output of the step. Says nothing about admission |
| 3 | `trade_manager.py:4-10` | *"Partial exits at 1:1, 1:2, 1:3 RR"* | **Exit management**, not admission |
| 4 | `SYSTEM_STRUCTURE_DIAGRAM.md:413-416` | *"Check RR milestones: 1:1 → CLOSE_50PCT, 1:2 → TRAIL_SL, 1:3 → CLOSE_ALL"* | **Exit management** |
| 5 | `FLOW_DIAGRAM_WITH_FLAWS.md:172-173` | *"Trail SL at 1:2 RR"*, *"Close remaining at 1:3 RR"* | **Exit management** |
| 6 | `order_execution.py:118-120` | `exit_1_1 = entry + risk`, … `exit_1_3 = take_profit` | **Exit management** |

**INFERENCE:** every documented RR usage in the repository except #1 and #2 is
about *managing a position after entry*. The R-multiple ladder is a coherent,
documented model — and it is a model of **exits**. Only the box label connects
RR to *admission*, and it carries no content beyond the phrase.

## 2.2 What is NOT documented anywhere

**OBSERVED**, by exhaustive search:

- **No rationale for `1.5`, `2.0` or `2.5`** as admission thresholds.
- **No rationale for `5.0`, `6.0`, `7.0`** quality thresholds.
- **No definition of an independent reward quantity** for admission purposes.
- **No statement that DEAD_CALM should or should not be admissible** through
  this gate.
- **No commit message.** Phase 4B established that all strategy code arrived in
  one bulk commit (`c3cf4df`, "update", 51 files, 43,719 insertions), and that
  no commit message before this project's phases mentions TP, target, reward or
  RR.

## 2.3 Prior classification that bears directly on this

**DOCUMENTED**, `docs/PHASE_4B_TARGET_SEMANTICS.md` §8: the fixed-R target model
is classified **"C — deliberate fixed-R design"**, documented in two design
documents and producing the identity `exit_1_3 == take_profit`. Its Rider 2:

> *"Under fixed-R, `rr` is a **chosen input**. Testing a chosen input against
> `2.0` is not a weak check — it is a **category error**: the gate asks whether
> the value you selected is the value you selected."*

**INFERENCE:** that verdict was written about the retired `valid_rr`. It applies
verbatim to this gate, because the quantity and the construction are identical.

---

# 3. The Mathematical Contract, Restated

**DERIVED MATHEMATICS.** With `R = risk_distance`, `k = tp_ratio`, `E = entry_price`:

```
take_profit     = E ± R·k
reward_distance = |(E ± R·k) − E| = R·k          (R > 0, k > 0)
rr              = R·k / R = k
```

`rr ≡ tp_ratio` for every regime and both directions, in exact arithmetic.
**It contains no information about price, stop, structure, liquidity or
volatility.**

**OBSERVED**, measured over 1,265 L8 decisions: maximum deviation from the
regime constant `~3.6e-13` — float error only, no market content.

**INFERENCE:** any comparison of `rr` to a constant inside this gate is a
comparison of two configuration values. It cannot be a feasibility test, because
nothing feasible enters it.

---

# 4. The Three Options

## OPTION A — Retire `rr` from this gate; `trigger_quality` alone admits

| | |
|---|---|
| **Behavioural meaning** | `entry_allowed = trigger_quality >= T(regime)`. Admission depends only on the trigger's own quality score |
| **Mathematical meaning** | Removes a comparison between two constants. The remaining term is the only one that varies with market state |
| **Information added beyond `tp_ratio`** | **None removed that existed.** The `rr` term added nothing; deleting it loses nothing measurable |
| **Candidates that change — frozen dataset** | **1.** The 2026-08-06 MICRO_SCALP candidate (quality 10.0) is admitted. 3 → 4 signals |
| **Candidates that change — prospectively** | **DEAD_CALM becomes admissible for the first time.** Its 22 L8 decisions are currently barred by `1.5 < 2.0` and would face only `quality >= 5.0`. **OBSERVED:** none of them currently reaches the gate (`entry_triggered` is false for all), so the effect is zero on this data and unknown on any other |
| **Strategy-dependent or implementation artefact?** | **Strategy change.** It alters which regimes can produce entries — a policy outcome, not a numerical one |
| **Baseline integrity** | `baseline_004`/`005` unaffected (frozen, zero trades). A future baseline would differ by the flipped candidate |
| **Future research** | Cleanest: one varying term, no tautology. But DEAD_CALM's admissibility changes silently as a side effect, which is the kind of coupled change this project has repeatedly had to untangle |
| **Evidence required** | A ruling that a chosen R needs no validation at admission, **and** a separate ruling on DEAD_CALM (U5/DD5), because A decides it implicitly |
| **Documentation support** | **Contradicts** the one documented statement (§2.1 #1), which says this function performs RR validation |

## OPTION B — Retain an RR term, defined from an independent reward

| | |
|---|---|
| **Behavioural meaning** | `rr` would be a *measured* reward/risk, e.g. `distance(entry → tp_pool) / distance(entry → stop)`, compared to a threshold |
| **Mathematical meaning** | `rr` stops being `tp_ratio` and becomes a function of liquidity structure. The comparison becomes genuinely informative |
| **Information added beyond `tp_ratio`** | **Real information** — the only option that adds any |
| **Candidates that change — frozen dataset** | **MEASURED** (Phase 4B §6, 1,504 allowed candidates): market-derived RR has **median 0.25**; `≥ 1.0` admits 5.85 %, `≥ 1.5` admits 2.46 %, `≥ 2.0` admits **1.26 %**. At any threshold near the current ones, **essentially every candidate is rejected**, including the 3 currently admitted |
| **By regime** | MICRO_SCALP 0.24 · REGIME_SCALP 0.25 · INTRADAY_SWING **0.18** · DEAD_CALM 0.32. **INTRADAY_SWING has the largest fixed ratio (3.0) and the smallest market-derived one** |
| **Strategy-dependent or implementation artefact?** | **Strategy change, and the largest of the three** |
| **Baseline integrity** | Unaffected. Any future baseline is not comparable to `baseline_005` on admission semantics |
| **Future research** | A gate that measures something. But it introduces a second target concept alongside the deliberate fixed-R one, and Phase 4B found `tp_pool` is validated on **side and score, never on distance** — using its distance would give it a role its own construction does not support |
| **Evidence required** | (a) A definition of the reward quantity; (b) a threshold with a rationale; (c) reconciliation with the deliberate fixed-R target model, since the two would disagree by a median of **1.36 R**; (d) forward evidence that the measured RR predicts anything, **which requires trades that do not exist** |
| **Documentation support** | **None.** No document defines an independent admission reward. `tp_pool` is documented as a feasibility input, not a target |

## OPTION C — Retain the semantics; repair the arithmetic

| | |
|---|---|
| **Behavioural meaning** | `reward_distance = risk_distance × tp_ratio` directly. `rr` becomes exactly `tp_ratio`; the comparison becomes deterministic per regime (§1 table) |
| **Mathematical meaning** | Makes the implementation compute the quantity its own algebra defines. **Removes an artefact; introduces no policy** |
| **Information added beyond `tp_ratio`** | **None** — and this option is honest that there is none. The term becomes a visible per-regime constant rather than a hidden coin-flip |
| **Candidates that change — frozen dataset** | **1**, the same one as Option A: 2026-08-06 goes from `1.4999999999998295` to exactly `1.5`, which satisfies `>= 1.5`. 3 → 4 signals |
| **Candidates that change — prospectively** | **263 MICRO_SCALP L8 candidates** stop being rejected on rounding. **OBSERVED:** none currently reaches the gate, so the frozen-dataset effect is the single candidate above. **DEAD_CALM is unchanged** — still barred at `1.5 < 2.0` |
| **Strategy-dependent or implementation artefact?** | **Removal of an implementation artefact.** The policy — which regimes may enter — is unchanged in every case |
| **Baseline integrity** | Unaffected. A future baseline differs by the one flipped candidate, attributable to a named numerical repair |
| **Future research** | **Makes U2 decidable.** Once the term is deterministic, keeping or removing it is a policy choice about regimes, not a question about rounding |
| **Evidence required** | **None beyond the algebra in §3**, which is already proved and measured |
| **Documentation support** | **Consistent with** §2.1 #1 (the function still performs "RR validation"), and with the deliberate fixed-R model, which constructs `take_profit` from exactly this product |

## 4.1 A and C coincide on the frozen dataset, and differ prospectively

**OBSERVED.** Both admit the 2026-08-06 candidate and nothing else, because
**all 15 raw-triggered candidates on this dataset are MICRO_SCALP** and no
DEAD_CALM candidate ever reaches the gate.

**INFERENCE:** the frozen dataset **cannot distinguish A from C**. Choosing
between them on its evidence is impossible, and choosing on the trade count
would be choosing on a number they share. The distinction is prospective and
is entirely about DEAD_CALM: **A makes it admissible, C does not.**

---

# 5. U4 Considered Separately

**The question:** should `reward_distance` be `risk_distance × tp_ratio` rather
than `|take_profit − entry_price|`?

**DERIVED**, reproduced from the 2026-08-06 candidate:

```
risk_distance * tp_ratio                    = 3.9974999999999454   exact product
|(entry + product) - entry|                 = 3.9974999999994907   4.5e-13 destroyed
product / risk_distance                     = 1.5                  exact
round_tripped / risk_distance               = 1.4999999999998295   below threshold
```

**INFERENCE, and the reason this is separable from U2/U3:** the direct form is
not a new definition. `take_profit` is *already built* from
`risk_distance × tp_ratio` on the preceding line. Reconstructing the same
quantity by adding it to a value ~1,065× larger and subtracting that value back
is a lossy way to recover a number the function already has.

## 5.1 Blast radius — narrower than it looks, because of Phase 5B-ii

**OBSERVED.** Changing `reward_distance` affects:

| | Affected? | Why |
|---|---|---|
| `rr`, hence this gate | **Yes** — the point of the change | |
| `reward_distance` diagnostic | Yes — becomes exact | |
| `take_profit` itself | **No** — computed separately and unchanged | |
| **The canonical exit target** | **No** | Phase 5B-ii: the adapter computes `target = actual_fill ± tp_ratio × original_R` from `strategy_rr_ratio`, and **overwrites** `position.take_profit` with it (`trade_adapter.py:322`). The carried value has no authority over any exit |
| Stop construction | No | |
| Sizing | No | Phase 6F sizing takes `stop_distance`, never `reward_distance` |

**INFERENCE:** before 5B-ii this change would have moved every exit. After it,
the only behavioural consequence is the gate comparison.

---

# 6. Recommended Contract Wording

## 6.1 U4 — recommended, on repository evidence alone

> **Reward distance is the product, not a reconstruction.**
>
> `reward_distance` is defined as `risk_distance × tp_ratio` — the quantity from
> which `take_profit` is constructed — and is not recovered by subtracting
> `entry_price` from `take_profit`. The reconstruction is arithmetically lossy
> in proportion to `entry_price / (risk_distance × tp_ratio)`, and the loss is
> of the same order as the distance between `rr` and two of the four regime
> thresholds.
>
> This states no policy. It makes the implementation compute the quantity its
> own algebra already defines.

**Justification:** §3 proves the identity; §5 proves the loss; §2.3 shows the
repository already treats `take_profit = risk × tp_ratio` as the deliberate
construction. **No statement of intent is required**, which is precisely why
this part is answerable and the rest is not.

## 6.2 U2 and U3 — **UNRESOLVED**

**No contract is recommended, because the evidence does not support one.**

What would be needed, and what exists:

| Needed | Exists |
|---|---|
| A statement that admission should test reward/risk | **One box label**, "RR validation", with no quantity, threshold or rationale (§2.1 #1) |
| A rationale for `1.5 / 2.0 / 2.5` | **Nothing** |
| A definition of an independent reward quantity | **Nothing.** `tp_pool` is a feasibility input validated on side and score, never distance |
| A reason the thresholds differ by regime | **Nothing** |
| A ruling on DEAD_CALM | **Nothing**, and the one related note ("blocked at L2 anyway") is contradicted by measurement |

**INFERENCE:** writing a contract now would be inventing intent. Phase 6C
forbade exactly that for the retired gate, and the same reasoning applies here.

**The specific question for review, stated as narrowly as possible:**

> Under a deliberately fixed-R target, `rr` at admission is `tp_ratio`. Should
> the admission gate compare it to a constant at all — and if so, is that
> comparison a **regime-admissibility switch** (which is what it is), and should
> it be written as one?

---

# 7. Proposed Minimal Implementation Change — **NOT IMPLEMENTED**

Recorded so the next phase can be scoped. **Nothing below is authorised.**

## 7.1 For U4 only

**One line**, `entry_engine.calculate_entry_levels`:

```diff
- reward_distance = abs(take_profit - entry_price)
+ reward_distance = risk_distance * tp_ratio
```

`take_profit`, `risk_distance`, `stop_loss` and the returned keys are unchanged.

**Expected effect, to be measured and not assumed:**

| | Expectation |
|---|---|
| `rr` | becomes exactly `tp_ratio` for every decision |
| Gate outcomes, frozen dataset | 3 → **4** signals; the 2026-08-06 candidate admitted |
| DEAD_CALM | unchanged, still barred |
| Canonical targets, exits, P&L, R | **unchanged** (§5.1) |
| R1 fixture fingerprints | **must not change** — the fixtures run at `tp_ratio 3.0`, far from any threshold. **A change here is a STOP condition** |
| `decisions_fingerprint` | changes, by exactly the flipped candidate |

## 7.2 Sequencing

**INFERENCE:** 7.1 should land **before** U2 is decided, because it converts the
term from an artefact into a visible policy, and a policy decision taken while
the mechanism is decided by `1.7e-13` cannot be evaluated. It should land as its
own commit, with its own before/after audit, exactly as 5B-i and 5B-ii were
separated.

**It must not be bundled with any U2 decision**, or the two effects become
inseparable — the failure mode this project has repeatedly had to unwind.

---

# 8. Tests That Would Need Rewriting or Adding

| Test | Action | Why |
|---|---|---|
| `test_valid_rr_retired.test_micro_scalp_admission_turns_on_floating_point_noise` | **Rewrite** | It pins the artefact. After the repair the candidate is admitted, so the test must pin the *repaired* behaviour and record the artefact as history |
| `test_valid_rr_retired.test_the_loss_is_the_round_trip_through_take_profit` | **Keep, re-target** | The mechanism demonstration stays valid as a regression guard against reintroducing the round-trip |
| `test_baseline_defects.TestRrIsATautology.*` | **Strengthen** | `assertAlmostEqual(rr, tp_ratio, places=9)` would become `assertEqual` — exact, which is the point |
| `tests/test_entry_quality_gate.py` (all 3) | **Rewrite** | Phase 6J: they pass `rr` values (1.4, 2.4, 2.8) that **cannot occur** for the regimes they are paired with. They would still pass after the change while testing nothing real |
| **New** | Add | Each regime's `rr` equals its `tp_ratio` **exactly**, and the gate's `rr` term is therefore a deterministic per-regime constant — the §1 table, asserted |
| **New** | Add | DEAD_CALM remains barred after the repair, so the change is visibly not a DEAD_CALM decision |
| R1 regression | **Unchanged** | Must continue to pass with its pinned fingerprints |

---

# 9. Provenance Impact

| Artefact | Impact |
|---|---|
| **`baseline_004`** | **None. Untouched, not regenerated, not re-pinned.** |
| **`baseline_005`** | **None. Untouched, not regenerated, not re-pinned.** |
| R1 fixtures and their ledger fingerprints | **Expected: none.** Both run at `tp_ratio 3.0` against a `2.5` threshold — a `0.5` margin, ~12 orders of magnitude above the error. **Any change is a STOP condition** |
| `decisions_fingerprint` (current code) | Would change from `127fd774…` by exactly the flipped candidate. Development evidence only |
| Any future baseline | Must be a new id, compared against `baseline_005`, with the difference attributed to the named repair |

**Nothing in this document changed any of them.** This commit adds one document
and modifies no code, test, fixture or artefact.

---

# 10. Unresolved

| # | Question | Status |
|---|---|---|
| U2 | Should the gate compare `rr` at all? | **UNRESOLVED** — one box label is not a contract |
| U3 | If retained, what does it measure? | **UNRESOLVED** — no independent quantity is defined; inventing one is forbidden |
| U5 | Should DEAD_CALM be admissible? | **UNRESOLVED**, and **Option A decides it implicitly** — which is the strongest reason not to choose A casually |
| U1 | What is `trigger_quality`, and what should its thresholds be? | **UNRESOLVED** — after any of A/B/C it is the gate's only varying term |
| U6 | Should the rejection message name the term that failed? | **UNRESOLVED** — deferred by instruction until the contract is decided |
| U8 | `U10` regime ATR bands in dollars vs pips | **UNRESOLVED** — decides which thresholds apply at all |

---

# 11. Non-Goals

No option was selected for producing more or fewer trades. The 263 MICRO_SCALP
candidates are used **only** to size the artefact — they never reach the gate on
this dataset, and their count is not an argument for any option. No backtest
performance was consulted, and none exists: **zero trades have ever been
executed, held or closed in any measurement.**

**No profitability conclusion is drawn or available.** The three currently
admitted signals, and the fourth that any repair would add, have never been
executed. Nothing here says whether any of them would win or lose.
