"""
Unit tests for database operations.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.operations import (
    create_order,
    get_order_by_id,
    create_trade_pair,
    get_system_state,
    update_system_state
)

# Use in-memory SQLite for testing
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    """Create a new database session for testing."""
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)

def test_create_order(db_session: Session):
    """Test creating a new order."""
    order = create_order(
        db_session,
        binance_order_id="test123",
        symbol="TRUMPUSDC",
        side="BUY",
        price=1.2345,
        quantity=10.0
    )
    
    assert order.id is not None
    assert order.binance_order_id == "test123"
    assert order.status == "OPEN"
    
    # Verify we can retrieve it
    retrieved = get_order_by_id(db_session, order.id)
    assert retrieved is not None
    assert retrieved.binance_order_id == order.binance_order_id

def test_create_trade_pair(db_session: Session):
    """Test creating a trade pair."""
    # First create an order
    order = create_order(
        db_session,
        binance_order_id="test123",
        symbol="TRUMPUSDC",
        side="BUY",
        price=1.2345,
        quantity=10.0
    )
    
    # Create trade pair
    trade_pair = create_trade_pair(
        db_session,
        buy_order_id=order.id,
        target_profit_price=1.2400
    )
    
    assert trade_pair.id is not None
    assert trade_pair.buy_order_id == order.id
    assert trade_pair.status == "WAITING_FOR_PROFIT"

def test_system_state(db_session: Session):
    """Test system state operations."""
    # Get initial state (should create it)
    state = get_system_state(db_session)
    assert state is not None
    assert state.id is not None
    
    # Update state
    updated = update_system_state(
        db_session,
        websocket_status="CONNECTED",
        last_error=None,
        reconnection_attempts=0
    )
    
    assert updated.websocket_status == "CONNECTED"
    assert updated.reconnection_attempts == 0
    assert updated.last_processed_time is not None 