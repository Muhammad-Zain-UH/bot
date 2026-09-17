# Momentum entry specification — resting LIMIT_FVG

**Documentation only.** No code was changed, no baseline touched, no backtest
run. Nothing here is implemented.

**Baseline:** `9ea0c5d`. **Diagnostics relied on:** `6c63b14` (FVG zone/price
test), `c3f130e` (forward replay), `11c074c` (`raw_triggered`).

**Strategy-owner decision, recorded:** the momentum path is a **RESTING
LIMIT_FVG** entry. Detect a fresh M5 FVG → treat it as the zone → place a
pending limit order → wait for price to return → fill only when the order price
is actually reached → manage expiry and invalidation explicitly → no trade if
price never returns.

### How to read this document

Every statement carries one of these tags. Nothing is asserted without one.

| Tag | Meaning |
|---|---|
| **[REPO]** | Established fact about the current code, verifiable by reading it |
| **[MEASURED]** | A Phase 4A measurement result |
| **[DECISION]** | An explicit strategy-owner decision |
| **[CONSEQUENCE]** | Follows necessarily from a [DECISION] plus a [REPO] fact |
| **[UNRESOLVED]** | **Strategy-owner decision / experimental parameter — not chosen here** |

**No parameter in this document was selected by looking for a value that
maximises trades or touches.** Where a value cannot be derived from an existing
repository requirement, it is left [UNRESOLVED].

---

## 1. FVG formation

**Formation bars.** **[REPO]** `entry_engine.detect_fvg` uses exactly the three
most recent closed M5 bars: `left = m5[-3]`, `middle = m5[-2]`, `right = m5[-1]`.
It does not scan backward for older gaps.

**Bullish (BUY).** **[REPO]** `gap_low = left.high`, `gap_high = right.low`;
valid when `gap_high > gap_low` **and** the middle candle is bullish
(`close > open`).

**Bearish (SELL).** **[REPO]** `gap_low = right.high`, `gap_high = left.low`;
valid when `gap_high > gap_low` **and** the middle candle is bearish
(`close < open`).

**Minimum size.** **[REPO]** `entry_engine` imposes **none**. **[MEASURED]**
Observed zone widths across the 117: min **$0.01**, median **$0.94**, max
**$10.39** — the median being about 0.02 % of gold's price in this period.
**[UNRESOLVED]** Whether a minimum applies, and what it is. `poi_engine` uses
`>= 3` on its own M15 gaps, but that is a different detector on a different
timeframe and importing it would be an unspecified change (see §6).

**Freshness / unfilled at detection.** **[CONSEQUENCE]** A gap detected from the
three most recent bars is **fresh by construction**: no bar exists after its
right bar, so nothing can have filled it. No freshness test is required at
detection, and any such test would be vacuous. **[REPO]** This is why the
current `price_in_fvg` cannot be a retracement check — there is nothing yet to
have retraced.

**Detector defect to be addressed.** **[REPO]** When `gap_valid` is false,
`detect_fvg` returns `fvg_found: False` **but still returns `zone_low` and
`zone_high`** (the inverted gap) with `midpoint: None`
(`entry_engine.py:292`). **[MEASURED]** The caller consumed those bounds without
checking the flag, producing `price_in_fvg = True` in 943 cases where no FVG
existed. **[CONSEQUENCE]** Under this specification the zone is only defined
when `fvg_found` is true; a consumer must never read bounds otherwise.

## 2. Entry location

**Current behaviour.** **[REPO]** `confirmed_entry_price` is set to
`m5[-1].close`, then overridden to `fvg["midpoint"]` whenever a midpoint exists,
then overridden again to `m1[-1].close` when M1 CHoCH confirms
(`entry_engine.py:579-583`). **[MEASURED]** Across the 117 FVG-positive cases:
104 took the midpoint, 13 took the CHoCH override.

**Midpoint calculation.** **[REPO]** `midpoint = gap_low + (gap_high - gap_low) / 2`
— the arithmetic centre of the zone, and `None` when the gap is invalid.

**Is the entry exactly the midpoint?** **[UNRESOLVED]** The owner decision fixes
*that* a limit rests at a defined location, not *which* location. At least three
candidates exist, and none is derivable from the repository:

