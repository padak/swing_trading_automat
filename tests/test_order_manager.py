"""Unit tests for order manager module."""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytest
import time
import threading

from src.core.order_manager import OrderManager
from src.db.models import Order, OrderStatus
from src.config.settings import (
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE,
    MAX_SELL_VALUE_USDC,
    MAX_ORDER_USDC,
    POSITION_DURATION_ALERT_THRESHOLD
)

@pytest.fixture
def mock_price_manager():
    """Create a mock price manager."""
    manager = Mock()
    manager.get_current_price.return_value = 1.0
    return manager

@pytest.fixture
def order_manager(mock_price_manager):
    """Create an order manager instance for testing."""
    return OrderManager(mock_price_manager)

@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    return session

def test_place_buy_order_success(order_manager, mock_db_session):
    """Test successful buy order placement."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.create_order') as mock_create_order, \
         patch('requests.post') as mock_post:
        
        # Mock API response
        mock_post.return_value.json.return_value = {
            'orderId': '12345',
            'price': '1.0'
        }
        mock_post.return_value.status_code = 200
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_create_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        # Place order
        order_id = order_manager.place_buy_order(100.0, 1.0)
        
        assert order_id == '12345'
        mock_post.assert_called_once()
        mock_create_order.assert_called_once()

def test_place_buy_order_invalid_size(order_manager):
    """Test buy order with invalid size."""
    # Try to place order exceeding max value
    quantity = MAX_SELL_VALUE_USDC + 1
    order_id = order_manager.place_buy_order(quantity, 1.0)
    
    assert order_id is None

def test_place_sell_order_success(order_manager, mock_db_session):
    """Test successful sell order placement."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.create_order') as mock_create_order, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('requests.post') as mock_post:
        
        # Mock API response
        mock_post.return_value.json.return_value = {
            'orderId': '12346',
            'price': '1.01'
        }
        mock_post.return_value.status_code = 200
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED
        )
        mock_create_order.return_value = Order(
            order_id='12346',
            symbol=TRADING_SYMBOL,
            side='SELL',
            quantity=100.0,
            price=1.01,
            status=OrderStatus.NEW,
            related_order_id='12345'
        )
        
        # Place sell order
        order_id = order_manager.place_sell_order('12345', 100.0)
        
        assert order_id == '12346'
        mock_post.assert_called_once()
        mock_create_order.assert_called_once()

