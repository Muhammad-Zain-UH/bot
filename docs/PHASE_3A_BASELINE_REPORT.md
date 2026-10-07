# Phase 3A — Real XAUUSD Historical Baseline

**Status:** complete. **Commits:** `58128ff`, `a8b8092`. **Canonical baseline:** `baselines/baseline_004/`.

> **CORRECTION — 2026-09-17, after Phase 4A pre-analysis.** This report
> originally attributed 994 of the 1,265 L8 blocks causally to the RR
> tautology. That attribution is **withdrawn**: measurement shows the allowed
> entry candidate had `raw_triggered = False` at **all 1,265**, so the RR gate
> was never the binding term. The tautology is real but **latent**. The
> measurements themselves are unchanged and the baseline artifacts are
> untouched — only the causal claim is corrected. Affected passages are marked
> below and the full correction is in the **Addendum**.

Measurement phase. No strategy logic was changed, no threshold was tuned, and no
performance claim is made. The strategy produced **zero trades**, so most of the
statistics this report is required to carry are empty — and where they are empty,
that is stated rather than filled with zeros.

---

## 1. Dataset

| Property | Value |
|---|---|
| Source | MetaTrader 5, read-only `copy_rates_range` via `tools/export_mt5_history.py` |
| Broker / server | MetaQuotes Ltd. / MetaQuotes-Demo |
| Account | `5056046608`, USD, `trade_allowed = False` |
| Symbol | XAUUSD ("Gold vs US Dollar"), digits 2, point 0.01 |
| Exported | 2026-09-16T12:32:25Z |
| Server timezone | **UTC+3** (measured from a live tick, not assumed) |
| Immutable dataset hash | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` |

### Timeframes — all broker-native, nothing resampled

| TF | Bars | First (UTC) | Last (UTC) | SHA-256 (first 16) |
|---|---|---|---|---|
| M1 | 100,002 | 2026-06-02 10:20 | 2026-09-16 12:32 | `a2870881e9a34b74` |
| M5 | 20,127 | 2026-06-02 00:00 | 2026-09-16 12:30 | `a0cdd0f9b68c3f3e` |
| M15 | 6,711 | 2026-06-02 00:00 | 2026-09-16 12:30 | `f28c479a678592b1` |
| H1 | 1,680 | 2026-06-02 00:00 | 2026-09-16 12:00 | `e2c504b977facffb` |
| H4 | 459 | 2026-06-02 01:00 | 2026-09-16 09:00 | `d938f128a9639034` |
| D1 | 76 | 2026-06-02 21:00 | 2026-09-15 21:00 | `b4473abfa4144031` |

`derived` is empty — `all_native: true`. H4 opens at 01:00/05:00/09:00 UTC and D1
at 21:00 UTC because the server runs UTC+3. These are **preserved, not re-cut**:
re-cutting to UTC midnight would replace real broker candles with synthetic ones.

**M1 is the binding constraint.** The replay drives on M5 and requires M1, so the
usable window is about 3.5 months regardless of what D1 reaches back to. No
multi-year claim is supportable from this export.

### Data quality

Zero validation issues, zero duplicate timestamps, monotonic timestamps on all
six timeframes. 78 M1 gaps longer than one minute:

| Kind | Count | Shape |
|---|---|---|
| Weekend closure | 15 | All start Friday; 13 at 19:xx UTC, 2 at 17:xx (holiday weekends 2026-06-19, 2026-07-03) |
| Daily broker break | 61 | 60 of exactly 2h01m starting 19:59 UTC; 1 of 3h31m |
| Short interruption | 2 | 3 minutes each, 2026-06-04 08:31 and 2026-07-24 12:59 |

The daily break at 20:00–22:00 UTC is 23:00–01:00 server time — a normal
maintenance window. Nothing was repaired or back-filled.

---

## 2. Replay configuration

| Setting | Value | Note |
|---|---|---|
| Spread | **2.0 pips — ASSUMED** | Broker serves OHLC only, no bid/ask history. Recorded as `spread_source: ASSUMED`. Live spread at export was 39 points = **3.9 pips**, so the assumption is *not* conservative. |
| Slippage | 0.0 pips | Held at zero so its effect stays attributable later |
| Commission | 0.0 per lot | Same reason |
| Latency | Not modelled | No latency model exists; execution is bar-driven |
| Lot size | Fixed 0.01 | `risk_manager` deliberately not used — its ~10× contract-size defect (R1) would contaminate every currency figure |
| Fill timing | Next bar open | Enforced: `SimulatedFill` raises if entry bar ≤ decision bar |
| Intrabar | CONSERVATIVE | When a bar touches both stop and target, the stop is taken |
| Spread on exit | Applied | |
| Max open positions | 3 | |
| Driving timeframe | M5 | |

Symbol specification came from the broker's own metadata, not from constants:
`tick_size 0.01`, `tick_value 0.1`, `contract_size 100.0`, `pip_size 0.10`,
volume min/max/step `0.01 / 100.0 / 0.01`.

---

## 3. Decision funnel

15,735 decisions, 2026-06-24 17:00 → 2026-09-16 12:35 UTC (83d 20h). The first
4,392 M5 bars (22d 17h) were consumed by warm-up — H4 alone needs 100 bars.

| Layer | Reached | % | Blocked here | % |
|---|---|---|---|---|
| L1 BIAS | 15,735 | 100.00 | 2,392 | 15.20 |
| L2 STRUCTURE | 13,343 | 84.80 | 7 | 0.04 |
| L3 PULLBACK | 13,336 | 84.75 | 5,868 | 37.29 |
| L4 LIQUIDITY | 7,468 | 47.46 | 629 | 4.00 |
| L5 SWEEP | 6,839 | 43.46 | 4,075 | 25.90 |
| L6 POI | 2,764 | 17.57 | 1 | 0.01 |
| L7 CONFIDENCE | 2,763 | 17.56 | 1,498 | 9.52 |
| L8 ENTRY | 1,265 | 8.04 | 1,265 | 8.04 |

Monotonic, and blocked counts sum to exactly 15,735. "Reached" folds variant
labels (`L6_POI_BYPASSED`, `L3_PULLBACK_MOMENTUM`, `L5_SWEEP_WAIT`) into the
parent layer; matching bare names instead makes the funnel non-monotonic, which
is now guarded by `tests/backtest/test_baseline_funnel.py`.

### Dominant block reasons

- **L1 (2,392)** — H4 bias NEUTRAL 1,679; H1 fast bias NEUTRAL 713.
- **L2 (7)** — all "H1 structure is broken". The `h1_atr < 8.0` sub-gate fired **zero** times.
- **L3 (5,868)** — "No confirmed pullback detected" 1,731; "Swing too recent … momentum fallback failed" 608; remainder itemised retracement failures.
- **L5 (4,075)** — M15 CHoCH not confirmed: 1,329 SELL / 1,112 BUY; "zone near liquidity, waiting for confirmation" 892 SELL / 742 BUY.
- **L7 (1,498)** — "Confidence score too low".
- **L8 (1,265)** — "Entry triggers not all confirmed" (see §10).

---

## 4. Regime and session distribution

| Regime | `tp_ratio` | Decisions | % | Reached L8 | Entry reachable? |
|---|---|---|---|---|---|
| REGIME_SCALP | 2.0 | 6,492 | 41.26 | 217 | Yes |
| MICRO_SCALP | 1.5 | 5,121 | 32.55 | 972 | **No** |
| DEAD_CALM | 1.5 | 2,312 | 14.69 | 22 | **No** |
| INTRADAY_SWING | 3.0 | 1,810 | 11.50 | 54 | Yes |

`signals_by_regime` is empty — no regime produced a signal.

Sessions are derived post-hoc from the immutable decision stream using the
strategy's own `get_current_session` under a frozen clock, because with zero
trades `exit_statistics.by_outcome_and_session` is empty.

| Session (UTC) | Decisions | % | Reached L8 | Dominant regimes |
|---|---|---|---|---|
| Asian 00–07 | 5,040 | 32.03 | 430 | REGIME_SCALP 2,382 / MICRO_SCALP 2,313 |
| NewYork 13–21 | 4,999 | 31.77 | 228 | REGIME_SCALP 2,191 / DEAD_CALM 1,459 |
| London 07–13 | 4,316 | 27.43 | 607 | **MICRO_SCALP 2,736** |
| Dead 21–24 | 1,380 | 8.77 | 0 | DEAD_CALM 820 |

The session that penetrates deepest is London, and London is dominated by the one
regime where an entry is structurally impossible.

---

## 5. Signal statistics

| Metric | Value |
|---|---|
| Total signals | **0** |
| BUY / SELL | 0 / 0 |
| Signal types | `PRE_ENTRY` 15,735; `ENTRY_SIGNAL` 0; `NO_SIGNAL` 0; `ERROR` 0 |
| Signal timestamps | None exist |
| Strategy errors | 0 |

Direction was still evaluated on blocked decisions: of the 1,265 that reached L8,
708 were BUY and 557 SELL.

**Signal fingerprint** (SHA-256 over `decision_statistics.json`):
`2391aba00b46c8bd2e1dcf0cc5f82153b1507b63870de11916858239823d2900` — identical
across all three runs.

---

## 6. Trade statistics

**Zero trades.** Every field below is undefined, not zero. `metrics.json` records
`null` for each ratio deliberately: a win rate over no trades is not 0%.

| Metric | Value |
|---|---|
| Total trades / filled / rejected | 0 / 0 / 0 |
| Wins / losses / breakeven | 0 / 0 / 0 |
| Win rate, profit factor, expectancy | `null` |
| Realised R — average / median / max / min | `null` |
| Realised P&L gross / net / commission | 0.0 / 0.0 / 0.0 |
| Max drawdown ($ and R) | 0.0 / 0.0 |
| Holding time | `null` |
| Open at end | 0 |

`ledger_fingerprint = 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
— which is exactly `sha256("[]")`. It therefore carries **no information** about
this run, a fact that matters for §8.

