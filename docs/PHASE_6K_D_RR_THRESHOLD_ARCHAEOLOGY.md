# Phase 6K-D — RR Threshold Archaeology

**Evidence audit. No production source, threshold, gate, DEAD_CALM, baseline or
R1 fixture changed.** U4 not implemented; the runtime gate is neither removed
nor relocated. No profitability or trade count was used to select a threshold.

**Input:** Phase 6K-C `5b25514`.

**Question:** does repository history contain enough evidence to recover the
*intended numerical* RR threshold, without inventing one?

## Evidence classes

**DOCUMENTED** · **STRONG HISTORICAL** · **IMPLEMENTATION** · **TEST FIXTURE** ·
**INFERENCE**

---

# 1. Verdict

> ## **HISTORICAL VALUES ONLY / CURRENT VALUE UNDOCUMENTED**

**Two historical admission thresholds are recoverable — and they contradict each
other.** The design docstring specifies **1:3**; the code that implemented it
used **`rr >= 2.0`** and called it **"Minimum 1:2"**. Both are DOCUMENTED, in the
same file, at the same commit.

**The three current regime thresholds — 1.5 / 2.0 / 2.5 — have no recovered
rationale of any kind.** They appear for the first time inside an undocumented
uncommitted-WIP window, in a function with no comments and no commit message.
Neither design document that arrived alongside them states a single RR or
quality threshold value.

**No single current value is recoverable.** Saying otherwise would require
inventing one.

---

# 2. Complete Threshold Evidence Table

