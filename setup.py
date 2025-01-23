from setuptools import setup, find_packages

setup(
    name="swing_trading_automat",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "python-binance>=1.0.19",
        "SQLAlchemy>=2.0.0",
        "websockets>=12.0",
        "websocket-client>=1.7.0",  # Added for test dependencies
        "python-dotenv>=1.0.0",
        "structlog>=24.1.0",
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
        "pytest-mock>=3.12.0",
        "pytest-cov>=4.1.0",
        "mypy>=1.8.0",
        "types-python-dateutil>=2.8.19.14",
        "black>=24.1.0",
        "isort>=5.13.0",
        "flake8>=7.0.0",
        "psutil>=5.9.6",
        "memory-profiler>=0.61.0",
    ],
    python_requires=">=3.8",
) 