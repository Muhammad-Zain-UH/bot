# Bar History Probe — post-navigation run, 2026-10-01

## HISTORY_NOT_EXPANDED

**Manual chart navigation did not expand API-accessible history on M1, M5, M15 or
H1.** Every floor is byte-identical to the pre-navigation probe.

**H4 was probed for the first time and is genuinely deep: 2004-06-11, 22.3 years,
34,174 bars, complete and uncapped.**

Your GUI observations are confirmed by the API — and they are confirmed to be
*already* the limit, not a staging post. The oldest visible chart dates you
reported equal the API floors exactly, which means the charts are displaying
everything the terminal holds.

---

## 1–2. Gate and build

| | |
|---|---|
| Live `terminal_info().maxbars` | **100,000,000** |
| `common.ini MaxBars` | 100,000,000 (persisted) |
| Terminal build | **5739** (6230 downloaded, not applied — no restart) |

## 3–11. Depth, expansion verdict, and exact difference

Expected-count validation is now **inside the probe**:
`EXPECTED_7DAY = {M1: 6600, M5: 1320, M15: 440, H1: 110, H4: 27}`.
A return of ≤1 is classified a **sentinel stub**, never data. No bisection —
availability is not assumed monotonic, so every year is tested.

| TF | Earliest reliable (server) | Rows held | Years | Earliest REAL year | Real yrs | Stubs | **Expanded?** | **Δ vs previous** |
|---|---|---|---|---|---|---|---|---|
| **M1** | 2026-06-17 | 100,255 | **0.29** | **none** | 0 | 24 | **No** | **none** |
| **M5** | 2025-04-25 | 100,051 | **1.43** | 2025 | 2 | 22 | **No** | **none** |
| **M15** | 2022-06-30 | 100,017 | **4.25** | 2023 | 4 | 20 | **No** | **none** |
| **H1** | 2009-08-18 | 100,000 | **17.12** | 2010 | 17 | 7 | **No** | **none** |
| **H4** | **2004-06-11** | **34,174** | **22.3** | 2005 | 22 | 2 | *first measurement* | n/a |

Year-by-year counts:

```
M1   03..26 all = 1                                      -> 0 real years
M5   03..24 = 1,  25 = 1380,  26 = 1320                  -> 2 real
M15  03..22 = 1,  23/24/25 = 460,  26 = 440              -> 4 real
H1   03..09 = 1,  10 = 110,  11..25 = 115,  26 = 110     -> 17 real
H4   03/04 = 1,  05..26 = 30/31 per window               -> 22 real, contiguous
```

**On the H4 "2004 stub".** The scan probes a 7-day window each **June**. H4 data
begins **2004-06-11**, which is *after* the 2004-06-01…08 window, so 2004 reads as
a stub while `copy_rates_from_pos` confirms 2004-06-11. The stub is a window
artifact, not absent data — and it is exactly why the expected-count rule must be
read together with the direct floor, not instead of it.

### Why H4 is deep and the rest are not

| TF | Rows held |
|---|---|
| M1 | 100,255 |
| M5 | 100,051 |
| M15 | 100,017 |
| H1 | 100,000 |
| **H4** | **34,174** |

> **There is a ~100,000-bar-per-timeframe materialisation ceiling that MaxBars at
> 1e8 does not lift.** H4 escapes it only because its *entire* 22.3-year history is
> 34,174 bars — a third of what M1 consumes in 3.5 months. All three request sizes
> (99,999 / 150,000 / 500,000) return the same 34,174 for H4, so H4 is **complete,
> not truncated**.
>
> The consequence: **coarse timeframes get decades, fine timeframes get months.**

### Manual navigation had no effect — evidence

1. Floors identical to the pre-navigation probe, to the day.
2. Your GUI-reported oldest dates **equal** the API floors — the charts are already
   at the end of what exists locally.
3. Earlier sync test: `copy_rates_range` at old M1/M5/M15/H1 anchors, re-requested
   after 60 s, 180 s and 360 s, stayed at the 1-row sentinel throughout.

## 12. Gaps and market-minute coverage

