"""
MAIN ORCHESTRATION ENGINE - 10 LAYER TRADING BOT
Purpose: Integrate all 10 entry + exit layers into production trading flow

System Architecture:
  Layer 0: Pre-trade gates (daily loss, spread, news)
  Layer 1-8: Sequential entry filters (all must pass)
  Layer 9: Trade management (partial exits 1:1/1:2/1:3 RR)
  Layer 10: Feedback loop (performance tracking & auto-adjustment)
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

# Try to import MT5 handler (optional for live trading)
try:
    import config
    from mt5_handler import connect_mt5, get_market_data, shutdown_mt5, get_current_spread, get_current_price
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("[INFO] MT5 not available - running in analysis mode")

# Import all layer modules
try:
    from bias_engine import get_h4_bias
    from structure_engine import get_h1_structure
    from pullback_detector import get_m15_pullback
    from liquidity_engine import identify_liquidity_pools, assess_liquidity_gate
    from sweep_detector import get_sweep_and_structure
    from poi_engine import identify_poi, format_poi_layer_detail, build_poi_layer_data
    from confidence_engine import get_confidence_engine, evaluate_poi_fib_confluence
    from entry_engine import get_entry_trigger
    from trade_manager import manage_open_trade, close_position
    from feedback_loop import log_closed_trade, calculate_weekly_performance
    from indicators import calculate_indicators  # ADD THIS
    LAYERS_AVAILABLE = True
except ImportError as e:
    LAYERS_AVAILABLE = False
    print(f"[WARNING] Could not import all layers: {e}")

# ============================================================
# CONFIGURATION
# ============================================================

_SHOULD_CONTINUE = True

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
}

SIGNAL_LOG_COLUMNS = [
    "timestamp", "signal_type", "layers_passed", "layer_failed", 
    "fail_reason", "l6_poi_type", "l6_poi_score", 
    "entry_grade", "setup_type", "entry_method", "entry_mode", "trigger_type", "rr_valid", "entry_price", "stop_loss", 
    "take_profit", "rr_ratio", "session", "position_type"
]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot_main.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TradingBot')

# ============================================================
# SIGNAL LOGGING
# ============================================================

def _append_signal_log(log_file: str, row: dict) -> None:
    """Append signal to CSV log."""
    file_exists = os.path.isfile(log_file)
    
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SIGNAL_LOG_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def _count_today_entry_signals(log_file: str = "signal_log.csv") -> int:
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

def get_session_name() -> str:
    """Get current session name (GMT/UTC)."""
    utc_now = datetime.now(timezone.utc)
    hour = utc_now.hour
    
    # Session times in UTC (GMT) - checked in order from earliest to latest
    if 0 <= hour < 3:              # 0 AM - 3 AM = Dead time
        return "DEAD"
    elif 3 <= hour < 8:            # 3 AM - 8 AM = Asian session opening
        return "ASIAN"
    elif 8 <= hour < 13:           # 8 AM - 1 PM = London opening
        return "LONDON_OPEN"
    elif 13 <= hour < 17:          # 1 PM - 5 PM = London peak
        return "LONDON"
    elif 17 <= hour < 21:          # 5 PM - 9 PM = New York
        return "NY"
    else:                          # 9 PM - midnight = US close / Dead
        return "DEAD"

def get_session_bonus() -> float:
    """Get confidence bonus for current session."""
    session = get_session_name()
    if session in ["LONDON", "LONDON_OPEN", "NY"]:
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
            indicators = calculate_indicators(frame) if callable(calculate_indicators) else {}
            rsi_value = indicators.get("rsi_14") if isinstance(indicators, dict) else None
            if rsi_value is not None:
                return float(rsi_value)
        except Exception:
            continue
    return None

# ============================================================
# DETAILED OUTPUT FORMATTER
# ============================================================

def print_market_header(price: float = 0, session: str = ""):
    """Print market analysis header."""
    print(f"\n{'='*90}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [ANALYSIS] MARKET ANALYSIS | XAUUSD @ {price:.2f} | Session: {session}")
    print(f"{'='*90}")

def print_layer_result(layer_num: int, layer_name: str, status: str, reason: str = "", details: str = ""):
    """Print layer analysis result."""
    if status == "PASS":
        symbol = "✓"
        status_display = "PASS"
    elif status == "BLOCK":
        symbol = "✗"
        status_display = "BLOCK"
    else:
        symbol = "⏳"
        status_display = "WAIT"
    
    msg = f"  L{layer_num} [{status_display:6s}] {layer_name:20s} | {reason}"
    if details:
        msg += f" | {details}"
    print(msg)

def print_entry_signal(signal: Dict):
    """Print entry signal with full details."""
    print(f"\n{'='*90}")
    print(f"[SIGNAL] ENTRY SIGNAL GENERATED - {signal.get('grade', 'N/A').upper()} GRADE")
    print(f"{'='*90}")
    print(f"  Position Type:    {signal.get('position_type', 'N/A')}")
    print(f"  Setup Type:       {signal.get('setup_type', 'N/A')}")
    if signal.get("entry_method"):
        print(f"  Entry Method:     {signal.get('entry_method')}")
    if signal.get("entry_mode"):
        print(f"  Entry Mode:       {signal.get('entry_mode')}")
    if signal.get("trigger_type"):
        print(f"  Trigger Type:     {signal.get('trigger_type')}")
    print(f"  RR Valid:         {signal.get('rr_valid', 'N/A')}")
    print(f"  Entry Price:      {signal.get('entry_price', 0):.2f}")
    print(f"  Stop Loss:        {signal.get('stop_loss', 0):.2f}")
    print(f"  Take Profit:      {signal.get('take_profit', 0):.2f}")
    print(f"  Risk/Reward:      1:{signal.get('rr_ratio', 0):.1f}")
    print(f"  Timestamp:        {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*90}\n")


def print_run_summary(analysis: Dict) -> None:
    """Print a compact run summary for easy scanning."""
    layers = ", ".join(analysis.get("layers_passed", [])) or "none"
    failed = analysis.get("layer_failed") or "none"
    reason = analysis.get("fail_reason") or ""
    layer_8 = analysis.get("layer_8") or {}
    entry = analysis.get("entry_signal") or {}

    print("\n" + "=" * 90)
    print(f"[RUN] {analysis.get('signal_type', 'UNKNOWN')} | passed: {layers}")
    print(f"[RUN] failed: {failed}" + (f" | reason: {reason}" if reason else ""))
    if layer_8:
        print(
            f"[RUN] setup: {layer_8.get('setup_type', 'N/A')} | "
            f"entry_method: {layer_8.get('entry_style', 'N/A')} | "
            f"mode: {layer_8.get('entry_mode', 'N/A')} | "
            f"trigger: {layer_8.get('trigger_type', 'N/A')} | "
            f"rr_valid: {layer_8.get('rr_valid', 'N/A')}"
        )
    if entry:
        print(
            f"[RUN] signal: {entry.get('position_type', 'N/A')} | "
            f"setup: {entry.get('setup_type', 'N/A')} | "
            f"method: {entry.get('entry_method', 'N/A')} | "
            f"mode: {entry.get('entry_mode', 'N/A')} | "
            f"trigger: {entry.get('trigger_type', 'N/A')} | "
            f"rr_valid: {entry.get('rr_valid', 'N/A')} | "
            f"RR: 1:{float(entry.get('rr_ratio', 0.0)):.1f} | "
            f"grade: {entry.get('grade', 'N/A')}"
        )
    print("=" * 90)

def print_no_signal(reason: str, failed_layer: str = ""):
    """Print why no signal was generated."""
    print(f"\n  ⏸ NO SIGNAL: {reason}")
    if failed_layer:
        print(f"     Blocked at: {failed_layer}")

# ============================================================
# PRE-TRADE GATE CHECKS (Layer 0)
# ============================================================

def check_pre_trade_gates(
    account_balance: float = 0,
    current_daily_loss: float = 0,
    current_spread: float = 0.5
) -> Dict:
    """Layer 0: Pre-trade gate checks - blocks all trading if any gate fails."""
    gates_passed = []
    gates_failed = []
    
    # Gate 1: Daily loss limit
    max_daily_loss = (account_balance * CONFIG["max_daily_loss_percent"] / 100) if account_balance > 0 else 1000
    if abs(current_daily_loss) > max_daily_loss:
        gates_failed.append(f"DAILY LOSS LIMIT: {current_daily_loss:.2f} > {max_daily_loss:.2f}")
    else:
        gates_passed.append(f"Daily loss OK ({current_daily_loss:.2f} / {max_daily_loss:.2f})")
    
    # Gate 2: Spread check
    SPREAD_MAX = 0.8  # XAUUSD should be tight
    if current_spread > SPREAD_MAX:
        gates_failed.append(f"SPREAD TOO HIGH: {current_spread:.2f} > {SPREAD_MAX:.2f}")
    else:
        gates_passed.append(f"Spread OK ({current_spread:.2f})")

    session = get_session_name()
    if session == "DEAD":
        gates_failed.append("DEAD SESSION: no trading between 22:00 and 03:00 UTC")
    else:
        gates_passed.append(f"Session OK ({session})")
    
    return {
        "all_gates_passed": len(gates_failed) == 0,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "recommendation": "TRADING ALLOWED" if len(gates_failed) == 0 else "TRADING BLOCKED"
    }

# ============================================================
# MAIN ENTRY ANALYSIS FLOW (Layers 1-8)
# ============================================================

def analyze_entry(
    h4_data=None, h1_data=None, m15_data=None, 
    m5_data=None, m1_data=None, daily_data=None,
    current_price: float = 0
) -> Dict:
    """
    Main 8-layer sequential entry analysis.
    Stops at first layer failure (hard gates).
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
    
    session = get_session_name()
    print_market_header(current_price, session)
    
    if not LAYERS_AVAILABLE or h4_data is None:
        analysis["signal_type"] = "ERROR"
        analysis["fail_reason"] = "Missing data or layers not available"
        print_layer_result(0, "Pre-Gates", "PASS", "All gates passed")
        print_layer_result(1, "Data Check", "BLOCK", "Missing market data or layer modules")
        return analysis
    
    try:
        # Normalize direction vocab across layers
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

        # ============ LAYER 1: BIAS ============
        # Calculate indicators from H4 data first
        h4_indicators = calculate_indicators(h4_data) if h4_data is not None and len(h4_data) > 0 else {}
        if h4_data is not None and len(h4_data) >= 2 and "closes_2" not in h4_indicators:
            h4_indicators["closes_2"] = [float(v) for v in h4_data["close"].tail(2).tolist()]
        bias = get_h4_bias(h4_indicators, daily_data=daily_data, h4_data=h4_data) if callable(get_h4_bias) else None
        if not bias or bias.get("bias") == "NEUTRAL":
            analysis["layer_failed"] = "L1_BIAS"
            analysis["fail_reason"] = "H4 Bias is NEUTRAL"
            analysis["signal_type"] = "PRE_ENTRY"
            # Extract EMA details for debug output
            ema20 = bias.get('ema20', 0) if bias else 0
            ema50 = bias.get('ema50', 0) if bias else 0
            ema_dist = bias.get('ema_distance', 0) if bias else 0
            ema_threshold = bias.get('ema_threshold', 5.0) if bias else 5.0
            reason = bias.get('reasoning', 'EMAs too close') if bias else 'Unknown'
            print_layer_result(1, "H4 Bias", "BLOCK", f"EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | Distance: {abs(ema_dist):.2f} | Threshold: {ema_threshold:.2f} | {reason}")
            print_no_signal("Waiting for H4 bias direction", "L1_BIAS")
            return analysis
        analysis["layers_passed"].append("L1_BIAS")
        analysis["layer_1"] = bias
        bias_strength = bias.get('bias_strength', 0)
        ema20 = bias.get('ema20', 0)
        ema50 = bias.get('ema50', 0)
        ema_dist = bias.get('ema_distance', 0)
        ema_threshold = bias.get('ema_threshold', 5.0)
        print_layer_result(1, "H4 Bias", "PASS", f"{bias.get('bias')} (EMA: {ema20:.2f}/{ema50:.2f}, dist: {abs(ema_dist):.2f}, threshold: {ema_threshold:.2f}, strength: {bias_strength:.1f}/10)")
        side = _bias_to_side(bias.get("bias", "NEUTRAL"))
        
        # ============ LAYER 2: STRUCTURE ============
        struct = get_h1_structure(h1_data, bias["bias"]) if callable(get_h1_structure) and h1_data is not None else None
        
        # FIX #3: Conditional L2 gate based on volatility
        h1_atr = None
        if h1_data is not None and len(h1_data) >= 14:
            ranges = h1_data["high"].tail(14) - h1_data["low"].tail(14)
            h1_atr = ranges.mean()
        
        struct_type = struct.get("structure_type", "UNKNOWN") if struct else "BROKEN"
        is_high_volatility = h1_atr and h1_atr > 15.0

        if struct_type == "BROKEN":
            if is_high_volatility:
                print_layer_result(2, "H1 Structure", "WARN", f"Structure: BROKEN (high vol {h1_atr:.1f}p) - proceeding")
                analysis["layers_passed"].append("L2_STRUCTURE")
            else:
                atr_display = f"{h1_atr:.1f}" if h1_atr is not None else "N/A"
                analysis["layer_failed"] = "L2_STRUCTURE"
                analysis["fail_reason"] = "H1 structure broken"
                analysis["signal_type"] = "PRE_ENTRY"
                print_layer_result(2, "H1 Structure", "BLOCK", f"Structure broken in normal volatility ({atr_display}p)")
                print_no_signal("H1 structure broken", "L2_STRUCTURE")
                return analysis
        elif struct_type == "UNKNOWN":
            print_layer_result(2, "H1 Structure", "WARN", "Structure: UNKNOWN - proceeding with caution")
        else:
            analysis["layers_passed"].append("L2_STRUCTURE")
            struct_conf = struct.get("structure_confidence", 0.0)
            print_layer_result(2, "H1 Structure", "PASS", f"{struct_type} (confidence: {float(struct_conf):.1f}/10)")
        
        analysis["layer_2"] = struct
        
        # ============ LAYER 3: PULLBACK ============
        pullback = get_m15_pullback(m15_data, bias["bias"]) if callable(get_m15_pullback) and m15_data is not None else None
        
        # FIX #2: Enforce pullback quality gate (minimum 5.0) AND pullback must be detected
        pullback_quality = pullback.get("pullback_quality", 0.0) if pullback else 0.0
        pullback_detected = pullback.get("pullback_detected", False) if pullback else False
        pullback_reason = pullback.get("reasoning", "No pullback details available") if pullback else "No pullback details available"
        pullback_warning = "WARNING: volume rising into pullback" if pullback and pullback.get("volume_warning") else ""
        MIN_PULLBACK_QUALITY = 5.0
        if not pullback or pullback_quality < MIN_PULLBACK_QUALITY or not pullback_detected:
            if not pullback_detected and pullback_quality >= MIN_PULLBACK_QUALITY:
                print_layer_result(3, "M15 Pullback", "BLOCK", f"Quality ready ({pullback_quality:.1f}/10) but pullback NOT YET formed", pullback_reason)
            else:
                print_layer_result(3, "M15 Pullback", "BLOCK", f"Quality too low ({pullback_quality:.1f} < {MIN_PULLBACK_QUALITY}) or no pullback", pullback_reason)
            print_no_signal("Pullback not ready", "L3_PULLBACK")
            analysis["signal_type"] = "PRE_ENTRY"
            return analysis
        
        analysis["layers_passed"].append("L3_PULLBACK")
        analysis["layer_3"] = pullback or {"pullback_detected": False}
        pullback_detected = pullback.get("pullback_detected", False) if pullback else False
        pullback_depth = pullback.get("pullback_depth_fib") if pullback else None
        pullback_depth = pullback_depth if pullback_depth is not None else 0.0
        pb_status = "DETECTED" if pullback_detected else "NOT YET"
        print_layer_result(3, "M15 Pullback", "PASS", f"{pb_status} (depth: {pullback_depth:.3f}, quality: {pullback_quality:.1f}/10)", pullback_warning or pullback_reason)
        
        # ============ LAYER 4: LIQUIDITY ============
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
            analysis["fail_reason"] = liquidity_reason or "Directional liquidity targets fail safety checks (score/distance)"
            analysis["signal_type"] = "PRE_ENTRY"
            pool_type = sweep_pool.get("pool_type", "unknown") if sweep_pool else "missing"
            print_layer_result(4, "Liquidity", "BLOCK", f"Sweep ({pool_type}) score={sweep_score}, dist={sweep_dist:.2f}, tp_score={tp_score} - failed safety checks")
            print_no_signal("Sweep/TP safety checks failed", "L4_LIQUIDITY")
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
        liquidity_status = "PASS" if liquidity_state == "PASS" else "WARN"
        print_layer_result(4, "Liquidity", liquidity_status, liquidity_reason or f"Found {len(pool_list)} pools", f"Sweep: {sweep_pool.get('level'):.2f} | TP: {tp_pool.get('level'):.2f}")
        
        # ============ LAYER 5: SWEEP ============
        sweep = (
            get_sweep_and_structure(m15_data, h1_data, sweep_pool["level"], side)
            if callable(get_sweep_and_structure) and m15_data is not None and h1_data is not None
            else None
        )
        sweep_gate_state = sweep.get("gate_state", "BLOCK") if sweep else "BLOCK"
        sweep_gate_reason = sweep.get("gate_reason", "No sweep or CHoCH detected") if sweep else "No sweep or CHoCH detected"
        if sweep_gate_state == "WATCH":
            analysis["layer_failed"] = "L5_SWEEP_WAIT"
            analysis["fail_reason"] = sweep_gate_reason
            analysis["signal_type"] = "PRE_ENTRY"
            print_layer_result(5, "Sweep/CHoCH/BOS", "WAIT", sweep_gate_reason)
            print_no_signal("Sweep zone is active but not confirmed yet", "L5_SWEEP_WAIT")
            return analysis
        if not sweep or (not sweep.get("sweep_confirmed") and not sweep.get("choch_confirmed")):
            analysis["layer_failed"] = "L5_SWEEP"
            analysis["fail_reason"] = sweep_gate_reason
            analysis["signal_type"] = "PRE_ENTRY"
            print_layer_result(5, "Sweep/CHoCH/BOS", "BLOCK", sweep_gate_reason or "Waiting for liquidity sweep or structure break")
            print_no_signal("No sweep or CHoCH detected yet", "L5_SWEEP")
            return analysis
        
        # FIX #1: Validate sweep direction matches entry side (if sweep_confirmed)
        if sweep.get("sweep_confirmed"):
            sweep_type = sweep.get("sweep_type", "")
            if side == "BUY" and "bearish" in sweep_type.lower():
                analysis["layer_failed"] = "L5_SWEEP_DIRECTION"
                analysis["fail_reason"] = f"Bearish sweep on BUY signal"
                analysis["signal_type"] = "PRE_ENTRY"
                print_layer_result(5, "Sweep/CHoCH/BOS", "BLOCK", f"Direction mismatch: {sweep_type} on {side}")
                print_no_signal("Sweep direction mismatch", "L5_SWEEP_DIRECTION")
                return analysis
            if side == "SELL" and "bullish" in sweep_type.lower():
                analysis["layer_failed"] = "L5_SWEEP_DIRECTION"
                analysis["fail_reason"] = f"Bullish sweep on SELL signal"
                analysis["signal_type"] = "PRE_ENTRY"
                print_layer_result(5, "Sweep/CHoCH/BOS", "BLOCK", f"Direction mismatch: {sweep_type} on {side}")
                print_no_signal("Sweep direction mismatch", "L5_SWEEP_DIRECTION")
                return analysis
        analysis["layers_passed"].append("L5_SWEEP")
        analysis["layer_5"] = {
            "sweep_confirmed": sweep.get("sweep_confirmed"),
            "setup_grade": sweep.get("setup_grade"),
            "state": sweep_gate_state,
            "gate_reason": sweep_gate_reason,
        }
        sweep_status = "CONFIRMED" if sweep.get("sweep_confirmed") else "CHOCH"
        setup_grade = sweep.get("setup_grade", "N/A")
        print_layer_result(5, "Sweep/CHoCH", "PASS", f"{sweep_status} (setup grade: {setup_grade})")
        
        # ============ LAYER 6: POI ============
        poi = (
            identify_poi(m15_data, h1_data=h1_data, direction=side, current_price=current_price)
            if callable(identify_poi) and m15_data is not None
            else {}
        )
        best_poi = poi.get("best_poi")
        poi_reason, poi_details = (
            format_poi_layer_detail(poi, current_price)
            if callable(format_poi_layer_detail)
            else ("POI scan", "")
        )
        analysis["layer_6"] = build_poi_layer_data(poi) if callable(build_poi_layer_data) else {}
        if not best_poi or best_poi.get("score", 0) < 70:
            analysis["layer_failed"] = "L6_POI"
            poi_score = best_poi.get("score", 0) if best_poi else 0
            analysis["fail_reason"] = f"POI score too low ({poi_score:.0f} < 70)"
            analysis["signal_type"] = "PRE_ENTRY"
            block_reason = poi_reason if best_poi else f"No POI >= 70 (best {poi_score:.0f}/100)"
            print_layer_result(6, "POI Quality", "BLOCK", block_reason, poi_details)
            print_no_signal("No high-quality Point of Interest identified", "L6_POI")
            return analysis
        analysis["layers_passed"].append("L6_POI")
        print_layer_result(6, "POI Quality", "PASS", poi_reason, poi_details)
        
        # ============ LAYER 7: CONFIDENCE ============
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
                session=_normalize_session_for_conf(session),
                structure_valid=bool(struct.get("structure_valid", False)),
                has_fib_confluence=bool(poi_fib.get("has_fib_confluence", False)),
                rsi_value=intraday_rsi,
            )
            if callable(get_confidence_engine)
            else {}
        )
        if conf.get("grade") == "REJECT":
            analysis["layer_failed"] = "L7_CONFIDENCE"
            conf_score = conf.get('final_score', 0)
            analysis["fail_reason"] = f"Confidence score too low ({conf_score:.1f} < 70)"
            analysis["signal_type"] = "PRE_ENTRY"
            print_layer_result(7, "Confidence", "BLOCK", f"Score {conf_score:.1f}/100 - REJECT grade")
            print_no_signal("Setup confidence below threshold", "L7_CONFIDENCE")
            return analysis
        analysis["layers_passed"].append("L7_CONFIDENCE")
        analysis["layer_7"] = {
            "score": conf.get("final_score"),
            "grade": conf.get("grade"),
            "fib_confluence": poi_fib,
            "rsi_value": intraday_rsi,
        }
        conf_score = conf.get('final_score', 0)
        conf_grade = conf.get('grade', 'N/A')
        fib_note = "FIB" if poi_fib.get("has_fib_confluence") else "no FIB"
        rsi_note = f"RSI: {intraday_rsi:.1f}" if intraday_rsi is not None else "RSI: N/A"
        print_layer_result(7, "Confidence", "PASS", f"Score: {conf_score:.1f}/100 ({conf_grade} grade, {fib_note}, {rsi_note})")
        
        # ============ LAYER 8: ENTRY TRIGGER ============
        confirmed_m5_close = float(m5_data.iloc[-2]["close"]) if m5_data is not None and len(m5_data) >= 2 else current_price
        entry = (
            get_entry_trigger(
                m5_data=m5_data,
                m1_data=m1_data,
                current_price=confirmed_m5_close,
                direction=side,
                sweep_wick_low=sweep.get("sweep_wick_low") if sweep else None,
                sweep_wick_high=sweep.get("sweep_wick_high") if sweep else None,
            )
            if callable(get_entry_trigger) and m5_data is not None and m1_data is not None
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
        trigger_type = entry.get("trigger_type", "N/A")
        rr_ratio = entry.get("reward_to_risk_ratio", 0)
        print_layer_result(8, "Entry Trigger", "PASS", f"{entry.get('setup_type', 'REJECTED')} | {entry.get('entry_style', 'NONE')} confirmed (RR: 1:{rr_ratio:.1f})")
        
        # ============ ALL LAYERS PASSED - GENERATE ENTRY SIGNAL ============
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
            "poi_type": l6_poi_type,
            "timestamp": datetime.now().isoformat()
        }
        
        print_entry_signal(analysis['entry_signal'])
        logger.info(f"[+] ENTRY SIGNAL: {analysis['entry_signal']['position_type']} "
                   f"@ {analysis['entry_signal']['entry_price']:.2f} "
                   f"| {analysis['entry_signal']['setup_type']} / {analysis['entry_signal']['entry_mode']} "
                   f"RR: {analysis['entry_signal']['rr_ratio']:.1f}:1 ({analysis['entry_signal']['grade']} grade)")
        
    except Exception as e:
        analysis["layer_failed"] = "ERROR"
        analysis["fail_reason"] = str(e)
        logger.error(f"Error in entry analysis: {e}", exc_info=True)
    
    return analysis

