# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *

logger = get_logger(__name__)

# provide a different _name_ for correct mapping
logger_live = get_logger(
    f"{__name__}.live", # e.g. balance.live
    log_live=True,
)

# class for updating balances in live mode

class LiveUpdateBalances:
    """
    Manages the live trading balances and risk reservation.
    The trading model works as follows:
        1. A percentage of the CURRENT available balance is allocated
           to a position.
        2. Leverage increases the position's notional exposure.
        3. The maximum SL percentage determines the maximum potential
           loss of that leveraged position.
        4. That maximum potential loss is reserved from the
           available balance.
    Example
    -------
    Main balance:
        $1,000
    Entry percentage:
        5%
    Position capital:
        $1,000 × 0.05 = $50
    Leverage:
        20x
    Notional exposure:
        $50 × 20 = $1,000
    Maximum SL:
        10%
    Maximum potential loss:
        $1,000 × 0.10 = $100
    Therefore:
        Main balance     = $1,000
        Available balance = $1,000 - $100 = $900
    The next position is calculated using the new available balance:
        $900 × 5% = $45
        $45 × 20 × 10% = $90 reserved
    This creates a dynamic risk budget where each new position
    consumes a percentage of the remaining available balance.
    Parameters
    ----------
    capital:
        Position capital allocated by the strategy.
    """
    def __init__(self, capital: float) -> None:
        """
        Initialize the balance manager.
        Parameters
        ----------
        capital:
            Position capital allocated to the current operation.
        """
        self.capital = float(capital)

    # ------------------------------------------------------------------
    # Internal balance update
    # ------------------------------------------------------------------

    def _update_balance(self, balance_key: str) -> None:
        """
        Apply self.capital to a specific balance.
        The current balance file is loaded immediately before the
        update to avoid working with stale in-memory data.
        Parameters
        ----------
        balance_key:
            JSON key to update.
            Supported values:
                - "main_balance"
                - "available_balance"
        """
        try:
            balances = load_json_file(LIVE_BALANCES)
            old_balance = float(
                balances.get(balance_key, 0.0)
            )
            new_balance = round(
                old_balance + self.capital,
                2,
            )
            # Prevent accidental negative balances.
            if new_balance < 0:
                raise ValueError(
                    f"Balance '{balance_key}' cannot become negative. "
                    f"old={old_balance:.2f}, "
                    f"delta={self.capital:.2f}, "
                    f"new={new_balance:.2f}"
                )
            # Constraint: available_balance <= main_balance
            main_balance = balances.get("main_balance")

            if balance_key == "available_balance":
                if main_balance is not None:
                    if new_balance > main_balance:
                        logger.error(
                            "❌🏛️ [AVAILABLE BALANCE] the available balance: %.4f "
                            "is greater than main balance: %.4f, it will be set to main balance",
                            new_balance,
                            main_balance,
                        )
                        new_balance = main_balance
                    else:
                        logger.info("✅ [AVAILABLE BALANCE] available balance: %.4f is correctly" 
                                    " lt main balance: %.4f",
                                    new_balance, main_balance)
            

            balances[balance_key] = new_balance
            save_json_file(
                LIVE_BALANCES,
                balances,
            )
            logger_live.info(
                "🏛️ [%s] balance updated: %.2f → %.2f "
                "(delta=%+.2f)",
                balance_key.upper(),
                old_balance,
                new_balance,
                self.capital,
            )
            try:
                # verify if gets double or more
                initial_balance = load_json_file(CONFIG_LIVE_FILE)["initial_balance"]
                if new_balance >= (initial_balance * 2):
                    logger_live.info("🟩 [DUPLICATED BALANCE] strategy duplicates its"
                                     "original balance, a withdrawall will be executed")
                    self.withdrawal_balance()
                    
            except Exception as e:
                logger.exception("❌ [DUPLICATED BALANCE] an error ocurred attempting call "
                                 " a withdrawal: %s", e)
                return
        except Exception:
            logger_live.exception(
                "❌ [%s] failed to update balance.",
                balance_key.upper(),
            )
            raise

    # ------------------------------------------------------------------
    # Main balance
    # ------------------------------------------------------------------

    def update_main_balance(self) -> None:
        """
        Update the main balance using self.capital.
        Positive capital increases the balance.
        Negative capital decreases the balance.
        Example
        -------
        capital = +25.50
            1000.00 → 1025.50
        capital = -25.50
            1000.00 → 974.50
        """

        self._update_balance("main_balance")

    # ------------------------------------------------------------------
    # Available balance
    # ------------------------------------------------------------------

    def update_available_balance(self) -> None:
        """
        Update the available balance using self.capital.
        This is normally used when reserving or releasing capital
        associated with active positions.
        """

        self._update_balance("available_balance")

    # ------------------------------------------------------------------
    # Collateral / maximum-loss calculation
    # ------------------------------------------------------------------

    def calculate_collateral(self) -> float:
        """
        Calculate and reserve the maximum potential loss of the
        leveraged position.
        The calculation is:
            collateral =
                position_capital
                × leverage
                × max_sl
        Example
        -------
        position_capital = $50
        leverage         = 20x
        max_sl            = 10%
        Notional exposure:
            $50 × 20 = $1,000
        Maximum potential loss:
            $1,000 × 0.10 = $100
        Therefore $100 is reserved from available balance.
        Returns
        -------
        float
            The collateral reserved for the position.
        """
        try:
            config = load_json_file(CONFIG_LIVE_FILE)
            max_sl = float(
                config.get("sl_percentage", 0.10)
            )
            leverage = float(
                config.get("leverage", 20)
            )
            position_capital = self.capital
            if position_capital <= 0:
                raise ValueError(
                    f"Position capital must be positive. "
                    f"Received: {position_capital}"
                )
            if leverage <= 0:
                raise ValueError(
                    f"Leverage must be positive. "
                    f"Received: {leverage}"
                )
            if not 0 < max_sl <= 1:
                raise ValueError(
                    f"SL percentage must be between 0 and 1. "
                    f"Received: {max_sl}"
                )

            # ----------------------------------------------------------
            # Calculate leveraged notional exposure.
            # ----------------------------------------------------------

            notional_exposure = (
                position_capital * leverage
            )

            # ----------------------------------------------------------
            # Calculate maximum potential loss.
            #
            # This is the amount we must reserve from the
            # available balance to protect against the configured
            # maximum SL.
            # ----------------------------------------------------------

            collateral = round(
                notional_exposure * max_sl,
                2,
            )

            logger_live.info(
                "🏛️ [COLLATERAL] position_capital=%.2f | "
                "leverage=%.2fx | notional=%.2f | "
                "max_sl=%.2f%% | collateral=%.2f",
                position_capital,
                leverage,
                notional_exposure,
                max_sl * 100,
                collateral,
            )
            return collateral
        except Exception:
            logger_live.exception(
                "❌ [COLLATERAL] failed to calculate/update collateral."
            )
            raise

    def reserve_collateral(self):            
        # ----------------------------------------------------------
        # Reserve collateral from available balance.
        # ----------------------------------------------------------
        collateral = self.calculate_collateral()
        self.capital = -collateral
        self.update_available_balance()
        logger_live.info(
            "🏛️ [COLLATERAL] %.2f reserved from available balance.",
            collateral,
        )

    def restore_collateral(self):
        """
        In this case, capital is the collateral returned to the balance
        """
        self.update_available_balance()

    # ------------------------------------------------------------------
    # Ticker balances
    # ------------------------------------------------------------------

    def update_ticker_balance(self, ticker: str, gain:float):
        """
        update the individual ticker balance
        constraints:
            ticker balance never is above 1.0 and below config["minimum_bet]
        ---------------------
        params:
            ticker(str) - Name of the ticker e.g. "BTCUSDT"
            gain(float) - gain of the operation e.g. 0.01 or -0.01
        """
        try:
            # open the ticker balance json file
            ticker_balance_file = load_json_file(TICKERS_BALANCES_LIVE)
            ticker_balance = ticker_balance_file[ticker]
            # get the minimum value for balance
            config = load_json_file(CONFIG_LIVE_FILE)
            minimum_ticker_balance = config.get("minimum_bet", 0.005)
            loss_protection = config.get("loss_protection", 1)
            if ticker_balance is None:
                logger_live.error(f"❌ [TICKER BALANCE] ticker {ticker} does not exist in {TICKERS_BALANCES_LIVE} file")
                raise ValueError(f"Invalid value: {ticker}")
            actual_balance = ticker_balance["actual_balance"]
            new_balance = actual_balance + (gain * loss_protection)
            if new_balance > 1.0:
                new_balance = 1.0
            elif new_balance < minimum_ticker_balance:
                new_balance = minimum_ticker_balance
            ticker_balance_file[ticker]["actual_balance"] = new_balance
            save_json_file(TICKERS_BALANCES_LIVE, ticker_balance_file)
            logger_live.info(f"🏛️ [BALANCES] {ticker} balance was succesfully updated from {actual_balance} to {new_balance}")
        except Exception as e:
            logger_live.exception("❌ [TICKER BALANCE] an exception ocurred during execution")
            raise RuntimeError ("update ticker balance fails") from e

    # ------------------------------------------------------------------
    # Collect / withdrawls
    # ------------------------------------------------------------------

    def reset_balance(self):
        """
        This method collect an ammount set in config['initial_balance']
        once profit reaches the ammount
        Workflow:
            1. Once this method is called, the main balance is reseted
            2. The available balance is substracted to the reseted main balance
        """
        try:
            config = load_json_file(CONFIG_LIVE_FILE)
            balances = load_json_file(LIVE_BALANCES)
            original_balance = config['initial_balance']
            balances["main_balance"] = original_balance
            save_json_file(LIVE_BALANCES, balances)
            # retrieve balance again, for safety
            updated_main_balance = load_json_file(LIVE_BALANCES)["main_balance"]
            logger_live.info("🏛️  [RESET BALANCE] main balance was reset to %.2f", 
                            updated_main_balance)
        except Exception:
            logger.exception("❌ [RESET BALANCE] balance could not be reseted")
            # return avoids execution break
            return

    def withdrawal_balance(self):
        """
        This method creates a virtual withdrawal for the main balance
        Validation: main balance must be above of double of the initial
        """
        # validate the balance
        main_balance = load_json_file(LIVE_BALANCES)["main_balance"]
        initial_balance = load_json_file(CONFIG_LIVE_FILE)['initial_balance']
        if main_balance < (2 * initial_balance):
            logger_live.error("❌  [WITHDRAWAL] actual balance is not duplicated yet")
            return
        withdrawal = main_balance - initial_balance
        # just create a logger info entry, that serves as evidence and track
        logger.info("🏛️ [WITHDRAWAL] a virtual withdrawal of %.4f was executed", withdrawal)
        # reset the main balance
        self.reset_balance()


