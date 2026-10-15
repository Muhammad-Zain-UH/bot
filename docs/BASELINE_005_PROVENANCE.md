# baseline_005 — Provenance

> **Current-path diagnostic baseline; zero-trade result; not a profitability
> study.**

**Phase 6D, Workstream A.** No strategy rule, gate, parameter, `valid_rr`,
regime/style behaviour, sizing, execution or canonical trade-management code was
modified to produce this baseline. `baselines/baseline_004` was **not**
overwritten, modified or regenerated. Nothing was altered to create trades.

## Labels

**OBSERVED** source/artefact · **MEASURED** computed or produced by a run ·
**DOCUMENTED** stated as intent in a repository document · **INFERRED**
reasoning from stated premises · **UNRESOLVED** deliberately not answered.

---

# 1. Why this baseline exists

**DOCUMENTED**, Phase 6C Decision D: create a frozen record of the **current**
decision path *before* implementing the approved `valid_rr` semantic change, so
that any later change can be attributed against something.

**OBSERVED**, Phase 6A §B.1: `baseline_004` was generated at
`04a341daa03de2e8f567b4d01f5c572f7084eb1e`. After that commit, Phase 4A Step 4
removed `price_in_fvg` from the momentum `core_trigger`:

```diff
 core_trigger = bool(
     kill_zone
     and displacement.get("displacement_found")
     and fvg.get("fvg_found")
-    and price_in_fvg
     and m1_choch["m1_choch_confirmed"]
 )
```

The commit records this as deliberate: *"This changes entry prices and therefore
outcomes; it is not a bug fix."* **`baseline_004` therefore could not be assumed
to represent the shipped trigger path.** §5 reports what testing that assumption
actually found.

---

# 2. Exact provenance

| Field | Value |
|---|---|
| Baseline id | `baseline_005` |
| **Source commit** | `7b702ddda0b0061eab03d39403c3747784b8735a` (Phase 6C) |
| Working tree at generation | **clean** — verified by the runner before the run |
| Created (run 1) | 2026-09-23T10:17:28.880344Z |
| **Dataset SHA-256** | `433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c` |
| Dataset source | `data/raw` — the same directory that produced `baseline_004` |
| Symbol | XAUUSD |
| Driving timeframe | M5 |
| Timeframes loaded | D1, H4, H1, M15, M5, M1 |
| Derived-from-M1 timeframes | **none** — all native |
| Dataset range | 2026-06-02 → 2026-09-16 |
| Decision range | 2026-06-24T17:00:00Z → 2026-09-16T12:35:00Z |
| Strategy entry point | `main_production.analyze_entry` |
| Broker / server | MetaQuotes Ltd. / MetaQuotes-Demo |
| Elapsed | 1,708.37 s (9.21 decisions/s) |

## 2.1 Configuration — OBSERVED, identical to `baseline_004`

| Setting | Value |
|---|---|
| Volume | **0.01 lots, FIXED** — `risk_manager` deliberately not used |
| Spread | **2.0 pips, ASSUMED** — no historical spread series exists |
| Slippage | 0.0 |
| Commission per lot | 0.0 |
| Intrabar policy | CONSERVATIVE |
| `max_open_positions` | 3 |
| Entry timing | next bar open |
| Apply spread on exit | true |
| `live_trading_enabled` | **false** |
| `money_per_price_unit(1.0)` | **10.0** — from the broker's own `tick_value` |

**The `money_per_price_unit` value is UNRESOLVED and carried unchanged on
purpose.** It reflects the broker-field ambiguity documented in
`docs/BROKER_ECONOMICS_RECONCILIATION.md`. Changing it would have been a
sizing/economics decision this baseline is explicitly not authorised to make.
**It affects no figure here, because there are zero trades.**

## 2.2 Generation command

```
python <scratchpad>/run_baseline_005.py baseline_005 baselines
```

The runner is the Phase 3A baseline runner with the output root parameterised
and provenance echoing added. It sets `TRADING_BOT_LOG_FILE` and four other
output paths to a temporary directory **before importing `main_production`**, so
the permanent production record is not touched, and redirects the strategy's
per-decision banner to a sink (`print()` has no effect on the decision path).
It calls `backtest.baseline.run_baseline` and `write_artifacts` unmodified.

**The runner is not committed**, consistent with `baseline_004`, whose runner
was also a scratchpad script. It is reproduced in §8 so the run can be rebuilt.

