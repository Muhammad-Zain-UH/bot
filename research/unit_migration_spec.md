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

This is chosen because it has **no fitted quantity**. The median close is a
property of the frozen dataset, not a parameter; the behaviour at the median is
preserved exactly; and the drift away from the median is removed. Anchoring to
any *other* point — a chosen era, a "representative" year — would be a decision
about which regime matters, and this rule avoids making one.

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
  Where Rule 1 and Rule 2 both apply, they fully determine the result. Where a
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

## 6. What this cannot establish

The migration makes the thresholds mean what they claim and stop re-tuning
themselves as gold's price moves. It does **not** create an edge, and nothing in
the result should be read as evidence of one. 138 pre-registered tests across
five hypotheses found no edge in this data at these horizons and costs, and
correcting a unit does not change that.

What it does change is that a gate which admitted no bars at all in 2017–18 was
never actually asking the question it was written to ask.
