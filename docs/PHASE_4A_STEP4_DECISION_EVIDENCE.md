# Step-4 decision evidence: invalidation, expiry, CHoCH override, cross-session survival

**Read-only.** No strategy file, production pending-order code, parameter or
baseline artifact was changed. Nothing is implemented. No value was chosen by
looking for the one that maximises fills or touches.

**Execution baseline:** `a4f7141` (R1). **Design held fixed:** `LIMIT_FVG`
resting at the **FVG midpoint**, unless decision C determines otherwise.
**Terminology:** formation → pending-order creation → price reach → limit fill →
zone invalidation.

**Tags:** `[REPO]` original repository code · `[PHASE_2A]` scaffolding I added in
`f39faa9` · `[MEASURED]` observed · `[DECISION]` explicit decision ·
`[CONSEQUENCE]` follows from the above · `[UNRESOLVED]` not determinable.

## Method, common to all four

`[MEASURED]` The 117 FVG-positive L8 records (`docs/phase_4a_fvg_records.json`)
were replayed forward over the real XAUUSD M5 series, measuring bars from
formation to: zone touch, **midpoint reach** (the fill event under the chosen
design), the 50 %-fill depth, and full traversal — plus the session, daily-break
and weekend transitions crossed before each.

Level tests use the specification's direction-aware rule (§0 Decision 2.1),
which mirrors `resolve_intrabar`'s stop comparison: BUY reached when
`bar.low <= level`, SELL when `bar.high >= level`. `poi_engine._zone_touched`
tests *zone overlap* and would miss a bar gapping through a level, so it is used
for zone touch only — and as a cross-check: **0 disagreements in 117**.

Run twice, byte-identical, fingerprint
`de958e16adf3905bce2e5f392d749b2df7e7c56cc969282495fc7f5244997c7c`.

---

# A. FVG invalidation

## A1. Existing evidence

`[REPO]` `entry_engine` has **no invalidation concept whatsoever** — no fill
tracking, no touch tracking, no staleness, no expiry. Its FVG is detected fresh
from the last three bars and consumed in the same instant.

`[REPO]` `poi_engine` has two related mechanisms, and **neither is an order
invalidation rule**:

- `_zone_touched(...)` — *"True if any candle after formation traded into the
  zone"*;
- the inline `fill` fraction in `detect_fvg`, which rejects a gap at `fill >= 0.5`.

`[REPO]` Both feed **POI scoring**: `is_untested = fill_pct < 20 and not
_zone_touched(...)`, and `is_untested` awards **+30** in `score_poi`. They answer
*"is this zone still attractive to rank?"*, not *"should a resting order be
cancelled?"*. `[CONSEQUENCE]` They are scoring inputs for L6 selection, not
lifecycle rules for an L8 order, and treating them as the latter would be reading
intent into code that does not express it.

`[REPO]` The polarity is also opposite: L6 rewards a zone that price has **not**
entered, while a resting L8 limit requires price to enter.

## A2. Methodology

For each record, the first bar after formation at which price reaches the zone
edge, the midpoint, the 50 %-fill depth and the far edge.

## A3. Measured results

| Event | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| Zone touch | 116/117 | 1 | 1.0 | **1.0** | 7.0 | 1464 |
| **Midpoint reach (the fill)** | 116/117 | 1 | 1.0 | **2.5** | 11.8 | 1464 |
| 50 %-fill depth | 116/117 | 1 | 1.0 | **2.5** | 11.8 | 1464 |
| Full traversal | 116/117 | 1 | 1.0 | **4.0** | 21.2 | 1464 |

`[MEASURED]` **`bars_to_midpoint == bars_to_half_fill` in 117 of 117.** This is
not a coincidence: the midpoint sits at exactly 50 % zone depth, so reaching it
*is* a 50 % fill.

`[MEASURED]` Which rules could fire **before** the fill:

| Candidate rule | Fires strictly before the midpoint fill |
|---|---|
| POI `fill >= 0.5` | **0 / 116** |
| Full traversal | **0 / 116** |
| Zone touch (shallower) | 29 / 116 |

`[CONSEQUENCE]` This is geometric, not empirical luck: `low <= zone_low` implies
`low <= midpoint`, so traversal is a strict subset of midpoint-reach and can
never precede it. The 50 % level *is* the midpoint.

