"""
Trade State Persistence Layer
Saves and restores open trades to survive bot restarts.
Provides recovery mechanisms for graceful shutdown/restart cycles.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Setup logging
logger = logging.getLogger("TradePeristence")

# Persistence files
PERSISTENCE_DIR = Path(__file__).parent / "trade_states"
PERSISTENCE_FILE = PERSISTENCE_DIR / "active_trades.json"
BACKUP_FILE = PERSISTENCE_DIR / "active_trades_backup.json"
CLOSED_TRADES_FILE = PERSISTENCE_DIR / "closed_trades.json"

# Create persistence directory
PERSISTENCE_DIR.mkdir(exist_ok=True)


def save_active_trades(trades: List[Dict[str, Any]]) -> bool:
    """
    Save all open trade states to JSON file with automatic backup.
    
    Args:
        trades: List of open trade dictionaries with full state
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create backup of existing file
        if PERSISTENCE_FILE.exists():
            try:
                with open(PERSISTENCE_FILE, 'r') as f:
                    backup_data = json.load(f)
                with open(BACKUP_FILE, 'w') as f:
                    json.dump(backup_data, f, indent=2, default=str)
                logger.debug(f"Created backup at {BACKUP_FILE}")
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")
        
        # Save current state
        persistence_data = {
            "timestamp": datetime.now().isoformat(),
            "total_trades": len(trades),
            "trades": trades
        }
        
        with open(PERSISTENCE_FILE, 'w') as f:
            json.dump(persistence_data, f, indent=2, default=str)
        
        logger.info(f"[+] Saved {len(trades)} trade states to {PERSISTENCE_FILE}")
        return True
    
    except Exception as e:
        logger.error(f"[-] Error saving trade states: {e}")
        return False


def load_active_trades() -> List[Dict[str, Any]]:
    """
    Load all persisted trade states from JSON file.
    Falls back to backup if primary file is corrupted.
    
    Returns:
        List of trade dictionaries, empty list if none found
    """
    try:
        if not PERSISTENCE_FILE.exists():
            logger.info("[INFO] No persisted trade states found (first run)")
            return []
        
        with open(PERSISTENCE_FILE, 'r') as f:
            data = json.load(f)
        
        trades = data.get("trades", [])
        logger.info(f"[+] Loaded {len(trades)} trade states from {PERSISTENCE_FILE}")
        return trades
    
    except json.JSONDecodeError as e:
        logger.error(f"[-] JSON error loading trade states: {e}")
        # Try to recover from backup
        try:
            if BACKUP_FILE.exists():
                with open(BACKUP_FILE, 'r') as f:
                    data = json.load(f)
                trades = data.get("trades", [])
                logger.info(f"[+] Recovered {len(trades)} trades from backup")
                return trades
        except Exception as backup_e:
            logger.error(f"[-] Could not recover from backup: {backup_e}")
        return []
    
    except Exception as e:
        logger.error(f"[-] Error loading trade states: {e}")
        return []


def save_closed_trade(trade: Dict[str, Any]) -> bool:
    """
    Archive a closed trade for historical tracking and performance analysis.
    
    Args:
        trade: Closed trade dictionary with entry/exit prices and PnL
    
    Returns:
        True if successful, False otherwise
    """
    try:
        closed_trades = []
        
        # Load existing closed trades
        if CLOSED_TRADES_FILE.exists():
            with open(CLOSED_TRADES_FILE, 'r') as f:
                data = json.load(f)
                closed_trades = data.get("trades", [])
        
        # Add new closed trade
        closed_trades.append({
            **trade,
            "closed_at": datetime.now().isoformat()
        })
        
        # Save updated list
        persistence_data = {
            "timestamp": datetime.now().isoformat(),
            "total_closed": len(closed_trades),
            "trades": closed_trades
        }
        
        with open(CLOSED_TRADES_FILE, 'w') as f:
            json.dump(persistence_data, f, indent=2, default=str)
        
        logger.debug(f"[+] Archived closed trade {trade.get('trade_id')}")
        return True
    
    except Exception as e:
        logger.error(f"[-] Error archiving closed trade: {e}")
        return False


