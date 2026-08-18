# invercrypto/strategy/common_files/binance/orders.py
"""
This module contains classes and functions to manage orders in binance futures
"""
import asyncio
import json
import math
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
import aiohttp
from database import is_ticker_in_bet
from common_files.logger import get_logger
from common_files.paths import load_json_file
from common_files.paths import LIVE_BALANCES, CONFIG_LIVE_FILE, TICKERS_BALANCES_LIVE

logger = get_logger(__name__, log_live=True)


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
    def __init__(self, symbol, client):
        self.available_balance = None
        self.config = {}
        self.tickers_balances = {}
        self.symbol = symbol
        self.client = client

        self.open_files()

    def open_files(self):
        """
        Opens the necessary files for reading/writing.
        """
        try:
            with open(LIVE_BALANCES, 'r') as f:
                self.available_balance = json.load(f).get("available_balance", 0.0)
            with open(CONFIG_LIVE_FILE, 'r') as f:
                self.config = json.load(f)
            with open(TICKERS_BALANCES_LIVE, 'r') as f:
                self.tickers_balances = json.load(f)
        except Exception as e:
            logger.error(f"Error opening files: {e}")
            raise

    async def get_notional_size(self) -> float:
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
            available_balance = self.available_balance
            size_percentage = self.config.get("size_percentage", 0.07)  # Default to 1% if not set
            leverage = self.config.get("leverage", 3)  # Default to 3x if not set
            ticker_balance = self.tickers_balances.get(self.symbol, 0.0)["actual_balance"]
            notional_size = available_balance * size_percentage * leverage * ticker_balance
            return notional_size
        except Exception as e:
            logger.error(f"Error calculating notional size for {self.symbol}: {e}")
            return 0.0

    async def get_quantity_from_notional(self) -> float:
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
            notional_size = await self.get_notional_size()
            ticker = await self.client.futures_symbol_ticker(symbol=self.symbol)
            current_price = float(ticker['price'])
            quantity = notional_size / current_price
            return quantity
        except Exception as e:
            logger.exception(f"Error calculating quantity from notional for {self.symbol}: {e}")
            return 0.0


# ====================================================#
#    Orders: Auxiliar methods for order creation      #
# ====================================================#

