"""Tests for order validation functionality."""
import pytest
from decimal import Decimal

from src.config.settings import (
    MAX_SELL_VALUE_USDC,
    MIN_PROFIT_PERCENTAGE,
    TRADING_SYMBOL
)
from src.core.order_validator import (
    validate_new_order,
    validate_order_update,
    validate_sell_order_placement,
    _is_valid_status_transition
)
from src.db.models import Order, OrderStatus

class TestOrderValidator:
    """Tests for order validation functionality."""
    
    def test_validate_new_order_success(self):
        """Test successful validation of new orders."""
        # Test valid BUY order
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=10.0,
            price=1.0
        )
        assert is_valid
        assert error is None
        
        # Test valid SELL order
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='SELL',
            quantity=10.0,
            price=1.0,
            related_order_id='12345'
        )
        assert is_valid
        assert error is None
    
    def test_validate_new_order_invalid_symbol(self):
        """Test validation with invalid symbol."""
        is_valid, error = validate_new_order(
            symbol='INVALID',
            side='BUY',
            quantity=10.0,
            price=1.0
        )
        assert not is_valid
        assert 'Invalid symbol' in error
    
    def test_validate_new_order_invalid_side(self):
        """Test validation with invalid side."""
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='INVALID',
            quantity=10.0,
            price=1.0
        )
        assert not is_valid
        assert 'Invalid side' in error
    
    def test_validate_new_order_size_limits(self):
        """Test order size validation."""
        # Test at max value
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=MAX_SELL_VALUE_USDC,
            price=1.0
        )
        assert is_valid
        assert error is None
        
        # Test exceeding max value
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=MAX_SELL_VALUE_USDC + 1,
            price=1.0
        )
        assert not is_valid
        assert 'exceeds maximum allowed' in error
    
    def test_validate_new_order_sell_without_related(self):
        """Test SELL order validation without related order ID."""
        is_valid, error = validate_new_order(
            symbol=TRADING_SYMBOL,
            side='SELL',
            quantity=10.0,
            price=1.0
        )
        assert not is_valid
        assert 'must have a related BUY order' in error
    
    def test_validate_order_update_success(self):
        """Test successful order update validation."""
        order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        # Test valid transition to PARTIALLY_FILLED
        is_valid, error = validate_order_update(
            order=order,
            new_status='PARTIALLY_FILLED',
            filled_quantity=50.0,
            average_price=1.0
        )
        assert is_valid
        assert error is None
        
        # Test valid transition to FILLED
        order.status = OrderStatus.PARTIALLY_FILLED
        order.filled_quantity = 50.0
        is_valid, error = validate_order_update(
            order=order,
            new_status='FILLED',
            filled_quantity=100.0,
            average_price=1.0
        )
        assert is_valid
        assert error is None
    
    def test_validate_order_update_invalid_transition(self):
        """Test invalid order status transitions."""
        order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED
        )
        
        # Test invalid transition from FILLED to PARTIALLY_FILLED
        is_valid, error = validate_order_update(
            order=order,
            new_status='PARTIALLY_FILLED',
            filled_quantity=50.0
        )
        assert not is_valid
        assert 'Invalid status transition' in error
    
    def test_validate_order_update_invalid_quantity(self):
        """Test order update with invalid quantities."""
        order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW,
            filled_quantity=0.0
        )
        
        # Test negative fill quantity
        is_valid, error = validate_order_update(
            order=order,
            new_status='PARTIALLY_FILLED',
            filled_quantity=-10.0
        )
        assert not is_valid
        assert 'Fill quantity cannot be negative' in error
        
        # Test fill quantity exceeding order quantity
        is_valid, error = validate_order_update(
            order=order,
            new_status='PARTIALLY_FILLED',
            filled_quantity=150.0
        )
        assert not is_valid
        assert 'exceeds order quantity' in error
        
        # Test decreasing fill quantity
        order.filled_quantity = 50.0
        is_valid, error = validate_order_update(
            order=order,
            new_status='PARTIALLY_FILLED',
            filled_quantity=40.0
        )
        assert not is_valid
        assert 'Fill quantity cannot decrease' in error
    
    def test_validate_sell_order_placement_success(self):
        """Test successful validation of sell order placement."""
        buy_order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED,
            filled_quantity=100.0
        )
        
        # Test placing sell order for full quantity
        is_valid, error = validate_sell_order_placement(
            buy_order=buy_order,
            sell_quantity=100.0,
            current_price=1.1
        )
        assert is_valid
        assert error is None
        
        # Test placing sell order for partial quantity
        is_valid, error = validate_sell_order_placement(
            buy_order=buy_order,
            sell_quantity=50.0,
            current_price=1.1
        )
        assert is_valid
        assert error is None
    
    def test_validate_sell_order_placement_invalid_status(self):
        """Test sell order placement with invalid buy order status."""
        buy_order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        is_valid, error = validate_sell_order_placement(
            buy_order=buy_order,
            sell_quantity=100.0,
            current_price=1.1
        )
        assert not is_valid
        assert 'Cannot place SELL order' in error
    
    def test_validate_sell_order_placement_quantity_check(self):
        """Test sell order quantity validation."""
        buy_order = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=50.0
        )
        
        # Test selling more than filled quantity
        is_valid, error = validate_sell_order_placement(
            buy_order=buy_order,
            sell_quantity=75.0,
            current_price=1.1
        )
        assert not is_valid
        assert 'exceeds filled quantity' in error
        
        # Test with existing sell orders
        existing_sell_orders = {
            '12346': Order(
                order_id='12346',
                symbol=TRADING_SYMBOL,
                side='SELL',
                quantity=30.0,
                price=1.1,
                status=OrderStatus.NEW
            )
        }
        
        # This would exceed total filled quantity (30 + 30 > 50)
        is_valid, error = validate_sell_order_placement(
            buy_order=buy_order,
            sell_quantity=30.0,
            current_price=1.1,
            existing_sell_orders=existing_sell_orders
        )
        assert not is_valid
        assert 'would exceed filled quantity' in error 