def update_all_balances(profit: float, capital: float, gain: float, ticker: str, end_operation=False):
    """
    Every time that an operation complete its cycle, all balances must be updated:
    ---------------------
    main balance
    ---------------------
    :param: profit(float) - net profit of the operation e.g. -100 (usdt) or 100 (usdt)
    update the main balance acording param profit
    
    ---------------------
    available balance
    ---------------------
    :param: capital(float) - capital used in the position e.g. 100 (usdt) 
    update the available balance using param capital for calculations

    ---------------------
    ticker balance
    ---------------------
    :param: ticker(str) - name of ticker e.g. "BTCUSDT"
    :param: gain(float) - gain of the operation e.g. 0.02
    the ticker balance is updated with param gain
    """
    # 1. update main balance
    balances = LiveUpdateBalances(capital=profit)
    balances.update_main_balance()

    # 2. update available balance

    # A. get a new instance of LiveUpdateBalance for new calculations
    available_balances = LiveUpdateBalances(capital=capital)
    if end_operation is False:
        # is the init of the operation, collateral must be retailed
        collateral = available_balances.calculate_collateral()
        # B. with collateral calculated, again build a new instance for balances
        updated_available_balances = LiveUpdateBalances(capital=collateral)
        # finally update available balance
        updated_available_balances.update_available_balance()
    else:
        # it is the end of the operation, collateral must be restored
        collateral = available_balances.restore_collateral()
    

    # 3. update ticker balance 
    # in this case we can use any instance, capital parameter is not used for ticker balance update
    balances.update_ticker_balance(ticker=ticker, gain=gain)

    logger_live.info(f"✅ [UPDATE BALANCES] all balances was updated")

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
    # get the actual available balance
    available_balance = load_json_file(AVAILABLE_BALANCE)
    actual_available_balance = available_balance["available_balance"]
    remain_balance = actual_available_balance - colateral
    available_balance["available_balance"] = remain_balance
    save_json_file(AVAILABLE_BALANCE, available_balance)
    logger.info(f"🏛️  [AVAILABLE BALANCE] The available balance remains in {remain_balance: .2f}")
    return remain_balance

