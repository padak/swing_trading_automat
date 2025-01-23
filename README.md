# Binance Swing Trading Automation

An automated trading system for swing trading on Binance, focusing on managing SELL orders for existing BUY positions.

## Features

- Real-time price monitoring via WebSocket with REST API fallback
- Automated SELL order placement with configurable profit targets
- Independent handling of partial fills
- Position duration tracking and alerts
- Comprehensive order validation and state management
- Persistent state storage with SQLite
- Robust error handling and recovery

## Requirements

- Python 3.8+
- Binance API credentials
- SQLite3

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/yourusername/swing_trading_automat.git
cd swing_trading_automat
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your Binance API credentials and preferences
```

5. Run the application:
```bash
python main.py
```

## Documentation

- [User Guide](docs/user_guide/README.md) - Detailed usage instructions
- [API Documentation](docs/api/README.md) - Internal API reference
- [Deployment Guide](docs/deployment/README.md) - Production deployment instructions
- [Design Documentation](PRODUCTION_DESIGN.md) - System architecture and design

## Project Structure

```
binance_swing_trading/
├── src/                    # Source code
│   ├── config/            # Configuration management
│   ├── core/              # Core trading logic
│   ├── db/               # Database operations
│   └── utils/            # Utility functions
├── tools/                 # CLI utilities
├── tests/                # Test suite
├── docs/                 # Documentation
│   ├── user_guide/      # User documentation
│   ├── api/             # API documentation
│   └── deployment/      # Deployment guides
└── data/                 # Data directory
    ├── trading.db       # SQLite database
    └── logs/            # Log files
```

## Configuration

Key configuration parameters in `.env`:

- `BINANCE_API_KEY` - Your Binance API key
- `BINANCE_API_SECRET` - Your Binance API secret
- `TRADING_SYMBOL` - Trading pair (e.g., TRUMPUSDC)
- `MIN_PROFIT_PERCENTAGE` - Minimum profit target (default: 0.3%)
- `MAX_SELL_VALUE_USDC` - Maximum order size in USDC

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Binance API documentation
- Python-Binance library
- SQLAlchemy ORM 