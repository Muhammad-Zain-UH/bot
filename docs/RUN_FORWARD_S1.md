# Running forward test S1 (demo only)

Spec: `research/v2026/FORWARD_S1_SPEC.md`. Orders go only to a **demo** account: the broker refuses to
start or send on any account whose trade mode is not DEMO, and `LIVE_TRADING_ENABLED` stays `False`.

**Before starting**: MetaTrader 5 open and logged in to the MetaQuotes-Demo account; Tools > Options >
Expert Advisors > "Allow algorithmic trading" ticked; the AutoTrading button on. The first entry is
2026-10-14 at 19:00 New York (23:00 UTC), for trading day 2026-10-15.

**Start** (from the repository folder, in PowerShell):
`.\venv\Scripts\python.exe -m gold.live.forward_s1`
It prints one line per event (CLOCK, ENTRY, SKIP, TRADE, KILL SWITCH) and appends it to
`data\forward\s1_daily.log`. Trades: `data\forward\s1_trades.csv`; S2 paper log:
`data\forward\s2_signals.csv`; state: `data\forward\s1_state.json` (written atomically every 10 s).

**Stop**: Ctrl+C. State is kept; an open position keeps its server-side stop, and if its 11:00 UTC exit
passed while stopped, the next start closes it at once. On restart, open S1 positions (magic 20261015)
are reconciled with the state file; nothing is opened twice.

**Keep it running** (Windows Task Scheduler, run once in an elevated PowerShell; adjust the path):
`schtasks /Create /TN "ForwardS1" /SC ONLOGON /RL LIMITED /TR "cmd /c cd /d C:\intraday_june\bot4-24\zoyaintraday_bot && .\venv\Scripts\python.exe -m gold.live.forward_s1 >> data\forward\s1_console.log 2>&1"`
Then in Task Scheduler > ForwardS1 > Properties > Settings: tick "If the task fails, restart every 5
minutes" and untick "Stop the task if it runs longer than". MT5 must also start at logon (add it to
Startup). Remove with `schtasks /Delete /TN "ForwardS1" /F`.

**End**: after 2027-01-15 the loop writes `data\forward\s1_decision.json` (CONTINUE / STOP, mean and sd
of net R, t, max drawdown, hold benchmark) and exits. The kill switch (cumulative net R ≤ −6 R) stops
new entries earlier.