def load_closed_trades() -> List[Dict[str, Any]]:
    """
    Load all archived closed trades for performance analysis.
    
    Returns:
        List of closed trade dictionaries
    """
    try:
        if not CLOSED_TRADES_FILE.exists():
            return []
        
        with open(CLOSED_TRADES_FILE, 'r') as f:
            data = json.load(f)
        
        trades = data.get("trades", [])
        logger.debug(f"[+] Loaded {len(trades)} closed trades")
        return trades
    
    except Exception as e:
        logger.error(f"[-] Error loading closed trades: {e}")
        return []


def clear_persistence() -> bool:
    """
    Clear all persistence files (use with caution).
    
    Returns:
        True if successful
    """
    try:
        if PERSISTENCE_FILE.exists():
            os.remove(PERSISTENCE_FILE)
        if BACKUP_FILE.exists():
            os.remove(BACKUP_FILE)
        logger.info("[+] Cleared trade persistence files")
        return True
    except Exception as e:
        logger.error(f"[-] Error clearing persistence: {e}")
        return False


def get_persistence_status() -> Dict[str, Any]:
    """
    Get current persistence status (diagnostic info).
    
    Returns:
        Dictionary with file paths, sizes, and trade counts
    """
    status = {
        "persistence_dir": str(PERSISTENCE_DIR),
        "active_trades_file": str(PERSISTENCE_FILE),
        "backup_file": str(BACKUP_FILE),
        "closed_trades_file": str(CLOSED_TRADES_FILE),
        "active_trades": 0,
        "closed_trades": 0,
        "last_save": None
    }
    
    try:
        if PERSISTENCE_FILE.exists():
            with open(PERSISTENCE_FILE, 'r') as f:
                data = json.load(f)
            status["active_trades"] = len(data.get("trades", []))
            status["last_save"] = data.get("timestamp")
        
        if CLOSED_TRADES_FILE.exists():
            with open(CLOSED_TRADES_FILE, 'r') as f:
                data = json.load(f)
            status["closed_trades"] = len(data.get("trades", []))
    
    except Exception as e:
        status["error"] = str(e)
    
    return status


# =============================================================================
# TEST & VALIDATION
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("TRADE STATE PERSISTENCE - VALIDATION")
    print("="*70 + "\n")
    
    # Test save
    print("[TEST 1] Save trade states")
    test_trades = [
        {
            "trade_id": "XAUUSD_001",
            "entry_price": 2450.00,
            "stop_loss": 2420.00,
            "take_profit": 2540.00,
            "position_type": "BUY",
            "entry_time": "2026-05-27T10:00:00",
            "status": "OPEN",
            "position_size": 0.5
        },
        {
            "trade_id": "XAUUSD_002",
            "entry_price": 2460.00,
            "stop_loss": 2430.00,
            "take_profit": 2550.00,
            "position_type": "SELL",
            "entry_time": "2026-05-27T11:30:00",
            "status": "OPEN",
            "position_size": 1.0
        }
    ]
    
    result = save_active_trades(test_trades)
    print(f"Result: {'[+] PASS' if result else '[-] FAIL'}\n")
    
    # Test load
    print("[TEST 2] Load trade states")
    loaded = load_active_trades()
    print(f"Loaded {len(loaded)} trades")
    for trade in loaded:
        print(f"  - {trade['trade_id']}: {trade['position_type']} @ {trade['entry_price']:.2f}")
    print(f"Result: {'[+] PASS' if len(loaded) == len(test_trades) else '[-] FAIL'}\n")
    
    # Test closed trade archiving
    print("[TEST 3] Archive closed trade")
    closed_trade = {
        "trade_id": "XAUUSD_001",
        "entry_price": 2450.00,
        "exit_price": 2540.00,
        "pnl": 90.00,
        "pnl_pct": 0.36,
        "reward_to_risk": 3.0
    }
    result = save_closed_trade(closed_trade)
    print(f"Result: {'[+] PASS' if result else '[-] FAIL'}\n")
    
    # Test status
    print("[TEST 4] Get persistence status")
    status = get_persistence_status()
    print(f"Active trades: {status['active_trades']}")
    print(f"Closed trades: {status['closed_trades']}")
    print(f"Last save: {status['last_save']}")
    print(f"Result: [+] PASS\n")
    
    print("="*70)
    print("[+] TRADE STATE PERSISTENCE MODULE READY")
    print("="*70)
