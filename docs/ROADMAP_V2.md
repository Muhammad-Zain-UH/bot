# ROADMAP V2 — from "no edge yet" to a validated gold system

Plan of record from 2026-10-06. Claude Code reads this before every task.
Owner decisions are in §2. Prompts that execute this plan are in
`docs/PROMPTS_V2.md`.

No plan can promise profit. This one is built so that a real edge, if gold
has one we can reach, gets found on enough data, and so that a dead idea dies
in days instead of weeks.

---

## 1. Review of the repository (branch `phase-0-1-foundations`, HEAD `f0f4477`)

### 1.1 What is genuinely strong — keep all of it

- **Research discipline.** Pre-registration committed before scripts, causal
  feature/label split with truncation checks (`research/panel_features.py`),
  non-overlapping inference, estimator-disagreement checks, a mechanical
  FINAL_OOS lock (`research/dataset_access.py`, `OOSLockedError`). This is
  better than most professional research setups. It is why the null results
  can be trusted.
- **Safety and execution core.** `core/` (units, sizing, risk_limits, safety,
  types with `PendingOrderIntent` invariants), `execution/` (paper broker,
  intrabar policy, fills, trade identity), `LIVE_TRADING_ENABLED` hard-coded
  `False` in `core/safety.py`. Reuse this for the new system.
- **Honest negatives.** H01–H06, the original-continuation audit and the
  production-path audit are real knowledge, not wasted work.

### 1.2 What went wrong — five problems, in order of cost

**P1. Effort kept going into a strategy the research had already ruled out.**
`research/PRODUCTION_PATH_AUDIT_REPORT.md`: 0 of 21 layer hypotheses survive;
L6 POI "is a restatement, not a layer" (poi_score = 68.0 on 89.44% of
decisions); structure "confirmation" cannot disagree with the bias (0 of 60,638
decisions). `research/ORIGINAL_CONTINUATION_AUDIT_REPORT.md`: displacement and
structure layers *subtract* from bias alone. Yet the newest commits
(baselines 009–014, U1–U12 unit migration, ATR unification, the 20-item
`docs/PHASE_8_RESEARCH_LEDGER.md`) are still repairing that pipeline. Its replay
produces 4–6 trades in 16 weeks, so no repair can ever be evaluated on outcome.
**Decision D1 below: freeze it.**

**P2. The cost gate measured the wrong thing and killed intraday research.**
`research/BENCHMARK_REPORT.md` caps every strategy at 52 round turns a year
because "504 round turns would cost 192.7% of the buy-and-hold CAGR". That
compares spread drag with *buy-and-hold's* return, which silently assumes a
trade earns a share of gold's drift. A trade-based strategy pays its cost per
trade and earns its own expectancy per trade: if the gross edge per trade is
larger than the cost per trade, trade count does not matter. The report itself
notes hour-of-day effects have "roughly 3× statistical headroom" — and then
rejected them without ever measuring their size. **Intraday time-structure in
gold has never actually been tested in this repo.**

**P3. The data limit is the broker's, not the market's.** Every power failure
in `research/VIABILITY_REPORT.md` traces to the broker's ~100,000-bar cap per
timeframe (`research/BAR_HISTORY_PROBE.md`: M15 only 4.25 years, zero
bear-market years; M1 0.29 years). Dukascopy publishes free XAUUSD **M1 bid and
ask from 2003-05-05** — 23 years of intraday history, including 2008, the
2013–15 bear market, 2018 and 2022, *with real historical spreads*. That
single change makes the intraday questions testable.

**P4. Wrong benchmark for half the strategy forms.** "Beat buy-and-hold Sharpe
and drawdown in both arms" is the right test for a long-or-flat exposure
overlay (H05, H06). It is the wrong test for a long/short or intraday strategy,
whose natural benchmark is cash plus a drift-neutral control. Also missing:
**overnight financing (swap)**, which every CFD position held past 17:00 New
York pays, and which can dominate slow strategies at a retail broker.

