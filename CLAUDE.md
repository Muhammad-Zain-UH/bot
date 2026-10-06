# CLAUDE.md — XAUUSD research and trading system

## Read first
- Plan of record: `docs/ROADMAP_V2.md`. Owner decisions D1–D6 in its §2 are
  settled; do not reopen them or write decision documents about them.
- Each task comes from `docs/PROMPTS_V2.md`. Do only that task, then stop.

## Frozen — do not modify, do not extend, do not "fix"
- Legacy SMC/ICT pipeline (D1): every `*.py` file in the repository root, e.g.
  `main_production.py`, `main.py`, `bias_engine.py`, `entry_engine.py`,
  `structure_engine.py`, `sweep_detector.py`, `poi_engine.py`,
  `liquidity_engine.py`, `pullback_detector.py`, `confidence_engine.py`,
  `technical_engine.py`, `strategy_engine.py`, `feedback_loop.py` and the rest.
  If you notice a bug there, add one line to `docs/LEGACY_FROZEN.md`. Nothing more.
- `baselines/`, `data/research_v1/`, every fingerprint file, every FINAL_OOS lock.
- `core/safety.py` `LIVE_TRADING_ENABLED = False`.

## Reuse instead of rewriting
- `core/`: units, sizing (`lots_for_risk`), risk_limits, safety, types.
- `execution/`: `broker.Broker` protocol, `PaperBroker`, `intrabar`, `fills`.
- `research/dataset_access.py` (loader and `OOSLockedError` pattern),
  `research/phase1_statistical_controls.py` (inference helpers).
- New code goes in the `gold/` package (layout in ROADMAP_V2 §3).

## How to work
1. Smallest change that answers the question. No new frameworks, registries,
   plugin systems, or abstraction layers unless the task names them.
2. Pre-registration stays: a hypothesis spec is committed alone, before the
   script that computes its results. Specs use
   `research/templates/HYPOTHESIS_TEMPLATE.md` and stay under one page.
3. Reports use `research/templates/REPORT_TEMPLATE.md`: verdict first, the
   pre-declared table, controls, at most five limitation bullets. Max 120 lines.
   If a number was wrong, fix it in place and add one line under "Changes".
   No retraction banners, no strike-through history.
4. Never read FINAL_OOS without the written token from the owner. Never fit
   or choose anything on DEV.
5. Units in names: prices in USD per oz (`price_usd`), distances `*_usd`,
   costs `cost_usd` per round turn per oz, returns as log returns (`r_*`),
   trade results in R. Never compare pips with dollars.
6. Time: store UTC. Define sessions in their market time zone with `zoneinfo`
   (`America/New_York`, `Europe/London`). Never hard-code UTC or PKT offsets.
   On Windows, `tzdata` must be installed.
7. Tests: stdlib `unittest`, as the repo already does. Test behaviour, never
   source text. Every new data or feature function gets a truncation
   (no-lookahead) test.
8. One task = one commit: `area: what changed -- verdict`. Data stays out of git.
9. If you are blocked by a genuine owner choice, stop and ask one short
   question with your recommended answer.

## Reply format at the end of every task (max 15 lines)
- What changed (files)
- Test result (count, pass/fail)
- Verdict or key numbers
- Anything that needs the owner
- Next prompt to run

## Commands
- All tests: `python -m unittest discover -s tests -t .`
- New package tests: `python -m unittest discover -s gold/tests -t .`
