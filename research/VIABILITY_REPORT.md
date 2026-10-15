# Viability study — what can this data actually decide?

## Headline: H01–H04 were run on a combination that is NOT TESTABLE at any event rate

All four hypotheses concentrated on **4-hour horizons measured on M15 bars**. That
combination needs **≥ 8,149 independent observations** to resolve a cost-sized
effect and only **4,688 exist** — a minimum event rate of **108.6%**, i.e. more
events than there are bars. **It could not have worked even if every single bar
had been an event.**

| Combination | GO? | headroom | min events needed | min event rate | available |
|---|---|---|---|---|---|
| **1h \| H1** | **GO** | **9.37×** | 1,067 | **1.14%** | **93,739** |
| **4h \| H4** | **GO** | 3.12× | 3,334 | 10.26% | 32,500 |
| **1h \| M15** | **GO** | 3.02× | 2,054 | 2.74% | 18,753 |
| **4h \| H1** | **GO** | 2.37× | 4,163 | 4.44% | 23,434 |
| **4h \| M15** ← *where H01–H04 ran* | **NO** | **0.76×** | 8,149 | **108.6%** | 4,688 |
| 1h \| M5 | NO | 0.66× | 4,771 | 189.9% | 2,093 |
| 24h \| H4 | NO | 0.52× | 20,111 | 61.9% | 5,416 |
| 24h \| H1 | NO | 0.38× | 26,870 | 28.7% | 3,905 |
| 4h \| M5 | NO | 0.17× | 18,882 | 751.5% | 523 |
| 24h \| M15 | NO | 0.13× | 47,603 | 63.5% | 781 |
| 24h \| M5 | NO | 0.03× | 103,133 | 410.5% | 87 |

**4 of 11 combinations can support a decision. The programme spent four hypotheses
on one that cannot.**

And where a hypothesis *did* use a viable combination — `1h | M15`, which needs
**≥ 2,054 events** — H01 had 1,052, H02 574, H03 697, H04 624 per state. **Short
by 2–4×, every time.**

---

## 1. Method — and a correction to the framing

The first draft of this plan compared `cost / ATR` across timeframes. **That was
wrong**, and the error is worth stating because it is the kind that quietly
misdirects a research programme.

The round-turn cost is a **fixed dollar amount** ($0.33), and a 4-hour price move
is **the same move however it is barred**. So the choice of bar timeframe does
**not** change the economics of a trade at a given holding period. Comparing ATRs
across timeframes compares different things and makes it look as though switching
timeframe improves the edge-to-cost ratio. It does not.

What timeframe actually changes is **how much history exists, and therefore how
many independent observations of that holding period are available.**

Everything is therefore computed at a fixed **wall-clock** horizon:

```
cost_in_sd = round_turn_dollars / sd( dollar move over the horizon )
MDE_in_sd  = z / sqrt( independent observations )

TESTABLE  ⟺  MDE_in_sd <= cost_in_sd
```

`z` is the corrected threshold. Three are reported: single test (2.0),
declared-12 (2.865) and **accumulated-30 (3.144)** — the last being the promotion
threshold H04 actually used, and the one the GO column uses.

Independent observations are **non-overlapping** windows: `bars / bars_per_horizon`.
Statistics come from `research/dataset_access.py` and
`research/phase1_statistical_controls.py` — no new statistical code.

**READ-ONLY.** No feature, threshold, candidate or label is selected here. All
series are truncated at the DEV boundary (`2025-09-02 14:15`); **FINAL_OOS is not
inspected.**

## 2. The decisive table

| hor | TF | bars/hor | indep obs | sd($) | cost_in_sd | MDE (1 test) | MDE (12) | **MDE (30)** | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1h | M5 | 12 | 2,093 | 7.250 | 0.0455 | 0.0437 | 0.0626 | 0.0687 | NOT TESTABLE |
| 1h | M15 | 4 | 18,753 | 4.756 | 0.0694 | 0.0146 | 0.0209 | **0.0230** | **TESTABLE** |
| **1h** | **H1** | **1** | **93,739** | 3.428 | **0.0963** | 0.0065 | 0.0094 | **0.0103** | **TESTABLE** |
| 4h | M5 | 48 | 523 | 14.424 | 0.0229 | 0.0874 | 0.1253 | 0.1375 | NOT TESTABLE |
| **4h** | **M15** | 16 | 4,688 | 9.474 | 0.0348 | 0.0292 | 0.0418 | **0.0459** | **NOT TESTABLE** |
| 4h | H1 | 4 | 23,434 | 6.772 | 0.0487 | 0.0131 | 0.0187 | **0.0205** | **TESTABLE** |
| 4h | H4 | 1 | 32,500 | 6.060 | 0.0545 | 0.0111 | 0.0159 | **0.0174** | **TESTABLE** |
| 24h | M5 | 288 | 87 | 33.702 | 0.0098 | 0.2144 | 0.3072 | 0.3371 | NOT TESTABLE |
| 24h | M15 | 96 | 781 | 22.903 | 0.0144 | 0.0716 | 0.1025 | 0.1125 | NOT TESTABLE |
| 24h | H1 | 24 | 3,905 | 17.204 | 0.0192 | 0.0320 | 0.0459 | 0.0503 | NOT TESTABLE |
| 24h | H4 | 6 | 5,416 | 14.883 | 0.0222 | 0.0272 | 0.0389 | 0.0427 | NOT TESTABLE |

