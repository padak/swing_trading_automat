Below is a proposed directory structure and implementation plan in Python for your swing-trading project. The idea is to keep the entire functionality in one folder so it’s easy to integrate into a larger system while remaining self-contained.

All names here are just suggestions; feel free to rename them as needed.

1. Directory Structure
```
binance_swing_trading/
├── binance_swing_trading
│   ├── __init__.py
│   ├── config.py
│   ├── constants.py
│   ├── database.py
│   ├── orders_manager.py
│   ├── websocket_listener.py
│   ├── trader.py
│   ├── utils.py
│   └── main.py
├── docs
│   ├── README.md
│   ├── USER_GUIDE.md
│   └── DEVELOPER_GUIDE.md
├── requirements.txt
└── setup.py
```

Explanation
1. binance_swing_trading (top-level folder):
 - This is the Python package folder with all source code.
 - Everything related to your swing trading logic goes here.

2. docs folder:
 - Contains documentation (user guide, developer guide, etc.).

3. requirements.txt:
 - List of Python dependencies (e.g., python-binance, requests, websockets, SQLAlchemy or sqlite3 usage, etc.).

4. setup.py (optional):
 - If you plan to distribute or install this package, you can use setup.py or a modern pyproject.toml for packaging.

----

2. File-by-File Responsibilities

Below are the main files inside the binance_swing_trading/ package and what each does:

1. __init__.py
 - Makes this folder a Python package.
 - Usually empty, or may contain import shortcuts if desired.

2. config.py
 - Holds configuration logic, e.g. reading from environment variables or reading command-line arguments (argparse) that define:
    - Binance API credentials
    - Trading symbol (e.g., TRUMPUSDC)
    - Minimum profit threshold
    - Database path
    - Logging preferences, etc.
 - Could also parse command-line flags like --dry-run or --read-only.

3. constants.py
 - Holds constant values (e.g., FEE_RATE_BUY = 0.001, FEE_RATE_SELL = 0.001 if 0.1%; or default symbol names, default timeouts).
 - Helps keep “magic numbers” in one place.

4. database.py
 - Manages SQLite connection, table creation, and queries.
 - For example:
    - A table for storing open BUY orders that need SELL.
    - A table for storing logs of completed trades or partial fills.
 - Could use Python’s built-in sqlite3 module or an ORM like SQLAlchemy.

5. orders_manager.py
 - Responsible for interacting with the Binance REST API to:
    - Fetch current orders (open/closed).
    - Place BUY/SELL orders (market or limit).
    - Cancel orders if needed.
 - Could wrap the python-binance library or use your own calls via requests.

6. websocket_listener.py
 - Subscribes to Binance WebSocket streams:
    - Market data (e.g., live price ticks for TRUMPUSDC).
    - User data (to get real-time order fill updates, if you choose to integrate that).
 - Emits events (e.g., using Python signals, or callback handlers) that other modules can react to.

7. trader.py
 - The core logic for your swing trading strategy:
    - Maintains an internal dictionary/map of unfilled BUY orders vs. SELL orders.
    - Decides when to place a SELL, at what price, or if you’re in “read-only” or “dry-run” mode.
    - For each BUY, checks the WebSocket’s current price to see if it’s above the threshold.
    - If it meets or exceeds the threshold (accounting for fees), calls orders_manager to place a SELL order or do a market SELL.

8. utils.py
 - Utility/helper functions, for example:
    - Logging setup (if not handled in main.py).
    - Price calculations (e.g., computing minimum profitable sell price).
    - Date/time conversions, etc.

9. main.py
 - The entry point script that ties everything together.
 - Parses command-line arguments (using argparse or a similar library) to set up configuration.
 - Initializes database connection, websocket_listener, trader.
 - Kicks off the main loop or asynchronous event loop.
 - Based on arguments (--read-only, --dry-run, etc.), it decides how to behave.
 - Example usage:
 ```
 python main.py --mode read_only
 python main.py --mode trade
```

----

3. Detailed Implementation Flow

Below is a more step-by-step outline of how the system might work in “trading mode” (i.e., ver. 1 idea):

1. Initialization (in main.py):
 - Parse command-line arguments (via argparse).
 - Load environment variables or config file (in config.py).
 - Initialize the database (in database.py).
 - Initialize the orders_manager with Binance API credentials.
- Create an instance of trader.Trader() (the main strategy class).

2. Load existing orders (in orders_manager.py):
 - Retrieve open BUY and SELL orders from Binance REST API.
 - Optionally store them in your local DB (in database.py).
 - trader will filter out those that already have matching pairs.

3. Match orders (in trader.py):
 - For each found BUY, check if there is a SELL that fully or partially matched it (so you only track the unmatched portion).
 - Store unmatched BUYs in an internal data structure (e.g. a dict mapping order_id -> quantity).
 - If there is a SELL that partially covers a BUY, adjust accordingly.

4. Start WebSocket (in websocket_listener.py):
 - Listen to market price updates for TRUMPUSDC.
 - On each price update, call back to a method in trader (e.g. trader.on_price_update(new_price)).

