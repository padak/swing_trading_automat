"""
State manager for handling system state persistence and recovery.
Manages graceful shutdowns and tracks system-wide state.
"""
from typing import Dict, Any, Optional
from datetime import datetime
import signal
import threading
import atexit

from src.config.logging_config import get_logger
from src.db.operations import (
    get_db,
    update_system_state,
    get_system_state,
    get_open_orders
)
from src.db.models import SystemState, SystemStatus

logger = get_logger(__name__)

class StateManager:
    """Manages system state and handles state reconciliation."""
    
    def __init__(self, price_manager, order_manager):
        """
        Initialize state manager.
        
        Args:
            price_manager: Instance of PriceManager for WebSocket state
            order_manager: Instance of OrderManager for order state
        """
        self.price_manager = price_manager
        self.order_manager = order_manager
        self.logger = get_logger(__name__)
        self.should_run = True
        self.state_check_interval = 60  # Check state every minute
        
        # Start state monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_state)
        self.monitor_thread.daemon = True
        
        # Register shutdown handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        atexit.register(self._cleanup)
    
    def start(self):
        """Start the state manager and perform initial state reconciliation."""
        try:
            self._reconcile_state()
            self.logger.info("State Manager started - initial state reconciled")
        except Exception as e:
            self.logger.error(f"Failed to start state manager: {str(e)}")
            raise
            
    def stop(self) -> None:
        """Stop the state manager and cleanup resources."""
        self.logger.debug("StateManager stop initiated")
        self.should_run = False
        
        try:
            # Wait for any pending state updates to complete
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.logger.debug("Waiting for state check thread to stop...")
                self.monitor_thread.join(timeout=5)
                if self.monitor_thread.is_alive():
                    self.logger.warning("State check thread did not stop within timeout")
            
        except Exception as e:
            self.logger.error(f"Error during StateManager shutdown: {str(e)}")
        finally:
            self.logger.debug("StateManager stop completed")
            self._cleanup()
    
    def update_state(self, websocket_status: str = None, last_error: str = None) -> None:
        """
        Update system state in database.
        
        Args:
            websocket_status: Current WebSocket connection status
            last_error: Last error message if any
        """
        try:
            with get_db() as db:
                update_system_state(
                    db,
                    websocket_status=websocket_status,
                    last_error=last_error,
                    reconnection_attempts=0 if websocket_status == "CONNECTED" else None
                )
        except Exception as e:
            self.logger.error(f"Failed to update system state: {str(e)}")
            
    def _reconcile_state(self) -> None:
        """
        Reconcile local state with Binance's state.
        Loads system state from DB and cross-checks with Binance.
        """
        try:
            with get_db() as db:
                # Load current state
                state = get_system_state(db)
                self.logger.info("Loaded system state", 
                               websocket_status=state.websocket_status,
                               last_processed_time=state.last_processed_time)
                
                # TODO: Implement Binance state reconciliation
                # 1. Fetch open orders from Binance
                # 2. Compare with local DB state
                # 3. Update any mismatches
                
                # For now, just mark as initializing
                update_system_state(
                    db,
                    websocket_status="INITIALIZING",
                    last_error=None,
                    reconnection_attempts=0
                )
                
        except Exception as e:
            self.logger.error(f"Failed to reconcile state: {str(e)}")
            raise
    
    def _monitor_state(self) -> None:
        """Monitor system state and components."""
        while self.should_run:
            try:
                current_state = self._get_current_state()
                
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status=current_state['websocket_status'],
                        last_error=None,
                        reconnection_attempts=0 if current_state['websocket_status'] == "CONNECTED" else None
                    )
                
                # Sleep for interval
                for _ in range(self.state_check_interval):
                    if not self.should_run:
                        break
                    threading.Event().wait(1)
                    
            except Exception as e:
                self.logger.error(
                    "State monitoring error",
                    error=str(e)
                )
                threading.Event().wait(self.state_check_interval)
    
    def _get_current_state(self) -> Dict[str, Any]:
        """
        Get current system state.
        
        Returns:
            Dict[str, Any]: Current state information
        """
        # Check WebSocket status
        websocket_status = "CONNECTED" if self.price_manager.connected else "DISCONNECTED"
        
        # Get open orders
        with get_db() as db:
            open_orders = get_open_orders(db)
        
        # Determine system status
        if not self.price_manager.connected:
            status = SystemStatus.DEGRADED
        elif len(open_orders) > 0:
            status = SystemStatus.TRADING
        else:
            status = SystemStatus.READY
        
        return {
            'status': status,
            'websocket_status': websocket_status,
            'last_price_update': self.price_manager.last_message_time,
            'open_orders': len(open_orders)
        }
    
    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """
        Handle shutdown signal.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        logger.info(
            "Shutdown signal received",
            signal=signum
        )
        self.stop()
    
    def _cleanup(self) -> None:
        """Clean up resources and persist final state."""
        try:
            with get_db() as db:
                update_system_state(
                    db,
                    websocket_status="STOPPED",
                    last_error=None,
                    reconnection_attempts=0
                )
            
            self.logger.info("System state persisted for shutdown")
            
        except Exception as e:
            self.logger.error(
                "Failed to persist shutdown state",
                error=str(e)
            )
    
    def get_system_summary(self) -> Dict[str, Any]:
        """
        Get summary of current system state.
        
        Returns:
            Dict[str, Any]: System state summary
        """
        current_state = self._get_current_state()
        
        # Get position durations
        positions = self.order_manager.get_open_positions()
        position_durations = {
            p['order_id']: p['duration_seconds']
            for p in positions
        }
        
        return {
            'status': current_state['status'].value,
            'websocket_status': current_state['websocket_status'],
            'last_price_update': current_state['last_price_update'],
            'open_orders': current_state['open_orders'],
            'positions': positions,
            'position_durations': position_durations
        }
    
    def is_healthy(self) -> bool:
        """
        Check if system is in a healthy state.
        
        Returns:
            bool: True if system is healthy
        """
        current_state = self._get_current_state()
        
        # System is healthy if:
        # 1. WebSocket is connected
        # 2. Recent price updates (within last minute)
        # 3. No errors in state monitoring
        return (
            current_state['websocket_status'] == "CONNECTED" and
            current_state['last_price_update'] and
            (datetime.utcnow() - current_state['last_price_update']).total_seconds() < 60
        ) 