---

## 7. Exit analysis

No positions were opened, so there is nothing to analyse: zero TP exits, zero SL
exits, zero ambiguous bars, no stop or target distances, no end-of-data closures.
`exit_statistics.json` is empty in every breakdown.

The conservative intrabar policy was therefore never exercised on real data. The
mechanism was exercised on the Phase 2A.1 fixture (BUY and SELL both filled at
next-bar open and resolved against SL and TP), but that is fixture evidence, not
evidence from this dataset.

**Suspicious execution behaviour: none observed** — and that finding is weak, because
with no fills there was almost nothing for the execution layer to do.

---

## 8. Determinism

Three independent runs. 002 ran on an earlier harness; 003 and 004 on the current one.

| Property | 002 | 003 | 004 | Match |
|---|---|---|---|---|
| `dataset_sha256` | `433b7e27…` | same | same | ✅ |
| `decisions_fingerprint` | n/a | `e9421f30…` | same | ✅ |
| `ledger_fingerprint` | `4f53cda1…` | same | same | ✅ |
| `run_fingerprint` | n/a | `1276a31f…` | same | ✅ |
| metrics fingerprint | `8d25ac5d…` | same | same | ✅ |
| signal fingerprint | `2391aba0…` | same | same | ✅ |
| funnel / regime / exit / side | — | — | — | ✅ all identical |
| **`decisions.jsonl` (bytes)** | `eba74c08…` | same | same | ✅ |

