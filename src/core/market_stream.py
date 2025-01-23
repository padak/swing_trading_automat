"""
Market data WebSocket stream manager.
Handles real-time price updates from Binance.
"""
from typing import Optional, Dict, Any, List, Callable

from src.config.logging_config import get_logger
from src.config.settings import TRADING_SYMBOL
from .websocket_manager import WebSocketManager

logger = get_logger(__name__)

class MarketStreamManager(WebSocketManager):
    """Manages WebSocket connection for market data stream."""
    
    def __init__(self):
        """Initialize the market data stream manager."""
        # Binance WebSocket stream URL for spot market
        symbol = TRADING_SYMBOL.lower()
        url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"
        super().__init__(url=url, name="MarketStream")
        
        self.current_price: Optional[float] = None
        self.price_update_callbacks: List[Callable[[float], None]] = []
    
    async def subscribe(self) -> bool:
        """
        Subscribe to the trade stream.
        For Binance, the subscription is automatic based on the URL.
        
        Returns:
            bool: True as no explicit subscription is needed
        """
        # Register the trade event handler
        self.register_handler("trade", self._handle_trade)
        return True
    
    async def _handle_trade(self, message: Dict[str, Any]) -> None:
        """
        Handle incoming trade events.
        
        Args:
            message: Trade event data from Binance
        """
        try:
            price = float(message["p"])  # Price from trade event
            self.current_price = price
            
            # Notify all registered callbacks
            for callback in self.price_update_callbacks:
                try:
                    callback(price)
                except Exception as e:
                    logger.error(
                        "Price update callback error",
                        callback=callback.__name__,
                        error=str(e)
                    )
            
            logger.debug(
                "Price update",
                symbol=TRADING_SYMBOL,
                price=price
            )
            
        except (KeyError, ValueError) as e:
            logger.error(
                "Invalid trade message format",
                message=message,
                error=str(e)
            )
    
    def get_current_price(self) -> Optional[float]:
        """
        Get the most recent price.
        
        Returns:
            Optional[float]: Current price or None if not available
        """
        return self.current_price
    
    def register_price_callback(self, callback: Callable[[float], None]) -> None:
        """
        Register a callback for price updates.
        
        Args:
            callback: Function to call with new price
        """
        if callback not in self.price_update_callbacks:
            self.price_update_callbacks.append(callback)
            logger.info(
                "Registered price callback",
                callback=callback.__name__
            )
    
    def remove_price_callback(self, callback: Callable[[float], None]) -> None:
        """
        Remove a previously registered price callback.
        
        Args:
            callback: Function to remove
        """
        if callback in self.price_update_callbacks:
            self.price_update_callbacks.remove(callback)
            logger.info(
                "Removed price callback",
                callback=callback.__name__
            ) 