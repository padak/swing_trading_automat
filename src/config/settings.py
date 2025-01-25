"""
Configuration settings for the Binance Swing Trading Automation.

This module contains all configurable values used across the application,
ensuring consistency between local development and production environments.
Values can be overridden via environment variables.
"""

import os
from pathlib import Path
from typing import Optional, Final

from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path('.env')
if not env_path.exists():
    raise FileNotFoundError("The .env file is required but was not found. Please copy .env.example to .env and update the values.")
load_dotenv(dotenv_path=env_path)

# API Configuration
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
BINANCE_API_URL: str = "https://api.binance.com/api"
BINANCE_STREAM_URL: str = "wss://stream.binance.com:9443"
TRADING_SYMBOL: str = os.getenv("TRADING_SYMBOL", "TRUMPUSDC")

# Trading Parameters
MIN_PROFIT_PERCENTAGE: float = float(os.getenv("MIN_PROFIT_PERCENTAGE", "0.3"))
MAX_SELL_VALUE_USDC: float = float(os.getenv("MAX_SELL_VALUE_USDC", "100"))
MAX_ORDER_USDC: float = float(os.getenv("MAX_ORDER_USDC", "100"))  # Maximum order size in USDC
POSITION_AGE_ALERT_HOURS: int = int(os.getenv("POSITION_AGE_ALERT_HOURS", "10"))
POSITION_DURATION_ALERT_THRESHOLD: int = POSITION_AGE_ALERT_HOURS * 3600  # Convert hours to seconds
POSITION_DURATION_CHECK_INTERVAL: int = int(os.getenv("POSITION_DURATION_CHECK_INTERVAL", "300"))  # Check every 5 minutes

