# ATR fragmentation (A1–A4) and bar conventions (B1–B6) — specification

**Pre-registered.** Committed **alone**, before any migration and before any
post-change measurement exists, in the same discipline as
`research/unit_migration_spec.md` and the six hypothesis specs. Git is the
evidence.

Pre-change control: `baselines/baseline_012` (the retained configuration,
fingerprint `f5bf2a00…`).

---

## 1. Why this is being done now, and why it is my error

`PHASE_2_ISSUES.md`'s Phase 4 specifies: *"U1–U12, A1–A4, B1–B6 together, one
coherent change, measured against the Phase 3 baseline."*

I migrated only U1–U12. That was not a smaller version of the same change — it
left the other two thirds of one coherent change undone, and in one place it made
things actively worse:

**Correcting U8's unit promoted a broken estimator to load-bearing.** U8's floor
is `max(2.5 pips, m15_atr * 0.12)`. Before the unit fix the constant bound on
98.8% of bars, so the ATR term was dead code. After it, the ATR term matters —
and `m15_atr` comes from **A3**, which is not an ATR.

The register predicted this exact coupling before I made it: *"That understated
ATR sets `sweep_min` (U8)."*

**And a figure in `research/UNIT_MIGRATION_REPORT.md` is wrong because of it.**
That report claims the unit fix made `atr*0.12` bind on **73.7%** of bars. The
measurement script computed a *true* Wilder ATR; production computes A3. With the
estimator actually in the code the figure is **36.7%**. The qualitative
conclusion holds — the branch did come alive — but the number is overstated and
is corrected as part of this work.

## 2. What is wrong, measured before changing anything

### A — four incompatible ATR definitions

Measured on all 100,020 M15 bars of the frozen export:

| | median | mean | ratio to true Wilder |
|---|---|---|---|
| true Wilder ATR-14 | $3.084 | $4.776 | — |
| **A3 as coded** | **$1.516** | $2.365 | **0.475** |

| id | site | definition | why it is wrong |
|---|---|---|---|
| **A3** | `sweep_detector._estimate_m15_atr` | `close.diff().abs().rolling(14).mean()` | **close-to-close only.** Cannot see intrabar range at all, so a wide-range bar reports a small value. Understates by ~2.1×. **P0** |
| A2 | `pullback_detector._estimate_recent_atr` | true range but **SMA-14** | not Wilder smoothing |
| A4 | `main_production` `h1_atr` | `mean(high − low)` over 14 | **ignores gaps** (no previous-close terms) |
| A1 | `indicators.py:130` | `pandas_ta.atr` | correct; to be *asserted*, not edited |

**A2 and A3 also fabricate readings.** They return silent defaults (`10.0`,
`15.0`) when data is short. At `×0.12`, a default of 15.0 is a **$1.80** sweep
floor — **7× the $0.25 pip floor** — invented from no data.
`core.indicators.atr_wilder` raises `InsufficientBarsError` instead.

### B — six disagreeing bar accesses

| id | site | uses | effect |
|---|---|---|---|
| **B3** | `entry_engine.py:650,654` | `iloc[-2]["close"]` | **entry priced off a stale bar**; the M1 one is 2 minutes stale. **P0** |
| **B4** | `main_production.py:1261` | `iloc[-2]["close"]` | stale price passed as `current_price` into L8. **P0** |
| B5 | `pullback_detector.py:221` | `recent.iloc[:-1]` | **double-drop** — removes a forming bar that is not there, so detection is two bars stale |
| B1 | `entry_engine.py:158` | `iloc[-2]` | one bar stale |
| B2 | `entry_engine.py:196` | `iloc[:-1].tail(3)` | one bar stale |
| B6 | `entry_engine.py:228` | `iloc[-1]` | **correct**, and therefore inconsistent with B1/B2 in the same pass |

Consequence: **a pullback entry is priced off a bar that closed five minutes ago
while a momentum entry on the same pass uses the current one**, on a strategy
targeting 15–25 pip moves.

### The premise, verified rather than assumed

