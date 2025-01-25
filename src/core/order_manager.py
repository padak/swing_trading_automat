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
from sqlalchemy.orm import Session

from src.config.logging_config import get_logger
from src.config.settings import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_API_URL,
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE,
    MAX_ORDER_USDC,
    POSITION_DURATION_ALERT_THRESHOLD,
    POSITION_DURATION_CHECK_INTERVAL,
    MIN_ORDER_QUANTITY,
    PROFIT_MARGIN,
    MAX_POSITION_DURATION,
    MONITOR_LOOP_INTERVAL,
    DB_TRANSACTION_TIMEOUT,
    POSITION_CHECK_INTERVAL,
    SHUTDOWN_TIMEOUT_ORDER,
    THREAD_SHUTDOWN_TIMEOUT,
    THREAD_TIMEOUT,
    ORDER_CHECK_INTERVAL
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

class ThreadInfo:
    """Track thread information for monitoring and cleanup."""
    def __init__(self, thread: threading.Thread, purpose: str):
        self.thread = thread
        self.purpose = purpose
        self.start_time = datetime.utcnow()
        self.last_active = self.start_time
        self.error_count = 0

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_active = datetime.utcnow()

    def increment_errors(self):
        """Increment error count."""
        self.error_count += 1

class OrderManager:
    """
    Manages order operations including monitoring, placement, and tracking.
    Handles both market and limit orders with partial fill support.
    """
    
    def __init__(self, price_manager, state_manager):
        """
        Initialize order manager with proper thread tracking.
        
        Args:
            price_manager: Instance of PriceManager for price updates and order status
            state_manager: Instance of StateManager for system state management
        """
        self.logger = get_logger(__name__)
        self.price_manager = price_manager
        self.state_manager = state_manager
        self.should_run = False
        self.threads: Dict[str, ThreadInfo] = {}
        self.monitored_orders: Dict[str, Dict[str, Any]] = {}
        self.position_alerts: Set[str] = set()
        self.state_transitions: Dict[str, List[Dict[str, Any]]] = {}
        self.last_state_update = datetime.utcnow()
        self.shutdown_in_progress = False
        
        # Register callbacks
        self.price_manager.register_price_callback(self.handle_price_update)
        self.price_manager.register_order_callback(self.handle_order_update)
        
        self.logger.info("OrderManager initialized")
    
    def _register_thread(self, thread: threading.Thread, purpose: str) -> None:
        """Register a thread for monitoring."""
        thread_id = f"{thread.name}_{thread.ident}"
        self.threads[thread_id] = ThreadInfo(thread, purpose)
        self.logger.debug(
            f"Registered thread",
            extra={
                "thread_id": thread_id,
                "purpose": purpose,
                "total_threads": len(self.threads)
            }
        )

    def _cleanup_thread(self, thread_id: str) -> None:
        """Clean up a thread's resources."""
        if thread_id in self.threads:
            thread_info = self.threads[thread_id]
            self.logger.debug(
                f"Cleaning up thread",
                extra={
                    "thread_id": thread_id,
                    "purpose": thread_info.purpose,
                    "runtime": (datetime.utcnow() - thread_info.start_time).total_seconds(),
                    "error_count": thread_info.error_count
                }
            )
            del self.threads[thread_id]
    
    def start(self):
        """Start the order manager with proper thread management."""
        try:
            if self.should_run:
                self.logger.warning("OrderManager already running")
                return
                
            self.should_run = True
            self.logger.info("Starting OrderManager")
            
            # Start position monitor thread
            monitor_thread = threading.Thread(
                target=self._monitor_positions,
                name="PositionMonitor",
                daemon=True
            )
            monitor_thread.start()
            self._register_thread(monitor_thread, "position_monitoring")
            
            # Wait for monitor thread to start with timeout
            start_time = time.time()
            while not any(t.thread.name == "PositionMonitor" and t.thread.is_alive() 
                         for t in self.threads.values()):
                if time.time() - start_time > 5.0:
                    raise RuntimeError("Position monitor thread failed to start")
                time.sleep(0.1)
            
            self.logger.info(
                "OrderManager started successfully",
                extra={
                    "active_threads": len(self.threads),
                    "thread_purposes": [t.purpose for t in self.threads.values()]
                }
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to start OrderManager",
                exc_info=True,
                extra={"error": str(e)}
            )
            self.stop()
            raise
    
    def stop(self) -> None:
        """Stop the order manager with proper thread cleanup."""
        if not self.should_run:
            self.logger.debug("OrderManager already stopped")
            return
            
        self.logger.info("OrderManager stop initiated")
        stop_start = time.time()
        
        # Signal threads to stop
        self.should_run = False
        
        # Join all threads with timeout
        active_threads = list(self.threads.items())
        for thread_id, thread_info in active_threads:
            try:
                if thread_info.thread.is_alive():
                    self.logger.debug(
                        f"Waiting for thread to stop",
                        extra={
                            "thread_id": thread_id,
                            "purpose": thread_info.purpose,
                            "runtime": (datetime.utcnow() - thread_info.start_time).total_seconds()
                        }
                    )
                    thread_info.thread.join(timeout=SHUTDOWN_TIMEOUT_ORDER)
                    if thread_info.thread.is_alive():
                        self.logger.warning(
                            f"Thread did not stop in time",
                            extra={
                                "thread_id": thread_id,
                                "purpose": thread_info.purpose,
                                "error_count": thread_info.error_count
                            }
                        )
                    else:
                        self.logger.debug(f"Thread {thread_id} stopped successfully")
                        self._cleanup_thread(thread_id)
            except Exception as e:
                self.logger.error(
                    f"Error stopping thread",
                    exc_info=True,
                    extra={
                        "thread_id": thread_id,
                        "purpose": thread_info.purpose,
                        "error": str(e)
                    }
                )
        
        # Clear remaining threads
        remaining_threads = len(self.threads)
        if remaining_threads > 0:
            self.logger.warning(
                f"Threads did not stop properly",
                extra={
                    "remaining_count": remaining_threads,
                    "thread_purposes": [t.purpose for t in self.threads.values()]
                }
            )
        self.threads.clear()
        
        # Clear state with logging
        orders_count = len(self.monitored_orders)
        alerts_count = len(self.position_alerts)
        transitions_count = len(self.state_transitions)
        
        self.monitored_orders.clear()
        self.position_alerts.clear()
        self.state_transitions.clear()
        
        stop_duration = time.time() - stop_start
        self.logger.info(
            "OrderManager stopped successfully",
            extra={
                "stop_duration": stop_duration,
                "cleared_orders": orders_count,
                "cleared_alerts": alerts_count,
                "cleared_transitions": transitions_count
            }
        )

    def handle_price_update(self, price: float):
        """
        Handle price updates from PriceManager.
        Checks profit conditions and places sell orders if needed.
        
        Args:
            price: Current market price
        """
        if not self.should_run:
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
    
    def handle_order_update(self, data: Dict[str, Any]) -> None:
        """Handle order update with proper error handling and state tracking."""
        try:
            # Log raw data first for debugging
            self.logger.debug(
                "Received order update",
                extra={
                    "raw_data": data,
                    "event_type": data.get('e'),
                    "has_side": 'S' in data or 'side' in data,
                    "has_status": 'X' in data or 'status' in data,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )

            # Extract order details with proper error handling
            try:
                order_details = self._extract_order_details(data)
            except KeyError as e:
                self.logger.error(
                    "Missing required field in order update",
                    exc_info=True,
                    extra={"missing_field": str(e), "data": data}
                )
                return
            except ValueError as e:
                self.logger.error(
                    "Invalid value in order update",
                    exc_info=True,
                    extra={"error": str(e), "data": data}
                )
                return

            # Process order with timeout and transaction management
            with get_db() as db:
                try:
                    db.begin_nested()  # Create savepoint
                    self._process_order_update(db, order_details)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error processing order update",
                        exc_info=True,
                        extra={
                            "order_details": order_details,
                            "error": str(e)
                        }
                    )
                    raise

        except Exception as e:
            self.logger.error(
                "Unhandled error in order update",
                exc_info=True,
                extra={"error": str(e)}
            )

    def _extract_order_details(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract order details from update data with validation."""
        try:
            if 'e' in data and data['e'] == 'executionReport':
                # WebSocket execution report format
                details = {
                    'order_id': str(data['i']),  # orderId
                    'side': data['S'],  # side
                    'status': data['X'],  # status
                    'symbol': data['s'],  # symbol
                    'quantity': float(data['q']),  # quantity
                    'filled': float(data['z']),  # cumulative filled quantity
                    'price': float(data['L']) if float(data['L']) > 0 else float(data['p']),  # last filled price or order price
                    'commission': float(data.get('n', 0)),  # commission amount
                    'commission_asset': data.get('N', ''),  # commission asset
                    'trade_id': data.get('t'),  # trade ID if filled
                    'order_type': data.get('o', 'LIMIT'),  # order type
                    'stop_price': float(data.get('P', 0)),  # stop price if any
                    'execution_type': data.get('x'),  # execution type
                    'reject_reason': data.get('r'),  # rejection reason if any
                    'timestamp': datetime.fromtimestamp(int(data['T']) / 1000) if 'T' in data else datetime.utcnow()
                }
            else:
                # Simplified order update format
                details = {
                    'order_id': str(data['order_id']),
                    'side': data.get('side'),
                    'status': data['status'],
                    'symbol': data.get('symbol', 'TRUMPUSDC'),
                    'quantity': float(data['quantity']),
                    'filled': float(data['filled']),
                    'price': float(data.get('last_filled_price', 0)) or float(data.get('price', 0)),
                    'commission': float(data.get('commission', 0)),
                    'commission_asset': data.get('commission_asset', ''),
                    'trade_id': data.get('trade_id'),
                    'order_type': data.get('type', 'LIMIT'),
                    'stop_price': float(data.get('stop_price', 0)),
                    'execution_type': data.get('execution_type'),
                    'reject_reason': data.get('reject_reason'),
                    'timestamp': data.get('timestamp', datetime.utcnow())
                }

            # Validate required fields
            required_fields = ['order_id', 'status', 'quantity', 'filled']
            missing_fields = [field for field in required_fields if not details.get(field)]
            if missing_fields:
                raise KeyError(f"Missing required fields: {', '.join(missing_fields)}")

            # Validate numeric fields
            numeric_fields = ['quantity', 'filled', 'price']
            for field in numeric_fields:
                if details.get(field) and not isinstance(details[field], (int, float)):
                    raise ValueError(f"Invalid numeric value for {field}: {details[field]}")

            return details

        except (KeyError, ValueError, TypeError) as e:
            self.logger.error(
                "Error extracting order details",
                exc_info=True,
                extra={"error": str(e), "data": data}
            )
            raise

    def _process_order_update(self, db: Session, details: Dict[str, Any]) -> None:
        """Process order update with proper state tracking and validation."""
        try:
            order = self.state_manager.get_order_by_id(details['order_id'])
            
            # Validate and track state transition
            if order and details['status'] != order.status:
                if not self._validate_state_transition(order.status, details['status']):
                    self.logger.error(
                        "Invalid state transition attempted",
                        extra={
                            "order_id": details['order_id'],
                            "current_status": order.status,
                            "attempted_status": details['status']
                        }
                    )
                    return
                self._track_state_transition(order, details['status'])
            
            # Create or update order with transaction management
            try:
                db.begin_nested()  # Create savepoint
                
                if not order and details['status'] in ['NEW', 'PARTIALLY_FILLED', 'OPEN']:
                    self.logger.info(
                        "Creating new order record",
                        extra={
                            "order_id": details['order_id'],
                            "side": details['side'],
                            "status": details['status'],
                            "timestamp": details['timestamp'].isoformat()
                        }
                    )
                    order = self.state_manager.create_order(
                        binance_order_id=details['order_id'],
                        symbol=details['symbol'],
                        side=details['side'] or 'BUY',  # Default to BUY if side is unknown
                        quantity=details['quantity'],
                        price=details['price'],
                        status=details['status'],
                        order_type=details['order_type'],
                        commission=details['commission'],
                        commission_asset=details['commission_asset']
                    )
                elif order:
                    self.logger.info(
                        "Updating existing order",
                        extra={
                            "order_id": details['order_id'],
                            "old_status": order.status,
                            "new_status": details['status'],
                            "filled": details['filled'],
                            "timestamp": details['timestamp'].isoformat()
                        }
                    )
                    self.state_manager.update_order(
                        order_id=details['order_id'],
                        status=details['status'],
                        filled_quantity=details['filled'],
                        commission=details['commission'],
                        commission_asset=details['commission_asset'],
                        last_update=details['timestamp']
                    )
                
                db.commit()
                
                # Handle filled BUY orders after successful commit
                if (details['status'] == 'FILLED' and 
                    (details['side'] == 'BUY' or (order and order.side == 'BUY'))):
                    self._handle_buy_fill(order, details)
                    
            except Exception as e:
                db.rollback()
                self.logger.error(
                    "Error in database transaction",
                    exc_info=True,
                    extra={
                        "order_id": details['order_id'],
                        "status": details['status'],
                        "error": str(e)
                    }
                )
                raise

        except Exception as e:
            self.logger.error(
                "Error processing order update",
                exc_info=True,
                extra={
                    "order_id": details.get('order_id'),
                    "status": details.get('status'),
                    "error": str(e)
                }
            )
            raise

    def _validate_state_transition(self, current_status: str, new_status: str) -> bool:
        """
        Validate if a state transition is allowed according to design specification.
        
        Args:
            current_status: Current order status
            new_status: Proposed new status
            
        Returns:
            bool: True if transition is valid, False otherwise
        """
        try:
            # Define valid transitions based on OrderTransition enum
            transition = (current_status, new_status)
            valid_transitions = [
                (t.value[0], t.value[1]) for t in OrderTransition
            ]
            
            # Special case: Allow NEW to OPEN transition (they are equivalent)
            if transition == ('NEW', 'OPEN') or transition == ('OPEN', 'NEW'):
                return True
            
            is_valid = transition in valid_transitions
            if not is_valid:
                self.logger.warning(
                    "Invalid state transition attempted",
                    extra={
                        "from_status": current_status,
                        "to_status": new_status,
                        "valid_transitions": valid_transitions,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
            return is_valid
            
        except Exception as e:
            self.logger.error(
                "Error validating state transition",
                exc_info=True,
                extra={
                    "from_status": current_status,
                    "to_status": new_status,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            return False

    def _track_state_transition(self, order: Order, new_status: str) -> None:
        """Track order state transitions with timestamps and validation."""
        try:
            if order.status == new_status:
                return
                
            if not self._validate_state_transition(order.status, new_status):
                self.logger.error(
                    "Invalid state transition rejected",
                    extra={
                        "order_id": order.binance_order_id,
                        "current_status": order.status,
                        "attempted_status": new_status,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                return
                
            transition = {
                'timestamp': datetime.utcnow().isoformat(),
                'from_status': order.status,
                'to_status': new_status,
                'order_id': order.binance_order_id,
                'filled_quantity': order.filled_quantity,
                'price': order.price,
                'side': order.side
            }
            
            if order.binance_order_id not in self.state_transitions:
                self.state_transitions[order.binance_order_id] = []
            
            self.state_transitions[order.binance_order_id].append(transition)
            
            self.logger.info(
                "Order state transition",
                extra={
                    "order_id": order.binance_order_id,
                    "from_status": order.status,
                    "to_status": new_status,
                    "transition": transition,
                    "total_transitions": len(self.state_transitions[order.binance_order_id])
                }
            )
            
            # Update state manager with latest transition
            if (datetime.utcnow() - self.last_state_update).total_seconds() >= MONITOR_LOOP_INTERVAL:
                self.state_manager.update_state(
                    last_order_update=datetime.utcnow(),
                    last_status_change=new_status,
                    order_id=order.binance_order_id
                )
                self.last_state_update = datetime.utcnow()
                
        except Exception as e:
            self.logger.error(
                "Error tracking state transition",
                exc_info=True,
                extra={
                    "order_id": order.binance_order_id if order else None,
                    "from_status": order.status if order else None,
                    "to_status": new_status,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            )

    def _handle_buy_fill(self, order: Order, details: Dict[str, Any]) -> None:
        """Handle filled BUY order with commission consideration."""
        try:
            filled_quantity = float(details['filled'])
            fill_price = float(details['price'])
            
            # Adjust quantity for commission if paid in the traded asset
            if details['commission_asset'] == order.symbol.replace('USDC', ''):
                adjusted_quantity = filled_quantity - float(details['commission'])
                self.logger.info(
                    "Adjusted quantity for commission",
                    extra={
                        "order_id": order.binance_order_id,
                        "original_quantity": filled_quantity,
                        "commission": details['commission'],
                        "adjusted_quantity": adjusted_quantity
                    }
                )
                filled_quantity = adjusted_quantity

            # Validate final quantity
            if filled_quantity < MIN_ORDER_QUANTITY:
                self.logger.warning(
                    "Filled quantity below minimum after commission",
                    extra={
                        "order_id": order.binance_order_id,
                        "quantity": filled_quantity,
                        "min_quantity": MIN_ORDER_QUANTITY
                    }
                )
                return

            # Place sell order
            sell_order_id = self.place_sell_order(
                order.binance_order_id,
                filled_quantity,
                MIN_PROFIT_PERCENTAGE
            )
            
            if sell_order_id:
                self.logger.info(
                    "Placed sell order for filled buy",
                    extra={
                        "buy_order_id": order.binance_order_id,
                        "sell_order_id": sell_order_id,
                        "quantity": filled_quantity,
                        "buy_price": fill_price
                    }
                )
            else:
                self.logger.error(
                    "Failed to place sell order",
                    extra={
                        "buy_order_id": order.binance_order_id,
                        "quantity": filled_quantity,
                        "buy_price": fill_price
                    }
                )

        except Exception as e:
            self.logger.error(
                "Error handling buy fill",
                exc_info=True,
                extra={
                    "order_id": order.binance_order_id,
                    "error": str(e)
                }
            )
            raise

    def _handle_filled_order(self, order: Order) -> None:
        """
        Handle a completely filled order by updating state and creating sell orders if needed.
        
        Args:
            order: The filled Order object
        """
        try:
            with get_db() as db:
                db.begin_nested()  # Create savepoint
                try:
                    # Update order status
                    order.status = 'FILLED'
                    order.filled_quantity = order.quantity
                    order.last_update = datetime.utcnow()
                    
                    # For BUY orders, create corresponding SELL order
                    if order.side == 'BUY':
                        sell_price = self.profit_calculator.calculate_sell_price(
                            buy_price=order.price,
                            quantity=order.quantity,
                            symbol=order.symbol
                        )
                        
                        sell_order = Order(
                            symbol=order.symbol,
                            side='SELL',
                            quantity=order.filled_quantity,
                            price=sell_price,
                            status='NEW',
                            parent_order_id=order.binance_order_id,
                            created_at=datetime.utcnow(),
                            last_update=datetime.utcnow()
                        )
                        
                        # Place sell order on exchange
                        response = self.price_manager.place_limit_order(
                            symbol=sell_order.symbol,
                            side='SELL',
                            quantity=sell_order.quantity,
                            price=sell_order.price
                        )
                        
                        if response and 'orderId' in response:
                            sell_order.binance_order_id = str(response['orderId'])
                            db.add(sell_order)
                            self.logger.info(
                                "Created SELL order for filled BUY order",
                                extra={
                                    "buy_order_id": order.binance_order_id,
                                    "sell_order_id": sell_order.binance_order_id,
                                    "symbol": order.symbol,
                                    "quantity": sell_order.quantity,
                                    "price": sell_order.price
                                }
                            )
                        else:
                            self.logger.error(
                                "Failed to place SELL order",
                                extra={
                                    "buy_order_id": order.binance_order_id,
                                    "response": response
                                }
                            )
                            
                    db.commit()
                    
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error handling filled order",
                        exc_info=True,
                        extra={
                            "order_id": order.binance_order_id,
                            "error": str(e)
                        }
                    )
                    
        except Exception as e:
            self.logger.error(
                "Database error handling filled order",
                exc_info=True,
                extra={
                    "order_id": order.binance_order_id,
                    "error": str(e)
                }
            )

    def _handle_partial_fill(self, order: Order) -> None:
        """
        Handle a partially filled order by updating state and creating partial sell orders if needed.
        
        Args:
            order: The partially filled Order object
        """
        try:
            with get_db() as db:
                db.begin_nested()  # Create savepoint
                try:
                    # Get previous fill amount to determine if new fill occurred
                    previous_fill = db.query(Order).filter_by(
                        binance_order_id=order.binance_order_id
                    ).first()
                    
                    if not previous_fill:
                        self.logger.error(
                            "Previous order not found for partial fill",
                            extra={"order_id": order.binance_order_id}
                        )
                        return
                        
                    new_fill_amount = order.filled_quantity - previous_fill.filled_quantity
                    
                    # Only process if there's a new fill
                    if new_fill_amount > 0:
                        # For BUY orders, create corresponding partial SELL order
                        if order.side == 'BUY':
                            sell_price = self.profit_calculator.calculate_sell_price(
                                buy_price=order.price,
                                quantity=new_fill_amount,
                                symbol=order.symbol
                            )
                            
                            partial_sell = Order(
                                symbol=order.symbol,
                                side='SELL',
                                quantity=new_fill_amount,
                                price=sell_price,
                                status='NEW',
                                parent_order_id=order.binance_order_id,
                                is_partial=True,
                                created_at=datetime.utcnow(),
                                last_update=datetime.utcnow()
                            )
                            
                            # Place partial sell order
                            response = self.price_manager.place_limit_order(
                                symbol=partial_sell.symbol,
                                side='SELL',
                                quantity=partial_sell.quantity,
                                price=partial_sell.price
                            )
                            
                            if response and 'orderId' in response:
                                partial_sell.binance_order_id = str(response['orderId'])
                                db.add(partial_sell)
                                self.logger.info(
                                    "Created partial SELL order",
                                    extra={
                                        "buy_order_id": order.binance_order_id,
                                        "sell_order_id": partial_sell.binance_order_id,
                                        "symbol": order.symbol,
                                        "quantity": partial_sell.quantity,
                                        "price": partial_sell.price,
                                        "is_partial": True
                                    }
                                )
                            else:
                                self.logger.error(
                                    "Failed to place partial SELL order",
                                    extra={
                                        "buy_order_id": order.binance_order_id,
                                        "response": response
                                    }
                                )
                                
                    # Update original order
                    order.filled_quantity = float(order.filled_quantity)
                    order.last_update = datetime.utcnow()
                    db.commit()
                    
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error handling partial fill",
                        exc_info=True,
                        extra={
                            "order_id": order.binance_order_id,
                            "error": str(e)
                        }
                    )
                    
        except Exception as e:
            self.logger.error(
                "Database error handling partial fill",
                exc_info=True,
                extra={
                    "order_id": order.binance_order_id,
                    "error": str(e)
                }
            )

    def _monitor_positions(self) -> None:
        """Monitor open positions and handle state updates."""
        thread_id = f"{threading.current_thread().name}_{threading.get_ident()}"
        self.logger.info("Starting position monitoring", extra={"thread_id": thread_id})
        
        while self.should_run:
            try:
                with get_db() as db:
                    # Update system state
                    self.state_manager.update_state(websocket_status="MONITORING")
                    
                    # Check positions
                    self._check_position_durations(db)
                
                # Use shorter sleep interval for faster shutdown response
                for _ in range(int(POSITION_CHECK_INTERVAL / MONITOR_LOOP_INTERVAL)):
                    if not self.should_run:
                        break
                    time.sleep(MONITOR_LOOP_INTERVAL)
                    
            except Exception as e:
                if self.should_run:  # Only log if we're still supposed to be running
                    if thread_id in self.threads:
                        self.threads[thread_id].increment_errors()
                    
                    self.logger.error(
                        "Error in position monitoring",
                        exc_info=True,
                        extra={
                            "thread_id": thread_id,
                            "error": str(e),
                            "error_count": self.threads[thread_id].error_count if thread_id in self.threads else 0
                        }
                    )
                    # Update state with error
                    try:
                        self.state_manager.update_state(
                            websocket_status="ERROR",
                            last_error=str(e)
                        )
                    except Exception as state_error:
                        self.logger.error(
                            "Failed to update state after monitoring error",
                            exc_info=True,
                            extra={"error": str(state_error)}
                        )
                    time.sleep(MONITOR_LOOP_INTERVAL)  # Brief pause on error

        self.logger.info(
            "Position monitoring stopped",
            extra={"thread_id": thread_id}
        )

    def _check_position_durations(self, db):
        """Check position durations with proper error handling and state updates."""
        try:
            positions = self.get_open_positions()
            for position in positions:
                order_id = position['order_id']
                duration = position['duration_seconds']
                
                # Check if position exceeds duration threshold and hasn't alerted
                if (duration > POSITION_DURATION_ALERT_THRESHOLD and 
                    order_id not in self.position_alerts):
                    self.logger.warning(
                        "Position duration alert",
                        extra={
                            "order_id": order_id,
                            "symbol": position['symbol'],
                            "duration_hours": duration / 3600,
                            "quantity": position['quantity'],
                            "price": position['price']
                        }
                    )
                    self.position_alerts.add(order_id)
            
            # Cleanup alerts for closed positions
            open_order_ids = {p['order_id'] for p in positions}
            self.position_alerts = self.position_alerts & open_order_ids
            
            # Update system state with position information
            self.state_manager.update_state(
                open_positions=len(positions),
                oldest_position_age=max(
                    (p['duration_seconds'] for p in positions),
                    default=0
                )
            )
            
        except Exception as e:
            self.logger.error(
                "Error checking position durations",
                exc_info=True,
                extra={"error": str(e)}
            )
            raise

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

    def start_monitoring(self) -> None:
        """Start the order monitoring thread."""
        if self.should_run:
            self.logger.warning("Order monitoring already running")
            return
            
        self.should_run = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="OrderMonitorThread",
            daemon=True
        )
        self.monitor_thread.start()
        self.logger.info("Order monitoring started")

    def stop_monitoring(self) -> None:
        """Stop the order monitoring thread gracefully."""
        self.logger.info("Initiating order monitoring shutdown")
        self.shutdown_in_progress = True
        self.should_run = False
        
        # Wait for monitor thread to finish
        if hasattr(self, 'monitor_thread') and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=THREAD_SHUTDOWN_TIMEOUT)
            if self.monitor_thread.is_alive():
                self.logger.error("Monitor thread failed to shutdown gracefully")
                
        # Clean up any remaining threads
        for order_id, thread_info in list(self.threads.items()):
            if thread_info.thread.is_alive():
                self.logger.warning(
                    f"Force stopping thread for order {order_id}",
                    extra={"thread_name": thread_info.thread.name}
                )
                self._stop_monitoring_thread(order_id)
                
        self.logger.info("Order monitoring stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop that checks order status and manages threads."""
        while self.should_run:
            try:
                # Clean up completed threads
                self._cleanup_threads()
                
                # Check for orders that need monitoring
                with get_db() as db:
                    active_orders = db.query(Order).filter(
                        Order.status.in_(['NEW', 'PARTIALLY_FILLED'])
                    ).all()
                    
                    for order in active_orders:
                        if order.binance_order_id not in self.threads:
                            self._start_monitoring_thread(order)
                            
                # Update state manager
                if active_orders:
                    self.state_manager.update_state(
                        db,
                        last_check=datetime.utcnow(),
                        active_orders=len(active_orders)
                    )
                    
            except Exception as e:
                self.logger.error(
                    "Error in monitor loop",
                    exc_info=True,
                    extra={"error": str(e)}
                )
                
            time.sleep(MONITOR_LOOP_INTERVAL)

    def _start_monitoring_thread(self, order: Order) -> None:
        """Start a dedicated thread for monitoring a specific order."""
        if order.binance_order_id in self.threads:
            return
            
        thread = threading.Thread(
            target=self._monitor_order,
            args=(order,),
            name=f"OrderMonitor-{order.binance_order_id}",
            daemon=True
        )
        
        self.threads[order.binance_order_id] = ThreadInfo(
            thread=thread,
            start_time=datetime.utcnow(),
            last_update=datetime.utcnow(),
            order_id=order.binance_order_id
        )
        
        thread.start()
        self.logger.info(
            f"Started monitoring thread for order {order.binance_order_id}",
            extra={
                "order_id": order.binance_order_id,
                "thread_name": thread.name
            }
        )

    def _stop_monitoring_thread(self, order_id: str) -> None:
        """Stop monitoring a specific order thread."""
        if order_id not in self.threads:
            return
            
        thread_info = self.threads[order_id]
        if thread_info.thread.is_alive():
            # Signal thread to stop
            self.monitored_orders.pop(order_id, None)
            
            # Wait for thread to finish
            thread_info.thread.join(timeout=THREAD_SHUTDOWN_TIMEOUT)
            if thread_info.thread.is_alive():
                self.logger.error(
                    f"Thread for order {order_id} failed to stop gracefully",
                    extra={"thread_name": thread_info.thread.name}
                )
                
        del self.threads[order_id]
        self.logger.info(
            f"Stopped monitoring thread for order {order_id}",
            extra={"thread_name": thread_info.thread.name}
        )

    def _cleanup_threads(self) -> None:
        """Clean up completed or stale monitoring threads."""
        current_time = datetime.utcnow()
        for order_id, thread_info in list(self.threads.items()):
            if not thread_info.thread.is_alive():
                del self.threads[order_id]
                self.logger.info(
                    f"Cleaned up completed thread for order {order_id}",
                    extra={"thread_name": thread_info.thread.name}
                )
            elif (current_time - thread_info.last_update).total_seconds() > THREAD_TIMEOUT:
                self.logger.warning(
                    f"Thread for order {order_id} timed out",
                    extra={
                        "thread_name": thread_info.thread.name,
                        "duration": (current_time - thread_info.start_time).total_seconds()
                    }
                )
                self._stop_monitoring_thread(order_id)

    def _monitor_order(self, order: Order) -> None:
        """Monitor a specific order for updates and state changes."""
        while not self.shutdown_in_progress and order.binance_order_id in self.threads:
            try:
                # Get latest order status from Binance
                order_status = self.price_manager.get_order_status(
                    order.symbol,
                    order.binance_order_id
                )
                
                if order_status:
                    with get_db() as db:
                        db.begin_nested()  # Create savepoint
                        try:
                            # Update order status
                            order = db.query(Order).filter_by(
                                binance_order_id=order.binance_order_id
                            ).first()
                            
                            if not order:
                                self.logger.error(
                                    "Order not found in database",
                                    extra={"order_id": order.binance_order_id}
                                )
                                break
                                
                            # Track state transition
                            if order_status['status'] != order.status:
                                self._track_state_transition(order, order_status['status'])
                                
                            # Update order details
                            order.status = order_status['status']
                            order.filled_quantity = float(order_status['executedQty'])
                            order.last_update = datetime.utcnow()
                            
                            # Handle filled orders
                            if order.status == 'FILLED':
                                self._handle_filled_order(order)
                                break
                                
                            # Handle partially filled orders
                            elif order.status == 'PARTIALLY_FILLED':
                                self._handle_partial_fill(order)
                                
                            db.commit()
                            
                        except Exception as e:
                            db.rollback()
                            self.logger.error(
                                "Error updating order status",
                                exc_info=True,
                                extra={
                                    "order_id": order.binance_order_id,
                                    "error": str(e)
                                }
                            )
                            
                # Update thread info
                if order.binance_order_id in self.threads:
                    self.threads[order.binance_order_id].last_update = datetime.utcnow()
                    
            except Exception as e:
                self.logger.error(
                    "Error monitoring order",
                    exc_info=True,
                    extra={
                        "order_id": order.binance_order_id,
                        "error": str(e)
                    }
                )
                
            time.sleep(ORDER_CHECK_INTERVAL)
            
        self.logger.info(
            f"Stopped monitoring order {order.binance_order_id}",
            extra={"final_status": order.status if order else None}
        ) 

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an active order.
        
        Args:
            order_id: The Binance order ID to cancel
            
        Returns:
            bool: True if cancellation was successful, False otherwise
        """
        try:
            with get_db() as db:
                db.begin_nested()  # Create savepoint
                try:
                    # Get order from database
                    order = db.query(Order).filter_by(
                        binance_order_id=order_id
                    ).first()
                    
                    if not order:
                        self.logger.error(
                            "Order not found for cancellation",
                            extra={"order_id": order_id}
                        )
                        return False
                        
                    # Only cancel active orders
                    if order.status not in ['NEW', 'PARTIALLY_FILLED']:
                        self.logger.warning(
                            "Cannot cancel non-active order",
                            extra={
                                "order_id": order_id,
                                "status": order.status
                            }
                        )
                        return False
                        
                    # Cancel on exchange
                    response = self.price_manager.cancel_order(
                        symbol=order.symbol,
                        order_id=order_id
                    )
                    
                    if response and response.get('status') == 'CANCELED':
                        # Update order status
                        order.status = 'CANCELED'
                        order.last_update = datetime.utcnow()
                        
                        # Track state transition
                        self._track_state_transition(order, 'CANCELED')
                        
                        # Stop monitoring thread
                        self._stop_monitoring_thread(order_id)
                        
                        db.commit()
                        self.logger.info(
                            "Order cancelled successfully",
                            extra={
                                "order_id": order_id,
                                "symbol": order.symbol,
                                "side": order.side
                            }
                        )
                        return True
                        
                    else:
                        self.logger.error(
                            "Failed to cancel order on exchange",
                            extra={
                                "order_id": order_id,
                                "response": response
                            }
                        )
                        return False
                        
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error cancelling order",
                        exc_info=True,
                        extra={
                            "order_id": order_id,
                            "error": str(e)
                        }
                    )
                    return False
                    
        except Exception as e:
            self.logger.error(
                "Database error cancelling order",
                exc_info=True,
                extra={
                    "order_id": order_id,
                    "error": str(e)
                }
            )
            return False

    def cleanup_stale_orders(self, max_age_hours: int = 24) -> None:
        """
        Cancel orders that have been open for too long.
        
        Args:
            max_age_hours: Maximum age in hours before an order is considered stale
        """
        try:
            with get_db() as db:
                # Find stale orders
                cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
                stale_orders = db.query(Order).filter(
                    Order.status.in_(['NEW', 'PARTIALLY_FILLED']),
                    Order.created_at < cutoff_time
                ).all()
                
                for order in stale_orders:
                    self.logger.warning(
                        "Found stale order",
                        extra={
                            "order_id": order.binance_order_id,
                            "age_hours": (datetime.utcnow() - order.created_at).total_seconds() / 3600,
                            "status": order.status
                        }
                    )
                    
                    # Attempt to cancel
                    if self.cancel_order(order.binance_order_id):
                        self.logger.info(
                            "Cancelled stale order",
                            extra={
                                "order_id": order.binance_order_id,
                                "age_hours": (datetime.utcnow() - order.created_at).total_seconds() / 3600
                            }
                        )
                    else:
                        self.logger.error(
                            "Failed to cancel stale order",
                            extra={"order_id": order.binance_order_id}
                        )
                        
        except Exception as e:
            self.logger.error(
                "Error cleaning up stale orders",
                exc_info=True,
                extra={"error": str(e)}
            )

    def cleanup_completed_orders(self, max_age_days: int = 7) -> None:
        """
        Archive or delete old completed orders from the database.
        
        Args:
            max_age_days: Maximum age in days before a completed order is archived
        """
        try:
            with get_db() as db:
                db.begin_nested()  # Create savepoint
                try:
                    # Find old completed orders
                    cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
                    completed_orders = db.query(Order).filter(
                        Order.status.in_(['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']),
                        Order.last_update < cutoff_time
                    ).all()
                    
                    for order in completed_orders:
                        # Archive order details if needed
                        self._archive_order(order)
                        
                        # Delete from active orders table
                        db.delete(order)
                        
                        self.logger.info(
                            "Archived and deleted old order",
                            extra={
                                "order_id": order.binance_order_id,
                                "status": order.status,
                                "age_days": (datetime.utcnow() - order.created_at).total_seconds() / 86400
                            }
                        )
                        
                    db.commit()
                    
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error archiving completed orders",
                        exc_info=True,
                        extra={"error": str(e)}
                    )
                    
        except Exception as e:
            self.logger.error(
                "Database error cleaning up completed orders",
                exc_info=True,
                extra={"error": str(e)}
            )

    def _archive_order(self, order: Order) -> None:
        """
        Archive order details for historical record keeping.
        
        Args:
            order: The Order object to archive
        """
        try:
            # Create archive record
            archive = OrderArchive(
                binance_order_id=order.binance_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                filled_quantity=order.filled_quantity,
                status=order.status,
                parent_order_id=order.parent_order_id,
                is_partial=order.is_partial,
                created_at=order.created_at,
                last_update=order.last_update,
                archived_at=datetime.utcnow()
            )
            
            with get_db() as db:
                db.begin_nested()  # Create savepoint
                try:
                    db.add(archive)
                    db.commit()
                    
                except Exception as e:
                    db.rollback()
                    self.logger.error(
                        "Error creating archive record",
                        exc_info=True,
                        extra={
                            "order_id": order.binance_order_id,
                            "error": str(e)
                        }
                    )
                    
        except Exception as e:
            self.logger.error(
                "Database error archiving order",
                exc_info=True,
                extra={
                    "order_id": order.binance_order_id,
                    "error": str(e)
                }
            ) 