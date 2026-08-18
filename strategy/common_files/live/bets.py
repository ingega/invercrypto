# invercrypto/strategy/common_files/live/bets.py
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from database import query_algo_id, query_bet_mode ,query_capital, query_operation_id, query_tickets_in_bet  
from database import save_live_operation_to_db, save_live_partial_operation_to_db, update_live_complete_operation
from database import calculate_accumulated_loss, calculate_total_loss, update_live_partial_operation, validate_operation_id
from database import query_collateral, query_operation_id_unresolved, query_ticker_by_op_id, is_operation_expired
from data_classes import CompletedLiveOperation, PartialLiveOperation, UpdateCompleteLiveOperation, UpdatePartialLiveOPeration
from common_files.balances import LiveUpdateBalances, update_all_balances
from common_files.binance_utils.orders import bet_execute, synchronize_orders, GetOrders
from common_files.logger import get_logger
from common_files.paths import load_json_file, CONFIG_LIVE_FILE
from tangent.filter import scan_tangent_opportunities

# init logger
logger = get_logger(__name__, log_live=True)

########################################################
#                results functions                     #
########################################################

async def calculate_gain(pnl: float, commission: float, operation_id: int) -> float | None:
    """
    Calculates net gain for an operation
    -------------------------------------------
    params:
        pnl(float): pnl realized for the operation e.g. 3.5 or -3.5 (usdt) positive or negative
        commission(float): commissions spended for operations e.g. 0.5 (usdt) only positive
        operation_id(int): operation_id of the actual operation
    execution:
        1. retrieve capital from database
        2. retrieve leverage from config
        3. calculate gain
    calculation:
        gain = ((pnl - commission) / leverage) / capital
    return:
        gain(float) e.g. 0.02 or -0.02 could be positive or negative
    """
    # ---------------------------------------------
    # 1. retrieve values
    # ---------------------------------------------
    capital = await query_capital(operation_id=operation_id)
    # defensive retrieve for leverage
    try:
        leverage = load_json_file(CONFIG_LIVE_FILE)["leverage"]
        return ((pnl - commission) / leverage) / capital
    except Exception:
        logger.exception(
            "❌ [CONFIG] Could not retrieve leverage. "
            "config_file=%s",
            CONFIG_LIVE_FILE,
        )

# ------------------------------------------------------
#                secondary bet results
#-------------------------------------------------------

class SecondaryFinalResolution:
    """
    This class use the workflow to update records and ends an operation
    The 3 possibles scenarios: TP, SL, TIE
    Once operation ends the workflow update is:
        1. Achieve the totals
        2. update the complete_operation record
        3. update balances
    """
    def __init__(self, operation_id:int, symbol: str, outcome:str) -> None:
        self.operation_id = operation_id
        self.symbol = symbol
        self.outcome = outcome

    async def close_operation(self):
        try:
            # 1. retrieve totals from operation_id query
            totals = await calculate_total_loss(operation_id=self.operation_id)
        
            # 2. update the complete_operation_record
            exit_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            # calculate profit
            profit = totals["pnl"] - totals["commission"]
            complete_record = UpdateCompleteLiveOperation(
                exit_date=exit_date,
                outcome=self.outcome,
                gain=totals["gain"],
                pnl=totals["pnl"],
                commission=totals["commission"],
                fee = 0,
                profit=profit,
                operation_id=self.operation_id
            )
            await update_live_complete_operation(update_record=complete_record)
        
            # 3. update balances, retrieve collateral
            collateral = await query_collateral(operation_id=self.operation_id)
            capital = collateral + profit
            update_all_balances(
                profit=profit,
                capital=capital,
                gain=totals["gain"],
                ticker=self.symbol,
                end_operation=True
            )
        
            logger.info("✅ [FINAL OPERATION] the pipeline of %s was executed successfully", self.outcome)
        except Exception:
            logger.exception("❌ Secondary final resolution fails")

@dataclass
class TieExitResult:
    exit_date: str
    exit_price: float
    pnl: float
    commission: float
    exit_order_id: int


