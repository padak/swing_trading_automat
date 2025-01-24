"""
SQLAlchemy models for the trading system database.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    ForeignKey, Text, create_engine
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column,
    relationship
)

from src.config.settings import DB_PATH

class OrderStatus(str, Enum):
    """Order status values according to design specification."""
    OPEN = "OPEN"               # Initial state when order is placed
    FILLED = "FILLED"           # Order has been completely filled
    CANCELLED = "CANCELLED"     # Order was cancelled
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # Order is partially filled
    REJECTED = "REJECTED"       # Order was rejected by exchange
    EXPIRED = "EXPIRED"         # Order expired without being filled

class SystemStatus(str, Enum):
    """Enum for system statuses."""
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    RECONNECTING = "RECONNECTING"
    INITIALIZING = "INITIALIZING"
    MAINTENANCE = "MAINTENANCE"

# Create the SQLAlchemy base class
class Base(DeclarativeBase):
    pass

class Order(Base):
    """Model representing orders in the system."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    binance_order_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # 'BUY' or 'SELL'
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    parent_order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('orders.id'), nullable=True)
    hold_duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Duration in seconds
    fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fill_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fill_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Add order_id property that maps to binance_order_id
    @property
    def order_id(self) -> str:
        """Maintain compatibility with code expecting order_id."""
        return self.binance_order_id

    # Fix self-referential relationship
    parent_order = relationship(
        "Order",
        remote_side=[id],
        back_populates="child_orders"
    )
    child_orders = relationship(
        "Order",
        back_populates="parent_order"
    )
    
    # Other relationships
    buy_trades = relationship("TradePair", backref="buy_order", foreign_keys="TradePair.buy_order_id")
    sell_trades = relationship("TradePair", backref="sell_order", foreign_keys="TradePair.sell_order_id")

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, binance_id={self.binance_order_id}, side={self.side}, status={self.status})>"

class TradePair(Base):
    """Model representing pairs of BUY and SELL orders."""
    __tablename__ = "trade_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    buy_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('orders.id'), nullable=False)
    sell_order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('orders.id'), nullable=True)
    target_profit_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'WAITING_FOR_PROFIT', 'SELL_PLACED', 'COMPLETED'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    original_buy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('orders.id'), nullable=True)

    def __repr__(self) -> str:
        return f"<TradePair(id={self.id}, status={self.status})>"

class SystemState(Base):
    """Model for tracking system state and recovery information."""
    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_processed_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    websocket_status: Mapped[str] = mapped_column(String(20), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_reconciliation_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reconnection_attempts: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<SystemState(id={self.id}, websocket_status={self.websocket_status})>"

# Database initialization function
def init_db() -> None:
    """Initialize the database by creating all tables."""
    engine = create_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(engine) 