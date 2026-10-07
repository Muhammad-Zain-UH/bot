# Unit migration U1–U12 — specification

**Pre-registered.** This document is committed **before** the migration is
implemented and before any post-migration measurement exists, in the same
discipline as the five hypothesis specs. Its purpose is to fix the migration
*rule* in advance, so that the thresholds which come out of it cannot be
mistaken for — or quietly turned into — thresholds chosen because their results
looked better.

Evidence base: `research/UNIT_MIGRATION_EVIDENCE.md` and
`research/unit_migration_evidence.json`.
Pre-migration control: `baselines/baseline_009` (fingerprint
`e1293df1…c63fe4e97`, identical to `baseline_008`).

---

## 1. The two distinct defects

`PHASE_2_ISSUES.md` section 1 treats U1–U12 as one defect class, "unit
confusion". The measurement shows it is **two**, and they need different fixes.

**Defect A — mislabelled unit.** A threshold named "pips" applied to a raw
price. On XAUUSD 1 pip = $0.10, so the threshold is **10× its intended size**.
Confirmed at exactly 10.0× for U1–U9. This has a *declared* correct answer: the
value the name always claimed.

**Defect B — absolute scale.** The threshold is expressed in absolute dollars on
a series that went **$951 → $4,173**, so its selectivity is a function of the
price level rather than of the market. U9 admitted **0.00%** of 2017–18 bars and
**100.00%** of 2026 bars. This has **no declared correct answer**, and fixing
Defect A does not fix it.

U10 is the proof they are separate: its regime bands are **not** 10× wrong — read
as dollars they produce a sensible spread of regimes — yet they drift hardest in
consequence, because the regime selects risk-per-trade (0.75 / 1.0 / 1.5 %).

## 2. The migration rule

Declared in advance, mechanical, and with **no free parameter**.

**Rule 1 — restore the declared unit.** Where a threshold's name says pips and
the code compares it to a price, express it with `core.units.Pips` and convert
through the instrument's `SymbolSpecification`. The target is the value the name
always asserted; this is a correctness fix with a known answer, not a search.

**Rule 2 — make it scale-invariant at the median.** Convert each absolute
threshold to a fraction of price, calibrated so that it is **numerically
unchanged at the dataset's median close** and scales from there.

For a threshold $T$ dollars and median close $P_{med}$:

```
fraction = T / P_med        threshold(price) = fraction * price
```

The behaviour at the median is preserved exactly, and the drift away from it is
removed.

### Correction: Rule 2 does not eliminate the free parameter, it relocates it

The first draft of this rule claimed "no fitted quantity". That was wrong, and
testing the rule before implementing it is what caught it.

**The anchor is itself a parameter.** The timeframes cover different eras, so
their medians differ enormously — H1 $1,544 (2009–2026), M15 $2,457 (2022–2026),
M5 $4,175 (2025–2026), H4 $1,316 (2004–2026). For U9's $8.00 floor:

| anchor | fraction | blocks, 17-yr average |
|---|---|---|
| H1 median $1,544.08 | 0.5181 % | ~95 % of bars |
| M5 median $4,175.05 | 0.1916 % | far fewer |

So the anchor sets the gate's selectivity almost as directly as the dollar
threshold did. There is **no parameter-free repair**: an absolute threshold can
only be replaced by another parameterisation, and every alternative hides a
constant somewhere — a percentile rule hides the percentile, and calibrating to
reproduce the current pass rate fits the sample outright.

**What Rule 2 does achieve, and it is verifiable in advance:** it removes the
*price-level dependence*, which is the actual defect. Measured on U9 before
implementing anything:

* absolute $8.00 → best-to-worst-year spread **100.0 pp** (0.0 % to 100.0 %)
* fraction 0.5181 % → spread **30.1 pp** (69.9 % to 100.0 %)

**The declared anchor is the H1 median close, $1544.08**, for every site
regardless of the timeframe it is applied on. Reason: H1 is the series this
research programme already treats as its reference — `research_split_manifest_h1.json`
defines TRAIN/DEV/FINAL_OOS on it — and it is the deepest series with full bar
coverage (100,001 bars, 2009–2026). One anchor is used everywhere so that the
choice of timeframe cannot change a threshold.

This is a **declared choice with a stated reason, fixed before any outcome was
measured** — not a derived quantity, and this document no longer claims it is
one. A different anchor would give different selectivity, and that is recorded
here so the result is never presented as inevitable.

**Rule 3 — where a scale-invariant term already exists, make it primary.** U8 is
`max(2.5, m15_atr * 0.12)`. The ATR term is already scale-invariant and already
written; the constant is what breaks it. Promote the ATR term and keep a
pip-denominated floor for degenerate low-volatility bars.

**Rule 4 — name every newly-binding parameter.** Where Rule 3 shifts the binding
constraint onto a coefficient that was previously dead code, that coefficient
becomes a live, unvalidated parameter and is recorded as such. U8's `0.12` binds
on 1.2 % of bars today and would bind on nearly all of them afterwards. It has
never been validated against anything.

## 3. What is forbidden

* **No threshold may be selected, adjusted or rejected on the basis of any
  backtest output** — not trade count, not win rate, not P&L, not funnel shape,
  not "the pass rate looks more sensible". The rule above determines every value.
* **No new ATR or percentage coefficient may be invented** where none exists.
  Given the declared anchor, Rule 1 and Rule 2 together determine every value
  mechanically; the anchor itself is declared once, above, and not revisited per
  site. Where a
  site needs a coefficient the codebase has never declared, the site is migrated
  under Rules 1–2 only and the residual recorded as open.
