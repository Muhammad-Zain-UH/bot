# Phase 6K-G — Post-U4 Admission-Surface Audit

**Audit only. No production source, threshold, regime rule, DEAD_CALM,
`trigger_quality`, baseline or R1 fixture changed.** U9 is not chosen. No
threshold sweep was run. No issue is ranked by profitability, and nothing is
inferred about which threshold is "better" from the four current signals.

**Input:** Phase 6K-F `7b1c5f1`.

**Purpose:** map the final admission surface so that the eventual U9 decision
cannot become a proxy for other unresolved defects.

## Labels

**OBSERVED** source · **MEASURED** from a run or frozen artefact ·
**DOCUMENTED** stated as intent · **INFERENCE** reasoning from stated premises.

---

# 1. Executive Summary

**Three findings.**

**F1 — The final gate has never rejected anything, post-U4.** Its entire
observable history is **4 candidates, 4 admissions, 0 rejections**. Before U4 it
rejected exactly one, on floating-point error. **Both of its terms are
currently unexercised as discriminators.**

**F2 — `trigger_quality` is saturated for the only population the gate sees.**
**MEASURED:** all 4 gate-reaching candidates scored **exactly 10.0**, the cap.
**INFERENCE, corroborated:** `core_trigger` requires `kill_zone`,
`displacement_found`, `fvg_found` and `m1_choch_confirmed`; the quality sum adds
a non-zero term for each plus `+1.0` for the kill zone, then applies
`min(10.0, …)`. **A candidate that satisfies the trigger is structurally likely
to saturate.** After U4, quality is the gate's only term that *could* vary — and
it does not, for the candidates it judges.

**F3 — DEAD_CALM's RR barrier has never been exercised.** **MEASURED:** 22
DEAD_CALM decisions reached L8; **none** reached the gate, because
`entry_triggered` was false for every one. Its inability to trade on this
dataset is caused by `raw_triggered`, **not** by the `rr >= 2.0` default. That
barrier is **latent**, not operative.

**Consequence for U9:** the threshold decision is being made over a gate with
**four observations, zero rejections, and one saturated term.** That is not a
reason to choose any particular value — it is a reason to record that the
evidence base for *any* value is four data points.

---

# 2. The Complete Admission Surface, Post-U4

**MEASURED**, full replay of the verified dataset (SHA-256 `433b7e27…`),
post-U4 run. Blocks sum to 15,735 — every decision accounted for.

| # | Gate | Condition | Regime/style dependent | Entering | Passing | Failing |
|---|---|---|---|---|---|---|
| 1 | **L1 BIAS** | HN EMA bias not NEUTRAL | no | 15,735 | 13,343 | 2,392 |
| 2 | **L2 STRUCTURE** | HN structure intact | no | 13,343 | 13,336 | 7 |
| 3 | **L3 PULLBACK** | confirmed pullback | **yes** — `bypass_l3` for MICRO_SCALP | 13,336 | 7,468 | 5,868 |
| 4 | **L4 LIQUIDITY** | sweep/TP pool quality + distance | no | 7,468 | 6,839 | 629 |
| 5 | **L5 SWEEP/CHoCH** | sweep + CHoCH confirmed | no | 6,839 | 2,764 | 4,075 |
| 6 | **L6 POI** | POI score ≥ threshold | **yes** — `bypass_l6`, threshold 50/60/70 | 2,764 | 2,763 | 1 |
| 7 | **L7 CONFIDENCE** | score ≥ 55 (MICRO) or 70 | **yes** | 2,763 | 1,265 | 1,498 |
| 8a | **L8 raw trigger** | `entry_triggered` | **yes** — style restriction | 1,265 | **4** | **1,261** |
| 8b | **L8 regime gate** | `quality >= Q and rr >= R` | **yes** | **4** | **4** | **0** |
| — | **ENTRY_SIGNAL** | — | — | — | **4** | — |

## 2.1 Inside L8 — where the surface actually narrows

**MEASURED:**

