# invercrypto/strategy/tangent/main.py
import csv
import asyncio
from datetime import datetime
from typing import Optional, List

# local functions
from utils.timing import wait_for_time_trigger
from tangent.filter import scan_tangent_opportunities
from common_files.binance import get_actual_prices
# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *

logger = get_logger(__name__)

# check direct bet function
def check_active_bets_resolution(actual_bets: Optional[list], 
                                 current_prices_dict: List[dict]):
    """
    Verifies open bets against current high/low/close data.
    For demonstration, we check against the current spot/mark price.
    In full integration, replace this with intra-hour 1m high/low data fetch.
    A function to retrieve data from binance is required
    :params:
        - actual_bets (list): a list with the actual tickers in direct bet
        - current_prices_dict: List[dict] list with current tickers prices
    """
    # first, verify if actual_bets contain tickers
    if len(actual_bets) == 0:
        logger.info(f"No bets found for {BET_FILE}")
        return None
    resolved_tickers = []
    init_csv_log()
    
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for ticker, bet in list(actual_bets.items()):
        # Pull current ticker price if available from stream/API
        current_price = current_prices_dict.get(ticker)
        if not current_price:
            continue
        # get the high and the low
        high = current_price[ticker]["high"]
        low = current_price[ticker]["low"]
        side = bet["side"]
        tp = bet["tp"]
        sl = bet["sl"]
        outcome = None
        
        # Determine tracking conditions based on position side
        if side == "BUY":  # Long Position
            if high >= tp:
                outcome = "TP"
            elif low <= sl:
                outcome = "SL"
        elif side == "SELL":  # Short Position
            if low <= tp:
                outcome = "TP"
            elif high >= sl:
                outcome = "SL"
                
        if outcome:
            # Append to institutional CSV Log
            # get the exit_price
            if outcome == "TP":
                exit_price = tp
            else:
                exit_price = sl
            # bets resolved going to csv files
            with open(OPERATIONS_FILE, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    bet.get("entry_date", current_time_str), # avoid error
                    ticker,
                    side,
                    bet["entry_price"],
                    tp,
                    sl,
                    current_time_str,
                    exit_price,
                    outcome
                ])
            # append the ticker that need to be removed in master bet json
            resolved_tickers.append(ticker)
            logger.info(f"🚨 OPERATION RESOLVED: {ticker} hit {outcome} at {current_price}")
            
    # Purge completed positions from the dictionary
    actual_bet_file = load_json_file(BET_FILE)
    for ticker in resolved_tickers:
        # remove it from actual_bets.json file
        del actual_bet_file[ticker]
    # finally update json file
    save_json_file(BET_FILE, actual_bet_file)
    
    return actual_bet_file

# aux function to build bet payload
def build_bet_payload(item: dict) -> dict:
    config = load_json_file(CONFIG_FILE)

    ticker = item["ticker"]
    entry_price = item["entry_price"]
    side = item["side"]
    entry_date = item["entry_date"]

    if side == "BUY":
        tp = entry_price * (1 + config["direct_bet_percentage"])
        sl = entry_price * (1 - config["direct_bet_percentage"])
    else:
        tp = entry_price * (1 - config["direct_bet_percentage"])
        sl = entry_price * (1 + config["direct_bet_percentage"])

    return {
        ticker: {
            "entry_date": entry_date,
            "entry_price": entry_price,
            "side": side,
            "tp": tp,
            "sl": sl,
        }
    }

async def main_engine_loop():
    logger.info("🤖 Invercrypto 2.0 Live Simulator Pipeline Initialize.")
    config = load_json_file(CONFIG_FILE)
    tickers = load_json_file(TICKERS_FILE)["selected_tickers"]
    # Configure variables for top-of-the-hour pre-emption (e.g., 3 seconds before close)
    TARGET_MIN = config["target_minutes"]
    TARGET_SEC = config["target_seconds"]
    
    while True:
        # 1. Yield thread control until the exact pre-emptive offset window is hit
        await wait_for_time_trigger(target_hour=0,
            target_minute=TARGET_MIN, target_second=TARGET_SEC)
        # 2. Fire the bet results, for that we need the actual prices
        actual_prices = {}
        actual_bets = load_json_file(BET_FILE)
        for ticker in tickers:
            data = get_actual_prices(ticker=ticker, interval=config["timeframe"])
            actual_prices[ticker] = data
        logger.info("⚡ Verifying the actual bets...")
        result = check_active_bets_resolution(actual_bets=actual_bets, 
                                              current_prices_dict=actual_prices)
        # result returns the pending oppor (actual tickers with unresolved bet)
        if result:
            logger.info(f"⚠️ [SCAN COMPLETE] - after the scanner, there's {len(result)} pendings bet")
        else:
            logger.info(f"⚠️ [SCAN COMPLETE] - there was no bets found")
        # 3. now, let's scan for new opportunities
        opportunities = scan_tangent_opportunities()
        if not opportunities:
            logger.info("🤷 Sweep complete. Zero opportunities matched current boundaries.")
        else:
            final_compose = {}
            for opp in opportunities:
                # we need to skip those tickers with an actual position
                if result and opp["ticker"] in result:
                    message = f"🖥️ [TICKER NOT AVALAIBLE] {opp['ticker']} "
                    message += f"actually is in a bet, the position was skiped"
                    logger.info(message)
                    continue
                alert_msg = (
                    f"🚨 Opportunity alarm: Ticker={opp['ticker']} | "
                    f"Directional-Side={opp['side']} | Tangent-Value={opp['val']:.4f} | "
                    f"Trigger-Price={opp['entry_price']}"
                )
                logger.info(alert_msg)
                # now let's add the ticker to json file, first we need complete data
                final_compose.update(build_bet_payload(opp))
            # 4. in this point we have the correct information in final compose to add at json file 
            new_bet_file = load_json_file(BET_FILE)
            for bet in final_compose.items():
                payload = {bet[0]: bet[1]}
                new_bet_file.update(payload)
            # 5. final movement, save the updated bet file
            save_json_file(BET_FILE, new_bet_file)
        # inform
        logger.info(f"✅[OPERATION COMPLETE] The revision and scaner oppor was completed")
                
                
        # Give a small buffer pause to prevent hitting the same execution second twice
        await asyncio.sleep(7)

if __name__ == "__main__":
    try:
        asyncio.run(main_engine_loop()) 
    except KeyboardInterrupt:
        logger.exception("\n🛑 Simulator runtime manually terminated safely. Standing down.")