# Phase 6B — Strategy-Contract Decision Evidence

**Investigation only.** No production code, test, strategy parameter,
specification, fixture or baseline was modified. `baselines/baseline_004` was
read and not regenerated. Nothing was removed, loosened, replaced or bypassed.

**Starting state:** Phase 6 audit `ee88f84`; Phase 6A investigation `71269f2`.

## Labels

**OBSERVED** — read directly from repository source.
**MEASURED** — produced by running code, or read from a frozen artefact.
**DOCUMENTED** — stated in a repository document as intent, not merely described.
**INFERRED** — reasoning from OBSERVED/MEASURED premises; the premises are given.
**UNKNOWN** — not established.
**UNRESOLVED** — a registered open question; deliberately not answered.

---

# 1. Executive Summary

**The two contract questions were already registered as open decisions before
this investigation began.** Phase 6B's main result is that neither is new, both
are formally recorded, and one of them is recorded *with the same measurement I
reported in Phase 6A as a discovery*.

**Two corrections to my own prior reports are required.**

### Correction 1 — Phase 6A overstated the novelty of the `valid_rr` finding

Phase 6A stated the 4 MICRO_SCALP momentum rejections were *"the first time in
this repository's recorded history that `valid_rr` has bound anything."*

**That is wrong.** `docs/PHASE_4B_FIX_DECISION_MATRIX.md` §6, committed
2026-09-18 — five days before Phase 6A — already records, labelled
**[MEASURED]**:

> "The four real XAUUSD LIMIT_FVG candidates — all MICRO_SCALP — were rejected
> by this gate. **It is the current binding constraint.**"

Phase 6A re-measured a known fact and presented it as new. The *measurement*
was correct and reproduced independently; the *claim of novelty* was not.

### Correction 2 — Phase 6 classified the sizing 10× too confidently, and Phase 6A's "amendment" was also a rediscovery

Phase 6 called it "**A** — a genuine defect". Phase 6A amended that to "defect
compounded by a data/provenance issue". **Both were rediscoveries.** The
repository already carries:

- **`PHASE_2_ISSUES.md` D1** (P0): *"Broker tick value contradicts contract
  size… a factor of 10. The baseline uses the broker's own tick value rather
  than silently substituting the contract size."*
- **`PHASE_2_ISSUES.md` R1** (P0): `risk_manager` divides by 10.0 where contract
  size implies 100.
- **`PHASE_4B_FIX_DECISION_MATRIX.md` B7 / DD11**: *"Broker field authority —
  `contract_size` vs `tick_value`, a 10× difference, **both from the broker**"*,
  classified **DECISION**, unresolved.

The correct status is **CONTRACT AMBIGUITY — a registered open decision
(DD11)**, not a defect awaiting a fix. §6.

### The substantive new findings

**N1 — The 11 pullback candidates are double-blocked. MEASURED.**
Every one is MICRO_SCALP with `tp_ratio = 1.5`, so
`pullback_entry_triggered = raw_triggered AND valid_rr = True AND False =
False`. **Lifting the style restriction alone would produce zero additional
signals**, because `valid_rr` would reject all 11 anyway. The style restriction
is **not independently causal** for signals on this dataset. Phase 6A did not
state this.

**N2 — Full geometry for all 15 `raw=True` candidates, with timestamps.** §3, §5.
Every one has `reward / risk = 1.5` to floating-point precision — the tautology
confirmed numerically on the exact candidates it rejects.

**N3 — The style restriction's documentary support is asymmetric. OBSERVED.**
MICRO_SCALP→MOMENTUM has *indirect* support; INTRADAY_SWING→PULLBACK has
**none anywhere in the repository**. §2.

### Classifications

| Issue | Class | Basis |
|---|---|---|
| Regime/style restriction | **C — implementation behavior with no documented intent**, with a partial-D rider | §2, §7 |
| `valid_rr` / `tp_ratio` | **C — redundant, intent undocumented**, under a deliberate fixed-R design | §4, §7 |
| Sizing 10× | **CONTRACT AMBIGUITY** (registered DD11) | §6, §7 |

**Phase 7 cannot begin.** Six prerequisites are unmet, two of which are
unmeetable in principle today. §8.

---

# 2. Regime/Style Restriction Evidence

## 2.1 The predicate — OBSERVED

`entry_engine.py:687-694`, inside `get_entry_trigger`:

```python
allowed_styles = ["PULLBACK", "MOMENTUM"]
if regime:
    reg_name = regime.get("regime", "DEFAULT")
    if reg_name == "MICRO_SCALP":
        allowed_styles = ["MOMENTUM"]
    elif reg_name == "INTRADAY_SWING":
        allowed_styles = ["PULLBACK"]
```

