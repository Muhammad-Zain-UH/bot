# A1–A4 / B1–B6 — result

Pre-registration: `research/atr_bar_convention_spec.md`, committed alone at
`c4ac045` before any migration existed.
Controls: `baselines/baseline_012` (pre-change), `baseline_013` (including B1),
`baseline_014` (**shipped**).

---

## Summary

**Shipped:** A2, A3, A4 collapsed onto `core.indicators.atr_wilder`; the
fabricated ATR defaults removed; B2, B3, B4, B5 moved onto `core.candles`. A1
was already correct and is asserted equal rather than edited.

**Not shipped:** B1, recorded **UNRESOLVED** at the site and in the register.

**The spec's own prediction was falsified**, and the measurement is what caught
it. Two figures previously reported in this programme were wrong and are
corrected here.

## 1. Four ATR definitions became one

| id | site | was | fault |
|---|---|---|---|
| **A3** | `sweep_detector._estimate_m15_atr` | `close.diff().abs().rolling(14).mean()` | **not an ATR.** Close-to-close only, blind to intrabar range |
| A2 | `pullback_detector._estimate_recent_atr` | true range, `rolling(14).mean()` | SMA not Wilder; `min_periods=3` allowed a "14-period ATR" from three observations |
| A4 | `main_production` `h1_atr` | `mean(high − low)` over 14 | ignored gaps **and** used an SMA |
| A1 | `indicators.py` | `pandas_ta.atr` | correct — verified equal to `atr_wilder` to 6 dp |

Measured over all **100,020** M15 bars of the frozen export:

| | median | mean | ratio to true |
|---|---|---|---|
| true Wilder ATR-14 | $3.084 | $4.776 | — |
| **A3 as coded** | **$1.516** | $2.365 | **0.475** |

A3 understated volatility by roughly **2.1×**. A2 and A4 each had **two** faults
rather than the one the register listed.

### Why A3 was the P0, and why it was my responsibility

`sweep_min` is `max(2.5 pips, m15_atr * 0.12)`. Before U8's unit fix the
constant bound on **98.8%** of bars, so `m15_atr` barely mattered. Correcting
U8's unit moved the floor from $2.50 to $0.25 and the ATR term began to bind —
so **my own earlier change promoted a non-ATR to setting the busiest gate in the
system** (L5 blocked 3,325 of 15,735 decisions in `baseline_012`).

The register had predicted exactly this coupling: *"That understated ATR sets
`sweep_min` (U8)."*

### Fabricated volatility removed

A2 and A3 returned silent defaults — `10.0` and `15.0` — on any short frame or
exception. At `×0.12` a default of 15.0 is a **$1.80** sweep floor, **seven
times** the $0.25 pip floor, invented from no data. Both now return `None` and
their callers decline, matching `execute_entry_signal`'s "no symbol
specification → no trade".

**Measured cost of that strictness: zero.** Across 15,735 decisions on real
data there were **no** "ATR unavailable" events.

## 2. Bar conventions made explicit

The premise was verified rather than assumed: `get_market_data` defaults
`closed_only=True` and **all three fetch paths honour it** — the primary and
last-resort calls use `start_pos = 1`, the range fallback applies `iloc[:-1]`
(`mt5_handler.py:46-135`). So `iloc[-1]` **is** the last closed bar.

That check exists because of U1: in the unit migration a parameter named
`buffer_pips` turned out to be the only evidence for its own units, and treating
the name as a specification produced a stop $0.95 from entry.

| id | fix |
|---|---|
| **B3/B4** (P0) | entry price and L8's `current_price` came from `iloc[-2]` — five minutes stale, the M1 leg two — while a **momentum** entry on the same pass used the current bar. Now `last_closed_bar()`. |
| B5 | `pullback_detector` applied `recent.iloc[:-1]` to an already closed-only frame: a **double-drop**, running detection two bars stale. Now `closed_bars()`, which is idempotent under `CLOSED_ONLY` — the bug `core/candles.py`'s own docstring already names. |
| B2 | `detect_momentum_confirmation`'s `current_volume` came from `iloc[:-1]`. Its `prev_rsi` **keeps** `iloc[:-1]` deliberately — that one wants the previous bar's RSI, which is intent, not a bug. |
| B6 | already correct; its inconsistency with B1/B2 is resolved by the others moving to it. |

## 3. B1 — implemented, measured, left UNRESOLVED

`detect_rejection_candle` reads `iloc[-2]` into a variable named `current`.

**For it being a defect:** the name; `iloc[-1]` is the last closed bar;
`detect_displacement_candle` in the same module reads `iloc[-1]` and the two are
alternative confirmations evaluated on one pass; `core/candles.py` lists the site
as "one bar stale".