- the **midpoint** (current behaviour);
- the **proximal edge** — the boundary price reaches first (`zone_high` for BUY,
  `zone_low` for SELL), which fills earliest and shallowest;
- the **distal edge** — the far boundary, which fills only on deeper penetration.

**[MEASURED]** Relevant but not decisive: 68 of 116 touching bars straddled the
zone entirely, so all three locations would frequently be crossed within a single
bar. This makes the choice *less* separable on historical data, not more.

**May CHoCH override the midpoint?** **[UNRESOLVED]**. **[MEASURED]** The CHoCH
override is the **only** mechanism by which the entry leaves the zone — 0 of 13
CHoCH-sourced entries were inside the FVG, against 104 of 104 midpoint-sourced.
**[CONSEQUENCE]** Under a resting-limit design an override that moves the order
*outside* the zone contradicts the premise that the FVG is the zone being waited
for. If the override is retained, the specification must state its rationale and
its price source; **no rationale for it exists anywhere in the repository**
(no comment, docstring, test or design document).

**Must the entry remain inside the FVG?** **[UNRESOLVED]**, and it is the same
question as the one above. If the answer is yes, the CHoCH override must be
removed or constrained; if no, the override needs a stated purpose.

**Bar-index inconsistency to resolve.** **[REPO]** The pullback path uses
`m1[-2].close` for its CHoCH override; the momentum path uses `m1[-1].close`
(`entry_engine.py:497` vs `583`). No reason is recorded. **[UNRESOLVED]**

## 3. Trigger semantics

**`price_in_fvg` is removed from the trigger.** **[DECISION + CONSEQUENCE]** The
owner's instruction is to remove its current interpretation unless the
specification gives it an independent purpose. Under a resting-limit design it
has none at signal time:

- asserting price is *already* in the zone contradicts the purpose of a resting
  order — the order exists precisely because price is not there yet;
- asserting the zone is *unfilled* is vacuous, because a freshly formed gap is
  unfilled by construction (§1);
- **[MEASURED]** as implemented it tested `m5[-2].close`, the middle candle of
  the gap itself, which was outside the zone in 103 of 116 cases at a median
  1.1× the zone width.

**[CONSEQUENCE]** `core_trigger` becomes a four-way AND:

```
kill_zone AND displacement_found AND fvg_found AND m1_choch_confirmed
```

**[UNRESOLVED]** Whether each of those four remains is a separate decision this
specification does not make. **[MEASURED]** None of them was ever the *sole*
blocker across the 1,265 L8 decisions — only the FVG terms were — so removing
`price_in_fvg` alone cannot be assumed to change the outcome.

**What creates the pending order.** **[DECISION]** The pending order is created
at the decision instant on which the four-way trigger is satisfied and a valid
FVG exists. That instant is the **formation** event.

**Formation is not touch.** **[CONSEQUENCE]** Two distinct events must never be
conflated:

| Event | When | What it does |
|---|---|---|
| **Formation** | decision bar, from `m5[-3..-1]` | creates the pending order |
| **Touch / fill** | a **strictly later** bar | may fill the pending order |

The current code has only the first and treats it as though it were the second.

## 4. Pending-order lifecycle

**[REPO]** None of this exists. `order_execution.OrderType` has exactly two
members, `BUY` and `SELL`; `create_order` treats an order as filled at signal
time; there is no `BUY_LIMIT`, `SELL_LIMIT`, `TRADE_ACTION_PENDING`,
`pending_order` or `limit_price` anywhere. `PaperBroker` exposes only
`submit_market_order`. Everything below is therefore new machinery.

**Pending state.** **[DECISION]** An order sits pending from its formation bar
until exactly one terminal event occurs: **filled**, **invalidated**,
**expired**, or **cancelled**. The state must be explicit and recorded, not
implied by absence.

**Fill event.** **[DECISION]** A pending order fills only when the order price is
actually reached by a bar strictly after formation. **[UNRESOLVED — and this is
the most consequential open parameter]** what "reached" means on bar data:

- **[MEASURED]** 68 of 116 touching bars straddled the zone entirely — price
  crossed the whole gap within one bar. A bar whose range covers the limit price
  is evidence price traded there; it is **not** proof an order at that price
  would have filled at that price.
