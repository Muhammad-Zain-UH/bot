# S1b paper log — buying at the daily reopen (no orders)

Pre-registered and committed alone before the logger exists. Owner decision 2026-10-14.
**Paper only**: `gold/live/paper_s1b.py` is a separate, read-only process. It sends no order, holds no
position and does not interact with forward test S1 (`gold/live/forward_s1.py`), which is unchanged.

## Why
In 2025-09 → 2026-10, gold's WGC "Asia" gain sat almost entirely in the first hour after the daily
reopen (`research/v2026/REGIME_2026_EXPLORATION.md`, section G), right after a negative gap across the
broker's daily break. S1 does not hold that hour. This log measures, going forward, what a buyer at the
reopen would actually get — paying the ask at the first quote, when spreads are widest.

## What is recorded (XAUUSD, MetaQuotes-Demo price feed)
For each trading day d (labelled by the UTC date of its 11:00 UTC close, as in S1):
- **reopen**: open time of the first H1 bar after a gap of at least one missing hour (the daily break;
  on Mondays the weekend), found as in S1;
- **first quote**: the first tick at or after the reopen — its time, bid and ask;
- **mid + 60 min**: the mid (ask + bid) / 2 of the last tick at or before reopen + 60 minutes;
- **mid at 11:00 UTC**: the mid of the last tick at or before 11:00 UTC on d;
- derived: r_first_hour = log(mid + 60 / first ask); r_rest = log(mid 11:00 / mid + 60);
  r_total = log(mid 11:00 / first ask); spreads at the first quote and at + 60 minutes.

Rows are computed from the server's tick history once 11:00 UTC on d has passed, so a restart loses
nothing; missing days are back-filled. Output: `data/forward/s1b_paper.csv` (gitignored).

## Period and use
Trading days 2026-10-15 → 2027-01-15, the same period as S1. Descriptive only: mean, median and count
of each return are reported at the end next to S1. No pass/fail rule is set here; acting on S1b would
need its own pre-registered test.
