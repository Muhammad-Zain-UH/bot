# D-6N-1 — Regime / Session Separation

**One controlled architectural change.** Regime is now a volatility
classification; session remains a separate eligibility question. No threshold,
ATR calculation, session definition, kill zone, entry gate, L1–L8 logic,
Fibonacci, sweep, CHoCH, BOS, POI, quality weight, RR, `tp_ratio`, stop, target,
execution, sizing or lifecycle was changed. `baseline_004`, `baseline_005`, the
R1 fixtures and the dataset were read only and are verified unchanged (§14).

**Input:** commit `1560c90` (Phase 6Q).

---

# 1. The Exact Source Change

**One functional line**, `entry_engine.detect_regime`:

```diff
- if m5_atr >= 2.5 and m5_atr <= 4.5 and (kill_zone or session in {"Asian", "London", "LondonNewYork"}):
+ if m5_atr >= 2.5 and m5_atr <= 4.5:
```

Seventeen comment lines record the rationale. **`git diff -U0 -- '*.py' ':!tests/'`
contains exactly one removed and one added functional line.**

`session` and `kill_zone` are still computed, still returned in the regime dict,
and still used in the reasoning string. **No gate was removed.**

---

# 2. Pre-Change Control

The control gate required the pre-change state to match Phase 6Q before
proceeding. A full HEAD replay of `analyze_entry` over the frozen dataset gave:

| Check | Expected | Measured | |
|---|---|---|---|
| Decisions | 15,735 | **15,735** | ✓ |
| DEAD_CALM / INTRADAY_SWING / MICRO_SCALP / REGIME_SCALP | 2,312 / 1,810 / 5,121 / 6,492 | **identical** | ✓ |
| Final signals | 4 (post-U4, Phase 6K-F) | **4** | ✓ |
| L8_ENTRY blocks | 1,261 (post-U4) | **1,261** | ✓ |
| L1 / L2 / L3 / L4 / L5 / L5_WAIT / L6 / L7 | 2,392 / 7 / 5,868 / 629 / 2,441 / 1,634 / 1 / 1,498 | **identical** | ✓ |
| Production source since the fingerprint commit | unchanged | **`git diff` empty** | ✓ |

**Every figure matched. The gate was satisfied.**

---

# 3. Regime Transition Table

| Regime | PRE | POST | Δ |
|---|---|---|---|
| **DEAD_CALM** | 2,312 | **119** | **−2,193** |
| **MICRO_SCALP** | 5,121 | **7,314** | **+2,193** |
| REGIME_SCALP | 6,492 | 6,492 | **0** |
| INTRADAY_SWING | 1,810 | 1,810 | **0** |

**Exactly one transition occurs: `DEAD_CALM → MICRO_SCALP`, 2,193 decisions.**
No other regime transition exists, in either direction.

**The 2,193 are precisely the population Phase 6M identified** — band-B
volatility (2.5 ≤ ATR ≤ 4.5) in a session the old disjunct excluded. Verified
independently: the PRE capture contains **2,193** decisions that were DEAD_CALM
with ATR in band B.

**DEAD_CALM's surviving 119 are the genuinely low-volatility bars**
(ATR < 2.5), matching Phase 6M's count of 119 exactly.

### By session — the change touches only the previously-ineligible ones

| Session | DEAD_CALM | MICRO_SCALP | REGIME_SCALP | INTRADAY_SWING |
|---|---|---|---|---|
| Asian | 18 → 18 | 2,313 → 2,313 | 2,382 → 2,382 | 327 → 327 |
| London | 15 → 15 | 2,736 → 2,736 | 1,444 → 1,444 | 121 → 121 |
| **NewYork** | **1,459 → 30** | **72 → 1,501** | 2,191 → 2,191 | 1,277 → 1,277 |
| **Dead** | **743 → 56** | **0 → 687** | 317 → 317 | 44 → 44 |
| **Closed** | **77 → 0** | **0 → 77** | 158 → 158 | 41 → 41 |

**Asian and London are byte-identical** — they were always eligible.

---

# 4. Changed Decisions and First Divergence

| | |
|---|---|
| **Changed decisions** | **2,193 (13.94 %)** |
| **First divergence point** | **`L0_REGIME` for all 2,193** — no exceptions |

**Every changed decision is one whose regime changed.** No decision changed
without a regime change, and no regime change failed to produce a change.

### Change classification (priority-ordered: E > D > C > B > A)

| Class | Count |
|---|---|
| **D — gate outcome changed** | **1,753** |
| B — regime + style changed | 278 |
| A — regime changed only | 118 |
| C — side changed (same gate, same signal) | 44 |
| E — final signal changed | **0** |

### Which fields changed