- **[REPO]** The codebase already faces this ambiguity for stops and targets and
  resolves it explicitly via `execution/intrabar.py::IntrabarPolicy`
  (CONSERVATIVE / OPTIMISTIC / MIDPOINT_HEURISTIC / TICK_DATA, with `TICK_DATA`
  raising rather than silently falling back). **[CONSEQUENCE]** A limit fill
  needs an equivalent stated policy, including the case where the limit price and
  the stop are both covered by the same bar.
- **[REPO]** No tick data exists for this dataset, so `TICK_DATA` is unavailable.

**Cancellation.** **[UNRESOLVED]** Whether any condition other than invalidation
or expiry cancels a resting order — for example a bias flip at L1, or a new FVG
forming in the opposite direction.

**Invalidation.** **[UNRESOLVED]** What invalidates the zone. **[REPO]**
`poi_engine` rejects an FVG once `fill >= 0.5`. **[MEASURED]** Applying that
criterion to these zones, **116 of 117 would be invalidated**, with the median
zone filling **completely** (max fill 1.000). **[CONSEQUENCE]** Any invalidation
rule stricter than "filled" will terminate most of these orders, and adopting
poi's 0.5 would be importing an M15 POI rule into L8 — explicitly out of scope
here (§6).

**Expiry.** **[UNRESOLVED — EXPERIMENTAL PARAMETER]** No expiry period exists in
the repository and none is chosen here. **[MEASURED]** For description only, and
explicitly **not** a recommendation: touches occurred within 1 bar in 50.4 % of
cases, 6 bars in 72.6 %, 24 bars in 85.5 %, and eventually in 99.1 %; the slowest
was 1,464 bars. **Selecting an expiry because it maximises touches would be
choosing a parameter from an outcome**, which this phase exists to avoid.

**Price crossing without a fill.** **[CONSEQUENCE]** Under a conservative fill
policy a bar may cross the order price and still not be treated as a fill. The
specification must define whether such an order remains pending, and this must be
decided **with** the fill policy, not separately — they are one decision.

**Across sessions.** **[UNRESOLVED]** Whether a pending order survives the daily
break and the weekend. **[REPO]** The dataset has 61 daily breaks of ~2 h and 15
weekend gaps; **[REPO]** `risk_manager` defines a `Dead` session and L8 currently
requires a kill zone (08–10, 12–14 UTC) at formation, but nothing states whether
that constraint applies at fill time too.

## 5. Time semantics

**Formation timestamp.** **[DECISION + REPO]** The FVG is complete when its
right bar closes. The formation bar is the last M5 bar with
`open_time + 5min <= decision_time` — the bar the detector used as `m5[-1]`.

**Subsequent bars only.** **[DECISION]** Retracement and fill are evaluated
strictly on bars **after** the formation bar. **[REPO]** This matches
`poi_engine._zone_touched`, which scans `range(after_idx + 1, len(frame))`, and
it is the rule the Phase 4A forward replay already used.

**No look-ahead.** **[REPO]** The replay invariant
`bar.open_time + timeframe.duration <= T` is unchanged and continues to govern
what the strategy can see at any decision instant. A pending order introduces no
exception: it is created from information available at formation and resolved by
bars that arrive afterwards.

**Which bar may fill.** **[CONSEQUENCE]** The earliest bar eligible to fill is
`formation_idx + 1`. **[REPO]** `execution/broker.py::SimulatedFill` already
enforces `entry_bar_time >= decision_time` and raises `DomainInvariantError`
otherwise, so the existing guard extends to pending fills without weakening.

## 6. Relationship to `poi_engine` — documented, not unified

**[DECISION]** The two FVG implementations are **not** unified in this
specification, and no M15 POI rule is imported into L8 unless stated explicitly
above (none is).

| Property | `entry_engine` (L8) | `poi_engine` (L6) |
|---|---|---|
| Timeframe | M5 | M15 |
| Formation | fixed last 3 bars | scans `tail(10)`, **adjacent pairs** (2-candle) |
| Bullish | `left.high` → `right.low`, middle bullish | `curr_low > prev_high` |
| Bearish | `right.high` → `left.low`, middle bearish | `prev_low > curr_high` |
| Bounds | `zone_low` / `zone_high` (returned even when invalid) | `fvg_top` / `fvg_bottom` (`None` when absent) |
| Minimum size | none | `>= 3` (comment says pips; value is price units) |
| Touch | none | `_zone_touched` — wicks, post-formation |
| Fill | none | `fill_percent`, rejects at `>= 0.5` |
| Polarity | price required **in** the zone | **untested** rewarded (+30) |
| Midpoint | computed | not computed |
| Consumer | `core_trigger` (L8) | `score_poi` / `identify_poi` (L6) |

