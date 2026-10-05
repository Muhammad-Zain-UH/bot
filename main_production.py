"""
PRODUCTION-READY MAIN ORCHESTRATION ENGINE
10-Layer Trading Bot with Order Execution, State Persistence, and Error Recovery

UPDATED: Regime-aware spread check at L0, dynamic confidence weights, regime-specific entry logic.
"""

from __future__ import annotations
import signal as signal_module
import sys
import time
from datetime import datetime, timezone, timedelta
import csv
import os
import logging
from typing import Dict, List, Optional, Tuple

try:
    # Keep Windows consoles from choking on Unicode log messages.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
# CORE FOUNDATIONS (Phase 1)
#
# Imported unguarded, on purpose. Every other import in this module is wrapped
# in try/except so the bot degrades rather than crashes -- that is appropriate
# for optional analysis layers, but NOT for the execution safety lock. If
# core.safety cannot be imported, the process must fail immediately rather than
# continue with the lock silently absent.
# ============================================================
from core.safety import (
    ExecutionMode,
    LIVE_TRADING_ENABLED,
    UnsafeExecutionStateError,
    assert_live_trading_disabled,
    describe_execution_state,
    resolve_execution_mode,
    validate_execution_environment,
)
from core.risk_limits import (
    AccountRiskState,
    RiskDecision,
    RiskLimitError,
    RiskLimits,
    RiskVerdict,
    build_state as build_risk_state,
    evaluate as evaluate_risk,
    overdue_positions,
)
from core.signal_log import SIGNAL_LOG_COLUMNS as CORE_SIGNAL_LOG_COLUMNS
from core.symbols import XAUUSD_2DIGIT as XAUUSD_SPEC
from core.signal_log import append_signal_row
from core.units import Percentage

# Indicators (required for bias engine contract)
try:
    from indicators import calculate_indicators
    INDICATORS_AVAILABLE = True
except ImportError:
    INDICATORS_AVAILABLE = False

# ============================================================
# IMPORTS - CORE LAYERS
# ============================================================

try:
    import config
    from mt5_handler import connect_mt5, get_market_data, shutdown_mt5, get_current_spread, get_current_price
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("[INFO] MT5 not available - running in analysis/demo mode")

# Import all 10 layer modules
try:
    from bias_engine import get_h4_bias, get_fast_bias
    from structure_engine import get_h1_structure
    from pullback_detector import get_m15_pullback
    from liquidity_engine import identify_liquidity_pools, assess_liquidity_gate
    from sweep_detector import get_sweep_and_structure
    from poi_engine import identify_poi, build_poi_layer_data
    from confidence_engine import get_confidence_engine, evaluate_poi_fib_confluence
    from entry_engine import get_entry_trigger, detect_regime, evaluate_entry_for_regime
    from trade_manager import manage_open_trade, close_position
    from feedback_loop import log_closed_trade, calculate_weekly_performance
    LAYERS_AVAILABLE = True
except ImportError as e:
    LAYERS_AVAILABLE = False
    print(f"[WARNING] Could not import all layers: {e}")

# ============================================================
# IMPORTS - PRODUCTION COMPONENTS
# ============================================================

try:
    # load_closed_trades was not imported, so the closed-trade history this
    # module writes could never be read back -- which is why realised P&L had
    # no source even though trade_persistence had always provided one.
    from trade_persistence import (
        load_active_trades,
        load_closed_trades,
        save_active_trades,
        save_closed_trade,
    )
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False
    print("[WARNING] Trade persistence not available")

try:
    from risk_manager import calculate_lot_size_for_symbol, get_current_session
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    RISK_MANAGER_AVAILABLE = False
    print("[WARNING] Risk manager not available")

try:
    from order_execution import OrderExecutor, OrderType
    EXECUTION_AVAILABLE = True
except ImportError:
    EXECUTION_AVAILABLE = False
    print("[WARNING] Order execution not available")

try:
    from error_recovery import SystemMonitor, ConnectionManager, GracefulShutdownManager, AlertManager, ErrorSeverity, HealthStatus
    ERROR_RECOVERY_AVAILABLE = True
except ImportError:
    ERROR_RECOVERY_AVAILABLE = False
    print("[WARNING] Error recovery not available")

# ============================================================
# GLOBAL STATE
# ============================================================

_SHOULD_CONTINUE = True
_OPEN_TRADES: List[Dict] = []

# Shutdown must never close a position this process did not open. See the gate in
# graceful_shutdown(). Closing is opt-in and defaults OFF; flipping this to True
# is not sufficient on its own, because core.safety.LIVE_TRADING_ENABLED is also
# False and _OWNED_TICKETS can only be filled by a working opening path, which
# this module does not have.
CLOSE_POSITIONS_ON_SHUTDOWN = False
_OWNED_TICKETS: set[int] = set()

# PHASE 0.2 / 0.4: paths are environment-overridable so that tests can redirect
# them to a temporary directory instead of writing into production trading data.
# The defaults are the production paths, so normal operation is unchanged.
#
# The legacy "signal_log.csv" is NOT reused. It accumulated 39,709 rows under a
# 77-column header from an abandoned pipeline while this module wrote 20 columns,
# leaving every field mislabelled. It is archived unmodified at
# archive/2026-09-16_signal_log_legacy_mixed_schema.csv and was not repaired --
# realigning it would mean fabricating data. New records go to a schema-versioned
# file whose header is verified before every append (see core/signal_log.py).
_SIGNAL_LOG_FILE = os.getenv("SIGNAL_LOG_FILE", "signal_log_v2.csv")

# ============================================================
# CONFIGURATION
# ============================================================

CONFIG = {
    "symbol": "XAUUSD",
    "max_concurrent_trades": 3,
    # NOT the enforced figure. The enforced daily-loss cap is
    # config.MAX_DAILY_LOSS_PERCENT, applied through RISK_LIMITS below. This key
    # is kept only because external readers import main_production.CONFIG; it is
    # read by nothing in this module. It held 5.0 while the gate that was meant
    # to apply it could not fire, which is where the belief that the account was
    # protected came from.
    "max_daily_loss_percent": 5.0,
    "risk_per_trade_a_plus": 1.5,
    "risk_per_trade_a": 1.0,
    "h4_candles_required": 100,
    "h1_candles_required": 60,
    "m15_candles_required": 50,
    "m5_candles_required": 100,
    "m1_candles_required": 200,
    # SIMULATION is the only mode this process can actually start in.
    # `False` declares live intent: resolve_execution_mode() maps it to
    # ExecutionMode.LIVE, which validate_execution_environment() refuses
    # unconditionally, so main() raised before reaching the loop. The refusal
    # message at core/safety.py:201-206 prescribes exactly this setting.
    #
    # This does NOT re-enable live trading and cannot: LIVE_TRADING_ENABLED is
    # a Final False with no override, and no send_order path exists anywhere in
    # the repo. Flipping this back to False does not enable trading either -- it
    # only restores the startup refusal.
    "demo_mode": True,
}

# ------------------------------------------------------------------
# L2 volatility floor, in QUOTE CURRENCY (USD), not pips.
#
# Named so there is exactly one place to change it. The value 8.0 is carried
# over unchanged from the inline literal it replaced -- this is not a retune.
#
# It is absolute USD, which makes it price-level dependent rather than a
# volatility measurement. Measured on data/research_v1/bars/XAUUSD_H1.csv
# (14-bar mean high-low range vs this floor):
#
#     2017, 2018  (gold ~$1,260)  100.0% of bars blocked
#     2009-2023   ($1,075-1,943)   81-100% blocked
#     2025        ($3,443)             31.4% blocked
#     2026        ($4,550)              0.0% blocked
#
# Same code, opposite behaviour, purely because gold quadrupled. That is
# PHASE_2_ISSUES.md U9/U10/P2 (P0). Replacing this with a scale-invariant
# form is a behavioural change and is measured separately -- see the plan's
# Track 2. Do not "just lower it".
# ------------------------------------------------------------------
L2_MIN_H1_RANGE_USD: float = 8.0
"""The L2 volatility floor, in QUOTE CURRENCY (USD). Absolute, deliberately.

This is U9 in PHASE_2_ISSUES.md. The unit MISLABELLING is fixed -- the threshold
is named for what it is and every operator message prints ATR in dollars. The
ABSOLUTENESS is a known, measured, **open** defect:

    2017, 2018  (gold ~$1,260)  blocks 100.0% of bars
    2026        (gold  $4,550)  blocks   0.0% of bars

Same code, opposite behaviour, because gold quadrupled. It is not a volatility
filter; it is a proxy for whether gold has got expensive.

### A price-scaled version was implemented, measured and REVERTED

`core/thresholds.py` exists and works, and scaling this floor by the prevailing
price did what it was meant to: the best-to-worst-year spread fell from 100.0
percentage points to 30.1.

It was reverted because of what it did downstream. Measured end to end as
`baselines/baseline_010` against `baseline_009`, on identical data:

    L2_STRUCTURE blocks      12  ->  7,533
    L1_BIAS blocks        1,505  ->  5,950   (knock-on: see below)
    signals                   4  ->      0

Together, 85.7% of 15,735 decisions died at L1 or L2 and the strategy produced
nothing. The L1 jump is indirect: with most bars reclassified DEAD_CALM, L1
stops using the H1 fast bias and falls back to the stricter H4 bias, because
`use_fast_bias` is true only for the scalp regimes.

The reason this is a revert and not a retune: the scaled threshold's selectivity
depends entirely on the reference price chosen, and no non-arbitrary reference
exists (see research/unit_migration_spec.md, which records that correction).
Picking a reference that kept the strategy trading would have been selecting a
threshold by its effect on output, which is the one thing the migration spec
forbids. So the honest options were "scale it and produce nothing" or "leave it
absolute and say so". This is the latter.

Do not change this value to make the strategy trade more. The finding this
records is that the strategy's thresholds only ever worked because they were
accidentally calibrated to one price level, and a different number here does not
fix that.
"""

# PHASE 0.2: single source of truth for the signal-log schema now lives in
# core/signal_log.py. This alias is kept so any external reader importing
# main_production.SIGNAL_LOG_COLUMNS still resolves, but the definition is no
# longer duplicated here -- the duplication is how the file's header and its
# rows came to disagree.
SIGNAL_LOG_COLUMNS = list(CORE_SIGNAL_LOG_COLUMNS)

# ------------------------------------------------------------------
# ACCOUNT-LEVEL RISK LIMITS
#
# Built once from config.py so there is a single declared source. Before this,
# every account-level control in the system was unreachable: the daily-loss
# breaker was called without its loss argument and evaluated `0 < -500` forever
# (PHASE_2_ISSUES.md R3), and no drawdown, consecutive-loss or exposure limit
# existed at all (R7, R8).
#
# `max_hold` makes config.INTRADAY_MAX_HOLD_MINUTES mean something; it has been
# defined and enforced nowhere since it was written (R9).
# `max_lots_per_position` applies config.INTRADAY_LOT_SIZE_MAX, which
# core.sizing does not -- it caps at the BROKER's volume_max, a far larger
# limit (R6).
# ------------------------------------------------------------------
# `config` is imported inside a try below, so construction is guarded. On
# failure RISK_LIMITS stays None, and the gate treats un-evaluable limits as a
# block -- never as permission. That is the same rule the module itself applies
# to unknown account state.
try:
    RISK_LIMITS: RiskLimits | None = RiskLimits(
        max_daily_loss=Percentage(config.MAX_DAILY_LOSS_PERCENT),
        max_drawdown=Percentage(config.MAX_DRAWDOWN_PERCENT),
        max_concurrent_positions=CONFIG["max_concurrent_trades"],
        max_open_lots=config.MAX_OPEN_LOTS,
        max_lots_per_position=config.INTRADAY_LOT_SIZE_MAX,
        max_consecutive_losses=config.MAX_CONSECUTIVE_LOSSES,
        max_hold=timedelta(minutes=config.INTRADAY_MAX_HOLD_MINUTES),
    )
