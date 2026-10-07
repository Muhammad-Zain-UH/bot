# Sizing Contract

The single definition of how a position size is derived from a risk budget.

**Scope.** This is a correctness implementation, not an optimisation. No
strategy entry rule, regime/style rule, `valid_rr`, target or stop semantics,
trade-management behaviour or risk-percentage policy is changed by it. No
baseline is modified.

**Evidence.** The economics were established in Phase 6E and captured from the
actual terminal: `docs/BROKER_SYMBOL_SPECIFICATION_EVIDENCE.md`.

---

# 1. The contract

```
risk_budget    = balance × risk_fraction                    [account currency]
money_per_lot  = stop_distance × money_per_price_unit(1.0)  [account currency]
raw_lots       = risk_budget / money_per_lot                [lots]
lots           = floor_to_step(raw_lots)                    [lots]
actual_risk    = stop_distance × money_per_price_unit(lots) [account currency]
```

Implemented once, in `core/sizing.py` → `lots_for_risk`.

## 1.1 Units

| Quantity | Unit | Not |
|---|---|---|
| `balance` | account currency | — |
| `risk_fraction` | **fraction in (0, 1]** | not a percentage; `0.01` is 1 % |
| `stop_distance` | **price units** | not pips, not points |
| `money_per_price_unit` | account currency per 1.0 price unit per lot | — |
| `lots` | lots | not units, not contracts |

`risk_fraction` rejects values above `1.0`, so a percentage passed by mistake
(`1.0` meaning 1 %) is caught rather than silently risking the whole account.
`risk_manager.calculate_lot_size_for_symbol` keeps the **percentage** signature
its production caller uses and divides by 100 before delegating; it contains no
other arithmetic.

---

# 2. Supported calculation modes

**Which formula applies is a property of the instrument**, read from the
broker's `SYMBOL_TRADE_CALC_MODE`. `core.symbols.CalculationMode` lists only the
modes whose documented profit formula is
`(close − open) × contract_size × lots`:

| Mode | MT5 value | Profit formula |
|---|---|---|
| `FOREX` | 0 | `(close − open) × contract_size × lots` |
| `CFD` | 2 | same |
| `CFD_INDEX` | 3 | same |
| **`CFD_LEVERAGE`** | **4** | same — **the mode of the XAUUSD this repository trades** |

Therefore `money_per_price_unit(volume) = contract_size × volume`.

## 2.1 Unsupported modes raise

Futures and exchange modes compute profit from tick price and tick size, not
contract size. They are **absent from the enum on purpose**:

- `SymbolSpecification.from_mt5_symbol_info` raises
  `UnsupportedCalculationModeError` if the broker reports an unlisted mode, so
  such an instrument cannot be constructed and then priced with a formula that
  does not describe it.
- `money_per_price_unit` raises for the same reason.

Adding a tick-based mode is **an explicit separate implementation** with its own
evidence. It must not be reached by widening the enum.

---

# 3. `tick_value` is not authoritative here

**For the supported modes, `tick_value` is not consulted at all.**

This is not a preference. On the XAUUSD used by this repository
(MetaQuotes Ltd. / MetaQuotes-Demo) the broker reports:

```
trade_tick_size     0.01
trade_tick_value    0.1      <- implies 10.0 per price unit per lot
trade_contract_size 100.0    <- implies 100.0 per price unit per lot
```

The two disagree by exactly ten. Phase 6E asked the terminal itself: for 1.0 lot
over a $1.00 move, `order_calc_profit` returns **$100.00**, and for a single
0.01 tick on 1.0 lot it returns **$1.00** — not the reported `0.1`. **The
server's `tick_value` is inconsistent with its own profit calculation.**

`tick_value` is still stored on the specification exactly as the broker reported
it, because the specification records what the broker says. It simply governs
nothing for these modes.

## 3.1 No cross-check that rejects the broker file

A validator asserting `tick_value ≈ tick_size × contract_size` would **reject
this broker's own metadata**, which is the environment the repository actually
uses. It is deliberately **not** added. Instrument economics are taken from the
calculation mode, the contract size and the price movement — never from a
consistency assumption between fields.

If a tick-based mode is ever supported, `tick_value` becomes authoritative *for
that mode only*, and validating it belongs in that implementation.

---

# 4. Normalisation, rounding and bounds

## 4.1 Rounding is downward, always

`raw_lots` is the largest size whose loss at the stop equals the budget, so any
rounding up spends more than was authorised. `round_volume_to_step` floors.

**Nearest-rounding is specifically excluded.** `round(0.0399, 2)` is `0.04`,
which on a $30 gold stop is $120 against a $119.70 budget — an overshoot that
appears only on some inputs and is therefore harder to notice than a constant
error.

