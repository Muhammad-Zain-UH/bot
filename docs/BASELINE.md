# Baselines

A baseline is one immutable measurement of the strategy **exactly as it stands**
over a fixed dataset. It is not a performance claim and not a target to improve
against by tuning. It exists so that a later change can be shown to have moved
something, rather than asserted to have.

## What makes a baseline trustworthy

Four properties, each enforced rather than assumed.

**The data is real and unrepaired.** `tools/export_mt5_history.py` is the only
module permitted to import MetaTrader5, and it uses read-only calls only --
`copy_rates_range`, `symbol_info`, `symbol_info_tick`, `account_info`,
`terminal_info`. `tests/execution/test_no_live_execution.py` parses its AST to
keep that true. Exported frames are validated by `data.dataset.validate_bars`,
and a timeframe that fails validation is **not written**. Nothing is cleaned,
back-filled or smoothed: a broker data problem must surface as a missing file,
never as a quietly corrected bar inside a result.

**Time is true UTC.** MT5 reports bar times in the broker server's timezone.
The exporter measures the offset from a live tick and subtracts it. This
matters because `risk_manager` defines its session windows on UTC hours, so
labelling server stamps as UTC would shift every session by the offset. The
measured MetaQuotes-Demo offset is UTC+3. Broker-native H4 and D1 candles are
therefore not aligned to UTC midnight -- D1 opens 21:00 UTC -- and they are kept
that way. Re-cutting them to UTC would substitute synthetic candles for real
ones, and `HistoricalDataset.derived` records which timeframes, if any, were
resampled. For a baseline it must be empty.

**No look-ahead.** The replay engine answers every data request as of the
decision instant, using the invariant `bar.open_time + timeframe.duration <= T`.
Nothing the strategy can reach is later than `T`.

**It repeats.** Two properties are written to `run_fingerprint.txt`:

- `dataset_sha256` -- hashes bar *values*, not file bytes, so CSV formatting and
  float repr cannot change it.
- `decisions_fingerprint` -- hashes the ordered decision stream: instant,
  regime, signal type, side, layers cleared, blocking layer, stated reason.

The second exists because the first is not enough. `run_fingerprint` combines
the dataset, the ledger and the metrics -- and on a run that produced no trades
the ledger is empty and every metric is `None`, so two runs that disagreed on
every single decision would still produce the same digest. A determinism check
built on that alone would be vacuous.
`tests/backtest/test_baseline_fingerprint.py` mutates each covered field in turn
and requires the digest to move, including tests that field and record
boundaries cannot be smeared into each other.

## What a baseline deliberately does not do

- **It does not size positions.** Every simulated trade is a fixed 0.01 lots.
  `risk_manager` is not consulted, and
  `tests/integration/test_strategy_to_broker.py` enforces that the simulation
  packages cannot import it. One narrow exemption is allow-listed by name:
  `backtest/baseline.py` calls `get_current_session` to label decisions with the
  strategy's own session definition rather than a second one that could
  disagree. That call returns a string and reaches no P&L figure.
- **It does not use the strategy's reported RR as an outcome.** Realised R is
  computed from the actual simulated fill. The strategy's own `rr_ratio` is kept
  beside it as `strategy_rr_ratio`, a diagnostic -- it equals the regime's
  `tp_ratio` by construction (PHASE_2_ISSUES E9) and measures nothing.
- **It does not pretend the spread is historical.** The broker serves OHLC with
  no bid/ask history, so a flat assumption is applied and every manifest records
  `spread_is_assumed: true`.
- **It does not fix anything.** Defects observed during a baseline are recorded
  in `defect_observations.json` and in PHASE_2_ISSUES.md. Changing the strategy
  during a measurement invalidates the measurement.

## Immutability

`write_artifacts` raises `FileExistsError` rather than overwriting. To re-measure,
use a new `baseline_id`. Superseded baselines are kept, not deleted -- a baseline
whose numbers were produced by an older harness is still the record of what that
harness reported.

Every directory holds `manifest.json`, `dataset_manifest.json`, `metrics.json`,
`decision_statistics.json`, `layer_funnel.json`, `regime_statistics.json`,
`exit_statistics.json`, `defect_observations.json`, `side_performance.json`,
`trade_ledger.json` and `run_fingerprint.txt`. Three more appear only when there
is something to put in them: `trade_ledger.csv` (only if the run produced
trades), `rejections.json` (only if orders were rejected), and `decisions.jsonl`
(one line per decision). The last is gitignored -- about 5 MB per run, fully
regenerable, and already covered by `decisions_fingerprint`.

A zero-trade baseline is therefore expected to have no `trade_ledger.csv`, an
empty `trade_ledger.json`, and a `metrics.json` whose ratios are all `null`
rather than zero. `null` means undefined, not 0.0: a win rate over no trades is
not 0%.

## Reading the layer funnel

`layer_funnel.json` reports, per layer, how many decisions reached it and how
many blocked there. Two details matter when reading it.

Reached-counts are cumulative and must be monotonically non-increasing across
L1 to L8. They are matched by prefix (`passed.startswith(layer + "_")`) because
the strategy emits variant labels -- `L6_POI_BYPASSED`, `L5_SWEEP_WAIT`,
`L3_PULLBACK_MOMENTUM`. Matching exact strings instead makes bypassed layers
look unreached and the funnel non-monotonic.

A high block count at a layer is not evidence that the layer is the problem. A
layer can only block what earlier layers let through, so an early gate that is
too tight hides everything behind it.

## Running one

```
python -m tools.export_mt5_history --symbol XAUUSD --from 2026-06-02 --to 2026-09-17 --out data/raw
```

Then drive `backtest.baseline.run_baseline` with the dataset, a
`SymbolSpecification` built by `spec_from_broker_metadata` from the broker's own
`broker_metadata.json`, and a fresh `baseline_id`.

The strategy prints a multi-line banner per decision -- several megabytes over a
full run, enough to dominate runtime. Redirect its stdout to a sink for the
duration. `print()` has no effect on the decision path, so suppressing it changes
no result; run the redirect around the import too, since the banner is written at
module level.
