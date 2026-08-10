# invercrypto/strategy/common_files/bets.py
# importation in alpha sorted
from datetime import datetime, timedelta
from typing import List, Tuple
# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *
# database operations
from data_classes import CompletedOperation, PartialOperation, UpdateCompletedOperation 
from data_classes import UpdatePartialOperation
from data_classes import SecondaryBet
# live operations
from data_classes import AddBetToJSON
from database import save_partial_operation_to_db, update_completed_operations, update_partial_operations
# balance operations
from common_files.balances import calculate_net_profit, update_available_balance 
from common_files.balances import update_main_balance, update_ticker_balance, calculate_colateral
"""
This module contains the direct and secondary bets and neccsesary function for the execution
"""

logger = get_logger(__name__)

class DataError(Exception):
    pass

# aux classes to add/remove bets from file
class ActualBets:
    def __init__(self, data:dict | None = None, ticker: str | None = None):
        if data:
            self.data = data
        if ticker:
            self.ticker = ticker

    def remove_bet(self):
        if not self.ticker:
            raise DataError("Remove a ticker from actual_bets.json file, requires parameter ticker")
        actual_bets_file = load_json_file(BET_FILE)
        actual_bets_file.pop(self.ticker)
        save_json_file(BET_FILE, actual_bets_file)
        logger.info(f"☑️ [DIRECT BET FILE] ticker {self.ticker} was removed from actual bets file")

class SecondaryBets:
    def __init__(self, secondary_bet:SecondaryBet | None = None, ticker: str | None = None):
        if secondary_bet:
            self.data = secondary_bet
        if ticker:
            self.ticker = ticker

    def add_secondary_bet(self):
        if not self.data:
            raise DataError(
                "Add a ticker to secondary_bets.json file, requires parameter secondary_bet"
                )
        secondary_dict = self.data.as_json()
        actual_secondary_bets_file = load_json_file(SECONDARY_BET_FILE)
        actual_secondary_bets_file.update(secondary_dict)
        save_json_file(SECONDARY_BET_FILE, actual_secondary_bets_file)
        # retrieve ticker
        ticker = next(iter(secondary_dict))
        data_value = secondary_dict[ticker]
        logger.info(f"🟡 [SECONDARY BETS] ticker {ticker} was added to secondary "
                    f" bets file with value: {data_value}")

    def remove_secondary_bet(self):
        if not self.ticker:
            raise DataError("Remove a ticker from secondary_bets.json file, requires parameter ticker")
        actual_secondary_bets_file = load_json_file(SECONDARY_BET_FILE)
        actual_secondary_bets_file.pop(self.ticker)
        save_json_file(SECONDARY_BET_FILE, actual_secondary_bets_file)
        logger.info(f"☑️ [DIRECT BET FILE] ticker {self.ticker} was removed from actual bets file")

    def update_secondary_bet(self,
            actual_loss_percentage: float,
            actual_side: str,
            tp: float,
            sl: float,
            last_partial_id: int
        ):
        actual_partial_file = load_json_file(SECONDARY_BET_FILE)
        data = {
            "actual_loss_percentage": actual_loss_percentage,
            "actual_side": actual_side,
            "tp": tp,
            "sl": sl,
            "last_partial_id": last_partial_id
        }
        # update ticker data
        actual_partial_file[self.ticker].update(data)
        final_data = actual_partial_file[self.ticker]
        operation_id = actual_partial_file[self.ticker]["operation_id"]
        save_json_file(SECONDARY_BET_FILE, actual_partial_file)
        logger.info(f"2️⃣ [SEC BET FILE] ticker {self.ticker} in operation id: " 
                    f"{operation_id} was uptated with these new values: {final_data}")


# aux secondary bet function
def calculate_flip_brackets(side: str, 
                            entry_price: float, 
                            total_loss_pct: float) -> Tuple[float, float]:
    """Calculates brackets for a flipped leg based on relative percentage debt."""
    # values of the configuratio is in config.json
    config = load_json_file(CONFIG_FILE)
    if side == "BUY":
        sl = entry_price * (1.0 - config["flip_percentage"])
        tp = entry_price * (1.0 + total_loss_pct + config["profit_percentage"])
    else:  # SELL
        sl = entry_price * (1.0 + config["flip_percentage"])
        tp = entry_price * (1.0 - total_loss_pct - config["profit_percentage"])
    return tp, sl

