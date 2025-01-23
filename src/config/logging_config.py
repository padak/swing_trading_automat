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

from .settings import (
    LOG_PATH,
    ERROR_LOG_PATH,
    LOG_LEVEL,
    LOG_ROTATION_SIZE_MB,
    LOG_BACKUP_COUNT
)

def setup_logging() -> None:
    """Configure the logging system with both file and console outputs."""
    
    # Set up standard logging
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
    
    # Configure structlog processors
    processors: list[Processor] = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ]
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Get the root logger and add handlers
    root_logger = logging.getLogger()
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)

def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a logger instance with the given name.
    
    Args:
        name: The name of the logger (usually __name__ of the module)
        
    Returns:
        structlog.BoundLogger: A configured logger instance
    """
    return structlog.get_logger(name)

# Example usage:
# logger = get_logger(__name__)
# logger.info("message", extra_field="value")
# logger.error("error occurred", error="details", stack=True) 