Then `entry_engine.py:707-711`:

```python
candidates = []
if "PULLBACK" in allowed_styles:  candidates.append(pullback_entry)
if "MOMENTUM" in allowed_styles:  candidates.append(momentum_entry)
```

**Both candidates are always fully evaluated** (`:696`, `:701`). The restriction
governs only which may be *selected*. A candidate that satisfies its entire
conjunction is silently dropped if its style is not permitted.

## 2.2 Source of the permitted styles — OBSERVED

**A hardcoded `if`/`elif` on the regime *name*.** Not from `config.py`, not from
the regime dict, not from any data file. `detect_regime` returns
`risk_percent`, `tp_ratio`, `bypass_l3`, `bypass_l6`, `poi_threshold`,
`max_spread_pips` — **no style field**. The restriction is not part of the
regime's published configuration.

## 2.3 Callers — OBSERVED

`get_entry_trigger` is called from `main_production.py:~487` (the L8 gate) and
from `main.py`. Nothing else consumes `allowed_styles`; it is local.

## 2.4 Documentation — OBSERVED, and asymmetric

| Claim | Evidence | Strength |
|---|---|---|
| MICRO_SCALP ↔ momentum | `SYSTEM_STRUCTURE_DIAGRAM.md:234`: *"If `regime_info["bypass_l3"] == True` → SKIP gate (**MICRO_SCALP momentum entries don't need pullback**)"* | **Indirect.** It justifies the **L3 bypass**, not the L8 style restriction. It says MICRO_SCALP momentum entries need no pullback *detection*; it does not say pullback *entries* are forbidden. |
| MICRO_SCALP regime config | `SYSTEM_STRUCTURE_DIAGRAM.md:444-455` lists six config fields | **Negative evidence.** No style field is documented. |
| INTRADAY_SWING ↔ pullback | Searched `*.md` and `docs/*.md` | **None.** Every occurrence is an audit *describing the implementation* (`PHASE_4A_RAW_TRIGGER_PROBE.md:41`, `PHASE_4B_STRATEGY_AUDIT.md:300`, Phase 6A). No design document states it. |

## 2.5 Tests — MEASURED

```
grep -rn "allowed_styles" tests/   →  no matches
```

**No test pins the restriction.** Nothing in the suite would fail if it were
changed. (Contrast `valid_rr`, which *is* pinned — §4.4.)

## 2.6 Commit history — OBSERVED

`git log -L 687,695:entry_engine.py` yields two commits:

| Commit | Date | Message |
|---|---|---|
| `c3cf4df` | 2026-07-01 | `update` |
| `4c90b81` | 2026-09-16 | `chore: baseline before phase 0/1 foundations` |

The block originates in `c3cf4df`, whose message is `update` — one of a series
(`update`, `updaet`, `update`, `hi first`) predating the disciplined phase work.
**No commit message, code comment or docstring gives a reason.**

## 2.7 Prior classification — DOCUMENTED

`docs/PHASE_4B_STRATEGY_AUDIT.md` (`d6464b0`, 2026-09-18) already reached this:

- **#44** — `allowed_styles` from regime: class **AMBIGUOUS**. *"Unresolved: why
  MICRO_SCALP may only take MOMENTUM and INTRADAY_SWING only PULLBACK."*
- **#12** — a recorded **contradiction**: L3 determines whether the setup is a
  pullback or a momentum continuation and writes it to a field *"read **only**
  by display functions"*. *"L8 ignores it entirely: `get_entry_trigger` derives
  `allowed_styles` from the regime name, not from L3's finding."*
- **#46** — `_score_entry_candidate` is **DEAD in 2 of 4 regimes**, because a
  single permitted style leaves nothing to score.

## 2.8 Classification

**C — implementation behavior with no documented intent.**

Grounds: a hardcoded name comparison, absent from the documented regime config,
pinned by no test, originating in a commit called `update` with no recorded
reason, and already classified AMBIGUOUS by a prior audit.

**Rider — a partial D (contradictory evidence), confined to MICRO_SCALP.**
`SYSTEM_STRUCTURE_DIAGRAM.md:234` associates MICRO_SCALP with momentum entries,
which is *some* evidence of intent for that half. Set against it: finding #12's
direct contradiction with L3, and the complete absence of any statement for
INTRADAY_SWING. **The evidence is not strong enough for B (implicitly specified
by tests/configuration)** — there is no test and no configuration field.

**UNRESOLVED and not answered here:** why MICRO_SCALP may take only MOMENTUM,
and why INTRADAY_SWING may take only PULLBACK.

