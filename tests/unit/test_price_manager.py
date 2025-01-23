"""
Unit tests for price manager.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import WebSocketException

from src.core.price_manager import PriceManager

@pytest.fixture
def price_manager():
    """Create a price manager instance for testing."""
    return PriceManager()

@pytest.mark.asyncio
async def test_websocket_connection(price_manager):
    """Test WebSocket connection and disconnection."""
    # Mock the websockets.connect
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.close = AsyncMock()
    
    with patch('websockets.connect', return_value=mock_ws):
        # Test connection
        connected = await price_manager.connect()
        assert connected is True
        assert price_manager.connected is True
        
        # Test disconnection
        await price_manager.disconnect()
        assert price_manager.connected is False
        mock_ws.close.assert_called_once()

@pytest.mark.asyncio
async def test_websocket_reconnection(price_manager):
    """Test WebSocket reconnection logic."""
    # Mock websockets.connect to fail first, then succeed
    mock_ws = AsyncMock()
    connect_mock = AsyncMock(side_effect=[
        WebSocketException("Connection failed"),
        mock_ws
    ])
    
    with patch('websockets.connect', connect_mock), \
         patch('asyncio.sleep', AsyncMock()):  # Skip actual sleep
        
        # Should succeed on second attempt
        connected = await price_manager.connect()
        assert connected is True
        assert price_manager.connected is True
        assert price_manager.reconnection_attempts == 0  # Reset after success

@pytest.mark.asyncio
async def test_message_handling(price_manager):
    """Test WebSocket message handling."""
    # Create mock callbacks
    callback1 = MagicMock()
    callback2 = MagicMock()
    
    # Register callbacks
    price_manager.register_price_callback(callback1)
    price_manager.register_price_callback(callback2)
    
    # Simulate trade message
    trade_msg = {
        "e": "trade",
        "p": "1.2345",
        "q": "100",
        "T": 1234567890123
    }
    
    # Process message
    await price_manager._handle_message(trade_msg)
    
    # Verify callbacks were called
    callback1.assert_called_once_with(1.2345)
    callback2.assert_called_once_with(1.2345)
    
    # Verify current price was updated
    assert price_manager.get_current_price() == 1.2345
    
    # Test callback removal
    price_manager.remove_price_callback(callback1)
    await price_manager._handle_message(trade_msg)
    
    # callback1 should not be called again
    assert callback1.call_count == 1
    # callback2 should be called again
    assert callback2.call_count == 2

@pytest.mark.asyncio
async def test_invalid_message_handling(price_manager):
    """Test handling of invalid messages."""
    # Invalid message (missing price)
    invalid_msg = {
        "e": "trade",
        "q": "100",
        "T": 1234567890123
    }
    
    # Should not raise exception but log error
    with patch('src.core.price_manager.logger.error') as mock_logger:
        await price_manager._handle_message(invalid_msg)
        mock_logger.assert_called_once()
        assert price_manager.get_current_price() is None

def test_rest_api_fallback(price_manager):
    """Test REST API fallback when WebSocket price is not available."""
    # Mock successful REST API response
    mock_response = MagicMock()
    mock_response.json.return_value = {"price": "1.2345"}
    
    with patch('requests.get', return_value=mock_response):
        # Clear WebSocket price
        price_manager.current_price = None
        
        # Should fall back to REST API
        price = price_manager.get_current_price()
        assert price == 1.2345
    
    # Mock failed REST API response
    with patch('requests.get', side_effect=Exception("API Error")):
        price_manager.current_price = None
        price = price_manager.get_current_price()
        assert price is None

@pytest.mark.asyncio
async def test_listen_loop(price_manager):
    """Test the main WebSocket listen loop."""
    mock_ws = AsyncMock()
    mock_messages = [
        '{"e":"trade","p":"1.2345","q":"100"}',
        '{"e":"trade","p":"1.2350","q":"200"}',
        WebSocketException("Connection lost")
    ]
    mock_ws.__aiter__.return_value = mock_messages
    
    with patch('websockets.connect', return_value=mock_ws), \
         patch('asyncio.sleep', AsyncMock()):
        
        # Start listening but break after processing messages
        price_manager.should_run = False
        await price_manager.listen()
        
        # Verify the last valid price was recorded
        assert price_manager.current_price == 1.2350 