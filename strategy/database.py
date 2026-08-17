# invercrypto/strategy/database.py
# alpha listed importations
import sqlite3
import traceback
from data_classes import CompletedOperation, PartialOperation, UpdateCompletedOperation, UpdatePartialOperation
from data_classes import CompletedLiveOperation, PartialLiveOperation, UpdateCompleteLiveOperation, UpdatePartialLiveOPeration
from common_files.logger import get_logger
from common_files.paths import DB_PATH, DB_LIVE_PATH

logger = get_logger(__name__)

# provide a different name, for mapping
logger_live = get_logger(
    f"{__name__}.live",
    log_live=True,
)
    
    
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
            operation_id, strategy, ticker, entry_date, capital, collateral, quantity, exit_date, 
            outcome, gain, pnl, commission, fee, profit  
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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

async def save_live_partial_operation_to_db(
    partial_live_operation: PartialLiveOperation,
) -> int | None:
    """
    Safely insert a partial operation.

    Before inserting, validates that the parent
    completed operation:

        1. Exists.
        2. Is still UNRESOLVED.

    This prevents orphaned UNRESOLVED partial operations
    from being created after the parent operation has already
    been resolved.
    """

    validate_query = """
        SELECT 1
        FROM completed_operations
        WHERE operation_id = ?
          AND outcome = 'UNRESOLVED';
    """

    insert_query = """
        INSERT INTO partial_operations (
            operation_id,
            order_id,
            exit_order_id,
            entry_date,
            side,
            entry_price,
            type,
            tp,
            sl,
            tp_algo_id,
            sl_algo_id,
            exit_date,
            exit_price,
            outcome,
            gain,
            pnl,
            commission,
            bet
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()

            # ---------------------------------------------------------
            # 1. Validate parent operation
            # ---------------------------------------------------------

            cursor.execute(
                validate_query,
                (partial_live_operation.operation_id,),
            )

            parent = cursor.fetchone()

            if parent is None:
                logger_live.error(
                    "❌ [DB DEFENSE] Cannot insert partial operation. "
                    "Parent operation_id=%s does not exist or is "
                    "already resolved.",
                    partial_live_operation.operation_id,
                )

                raise RuntimeError(
                    "Cannot insert partial operation: "
                    "parent operation is not unresolved."
                )

            # ---------------------------------------------------------
            # 2. Insert partial operation
            # ---------------------------------------------------------

            cursor.execute(
                insert_query,
                partial_live_operation.as_tuple(),
            )

            conn.commit()

            # ---------------------------------------------------------
            # 3. Logging
            # ---------------------------------------------------------

            logger_live.info(
                "🟢 [DB] Partial operation inserted. "
                "operation_id=%s | order_id=%s | side=%s | "
                "outcome=%s | gain=%+.6f",
                partial_live_operation.operation_id,
                partial_live_operation.order_id,
                partial_live_operation.side,
                partial_live_operation.outcome,
                partial_live_operation.gain,
            )

            return cursor.lastrowid

    except sqlite3.IntegrityError:
        logger_live.exception(
            "❌ [DB] Integrity violation inserting partial operation. "
            "operation_id=%s",
            partial_live_operation.operation_id,
        )
        raise

    except sqlite3.Error:
        logger_live.exception(
            "❌ [DB] Failed to insert partial operation. "
            "operation_id=%s",
            partial_live_operation.operation_id,
        )
        raise

##################### UPDATE FUNCTIONS  ######################

async def update_live_complete_operation(
    update_record: UpdateCompleteLiveOperation
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
            logger_live.info(f"🟢 [DB] Completed operation {update_record.operation_id} was updated susccessfully")
            return cursor.rowcount == 1

    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE UPDATE FAILURE: {e}"
        )
        return False

async def update_live_partial_operation(
    update_record: UpdatePartialLiveOPeration,
) -> bool:
    """
    Updates a completed operation with exit information.
    """

    query = """
        UPDATE partial_operations
        SET
            exit_order_id = ?,
            exit_date = ?,
            exit_price = ?,
            outcome = ?,
            gain = ?,
            pnl = ?,
            commission = ?
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
            logger_live.info(f"🟢 [DB] Partial operation {update_record.operation_id} was updated susccessfully")
            return cursor.rowcount == 1

    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE PARTIAL UPDATE FAILURE: {e}"
        )
        return False


##################### QUERY FUNCTIONS  #####################

# --------- operation_id, order_id, any id ------------------------#

async def query_operation_id(
    ticker: str,
) -> int | None:
    """
    Retrieve order_id and operation_id from partial_operations
    for an unresolved completed operation.
    """
    query = """
        SELECT
            operation_id
        FROM completed_operations
        WHERE completed_operations.ticker = ?
          AND completed_operations.outcome = 'UNRESOLVED';
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (ticker,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row[0]
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE ORDER_ID QUERY FAILURE: {e}"
        )
        return None

async def query_algo_id(operation_id: int):
    query = """
        SELECT tp_algo_id, sl_algo_id
        FROM partial_operations
        WHERE operation_id = ?
        AND outcome = 'UNRESOLVED';
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE ALGO_ID QUERY FAILURE: {e}"
        )
        return None

async def validate_operation_id(operation_id: int) -> bool:
    query = """
        SELECT * 
        FROM partial_operations
        WHERE operation_id = ?
        """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            else:
                return True
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE VALIDATE_OPERATION_ID QUERY FAILURE: {e}"
        )
        return False

async def query_operation_id_unresolved():
    """
    Retunrs all operations id unresolved
    """
    query = """
            SELECT operation_id 
            FROM completed_operations
            WHERE outcome = 'UNRESOLVED';
            """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            if row is None:
                return None
            
            return row

    except sqlite3.Error:
        logger_live.exception(
            "❌ [DATABASE] Failed to query unresolved operations")
        return None

