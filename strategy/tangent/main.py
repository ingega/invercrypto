# invercrypto/strategy/tangent/main.py
import asyncio

# local functions
from common_files.bets import check_active_bets_resolution, resolve_secondary_bets, reset_bets
from common_files.binance_utils.bars import get_actual_prices
from tangent.filter import scan_tangent_opportunities
from utils.timing import wait_for_time_trigger
# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *
# balances
from common_files.balances import reset_balances
# database
from database import reset_completed_operations, reset_partial_operations

logger = get_logger(__name__)

async def main_engine_loop():
    """
    workflow:
    while True:
        1. Trigger time control
        2. Review direct bet result
        3. Review secondary_bet result
        4. call scanner opportunities
    """
    logger.info("🤖 Invercrypto 2.0 Live Simulator Pipeline Initialize.")
    config = load_json_file(CONFIG_FILE)
    tickers_file = load_json_file(TICKERS_FILE)
    tickers = tickers_file["selected_tickers"]
    ##### pipeline for strategy reset #####################
    # 1. remove all logs
    # 2. Call reset_completed_operations
    # 3. Call reset_partial_operations
    # 4. Call reset_balances
    # 5. remove bets and partial bets
    #########################################################
    reset_strategy = config.get("reset_strategy", False)
    if reset_strategy:
        # 1. reset log file
        try:
            with open(LOG_FILE, "r+") as file:
                file.truncate(0)
                file.close()
        except:
            logger.warning(f"⚠️ [LOG] The logger file could not have been reset.")
        # 2. reset completed operations
        reset_completed_operations()
        # 3. reset partial operations
        reset_partial_operations()
        # 4. reset balances
        reset_balances()
        # 5. remove bets and partial bets
        reset_bets()
        # avoid loop or accidents
        config["reset_strategy"] = False
        save_json_file(CONFIG_FILE, config)
    elif reset_strategy is None:
        logger.info(f"⚠️ [CONFIG] Variable 'reset_strategy' is not present in config file")

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
            data = get_actual_prices(ticker=ticker, interval="1m")
            actual_prices[ticker] = data
        print("⚡ Verifying the actual bets...")
        check_active_bets_resolution(current_prices_dict=actual_prices)
        # inform how many bets are active
        dir_bets = load_json_file(BET_FILE)
        sec_bets = load_json_file(SECONDARY_BET_FILE)
        main_balance = load_json_file(MAIN_BALANCE)["main_balance"]
        direct_bets = len(dir_bets)
        secondary_bets = len(sec_bets)
        # secondary bet need to be loaded
        print(f"🔵 [SCAN COMPLETE] - after the scanner, there's " 
                    f"{direct_bets} directs and {secondary_bets} secondary pending bets, main balance remains in: {main_balance}")
        # III: verify the secondary bets
        resolve_secondary_bets(secondary_bets=sec_bets, current_prices=actual_prices)
        # 4. scan for new opportunities
        scan_tangent_opportunities()
        # inform
        print(f"✅[OPERATION COMPLETE] The revision and scaner oppor was completed")
        # Give a small buffer pause to prevent hitting the same execution second twice
        await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main_engine_loop()) 
    except KeyboardInterrupt:
        logger.exception("\n🛑 Simulator runtime manually terminated safely (user key press). Standing down.")