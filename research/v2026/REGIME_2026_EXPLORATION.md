# 2026 regime exploration — FINAL_OOS opened (exploratory, descriptive only)

NEW = 2025-09-03 → 2026-10-13 (287 D1 sessions); DEV = 2021-01-05 → 2025-09-01 (1203). MetaQuotes-Demo, v1b clock rule, D1 at 17:00 NY.
Descriptive only. FINAL_OOS is no longer clean; new strategies need a forward demo test from 2026-10-15. Log returns in %, vol annualised %, n = observations.

## A. Gold by month (NEW)

| Month | Return | n D1 | Realised vol (H1) | n H1 | ATR(14) $ | ATR % | n ATR | Max intra-month DD |
|---|---|---|---|---|---|---|---|---|
| 2025-09 | +8.03 | 19 | 14.3 | 463 | 49.5 | 1.31 | 7 | 1.8 |
| 2025-10 | +3.66 | 23 | 25.8 | 526 | 91.7 | 2.26 | 23 | 11.0 |
| 2025-11 | +5.28 | 20 | 20.6 | 459 | 97.4 | 2.39 | 20 | 5.5 |
| 2025-12 | +2.34 | 22 | 19.2 | 502 | 67.1 | 1.56 | 22 | 5.7 |
| 2026-01 | +12.51 | 21 | 38.9 | 481 | 99.2 | 2.08 | 21 | 12.9 |
| 2026-02 | +7.56 | 20 | 40.8 | 454 | 228.9 | 4.58 | 20 | 7.5 |
| 2026-03 | -11.98 | 22 | 41.1 | 505 | 154.9 | 3.23 | 22 | 22.3 |
| 2026-04 | -1.41 | 21 | 26.9 | 462 | 148.4 | 3.14 | 21 | 7.3 |
| 2026-05 | -1.56 | 21 | 21.3 | 461 | 103.3 | 2.25 | 21 | 8.3 |
| 2026-06 | -12.38 | 22 | 28.0 | 482 | 113.3 | 2.69 | 22 | 12.7 |
| 2026-07 | +0.86 | 23 | 23.0 | 502 | 101.2 | 2.48 | 23 | 5.3 |
| 2026-08 | +9.48 | 21 | 21.6 | 464 | 104.6 | 2.36 | 21 | 5.7 |
| 2026-09 | -6.92 | 22 | 23.0 | 483 | 106.5 | 2.46 | 22 | 8.4 |
| 2026-10 | +0.18 | 9 | 17.9 | 205 | 86.1 | 2.07 | 9 | 3.1 |

DEV by year (sum of monthly returns; mean of monthly vol and ATR %; worst monthly DD):

| Year | Months | Return | Mean vol | Mean ATR % | Worst DD | n D1 |
|---|---|---|---|---|---|---|
| 2021 | 12 | -6.4 | 14.3 | 1.33 | 8.4 | 256 |
| 2022 | 12 | -0.3 | 14.8 | 1.41 | 8.3 | 258 |
| 2023 | 12 | +12.3 | 12.8 | 1.23 | 7.6 | 257 |
| 2024 | 12 | +24.1 | 13.9 | 1.37 | 7.7 | 259 |
| 2025 | 9 | +28.1 | 16.4 | 1.53 | 8.8 | 172 |

## B. Gold sessions (WGC fixed UTC: Asia 22–11, Europe 11–14, US 14–22)

