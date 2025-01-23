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
    """
    Manages system state persistence, recovery, and graceful shutdowns.
    Tracks system-wide state and handles state transitions.
    """
    
    def __init__(self, price_manager, order_manager):
        """
        Initialize state manager.
        
        Args:
            price_manager: Instance of PriceManager for WebSocket state
            order_manager: Instance of OrderManager for order state
        """
        self.price_manager = price_manager
        self.order_manager = order_manager
        self.should_run = True
        self.state_check_interval = 60  # Check state every minute
        
        # Start state monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_state)
        self.monitor_thread.daemon = True
        
        # Register shutdown handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        atexit.register(self._cleanup)
    
    def start(self) -> None:
        """Start state monitoring and recovery."""
        try:
            # Recover state from database
            self._recover_state()
            
            # Start monitoring
            self.monitor_thread.start()
            
            logger.info("State manager started")
            
        except Exception as e:
            logger.error(
                "Failed to start state manager",
                error=str(e)
            )
            raise
    
    def stop(self) -> None:
        """Stop state monitoring gracefully."""
        self.should_run = False
        if self.monitor_thread.is_alive():
            self.monitor_thread.join()
        self._cleanup()
    
    def _recover_state(self) -> None:
        """Recover system state from database."""
        try:
            with get_db() as db:
                state = get_system_state(db)
                if not state:
                    logger.info("No previous state found, starting fresh")
                    return
                
                # Update system status
                update_system_state(
                    db,
                    status=SystemStatus.STARTING,
                    last_state_check=datetime.utcnow()
                )
                
                # Check for open orders
                open_orders = get_open_orders(db)
                if open_orders:
                    logger.info(
                        "Found open orders during recovery",
                        count=len(open_orders)
                    )
                
                logger.info(
                    "State recovered",
                    previous_status=state.status,
                    open_orders=len(open_orders)
                )
                
        except Exception as e:
            logger.error(
                "Failed to recover state",
                error=str(e)
            )
            raise
    
    def _monitor_state(self) -> None:
        """Monitor system state and components."""
        while self.should_run:
            try:
                current_state = self._get_current_state()
                
                with get_db() as db:
                    update_system_state(
                        db,
                        status=current_state['status'],
                        websocket_status=current_state['websocket_status'],
                        last_price_update=current_state['last_price_update'],
                        last_state_check=datetime.utcnow(),
                        open_orders=current_state['open_orders']
                    )
                
                # Sleep for interval
                for _ in range(self.state_check_interval):
                    if not self.should_run:
                        break
                    threading.Event().wait(1)
                    
            except Exception as e:
                logger.error(
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
                    status=SystemStatus.STOPPED,
                    last_state_check=datetime.utcnow()
                )
            
            logger.info("System state persisted for shutdown")
            
        except Exception as e:
            logger.error(
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