def flip_worlflow(ticker:str,
                  acummulated_loss: float,
                  actual_side: str,
                  tp: float,
                  sl: float,
                  update_partial_operation: UpdatePartialOperation,
                  partial_operation: PartialOperation,
                  ):
    """
    This pipeline is executed when a position get a "flip" loss bet
    1. Update partial_operation
    1. add partial_entry
    2. update vars in secondary_bets
        A. acummulated_loss
        B. entry_date (equal to last exit_date)
        C. Actual side
        D. new tp, sl
    """
    # 1. update partial operation
    update_partial_operations(update_partial_operation=update_partial_operation)
    # 2. add partial_entry and retrieve new id
    partial_id = save_partial_operation_to_db(partial_operation=partial_operation)
    partial_id = 0 if not partial_id else partial_id
    # 3. update vars in secondary_lost
    # get entry_date
    entry_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_sec_json = SecondaryBets(ticker=ticker)
    update_sec_json.update_secondary_bet(
        actual_loss_percentage=acummulated_loss,
        actual_side=actual_side,
        tp=tp,
        sl=sl,
        last_partial_id=partial_id
    )
    logger.info(f"🟠 [SECONDARY BET] record {ticker} added to partial record with"
                f"an acummulated loss of: {acummulated_loss} new side: {actual_side} at {entry_date}")
    
def calculate_profit(side: str, entry_price: float, close_price: float):
    if side == "BUY":
        return (close_price - entry_price) / entry_price
    elif side == "SELL":
        return (entry_price - close_price) / entry_price
    return

# secondary bet workflow
def secondary_bet_resolution(ticker: str,
                            exit_price: float,
                            outcome: str,
                            gain: float,
                            leg_gain: float,
                            operation_id: int,
                            capital: float, 
                             ):
    """
    Executes a pipeline if a secondary bet is resolved or flips
    1. update partial operation.
    2. Update completed operation.
    3. Update main balance.
    4. Update available balance.
    5. Update ticker balance.
    6. Remove ticket from secondary_bet
    """
    # 1. update partial record
    # get or calculate necessary data
    logger.info(f"2️⃣ [SEC BET] secondary bet resulution for {ticker} with outcome"
                f" {outcome} starts here\n{'*' * 50}")
    exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # get partial id
    partial_id = load_json_file(SECONDARY_BET_FILE)[ticker]["last_partial_id"]
    # the record is updated with leg_gain
    update_partial_record = UpdatePartialOperation(
        exit_date=exit_date,
        exit_price=exit_price,
        outcome=outcome,
        gain=leg_gain,
        partial_id=partial_id
    )
    update_partial_operations(update_partial_operation=update_partial_record)
    # 2. update completed operation
    # add missing values
    profit = calculate_net_profit(gain=gain, capital=capital)
    # in this case, is net gain
    update_operation_record = UpdateCompletedOperation(
        outcome=outcome,
        gain=gain,
        profit=profit,
        operation_id=operation_id
    )
    update_completed_operations(update_completed_operation=update_operation_record)
    # 3. update main balance
    update_main_balance(gain=gain, capital=capital)
    # 4. update available balance
    # get colateral
    colateral = load_json_file(SECONDARY_BET_FILE)[ticker]["colateral"]
    update_available_balance(gain=gain, capital=capital, colateral=colateral)
    # 5. update ticker balance
    update_ticker_balance(ticker=ticker, gain=gain)
    # 6. remove ticker from secodary bet
    secondary_bet = SecondaryBets(ticker=ticker)
    secondary_bet.remove_secondary_bet()
    logger.info(f"2️⃣ [SEC BET] secondary bet resulution for {ticker} with outcome"
                    f" {outcome} ends here\n{'*' * 50}")