class SymbolRulesManager:
    """
    Manages Binance Futures symbol precision and filter rules.
    """

    def __init__(self, client):
        self.client = client
        self.rules_cache = {}

    @classmethod
    async def create(
        cls,
        client,
        retries: int = 5,
        retry_delay: float = 1.0,
    ):
        """
        Creates and initializes the SymbolRulesManager.
        Retries exchange-info retrieval when Binance temporarily
        fails to respond.
        """
        instance = cls(client)
        for attempt in range(1, retries + 1):
            try:
                if attempt > 1:
                    logger.info(
                        "Initializing SymbolRulesManager "
                        "(attempt %d/%d)...",
                        attempt,
                        retries,
                    )
                await instance.refresh_symbol_rules()
                if attempt > 1:
                    logger.info(
                        "SymbolRulesManager initialized successfully."
                    )
                return instance
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout retrieving Binance exchange info "
                    "(attempt %d/%d). Retrying in %.1f seconds...",
                    attempt,
                    retries,
                    retry_delay,
                )
            except aiohttp.ClientError:
                logger.exception(
                    "Network error retrieving Binance exchange info "
                    "(attempt %d/%d).",
                    attempt,
                    retries,
                )
            except Exception:
                logger.exception(
                    "Unexpected error initializing "
                    "SymbolRulesManager "
                    "(attempt %d/%d).",
                    attempt,
                    retries,
                )
            if attempt < retries:
                await asyncio.sleep(retry_delay)
        raise RuntimeError(
            "Unable to initialize SymbolRulesManager after "
            f"{retries} attempts."
        )

    async def refresh_symbol_rules(self):
        """
        Fetches and caches symbol precision and filter rules
        from Binance Futures.
        """
        try:
            exchange_info = await self.client.futures_exchange_info()
            for symbol_info in exchange_info["symbols"]:
                symbol = symbol_info["symbol"]
                price_filter = next(
                    f for f in symbol_info["filters"]
                    if f["filterType"] == "PRICE_FILTER"
                )
                lot_size_filter = next(
                    f for f in symbol_info["filters"]
                    if f["filterType"] == "LOT_SIZE"
                )
                min_notional_filter = next(
                    (
                        f for f in symbol_info["filters"]
                        if f["filterType"] == "MIN_NOTIONAL"
                    ),
                    None,
                )
                self.rules_cache[symbol] = {
                    "tick_size": float(price_filter["tickSize"]),
                    "step_size": float(lot_size_filter["stepSize"]),
                    "min_qty": float(lot_size_filter["minQty"]),
                    "min_notional": (
                        float(min_notional_filter["notional"])
                        if min_notional_filter
                        else 5.0
                    ),
                    "quantityPrecision": symbol_info["quantityPrecision"],
                    "pricePrecision": symbol_info["pricePrecision"],
                }

        except Exception as e:
            logger.exception(
                "Failed to fetch exchange info: %s",
                e,
            )
            raise

    def format_quantity(self, symbol: str, quantity: float) -> float:
        rules = self.rules_cache.get(symbol)

        if not rules:
            logger.error(
            "Exchange rules NOT FOUND for symbol=%s. "
            "Available cached symbols=%d",
            symbol,
            len(self.rules_cache),
            )
            raise ValueError(
                f"No exchange rules available for {symbol}"
            )

        logger.info(
            "Quantity rules: symbol=%s | "
            "input=%s | step_size=%s | min_qty=%s | "
            "quantity_precision=%s",
            symbol,
            quantity,
            rules["step_size"],
            rules["min_qty"],
            rules["quantityPrecision"],
        )

        step_size = rules["step_size"]
        precision = rules["quantityPrecision"]

        factored = math.floor(quantity / step_size) * step_size

        return round(factored, precision)

    def format_price(self, symbol: str, price: float) -> float:
        rules = self.rules_cache.get(symbol)

        if not rules:
            return price

        tick_size = rules["tick_size"]
        precision = rules["pricePrecision"]

        factored = round(price / tick_size) * tick_size

        return round(factored, precision)

    def validate_min_notional(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ) -> bool:

        rules = self.rules_cache.get(symbol)

        if not rules:
            return True

        notional_value = quantity * price

        return notional_value >= rules["min_notional"]


# ====================================================#
#      GetOrders: query all orders and positions      #
# ====================================================#

