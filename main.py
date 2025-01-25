#!/usr/bin/env python3

import os
import signal
import sys
import logging
import time
import threading
from typing import Optional, Any
from dotenv import load_dotenv

from src.config.logging_config import setup_logging
from src.config.settings import (
    SHUTDOWN_TIMEOUT_ORDER,
    SHUTDOWN_TIMEOUT_PRICE,
    SHUTDOWN_TIMEOUT_STATE,
    MONITOR_LOOP_INTERVAL
)
from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager
from src.db.operations import initialize_database

class Application:
    def __init__(self):
        self.price_manager: Optional[PriceManager] = None
        self.order_manager: Optional[OrderManager] = None
        self.state_manager: Optional[StateManager] = None
        self.logger = logging.getLogger(__name__)
        self.running = True
        self.shutting_down = False  # Track shutdown state

    def initialize(self):
        """Initialize all components according to design specification."""
        try:
            # Load environment variables
            load_dotenv()
            
            # Setup logging
            setup_logging()
            self.logger.info("Starting Binance Swing Trading Automation")
            
            # Initialize database
            initialize_database()
            self.logger.info("Database initialized")
            
            # Initialize components in correct order according to design:
            # 1. Price Manager (WebSocket connections)
            self.price_manager = PriceManager()
            self.logger.info("Price Manager initialized")
            
            # 2. Order Manager (depends on Price Manager)
            self.order_manager = OrderManager(
                price_manager=self.price_manager,
                state_manager=None  # Will be set after StateManager initialization
            )
            self.logger.info("Order Manager initialized")
            
            # 3. State Manager (requires both Price and Order managers)
            self.state_manager = StateManager(
                price_manager=self.price_manager,
                order_manager=self.order_manager
            )
            # Update Order Manager with State Manager reference
            self.order_manager.state_manager = self.state_manager
            self.logger.info("State Manager initialized")
            
            # Register callbacks
            self.price_manager.register_price_callback(self.order_manager.handle_price_update)
            self.price_manager.register_order_callback(self.order_manager.handle_order_update)
            self.logger.info("Callbacks registered")
            
            # Start components in order according to design:
            # 1. State Manager (load and reconcile state)
            self.state_manager.start()
            self.logger.info("State Manager started - state loaded and reconciled")
            
            # 2. Price Manager (establish WebSocket connections)
            self.price_manager.start()
            self.logger.info("Price Manager started - WebSocket connections established")
            
            # 3. Order Manager (begin monitoring)
            self.order_manager.start()
            self.logger.info("Order Manager started - monitoring orders")
            
            self.logger.info("All components initialized and started")
            
        except Exception as e:
            self.logger.error("Failed to initialize application", exc_info=True)
            self.shutdown()
            sys.exit(1)

    def handle_signal(self, signum: int, frame: Any) -> None:
        """Simple, direct signal handler that either initiates shutdown or forces exit."""
        self.logger.info("Caught signal %s, initiating shutdown...", signum)
        
        if self.shutting_down:
            self.logger.warning("Forced exit requested, calling os._exit(1)", exc_info=True)
            # Ensure logs are flushed before forced exit
            for handler in logging.getLogger().handlers:
                handler.flush()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
            
        self.shutdown()

    def shutdown(self) -> None:
        """Ordered shutdown of components with proper state tracking."""
        try:
            self.shutting_down = True
            self.running = False
            
            # 1. Stop OrderManager (depends on others)
            if self.order_manager:
                self.logger.info("Stopping Order Manager...")
                self.order_manager.stop()
                if not self.order_manager.join(timeout=SHUTDOWN_TIMEOUT_ORDER):
                    self.logger.error("OrderManager failed to stop in time")
            
            # 2. Stop PriceManager (provides data)
            if self.price_manager:
                self.logger.info("Stopping Price Manager...")
                self.price_manager.stop()
                if not self.price_manager.join(timeout=SHUTDOWN_TIMEOUT_PRICE):
                    self.logger.error("PriceManager failed to stop in time")
            
            # 3. Stop StateManager (handles final state)
            if self.state_manager:
                self.logger.info("Stopping State Manager...")
                # Update final state before stopping
                self.state_manager.update_state(
                    websocket_status="STOPPED",
                    last_error=None,
                    reconnection_attempts=0
                )
                self.state_manager.stop()
                if not self.state_manager.join(timeout=SHUTDOWN_TIMEOUT_STATE):
                    self.logger.error("StateManager failed to stop in time")
            
            # Final state verification
            self.verify_final_state()
            
        except Exception as e:
            self.logger.error("Error during shutdown", exc_info=True)
            raise
        finally:
            # Ensure all logs are flushed
            for handler in logging.getLogger().handlers:
                handler.flush()
            sys.stdout.flush()
            sys.stderr.flush()
            sys.exit(0)  # Clean exit after resources are freed

    def verify_final_state(self):
        """Verify database state and resource cleanup."""
        try:
            if self.state_manager:
                # Verify DB state
                assert self.state_manager.db.verify_integrity()
                
                # Check for active threads
                active_threads = threading.enumerate()
                assert len(active_threads) == 1  # Only main thread
                
                # Verify WebSocket closure
                if self.price_manager:
                    assert all(ws.closed for ws in self.price_manager.websockets)
                
                # Verify DB connections are closed
                assert self.state_manager.db.pool.size() == 0
                
        except AssertionError as e:
            self.logger.error("State verification failed", exc_info=True)
            raise

    def run(self) -> None:
        """Run the application."""
        try:
            # Register signal handler only once
            signal.signal(signal.SIGINT, self.handle_signal)
            signal.signal(signal.SIGTERM, self.handle_signal)
            
            self.initialize()
            self.logger.info("Application initialized, entering main loop")
            
            # Main loop with shorter sleep interval
            while self.running:
                time.sleep(MONITOR_LOOP_INTERVAL)
                
            self.logger.debug("Main loop ended, shutdown in progress")
            
        except Exception as e:
            self.logger.error("Error in main loop", exc_info=True)
        finally:
            if not self.shutting_down:  # Only call shutdown if not already shutting down
                self.shutdown()

def main():
    app = Application()
    app.run()

if __name__ == "__main__":
    main() 