**P5. Process overhead.** Hypothesis specs and reports run 21–31 KB each;
corrections are layered as retraction archaeology; decisions become documents.
That slows learning without adding rigour. The rigour lives in the code checks
and the pre-registration commit order, not in report length. **CLAUDE.md now
caps reports at one page.**

### 1.3 What the evidence actually says so far

| Finding | Source | Meaning |
|---|---|---|
| SMC/ICT layers add no information | production-path + continuation audits | Do not rebuild it in another form |
| Pattern hypotheses H01–H04 mostly measured drift | H01–H04 reports | Bull-market sample; patterns not shown |
| Slow trend filter, long/flat, loses to hold | H05 | Gold's drift is expensive to sit out |
| Real-yield link is real (monthly corr −0.54 / −0.43) but a 0/1 rule fails | H06 | Mechanism exists; this functional form does not trade |
| Cost per trade fell ~4× relative to volatility | `DATASET_ACCEPTANCE.md`: $0.33 cost vs median M15 ATR $2.085 (2022–24) → $8.932 (2025–26) | Intraday economics today are far better than in the sample the earlier research used |

---

## 2. Owner decisions (approve once; Claude Code treats them as settled)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Freeze the legacy SMC/ICT pipeline and close the Phase 8 ledger as "not pursued". No more fixes, baselines or ledger entries for it. | **Approve** |
| D2 | Primary research data becomes Dukascopy XAUUSD M1 bid+ask 2003-05-05 → 2026-10-01. Broker data is used for reconciliation, cost calibration and execution realism. | **Approve** |
| D3 | Gate amendments in §5 (per-trade economics, benchmark by form, financing, historical costs). The 52-round-turn gate no longer applies to trade-based forms. | **Approve** |
| D4 | Multiple testing: V2 counts its own tests from zero with Bonferroni over the V2 cumulative count, **plus** mandatory replication in an untouched 8.7-year DEV arm. | **Approve** |
| D5 | Slow, externally-established effects (H10, H11) use the "external-prior confirmation" standard in §5, because one instrument can never give statistical significance for a Sharpe around 0.4. | **Approve** |
| D6 | First live risk budget: 0.25% equity per trade, 1% daily loss stop, 6% drawdown halt, for the first 3 months. | **Approve** |

---

## 3. Target architecture — small, separate, testable

```
          Dukascopy M1 bid/ask 2003→   Broker MT5 (live + recent)   FRED (rates)
                      │                          │                      │
                      ▼                          ▼                      ▼
   gold/data   build · validate · fingerprint · split · reconcile · OOS lock
                      │
                      ▼
   gold/hyp    one module per hypothesis: frozen constants → event/return table
                      │                      (pure functions, no I/O)
                      ▼
   gold/stats  thin wrappers over research/phase1_statistical_controls.py
   gold/econ   costs from bid/ask, broker calibration, financing
                      │
                      ▼  only survivors continue
   gold/sim    trade simulator: entry, stop, target, time exit, M1 resolution
                      │
                      ▼
   gold/sleeves  one class per validated edge, ≤3 parameters each
   gold/portfolio  equal-risk sleeves, vol scaling, account limits (core/risk_limits)
                      │
                      ▼
   gold/live   scheduler (zoneinfo sessions) → execution.broker.Broker
               PaperBroker for shadow, new MT5Broker for live (demo first)
```

Rules: a sleeve is a validated edge with its own frozen parameters. No layer
stacking — a filter is only added if it is itself a pre-registered, validated
hypothesis. Reuse `core/` and `execution/`; the legacy top-level `*.py` files
are not imported by anything in `gold/`.

---

## 4. Data plan (V2 dataset)

**Source.** Dukascopy XAUUSD M1 candles, BID and ASK series separately,
2003-05-05 → 2026-10-01 UTC, via the `dukascopy-node` CLI. Flat zero-volume
candles (closed market) are excluded. Raw yearly files are immutable.

