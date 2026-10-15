# Phase 4B — I1: Partial Exit Representation

**Design and evidence only.** No production Python, test, baseline,
`core/trade_model.py` or canonical specification is changed. Nothing is
implemented. `baseline_004` remains **FROZEN**.

**Question (I1):** how should a canonical position that partially closes at 1R
and later closes its remainder be represented?

**Why it blocks:** the canonical model produces **two exits per position**; the
backtest can represent **one**.

## Evidence labels

| Label | Meaning |
|---|---|
| **[REPO]** | Established by repository code at `9792de7` |
| **[MEASURED]** | Established by running existing code read-only |
| **[DECISION]** | A design choice proposed for review — not implemented |
| **[UNRESOLVED]** | Cannot be settled from existing evidence |

---

# A. Current Representations

## A.1 `core.trade_model` — the canonical domain

**[REPO]** `TradeState` (frozen) carries geometry, quantity as integer steps,
milestone flags, both stop states, lifecycle, closure reason and fill,
`pending_close_reason`, `last_evaluated_time` and `anomalies`.

| Lifecycle assumption | Consequence |
|---|---|
| One position, quantity falls (spec 8.2) | A partial is **not** a new position |
| `steps_at_entry` immutable, `steps_remaining` monotonically non-increasing | Both are needed to reconstruct what was closed |
| `closure_fill_price` is **singular** | The domain records the **final** fill only; the partial's price is **not stored** |
| **No identity field** | See §E — the canonical model cannot name the position it describes |

**[REPO] First contradiction.** `TradeState` has no `position_id`, and
`closure_fill_price` is one value. The domain therefore cannot, by itself,
reconstruct a two-exit history. Whatever representation is chosen, the partial's
executed price must be retained **outside** `TradeState`, by the adapter.

## A.2 `execution/broker.py` — `SimulatedPosition`

**[REPO]** Fields (`:249-264`):

```
position_id, symbol, side, volume, entry_price, stop_loss, take_profit,
entry_time, state, exit_price, exit_time, exit_reason, was_ambiguous_exit,
bars_held, fill, metadata
```

| Assumption | Evidence |
|---|---|
| `volume` is **fixed** at open | No code assigns it after construction |
| Exactly **one** exit: `exit_price`, `exit_time`, `exit_reason` | Singular fields |
| `risk_distance = abs(entry_price - stop_loss)` | Property, recomputed from the **current** stop |
| `PositionState` has five closed states and no partial state | `:56-64` |

**[REPO] Note on `risk_distance`.** It reads the *current* `stop_loss`. If a
stop is ever moved to breakeven, `risk_distance` becomes ~0 and every downstream
`risk_amount` and `r_multiple` collapses. Nothing moves the stop today, so this
is latent — but it becomes live the moment the canonical ladder is wired.

## A.3 `backtest/ledger.py` — `SimulatedTrade`

**[REPO]** 31 fields, all scalar (`:139-175`): identity and outcome; six
timestamps; entry price and reference; stop, target; **one** `exit_time`, **one**
`exit_price`, **one** `exit_reason`, **one** `was_ambiguous_exit`; `quantity`;
`price_risk`, `gross_pnl`, `commission`, `slippage_cost`, `net_pnl`,
`risk_amount`, `r_multiple`, `bars_held`; four strategy labels and `metadata`.

**[REPO]** `to_dict()` is `asdict()` — flat, JSON- and CSV-serialisable.

## A.4 `trade_from_position` — the producer

**[REPO]** (`:196-272`) One closed `SimulatedPosition` → exactly one
`SimulatedTrade`:

```
trade_id   = position.position_id          # identity is ALIASED, not derived
gross_pnl  = price_move(exit_price) * money_per_price_unit(position.volume)
risk_amount= money_for_price_distance(risk_distance, position.volume)
r_multiple = net_pnl / risk_amount
bars_held  = position.bars_held
```

**[REPO]** It raises if the position is still open, so a record exists only at
terminal state.

## A.5 `TradeLedger` — the collection

**[REPO]** `record()` appends; `trades` returns the list; `completed_trades`
filters by outcome; `write_jsonl` writes one JSON object per line;
`fingerprint()` hashes `[t.to_dict() for t in self._trades]` (`:359-372`).

**[REPO] Second contradiction.** The fingerprint hashes the **whole dict**, so
*adding a field* to `SimulatedTrade` changes every ledger fingerprint in the
repository, whether or not any behaviour changed.

## A.6 `main_production` / execution

