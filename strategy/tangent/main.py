# invercrypto/strategy/tangent/main.py
import asyncio

# local functions
from common_files.bets import check_active_bets_resolution, resolve_secondary_bets
from common_files.binance import get_actual_prices
from tangent.filter import scan_tangent_opportunities
from utils.timing import wait_for_time_trigger
# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *

logger = get_logger(__name__)


# aux function to build bet payload
def build_bet_payload(item: dict) -> dict:
    config = load_json_file(CONFIG_FILE)

    ticker = item["ticker"]
    entry_price = item["entry_price"]
    side = item["side"]
    entry_date = item["entry_date"]
    tangent = item["val"]

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
            "tangent": tangent,
            "side": side,
            "tp": tp,
            "sl": sl,
        }
    }

async def main_engine_loop():
    logger.info("🤖 Invercrypto 2.0 Live Simulator Pipeline Initialize.")
    config = load_json_file(CONFIG_FILE)
    tickers_file = load_json_file(TICKERS_FILE)
    tickers = tickers_file["selected_tickers"]
    # Configure variables for top-of-the-hour pre-emption (e.g., 3 seconds before close)
    TARGET_MIN = config["target_minutes"]
    TARGET_SEC = config["target_seconds"]
    
    while True:
        # 1. Yield thread control until the exact pre-emptive offset window is hit
        await wait_for_time_trigger(target_hour=0,
            target_minute=TARGET_MIN, target_second=TARGET_SEC)
        # 2. Fire the bet results, for that we need the actual prices
        actual_prices = {}
        for ticker in tickers:
            data = get_actual_prices(ticker=ticker, interval=config["timeframe"])
            actual_prices[ticker] = data
        logger.info("⚡ Verifying the actual bets...")
        result = check_active_bets_resolution(current_prices_dict=actual_prices)
        # result returns the pending oppor (actual tickers with unresolved bet)
        if result:
            direct_bets = len(result[0])
            secondary_bets = len(result[1])
            logger.info(f"⚠️ [SCAN COMPLETE] - after the scanner, there's " 
                        f"{direct_bets} directs and {secondary_bets} secondary pending bets")
        else:
            logger.info(f"⚠️ [SCAN COMPLETE] - there was no bets found")
        # next step: verify the secondary bets
        # open secondary bet file
        secondary_bet_file = load_json_file(SECONDARY_BET_FILE)
        secondary_bets_result = resolve_secondary_bets(secondary_bets=secondary_bet_file,
                                                       current_prices=actual_prices)
        # save the new values for sec bet
        save_json_file(SECONDARY_BET_FILE, secondary_bets_result)
        # 3. now, let's scan for new opportunities
        opportunities = scan_tangent_opportunities()
        if not opportunities:
            logger.info("🤷 Sweep complete. Zero opportunities matched current boundaries.")
        else:
            final_compose = {}
            for opp in opportunities:
                # this tikver are already filtered
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