`[MEASURED]` Full traversal happens **on the same bar** as the fill in 82 of 116
(70.7 %). Between zone touch and fill: median **0 bars**, i.e. usually the same
bar; 87 of 116 fill on the bar they first touch.

## A4. What the evidence does NOT establish

- What invalidation *should* be. It establishes only what it cannot usefully be.
- Whether a non-geometric invalidation (bias flip, opposing structure, new FVG)
  would be appropriate — no such rule exists anywhere to measure.
- Anything about the 1,148 decisions where `fvg_found` was false.

## A5. Candidate interpretations

1. **Import the POI 50 % rule.** `[MEASURED]` Self-defeating: it fires on the
   exact bar the limit fills, 117/117, so it would require an arbitrary
   tie-break to decide whether the order filled or died.
2. **Invalidate on full traversal.** `[MEASURED]` Also unfireable — 0/116 precede
   the fill, and 82/116 traverse on the fill bar itself.
3. **Invalidate on zone touch.** `[MEASURED]` Can fire first (29/116), but it
   would cancel the order precisely when price arrives, which inverts the design.
4. **No zone-based invalidation**; rely on expiry alone.
5. **Non-geometric invalidation** (structural). No repository basis.

## A6. Experiment that would distinguish them

None on this data can separate 4 from 5, because 5 does not exist to be
measured. What *would* help: measuring what happens **after** a hypothetical
fill — whether zones that fill and then reverse differ structurally from those
that continue — but that requires a fill model and belongs after Step 4, not
before it.

## A7. Can the decision be made?

**Partly.** `[CONSEQUENCE]` The evidence is decisive *negatively*: **no
zone-penetration rule available in this repository can protect a midpoint limit,
because all of them fire at or after the fill event, never before it.** The POI
50 % rule in particular must not be imported.

**The positive rule is `[UNRESOLVED]`.**

## A8. Blocking

What invalidation is *for*. If it exists to cancel an order whose setup has
decayed, the trigger must be something other than price entering the zone —
because that is the fill. No such concept exists in the repository, so this is a
design choice with no evidential basis, and I am not making it.

---

# B. Pending-order expiry

## B1. Existing evidence

`[REPO]` No expiry exists anywhere — no `ORDER_TIME_SPECIFIED` equivalent, no
staleness counter, no TTL. `[REPO]` `order_execution.OrderType` has only `BUY`
and `SELL`, so no resting order has ever had a lifetime to bound.
`[PHASE_2A]` `max_bars_held` bounds an **open position**, not a pending order,
and is `None` in the baseline.

## B2. Methodology

Bars from formation to midpoint reach, with the tail characterised in bars,
minutes, calendar days and session/break crossings.

## B3. Measured results

| Horizon | Filled | % |
|---|---|---|
| ≤ 1 bar | 47 | 40.2 |
| ≤ 3 | 66 | 56.4 |
| ≤ 6 | 80 | 68.4 |
| ≤ 12 | 88 | 75.2 |
| ≤ 24 | 98 | 83.8 |
| ≤ 48 | 101 | 86.3 |
| ≤ 96 | 108 | 92.3 |
| eventually | 116 | 99.1 |
| **never** | **1** | **0.9** |

`[MEASURED]` Elapsed time to fill: median **12.5 minutes**, p75 **59 minutes**,
max **13,800 minutes** (9.6 days). Calendar days spanned: 109 of 116 fill the
same day; 2 span two days, 2 span three, 1 spans seven, 2 span eight.

`[MEASURED]` The 18 orders taking more than 24 bars include three that rest
across **two weekends** and four daily breaks.

`[MEASURED]` The single never-filled zone is the $0.08-wide one, untouched in
7,987 bars.

## B4. What the evidence does NOT establish

- Any expiry value. The distribution is continuous and heavy-tailed; every
  cut-off is a trade-off between capturing fills and holding stale orders.
- Which *form* of rule is right. Fixed-bar, session-based and no-expiry are all
  representable; the data does not prefer one.
- Whether late fills are *desirable*. A fill 1,464 bars later is a fill, but
  whether the setup it was based on still means anything is unmeasured — and
  that is the actual question behind expiry.

## B5. Candidate interpretations

1. **No expiry** — rests until filled or invalidated. Captures 99.1 %, but three
   orders would rest for over a week across weekends.
