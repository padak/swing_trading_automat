"""Performance tests for critical system operations."""
import time
import pytest
import psutil
import threading
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
import memory_profiler

from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager
from src.db.models import Order, OrderStatus
from src.db.operations import get_db, create_order, get_open_orders
from src.config.settings import TRADING_SYMBOL

def measure_time(func):
    """Decorator to measure function execution time."""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} took {end - start:.4f} seconds")
        return result
    return wrapper

def measure_memory(func):
    """Decorator to measure memory usage."""
    def wrapper(*args, **kwargs):
        process = psutil.Process()
        mem_before = process.memory_info().rss / 1024 / 1024  # MB
        result = func(*args, **kwargs)
        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        print(f"{func.__name__} memory usage: {mem_after - mem_before:.2f} MB")
        return result
    return wrapper

@pytest.fixture
def trading_system():
    """Set up complete trading system for performance testing."""
    price_manager = PriceManager()
    order_manager = OrderManager(price_manager)
    state_manager = StateManager(price_manager, order_manager)
    
    yield {
        'price_manager': price_manager,
        'order_manager': order_manager,
        'state_manager': state_manager
    }
    
    state_manager.stop()
    price_manager.stop()

def test_websocket_connection_performance():
    """Test WebSocket connection and reconnection performance."""
    price_manager = PriceManager()
    
    # Measure initial connection time
    start = time.perf_counter()
    price_manager.start()
    end = time.perf_counter()
    initial_connect_time = end - start
    
    # Test reconnection performance
    reconnect_times = []
    for _ in range(5):
        price_manager._handle_close(None)
        start = time.perf_counter()
        price_manager.connect()
        end = time.perf_counter()
        reconnect_times.append(end - start)
    
    avg_reconnect_time = sum(reconnect_times) / len(reconnect_times)
    
    print(f"Initial connection time: {initial_connect_time:.4f}s")
    print(f"Average reconnection time: {avg_reconnect_time:.4f}s")
    
    # Cleanup
    price_manager.stop()
    
    # Performance assertions
    assert initial_connect_time < 1.0, "Initial connection too slow"
    assert avg_reconnect_time < 0.5, "Reconnection too slow"

@measure_time
@measure_memory
def test_price_update_throughput():
    """Test system's ability to handle high-frequency price updates."""
    price_manager = PriceManager()
    updates_processed = 0
    
    def count_update(price):
        nonlocal updates_processed
        updates_processed += 1
    
    price_manager.register_price_callback(count_update)
    
    # Generate 1000 price updates
    start = time.perf_counter()
    for i in range(1000):
        price_manager._handle_trade_message(None, {
            'e': 'trade',
            'E': int(time.time() * 1000),
            'p': str(1.0 + i/10000),
            'q': '100.0'
        })
    end = time.perf_counter()
    
    processing_time = end - start
    updates_per_second = 1000 / processing_time
    
    print(f"Processed {updates_per_second:.2f} updates per second")
    assert updates_per_second > 1000, "Price update processing too slow"
    
    # Cleanup
    price_manager.stop()

@measure_time
@measure_memory
def test_database_performance():
    """Test database operation performance."""
    # Test write performance
    start = time.perf_counter()
    orders_created = 0
    
    with get_db() as db:
        for i in range(100):
            order = create_order(
                db,
                order_id=f'perf_test_{i}',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            orders_created += 1
    
    write_time = time.perf_counter() - start
    writes_per_second = orders_created / write_time
    
    # Test read performance
    start = time.perf_counter()
    reads = 0
    
    with get_db() as db:
        for _ in range(100):
            orders = get_open_orders(db)
            reads += 1
    
    read_time = time.perf_counter() - start
    reads_per_second = reads / read_time
    
    print(f"Database writes per second: {writes_per_second:.2f}")
    print(f"Database reads per second: {reads_per_second:.2f}")
    
    assert writes_per_second > 50, "Database write performance too slow"
    assert reads_per_second > 100, "Database read performance too slow"

@measure_time
@measure_memory
def test_order_management_performance(trading_system):
    """Test order management performance under load."""
    order_manager = trading_system['order_manager']
    price_manager = trading_system['price_manager']
    
    # Test order placement performance
    start = time.perf_counter()
    orders_placed = 0
    
    for i in range(100):
        order_id = order_manager.place_buy_order(100.0, 1.0)
        if order_id:
            orders_placed += 1
            
            # Simulate immediate fill
            price_manager._handle_user_message(None, {
                'e': 'executionReport',
                'i': order_id,
                'X': 'FILLED',
                'l': '100.0',
                'L': '1.0'
            })
    
    order_time = time.perf_counter() - start
    orders_per_second = orders_placed / order_time
    
    print(f"Orders processed per second: {orders_per_second:.2f}")
    assert orders_per_second > 10, "Order processing too slow"

@measure_time
@measure_memory
def test_system_state_performance(trading_system):
    """Test system state management performance."""
    state_manager = trading_system['state_manager']
    
    # Test state update performance
    start = time.perf_counter()
    updates = 0
    
    for _ in range(1000):
        state = state_manager._get_current_state()
        updates += 1
    
    update_time = time.perf_counter() - start
    updates_per_second = updates / update_time
    
    print(f"State updates per second: {updates_per_second:.2f}")
    assert updates_per_second > 100, "State management too slow"

def test_memory_leak_detection(trading_system):
    """Test for memory leaks during extended operation."""
    price_manager = trading_system['price_manager']
    order_manager = trading_system['order_manager']
    state_manager = trading_system['state_manager']
    
    process = psutil.Process()
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    # Run system operations for a period
    for _ in range(1000):
        # Simulate price updates
        price_manager._handle_trade_message(None, {
            'e': 'trade',
            'E': int(time.time() * 1000),
            'p': '1.0',
            'q': '100.0'
        })
        
        # Get system state
        state_manager._get_current_state()
    
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    memory_growth = final_memory - initial_memory
    
    print(f"Memory growth: {memory_growth:.2f} MB")
    assert memory_growth < 10, "Potential memory leak detected" 