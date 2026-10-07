> **CLOSED 2026-10-06 — not pursued, strategy frozen (D1). See `docs/LEGACY_FROZEN.md`.**

# Phase 8 — Research Ledger and Experimental Framework

**Framework only. No experiment has been run. No production code, test, pin,
fingerprint or baseline was changed in creating this document.**

**Reference point:** `baselines/baseline_006` at commit
`a1029a9c609b2d6788978d2a701eb9da2dc2d309`, installed and committed as
`9df761f`. Every Phase 8 experiment compares against it.

> ### Stage 0 correction notice — 2026-09-29
>
> **Stage 0 discovered that the original ledger overstated what `baseline_006`
> artifacts could measure for P8-13 and P8-19. Those measurement gaps are now
> explicitly recorded.**
>
> `decisions.jsonl` carries only `t`, `regime`, `side`, `signal`, `blocked`,
> `passed`, `reason`, `price`. It has no POI fields and no per-decision
> `risk_distance`, so two questions the original Stage 0 scoping called
> "read-only" are not answerable from the artifacts at all.
>
> Corrections appear as **Stage 0 update** blocks beneath each item. Original
> rows are retained unaltered except for pointers, so the prior finding and its
> correction can both be read. **No prior finding has been deleted.** Items
> corrected: **P8-04, P8-06, P8-07, P8-13, P8-18, P8-19**. **No replay was run**
> to produce any of it.

**This ledger does not rank anything.** It contains no judgement about which
item matters most, which change would perform best, or which value any
undetermined parameter should take. §4's sequence is a *dependency* order, not a
priority order. Anyone reading a preference into it is reading something that was
deliberately not written.

---

## Classification scheme

| Class | Meaning |
|---|---|
| **A — Mechanical defect** | The code does something demonstrably different from what it computes elsewhere or from what its own units imply. Correctness question; has a right answer |
| **B — Strategy-contract decision** | The code is internally consistent but the intended contract is undetermined. Requires an owner decision, not evidence |
| **C — Edge hypothesis** | A claim about market behaviour that could in principle be tested. Requires an experiment |
| **D — Documentation / residual code** | No operational effect. Cleanup or annotation only |
| **E — Observation only** | Recorded behaviour; no action currently justified by available evidence |

**"Alters production behaviour"** means: would change the decision stream of the
frozen replay. Determined by inspection where the answer is provable, and marked
**UNMEASURED** where it is not — an unmeasured answer is not a small one.

---

# 1. Core ledger

## P8-01 — L3 `0.786` acceptance-ceiling provenance

| Field | |
|---|---|
| **Current behaviour** | Retracement accepted on `0.236 <= p <= 0.786`. `0.786` is the upper bound |
| **Evidence** | D-6OF-2F. The five ratios were inherited wholesale from `fibonacci_levels.py` (`a11e405`, 2026-05-13) as the standard Fibonacci set; the accepted band is exactly `[min, max]` of that set. `0.618` carries the annotation *"Golden ratio - most important"*; **`0.786` carries none**. The boundary has never been modified since creation |
| **Classification** | **B** (contract), with an unresolved-provenance flag |
| **Alters production?** | **Yes** — any change to the ceiling moves L3 admissions. Phase 6O-B measured 21 decisions in 61.8–78.6% and 363 in 78.6–100% among blocked decisions reporting a retracement |
| **Historical intent** | **NOT established.** No repository evidence explains why 78.6% was selected as a ceiling. A structural explanation exists (it is the largest member of the inherited set) but that is not intent |
| **Mechanical or strategy?** | **Strategy choice** |
| **Evidence required first** | External: what the ceiling is *for*. No repository artefact can supply it |
| **Phase 8 experiment** | None that settles provenance. A sensitivity sweep would describe what different ceilings admit; it cannot recover intent, and running one risks substituting a preferred outcome for a missing rationale |
| **Defer?** | **Yes** — pending an owner decision on what the band is meant to express |

## P8-02 — Historical RR numerical minimum unrecoverable

| Field | |
|---|---|
| **Current behaviour** | No repository-wide minimum RR exists. Per-regime gate minimums are 1.5 / 2.0 / 2.5 / default 2.0 |
| **Evidence** | U9-RR, Phase 6K-D. The original design docstring specified **1:3** (*"MINIMUM RR CHECK (Hard Gate) … NO TRADE"*); the code implementing it used **`rr >= 2.0`** and called it *"Minimum 1:2"*. Both DOCUMENTED, same file, same commit `c3cf4df`. The three current gate thresholds have no recovered rationale of any kind |
| **Classification** | **B** |
| **Alters production?** | Depends entirely on the value chosen |
| **Historical intent** | **CONTRADICTORY and therefore not established.** Two documented values disagree |
| **Mechanical or strategy?** | **Strategy choice** |
| **Evidence required first** | **P8-03 must be resolved first.** While `rr ≡ tp_ratio`, choosing a minimum is not an RR policy — it is a regime-admissibility policy in RR clothing (Phase 6K-E) |
| **Phase 8 experiment** | **None while P8-03 stands.** An RR sweep would measure which regimes each value permits, not which RR is appropriate |
| **Defer?** | **Yes — blocked by P8-03** |

## P8-03 — The surviving RR comparison is mathematically degenerate

| Field | |
|---|---|
| **Current behaviour** | `take_profit = entry ± risk_distance × tp_ratio`, then `rr = reward_distance / risk_distance`, so **`rr ≡ tp_ratio` identically**. `evaluate_entry_for_regime` compares that constant against a per-regime constant. The verdict is fixed per regime before any price is read |
| **Evidence** | U9-RR §4; `entry_engine.py:432-435` carries the comment in-source; `defect_observations.json` E9/E10/Q3 |
| **Classification** | **B** — structural, not a coding error |
| **Alters production?** | **Yes, necessarily.** Any construction that makes `rr` price-derived changes which decisions pass L8 |
| **Historical intent** | **Partially established.** The *designed* intent was a per-opportunity gate (*"Recalculate or wait for better level"*) — DOCUMENTED and never implementable, because TP was always built at the ratio. The *current* structure is a consequence, not a decision |
| **Mechanical or strategy?** | **Strategy choice.** Making RR meaningful requires a market-derived target (structure, liquidity, measured move), which is a new strategy contract, not a repair |
| **Evidence required first** | An owner decision on whether the target should remain a fixed multiple of risk or become market-derived. Phase 4B (`PHASE_4B_TARGET_SEMANTICS`) already framed this as market-derived vs fixed-R |
| **Phase 8 experiment** | **Candidate, and the pivotal one.** Construct a market-derived target as an *alternative* path, replay, compare against baseline_006. Must not replace the existing construction until compared |
| **Defer?** | **No** — but it requires the owner decision above before an experiment is meaningful |

## P8-04 — DEAD_CALM barred by the surviving RR branch (mechanism)

| Field | |
|---|---|
| **Current behaviour** | `evaluate_entry_for_regime` has no DEAD_CALM branch, so DEAD_CALM falls to the default `rr >= 2.0` against a `tp_ratio` of 1.5. `1.5 >= 2.0` is false, so DEAD_CALM is structurally unable to enter |
| **Evidence** | U9-RR §4; baseline_006: DEAD_CALM 119 decisions, **0 reached L8**, 0 signals |
| **Classification** | **A** — the absence of a branch is an omission, not a stated rule |
| **Alters production?** | ~~**Yes, but bounded.** … adding a branch alone may change nothing — **UNMEASURED**~~ **SUPERSEDED — now measured; see Stage 0 update** |
| **Historical intent** | **NOT established.** No artefact says DEAD_CALM should or should not trade. It is a catch-all `else`, as Phase 6M/6N documented |
| **Mechanical or strategy?** | **Mechanical** in form (missing branch), **strategy** in consequence (whether DEAD_CALM trades) — see P8-05 |
| **Evidence required first** | P8-05's answer. The branch cannot be written without knowing what it should say |
| **Phase 8 experiment** | ~~Measure where DEAD_CALM's 119 decisions currently terminate~~ — **DONE in Stage 0, no replay used** |
| **Defer?** | **No** for the measurement; **yes** for any code change |

### Stage 0 update (2026-09-29) — measured; the conclusion inverts

**The RR branch blocked no DEAD_CALM decision in `baseline_006`.** All 119
terminate before L8:

| Terminal layer | Decisions |
|---|---|
| L1_BIAS | **65** |
| L3_PULLBACK | **46** |
| L5_SWEEP | **8** |
| Reached L8 | **0** |
| Signals | **0** |

The default `rr >= 2.0` branch is therefore **never evaluated** for DEAD_CALM on
this dataset. The original row's implication — that the branch is what bars
DEAD_CALM — is wrong for `baseline_006`. Earlier layers are.