**The complete ordered decision stream is byte-identical across all three runs:**
15,735 lines each, 0 differing lines.

Two honest qualifications.

**`run_fingerprint` alone was not sufficient**, and an earlier determinism claim
in this phase partly rested on it. As originally written it hashed dataset +
ledger + metrics — and on a zero-trade run the ledger is `sha256("[]")` and every
metric is `null`, so two runs disagreeing on *every* decision would still have
matched. `decisions_fingerprint` was added over the ordered stream, and
`tests/backtest/test_baseline_fingerprint.py` mutates each covered field in turn
and requires the digest to move, including tests that field and record boundaries
cannot be smeared together.

**One artifact differs between 003 and 004**: `defect_observations.json`, by the
single additive key `"regimes_not_in_mirror": []`. I hardened that reporting
function between the two runs, and 004 picked it up. It is a harness change, not
non-determinism — every measured value and the full decision stream are identical,
and the added key is empty. 004 is canonical because its artifacts match the
committed code.

`baselines/baseline_001/` is retained but **superseded**: its `reached_layer`
counts are non-monotonic (L3 8,570, L6 1,024) because it predates the bypass-label
fix. Its `blocked_at` counts and decision totals agree exactly with the others —
only the derived funnel was wrong.

---

## 9. Leakage

| Test suite | Tests | Result |
|---|---|---|
| `tests/backtest/test_leakage.py` | 14 | PASS |
| `tests/integration/test_integration_leakage.py` | 23 | PASS |
| `tests/integration/test_real_data_baseline.py` | 6 | **PASS** |
| `tests/backtest/test_clock_patch.py` | 19 | PASS |
| `tests/backtest/test_determinism.py` | 9 | PASS |

