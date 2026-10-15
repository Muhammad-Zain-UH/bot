# Broker Economics — Evidence and Sizing Reconciliation

**Investigation only. No sizing code, production code, test, specification or
baseline is changed by this document.** The 10× ambiguity is **not resolved
here**, and is deliberately not resolved by choosing whichever formula looks
more intuitive.

**Phase 6D, Workstreams B and C.** Inputs: Phase 6 `ee88f84`, 6A `71269f2`,
6B `0c737a2`, 6C `7b702dd`.

## Labels

**OBSERVED** repository source or artefact · **MEASURED** computed here ·
**DOCUMENTED** official vendor documentation · **INFERRED** reasoning from
stated premises · **UNRESOLVED** deliberately not answered.

---

# 1. Conclusion

| Question | Answer |
|---|---|
| Broker identity | **ESTABLISHED** — §2 |
| Authoritative contract specification for this instrument | **NOT AVAILABLE** — §3 |
| **Classification** | **BROKER ECONOMICS UNVERIFIED** |

**But the investigation did not end there.** Official MetaTrader documentation
establishes **exactly which field governs profit**, and therefore exactly which
single missing datum would resolve the ambiguity:

> **`SYMBOL_TRADE_CALC_MODE`** — never captured by the exporter. **DOCUMENTED:**
> in Forex and CFD calculation modes MT5 computes profit as
> `(close_price − open_price) × Contract_Size × Lots`; **tick value is used only
> in futures modes.** If XAUUSD on this server is a Forex or CFD mode, then
> `contract_size` governs and `tick_value` does not enter profit at all.

This converts the open question from "which number is right?" — unanswerable
from the repository — into "capture one additional field from the same
terminal", which is a defined, bounded task. §7.

**The ambiguity is also asymmetric in consequence** (§6): sizing on the
`tick_value` reading while `contract_size` governs risks **9.90 %** of balance
against an intended 1 % — a 10× over-risk. The reverse error under-risks at
0.09 %. The current `risk_manager` sits on the over-risking side. **This is a
risk observation, not a resolution**, and it is not used as grounds to pick.

---

# 2. Broker Identity — ESTABLISHED

**OBSERVED**, `data/raw/broker_metadata.json`, captured by
`tools/export_mt5_history.py` from a live MT5 terminal:

| Field | Value |
|---|---|
| Broker (`company`) | **MetaQuotes Ltd.** |
| Server | **MetaQuotes-Demo** |
| Account type | **Demo** (inferred from the server name; the account login/type was not exported) |
| Instrument | **XAUUSD** |
| Description | "Gold vs US Dollar" |
| Account currency | USD |
| Base / profit currency | XAU / USD |
| Server UTC offset | +3.0 h, measured at export |
| Export timestamp | **2026-09-16T12:32:25.695231Z** |

**INFERRED:** `MetaQuotes-Demo` is the demonstration server operated by the
platform vendor and shipped with the MetaTrader 5 terminal, not a retail
broker's production server. This matters for §3.

**The broker is not invented and not substituted.** It is named in the
repository's own export.

---

# 3. Why No Authoritative Contract Specification Exists

Working the priority order the brief sets out:

| Priority | Source | Outcome |
|---|---|---|
| 1 | The broker's official XAUUSD contract specification | **Not available.** MetaQuotes publishes no contract-specification document for `MetaQuotes-Demo`. It is a test server bundled with the terminal, not a commercial product with published trading conditions. |
| 2 | Broker/platform symbol specification for this exact account/instrument | **This is the export in §4 — and it is self-contradictory.** For a demo server the terminal's `symbol_info` *is* the specification; there is no second authority to appeal to. |
| 3 | Official MetaTrader documentation on the relevant symbol properties | **Available and used** — §5. It defines what the fields mean and which governs profit, but **cannot supply this server's values.** |
| 4 | Other sources | **Consulted and explicitly rejected as authority** — §5.4. |

**Classification: BROKER ECONOMICS UNVERIFIED.** Identity is established;
authoritative economics are not.

---

# 4. The Contradiction, Restated Exactly