```
1,265 reach L8
  └─ 1,261 blocked: "Entry triggers not all confirmed"   (entry_triggered false)
  └─     4 reach evaluate_entry_for_regime
         ├─ quality >= 5.0   ->  4 pass, 0 fail   (all exactly 10.0)
         ├─ rr      >= 1.5   ->  4 pass, 0 fail   (all exactly 1.5, post-U4)
         └─     4 admitted
```

**99.7 % of the narrowing at L8 happens before the gate.** The gate itself
judges 4 candidates.

---

# 3. Gate-by-Gate Findings

## A. `trigger_quality` — thresholds 5.0 / 6.0 / 7.0

| | |
|---|---|
| Condition | `trigger_quality >= 5.0` (MICRO_SCALP), `6.0` (REGIME_SCALP), `7.0` (INTRADAY_SWING), `5.0` (default) |
| Regime-specific | **Yes** |
| Documented as intent | **No.** Phase 6K-D: no comment, no commit message, no design document states any of the three |
| Rationale known | **No** |
| Entering / passing / failing | **4 / 4 / 0** |
| Values observed | **10.0, 10.0, 10.0, 10.0** — the cap |

**MEASURED, the wider population.** Across all 15 raw-triggered candidates
(11 of which never reach the gate), quality ranged **4.68 – 10.0**, with **7 at
exactly 10.0**.

**INFERENCE — the saturation is structural, not coincidental.** **OBSERVED**,
`entry_engine.py:625-633`: momentum quality is
`displacement_quality + 0.6×fvg_quality + 0.4×momentum_quality +
0.8×m1_quality + 1.0(kill_zone) + 0.25(rejection)`, then `min(10.0, …)`. Every
term the sum draws on is a condition `core_trigger` already requires. A
candidate that passes the trigger therefore contributes to all of them and
saturates.

**Soundness:** the arithmetic is sound; the **discriminating power is not**. A
score capped at 10.0 that saturates for its whole judged population cannot
separate candidates. **The threshold has never bound.**

**Tests exercising production-equivalent values:** **none.**
`tests/test_entry_quality_gate.py` uses 4.2, 6.8, 7.2 — plausible values that
have never been observed at the gate, paired with `rr` values that
**cannot occur** (§F).

**Not changed.**

## B. RR admission — the four confirmations

| Item | Status | Confirmation |
|---|---|---|
| **U2 structure** | **Retained** | The runtime gate is present at `evaluate_entry_for_regime`; not removed, not relocated to configuration. **OBSERVED** in source at HEAD |
| **U3 meaning** | **Resolved** | `rr` is the configured TP/risk multiple. **MEASURED post-U4:** all four gate-reaching candidates evaluate to exactly their regime `tp_ratio` |
| **U4 representation** | **Complete** | `reward_distance = risk_distance * tp_ratio`. **MEASURED:** one admission changed, zero removed, R1 unchanged |
| **U9 numerical minimum** | **UNRESOLVED** | No value chosen, proposed or implied by this audit |

**Current behaviour, quantified — and explicitly not evidence for keeping these
values:** with `1.5 / 2.0 / 2.5 / 2.0` in force, the RR term passes **4 / 4** and
rejects **0**. **That is a fact about the current configuration on four
candidates. It is not an argument that the configuration is correct**, and per
Phase 6K-E §3 any value's effect on these four is known in advance, so the
observation cannot serve as independent support for any choice.

**Residual hazard, unchanged by U4:** MICRO_SCALP's threshold still equals its
own `tp_ratio` exactly. `(R × k) / R` differs from `k` by one ulp in roughly
10 % of values, so a future candidate can still land below. **U9, not U4.**

## C. Regime / style constraints

**OBSERVED**, `entry_engine.get_entry_trigger:687-694`:

