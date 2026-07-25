# invercrypto/strategy/common_files/bets.py
# importation in alpha sorted
from datetime import datetime, timedelta
from typing import List, Tuple
# logger
from common_files.logger import get_logger
# json and config files
from common_files.paths import *
# database operations
from data_classes import CompletedOperation, PartialOperation, UpdateOperation
from database import save_operation_to_db, save_partial_operation_to_db, update_operations
# balance operations
from common_files.balances import calculate_net_profit, update_available_balance 
from common_files.balances import update_main_balance, update_ticker_balance
"""
This module contains the direct and secondary bets and neccsesary function for the execution
"""

logger = get_logger(__name__)

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

def calculate_profit(side: str, entry_price: float, close_price: float):
    if side == "BUY":
        return (close_price - entry_price) / entry_price
    elif side == "SELL":
        return (entry_price - close_price) / entry_price
    return

# secondary bet function
def resolve_secondary_bets(secondary_bets: dict, current_prices: dict) -> dict:
    """
    Checks active secondary flip paths at 1-minute intervals.
    Handles the 10% structural circuit breaker and 24-hour TIE expiration constraints.
    """
    remaining_secondary = {}
    current_time = datetime.now()
    current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
    config = load_json_file(CONFIG_FILE)

    for ticker, bet in secondary_bets.items():
        price_data = current_prices.get(ticker)
        if not price_data:
            remaining_secondary[ticker] = bet
            continue
        # retrieve data
        entry_date = bet["entry_date"]
        exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        actual_side = bet["actual_side"]
        entry_price = bet["entry_price"]
        exit_price = price_data[ticker]["close"]
        tp = bet["tp"]
        sl = bet["sl"]
        operation_id = bet["operation_id"]
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
            gain = bet["actual_loss_percentage"] - leg_profit
            # save record to partial operations as well
            record = PartialOperation(
                operation_id=operation_id,
                entry_date=entry_date,
                side=actual_side,
                entry_price=entry_price,
                tp=tp,
                sl=sl,
                exit_price=exit_price,
                exit_date=exit_date,
                outcome="TIE",
                gain=gain,
                bet="I"
            )
            save_partial_operation_to_db(record)
            # update main record
            tie_profit = calculate_net_profit(gain=gain, capital=capital)
            tie_record = UpdateOperation(
                outcome="TIE",
                gain=gain,
                profit=tie_profit,
                operation_id=operation_id
            )
            update_operations(update_operation=tie_record)
            # update ticker balance
            update_ticker_balance(ticker=ticker, gain=gain)
            # update main and available balances
            update_main_balance(gain=gain, capital=capital)
            colateral_returned = bet["colateral"] + tie_profit
            update_available_balance(capital=colateral_returned)
            logger.warning(f"⏱️ 24-HOUR TIE CONSTRAINT BREACHED: Liquidating cycle for {ticker}.")
            continue
        high, low = price_data[ticker]["close"], price_data[ticker]["close"]
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
            gain = config["profit_percentage"] - config["commision"] # gain
            # add record to the partial operation
            record = PartialOperation(
                            operation_id=operation_id,
                            entry_date=entry_date,
                            side=actual_side,
                            entry_price=entry_price,
                            tp=tp,
                            sl=sl,
                            exit_price=exit_price,
                            exit_date=exit_date,
                            outcome="TP",
                            gain=gain,
                            bet="I"
                        )
            save_partial_operation_to_db(record)
            # also we need to update the profit, outcome and gain for the operation_id
            # calculate profit
            tp_profit = calculate_net_profit(gain=gain, capital=capital)
            update_record = UpdateOperation(
                outcome="ITP",
                gain=gain,
                profit=tp_profit,
                operation_id=operation_id
            )
            update_operations(update_operation=update_record)
            # update ticker balance
            update_ticker_balance(ticker=ticker, gain=gain)
            # update main balance and available balance
            update_main_balance(gain=gain, capital=capital)
            colateral_returned = bet["colateral"] + tp_profit
            update_available_balance(capital=colateral_returned)
            logger.info(f"🏆 SECONDARY CYCLE RESOLVED (TP): {ticker} cleared debt structure.")
        elif outcome == "SL":
            # Add relative distance of this leg's failure to our global debt metric
            this_leg_loss = abs(bet["entry_price"] - sl) / bet["entry_price"]
            total_loss_pct = bet["actual_loss_percentage"] + this_leg_loss
            # 2. 10% Absolute Risk Circuit Breaker Check
            if total_loss_pct >= config["sl_percentage"]:
                gain = -total_loss_pct
                sl_profit = calculate_net_profit(gain=gain, capital=capital)
                # add record to the partial operation
                sl_record = PartialOperation(
                                operation_id=operation_id,
                                entry_date=entry_date,
                                side=actual_side,
                                entry_price=entry_price,
                                tp=tp,
                                sl=sl,
                                exit_price=exit_price,
                                exit_date=exit_date,
                                outcome="SL",
                                gain=gain,
                                bet="I"
                            )
                save_partial_operation_to_db(partial_operation=sl_record)
                # update the gain and profit of the main record
                update_sl_record = UpdateOperation(
                    outcome="SL",
                    gain=gain,
                    profit=sl_profit,
                    operation_id=operation_id
                )
                update_operations(update_operation=update_sl_record)
                # finally update tickers_balances
                update_ticker_balance(ticker=ticker, gain=gain)
                # update main and available balance
                update_main_balance(gain=gain, capital=capital)
                # returned balance is colateral + profit
                colateral_returned = bet["colateral"] + sl_profit
                update_available_balance(capital=colateral_returned)
                logger.error(f"🆘 ABSOLUTE LOSS BREACHED: Killing cycle for {ticker}. Final Outcome: SL.")
                continue

            # 3. Permitted to continue -> Flip again!
            flipped_side = "SELL" if side == "BUY" else "BUY"
            new_tp, new_sl = calculate_flip_brackets(flipped_side, sl, total_loss_pct)

            remaining_secondary[ticker] = {
                "capital": bet["capital"],
                "colateral": bet["colateral"],
                "entry_price": sl,
                "tangent": bet["tangent"],
                "actual_loss_percentage": total_loss_pct,
                "cycle_start_time": bet["cycle_start_time"],  # Persist anchor clock
                "actual_side": flipped_side,
                "tp": new_tp,
                "sl": new_sl
            }
            # add the record at partial_operations
            # entry_date is actually the exit_date of the preview record
            new_entry_date = bet["exit_date"]
            new_exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sl_record = PartialOperation(
                                            operation_id=operation_id,
                                            entry_date=new_entry_date,
                                            side=flipped_side,
                                            entry_price=sl,
                                            tp=new_tp,
                                            sl=new_sl,
                                            exit_price=exit_price,
                                            exit_date=new_exit_date,
                                            outcome="SL",
                                            gain=this_leg_loss,
                                            bet="I"
                                        )
            save_partial_operation_to_db(partial_operation=sl_record)
            logger.warning(f"🔄 LEG FLIP COMPLETED: {ticker} transitioned to new leg. Total Debt: {total_loss_pct*100:.2f}%")
        else:
            remaining_secondary[ticker] = bet

    return remaining_secondary

