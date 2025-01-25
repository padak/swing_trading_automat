"""
Database operations for the trading system.
Provides CRUD operations and session management.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional, List, Dict, Any, Tuple
from decimal import Decimal

from sqlalchemy import create_engine, select, or_, and_, desc, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from src.config.logging_config import get_logger
from src.config.settings import DB_PATH
from .models import Base, Order, OrderStatus, SystemState

logger = get_logger(__name__)

# Create database engine
engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def initialize_database():
    """Initialize database schema."""
    Base.metadata.create_all(bind=engine)
    logger.info("Initialized database schema")

@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Ensures proper handling of sessions and rollback on errors.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Database error", error=str(e))
        raise
    finally:
        db.close()

def create_order(
    db: Session,
    order_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    status: OrderStatus,
    order_type: str = 'LIMIT',
    related_order_id: Optional[str] = None,
    filled_quantity: Optional[float] = None,
    average_price: Optional[float] = None
) -> Order:
    """
    Create a new order record.
    
    Args:
        db: Database session
        order_id: Unique order identifier
        symbol: Trading pair symbol
        side: BUY or SELL
        quantity: Order quantity
        price: Order price
        status: Order status
        order_type: Order type (LIMIT, MARKET, PARTIAL_FILL)
        related_order_id: ID of related order (for partial fills/sells)
        filled_quantity: Amount filled so far
        average_price: Average fill price
        
    Returns:
        Order: Created order record
        
    Raises:
        IntegrityError: If order_id already exists
    """
    try:
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=status,
            order_type=order_type,
            related_order_id=related_order_id,
            filled_quantity=filled_quantity or 0.0,
            average_price=average_price or price,
            created_at=datetime.utcnow()
        )
        db.add(order)
        db.flush()
        
        logger.info(
            "Created order",
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=status.value,
            order_type=order_type
        )
        return order
        
    except IntegrityError as e:
        logger.error(
            "Failed to create order - duplicate order_id",
            order_id=order_id,
            error=str(e)
        )
        raise

def update_order(
    db: Session,
    order_id: str,
    status: Optional[OrderStatus] = None,
    filled_quantity: Optional[float] = None,
    average_price: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[Order]:
    """
    Update an order's status and fill information.
    
    Args:
        db: Database session
        order_id: Order to update
        status: New order status
        filled_quantity: Updated fill quantity
        average_price: Updated average fill price
        metadata: Additional data to store
        
    Returns:
        Optional[Order]: Updated order if found
    """
    order = get_order_by_id(db, order_id)
    if not order:
        logger.error("Order not found for update", order_id=order_id)
        return None
    
    # Track changes for logging
    changes = {}
    
    if status is not None and status != order.status:
        changes['status'] = (order.status.value, status.value)
        order.status = status
        order.status_updated_at = datetime.utcnow()
    
    if filled_quantity is not None and filled_quantity != order.filled_quantity:
        changes['filled_quantity'] = (order.filled_quantity, filled_quantity)
        order.filled_quantity = filled_quantity
        order.last_fill_time = datetime.utcnow()
    
    if average_price is not None and average_price != order.average_price:
        changes['average_price'] = (order.average_price, average_price)
        order.average_price = average_price
    
    if metadata:
        order.metadata = {**(order.metadata or {}), **metadata}
        changes['metadata'] = metadata
    
    if changes:
        logger.info(
            "Updated order",
            order_id=order_id,
            changes=changes
        )
    
    return order

def get_order_by_id(db: Session, order_id: str) -> Optional[Order]:
    """Get an order by its Binance order ID."""
    return db.scalar(
        select(Order).where(Order.binance_order_id == str(order_id))
    )

def get_orders_by_status(
    db: Session,
    status: List[OrderStatus],
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Order]:
    """
    Get orders by status with optional filtering.
    
    Args:
        db: Database session
        status: List of statuses to include
        symbol: Optional symbol filter
        side: Optional side filter (BUY/SELL)
        limit: Optional limit on number of orders
        
    Returns:
        List[Order]: Matching orders
    """
    query = select(Order).where(Order.status.in_(status))
    
    if symbol:
        query = query.where(Order.symbol == symbol)
    if side:
        query = query.where(Order.side == side)
    
    query = query.order_by(desc(Order.created_at))
    
    if limit:
        query = query.limit(limit)
    
    return list(db.scalars(query))

def get_open_orders(
    db: Session,
    symbol: Optional[str] = None,
    side: Optional[str] = None
) -> List[Order]:
    """
    Get all open orders (NEW or PARTIALLY_FILLED).
    
    Args:
        db: Database session
        symbol: Optional symbol filter
        side: Optional side filter
        
    Returns:
        List[Order]: Open orders
    """
    return get_orders_by_status(
        db,
        [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED],
        symbol,
        side
    )

def get_related_orders(
    db: Session,
    order_id: str,
    include_parent: bool = True
) -> List[Order]:
    """
    Get all orders related to the given order ID.
    
    Args:
        db: Database session
        order_id: Order ID to find relations for
        include_parent: Whether to include the parent order
        
    Returns:
        List[Order]: Related orders
    """
    conditions = [Order.related_order_id == order_id]
    if include_parent:
        conditions.append(Order.order_id == order_id)
    
    return list(db.scalars(
        select(Order).where(or_(*conditions))
    ))

def get_order_chain(
    db: Session,
    order_id: str
) -> List[Order]:
    """
    Get the complete chain of related orders.
    Includes the original order, all partial fills, and all sell orders.
    Orders are returned in chronological order.
    
    Args:
        db: Database session
        order_id: Starting order ID
        
    Returns:
        List[Order]: Chain of related orders
    """
    # Get the original order and its direct relations
    orders = get_related_orders(db, order_id)
    
    # Get any orders related to the related orders
    related_ids = {o.order_id for o in orders} - {order_id}
    while related_ids:
        new_related = []
        for related_id in related_ids:
            new_related.extend(get_related_orders(db, related_id, False))
        
        if not new_related:
            break
            
        orders.extend(new_related)
        related_ids = {o.order_id for o in new_related}
    
    # Sort by creation time
    return sorted(orders, key=lambda o: o.created_at or datetime.max)

def get_position_summary(
    db: Session,
    order_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a summary of a position including all related orders.
    
    Args:
        db: Database session
        order_id: Order ID to summarize
        
    Returns:
        Optional[Dict[str, Any]]: Position summary or None if not found
    """
    order = get_order_by_id(db, order_id)
    if not order:
        return None
    
    chain = get_order_chain(db, order_id)
    
    # Calculate totals
    total_bought = sum(
        o.filled_quantity or 0
        for o in chain
        if o.side == 'BUY' and o.status in [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED]
    )
    
    total_sold = sum(
        o.filled_quantity or 0
        for o in chain
        if o.side == 'SELL' and o.status == OrderStatus.FILLED
    )
    
    # Calculate average prices
    buy_value = sum(
        (o.filled_quantity or 0) * (o.average_price or o.price)
        for o in chain
        if o.side == 'BUY' and o.status in [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED]
    )
    
    sell_value = sum(
        (o.filled_quantity or 0) * (o.average_price or o.price)
        for o in chain
        if o.side == 'SELL' and o.status == OrderStatus.FILLED
    )
    
    avg_buy_price = buy_value / total_bought if total_bought > 0 else 0
    avg_sell_price = sell_value / total_sold if total_sold > 0 else 0
    
    return {
        'order_id': order_id,
        'symbol': order.symbol,
        'total_quantity': order.quantity,
        'total_bought': total_bought,
        'total_sold': total_sold,
        'remaining_quantity': total_bought - total_sold,
        'avg_buy_price': avg_buy_price,
        'avg_sell_price': avg_sell_price,
        'realized_profit': sell_value - (total_sold * avg_buy_price),
        'status': order.status.value,
        'created_at': order.created_at,
        'last_updated': max(o.status_updated_at or datetime.min for o in chain),
        'has_partial_fills': any(o.order_type == 'PARTIAL_FILL' for o in chain),
        'buy_orders': [
            {
                'order_id': o.order_id,
                'quantity': o.quantity,
                'filled_quantity': o.filled_quantity,
                'price': o.price,
                'average_price': o.average_price,
                'status': o.status.value,
                'type': o.order_type
            }
            for o in chain
            if o.side == 'BUY'
        ],
        'sell_orders': [
            {
                'order_id': o.order_id,
                'quantity': o.quantity,
                'filled_quantity': o.filled_quantity,
                'price': o.price,
                'average_price': o.average_price,
                'status': o.status.value
            }
            for o in chain
            if o.side == 'SELL'
        ]
    }

