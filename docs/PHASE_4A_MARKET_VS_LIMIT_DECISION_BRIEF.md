# Phase 4A — design decision brief: MARKET entry vs resting LIMIT_FVG

**Read-only.** No strategy or production file was modified. Neither design is
implemented, recommended or ranked. Baseline `62ce38e`; Phase 3A artifacts
untouched.

**The blocker:** is the momentum FVG setup intended to be a MARKET entry or a
resting LIMIT_FVG entry? Everything else about `price_in_fvg` follows from the
answer.

> **Correction carried forward.** The previous report (`62ce38e`, evidence 10)
> cited `paper_broker._pending` as evidence that the limit design was never
> implemented. `execution/paper_broker.py` is **my own Phase 2A file**
> (`f39faa9`, 2026-09-16), so `_pending` is unused scaffolding I left and says
> nothing about the original author's intent. The `entry_mode` half of that
> evidence stands, and is now joined by a stronger original-code finding
> (evidence 6 below).

---

## 1. The two reconstructed designs

Reconstruction of consequences, not proposals.

### A — MARKET ENTRY

| Aspect | What would happen |
|---|---|
| **When triggered** | At the close of the decision bar, when all five `core_trigger` terms are true simultaneously. Single-instant evaluation; no waiting. |
| **Price used** | `confirmed_entry_price` — which is `fvg["midpoint"]`, unless CHoCH overrides it to `m1[-1].close`. In the backtest the *fill* is the next bar's open. |
| **`fvg.midpoint` vs market price** | They are different things. The midpoint is a geometric level inside a gap that has just formed; the transactable price at that instant is `m5[-1].close`/the live bid-ask. Using the midpoint as a *market* entry price records a price the order cannot transact at — already on record as **Q1** (realised R ≠ reported RR, because risk is priced against an entry that is never filled). Under A, the midpoint override is the anomaly. |
| **What `price_in_fvg` would mean** | "Price is inside the gap *now*, so a market order lands inside the zone." Coherent **only if** the price tested is the price that will transact. It currently tests `m5[-2].close` — neither the transactable price nor the entry price. |
| **`entry_mode="LIMIT_FVG"`** | Becomes a misnomer. It is already inert: propagated into logs and the signal dict, never branched on. |
| **CHoCH override** | Becomes arguably the *correct* behaviour — `m1[-1].close` is much closer to a transactable price than a geometric midpoint. Under A the override is the sane branch and the midpoint is the defect. |

### B — RESTING LIMIT_FVG

| Aspect | What would happen |
|---|---|
| **When the FVG is formed** | At the decision bar, from `m5[-3], m5[-2], m5[-1]`. The gap is one bar old at most. |
| **Where the order is placed** | At `fvg["midpoint"]` on the current reading. Whether the midpoint, the proximal edge or the distal edge is correct is **undecided** (§6). |
| **What causes it to fill** | A **subsequent** bar trading into the zone. The repository already defines this: `poi_engine._zone_touched` — *"True if any candle after formation traded into the zone"*, `low <= top and high >= bottom`, using wicks. |
| **If price never returns** | The order must expire. **No expiry logic exists anywhere.** |
| **If the FVG is filled/invalidated first** | The order must be cancelled. `poi_engine` has the concept (`fill >= 0.5` rejects the FVG; `fill_percent` quantifies depth); `entry_engine` has **none**. |
| **What `price_in_fvg` would mean** | At signal time, **nothing** — or the opposite of what it currently asserts. A resting order exists *because* price is not in the zone yet. Requiring price to already be inside contradicts the design, and would align badly with L6, which rewards **untested** zones (+30). |
| **Missing machinery** | Pending-order state and persistence; expiry; invalidation/cancel; fill detection against later bars; SL/TP activation on fill rather than on signal; and broker-side support. **The original `OrderType` enum has exactly two members, `BUY` and `SELL`** — see evidence 6. |

## 2. Evidence trace — what each item *proves* vs *suggests*