Two patterns matter:

- **Longer horizons get harder, not easier.** `cost_in_sd` falls with horizon
  (0.096 → 0.049 → 0.019 on H1) because the move grows while the spread does not —
  so the *economics* improve. But independent observations fall faster
  (93,739 → 23,434 → 3,905), so detectability collapses. **24h is not testable on
  any timeframe.**
- **1h on H1 is the standout**, with **9.37× headroom** — the only combination
  with real room to spare.

## 3. Event-rate budget — the constraint that was violated

A mechanism firing on only a fraction `p` of bars gets only `p ×` the
observations. MDE at the accumulated-30 threshold, by event rate
(`*` = testable):

| hor \| TF | cost_in_sd | p=0.5% | 1% | 2% | 5% | 10% | 25% | 100% |
|---|---|---|---|---|---|---|---|---|
| 1h \| M5 | 0.0455 | 0.288 | 0.209 | 0.154 | 0.110 | 0.091 | 0.077 | 0.069 |
| 1h \| M15 | 0.0694 | 0.164 | 0.116 | 0.083 | **0.055\*** | **0.041\*** | **0.030\*** | **0.023\*** |
| **1h \| H1** | 0.0963 | 0.145 | 0.103 | **0.073\*** | **0.046\*** | **0.032\*** | **0.021\*** | **0.010\*** |
| 4h \| M5 | 0.0229 | 0.313 | 0.239 | 0.194 | 0.162 | 0.150 | 0.141 | 0.137 |
| **4h \| M15** | 0.0348 | 0.169 | 0.123 | 0.093 | 0.068 | 0.057 | 0.050 | 0.046 |
| 4h \| H1 | 0.0487 | 0.146 | 0.104 | 0.075 | 0.049 | **0.037\*** | **0.027\*** | **0.021\*** |
| 4h \| H4 | 0.0544 | 0.247 | 0.174 | 0.123 | 0.078 | 0.055 | **0.035\*** | **0.017\*** |
| 24h \| H1 | 0.0192 | 0.153 | 0.114 | 0.088 | 0.067 | 0.059 | 0.053 | 0.050 |

**`4h | M15` has no asterisk in any column** — not even at p = 100%. That row is
the quantitative obituary for H01–H04's primary design.

**`1h | H1` is testable from p = 2%** — a mechanism as selective as H01's (2.1% of
bars) would have been testable there.

## 4. Regime inventory — the second structural error, quantified

To the DEV boundary only:

| TF | years | up / down years | **bars in down years** | net | down years |
|---|---|---|---|---|---|
| **M15** | 4 | **4 / 0** | **0.0%** | **+92.8%** | **none** |
| **H1** | 17 | 11 / 6 | **37.6%** | +269.3% | 2013, 2014, 2015, 2018, 2021, 2022 |
| H4 | 22 | 16 / 6 | 28.4% | +819.1% | 2013, 2014, 2015, 2018, 2021, 2022 |

**The M15 sample contains zero down years.** Not "few" — zero. Every directional
hypothesis in this programme was tested on a sample with **no bear-market bars at
all**, which is why every report's strongest finding reduced to drift and why the
LONG/SHORT split diagnostic fired in H01, H02, H03 and H04 alike.

**H1 offers 37.6% of its bars inside down years**, including the 2013–2015
decline. That is the single largest improvement available, and it required no new
data — only using what was already fingerprinted and frozen.

## 5. Cost sensitivity — and why it reads backwards

| assumed spread | combinations feasible at full history |
|---|---|
| ×1.0 (as measured, $0.33) | **4 of 11** |
| ×2.0 | 7 of 11 |
| ×4.0 | 8 of 11 |

**A wider spread makes more combinations "feasible", which is not good news.**
`cost_in_sd` rises with the spread, so `MDE ≤ cost` becomes easier to satisfy —
but only because the bar for an *economically interesting* effect has risen, and
larger effects are easier to detect. **It makes the test easier and the strategy
harder.**

