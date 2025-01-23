"""
Configuration settings for the trading system.
Loads and validates environment variables.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path('.env')
if not env_path.exists():
    raise FileNotFoundError("The .env file is required but was not found. Please copy .env.example to .env and update the values.")
load_dotenv(dotenv_path=env_path)

# API Configuration
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
BINANCE_API_URL: str = os.getenv("BINANCE_API_URL", "https://api.binance.com")
BINANCE_STREAM_URL: str = os.getenv("BINANCE_STREAM_URL", "wss://stream.binance.com:9443")
TRADING_SYMBOL: str = os.getenv("TRADING_SYMBOL", "TRUMPUSDC")

# Trading Parameters
MIN_PROFIT_PERCENTAGE: float = float(os.getenv("MIN_PROFIT_PERCENTAGE", "0.3"))
MAX_SELL_VALUE_USDC: float = float(os.getenv("MAX_SELL_VALUE_USDC", "100"))
MAX_ORDER_USDC: float = float(os.getenv("MAX_ORDER_USDC", "100"))  # Maximum order size in USDC
POSITION_AGE_ALERT_HOURS: int = int(os.getenv("POSITION_AGE_ALERT_HOURS", "10"))

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