## 2.3 Provenance chain

**MEASURED** — every baseline in the repository:

| Baseline | Commit | Created | Decisions | Signals | `run_fingerprint` |
|---|---|---|---|---|---|
| `baseline_001` | `04a341da` | 2026-09-17T04:51:03 | 15,735 | 0 | `d66abb82…` |
| `baseline_002` | `04a341da` | 2026-09-17T05:23:46 | 15,735 | 0 | `d66abb82…` |
| `baseline_003` | `04a341da` | 2026-09-17T06:19:07 | 15,735 | 0 | `1276a31f…` |
| `baseline_004` | `04a341da` | 2026-09-17T06:46:47 | 15,735 | 0 | `1276a31f…` |
| **`baseline_005`** | **`7b702ddd`** | 2026-09-23T10:17:28 | **15,735** | **0** | **`1276a31f…`** |

**INFERRED:** the zero-signal result has now been produced **five times**, at
two different commits six days apart, by two different operators of the same
generation path. It is not a transient.

`001`/`002` and `003`/`004` each form a deterministic pair, so generate-twice-
and-compare is the established method here; §4 applies it again.

---

# 3. Captured results — MEASURED

## 3.1 Counts

| Stage | Count |
|---|---|
| Total decisions | **15,735** |
| Signal types | `PRE_ENTRY: 15735` — nothing else |
| Strategy errors | **0** |
| Signals | **0** |
| Pending orders created | **0** |
| Fills | **0** |
| Orders / rejected orders | 0 / 0 |
| Trades | **0** |
| Completed trades | 0 |
| Open at end | 0 |

## 3.2 Layer funnel

| Layer | Reached | Blocked |
|---|---|---|
| L1 BIAS | 15,735 | 2,392 |
| L2 STRUCTURE | 13,343 | 7 |
| L3 PULLBACK | 13,336 | 5,868 |
| L4 LIQUIDITY | 7,468 | 629 |
| L5 SWEEP | 6,839 | 4,075 |
| L6 POI | 2,764 | 1 |
| L7 CONFIDENCE | 2,763 | 1,498 |
| **L8 ENTRY** | **1,265** | **1,265** |

Blocks sum to 15,735 — every decision accounted for. **L8 rejects 100 % of what
reaches it.**

## 3.3 Regime and `valid_rr` outcomes at L8

**OBSERVED** from `layer_funnel.json` and `defect_observations.json`:

| Regime | `tp_ratio` | Decisions | Reached L8 | `valid_rr` reachable |
|---|---|---|---|---|
| REGIME_SCALP | 2.0 | 6,492 | 217 | Yes |
| MICRO_SCALP | 1.5 | 5,121 | 972 | **No** |
| DEAD_CALM | 1.5 | 2,312 | 22 | **No** |
| INTRADAY_SWING | 3.0 | 1,810 | 54 | Yes |

`valid_rr` is **false for 994** of the 1,265 (MICRO_SCALP + DEAD_CALM) and true
for 271.

## 3.4 Raw trigger counts — NOT in these artefacts

**This baseline does not record `raw_triggered`, `core_trigger` or `valid_rr`
per decision.** `decisions.jsonl` carries `t, regime, side, signal, blocked,
passed, reason, price` and nothing else.

The raw-trigger figures requested by the brief come from the Phase 6A
instrumented replay, at the same commit lineage and over the same dataset,
**reproduced three times identically**:

| | Count |
|---|---|
| `setup_type = REJECTED` (neither style raised `raw_triggered`) | 1,250 |
| `setup_type = PULLBACK` | 11 |
| `setup_type = MOMENTUM` | **4** |
| `raw=False, valid_rr=False` | 979 |
| `raw=False, valid_rr=True` | 271 |
| `raw=True, valid_rr=False` | **15** |
| `raw=True, valid_rr=True` | **0** |

**This gap is a limitation of the artefact set, recorded in §5.2 and not fixed
here.**

## 3.5 Pending-order statistics

**OBSERVED**, `pending_statistics.json`: `pending_created: 0`, `filled: 0`,
`expired: 0`, `invalidated: 0`, `cancelled: 0`, `fill_rate: null`.

The artefact records its own control conditions: expiry, zone invalidation and
cross-session cancellation are all **`DISABLED [EXPERIMENTAL CONTROL]`**, with
the note *"Research condition only. NOT a live-trading policy: an order with no
expiry and no invalidation must not rest indefinitely against a real broker."*
**Carried unchanged. UNRESOLVED as a live policy.**

