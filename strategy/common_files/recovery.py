# invercrypto/strategy/common_files/live/recovery.py

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from database import query_unresolved_operations, query_bet_mode, query_capital, update_completed_operations, update_live_partial_operation
from data_classes import UpdateCompleteLiveOperation, UpdatePartialLiveOPeration
from common_files.binance_utils.orders import GetOrders
from common_files.live.bets import direct_bet_tp_routine, direct_bet_sl_routine
from common_files.live.bets import secondary_bet_sl_resolution, SecondaryFinalResolution
from common_files.live.bets import calculate_gain
from common_files.logger import get_logger
from common_files.live.operation_lock import LIVE_OPERATION_LOCK
from common_files.paths import load_json_file, CONFIG_LIVE_FILE


logger_live = get_logger(__name__, log_live=True)


# =============================================================================
# Exceptions
# =============================================================================


class RecoveryError(RuntimeError):
    """
    Raised when an unresolved operation cannot be safely reconciled.

    Recovery errors are intentionally fatal to the startup process.
    The trading engine must not continue when the state of an operation
    cannot be established with sufficient confidence.
    """


# =============================================================================
# Binance position
# =============================================================================


async def get_binance_position(
    client,
    ticker: str,
) -> dict:
    """
    Returns the Binance Futures position for a symbol.

    The function fails closed if Binance does not return a reliable
    position response.
    """

    try:
        positions = await client.futures_position_information(
            symbol=ticker,
        )

        if not positions:
            logger_live.warning(
                "⚠️ [RECOVERY] No position array returned for ticker=%s. "
                "Assuming positionAmt=0.",
                ticker,
            )

            return {
                "symbol": ticker,
                "positionAmt": "0",
            }

        if len(positions) != 1:
            raise RecoveryError(
                f"Unexpected number of Binance positions returned "
                f"for ticker={ticker}: {len(positions)}"
            )

        position = positions[0]

        if position.get("symbol") != ticker:
            raise RecoveryError(
                f"Binance position symbol mismatch: "
                f"expected={ticker}, "
                f"received={position.get('symbol')}"
            )

        if "positionAmt" not in position:
            raise RecoveryError(
                f"Binance position response does not contain "
                f"positionAmt for ticker={ticker}"
            )

        logger_live.info(
            "🔎 [RECOVERY] Binance position retrieved | "
            "ticker=%s | positionAmt=%s",
            ticker,
            position["positionAmt"],
        )

        return position

    except RecoveryError:
        logger_live.exception(
            "❌ [RECOVERY] Invalid Binance position response | "
            "ticker=%s",
            ticker,
        )
        raise

    except Exception as e:
        logger_live.exception(
            "❌ [RECOVERY] Failed to retrieve Binance position | "
            "ticker=%s",
            ticker,
        )

        raise RecoveryError(
            f"Failed to retrieve Binance position "
            f"for ticker={ticker}"
        ) from e


# =============================================================================
# Binance algo order
# =============================================================================


async def get_algo_order(
    client,
    algo_id: int,
) -> dict | None:
    """
    Retrieves a Binance Futures algo order by algo ID.

    Returns None when Binance successfully responds but the algo order
    cannot be found.

    Raises RecoveryError when the Binance request itself fails.
    """

    try:
        response = await client.futures_get_algo_order(
            algoId=algo_id,
        )

        if not response:
            logger_live.warning(
                "⚠️ [RECOVERY] Algo order not found | "
                "algo_id=%s",
                algo_id,
            )
            return None

        logger_live.info(
            "🔎 [RECOVERY] Algo order retrieved | "
            "algo_id=%s | status=%s | "
            "algo_status=%s | actual_order_id=%s",
            algo_id,
            response.get("status"),
            response.get("algoStatus"),
            response.get("actualOrderId"),
        )

        return response

    except Exception as e:
        logger_live.exception(
            "❌ [RECOVERY] Failed to retrieve algo order | "
            "algo_id=%s",
            algo_id,
        )

        raise RecoveryError(
            f"Failed to retrieve Binance algo order "
            f"{algo_id}"
        ) from e


# =============================================================================
# Binance exit order
# =============================================================================


