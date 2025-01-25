"""
Logging configuration for the trading system.
Sets up structured logging with file rotation.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Dict, Any

import structlog
from structlog.types import Processor
from structlog.stdlib import LoggerFactory

from .settings import (
    LOG_PATH,
    ERROR_LOG_PATH,
    LOG_LEVEL,
    LOG_ROTATION_SIZE_MB,
    LOG_BACKUP_COUNT
)

def setup_logging() -> None:
    """Configure the logging system with structured logging and file rotation."""
    
    # Set timestamp format for all loggers
    structlog.configure(
        processors=[
            # Add timestamps to all log entries
            structlog.processors.TimeStamper(fmt="iso"),
            # Add log level
            structlog.stdlib.add_log_level,
            # Add caller info
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # If log level is ERROR, add stack info
            structlog.processors.StackInfoRenderer(),
            # Format any exceptions
            structlog.processors.format_exc_info,
            # Ensure all strings are unicode
            structlog.processors.UnicodeDecoder(),
            # Convert to JSON format
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, LOG_LEVEL.upper())
    )
    
    # Configure file handlers
    main_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_ROTATION_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT
    )
    
    error_handler = RotatingFileHandler(
        ERROR_LOG_PATH,
        maxBytes=LOG_ROTATION_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT
    )
    error_handler.setLevel(logging.ERROR)
    
    # Get the root logger and add handlers
    root_logger = logging.getLogger()
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance with the given name.
    
    Args:
        name: The name of the logger (usually __name__ of the module)
        
    Returns:
        structlog.stdlib.BoundLogger: A configured structured logger instance
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing order", order_id="123", amount=100)
        >>> logger.error("Order failed", order_id="123", error="Insufficient funds")
    """
    return structlog.get_logger(name)

# Initialize logging on module import
setup_logging()

# Example usage:
# logger = get_logger(__name__)
# logger.info("message", extra_field="value")
# logger.error("error occurred", error="details", stack=True) 