def test_handle_order_update(order_manager, mock_db_session):
    """Test order update handling."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('src.core.order_manager.update_order') as mock_update_order:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        
        # Send update
        update = {
            'order_id': '12345',
            'status': 'FILLED',
            'filled_qty': 100.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        mock_update_order.assert_called_once_with(
            mock_db_session,
            order_id='12345',
            status=OrderStatus.FILLED,
            filled_quantity=100.0,
            average_price=1.0
        )

def test_handle_partial_fill(order_manager, mock_db_session):
    """Test partial fill handling."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
         patch('src.core.order_manager.update_order') as mock_update_order, \
         patch.object(order_manager, 'place_sell_order') as mock_place_sell:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.NEW
        )
        mock_place_sell.return_value = '12346'
        
        # Send partial fill update
        update = {
            'order_id': '12345',
            'status': 'PARTIALLY_FILLED',
            'filled_qty': 50.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        mock_update_order.assert_called_once()
        mock_place_sell.assert_called_once_with('12345', 50.0)

def test_get_position_duration(order_manager, mock_db_session):
    """Test position duration calculation."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_order_by_id') as mock_get_order:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        created_at = datetime.utcnow() - timedelta(hours=1)
        mock_get_order.return_value = Order(
            order_id='12345',
            symbol=TRADING_SYMBOL,
            side='BUY',
            quantity=100.0,
            price=1.0,
            status=OrderStatus.FILLED,
            created_at=created_at
        )
        
        duration = order_manager.get_position_duration('12345')
        
        assert 3500 < duration < 3700  # ~1 hour in seconds

def test_get_open_positions(order_manager, mock_db_session):
    """Test retrieving open positions."""
    with patch('src.core.order_manager.get_db') as mock_get_db, \
         patch('src.core.order_manager.get_open_orders') as mock_get_orders:
        
        # Mock database
        mock_get_db.return_value.__enter__.return_value = mock_db_session
        created_at = datetime.utcnow() - timedelta(hours=1)
        mock_get_orders.return_value = [
            Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED,
                created_at=created_at
            )
        ]
        
        positions = order_manager.get_open_positions()
        
        assert len(positions) == 1
        assert positions[0]['order_id'] == '12345'
        assert positions[0]['symbol'] == TRADING_SYMBOL
        assert positions[0]['quantity'] == 100.0
        assert positions[0]['price'] == 1.0
        assert positions[0]['status'] == OrderStatus.FILLED.value
        assert 3500 < positions[0]['duration_seconds'] < 3700 

# Performance Tests
@pytest.mark.performance
class TestOrderManagerPerformance:
    """Performance tests for OrderManager."""
    
    @pytest.fixture
    def order_manager_perf(self, mock_price_manager):
        """Create an order manager instance for performance testing."""
        return OrderManager(mock_price_manager)

    def test_order_processing_throughput(self, order_manager_perf, mock_db_session, benchmark):
        """Test order processing throughput."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.update_order') as mock_update_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            def process_orders():
                """Process 1000 order updates."""
                update = {
                    'order_id': '12345',
                    'status': 'FILLED',
                    'filled_qty': 100.0,
                    'price': 1.0
                }
                for _ in range(1000):
                    order_manager_perf._handle_order_update(update)
            
            # Benchmark processing 1000 order updates
            benchmark(process_orders)
            assert mock_update_order.call_count == 1000

    def test_partial_fill_processing_latency(self, order_manager_perf, mock_db_session):
        """Test latency of partial fill processing."""
        latencies = []
        
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.update_order') as mock_update_order, \
             patch.object(order_manager_perf, 'place_sell_order') as mock_place_sell:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            mock_place_sell.return_value = '12346'
            
            update = {
                'order_id': '12345',
                'status': 'PARTIALLY_FILLED',
                'filled_qty': 50.0,
                'price': 1.0
            }
            
            # Measure latency for 100 partial fill updates
            for _ in range(100):
                start_time = time.perf_counter()
                order_manager_perf._handle_order_update(update)
                end_time = time.perf_counter()
                latencies.append((end_time - start_time) * 1000)  # Convert to milliseconds
            
            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            
            # Assert reasonable latency bounds (adjust based on requirements)
            assert avg_latency < 5.0, f"Average latency {avg_latency}ms exceeds 5ms threshold"
            assert max_latency < 20.0, f"Maximum latency {max_latency}ms exceeds 20ms threshold"

    def test_concurrent_order_processing(self, order_manager_perf, mock_db_session):
        """Test performance with concurrent order processing."""
        orders_processed = 0
        lock = threading.Lock()
        
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.update_order') as mock_update_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            def process_orders():
                nonlocal orders_processed
                update = {
                    'order_id': '12345',
                    'status': 'FILLED',
                    'filled_qty': 100.0,
                    'price': 1.0
                }
                for _ in range(250):
                    order_manager_perf._handle_order_update(update)
                    with lock:
                        orders_processed += 1
                    time.sleep(0.001)  # Simulate realistic order arrival
            
            # Start concurrent processing with 4 threads
            threads = [threading.Thread(target=process_orders) for _ in range(4)]
            
            start_time = time.perf_counter()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            end_time = time.perf_counter()
            
            total_time = end_time - start_time
            
            # Verify all orders were processed
            assert orders_processed == 1000, f"Only processed {orders_processed}/1000 orders"
            
            # Assert reasonable processing time (adjust based on requirements)
            assert total_time < 2.0, f"Concurrent processing took {total_time}s, exceeding 2s threshold"

    def test_position_query_performance(self, order_manager_perf, mock_db_session, benchmark):
        """Test performance of position querying."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_open_orders') as mock_get_orders:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            created_at = datetime.utcnow() - timedelta(hours=1)
            
            # Create 1000 test orders
            mock_orders = [
                Order(
                    order_id=str(i),
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=100.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    created_at=created_at
                ) for i in range(1000)
            ]
            mock_get_orders.return_value = mock_orders
            
            def query_positions():
                """Query all open positions."""
                return order_manager_perf.get_open_positions()
            
            # Benchmark querying 1000 positions
            result = benchmark(query_positions)
            positions = result
            
            assert len(positions) == 1000
            # Assert reasonable query time (adjust based on requirements)
            assert result.stats.stats.mean < 0.1, f"Average query time {result.stats.stats.mean}s exceeds 100ms threshold"

class TestOrderMonitoring:
    """Tests for order monitoring functionality."""
    
    def test_validate_fill_quantity(self, order_manager):
        """Test fill quantity validation."""
        mock_order = Mock(
            order_id="test123",
            quantity=1.0,
            side="BUY",
            filled_quantity=0.0
        )
        
        # Valid fill
        is_valid, _ = order_manager._validate_fill_quantity(mock_order, 0.5)
        assert is_valid
        
        # Fill exceeding order quantity
        is_valid, error = order_manager._validate_fill_quantity(mock_order, 1.5)
        assert not is_valid
        assert "exceed order quantity" in error
        
        # Zero fill
        is_valid, _ = order_manager._validate_fill_quantity(mock_order, 0.0)
        assert is_valid
    
    def test_handle_buy_order_update(self, order_manager):
        """Test handling of BUY order updates."""
        order_id = "test123"
        
        # Simulate NEW order
        update = {
            'order_id': order_id,
            'status': 'NEW',
            'filled_qty': 0.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        # Verify monitoring state
        assert order_id in order_manager.monitored_orders
        assert order_manager.monitored_orders[order_id]['status'] == 'NEW'
        assert len(order_manager.monitored_orders[order_id]['fills']) == 0
        
        # Simulate partial fill
        update = {
            'order_id': order_id,
            'status': 'PARTIALLY_FILLED',
            'filled_qty': 0.5,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        # Verify fill recorded
        assert len(order_manager.monitored_orders[order_id]['fills']) == 1
        assert order_manager.monitored_orders[order_id]['fills'][0]['quantity'] == 0.5
        
        # Simulate complete fill
        update = {
            'order_id': order_id,
            'status': 'FILLED',
            'filled_qty': 0.5,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        # Verify monitoring state cleaned up
        assert order_id not in order_manager.monitored_orders
    
    def test_handle_partial_fills(self, order_manager):
        """Test handling of partial fills for BUY orders."""
        mock_order = Mock(
            order_id="test123",
            quantity=1.0,
            side="BUY",
            status=OrderStatus.NEW
        )
        
        # First partial fill
        order_manager._handle_partial_fill(mock_order, 0.3, 1.0)
        
        # Second partial fill
        order_manager._handle_partial_fill(mock_order, 0.4, 1.0)
        
        # Final fill
        order_manager._handle_partial_fill(mock_order, 0.3, 1.0)
        
        # Verify each fill was handled independently
        assert mock_order.order_id in order_manager.monitored_orders
        fills = order_manager.monitored_orders[mock_order.order_id]['fills']
        assert len(fills) == 3
        assert sum(fill['quantity'] for fill in fills) == 1.0
    
    def test_invalid_order_updates(self, order_manager):
        """Test handling of invalid order updates."""
        # Unknown order
        update = {
            'order_id': 'unknown123',
            'status': 'NEW',
            'filled_qty': 0.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        assert 'unknown123' not in order_manager.monitored_orders
        
        # Invalid fill quantity
        update = {
            'order_id': 'test123',
            'status': 'PARTIALLY_FILLED',
            'filled_qty': -1.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        assert 'test123' not in order_manager.monitored_orders
    
    def test_cleanup_completed_orders(self, order_manager):
        """Test cleanup of completed orders from monitoring."""
        order_id = "test123"
        order_manager.monitored_orders[order_id] = {
            'last_update': time.time(),
            'fills': [],
            'status': 'NEW'
        }
        
        # Test each terminal status
        for status in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
            update = {
                'order_id': order_id,
                'status': status,
                'filled_qty': 0.0,
                'price': 1.0
            }
            order_manager._handle_order_update(update)
            assert order_id not in order_manager.monitored_orders 

class TestSellOrderPlacement:
    """Tests for sell order placement functionality."""
    
    def test_place_sell_order_success(self, order_manager, mock_db_session):
        """Test successful sell order placement."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related, \
             patch('requests.post') as mock_post:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock buy order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                filled_quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
            
            # Mock no existing sell orders
            mock_get_related.return_value = []
            
            # Mock API response
            mock_post.return_value.json.return_value = {
                'orderId': '12346',
                'price': '1.003'  # 0.3% profit
            }
            mock_post.return_value.status_code = 200
            
            # Place sell order
            sell_order_id = order_manager.place_sell_order('12345', 100.0)
            
            assert sell_order_id == '12346'
            mock_post.assert_called_once()
    
    def test_sell_order_validation(self, order_manager, mock_db_session):
        """Test sell order validation checks."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Test unfilled buy order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                filled_quantity=0.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            sell_order_id = order_manager.place_sell_order('12345', 100.0)
            assert sell_order_id is None
            
            # Test excessive sell quantity
            mock_get_order.return_value.status = OrderStatus.FILLED
            mock_get_order.return_value.filled_quantity = 50.0
            mock_get_related.return_value = []
            
            sell_order_id = order_manager.place_sell_order('12345', 100.0)
            assert sell_order_id is None
            
            # Test with existing sell orders
            mock_get_order.return_value.filled_quantity = 100.0
            mock_get_related.return_value = [
                Order(
                    order_id='12346',
                    symbol=TRADING_SYMBOL,
                    side='SELL',
                    quantity=80.0,
                    status=OrderStatus.NEW
                )
            ]
            
            sell_order_id = order_manager.place_sell_order('12345', 30.0)
            assert sell_order_id is None
    
    def test_sell_order_profit_calculation(self, order_manager, mock_db_session):
        """Test profit calculation for sell orders."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related, \
             patch('requests.post') as mock_post:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock buy order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                filled_quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
            
            # Mock no existing sell orders
            mock_get_related.return_value = []
            
            # Mock API response
            mock_post.return_value.json.return_value = {'orderId': '12346'}
            mock_post.return_value.status_code = 200
            
            # Test with different profit targets
            for profit in [0.003, 0.005, 0.01]:
                order_manager.place_sell_order('12345', 100.0, profit)
                
                # Extract price from API call
                call_args = mock_post.call_args[1]['params']
                sell_price = float(call_args['price'])
                
                # Verify price includes fees and profit
                assert sell_price > 1.0 * (1 + profit)
                mock_post.reset_mock()
    
    @pytest.mark.performance
    def test_sell_order_placement_latency(self, order_manager, mock_db_session, benchmark):
        """Test latency of sell order placement."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related, \
             patch('requests.post') as mock_post:
            
            # Mock database and responses
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                filled_quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
            mock_get_related.return_value = []
            mock_post.return_value.json.return_value = {'orderId': '12346'}
            mock_post.return_value.status_code = 200
            
            def place_orders():
                """Place 100 sell orders."""
                for _ in range(100):
                    order_manager.place_sell_order('12345', 1.0)
            
            # Benchmark sell order placement
            result = benchmark(place_orders)
            
            # Assert reasonable latency (adjust based on requirements)
            assert result.stats.stats.mean < 0.01  # Average under 10ms per order 

class TestPartialFillHandling:
    """Tests for partial fill handling functionality."""
    
    def test_partial_fill_independent_trades(self, order_manager, mock_db_session):
        """Test that each partial fill creates an independent trade."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.create_order') as mock_create_order, \
             patch.object(order_manager, 'place_sell_order') as mock_place_sell:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock original buy order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            # Mock trade record creation
            mock_create_order.side_effect = [
                Order(order_id=f'12345_fill_{i}', quantity=qty)
                for i, qty in enumerate([30.0, 40.0, 30.0])
            ]
            
            # Mock sell order placement
            mock_place_sell.side_effect = [f'sell_{i}' for i in range(3)]
            
            # Simulate three partial fills
            fills = [
                (30.0, 1.0),  # First fill: 30%
                (70.0, 1.0),  # Second fill: +40%
                (100.0, 1.0)  # Final fill: +30%
            ]
            
            for total_filled, price in fills:
                update = {
                    'order_id': '12345',
                    'status': 'PARTIALLY_FILLED' if total_filled < 100.0 else 'FILLED',
                    'filled_qty': total_filled,
                    'price': price
                }
                order_manager._handle_order_update(update)
            
            # Verify three independent trades were created
            assert mock_create_order.call_count == 3
            
            # Verify each trade got its own sell order
            assert mock_place_sell.call_count == 3
            
            # Verify trade quantities
            trade_quantities = [
                call[1]['quantity']
                for call in mock_create_order.call_args_list
            ]
            assert trade_quantities == [30.0, 40.0, 30.0]
    
    def test_partial_fill_quantity_tracking(self, order_manager):
        """Test accurate tracking of partial fill quantities."""
        order_id = "test123"
        
        # First fill: 30%
        update = {
            'order_id': order_id,
            'status': 'PARTIALLY_FILLED',
            'filled_qty': 30.0,
            'price': 1.0
        }
        order_manager._handle_order_update(update)
        
        assert order_manager.monitored_orders[order_id]['total_filled'] == 30.0
        assert len(order_manager.monitored_orders[order_id]['fills']) == 1
        assert order_manager.monitored_orders[order_id]['fills'][0]['quantity'] == 30.0
        
        # Second fill: +40% (70% total)
        update['filled_qty'] = 70.0
        order_manager._handle_order_update(update)
        
        assert order_manager.monitored_orders[order_id]['total_filled'] == 70.0
        assert len(order_manager.monitored_orders[order_id]['fills']) == 2
        assert order_manager.monitored_orders[order_id]['fills'][1]['quantity'] == 40.0
        
        # Final fill: +30% (100% total)
        update['filled_qty'] = 100.0
        update['status'] = 'FILLED'
        order_manager._handle_order_update(update)
        
        # Verify order is no longer monitored after completion
        assert order_id not in order_manager.monitored_orders
    
    def test_partial_fill_validation(self, order_manager, mock_db_session):
        """Test validation of partial fill quantities."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock original buy order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            # Test invalid fill sequence
            updates = [
                # First fill: 30%
                {
                    'order_id': '12345',
                    'status': 'PARTIALLY_FILLED',
                    'filled_qty': 30.0,
                    'price': 1.0
                },
                # Invalid fill: Goes backwards
                {
                    'order_id': '12345',
                    'status': 'PARTIALLY_FILLED',
                    'filled_qty': 20.0,
                    'price': 1.0
                },
                # Invalid fill: Exceeds total
                {
                    'order_id': '12345',
                    'status': 'PARTIALLY_FILLED',
                    'filled_qty': 120.0,
                    'price': 1.0
                }
            ]
            
            # First fill should succeed
            order_manager._handle_order_update(updates[0])
            assert '12345' in order_manager.monitored_orders
            assert order_manager.monitored_orders['12345']['total_filled'] == 30.0
            
            # Invalid fills should be rejected
            order_manager._handle_order_update(updates[1])
            assert order_manager.monitored_orders['12345']['total_filled'] == 30.0
            
            order_manager._handle_order_update(updates[2])
            assert order_manager.monitored_orders['12345']['total_filled'] == 30.0
    
    @pytest.mark.performance
    def test_partial_fill_processing_performance(self, order_manager, mock_db_session, benchmark):
        """Test performance of partial fill processing."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.create_order') as mock_create_order, \
             patch.object(order_manager, 'place_sell_order') as mock_place_sell:
            
            # Mock database and responses
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            def process_partial_fills():
                """Process 100 partial fills."""
                for i in range(100):
                    update = {
                        'order_id': '12345',
                        'status': 'PARTIALLY_FILLED',
                        'filled_qty': i + 1.0,
                        'price': 1.0
                    }
                    order_manager._handle_order_update(update)
            
            # Benchmark partial fill processing
            result = benchmark(process_partial_fills)
            
            # Assert reasonable latency (adjust based on requirements)
            assert result.stats.stats.mean < 0.005  # Average under 5ms per fill 

class TestPositionDurationTracking:
    """Tests for position duration tracking functionality."""
    
    def test_get_position_duration_with_partial_fills(self, order_manager, mock_db_session):
        """Test duration calculation with partial fills."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Create timestamps for testing
            now = datetime.utcnow()
            order_time = now - timedelta(hours=2)
            fill1_time = now - timedelta(hours=1.5)
            fill2_time = now - timedelta(hours=1)
            
            # Mock main order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED,
                created_at=order_time
            )
            
            # Mock partial fills
            mock_get_related.return_value = [
                Order(
                    order_id='12345_fill_1',
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=50.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    created_at=fill1_time,
                    order_type='PARTIAL_FILL'
                ),
                Order(
                    order_id='12345_fill_2',
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=50.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    created_at=fill2_time,
                    order_type='PARTIAL_FILL'
                )
            ]
            
            # Get duration
            duration = order_manager.get_position_duration('12345')
            
            # Duration should be from earliest time (order creation)
            assert duration is not None
            assert abs(duration - 7200) < 1  # ~2 hours in seconds
    
    def test_get_open_positions_with_partial_fills(self, order_manager, mock_db_session):
        """Test open positions retrieval with partial fills."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_open_orders') as mock_get_orders, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock open orders
            mock_get_orders.return_value = [
                Order(
                    order_id='12345',
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=100.0,
                    filled_quantity=100.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    created_at=datetime.utcnow() - timedelta(hours=2)
                )
            ]
            
            # Mock related orders (partial fills and sells)
            mock_get_related.return_value = [
                Order(
                    order_id='12345_fill_1',
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=60.0,
                    filled_quantity=60.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    order_type='PARTIAL_FILL'
                ),
                Order(
                    order_id='12346',
                    symbol=TRADING_SYMBOL,
                    side='SELL',
                    quantity=60.0,
                    filled_quantity=60.0,
                    price=1.003,
                    status=OrderStatus.FILLED
                )
            ]
            
            # Get positions
            positions = order_manager.get_open_positions()
            
            assert len(positions) == 1
            position = positions[0]
            
            # Verify position details
            assert position['order_id'] == '12345'
            assert position['quantity'] == 100.0
            assert position['filled_quantity'] == 160.0  # Original + partial fill
            assert position['sold_quantity'] == 60.0
            assert position['remaining_quantity'] == 100.0  # 160 filled - 60 sold
            assert position['has_partial_fills'] is True
            assert len(position['sell_orders']) == 1
            assert position['duration_hours'] is not None
            assert abs(position['duration_hours'] - 2.0) < 0.1
    
    def test_position_duration_monitoring(self, order_manager, mock_db_session):
        """Test position duration monitoring and alerts."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_open_orders') as mock_get_orders, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related, \
             patch('src.core.order_manager.logger') as mock_logger:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Create an old position that should trigger alert
            old_time = datetime.utcnow() - timedelta(hours=POSITION_DURATION_ALERT_THRESHOLD/3600 + 1)
            mock_get_orders.return_value = [
                Order(
                    order_id='12345',
                    symbol=TRADING_SYMBOL,
                    side='BUY',
                    quantity=100.0,
                    price=1.0,
                    status=OrderStatus.FILLED,
                    created_at=old_time
                )
            ]
            mock_get_related.return_value = []
            
            # Run one monitoring cycle
            order_manager._monitor_position_durations()
            
            # Verify alert was logged
            mock_logger.warning.assert_called_once()
            alert_args = mock_logger.warning.call_args[1]
            assert alert_args['order_id'] == '12345'
            assert alert_args['duration_hours'] > POSITION_DURATION_ALERT_THRESHOLD/3600
            
            # Verify alert is tracked
            assert '12345' in order_manager.position_alerts
            
            # Simulate position closed
            mock_get_orders.return_value = []
            
            # Run another monitoring cycle
            order_manager._monitor_position_durations()
            
            # Verify alert was cleaned up
            assert '12345' not in order_manager.position_alerts
    
    @pytest.mark.performance
    def test_position_duration_tracking_performance(self, order_manager, mock_db_session, benchmark):
        """Test performance of position duration tracking."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_open_orders') as mock_get_orders, \
             patch('src.core.order_manager.get_related_orders') as mock_get_related:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Create 1000 test positions with varying durations
            positions = []
            for i in range(1000):
                age_hours = i % 48  # Spread positions over 48 hours
                created_at = datetime.utcnow() - timedelta(hours=age_hours)
                positions.append(
                    Order(
                        order_id=str(i),
                        symbol=TRADING_SYMBOL,
                        side='BUY',
                        quantity=100.0,
                        price=1.0,
                        status=OrderStatus.FILLED,
                        created_at=created_at
                    )
                )
            mock_get_orders.return_value = positions
            mock_get_related.return_value = []
            
            def track_durations():
                """Track durations for all positions."""
                return order_manager.get_open_positions()
            
            # Benchmark duration tracking
            result = benchmark(track_durations)
            positions = result
            
            assert len(positions) == 1000
            # Assert reasonable processing time (adjust based on requirements)
            assert result.stats.stats.mean < 0.1  # Under 100ms for 1000 positions 

class TestOrderStateTransitions:
    """Tests for order state transition functionality."""
    
    def test_valid_state_transitions(self, order_manager):
        """Test valid order state transitions."""
        # Test NEW to PARTIALLY_FILLED
        assert order_manager._validate_state_transition(
            "test123",
            "NEW",
            "PARTIALLY_FILLED"
        )
        
        # Test NEW to FILLED
        assert order_manager._validate_state_transition(
            "test123",
            "NEW",
            "FILLED"
        )
        
        # Test PARTIALLY_FILLED to FILLED
        assert order_manager._validate_state_transition(
            "test123",
            "PARTIALLY_FILLED",
            "FILLED"
        )
    
    def test_invalid_state_transitions(self, order_manager):
        """Test invalid order state transitions."""
        with pytest.raises(OrderTransitionError):
            # Cannot go from FILLED to PARTIALLY_FILLED
            order_manager._validate_state_transition(
                "test123",
                "FILLED",
                "PARTIALLY_FILLED"
            )
        
        with pytest.raises(OrderTransitionError):
            # Cannot go from CANCELED to NEW
            order_manager._validate_state_transition(
                "test123",
                "CANCELED",
                "NEW"
            )
    
    def test_state_transition_recording(self, order_manager, mock_db_session):
        """Test recording of state transitions."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            # Simulate order updates
            updates = [
                {
                    'order_id': '12345',
                    'status': 'PARTIALLY_FILLED',
                    'filled_qty': 50.0,
                    'price': 1.0
                },
                {
                    'order_id': '12345',
                    'status': 'FILLED',
                    'filled_qty': 100.0,
                    'price': 1.0
                }
            ]
            
            # Process updates
            for update in updates:
                order_manager._handle_order_update(update)
            
            # Get transition history
            transitions = order_manager.get_order_transitions('12345')
            
            # Verify transitions
            assert len(transitions) == 2
            assert transitions[0]['from_status'] == 'NEW'
            assert transitions[0]['to_status'] == 'PARTIALLY_FILLED'
            assert transitions[1]['from_status'] == 'PARTIALLY_FILLED'
            assert transitions[1]['to_status'] == 'FILLED'
            
            # Verify metadata
            assert transitions[0]['metadata']['filled_qty'] == 50.0
            assert transitions[1]['metadata']['filled_qty'] == 100.0
    
    def test_state_transition_validation_in_order_update(self, order_manager, mock_db_session):
        """Test state transition validation during order updates."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order, \
             patch('src.core.order_manager.update_order') as mock_update_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock order in FILLED state
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.FILLED
            )
            
            # Try invalid transition
            update = {
                'order_id': '12345',
                'status': 'PARTIALLY_FILLED',  # Invalid: can't go back to PARTIALLY_FILLED
                'filled_qty': 50.0,
                'price': 1.0
            }
            
            # Process update
            order_manager._handle_order_update(update)
            
            # Verify order was not updated
            mock_update_order.assert_not_called()
    
    @pytest.mark.performance
    def test_state_transition_performance(self, order_manager, mock_db_session, benchmark):
        """Test performance of state transition handling."""
        with patch('src.core.order_manager.get_db') as mock_get_db, \
             patch('src.core.order_manager.get_order_by_id') as mock_get_order:
            
            # Mock database
            mock_get_db.return_value.__enter__.return_value = mock_db_session
            
            # Mock order
            mock_get_order.return_value = Order(
                order_id='12345',
                symbol=TRADING_SYMBOL,
                side='BUY',
                quantity=100.0,
                price=1.0,
                status=OrderStatus.NEW
            )
            
            def process_transitions():
                """Process 1000 state transitions."""
                for i in range(1000):
                    order_manager._validate_state_transition(
                        "test123",
                        "NEW",
                        "PARTIALLY_FILLED"
                    )
            
            # Benchmark state transition validation
            result = benchmark(process_transitions)
            
            # Assert reasonable processing time
            assert result.stats.stats.mean < 0.001  # Under 1ms per transition 