# check direct bet function
def check_active_bets_resolution(current_prices_dict: List[dict]):
    """
    Verifies open bets against current high/low/close data.
    For demonstration, we check against the current spot/mark price.
    In full integration, replace this with intra-hour 1m high/low data fetch.
    A function to retrieve data from binance is required
    :params:
        - current_prices_dict: List[dict] list with current tickers prices
    """
    # retrieve actual bets file
    actual_bets = load_json_file(BET_FILE)
    # first, verify if actual_bets contain tickers
    if len(actual_bets) == 0:
        logger.info(f"No bets found for {BET_FILE}")
        return None
    resolved_tickers = []
    init_csv_log()
    
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config = load_json_file(CONFIG_FILE)
    final_secondary_bet_compose = {}
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
            colateral = bet["colateral"]
            operation_id = bet["operation_id"]
            exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry_date = bet.get("entry_date", current_time_str) # avoid error
            entry_price = bet["entry_price"]
            # get the exit_price
            if outcome == "TP":
                exit_price = tp
                # add to the database
                gain = config["direct_bet_percentage"] - config["commission"]
                profit = calculate_net_profit(gain=gain, capital=capital) 
                tp_record = CompletedOperation(
                    operation_id=operation_id,
                    strategy="tangent",
                    ticker=ticker,
                    outcome="DTP",
                    gain=gain,
                    capital=capital,
                    profit=profit
                )
                save_operation_to_db(tp_record)
                # save record to partial operations as well
                record_partial = (
                    operation_id, entry_date, side, entry_price, tp, sl, 
                    exit_date, exit_price, "DTP", gain, "D"
                                )
                record_partial = PartialOperation(
                    operation_id=operation_id,
                    entry_date=entry_date,
                    side=side,
                    entry_price=exit_price,
                    tp=tp,
                    sl=sl,
                    exit_date=exit_date,
                    exit_price=exit_price,
                    outcome="TP",
                    gain=gain,
                    bet="D"
                )
                save_partial_operation_to_db(record_partial)
                # append the ticker that need to be removed in master bet json
                resolved_tickers.append(ticker)
                # update the ticker balance
                update_ticker_balance(ticker=ticker, gain=gain)
                # also update the main and available balance
                update_main_balance(gain=gain, capital=capital)
                # the net balance for available_balance is the colateral + profit
                colateral_returned = bet["colateral"] + profit
                update_available_balance(capital=colateral_returned)
                logger.info(f"🍾 OPERATION RESOLVED: {ticker} hit {outcome} at {current_price}")
            else:
                logger.info(f"📢 TICKER SL: {ticker} hit {outcome} at {current_price}")
                # secondary bet protection
                exit_price = sl
                # add the values
                acummulated_loss = config["direct_bet_percentage"] + config["commission"]
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # the side must flip
                new_side = "SELL" if side == "BUY" else "SELL"
                # sl, and tp must be calculated with flip function
                tp, sl = calculate_flip_brackets(side=new_side,
                                                 entry_price=exit_price,
                                                 total_loss_pct=acummulated_loss)
                # add operation to db
                record_complete = CompletedOperation(
                    operation_id=operation_id,
                    strategy="tangent",
                    ticker=ticker,
                    outcome="PENDING", # will be updated after the conclusion
                    gain=0, # will be updated after the conclusion
                    capital=capital,
                    profit=0 # will be updated after the conclusion
                )
                save_operation_to_db(operation=record_complete)
                # add sl record to partial operations
                record_partial = PartialOperation(
                    operation_id=operation_id,
                    entry_date=entry_date,
                    side=side,
                    entry_price=entry_price,
                    tp=tp,
                    sl=sl,
                    exit_price=exit_price,
                    exit_date=current_time,
                    outcome="SL",
                    gain=-acummulated_loss,
                    bet="D"
                )
                new_exit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                record_partial = PartialOperation(
                    operation_id=operation_id,
                    entry_date=entry_date,
                    side=new_side,
                    entry_price=entry_price,
                    tp=tp,
                    sl=sl,
                    exit_date=new_exit_date,
                    exit_price=exit_price,
                    outcome="SL",
                    gain=acummulated_loss,
                    bet="D"
                )
                record = {
                    ticker: {
                        "operation_id": operation_id,
                        "capital": capital,
                        "colateral": colateral,
                        "entry_price": exit_price,
                        "entry_date": entry_date,
                        "tangent": 0, # this is the flag to indicate secondary bet
                        "actual_loss_percentage": acummulated_loss,
                        "cycle_start_time": current_time,
                        "actual_side": new_side,
                        "tp": tp,
                        "sl": sl
                    }
                }
                # added to the final_secondary list
                final_secondary_bet_compose.update(record)
                # remove it from direct bet, by adding to resolved_tickers
                resolved_tickers.append(ticker)
            
    # Purge completed positions from the dictionary
    actual_bet_file = load_json_file(BET_FILE)
    for ticker in resolved_tickers:
        # remove it from actual_bets.json file
        del actual_bet_file[ticker]
    # update bet json file
    save_json_file(BET_FILE, actual_bet_file)
    # update secondary bet json file
    new_secondary_bet_file = {}
    if final_secondary_bet_compose:
        new_secondary_bet_file = load_json_file(SECONDARY_BET_FILE)
        for bet in final_secondary_bet_compose.items():
            payload = {bet[0]: bet[1]}
            new_secondary_bet_file.update(payload)
        # final movement, save the updated bet file
        save_json_file(SECONDARY_BET_FILE, new_secondary_bet_file)
    return actual_bet_file
