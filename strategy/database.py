# invercrypto/strategy/database.py
# alpha listed importations
import sqlite3
import traceback
from data_classes import CompletedOperation, PartialOperation, UpdateCompletedOperation, UpdatePartialOperation
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
            CREATE TABLE IF NOT EXISTS completed_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                ticker TEXT NOT NULL,
                outcome TEXT NOT NULL,
                gain REAL NOT NULL,
                capital REAL NOT NULL,
                profit REAL NOT NULL
            );
        """)
        # Composite Index to radically accelerate future Machine Learning data fetching
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_outcome 
            ON completed_operations (ticker, outcome);
        """)
        conn.commit()

        # second table
        cursor.execute("""
                CREATE TABLE IF NOT EXISTS partial_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id INTEGER NOT NULL,
                    entry_date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    tp REAL NOT NULL,
                    sl REAL NOT NULL,
                    exit_date TEXT NOT NULL,
                    exit_price REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    gain REAL NOT NULL,
                    bet TEXT NOT NULL
                );
            """)
        # Composite Index to radically accelerate future Machine Learning data fetching
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entry_date_outcome 
            ON partial_operations (entry_date, outcome);
        """)
        conn.commit()

def save_operation_to_db(operation: CompletedOperation) -> int | None:
    """
    Safely records a resolved direct bet into the SQLite data layer.
    """
    query = """
        INSERT INTO completed_operations (
            operation_id, strategy, ticker, outcome, gain, capital, profit  
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """ 
    print("operation id debug:", operation.operation_id)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, operation.as_tuple())
            conn.commit()
            logger.info(f"🟢 [DB] record for {operation.ticker} added to completed_operations" 
                        f" table with operation_id {operation.operation_id}")
            return cursor.lastrowid
    except sqlite3.Error as e:
       logger.error(f"❌ DATABASE COMP INSERTION FAILURE: {str(e)}")
       return 0

def save_partial_operation_to_db(partial_operation: PartialOperation) -> int | None:
    """
    Safely records a resolved direct bet into the SQLite data layer.
    """
    query = """
        INSERT INTO partial_operations (
            operation_id, entry_date, side, entry_price, tp, sl, 
            exit_date, exit_price, outcome, gain, bet  
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """ 
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, partial_operation.as_tuple())
            conn.commit()
            logger.info("🟢 [DB] record added to partial_operations table with"
                        f" operation id: {partial_operation.operation_id}")
            return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"❌ DATABASE PARTIAL OP INSERTION FAILURE: {str(e)}")
        return 0

def update_completed_operations(update_completed_operation: UpdateCompletedOperation) -> bool:
    """
    Update gain and profit for a completed operation
    ------------------------------------
    params:
        dataclass UpdateCompletedOperation: 
           outocome(str), gain(float), 
           profit(float), operation_id(int)
    ------------------------------------
    Example:
        update_completed_operations("ITP", 0.02, 50, 1784889912000)
    Using dataclass:
        op = UpdateCompletedOperation(
        outcome = "ITP",
        gain = 0.02,
        profit = 50,
        operation_id = 1784889912000
        )
        update_completed_operations(update_completed_operation=op)
    """
    query = """
            UPDATE completed_operations 
            SET
                outcome = ?,  
                gain = ?, 
                profit = ?
            WHERE operation_id = ?;
        """ 
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, update_completed_operation.as_tuple())
            conn.commit()
            logger.info(f"🟢 [DB] record {update_completed_operation.operation_id} updated in completed_operations table")
    except sqlite3.Error as e:
        logger.error(f"❌ DATABASE UPDATE OP INSERTION FAILURE: {str(e)}")
        logger.exception("Exception commited updating a completed operation")
        return False

    return True

def update_partial_operations(update_partial_operation: UpdatePartialOperation) -> bool:
    """
    Update exit_date, exit_price, outcome and gain for a partial operation
    ------------------------------------
    params:
        dataclass UpdatePartialOperation: 
           exit_date(str), exit_price(float), outcome(str), 
           gain(float), id(int)
    ------------------------------------
    Example:
        update_partial_operations("2026-07-25 00:00:00", 65000, "ITP", 0.02, 1784889912000)
    Using dataclass:
        op = UpdatePartialOperation(
        exit_date = "2026-07-25 00:00:00",
        exit_price = 65000
        outcome = "ITP",
        gain = 0.02,
        id = 200
        )
        update_partial_operations(update_partial_operation=op)
    """
    query = """
            UPDATE partial_operations 
            SET
                exit_date = ?, 
                exit_price = ?, 
                outcome = ?, 
                gain = ?   
            WHERE id = ?;
        """ 
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, update_partial_operation.as_tuple())
            conn.commit()
            logger.info(f"🟢 [DB] record {update_partial_operation.partial_id} updated "
                        f"in partial_operations table")
    except sqlite3.Error as e:
        logger.error(f"❌ DATABASE UPDATE OP INSERTION FAILURE: {str(e)}")
        logger.exception("Exception commited updating a partial operation")
        return False

    return True

def reset_completed_operations():
    """
    Delete all records from completed_operations table
    """
    query = "DELETE FROM completed_operations;"

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(query)
            conn.commit()
            logger.info(f"❌ [DB] All records of completed_operations table was deleted")
    except sqlite3.Error as e:
            logger.error(f"❌ DATABASE COMP INSERTION FAILURE: {str(e)}")
            traceback.print_exc()

def reset_partial_operations():
    """
    Delete all records from partial_operations table
    """
    query = "DELETE FROM partial_operations;"

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(query)
            conn.commit()
            logger.info(f"❌ [DB] All records of partial_operations table was deleted")
    except sqlite3.Error as e:
            logger.error(f"❌ [DB] DATABASE COMP INSERTION FAILURE: {str(e)}")
            traceback.print_exc()

if __name__ == "__main__":
    init_operations_db()
    print("database already created")