**[REPO]** A trade is a **dict**: `trade_id`, `order_id`, `entry_price`,
`stop_loss`, `take_profit`, `position_type`, `entry_time`, `status`,
`position_size` (lots), `state: None`. Held in `_OPEN_TRADES`, persisted by
`trade_persistence`. **No exit fields at all** — production has never recorded a
closed trade (`log_closed_trade` and `save_closed_trade` are imported and never
called).

## A.7 `order_execution`

**[REPO]** An order dict with `position_size` written once, three
`exit_1_x: {triggered, price}` sub-dicts, and `status` doubling as the milestone
marker. `PARTIAL` is a **status**, never a quantity.

## A.8 `trade_manager`

**[REPO]** `trade_state` carries `position_size` as a **fraction**
(1.0 → 0.5 → 0.0) with no link to lots, plus `current_sl`, `sl_status` and two
milestone flags. It is the only existing implementation that represents a
partially closed position at all — as a fraction, in memory, with no execution
record.

## A.9 Consumers

| Consumer | Uses | Effect of a second row per position |
|---|---|---|
| `backtest/metrics.py:166-214` | `len(trades)`, `completed`, `wins`/`losses` by `net_pnl`, `r_values`, `ambiguous`, `average_bars_held`, `by_outcome`/`by_direction`/`by_regime`/`by_setup` | **Trade count doubles; win rate skews** — a 1R partial is always a win, so pairing it with a losing remainder reports 50 % where one position broke even. `bars_held` would be averaged twice |
| `backtest/baseline.py:918-951` | `trade_ledger.json`, a CSV via `pd.DataFrame`, `ledger_fingerprint` in `run_fingerprint.txt` | CSV requires flat columns; fingerprint changes on any field change |
| `backtest/runner.py:119,170,232` | metrics, `trades.jsonl`, console summary | Same |
| `tests/integration/test_r1_same_bar_regression.py` | `assertEqual(len(self.ledger.trades), 1)`, pinned fingerprints, pinned `bars_held` | **Breaks on a second row; fingerprint breaks on any field change** |
| `tests/backtest/test_determinism.py:118` | metrics over `ledger.trades` | Recomputed, not pinned |
| Production reporting | — | **None exists** |

---

# B. Canonical Lifecycle — the worked example

**Using the specification exactly as written. No semantics are changed.**

Entry: BUY 1.00 lot at 2450.00, original stop 2420.00, `tp_ratio` 3.0.
**[REPO]** `volume_step = 0.01`, so 1.00 lot = **100 steps**, and
`floor(100 / 2) = 50` steps = **0.50 lots** — the partial is exactly half.

```
R      = |2450.00 - 2420.00| = 30.00
M1R    = 2480.00      M2R = 2510.00      TARGET = 2540.00
```

| After | Domain state | What must exist **outside** the domain |
|---|---|---|
| **Creation** | `steps_at_entry=100`, `steps_remaining=100`, `milestones_consumed={}`, stop `ORIGINAL` @2420, `OPEN` | Position identity; the fill's provenance (decision time, bar times, reference price) |
| **Event 1 — price reaches 1R** | `M1R` consumed; `PartialCloseRequest(50)`; `StopModifyRequest(2450.00, BREAKEVEN)`; still `OPEN`, `steps_remaining` **still 100** until confirmed | The request itself |
| **Event 1 confirmed** | `steps_remaining=50`; `stop_state_confirmed=BREAKEVEN` @2450 | **The partial's executed price, time and quantity — the domain does not store them** |
| **Event 2 — remainder runs** | unchanged; `M2R` may consume and promote to `LOCKED_1R` @2480 | Stop-modification history, if it is to be auditable |
| **Event 3 — target or stop** | `CloseRequest(reason, requested_level, observed_reference, steps=50)`; `pending_close_reason` set; **still `OPEN`** | The request |
| **Event 3 confirmed** | `CLOSED`, `closure_reason`, `closure_fill_price`, `steps_remaining=0` | The final fill's price, time and quantity; and the **aggregate** of both fills |

**[REPO]** So one canonical position generates, at minimum: one entry fill, one
partial exit fill, one final exit fill, plus up to two stop modifications. The
current ledger can hold **one** of the three fills.

---

# C. Representation Options

Not ranked here. Each cell states what the option does, with evidence where the
repository settles it.

