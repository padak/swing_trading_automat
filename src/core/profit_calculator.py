"""
Profit calculator for determining minimum sell prices and validating orders.
Handles all fee calculations and ensures 0.3% net profit after fees.
"""
from typing import Optional, Tuple

from src.config.logging_config import get_logger
from src.config.settings import (
    MIN_PROFIT_PERCENTAGE,
    MAX_SELL_VALUE_USDC
)

logger = get_logger(__name__)

def calculate_min_sell_price(buy_price: float, quantity: float) -> float:
    """
    Calculate minimum sell price to achieve target profit after fees.
    
    Detailed calculation steps:
    1. Calculate buy cost including fee:
       - Buy cost = quantity * buy_price
       - Buy fee = buy_cost * 0.001 (0.1%)
       - Total buy cost = buy_cost + buy_fee
    
    2. Calculate required profit:
       - Base amount = quantity * buy_price
       - Required profit = base amount * MIN_PROFIT_PERCENTAGE (0.3%)
    
    3. Calculate required sell amount:
       - Required amount = total buy cost + required profit
       - Account for sell fee: final_amount = required_amount / (1 - 0.001)
       - Required sell price = final_amount / quantity
    
    Args:
        buy_price: The price at which the asset was bought
        quantity: The quantity of the asset bought
        
    Returns:
        float: Minimum sell price required for target profit after all fees
    
    Raises:
        ValueError: If inputs are invalid (negative or zero)
    """
    if buy_price <= 0:
        raise ValueError("Buy price must be positive")
    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    
    # Calculate buy cost and fee
    buy_cost = buy_price * quantity
    buy_fee = buy_cost * 0.001  # 0.1% buy fee
    total_buy_cost = buy_cost + buy_fee
    
    # Calculate required profit
    required_profit = buy_cost * (MIN_PROFIT_PERCENTAGE / 100)  # Convert percentage to decimal
    
    # Calculate required sell amount
    required_amount = total_buy_cost + required_profit
    
    # Account for sell fee (0.1%)
    final_sell_price = required_amount / (quantity * (1 - 0.001))
    
    # Validate result
    sell_amount = final_sell_price * quantity * (1 - 0.001)
    if sell_amount < total_buy_cost + required_profit:
        # Adjust for rounding if needed
        final_sell_price *= 1.00001
    
    logger.debug(
        "Calculated minimum sell price",
        buy_price=buy_price,
        quantity=quantity,
        min_sell_price=final_sell_price,
        expected_profit=required_profit
    )
    
    return final_sell_price

def validate_order_size(price: float, quantity: float) -> Tuple[bool, Optional[str]]:
    """
    Validate order size against maximum allowed value.
    
    Args:
        price: Order price in USDC
        quantity: Order quantity
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
        
    Example:
        >>> validate_order_size(1.2345, 80)
        (True, None)
        >>> validate_order_size(1.2345, 100)
        (False, "Order value 123.45 USDC exceeds maximum allowed 100 USDC")
    """
    if price <= 0:
        return False, "Price must be positive"
    if quantity <= 0:
        return False, "Quantity must be positive"
    
    order_value = price * quantity
    if order_value > MAX_SELL_VALUE_USDC:
        error_msg = (
            f"Order value {order_value:.2f} USDC "
            f"exceeds maximum allowed {MAX_SELL_VALUE_USDC} USDC"
        )
        logger.warning(
            "Order size validation failed",
            price=price,
            quantity=quantity,
            order_value=order_value,
            max_allowed=MAX_SELL_VALUE_USDC
        )
        return False, error_msg
    
    return True, None

def calculate_net_profit(
    buy_price: float,
    sell_price: float,
    quantity: float
) -> float:
    """
    Calculate net profit after fees for a completed trade.
    
    Args:
        buy_price: The price at which the asset was bought
        sell_price: The price at which the asset was sold
        quantity: The quantity of the asset traded
        
    Returns:
        float: Net profit in USDC after all fees
        
    Raises:
        ValueError: If inputs are invalid (negative or zero)
    """
    if buy_price <= 0 or sell_price <= 0 or quantity <= 0:
        raise ValueError("All inputs must be positive")
    
    # Calculate buy side
    buy_cost = buy_price * quantity
    buy_fee = buy_cost * 0.001
    total_buy_cost = buy_cost + buy_fee
    
    # Calculate sell side
    sell_amount = sell_price * quantity
    sell_fee = sell_amount * 0.001
    total_sell_amount = sell_amount - sell_fee
    
    # Calculate net profit
    net_profit = total_sell_amount - total_buy_cost
    
    logger.debug(
        "Calculated net profit",
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
        net_profit=net_profit
    )
    
    return net_profit 