async def recover_from_exit_order(
    client,
    operation: dict,
) -> dict:
    """
    Recovers an operation whose exit order ID is already known.

    The order is retrieved directly from Binance and validated before
    being considered a recoverable completed operation.
    """

    operation_id = operation["operation_id"]
    ticker = operation["ticker"]
    exit_order_id = operation["exit_order_id"]

    logger_live.info(
        "🔎 [RECOVERY] Recovering known exit order | "
        "operation_id=%s | ticker=%s | exit_order_id=%s",
        operation_id,
        ticker,
        exit_order_id,
    )

    try:
        order = await client.futures_get_order(
            symbol=ticker,
            orderId=exit_order_id,
        )

        if not order:
            raise RecoveryError(
                f"Binance returned no data for "
                f"exit_order_id={exit_order_id}"
            )

        # -------------------------------------------------------------
        # Validate identity
        # -------------------------------------------------------------

        returned_symbol = order.get("symbol")

        if returned_symbol != ticker:
            raise RecoveryError(
                f"Exit order symbol mismatch | "
                f"operation_id={operation_id} | "
                f"expected={ticker} | "
                f"received={returned_symbol}"
            )

        returned_order_id = order.get("orderId")

        if returned_order_id is None:
            raise RecoveryError(
                f"Exit order response does not contain orderId | "
                f"exit_order_id={exit_order_id}"
            )

        if int(returned_order_id) != int(exit_order_id):
            raise RecoveryError(
                f"Exit order ID mismatch | "
                f"expected={exit_order_id} | "
                f"received={returned_order_id}"
            )

        # -------------------------------------------------------------
        # Validate execution status
        # -------------------------------------------------------------

        status = order.get("status")

        logger_live.info(
            "🔎 [RECOVERY] Exit order retrieved | "
            "operation_id=%s | "
            "exit_order_id=%s | "
            "status=%s",
            operation_id,
            exit_order_id,
            status,
        )

        if status != "FILLED":
            raise RecoveryError(
                f"Exit order is not FILLED | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id} | "
                f"status={status}"
            )

        # -------------------------------------------------------------
        # Validate execution quantity
        # -------------------------------------------------------------

        executed_qty = order.get("executedQty")

        if executed_qty in (None, "", "0", 0, 0.0):
            raise RecoveryError(
                f"Exit order does not contain a valid executedQty | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id}"
            )

        # -------------------------------------------------------------
        # Validate execution price
        # -------------------------------------------------------------

        avg_price = order.get("avgPrice")

        if avg_price in (None, "", "0", 0, 0.0):
            raise RecoveryError(
                f"Exit order does not contain a valid avgPrice | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id}"
            )

        # -------------------------------------------------------------
        # Validate side
        # -------------------------------------------------------------

        side = order.get("side")

        if side not in ("BUY", "SELL"):
            raise RecoveryError(
                f"Exit order does not contain a valid side | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id} | "
                f"side={side}"
            )

        logger_live.info(
            "🟢 [RECOVERY] Exit order validated | "
            "operation_id=%s | "
            "exit_order_id=%s | "
            "executed_qty=%s | "
            "avg_price=%s",
            operation_id,
            exit_order_id,
            executed_qty,
            avg_price,
        )

        return order

    except RecoveryError:
        logger_live.exception(
            "❌ [RECOVERY] Exit order validation failed | "
            "operation_id=%s | exit_order_id=%s",
            operation_id,
            exit_order_id,
        )
        raise

    except Exception as e:
        logger_live.exception(
            "❌ [RECOVERY] Failed to recover exit order | "
            "operation_id=%s | exit_order_id=%s",
            operation_id,
            exit_order_id,
        )

        raise RecoveryError(
            f"Failed to recover exit order "
            f"{exit_order_id} "
            f"for operation {operation_id}"
        ) from e


# =============================================================================
# Existing order recovery
# =============================================================================


