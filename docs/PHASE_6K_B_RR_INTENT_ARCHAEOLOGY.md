# Phase 6K-B — RR Intent Archaeology

**Evidence audit. No production code, threshold, gate, regime rule or baseline
changed.** No backtest performance, trade count or signal count was used as
evidence of intent.

**Input:** Phase 6K-A `87f4b47`.

**Question:** was the RR condition historically intended to mean **(A)** the
configured target multiple, or **(B)** an independently measured market-derived
reward/risk opportunity?

## Evidence labels

**DOCUMENTED** — explicit stated intent (comment, doc, commit message).
**STRONG HISTORICAL** — explicit historical design or naming evidence in a
version-controlled artefact.
**IMPLEMENTATION** — observed code behaviour only.
**INFERENCE** — interpretation; not evidence.

---

# 1. Verdict

## 1.1 On what `rr` means: **CLEAR A**

**The author's own RR concept was the configured multiple of risk.** This is
established by evidence that **no longer exists at HEAD** and was recovered from
`c3cf4df` (2026-07-01), the earliest committed version of `entry_engine.py`:

> **The multiplier that builds `take_profit` was originally named `rr_ratio`.**
>
> ```python
> def calculate_entry_levels(..., rr_ratio: float = 3.0, ...):
>     # Calculate TP (1:3 RR = 3× risk)
>     take_profit = entry_price + (risk_distance * rr_ratio)
>     ...
>     # Validate RR
>     valid_rr = rr >= 2.0  # Minimum 1:2
> ```

The parameter is called the **risk-reward ratio**, the comment equates
**"1:3 RR" with "3× risk"**, and the threshold comment reads **"Minimum 1:2"** —
reward at least twice risk. There is no ambiguity about what the author meant:
RR *is* the multiple of risk used to construct the target.

**It was later renamed `rr_ratio` → `tp_ratio`** in uncommitted work, with no
commit message. **INFERENCE:** that rename is why later audits — including my
own — read the multiplier as a "target ratio" and treated the gate as though it
*might* be testing something independent. It never was.

## 1.2 On the surviving gate's thresholds: **UNDOCUMENTED**

`evaluate_entry_for_regime` contains **zero comments in every committed version
of the file**, including the first. It has no commit message of its own (§3.2).
**No historical rationale exists for `1.5`, `2.0`, `2.5`, or for `5.0 / 6.0 /
7.0`.**

## 1.3 Consequence

The two questions separate cleanly:

| | Status |
|---|---|
| **U3 — what does the RR term measure?** | **RESOLVED by evidence: the configured multiple of risk.** Not market opportunity |
| **U2 — should the gate compare it, and at what value?** | **UNDOCUMENTED. Still a policy decision.** §8 |

---

# 2. Evidence Table

