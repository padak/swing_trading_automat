"""
Unit tests for market data stream manager.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import WebSocketException

from src.core.market_stream import MarketStreamManager

@pytest.fixture
def market_stream():
    """Create a market stream instance for testing."""
    return MarketStreamManager()

@pytest.mark.asyncio
async def test_market_stream_connection(market_stream):
    """Test market stream connection and subscription."""
    # Mock the websockets.connect
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.close = AsyncMock()
    
    with patch('websockets.connect', return_value=mock_ws):
        # Test connection
        connected = await market_stream.connect()
        assert connected is True
        assert market_stream.connected is True
        
        # Test subscription
        subscribed = await market_stream.subscribe()
        assert subscribed is True
        
        # Test disconnection
        await market_stream.disconnect()
        assert market_stream.connected is False
        mock_ws.close.assert_called_once()

@pytest.mark.asyncio
async def test_market_stream_reconnection(market_stream):
    """Test market stream reconnection logic."""
    # Mock websockets.connect to fail first, then succeed
    mock_ws = AsyncMock()
    connect_mock = AsyncMock(side_effect=[
        WebSocketException("Connection failed"),
        mock_ws
    ])
    
    with patch('websockets.connect', connect_mock), \
         patch('asyncio.sleep', AsyncMock()):  # Skip actual sleep
        
        # Should succeed on second attempt
        connected = await market_stream.connect()
        assert connected is True
        assert market_stream.connected is True
        assert market_stream.reconnection_attempts == 0  # Reset after success

def test_price_callbacks(market_stream):
    """Test price update callback system."""
    # Create mock callbacks
    callback1 = MagicMock()
    callback2 = MagicMock()
    
    # Register callbacks
    market_stream.register_price_callback(callback1)
    market_stream.register_price_callback(callback2)
    
    # Simulate trade message
    trade_msg = {
        "e": "trade",
        "p": "1.2345",
        "q": "100",
        "T": 1234567890123
    }
    
    # Process message
    asyncio.run(market_stream._handle_trade(trade_msg))
    
    # Verify callbacks were called
    callback1.assert_called_once_with(1.2345)
    callback2.assert_called_once_with(1.2345)
    
    # Verify current price was updated
    assert market_stream.get_current_price() == 1.2345
    
    # Test callback removal
    market_stream.remove_price_callback(callback1)
    asyncio.run(market_stream._handle_trade(trade_msg))
    
    # callback1 should not be called again
    assert callback1.call_count == 1
    # callback2 should be called again
    assert callback2.call_count == 2

@pytest.mark.asyncio
async def test_invalid_message_handling(market_stream):
    """Test handling of invalid trade messages."""
    # Invalid message (missing price)
    invalid_msg = {
        "e": "trade",
        "q": "100",
        "T": 1234567890123
    }
    
    # Should not raise exception but log error
    with patch('src.core.market_stream.logger.error') as mock_logger:
        await market_stream._handle_trade(invalid_msg)
        mock_logger.assert_called_once()
        assert market_stream.get_current_price() is None 