# Hypothesis 05 — SLOW TREND-CONDITIONAL EXPOSURE

**Committed BEFORE any result is computed.** This commit contains the
specification and nothing else.

Governing standards, both binding: `research/RESEARCH_TO_STRATEGY_GATE.md` and
`research/STATISTICAL_RESEARCH_CONTROLS.md`.

| Prior | Status |
|---|---|
| H01 compression → breakout | **NOT SUPPORTED** (`45223cd`) |
| H02 failed breakout → reversal | **INCONCLUSIVE / UNDERPOWERED** (`5230336`) |
| H03 volatility-state transition | **NOT SUPPORTED** (`7b59b95`) |
| H04 liquidity displacement → acceptance | **NOT SUPPORTED** (`52b44d3`) |
| Viability study | 4 of 11 combinations testable (`40528a4`) |
| Benchmark + cost gate | hold Sharpe 0.387, maxDD −45.25%, gate 52 round turns/yr (`28e1807`) |

---

## 1. What is being claimed, and what is not

**Claim:** reducing exposure to gold when it is below a slow trend filter
improves *risk-adjusted* outcomes versus holding it continuously — primarily by
avoiding sustained declines.

**This is not an alpha claim.** It does not assert a predictive edge on returns.
It asserts that a known risk-management effect survives this instrument's costs.
Time-series momentum is among the most replicated results in asset pricing
(Moskowitz-Ooi-Pedersen across 58 instruments; Hurst-Ooi-Pedersen back to 1880),
so the mechanism is not novel — the open question is whether it pays for itself
here, at this spread, on this history.

**Why this form and not another.** H01–H04 tested price-pattern alpha and found
none across 126 pre-registered tests. Intraday timing is separately ruled out on
economics: ~504 round turns/year costs **192.7%** of the benchmark's entire return
(`BENCHMARK_REPORT.md` §3). The only admissible form left is transition-slow
exposure modulation, which is what this tests.

**Direction of expected effect, signed in advance:** lower maximum drawdown and
no degradation in Sharpe. **Not** higher CAGR — a trend filter is expected to
*give up* return in exchange for avoided drawdown, and §6 requires that give-up
to be stated rather than hidden.

---

## 2. Data

Via `research/dataset_access.py` with `manifest=H1_SPLIT_MANIFEST`
(`research/research_split_manifest_h1.json`):

| Arm | Window | H1 bars | years |
|---|---|---|---|
| **TRAIN** | 2009-08-31 → 2020-12-31 | 66,147 | 11.33 |
| **DEV** | 2021-01-04 → 2025-09-02 | 27,589 | 4.66 |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | **LOCKED** | — |

Both arms contain bear markets — TRAIN 2013/14/15/18 (**35.47%** of bars in down
years), DEV 2021/22. This is the first hypothesis in this programme that can be
tested outside a bull run.

**FINAL_OOS is not read**, as data or as context. No M5, M1 or tick data is used.
**No tuning occurs on DEV**: nothing is refit there.

---

## 3. The rule, frozen

```
# D1 is absent from the dataset, so the daily series is built from H1.
daily_close[d] := the close of the LAST H1 bar whose timestamp falls in UTC day d

sma[d]     := mean( daily_close[d-99 .. d] )          # 100 daily closes, inclusive
signal[d]  := daily_close[d] > sma[d]
target[d]  := 1.0 if signal[d] else 0.0

execution  := the exposure change is applied at the OPEN of the first H1 bar
              strictly after the H1 bar that produced daily_close[d]
```

`sma[d]` includes `daily_close[d]`, which is legitimate because the signal is
known at that daily close and execution happens strictly afterwards. The
causality boundary is the execution bar, not the signal bar, and §8 verifies it.

**Exposure is long or flat only, `{0.0, 1.0}`, and never exceeds 1.0.** No
shorting. No leverage. Leverage is a scaling decision applied after an edge is
demonstrated, not part of demonstrating one.

### Why SMA100 — selected performance-blind

Chosen on two pre-stated criteria computed **without reference to any return,
Sharpe or drawdown figure** (counts only):

