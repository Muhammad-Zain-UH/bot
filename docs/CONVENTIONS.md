# Engineering conventions

Rules for code written from Phase 1 onward. They exist because each one
corresponds to a defect the Phase 1 audit actually found — none is theoretical.

Existing strategy modules have **not** been migrated onto these conventions.
Doing so changes trading behaviour, which is deferred until a measured baseline
exists. Violations are catalogued in [`PHASE_2_ISSUES.md`](../PHASE_2_ISSUES.md).

---

## 1. Units: a bare number is never a distance

**Rule:** any price distance, threshold or buffer is a typed quantity from
`core.units`, and every conversion takes an explicit `SymbolSpecification`.

On XAUUSD (1 pip = $0.10 = 10 points) these are three different quantities:

```python
PriceDistance(3.0)   # $3.00  = 30 pips = 300 points
Pips(3.0)            # $0.30  =  3 pips =  30 points
Points(3.0)          # $0.03  = 0.3 pip =   3 points
```

```python
# WRONG - what entry_engine does today. Is 3.0 dollars or pips?
stop = swing_low - 3.0                      # $3.00 buffer; 3 pips was intended

# RIGHT - the unit is in the type, and the instrument is named
stop = Pips(3.0).to_price(spec).below(swing_low)
```

Mixing units raises `UnitMismatchError` rather than silently converting.

**Why:** ten live thresholds are 10x their intended size. `max_sweep_distance =
60.0` "pips" is $60 — 600 pips — so the cap never binds.

**Corollaries**

- Never hardcode `0.10`, `100`, or any instrument fact. Ask the
  `SymbolSpecification`; obtain it from the broker.
- MT5's `(ask - bid) / point` is **points**, not pips.
- `Percentage(0.5)` means 0.5 %. Use `Percentage.from_fraction(0.005)` if you
  hold a fraction.
- `AtrMultiple` is dimensionless until resolved against a real ATR.

---

## 2. Bars: the convention is declared, never inferred

**Rule:** a frame's bar convention is a property of the frame, stated by whoever
produced it. Access bars through `core.candles`.

```python
BarConvention.CLOSED_ONLY       # every row is complete; last_closed is iloc[-1]
BarConvention.INCLUDES_FORMING  # final row is live;     last_closed is iloc[-2]
```

`get_market_data(closed_only=True)` returns `CLOSED_ONLY`, which is the project
default. So **`iloc[-1]` is the last closed bar.**

```python
# WRONG - stale by one full bar on a CLOSED_ONLY frame
current = m5_data.iloc[-2]

# WRONG - double-drop; removes a forming bar that is not there
closed = frame.iloc[:-1]

# RIGHT
current  = last_closed_bar(m5_data, BarConvention.CLOSED_ONLY)
previous = previous_closed_bar(m5_data, BarConvention.CLOSED_ONLY)
```

`closed_bars()` is idempotent under `CLOSED_ONLY`; `.iloc[:-1]` is not.

**Two failure modes, both silent:**

- **Repainting** — using the forming bar. Its high/low/close change as it
  develops, so the signal changes with it and vanishes after the close.
- **Staleness** — using `iloc[-2]` on a `CLOSED_ONLY` frame. A full bar of lag
  for no benefit.

**Why:** seven call sites disagree. A pullback entry is priced off a bar that
closed five minutes ago while a momentum entry uses the current one.

`forming_bar()` returns `None` under `CLOSED_ONLY`. It is legitimate only for
display and live stop/target monitoring — never for structure, sweeps or entries.

---

## 3. Time: injected, aware, and UTC internally

**Rule:** no `datetime.now()`, `datetime.today()` or `time.time()` in decision
logic. Take a `Clock` and call `now_utc()`.

```python
# WRONG - untestable, unreplayable, silently machine-dependent
def within_kill_zone() -> bool:
    return datetime.now(timezone.utc).hour in range(8, 10)

# RIGHT
def within_kill_zone(clock: Clock) -> bool:
    return clock.now_utc().hour in range(8, 10)
```

Four distinct timelines, never conflated:

| Timeline | Use |
|---|---|
| **UTC** | All internal reasoning and all persisted timestamps. |
| **broker** | MT5 server clock. Bar timestamps; daily boundaries; PDH/PDL. |
| **local** | Operator display **only**. No decision may depend on it. |
| **session** | Market session, derived from UTC. |

**Every datetime is timezone-aware.** A naive datetime is rejected at the domain
boundary — it is what allows local time to be compared against UTC market data
with no error raised.

The broker offset is an explicit constructor argument. Inferring it from bar
timestamps produces an offset that silently breaks across DST.

**Why:** `_count_today_entry_signals` compares a naive local date against UTC
data. On a machine far enough from UTC the daily counter reads the wrong day.

Use `FakeClock` in tests. `ReplayClock` arrives with the backtest engine (Phase 3).

---

## 4. ATR: one definition

**Rule:** `core.indicators.atr_wilder` is the only ATR.

- **Input:** `high`, `low`, `close`.
- **Bars:** closed only — otherwise ATR repaints, and so does every threshold
  derived from it.