| Field | Count | |
|---|---|---|
| `regime`, `bypass_l3`, `bypass_l6`, `poi_threshold` | 2,193 | mechanical consequence |
| `style` | 2,075 | MICRO_SCALP is MOMENTUM-only |
| `passed` | 2,075 | |
| `blocked` | 1,753 | |
| **`bias`** | **1,158** | **the cascade — §5** |
| **`direction`** | **1,157** | |
| `bos_flip` | 912 | |
| `momentum_fallback` | 906 | |
| `tp_ratio` | **0** | DEAD_CALM and MICRO_SCALP both use 1.5 |
| `entry_price`, `stop_loss`, `take_profit`, `rr`, `quality`, `risk_distance` | **0** | none of the 2,193 is a signal in either run |

---

# 5. Downstream Cascade — the non-obvious consequence

**The regime selects which bias engine runs.** Phase 6O-E established that
`use_fast_bias = regime in ("MICRO_SCALP", "REGIME_SCALP")`. Moving 2,193
decisions into MICRO_SCALP moved them from the strict **H4** engine to the
**H1 fast** engine.

| | PRE | POST |
|---|---|---|
| Bias timeframe H1 / H4 | 11,613 / 4,122 | **13,806 / 1,929** |
| L1_BIAS blocks among the 2,193 | 1,017 | **130** |

**Bias label transitions within the 2,193:**

| Transition | Count | |
|---|---|---|
| `NEUTRAL → BULLISH` | 483 | previously blocked at L1 |
| `NEUTRAL → BEARISH` | 416 | previously blocked at L1 |
| **`BEARISH → BULLISH`** | **154** | **direction reversed** |
| **`BULLISH → BEARISH`** | **93** | **direction reversed** |
| `BULLISH → NEUTRAL` | 12 | newly blocked at L1 |

> **247 of the 2,193 decisions now carry the opposite direction — not because
> anything in L1 or L2 changed, but because the H1 and H4 bias engines disagree
> and the regime chooses between them.** This was predicted in Phase 6O-E and is
> now measured.

### Layer funnel, PRE → POST

| Layer | PRE | POST | Δ |
|---|---|---|---|
| L1_BIAS | 2,392 | **1,505** | **−887** |
| L2_STRUCTURE | 7 | 12 | +5 |
| L3_PULLBACK | 5,868 | 5,094 | −774 |
| L4_LIQUIDITY | 629 | 725 | +96 |
| L5_SWEEP | 2,441 | 3,037 | +596 |
| L5_SWEEP_WAIT | 1,634 | 1,935 | +301 |
| L6_POI | 1 | 1 | 0 |
| L7_CONFIDENCE | 1,498 | 1,833 | +335 |
| L8_ENTRY | 1,261 | 1,589 | +328 |

**Entry style:** MOMENTUM 4,766 → **6,824 (+2,058)**; PULLBACK 2,702 → 2,300
(−402); both-allowed 5,875 → 5,106 (−769).

**L2 reversals:** 1,738 → **1,845 (+107)**, because 887 more decisions reach L2
at all. The reversal *rate* is essentially unchanged: **13.03 % → 12.97 %**. The
BROKEN identity still holds: **1,857 = 1,845 + 12**.

---

# 6. Final Signals

| | PRE | POST |
|---|---|---|
| **ENTRY_SIGNAL** | **4** | **4** |
| Added | — | **none** |
| Removed | — | **none** |

**The same four timestamps, unchanged in every field.** None of the 2,193
changed decisions is a signal in either run.

```
2026-07-17T12:40   London  kill_zone=True  MICRO_SCALP
2026-08-06T08:00   London  kill_zone=True  MICRO_SCALP
2026-08-12T09:25   London  kill_zone=True  MICRO_SCALP
2026-08-28T08:45   London  kill_zone=True  MICRO_SCALP
```

**This is a measurement, not an evaluation.** It is stated because the brief
requires the signal delta, and it is neither an improvement nor a regression.

---

# 7. Session Safety

**The requirement:** out-of-session entries must not have become eligible.

| Session | Decisions | Reached L8 | **Signals** | Kill zone ever true |
|---|---|---|---|---|
| **Dead** | 1,104 | **0 → 13** | **0 → 0** | **0** |
| **Closed** | 276 | **0 → 0** | **0 → 0** | **0** |

**Signals in Dead or Closed: 0, before and after.** All four signals are London,
kill zone active.

**13 Dead-session decisions now reach L8 that previously did not.** Every one is
`MICRO_SCALP`, style `MOMENTUM`, and every one is blocked at L8 with
*"Entry triggers not all confirmed"* — because `_evaluate_momentum_entry`
requires `kill_zone`, which is never true in the Dead session (hours 21–23).

### The safety mechanism, stated precisely — and a caveat

