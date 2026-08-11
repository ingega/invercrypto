# invercrypto/strategy/database.py
# alpha listed importations
import sqlite3
import traceback
from typing import Tuple
from data_classes import CompletedOperation, PartialOperation, UpdateCompletedOperation, UpdatePartialOperation
from data_classes import CompletedLiveOperation, PartialLiveOperation, UpdateCompleteLiveOperation, UpdatePartialLiveOPeration
from common_files.logger import get_logger
from common_files.paths import DB_PATH, DB_LIVE_PATH

logger = get_logger(__name__)
logger_live = get_logger(__name__, log_live=True)
    
    
def init_operations_db() -> None:
    """
    Initializes the SQLite database and creates the operations 
    table if it does not exist.
    Includes a composite index to keep historical ML feature fetches 
    lightning-fast.
    """
    # initialize live database
    with sqlite3.connect(DB_LIVE_PATH) as conn:
        cursor = conn.cursor()
        # Enable Write-Ahead Logging for high-frequency concurrency updates
        cursor.execute("PRAGMA journal_mode=WAL;")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Enable Write-Ahead Logging for high-frequency concurrency updates
        cursor.execute("PRAGMA journal_mode=WAL;")
        
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

############################################################
#                   LIVE DATABASE                          #             
############################################################

##################### SAVE FUNCTIONS  ######################

async def save_live_operation_to_db(live_operation: CompletedLiveOperation) -> int | None:
    """
    Safely records a resolved direct bet into the SQLite data layer.
    """
    query = """
        INSERT INTO completed_operations (
            operation_id, strategy, ticker, entry_date, capital, quantity, exit_date, 
            outcome, gain, pnl, commission, fee, profit  
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """ 
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, live_operation.as_tuple())
            conn.commit()
            # prepare data for logger
            data_exit = {
                "operation_id": live_operation.operation_id,
                "strategy": live_operation.strategy,
                "ticker": live_operation.ticker,
                "outcome": live_operation.outcome,
                "gain": live_operation.gain,
                "capital": live_operation.capital,
                "profit": live_operation.profit
            }
            logger_live.info(f"🟢 [DB] record for {live_operation.ticker} added to completed_operations" 
                        f" table with values: {data_exit} ")
            return cursor.lastrowid
    except sqlite3.Error as e:
       logger_live.error(f"❌ DATABASE COMP INSERTION FAILURE: {str(e)}")

async def save_live_partial_operation_to_db(partial_live_operation: PartialLiveOperation) -> int | None:
    """
    Safely records a resolved partial bet into the SQLite data layer.
    """
    query = """
        INSERT INTO completed_operations (
            operation_id, order_id, entry_date, side, entry_price, type, tp, sl, exit_date, exit_ptice,
            outcome, gain, pnl, commission, bet
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """ 
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, partial_live_operation.as_tuple())
            conn.commit()
            # prepare data for logger
            data_exit = {
                "operation_id": partial_live_operation.operation_id,
                "order_id": partial_live_operation.order_id,
                "side": partial_live_operation.side,
                "outcome": partial_live_operation.outcome,
                "gain": partial_live_operation.gain
            }
            logger_live.info(f"🟢 [DB] record for {partial_live_operation.operation_id} added to partial_operations" 
                        f" table with values: {data_exit} ")
            return cursor.lastrowid
    except sqlite3.Error as e:
       logger_live.error(f"❌ DATABASE COMP INSERTION FAILURE: {str(e)}")

##################### UPDATE FUNCTIONS  ######################

def update_live_complete_operation(
    update_record: UpdateCompletedOperation,
) -> bool:
    """
    Updates a completed operation with exit information.
    """

    query = """
        UPDATE completed_operations
        SET
            exit_date = ?,
            outcome = ?,
            gain = ?,
            pnl = ?,
            commission = ?,
            fee = ?,
            profit = ?
        WHERE operation_id = ?;
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                update_record.as_tuple(),
            )
            conn.commit()
            return cursor.rowcount == 1

    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE UPDATE FAILURE: {e}"
        )
        return False


##################### QUERY FUNCTIONS  #####################

async def query_tickets_in_bet():
    """
    Verify if a ticker is in a bet
    """
    query = """ 
    SELECT ticker FROM completed_operations 
    WHERE outcome = 'UNRESOLVED';
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            # return all tickers in bet
            return cursor.fetchall()
            
    except sqlite3.Error as e:
           logger_live.error(f"❌ DATABASE COMP INSERTION FAILURE: {str(e)}") 

async def query_order_id(ticker: str) -> Tuple[int | None, int | None]:
    """
    Retrieve order_id from partial_operations
    for an unresolved completed operation.
    """
    query = """
        SELECT partial_operations.order_id, partial_operations.operation_id
        FROM partial_operations
        INNER JOIN completed_operations
            ON partial_operations.operation_id =
               completed_operations.operation_id
        WHERE completed_operations.ticker = ?
          AND completed_operations.outcome = 'UNRESOLVED';
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (ticker,))
            row = cursor.fetchone()
            if row is None:
                return None, None
            return row[0]

    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE ORDER_ID QUERY FAILURE: {e}"
        )
        return None, None

async def query_capital(operation_id: int) -> float:
    query = """
    SELECT capital
    FROM completed_operations
    WHERE operation_id = ?
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return 0.0
            return row[0]
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE ORDER_ID QUERY FAILURE: {e}"
        )
        return 0.0

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