async def close_tie_operation(
    client,
    symbol: str,
) -> TieExitResult:
    """
    Force-closes an active Futures position for a TIE operation.

    The position is closed using a reduce-only market order.
    Any remaining open orders for the symbol are then cancelled.

    Returns Binance execution data required to finalize
    the operation in the database.
    """

    try:
        # ---------------------------------------------------------
        # 1. Retrieve current position
        # ---------------------------------------------------------
        positions = await client.futures_position_information(
            symbol=symbol,
        )

        position = next(
            (
                item
                for item in positions
                if item["symbol"] == symbol
            ),
            None,
        )

        if position is None:
            raise RuntimeError(
                f"No position information found for {symbol}"
            )

        position_amt = float(position["positionAmt"])

        if position_amt == 0:
            raise RuntimeError(
                f"No active position to close for {symbol}"
            )

        # ---------------------------------------------------------
        # 2. Determine closing side
        # ---------------------------------------------------------
        side = "SELL" if position_amt > 0 else "BUY"
        quantity = abs(position_amt)

        logger.info(
            "🟨 [TIE] Closing position | "
            "symbol=%s | side=%s | quantity=%s",
            symbol,
            side,
            quantity,
        )

        # ---------------------------------------------------------
        # 3. Close position
        # ---------------------------------------------------------
        close_order = await client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
            reduceOnly=True,
        )

        exit_order_id = close_order["orderId"]

        logger.info(
            "🟨 [TIE] Close order submitted | "
            "symbol=%s | order_id=%s",
            symbol,
            exit_order_id,
        )

        # ---------------------------------------------------------
        # 4. Retrieve final order status
        # ---------------------------------------------------------
        order = await client.futures_get_order(
            symbol=symbol,
            orderId=exit_order_id,
        )

        if order["status"] != "FILLED":
            raise RuntimeError(
                f"TIE close order was not filled | "
                f"symbol={symbol} | "
                f"order_id={exit_order_id} | "
                f"status={order['status']}"
            )

        # ---------------------------------------------------------
        # 5. Cancel orphan SL/TP orders
        # ---------------------------------------------------------
        await client.futures_cancel_all_open_orders(
            symbol=symbol,
        )

        logger.info(
            "🟨 [TIE] Orphan orders cancelled | symbol=%s",
            symbol,
        )

        # ---------------------------------------------------------
        # 6. Retrieve executions
        # ---------------------------------------------------------
        trades = await client.futures_account_trades(
            symbol=symbol,
        )

        exit_trades = [
            trade
            for trade in trades
            if int(trade["orderId"]) == int(exit_order_id)
        ]

        if not exit_trades:
            raise RuntimeError(
                f"No trade execution found for TIE order | "
                f"symbol={symbol} | "
                f"order_id={exit_order_id}"
            )

        # ---------------------------------------------------------
        # 7. Aggregate execution data
        # ---------------------------------------------------------
        total_qty = sum(
            float(trade["qty"])
            for trade in exit_trades
        )

        pnl = sum(
            float(trade["realizedPnl"])
            for trade in exit_trades
        )

        commission = sum(
            float(trade["commission"])
            for trade in exit_trades
        )

        exit_price = (
            sum(
                float(trade["price"]) * float(trade["qty"])
                for trade in exit_trades
            )
            / total_qty
        )

        # ---------------------------------------------------------
        # 8. Use Binance execution timestamp
        # ---------------------------------------------------------
        exit_timestamp = max(
            int(trade["time"])
            for trade in exit_trades
        )

        exit_date = datetime.fromtimestamp(
            exit_timestamp / 1000,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")

        logger.info(
            "🟨 [TIE RESULT] symbol=%s | "
            "order_id=%s | "
            "exit_price=%.8f | "
            "pnl=%.8f | "
            "commission=%.8f",
            symbol,
            exit_order_id,
            exit_price,
            pnl,
            commission,
        )

        return TieExitResult(
            exit_date=exit_date,
            exit_price=exit_price,
            pnl=pnl,
            commission=commission,
            exit_order_id=exit_order_id,
        )

    except Exception as e:
        logger.exception(
            "❌ [TIE] Failed to close TIE operation | symbol=%s",
            symbol,
        )
        raise RuntimeError(
            f"Failed to close TIE operation for {symbol}"
        ) from e

async def update_tie_operation(operation_id: int, update_record: TieExitResult):
    """
    With the information provided, this method updates the partial record
    """
    try:
        # calculate gain
        gain = await calculate_gain(pnl=update_record.pnl, 
                                    commission=update_record.commission, 
                                    operation_id=operation_id)
        partial_record = UpdatePartialLiveOPeration(
            exit_order_id=update_record.exit_order_id,
            exit_date=update_record.exit_date,
            exit_price=update_record.exit_price,
            outcome="TIE",
            gain=gain,
            pnl=update_record.pnl,
            commission=update_record.commission,
            operation_id=operation_id
        )
        await update_live_partial_operation(update_record=partial_record)
        logger.info("✅ [UPDATE TIE OPERATION] pipeline was executed successfully")
    except Exception as e:
        logger.exception("❌ [UPDATE TIE OPERATION] pileline fails")
        raise RuntimeError("pileline fails in runtime") from e

async def secondary_bet_sl_resolution(
        client,
        rules_mgr,
        symbol: str,
        side: str,
        exit_order_id: int,
        exit_price: float,
        gain: float,
        pnl: float,
        commission: float,
        operation_id: int
):
    """
    If a secondary bet hit sl, the next pipeline must be executed
    1. Update actual partial record
    2. check accummlated loss: 
        if loss is gt allowed limit (config["sl_percentage"])
            call final sl resolution
        else
            call flip resolution
    """ 
    # 1. update partial record
    exit_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[UPDATE PARTIAL OP] values: exit_order_id: {exit_order_id} | exit date: {exit_date}"
                f" | exit_price: {exit_price:.6f} | outcome: SL | gain: {gain:.6f} | pnl: {pnl: .3f} |"
                f" commission: {commission:.6f} | operation_id: {operation_id}")
    partial_record = UpdatePartialLiveOPeration(
        exit_order_id = exit_order_id,
        exit_date=exit_date,
        exit_price=exit_price,
        outcome="SL",
        gain=gain,
        pnl=pnl,
        commission=commission,
        operation_id=operation_id
    )
    await update_live_partial_operation(update_record=partial_record)
    # ---------- once updated, calculate the acummulated loss -------- #
    acumm_loss = await calculate_accumulated_loss(operation_id=operation_id)
    config = load_json_file(CONFIG_LIVE_FILE)
    max_sl_allowed = config["sl_percentage"]
    if acumm_loss >= max_sl_allowed:
        final_sl = SecondaryFinalResolution(operation_id=operation_id, symbol=symbol, outcome="SL")
        await final_sl.close_operation()
    else:
        await secondary_bet_flip_resolution(
            client=client,
            rules_mgr=rules_mgr,
            symbol=symbol,
            side=side,
            adjust=acumm_loss,
            operation_id=operation_id
        )