| # | Source / date / commit | Value | Role | Regime | Exact rationale | Class | Confidence |
|---|---|---|---|---|---|---|---|
| 1 | `entry_engine.py:35`, `c3cf4df`, 2026-07-01 | **1:3** | **B — ADMISSION** | global | *"If calculated TP doesn't give minimum 1:3 RR → NO TRADE"* — states the rule, **not why 1:3** | **DOCUMENTED** | High (that it is admission) / **None** (that 1:3 is justified) |
| 2 | `entry_engine.py:1001`, `c3cf4df` | **2.0** | **B — ADMISSION** | global | `valid_rr = rr >= 2.0  # Minimum 1:2` — states the value, **not why 2** | **DOCUMENTED** | High / **None** |
| 3 | `entry_engine.py:967`, `c3cf4df` | **1:2** | **B — ADMISSION** | global | Docstring: `"valid_rr": bool,  # True if RR ≥ 1:2` | **DOCUMENTED** | High / None |
| 4 | `entry_engine.py:31`, `c3cf4df` | **1:3** | **A — TP CONSTRUCTION** | "for A+" | *"TAKE PROFIT (1:3 RR for A+)"* — a grade, the only qualifier found | **DOCUMENTED** | High |
| 5 | `entry_engine.py:953`, `c3cf4df` | **3.0** | **A — TP CONSTRUCTION** | default param | `rr_ratio: float = 3.0` — no rationale | **STRONG HISTORICAL** | High |
| 6 | `entry_engine.py:991`, `c3cf4df` | **3.0** | **A — TP CONSTRUCTION** | — | `# Calculate TP (1:3 RR = 3× risk)` — defines, does not justify | **DOCUMENTED** | High |
| 7 | `entry_engine.py:78/90/100/109`, `c3cf4df` → HEAD | **1.5 / 2.0 / 3.0 / 1.5** | **A — TP CONSTRUCTION** | MICRO / REGIME / INTRADAY / DEAD_CALM | Only DEAD_CALM's is commented: *"Realistic if it somehow escaped L2"* — a **fallback**, not a design value | **DOCUMENTED** (DEAD_CALM only) | High |
| 8 | `entry_engine.py:770`, `4c90b81`, 2026-09-16 | **1.5** | **B — ADMISSION** | MICRO_SCALP | **None. No comment, no commit message, no document** | **IMPLEMENTATION** | **None** |
| 9 | `entry_engine.py:781`, `4c90b81` | **2.0** | **B — ADMISSION** | REGIME_SCALP | **None** | **IMPLEMENTATION** | **None** |
| 10 | `entry_engine.py:792`, `4c90b81` | **2.5** | **B — ADMISSION** | INTRADAY_SWING | **None** | **IMPLEMENTATION** | **None** |
| 11 | `entry_engine.py:802`, `4c90b81` | **2.0** | **B — ADMISSION** | default / DEAD_CALM | **None** | **IMPLEMENTATION** | **None** |
| 12 | `entry_engine.py:770/781/792`, `4c90b81` | **5.0 / 6.0 / 7.0** | **B — ADMISSION** (quality) | per regime | **None** | **IMPLEMENTATION** | **None** |
| 13 | `main.py:8`, `main_production.py:8`, `c3cf4df` | 1:1 / 1:2 / 1:3 | **C — EXIT LADDER** | — | *"Layer 9: Trade management (partial exits 1:1/1:2/1:3 RR)"* | **DOCUMENTED** | High — **explicitly exits, not admission** |
| 14 | `order_execution.py:24/247-275`, `c3cf4df` | 1:2, 1:3 | **C — EXIT LADDER** | — | Trail SL at 1:2; TP at 1:3 | **IMPLEMENTATION** | High — exits |
| 15 | `test_week3_verification.py:78-115`, `c3cf4df` | 1:2, 1:3 | **C/D — EXIT tests** | — | Verifies exit behaviour | **TEST FIXTURE** | n/a |
| 16 | `entry_engine.py:671`, `c3cf4df` | **1.5**, 4.0 | **Neither — SCORING WEIGHT** | — | `rr_bonus = min(rr, 4.0) * 1.5` — a multiplier and a cap | **IMPLEMENTATION** | High — **a decoy: 1.5 here is not a threshold** |
| 17 | `entry_engine.py:673`, `c3cf4df` | 2.0 | **Neither — SCORING WEIGHT** | — | `(quality * 2.0)` | **IMPLEMENTATION** | High — decoy |
| 18 | `test_l6_signal_output.py:113`, `c3cf4df` | 2.0 | **D — TEST FIXTURE** | — | `"rr_ratio": 2.0` in a sample payload | **TEST FIXTURE** | n/a |
| 19 | `tests/test_entry_quality_gate.py`, `4c90b81` | q 4.2 / rr 1.4; q 6.8 / rr 2.4; q 7.2 / rr 2.8 | **D — TEST FIXTURE** | MICRO / REGIME / INTRADAY | Values straddle the thresholds — confirms they were deliberate **as written**, explains nothing about why | **TEST FIXTURE** | n/a |
| 20 | `architecture.txt`, `SYSTEM_STRUCTURE_DIAGRAM.md`, arrived `4c90b81` | **none** | — | — | Both say *"RR validation"*; **neither states a single threshold value** | **Absence of evidence** | High |
| 21 | `entry_engine.py:108/151/176/188`, `c3cf4df` | **2.5** | **Neither — ATR BAND** | MICRO / DEAD_CALM | `m5_atr >= 2.5`, `ATR < 2.5` | **IMPLEMENTATION** | High — **decoy: the only pre-WIP 2.5 is an ATR boundary** |

## 2.1 Decoys, stated explicitly

The brief warned against conflating roles. Three values look like threshold
evidence and are not:

- **`1.5` at item 16** is a scoring multiplier (`min(rr, 4.0) * 1.5`).
- **`2.0` at item 17** is a scoring weight on quality.
- **`2.5` at item 21** is an ATR band boundary — and it is the **only**
  occurrence of `2.5` in `entry_engine.py` before the WIP window. It has **no
  RR meaning** there.

---

# 3. Reconstructed Timeline