except (NameError, AttributeError, RiskLimitError) as _exc:
    RISK_LIMITS = None
    # `logger` is not built until later in this module, so this uses print --
    # the same pattern the layer-import guard above uses at module scope.
    print(
        f"[CRITICAL] Could not build the account risk limits: {_exc}. "
        f"Every pre-trade gate will BLOCK until this is resolved."
    )

# ============================================================
# LOGGING SETUP
# ============================================================

def _ascii_safe(text: object) -> str:
    """Convert text to ASCII-safe form for Windows consoles and logs."""
    return str(text).encode("ascii", errors="replace").decode("ascii")

# PHASE 0.4: environment-overridable so importing this module under test does not
# append to the production log. Previously the path was hardcoded and built at
# import time, so merely importing main_production wrote to it -- which is how
# four synthetic "ENTRY SIGNAL GENERATED" entries (Entry 101.00 / SL 99.00 /
# TP 104.00) from tests/test_layer_gate_logic.py ended up in the permanent
# production record. The default is unchanged.
log_file_path = os.getenv(
    "TRADING_BOT_LOG_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), 'trading_bot_production.log')),
)

logger = logging.getLogger('TradingBot-Production')
logger.setLevel(logging.INFO)
logger.propagate = False
logger.handlers.clear()

file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(stream=sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)

# ============================================================
# ENHANCED TERMINAL VISIBILITY
# ============================================================

def print_market_snapshot(price: float, h1_atr: float, m5_atr: float, session: str, spread: float) -> None:
    # `h1_atr` and `m5_atr` arrive in QUOTE CURRENCY (USD). `spread` really is
    # pips (mt5_handler.get_current_spread divides by pip size), so only the ATR
    # labels below were wrong. These bands are the same absolute-USD scale as
    # L2_MIN_H1_RANGE_USD and drift with the price level the same way; they are
    # display-only and are left numerically unchanged pending Track 2.
    utc_now = datetime.now(timezone.utc).strftime("%H:%M")
    # Absolute USD bands, matching the L2 gate's own floor -- the display and
    # the gate must not disagree about what counts as calm. They drift with the
    # price level exactly as the gate does; see L2_MIN_H1_RANGE_USD.
    if h1_atr < L2_MIN_H1_RANGE_USD:
        vol_status = "DEAD CALM"
    elif h1_atr < 15:
        vol_status = "LOW-MEDIUM"
    elif h1_atr < 25:
        vol_status = "MEDIUM"
    else:
        vol_status = "HIGH"

    if spread > 10:
        spread_status = "WIDE"
    elif spread > 5:
        spread_status = "MODERATE"
    else:
        spread_status = "TIGHT"

    print("\n" + "█" * 120)
    print(f"  📊 MARKET SNAPSHOT │ {utc_now} UTC │ Price: {price:.2f} │ Session: {session:10s} │ Spread: {spread:.1f}pip ({spread_status:10s})")
    print(f"  🎯 Volatility      │ H1 ATR: ${h1_atr:.2f} ({vol_status:15s}) │ M5 ATR: ${m5_atr:.2f} │ Trend: {'UP' if m5_atr > 5 else 'NORMAL'}")
    print("█" * 120)

def print_regime_detection(regime_info: Dict) -> None:
    if not regime_info:
        return
    regime = regime_info.get("regime", "UNKNOWN")
    m5_atr = regime_info.get("m5_atr", 0.0)
    risk_pct = regime_info.get("risk_percent", 0.0)
    tp_ratio = regime_info.get("tp_ratio", 0.0)
    poi_threshold = regime_info.get("poi_threshold", 0.0)
    bypass_l3 = regime_info.get("bypass_l3", False)
    bypass_l6 = regime_info.get("bypass_l6", False)
    max_spread = regime_info.get("max_spread_pips", 7.0)
    current_spread = regime_info.get("current_spread", 0.0)
    spread_acceptable = regime_info.get("spread_acceptable", True)

    regime_symbol = "⚡" if regime == "MICRO_SCALP" else ("📈" if regime == "REGIME_SCALP" else "📊")
    spread_indicator = f"✓ {current_spread:.1f}pip (OK, max {max_spread:.1f})" if spread_acceptable else f"✗ {current_spread:.1f}pip (EXCEEDS max {max_spread:.1f})"

    if regime == "DEAD_CALM":
        bypass_msg = "(Will be BLOCKED at L2 - no trading)"
    elif bypass_l3 or bypass_l6:
        bypass_msg = f"(Bypass: L{'3 ' if bypass_l3 else ''}{'L6' if bypass_l6 else ''})"
    else:
        bypass_msg = "(Full L1-L8)"

    print(f"\n  {regime_symbol} REGIME: {regime:15s} │ M5 ATR: ${m5_atr:6.2f} │ Risk: {risk_pct:.2f}% │ TP Target: {tp_ratio:.1f}R │ POI: {poi_threshold:.0f}%")
    print(f"     Spread: {spread_indicator:35s} │ Confidence: 70% threshold │ {bypass_msg}")

def print_trade_context(analysis: Dict) -> None:
    side = analysis.get("direction", "UNKNOWN")
    regime = analysis.get("regime_name") or analysis.get("regime_info", {}).get("regime", "UNKNOWN")
    candidate = analysis.get("candidate_entry_style", "PULLBACK / MOMENTUM")
    print(f"\n  🎯 TARGET: {side:4s} | REGIME: {regime:15s} | LOOKING FOR: {candidate}")

def build_layer_progress_summary(layers_passed: list, layer_failed: Optional[str] = None) -> str:
    entry_layers = ["L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY", "L5_SWEEP", "L6_POI", "L7_CONFIDENCE", "L8_ENTRY"]
    completed_layers = [layer for layer in entry_layers if layer in layers_passed]
    if layer_failed and layer_failed != "NONE":
        return (
            f"{len(completed_layers)}/{len(entry_layers)} entry layers passed | "
            f"Completed: {', '.join(completed_layers) if completed_layers else 'none'} | "
            f"Current block: {layer_failed} | "
            f"Pending: {', '.join([layer for layer in entry_layers if layer not in completed_layers and layer != layer_failed]) if any(layer not in completed_layers and layer != layer_failed for layer in entry_layers) else 'none'}"
        )
    return (
        f"{len(completed_layers)}/{len(entry_layers)} entry layers passed | "
        f"Completed: {', '.join(completed_layers) if completed_layers else 'none'}"
    )

def print_layer_status(layers_passed: list, layer_failed: str, fail_reason: str) -> None:
    layer_descriptions = {
        "L0_GATES": "Pre-trade gates (daily loss, session, spread monitor)",
        "L1_BIAS": "H4 EMA directional bias (bullish/bearish confirmation)",
        "L2_STRUCTURE": "H1 structure (HH/HL, LH/LL) + ATR volatility check",
        "L3_PULLBACK": "M15 pullback quality (retracement setup detection)",
        "L4_LIQUIDITY": "Liquidity pools (sweep/TP level quality)",
        "L5_SWEEP": "Sweep confirmation + CHoCH/BOS structure",
        "L6_POI": "Point of Interest order blocks (POI confluence)",
        "L7_CONFIDENCE": "Confidence score (weighted component aggregate)",
        "L8_ENTRY": "Entry triggers + spread regime check",
        "L8_SPREAD": "Spread tolerance check for the active regime",
    }
    all_layers = ["L0_GATES", "L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY",
                  "L5_SWEEP", "L6_POI", "L7_CONFIDENCE", "L8_ENTRY"]

    print(f"\n  📋 {build_layer_progress_summary(layers_passed, layer_failed)}")
    status_line = ""
    for layer in all_layers:
        if layer in layers_passed:
            status_line += f"✓{layer} "
        elif layer == layer_failed:
            status_line += f"✗{layer} "
        else:
            status_line += f"- "
    print(f"  🔎 LAYER PIPELINE: {status_line}")

    if layer_failed and fail_reason:
        desc = layer_descriptions.get(layer_failed, "Unknown layer")
        print(f"\n  ❌ BLOCKED AT {layer_failed}")
        print(f"     What: {desc}")
        print(f"     Why:  {fail_reason}")
    print("\n" + "█" * 120)

def print_layer_result(layer_num: int, layer_name: str, status: str, reason: str = "", details: str = "") -> None:
    status = status.upper()
    if status == "PASS":
        status_display = "PASS"
    elif status == "BLOCK":
        status_display = "BLOCK"
    elif status == "WAIT":
        status_display = "WAIT"
    else:
        status_display = status

    msg = f"  L{layer_num} [{status_display:5s}] {layer_name:20s} | {reason}"
    if details:
        msg += f" | {details}"
    print(msg)

def _log_same_summary(analysis: Dict) -> None:
    signal_type = analysis.get('signal_type', 'UNKNOWN')
    layers = analysis.get("layers_passed", [])
    layer_failed = analysis.get("layer_failed") or "NONE"
    fail_reason = analysis.get("fail_reason", "")
    regime = analysis.get("regime_name") or analysis.get("regime_info", {}).get("regime", "UNKNOWN")
    side = analysis.get("direction", "UNKNOWN")
    candidate = analysis.get("candidate_entry_style", "PULLBACK / MOMENTUM")
    price = analysis.get("current_price")
    price_text = "N/A" if price in (None, "", 0) else f"{float(price):.2f}"
    passed_layers = ",".join(layers) if layers else "NONE"

    log_line = (
        f"[DECISION] price={price_text} side={side} regime={regime} target={candidate} "
        f"passed={passed_layers} blocked={layer_failed} signal={signal_type} reason={fail_reason or 'NONE'}"
    )
    logger.info(log_line)