**It is not structurally dead code either.** Cross-checked against the earlier
baselines, where the population was nineteen times larger:

| Baseline | DEAD_CALM decisions | Reached L8 | Signals |
|---|---|---|---|
| `baseline_004` | 2,312 | **22** | 0 |
| `baseline_005` | 2,312 | **22** | 0 |
| `baseline_006` | 119 | **0** | 0 |

The branch was reachable for 22 decisions before D-6N-1 shrank the population.
**It is dataset-dependent reachable code**, and its reachability is governed by
regime classification — hence the new soft dependency on **P8-14**.

**Exception-path inconsistency, discovered in Stage 0.** `detect_regime` assigns
DEAD_CALM `tp_ratio = 1.5` on its normal path (`entry_engine.py:126`) and
`tp_ratio = 2.0` on its exception path (`entry_engine.py:160`). Since
`rr ≡ tp_ratio`, DEAD_CALM is **inadmissible when regime detection succeeds and
admissible when it errors**. Recorded, not resolved.

**A second contradiction:** DEAD_CALM's reasoning string says *"too low → Will be
BLOCKED at L2"*. **Zero** of the 119 block at L2. The stated expectation is wrong
about the layer as well as the mechanism.

**Revised classification:** **B — unresolved contract**, not A. A missing branch
cannot be called an omission until it is known what the branch should say.
**The contract question remains P8-05 and is not resolved here.**

**Dependencies:** hard on **P8-05**; soft on **P8-14**. Moves from Stage 0 to
**Stage 3**.

## P8-05 — Should DEAD_CALM trade at all? (contract)

| Field | |
|---|---|
| **Current behaviour** | DEAD_CALM is reached when M5 ATR < 2.5 and the reasoning string says *"too low → Will be BLOCKED at L2"* — but D-6N-1 separated volatility from session, and the population fell from 2,312 to 119 |
| **Evidence** | Phase 6M/6N: DEAD_CALM is a catch-all `else`, and the author's own reasoning string asserts a block that L2 does not actually perform |
| **Classification** | **B** |
| **Alters production?** | **Yes** if DEAD_CALM is made tradeable; **no** if the current bar is made explicit |
| **Historical intent** | **Ambiguous.** The name and the reasoning string say "do not trade"; no gate implements that directly |
| **Mechanical or strategy?** | **Strategy choice** |
| **Evidence required first** | Owner decision: is DEAD_CALM a *regime* or a *rejection*? |
| **Phase 8 experiment** | None until decided. If the answer is "rejection", the correct change is an explicit block with a stated reason, which is a contract change, not an experiment |
| **Defer?** | **Yes** |

## P8-06 — MICRO_SCALP / REGIME_SCALP exact-equality RR boundaries

| Field | |
|---|---|
| **Current behaviour** | MICRO_SCALP gates `rr >= 1.5` against a `tp_ratio` of 1.5; REGIME_SCALP gates `rr >= 2.0` against 2.0. Admission turns on floating-point equality |
| **Evidence** | U9-RR §4. U4 (`7b1c5f1`) is the demonstration: the 2026-08-06 candidate computed `rr = 1.4999999999999196`, 8e-14 below the boundary, and was refused. Correcting the reward derivation moved signals **3 → 4**. That candidate is signal #2 in baseline_006 |
| **Classification** | **A** |
| **Alters production?** | **Yes — demonstrably.** One signal out of four in the current baseline exists because of this |
| **Historical intent** | **NOT established** that the boundary should be an equality test. Nothing records the thresholds being chosen to coincide with the ratios |
| **Mechanical or strategy?** | **Mechanical.** A gate whose outcome depends on the last bits of a float is not expressing a strategy |
| **Evidence required first** | None to characterise it; it is proven. A *fix* requires deciding whether the comparison should be `>=` with tolerance, or whether the coincidence of thresholds and ratios should be removed — which touches P8-02 |
| **Phase 8 experiment** | ~~Measure how many L8-reaching decisions sit within float tolerance~~ — **DONE in Stage 0, no replay used** |
| **Defer?** | **No** for the measurement. The fix is coupled to P8-02/P8-03 and should not be made in isolation |

### Stage 0 update (2026-09-29) — measured

Recomputed from `trade_ledger.json` for every decision that reached the gate:

| Trade | `risk_distance` | `rr = (rd × 1.5) / rd` | `>= 1.5` | Exactly `1.5`? |
|---|---|---|---|---|
| 1 | 2.3649999999997817 | 1.5 | yes | **yes** |
| 2 | 2.6649999999999636 | 1.5 | yes | **yes** |
| 3 | 2.785000000000764 | 1.5 | yes | **yes** |
| 4 | 8.534999999999854 | 1.5 | yes | **yes** |

**All four decisions that reached the RR gate compute exactly 1.5 against a
threshold of exactly 1.5** — not near the boundary, on it. That is the gate's
entire input population.

**The gate rejected zero decisions.** All **1,583** L8 blocks carry the single
reason *"Entry triggers not all confirmed"* — the `entry_triggered` check at
`main_production.py:1023`, **before** `evaluate_entry_for_regime`. None of the
gate's own messages appears in `layer_funnel.json`. Of 1,587 decisions reaching
L8, 1,583 died before the gate and 4 passed it.

**So `baseline_006` contains no evidence of the gate rejecting an ordinary
decision.** The one historical rejection is the pre-U4 case
(`rr = 1.4999999999999196`), which `7b1c5f1` removed.

**Remains coupled** to P8-02 and P8-03; must not be repaired in isolation. No
code altered.

## P8-07 — U9-H1: H1 ATR gate units

| Field | |
|---|---|
| **Current behaviour** | `main_production` gates on `h1_atr < 8.0` and reports it as "pips"; the value is quote-currency dollars, so the real threshold is **$8.00 = 80 pips** |
| **Evidence** | PHASE_2_ISSUES U9; `defect_observations.json` `U9_h1_atr_gate_units`, which records **0 occurrences** on this dataset |
| **Classification** | **A**, currently with **E** consequences — the defect is real, its effect on this dataset is nil |
| **Alters production?** | **No on this dataset** (0 firings). **Yes on a dataset at a different price level** — the threshold is absolute USD, so its selectivity tracks gold's price |
| **Historical intent** | **Established that the label is wrong** (it says pips, the value is dollars). Not established what threshold was intended |
| **Mechanical or strategy?** | **Mechanical** (unit mislabel) wrapping a **strategy** quantity (the threshold itself) |
| **Evidence required first** | Whether the intended unit was pips. If so the correct value is 0.8, a 10× change |
| **Phase 8 experiment** | None needed to characterise. Any repair is a controlled change measured against baseline_006 |
| **Defer?** | **No** — but note it changes nothing measurable here, so it cannot be validated by this dataset |

### Stage 0 update (2026-09-29) — quantified; the repair is unfalsifiable here

**Unit analysis, from source.** `h1_atr = mean(high − low)` over 14 H1 bars
(`main_production.py:675-676`). `high` and `low` are XAUUSD prices in **quote
currency**, so the statistic is **dollar-denominated**. With `pip_size = 0.10`,
the literal `8.0` represents **$8.00 — 80 pips**, while the message at line 737
formats it as `"< 8.0 pips"`. The gate blocks at **L2_STRUCTURE**, not L1.

**Read-only computation over the frozen H1 frame**, the exact production
quantity (rolling 14-bar mean of `high − low`):

```
bars 1,667   min 10.9029   p01 11.5888   median 18.7579   max 39.8286
count < 8.0 : 0     <- the gate as written
count < 0.8 : 0     <- the gate if the literal meant pips
price range : 3942.48 - 4696.73
```

**This dataset cannot distinguish the two interpretations.** Both fire **zero**
times. Corroborated twice: `defect_observations.json` records `occurrences: 0`,
and all 12 L2 blocks in `baseline_006` carry *"HN structure is broken"* — none
carries *"H1 ATR too calm"*.

**Consequence for experimentation: any repair is currently unfalsifiable.** A
replay after the change produces a null diff *whichever unit is chosen*. **A null
replay here is not a validation and must never be recorded as one.** Validating a
repair needs a dataset whose 14-bar H1 range falls below the threshold under at
least one reading.

## P8-08 — Q6 / U1: `$3.00` stop buffer