2. **Fixed-bar expiry** — any N is representable; the table gives the capture
   rate for each, which is exactly why choosing from it would be fitting a
   parameter to an outcome.
3. **Session-based** — `[MEASURED]` 94 of 116 (81.0 %) fill in the session they
   formed in, so "expire at session end" is a coherent rule with a measurable
   cost.
4. **Structure-based** — expire when the setup that produced it is gone. No
   repository basis.

## B6. Experiment that would distinguish them

Only one that measures fill *quality*, not fill *rate*: whether late fills
perform differently from prompt ones. That needs simulated outcomes, i.e. Step 4
must already exist. **Expiry cannot be evidence-based before the thing it bounds
is implemented.** A defensible interim is to implement with no expiry, measure,
and set one afterwards from evidence — but that is a sequencing proposal, not a
decision.

## B7. Can the decision be made?

**No. `[UNRESOLVED]`.**

## B8. Blocking

An expiry answers "how long is this setup still valid?", which is a claim about
the strategy, not about the fill distribution. Choosing N from the table above
would select a parameter from an outcome — the practice this phase exists to
avoid.

---

# C. CHoCH override

## C1. Existing evidence

`[REPO]` `_evaluate_momentum_entry` sets the entry price in three steps:

```python
confirmed_entry_price = m5[-1].close
if fvg.midpoint is not None:   confirmed_entry_price = fvg.midpoint
if m1_choch_confirmed:         confirmed_entry_price = m1[-1].close
```

`[REPO]` `detect_m1_choch` returns `choch_level = current_close`, the close of
the M1 candle that **broke** the prior swing, confirmed only when that candle
closes beyond the swing with body strength. `[CONSEQUENCE]` `m1[-1].close` is
therefore the **breakout price**, not a retracement level. It expresses "enter
where momentum confirmed", which is a different entry model from "rest an order
inside a gap and wait".

`[REPO]` No comment, docstring, test or design document explains the override,
and it arrived in the same bulk commit as everything else.

## C2. Methodology

For each of the 13 CHoCH-sourced cases: the zone, the midpoint, the override
price, its position relative to the zone, and whether the midpoint is reached.

## C3. Measured results

| Formation (UTC) | Side | Zone | Midpoint | `m1[-1].close` | Offset | Midpoint filled |
|---|---|---|---|---|---|---|
| 2026-07-17 12:40 | SELL | 3983.09–3984.36 | 3983.73 | 3977.75 | −5.34 below | 12 bars |
| 2026-07-29 12:30 | SELL | 4017.40–4018.83 | 4018.11 | 4013.10 | −4.30 below | 1 |
| 2026-07-31 05:05 | BUY | 4078.10–4079.74 | 4078.92 | 4082.45 | +2.71 above | 6 |
| 2026-08-06 07:20 | BUY | 4260.16–4261.13 | 4260.65 | 4264.36 | +3.23 above | 1 |
| 2026-08-06 08:00 | BUY | 4257.22–4258.33 | 4257.77 | 4262.66 | +4.33 above | 46 |
| 2026-08-07 14:25 | BUY | 4341.75–4343.53 | 4342.64 | 4351.25 | +7.72 above | 4 |
| 2026-08-10 04:20 | BUY | 4327.57–4330.59 | 4329.08 | 4333.75 | +3.16 above | 84 |
| 2026-08-12 00:20 | BUY | 4371.01–4373.94 | 4372.48 | 4379.70 | +5.76 above | 237 |
| 2026-08-12 09:25 | BUY | 4413.02–4413.45 | 4413.24 | 4423.52 | +10.07 above | 1 |
| 2026-08-18 10:40 | BUY | 4392.18–4393.45 | 4392.82 | 4397.50 | +4.05 above | 6 |
| 2026-08-28 04:40 | SELL | 4581.89–4583.05 | 4582.47 | 4578.35 | −3.54 below | 3 |
| 2026-08-28 08:45 | SELL | 4607.60–4607.99 | 4607.80 | 4603.47 | −4.13 below | 18 |
| 2026-09-08 05:30 | SELL | 4425.30–4426.20 | 4425.75 | 4420.46 | −4.84 below | 2 |