async def recover_from_existing_order(
    client,
    operation: dict,
) -> dict | None:
    """
    Checks whether the existing order_id is actually the order that
    closed the Binance position.
    This is critical for manual exits.
    In a manual close, the database may contain:
        order_id       = 12345
        exit_order_id  = 12345
    The equality does NOT mean that the exit order is unknown.
    We therefore ask Binance whether order_id is FILLED.
    Returns:
        {
            "exit_order": order,
            "outcome": "TIE",
        }
        when the existing order is FILLED.
    Returns:
        None
        when the existing order is not FILLED and recovery must
        continue through TP/SL algo orders.
    """

    operation_id = operation["operation_id"]
    ticker = operation["ticker"]
    order_id = operation["order_id"]

    logger_live.info(
        "🔎 [RECOVERY] Checking existing order as possible exit | "
        "operation_id=%s | ticker=%s | order_id=%s",
        operation_id,
        ticker,
        order_id,
    )

    try:
        order = await client.futures_get_order(
            symbol=ticker,
            orderId=order_id,
        )

        if not order:
            raise RecoveryError(
                f"Binance returned no data for "
                f"order_id={order_id} | "
                f"operation_id={operation_id} | "
                f"ticker={ticker}"
            )

        # -------------------------------------------------------------
        # Validate symbol
        # -------------------------------------------------------------

        returned_symbol = order.get("symbol")

        if returned_symbol != ticker:
            raise RecoveryError(
                f"Order symbol mismatch | "
                f"operation_id={operation_id} | "
                f"expected={ticker} | "
                f"received={returned_symbol}"
            )

        # -------------------------------------------------------------
        # Validate order ID
        # -------------------------------------------------------------

        returned_order_id = order.get("orderId")

        if returned_order_id is None:
            raise RecoveryError(
                f"Order response does not contain orderId | "
                f"operation_id={operation_id} | "
                f"order_id={order_id}"
            )

        if int(returned_order_id) != int(order_id):
            raise RecoveryError(
                f"Order ID mismatch | "
                f"operation_id={operation_id} | "
                f"expected={order_id} | "
                f"received={returned_order_id}"
            )

        status = order.get("status")

        logger_live.info(
            "🔎 [RECOVERY] Existing order retrieved | "
            "operation_id=%s | ticker=%s | "
            "order_id=%s | status=%s | side=%s | "
            "executed_qty=%s | avg_price=%s",
            operation_id,
            ticker,
            order_id,
            status,
            order.get("side"),
            order.get("executedQty"),
            order.get("avgPrice"),
        )

        # -------------------------------------------------------------
        # IMPORTANT:
        #
        # If the existing order is not FILLED, it cannot be the
        # order that closed the position.
        #
        # Only in this case should we continue looking at TP/SL.
        # -------------------------------------------------------------

        if status != "FILLED" or not (order.get("reduceOnly") 
                    or order.get("closePosition")):
            logger_live.info(
                "🔎 [RECOVERY] Existing order is not FILLED | "
                "operation_id=%s | ticker=%s | "
                "order_id=%s | status=%s",
                operation_id,
                ticker,
                order_id,
                status,
            )

            return None

        # -------------------------------------------------------------
        # The position is already CLOSED and this order is FILLED.
        #
        # Therefore this order is the strongest available evidence
        # of the exit.
        #
        # This is the manual-close scenario.
        # -------------------------------------------------------------

        logger_live.warning(
            "🟢 [RECOVERY] Existing FILLED order identified as "
            "the exit order | "
            "operation_id=%s | ticker=%s | "
            "order_id=%s | outcome=TIE",
            operation_id,
            ticker,
            order_id,
        )

        return {
            "exit_order": order,
            "outcome": "TIE",
        }

    except RecoveryError:
        raise

    except Exception as e:
        logger_live.exception(
            "❌ [RECOVERY] Failed to inspect existing order | "
            "operation_id=%s | ticker=%s | order_id=%s",
            operation_id,
            ticker,
            order_id,
        )

        raise RecoveryError(
            f"Failed to inspect existing order "
            f"{order_id} for operation {operation_id}"
        ) from e


# =============================================================================
# Algo-order recovery
# =============================================================================


def _get_actual_order_id(
    algo_order: dict,
) -> int | None:
    """
    Extracts the actual Binance order ID generated when an algo order
    is triggered.
    """

    actual_order_id = algo_order.get("actualOrderId")

    if actual_order_id in (None, "", 0, "0"):
        return None

    try:
        return int(actual_order_id)

    except (TypeError, ValueError) as e:
        raise RecoveryError(
            f"Invalid actualOrderId in algo response: "
            f"{actual_order_id}"
        ) from e