def print_run_summary(analysis: Dict) -> None:
    signal_type = analysis.get('signal_type', 'UNKNOWN')
    layers = analysis.get("layers_passed", [])
    layer_failed = analysis.get("layer_failed", "NONE")
    fail_reason = analysis.get("fail_reason", "")
    regime_info = analysis.get("regime_info", {})
    entry = analysis.get("entry_signal")

    if regime_info:
        print_regime_detection(regime_info)

    print_trade_context(analysis)
    print_layer_status(layers, layer_failed, fail_reason)
    _log_same_summary(analysis)

    if signal_type == "ENTRY_SIGNAL" and entry:
        print(f"\n  ✅ ENTRY SIGNAL GENERATED")
        print(f"     Position Type: {entry.get('position_type', 'N/A'):8s} │ Grade: {entry.get('grade', 'N/A')}")
        print(f"     Setup Type: {entry.get('setup_type', 'N/A'):20s} │ Trigger: {entry.get('trigger_type', 'N/A')}")
        print(f"     Entry Price: {entry.get('entry_price', 'N/A'):10s} │ Risk %: {entry.get('risk_percent', 'N/A')}")
        print(f"     Risk/Reward: 1:{float(entry.get('rr_ratio', 0.0)):.2f} │ Confidence: {entry.get('confidence_score', 0.0):.1f}%")
        print(f"     Setup Details: {entry.get('setup_description', 'N/A')}")
        print("     " + "=" * 115)
    elif signal_type == "PRE_ENTRY":
        print(f"\n  ⏳ PRE-ENTRY SIGNAL ({build_layer_progress_summary(layers, layer_failed)})")
        print(f"     Current Gate: {layer_failed if layer_failed != 'NONE' else 'L0_GATES'}")
        print(f"     Waiting For: {fail_reason}")
        print("     " + "=" * 115)
    elif signal_type == "ERROR":
        print(f"\n  ⚠️  ANALYSIS ERROR")
        print(f"     Issue: {fail_reason}")
        print("     " + "=" * 115)
    else:
        print(f"\n  ℹ️  MONITORING ({build_layer_progress_summary(layers, layer_failed)})")
        if fail_reason:
            print(f"     Next Gate: {fail_reason}")
        print("     " + "=" * 115)
    print()

monitor = None
connection_mgr = None
shutdown_mgr = None
alert_mgr = None
order_executor = None

def initialize_production_components():
    global monitor, connection_mgr, shutdown_mgr, alert_mgr, order_executor
    if ERROR_RECOVERY_AVAILABLE:
        logger.info("[INIT] Initializing System Monitor...")
        monitor = SystemMonitor()
        logger.info("[INIT] Initializing Connection Manager...")
        connection_mgr = ConnectionManager()
        logger.info("[INIT] Initializing Graceful Shutdown Manager...")
        shutdown_mgr = GracefulShutdownManager(persistence_layer=__import__('trade_persistence') if PERSISTENCE_AVAILABLE else None)
        logger.info("[INIT] Initializing Alert Manager...")
        alert_mgr = AlertManager()
    if EXECUTION_AVAILABLE:
        logger.info("[INIT] Initializing Order Executor...")
        order_executor = OrderExecutor()
    logger.info("[INIT] [+] All production components initialized")

# ============================================================
# SIGNAL LOGGING
# ============================================================

def log_signal(row: dict) -> None:
    """Append one decision row to the schema-versioned signal log.

    PHASE 0.2: delegates to core.signal_log, which verifies the header before
    every append and rotates a mismatched file aside rather than appending
    values that do not correspond to it. Row content is unchanged from the
    legacy writer; only a leading schema_version column is added.
    """
    try:
        append_signal_row(_SIGNAL_LOG_FILE, row)
    except Exception as e:
        logger.error(f"Error logging signal: {e}")

def _count_today_entry_signals(log_file: str = _SIGNAL_LOG_FILE) -> int:
    if not os.path.isfile(log_file):
        return 0
    today = datetime.now().date().isoformat()
    count = 0
    try:
        with open(log_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("signal_type", "")).upper() != "ENTRY_SIGNAL":
                    continue
                timestamp = str(row.get("timestamp", ""))
                if timestamp[:10] == today:
                    count += 1
    except Exception:
        return 0
    return count

# ============================================================
# SESSION & TIMING UTILITIES
# ============================================================

def get_session_name() -> str:
    try:
        from risk_manager import get_current_session as _get_current_session
        session = _get_current_session()
        session_map = {
            "Asian": "ASIAN",
            "London": "LONDON",
            "LondonNewYork": "LONDON",
            "NewYork": "NY",
            "Dead": "DEAD",
            "Closed": "DEAD",
        }
        return session_map.get(session, "DEAD")
    except Exception:
        hour = datetime.now(timezone.utc).hour
        if 0 <= hour < 7:
            return "ASIAN"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 21:
            return "NY"
        return "DEAD"

def get_session_bonus() -> float:
    session = get_session_name()
    if session in ["LONDON", "NY"]:
        return 8.0
    if session == "ASIAN":
        return 0.0
    if session == "DEAD":
        return -15.0
    return 0.0

def _extract_intraday_rsi(m15_data=None, m5_data=None) -> float | None:
    for frame in (m15_data, m5_data):
        if frame is None or len(frame) == 0:
            continue
        try:
            indicators = calculate_indicators(frame) if INDICATORS_AVAILABLE and callable(calculate_indicators) else {}
            rsi_value = indicators.get("rsi_14") if isinstance(indicators, dict) else None
            if rsi_value is not None:
                return float(rsi_value)
        except Exception:
            continue
    return None

# ============================================================
# LAYER 0: PRE-TRADE GATES (UPDATED with regime-aware spread)
# ============================================================

def check_pre_trade_gates(
    regime_info: Dict = None,
    *,
    risk: Optional[RiskDecision] = None,
) -> Dict:
    """Layer 0. Account-level risk, spread and session, before any analysis.

    Args:
        regime_info: The regime snapshot, supplying the spread and its
            regime-specific tolerance.
        risk: A pre-computed risk decision. Computed here when omitted, so that
            a bare ``check_pre_trade_gates()`` is safe rather than permissive.

    Returns:
        The gate result, including ``risk_verdict`` and ``max_new_lots`` so the
        caller can size within the remaining exposure headroom.

    The two parameters this replaced -- ``account_balance: float = 10000`` and
    ``current_daily_loss: float = 0`` -- were the system's worst defect class.
    The only caller invoked ``check_pre_trade_gates(regime_info=...)``, so both
    took their defaults on every one of 39,709 production cycles. The breaker
    evaluated ``0 < -500`` forever and reported "Daily loss OK (0.00 / 500.00)"
    while having no access to the account at all (``PHASE_2_ISSUES.md`` R2, R3).

    They are gone rather than corrected, because a defaulted risk input is an
    assertion the function cannot support. The replacement either reads the real
    state or reports HALT.
    """
    gates_passed = []
    gates_failed = []

    # --- Account-level risk: daily loss, drawdown, exposure, streak ---
    if risk is None:
        if RISK_LIMITS is None:
            risk = RiskDecision(
                RiskVerdict.HALT,
                ("RISK LIMITS UNAVAILABLE: see the startup log",), 0.0)
        else:
            risk = evaluate_risk(account_risk_state(), RISK_LIMITS)
    if risk.verdict is RiskVerdict.ALLOW:
        gates_passed.append(
            f"Account risk OK (headroom {risk.max_new_lots:.2f} lots)")
    else:
        gates_failed.extend(f"{risk.verdict.value}: {b}" for b in risk.breaches)

    # --- Spread -------------------------------------------------------
    # This computed both figures and then compared nothing: the body was
    # replaced by the comment "# DISABLED SPREAD CHECK" and an unconditional
    # pass labelled "[CHECK DISABLED]". Spread is the one cost the strategy
    # pays on every entry and exit, and the regime classifier already publishes
    # a per-regime tolerance (5.0 pip MICRO_SCALP, 7.0 REGIME_SCALP, 10.0
    # INTRADAY_SWING) that nothing consulted.
    #
    # `current_spread` genuinely IS in pips -- mt5_handler.get_current_spread
    # divides by pip size -- unlike the ATR figures elsewhere in this module.
    if regime_info:
        max_spread = regime_info.get("max_spread_pips", 10.0)
        current_spread = regime_info.get("current_spread")
        if current_spread is None:
            # Unknown spread is not an acceptable spread. The old inline default
            # of 0.5 pip asserted a tight market on no evidence.
            gates_failed.append(
                "SPREAD UNKNOWN: regime_info carries no current_spread, so the "
                "entry cost cannot be bounded")
        elif float(current_spread) > float(max_spread):
            gates_failed.append(
                f"SPREAD: {float(current_spread):.1f} pip exceeds the "
                f"{float(max_spread):.1f} pip maximum for this regime")
        else:
            gates_passed.append(
                f"Spread OK ({float(current_spread):.1f} pip within "
                f"{float(max_spread):.1f} pip)")
    else:
        gates_failed.append(
            "SPREAD UNKNOWN: no regime info, so no spread tolerance applies")

    # Session check
    session = get_session_name()
    if session == "DEAD":
        gates_failed.append("DEAD SESSION: no trading between 22:00 and 03:00 UTC")
    else:
        gates_passed.append(f"Session OK ({session})")

    return {
        "all_gates_passed": len(gates_failed) == 0,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "session": session,
        "risk_verdict": risk.verdict.value,
        "max_new_lots": risk.max_new_lots,
    }
# ============================================================
# LAYERS 1-8: SEQUENTIAL ENTRY ANALYSIS (UPDATED)
# ============================================================

