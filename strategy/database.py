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
            # prepare data for logger
            data_exit = {
                "operation_id": operation.operation_id,
                "strategy": operation.strategy,
                "ticker": operation.ticker,
                "outcome": operation.outcome,
                "gain": operation.gain,
                "capital": operation.capital,
                "profit": operation.profit
            }
            logger.info(f"🟢 [DB] record for {operation.ticker} added to completed_operations" 
                        f" table with values: {data_exit} ")
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
            # prepare data for logger
            data_exit = {
                "operation_id": partial_operation.operation_id,
                "entry_date": partial_operation.entry_date,
                "side": partial_operation.side,
                "entry_price": partial_operation.entry_price,
                "tp": partial_operation.tp,
                "sl": partial_operation.sl,
                "exit_date": partial_operation.exit_date,
                "exit_price": partial_operation.exit_price,
                "outcome": partial_operation.outcome,
                "gain": partial_operation.gain,
                "bet": partial_operation.bet
            }
            logger.info("🟢 [DB] record added to partial_operations table with"
                        f" operation id: {partial_operation.operation_id} and values: {data_exit}")
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
            # get the entire updated record
            select_query = """
                        SELECT * FROM completed_operations
                        WHERE operation_id = ? 
                    """
            # execute query
            cursor.execute(
                select_query,
                (update_completed_operation.operation_id,)
            )

            record = cursor.fetchone()
            # record is a list with id, operation_id, strategy, ticker, outcome, gain, capital, profit
            record_dict = {
                "id": record[0],
                "operation_id": record[1],
                "strategy": record[2],
                "ticker": record[3],
                "outcome": record[4],
                "gain": record[5],
                "capital": record[6],
                "profit": record[7]
            }
            
            logger.info(f"🟢 [DB] record {update_completed_operation.operation_id} "
                        f"updated in completed_operations table with values: {record_dict}")
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
            # retrieve the entire record
            updated_query = """
                SELECT * FROM partial_operations
                WHERE id = ?;
            """
            cursor.execute(updated_query, 
                           (update_partial_operation.partial_id,)
                           )
            record = cursor.fetchone()
            # format exit data, the fields are:  id, operation_id, entry_date, side, entry_price, tp, sl, exit_date, exit_price
            # outcome, gain, bet
            data_result = {
                "id": record[0],
                "operation_id": record[1],
                "entry_date": record[2],
                "side": record[3],
                "entry_price": record[4],
                "tp": record[5],
                "sl": record[6],
                "exit_date": record[7],
                "exit_price": record[8],
                "outcome": record[9],
                "gain": record[10],
                "bet": record[11]
            }
            logger.info(f"🟢 [DB] record {update_partial_operation.partial_id} updated "
                                    f"in partial_operations table with final values: {data_result}")
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

def main():
    from data_classes import UpdatePartialOperation
    partial_operation = UpdatePartialOperation(
        exit_date="2026-07-31 00:00:00",
        exit_price=510.0,
        outcome="TEST_OUTCOME",
        gain=0.1,
        partial_id=1839
    )
    update_partial_operations(update_partial_operation=partial_operation)

if __name__ == "__main__":
    # init_operations_db()
    # print("database already created")
    main()