async def secondary_bet_flip_resolution(client,
                                        rules_mgr,
                                        symbol,
                                        side,
                                        adjust,
                                        operation_id):
    """
    Add a new partial record
    """
    flip_side = "SELL" if side == "BUY" else "SELL"
    try:
        await make_entry_pipeline(client=client,
                        rules_mgr=rules_mgr,
                        symbol=symbol,
                        side=flip_side,
                        bet_mode="secondary",
                        adjust=adjust,
                        oper_id=operation_id)
        logger.info("✅ [FLIP] flip routine was executed successfully")
    except Exception:
        logger.exception("❌ [FLIP] secondary bet flip function fails")

async def bet_time_expiration(operation_id: int) -> bool:
    """
    Function verify if an operation in secondary is in timeout
    returns a bool var with the result of the query
    function need the ammount if time for expiration
    """
    # get minutes for expiring
    minutes_allowed = load_json_file(CONFIG_LIVE_FILE).get("stop_bet_minutes", 1440)
    # returns true or false
    return await is_operation_expired(operation_id=operation_id, minutes_for_expiration=minutes_allowed)

async def bet_time_expiration_handler(client):
    unresolved_operation_id = await query_operation_id_unresolved()
    if unresolved_operation_id is not None:
        for operation in unresolved_operation_id:
            result = await bet_time_expiration(operation_id=operation)
            if result:
                # retrieve symbol
                symbol = await query_ticker_by_op_id(operation_id=operation)
                if symbol is not None:
                    result = await bet_time_expiration(operation_id=operation)
                    if result:
                        # first update the partial record
                        result = await close_tie_operation(client=client, symbol=symbol)
                        await update_tie_operation(operation_id=operation, update_record=result)
                        # finally update and close operation
                        operation_finished = SecondaryFinalResolution(operation_id=operation, symbol=symbol, outcome="TIE")
                        await operation_finished.close_operation()