def update_available_balance(gain: float, capital: float, colateral: float) -> float:
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
        - If the actual available balance is 1000, and profit is 200, the available_balance is
        updated to 1200, function returns 1200
        - If the actual available balance is 1000, and profit is -200, the available_balance
        is updated to 800, function returns 800
    """
    # calculates the profit first
    leverage = load_json_file(CONFIG_FILE)["leverage"]
    profit = gain * leverage * capital
    available_balance = load_json_file(AVAILABLE_BALANCE)
    actual_balance = available_balance["available_balance"]
    updated_balance = actual_balance + profit + colateral
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

def reset_balances():
    config = load_json_file(CONFIG_FILE)
    initial_balance = config.get("initial_balance", 1500)
    # main
    main_balance = load_json_file(MAIN_BALANCE)
    main_balance["main_balance"] = initial_balance
    save_json_file(MAIN_BALANCE, main_balance)
    logger.info(f"🏛️ [BALANCES] main_balance was reseted to {initial_balance}")
    # available
    available_balance = load_json_file(AVAILABLE_BALANCE)
    available_balance["available_balance"] = initial_balance
    save_json_file(AVAILABLE_BALANCE, available_balance)
    logger.info(f"🏛️ [BALANCES] available_balance was reseted to {initial_balance}")
    # tickers
    tickers_balances = load_json_file(TICKERS_BALANCES)
    for ticker in tickers_balances:
        tickers_balances[ticker]["actual_balance"] = 1.0
    save_json_file(TICKERS_BALANCES, tickers_balances)
    logger.info(f"🏛️ [BALANCES] ticker balances was reseted to 1.0")
    


def main():
    # create a withdrawal
    balance = LiveUpdateBalances(capital=0)
    balance.withdrawal_balance()

if __name__ == "__main__":
    main()