async def recover_from_algo_order(
    client,
    operation: dict,
) -> dict | None:
    """
    Determines which exit algo order was triggered and retrieves
    the corresponding actual Binance order.

    This function is only reached when the existing order_id was
    NOT a FILLED exit order. Returns None when neither algo identifies
    an exit so recovery can inspect account trade history.
    """

    operation_id = operation["operation_id"]
    ticker = operation["ticker"]

    tp_algo_id = operation["tp_algo_id"]
    sl_algo_id = operation["sl_algo_id"]

    logger_live.info(
        "🔎 [RECOVERY] Searching exit algo orders | "
        "operation_id=%s | ticker=%s | "
        "tp_algo_id=%s | sl_algo_id=%s",
        operation_id,
        ticker,
        tp_algo_id,
        sl_algo_id,
    )

    tp_order = await get_algo_order(
        client=client,
        algo_id=tp_algo_id,
    )

    sl_order = await get_algo_order(
        client=client,
        algo_id=sl_algo_id,
    )

    # -----------------------------------------------------------------
    # Determine which algo order actually triggered.
    # -----------------------------------------------------------------

    tp_actual_order_id = (
        _get_actual_order_id(tp_order)
        if tp_order
        else None
    )

    sl_actual_order_id = (
        _get_actual_order_id(sl_order)
        if sl_order
        else None
    )

    # -----------------------------------------------------------------
    # Both triggered is an invalid state for this architecture.
    # -----------------------------------------------------------------

    if (
        tp_actual_order_id is not None
        and sl_actual_order_id is not None
    ):
        raise RecoveryError(
            f"Both TP and SL appear to have triggered | "
            f"operation_id={operation_id} | "
            f"tp_order={tp_actual_order_id} | "
            f"sl_order={sl_actual_order_id}"
        )

    # -----------------------------------------------------------------
    # No actual exit order found.
    # -----------------------------------------------------------------

    if (
        tp_actual_order_id is None
        and sl_actual_order_id is None
    ):
        logger_live.warning(
            "⚠️ [RECOVERY] No triggered TP/SL exit ID found; "
            "checking Binance trade history | operation_id=%s | "
            "ticker=%s",
            operation_id,
            ticker,
        )
        return None

    # -----------------------------------------------------------------
    # Select triggered algo.
    # -----------------------------------------------------------------

    if tp_actual_order_id is not None:

        selected_algo = tp_order
        exit_order_id = tp_actual_order_id
        outcome = "TP"

        logger_live.warning(
            "⚠️ [RECOVERY] TP algo order triggered | "
            "operation_id=%s | "
            "algo_id=%s | "
            "exit_order_id=%s",
            operation_id,
            tp_algo_id,
            exit_order_id,
        )

    else:

        selected_algo = sl_order
        exit_order_id = sl_actual_order_id
        outcome = "SL"

        logger_live.warning(
            "⚠️ [RECOVERY] SL algo order triggered | "
            "operation_id=%s | "
            "algo_id=%s | "
            "exit_order_id=%s",
            operation_id,
            sl_algo_id,
            exit_order_id,
        )

    # -----------------------------------------------------------------
    # Retrieve the actual execution order.
    # -----------------------------------------------------------------

    recovered_operation = operation.copy()

    recovered_operation["exit_order_id"] = exit_order_id

    exit_order = await recover_from_exit_order(
        client=client,
        operation=recovered_operation,
    )

    return {
        "algo_order": selected_algo,
        "exit_order": exit_order,
        "outcome": outcome,
    }