Pinned by `RiskIsNeverExceeded.test_rounding_is_downward_never_nearest`.

## 4.2 Below the minimum: declined, not raised

If the floored size is under `volume_min`, `lots_for_risk` returns
`tradeable=False`, `lots=0.0` and a reason. **It does not substitute the
minimum.**

Raising to the minimum takes more risk than authorised, quietly, and precisely
when the account is smallest or the stop widest — a $1 budget on a $30 gold stop
would buy 0.01 lots and risk $30, thirty times the instruction.

`risk_manager.calculate_lot_size_for_symbol` surfaces this as `0.0`, and
`main_production.execute_entry_signal` logs and places no order.

## 4.3 Above the maximum: capped

Capped to `volume_max`, floored to the step. The resulting risk is below budget,
so the invariant holds.

## 4.4 The invariant

> **`actual_risk ≤ risk_budget` whenever `tradeable` is true.**

Pinned across five balances × six risk fractions × five stop distances.

---

# 5. The worked example

$10,000 balance · 1 % risk · $30 stop · `contract_size = 100`:

```
risk_budget   = 10_000 × 0.01            = $100.00
money_per_lot = 30 × 100                 = $3,000.00
raw_lots      = 100 / 3_000              = 0.0333333…
lots          = floor to 0.01            = 0.03
actual_risk   = 30 × 100 × 0.03          = $90.00      (≤ $100 budget)
```

**What it replaced:** the previous implementation divided by `10.0` and
nearest-rounded, giving **0.33 lots**. At the established economics that is
**$990 — 9.90 % of the account against an instruction of 1 %.**

---

# 6. Live and backtest consistency

There is **one implementation**, so the paths cannot drift:

| Path | How it sizes |
|---|---|
| Production (`main_production.execute_entry_signal`) | builds the spec from the live terminal via `from_mt5_symbol_info`, then `calculate_lot_size_for_symbol` → `lots_for_risk` |
| Backtest (`ReplayEngine`) | **does not size.** It trades a fixed `volume` by design, so its quantity is an input, not a derivation |
| P&L and R (`backtest/ledger.py`) | `money_per_price_unit` — the same conversion sizing uses |

`tests/integration/test_sizing_consistency.py` pins that the broker-derived
specification and the reference constant price a move identically (both
`100.0`), size identically, and that `risk_manager` returns exactly what
`lots_for_risk` returns.

**Two conflicting formulas were removed.** `execute_entry_signal` previously had
an `if`/`else` whose branches divided by `10.0` and `100.0` for the same symbol
(registered as B6, *"They differ by 10×. One is wrong"*). There is now one
branch.

---

# 7. Quantity through execution

Pinned end to end by `QuantityReachesTheBrokerAndTheLedger`: a sized 0.33 lots
reaches the broker as `volume`, the canonical state as `steps_at_entry = 33`,
and the ledger as `quantity = 0.33` with a realised loss at the stop of
**−$990.00 = −1R**.

## 7.1 Legacy path — deliberately not repaired

`order_execution.execute_order` calls `mt5_handler.send_order(...)` **without
passing a volume**, and `mt5_handler.py` defines no `send_order`. That path is
**legacy and broken**, was recorded in the Phase 6 audit, and is **not touched
here** — repairing an unrelated legacy path inside a sizing commit would mix two
changes. Its status is unchanged: it cannot execute.

---

# 8. What this does not resolve

| # | Item | Status |
|---|---|---|
| S4 | `min(lot, 1.0)` vs `config.INTRADAY_LOT_SIZE_MAX = 0.1` | **Open.** The hard `1.0` cap is gone — bounds now come from the specification — but whether the config ceiling should apply is a policy question, undecided |
| S6 | A `tick_value` cross-check | **Deliberately not added** — §3.1 |
| S7 | Reference constants vs broker-derived spec | **Reconciled for economics**: both now yield `100.0` for XAUUSD. `XAUUSD_2DIGIT` remains "test/documentation use only" |
| — | Margin under CFDLEVERAGE (price-dependent) | **Not investigated.** Unused by the backtest |
| — | `valid_rr` | **Untouched.** Phase 6C Decision B is separate and is not implemented here |
| — | Whether the backtest should ever size | **Open.** It trades a fixed volume by design |

## 8.1 A correction made in passing

`EURUSD_5DIGIT` carried `tick_value = 0.1` against `contract_size = 100_000`,
implying `10,000` per price unit where the contract implies `100,000` — the same
ten-fold inconsistency as the live gold symbol, in a constant used by tests and
documentation. It is corrected to `1.0` (`100,000 × 0.00001 = $1.00`), and its
calculation mode is declared `FOREX`. The test that pinned `10_000.0` now pins
`100_000.0` and records why.