| Month (NEW) | Asia | Europe | US | n days |
|---|---|---|---|---|
| 2025-09 | +5.19 | +3.35 | +0.13 | 20 |
| 2025-10 | +3.40 | -0.18 | +0.73 | 22 |
| 2025-11 | +5.13 | +0.77 | -0.67 | 20 |
| 2025-12 | +2.45 | +4.04 | -5.04 | 22 |
| 2026-01 | +9.55 | -2.09 | +3.33 | 21 |
| 2026-02 | +7.75 | +0.45 | -0.19 | 19 |
| 2026-03 | -4.36 | -1.53 | -5.12 | 17 |
| 2026-04 | +1.05 | +2.84 | -1.64 | 21 |
| 2026-05 | -3.71 | +2.09 | +0.47 | 21 |
| 2026-06 | +0.22 | -3.36 | -7.78 | 22 |
| 2026-07 | +5.37 | +3.71 | -1.01 | 23 |
| 2026-08 | +10.12 | +3.46 | +1.46 | 21 |
| 2026-09 | +2.66 | +1.58 | -4.13 | 22 |
| 2026-10 | +2.82 | -1.27 | -0.15 | 9 |

| Mean per day (×10⁻⁴ log) | NEW | n | DEV | n |
|---|---|---|---|---|
| Asia | +17.0 | 280 | +3.0 | 1198 |
| Europe | +5.0 | 280 | -0.9 | 1198 |
| Us | -7.0 | 280 | +1.9 | 1198 |

Next Asia session after the US session (σ of US returns: NEW 0.89 %, DEV 0.56 %), ×10⁻⁴ log:

| US session | NEW mean | NEW sd | n | DEV mean | DEV sd | n |
|---|---|---|---|---|---|---|
| US fell > 1σ | +0.6 | 179 | 43 | +4.0 | 55 | 142 |
| US within ±1σ | +17.4 | 96 | 207 | +4.5 | 51 | 900 |
| US rose > 1σ | +41.4 | 104 | 28 | -5.6 | 59 | 154 |

## C. Persistence

| Lag | D1 ρ NEW (n) | D1 ρ DEV (n) | H4 ρ NEW (n) | H4 ρ DEV (n) |
|---|---|---|---|---|
| 1 | -0.003 (285) | +0.002 (1201) | -0.002 (1722) | +0.004 (7217) |
| 2 | -0.088 (284) | -0.050 (1200) | +0.023 (1721) | +0.013 (7216) |
| 3 | +0.020 (283) | +0.014 (1199) | +0.036 (1720) | -0.017 (7215) |
| 4 | -0.008 (282) | +0.016 (1198) | +0.078 (1719) | +0.006 (7214) |
| 5 | +0.085 (281) | +0.001 (1197) | +0.016 (1718) | +0.017 (7213) |
| 6 | — | — | -0.031 (1717) | -0.000 (7212) |

| Window | D1 close beyond prior 20-day | Next k days | n | Mean | Median | Share > 0 |
|---|---|---|---|---|---|---|
| NEW | above 20-day high | 1d | 29 | +0.48 | +0.59 | 72 % |
| NEW | above 20-day high | 3d | 29 | +0.76 | +1.60 | 69 % |
| NEW | above 20-day high | 5d | 29 | +0.55 | +0.74 | 55 % |
| NEW | below 20-day low | 1d | 11 | -0.39 | +0.78 | 64 % |
| NEW | below 20-day low | 3d | 11 | -0.90 | +0.28 | 55 % |
| NEW | below 20-day low | 5d | 10 | -0.59 | +0.21 | 60 % |
| DEV | above 20-day high | 1d | 105 | -0.03 | -0.06 | 48 % |
| DEV | above 20-day high | 3d | 103 | +0.20 | +0.21 | 57 % |
| DEV | above 20-day high | 5d | 103 | +0.33 | +0.42 | 64 % |
| DEV | below 20-day low | 1d | 56 | +0.04 | +0.04 | 54 % |
| DEV | below 20-day low | 3d | 56 | +0.28 | +0.38 | 61 % |
| DEV | below 20-day low | 5d | 56 | +0.64 | +0.79 | 62 % |

## D. Macro (daily gold return vs daily change: DGS10, DFII10 in bp; DTWEXBGS in log)

