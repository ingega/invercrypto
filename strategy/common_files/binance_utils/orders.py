# invercrypto/strategy/common_files/binance/orders.py
"""
This module contains classes and functions to manage orders in binance futures
"""
import json
import os
import math
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, List
from binance.client import Client
from typing import List
from common_files.logger import get_logger
from common_files.paths import load_json_file
from common_files.paths import MAIN_BALANCE_LIVE, CONFIG_LIVE_FILE, SECONDARY_BETS_LIVE, TICKERS_BALANCES_LIVE

logger = get_logger(__name__, log_live=True)

client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)



# ====================================================#
#  Notional: Auxiliar methods for orders creation     #
# ====================================================#

class NotonialSize:
    """
    This class manages the notional size and configuration for trading on Binance Futures.
    by gathering the necessary configuration and balance files.
    Methods:
        - _init_: Initializes the NotonialSize class and opens necessary files.
        - open_files: Opens the necessary files for reading/writing.
    """
    def __init__(self, symbol):
        self.main_balance = None
        self.config = {}
        self.secondary_bets = {}
        self.tickers_balances = {}
        self.symbol = symbol

        self.open_files()

    def open_files(self):
        """
        Opens the necessary files for reading/writing.
        """
        try:
            with open(MAIN_BALANCE_LIVE, 'r') as f:
                self.main_balance = json.load(f).get("main_balance", 0.0)
            with open(CONFIG_LIVE_FILE, 'r') as f:
                self.config = json.load(f)
            with open(SECONDARY_BETS_LIVE, 'r') as f:
                self.secondary_bets = json.load(f)
            with open(TICKERS_BALANCES_LIVE, 'r') as f:
                self.tickers_balances = json.load(f)
        except Exception as e:
            logger.error(f"Error opening files: {e}")
            raise

    def get_notional_size(self) -> float:
        """
        Calculates the notional size for a given symbol based on the main balance and configuration.
        1. Retrieves the main balance from the main_balance.json file.
        2. Retrieves the size percentage from the config.json file.
        3. Get the leverage from the config.json file.
        4. Get the ticker balance from the tickers_balances.json file.
        5. Calculates the notional size using the formula:
        notional_size = main_balance * size_percentage * leverage * ticker_balance
        6. Returns the calculated notional size.
        :param symbol: The trading pair symbol (e.g., 'BTCUSDT').
        :return: The calculated notional size.
        """
        try:
            main_balance = self.main_balance
            size_percentage = self.config.get("size_percentage", 0.07)  # Default to 1% if not set
            leverage = self.config.get("leverage", 3)  # Default to 3x if not set
            ticker_balance = self.tickers_balances.get(self.symbol, 0.0)["actual_balance"]
            print(f"Calculating notional size for {self.symbol}: main_balance={main_balance}, "
                  f"size_percentage={size_percentage}, leverage={leverage}, ticker_balance={ticker_balance}")
            notional_size = main_balance * size_percentage * leverage * ticker_balance
            return notional_size
        except Exception as e:
            logger.error(f"Error calculating notional size for {self.symbol}: {e}")
            return 0.0

    def get_quantity_from_notional(self) -> float:
        """
        Calculates the quantity to trade based on the notional size and current price of the symbol.
        1. Fetches the current price of the symbol from Binance Futures.
        2. Calculates the quantity using the formula:
        quantity = notional_size / current_price
        3. Returns the calculated quantity.
        :param symbol: The trading pair symbol (e.g., 'BTCUSDT').
        :param notional_size: The notional size for the trade.
        :return: The calculated quantity to trade.
        """
        try:
            # get notional size
            notional_size = self.get_notional_size()
            ticker = client.futures_symbol_ticker(symbol=self.symbol)
            current_price = float(ticker['price'])
            quantity = notional_size / current_price
            return quantity
        except Exception as e:
            logger.error(f"Error calculating quantity from notional for {self.symbol}: {e}")
            return 0.0


# ====================================================#
#    Orders: Auxiliar methods for order creation      #
# ====================================================#

