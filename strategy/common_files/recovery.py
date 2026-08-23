# invercrypto/strategy/common_files/live/recovery.py

from __future__ import annotations
from datetime import datetime, timezone

from database import query_unresolved_operations, query_bet_mode, query_capital
from common_files.binance_utils.orders import GetOrders
from common_files.live.bets import direct_bet_tp_routine, direct_bet_sl_routine
from common_files.live.bets import secondary_bet_sl_resolution, SecondaryFinalResolution
from common_files.live.bets import calculate_gain
from common_files.logger import get_logger
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

    Args:
        client:
            Binance AsyncClient instance.

        ticker:
            Binance symbol, e.g. BTCUSDT.

    Returns:
        Binance position dictionary.

    Raises:
        RecoveryError:
            If Binance cannot provide a reliable position state.
    """

    try:
        positions = await client.futures_position_information(
            symbol=ticker,
        )

        if not positions:
            logger_live.warning(
                "⚠️ [RECOVERY] No position array returned for ticker=%s. Assuming positionAmt=0.",
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

    Args:
        client:
            Binance AsyncClient instance.

        algo_id:
            Binance algo order ID.

    Returns:
        Algo order dictionary or None.
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

    Args:
        client:
            Binance AsyncClient instance.

        operation:
            Operation retrieved from the database.

    Returns:
        Dictionary containing the recovered Binance order.

    Raises:
        RecoveryError:
            If the order cannot be safely recovered.
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

        if executed_qty is None:
            raise RecoveryError(
                f"Exit order does not contain executedQty | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id}"
            )

        # -------------------------------------------------------------
        # Validate execution price
        #
        # avgPrice is normally available for Futures orders.
        # If Binance returns an empty/zero value, do not guess.
        # -------------------------------------------------------------

        avg_price = order.get("avgPrice")

        if avg_price in (None, "", "0", 0, 0.0):
            raise RecoveryError(
                f"Exit order does not contain a valid avgPrice | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id}"
            )

        side = order.get("side")

        if side not in ("BUY", "SELL"):
            raise RecoveryError(
                f"Exit order does not contain a valid side | "
                f"operation_id={operation_id} | "
                f"exit_order_id={exit_order_id}"
                f"side retrieved: {side}"
            )

        logger_live.info(
            "🟢 [RECOVERY] Exit order validated | "
            "operation_id=%s | "
            "exit_order_id=%s | "
            "executed_qty=%s | "
            "avg_price=%s | "
            "pnl=%.4f | "
            "commission=%.4f",
            operation_id,
            exit_order_id,
            executed_qty,
            avg_price
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
) -> dict:
    """
    Determines which exit algo order was triggered and retrieves
    the corresponding actual Binance order.

    This function does NOT update the database.

    It only reconstructs the Binance-side state.

    Args:
        client:
            Binance AsyncClient instance.

        operation:
            Unresolved database operation.

    Returns:
        Dictionary containing:

            {
                "algo_order": ...,
                "exit_order": ...
            }

    Raises:
        RecoveryError:
            If Binance cannot provide enough information to determine
            the actual exit.
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
    #
    # actualOrderId is the strongest evidence that the conditional
    # order actually generated an execution order.
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
        raise RecoveryError(
            f"No recoverable exit order found in TP/SL algo orders | "
            f"operation_id={operation_id} | "
            f"ticker={ticker}"
        )

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

    Two scenarios exist:

        1. exit_order_id is already known.
        2. exit_order_id is still equal to order_id.

    Returns:
        Recovery information obtained from Binance.
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
    # Exit order already recorded.
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
    # Exit order is unknown.
    # -----------------------------------------------------------------

    logger_live.warning(
        "⚠️ [RECOVERY] Exit order unknown | "
        "operation_id=%s | ticker=%s | "
        "entry_order_id=%s",
        operation_id,
        ticker,
        order_id,
    )

    return await recover_from_algo_order(
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


# =============================================================================
# Main reconciliation function
# =============================================================================


async def verify_active_operations(
    client,
    rules_mgr=None,
) -> None:
    """
    Reconciles unresolved database operations against Binance.

    This function MUST complete successfully before the trading engine
    is allowed to execute new operations.

    State matrix:

        DB UNRESOLVED
            │
            ├── Binance position OPEN
            │       └── leave operation untouched
            │
            └── Binance position CLOSED
                    │
                    └── recover_closed_operation()

    IMPORTANT:

        This function intentionally fails closed.

        If one unresolved operation cannot be reconciled with confidence,
        the exception propagates and the trading engine must not continue.
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
            # IMPORTANT:
            #
            # At this point we have reconstructed Binance's state,
            # but we intentionally do NOT update SQLite here.
            #
            # The database update should go through the existing
            # centralized operation-resolution function.
            # ---------------------------------------------------------
            outcome = recovery_data.get("outcome")
            exit_order = recovery_data["exit_order"].get("orderId")
            logger_live.warning(
                "🟡 [RECOVERY] Operation reconstructed successfully | "
                "operation_id=%s | ticker=%s | outcome=%s | "
                "exit_order_id=%s",
                operation_id,
                ticker,
                outcome,
                exit_order,
            )
            # now, let's analize if it is a direct or secodary bet
            # and if it is sl or tp
            bet_mode = await query_bet_mode(operation_id=operation_id)
            # and retrieve missing information from db
            capital = await query_capital(operation_id=operation_id)
            leverage = load_json_file(CONFIG_LIVE_FILE)["leverage"]
            exit_date = datetime.now(tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if bet_mode == "D": # direct bet stage
                if outcome == "SL": # direct bet sl
                    await direct_bet_sl_routine(
                        client=client,
                        rules_mgr=rules_mgr,
                        symbol=ticker,
                        operation_id=operation_id,
                        exit_order_id=exit_order,
                        capital=capital,
                        leverage=leverage,
                        exit_date=exit_date
                    )
                    logger_live.info("☑️ [RECOVERY FUNCTION] position is on SL, routine from"
                                     "direct bet sl was executed with next values:"
                                     "symbol: %s | operation_id: %d | exit_order: %d |"
                                     "capital: %.4f | leverage: %d | exit date: %s",
                                     ticker,
                                     operation_id,
                                     exit_order,
                                     capital,
                                     leverage,
                                     exit_date)
                elif outcome == "TP": # direct tp
                    await direct_bet_tp_routine(
                        client=client,
                        symbol=ticker,
                        operation_id=operation_id,
                        exit_order_id=exit_order,
                        capital=capital,
                        leverage=leverage,
                        exit_date=exit_date
                    )   
                    logger_live.info("☑️ [RECOVERY FUNCTION] position is on TP, routine from"
                            "direct bet tp was executed with next values:"
                            "symbol: %s | operation_id: %d | exit_order: %d |"
                            "capital: %.4f | leverage: %d | exit date: %s",
                            ticker,
                            operation_id,
                            exit_order,
                            capital,
                            leverage,
                            exit_date
                            )
            elif bet_mode == "I": # indirect (secondary) bet
                if outcome == "SL":
                    # retrieve missing data
                    order_main = GetOrders(client=client)
                    order_data = await order_main.get_order(
                        symbol=ticker, order_id=exit_order)
                    side = order_data.get("side")
                    order_trades = await order_main.get_order_execution(
                        symbol=ticker,
                        order_id=exit_order)
                    pnl = float(order_trades.get("realized_pnl"))
                    commission = float(order_trades.get("commission"))
                    gain = await calculate_gain(pnl=pnl, 
                                                commission=commission,
                                                operation_id=operation_id)
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
                        operation_id=operation_id
                    )        
                    logger_live.info("☑️ [RECOVERY FUNCTION] secondary SL routine was executed")
                elif outcome == "TP": # Indirect TP
                    await SecondaryFinalResolution(
                        operation_id=operation_id,
                        symbol=ticker,
                        outcome="ITP"
                    ).close_operation()
                    logger_live.info("☑️ [RECOVERY FUNCTION] secondary TP routine was executed")

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
            "Unexpected failure during active operation reconciliation"
        ) from e

async def main():
    import os
    from binance import AsyncClient

    api_key = os.environ.get("BINANCE_API_KEY", "").strip('"' "'")
    api_secret = os.environ.get("BINANCE_API_SECRET", "").strip('"' "'")

    # Correct async instantiation
    client = await AsyncClient.create(
        api_key=api_key,
        api_secret=api_secret,
    )
    
    try:
        res = await client.futures_position_information(symbol="BELUSDT")
        print(res)
    finally:
        # Good practice to close the connection socket cleanly
        await client.close_connection()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())