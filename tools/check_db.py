#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from sqlalchemy import inspect, text
from src.db.operations import get_db
from src.db.models import Base, Order, SystemState
from src.config.logging_config import setup_logging, get_logger

def check_tables_exist(inspector, logger):
    """Check if all required tables exist."""
    existing_tables = inspector.get_table_names()
    required_tables = [t.__tablename__ for t in Base.__subclasses__()]
    
    logger.info("Checking database tables", existing=existing_tables, required=required_tables)
    
    missing_tables = set(required_tables) - set(existing_tables)
    if missing_tables:
        logger.error("Missing tables detected", missing=list(missing_tables))
        return False
        
    return True

def check_table_columns(inspector, table_name, logger):
    """Check columns in a table."""
    columns = inspector.get_columns(table_name)
    logger.info(f"Table {table_name} columns:", columns=[c['name'] for c in columns])
    return columns

def check_table_constraints(inspector, table_name, logger):
    """Check foreign keys and other constraints."""
    foreign_keys = inspector.get_foreign_keys(table_name)
    primary_keys = inspector.get_pk_constraint(table_name)
    indexes = inspector.get_indexes(table_name)
    
    logger.info(
        f"Table {table_name} constraints:",
        foreign_keys=foreign_keys,
        primary_keys=primary_keys,
        indexes=indexes
    )

def check_system_state(db, logger):
    """Check system state record."""
    try:
        with db() as session:
            state = session.query(SystemState).first()
            if state:
                logger.info(
                    "System state record found",
                    websocket_status=state.websocket_status,
                    last_processed_time=state.last_processed_time
                )
            else:
                logger.warning("No system state record found")
    except Exception as e:
        logger.error("Error checking system state", error=str(e))

def check_orders(db, logger):
    """Check orders table data."""
    try:
        with db() as session:
            orders = session.query(Order).all()
            logger.info(f"Found {len(orders)} orders")
            
            # Check for any orders with invalid status
            for order in orders:
                logger.info(
                    "Order details",
                    id=order.id,
                    binance_order_id=order.binance_order_id,
                    status=order.status,
                    side=order.side
                )
    except Exception as e:
        logger.error("Error checking orders", error=str(e))

def main():
    """Main database check function."""
    setup_logging()
    logger = get_logger(__name__)
    
    try:
        with get_db() as db:
            inspector = inspect(db.get_bind())
            
            # Check tables
            if not check_tables_exist(inspector, logger):
                logger.error("Database schema verification failed")
                return
                
            # Check each table's structure
            for table_name in inspector.get_table_names():
                check_table_columns(inspector, table_name, logger)
                check_table_constraints(inspector, table_name, logger)
            
            # Check data
            check_system_state(get_db, logger)
            check_orders(get_db, logger)
            
            logger.info("Database check completed")
            
    except Exception as e:
        logger.error("Database check failed", error=str(e))
        raise

if __name__ == "__main__":
    main() 