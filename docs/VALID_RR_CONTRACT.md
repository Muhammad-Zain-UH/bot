# The `valid_rr` Contract

**`valid_rr` is no longer an independent runtime gate.** It was removed from
`entry_triggered` in Phase 6I.

**No minimum-RR value is defined anywhere in this repository, and none was
introduced.** The minimum remains **UNRESOLVED**.

**No profitability claim is made.** Nothing here says the strategy is better,
worse, or viable. Three candidates now reach signal construction that did not
before; what they would do is unmeasured.

---

# 1. What was removed, and why

**OBSERVED.** `calculate_entry_levels` builds the target as:

```
take_profit     = entry_price ± risk_distance × tp_ratio
reward_distance = |take_profit − entry_price|
rr              = reward_distance / risk_distance      →  rr ≡ tp_ratio
valid_rr        = rr >= 2.0                            →  (tp_ratio >= 2.0)
```

`rr` was constructed from `tp_ratio` two lines earlier, so comparing it to a
threshold asked whether the configured value was the configured value. The
verdict was fixed per regime before any price was read.

**Phase 6C Decision B** ruled that a minimum-RR requirement, if one is wanted,
is a **configuration invariant over `tp_ratio`** — checked once, where the ratio
is chosen — not a per-candidate runtime gate. Phase 6I implements only the
removal.

## 1.1 The change

```diff
- "entry_triggered": bool(raw_triggered and entry_levels["valid_rr"]),
+ "entry_triggered": bool(raw_triggered),
```

and the same for the momentum path's `core_trigger`. The `valid_rr` field is
gone from every returned dict, and the scoring bonus that read it is gone.

**Nothing replaced it.** No threshold was moved, added or renamed.

## 1.2 Why removing the scoring bonus changes no selection

**DERIVED, and tested.** `_score_entry_candidate` added `2.0 if valid_rr`. Since
`valid_rr ≡ (tp_ratio >= 2.0)` and both candidates in a decision are evaluated at
the same `regime_tp_ratio`, both received the **same** bonus, so it cancelled in
every comparison. Pinned by
`test_the_removed_scoring_bonus_could_never_have_decided_a_winner`.

---

# 2. Observability

**The geometry is still reported; only the verdict is gone.**

`calculate_entry_levels` still returns `entry_price`, `stop_loss`,
`take_profit`, `risk_distance`, `reward_distance` and `reward_to_risk_ratio`.

`main_production`'s L8 decision record reports `tp_ratio`, `risk_distance`,
`reward_distance` and `rr` in place of the former `rr_valid` boolean. A field
claiming an RR verdict was reached would be untrue, so none is recorded.

**Retired vocabulary.** `core/signal_log.py`'s v2 column order still contains
`rr_valid`. The column is now **defined but unpopulated**, on the existing
`CLOSED_TIME` / `TIME_EXIT` precedent: retiring a mechanism does not require
rewriting a log schema, and an empty column is honest about what was evaluated.

---

# 3. A second RR gate exists, and was **not** removed

**This is the most important thing to understand about the current state.**

**OBSERVED.** `entry_engine.evaluate_entry_for_regime` applies its own
thresholds *after* `entry_triggered`, conjoined with `trigger_quality`:

| Regime | Gate |
|---|---|
| MICRO_SCALP | `quality >= 5.0 and rr >= 1.5` |
| REGIME_SCALP | `quality >= 6.0 and rr >= 2.0` |
| INTRADAY_SWING | `quality >= 7.0 and rr >= 2.5` |
| *(default — includes DEAD_CALM)* | `quality >= 5.0 and rr >= 2.0` |

This is a **different, pre-existing gate**: per-regime, conjoined with quality,
applied after the trigger rather than as part of it. Phase 6I had no authority
to touch it and did not. It is pinned by five tests so that *"the RR gate is
retired"* can never be read as *"no RR comparison remains"*.

## 3.1 DEAD_CALM is still structurally unable to enter — **UNRESOLVED**

**MEASURED.** DEAD_CALM has no branch of its own, so it falls to the default
`rr >= 2.0` against a `tp_ratio` of **1.5**. No trigger quality can rescue it.
The tautology that justified retiring `valid_rr` still bars DEAD_CALM, through
a different function.

**Not introduced by Phase 6I, and not fixed by it.** Whether DEAD_CALM should
have a branch, a different `tp_ratio`, or no entry at all is a strategy-contract
question and belongs to review.

## 3.2 MICRO_SCALP admission turns on floating-point noise — **UNRESOLVED**

**MEASURED, from the verified dataset.** MICRO_SCALP's threshold is `rr >= 1.5`
and its `tp_ratio` is exactly `1.5`, so `rr` lands **on the boundary** and the
comparison is decided by representation error.

The candidate at **2026-08-06 08:00** computed
`rr = 1.4999999999999196` — below `1.5` by about `8e-14` — and was refused,
while three candidates at or just above `1.5` were admitted.

The diagnostic message compounds it: it reports `micro scalp quality too low
(quality=10.0, rr=1.5)`. Quality was 10.0 and passed; `rr` failed; and the
message prints the value that failed as `1.5`, the value it was required to
reach.

**This is why 3 candidates became signals rather than the 4 Phase 6A predicted.**
Pinned as an observation, not endorsed, and **not fixed** — changing a threshold
or a message is outside Phase 6I's scope.

---

# 4. Measured effect on the verified dataset