5. React to new price (trader.on_price_update):
 - For each unmatched BUY in memory, compute the minimum SELL price needed to achieve the target profit.
 - If new_price >= min_sell_price, call orders_manager.sell(...) to place a SELL order (or do a market SELL).
 - On success, remove that BUY from your unmatched list and update the DB.

6. Logging (utils.py or integrated):
 - Each time a SELL is placed, log the event with timestamp, price, fees, etc.
 - Each time a partial fill is received from the user data stream, update logs or DB.

7. Shutdown:
 - If the script is stopped, gracefully close WebSocket connections, close DB connections, etc.

----

4. Example Code Snippets

config.py
```
import os
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(description="Binance Swing Trading Script")
    parser.add_argument("--mode", type=str, default="read_only",
                        choices=["read_only", "trade"],
                        help="Script mode: 'read_only' will not execute trades, 'trade' will place actual orders.")
    parser.add_argument("--db-path", type=str, default=":memory:",
                        help="Path to the SQLite database file. Default is in-memory.")
    # Add more arguments as needed...
    return parser.parse_args()

def load_config():
    """Load config from environment variables or set defaults."""
    config = {}
    config["BINANCE_API_KEY"] = os.environ.get("BINANCE_API_KEY", "YOUR_API_KEY")
    config["BINANCE_API_SECRET"] = os.environ.get("BINANCE_API_SECRET", "YOUR_API_SECRET")
    # ...
    return config
```

database.py
```
import sqlite3

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def init_db(self):
        """Create tables if they do not exist."""
        self.conn = sqlite3.connect(self.db_path)
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    buy_order_id TEXT,
                    sell_order_id TEXT,
                    buy_price REAL,
                    sell_price REAL,
                    quantity REAL,
                    status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def insert_trade(self, symbol, buy_order_id, sell_order_id, buy_price, sell_price, quantity, status):
        with self.conn:
            self.conn.execute("""
                INSERT INTO trades (symbol, buy_order_id, sell_order_id, buy_price, sell_price, quantity, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, buy_order_id, sell_order_id, buy_price, sell_price, quantity, status))

    def close(self):
        """Close the DB connection."""
        if self.conn:
            self.conn.close()
```

orders_manager.py
```
# Example using python-binance
from binance.client import Client

class OrdersManager:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)
    
    def get_open_orders(self, symbol):
        """Fetch open orders from Binance."""
        return self.client.get_open_orders(symbol=symbol)
    
    def place_sell_order(self, symbol, quantity, price=None):
        """
        Place a SELL order.
        If price is provided, place a limit SELL.
        Otherwise, do a market SELL.
        """
        if price:
            order = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="LIMIT",
                timeInForce="GTC",
                quantity=quantity,
                price=str(price)
            )
        else:
            order = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity
            )
        return order
```

websocket_listener.py
```
import asyncio
import websockets
import json

class WebSocketListener:
    def __init__(self, symbol, on_price_update):
        """
        symbol: e.g. "TRUMPUSDC"
        on_price_update: callback function that gets called with the new price
        """
        self.symbol = symbol.lower()  # Typically binance uses lowercase for streams
        self.on_price_update = on_price_update
        self.ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@trade"
        self.is_running = False

    async def listen(self):
        """Listen to the trade stream for price updates."""
        self.is_running = True
        async with websockets.connect(self.ws_url) as ws:
            while self.is_running:
                try:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    # data["p"] is typically the price in a trade payload
                    price = float(data["p"])
                    self.on_price_update(price)
                except Exception as e:
                    print("WebSocket Error:", e)
                    self.is_running = False
                    break

    def stop(self):
        self.is_running = False
```

trader.py
```
class Trader:
    def __init__(self, orders_manager, db_manager, symbol, mode="read_only", profit_threshold=0.005):
        """
        orders_manager: instance of OrdersManager
        db_manager: instance of DatabaseManager
        symbol: e.g., "TRUMPUSDC"
        mode: "read_only" or "trade"
        profit_threshold: e.g. 0.005 -> 0.5% profit
        """
        self.orders_manager = orders_manager
        self.db_manager = db_manager
        self.symbol = symbol
        self.mode = mode
        self.profit_threshold = profit_threshold
        self.unmatched_buys = {}  # buy_order_id -> (buy_price, quantity)

    def load_unmatched_orders(self):
        """Populate self.unmatched_buys by reading open orders from the exchange."""
        open_orders = self.orders_manager.get_open_orders(self.symbol)
        # Filter or parse them; store buys in unmatched_buys, etc.
        for order in open_orders:
            if order["side"] == "BUY":
                buy_price = float(order["price"])
                quantity = float(order["origQty"]) - float(order["executedQty"])
                self.unmatched_buys[order["orderId"]] = (buy_price, quantity)

    def on_price_update(self, new_price):
        """
        Called whenever the WebSocket gives us a new price.
        For each unmatched BUY, check if new_price >= buy_price * (1 + profit_threshold + fees).
        """
        # Fees might be 0.001 for buy + 0.001 for sell => 0.002 total
        # So the formula might be: min_sell_price = buy_price * (1 + profit_threshold + 0.002)
        order_ids_to_remove = []
        for buy_order_id, (buy_price, quantity) in self.unmatched_buys.items():
            min_sell_price = buy_price * (1 + self.profit_threshold + 0.002)
            if new_price >= min_sell_price:
                # Time to sell
                if self.mode == "trade":
                    self.orders_manager.place_sell_order(self.symbol, quantity, price=str(new_price))
                    print(f"Placed SELL at ~{new_price} for order {buy_order_id}")
                    # Insert to DB
                    self.db_manager.insert_trade(
                        symbol=self.symbol,
                        buy_order_id=buy_order_id,
                        sell_order_id="PENDING",  # We will update later with actual ID
                        buy_price=buy_price,
                        sell_price=new_price,
                        quantity=quantity,
                        status="SELL_PLACED"
                    )
                else:
                    print(f"[READ_ONLY] Would place SELL at {new_price} for order {buy_order_id}")

                order_ids_to_remove.append(buy_order_id)

        # Remove matched BUYs from internal dict
        for oid in order_ids_to_remove:
            del self.unmatched_buys[oid]
```

