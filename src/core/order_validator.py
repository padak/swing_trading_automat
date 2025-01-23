"""
Order validation module for enforcing trading rules and constraints.
Provides comprehensive validation for all order types and operations.
"""
from decimal import Decimal
from typing import Dict, Optional, Tuple, Union

from src.config.logging_config import get_logger
from src.config.settings import (
    MAX_SELL_VALUE_USDC,
    MIN_PROFIT_PERCENTAGE,
    TRADING_SYMBOL
)
from src.db.models import Order, OrderStatus

logger = get_logger(__name__)

def validate_new_order(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    related_order_id: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate a new order before placement.
    
    Args:
        symbol: Trading pair symbol
        side: Order side ('BUY' or 'SELL')
        quantity: Order quantity
        price: Order price
        related_order_id: ID of related order (for SELL orders)
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    # Validate symbol
    if symbol != TRADING_SYMBOL:
        return False, f"Invalid symbol {symbol}, expected {TRADING_SYMBOL}"
    
    # Validate side
    if side not in ['BUY', 'SELL']:
        return False, f"Invalid side {side}, must be 'BUY' or 'SELL'"
    
    # Validate price and quantity
    if price <= 0:
        return False, "Price must be positive"
    if quantity <= 0:
        return False, "Quantity must be positive"
    
    # Validate order size
    order_value = Decimal(str(price)) * Decimal(str(quantity))
    if order_value > Decimal(str(MAX_SELL_VALUE_USDC)):
        error_msg = (
            f"Order value {float(order_value):.2f} USDC "
            f"exceeds maximum allowed {MAX_SELL_VALUE_USDC} USDC"
        )
        logger.warning(
            "Order size validation failed",
            price=price,
            quantity=quantity,
            order_value=float(order_value),
            max_allowed=MAX_SELL_VALUE_USDC
        )
        return False, error_msg
    
    # For SELL orders, related_order_id is required
    if side == 'SELL' and not related_order_id:
        return False, "SELL orders must have a related BUY order"
    
    return True, None

def validate_order_update(
    order: Order,
    new_status: str,
    filled_quantity: Optional[float] = None,
    average_price: Optional[float] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate an order update.
    
    Args:
        order: Existing order to update
        new_status: New order status
        filled_quantity: New filled quantity
        average_price: New average fill price
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    # Validate status transition
    if not _is_valid_status_transition(order.status, new_status):
        return False, f"Invalid status transition from {order.status} to {new_status}"
    
    # Validate fill quantity
    if filled_quantity is not None:
        if filled_quantity < 0:
            return False, "Fill quantity cannot be negative"
        if filled_quantity > order.quantity:
            return False, f"Fill quantity {filled_quantity} exceeds order quantity {order.quantity}"
        if filled_quantity < (order.filled_quantity or 0):
            return False, "Fill quantity cannot decrease"
    
    # Validate average price
    if average_price is not None and average_price <= 0:
        return False, "Average price must be positive"
    
    return True, None

def validate_sell_order_placement(
    buy_order: Order,
    sell_quantity: float,
    current_price: float,
    existing_sell_orders: Optional[Dict[str, Order]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate placement of a SELL order against a BUY order.
    
    Args:
        buy_order: The BUY order to sell against
        sell_quantity: Quantity to sell
        current_price: Current market price
        existing_sell_orders: Map of existing SELL orders for this BUY
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    # Validate BUY order status
    if buy_order.status not in [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED]:
        return False, f"Cannot place SELL order for BUY order in status {buy_order.status}"
    
    # Validate quantities
    filled_quantity = buy_order.filled_quantity or 0
    if sell_quantity > filled_quantity:
        return False, f"Sell quantity {sell_quantity} exceeds filled quantity {filled_quantity}"
    
    # Check existing sell orders
    if existing_sell_orders:
        existing_sell_qty = sum(
            o.quantity for o in existing_sell_orders.values()
            if o.status != OrderStatus.CANCELED
        )
        if existing_sell_qty + sell_quantity > filled_quantity:
            return False, (
                f"Total sell quantity {existing_sell_qty + sell_quantity} "
                f"would exceed filled quantity {filled_quantity}"
            )
    
    # Validate order size
    order_value = Decimal(str(current_price)) * Decimal(str(sell_quantity))
    if order_value > Decimal(str(MAX_SELL_VALUE_USDC)):
        error_msg = (
            f"Sell order value {float(order_value):.2f} USDC "
            f"exceeds maximum allowed {MAX_SELL_VALUE_USDC} USDC"
        )
        logger.warning(
            "Sell order size validation failed",
            price=current_price,
            quantity=sell_quantity,
            order_value=float(order_value),
            max_allowed=MAX_SELL_VALUE_USDC
        )
        return False, error_msg
    
    return True, None

def _is_valid_status_transition(current_status: str, new_status: str) -> bool:
    """Check if a status transition is valid."""
    valid_transitions = {
        OrderStatus.NEW: [
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED
        ],
        OrderStatus.PARTIALLY_FILLED: [
            OrderStatus.PARTIALLY_FILLED,  # Additional partial fills
            OrderStatus.FILLED,
            OrderStatus.CANCELED
        ],
        OrderStatus.FILLED: [],  # No transitions from FILLED
        OrderStatus.CANCELED: [],  # No transitions from CANCELED
        OrderStatus.REJECTED: []  # No transitions from REJECTED
    }
    
    return OrderStatus[new_status] in valid_transitions.get(OrderStatus[current_status], []) 