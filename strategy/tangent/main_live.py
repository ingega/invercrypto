# invercrypto/strategy/common_files/binance/orders.py
import asyncio
import os
import time
from binance import AsyncClient, BinanceSocketManager
from datetime import datetime
from typing import List
from database import query_tickets_in_bet, save_live_operation_to_db, query_order_id, query_capital, query_algo_id
from database import save_live_partial_operation_to_db, save_partial_operation_to_db, update_live_complete_operation
from database import update_live_partial_operation
from data_classes import CompletedLiveOperation, UpdateCompletedOperation, PartialLiveOperation, UpdatePartialLiveOPeration
from common_files.binance_utils.orders import direct_bet_execute, synchronize_orders, SymbolRulesManager, GetOrders
from common_files.logger import get_logger
from common_files.paths import load_json_file, CONFIG_LIVE_FILE
from tangent.filter import scan_tangent_opportunities
from utils.timing import wait_for_time_trigger



# init logger
logger = get_logger(__name__, log_live=True)

async def calculate_capital(entry_price: float, qty: float) -> float:
    # capital is calculated with formula entry_price * quantity / leverage
    leverage = load_json_file(CONFIG_LIVE_FILE).get("leverage", 1)
    return entry_price * qty / leverage

async def make_entry_pipeline(client, rules_mgr, symbol, side):
    result = await direct_bet_execute(symbol=symbol, 
                                      side=side, 
                                      client=client,
                                      rules_mgr=rules_mgr
                                      )
    data = result['data']
    if result.get("status") == "SUCCESS":
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
        # add information to db
        operation_id = time.time_ns()
        entry_price = data["price"]
        quantity = data["quantity"]
        capital = await calculate_capital(entry_price=entry_price, qty=quantity)
        completed_record = CompletedLiveOperation(
            operation_id=operation_id,
            strategy="tangent",
            ticker=symbol,
            entry_date=data["timestamp"],
            capital=capital,
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
        # inform
        logger.info(f"🟢 [DB] complete record added to the database successfully")
        # add the partial record to db
        partial_record = PartialLiveOperation(
            operation_id=operation_id,
            order_id=order_id,
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
            bet="D"
        )
        await save_live_partial_operation_to_db(partial_live_operation=partial_record)
        logger.info(f"🟢 [DB] partial record added to the database successfully")

        return {"status": "SUCCESS", "message": "records added to the database"}
    return {"status": "FAIL", "message": "failure in direct_bet_execute pipeline"}

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

async def verify_bet_result(msg, client):
    """
    Event-driven callback triggered in real time when Binance fills an order.
    """
    event_data = msg.get('o', {})
    symbol = event_data.get('s')
    order_status = event_data.get('X')  # FILLED, CANCELED, EXPIRED
    strategy_id = event_data.get('si')   # STOP_MARKET, TAKE_PROFIT_MARKET, etc.
    if order_status == 'FILLED':
        # if strategy_id is 0, is because is the original market order
        if strategy_id == 0:
            return
        logger.info(f"⚡ [EVENT TRIGGERED] {symbol} Order {strategy_id} FILLED!")
        # retrieve algo id's
        order_id, operation_id = await query_order_id(ticker=symbol)
        tp_algo_id, sl_algo_id = await query_algo_id(operation_id=operation_id)
        logger.debug(f"content of order_id, operation_id, tp_algo_id, sl_algo_id"
                     f"{order_id}, {operation_id}, {tp_algo_id}, {sl_algo_id}")
        # get common data
        leverage = load_json_file(CONFIG_LIVE_FILE)["leverage"]
        if strategy_id == sl_algo_id:  # SL triggered
            logger.info(f" [SL] stop order was executed")
            # A. Retrieve the order_id from DB
            if order_id:
                # B. Update Database, profit is the realized pnl, commission must be incluied as well, gain can 
                # be calculated with the original capital and leverage
                # gain = ((pnl - commission) / leverage) / capital
                # e.g pnl = 10 USDT, commission = 0.5 usdt, leverage = 10, capital = 100
                # gain = ((10 - 0.5) / 10) / 100 = 0.0095 -> 0.95% Buying in 100 and selling in 101 (1% TP) I get 0.95% gain
                capital = await query_capital(operation_id=operation_id)
                # get pnl and commission
                order_data = await GetOrders(client=client).get_order_execution(symbol=symbol, order_id=order_id)
                print(f"{'=' * 10} value of order data: {order_data} {'=' * 10}")
                pnl = float(order_data["realized_pnl"])
                commission = float(order_data["commission"])
                gain = 0
                if capital > 0:
                    gain = ((pnl - commission) / leverage) / capital
                profit = pnl - commission
                update_record = UpdateCompletedOperation(
                    outcome="SL",
                    gain=gain,
                    profit=profit,
                    operation_id=operation_id
                )
                await update_live_complete_operation(update_record=update_record)
                # update partial record as well
                exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # the orderId assigned is retrieved for GetOrders
                new_order_id = order_data["orderId"]
                partial_update_record = UpdatePartialLiveOPeration(
                    order_id=new_order_id,
                    exit_date=exit_date,
                    exit_price=0,
                    outcome="SL",
                    gain=gain,
                    pnl=pnl,
                    commission=commission,
                    operation_id=operation_id
                )
                await update_live_partial_operation(update_record=partial_update_record)
                logger.info(f"🟥 [ORDER UPDATE] SL order {order_id} executed and updated")

                # C. Use `client` to cancel lingering Take Profit orphan order!
                await client.futures_cancel_all_open_orders(symbol=symbol)
                logger.info(f"🧹 [ORPHAN CLEANUP] Canceled lingering TP orders for {symbol}")
            else:
                logger.error(f"❌ [ORDER ID] order_id for {symbol} could not be retrieved")
        elif strategy_id == tp_algo_id:  # TP triggered
            # A. Retrieve the order_id from DB
            logger.info(f" [TP] take profit order was executed")
            order_id, operation_id = await query_order_id(ticker=symbol)
            if order_id:
                # B. Update Database, profit is the realized pnl, commission must be incluied as well, gain can 
                # be calculated with the original capital and leverage
                # gain = ((pnl - commission) / leverage) / capital
                # e.g pnl = 10 USDT, commission = 0.5 usdt, leverage = 10, capital = 100
                # gain = ((10 - 0.5) / 10) / 100 = 0.0095 -> 0.95% Buying in 100 and selling in 101 (1% TP) I get 0.95% gain
                capital = await query_capital(operation_id=operation_id)
                # get pnl and commission
                order_data = await GetOrders(client=client).get_order_execution(symbol=symbol, order_id=order_id)
                print(f"{'=' * 10} value of order data: {order_data} {'=' * 10}")
                pnl = order_data["realized_pnl"]
                commission = order_data["commission"]
                gain = 0
                if capital > 0:
                    gain = ((pnl - commission) / leverage) / capital
                profit = pnl - commission
                update_record = UpdateCompletedOperation(
                    outcome="TP",
                    gain=gain,
                    profit=profit,
                    operation_id=operation_id
                )
                logger.info(f"🟩 [ORDER UPDATE] TP order {order_id} executed and updated")
                # C. Use `client` to cancel lingering Take Profit orphan order!
                await client.futures_cancel_all_open_orders(symbol=symbol)
                logger.info(f"🧹 [ORPHAN CLEANUP] Canceled lingering TP orders for {symbol}")
            else:
                logger.error(f"❌ [ORDER ID] order_id for {symbol} could not be retrieved")
        else:
            logger.info(f" [TYPE MISSMATCH] the order_type executed was a {strategy_id} type")

async def start_user_stream(client):
    bsm = BinanceSocketManager(client)
    user_socket = bsm.futures_user_socket()
    try:
        logger.info(
            "Starting Binance Futures user stream. "
            "Task=%s",
            asyncio.current_task().get_name(),
        )
        async with user_socket as stream:
            logger.info(
                "Binance Futures WebSocket connected. "
                "Task=%s",
                asyncio.current_task().get_name(),
            )
            while True:
                msg = await stream.recv()
                logger.debug(
                    "WebSocket message received: %s",
                    msg,
                )
                if msg.get("e") == "ORDER_TRADE_UPDATE":
                    logger.info(
                        "ORDER_TRADE_UPDATE received: "
                        "symbol=%s",
                        msg.get("o", {}).get("s"),
                    )
                    logger.info(f" [MSG] complete msg content: {msg}")
                    await verify_bet_result(
                        msg,
                        client,
                    )
    except asyncio.CancelledError:
        task = asyncio.current_task()
        logger.warning(
            "USER STREAM CANCELLED! "
            "task=%s, cancelling=%s, "
            "task_done=%s, task_cancelled=%s",
            task.get_name() if task else None,
            task.cancelling() if task else None,
            task.done() if task else None,
            task.cancelled() if task else None,
        )
        raise
    except Exception:
        logger.exception(
            "USER STREAM FAILED WITH EXCEPTION."
        )
        raise
    finally:
        logger.info(
            "Binance Futures user stream closed."
        )

async def main():
    config = load_json_file(CONFIG_LIVE_FILE)
    target_hour = config["target_hours"]
    target_minute = config["target_minutes"]
    target_second = config["target_seconds"]
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    client = await AsyncClient.create(
        api_key=api_key,
        api_secret=api_secret,
    )
    user_stream_task = asyncio.create_task(
        start_user_stream(client)
    )
    try:
        while True:
            # 1. Wait for execution window
            await wait_for_time_trigger(
                target_hour=target_hour,
                target_minute=target_minute,
                target_second=target_second,
            )
            # 2. Scan for new opportunities
            # create the rules manager
            rules_mgr = await SymbolRulesManager.create(client=client)
            await entries_pipeline(client=client, rules_mgr=rules_mgr)
    finally:
        user_stream_task.cancel()
        try:
            await user_stream_task
        except asyncio.CancelledError:
            pass
        await client.close_connection()
           

if __name__ == '__main__':
    try:
        asyncio.run(main()) 
    except KeyboardInterrupt:
        print("\n🛑 Simulator runtime manually terminated safely (user key press). Standing down.")