class SymbolRulesManager:
    """
    This class manages the precision and filter rules for symbols on Binance Futures. 
    It fetches the rules from the exchange and caches them for efficient access during 
    order creation and validation.
    Methods:
        - refresh_symbol_rules: Fetches and caches symbol precision and filter rules from Binance Futures.
        - format_quantity: Truncates quantity according to symbol stepSize.
        - format_price: Rounds price according to symbol tickSize.
        - validate_min_notional: Verifies if trade value exceeds Binance minimum notional value (e.g. $5 or $10 USDT).
    Parameters:
        - client: An instance of the Binance Client.
    """
    def __init__(self, client):
        self.client = client
        self.rules_cache = {}
        self.refresh_symbol_rules()

    def refresh_symbol_rules(self):
        """
        Fetches and caches symbol precision and filter rules from Binance Futures.
        """
        try:
            exchange_info = self.client.futures_exchange_info()
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol']
                
                # Extract filters
                price_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER')
                lot_size_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE')
                min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)

                self.rules_cache[symbol] = {
                    'tick_size': float(price_filter['tickSize']),
                    'step_size': float(lot_size_filter['stepSize']),
                    'min_qty': float(lot_size_filter['minQty']),
                    'min_notional': float(min_notional_filter['notional']) if min_notional_filter else 5.0,
                    'quantityPrecision': symbol_info['quantityPrecision'],
                    'pricePrecision': symbol_info['pricePrecision']
                }
            logger.info("Successfully cached exchange rules for all symbols.")
        except Exception as e:
            logger.error(f"Failed to fetch exchange info: {e}")

    def format_quantity(self, symbol: str, quantity: float) -> float:
        """
        Truncates quantity according to symbol stepSize.
        """
        rules = self.rules_cache.get(symbol)
        if not rules:
            return quantity
        
        step_size = rules['step_size']
        precision = rules['quantityPrecision']
        
        # Round down to avoid exceeding available margin/balance
        factored = math.floor(quantity / step_size) * step_size
        return round(factored, precision)

    def format_price(self, symbol: str, price: float) -> float:
        """
        Rounds price according to symbol tickSize.
        """
        rules = self.rules_cache.get(symbol)
        if not rules:
            return price
        
        tick_size = rules['tick_size']
        precision = rules['pricePrecision']
        
        factored = round(price / tick_size) * tick_size
        return round(factored, precision)

    def validate_min_notional(self, symbol: str, quantity: float, price: float) -> bool:
        """
        Verifies if trade value exceeds Binance minimum notional value (e.g. $5 or $10 USDT).
        """
        rules = self.rules_cache.get(symbol)
        if not rules:
            return True
        notional_value = quantity * price
        return notional_value >= rules['min_notional']


# ====================================================#
#      GetOrders: query all orders and positions      #
# ====================================================#
class GetOrders:
    def __init__(self, client):
        self.client = client

    def get_all_orders(self, symbol):
        """
        Get all orders for a given symbol.
        :param symbol: The trading pair symbol (e.g., 'BTCUSDT').
        :return: A list of all orders for the specified symbol.
        """
        try:
            orders = self.client.futures_get_all_orders(symbol=symbol)
            return orders
        except Exception as e:
            logger.error(f"Error fetching orders for {symbol}: {e}")
            return []

    def get_all_positions(self):
        """
        Get all positions for the account.
        :return: A list of all positions.
        """
        try:
            positions = self.client.futures_account_trades(limit=10)  # Adjust limit as needed
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

# ====================================================#
#              Orders: creates orders                 #
# ====================================================#

