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
    net_profit = calculate_net_profit(gain=gain, capital=capital)
    new_balance = main_balance + net_profit
    if new_balance <= 0:
        logger.info(f"🆘 [BALANCE TERMINATED] - The current balance is completed loss")
        new_balance = 0
    record = {"main_balance": new_balance}
    logger.info(f"🏛️ [BALANCE UPDATED] The new main balance is {new_balance: .2f}")
    save_json_file(MAIN_BALANCE, record)
    return new_balance

# available balance
def reduce_available_balance(colateral: float) -> float:
    """
    This function update the available balance by reducing
    the available balance for next position
    =====================================
    parameters:
    -------------------------------------
    colateral(float): max amount of loss on a position
    -------------------------------------
    returns:
    remain_balance(float): available capital for next operation
    Example:
        If the available_balance is 1500 and the colateral ammount for actual
        postion is 50, then, the available_balance for next position is 1450
    =======================================
    """
    # get the actual available balalce
    available_balance = load_json_file(AVAILABLE_BALANCE)
    actual_available_balance = available_balance["available_balance"]
    remain_balance = actual_available_balance - colateral
    available_balance["available_balance"] = remain_balance
    save_json_file(AVAILABLE_BALANCE, available_balance)
    logger.info(f"🏛️  [AVAILABLE BALANCE] The available balance remains in {remain_balance: .2f}")
    return remain_balance

def update_available_balance(capital: float) -> float:
    """
    This function add the capital (positive or negative) to the
    available balance
    ========================================
    parameters:
        capital(float): ammount added (or substracted) to the available_balance
    -----------------------------------------
    returns:
        final_balance(float): final available_balance for next position
    Example:
        - If the actual available balance is 1000, and capital is 200, the available_balance is
        updated to 1200, function returns 1200
        - If the actual available balance is 1000, and capital is -200, the available_balance
        is updated to 800, function returns 800
    """
    available_balance = load_json_file(AVAILABLE_BALANCE)
    actual_balance = available_balance["available_balance"]
    updated_balance = actual_balance + capital
    available_balance["available_balance"] = updated_balance
    save_json_file(AVAILABLE_BALANCE, available_balance)
    logger.info(f"🏛️  [AVAILABLE BALANCE] The updated available balance is {updated_balance: .2f}")
    return updated_balance

def calculate_notional_size(ticker:str):
    """
    This function calculates the money for a position (notional size)
    parameters:
    ------------------------
    ticker(str): name of ticker
    -------------------------
    returns:
    net_capital(float): net capital for the next position
    -------------------------
    """
    balance = load_json_file(AVAILABLE_BALANCE)["available_balance"]
    config = load_json_file(CONFIG_FILE)
    size = config["size_percentage"] # percentage of main capital
    # tickers in direct bet are necessary for evaluation
    direct_positions = load_json_file(BET_FILE)
    secondary_positions = load_json_file(SECONDARY_BET_FILE)
    total_positions = len(direct_positions) + len(secondary_positions)
    if total_positions > 5: # just half of the position
        size /= 2
    # finally the balance of ticker
    ticker_balance = load_json_file(TICKERS_BALANCES)[ticker]["actual_balance"]
    net_capital = balance * size * ticker_balance
    return net_capital

# colateral func
def calculate_colateral(capital: float) -> float:
    """
    This method calculates the colateral position for reduction
    of available balance
    =======================
    parameters:
        capital(float): capital used in a position
    -----------------------
    return:
        colateral(float): colateral capital that reduces the
        available balance for next position
    Examples:
    With a 10% sl_percentage configurated and 20x levarage
    a capital of 20 gets a colateral of
    20*0.1*20 = 40 -> colateral returned
    ========================
    """
    config = load_json_file(CONFIG_FILE)
    leverage = config["leverage"]
    max_sl = config["sl_percentage"] # maximum percentage of loss in a position
    colateral = capital * max_sl * leverage
    return colateral

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