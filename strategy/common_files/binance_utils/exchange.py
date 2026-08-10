# invercrypto/strategy/common_files/binance/exchange.py
import time
from binance.client import Client
from typing import List
from common_files.logger import get_logger

client = Client()

logger = get_logger(__name__)

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