| Criterion | **Option 1** — one row, exits nested | **Option 2** — position row + separate fill ledger | **Option 3** — each partial is its own position/trade |
|---|---|---|---|
| Position identity continuity | One `trade_id`, preserved | One `trade_id` on the position row; fills reference it | **Broken** — two ids for one position |
| Quantity accounting | `quantity` = original; per-exit quantities nested | `quantity` = original on the row; exact quantity per fill | Each record carries its own slice; the original is not recoverable from either alone |
| Entry price | One value | One value | Duplicated across both records |
| Original risk / R | One `price_risk`, `risk_amount` on the original quantity | Same | Duplicated; **[REPO]** spec forbids recomputing R, so the second record must inherit it rather than derive it |
| Partial exit price | Nested | A fill row | The first record's `exit_price` |
| Final exit price | `exit_price` must be redefined as "last" | A fill row; the position row's `exit_price` is the final one | The second record's `exit_price` |
| Closure reason | One per exit, nested | One per fill; the position's reason is the final one | One each |
| Milestone history | Nested or in `metadata` | Natural: each fill names the milestone that caused it | Lost across the boundary |
| `bars_held` | Position-level, one value | Position-level, one value | **Double-counted** if summed, ambiguous if not |
| Ambiguity count | Per exit; "the" flag becomes undefined | Per fill, with a position-level "any" | Counted twice |
| Realised P&L | Sum over nested exits | Sum over fills, stored on the position row | Two independent P&Ls; the position's total requires a join |
| Remaining / open quantity | Derivable | Explicit on the position row | Not represented |
| Broker execution mapping | Indirect | **Direct** — a broker deal *is* a fill | Indirect; one broker position maps to two records |
| Live restart / persistence | One object to persist, with a list | Position + its fills; fills are append-only | Two objects with an implicit relationship |
| `PaperBroker` compatibility | Needs mutable volume + multi-exit capture | Needs mutable volume + a fill emitter | Needs position splitting, which the broker has no concept of |
| Backtest compatibility | CSV gains a list-valued column | CSV unchanged in shape; a second artifact is added | Row count changes meaning |
| Reporting compatibility | `len(trades)` stable | `len(trades)` stable | **`len(trades)` doubles** |
| Backward compatibility | Fingerprint changes (new/renamed fields) | Fingerprint changes (new fields) | Fingerprint **and** row count change |
| Double-counting risk | Low | Low | **High** — `metrics.py` counts rows, so a 1R partial and its remainder are two "trades" |
| Reconstruct full history | Yes, if every exit is nested | **Yes, by construction** | Only by joining on a convention that does not exist |

**[REPO] One option conflicts with the canonical specification.** Spec 8.2 states
"a partially closed position is `OPEN` with fewer steps. There is no distinct
'partially closed' position state", and spec 4.1 freezes R for the life of *the*
position. **Option 3 represents one canonical position as two**, which
contradicts both. That is repository evidence, not a preference.

---

# D. Ledger Semantics — what `SimulatedTrade` actually is

**Traced, not inferred from the name.**

| Candidate meaning | Verdict | Evidence |
|---|---|---|
| An **order** | **No** | Rejected orders never become one; they go to `record_rejection` as separate dicts |
| A **position** | **Closest** | Produced 1:1 by `trade_from_position` from a closed `SimulatedPosition`, and `trade_id = position.position_id` — identity is aliased, not derived |
| A **complete trade** | **In effect, yes** | `metrics.py` treats each row as one trade for counts, win rate and R |
| An **execution / fill** | **No** | There is no fill-level record anywhere; `commission` and `slippage_cost` are passed in per position |
| A **reporting aggregate** | **Partly** | It carries derived values (`gross_pnl`, `r_multiple`) but is also the primary persisted artifact |

**[REPO] Conclusion: `SimulatedTrade` is a closed position flattened into one
row, and the system treats "position", "trade" and "row" as the same thing.**
That identity is exactly what a partial exit breaks.

## D.1 What changes if it changes

| Artifact | Changes? | Evidence |
|---|---|---|
| Existing test expectations | **Yes** | `test_r1_same_bar_regression` asserts `len(ledger.trades) == 1` and pins two fingerprints |
| Fingerprints | **Yes, unavoidably** | `fingerprint()` hashes `asdict()`; adding **any** field changes it |
| Closed-trade counts | Only under Option 3 | `metrics.total_trades = len(trades)` |
| P&L | No, if aggregation is defined as the sum over fills | `gross_pnl` is per row today |
| `bars_held` | No, if it stays position-level | `average_bars_held` averages rows |
| Ambiguity counts | **Yes** | `ambiguous = sum(1 for t in completed if t.was_ambiguous_exit)` — with two exits, "the" flag is undefined |
| Published `baseline_004` artifacts | **No — they are frozen and are not regenerated** | §H |