| # | Finding | File / function | Proves | Merely suggests |
|---|---|---|---|---|
| 1 | `entry_mode = "LIMIT_FVG"` set on the momentum path only | `entry_engine.py:625` `_evaluate_momentum_entry` | The author labelled this path as a limit entry | That a resting-order design was intended |
| 2 | `entry_mode` is read in 12 places — all logging, signal dicts, CSV columns | `main.py`, `main_production.py`, `core/signal_log.py:88` | **No code branches on the value.** It is inert | — |
| 3 | `"MARKET"` is the value on the pullback path and the default everywhere | `entry_engine.py:532, 724` | Two modes were contemplated as labels | — |
| 4 | `confirmed_entry_price = fvg["midpoint"]` whenever a midpoint exists | `entry_engine.py:580-581` | The entry price is the gap's geometric centre | That the author expected price to return to it |
| 5 | CHoCH override replaces it with `m1[-1].close` | `entry_engine.py:582-583` | A later, market-like price can replace the geometric one | The two overrides were written with different mental models |
| 6 | **`class OrderType(Enum): BUY, SELL`** — no LIMIT, STOP or PENDING | `order_execution.py:30-32` (**original code**) | **The original execution layer has no resting-order concept at all** | That LIMIT_FVG was aspirational |
| 7 | `create_order(...)` takes `entry_price` and immediately logs the order as created at that price | `order_execution.py:66-124` | Orders are modelled as filled at signal time | — |
| 8 | No `BUY_LIMIT`/`SELL_LIMIT`/`TRADE_ACTION_PENDING`/`pending_order`/`limit_price` anywhere | repo-wide grep | **No pending-order machinery exists** | — |
| 9 | `paper_broker._pending` declared, never used | `execution/paper_broker.py:67,86` | Nothing — **this is my Phase 2A file**, not original design | — |
| 10 | `price_in_fvg` computed and consumed only inside `_evaluate_momentum_entry` | `entry_engine.py:585,591,609,655` | It is a live gate; its returned value is dead output | — |
| 11 | `fvg_found` returned with zone bounds even when `gap_valid` is false | `entry_engine.py:292` | The detector reports bounds for a gap it says does not exist | Carelessness rather than intent |
| 12 | `_zone_touched` — *"True if any candle after formation traded into the zone"* | `poi_engine.py:56-73` | **The repo already defines zone interaction**, over post-formation bars, using wicks | That the same definition was meant for L8 |
| 13 | `fill` computed over subsequent candles; FVG rejected if `fill >= 0.5` | `poi_engine.py:322-331` | The repo models gap *filling* explicitly | — |
| 14 | `is_untested = fill_pct < 20 and not _zone_touched(...)`; untested scores **+30** | `poi_engine.py:421-424, 627` | **L6 rewards the opposite polarity to `price_in_fvg`** | The two layers were designed by different reasoning |
| 15 | Design docs describe L8 as rejection candle + momentum + M1 flip only | `SYSTEM_STRUCTURE_DIAGRAM.md:356-362`, `FLOW_DIAGRAM_WITH_FLAWS.md:138-152` | **The momentum/FVG path is undocumented** | It was added after the documented design |
| 16 | Both docs mention FVG only under L6/POI | same | The documented FVG concept is the POI one | — |
| 17 | No test references `price_in_fvg`, `core_trigger`, `_evaluate_momentum_entry`, `LIMIT_FVG` | `tests/`, `test_*.py` | **The momentum path is untested** | — |
| 18 | Whole momentum block from one bulk commit `c3cf4df` ("update", 51 files) | `git blame -L 574,615` | No ordering between gate and overrides can be established | — |

## 3. The two FVG implementations, factually

| Property | `entry_engine` FVG | `poi_engine` FVG |
|---|---|---|
| **Timeframe** | M5 | M15 |
| **Formation bars** | Fixed: the last 3 closed bars (`[-3]`, `[-2]`, `[-1]`). No scanning | Scans `tail(10)`, **adjacent pairs** (`prev`, `curr`) — a 2-candle gap, not the 3-candle form |
| **Bullish definition** | `gap_low = left.high`, `gap_high = right.low`, requires middle candle bullish **and** `gap_high > gap_low` | `curr_low > prev_high` |
| **Bearish definition** | `gap_low = right.high`, `gap_high = left.low`, requires middle candle bearish **and** `gap_high > gap_low` | `prev_low > curr_high` |
| **Zone bounds** | `zone_low` / `zone_high` — **returned even when `fvg_found` is False** | `fvg_top` / `fvg_bottom` — `None` when not found |
| **Minimum gap size** | **None** | `gap_size >= 3` (comment says "3 pips"; the value is in price units, i.e. **$3.00** — the U-series unit confusion) |
| **Touch definition** | **None.** A single close tested for containment, with a ±35 % midpoint tolerance | `_zone_touched`: any post-formation candle with `low <= top and high >= bottom` (wicks) |
| **Fill / invalidation** | **None** | `fill` fraction over subsequent candles; FVG rejected at `fill >= 0.5` |
| **Polarity** | Price must be **in** the zone (`price_in_fvg` must be True) | **Untested / unfilled is better** (`+30`) |
| **Midpoint** | `gap_low + size/2`; `None` when invalid | Not computed |
| **Quality inputs** | ATR, candle body, volume ratio → `fvg_quality` | Fixed `base_score = 25` |
| **Consumer** | `core_trigger` in `_evaluate_momentum_entry` (**L8**) | `identify_poi` / `score_poi` (**L6**) |

