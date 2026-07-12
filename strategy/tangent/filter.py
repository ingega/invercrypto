import os
import json
from binance.client import Client
# I/O files functions
from common_files.paths import *
from common_files.logger import get_logger

logger = get_logger(__name__)

def calculate_tangent_pure(closes: list, separation: int) -> float:
    """
    Computes the mathematical slope using standard primitive lists.
    Avoids all library indexing overhead.
    """
    if len(closes) < separation + 1:
        return 0.0
    
    current_price = closes[-1]
    historical_anchor = closes[-(separation + 1)]
    
    # Structural tangent slope formula remains pristine
    return (current_price - historical_anchor) / historical_anchor

def scan_tangent_opportunities():
    config = load_json_file(CONFIG_FILE)
    tickers = load_json_file(TICKERS_FILE)["selected_tickers"]
    separation = config["separation"]
    threshold = config["threshold"]
    interval = config["timeframe"]
    
    # Unauthenticated client uses raw public REST responses
    client = Client()
    found_opportunities = []
    
    logger.info(f"🔎 [PURE SCAN] Scanning tickers: sep={separation}, threshold={threshold * 100}% "
                f"list of tickers: {tickers}")
    
    for ticker in tickers:
        try:
            # Fetch raw kline information from Binance. Returns a list of lists.
            # limit parameter requests exactly what we need + a small safety buffer
            klines = client.get_klines(symbol=ticker, 
                                       interval=interval, 
                                       limit=separation + 5)
            
            # Extract out only the closing price (index 4 in Binance kline array format) 
            # and map it directly to floats
            closes = [float(candle[4]) for candle in klines]
            
            # Run the native slope math
            tangent_value = calculate_tangent_pure(closes, separation)
            current_price = closes[-1]
            if tangent_value >= threshold:
                found_opportunities.append({"ticker": ticker,
                                            "side": "BUY",
                                            "val": tangent_value,
                                            "entry_price": current_price})
            elif tangent_value <= -threshold:
                found_opportunities.append({"ticker": ticker, "side": "SELL", "val": tangent_value, "entry_price": current_price})
                
        except Exception as e:
            print(f"❌ Error sweeping live REST data for {ticker}: {e}")
            
    return found_opportunities