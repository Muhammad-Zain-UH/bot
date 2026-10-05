# Unit migration: what each threshold actually does

Regenerate with `python research/unit_migration_evidence.py`. Read-only;
**FINAL_OOS is not inspected.** Measured on `data/research_v1/bars/`, the frozen
hashed export (H1 100,001 bars 2009-2026; M15 100,020 bars 2022-2026; M5 100,058
bars 2025-2026).

`PHASE_2_ISSUES.md` section 1 lists twelve unit-confusion defects and says they
must be migrated **together** and **behind a backtest**, because they interact.
It does not say how large any of them is. This supplies that, so the migration is
driven by measurement rather than by the register's ranking assertion.

On XAUUSD **1 pip = $0.10**, so a threshold named "pips" and applied to a raw
price is **10×** its intended size.

## 1. Every mislabelled threshold is exactly 10× — and every one drifts

| id | site | as-is | as-intended | clears as-is | clears as-intended | **drift** |
|---|---|---|---|---|---|---|
| **U8** | `sweep_detector.py:196` | $2.50 | $0.25 | 20.11% | 92.75% | **60.9 pp** |
| **U7** | `poi_engine.py:191,229` | $5.00 | $0.50 | 11.51% | 74.85% | 37.3 pp |
| **U6** | `poi_engine.py:427` | $20.00 | $2.00 | 0.75% | 33.12% | 3.6 pp |
| **U9** | `main_production.py` L2 | $8.00 | $0.80 | 12.40% | 100.00% | **100.0 pp** |

"Drift" is the spread between the threshold's best and worst year, in percentage
points. It is the number that matters, and it is the reason this is not a
divide-by-ten exercise.

## 2. The finding: these are not *mis-sized*, they are *absolute*

A threshold that is 10× too large is wrong by a knowable amount and can be
corrected once. A threshold expressed in **absolute dollars** on a series that
went **$951 → $4,173** silently re-tunes itself every year, and dividing it by
ten does not fix that.

**U9, the L2 volatility floor** — `h1_atr < 8.0`, where clearing it means the
gate does *not* block:

| year | mean price | mean H1 range | clears the floor |
|---|---|---|---|
| **2017** | $1,258 | $2.34 | **0.00%** |
| **2018** | $1,269 | $2.31 | **0.00%** |
| 2015 | $1,160 | $2.90 | 0.10% |
| 2020 | $1,773 | $6.03 | 17.17% |
| 2024 | $2,389 | $6.04 | 15.06% |
| 2025 | $3,443 | $11.48 | 68.64% |
| **2026** | $4,550 | $24.01 | **100.00%** |

In 2017 and 2018 this gate admitted **no bars at all**. In 2026 it admits every
one. Same code. It is not a volatility filter; it is a proxy for whether gold has
got expensive yet. This is consistent with the production record of **39,709
decisions producing zero entry signals**.

## 3. U8 is the highest-leverage item, and the obvious fix is wrong

`sweep_min = max(2.5, m15_atr * 0.12)`

The `max()` makes this look scale-aware. It is not:

- the ATR term exceeds the constant only when M15 ATR > **$20.83**, the **99th
  percentile**
- so on **98.8%** of bars the **absolute constant binds**, and the
  scale-invariant branch is **effectively dead code**

U8 is the busiest gate in the system — `baseline_008` blocked **5,000 of 15,735
decisions at L5_SWEEP**, and this is that gate's threshold.

**Correcting only the unit would be a mistake.** $2.50 → $0.25 moves the pass
rate from 20.11% to **92.75%**, which is not a sweep filter at all: a "liquidity
sweep" that needs only a $0.25 wick is any candle. The ATR coefficient `0.12`
would then become the real parameter, and it has never been validated.

So the correct migration for U8 is to make the gate **scale-invariant** — let the
ATR term do the work and keep a pip-denominated constant only as a floor for
degenerate low-volatility bars. That changes which parameter matters, and the new
binding parameter is unvalidated. **That must be stated, not hidden in a pass
rate that looks reasonable.**

## 4. U5 shows why a band is worse than a floor

`if 5 <= zone_size <= 15: score += 15`

| year | mean price | in as-is band ($5–15) | in as-intended band ($0.50–1.50) |
|---|---|---|---|
| 2022 | $1,729 | 4.49% | 36.86% |
| 2023 | $1,943 | 4.70% | 41.11% |
| 2024 | $2,389 | 11.34% | 20.69% |
| 2025 | $3,443 | 38.13% | 4.42% |
| 2026 | $4,550 | 65.79% | **0.03%** |

A floor becomes monotonically easier as the price level rises. A **band** moves
zones *through* it and out the top, so the bonus becomes common and then rare
again. Note that **neither** band is right: the as-is band is becoming common,
and the as-intended band has already become almost unreachable. Dividing by ten
would replace a threshold that is currently too loose with one that is already
too tight.

## 5. U10 is the exception that proves the diagnosis

`detect_regime`'s M5 ATR bands `2.5 / 4.5 / 7.0`, labelled "pip":

| | 2025 (mean $3,673) | 2026 (mean $4,550) |
|---|---|---|
| `DEAD_CALM` | 35.06% | **0.47%** |
| `MICRO_SCALP` | 43.03% | 31.94% |
| `REGIME_SCALP` | 17.35% | 40.00% |
| `INTRADAY_SWING` | 4.56% | **27.59%** |

Unlike the others, these bands are **not wrong by a factor of ten**: read as
dollars they produce a sensible spread of regimes. The defect is purely that they
are **absolute**.

And the consequence is the most serious one in this document, because the regime
selects **risk-per-trade** (0.75% / 1.0% / 1.5%). Over thirteen months, with no
code change, the share of bars in the highest-risk regime went **4.56% → 27.59%**.
The account's risk per trade escalated by a factor of six because gold got
expensive.

That is the clearest statement of the whole defect class: **the system's risk
appetite is a function of the price level, and nobody chose that.**

## 6. What this document does not do

It **selects no threshold.** The pass rates describe what a candidate value would
admit. Using them to choose a value would be fitting — a threshold picked because
its pass rate looks reasonable is a threshold fitted to the sample — and that is
precisely what the register warns against.

No trade count, P&L, win rate or return figure appears anywhere in this analysis.
The measurement is of **gate selectivity against bar data**, which is
well-powered (100,001 H1 bars), and deliberately not of performance, which on the
available replay window would rest on **4 completed trades** and is not a sample.

## 7. Consequence for the migration

1. **Migrate together.** Confirmed necessary: U8 governs L5, which gates L6–L8,
   so correcting it alone changes the population every later threshold sees.
2. **Scale-invariance, not division.** The defect is absoluteness. `core/units.py`
   already provides `AtrMultiple` and `Percentage` for expressing this, and
   `Pips`/`PriceDistance` for the ones that genuinely are distances.
3. **Name the new binding parameters.** Where a scale-invariant form shifts the
   binding constraint onto a previously-dead coefficient (U8's `0.12`), that
   coefficient becomes an unvalidated parameter and must be recorded as one.
4. **Measure the funnel, not the P&L.** 15,735 decisions through eight layers is
   enough to see where the pipeline blocks and how a fix redistributes that.
   4 trades is not enough to say anything about whether it made money, and no
   such claim will be made.