# ------------------------------------------------------
#                direct bet results
#-------------------------------------------------------

async def direct_bet_sl_routine(
    *,
    client,
    rules_mgr,
    symbol: str,
    operation_id: int,
    exit_order_id: int,
    capital: float,
    leverage: float,
    exit_date: str,
) -> None:
    """
    Handles a Direct Bet Stop Loss execution.

    Responsibilities:
        1. Retrieve final execution information from Binance.
        2. Calculate PnL, commission, profit and gain.
        3. Update partial_operations.
        #  this operation becomes a secondary bet
        4. add a new partial_operation record
    """
    logger.info(
        "🟥 [SL] Processing Stop Loss execution | "
        "symbol=%s | operation_id=%s | exit_order_id=%s",
        symbol,
        operation_id,
        exit_order_id,
    )
    # ------------------------------------------------------------------
    # 1. Retrieve FINAL execution information from Binance
    # ------------------------------------------------------------------
    order_data = await GetOrders(
        client=client
    ).get_order_execution(
        symbol=symbol,
        order_id=exit_order_id,
    )
    if not order_data:
        logger.error(
            "❌ [SL] Could not retrieve execution data | "
            "symbol=%s | order_id=%s",
            symbol,
            exit_order_id,
        )
        return
    pnl = float(order_data["realized_pnl"])
    commission = float(order_data["commission"])
    # BEWARE! the exit_order, is the loss order, therefore there's no need to flip
    side = order_data["side"]
    # ------------------------------------------------------------------
    # 2. Calculate financial results
    # ------------------------------------------------------------------
    profit = pnl - commission
    gain = 0.0
    if capital > 0:
        gain = ((pnl - commission) / leverage) / capital
    # if the first bet loss, the second bet try to recover the loss
    # variable adjust is used for that
    adjust = abs(gain) + commission
    logger.info(
        "🟥 [SL RESULT] symbol=%s | pnl=%.8f | commission=%.8f | "
        "profit=%.8f | gain=%.6f | adjust=%.8f",
        symbol,
        pnl,
        commission,
        profit,
        gain,
        adjust
    )
    # ------------------------------------------------------------------
    # 3. Update partial operation
    # ------------------------------------------------------------------
    
    exit_price = float(order_data["avgPrice"])
    partial_update_record = UpdatePartialLiveOPeration(
        exit_order_id=exit_order_id,
        exit_date=exit_date,
        exit_price=exit_price,
        outcome="SL",
        gain=gain,
        pnl=pnl,
        commission=commission,
        operation_id=operation_id,
    )
    await update_live_partial_operation(
        update_record=partial_update_record
    )
    logger.info(
        "🟥 [SL DATABASE] Operation updated | "
        "symbol=%s | operation_id=%s | exit_order_id=%s",
        symbol,
        operation_id,
        exit_order_id,
    )
    # ------------------------------------------------------------------
    # 4. Add a new partial record
    # ------------------------------------------------------------------
    # The side is already in the correct direction
    logger.info("[DIRECT SL PIPELINE] the information retrieved for make entry pipeline is"
                "symbol=%s | side=%s | adjust=%.6f | opertion_id=%d",
                symbol, side, adjust, operation_id)
    await make_entry_pipeline(client=client,
                        rules_mgr=rules_mgr,
                        symbol=symbol,
                        side=side,
                        bet_mode="secondary",
                        adjust=adjust,
                        oper_id=operation_id)

