# Broker Symbol Specification — Authoritative Evidence

**Evidence capture only. No production code, sizing logic, `valid_rr`, strategy
rule, regime/style behaviour, trade-management code, test or baseline was
modified.** No performance baseline was generated. Neither sizing model was
implemented. `LIVE_TRADING_ENABLED` remains the literal `False`.

**Phase 6E.** Inputs: Phase 6D `79d33a9` and the open question **DD11** — which
of two disagreeing broker-reported fields governs XAUUSD economics.

## Labels

**OBSERVED** repository source/artefact · **CAPTURED** read live from the actual
terminal · **DOCUMENTED** official MQL5 reference · **DERIVED** computed from
CAPTURED/DOCUMENTED inputs · **UNRESOLVED** deliberately not answered.

## Read-only guarantee

Every terminal call made was `initialize`, `terminal_info`, `account_info`,
`symbol_info`, `symbol_info_tick`, `order_calc_profit`, `shutdown`.
**No `order_send`, no `order_check`, no `symbol_select`, no account
modification, no order of any kind — live or demo.** `order_calc_profit` is a
pure calculator: it returns a number and performs no trading action. The
terminal independently reported **`trade_allowed: false`**.

---

# 1. Exact Environment Identity — CAPTURED

The connected environment was verified against the repository's own export
**before any value was trusted**. A mismatch would have been reported, not
worked around.

| | Repository export | Live terminal | Match |
|---|---|---|---|
| Broker / company | MetaQuotes Ltd. | **MetaQuotes Ltd.** | ✅ |
| Server | MetaQuotes-Demo | **MetaQuotes-Demo** | ✅ |
| Symbol | XAUUSD | **XAUUSD** | ✅ |

| Field | Value |
|---|---|
| Account login | `5056046608` |
| Account name | Zain Jutt |
| Account `trade_mode` | `0` — **DEMO** |
| Account currency | **USD** |
| Leverage | 100 |
| Balance | 100,000.00 |
| Terminal | MetaTrader 5, **build 5739** |
| Terminal path | `C:\Program Files\MetaTrader 5` |
| Terminal `connected` | `true` |
| Terminal `trade_allowed` | **`false`** |
| Capture timestamp | **2026-09-23T11:02:04.129101Z** |
| Live tick at capture | bid 4373.47 / ask 4373.81, spread 34 points |

**This is the actual environment that produced the repository export.** No
generic specification, other broker, other server, other account or internet
example was substituted.

---

# 2. Captured Symbol Properties — CAPTURED

Full `symbol_info("XAUUSD")`, the fields that bear on economics:

| Property | Value |
|---|---|
| `name` / `description` | XAUUSD / "Gold vs US Dollar" |
| `digits` | 2 |
| `point` | 0.01 |
| **`trade_calc_mode`** | **4** |
| `trade_mode` | 4 |
| `trade_exemode` | 2 |
| **`trade_contract_size`** | **100.0** |
| **`trade_tick_size`** | **0.01** |
| **`trade_tick_value`** | **0.1** |
| **`trade_tick_value_profit`** | **0.1** |
| **`trade_tick_value_loss`** | **0.1** |
| `currency_base` | XAU |
| `currency_profit` | **USD** |
| `currency_margin` | **USD** |
| `volume_min` / `step` / `max` | 0.01 / 0.01 / 100.0 |
| `margin_initial` / `margin_maintenance` | 0.0 / 0.0 |
| `swap_mode` | 1 |

## 2.1 Properties governing tick-value behaviour

The brief asks specifically whether tick value is fixed, profit/loss asymmetric,
or price/conversion dependent. **CAPTURED:**

| Question | Answer |
|---|---|
| Profit/loss asymmetric? | **No.** `tick_value_profit == tick_value_loss == 0.1` |
| Currency conversion required? | **No.** `currency_profit = currency_margin = USD =` account currency |
| Price-dependent? | Profit is not (§5). **Margin is** — the CFDLEVERAGE margin formula contains `MarketPrice` |

## 2.2 The export was faithful — and the contradiction persists live

**CAPTURED:** `trade_contract_size 100.0`, `trade_tick_size 0.01`,
`trade_tick_value 0.1` are **identical** to the 2026-09-16 export. The
repository's capture was accurate; the contradiction is a property of the
server's data, not an export error.

---

# 3. Calculation Mode — CAPTURED

```
trade_calc_mode = 4  =  SYMBOL_CALC_MODE_CFDLEVERAGE
```

The name was resolved from the `MetaTrader5` package's own constants, not
guessed:

| Value | Constant | |
|---|---|---|
| 0 | `SYMBOL_CALC_MODE_FOREX` | |
| 1 | `SYMBOL_CALC_MODE_FUTURES` | |
| 2 | `SYMBOL_CALC_MODE_CFD` | |
| 3 | `SYMBOL_CALC_MODE_CFDINDEX` | |
| **4** | **`SYMBOL_CALC_MODE_CFDLEVERAGE`** | **← this symbol** |
| 5 | `SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE` | |
| 32–64 | exchange modes | |