**MEASURED.** Current code, dataset SHA-256 `433b7e27…`, the same data behind
`baseline_004` and `baseline_005`.

| | Before (`baseline_005`) | After | Δ |
|---|---|---|---|
| Decisions | 15,735 | 15,735 | 0 |
| Reached L8 | 1,265 | 1,265 | **0** |
| Blocked at L8 | 1,265 | **1,262** | **−3** |
| **Signals** | **0** | **3** | **+3** |
| Pending orders / fills | 0 | 3 orders | +3 |
| L1, L2, L3, L4, L6, L7 blocks | — | **all identical** | 0 |

**The only funnel change is at L8: three decisions moved from blocked to
signal.** Every upstream layer blocks exactly what it blocked before.

## 4.1 The three newly admitted candidates

All MICRO_SCALP — the regime the retired gate made unenterable:

| Timestamp (UTC) | Regime | Side | Why it is now admitted |
|---|---|---|---|
| 2026-07-17 12:40 | MICRO_SCALP | SELL | `core_trigger` was already true; the retired `tp_ratio 1.5 >= 2.0` term no longer refuses it, and `rr >= 1.5` passes |
| 2026-08-12 09:25 | MICRO_SCALP | BUY | same |
| 2026-08-28 08:45 | MICRO_SCALP | SELL | same |

**Each was blocked solely by the retired gate**, as Phase 6A/6B measured. The
fourth (2026-08-06 08:00 BUY) is refused by the *second* gate on the
floating-point boundary described in §3.2 — not by anything Phase 6I changed.

## 4.2 The 11 pullback candidates did **not** become signals

**MEASURED, and this was the explicit requirement.** No pullback signal appears.
All 11 are MICRO_SCALP, where `allowed_styles = ["MOMENTUM"]`, so the pullback
candidate is never placed in `candidates` and cannot be selected. **The
regime/style restriction is frozen and still binds**, exactly as Phase 6C
Decision A requires.

## 4.3 An error in the first measurement, and its correction

The first replay computed a decisions fingerprint over **3** snapshots rather
than 15,735, because `ReplayConfig.capture_all_snapshots` defaults to `False`
and retains only signals. That value was **not comparable** to `baseline_005`
and is not reported. The measurement was re-run with
`capture_all_snapshots=True`; §4's figures are from that run.

A second artefact was also ruled out: a raw block-label counter showed
`L5_SWEEP` falling 4,075 → 2,441. That is a **counting difference, not a
behaviour change** — `backtest.baseline._BLOCK_TO_LAYER` folds
`L5_SWEEP_WAIT` (1,634) into `L5_SWEEP`, and `2,441 + 1,634 = 4,075`. The raw
counter did not apply the mapping.

---

# 5. Fingerprints and baseline discipline

**`baseline_004` and `baseline_005` are untouched, unmodified and not
re-pinned.** Neither was regenerated.

**Development evidence only**, current code over the verified dataset:

```
decisions_fingerprint BEFORE  e9421f30331e5b3bf1688fc8f74289248059692075b882e328d9ff3eb7825c75
decisions_fingerprint AFTER   127fd774d795b1ccdecbed40bca8348615d145161583aa9171258c809f13af3d
```

**The difference is caused entirely by the removal of the redundant gate.** The
fingerprint hashes, per decision, the layers cleared, the layer that blocked and
the stated reason. Three decisions changed from `blocked=L8_ENTRY, reason="Entry
triggers not all confirmed"` to a signal with `L8_ENTRY` in `layers_passed`.
Nothing else in the stream differs: the decision count, every upstream block
count and the L8-reached count are all identical.

The R1 regression fixtures are **unchanged** — 25/25 pass with their pinned
ledger fingerprints, because both fixtures run at `tp_ratio 3.0`, which already
satisfied the retired gate.

---

# 6. If a minimum RR is wanted later

**UNRESOLVED**, and deliberately left so. Phase 6C Decision B states the shape
the answer must take:

> A minimum reward-to-risk requirement is a statement about how the strategy is
> **configured**, not about an individual decision. Under fixed-R the target is
> `entry ± tp_ratio × R` by construction, so every trade in a regime realises
> that regime's `tp_ratio` as its target multiple, known before any price is
> read. The requirement therefore belongs where `tp_ratio` is chosen — a
> configuration invariant, checked once, not a runtime gate.

Two questions must be answered together, and neither is answered here:

1. **What is the minimum, and does one exist at all?** The retired `2.0` had no
   recorded rationale and was not carried forward.
2. **If a minimum is adopted, MICRO_SCALP and DEAD_CALM violate it at 1.5.**
   Either their `tp_ratio` changes or the minimum does. This is **DD5**.

Any such policy must be specified at the configuration / strategy-contract
level. Reintroducing a per-candidate comparison would recreate the tautology,
and `test_entry_triggered_is_not_conjoined_with_any_rr_verdict` now fails if it
is attempted.

---

# 7. Scope

**Changed:** `entry_engine.py` (the gate, the scoring bonus, the verdict field),
`main_production.py` (decision-record diagnostics), `backtest/baseline.py`
(defect observation now past tense), and tests.

**Not changed:** `tp_ratio` values, regime/style rules, candidate generation,
entry price, stop construction, target construction, `evaluate_entry_for_regime`
and its thresholds, sizing, execution, trade management, the broker surface,
`main.py`, `trade_manager`, and both baselines.
