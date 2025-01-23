"""Unit tests for price manager module."""
import json
from unittest.mock import Mock, patch, MagicMock
import pytest
import websocket
import time
from datetime import datetime, timedelta
import threading

from src.core.price_manager import PriceManager
from src.config.settings import (
    TRADING_SYMBOL,
    WEBSOCKET_RECONNECT_TIMEOUT,
    WEBSOCKET_INITIAL_RETRY_DELAY,
    REST_API_REFRESH_RATE
)
from src.db.models import SystemStatus

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

def test_listen_key_keep_alive_loop(price_manager):
    """Test the automatic listen key keep-alive loop."""
    with patch('time.sleep'), \
         patch.object(price_manager, '_keep_listen_key_alive') as mock_keep_alive:
        
        price_manager.listen_key = 'test_key'
        price_manager.should_run = True
        
        # Start keep-alive thread
        thread = threading.Thread(target=price_manager._keep_listen_key_alive_loop)
        thread.daemon = True
        thread.start()
        
        # Let it run for a bit
        time.sleep(0.1)
        price_manager.should_run = False
        thread.join(timeout=1.0)
        
        # Verify keep-alive was called
        assert mock_keep_alive.called
        assert price_manager.listen_key_last_update is not None

def test_execution_report_validation(price_manager):
    """Test validation of execution report fields."""
    # Missing required fields
    invalid_report = {
        'e': 'executionReport',
        'i': '12345'  # Missing other required fields
    }
    price_manager._handle_execution_report(invalid_report)
    
    # Invalid quantities
    invalid_quantities = {
        'e': 'executionReport',
        'i': '12345',
        'X': 'FILLED',
        'q': '100.0',  # Original quantity
        'z': '150.0',  # Filled > Original (invalid)
        'p': '1.2345',
        'l': '50.0',
        'L': '1.2345'
    }
    price_manager._handle_execution_report(invalid_quantities)
    
    # Invalid status
    invalid_status = {
        'e': 'executionReport',
        'i': '12345',
        'X': 'INVALID_STATUS',
        'q': '100.0',
        'z': '50.0',
        'p': '1.2345',
        'l': '50.0',
        'L': '1.2345'
    }
    price_manager._handle_execution_report(invalid_status)
    
    # Valid report with commission
    mock_callback = Mock()
    price_manager.register_order_callback('test', mock_callback)
    
    valid_report = {
        'e': 'executionReport',
        'i': '12345',
        'X': 'FILLED',
        'q': '100.0',
        'z': '100.0',
        'p': '1.2345',
        'l': '50.0',
        'L': '1.2345',
        'n': '0.1',    # Commission amount
        'N': 'TRUMP'   # Commission asset
    }
    price_manager._handle_execution_report(valid_report)
    
    # Verify callback was called with correct data
    mock_callback.assert_called_once()
    call_args = mock_callback.call_args[0][0]
    assert call_args['order_id'] == '12345'
    assert call_args['status'] == 'FILLED'
    assert call_args['commission'] == 0.1
    assert call_args['commission_asset'] == 'TRUMP'

def test_account_update_validation(price_manager):
    """Test validation of account update messages."""
    # Missing balances
    invalid_update = {
        'e': 'outboundAccountPosition'
        # Missing 'B' field
    }
    price_manager._handle_account_update(invalid_update)
    
    # Invalid balance data
    invalid_balance = {
        'e': 'outboundAccountPosition',
        'B': [
            {
                'a': 'TRUMP'
                # Missing 'f' and 'l' fields
            }
        ]
    }
    price_manager._handle_account_update(invalid_balance)
    
    # Valid balance update
    valid_update = {
        'e': 'outboundAccountPosition',
        'E': 1234567890000,
        'B': [
            {
                'a': 'TRUMP',
                'f': '100.0',
                'l': '50.0'
            },
            {
                'a': 'USDC',
                'f': '1000.0',
                'l': '0.0'
            }
        ]
    }
    price_manager._handle_account_update(valid_update)
    # No assertion needed - just verify no exceptions are raised

@pytest.mark.performance
def test_user_message_processing_performance(price_manager):
    """Test performance of user message processing."""
    mock_callback = Mock()
    price_manager.register_order_callback('test', mock_callback)
    
    # Create a batch of valid messages
    messages = []
    for i in range(1000):
        messages.append(json.dumps({
            'e': 'executionReport',
            'i': str(i),
            'X': 'FILLED',
            'q': '100.0',
            'z': '100.0',
            'p': '1.2345',
            'l': '100.0',
            'L': '1.2345',
            'n': '0.1',
            'N': 'TRUMP'
        }))
    
    start_time = time.perf_counter()
    
    # Process all messages
    for message in messages:
        price_manager._handle_user_message(None, message)
    
    end_time = time.perf_counter()
    processing_time = (end_time - start_time) * 1000  # Convert to milliseconds
    
    # Verify performance
    assert processing_time < 1000.0, f"Processing time {processing_time}ms exceeds 1000ms threshold"
    assert mock_callback.call_count == 1000

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