class GetOrders:
    """
    Provides access to Binance Futures orders, positions,
    and trade executions.
    """

    def __init__(self, client):
        self.client = client

    # -------------------------------------------------------------------------
    # ORDERS
    # -------------------------------------------------------------------------

    async def get_all_orders(self, symbol: str) -> list[dict]:
        """
        Retrieves all orders for a given symbol.

        Args:
            symbol: Binance Futures symbol, e.g. 'BTCUSDT'.

        Returns:
            List of Binance order dictionaries.
            Empty list if the request fails.
        """
        try:
            logger.debug(
                "Retrieving all Futures orders: symbol=%s",
                symbol,
            )

            orders = await self.client.futures_get_all_orders(
                symbol=symbol,
            )

            logger.debug(
                "Orders retrieved: symbol=%s, count=%d",
                symbol,
                len(orders),
            )

            return orders

        except Exception:
            logger.exception(
                "Failed to retrieve all Futures orders: "
                "symbol=%s",
                symbol,
            )
            return []

    async def get_order(
        self,
        symbol: str,
        order_id: int,
    ) -> dict | None:
        """
        Retrieves a specific Binance Futures order.

        Args:
            symbol: Binance Futures symbol.
            order_id: Binance order ID.

        Returns:
            Complete Binance order dictionary,
            or None if the order cannot be retrieved.
        """
        try:
            logger.debug(
                "Retrieving Futures order: "
                "symbol=%s, order_id=%s",
                symbol,
                order_id,
            )

            order = await self.client.futures_get_order(
                symbol=symbol,
                orderId=order_id,
            )

            logger.debug(
                "Futures order retrieved: "
                "symbol=%s, order_id=%s, "
                "status=%s, type=%s, side=%s, "
                "executedQty=%s, avgPrice=%s",
                symbol,
                order_id,
                order.get("status"),
                order.get("type"),
                order.get("side"),
                order.get("executedQty"),
                order.get("avgPrice"),
            )

            return order

        except Exception:
            logger.exception(
                "Failed to retrieve Futures order: "
                "symbol=%s, order_id=%s",
                symbol,
                order_id,
            )
            return None

    # -------------------------------------------------------------------------
    # POSITIONS
    # -------------------------------------------------------------------------

    async def get_all_positions(self) -> list[dict]:
        """
        Retrieves all Futures positions for the account.

        Returns:
            List of position dictionaries.
            Empty list if the request fails.
        """
        try:
            logger.debug(
                "Retrieving all Futures positions."
            )

            positions = await self.client.futures_position_information()

            logger.debug(
                "Positions retrieved: count=%d",
                len(positions),
            )

            return positions

        except Exception:
            logger.exception(
                "Failed to retrieve Futures positions."
            )
            return []

    # -------------------------------------------------------------------------
    # TRADES / EXECUTIONS
    # -------------------------------------------------------------------------

    async def get_trades(
        self,
        symbol: str,
        order_id: int,
    ) -> list[dict]:
        """
        Retrieves all Futures trade executions associated
        with a specific order.

        One Binance order can generate multiple trade
        executions/fills.

        Args:
            symbol: Binance Futures symbol.
            order_id: Binance order ID.

        Returns:
            List of Binance trade dictionaries.
            Empty list if no trades are found or the request fails.
        """
        try:
            logger.debug(
                "Retrieving Futures trades: "
                "symbol=%s, order_id=%s",
                symbol,
                order_id,
            )

            trades = await self.client.futures_account_trades(
                symbol=symbol,
                orderId=order_id,
            )

            logger.debug(
                "Trades retrieved: "
                "symbol=%s, order_id=%s, trade_count=%d",
                symbol,
                order_id,
                len(trades),
            )

            return trades

        except Exception:
            logger.exception(
                "Failed retrieving Futures trades: "
                "symbol=%s, order_id=%s",
                symbol,
                order_id,
            )
            return []

    # -------------------------------------------------------------------------
    # COMPLETE ORDER EXECUTION
    # -------------------------------------------------------------------------

    async def get_order_execution(
        self,
        symbol: str,
        order_id: int,
    ) -> dict | None:
        """
        Retrieves and combines order-level and execution-level
        information for a specific Futures order.

        The order endpoint provides information such as:
            - status
            - type
            - side
            - original quantity
            - executed quantity
            - average price

        The trade endpoint provides:
            - individual executions
            - realized PnL
            - commission
            - commission asset

        Multiple trade executions are aggregated into a single
        result.

        Args:
            symbol: Binance Futures symbol.
            order_id: Binance order ID.

        Returns:
            Combined order/execution dictionary,
            or None if the order cannot be retrieved.
        """

        order = await self.get_order(
            symbol=symbol,
            order_id=order_id,
        )

        if order is None:
            logger.error(
                "Cannot build order execution: "
                "order not found. symbol=%s, order_id=%s",
                symbol,
                order_id,
            )
            return None

        trades = await self.get_trades(
            symbol=symbol,
            order_id=order_id,
        )

        # ---------------------------------------------------------------------
        # No executions yet
        # ---------------------------------------------------------------------

        if not trades:
            logger.warning(
                "Order has no trade executions: "
                "symbol=%s, order_id=%s, status=%s",
                symbol,
                order_id,
                order.get("status"),
            )

            return {
                **order,
                "trade_count": 0,
                "executed_qty": Decimal("0"),
                "average_trade_price": Decimal("0"),
                "realized_pnl": Decimal("0"),
                "commission": Decimal("0"),
                "commission_asset": None,
                "trades": [],
            }

        # ---------------------------------------------------------------------
        # Aggregate executions
        # ---------------------------------------------------------------------

        executed_qty = sum(
            (
                Decimal(trade["qty"])
                for trade in trades
            ),
            Decimal("0"),
        )

        realized_pnl = sum(
            (
                Decimal(trade["realizedPnl"])
                for trade in trades
            ),
            Decimal("0"),
        )

        commission = sum(
            (
                Decimal(trade["commission"])
                for trade in trades
            ),
            Decimal("0"),
        )

        # Binance should normally use the same commission asset
        # for all executions of the order.
        commission_assets = {
            trade.get("commissionAsset")
            for trade in trades
        }

        if len(commission_assets) == 1:
            commission_asset = commission_assets.pop()
        else:
            logger.warning(
                "Multiple commission assets found: "
                "symbol=%s, order_id=%s, assets=%s",
                symbol,
                order_id,
                commission_assets,
            )
            commission_asset = None

        # ---------------------------------------------------------------------
        # Weighted average execution price
        # ---------------------------------------------------------------------

        total_quote = sum(
            (
                Decimal(trade["price"])
                * Decimal(trade["qty"])
                for trade in trades
            ),
            Decimal("0"),
        )

        average_trade_price = (
            total_quote / executed_qty
            if executed_qty > 0
            else Decimal("0")
        )

        logger.debug(
            "Order execution aggregated: "
            "symbol=%s, order_id=%s, "
            "trades=%d, qty=%s, avg_price=%s, "
            "realized_pnl=%s, commission=%s",
            symbol,
            order_id,
            len(trades),
            executed_qty,
            average_trade_price,
            realized_pnl,
            commission,
        )

        return {
            **order,

            # Execution information
            "trade_count": len(trades),
            "executed_qty": executed_qty,
            "average_trade_price": average_trade_price,

            # Financial information
            "realized_pnl": realized_pnl,
            "commission": commission,
            "commission_asset": commission_asset,

            # Raw executions
            "trades": trades,
        }

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

    async def execute_bracket_market_trade(self, symbol: str, side: str, quantity: float, 
                                     stop_loss_price: float, take_profit_price: float,
                                     client) -> Dict[Any, Any]:
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
        # ------ defensive line, if there's a live operation, execution must be aborted ------- #
        try:
            open_orders = await client.futures_get_open_orders(
                symbol=symbol
            )

            if open_orders:
                logger.warning(
                    "⚠️ [ORDER DEFENSE] Open orders detected for %s. "
                    "count=%d",
                    symbol,
                    len(open_orders),
                )

                for order in open_orders:
                    logger.warning(
                        "⚠️ [OPEN ORDER] symbol=%s | "
                        "order_id=%s | type=%s | side=%s | status=%s",
                        symbol,
                        order.get("orderId"),
                        order.get("type"),
                        order.get("side"),
                        order.get("status"),
                    )

                raise RuntimeError(
                    f"Open Binance Futures orders already exist "
                    f"for {symbol}."
                )

            logger.debug(
                "✅ [ORDER DEFENSE] No open orders found for %s.",
                symbol,
            )

        except RuntimeError:
            raise

        except Exception:
            logger.exception(
                "❌ [ORDER DEFENSE] Failed to verify open orders "
                "for symbol=%s",
                symbol,
            )
            raise

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
            market_order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=formatted_qty
            )
            # create dict with orderId, side, price, quantity and timestamp
            update_time = market_order.get("updateTime")
            timestamp = datetime.fromtimestamp(update_time / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
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
            sl_order = await self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type='STOP_MARKET',
                stopPrice=formatted_sl,
                closePosition=True
            )
            
            market_order_data['sl'] = float(sl_order.get('triggerPrice', 0))
            market_order_data['sl_algo_id'] = sl_order.get('algoId', 0)
            logger.info(f"Stop Loss set at {formatted_sl}")
            timestamp = None

            # 4. Place Take Profit Bracket
            
            tp_order = await self.client.futures_create_order(
                symbol=symbol,
                side=exit_side,
                type='TAKE_PROFIT_MARKET',
                stopPrice=formatted_tp,
                closePosition=True
            )

            market_order_data['tp'] = float(tp_order.get('triggerPrice', 0))
            market_order_data['tp_algo_id'] = tp_order.get('algoId', 0)

            logger.info(f"Take Profit set at {formatted_tp}")

        except Exception as e:
            # EMERGENCY ROLLBACK: If SL or TP placement fails, immediately liquidate position!
            logger.critical(f"[{symbol}] Failed to place SL/TP brackets after entry! Executing emergency exit. Error: {e}")
            await self.client.futures_create_order(
                symbol=symbol, side=exit_side, type='MARKET', quantity=quantity, reduceOnly=True
            )
            await self.client.futures_cancel_all_open_orders(symbol=symbol)
            return {"status": "FAILED: ROLLBACK", "error": str(e)}
        return {"status": "SUCCESS", "data": market_order_data}

    async def cancel_all_symbol_orders(self, symbol: str):
        """
        Cleans up lingering open SL/TP orders when position closes.
        """
        try:
            res = await self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Cancelled all open orders for {symbol}")
            return res
        except Exception as e:
            logger.error(f"Failed to cancel open orders for {symbol}: {e}")
            return None


