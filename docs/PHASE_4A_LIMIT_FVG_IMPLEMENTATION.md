# LIMIT_FVG — first control implementation

**This is a research control experiment, not a trading configuration.** Expiry,
zone invalidation and cross-session cancellation are **disabled**. That is a
deliberate control condition so the unmodified fill behaviour can be measured
once; it is **not** a policy and must never be represented as one.

> **Not safe for live trading as configured.** An order with no expiry and no
> invalidation would rest indefinitely against a real broker. `LIVE_TRADING_ENABLED`
> remains a literal `False` and nothing here changes that.

**Baseline before:** `a4f7141` (R1). **Specification:** `6df835d`.
**Evidence:** `1007721`.

## Tag legend

| Tag | Meaning |
|---|---|
| `[REPO]` | Original repository code (`c3cf4df` / `2186e66`) |
| `[PHASE_2A]` | Simulation scaffolding I added in `f39faa9` |
| `[DECISION]` | Strategy-owner decision, already recorded |
| `[EXPERIMENTAL CONTROL]` | Temporary research condition — **not** a decision |
| `[CONSEQUENCE]` | Follows from the above |
| `[UNRESOLVED]` | Still undetermined |

---

## 1. Semantics by classification

### Implemented from established decisions

| Semantic | Tag | Where |
|---|---|---|
| Momentum path is a resting `LIMIT_FVG` order | `[DECISION]` | spec `6df835d` |
| Limit price is the **FVG midpoint** | `[DECISION]` | `entry_engine` (already computed this way) |
| Pending order created on the formation/decision bar | `[DECISION]` | `replay_engine` → `submit_limit_order` |
| Reach test: BUY `bar_low <= limit`, SELL `bar_high >= limit` | `[DECISION]` | `PendingOrderIntent.is_reached_by` |
| Same-bar fill impossible; earliest fill is N+1 | `[DECISION]` + `[PHASE_2A]` | `PendingOrder.may_fill_on` / `mark_filled` |
| Filled position is eligible for exits on its fill bar | `[PHASE_2A]` (R1, `a4f7141`) | `PaperBroker.on_bar` |
| Exit resolution unchanged | `[PHASE_2A]` | `resolve_intrabar`, untouched |
| POI 50 % fill rule **not** imported | `[DECISION]` | — |

### Strategy-semantic changes — deliberate, and not bug fixes

**1. CHoCH entry-price override removed from the momentum path.** `[DECISION]`

`[REPO]` `_evaluate_momentum_entry` overwrote the FVG midpoint with
`m1[-1].close` whenever M1 CHoCH confirmed. `[REPO]` `detect_m1_choch` returns
that value as `choch_level` — the close of the candle that **broke** the swing,
i.e. a breakout price. `[MEASURED]` It sat outside the gap on **13 of 13**
occurrences, always on the far side (BUY above, SELL below), so a limit cannot
rest there.

`[CONSEQUENCE]` **This changes entry prices and therefore outcomes on those
setups. It is a strategy change, not an execution correction.** `[REPO]` The
pullback path keeps its own separate `m1[-2]` override, untouched — the change
is narrow and a test pins that narrowness.

**2. `price_in_fvg` removed from `core_trigger`.** `[DECISION]` (spec §3)

`[CONSEQUENCE]` `core_trigger` is now a four-way AND: `kill_zone AND
displacement_found AND fvg_found AND m1_choch_confirmed`. `price_in_fvg` is
still computed and still returned as a diagnostic — only its role as a gate is
gone.

`[MEASURED]` On the Phase 2A.1 long fixture this produces **one extra signal**,
which rests as a pending order and never fills, so the ledger and its pinned
fingerprint are unchanged.

### Experimental controls — temporary, not decisions

| Control | State | Why |
|---|---|---|
| **Expiry** | `DISABLED` `[EXPERIMENTAL CONTROL]` | `[UNRESOLVED]` — encodes how long a setup stays valid; selecting a value from the fill distribution would fit a parameter to an outcome |
| **Zone invalidation** | `DISABLED` `[EXPERIMENTAL CONTROL]` | `[UNRESOLVED]` — and `[MEASURED]` every zone-penetration rule available fires at or after the fill (117/117 for the 50 % rule), so none can protect the order |
| **Cross-session cancellation** | `DISABLED` `[EXPERIMENTAL CONTROL]` | `[UNRESOLVED]` — whether the DEAD-session prohibition binds a resting order or only a new decision is unanswered |

`[CONSEQUENCE]` `PendingState.EXPIRED`, `INVALIDATED` and `CANCELLED` exist in
the enum because the lifecycle is incomplete without them, but **no code path
currently produces them**. Tests pin that absence so a rule cannot appear
without the decision behind it being recorded first.

### Still unresolved

`[UNRESOLVED]` Expiry · zone invalidation · cross-session survival · minimum gap
size · cancellation conditions · whether the remaining four AND terms should
stay · the M1 bar-index disagreement between the two paths · partial-bar
exposure when a limit fills mid-bar.

`[UNRESOLVED]` **The RR tautology (E9/E10) is now on the binding path.** It was
latent while nothing could trigger; with `price_in_fvg` gone it is the next gate
an entry must pass, and in `tp_ratio < 2.0` regimes it cannot be passed. It was
explicitly out of scope here and is **not** touched.

---

## 2. Architecture

