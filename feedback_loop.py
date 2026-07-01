"""
LAYER 10: FEEDBACK LOOP ENGINE
Purpose: Weekly performance tracking and automated weight adjustment
Implements: Win rate tracking per setup type, auto-weighting based on performance

Key Functions:
  log_closed_trade() - Record completed trade with outcome and setup type
  calculate_weekly_performance() - Win rate, avg RR, by setup type
  auto_adjust_weights() - Reduce confidence weight if setup <45% WR
  get_performance_report() - Summary stats and recommendations
"""

import pandas as pd
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ============================================================
# TRADE LOGGING & RECORDING
# ============================================================

def log_closed_trade(
    trade_id: str,
    setup_type: str,  # "OB" (Order Block), "FVG", "Fib", "Breaker"
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    take_profit: float,
    position_type: str,  # "BUY" or "SELL"
    profit_loss_pips: float,
    close_reason: str,  # "SL_HIT", "1_1_EXIT", "1_2_EXIT", "1_3_EXIT", "BREAKEVEN"
    session: str,  # "LONDON", "NY", "ASIAN", "DEAD"
    entry_time: str,
    exit_time: str,
    confidence_grade: str,  # "A+", "A", "REJECT"
    pnl_percent: float = None  # Optional: profit as % of risk
) -> Dict:
    """
    Log a closed trade for performance tracking.
    
    Args:
        trade_id: Unique trade identifier
        setup_type: POI type that triggered entry
        entry_price: Entry execution price
        exit_price: Exit execution price
        stop_loss: SL level used
        take_profit: TP level used
        position_type: Direction
        profit_loss_pips: Net profit/loss in pips
        close_reason: Why position was closed
        session: Trading session
        entry_time: ISO format
        exit_time: ISO format
        confidence_grade: Final grade before entry
        pnl_percent: ROE% (profit as % of risk)
    
    Returns:
        Dict with logged trade record
    """
    try:
        entry_price = float(entry_price)
        exit_price = float(exit_price)
        stop_loss = float(stop_loss)
        take_profit = float(take_profit)
        profit_loss_pips = float(profit_loss_pips)
    except (ValueError, TypeError):
        return {"success": False, "reason": "Invalid price inputs"}
    
    # Calculate RR if not provided
    if position_type == "BUY":
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
    else:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
    
    if risk > 0:
        rr_ratio = reward / risk
    else:
        rr_ratio = 0
    
    # Calculate actual RR achieved
    if close_reason == "SL_HIT":
        actual_rr = -1.0  # Loss
        outcome = "LOSS"
    else:
        if risk > 0:
            actual_rr = profit_loss_pips / risk
        else:
            actual_rr = 0
        outcome = "WIN" if profit_loss_pips > 0 else "LOSS"
    
    trade_record = {
        "trade_id": trade_id,
        "setup_type": setup_type,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_type": position_type,
        "profit_loss_pips": profit_loss_pips,
        "close_reason": close_reason,
        "session": session,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "confidence_grade": confidence_grade,
        "expected_rr": rr_ratio,
        "actual_rr": actual_rr,
        "outcome": outcome,
        "timestamp_logged": datetime.now().isoformat()
    }
    
    return {
        "success": True,
        "trade_record": trade_record,
        "summary": f"{outcome}: {setup_type} in {session} (RR: {actual_rr:.2f}:1)"
    }


# ============================================================
# PERFORMANCE ANALYSIS
# ============================================================