# ====================================================#
#             functions for execution                 #
# ====================================================#


async def synchronize_orders(
    client,
    symbol: str,
    order_id: int,
    poll_interval: float = 0.5,
    max_wait_time: float = 30.0
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
            order = await client.futures_get_order(
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

async def bet_execute(client, 
                    rules_mgr,
                    symbol: str, 
                    side: str,
                    bet_mode: str = "direct",
                    adjust:float = 0) -> dict:
    """
    Executes a direct bet (market order with SL and TP) for a given symbol and side.
    :param symbol: The trading pair symbol (e.g., 'BTCUSDT').
    :param side: 'BUY' or 'SELL'.
    """

    order_mgr = CreateOrderManager(client, rules_mgr)

    # Load configuration
    config = load_json_file(CONFIG_LIVE_FILE)
    if bet_mode == "direct":
        pct_offset = config.get("direct_bet_percentage", 0.005)
    else:
        pct_offset = config.get("flip_percentage", 0.005)

    # quantity depends if there's actual bet or not
    active_ticker_bet, quantity =  await is_ticker_in_bet(ticker=symbol)
    if quantity == 0 and active_ticker_bet:
        logger.exception("⚠️ [QUANTITY] an error ocurred retrieving the quantity, "
                         "values: active ticker, %b, quantity: %d", active_ticker_bet, quantity)
        raise

    if active_ticker_bet:
        raw_quantity = quantity
    else:
        # Get notional size and quantity
        notional_size_mgr = NotonialSize(symbol=symbol, client=client)
        raw_quantity = await notional_size_mgr.get_quantity_from_notional()
    logger.debug(
        "Ticker request: symbol=%s | "
        "task=%s | loop=%s | client=%s",
        symbol,
        asyncio.current_task(),
        asyncio.get_running_loop(),
        id(client),
                )
    # Fetch current price to compute SL & TP targets dynamically
    ticker = await client.futures_symbol_ticker(symbol=symbol)
    current_price = float(ticker['price'])
    logger.info(f"Current Market Price for {symbol}: {current_price}")

    # Calculate SL and TP based on the side of the trade
    if side.upper() == "BUY":
        tp_price = current_price * (1.0 + pct_offset + adjust) # only tp could be adjusted
        sl_price = current_price * (1.0 - pct_offset)
    elif side.upper() == "SELL":
        tp_price = current_price * (1.0 - pct_offset - adjust)
        sl_price = current_price * (1.0 + pct_offset)
    else:
        logger.error(f"Invalid side '{side}' provided. Must be 'BUY' or 'SELL'.")
        return {"status": "FAILED", "error": "Invalid side provided."}

    logger.info(f"Calculated Targets -> TP: {tp_price:.7f} | SL: {sl_price:.7f}")

    # Execute the bracket market trade
    result = await order_mgr.execute_bracket_market_trade(
        symbol=symbol,
        side=side,
        quantity=raw_quantity,
        stop_loss_price=sl_price,
        take_profit_price=tp_price,
        client=client
    )

    if result.get("status") == "SUCCESS":
        logger.info("🎯 Direct Bet Test PASSED cleanly!")
    else:
        logger.error(f"❌ Direct Bet Test Failed: {result.get('error')}")
        return {"status": "FAILED", "error": result.get("error")}

    return result

def main():
    print("invercrypto/strategy/common_files/binance_utils/orders.py module")

if __name__ == "__main__":
    main()