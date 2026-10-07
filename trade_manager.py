"""
LAYER 9: TRADE MANAGEMENT ENGINE
Purpose: Manage open trades with strategic partial exits and SL adjustments
Implements: Partial exits at 1:1, 1:2, 1:3 RR with SL management + breakeven protection

Key Functions:
  manage_open_trade() - Main interface for trade state management
  check_partial_exit_1_1() - Close 50% at 1:1 RR, move SL to breakeven
  check_partial_exit_1_2() - Trail SL at 1:2 RR (lock 50% of leg 2)
  check_final_exit_1_3() - Close remaining at 1:3 RR
  check_breakeven_stop() - Close at breakeven if price returns to entry
  close_position() - Execute position close with logging
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import json

# ============================================================
# PARTIAL EXIT LOGIC - 1:1 RATIO
# ============================================================

def check_partial_exit_1_1(
    current_price: float,
    entry_price: float,
    take_profit: float,
    stop_loss: float,
    position_type: str = "BUY"
) -> Dict:
    """
    Check if 1:1 reward-to-risk reached.
    If yes: Close 50% position, move SL to breakeven.
    
    Args:
        current_price: Current market price
        entry_price: Entry price
        take_profit: Original TP level
        stop_loss: Current SL (may have been adjusted)
        position_type: "BUY" or "SELL"
    
    Returns:
        Dict with exit_1_1_triggered, exit_price, new_sl, recommendation
    """
    try:
        current_price = float(current_price)
        entry_price = float(entry_price)
        take_profit = float(take_profit)
        stop_loss = float(stop_loss)
    except (ValueError, TypeError):
        return {
            "exit_1_1_triggered": False,
            "reason": "Invalid price inputs"
        }
    
    if position_type == "BUY":
        # BUY: Entry < TP
        # 1:1 RR = entry + (entry - sl)
        risk_distance = entry_price - stop_loss
        if risk_distance <= 0:
            return {"exit_1_1_triggered": False, "reason": "Invalid SL"}
        
        rr_1_1_level = entry_price + risk_distance
        
        if current_price >= rr_1_1_level:
            return {
                "exit_1_1_triggered": True,
                "exit_price": rr_1_1_level,
                "position_size_close": 0.5,  # Close 50%
                "new_stop_loss": entry_price,  # Move SL to BE
                "reason": f"1:1 RR reached (price {current_price:.2f} >= {rr_1_1_level:.2f})",
                "profit_pips": risk_distance,
                "new_risk": 0.0,  # Breakeven = no more risk
                "recommendation": "CLOSE 50%, MOVE SL TO BREAKEVEN"
            }
    
    elif position_type == "SELL":
        # SELL: Entry > TP
        # 1:1 RR = entry - (sl - entry)
        risk_distance = stop_loss - entry_price
        if risk_distance <= 0:
            return {"exit_1_1_triggered": False, "reason": "Invalid SL"}
        
        rr_1_1_level = entry_price - risk_distance
        
        if current_price <= rr_1_1_level:
            return {
                "exit_1_1_triggered": True,
                "exit_price": rr_1_1_level,
                "position_size_close": 0.5,  # Close 50%
                "new_stop_loss": entry_price,  # Move SL to BE
                "reason": f"1:1 RR reached (price {current_price:.2f} <= {rr_1_1_level:.2f})",
                "profit_pips": risk_distance,
                "new_risk": 0.0,  # Breakeven = no more risk
                "recommendation": "CLOSE 50%, MOVE SL TO BREAKEVEN"
            }
    
    return {
        "exit_1_1_triggered": False,
        "reason": f"1:1 RR not reached yet (current: {current_price:.2f})"
    }


# ============================================================
# SL TRAILING - 1:2 RATIO
# ============================================================

def check_partial_exit_1_2(
    current_price: float,
    entry_price: float,
    take_profit: float,
    stop_loss: float,
    position_type: str = "BUY",
    current_sl_status: str = "breakeven"  # "original", "breakeven", "trailing"
) -> Dict:
    """
    Check if 1:2 reward-to-risk reached.
    If yes and SL at breakeven: Trail SL to 50% of leg 2 (lock partial profits).
    
    Args:
        current_price: Current market price
        entry_price: Entry price
        take_profit: Original TP (full target)
        stop_loss: Current SL position
        position_type: "BUY" or "SELL"
        current_sl_status: Where SL currently is ("original", "breakeven", "trailing")
    
    Returns:
        Dict with exit_1_2_triggered, new_sl, locked_profit, recommendation
    """
    try:
        current_price = float(current_price)
        entry_price = float(entry_price)
        take_profit = float(take_profit)
        stop_loss = float(stop_loss)
    except (ValueError, TypeError):
        return {
            "exit_1_2_triggered": False,
            "reason": "Invalid price inputs"
        }
    
    if position_type == "BUY":
        # BUY: Entry < TP
        # 1:2 RR = entry + 2×(entry - original_sl)
        # But we need to calculate from current SL if it's been moved
        
        # If SL is at breakeven or original, calculate 1:2 from there
        original_risk = entry_price - stop_loss
        if original_risk <= 0:
            return {"exit_1_2_triggered": False, "reason": "Invalid SL"}
        
        rr_1_2_level = entry_price + (2 * original_risk)
        
        if current_price >= rr_1_2_level and current_sl_status in ["breakeven", "original"]:
            # Trail SL to 50% of leg 2
            # Leg 2 = from entry to (entry + 2×risk)
            # 50% of leg 2 = entry + risk
            new_sl = entry_price + original_risk
            locked_profit = new_sl - entry_price  # pips locked
            
            return {
                "exit_1_2_triggered": True,
                "exit_reason": "1:2 RR reached",
                "new_stop_loss": new_sl,
                "new_sl_status": "trailing",
                "locked_profit_pips": locked_profit,
                "reason": f"1:2 RR reached (price {current_price:.2f} >= {rr_1_2_level:.2f})",
                "recommendation": f"TRAIL SL TO {new_sl:.2f} (lock {locked_profit:.1f}p)"
            }
    
    elif position_type == "SELL":
        # SELL: Entry > TP
        # 1:2 RR = entry - 2×(sl - entry)
        original_risk = stop_loss - entry_price
        if original_risk <= 0:
            return {"exit_1_2_triggered": False, "reason": "Invalid SL"}
        
        rr_1_2_level = entry_price - (2 * original_risk)
        
        if current_price <= rr_1_2_level and current_sl_status in ["breakeven", "original"]:
            # Trail SL to 50% of leg 2
            new_sl = entry_price - original_risk
            locked_profit = entry_price - new_sl  # pips locked
            
            return {
                "exit_1_2_triggered": True,
                "exit_reason": "1:2 RR reached",
                "new_stop_loss": new_sl,
                "new_sl_status": "trailing",
                "locked_profit_pips": locked_profit,
                "reason": f"1:2 RR reached (price {current_price:.2f} <= {rr_1_2_level:.2f})",
                "recommendation": f"TRAIL SL TO {new_sl:.2f} (lock {locked_profit:.1f}p)"
            }
    
    return {
        "exit_1_2_triggered": False,
        "reason": "1:2 RR not reached yet"
    }


# ============================================================
# FINAL EXIT - 1:3 RATIO
# ============================================================

def check_final_exit_1_3(
    current_price: float,
    entry_price: float,
    take_profit: float,
    position_type: str = "BUY"
) -> Dict:
    """
    Check if 1:3 reward-to-risk reached (original full TP).
    If yes: Close remaining position.
    
    Args:
        current_price: Current market price
        entry_price: Entry price
        take_profit: Original TP level (full 1:3 target)
        position_type: "BUY" or "SELL"
    
    Returns:
        Dict with exit_1_3_triggered, exit_price, total_profit, recommendation
    """
    try:
        current_price = float(current_price)
        entry_price = float(entry_price)
        take_profit = float(take_profit)
    except (ValueError, TypeError):
        return {
            "exit_1_3_triggered": False,
            "reason": "Invalid price inputs"
        }
    
    if position_type == "BUY":
        # BUY: Close if price >= TP
        if current_price >= take_profit:
            profit = take_profit - entry_price
            return {
                "exit_1_3_triggered": True,
                "exit_price": take_profit,
                "position_size_close": 1.0,  # Close 100%
                "total_profit_pips": profit,
                "reason": f"1:3 RR reached (price {current_price:.2f} >= TP {take_profit:.2f})",
                "recommendation": "CLOSE ALL (1:3 TP HIT)"
            }
    
    elif position_type == "SELL":
        # SELL: Close if price <= TP
        if current_price <= take_profit:
            profit = entry_price - take_profit
            return {
                "exit_1_3_triggered": True,
                "exit_price": take_profit,
                "position_size_close": 1.0,  # Close 100%
                "total_profit_pips": profit,
                "reason": f"1:3 RR reached (price {current_price:.2f} <= TP {take_profit:.2f})",
                "recommendation": "CLOSE ALL (1:3 TP HIT)"
            }
    
    return {
        "exit_1_3_triggered": False,
        "reason": "1:3 TP not reached yet"
    }


# ============================================================
# BREAKEVEN PROTECTION
# ============================================================

def check_breakeven_stop(
    current_price: float,
    entry_price: float,
    stop_loss: float,
    position_type: str = "BUY",
    breakeven_trigger_pip_buffer: float = 2.0
) -> Dict:
    """
    Close position at breakeven + buffer if price retraces back.
    Protects against reversal after running favorably.
    
    Args:
        current_price: Current market price
        entry_price: Entry price
        stop_loss: Current SL
        position_type: "BUY" or "SELL"
        breakeven_trigger_pip_buffer: Close at entry ± this buffer
    
    Returns:
        Dict with breakeven_stop_triggered, close_price, reason
    """
    try:
        current_price = float(current_price)
        entry_price = float(entry_price)
        stop_loss = float(stop_loss)
        breakeven_trigger_pip_buffer = float(breakeven_trigger_pip_buffer)
    except (ValueError, TypeError):
        return {
            "breakeven_stop_triggered": False,
            "reason": "Invalid price inputs"
        }
    
    if position_type == "BUY":
        # BUY: Stop is below entry, so if price comes back to near entry = protect
        # Only trigger if: price was above entry, now coming back, AND SL was moved to BE
        if stop_loss >= entry_price - 1.0:  # SL at or near breakeven
            be_level = entry_price + breakeven_trigger_pip_buffer
            if current_price <= be_level and current_price > stop_loss:
                return {
                    "breakeven_stop_triggered": True,
                    "close_price": entry_price + breakeven_trigger_pip_buffer,
                    "reason": f"Breakeven stop: price {current_price:.2f} near entry {entry_price:.2f}",
                    "recommendation": "CLOSE AT BREAKEVEN (+buffer) to protect gains"
                }
    
    elif position_type == "SELL":
        # SELL: Stop is above entry, so if price comes back = protect
        if stop_loss <= entry_price + 1.0:  # SL at or near breakeven
            be_level = entry_price - breakeven_trigger_pip_buffer
            if current_price >= be_level and current_price < stop_loss:
                return {
                    "breakeven_stop_triggered": True,
                    "close_price": entry_price - breakeven_trigger_pip_buffer,
                    "reason": f"Breakeven stop: price {current_price:.2f} near entry {entry_price:.2f}",
                    "recommendation": "CLOSE AT BREAKEVEN (+buffer) to protect gains"
                }
    
    return {
        "breakeven_stop_triggered": False,
        "reason": "No breakeven trigger"
    }


# ============================================================
# MAIN TRADE MANAGEMENT FLOW
# ============================================================

def manage_open_trade(
    trade_id: str,
    current_price: float,
    entry_price: float,
    original_stop_loss: float,
    take_profit: float,
    entry_time: str,
    position_type: str = "BUY",
    trade_state: Dict = None
) -> Dict:
    """
    Main interface for managing a single open trade.
    Checks exit conditions in order: 1:1 partial → 1:2 trail → 1:3 final → breakeven stop.
    
    Args:
        trade_id: Unique trade identifier
        current_price: Current market price
        entry_price: Entry execution price
        original_stop_loss: Original SL (never changes, for RR calculation)
        take_profit: Full 1:3 TP level
        entry_time: When trade was entered (ISO format)
        position_type: "BUY" or "SELL"
        trade_state: Previous state dict (for tracking SL changes)
    
    Returns:
        Dict with full trade state and action recommendations
    """
    if trade_state is None:
        trade_state = {
            "position_size": 1.0,  # Full position size
            "current_sl": original_stop_loss,
            "sl_status": "original",
            "exit_1_1_taken": False,
            "exit_1_2_status": "pending",  # "pending", "sl_trailed", "completed"
            "profit_locked_1_2": 0.0
        }
    
    result = {
        "trade_id": trade_id,
        "timestamp": datetime.now().isoformat(),
        "entry_price": entry_price,
        "current_price": current_price,
        "position_type": position_type,
        "position_size": trade_state["position_size"],
        "actions": [],
        "updates": []
    }
    
    # Check SL hit (immediate close)
    if position_type == "BUY" and current_price <= trade_state["current_sl"]:
        result["actions"].append({
            "action": "CLOSE_ALL",
            "reason": "SL HIT",
            "exit_price": trade_state["current_sl"],
            "pnl": "LOSS"
        })
        result["trade_status"] = "CLOSED_SL"
        return result
    
    elif position_type == "SELL" and current_price >= trade_state["current_sl"]:
        result["actions"].append({
            "action": "CLOSE_ALL",
            "reason": "SL HIT",
            "exit_price": trade_state["current_sl"],
            "pnl": "LOSS"
        })
        result["trade_status"] = "CLOSED_SL"
        return result
    
    # Check 1:1 exit (if not already taken)
    if not trade_state["exit_1_1_taken"]:
        exit_1_1 = check_partial_exit_1_1(
            current_price, entry_price, take_profit, 
            trade_state["current_sl"], position_type
        )
        if exit_1_1.get("exit_1_1_triggered"):
            result["actions"].append({
                "action": "PARTIAL_CLOSE_50PCT",
                "reason": "1:1 RR REACHED",
                "exit_price": exit_1_1["exit_price"],
                "profit_pips": exit_1_1["profit_pips"]
            })
            result["updates"].append(f"SL moved to breakeven: {exit_1_1['new_stop_loss']:.2f}")
            
            trade_state["exit_1_1_taken"] = True
            trade_state["position_size"] = 0.5
            trade_state["current_sl"] = exit_1_1["new_stop_loss"]
            trade_state["sl_status"] = "breakeven"
    
    # Check 1:2 trail (if 1:1 taken and remaining position > 0)
    if trade_state["exit_1_1_taken"] and trade_state["exit_1_2_status"] == "pending":
        exit_1_2 = check_partial_exit_1_2(
            current_price, entry_price, take_profit,
            original_stop_loss, position_type, trade_state["sl_status"]
        )
        if exit_1_2.get("exit_1_2_triggered"):
            result["actions"].append({
                "action": "TRAIL_SL",
                "reason": "1:2 RR REACHED",
                "new_sl": exit_1_2["new_stop_loss"],
                "profit_locked": exit_1_2["locked_profit_pips"]
            })
            
            trade_state["current_sl"] = exit_1_2["new_stop_loss"]
            trade_state["sl_status"] = "trailing"
            trade_state["exit_1_2_status"] = "sl_trailed"
            trade_state["profit_locked_1_2"] = exit_1_2["locked_profit_pips"]
    
    # Check 1:3 exit (if still holding remaining position)
    if trade_state["position_size"] > 0:
        exit_1_3 = check_final_exit_1_3(
            current_price, entry_price, take_profit, position_type
        )
        if exit_1_3.get("exit_1_3_triggered"):
            result["actions"].append({
                "action": "CLOSE_ALL_REMAINING",
                "reason": "1:3 TP HIT",
                "exit_price": exit_1_3["exit_price"],
                "profit_pips": exit_1_3["total_profit_pips"]
            })
            trade_state["position_size"] = 0.0
    
    # Check breakeven stop (protection if reversal)
    if trade_state["position_size"] > 0 and trade_state["sl_status"] in ["breakeven", "trailing"]:
        be_stop = check_breakeven_stop(
            current_price, entry_price, trade_state["current_sl"],
            position_type, breakeven_trigger_pip_buffer=2.0
        )
        if be_stop.get("breakeven_stop_triggered"):
            result["actions"].append({
                "action": "CLOSE_BREAKEVEN_PROTECTION",
                "reason": "REVERSAL PROTECTION",
                "close_price": be_stop["close_price"]
            })
            trade_state["position_size"] = 0.0
    
    # Final status
    if trade_state["position_size"] == 0:
        result["trade_status"] = "CLOSED"
    else:
        result["trade_status"] = "OPEN"
    
    result["trade_state"] = trade_state
    
    return result


# ============================================================
# POSITION CLOSING & LOGGING
# ============================================================

def close_position(
    trade_id: str,
    closing_price: float,
    entry_price: float,
    position_type: str,
    close_reason: str,
    closing_time: str = None
) -> Dict:
    """
    Execute position close and calculate final PnL.
    
    Args:
        trade_id: Trade identifier
        closing_price: Close execution price
        entry_price: Original entry price
        position_type: "BUY" or "SELL"
        close_reason: Why position was closed
        closing_time: When position was closed (ISO format)
    
    Returns:
        Dict with closed trade details and PnL
    """
    if closing_time is None:
        closing_time = datetime.now().isoformat()
    
    try:
        closing_price = float(closing_price)
        entry_price = float(entry_price)
    except (ValueError, TypeError):
        return {"success": False, "reason": "Invalid price inputs"}
    
    if position_type == "BUY":
        profit_pips = closing_price - entry_price
        profit_direction = "WIN" if profit_pips > 0 else "LOSS"
    elif position_type == "SELL":
        profit_pips = entry_price - closing_price
        profit_direction = "WIN" if profit_pips > 0 else "LOSS"
    else:
        return {"success": False, "reason": "Invalid position type"}
    
    return {
        "success": True,
        "trade_id": trade_id,
        "entry_price": entry_price,
        "closing_price": closing_price,
        "position_type": position_type,
        "profit_pips": profit_pips,
        "profit_direction": profit_direction,
        "close_reason": close_reason,
        "closing_time": closing_time,
        "status": "CLOSED"
    }


# ============================================================
# TEST/DEMO
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("[TRADE MANAGER] Layer 9 - Trade Management Engine")
    print("="*60)
    
    # Mock BUY trade scenario
    print("\n[SCENARIO 1] BUY Trade - Follow partial exits")
    print("-" * 60)
    
    entry = 2450.00
    original_sl = 2420.00
    tp = 2540.00
    
    print(f"Entry: {entry:.2f} | SL: {original_sl:.2f} | TP: {tp:.2f}")
    print(f"Risk: {entry - original_sl:.1f}p | Reward: {tp - entry:.1f}p | RR: 3:1")
    
    # Price progresses: 2450 → 2470 (1:1) → 2490 (1:2) → 2540 (1:3)
    prices = [2470, 2490, 2540]
    trade_state = None
    
    for i, price in enumerate(prices, 1):
        print(f"\n  Price Update #{i}: {price:.2f}")
        result = manage_open_trade(
            trade_id="BUY_001",
            current_price=price,
            entry_price=entry,
            original_stop_loss=original_sl,
            take_profit=tp,
            entry_time="2026-05-26 10:00:00",
            position_type="BUY",
            trade_state=trade_state
        )
        
        for action in result.get("actions", []):
            print(f"    ✓ {action['action']}: {action['reason']}")
            if "exit_price" in action:
                print(f"      Exit: {action['exit_price']:.2f}")
            if "profit_pips" in action:
                print(f"      Profit: {action['profit_pips']:.1f}p")
            if "new_sl" in action:
                print(f"      New SL: {action['new_sl']:.2f}")
        
        for update in result.get("updates", []):
            print(f"    ℹ {update}")
        
        print(f"    Position: {result['trade_state']['position_size']:.1%} | Status: {result['trade_status']}")
        
        trade_state = result["trade_state"]
    
    print("\n" + "="*60)
    print("✅ Layer 9 Trade Manager Ready!")
    print("="*60)
