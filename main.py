#!/usr/bin/env python3

import os
import signal
import sys
import logging
from typing import Optional
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
        """Initialize all components in the correct order."""
        try:
            # Load environment variables
            load_dotenv()
            
            # Setup logging
            setup_logging()
            self.logger.info("Starting Binance Swing Trading Automation")
            
            # Initialize database
            initialize_database()
            self.logger.info("Database initialized")
            
            # Initialize components
            self.price_manager = PriceManager()
            self.order_manager = OrderManager()
            self.state_manager = StateManager()
            
            # Register callbacks
            self.price_manager.register_price_callback(self.order_manager.handle_price_update)
            self.price_manager.register_order_callback(self.order_manager.handle_order_update)
            
            # Start components
            self.price_manager.start()
            self.order_manager.start()
            self.state_manager.start()
            
            self.logger.info("All components initialized and started")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize application: {str(e)}")
            self.shutdown()
            sys.exit(1)

    def shutdown(self):
        """Gracefully shut down all components."""
        self.logger.info("Initiating graceful shutdown")
        self.running = False
        
        try:
            # Stop components in reverse order
            if self.state_manager:
                self.state_manager.stop()
            if self.order_manager:
                self.order_manager.stop()
            if self.price_manager:
                self.price_manager.stop()
                
            self.logger.info("All components stopped successfully")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")
        
        sys.exit(0)

    def handle_signal(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        self.logger.info(f"Received signal {signum}")
        self.shutdown()

    def run(self):
        """Main application loop."""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        
        try:
            self.initialize()
            
            # Keep the main thread alive
            while self.running:
                signal.pause()
                
        except Exception as e:
            self.logger.error(f"Error in main loop: {str(e)}")
            self.shutdown()

def main():
    app = Application()
    app.run()

if __name__ == "__main__":
    main() 