class TestPriceManagerErrorHandling:
    """Test WebSocket error handling in PriceManager."""
    
    @pytest.fixture
    def price_manager(self):
        """Create PriceManager instance for testing."""
        manager = PriceManager()
        yield manager
        manager.stop()
    
    def test_market_websocket_reconnection(self, price_manager):
        """Test market WebSocket reconnection with exponential backoff."""
        # Mock WebSocket
        mock_ws = MagicMock()
        price_manager.ws = mock_ws
        
        # Simulate connection error
        price_manager._handle_market_error(mock_ws, Exception("Test error"))
        
        # Verify state
        assert not price_manager.connected
        assert price_manager.reconnection_attempts == 0
        
        # Simulate reconnection attempt
        should_continue = price_manager._handle_reconnection()
        
        # Verify exponential backoff
        assert should_continue
        assert price_manager.reconnection_attempts == 1
        assert price_manager.using_rest_fallback
        
    def test_websocket_timeout_shutdown(self, price_manager):
        """Test WebSocket timeout shutdown after 15 minutes."""
        # Mock WebSocket and time
        mock_ws = MagicMock()
        price_manager.ws = mock_ws
        price_manager.reconnection_start_time = time.time() - WEBSOCKET_RECONNECT_TIMEOUT - 1
        
        # Simulate reconnection attempt
        with pytest.raises(SystemExit):
            price_manager._handle_reconnection()
        
        # Verify shutdown state
        assert not price_manager.should_run
        assert not price_manager.connected
        
    def test_rest_api_fallback(self, price_manager):
        """Test REST API fallback during WebSocket disconnection."""
        # Mock REST API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'price': '100.0'}
        
        with patch('requests.get', return_value=mock_response):
            # Start fallback
            price_manager._start_rest_fallback()
            assert price_manager.using_rest_fallback
            
            # Wait for fallback update
            time.sleep(REST_API_REFRESH_RATE * 2)
            
            # Stop fallback
            price_manager._stop_rest_fallback()
            assert not price_manager.using_rest_fallback
            
    def test_user_stream_error_handling(self, price_manager):
        """Test user data stream error handling."""
        # Mock WebSocket
        mock_ws = MagicMock()
        price_manager.user_ws = mock_ws
        
        # Simulate error
        price_manager._handle_user_error(mock_ws, Exception("Test error"))
        assert not price_manager.user_stream_connected
        
        # Simulate reconnection
        price_manager._handle_user_open(mock_ws)
        assert price_manager.user_stream_connected
        assert price_manager.reconnection_attempts == 0
        
    def test_invalid_message_handling(self, price_manager):
        """Test handling of invalid WebSocket messages."""
        # Mock WebSocket
        mock_ws = MagicMock()
        
        # Test invalid JSON
        price_manager._handle_market_message(mock_ws, "invalid json")
        assert price_manager.current_price is None
        
        # Test invalid message format
        price_manager._handle_market_message(mock_ws, json.dumps({}))
        assert price_manager.current_price is None
        
        # Test valid price update
        price_manager._handle_market_message(mock_ws, json.dumps({'p': '100.0'}))
        assert price_manager.current_price == 100.0
        
    def test_connection_monitoring(self, price_manager):
        """Test WebSocket connection monitoring."""
        # Mock WebSocket
        mock_ws = MagicMock()
        price_manager.ws = mock_ws
        price_manager.connected = True
        
        # Set old message time
        price_manager.last_message_time = time.time() - WEBSOCKET_RECONNECT_TIMEOUT - 1
        
        # Run monitor once
        price_manager._monitor_connection()
        
        # Verify connection was closed
        mock_ws.close.assert_called_once()
        
    def test_graceful_shutdown(self, price_manager):
        """Test graceful shutdown process."""
        # Mock WebSocket connections
        mock_market_ws = MagicMock()
        mock_user_ws = MagicMock()
        price_manager.ws = mock_market_ws
        price_manager.user_ws = mock_user_ws
        price_manager.listen_key = "test_key"
        
        # Stop price manager
        price_manager.stop()
        
        # Verify cleanup
        assert not price_manager.should_run
        mock_market_ws.close.assert_called_once()
        mock_user_ws.close.assert_called_once()
        assert not price_manager.connected
        assert not price_manager.user_stream_connected 