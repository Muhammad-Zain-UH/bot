# MT5 Data Acquisition Probe — 2026-10-01

**DATA ACQUISITION STATUS = MANUAL MT5 ACTION REQUIRED**

The gating check failed: `MaxBars` is still **100000**, unchanged from the
2026-09-16 export. Per the brief, the probe stopped before any bar or tick
measurement. A second, transient blocker is also present.

Everything below was measured read-only from the terminal's own config, logs and
cache directory listings. **No `.hcc` or `.tkc` file was parsed** — depth is
inferred from filenames and sizes only. No production code, no `data/raw`, and no
baseline was touched.

---

## Blockers

| ID | Type | Finding | Effect |
|---|---|---|---|
| **B1** | **manual** | `MaxBars=100000` in `config/common.ini [Charts]` — identical to the value recorded in the previous export | Caps `copy_rates` depth. ~100k M1 bars ≈ 69 market days, which is exactly what truncated the previous M1 series |
| **B2** | **transient** | MT5 IPC refuses: `(-10003, "IPC initialize failed, Pipe server didn't answer in 60 sec")`; a second attempt exceeded 300 s | No bar or tick probe possible until it clears |

**B2 is not a login problem.** The terminal is authorized — `'5056046608': authorized
on MetaQuotes-Demo through Access Point HA (ping 155.29 ms, server build 6231)` at
10:14:10. It is busy: a LiveUpdate to build 6230 completed at 10:18:48, and a large
XAUUSD tick-history download is in flight, measured at **25 MB per 20 seconds**. A
terminal in that state does not answer the IPC pipe inside 60 s.

### Correction

An earlier read of today's log showed 7 lines with no authorization entry, and I
read that as "not logged in." The log was buffered; it now shows 19 lines
including the authorization. **That inference was wrong** — the terminal is and
was logged in.

---

## Measured environment

| | |
|---|---|
| Terminal | MetaTrader 5 x64 **build 5739** running; **build 6230 downloaded and pending restart** |
| Server build | 6231 |
| Python package | `MetaTrader5 5.0.5640` |
| Account / server | `5056046608` on **MetaQuotes-Demo**, demo, hedging, trading enabled |
| Symbols on server | 12,363 |
| Install / data dir | `C:\Program Files\MetaTrader 5\` · `…\Terminal\D0E8209F77C8CF37AD8BF550E51FF075` |
| Machine timezone | GMT+5 (per terminal log) |
| **Free disk** | **18 GB of 238 GB (93% used)** |

## Cached history depth — the significant finding

### XAUUSD bar cache

**23 yearly `.hcc` files: 2004 → 2026, 428 MB.** Continuous, no missing year.

> **The 16-week research dataset was never a broker limitation.** This broker holds
> roughly **22 years** of XAUUSD bar history. The previous dataset's length was a
> product of `MaxBars=100000` and the export's scope, not of what the server has.
> The 2–3 year recommendation in the acquisition spec is comfortably available, and
> so is far more.

### XAUUSD tick cache — actively downloading

**10 monthly `.tkc` files: 202601 → 202610, 512 MB, and still growing backwards.**

| Measure | Value |
|---|---|
| Oldest month present | **2026-01** (was 2026-05 fourteen minutes earlier) |
| Mean size, full month | **57 MB** |
| Growth observed | 25 MB / 20 s, backwards in time |

Tick depth cannot be stated yet because the download has not finished. It is
**already ≥10 months** and the floor is still receding.

### Storage projection from measured `.tkc` rate

| Period | `.tkc` (MT5 compressed) |
|---|---|
| 1 year | **0.68 GB** |
| 2 years | **1.37 GB** |
| 3 years | **2.05 GB** |

Normalized Parquet carrying `bid, ask, spread, mid, last, volume, volume_real,
flags, time_msc` will differ from this; it is a different schema, not the same
bytes recompressed. Treat 2–4 GB as the planning range for 3 years across both
the raw `.tkc` and the normalized store — and note the **18 GB free** headroom,
which the in-flight download is consuming now.

---

## Required manual actions

### 1. Raise MaxBars — the blocking action

```
Tools → Options → Charts → "Max bars in chart"
  change 100000  →  Unlimited  (or 2147483647)
OK → restart the terminal
```

Verify afterwards:

```
grep MaxBars "…\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\config\common.ini"
```

It must no longer read `MaxBars=100000`. The value is written on clean shutdown,
so **restart the terminal rather than killing it**, or the change will not persist.

### 2. Let the terminal settle

- Allow the in-flight tick download to finish (watch the cache directory stop growing).
- Restart to apply **build 6230**, which is already downloaded.
- After that restart, re-check the Python package: the terminal will be on 6230
  while `MetaTrader5` is 5.0.5640. It worked against 5739, but a two-build jump is
  the most likely cause of a repeat IPC failure, and `pip install -U MetaTrader5`
  is the remedy if so.

### 3. Force full bar history into the terminal

For each of M1, M5, M15, H1: open an XAUUSD chart and press **Home** / scroll back
until the chart stops extending. MT5 does not request history a chart has never
displayed, so an unvisited timeframe will probe shallow regardless of `MaxBars`.

### 4. Then run the probe

```
python research/data_acquisition_probe.py research/data_acquisition_probe.json
```

It is written and ready. It captures uncurated `symbol_info`, `terminal_info` and
`account_info` dumps, per-timeframe earliest/latest/rows/gaps, progressively
larger bounded tick windows (1, 7, 30, 90, 180, 365, 730, 1095 days at 6-hour
samples), full tick-field population including `time_msc` and `flags`, per-tick
spread statistics, and a ≤14-request bisection for the oldest obtainable tick.

---

## Deliverable items

| | Item | Result |
|---|---|---|
| **A** | Maxbars | **100000 — NOT raised.** Prior value 100000. No change |
| **B** | Earliest M1 | **Not obtained** — IPC blocked. Bar cache implies 2004 |
| **C** | Earliest M5 | **Not obtained.** Same |
| **D** | Earliest M15 | **Not obtained.** Same |
| **E** | Earliest H1 | **Not obtained.** Same |
| **F** | Earliest tick | **Not obtained.** Cache floor currently 2026-01 and receding |
| **G** | Tick depth available | **≥10 months confirmed, still downloading.** Not yet bounded |
| **H** | Tick field population | **Not obtained** — requires `copy_ticks_range` |
| **I** | Approximate ticks/year | **Not obtained.** 57 MB/month `.tkc` measured; bytes are not a tick count |
| **J** | Storage, 2 years | **1.37 GB** `.tkc`; 2–3 GB planning figure including the normalized store |
| **K** | Storage, 3 years | **2.05 GB** `.tkc`; 2–4 GB planning figure |
| **L** | Is 2 years available? | **Bars: yes, comfortably** (2004→2026). **Ticks: not yet established** |
| **M** | Is 3 years available? | **Bars: yes.** **Ticks: not yet established** |
| **N** | Broker/server limits | No evidence of a *broker* history limit. The observed limits are local: `MaxBars=100000`, 18 GB free disk, a pending build upgrade, and a Python package two builds behind |
| **O** | Exact next action | **Raise MaxBars to Unlimited, restart the terminal, let the tick download finish, scroll back all four timeframes, then re-run the probe** |

---

## Files

- `research/data_acquisition_probe.py` — the probe, ready to run
- `research/data_acquisition_probe.json` — this run's machine-readable output,
  `status: MANUAL_MT5_ACTION_REQUIRED`, with every unobtained measurement listed
  explicitly under `measurements_not_obtained` rather than defaulted or guessed
- `research/DATA_ACQUISITION_PROBE.md` — this report
