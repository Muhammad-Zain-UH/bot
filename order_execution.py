"""
Order Execution & Management Layer
Handles live order placement, execution, tracking, and error recovery.
Integrates with MT5 via mt5_handler.py for market execution.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import logging
from enum import Enum
import time
import random

# Setup logging
logger = logging.getLogger("OrderExecution")

# Order Status Enums
class OrderStatus(Enum):
    PENDING = "PENDING"           # Waiting to be sent to MT5
    SENT = "SENT"                 # Sent to MT5, waiting confirmation
    OPEN = "OPEN"                 # Order confirmed, position open
    PARTIAL_CLOSE = "PARTIAL"     # 50% closed at 1:1 RR
    TRAILING_SL = "TRAILING"      # SL trailing at 1:2 RR
    CLOSED = "CLOSED"             # Position fully closed
    REJECTED = "REJECTED"         # MT5 rejected order
    EXPIRED = "EXPIRED"           # Order expired due to timeout


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"


# =============================================================================
# ORDER EXECUTION ENGINE
# =============================================================================

class OrderExecutor:
    """
    Main order execution engine that interfaces with MT5.
    Handles order placement, tracking, retry logic, and partial exits.
    """
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 0.5):
        """
        Initialize order executor.
        
        Args:
            max_retries: Maximum attempts to place an order
            retry_delay: Delay between retry attempts (seconds)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.order_counter = 0
        
    def generate_order_id(self) -> str:
        """Generate unique order ID."""
        self.order_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"XAUUSD_{timestamp}_{self.order_counter}"
    
    def create_order(
        self,
        order_type: OrderType,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float = 1.0,
        signal_grade: str = "A",
        confidence_score: float = 75.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create new order object (not yet sent to MT5).
        
        Args:
            order_type: BUY or SELL
            entry_price: Entry price from entry engine
            stop_loss: SL price from entry engine
            take_profit: TP price from entry engine
            position_size: % of account to risk (0.5-1.0)
            signal_grade: A+ or A
            confidence_score: 0-100 score from confidence engine
            metadata: Additional data (setup_type, session, etc.)
        
        Returns:
            Order object ready for execution
        """
        order_id = self.generate_order_id()
        
        # Calculate risk/reward
        risk_distance = abs(entry_price - stop_loss)
        reward_distance = abs(take_profit - entry_price)
        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0
        
        order = {
            "order_id": order_id,
            "order_type": order_type.value,
            "status": OrderStatus.PENDING.value,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_size": position_size,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "rr_ratio": rr_ratio,
            "signal_grade": signal_grade,
            "confidence_score": confidence_score,
            "created_at": datetime.now().isoformat(),
            "sent_at": None,
            "executed_at": None,
            "execution_price": None,
            "mt5_order_id": None,
            "metadata": metadata or {},
            "exit_1_1": {"triggered": False, "price": entry_price + risk_distance},
            "exit_1_2": {"triggered": False, "price": entry_price + (risk_distance * 2)},
            "exit_1_3": {"triggered": False, "price": take_profit},
            "errors": []
        }
        
        self.orders[order_id] = order
        logger.info(f"✓ Order created: {order_id} | {order_type.value} @ {entry_price:.2f} | RR {rr_ratio:.1f}:1")
        return order
    
    def execute_order(self, order_id: str, mt5_handler=None, simulation: bool = True) -> Tuple[bool, str]:
        """
        Execute order on MT5 with retry logic.
        
        Args:
            order_id: ID of order to execute
            mt5_handler: MT5 handler instance (optional for demo mode)
            simulation: If True, simulate execution without MT5
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if order_id not in self.orders:
            return False, f"Order {order_id} not found"
        
        order = self.orders[order_id]
        
        # Retry logic
        for attempt in range(1, self.max_retries + 1):
            try:
                # Simulate execution
                if simulation:
                    logger.debug(f"[SIMULATION] Executing order {order_id} (attempt {attempt}/{self.max_retries})")
                    
                    # Simulate occasional failures for robustness testing
                    if random.random() < 0.05:  # 5% failure rate in sim
                        raise Exception("Simulated MT5 connection error")
                    
                    # Mark as executed
                    order["status"] = OrderStatus.OPEN.value
                    order["sent_at"] = datetime.now().isoformat()
                    order["executed_at"] = datetime.now().isoformat()
                    order["execution_price"] = order["entry_price"]
                    order["mt5_order_id"] = random.randint(1000000, 9999999)
                    
                    logger.info(f"✓ Order executed: {order_id} @ {order['execution_price']:.2f}")
                    return True, f"Order {order_id} executed successfully"
                
                # Real MT5 execution (when mt5_handler provided)
                elif mt5_handler:
                    logger.debug(f"Sending order to MT5: {order_id} (attempt {attempt}/{self.max_retries})")
                    
                    result = mt5_handler.send_order(
                        order_type=order["order_type"],
                        entry_price=order["entry_price"],
                        stop_loss=order["stop_loss"],
                        take_profit=order["take_profit"],
                        comment=order_id
                    )
                    
                    if result and result.get("status") == "OK":
                        order["status"] = OrderStatus.OPEN.value
                        order["sent_at"] = datetime.now().isoformat()
                        order["executed_at"] = datetime.now().isoformat()
                        order["execution_price"] = order["entry_price"]
                        order["mt5_order_id"] = result.get("order_id")
                        
                        logger.info(f"✓ Order executed on MT5: {order_id} (MT5 ID: {order['mt5_order_id']})")
                        return True, f"Order {order_id} executed on MT5"
                    else:
                        raise Exception(result.get("error", "MT5 order rejection") if result else "No response from MT5")
                
                else:
                    return False, "No MT5 handler provided and simulation disabled"
            
            except Exception as e:
                error_msg = f"Attempt {attempt}/{self.max_retries}: {str(e)}"
                order["errors"].append({
                    "timestamp": datetime.now().isoformat(),
                    "attempt": attempt,
                    "error": str(e)
                })
                
                logger.warning(f"✗ Order execution failed: {error_msg}")
                
                if attempt < self.max_retries:
                    logger.info(f"  → Retrying in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)
                else:
                    order["status"] = OrderStatus.REJECTED.value
                    logger.error(f"✗ Order {order_id} REJECTED after {self.max_retries} attempts")
                    return False, f"Order {order_id} rejected after {self.max_retries} attempts"
        
        return False, f"Order {order_id} execution exhausted retries"
    
    def update_current_price(self, order_id: str, current_price: float) -> Dict[str, Any]:
        """
        Update order with current price and check for partial exit triggers.
        
        Args:
            order_id: Order to update
            current_price: Current market price
        
        Returns:
            Dictionary with exit actions if triggered
        """
        if order_id not in self.orders:
            return {"status": "error", "message": "Order not found"}
        
        order = self.orders[order_id]
        
        if order["status"] not in [OrderStatus.OPEN.value, OrderStatus.PARTIAL_CLOSE.value, OrderStatus.TRAILING_SL.value]:
            return {"status": "inactive", "message": f"Order in {order['status']} status"}
        
        actions = []
        
        # Check 1:1 RR exit (50% close)
        if not order["exit_1_1"]["triggered"]:
            if (order["order_type"] == "BUY" and current_price >= order["exit_1_1"]["price"]) or \
               (order["order_type"] == "SELL" and current_price <= order["exit_1_1"]["price"]):
                order["exit_1_1"]["triggered"] = True
                order["status"] = OrderStatus.PARTIAL_CLOSE.value
                actions.append({
                    "action": "CLOSE_50PCT",
                    "level": "1:1 RR",
                    "price": current_price,
                    "profit_pips": abs(current_price - order["entry_price"])
                })
                logger.info(f"✓ 1:1 RR reached on {order_id}: Close 50% @ {current_price:.2f}")
        
        # Check 1:2 RR exit (trail SL)
        if not order["exit_1_2"]["triggered"] and order["exit_1_1"]["triggered"]:
            if (order["order_type"] == "BUY" and current_price >= order["exit_1_2"]["price"]) or \
               (order["order_type"] == "SELL" and current_price <= order["exit_1_2"]["price"]):
                order["exit_1_2"]["triggered"] = True
                order["status"] = OrderStatus.TRAILING_SL.value
                
                # Trail SL to breakeven for remaining 50%
                trail_sl = order["entry_price"]
                actions.append({
                    "action": "TRAIL_SL",
                    "level": "1:2 RR",
                    "price": current_price,
                    "new_sl": trail_sl,
                    "profit_locked": abs(order["entry_price"] - order["stop_loss"])
                })
                logger.info(f"✓ 1:2 RR reached on {order_id}: Trail SL to {trail_sl:.2f}")
        
        # Check 1:3 RR exit (take profit)
        if not order["exit_1_3"]["triggered"]:
            if (order["order_type"] == "BUY" and current_price >= order["exit_1_3"]["price"]) or \
               (order["order_type"] == "SELL" and current_price <= order["exit_1_3"]["price"]):
                order["exit_1_3"]["triggered"] = True
                order["status"] = OrderStatus.CLOSED.value
                
                final_profit = abs(current_price - order["entry_price"])
                actions.append({
                    "action": "CLOSE_ALL",
                    "level": "TP (1:3 RR)",
                    "price": current_price,
                    "total_profit_pips": final_profit,
                    "total_profit_rr": final_profit / order["risk_distance"] if order["risk_distance"] > 0 else 0
                })
                logger.info(f"✓ TP hit on {order_id}: Close all @ {current_price:.2f}")
        
        return {
            "status": "updated",
            "order_id": order_id,
            "current_price": current_price,
            "order_status": order["status"],
            "actions": actions
        }
    
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details."""
        return self.orders.get(order_id)
    
    def get_all_open_orders(self) -> List[Dict[str, Any]]:
        """Get all currently open orders."""
        return [
            order for order in self.orders.values()
            if order["status"] in [
                OrderStatus.PENDING.value,
                OrderStatus.SENT.value,
                OrderStatus.OPEN.value,
                OrderStatus.PARTIAL_CLOSE.value,
                OrderStatus.TRAILING_SL.value
            ]
        ]
    
    def get_all_closed_orders(self) -> List[Dict[str, Any]]:
        """Get all closed orders."""
        return [
            order for order in self.orders.values()
            if order["status"] in [OrderStatus.CLOSED.value, OrderStatus.REJECTED.value]
        ]


# =============================================================================
# TEST & VALIDATION
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("ORDER EXECUTION & MANAGEMENT - VALIDATION")
    print("="*70 + "\n")
    
    # Initialize executor
    executor = OrderExecutor()
    
    # Test 1: Create order
    print("[TEST 1] Create Order")
    order = executor.create_order(
        order_type=OrderType.BUY,
        entry_price=2450.00,
        stop_loss=2420.00,
        take_profit=2540.00,
        position_size=0.5,
        signal_grade="A+",
        confidence_score=85.5,
        metadata={"setup_type": "OB", "session": "LONDON"}
    )
    print(f"✓ Order created: {order['order_id']}")
    print(f"  Entry: {order['entry_price']:.2f}")
    print(f"  SL: {order['stop_loss']:.2f}")
    print(f"  TP: {order['take_profit']:.2f}")
    print(f"  RR: {order['rr_ratio']:.1f}:1\n")
    
    # Test 2: Execute order
    print("[TEST 2] Execute Order (Simulation)")
    success, message = executor.execute_order(order["order_id"], simulation=True)
    print(f"Result: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"Message: {message}\n")
    
    # Test 3: Update current price and check exits
    print("[TEST 3] Track Price Movements")
    prices = [2460.00, 2480.00, 2510.00, 2540.00]
    for price in prices:
        result = executor.update_current_price(order["order_id"], price)
        print(f"Price: {price:.2f}")
        if result.get("actions"):
            for action in result["actions"]:
                print(f"  → {action['action']}: {action['level']}")
        else:
            print(f"  → No action triggered")
    print()
    
    # Test 4: Multiple orders
    print("[TEST 4] Multiple Orders Management")
    for i in range(3):
        o = executor.create_order(
            order_type=OrderType.SELL if i % 2 else OrderType.BUY,
            entry_price=2450.00 - (i * 10),
            stop_loss=2420.00 - (i * 10),
            take_profit=2540.00 - (i * 10),
            signal_grade="A",
            confidence_score=75.0
        )
        executor.execute_order(o["order_id"], simulation=True)
    
    open_orders = executor.get_all_open_orders()
    print(f"✓ Total open orders: {len(open_orders)}")
    for order in open_orders[:3]:
        print(f"  - {order['order_id']}: {order['order_type']} @ {order['entry_price']:.2f}")
    print()
    
    print("="*70)
    print("✅ ORDER EXECUTION LAYER READY")
    print("="*70)
