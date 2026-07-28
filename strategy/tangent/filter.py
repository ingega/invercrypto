import time
from binance.client import Client
from datetime import datetime as dt
from datetime import UTC
from typing import Tuple
# I/O files functions
from common_files.paths import *
from common_files.logger import get_logger
# notional size and balance functions
from common_files.balances import calculate_notional_size, calculate_colateral, reduce_available_balance
# operations
from data_classes import DirectBet, CompletedOperation, PartialOperation
# database
from database import save_operation_to_db, save_partial_operation_to_db

logger = get_logger(__name__)

def calculate_tpsl(side:str, entry_price:float) -> Tuple[float, float]:
    # get direct bet percentages
    direct_bet_pct = load_json_file(CONFIG_FILE)["direct_bet_percentage"]
    tp, sl = 0, 0
    if side == "BUY":
        tp = entry_price * (1 + direct_bet_pct)
        sl = entry_price * (1 - direct_bet_pct)
    else:
        tp = entry_price * (1 - direct_bet_pct)
        sl = entry_price * (1 + direct_bet_pct)
    return tp, sl

# aux funct for entry addition
def add_entry(ticker:str, side:str, entry_price: float):
    """
    This function must execute the next workflow:
    I. Get capitial: Capital is retrieved from main_balance, but calculated with available_balance.
    II. Available balance reduces its balance.
    III. The entry is added to completed op (With generic exit_date, outcome, gain, profit)
    IV. The entry is added to partial op as well, with generic exit_date, exit_price, outcome, gain
    V. Entry is added to direct_bets
    ----------------------------------------
    params:
        ticker(str): Name of ticker
        side(str): side of the position (BUY or SELL)
        entry_price(float): initial price for position 
    ----------------------------------------
    """
    logger.info(f"↩️ record {ticker} starts the add entry pipeline")
    # 1. Get capital
    capital = calculate_notional_size(ticker=ticker)
    # 2. reduces the available balance
    # calculate colateral
    colateral = calculate_colateral(capital=capital)
    # reduce the balance
    reduce_available_balance(colateral=colateral)
    # 3. add record to completed_operations
    # get operation_id
    operation_id = time.time_ns()
    completed_record = CompletedOperation(
        operation_id=operation_id,
        strategy="tangent",
        ticker=ticker,
        outcome="UNRESOLVED",
        gain=0,
        capital=capital,
        profit=0
    )
    save_operation_to_db(operation=completed_record)
    # 4 add the partial operation
    # get the missed data
    entry_date = dt.now().strftime("%Y-%m-%d %H:%M:%S")
    tp, sl = calculate_tpsl(side=side, entry_price=entry_price)
    partial_record = PartialOperation(
        operation_id=operation_id,
        entry_date=entry_date,
        side=side,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        exit_date=entry_date,
        exit_price=0,
        outcome="UNRESOLVED",
        gain=0,
        bet="D"
    )
    partial_operation_id = save_partial_operation_to_db(partial_operation=partial_record)
    partial_operation_id = 0 if not partial_operation_id else partial_operation_id
    # 5. add entry to direct bets json file
    direct_bet_file = load_json_file(BET_FILE)
    # build the json payload
    direct_bet_record = DirectBet(
        operation_id=operation_id,
        ticker=ticker,
        capital=capital,
        colateral=colateral,
        entry_date=entry_date,
        side=side,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        last_partial_id=partial_operation_id
    )
    direct_bet_file.update(direct_bet_record.as_json())
    save_json_file(BET_FILE, direct_bet_file)
    # finally inform
    logger.info(f"↩️ record {ticker} was added to actual bets file")

def scan_tangent_opportunities():
    config = load_json_file(CONFIG_FILE)
    tickers = load_json_file(TICKERS_FILE)["selected_tickers"]
    separation = config["separation"]
    threshold = config["threshold"]
    interval = config["timeframe"]
    
    # Unauthenticated client uses raw public REST responses
    client = Client()
    found_opportunities = []
    
    print(f"🔎 [PURE SCAN] Scanning tickers: {tickers}")
    # get direct bets tickers
    direct_bets = load_json_file(BET_FILE)
    secondary_bets = load_json_file(SECONDARY_BET_FILE)
    for ticker in tickers:
        # avoid tickers in actual bet
        if ticker in direct_bets:
            continue
        if ticker in secondary_bets:
            continue
        try:
            # Fetch raw kline information from Binance. Returns a list of lists.
            # limit parameter requests exactly what we need + a small safety buffer
            klines = client.futures_klines(symbol=ticker, 
                                       interval=interval, 
                                       limit=separation)
            
            # Extract out only the closing price (index 4 in Binance kline array format) 
            # and map it directly to floats
            epoch_ms = klines[-1][6] + 1 # last bar close time plus 1 ms
            entry_date = dt.fromtimestamp(epoch_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            last_close = float(klines[-1][4])
            first_close = float(klines[0][4])
            # tangent is: last close - first close / first close
            tangent_value = (last_close - first_close) / first_close
            entry_price = last_close
            if tangent_value >= threshold:
                # add entry in BUY:
                add_entry(ticker=ticker, side="BUY", entry_price=entry_price)
            elif tangent_value <= -threshold:
                # add entry in SELL
                add_entry(ticker=ticker, side="SELL", entry_price=entry_price)
                
        except Exception as e:
            print(f"❌ Error sweeping live REST data for {ticker}: {e}")
            
    return found_opportunities