# --------------- financial queries ------------------------------- #

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

async def query_collateral(operation_id: int) -> float | None:
    query = """
    SELECT collateral
    FROM completed_operations
    WHERE operation_id = ?
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row[0]
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE COLLATERAL QUERY FAILURE: {e}"
        )
        return None

async def calculate_accumulated_loss(
    operation_id: int,
) -> float | None:
    """
    Calculates the accumulated loss of an active operation.
    `gain` is expected to be negative while this function is called.
    Commission and fees are stored as positive values.

    Example:
        gain       = -5.00
        commission =  0.50
        fee        =  0.10

        accumulated_loss = 5.60
    The returned value is always positive.
    """
    query = """
        SELECT
            ABS(COALESCE(SUM(gain), 0))
            + COALESCE(SUM(commission), 0)
            + COALESCE(SUM(fee), 0)
        FROM partial_operations
        WHERE operation_id = ?
    """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return float(row[0])
    except sqlite3.Error:
        logger_live.exception(
            "❌ [DATABASE] Failed to calculate accumulated loss "
            "for operation_id=%s",
            operation_id,
        )
        return None

async def calculate_total_loss(
    operation_id: int,
) -> dict[str, float] | None:
    """
    Calculates the accumulated financial results of an operation.

    Returns:
        A dictionary containing:

        - pnl: Total realized PnL.
        - gain: Total accumulated gain.
        - commission: Total commissions.
        - fee: Total fees.

        Returns None if the database query fails.
    """

    query = """
        SELECT
            COALESCE(SUM(pnl), 0),
            COALESCE(SUM(gain), 0),
            COALESCE(SUM(commission), 0)
        FROM partial_operations
        WHERE operation_id = ?
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()

            cursor.execute(
                query,
                (operation_id,),
            )

            row = cursor.fetchone()

            if row is None:
                return None

            return {
                "pnl": float(row[0]),
                "gain": float(row[1]),
                "commission": float(row[2])
            }

    except sqlite3.Error:
        logger_live.exception(
            "❌ [DATABASE] Failed to calculate total loss "
            "for operation_id=%s",
            operation_id,
        )
        return None


# ---------- ticker releated ----------------------------#

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

async def query_ticker_by_op_id(
    operation_id: int,
) -> str | None:
    """
    Return the ticker associated with an operation_id.
    """
    query = """
        SELECT ticker
        FROM completed_operations
        WHERE operation_id = ?;
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return row[0]

    except sqlite3.Error:
        logger_live.exception(
            "❌ [DATABASE] Failed to retrieve ticker "
            "for operation_id=%s",
            operation_id,
        )
        return None


# ---------- time expired aux queries --------------------#

async def is_operation_expired(
    operation_id: int,
    minutes_for_expiration: int,
) -> bool:
    """
    Determine whether the secondary stage of an operation
    has exceeded its configured expiration time.

    The expiration clock starts at the exit_date of the
    direct bet (bet='D', outcome='SL').

    The operation is expired only when:
        1. The direct bet has been resolved by SL.
        2. An UNRESOLVED row still exists for the operation.
        3. The configured expiration time has elapsed.
    """

    query = """
        SELECT EXISTS (
            SELECT 1
            FROM partial_operations AS direct
            WHERE direct.operation_id = ?
              AND direct.bet = 'D'
              AND direct.outcome = 'SL'
              AND datetime(
                    direct.exit_date,
                    '+' || ? || ' minutes'
                  ) <= datetime('now')
              AND EXISTS (
                  SELECT 1
                  FROM partial_operations AS unresolved
                  WHERE unresolved.operation_id = direct.operation_id
                    AND unresolved.outcome = 'UNRESOLVED'
              )
        );
    """

    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()

            cursor.execute(
                query,
                (
                    operation_id,
                    minutes_for_expiration,
                ),
            )

            row = cursor.fetchone()

            return bool(row[0]) if row is not None else False

    except sqlite3.Error:
        logger_live.exception(
            "❌ [DATABASE] Failed to check expiration "
            "for operation_id=%s",
            operation_id,
        )
        return False

# ---------------- bets   --------------------------------#

async def query_bet_mode(operation_id:int):
    """
    This query returns the bet mode of an active ticker
    :param: ticker(str) Name of the ticker e.g. "BTCUSDT"
    :return: 
        a str value, "D" for direct bet mode or "I" for 
        secondary bet mode (I is for indirect, an older nomenclature)
    """
    query = """
        SELECT bet 
        FROM partial_operations
        WHERE outcome = 'UNRESOLVED'
        AND operation_id = ?
        """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row[0]
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE BET_MODE QUERY FAILURE: {e}"
        )
        return None

async def is_ticker_in_bet(ticker:str) -> tuple[bool, float]:
    """
    This query returns a bool value if depends if a ticker is on an unresolved bet
    :param: symbol(str) Name of the ticker e.g. "BTCUSDT"
    :return: 
        a boolean value, True if there's an active bet for this symbol, otherwise False 
        also the quantity in bet
    """
    query = """
        SELECT quantity
        FROM completed_operations
        WHERE ticker = ?
        AND outcome = 'UNRESOLVED'
        """
    try:
        with sqlite3.connect(DB_LIVE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (ticker,))
            row = cursor.fetchone() 
            if row is None:
                return False, 0.0
            return True, row[0]
    except sqlite3.Error as e:
        logger_live.error(
            f"❌ DATABASE BET_MODE QUERY FAILURE: {e}"
        )
        return False, 0.0


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
