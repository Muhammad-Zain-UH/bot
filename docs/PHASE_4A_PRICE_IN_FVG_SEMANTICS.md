# Phase 4A — semantic investigation: what was `price_in_fvg` intended to prove?

**Read-only.** No file under investigation was modified. No strategy logic, FVG
detection, threshold, session rule, risk, execution or backtest behaviour was
changed. Nothing was optimised. Nothing is proposed for implementation.

**Diagnostic baseline:** commit `6c63b14`.

**Verdict, up front: E — ambiguous / undetermined.** The repository contains no
comment, docstring, test or design document that states the purpose of this
condition, and its entire git history is one bulk commit. Each of the three
coherent candidate purposes (A, B, C) is contradicted by some part of the
implementation. A secondary structural finding is reported separately below: of
the three, only **A** makes the *surrounding* mechanisms coherent — but that is
an inference about design intent, not evidence of it, and it is labelled as such.

---

## 1. Evidence table

| # | Evidence | Source | What it indicates |
|---|---|---|---|
| 1 | `price_in_fvg` occurs on exactly 4 lines: assigned at 585, computed at 591, consumed in `core_trigger` at 609, returned at 655 | `entry_engine.py` | One producer, one consumer. It is an active gate, not dead code. |
| 2 | No caller anywhere reads `momentum_entry["price_in_fvg"]` or `["fvg"]` | repo-wide grep | Its *returned* value is dead output. Only the internal AND uses it. |
| 3 | **No docstring on `_evaluate_momentum_entry`; no comment on `core_trigger`** | `entry_engine.py:556, 607` | No stated intent at the site. |
| 4 | The FVG is built from `m5[-3], m5[-2], m5[-1]` — the three most recent closed bars | `entry_engine.py:267-269` | The gap has **just formed**. No bar exists after it yet. |
| 5 | `price_in_fvg` tests `current_price`, which `main_production` sets to `m5[-2].close` | `main_production.py:983`, `entry_engine.py:591` | The tested price is the **middle candle of the gap pattern itself**. |
| 6 | `confirmed_entry_price` is overridden to `fvg["midpoint"]` whenever a midpoint exists | `entry_engine.py:580-581` | The entry price is the zone centre — inside by construction. |
| 7 | `confirmed_entry_price` is overridden again to `m1[-1].close` when CHoCH confirms | `entry_engine.py:582-583` | A later override can move the entry out of the zone. |
| 8 | Measured: midpoint-sourced entries inside the zone **104/104**; CHoCH-sourced **0/13** | `docs/phase_4a_fvg_records.json` | Under B the check would be redundant in 104 cases and meaningful in 13. |
| 9 | `entry_mode = "LIMIT_FVG"` is set only on the momentum path | `entry_engine.py:625` | The design intends a **limit order at the FVG**, i.e. price is expected to arrive *later*. |
| 10 | `entry_mode` is propagated into logs and the signal dict but **no code branches on it**; `paper_broker._pending` is declared and never used | repo-wide grep; `execution/paper_broker.py:67,86` | The limit-order design was never implemented. Every path is effectively market. |
| 11 | **A second, independent FVG detector exists** in `poi_engine.detect_fvg` with a `fill_percent` concept | `poi_engine.py:273-370` | The codebase elsewhere models price *returning into* a gap explicitly. |
| 12 | That detector scans **subsequent** candles and rejects the FVG if `fill >= 0.5` | `poi_engine.py:322-331` | "Interaction with a gap" is measured over bars **after** formation, using **wicks**. |
| 13 | `_zone_touched(...)` — docstring: *"True if any candle after formation traded into the zone."* Tests `low <= top and high >= bottom` | `poi_engine.py:56-73` | The repository already has a precise vocabulary for zone interaction. |
| 14 | POI scoring awards **+30 for "Untested, first touch"**, and FVG `is_untested = fill_pct < 20 and not _zone_touched(...)` | `poi_engine.py:29, 421-424, 627` | In L6 an **unfilled/untouched** zone is the *desirable* state — the opposite polarity to `price_in_fvg`. |
| 15 | Design doc L8 "Entry Trigger Detection" lists only: rejection candle, wick ≥2× body, close in upper/lower 50%, next M1 close, volume, RSI, MACD | `SYSTEM_STRUCTURE_DIAGRAM.md:356-362` | **The momentum/FVG path is undocumented.** What is documented is the pullback path. |
| 16 | Flow doc L8 lists only rejection candle, momentum confirmation, M1 microstructure flip | `FLOW_DIAGRAM_WITH_FLAWS.md:138-152` | Same. No FVG, kill zone or displacement requirement is described anywhere. |
| 17 | Both design docs mention FVG **only** under Layer 6 / POI ("unfilled gaps ≥3 pips") | `FLOW_DIAGRAM_WITH_FLAWS.md:110`, `SYSTEM_STRUCTURE_DIAGRAM.md:308` | The documented FVG concept in this system is the L6 POI one, not an L8 gate. |
| 18 | **No test references** `price_in_fvg`, `core_trigger`, `_evaluate_momentum_entry` or `LIMIT_FVG` | repo-wide grep | The momentum path is entirely untested. |
| 19 | The one `get_entry_trigger` test asserts `entry_price == m1[-2].close` and pullback-style `trigger_type`s | `test_layer_fixes.py:463-476` | The only behavioural test targets the **pullback** path. (Its expected `trigger_type` strings are also stale versus current code.) |
| 20 | Pullback uses `m1[-2].close`; momentum uses `m1[-1].close` for the same override | `entry_engine.py:497` vs `583` | The two paths disagree on bar index, with no stated reason. |