class CreateOrderManager:
    """
    This class manages the creation of bracket orders (Market Entry + SL + TP) on Binance Futures.
    Methods:
        - execute_bracket_market_trade: Executes a Market Entry Order and places corresponding SL and TP brackets.
        - cancel_all_symbol_orders: Cleans up lingering open SL/TP orders when position closes.
    Parameters:
        - client: An instance of the Binance Client.
        - rules_manager: An instance of the SymbolRulesManager.
    """
    def __init__(self, client, rules_manager: SymbolRulesManager):
        self.client = client
        self.rules_manager = rules_manager

    def execute_bracket_market_trade(self, symbol: str, side: str, quantity: float, 
                                     stop_loss_price: float, take_profit_price: float) -> Dict[Any, Any]:
        """
        Executes a Market Entry Order and places corresponding SL and TP brackets on Binance Futures.
        If SL or TP placement fails, it performs an emergency rollback by liquidating the position and 
        canceling all open orders.
        
        :param symbol: e.g. 'BTCUSDT'
        :param side: 'BUY' (for Long) or 'SELL' (for Short)
        :param quantity: Raw calculated quantity
        :param stop_loss_price: Trigger price for Stop Loss
        :param take_profit_price: Trigger price for Take Profit
        """
        # 1. Format inputs against exchange rules
        formatted_qty = self.rules_manager.format_quantity(symbol, quantity)
        formatted_sl = self.rules_manager.format_price(symbol, stop_loss_price)
        formatted_tp = self.rules_manager.format_price(symbol, take_profit_price)
        
        # Determine opposite side for exit orders
        exit_side = 'SELL' if side == 'BUY' else 'BUY'
        output = {}

        try:
            # 2. Execute Primary Direct Market Order
            logger.info(f"Submitting {side} Market Order for {symbol} | Qty: {formatted_qty}")
            market_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=formatted_qty
            )
            # create dict with orderId, side, price, quantity and timestamp
            update_time = market_order.get("updateTime")
            timestamp = datetime.fromtimestamp(update_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
            update_time = None # avoids overwriting values for sl and tp orders

            market_order_data = {
                "orderId": market_order.get('orderId'),
                "side": market_order.get("side"),
                "price": market_order.get('avgPrice'),
                "quantity": market_order.get('executedQty'),
                "timestamp": timestamp
            }
            logger.info(f"Market order filled: OrderId {market_order.get('orderId')}")
            timestamp = None
        except Exception as e:
                    logger.error(f"Failed to execute market order trade for {symbol}: {e}")
                    return {"status": "FAILED", "error": str(e)}
        
        try:
            # 3. Place Stop Loss Bracket
            sl_order = self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type='STOP_MARKET',
                stopPrice=formatted_sl,
                closePosition=True
            )
            
            market_order_data['sl'] = float(sl_order.get('triggerPrice', 0))
            logger.info(f"Stop Loss set at {formatted_sl}")
            timestamp = None

            # 4. Place Take Profit Bracket
            
            tp_order = self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type='TAKE_PROFIT_MARKET',
                stopPrice=formatted_tp,
                closePosition=True
            )

            market_order_data['tp'] = float(tp_order.get('triggerPrice', 0))
            logger.info(f"Take Profit set at {formatted_tp}")

        except Exception as e:
            # EMERGENCY ROLLBACK: If SL or TP placement fails, immediately liquidate position!
            logger.critical(f"[{symbol}] Failed to place SL/TP brackets after entry! Executing emergency exit. Error: {e}")
            self.client.futures_create_order(
                symbol=symbol, side=exit_side, type='MARKET', quantity=quantity, reduceOnly=True
            )
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            return {"status": "FAILED: ROLLBACK", "error": str(e)}
        return {"status": "SUCCESS", "data": market_order_data}

        

    def cancel_all_symbol_orders(self, symbol: str):
        """
        Cleans up lingering open SL/TP orders when position closes.
        """
        try:
            res = self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Cancelled all open orders for {symbol}")
            return res
        except Exception as e:
            logger.error(f"Failed to cancel open orders for {symbol}: {e}")
            return None


# ====================================================#
#             functions for execution                 #
# ====================================================#