| Window | Series | Corr | Beta | 60-day corr min / median / max (n) | n days |
|---|---|---|---|---|---|
| NEW | dgs10_bp | -0.23 | -0.0010 | -0.60 / -0.20 / +0.15 (216) | 275 |
| NEW | dfii10_bp | -0.23 | -0.0011 | -0.46 / -0.24 / +0.16 (216) | 275 |
| NEW | dtwex_log | -0.43 | -2.8753 | -0.64 / -0.48 / -0.18 (216) | 275 |
| DEV | dgs10_bp | -0.35 | -0.0005 | -0.72 / -0.37 / +0.18 (1100) | 1159 |
| DEV | dfii10_bp | -0.39 | -0.0006 | -0.67 / -0.47 / +0.18 (1100) | 1159 |
| DEV | dtwex_log | -0.41 | -1.1693 | -0.73 / -0.44 / +0.20 (1100) | 1159 |

| Window | Days | n | Mean gold return | Share > 0 |
|---|---|---|---|---|
| NEW | DGS10 > +10 bp and dollar up | 4 | -2.331 | 0 % |
| NEW | all days | 275 | +0.047 | 56 % |
| DEV | DGS10 > +10 bp and dollar up | 58 | -0.729 | 17 % |
| DEV | all days | 1159 | +0.047 | 53 % |

## E. Events (NFP = first Friday; BLS dates not fetched, HTTP 403; FOMC dates as given, NEW only)

| Window | Days | n | Mean \|move\| | Median \|move\| | Mean range |
|---|---|---|---|---|---|
| NEW | FOMC | 9 | 1.62 | 0.81 | 3.02 |
| NEW | NFP (first Friday) | 14 | 1.27 | 0.84 | 2.54 |
| NEW | other days | 263 | 1.25 | 0.93 | 2.48 |
| DEV | NFP (first Friday) | 56 | 1.01 | 0.81 | 1.78 |
| DEV | other days | 1146 | 0.68 | 0.51 | 1.35 |

## F. Silver and FX — monthly return / realised vol, NEW (n D1 in brackets; gold in A)

| Month | XAGUSD | EURUSD | USDJPY | GBPUSD | AUDUSD |
|---|---|---|---|---|---|
| 2025-09 | +12.5 / 24.6 (19) | +0.6 / 5.7 (19) | -0.1 / 7.2 (19) | +0.0 / 5.9 (19) | +1.1 / 7.2 (19) |
| 2025-10 | +4.2 / 42.6 (23) | -1.7 / 5.6 (23) | +4.0 / 8.6 (23) | -2.2 / 6.8 (23) | -1.1 / 8.0 (23) |
| 2025-11 | +14.8 / 36.6 (20) | +0.5 / 4.9 (20) | +1.4 / 6.4 (20) | +0.6 / 6.5 (20) | +0.0 / 7.8 (20) |
| 2025-12 | +23.7 / 57.1 (22) | +1.3 / 4.4 (22) | +0.3 / 6.0 (22) | +1.9 / 5.4 (22) | +2.0 / 6.0 (22) |
| 2026-01 | +17.0 / 94.1 (22) | +0.9 / 6.5 (21) | -1.2 / 8.6 (21) | +1.5 / 6.7 (21) | +4.2 / 9.5 (21) |
| 2026-02 | +10.1 / 116.9 (20) | -0.3 / 5.2 (20) | +0.8 / 8.6 (20) | -1.5 / 6.8 (20) | +2.2 / 10.6 (20) |
| 2026-03 | -22.2 / 81.9 (22) | -2.2 / 8.7 (22) | +1.7 / 7.2 (22) | -2.0 / 9.9 (22) | -3.1 / 14.2 (22) |
| 2026-04 | -1.8 / 51.3 (21) | +1.5 / 6.1 (22) | -1.3 / 8.0 (22) | +2.8 / 6.9 (22) | +4.3 / 10.4 (22) |
| 2026-05 | +2.1 / 52.6 (21) | -0.6 / 4.8 (21) | +1.7 / 7.3 (21) | -1.1 / 6.2 (21) | -0.2 / 8.0 (21) |
| 2026-06 | -25.1 / 58.2 (22) | -2.1 / 5.9 (22) | +2.0 / 3.8 (22) | -1.5 / 6.5 (22) | -3.8 / 8.1 (22) |
| 2026-07 | -1.1 / 45.1 (23) | +0.9 / 5.4 (23) | -3.3 / 10.5 (23) | +1.6 / 5.9 (23) | +1.4 / 7.6 (23) |
| 2026-08 | +13.9 / 39.5 (21) | +0.8 / 3.8 (21) | +1.5 / 6.5 (21) | +0.5 / 4.1 (21) | +2.1 / 5.5 (21) |
| 2026-09 | -9.8 / 37.6 (22) | -2.5 / 4.5 (22) | -1.5 / 9.3 (22) | -2.1 / 4.9 (22) | -3.2 / 6.5 (22) |
| 2026-10 | -1.9 / 31.3 (9) | -1.2 / 6.8 (9) | +0.6 / 6.0 (9) | -0.1 / 5.2 (9) | +0.5 / 6.4 (9) |