`[MEASURED]` **13 of 13 lie outside the zone, always on the far side**: every
BUY override is **above** the zone (8/8), every SELL **below** (5/5). None is
inside.

`[CONSEQUENCE]` A BUY limit must rest **below** market and its FVG lies below;
the override sits **above** the zone, in the direction the trade is going. It is
not a level price retraces *down* to — it is where price already is or is
heading. **A resting limit cannot be placed there.** The same holds inverted for
SELL.

`[MEASURED]` **All 13 zones reach their midpoint** (1 to 237 bars, median 6), so
every one of these setups remains a viable candidate under a midpoint limit.

## C4. What the evidence does NOT establish

- Why the override was written. No rationale is recorded anywhere.
- Whether the breakout entry it implies is better or worse — no outcomes exist.
- Whether the same author intended both mechanisms to coexist.

## C5. Candidate interpretations

1. **The override is a leftover from a market/breakout entry model**, predating
   or unrelated to `LIMIT_FVG`. Consistent with every measurement, but
   unprovable.
2. **The momentum path is deliberately dual-model** — a limit when no CHoCH,
   a breakout entry when CHoCH confirms. Coherent as a design, but nothing
   states it and `entry_mode` is a single value.
3. **The override is simply a defect** — the last write wins over the midpoint
   by accident of statement order.

## C6. Experiment that would distinguish them

None. This is a question about intent, and the repository contains no record of
it. Interpretations 1 and 3 are indistinguishable by measurement.

## C7. Can the decision be made?

**Yes, on compatibility — and the answer is forced by a decision already taken.**

`[CONSEQUENCE]` Given `LIMIT_FVG` with a midpoint limit price, the override is
**unexecutable**: 13/13 of its prices are on the wrong side of the zone to rest
as a limit. It cannot be honoured as specified.

`[DECISION — proposed, not taken]` Remove the CHoCH override from the
`LIMIT_FVG` path. All 13 affected setups survive as midpoint-limit candidates.

**Is that a strategy change or an execution-semantic correction?** `[CONSEQUENCE]`
**A strategy change.** It changes the entry price on 13 of 117 setups and
therefore their outcomes. It is *forced* by the design decision already taken,
but that does not make it semantically neutral, and it should not be presented
as a mere correction.

## C8. Blocking

Only if you want interpretation 2 — a deliberately dual-model momentum path.
That would need its own entry mode, its own execution semantics and its own
specification, and it contradicts "midpoint limit price" as currently held. That
is your call; the incompatibility itself is settled.

---

# D. Cross-session survival

## D1. Existing evidence — four distinct concepts

`[CONSEQUENCE]` These are routinely conflated and must not be:

| Concept | Where it lives | Status |
|---|---|---|
| **Strategy eligibility** | L1–L8 in `analyze_entry`, re-evaluated every M5 bar | `[REPO]` exists |
| **Session gate eligibility** | `check_pre_trade_gates` — DEAD session blocks | `[REPO]` exists, **but see below** |
| **Pending-order lifetime** | — | `[REPO]` **does not exist** |
| **Fill eligibility** | — | `[REPO]` **does not exist** |

`[REPO]` **The session gate is not in the decision path.** An AST trace shows
`check_pre_trade_gates` is called **only from `main()`** (line 1373), never from
`analyze_entry`. It is a live-loop gate. `[MEASURED]` Consistent with the Phase
3A funnel, where L1 was reached by 100 % of decisions including all 1,380
Dead-session ones.

`[REPO]` L8 momentum requires `kill_zone` (08–10, 12–14 UTC) at **formation**.
Nothing anywhere says whether that constraint should apply at **fill** time,
because no fill-time concept exists.

`[REPO]` The DEAD-session text says "no trading between 22:00 and 03:00 UTC"
while `get_current_session` returns `Dead` for 21:00–24:00 — the two disagree.
Noted, not investigated; out of scope.

## D2. Methodology

For each order reaching its midpoint, the session at formation and at fill, the
number of session transitions, daily broker breaks and weekend breaks crossed,
and calendar days spanned.

## D3. Measured results

`[MEASURED]` Of the 116 orders that reach the midpoint:

| | n | % |
|---|---|---|
| Fill in the **same** session as formation | 94 | 81.0 |
| Fill in a **different** session | **22** | **19.0** |
| Cross ≥1 daily broker break | **10** | **8.6** |
| Cross ≥1 weekend break | **3** | **2.6** |

