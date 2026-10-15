# PSX data audit — is the free data fit for a monthly momentum test?

Snapshot 2026-10-14 · code `psx/data/` · numbers `research/psx/data_audit.json` · raw `data/psx/raw/` (gitignored, 4,591 files,
hashes `research/psx/psx_fingerprints.json`) · **no strategy or portfolio returns computed** · max 80 lines.

## Verdict
**FIT, with conditions, for 2013-11 → 2026-10 only.** PSX's daily closing files are survivorship-free and carry the
exchange's ex-date reference price (LDCP), so a dividend-, bonus- and split-adjusted series can be built. Conditions:
(1) closing files are the price source, psxdata histories only a cross-check; (2) 12.9 years ≈ 140 monthly holding periods
after a 12-month formation window, overlapping Shah & Shah (2004–2014) only in 2013-11 → 2014-12, nothing earlier free;
(3) small liquid universe, 59–169 stocks a year; (4) PSX publishes no shares-outstanding, split or symbol-change history:
equal weights only, no size control.

## Sources (dps.psx.com.pk via psxdata's request token; one request per 1.5 s, write-once, resumable)
| Source | Coverage | Role |
|---|---|---|
| Closing files `/download/mkt_summary/<day>.Z`: all instruments traded that day, OHLC, volume, LDCP, XD/XB/XR flags | 2013-11-04 → 2026-10-13, 3,191 days (earlier: 404) | primary |
| psxdata `stocks()` = POST `/historical`: unadjusted OHLCV per symbol | rolling 10 years (2016-10-17 →); 1,372 asked, 1,117 with rows | cross-check |
| KSE-100 via `/historical` | 2016-10-17 → 2026-10-13, 2,478 days | calendar |
| Payouts listing, POST `/payouts` | 723 announcements 2024-11-04 → 2026-10-06 (672 D, 18 B, 34 R) | validation |
| Company pages `/company/<symbol>` | current status badge only (DELISTED, CHANGED) | delisting test |

## Symbols per year (ordinary shares*) and liquidity**
2000–2012: **0** in every free PSX source.
| Year | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Closing files | 474 | 491 | 489 | 482 | 467 | 467 | 459 | 449 | 458 | 461 | 462 | 490 | 487 | 493 |
| Histories | – | – | – | 482 | 501 | 497 | 488 | 476 | 485 | 482 | 478 | 500 | 491 | 496 |
| Liquid** | 65 | 83 | 88 | 96 | 102 | 93 | 59 | 93 | 106 | 69 | 78 | 123 | 165 | 169 |

Earliest date per symbol: closing files, 474 on the first file (left-censored), then 7–26 new listings a year; histories, 592 of
705 on the window's first day. \* No debt, ETFs, closed-end funds, futures, or the 221 letters of right and preference shares
(symbol + R, R1…, PS, CPS). \*\* Median close ≥ Rs 10 and median daily close × volume (0 without trades) ≥ Rs 5 m per year.

## Survivorship
- The closing files list every traded symbol: 670 equity symbols traded, 183 stopped before 2026-07-01 (delisted, merged,
  renamed, suspended; 4–20 a year). All 128 that stopped after 2016-10-17 are still served by `/historical`.
- Known names: ENGRO (badge DELISTED, last trade 2025-01-03), DAWH (CHANGED, 2025-01-03), BYCO (CHANGED, 2021-12-20), ICI
  (CHANGED, 2023-01-12), IGIIL (CHANGED, 2018-04-18) are in both sources; PICT and AGTL, tested as delisted, still trade.
  `/symbols` (1,041 entries) still lists dead names, so "listed now" is no survivorship filter.
- 54 symbol changes detected (e.g. KESC → KEL). `/historical` files a renamed company's past under the new symbol (ENGROH
  carries DAWH's prices before 2025), so histories double-count renamed companies; the closing files do not.

## Daily price limit and corporate actions
- Observed limit (LDCP ≥ Rs 20): ±5 % to 2020-01-17, ±7.5 % from 2020-01-20, ±10 % from 2024-05-27, Rs 1 floor (68,188
  closes moved more than the percentage, 5 more than Rs 1). Versus LDCP no close leaves the band but 7 first trading days.
- On an ex-date the exchange lowers LDCP and tags the name XD/XB/XR: 4,522 flag runs, 4,369 with LDCP lowered on day 1.
  Versus the 2024-11+ payouts: bonus 14 of 14 ex-days exact; dividends 483 of 532 equal d % × Rs 10 face value.
- Splits and consolidations carry no flag; LDCP then moves more than the limit allows (49, e.g. AHCL 109.69 → 10.97).

Single-day moves beyond the band in the unadjusted histories: **874** (another 167 span trading gaps).
| Matched to | n |
|---|---|
| The exchange's LDCP adjustment that day (ex-date or split) | 819 |
| An XD/XB/XR flag within 3 trading days | 3 |
| History's previous close ≠ PSX official close (days without trades, 2016-Q4) | 20 |
| Symbol not in that day's closing file (renamed company's stitched history) | 28 |
| **Unexplained**: ENGROH 2025-01-06 (scheme of arrangement), GCIL 2025-04-03 (unflagged Rs 5 cut), IDRT 2016-12-02, LPGL 2016-12-22 | **4** |

## Adjusted series (built: `data/psx/derived/adjusted.parquet`)
Forward-chained per symbol, never back-adjusted (truncation-tested): close / LDCP on flagged or beyond-limit days, close /
previous official close otherwise; zero-volume rows kept (they carry PSX's official close); dividends reinvested on the
ex-date (a total-return index in Rs). 3,556 unflagged LDCP mismatches are ignored; 3,101 fall on 14 days with ≥ 20 % of the
market mismatched because the previous day's file is missing (2 confirmed by KSE-100: 2018-07-19, 2021-02-09; 12 inferred,
2015–16; 10 were 404, 4 empty; none a month-end). Both sources share 897,158 symbol-days: 99.98 % of closes within 0.1 %.

## What is missing, and where else it could come from
- Before 2013-11: PSX's Market Data Team licenses data (marketdatarequest@psx.com.pk); vendors (LSEG Datastream,
  Bloomberg); broker data. A Kaggle PSX dataset needs this same audit (delisted names, adjustments) first.
- Shares outstanding and free float history (market-cap weights, size): not on dps.psx.com.pk; a vendor or annual reports.

## Limitations
- PSX's Data Legal Notice forbids redistribution: raw and derived data stay in gitignored `data/psx/`; only counts and hashes are committed.
- Traded value is close × volume (no turnover column); the Rs 5 m threshold is nominal, and high inflation since 2022 loosens it.
- `/historical` serves a rolling ten years (its first date moves forward daily); the 2026-10-14 snapshot is kept immutable.
- The equity filter uses symbol pattern and sector; non-voting shares, modarabas and REITs remain in the universe.
- Six history responses were HTTP 200 with body "error"; moved to `data/psx/rejected/`, re-fetched; the downloader now rejects such bodies.

## Changes
- (none)
