# Swing Trading Automation Implementation Plan

## 1. Directory Structure

```
binance_swing_trading/
├── src/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py          # App settings, constants, env loading
│   │   └── logging_config.py    # Logging configuration
│   ├── core/
│   │   ├── __init__.py
│   │   ├── price_manager.py     # Price updates (WebSocket + REST fallback)
│   │   ├── order_manager.py     # Order operations
│   │   ├── profit_calculator.py # Profit calculations with fees
│   │   └── state_manager.py     # System state management
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLite table definitions
│   │   └── operations.py       # DB operations
│   └── utils/
│       ├── __init__.py
│       └── helpers.py          # Utility functions
├── tests/
│   ├── __init__.py
│   ├── test_price_manager.py
│   ├── test_order_manager.py
│   ├── test_profit_calculator.py
│   └── test_state_manager.py
├── data/
│   ├── trading.db             # SQLite database
│   └── logs/
│       └── trading.log        # Rotating log files
├── .env.example               # Template for environment variables
├── requirements.txt           # Project dependencies
├── main.py                   # Entry point
└── README.md                 # Project documentation
```

## 2. Database Schema

```sql
-- Orders table
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binance_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,  -- 'BUY' or 'SELL'
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL,  -- 'OPEN', 'FILLED', 'CANCELLED'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trade pairs table (linking BUY and SELL orders)
CREATE TABLE trade_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buy_order_id INTEGER NOT NULL,
    sell_order_id INTEGER,  -- NULL until SELL order is created
    target_profit_price REAL NOT NULL,  -- Calculated minimum sell price for profit
    status TEXT NOT NULL,  -- 'WAITING_FOR_PROFIT', 'SELL_PLACED', 'COMPLETED'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (buy_order_id) REFERENCES orders(id),
    FOREIGN KEY (sell_order_id) REFERENCES orders(id)
);

-- System state table
CREATE TABLE system_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    last_processed_time TIMESTAMP,
    websocket_status TEXT,
    last_error TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 3. Core Components

### 3.1 Price Manager (price_manager.py)
- WebSocket connection management with exponential backoff
- REST API fallback implementation
- Price update broadcasting to subscribers
- Connection state monitoring

### 3.2 Order Manager (order_manager.py)
- Order tracking and management
- BUY order discovery
- SELL order placement with profit calculation
- Order status monitoring

### 3.3 Profit Calculator (profit_calculator.py)
- Fee calculation (0.1% buy + 0.1% sell)
- Minimum sell price calculation for 0.3% net profit
- Validation of order sizes (max 100 USDC)

### 3.4 State Manager (state_manager.py)
- System state persistence
- Graceful shutdown handling
- Recovery from saved state
- Multiple BUY orders consolidation

## 4. Configuration

### 4.1 Environment Variables (.env)
```
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
TRADING_SYMBOL=TRUMPUSDC
MIN_PROFIT_PERCENTAGE=0.3
MAX_SELL_VALUE_USDC=100
DB_PATH=data/trading.db
LOG_PATH=data/logs/trading.log
LOG_LEVEL=INFO
WEBSOCKET_RECONNECT_TIMEOUT=900  # 15 minutes in seconds
REST_API_REFRESH_RATE=5  # seconds
```

### 4.2 Logging Configuration
- Rotating file handler (100MB limit)
- Configurable verbosity levels
- Network errors and rate limits logging
- Separate error logging stream

## 5. Testing Strategy

### 5.1 Unit Tests
- Mock Binance API responses
- Test profit calculations
- Test order management logic
- Test WebSocket reconnection logic

### 5.2 Integration Tests
- Database operations
- State management
- Order workflow

## 6. Error Handling

### 6.1 WebSocket Management
- Exponential backoff for reconnection
- 15-minute timeout limit
- Automatic fallback to REST API
- Graceful shutdown procedure

### 6.2 Order Management
- Validation of order sizes
- Fee calculation verification
- Order status monitoring
- Error state recovery

## 7. Future Extension Points

### 7.1 Strategy Layer Interface
```python
class TradingStrategy(ABC):
    @abstractmethod
    def should_place_sell_order(self, buy_order: Order, current_price: float) -> bool:
        pass

    @abstractmethod
    def calculate_sell_price(self, buy_order: Order, current_price: float) -> float:
        pass
```

### 7.2 Plugin Architecture
- Strategy registration system
- Event hooks for price updates
- Custom order validation rules
- External data source integration

## 8. Implementation Phases

### Phase 1: Core Infrastructure
1. Set up project structure
2. Implement database schema
3. Create basic logging system
4. Set up configuration management

### Phase 2: Price Management
1. Implement WebSocket connection
2. Add REST API fallback
3. Create price update system
4. Add reconnection logic

### Phase 3: Order Management
1. Implement order tracking
2. Add profit calculation
3. Create order placement system
4. Implement state management

### Phase 4: Testing & Hardening
1. Write unit tests
2. Add integration tests
3. Implement error handling
4. Add logging and monitoring

### Phase 5: Documentation & Cleanup
1. Add code documentation
2. Create user guide
3. Document API interfaces
4. Create deployment guide 