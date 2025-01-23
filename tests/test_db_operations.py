"""
Unit tests for database operations.
"""
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from src.db.models import Base, Order, OrderStatus
from src.db.operations import (
    init_db,
    create_order,
    update_order,
    get_order_by_id,
    get_orders_by_status,
    get_open_orders,
    get_related_orders,
    get_order_chain,
    get_position_summary
)

# Use in-memory SQLite for testing
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(autouse=True)
def setup_database():
    """Create test database and tables."""
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Get database session."""
    engine = create_engine(TEST_DB_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_create_order(db: Session):
    """Test order creation."""
    order = create_order(
        db,
        order_id="test123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.NEW
    )
    
    assert order.order_id == "test123"
    assert order.symbol == "BTCUSDT"
    assert order.side == "BUY"
    assert order.quantity == 1.0
    assert order.price == 50000.0
    assert order.status == OrderStatus.NEW
    assert order.created_at is not None

def test_create_duplicate_order(db: Session):
    """Test handling of duplicate order IDs."""
    create_order(
        db,
        order_id="test123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.NEW
    )
    
    with pytest.raises(IntegrityError):
        create_order(
            db,
            order_id="test123",
            symbol="BTCUSDT",
            side="BUY",
            quantity=1.0,
            price=50000.0,
            status=OrderStatus.NEW
        )

def test_update_order(db: Session):
    """Test order updates."""
    order = create_order(
        db,
        order_id="test123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.NEW
    )
    
    # Update status
    updated = update_order(
        db,
        order_id="test123",
        status=OrderStatus.PARTIALLY_FILLED,
        filled_quantity=0.5,
        average_price=50100.0
    )
    
    assert updated is not None
    assert updated.status == OrderStatus.PARTIALLY_FILLED
    assert updated.filled_quantity == 0.5
    assert updated.average_price == 50100.0
    assert updated.status_updated_at is not None
    assert updated.last_fill_time is not None

def test_get_orders_by_status(db: Session):
    """Test order retrieval by status."""
    # Create test orders
    create_order(
        db,
        order_id="new1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.NEW
    )
    create_order(
        db,
        order_id="new2",
        symbol="ETHUSDT",
        side="BUY",
        quantity=1.0,
        price=3000.0,
        status=OrderStatus.NEW
    )
    create_order(
        db,
        order_id="filled1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.FILLED
    )
    
    # Test filtering
    new_orders = get_orders_by_status(db, [OrderStatus.NEW])
    assert len(new_orders) == 2
    
    btc_orders = get_orders_by_status(
        db,
        [OrderStatus.NEW, OrderStatus.FILLED],
        symbol="BTCUSDT"
    )
    assert len(btc_orders) == 2
    
    buy_orders = get_orders_by_status(
        db,
        [OrderStatus.NEW],
        side="BUY"
    )
    assert len(buy_orders) == 2

def test_get_open_orders(db: Session):
    """Test open order retrieval."""
    # Create test orders
    create_order(
        db,
        order_id="new1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.NEW
    )
    create_order(
        db,
        order_id="partial1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.PARTIALLY_FILLED
    )
    create_order(
        db,
        order_id="filled1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.FILLED
    )
    
    open_orders = get_open_orders(db)
    assert len(open_orders) == 2
    assert all(o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED] for o in open_orders)

def test_get_related_orders(db: Session):
    """Test related order retrieval."""
    # Create parent order
    parent = create_order(
        db,
        order_id="parent123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.PARTIALLY_FILLED
    )
    
    # Create partial fill
    create_order(
        db,
        order_id="partial1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.5,
        price=50000.0,
        status=OrderStatus.FILLED,
        order_type="PARTIAL_FILL",
        related_order_id=parent.order_id
    )
    
    # Create sell order
    create_order(
        db,
        order_id="sell1",
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.5,
        price=51000.0,
        status=OrderStatus.NEW,
        related_order_id=parent.order_id
    )
    
    # Test retrieval
    related = get_related_orders(db, parent.order_id)
    assert len(related) == 3  # Parent + partial + sell
    
    # Test without parent
    related_no_parent = get_related_orders(db, parent.order_id, include_parent=False)
    assert len(related_no_parent) == 2  # Just partial + sell

def test_get_order_chain(db: Session):
    """Test order chain retrieval."""
    # Create parent order
    parent = create_order(
        db,
        order_id="parent123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.PARTIALLY_FILLED,
        created_at=datetime.utcnow()
    )
    
    # Create first partial fill and sell
    partial1 = create_order(
        db,
        order_id="partial1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.5,
        price=50000.0,
        status=OrderStatus.FILLED,
        order_type="PARTIAL_FILL",
        related_order_id=parent.order_id,
        created_at=datetime.utcnow() + timedelta(minutes=1)
    )
    
    sell1 = create_order(
        db,
        order_id="sell1",
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.5,
        price=51000.0,
        status=OrderStatus.NEW,
        related_order_id=partial1.order_id,
        created_at=datetime.utcnow() + timedelta(minutes=2)
    )
    
    # Create second partial fill and sell
    partial2 = create_order(
        db,
        order_id="partial2",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.5,
        price=50100.0,
        status=OrderStatus.FILLED,
        order_type="PARTIAL_FILL",
        related_order_id=parent.order_id,
        created_at=datetime.utcnow() + timedelta(minutes=3)
    )
    
    sell2 = create_order(
        db,
        order_id="sell2",
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.5,
        price=51100.0,
        status=OrderStatus.NEW,
        related_order_id=partial2.order_id,
        created_at=datetime.utcnow() + timedelta(minutes=4)
    )
    
    # Test chain retrieval
    chain = get_order_chain(db, parent.order_id)
    assert len(chain) == 5
    
    # Verify chronological order
    for i in range(len(chain) - 1):
        assert chain[i].created_at <= chain[i + 1].created_at

def test_get_position_summary(db: Session):
    """Test position summary calculation."""
    # Create parent order
    parent = create_order(
        db,
        order_id="parent123",
        symbol="BTCUSDT",
        side="BUY",
        quantity=1.0,
        price=50000.0,
        status=OrderStatus.PARTIALLY_FILLED,
        filled_quantity=1.0,
        average_price=50000.0
    )
    
    # Create first partial fill and sell
    partial1 = create_order(
        db,
        order_id="partial1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.5,
        price=50000.0,
        status=OrderStatus.FILLED,
        order_type="PARTIAL_FILL",
        related_order_id=parent.order_id,
        filled_quantity=0.5,
        average_price=50000.0
    )
    
    sell1 = create_order(
        db,
        order_id="sell1",
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.5,
        price=51000.0,
        status=OrderStatus.FILLED,
        related_order_id=partial1.order_id,
        filled_quantity=0.5,
        average_price=51000.0
    )
    
    # Create second partial fill and sell
    partial2 = create_order(
        db,
        order_id="partial2",
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.5,
        price=50100.0,
        status=OrderStatus.FILLED,
        order_type="PARTIAL_FILL",
        related_order_id=parent.order_id,
        filled_quantity=0.5,
        average_price=50100.0
    )
    
    sell2 = create_order(
        db,
        order_id="sell2",
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.5,
        price=51100.0,
        status=OrderStatus.NEW,
        related_order_id=partial2.order_id
    )
    
    # Test summary calculation
    summary = get_position_summary(db, parent.order_id)
    assert summary is not None
    
    # Verify calculations
    assert summary['total_bought'] == 2.0  # Parent + 2 partials
    assert summary['total_sold'] == 0.5  # One sell filled
    assert summary['remaining_quantity'] == 1.5  # 2.0 - 0.5
    assert abs(summary['avg_buy_price'] - 50033.33) < 0.01  # (50000 + 50000 + 50100) / 3
    assert summary['avg_sell_price'] == 51000.0  # Only one sell filled
    
    # Verify profit calculation
    expected_profit = (0.5 * 51000.0) - (0.5 * 50033.33)
    assert abs(summary['realized_profit'] - expected_profit) < 0.01
    
    # Verify order lists
    assert len(summary['buy_orders']) == 3
    assert len(summary['sell_orders']) == 2
    assert summary['has_partial_fills'] is True

@pytest.mark.performance
def test_database_performance(db: Session, benchmark):
    """Test database operation performance."""
    def create_and_update_orders():
        """Create and update multiple orders."""
        orders = []
        for i in range(100):
            order = create_order(
                db,
                order_id=f"perf{i}",
                symbol="BTCUSDT",
                side="BUY",
                quantity=1.0,
                price=50000.0,
                status=OrderStatus.NEW
            )
            orders.append(order)
        
        for order in orders:
            update_order(
                db,
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                filled_quantity=1.0,
                average_price=50100.0
            )
            get_position_summary(db, order.order_id)
    
    # Run benchmark
    result = benchmark(create_and_update_orders)
    
    # Assert reasonable performance
    assert result.stats.stats.mean < 1.0  # Under 1 second for 100 orders 