**This is the datum Phase 6D identified as missing and decisive.**

---

# 4. Official Definition — DOCUMENTED

MQL5 Reference, `ENUM_SYMBOL_CALC_MODE`, retrieved 2026-09-23:

> **`SYMBOL_CALC_MODE_CFDLEVERAGE`** — *"CFD Leverage mode - calculation of
> margin and profit for CFD at leverage trading"*
>
> **Profit:** `(close_price - open_price) * Contract_Size * Lots`
> **Margin:** `(Lots * ContractSize * MarketPrice) / Leverage * Margin_Rate`

For comparison, both neighbouring CFD modes carry the **identical** profit
formula:

| Mode | Profit formula |
|---|---|
| `SYMBOL_CALC_MODE_CFD` | `(close_price - open_price) * Contract_Size * Lots` |
| `SYMBOL_CALC_MODE_CFDINDEX` | `(close_price - open_price) * Contract_Size * Lots` |
| **`SYMBOL_CALC_MODE_CFDLEVERAGE`** | `(close_price - open_price) * Contract_Size * Lots` |

**The CFDLEVERAGE profit formula uses contract size. Tick value does not appear
in it.** The three modes differ only in margin treatment.

---

# 5. Applicable Profit Formula, Every Variable Mapped — DERIVED

```
Profit = (close_price - open_price) × Contract_Size × Lots
```

| Formula variable | Captured property | Value |
|---|---|---|
| `close_price`, `open_price` | quoted price, `digits=2`, `point=0.01` | e.g. 4301.00, 4300.00 |
| **`Contract_Size`** | **`trade_contract_size`** | **100.0** (troy ounces per 1.0 lot) |
| `Lots` | volume, `volume_step = 0.01` | e.g. 1.00 |
| result currency | `currency_profit` | **USD** = account currency, no conversion |

**DERIVED:** money per 1.00 price unit per 1.0 lot
= `1.00 × 100.0 × 1.0` = **$100.00**.

**`trade_tick_size` and `trade_tick_value` do not appear in this formula.**
For this calculation mode they are not load-bearing for profit.

## 5.1 The terminal's own answer — CAPTURED

`order_calc_profit` asks the terminal to apply its own calculation mode. Six
cases, all against the captured specification:

| Side | Lots | Move | **Terminal** | Predicted by `contract_size` | Predicted by `tick_value` | Verdict |
|---|---|---|---|---|---|---|
| BUY | 1.00 | +$1.00 | **100.00** | 100.00 | 10.00 | **contract_size** |
| BUY | 1.00 | +$0.01 (one tick) | **1.00** | 1.00 | 0.10 | **contract_size** |
| BUY | 0.01 | +$1.00 | **1.00** | 1.00 | 0.10 | **contract_size** |
| BUY | 1.00 | −$1.00 | **−100.00** | −100.00 | −10.00 | **contract_size** |
| SELL | 1.00 | −$1.00 | **100.00** | 100.00 | 10.00 | **contract_size** |
| BUY | 1.00 | +$30.00 | **3000.00** | 3000.00 | 300.00 | **contract_size** |

**All six match `contract_size` exactly. None matches `tick_value`.** Sign
handling is correct for both directions.

## 5.2 Is `tick_value` still relevant, and how?

**CAPTURED, and this is the sharpest single result:** case 2 asks the terminal
what **one tick** (0.01) is worth on 1.0 lot. Its answer is **$1.00**. The
symbol reports `trade_tick_value = 0.1`.

> **DERIVED: the terminal's own true tick value for XAUUSD on this server is
> `$1.00` per 1.0 lot, which equals `tick_size × contract_size = 0.01 × 100.0`.
> The reported `trade_tick_value = 0.1` is inconsistent with the terminal's own
> profit computation by exactly 10×.**

So `tick_value` is not merely "not used" here — **as reported for this symbol on
this server it is wrong**, and it disagrees with the platform that reports it.
`tick_value_profit` and `tick_value_loss` carry the same wrong value, so the
error is uniform rather than an asymmetry artefact.

**Where `tick_value` would still matter:** in the futures calculation modes
(`SYMBOL_CALC_MODE_FUTURES`, `EXCH_FUTURES`), whose profit formulas are
tick-based. **This symbol is not in one of those modes**, so for XAUUSD on
MetaQuotes-Demo the field has no economic role.

---

# 6. Mapping to the Repository's Formulas — DERIVED