def synchronize_orders(
    symbol: str,
    order_id: int,
    poll_interval: float = 0.5,
    max_wait_time: float = 30.0,
) -> Dict[Any, Any]:
    """
    Synchronizes order information with Binance.

    This function polls Binance until every order reaches a terminal state
    (FILLED, CANCELED, EXPIRED or REJECTED), or until the timeout expires.

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. 'BTCUSDT').

    order_id : int
        order id assigned for Binance API.

    poll_interval : float
        Seconds between polling cycles.

    max_wait_time : float
        Maximum number of seconds to wait.

    Returns
    -------
    Dict[int, dict]
        Dictionary keyed by orderId containing the retrieved information.
    """

    output: Dict[str, Any] = {}

    logger.info(
        f"Retrieved information for orderId {order_id} order from Binance..."
    )

    start_time = time.monotonic()
    output = {}

    while (time.monotonic() - start_time) < max_wait_time:

        try:
            order = client.futures_get_order(
                symbol=symbol,
                orderId=order_id
                )

            if order["status"] == "FILLED":
                output = {
                        "price": float(order.get("avgPrice")),
                        "quantity": float(order.get("executedQty"))
                        }
                logger.info(f"✓ Order {order_id} synchronized ")
                return output
            else:
                logger.info(f"Waiting for order {order_id} ...")
                time.sleep(poll_interval)

        except Exception as e:
            logger.error(f"Error retrieving order {order_id}: {e}")

    # Timeout
    logger.warning(f"Timeout reached after {max_wait_time:.1f}s.")

    return output

def direct_bet_execute(symbol: str, side: str) -> dict:
    """
    Executes a direct bet (market order with SL and TP) for a given symbol and side.
    :param symbol: The trading pair symbol (e.g., 'BTCUSDT').
    :param side: 'BUY' or 'SELL'.
    """
    # Initialize Rule Manager and Order Manager
    rules_mgr = SymbolRulesManager(client)
    order_mgr = CreateOrderManager(client, rules_mgr)

    # Load configuration
    config = load_json_file(CONFIG_LIVE_FILE)
    pct_offset = config.get("direct_bet_percentage", 0.005)

    # Get notional size and quantity
    notional_size_mgr = NotonialSize(symbol)
    raw_quantity = notional_size_mgr.get_quantity_from_notional()

    # Fetch current price to compute SL & TP targets dynamically
    ticker = client.futures_symbol_ticker(symbol=symbol)
    current_price = float(ticker['price'])
    logger.info(f"Current Market Price for {symbol}: {current_price}")

    # Calculate SL and TP based on the side of the trade
    if side.upper() == "BUY":
        tp_price = current_price * (1.0 + pct_offset)
        sl_price = current_price * (1.0 - pct_offset)
    elif side.upper() == "SELL":
        tp_price = current_price * (1.0 - pct_offset)
        sl_price = current_price * (1.0 + pct_offset)
    else:
        logger.error(f"Invalid side '{side}' provided. Must be 'BUY' or 'SELL'.")
        return {"status": "FAILED", "error": "Invalid side provided."}

    logger.info(f"Calculated Targets -> TP: {tp_price:.7f} | SL: {sl_price:.7f}")

    # Execute the bracket market trade
    result = order_mgr.execute_bracket_market_trade(
        symbol=symbol,
        side=side,
        quantity=raw_quantity,
        stop_loss_price=sl_price,
        take_profit_price=tp_price
    )

    if result.get("status") == "SUCCESS":
        logger.info("🎯 Direct Bet Test PASSED cleanly!")
    else:
        logger.error(f"❌ Direct Bet Test Failed: {result.get('error')}")
        return {"status": "FAILED", "error": result.get("error")}

    return result

def main():
    symbol = "1000PEPEUSDT"
    side = "SELL"
    result = direct_bet_execute(symbol, side)
    data = result['data']
    if result.get("status") == "SUCCESS":
        order_id = data.get("orderId", {})
        # after sending the order, check if it was filled and log the result
        synchronized_orders = synchronize_orders(symbol, order_id)
        # finally update orders
        if len(synchronized_orders) > 0:
            data.update(synchronized_orders)
    logger.info(f"Pipeline executed, final values are: {data}")

if __name__ == "__main__":
    main()