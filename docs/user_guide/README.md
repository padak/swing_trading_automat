# User Guide

## Table of Contents

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Usage](#usage)
4. [Monitoring](#monitoring)
5. [Troubleshooting](#troubleshooting)

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Git
- SQLite3
- Binance account with API access

### Step-by-Step Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/swing_trading_automat.git
cd swing_trading_automat
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the package in development mode:
```bash
pip install -e .
```

## Configuration

### Environment Variables

1. Create your environment file:
```bash
cp .env.example .env
```

2. Edit `.env` with your settings:
```ini
# API Configuration
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
TRADING_SYMBOL=TRUMPUSDC

# Trading Parameters
MIN_PROFIT_PERCENTAGE=0.3
MAX_SELL_VALUE_USDC=100
POSITION_AGE_ALERT_HOURS=10
```

### Trading Parameters

- `TRADING_SYMBOL`: The trading pair to monitor (e.g., TRUMPUSDC)
- `MIN_PROFIT_PERCENTAGE`: Minimum profit target for SELL orders (default: 0.3%)
- `MAX_SELL_VALUE_USDC`: Maximum order size in USDC (default: 100)
- `POSITION_AGE_ALERT_HOURS`: Alert threshold for position age (default: 10)

## Usage

### Starting the Application

1. Ensure your virtual environment is activated:
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Run the application:
```bash
python main.py
```

### Managing Positions

Use the CLI utility for manual position management:
```bash
python -m tools.manage_positions list  # List all positions
python -m tools.manage_positions view <order_id>  # View specific position
python -m tools.manage_positions cancel <order_id>  # Cancel an order
```

## Monitoring

### Log Files

- Main log: `data/logs/trading.log`
- Error log: `data/logs/error.log`

### System Status

Monitor the application status through:
1. Log files in `data/logs/`
2. SQLite database at `data/trading.db`
3. CLI utility status command:
```bash
python -m tools.manage_positions status
```

## Troubleshooting

### Common Issues

1. WebSocket Connection Issues
   - Check your internet connection
   - Verify API credentials
   - Check Binance API server status

2. Database Errors
   - Ensure SQLite is installed
   - Check file permissions for data directory
   - Verify database file is not corrupted

3. Order Placement Failures
   - Verify sufficient balance
   - Check order size limits
   - Validate trading pair availability

### Error Recovery

1. Application Crashes
   - Check error logs at `data/logs/error.log`
   - Restart the application
   - State will be recovered automatically

2. Invalid Configuration
   - Verify .env file settings
   - Check log files for configuration errors
   - Ensure API credentials are valid

### Getting Help

1. Check the error logs
2. Review the documentation
3. Submit an issue on GitHub with:
   - Error message
   - Log snippets
   - Steps to reproduce 