| # | Evidence | Source / date / commit | Exact meaning | A | B | Strength |
|---|---|---|---|---|---|---|
| 1 | `rr_ratio: float = 3.0` — the parameter that builds `take_profit` | `entry_engine.py:953`, `c3cf4df`, 2026-07-01 | The multiplier **is** the risk-reward ratio | ✅ | — | **STRONG HISTORICAL** |
| 2 | `# Calculate TP (1:3 RR = 3× risk)` | `entry_engine.py:991`, `c3cf4df` | "1:3 RR" **means** 3× risk | ✅ | — | **DOCUMENTED** |
| 3 | `valid_rr = rr >= 2.0  # Minimum 1:2` | `entry_engine.py:1001`, `c3cf4df` | Threshold means reward ≥ 2× risk | ✅ | — | **DOCUMENTED** |
| 4 | `# Validate RR` | `entry_engine.py:1000`, `c3cf4df` | Names the activity; no quantity | ✅ weak | — | DOCUMENTED (weak) |
| 5 | `reasoning = f"... RR {rr:.1f}:1"` | `c3cf4df` | Formats as `N:1` — the R-multiple convention | ✅ | — | IMPLEMENTATION |
| 6 | `take_profit = entry_price + (risk_distance * rr_ratio)` | `c3cf4df` → HEAD, unchanged | Target built from risk × multiple, never from a market level | ✅ | ❌ | IMPLEMENTATION |
| 7 | *"evaluate_entry_for_regime(): Validates RR ratio and determines MARKET/LIMIT entry mode"* | `architecture.txt:830` (arrived `4c90b81`) | Names the activity; no quantity, threshold or rationale | neutral | neutral | DOCUMENTED (weak) |
| 8 | *"Step 3: evaluate_entry_for_regime() • RR validation"* | `SYSTEM_STRUCTURE_DIAGRAM.md:365` | Same label, same absence | neutral | neutral | DOCUMENTED (weak) |
| 9 | *"1:1 → CLOSE_50PCT, 1:2 → TRAIL_SL, 1:3 → CLOSE_ALL"* | `SYSTEM_STRUCTURE_DIAGRAM.md:413-416`, `architecture.txt:838-840`, `FLOW_DIAGRAM_WITH_FLAWS.md:172-173`, `trade_manager.py:4-10` | Every RR usage outside admission is an **R-multiple of risk** | ✅ | — | **DOCUMENTED** |
| 10 | `exit_1_1 = entry + risk`, `exit_1_2 = entry + risk×2`, `exit_1_3 = take_profit` | `order_execution.py:118-120` | The ladder **closes on** `take_profit`, so `take_profit` is the 3R rung | ✅ | — | IMPLEMENTATION |
| 11 | **`take_profit` was NEVER derived from `tp_pool`** | all 80 commits, searched | The market-derived target has no implementation history | — | ❌ | **STRONG HISTORICAL** |
| 12 | **No commit ever computed `rr` or `reward` from `tp_pool`** | all 80 commits, searched | No market-derived RR ever existed | — | ❌ | **STRONG HISTORICAL** |
| 13 | `evaluate_entry_for_regime` has **no comment in any committed version** | `4c90b81` → HEAD | No rationale for `1.5 / 2.0 / 2.5` | neutral | neutral | **Absence of evidence** |
| 14 | The gate and its tests arrived as **uncommitted WIP in a preservation snapshot** | `4c90b81`, 2026-09-16 | No authored commit message exists for it | neutral | neutral | **STRONG HISTORICAL** |
| 15 | `rr_ratio` renamed to `tp_ratio`, silently, in uncommitted WIP | between `c3cf4df` and `4c90b81` | The only evidence that could favour B — and it is a rename, not a redefinition | — | ~ weak | INFERENCE |

---

# 3. Commit-History Findings

## 3.1 The repository has 80 commits and almost no messages

**OBSERVED.** The twelve oldest are `Initial commit`, `hi first`, `update`,
`updaet`, `update`, `h`, `update` ×5, `upda`. **No pre-project commit message
mentions RR, reward, target or TP.**

`entry_engine.py` has been touched by exactly **four** commits:

| Commit | Date | Message | Relevance |
|---|---|---|---|
| `c3cf4df` | 2026-07-01 | `update` | **The earliest committed `entry_engine.py`.** Carries every intent comment in §2 |
| `4c90b81` | 2026-09-16 | `chore: baseline before phase 0/1 foundations` | **Introduces `evaluate_entry_for_regime`** and strips the intent comments |
| `8a4e010` | 2026-09-17 | `feat(execution): first LIMIT_FVG control experiment` | This project |
| `8c5724c` | 2026-09-24 | `feat(strategy): retire the redundant per-candidate valid_rr gate` | This project |

## 3.2 The surviving gate has no authored provenance

**OBSERVED.** `4c90b81`'s own message describes itself as a *"Preservation
snapshot of the working tree exactly as it existed before any Phase 0 or Phase 1
work… 12 modified engine/orchestration files (uncommitted WIP), the previously
untracked `tests/` directory."*

**INFERENCE, premises above:** `evaluate_entry_for_regime` and its only
dedicated tests (`tests/test_entry_quality_gate.py`) were both **uncommitted
working-tree changes**, captured wholesale. **There is no commit in which the
author explained, or was asked to explain, this gate or its thresholds.** Its
absence of rationale is not an oversight in documentation — there was never a
moment at which rationale was recorded.

## 3.3 The intent comments were removed, not revised

**OBSERVED.** None of `# Calculate TP (1:3 RR = 3× risk)`, `# Validate RR`,
`# Minimum 1:2`, or the `rr_ratio` name survives at HEAD. They were stripped in
the same uncommitted window that renamed the parameter and added the new gate.

**INFERENCE:** every later reader of this code — including four phases of this
project's own audits — worked from a version with the intent deleted. That is
why "does RR mean the configured multiple or a market measurement?" looked open.
**At `c3cf4df` it was never open.**