def _simple_rsi(closes, period: int = 14) -> float | None:
    """Standard RSI-14 computed directly from a close-price series."""
    try:
        if closes is None or len(closes) < period + 1:
            return None
        delta = closes.diff().dropna()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.rolling(window=period).mean().iloc[-1]
        avg_loss = losses.rolling(window=period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
    except Exception:
        return None


def _check_regime_scalp_momentum(m5_data, side: str, break_reference: float | None, m5_atr: float | None) -> tuple[bool, str]:
    """
    FIX (SCALP-1): REGIME_SCALP momentum-continuation fallback for when price
    breaks out and never pulls back. This is intentionally NOT a bypass like
    MICRO_SCALP's - it substitutes the pullback check for FOUR stricter checks,
    so a momentum entry has to earn its way in rather than skip verification:
      1. Sustained direction (2+ consecutive M5 closes), not a single wick
      2. Real participation (M5 volume above its own 20-candle baseline)
      3. Not already exhausted (RSI in a healthy continuation band, not extreme)
      4. Not overextended (still within 1.2x M5 ATR of the structural break level)
    L6 POI is NOT bypassed for this path - a momentum entry still needs real
    confluence, just without a pullback discount on entry price.
    """
    if m5_data is None or len(m5_data) < 22:
        return False, "Insufficient M5 data for momentum continuation check"

    recent = m5_data.tail(22).reset_index(drop=True)
    try:
        last_close = float(recent["close"].iloc[-1])
        prev_close = float(recent["close"].iloc[-2])
        prev2_close = float(recent["close"].iloc[-3])
    except Exception:
        return False, "Could not read recent M5 closes"

    if side == "BUY":
        sustained = last_close > prev_close > prev2_close
    elif side == "SELL":
        sustained = last_close < prev_close < prev2_close
    else:
        sustained = False
    if not sustained:
        return False, "M5 closes not showing 2+ consecutive moves in the breakout direction"

    try:
        volumes = recent["tick_volume"].tail(21)
        baseline_vol = float(volumes.iloc[:-1].mean())
        current_vol = float(volumes.iloc[-1])
    except Exception:
        return False, "Could not read M5 volume"
    if baseline_vol <= 0 or current_vol < baseline_vol:
        return False, f"M5 volume ({current_vol:.0f}) below 20-candle baseline ({baseline_vol:.0f}) - move lacks participation"

    rsi = _simple_rsi(recent["close"], period=14)
    if rsi is None:
        return False, "Could not compute M5 RSI for momentum check"
    if side == "BUY" and not (55.0 <= rsi <= 75.0):
        return False, f"M5 RSI {rsi:.1f} outside momentum band 55-75 for BUY (too weak or already exhausted)"
    if side == "SELL" and not (25.0 <= rsi <= 45.0):
        return False, f"M5 RSI {rsi:.1f} outside momentum band 25-45 for SELL (too weak or already exhausted)"

    if break_reference is not None and m5_atr:
        # U11. Was the bare literal 0.10 with a comment. The value is right for
        # XAUUSD at 2-decimal quoting, but duplicating broker data inline is how
        # it ends up disagreeing with the specification elsewhere -- and the
        # specification is the thing the sizer already trusts.
        pip_size = XAUUSD_SPEC.pip_size
        distance_pips = abs(last_close - break_reference) / pip_size
        max_allowed_pips = 1.2 * m5_atr / pip_size
        if distance_pips > max_allowed_pips:
            return False, f"Price extended {distance_pips:.1f} pips from break level, exceeds {max_allowed_pips:.1f} pip cap (1.2x M5 ATR) - too late to chase"

    return True, "Momentum continuation confirmed: sustained direction + volume + healthy RSI + not overextended"


def analyze_entry(
    h4_data=None, h1_data=None, m15_data=None,
    m5_data=None, m1_data=None, daily_data=None,
    current_price: float = 0,
    regime_info: Dict = None
) -> Dict:
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "layers_passed": [],
        "layer_failed": None,
        "signal_type": "NO_SIGNAL",
        "entry_signal": None,
        "regime_info": regime_info or {}
    }

    max_intraday_trades = getattr(globals().get("config"), "MAX_INTRADAY_TRADES_PER_DAY", 4)
    if max_intraday_trades > 0:
        trades_today = _count_today_entry_signals()
        if trades_today >= max_intraday_trades:
            analysis["signal_type"] = "PRE_ENTRY"
            analysis["layer_failed"] = "DAILY_LIMIT"
            analysis["fail_reason"] = f"Daily limit reached ({trades_today} trades)"
            return analysis

    if not LAYERS_AVAILABLE or h4_data is None:
        analysis["signal_type"] = "ERROR"
        analysis["fail_reason"] = "Missing data or layers not available"
        return analysis

    try:
        def _bias_to_side(bias_label: str) -> str:
            return "BUY" if str(bias_label).upper() == "BULLISH" else "SELL"

        def _normalize_session_for_conf(session_name: str) -> str:
            s = str(session_name).upper()
            if s in {"LONDON", "LONDON_OPEN"}:
                return "LONDON"
            if s == "NY":
                return "NEWYORK"
            if s == "ASIAN":
                return "ASIAN"
            if s == "DEAD":
                return "DEAD"
            return "OTHER"

        if current_price in (None, 0):
            try:
                if m1_data is not None and len(m1_data) > 0:
                    current_price = float(m1_data.iloc[-1]["close"])
                elif m15_data is not None and len(m15_data) > 0:
                    current_price = float(m15_data.iloc[-1]["close"])
            except Exception:
                current_price = None

        analysis["current_price"] = current_price

        # Use precomputed regime_info (or compute if missing)
        if not regime_info:
            # NOTE: `detect_regime` is deliberately NOT re-imported here.
            # A function-local `from entry_engine import detect_regime` used to
            # sit on this line, shadowing the module-level binding made at
            # main_production.py:76. It was pure redundancy with one real
            # effect: it defeated `patch.object(main_production, "detect_regime")`,
            # so a test could patch the regime and silently get the real
            # classifier instead. tests/test_layer_gate_logic.py was failing for
            # exactly that reason -- it set MICRO_SCALP (L7 threshold 55) and L7
            # read the unpatched regime and applied 70.
            # The main loop at :1528 already calls the module-level name.
            current_spread = 0.5
            try:
                if MT5_AVAILABLE and callable(get_current_spread):
                    current_spread = get_current_spread(CONFIG["symbol"])
            except Exception:
                current_spread = 0.5
            regime_info = detect_regime(m5_data, m15_data, h1_data, current_spread=current_spread)
        analysis["regime_info"] = regime_info

        m5_atr = regime_info.get("m5_atr", 0.0)
        h1_atr = None
        if h1_data is not None and len(h1_data) >= 14:
            ranges_h1 = h1_data["high"].tail(14) - h1_data["low"].tail(14)
            h1_atr = ranges_h1.mean()
        if current_price and h1_atr is not None and m5_atr:
            session_name = get_session_name()
            current_spread = regime_info.get("current_spread", 0.5)
            print_market_snapshot(float(current_price), float(h1_atr), float(m5_atr), session_name, float(current_spread))

        # ============ LAYER 1: BIAS ============
        # FIX (BIAS-2): H4 bias alone was gating ALL regimes identically, including
        # MICRO_SCALP/REGIME_SCALP which don't hold long enough to need H4-level
        # conviction. A choppy multi-day H4 range was blocking every regime at once.
        # Scalp regimes now use the fast H1 bias (bias_engine.get_fast_bias) as the
        # actual gate; H4 bias is still computed and kept as a confluence signal for
        # visibility/future confidence weighting, but no longer blocks scalp entries
        # on its own. INTRADAY_SWING keeps the original strict H4-only gate, since a
        # 150+ pip swing target should wait for real multi-day conviction.
        h4_indicators = calculate_indicators(h4_data) if INDICATORS_AVAILABLE and h4_data is not None and len(h4_data) > 0 else {}
        if h4_data is not None and len(h4_data) >= 2 and "closes_2" not in h4_indicators:
            h4_indicators["closes_2"] = [float(v) for v in h4_data["close"].tail(2).tolist()]
        h4_bias = get_h4_bias(h4_indicators, daily_data=daily_data, h4_data=h4_data) if callable(get_h4_bias) else None

        regime_name = regime_info.get("regime", "UNKNOWN") if regime_info else "UNKNOWN"
        use_fast_bias = regime_name in ("MICRO_SCALP", "REGIME_SCALP")

        if use_fast_bias:
            h1_indicators = calculate_indicators(h1_data) if INDICATORS_AVAILABLE and h1_data is not None and len(h1_data) > 0 else {}
            bias = get_fast_bias(h1_indicators, h1_data=h1_data) if callable(get_fast_bias) else None
            h4_confluence = bool(h4_bias and bias and h4_bias.get("bias") == bias.get("bias") and bias.get("bias") != "NEUTRAL")
            analysis["h4_confluence"] = h4_confluence
            analysis["h4_bias_reference"] = (h4_bias or {}).get("bias", "UNKNOWN")
        else:
            bias = h4_bias
            analysis["h4_confluence"] = None
            analysis["h4_bias_reference"] = (h4_bias or {}).get("bias", "UNKNOWN")

        if not bias or bias.get("bias") == "NEUTRAL":
            analysis["layer_1"] = bias or {}
            analysis["layer_failed"] = "L1_BIAS"
            bias_reason = (bias or {}).get("full_report") or (bias or {}).get("reasoning") or "No bias details available"
            bias_label = "H1 Fast Bias" if use_fast_bias else "H4 Bias"
            analysis["fail_reason"] = f"{bias_label} is NEUTRAL | {bias_reason}"
            analysis["signal_type"] = "PRE_ENTRY"
            print_layer_result(1, bias_label, "BLOCK", "NEUTRAL", bias_reason)
            return analysis
        analysis["layers_passed"].append("L1_BIAS")
        analysis["layer_1"] = bias
        side = _bias_to_side(bias.get("bias", "NEUTRAL"))
        analysis["direction"] = side
        analysis["candidate_entry_style"] = "PULLBACK / MOMENTUM"
        if regime_info:
            analysis["regime_name"] = regime_info.get("regime", "UNKNOWN")

        # ============ LAYER 2: H1 STRUCTURE ============
        struct = get_h1_structure(h1_data, bias["bias"]) if callable(get_h1_structure) and h1_data is not None else None
        analysis["layer_2"] = struct or {}

        struct_type = struct.get("structure_type", "UNKNOWN") if struct else "BROKEN"
        # `h1_atr` here is the mean H1 high-low range in QUOTE CURRENCY (USD),
        # not pips -- see the assignment above. The old message called it "pips",
        # which is U9 in PHASE_2_ISSUES.md. The threshold VALUE is deliberately
        # unchanged here; it is absolute-USD and therefore price-level dependent
        # (it blocked 100.0% of 2017-18 bars and 0.0% of 2026 bars on the real
        # H1 dataset), but correcting that is a measured change -- see Track 2.
        # This commit only stops the output lying about the unit, and stops
        # "indicator unavailable" being reported as "volatility is zero".
        if h1_atr is None:
            # Data/indicator failure, NOT a market observation. Blocking is the
            # safe direction, but calling it "too calm" asserts a volatility
            # measurement that was never taken.
            analysis["layer_failed"] = "L2_STRUCTURE"
            analysis["fail_reason"] = (
                "H1 ATR unavailable (indicator or history failure) - "
                "cannot assess volatility, declining to trade"
            )
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis

        h1_atr_val = float(h1_atr)
        if h1_atr_val < L2_MIN_H1_RANGE_USD:
            analysis["layer_failed"] = "L2_STRUCTURE"
            analysis["fail_reason"] = (
                f"H1 ATR too calm (${h1_atr_val:.2f} < ${L2_MIN_H1_RANGE_USD:.2f}) "
                f"- no volatility to trade"
            )
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis

        # FIX (STRUCTURE-2): Previously a BROKEN structure was pure dead weight - the
        # bot detected a genuine break of structure against its own bias and just
        # discarded it. A confirmed close beyond the last swing high/low, opposite the
        # current bias, is itself a standard, tradeable reversal signal (break of
        # structure). Re-check: if the break is fresh (this candle) and the OPPOSITE
        # direction shows valid structure of its own, flip side/bias and continue the
        # pipeline instead of stalling. Only flips once per pass to avoid oscillation.
        analysis["bos_flip"] = False
        if struct_type == "BROKEN":
            try:
                h1_close = float(h1_data.iloc[-1]["close"]) if h1_data is not None and len(h1_data) > 0 else current_price
            except (TypeError, ValueError):
                h1_close = current_price
            last_high = struct.get("last_swing_high") if struct else None
            last_low = struct.get("last_swing_low") if struct else None

            flipped_side = None
            if side == "SELL" and last_high is not None and h1_close is not None and h1_close > last_high:
                flipped_side = "BUY"
            elif side == "BUY" and last_low is not None and h1_close is not None and h1_close < last_low:
                flipped_side = "SELL"

            if flipped_side:
                flipped_bias_label = "BULLISH" if flipped_side == "BUY" else "BEARISH"
                restruct = get_h1_structure(h1_data, flipped_bias_label) if callable(get_h1_structure) and h1_data is not None else None
                restruct_type = restruct.get("structure_type", "UNKNOWN") if restruct else "BROKEN"

                if restruct_type in ("HH/HL", "LH/LL"):
                    logger.info(
                        f"[L2_STRUCTURE] BOS FLIP: {side} bias invalidated by fresh break "
                        f"({struct.get('break_reason', '')}) - flipping to {flipped_side}, "
                        f"new structure confirmed ({restruct_type})"
                    )
                    side = flipped_side
                    analysis["direction"] = side
                    # P8-15 (`bias`): the flip reverses the direction the pipeline
                    # actually trades, so the L1 label carried forward must reverse
                    # with it. architecture.txt documents this flip as flipping the
                    # bias (760-761); until now only `side` moved, leaving
                    # analysis["layer_1"]["bias"] asserting the abandoned direction.
                    # Mutated in place because analysis["layer_1"] already holds
                    # this same dict, so the reported L1 becomes consistent too.
                    # `bias_strength` is deliberately NOT touched -- that remains
                    # the separate, open P8-15(`bias_strength`) contract question.
                    bias["bias"] = flipped_bias_label
                    analysis["bos_flip"] = True
                    analysis["bos_flip_reason"] = struct.get("break_reason", "")
                    struct = restruct
                    struct_type = restruct_type
                    analysis["layer_2"] = struct or {}
                # else: opposite direction has no confirmed structure yet either -
                # fall through to the normal BROKEN failure below.

        if struct_type == "BROKEN":
            analysis["layer_failed"] = "L2_STRUCTURE"
            analysis["fail_reason"] = f"H1 structure is broken ({struct.get('break_reason', 'no structure confirmation')})"
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis

        if struct_type == "UNKNOWN":
            pass  # proceed with caution
        analysis["layers_passed"].append("L2_STRUCTURE")

        # ============ LAYER 3: M15 PULLBACK ============
        bypass_l3 = bool(regime_info.get("bypass_l3", False)) if regime_info else False

        # D-6OF-2B: L3 evaluates the direction the pipeline is actually trading.
        # `bias` is L1's pre-L2 label and the BOS flip never updates it, so before
        # this change a reversed decision asked L3 to find a retracement of an
        # impulse in the direction the pipeline had just abandoned. `architecture.txt`
        # documents the flip as flipping the bias (760-761) and L3's purpose as
        # "identify quality pullbacks in the direction of the bias" (765); the two
        # compose to the effective side. The BUY/SELL -> BULLISH/BEARISH mapping is
        # the same one the flip block already uses at line 764.
        # This is a strategy-contract change, not a correctness repair. See
        # docs/PHASE_6OF_2_SIDE_BIAS_STATE_AUDIT.md and D-6OB-1/2, D-6OF-2C.
        effective_bias_label = "BULLISH" if side == "BUY" else "BEARISH"
        pullback = get_m15_pullback(m15_data, effective_bias_label) if callable(get_m15_pullback) and m15_data is not None else None
        pullback_quality = pullback.get("pullback_quality", 0.0) if pullback else 0.0
        pullback_detected = pullback.get("pullback_detected", False) if pullback else False
        pullback_reason = pullback.get("reasoning", "No pullback details available") if pullback else "No pullback details available"
        # HISTORICAL RESIDUE -- INERT AT HEAD. Do not read this as an active
        # independent threshold, and do not tune it.
        #   Origin: the gate at c3cf4df was `not pullback or quality < 1.5`, with
        #   1.5 the operative threshold and `pullback_detected` NOT a gate (it
        #   only chose the PRE_ENTRY log line). The value was itself the result of
        #   a deliberate lowering ("FIX #2 (PHASE 5)").
        #   Why it is now inert: the gate below also requires pullback_detected,
        #   and detection requires 0.236 <= retracement <= 0.786, which floors the
        #   base quality at 4.0 with only non-negative bonuses on top. So reaching
        #   the `< MIN_PULLBACK_QUALITY` comparison guarantees quality >= 4.0 and
        #   it can never fire -- measured 0 times in 15,735 decisions (L3-D5).
        #   Retained for historical traceability. The implication that makes it
        #   inert is pinned by tests/backtest/test_l3_quality_invariant.py.
        MIN_PULLBACK_QUALITY = 1.5

        analysis["momentum_fallback"] = False
        if bypass_l3:
            analysis["candidate_entry_style"] = "MOMENTUM"
            analysis["layers_passed"].append("L3_PULLBACK_BYPASSED")
        elif not pullback or not pullback_detected or pullback_quality < MIN_PULLBACK_QUALITY:
            # FIX (SCALP-1): REGIME_SCALP gets one more chance before failing L3 -
            # a strict momentum-continuation check for breakouts that never pull back.
            # Every other regime (including INTRADAY_SWING) still fails here as before.
            momentum_ok = False
            momentum_reason = ""
            if regime_name == "REGIME_SCALP":
                break_reference = struct.get("last_swing_high") if side == "BUY" else struct.get("last_swing_low")
                momentum_ok, momentum_reason = _check_regime_scalp_momentum(
                    m5_data, side, break_reference, regime_info.get("m5_atr") if regime_info else None
                )

            if momentum_ok:
                analysis["candidate_entry_style"] = "MOMENTUM"
                analysis["momentum_fallback"] = True
                analysis["layers_passed"].append("L3_PULLBACK_MOMENTUM")
                logger.info(f"[L3_PULLBACK] REGIME_SCALP momentum fallback: {momentum_reason}")
            else:
                analysis["layer_failed"] = "L3_PULLBACK"
                if regime_name == "REGIME_SCALP" and momentum_reason:
                    analysis["fail_reason"] = f"No pullback ({pullback_reason}) and momentum fallback failed: {momentum_reason}"
                elif not pullback_detected:
                    analysis["fail_reason"] = "No confirmed pullback detected"
                else:
                    analysis["fail_reason"] = f"Pullback quality too low ({pullback_quality:.1f} < {MIN_PULLBACK_QUALITY})"
                analysis["signal_type"] = "PRE_ENTRY"
                return analysis
        else:
            analysis["candidate_entry_style"] = "PULLBACK"
            analysis["layers_passed"].append("L3_PULLBACK")

        # ============ LAYER 4: LIQUIDITY POOLS ============
        pools_result = (
            identify_liquidity_pools(m15_data, h1_data=h1_data, h4_data=h4_data, daily_data=daily_data, current_price=current_price, side=side)
            if callable(identify_liquidity_pools) and m15_data is not None
            else {}
        )
        sweep_pool = pools_result.get("sweep_pool")
        tp_pool = pools_result.get("tp_pool")

        liquidity_assessment = (
            assess_liquidity_gate(sweep_pool, tp_pool, current_price, side)
            if callable(assess_liquidity_gate)
            else {"state": "BLOCK", "reason": "Liquidity assessment unavailable"}
        )
        liquidity_state = liquidity_assessment.get("state", "BLOCK")
        if liquidity_state == "BLOCK":
            analysis["layer_failed"] = "L4_LIQUIDITY"
            analysis["fail_reason"] = liquidity_assessment.get("reason", "Sweep/TP safety checks failed")
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis

        analysis["layers_passed"].append("L4_LIQUIDITY")
        analysis["layer_4"] = {
            "pools_found": len(pools_result.get("liquidity_pools", [])),
            "sweep_pool": sweep_pool,
            "tp_pool": tp_pool,
            "state": liquidity_state,
        }

        # ============ LAYER 5: SWEEP + STRUCTURE ============
        l4_sweep_level = sweep_pool.get("level") if sweep_pool else None
        sweep = (
            get_sweep_and_structure(m15_data, h1_data, l4_sweep_level, side, l4_override_level=l4_sweep_level)
            if callable(get_sweep_and_structure) and m15_data is not None and h1_data is not None
            else None
        )
        sweep_gate_state = sweep.get("gate_state", "BLOCK") if sweep else "BLOCK"
        if sweep_gate_state == "WATCH":
            analysis["layer_failed"] = "L5_SWEEP_WAIT"
            analysis["fail_reason"] = sweep.get("gate_reason", "Sweep not confirmed yet")
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        if not sweep or (not sweep.get("sweep_confirmed") and not sweep.get("choch_confirmed")):
            analysis["layer_failed"] = "L5_SWEEP"
            analysis["fail_reason"] = sweep.get("gate_reason", "No sweep or CHoCH detected")
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis

        if sweep.get("sweep_confirmed"):
            sweep_type = sweep.get("sweep_type", "")
            if side == "BUY" and "bearish" in sweep_type.lower():
                analysis["layer_failed"] = "L5_SWEEP_DIRECTION"
                analysis["fail_reason"] = f"Bearish sweep on BUY signal (sweep_type: {sweep_type})"
                analysis["signal_type"] = "PRE_ENTRY"
                return analysis
            if side == "SELL" and "bullish" in sweep_type.lower():
                analysis["layer_failed"] = "L5_SWEEP_DIRECTION"
                analysis["fail_reason"] = f"Bullish sweep on SELL signal (sweep_type: {sweep_type})"
                analysis["signal_type"] = "PRE_ENTRY"
                return analysis

        analysis["layers_passed"].append("L5_SWEEP")
        analysis["layer_5"] = {
            "sweep_confirmed": sweep.get("sweep_confirmed"),
            "setup_grade": sweep.get("setup_grade"),
            "state": sweep_gate_state,
            "gate_reason": sweep.get("gate_reason"),
        }

        # ============ LAYER 6: POI QUALITY ============
        bypass_l6 = bool(regime_info.get("bypass_l6", False)) if regime_info else False

        poi = (
            identify_poi(m15_data, h1_data=h1_data, direction=side, current_price=current_price)
            if callable(identify_poi) and m15_data is not None
            else {}
        )
        best_poi = poi.get("best_poi")
        analysis["layer_6"] = build_poi_layer_data(poi) if callable(build_poi_layer_data) else {}

        sweep_confirmed = sweep.get("sweep_confirmed", False) if sweep else False
        poi_threshold = 60 if sweep_confirmed else 70

        if bypass_l6:
            analysis["layers_passed"].append("L6_POI_BYPASSED")
        elif not best_poi or best_poi.get("score", 0) < poi_threshold:
            analysis["layer_failed"] = "L6_POI"
            analysis["fail_reason"] = f"POI score too low ({best_poi.get('score', 0):.0f} < {poi_threshold})" if best_poi else "No POI found"
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        else:
            analysis["layers_passed"].append("L6_POI")

        # ============ LAYER 7: CONFIDENCE SCORE ============
        poi_fib = (
            evaluate_poi_fib_confluence(
                h1_data,
                best_poi.get("top") if best_poi else None,
                best_poi.get("bottom") if best_poi else None,
                side,
            )
            if callable(evaluate_poi_fib_confluence)
            else {"has_fib_confluence": False}
        )
        intraday_rsi = _extract_intraday_rsi(m15_data, m5_data)
        conf = (
            get_confidence_engine(
                bias_strength=bias.get("bias_strength", 0.0),
                structure_confidence=struct.get("structure_confidence", 0.0),
                sweep_quality=sweep.get("sweep_quality", 0.0) if sweep else 0.0,
                poi_score=float(best_poi.get("score", 0.0)) if best_poi else 0.0,
                session=_normalize_session_for_conf(get_session_name()),
                structure_valid=bool(struct.get("structure_valid", False)),
                has_fib_confluence=bool(poi_fib.get("has_fib_confluence", False)),
                rsi_value=intraday_rsi,
                regime=regime_info.get("regime", "DEFAULT"),
            )
            if callable(get_confidence_engine)
            else {}
        )
        conf_score = float(conf.get("final_score", 0.0) or 0.0)
        threshold = 55 if regime_info.get("regime") == "MICRO_SCALP" else 70
        # FIX (SCALP-1): momentum-fallback entries (no pullback confirmation) need a
        # higher confidence bar to compensate for the missing L3 confirmation layer.
        if analysis.get("momentum_fallback"):
            threshold = max(threshold, 75)
        if conf_score < threshold:
            analysis["layer_failed"] = "L7_CONFIDENCE"
            analysis["fail_reason"] = f"Confidence score too low ({conf_score:.1f} < {threshold})"
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        analysis["layers_passed"].append("L7_CONFIDENCE")
        conf_grade = conf.get("grade")
        if analysis.get("momentum_fallback") and conf_grade == "A+":
            conf_grade = "A"
        analysis["layer_7"] = {
            "score": conf.get("final_score"),
            "grade": conf_grade,
            "fib_confluence": poi_fib,
            "rsi_value": intraday_rsi,
        }

        # ============ LAYER 8: ENTRY TRIGGERS ============
        # Spread already checked at L0; no need to re-check here.

        confirmed_m5_close = float(m5_data.iloc[-2]["close"]) if m5_data is not None and len(m5_data) >= 2 else float(current_price) if current_price is not None else 0.0
        entry = (
            get_entry_trigger(
                m5_data=m5_data,
                m1_data=m1_data,
                current_price=confirmed_m5_close,
                direction=side,
                sweep_wick_low=sweep.get("sweep_wick_low") if sweep else None,
                sweep_wick_high=sweep.get("sweep_wick_high") if sweep else None,
                regime=regime_info,
                regime_tp_ratio=regime_info.get("tp_ratio", 3.0),
            )
            if callable(get_entry_trigger) and m5_data is not None and m1_data is not None and current_price is not None
            else {}
        )

        if not entry.get("entry_triggered"):
            analysis["layer_failed"] = "L8_ENTRY"
            analysis["fail_reason"] = "Entry triggers not all confirmed"
            analysis["signal_type"] = "PRE_ENTRY"
            analysis["layer_8"] = {
                "setup_type": entry.get("setup_type", "REJECTED"),
                "entry_style": entry.get("entry_style", "NONE"),
                "entry_mode": entry.get("entry_mode", "MARKET"),
                "trigger_type": entry.get("trigger_type", "none"),
                # No RR verdict is recorded: the gate that produced one is
                # retired (docs/VALID_RR_CONTRACT.md). The geometry it was
                # derived from is reported instead, which is what a reader
                # needs and what the verdict never added to.
                "tp_ratio": regime_info.get("tp_ratio"),
                "risk_distance": entry.get("risk_distance"),
                "reward_distance": entry.get("reward_distance"),
                "rr": entry.get("reward_to_risk_ratio", 0),
                "entry_triggered": False,
            }
            print_layer_result(8, "Entry Trigger", "WAIT", f"Setup: {entry.get('setup_type', 'REJECTED')} | waiting for M5/M1 confirmation")
            return analysis

        gate_result = evaluate_entry_for_regime(entry, regime_info)
        if not gate_result.get("entry_allowed", False):
            analysis["layer_failed"] = "L8_ENTRY"
            analysis["fail_reason"] = gate_result.get("reason", "entry quality gate failed")
            analysis["signal_type"] = "PRE_ENTRY"
            analysis["layer_8"] = {
                "setup_type": entry.get("setup_type", "REJECTED"),
                "trigger_type": entry.get("trigger_type"),
                "entry_style": entry.get("entry_style", "NONE"),
                "entry_mode": entry.get("entry_mode", "MARKET"),
                "tp_ratio": regime_info.get("tp_ratio"),
                "rr": entry.get("reward_to_risk_ratio"),
                "entry_triggered": False,
                "gate_reason": gate_result.get("reason"),
            }
            return analysis

        analysis["layers_passed"].append("L8_ENTRY")
        analysis["layer_8"] = {
            "setup_type": entry.get("setup_type", "REJECTED"),
            "trigger_type": entry.get("trigger_type"),
            "entry_style": entry.get("entry_style", "NONE"),
            "entry_mode": entry.get("entry_mode", "MARKET"),
            "tp_ratio": regime_info.get("tp_ratio"),
            "rr": entry.get("reward_to_risk_ratio"),
            "entry_triggered": True,
            "recommended_mode": gate_result.get("recommended_mode"),
        }
        print_layer_result(8, "Entry Trigger", "PASS", f"{entry.get('setup_type', 'REJECTED')} | {entry.get('entry_style', 'NONE')} confirmed (RR: 1:{entry.get('reward_to_risk_ratio', 0):.1f})")

        # ============ ALL LAYERS PASSED - ENTRY SIGNAL ============
        analysis["signal_type"] = "ENTRY_SIGNAL"
        l6_data = analysis.get("layer_6", {})
        risk_pct = regime_info.get("risk_percent", 1.0)
        analysis["entry_signal"] = {
            # D-6OF-2A: the order direction must be the one the geometry was
            # built for. `entry_price`, `stop_loss` and `take_profit` below all
            # come from `entry`, which L8 produced for `side` -- the effective
            # direction after any L2 BOS reversal. `bias` is the *pre-reversal*
            # label and is never updated by the flip, so deriving the order side
            # from it meant a reversed decision would have opened a trade in the
            # original direction carrying a stop and target for the opposite one.
            # `replay_engine` reads this field and nothing else to set the side.
            # Never observed: no reversal has reached a signal. See
            # docs/PHASE_6OF_2_SIDE_BIAS_STATE_AUDIT.md.
            "position_type": side,
            "entry_price": entry.get("entry_price", 0),
            "stop_loss": entry.get("stop_loss", 0),
            "take_profit": entry.get("take_profit", 0),
            "rr_ratio": entry.get("reward_to_risk_ratio", 0),
            "grade": conf.get("grade", "A"),
            "setup_type": entry.get("setup_type", "REJECTED"),
            "entry_method": entry.get("entry_style", "NONE"),
            "entry_mode": entry.get("entry_mode", "MARKET"),
            "trigger_type": entry.get("trigger_type", "none"),
            "tp_ratio": regime_info.get("tp_ratio"),
            "risk_distance": entry.get("risk_distance"),
            "reward_distance": entry.get("reward_distance"),
            # Carried so execution can rest a LIMIT_FVG order without the
            # strategy knowing anything about how orders are filled.
            "limit_price": entry.get("limit_price"),
            "fvg_zone_low": entry.get("fvg_zone_low"),
            "fvg_zone_high": entry.get("fvg_zone_high"),
            "poi_type": l6_data.get("poi_type", "N/A") if isinstance(l6_data, dict) else "N/A",
            "risk_percent": risk_pct,
            "timestamp": datetime.now().isoformat()
        }

        logger.info("[ENTRY] ENTRY SIGNAL GENERATED:")
        logger.info(f"   Position: {analysis['entry_signal']['position_type']}")
        logger.info(f"   Setup: {analysis['entry_signal']['setup_type']} | Method: {analysis['entry_signal']['entry_method']} | Mode: {analysis['entry_signal']['entry_mode']} | Trigger: {analysis['entry_signal']['trigger_type']}")
        logger.info(f"   Entry: {analysis['entry_signal']['entry_price']:.2f}")
        logger.info(f"   SL: {analysis['entry_signal']['stop_loss']:.2f}")
        logger.info(f"   TP: {analysis['entry_signal']['take_profit']:.2f}")
        logger.info(f"   RR: {analysis['entry_signal']['rr_ratio']:.1f}:1 ({analysis['entry_signal']['grade']} grade)")

    except Exception as e:
        analysis["layer_failed"] = "ERROR"
        analysis["fail_reason"] = str(e)
        logger.error(f"Error in entry analysis: {e}", exc_info=True)
        if monitor:
            monitor.log_error("ENTRY_ANALYSIS_ERROR", str(e), ErrorSeverity.ERROR)

    return analysis