def get_system_state(db: Session) -> SystemState:
    """Get or create the system state record."""
    state = db.scalar(select(SystemState))
    if not state:
        state = SystemState()
        db.add(state)
        db.flush()
        logger.info("Created system state record")
    return state

def update_system_state(
    db: Session,
    websocket_status: Optional[str] = None,
    last_error: Optional[str] = None,
    last_order_update: Optional[datetime] = None,
    last_status_change: Optional[str] = None,
    order_id: Optional[str] = None,
    reconnection_attempts: Optional[int] = None,
    open_positions: Optional[int] = None,
    oldest_position_age: Optional[float] = None
) -> SystemState:
    """
    Update the system state according to design specification.
    
    Args:
        db: Database session
        websocket_status: Current WebSocket connection status
        last_error: Last error message if any
        last_order_update: Timestamp of last order update
        last_status_change: Last order status change
        order_id: ID of the order being updated
        reconnection_attempts: Number of reconnection attempts
        open_positions: Number of open positions
        oldest_position_age: Age of oldest position in seconds
        
    Returns:
        SystemState: Updated system state
    """
    state = get_system_state(db)
    
    # Keep track of old values to detect true changes
    old_values = {
        'websocket_status': state.websocket_status,
        'last_error': state.last_error,
        'last_order_update': state.last_order_update,
        'last_status_change': state.last_status_change,
        'last_order_id': state.last_order_id,
        'reconnection_attempts': state.reconnection_attempts,
        'open_positions': state.open_positions,
        'oldest_position_age': state.oldest_position_age,
    }

    if websocket_status is not None:
        state.websocket_status = websocket_status
    if last_error is not None:
        state.last_error = last_error
    if last_order_update is not None:
        state.last_order_update = last_order_update
    if last_status_change is not None:
        state.last_status_change = last_status_change
    if order_id is not None:
        state.last_order_id = order_id
    if reconnection_attempts is not None:
        state.reconnection_attempts = reconnection_attempts
    if open_positions is not None:
        state.open_positions = open_positions
    if oldest_position_age is not None:
        state.oldest_position_age = oldest_position_age

    state.last_processed_time = datetime.utcnow()

    # Compare old vs new to see if anything changed
    changed = (
        state.websocket_status != old_values['websocket_status'] or
        state.last_error != old_values['last_error'] or
        state.last_order_update != old_values['last_order_update'] or
        state.last_status_change != old_values['last_status_change'] or
        state.last_order_id != old_values['last_order_id'] or
        state.reconnection_attempts != old_values['reconnection_attempts'] or
        state.open_positions != old_values['open_positions'] or
        state.oldest_position_age != old_values['oldest_position_age']
    )

    if changed:
        logger.info(
            "Updated system state",
            websocket_status=state.websocket_status,
            last_error=state.last_error,
            last_order_update=state.last_order_update.isoformat() if state.last_order_update else None,
            last_status_change=state.last_status_change,
            order_id=state.last_order_id,
            reconnection_attempts=state.reconnection_attempts,
            open_positions=state.open_positions,
            oldest_position_age=state.oldest_position_age
        )

    return state 