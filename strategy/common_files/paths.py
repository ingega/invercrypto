# invercrypto/strategy/common_files/paths.py
import csv
import json
import os
from dotenv import load_dotenv
from pathlib import Path
"""
This file maps all configurations and json necessary files
"""
# load env
PROJECT_ROOT = Path(__file__).resolve().parent.parent # get strategy folder
load_dotenv(PROJECT_ROOT / ".env")

# project root path
DATA_PATH = Path(os.environ["DATA_PATH"])

# data dir changes if 
DATA_DIR = DATA_PATH
# data folders
CONFIG_DIR = DATA_DIR / "config"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = DATA_DIR / "logs"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
# user config vars
CONFIG_FILE = CONFIG_DIR / "config.json"
TICKERS_FILE = CONFIG_DIR / "tickers.json"
# system address vars
BET_FILE = STATE_DIR / "actual_bets.json"
SECONDARY_BET_FILE = STATE_DIR / "secondary_bets.json"
OPERATIONS_FILE = STATE_DIR / "completed_operations.csv"
# balances
TICKERS_BALANCES = STATE_DIR / "tickers_balances.json"
MAIN_BALANCE = STATE_DIR / "main_balance.json"
AVAILABLE_BALANCE = STATE_DIR / "available_balance.json"
# logs
# adding more strategies, naming must be like TANGENT_LOG_FILE etc.
LOG_FILE = LOG_DIR / "engine.log"
LOG_LIVE_FILE = LOG_DIR / "engine_live.log"

# database path
DB_PATH = DATA_PATH / "operations.db"

######################################################
#      Real strategy files (live folder)             #
######################################################

# database
DB_LIVE_PATH = DATA_PATH / "operations_live.db"

# config
CONFIG_DIR_LIVE = DATA_PATH / "config" / "live"
CONFIG_DIR_LIVE.mkdir(parents=True, exist_ok=True)

CONFIG_LIVE_FILE = CONFIG_DIR_LIVE / "config.json"

# balances
MAIN_LIVE_STATE_FOLDER = DATA_PATH / "state" / "live"
MAIN_LIVE_STATE_FOLDER.mkdir(parents=True, exist_ok=True)

MAIN_BALANCE_LIVE = MAIN_LIVE_STATE_FOLDER / "main_balance.json"
AVAILABLE_BALANCE_LIVE = MAIN_LIVE_STATE_FOLDER / "available_balance.json"
TICKERS_BALANCES_LIVE = MAIN_LIVE_STATE_FOLDER / "tickers_balances.json"

# bets
DIRECT_BETS_LIVE = MAIN_LIVE_STATE_FOLDER / "direct_bets.json"
SECONDARY_BETS_LIVE = MAIN_LIVE_STATE_FOLDER / "secondary_bets.json"


# I/O files functions
def load_json_file(filepath, default_factory=dict):
    if not os.path.exists(filepath):
        return default_factory()
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default_factory()

def save_json_file(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)

def init_csv_log():
    if not os.path.exists(OPERATIONS_FILE):
        with open(OPERATIONS_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "entry_date", "ticker", "side", "entry_price", 
                "tp_price", "sl_price", "exit_date", "exit_price", "outcome"
            ])

if __name__ == "__main__":
    print(DATA_PATH)