async def direct_bet_tp_routine(
    *,
    client,
    symbol: str,
    operation_id: int,
    exit_order_id: int,
    capital: float,
    leverage: float,
    exit_date: str,
) -> None:
    """
    Handles a Direct Bet Take Profit execution.
    Responsibilities:
        1. Retrieve final execution information from Binance.
        2. Calculate PnL, commission, profit and gain.
        3. Update completed_operations.
        4. Update partial_operations.
        5. Cancel remaining orphan orders.
        6. Update balances.
    """
    logger.info(
        "🟩 [TP] Processing Take Profit execution | "
        "symbol=%s | operation_id=%s | exit_order_id=%s",
        symbol,
        operation_id,
        exit_order_id,
    )
    # ------------------------------------------------------------------
    # 1. Retrieve FINAL execution information from Binance
    # ------------------------------------------------------------------
    order_data = await GetOrders(
        client=client
    ).get_order_execution(
        symbol=symbol,
        order_id=exit_order_id,
    )
    if not order_data:
        logger.error(
            "❌ [TP] Could not retrieve execution data | "
            "symbol=%s | order_id=%s",
            symbol,
            exit_order_id,
        )
        return
    pnl = float(order_data["realized_pnl"])
    commission = float(order_data["commission"])
    # ------------------------------------------------------------------
    # 2. Calculate financial results
    # ------------------------------------------------------------------
    profit = pnl - commission
    gain = 0.0
    if capital > 0:
        gain = ((pnl - commission) / leverage) / capital
    logger.info(
        "🟩 [TP RESULT] symbol=%s | pnl=%.8f | commission=%.8f | "
        "profit=%.8f | gain=%.6f",
        symbol,
        pnl,
        commission,
        profit,
        gain,
    )
    # ------------------------------------------------------------------
    # 3. Update completed operation
    # ------------------------------------------------------------------
    update_record = UpdateCompleteLiveOperation(
        exit_date=exit_date,
        outcome="DTP",
        gain=gain,
        pnl=pnl,
        commission=commission,
        fee=0,
        profit=profit,
        operation_id=operation_id,
    )
    await update_live_complete_operation(
        update_record=update_record
    )
    # ------------------------------------------------------------------
    # 4. Update partial operation
    # ------------------------------------------------------------------
    exit_price = float(order_data["avgPrice"])
    partial_update_record = UpdatePartialLiveOPeration(
        exit_order_id=exit_order_id,
        exit_date=exit_date,
        exit_price=exit_price,
        outcome="TP",
        gain=gain,
        pnl=pnl,
        commission=commission,
        operation_id=operation_id,
    )
    await update_live_partial_operation(
        update_record=partial_update_record
    )
    logger.info(
        "🟩 [TP DATABASE] Operation updated | "
        "symbol=%s | operation_id=%s | exit_order_id=%s",
        symbol,
        operation_id,
        exit_order_id,
    )
    # ------------------------------------------------------------------
    # 5. Cancel remaining SL/TP orders
    # ------------------------------------------------------------------
    try:
        await client.futures_cancel_all_open_orders(
            symbol=symbol
        )
        logger.info(
            "🧹 [ORPHAN CLEANUP] Remaining orders cancelled | "
            "symbol=%s",
            symbol,
        )
    except Exception:
        logger.exception(
            "❌ [ORPHAN CLEANUP] Failed cancelling remaining "
            "orders | symbol=%s",
            symbol,
        )
    # ------------------------------------------------------------------
    # 6. Update balances
    # ------------------------------------------------------------------
    update_all_balances(
        profit=profit,
        capital=capital,
        gain=gain,
        ticker=symbol,
    )
    logger.info(
        "✅ [TP] Direct Bet TP routine completed | "
        "symbol=%s | operation_id=%s",
        symbol,
        operation_id,
    )