Session transitions crossed: 0 → 93 orders, 1 → 14, 2 → 2, 3 → 1, 5 → 1, 8 → 1,
9 → 1, 22 → 3.

| Formation → fill | n |
|---|---|
| London → London | 44 |
| Asian → Asian | 36 |
| NewYork → NewYork | 14 |
| Asian → London | 10 |
| London → NewYork | 4 |
| NewYork → Dead | 2 |
| London → **Closed** (weekend) | 2 |
| Asian → NewYork | 2 |
| NewYork → Asian | 1 |
| Asian → Dead | 1 |

`[MEASURED]` Three orders fill in `Dead` or `Closed` — sessions in which the
live-loop gate would refuse to trade at all.

## D4. What the evidence does NOT establish

- Whether an order *should* survive any boundary. The repository has no opinion,
  because it has no pending concept.
- Whether a fill during `Dead`/`Closed` is acceptable. The L0 gate blocks *new*
  trading then; it says nothing about a pre-existing resting order, and it is not
  even in the replay path.
- Whether the kill-zone constraint is about *when a setup forms* or *when a trade
  is taken*. The distinction has never had to be made.

## D5. Candidate interpretations

1. **Survive indefinitely.** Captures the 19 % cross-session fills, but permits
   fills in `Dead`/`Closed` (3 cases) that the live gate would forbid for a new
   trade.
2. **Expire at session end.** Would drop 22 of 116 (19.0 %).
3. **Expire at the daily break.** Would drop 10 of 116 (8.6 %).
4. **Expire at the weekend only.** Would drop 3 of 116 (2.6 %).
5. **Survive, but suppress fills while the session gate would block.** Coherent,
   and the only one that reconciles a resting order with the existing DEAD rule —
   but it invents a fill-eligibility concept that does not exist.

## D6. Experiment that would distinguish them

Nothing read-only. Each option is a different rule, not a different reading of
the same data; the measurements above give the *cost* of each but cannot rank
them without knowing what a fill during `Dead` is worth.

## D7. Can the decision be made?

**No. `[UNRESOLVED]`** — though the magnitudes are now known precisely, and the
question is sharper than before: *does the DEAD-session prohibition bind a
resting order, or only a new trade decision?*

## D8. Blocking

That question. It is answerable only by you, because the repository never had to
answer it. `[CONSEQUENCE]` Note it interacts with B: "expire at session end" is
simultaneously an expiry rule and a survival rule, so B and D should be decided
together, not separately.

---

## Final table

| Decision | Evidence sufficient? | Proposed decision | Blocking issue |
|---|---|---|---|
| **Invalidation** | **Negatively yes, positively no** | **Do not import the POI 50 % rule** — it fires on the exact bar the limit fills (117/117), as does traversal (0/116 precede). Positive rule **[UNRESOLVED]** | What invalidation is *for*. Any zone-penetration trigger is logically incapable of firing before the fill; a non-geometric basis has no repository precedent |
| **Expiry** | **No — [UNRESOLVED]** | None. Distributions recorded (median 2.5 bars, p75 11.8, 83.8 % ≤24, 99.1 % eventually, max 1,464) | Expiry encodes how long a setup stays valid — a strategy claim. Selecting N from the fill distribution would fit a parameter to an outcome. Cannot be evidence-based until fills exist to evaluate |
| **CHoCH override** | **Yes (compatibility)** | **Remove it from the `LIMIT_FVG` path.** 13/13 override prices sit on the far side of the zone and cannot rest as a limit; all 13 setups survive as midpoint candidates. **This is a strategy change, not a neutral correction** | None for the incompatibility. Blocking only if you want a deliberately dual-model momentum path, which needs its own entry mode and specification |
| **Cross-session survival** | **No — [UNRESOLVED]** | None. Costs measured: 19.0 % cross a session, 8.6 % a daily break, 2.6 % a weekend; 3 fill in Dead/Closed | Whether the DEAD-session prohibition binds a *resting order* or only a *new decision*. The gate exists but lives in `main()`, not the decision path. Must be decided jointly with expiry |

---

*Evidence report complete. No code changed, no baseline touched, no parameter chosen, nothing implemented. Stopping for review.*
