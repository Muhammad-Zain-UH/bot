# Claude Code prompts — V2 programme

## How to use this file

1. Put `CLAUDE.md` (repo root), `docs/ROADMAP_V2.md` and this file into the
   repo on branch `phase-0-1-foundations`, and commit them yourself:
   `git add CLAUDE.md docs/ROADMAP_V2.md docs/PROMPTS_V2.md`
   `git commit -m "v2: plan of record"`
2. Open Claude Code in VS Code at the repo root. Paste **one prompt at a time**,
   in order. Each prompt ends with a commit and a 15-line reply.
3. After each step, paste Claude Code's reply (and the report it wrote) into
   the Claude chat for review before you run the next prompt. Prompts with a
   `<placeholder>` need a value from the previous step.
4. Never skip ahead. P6 and later run **only** if a hypothesis survives.

---

## P0 — Freeze the legacy pipeline, set up V2

```text
Read CLAUDE.md and docs/ROADMAP_V2.md completely. I approve owner decisions D1–D6 in ROADMAP_V2 §2.

Task P0 — freeze the legacy pipeline and set up the V2 skeleton. Do not change any legacy code.

1. Create docs/LEGACY_FROZEN.md (max 40 lines): the frozen modules (the repo-root *.py files), the evidence (headline of research/PRODUCTION_PATH_AUDIT_REPORT.md, headline of research/ORIGINAL_CONTINUATION_AUDIT_REPORT.md, 4–6 trades per 16-week replay in baselines 006–014), and that Phase 8 items P8-01…P8-20 are closed as "not pursued — strategy frozen (D1)". Add one line at the top of docs/PHASE_8_RESEARCH_LEDGER.md pointing to it.
2. Create research/templates/HYPOTHESIS_TEMPLATE.md and research/templates/REPORT_TEMPLATE.md (max 60 lines each).
   Hypothesis template sections: ID and name; mechanism and external evidence; data, timeframe and arms; exact construction with every constant listed; tests and their count; controls; DEV replication rule; economics rule; evidence against; power pre-check result.
   Report template sections: one-line verdict; pre-declared results table; controls table; economics table; limitations (max 5 bullets); changes.
3. Append a section "V2 amendments (2026-10)" to research/RESEARCH_TO_STRATEGY_GATE.md: copy the six numbered rules of ROADMAP_V2 §5 verbatim, then one sentence: "Where these conflict with earlier sections, these govern."
4. Create the package skeleton gold/ with subpackages data, econ, stats, hyp, sim, sleeves, portfolio, live, tests. Only __init__.py files, plus gold/tests/test_smoke.py with one import test.
5. Run the legacy test suite and the gold tests. Everything must pass.
6. Commit: "v2: freeze legacy pipeline, templates, gate amendments, gold/ skeleton".
```

---

## P1 — Build the V2 dataset from Dukascopy