| # | Transition | Earliest evidence | Explained by a commit message or document? |
|---|---|---|---|
| 1 | Fixed TP construction at `rr_ratio = 3.0` | `c3cf4df`, 2026-07-01, `entry_engine.py:953` + docstring `:31` | **No.** Commit message is `update`. The docstring *states* 1:3 "for A+" but gives no reason |
| 2 | Global admission gate `valid_rr = rr >= 2.0` | `c3cf4df`, `entry_engine.py:1001`, conjoined into `entry_triggered` at `:733` and `:826` | **No.** Same `update` commit. The comment states "Minimum 1:2" without justification |
| 3 | `rr_ratio` → `tp_ratio` rename | Between `c3cf4df` (2026-07-01) and `4c90b81` (2026-09-16) — **uncommitted** | **No.** No commit, no message, no comment |
| 4 | `evaluate_entry_for_regime` introduced | `4c90b81`, 2026-09-16 — arrived as **uncommitted WIP** in a preservation snapshot | **No.** The snapshot's message describes *what* it preserves, not what the author was doing |
| 5 | Regime thresholds 1.5 / 2.0 / 2.5 emerge | `4c90b81`, `entry_engine.py:770/781/792` | **No.** Zero comments in the function, in any committed version |

**STRONG HISTORICAL:** transitions 3, 4 and 5 all occur inside a **single
undocumented window**. The same window deleted the 37-line design docstring
(including the "MINIMUM RR CHECK (Hard Gate)" specification), stripped every RR
intent comment, and stripped the DEAD_CALM comments. **The rationale and the new
thresholds changed places in one unrecorded edit.**

## 3.1 What the branches contain

**OBSERVED.** Five refs exist: `main` and `origin/main` point at the Initial
commit only; `test` at `4c90b81`; `origin/test` at `a6f9f4b`;
`phase-0-1-foundations` at HEAD. **`a6f9f4b` does not modify `entry_engine.py`
at all** relative to `c3cf4df` — checked by diff. No branch contains threshold
evidence absent from the main line.

**OBSERVED.** `"Hard Gate"` also appears at the Initial commit (`2186e66`) in
`ai_analyst.py` — *"Python rule engine → technical score + hard gates"*. That is
a general architecture phrase about the rule engine, **unrelated to RR**, and is
recorded here only so it is not mistaken for earlier threshold evidence.

---

# 4. Strongest Evidence for Each Candidate Value

**For 3.0 / 1:3** — item 1: *"minimum 1:3 RR → NO TRADE"*, the only place a
value and the word "minimum" appear together with a rejection outcome.
**Against it:** the code never implemented 1:3 as a minimum. Item 4 shows the
same docstring uses 1:3 for *TP construction*, and the brief correctly warns a
construction multiple is not automatically an admission threshold. The docstring
is the **only** source for 1:3-as-minimum, and the implementation contradicted
it immediately.

**For 2.0 / 1:2** — items 2 and 3: the value that was actually *implemented* as
an admission gate, stated twice (code comment and docstring annotation).
**Against it:** the brief explicitly warns against treating 2.0 as canonical
merely because the original code used it. No rationale accompanies it, and it
contradicts the design docstring in the same file.

**For 1.5 / 2.0 / 2.5 (regime-specific)** — items 8–11: they are the values in
force today and the only ones a reader of HEAD would find. **Against them:**
**no rationale exists at any strength.** No comment, no commit message, no
design document, no test that explains rather than exercises. They arrived in
an unrecorded edit.

**For a regime-specific *shape* (as opposed to values)** — **INFERENCE only, and
it does not establish intent.** Two observations, recorded because they are
factual and because omitting them would be selective:

1. MICRO_SCALP's threshold (**1.5**) and REGIME_SCALP's (**2.0**) are **exactly
   those regimes' own `tp_ratio`**. INTRADAY_SWING's (**2.5**) is **not** its
   `tp_ratio` (3.0).
2. Both the quality ladder (5.0 / 6.0 / 7.0) and the RR ladder (1.5 / 2.0 / 2.5)
   rise monotonically with regime timeframe.

**Neither observation is rationale.** The brief forbids inferring rationale from
the resulting number alone, and these are exactly that. They are recorded as
patterns, not explanations. Pattern 1 in particular is equally consistent with
values copied from the `tp_ratio` table and with values chosen independently
that happen to coincide — and pattern 1 **breaks** for INTRADAY_SWING, which is
itself a reason not to read intent into it.

---

# 5. Contradictions