def calculate_weekly_performance(
    trade_records: List[Dict],
    lookback_days: int = 7
) -> Dict:
    """
    Calculate weekly performance metrics grouped by setup type.
    
    Args:
        trade_records: List of closed trade dicts from log_closed_trade()
        lookback_days: How many days back to analyze
    
    Returns:
        Dict with performance by setup type: win rate, avg RR, profit factor, etc.
    """
    if not trade_records:
        return {
            "period": f"Last {lookback_days} days",
            "total_trades": 0,
            "setup_performance": {},
            "recommendation": "No closed trades yet"
        }
    
    # Filter to lookback period
    cutoff_time = datetime.now() - timedelta(days=lookback_days)
    recent_trades = []
    
    for record in trade_records:
        try:
            exit_time = datetime.fromisoformat(record["exit_time"])
            if exit_time >= cutoff_time:
                recent_trades.append(record)
        except (ValueError, KeyError):
            continue
    
    if not recent_trades:
        return {
            "period": f"Last {lookback_days} days",
            "total_trades": 0,
            "setup_performance": {},
            "recommendation": "No recent trades in period"
        }
    
    # Group by setup type
    by_setup = defaultdict(list)
    for record in recent_trades:
        setup = record.get("setup_type", "UNKNOWN")
        by_setup[setup].append(record)
    
    # Calculate stats per setup
    setup_performance = {}
    
    for setup_type, records in by_setup.items():
        wins = sum(1 for r in records if r["outcome"] == "WIN")
        losses = sum(1 for r in records if r["outcome"] == "LOSS")
        breakeven = sum(1 for r in records if r.get("close_reason") == "BREAKEVEN")
        total = len(records)
        
        # Win rate of decisive trades only (exclude breakeven)
        decisive = wins + losses
        win_rate = wins / decisive * 100 if decisive > 0 else 0
        
        # Average RR for winning trades
        winning_rr = [r["actual_rr"] for r in records if r["outcome"] == "WIN" and r["actual_rr"] > 0]
        avg_winning_rr = sum(winning_rr) / len(winning_rr) if winning_rr else 0
        
        # Losing RR
        losing_rr = [r["actual_rr"] for r in records if r["outcome"] == "LOSS"]
        avg_losing_rr = sum(losing_rr) / len(losing_rr) if losing_rr else -1.0
        
        # Profit factor (total wins / total losses)
        total_win_pips = sum(r["profit_loss_pips"] for r in records if r["outcome"] == "WIN")
        total_loss_pips = abs(sum(r["profit_loss_pips"] for r in records if r["outcome"] == "LOSS"))
        
        profit_factor = total_win_pips / total_loss_pips if total_loss_pips > 0 else 0
        
        setup_performance[setup_type] = {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate_percent": win_rate,
            "avg_winning_rr": avg_winning_rr,
            "avg_losing_rr": avg_losing_rr,
            "total_win_pips": total_win_pips,
            "total_loss_pips": total_loss_pips,
            "profit_factor": profit_factor,
            "status": get_setup_status(win_rate),
            "recommendation": get_setup_recommendation(win_rate, total)
        }
    
    # Overall stats
    total_trades = len(recent_trades)
    overall_wins = sum(1 for r in recent_trades if r["outcome"] == "WIN")
    overall_win_rate = overall_wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        "period": f"Last {lookback_days} days",
        "analysis_timestamp": datetime.now().isoformat(),
        "total_trades": total_trades,
        "overall_win_rate_percent": overall_win_rate,
        "setup_performance": setup_performance,
        "recommendation": get_overall_recommendation(overall_win_rate)
    }


# ============================================================
# AUTO-WEIGHT ADJUSTMENT
# ============================================================