**Real-data leakage result: PASS.** At six decision instants spread across the
dataset, every bar at or after the instant was shifted by +$500 and the decision
re-run. All six were byte-identical. The mutation is proved material (+$500 moves
price six hours later by more than $100), and the test now requires every sample
to be tested rather than accepting silent skips.

This test previously produced a **vacuous pass**, and the fix is worth recording.
`open(os.devnull, "w")` opens as cp1252 on Windows; the strategy prints
box-drawing characters; the resulting `UnicodeEncodeError` was swallowed by
`analyze_entry`'s blanket `except` and returned as `layer_failed == "ERROR"` on
*both* sides. The two runs then "agreed" — on an error. Fixed with
`encoding="utf-8"`, and an `ERROR` decision now raises rather than being compared.

No leakage failures.

---

## 10. Strategy defects observed — evidence only, nothing fixed

### D-series (new, from this baseline)

| ID | Defect | Occurrences | Evidence |
|---|---|---|---|
| **E9/E10/Q3** | `calculate_entry_levels` sets `take_profit = entry ± risk_distance × tp_ratio`, then tests `valid_rr = rr >= 2.0`. Those two lines make `rr` **identically equal** to `tp_ratio`, so the gate reads a config constant. Since `entry_triggered = raw_triggered and valid_rr`, no decision in a `tp_ratio < 2.0` regime can ever enter. **The defect is real but latent — see Addendum.** | 7,433 decisions in affected regimes. ~~994 of 1,265 L8 blocks (78.58%)~~ **WITHDRAWN** — that is the count of L8-reaching decisions *in* an unreachable regime, **not** the count the gate blocked. The gate blocked **0**. | `2026-06-24T17:00Z` onward. Proved directly against the production function for every regime and both sides in `test_baseline_defects.py`. |
| **D8** | `detect_regime` admits MICRO_SCALP on `session in {"Asian","London","LondonNewYork"}`, but `get_current_session` returns only Asian/London/NewYork/Dead/Closed. **`LondonNewYork` is unreachable.** Also in `config.py:125`, `main_production.py:442`. | Structural | New York shows 72 MICRO_SCALP decisions vs London's 2,736. Proved by enumerating every hour of a full week under a frozen clock. |
| **D1** | Broker `trade_contract_size = 100.0` but `trade_tick_value = 0.1` with `trade_tick_size = 0.01`, giving `money_per_price_unit(1 lot) = 10.0` — a **factor of 10** disagreement. The baseline uses the broker's tick value rather than substituting the contract size. | Every currency figure | `manifest.json` records both. |
| **D9** | The L2 `h1_atr < 8.0` gate fired **zero** times on real data; all 7 L2 blocks were "H1 structure is broken". The threshold is absolute USD — at gold near $3,900 it is ~0.2% of price. Not harmless, just not selective *at this price level*. | 0 of 15,735 | Same gate causes the two pre-existing test failures (D7) by firing at 0.0 when indicators are mocked. |
| **D5** | L3 (5,868) and L5 (4,075) dominate attrition far ahead of L8 (1,265). Removing the L8 tautology alone would not make the strategy trade at the rate the layer structure implies. | — | §3 funnel. |
| **D2** | M1 bounds coverage to ~3.5 months regardless of D1 reach. | — | §1. |
| **D3** | Server time is UTC+3, not UTC; handled at export. Native H4/D1 are not UTC-aligned and are preserved. | — | §1. |
| **D4** | Spread is ASSUMED at 2.0 pips; live was 3.9 pips. No spread-sensitive conclusion is supportable. | — | §2. |
| **D6** | `run_fingerprint` was insufficient to prove zero-trade determinism. | — | §8. Harness, not strategy. |
| **D7** | Two pre-existing test failures, reproduced at `04a341d` in a clean worktree. | 2 | §11. |
| **D10** | **The baseline wrote to the production log.** See below. | 8,860 lines | §11. Harness, not strategy. |