---

# 4. Determinism — MEASURED

Generated twice, from the same commit and dataset, run 1 into
`baselines/baseline_005` and run 2 into a scratchpad directory.

**12 of 13 generated artefacts are byte-identical.**

| File | Run 1 vs Run 2 |
|---|---|
| `dataset_manifest.json` | **IDENTICAL** |
| `decision_statistics.json` | **IDENTICAL** |
| `decisions.jsonl` | **IDENTICAL** |
| `defect_observations.json` | **IDENTICAL** |
| `exit_statistics.json` | **IDENTICAL** |
| `layer_funnel.json` | **IDENTICAL** |
| `metrics.json` | **IDENTICAL** |
| `pending_statistics.json` | **IDENTICAL** |
| `regime_statistics.json` | **IDENTICAL** |
| `run_fingerprint.txt` | **IDENTICAL** |
| `side_performance.json` | **IDENTICAL** |
| `trade_ledger.json` | **IDENTICAL** |
| `manifest.json` | **DIFFERS — wall-clock only** |

The whole of `manifest.json`'s difference:

```
created_utc          2026-09-23T10:17:28.880344+00:00  ->  2026-09-23T10:46:56.236244+00:00
decisions_per_second 9.21                              ->  9.07
elapsed_seconds      1708.37                           ->  1735.15
```

**INFERRED:** `created_utc` and the two timing fields are wall-clock
measurements and cannot be identical across runs. **Byte-identity is claimed for
every deterministic artefact and explicitly not claimed for these three
fields.** No fingerprint, count, funnel figure or metric differs.

---

# 5. The significant finding: the decision stream is unchanged

## 5.1 `baseline_005` vs `baseline_004`

**MEASURED**, file by file:

| File | Result |
|---|---|
| **`decisions.jsonl`** | **BYTE-IDENTICAL** — all 15,735 decisions |
| `run_fingerprint.txt` | **BYTE-IDENTICAL** |
| `layer_funnel.json` | **BYTE-IDENTICAL** |
| `decision_statistics.json`, `metrics.json`, `regime_statistics.json`, `exit_statistics.json`, `side_performance.json`, `trade_ledger.json`, `dataset_manifest.json` | **BYTE-IDENTICAL** |
| `manifest.json` | differs: `baseline_id`, `created_utc`, `git_commit`, `strategy_version`, timings |
| `defect_observations.json` | differs: one field **renamed** (`share_of_l8_blocked_by_tautology` → `share_of_l8_reached_in_unreachable_regime`, **same value 0.785771**) and a `causal_note` **added** — both from a later reporting commit, not a behaviour change |
| `pending_statistics.json` | **new** — the artefact did not exist when `baseline_004` was written |

Fingerprints, at both commits:

```
run_fingerprint       1276a31f673a5a82b2879ea5113b12e486da0d2491d03127b30370fd59f2d991
decisions_fingerprint e9421f30331e5b3bf1688fc8f74289248059692075b882e328d9ff3eb7825c75
ledger_fingerprint    4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
dataset_sha256        433b7e2713babdef2ea69909a8bc6a515292dc70b0db434c0b63c256a970b07c
```

**All four identical to `baseline_004`.** (`4f53cda1…` is the hash of an empty
ledger.)

## 5.2 Why — and the limitation it exposes

**INFERRED**, premises in §5.1 and Phase 6A:

The `price_in_fvg` removal changes `core_trigger` for exactly 4 decisions,
turning momentum `raw_triggered` from `False` to `True`. But all 4 are
MICRO_SCALP, where `valid_rr` is false, so `entry_triggered` remains `False`
either way. The decision snapshot records `blocked: "L8_ENTRY"` with reason
`"Entry triggers not all confirmed"` — **the same values before and after.** The
change is real and internal; it never reaches a recorded field.

> **Limitation. `decisions_fingerprint` is invariant to this class of change.**
> A semantic change inside L8 that does not flip `entry_triggered` is
> **undetectable** from these artefacts. The fingerprint is a faithful hash of
> the recorded decision stream; it is not a hash of the strategy's internal
> state, and it must not be relied on to detect trigger-logic changes.

This is why Phase 6A required an instrumented replay, and why §3.4's raw-trigger
counts cannot come from this baseline.