```text
Task P1 — build the V2 dataset from Dukascopy, per ROADMAP_V2 §4. Data work only; no strategy code.

Download
1. Check Node.js >= 18 (node --version). If missing, stop and tell me. Run `npx dukascopy-node --help` and confirm from the help output the flags for: instrument, from/to dates, timeframe m1, price type bid/ask, csv format, volumes, retries, batch size/pause, output directory, and how zero-volume "flat" candles are handled. Use the help output, not memory.
2. Write gold/data/download_dukascopy.py: download XAUUSD m1 BID and ASK separately, one calendar year per file, 2003-05-05 to 2026-10-01 UTC, into data/dukascopy_v1/raw/{bid,ask}/XAUUSD_m1_{side}_{year}.csv. Resumable: skip a year whose file exists and passes a row-count sanity check. Never overwrite an existing raw file (refuse, as research/build_accessible_bar_dataset.py does for raw_server/). Retries with backoff. Log row counts per year.
3. Add data/dukascopy_v1/ to .gitignore. Run the download. It can take hours; when it finishes, continue.

Build
4. gold/data/build_v2.py: inner-join bid and ask on timestamp (report rows dropped from each side per year); exclude zero-volume flat candles. Columns: time (UTC, bar open), bid_o, bid_h, bid_l, bid_c, ask_o, ask_h, ask_l, ask_c, mid_o, mid_h, mid_l, mid_c (= (bid + ask) / 2 per field), spread_c (= ask_c − bid_c), volume. Write data/dukascopy_v1/bars/XAUUSD_M1.parquet.
5. Resample from M1: M15, H1, H4 (left-labelled, left-closed, UTC) and D1 with the day boundary at 17:00 America/New_York (DST-correct with zoneinfo). Write each as Parquet.

Validate (the build fails on any of these)
6. Unique, increasing time; high >= max(open, close) and low <= min(open, close) for bid, ask and mid; ask >= bid on every field; no NaN.
   Price sanity: the max mid_h in September 2011 is between 1,890 and 1,930, and the max mid_h in August 2020 is between 2,050 and 2,090. If not, the price scaling is wrong — stop and tell me.
7. Report without failing: bars per year; the longest gaps per year, excluding weekends and the 17:00–18:00 New York break; spread_c median and p95 per year and per New York hour.

Fingerprint and split
8. Fingerprint every frame with the method in research/dataset_access._fingerprint. Write research/dukascopy_v1_fingerprints.json (committed).
9. Write research/research_split_manifest_v2.json: TRAIN 2003-05-05 → 2016-12-30, DEV 2017-01-02 → 2025-09-01, FINAL_OOS 2025-09-02 → 2026-10-01 locked with token "OOS-AUTHORISATION-NOT-ISSUED", purge of one trading day after each boundary.
10. gold/data/store.py: load_v2(tf, arm, oos_authorisation=None) verifies fingerprints and raises research.dataset_access.OOSLockedError for FINAL_OOS without the exact token. Import from research/dataset_access.py wherever possible instead of duplicating it.

Reconcile with the broker
11. gold/data/reconcile.py, on the H1 and M15 overlap with data/research_v1 (UTC-normalised frames via research/dataset_access, TRAIN and DEV arms only): best timestamp lag by return correlation (must be 0 minutes), H1 log-return correlation, median and p95 of |close difference|, fraction of bars whose high or low differ by more than $1.
12. Cost calibration, outside every research arm: write gold/data/calibrate_cost.py. It fetches the broker's XAUUSD ticks with MT5 copy_ticks_range for the full week 2026-10-05 00:00 UTC → 2026-10-09 21:00 UTC, resamples them to M1 bid/ask spreads, and downloads Dukascopy m1 bid/ask for exactly the same dates into data/dukascopy_v1/calibration/ (never into raw/). Compute both median spreads over minutes present in both. k_cost = max(1, broker_median / dukascopy_median). Store k_cost and the window under "cost_calibration" in research/dukascopy_v1_fingerprints.json. Do not use the existing 2026-09-24 tick sample: it lies inside FINAL_OOS. If that week has not finished yet, finish every other step, commit, and tell me — run step 12 later as its own commit.

Tests (gold/tests/test_data_v2.py)
13. Synthetic bid/ask fixture: join, flat exclusion, mid and spread arithmetic, the D1 boundary across both 2024 New York DST changes (2024-03-10 and 2024-11-03), resample truncation (resampling a prefix equals the prefix of the resample, for complete bars), OOS lock raises.

Report
14. research/DATASET_V2.md (max 120 lines): coverage, validation results, spread per year, reconciliation table, k_cost, fingerprints.
15. Commit code, manifest, fingerprints, report and tests (never data): "data: Dukascopy XAUUSD M1 bid/ask 2003-2026 -- V2 dataset frozen".
```

---

## P2 — Economics module and power pre-check

```text
Task P2 — economics module and power pre-check for H07–H11 (ROADMAP_V2 §5–§6).
Rule for this task: do not print, log or store the mean of any hypothesis variable. Only counts, standard deviations and costs.

1. gold/econ/costs.py:
   - round_turn_cost_usd(spread_entry_usd, spread_exit_usd, k_cost) = k_cost × (spread_entry_usd + spread_exit_usd) / 2
   - cost_in_log_units(cost_usd, price_usd)
   - financing_usd(notional_usd, nights, side, dff_annual, markup=0.025): long pays dff_annual + markup, short pays markup, prorated by calendar nights / 365 (weekends count as calendar nights).
   Unit tests for each.
2. Add DFF to SERIES in research/acquire_cross_asset.py and fetch it the same way as the other FRED series; extend the existing verification.
3. Implement the hypothesis variables exactly as ROADMAP_V2 §6 defines them, as pure functions over the M1 frame returning one row per day, constants at module top:
   gold/hyp/h07_sessions.py (six blocks), gold/hyp/h08_intraday_momentum.py (days with r_early == 0 are dropped), gold/hyp/h09_pm_auction.py.
   Tests: synthetic M1 fixture with known prices, including a DST-change week in New York and in London, and a day with a missing anchor minute (must be dropped); truncation test.
4. gold/econ/power.py, TRAIN only: for H07 (each block), H08, H09 record N (one observation per day), the standard deviation of the variable whose mean will be tested, and the median DEV-era round-turn cost (× k_cost) in the same log units. z = Bonferroni two-sided at α = 0.05 over the batch-1 test count (8). MDE = z × sd / sqrt(N). TESTABLE if MDE <= cost.
   For H10 and H11: N weekly observations in TRAIN and DEV, and the Sharpe standard error ≈ sqrt((1 + SR²/2) / years) for SR = 0.3 and 0.5.
5. research/POWER_V2.md (max 60 lines): one table and one verdict per hypothesis. A batch-1 hypothesis that is NOT TESTABLE is dropped from batch 1, and the test count and z are recomputed — state the final count and z.
6. Commit: "research: V2 economics and power pre-check".
```