# ============================================================
# POSITION MANAGEMENT (Layer 9)
# ============================================================

def manage_positions(open_trades: List[Dict], current_prices: Dict) -> List[Dict]:
    """Layer 9: Update all open positions with partial exit logic."""
    if not callable(manage_open_trade):
        return open_trades
    
    for trade in open_trades:
        try:
            current_price = current_prices.get(trade["trade_id"], trade.get("entry_price", 0))
            
            mgmt = manage_open_trade(
                trade_id=trade["trade_id"],
                current_price=current_price,
                entry_price=trade["entry_price"],
                original_stop_loss=trade["stop_loss"],
                take_profit=trade["take_profit"],
                entry_time=trade.get("entry_time", ""),
                position_type=trade.get("position_type", "BUY"),
                trade_state=trade.get("state")
            )
            
            trade["status"] = mgmt.get("trade_status", "OPEN")
            trade["actions"] = mgmt.get("actions", [])
            trade["state"] = mgmt.get("trade_state")
            trade["last_check"] = datetime.now().isoformat()
            
            # Log actions
            for action in mgmt.get("actions", []):
                logger.info(f"[{trade['trade_id']}] {action.get('action')}: {action.get('reason')}")
        
        except Exception as e:
            logger.error(f"Error managing position {trade.get('trade_id')}: {e}")
    
    return open_trades