## 2. Git / history findings

| Question | Finding |
|---|---|
| When was `entry_engine.py` introduced? | Commit `c3cf4df`, dated **2026-07-01**, message **"update"** — added the file whole, 1,115 lines. |
| Size of that commit | **51 files, 43,719 insertions.** A bulk import, not an incremental change. |
| Blame across the momentum block (lines 574–615) | **41 of 42 lines from `c3cf4df`**; 1 line from `4c90b81` (the Phase 0 preservation snapshot). |
| Was the gate introduced before or after the midpoint / CHoCH entry-price behaviour? | **Cannot be determined.** `price_in_fvg`, the `fvg.midpoint` override and the CHoCH override all arrive in the *same* commit, in the *same* function. There is no intermediate history. |
| Any explanatory commit message? | No. The message is "update". |

**Conclusion on history: it yields no evidence of intent.** Item 12 of the
investigation brief — whether the gate predates the midpoint/CHoCH behaviour —
is unanswerable from this repository.

## 3. Semantic classification

### Why each candidate fails

**A — Retracement confirmation** (price must have returned into an
already-formed FVG). *Structurally impossible as implemented.* The FVG is
detected from the three most recent closed bars, so it has just formed and **no
subsequent bar exists** to have retraced into it. The check also tests a single
*close* of a bar **inside** the pattern, not a later bar's wick. The repository's
own retracement vocabulary (`_zone_touched`, `fill_percent`) scans bars *after*
formation and uses highs/lows — `price_in_fvg` does neither.

**B — Entry-location validation** (the proposed entry must lie inside the FVG).
*Contradicted by the code, and redundant if it were the intent.* The check does
not test the entry price; it tests `m5[-2].close`, a different value. And were it
changed to test `confirmed_entry_price`, it would be **true by construction in
104 of the 117 measured cases**, because that price *is* `fvg["midpoint"]`, the
arithmetic centre of the zone. Redundancy quantified: 104/104 midpoint-sourced
entries inside; only the 13 CHoCH-overridden cases could ever fail.

**C — FVG-touch / interaction confirmation.** *The concept exists in the
repository, but not here.* `_zone_touched` and `fill_percent` live in
`poi_engine`, operate on M15, scan post-formation bars, and are used with the
**opposite polarity** — an untouched zone scores **+30**. Nothing connects them
to `entry_engine`, and `entry_engine` has its own unrelated FVG detector.

**D — Redundant / legacy.** *Rejected on the evidence.* `price_in_fvg` is a live
term in `core_trigger` and demonstrably decides outcomes — Phase 4A measured it
as part of the binding conjunction. It is not vestigial, however poorly specified.

### Classification: **E — ambiguous / undetermined**

The repository provides **no** positive evidence of intent: no comment, no
docstring, no test, no design-document mention, and a single unexplained bulk
commit. Every coherent purpose is contradicted by some part of the
implementation. Assigning A, B or C would be guessing.

### Secondary structural finding — inference, not evidence

Recorded because it is decision-relevant, and explicitly labelled as inference.