async def recover_from_account_trades(
    client,
    operation: dict,
) -> dict:
    """Recover a flat operation from its matching Binance entry and exit fills."""
    operation_id = operation["operation_id"]
    ticker = operation["ticker"]
    try:
        entry_order_id = int(operation["order_id"])
    except (TypeError, ValueError) as e:
        raise RecoveryError(
            f"Invalid entry order ID for operation_id={operation_id}"
        ) from e
    entry_side = operation.get("side")

    if entry_side not in ("BUY", "SELL"):
        raise RecoveryError(
            f"Invalid entry side for operation_id={operation_id}: "
            f"{entry_side}"
        )

    try:
        entry_date = datetime.fromisoformat(
            str(operation["entry_date"]).replace("Z", "+00:00")
        )
        if entry_date.tzinfo is None:
            entry_date = entry_date.replace(tzinfo=timezone.utc)
        start_time = int(entry_date.timestamp() * 1000)

        trades = await client.futures_account_trades(
            symbol=ticker,
            startTime=start_time,
            limit=1000,
        )
    except RecoveryError:
        raise
    except Exception as e:
        logger_live.exception(
            "❌ [RECOVERY] Failed to retrieve Binance trade history | "
            "operation_id=%s | ticker=%s",
            operation_id,
            ticker,
        )
        raise RecoveryError(
            f"Failed to retrieve Binance trade history for "
            f"operation_id={operation_id}"
        ) from e

    if not trades:
        raise RecoveryError(
            f"No Binance trades found for closed operation | "
            f"operation_id={operation_id} | ticker={ticker}"
        )

    entry_trades = [
        trade
        for trade in trades
        if trade.get("symbol") == ticker
        and str(trade.get("orderId")) == str(entry_order_id)
        and trade.get("side") == entry_side
    ]

    if not entry_trades:
        raise RecoveryError(
            f"Entry fills not found in Binance trade history | "
            f"operation_id={operation_id} | "
            f"entry_order_id={entry_order_id}"
        )

    try:
        entry_quantity = sum(
            (Decimal(str(trade["qty"])) for trade in entry_trades),
            Decimal(0),
        )
        latest_entry_time = max(
            int(trade["time"])
            for trade in entry_trades
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise RecoveryError(
            f"Invalid entry fill data for operation_id={operation_id}"
        ) from e

    if entry_quantity <= 0:
        raise RecoveryError(
            f"Entry fills have no positive quantity | "
            f"operation_id={operation_id}"
        )

    entry_position_sides = {
        trade.get("positionSide")
        for trade in entry_trades
    }
    if len(entry_position_sides) != 1:
        raise RecoveryError(
            f"Inconsistent entry position sides | "
            f"operation_id={operation_id}"
        )
    entry_position_side = next(iter(entry_position_sides))

    exit_side = "SELL" if entry_side == "BUY" else "BUY"
    exit_trades_by_order: dict[int, list[dict]] = {}
    for trade in trades:
        if (
            trade.get("symbol") != ticker
            or trade.get("side") != exit_side
            or trade.get("positionSide") != entry_position_side
        ):
            continue

        try:
            order_id = int(trade["orderId"])
            trade_time = int(trade["time"])
        except (KeyError, TypeError, ValueError) as e:
            raise RecoveryError(
                f"Invalid exit fill identity in trade history | "
                f"operation_id={operation_id}"
            ) from e

        if (
            order_id == entry_order_id
            or trade_time < latest_entry_time
        ):
            continue

        exit_trades_by_order.setdefault(order_id, []).append(trade)

    quantity_tolerance = max(
        Decimal("0.000000000001"),
        entry_quantity * Decimal("0.00000001"),
    )
    matching_orders = []
    for order_id, order_trades in exit_trades_by_order.items():
        try:
            exit_quantity = sum(
                (Decimal(str(trade["qty"])) for trade in order_trades),
                Decimal(0),
            )
        except (KeyError, TypeError, InvalidOperation) as e:
            raise RecoveryError(
                f"Invalid exit fill quantity | operation_id={operation_id} | "
                f"exit_order_id={order_id}"
            ) from e

        if abs(exit_quantity - entry_quantity) <= quantity_tolerance:
            matching_orders.append((order_id, order_trades, exit_quantity))

    if len(matching_orders) != 1:
        raise RecoveryError(
            "Could not uniquely match a full position close in Binance "
            "trade history | "
            f"operation_id={operation_id} | ticker={ticker} | "
            f"matching_orders={len(matching_orders)}"
        )

    exit_order_id, exit_trades, exit_quantity = matching_orders[0]
    recovered_operation = operation.copy()
    recovered_operation["exit_order_id"] = exit_order_id
    exit_order = await recover_from_exit_order(
        client=client,
        operation=recovered_operation,
    )

    try:
        exit_notional = sum(
            (
                Decimal(str(trade["price"]))
                * Decimal(str(trade["qty"]))
                for trade in exit_trades
            ),
            Decimal(0),
        )
        pnl = sum(
            (Decimal(str(trade["realizedPnl"])) for trade in exit_trades),
            Decimal(0),
        )
        commission = sum(
            (
                Decimal(str(trade["commission"]))
                for trade in entry_trades + exit_trades
            ),
            Decimal(0),
        )
        exit_timestamp = max(
            int(trade["time"])
            for trade in exit_trades
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise RecoveryError(
            f"Invalid trade execution data | "
            f"operation_id={operation_id} | "
            f"exit_order_id={exit_order_id}"
        ) from e

    trade_summary = {
        "pnl": float(pnl),
        "commission": float(commission),
        "exit_price": float(exit_notional / exit_quantity),
        "exit_date": datetime.fromtimestamp(
            exit_timestamp / 1000,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    logger_live.warning(
        "🟠 [RECOVERY] Recovered closed position from Binance trades as TIE | "
        "operation_id=%s | ticker=%s | exit_order_id=%s | "
        "exit_quantity=%s",
        operation_id,
        ticker,
        exit_order_id,
        exit_quantity,
    )

    return {
        "exit_order": exit_order,
        "outcome": "TIE",
        "trade_summary": trade_summary,
    }


# =============================================================================
# Closed operation recovery
# =============================================================================


async def recover_closed_operation(
    client,
    operation: dict,
) -> dict:
    """
    Recovers an unresolved database operation whose Binance position
    is already closed.

    Recovery priority:

        1. exit_order_id is different from order_id
           -> retrieve the known exit order.

        2. exit_order_id == order_id
           -> inspect order_id directly.

        3. If order_id is FILLED
           -> it is the exit order (manual close).

        4. If order_id is not FILLED
           -> search TP/SL algo orders.
    """

    operation_id = operation["operation_id"]
    ticker = operation["ticker"]

    order_id = operation["order_id"]
    exit_order_id = operation["exit_order_id"]

    logger_live.info(
        "🔎 [RECOVERY] Recovering closed operation | "
        "operation_id=%s | ticker=%s",
        operation_id,
        ticker,
    )

    # -----------------------------------------------------------------
    # Exit order already recorded and different from entry order.
    # -----------------------------------------------------------------

    if exit_order_id != order_id:

        logger_live.info(
            "🔎 [RECOVERY] Exit order already recorded | "
            "operation_id=%s | exit_order_id=%s",
            operation_id,
            exit_order_id,
        )

        exit_order = await recover_from_exit_order(
            client=client,
            operation=operation,
        )

        return {
            "exit_order": exit_order,
            "outcome": None,
        }

    # -----------------------------------------------------------------
    # IMPORTANT:
    #
    # exit_order_id == order_id does NOT necessarily mean that the
    # exit order is unknown.
    #
    # A manual market close can use a normal Binance order ID.
    #
    # Therefore, inspect the existing order BEFORE querying the
    # TP/SL algo orders.
    # -----------------------------------------------------------------

    logger_live.info(
        "🔎 [RECOVERY] exit_order_id equals order_id. "
        "Checking existing order before TP/SL recovery | "
        "operation_id=%s | ticker=%s | order_id=%s",
        operation_id,
        ticker,
        order_id,
    )

    known_order_recovery = await recover_from_existing_order(
        client=client,
        operation=operation,
    )

    # -----------------------------------------------------------------
    # Existing order was FILLED.
    #
    # This is the manual-close scenario.
    # -----------------------------------------------------------------

    if known_order_recovery is not None:

        logger_live.warning(
            "🟢 [RECOVERY] Existing order recovered as exit | "
            "operation_id=%s | ticker=%s | "
            "exit_order_id=%s | outcome=%s",
            operation_id,
            ticker,
            order_id,
            known_order_recovery.get("outcome"),
        )

        return known_order_recovery

    # -----------------------------------------------------------------
    # Existing order was not FILLED.
    #
    # Only now do we search TP/SL algo orders.
    # -----------------------------------------------------------------

    logger_live.warning(
        "⚠️ [RECOVERY] Existing order is not the exit. "
        "Searching TP/SL algo orders | "
        "operation_id=%s | ticker=%s | "
        "order_id=%s",
        operation_id,
        ticker,
        order_id,
    )

    algo_recovery = await recover_from_algo_order(
        client=client,
        operation=operation,
    )
    if algo_recovery is not None:
        return algo_recovery

    return await recover_from_account_trades(
        client=client,
        operation=operation,
    )


# =============================================================================
# Database operation validation
# =============================================================================


def validate_recovery_operation(
    operation: dict,
) -> None:
    """
    Validates that an unresolved database operation contains all
    fields required by the recovery process.
    """

    required_fields = (
        "operation_id",
        "ticker",
        "order_id",
        "exit_order_id",
        "tp_algo_id",
        "sl_algo_id",
        "exit_price",
    )

    missing_fields = [
        field
        for field in required_fields
        if field not in operation
    ]

    if missing_fields:
        raise RecoveryError(
            "Invalid unresolved operation. "
            f"Missing fields={missing_fields}"
        )

    if operation["operation_id"] is None:
        raise RecoveryError(
            "Recovery operation contains NULL operation_id"
        )

    if not operation["ticker"]:
        raise RecoveryError(
            "Recovery operation contains empty ticker"
        )

    if operation["order_id"] is None:
        raise RecoveryError(
            "Recovery operation contains NULL order_id"
        )

    if operation["exit_order_id"] is None:
        raise RecoveryError(
            "Recovery operation contains NULL exit_order_id"
        )

    if operation["exit_price"] is None:
            raise RecoveryError(
                "Recovery operation contains NULL exit_order_id"
            )


# =============================================================================
# Main reconciliation function
# =============================================================================


async def _verify_active_operations_unlocked(
    client,
    rules_mgr=None,
) -> None:
    """
    Reconciles unresolved database operations against Binance.

    State matrix:

        DB UNRESOLVED
            │
            ├── Binance position OPEN
            │       └── leave operation untouched
            │
            └── Binance position CLOSED
                    │
                    └── recover_closed_operation()

    The recovery process fails closed.
    """

    logger_live.info(
        "🔎 [RECOVERY] Starting active operation reconciliation..."
    )

    try:
        operations = await query_unresolved_operations()

        if operations is None:
            raise RecoveryError(
                "Database returned None while querying "
                "unresolved operations"
            )

        if not operations:
            logger_live.info(
                "🟢 [RECOVERY] No unresolved operations found."
            )
            return

        logger_live.warning(
            "⚠️ [RECOVERY] Found %s unresolved operation(s)",
            len(operations),
        )

        for operation in operations:

            validate_recovery_operation(operation)

            operation_id = operation["operation_id"]
            ticker = operation["ticker"]

            logger_live.info(
                "🔎 [RECOVERY] Verifying operation | "
                "operation_id=%s | ticker=%s",
                operation_id,
                ticker,
            )

            # ---------------------------------------------------------
            # Ask Binance for the current position.
            # ---------------------------------------------------------

            position = await get_binance_position(
                client=client,
                ticker=ticker,
            )

            position_amount_raw = position.get("positionAmt")

            if position_amount_raw is None:
                raise RecoveryError(
                    f"Missing positionAmt | "
                    f"operation_id={operation_id} | "
                    f"ticker={ticker}"
                )

            try:
                position_amount = float(position_amount_raw)

            except (TypeError, ValueError) as e:
                raise RecoveryError(
                    f"Invalid positionAmt={position_amount_raw} | "
                    f"operation_id={operation_id} | "
                    f"ticker={ticker}"
                ) from e

            # ---------------------------------------------------------
            # Position still exists.
            # ---------------------------------------------------------

            if position_amount != 0.0:

                logger_live.info(
                    "🟢 [RECOVERY] Active position confirmed | "
                    "operation_id=%s | ticker=%s | position=%s",
                    operation_id,
                    ticker,
                    position_amount,
                )

                continue

            # ---------------------------------------------------------
            # DB says unresolved, but Binance says position closed.
            # ---------------------------------------------------------

            logger_live.warning(
                "⚠️ [RECOVERY] Position CLOSED while database "
                "is UNRESOLVED | operation_id=%s | ticker=%s",
                operation_id,
                ticker,
            )

            recovery_data = await recover_closed_operation(
                client=client,
                operation=operation,
            )

            # ---------------------------------------------------------
            # Binance state reconstructed.
            # ---------------------------------------------------------

            outcome = recovery_data.get("outcome")
            exit_order = recovery_data["exit_order"].get("orderId")
            # zero in db, recovery process contains failures
            average_price = float(recovery_data["exit_order"].get("avgPrice", 0))

            logger_live.warning(
                "🟡 [RECOVERY] Operation reconstructed successfully | "
                "operation_id=%s | ticker=%s | outcome=%s | "
                "exit_order_id=%s | exit_price=%.6f",
                operation_id,
                ticker,
                outcome,
                exit_order,
                average_price
            )

            # ---------------------------------------------------------
            # TIE EXIT
            #
            # The order was FILLED and the position is closed, but it
            # was not generated by TP/SL.
            #
            # We deliberately do NOT classify it as TP or SL.
            # ---------------------------------------------------------

            if outcome == "TIE":

                logger_live.warning(
                    "🟠 [RECOVERY] Manual exit detected | "
                    "operation_id=%s | ticker=%s | "
                    "exit_order_id=%s | "
                    "The existing FILLED order closed the position.",
                    operation_id,
                    ticker,
                    exit_order,
                )

                trade_summary = recovery_data.get("trade_summary")
                if trade_summary is None:
                    order_data = GetOrders(client=client)
                    retrieve_data = await order_data.get_order_execution(
                        symbol=ticker,
                        order_id=exit_order,
                    )
                    if not retrieve_data:
                        raise RecoveryError(
                            "Could not retrieve TIE execution totals | "
                            f"operation_id={operation_id} | "
                            f"exit_order_id={exit_order}"
                        )
                    pnl = float(retrieve_data["realized_pnl"])
                    commission = float(retrieve_data["commission"])
                    tie_exit_date = datetime.now(
                        tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    tie_exit_price = average_price
                else:
                    pnl = trade_summary["pnl"]
                    commission = trade_summary["commission"]
                    tie_exit_date = trade_summary["exit_date"]
                    tie_exit_price = trade_summary["exit_price"]

                # update the partial_operation first
                tie_gain = await calculate_gain(pnl=pnl, commission=commission, operation_id=operation_id)
                update_partial_record = UpdatePartialLiveOPeration(
                    exit_order_id=exit_order, 
                    exit_date=tie_exit_date,
                    exit_price=tie_exit_price,
                    outcome="TIE",
                    gain=tie_gain,
                    pnl=pnl,
                    commission=commission,
                    operation_id=operation_id
                )
                await update_live_partial_operation(update_record=update_partial_record)
                # now with partial position completed, close the complete_operation
                await SecondaryFinalResolution(
                    operation_id=operation_id,
                    symbol=ticker, 
                    outcome="TIE").close_operation()
                
                # continue breaks this position and goes on with next
                continue

            # ---------------------------------------------------------
            # TP/SL recovery
            # ---------------------------------------------------------

            bet_mode = await query_bet_mode(
                operation_id=operation_id
            )

            capital = await query_capital(
                operation_id=operation_id
            )

            leverage = load_json_file(
                CONFIG_LIVE_FILE
            )["leverage"]

            exit_date = datetime.now(
                tz=timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            # =========================================================
            # DIRECT BET
            # =========================================================

            if bet_mode == "D":

                # -----------------------------------------------------
                # Direct SL
                # -----------------------------------------------------

                if outcome == "SL":

                    await direct_bet_sl_routine(
                        client=client,
                        rules_mgr=rules_mgr,
                        symbol=ticker,
                        operation_id=operation_id,
                        exit_order_id=exit_order,
                        capital=capital,
                        leverage=leverage,
                        exit_date=exit_date,
                    )

                    logger_live.info(
                        "☑️ [RECOVERY FUNCTION] Position is on SL. "
                        "Direct bet SL routine executed | "
                        "symbol=%s | operation_id=%d | "
                        "exit_order=%d | capital=%.4f | "
                        "leverage=%d | exit_date=%s",
                        ticker,
                        operation_id,
                        exit_order,
                        capital,
                        leverage,
                        exit_date,
                    )

                # -----------------------------------------------------
                # Direct TP
                # -----------------------------------------------------

                elif outcome == "TP":

                    await direct_bet_tp_routine(
                        client=client,
                        symbol=ticker,
                        operation_id=operation_id,
                        exit_order_id=exit_order,
                        capital=capital,
                        leverage=leverage,
                        exit_date=exit_date,
                    )

                    logger_live.info(
                        "☑️ [RECOVERY FUNCTION] Position is on TP. "
                        "Direct bet TP routine executed | "
                        "symbol=%s | operation_id=%d | "
                        "exit_order=%d | capital=%.4f | "
                        "leverage=%d | exit_date=%s",
                        ticker,
                        operation_id,
                        exit_order,
                        capital,
                        leverage,
                        exit_date,
                    )

            # =========================================================
            # INDIRECT / SECONDARY BET
            # =========================================================

            elif bet_mode == "I":

                # -----------------------------------------------------
                # Secondary SL
                # -----------------------------------------------------

                if outcome == "SL":

                    order_main = GetOrders(
                        client=client
                    )

                    order_data = await order_main.get_order(
                        symbol=ticker,
                        order_id=exit_order,
                    )

                    side = order_data.get("side")

                    order_trades = (
                        await order_main.get_order_execution(
                            symbol=ticker,
                            order_id=exit_order,
                        )
                    )

                    pnl = float(
                        order_trades.get("realized_pnl")
                    )

                    commission = float(
                        order_trades.get("commission")
                    )

                    gain = await calculate_gain(
                        pnl=pnl,
                        commission=commission,
                        operation_id=operation_id,
                    )

                    await secondary_bet_sl_resolution(
                        client=client,
                        rules_mgr=rules_mgr,
                        symbol=ticker,
                        side=side,
                        exit_order_id=exit_order,
                        exit_price=0,
                        gain=gain,
                        pnl=pnl,
                        commission=commission,
                        operation_id=operation_id,
                    )

                    logger_live.info(
                        "☑️ [RECOVERY FUNCTION] "
                        "Secondary SL routine was executed"
                    )

                # -----------------------------------------------------
                # Secondary TP
                # -----------------------------------------------------

                elif outcome == "TP":

                    await SecondaryFinalResolution(
                        operation_id=operation_id,
                        symbol=ticker,
                        outcome="ITP",
                    ).close_operation()

                    logger_live.info(
                        "☑️ [RECOVERY FUNCTION] "
                        "Secondary TP routine was executed"
                    )

        logger_live.info(
            "🟢 [RECOVERY] Active operation reconciliation completed."
        )

    except RecoveryError:

        logger_live.exception(
            "🚨 [RECOVERY] Reconciliation failed. "
            "Trading engine MUST remain stopped."
        )

        raise

    except Exception as e:

        logger_live.exception(
            "🚨 [RECOVERY] Unexpected reconciliation failure. "
            "Trading engine MUST remain stopped."
        )

        raise RecoveryError(
            "Unexpected failure during active operation "
            "reconciliation"
        ) from e


async def verify_active_operations(
    client,
    rules_mgr=None,
) -> None:
    async with LIVE_OPERATION_LOCK:
        await _verify_active_operations_unlocked(
            client=client,
            rules_mgr=rules_mgr,
        )


# =============================================================================
# Test / standalone execution
# =============================================================================


async def main():
    import os

    from binance import AsyncClient

    api_key = os.environ.get(
        "BINANCE_API_KEY",
        "",
    ).strip('"' "'")

    api_secret = os.environ.get(
        "BINANCE_API_SECRET",
        "",
    ).strip('"' "'")

    client = await AsyncClient.create(
        api_key=api_key,
        api_secret=api_secret,
    )

    try:

        res = await client.futures_position_information(
            symbol="BELUSDT"
        )

        print(res)

    finally:

        await client.close_connection()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())