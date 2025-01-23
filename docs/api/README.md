# API Documentation

## Core Components

### PriceManager

The `PriceManager` class handles real-time price updates and WebSocket connections.

```python
from src.core.price_manager import PriceManager

price_manager = PriceManager()
```

#### Methods

- `start()`: Initializes WebSocket connections and starts price monitoring
- `stop()`: Gracefully closes connections and stops monitoring
- `register_price_callback(callback)`: Registers a callback for price updates
- `register_order_callback(callback)`: Registers a callback for order updates
- `get_current_price(symbol: str) -> float`: Returns current price for a symbol

### OrderManager

The `OrderManager` class handles order operations and position management.

```python
from src.core.order_manager import OrderManager

order_manager = OrderManager()
```

#### Methods

- `start()`: Initializes order monitoring
- `stop()`: Gracefully stops order monitoring
- `handle_price_update(symbol: str, price: float)`: Processes price updates
- `handle_order_update(order_data: dict)`: Processes order status updates
- `get_position_duration(order_id: str) -> timedelta`: Returns position age

### StateManager

The `StateManager` class manages system state and persistence.

```python
from src.core.state_manager import StateManager

state_manager = StateManager()
```

#### Methods

- `start()`: Initializes state monitoring
- `stop()`: Gracefully stops state monitoring
- `get_current_state() -> dict`: Returns current system state
- `save_state() -> bool`: Persists current state to database

## Database Operations

### Models

```python
from src.db.models import Order, TradePair, SystemState
```

#### Order Model
- Fields: id, binance_order_id, symbol, side, price, quantity, status
- Relationships: related_orders, trade_pair

#### TradePair Model
- Fields: id, buy_order_id, sell_order_id, status
- Relationships: buy_order, sell_order

#### SystemState Model
- Fields: id, timestamp, state_data, status

### Operations

```python
from src.db.operations import (
    create_order,
    get_order_by_id,
    update_order,
    get_open_orders
)
```

#### Functions

- `create_order(data: dict) -> Order`: Creates new order record
- `get_order_by_id(order_id: str) -> Order`: Retrieves order by ID
- `update_order(order_id: str, data: dict) -> bool`: Updates order record
- `get_open_orders() -> List[Order]`: Returns all open orders

## Configuration

### Settings

```python
from src.config.settings import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    TRADING_SYMBOL,
    MIN_PROFIT_PERCENTAGE,
    MAX_SELL_VALUE_USDC
)
```

### Logging

```python
from src.config.logging_config import setup_logging

setup_logging()
```

## CLI Utility

### Position Management

```python
from tools.manage_positions import (
    list_positions,
    view_position,
    cancel_order
)
```

#### Functions

- `list_positions() -> List[dict]`: Lists all positions
- `view_position(order_id: str) -> dict`: Views specific position
- `cancel_order(order_id: str) -> bool`: Cancels an order

## Error Handling

### Custom Exceptions

```python
from src.utils.exceptions import (
    OrderValidationError,
    WebSocketError,
    DatabaseError
)
```

### Error Recovery

```python
from src.utils.recovery import (
    recover_state,
    reconcile_orders,
    validate_system_state
)
```

## Examples

### Starting the System

```python
from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager

# Initialize components
price_manager = PriceManager()
order_manager = OrderManager()
state_manager = StateManager()

# Register callbacks
price_manager.register_price_callback(order_manager.handle_price_update)
price_manager.register_order_callback(order_manager.handle_order_update)

# Start components
price_manager.start()
order_manager.start()
state_manager.start()
```

### Managing Orders

```python
from src.db.operations import create_order, get_order_by_id

# Create a new order
order_data = {
    "symbol": "TRUMPUSDC",
    "side": "BUY",
    "price": 100.0,
    "quantity": 1.0
}
order = create_order(order_data)

# Get order details
order = get_order_by_id(order.id)
```

### Error Handling

```python
from src.utils.exceptions import OrderValidationError

try:
    # Attempt to create order
    order = create_order(order_data)
except OrderValidationError as e:
    # Handle validation error
    logger.error(f"Order validation failed: {str(e)}")
except Exception as e:
    # Handle unexpected error
    logger.error(f"Unexpected error: {str(e)}")
``` 