# invercrypto/strategy/common_files/paths.py

from pathlib import Path

"""
This file maps all configurations, and json necessary files
"""

DATA_DIR = Path("/app/data")

CONFIG_DIR = DATA_DIR / "config"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = DATA_DIR / "logs"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "config.json"
TICKERS_FILE = CONFIG_DIR / "tickers.json"

BET_FILE = STATE_DIR / "actual_bets.json"
OPERATIONS_FILE = STATE_DIR / "completed_operations.csv"