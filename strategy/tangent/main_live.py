import asyncio
import os
from binance import AsyncClient, BinanceSocketManager
from common_files.binance_utils.orders import SymbolRulesManager
from common_files.live.bets import entries_pipeline, verify_bet_result, bet_time_expiration_handler
from common_files.logger import get_logger
from common_files.paths import load_json_file, CONFIG_LIVE_FILE
from utils.timing import wait_for_time_trigger

# init logger
logger = get_logger(__name__, log_live=True)

async def start_user_stream(client, rules_mgr):
    """
    Maintains the Binance Futures user-data WebSocket.

    The stream is intentionally kept independent from the main
    execution loop. If Binance disconnects or the stream fails,
    the supervisor will restart it.
    """

    bsm = BinanceSocketManager(client)
    user_socket = bsm.futures_user_socket()

    try:
        logger.info(
            "Starting Binance Futures user stream. Task=%s",
            asyncio.current_task().get_name(),
        )

        async with user_socket as stream:

            logger.info(
                "Binance Futures WebSocket connected. Task=%s",
                asyncio.current_task().get_name(),
            )

            while True:

                msg = await stream.recv()

                if msg.get("e") != "ORDER_TRADE_UPDATE":
                    continue

                logger.info(
                    "ORDER_TRADE_UPDATE received: symbol=%s",
                    msg.get("o", {}).get("s"),
                )

                await verify_bet_result(
                    msg=msg,
                    client=client,
                    rules_mgr=rules_mgr,
                )

    except asyncio.CancelledError:

        task = asyncio.current_task()

        logger.warning(
            "USER STREAM CANCELLED! "
            "task=%s, cancelling=%s, "
            "task_done=%s, task_cancelled=%s",
            task.get_name() if task else None,
            task.cancelling() if task else None,
            task.done() if task else None,
            task.cancelled() if task else None,
        )

        raise

    except Exception:

        logger.exception(
            "USER STREAM FAILED WITH EXCEPTION."
        )

        raise

    finally:

        logger.info(
            "Binance Futures user stream closed."
        )

async def user_stream_supervisor(client, rules_mgr):
    """
    Keeps the Binance Futures user stream alive.

    If the WebSocket fails, it is restarted automatically.
    """

    while True:

        try:

            logger.info(
                "Starting Binance Futures user stream supervisor."
            )

            await start_user_stream(
                client=client,
                rules_mgr=rules_mgr,
            )

        except asyncio.CancelledError:

            logger.info(
                "User stream supervisor cancelled."
            )

            raise

        except Exception:

            logger.exception(
                "❌ User stream crashed. "
                "Restarting in 5 seconds..."
            )

            await asyncio.sleep(5)

async def time_expiration_monitor(client):
    """
    Continuously monitors unresolved operations and closes
    operations that exceed the configured maximum lifetime.
    """
    while True:
        try:
            await bet_time_expiration_handler(client=client)

        except asyncio.CancelledError:
            logger.info(
                "Time expiration monitor cancelled."
            )
            raise

        except Exception:
            logger.exception(
                "❌ Time expiration monitor failed."
            )

        await asyncio.sleep(5)

async def main():

    config = load_json_file(CONFIG_LIVE_FILE)

    target_hour = config["target_hours"]
    target_minute = config["target_minutes"]
    target_second = config["target_seconds"]

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    client = await AsyncClient.create(
        api_key=api_key,
        api_secret=api_secret,
    )

    try:

        # ---------------------------------------------------------
        # Initialize exchange rules
        # ---------------------------------------------------------

        while True:

            try:

                rules_mgr = await SymbolRulesManager.create(
                    client=client,
                    retries=5,
                    retry_delay=1.0,
                )

                logger.info(
                    "✅ SymbolRulesManager initialized successfully."
                )

                break

            except Exception:

                logger.exception(
                    "❌ Unable to initialize SymbolRulesManager. "
                    "Retrying in 5 seconds..."
                )

                await asyncio.sleep(5)

        # ---------------------------------------------------------
        # Independent Background process
        # ---------------------------------------------------------

        user_stream_task = asyncio.create_task(
            user_stream_supervisor(
                client=client,
                rules_mgr=rules_mgr,
            ),
            name="binance-user-stream",
        )

        expiration_task = asyncio.create_task(
        time_expiration_monitor(client=client),
        name="time-expiration-monitor",
    )

        # ---------------------------------------------------------
        # Main execution loop
        # ---------------------------------------------------------

        while True:

            # -----------------------------------------------------
            # 1. Wait for execution window
            # -----------------------------------------------------

            await wait_for_time_trigger(
                target_hour=target_hour,
                target_minute=target_minute,
                target_second=target_second,
            )

            # -----------------------------------------------------
            # 2. Execute strategy
            # -----------------------------------------------------

            try:

                await entries_pipeline(
                    client=client,
                    rules_mgr=rules_mgr,
                )

            except Exception:

                logger.exception(
                    "❌ Entries pipeline failed. "
                    "Returning to execution loop."
                )

    finally:

        logger.info(
            "Shutting down trading engine..."
        )

        # ---------------------------------------------------------
        # Stop user stream
        # ---------------------------------------------------------

        user_stream_task.cancel()

        try:

            await user_stream_task

        except asyncio.CancelledError:

            pass

        # ---------------------------------------------------------
        # Close Binance client
        # ---------------------------------------------------------

        await client.close_connection()

        logger.info(
            "Trading engine shutdown completed."
        )
           

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n🛑 Simulator runtime manually terminated safely "
            "(user key press). Standing down."
        )