No unification is recommended here; §6 records it as an open decision.

## 4. What the 117 records imply under each design

From `docs/phase_4a_fvg_records.json`. Neither reading is asserted to be correct.

**Under a MARKET interpretation.** The gate is asking a sensible question badly.
"Is price in the zone now?" is the right question for a market entry, but it is
asked of `m5[-2].close` — the middle candle *of the gap itself*, a bar
structurally unlikely to sit inside the gap its neighbours form. Measured: the
tested price sat a median **1.1× the zone width** outside. Of the 116 rejections,
**103** had an entry price (the midpoint) inside the zone and **13** (the CHoCH
cases) had it outside. Under A those 13 are the only ones where the gate's
verdict and the entry price agree — and they agree on rejection. The 103 are
rejections of setups whose nominal entry was at the zone centre, although that
centre is not a transactable price (Q1).

**Under a RESTING LIMIT interpretation.** The question is irrelevant at signal
time. All 117 had a freshly formed, valid gap — exactly the precondition for
placing a resting order. Whether price later returned into the zone is
**unmeasured**: the diagnostic never examined bars after the decision, because
the production code never does either. Under B the gate as written rejects 116
candidate setups on a criterion that does not bear on the design, and the single
case it passed — price already inside the zone, by 2 cents — is the one where a
resting order would be least useful, since it would fill almost immediately.

**Common to both.** The FVG representation is sound in all 117: 0 inverted
bounds, 0 fallback midpoints. Whatever is wrong is not the gap geometry.

## 5. Decision matrix — descriptive only

| Question | MARKET entry | Resting LIMIT_FVG |
|---|---|---|
| Fits current `entry_mode` name? | **No** — the label says LIMIT | **Yes** |
| Fits midpoint entry price? | **No** — a geometric level is not transactable (Q1) | **Yes** — a limit rests at a chosen level |
| Makes `price_in_fvg` meaningful? | **Potentially** — but only if it tests the transactable price, not `m5[-2].close`; and not if it tests the midpoint, which is inside by construction (104/104) | **No** — contradicts the design; the meaningful test would be the opposite (zone unfilled) |
| Requires pending-order machinery? | No | **Yes** — state, expiry, invalidation, fill detection, none of which exist |
| Requires future-bar interaction? | No | **Yes** — fill is defined only over post-formation bars |
| Compatible with existing `poi_engine` concepts? | Partly — shares no vocabulary, but needs none | **Yes** — `_zone_touched` and `fill_percent` are exactly the needed primitives, though with inverted polarity at L6 |
| **Evidence supporting it** | `OrderType` has only BUY/SELL (ev. 6); `create_order` fills at signal time (ev. 7); no pending machinery anywhere (ev. 8); design docs describe an immediate trigger (ev. 15) | `entry_mode = "LIMIT_FVG"` (ev. 1); entry price is the gap centre (ev. 4); FVG detected the instant it forms, leaving nothing to confirm yet |
| **Evidence against it** | The path is explicitly labelled LIMIT; the midpoint entry makes no sense as a market price | No execution support of any kind; no expiry, invalidation or fill logic; L8 is documented as an immediate trigger |

## 6. Unresolved design decisions

None is resolved here.

