"""
Base WebSocket manager with reconnection logic and error handling.
"""
import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, Callable

import websockets
from websockets.exceptions import WebSocketException

from src.config.logging_config import get_logger
from src.config.settings import (
    WEBSOCKET_RECONNECT_TIMEOUT,
    WEBSOCKET_INITIAL_RETRY_DELAY
)
from src.db.operations import get_db, update_system_state

logger = get_logger(__name__)

class WebSocketManager(ABC):
    """Base class for WebSocket connections with automatic reconnection."""
    
    def __init__(self, url: str, name: str):
        """
        Initialize the WebSocket manager.
        
        Args:
            url: WebSocket endpoint URL
            name: Name of this connection for logging
        """
        self.url = url
        self.name = name
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.should_run = True
        self.last_message_time: Optional[datetime] = None
        self.reconnection_attempts = 0
        self.message_handlers: Dict[str, Callable] = {}
        
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
                self.ws = await websockets.connect(self.url)
                self.connected = True
                self.reconnection_attempts = 0
                
                # Update system state
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status=f"{self.name}_CONNECTED",
                        reconnection_attempts=0
                    )
                
                logger.info(f"{self.name} WebSocket connected", url=self.url)
                return True
                
            except WebSocketException as e:
                self.connected = False
                self.reconnection_attempts += 1
                
                # Update system state
                with get_db() as db:
                    update_system_state(
                        db,
                        websocket_status=f"{self.name}_DISCONNECTED",
                        last_error=str(e),
                        reconnection_attempts=self.reconnection_attempts
                    )
                
                # Check if we've exceeded the timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > WEBSOCKET_RECONNECT_TIMEOUT:
                    logger.error(
                        f"{self.name} WebSocket connection failed after timeout",
                        attempts=self.reconnection_attempts,
                        elapsed_seconds=elapsed
                    )
                    return False
                
                # Exponential backoff
                logger.warning(
                    f"{self.name} WebSocket connection failed, retrying",
                    attempt=self.reconnection_attempts,
                    delay=retry_delay,
                    error=str(e)
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Cap at 60 seconds
    
    @abstractmethod
    async def subscribe(self) -> bool:
        """
        Subscribe to required channels after connection.
        Must be implemented by subclasses.
        
        Returns:
            bool: True if subscription successful, False otherwise
        """
        pass
    
    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        self.should_run = False
        if self.ws and self.connected:
            await self.ws.close()
            self.connected = False
            logger.info(f"{self.name} WebSocket disconnected")
    
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """
        Send a message through the WebSocket connection.
        
        Args:
            message: Dictionary to be sent as JSON
            
        Returns:
            bool: True if send successful, False otherwise
        """
        if not self.ws or not self.connected:
            logger.error(f"{self.name} WebSocket not connected")
            return False
        
        try:
            await self.ws.send(json.dumps(message))
            return True
        except WebSocketException as e:
            logger.error(
                f"{self.name} WebSocket send failed",
                error=str(e),
                message=message
            )
            self.connected = False
            return False
    
    def register_handler(self, event_type: str, handler: Callable) -> None:
        """
        Register a handler function for a specific event type.
        
        Args:
            event_type: Type of event to handle
            handler: Callback function to handle the event
        """
        self.message_handlers[event_type] = handler
    
    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """
        Process incoming WebSocket messages.
        
        Args:
            message: Received message as dictionary
        """
        event_type = message.get("e")
        if event_type and event_type in self.message_handlers:
            try:
                await self.message_handlers[event_type](message)
            except Exception as e:
                logger.error(
                    f"{self.name} Message handler error",
                    event_type=event_type,
                    error=str(e)
                )
        else:
            logger.warning(
                f"{self.name} Unhandled message type",
                event_type=event_type
            )
    
    async def listen(self) -> None:
        """
        Main loop for receiving messages.
        Handles reconnection if connection is lost.
        """
        while self.should_run:
            if not self.connected:
                if not await self.connect() or not await self.subscribe():
                    logger.error(f"{self.name} WebSocket failed to initialize")
                    return
            
            try:
                async for message in self.ws:
                    self.last_message_time = datetime.utcnow()
                    try:
                        data = json.loads(message)
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"{self.name} Invalid JSON received",
                            message=message,
                            error=str(e)
                        )
            
            except WebSocketException as e:
                self.connected = False
                logger.error(
                    f"{self.name} WebSocket error during listen",
                    error=str(e)
                )
                # Connection lost, try to reconnect
                continue 