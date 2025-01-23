"""
Database operations for the trading system.
Provides CRUD operations and session management.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional, List

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.config.logging_config import get_logger
from src.config.settings import DB_PATH
from .models import Base, Order, TradePair, SystemState

logger = get_logger(__name__)

# Create database engine
engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

# Order Operations
def create_order(
    db: Session,
    binance_order_id: str,
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    parent_order_id: Optional[int] = None
) -> Order:
    """Create a new order record."""
    order = Order(
        binance_order_id=binance_order_id,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        status="OPEN",
        parent_order_id=parent_order_id
    )
    db.add(order)
    db.flush()  # Get the ID without committing
    logger.info("Created order", order_id=order.id, binance_id=binance_order_id)
    return order

def get_order_by_id(db: Session, order_id: int) -> Optional[Order]:
    """Get an order by its ID."""
    return db.get(Order, order_id)

def get_order_by_binance_id(db: Session, binance_id: str) -> Optional[Order]:
    """Get an order by its Binance order ID."""
    return db.scalar(select(Order).where(Order.binance_order_id == binance_id))

def update_order_status(
    db: Session,
    order_id: int,
    status: str,
    fill_price: Optional[float] = None,
    fill_quantity: Optional[float] = None
) -> Optional[Order]:
    """Update an order's status and fill information."""
    order = get_order_by_id(db, order_id)
    if order:
        order.status = status
        if fill_price is not None:
            order.fill_price = fill_price
        if fill_quantity is not None:
            order.fill_quantity = fill_quantity
        if status == "FILLED":
            order.fill_time = datetime.utcnow()
        logger.info("Updated order status", order_id=order_id, status=status)
    return order

def get_open_orders(db: Session) -> List[Order]:
    """Get all open orders."""
    return list(db.scalars(select(Order).where(Order.status == "OPEN")))

# Trade Pair Operations
def create_trade_pair(
    db: Session,
    buy_order_id: int,
    target_profit_price: float,
    original_buy_id: Optional[int] = None
) -> TradePair:
    """Create a new trade pair record."""
    trade_pair = TradePair(
        buy_order_id=buy_order_id,
        target_profit_price=target_profit_price,
        status="WAITING_FOR_PROFIT",
        original_buy_id=original_buy_id
    )
    db.add(trade_pair)
    db.flush()
    logger.info("Created trade pair", trade_pair_id=trade_pair.id)
    return trade_pair

def update_trade_pair(
    db: Session,
    trade_pair_id: int,
    sell_order_id: Optional[int] = None,
    status: Optional[str] = None
) -> Optional[TradePair]:
    """Update a trade pair with sell order information."""
    trade_pair = db.get(TradePair, trade_pair_id)
    if trade_pair:
        if sell_order_id is not None:
            trade_pair.sell_order_id = sell_order_id
        if status is not None:
            trade_pair.status = status
        logger.info("Updated trade pair", trade_pair_id=trade_pair_id, status=status)
    return trade_pair

def get_active_trade_pairs(db: Session) -> List[TradePair]:
    """Get all trade pairs that are not completed."""
    return list(db.scalars(
        select(TradePair).where(TradePair.status != "COMPLETED")
    ))

# System State Operations
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
    reconnection_attempts: Optional[int] = None
) -> SystemState:
    """Update the system state."""
    state = get_system_state(db)
    if websocket_status is not None:
        state.websocket_status = websocket_status
    if last_error is not None:
        state.last_error = last_error
    if reconnection_attempts is not None:
        state.reconnection_attempts = reconnection_attempts
    state.last_processed_time = datetime.utcnow()
    logger.info("Updated system state", websocket_status=websocket_status)
    return state

def record_reconciliation(db: Session) -> None:
    """Record a successful state reconciliation."""
    state = get_system_state(db)
    state.last_reconciliation_time = datetime.utcnow()
    logger.info("Recorded state reconciliation") 