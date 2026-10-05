# Unit migration U1–U12 — result

Pre-registration: `research/unit_migration_spec.md` (committed before any
implementation, and amended once — before implementation — to correct an
overclaim in its own rule).
Evidence: `research/UNIT_MIGRATION_EVIDENCE.md`.
Controls: `baselines/baseline_009` (pre-migration), `baselines/baseline_010`
(full migration, both rules).

---

## Summary

**Rule 1 — restore the declared unit — was applied everywhere and kept.** Ten
thresholds across five modules were 10× their intended size because a value
named in pips was compared against a raw price. Each now goes through
`core.units.Pips` and the instrument specification.

**Rule 2 — make the threshold scale-invariant — was implemented, measured end to
end, and reverted.** It did what it was designed to do, and the end-to-end
consequence was that the strategy produced **zero signals**.

Both outcomes are reported because both were pre-declared as possible. The
success criterion was fixed in advance and was not a performance figure.

## 1. Rule 1: what was wrong, and what it is now

| id | site | was | is | effect |
|---|---|---|---|---|
| **U1** | `entry_engine` stop anchor | $3.00 | **$3.00** | **not changed** — see §1a |
| **U8** | `sweep_detector` min wick | $2.50 | $0.25 | see below — the important one |
| U8 | `sweep_detector` max wick | $30.00 | $3.00 | ceiling never rejected anything |
| U2 | `liquidity_engine` proximity | $2.00 | $0.20 | bonus fired too readily |
| U3 | `liquidity_engine` penalties | $50 / $30 | $5.00 / $3.00 | penalties never fired |
| **U4** | `liquidity_engine` sweep cap | $60.00 | $6.00 | 600 pips — no cap at all |
| U5 | `poi_engine` zone band | $5–15 | $0.50–1.50 | bonus essentially never fired |
| U6 | `poi_engine` displacement | $20 / $10 | $2.00 / $1.00 | fired on 0.03% of bars |
| U7 | `poi_engine` body | $5.00 | $0.50 | fired on 1.4% of bars |
| U11 | `main_production` inline pip size | literal `0.10` | from the spec | duplicated broker data |
| U12 | `mt5_handler` pip size | literal `0.10` | from the spec | would break silently on a precision change |

Every one is now a typed `Pips` constant, so the comparison cannot silently
revert to a raw price — `Pips(2.5).to_price(spec)` is $0.25, where a bare `2.5`
was $2.50.

### 1a. U1 was the one site where Rule 1's premise did not hold

Rule 1 claimed every site had "a genuinely declared answer — the value the name
always claimed." For nine sites that is true, and two of them are
self-corroborating: `sweep_detector`'s docstring independently says "Wick
penetration: 3-8 **pips** below pool", and `poi_engine`'s comment reads "Size
bonus (+15 for 5-15 **pips**)". The name is not the only evidence there.

**For U1 it was.** And this repository had already declined to settle it:

* `docs/BASELINE_005_PROVENANCE.md` lists it as a question —
  *"U1 — **is** the `$3.00` stop buffer intended as 3 pips?"*
* `docs/BROKER_SYMBOL_SPECIFICATION_EVIDENCE.md` records *"U1 stop buffer —
  **UNRESOLVED**"*

The 3-pip reading was implemented, measured, and rejected on evidence:

| | $3.00 (kept) | $0.30 (rejected) |
|---|---|---|
| short fixture stop distance | $3.65 | **$0.95** |
| short fixture outcome | TARGET_HIT | **STOPPED on bar 1** |
| vs. the assumed round-trip spread ($0.40) | 9× | **2.4×** |

`execution/fills.py` assumes a 2.0 pip spread, so a 3-pip buffer is roughly 1.5
round trips — a stop the bid/ask alone can take out. On the short fixture it
was: noise decided the outcome, not structure.

So U1 keeps **$3.00**, now expressed as a typed `Pips(30.0)` so the unit is
explicit at the call site. That is **not** an endorsement of the value. It is a
refusal to move stop placement on the authority of a variable name, and the
intent remains **UNRESOLVED** exactly as the repo already had it.

The general lesson, and it applies to the whole migration: *a parameter name is
not a specification.* Rule 1 is sound where the name is corroborated and unsound
where it stands alone.

### The best result: correcting a unit resurrected dead code

`sweep_detector.py` reads `sweep_min = max(2.5, m15_atr * 0.12)`. The `max()`
makes it look scale-aware. It was not: the ATR term exceeds the constant only
when M15 ATR > $20.83, the **99th percentile**, so the absolute constant bound on
**98.8%** of bars and the one scale-invariant term in the module was effectively
dead code.

With the floor at its intended $0.25, `m15_atr * 0.12` binds on **73.7%** of
bars. Fixing the unit made the scale-aware branch live **without inventing any
coefficient**. This is the single most valuable change in the migration.

Recorded per Rule 4: `0.12` and `2.0` are now the binding parameters, and they
have never been validated against anything. They were unreachable when written.

## 2. The pre-declared criterion, and where it failed

> **The spread between a threshold's best and worst year falls.**

| site | before | after | verdict |
|---|---|---|---|
| U8 sweep minimum | 60.6 pp | **7.1 pp** | met |
| U9 L2 floor (Rule 2) | 100.0 pp | **30.1 pp** | met |
| U7 order-block body | 37.3 pp | 31.6 pp | met |
| **U6 displacement** | 3.6 pp | **57.6 pp** | **failed** |

**U6 failed, and the failure is informative about the criterion rather than the
fix.** At $20.00 the threshold fired on 0.03–3.7% of bars: it was effectively
**inert**, and an inert threshold has trivially low drift. Correcting the unit
made it live, and a live *absolute* threshold drifts.

