"""Unit tests for profit calculator module."""
import pytest

from src.core.profit_calculator import (
    calculate_min_sell_price,
    validate_order_size,
    calculate_net_profit
)
from src.config.settings import (
    MIN_PROFIT_PERCENTAGE,
    MAX_SELL_VALUE_USDC
)

def test_calculate_min_sell_price_basic():
    """Test basic minimum sell price calculation."""
    buy_price = 1.0
    quantity = 100.0
    min_sell = calculate_min_sell_price(buy_price, quantity)
    
    # Calculate expected minimum sell price
    buy_cost = buy_price * quantity
    buy_fee = buy_cost * 0.001
    total_buy_cost = buy_cost + buy_fee
    required_profit = buy_cost * (MIN_PROFIT_PERCENTAGE / 100)
    required_amount = total_buy_cost + required_profit
    expected_min_sell = required_amount / (quantity * (1 - 0.001))
    
    assert abs(min_sell - expected_min_sell) < 0.00001, \
        f"Expected {expected_min_sell}, got {min_sell}"

def test_calculate_min_sell_price_invalid_inputs():
    """Test error handling for invalid inputs."""
    with pytest.raises(ValueError, match="Buy price must be positive"):
        calculate_min_sell_price(0, 100)
    
    with pytest.raises(ValueError, match="Buy price must be positive"):
        calculate_min_sell_price(-1, 100)
    
    with pytest.raises(ValueError, match="Quantity must be positive"):
        calculate_min_sell_price(1, 0)
    
    with pytest.raises(ValueError, match="Quantity must be positive"):
        calculate_min_sell_price(1, -1)

def test_validate_order_size_within_limit():
    """Test order size validation within limits."""
    # Test at exactly max value
    price = 1.0
    quantity = MAX_SELL_VALUE_USDC
    is_valid, error = validate_order_size(price, quantity)
    assert is_valid
    assert error is None
    
    # Test below max value
    quantity = MAX_SELL_VALUE_USDC - 1
    is_valid, error = validate_order_size(price, quantity)
    assert is_valid
    assert error is None

def test_validate_order_size_exceeds_limit():
    """Test order size validation when exceeding limits."""
    price = 1.0
    quantity = MAX_SELL_VALUE_USDC + 1
    is_valid, error = validate_order_size(price, quantity)
    assert not is_valid
    assert "exceeds maximum allowed" in error

def test_validate_order_size_invalid_inputs():
    """Test order size validation with invalid inputs."""
    is_valid, error = validate_order_size(0, 100)
    assert not is_valid
    assert "Price must be positive" == error
    
    is_valid, error = validate_order_size(-1, 100)
    assert not is_valid
    assert "Price must be positive" == error
    
    is_valid, error = validate_order_size(1, 0)
    assert not is_valid
    assert "Quantity must be positive" == error
    
    is_valid, error = validate_order_size(1, -1)
    assert not is_valid
    assert "Quantity must be positive" == error

def test_calculate_net_profit_basic():
    """Test basic net profit calculation."""
    buy_price = 1.0
    sell_price = 1.01
    quantity = 100.0
    
    net_profit = calculate_net_profit(buy_price, sell_price, quantity)
    
    # Calculate expected profit
    buy_cost = buy_price * quantity
    buy_fee = buy_cost * 0.001
    total_buy_cost = buy_cost + buy_fee
    
    sell_amount = sell_price * quantity
    sell_fee = sell_amount * 0.001
    total_sell_amount = sell_amount - sell_fee
    
    expected_profit = total_sell_amount - total_buy_cost
    
    assert abs(net_profit - expected_profit) < 0.00001, \
        f"Expected {expected_profit}, got {net_profit}"

def test_calculate_net_profit_loss():
    """Test net profit calculation for a losing trade."""
    buy_price = 1.0
    sell_price = 0.99  # Selling at a loss
    quantity = 100.0
    
    net_profit = calculate_net_profit(buy_price, sell_price, quantity)
    assert net_profit < 0, "Expected negative profit for losing trade"

def test_calculate_net_profit_invalid_inputs():
    """Test error handling for invalid inputs in net profit calculation."""
    with pytest.raises(ValueError, match="All inputs must be positive"):
        calculate_net_profit(0, 1, 100)
    
    with pytest.raises(ValueError, match="All inputs must be positive"):
        calculate_net_profit(1, 0, 100)
    
    with pytest.raises(ValueError, match="All inputs must be positive"):
        calculate_net_profit(1, 1, 0)
    
    with pytest.raises(ValueError, match="All inputs must be positive"):
        calculate_net_profit(-1, 1, 100) 