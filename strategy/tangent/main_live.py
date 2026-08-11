# invercrypto/strategy/common_files/binance/orders.py
import asyncio
import os
import time
from binance import AsyncClient, BinanceSocketManager, Client
from typing import List
from database import query_tickets_in_bet, save_live_operation_to_db, query_order_id
from data_classes import CompletedLiveOperation, UpdateCompletedOperation
from common_files.logger import get_logger
from common_files.paths import load_json_file, CONFIG_LIVE_FILE
from common_files.binance_utils.orders import direct_bet_execute, synchronize_orders
from tangent.filter import scan_tangent_opportunities
from utils.timing import wait_for_time_trigger



# init logger
logger = get_logger(__name__, log_live=True)


async def calculate_capital(entry_price: float, qty: float) -> float:
    # capital is calculated with formula entry_price * quantity / leverage
    leverage = load_json_file(CONFIG_LIVE_FILE).get("leverage", 1)
    return entry_price * qty / leverage

async def make_entry_pipeline(symbol, side):
    print("=" * 10, "Start make entry pipeline ... ", "=" * 10)
    result = direct_bet_execute(symbol, side)
    data = result['data']
    if result.get("status") == "SUCCESS":
        order_id = data.get("orderId", {})
        # after sending the order, check if it was filled and log the result
        synchronized_orders = synchronize_orders(symbol, order_id)
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
        save_live_operation_to_db(live_operation=completed_record)
        # inform
        logger.info(f"🟢 [DB] record added to the database successfully")
        return {"status": "SUCCESS", "message": "record added to the database"}
    print("=" * 10, "End make entry pipeline ... ", "=" * 10)
    return {"status": "FAIL", "message": "failure in direct_bet_execute pipeline"}

async def scan_for_opportunities() -> List[str | None]:
    final_list = []
    oppor = await scan_tangent_opportunities(live=True)
    print("oppor content:", oppor)
    if len(oppor) > 0: # verify that there's no actual bet on that ticker
        # retrieve the tickers in an actual bet
        tickers = await query_tickets_in_bet()
        print("content of tickers: ", tickers)
        active_symbols = {ticker[0] for ticker in tickers}
        final_list = [
                symbol
                for symbol in oppor
                if symbol not in active_symbols
                ]
    return final_list

async def entries_pipeline():
    """
    This pipeline scans for oppor, and if any ticker creates an opportunity, next pipeline is executed:
    1. Make the entry
    2. Save record in database
    3. Inform
    """
    print("=" * 10, "start entries pipeline....", "=" * 10)
    # 1. Scan opportunities
    oppor = await scan_for_opportunities()
    # oppor contains ticker and side
    if oppor:
        try:
            for op in oppor:
                ticker, side = op["ticker"], op["side"]
                await make_entry_pipeline(symbol=ticker, side=side)
        except Exception as e:
            print(f"error retrieving oppor, content: {oppor}, error: {e}")
    else:
        print("no opportunities found")
    print("=" * 10, "end entries pipeline....", "=" * 10)

async def verify_bet_result(msg, client):
    """
    Event-driven callback triggered in real time when Binance fills an order.
    """
    print("=" * 10, "start verify bet result....", "=" * 10)
    event_data = msg.get('o', {})
    symbol = event_data.get('s')
    order_status = event_data.get('X')  # FILLED, CANCELED, EXPIRED
    order_type = event_data.get('ot')   # STOP_MARKET, TAKE_PROFIT_MARKET, etc.

    if order_status == 'FILLED':
        logger.info(f"⚡ [EVENT TRIGGERED] {symbol} Order {order_type} FILLED!")

        if order_type == 'STOP_MARKET':  # SL triggered
            # A. Retrieve the order_id from DB
            order_id, operation_id = query_order_id(ticker=symbol)

            if order_id:
                # B. Update Database
                update_record = UpdateCompletedOperation(
                    outcome="SL",
                    gain=-0.005,
                    profit=1,
                    operation_id=operation_id
                )
                logger.info(f"🟥 [ORDER UPDATE] SL order {order_id} executed and updated")

                # C. Use `client` to cancel lingering Take Profit orphan order!
                await client.futures_cancel_all_open_orders(symbol=symbol)
                logger.info(f"🧹 [ORPHAN CLEANUP] Canceled lingering TP orders for {symbol}")

            else:
                logger.error(f"❌ [ORDER ID] order_id for {symbol} could not be retrieved")

    print("=" * 10, "... ends verify bet result", "=" * 10)

async def start_user_stream(client):
    print("=" * 10, "start user stream....", "=" * 10)
    bsm = BinanceSocketManager(client)
    user_socket = bsm.futures_user_socket()
    try:
        async with user_socket as stream:
            while True:
                msg = await stream.recv()
                if msg.get("e") == "ORDER_TRADE_UPDATE":
                    await verify_bet_result(
                        msg,
                        client,
                    )
    except asyncio.CancelledError:
        logger.info("User stream task cancelled.")
        raise
    except Exception:
        logger.exception("User stream failed.")
        raise
    finally:
        print("=" * 10, "end user stream....", "=" * 10)

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
            await entries_pipeline()
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
