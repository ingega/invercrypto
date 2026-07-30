# invercrypto/strategy/common_files/binance.py
import time
from binance.client import Client
from typing import List
from common_files.logger import get_logger
"""
This module extract information from binance client such as klines, orders, etc
"""

# binance client
client = Client()

# logger
logger = get_logger(__name__)

def get_bars(ticker:str, bars:int, interval:str) -> dict:
    """
    This functions retrives the bars information from binance futures
    """
    attempts = 0
    while attempts < 10:
        try:
            return client.futures_klines(
                symbol=ticker, 
                interval=interval, 
                limit=bars)
        except:
            logger.exception("klines could not retrieved from binance side")
            attempts += 1
            if attempts >= 10:
                return {}
    return {}

def get_actual_prices(ticker:str, interval: str) -> dict:
    """
    Retrive the actual bar, and return prices as a dict
    """
    attempts = 0
    while attempts < 10:
        try:
            kline =client.futures_klines(
                symbol=ticker, 
                interval=interval, 
                limit=1)[0] # just the actual bar
            # kline[1:4] is OHLC in str
            return {
                ticker:{
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4])
                }
            }
        except:
            logger.exception(f"klines for {ticker} could not retrieved from binance side")
            attempts += 1
            if attempts >= 10:
                return {}
            time.sleep(1)
    return {}

# important information related with LOT_SIZE and MIN_NOT for tickers

def get_binance_exchange_info(tickers: List[str]) -> list:
    # avoid binance break
    attempts = 0
    exchange_info = {}
    final_dict = []
    while attempts < 10:
        try:    
            exchange_info = client.futures_exchange_info()
            break
        except:
            logger.exception("failute in binance side")
            attempts += 1
            if attempts >= 10: # binance could not recover
                return []
            # wait 1 second, binance almost all time self-recorvers
            time.sleep(1)
    for symbol in exchange_info["symbols"]:
        if symbol["symbol"] in tickers:
            filter = symbol["filters"]
            min_qty = filter[1]["minQty"]
            min_notional = filter[4]["notional"]
            record = {
                "ticker": symbol["symbol"],
                "min_qty": min_qty,
                "min_notional": min_notional
            }
            final_dict.append(record)

    return final_dict

def main():
    tickers = ["BTCUSDT", "BELUSDT"]
    information = get_binance_exchange_info(tickers=tickers)
    for t in information:
        print(t)

if __name__ == "__main__":
    main()