#!/usr/bin/env python3
"""Simple script to test Binance API connection and WebSocket."""

import os
import sys
import json
import asyncio
from binance import AsyncClient, BinanceSocketManager
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_api_connection():
    """Test REST API connection and permissions."""
    print("\n=== Testing Binance API Connection ===\n")
    
    # Load environment variables
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    print(f"Loading .env from: {env_path}")
    load_dotenv(env_path)
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    symbol = os.getenv('TRADING_SYMBOL', 'TRUMPUSDC')
    
    # Debug: Print partial key for verification
    if api_key:
        print(f"API Key loaded (showing first/last 4 chars): {api_key[:4]}...{api_key[-4:]}")
    else:
        print("No API key found in environment")
        
    if api_secret:
        print(f"API Secret loaded (length): {len(api_secret)} chars")
    else:
        print("No API secret found in environment")
    
    if not api_key or not api_secret:
        print("Error: API credentials not found in .env file")
        return
    
    try:
        # Initialize async client
        client = await AsyncClient.create(api_key, api_secret)
        
        try:
            # Test API connection
            server_time = await client.get_server_time()
            print("\n✓ Successfully connected to Binance API")
            
            # Test account access
            print("\n=== Account Information ===")
            account = await client.get_account()
            print("✓ Successfully accessed account information")
            print(f"Account type: {account.get('accountType', 'Not specified')}")
            print(f"Can trade: {account.get('canTrade', False)}")
            print(f"Can withdraw: {account.get('canWithdraw', False)}")
            print(f"Can deposit: {account.get('canDeposit', False)}")
            
            # Show permissions
            permissions = account.get('permissions', [])
            print("\n=== Account Permissions ===")
            print(f"Raw permissions: {permissions}")
            
            # Test market data access
            print("\n=== Market Information ===")
            exchange_info = await client.get_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                print("✓ Successfully retrieved TRUMPUSDC market data")
                print(f"Symbol status: {symbol_info.get('status')}")
                print(f"Base asset: {symbol_info.get('baseAsset')}")
                print(f"Quote asset: {symbol_info.get('quoteAsset')}")
                
                # Get current price
                ticker = await client.get_symbol_ticker(symbol=symbol)
                print(f"\nCurrent price: {ticker['price']}")
            else:
                print("✗ Could not find TRUMPUSDC market data")
                
            # Test balance
            print("\n=== Asset Balances ===")
            balances = [b for b in account.get('balances', []) if float(b['free']) > 0 or float(b['locked']) > 0]
            for balance in balances:
                print(f"{balance['asset']}:")
                print(f"  Free: {balance['free']}")
                print(f"  Locked: {balance['locked']}")
                
            # Test WebSocket connections
            await test_websockets(client, symbol.lower())
                
        finally:
            await client.close_connection()
            
    except Exception as e:
        print(f"\nError connecting to Binance: {str(e)}")
        print("\nFull error details:")
        import traceback
        traceback.print_exc()

async def test_websockets(client: AsyncClient, symbol: str):
    """
    Test both market data and user data WebSocket streams.
    
    Args:
        client: Binance AsyncClient instance
        symbol: Trading symbol in lowercase
    """
    print("\n=== Testing WebSocket Connections ===\n")
    
    # Track message receipt
    received_trade = asyncio.Event()
    received_user = asyncio.Event()
    
    async def process_message(msg, event, name):
        """Process a message from any socket."""
        print(f"\n✓ Received {name} message:")
        print(json.dumps(msg, indent=2))
        event.set()
    
    try:
        bsm = BinanceSocketManager(client)
        
        # Start trade socket
        print("\nStarting trade socket...")
        async with bsm.trade_socket(symbol) as ts:
            # Start user socket
            print("Starting user socket...")
            async with bsm.user_socket() as us:
                print("✓ WebSocket connections established")
                
                # Create message handling tasks
                trade_task = asyncio.create_task(process_message(
                    await ts.recv(), received_trade, "trade"))
                user_task = asyncio.create_task(process_message(
                    await us.recv(), received_user, "user"))
                
                # Wait for messages with timeout
                try:
                    print("\nWaiting for WebSocket messages...")
                    await asyncio.wait_for(asyncio.gather(
                        trade_task,
                        user_task
                    ), timeout=15.0)
                    print("\n✓ All WebSocket tests passed!")
                except asyncio.TimeoutError:
                    print("\n✗ WebSocket test timeout after 15 seconds:")
                    print(f"Received trade message: {received_trade.is_set()}")
                    print(f"Received user message: {received_user.is_set()}")
        
    except Exception as e:
        print(f"\n✗ Error in WebSocket test: {str(e)}")
        print("Full error details:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(test_api_connection())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"\nTest failed: {e}") 