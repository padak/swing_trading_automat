"""Unit tests for price manager module."""
import json
from unittest.mock import Mock, patch
import pytest
import websocket

from src.core.price_manager import PriceManager
from src.config.settings import TRADING_SYMBOL

@pytest.fixture
def price_manager():
    """Create a price manager instance for testing."""
    manager = PriceManager(TRADING_SYMBOL)
    yield manager
    manager.stop()

def test_price_callback_registration(price_manager):
    """Test registering and triggering price callbacks."""
    mock_callback = Mock()
    price_manager.register_price_callback("test", mock_callback)
    
    # Simulate trade message
    message = json.dumps({
        "e": "trade",
        "p": "1.2345"
    })
    price_manager._handle_market_message(None, message)
    
    mock_callback.assert_called_once_with(1.2345)

def test_order_callback_registration(price_manager):
    """Test registering and triggering order callbacks."""
    mock_callback = Mock()
    price_manager.register_order_callback("test", mock_callback)
    
    # Simulate execution report
    message = json.dumps({
        "e": "executionReport",
        "i": 12345,  # Order ID
        "X": "FILLED",  # Order status
        "l": "100",  # Last filled quantity
        "L": "1.2345"  # Last filled price
    })
    price_manager._handle_user_message(None, message)
    
    mock_callback.assert_called_once_with({
        'order_id': 12345,
        'status': 'FILLED',
        'filled_qty': 100.0,
        'price': 1.2345
    })

def test_listen_key_management(price_manager):
    """Test listen key lifecycle management."""
    with patch('requests.post') as mock_post, \
         patch('requests.put') as mock_put, \
         patch('requests.delete') as mock_delete:
        
        # Test getting listen key
        mock_post.return_value.json.return_value = {'listenKey': 'test_key'}
        mock_post.return_value.status_code = 200
        
        listen_key = price_manager._get_listen_key()
        assert listen_key == 'test_key'
        
        # Test keeping listen key alive
        price_manager.listen_key = 'test_key'
        mock_put.return_value.status_code = 200
        
        price_manager._keep_listen_key_alive()
        mock_put.assert_called_once()
        
        # Test deleting listen key
        mock_delete.return_value.status_code = 200
        
        price_manager._delete_listen_key()
        mock_delete.assert_called_once()

def test_websocket_reconnection(price_manager):
    """Test WebSocket reconnection logic."""
    # Simulate max reconnection attempts
    price_manager.reconnection_attempts = 0
    for _ in range(5):
        price_manager._handle_reconnection()
    
    assert price_manager.reconnection_attempts == 5

def test_invalid_message_handling(price_manager):
    """Test handling of invalid messages."""
    # Invalid JSON
    price_manager._handle_market_message(None, "invalid json")
    price_manager._handle_user_message(None, "invalid json")
    
    # Valid JSON but missing required fields
    price_manager._handle_market_message(None, "{}")
    price_manager._handle_user_message(None, "{}")
    
    # No assertions needed - just verify no exceptions are raised

def test_rest_api_fallback(price_manager):
    """Test REST API fallback for price retrieval."""
    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {'price': '1.2345'}
        mock_get.return_value.status_code = 200
        
        price = price_manager.get_current_price()
        assert price == 1.2345
        
        # Test error handling
        mock_get.side_effect = Exception("API error")
        price = price_manager.get_current_price()
        assert price is None

def test_account_update_handling(price_manager):
    """Test handling of account update messages."""
    message = json.dumps({
        "e": "outboundAccountPosition",
        "B": [
            {
                "a": "TRUMP",
                "f": "100.0",
                "l": "0.0"
            }
        ]
    })
    # Just verify no exceptions are raised
    price_manager._handle_user_message(None, message)

def test_websocket_lifecycle(price_manager):
    """Test WebSocket connection lifecycle."""
    # Test connection
    price_manager._handle_open(None)
    assert price_manager.connected
    assert price_manager.reconnection_attempts == 0
    
    # Test user connection
    price_manager._handle_user_open(None)
    assert price_manager.user_stream_connected
    assert price_manager.reconnection_attempts == 0
    
    # Test disconnection
    price_manager._handle_close(price_manager.ws, 1000, "Normal closure")
    assert not price_manager.connected
    
    # Test user disconnection
    price_manager._handle_close(price_manager.user_ws, 1000, "Normal closure")
    assert not price_manager.user_stream_connected

def test_error_handling(price_manager):
    """Test WebSocket error handling."""
    error = Exception("Test error")
    price_manager._handle_error(None, error)
    # No assertions needed - just verify no exceptions are raised 