The useful reading: **the four GO verdicts are robust to the spread assumption.**
They are GO at the most optimistic spread and remain GO at wider ones. The $0.33
figure, measured on the 2025–26 feed, is almost certainly optimistic for 2009–2015,
and that does not threaten the conclusion.

## 6. Retention model validation — and a prediction of mine that was wrong

Event retention under non-overlapping selection was **measured** with the
production selector rather than modelled, by placing events at random.

| Hypothesis cell | raw | observed non-ov | observed | modelled |
|---|---|---|---|---|
| H01 TRAIN @4h | 1,052 | 914 | 86.9% | 76.5% |
| H02 TRAIN @4h | 574 | 516 | 89.9% | 84.5% |
| H03 TRAIN EXP @4h | 697 | 687 | **98.6%** | 82.6% |
| H04 TRAIN LONG_ACCEPT @4h | 624 | 502 | 80.4% | 83.7% |
| H01 TRAIN @1h | 1,052 | 1,044 | 99.2% | 94.6% |
| H03 TRAIN EXP @1h | 697 | 697 | **100.0%** | 96.3% |

I expected random placement to **over**-estimate retention, on the reasoning that
real events cluster. **It under-estimated in 5 of 6 cases.** The reason is that
every hypothesis in this programme enforces minimum event spacing in its
deduplication rule, which makes real events *more regular* than random, not less.

The model is therefore **conservative**: it over-states MDE and sets a slightly
too strict GO bar — the safe direction for a gating study. The GO verdicts would
only become more favourable with observed retentions.

---

## 7. What this means for the programme

**The four nulls are not strong evidence that no edge exists.** Three of four
hypotheses were tested at a resolution that could not have detected a cost-sized
effect regardless of what the market was doing, on a sample containing no bear
market. H01–H04 should be read as **largely uninformative about the market**, and
informative only about the research design.

That is a materially different conclusion from "gold M15 patterns don't work",
and it is the honest one.

**It is still entirely possible that no exploitable price-pattern edge exists.**
This study does not say one does. It says the question has not yet been asked at a
resolution capable of answering it.

### Binding design constraint from here

> **Every future hypothesis must cite a GO row from §2, and must declare an
> expected event rate at or above that row's minimum.** A hypothesis that cannot
> is not run.

### The four viable combinations, in order of headroom

1. **`1h | H1`** — 9.37× headroom, 93,739 observations, 17 years, 37.6% bear-market
   bars, testable from a 1.14% event rate. **The obvious home for the next
   hypothesis.**
2. **`4h | H4`** — 3.12×, 22 years, but needs a 10.26% event rate.
3. **`1h | M15`** — 3.02×, and the only viable M15 row, but **4 years and zero bear
   market**. Usable for replication, not for primary discovery.
4. **`4h | H1`** — 2.37×, needs a 4.44% event rate.

## 8. Limitations

1. **`sd` is measured over each timeframe's full available history to the DEV
   boundary**, which spans different eras per timeframe (M15 from 2022, H4 from
   2004). Gold's dollar volatility rose roughly 4× over the record, so these
   `sd` values are era-weighted averages, not current values. The GO/NO-GO
   ordering is driven by observation counts, which differ by far more than `sd`
   does, so the ranking is robust — but a 2025-era-only `sd` would raise
   `cost_in_sd` for every row.
2. **The spread assumption** (§5). Robust in direction, optimistic in level for
   older eras.
3. **Independent observations are counted as `bars / bars_per_horizon`**, which
   assumes non-overlapping windows are statistically independent. Volatility
   clustering means they are not fully independent, so the true effective sample
   is somewhat smaller and the real MDE somewhat larger than reported. The GO
   margins at 2.4–3.1× headroom are thin enough that this matters; the 9.37×
   margin on `1h | H1` is not.
4. **This study says nothing about whether an effect exists** — only about whether
   one of a given size could be seen. It is a power and economics study, not a
   discovery.
5. **M5 is only 0.4 years to the DEV boundary** (25,126 bars) and M1 has zero bars
   in the authorised window, so neither can support anything. Confirmed here
   rather than assumed.
6. **One instrument, one broker.** Nothing here addresses the largest untouched
   gap: the entire dataset is XAUUSD OHLC, with no calendar, cross-asset or
   positioning data.

---

## Verdict

**4 of 11 (horizon, timeframe) combinations can support a decision.** The
programme spent four hypotheses on one that cannot, using event counts 2–4× below
the minimum even where the combination was viable, on a sample with **zero
bear-market years**.

The next hypothesis belongs on **`1h | H1`**: 93,739 independent observations,
17 years, 37.6% of bars inside down years, and 9.37× headroom against cost.

No strategy was designed. No threshold was optimised. FINAL_OOS was not
inspected. No profitability claim is made or implied.