| Field | |
|---|---|
| **Current behaviour** | `_select_stop_anchor` subtracts `buffer_pips = 3.0` directly from a price, producing a **$3.00** buffer where the name implies 3 pips ($0.30) |
| **Evidence** | PHASE_2_ISSUES U1 (P0); `defect_observations.json` `Q6_stop_buffer_units`, 4 occurrences; confirmed by inspection in Phase 2A.1 (sweep wick 2511.73 → stop 2508.73) |
| **Classification** | ~~**A**~~ **B — strategy-contract question. RECLASSIFIED; see the characterization update below** |
| **Alters production?** | ~~**Yes.** It changes `risk_distance` … hence `rr`, hence — via P8-06's equality boundaries — potentially admission itself~~ **FACTUALLY INCORRECT — the buffer cannot move `rr` and cannot reach admission. Corrected in the update below** |
| **Historical intent** | **Established that name and behaviour disagree.** Not established which was intended |
| **Mechanical or strategy?** | ~~**Mechanical**~~ **Strategy — the inconsistency is mechanical, but no uniquely justified correction exists** |
| **Evidence required first** | Owner decision on the intended buffer, **and the anchor contract (P8-18)**. PHASE_4B_FIX_DECISION_MATRIX M6 warns: **rename and convert as one change** |
| **Phase 8 experiment** | ~~Controlled change, single variable, replay, compare~~ **NONE APPROVED. `3.0 -> 0.30` is explicitly NOT approved; see the update below** |
| **Defer?** | ~~**No**~~ **Yes — deferred behind an owner decision and P8-18** |

### P8-08 characterization update (2026-09-29) — reclassified A -> B

> ## NO EXPERIMENT APPROVED / NONE RUN
>
> No production code was changed, no replay was run and no test suite was run for
> P8-08. This block records read-only characterization only.

**Starting state:** HEAD `e857e37e50907f5da3c1d3b856808c1da2acdae9`, reference
baseline `baselines/baseline_007`.

#### Evidence classes used below

**OBSERVED** — read directly from `baseline_007` artifacts or from source.
**PROJECTION** — arithmetic on recorded values; **not** a replay measurement.
**INFERENCE** — interpretation, including later-auditor wording.

#### The code path — OBSERVED

`entry_engine.py:373-389`, `_select_stop_anchor`, `buffer_pips: float = 3.0`:
`min(candidates) - buffer_pips` for BUY, `max(candidates) + buffer_pips` for
SELL. `3.0` is applied to a **price**, so on XAUUSD (`pip_size = 0.10`) the
buffer is **$3.00 = 30 pips**, where the name says 3 pips. One caller,
`entry_engine.py:404` inside `calculate_entry_levels`; `buffer_pips` is **never
passed** anywhere in the repository, so the default always applies.

**History — OBSERVED.** `git log -S"buffer_pips"` returns exactly one production
commit, `c3cf4df` (2026-07-01). The arithmetic is **byte-identical from creation
to HEAD**. No commit ever changed, annotated or debated the value or its units.

#### Blast radius — the previous row was factually incorrect

**OBSERVED, by tracing every consumer.** The buffer **cannot** change:

- any **L1-L8 layer verdict**;
- **side** or **regime**;
- **POI / setup / candidate selection**;
- **signal generation**;
- the **entry price**;
- **RR admission**.

Because:

- `entry_triggered` is `bool(core_trigger)` / `bool(raw_triggered)` — price-pattern
  conditions only, with no geometry term;
- `trigger_quality` is composed from displacement, FVG, momentum and CHoCH
  qualities plus kill-zone and rejection — **no dependence on stop or risk**;
- `reward_distance = risk_distance * tp_ratio`, so
  **`rr = reward_distance / risk_distance` is identically `tp_ratio`** for any
  non-zero risk (P8-03). The buffer is therefore **invisible** to the RR gate and
  to P8-06's equality boundary;
- `_score_entry_candidate` reads only quality, `rr` and style — all invariant.

> **The superseded row claimed the buffer reaches `rr` and "potentially admission
> itself" via P8-06. That is wrong and is retracted here.**

**The actual direct blast radius:**

| Affected | |
|---|---|
| `stop_loss` | stop geometry |
| `risk_distance` | risk geometry |
| `take_profit`, `reward_distance` | target / reward geometry |
| Simulated trade outcomes | via the geometry above |
| `reasoning` string | diagnostic / reason text |

#### baseline_007 exposure — OBSERVED

**1,589** decisions reach L8 and compute entry levels (1,585 blocked at L8, 4
signals). **Anchor-path usage per decision is NOT recorded** —
`defect_observations.json` Q6 states this explicitly: the decision snapshot
carries no sweep-wick level. Three of the four trades provably used the anchor
path (stop offset below the 8.0 MOMENTUM fallback floor); the fourth is
consistent with it. `_select_stop_anchor` is regime-independent.

#### Why `3.0 -> 0.30` is NOT an approved experiment

**PROJECTION** — arithmetic on `baseline_007`'s recorded values, not a replay.
Applying the arithmetically obvious unit correction to the four trades:

| # | Side | Strategy entry | Stop @ $0.30 | Stop side vs entry |
|---|---|---|---|---|
| 1 | SELL | 3983.725 | 3983.390 | **WRONG SIDE** |
| 2 | BUY | 4257.775 | 4257.810 | **WRONG SIDE** |
| 3 | BUY | 4413.235 | 4413.150 | correct; risk 2.785 -> 0.085 |
| 4 | SELL | 4607.795 | 4613.630 | correct; risk 8.535 -> 5.835 |

Measured against the **fill** price, which is what
`execution/paper_broker.py:186,198` validates, one of the four would be
**rejected** (*"stop … is at or below the SELL fill"*), and surviving risk
distances collapse from 2.565 / 2.865 / 2.985 / 8.735 to 0.135 / 0.165 / 0.285 /
6.035.

**In two of four observed cases the anchor already sits on the wrong side of the
entry, and the oversized $3.00 buffer is the only thing pushing the stop back to
the correct side.** The buffer is masking a separate latent defect —
`PHASE_2_ISSUES` **E11**, *"No check that the stop is on the correct side of
entry."*

So the unit correction does not repair a clean bug; it **exposes E11** on half the
observed population. It is therefore **NOT APPROVED**, on four grounds:

1. it produces wrong-side stops in observed cases;
2. it exposes the separate E11 geometry issue;
3. the correct anchor contract is unresolved;
4. **P8-18** is relevant to resolving that contract.

#### Dependency on P8-18 — explicit

> **P8-08 is BLOCKED behind P8-18.** The live question is not which unit the
> buffer meant, but **what the stop should be anchored to when the MOMENTUM entry
> price is the FVG midpoint** rather than a bar close. Until that contract is
> settled, any buffer value is arbitrary. An explicit stop-side check (E11) would
> also need to exist before a buffer change could be evaluated cleanly, since it
> would turn the currently-masked cases into visible rejections.

#### Historical intent — preserved, UNRESOLVED

