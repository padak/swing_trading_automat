"""
Order manager for handling buy/sell operations and tracking positions.
Handles order monitoring, placement, and partial fill tracking.
"""
from typing import Optional, Dict, Any, List, Tuple, Set
from datetime import datetime, timedelta
import time
import hmac
import hashlib
import requests
import threading
from enum import Enum

from src.config.logging_config import get_logger
from src.config.settings import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_API_URL,
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE,
    MAX_ORDER_USDC,
    POSITION_DURATION_ALERT_THRESHOLD,
    POSITION_DURATION_CHECK_INTERVAL
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
    get_order_by_id,
    get_related_orders,
    update_system_state
)
from src.db.models import Order, OrderStatus, SystemStatus

logger = get_logger(__name__)

class OrderTransition(Enum):
    """Valid order state transitions according to design specification."""
    OPEN_TO_PARTIAL = ('OPEN', 'PARTIALLY_FILLED')
    OPEN_TO_FILLED = ('OPEN', 'FILLED')
    OPEN_TO_CANCELLED = ('OPEN', 'CANCELLED')
    OPEN_TO_REJECTED = ('OPEN', 'REJECTED')
    PARTIAL_TO_FILLED = ('PARTIALLY_FILLED', 'FILLED')
    PARTIAL_TO_CANCELLED = ('PARTIALLY_FILLED', 'CANCELLED')

