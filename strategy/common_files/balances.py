# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *

logger = get_logger(__name__)

# ticker balance
def reset_ticker_balance():
    # get tickers
    tickers = load_json_file(TICKERS_FILE)["selected_tickers"]
    new_balances = {}
    for ticker in tickers:
        record = {ticker: {"actual_balance": 1.0}}
        new_balances.update(record)
    # save the file
    save_json_file(TICKERS_BALANCES, new_balances)

def update_ticker_balance(ticker: str, gain:float):
    # get config
    config = load_json_file(CONFIG_FILE)
    loss_protection = config["loss_protection"]
    adjust = gain * loss_protection
    # get tickers balance
    tickers_balances = load_json_file(TICKERS_BALANCES)
    actual_balance = tickers_balances[ticker]["actual_balance"]
    new_balance = actual_balance + adjust
    if new_balance > 1.0:
        new_balance = 1.0
    elif new_balance < config["minimum_bet"]:
        new_balance = config["minimum_bet"]
    tickers_balances[ticker]["actual_balance"] = new_balance
    save_json_file(TICKERS_BALANCES, tickers_balances)
    logger.info(f"🔢 [TICKER BALANCE] the balance in {ticker} was updated to {new_balance: .3f}")

def calculate_net_profit(gain:float, capital:float) -> float:
    """
    This function calculate the total profit
    Parameters:
    -------------------
    gain (float): percentage of gain/loss of the operation
    capital(float): the quantity of money used at begining of operation
    -------------------
    """
    # get leverage
    leverage = load_json_file(CONFIG_FILE)["leverage"]
    # calculate net profit
    return gain * leverage * capital
    
# main balance
def update_main_balance(gain:float, capital:float) -> float:
    # get balance
    main_balance = load_json_file(MAIN_BALANCE)["main_balance"]
    # get profit
    net_profit = calculate_profit(gain=gain, capital=capital)
    new_balance = main_balance + net_profit
    if new_balance <= 0:
        logger.info(f"🆘 [BALANCE TERMINATED] - The current balance is completed loss")
        new_balance = 0
    record = {"main_balance": new_balance}
    logger.info(f"🏛️ [BALANCE UPDATED] The new main balance is {new_balance: .2f}")
    save_json_file(MAIN_BALANCE, record)
    return new_balance

def calculate_notional_size(ticker:str):
    balance = load_json_file(MAIN_BALANCE)["main_balance"]
    size = load_json_file(CONFIG_FILE)["size_percentage"] # percentage of main capital
    # tickers in direct bet are necessary for evaluation
    direct_positions = load_json_file(BET_FILE)
    secondary_positions = load_json_file(SECONDARY_BET_FILE)
    total_positions = len(direct_positions) + len(secondary_positions)
    if total_positions > 5: # just half of the position
        size /= 2
    # finally the balance of ticker
    ticker_balance = load_json_file(TICKERS_BALANCES)[ticker]["actual_balance"]
    return balance * size * ticker_balance


def main():
    # get the capital for BTC first
    ticker = "BTCUSDT"
    capital = calculate_notional_size(ticker=ticker)
    gain = -0.05
    update_main_balance(gain=gain, capital=capital)
    update_ticker_balance(ticker=ticker, gain=gain)
    print("all routine completed")

if __name__ == "__main__":
    main()