# secondary bet function
def resolve_secondary_bets(secondary_bets: dict, current_prices: dict) -> dict:
    """
    Checks active secondary flip paths at 1-minute intervals.
    Handles the 10% structural circuit breaker and 24-hour TIE expiration constraints.
    """
    remaining_secondary = {}
    current_time = datetime.now()
    config = load_json_file(CONFIG_FILE)
    exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ticker, bet in secondary_bets.items():
        price_data = current_prices.get(ticker)
        if not price_data:
            remaining_secondary[ticker] = bet
            continue
        # retrieve data
        entry_date = bet["entry_date"]
        actual_side = bet["actual_side"]
        entry_price = bet["entry_price"]
        exit_price = price_data[ticker]["close"]
        tp = bet["tp"]
        sl = bet["sl"]
        operation_id = bet["operation_id"]
        last_partial_id = bet["last_partial_id"]
        capital = bet["capital"]
        # 1. 24-Hour Time-Expiration (TIE) Safety Engine Check
        start_time = datetime.strptime(bet["cycle_start_time"], "%Y-%m-%d %H:%M:%S")
        # minutes provided by config
        minutes = config["stop_bet_minutes"]
        if current_time - start_time >= timedelta(minutes=minutes):
            # calculate this leg profit
            leg_profit = calculate_profit(side=actual_side,
                                          entry_price=entry_price,
                                          close_price= exit_price)
            # gain is this leg profit minus the acummulated loss
            # example: this_leg_profit: 1%, accumulated profit: 2%, net=1%-2%=-1%
            # example: this_leg_profit: -1%, accumulated profit: 2%, net=-1%-2%=-3%
            gain = leg_profit - bet["actual_loss_percentage"]
            # call the resolution pipeline
            # in this case, leg_gain is for partial operation, and gain for completed operation
            secondary_bet_resolution(
                ticker=ticker,
                exit_price=exit_price,
                outcome="TIE",
                gain=gain,
                leg_gain=leg_profit,
                operation_id=operation_id,
                capital=capital
            )
            logger.warning(f"⏱️ TIME TIE CONSTRAINT BREACHED: Liquidating cycle for {ticker}.")
            continue
        high, low = price_data[ticker]["high"], price_data[ticker]["low"]
        side, tp, sl = bet["actual_side"], bet["tp"], bet["sl"]
        outcome = None

        if side == "BUY":
            if high >= tp: outcome = "TP"
            elif low <= sl: outcome = "SL"
        elif side == "SELL":
            if low <= tp: outcome = "TP"
            elif high >= sl: outcome = "SL"

        if outcome == "TP":
            # actually is tp - commission
            tp_gain = config["profit_percentage"] - config["commision"] # gain
            # this leg gain, is tp_gain - actual_loss_precentage
            tp_leg_gain = tp_gain - config["sl_percentage"]
            # execute secondary resolved pipeline
            secondary_bet_resolution(
                ticker=ticker,
                exit_price=tp,
                outcome="TP",
                gain=tp_gain,
                leg_gain=tp_leg_gain,
                operation_id=operation_id,
                capital=capital
            )
            logger.info(f"🏆 SECONDARY CYCLE RESOLVED (TP): {ticker} cleared debt structure.")
        elif outcome == "SL":
            # sl flipped is sec_bet + commission
            this_leg_loss = config["flip_percentage"] + config["commission"]
            total_loss_pct = bet["actual_loss_percentage"] + this_leg_loss
            # 2. 10% Absolute Risk Circuit Breaker Check
            if total_loss_pct >= config["sl_percentage"]:
                # execute secondary resolved pipeline
                secondary_bet_resolution(
                    ticker=ticker,
                    exit_price=sl,
                    outcome="SL",
                    gain=-total_loss_pct,
                    leg_gain=-this_leg_loss,
                    operation_id=operation_id,
                    capital=capital,
                )
                logger.error(f"🆘 ABSOLUTE LOSS BREACHED: Killing cycle for {ticker}. Final Outcome: SL.")
                continue

            # 3. Permitted to continue -> Flip again!
            flipped_side = "SELL" if side == "BUY" else "BUY"
            new_tp, new_sl = calculate_flip_brackets(flipped_side, sl, total_loss_pct)
            # flipped pipeline
            # the entry_date for a new record is current time, and exit_date same (later is updated)
            # for the new record, the outcome is UNRESOLVED and gain is 0, exit price is the same for entry
            # but the entry_price, is actually the last sl
            partial_operation = PartialOperation(
                operation_id=operation_id,
                entry_date=exit_date,
                side=flipped_side,
                entry_price=sl,
                tp=new_tp,
                sl=new_sl,
                exit_date=exit_date,
                exit_price=sl,
                outcome="UNRESOLVED",
                gain=0,
                bet="I"
            )
            # pipeline updated the previus partial operation as well
            update_partial_operation = UpdatePartialOperation(
                exit_date=exit_date,
                exit_price=sl,
                outcome="SL",
                gain=-this_leg_loss,
                partial_id=last_partial_id
            )
            flip_worlflow(
                ticker=ticker,
                acummulated_loss=total_loss_pct,
                actual_side=flipped_side,
                tp=new_tp,
                sl=new_sl,
                partial_operation=partial_operation,
                update_partial_operation = update_partial_operation
            )
            logger.warning(f"🔄 LEG FLIP COMPLETED: {ticker} transitioned to new leg. Total Debt: {total_loss_pct*100:.2f}%")
        else:
            remaining_secondary[ticker] = bet

    return remaining_secondary