```
STRATEGY                         EXECUTION
--------                         ---------
entry_engine.get_entry_trigger
  -> entry_signal carries
     limit_price, zone bounds
        |
        v
main_production.analyze_entry
        |
        v
ReplayEngine  --builds-->  PendingOrderIntent  (core/types.py, broker-agnostic)
        |                         |
        |                         v
        +------------>  PaperBroker.submit_limit_order
                                  |
                                  v
                            PendingOrder  (owns lifecycle + timing guard)
                                  |
                       on_bar:  A maintenance (empty -- control)
                                B fill attempt   (bars > formation only)
                                C exits          (R1: includes the fill bar)
                                  |
                                  v
                        SimulatedPosition -> TradeLedger -> metrics
```

`[CONSEQUENCE]` Execution never calls back into the strategy. The strategy
describes a resting price; it is never asked whether something filled.

`[PHASE_2A]` The no-look-ahead invariant is enforced **on the domain object**:
`PendingOrder.mark_filled` raises `DomainInvariantError` for any bar at or
before formation, mirroring `SimulatedFill.__post_init__`. Callers are not
trusted to check.

---

## 3. Lifecycle states and provenance

`[CONSEQUENCE]` The research layer can distinguish, per order: **created**,
**still waiting**, **reached but unfilled** (capacity-denied), **filled**, and
the resulting **position exit**.

`pending_statistics.json` records for every order: formation time, zone bounds,
midpoint, side, time to first reach, time to fill, fill bar and price, session
at formation and at fill, and whether the fill crossed a session, a daily
boundary or a weekend. Realised R continues to come from the ledger, computed
from the **actual fill**, never from the strategy's nominated price.

---

## 4. Files changed

| File | Provenance | Change |
|---|---|---|
| `core/types.py` | Phase 0/1 | `PendingOrderIntent` added |
| `execution/broker.py` | `[PHASE_2A]` | `PendingState`, `PendingOrder` |
| `execution/paper_broker.py` | `[PHASE_2A]` | `submit_limit_order`, `_fill_pending`, `_open_position` extracted, phases wired into `on_bar` |
| `backtest/replay_engine.py` | `[PHASE_2A]` | builds and submits the intent; exposes `pending_orders` |
| `backtest/baseline.py` | `[PHASE_2A]` | `pending_statistics` artifact |
| `entry_engine.py` | **`[REPO]`** | **the two strategy changes above** |
| `main_production.py` | **`[REPO]`** | carries `limit_price` and zone bounds on `entry_signal` |

`[CONSEQUENCE]` Two original-repository files are modified. Both changes are
authorised and recorded; neither is presented as a correction.

---

*First LIMIT_FVG control experiment. No optimisation, no parameter selection, no profitability claim.*

---

## 5. Control experiment — real XAUUSD dataset

Dataset `433b7e27…`, 15,735 decisions, unchanged replay configuration.

| Metric | Value |
|---|---|
| L8 candidates (reached L8) | **1,265** |
| **Pending orders created** | **0** |
| Pending filled | 0 |
| Fill rate | undefined (no orders) |
| Still waiting / reached-but-unfilled | 0 / 0 |
| Expired / invalidated / cancelled | 0 / 0 / 0 (controls disabled) |
| Time-to-fill distribution | no data |
| Session-crossing / daily-boundary / weekend fills | no data |
| Fills during Dead or Closed | no data |
| Exits | 0 |
| Ambiguous entry / exit cases | 0 / 0 |
| Trade count | **0** |
| `ledger_fingerprint` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `run_fingerprint` | `1276a31f673a5a82b2879ea5113b12e486da0d2491d03127b30370fd59f2d991` |
| Leakage suites | **PASS** (52 tests, incl. real-data mutation) |

`[MEASURED]` **Every artifact is byte-identical to `baseline_004`**, including
the 15,735-line decision stream, the layer funnel and all fingerprints. The
before/after comparison is therefore exact: **this implementation changed
nothing on the real dataset.**

### Why zero — and it is not the pending machinery

`[MEASURED]` Removing `price_in_fvg` lets **4** decisions satisfy the four-way
`core_trigger` — all MICRO_SCALP, all London session:

| Formation (UTC) | Regime | Session | Side |
|---|---|---|---|
| 2026-07-17 12:40 | MICRO_SCALP | London | SELL |
| 2026-08-06 08:00 | MICRO_SCALP | London | BUY |
| 2026-08-12 09:25 | MICRO_SCALP | London | BUY |
| 2026-08-28 08:45 | MICRO_SCALP | London | SELL |

`[REPO]` But an entry signal requires `entry_triggered = core_trigger AND
valid_rr`, and `[REPO]` MICRO_SCALP carries `tp_ratio = 1.5` while
`valid_rr = rr >= 2.0` with `rr ≡ tp_ratio`. `[CONSEQUENCE]` All four are
rejected at the same gate, with the same reason, so the funnel is unchanged and
no intent is ever constructed.

`[CONSEQUENCE]` **E9/E10 has moved from latent to measured as binding.** Phase 3A
established the tautology exists; Phase 4A's diagnostics showed it never bound
because `raw_triggered` failed first. With `price_in_fvg` gone, `raw_triggered`
now succeeds four times and the RR gate is what rejects them. This is the causal
evidence the phase sequence was built to produce.

`[UNRESOLVED]` The RR tautology was explicitly out of scope and was **not**
touched. Bypassing `valid_rr` would have been a second, unauthorised strategy
change, and would have manufactured orders the production logic does not permit.

### What this experiment does and does not establish

**Establishes:** the pending-order path is implemented, tested and inert; it
introduces no change to the real-data decision stream; leakage and determinism
hold; and the next binding constraint is identified precisely.

**Does not establish:** anything about fill behaviour on real data — no order
was created, so every fill-related measurement is empty. **Nothing whatsoever
about profitability.** The 25 lifecycle tests exercise the machinery on
constructed bars; the real dataset has not exercised it at all.