main.py
```
import asyncio
import sys

from binance_swing_trading.config import parse_arguments, load_config
from binance_swing_trading.database import DatabaseManager
from binance_swing_trading.orders_manager import OrdersManager
from binance_swing_trading.websocket_listener import WebSocketListener
from binance_swing_trading.trader import Trader

def main():
    args = parse_arguments()
    config = load_config()

    # Initialize DB
    db_manager = DatabaseManager(db_path=args.db_path)
    
    # Initialize OrdersManager with your Binance keys
    orders_manager = OrdersManager(
        api_key=config["BINANCE_API_KEY"],
        api_secret=config["BINANCE_API_SECRET"]
    )
    
    # Create Trader
    trader = Trader(
        orders_manager=orders_manager,
        db_manager=db_manager,
        symbol="TRUMPUSDC",
        mode=args.mode,  # "read_only" or "trade"
        profit_threshold=0.005  # 0.5% for example
    )

    # Load unmatched BUY orders
    trader.load_unmatched_orders()

    # Set up WebSocket listener
    ws_listener = WebSocketListener(
        symbol="TRUMPUSDC",
        on_price_update=trader.on_price_update
    )

    # Start listening in an asyncio loop
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(ws_listener.listen())
    except KeyboardInterrupt:
        print("Script interrupted by user")
    finally:
        ws_listener.stop()
        db_manager.close()

if __name__ == "__main__":
    main()
```

----

5. Documentation Structure

- docs/README.md
   - Overview of the project, purpose, disclaimers, license info.
   - Quick start guide: installing dependencies, environment variables, etc.
- docs/USER_GUIDE.md
   - Detailed usage instructions (how to run main.py, how to set up API keys, how to do read-only vs. actual trading mode).
   - Explanation of core functionalities (matching BUY to SELL, how the script decides to SELL, etc.).
- docs/DEVELOPER_GUIDE.md
   - Explanation of the directory structure and module responsibilities.
   - How to extend the code with new features (like AI logic or a new trading symbol).
   - Potential improvements or known limitations.

----

6. Libraries & Notes

Below are some typical libraries (and reasons to use them) you might need in requirements.txt:

1. python-binance
 - Provides a convenient wrapper around Binance’s REST API and WebSocket.
 - Alternatively, you can use ccxt to connect to multiple exchanges with a single API.

2. websockets
 - A popular asyncio-based WebSocket client library (if not using python-binance’s built-in websocket).

3. sqlite3 (standard library) or SQLAlchemy
 - sqlite3 is built-in, no external dependency needed.
 - SQLAlchemy can simplify queries if you want an ORM style.

4. argparse
 - Standard library for command-line argument parsing.

5. logging
 - Built-in Python logging library (or you could just write logs to a file manually).

----

7. Final Thoughts

- Extensibility:
  - You can easily add your “Version 2” AI/trend logic in trader.py by replacing or augmenting the on_price_update method with more sophisticated logic.
- Robustness:
  - Consider robust error handling and try/except around REST calls.
  - Possibly implement rate limit checks in orders_manager.
- Testing:
  - For testing or “dry-run” usage, you can use --mode read_only to only see logs and skip actual trade placement.
  - You might also implement a “paper trading” approach, simulating a fill at a certain price in your local DB.
- Security:
  - Keep your API keys secure (don’t commit them in code).
  - You might want to handle them via environment variables or a .env file.

----

Summary

This plan provides:

1. Clear code organization in separate modules.
2. A single main.py entry point for orchestration.
3. Support for read-only vs. trading mode via command-line arguments.
4. Simple, comment-rich code snippets to guide your implementation.
5. Documentation for both end-users and developers in the docs folder.

You can adjust each piece to your workflow or naming standards, but this layout should be a solid foundation to implement and expand your swing-trading system.