---

# 4. The `tp_pool` Investigation

Answering the eight questions asked.

**1. What is it?** **DOCUMENTED**, `architecture.txt:246`: *"tp_pool:
take-profit cluster level + score"* — a clustered liquidity level on
M15/H1/H4/Daily where price might travel, with a quality score.

**2. How is it calculated?** **IMPLEMENTATION**, `liquidity_engine.py:618-652`:
`identify_liquidity_pools` scans for clustered highs/lows; directional
candidates are ranked by `_rank_directional_pool` and the best on the correct
side becomes `tp_pool`.

**3. Independent of `tp_ratio`?** **Yes, completely.** It derives from price
structure. `tp_ratio` is a regime constant. They share no input.

**4. Does it represent realistic available reward?** **It is the only quantity
in the repository that could.** Phase 4B measured entry→`tp_pool` distance
against entry→stop: **median RR 0.25**, `≥1.0` on 5.85 %, `≥2.0` on 1.26 %.

**5. Was it ever connected to entry admission?** **Yes — but at L4, not L8.**
**DOCUMENTED**, `architecture.txt:781`: *"assess_liquidity_gate(): Validates
sweep pool quality, distance from current price, and TP pool quality."*
**INFERENCE, and it matters:** the *distance* test is on the **sweep** pool;
`tp_pool` is validated on **quality/score only**. Its distance — the thing an RR
would need — is never gated on.

**6. Was it ever described as RR?** **No.** **OBSERVED:** searched all 80
commits — no commit ever computes `rr` or `reward` from `tp_pool`.

**7. Was it ever described as an entry filter?** **Only as an L4 quality
input.** Never as an RR or reward filter.

**8. Why was it removed/bypassed/unused?** **It was never removed, because it
was never used for this.** **OBSERVED:** `take_profit` was **never** derived
from `tp_pool` in any of the 80 commits. There is no history of a market-derived
target being tried and abandoned — the fixed-R construction is the only one that
has ever existed.

---

# 5. DEAD_CALM — New Documented Evidence

Phase 6J classified DEAD_CALM's fall-through as *undocumented*. **That was
correct for HEAD. It is not correct for `c3cf4df`**, where the entire block is
commented:

```python
# Dead calm (ATR < 2.5) - Will be BLOCKED by L2, but show proper config anyway
regime = "DEAD_CALM"
risk = 0.75              # Show a value even though trade won't happen
tp_ratio = 1.5           # Realistic if it somehow escaped L2
bypass_l3 = False
bypass_l6 = False
poi_threshold = 70       # Normal threshold (won't matter, L2 blocks first)
max_spread_pips = 5.0    # N/A (will be blocked at L2)
```

**DOCUMENTED INTENT, recovered:**

1. **DEAD_CALM's entire configuration is cosmetic.** *"show proper config
   anyway"*, *"Show a value even though trade won't happen"*, *"won't matter, L2
   blocks first"*, *"N/A"*.
2. **`tp_ratio = 1.5` was a fallback, not a designed admission parameter** —
   *"Realistic if it somehow escaped L2"*. The author anticipated escape and
   chose a plausible value, not a considered one.
3. The belief survives at HEAD only in a user-facing string:
   `"DEAD_CALM: M5 ATR {…} too low → Will be BLOCKED at L2"`. **Every comment was
   stripped.**

**MEASURED, and it contradicts the premise:** **22 DEAD_CALM decisions reached
L8**, and `L2_STRUCTURE` blocked **7** decisions in total across all regimes.
DEAD_CALM is not blocked at L2.

**INFERENCE:** DEAD_CALM's inability to enter is **not a designed exclusion**.
It is the incidental product of a fallback `tp_ratio` meeting an undocumented
threshold, inside a gate the author expected never to be reached by that regime.
**Not fixed here.**

---

# 6. The Four Required Statements

## A. Strongest evidence **for** A