- **True range:** `max(H-L, |H-C_prev|, |L-C_prev|)`. The first bar has no
  previous close, so it is dropped, not approximated.
- **Smoothing:** Wilder's RMA, seeded with the mean of the first `period` true
  ranges. Matches MetaTrader.
- **Unit:** `PriceDistance` — quote-currency price, **never pips**. Convert
  explicitly with `.to_pips(spec)`.
- **Insufficient bars:** raises `InsufficientBarsError`. Never returns a default.

Implemented in plain pandas/numpy, not `pandas_ta` (the installed build is a
beta, `0.4.71b0`).

**Why:** four incompatible implementations coexist and are compared against each
other. `sweep_detector` uses `close.diff().abs().rolling(14).mean()`, which
cannot see intrabar range at all — and its output sets the minimum wick depth for
a sweep. Three of the four also return a fabricated default (`15.0`, `10.0`) when
data is short.

---

## 5. Domain types over dictionaries

**Rule:** new code passes types from `core.types`, not `dict[str, Any]`.

```python
# WRONG - a typo yields a default and the pipeline continues on a fake zero
score = poi.get("scoer", 0)

# RIGHT - invalid states cannot be constructed
stop = StopLoss(price=3990.0, entry_price=4000.0, side=Side.BUY)
```

Invariants are enforced at construction, not checked later:

- `StopLoss` / `TakeProfit` — must sit on the correct side of entry.
- `MarketBar` — `high >= low`, and the range must bracket open and close.
- `MarketPrice` — no crossed book; `price_for(side)` gives the executable side.
- `RiskParameters` — risk is a `Percentage`, positive, `<= 100`.
- `Position` — `broker_verified` defaults to `False`.
- `Side.from_bias()` — rejects `NEUTRAL` instead of turning it into a short.

**Why:** `entry_engine` computes `risk_distance = abs(entry - stop)` with no side
check, so a stop above entry on a BUY yields a positive risk distance and flows
onward as a normal trade.

Migration is incremental, one boundary at a time. Rewriting eight layers at once
is the failure mode being avoided.

---

## 6. Fail loudly

**Rule:** missing or invalid data raises. It never becomes a plausible default.

```python
# WRONG - fabricates a volatility reading out of nothing
except Exception:
    return default  # 15.0

# RIGHT
raise InsufficientBarsError(f"ATR({period}) needs {period + 1} bars, got {len(frame)}")
```

Never wrap decision logic in a blanket `except Exception` that downgrades to a
neutral result. `analyze_entry` converts *any* exception — a `KeyError`, a unit
bug — into `signal_type="ERROR"`, silently.

A trading process that cannot do its job must stop, not continue quietly. See
`core.safety`: an invalid execution configuration refuses startup rather than
degrading into a no-op that looks like normal operation.

---

## 7. `core` stays pure

Rules enforced by `tests/core/test_core_constraints.py`, which parses the AST:

1. **No `MetaTrader5` import.** `core` must be importable and testable with no
   broker terminal. Broker data enters via duck-typed adapters such as
   `SymbolSpecification.from_mt5_symbol_info`.
2. **No ambient clock** outside `core/clock.py`.
3. **No import cycles.** The graph is one-way:
   `symbols → units → types`; `clock`, `candles`, `safety`, `signal_log` depend on
   at most `symbols` and `units`. `core/__init__.py` re-exports nothing.
4. **No undeclared dependencies.** Only stdlib, `pandas`, `numpy`. `pydantic` is
   installed in the virtualenv but absent from `requirements.txt`, so it is not
   used.

---

## 8. Tests never touch production data

`tests/__init__.py` redirects every output path to a temporary directory **before
any project module is imported** — several resolve their paths at import time, so
the ordering is load-bearing.

**Why:** four fabricated `ENTRY SIGNAL GENERATED` records reached
`trading_bot_production.log` from `tests/test_layer_gate_logic.py`, simply because
importing the module under test opened the production log for append. That put
invented trade data into the only record of what the system had done.

`tests/core/test_log_isolation.py` is the regression guard.

Fixtures are deterministic. Expected values are derived by hand in the fixture's
docstring — a golden number nobody can re-derive is a number nobody can trust.

---

## 9. Floats, not `Decimal`

MT5 returns float64 and the pipeline is pandas. `Decimal` at this boundary would
force conversions everywhere for no accuracy gain on tick-quantised values.

Precision is handled explicitly instead: comparisons use a tolerance
(`COMPARISON_TOLERANCE = 1e-9`), and broker-valid values are produced on demand
via `round_to_tick`, `round_volume_to_step` and `PriceDistance.quantize`.

Volume rounds **down** — rounding a position size up takes more risk than the
risk engine authorised.

---

## 10. Measure before tuning

Priority order:

> safety → correctness → determinism → testability → backtesting →
> statistical validation → strategy improvement → optimization

Not:

> more indicators → more filters → more confidence → more trades → "profitability"

**No threshold in this system currently has any empirical basis.** Until a
backtest harness exists, changing one swaps an unvalidated configuration for
another. Never optimise for trade count. Never claim profitability without
out-of-sample evidence.