---

## P3 — Pre-register batch 1

```text
Task P3 — pre-register batch 1: only the hypotheses research/POWER_V2.md marks TESTABLE among H07, H08, H09.

1. Write research/v2/H07_SPEC.md, H08_SPEC.md, H09_SPEC.md from research/templates/HYPOTHESIS_TEMPLATE.md. Copy constructions, tests, controls, the DEV rule and the economics rule from ROADMAP_V2 §5–§6 exactly. Add: the final batch test count and TRAIN z threshold from POWER_V2.md, the era definitions, the bootstrap seed, and "evidence against" = any of: TRAIN not significant; a control fails; the sign differs across TRAIN eras; DEV one-sided p >= 0.05; DEV net per trade <= 0 at 1× cost.
2. Do not add variants, extra windows, extra horizons or diagnostics that could later be chosen from. If you think something is missing, ask me before committing.
3. Commit the specs alone: "research: pre-register V2 batch 1". Tell me the commit SHA, then stop.
```

---

## P4 — Run batch 1

```text
Task P4 — run batch 1 exactly as pre-registered at commit <SHA from P3>.

1. gold/stats/infer.py: thin wrappers over research/phase1_statistical_controls.py — t statistic on per-day observations as the headline, and a calendar-month block bootstrap (10,000 draws, seed from the spec) as the secondary estimator, flagging ESTIMATOR_SIGN_DISAGREEMENT as the existing standard requires.
2. research/v2/run_batch1.py: load TRAIN via gold.data.store; compute every pre-registered statistic and control; fix each direction from TRAIN; then load DEV and evaluate DEV replication and economics at 1× and 2× cost (DEV-era spreads × k_cost). Assert that FINAL_OOS is never loaded.
3. Save research/v2/batch1_results.json. Write research/v2/BATCH1_REPORT.md from the report template (max 120 lines). Verdict per hypothesis — SURVIVES / NOT SUPPORTED / INCONCLUSIVE — by the pre-registered rules only.
4. Do not change any spec, threshold or window after seeing results. If something looks like a bug, stop and tell me before fixing it.
5. Commit: "research: V2 batch 1 -- <n> survivors".
```

---

## P5 — Batch 2 (slow effects)

```text
Task P5 — batch 2 (H10, H11), per ROADMAP_V2 §6 and the external-prior standard in §5 rule 5.

Step A — commit alone first.
Write research/v2/H10_SPEC.md and H11_SPEC.md from the template: constructions, execution timing and financing exactly as ROADMAP_V2 §6. For H11, compute only σ* (the median of σ21 over TRAIN) — no returns — and write its value into the spec. Commit: "research: pre-register V2 batch 2 (H10-H11)". Tell me the SHA.

Step B.
1. gold/hyp/h10_tsmom.py and gold/hyp/h11_vol_managed.py: pure functions over D1 (decisions) and M1 bid/ask (execution prices). Decide at the Friday 17:00 New York close; execute at the first M1 bar >= 60 minutes after the Sunday open; cost = half-spread × |Δposition| × k_cost; financing every night via gold/econ/costs.financing_usd.
2. research/v2/run_batch2.py: TRAIN and DEV — net Sharpe, CAGR, max drawdown, longest underwater, turnover, Sharpe standard error, share of net P&L per era; benchmark = cash for H10, buy-and-hold with the same financing for H11. FINAL_OOS never loaded (assert).
3. Tests: no lookahead (position for week w uses data up to that week's Friday close only), financing arithmetic, execution-bar selection across a DST change.
4. research/v2/BATCH2_REPORT.md (max 120 lines), verdicts by §5 rule 5 only. Commit: "research: V2 batch 2 results".
```

---

## P6 — Sleeves and portfolio (only with survivors)

