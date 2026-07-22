import os
import json
from binance.client import Client
from datetime import datetime as dt
from datetime import UTC
# I/O files functions
from common_files.paths import *
from common_files.logger import get_logger
# notional size and balance functions
from common_files.balances import calculate_notional_size

logger = get_logger(__name__)

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
            # necessary data: entry_date, side, val, and entry_price
            print(f"tangent value for {ticker}: {tangent_value: .4f} and the threshold is {threshold}")
            print("is tangent <= -threshold?: ", tangent_value<=-threshold)
            # prepare notional size
            capital = calculate_notional_size(ticker=ticker)
            if tangent_value >= threshold:
                found_opportunities.append({"ticker": ticker,
                                            "capital": capital,
                                            "entry_date": entry_date,
                                            "side": "BUY",
                                            "val": tangent_value,
                                            "entry_price": last_close})
            elif tangent_value <= -threshold:
                found_opportunities.append({"ticker": ticker,
                                            "capital": capital,
                                            "entry_date": entry_date,
                                            "side": "SELL",
                                            "val": tangent_value,
                                            "entry_price": last_close})
                
        except Exception as e:
            print(f"❌ Error sweeping live REST data for {ticker}: {e}")
            
    return found_opportunities