**What now prevents out-of-session entries is the kill-zone requirement inside
the momentum trigger, not the regime classifier.** MICRO_SCALP is MOMENTUM-only,
and MOMENTUM requires the kill zone.

**Before this change there were two independent barriers**: that one, *and*
DEAD_CALM's structurally impossible RR gate (`1.5 >= 2.0`, false by
construction). **The second barrier is now gone.** It was never designed as a
safety mechanism — it was a by-product of the RR tautology (E9/E10) — but it was
load-bearing in practice.

> **Defence-in-depth was reduced from two accidental layers to one.** If
> MICRO_SCALP's MOMENTUM-only style restriction or the momentum kill-zone gate
> were ever changed, out-of-session entries would become reachable. Neither is
> changed here, and both are pinned by tests. **This is recorded as a new
> standing risk, not as a defect introduced by this change.**

**Unchanged:** session definitions, `KILL_ZONES_UTC`, weekend handling. The
Closed-session regime relabelling (77 DEAD_CALM → MICRO_SCALP) is a direct
consequence of the reclassification and produces no signal, since weekend bars
exist only at hours 22–23.

---

# 8. Temporal Safety

| Check | Result |
|---|---|
| Leakage suite (`test_leakage`, `test_integration_leakage`) | **Pass** |
| SELL-side leakage suite (Phase 6Q, 18 tests) | **Pass** |
| Future-bar violations | **0** — the change touches no data access |
| New temporal dependency | **None** — one boolean conjunct was removed |
| BUY and SELL coverage | **Both retained** |

`detect_regime` reads the same frames, at the same instants, through the same
`frozen_clock`. Nothing about data visibility changed.

---

# 9. Test Results

| | Before | After |
|---|---|---|
| Tests | 1,061 | **1,064** |
| Failures | 2 | **2** |

### Expected failures — tests that encoded the old contract

| Test | Disposition |
|---|---|
| `test_baseline_defects.test_detect_regime_still_references_it` | **Failed by design.** Its own docstring said *"If this stops matching, the defect was fixed and D8 can be closed."* Replaced by `test_detect_regime_no_longer_references_it`, plus a new test pinning that the label **survives** in `config.py` and `main_production.py` — **D8 is closed in the classifier, not repo-wide** |
| `PinnedAggregateFingerprint` × 5 | **Failed by design** once the fingerprint became a HEAD replay. Split into a frozen-stream artifact check and post-change HEAD assertions |
| `PinnedCorrectedL2Population` × 5 | **Failed by design.** Updated: sided 13,343 → 14,230; reversals 1,738 → 1,845; BROKEN 1,745 → 1,857; rescue failures 7 → 12; distinct H1 states 153 → 157 |

**No test was edited merely to make it green.** Each updated assertion states the
PRE value, the POST value, and why it moved.

### Unexpected failures

**None.**

### Unchanged pre-existing failures

`test_micro_scalp_l7_confidence_uses_55_threshold` and
`test_pullback_gate_requires_real_pullback_detection` — both classified vacuous
in Phase 6P; both fail at L2 because mocked indicators make `h1_atr = 0.0 < 8.0`,
and neither reaches the layer it names.

### A pin of mine that did not hold

`test_dead_calm_is_the_else_branch_not_an_atr_test`, written in Phase 6P,
**passed before and after the change** and should have failed. It guarded its
assertion with `if 2.5 <= atr <= 4.5` at an instant whose ATR is **5.147**, so
the assertion never ran. **It was vacuous from the day I wrote it** — the exact
failure mode Phase 6P catalogued in other people's tests. Replaced with
`test_band_b_volatility_classifies_micro_scalp_regardless_of_session`, which
asserts its premises (session, kill zone, band membership) rather than guarding
on them.

---

# 10. Fingerprints

| Artifact | Contents |
|---|---|
| `audit/d6n1/fingerprint_pre.json` | Pre-change, **not overwritten** |
| `audit/d6n1/fingerprint_post.json` | Post-change |
| `tests/fixtures/behavior_fingerprint.json` | Post-change (the live pin) |
| `audit/d6n1/replay_fingerprint_{pre,post,diff}.json` | Decision-level replay summaries and their diff |

**Decision-stream checksums:** PRE `178f8da39d68a9bc…` → POST `67366ced8aaa1c6e…`.

### A generator defect found and fixed during this change

The Phase 6P generator read `blocked_at` / `signal_type` / `effective_side` from
the **frozen `baseline_005` stream** while recomputing regime, bias and structure
from **HEAD**. That mixture is coherent only while HEAD's strategy matches the
stream's.

**The first post-change regeneration produced nonsense**: side-state combinations
such as `L1=BUY | EFF=None` (483) and `L1=None | EFF=BUY` (12), because HEAD now
produced a side for 887 decisions the stream recorded as blocked at L1. The
derived "1,983 reversals" was an artifact of comparing two different strategies.