| Regime | Allowed styles | Documented intent | Candidates blocked |
|---|---|---|---|
| **MICRO_SCALP** | **MOMENTUM only** | **Indirect only** — `SYSTEM_STRUCTURE_DIAGRAM.md:234`, *"MICRO_SCALP momentum entries don't need pullback"*, which justifies the **L3 bypass**, not the L8 restriction | **11** — every pullback candidate that fired |
| **INTRADAY_SWING** | **PULLBACK only** | **None anywhere.** Every mention is an audit describing the implementation | **0** on this dataset |
| REGIME_SCALP | both | n/a | 0 |
| DEAD_CALM | both | n/a | 0 |

**MEASURED:** **all 11 blocked candidates are MICRO_SCALP pullbacks.** The
INTRADAY_SWING restriction has **never been exercised**, so it is undocumented
*and* untested by data.

**Recorded contradiction** (Phase 4B audit #12, unchanged): L3 determines whether
the setup is a pullback or a momentum continuation and writes it to a field read
**only by display functions**; L8 decides again from the regime name and ignores
it.

**Not changed.** Phase 6C Decision A accepted this provisionally.

## D. DEAD_CALM — post-U4

**MEASURED, post-U4:**

| | |
|---|---|
| Decisions in DEAD_CALM | **2,312** (14.7 % of all) |
| Reaching L8 | **22** |
| Reaching the regime gate | **0** |
| Blocked by `rr >= 2.0` | **0** |
| Raw triggers (`entry_triggered`) | **0** — all 15 raw triggers on this dataset are MICRO_SCALP |

**The distinction the brief asks for, answered precisely:**

| Question | Answer |
|---|---|
| **Can it currently pass?** | **No** |
| **Why not, on this dataset?** | **`raw_triggered` was never true.** Not the RR gate |
| **Is the RR barrier operative?** | **No — it is latent.** `1.5 < 2.0` would bar it, but no candidate has ever reached the comparison |
| **Is it intentionally forbidden?** | **No.** No document forbids it |

**Preserved historical evidence** (Phase 6K-B, from `c3cf4df`):

```
# Dead calm (ATR < 2.5) - Will be BLOCKED by L2, but show proper config anyway
risk = 0.75              # Show a value even though trade won't happen
tp_ratio = 1.5           # Realistic if it somehow escaped L2
poi_threshold = 70       # Normal threshold (won't matter, L2 blocks first)
```

**Its `tp_ratio = 1.5` is a documented cosmetic fallback**, and the belief it
rests on is **contradicted**: 22 decisions reached L8 while L2 blocked 7 in
total across all regimes.

**Not changed.**

## E. Rejection diagnostics

| # | Message | Defect | Status |
|---|---|---|---|
| 1 | `"micro scalp quality too low (quality=…, rr=…)"` | **Misattributes.** Fires when **either** term fails but names only quality. It named quality for the 2026-08-06 candidate whose quality was 10.0 and whose `rr` failed | **Still present.** Its only occurrence disappeared post-U4 by consequence, not by edit — **the defect is untouched** |
| 2 | Same message | **Prints the failing value as the threshold.** `:.1f` rendered `1.4999999999998295` as `rr=1.5` — the exact value it failed to reach | **Still present** |
| 3 | `"regime scalp quality too low"`, `"intraday quality too low"` | Same misattribution, same format | **Still present, never observed firing** |
| 4 | `"default entry gate"` | **Says nothing.** The DEAD_CALM path's rejection reason carries no information at all | **Still present, never observed firing** |
| 5 | `"Entry triggers not all confirmed"` | Accurate but **undifferentiated** — 1,261 decisions share it, covering style restriction, missing FVG, missing CHoCH and more | **Still present** |

**Not fixed** — deferred by instruction until the contract is decided.

## F. Tests

**Exercising impossible / non-production combinations:**

| Test | Uses | Production reality |
|---|---|---|
| `test_micro_scalp_requires_stronger_quality_and_rr` | `rr = 1.4` | MICRO_SCALP `rr` is **exactly 1.5** |
| `test_regime_scalp_allows_stronger_setup` | `rr = 2.4` | REGIME_SCALP `rr` is **exactly 2.0** |
| `test_intraday_requires_high_quality` | `rr = 2.8` | INTRADAY_SWING `rr` is **exactly 3.0** |

**INFERENCE:** since `rr ≡ tp_ratio`, none of these three `rr` values can occur
for the regime it is paired with. The tests pass and exercise the gate with
inputs production cannot produce. The first also fails **both** terms at once
(`quality 4.2`, `rr 1.4`), so it cannot show which one bound — and it asserts on
the message text that §E.1 shows to be misattributing.

**Missing tests for actual production boundary conditions:**

| # | Gap |
|---|---|
| 1 | **No test that `rr` equals `tp_ratio` exactly at the gate**, per regime |
| 2 | **No test that quality saturates at 10.0** for a trigger-passing candidate — §A |
| 3 | **No test for the DEAD_CALM default branch** — it is the only branch with no test at all |
| 4 | **No test that the message names the term that actually failed** — it cannot pass today |
| 5 | **No test that the INTRADAY_SWING style restriction blocks anything** — untested by data and by suite |

**Not rewritten.** Doing so is U7 and belongs with the gate's own decision; this
audit required no source change and made none.

## G. U10 — ATR band units, restated only as it affects admission

**OBSERVED**, `PHASE_2_ISSUES.md` U10 (**P0**, unresolved): `detect_regime`'s
ATR bands `2.5 / 4.5 / 7.0` are labelled "pip" but applied to a raw ATR in
**dollars**. For XAUUSD 1 pip = $0.10, so a threshold intended as 2.5 pips is
being applied as **$2.50 = 25 pips**.

**Why it belongs in an admission audit:** the regime selects **`tp_ratio`, the
quality threshold, the RR threshold, the POI threshold, the bypass flags and
the allowed styles.** If the bands are wrong, **every row of §2 and §3 is
conditioned on a misclassification**, and the U9 decision would be choosing a
minimum for regimes that are not the regimes intended.

**MEASURED distribution under the current bands:** REGIME_SCALP 6,492 ·
MICRO_SCALP 5,121 · DEAD_CALM 2,312 · INTRADAY_SWING 1,810.

**Not fixed, not investigated further here.** Recorded as a **dependency of
U9**, not as a separate task.

---

# 4. Decision Matrix

| # | Issue | Current behaviour | Evidence strength | Correctness status | Design status | Blocks Phase 7? | Next action |
|---|---|---|---|---|---|---|---|
| 1 | **U3** — what `rr` means | Configured TP/risk multiple | **DOCUMENTED** (6K-B) | Sound | **RESOLVED** | No | None |
| 2 | **U4** — reward representation | `risk_distance × tp_ratio` | **MEASURED** | Sound | **RESOLVED** | No | None |
| 3 | **U2** — gate structure | Runtime gate retained | **DOCUMENTED** (6K-C hard gate) | Sound | **RESOLVED** (structure) | No | None |
| 4 | **U9** — the minimum RR | 1.5 / 2.0 / 2.5 / 2.0 | **None** for any value | n/a — a choice | **DESIGN DECISION** | **YES** | Requires 6K-E §6.1 record |
| 5 | **U1** — quality thresholds 5/6/7 | Pass 4/4, all at the 10.0 cap | **None** | **Sound arithmetic, no discriminating power** | **DESIGN DECISION** | **YES** | Decide what quality measures |
| 6 | **Quality saturation** | Structurally saturates for trigger-passing candidates | **MEASURED** 4/4 + **INFERENCE** from construction | **IMPLEMENTATION DEFECT** — a capped score that saturates cannot discriminate | Needs a decision, not just a repair | **YES** | Investigate before U1 |
| 7 | **U5** — DEAD_CALM | Cannot pass; barrier **latent**, never exercised | **DOCUMENTED** that its config is cosmetic | Not a defect — an accident | **DESIGN DECISION** | **YES** | Must be explicit either way |
| 8 | **Style restriction** | MICRO→MOMENTUM blocks 11; INTRADAY→PULLBACK blocks 0 | **Indirect** for one half, **none** for the other | Sound as written | **DESIGN DECISION** (6C accepted provisionally) | No — accepted | Revisit only if U9 changes admission |
| 9 | **L3/L8 style contradiction** | L8 ignores L3's setup finding | **DOCUMENTED** (audit #12) | **IMPLEMENTATION DEFECT** | Needs a decision | No | Register |
| 10 | **Misattributing message** | Names quality when `rr` fails; prints failing value as threshold | **MEASURED** | **IMPLEMENTATION DEFECT** | Repair, no policy | No — but corrupts diagnosis | Fix with U9 |
| 11 | **`"default entry gate"`** | Carries no information | **OBSERVED** | **IMPLEMENTATION DEFECT** | Repair | No | Fix with #10 |
| 12 | **Undifferentiated L8 reason** | 1,261 decisions share one string | **MEASURED** | **DOCUMENTATION DEFECT** (diagnostic) | Repair | No | Fix with #10 |
| 13 | **Impossible test inputs** | 3 tests use unreachable `rr` | **MEASURED** | **MEASUREMENT/TEST DEFECT** | Rewrite = U7 | No | With the gate decision |
| 14 | **5 missing boundary tests** | §F | **MEASURED** | **MEASUREMENT/TEST DEFECT** | Add | No | With U7 |
| 15 | **U10** — ATR bands in dollars | Regime misclassification possible | **DOCUMENTED** P0 | **IMPLEMENTATION DEFECT** | Needs units decision | **YES — upstream of U9** | Resolve **before** U9 |
| 16 | **Residual ulp hazard** | Threshold equals `tp_ratio` | **MEASURED** ~10 % inexact | Not a defect post-U4 | Subsumed by **U9** | With U9 | Address in U9 |
| 17 | **Zero trades** | No signal ever executed | **MEASURED** | n/a | **OUTSIDE CURRENT SCOPE** | **YES** | Phase 7 prerequisite |

---

# 5. The Exact Remaining Pre-Phase-7 Work

**Six items block Phase 7.** Ordered by dependency, **not by expected effect on
any outcome.**

| Order | Item | Why it must come first |
|---|---|---|
| **1** | **U10** — ATR band units (#15) | Determines which regime a decision lands in, hence which `tp_ratio`, which thresholds and which styles apply. **A U9 chosen before this is a minimum for regimes that may be misclassified** |
| **2** | **Quality saturation** (#6) | After U4, quality is the gate's only potentially-varying term, and it is saturated for every candidate the gate judges. Deciding U1 without knowing why is deciding blind |
| **3** | **U1** — quality thresholds (#5) | Follows directly from 2 |
| **4** | **U9** — the minimum RR (#4) | Depends on 1. Requires the 6K-E §6.1 record: value, scope, why not its neighbours, which regimes it permits, what falsifies it |
| **5** | **U5** — DEAD_CALM (#7) | Must be an explicit statement, never a side effect of 4 |
| **6** | **A trade-producing baseline** (#17) | Requires 1–5 settled |

**Not blocking, and repairable independently:** the diagnostic defects
(#10, #11, #12) and the test defects (#13, #14).

**The observation that should govern U9, stated once:** the gate it configures
has **four observations and zero rejections**, and one of its two terms is
saturated. **Whatever value is chosen, the record must say that the evidence
base was four candidates.** That is not an argument for or against any value.

---

# 6. Confirmation

| | |
|---|---|
| Source changes | **None.** No `.py` file modified |
| Thresholds / regime rules / DEAD_CALM / `trigger_quality` | **Unchanged** |
| U9 | **Not chosen.** No value proposed or implied |
| Threshold sweep | **Not run** |
| `baseline_004` / `baseline_005` | **Untouched** |
| R1 fixtures | **Untouched** |
| Working tree | Clean; this commit adds one document |

**No issue was ranked by profitability, and nothing was inferred about which
threshold is better from the four signals.** No profitability conclusion is
drawn or available: those four have never been executed, held or closed.