---

# E. Position Identity

| Layer | Identity | Stable? |
|---|---|---|
| `PaperBroker` | `position_id = f"SIM-{self._counter:06d}"` | **Yes**, within a run |
| Ledger | `trade_id = position.position_id` | Yes, aliased |
| `PendingOrder` | `order_id`, plus `sequence` for deterministic ordering | Yes |
| Production | `order_id = f"XAUUSD_{timestamp}_{counter}"`, `trade_id = order_id`; `manage_positions` mints a `_auto_{time}` id when one is missing | Partly — the auto-fallback is time-based and not reproducible |
| **`core.trade_model`** | **None. `TradeState` has no id field** | **Absent** |

**[REPO] Third contradiction.** The canonical domain has no notion of *which*
position a `TradeState` describes. Today that is harmless — the adapter would
hold a `dict[id, TradeState]`. It stops being harmless the moment fills must
reference their position, because the reference has no defined source.

**[DECISION]** Identity would need to be introduced at the adapter boundary, and
the id minted where the position is created — at the fill. **Not implemented
here.** Whether it additionally belongs *inside* `TradeState` is left open (§K,
I5).

---

# F. `PaperBroker` — current lifecycle and required changes

**[REPO] Today:**

```
submit_market_order / submit_limit_order
    -> _open_position(...)  -> SimulatedPosition(volume=..., state=OPEN)
on_bar(bar, bar_time)
    -> _fill_pending(...)                    # resting orders become positions
    -> resolve_intrabar(...)                 # the broker decides the exit
    -> _close(raw_exit_price, state, reason) # single, whole-position closure
    -> returns closed positions
ReplayEngine
    -> trade_from_position(...)  -> ledger.record(...)
```

**[DECISION] What must change for the domain to own exit decisions:**

| Aspect | Required change |
|---|---|
| Partial close affects quantity | `SimulatedPosition.volume` must become mutable, or split into `volume_at_entry` and `volume_remaining`. The broker has no partial-close verb today |
| A later final close | Closes `volume_remaining`, not `volume`; the position's terminal record must reflect both events |
| Broker-reported execution price | Each execution's price must be captured where it happens, then returned to the adapter as `PartialCloseFilled` / `CloseFilled`. Today it is written straight onto the position by `_close` |
| Broker rejection | Has no representation at all — every paper operation succeeds. A rejection path must exist for the adapter to exercise `PartialCloseRejected` / `CloseRejected`, even if paper never produces one |
| Final trade record | Produced by the adapter from the domain state plus the fills, not by `trade_from_position` from a single position object |
| Exit decisions | `resolve_intrabar` and `_close` stop deciding; `on_bar` delivers the bar and executes instructions |

**Not implemented.**

---

# G. Metrics — where each naturally belongs

**[REPO] "Today" is where the value is computed now.**

| Metric | Today | Belongs to | Reasoning |
|---|---|---|---|
| `bars_held` | `SimulatedPosition.bars_held`, incremented per bar | **Position lifecycle** | It measures how long *the position* existed; a partial does not end it |
| Ambiguity | `was_ambiguous_exit`, one flag per position | **Individual execution** | Each exit resolves its own bar; the position-level view is "any exit was ambiguous" |
| Entry price | `position.entry_price` | **Position lifecycle** | One entry per position under the canonical model |
| Exit price | `position.exit_price` | **Individual execution** | Two exits have two prices; the position row can carry the final one |
| Quantity | `position.volume` | **Both** — original on the position, executed amount per fill | The 50 % rule needs `steps_at_entry`; P&L needs the per-fill amount |
| P&L | `gross_pnl`/`net_pnl` per row | **Execution**, aggregated to the position | Each fill realises P&L at its own price |
| R multiple | `net_pnl / risk_amount` on the full volume | **Aggregate trade record** | R is a property of the position's frozen geometry; a per-fill R would divide by a risk the fill never carried |
| Closure reason | `exit_reason` | **Individual execution**, with the position's being the final one | The partial's reason is "1R milestone", the remainder's is stop or target |

**No new semantics are invented here** — each row states where the value is
produced today and which of the three levels it describes.

---

# H. Backward-Compatibility Impact

**Identified, not changed.**

