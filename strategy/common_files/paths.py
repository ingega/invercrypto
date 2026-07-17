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
PROJECT_ROOT = Path(__file__).resolve().parent.parent # get strategy
load_dotenv(PROJECT_ROOT / ".env")

# data path
DATA_DIR = Path("/app/data")
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
OPERATIONS_FILE = STATE_DIR / "completed_operations.csv"

# project root path
DATA_PATH = Path(os.environ["DATA_PATH"])
DB_PATH = DATA_PATH / "operations.db"

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