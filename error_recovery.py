"""
Error Recovery & Monitoring Layer
Provides resilience, monitoring, and graceful failure handling for production trading.
Manages connection recovery, position preservation, and system health.
"""

import logging
import time
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from pathlib import Path
import threading

# Setup logging
logger = logging.getLogger("ErrorRecovery")


class HealthStatus(Enum):
    """System health states."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    RECOVERING = "RECOVERING"
    OFFLINE = "OFFLINE"


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# =============================================================================
# SYSTEM MONITOR
# =============================================================================

class SystemMonitor:
    """
    Continuous monitoring of bot health, connections, and operations.
    Provides early warning of issues and triggers recovery actions.
    """
    
    def __init__(self, check_interval: float = 5.0):
        """
        Initialize system monitor.
        
        Args:
            check_interval: Seconds between health checks
        """
        self.check_interval = check_interval
        self.status = HealthStatus.HEALTHY
        self.last_check = datetime.now()
        self.errors: List[Dict[str, Any]] = []
        self.recoveries: List[Dict[str, Any]] = []
        self.metrics = {
            "orders_created": 0,
            "orders_executed": 0,
            "orders_failed": 0,
            "positions_open": 0,
            "positions_closed": 0,
            "connection_losses": 0,
            "recovery_attempts": 0,
            "uptime_seconds": 0
        }
        self.start_time = datetime.now()
        self.monitoring_active = False
    
    def log_error(
        self,
        error_type: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        recoverable: bool = True,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log an error for tracking and recovery.
        
        Args:
            error_type: Category of error (e.g., "MT5_CONNECTION", "ORDER_FAILED")
            message: Error description
            severity: Severity level
            recoverable: Whether error can trigger automatic recovery
            context: Additional context data
        
        Returns:
            Error ID for reference
        """
        error_id = f"ERR_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        error_entry = {
            "error_id": error_id,
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "message": message,
            "severity": severity.value,
            "recoverable": recoverable,
            "context": context or {}
        }
        
        self.errors.append(error_entry)
        
        # Update status based on severity
        if severity == ErrorSeverity.CRITICAL:
            self.status = HealthStatus.CRITICAL
            logger.critical(f"[CRITICAL] CRITICAL ERROR [{error_id}]: {message}")
        elif severity == ErrorSeverity.ERROR:
            if self.status != HealthStatus.CRITICAL:
                self.status = HealthStatus.DEGRADED
            logger.error(f"[ERROR] ERROR [{error_id}]: {message}")
        else:
            logger.warning(f"[WARNING] WARNING [{error_id}]: {message}")
        
        # Track error counts
        self.metrics["orders_failed"] += 1
        
        return error_id
    
    def log_recovery(
        self,
        error_id: str,
        recovery_action: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log recovery attempt for an error.
        
        Args:
            error_id: ID of original error
            recovery_action: What action was taken
            success: Whether recovery succeeded
            details: Additional recovery details
        """
        recovery_entry = {
            "recovery_id": f"REC_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "timestamp": datetime.now().isoformat(),
            "error_id": error_id,
            "recovery_action": recovery_action,
            "success": success,
            "details": details or {}
        }
        
        self.recoveries.append(recovery_entry)
        self.metrics["recovery_attempts"] += 1
        
        if success:
            logger.info(f"[RECOVERY] Recovery successful: {recovery_action} [{error_id}]")
            if self.status != HealthStatus.CRITICAL:
                self.status = HealthStatus.HEALTHY
        else:
            logger.error(f"[RECOVERY] Recovery failed: {recovery_action} [{error_id}]")
            self.status = HealthStatus.CRITICAL
    
    def check_health(self) -> HealthStatus:
        """
        Perform system health check.
        
        Returns:
            Current health status
        """
        self.last_check = datetime.now()
        
        # Calculate uptime
        uptime = (datetime.now() - self.start_time).total_seconds()
        self.metrics["uptime_seconds"] = int(uptime)
        
        # Health assessment
        if len(self.errors) > 10:
            self.status = HealthStatus.CRITICAL
        elif len(self.errors) > 5:
            self.status = HealthStatus.DEGRADED
        elif self.metrics["connection_losses"] > 3:
            self.status = HealthStatus.CRITICAL
        else:
            if self.status == HealthStatus.RECOVERING:
                self.status = HealthStatus.HEALTHY
        
        return self.status
    
    def get_status_report(self) -> Dict[str, Any]:
        """
        Get comprehensive status report.
        
        Returns:
            Dictionary with all system metrics
        """
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        uptime_hours = uptime_seconds / 3600
        
        return {
            "timestamp": datetime.now().isoformat(),
            "status": self.status.value,
            "uptime": {
                "seconds": int(uptime_seconds),
                "hours": round(uptime_hours, 2),
                "readable": f"{int(uptime_hours)}h {int((uptime_seconds % 3600) / 60)}m"
            },
            "metrics": self.metrics,
            "recent_errors": self.errors[-5:] if self.errors else [],
            "recent_recoveries": self.recoveries[-5:] if self.recoveries else [],
            "error_summary": {
                "total_errors": len(self.errors),
                "total_recoveries": len(self.recoveries),
                "recovery_success_rate": (
                    sum(1 for r in self.recoveries if r["success"]) / len(self.recoveries) * 100
                    if self.recoveries else 0
                )
            }
        }


# =============================================================================
# CONNECTION MANAGER
# =============================================================================

class ConnectionManager:
    """
    Manages MT5 connection with automatic reconnection logic.
    """
    
    def __init__(self, max_reconnect_attempts: int = 5, reconnect_delay: float = 2.0):
        """
        Initialize connection manager.
        
        Args:
            max_reconnect_attempts: Maximum reconnection attempts
            reconnect_delay: Delay between reconnection attempts (seconds)
        """
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.is_connected = False
        self.last_connection_loss = None
        self.connection_failures = 0
    
    def test_connection(self, mt5_handler=None) -> bool:
        """
        Test MT5 connection.
        
        Args:
            mt5_handler: MT5 handler instance
        
        Returns:
            True if connected, False otherwise
        """
        if not mt5_handler:
            logger.warning("No MT5 handler provided, assuming simulation mode")
            return True
        
        try:
            # Check if MT5 is still initialized
            account_info = mt5_handler.get_account_info()
            self.is_connected = account_info is not None
            
            if self.is_connected:
                logger.debug("[CONNECTION] MT5 connection healthy")
                self.connection_failures = 0
            else:
                self.connection_failures += 1
                logger.warning(f"[CONNECTION] MT5 connection test failed (attempt {self.connection_failures})")
            
            return self.is_connected
        
        except Exception as e:
            self.connection_failures += 1
            logger.error(f"[CONNECTION] Connection test error: {e}")
            return False
    
    def reconnect(self, mt5_handler=None, monitor: Optional[SystemMonitor] = None) -> bool:
        """
        Attempt to reconnect to MT5.
        
        Args:
            mt5_handler: MT5 handler instance
            monitor: System monitor for error logging
        
        Returns:
            True if reconnection successful
        """
        if monitor:
            monitor.status = HealthStatus.RECOVERING
            monitor.metrics["connection_losses"] += 1
        
        for attempt in range(1, self.max_reconnect_attempts + 1):
            logger.info(f"Reconnection attempt {attempt}/{self.max_reconnect_attempts}")
            
            try:
                if mt5_handler and hasattr(mt5_handler, 'reconnect'):
                    mt5_handler.reconnect()
                
                time.sleep(self.reconnect_delay)
                
                if self.test_connection(mt5_handler):
                    logger.info(f"[CONNECTION] Reconnected successfully on attempt {attempt}")
                    self.last_connection_loss = datetime.now()
                    
                    if monitor:
                        monitor.log_recovery(
                            error_id="CON_LOSS",
                            recovery_action="RECONNECT",
                            success=True,
                            details={"attempt": attempt}
                        )
                    
                    return True
            
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt} failed: {e}")
            
            if attempt < self.max_reconnect_attempts:
                time.sleep(self.reconnect_delay * attempt)
        
        logger.critical("[CONNECTION] Failed to reconnect after all attempts")
        if monitor:
            monitor.log_error(
                error_type="CONNECTION_FAILED",
                message=f"Failed to reconnect after {self.max_reconnect_attempts} attempts",
                severity=ErrorSeverity.CRITICAL,
                recoverable=False
            )
        
        return False


# =============================================================================
# GRACEFUL SHUTDOWN MANAGER
# =============================================================================

class GracefulShutdownManager:
    """
    Manages graceful shutdown with position preservation and cleanup.
    """
    
    def __init__(self, persistence_layer=None):
        """
        Initialize shutdown manager.
        
        Args:
            persistence_layer: Trade persistence module
        """
        self.persistence_layer = persistence_layer
        self.shutdown_requested = False
        self.cleanup_tasks: List[Callable] = []
    
    def register_cleanup_task(self, task: Callable) -> None:
        """
        Register a cleanup task to run on shutdown.
        
        Args:
            task: Callable to execute during cleanup
        """
        self.cleanup_tasks.append(task)
        logger.debug(f"[SHUTDOWN] Registered cleanup task: {task.__name__}")
    
    def shutdown(self, open_trades: List[Dict[str, Any]], monitor: Optional[SystemMonitor] = None) -> bool:
        """
        Execute graceful shutdown.
        
        Args:
            open_trades: List of open trades to preserve
            monitor: System monitor
        
        Returns:
            True if shutdown successful
        """
        logger.info("[SHUTDOWN] Initiating graceful shutdown...")
        self.shutdown_requested = True
        
        try:
            # 1. Preserve open trades
            if self.persistence_layer and open_trades:
                logger.info(f"  [SHUTDOWN] Saving {len(open_trades)} open trades...")
                self.persistence_layer.save_active_trades(open_trades)
            
            # 2. Execute cleanup tasks
            for task in self.cleanup_tasks:
                try:
                    logger.info(f"  [SHUTDOWN] Running cleanup: {task.__name__}...")
                    task()
                except Exception as e:
                    logger.error(f"[SHUTDOWN] Cleanup task failed: {e}")
            
            # 3. Log final status
            if monitor:
                report = monitor.get_status_report()
                logger.info("[SHUTDOWN] Final status report:")
                logger.info(f"  - Uptime: {report['uptime']['readable']}")
                logger.info(f"  - Total errors: {report['error_summary']['total_errors']}")
                logger.info(f"  - Total recoveries: {report['error_summary']['total_recoveries']}")
            
            logger.info("[SHUTDOWN] Graceful shutdown completed successfully")
            return True
        
        except Exception as e:
            logger.critical(f"[SHUTDOWN] Graceful shutdown failed: {e}")
            return False


# =============================================================================
# ALERT MANAGER
# =============================================================================

class AlertManager:
    """
    Manages system alerts and notifications.
    """
    
    def __init__(self):
        self.alerts: List[Dict[str, Any]] = []
    
    def send_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.WARNING
    ) -> str:
        """
        Send system alert.
        
        Args:
            alert_type: Type of alert (e.g., "CONNECTION_LOSS", "HIGH_DRAWDOWN")
            title: Alert title
            message: Alert message
            severity: Severity level
        
        Returns:
            Alert ID
        """
        alert_id = f"ALERT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        alert = {
            "alert_id": alert_id,
            "timestamp": datetime.now().isoformat(),
            "alert_type": alert_type,
            "title": title,
            "message": message,
            "severity": severity.value
        }
        
        self.alerts.append(alert)
        
        logger.info(f"🔔 ALERT [{alert_type}]: {title}")
        logger.info(f"   {message}")
        
        return alert_id


# =============================================================================
# TEST & VALIDATION
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("ERROR RECOVERY & MONITORING - VALIDATION")
    print("="*70 + "\n")
    
    # Initialize components
    monitor = SystemMonitor()
    connection_mgr = ConnectionManager()
    shutdown_mgr = GracefulShutdownManager()
    alert_mgr = AlertManager()
    
    # Test 1: System monitoring
    print("[TEST 1] System Monitoring")
    monitor.check_health()
    monitor.metrics["orders_created"] = 5
    monitor.metrics["orders_executed"] = 5
    monitor.metrics["positions_open"] = 2
    
    status = monitor.check_health()
    print(f"✓ Current status: {status.value}")
    print(f"  Metrics: {monitor.metrics}\n")
    
    # Test 2: Error logging
    print("[TEST 2] Error Logging & Recovery")
    error_id = monitor.log_error(
        error_type="ORDER_FAILED",
        message="MT5 rejected order due to invalid SL",
        severity=ErrorSeverity.ERROR,
        context={"order_id": "TEST_001"}
    )
    print(f"✓ Error logged: {error_id}\n")
    
    monitor.log_recovery(
        error_id=error_id,
        recovery_action="RETRY_ORDER",
        success=True,
        details={"retry_attempt": 2}
    )
    print(f"✓ Recovery logged\n")
    
    # Test 3: Connection management
    print("[TEST 3] Connection Management")
    is_connected = connection_mgr.test_connection()
    print(f"✓ Connection test: {is_connected}\n")
    
    # Test 4: Alerts
    print("[TEST 4] Alert System")
    alert_id = alert_mgr.send_alert(
        alert_type="HIGH_DRAWDOWN",
        title="Daily Loss Limit Warning",
        message="Current daily loss: 4.5% (limit: 5%)",
        severity=ErrorSeverity.WARNING
    )
    print(f"✓ Alert sent: {alert_id}\n")
    
    # Test 5: Status report
    print("[TEST 5] Status Report")
    report = monitor.get_status_report()
    print(f"✓ Status: {report['status']}")
    print(f"  Uptime: {report['uptime']['readable']}")
    print(f"  Total errors: {report['error_summary']['total_errors']}")
    print(f"  Total recoveries: {report['error_summary']['total_recoveries']}\n")
    
    # Test 6: Graceful shutdown
    print("[TEST 6] Graceful Shutdown")
    
    # Register cleanup task
    def cleanup_example():
        print("    Closing database connections...")
    
    shutdown_mgr.register_cleanup_task(cleanup_example)
    
    open_trades = [
        {"trade_id": "T001", "status": "OPEN"},
        {"trade_id": "T002", "status": "OPEN"}
    ]
    
    result = shutdown_mgr.shutdown(open_trades, monitor)
    print(f"✓ Shutdown result: {result}\n")
    
    print("="*70)
    print("✅ ERROR RECOVERY & MONITORING LAYER READY")
    print("="*70)