### Carried forward, unchanged

- **Q1/Q2 — realised R vs reported RR**: 0 occurrences this run (no trades). The plumbing is in place: `strategy_rr_ratio` is captured as a diagnostic and realised R is computed from the actual fill, never from the strategy's own number.
- **Q6 / U1 — the `buffer_pips = 3.0` stop buffer is subtracted from a price**, giving a **$3.00** buffer where 3 pips was meant. Not measurable from a zero-trade ledger; re-proved by direct call: `_select_stop_anchor("BUY", sweep_wick_low=2511.73) → 2508.73`.
- **G2 / U10 — regime bands are absolute USD** (2.5 / 4.5 / 7.0). Regime selection on this dataset is a function of gold's price level, not of relative volatility.

**Nothing above was fixed.** The only code changes are harness and test code.

---

## 11. Code and Git integrity

| | |
|---|---|
| Commits | `58128ff` (baseline infrastructure), `a8b8092` (production-log guard) |
| Baseline ran against | `04a341daa03de2e8f567b4d01f5c572f7084eb1e` |
| Branch | `phase-0-1-foundations` |
| Working tree | clean |

### Files changed, `04a341d → a8b8092`

```
backtest/baseline.py                          (new)
backtest/replay_engine.py                     (+7: three additive diagnostic keys)
tests/backtest/test_baseline_artifacts.py     (new)
tests/backtest/test_baseline_defects.py       (new)
tests/backtest/test_baseline_fingerprint.py   (new)
tests/backtest/test_baseline_funnel.py        (new)
tests/execution/test_import_arms_nothing.py   (new)
tests/integration/test_real_data_baseline.py  (new)
tests/integration/test_strategy_to_broker.py  (guard narrowed + 1 test)
tools/export_mt5_history.py                   (rewritten for real history)
```

**Strategy modules: untouched.** All 110 tracked `.py` files at `04a341d` were
hashed against the working tree with line endings normalised; only the three
non-strategy files above differ. (An earlier check that compared raw bytes was
wrong — `git show` emits LF against a CRLF working tree and falsely flagged 46
files.)

### Tests