**Built frames** (`data/dukascopy_v1/`, gitignored, fingerprinted):
M1 with `bid_o,h,l,c`, `ask_o,h,l,c`, `mid_o,h,l,c`, `spread_c`, `volume`;
resampled M15, H1, H4, D1 from M1. D1 day boundary = 17:00 America/New_York.

**Validation.** Monotonic UTC index, no duplicates, OHLC consistency,
`ask ≥ bid` everywhere, gap report per year, spread median/p95 per year and per
NY hour. Price sanity: the 2011-09 high ≈ $1,920 and the 2020-08 high ≈ $2,075.

**Reconciliation with the broker** on the overlap (from 2022-06-30 on M15/H1,
using the UTC-normalised `data/research_v1/` files): H1 log-return correlation,
median absolute close difference, timestamp alignment check.

**Broker cost calibration:**
`k_cost = max(1, broker_median_spread / dukascopy_median_spread)`, measured over
the same week of ticks, 2026-10-05 → 2026-10-09, which is **after 2026-10-01**.
That window lies outside every arm, so calibrating never touches FINAL_OOS. The existing $0.33
figure came from a 2026-09-24 tick sample, which is inside FINAL_OOS. Every
cost in V2 is Dukascopy spread × `k_cost`.

**Split (manifest `research/research_split_manifest_v2.json`).**

| Arm | Range | Content |
|---|---|---|
| TRAIN | 2003-05-05 → 2016-12-30 | 2008 crash, 2011 peak, 2013–15 bear |
| DEV | 2017-01-02 → 2025-09-01 | 2018 dip, 2020, 2022 bear, 2024–25 bull |
| FINAL_OOS | 2025-09-02 → 2026-10-01 | **unchanged, still locked** |

Purge: one full trading day after each boundary. The loader refuses FINAL_OOS
exactly like `research/dataset_access.py`.

**Rates.** Add `DFF` (effective fed funds, daily) to the existing FRED
acquisition (`research/acquire_cross_asset.py`) for the financing model.

---

## 5. Gate amendments V2 (added to `research/RESEARCH_TO_STRATEGY_GATE.md`)

Everything in the existing gate stays (pre-registration order, causal checks,
non-overlap inference, power pre-check, temporal replication, FINAL_OOS
rules) except:

1. **Economics per trade.** For trade-based forms the economic test is: mean
   net result per trade > 0, where net = gross − round-turn cost at the actual
   time of entry and exit (`(spread_entry + spread_exit)/2 × k_cost`, plus
   financing if held past 17:00 NY). Evaluate at 1× and 2× cost. The
   52-round-turn cap applies only to exposure overlays.
2. **Benchmark by form.** Long/flat exposure overlays → buy-and-hold (existing
   rule). Long/short or intraday forms → cash, plus a drift control (both legs
   reported separately, and a drift-adjusted version must agree in sign).
3. **Cost era.** Statistics are computed on gross mid returns in TRAIN.
   Economics are judged in DEV at DEV-era costs, because that is the cost
   environment a live bot faces.
4. **Multiple testing (D4).** TRAIN significance threshold = Bonferroni over
   the V2 cumulative test count (two-sided, α = 0.05). DEV replication =
   one-sided p < 0.05 in the direction fixed by TRAIN, with no re-fitting.
5. **External-prior confirmation (D5)**, for H10 and H11 only: net Sharpe > 0
   (H10) or Sharpe and max drawdown better than hold (H11) in **both** TRAIN
   and DEV; no single era supplies more than 60% of cumulative net P&L; Sharpe
   standard error disclosed. Significance is not required and not claimed.
6. **Reports.** One page, template in `research/templates/`. Verdict first.

---

## 6. Hypothesis queue

Each hypothesis has a mechanism with outside evidence, a fixed construction,
and a small test count. All constructions are causal; anchors use the last M1
close at or before the anchor minute (within 5 minutes, else the day is
dropped). Time windows use `zoneinfo`, never fixed UTC offsets.

