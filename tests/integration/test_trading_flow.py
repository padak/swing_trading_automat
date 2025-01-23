"""Integration tests for complete trading flow."""
import pytest
from datetime import datetime
from unittest.mock import patch, Mock

from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager
from src.db.models import Order, OrderStatus, SystemStatus
from src.config.settings import TRADING_SYMBOL

class MockWebSocket:
    """Mock WebSocket for testing."""
    def __init__(self):
        self.on_message = None
        self.on_error = None
        self.on_close = None
        self.on_open = None
    
    def run_forever(self):
        """Simulate WebSocket connection."""
        if self.on_open:
            self.on_open(self)

@pytest.fixture
def mock_binance():
    """Mock Binance API responses."""
    with patch('requests.post') as mock_post, \
         patch('requests.get') as mock_get, \
         patch('requests.put') as mock_put, \
         patch('requests.delete') as mock_delete, \
         patch('websocket.WebSocketApp', return_value=MockWebSocket()):
        
        # Mock API responses
        mock_post.return_value.json.return_value = {
            'orderId': '12345',
            'price': '1.0',
            'listenKey': 'test_key'
        }
        mock_post.return_value.status_code = 200
        
        mock_get.return_value.json.return_value = {
            'price': '1.0'
        }
        mock_get.return_value.status_code = 200
        
        mock_put.return_value.status_code = 200
        mock_delete.return_value.status_code = 200
        
        yield {
            'post': mock_post,
            'get': mock_get,
            'put': mock_put,
            'delete': mock_delete
        }

@pytest.fixture
def trading_system(mock_binance):
    """Set up complete trading system."""
    price_manager = PriceManager()
    order_manager = OrderManager(price_manager)
    state_manager = StateManager(price_manager, order_manager)
    
    # Start system
    price_manager.start()
    state_manager.start()
    
    yield {
        'price_manager': price_manager,
        'order_manager': order_manager,
        'state_manager': state_manager
    }
    
    # Cleanup
    state_manager.stop()
    price_manager.stop()

def test_system_startup(trading_system, mock_binance):
    """Test system startup and initialization."""
    state_manager = trading_system['state_manager']
    
    # Verify system state
    summary = state_manager.get_system_summary()
    assert summary['status'] == SystemStatus.READY.value
    assert summary['websocket_status'] == "CONNECTED"
    assert summary['open_orders'] == 0
    assert state_manager.is_healthy()
    
    # Verify API calls
    mock_binance['post'].assert_called()  # Listen key creation
    mock_binance['get'].assert_called()  # Price check

def test_complete_trade_flow(trading_system, mock_binance):
    """Test complete trade flow from buy to sell."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    state_manager = trading_system['state_manager']
    
    # Place buy order
    buy_order_id = order_manager.place_buy_order(100.0, 1.0)
    assert buy_order_id == '12345'
    
    # Simulate order update
    price_manager._handle_user_message(None, {
        'e': 'executionReport',
        'i': buy_order_id,
        'X': 'FILLED',
        'l': '100.0',
        'L': '1.0'
    })
    
    # Verify system state
    summary = state_manager.get_system_summary()
    assert summary['status'] == SystemStatus.TRADING.value
    assert len(summary['positions']) == 1
    
    # Place sell order
    sell_order_id = order_manager.place_sell_order(buy_order_id, 100.0)
    assert sell_order_id is not None
    
    # Simulate sell order update
    price_manager._handle_user_message(None, {
        'e': 'executionReport',
        'i': sell_order_id,
        'X': 'FILLED',
        'l': '100.0',
        'L': '1.01'
    })
    
    # Verify final state
    summary = state_manager.get_system_summary()
    assert summary['status'] == SystemStatus.READY.value
    assert len(summary['positions']) == 0

def test_partial_fill_handling(trading_system, mock_binance):
    """Test handling of partial fills."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    
    # Place buy order
    buy_order_id = order_manager.place_buy_order(100.0, 1.0)
    assert buy_order_id == '12345'
    
    # Simulate partial fill
    price_manager._handle_user_message(None, {
        'e': 'executionReport',
        'i': buy_order_id,
        'X': 'PARTIALLY_FILLED',
        'l': '50.0',
        'L': '1.0'
    })
    
    # Verify sell order was placed for partial amount
    mock_binance['post'].assert_called()
    last_order = mock_binance['post'].call_args_list[-1]
    assert float(last_order[1]['params']['quantity']) == 50.0

def test_system_recovery(trading_system, mock_binance):
    """Test system state recovery."""
    order_manager = trading_system['order_manager']
    state_manager = trading_system['state_manager']
    
    # Place order to create state
    buy_order_id = order_manager.place_buy_order(100.0, 1.0)
    assert buy_order_id == '12345'
    
    # Stop and restart system
    state_manager.stop()
    state_manager.start()
    
    # Verify state was recovered
    summary = state_manager.get_system_summary()
    assert summary['open_orders'] == 1
    assert len(summary['positions']) == 1

def test_error_handling(trading_system, mock_binance):
    """Test system error handling."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    state_manager = trading_system['state_manager']
    
    # Test WebSocket error
    price_manager._handle_error(None, Exception("Test error"))
    assert not state_manager.is_healthy()
    
    # Test invalid order
    mock_binance['post'].side_effect = Exception("API error")
    order_id = order_manager.place_buy_order(100.0, 1.0)
    assert order_id is None
    
    # Verify system remains operational
    assert state_manager.get_system_summary()['status'] == SystemStatus.DEGRADED.value

def test_shutdown_handling(trading_system):
    """Test graceful shutdown handling."""
    state_manager = trading_system['state_manager']
    price_manager = trading_system['price_manager']
    
    # Stop system
    state_manager.stop()
    
    # Verify cleanup
    assert not state_manager.should_run
    assert not price_manager.should_run
    assert not state_manager.monitor_thread.is_alive() 