| rule | exposure changes/yr | round turns/yr | % of TRAIN CAGR | **episodes** |
|---|---|---|---|---|
| SMA50 | 22.1 | 11.1 | 4.2% | **126** |
| **SMA100** | **15.4** | **7.7** | **2.9%** | **88** |
| SMA200 | 7.3 | 3.7 | 1.4% | 42 |
| SMA200 ± 2% hysteresis | 2.0 | 1.0 | 0.4% | **12 — worthless** |

Cost is **not** the binding constraint for any of these; **evidence is**. The
cheapest rules are nearly free and have almost no episodes to validate on.
SMA100 is the midpoint of the usable zone on both axes: adequate episodes (88)
and negligible cost (2.9% of CAGR, against a 20% gate).

**SMA50 and SMA200 are declared NOW as sensitivity reports, not as alternatives
to select from after seeing results.** The primary is SMA100 and does not change.

### Cost model, and a correction to figures quoted earlier

```
one round turn      = 1 x spread = $0.33   (ask = mid + S/2, bid = mid - S/2)
one exposure change = |delta exposure| x S/2 = $0.165 per unit
```

A full 0→1→0 cycle is two changes and therefore exactly one round turn. **Cost is
charged at the price prevailing at each transition**, not at an era-average,
because the spread is a fixed dollar amount while the price level moved ~4×
across the record.

> **Correction.** Figures I quoted earlier in this session treated each exposure
> *change* as a full round turn, which double-counts. SMA100's true cost is **7.7
> round turns/year (2.9% of CAGR)**, not 15.4/year and 5.9%. The earlier figures
> were conservative, so no conclusion rests on the error, but the table above is
> the correct one.

> **A convention conflict in the repository, resolved explicitly.**
> `execution/fills.py` `FillModel` applies the full spread on both entry and exit
> — **2× spread per round turn, in pips**. The research layer and
> `research/benchmark.py` use **1× spread, in USD**. This hypothesis uses the
> research convention (1×), consistently with the benchmark it is measured
> against. The discrepancy is recorded, not repaired.

---

## 4. The benchmark

Buy-and-hold, from `research/benchmark.py`, which is **reused, not reimplemented**:

| | TRAIN | DEV |
|---|---|---|
| CAGR | +6.266% | +13.787% |
| **max drawdown** | **−45.25%** | **−21.87%** |
| longest underwater | 8.93 yr | 1.15 yr |
| Sharpe (rf=0) | 0.387 | 0.880 |

Equity is marked to market on **every H1 bar**:

```
equity[t+1] = equity[t] * (1 + exposure[t] * (close[t+1]/close[t] - 1))
            - transition cost at t+1 if exposure changes there
```

Sharpe annualises on **measured bars per year per arm** (5,837 TRAIN, 5,921 DEV),
not an assumed 24×365 — gold trades ~120 hours a week and the calendar basis
overstates volatility by 1.23×.

---

## 5. Primary criterion — and why it is not a significance test

**PRIMARY: maximum drawdown materially below the benchmark in BOTH arms**, net of
transition costs. "Materially" is declared as **at least 5 percentage points**
better in each arm: ≤ −40.25% in TRAIN and ≤ −16.87% in DEV.

This is a direct comparison of two numbers, **not a null-hypothesis test**, so
Bonferroni and Benjamini–Hochberg do not apply to it and will not be invoked.
The protection against a false discovery is structural, and is the whole reason
this file exists before the results:

1. the rule is **pre-registered** and its parameter chosen performance-blind;
2. **both arms** must pass, and they have deliberately different character
   (Sharpe 0.387 vs 0.880, drawdown −45.25% vs −21.87%);
3. **no parameter search** — SMA50/200 are disclosure, not candidates;
4. the Sharpe comparison **is** a statistical test and is reported with its
   honest power limitation (§6).

## 6. Supporting measures — all required, none sufficient

**Sharpe must not degrade** in either arm. A *statistically significant* Sharpe
improvement will **not** be claimed, because it cannot be established here:

- the benchmark's own Sharpe is **0.387 ± 0.60** on TRAIN and **0.880 ± 1.07** on
  DEV — neither is distinguishable from zero;
- a paired Jobson-Korkie / Memmel test at ρ≈0.90 needs **ΔSharpe ≥ 0.32**
  (0.387 → 0.71) for 2-SE significance on TRAIN.

The paired test is reported with its SE and the realised correlation, and the
report must state that the result is underpowered rather than imply otherwise.