async def verify_bet_result(msg, client, rules_mgr):
    """
    Event-driven dispatcher triggered by Binance Futures
    ORDER_TRADE_UPDATE events.
    This function intentionally contains no business logic.
    Its only responsibility is to identify the event and
    dispatch it to the appropriate execution routine.
    """
    event_data = msg.get("o", {})
    symbol = event_data.get("s")
    order_status = event_data.get("X")
    algo_id = event_data.get("si")
    exit_order_id = event_data.get("i")
    side = event_data.get("S")
    avg_price = float(event_data.get("ap"))
    realized_pnl = float(event_data.get("rp"))
    commission = float(event_data.get("n"))
    
    # ------------------------------------------------------------------
    # We only care about FILLED orders.
    # ------------------------------------------------------------------
    if order_status != "FILLED":
        return
    # ------------------------------------------------------------------
    # Binance sends the original MARKET order through the same
    # ORDER_TRADE_UPDATE event.
    # ------------------------------------------------------------------
    if algo_id == 0:
        logger.debug(
            "ℹ️ [ENTRY EVENT] Ignoring original market order | "
            "symbol=%s | order_id=%s",
            symbol,
            exit_order_id,
        )
        return
    logger.info(
        "⚡ [EVENT TRIGGERED] Exit order filled | "
        "symbol=%s | strategy_id=%s | exit_order_id=%s",
        symbol,
        algo_id,
        exit_order_id,
    )
    # ------------------------------------------------------------------
    # Basic validation
    # ------------------------------------------------------------------
    if not symbol:
        logger.error(
            "❌ [EVENT] Filled event without symbol."
        )
        return
    if not exit_order_id:
        logger.error(
            "❌ [EVENT] Filled exit event without order ID | "
            "symbol=%s | strategy_id=%s",
            symbol,
            algo_id,
        )
        return
    # ------------------------------------------------------------------
    # Retrieve strategy information
    # ------------------------------------------------------------------
    operation_id = await query_operation_id(
        ticker=symbol
    )
    if operation_id is None:
        logger.error(
            "❌ [EVENT] Could not find operation_id | "
            "symbol=%s | strategy_id=%s | exit_order_id=%s",
            symbol,
            algo_id,
            exit_order_id,
        )
        return
    tp_algo_id, sl_algo_id = await query_algo_id(operation_id=operation_id) # pyright: ignore[reportGeneralTypeIssues]

    logger.debug(
        "[EVENT DATA] symbol=%s | exit_order_id=%s | "
        "operation_id=%s | strategy_id=%s | "
        "tp_algo_id=%s | sl_algo_id=%s",
        symbol,
        exit_order_id,
        operation_id,
        algo_id,
        tp_algo_id,
        sl_algo_id,
    )
    # ------------------------------------------------------------------
    # Common data
    # ------------------------------------------------------------------
    config = load_json_file(CONFIG_LIVE_FILE)
    leverage = float(
        config["leverage"]
    )
    capital = await query_capital(
        operation_id=operation_id
    )
    exit_date = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # ------------------------------------------------------------------
    # verify if it is direct or indirect mode
    # ------------------------------------------------------------------

    bet_mode = await query_bet_mode(operation_id=operation_id)
    if bet_mode is None:
        logger.error(f"❌ [BET MODE] the value of bet mode could not be retrieved for the db")
        return

    # ------------------------------------------------------------------
    # Dispatch SL
    # ------------------------------------------------------------------
    if algo_id == sl_algo_id:
        # verify for mode
        if bet_mode == "D": # direct bet mode
            await direct_bet_sl_routine(
                client=client,
                rules_mgr=rules_mgr,
                symbol=symbol,
                operation_id=operation_id,
                exit_order_id=exit_order_id,
                capital=capital,
                leverage=leverage,
                exit_date=exit_date,
            )
            return
        elif bet_mode == "I":
            gain = await calculate_gain(pnl=realized_pnl, commission=commission, operation_id=operation_id)
            await secondary_bet_sl_resolution(
                client=client,
                rules_mgr=rules_mgr,
                symbol=symbol,
                side=side,
                exit_order_id=exit_order_id,
                exit_price=avg_price,
                gain=gain,
                pnl=realized_pnl,
                commission=commission,
                operation_id=operation_id
            )
            return
    # ------------------------------------------------------------------
    # Dispatch TP
    # ------------------------------------------------------------------
    if algo_id == tp_algo_id:
        if bet_mode == "D":
            await direct_bet_tp_routine(
                client=client,
                symbol=symbol,
                operation_id=operation_id,
                exit_order_id=exit_order_id,
                capital=capital,
                leverage=leverage,
                exit_date=exit_date,
            )
            return
        elif bet_mode == "I":
            tp_outcome = SecondaryFinalResolution(operation_id=operation_id, symbol=symbol, outcome="ITP")
            await tp_outcome.close_operation()
            return
        else:
            logger.error(f"❌ [BET MODE] an unreconigzed value was returned for the query: {bet_mode}")
    # ------------------------------------------------------------------
    # Unknown algo ID
    # ------------------------------------------------------------------
    logger.warning(
        "⚠️ [TYPE MISMATCH] Filled order does not match "
        "stored TP/SL algo IDs | "
        "symbol=%s | algo_id=%s | "
        "tp_algo_id=%s | sl_algo_id=%s | "
        "exit_order_id=%s",
        symbol,
        algo_id,
        tp_algo_id,
        sl_algo_id,
        exit_order_id,
    )