* **No claim of improvement.** The migration's success criterion is that the
  thresholds mean what they say and stop drifting with the price level. Whether
  that produces better trading is a separate question this cannot answer.
* `LIVE_TRADING_ENABLED` stays `False`; FINAL_OOS stays locked;
  `baseline_004`, `baseline_008`, `baseline_009` stay byte-identical.

## 4. Sites, and which rule applies

| id | site | Defect A (10×) | Defect B (absolute) | rule |
|---|---|---|---|---|
| U1 | `entry_engine.py:380` stop buffer | yes | yes | 1 + 2 |
| U2 | `liquidity_engine.py:350` proximity bonus | yes | yes | 1 + 2 |
| U3 | `liquidity_engine.py:358,363` distance penalty | yes | yes | 1 + 2 |
| U4 | `liquidity_engine.py:754` max sweep distance | yes | yes | 1 + 2 |
| U5 | `poi_engine.py:441` zone-size band | yes | yes | 1 + 2 |
| U6 | `poi_engine.py:427` displacement | yes | yes | 1 + 2 |
| U7 | `poi_engine.py:191,229` order-block body | yes | yes | 1 + 2 |
| U8 | `sweep_detector.py:196` sweep minimum | yes | yes | **3 + 4** |
| U9 | `main_production.py` L2 floor | fixed already | yes | 2 |
| U10 | `entry_engine.py:92-124` regime bands | **no** | yes | **2 only** |
| U11 | `main_production.py` inline `pip_size` | — | — | use the spec |
| U12 | `mt5_handler.py:150` hardcoded pip size | — | — | use the spec |

## 5. Measurement, declared before it is taken

**Primary measurement — gate selectivity across price regimes.** For each
migrated threshold, the share of bars it admits, by year, over the deepest
history that timeframe has (H1 2009–2026, M15 2022–2026, M5 2025–2026). The
pre-declared success criterion:

> **The spread between a threshold's best and worst year falls.**

That is the whole point of the migration and it is measurable on 100,001 bars.
Current spreads: U9 **100.0 pp**, U8 **60.9 pp**, U7 **37.3 pp**.

**Secondary measurement — layer interaction.** The L1–L7 funnel over the deep
history, obtained by calling `analyze_entry(..., m1_data=None)`. This needs no
change to the strategy: L8 already requires `m1_data` and already records
`L8_ENTRY` when it is absent, so L1–L7 are measurable wherever M5 and M15 exist.
Decisions are subsampled to one per hour; that changes the decision *population*
and no cross-comparison with `baseline_009`'s per-M5-bar funnel is made.

**Control — `baselines/baseline_009`.** Re-run after the migration on identical
data and assumptions. Reported in full.

### The limitation that bounds the control, stated in advance

`baseline_009`'s window is **2026-06-02 → 2026-09-16**, bound by the broker's M1
floor of 2026-06-17. Gold is above $4,000 throughout — **precisely the era in
which these absolute thresholds are least restrictive.** L2 blocks 0.0 % of 2026
bars against 100.0 % of 2017–18 bars.

So the baseline control **cannot exercise the defect this migration fixes**, and
a small funnel change there is not evidence that the migration is small. The
primary measurement exists because of this, and it is the one that carries
weight. This is a data limit, not a tooling limit: re-exporting does not help,
because the broker holds no deeper M1.

## 5a. Outcome against this specification (added after execution)

Recorded here so the spec and its result are not read apart. Full detail in
`research/UNIT_MIGRATION_REPORT.md`.

* **Rule 1 kept at 9 of 10 sites.** U2-U8, U11, U12 migrated to typed `Pips`.
* **Rule 1 reverted at U1.** Its premise -- that the name carries a declared
  answer -- does not hold there. Two repo docs already recorded U1 as
  **UNRESOLVED**, the name was the only evidence, and $0.30 is ~1.5 round trips
  through the assumed spread. At $0.30 the short fixture's stop sat $0.95 from
  entry and was hit on the next bar. Value kept at $3.00, unit made explicit.
* **Rule 2 implemented, measured, reverted.** It met its criterion (U9 drift
  100.0pp -> 30.1pp) and took signals from 4 to **0** (`baseline_010`). The
  revert was chosen over picking a reference price that kept the strategy
  trading, which this document forbids.
* **Rule 3 achieved by Rule 1 alone.** U8's dead `atr*0.12` branch went from
  binding on 1.2% of bars to 73.7% once the constant was corrected. No
  coefficient was invented.
* **Rule 4 honoured.** U8's `0.12` and `2.0` are recorded in place as newly
  live and never validated.

### The criterion in §5 was flawed, and the measurement exposed it

> *the spread between a threshold's best and worst year falls*

Met at U8 (60.6 -> 7.1pp), U9 (100.0 -> 30.1pp) and U7 (37.3 -> 31.6pp).
**Failed at U6** (3.6 -> 57.6pp) -- because at $20.00 that threshold fired on
0.03-3.7% of bars. It was effectively **inert**, and an inert threshold has
trivially low drift.

So the criterion cannot distinguish *stable because scale-invariant* from
*stable because it never fires*. A better one would condition on the threshold
being active. Recorded rather than quietly dropped.

## 6. What this cannot establish

The migration makes the thresholds mean what they claim and stop re-tuning
themselves as gold's price moves. It does **not** create an edge, and nothing in
the result should be read as evidence of one. 138 pre-registered tests across
five hypotheses found no edge in this data at these horizons and costs, and
correcting a unit does not change that.

What it does change is that a gate which admitted no bars at all in 2017–18 was
never actually asking the question it was written to ask.