| Artifact | Impact | Why |
|---|---|---|
| `tests/integration/test_r1_same_bar_regression.py` | **Will change.** `assertEqual(len(self.ledger.trades), 1)` survives Options 1 and 2 but not 3; both pinned fingerprints change under **every** option | `fingerprint()` hashes `asdict()`; the test's own docstring already records that R1 changed them once before |
| Ledger fingerprints generally | **Change under every option** | Any field addition |
| `SimulatedTrade` expectations | Change wherever fields are asserted | §A.9 |
| Closed-trade counts | Change **only** under Option 3 | `total_trades = len(trades)` |
| `trade_ledger.json`, `trades.jsonl`, the CSV | Shape changes; the CSV needs flat columns, so a nested exit list would serialise as a stringified object | `pd.DataFrame(...).to_csv` at `baseline.py:925` |
| `run_fingerprint.txt` | Contains `ledger_fingerprint`, so it changes | `baseline.py:951` |
| `decisions_fingerprint` | **Unchanged** | It hashes the decision stream, which trade management does not touch |
| **`baseline_004` artifacts** | **Untouched. Frozen, never regenerated** | Any future run is a different executable model, compared like-for-like against a *new* baseline |
| Production reporting | No impact | None exists |

**[MEASURED]** `baseline_004` contains **zero trades**, so no historical trade
record is invalidated by any option. The compatibility cost is confined to
fixtures and pinned fingerprints.

---

# I. Decision Criteria

The eventual representation must satisfy all ten. These are factual tests, not
preferences.

| # | Criterion | Satisfied when |
|---|---|---|
| 1 | Lossless execution history | Every executed quantity, price, time and cause is recoverable |
| 2 | Unambiguous position quantity | Original and remaining are both explicit at every point |
| 3 | Stable position identity | One id per canonical position, minted once, reproducible in replay |
| 4 | Correct partial and final P&L | Each fill's P&L at its own price; the position's total is their sum |
| 5 | Correct canonical lifecycle | One position, `OPEN` until a confirmed close (spec 8.2, 11.1a) |
| 6 | Deterministic backtest reconstruction | Same input → same records, byte-identically |
| 7 | Live/broker compatibility | Maps onto broker deals without invention |
| 8 | No double-counting | One canonical position counts as one trade |
| 9 | Restart/persistence compatible | Enough to rebuild `TradeState` after a restart |
| 10 | Preserve historical metrics where semantics are genuinely unchanged | Position-level metrics keep their meaning |

---

# J. Recommendation

**[DECISION] Proposed: Option 2 — a position-scoped trade record, plus a
separate append-only execution (fill) ledger.**

Proposed for review. **Not implemented.**

```
  TradeRecord   one per canonical position   (what trades.jsonl holds today)
      │  position_id, entry provenance, frozen geometry (R, levels),
      │  original quantity, final closure reason, aggregate P&L,
      │  bars_held, any_exit_ambiguous
      │
      └── FillRecord  one per execution, referencing position_id
             sequence, kind (ENTRY | PARTIAL_EXIT | FINAL_EXIT),
             cause (M1R | STOP | TARGET | EXTERNAL | END_OF_DATA | MANUAL),
             requested_level, observed_reference, executed_price,
             quantity, time, was_ambiguous
```

**Evidence for it, criterion by criterion:**

| # | Evidence |
|---|---|
| 1 | Only an explicit per-execution record is lossless. **[REPO]** `TradeState` stores one `closure_fill_price`, so the partial's price exists nowhere else (§A.1) |
| 3, 8 | One row per position keeps `metrics.total_trades = len(trades)` meaning what it means today (`metrics.py:185`), so the 1R partial is not counted as a trade |
| 4, 7 | **[REPO]** The canonical broker contract is already per-execution — `PartialCloseFilled`, `CloseFilled` each carry their own price and quantity (spec 16). A fill ledger is the same shape, and MT5 reports deals per execution, so live needs no translation layer |
| 5 | Matches spec 8.2 exactly: one position whose quantity falls. Option 3 contradicts it |
| 6 | Append-only records in a deterministic order fingerprint as cleanly as the current list |
| 9 | `steps_at_entry` plus the fill history reconstructs `steps_remaining` after a restart, without trusting a cached scalar |
| 10 | `bars_held`, entry price and R keep their present position-level meaning (§G), so those metrics stay comparable in kind |
| 2 | Original quantity on the record, executed quantity per fill; remaining is their difference — no inference |

**Why not the other two, on evidence rather than taste:**

- **Option 3** contradicts spec 8.2 and spec 4.1, and doubles
  `metrics.total_trades`, skewing win rate because a 1R partial is always a win.