---

# 3. The 11 Pullback Candidates

**MEASURED.** Instrumented read-only replay of current code over the verified
dataset; `entry_engine.get_entry_trigger` wrapped, result returned unmodified.
Timestamps recovered by index-join against the frozen L8 decision stream
(1,265 rows, 1:1 with the 1,265 trigger invocations).

**Join validated:** all 11 timestamps reproduce
`docs/PHASE_4A_RAW_TRIGGER_PROBE.md` §7 exactly, which was produced by an
independent method at a different commit.

| # | Timestamp (UTC) | Side | Regime | Style | raw | entry | stop | TP | risk | reward | RR | `tp_ratio` | `valid_rr` | Rejection |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-30 10:15 | BUY | MICRO_SCALP | PULLBACK | **True** | 4024.31 | 4018.51 | 4033.01 | 5.800 | 8.700 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 2 | 2026-07-08 04:55 | SELL | MICRO_SCALP | PULLBACK | **True** | 4126.03 | 4131.84 | 4117.31 | 5.810 | 8.715 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 3 | 2026-07-08 05:50 | SELL | MICRO_SCALP | PULLBACK | **True** | 4126.90 | 4136.98 | 4111.78 | 10.080 | 15.120 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 4 | 2026-07-23 05:30 | BUY | MICRO_SCALP | PULLBACK | **True** | 4123.18 | 4116.76 | 4132.81 | 6.420 | 9.630 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 5 | 2026-07-23 12:15 | SELL | MICRO_SCALP | PULLBACK | **True** | 4082.07 | 4096.81 | 4059.96 | 14.740 | 22.110 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 6 | 2026-08-11 00:45 | BUY | MICRO_SCALP | PULLBACK | **True** | 4410.85 | 4393.10 | 4437.48 | 17.750 | 26.625 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 7 | 2026-08-12 04:05 | BUY | MICRO_SCALP | PULLBACK | **True** | 4402.19 | 4391.12 | 4418.79 | 11.070 | 16.605 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 8 | 2026-08-12 04:45 | BUY | MICRO_SCALP | PULLBACK | **True** | 4399.15 | 4392.43 | 4409.23 | 6.720 | 10.080 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 9 | 2026-09-01 04:00 | SELL | MICRO_SCALP | PULLBACK | **True** | 4437.95 | 4446.23 | 4425.53 | 8.280 | 12.420 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 10 | 2026-09-08 05:05 | SELL | MICRO_SCALP | PULLBACK | **True** | 4435.69 | 4442.82 | 4424.99 | 7.130 | 10.695 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |
| 11 | 2026-09-15 06:00 | SELL | MICRO_SCALP | PULLBACK | **True** | 4291.26 | 4302.77 | 4273.99 | 11.510 | 17.265 | 1.5 | 1.5 | **False** | style ∧ `valid_rr` |

**Every one is MICRO_SCALP.** No INTRADAY_SWING candidate was ever discarded by
the restriction on this dataset, so the INTRADAY_SWING→PULLBACK half is
**untested by data** as well as undocumented.

## 3.1 Do they satisfy the remaining entry conditions? — MEASURED

**No.** This is the finding Phase 6A did not state.

```
pullback_entry_triggered = raw_triggered AND valid_rr
                         = True          AND False     = False
```

**MEASURED:** `pullback_entry_triggered = False` for all 11.

Because all 11 are MICRO_SCALP (`tp_ratio = 1.5 < 2.0`), they fail `valid_rr`
independently of the style restriction. They are blocked **twice, by
independent mechanisms**:

| Mechanism | Blocks | Would removing it alone admit them? |
|---|---|---|
| Style restriction (`allowed_styles = ["MOMENTUM"]`) | all 11 | **No** — `valid_rr` still rejects them |
| `valid_rr` (`1.5 >= 2.0` is false) | all 11 | **No** — style restriction still drops them |

**INFERRED, from those two MEASURED facts:** on this dataset the style
restriction has **no independent causal effect on signal count**. Both
mechanisms would have to change for any of the 11 to become a signal. This is
stated as a consequence of the measurements, **not** as an argument for changing
either.

Upstream: all 11 passed L1–L7 by construction (they reached L8). Beyond
`valid_rr`, no further L8 gate exists.

---

# 4. `valid_rr` / `tp_ratio` Evidence

## 4.1 Origin of `tp_ratio` — OBSERVED

`entry_engine.detect_regime` (`:76-112`), hardcoded per branch:

| Regime | `tp_ratio` | ATR band | `risk_percent` |
|---|---|---|---|
| MICRO_SCALP | **1.5** | M5 ATR 2.5–4.5 + kill zone/session | 0.75 |
| REGIME_SCALP | **2.0** | M5 ATR 4.5–7.0 | 1.0 |
| INTRADAY_SWING | **3.0** | M5 ATR > 7.0 | 1.5 |
| DEAD_CALM | **1.5** | otherwise | 0.75 |

Plus `2.0` on an exception path (`:143`) and a `3.0` default parameter
(`:383`, `:461`, `:685`). Mirrored in `backtest.baseline.REGIME_TP_RATIO`, which
`tests/backtest/test_baseline_defects.py` verifies against `entry_engine`'s AST
so the mirror cannot drift.

## 4.2 Origin of the threshold — OBSERVED

`entry_engine.py:409`: `valid_rr = rr >= 2.0` — **a bare literal.** Not in
`config.py`; no named constant. `backtest.baseline.VALID_RR_THRESHOLD = 2.0` is
a *mirror for reporting*, recovered from the AST by test, not the source.

## 4.3 Why the threshold exists — UNKNOWN

`docs/PHASE_4B_TARGET_SEMANTICS.md` §9, "Missing evidence":

> **"2. No rationale for `2.0`.** Nothing explains the threshold, and under
> fixed-R it cannot be satisfied at all in two of four regimes.
> **3. No rationale for the per-regime ratios** 1.5 / 2.0 / 3.0."

**No document, comment, docstring or commit message explains either.**

## 4.4 Tests — MEASURED

`tests/backtest/test_baseline_defects.py` pins the behaviour **as a defect**,
proving it against the production function rather than asserting it in prose:

| Test | Asserts |
|---|---|
| `test_mirror_matches_entry_engine_source` | mirror equals AST-recovered literals |
| `test_valid_rr_threshold_matches_entry_engine_source` | recovers `2.0` from source |
| `test_reported_rr_equals_tp_ratio_for_every_regime` | `rr == tp_ratio`, 9 places |
| `test_valid_rr_is_unreachable_below_the_threshold` | `valid_rr == (tp_ratio >= 2.0)` |
| `test_holds_for_sell_as_well` | same for SELL |
| `test_entry_triggered_is_conjoined_with_valid_rr` | both paths AND the trigger with `valid_rr` |

Its docstring: *"Two things are checked here, and **neither of them changes the
strategy**… The baseline claims that `valid_rr` tests a config constant rather
than the trade. That claim is proved directly against the production function."*

**The tests pin it as a documented defect (E9/E10), not as intended behaviour.**

## 4.5 Consumers — OBSERVED