The mechanisms *surrounding* the gate are coherent only under a retracement /
limit-order design: `entry_mode = "LIMIT_FVG"` (evidence 9) and
`confirmed_entry_price = fvg.midpoint` (evidence 6) together describe *"a gap has
just formed; place a resting order at its centre and wait for price to come
back"*. Under that design a gate asserting price is **already** in the zone is
contradictory — a limit order exists precisely because price is not there yet.

Two further facts make this reading incomplete rather than confirmed: the limit
order is **never implemented** (evidence 10), and the design documents describe an
L8 that contains none of this (evidence 15–16). The most defensible summary is
that the momentum/FVG path is an **unfinished and undocumented addition**, and
`price_in_fvg` cannot be shown to have a settled purpose.

## 4. What `price_in_fvg` should prove

**Not answerable from repository evidence.** Per the brief, this is stated rather
than guessed.

What *can* be stated precisely: **if** the owner decides the intent is
retracement confirmation, the repository already contains the exact observable
event, and no new rule need be invented —

> `poi_engine._zone_touched`: *"True if any candle after formation traded into the
> zone"*, tested as `low <= zone_top and high >= zone_bottom` over bars strictly
> after the bar that formed the zone (`poi_engine.py:56-73`); with
> `fill_percent` (`poi_engine.py:322-331`) quantifying penetration depth as a
> fraction of gap size, using the subsequent bars' lows (BUY) or highs (SELL).

Both use **wicks, not closes**, and both scan **after** formation. Adopting
either would require the FVG to be identified on an **earlier** bar than
`m5[-1]`, since a gap formed on the latest bar has no subsequent bars. **That is
a design change and is not proposed here.**

## 5. Minimum decisions required from the strategy owner

Ordered; the first is blocking.

1. **Is the momentum path intended to be a resting limit order at the FVG
   midpoint, or a market entry?** Everything else follows. `entry_mode =
   "LIMIT_FVG"` says limit; no execution code implements it.
2. **If limit:** what must be true at *signal* time — that the gap exists and is
   unfilled? Then `price_in_fvg` is wrong in polarity and should arguably assert
   the opposite. Note this would align L8 with L6, which rewards untested zones.
3. **If market:** what must be true about price relative to the gap? If the answer
   is "the entry price is in the zone", that is redundant while the entry is the
   midpoint (104/104), and the redundancy must be resolved before the check has
   meaning.
4. **Which bar should the FVG be detected on?** Retracement semantics require a
   gap older than the current bar. The present detector only ever sees a gap
   formed on the latest three bars.
5. **Should `entry_engine` and `poi_engine` share one FVG definition?** Two
   independent detectors currently disagree on timeframe (M5 vs M15), on bound
   naming (`zone_low/high` vs `fvg_top/bottom`), on minimum size (none vs ≥3),
   and on polarity (in-zone required vs untested rewarded).
6. **Which M1 bar index is correct** for the CHoCH entry override — pullback uses
   `[-2]`, momentum uses `[-1]` (evidence 20).

Until 1 and 2 are answered, **no change to `price_in_fvg` can be justified as a
correction** rather than a redesign.

## 6. What must NOT be changed yet

- `entry_engine.py` — in particular `detect_fvg`, `_evaluate_momentum_entry`,
  `price_in_fvg`, `core_trigger`, the midpoint override, the CHoCH override.
- `main_production.py` — including `confirmed_m5_close` at line 983.
- `poi_engine.py` — `detect_fvg`, `_zone_touched`, `fill_percent`, POI scoring.
- Any threshold, including the `0.35` tolerance band, the `≥3` gap minimum, and
  the `0.5` fill limit.
- Session rules, kill zones, risk, sizing, execution, backtest configuration.
- The Phase 3A baseline artifacts, which remain immutable.

**Specifically do not** "fix" `price_in_fvg` by pointing it at
`confirmed_entry_price`. That was measured to be near-vacuous (104/117 true by
construction) and would introduce a second tautology of the same family as the RR
one already on record.

## 7. Determinism

The trace was scripted and executed twice.

| | Run 1 | Run 2 |
|---|---|---|
| Output SHA-256 (first 32) | `77e60052add65a8b466cccd102684012` | same |

Files **byte-identical**. The trace covers every `price_in_fvg`,
`confirmed_entry_price`, `fvg.midpoint` and `entry_mode` site, the `core_trigger`
assembly, both FVG detectors, `_zone_touched`, and the blame summary.

---

*Read-only investigation complete. No implementation, no tuning. Stopping for review.*