| Symbol | Vol NEW | Vol DEV | Corr with gold NEW (n) | 2026 (n) | DEV (n) | VR(5) NEW (n) | VR(5) DEV (n) |
|---|---|---|---|---|---|---|---|
| XAUUSD | 27.9 | 14.9 | — | — | — | 0.91 (286) | 0.95 (1202) |
| XAGUSD | 63.5 | 27.8 | +0.83 (286) | +0.84 (202) | +0.74 (1202) | 0.90 (287) | 0.98 (1202) |
| EURUSD | 5.5 | 7.8 | +0.42 (286) | +0.46 (202) | +0.43 (1202) | 1.04 (287) | 0.94 (1212) |
| USDJPY | 8.2 | 9.9 | -0.21 (286) | -0.28 (202) | -0.44 (1202) | 1.10 (287) | 0.93 (1213) |
| GBPUSD | 6.2 | 8.7 | +0.39 (286) | +0.44 (202) | +0.42 (1202) | 0.93 (287) | 0.94 (1212) |
| AUDUSD | 7.8 | 10.7 | +0.55 (286) | +0.61 (202) | +0.48 (1202) | 1.00 (287) | 0.85 (1213) |

## G. Reconciliation of session returns with D1 returns

Exact telescoping of each D1 session (17:00 NY): max |residual| 1.7e-15 — no arithmetic error.

| Component (sum, %) | NEW | n | DEV | n |
|---|---|---|---|---|
| D1 return | +15.64 | 286 | +57.81 | 1202 |
| Gap, daily break (weekdays) | -19.90 | 228 | +8.65 | 963 |
| Gap, weekend (Mondays) | -6.02 | 58 | +2.80 | 239 |
| First hour after reopen | +44.16 | 286 | +6.30 | 1202 |
| Asia after the first hour (to 11:00 UTC) | +3.84 | 286 | +31.56 | 1202 |
| Europe 11–14 UTC | +14.87 | 286 | -12.71 | 1202 |
| US 14 UTC → session close | -21.31 | 286 | +21.22 | 1202 |

Weekday first hour after reopen: NEW mean +16.2 × 10⁻⁴ (71 % > 0, n 228); DEV +1.1 × 10⁻⁴ (56 % > 0, n 963).

