"""
Price manager for handling real-time price updates and WebSocket connections.
Includes both WebSocket streaming and REST API fallback.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

import requests
import websockets
from websockets.exceptions import WebSocketException

from src.config.logging_config import get_logger
from src.config.settings import (
    TRADING_SYMBOL,
    REST_API_REFRESH_RATE,
    WEBSOCKET_RECONNECT_TIMEOUT,
    WEBSOCKET_INITIAL_RETRY_DELAY
)
from src.db.operations import get_db, update_system_state

logger = get_logger(__name__)

class PriceManager:
    """
    Manages real-time price updates using WebSocket connection.
    Includes REST API fallback for reliability.
    """
    
    def __init__(self):
        """Initialize the price manager."""
        symbol = TRADING_SYMBOL.lower()
        self.ws_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"
        self.rest_api_url = f"https://api.binance.com/api/v3/ticker/price?symbol={TRADING_SYMBOL}"
        
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.should_run = True
        self.last_message_time: Optional[datetime] = None
        self.reconnection_attempts = 0
        
        self.current_price: Optional[float] = None
        self.price_update_callbacks: List[Callable[[float], None]] = []
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connection with exponential backoff.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        retry_delay = WEBSOCKET_INITIAL_RETRY_DELAY
        start_time = datetime.utcnow()
        
        while self.should_run:
            try:
                self.ws = await websockets.connect(self.ws_url)
                self.connected = True
                self.reconnection_attempts = 0
                
                # Update system state
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status="PRICE_MANAGER_CONNECTED",
                        reconnection_attempts=0
                    )
                
                logger.info("Price WebSocket connected", url=self.ws_url)
                return True
                
            except WebSocketException as e:
                self.connected = False
                self.reconnection_attempts += 1
                
                # Update system state
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status="PRICE_MANAGER_DISCONNECTED",
                        last_error=str(e),
                        reconnection_attempts=self.reconnection_attempts
                    )
                
                # Check if we've exceeded the timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > WEBSOCKET_RECONNECT_TIMEOUT:
                    logger.error(
                        "Price WebSocket connection failed after timeout",
                        attempts=self.reconnection_attempts,
                        elapsed_seconds=elapsed
                    )
                    return False
                
                # Exponential backoff
                logger.warning(
                    "Price WebSocket connection failed, retrying",
                    attempt=self.reconnection_attempts,
                    delay=retry_delay,
                    error=str(e)
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Cap at 60 seconds
    
    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        self.should_run = False
        if self.ws and self.connected:
            await self.ws.close()
            self.connected = False
            logger.info("Price WebSocket disconnected")
    
    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """
        Handle incoming trade message.
        
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
    
    async def listen(self) -> None:
        """
        Main loop for receiving messages.
        Handles reconnection if connection is lost.
        """
        while self.should_run:
            if not self.connected:
                if not await self.connect():
                    logger.error("Price WebSocket failed to initialize")
                    return
            
            try:
                async for message in self.ws:
                    self.last_message_time = datetime.utcnow()
                    try:
                        data = json.loads(message)
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Invalid JSON received",
                            message=message,
                            error=str(e)
                        )
            
            except WebSocketException as e:
                self.connected = False
                logger.error(
                    "WebSocket error during listen",
                    error=str(e)
                )
                # Connection lost, try to reconnect
                continue
    
    def get_current_price(self) -> Optional[float]:
        """
        Get the most recent price.
        Falls back to REST API if WebSocket is not available.
        
        Returns:
            Optional[float]: Current price or None if not available
        """
        if self.current_price is not None:
            return self.current_price
        
        # Fallback to REST API
        try:
            response = requests.get(self.rest_api_url)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except Exception as e:
            logger.error(
                "REST API fallback failed",
                error=str(e)
            )
            return None
    
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