# ============================================================
# ORDER EXECUTION
# ============================================================

def _live_symbol_specification():
    """Build the traded symbol's specification from the broker, or ``None``.

    The specification is read from the terminal rather than assumed, because
    the economics differ per instrument and per broker: which formula applies
    is decided by the symbol's calculation mode, which only the broker knows.

    Returns:
        A ``SymbolSpecification``, or ``None`` if the terminal or the symbol is
        unavailable, or the instrument's calculation mode is unsupported. The
        caller must decline to trade rather than guess.
    """
    if not MT5_AVAILABLE:
        return None
    try:
        from core.symbols import SymbolSpecification

        info = mt5.symbol_info(CONFIG["symbol"])
        if info is None:
            logger.error(f"[SIZING] symbol_info({CONFIG['symbol']}) returned None")
            return None
        return SymbolSpecification.from_mt5_symbol_info(
            info, pip_size=CONFIG.get("pip_size", 0.10)
        )
    except Exception as exc:
        logger.error(f"[SIZING] Could not build a symbol specification: {exc}")
        return None


def realised_pnl(trade: Dict, exit_price: float, spec=None) -> Optional[float]:
    """Realised P&L for a closed trade, in account currency.

    Nothing in this system tracked realised P&L (``PHASE_2_ISSUES.md`` R4), so
    no component could answer "is the account down today?" -- which is why the
    daily-loss breaker had nothing to evaluate even once it was wired up.

    Args:
        trade: The trade record. Needs ``entry_price``, ``position_size`` and
            ``position_type``.
        exit_price: The price the position closed at.
        spec: The instrument specification. Fetched from the broker when omitted.

    Returns:
        P&L in account currency, or ``None`` when it cannot be computed. ``None``
        is **not** zero: a trade whose P&L is unknown must not be silently
        counted as flat, because that understates the day's loss.
    """
    try:
        spec = spec if spec is not None else _live_symbol_specification()
        if spec is None:
            logger.error(
                "[PNL] No symbol specification; cannot value the close of "
                f"{trade.get('trade_id')}. Reporting unknown rather than zero."
            )
            return None
        entry = float(trade["entry_price"])
        volume = float(trade["position_size"])
        side = str(trade["position_type"]).upper()
        move = float(exit_price) - entry
        if side in ("SELL", "SHORT"):
            move = -move
        elif side not in ("BUY", "LONG"):
            logger.error(f"[PNL] Unknown position_type {side!r}; cannot sign the move")
            return None
        # contract_size-derived, NOT tick-derived: the broker reports
        # tick_value/tick_size disagreeing with contract_size by 10x on this
        # symbol. See SymbolSpecification.money_per_price_unit.
        return move * spec.money_per_price_unit(volume)
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(f"[PNL] Could not value the close of {trade.get('trade_id')}: {exc}")
        return None