| | Tests | Failures | Errors |
|---|---|---|---|
| Before Phase 3A additions | 546 | 2 | 0 |
| **Final** | **602** | **2** | **0** |

- **Pre-existing: 2.** `test_pullback_gate_requires_real_pullback_detection` and `test_micro_scalp_l7_confidence_uses_55_threshold`. Reproduced at `04a341d` in a clean worktree. Both patch `calculate_indicators` to `{}`, so L2's H1-ATR sub-gate reads `0.0 < 8.0` and blocks before the layer under test. **Left failing** — repairing them means editing assertions about strategy gate behaviour.
- **Phase-3 failures: 0.** One was introduced and resolved during the phase: `baseline.py` imports `risk_manager` for session labelling, tripping the Phase 2A.1 blanket ban. Rather than weaken the guard, it was narrowed to an enforced allowlist (`get_current_session` only) plus a new test forbidding any sizing symbol.
- **Newly introduced: 0.** +56 tests, 0 skips.

### No live execution path

- `core.safety.LIVE_TRADING_ENABLED` is `False` — a literal `Final[bool]`, no env read, no override.
- Two `mt5.order_send` call sites exist, both **pre-existing and unchanged**: `graceful_shutdown()` (`main_production.py:1240`) and `close_all_positions()` (`main.py:770`).
- Both are reachable only from `main()` or a signal handler, and the `signal.signal` registrations sit **inside `main()`** — which a replay never calls. There is no `atexit` hook. The only module-level calls on import are logging setup.
- `tests/execution/test_import_arms_nothing.py` now asserts this in a subprocess: importing `main_production` installs no signal handler and registers no project-owned exit hook.
- Nothing in `data/`, `execution/` or `backtest/` imports MetaTrader5 or references any order API.

### Production log integrity — a defect was found here

`main_production` builds its `logging.FileHandler` at module scope from
`TRADING_BOT_LOG_FILE`, defaulting to `trading_bot_production.log`. The baseline
runner redirected stdout but **not** logging, so baselines 001–004 appended
**8,860 lines** to the permanent record across 2026-09-15..17 — 8,799
`[L2_STRUCTURE]`, 31 `[L3_PULLBACK]`, 24 `[INIT]`, 4 `[BOT]`, 2 `[DECISION]`.

**No fabricated signal entered the record.** The run produced none, and the file's
`ENTRY SIGNAL GENERATED` count is still the same 4 July entries the Phase 1 audit
attributed to `tests/test_layer_gate_logic.py`. No signal CSV was written.

This is the Phase 0.4 failure mode recurring *outside* the test harness, which
`tests/__init__.py` cannot cover because a baseline is not a test run. Fixed in
commit `a8b8092`: `run_baseline` now calls `assert_logs_are_redirected()` and
refuses to start. Matching is by **resolved path**, not filename — a first
attempt matched basenames and broke two tests in the full suite but not in
isolation, because `tests/__init__.py` redirects into a temp directory while
keeping the original basenames. Verified: a full suite run no longer changes the
production log's size or mtime. The polluted lines are **left in place** rather
than edited out, per the standing rule that the record is preserved.

Results are unaffected — logging does not touch the decision path — so the
existing baselines stand.

---

## 12. Final assessment

### What this baseline proves

1. **The measurement chain works on real broker data and repeats exactly.** Export → validate → replay → paper broker → ledger → metrics, over 15,735 decisions on real XAUUSD, byte-identical across three runs and three harness versions.
2. **The strategy as it stands produced zero trades** over ~3.5 months of real XAUUSD history, with zero errors. This is a fact about the code and this dataset, not a prediction.
3. ~~**The largest single identified cause is a comparison against a configuration constant.**~~ **WITHDRAWN — see Addendum.** The RR gate is tautological, but it was not the binding term at any of the 1,265 L8 blocks. The binding term was `raw_triggered`, which was `False` for the allowed candidate in every case. The largest identified cause at L8 is **the entry trigger conditions**, not RR.
4. **No look-ahead was detected on real data.** Future mutation changed no past decision at any tested instant.
5. **Live trading remained impossible throughout**, now enforced by a subprocess-level test rather than by reading source.

