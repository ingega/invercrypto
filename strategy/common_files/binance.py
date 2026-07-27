# invercrypto/strategy/common_files/binance.py
from binance.client import Client
from typing import List
"""
This module extract information from binance client such as klines, orders, etc
"""

# binance client
client = Client()

def get_bars(ticker:str, bars:int, interval:str) -> dict:
    """
    This functions retrives the bars information from binance futures
    """
    return client.futures_klines(
        symbol=ticker, 
        interval=interval, 
        limit=bars)

def get_actual_prices(ticker:str, interval: str) -> dict:
    """
    Retrive the actual bar, and return prices as a dict
    """
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

# important information related with LOT_SIZE and MIN_NOT for tickers

def get_binance_exchange_info(tickers: List[str]) -> list:
    exchange_info = client.futures_exchange_info()
    final_dict = []
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