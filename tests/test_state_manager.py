"""Unit tests for state manager module."""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytest
import signal

from src.core.state_manager import StateManager
from src.db.models import SystemState, SystemStatus, Order, OrderStatus

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