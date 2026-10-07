# Legacy SMC/ICT pipeline — FROZEN (D1, 2026-10-06)

Owner decision D1 in `docs/ROADMAP_V2.md` §2. No fixes, baselines, unit
migrations or ledger entries for this pipeline. Nothing in `gold/` imports it.

## Frozen modules
Every `*.py` file in the repository root: `main_production.py`, `main.py`,
`bias_engine.py`, `structure_engine.py`, `sweep_detector.py`, `poi_engine.py`,
`liquidity_engine.py`, `pullback_detector.py`, `pullback_handler.py`,
`entry_engine.py`, `confidence_engine.py`, `technical_engine.py`,
`strategy_engine.py`, `feedback_loop.py`, `config.py`, `indicators.py`,
`key_levels.py`, `fibonacci_levels.py`, `cvd_divergence.py`,
`institutional_patterns.py`, `risk_manager.py`, `trade_manager.py`,
`trade_persistence.py`, `order_execution.py`, `mt5_handler.py`,
`news_handler.py`, `error_recovery.py`, `ai_analyst.py`, `utils.py`,
`stage1.py`, `stage2.py`, `debug_l4.py` and the root `test_*.py` scripts.
`baselines/` and their fingerprints are immutable.

## Evidence
- `research/PRODUCTION_PATH_AUDIT_REPORT.md`: no predefined production layer
  demonstrates robust incremental information — 0 of 21 hypotheses survive
  (Bonferroni and BH); L6 POI is a restatement of L5; structure confirmation
  never disagrees with the bias (0 of 60,638 decisions).
- `research/ORIGINAL_CONTINUATION_AUDIT_REPORT.md`: NOT SUPPORTED — the
  displacement and structure layers subtract from bias alone at every horizon.
- Replays in `baselines/baseline_006`–`014` (window 2026-06-02 → 2026-09-16,
  about 15 weeks): 3–6 trades each (006–009: 4, 011–012: 3, 013–014: 6;
  010, the reverted scale-invariance run, 0). No change can be judged on outcome.

## Phase 8 ledger
`docs/PHASE_8_RESEARCH_LEDGER.md` items P8-01 … P8-20 are closed:
**not pursued — strategy frozen (D1).**

## Bugs noticed later
One line each, nothing more.