class OrderManager:
    """
    Manages order operations including monitoring, placement, and tracking.
    Handles both market and limit orders with partial fill support.
    """
    
    def __init__(self, price_manager, state_manager):
        """
        Initialize order manager.
        
        Args:
            price_manager: Instance of PriceManager for price updates and order status
            state_manager: Instance of StateManager for system state management
        """
        self.logger = get_logger(__name__)  # Initialize logger first
        self.price_manager = price_manager
        self.state_manager = state_manager
        self.monitored_orders: Dict[str, Dict[str, Any]] = {}
        self.position_alerts: Set[str] = set()  # Track orders that have triggered alerts
        self.state_transitions: Dict[str, List[Dict[str, Any]]] = {}
        self.running = False
        self.duration_monitor_thread = None
        
        # Start position duration monitoring
        self._start_duration_monitoring()
    
    def start(self):
        """Start the order manager."""
        self.running = True
        self.logger.info("Order Manager started")
    
    def stop(self) -> None:
        """Stop the order manager and cleanup resources."""
        self.logger.debug("OrderManager stop initiated")
        
        # Set running flag to false first
        self.running = False
        
        # Stop duration monitoring thread with timeout
        if self.duration_monitor_thread and self.duration_monitor_thread.is_alive():
            self.logger.debug("Waiting for duration monitor thread to stop...")
            self.duration_monitor_thread.join(timeout=5)
            if self.duration_monitor_thread.is_alive():
                self.logger.warning("Duration monitor thread did not stop within timeout")
        
        # Clear any stored state
        self.position_alerts.clear()
        self.state_transitions.clear()
        
        self.logger.debug("OrderManager stop completed")
    
    def handle_price_update(self, price: float):
        """
        Handle price updates from PriceManager.
        Checks profit conditions and places sell orders if needed.
        
        Args:
            price: Current market price
        """
        if not self.running:
            return
            
        try:
            with get_db() as db:
                # Get all open buy orders
                open_orders = get_open_orders(db, side='BUY')
                
                for order in open_orders:
                    if order.status == OrderStatus.FILLED:
                        # Calculate profit potential
                        min_sell_price = calculate_min_sell_price(
                            order.average_price or order.price,
                            order.filled_quantity
                        )
                        
                        if price >= min_sell_price:
                            # Place sell order
                            self.place_sell_order(
                                order.binance_order_id,
                                order.filled_quantity
                            )
                            
        except Exception as e:
            logger.error("Error handling price update", error=str(e))
    
    def handle_order_update(self, order_data: Dict[str, Any]) -> None:
        """Handle order update from WebSocket."""
        try:
            # Extract data from Binance format
            # Note: Binance uses 'i' for orderId, 'S' for side, 'X' for status
            order_id = str(order_data.get('i', order_data.get('order_id')))
            side = order_data.get('S', order_data.get('side', 'UNKNOWN'))
            status = order_data.get('X', order_data.get('status'))
            quantity = float(order_data.get('q', order_data.get('quantity', 0)))
            filled_quantity = float(order_data.get('z', order_data.get('filled', 0)))
            # Use last filled price if price is 0
            price = float(order_data.get('L', order_data.get('last_filled_price', 0))) or float(order_data.get('p', order_data.get('price', 0)))
            
            self.logger.debug(
                "Processing order update",
                extra={
                    "order_id": order_id,
                    "side": side,
                    "status": status,
                    "quantity": quantity,
                    "filled_quantity": filled_quantity,
                    "price": price,
                    "raw_data": order_data
                }
            )

            with get_db() as db:
                # First try to find existing order
                order = get_order_by_id(db, order_id)
                
                # If order not found and this is an OPEN status, create it
                if not order and status == "NEW":
                    self.logger.info(
                        "Creating new order record",
                        extra={
                            "order_id": order_id,
                            "side": side,
                            "quantity": quantity
                        }
                    )
                    order = create_order(
                        db,
                        order_id=order_id,
                        symbol=TRADING_SYMBOL,
                        side=side,
                        quantity=quantity,
                        price=price,
                        status=OrderStatus.OPEN
                    )
                elif not order:
                    self.logger.error(
                        "Order not found and not in OPEN status",
                        extra={
                            "order_id": order_id,
                            "status": status
                        }
                    )
                    return
                else:
                    self.logger.debug(
                        "Found matching order in database",
                        extra={
                            "order_id": order_id,
                            "db_status": order.status,
                            "db_side": order.side
                        }
                    )

                # Handle filled BUY orders
                if status == "FILLED" and side == "BUY":
                    self.logger.info(
                        "BUY order filled, preparing SELL order",
                        extra={
                            "order_id": order_id,
                            "fill_quantity": filled_quantity,
                            "fill_price": price
                        }
                    )

                    # Check minimum quantity
                    if filled_quantity < MIN_SELL_QUANTITY:
                        self.logger.warning(
                            "Not placing SELL - below minimum quantity",
                            extra={
                                "quantity": filled_quantity,
                                "min_required": MIN_SELL_QUANTITY
                            }
                        )
                        return

                    # Calculate target sell price
                    try:
                        target_price = self.calculate_sell_price(price)
                        self.logger.info(
                            "Calculated SELL target price",
                            extra={
                                "buy_price": price,
                                "target_price": target_price,
                                "profit_margin": ((target_price / price) - 1) * 100
                            }
                        )
                    except Exception as e:
                        self.logger.error(
                            "Failed to calculate sell price",
                            error=str(e),
                            buy_price=price
                        )
                        return

                    # Place sell order
                    try:
                        sell_order = self.place_sell_order(
                            symbol=order.symbol,
                            quantity=filled_quantity,
                            price=target_price,
                            related_order_id=order_id
                        )
                        self.logger.info(
                            "Successfully placed SELL order",
                            extra={
                                "sell_order_id": sell_order.order_id,
                                "quantity": filled_quantity,
                                "price": target_price,
                                "related_buy_id": order_id
                            }
                        )
                    except Exception as e:
                        self.logger.error(
                            "Failed to place SELL order",
                            error=str(e),
                            quantity=filled_quantity,
                            price=target_price
                        )

                # Update order status in database
                update_order(
                    db,
                    order_id,
                    status=OrderStatus(status),
                    filled_quantity=filled_quantity,
                    average_price=price
                )

        except Exception as e:
            self.logger.error(
                "Error handling order update",
                error=str(e),
                order_data=order_data
            )

    def _handle_partial_fill(self, db, order: Order, update_data: Dict[str, Any]):
        """Handle partial order fills."""
        try:
            filled_qty = float(update_data.get('executedQty', 0))
            avg_price = float(update_data.get('avgPrice', 0))
            
            # Update order
            update_order(
                db,
                order.binance_order_id,
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=filled_qty,
                average_price=avg_price
            )
            
            # Create independent trade for filled portion
            if order.side == 'BUY':
                self._create_partial_buy_trade(db, order, filled_qty, avg_price)
                
        except Exception as e:
            logger.error("Error handling partial fill", error=str(e))
    
    def _handle_complete_fill(self, db, order: Order, update_data: Dict[str, Any]):
        """Handle complete order fills."""
        try:
            filled_qty = float(update_data.get('executedQty', 0))
            avg_price = float(update_data.get('avgPrice', 0))
            
            # Update order
            update_order(
                db,
                order.binance_order_id,
                status=OrderStatus.FILLED,
                filled_quantity=filled_qty,
                average_price=avg_price
            )
            
            # If this is a buy order, calculate and place sell order
            if order.side == 'BUY':
                self._handle_buy_fill(db, order, filled_qty, avg_price)
                
        except Exception as e:
            logger.error("Error handling complete fill", error=str(e))
    
    def _handle_order_termination(self, db, order: Order, status: str):
        """Handle order cancellation, rejection, or expiration."""
        try:
            update_order(
                db,
                order.binance_order_id,
                status=OrderStatus[status]
            )
        except Exception as e:
            logger.error("Error handling order termination", error=str(e))

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
                status=OrderStatus.OPEN,
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
        Ensures strict quantity matching and profit requirements.
        
        Args:
            buy_order_id: Original buy order ID
            quantity: Quantity to sell
            min_profit: Minimum profit percentage required
            
        Returns:
            Optional[str]: Order ID if successful, None otherwise
        """
        # Get buy order details and validate
        with get_db() as db:
            buy_order = get_order_by_id(db, buy_order_id)
            if not buy_order:
                logger.error(
                    "Buy order not found",
                    buy_order_id=buy_order_id
                )
                return None
            
            # Validate buy order status
            if buy_order.status not in [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED]:
                logger.error(
                    "Buy order not filled",
                    buy_order_id=buy_order_id,
                    status=buy_order.status
                )
                return None
            
            # Get existing sell orders for this buy order
            related_orders = get_related_orders(db, buy_order_id)
            existing_sell_qty = sum(
                o.quantity
                for o in related_orders
                if o.side == 'SELL' and o.status != OrderStatus.CANCELED
            )
            
            # Validate total sell quantity doesn't exceed buy quantity
            if existing_sell_qty + quantity > buy_order.filled_quantity:
                logger.error(
                    "Total sell quantity would exceed buy quantity",
                    buy_order_id=buy_order_id,
                    requested_qty=quantity,
                    existing_sell_qty=existing_sell_qty,
                    buy_filled_qty=buy_order.filled_quantity
                )
                return None
            
            # Validate order size
            current_price = self.price_manager.get_current_price()
            if not current_price:
                logger.error("Cannot validate sell order - price not available")
                return None
            
            # Calculate order value in USDC
            order_value = current_price * quantity
            if order_value > MAX_ORDER_USDC:  # From settings
                logger.error(
                    "Order exceeds maximum value",
                    max_value=MAX_ORDER_USDC,
                    attempted_value=order_value
                )
                return None
            
            is_valid, error = validate_order_size(current_price, quantity)
            if not is_valid:
                logger.error(
                    "Invalid sell order size",
                    error=error,
                    price=current_price,
                    quantity=quantity
                )
                return None
        
        # Calculate minimum sell price with required profit
        min_sell_price = calculate_min_sell_price(
            buy_order.price,
            quantity,
            min_profit
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
                status=OrderStatus.OPEN,
                order_type='LIMIT',
                related_order_id=buy_order_id
            )
            
            logger.info(
                "Sell order placed",
                order_id=order.order_id,
                buy_order_id=buy_order_id,
                quantity=quantity,
                price=min_sell_price,
                profit_target=min_profit
            )
            
            return order.order_id
    
    def _validate_fill_quantity(self, order: Order, new_filled_qty: float) -> Tuple[bool, str]:
        """
        Validate fill quantity against existing order and related orders.
        
        Args:
            order: Order being filled
            new_filled_qty: New quantity being filled
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        with get_db() as db:
            # Get all related orders
            related_orders = get_related_orders(db, order.order_id)
            total_filled = sum(o.filled_quantity or 0 for o in related_orders)
            
            # Check if new fill would exceed original quantity
            if total_filled + new_filled_qty > order.quantity:
                return False, f"Fill quantity {new_filled_qty} would exceed order quantity {order.quantity}"
            
            # For sell orders, validate against buy order quantity
            if order.side == 'SELL' and order.related_order_id:
                buy_order = get_order_by_id(db, order.related_order_id)
                if buy_order and new_filled_qty > buy_order.filled_quantity:
                    return False, f"Sell quantity {new_filled_qty} exceeds buy fill quantity {buy_order.filled_quantity}"
            
            return True, ""

    def _validate_state_transition(
        self,
        order_id: str,
        current_status: str,
        new_status: str
    ) -> bool:
        """
        Validate if a state transition is allowed.
        
        Args:
            order_id: Order ID being updated
            current_status: Current order status
            new_status: Proposed new status
            
        Returns:
            bool: True if transition is valid
            
        Raises:
            OrderTransitionError: If transition is invalid
        """
        # Get valid transitions
        valid_transitions = [
            t.value for t in OrderTransition 
            if t.value[0] == current_status
        ]
        
        # Check if transition is valid
        if not valid_transitions:
            raise OrderTransitionError(
                f"No valid transitions from {current_status}"
            )
        
        valid_next_states = [t[1] for t in valid_transitions]
        if new_status not in valid_next_states:
            raise OrderTransitionError(
                f"Invalid transition from {current_status} to {new_status}. "
                f"Valid transitions: {valid_next_states}"
            )
        
        return True
    
    def _record_state_transition(
        self,
        order_id: str,
        from_status: str,
        to_status: str,
        reason: str = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        Record an order state transition for auditing.
        
        Args:
            order_id: Order being updated
            from_status: Previous status
            to_status: New status
            reason: Optional reason for transition
            metadata: Optional additional data
        """
        if order_id not in self.state_transitions:
            self.state_transitions[order_id] = []
        
        transition = {
            'timestamp': datetime.utcnow(),
            'from_status': from_status,
            'to_status': to_status,
            'reason': reason,
            'metadata': metadata or {}
        }
        
        self.state_transitions[order_id].append(transition)
        
        logger.info(
            "Order state transition",
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            metadata=metadata
        )
    
    def _handle_order_update(self, update: Dict[str, Any]):
        # Add fallback mechanism
        if not self.price_manager.ws_connected:
            logger.warning("WebSocket disconnected, using REST fallback")
            self._poll_orders_via_rest()
        
        order_id = str(update['order_id'])
        new_status = update['status']
        filled_qty = update['filled_qty']
        price = update['price']
        
        with get_db() as db:
            order = get_order_by_id(db, order_id)
            if not order:
                logger.warning(
                    "Received update for unknown order",
                    order_id=order_id,
                    status=new_status
                )
                return
            
            current_status = order.status.value
            
            # Validate state transition
            try:
                self._validate_state_transition(
                    order_id,
                    current_status,
                    new_status
                )
            except OrderTransitionError as e:
                logger.error(
                    "Invalid order state transition",
                    order_id=order_id,
                    error=str(e),
                    current_status=current_status,
                    new_status=new_status
                )
                return
            
            # Validate fill quantity
            is_valid, error = self._validate_fill_quantity(order, filled_qty)
            if not is_valid:
                logger.error(
                    "Invalid fill quantity",
                    order_id=order_id,
                    error=error
                )
                return
            
            # Track monitoring state
            if order_id not in self.monitored_orders:
                self.monitored_orders[order_id] = {
                    'last_update': time.time(),
                    'fills': [],
                    'total_filled': 0.0
                }
            
            # Record fill
            if filled_qty > 0:
                new_fill_qty = filled_qty - self.monitored_orders[order_id]['total_filled']
                if new_fill_qty > 0:
                    self.monitored_orders[order_id]['fills'].append({
                        'quantity': new_fill_qty,
                        'price': price,
                        'timestamp': time.time()
                    })
                    self.monitored_orders[order_id]['total_filled'] = filled_qty
            
            # Update monitoring state
            self.monitored_orders[order_id]['last_update'] = time.time()
            self.monitored_orders[order_id]['status'] = new_status
            
            # Record state transition
            self._record_state_transition(
                order_id,
                current_status,
                new_status,
                metadata={
                    'filled_qty': filled_qty,
                    'price': price,
                    'new_fill_qty': new_fill_qty if filled_qty > 0 else 0
                }
            )
            
            # Update order in database
            update_order(
                db,
                order_id=order_id,
                status=OrderStatus[new_status],
                filled_quantity=filled_qty,
                average_price=price
            )
            
            logger.info(
                "Order updated",
                order_id=order_id,
                status=new_status,
                filled_qty=filled_qty,
                new_fill_qty=new_fill_qty if filled_qty > 0 else 0,
                price=price,
                side=order.side,
                total_fills=len(self.monitored_orders[order_id]['fills'])
            )
            
            # Handle BUY order fills
            if order.side == 'BUY':
                if new_status == 'PARTIALLY_FILLED' and new_fill_qty > 0:
                    self._handle_partial_fill(order, new_fill_qty, price)
                elif new_status == 'FILLED':
                    remaining_qty = order.quantity - sum(
                        fill['quantity'] 
                        for fill in self.monitored_orders[order_id]['fills']
                    )
                    if remaining_qty > 0:
                        self._handle_partial_fill(order, remaining_qty, price)
            
            # Cleanup monitoring state for completed orders
            if new_status in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
                self.monitored_orders.pop(order_id, None)
    
    def _handle_partial_fill(
        self,
        buy_order: Order,
        filled_qty: float,
        price: float
    ) -> None:
        """
        Handle partial fill by creating an independent trade record and placing corresponding sell order.
        Each partial fill is treated as a separate trade with its own SELL order.
        
        Args:
            buy_order: Original buy order
            filled_qty: Quantity that was filled
            price: Fill price
        """
        # Create independent trade record for this fill
        with get_db() as db:
            # Create a new trade record
            trade = create_order(
                db,
                order_id=f"{buy_order.order_id}_fill_{int(time.time())}",
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=filled_qty,
                price=price,
                status=OrderStatus.FILLED,
                order_type='PARTIAL_FILL',
                related_order_id=buy_order.order_id
            )
            
            logger.info(
                "Created independent trade record for partial fill",
                parent_order_id=buy_order.order_id,
                trade_id=trade.order_id,
                quantity=filled_qty,
                price=price
            )
        
        # Place corresponding sell order
        sell_order_id = self.place_sell_order(
            trade.order_id,  # Use the new trade record as parent
            filled_qty,
            MIN_PROFIT_PERCENTAGE
        )
        
        if sell_order_id:
            logger.info(
                "Placed sell order for partial fill",
                parent_order_id=buy_order.order_id,
                trade_id=trade.order_id,
                sell_order_id=sell_order_id,
                quantity=filled_qty,
                price=price
            )
        else:
            logger.error(
                "Failed to place sell order for partial fill",
                parent_order_id=buy_order.order_id,
                trade_id=trade.order_id,
                quantity=filled_qty,
                price=price
            )
    
    def _start_duration_monitoring(self) -> None:
        """Start the position duration monitoring thread."""
        self.duration_monitor_thread = threading.Thread(
            target=self._monitor_positions,
            daemon=True
        )
        self.duration_monitor_thread.start()
        logger.info("Started position duration monitoring thread")

    def _monitor_positions(self) -> None:
        """Monitor position durations and alert if threshold exceeded."""
        while self.running:
            try:
                with get_db() as db:
                    # Update system state with current monitoring status
                    update_system_state(
                        db,
                        websocket_status="MONITORING",
                        last_error=None,
                        reconnection_attempts=0
                    )
                    
                    # Check positions
                    self._check_position_durations(db)
                    
                # Sleep for interval
                time.sleep(POSITION_DURATION_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(
                    "Error in position duration monitoring",
                    error=str(e)
                )

    def _check_position_durations(self, db):
        positions = self.get_open_positions()
        for position in positions:
            order_id = position['order_id']
            duration = position['duration_seconds']
            
            # Check if position exceeds duration threshold and hasn't alerted
            if (duration > POSITION_DURATION_ALERT_THRESHOLD and 
                order_id not in self.position_alerts):
                logger.warning(
                    "Position duration alert",
                    order_id=order_id,
                    symbol=position['symbol'],
                    duration_hours=duration / 3600,
                    quantity=position['quantity'],
                    price=position['price']
                )
                self.position_alerts.add(order_id)
        
        # Cleanup alerts for closed positions
        open_order_ids = {p['order_id'] for p in positions}
        self.position_alerts = self.position_alerts & open_order_ids
        
        # Add this to store state periodically
        update_system_state(
            db,
            open_positions=len(self.get_open_positions()),
            oldest_position_age=max(
                p['duration_seconds'] 
                for p in self.get_open_positions()
            ) if self.get_open_positions() else 0
        )

    def get_position_duration(self, order_id: str) -> Optional[float]:
        """
        Get duration of a position in seconds.
        Includes partial fill durations for accurate tracking.
        
        Args:
            order_id: Order ID to check
            
        Returns:
            Optional[float]: Position duration in seconds or None if not found
        """
        with get_db() as db:
            order = get_order_by_id(db, order_id)
            if not order or not order.created_at:
                return None
            
            # For orders with partial fills, get the earliest fill time
            related_orders = get_related_orders(db, order_id)
            all_orders = [order] + related_orders
            
            # Find earliest timestamp among all related orders
            earliest_time = min(
                o.created_at for o in all_orders 
                if o.created_at is not None
            )
            
            return (datetime.utcnow() - earliest_time).total_seconds()
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions with their durations and related orders.
        Includes partial fills and sell order status.
        
        Returns:
            List[Dict[str, Any]]: List of open positions with details
        """
        positions = []
        with get_db() as db:
            orders = get_open_orders(db)
            for order in orders:
                # Get all related orders (partial fills and sells)
                related_orders = get_related_orders(db, order.order_id)
                
                # Calculate total filled quantity
                total_filled = sum(
                    o.filled_quantity or 0 
                    for o in [order] + related_orders 
                    if o.side == 'BUY'
                )
                
                # Calculate total sold quantity
                total_sold = sum(
                    (o.filled_quantity or 0)
                    for o in related_orders
                    if o.side == 'SELL' and o.status == OrderStatus.FILLED
                )
                
                # Get position duration
                duration = self.get_position_duration(order.order_id)
                
                positions.append({
                    'order_id': order.order_id,
                    'symbol': order.symbol,
                    'quantity': order.quantity,
                    'filled_quantity': total_filled,
                    'sold_quantity': total_sold,
                    'remaining_quantity': total_filled - total_sold,
                    'price': order.price,
                    'status': order.status.value,
                    'duration_seconds': duration,
                    'duration_hours': duration / 3600 if duration else None,
                    'has_partial_fills': any(
                        o.order_type == 'PARTIAL_FILL' 
                        for o in related_orders
                    ),
                    'sell_orders': [
                        {
                            'order_id': o.order_id,
                            'quantity': o.quantity,
                            'price': o.price,
                            'status': o.status.value
                        }
                        for o in related_orders
                        if o.side == 'SELL'
                    ]
                })
        
        return positions

    def get_order_transitions(self, order_id: str) -> List[Dict[str, Any]]:
        """
        Get state transition history for an order.
        
        Args:
            order_id: Order to get transitions for
            
        Returns:
            List[Dict[str, Any]]: List of state transitions
        """
        return self.state_transitions.get(order_id, [])

    def _poll_orders_via_rest(self):
        # Implement REST API polling logic
        pass 

    def _update_order_status(self, order_id: int, new_status: str) -> None:
        """Update order status in database."""
        with get_db() as db:
            order = get_order_by_id(db, order_id)
            if order:
                order.status = OrderStatus[new_status].value
                db.commit() 