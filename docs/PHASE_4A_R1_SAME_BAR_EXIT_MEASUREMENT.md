# R1 — same-bar exit eligibility: measurement and design

**Read-only.** No production, backtest, strategy or baseline file was modified.
Step 4 is not implemented. Invalidation, expiry, CHoCH override and
cross-session survival are untouched. The intrabar policy is neither modified
nor reinterpreted.

**Baseline:** `316b861`. **Scope:** R1 only — the `bar_time <= entry_time` skip
in `PaperBroker.on_bar`.

**Tag legend:** `[REPO]` original repository behaviour · `[PHASE_2A]` scaffolding
I added in `f39faa9` · `[MEASURED]` observed · `[DECISION]` explicit design
decision · `[CONSEQUENCE]` behavioural implication · `[UNRESOLVED]` still unknown.

---

## 1. Exact current behaviour

### Provenance

`[REPO]` `entry_engine.py`, `main_production.py`, `order_execution.py`,
`risk_manager.py` are original. `[PHASE_2A]` **every file in this report's scope
— `execution/paper_broker.py`, `execution/intrabar.py`, `execution/broker.py`,
`backtest/ledger.py`, `backtest/metrics.py`, `backtest/replay_engine.py` — is
scaffolding I added.** R1 is a defect in my own code, not in the original system.

### The fill path

`[PHASE_2A]` `PaperBroker.submit_market_order` fills against `execution_bar`'s
**open** and sets:

```
entry_price = fill_model.entry_price(side, execution_bar["open"], spec)
entry_time  = bar_time            # the execution bar's OPEN time
```

`[PHASE_2A]` `ReplayEngine.run` supplies `execution_bar = feed.next_bar_after(T)`.
At decision instant **T** (close of bar **N**) the execution bar is **N+1**.

### The skip

`[PHASE_2A]` `PaperBroker.on_bar` begins:

```python
for position in list(self._open):
    if bar_time <= position.entry_time:
        continue
    position.bars_held += 1
    resolution = resolve_intrabar(...)
```

`[PHASE_2A]` Replay event order per decision instant T:

1. `broker.on_bar(bar N)` — the bar that just closed;
2. `_decide(...)`;
3. `broker.submit_market_order(execution_bar = bar N+1)`.

`[CONSEQUENCE]` A position filled at bar **N+1**'s open is passed to `on_bar` at
the *next* decision instant with `bar_time == entry_time`, so the condition is an
**equality** in practice, and the bar is skipped. The position is first evaluated
on bar **N+2**.

`[CONSEQUENCE]` **`bars_held` is incremented after the skip**, so it is also not
incremented on the fill bar. This is a second, separate effect of the same line
and is the one that actually moves fingerprints (§7).

`[PHASE_2A]` The docstring justifies the skip as avoiding "double-count[ing] the
bar". **That reasoning is wrong.** A market fill occurs at the bar's open, so the
position genuinely exists for the whole of that bar; evaluating its range is
correct, not double-counting.

### Existing test coverage

`[MEASURED]` **No test covers the skip.** A repo-wide search for `entry_time`,
`same_bar` or fill-bar assertions in `tests/` returns only a hand-constructed
trade (`test_ledger_and_metrics.py:55`) and `test_time_stop`
(`test_paper_broker.py:250`), neither of which passes the fill bar to `on_bar`.
The behaviour is entirely unprotected.

---

## 2. Answers to the seven questions

### Q1 — Which existing market-order scenarios are affected?

Two distinct effects, and only the second bites today.

**(a) Exit outcomes.** Only positions whose **fill bar** (N+1) range covers the
stop or the target. Because a market fill happens at that bar's *open*, the bar
must traverse a full risk distance (for the stop) or a full reward distance (for
the target) within one M5 bar.

`[MEASURED]` **Zero of the two trades that exist.** These are the only trades
produced anywhere in the repository:

| Fixture | Side | Entry | SL | TP | Fill bar H / L | Would hit stop | Would hit target | Outcome changes |
|---|---|---|---|---|---|---|---|---|
| long | BUY | 2517.87 | 2508.73 | 2557.68 | 2521.33 / 2517.48 | No | No | **No** |
| short | SELL | 2182.34 | 2186.00 | 2158.15 | 2183.43 / 2181.19 | No | No | **No** |

Computed by calling the production `resolve_intrabar` with each position's own
side, stop, target and the broker's policy. Deterministic: run twice,
byte-identical output.

`[MEASURED]` `baseline_004` produced **zero trades**, so exit-outcome impact
there is provably nil.