- **Option 1** is Option 2 with the fills nested inside the row instead of
  beside it. It is not wrong, but **[REPO]** `to_dict()` is `asdict()` and
  `baseline.py:925` writes the rows through `pd.DataFrame(...).to_csv`, so a
  nested list becomes a stringified column — the execution history would be
  present but not queryable. The information content is identical; the
  difference is whether fills are addressable.

**[DECISION]** The canonical domain is **not** bent to fit the ledger: no field
is added to `TradeState`, and the aggregate record is derived by the adapter
from the domain state plus the fills it observed.

---

# K. Dependency Effects

| # | Question | Effect of the proposal | Class |
|---|---|---|---|
| **I2** | `TradeState` persistence | **Constrained, not resolved.** The fill ledger gives a rebuild path — `steps_at_entry` minus the sum of exit fills — so persistence need not be the sole source of truth. The serialisation format for enums, `frozenset` and aware datetimes is still undefined | [UNRESOLVED] |
| **I4** | `SimulatedPosition` as source of truth | **Largely resolved.** The authoritative quantity becomes `TradeState.steps_remaining`, and `SimulatedPosition` becomes the broker's own bookkeeping — a projection. Whether the class survives at all is an implementation choice | [DECISION] pending |
| **I5** | Position-id continuity | **Newly exposed, sharply.** Fills must reference a position id, and **[REPO]** `TradeState` has none (§E). An id must be minted at the fill, by the adapter. Whether it also belongs inside `TradeState` is open | [UNRESOLVED] |
| **I8** | `bars_held` and ambiguity | **Constrained.** `bars_held` stays position-level and keeps its meaning. Ambiguity becomes per-fill, with a position-level "any exit was ambiguous"; `metrics.ambiguous_exits` must state which it counts | [UNRESOLVED] |
| I3 | Live `PriceObservation` source | **Independent** — unaffected | [UNRESOLVED] |
| I6 | `IntrabarPolicy` survival | **Constrained.** A per-fill ambiguity flag gives the policy's output a home, but whether the policy survives is still open | [UNRESOLVED] |
| I7 | Concurrency-cap ownership | **Independent** | [UNRESOLVED] |

---

# L. R1 Warning — recorded separately

**[REPO]** `trade_manager` implements `CLOSE_BREAKEVEN_PROTECTION`
(`trade_manager.py:467`). The canonical model does not, because reversal
protection is **R1 and unresolved**.

**Retiring `trade_manager` therefore removes a behaviour with nothing replacing
it.** That is recorded here so the removal cannot happen silently.

**This document does not replace, recreate, reinterpret or implement reversal
protection, and R1 stays outside the I1 decision.** Nothing in §J depends on
it: the proposal represents whatever exits the canonical model produces, and
would represent a protection exit too, should R1 ever add one, as another fill
cause.

---

# M. Prohibited Changes — confirmed observed

No production Python, test, baseline, `core/trade_model.py` or canonical
specification was modified. The adapter is not wired, `trade_manager` is not
retired, `PaperBroker` is unchanged, ledger behaviour is unchanged, and R1–R4,
U5/R8 and U6/R9 are untouched.

---

# N. Verification

**Nothing was modified.** The only new file is this document.

Read-only inspection covered `core/trade_model.py`, `execution/broker.py`,
`execution/paper_broker.py`, `backtest/ledger.py`, `backtest/metrics.py`,
`backtest/baseline.py`, `backtest/runner.py`, `backtest/replay_engine.py`,
`trade_manager.py`, `order_execution.py`, `main_production.py`,
`trade_persistence.py` and `tests/integration/test_r1_same_bar_regression.py`.

## Existing test suite, run unmodified

```
env -u TRADING_BOT_LOG_FILE -u TRADING_BOT_MAIN_LOG_FILE -u SIGNAL_LOG_FILE \
    -u MAIN_SIGNAL_LOG_FILE -u LOG_FILE \
    ./venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| Result | |
|---|---|
| Tests run | **752** |
| Duration | 579.2 s |
| Failures | **2** |
| Errors | **0** |
| Skipped | **0** |

Both failures are the pre-existing L2 H1-ATR mock failures in
`tests/test_layer_gate_logic.py`, which reproduce at `04a341d`. Unchanged from
`9792de7`, as expected for a documentation-only phase.

---

*Design and evidence only. No code changed, no representation implemented, no option adopted without review, no baseline created, no performance claim made. Stopping for review.*