**Against:** **both** integration fixtures place the rejection candle at
`iloc[-2]` and the break at `iloc[-1]`, and
`tests/fixtures/integration_market.TRIGGER_BARS` is commented *"two M5 candles:
rejection, then the break"* — a coherent entry pattern, and the only statement of
**intent** anywhere.

The fixtures are derived evidence — written to satisfy the code — so they do not
settle it. But nothing states the detector's intended bar either.

### The measurement that decided it

`baseline_014` (shipped, `iloc[-2]`) has a funnel **identical to `baseline_013`**
(last closed bar) at every one of eight layers across 15,735 decisions.

**B1 moves not one gate decision on real data.** The only thing sensitive to it
was two synthetic fixtures tuned against the old index — where it took signals to
zero and caused **60 of 64** test failures.

It is not neutral at the **fill** level: the same six signals resolved
differently (013: 2 wins/4 losses; 014: 4/2), because the rejection candle feeds
the pullback entry's geometry. **Six trades carries no performance information**,
so that is not evidence for either reading.

Resolving B1 needs both fixtures rebuilt to clear all eight layers with the
rejection candle last. An attempt rippled into POI scoring — the short fixture
dropped to 60 against a 70 threshold — so it is a separate measured pass.

## 4. The shipped funnel

`baseline_014` against `baseline_012`:

| blocked at | 012 | **014** | cause |
|---|---|---|---|
| L1_BIAS | 1,505 | **1,505** | untouched |
| L2_STRUCTURE | 12 | **12** | untouched |
| L3_PULLBACK | 5,044 | **5,039** | B5: one more closed bar |
| L4_LIQUIDITY | 2,142 | **2,089** | A3 via `sweep_min`/`sweep_max` |
| L5_SWEEP | 3,325 | **3,411** | A3 |
| L7_CONFIDENCE | 1,787 | **1,688** | more candidates reach it |
| L8_ENTRY | 1,917 | **1,985** | consequence of the above |
| **signals** | **3** | **6** | |

L1 and L2 byte-identical confirms nothing upstream was disturbed.

### The prediction this falsified

Spec §6 recorded, in advance: *"L5_SWEEP should tighten… signals may fall below
`baseline_012`'s 3"*, and *"if signals reach zero… measured, reported and put to
the user."*

On real data **L5 tightened by 86 decisions, L7 loosened by 99, and signals
doubled to 6.** The zero-signal outcome I first observed was a **fixture
artefact** — the fixtures are synthetic constructions tuned against the previous
ATR; `data/raw` is not. Without `baseline_013` the fixture result would have been
reported as the real one, and a user question would have been raised on a false
premise.

## 5. Two corrections to previously reported figures

**`UNIT_MIGRATION_REPORT.md` claimed U8's fix made `atr*0.12` bind on 73.7% of
bars.** That was measured with a *true* Wilder ATR while production computed A3.
The real figure at the time was **36.7%**, and the pip floor still dominated. It
is 73.7% again now that A3 is fixed.

Root cause: the measurement script and the production path computed the same
quantity two different ways and nothing checked they agreed. Now prevented by
`tests/core/test_atr_single_definition.py`, which asserts every strategy-path ATR
equals `atr_wilder` on real bars.

**A4's aggregate effect is smaller than its per-bar effect suggests.** The L2
block rate moves 87.60% → 88.25% over all H1 bars, but the per-bar ratio spans
**0.77 to 1.40** — because A4 had both a gap fault (which only raises true range)
and a smoothing fault (SMA vs Wilder, which can go either way).

Recorded at the site: A4's fix changes **what `L2_MIN_H1_RANGE_USD` is compared
against**. The floor's value is unchanged at 8.0 by the decision recorded at that
constant, but `h1_atr` is now a gap-aware true-range average, so the floor means
something slightly different even though the number did not move.

## 6. Found and deliberately not fixed

**U13/U14**, new register items: `near_buffer = max(2.5, atr * 0.20)` and
`momentum_buffer = max(5.0, atr * 0.50)` in `assess_liquidity_gate`. Bare floats
compared against a quote-currency distance — the same shape as U1–U12 but absent
from that enumeration, so outside this spec's scope.

Not folded in, for two reasons: their intent is unrecorded exactly as U1's was,
and they now sit beside a **corrected** ATR, so their weight relative to the
constants has already shifted. Whatever is done to them should be measured
against `baseline_014`, not against what came before it.

## 7. What this does not establish

Making four ATR definitions one creates no edge, and none is claimed. No
threshold was adjusted to compensate for the ATR change, which the spec forbade
explicitly — and the funnel moving as little as it did is a result, not a target
that was aimed at.

U9's L2 floor and U10's regime bands remain **absolute** by the decision recorded
at both sites, so the system's behaviour still drifts with gold's price level.
Fixing that means re-deriving the regimes from the volatility distribution, which
is strategy design and needs its own pre-registration.