| TF | Rows | Span | Monotonic | Dupes | `high<low` | NaN | **Coverage** | Max gap |
|---|---|---|---|---|---|---|---|---|
| M1 | 50,000 | 2026-08-10 → 10-01 | ✓ | 0 | 0 | 0 | **0.668** | 50.0 h |
| M5 | 50,000 | 2026-01-09 → 10-01 | ✓ | 0 | 0 | 0 | **0.656** | 74.1 h |
| M15 | 50,000 | 2024-08-09 → 10-01 | ✓ | 0 | 0 | 0 | **0.666** | 74.3 h |
| H1 | 50,000 | 2018-04-05 → 10-01 | ✓ | 0 | 0 | 0 | **0.672** | 77.0 h |
| **H4** | **34,174** | **2004-06-11 → 10-01** | ✓ | 0 | 0 | 0 | **0.699** | 112.0 h |

Coverage ≈0.66–0.70 on all five — the expected ratio for ~110 market hours in 168.
H4's 112 h maximum gap is a holiday-extended weekend.

## 13. Server UTC offset

**+3.00 h, measured independently** — `symbol_info_tick.time` vs wall-clock UTC.
All `copy_rates_*` / `copy_ticks_*` timestamps are **server time**; subtract 3 h.

Session, derived from bars: daily break **server 22:55 → 01:00 = UTC 19:55 →
22:00** (104×); weekend **Fri 19:55 → Sun 22:00 UTC** (24×). M5 offsets
`{0,5,…,55}`, H1 `{0}`. Unchanged from previous runs.

## 14. Cross-timeframe integrity

M1 resampled against native bars:

| Native | Overlap | Exact match O / H / L / C |
|---|---|---|
| M5 | 8,001 | 99.99 / 99.99 / **100** / **100 %** |
| M15 | 2,667 | 99.96 / **100** / **100** / 99.96 % |
| H1 | 668 | 99.85 / 99.85 / 99.85 / 99.85 % |

Agreement is near-exact; residual disagreements sit in boundary buckets where the
finite M1 window supplies an incomplete first or last bar, and scale with bucket
width. **H4 cannot be cross-checked from M1** — M1 holds 0.29 years, H4 starts
2004, so there is no usable overlap.

## 15. Remaining limitations

| Type | Finding |
|---|---|
| **Structural** | **~100,000-bar per-timeframe materialisation ceiling**, not lifted by MaxBars=1e8 and not lifted by chart navigation. This is now the binding constraint on M1/M5/M15/H1 |
| **Structural** | M1 is the worst affected: **0.29 years**. Sub-M1 and M1-based research cannot reach back further at this broker without a different acquisition route |
| API | `copy_rates_range` returns a **1-row sentinel** for unmaterialised periods |
| API | A single very wide `copy_rates_range` returns `Invalid params`; any export must be chunked |
| API | H4 `copy_rates_range` from 2005 returns 33,357 rows vs 34,174 from `from_pos` — `from_pos` reaches 2004-06-11, the range call started at 2005-01-01. Use `from_pos` for the true floor |
| Local | Build 6230 downloaded, not applied |
| Broker | XAUUSD **tick** archive 52-month hole (2021 → 2025-04) — unaffected |
| Disk | `bases/` at 1.7 GB from earlier tick syncs |

**Ticks unchanged:** contiguous **2025-05-27 → 2026-10-01** (≈16.2 months); density
break **2025-12-10**, pre-break median 109,506 ticks/day vs post-break 832,404
(7.6×).

---

## Not ready for research

Stated explicitly, per instruction. What the measurements now establish:

- **H4 is the only timeframe with multi-regime depth** — 22.3 years, complete,
  clean, contiguous from 2004-06-11. It was previously excluded from the research
  plan for warmup cost and broker-native alignment, and it is now the only
  timeframe that could support long-horizon validation.
- **H1 at 17.12 years is substantial** and is hour-aligned in both server and UTC
  time, so it carries none of H4's alignment caveat.
- **M1 at 0.29 years and M5 at 1.43 years are the hard constraints**, and neither
  the MaxBars change nor chart navigation moved them.

I am not proposing an architecture change off the back of this — the H4-versus-H1
tradeoff (depth versus alignment, and H4's non-UTC boundaries) is an architecture
decision, and the earlier H4 exclusion was deliberate.

## Files

`research/bar_history_probe.py` — one change this run, disclosed: **H4 added** to
the timeframe set, and the expected-count classification moved *into* the probe so
stub/real/zero counts are recorded in the JSON rather than applied at report time.

`research/bar_history_probe.json`, `research/BAR_HISTORY_PROBE.md`.

All untracked, **nothing committed**. `baseline_008` untouched. No production
change, no export, no strategy research, no feature mining, no threshold tuning,
no `.hcc`/`.tkc` parsing, no inference from cache files.