**Recorded as a recommendation, not implemented:** a future artefact revision
could record the L8 conjuncts (`raw_triggered`, `core_trigger`, `valid_rr`,
`setup_type`) per decision. That would be a change to what baselines capture and
needs its own authorisation; it is **not** part of Phase 6D.

## 5.3 What this does and does not establish

| Establishes | Does not establish |
|---|---|
| The current path is frozen at a named commit (Phase 6C prerequisite **P1**) | That the trigger path is unchanged — it is not; §5.2 |
| `baseline_004`'s decision stream is still exactly reproducible on current code | That `baseline_004` can substitute for `baseline_005` going forward |
| Zero trades is reproducible across commits and runs | Anything about performance — there is nothing to measure |

---

# 6. Immutability

**OBSERVED:** `write_artifacts` raises rather than writing into an existing
directory — *"Baselines are immutable — choose a new id rather than overwriting."*
Run 2 was therefore directed to a scratchpad path, never to `baselines/`.

`baselines/baseline_004` was **not** touched: `git status --porcelain baselines/`
reported no modification to it at any point, and its twelve artefacts retain
their 2026-09-17 timestamps.

**One non-generated file was added**, `baselines/baseline_005/LABEL.md`, carrying
the label this phase requires. **No generated artefact was modified.**

## 6.1 Artefact hashes — SHA-256

```
LABEL.md                  44cd5a33c7e2b564d0580da057fe34b2e430698ab79f7e8bb154a439923c3f19
dataset_manifest.json     ceceb03997f911724af2d0ddb0b900edef3714617b7a1bf1884029a0518b5410
decision_statistics.json  d976e022d63f8fb0e9c88774d52126424ae091283cb5766767cf55d56af0c318
decisions.jsonl           eba74c0886e9ebb5710bd364c9a5ea572913ffec7e7e478187de398c6296d228
defect_observations.json  1ea8a36b6ae1800358dd5f3ce1f3447a217794c01a46ff186e70b6d155358031
exit_statistics.json      e453bf5a23d3058777a5ec3fe2fb8b4b75dc627919b6728fb0a1da6e54cae9cb
layer_funnel.json         6a0f125863b28dd46466855be5d20f7d338caf615413026c93fb1874a7511c93
manifest.json             46779ea9533e0be00f35a2e3bee335e1bdc2422c68b1afcbf2972b1d937fd374
metrics.json              76ef2bfa26a976e38548b0450f2776d1e39c461bf5828f28f298ca6c06c0a804
pending_statistics.json   624e498246def9448132c88aec353f4a4fd30bfe634f84fb9d1100886a12c404
regime_statistics.json    f66e9711eee1f55628f80cab6e03dd2608cae4d872d15458c9de07ceb8c3000d
run_fingerprint.txt       61639224beb79cafffba2809681a079897c6801a9bc6d1e9a75c355a85bba653
side_performance.json     09aa44d433acd4c16956040e234fb82ad61e4f99204963769357632db5d8235a
trade_ledger.json         4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
```

`manifest.json`'s hash is **run-specific by construction** (§4). The other
twelve generated hashes are reproducible from the commit and dataset.

---

# 7. Phase 7 Gate — Workstream D

**Phase 7 may not begin.** Status after Phase 6D:

| # | Prerequisite | Before 6D | After 6D | Note |
|---|---|---|---|---|
| P1 | Current decision path frozen | NOT MET | **MET** | `baseline_005`, deterministic |
| P2 | Current trigger behaviour measured | MET | MET | Phase 6A/6B |
| P3 | Regime/style contract decided | Pending ratification | Pending ratification | Phase 6C Decision A |
| P4 | `valid_rr` contract decided | Pending; impl. blocked | Pending; impl. blocked | DD2, DD5 **UNRESOLVED** |
| P5 | Sizing semantics sufficient | NOT MET | **NOT MET** | **BROKER ECONOMICS UNVERIFIED** |
| P6 | Baseline generation path established | MET | **MET, demonstrated** | Two runs, deterministic |
| P7 | Trade-level baseline exists | NOT MET | **NOT MET** | Zero trades, now confirmed five times |
| P8 | Execution semantics frozen | MET | MET | Phase 5B |
| P9 | Ledger semantics frozen | MET | MET | Phase 3 + 5B-i |
| P10 | Costs frozen | PARTIAL | PARTIAL | Frozen as **assumptions**; never validated |
| P11 | Provenance complete | MET | **MET** | Dataset hash verified; full chain §2.3 |
| P12 | Dataset exercises the strategy sufficiently | NOT MET | NOT MET | Depends on P7 |
| P13 | No correctness issue capable of corrupting results | NOT MET | NOT MET | Depends on P5 |