def auto_adjust_weights(
    performance_report: Dict,
    current_weights: Dict = None
) -> Dict:
    """
    Auto-adjust confidence weights based on setup performance.
    If a setup type <45% WR: reduce its weight in future confidence calculations.
    
    Args:
        performance_report: Output from calculate_weekly_performance()
        current_weights: Current confidence formula weights
                        Default: {bias: 0.25, structure: 0.20, sweep: 0.20, poi: 0.20, session: 0.10}
    
    Returns:
        Dict with original weights, recommended adjustments, and rationale
    """
    if current_weights is None:
        current_weights = {
            "bias": 0.25,
            "structure": 0.20,
            "sweep": 0.20,
            "poi": 0.20,
            "session": 0.10
        }
    
    adjustments = {}
    rationale = []
    
    setup_perf = performance_report.get("setup_performance", {})
    
    for setup_type, perf in setup_perf.items():
        win_rate = perf["win_rate_percent"]
        total = perf["total_trades"]
        
        # Only adjust if enough sample size (5+ trades)
        if total < 5:
            adjustments[setup_type] = {
                "current_weight": 1.0,  # Base weight per setup
                "recommended_weight": 1.0,
                "change_percent": 0,
                "reason": "Insufficient sample size (<5 trades)"
            }
            continue
        
        # Scoring rules
        if win_rate < 40:
            # Severely underperforming: reduce by 50%
            recommended = 0.5
            rationale.append(f"{setup_type}: CRITICAL - Only {win_rate:.1f}% WR ({total} trades)")
        elif win_rate < 50:
            # Underperforming: reduce by 25%
            recommended = 0.75
            rationale.append(f"{setup_type}: POOR - Only {win_rate:.1f}% WR ({total} trades)")
        elif win_rate < 60:
            # Below target: reduce by 10%
            recommended = 0.90
            rationale.append(f"{setup_type}: BELOW TARGET - {win_rate:.1f}% WR ({total} trades)")
        else:
            # Meeting/exceeding target: no adjustment
            recommended = 1.0
            rationale.append(f"{setup_type}: GOOD - {win_rate:.1f}% WR ({total} trades)")
        
        change_percent = (recommended - 1.0) * 100
        
        adjustments[setup_type] = {
            "current_weight": 1.0,
            "recommended_weight": recommended,
            "change_percent": change_percent,
            "win_rate_percent": win_rate,
            "sample_size": total
        }
    
    # Overall confidence weight adjustment
    overall_wr = performance_report.get("overall_win_rate_percent", 0)
    
    if overall_wr >= 65:
        confidence_multiplier = 1.0  # No change, system is working
        conf_rationale = "System performing excellently (≥65% WR)"
    elif overall_wr >= 60:
        confidence_multiplier = 0.95  # Slight decrease
        conf_rationale = "System meeting target (60-64% WR)"
    elif overall_wr >= 55:
        confidence_multiplier = 0.85  # Moderate decrease
        conf_rationale = "System slightly below target (55-59% WR)"
    else:
        confidence_multiplier = 0.70  # Significant decrease
        conf_rationale = "System needs review (<55% WR)"
    
    return {
        "period": performance_report.get("period"),
        "current_weights": current_weights,
        "setup_adjustments": adjustments,
        "overall_confidence_multiplier": confidence_multiplier,
        "confidence_adjustment_reason": conf_rationale,
        "rationale": rationale,
        "recommendation": generate_weight_recommendation(adjustments, confidence_multiplier)
    }


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_setup_status(win_rate: float) -> str:
    """Classify setup performance."""
    if win_rate >= 65:
        return "EXCELLENT"
    elif win_rate >= 60:
        return "GOOD"
    elif win_rate >= 50:
        return "ACCEPTABLE"
    elif win_rate >= 45:
        return "POOR"
    else:
        return "CRITICAL"


def get_setup_recommendation(win_rate: float, total_trades: int) -> str:
    """Get recommendation for specific setup type."""
    if total_trades < 5:
        return "Collect more data (need ≥5 trades)"
    
    if win_rate >= 65:
        return "✓ Prioritize this setup - strong performer"
    elif win_rate >= 60:
        return "✓ Continue - meets target"
    elif win_rate >= 50:
        return "⚠ Monitor - acceptable but room for improvement"
    elif win_rate >= 45:
        return "✗ Reduce weight - underperforming"
    else:
        return "✗✗ CRITICAL - Consider removing or reworking logic"


def get_overall_recommendation(win_rate: float) -> str:
    """Get overall system recommendation."""
    if win_rate >= 65:
        return "SYSTEM EXCELLENT - Maintain current weights, scale up"
    elif win_rate >= 60:
        return "SYSTEM GOOD - Meeting targets, monitor adjustments"
    elif win_rate >= 55:
        return "SYSTEM ACCEPTABLE - Review underperforming setups"
    else:
        return "SYSTEM REVIEW NEEDED - Investigate root causes, test smaller size"


def generate_weight_recommendation(adjustments: Dict, multiplier: float) -> str:
    """Generate actionable weight adjustment recommendation."""
    reduced_setups = [
        setup for setup, adj in adjustments.items()
        if adj["recommended_weight"] < 1.0
    ]
    
    if not reduced_setups:
        return "No adjustments needed - all setups performing well"
    
    msg = f"Reduce weight for: {', '.join(reduced_setups)}"
    if multiplier < 1.0:
        msg += f"\nApply {multiplier*100:.0f}% confidence multiplier overall"
    
    return msg


# ============================================================
# PERFORMANCE REPORTING
# ============================================================