Found something obviously wrong? Record it in `PHASE_2_ISSUES.md`. Do not tune it.

---

## 11. Replay and bar availability

**Rule:** a bar is visible at replay time `T` if and only if

```
bar.open_time + timeframe.duration <= T
```

MetaTrader stamps a bar by its **open** time. An M5 bar stamped `10:35` covers
10:35:00–10:39:59 and only becomes known at `10:40`.

```
At T = 10:37:00
  M1   10:36  closed 10:37   visible
  M5   10:30  closed 10:35   visible
  M5   10:35  closed 10:40   NOT visible
  M15  10:15  closed 10:30   visible
  H1   09:00  closed 10:00   visible
  H4   04:00  closed 08:00   visible   (the 08:00 bar closes at 12:00)
```

The boundary is inclusive: a bar closing exactly at `T` is visible.

Treating the stamp as a close time is the classic silent look-ahead. It never
raises, it looks right on a chart, and it makes every backtest optimistic
because the strategy sees the outcome of the bar it is deciding on.

Future bars are **not materialised** into the frame the strategy receives — they
are absent, not filtered. `ReplayFeed.bars()` returns a defensive copy, so a
retained reference cannot later grow.

**Short history returns an EMPTY frame, not a partial one.** That mirrors
`mt5_handler.get_market_data`, which refuses any request it cannot fill
completely. Returning a short frame would feed the strategy something
production never sees.

**Entries fill on the next bar's open.** A decision is taken after a bar closes,
so filling at that same close would trade at a price only knowable once the
opportunity had passed. Gaps fill at the open — worse than the level.

**Ambiguous bars follow an explicit policy.** When one bar contains both stop
and target, OHLC cannot say which came first. The baseline is `CONSERVATIVE`
(stop first), chosen before any result was seen. Every ambiguous resolution is
counted and reported; changing the policy to improve a headline figure would be
curve-fitting the simulator, which is harder to detect than curve-fitting the
strategy.

**The replay clock is temporary Phase 2A infrastructure.** `backtest.clock_patch`
scopes a frozen `datetime` into `risk_manager`, `entry_engine` and
`main_production` for the duration of one decision, then restores it in a
`finally`. It exists because those modules read the wall clock directly (N1–N4)
and Phase 2A may not edit strategy files. Phase 3 should replace it with real
injection per §3.

A test stub that reads `datetime.now()` in its **own** module is *not* covered by
that patch and will be wall-clock dependent. This bit us once: a determinism
stub gated on `now.minute % 2` and passed or failed depending on when the suite
ran. Route clock reads through a patched module.

---

## 12. Integration fixtures (Phase 2A.1)

**Rule:** an integration fixture may be *shaped* to meet the strategy's existing
conditions. It may never be used to *change* them.

Phase 2A showed a random walk blocks at L1/L2 essentially always — the strategy
looks for trend, impulse, retracement, a sweep of equal lows, then a reclaim, and
a walk produces that only by accident. So
`tests/fixtures/integration_market.py` scripts that sequence explicitly.

What that is allowed to mean:

- arranging price action the gate is written to detect (equal lows, a sweep wick,
  a rejection candle)
- positioning the path so real liquidity exists where the strategy looks for it
  (the start price is solved so a round number sits within $2 of the close, which
  is what lifts L4's take-profit pool to a passing score)
- choosing a decision instant on a weekday in the London session, because
  `get_current_session` returns `"Closed"` at weekends and costs −15 on L7

What it must never mean:

- lowering a threshold, weight, period or ratio
- mocking `analyze_entry`, stubbing a layer, or hand-writing a signal dict
- inserting a trade into the ledger directly

**If the strategy declines to signal, report the blocking layer. Do not force
it.** A zero-signal integration result is a valid finding.

### Alignment is load-bearing

Phase boundaries are chosen so the M15 grid lands correctly:

```
warmup (multiple of 15) | impulse 240 | retrace 90 | basing 45 | reclaim 15 | trigger 10
```

The reclaim must be **exactly one M15 candle**. L3 reads `closed.iloc[-1]` (it
drops an extra bar) while L5's CHoCH reads `iloc[-1]`, so only a single-candle
sweep lets L3 still see the retracement low while L5 already sees the reclaim.

### Clamp the extreme you are not pooling

Each basing candle pins the pooled extreme (lows for a long) *and* clamps the
opposite one. Without the clamp, noise forms a fractal on the other side and
`pullback_detector._find_recent_fractal_swing` anchors to it instead of the
impulse swing — observed as `retracement_ratio=0.071` and
`"Swing too recent (2 bars)"`. Derive the clamp from the **preceding** candle, or
it will sit outside the natural range and silently do nothing.

### Realised R will not equal the strategy's nominal RR

The strategy computes RR against an entry price it never gets filled at: the fill
is the next bar's open plus spread. In the reference long trade the nominal ratio
is 3.0 and realised R is 4.33. That gap is the practical effect of
`PHASE_2_ISSUES` B3/B4 and E9 — not a simulator defect.
