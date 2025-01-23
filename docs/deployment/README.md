# Deployment Guide

## Table of Contents

1. [Production Setup](#production-setup)
2. [System Requirements](#system-requirements)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Monitoring](#monitoring)
6. [Maintenance](#maintenance)
7. [Backup & Recovery](#backup--recovery)

## Production Setup

### System Requirements

#### Minimum Requirements
- CPU: 2 cores
- RAM: 4GB
- Storage: 20GB
- Network: Stable internet connection
- Python 3.8+
- SQLite3

#### Recommended Requirements
- CPU: 4 cores
- RAM: 8GB
- Storage: 50GB SSD
- Network: High-speed, low-latency connection

### Operating System Setup

1. Update system packages:
```bash
sudo apt update
sudo apt upgrade -y
```

2. Install dependencies:
```bash
sudo apt install -y python3-pip python3-venv sqlite3
```

## Installation

### Application Setup

1. Create application directory:
```bash
sudo mkdir -p /opt/swing_trading
sudo chown -R $USER:$USER /opt/swing_trading
```

2. Clone repository:
```bash
cd /opt/swing_trading
git clone https://github.com/yourusername/swing_trading_automat.git
cd swing_trading_automat
```

3. Create virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Service Setup

1. Create systemd service file:
```bash
sudo nano /etc/systemd/system/swing_trading.service
```

2. Add service configuration:
```ini
[Unit]
Description=Swing Trading Automation
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/opt/swing_trading/swing_trading_automat
Environment=PATH=/opt/swing_trading/swing_trading_automat/venv/bin:$PATH
ExecStart=/opt/swing_trading/swing_trading_automat/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

3. Enable and start service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable swing_trading
sudo systemctl start swing_trading
```

## Configuration

### Environment Setup

1. Create production environment file:
```bash
cp .env.example .env.production
```

2. Configure production settings:
```ini
# API Configuration
BINANCE_API_KEY=your_production_api_key
BINANCE_API_SECRET=your_production_api_secret
TRADING_SYMBOL=TRUMPUSDC

# Trading Parameters
MIN_PROFIT_PERCENTAGE=0.3
MAX_SELL_VALUE_USDC=100
POSITION_AGE_ALERT_HOURS=10

# System Configuration
DB_PATH=/opt/swing_trading/data/trading.db
LOG_PATH=/opt/swing_trading/data/logs/trading.log
ERROR_LOG_PATH=/opt/swing_trading/data/logs/error.log
LOG_LEVEL=INFO
```

### Log Rotation

1. Create logrotate configuration:
```bash
sudo nano /etc/logrotate.d/swing_trading
```

2. Add rotation rules:
```
/opt/swing_trading/data/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 your_username your_username
}
```

## Monitoring

### System Monitoring

1. Check service status:
```bash
sudo systemctl status swing_trading
```

2. View logs:
```bash
journalctl -u swing_trading -f
```

3. Monitor application logs:
```bash
tail -f /opt/swing_trading/data/logs/trading.log
```

### Performance Monitoring

1. Monitor system resources:
```bash
top -u your_username
```

2. Check disk usage:
```bash
df -h /opt/swing_trading
```

3. Monitor database size:
```bash
ls -lh /opt/swing_trading/data/trading.db
```

## Maintenance

### Regular Tasks

1. Log cleanup:
```bash
find /opt/swing_trading/data/logs -name "*.gz" -mtime +30 -delete
```

2. Database maintenance:
```bash
sqlite3 /opt/swing_trading/data/trading.db "VACUUM;"
```

3. Update application:
```bash
cd /opt/swing_trading/swing_trading_automat
git pull
source venv/bin/activate
pip install -e .
sudo systemctl restart swing_trading
```

### Health Checks

1. Check WebSocket connection:
```bash
python -m tools.manage_positions status
```

2. Verify database integrity:
```bash
sqlite3 /opt/swing_trading/data/trading.db "PRAGMA integrity_check;"
```

## Backup & Recovery

### Backup Procedures

1. Database backup:
```bash
mkdir -p /opt/swing_trading/backups
sqlite3 /opt/swing_trading/data/trading.db ".backup '/opt/swing_trading/backups/trading_$(date +%Y%m%d).db'"
```

2. Configuration backup:
```bash
cp /opt/swing_trading/swing_trading_automat/.env.production /opt/swing_trading/backups/env_$(date +%Y%m%d)
```

### Recovery Procedures

1. Database recovery:
```bash
sudo systemctl stop swing_trading
cp /opt/swing_trading/backups/trading_YYYYMMDD.db /opt/swing_trading/data/trading.db
sudo systemctl start swing_trading
```

2. Configuration recovery:
```bash
cp /opt/swing_trading/backups/env_YYYYMMDD /opt/swing_trading/swing_trading_automat/.env.production
sudo systemctl restart swing_trading
```

### Emergency Procedures

1. Emergency shutdown:
```bash
sudo systemctl stop swing_trading
```

2. State verification:
```bash
python -m tools.manage_positions verify
```

3. System recovery:
```bash
python -m tools.manage_positions recover
sudo systemctl start swing_trading
``` 