def get_performance_report(
    trade_records: List[Dict],
    current_weights: Dict = None,
    lookback_days: int = 7
) -> Dict:
    """
    Generate comprehensive weekly performance report with auto-adjustments.
    
    Args:
        trade_records: All closed trade records
        current_weights: Current confidence weights
        lookback_days: Analysis period
    
    Returns:
        Complete report with performance, adjustments, and recommendations
    """
    # Calculate performance
    perf = calculate_weekly_performance(trade_records, lookback_days)
    
    # Generate auto-adjustments
    adjustments = auto_adjust_weights(perf, current_weights)
    
    return {
        "report_generated": datetime.now().isoformat(),
        "performance": perf,
        "weight_adjustments": adjustments,
        "next_review": (datetime.now() + timedelta(days=7)).isoformat()
    }


# ============================================================
# TEST/DEMO
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("[FEEDBACK LOOP] Layer 10 - Automated Performance Tracking")
    print("="*70)
    
    # Simulate closed trades
    print("\n[DEMO] Logging simulated trades...")
    print("-" * 70)
    
    trade_records = []
    
    # Order Block setups: Good performance (65% WR)
    for i in range(10):
        outcome = "WIN" if i < 7 else "LOSS"  # 7 wins, 3 losses
        pips = 50 if outcome == "WIN" else -30
        record = log_closed_trade(
            trade_id=f"OB_{i+1:03d}",
            setup_type="OB",
            entry_price=2450.00,
            exit_price=2450.00 + (pips * 0.01 if pips > 0 else pips * 0.01),
            stop_loss=2420.00,
            take_profit=2540.00,
            position_type="BUY",
            profit_loss_pips=pips,
            close_reason="1_3_EXIT" if outcome == "WIN" else "SL_HIT",
            session="LONDON",
            entry_time=(datetime.now() - timedelta(days=1)).isoformat(),
            exit_time=datetime.now().isoformat(),
            confidence_grade="A+",
            pnl_percent=None
        )
        if record["success"]:
            trade_records.append(record["trade_record"])
    
    # FVG setups: Poor performance (40% WR)
    for i in range(5):
        outcome = "WIN" if i < 2 else "LOSS"  # 2 wins, 3 losses
        pips = 45 if outcome == "WIN" else -25
        record = log_closed_trade(
            trade_id=f"FVG_{i+1:03d}",
            setup_type="FVG",
            entry_price=2460.00,
            exit_price=2460.00 + (pips * 0.01 if pips > 0 else pips * 0.01),
            stop_loss=2430.00,
            take_profit=2550.00,
            position_type="BUY",
            profit_loss_pips=pips,
            close_reason="1_3_EXIT" if outcome == "WIN" else "SL_HIT",
            session="NY",
            entry_time=(datetime.now() - timedelta(days=2)).isoformat(),
            exit_time=(datetime.now() - timedelta(days=1)).isoformat(),
            confidence_grade="A",
            pnl_percent=None
        )
        if record["success"]:
            trade_records.append(record["trade_record"])
    
    print(f"✓ Logged {len(trade_records)} trade records\n")
    
    # Calculate performance
    print("[PERFORMANCE ANALYSIS]")
    print("-" * 70)
    perf = calculate_weekly_performance(trade_records, lookback_days=7)
    
    print(f"Period: {perf['period']}")
    print(f"Total Trades: {perf['total_trades']}")
    print(f"Overall Win Rate: {perf['overall_win_rate_percent']:.1f}%\n")
    
    for setup, stats in perf["setup_performance"].items():
        print(f"  {setup}:")
        print(f"    Trades: {stats['total_trades']} ({stats['wins']}W-{stats['losses']}L)")
        print(f"    Win Rate: {stats['win_rate_percent']:.1f}%")
        print(f"    Avg Winning RR: {stats['avg_winning_rr']:.2f}:1")
        print(f"    Status: {stats['status']}")
        print(f"    {stats['recommendation']}\n")
    
    # Auto-adjust weights
    print("[AUTO-WEIGHT ADJUSTMENT]")
    print("-" * 70)
    adjustments = auto_adjust_weights(perf)
    
    for setup, adj in adjustments.get("setup_adjustments", {}).items():
        print(f"  {setup}:")
        print(f"    Current Weight: {adj['current_weight']:.2f}")
        print(f"    Recommended: {adj['recommended_weight']:.2f} ({adj['change_percent']:+.0f}%)\n")
    
    print(f"Overall Confidence Multiplier: {adjustments['overall_confidence_multiplier']:.2f}")
    print(f"Reason: {adjustments['confidence_adjustment_reason']}\n")
    
    print("\n" + "="*70)
    print("✅ Layer 10 Feedback Loop Ready!")
    print("="*70)
