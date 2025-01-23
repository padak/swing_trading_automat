"""
Price manager for handling real-time price updates and WebSocket connections.
Also handles user data stream for order updates.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
import time
import websocket
import requests
import hmac
import hashlib
import threading

from src.config.logging_config import get_logger
from src.config.settings import (
    TRADING_SYMBOL,
    REST_API_REFRESH_RATE,
    WEBSOCKET_RECONNECT_TIMEOUT,
    WEBSOCKET_INITIAL_RETRY_DELAY,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    WEBSOCKET_RECONNECT_DELAY,
    MAX_RECONNECTION_ATTEMPTS,
    BINANCE_API_URL,
    BINANCE_STREAM_URL
)
from src.db.operations import get_db, update_system_state

logger = get_logger(__name__)

class PriceManager:
    """
    Price manager that handles WebSocket connections for price updates and order status.
    Includes REST API fallback for reliability.
    """
    
    def __init__(self):
        """
        Initialize price manager with WebSocket and REST endpoints.
        """
        symbol = TRADING_SYMBOL.lower()
        self.ws_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"
        self.rest_api_url = f"https://api.binance.com/api/v3/ticker/price?symbol={TRADING_SYMBOL}"
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.user_ws: Optional[websocket.WebSocketApp] = None
        self.connected = False
        self.user_stream_connected = False
        self.should_run = True
        self.last_message_time: Optional[float] = None
        self.reconnection_attempts = 0
        
        self.current_price: Optional[float] = None
        self.price_callbacks: Dict[str, Callable[[float], None]] = {}
        self.order_callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        
        # REST API endpoints
        self.listen_key_url = f"{BINANCE_API_URL}/v3/userDataStream"
        self.listen_key: Optional[str] = None
        
        # Start WebSocket threads
        self.market_thread = threading.Thread(target=self._run_market_websocket)
        self.user_thread = threading.Thread(target=self._run_user_websocket)
        self.market_thread.daemon = True
        self.user_thread.daemon = True
    
    def start(self) -> None:
        """Start both market data and user data streams."""
        self.market_thread.start()
        self.user_thread.start()
    
    def stop(self) -> None:
        """Stop both WebSocket connections gracefully."""
        self.should_run = False
        if self.ws:
            self.ws.close()
        if self.user_ws:
            self.user_ws.close()
        if self.listen_key:
            self._delete_listen_key()
    
    def _get_listen_key(self) -> Optional[str]:
        """Get user data stream listen key."""
        try:
            headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
            response = requests.post(self.listen_key_url, headers=headers)
            response.raise_for_status()
            return response.json()['listenKey']
        except Exception as e:
            logger.error(
                "Failed to get listen key",
                error=str(e),
                symbol=TRADING_SYMBOL
            )
            return None
    
    def _keep_listen_key_alive(self) -> None:
        """Ping listen key to keep it alive."""
        if not self.listen_key:
            return
        
        try:
            headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
            response = requests.put(
                f"{self.listen_key_url}/{self.listen_key}",
                headers=headers
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(
                "Failed to keep listen key alive",
                error=str(e),
                symbol=TRADING_SYMBOL
            )
            self.listen_key = None
    
    def _delete_listen_key(self) -> None:
        """Delete listen key on shutdown."""
        if not self.listen_key:
            return
        
        try:
            headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
            response = requests.delete(
                f"{self.listen_key_url}/{self.listen_key}",
                headers=headers
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(
                "Failed to delete listen key",
                error=str(e),
                symbol=TRADING_SYMBOL
            )
    
    def _run_market_websocket(self) -> None:
        """Run market data WebSocket connection."""
        while self.should_run:
            try:
                stream_url = f"{BINANCE_STREAM_URL}/ws/{TRADING_SYMBOL}@trade"
                self.ws = websocket.WebSocketApp(
                    stream_url,
                    on_message=self._handle_market_message,
                    on_error=self._handle_error,
                    on_close=self._handle_close,
                    on_open=self._handle_open
                )
                self.ws.run_forever()
                
                if self.should_run:
                    self._handle_reconnection()
            except Exception as e:
                logger.error(
                    "Market WebSocket error",
                    error=str(e),
                    symbol=TRADING_SYMBOL
                )
                self._handle_reconnection()
    
    def _run_user_websocket(self) -> None:
        """Run user data WebSocket connection."""
        while self.should_run:
            try:
                if not self.listen_key:
                    self.listen_key = self._get_listen_key()
                    if not self.listen_key:
                        time.sleep(WEBSOCKET_RECONNECT_DELAY)
                        continue
                
                stream_url = f"{BINANCE_STREAM_URL}/ws/{self.listen_key}"
                self.user_ws = websocket.WebSocketApp(
                    stream_url,
                    on_message=self._handle_user_message,
                    on_error=self._handle_error,
                    on_close=self._handle_close,
                    on_open=self._handle_user_open
                )
                self.user_ws.run_forever()
                
                if self.should_run:
                    self._handle_reconnection()
            except Exception as e:
                logger.error(
                    "User WebSocket error",
                    error=str(e),
                    symbol=TRADING_SYMBOL
                )
                self._handle_reconnection()
    
    def _handle_market_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle market data message."""
        try:
            data = json.loads(message)
            if 'e' in data and data['e'] == 'trade':
                self.last_message_time = time.time()
                price = float(data['p'])
                for callback in self.price_callbacks.values():
                    callback(price)
        except Exception as e:
            logger.error(
                "Failed to handle market message",
                error=str(e),
                message=message
            )
    
    def _handle_user_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle user data message."""
        try:
            data = json.loads(message)
            if 'e' in data:
                event_type = data['e']
                if event_type == 'executionReport':
                    self._handle_execution_report(data)
                elif event_type == 'outboundAccountPosition':
                    self._handle_account_update(data)
        except Exception as e:
            logger.error(
                "Failed to handle user message",
                error=str(e),
                message=message
            )
    
    def _handle_execution_report(self, data: Dict[str, Any]) -> None:
        """Handle order execution report."""
        try:
            order_id = data['i']
            status = data['X']
            filled_qty = float(data['l'])
            price = float(data['L'])
            
            for callback in self.order_callbacks.values():
                callback({
                    'order_id': order_id,
                    'status': status,
                    'filled_qty': filled_qty,
                    'price': price
                })
        except Exception as e:
            logger.error(
                "Failed to handle execution report",
                error=str(e),
                data=data
            )
    
    def _handle_account_update(self, data: Dict[str, Any]) -> None:
        """Handle account balance/position updates."""
        try:
            # Process balance updates if needed
            pass
        except Exception as e:
            logger.error(
                "Failed to handle account update",
                error=str(e),
                data=data
            )
    
    def _handle_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """Handle WebSocket error."""
        logger.error(
            "WebSocket error",
            error=str(error),
            symbol=TRADING_SYMBOL
        )
    
    def _handle_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """Handle WebSocket close."""
        if ws == self.ws:
            self.connected = False
        else:
            self.user_stream_connected = False
        logger.info(
            "WebSocket connection closed",
            status_code=close_status_code,
            message=close_msg
        )
    
    def _handle_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle market data WebSocket open."""
        self.connected = True
        self.reconnection_attempts = 0
        logger.info(
            "Market data WebSocket connected",
            symbol=TRADING_SYMBOL
        )
    
    def _handle_user_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle user data WebSocket open."""
        self.user_stream_connected = True
        self.reconnection_attempts = 0
        logger.info(
            "User data WebSocket connected",
            symbol=TRADING_SYMBOL
        )
    
    def _handle_reconnection(self) -> None:
        """Handle WebSocket reconnection with exponential backoff."""
        if self.reconnection_attempts >= MAX_RECONNECTION_ATTEMPTS:
            logger.error(
                "Max reconnection attempts reached",
                symbol=TRADING_SYMBOL
            )
            return
        
        delay = WEBSOCKET_RECONNECT_DELAY * (2 ** self.reconnection_attempts)
        self.reconnection_attempts += 1
        logger.info(
            "Attempting to reconnect",
            attempt=self.reconnection_attempts,
            delay=delay
        )
        time.sleep(delay)
    
    def register_price_callback(self, name: str, callback: Callable[[float], None]) -> None:
        """Register callback for price updates."""
        self.price_callbacks[name] = callback
    
    def register_order_callback(self, name: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register callback for order updates."""
        self.order_callbacks[name] = callback
    
    def get_current_price(self) -> Optional[float]:
        """Get current price from REST API if WebSocket is not available."""
        if self.current_price is not None:
            return self.current_price
        
        try:
            response = requests.get(self.rest_api_url)
            response.raise_for_status()
            return float(response.json()['price'])
        except Exception as e:
            logger.error(
                "Failed to get price from REST API",
                error=str(e),
                symbol=TRADING_SYMBOL
            )
            return None 