# System Configuration
DB_PATH: Path = Path(os.getenv("DB_PATH", "data/trading.db"))
LOG_PATH: Path = Path(os.getenv("LOG_PATH", "data/logs/trading.log"))
ERROR_LOG_PATH: Path = Path(os.getenv("ERROR_LOG_PATH", "data/logs/error.log"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# WebSocket Configuration
WEBSOCKET_RECONNECT_TIMEOUT: int = int(os.getenv("WEBSOCKET_RECONNECT_TIMEOUT", "900"))
WEBSOCKET_INITIAL_RETRY_DELAY: int = int(os.getenv("WEBSOCKET_INITIAL_RETRY_DELAY", "1"))
WEBSOCKET_RECONNECT_DELAY: int = int(os.getenv("WEBSOCKET_RECONNECT_DELAY", "5"))
WEBSOCKET_MAX_RETRIES: int = int(os.getenv("WEBSOCKET_MAX_RETRIES", "3"))
MAX_RECONNECTION_ATTEMPTS: int = int(os.getenv("MAX_RECONNECTION_ATTEMPTS", "5"))
WEBSOCKET_PING_INTERVAL: int = int(os.getenv("WEBSOCKET_PING_INTERVAL", "30"))
WEBSOCKET_PING_TIMEOUT: int = int(os.getenv("WEBSOCKET_PING_TIMEOUT", "10"))
REST_API_REFRESH_RATE: int = int(os.getenv("REST_API_REFRESH_RATE", "5"))
LISTEN_KEY_KEEP_ALIVE_INTERVAL: int = int(os.getenv("LISTEN_KEY_KEEP_ALIVE_INTERVAL", "1800"))  # 30 minutes in seconds

# Performance Settings
MAX_ORDER_PROCESSING_TIME: float = float(os.getenv("MAX_ORDER_PROCESSING_TIME", "0.5"))  # seconds
MAX_PRICE_UPDATE_LATENCY: float = float(os.getenv("MAX_PRICE_UPDATE_LATENCY", "0.1"))  # seconds
MAX_STATE_RECOVERY_TIME: float = float(os.getenv("MAX_STATE_RECOVERY_TIME", "1.0"))  # seconds
CONCURRENT_UPDATES_THRESHOLD: int = int(os.getenv("CONCURRENT_UPDATES_THRESHOLD", "100"))

# Logging Configuration
LOG_ROTATION_SIZE_MB: int = int(os.getenv("LOG_ROTATION_SIZE_MB", "100"))
LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# Component Shutdown Timeouts (in seconds)
# ---------------------------------------
# These values determine how long we wait for each component to shut down
# before considering it failed. Order is important as components are shut down
# in reverse dependency order.

SHUTDOWN_TIMEOUT_ORDER: Final[float] = float(os.getenv('SHUTDOWN_TIMEOUT_ORDER', '1.0'))
SHUTDOWN_TIMEOUT_PRICE: Final[float] = float(os.getenv('SHUTDOWN_TIMEOUT_PRICE', '1.0'))
SHUTDOWN_TIMEOUT_STATE: Final[float] = float(os.getenv('SHUTDOWN_TIMEOUT_STATE', '2.0'))
THREAD_SHUTDOWN_TIMEOUT: Final[float] = float(os.getenv('THREAD_SHUTDOWN_TIMEOUT', '5.0'))
THREAD_TIMEOUT: Final[float] = float(os.getenv('THREAD_TIMEOUT', '180.0'))  # 3 minutes before thread considered stale

# Monitoring Intervals (in seconds)
# -------------------------------
# These values control how frequently different monitoring operations occur.
# Shorter intervals mean faster response but more CPU usage.

MONITOR_LOOP_INTERVAL: Final[float] = float(os.getenv('MONITOR_LOOP_INTERVAL', '0.1'))
POSITION_CHECK_INTERVAL: Final[float] = float(os.getenv('POSITION_CHECK_INTERVAL', '0.1'))
PRICE_UPDATE_INTERVAL: Final[float] = float(os.getenv('PRICE_UPDATE_INTERVAL', '0.1'))
STATE_RECONCILE_INTERVAL: Final[float] = float(os.getenv('STATE_RECONCILE_INTERVAL', '0.1'))

# WebSocket Settings
# ----------------
# Configuration for WebSocket connections and reconnection behavior

WEBSOCKET_CLOSE_TIMEOUT: Final[float] = float(os.getenv('WEBSOCKET_CLOSE_TIMEOUT', '1.0'))

# Database Settings
# ---------------
# Configuration for database operations and connection pool

DB_POOL_SIZE: Final[int] = int(os.getenv('DB_POOL_SIZE', '5'))
DB_POOL_TIMEOUT: Final[float] = float(os.getenv('DB_POOL_TIMEOUT', '2.0'))
DB_TRANSACTION_TIMEOUT: Final[float] = float(os.getenv('DB_TRANSACTION_TIMEOUT', '1.0'))

# Trading Settings
# --------------
# Configuration for order placement and management

MIN_ORDER_QUANTITY: Final[float] = float(os.getenv('MIN_ORDER_QUANTITY', '0.01'))
PROFIT_MARGIN: Final[float] = float(os.getenv('PROFIT_MARGIN', '0.02'))  # 2%
MAX_POSITION_DURATION: Final[int] = int(os.getenv('MAX_POSITION_DURATION', '86400'))  # 24 hours
ORDER_CHECK_INTERVAL: Final[float] = float(os.getenv('ORDER_CHECK_INTERVAL', '10.0'))  # Fallback REST polling interval when WebSocket is down

# API Settings
# ----------
# Configuration for API endpoints and timeouts

API_REQUEST_TIMEOUT: Final[float] = float(os.getenv('API_REQUEST_TIMEOUT', '5.0'))
API_KEEPALIVE_TIMEOUT: Final[float] = float(os.getenv('API_KEEPALIVE_TIMEOUT', '30.0'))

def validate_config() -> Optional[str]:
    """
    Validate the configuration settings.
    
    Returns:
        Optional[str]: Error message if validation fails, None if successful
    """
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return "Missing Binance API credentials"
    
    if MIN_PROFIT_PERCENTAGE <= 0:
        return "MIN_PROFIT_PERCENTAGE must be greater than 0"
    
    if MAX_SELL_VALUE_USDC <= 0:
        return "MAX_SELL_VALUE_USDC must be greater than 0"
    
    if POSITION_AGE_ALERT_HOURS <= 0:
        return "POSITION_AGE_ALERT_HOURS must be greater than 0"
    
    if WEBSOCKET_RECONNECT_DELAY <= 0:
        return "WEBSOCKET_RECONNECT_DELAY must be greater than 0"
    
    if WEBSOCKET_MAX_RETRIES <= 0:
        return "WEBSOCKET_MAX_RETRIES must be greater than 0"
    
    if MAX_RECONNECTION_ATTEMPTS <= 0:
        return "MAX_RECONNECTION_ATTEMPTS must be greater than 0"
    
    if WEBSOCKET_PING_INTERVAL <= 0:
        return "WEBSOCKET_PING_INTERVAL must be greater than 0"
    
    if WEBSOCKET_PING_TIMEOUT <= 0:
        return "WEBSOCKET_PING_TIMEOUT must be greater than 0"
    
    if MAX_ORDER_PROCESSING_TIME <= 0:
        return "MAX_ORDER_PROCESSING_TIME must be greater than 0"
    
    if MAX_PRICE_UPDATE_LATENCY <= 0:
        return "MAX_PRICE_UPDATE_LATENCY must be greater than 0"
    
    if MAX_STATE_RECOVERY_TIME <= 0:
        return "MAX_STATE_RECOVERY_TIME must be greater than 0"
    
    if CONCURRENT_UPDATES_THRESHOLD <= 0:
        return "CONCURRENT_UPDATES_THRESHOLD must be greater than 0"
    
    # Create necessary directories if they don't exist
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    return None

def validate_settings():
    """Validate that all settings are within acceptable ranges."""
    assert 0 < SHUTDOWN_TIMEOUT_ORDER <= 5, "Shutdown timeout must be between 0 and 5 seconds"
    assert 0 < SHUTDOWN_TIMEOUT_PRICE <= 5, "Shutdown timeout must be between 0 and 5 seconds"
    assert 0 < SHUTDOWN_TIMEOUT_STATE <= 5, "Shutdown timeout must be between 0 and 5 seconds"
    assert 0 < THREAD_SHUTDOWN_TIMEOUT <= 10, "Thread shutdown timeout must be between 0 and 10 seconds"
    assert 60 <= THREAD_TIMEOUT <= 300, "Thread timeout must be between 1 and 5 minutes"
    
    assert 0 < MONITOR_LOOP_INTERVAL <= 1, "Monitor interval must be between 0 and 1 second"
    assert 0 < POSITION_CHECK_INTERVAL <= 1, "Position check interval must be between 0 and 1 second"
    assert 0 < PRICE_UPDATE_INTERVAL <= 1, "Price update interval must be between 0 and 1 second"
    assert 0 < STATE_RECONCILE_INTERVAL <= 1, "State reconcile interval must be between 0 and 1 second"
    assert ORDER_CHECK_INTERVAL >= 10, "Order check interval must be at least 10 seconds when in fallback mode"
    
    assert 0 < DB_POOL_SIZE <= 10, "DB pool size must be between 1 and 10"
    assert DB_POOL_TIMEOUT > 0, "DB pool timeout must be positive"
    
    assert MIN_ORDER_QUANTITY > 0, "Minimum order quantity must be positive"
    assert 0 < PROFIT_MARGIN < 1, "Profit margin must be between 0 and 1"
    assert MAX_POSITION_DURATION > 0, "Maximum position duration must be positive"

# Validate settings on module import
validate_settings() 