| Site | Use | Affects entry? |
|---|---|---|
| `entry_engine.py:535` | `entry_triggered = raw_triggered AND valid_rr` (pullback) | **Yes** |
| `entry_engine.py:638` | `entry_triggered = core_trigger AND valid_rr` (momentum) | **Yes** |
| `entry_engine.py:445` | `valid_bonus = 2.0 if candidate.get("valid_rr")` in scoring | Only where both styles are allowed (#46) |
| `entry_engine.py:418, 430, 544, 649, 750` | carried in returned dicts | No |
| `main_production.py:1008, 1025, 1038` | `rr_valid` reporting | No |

## 4.6 Does any caller compute an independent reward/risk? — OBSERVED

**No caller computes an independent quantity that reaches a gate.**

`order_execution.create_order:96` recomputes `rr_ratio = reward_distance /
risk_distance` from the passed prices — but those prices were themselves built
as `entry ± risk × tp_ratio`, so it recovers `tp_ratio` again, and the value is
stored in the order dict and **never gated on**. `backtest/ledger.py` computes
realised R from actual fills, but that is an *outcome measure* after the fact,
not an admission input.

**MEASURED — the tautology holds in the live data.** Observed `rr` across all
1,265 L8 decisions, by regime:

| Regime | `tp_ratio` | Observed `rr` | Max deviation |
|---|---|---|---|
| MICRO_SCALP | 1.5 | 1.5 ± float noise | ~3.6e-13 |
| DEAD_CALM | 1.5 | 1.5 ± float noise | ~8.0e-14 |
| REGIME_SCALP | 2.0 | 2.0 (216), 2.0000000000000231 (1) | ~2.3e-14 |
| INTRADAY_SWING | 3.0 | 3.0 (52), two at 2.99999999999998 | ~1.9e-14 |

## 4.7 Independent feasibility gate, or a re-check of the configured multiple?

**A re-check of the configured multiple. OBSERVED + MEASURED.** `rr` is
constructed from `tp_ratio` and compared to a constant; no market quantity
enters. The boolean is fixed per regime before any price is read.

`docs/PHASE_4B_TARGET_SEMANTICS.md` §8 classifies the fixed-R target model
itself as **"C — deliberate fixed-R design"**, documented in two design
documents and producing the identity `exit_1_3 == take_profit`. Its Rider 2:

> *"E9/E10 remains a defect under **either** model… Under fixed-R, `rr` is a
> **chosen input**. Testing a chosen input against `2.0` is not a weak check — it
> is a **category error**: the gate asks whether the value you selected is the
> value you selected."*

**INFERRED, premises above:** the *target model* is deliberate and documented;
the *gate over it* is not. Under a market-derived target `valid_rr` would be a
real filter (measured: median RR 0.25, 1.26 % ≥ 2.0). Under the fixed-R design
that was actually adopted, it can only restate configuration. The gate's form
fits a model the repository did not adopt.

## 4.8 Already a registered decision — DOCUMENTED

`docs/PHASE_4B_FIX_DECISION_MATRIX.md` B13 / **DD15**, class **DECISION**,
disposition **"Do not change"**, with three options and what each would require
(remove / replace with attainability / keep and justify). It states:

> **"`valid_rr` must not be changed until DD1, DD2 and DD5 are settled"**,
> because what "R" means downstream depends on them.

DD1 (which manager is canonical) was settled in Phase 4B. **DD2** (lifecycle
ownership) and **DD5** (ladder-ordering remedy — *"scale milestones with
`tp_ratio`, or floor `tp_ratio` above 2.0"*) remain **UNRESOLVED**. DD5 is
directly coupled: flooring `tp_ratio` above 2.0 would dissolve the `valid_rr`
question by construction.

## 4.9 Classification

**C — redundant, and intent undocumented.**

Not A: it measures no independent quantity (§4.6). Not B (redundant but
intentionally retained): retention is *recorded* (DD15 says "do not change"),
but that is a **moratorium pending evidence**, not a statement that the
redundancy is wanted — and §4.3 finds no rationale for the threshold at all.
Not D: nothing asserts the gate *is* independent, so there is no contradiction
to resolve; code, tests and docs agree it is a tautology.

**"Likely accidental" is the reading the evidence supports, with one caveat:**
the gate's form is coherent under a market-derived target model. Whether it is a
vestige of such a model or was written in error is **UNKNOWN** — no commit
message or document records the decision.

---

# 5. The 4 Current-Code Candidates

**MEASURED.** Rejected **solely** by `valid_rr` on current code. They do not
exist under `baseline_004`, whose `core_trigger` also required `price_in_fvg`.

| # | Timestamp (UTC) | Side | Regime | Style / mode | `core_trigger` | entry | stop | TP | risk | reward | RR | `tp_ratio` | Threshold | `valid_rr` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-17 12:40 | SELL | MICRO_SCALP | MOMENTUM / LIMIT_FVG | **True** | 3983.7250 | 3986.09 | 3980.1775 | 2.365 | 3.5475 | **1.5** | 1.5 | 2.0 | **False** |
| 2 | 2026-08-06 08:00 | BUY | MICRO_SCALP | MOMENTUM / LIMIT_FVG | **True** | 4257.7750 | 4255.11 | 4261.7725 | 2.665 | 3.9975 | **1.5** | 1.5 | 2.0 | **False** |
| 3 | 2026-08-12 09:25 | BUY | MICRO_SCALP | MOMENTUM / LIMIT_FVG | **True** | 4413.2350 | 4410.45 | 4417.4125 | 2.785 | 4.1775 | **1.5** | 1.5 | 2.0 | **False** |
| 4 | 2026-08-28 08:45 | SELL | MICRO_SCALP | MOMENTUM / LIMIT_FVG | **True** | 4607.7950 | 4616.33 | 4594.9925 | 8.535 | 12.8025 | **1.5** | 1.5 | 2.0 | **False** |

**Exact rejection predicate — OBSERVED:**

```python
valid_rr        = rr >= 2.0                      # entry_engine.py:409
entry_triggered = core_trigger and valid_rr      # entry_engine.py:638
                = True         and False  = False
```

**`reward / risk` is exactly 1.5 in all four**, to floating-point precision —
the tautology confirmed on the very candidates it rejects.

**Would any other gate reject them? — MEASURED: no.**

- L1–L7: all passed by construction (they reached L8).
- Within L8: `core_trigger = True`; `valid_rr` is the only other term.
- `trigger_type = "momentum+fvg+choch"` for all four, so `kill_zone`,
  `displacement_found`, `fvg_found` and `m1_choch_confirmed` were all true.
- All four timestamps fall inside `KILL_ZONES_UTC = ((8,10),(12,14))` —
  12:40, 08:00, 09:25, 08:45 — consistent with `core_trigger` requiring it.
- Style: MICRO_SCALP permits MOMENTUM, so unlike the 11 these are **not** also
  blocked by the style restriction.

**`valid_rr` is the sole and sufficient blocker for these four.**

**Not investigated, and deliberately so:** what these four would have done if
admitted. That is `PHASE_4B_FIX_DECISION_MATRIX.md` §6 Option 1's
**[EXPERIMENT]**, and running it is a strategy change.

Three of the four have risk of 2.365–2.785 — the LIMIT_FVG entry rests at the
FVG midpoint, close to the stop. **Recorded as an observation only**; no claim
is made about whether such stops are appropriate.

---

# 6. Sizing Unit Disagreement

## 6.1 The broker's own numbers — OBSERVED

`data/raw/broker_metadata.json`, exported 2026-09-16 from MetaQuotes-Demo:

```
symbol XAUUSD   digits 2   point 0.01
trade_tick_size     0.01
trade_tick_value    0.1
trade_contract_size 100.0
volume_min 0.01   volume_step 0.01   volume_max 100.0
account_currency USD   currency_base XAU   currency_profit USD
```

**MEASURED — internally inconsistent:**

```
tick_size x contract_size = 0.01 x 100.0 = 1.0    <- implied tick_value
broker-reported tick_value               = 0.1    <- disagrees, ratio exactly 10

money per $1.00 move per 1.0 lot:
  from tick_value    (0.1 / 0.01) = 10.0
  from contract_size               = 100.0
```

**The two fields the broker reports cannot both be right.**

## 6.2 The two formulas — OBSERVED

| | `risk_manager.calculate_lot_size_for_symbol` | `core.symbols.money_per_price_unit` |
|---|---|---|
| Location | `risk_manager.py:5-22` | `core/symbols.py:276-299` |
| Formula | `risk_amount / (stop_distance * 10.0)` | `(tick_value / tick_size) * volume` |
| Input units | balance (USD), percent, prices (USD) | volume (lots) |
| Intermediate | `risk_amount` USD; `stop_distance` **price units** | — |
| Output units | lots | USD per 1.0 price unit |
| Origin of the constant | **hardcoded literal `10.0`**, no derivation | **derived from the spec's `tick_value`/`tick_size`** |
| Value for this broker | 10.0 | **10.0** (broker spec) / **100.0** (`XAUUSD_2DIGIT`) |
| Post-processing | `max(0.01, round(·,2))`, then `min(·, 1.0)` | none |
| Caller | `main_production.py:1099` | ledger P&L and R (`ledger.py:236, 780, 815`) |

**OBSERVED** — dead code: `pip_value = 0.01` (`risk_manager.py:17`) is assigned
and never read. The surrounding comments contradict each other and are openly
uncertain.

**OBSERVED** — two specs exist. `XAUUSD_2DIGIT` hardcodes `tick_value=1.0`
(→ 100.0) and is marked *"Test/documentation use only"*; `baseline_004` built
its spec from broker metadata via `spec_from_broker_metadata` (→ 10.0). **Tests
and the baseline do not share a symbol specification.**

**OBSERVED** — `SymbolSpecification.__post_init__` validates each field for
positivity but **never cross-checks `tick_value ≈ tick_size × contract_size`**,
so the inconsistent spec is accepted silently.

## 6.3 Does the repository establish broker truth? — **No**

**The only evidence of the broker's contract is the export itself, and it is
self-contradictory.** There is no independent source: no broker specification
document, no second export, no trade confirmation, no account statement. **UNKNOWN.**

## 6.4 The repository's own positions conflict — DOCUMENTED

| Source | Position |
|---|---|
| `PHASE_2_ISSUES.md` **R1** (P0) | *"XAUUSD contract size is **100, not 10**, so every position is ~10x oversized. `money_per_price_unit()` returns the **correct 100.0**"* — asserts contract_size is authoritative |
| `PHASE_2_ISSUES.md` **D1** (P0) | *"Broker `trade_contract_size = 100.0` but `trade_tick_value = 0.1`… **The baseline uses the broker's own tick value rather than silently substituting the contract size.**"* — declines to pick |
| `PHASE_4B_FIX_DECISION_MATRIX.md` **B7 / DD11** | *"Broker field authority — `contract_size` vs `tick_value`, a 10× difference, **both from the broker**"* — class **DECISION**, unresolved |
| `PHASE_4B_CANONICAL_TRADE_MANAGEMENT_SPEC.md:1241` | *"**Explicitly not resolved here**: DD11… F4 (hardcoded `account_balance = 10000`), B6 (the two conflicting sizing formulas)"* |

R1 asserts what DD11 declines to decide. R1's claim that `money_per_price_unit()`
"returns the correct 100.0" is true only of the **reference constant**, not of
the **broker-derived spec** the baseline actually used, which returns 10.0.

## 6.5 Classification

**CONTRACT AMBIGUITY.**

Not CONFIRMED DEFECT: that label requires knowing which value is correct, and
§6.3 shows the repository cannot establish it.
Not purely DATA/PROVENANCE ISSUE: the data problem is real, but a *registered
decision* (DD11) already exists, so this is a known undecided contract, not an
undiscovered data fault.
Not UNKNOWN: the disagreement is fully characterised; only the resolution is open.

**Separable sub-issues, none decided here:**

| # | Issue | Class |
|---|---|---|
| S1 | Which broker field is authoritative (DD11) | **CONTRACT AMBIGUITY** — needs external evidence |
| S2 | `risk_manager` hardcodes `10.0` instead of deriving from any spec | **CONFIRMED DEFECT** — independent of S1; a magic literal is wrong even if 10.0 is right |
| S3 | Two conflicting formulas in one `if`/`else` (B6) | **CONFIRMED DEFECT**, but **gated on S1** — B6 is registered class FIX with *"They differ by 10×. One is wrong. **Do not pick before B7**"* |
| S4 | `min(lot, 1.0)` ignores `config.INTRADAY_LOT_SIZE_MAX = 0.1` (R6) | **CONFIRMED DEFECT** |
| S5 | `max(0.01, …)` inflates a sub-minimum size instead of declining (R5) | **CONFIRMED DEFECT** |
| S6 | No spec cross-check of `tick_value` vs `tick_size × contract_size` | **CONFIRMED DEFECT** |
| S7 | Tests and baseline use different symbol specs | **CONFIRMED DEFECT** |

**S2, S4, S5, S6 and S7 are decidable without S1**; **S3 is explicitly gated on
it** by the existing register. Phase 6 treated the whole cluster as one "10×
defect"; it is seven separable issues, of which only S1 needs evidence the
repository does not contain, and only S3 must wait for S1's answer.

**No figure in `baseline_004` is affected** — it contains zero trades.

---

# 7. Decision Classification Summary

| Issue | Class | Confidence basis | Registered as |
|---|---|---|---|
| **Regime/style restriction** | **C** — implementation behavior, no documented intent; partial-D rider for MICRO_SCALP | Hardcoded name check; no config field; **no test**; commit `update`; prior audit #44 AMBIGUOUS; contradiction #12 | **New** — no DD number |
| **`valid_rr` / `tp_ratio`** | **C** — redundant, intent undocumented | Tautology proved to ~1e-13 in code, tests and live data; **no rationale for 2.0 or for 1.5/2.0/3.0**; fixed-R target model itself deliberate | **DD15 / B13** |
| **Sizing 10×** | **CONTRACT AMBIGUITY** (S1) + six confirmed defects (S2–S7) | Broker export self-contradictory; no independent source; repository positions conflict | **DD11 / B7**, D1, R1, B6 |

**The style restriction is the only one of the three not already registered as a
decision.** That is itself a finding: it has been observed and classified
AMBIGUOUS by a prior audit but never entered the formal decision register.

---

# 8. Phase 7 Prerequisites

Assessed against the brief's criteria. **Phase 7 cannot begin.**

| # | Criterion | Status | Evidence |
|---|---|---|---|
| P1 | Current decision path frozen | **NOT MET** | `baseline_004` is at `04a341d`; `core_trigger` changed since. No frozen artefact represents current code. |
| P2 | Current trigger behaviour measured | **MET** | Phase 6A + this report: 1,265 L8, 15 `raw=True`, 4 blocked solely by `valid_rr`. Reproduced across three runs. |
| P3 | Regime/style contract resolved **or explicitly accepted as unresolved** | **NOT MET** | Class C, not registered, never reviewed. Neither resolved nor formally accepted. §2 |
| P4 | `valid_rr` contract resolved **or explicitly accepted as unresolved** | **PARTIALLY MET** | DD15 registers it and says "do not change" — a *recorded* acceptance. But it is gated on **DD2 and DD5, both unresolved**. §4.8 |
| P5 | Sizing units resolved enough for risk/P&L to be meaningful | **NOT MET** | S1 (DD11) undecided; every money and R figure scales 10× on the answer. §6 |
| P6 | Historical baseline generation path established | **MET** | `run_baseline` exists; dataset hash verified byte-identical; run reproducible in ~28 min. §B of Phase 6A |
| P7 | Trade-level baseline exists | **NOT MET** | Zero trades anywhere. `baseline_004` `trade_ledger.json` = `[]`. |
| P8 | Costs/execution semantics established | **PARTIALLY MET** | Spread 2.0 pips is **ASSUMED**, recorded as such; slippage and commission zero *so their effects remain attributable*. Never validated against a real fill. |
| P9 | Provenance established | **MET** | Dataset SHA-256 matches on all six timeframes; strategy commit in history; manifest complete. |
| P10 | No unresolved correctness issue capable of materially corrupting results | **NOT MET** | S1 alone scales every currency figure by 10×. Plus `detect_fvg` (Phase 6A §I.1), the `$3.00` buffer (U1), absolute-USD ATR bands (U10). |

**Unmet: P1, P3, P5, P7, P10. Partial: P4, P8.**

**Two are unmeetable in principle today.** P7 requires trades; trades require
either a decision that changes the gates (P3/P4) or a dataset/configuration
where the existing gates fire. **Neither exists.** P10 depends on P5, which
depends on external broker evidence the repository does not contain.

**The minimum honest statement:** Phase 7 is blocked on P7, and P7 is blocked on
decisions no measurement can make. **This is a decision point for review, not an
engineering task.** Running the code is not the constraint — the code runs, is
deterministic, and is fully measured. It produces zero trades by the contract
currently in force.

---

# 9. Unresolved Questions

Carried forward. **None answered here.**

| # | Question | Blocks | Registered |
|---|---|---|---|
| Q1 | Why may MICRO_SCALP take only MOMENTUM? | P3 | No — **should be registered** |
| Q2 | Why may INTRADAY_SWING take only PULLBACK? No document mentions it, and no candidate on this dataset was ever affected | P3 | No |
| Q3 | Should L8 respect L3's setup-style finding, which it currently ignores entirely (#12)? | P3 | No |
| Q4 | What should `valid_rr` do under a deliberately fixed-R target? | P4 | **DD15** |
| Q5 | What is the rationale for the `2.0` threshold? | P4 | Missing-evidence #2 |
| Q6 | What is the rationale for `tp_ratio` 1.5 / 2.0 / 3.0? | P4 | Missing-evidence #3 |
| Q7 | Which broker field is authoritative — `contract_size` or `tick_value`? | P5, P10 | **DD11 / B7** |
| Q8 | Who owns the trade lifecycle? | P4 (gates DD15) | **DD2** |
| Q9 | Ladder-ordering remedy — scale milestones with `tp_ratio`, or floor `tp_ratio` above 2.0? Flooring would dissolve Q4 by construction | P4 (gates DD15) | **DD5** |
| Q10 | Is there any dataset or configuration under which the current contract produces a trade? | P7 | No |
| Q11 | Is 15,735 decisions over ~3 months sufficient to characterise trigger rarity? | P7 | No |

---

# 10. Explicit Non-Goals

Nothing in this document proposes, recommends or performs any of the following,
and no statement here should be read as an argument for them:

- **removing, weakening, replacing or bypassing `valid_rr`** — §5 records that 4
  candidates are blocked solely by it; that is a reason to *decide*, not to act;
- **lowering the RR threshold**;
- **permitting the 11 pullback candidates** — §3.1 further records that doing so
  alone would admit none of them, which is a measurement, not a recommendation;
- **altering regime/style configuration**;
- **changing `tp_ratio`**, the regime ATR bands, or any parameter;
- **modifying FVG, CHoCH, trigger or session rules**;
- **adding fallback entries** or tuning for more trades;
- **fixing sizing** — §6 deliberately stops at classification;
- **regenerating or reinterpreting `baseline_004`**;
- **amending the canonical trade-management specification** — no contradiction
  with it was found;
- **any profitability conclusion.** Zero trades exist. Nothing here says the
  strategy is or is not viable, and the geometry recorded in §3 and §5 is
  evidence about *admission*, never about outcome.

**Diagnostic integrity.** The instrumented replay wrapped
`entry_engine.get_entry_trigger` and returned its result unmodified, redirected
`TRADING_BOT_LOG_FILE` and all other output paths to the session scratchpad
**before** importing `main_production`, and wrote one JSON file outside the
repository. It reproduced the frozen decision count (15,735) and L8 population
(1,265) exactly, and was **run three times with identical results**. The 11
pullback timestamps independently reproduce `PHASE_4A_RAW_TRIGGER_PROBE.md` §7,
which used a different method at a different commit. The diagnostic is **not
committed**.
