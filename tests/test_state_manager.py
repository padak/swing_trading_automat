"""Unit tests for state manager module."""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytest
import signal
import json

from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager
from src.db.models import SystemState, SystemStatus, Order, OrderStatus
from src.config.settings import TRADING_SYMBOL

@pytest.fixture
def mock_price_manager():
    """Create a mock price manager."""
    manager = Mock()
    manager.connected = True
    manager.last_message_time = datetime.utcnow()
    return manager

@pytest.fixture
def mock_order_manager():
    """Create a mock order manager."""
    manager = Mock()
    manager.get_open_positions.return_value = []
    return manager

@pytest.fixture
def state_manager(mock_price_manager, mock_order_manager):
    """Create a state manager instance for testing."""
    manager = StateManager(mock_price_manager, mock_order_manager)
    yield manager
    manager.stop()

@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    return session

def test_state_recovery(state_manager, mock_db_session):
    """Test system state recovery."""
    with patch('src.core.state_manager.get_db') as mock_get_db, \
         patch('src.core.state_manager.get_system_state') as mock_get_state, \
         patch('src.core.state_manager.get_open_orders') as mock_get_orders, \
         patch('src.core.state_manager.update_system_state') as mock_update_state:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_state.return_value = SystemState(
            status=SystemStatus.TRADING,
            websocket_status="CONNECTED",
            last_state_check=datetime.utcnow()
        )
        mock_get_orders.return_value = [
            Order(
                order_id='12345',
                symbol='TRUMPUSDC',
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
        ]
        
        # Test recovery
        state_manager._recover_state()
        
        mock_update_state.assert_called_once()
        assert mock_update_state.call_args[1]['status'] == SystemStatus.STARTING

def test_state_monitoring(state_manager, mock_db_session):
    """Test state monitoring thread."""
    with patch('src.core.state_manager.get_db') as mock_get_db, \
         patch('src.core.state_manager.update_system_state') as mock_update_state, \
         patch('src.core.state_manager.get_open_orders') as mock_get_orders:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_orders.return_value = []
        
        # Run one monitoring cycle
        state_manager._monitor_state()
        
        mock_update_state.assert_called_once()
        assert mock_update_state.call_args[1]['status'] == SystemStatus.READY

def test_shutdown_handling(state_manager, mock_db_session):
    """Test graceful shutdown handling."""
    with patch('src.core.state_manager.get_db') as mock_get_db, \
         patch('src.core.state_manager.update_system_state') as mock_update_state:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        
        # Test shutdown
        state_manager._handle_shutdown(signal.SIGTERM, None)
        
        mock_update_state.assert_called_once()
        assert mock_update_state.call_args[1]['status'] == SystemStatus.STOPPED

def test_system_summary(state_manager, mock_db_session):
    """Test system summary generation."""
    with patch('src.core.state_manager.get_db') as mock_get_db, \
         patch('src.core.state_manager.get_open_orders') as mock_get_orders:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_orders.return_value = []
        
        # Mock order manager
        state_manager.order_manager.get_open_positions.return_value = [
            {
                'order_id': '12345',
                'symbol': 'TRUMPUSDC',
                'quantity': 100.0,
                'price': 1.0,
                'status': OrderStatus.FILLED.value,
                'duration_seconds': 3600
            }
        ]
        
        # Get summary
        summary = state_manager.get_system_summary()
        
        assert summary['status'] == SystemStatus.READY.value
        assert summary['websocket_status'] == "CONNECTED"
        assert len(summary['positions']) == 1
        assert summary['position_durations']['12345'] == 3600

def test_health_check(state_manager):
    """Test system health check."""
    # Test healthy state
    assert state_manager.is_healthy()
    
    # Test unhealthy states
    state_manager.price_manager.connected = False
    assert not state_manager.is_healthy()
    
    state_manager.price_manager.connected = True
    state_manager.price_manager.last_message_time = datetime.utcnow() - timedelta(minutes=2)
    assert not state_manager.is_healthy()

def test_state_transitions(state_manager, mock_db_session):
    """Test system state transitions."""
    with patch('src.core.state_manager.get_db') as mock_get_db, \
         patch('src.core.state_manager.get_open_orders') as mock_get_orders:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        
        # Test transition to TRADING
        mock_get_orders.return_value = [
            Order(
                order_id='12345',
                symbol='TRUMPUSDC',
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
        ]
        state = state_manager._get_current_state()
        assert state['status'] == SystemStatus.TRADING
        
        # Test transition to DEGRADED
        state_manager.price_manager.connected = False
        state = state_manager._get_current_state()
        assert state['status'] == SystemStatus.DEGRADED
        
        # Test transition to READY
        state_manager.price_manager.connected = True
        mock_get_orders.return_value = []
        state = state_manager._get_current_state()
        assert state['status'] == SystemStatus.READY 

# Integration Tests

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

def test_integration_system_startup(trading_system, mock_binance):
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

def test_integration_complete_trade_flow(trading_system, mock_binance):
    """Test complete trade flow from buy to sell."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    state_manager = trading_system['state_manager']
    
    # Place buy order
    buy_order_id = order_manager.place_buy_order(100.0, 1.0)
    assert buy_order_id == '12345'
    
    # Simulate order update
    price_manager._handle_user_message(None, json.dumps({
        'e': 'executionReport',
        'i': buy_order_id,
        'X': 'FILLED',
        'l': '100.0',
        'L': '1.0'
    }))
    
    # Verify system state
    summary = state_manager.get_system_summary()
    assert summary['status'] == SystemStatus.TRADING.value
    assert len(summary['positions']) == 1
    
    # Place sell order
    sell_order_id = order_manager.place_sell_order(buy_order_id, 100.0)
    assert sell_order_id is not None
    
    # Simulate sell order update
    price_manager._handle_user_message(None, json.dumps({
        'e': 'executionReport',
        'i': sell_order_id,
        'X': 'FILLED',
        'l': '100.0',
        'L': '1.01'
    }))
    
    # Verify final state
    summary = state_manager.get_system_summary()
    assert summary['status'] == SystemStatus.READY.value
    assert len(summary['positions']) == 0

def test_integration_partial_fill(trading_system, mock_binance):
    """Test handling of partial fills."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    
    # Place buy order
    buy_order_id = order_manager.place_buy_order(100.0, 1.0)
    assert buy_order_id == '12345'
    
    # Simulate partial fill
    price_manager._handle_user_message(None, json.dumps({
        'e': 'executionReport',
        'i': buy_order_id,
        'X': 'PARTIALLY_FILLED',
        'l': '50.0',
        'L': '1.0'
    }))
    
    # Verify sell order was placed for partial amount
    mock_binance['post'].assert_called()
    last_order = mock_binance['post'].call_args_list[-1]
    assert float(last_order[1]['params']['quantity']) == 50.0

def test_integration_system_recovery(trading_system, mock_binance):
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

def test_integration_error_handling(trading_system, mock_binance):
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

# Performance Tests
@pytest.mark.performance
class TestStateManagerPerformance:
    """Performance tests for state manager."""
    
    @pytest.fixture
    def state_manager_perf(self, mock_price_manager, mock_order_manager):
        """Create a state manager instance for performance testing."""
        manager = StateManager(mock_price_manager, mock_order_manager)
        yield manager
        manager.stop()

    def test_state_monitoring_throughput(self, state_manager_perf, mock_db_session, benchmark):
        """Test throughput of state monitoring operations."""
        with patch('src.core.state_manager.get_db') as mock_get_db, \
             patch('src.core.state_manager.update_system_state') as mock_update_state, \
             patch('src.core.state_manager.get_open_orders') as mock_get_orders:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_orders.return_value = []
            
            def monitor_states():
                """Monitor system state 1000 times."""
                for _ in range(1000):
                    state_manager_perf._monitor_state()
            
            # Benchmark 1000 state monitoring cycles
            benchmark(monitor_states)
            assert mock_update_state.call_count == 1000

    def test_state_recovery_performance(self, state_manager_perf, mock_db_session):
        """Test performance of state recovery with large order history."""
        with patch('src.core.state_manager.get_db') as mock_get_db, \
             patch('src.core.state_manager.get_system_state') as mock_get_state, \
             patch('src.core.state_manager.get_open_orders') as mock_get_orders, \
             patch('src.core.state_manager.update_system_state') as mock_update_state:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_state.return_value = SystemState(
                status=SystemStatus.TRADING,
                websocket_status="CONNECTED",
                last_state_check=datetime.utcnow()
            )
            
            # Create 1000 test orders
            mock_orders = [
                Order(
                    order_id=str(i),
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=100.0,
                    price=1.0,
                    status=OrderStatus.FILLED
                ) for i in range(1000)
            ]
            mock_get_orders.return_value = mock_orders
            
            # Measure recovery time
            start_time = datetime.utcnow()
            state_manager_perf._recover_state()
            end_time = datetime.utcnow()
            
            recovery_time = (end_time - start_time).total_seconds()
            
            # Assert reasonable recovery time (adjust based on requirements)
            assert recovery_time < 1.0, f"State recovery took {recovery_time}s, exceeding 1s threshold"

    def test_system_summary_performance(self, state_manager_perf, mock_db_session, benchmark):
        """Test performance of system summary generation with large dataset."""
        with patch('src.core.state_manager.get_db') as mock_get_db, \
             patch('src.core.state_manager.get_open_orders') as mock_get_orders:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Create 1000 test positions
            positions = [
                {
                    'order_id': str(i),
                    'symbol': TRADING_SYMBOL,
                    'quantity': 100.0,
                    'price': 1.0,
                    'status': OrderStatus.FILLED.value,
                    'duration_seconds': i * 100
                } for i in range(1000)
            ]
            state_manager_perf.order_manager.get_open_positions.return_value = positions
            mock_get_orders.return_value = []
            
            def generate_summaries():
                """Generate system summary 100 times."""
                for _ in range(100):
                    state_manager_perf.get_system_summary()
            
            # Benchmark 100 summary generations
            benchmark(generate_summaries)

    def test_concurrent_state_updates(self, state_manager_perf, mock_db_session):
        """Test performance with concurrent state updates."""
        import threading
        import time
        
        updates_completed = 0
        errors_detected = 0
        lock = threading.Lock()
        
        with patch('src.core.state_manager.get_db') as mock_get_db, \
             patch('src.core.state_manager.update_system_state') as mock_update_state, \
             patch('src.core.state_manager.get_open_orders') as mock_get_orders:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_orders.return_value = []
            
            def update_state():
                """Update system state in a loop."""
                nonlocal updates_completed, errors_detected
                try:
                    for _ in range(250):  # 250 updates per thread
                        state_manager_perf._monitor_state()
                        with lock:
                            updates_completed += 1
                        time.sleep(0.001)  # Simulate realistic update timing
                except Exception:
                    with lock:
                        errors_detected += 1
            
            # Start concurrent updates with 4 threads
            threads = [threading.Thread(target=update_state) for _ in range(4)]
            
            start_time = time.perf_counter()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            end_time = time.perf_counter()
            
            total_time = end_time - start_time
            
            # Verify all updates completed successfully
            assert updates_completed == 1000, \
                f"Only completed {updates_completed}/1000 updates"
            assert errors_detected == 0, \
                f"Detected {errors_detected} update errors"
            
            # Assert reasonable processing time (adjust based on requirements)
            assert total_time < 2.0, \
                f"Concurrent updates took {total_time}s, exceeding 2s threshold"

    def test_health_check_performance(self, state_manager_perf, benchmark):
        """Test performance of health check operations."""
        def check_health():
            """Perform 10000 health checks."""
            for _ in range(10000):
                state_manager_perf.is_healthy()
        
        # Benchmark 10000 health checks
        benchmark(check_health) 