**[CONSEQUENCE]** The one thing L8 genuinely lacks — a definition of "traded into
the zone" — already exists as `_zone_touched`, and the Phase 4A forward replay
called it directly on M5 without modification. **[UNRESOLVED]** Whether L8 should
call it, reimplement it, or share a common primitive.

## 7. Costs and execution

**Signal price vs execution price.** **[CONSEQUENCE]** These must remain
distinct fields and must never be conflated. **[REPO]** The strategy's
`confirmed_entry_price` is the price the signal nominates; the simulated fill is
produced by the broker. **[REPO]** Conflating them is already on record as **Q1**
— the strategy prices risk against an entry it is not filled at, which is why
realised R differs from reported RR on every trade.

**Phase 3A assumptions are preserved unchanged** unless a future experiment
states otherwise. **[REPO]** Spread **2.0 pips, ASSUMED** (the broker quoted 3.9
pips live, so it is not conservative); slippage **0**; commission **0**; fixed
**0.01** lots; `risk_manager` not consulted; CONSERVATIVE intrabar policy;
maximum 3 open positions; M5 decision cadence.

**No profitability assumption is introduced.** **[MEASURED]** The excursion
figures in `docs/PHASE_4A_FORWARD_REPLAY_TOUCH.md` §6 record favourable movement
only — no adverse side, no stop, no target, no costs — and are explicitly not a
performance estimate.

**[CONSEQUENCE]** The latent RR tautology (E9/E10) becomes **reachable** the
moment an entry can actually fire in a `tp_ratio < 2.0` regime. It is not
addressed here and remains recorded, but it will bind once this path produces
entries.

---

## Design table

| Component | Current implementation | New intended specification | Requires code change? |
|---|---|---|---|
| **FVG detection** | 3 most recent M5 bars; no minimum size; returns bounds even when invalid | Same 3-bar detection. Bounds defined **only** when `fvg_found`. Minimum size [UNRESOLVED] | **Yes** — stop returning bounds for an invalid gap |
| **FVG validation** | `gap_high > gap_low` + middle-candle direction | Unchanged | No |
| **Entry price** | `m5[-1].close` → `fvg.midpoint` → `m1[-1].close` under CHoCH | A single defined limit level [UNRESOLVED: midpoint / proximal / distal] | **Yes** |
| **`price_in_fvg`** | `m5[-2].close` tested against the zone; term in the AND | **Removed** — no independent purpose under a resting design | **Yes** |
| **Pending order** | Does not exist | Explicit pending state with four terminal outcomes | **Yes — new machinery** |
| **Fill detection** | Not applicable; fills at next bar open | Fill only when the order price is reached on a strictly later bar, under a stated intrabar policy [UNRESOLVED] | **Yes — new machinery** |
| **Invalidation** | Does not exist | Explicit rule [UNRESOLVED] | **Yes — new machinery** |
| **Expiry** | Does not exist | Explicit rule [UNRESOLVED — EXPERIMENTAL PARAMETER] | **Yes — new machinery** |
| **CHoCH override** | Replaces entry with `m1[-1].close`; only route out of the zone | [UNRESOLVED] — retain with a stated rationale, constrain, or remove | **Yes if changed** |
| **POI relationship** | Two unrelated detectors | Documented, **not unified**; `_zone_touched` is the candidate shared primitive [UNRESOLVED] | **No** (not in this specification) |

---

## Unresolved decisions — what you still need to decide