def account_risk_state() -> Optional[AccountRiskState]:
    """Assemble the account's risk state from the broker and the trade history.

    Read-only: ``account_info`` and ``positions_get`` only. No order is placed
    and no account setting is touched.

    Returns:
        The state, or ``None`` when it cannot be established. ``None`` makes
        :func:`core.risk_limits.evaluate` return ``HALT``; it is never treated as
        a flat account. That inversion is the whole point -- the defect being
        fixed here was a default that asserted "no loss today" on a function
        that had no way to know.
    """
    if not MT5_AVAILABLE:
        logger.warning("[RISK] MT5 unavailable; account state cannot be read")
        return None
    try:
        info = mt5.account_info()
        if info is None:
            logger.error("[RISK] account_info() returned None")
            return None

        positions = mt5.positions_get(symbol=CONFIG["symbol"]) or ()
        open_lots = float(sum(float(pos.volume) for pos in positions))

        closed = load_closed_trades() if PERSISTENCE_AVAILABLE else []

        return build_risk_state(
            balance=float(info.balance),
            equity=float(info.equity),
            closed_trades=closed,
            open_positions=len(positions),
            open_lots=open_lots,
            now=datetime.now(timezone.utc),
        )
    except (RiskLimitError, AttributeError, TypeError, ValueError) as exc:
        logger.error(f"[RISK] Could not establish account state: {exc}")
        return None


