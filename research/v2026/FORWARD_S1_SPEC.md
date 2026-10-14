# Forward test S1 — "Asia session long" on XAUUSD (MetaQuotes-Demo)

Pre-registered and committed alone before any order code or order exists. Owner decision
2026-10-14. **Demo only**: orders go to the MetaQuotes-Demo account; `core/safety.py`
`LIVE_TRADING_ENABLED` stays `False`, and the broker refuses any account whose `trade_mode` is not
DEMO before every `order_send`.

## 1. Why, and the evidence against
- Exploration of 2025-09 → 2026-10 (`research/v2026/REGIME_2026_EXPLORATION.md`, FINAL_OOS opened)
  showed gold strong in the WGC Asia session.
- Against (section G of that report): almost all of that strength (+44.2 % of +48.0 % summed) was in
  the **first hour after the daily reopen**, which S1 does not hold. The window S1 trades — Asia after
  the first hour, to 11:00 UTC — summed only **+3.8 %** over 286 sessions (≈ +1.3 × 10⁻⁴ per day,
  about one long-only round-trip cost). The demo server's session close moved from 17:00 to 16:00
  New York in April 2026. H15 (Asia vs US, 2009–2020) was NOT SUPPORTED. S1 is therefore an
  exploratory forward test, not a confirmed edge.

## 2. Instrument, account, period
- XAUUSD on the MetaQuotes-Demo account; magic number **20261015**.
- Trading day d = the UTC date of its 11:00 UTC exit. Period: trading days **2026-10-15** (entry on the
  evening of 2026-10-14 New York time) through **2027-01-15**, Monday–Friday.

## 3. Rules (each trading day)
- **Daily reopen**: the open time of the first H1 bar after a gap of at least one missing hour between
  consecutive H1 bars (the daily break; on Mondays the weekend). Currently 18:00 New York.
- **Entry**: market BUY at the open of the first H1 bar whose open time is ≥ reopen + 60 minutes
  (currently 19:00 New York = 23:00 UTC in US summer, 00:00 UTC in US winter). The order is sent when
  that bar starts; slippage = fill − that bar's open.
- **Exit**: market close at the close of the H1 bar ending 11:00 UTC (sent when that bar closes);
  slippage = fill − that bar's close. If that bar does not exist, at the first chance after 11:00 UTC.
- **Stop loss**: entry fill price − 1.0 × ATR(14), ATR = simple mean of the last 14 true ranges of
  **closed** broker D1 bars; placed on the order (server-side). No take profit.
- **Size**: risk 0.25 % of demo equity to the stop, via `core.sizing.lots_for_risk` (rounded down to
  volume_step; the day is skipped if below volume_min). Filling mode and the minimum stop distance
  (trade_stops_level) from `symbol_info`; a stop closer than that minimum skips the day.
- **Spread skip**: skip the day if the tick spread (ask − bid) at entry > 3 × the median tick spread of
  all ticks in the same UTC hour on each of the last 20 trading days. Tick spreads on both sides: the
  MT5 bar `spread` field is a broker summary about 4.6 × smaller (k_cost), so it is not comparable.
- No entry if the measured server clock disagrees with the v1b rule (server = Europe/Athens time), if
  the kill switch has fired, or outside the period.

## 4. S2 paper log (no orders)
On each newly closed broker D1 bar: close > highest high of the prior 20 D1 bars → long signal; close <
lowest low of the prior 20 → short signal. Record the signed log return to the next 1, 3 and 5 D1 closes.

## 5. Records
Per trade: trading day, entry/exit times (UTC), entry-bar open, exit-bar close, fills, slippage, stop,
lots, tick spreads at entry and exit, exit reason (TIME or STOP), gross USD, commission + swap + fees,
net USD, risk USD (lots × contract size × |fill − stop|), net R = net USD / risk USD, equity after.
Benchmark: holding gold continuously from the first entry to the last exit (log return), reported next
to S1's return on equity. A daily summary line; skips are logged with their reason.

## 6. Kill switch and decision
- Kill switch: stop trading if cumulative net R ≤ −6 R.
- At the end (or on the kill switch): **CONTINUE** (next step: a real-broker check) only if mean net R
  > 0 **and** the maximum drawdown of cumulative net R < 8 R; otherwise **STOP**. Reported: n trades,
  mean and sd of net R, t = mean / (sd / √n), max drawdown, benchmark. About 60 trades give an
  indication, not proof; no significance is claimed.
