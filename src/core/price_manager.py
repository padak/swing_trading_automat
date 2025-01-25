"""
Price manager for handling real-time price updates and WebSocket connections.
Also handles user data stream for order updates.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
import time
import websocket
import requests
import hmac
import hashlib
import threading
from binance.client import Client

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
    BINANCE_STREAM_URL,
    LISTEN_KEY_KEEP_ALIVE_INTERVAL,
    PRICE_UPDATE_INTERVAL,
    WEBSOCKET_CLOSE_TIMEOUT,
    API_REQUEST_TIMEOUT,
    API_KEEPALIVE_TIMEOUT
)
from src.db.operations import get_db, update_system_state
from src.db.models import SystemStatus, OrderStatus

class PriceManager:
    """
    Price manager that handles WebSocket connections for price updates and order status.
    Includes REST API fallback for reliability.
    """
    
    def __init__(self):
        """
        Initialize price manager with WebSocket and REST endpoints.
        """
        self.logger = get_logger(__name__)
        self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
        
        symbol = TRADING_SYMBOL.lower()
        self.ws_url = f"{BINANCE_STREAM_URL}/ws/{symbol}@trade"
        self.rest_api_url = f"{BINANCE_API_URL}/v3/ticker/price?symbol={TRADING_SYMBOL}"
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.user_ws: Optional[websocket.WebSocketApp] = None
        self.connected = False
        self.user_stream_connected = False
        self.should_run = True
        self.last_message_time: Optional[float] = None
        self.reconnection_start_time: Optional[float] = None
        self.reconnection_attempts = 0
        self.using_rest_fallback = False
        
        self.current_price: Optional[float] = None
        self.price_callbacks: List[Callable[[float], None]] = []
        self.order_callbacks: List[Callable[[Dict], None]] = []
        
        # REST API endpoints
        self.listen_key_url = f"{BINANCE_API_URL}/v3/userDataStream"
        self.listen_key: Optional[str] = None
        self.listen_key_last_update: Optional[float] = None
        
        # Thread tracking
        self.threads: List[threading.Thread] = []
    
    def start(self) -> None:
        """Start price manager and monitoring threads."""
        try:
            self.should_run = True
            self.logger.info("Starting PriceManager")
            
            # Get initial price via REST API
            self._update_price_rest()
            
            # Start market data WebSocket
            self._start_market_websocket()
            
            # Start user data stream
            self._start_user_websocket()
            
            # Start monitoring thread
            monitor_thread = threading.Thread(target=self._monitor_connection)
            monitor_thread.daemon = True
            self.threads.append(monitor_thread)
            monitor_thread.start()
            
            self.logger.info("PriceManager started successfully")
            
        except Exception as e:
            self.logger.error("Failed to start PriceManager", exc_info=True)
            self.stop()
            raise
    
    def stop(self) -> None:
        """Stop price manager and cleanup WebSocket connections."""
        self.logger.debug("PriceManager stop initiated")
        self.should_run = False

        try:
            # Close WebSockets with timeout
            self._close_websockets()
            
            # Stop all threads with timeout
            self._stop_threads()
            
            # Delete listen key
            if self.listen_key:
                self._delete_listen_key()
            
            # Update final state
            with get_db() as db:
                update_system_state(
                    db,
                    websocket_status="STOPPED",
                    last_error=None
                )
            
            self.logger.info("PriceManager stopped successfully")
            
        except Exception as e:
            self.logger.error("Error during PriceManager shutdown", exc_info=True)
            raise

    def _close_websockets(self) -> None:
        """Close all WebSocket connections with timeout."""
        for ws in [self.ws, self.user_ws]:
            if ws:
                try:
                    ws.close()
                    # Wait briefly for clean close
                    time.sleep(WEBSOCKET_CLOSE_TIMEOUT)
                except Exception as e:
                    self.logger.error(f"Error closing WebSocket: {e}", exc_info=True)

    def _stop_threads(self) -> None:
        """Stop all threads with timeout."""
        for thread in self.threads:
            try:
                if thread.is_alive():
                    thread.join(timeout=1.0)  # 1 second timeout per thread
                    if thread.is_alive():
                        self.logger.warning(f"Thread {thread.name} did not stop in time")
            except Exception as e:
                self.logger.error(f"Error stopping thread {thread.name}: {e}", exc_info=True)
        self.threads.clear()

    def _get_listen_key(self) -> Optional[str]:
        """Get user data stream listen key."""
        try:
            response = requests.post(
                f"{BINANCE_API_URL}/v3/userDataStream",
                headers={"X-MBX-APIKEY": BINANCE_API_KEY},
                timeout=API_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()['listenKey']
        except Exception as e:
            self.logger.error("Failed to get listen key", exc_info=True)
            return None
    
    def _keep_listen_key_alive(self) -> None:
        """Ping listen key to keep it alive."""
        if not self.listen_key:
            return
        
        try:
            response = requests.put(
                f"{BINANCE_API_URL}/v3/userDataStream",
                headers={"X-MBX-APIKEY": BINANCE_API_KEY},
                params={'listenKey': self.listen_key},
                timeout=API_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            self.logger.debug("Successfully refreshed listen key")
        except Exception as e:
            self.logger.error("Failed to keep listen key alive", exc_info=True)
            self.listen_key = None
    
    def _delete_listen_key(self) -> None:
        """Delete listen key on shutdown."""
        if not self.listen_key:
            return
        
        try:
            response = requests.delete(
                f"{BINANCE_API_URL}/v3/userDataStream",
                headers={"X-MBX-APIKEY": BINANCE_API_KEY},
                params={"listenKey": self.listen_key},
                timeout=API_REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except Exception as e:
            self.logger.error("Failed to delete listen key", exc_info=True)
    
    def _run_market_websocket(self) -> None:
        """Run market data WebSocket connection with error handling."""
        while self.should_run:
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_message=self._handle_market_message,
                    on_error=self._handle_market_error,
                    on_close=self._handle_market_close,
                    on_open=self._handle_market_open
                )
                
                # Save connection state
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status="CONNECTING",
                        last_error=None
                    )
                
                self.ws.run_forever()
                
                # If we get here, connection was closed
                if not self.should_run:
                    break
                    
                # Attempt reconnection with exponential backoff
                if not self._handle_reconnection():
                    break
                    
            except Exception as e:
                self.logger.error(
                    "Error in market WebSocket thread",
                    error=str(e)
                )
                if not self._handle_reconnection():
                    break
    
    def _handle_market_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle successful market WebSocket connection."""
        self.connected = True
        self.reconnection_attempts = 0
        self._stop_rest_fallback()
        
        # Update connection state
        with get_db() as db:
            update_system_state(
                db,
                websocket_status="CONNECTED",
                last_error=None
            )
        
        self.logger.info(
            "Market WebSocket connected",
            symbol=TRADING_SYMBOL
        )
    
    def _handle_market_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle incoming market data message."""
        try:
            data = json.loads(message)
            if 'p' in data:  # Price update
                price = float(data['p'])
                self.current_price = price
                self.last_message_time = time.time()
                
                # Notify callbacks
                for callback in self.price_callbacks:
                    try:
                        callback(price)
                    except Exception as e:
                        self.logger.error("Error in price callback", exc_info=True)
                        
        except json.JSONDecodeError:
            self.logger.error(
                "Invalid JSON in market message",
                message=message[:100]  # Log first 100 chars only
            )
        except Exception as e:
            self.logger.error(
                "Error processing market message",
                error=str(e),
                message=message[:100]
            )
    
    def _handle_market_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """Handle market WebSocket error."""
        self.connected = False
        
        # Update connection state
        with get_db() as db:
            update_system_state(
                db,
                websocket_status="ERROR",
                last_error=str(error)
            )
        
        self.logger.error("Market WebSocket error", error=str(error))
    
    def _handle_market_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """Handle market WebSocket closure."""
        self.connected = False
        
        # Update connection state
        with get_db() as db:
            update_system_state(
                db,
                websocket_status="DISCONNECTED",
                last_error=f"Connection closed: {close_msg}"
            )
        
        self.logger.warning("Market WebSocket closed", status_code=close_status_code, message=close_msg)
    
    def _run_user_websocket(self) -> None:
        """Run user data WebSocket connection with automatic listen key management."""
        while self.should_run:
            try:
                if not self.listen_key:
                    self.listen_key = self._get_listen_key()
                    if not self.listen_key:
                        self.logger.error("Failed to get listen key, retrying...")
                        time.sleep(WEBSOCKET_RECONNECT_DELAY)
                        continue
                    
                    # Start keep-alive thread
                    self._start_keep_alive_timer()
                
                stream_url = f"{BINANCE_STREAM_URL}/ws/{self.listen_key}"
                self.user_ws = websocket.WebSocketApp(
                    stream_url,
                    on_message=self._handle_user_message,
                    on_error=self._handle_user_error,
                    on_close=self._handle_user_close,
                    on_open=self._handle_user_open
                )
                
                self.logger.info(
                    "Starting user data WebSocket",
                    url=stream_url
                )
                
                self.user_ws.run_forever()
                
                if self.should_run:
                    if not self._handle_reconnection():
                        break
                        
            except Exception as e:
                self.logger.error(
                    "User WebSocket error",
                    error=str(e),
                    symbol=TRADING_SYMBOL
                )
                if not self._handle_reconnection():
                    break

    def _keep_listen_key_alive_loop(self) -> None:
        """Keep listen key alive with periodic updates."""
        while self.should_run and self.listen_key:
            try:
                # Update listen key if it's time
                current_time = time.time()
                if (not self.listen_key_last_update or 
                    current_time - self.listen_key_last_update >= LISTEN_KEY_KEEP_ALIVE_INTERVAL):
                    self._keep_listen_key_alive()
                    self.listen_key_last_update = current_time
                
                # Sleep for a portion of the interval
                time.sleep(LISTEN_KEY_KEEP_ALIVE_INTERVAL / 4)
                
            except Exception as e:
                self.logger.error(
                    "Error in listen key keep-alive loop",
                    error=str(e)
                )
                time.sleep(WEBSOCKET_RECONNECT_DELAY)

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
            self.logger.error(
                "Failed to handle user message",
                error=str(e),
                message=message
            )
    
    def _handle_execution_report(self, data: Dict[str, Any]) -> None:
        """
        Handle order execution report with enhanced validation and error handling.
        
        Args:
            data: Execution report data from Binance
        """
        try:
            # Required fields validation
            required_fields = ['i', 'X', 'q', 'z', 'p', 'l', 'L']
            if not all(field in data for field in required_fields):
                self.logger.error("Missing required fields in execution report", data=data)
                return
            
            # Map Binance status to internal status
            status_mapping = {
                'NEW': 'OPEN',
                'PARTIALLY_FILLED': 'PARTIALLY_FILLED',
                'FILLED': 'FILLED',
                'CANCELED': 'CANCELLED',
                'REJECTED': 'REJECTED',
                'EXPIRED': 'EXPIRED',
                'PENDING_CANCEL': 'CANCELLED'
            }
            
            # Extract and validate data
            order_id = str(data['i'])  # Order ID
            status = status_mapping.get(data['X'], 'REJECTED')  # Map status or default to REJECTED
            quantity = float(data['q'])  # Original quantity
            filled = float(data['z'])    # Cumulative filled
            price = float(data['p'])     # Order price
            last_filled_qty = float(data['l'])  # Last filled quantity
            last_filled_price = float(data['L']) # Last filled price
            
            # Create order update
            order_update = {
                'order_id': order_id,
                'status': status,
                'quantity': quantity,
                'filled': filled,
                'price': price,
                'last_filled_qty': last_filled_qty,
                'last_filled_price': last_filled_price,
                'timestamp': data.get('T', int(time.time() * 1000))  # Event time
            }
            
            # Add commission info if available
            if 'n' in data and 'N' in data:
                order_update.update({
                    'commission': float(data['n']),
                    'commission_asset': data['N']
                })
            
            # Notify callbacks
            for callback in self.order_callbacks:
                try:
                    callback(order_update)
                except Exception as e:
                    self.logger.error("Error in order callback", callback=callback.__name__, error=str(e))
            
            self.logger.info("Processed execution report", 
                           order_id=order_id,
                           status=status,
                           filled=filled,
                           quantity=quantity)
            
        except Exception as e:
            self.logger.error("Failed to handle execution report", error=str(e), data=data)
    
    def _handle_account_update(self, data: Dict[str, Any]) -> None:
        """
        Handle account balance and position updates.
        
        Args:
            data: Account update data from Binance
        """
        try:
            # Validate update has balances
            if 'B' not in data:
                self.logger.error("Missing balances in account update", data=data)
                return
            
            # Process each balance update
            for balance in data['B']:
                if not all(k in balance for k in ['a', 'f', 'l']):
                    self.logger.error("Invalid balance data", balance=balance)
                    continue
                
                asset = balance['a']  # Asset
                free = float(balance['f'])  # Free amount
                locked = float(balance['l'])  # Locked amount
                
                # Log significant balance changes
                self.logger.info("Account balance update",
                               asset=asset,
                               free=free,
                               locked=locked,
                               timestamp=data.get('E', int(time.time() * 1000)))
            
        except Exception as e:
            self.logger.error("Failed to handle account update", error=str(e), data=data)
    
    def _handle_user_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """Handle user data WebSocket error."""
        self.user_stream_connected = False
        
        self.logger.error(
            "User data WebSocket error",
            error=str(error),
            symbol=TRADING_SYMBOL
        )
        
        # Update system state
        with get_db() as db:
            update_system_state(
                db,
                websocket_status="ERROR",
                last_error=str(error)
            )

    def _handle_user_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """Handle user data WebSocket closure."""
        self.user_stream_connected = False
        
        self.logger.warning(
            "User data WebSocket closed",
            status_code=close_status_code,
            message=close_msg
        )
        
        # Update system state
        with get_db() as db:
            update_system_state(
                db,
                websocket_status="PARTIALLY_CONNECTED",
                last_error=f"User data stream closed: {close_msg}"
            )

    def _handle_user_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle user data WebSocket open."""
        self.user_stream_connected = True
        self.reconnection_attempts = 0
        self.logger.info(
            "User data WebSocket connected",
            symbol=TRADING_SYMBOL
        )
    
    def _handle_reconnection(self) -> bool:
        """
        Handle WebSocket reconnection with exponential backoff.
        Returns True if should continue reconnecting, False if should shutdown.
        """
        # Initialize reconnection start time if first attempt
        if self.reconnection_attempts == 0:
            self.reconnection_start_time = time.time()
            self._start_rest_fallback()
        
        # Check if we've exceeded 15-minute timeout
        if time.time() - self.reconnection_start_time > WEBSOCKET_RECONNECT_TIMEOUT:
            self.logger.error(
                "WebSocket reconnection timeout exceeded",
                timeout_minutes=WEBSOCKET_RECONNECT_TIMEOUT/60,
                total_attempts=self.reconnection_attempts
            )
            self._handle_timeout_shutdown()
            return False
        
        # Calculate exponential backoff delay
        delay = WEBSOCKET_INITIAL_RETRY_DELAY * (2 ** self.reconnection_attempts)
        self.reconnection_attempts += 1
        
        self.logger.info(
            "Attempting to reconnect",
            attempt=self.reconnection_attempts,
            delay=delay,
            elapsed_time=(time.time() - self.reconnection_start_time)
        )
        
        time.sleep(delay)
        return True

    def _start_rest_fallback(self) -> None:
        """Start REST API fallback for price and order updates."""
        if not self.using_rest_fallback:
            self.using_rest_fallback = True
            self.rest_fallback_thread = threading.Thread(target=self._run_rest_fallback)
            self.rest_fallback_thread.daemon = True
            self.rest_fallback_thread.start()
            self.logger.info("Started REST API fallback")

    def _stop_rest_fallback(self) -> None:
        """Stop REST API fallback when WebSocket is restored."""
        self.using_rest_fallback = False
        self.logger.info("Stopped REST API fallback")

    def _run_rest_fallback(self) -> None:
        """Run REST API fallback loop for price and order updates."""
        while self.using_rest_fallback and self.should_run:
            try:
                # Get current price
                response = requests.get(self.rest_api_url)
                if response.status_code == 200:
                    price = float(response.json()['price'])
                    for callback in self.price_callbacks:
                        callback(price)
                
                # Get order updates if needed
                # ... (order polling logic)
                
                time.sleep(REST_API_REFRESH_RATE)
            except Exception as e:
                self.logger.error("REST API fallback error", error=str(e))
                time.sleep(REST_API_REFRESH_RATE)

    def _handle_timeout_shutdown(self) -> None:
        """Handle shutdown after WebSocket reconnection timeout."""
        self.logger.critical(
            "Initiating shutdown due to WebSocket reconnection timeout",
            reconnection_attempts=self.reconnection_attempts,
            elapsed_time=(time.time() - self.reconnection_start_time)
        )
        
        try:
            # Save current state
            with get_db() as db:
                update_system_state(
                    db,
                    websocket_status="DISCONNECTED",
                    last_error="WebSocket reconnection timeout exceeded"
                )
            
            # Stop all operations
            self.should_run = False
            if self.ws:
                self.ws.close()
            if self.user_ws:
                self.user_ws.close()
            if self.listen_key:
                self._delete_listen_key()
            
            self.logger.info("Completed graceful shutdown after timeout")
            
        except Exception as e:
            self.logger.error(
                "Error during timeout shutdown",
                error=str(e)
            )
        
        # Exit with non-zero status code
        import sys
        sys.exit(1)
    
    def register_price_callback(self, callback: Callable[[float], None]) -> None:
        """
        Registers a callback function to handle price updates.
        
        Args:
            callback (Callable[[float], None]): A function that takes a price float 
                as a parameter and returns None.
        """
        self.price_callbacks.append(callback)
        self.logger.info("Registered price update callback")

    def register_order_callback(self, callback: Callable[[Dict], None]) -> None:
        """
        Registers a callback function to handle order updates.
        
        Args:
            callback (Callable[[Dict], None]): A function that takes an order update dict
                as a parameter and returns None.
        """
        self.order_callbacks.append(callback)
        self.logger.info("Registered order update callback")
    
    def get_current_price(self) -> Optional[float]:
        """Get current price from REST API if WebSocket is not available."""
        if self.current_price is not None:
            return self.current_price
        
        try:
            response = requests.get(self.rest_api_url)
            response.raise_for_status()
            return float(response.json()['price'])
        except Exception as e:
            self.logger.error("Failed to get price from REST API",
                            error=str(e),
                            symbol=TRADING_SYMBOL)
            return None

    def _monitor_connection(self) -> None:
        """Monitor WebSocket connection health."""
        while self.should_run:
            try:
                current_time = time.time()
                
                # Check market data connection
                if self.connected and self.last_message_time:
                    elapsed = current_time - self.last_message_time
                    if elapsed > PRICE_UPDATE_INTERVAL * 2:
                        self.logger.warning(
                            "No market data received recently",
                            elapsed_seconds=elapsed
                        )
                        self._update_price_rest()  # Fallback to REST API
                
                # Check user data connection
                if self.user_stream_connected and self.listen_key_last_update:
                    elapsed = current_time - self.listen_key_last_update
                    if elapsed > API_KEEPALIVE_TIMEOUT:
                        self.logger.warning(
                            "User data stream keep-alive timeout",
                            elapsed_seconds=elapsed
                        )
                        self._keep_listen_key_alive()
                
                time.sleep(0.1)  # Check frequently for responsive shutdown
                
            except Exception as e:
                self.logger.error("Error in connection monitor", exc_info=True)
                if not self.should_run:
                    break
                time.sleep(0.1)

    def _start_keep_alive_timer(self) -> None:
        """Start timer to keep the user data stream alive."""
        if not self.listen_key or not self.should_run:
            return
            
        def keep_alive():
            while self.should_run and self.listen_key:
                try:
                    self._keep_listen_key_alive()
                    time.sleep(API_KEEPALIVE_TIMEOUT / 2)  # Refresh at half the timeout
                except Exception as e:
                    self.logger.error("Keep-alive timer error", exc_info=True)
                    if not self.should_run:
                        break
                    time.sleep(1.0)  # Brief delay on error

        keep_alive_thread = threading.Thread(target=keep_alive)
        keep_alive_thread.daemon = True
        self.threads.append(keep_alive_thread)
        keep_alive_thread.start()
        self.logger.debug("Started listen key keep-alive timer")

    def _start_market_websocket(self) -> None:
        """Start market data WebSocket connection."""
        try:
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=self._handle_market_message,
                on_error=self._handle_market_error,
                on_close=self._handle_market_close,
                on_open=self._handle_market_open
            )
            
            ws_thread = threading.Thread(target=self.ws.run_forever)
            ws_thread.daemon = True
            self.threads.append(ws_thread)
            ws_thread.start()
            
            self.logger.info("Started market data WebSocket", url=self.ws_url)
            
        except Exception as e:
            self.logger.error("Failed to start market WebSocket", exc_info=True)
            raise

    def _start_user_websocket(self) -> None:
        """Start user data WebSocket connection."""
        try:
            self.listen_key = self._get_listen_key()
            if not self.listen_key:
                self.logger.error("Failed to get listen key")
                return
            
            stream_url = f"{BINANCE_STREAM_URL}/ws/{self.listen_key}"
            self.user_ws = websocket.WebSocketApp(
                stream_url,
                on_message=self._handle_user_message,
                on_error=self._handle_user_error,
                on_close=self._handle_user_close,
                on_open=self._handle_user_open
            )
            
            ws_thread = threading.Thread(target=self.user_ws.run_forever)
            ws_thread.daemon = True
            self.threads.append(ws_thread)
            ws_thread.start()
            
            # Start keep-alive timer
            self._start_keep_alive_timer()
            
            self.logger.info("Started user data WebSocket", url=stream_url)
            
        except Exception as e:
            self.logger.error("Failed to start user WebSocket", exc_info=True)
            raise

    def _update_price_rest(self) -> None:
        """Update price using REST API as fallback."""
        try:
            response = requests.get(
                f"{BINANCE_API_URL}/v3/ticker/price",
                params={"symbol": TRADING_SYMBOL},
                timeout=API_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            self.current_price = float(data['price'])
            self.logger.debug("Updated price via REST: %s", self.current_price)
        except Exception as e:
            self.logger.error("Failed to update price via REST", exc_info=True)

    def _start_keep_alive_timer(self) -> None:
        """Start timer to keep the user data stream alive."""
        if not self.listen_key or not self.should_run:
            return
            
        def keep_alive():
            while self.should_run and self.listen_key:
                try:
                    self._keep_listen_key_alive()
                    time.sleep(API_KEEPALIVE_TIMEOUT / 2)  # Refresh at half the timeout
                except Exception as e:
                    self.logger.error("Keep-alive timer error", exc_info=True)
                    if not self.should_run:
                        break
                    time.sleep(1.0)  # Brief delay on error

        keep_alive_thread = threading.Thread(target=keep_alive)
        keep_alive_thread.daemon = True
        self.threads.append(keep_alive_thread)
        keep_alive_thread.start()
        self.logger.debug("Started listen key keep-alive timer") 