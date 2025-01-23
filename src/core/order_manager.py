"""
Order manager for handling buy/sell operations and tracking positions.
Handles order monitoring, placement, and partial fill tracking.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import time
import hmac
import hashlib
import requests

from src.config.logging_config import get_logger
from src.config.settings import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_API_URL,
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE
)
from src.core.profit_calculator import (
    calculate_min_sell_price,
    validate_order_size
)
from src.db.operations import (
    get_db,
    create_order,
    update_order,
    get_open_orders,
    get_order_by_id
)
from src.db.models import Order, OrderStatus

logger = get_logger(__name__)

class OrderManager:
    """
    Manages order operations including monitoring, placement, and tracking.
    Handles both market and limit orders with partial fill support.
    """
    
    def __init__(self, price_manager):
        """
        Initialize order manager.
        
        Args:
            price_manager: Instance of PriceManager for price updates and order status
        """
        self.price_manager = price_manager
        
        # Register for order updates
        self.price_manager.register_order_callback(
            "order_manager",
            self._handle_order_update
        )
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Generate signature for API request.
        
        Args:
            params: Request parameters to sign
            
        Returns:
            str: HMAC SHA256 signature
        """
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            BINANCE_API_SECRET.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _place_order(
        self,
        side: str,
        quantity: float,
        price: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Place an order on Binance.
        
        Args:
            side: 'BUY' or 'SELL'
            quantity: Order quantity
            price: Optional limit price (None for market orders)
            
        Returns:
            Optional[Dict[str, Any]]: Order response or None if failed
        """
        try:
            endpoint = f"{BINANCE_API_URL}/v3/order"
            params = {
                'symbol': TRADING_SYMBOL,
                'side': side,
                'type': 'LIMIT' if price else 'MARKET',
                'quantity': f"{quantity:.8f}",
                'timestamp': int(time.time() * 1000)
            }
            
            if price:
                params['price'] = f"{price:.8f}"
                params['timeInForce'] = 'GTC'
            
            # Add signature
            params['signature'] = self._generate_signature(params)
            
            # Place order
            headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
            response = requests.post(endpoint, headers=headers, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(
                "Failed to place order",
                side=side,
                quantity=quantity,
                price=price,
                error=str(e)
            )
            return None
    
    def place_buy_order(self, quantity: float, price: Optional[float] = None) -> Optional[str]:
        """
        Place a buy order and store it in the database.
        
        Args:
            quantity: Order quantity
            price: Optional limit price (None for market orders)
            
        Returns:
            Optional[str]: Order ID if successful, None otherwise
        """
        # Validate order size
        current_price = price or self.price_manager.get_current_price()
        if not current_price:
            logger.error("Cannot place buy order - price not available")
            return None
        
        is_valid, error = validate_order_size(current_price, quantity)
        if not is_valid:
            logger.error(
                "Invalid order size",
                error=error,
                price=current_price,
                quantity=quantity
            )
            return None
        
        # Place order
        order_response = self._place_order('BUY', quantity, price)
        if not order_response:
            return None
        
        # Store in database
        with get_db() as db:
            order = create_order(
                db,
                order_id=str(order_response['orderId']),
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=quantity,
                price=price or float(order_response['price']),
                status=OrderStatus.NEW,
                order_type='LIMIT' if price else 'MARKET'
            )
            
            logger.info(
                "Buy order placed",
                order_id=order.order_id,
                quantity=quantity,
                price=price
            )
            
            return order.order_id
    
    def place_sell_order(
        self,
        buy_order_id: str,
        quantity: float,
        min_profit: float = MIN_PROFIT_PERCENTAGE
    ) -> Optional[str]:
        """
        Place a sell order for a buy position.
        
        Args:
            buy_order_id: Original buy order ID
            quantity: Quantity to sell
            min_profit: Minimum profit percentage required
            
        Returns:
            Optional[str]: Order ID if successful, None otherwise
        """
        # Get buy order details
        with get_db() as db:
            buy_order = get_order_by_id(db, buy_order_id)
            if not buy_order:
                logger.error(
                    "Buy order not found",
                    buy_order_id=buy_order_id
                )
                return None
        
        # Calculate minimum sell price
        min_sell_price = calculate_min_sell_price(
            buy_order.price,
            quantity
        )
        
        # Place sell order
        order_response = self._place_order('SELL', quantity, min_sell_price)
        if not order_response:
            return None
        
        # Store in database
        with get_db() as db:
            order = create_order(
                db,
                order_id=str(order_response['orderId']),
                symbol=TRADING_SYMBOL,
                side='SELL',
                quantity=quantity,
                price=min_sell_price,
                status=OrderStatus.NEW,
                order_type='LIMIT',
                related_order_id=buy_order_id
            )
            
            logger.info(
                "Sell order placed",
                order_id=order.order_id,
                buy_order_id=buy_order_id,
                quantity=quantity,
                price=min_sell_price
            )
            
            return order.order_id
    
    def _handle_order_update(self, update: Dict[str, Any]) -> None:
        """
        Handle order status update from WebSocket.
        
        Args:
            update: Order update data
        """
        order_id = str(update['order_id'])
        status = update['status']
        filled_qty = update['filled_qty']
        price = update['price']
        
        with get_db() as db:
            order = get_order_by_id(db, order_id)
            if not order:
                logger.warning(
                    "Received update for unknown order",
                    order_id=order_id
                )
                return
            
            # Update order status
            update_order(
                db,
                order_id=order_id,
                status=OrderStatus[status],
                filled_quantity=filled_qty,
                average_price=price
            )
            
            logger.info(
                "Order updated",
                order_id=order_id,
                status=status,
                filled_qty=filled_qty,
                price=price
            )
            
            # Handle partial fills for buy orders
            if (
                order.side == 'BUY' and
                status == 'PARTIALLY_FILLED' and
                filled_qty > 0
            ):
                self._handle_partial_fill(order, filled_qty, price)
    
    def _handle_partial_fill(
        self,
        buy_order: Order,
        filled_qty: float,
        price: float
    ) -> None:
        """
        Handle partial fill by placing corresponding sell order.
        
        Args:
            buy_order: Original buy order
            filled_qty: Quantity that was filled
            price: Fill price
        """
        # Place sell order for the partially filled amount
        sell_order_id = self.place_sell_order(
            buy_order.order_id,
            filled_qty
        )
        
        if sell_order_id:
            logger.info(
                "Placed sell order for partial fill",
                buy_order_id=buy_order.order_id,
                sell_order_id=sell_order_id,
                quantity=filled_qty,
                price=price
            )
        else:
            logger.error(
                "Failed to place sell order for partial fill",
                buy_order_id=buy_order.order_id,
                quantity=filled_qty,
                price=price
            )
    
    def get_position_duration(self, order_id: str) -> Optional[float]:
        """
        Get duration of a position in seconds.
        
        Args:
            order_id: Order ID to check
            
        Returns:
            Optional[float]: Position duration in seconds or None if not found
        """
        with get_db() as db:
            order = get_order_by_id(db, order_id)
            if not order or not order.created_at:
                return None
            
            return (datetime.utcnow() - order.created_at).total_seconds()
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions with their durations.
        
        Returns:
            List[Dict[str, Any]]: List of open positions with details
        """
        positions = []
        with get_db() as db:
            orders = get_open_orders(db)
            for order in orders:
                duration = self.get_position_duration(order.order_id)
                positions.append({
                    'order_id': order.order_id,
                    'symbol': order.symbol,
                    'quantity': order.quantity,
                    'price': order.price,
                    'status': order.status.value,
                    'duration_seconds': duration
                })
        
        return positions 