# aux functions for direct_bet resolution

def tp_outcome_workflow(ticker: str,
                        exit_price: float,
                        gain: float, 
                        capital: float, 
                        operation_id: int
                        ):
    """
    Auxiliary function for tp direct bet result
    The workflow is this:
        1. Update completed operation.
        2. Update partial operation.
        3. Update main balance
        4. Update available balance
        5. Update ticker balance.
        6. remove ticker from direct_bet
    """
    # 1. Update completed operation, get the missing data
    exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    profit = calculate_net_profit(gain=gain, capital=capital)
    completed_record = UpdateCompletedOperation(
        outcome="DTP",
        gain=gain,
        profit=profit,
        operation_id=operation_id
    )
    update_completed_operations(update_completed_operation=completed_record)
    # 2. Update partial operation
    # retrieve last id
    partial_id = load_json_file(BET_FILE)[ticker]["last_partial_id"]
    partial_operation = UpdatePartialOperation(
        exit_date=exit_date,
        exit_price=exit_price,
        outcome="TP",
        gain=gain,
        partial_id=partial_id
    )
    update_partial_operations(update_partial_operation=partial_operation)
    # 3. update main balance
    update_main_balance(gain=gain, capital=capital)
    # 4. update available balance
    # get colateral
    colateral = load_json_file(BET_FILE)[ticker]["colateral"]
    update_available_balance(gain=gain, capital=capital, colateral=colateral)
    # 5. update ticker balance
    update_ticker_balance(ticker=ticker, gain=gain)
    # 6. remove ticket from direct bet
    data_bet = ActualBets(ticker=ticker)
    data_bet.remove_bet()

def sl_outcome_workflow(ticker: str,
                        entry_price,
                        exit_price: float, 
                        loss_percentage: float,
                        actual_side: str,
                        tp: float,
                        sl: float,
                        capital: float,
                        gain: float, 
                        operation_id: int,
                        partial_operation: PartialOperation):
    """
    If direct bet hits sl, the workflow is:
        1. Update partial_operation
        2. Add a new partial_operation
        2. Add secondary_bet
        3. remove ticker from direct_bet
    """
    logger.info(f"🔥 [DIRECT BET] ticker {ticker} hits sl in direct db, sl pipeline" 
                f" starts with operation id {operation_id}\n{'*' * 50}")
    # 1. update partial_operation
    exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    partial_id = load_json_file(BET_FILE)[ticker]['last_partial_id']
    update_partial_operation = UpdatePartialOperation(
        exit_date=exit_date,
        exit_price=exit_price,
        outcome="SL",
        gain=gain,
        partial_id=partial_id
    )
    update_partial_operations(update_partial_operation=update_partial_operation)
    # add a new partial operation, and get the last_partial_id
    last_partial_id = save_partial_operation_to_db(partial_operation=partial_operation)
    last_partial_id = 0 if not last_partial_id else last_partial_id
    # 2. Add record to secondary_bet
    colateral = calculate_colateral(capital=capital)
    entry_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # get the last partial id
    secondary_record = SecondaryBet(
        ticker=ticker,
        operation_id=operation_id,
        capital=capital,
        colateral=colateral,
        entry_price=entry_price,
        entry_date=entry_date,
        actual_loss_percentage=loss_percentage,
        cycle_start_time=entry_date,
        actual_side=actual_side,
        tp=tp,
        sl=sl,
        last_partial_id=last_partial_id
    )
    secondary_bet = SecondaryBets(secondary_bet=secondary_record)
    secondary_bet.add_secondary_bet()
    # 3. remove ticker from direct bet
    direct_bet = ActualBets(ticker=ticker)
    direct_bet.remove_bet()
    logger.info(f"🔥 pipeline executed for operation id {operation_id}\n{'*' * 50}")