**CAGR give-up must be stated explicitly.** A drawdown cut that surrenders most
of the return is not an improvement. Reported: CAGR, total return, time in
market, number of transitions, realised cost in both dollars and % of capital.

**Slippage grid:** 0 / 0.25 / 0.50 / 1.00 × spread, reported as a grid, never
optimised.

**Per-episode ledger, mandatory.** TRAIN's drawdown outcome will lean heavily on
whether one rule caught one event (the 2013–2015 decline, −45.2%). Every episode
— entry date, exit date, duration, return, contribution to drawdown avoided —
must be listed, so a result driven by a single episode is visible rather than
hidden inside an aggregate.

**Per-era breakdown:** 2009-12, 2013-16, 2017-20, 2021-24, declared now.

---

## 7. What would constitute evidence AGAINST

- max drawdown not at least 5 points better in **either** arm;
- Sharpe degrading in either arm;
- the drawdown improvement attributable to **one** episode, with the rest neutral
  or harmful (the per-episode ledger decides this);
- CAGR give-up so large that total return is below the benchmark's by more than
  the drawdown improvement justifies — reported as a risk/return pair, not a
  single score;
- sign disagreement between arms on any supporting measure;
- the result reversing under the SMA50/SMA200 sensitivity reports, which would
  indicate SMA100 sits on a knife edge rather than a plateau.

**INCONCLUSIVE** if the drawdown improvement is positive but under 5 points, or
if it is confined to one arm.

---

## 8. Causal reconstruction — tolerances frozen BEFORE results

| Quantity | Frozen tolerance | Justification |
|---|---|---|
| `daily_close` | **exactly 0.0** | a selection of an existing float64, no arithmetic |
| `sma[d]` | **relative 1e-13** | mean of 100 float64 terms; bound ≈ 100·eps ≈ 2.2e-14 |
| `signal[d]` | **0 disagreements** | boolean |
| exposure series | **0 disagreements** | boolean |
| execution bar index | **0 disagreements** | integer |

**Method:** for a frozen sample of **60** transition dates (seed **20261007**),
every quantity is rebuilt from the H1 series truncated at the signal bar and
compared with the panel value.

**Lookahead audit, exhaustive:** for every H1 bar, assert that the exposure
applied at that bar derives from a daily close whose H1 bar index is **strictly
less** than the bar's own index. Checked on all bars, not sampled.

---

## 9. No feature mining — binding

**One** signal definition, **one** window (100), **one** cadence (daily),
**one** exposure ladder ({0,1}), **one** execution rule. Not searched: alternative
moving-average types, alternative windows beyond the two declared sensitivity
reports, hysteresis bands, volatility overlays, dual-window crossovers,
breakout filters, any H01–H04 construct, or any non-price data.

A volatility overlay is a **separate hypothesis (H06)** requiring its own
pre-registration. It is not added here, so that this test measures one mechanism.

**If H05 fails, the failure is recorded** and no strategy is built. The rule is
not mutated until it passes.

---

## 10. Classification

| Outcome | Classification |
|---|---|
| drawdown ≥5 points better in both arms, Sharpe not degraded, give-up stated and acceptable, not single-episode | **H05 — SUPPORTED** |
| drawdown improvement positive but <5 points, or only one arm | **H05 — INCONCLUSIVE** |
| any §7 criterion met | **H05 — NOT SUPPORTED** |

**SUPPORTED does not authorise live trading.** It authorises Phase 2 (build the
system), which is followed by validation, FINAL_OOS under separate written
authorisation, paper trading, and the G12 live-readiness review.

## 11. Outputs

`research/hypothesis_05_trend_exposure.py` · `research/HYPOTHESIS_05_REPORT.md` ·
`research/hypothesis_05_results.json` · `research/hypothesis_05_controls.json`

## 12. Verification before the results commit

1. this specification committed **before** results, specification only;
2. FINAL_OOS token unchanged; 3. FINAL_OOS inaccessible and not loaded;
4. dataset fingerprints unchanged; 5. both split manifests unchanged;
6. `baseline_008` unchanged; 7. production unchanged;
8. `LIVE_TRADING_ENABLED is False`; 9. causal tolerances frozen before results;
10. no DEV tuning; 11. exactly one rule tested; 12. working tree contains only
intended research changes.
