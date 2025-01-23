"""Unit tests for order manager module."""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytest

from src.core.order_manager import OrderManager
from src.db.models import Order, OrderStatus
from src.config.settings import (
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE,
    MAX_SELL_VALUE_USDC
)

@pytest.fixture
def mock_price_manager():
    """Create a mock price manager."""
    manager = Mock()
    manager.get_current_price.return_value = 1.0
    return manager

@pytest.fixture
def order_manager(mock_price_manager):
    """Create an order manager instance for testing."""
    return OrderManager(mock_price_manager)

@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    return session

def test_place_buy_order_success(order_manager, mock_db_session):
    """Test successful buy order placement."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.create_order') as mock_create_order, \
         patch('requests.post') as mock_post:
        
        # Mock API response
        mock_post.return_value.json.return_value = {
            'orderId': '12345',
            'price': '1.0'
        }
        mock_post.return_value.status_code = 200
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_create_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        # Place order
        order_id = order_manager.place_buy_order(100.0, 1.0)
        
        assert order_id == '12345'
        mock_post.assert_called_once()
        mock_create_order.assert_called_once()

def test_place_buy_order_invalid_size(order_manager):
    """Test buy order with invalid size."""
    # Try to place order exceeding max value
    quantity = MAX_SELL_VALUE_USDC + 1
    order_id = order_manager.place_buy_order(quantity, 1.0)
    
    assert order_id is None

def test_place_sell_order_success(order_manager, mock_db_session):
    """Test successful sell order placement."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.create_order') as mock_create_order, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('requests.post') as mock_post:
        
        # Mock API response
        mock_post.return_value.json.return_value = {
            'orderId': '12346',
            'price': '1.01'
        }
        mock_post.return_value.status_code = 200
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED
        )
        mock_create_order.return_value = Order(
            order_id='12346',
            symbol=TRADING_SYMBOL,
            side='SELL',
            quantity=100.0,
            price=1.01,
            status=OrderStatus.NEW,
            related_order_id='12345'
        )
        
        # Place sell order
        order_id = order_manager.place_sell_order('12345', 100.0)
        
        assert order_id == '12346'
        mock_post.assert_called_once()
        mock_create_order.assert_called_once()

def test_handle_order_update(order_manager, mock_db_session):
    """Test order update handling."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('src.core.order_manager.update_order') as mock_update_order:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        # Send update
        update = {
            'order_id': '12345',
            'status': 'FILLED',
            'filled_qty': 100.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        mock_update_order.assert_called_once_with(
            mock_db_session,
            order_id='12345',
            status=OrderStatus.FILLED,
            filled_quantity=100.0,
            average_price=1.0
        )

def test_handle_partial_fill(order_manager, mock_db_session):
    """Test partial fill handling."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('src.core.order_manager.update_order') as mock_update_order, \
         patch.object(order_manager, 'place_sell_order') as mock_place_sell:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        mock_place_sell.return_value = '12346'
        
        # Send partial fill update
        update = {
            'order_id': '12345',
            'status': 'PARTIALLY_FILLED',
            'filled_qty': 50.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        mock_update_order.assert_called_once()
        mock_place_sell.assert_called_once_with('12345', 50.0)

def test_get_position_duration(order_manager, mock_db_session):
    """Test position duration calculation."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        created_at = datetime.utcnow() - timedelta(hours=1)
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED,
            created_at=created_at
        )
        
        duration = order_manager.get_position_duration('12345')
        
        assert 3500 < duration < 3700  # ~1 hour in seconds

def test_get_open_positions(order_manager, mock_db_session):
    """Test retrieving open positions."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_open_orders') as mock_get_orders:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        created_at = datetime.utcnow() - timedelta(hours=1)
        mock_get_orders.return_value = [
            Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED,
                created_at=created_at
            )
        ]
        
        positions = order_manager.get_open_positions()
        
        assert len(positions) == 1
        assert positions[0]['order_id'] == '12345'
        assert positions[0]['symbol'] == TRADING_SYMBOL
        assert positions[0]['quantity'] == 100.0
        assert positions[0]['price'] == 1.0
        assert positions[0]['status'] == OrderStatus.FILLED.value
        assert 3500 < positions[0]['duration_seconds'] < 3700 