# check direct bet function
def check_active_bets_resolution(current_prices_dict: List[dict]) -> None:
    """
    VErify if a direct bet get resolution, and call the function attached to the result   
    :params:
        - current_prices_dict: List[dict] list with current tickers prices
    """
    # retrieve actual bets file
    actual_bets = load_json_file(BET_FILE)
    # first, verify if actual_bets contain tickers
    if len(actual_bets) == 0:
        print(f"No bets found for {BET_FILE}")
        return None
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config = load_json_file(CONFIG_FILE)
    for ticker, bet in list(actual_bets.items()):
        # Pull current ticker price if available from stream/API
        current_price = current_prices_dict.get(ticker)
        if not current_price:
            continue
        # get the close, avoid overlaaping oppor
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
            capital = bet["capital"]
            operation_id = bet["operation_id"]
            entry_date = bet.get("entry_date", current_time_str) # avoid error
            entry_price = bet["entry_price"]
            # get the exit_price
            if outcome == "TP":
                # get data to call tp workflow func
                exit_price = tp
                gain = config["direct_bet_percentage"] - config["commission"]
                tp_outcome_workflow(ticker=ticker,
                                    exit_price=exit_price,
                                    gain=gain,
                                    capital=capital,
                                    operation_id=operation_id
                                    )
                
                logger.info(f"🍾 OPERATION RESOLVED: {ticker} hit {outcome} at {current_price}")
            else:
                # get data to call sl_workflow
                exit_price = sl
                # add the values
                acummulated_loss = config["direct_bet_percentage"] + config["commission"]
                # the side must flip
                new_side = "SELL" if side == "BUY" else "BUY"
                # sl, and tp must be calculated with flip function
                secondary_tp, secondary_sl = calculate_flip_brackets(side=new_side,
                                                 entry_price=exit_price,
                                                 total_loss_pct=acummulated_loss)
                # add partial_operation_data, the entry date is current time
                partial_operation = PartialOperation(
                    operation_id=operation_id,
                    entry_date=current_time_str,
                    side=new_side,
                    entry_price=sl,
                    tp=secondary_tp,
                    sl=secondary_sl,
                    exit_date=entry_date,
                    exit_price=entry_price,
                    outcome="UNRESOLVED",
                    gain=0,
                    bet="I"
                )
                sl_outcome_workflow(
                    ticker=ticker,
                    entry_price=sl,
                    exit_price=exit_price,
                    loss_percentage=acummulated_loss,
                    actual_side=new_side,
                    tp=secondary_tp,
                    sl=secondary_sl,
                    capital=capital,
                    gain=-acummulated_loss,
                    operation_id=operation_id,
                    partial_operation=partial_operation
                )
                logger.info(f"📢 TICKER SL: {ticker} hit {outcome} at {current_price}")
            
    
    return None

def reset_bets():
    save_json_file(BET_FILE, {})
    save_json_file(SECONDARY_BET_FILE, {})
    logger.info(f"🧹 [BET] All bets was removed")


#######################################################################
#                          LIVE BETS                                  #                
#######################################################################

# JSON files
class ActualLiveBets:
    def __init__(self):
        self.actual_bets_file = load_json_file(DIRECT_BETS_LIVE)

    def add_bet(self, data: AddBetToJSON):
        """
        Method to add a record in direct bet json file
        --------------------------------------------------
        Params:
            data(AddBetToJSON): JSON format dict with data to be added
            e.g. {
            "BTCUSDT": {
                "operation_id": 12456 
                }
            }
        """
        bets_file = self.actual_bets_file.copy()
        bets_file.update(data.as_dict())
        save_json_file(DIRECT_BETS_LIVE, bets_file)

    def remove_bet(self, ticker):
        if not ticker:
            raise DataError("Remove a ticker from actual_bets.json file, requires parameter ticker")
        bets_file = self.actual_bets_file.copy()
        bets_file.pop(ticker)
        save_json_file(DIRECT_BETS_LIVE, bets_file)
        logger.info(f"☑️ [LIVE][DIRECT BET FILE] ticker {ticker} was removed from actual bets file")

# wrokflow

def verify_live_direct_bet_result():
    """
    This function verify if any bet has been executed
    workflow:
    1. Open direct_bet_live_file
    2. Iterate searching for 
    """

def verify_live_secondary_bet_result():
    pass


def main():
    
    config = load_json_file(CONFIG_FILE)
    this_leg_loss = -config["flip_percentage"] - config["commission"]
    print(this_leg_loss)

if __name__ == '__main__':
    main()