### Batch 1 — intraday time structure (TRAIN/DEV on Dukascopy M1, flat by 17:00 NY, so no financing)

**H07 — Session return structure.** Trading day = 18:00 → 17:00
America/New_York, split into six blocks in New York time:
B1 18–22, B2 22–02, B3 02–06 (London open), B4 06–10 (COMEX open, 08:30 US
data), B5 10–14 (London PM auction, COMEX settlement 13:30), B6 14–17.
Variable: mid log return of each block per day; a block is dropped if < 80% of
its minutes exist.
- Mechanism: price discovery and hedging flows are concentrated in specific
  sessions; an Asia-up / US-down asymmetry is widely reported for gold but has
  not been established out of sample.
- Tests (6): mean block return ≠ 0 in TRAIN. Direction `d_b` = sign of the
  TRAIN mean.
- Controls: drift-adjusted version `r_b − (h_b/H_day)·r_day` has the same sign
  with |t| ≥ 2; sign identical in all three TRAIN eras (2003–07, 2008–12,
  2013–16).
- DEV: one-sided test in direction `d_b`; net per trade > 0 at 1× DEV cost and
  ≥ 0 at 2×.

**H08 — Intraday momentum into COMEX settlement.** `r_early` = mid log return
18:00 (previous day) → 12:00 NY; `r_late` = 12:00 → 13:30 NY.
Trade variable `y = sign(r_early) × r_late`; days with `r_early = 0` are dropped.
- Mechanism: intraday momentum (Gao, Han, Li & Zhou, 2018, *Journal of
  Financial Economics*): late-session hedging and late-informed trading follow
  the day's earlier move. For gold the day's main liquidity event is the COMEX
  settlement at 13:30 ET.
- Test (1): mean(y) > 0 in TRAIN.
- Controls: both legs separately — mean(r_late | r_early > 0) > 0 and
  mean(r_late | r_early < 0) < 0; positive in all three TRAIN eras.
- DEV: one-sided; net > 0 at 1× cost, ≥ 0 at 2×.

**H09 — London PM auction reversal.** `r_pre` = 14:00 → 15:00
Europe/London, `r_post` = 15:00 → 16:00. `y = −sign(r_pre) × r_post`.
- Mechanism: hedging flows into the fix, then unwinding (Caminschi & Heaney,
  2014, *Journal of Futures Markets*, on the old London PM fixing).
- Test (1): TRAIN restricted to the old-fix era 2003-05-05 → 2015-03-19.
  DEV (2017–2025) is entirely the ICE auction era, which began 2015-03-20.
- Pre-declared expectation: weaker in DEV. Low prior; included because it is
  cheap and the regime break is known in advance.

Batch 1 total: 8 tests.

### Batch 2 — slow, externally established effects (D1, financing included)

**H10 — Time-series momentum, long/short, volatility-targeted.**
Weekly at the Friday 17:00 NY close: `s = mean(sign(R21), sign(R63), sign(R252))`
over trading-day returns; position = `s × min(2, 0.10 / σ63)` with σ63 the
annualised standard deviation of daily log returns. Executed at the first M1
bar ≥ 60 minutes after the Sunday open. The three lookbacks are blended, not
chosen.
- Mechanism: Moskowitz, Ooi & Pedersen (2012), *JFE*, 58 futures including
  gold; Hurst, Ooi & Pedersen (2017), a century of evidence.
- Benchmark: cash. Report correlation with buy-and-hold.
- Gate: external-prior confirmation (§5, rule 5).

**H11 — Volatility-managed long exposure.** Weekly exposure =
`min(1.5, σ* / σ21)`, where σ* is the median σ21 over TRAIN (frozen).
- Mechanism: Moreira & Muir (2017), *Journal of Finance*. Contrary
  out-of-sample evidence: Cederburg, O'Doherty, Wang & Yan (2020), *JFE*. Prior
  is low-to-moderate.