1. **MARKET vs resting LIMIT_FVG.** Blocking; everything below depends on it.
2. **Which bar establishes the FVG.** Currently always the latest three. Retracement semantics require a gap older than the current bar; there is no scan-back in `entry_engine`.
3. **Must an FVG be fresh / unfilled?** `entry_engine` has no freshness concept; `poi_engine` requires `fill < 0.5` and rewards untested.
4. **What constitutes a touch or a fill?** `poi_engine` defines both, on wicks, over post-formation bars. `entry_engine` defines neither.
5. **Is the entry the midpoint, a zone edge, or a market price?** Currently the midpoint, overridden by CHoCH.
6. **May CHoCH override the FVG entry price?** It currently does, and it is the only route by which the entry leaves the zone (13 of 117).
7. **Should FVG logic be shared with `poi_engine`?** The two detectors differ on timeframe, bar count, bound naming, minimum size, touch, fill and polarity.
8. **Should the momentum path remain a five-way AND?** Measured: `raw_triggered` was false in all 1,265 L8 decisions; only FVG terms were ever the sole blocker.
9. **Which M1 bar index is correct** for the CHoCH override — pullback uses `[-2]`, momentum `[-1]`.

## 7. Final output

### A. What the repository establishes with high confidence

1. **No resting-order capability exists.** `OrderType` has two members, BUY and SELL; `create_order` treats an order as filled at signal time; no limit/stop/pending construct appears anywhere.
2. **`entry_mode` is inert.** Set in two places, read in twelve, branched on in none.
3. **`price_in_fvg` is a live gate with one consumer** and no documentation, no test, and no explanatory history.
4. **Two incompatible FVG definitions coexist**, differing on every property in §3, including polarity.
5. **The repository already contains precise zone-interaction primitives** — `_zone_touched` and `fill_percent` — in `poi_engine`, unused by `entry_engine`.
6. **The momentum/FVG path is undocumented.** Both design documents describe an L8 built from rejection candle, momentum confirmation and M1 flip.
7. **The 117 FVG-positive cases have sound geometry** — 0 inverted bounds, 0 fallback midpoints.

### B. What is only inference

1. That `entry_mode = "LIMIT_FVG"` plus a midpoint entry implies a retracement design. It is the only reading under which those two cohere, but no code, comment or document says so.
2. That the momentum path is an unfinished addition. Consistent with the absence of docs, tests and execution support — but "unfinished" is an interpretation, not a record.
3. That the CHoCH override reflects a different mental model from the midpoint override. Suggested by their incompatibility; nothing states it.
4. That `poi_engine`'s primitives were meant to serve L8. They are simply the only ones present.

### C. Minimum decisions required before implementation

**Blocking, in order:**

1. **MARKET or resting LIMIT?** (§6.1)
2. **If LIMIT:** are you prepared to build pending-order state, expiry, invalidation and fill detection — none of which exists — and to accept that `LIVE_TRADING_ENABLED` stays false until the execution layer supports it?
3. **If MARKET:** what price is the entry, given that the midpoint is not transactable? (§6.5)
4. **What is `price_in_fvg` for**, expressed as a sentence about the market rather than about code? Everything else can be derived from that sentence; nothing can be derived without it.

**Needed before the second experiment, not the first:** §6.2, 6.3, 6.4, 6.6, 6.7, 6.9.

### D. Proposed sequence of experiments — after those decisions, NOT executed

Each one change, measured against the immutable Phase 3A baseline, in the Phase 4A style: read-only diagnostic first, then a single isolated change, then a determinism and leakage check.

1. **Measure before changing.** For the 117, replay forward and record whether a subsequent bar would have touched the zone, using `_zone_touched` semantics, and within how many bars. This is read-only, needs no decision, and is the only thing that can say whether a retracement design would have had anything to fill. **It does not commit to either design.**
2. **Then the decided change**, in isolation — under MARKET, correct the price the gate tests; under LIMIT, remove the contradictory gate and add the fill lifecycle. Not both.
3. **Re-measure the funnel**, expecting the next binding constraint to surface, since the momentum trigger is a five-way AND.
4. **Only afterwards**, revisit the RR tautology (E9/E10), which remains latent and will bind the moment an allowed candidate fires in a `tp_ratio < 2.0` regime.

Step 1 is the only one I would suggest running before decisions are made, and only if you want it.

---

*Read-only design brief. Nothing implemented, nothing tuned, no design chosen. Stopping for review.*
