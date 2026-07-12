# invercrypto/strategy/common_files/binance.py
from binance.client import Client
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