**(b) `bars_held` — affects every position without exception.** Removing the skip
increments `bars_held` by exactly 1 for every position, whatever the price
action.

`[MEASURED]` The two fixture trades would go **23 → 24** and **19 → 20**.

`[CONSEQUENCE]` `bars_held` reaches `SimulatedTrade` (`ledger.py:267`), and
`SimulatedTrade.to_dict()` is `asdict(self)`, which `TradeLedger.fingerprint()`
hashes. It also feeds `BacktestMetrics.average_bars_held` (`metrics.py:237`).
**So the ledger fingerprint and metrics change even when no exit changes.**

`[CONSEQUENCE]` If `max_bars_held` were ever set, positions would time out one
bar earlier. `[REPO]` It is `None` in the baseline configuration, so that path is
currently inert.

### Q2 — Is `entry_time` equal to the bar timestamp?

`[PHASE_2A]` **Yes, exactly.** `entry_time = bar_time`, the execution bar's open
time. The guard is therefore an equality test in practice, never a strict
inequality, and it fires on exactly one bar per position — the fill bar.

`[CONSEQUENCE]` For a **market** fill the architecture's rule ("eligible during
the remainder of bar N") means the **whole** bar, because the fill is at the
open. There is no partial-bar exposure to model. `[CONSEQUENCE]` For a future
**limit** fill the fill occurs mid-bar and the exposure is a *fraction* of the
bar — a genuinely harder problem that belongs to Step 4, **not** to R1.

### Q3 — Does same-bar exit introduce new ambiguity?

`[CONSEQUENCE]` **For market fills, no new class.** The position exists from the
bar's open, so the full bar range legitimately applies and `resolve_intrabar` is
exactly the right tool, used unchanged with no new policy.

`[CONSEQUENCE]` What *is* new is a qualitatively different **event**: a position
that opens and closes inside one bar — a same-bar round trip. That is not an
ambiguity, but it is worth being able to see (Q5).

`[UNRESOLVED]` The partial-bar exposure problem for limit fills. Out of R1 scope.

### Q4 — Can `resolve_intrabar` deterministically resolve the three cases?

`[REPO]`/`[PHASE_2A]` Yes, all three, with no modification:

| Case | Result | Ambiguous? |
|---|---|---|
| entry → stop only | `hit_stop=True` | No |
| entry → target only | `hit_target=True` | No |
| entry → **both** | CONSERVATIVE resolves to **stop** | **Yes**, flagged and counted |

The third is deterministic *and* flagged, which is precisely the existing design:
resolve against the strategy, mark it, count it. No reinterpretation needed.

### Q5 — Does entry-vs-exit ordering need a counter separate from `ambiguous_exits`?

`[DECISION]` **Not a new ambiguity counter — but a new descriptive flag.**

- Numerically, `ambiguous_exits` already covers it: a fill-bar exit that hits
  both levels is ambiguous in exactly the existing sense.
- Qualitatively, a same-bar round trip is a different animal from an exit three
  bars later, and a result driven by same-bar exits would be more fragile than
  the count alone suggests.

Proposed: a `same_bar_exit: bool` on `SimulatedTrade` plus a
`same_bar_exits` count in metrics. **This is not the entry-vs-exit ambiguity
class** from the architecture document — that one arises only when a limit fills
mid-bar and belongs to Step 4.

### Q6 — Tests required

See §3.

### Q7 — Can baselines be preserved byte-for-byte?

`[MEASURED]` **Split answer, and the distinction matters:**

| Artifact | Byte-identical after R1? | Why |
|---|---|---|
| `baseline_004` — `decisions.jsonl`, `decisions_fingerprint` | **Yes** | Decisions are taken before execution; R1 cannot reach them |
| `baseline_004` — `ledger_fingerprint`, `metrics.json`, `run_fingerprint` | **Yes** | Zero trades: the ledger is empty and `average_bars_held` is `null` |
| `baseline_001/002/003` | **Yes** | Same — all zero-trade |
| **Phase 2A.1 fixture ledgers / metrics** | **No** | `bars_held` 23→24 and 19→20 changes `to_dict()`, hence the ledger fingerprint and `average_bars_held` |
| Phase 2A.1 fixture **exit outcomes** | **Yes** | Both still `CLOSED_TARGET` at the same bar and price |

`[CONSEQUENCE]` **R1 is not a no-op.** Every Phase 3A baseline artifact survives
byte-identically, but any fixture-derived ledger fingerprint does not. A claim of
"no behavioural change" would be false, and the commit must record before/after
fingerprints rather than asserting equivalence.

