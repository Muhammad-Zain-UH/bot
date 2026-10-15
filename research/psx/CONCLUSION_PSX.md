# PSX track — conclusion

**Closed by the owner on 2026-10-15. H-PSX-01 was NOT SUPPORTED; no PSX strategy is traded.**

## Data audit (`ccc219c`, `research/psx/DATA_PSX.md`)
- **Verdict:** FIT, with conditions, for 2013-11 → 2026-10 only.
- **Price source:** PSX's daily closing files. They are survivorship-free: 183 equity names stopped trading and all remain in the files. The exchange's ex-date reference price (LDCP) gives a dividend-, bonus- and split-adjusted total-return series.
- **Conditions:**
  - nothing free exists before 2013-11;
  - psxdata histories are a cross-check only (rolling 10 years, renames double-counted);
  - the liquid universe is small;
  - there is no shares-outstanding history, so portfolios can only be equal-weighted.

## H-PSX-01 — 12–1 month momentum winners vs the equal-weight liquid universe (`2f29732`)
- Pre-registered in `521cfde`, with the construction pinned to `07b9e3f`; 141 holding months, 2015-01 → 2026-09.
- **NOT SUPPORTED:**
  - mean net excess at 1× cost +0.28 % a month, Newey–West t 1.24, one-sided p = 0.108 (α = 0.0167);
  - the 60 % era cap fails (2015–2018 supplies 73 %), which also rules out WEAK SUPPORT.
- **Underpowered:** the blinded power check put the MDE at 0.66 % a month against E_ref 0.60 % (power 71 %). The test therefore does not show that PSX momentum is absent.
- Report: `research/psx/H_PSX01_REPORT.md`.

## Practical finding
From 2016-11, the winners matched the KSE-100 price index but did not beat it. The index excludes dividends, which favours the winners in this comparison.

| From 2016-11 | Net CAGR | Max drawdown |
|---|---|---|
| Winners | +15.07 % | 46.8 % |
| KSE-100 price index (no dividends) | +15.24 % | 40.3 % |

## Family status
- **Confirmatory slots:** 1 of the 3 has been used. The owner closed the track on 2026-10-15.
- **Future hypotheses:** any future PSX hypothesis must be pre-registered and counts as #2, at one-sided α = 0.05/3.
- **Data:** all PSX data stays in gitignored `data/psx/` (PSX Data Legal Notice). Only counts and hashes are committed.
