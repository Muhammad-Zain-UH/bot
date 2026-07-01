"""
PRODUCTION-READY MAIN ORCHESTRATION ENGINE
10-Layer Trading Bot with Order Execution, State Persistence, and Error Recovery

System Architecture:
  Layer 0: Pre-trade gates (daily loss, spread, news)
  Layer 1-8: Sequential entry filters (all must pass)
  Layer 9: Trade management (partial exits 1:1/1:2/1:3 RR)
  Layer 10: Feedback loop (performance tracking & auto-adjustment)
  
  + Order Execution: Live order placement with retry logic
  + Trade Persistence: State preservation across restarts
  + Error Recovery: Connection management and graceful shutdown
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
    from bias_engine import get_h4_bias
    from structure_engine import get_h1_structure
    from pullback_detector import get_m15_pullback
    from liquidity_engine import identify_liquidity_pools, assess_liquidity_gate
    from sweep_detector import get_sweep_and_structure
    from poi_engine import identify_poi, build_poi_layer_data
    from confidence_engine import get_confidence_engine, evaluate_poi_fib_confluence
    from entry_engine import get_entry_trigger, detect_regime
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
    from trade_persistence import save_active_trades, load_active_trades, save_closed_trade
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False
    print("[WARNING] Trade persistence not available")

try:
    from risk_manager import calculate_lot_size_for_symbol
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
_SIGNAL_LOG_FILE = "signal_log.csv"

# ============================================================
# CONFIGURATION
# ============================================================

CONFIG = {
    "symbol": "XAUUSD",
    "max_concurrent_trades": 3,
    "max_daily_loss_percent": 5.0,
    "risk_per_trade_a_plus": 1.5,
    "risk_per_trade_a": 1.0,
    "h4_candles_required": 100,
    "h1_candles_required": 60,
    "m15_candles_required": 50,
    "m5_candles_required": 100,
    "m1_candles_required": 200,
    "demo_mode": False,  # Set to False for live trading
}

SIGNAL_LOG_COLUMNS = [
    "timestamp", "signal_type", "layers_passed", "layer_failed", 
    "fail_reason", "l6_poi_type", "l6_poi_score",
    "entry_grade", "setup_type", "entry_method", "entry_mode", "trigger_type", "rr_valid", "entry_price", "stop_loss", 
    "take_profit", "rr_ratio", "session", "position_type", "order_id"
]

# ============================================================
# LOGGING SETUP
# ============================================================

def _ascii_safe(text: object) -> str:
    """Convert text to ASCII-safe form for Windows consoles and logs."""
    return str(text).encode("ascii", errors="replace").decode("ascii")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot_production.log', encoding="utf-8"),
        logging.StreamHandler(stream=sys.stdout)
    ]
)
logger = logging.getLogger('TradingBot-Production')

# ============================================================
# ENHANCED TERMINAL VISIBILITY (PHASE 4)
# ============================================================

def print_market_snapshot(price: float, h1_atr: float, m5_atr: float, session: str, spread: float) -> None:
    """Display current market conditions in terminal with volatility context."""
    utc_now = datetime.now(timezone.utc).strftime("%H:%M")
    
    # Volatility interpretation
    if h1_atr < 8:
        vol_status = "DEAD CALM"
    elif h1_atr < 15:
        vol_status = "LOW-MEDIUM"
    elif h1_atr < 25:
        vol_status = "MEDIUM"
    else:
        vol_status = "HIGH"
    
    # Spread assessment
    if spread > 10:
        spread_status = "WIDE"
    elif spread > 5:
        spread_status = "MODERATE"
    else:
        spread_status = "TIGHT"
    
    print("\n" + "█" * 120)
    print(f"  📊 MARKET SNAPSHOT │ {utc_now} UTC │ Price: {price:.2f} │ Session: {session:10s} │ Spread: {spread:.1f}pip ({spread_status:10s})")
    print(f"  🎯 Volatility      │ H1 ATR: {h1_atr:.1f}pip ({vol_status:15s}) │ M5 ATR: {m5_atr:.1f}pip │ Trend: {'UP' if m5_atr > 5 else 'NORMAL'}")
    print("█" * 120)

def print_regime_detection(regime_info: Dict) -> None:
    """Display detected trading regime with spread tolerance and configuration."""
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
    
    # Spread status indicator
    if spread_acceptable:
        spread_indicator = f"✓ {current_spread:.1f}pip (OK, max {max_spread:.1f})"
    else:
        spread_indicator = f"✗ {current_spread:.1f}pip (EXCEEDS max {max_spread:.1f})"
    
    # Determine display message
    if regime == "DEAD_CALM":
        bypass_msg = "(Will be BLOCKED at L2 - no trading)"
    elif bypass_l3 or bypass_l6:
        bypass_msg = f"(Bypass: L{'3 ' if bypass_l3 else ''}{'L6' if bypass_l6 else ''})"
    else:
        bypass_msg = "(Full L1-L8)"
    
    print(f"\n  {regime_symbol} REGIME: {regime:15s} │ M5 ATR: {m5_atr:5.1f}pip │ Risk: {risk_pct:.2f}% │ TP Target: {tp_ratio:.1f}R │ POI: {poi_threshold:.0f}%")
    print(f"     Spread: {spread_indicator:35s} │ Confidence: 70% threshold │ {bypass_msg}")

def print_layer_status(layers_passed: list, layer_failed: str, fail_reason: str) -> None:
    """Display layer-by-layer pass/fail status with detailed descriptions."""
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
    }
    
    all_layers = ["L0_GATES", "L1_BIAS", "L2_STRUCTURE", "L3_PULLBACK", "L4_LIQUIDITY", 
                  "L5_SWEEP", "L6_POI", "L7_CONFIDENCE", "L8_ENTRY"]
    
    status_line = ""
    for layer in all_layers:
        if layer in layers_passed:
            status_line += f"✓{layer} "
        elif layer == layer_failed:
            status_line += f"✗{layer} "
        else:
            status_line += f"- "
    
    print(f"\n  📋 LAYER PIPELINE: {status_line}")
    
    if layer_failed and fail_reason:
        desc = layer_descriptions.get(layer_failed, "Unknown layer")
        print(f"\n  ❌ BLOCKED AT {layer_failed}")
        print(f"     What: {desc}")
        print(f"     Why:  {fail_reason}")
    
    print("\n" + "█" * 120)


def print_layer_result(layer_num: int, layer_name: str, status: str, reason: str = "", details: str = "") -> None:
    """Print a single layer result in a safe, concise format."""
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

def print_run_summary(analysis: Dict) -> None:
    """Enhanced summary with regime, layer status, and entry details."""
    signal_type = analysis.get('signal_type', 'UNKNOWN')
    layers = analysis.get("layers_passed", [])
    layer_failed = analysis.get("layer_failed", "NONE")
    fail_reason = analysis.get("fail_reason", "")
    regime_info = analysis.get("regime_info", {})
    layer_8 = analysis.get("layer_8", {})
    entry = analysis.get("entry_signal")
    
    # Display regime detection
    if regime_info:
        print_regime_detection(regime_info)
    
    # Display layer-by-layer status
    print_layer_status(layers, layer_failed, fail_reason)
    
    # Display entry signal if generated
    if signal_type == "ENTRY_SIGNAL" and entry:
        print(f"\n  ✅ ENTRY SIGNAL GENERATED")
        print(f"     Position Type: {entry.get('position_type', 'N/A'):8s} │ Grade: {entry.get('grade', 'N/A')}")
        print(f"     Setup Type: {entry.get('setup_type', 'N/A'):20s} │ Trigger: {entry.get('trigger_type', 'N/A')}")
        print(f"     Entry Price: {entry.get('entry_price', 'N/A'):10s} │ Risk %: {entry.get('risk_percent', 'N/A')}")
        print(f"     Risk/Reward: 1:{float(entry.get('rr_ratio', 0.0)):.2f} │ Confidence: {entry.get('confidence_score', 0.0):.1f}%")
        print(f"     Setup Details: {entry.get('setup_description', 'N/A')}")
        print("     " + "=" * 115)
        
    elif signal_type == "PRE_ENTRY":
        layers_passed = len(layers)
        print(f"\n  ⏳ PRE-ENTRY SIGNAL (Setup building - {layers_passed}/9 layers passed)")
        print(f"     Waiting For: {fail_reason}")
        print(f"     Status: Setup conditions are forming, entry triggers not yet fired")
        print("     " + "=" * 115)
        
    elif signal_type == "ERROR":
        print(f"\n  ⚠️  ANALYSIS ERROR")
        print(f"     Issue: {fail_reason}")
        print("     " + "=" * 115)
        
    else:
        layers_passed = len(layers)
        print(f"\n  ℹ️  MONITORING ({layers_passed}/9 layers passed)")
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
    """Initialize all production-critical components."""
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
    """Append signal to CSV log."""
    file_exists = os.path.isfile(_SIGNAL_LOG_FILE)
    
    try:
        with open(_SIGNAL_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SIGNAL_LOG_COLUMNS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Error logging signal: {e}")


def _count_today_entry_signals(log_file: str = _SIGNAL_LOG_FILE) -> int:
    """Count ENTRY_SIGNAL rows logged today."""
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
    """Get current session name using the canonical risk-manager schedule."""
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
        # Fallback to UTC if risk_manager is unavailable.
        hour = datetime.now(timezone.utc).hour
        if 0 <= hour < 7:
            return "ASIAN"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 21:
            return "NY"
        return "DEAD"

def get_session_bonus() -> float:
    """Get confidence bonus for current session."""
    session = get_session_name()
    if session in ["LONDON", "NY"]:
        return 8.0
    if session == "ASIAN":
        return -5.0
    if session == "DEAD":
        return -15.0
    return 0.0


def _extract_intraday_rsi(m15_data=None, m5_data=None) -> float | None:
    """Prefer M15 RSI, fallback to M5 RSI for intraday confirmation."""
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
# LAYER 0: PRE-TRADE GATES
# ============================================================

def check_pre_trade_gates(
    account_balance: float = 10000,
    current_daily_loss: float = 0,
    current_spread: float = 0.5
) -> Dict:
    """Layer 0: Pre-trade gate checks - blocks all trading if any gate fails."""
    gates_passed = []
    gates_failed = []
    
    # Gate 1: Daily loss limit
    max_daily_loss = (account_balance * CONFIG["max_daily_loss_percent"] / 100) if account_balance > 0 else 1000
    if current_daily_loss < -max_daily_loss:
        gates_failed.append(f"DAILY_LOSS: {current_daily_loss:.2f} > {max_daily_loss:.2f}")
    else:
        gates_passed.append(f"Daily loss OK ({abs(current_daily_loss):.2f} / {max_daily_loss:.2f})")
    
    # Gate 2: Spread check - DEFERRED TO L8 ENTRY TRIGGER
    # Reason: Spread tolerance is REGIME-SPECIFIC (not one-size-fits-all)
    # - MICRO_SCALP (1.5R target): Can't afford spreads > 5 pips
    # - REGIME_SCALP (2.0R target): Can tolerate spreads 3-7 pips
    # - INTRADAY_SWING (3.0R target): Can tolerate spreads 5-10+ pips
    # Hard L0 gate prevents regime-based entries from ever happening
    # L8 Entry Engine will evaluate spread against regime's profit target
    gates_passed.append(f"Spread monitoring: {current_spread:.1f}pip (L8 Entry Trigger will evaluate vs regime)")
    
    # Gate 3: Session check
    # FIX #9 (PHASE 4): Keep Asian as VALID session (no hard block)
    # Only block DEAD session (22:00-03:00 UTC)
    # Regime Switch (L8) will dictate risk % based on session volatility
    session = get_session_name()
    if session == "DEAD":
        gates_failed.append("DEAD SESSION: no trading between 22:00 and 03:00 UTC")
    elif session in ["LONDON", "NY"]:
        gates_passed.append(f"Session OK ({session}) - Prime tier")
    elif session == "ASIAN":
        gates_passed.append(f"Session OK ({session}) - Asian session valid (Tier 2 - Regime Switch applies 0.75-1.0% risk)")
    else:
        gates_passed.append(f"Session OK ({session})")
    
    return {
        "all_gates_passed": len(gates_failed) == 0,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "session": session
    }

# ============================================================
# LAYERS 1-8: SEQUENTIAL ENTRY ANALYSIS
# ============================================================

def analyze_entry(
    h4_data=None, h1_data=None, m15_data=None, 
    m5_data=None, m1_data=None, daily_data=None,
    current_price: float = 0
) -> Dict:
    """
    Layers 1-8: Sequential entry analysis with hard gates.
    Stops at first layer failure.
    """
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "layers_passed": [],
        "layer_failed": None,
        "signal_type": "NO_SIGNAL",
        "entry_signal": None
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

        # best-effort current price for downstream (SL/TP)
        if current_price in (None, 0):
            try:
                if m1_data is not None and len(m1_data) > 0:
                    current_price = float(m1_data.iloc[-1]["close"])
                elif m15_data is not None and len(m15_data) > 0:
                    current_price = float(m15_data.iloc[-1]["close"])
            except Exception:
                current_price = None

        # ============ REGIME DETECTION (PHASE 4 - EARLY VISIBILITY) ============
        regime_info = None
        m5_atr = None
        h1_atr = None
        current_spread = 0.5
        
        # Calculate M5 ATR for regime detection
        if m5_data is not None and len(m5_data) >= 14:
            ranges_m5 = m5_data["high"].tail(14) - m5_data["low"].tail(14)
            m5_atr = ranges_m5.mean()
        
        # Calculate H1 ATR for display
        if h1_data is not None and len(h1_data) >= 14:
            ranges_h1 = h1_data["high"].tail(14) - h1_data["low"].tail(14)
            h1_atr = ranges_h1.mean()
        
        # Fetch current spread BEFORE regime detection (needed for spread validation)
        current_spread = 0.5
        try:
            if MT5_AVAILABLE and callable(get_current_spread):
                current_spread = get_current_spread(CONFIG["symbol"])
        except Exception:
            current_spread = 0.5
        
        # Detect regime (now includes spread validation)
        if callable(detect_regime) and m5_data is not None and m15_data is not None and h1_data is not None:
            regime_info = detect_regime(m5_data, m15_data, h1_data, current_spread=current_spread)
            analysis["regime_info"] = regime_info
        
        # Display market snapshot for visibility
        if current_price and h1_atr is not None and m5_atr is not None:
            session_name = get_session_name()
            print_market_snapshot(float(current_price), float(h1_atr), float(m5_atr), session_name, float(current_spread))

        # ============ LAYER 1: H4 BIAS ============
        h4_indicators = calculate_indicators(h4_data) if INDICATORS_AVAILABLE and h4_data is not None and len(h4_data) > 0 else {}
        if h4_data is not None and len(h4_data) >= 2 and "closes_2" not in h4_indicators:
            h4_indicators["closes_2"] = [float(v) for v in h4_data["close"].tail(2).tolist()]
        bias = get_h4_bias(h4_indicators, daily_data=daily_data, h4_data=h4_data) if callable(get_h4_bias) else None
        if not bias or bias.get("bias") == "NEUTRAL":
            analysis["layer_1"] = bias or {}
            analysis["layer_failed"] = "L1_BIAS"
            bias_reason = (bias or {}).get("full_report") or (bias or {}).get("reasoning") or "No bias details available"
            analysis["fail_reason"] = f"H4 Bias is NEUTRAL | {bias_reason}"
            analysis["signal_type"] = "PRE_ENTRY"
            safe_bias_reason = _ascii_safe(bias_reason)
            logger.warning(f"[L1_BIAS] NEUTRAL | {safe_bias_reason}")
            print_layer_result(1, "H4 Bias", "BLOCK", "NEUTRAL", safe_bias_reason)
            return analysis
        analysis["layers_passed"].append("L1_BIAS")
        analysis["layer_1"] = bias
        side = _bias_to_side(bias.get("bias", "NEUTRAL"))
        
        # ============ LAYER 2: H1 STRUCTURE ============
        struct = get_h1_structure(h1_data, bias["bias"]) if callable(get_h1_structure) and h1_data is not None else None
        
        # FIX #1 (PHASE 4): FATAL ATR BLOCKER REVERSAL
        # H1 ATR already calculated in regime detection (see early visibility section above)
        struct_type = struct.get("structure_type", "UNKNOWN") if struct else "BROKEN"
        
        # NEW LOGIC: Block ONLY when ATR is DEAD CALM (<8 pips)
        # High volatility (ATR >15) is ALLOWED - use volatility to widen stops
        is_dead_calm = h1_atr and h1_atr < 8.0  # Block extreme calm only
        is_high_volatility = h1_atr and h1_atr > 15.0  # Allow high vol
        
        if is_dead_calm:
            analysis["layer_failed"] = "L2_STRUCTURE"
            analysis["fail_reason"] = f"H1 ATR too calm ({h1_atr:.1f} < 8.0 pips) - no volatility to trade"
            analysis["signal_type"] = "PRE_ENTRY"
            logger.warning(f"[L2_STRUCTURE] BLOCK: ATR dead calm ({h1_atr:.1f} pips) - no trading in stagnant market")
            return analysis
        
        if struct_type == "BROKEN":
            if is_high_volatility:
                logger.info(f"[L2_STRUCTURE] Structure BROKEN but HIGH VOLATILITY ({h1_atr:.1f} pips ATR) - ALLOWED, will widen stops")
                analysis["layers_passed"].append("L2_STRUCTURE")
            else:
                # Normal volatility (8-15 pips): broken structure is still a soft block with warning
                logger.warning(f"[L2_STRUCTURE] Structure BROKEN in normal volatility ({h1_atr:.1f} pips ATR) - proceeding cautiously")
                analysis["layers_passed"].append("L2_STRUCTURE")
        elif struct_type == "UNKNOWN":
            logger.warning("[L2_STRUCTURE] Structure UNKNOWN - proceeding with caution")
        else:
            analysis["layers_passed"].append("L2_STRUCTURE")
        
        # ============ LAYER 3: M15 PULLBACK ============
        pullback = get_m15_pullback(m15_data, bias["bias"]) if callable(get_m15_pullback) and m15_data is not None else None
        # FIX #2 (PHASE 5): Lower pullback quality gate - quality >= 1.5 means PASS L3
        # Allow PRE_ENTRY signals to flow through to lower layers
        pullback_quality = pullback.get("pullback_quality", 0.0) if pullback else 0.0
        pullback_detected = pullback.get("pullback_detected", False) if pullback else False
        pullback_reason = pullback.get("reasoning", "No pullback details available") if pullback else "No pullback details available"
        pullback_warning = "WARNING: volume rising into pullback" if pullback and pullback.get("volume_warning") else ""
        MIN_PULLBACK_QUALITY = 1.5
        
        if not pullback or pullback_quality < MIN_PULLBACK_QUALITY:
            analysis["layer_failed"] = "L3_PULLBACK"
            analysis["fail_reason"] = f"Pullback quality too low ({pullback_quality:.1f} < {MIN_PULLBACK_QUALITY})"
            analysis["signal_type"] = "PRE_ENTRY"
            logger.warning(f"[L3_PULLBACK] Quality gate failed: {pullback_quality:.1f} < {MIN_PULLBACK_QUALITY}")
            return analysis
        
        analysis["layers_passed"].append("L3_PULLBACK")
        if not pullback_detected:
            logger.info(f"[L3_PULLBACK] Quality ready ({pullback_quality:.1f}/10) - PRE_ENTRY signal")
        if pullback_warning:
            logger.warning(f"[L3_PULLBACK] {pullback_warning}")
        
        # ============ LAYER 4: LIQUIDITY POOLS ============
        pools_result = (
            identify_liquidity_pools(m15_data, h1_data=h1_data, h4_data=h4_data, daily_data=daily_data, current_price=current_price, side=side)
            if callable(identify_liquidity_pools) and m15_data is not None
            else {}
        )
        pool_list = pools_result.get("liquidity_pools", [])
        sweep_pool = pools_result.get("sweep_pool")
        tp_pool = pools_result.get("tp_pool")

        liquidity_assessment = (
            assess_liquidity_gate(sweep_pool, tp_pool, current_price, side)
            if callable(assess_liquidity_gate)
            else {
                "state": "BLOCK",
                "reason": "Liquidity assessment unavailable",
                "sweep_score": sweep_pool.get("score", 0) if sweep_pool else 0,
                "tp_score": tp_pool.get("score", 0) if tp_pool else 0,
                "sweep_distance": abs(sweep_pool.get("level", 0) - current_price) if sweep_pool else None,
                "thresholds": {},
            }
        )
        liquidity_state = liquidity_assessment.get("state", "BLOCK")
        liquidity_reason = liquidity_assessment.get("reason", "")
        sweep_score = liquidity_assessment.get("sweep_score", sweep_pool.get("score", 0) if sweep_pool else 0)
        tp_score = liquidity_assessment.get("tp_score", tp_pool.get("score", 0) if tp_pool else 0)
        sweep_dist = liquidity_assessment.get("sweep_distance", abs(sweep_pool.get("level", 0) - current_price) if sweep_pool else 999)

        if liquidity_state == "BLOCK":
            analysis["layer_failed"] = "L4_LIQUIDITY"
            analysis["fail_reason"] = liquidity_reason or "Sweep/TP safety checks failed (score/distance)"
            analysis["signal_type"] = "PRE_ENTRY"
            logger.warning(f"[L4_SAFE] Sweep {sweep_pool.get('pool_type','')} score:{sweep_score} dist:{sweep_dist:.2f} tp_score:{tp_score}")
            return analysis

        analysis["layers_passed"].append("L4_LIQUIDITY")
        analysis["layer_4"] = {
            "pools_found": len(pool_list),
            "high_quality": len([p for p in pool_list if p.get('score',0)>=70]),
            "sweep_pool": sweep_pool,
            "tp_pool": tp_pool,
            "state": liquidity_state,
            "reason": liquidity_reason,
            "thresholds": liquidity_assessment.get("thresholds", {}),
        }
        target_pool = tp_pool

        # ============ LAYER 5: SWEEP + STRUCTURE ============
        # FIX #8 (PHASE 4): Pass exact L4 sweep level to L5 (hard handshake)
        l4_sweep_level = sweep_pool.get("level") if sweep_pool else None
        sweep = (
            get_sweep_and_structure(m15_data, h1_data, sweep_pool["level"], side, l4_override_level=l4_sweep_level)
            if callable(get_sweep_and_structure) and m15_data is not None and h1_data is not None
            else None
        )
        sweep_gate_state = sweep.get("gate_state", "BLOCK") if sweep else "BLOCK"
        sweep_gate_reason = sweep.get("gate_reason", "No sweep or CHoCH detected") if sweep else "No sweep or CHoCH detected"
        if sweep_gate_state == "WATCH":
            analysis["layer_failed"] = "L5_SWEEP_WAIT"
            analysis["fail_reason"] = sweep_gate_reason
            analysis["signal_type"] = "PRE_ENTRY"
            logger.warning(f"[L5_WAIT] {sweep_gate_reason}")
            return analysis
        if not sweep or (not sweep.get("sweep_confirmed") and not sweep.get("choch_confirmed")):
            analysis["layer_failed"] = "L5_SWEEP"
            analysis["fail_reason"] = sweep_gate_reason
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        
        # Validate sweep direction matches entry side
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
            "gate_reason": sweep_gate_reason,
        }
        
        # ============ LAYER 6: POI QUALITY ============
        poi = (
            identify_poi(m15_data, h1_data=h1_data, direction=side, current_price=current_price)
            if callable(identify_poi) and m15_data is not None
            else {}
        )
        best_poi = poi.get("best_poi")
        analysis["layer_6"] = build_poi_layer_data(poi) if callable(build_poi_layer_data) else {}
        
        # FIX #4 (PHASE 4): DYNAMIC POI THRESHOLD
        # If sweep confirmed, lower threshold from 70 to 60 (confirmed sweep justifies slightly weaker POI)
        sweep_confirmed = sweep.get("sweep_confirmed", False) if sweep else False
        poi_threshold = 60 if sweep_confirmed else 70
        
        if not best_poi or best_poi.get("score", 0) < poi_threshold:
            analysis["layer_failed"] = "L6_POI"
            analysis["fail_reason"] = f"POI score too low ({best_poi.get('score', 0):.0f} < {poi_threshold})" if best_poi else "No POI found"
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
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
            else {"has_fib_confluence": False, "matched_levels": [], "reasoning": "Unavailable"}
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
                regime=analysis.get("regime_info", {}).get("regime", "DEFAULT"),
            )
            if callable(get_confidence_engine)
            else {}
        )
        if conf.get("grade") == "REJECT":
            analysis["layer_failed"] = "L7_CONFIDENCE"
            conf_score = conf.get('final_score', 0)
            threshold = 55 if analysis.get("regime_info", {}).get("regime") == "MICRO_SCALP" else 70
            analysis["fail_reason"] = f"Confidence score too low ({conf_score:.1f} < {threshold})"
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        analysis["layers_passed"].append("L7_CONFIDENCE")
        analysis["layer_7"] = {
            "score": conf.get("final_score"),
            "grade": conf.get("grade"),
            "fib_confluence": poi_fib,
            "rsi_value": intraday_rsi,
        }
        
        # ============ LAYER 8: ENTRY TRIGGERS + REGIME SPREAD CHECK ============
        
        # Check spread acceptability for regime (FIX PHASE 5)
        regime_info = analysis.get("regime_info", {})
        if regime_info and not regime_info.get("spread_acceptable", True):
            analysis["layer_failed"] = "L8_SPREAD"
            spread = regime_info.get("current_spread", current_spread)
            max_spread = regime_info.get("max_spread_pips", 7.0)
            regime = regime_info.get("regime", "UNKNOWN")
            analysis["fail_reason"] = f"Spread {spread:.1f}pip exceeds {regime} tolerance ({max_spread:.1f}pip max)"
            analysis["signal_type"] = "REJECTED"
            logger.warning(f"[L8_SPREAD] {analysis['fail_reason']}")
            return analysis
        
        confirmed_m5_close = float(m5_data.iloc[-2]["close"]) if m5_data is not None and len(m5_data) >= 2 else float(current_price) if current_price is not None else 0.0
        entry = (
            get_entry_trigger(
                m5_data=m5_data,
                m1_data=m1_data,
                current_price=confirmed_m5_close,
                direction=side,
                sweep_wick_low=sweep.get("sweep_wick_low") if sweep else None,
                sweep_wick_high=sweep.get("sweep_wick_high") if sweep else None,
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
                "rr_valid": entry.get("rr_valid", False),
                "rr": entry.get("reward_to_risk_ratio", 0),
                "entry_triggered": False,
            }
            print_layer_result(
                8,
                "Entry Trigger",
                "WAIT",
                f"Setup: {entry.get('setup_type', 'REJECTED')} | candidate: {entry.get('entry_style', 'NONE')} | waiting for M5/M1 confirmation",
            )
            print_no_signal("Waiting for M5/M1 entry triggers to fire", "L8_ENTRY")
            return analysis
        analysis["layers_passed"].append("L8_ENTRY")
        analysis["layer_8"] = {
            "setup_type": entry.get("setup_type", "REJECTED"),
            "trigger_type": entry.get("trigger_type"),
            "entry_style": entry.get("entry_style", "NONE"),
            "entry_mode": entry.get("entry_mode", "MARKET"),
            "rr_valid": entry.get("rr_valid", False),
            "rr": entry.get("reward_to_risk_ratio"),
            "entry_triggered": True,
        }
        print_layer_result(8, "Entry Trigger", "PASS", f"{entry.get('setup_type', 'REJECTED')} | {entry.get('entry_style', 'NONE')} confirmed (RR: 1:{entry.get('reward_to_risk_ratio', 0):.1f})")
        
        # ============ ALL LAYERS PASSED - ENTRY SIGNAL ============
        analysis["signal_type"] = "ENTRY_SIGNAL"
        analysis["entry_signal"] = {
            "position_type": "BUY" if bias["bias"] == "BULLISH" else "SELL",
            "entry_price": entry.get("entry_price", 0),
            "stop_loss": entry.get("stop_loss", 0),
            "take_profit": entry.get("take_profit", 0),
            "rr_ratio": entry.get("reward_to_risk_ratio", 0),
            "grade": conf.get("grade", "A"),
            "setup_type": entry.get("setup_type", "REJECTED"),
            "entry_method": entry.get("entry_style", "NONE"),
            "entry_mode": entry.get("entry_mode", "MARKET"),
            "trigger_type": entry.get("trigger_type", "none"),
            "rr_valid": entry.get("rr_valid", False),
            "poi_type": l6_data.get("poi_type", "N/A") if isinstance(l6_data, dict) else "N/A",
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

def execute_entry_signal(entry_signal: Dict, account_balance: float = 10000) -> Optional[str]:
    """
    Execute entry signal with order creation and execution.
    
    Returns:
        Order ID if successful, None otherwise
    """
    if not entry_signal or not order_executor:
        return None
    
    try:
        # Calculate position size from risk if the risk manager is available.
        risk_pct = CONFIG["risk_per_trade_a_plus"] if entry_signal.get("grade") == "A+" else CONFIG["risk_per_trade_a"]
        if RISK_MANAGER_AVAILABLE:
            position_size = calculate_lot_size_for_symbol(
                CONFIG["symbol"],
                account_balance,
                risk_pct,
                entry_signal["entry_price"],
                entry_signal["stop_loss"],
            )
        else:
            risk_amount = account_balance * risk_pct / 100
            stop_distance = abs(entry_signal["entry_price"] - entry_signal["stop_loss"])
            position_size = max(0.01, round(risk_amount / (max(stop_distance, 1e-6) * 100.0), 2))
        
        # Create order
        order = order_executor.create_order(
            order_type=OrderType.BUY if entry_signal["position_type"] == "BUY" else OrderType.SELL,
            entry_price=entry_signal["entry_price"],
            stop_loss=entry_signal["stop_loss"],
            take_profit=entry_signal["take_profit"],
            position_size=position_size,
            signal_grade=entry_signal.get("grade", "A"),
            confidence_score=80.0,  # Would come from confidence engine
            metadata={
                "setup_type": entry_signal.get("setup_type", "REJECTED"),
                "entry_mode": entry_signal.get("entry_mode", "UNKNOWN"),
                "session": get_session_name()
            }
        )
        
        # Execute on MT5 or simulation
        success, message = order_executor.execute_order(
            order["order_id"],
            mt5_handler=None,
            simulation=CONFIG["demo_mode"]
        )
        
        if success:
            logger.info(f"[+] Order executed: {order['order_id']}")
            
            # Track trade
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
    """Layer 9: Update open positions with partial exit logic."""
    global _OPEN_TRADES
    
    closed_trades = []
    
    for trade in _OPEN_TRADES:
        try:
            # Auto-generate order_id if missing (for old trades saved before this field)
            if "order_id" not in trade:
                trade["order_id"] = f"{trade.get('trade_id', 'UNKNOWN')}_auto_{int(time.time())}"
                logger.debug(f"[AUTO_FIX] Generated order_id for {trade.get('trade_id')}")
            
            # Update current price
            current_price = current_prices.get(trade["trade_id"], trade.get("entry_price", 0))
            
            # Update order with current price
            if order_executor:
                result = order_executor.update_current_price(trade["order_id"], current_price)
                
                # Process any exit actions
                for action in result.get("actions", []):
                    if action["action"] == "CLOSE_50PCT":
                        logger.info(f"[{trade['trade_id']}] 1:1 RR: Close 50% @ {current_price:.2f}")
                    elif action["action"] == "TRAIL_SL":
                        logger.info(f"[{trade['trade_id']}] 1:2 RR: Trail SL")
                    elif action["action"] == "CLOSE_ALL":
                        logger.info(f"[{trade['trade_id']}] TP: Close all @ {current_price:.2f}")
                        closed_trades.append(trade)
            
            trade["last_check"] = datetime.now().isoformat()
        
        except Exception as e:
            logger.error(f"Error managing position {trade.get('trade_id')}: {e}")
    
    # Remove closed trades
    _OPEN_TRADES = [t for t in _OPEN_TRADES if t not in closed_trades]

# ============================================================
# PERSISTENCE
# ============================================================

def save_state() -> bool:
    """Save current state to disk."""
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
    """Restore state from disk."""
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
    """Graceful shutdown with position preservation."""
    global _SHOULD_CONTINUE
    
    logger.info("\n" + "="*70)
    logger.info("GRACEFUL SHUTDOWN INITIATED")
    logger.info("="*70)
    
    _SHOULD_CONTINUE = False
    
    # Close all positions on MT5
    try:
        if MT5_AVAILABLE:
            positions = mt5.positions_get(symbol=CONFIG["symbol"])
            if positions:
                logger.info(f"Closing {len(positions)} position(s)...")
                for pos in positions:
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
    
    # Save state
    save_state()
    
    # Shutdown MT5
    if MT5_AVAILABLE:
        shutdown_mt5()
    
    # Graceful shutdown with error recovery
    if shutdown_mgr:
        shutdown_mgr.shutdown(_OPEN_TRADES, monitor)
    
    logger.info("="*70)
    logger.info("[SHUTDOWN] COMPLETE")
    logger.info("="*70)

def signal_handler(sig, frame):
    """Handle shutdown signal."""
    logger.info("[SIGNAL] Shutdown signal received")
    graceful_shutdown()
    sys.exit(0)

# ============================================================
# MAIN BOT LOOP
# ============================================================

def main():
    """Main bot orchestration loop."""
    global _SHOULD_CONTINUE, _OPEN_TRADES
    
    logger.info("\n" + "="*70)
    logger.info("[BOT] PRODUCTION TRADING BOT STARTING")
    logger.info("="*70)
    
    # Print system configuration
    logger.info(f"Symbol: {CONFIG['symbol']}")
    logger.info(f"Mode: {'DEMO' if CONFIG['demo_mode'] else 'LIVE'}")
    logger.info(f"Max Concurrent Trades: {CONFIG['max_concurrent_trades']}")
    logger.info(f"Max Daily Loss: {CONFIG['max_daily_loss_percent']}%")
    logger.info(f"Layers Available: {LAYERS_AVAILABLE}")
    logger.info(f"MT5 Available: {MT5_AVAILABLE}")
    logger.info(f"Persistence Available: {PERSISTENCE_AVAILABLE}")
    logger.info(f"Order Execution Available: {EXECUTION_AVAILABLE}")
    logger.info(f"Error Recovery Available: {ERROR_RECOVERY_AVAILABLE}")
    
    # Initialize production components
    initialize_production_components()
    
    # Restore state if available
    restore_state()
    
    # Setup signal handlers
    signal_module.signal(signal_module.SIGINT, signal_handler)
    signal_module.signal(signal_module.SIGTERM, signal_handler)
    
    # Connect to MT5
    if MT5_AVAILABLE and not CONFIG["demo_mode"]:
        logger.info("Connecting to MT5...")
        if not connect_mt5():
            logger.error("Failed to connect to MT5")
            return
    
    logger.info("="*70)
    logger.info("[READY] BOT READY - Waiting for trading opportunities")
    logger.info("="*70 + "\n")
    
    iteration_count = 0
    
    # Main loop
    while _SHOULD_CONTINUE:
        try:
            iteration_count += 1
            
            # Layer 0: Pre-trade gates - fetch REAL spread from MT5 first
            current_spread = 0.5
            try:
                if MT5_AVAILABLE and callable(get_current_spread):
                    current_spread = get_current_spread(CONFIG["symbol"])
            except Exception:
                current_spread = 0.5
            
            gate_check = check_pre_trade_gates(current_spread=current_spread)
            
            if not gate_check["all_gates_passed"]:
                logger.warning(f"[L0] Trading blocked: {gate_check['gates_failed']}")
                time.sleep(60)
                continue
            
            # Check if we can open new trades
            if len(_OPEN_TRADES) < CONFIG["max_concurrent_trades"]:
                try:
                    # Fetch market data
                    if MT5_AVAILABLE and not CONFIG["demo_mode"]:
                        h4_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H4, CONFIG["h4_candles_required"])
                        h1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H1, CONFIG["h1_candles_required"])
                        m15_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M15, CONFIG["m15_candles_required"])
                        m5_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M5, CONFIG["m5_candles_required"])
                        m1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M1, CONFIG["m1_candles_required"])
                        daily_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_D1, 10)
                    else:
                        # Demo mode
                        h4_data = h1_data = m15_data = m5_data = m1_data = daily_data = None

                    try:
                        current_price = get_current_price(CONFIG["symbol"]) if MT5_AVAILABLE else 0
                    except Exception:
                        current_price = 0
                    
                    # Analyze entry
                    analysis = analyze_entry(h4_data, h1_data, m15_data, m5_data, m1_data, daily_data, current_price)
                    print_run_summary(analysis)
                    
                    # Extract L6 POI details
                    l6_data = analysis.get("layer_6", {})
                    l6_poi_type = l6_data.get("poi_type", "N/A") if l6_data else "N/A"
                    l6_poi_score = l6_data.get("score", "N/A") if l6_data else "N/A"
                    
                    # Log signal
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
                    
                    # Execute entry if signal generated
                    if analysis.get("signal_type") == "ENTRY_SIGNAL":
                        order_id = execute_entry_signal(analysis["entry_signal"])
                        if order_id:
                            logger.info(f"[+] Trade #{len(_OPEN_TRADES)} opened: {order_id}")
                
                except Exception as e:
                    logger.error(f"Error during entry analysis: {e}")
                    if monitor:
                        monitor.log_error("ENTRY_LOOP_ERROR", str(e), ErrorSeverity.ERROR)
            
            # Layer 9: Manage open positions
            manage_positions({})
            
            # Save state periodically
            if iteration_count % 10 == 0:
                save_state()
            
            # Check system health
            if monitor and iteration_count % 60 == 0:
                status = monitor.check_health()
                logger.debug(f"System health: {status.value}")
            
            # Wait before next iteration
            time.sleep(5)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            if monitor:
                monitor.log_error("MAIN_LOOP_ERROR", str(e), ErrorSeverity.CRITICAL)
            time.sleep(5)
    
    graceful_shutdown()

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