| Repository site | Formula | Value per lot | Against the captured mode |
|---|---|---|---|
| `risk_manager.calculate_lot_size_for_symbol` | `risk / (stop × **10.0**)` | 10.0 | **WRONG** — 10× too small a denominator ⇒ 10× oversized positions |
| `core.symbols.money_per_price_unit` | `(tick_value / tick_size) × volume` | **10.0** with the broker spec | **WRONG for this instrument** — applies the *futures* convention to a CFDLEVERAGE symbol, and reads a field the server reports incorrectly |
| `core.symbols.XAUUSD_2DIGIT` (hardcoded `tick_value = 1.0`) | same formula | **100.0** | **Numerically correct** — but by a hardcoded constant that happens to restore `tick_size × contract_size`, not by reading `contract_size` |
| `main_production.execute_entry_signal` fallback | `risk / (stop × **100.0**)` | 100.0 | **Numerically correct** |
| `backtest/ledger.py` P&L and R | via `money_per_price_unit` | **10.0** | **WRONG** — would understate every currency figure by 10× |

**DERIVED — the structural defect:** `money_per_price_unit` derives money from
`tick_value / tick_size`. Its docstring justifies this as staying *"correct for
brokers whose tick size differs from their point size."* That reasoning is sound
for futures-style instruments. **For a CFD-family mode the platform's own
formula is `Contract_Size`-based, so the derivation is using the wrong
convention for this instrument class** — and it is additionally reading a field
this server reports incorrectly. Two independent problems, one of which
(the convention) would persist even on a server whose `tick_value` were right.

**No code was changed.**

---

# 7. Resolution of the 10× Ambiguity

> ## DD11 is **RESOLVED**.
> **`contract_size` governs XAUUSD profit on MetaQuotes-Demo.**
> **Money per 1.00 price unit per 1.0 lot = `$100.00`.**

| Model | Interpretation | Verdict |
|---|---|---|
| **Model A** — `risk_manager`, `tick_value / tick_size` = 10.0 | **NOT SUPPORTED.** Contradicted by the calculation mode, by the official formula, and by the terminal's own calculator in six of six cases |
| **Model B** — `contract_size` = 100.0 | **SUPPORTED.** Matches the official CFDLEVERAGE profit formula and the terminal exactly |
| A third formulation? | **Not required.** `Profit = (close − open) × Contract_Size × Lots` is complete for profit, needs no conversion (§8), and no additional term |

**Evidence chain, three independent strands agreeing:**

1. **CAPTURED** `trade_calc_mode = 4 = SYMBOL_CALC_MODE_CFDLEVERAGE`.
2. **DOCUMENTED** CFDLEVERAGE profit = `(close − open) × Contract_Size × Lots` —
   the vendor's own specification of that mode.
3. **CAPTURED** `order_calc_profit` — the terminal applying its own mode —
   matches `contract_size` in all six synthetic cases **and** on a real
   historical bar at three lot sizes (§7.1).

No strand relies on a generic XAUUSD convention, and none was used.

## 7.1 Independent sanity check on real historical data — CAPTURED

The largest single-bar move in the frozen dataset (SHA-256
`433b7e27…`), priced by both models and by the terminal:

```
bar 2026-09-04 12:30:00+00:00   open 4467.61   close 4394.64   move  -$72.97
```

| Lots | **Terminal** | By `contract_size` | By `tick_value` | Verdict |
|---|---|---|---|---|
| 0.01 | **−72.97** | −72.97 | −7.297 | **contract_size** |
| 0.10 | **−729.70** | −729.70 | −72.97 | **contract_size** |
| 1.00 | **−7,297.00** | −7,297.00 | −729.70 | **contract_size** |

The theoretical calculation and the platform's own reported economics agree
exactly at every lot size, on real data from the baseline dataset.

**Consequence for the frozen baselines — no figure is affected.**
`baseline_004` and `baseline_005` both recorded
`money_per_price_unit_per_lot: 10.0` and both contain **zero trades**, so the
wrong value multiplied nothing. Neither baseline requires regeneration, and
neither was touched.

---

# 8. Currency and Conversion Uncertainty

**Resolved for this instrument and account — CAPTURED:**

| | |
|---|---|
| `currency_profit` | USD |
| `currency_margin` | USD |
| Account currency | USD |
| Conversion needed | **None.** Profit is computed directly in the account currency |
| Profit/loss asymmetry | **None.** `tick_value_profit == tick_value_loss` |
| Price dependence of profit | **None.** The profit formula is linear in the price difference |

**UNRESOLVED, and outside profit:** the **margin** formula for CFDLEVERAGE is
`(Lots × ContractSize × MarketPrice) / Leverage × Margin_Rate` — **price
dependent**, with `margin_initial = margin_maintenance = 0.0` captured and
`leverage = 100`. Margin has not been investigated, is not used anywhere in the
backtest, and is **not** resolved here.