**OBSERVED** — every field the exporter captured
(`tools/export_mt5_history.py:202-214`):

```
symbol XAUUSD    description "Gold vs US Dollar"    digits 2    point 0.01
trade_tick_size      0.01
trade_tick_value     0.1
trade_contract_size  100.0
volume_min 0.01   volume_step 0.01   volume_max 100.0
currency_base XAU   currency_profit USD   account_currency USD
current_spread_points 39
```

**MEASURED:**

```
tick_size × contract_size = 0.01 × 100.0 = 1.0      <- tick_value implied by the contract
trade_tick_value reported                = 0.1      <- disagrees, ratio exactly 10

money per $1.00 move, 1.0 lot:
  from tick_value    (0.1 / 0.01)  =  10.0
  from contract_size               = 100.0
```

**The two fields cannot both be right for a 1.0-lot basis.**

## 4.1 Fields MT5 exposes that were **not** captured — OBSERVED

The exporter records `info.trade_tick_value` and stops. MT5 also exposes:

| Property | Why it matters |
|---|---|
| **`SYMBOL_TRADE_CALC_MODE`** | **Determines which formula governs profit** — §5.2. The single most valuable missing field. |
| `SYMBOL_TRADE_TICK_VALUE_PROFIT` | What `trade_tick_value` is defined as — §5.1 |
| `SYMBOL_TRADE_TICK_VALUE_LOSS` | May differ from the profit tick value |
| `SYMBOL_VOLUME_LIMIT`, margin rates | Not needed here |

**INFERRED:** the export was built for bar history and captured a
reasonable-looking subset of `symbol_info`. The omission is not a defect in the
exporter's own terms; it is a gap that only became material once the two
captured fields were found to disagree.

---

# 5. Official MetaTrader Documentation — DOCUMENTED

Retrieved 2026-09-23 from the MQL5 reference,
`https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants`.

## 5.1 The tick-value definitions are circular and unitless

| Property | Documentation text, verbatim |
|---|---|
| `SYMBOL_TRADE_TICK_VALUE` | *"Value of SYMBOL_TRADE_TICK_VALUE_PROFIT"* |
| `SYMBOL_TRADE_TICK_VALUE_PROFIT` | *"Calculated tick price for a profitable position"* |
| `SYMBOL_TRADE_TICK_VALUE_LOSS` | *"Calculated tick price for a losing position"* |
| `SYMBOL_TRADE_TICK_SIZE` | *"Minimal price change"* |
| `SYMBOL_TRADE_CONTRACT_SIZE` | *"Trade contract size"* |
| `SYMBOL_POINT` | *"Symbol point value"* |

**DOCUMENTED, and decisive as a negative result:** the official documentation
**does not state the volume (lot) basis** of `SYMBOL_TRADE_TICK_VALUE`, and
**does not state its currency**. `SYMBOL_TRADE_TICK_VALUE` is defined only by
reference to `SYMBOL_TRADE_TICK_VALUE_PROFIT`, which is itself defined in five
words.

**INFERRED:** the near-universal convention is that tick value is per 1.0 lot in
the account currency, and the repository assumes this
(`core/symbols.money_per_price_unit` divides by `tick_size` and multiplies by
volume). **The vendor's own documentation does not confirm it.** An assumption
that is conventional but undocumented cannot settle a contradiction.

## 5.2 The profit formula — the most important finding

**DOCUMENTED**, `ENUM_SYMBOL_CALC_MODE`:

| Mode | Profit formula |
|---|---|
| `SYMBOL_CALC_MODE_FOREX` | `(close_price - open_price) * Contract_Size * Lots` |
| `SYMBOL_CALC_MODE_CFD` | `(close_price - open_price) * Contract_Size * Lots` |
| Futures modes | use **tick price and tick size** instead |

**Neither the Forex nor the CFD profit formula uses tick value at all.**

**INFERRED, premises above:** if XAUUSD on `MetaQuotes-Demo` is configured in a
Forex or CFD calculation mode, then:

- `contract_size = 100.0` governs profit, so a $1.00 move on 1.0 lot is **$100**;
- `trade_tick_value = 0.1` does not enter the profit calculation, and its
  disagreement with `tick_size × contract_size` would be a reporting artefact of
  that field rather than a statement about trade economics;
- **`core.symbols.money_per_price_unit`, which derives from
  `tick_value / tick_size`, would be using the *futures* convention for a
  non-futures instrument.**

**This is conditional and is not a resolution.** `trade_calc_mode` was not
captured, so the antecedent is unverified. **UNRESOLVED.**

## 5.3 What this does and does not establish

| Establishes | Does not establish |
|---|---|
| Which field MT5 uses for profit **in each mode** | Which mode this instrument uses |
| That `tick_value` is not load-bearing for Forex/CFD profit | That `tick_value = 0.1` is wrong — it may be correct for what it measures |
| That one specific missing field resolves the question | The actual contract terms of `MetaQuotes-Demo` |

## 5.4 Sources consulted and rejected as authority

A web search returned several third-party explanations of XAUUSD contract
specifications, uniformly describing the common convention: 100 troy ounces per
standard lot, giving $1.00 per 0.01 tick per lot — i.e. agreeing with
`contract_size`.

**These are recorded as context and explicitly rejected as authority**, for the
reason the brief gives: a generic XAUUSD specification must not be substituted
for the actual broker's instrument. One of the sources states the point
directly — contract specifications vary by broker, account type and symbol. The
convention agreeing with `contract_size` is **corroborating, not decisive**, and
is **not** used to resolve §1.

---

# 6. Sizing Reconciliation — MEASURED

Read-only. Computed from the broker's own fields; **no production code was
executed or modified.**

**Scenario:** balance $10,000 · risk 1 % · stop distance $30.00
→ `risk_amount = $100.00`

### Model A — `tick_value` interpretation

```
money_per_price_unit = tick_value / tick_size = 0.1 / 0.01 = 10.0  USD per $1.00 move per lot
money risk per 1.0 lot over a $30 stop      = $300.00
lots = risk_amount / (stop × mppu) = 100.00 / (30.00 × 10.0) = 0.333333 -> 0.33
```

### Model B — `contract_size` interpretation

```
money_per_price_unit = contract_size = 100.0  USD per $1.00 move per lot
money risk per 1.0 lot over a $30 stop      = $3,000.00
lots = risk_amount / (stop × mppu) = 100.00 / (30.00 × 100.0) = 0.033333 -> 0.03
```

### Consequence matrix

Rows are the model used **to size**; columns are the model that is **actually
true** of the instrument.

| Sized under ↓ / True economics → | **A true** | **B true** |
|---|---|---|
| **Model A** (0.33 lots) | $99.00 — **0.99 %** ✓ | **$990.00 — 9.90 %** ✗ **10× over** |
| **Model B** (0.03 lots) | $9.00 — 0.09 % ✗ 0.1× under | $90.00 — **0.90 %** ✓ |

**`risk_manager` as written** — `risk_amount / (stop × 10.0)`, then
`max(0.01, round(·, 2))`, then `min(·, 1.0)` — produces **0.33 lots** here,
identical to Model A. Its realised risk is **$99.00 (0.99 %) if A is true** and
**$990.00 (9.90 %) if B is true**.

## 6.1 The asymmetry — an observation, not a resolution

**MEASURED:** the two possible errors are not equally harmful.

- Sizing under **A** when **B** is true: **10× over-risk.** A 1 %-risk
  instruction places 9.90 % of the balance at risk.
- Sizing under **B** when **A** is true: **10× under-risk.** The position is
  smaller than intended; no risk-limit breach occurs.

**INFERRED:** under uncertainty, the two readings carry unequal downside. That
is a fact about the consequences, and it is **deliberately not used as grounds
to choose** — §5.2's conditional reasoning and §5.4's convention both point the
same way, and neither is authority. The purpose of this section is to expose
what the ambiguity costs, which is precisely what makes resolving it worth the
effort in §7.

## 6.2 Independent of the 10× question

These were established in Phase 6B §6.5 and are unaffected by which model wins:

| # | Issue | Status |
|---|---|---|
| S2 | `risk_manager` hardcodes `10.0` rather than deriving from any specification | **Defect** regardless — a magic literal is wrong even if 10.0 is right |
| S3 | Two formulas in one `if`/`else` (`10.0` vs `100.0`) | **Defect**, registered B6, explicitly *"Do not pick before B7"* |
| S4 | `min(lot, 1.0)` ignores `config.INTRADAY_LOT_SIZE_MAX = 0.1` | **Defect** |
| S5 | `max(0.01, …)` inflates a sub-minimum size instead of declining | **Defect** |
| S6 | `SymbolSpecification` never cross-checks `tick_value` vs `tick_size × contract_size` | **Defect** — it accepted the inconsistent spec silently |
| S7 | Tests use `XAUUSD_2DIGIT` (→100.0); the baseline uses the broker spec (→10.0) | **Defect** |

**None is fixed here.**

---

# 7. What Would Resolve It

**Recorded as a bounded task. Not performed — it requires the MT5 terminal and
the same account, which this environment does not have.**

| # | Action | Resolves |
|---|---|---|
| R1 | Capture **`SYMBOL_TRADE_CALC_MODE`** for XAUUSD from the same terminal/account | **Decisive** if Forex/CFD → `contract_size` governs (§5.2) |
| R2 | Capture `SYMBOL_TRADE_TICK_VALUE_PROFIT` and `SYMBOL_TRADE_TICK_VALUE_LOSS` | Confirms what `trade_tick_value` aliases; reveals asymmetry |
| R3 | Compute `OrderCalcProfit()` for a known 1.0-lot move on the live symbol | **Directly authoritative** — the terminal's own answer, no interpretation |
| R4 | Open a 0.01-lot demo position, move it a known distance, read realised P&L | Empirical, end-to-end. **Demo only** — `LIVE_TRADING_ENABLED` stays `False` |

**INFERRED:** R3 is the strongest available evidence short of R4, because it
asks the terminal to apply its own calculation mode rather than asking a human
to interpret two fields. R1 is the cheapest and is a one-line addition to the
existing exporter.

**Until one of these is done, the classification stands: BROKER ECONOMICS
UNVERIFIED.**

---

# 8. Limitations

Stated so nothing here is read as stronger than it is.

1. **The account login and type were not exported.** "Demo" is inferred from the
   server name, not read from an account field.
2. **The export is a single snapshot**, 2026-09-16T12:32:25Z. Symbol properties
   can change; no second export exists to compare against.
3. **The MQL5 documentation describes the platform, not this server.** It
   establishes which field governs profit in each mode; it cannot supply this
   instrument's mode or values.
4. **`SYMBOL_TRADE_CALC_MODE` is unknown**, so §5.2's conclusion is conditional
   throughout and is never asserted unconditionally.
5. **The third-party sources in §5.4 are not authority** and are not used to
   resolve anything.
6. **No live or demo trade was placed**, no MT5 connection was made, and no
   account was modified. `LIVE_TRADING_ENABLED` remains the literal `False`.
7. **Nothing here was validated against a realised fill**, because zero trades
   exist anywhere in the repository.

---

# 9. Sources

| Source | Retrieved | Role |
|---|---|---|
| `data/raw/broker_metadata.json` (exported 2026-09-16T12:32:25Z from MetaQuotes-Demo) | repository | **Primary** — broker identity and the contradictory fields |
| `tools/export_mt5_history.py:202-214` | repository | What was and was not captured |
| MQL5 Reference — ENUM_SYMBOL_INFO_DOUBLE / ENUM_SYMBOL_CALC_MODE, `https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants` | 2026-09-23 | **Vendor documentation** — field definitions and profit formulas |
| `PHASE_2_ISSUES.md` D1, R1, R5, R6 | repository | Prior recording of the same contradiction |
| `docs/PHASE_4B_FIX_DECISION_MATRIX.md` B6, B7 / DD11 | repository | The registered, undecided broker-field-authority question |
| Third-party XAUUSD specification articles | 2026-09-23 | **Context only — explicitly rejected as authority** (§5.4) |