########################################################
#          direct bet entry functions                  #
########################################################

async def calculate_capital(entry_price: float, qty: float) -> float:
    # capital is calculated with formula entry_price * quantity / leverage
    leverage = load_json_file(CONFIG_LIVE_FILE).get("leverage", 1)
    return entry_price * qty / leverage

async def make_entry_pipeline(client, rules_mgr, symbol, side, 
                              bet_mode: str = "direct", adjust:float = 0, oper_id: int = 0):
    """
    The pipeline is used for direct and secondary bet. In case of secondary bet, 3 parameters
    must be sended:
    :param: bet_mode(str) -> values acepted "direct" and "secondary"
    :param: adjust(float) -> the adjust value for tp offset
    :param: oper_id(int) -> the operation id of the original operation, must be > 0 and exist in db
    """
    # ------ basic validations ------------------------------#
    if bet_mode not in ["direct", "secondary"]:
        logger.exception(f"❌ [ENTRY PIPELINE] bet_mode {bet_mode} in invalid")
        raise
    # ins secondary mode, adjust must be gt 0
    if bet_mode == "secondary" and adjust <= 0:
        logger.exception(f"❌ [ENTRY PIPELINE] invalid value for adjust: {adjust}")
    # operation_id must exist in database
    validation = await validate_operation_id(operation_id=oper_id)
    if bet_mode == "secondary" and validation is False:
        logger.exception(f"❌ [ENTRY PIPELINE] operation_id {oper_id} doesn't exists")
    
    # -----------FIRST: add orders -------------------------- #
    result = await bet_execute(symbol=symbol, 
                                      side=side, 
                                      client=client,
                                      rules_mgr=rules_mgr,
                                      bet_mode=bet_mode,
                                      adjust=adjust
                                      )
    data = result['data']
    if result.get("status") == "SUCCESS":
        # --------- complete the missing fields for orders ----------------#
        order_id = data.get("orderId", {})
        # after sending the order, check if it was filled and log the result
        synchronized_orders = await synchronize_orders(symbol=symbol, order_id=order_id, client=client)
        # update orders
        if len(synchronized_orders) > 0:
            data.update(synchronized_orders)
        else:
            logger.exception(f"❌ [FAILS RETRIEVING ORDER INFORMATION] is not possible retrieve updated information"
                         f" for order id {order_id}")
            # dummy data can be added to avoid database unsync
        # --------------- add information to db ------------------------- #
        entry_price = data["price"]
        quantity = data["quantity"]
        # if it is direct bet, completed record must be added
        # other whise, only partial record
        # bet vaule is a flag to indicate if it is a direct or secondary bet
        bet_value_for_db = "D"
        operation_id = time.time_ns()
        if bet_mode == "direct":
            capital = await calculate_capital(entry_price=entry_price, qty=quantity)
            collateral = LiveUpdateBalances(capital=capital).calculate_collateral()
            completed_record = CompletedLiveOperation(
                operation_id=operation_id,
                strategy="tangent",
                ticker=symbol,
                entry_date=data["timestamp"],
                capital=capital,
                collateral=collateral,
                quantity=quantity,
                exit_date=data["timestamp"],
                outcome="UNRESOLVED",
                gain=0,
                pnl=0,
                commission=0,
                fee=0,
                profit=0
            )
            await save_live_operation_to_db(live_operation=completed_record)
            # ------------ reduce the available balance ------------------ #
            balances = LiveUpdateBalances(capital)
            balances.reserve_collateral()
            # inform
            logger.info(f"🟢 [DB] complete record added to the database successfully")
        else: # "secondary"
            # get the missing fields
            operation_id = oper_id
            # i is for indirect, an older heritaged naming convention
            # nowadays the indirect bet is called secondary bet
            bet_value_for_db = "I"
        # add the partial record to db
        partial_record = PartialLiveOperation(
            operation_id=operation_id,
            order_id=order_id,
            exit_order_id=order_id,
            entry_date=data["timestamp"],
            side=side,
            entry_price=synchronized_orders["price"],
            type="MARKET",
            tp=data["tp"],
            sl=data["sl"],
            tp_algo_id=data["tp_algo_id"],
            sl_algo_id=data["sl_algo_id"],
            exit_date=data["timestamp"],
            exit_price=synchronized_orders["price"],
            outcome="UNRESOLVED",
            gain=0,
            pnl=0,
            commission=0,
            bet=bet_value_for_db
        )
        await save_live_partial_operation_to_db(partial_live_operation=partial_record)
        logger.info(f"🟢 [DB] partial record added to the database successfully")
        logger.info(f"🚀 [MAKE ENTRY] pipeline for {bet_mode}_bet was executed successfully")
        return {"status": "SUCCESS", "message": "records in added to the database"}
    return {"status": "FAIL", "message": f"failure in bet_execute pipeline"}

async def entries_pipeline(client, rules_mgr):
    """
    This pipeline scans for oppor, and if any ticker creates an opportunity, next pipeline is executed:
    1. Make the entry
    2. Save record in database
    3. Inform
    """
    # 1. Scan opportunities
    oppor = await scan_for_opportunities()
    if oppor:
        try:
            for op in oppor:
                ticker, side = op["ticker"], op["side"]
                await make_entry_pipeline(symbol=ticker, side=side, client=client, rules_mgr=rules_mgr)
        except Exception as e:
            print(f"error retrieving oppor, content: {oppor}, error: {e}")
    else:
        print("no opportunities found")


#########################################################
#                  opportunities                        #
#########################################################

async def scan_for_opportunities() -> List[str | None]:
    final_list = []
    oppor = await scan_tangent_opportunities(live=True)
    if len(oppor) > 0: # verify that there's no actual bet on that ticker
        # retrieve the tickers in an actual bet
        tickers = await query_tickets_in_bet()
        active_symbols = {ticker[0] for ticker in tickers}
        for op in oppor:
            ticker = op['ticker']
            side = op['side']
            if ticker not in active_symbols:
                data = {"ticker": ticker, "side": side}
                final_list.append(data)
    return final_list