**Scope limit:** this resolution is for **XAUUSD on MetaQuotes-Demo with a USD
account**. It does not generalise to another symbol, server, account currency or
calculation mode, and must not be applied to one without re-capture.

---

# 9. Can Sizing Now Be Specified Unambiguously?

**The economics can. The production sizing path cannot yet be called fixed, and
nothing here fixes it.**

| | Status |
|---|---|
| **The economic question (DD11)** | **RESOLVED** — §7 |
| The lot-size formula, economically | **Unambiguous**: `lots = risk_amount / (stop_distance × contract_size)` |
| **Production sizing** | **NOT FIXED.** No code changed. Six defects survive DD11's resolution |

**Defects that remain, independent of DD11** (Phase 6B §6.5, unchanged):

| # | Issue | Status after 6E |
|---|---|---|
| S2 | `risk_manager` hardcodes `10.0` | **Now known wrong**, still present |
| S3 | Two formulas in one `if`/`else` (B6, *"Do not pick before B7"*) | **B7/DD11 is now answered**, so B6 is unblocked — but undecided and unimplemented |
| S4 | `min(lot, 1.0)` ignores `config.INTRADAY_LOT_SIZE_MAX = 0.1` | Open |
| S5 | `max(0.01, …)` inflates a sub-minimum size instead of declining | Open |
| S6 | `SymbolSpecification` never cross-checks `tick_value` vs `tick_size × contract_size` | Open — **and it would have caught this server's bad field** |
| S7 | Tests use `XAUUSD_2DIGIT` (→100.0); the baseline uses the broker spec (→10.0) | Open — the two now provably disagree, and the **test constant is the correct one** |

**DERIVED — the realised consequence, stated plainly:** at $10,000 balance, 1 %
risk and a $30 stop, `risk_manager` returns **0.33 lots**. Priced by the now-
established economics that is **$990 at risk — 9.90 % of balance against an
intended 1 %.** Phase 6D flagged this as the over-risking branch of an
asymmetric ambiguity; it is no longer ambiguous.

**This is a statement about the current code's behaviour, not a change to it.**

---

# 10. What Remains Unresolved

| # | Item | Status |
|---|---|---|
| U1 | **How to correct the sizing path** — repair `risk_manager`, replace it with a `contract_size`-based helper, or delete it | **UNRESOLVED** — a design decision, now unblocked |
| U2 | Whether `money_per_price_unit` should switch to a **calc-mode-aware** derivation, or `contract_size` unconditionally | **UNRESOLVED** — affects `backtest/ledger.py` P&L and R |
| U3 | Whether to add the `tick_value ≈ tick_size × contract_size` cross-check (S6), given this server would **fail** it | **UNRESOLVED** — a validator that rejects the live broker file needs a policy |
| U4 | Reconciling `XAUUSD_2DIGIT` with the broker-derived spec (S7) | **UNRESOLVED** |
| U5 | `min(lot, 1.0)` vs `INTRADAY_LOT_SIZE_MAX = 0.1` (S4), and S5 | **UNRESOLVED** |
| U6 | **Margin** semantics under CFDLEVERAGE | **UNRESOLVED**, not investigated |
| U7 | Whether MetaQuotes-Demo's `tick_value` should be reported upstream as a data fault | **UNRESOLVED** — out of scope |
| U8 | Everything in Phase 6C §6 not touched here — DD2, DD5, the minimum-RR value, regime/style ratification, U1 stop buffer | **UNRESOLVED** |

**Phase 7 gate:** DD11's resolution clears the *evidential* blocker on
prerequisites **P5** and **P13**, but neither is *met*, because the sizing code
is unchanged and the defects above are live. **P7 (a trade-level baseline) and
P12 remain unmet and are untouched by this phase.**

---

# 11. Sources

| Source | Retrieved | Role |
|---|---|---|
| Live MT5 terminal, build 5739, account `5056046608` @ MetaQuotes-Demo | 2026-09-23T11:02:04Z | **Primary — CAPTURED.** Symbol specification, calculation mode, `order_calc_profit` |
| MQL5 Reference, `ENUM_SYMBOL_CALC_MODE`, `https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants` | 2026-09-23 | **DOCUMENTED.** CFDLEVERAGE definition and profit/margin formulas |
| `data/raw/XAUUSD_M5.csv` (dataset SHA-256 `433b7e27…`) | repository | Real historical bar for §7.1 |
| `data/raw/broker_metadata.json` | repository | The 2026-09-16 export, verified faithful |
| `docs/BROKER_ECONOMICS_RECONCILIATION.md` | repository | The question this phase answers |

**No generic XAUUSD specification, third-party article, other broker, other
server or other account was used as evidence.** Phase 6D recorded third-party
sources as context and rejected them as authority; this phase did not need them,
and the authoritative result agrees with what they described — which is
corroboration after the fact, not part of the evidence chain.