```text
Task P6 — run only if at least one hypothesis SURVIVES in research/v2/BATCH1_REPORT.md or BATCH2_REPORT.md. If none does, stop and tell me (use P-STOP instead).

1. gold/sim/trades.py — trade simulator on M1 bid/ask.
   Input: one row per intent (decision time UTC, side, entry = next M1 open, stop distance in USD, exit time UTC, optional target in USD).
   Output: one row per trade — entry and exit price, exit reason (STOP / TARGET / TIME / ROLLOVER), gross_usd, cost_usd, net_usd, R.
   Rules: buys fill at ask and sells at bid, spread scaled by k_cost; long stops checked against bid lows and short stops against ask highs on every M1 bar; stop and target in the same bar → STOP; a gap through the stop fills at that bar's open; forced exit before 17:00 New York.
   Tests: a hand-built fixture for each exit reason; agreement with execution/intrabar.resolve_intrabar on shared fixtures; truncation test.
2. Write research/v2/SLEEVES_SPEC.md and commit it alone BEFORE any DEV simulation: one sleeve per survivor, its rule as tested, and the risk mechanics of ROADMAP_V2 §7.1. Then gold/sleeves/<name>.py, one class per sleeve, generating intents from closed bars only — the same class will run live.
3. Simulate TRAIN, then DEV. Run the robustness neighbourhood of ROADMAP_V2 §7.3 as a check only; the frozen values stay.
4. gold/portfolio/combine.py: equal risk per sleeve via core.sizing.lots_for_risk; core.risk_limits for the daily cap and drawdown halt with the D6 values. Report per sleeve and for the portfolio, DEV only: trades per week, mean R, net Sharpe, max drawdown, worst month, sleeve correlations.
5. research/v2/STRATEGY_REPORT.md (max 120 lines). Commit.
```

---

## P7 — FINAL_OOS, one look

```text
Task P7 — FINAL_OOS validation, one look. Authorisation token: <owner writes token here>.

1. Before loading anything, record in research/research_split_manifest_v2.json: today's date, the git SHA, the SHA of research/v2/SLEEVES_SPEC.md, and the token.
2. Run the frozen portfolio from P6 on FINAL_OOS: the Dukascopy bars, and separately the broker's research_v1 FINAL_OOS bars for execution realism. No parameter, sleeve or rule may change.
3. Report the same table as STRATEGY_REPORT.md plus a DEV-versus-OOS comparison. PASS if portfolio net result > 0 at 1× cost and the OOS mean R lies inside the DEV 90% bootstrap interval; otherwise FAIL. A FAIL ends this portfolio version.
4. research/v2/FINAL_OOS_REPORT.md (max 80 lines). Commit: "research: FINAL_OOS -- PASS" or "-- FAIL".
```

---

## P8 — Live engine for shadow trading (only after a PASS)

```text
Task P8 — live engine for shadow trading on an MT5 DEMO account. core/safety.py LIVE_TRADING_ENABLED stays False.

1. execution/mt5_broker.py: MT5Broker implementing the execution.broker.Broker protocol. Filling mode from symbol_info; respect trade_stops_level and the freeze level; round volume to volume_step within volume_min/volume_max; magic number per sleeve; idempotent order identity via execution/trade_identity.py. Refuse to send any order when account_info().trade_mode is not DEMO while LIVE_TRADING_ENABLED is False — raise, and test it with a fake MetaTrader5 module.
2. gold/live/clock.py: broker server time → UTC, measured at startup from the last tick versus UTC now and re-measured every hour; sessions via zoneinfo.
3. gold/live/runner.py: on each closed M1 bar, build frames from broker M1 (closed bars only); run each sleeve class from P6 unchanged; apply the event filter (calendar CSV in data/calendar/, loaded at start; refuse to trade on any day the calendar does not cover); core.risk_limits; then MT5Broker. Reconcile open positions by magic number on startup and after reconnect. Persist state atomically. Optional Telegram alerts via environment variables.
4. gold/live/monitor.py: rolling 40-trade mean R per sleeve versus the DEV 5th percentile → auto-pause that sleeve; slippage = actual fill minus simulated fill, logged per trade.
5. Tests with a fake MetaTrader5 module: placement, rejection handling, reconnect reconciliation, a DST week, the demo-only refusal.
6. docs/RUN_SHADOW.md (max 40 lines): how to start, stop and read the logs. Commit.
```

---

## P9 — Weekly shadow review (repeat each week)

```text
Task P9 — weekly shadow review. Read the past week's live logs. Per sleeve: trades, mean R with its interval versus DEV, slippage versus the simulator, rejected orders, auto-pauses. Max 30 lines. Recommend continue / pause sleeve / investigate. Do not change any sleeve parameter.
```

---

## P-STOP — if nothing survives

```text
Task P-STOP — no hypothesis survived. Write research/v2/CONCLUSION.md (max 60 lines): what was tested, the result of each test, and the three options in ROADMAP_V2 §8 with a short cost and benefit for each. Do not propose new gold hypotheses in this document. Commit and stop.
```