- The parameter name says **`buffer_pips`**.
- The current arithmetic treats `3.0` as **price units**.
- **No original-author evidence establishes which interpretation was intended.**
  The `c3cf4df` docstring (*"Pick the most defensive structure-based stop
  anchor."*) states no units. `core/units.py`'s wording *"where 3 pips was
  intended"* is **INFERENCE** — it was written by this rebuild in Phase 1, not by
  the original author, and treating it as attested intent would be circular.
- Whether `3.0` was chosen knowing it behaved as $3.00 is **unknown**, the same
  shape as P8-10's open `1.2` question.

#### Test coverage — OBSERVED

`test_baseline_defects.TestStopBufferIsAppliedInPriceUnits::test_buffer_is_three_price_units_not_three_pips`
is a **genuine behavioural pin** of current behaviour (2511.73 -> 2508.73); any
correction fails it by design. Its sibling `test_default_is_still_three` checks
only the signature default and is **partially ineffective** — a correction
written as `- buffer_pips * pip_size` keeps the default at `3.0` and slips past
it, the same failure mode as the two P8-15 pins. `tests/core/test_units.py` tests
the units library and pins nothing in production.

#### Why B rather than A

A mechanical defect has a determinable right answer. This one does not: the
intended unit is unrecoverable, and the arithmetically obvious correction
produces a different defect. **Reclassified B — strategy-contract question.**

## P8-09 — L3 is one M15 bar stale under replay

| Field | |
|---|---|
| **Current behaviour** | `pullback_detector` drops the last bar (`recent.iloc[:-1]`) to avoid a forming candle. Under replay the feed already supplies only closed bars, so the drop removes a bar that is not there |
| **Evidence** | Phase 6O-B L3-D6; PHASE_2_ISSUES B5 (*"double-drop"*) |
| **Classification** | **A** — a live/replay divergence |
| **Alters production?** | **Yes in replay** (L3 sees a different window). **No in live**, where the drop is correct. This is the important asymmetry: fixing it makes replay and live *agree*, which changes replay results |
| **Historical intent** | **Established** — the drop is deliberate and correct for live. The defect is that replay does not need it |
| **Mechanical or strategy?** | **Mechanical** |
| **Evidence required first** | Confirmation that `ReplayFeed` supplies only closed bars at every timeframe L3 touches. Partly established by the no-look-ahead invariant work |
| **Phase 8 experiment** | Controlled change, replay, compare. **Expect a large diff** — it shifts L3's entire input window, and L3 blocks 5,066 decisions |
| **Defer?** | **No** — but it is a big-diff change and should be run alone |

## P8-10 — L3 momentum-fallback cap compares pips to dollars

| Field | |
|---|---|
| **Current behaviour** | REGIME_SCALP's momentum fallback applies a distance cap that mixes pip and dollar units, making it ~10× too tight |
| **Evidence** | ~~Phase 6O-B L3-D7: 196 decisions reached it; **≤21 would flip**~~ **STALE — measured before D-6N-1 and D-6OF-2B; see the pre-experiment update below** |
| **Classification** | **A** |
| **Alters production?** | **Yes, bounded** — ~~≤21 decisions~~ **22 decisions at HEAD; see the pre-experiment update** |
| **Historical intent** | **NOT established** which unit was intended |
| **Mechanical or strategy?** | **Mechanical** |
| **Evidence required first** | Owner decision on the intended unit, same family as P8-07/P8-08 |
| **Phase 8 experiment** | Controlled change, replay, compare against the pre-declared ~~≤21~~ **22**. Scope and criteria specified in the pre-experiment update |
| **Defer?** | **No** |

### P8-10 pre-experiment update (2026-09-29) — measured at HEAD

> ## EXPERIMENT NOT YET APPROVED / NOT YET RUN
>
> No production code has been changed and no replay has been run for P8-10. This
> block records characterisation and a *proposed* experiment only.

**Starting state:** HEAD `8f16d8faaf14d3a02340596ef12dfc9bfa484219`, comparison
baseline `baselines/baseline_006`, dataset SHA
`433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c`.

#### The dimensional finding

`_check_regime_scalp_momentum` check 4 (`main_production.py`) compares:

```
distance_pips    = abs(last_close - break_reference) / pip_size   -> PIPS
max_allowed_pips = 1.2 * m5_atr                                   -> DOLLARS
```

`break_reference` is a swing price and `m5_atr` resolves through
`_atr_from_frame` to `atr_14`, a price-based ATR, so both are quote-currency
dollars. The left side is correctly converted to pips; the right side is not.
Rejection therefore occurs at `10·D > 1.2·A` rather than `D > 1.2·A` — **10×
tighter than a same-unit 1.2×ATR comparison.**

This is a statement about **dimensions only**. It is **not** a claim about what
the author intended — see the unresolved questions below.

#### Measured on baseline_006 — no replay used

Read directly from `decisions.jsonl`, which stores each decision's verbatim
`reason`, and check 4's message embeds both operands.

| Quantity | Measured at HEAD |
|---|---|
| Decisions reaching check 4 | **201** |
| Currently **rejected** by check 4 | **195** |
| Currently **pass** the momentum fallback | **6** |
| Would pass under the proposed unit correction | **22** |

All 195 are REGIME_SCALP (102 BUY / 93 SELL), as expected — the caller is
regime-gated. Rounding sensitivity is minimal: the counts derive from the
message's one-decimal values, and only **one** decision sits within 2% of the
corrected boundary (ratio 1.0093, still rejected), so the figure is stable to
±1. Median ratio is 2.86, i.e. typical rejections exceed even the corrected cap
by roughly 2.9×.

#### Why the old figure is stale

> **The `≤21` bound is no longer the correct pre-declared blast radius at HEAD.**
> It comes from Phase 6O-B, measured **before** D-6N-1 (which changed the regime
> population) and D-6OF-2B (which changed L3's direction input). The original
> statement is preserved above, struck through, because it remains the correct
> record of what was measured then. Running the experiment against `≤21` would
> trip its own blocker on a correct result.

#### The proposed one-line experiment

```
OLD:  max_allowed_pips = 1.2 * m5_atr
NEW:  max_allowed_pips = 1.2 * m5_atr / pip_size
```

One line, in `_check_regime_scalp_momentum` check 4. It makes both sides of the
comparison pips and makes the variable's name true. The `1.2` multiplier, the
ATR source, the message format and checks 1-3 are untouched.

**Pre-declared blast radius: exactly 22 pre-identified decisions change at L3**,
all REGIME_SCALP, each moving from blocked at `L3_PULLBACK` to passed via
`L3_PULLBACK_MOMENTUM`.

> **Downstream behaviour is NOT predictable in advance and must not be
> pre-declared.** For context only, and explicitly not a prediction: of the 6
> decisions that currently pass this fallback, 4 terminate at L4 and 2 at L5 —
> none has reached L6, L7 or L8 — and newly-admitted decisions additionally meet
> L7's `momentum_fallback` threshold of 75 and its A+ grade demotion.

#### Acceptance / rejection criteria

**Accept:** exactly the 22 pre-identified timestamps change at L3, plus whatever
downstream consequences those 22 produce.

**Reject / BLOCKER — stop and characterise, do not repair:**

- any decision outside the 22 changes;
- any MICRO_SCALP, INTRADAY_SWING or DEAD_CALM decision changes;
- any change to L1, L2, regime or side.

> **Signal count, P&L, win rate, profit factor and drawdown are OBSERVATIONS
> ONLY. They are not acceptance criteria and may not be used to accept, reject
> or tune this change.**

#### Test coverage

**There is currently no behavioural test asserting the P8-10 cap.** Nothing pins
the obsolete 10×-tight behaviour either, so unlike P8-15 there is nothing to
invert. Any future test should assert the **unit contract behaviourally** — the
boundary in both units through the production path — **not** by
implementation/source-text matching, which is the P8-15 lesson.

Noted in passing, not a task: `test_l3_direction_contract.test_scalp_1_is_unchanged`
does **not** cover this cap despite its name; it asserts two unrelated source
strings.

#### Unresolved — preserved, not resolved here

1. **The intended unit is not historically established.** The code is
   dimensionally inconsistent; repository evidence does not establish whether
   pips or dollars was intended. The proposed correction assumes the docstring
   (*"still within 1.2x M5 ATR of the structural break level"*) states the
   intent, which is an inference from prose, not attested intent. Same family as
   P8-07 and P8-08.
2. **Whether the `1.2` multiplier was itself calibrated against the accidentally
   tighter implementation** is unknown. If it was, correcting the units silently
   changes what `1.2` meant. No evidence either way; no speculation offered.

**Consequence:** the proposed experiment is **mechanically motivated, but
carries a bounded strategy-contract uncertainty.**


## P8-11 — `MIN_PULLBACK_QUALITY = 1.5` is inert

| Field | |
|---|---|
| **Current behaviour** | Reaching the comparison requires `pullback_detected`, which requires the accepted band, which floors base quality at 4.0 with only non-negative bonuses. So `quality < 1.5` cannot occur |
| **Evidence** | D-6OF-2G; Phase 6O-B L3-D5 measured **0 firings in 15,735**. Pinned by `tests/backtest/test_l3_quality_invariant.py` (D-6OF-2H) |
| **Classification** | **D** |
| **Alters production?** | **No.** Removing it changes 0 decisions — provable without replay |
| **Historical intent** | **Established.** It was the operative threshold at `c3cf4df` and was rendered inert by the gate change at `4c90b81`. Retained for traceability |
| **Mechanical or strategy?** | Neither — residue |
| **Evidence required first** | None |
| **Phase 8 experiment** | **None.** Nothing to test |
| **Defer?** | **Yes, indefinitely.** Annotated (D-6OF-2H) and pinned. Deletion would lose history for zero gain |

## P8-12 — `tp_ratio = 3.0` defaults unreachable

| Field | |
|---|---|
| **Current behaviour** | Four function signatures default `tp_ratio = 3.0`, and `main_production` uses `regime_info.get("tp_ratio", 3.0)`. `detect_regime` sets the key on both its normal and exception paths, so no default is reachable |
| **Evidence** | U9-RR §5. Residue of the former `rr_ratio = 3.0`, which *was* the operative universal multiplier at `c3cf4df` |
| **Classification** | **D** |
| **Alters production?** | **No** |
| **Historical intent** | **Established** — it is the fossil of the pre-`4c90b81` design |
| **Mechanical or strategy?** | Neither — residue |
| **Evidence required first** | None |
| **Phase 8 experiment** | **None** |
| **Defer?** | **Yes.** A misleading-default annotation is the appropriate treatment, not removal |

## P8-13 — `rr_bonus` cancels in candidate selection

| Field | |
|---|---|
| **Current behaviour** | `_score_entry_candidate` adds `min(rr, 4.0) × 1.5`. Both candidates in a decision are evaluated at the same `regime_tp_ratio`, so the bonus is identical and cancels in `max()` |
| **Evidence** | U9-RR §5, by the same argument `8c5724c` made when removing `valid_bonus`. **One exception:** a degenerate `risk_distance == 0` candidate scores `rr = 0` and would not cancel |
| **Classification** | **D**, with a narrow **A** edge case |
| **Alters production?** | **No** in the general case. The zero-risk edge case is **UNMEASURED** |
| **Historical intent** | **Not established.** It looks like an intent to prefer higher RR, which the construction defeats |
| **Mechanical or strategy?** | Residue, with a mechanical edge |
| **Evidence required first** | Count of candidates with `risk_distance == 0` in the frozen stream |
| **Phase 8 experiment** | ~~Read-only count — **no replay needed**~~ **SUPERSEDED — not obtainable from the artifacts; see Stage 0 update** |
| **Defer?** | **Yes** for removal; **no** for the count |

### Stage 0 update (2026-09-29) — cancellation confirmed; the count is NOT available

**Cancellation confirmed, by two independent routes.**

1. **`rr ≡ tp_ratio` for both candidates.** They are evaluated at the same
   `regime_tp_ratio`, so `rr_bonus` is identical and cancels in `max()` — the
   argument `8c5724c` used when removing `valid_bonus`.
2. **Most decisions have only one candidate.** `get_entry_trigger` restricts
   `allowed_styles` to MOMENTUM for MICRO_SCALP and PULLBACK for INTRADAY_SWING,
   so `max()` is identity and every bonus is irrelevant. That covers **9,124 of
   15,735** decisions. Only REGIME_SCALP compares two candidates in practice
   (DEFAULT is unreachable — see P8-04's update).

**The zero-risk edge case stands, unmeasured.** A candidate with
`risk_distance == 0`, or one returned by `calculate_entry_levels`' exception
path, scores `rr = 0.0`, so its bonus is 0 against the other's 2.25 and **does**
discriminate — against the degenerate candidate, which is arguably correct by
accident. Since `entry_triggered` is now `raw_triggered` alone, such a candidate
can reach the comparison.

> **The count of such candidates is NOT available from `baseline_006`
> artifacts.** `decisions.jsonl` carries eight fields and `risk_distance` is not
> among them; it is persisted only for the four filled trades in
> `trade_ledger.json`. The original row called this a read-only count. **That was
> wrong.** **No replay was run to obtain it.**

**Also recorded, not previously in this ledger:** `style_bonus` (0.5 for
PULLBACK) does **not** cancel — it is a live tiebreak whenever both candidates
are valid and quality ties. Current behaviour, not a defect.

**Treatment unchanged: documentation only.** Annotate, do not remove; belongs in
a cleanup-only commit with P8-11 and P8-12.

## P8-14 — G2 / U10-B: absolute vs relative ATR bands

| Field | |
|---|---|
| **Current behaviour** | `detect_regime` classifies on absolute-USD M5 ATR bands 2.5 / 4.5 / 7.0 |
| **Evidence** | `defect_observations.json` `G2_U10_absolute_regime_bands`: *"Regime selection on this dataset is a function of gold's price level during the period, not of relative volatility."* U10-A (units) was RESOLVED; **U10-B (absolute vs relative) was not** |
| **Classification** | **B**, with a testable **C** component |
| **Alters production?** | **Yes, very substantially.** Regime governs `tp_ratio`, risk, L3/L6 bypass, POI threshold and spread cap. D-6N-1 already showed how far a regime change propagates |
| **Historical intent** | **NOT established.** No artefact states whether bands were meant to be absolute or ATR-relative |
| **Mechanical or strategy?** | **Strategy choice**, but the *observation* that classification tracks price level is mechanical and proven |
| **Evidence required first** | Owner decision on whether regime means absolute volatility or relative. Then: does the dataset span enough price range to distinguish them? Gold moved ~3,900 → ~4,600 in this period, so the bands are not scale-stable across it |
| **Phase 8 experiment** | **Candidate.** Express bands as a fraction of price or of a longer-horizon ATR, replay, compare. **Must change one definition only**; do not also retune the boundary values, or the result is uninterpretable |
| **Defer?** | **No**, but it is the widest-blast-radius item here and must be run in isolation |

## P8-15 — `bias` / `bias_strength` not reassigned on the L2 flip

| Field | |
|---|---|
| **Current behaviour** | The BOS flip reverses `side` but leaves `bias` and `bias_strength` at their pre-flip values. `analysis["layer_1"]` and L7's `bias_strength` therefore carry the abandoned direction's numbers on every reversal |
| **Evidence** | D-6OF-2 models 2/3; 1,845 reversals at HEAD over ~157 distinct H1 states. D-6OF-2A fixed `position_type`; D-6OF-2B rebound L3 to the effective side; **these two remain open** |
| **Classification** | **A** for `bias` (a stale label the flip documents itself as changing); **B** for `bias_strength` (whether a flipped setup inherits the old conviction score is a contract question) |
| **Alters production?** | **`bias`: no** — it is reporting-only after D-6OF-2B. **`bias_strength`: yes** — L7 consumes it, and L7 blocks 1,825 decisions |
| **Historical intent** | **Established for `bias`**: `architecture.txt` 760-761 documents the flip as *"flip[s] bias"*. **Not established for `bias_strength`** |
| **Mechanical or strategy?** | Mixed — see above |
| **Evidence required first** | For `bias`: none, the doc states it. For `bias_strength`: an owner decision on what conviction a reversed setup should carry |
| **Phase 8 experiment** | Split them. `bias` reassignment is a zero-decision-change repair (verify by replay). `bias_strength` is a contract change requiring a pre-declared expectation, as D-6OF-2B did |
| **Defer?** | **No** for `bias`; **yes** for `bias_strength` |

## P8-16 — SCALP-1 check-4

| Field | |
|---|---|
| **Current behaviour** | REGIME_SCALP's momentum substitution path contains a broken check-4; separately, it does not extend to the 190 INTRADAY_SWING reversals |
| **Evidence** | D-6OB-2; D-6OF-2 deferral list |
| **Classification** | **A** for the broken check; **B** for whether it should extend to INTRADAY_SWING |
| **Alters production?** | **UNMEASURED** for the repair. **Yes** for the extension (190 decisions in scope) |
| **Historical intent** | **Not established** that the substitution was meant to be REGIME_SCALP-only |
| **Mechanical or strategy?** | Mixed |
| **Evidence required first** | A unit-level characterisation of what check-4 currently evaluates versus what its name implies. **D-6OB-2 explicitly warned against using the broken check-4 as evidence for anything** |
| **Phase 8 experiment** | Repair first, measure, then treat the extension as a separate contract question |
| **Defer?** | **No** for the repair; **yes** for the extension |

## P8-17 — Q1 / Q2: reported RR versus realised R

| Field | |
|---|---|
| **Current behaviour** | Risk is priced against a strategy entry price the trade is never filled at, so realised R differs from reported RR on every trade |
| **Evidence** | `defect_observations.json` `Q1_Q2_rr_vs_realised_r`, 4 occurrences, all four with `strategy_rr_ratio = 1.5` against realised R of −1.08, −0.61, +3.30, +1.48 |
| **Classification** | **E** currently — it is a measurement-validity statement, not a behaviour to change |
| **Alters production?** | **No** as an observation. Changing *how entry is priced* would, and that is P8-18 |
| **Historical intent** | **Established** that RR is reported, not judged (`entry_engine.py:433-435` says so in source) |
| **Mechanical or strategy?** | Neither — it is a caveat on interpreting the artefacts |
| **Evidence required first** | None |
| **Phase 8 experiment** | **None.** Its role is to prevent anyone using reported RR as an outcome measure in Phase 8 |
| **Defer?** | **N/A — standing caveat** |

## P8-18 — Entry priced off a stale bar (B3 / B4)

| Field | |
|---|---|
| **Current behaviour** | `_evaluate_pullback_entry` uses `iloc[-2]["close"]` as the entry price, and `main_production`'s `confirmed_m5_close` passes a stale close into L8 as `current_price` |
| **Evidence** | PHASE_2_ISSUES B3, B4 — both **P0**. Corroborated by baseline_006's ledger: every trade's `strategy_entry_price` differs from its actual fill (e.g. 3983.725 vs 3983.525) |
| **Classification** | **A** |
| **Alters production?** | **Yes** — it changes the price every downstream geometry calculation is anchored to |
| **Historical intent** | **Not established.** Consistent with B1/B2's staleness, inconsistent with B6 in the same pass |
| **Mechanical or strategy?** | **Mechanical** |
| **Evidence required first** | Whether the replay feed's "current price" is already the correct decision-time price, making the `-2` index a double-drop as in P8-09 |
| **Phase 8 experiment** | ~~Characterise first (read-only)~~ — **DONE in Stage 0**, then a controlled change |
| **Defer?** | **No** — it is upstream of P8-06 and P8-08, and should be understood before either is repaired |

### Stage 0 update (2026-09-29) — one row, two findings

The original row treated this as a single issue. **It is two, with different
classifications.** Neither is lookahead.

**A. Replay/live staleness — a data-window mismatch, NOT lookahead.**
`main_production.py:1007` computes
`confirmed_m5_close = m5_data.iloc[-2]["close"]` and passes it as
`current_price`. Under replay, `ReplayFeed.bars` returns *"the last `count` bars
closed at or before `as_of`"* — enforced by `_visible_count`, protected by a
deliberate `.copy()` so the strategy cannot hold a view onto later rows, and
directly tested by `test_no_returned_bar_has_closed_after_as_of`. So `iloc[-1]`
is **already** the last closed bar and `iloc[-2]` is **one bar older than
necessary**. Live, `get_market_data` may return a forming last bar, where
`iloc[-2]` is correct. **Replay therefore looks further into the past, never into
the future** — the same double-drop family as P8-09.

**B. Execution geometry — declared modelling, not a defect by itself.**
All four baseline trades are MOMENTUM, and that path does not use a bar close as
its entry price: `entry_engine.py:598-600` sets
`confirmed_entry_price = fvg["midpoint"]`, which becomes the resting limit price
(`pending_statistics.json` shows `limit_price` equal to `strategy_entry_price`).

| Side | Strategy entry | Fill | Diff | SL re-anchored? | TP re-anchored? |
|---|---|---|---|---|---|
| SELL | 3983.7250 | 3983.5250 | **−0.2000** | No | **Yes** |
| BUY | 4257.7750 | 4257.9750 | **+0.2000** | No | **Yes** |
| BUY | 4413.2350 | 4413.4350 | **+0.2000** | No | **Yes** |
| SELL | 4607.7950 | 4607.5950 | **−0.2000** | No | **Yes** |

Every difference is **exactly ±$0.20 = the declared 2.0-pip spread**, always
direction-adverse, with nothing else contributing. That is the
`spread_pips: 2.0` assumption behaving correctly.

**The asymmetry is the finding:** the **stop stays anchored to the strategy
entry** while the **target is re-anchored to the fill** (commit `97363c7`).
Intended risk and the realised-R denominator therefore differ — 2.365 against
2.565 on trade 1, about 8.5%.

> **`baseline_006` contains only MOMENTUM trades and therefore does NOT
> characterize the pullback / B3 path** — the path that actually prices off
> `m5[-2]` and then `m1[-2]`. Zero baseline trades exercise it.

**Downstream reach, corrected 2026-09-29.**

> ~~`strategy_entry_price` → `risk_distance` → `take_profit` → `reward_distance`
> → `rr` → the L8 RR gate, so it anchors the very boundary P8-06 describes.~~
> **RETRACTED — the final step is false.** This is the same error retracted for
> P8-08 in `f940c59`.

**The factual relationship.** `strategy_entry_price` does reach `risk_distance`,
`take_profit` and `reward_distance`, and it reaches **execution validation** —
`execution/paper_broker.py` compares the stop against the fill. But
`reward_distance = risk_distance * tp_ratio`, so
**`rr = reward_distance / risk_distance` is identically `tp_ratio`** for any
non-zero risk. `rr` is therefore invariant to the entry price and to the stop.

> **P8-18 cannot affect P8-06 admission through RR.** Nor can it change any other
> L1–L8 verdict: `entry_triggered` is a price-pattern condition and
> `trigger_quality` is composed from component qualities, neither carrying a
> geometry term.

**Actual direct blast radius:** stop geometry, `risk_distance`, target/reward
geometry, execution validation (stop-vs-fill), simulated trade outcomes, and
diagnostic reason text. **Remains a candidate for controlled research later.**

## P8-19 — S1: the Fibonacci POI repaints

| Field | |
|---|---|
| **Current behaviour** | The "Fibonacci 0.618" POI is built from a rolling `tail(20)` high/low, so the zone repaints every M15 bar. It is generated unconditionally and ~~frequently becomes `best_poi`~~ **(frequency claim SUPERSEDED — unmeasured; see Stage 0 update)** |
| **Evidence** | PHASE_2_ISSUES S1 (**P0**) |
| **Classification** | **A** |
| **Alters production?** | **UNMEASURED.** L6 blocks only 1 decision in baseline_006, but POI *scoring* feeds L7, which blocks 1,825 |
| **Historical intent** | **Not established** |
| **Mechanical or strategy?** | **Mechanical** — a repainting level is not a level |
| **Evidence required first** | How often the Fib POI is selected as `best_poi`, and what it contributes to L7 scores. ~~Read-only~~ **SUPERSEDED — not in the artifacts; see Stage 0 update** |
| **Phase 8 experiment** | Characterise first; repair is a separate controlled change |
| **Defer?** | **No** for characterisation |

### Stage 0 update (2026-09-29) — repainting confirmed, leakage excluded, reach wider

**Repainting: CONFIRMED.** `poi_engine.py:643-666` builds the zone from
`m15_data.tail(20)` high/low. Each new M15 bar slides the window, so the level
recomputes every bar. It is **not a fixed structural level**.

**Future-data leakage: EXCLUDED.** The frame is already truncated at `as_of` by
the replay feed's tested invariant (see P8-18's update). The computation can
never see a bar that has not closed.

> **Classification: retrospective signal instability / repainting — NOT
> future-data leakage.**

**`is_untested` is circular**, new to this ledger:
`_zone_touched(m15_data, fib_top, fib_bottom, fib_idx)` with
`fib_idx = len(m15_data) - 20` scans bars *after* that index — the same 20 bars
that defined the high and low. The 0.618 level of a range has almost always been
traded through within that range, so the flag is structurally biased to `False`.

**Downstream reach is broader than previously documented.** `identify_poi` runs
unconditionally at `main_production.py:934`, `best_poi` is assigned **before** the
`bypass_l6` check, and it reaches L7 as `poi_score` at `main_production.py:972`.

- **L6** consumes it but blocks only **1** decision in `baseline_006`.
- **L7** consumes it and blocks **1,825**.
- **The L6 bypass does not insulate MICRO_SCALP.** All 7,314 MICRO_SCALP
  decisions — including all four signals, whose `passed` lists show
  `L6_POI_BYPASSED` — still feed `best_poi["score"]` into L7.

The original row implied the bypass limited exposure. **It does not.**

> **No frequency is claimed.** How often the Fibonacci POI wins the sort, and what
> it contributes to L7 scores, **cannot be measured from `baseline_006`
> artifacts**: `decisions.jsonl` has no POI fields and `layer_funnel.json` records
> only the single L6 block. Answering it requires re-executing `identify_poi`
> across the decision stream — a partial replay. **No replay was run.**

**P8-19 is therefore BLOCKED from experimentation** until that measurement is
separately authorised.

## P8-20 — Ambiguous exits under the conservative intrabar policy

| Field | |
|---|---|
| **Current behaviour** | 1 of 4 trades in baseline_006 resolved by policy rather than from observed sequence, because M5 bars cannot order a same-bar stop and target |
| **Evidence** | baseline_006 `exit_statistics.json`; `metrics.json` `ambiguous_exit_fraction: 0.25` |
| **Classification** | **E** — an assumption, correctly declared, not a defect |
| **Alters production?** | **No.** It affects outcome attribution, not the decision stream |
| **Historical intent** | **Established** — the policy is declared in `execution_assumptions` |
| **Mechanical or strategy?** | Neither — a simulation assumption |
| **Evidence required first** | M1 data could disambiguate. The dataset has M1 |
| **Phase 8 experiment** | Optional: re-resolve ambiguous exits at M1 resolution. This changes **outcome measurement only**, never the decision stream, and must be reported as such |
| **Defer?** | **No**, but note that with 4 trades it moves a statistic that carries no inferential weight either way |

---

# 2. Carried from `PHASE_2_ISSUES.md`, not individually characterised

The following are in the broader defect ledger, touch the **decision path**, and
therefore belong in Phase 8 scope — but none has been characterised to the
standard above. **Listing them is not scheduling them.**

| ID | Item | Class (provisional) |
|---|---|---|
| U2, U3, U4 | Liquidity scoring/penalty distances declared in pips, applied as dollars | A |
| U5, U6, U7 | POI zone-size, displacement and body thresholds, same unit family | A |
| U8 | `sweep_min = max(2.5, atr×0.12)` — $2.50 minimum sweep (**P0**) | A |
| U11, U12 | Hardcoded `pip_size = 0.10` duplicating broker data | A |
| B1, B2, B6 | Staleness inconsistency within one pass | A |
| E11 | ~~No check that the stop is on the correct side of entry~~ **CORRECTED 2026-09-30 — see the E11 scope note below** | A |
| E12 | Entry never accounts for spread or slippage; `MAX_SLIPPAGE_PIPS` defined, never referenced | A |

**Explicitly out of Phase 8 research scope:** R1–R9 (risk/sizing), E1–E8
(execution/broker), E3/E4 (exit logic), and everything behind
`LIVE_TRADING_ENABLED`. These do not affect the frozen replay's decision stream —
the baseline uses fixed 0.01 lots and does not size — and several are unreachable
by design. They remain P0 in their own ledger and must be resolved before any
question of live operation arises. **Phase 8 is decision-path research only.**

---

# 2.1 Stop-anchor contract — decision record (2026-09-29)

> ## DECISION POINT — NOT A DECISION
>
> This section records an **unresolved strategy contract** and the evidence
> bearing on it. It selects nothing, proposes no parameter value, and is not
> permission to change any code.

**Reference:** HEAD `363a9219df50585912b47abd2d9239940a9301e7`, population
`baselines/baseline_007`, dataset
`433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c`. All figures
below come from a **read-only recomputation** over the 1,589 L8-reaching
decisions — the production functions were imported unmodified, nothing was
written to the repository, and no replay or experiment was run.

---

## Proven

**OBSERVED — source.** `_select_stop_anchor` never receives the entry price. It
returns `min(candidates) - buffer` for BUY and `max(candidates) + buffer` for
SELL, selecting by extremeness alone. Candidates are the sweep wick and, on
MOMENTUM only, `displacement.origin_low/high`. PULLBACK is passed **no**
`structure_*` at all.

**OBSERVED — geometry.** Under the current `detect_fvg` construction,
`displacement.origin_*` **is** the near FVG edge: for BUY `origin_low = m5[-1].low
= gap_high`; for SELL `origin_high = m5[-1].high = gap_low`. A midpoint entry
therefore always lies on the far side of it.

**MEASURED — the whole L8 population (1,589):**

| Population | n | Displacement candidate wrong-side | **Selected** anchor wrong-side | Buffered stop wrong-side |
|---|---|---|---|---|
| MOMENTUM, all | 1,525 | 150 (9.8 %) | **25 (1.6 %)** | **1 (0.1 %)** |
| └ FVG present → entry = **midpoint** | **139** | **139 (100.0 %)** | **24 (17.3 %)** | **1 (0.7 %)** |
| └ no FVG → entry = `m5[-1].close` | 1,386 | 11 (0.8 %) | 1 (0.1 %) | 0 |
| PULLBACK | 267 | n/a — no structural anchor | **0 (0.0 %)** | **0 (0.0 %)** |

- Selected anchor source, MOMENTUM: **sweep wick 1,393 / 1,525 (91.3 %)**,
  displacement origin 132 (8.7 %). The sweep-wick candidate is itself wrong-side
  in only 2 of 1,416 (0.1 %).
- **The $3.00 buffer rescues 24 of the 25 selected-anchor inversions.** The one
  survivor is `2026-07-21T18:30 BUY MICRO_SCALP`, where `fvg_size = 7.26` — half
  the gap (3.63) exceeds the buffer. 137 of 139 gaps are `< $6.00`
  (median 0.970, p75 1.810, max 7.260).
- **0 ATR-fallback cases** on either path: a candidate was always available.
- PULLBACK's 267 anchors were fully reconstructible read-only **despite zero
  executed PULLBACK trades**.
- **RR is invariant to entry and stop geometry.** `reward_distance =
  risk_distance * tp_ratio`, so `rr ≡ tp_ratio`; see the retraction in P8-18 and
  in P8-08.

### Stating the scale precisely

> **The selected-anchor problem is NOT widespread.** Three different quantities
> must not be collapsed into one:
>
> - **displacement-origin inversion is structurally universal** in the
>   midpoint sub-population — **139 / 139**;
> - **selected-anchor inversion is 25 / 1,525 overall**, and **24 / 139** within
>   the midpoint subset, because the sweep wick usually wins selection;
> - **buffered-stop inversion is 1 / 1,525.**
>
> The first is a property of one *candidate*; only the second and third describe
> what the system actually does.

### Correction to an earlier extrapolation

> **The earlier inference from the four historical trades was invalid and is
> retracted.** From 3-of-4 wrong-side anchors it was inferred that selected-anchor
> inversion was systematic. The full population shows **1.6 %**. Those four trades
> over-represented displacement-origin wins (2 of 4, against 8.7 % population-wide).
> The *geometric* claim — that the displacement origin is the near edge and is
> always wrong-side for a midpoint entry — was correct and is now confirmed at
> 100 % on exactly the sub-population it described. The extrapolation from four
> trades to a population rate was not.

---

## Historical evidence

**OBSERVED — original, `c3cf4df` (2026-07-01), byte-identical to HEAD apart from a
dropped docstring:** `_select_stop_anchor`, its `min`/`max` rule, `buffer_pips =
3.0`, `structure_* = displacement.origin_*` on MOMENTUM, PULLBACK receiving no
`structure_*`, and the FVG midpoint as a **candidate** entry. Its docstring reads
only *"Pick the most defensive structure-based stop anchor."*

**OBSERVED — the original entry was not the midpoint.** At `c3cf4df` the midpoint
was immediately overridden by the M1 breakout close when CHoCH confirmed.

**OBSERVED — rebuild-era, `8a4e010` (2026-09-17)** removed that override, making
the midpoint the final entry, and recorded its own measurement: the M1 close was
*"outside the gap on 13 of 13 occurrences, always on the far side"*. That commit
states explicitly: *"This changes entry prices and therefore outcomes; **it is not
a bug fix**."* — a deliberate strategy change, labelled as such.

**ABSENT.** No original-author artifact states the intended relationship between
the entry and the stop anchor. Historical intent for that relationship is
**NOT established**.

**INFERENCE, labelled as such.** The original design appears geometrically
coherent: with an entry outside the gap, the displacement origin was the *far*
edge and correctly behind the entry. Moving the entry to the midpoint without
revisiting the anchor is what made it the *near* edge. This follows from
`8a4e010`'s own 13/13 measurement plus the zone arithmetic; it is not attested.

---

## Unresolved strategy decisions

**Recorded, deliberately unanswered.**

1. For MOMENTUM midpoint entries, should the stop anchor be allowed to be the
   displacement-origin / near-FVG edge?
2. Should anchor selection be constrained **relative to the entry**, rather than
   by extremeness alone?
3. Is the sweep wick intended to remain the preferred defensive anchor?
4. Should PULLBACK have a separate anchor contract, given it currently has no
   structural anchor at all?
5. Is the buffer meant to be a fixed distance, a pip-defined distance, a
   gap-relative buffer, an ATR-based buffer, or something else?
6. Should **E11** become an invariant *after* the anchor contract is selected?

No option among these is endorsed here, and no value is proposed for any of them.

---

## Sequencing

| Item | State |
|---|---|
| **P8-08** (`$3.00` buffer) | **BLOCKED** — the buffer's role is undetermined until the anchor contract is settled |
| **P8-18** implementation | **BLOCKED** |
| **E11** implementation | **BLOCKED** — a contract-dependent detector, not an independently safe fix. On this evidence it would fire on the inverted candidates rather than repair them |
| **Anchor experiment** | **BLOCKED** |
| **Further read-only instrumentation** | **NOT required** unless a new question arises. The population is fully measured |

> ### The next required action is a strategy-owner contract decision.
>
> No experiment can substitute for it, and no further measurement is needed to
> take it.

---

## E11 scope note — corrected 2026-09-30

**Documentation only.** Recorded because earlier P8-08, P8-18 and stop-anchor
entries described E11 as simply absent. That is **too strong**, and the
correction matters for sequencing.

> **E11 is absent from `entry_engine`, not from the system.** The wrong-side and
> zero-risk geometry it names is already refused at the **execution boundary**, in
> two independent places.

**OBSERVED — source:**

- `core/types.py` `PendingOrderIntent.__post_init__` raises `DomainInvariantError`
  on *"BUY stop … is not below the limit"* and *"SELL stop … is not above the
  limit"* (and on an inverted zone, or a limit outside its zone). Every MOMENTUM
  LIMIT_FVG signal builds one of these, so the check is live and exercised —
  `baseline_007` records 4 intents built and 4 filled.
- `execution/paper_broker.py:277` raises `DomainInvariantError` when
  `position.risk_distance <= 0.0`.
- `execution/paper_broker.py:186,198` additionally reject a fill whose stop has
  been pushed through the fill price by cost adjustment.
- `trade_manager.py:60,81` guard with `if risk_distance <= 0: return`.
- `order_execution.py:96` holds the same guarded division but is **dead** (E1/E2).

**What remains true.** `entry_engine.calculate_entry_levels` itself performs no
side check — it computes `abs(entry_price - stop_loss)`, so an inverted stop
yields a positive risk distance and flows onward. `core/types.py` `StopLoss`
exists to make that unrepresentable and **is not used** by `entry_engine` or
`main_production`. So the *strategy layer* has no invariant; the *execution layer*
does.

**Consequence for sequencing, and why the earlier wording mattered.** A
wrong-side stop reaching a MOMENTUM intent would **raise**, not trade. It would
surface as a strategy error rather than a silent bad position. `baseline_007`
records `strategy_errors = 0` and `rejected_orders = 0`, so no such case occurred.
This makes an `entry_engine`-level E11 check a **defence-in-depth and
error-message improvement**, not the only thing standing between the strategy and
an inverted trade — which is how the earlier wording could be read.

**Unchanged by this correction:** E11 implementation remains **BLOCKED** behind
the stop-anchor contract decision, for the reason already recorded — on the
measured evidence it would fire on inverted candidates rather than repair them.

---

# 3. Experimental rules

**Binding on every Phase 8 experiment.**

### 3.1 The baseline is immutable

`baselines/baseline_006` is frozen. No experiment may overwrite, regenerate or
modify it — **including an experiment that looks better.** The `write_artifacts`
guard refuses to write into an existing baseline directory; that is the
mechanism, and it must not be worked around.

`baseline_004` remains the original production record. `baseline_005` remains
the pre-U4 zero-signal record. Both stay frozen.

### 3.2 Every experiment must

1. **Start from `baseline_006`'s commit** (`a1029a9`) and its dataset
   (`433b7e27…`). A different dataset is a different question.
2. **State the hypothesis before running.** Written down, with a pre-declared
   expected effect and a pre-declared blast radius. D-6OF-2B is the model: *"≈294
   of 1,070 verdicts change; anything outside that causal path is a BLOCKER."*
3. **Change exactly one thing.** One parameter, one rule, one construction. Two
   changes in one replay produce an uninterpretable result, not a faster one.
4. **Record the exact diff** — commit SHA, file, line, before and after.
5. **Use the same replay methodology** —
   `docs/BASELINE_005_PROVENANCE.md` §8, logs redirected,
   `assert_logs_are_redirected()`, `run_baseline` and `write_artifacts`
   unmodified, all other arguments at default.
6. **Compare against `baseline_006`** on: decisions, per-layer funnel, regime and
   session distribution, side distribution, signal count, exact signal list, and
   all four fingerprints.
7. **Get its own baseline identity** if retained — `baseline_007`, `_008`, … A
   result that changes the decision stream is never folded into an existing
   baseline.
8. **Report divergence outside the predicted path as a BLOCKER**, and stop. Do
   not rationalise an unexplained difference into an expected one.

### 3.3 Prohibited

- Selecting a change because it produces more signals, fewer signals, higher
  win rate, or better P&L.
- Tuning any threshold against replay output.
- Parameter sweeps presented as evidence of intent.
- Claiming profitability, or that the strategy is "better", from any replay.
- Inferring a design decision from what is mathematically or technically
  cleaner.
- Forcing a classification where the evidence is insufficient — mark
  **UNRESOLVED** instead.

### 3.4 On sample size

`baseline_006` contains **four trades**. Four is not a sample. No experiment may
report a win rate, expectancy, profit factor or drawdown as evidence for or
against a change. Until the number of trades is large enough to support an
inference — and this framework does not assert what that number is — the only
admissible comparisons are **structural**: which decisions changed, at which
layer, and why.

---

# 4. Proposed research sequence

**A dependency order, not a ranking.** Nothing here says an earlier item is more
important, more promising or more likely to help. The only claim is that later
items are harder to interpret before earlier ones are settled.

### Stage 0 — Read-only characterisation (no replay, no code change)

Answers questions from `baseline_006`'s own artefacts. Nothing here can change
production behaviour.

**Stage 0 is COMPLETE (2026-09-29). No replay was used.** Outcomes:

- **P8-04** — **DONE.** 0 of 119 reach L8 (65 L1 / 46 L3 / 8 L5); 22 did in
  b004/005. Reclassified **B**, and **moves to Stage 3**
- **P8-06** — **DONE.** 4 of 4 gate-reaching decisions compute exactly 1.5; the
  gate rejected 0. Stays coupled to P8-02/P8-03
- **P8-13** — **NOT OBTAINABLE.** `risk_distance` is not in `decisions.jsonl`.
  Cancellation confirmed by other means; the edge-case count remains unmeasured
- **P8-19** — **NOT OBTAINABLE.** `decisions.jsonl` has no POI fields.
  **P8-19 is blocked from Stage 2** until the measurement is authorised
- **P8-18** — **DONE.** The feed supplies only closed bars, so `iloc[-2]` is one
  bar staler than necessary. Not lookahead. Stays in Stage 2

### Stage 1 — Mechanical repairs with bounded, predictable blast radius

Each alone, each with a pre-declared expectation.

- **P8-15 (`bias` only)** — the documented reassignment; expect zero decision change
- **P8-10** — momentum-fallback units; pre-declared ~~≤21~~ **22** (measured on
  baseline_006 at HEAD; the ≤21 figure predates D-6N-1 and D-6OF-2B). **EXPERIMENT NOT YET APPROVED / NOT YET RUN**
- **P8-07** — H1 ATR gate units. **Stage 0 quantified this: the 14-bar H1 range
  never falls below 8.0 *or* 0.8 on this dataset, so both readings fire zero times
  and the repair is UNFALSIFIABLE here.** A null replay is not a validation. Carry
  it as an unvalidated correction, or defer to a dataset that can distinguish the
  units

### Stage 2 — Mechanical repairs that move the geometry

Larger diffs. Stage 0 must be complete, because these change the quantities
Stage 0 measures.

- **P8-18** — entry priced off a stale bar (upstream of the next two).
  Characterised in Stage 0; remains a candidate for controlled research
- ~~**P8-08** — the `$3.00` stop buffer (rename and convert as one change)~~
  **MOVED TO STAGE 3 by the 2026-09-29 characterization.** Reclassified B; no
  correction is uniquely justified, and it is blocked behind **P8-18**
- **P8-09** — L3 replay staleness (expect a large diff; L3 blocks 5,066)
- **P8-19** — the repainting POI. **BLOCKED** until its frequency and L7
  contribution are measured; `baseline_006` cannot supply them
- **P8-16 (repair only)** — SCALP-1 check-4

### Stage 3 — Contract decisions requiring the owner, not evidence

No experiment can settle these. They need a decision first; only then does an
experiment become meaningful.

- **P8-04** — **moved here by Stage 0.** No longer a measurement question: the
  branch blocks nothing on this dataset but was reachable in b004/005. Hard
  dependency on **P8-05**, soft dependency on **P8-14** (regime classification
  determines whether DEAD_CALM becomes reachable at all)
- **P8-08** — **moved here 2026-09-29.** What should the stop be anchored to
  when the MOMENTUM entry is the FVG midpoint? Not a unit question. Blocked
  behind **P8-18**; `3.0 -> 0.30` is explicitly not approved
- **P8-05** — is DEAD_CALM a regime or a rejection?
- **P8-14** — are ATR bands absolute or relative?
- **P8-03** — should the target stay a fixed multiple of risk, or become
  market-derived?
- **P8-01** — what is the retracement band meant to express?
- **P8-15 (`bias_strength`)** — what conviction does a reversed setup carry?
- **P8-16 (extension)** — should the substitution path reach INTRADAY_SWING?

### Stage 4 — Blocked until Stage 3 resolves

- **P8-02** — the RR minimum. Blocked by **P8-03**: while `rr ≡ tp_ratio`, any
  minimum is a regime-admissibility policy, not an RR policy

### Never in Stage sequence — documentation only

- **P8-11**, **P8-12** — annotate, do not remove
- **P8-17**, **P8-20** — standing caveats on interpreting results

---

# 5. Phase 8 status

> ## READY FOR CONTROLLED RESEARCH

`baseline_006` is installed, committed (`9df761f`), verified against the accepted
HEAD state on every measured dimension, and frozen. The ledger above classifies
every unresolved item carried out of Phases 6 and 7. The rules in §3 govern every
experiment that follows.

**No experiment has been run. No item has been ranked. No parameter has been
selected. No strategy behaviour has changed.**