# ============================================================
# SHUTDOWN
# ============================================================

def close_all_positions() -> bool:
    """Close all open positions before shutdown."""
    if not MT5_AVAILABLE:
        return True
    
    try:
        positions = mt5.positions_get(symbol=CONFIG["symbol"])
        if not positions:
            logger.info("[SHUTDOWN] No positions to close")
            return True
        
        logger.info(f"[SHUTDOWN] Closing {len(positions)} position(s)...")
        
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
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[+] Position {pos.ticket} closed")
            else:
                logger.warning(f"[-] Failed to close position {pos.ticket}: {result.comment}")
        
        return True
    
    except Exception as e:
        logger.error(f"Error during position closure: {e}")
        return False

def signal_handler(sig, frame):
    """Handle shutdown signal."""
    global _SHOULD_CONTINUE
    logger.info("[SIGNAL] Shutdown signal received")
    _SHOULD_CONTINUE = False
    close_all_positions()
    if MT5_AVAILABLE:
        shutdown_mt5()
    sys.exit(0)

# ============================================================
# MAIN BOT LOOP
# ============================================================

def main():
    """Main bot orchestration loop."""
    global _SHOULD_CONTINUE
    
    logger.info("="*70)
    logger.info("10-LAYER TRADING BOT STARTING")
    logger.info("="*70)
    
    # Print system status
    logger.info(f"[CONFIG] Symbol: {CONFIG['symbol']}")
    logger.info(f"[CONFIG] Max Concurrent: {CONFIG['max_concurrent_trades']}")
    logger.info(f"[CONFIG] Max Daily Loss: {CONFIG['max_daily_loss_percent']}%")
    logger.info(f"[STATUS] Layers Available: {LAYERS_AVAILABLE}")
    logger.info(f"[STATUS] MT5 Available: {MT5_AVAILABLE}")
    
    # Setup signal handlers
    signal_module.signal(signal_module.SIGINT, signal_handler)
    signal_module.signal(signal_module.SIGTERM, signal_handler)
    
    # Connect to MT5 if available
    if MT5_AVAILABLE:
        if not connect_mt5():
            logger.error("Failed to connect to MT5")
            return
    
    open_trades = []
    iteration_count = 0
    
    logger.info("="*70)
    logger.info("BOT READY - Waiting for market data")
    logger.info("="*70)
    
    while _SHOULD_CONTINUE:
        try:
            iteration_count += 1
            now = datetime.now()
            
            # Layer 0: Pre-trade gates
            gate_check = check_pre_trade_gates()
            
            if not gate_check["all_gates_passed"]:
                logger.warning(f"[L0] Trading blocked: {gate_check['gates_failed']}")
                time.sleep(60)
                continue
            
            # Check entry if slots available
            if len(open_trades) < CONFIG["max_concurrent_trades"]:
                if MT5_AVAILABLE:
                    try:
                        h4_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H4, CONFIG["h4_candles_required"])
                        h1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_H1, CONFIG["h1_candles_required"])
                        m15_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M15, CONFIG["m15_candles_required"])
                        m5_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M5, CONFIG["m5_candles_required"])
                        m1_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_M1, CONFIG["m1_candles_required"])
                        daily_data = get_market_data(CONFIG["symbol"], mt5.TIMEFRAME_D1, 10)
                    except Exception as e:
                        logger.warning(f"Error fetching market data: {e}")
                        time.sleep(10)
                        continue
                else:
                    # Demo mode - no real data
                    h4_data = h1_data = m15_data = m5_data = m1_data = daily_data = None
                
                # Get current price
                try:
                    current_price = get_current_price(CONFIG["symbol"]) if MT5_AVAILABLE else 0
                except:
                    current_price = h1_data.iloc[-1]['close'] if h1_data is not None and len(h1_data) > 0 else 0
                
                # Analyze entry with detailed output
                analysis = analyze_entry(h4_data, h1_data, m15_data, m5_data, m1_data, daily_data, current_price)
                print_run_summary(analysis)
                
                # Log signal
                l6_data = analysis.get("layer_6", {})
                l6_poi_type = l6_data.get("poi_type", "N/A") if l6_data else "N/A"
                l6_poi_score = l6_data.get("score", "N/A") if l6_data else "N/A"
                
                _append_signal_log("signal_log.csv", {
                    "timestamp": analysis.get("timestamp"),
                    "signal_type": analysis.get("signal_type"),
                    "layers_passed": ",".join(analysis.get("layers_passed", [])),
                    "layer_failed": analysis.get("layer_failed"),
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
                    "session": get_session_name(),
                    "position_type": analysis.get("entry_signal", {}).get("position_type") if analysis.get("entry_signal") else "N/A"
                })
                
                if analysis["signal_type"] == "ENTRY_SIGNAL":
                    # Create trade record
                    trade = {
                        "trade_id": f"XAUUSD_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        "entry_price": analysis["entry_signal"]["entry_price"],
                        "stop_loss": analysis["entry_signal"]["stop_loss"],
                        "take_profit": analysis["entry_signal"]["take_profit"],
                        "position_type": analysis["entry_signal"]["position_type"],
                        "entry_time": datetime.now().isoformat(),
                        "status": "OPEN",
                        "state": None
                    }
                    open_trades.append(trade)
                    logger.info(f"[ENTRY] Added trade: {trade['trade_id']}")
            
            # Manage positions (Layer 9)
            if open_trades:
                current_prices = {"spread": 0.5}  # Mock prices for demo
                open_trades = manage_positions(open_trades, current_prices)
                
                # Remove closed trades
                closed_trades = [t for t in open_trades if t.get("status") == "CLOSED"]
                open_trades = [t for t in open_trades if t.get("status") == "OPEN"]
                
                if closed_trades:
                    logger.info(f"[POSITIONS] {len(closed_trades)} trade(s) closed")
            
            logger.debug(f"[ITERATION {iteration_count}] Open trades: {len(open_trades)} | Session: {get_session_name()}")
            
            # Wait before next iteration
            time.sleep(30)
        
        except KeyboardInterrupt:
            logger.info("[MAIN] Keyboard interrupt received")
            _SHOULD_CONTINUE = False
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(10)
    
    # Cleanup
    logger.info("[SHUTDOWN] Closing positions...")
    close_all_positions()
    if MT5_AVAILABLE:
        shutdown_mt5()
    
    logger.info("="*70)
    logger.info("BOT STOPPED")
    logger.info("="*70)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("10-LAYER HYBRID TRADING BOT")
    print("="*70)
    print("\n[SYSTEM STATUS]")
    print(f"  Layers Available: {LAYERS_AVAILABLE}")
    print(f"  MT5 Available: {MT5_AVAILABLE}")
    print(f"  Configuration: XAUUSD, Max {CONFIG['max_concurrent_trades']} concurrent trades")
    print("\n[LAYERS]")
    print("  [+] Layer 0: Pre-Trade Gates")
    print("  [+] Layer 1: H4 Bias Engine")
    print("  [+] Layer 2: H1 Structure")
    print("  [+] Layer 3: M15 Pullback")
    print("  [+] Layer 4: Liquidity Engine")
    print("  [+] Layer 5: Sweep Detector")
    print("  [+] Layer 6: POI Quality")
    print("  [+] Layer 7: Confidence Score")
    print("  [+] Layer 8: Entry Triggers")
    print("  [+] Layer 9: Trade Manager")
    print("  [+] Layer 10: Feedback Loop")
    print("\n" + "="*70)
    
    if not LAYERS_AVAILABLE:
        print("[WARNING] Layer modules not fully available")
        print("Run in demo mode for testing\n")
    
    main()
