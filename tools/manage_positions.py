#!/usr/bin/env python3
"""
CLI utility for manual position management.
Allows viewing and managing trading positions.
"""
import argparse
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.config.logging_config import get_logger
from src.core.price_manager import PriceManager
from src.core.order_manager import OrderManager
from src.core.state_manager import StateManager
from src.db.operations import get_db, get_order_by_id, get_open_orders
from src.db.models import Order, OrderStatus

logger = get_logger(__name__)

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"

def format_price(price: float) -> str:
    """Format price with appropriate precision."""
    return f"{price:.4f}"

def print_position(position: Dict[str, Any]) -> None:
    """Print position details in a readable format."""
    duration = format_duration(position['duration_seconds']) if position['duration_seconds'] else 'N/A'
    print(f"\nPosition {position['order_id']}:")
    print(f"  Symbol:    {position['symbol']}")
    print(f"  Quantity:  {position['quantity']}")
    print(f"  Price:     {format_price(position['price'])} USDC")
    print(f"  Status:    {position['status']}")
    print(f"  Duration:  {duration}")

def print_system_status(state_manager: StateManager) -> None:
    """Print current system status."""
    summary = state_manager.get_system_summary()
    
    print("\nSystem Status:")
    print(f"  State:     {summary['status']}")
    print(f"  WebSocket: {summary['websocket_status']}")
    if summary['last_price_update']:
        last_update = (datetime.utcnow() - summary['last_price_update']).total_seconds()
        print(f"  Last Update: {format_duration(last_update)} ago")
    print(f"  Open Orders: {summary['open_orders']}")
    
    if not state_manager.is_healthy():
        print("\n⚠️  System is not in a healthy state!")

def list_positions(state_manager: StateManager) -> None:
    """List all open positions."""
    summary = state_manager.get_system_summary()
    
    print_system_status(state_manager)
    
    if not summary['positions']:
        print("\nNo open positions.")
        return
    
    print("\nOpen Positions:")
    for position in summary['positions']:
        print_position(position)

def view_position(
    state_manager: StateManager,
    order_id: str
) -> None:
    """View details of a specific position."""
    with get_db() as db:
        order = get_order_by_id(db, order_id)
        if not order:
            print(f"\nPosition {order_id} not found.")
            return
    
    duration = state_manager.order_manager.get_position_duration(order_id)
    position = {
        'order_id': order.order_id,
        'symbol': order.symbol,
        'quantity': order.quantity,
        'price': order.price,
        'status': order.status.value,
        'duration_seconds': duration
    }
    
    print_system_status(state_manager)
    print_position(position)

def place_buy_order(
    order_manager: OrderManager,
    quantity: float,
    price: Optional[float] = None
) -> None:
    """Place a new buy order."""
    order_id = order_manager.place_buy_order(quantity, price)
    if order_id:
        print(f"\nBuy order placed successfully: {order_id}")
        if price:
            print(f"Limit price: {format_price(price)} USDC")
        print(f"Quantity: {quantity}")
    else:
        print("\nFailed to place buy order.")

def place_sell_order(
    order_manager: OrderManager,
    buy_order_id: str,
    quantity: float
) -> None:
    """Place a sell order for an existing position."""
    order_id = order_manager.place_sell_order(buy_order_id, quantity)
    if order_id:
        print(f"\nSell order placed successfully: {order_id}")
        print(f"For buy order: {buy_order_id}")
        print(f"Quantity: {quantity}")
    else:
        print("\nFailed to place sell order.")

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Manage trading positions manually."
    )
    
    # Create subparsers for commands
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    subparsers.add_parser(
        'list',
        help='List all open positions'
    )
    
    # View command
    view_parser = subparsers.add_parser(
        'view',
        help='View specific position details'
    )
    view_parser.add_argument(
        'order_id',
        help='Order ID to view'
    )
    
    # Buy command
    buy_parser = subparsers.add_parser(
        'buy',
        help='Place a buy order'
    )
    buy_parser.add_argument(
        'quantity',
        type=float,
        help='Quantity to buy'
    )
    buy_parser.add_argument(
        '--price',
        type=float,
        help='Limit price (optional, market order if not specified)'
    )
    
    # Sell command
    sell_parser = subparsers.add_parser(
        'sell',
        help='Place a sell order for an existing position'
    )
    sell_parser.add_argument(
        'buy_order_id',
        help='Buy order ID to sell against'
    )
    sell_parser.add_argument(
        'quantity',
        type=float,
        help='Quantity to sell'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    try:
        # Initialize components
        price_manager = PriceManager()
        order_manager = OrderManager(price_manager)
        state_manager = StateManager(price_manager, order_manager)
        
        # Start managers
        price_manager.start()
        state_manager.start()
        
        # Execute command
        if args.command == 'list':
            list_positions(state_manager)
        
        elif args.command == 'view':
            view_position(state_manager, args.order_id)
        
        elif args.command == 'buy':
            place_buy_order(order_manager, args.quantity, args.price)
        
        elif args.command == 'sell':
            place_sell_order(order_manager, args.buy_order_id, args.quantity)
        
        else:
            parser.print_help()
        
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        logger.error("Command failed", error=str(e))
        print(f"\nError: {str(e)}")
        sys.exit(1)
    finally:
        # Cleanup
        if 'state_manager' in locals():
            state_manager.stop()
        if 'price_manager' in locals():
            price_manager.stop()

if __name__ == '__main__':
    main() 