**Net: P1 and P6 advanced. P5, P7, P12, P13 remain unmet.**

## 7.1 The four questions the brief asks

**Is sizing safe enough for performance research?**
**No. MEASURED:** sizing on the `tick_value` reading while `contract_size`
governs risks **9.90 %** of balance against an intended 1 % — a 10× over-risk;
the reverse under-risks at 0.09 %. Every currency and R figure scales by 10× on
the unresolved answer. **No.**

**Can a trade-producing research baseline legitimately be generated yet?**
**No.** The current contract produces zero trades — now confirmed five times
across two commits. The only legitimate routes are (a) implement the approved
`valid_rr` change, which is blocked on DD2 and DD5, or (b) find a period where
the current contract fires, which Phase 6C §4.2 rejected as a **baseline-
selection** method because choosing a period for producing trades conditions
every later result on that choice. Running other periods as a **diagnostic**
remains permitted and unanswered (Phase 6B Q10).

**Must `valid_rr` implementation occur before any performance baseline?**
**Yes, on current evidence** — but not because removing it is desirable. It is
the only identified mechanism by which the current contract would admit any
candidate at all: 4 decisions are blocked solely by it, and the other 1,261 fail
`raw_triggered` independently. **No claim is made about what those 4 would do.**
It cannot proceed until DD2 and DD5 are settled.

**What exactly remains with the strategy owner?**

| # | Decision | Blocks |
|---|---|---|
| 1 | Ratify Phase 6C Decision A (regime/style accepted as-is) | P3 |
| 2 | Ratify Phase 6C Decision B (`valid_rr` semantic) | P4 |
| 3 | **DD5** — scale milestones with `tp_ratio`, or floor `tp_ratio` above 2.0 | P4 → P7 |
| 4 | **The minimum RR value, or whether one exists** — the `2.0` has no rationale | P4 → P7 |
| 5 | **DD2** — who owns the trade lifecycle | P4 |
| 6 | **DD11** — which broker field is authoritative. **Needs external evidence**; §7 of the broker document gives four ways to obtain it | P5, P13 |
| 7 | U1 — is the `$3.00` stop buffer intended as 3 pips? | P13 |

**INFERRED:** items 1–5 are decisions the owner can make from evidence already
gathered. **Item 6 cannot be decided from anything in this repository** and is
the hard dependency for P5 and P13.

---

# 8. Reproducing this baseline

The runner is not committed. To rebuild it:

1. Set `TRADING_BOT_LOG_FILE`, `TRADING_BOT_MAIN_LOG_FILE`, `SIGNAL_LOG_FILE`,
   `MAIN_SIGNAL_LOG_FILE` and `LOG_FILE` to a temporary directory **before
   importing `main_production`**. `backtest.baseline.assert_logs_are_redirected`
   refuses to run otherwise.
2. `meta = json.load(open("data/raw/broker_metadata.json"))`
3. `ds = HistoricalDataset.from_directory("data/raw", "XAUUSD")`
4. `spec = spec_from_broker_metadata(meta, pip_size=0.10)`
5. Redirect stdout to a sink, then
   `run_baseline(ds, spec, baseline_id=..., git_commit=..., broker_metadata=meta,
   spread_pips=2.0, spread_is_assumed=True, progress_every=0)`
6. `write_artifacts(art, Path(<output root>))`

Every other argument takes its default. Expected wall time ~28 minutes.

---

# 9. Non-goals

This baseline and document do **not**:

- change any strategy rule, gate, parameter, `valid_rr`, regime/style behaviour,
  sizing, execution or canonical trade-management code;
- overwrite, modify or reinterpret `baseline_004`;
- resolve the broker-economics ambiguity — see
  `docs/BROKER_ECONOMICS_RECONCILIATION.md`, classified **BROKER ECONOMICS
  UNVERIFIED**;
- implement Phase 6C Decision B;
- select a historical period, for any reason;
- alter anything to create trades;
- make any profitability claim or performance prediction. **Zero trades means
  zero evidence about performance**, and the zero-trade result is the verified
  expected outcome of the contract currently in force — not a finding about the
  strategy's merit.
