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

# Performance Tests
@pytest.mark.performance
class TestProfitCalculatorPerformance:
    """Performance tests for profit calculator."""

    def test_min_sell_price_calculation_throughput(self, benchmark):
        """Test throughput of minimum sell price calculations."""
        def calculate_prices():
            """Calculate minimum sell prices for 10000 different scenarios."""
            for price in range(1, 101):  # 100 different prices
                for quantity in range(1, 101):  # 100 different quantities
                    calculate_min_sell_price(float(price), float(quantity))
        
        # Benchmark 10000 calculations
        benchmark(calculate_prices)

    def test_order_validation_throughput(self, benchmark):
        """Test throughput of order size validation."""
        def validate_orders():
            """Validate 10000 different order sizes."""
            for price in range(1, 101):  # 100 different prices
                for quantity in range(1, 101):  # 100 different quantities
                    validate_order_size(float(price), float(quantity))
        
        # Benchmark 10000 validations
        benchmark(validate_orders)

    def test_net_profit_calculation_throughput(self, benchmark):
        """Test throughput of net profit calculations."""
        def calculate_profits():
            """Calculate net profits for 10000 different scenarios."""
            for buy_price in range(1, 101):  # 100 different buy prices
                for sell_price in range(buy_price, buy_price + 100):  # 100 different sell prices per buy price
                    calculate_net_profit(float(buy_price), float(sell_price), 100.0)
        
        # Benchmark 10000 calculations
        benchmark(calculate_profits)

    def test_calculation_precision(self):
        """Test precision of profit calculations under high load."""
        # Test precision with many decimal places
        buy_price = 1.23456789
        quantity = 98.76543210
        expected_results = []
        actual_results = []
        
        # Calculate 1000 times and verify consistency
        for _ in range(1000):
            min_sell = calculate_min_sell_price(buy_price, quantity)
            actual_results.append(min_sell)
            
            # Calculate expected result (same as in basic test)
            buy_cost = buy_price * quantity
            buy_fee = buy_cost * 0.001
            total_buy_cost = buy_cost + buy_fee
            required_profit = buy_cost * (MIN_PROFIT_PERCENTAGE / 100)
            required_amount = total_buy_cost + required_profit
            expected_min_sell = required_amount / (quantity * (1 - 0.001))
            expected_results.append(expected_min_sell)
        
        # Verify all results are identical to 8 decimal places
        for actual, expected in zip(actual_results, expected_results):
            assert abs(actual - expected) < 1e-8, \
                f"Precision loss detected: expected {expected}, got {actual}"

    def test_concurrent_calculations(self):
        """Test performance with concurrent profit calculations."""
        import threading
        import time
        
        calculations_completed = 0
        errors_detected = 0
        lock = threading.Lock()
        
        def calculate_batch():
            """Calculate profits for a batch of scenarios."""
            nonlocal calculations_completed, errors_detected
            try:
                for _ in range(250):  # 250 calculations per thread
                    min_sell = calculate_min_sell_price(1.0, 100.0)
                    net_profit = calculate_net_profit(1.0, min_sell, 100.0)
                    # Verify profit meets minimum requirement
                    if net_profit < (100.0 * MIN_PROFIT_PERCENTAGE / 100):
                        with lock:
                            errors_detected += 1
                    with lock:
                        calculations_completed += 1
                    time.sleep(0.001)  # Simulate realistic calculation timing
            except Exception:
                with lock:
                    errors_detected += 1
        
        # Start concurrent calculations with 4 threads
        threads = [threading.Thread(target=calculate_batch) for _ in range(4)]
        
        start_time = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        end_time = time.perf_counter()
        
        total_time = end_time - start_time
        
        # Verify all calculations completed successfully
        assert calculations_completed == 1000, \
            f"Only completed {calculations_completed}/1000 calculations"
        assert errors_detected == 0, \
            f"Detected {errors_detected} calculation errors"
        
        # Assert reasonable processing time (adjust based on requirements)
        assert total_time < 2.0, \
            f"Concurrent calculations took {total_time}s, exceeding 2s threshold" 