**The parameter was named `rr_ratio` and the comment equates "1:3 RR" with "3×
risk"** (evidence 1–3, `c3cf4df`). The author wrote `take_profit = risk ×
rr_ratio` and immediately called `rr >= 2.0` a *"Minimum 1:2"*. Nothing about
that is ambiguous, and it is corroborated by every other documented RR usage in
the repository — the 1:1 / 1:2 / 1:3 exit ladder — all of which are multiples of
risk.

## B. Strongest evidence **for** B

**There is none of any strength.** The strongest available is evidence 15: the
silent rename `rr_ratio` → `tp_ratio`, which *could* be read as the author
distinguishing "target ratio" from some other "RR". **INFERENCE:** a rename
toward the thing the variable constructs is at least as consistent with A, and
no accompanying code, comment or commit introduced a second quantity. This is
interpretation, not evidence.

## C. Strongest evidence **against** A

**The thresholds of the surviving gate do not follow from A.** If RR is the
configured multiple, then `rr >= 1.5` in MICRO_SCALP (whose multiple **is** 1.5)
is a comparison that cannot fail, and `rr >= 2.0` for DEAD_CALM (multiple 1.5)
is one that cannot pass. **INFERENCE:** either the thresholds were written
without noticing they test a constant, or they were meant as regime
admissibility. The evidence does not say which — **which is exactly why U2
remains open.**

## D. Strongest evidence **against** B

**`take_profit` was never derived from `tp_pool` in any of 80 commits, and no
commit ever computed `rr` or `reward` from it** (evidence 11–12). The one
market-derived reward quantity that exists is validated on **quality, never on
distance** (`architecture.txt:781`), and distance is what an RR would require. B
has no implementation history, no documentation, and no abandoned attempt.

## E. Verdict

| Question | Category |
|---|---|
| **What the RR quantity was intended to mean** | **1 — CLEAR A** |
| **Whether the surviving gate should compare it, and at what value** | **4 — UNDOCUMENTED** |

**This is not a MIXED verdict.** The two questions are different: the *semantics*
are documented and unambiguous; the *policy* was never recorded at all.

## F. The exact unresolved question

> Given that `rr` is, by the author's own definition, the configured multiple of
> risk — should regime admissibility be expressed as a runtime comparison of
> that multiple inside `evaluate_entry_for_regime`, or as a configuration
> invariant where `tp_ratio` is chosen? And if the comparison is retained, what
> are `1.5`, `2.0` and `2.5` meant to be, given that no rationale was ever
> recorded and two of them cannot fail while one cannot pass?

## G. Can U2 / U3 now be resolved without inventing policy?

**U3 — yes.** The quantity is the configured multiple of risk. That is
evidence-established, and no invention is required to say so.

**U2 — no, but the question is now much smaller.** Because U3 is settled, the
RR term is *definitionally* a regime-admissibility switch: it compares a regime
constant to another constant. So U2 is no longer "what is this measuring?" but
"where should a regime-admissibility rule live, and what should it say?" —
a policy question with no recorded answer.

**What this archaeology removes from the decision:** Option B is no longer a
live alternative on historical grounds. It could still be *adopted* as new
design, but it cannot be justified as *restoring* intent. Nothing was ever built
that way.

---

# 7. Do the Thresholds Have Any Historical Rationale?

**No.**

| Threshold | Rationale found |
|---|---|
| `valid_rr >= 2.0` *(retired)* | **The only one with any**: `# Minimum 1:2` — states the meaning, not the reason for 2 |
| `rr >= 1.5` (MICRO_SCALP) | **None** |
| `rr >= 2.0` (REGIME_SCALP) | **None** |
| `rr >= 2.5` (INTRADAY_SWING) | **None** |
| `rr >= 2.0` (default / DEAD_CALM) | **None** |
| `quality >= 5.0 / 6.0 / 7.0` | **None** |

**OBSERVED:** the gate has never carried a comment, and never had a commit
message. `tp_ratio` values *do* carry comments in `c3cf4df` (e.g. *"Realistic if
it somehow escaped L2"*, *"Strict standards for high-vol setups"*) — so the
author did comment configuration when they had a reason. **The gate's thresholds
were not commented.**

---

# 8. Confirmation

| | |
|---|---|
| Source changes | **None.** No `.py` file modified |
| Threshold changes | **None** |
| `baseline_004` / `baseline_005` | **Untouched**, not regenerated, not re-pinned |
| R1 fixtures / fingerprints | **Unchanged** |
| DEAD_CALM, `trigger_quality`, the RR gate | **Unmodified** |
| U4 arithmetic repair | **Not implemented** |
| Working tree | Clean; this commit adds one document |

**No backtest performance, trade count, signal count or profitability figure was
used as evidence of intent**, and none is available: zero trades have ever been
executed, held or closed in any measurement.