### What it does NOT prove

- **Nothing about profitability, in either direction.** Zero trades is not a loss and not a win. No edge was measured because none was expressed.
- **Nothing about execution quality.** The fill model, intrabar policy, spread handling and exit logic were never exercised on real data — there were no fills.
- **Nothing about whether fixing E9/E10 would produce a viable strategy.** D5 shows most attrition happens at L3 and L5, well before L8.
- **Nothing generalisable.** One symbol, one broker, ~3.5 months, one market regime in gold's history. No out-of-sample split, no walk-forward, no Monte Carlo.
- **Nothing about the strategy's own reported RR as an outcome measure** — it was never tested against a realised R, because no R was realised.

### Limitations from the dataset and execution assumptions

- **Coverage is ~3.5 months**, bounded by M1, with 22d 17h consumed by warm-up. Too short for seasonal or regime-cycle conclusions.
- **Spread is ASSUMED at 2.0 pips and is optimistic** — the broker quoted 3.9 pips live. Slippage and commission are zero by choice.
- **No latency model** exists.
- **Fixed 0.01 lots**, because `risk_manager` carries a ~10× contract-size defect. All currency figures are therefore scale-arbitrary; R is the meaningful unit, and no R was produced.
- **The broker's own metadata is internally inconsistent** (D1): tick value implies $10/point/lot, contract size implies $100.
- **Regime classification is price-level dependent** (G2/U10), so the regime mix here reflects gold near $3,900–4,300, not volatility structure.

### What should be addressed in the next phase

In priority order, and **measured against this baseline** rather than assumed:

1. ~~**E9/E10 — the tautological RR gate.** … the single change most likely to move the decision stream.~~ **WITHDRAWN — see Addendum.** Correcting it would admit **zero** additional entries on this dataset. It remains a genuine latent defect worth fixing for correctness, but it is not the constraint to investigate first. **The entry trigger conditions are** — specifically the five-way AND in the momentum path and the two-way AND in the pullback path.
2. **D1/R1 — the contract-size vs tick-value contradiction.** Until this is resolved, no currency figure from any source can be trusted, and `risk_manager` cannot be re-enabled.
3. **U1/Q6, U8, U9, U10 — the price-unit confusion**, migrated as one coherent change through `core.units`, not piecemeal.
4. **D8 — the unreachable `LondonNewYork` label**, and an audit for other session-name mismatches.
5. **D5 — the L3/L5 attrition**, investigated only *after* the above, since fixing L8 changes what reaches them.
6. **Coverage.** Obtain more M1 history before any statistical validation; 3.5 months cannot support walk-forward.

**Do not tune any threshold before step 1 is measured.** With zero trades as the
baseline, any change that produces trades will look like an improvement, and
there is currently no way to distinguish more trades from more losses.

---

---

## Addendum — correction to the causal attribution (2026-09-17)

Added after Phase 4A pre-analysis. **No measurement in this report changed, and
no baseline artifact was touched.** What changed is a claim I drew *from* the
measurements, which the measurements did not support.

### What I claimed

That the RR tautology accounted for 994 of the 1,265 L8 blocks — "decided before
the market was consulted" — and was therefore "the largest single identified
cause" and the first thing to correct.

### Why it was wrong

`entry_triggered = raw_triggered and valid_rr`. I verified the `valid_rr` term
was tautological and then attributed the blocks to it **without measuring the
`raw_triggered` term**. Two true statements were run together:

- In MICRO_SCALP and DEAD_CALM, `valid_rr` can never be true. *(True.)*
- Therefore `valid_rr` is what blocked those decisions. *(Does not follow.)*

