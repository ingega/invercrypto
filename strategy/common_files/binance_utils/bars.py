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

# provide a different _name_ for correct mapping
logger_live = get_logger(
    f"{__name__}.live", # e.g. balance.live
    log_live=True,
)

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
            if logger_live.name.endswith(".live"):
                logger_live.exception("klines could not retrieved from binance side")
            else:    
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
            if logger_live.name.endswith(".live"):
                logger_live.exception(f"klines for {ticker} could not retrieved from binance side")    
            else:
                logger.exception(f"klines for {ticker} could not retrieved from binance side")
            attempts += 1
            if attempts >= 10:
                return {}
            time.sleep(1)
    return {}