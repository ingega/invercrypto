# invercrypto/strategy/database.py
# alpha listed importations
import sqlite3
from common_files.logger import get_logger
from common_files.paths import DB_PATH

logger = get_logger(__name__)
    
    

def init_operations_db() -> None:
    """
    Initializes the SQLite database and creates the operations 
    table if it does not exist.
    Includes a composite index to keep historical ML feature fetches 
    lightning-fast.
    """
    # debug
    logger.info(f"DB_PATH = {DB_PATH}")
    logger.info(f"Parent = {DB_PATH.parent}")
    logger.info(f"Exists = {DB_PATH.parent.exists()}")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Enable Write-Ahead Logging for high-frequency concurrency updates
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tangent_completed_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                tangent REAL NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                tp REAL NOT NULL,
                sl REAL NOT NULL,
                exit_date TEXT NOT NULL,
                exit_price REAL NOT NULL,
                outcome TEXT NOT NULL
            );
        """)
        # Composite Index to radically accelerate future Machine Learning data fetching
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_outcome 
            ON tangent_completed_operations (ticker, outcome);
        """)
        conn.commit()

def save_operation_to_db(data: tuple) -> None:
    """
    Safely records a resolved direct bet into the SQLite data layer.
    """
    query = """
        INSERT INTO tangent_completed_operations (
            strategy, entry_date, ticker, tangent, side, entry_price, tp, sl, exit_date, 
            exit_price, outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """ 
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, data)
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"❌ DATABASE INSERTION FAILURE: {str(e)}")

if __name__ == "__main__":
    init_operations_db()
    print("database already created")
