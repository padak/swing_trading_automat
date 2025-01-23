"""
Configuration settings for the trading system.
Loads and validates environment variables.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Configuration
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
TRADING_SYMBOL: str = os.getenv("TRADING_SYMBOL", "TRUMPUSDC")

# Trading Parameters
MIN_PROFIT_PERCENTAGE: float = float(os.getenv("MIN_PROFIT_PERCENTAGE", "0.3"))
MAX_SELL_VALUE_USDC: float = float(os.getenv("MAX_SELL_VALUE_USDC", "100"))
POSITION_AGE_ALERT_HOURS: int = int(os.getenv("POSITION_AGE_ALERT_HOURS", "10"))

# System Configuration
DB_PATH: Path = Path(os.getenv("DB_PATH", "data/trading.db"))
LOG_PATH: Path = Path(os.getenv("LOG_PATH", "data/logs/trading.log"))
ERROR_LOG_PATH: Path = Path(os.getenv("ERROR_LOG_PATH", "data/logs/error.log"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# WebSocket Configuration
WEBSOCKET_RECONNECT_TIMEOUT: int = int(os.getenv("WEBSOCKET_RECONNECT_TIMEOUT", "900"))
WEBSOCKET_INITIAL_RETRY_DELAY: int = int(os.getenv("WEBSOCKET_INITIAL_RETRY_DELAY", "1"))
REST_API_REFRESH_RATE: int = int(os.getenv("REST_API_REFRESH_RATE", "5"))

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
    
    # Create necessary directories if they don't exist
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    return None 