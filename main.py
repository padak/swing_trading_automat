#!/usr/bin/env python3

import os
import signal
import sys
import logging
import time
from typing import Optional, Any
from dotenv import load_dotenv

from src.config.logging_config import setup_logging
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
            self.logger.error(f"Failed to initialize application: {str(e)}")
            self.shutdown()
            sys.exit(1)

    def shutdown(self) -> None:
        """Perform graceful shutdown of all components."""
        # Prevent multiple shutdown attempts
        if not self.running:
            self.logger.warning("Shutdown already in progress")
            return

        self.logger.info("Initiating graceful shutdown")
        self.running = False

        try:
            # Stop components in reverse order with timeouts
            if self.order_manager:
                self.logger.debug("Stopping Order Manager...")
                self.order_manager.stop()
                self.logger.debug("Order Manager stop() returned")

            if self.price_manager:
                self.logger.debug("Stopping Price Manager...")
                self.price_manager.stop()
                self.logger.debug("Price Manager stop() returned")

            if self.state_manager:
                self.logger.debug("Stopping State Manager...")
                # Update final state before stopping
                self.state_manager.update_state(
                    websocket_status="STOPPED",
                    last_error=None,
                    reconnection_attempts=0
                )
                self.state_manager.stop()
                self.logger.debug("State Manager stop() returned")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")
        
        finally:
            self.logger.info("All components stopped, calling os._exit(0)")
            os._exit(0)  # Force exit after cleanup

    def handle_signal(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal."""
        if not self.running:
            self.logger.warning("Received additional shutdown signal, forcing exit")
            os._exit(1)
        
        self.logger.info(f"Received signal {signum}, initiating shutdown")
        self.shutdown()

    def run(self) -> None:
        """Run the application."""
        try:
            # Register signal handler only once
            signal.signal(signal.SIGINT, self.handle_signal)
            
            self.initialize()
            self.logger.info("Application initialized, entering main loop")
            
            # Main loop with explicit exit condition check
            while self.running:
                time.sleep(1)
                
            self.logger.debug("Main loop ended, calling final shutdown")
            
        except Exception as e:
            self.logger.error(f"Error in main loop: {str(e)}")
        finally:
            self.shutdown()

def main():
    app = Application()
    app.run()

if __name__ == "__main__":
    main() 