- Benchmark: buy-and-hold with the same financing.
- Gate: external-prior confirmation (§5, rule 5).

**Financing model (H10, H11).** Use the broker's current `swap_long` /
`swap_short` from MT5 `symbol_info` for the period it covers. For history, use
a conservative model: long pays DFF + 2.5% per year, short pays 2.5% per year,
both on notional.

### Parked — with the reason, so nobody re-opens them by accident

- **Macro-release drift (NFP, CPI, FOMC).** About 600 events in 23 years:
  underpowered at a cost-sized effect. The event calendar becomes a **risk
  filter** in every sleeve (no new entries ±30 minutes around these releases),
  not an alpha hypothesis.
- **Continuous real-yield exposure** (the H06 follow-up idea). TRAIN+DEV hold
  about 1.5 real-yield cycles; a functional form cannot be identified on that.
- **SMC/ICT patterns in any form.** Closed by the audits in §1.2.
- **Machine learning on OHLC features.** Only as a meta-filter on a sleeve
  that has already passed, never as the source of an edge.
- **Re-running H01–H04 on the longer data.** Their measured effects were 1/5 to
  1/3 of cost; more data would sharpen the estimate, not lift it above cost.

---

## 7. From survivors to a strategy

Only hypotheses that pass TRAIN **and** DEV continue.

1. **Sleeve per survivor.** The tested rule plus pre-declared risk
   mechanics, frozen before any DEV trade simulation:
   - catastrophe stop at 3 × ATR(14, M15) from entry (fixed, not tuned);
   - event filter (§6, Parked);
   - no position through 17:00 NY rollover for intraday sleeves;
   - Friday flat for intraday sleeves.
2. **Trade simulation** with `gold/sim` on M1: entry and exit at real bid/ask ×
   `k_cost`, stop checked on M1, stop-first if stop and exit share a bar,
   R-multiples recorded. Agreement with `execution/intrabar.resolve_intrabar`
   is tested on shared fixtures.
3. **Robustness.** Window boundaries ±30 minutes and the stop ±25%: net result
   must stay > 0 in DEV in at least 80% of neighbours. This is a check, not a
   selection; the frozen values are kept.
4. **Portfolio.** Equal risk per sleeve, sized with `core/sizing.lots_for_risk`,
   account limits with `core/risk_limits`, daily risk cap. Report sleeve
   correlations.
5. **FINAL_OOS, one look,** at the frozen portfolio after written owner
   authorisation. Failure ends that portfolio version.
6. **Shadow trading** 8–12 weeks on an MT5 demo account through the new
   `MT5Broker` (implements `execution.broker.Broker`). Compare fills with the
   simulator and live R-multiples with the DEV distribution. Auto-pause if the
   rolling 40-trade mean R falls below the DEV 5th percentile.
7. **Live readiness review (G12).** Only then can `LIVE_TRADING_ENABLED` be
   reconsidered, starting with the D6 risk budget.

## 8. Stop rule — what happens if nothing survives

If batch 1 and batch 2 produce no survivor, the honest conclusion is: no
single-instrument gold edge was found at the resolution available. Then
choose one of these, and do not build a trading bot on unvalidated rules:
- **(a) Breadth.** Time-series momentum across many instruments, where the
  evidence is strongest. This is the direction H06's report itself points to.
- **(b) Alerts only.** Use the system for discretionary decision support,
  without automated execution.
- **(c) Stop.**

## 9. Expected timeline

| Step | Prompt | Effort |
|---|---|---|
| Freeze + skeleton | P0 | ½ day |
| Dukascopy dataset | P1 | 1–2 days (download time dominates) |
| Economics + power pre-check | P2 | ½ day |
| Batch 1 pre-registration + run | P3–P4 | 1 day |
| Batch 2 | P5 | 1 day |
| Sleeves, portfolio (only with survivors) | P6 | 2–3 days |
| FINAL_OOS | P7 | ½ day |
| Live engine + shadow | P8 | 2 days + 8–12 weeks |