---

## 3. Test cases required before implementation

None exists today; all are new. **None touches strategy behaviour.**

**Direct unit tests — `tests/execution/test_paper_broker.py`**

1. A position filled on bar N whose bar N range covers the stop → closes on bar N at the stop.
2. Same for the target.
3. Fill bar covering **both** → CONSERVATIVE resolves to stop, `was_ambiguous=True`.
4. Fill bar covering **neither** → stays open, and `bars_held == 1` (the increment now happens).
5. Gap case: bar N opens already through the stop → exit at the open, matching the existing gap rule.
6. `bars_held` after N bars is exactly N, not N−1.
7. The timing invariant still holds: no fill or exit is ever attributed to a bar at or before `decision_bar_time` — `SimulatedFill.__post_init__` must still raise.
8. `max_bars_held` still fires at the configured count (guarding the off-by-one the increment introduces).

**Regression tests**

9. A full replay over `data/raw` reproduces `baseline_004` **byte-identically** — all four fingerprints and every summary artifact.
10. The Phase 2A.1 long and short fixtures still exit `CLOSED_TARGET`, at the same bar and price, with the same realised R. **`bars_held` and the ledger fingerprint are expected to change and must be asserted at their new values**, not at the old ones.
11. Determinism: two runs produce identical fingerprints.
12. The existing leakage suites still pass unchanged.

**Guard test**

13. Nothing in the diff touches `entry_engine.py`, `main_production.py` or any L1–L8 logic — assertable by the same AST/hash approach already used in `tests/integration/test_strategy_to_broker.py`.

---

## 4. Should R1 be a separately gated step?

`[DECISION]` **Separately staged and measured: yes. Gated behind a runtime flag:
no.**

**Staged, because** it is behavioural (§Q7) and must carry its own before/after
evidence rather than being absorbed into Step 4, where its effects would be
indistinguishable from the strategy change.

**Not flag-gated, because:**

- `[MEASURED]` exit-outcome impact is nil on every artifact that exists, so the
  before/after comparison is already obtainable without a switch;
- a permanent behaviour flag creates two code paths that both need testing
  forever, and dead configuration is a liability;
- the correct behaviour is not in doubt — a position filled at a bar's open
  exists for that bar. The current skip is a defect, not a policy.

`[UNRESOLVED]` If you would rather have a switch for sensitivity analysis, the
established precedent is `IntrabarPolicy`, whose alternatives exist precisely to
quantify fragility — a same-bar toggle could follow that pattern. That is your
call, not mine; I am not proposing it.

### Where R1 sits in the sequence

`[DECISION]` R1 should land **before** Steps 1–3, not after. Steps 1–3 claim
byte-identical reproduction of `baseline_004` as their pass criterion; if R1
lands afterwards it perturbs the very fingerprints those steps are being judged
against. Landing it first re-establishes a clean reference once, and — because
`baseline_004` has zero trades — that reference is unchanged for Phase 3A
artifacts anyway.

`[CONSEQUENCE]` R1 matters far more for Step 4 than for anything today. A
**market** fill at a bar's open must cross a full risk distance to stop out on
its fill bar. A **limit** fill happens at a price the bar has already reached,
with the stop beyond it in the direction price was already travelling —
`[MEASURED]` and 68 of 116 zone touches straddled the zone entirely. Same-bar
stop-outs should be expected to be common once limit fills exist, which is why
this must be fixed before they do.

---

## 5. Risks and unresolved items

**`bars_held` semantics change.** `[CONSEQUENCE]` Counting the fill bar as held
is defensible; so was not counting it. The change makes `average_bars_held`
increase by exactly 1 for every trade. Defensible either way, so it must be
stated in results rather than passed off as a bug fix with no consequences.

**`[UNRESOLVED]` Partial-bar exposure for limit fills.** Applying a whole bar's
range to a position that existed for only part of it overstates its exposure.
Out of R1 scope; must be resolved in Step 4.

**`[UNRESOLVED]` Whether `same_bar_exits` should also be surfaced per regime and
per session**, as other statistics are. A presentation question, not a
behavioural one.

**Weak regression cover.** `[MEASURED]` With zero trades in the baseline and two
in the fixtures, the regression suite can prove very little about exits. Items
1–8 in §3 carry essentially the whole burden of proving R1 correct.

---

*Measurement and design complete. No code changed, no baseline touched, nothing implemented. Stopping for review.*