| Month (NEW) | n | D1 | Gap (weekdays) | First hour | Asia rest | Sessions ending 15:00 / 16:00 NY bar |
|---|---|---|---|---|---|---|
| 2025-09 | 19 | +8.03 | +0.00 | +0.25 | +4.73 | 0 / 19 |
| 2025-10 | 23 | +3.66 | +0.07 | +2.65 | +1.05 | 0 / 23 |
| 2025-11 | 20 | +5.28 | +0.38 | +2.33 | +2.79 | 0 / 19 |
| 2025-12 | 22 | +2.34 | +0.86 | +1.20 | +1.25 | 0 / 21 |
| 2026-01 | 21 | +12.51 | +0.08 | +6.05 | +3.51 | 0 / 20 |
| 2026-02 | 20 | +7.56 | -0.24 | +2.19 | +5.59 | 0 / 18 |
| 2026-03 | 22 | -11.98 | +1.15 | +1.97 | -6.10 | 2 / 20 |
| 2026-04 | 21 | -1.41 | -0.29 | +2.50 | -1.45 | 21 / 0 |
| 2026-05 | 21 | -1.56 | -0.35 | +2.73 | -6.44 | 20 / 0 |
| 2026-06 | 22 | -12.38 | -2.59 | +2.55 | -2.33 | 21 / 0 |
| 2026-07 | 23 | +0.86 | -7.39 | +6.78 | -1.41 | 22 / 0 |
| 2026-08 | 21 | +9.48 | -5.08 | +6.20 | +3.93 | 21 / 0 |
| 2026-09 | 22 | -6.92 | -5.64 | +5.66 | -3.00 | 21 / 0 |
| 2026-10 | 9 | +0.18 | -0.88 | +1.10 | +1.71 | 9 / 0 |

## H. Is the first-hour gain a bid-quote artifact? (tick data)

MT5 ticks, bid and ask, 2025-05-27 → 2026-10-13 (the server's full tick history). Mean log return × 10⁻⁴ (n); spreads are medians in USD.

| Measure | all weekday reopens | weekday reopens from 2026-07-01 | weekend reopens (Mondays) |
|---|---|---|---|
| First hour after reopen — (a) bid bars | +12.8 (285) | +30.8 (60) | +10.9 (74) |
| First hour — (b) mid | +4.4 (285) | -1.1 (60) | +7.2 (74) |
| First hour — (c) buyer: ask in, mid out | -4.2 (285) | -33.4 (60) | +3.2 (74) |
| Last hour before break — (a) bid bars | -1.7 (285) | -2.8 (60) | +2.1 (74) |
| Last hour — (b) mid | -1.4 (285) | -2.7 (60) | +2.5 (74) |
| Last hour — (c) seller: mid in, bid out | -1.9 (285) | -3.1 (60) | +1.9 (74) |
| Gap across the break — bid | -6.3 (285) | -31.1 (60) | -6.6 (74) |
| Gap across the break — mid | +1.9 (285) | +1.0 (60) | -3.2 (74) |
| Median spread, first 15 min after reopen | 0.190 (283) | 0.755 (60) | 0.480 (73) |
| Median spread, last 15 min before break | 0.170 (277) | 0.240 (59) | 0.180 (70) |
| Median spread at the first tick | 0.500 (285) | 13.785 (60) | 0.500 (74) |
| Median (bar open − first tick bid) | 0.000 (285) | 0.000 (60) | 0.000 (74) |

**Verdict: the first-hour gain is a bid-quote artifact.** Since 2026-07-01 the first quote after the reopen has a median spread of $13.78, so the bid opens far below the true price and 'recovers' as the spread narrows: bid bars show +30.8, mid prices -1.1 and a buyer paying the ask -33.4 × 10⁻⁴ per weekday reopen. The negative gap across the break is the same artifact (bid -31.1, mid +1.0). Over all 285 weekday reopens the buyer's first hour is -4.2. Section G's first-hour sum in NEW, and the WGC 'Asia' strength built on it, are spread artifacts of bid-only bars, not price moves. Other bid-bar research may carry the same bias at reopen bars; ticks exist only from 2025-05-27, so TRAIN and DEV cannot be checked this way. S1 enters 60 minutes after the reopen and is not built on the reopen bar's price.