B1–B6 all rest on `get_market_data(closed_only=True)` already dropping the
forming bar, so `iloc[-1]` **is** the last closed bar. Verified in
`mt5_handler.py:46-135`: `closed_only=True` is the default and **all three fetch
paths honour it** — primary and last-resort use `start_pos = 1`, the range
fallback applies `iloc[:-1]`.

This was checked because of the U1 lesson from the unit migration: **a claim in a
document is not a specification.** U1's `buffer_pips` name was the only evidence
for its intent and turned out to be wrong. Here the claim is independently
confirmed in the code, so the migration proceeds.

## 3. The rule

Mechanical, with a declared answer, and therefore correctness rather than tuning:

1. **Every ATR in the strategy path becomes `core.indicators.atr_wilder`.**
2. **Every bar access becomes an explicit `core.candles` call** —
   `last_closed_bar`, `previous_closed_bar`, `closed_bars` — rather than a raw
   index, so each site states which bar it reads.
3. **Silent defaults are removed.** A frame too short to support an ATR yields
   `None` and the caller **declines**, matching
   `execute_entry_signal`'s "no symbol specification → no trade" pattern.
4. **A1 is asserted, not edited.** It is already correct; a test pins that it
   agrees with `atr_wilder`.

No coefficient is chosen. No threshold is moved.

## 4. Forbidden

* **No threshold may be adjusted to compensate.** Not `0.12`, not `2.0`, not
  `sweep_min`, `sweep_max`, `SWEEP_MIN_PIPS`, `SWEEP_MAX_PIPS`,
  `L2_MIN_H1_RANGE_USD`, nor any regime band.

  A true ATR is roughly **2.1×** A3's value, so `sweep_min` will rise through the
  `×0.12` term and **L5 will tighten**. That is the measurement. Retuning a
  threshold to hold the funnel still would convert a correctness fix into a
  fitted one and destroy the only thing this change has going for it.

* **No selection by output.** Not by trade count, win rate, P&L or funnel shape.
* **No claim of improvement.** Making four definitions one creates no edge.
* `LIVE_TRADING_ENABLED` stays `False`. FINAL_OOS stays locked.
  `baseline_004`, `008`, `009`, `012` stay byte-identical.

## 5. Success criteria — structural, not performance

Declared in advance, and deliberately **none of them is a return figure**:

1. **No module outside `core/` computes its own ATR.** Verified structurally: no
   `close.diff()`, `rolling(14).mean()` or `mean(high - low)` ATR surrogate
   survives in the strategy path.
2. **No ATR path returns a fabricated default.** A short frame declines.
3. **Every migrated bar site reads the bar its comment claims**, verified
   against `core.candles`.
4. **A1 agrees with `atr_wilder`** to within float tolerance on real bars.
5. **Full suite green** and `production_path_verification.py` **10/10**.
6. **The funnel change is reported in full**, `baseline_013` against
   `baseline_012`, whatever it shows.

## 6. What is expected to happen, recorded before it does

So the result cannot be presented as a surprise or as a success either way:

* **L5_SWEEP should tighten.** `sweep_min` roughly doubles via `×0.12`, so fewer
  candles qualify as sweeps. L5 blocked 3,325 of 15,735 decisions in
  `baseline_012`; expect more.
* **L2 may move.** A4 feeds `h1_atr`, which the L2 floor compares against.
  `L2_MIN_H1_RANGE_USD` stays at 8.0 by the decision recorded at that site, but
  a gap-aware ATR is a *different quantity*, so the floor's **meaning** changes
  even though its value does not. To be recorded there.
* **Signals may fall below `baseline_012`'s 3.** Three trades carry no
  performance information in either direction; the funnel is the measurement.

**If signals reach zero**, that is the situation Rule 2 produced in the unit
migration. It will be **measured, reported and put to the user** — not silently
kept and not silently reverted.

## 7. What this does not address

* **U9 and U10 remain absolute** by the decision recorded at both sites, so the
  L2 floor and the regime bands still drift with gold's price level.
* **The regime bands remain era-dependent.** Fixing that means re-deriving the
  regimes from the volatility distribution, which is strategy design and needs
  its own pre-registration.
* **U8's `0.12` and `2.0` remain unvalidated.** This change makes them act on a
  *correct* ATR, which is strictly better than acting on a wrong one, but it does
  not validate them. They were unreachable when written.