**That output was quarantined, not committed.** The generator now performs **one
HEAD replay** for every field, so the fingerprint is internally consistent by
construction. The regenerated file has exactly five coherent side-state
combinations and satisfies the BROKEN identity.

**This is the Phase 6Q §11 limitation materialising, and it is now fixed.**

---

# 11. Side-State Consistency — preserved

| Combination | PRE | POST |
|---|---|---|
| `L1=BUY \| EFF=BUY \| L3=BUY` | 5,681 | 6,169 |
| `L1=BUY \| EFF=SELL \| L3=BUY` | 726 | 770 |
| `L1=SELL \| EFF=BUY \| L3=SELL` | 1,012 | 1,075 |
| `L1=SELL \| EFF=SELL \| L3=SELL` | 5,924 | 6,216 |
| none | 2,392 | 1,505 |

**Still exactly five combinations, and `L3 == L1` in every one.** The stale-bias
inconsistency (D-6OF-2) is untouched and still pinned with zero exceptions.

---

# 12. What This Change Did **Not** Do

It did not remove a session gate — the L0 gate and
`strategy_engine._validate_session_rules` remain exactly as dead as Phase 6N
found them. It did not touch any threshold, the ATR calculation, `atr_ratio`,
the H1 volatility gate, session definitions, kill zones, any of L1–L8's internal
logic, Fibonacci, sweep, CHoCH, BOS, POI, quality weights, RR, `tp_ratio`, stop
or target construction, execution, sizing, lifecycle or pending-order behaviour.
It did not resolve U9-RR.

---

# 13. Integrity

| Check | Result |
|---|---|
| Production functional lines changed | **1** |
| `git status -- baselines/ data/ tests/integration/` | **empty** |
| `baseline_004` / `baseline_005` `run_fingerprint` | `1276a31f673a5a82b2879ea5113b12e486da…` unchanged |
| Dataset hash | `433b7e2713babdef…` unchanged |
| R1 fixtures | untouched, passing |

---

# 14. Remaining Strategy Decisions

| ID | Decision | Status |
|---|---|---|
| **U9-RR** | The RR minimum | **Unblocked by this change.** The population it governs is now stable |
| **D-6OF-2** | Reassign `bias` on the L2 flip, so L3 and L7 see the traded direction | Open — 1,845 decisions affected |
| **D-6OE-1 / D-6OF-1** | May L2 reverse L1's direction at all? | Open |
| **D-6OD-1** | Nearest or strongest liquidity level | Open |
| **D-6OC-1** | Should a sweep/CHoCH be required | Open |
| **D-6OB-1** | Should a pullback be required | Open |
| **U10-B** | Absolute or relative ATR bands | Open |
| **New** | Should the MICRO_SCALP MOMENTUM-only restriction remain the sole out-of-session barrier (§7)? | **Raised by this change** |
| Plus | D-6OB-2…7, D-6OC-2…6, D-6OD-2…6, D-6OE-2…6, D-6OF-3…7 | Open |

---

# 15. Recommended Next Decision — not implemented

> **D-6OF-2 — reassign `bias` when the L2 flip fires — before U9-RR.**

**Why before U9-RR.** U9-RR sets the minimum RR per regime, and the RR gate is
reached only by decisions that survive L3. **L3 currently measures a pullback
against the direction the pipeline abandoned**, on 1,845 decisions — 12.97 % of
those with a side. Phase 6O-F measured that reversed decisions fail L3 at 54.3 %
against 42.4 % for non-reversed. Choosing an RR threshold while L3 is evaluating
the wrong direction for one decision in eight would fix a number against a
population that D-6OF-2 is about to change.

**Why it is now the smallest useful next step.** It is a one-line change of the
same character as this one: assign `bias` alongside `side` in the flip block. Its
effect is pinned in advance by `PinnedSideStateConsistency` and
`PinnedSideStateInconsistencyHasZeroExceptions`, which will fail by design.

**Second, if D-6OF-2 is declined:** resolve **D-6OE-1** — whether L2 may reverse
direction at all — since every downstream decision inherits that answer.

**Do not proceed to U9-RR until one of the two is settled.**

---

# 16. Scope Confirmation

| | |
|---|---|
| Production change | **One functional line**, `entry_engine.detect_regime` |
| Thresholds, ATR, sessions, kill zones, L1–L8 logic, RR, stops, targets, sizing, execution | **Untouched** |
| Unrelated cleanup | **None** |
| Baselines, R1, dataset | **Read only; verified unchanged** |
| Signal count framed as improvement | **No** — §6 states it as a measurement |
| Tests edited to pass | **No** — every update records PRE, POST and cause |

**No profitability conclusion is drawn or available.** The four signals have
never been executed, held or closed in any measurement.