So the criterion as written cannot distinguish **"stable because
scale-invariant"** from **"stable because it never fires."** That is a flaw in my
pre-declared criterion, not a reason to call U6's fix wrong — and it is recorded
here rather than quietly dropped. A better criterion would condition on the
threshold being active.

## 3. Rule 2: implemented, measured, reverted

Rule 2 scaled a threshold by the prevailing price, calibrated to be unchanged at
a declared reference (the H1 median close, $1,544.08). Applied to U9 (the L2
volatility floor) and U10 (the regime bands).

**It worked as designed.** U9's drift fell 100.0 → 30.1 pp. U10's fell: DEAD_CALM
34.6 → 16.2 pp, INTRADAY_SWING 23.0 → 1.7 pp.

**And it took the strategy to zero signals.** `baseline_010` against
`baseline_009`, identical data and assumptions:

| blocked at | 009 | 010 | delta |
|---|---|---|---|
| L1_BIAS | 1,505 | **5,950** | +4,445 |
| L2_STRUCTURE | 12 | **7,533** | +7,521 |
| L3_PULLBACK | 5,044 | 962 | −4,082 |
| L4_LIQUIDITY | 748 | 536 | −212 |
| L5_SWEEP | 5,000 | 409 | −4,591 |
| L7_CONFIDENCE | 1,835 | 208 | −1,627 |
| L8_ENTRY | 1,585 | 137 | −1,448 |
| **signals** | **4** | **0** | **−4** |

85.7% of 15,735 decisions died at L1 or L2.

### Why, precisely

Gold's M5 ATR has a median of **0.1016% of price**. The scaled MICRO_SCALP floor
sits at **0.1619%** — the **84th percentile** of relative volatility. So ~85% of
bars classify `DEAD_CALM`, and `DEAD_CALM` blocks at L2.

There is a second, indirect effect that the funnel makes visible and that I had
not predicted. `use_fast_bias` is true only for the scalp regimes, so
reclassifying bars as `DEAD_CALM` also switches L1 from the H1 fast bias to the
stricter H4 bias. That is why L1_BIAS blocks nearly quadrupled even though
nothing in L1 was touched.

### The finding

Expressed relatively, the inherited `2.5` edge sat at the **84th percentile** of
volatility at $1,544 gold and the **12th percentile** at $4,550. **It was never
one threshold.**

So there is no price-scaled form that preserves an intent these numbers never
carried. The strategy produced signals at all only because its thresholds were
accidentally calibrated to a particular price level — and the level that made it
active was the recent, high one.

### Why this is a revert and not a retune

A reference price that kept the strategy trading was available: anchoring at the
M5 median ($4,175) instead of the H1 median ($1,544) gives a far looser gate.
Choosing it would have been selecting a threshold by its effect on output, which
the spec forbids explicitly.

The honest options were therefore *scale it and produce nothing*, or *leave it
absolute and say so*. Rule 2 is reverted for U9 and U10; the absoluteness is
documented in place, at both sites, with these measurements. `core/thresholds.py`
is retained, tested and unused by the gates — the tool is correct, and the
problem it solves is still open.

## 3a. The retained configuration, measured

`baselines/baseline_012` is the record of what was kept. Against the
pre-migration control on identical data and assumptions:

| blocked at | 009 pre-mig | **012 retained** | delta |
|---|---|---|---|
| L1_BIAS | 1,505 | **1,505** | 0 |
| L2_STRUCTURE | 12 | **12** | 0 |
| L3_PULLBACK | 5,044 | **5,044** | 0 |
| L4_LIQUIDITY | 748 | **2,142** | +1,394 |
| L5_SWEEP | 5,000 | **3,325** | −1,675 |
| L6_POI | 2 | 0 | −2 |
| L7_CONFIDENCE | 1,835 | 1,787 | −48 |
| L8_ENTRY | 1,585 | 1,917 | +332 |
| **signals** | **4** | **3** | **−1** |

**L1, L2 and L3 are byte-identical**, which confirms two things at once: Rule 2's
revert is complete, and Rule 1 touches nothing upstream of L4. Every change sits
in exactly the layers whose thresholds were migrated — L4 (U2/U3/U4), L5 (U8),
and L8 as a consequence of both.

The largest single effect is **L4_LIQUIDITY tripling**, because U4's cap went
from $60 — 600 pips, so no effective cap — to $6.00 and began rejecting distant
pools for the first time.

The strategy remains active at 3 signals, which is the material difference from
Rule 2's zero.

## 4. What remains open

* **U9 and U10 are still absolute**, and their drift is unfixed. Recorded at
  both sites so it cannot be rediscovered as a surprise.
* **U8's `0.12` and `2.0` are now live and unvalidated.**
* **Fixing U10 properly means re-deriving the regimes** from the volatility
  distribution rather than rescaling inherited constants — percentiles of
  relative volatility would be scale-invariant by construction. That is strategy
  design, not a correctness fix, and is not done here.
* **U5's band is wrong in both directions.** As-is it is becoming common
  (4.49% → 65.79% of bars); as-intended it has already become almost
  unreachable (36.86% → 0.03%). Rule 1 moved it to the second of those.

## 5. What this does not establish

The migration makes ten thresholds mean what their names always claimed. It does
**not** create an edge, and no result here should be read as evidence of one.

No threshold was selected, adjusted or rejected on the basis of trade count, win
rate, P&L or funnel shape. The only output-driven decision in this document is
the **revert**, and it was a decision to *stop* a change, taken because the
alternative was to choose a reference price by its effect on signal count.

`baseline_010` is retained as the record of what full scale-invariance does. It
produced zero trades, so it carries no performance information in either
direction — and neither does `baseline_009`'s four.
