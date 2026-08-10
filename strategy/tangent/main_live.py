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
from strategy.common_files.binance_utils.orders import direct_bet_execute, synchronize_orders
from tangent.filter import scan_tangent_opportunities
from utils.timing import wait_for_time_trigger

# create binance client
client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)

# init logger
logger = get_logger(__name__, log_live=True)


async def calculate_capital(entry_price: float, qty: float) -> float:
    # capital is calculated with formula entry_price * quantity / leverage
    leverage = load_json_file(CONFIG_LIVE_FILE).get("leverage", 1)
    return entry_price * qty / leverage

async def make_entry_pipeline(symbol, side):
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
    return {"status": "FAIL", "message": "failure in direct_bet_execute pipeline"}

async def scan_for_opportunities() -> List[str | None]:
    final_list = []
    oppor = scan_tangent_opportunities(live=True)
    if len(oppor) > 0: # verify that there's no actual bet on that ticker
        # retrieve the tickers in an actual bet
        tickers = query_tickets_in_bet()
        for op in oppor:
            if not op in tickers:
                final_list.append(op)
    return final_list

async def entries_pipeline():
    """
    This pipeline scans for oppor, and if any ticker creates an opportunity, next pipeline is executed:
    1. Make the entry
    2. Save record in database
    3. Inform
    """
    # 1. Scan opportunities
    oppor = scan_for_opportunities()
    # oppor contains ticker and side
    if oppor:
        for op in oppor:
            ticker, side = op["ticker"], op["side"]
            await make_entry_pipeline(symbol=ticker, side=side)
    print("no opportunities found")

async def verify_bet_result(msg):
    """
    Event-driven callback triggered in real time when Binance fills an order.
    """
    event_data = msg.get('o', {})
    symbol = event_data.get('s')
    order_status = event_data.get('X')  # FILLED, CANCELED, EXPIRED
    order_type = event_data.get('ot')   # STOP_MARKET, TAKE_PROFIT_MARKET, etc.
    if order_status == 'FILLED':
        logger.info(f"⚡ [EVENT TRIGGERED] {symbol} Order {order_type} FILLED!")
        # 1. Check order_type
        if order_type == 'STOP_MARKET': # sl wins
            # A. Retrieve the order_id
            order_id, operation_id = query_order_id(ticker=symbol)
            # B. Update information
            if order_id:
                update_record = UpdateCompletedOperation(
                    outcome="SL",
                    gain = -0.005,
                    profit=1,
                    operation_id=operation_id # pyright: ignore[reportArgumentType]
                )
                logger.info(f"🟥 [ORDER UPDATE] sl order with order {order_id} was executed and updated")
            else:
                logger.error(f"❌ [ORDER ID] order_id {order_id} could not be retrieved")


async def start_user_stream(client):
    bsm = BinanceSocketManager(client)
    # Open user data stream for Binance Futures
    user_socket = bsm.futures_user_socket()
    async with user_socket as stream:
        while True:
            msg = await stream.recv()
            if msg.get('e') == 'ORDER_TRADE_UPDATE':
                await verify_bet_result(msg)

async def main():
    """
    using Async mode, we can execute all pipeline in the main function
    1. time trigger
    2. Verify bets results
    3. Scan for new opportunities
    """
    # retrieve data from config file
    config = load_json_file(CONFIG_LIVE_FILE)
    target_hour = config["target_hours"]
    target_minute = config["target_minutes"]
    target_second = config["target_seconds"]
    while True:
        # 1. time trigger
        await wait_for_time_trigger(target_hour=target_hour, target_minute=target_minute, target_second=target_second)
        # 2. verify bets result
        await start_user_stream(client=client)
        # 3. Scan for opportunities
        await entries_pipeline()


        
           

if __name__ == '__main__':
    try:
        asyncio.run(main()) 
    except KeyboardInterrupt:
        print("\n🛑 Simulator runtime manually terminated safely (user key press). Standing down.")
