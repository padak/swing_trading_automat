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

# Performance Tests
@pytest.mark.performance
class TestPriceManagerPerformance:
    """Performance tests for PriceManager."""
    
    @pytest.fixture
    def price_manager_perf(self):
        """Create a price manager instance for performance testing."""
        manager = PriceManager(TRADING_SYMBOL)
        yield manager
        manager.stop()

    def test_websocket_message_throughput(self, price_manager_perf, benchmark):
        """Test WebSocket message processing throughput."""
        mock_callback = Mock()
        price_manager_perf.register_price_callback("test", mock_callback)
        
        def process_messages():
            """Process 1000 price update messages."""
            message = json.dumps({
                "e": "trade",
                "p": "1.2345"
            })
            for _ in range(1000):
                price_manager_perf._handle_market_message(None, message)
        
        # Benchmark processing 1000 messages
        benchmark(process_messages)
        assert mock_callback.call_count == 1000

    def test_price_update_latency(self, price_manager_perf):
        """Test latency of price update processing."""
        import time
        latencies = []
        mock_callback = Mock()
        price_manager_perf.register_price_callback("test", mock_callback)
        
        message = json.dumps({
            "e": "trade",
            "p": "1.2345"
        })
        
        # Measure latency for 100 price updates
        for _ in range(100):
            start_time = time.perf_counter()
            price_manager_perf._handle_market_message(None, message)
            end_time = time.perf_counter()
            latencies.append((end_time - start_time) * 1000)  # Convert to milliseconds
        
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        
        # Assert reasonable latency bounds (adjust based on requirements)
        assert avg_latency < 1.0, f"Average latency {avg_latency}ms exceeds 1ms threshold"
        assert max_latency < 5.0, f"Maximum latency {max_latency}ms exceeds 5ms threshold"

    def test_concurrent_stream_performance(self, price_manager_perf):
        """Test performance with concurrent market and user data streams."""
        import threading
        import time
        
        market_processed = 0
        user_processed = 0
        lock = threading.Lock()
        
        def market_callback(price):
            nonlocal market_processed
            with lock:
                market_processed += 1
        
        def user_callback(data):
            nonlocal user_processed
            with lock:
                user_processed += 1
        
        price_manager_perf.register_price_callback("test_market", market_callback)
        price_manager_perf.register_order_callback("test_user", user_callback)
        
        market_message = json.dumps({
            "e": "trade",
            "p": "1.2345"
        })
        
        user_message = json.dumps({
            "e": "executionReport",
            "i": 12345,
            "X": "FILLED",
            "l": "100",
            "L": "1.2345"
        })
        
        def process_market():
            for _ in range(500):
                price_manager_perf._handle_market_message(None, market_message)
                time.sleep(0.001)  # Simulate realistic message arrival
        
        def process_user():
            for _ in range(500):
                price_manager_perf._handle_user_message(None, user_message)
                time.sleep(0.001)  # Simulate realistic message arrival
        
        # Start concurrent processing
        market_thread = threading.Thread(target=process_market)
        user_thread = threading.Thread(target=process_user)
        
        start_time = time.perf_counter()
        market_thread.start()
        user_thread.start()
        market_thread.join()
        user_thread.join()
        end_time = time.perf_counter()
        
        total_time = end_time - start_time
        
        # Verify all messages were processed
        assert market_processed == 500, f"Only processed {market_processed}/500 market messages"
        assert user_processed == 500, f"Only processed {user_processed}/500 user messages"
        
        # Assert reasonable processing time (adjust based on requirements)
        assert total_time < 2.0, f"Concurrent processing took {total_time}s, exceeding 2s threshold"

    def test_reconnection_performance(self, price_manager_perf):
        """Test performance of WebSocket reconnection."""
        import time
        
        reconnection_times = []
        
        for _ in range(5):
            start_time = time.perf_counter()
            price_manager_perf._handle_reconnection()
            end_time = time.perf_counter()
            reconnection_times.append(end_time - start_time)
            
            # Reset for next attempt
            price_manager_perf.reconnection_attempts = 0
        
        avg_reconnect_time = sum(reconnection_times) / len(reconnection_times)
        max_reconnect_time = max(reconnection_times)
        
        # Assert reasonable reconnection times (adjust based on requirements)
        assert avg_reconnect_time < 0.1, f"Average reconnection time {avg_reconnect_time}s exceeds 100ms threshold"
        assert max_reconnect_time < 0.5, f"Maximum reconnection time {max_reconnect_time}s exceeds 500ms threshold" 