| # | Decision | Why it cannot be derived |
|---|---|---|
| 1 | **Limit price location** — midpoint, proximal edge, or distal edge | Owner decision fixed the design, not the level; the repo records no rationale |
| 2 | **Fill semantics on bar data** — what counts as "reached", and what happens when the limit and the stop fall in the same bar | No tick data; 68/116 bars straddled the zone; `IntrabarPolicy` shows the codebase treats this as an explicit choice |
| 3 | **Invalidation rule** | poi's `fill >= 0.5` is an M15 POI rule; importing it is out of scope and would terminate 116/117 |
| 4 | **Expiry** | No repository basis. **Must not be chosen from the touch distribution** |
| 5 | **CHoCH override** — keep, constrain, or remove | It is the only mechanism moving the entry outside the zone; no rationale recorded |
| 6 | **Minimum gap size** | `entry_engine` has none; `poi_engine`'s `>= 3` is a different detector and carries the pips/dollars unit defect |
| 7 | **Cancellation conditions** beyond invalidation and expiry | Nothing in the repo suggests any |
| 8 | **Survival across the daily break and weekend** | Kill-zone constraint at formation is documented; nothing states whether it applies at fill |
| 9 | **Do the other three AND terms remain?** (`kill_zone`, `displacement_found`, `m1_choch_confirmed`) | None was ever a sole blocker; removing `price_in_fvg` alone may change nothing |
| 10 | **M1 bar index** for the CHoCH override — `[-1]` or `[-2]` | The two paths disagree with no recorded reason |

Decisions **1 and 2 are blocking**: no implementation can begin without them.

---

## Production files and functions that would require modification

Listed for planning. **None is modified by this document.**

**Strategy**

- `entry_engine.py::detect_fvg` — stop returning bounds when `fvg_found` is false; minimum size if decision 6 adds one
- `entry_engine.py::_evaluate_momentum_entry` — remove `price_in_fvg`; reduce `core_trigger` to four terms; define the limit level; resolve the CHoCH override
- `entry_engine.py::get_entry_trigger` — return a pending-order intent rather than an immediate trigger
- `main_production.py` L8 block (≈ lines 983–1010) — emit and track a pending order instead of an immediate `ENTRY_SIGNAL`; revisit `confirmed_m5_close`

**Simulation / execution**

- `execution/broker.py` — `Broker` protocol, `FillStatus`, `SimulatedFill` pending states
- `execution/paper_broker.py` — `submit_limit_order`, pending processing inside `on_bar`, expiry and invalidation
- `execution/intrabar.py` — a stated limit-fill policy alongside the stop/target one
- `backtest/replay_engine.py` — carry pending orders across decision instants
- `backtest/ledger.py` / `backtest/metrics.py` — record formation→fill provenance and pending outcomes
- `core/signal_log.py` — columns for pending state (schema version bump)

**Out of scope, noted only**

- `order_execution.py::OrderType` — would need a LIMIT member before any live path. **Live trading stays disabled regardless.**

---

## Proposed implementation sequence

Each step is small, independently testable, and measured against the immutable
Phase 3A baseline. **Not executed.**

**Steps 1–3 change no strategy behaviour.** They add machinery that nothing yet
uses, so the full replay must reproduce `baseline_004` **byte-identically** —
decision stream, fingerprints and all. That is a strong regression guarantee and
should be an explicit pass criterion.

| Step | Change | Pass criterion |
|---|---|---|
| **0** | Resolve blocking decisions 1 and 2 | — |
| **1** | Pending-order support in `PaperBroker` (submit, pending state, fill/expiry/invalidate/cancel) + unit tests. Nothing submits one | Baseline reproduces byte-identically |
| **2** | Replay engine carries pending orders across decisions | Baseline reproduces byte-identically |
| **3** | Ledger/metrics record pending provenance and outcomes | Baseline reproduces byte-identically |
| **4** | **Strategy change, isolated:** remove `price_in_fvg`; emit a pending-order intent | First expected divergence. Re-measure the funnel; determinism and leakage suites must pass |
| **5** | Re-measure the funnel and the block distribution | Identify the next binding constraint — it is unmeasured and should not be assumed |
| **6** | Only then revisit the RR tautology (E9/E10), now reachable | Separate isolated experiment |

Fix the `detect_fvg` invalid-bounds defect (§1) either inside step 4 or as its
own step before it — it is a correctness fix independent of the design choice,
though it will change the decision stream and must therefore be measured, not
bundled silently.

---

*Specification complete. No code changed, no baseline touched, nothing implemented. Stopping for review.*