A conjunction is false as soon as either term is false. Establishing that one
term is always false says nothing about which term was actually binding.

### What the measurement shows

All 1,265 L8-blocked instants were replayed and the production entry functions
re-invoked with the inputs `main_production` passes them. The reconstruction
proved itself faithful: `setup_type`, `rr` and `rr_valid` matched the production
`layer_8` on **1,265 / 1,265**.

| Candidate | `raw_triggered = True` | `= False` |
|---|---|---|
| momentum | 0 | 1,265 |
| pullback | 11 | 1,254 |
| **allowed candidate for the regime** | **0** | **1,265** |

All 1,265 exited via the trigger path; none reached the entry-quality gate. The
11 pullback near-misses are all MICRO_SCALP, where `allowed_styles = ["MOMENTUM"]`
— so the pullback candidate was not evaluated, and the momentum candidate did not
fire.

**Forcing `valid_rr = True` would therefore have produced 0 additional entries.**
`raw_triggered` depends on the rejection candle, M1 CHoCH, displacement, FVG and
kill zone — none of which read TP or RR.

### Corrected conclusion

1. **`rr ≡ tp_ratio` is a genuine defect.** `calculate_entry_levels` derives the
   target from `tp_ratio` and then tests the resulting ratio against `2.0`, so the
   gate reads a configuration constant. Unchanged and still proven.
2. **It is latent, not active.** It has never been the binding term on this
   dataset. It would bind the moment an allowed candidate fires in a
   `tp_ratio < 2.0` regime — which has not yet happened.
3. **It was not demonstrated to cause the 1,265 L8 blocks.** It caused none of them.
4. **The binding constraint at L8 is `raw_triggered`** — the two-way AND in the
   pullback path and the five-way AND in the momentum path.

### The number 994 still means something — just not that

994 is the count of L8-*reaching* decisions **in** a regime where `valid_rr` is
unsatisfiable. That is a real and useful measure of how much runtime sits in a
structurally unenterable regime. It is **not** a count of decisions the RR gate
blocked, which is 0.

`baselines/baseline_00{1..4}/defect_observations.json` contains a field named
`share_of_l8_blocked_by_tautology`. **That name asserts a causation the data does
not support.** The artifacts are immutable and were not edited; the field is
renamed in `backtest/baseline.py` so future baselines do not repeat it, and its
recorded value (0.785771) should be read as "share of L8-reaching decisions that
were in an unreachable regime", not as an attribution.

### A note on the discarded TP target

Separately established while defining Phase 4A, and recorded here because it
bears on any future attempt to "fix" the RR gate: L4 computes a `tp_pool`, and
`assess_liquidity_gate` strictly validates it as being on the profitable side of
price with `score >= 60`. It is stored in `analysis["layer_4"]["tp_pool"]` and
then **never passed to L8** — `get_entry_trigger` takes no such argument. All
1,265 L8-blocked decisions had a valid `tp_pool` available and discarded.

Measured across the allowed candidates, the RR that pool would have implied:

| | Pool-implied RR | RR actually used |
|---|---|---|
| median | **0.25** | 1.5 / 2.0 / 3.0 (= `tp_ratio`) |
| p75 | 0.45 | — |
| ≥ 2.0 | 19 / 1,504 (**1.3%**) | 100% by construction |

So substituting the pool as the target is **not** a neutral bug-fix. The
synthetic target sits roughly 6× further away at the median, and a genuine
`rr >= 2.0` test against the pool would reject about 99% of setups. Whatever is
done about the tautology, the `2.0` threshold would then need a justification it
does not presently have.

### Method

Read-only. No strategy file was modified, and nothing was committed to strategy
code. The probe replays recorded decision instants and calls the production
functions; replaying a subset is sound because the replay is deterministic and
each decision depends only on bars visible at its own instant — confirmed by all
1,265 reproducing their recorded block exactly.

*Phase 3A complete. Awaiting approval before proceeding.*