| # | Contradiction | Sources |
|---|---|---|
| 1 | **Design says 1:3, code says 1:2** — in the same file, at the same commit | Items 1 vs 2/3 |
| 2 | **TP is fixed at 3× risk while a gate tests whether TP achieves a minimum** | Items 4/5/6 vs 1 — 6K-C's finding, restated |
| 3 | **The global gate (2.0) was replaced by regime gates (1.5/2.0/2.5) with no record**, and for a time both existed — `valid_rr >= 2.0` at `:409` *and* the regime gate — until Phase 6I retired the former | Items 2 vs 8–11 |
| 4 | **DEAD_CALM's `tp_ratio = 1.5` is a documented fallback**, yet the default gate demands 2.0 — so a value chosen as "realistic if it somehow escaped" is judged against a threshold it cannot meet | Item 7 vs 11 |
| 5 | **Test fixtures use `rr` values that cannot occur** (1.4, 2.4, 2.8 against `tp_ratio` 1.5, 2.0, 3.0) | Item 19 |

**INFERENCE on #5, labelled as such:** the test author treated `rr` as a free
variable. Combined with *"Recalculate or wait for better level"* (6K-C item 2),
this is consistent with the author believing throughout that `rr` was a measured
quantity that could fall short. It does not establish what threshold was
intended, and it is interpretation, not evidence.

---

# 6. Answers to the Required Determinations

**Is any threshold recoverable as CLEAR 1.5?** No. Only as an undocumented
current value, a scoring multiplier, or a regime `tp_ratio`.

**CLEAR 2.0?** No. It is the *implemented historical* admission value, with no
rationale, contradicted by the design docstring in the same file.

**CLEAR 2.5?** No. Its only pre-WIP occurrence is an ATR boundary; as an RR
threshold it appears once, undocumented.

**CLEAR 3.0?** No. Documented as a *TP construction* multiple and, once, as a
"minimum 1:3" that was never implemented.

**REGIME-SPECIFIC VALUES recovered?** **No.** The values exist; **no rationale
for any of them was found at any evidence strength.**

> ## **MULTIPLE HISTORICAL VALUES / NO SINGLE CURRENT VALUE RECOVERABLE**

---

# 7. The Remaining Human Decision

> **What the minimum RR should be, and whether it is one value or four.**
>
> History supplies **two** conflicting admission values — a documented **1:3**
> that was never implemented, and an implemented **1:2 / 2.0** that the same
> file's design section contradicts — plus **three current values with no
> rationale at any strength**. Nothing in 82 commits, five refs, two design
> documents or any test reconciles them.
>
> This is not recoverable by further archaeology. **The evidence is exhausted.**

**Subsidiary decisions this depends on, all still open:**

- Whether the minimum is global (as at `c3cf4df`) or per-regime (as now). The
  transition between the two is the single least-documented event in the
  repository's history.
- Whether DEAD_CALM's `tp_ratio = 1.5` — a documented **fallback** — should be
  judged against any minimum at all.
- Whether INTRADAY_SWING's `2.5` was meant to be `3.0`, given it is the only
  regime whose threshold does not equal its own ratio. **No evidence either
  way; recorded as a question, not a suggestion.**

**What archaeology has settled, and should not be re-litigated:** that an
admission rule was intended (6K-C), and that `rr` is the configured multiple and
not a market measurement (6K-B). **Only the number is open.**

---

# 8. Confirmation

| | |
|---|---|
| Source modifications | **None.** No `.py` file touched |
| Threshold modifications | **None** |
| Baseline modifications | **None.** `baseline_004` / `baseline_005` untouched, not re-pinned |
| R1 modifications | **None** |
| U4 implementation | **Not done** |
| DEAD_CALM behaviour | **Unchanged** |
| Backtest optimization | **None run** |
| Working tree | Clean; this commit adds one document |

**New evidence recorded by this phase:** the complete role-classified inventory
of every RR-adjacent numeric literal at `c3cf4df`; the identification of three
**decoy** values (a scoring multiplier, a scoring weight, an ATR boundary) that
resemble thresholds and are not; confirmation that `2.5` had **no RR meaning**
before the WIP window; confirmation that **neither design document states any
threshold**; and the branch survey establishing that `origin/test` contains no
`entry_engine.py` change.

**No profitability conclusion is drawn or available.**