def execute_entry_signal(
    entry_signal: Dict,
    account_balance: Optional[float] = None,
    *,
    max_lots: Optional[float] = None,
) -> Optional[str]:
    """Size and submit one entry signal.

    Args:
        entry_signal: The signal to act on.
        account_balance: The **broker's** balance. ``None`` declines the trade.
            This parameter previously defaulted to ``10000`` and the only caller
            passed nothing, so every position in the system was sized against a
            fictional account (``PHASE_2_ISSUES.md`` R2).
        max_lots: Exposure headroom in lots, from the account risk gate. The
            size is capped at this. ``core.sizing`` cannot apply it -- it caps at
            the broker's ``volume_max``, which is far larger than any limit this
            project sets (R6, R8).

    Returns:
        The order id, or ``None`` if the trade was declined.
    """
    if not entry_signal or not order_executor:
        return None

    if account_balance is None:
        logger.error(
            "[SIZING] No account balance available; declining to trade. "
            "Sizing against an assumed balance is how every risk figure in "
            "this system came to be fictional."
        )
        return None

    try:
        risk_pct = entry_signal.get("risk_percent", 1.0)

        # One sizing implementation, and the instrument comes from the broker.
        # This replaced two formulas that disagreed by a factor of ten -- the
        # risk_manager branch divided by 10.0 and this branch's fallback by
        # 100.0, for the same symbol. See docs/SIZING_CONTRACT.md.
        spec = _live_symbol_specification()
        if spec is None:
            logger.error(
                "[SIZING] No symbol specification available; declining to size. "
                "Instrument economics must not be assumed."
            )
            return None

        position_size = calculate_lot_size_for_symbol(
            CONFIG["symbol"],
            account_balance,
            risk_pct,
            entry_signal["entry_price"],
            entry_signal["stop_loss"],
            spec=spec,
        )
        # Exposure headroom. Applied AFTER the risk-based size so the trade is
        # reduced to fit the account's remaining capacity rather than sized up
        # to it -- the cap is a ceiling, never a target.
        if max_lots is not None and position_size > max_lots:
            logger.info(
                f"[SIZING] risk budget allowed {position_size:.2f} lots; "
                f"capped to {max_lots:.2f} by the account exposure limit"
            )
            position_size = max_lots

        if position_size <= 0.0:
            # The budget cannot buy a tradeable size. Declining is the whole
            # point: raising it to the minimum would exceed the risk budget.
            logger.warning(
                f"[SIZING] Risk budget affords no tradeable size "
                f"(balance={account_balance}, risk={risk_pct}%, "
                f"stop_distance={abs(entry_signal['entry_price'] - entry_signal['stop_loss'])}). "
                f"No order placed."
            )
            return None

        order = order_executor.create_order(
            order_type=OrderType.BUY if entry_signal["position_type"] == "BUY" else OrderType.SELL,
            entry_price=entry_signal["entry_price"],
            stop_loss=entry_signal["stop_loss"],
            take_profit=entry_signal["take_profit"],
            position_size=position_size,
            signal_grade=entry_signal.get("grade", "A"),
            confidence_score=80.0,
            metadata={
                "setup_type": entry_signal.get("setup_type", "REJECTED"),
                "entry_mode": entry_signal.get("entry_mode", "UNKNOWN"),
                "session": get_session_name()
            }
        )

        success, message = order_executor.execute_order(
            order["order_id"],
            mt5_handler=None,
            simulation=CONFIG["demo_mode"]
        )

        if success:
            logger.info(f"[+] Order executed: {order['order_id']}")
            trade = {
                "trade_id": order["order_id"],
                "order_id": order["order_id"],
                "entry_price": order["entry_price"],
                "stop_loss": order["stop_loss"],
                "take_profit": order["take_profit"],
                "position_type": order["order_type"],
                "entry_time": datetime.now().isoformat(),
                "status": "OPEN",
                "position_size": order["position_size"],
                "state": None
            }
            _OPEN_TRADES.append(trade)
            if monitor:
                monitor.metrics["orders_created"] += 1
                monitor.metrics["orders_executed"] += 1
            return order["order_id"]
        else:
            logger.error(f"[-] Order execution failed: {message}")
            if monitor:
                monitor.log_error("ORDER_EXECUTION_FAILED", message, ErrorSeverity.ERROR)
            return None

    except Exception as e:
        logger.error(f"Error executing entry signal: {e}")
        if monitor:
            monitor.log_error("SIGNAL_EXECUTION_ERROR", str(e), ErrorSeverity.ERROR)
        return None

# ============================================================
# POSITION MANAGEMENT (Layer 9)
# ============================================================

def manage_positions(current_prices: Dict) -> None:
    global _OPEN_TRADES
    closed_trades = []
    for trade in _OPEN_TRADES:
        try:
            if "order_id" not in trade:
                trade["order_id"] = f"{trade.get('trade_id', 'UNKNOWN')}_auto_{int(time.time())}"
                logger.debug(f"[AUTO_FIX] Generated order_id for {trade.get('trade_id')}")
            current_price = current_prices.get(trade["trade_id"], trade.get("entry_price", 0))
            if order_executor:
                result = order_executor.update_current_price(trade["order_id"], current_price)
                for action in result.get("actions", []):
                    if action["action"] == "CLOSE_50PCT":
                        logger.info(f"[{trade['trade_id']}] 1:1 RR: Close 50% @ {current_price:.2f}")
                    elif action["action"] == "TRAIL_SL":
                        logger.info(f"[{trade['trade_id']}] 1:2 RR: Trail SL")
                    elif action["action"] == "CLOSE_ALL":
                        logger.info(f"[{trade['trade_id']}] TP: Close all @ {current_price:.2f}")
                        _record_close(trade, current_price, "CLOSE_ALL")
                        closed_trades.append(trade)
            trade["last_check"] = datetime.now().isoformat()
        except Exception as e:
            logger.error(f"Error managing position {trade.get('trade_id')}: {e}")

    _OPEN_TRADES = [t for t in _OPEN_TRADES if t not in closed_trades]


def _record_close(trade: Dict, exit_price: float, reason: str) -> None:
    """Value a closing position and persist it, so the risk gate has a source.

    Closed trades were simply dropped from ``_OPEN_TRADES``: no P&L was computed
    and ``save_closed_trade`` was never called, so nothing in the system could
    answer "is the account down today?" (``PHASE_2_ISSUES.md`` R4). The
    daily-loss breaker and the drawdown kill switch both read this history.

    A trade whose P&L cannot be computed is persisted with ``pnl = None``, which
    :func:`core.risk_limits.realised_pnl_for_day` treats as a hard error rather
    than as zero -- an unknown loss must not read as no loss.
    """
    pnl = realised_pnl(trade, exit_price)
    trade["exit_price"] = float(exit_price)
    trade["exit_time"] = datetime.now(timezone.utc).isoformat()
    trade["exit_reason"] = reason
    trade["pnl"] = pnl
    trade["status"] = "CLOSED"
    if pnl is None:
        logger.error(
            f"[PNL] {trade.get('trade_id')} closed at {exit_price:.2f} but its "
            f"P&L could not be computed. Recorded as unknown; the risk gate "
            f"will refuse to evaluate the day rather than assume it was flat."
        )
    else:
        logger.info(
            f"[PNL] {trade.get('trade_id')} closed at {exit_price:.2f} "
            f"for {pnl:+.2f}"
        )
    if PERSISTENCE_AVAILABLE:
        try:
            save_closed_trade(trade)
        except Exception as exc:
            logger.error(f"[PNL] Could not persist the close: {exc}")
    if LAYERS_AVAILABLE:
        try:
            log_closed_trade(trade)
        except Exception as exc:
            logger.debug(f"[PNL] feedback_loop.log_closed_trade declined: {exc}")

# ============================================================
# PERSISTENCE
# ============================================================

def save_state() -> bool:
    if not PERSISTENCE_AVAILABLE:
        return False
    try:
        if _OPEN_TRADES:
            save_active_trades(_OPEN_TRADES)
        return True
    except Exception as e:
        logger.error(f"Error saving state: {e}")
        return False

def restore_state() -> bool:
    global _OPEN_TRADES
    if not PERSISTENCE_AVAILABLE:
        return False
    try:
        _OPEN_TRADES = load_active_trades()
        if _OPEN_TRADES:
            logger.info(f"[+] Restored {len(_OPEN_TRADES)} open trades from disk")
        return True
    except Exception as e:
        logger.error(f"Error restoring state: {e}")
        return False

# ============================================================
# SHUTDOWN
# ============================================================

def graceful_shutdown():
    global _SHOULD_CONTINUE
    logger.info("\n" + "="*70)
    logger.info("GRACEFUL SHUTDOWN INITIATED")
    logger.info("="*70)
    _SHOULD_CONTINUE = False

    # ----------------------------------------------------------------
    # Shutdown position closing -- GATED.
    #
    # This block previously called mt5.positions_get() and then
    # mt5.order_send() against EVERY open position on the symbol, with no
    # ownership check and no safety guard, on SIGINT/SIGTERM (:signal_handler)
    # and on normal loop exit. main_production.py has no working opening path,
    # so every position it could have found belonged to something else.
    #
    # It was previously unreachable only because CONFIG["demo_mode"] = False
    # made the process refuse to start. Setting demo_mode = True so the bot can
    # run in SIMULATION turned that accident into a live hazard on every Ctrl-C,
    # so the same four guards main.py uses (commit f5d17f5, Phase 6G R1) apply
    # here. Any one of them stops every order.
    # ----------------------------------------------------------------
    try:
        if not CLOSE_POSITIONS_ON_SHUTDOWN:
            logger.info("[SHUTDOWN] position closing disabled "
                        "(CLOSE_POSITIONS_ON_SHUTDOWN is False); no orders sent")
        elif not LIVE_TRADING_ENABLED:
            logger.info("[SHUTDOWN] live trading disabled by core.safety; "
                        "no orders sent")
        elif not MT5_AVAILABLE:
            pass
        elif not _OWNED_TICKETS:
            logger.info("[SHUTDOWN] this process opened no positions; "
                        "no orders sent")
        else:
            positions = mt5.positions_get(symbol=CONFIG["symbol"])
            if positions:
                logger.info(f"Closing {len(positions)} position(s)...")
                for pos in positions:
                    if pos.ticket not in _OWNED_TICKETS:
                        logger.info(f"[SHUTDOWN] skipping ticket {pos.ticket}: "
                                    "not opened by this process")
                        continue
                    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    close_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": CONFIG["symbol"],
                        "volume": pos.volume,
                        "type": close_type,
                        "position": pos.ticket
                    }
                    result = mt5.order_send(close_request)
                    logger.info(f"[+] Position {pos.ticket} closed" if result.retcode == mt5.TRADE_RETCODE_DONE else f"[-] Failed: {result.comment}")
    except Exception as e:
        logger.warning(f"Error closing MT5 positions: {e}")

    save_state()
    if MT5_AVAILABLE:
        shutdown_mt5()
    if shutdown_mgr:
        shutdown_mgr.shutdown(_OPEN_TRADES, monitor)
    logger.info("="*70)
    logger.info("[SHUTDOWN] COMPLETE")
    logger.info("="*70)

def signal_handler(sig, frame):
    logger.info("[SIGNAL] Shutdown signal received")
    graceful_shutdown()
    sys.exit(0)

# ============================================================
# MAIN BOT LOOP
# ============================================================

def main():
    global _SHOULD_CONTINUE, _OPEN_TRADES

    logger.info("\n" + "="*70)
    logger.info("[BOT] PRODUCTION TRADING BOT STARTING")
    logger.info("="*70)

    logger.info(f"Symbol: {CONFIG['symbol']}")
    logger.info(f"Mode: {'DEMO' if CONFIG['demo_mode'] else 'LIVE'}")
    # Report the limits that are actually ENFORCED. This previously printed
    # CONFIG["max_daily_loss_percent"] (5.0%), which nothing read -- the gate
    # that was supposed to apply it could not fire. Printing an unenforced
    # number is worse than printing none: it is where the operator's belief
    # that the account was protected came from.
    if RISK_LIMITS is None:
        logger.critical(
            "RISK LIMITS UNAVAILABLE -- every pre-trade gate will BLOCK")
    else:
        logger.info(
            f"Risk limits (enforced): "
            f"daily loss {RISK_LIMITS.max_daily_loss.value:.1f}% | "
            f"drawdown HALT {RISK_LIMITS.max_drawdown.value:.1f}% | "
            f"max {RISK_LIMITS.max_open_lots:.2f} lots open "
            f"({RISK_LIMITS.max_lots_per_position:.2f}/position) | "
            f"{RISK_LIMITS.max_concurrent_positions} concurrent | "
            f"{RISK_LIMITS.max_consecutive_losses} consecutive losses | "
            f"time stop {RISK_LIMITS.max_hold}"
        )
    logger.info(f"Layers Available: {LAYERS_AVAILABLE}")
    logger.info(f"MT5 Available: {MT5_AVAILABLE}")
    logger.info(f"Persistence Available: {PERSISTENCE_AVAILABLE}")
    logger.info(f"Order Execution Available: {EXECUTION_AVAILABLE}")
    logger.info(f"Error Recovery Available: {ERROR_RECOVERY_AVAILABLE}")

    initialize_production_components()

    # ----------------------------------------------------------------
    # PHASE 0.3: EXECUTION SAFETY GATE
    #
    # Runs before any state is restored, before MT5 is contacted, and before
    # the decision loop starts. It either returns a validated execution state
    # or raises -- there is no boolean for the caller to ignore.
    #
    # This is the check whose absence let the bot run 39,709 decision cycles
    # reporting "Mode: LIVE" while being structurally incapable of placing an
    # order. Refusing to start is the correct behaviour: a trading process that
    # believes it is live must either be able to trade or stop.
    #
    # Live trading is disabled unconditionally for Phase 0/1. There is no
    # environment variable, config key, or flag that re-enables it; see
    # core/safety.py for why that is deliberate.
    # ----------------------------------------------------------------
    assert_live_trading_disabled()
    execution_mode = resolve_execution_mode(
        demo_mode=CONFIG["demo_mode"],
        execution_available=EXECUTION_AVAILABLE,
    )
    try:
        execution_state = validate_execution_environment(
            mode=execution_mode,
            order_executor=order_executor,
            broker_handler=None,  # No broker adapter exists yet; Phase 2 work.
        )
    except UnsafeExecutionStateError as exc:
        logger.critical("=" * 70)
        logger.critical("STARTUP REFUSED - UNSAFE EXECUTION STATE")
        logger.critical("=" * 70)
        for line in str(exc).splitlines():
            logger.critical(line)
        logger.critical("=" * 70)
        raise

    logger.info(f"[SAFETY] {describe_execution_state(execution_state)}")

    restore_state()

    signal_module.signal(signal_module.SIGINT, signal_handler)
    signal_module.signal(signal_module.SIGTERM, signal_handler)

    if MT5_AVAILABLE and not CONFIG["demo_mode"]:
        logger.info("Connecting to MT5...")
        if not connect_mt5():
            logger.error("Failed to connect to MT5")
            return

    logger.info("="*70)
    logger.info("[READY] BOT READY - Waiting for trading opportunities")
    logger.info("="*70 + "\n")

    iteration_count = 0

    while _SHOULD_CONTINUE:
        try:
            iteration_count += 1

            # ----------------------------------------------------
            # 1. FETCH ALL DATA
            # ----------------------------------------------------
            if MT5_AVAILABLE and not CONFIG["demo_mode"]:
                h4_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H4, CONFIG["h4_candles_required"])
                h1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H1, CONFIG["h1_candles_required"])
                m15_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M15, CONFIG["m15_candles_required"])
                m5_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M5, CONFIG["m5_candles_required"])
                m1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M1, CONFIG["m1_candles_required"])
                daily_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_D1, 10)
            else:
                h4_data = h1_data = m15_data = m5_data = m1_data = daily_data = None

            try:
                current_price = get_current_price(CONFIG["symbol"]) if MT5_AVAILABLE else 0
            except Exception:
                current_price = 0

            # ----------------------------------------------------
            # 2. COMPUTE REGIME (EARLY) AND CHECK SPREAD
            # ----------------------------------------------------
            regime_info = None
            if LAYERS_AVAILABLE and m5_data is not None and m15_data is not None and h1_data is not None:
                current_spread = 0.5
                try:
                    if MT5_AVAILABLE and callable(get_current_spread):
                        current_spread = get_current_spread(CONFIG["symbol"])
                except Exception:
                    current_spread = 0.5
                regime_info = detect_regime(m5_data, m15_data, h1_data, current_spread=current_spread)

            # L0 Gates now include spread check
            # Read the account ONCE per cycle and reuse it: the gate, the time
            # stop and the sizer must all see the same snapshot, or they can
            # disagree about whether the account is allowed to trade.
            risk_state = account_risk_state()
            risk_decision = (
                evaluate_risk(risk_state, RISK_LIMITS) if RISK_LIMITS is not None
                else RiskDecision(RiskVerdict.HALT,
                                  ("RISK LIMITS UNAVAILABLE: see the startup log",),
                                  0.0)
            )
            gate_check = check_pre_trade_gates(regime_info=regime_info,
                                               risk=risk_decision)

            # ----------------------------------------------------
            # TIME STOP (config.INTRADAY_MAX_HOLD_MINUTES)
            #
            # Defined since it was written and enforced nowhere. Runs before the
            # gate's `continue`, so positions are still timed out while new
            # entries are blocked -- a halted account must still be able to
            # exit, or a drawdown breach would freeze its positions open.
            # ----------------------------------------------------
            try:
                for trade_id, held in overdue_positions(
                    _OPEN_TRADES, now=datetime.now(timezone.utc),
                    max_hold=RISK_LIMITS.max_hold if RISK_LIMITS else None,
                ):
                    logger.warning(
                        f"[TIME_STOP] {trade_id} held {held} >= "
                        f"{RISK_LIMITS.max_hold}; flagged for exit"
                    )
                    for trade in _OPEN_TRADES:
                        if str(trade.get("trade_id")) == trade_id:
                            trade["time_stop_due"] = True
            except RiskLimitError as exc:
                logger.error(f"[TIME_STOP] {exc}")

            if not gate_check["all_gates_passed"]:
                # Every failure is logged, not just spread ones. The previous
                # branch logged only when "SPREAD" appeared in the reasons, so a
                # daily-loss or drawdown breach would have blocked trading
                # silently -- the operator would see nothing at all.
                logger.warning(
                    f"[L0] Trading blocked ({gate_check['risk_verdict']}): "
                    f"{gate_check['gates_failed']}"
                )
                time.sleep(5)
                continue

            # ----------------------------------------------------
            # 3. ENTRY ANALYSIS (pass regime_info)
            # ----------------------------------------------------
            if len(_OPEN_TRADES) < CONFIG["max_concurrent_trades"]:
                analysis = analyze_entry(
                    h4_data, h1_data, m15_data, m5_data, m1_data, daily_data,
                    current_price, regime_info=regime_info
                )
                print_run_summary(analysis)

                l6_data = analysis.get("layer_6", {})
                l6_poi_type = l6_data.get("poi_type", "N/A") if l6_data else "N/A"
                l6_poi_score = l6_data.get("score", "N/A") if l6_data else "N/A"

                log_signal({
                    "timestamp": analysis.get("timestamp"),
                    "signal_type": analysis.get("signal_type"),
                    "layers_passed": ",".join(analysis.get("layers_passed", [])),
                    "layer_failed": analysis.get("layer_failed", ""),
                    "fail_reason": analysis.get("fail_reason", ""),
                    "l6_poi_type": l6_poi_type,
                    "l6_poi_score": l6_poi_score,
                    "entry_grade": analysis.get("entry_signal", {}).get("grade") if analysis.get("entry_signal") else "N/A",
                    "setup_type": analysis.get("entry_signal", {}).get("setup_type") if analysis.get("entry_signal") else analysis.get("layer_8", {}).get("setup_type", "N/A"),
                    "entry_method": analysis.get("entry_signal", {}).get("entry_method") if analysis.get("entry_signal") else "N/A",
                    "entry_mode": analysis.get("entry_signal", {}).get("entry_mode") if analysis.get("entry_signal") else "N/A",
                    "trigger_type": analysis.get("entry_signal", {}).get("trigger_type") if analysis.get("entry_signal") else "N/A",
                    "rr_valid": analysis.get("entry_signal", {}).get("rr_valid") if analysis.get("entry_signal") else "N/A",
                    "entry_price": analysis.get("entry_signal", {}).get("entry_price") if analysis.get("entry_signal") else "N/A",
                    "stop_loss": analysis.get("entry_signal", {}).get("stop_loss") if analysis.get("entry_signal") else "N/A",
                    "take_profit": analysis.get("entry_signal", {}).get("take_profit") if analysis.get("entry_signal") else "N/A",
                    "rr_ratio": analysis.get("entry_signal", {}).get("rr_ratio") if analysis.get("entry_signal") else "N/A",
                    "session": gate_check.get("session", ""),
                    "position_type": analysis.get("entry_signal", {}).get("position_type") if analysis.get("entry_signal") else "N/A",
                    "order_id": ""
                })

                if analysis.get("signal_type") == "ENTRY_SIGNAL":
                    # R2: the balance is the BROKER's, not the hardcoded
                    # 10000 default that made every risk figure fictional.
                    # R6/R8: cap the size at the headroom the exposure limit
                    # leaves, which core.sizing does not know about -- it caps
                    # at the broker's volume_max, a far larger limit.
                    order_id = execute_entry_signal(
                        analysis["entry_signal"],
                        account_balance=risk_state.balance if risk_state else None,
                        max_lots=gate_check["max_new_lots"],
                    )
                    if order_id:
                        logger.info(f"[+] Trade #{len(_OPEN_TRADES)} opened: {order_id}")

            # ----------------------------------------------------
            # 4. MANAGE OPEN POSITIONS
            # ----------------------------------------------------
            manage_positions({})

            if iteration_count % 10 == 0:
                save_state()

            if monitor and iteration_count % 60 == 0:
                status = monitor.check_health()
                logger.debug(f"System health: {status.value}")

            time.sleep(5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            if monitor:
                monitor.log_error("MAIN_LOOP_ERROR", str(e), ErrorSeverity.CRITICAL)
            time.sleep(5)

    graceful_shutdown()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)